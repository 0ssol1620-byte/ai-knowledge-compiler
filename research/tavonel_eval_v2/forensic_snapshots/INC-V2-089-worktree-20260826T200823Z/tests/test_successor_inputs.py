"""Tests for `endpoint/successor_prompt_schema.py` and
`tools/build_successor_cohort.py` — the GPU_SUCCESSOR_STUDY_V1 input contract.

No network, no GPU, no real acquisition artifact: the SFI2 acquisition this
study's real cohort would come from does not exist yet (that held-out study is
running). Every fixture below is a small inline stand-in shaped like one
admitted row of `tavonel.v2.source_fact_ir_heldout.acquisition.v2`'s
`admitted` list, built only from the shapes already declared in
`tools/sfi1_worker.py._extract_pair` and `source_fact_ir/ir.py.SourceFact.as_dict`.

Seven things this file guards, matching the task's definition of done:

1. a currency word in a prompt is refused
2. the two arms differ only in context
3. scorer classes are disjoint from the closed endpoint's
4. a fail-closed fact is excluded from the cohort and counted
5. a cohort below the floor reports infeasible rather than padding
6. the manifest shape satisfies the preflight's own feasibility gate
7. the prompt schema digest is stable across two builds
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

NS = Path(__file__).resolve().parents[1]
for _sub in ("tools", "source_fact_ir", "endpoint"):
    sys.path.insert(0, str(NS / _sub))

import build_successor_cohort as bsc  # noqa: E402
import gpu_successor_preflight as gsp  # noqa: E402
import ir  # noqa: E402
import successor_prompt_schema as sps  # noqa: E402

# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


def _fact(
    *,
    fact_id: str,
    kind: str,
    state: str,
    excerpt: str,
    representation: Any = None,
    policy_ref: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    return {
        "fact_id": fact_id,
        "kind": kind,
        "state": state,
        "witness": {"excerpt": excerpt},
        "representation": representation,
        "policy_ref": policy_ref,
        "reason": reason,
    }


def _admitted_row(
    *, lineage_id: str, after_facts: list[dict[str, Any]], before_version: str | None = "v1"
) -> dict[str, Any]:
    return {
        "lineage_id": lineage_id,
        "family": "fixture_family",
        "after_version": "v2",
        "before_version": before_version,
        "facts": {
            "after": after_facts,
            "before": [],
        },
    }


def _eligible_fact(index: int) -> dict[str, Any]:
    kind = gsp.ELIGIBLE_KINDS[index % len(gsp.ELIGIBLE_KINDS)]
    return _fact(
        fact_id=f"fact-eligible-{index}",
        kind=kind,
        state=ir.REPRESENTED,
        excerpt="some prose that never names the target",
        representation={"target": f"unit-{index}"},
    )


# ---------------------------------------------------------------------------
# 1. a currency word in a prompt is refused
# ---------------------------------------------------------------------------


def test_currency_word_in_prompt_is_refused():
    with pytest.raises(sps.CurrencyLanguageDetected):
        sps.assert_no_forbidden_language("This reflects the current value of the field.")


def test_stale_and_superseded_and_latest_are_also_refused():
    for word in ("stale", "superseded", "latest"):
        with pytest.raises(sps.CurrencyLanguageDetected):
            sps.assert_no_forbidden_language(f"The {word} record states X.")


def test_a_clean_prompt_is_not_refused():
    # must not raise
    sps.assert_no_forbidden_language(sps.SYSTEM_PROMPT)
    for question in sps.QUESTION_BY_KIND.values():
        sps.assert_no_forbidden_language(question)


def test_build_arm_request_refuses_a_question_template_that_would_leak_currency(monkeypatch):
    monkeypatch.setitem(
        sps.QUESTION_BY_KIND, ir.REFERENCE_TARGET, "What is the current reference target?"
    )
    with pytest.raises(sps.CurrencyLanguageDetected):
        sps.build_arm_request(
            arm=sps.ARM_VERIFIED_CURRENT_TYPED,
            kind=ir.REFERENCE_TARGET,
            representation={"target": "x"},
            context_blocks=["[1] some source text"],
        )


# ---------------------------------------------------------------------------
# 2. the two arms differ only in context
# ---------------------------------------------------------------------------


def test_two_arms_differ_only_in_context():
    verified = sps.build_arm_request(
        arm=sps.ARM_VERIFIED_CURRENT_TYPED,
        kind=ir.LANGUAGE,
        representation={"iso": "en"},
        context_blocks=["[1] current-revision source text"],
    )
    stale = sps.build_arm_request(
        arm=sps.ARM_STALE_APPEND_ONLY,
        kind=ir.LANGUAGE,
        representation={"iso": "en"},
        context_blocks=["[1] preceding-revision source text, a different artifact entirely"],
    )
    comparison = sps.assert_arms_identical_except_context(verified, stale)
    assert comparison["identical_except_context"], comparison["mismatches"]
    assert verified.context_blocks != stale.context_blocks
    assert verified.user_prompt != stale.user_prompt
    # the frame (system prompt + question) must never carry currency/revision
    # language; that check does not apply to context_blocks, which are real
    # document content and may legitimately use these words in prose
    sps.assert_no_forbidden_language(verified.system_prompt)
    sps.assert_no_forbidden_language(verified.question)
    sps.assert_no_forbidden_language(stale.question)
    # the arm name itself must never appear in either served prompt
    assert sps.ARM_VERIFIED_CURRENT_TYPED not in verified.user_prompt
    assert sps.ARM_STALE_APPEND_ONLY not in stale.user_prompt
    assert sps.MODEL_REVISION not in verified.user_prompt
    assert sps.MODEL_REVISION not in stale.user_prompt


def test_identical_context_makes_two_arm_requests_field_identical_apart_from_arm_label():
    same_context = ["[1] identical source text"]
    a = sps.build_arm_request(
        arm=sps.ARM_VERIFIED_CURRENT_TYPED,
        kind=ir.APPLICABILITY,
        representation={"scope": "US"},
        context_blocks=same_context,
    )
    b = sps.build_arm_request(
        arm=sps.ARM_STALE_APPEND_ONLY,
        kind=ir.APPLICABILITY,
        representation={"scope": "US"},
        context_blocks=same_context,
    )
    assert a.user_prompt == b.user_prompt
    comparison = sps.assert_arms_identical_except_context(a, b)
    assert comparison["identical_except_context"]


# ---------------------------------------------------------------------------
# 3. scorer classes are disjoint from the closed endpoint's
# ---------------------------------------------------------------------------


def test_scorer_classes_disjoint_from_closed_endpoint():
    result = sps.assert_scorer_classes_disjoint_from_closed_endpoint()
    assert result["disjoint"] is True
    assert result["overlap"] == []
    assert set(sps.SCORER_CLASSES) & set(gsp.FORBIDDEN_SCORER_CLASSES) == set()


def test_scorer_classes_are_exactly_the_protocols_three():
    assert sps.SCORER_CLASSES == (
        "ANSWER_MATCHES_CURRENT",
        "ANSWER_REFUSED",
        "ANSWER_OTHER",
    )


def test_refusal_class_is_its_own_class_distinct_from_wrong():
    assert sps.REFUSAL_CLASS == sps.ANSWER_REFUSED
    assert sps.REFUSAL_CLASS != sps.ANSWER_OTHER
    assert sps.REFUSAL_CLASS in sps.SCORER_CLASSES


# ---------------------------------------------------------------------------
# 4. a fail-closed fact is excluded from the cohort and counted
# ---------------------------------------------------------------------------


def test_unresolved_fact_is_excluded_and_counted():
    unresolved = _fact(
        fact_id="fact-unresolved-1",
        kind=ir.EFFECTIVE_TIME,
        state=ir.UNRESOLVED,
        excerpt="an ambiguous date reference",
        reason="ambiguous locator",
    )
    eligible = _eligible_fact(0)
    row = _admitted_row(lineage_id="lineage-fail-closed", after_facts=[unresolved, eligible])
    eligible_facts, excluded = bsc.eligible_facts_for_row(row)
    assert [f["fact_id"] for f in eligible_facts] == ["fact-eligible-0"]
    assert excluded[bsc.REASON_FAIL_CLOSED_STATE] == 1
    assert sum(excluded.values()) == 1


def test_unrepresented_fact_is_also_fail_closed_and_counted():
    unrepresented = _fact(
        fact_id="fact-unrepresented-1",
        kind=ir.REFERENCE_TARGET,
        state=ir.UNREPRESENTED,
        excerpt="a construct the compiled state never carried",
        reason="no canonical representation",
    )
    row = _admitted_row(lineage_id="lineage-unrepresented", after_facts=[unrepresented])
    eligible_facts, excluded = bsc.eligible_facts_for_row(row)
    assert eligible_facts == []
    assert excluded[bsc.REASON_FAIL_CLOSED_STATE] == 1


def test_ignored_fact_is_excluded_under_its_own_reason_not_fail_closed():
    ignored = _fact(
        fact_id="fact-ignored-1",
        kind=ir.APPLICABILITY,
        state=ir.IGNORED,
        excerpt="declined by predeclared policy",
        policy_ref="policy-do-not-extract-x",
    )
    row = _admitted_row(lineage_id="lineage-ignored", after_facts=[ignored])
    eligible_facts, excluded = bsc.eligible_facts_for_row(row)
    assert eligible_facts == []
    assert excluded[bsc.REASON_IGNORED_BY_POLICY] == 1
    assert excluded[bsc.REASON_FAIL_CLOSED_STATE] == 0


def test_manifest_never_silently_drops_a_fact_every_excluded_one_is_counted():
    facts = [
        _fact(
            fact_id="fact-ineligible-kind",
            kind=ir.CONTENT_TEXT,
            state=ir.REPRESENTED,
            excerpt="plain prose",
            representation={"text": "plain prose"},
        ),
        _fact(
            fact_id="fact-visible-in-text",
            kind=ir.LANGUAGE,
            state=ir.REPRESENTED,
            excerpt="written in en throughout",
            representation="en",
        ),
        _eligible_fact(0),
    ]
    row = _admitted_row(lineage_id="lineage-mixed", after_facts=facts)
    manifest = bsc.build_manifest({"schema": "fixture", "admitted": [row]})
    assert manifest["eligible_count"] == 1
    assert manifest["excluded"][bsc.REASON_INELIGIBLE_KIND] == 1
    assert manifest["excluded"][bsc.REASON_VISIBLE_IN_UNIT_TEXT] == 1
    assert manifest["excluded_total"] == 2
    # nothing vanished: eligible + excluded accounts for every fact seen
    assert manifest["eligible_count"] + manifest["excluded_total"] == len(facts)


# ---------------------------------------------------------------------------
# 5. a cohort below the floor reports infeasible rather than padding
# ---------------------------------------------------------------------------


def test_below_floor_cohort_reports_infeasible_and_does_not_pad():
    row = _admitted_row(
        lineage_id="lineage-small", after_facts=[_eligible_fact(i) for i in range(3)]
    )
    manifest = bsc.build_manifest({"schema": "fixture", "admitted": [row]})
    assert manifest["eligible_count"] == 3
    assert manifest["feasible"] is False
    assert len(manifest["facts"]) == 3  # not padded to the floor
    assert manifest["floor"] == gsp.COHORT_FLOOR


def test_at_floor_cohort_reports_feasible():
    row = _admitted_row(
        lineage_id="lineage-at-floor",
        after_facts=[_eligible_fact(i) for i in range(gsp.COHORT_FLOOR)],
    )
    manifest = bsc.build_manifest({"schema": "fixture", "admitted": [row]})
    assert manifest["eligible_count"] == gsp.COHORT_FLOOR
    assert manifest["feasible"] is True


def test_no_preceding_revision_excludes_every_fact_and_is_counted_not_dropped():
    row = _admitted_row(
        lineage_id="lineage-first-revision",
        after_facts=[_eligible_fact(0), _eligible_fact(1)],
        before_version=None,
    )
    eligible_facts, excluded = bsc.eligible_facts_for_row(row)
    assert eligible_facts == []
    assert excluded[bsc.REASON_NO_PRECEDING_REVISION] == 2


# ---------------------------------------------------------------------------
# 6. the manifest shape satisfies the preflight's own feasibility gate
# ---------------------------------------------------------------------------


def test_manifest_shape_satisfies_the_preflights_cohort_feasibility_gate(tmp_path):
    row = _admitted_row(
        lineage_id="lineage-gate-check",
        after_facts=[_eligible_fact(i) for i in range(gsp.COHORT_FLOOR)],
    )
    manifest = bsc.build_manifest({"schema": "fixture", "admitted": [row]})
    manifest_path = tmp_path / "typed_fact_cohort.json"
    bsc.write_manifest(manifest, manifest_path)

    gate_result = gsp.cohort_feasibility(manifest_path)
    assert gate_result["manifest_present"] is True
    assert gate_result["feasible"] is True
    assert gate_result["eligible_count"] == gsp.COHORT_FLOOR
    assert gate_result["floor"] == gsp.COHORT_FLOOR
    for kind in gsp.ELIGIBLE_KINDS:
        assert gate_result["by_kind"][kind] == manifest["by_kind"][kind]


def test_manifest_shape_below_floor_is_blocked_by_the_preflights_full_gate_run(tmp_path):
    row = _admitted_row(
        lineage_id="lineage-below-floor",
        after_facts=[_eligible_fact(i) for i in range(5)],
    )
    manifest = bsc.build_manifest({"schema": "fixture", "admitted": [row]})
    manifest_path = tmp_path / "typed_fact_cohort.json"
    bsc.write_manifest(manifest, manifest_path)

    #: No receipts directory is redirected any more: the preflight resolves its
    #: two acceptances from explicit paths, so naming none of them is a hard
    #: block and there is nothing for a stale receipt to be found by.
    body = gsp.run(
        manifest=manifest_path,
        model_pin={},
        runtime_image_digest="repo/image@sha256:" + "0" * 64,
    )

    assert body["verdict"] == "BLOCKED"
    assert "G_GSP_COHORT_FEASIBILITY" in body["blocking_gates"]
    assert body["gates"]["G_GSP_COHORT_FEASIBILITY"]["detail"]["eligible_count"] == 5


# ---------------------------------------------------------------------------
# 7. the prompt schema digest is stable across two builds
# ---------------------------------------------------------------------------


def test_prompt_schema_digest_is_stable_across_two_builds():
    first = sps.schema_digest()
    second = sps.schema_digest()
    assert first == second
    assert first.startswith("sha256:")


def test_frozen_contract_round_trips_through_json():
    contract = sps.frozen_contract()
    reparsed = json.loads(json.dumps(contract, sort_keys=True))
    assert reparsed == contract


def test_cohort_manifest_digest_is_stable_across_two_builds_of_the_same_acquisition():
    row = _admitted_row(
        lineage_id="lineage-digest", after_facts=[_eligible_fact(i) for i in range(4)]
    )
    acquisition = {"schema": "fixture", "admitted": [row]}
    first = bsc.build_manifest(acquisition)
    second = bsc.build_manifest(acquisition)
    assert first["facts_digest"] == second["facts_digest"]
    assert first["facts"] == second["facts"]


# ---------------------------------------------------------------------------
# design-must-not-be-the-closed-endpoint: cross-check against the preflight's
# own structural exclusion, using this study's actual constants
# ---------------------------------------------------------------------------


def test_context_budget_is_read_not_restated():
    import context_builder

    assert sps.CONTEXT_BUDGET_TOKENS == context_builder.TOTAL_PROMPT_TOKENS


def test_requires_value_transition_stays_false_in_the_cohort_builder():
    assert bsc.build_manifest({"schema": "fixture", "admitted": []})[
        "requires_value_transition_between_revisions"
    ] is False
    assert gsp.REQUIRES_VALUE_TRANSITION_BETWEEN_REVISIONS is False


# ---------------------------------------------------------------------------
# the real authority is SFI3-bound, immutable and single-writer
# ---------------------------------------------------------------------------


def _sealed_acceptance(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schema": "fixture",
                "provenance": {
                    "receipt_stem": bsc.sfi3_acceptance.STEM,
                    "immutable": True,
                },
            }
        ),
        encoding="utf-8",
    )


def test_authorised_manifest_binds_exact_sfi3_pass_and_acquisition(tmp_path, monkeypatch):
    acquisition = tmp_path / "sfi3-acquisition.json"
    acquisition.write_text(
        json.dumps(
            {
                "schema": bsc.SFI3_ACQUISITION_SCHEMA,
                "admitted": [_admitted_row(lineage_id="sfi3", after_facts=[_eligible_fact(1)])],
            }
        ),
        encoding="utf-8",
    )
    acceptance = tmp_path / "sfi3-acceptance.json"
    _sealed_acceptance(acceptance)
    monkeypatch.setattr(
        bsc.sfi3_acceptance,
        "verify_authority",
        lambda path: {
            "protocol_id": "SOURCE_FACT_IR_HELDOUT_V3",
            "acquisition": str(acquisition),
            "acquisition_sha256": bsc._sha_file(acquisition),
            "measurement_receipt": "score.json",
            "measurement_sha256": "sha256:" + "1" * 64,
            "verdict": "PASS",
        },
    )
    manifest = bsc.build_authorised_manifest(acquisition, acceptance)
    assert manifest["source_sfi3_acceptance"]["protocol_id"] == "SOURCE_FACT_IR_HELDOUT_V3"
    assert manifest["source_sfi3_acceptance"]["verdict"] == "PASS"
    assert manifest["source_acquisition_artifact"]["sha256"] == bsc._sha_file(acquisition)


def test_an_unsealed_sfi3_acceptance_is_refused(tmp_path):
    acceptance = tmp_path / "draft.json"
    acceptance.write_text(json.dumps({"schema": "fixture"}), encoding="utf-8")
    acquisition = tmp_path / "acquisition.json"
    acquisition.write_text("{}", encoding="utf-8")
    with pytest.raises(bsc.SuccessorFreezeRefused, match="not an immutable"):
        bsc.require_sfi3_authority(acquisition, acceptance)


def test_successor_seal_has_one_fixed_authority_and_no_pointer(tmp_path, monkeypatch):
    monkeypatch.setattr(bsc, "build_authorised_manifest", lambda a, s: {"facts": []})
    captured = {}

    def fake_write(stem, body, **kwargs):
        captured.update({"stem": stem, "body": body, **kwargs})
        return {"receipt": "sealed.json", "run_id": kwargs["run_id"]}

    monkeypatch.setattr(bsc, "write_immutable", fake_write)
    written = bsc.seal(tmp_path / "a.json", tmp_path / "s.json")
    assert written["run_id"] == bsc.AUTHORITY_RUN_ID
    assert captured["pointer"] is False
    assert captured["stem"] == bsc.RECEIPT_STEM


def test_a_second_successor_universe_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(bsc, "build_authorised_manifest", lambda a, s: {"facts": []})

    def duplicate(*args, **kwargs):
        raise bsc.ReceiptExists("held")

    monkeypatch.setattr(bsc, "write_immutable", duplicate)
    with pytest.raises(bsc.SuccessorFreezeRefused, match="second authority"):
        bsc.seal(tmp_path / "a.json", tmp_path / "s.json")


def test_fixture_manifest_export_refuses_overwrite(tmp_path):
    path = tmp_path / "manifest.json"
    bsc.write_manifest({"facts": []}, path)
    with pytest.raises(FileExistsError):
        bsc.write_manifest({"facts": ["changed"]}, path)
