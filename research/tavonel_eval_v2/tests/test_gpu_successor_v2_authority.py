from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

NS = Path(__file__).resolve().parents[1]
for sub in ("tools", "source_fact_ir", "endpoint"):
    sys.path.insert(0, str(NS / sub))
sys.path.insert(0, str(NS))

import build_gpu_successor_v2_cohort as cohort  # noqa: E402
import four_link_gate as gate  # noqa: E402
import gpu_successor_v2_four_link_acceptance as acceptance  # noqa: E402
from common import canonical_sha, sha_file  # noqa: E402

SFIR4_PROTOCOL = "SOURCE_FACT_IR_INDEPENDENT_REPLICATION_V4"
ACQUISITION_SCHEMA = "tavonel.sfir4.acquisition_authority.v1"


def _fact(index: int) -> dict:
    return {
        "fact_id": f"f-{index:03d}",
        "kind": "LANGUAGE",
        "state": "REPRESENTED_IN_COMPILED_STATE",
        "representation": "English",
        "witness": {
            "construct": "html",
            "byte_start": 0,
            "byte_end": 4,
            "excerpt": "lang=en",
            "unit_path": ["document", f"node-{index:03d}"],
        },
    }


def _authority_files(tmp_path: Path, count: int = 450):
    acquisition_path = tmp_path / "sfir4-acquisition.json"
    acquisition = {
        "schema": ACQUISITION_SCHEMA,
        "protocol_id": SFIR4_PROTOCOL,
        "admitted": [
            {
                "lineage_id": f"L{index:03d}",
                "family": "git",
                "before_version": "a",
                "after_version": "b",
                "facts": {"before": [], "after": [_fact(index)]},
            }
            for index in range(count)
        ],
    }
    acquisition_path.write_text(json.dumps(acquisition), encoding="utf-8")
    acceptance_path = tmp_path / "sfir4-acceptance.json"
    held = {
        "schema": "tavonel.sfir4.acceptance_authority.v1",
        "protocol_id": SFIR4_PROTOCOL,
        "state": "ACCEPTED",
        "verdict": "PASS",
        "acquisition": str(acquisition_path),
        "acquisition_sha256": sha_file(acquisition_path),
    }
    acceptance_path.write_text(json.dumps(held), encoding="utf-8")
    return acquisition_path, acceptance_path, held


def test_missing_sfir4_verifier_fails_closed(tmp_path):
    acquisition_path, acceptance_path, _ = _authority_files(tmp_path)
    with pytest.raises(cohort.V2AuthorityRefused, match="no SFIR4 acceptance verifier"):
        cohort.build_authorized_manifest(
            acquisition_path=acquisition_path,
            acceptance_path=acceptance_path,
            acceptance_sha256=sha_file(acceptance_path),
            expected_protocol_id=SFIR4_PROTOCOL,
            expected_acquisition_schema=ACQUISITION_SCHEMA,
        )


def test_exact_acceptance_digest_and_acquisition_schema_are_mandatory(tmp_path):
    acquisition_path, acceptance_path, held = _authority_files(tmp_path)
    with pytest.raises(cohort.V2AuthorityRefused, match="digest mismatch"):
        cohort.build_authorized_manifest(
            acquisition_path=acquisition_path,
            acceptance_path=acceptance_path,
            acceptance_sha256="sha256:" + "0" * 64,
            expected_protocol_id=SFIR4_PROTOCOL,
            expected_acquisition_schema=ACQUISITION_SCHEMA,
            verifier=lambda _path: held,
        )
    with pytest.raises(cohort.V2AuthorityRefused, match="acquisition schema"):
        cohort.build_authorized_manifest(
            acquisition_path=acquisition_path,
            acceptance_path=acceptance_path,
            acceptance_sha256=sha_file(acceptance_path),
            expected_protocol_id=SFIR4_PROTOCOL,
            expected_acquisition_schema="wrong.schema",
            verifier=lambda _path: held,
        )


def test_authorized_manifest_is_fresh_sfir4_bound_and_deterministic(tmp_path):
    acquisition_path, acceptance_path, held = _authority_files(tmp_path, count=451)
    kwargs = dict(
        acquisition_path=acquisition_path,
        acceptance_path=acceptance_path,
        acceptance_sha256=sha_file(acceptance_path),
        expected_protocol_id=SFIR4_PROTOCOL,
        expected_acquisition_schema=ACQUISITION_SCHEMA,
        verifier=lambda _path: held,
    )
    first = cohort.build_authorized_manifest(**kwargs)
    second = cohort.build_authorized_manifest(**kwargs)
    assert canonical_sha(first) == canonical_sha(second)
    assert first["schema"] == cohort.MANIFEST_SCHEMA
    assert first["authority_generation"] == "V2_FRESH_FROM_SFIR4_ONLY"
    assert first["historical_authority_reuse"] is False
    assert first["source_sfir4_protocol_id"] == SFIR4_PROTOCOL
    assert first["source_acquisition_schema"] == ACQUISITION_SCHEMA
    assert first["eligible_count"] == first["floor"] == 450
    assert len({fact["lineage_id"] for fact in first["facts"]}) == 450
    assert first["lineages_considered"] == 451
    assert first["feasible"] is True


def test_exactly_one_question_is_hash_selected_per_lineage(tmp_path):
    acquisition_path, acceptance_path, held = _authority_files(tmp_path)
    acquisition = json.loads(acquisition_path.read_text(encoding="utf-8"))
    acquisition["admitted"][0]["facts"]["after"].append(_fact(999))
    acquisition_path.write_text(json.dumps(acquisition), encoding="utf-8")
    held["acquisition_sha256"] = sha_file(acquisition_path)
    acceptance_path.write_text(json.dumps(held), encoding="utf-8")
    manifest = cohort.build_authorized_manifest(
        acquisition_path=acquisition_path,
        acceptance_path=acceptance_path,
        acceptance_sha256=sha_file(acceptance_path),
        expected_protocol_id=SFIR4_PROTOCOL,
        expected_acquisition_schema=ACQUISITION_SCHEMA,
        verifier=lambda _path: held,
    )
    assert manifest["raw_eligible_fact_count"] == 451
    assert manifest["eligible_count"] == 450
    assert len({fact["lineage_id"] for fact in manifest["facts"]}) == 450
    assert manifest["question_selection_digest"].startswith("sha256:")


def _write_v2_manifest_and_gate(tmp_path: Path):
    acquisition_path, acceptance_path, held = _authority_files(tmp_path)
    manifest = cohort.build_authorized_manifest(
        acquisition_path=acquisition_path,
        acceptance_path=acceptance_path,
        acceptance_sha256=sha_file(acceptance_path),
        expected_protocol_id=SFIR4_PROTOCOL,
        expected_acquisition_schema=ACQUISITION_SCHEMA,
        verifier=lambda _path: held,
    )
    manifest["provenance"] = {
        "receipt_stem": cohort.RECEIPT_STEM,
        "run_id": cohort.AUTHORITY_RUN_ID,
        "immutable": True,
    }
    manifest_path = tmp_path / "gpu-successor-v2-universe.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    result = gate.gate(manifest["facts"], floor=450)
    result["manifest"] = str(manifest_path)
    result["manifest_sha256"] = sha_file(manifest_path)
    gate_path = tmp_path / "four-link-gate.json"
    gate_path.write_text(json.dumps(result), encoding="utf-8")
    return manifest_path, gate_path


def test_v2_four_link_acceptance_revalidates_exact_manifest_at_floor(tmp_path):
    manifest_path, gate_path = _write_v2_manifest_and_gate(tmp_path)
    body = acceptance.build(manifest_path=manifest_path, gate_receipt_path=gate_path)
    assert body["state"] == "ACCEPTED"
    assert body["verdict"] == "PASS"
    assert body["eligible_count"] == body["floor"] == 450
    assert body["manifest_sha256"] == sha_file(manifest_path)


def test_v2_acceptance_rejects_historical_or_changed_manifest(tmp_path):
    manifest_path, gate_path = _write_v2_manifest_and_gate(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["historical_authority_reuse"] = True
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(acceptance.V2FourLinkRefused, match="historical"):
        acceptance.build(manifest_path=manifest_path, gate_receipt_path=gate_path)


def test_protocol_declares_no_provider_authority_and_powered_floor_450():
    body = yaml.safe_load(
        (NS / "protocols" / "GPU_SUCCESSOR_STUDY_V2.yaml").read_text(encoding="utf-8")
    )
    assert body["status"] == "FROZEN"
    assert "result-blind" in body["freeze_semantics"]
    assert body["four_link_gate"]["floor"] == 450
    assert body["inferential_design"]["target_lineages"] == 450
    assert body["inferential_design"]["power_basis"]["exact_two_sided_power_at_target"] > 0.90
    assert (
        body["inferential_design"]["deterministic_repeats"]["counted_as_independent_observations"]
        is False
    )
    assert body["budget"]["provider_calls_authorized_by_this_draft"] is False
    assert body["authority"]["missing_verifier_disposition"] == "REFUSE"
    assert body["scientific_separation"]["sfi3_and_sfir1_3"].startswith("historical evidence only")
