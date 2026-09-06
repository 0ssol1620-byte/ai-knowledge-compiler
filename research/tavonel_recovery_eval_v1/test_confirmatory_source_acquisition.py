from __future__ import annotations

import json
from pathlib import Path

import pytest

import confirmatory_source_acquisition as a


def test_contract_is_150_150_outcome_blind_and_dart_secondary():
    value = a.source_contract()
    assert value["primary_stage1_pages"] == 300
    assert value["primary_family_quotas"] == {"drdocbench": 150, "sec": 150}
    assert value["scientific_outcomes_used_to_define_sources"] is False
    assert value["secondary_external_validity"]["dart"] == {
        "quota": 100,
        "included_in_primary_result": False,
        "required": False,
    }
    body = {key: item for key, item in value.items() if key != "source_contract_digest"}
    assert value["source_contract_digest"] == a._digest(body)


def test_plan_does_not_open_fresh_sources(monkeypatch, tmp_path):
    monkeypatch.setattr(a, "PRIMARY_ATTESTATION", tmp_path / "primary.json")
    monkeypatch.setattr(a, "STRONG_ATTESTATION", tmp_path / "strong.json")
    value = a.plan()
    assert value["network_acquisition_currently_authorized"] is False
    assert value["fresh_source_bytes_read"] is False
    assert value["primary_family_quotas"] == {"drdocbench": 150, "sec": 150}


def test_qualification_gate_refuses_before_network(monkeypatch, tmp_path):
    monkeypatch.setattr(a, "PRIMARY_ATTESTATION", tmp_path / "missing-primary.json")
    monkeypatch.setattr(a, "STRONG_ATTESTATION", tmp_path / "missing-strong.json")
    called = False

    def forbidden_http(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("network must not be reached")

    monkeypatch.setattr(a, "_http_get", forbidden_http)
    with pytest.raises(a.SourceAcquisitionRefused, match="primary runtime qualification is missing"):
        a.acquire_sec_index_inventory()
    assert called is False


def test_sec_user_agent_must_be_declared(monkeypatch):
    monkeypatch.delenv(a.SEC_USER_AGENT_ENV, raising=False)
    with pytest.raises(a.SourceAcquisitionRefused, match=a.SEC_USER_AGENT_ENV):
        a._sec_user_agent()
    monkeypatch.setenv(a.SEC_USER_AGENT_ENV, "TAVONEL Research research@example.org")
    assert a._sec_user_agent().endswith("@example.org")


def test_sec_master_index_parsing_filters_forms_and_frozen_dates():
    text = "\n".join(
        (
            "CIK|Company Name|Form Type|Date Filed|Filename",
            "1001|Alpha Corp|10-Q|2026-05-05|edgar/data/1001/0000001001-26-000001.txt",
            "1002|Beta Corp|8-K|2026-05-06|edgar/data/1002/0000001002-26-000002.txt",
            "1003|Gamma Corp|10-K|2026-08-28|edgar/data/1003/0000001003-26-000003.txt",
            "1004|Too Late Corp|10-Q|2026-08-29|edgar/data/1004/0000001004-26-000004.txt",
        )
    )
    rows = a.parse_sec_master_index(text)
    assert [(row.cik, row.form) for row in rows] == [("1001", "10-Q"), ("1003", "10-K")]


def test_sec_filing_prefilter_is_deterministic_and_order_independent(monkeypatch):
    monkeypatch.setattr(a, "SEC_PREFILTER_COUNT", 3)
    rows = tuple(
        a.SecFiling(
            cik=str(1000 + index),
            company=f"Company {index}",
            form="10-Q" if index % 2 else "10-K",
            filed_date="2026-06-01",
            archive_filename=f"edgar/data/{1000 + index}/filing-{index}.txt",
        )
        for index in range(8)
    )
    left = a.preselect_sec_filings(rows)
    right = a.preselect_sec_filings(tuple(reversed(rows)))
    assert [row.stable_id for row in left] == [row.stable_id for row in right]
    assert len(left) == 3


def test_sec_prefilter_shortfall_is_fail_closed(monkeypatch):
    monkeypatch.setattr(a, "SEC_PREFILTER_COUNT", 2)
    row = a.SecFiling("1", "One", "10-Q", "2026-06-01", "edgar/data/1/one.txt")
    with pytest.raises(a.SourceAcquisitionRefused, match="below frozen prefilter count"):
        a.preselect_sec_filings((row,))


def test_sec_primary_document_uses_exact_form_lowest_sequence_then_filename():
    raw = b"""<SUBMISSION>\n<DOCUMENT>\n<TYPE>EX-99\n<SEQUENCE>1\n<FILENAME>x.htm\n<TEXT>wrong</TEXT>\n</DOCUMENT>\n<DOCUMENT>\n<TYPE>10-Q\n<SEQUENCE>3\n<FILENAME>b.htm\n<TEXT>later</TEXT>\n</DOCUMENT>\n<DOCUMENT>\n<TYPE>10-Q\n<SEQUENCE>2\n<FILENAME>a.htm\n<TEXT><html>primary</html></TEXT>\n</DOCUMENT>\n</SUBMISSION>"""
    value = a.extract_sec_primary_document(raw, "10-Q")
    assert value["sequence"] == 2
    assert value["filename"] == "a.htm"
    assert value["content"] == b"<html>primary</html>"
    assert value["content_sha256"] == a._sha_bytes(value["content"])


def test_drdoc_tree_uses_lfs_sha_and_separates_evaluator_paths():
    revision = "a" * 40
    tree = [
        {
            "path": "dev/medicine/doc-uuid/images/page_12.jpg",
            "lfs": {"oid": "b" * 64},
        },
        {"path": "dev/medicine/doc-uuid/json/page_12.json"},
        {"path": "dev/medicine/doc-uuid/mds/page_12.md"},
    ]
    candidates, evaluator = a.drdocbench_inventory_from_tree(tree, resolved_revision=revision)
    assert len(candidates) == 1
    row = candidates[0]
    assert row["source_sha256"] == "sha256:" + "b" * 64
    assert row["family_id"] == "drdocbench:doc-uuid"
    assert row["metadata"] == {"subject": "medicine", "page_number": 12}
    assert "json" not in row["metadata"] and "markdown" not in row["metadata"]
    assert evaluator[row["page_id"]] == {
        "json": "dev/medicine/doc-uuid/json/page_12.json",
        "markdown": "dev/medicine/doc-uuid/mds/page_12.md",
    }


def test_drdoc_tree_refuses_untransportable_image_digest():
    with pytest.raises(a.SourceAcquisitionRefused, match="transportable sha256"):
        a.drdocbench_inventory_from_tree(
            [{"path": "dev/math/doc/images/page_1.jpg", "lfs": {"oid": "git-sha1"}}],
            resolved_revision="a" * 40,
        )


def test_source_manifest_binds_contract_qualifications_and_no_hidden_content():
    contract = a.source_contract()
    candidate = {
        "source_family": "drdocbench",
        "family_id": "drdocbench:doc",
        "document_id": "doc",
        "page_id": "drdocbench:doc:page-1",
        "source_locator": "https://example.invalid/page.jpg",
        "source_revision": "a" * 40,
        "source_sha256": "sha256:" + "b" * 64,
        "acquisition_identity": "fixture",
        "metadata": {"page_number": 1},
    }
    result = a.build_source_manifest(
        contract=contract,
        candidate_records=[candidate],
        qualification={"primary_attestation_digest": "p", "strong_attestation_digest": "s"},
        source_revisions={"drdocbench": "a" * 40},
    )
    assert result["candidate_count"] == 1
    assert result["scientific_outcomes_observed_during_acquisition"] is False
    assert result["hidden_evaluator_content_in_runtime_manifest"] is False
    body = {key: item for key, item in result.items() if key != "source_manifest_digest"}
    assert result["source_manifest_digest"] == a._digest(body)