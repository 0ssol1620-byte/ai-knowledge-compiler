from __future__ import annotations

import json
from pathlib import Path

import pytest

import confirmatory_runtime_driver as d


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _fixture(tmp_path: Path):
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    entries = []
    runtime_entries = []
    for ordinal in (1, 2):
        page_id = f"page-{ordinal}"
        source_sha = "sha256:" + f"{ordinal:064x}"
        entries.append(
            {
                "selection_ordinal": ordinal,
                "source_family": "sec" if ordinal == 1 else "drdocbench",
                "family_id": f"family-{ordinal}",
                "document_id": f"document-{ordinal}",
                "page_id": page_id,
                "source_locator": f"https://example.invalid/{page_id}",
                "source_revision": "rev-1",
                "source_sha256": source_sha,
                "acquisition_identity": f"fixture:{page_id}",
                "metadata": {"page_number": ordinal},
            }
        )
        primary = artifact_root / f"primary-{ordinal}.md"
        peer = artifact_root / f"peer-{ordinal}.md"
        strong = artifact_root / f"strong-{ordinal}.md"
        text = f"Revenue {100 + ordinal} Total {200 + ordinal}"
        primary.write_text(text + "\n", encoding="utf-8")
        peer.write_text(text + "\n", encoding="utf-8")
        strong.write_text(text + "\n", encoding="utf-8")
        runtime_entries.append(
            {
                "selection_ordinal": ordinal,
                "page_id": page_id,
                "benchmark_id": "fresh",
                "source_sha256": source_sha,
                "primary_markdown": primary.name,
                "peer_text": peer.name,
                "strong_markdown": strong.name,
                "trigger": {
                    "risk": 0.1,
                    "uncertainty": 0.1,
                    "native_or_source_text": text + "\n",
                    "structural_failure": False,
                    "critical_token_constraint_failure": False,
                    "visual_round_trip_failure": False,
                    "cross_page_failure": False,
                    "strong_verified_by_independent_evidence": True,
                },
                "primary_gpu_seconds": 1.0,
                "strong_gpu_seconds": 5.0,
                "primary_cost_usd": 0.01,
                "strong_cost_usd": 0.05,
            }
        )

    cohort_body = {
        "schema": "tavonel.recovery.fresh_selection.v1",
        "entry_count": len(entries),
        "entries": entries,
        "scientific_outcomes_used_for_selection": False,
    }
    cohort = {**cohort_body, "cohort_seal_digest": d._digest(cohort_body)}
    cohort_path = tmp_path / "cohort.json"
    _write_json(cohort_path, cohort)

    primary_pin = "sha256:" + "a" * 64
    strong_pin = "sha256:" + "b" * 64
    freeze_body = {
        "schema": "tavonel.recovery.confirmatory_freeze.v1",
        "state": "FROZEN",
        "cohort_manifest_sha256": d._sha(cohort_path),
        "cohort_seal_digest": cohort["cohort_seal_digest"],
        "runtime_attestation_sha256": {"primary": primary_pin, "strong": strong_pin},
        "fresh_outcomes_observed_before_freeze": False,
        "threshold_retuning_after_freeze": False,
        "oracle_primary_eligible": False,
    }
    freeze = {**freeze_body, "freeze_digest": d._digest(freeze_body)}
    freeze_path = tmp_path / "freeze.json"
    _write_json(freeze_path, freeze)

    manifest = {
        "schema": d.SCHEMA,
        "freeze_digest": freeze["freeze_digest"],
        "cohort_manifest_sha256": d._sha(cohort_path),
        "primary_attestation_sha256": primary_pin,
        "strong_attestation_sha256": strong_pin,
        "entries": runtime_entries,
        "hidden_evaluation_mounted": False,
        "fresh_confirmatory_observation": True,
    }
    manifest_path = tmp_path / "runtime-manifest.json"
    _write_json(manifest_path, manifest)
    return artifact_root, cohort_path, freeze_path, manifest_path


def test_executes_five_arms_and_seals_without_hidden_evaluation(tmp_path: Path):
    artifact_root, cohort, freeze, manifest = _fixture(tmp_path)
    receipts = tmp_path / "receipts"
    result = d.execute_runtime(
        cohort_path=cohort,
        runtime_manifest_path=manifest,
        artifact_root=artifact_root,
        freeze_path=freeze,
        receipt_root=receipts,
    )
    assert result["state"] == "RUNTIME_OUTPUTS_SEALED"
    assert result["page_count"] == 2
    assert result["hidden_evaluation_opened"] is False
    assert len(result["primary_arms"]) == 5
    for ordinal in (1, 2):
        page = json.loads((receipts / "pages" / f"{ordinal:04d}.json").read_text(encoding="utf-8"))
        assert len(page["arms"]) == 5
        assert page["hidden_evaluation_opened"] is False
    assert d.verify_runtime_seal(receipt_root=receipts) == result


def test_resume_is_idempotent_for_already_sealed_pages(tmp_path: Path):
    artifact_root, cohort, freeze, manifest = _fixture(tmp_path)
    receipts = tmp_path / "receipts"
    first = d.execute_runtime(
        cohort_path=cohort,
        runtime_manifest_path=manifest,
        artifact_root=artifact_root,
        freeze_path=freeze,
        receipt_root=receipts,
    )
    second = d.execute_runtime(
        cohort_path=cohort,
        runtime_manifest_path=manifest,
        artifact_root=artifact_root,
        freeze_path=freeze,
        receipt_root=receipts,
    )
    assert first == second


def test_hidden_evaluation_field_is_refused_before_execution(tmp_path: Path):
    artifact_root, cohort, freeze, manifest = _fixture(tmp_path)
    value = json.loads(manifest.read_text(encoding="utf-8"))
    value["entries"][0]["ground_truth"] = "forbidden"
    _write_json(manifest, value)
    with pytest.raises(d.RuntimeDriverRefused, match="hidden evaluation-like"):
        d.execute_runtime(
            cohort_path=cohort,
            runtime_manifest_path=manifest,
            artifact_root=artifact_root,
            freeze_path=freeze,
            receipt_root=tmp_path / "receipts",
        )


def test_source_hash_drift_is_refused(tmp_path: Path):
    artifact_root, cohort, freeze, manifest = _fixture(tmp_path)
    value = json.loads(manifest.read_text(encoding="utf-8"))
    value["entries"][0]["source_sha256"] = "sha256:" + "f" * 64
    _write_json(manifest, value)
    with pytest.raises(d.RuntimeDriverRefused, match="source hash drifted"):
        d.execute_runtime(
            cohort_path=cohort,
            runtime_manifest_path=manifest,
            artifact_root=artifact_root,
            freeze_path=freeze,
            receipt_root=tmp_path / "receipts",
        )


def test_runtime_manifest_change_cannot_rebind_existing_page_receipts(tmp_path: Path):
    artifact_root, cohort, freeze, manifest = _fixture(tmp_path)
    receipts = tmp_path / "receipts"
    d.execute_runtime(
        cohort_path=cohort,
        runtime_manifest_path=manifest,
        artifact_root=artifact_root,
        freeze_path=freeze,
        receipt_root=receipts,
    )
    value = json.loads(manifest.read_text(encoding="utf-8"))
    value["entries"][0]["primary_gpu_seconds"] = 2.0
    _write_json(manifest, value)
    with pytest.raises(d.RuntimeDriverRefused, match="another manifest"):
        d.execute_runtime(
            cohort_path=cohort,
            runtime_manifest_path=manifest,
            artifact_root=artifact_root,
            freeze_path=freeze,
            receipt_root=receipts,
        )


def test_artifact_path_escape_is_refused(tmp_path: Path):
    artifact_root, cohort, freeze, manifest = _fixture(tmp_path)
    value = json.loads(manifest.read_text(encoding="utf-8"))
    value["entries"][0]["primary_markdown"] = "../escape.md"
    _write_json(manifest, value)
    with pytest.raises(d.RuntimeDriverRefused, match="relative artifact path"):
        d.execute_runtime(
            cohort_path=cohort,
            runtime_manifest_path=manifest,
            artifact_root=artifact_root,
            freeze_path=freeze,
            receipt_root=tmp_path / "receipts",
        )
