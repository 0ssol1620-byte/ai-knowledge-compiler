from __future__ import annotations

import copy
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from research.model_arena_v1.__main__ import main as cli_main
from research.model_arena_v1.examples.fixture_inputs import fixture
from research.model_arena_v1.protocol import (
    approval_signature_payload,
    approval_subject_digest,
    approval_subject_payload,
    compile_bundle,
    file_digest,
    validate_inputs,
)


def codes(report: object) -> set[str]:
    return {issue.code for issue in report.issues}  # type: ignore[attr-defined]


def test_fixture_is_structurally_valid_but_not_public_evidence() -> None:
    prereg, corpus, runs, layers = fixture()
    report = validate_inputs(prereg, corpus, runs, layers)
    assert report.valid, report.as_dict()


def test_calibration_and_final_arena_families_must_be_disjoint() -> None:
    prereg, corpus, runs, layers = fixture()
    corpus[0]["document_family_id"] = corpus[1]["document_family_id"]
    report = validate_inputs(prereg, corpus, runs, layers)
    assert "CALIBRATION_LEAKAGE" in codes(report)


def test_document_family_cannot_cross_router_splits() -> None:
    prereg, corpus, runs, layers = fixture()
    corpus[2]["document_family_id"] = corpus[1]["document_family_id"]
    report = validate_inputs(prereg, corpus, runs, layers)
    assert "FAMILY_SPLIT_LEAKAGE" in codes(report)


def test_duplicate_case_id_is_rejected_even_inside_one_family() -> None:
    prereg, corpus, runs, layers = fixture()
    corpus[2]["case_id"] = corpus[1]["case_id"]
    report = validate_inputs(prereg, corpus, runs, layers)
    assert "DUPLICATE_CASE" in codes(report)


def test_source_artifact_hash_is_recomputed_when_artifact_root_is_supplied(
    tmp_path: Path,
) -> None:
    prereg, corpus, runs, layers = fixture()
    (tmp_path / "case.bin").write_bytes(b"different bytes")
    corpus[1]["artifact_path"] = "case.bin"
    report = validate_inputs(prereg, corpus, runs, layers, artifact_root=tmp_path)
    assert "ARTIFACT_HASH_MISMATCH" in codes(report)


def test_source_artifact_cannot_escape_root_by_traversal(tmp_path: Path) -> None:
    prereg, corpus, runs, layers = fixture()
    corpus[1]["artifact_path"] = "../outside.bin"
    report = validate_inputs(prereg, corpus, runs, layers, artifact_root=tmp_path)
    assert "ARTIFACT_ESCAPE" in codes(report)


def test_source_artifact_cannot_escape_root_by_symlink(tmp_path: Path) -> None:
    prereg, corpus, runs, layers = fixture()
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"outside")
    link = root / "link.bin"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("file symlinks are unavailable on this Windows host")
    corpus[1]["artifact_path"] = "link.bin"
    report = validate_inputs(prereg, corpus, runs, layers, artifact_root=root)
    assert "ARTIFACT_ESCAPE" in codes(report)


def test_every_planned_page_arm_and_repeat_requires_a_receipt() -> None:
    prereg, corpus, runs, layers = fixture()
    runs.pop()
    report = validate_inputs(prereg, corpus, runs, layers)
    assert "INCOMPLETE_ACCOUNTING" in codes(report)


def test_missing_receipt_remains_in_exported_headline_denominator(tmp_path: Path) -> None:
    prereg, corpus, runs, layers = fixture()
    runs.pop()
    compile_bundle(prereg, corpus, runs, layers, tmp_path)
    results = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    batch = next(row for row in results["arms"] if row["arm_id"] == "api-N-P-batch")
    assert batch["planned_pages"] == 3
    assert batch["observed_receipts"] == 2
    assert batch["missing_receipts"] == 1
    assert batch["status_counts"]["MISSING_RECEIPT"] == 1


@pytest.mark.parametrize("repeat", [True, 0, 2, "1"])
def test_repeat_labels_are_exact_bounded_integers(repeat: object) -> None:
    prereg, corpus, runs, layers = fixture()
    runs[0]["repeat"] = repeat
    report = validate_inputs(prereg, corpus, runs, layers)
    assert "REPEAT_LABEL" in codes(report)


def test_unknown_outcome_is_not_accounted_as_a_known_failure() -> None:
    prereg, corpus, runs, layers = fixture()
    runs[0]["status"] = "MAYBE"
    report = validate_inputs(prereg, corpus, runs, layers)
    assert "RUN_STATUS" in codes(report)


def test_failures_also_require_measured_cost_and_latency() -> None:
    prereg, corpus, runs, layers = fixture()
    timeout = next(row for row in runs if row["status"] == "TIMEOUT")
    del timeout["actual_cost_usd"]
    report = validate_inputs(prereg, corpus, runs, layers)
    assert "ATTEMPT_METRIC" in codes(report)


def test_nan_is_rejected_in_run_and_layer_metrics() -> None:
    prereg, corpus, runs, layers = fixture()
    runs[0]["quality"] = float("nan")
    layers[0]["metrics"]["quality"] = float("nan")
    report = validate_inputs(prereg, corpus, runs, layers)
    assert {"SUCCESS_METRIC", "NON_FINITE_METRIC"} <= codes(report)


def test_batch_arm_requires_an_equivalence_receipt() -> None:
    prereg, corpus, runs, layers = fixture()
    del prereg["arms"][1]["batch_equivalence_receipt_sha256"]
    report = validate_inputs(prereg, corpus, runs, layers)
    assert "INVALID_SHA256" in codes(report)


@pytest.mark.parametrize("value", ["false", "yes", 1])
def test_boolean_like_values_never_enable_release(value: object, tmp_path: Path) -> None:
    prereg, corpus, runs, layers = fixture()
    prereg["public_release"]["current_actual_prices"] = value
    corpus[0]["license"]["publication_allowed"] = value
    report = validate_inputs(prereg, corpus, runs, layers)
    assert "STRICT_BOOLEAN" in codes(report)
    manifest = compile_bundle(prereg, corpus, runs, layers, tmp_path)
    assert manifest["release_state"] == "WITHHELD"
    assert "CURRENT_ACTUAL_PRICES_REQUIRED" in manifest["release_reasons"]
    assert "CORPUS_PUBLICATION_RIGHTS_INCOMPLETE" in manifest["release_reasons"]


def test_downstream_arms_hold_retriever_llm_prompt_corpus_and_questions_fixed() -> None:
    prereg, corpus, runs, layers = fixture()
    downstream = [row for row in layers if row["layer"] == "D"]
    downstream[1]["fixed_context"] = copy.deepcopy(downstream[1]["fixed_context"])
    downstream[1]["fixed_context"]["llm_sha256"] = "sha256:" + "d" * 64
    report = validate_inputs(prereg, corpus, runs, layers)
    assert "DOWNSTREAM_CONTEXT_DRIFT" in codes(report)


def test_continuous_update_requires_one_to_five_percent_change() -> None:
    prereg, corpus, runs, layers = fixture()
    ontology = next(row for row in layers if row["layer"] == "E")
    ontology["continuous_update"]["modified_fraction"] = 0.2
    report = validate_inputs(prereg, corpus, runs, layers)
    assert "MODIFIED_FRACTION" in codes(report)


def test_export_keeps_timeout_in_headline_denominator_and_withholds_fixture(tmp_path: Path) -> None:
    prereg, corpus, runs, layers = fixture()
    manifest = compile_bundle(prereg, corpus, runs, layers, tmp_path)
    results = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    batch = next(row for row in results["arms"] if row["arm_id"] == "api-N-P-batch")
    assert batch["planned_pages"] == 3
    assert batch["success_pages"] == 2
    assert batch["end_to_end_effective_score"] < batch["quality_success_only"]
    assert batch["status_counts"]["TIMEOUT"] == 1
    assert manifest["release_state"] == "WITHHELD"
    assert "FIXTURE_NOT_PUBLIC_EVIDENCE" in manifest["release_reasons"]
    schema = json.loads(
        (Path(__file__).parents[1] / "schemas" / "public_manifest.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator(schema).validate(manifest)
    for artifact in manifest["artifacts"].values():
        assert artifact["sha256"] == file_digest(tmp_path / artifact["path"])


def test_digest_strings_without_review_bytes_never_clear_release_gate(tmp_path: Path) -> None:
    prereg, corpus, runs, layers = fixture()
    prereg["public_release"]["reviews"] = {
        name: {"path": f"reviews/{name}.json", "sha256": "sha256:" + "d" * 64}
        for name in ("rights", "ip", "statistical", "claim")
    }
    manifest = compile_bundle(prereg, corpus, runs, layers, tmp_path, artifact_root=tmp_path)
    assert {
        "RIGHTS_REVIEW_BYTES_REQUIRED",
        "IP_REVIEW_BYTES_REQUIRED",
        "STATISTICAL_REVIEW_BYTES_REQUIRED",
        "CLAIM_REVIEW_BYTES_REQUIRED",
    } <= set(manifest["release_reasons"])


def test_external_approval_schema_and_signature_payload_are_unambiguous(tmp_path: Path) -> None:
    prereg, corpus, runs, layers = fixture()
    manifest = compile_bundle(prereg, corpus, runs, layers, tmp_path)
    assert manifest["publication_contract"]["approval_subject_sha256"] == (
        approval_subject_digest(manifest)
    )
    receipt = {
        "schema": "tavonel.arena.external_approval_receipt.v1",
        "decision": "APPROVED_FOR_PUBLICATION",
        "approval_subject_sha256": manifest["publication_contract"]["approval_subject_sha256"],
        "manifest_sha256": file_digest(tmp_path / "manifest.json"),
        "approved_at": "2026-09-12T12:00:00Z",
        "founder_identity_ref": "fixture-key-owner",
        "signature": {
            "algorithm": "FIXTURE",
            "key_id": "fixture",
            "value": "not-a-signature",
        },
        "review_receipts": {
            "rights": "sha256:" + "1" * 64,
            "ip": "sha256:" + "2" * 64,
            "statistical": "sha256:" + "3" * 64,
            "claim": "sha256:" + "4" * 64,
        },
    }
    schema = json.loads(
        (Path(__file__).parents[1] / "schemas" / "external_approval_receipt.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator(schema).validate(receipt)
    payload = approval_signature_payload(receipt)
    assert payload.startswith(b"tavonel.arena.approval_signature.v1\n")
    assert b"not-a-signature" not in payload
    assert b"review\tclaim\tsha256:" in payload


def test_approval_subject_digest_is_portable_to_node(tmp_path: Path) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is unavailable")
    prereg, corpus, runs, layers = fixture()
    manifest = compile_bundle(prereg, corpus, runs, layers, tmp_path)
    script = """
const fs = require('fs');
const crypto = require('crypto');
const manifest = JSON.parse(fs.readFileSync(process.argv[1], 'utf8'));
let payload = 'tavonel.arena.approval_subject.v1\\n';
for (const name of Object.keys(manifest.artifacts).sort()) {
  payload += `artifact\\t${name}\\t${manifest.artifacts[name].sha256}\\n`;
}
const subject = crypto.createHash('sha256').update(payload, 'ascii').digest('hex');
process.stdout.write('sha256:' + subject);
"""
    completed = subprocess.run(  # noqa: S603 - fixed local Node executable and fixture args
        [node, "-e", script, str(tmp_path / "manifest.json")],
        check=True,
        capture_output=True,
        text=True,
    )
    assert completed.stdout == manifest["publication_contract"]["approval_subject_sha256"]


def test_checked_in_interop_vector_matches_python_reference() -> None:
    vector = json.loads(
        (Path(__file__).parents[1] / "schemas" / "interop_vector_v1.json").read_text(
            encoding="utf-8"
        )
    )
    manifest = {"artifacts": vector["manifest_artifacts"]}
    receipt = vector["approval_receipt_without_signature"]
    assert approval_subject_payload(manifest).hex() == vector["subject_payload_hex"]
    assert approval_subject_digest(manifest) == vector["subject_sha256"]
    assert approval_signature_payload(receipt).hex() == vector["signature_payload_hex"]


def test_public_manifest_schema_rejects_empty_aggregate_arm(tmp_path: Path) -> None:
    prereg, corpus, runs, layers = fixture()
    manifest = compile_bundle(prereg, corpus, runs, layers, tmp_path)
    manifest["public_summary"]["arms"][0] = {}
    schema = json.loads(
        (Path(__file__).parents[1] / "schemas" / "public_manifest.schema.json").read_text(
            encoding="utf-8"
        )
    )
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(manifest)


def test_synthetic_origin_cannot_be_promoted_by_renaming_study(tmp_path: Path) -> None:
    prereg, corpus, runs, layers = fixture()
    prereg["study_id"] = "arena-public-v1"
    prereg["study_kind"] = "FINAL_ARENA"
    manifest = compile_bundle(prereg, corpus, runs, layers, tmp_path)
    assert manifest["release_state"] == "WITHHELD"
    assert "SYNTHETIC_FINAL_FORBIDDEN" in manifest["release_reasons"]
    assert "FIXTURE_NOT_PUBLIC_EVIDENCE" in manifest["release_reasons"]


def test_cli_fixture_validate_and_export_roundtrip(tmp_path: Path) -> None:
    source = tmp_path / "source"
    first_bundle = tmp_path / "first"
    second_bundle = tmp_path / "second"
    prereg, corpus, runs, layers = fixture()
    compile_bundle(prereg, corpus, runs, layers, source)
    args = [
        "--preregistration",
        str(source / "preregistration.json"),
        "--corpus",
        str(source / "corpus.jsonl"),
        "--runs",
        str(source / "runs.jsonl"),
        "--layers",
        str(source / "layers.jsonl"),
    ]
    assert cli_main(["validate", *args]) == 0
    assert cli_main(["export", *args, "--output", str(first_bundle)]) == 3
    roundtrip_args = [
        "--preregistration",
        str(first_bundle / "preregistration.json"),
        "--corpus",
        str(first_bundle / "corpus.jsonl"),
        "--runs",
        str(first_bundle / "runs.jsonl"),
        "--layers",
        str(first_bundle / "layers.jsonl"),
        "--output",
        str(second_bundle),
    ]
    assert cli_main(["export", *roundtrip_args]) == 3
    assert json.loads((first_bundle / "manifest.json").read_text(encoding="utf-8")) == json.loads(
        (second_bundle / "manifest.json").read_text(encoding="utf-8")
    )


def test_claimed_final_1000_page_design_fails_without_licensed_input() -> None:
    prereg, corpus, runs, layers = fixture()
    prereg["study_kind"] = "FINAL_ARENA"
    prereg["corpus_requirements"]["arena_total"] = 1000
    prereg["corpus_requirements"]["calibration_total"] = 100
    prereg["public_release"]["required_repeats"] = 3
    report = validate_inputs(prereg, corpus, runs, layers)
    assert {"ARENA_TOTAL", "CALIBRATION_TOTAL", "INCOMPLETE_ACCOUNTING"} <= codes(report)
