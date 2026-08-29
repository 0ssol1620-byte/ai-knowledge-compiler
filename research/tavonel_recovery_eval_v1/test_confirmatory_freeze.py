from __future__ import annotations

import json
from pathlib import Path

import confirmatory_freeze as f
import pytest
from confirmatory_selection import (
    STAGE1_FAMILY_QUOTAS,
    EvidenceAnchor,
    build_evidence_split,
    build_spent_manifest,
    select_stage1,
)
from recovery_protocol import ModelPin

SHA_A = "sha256:" + "a" * 64
SHA_B = "sha256:" + "b" * 64


def _candidate(family: str, index: int) -> dict:
    return {
        "source_family": family,
        "family_id": f"{family}-family-{index // 2}",
        "document_id": f"{family}-document-{index}",
        "page_id": f"{family}-page-{index}",
        "source_locator": f"https://example.invalid/{family}/{index}",
        "source_revision": "rev-1",
        "source_sha256": "sha256:" + f"{index + 1:064x}"[-64:],
        "acquisition_identity": f"{family}:{index}:rev-1",
        "metadata": {"page_number": index + 1},
    }


def _manifests(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    source = tmp_path / "source.json"
    spent = tmp_path / "spent.json"
    cohort = tmp_path / "cohort.json"
    split = tmp_path / "split.json"
    source.write_text(
        json.dumps({"schema": "tavonel.recovery.source_manifest.test.v1"}), encoding="utf-8"
    )
    spent_value = build_spent_manifest(exact_spent_ids=(), spent_family_ids=())
    spent.write_text(json.dumps(spent_value), encoding="utf-8")
    candidates = [
        _candidate(family, index)
        for family, quota in STAGE1_FAMILY_QUOTAS.items()
        for index in range(quota + 5)
    ]
    cohort.write_text(json.dumps(select_stage1(candidates, spent_value)), encoding="utf-8")
    split_value = build_evidence_split(
        (
            EvidenceAnchor("native", "SOURCE_NATIVE", trigger_eligible=True),
            EvidenceAnchor(
                "truth",
                "GROUND_TRUTH",
                evaluator_label=True,
                evaluation_eligible=True,
            ),
        )
    )
    split.write_text(json.dumps(split_value), encoding="utf-8")
    return source, spent, cohort, split


def _pin(role: str) -> ModelPin:
    return ModelPin(
        role=role,
        model_id=f"model-{role}",
        model_revision=f"revision-{role}",
        runtime_id=f"runtime-{role}",
        runtime_digest=SHA_A,
        prompt_or_schema_digest=SHA_B,
    )


def _patch_runtime_inputs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calibration = tmp_path / "calibration.json"
    calibration.write_bytes(f.CALIBRATION.read_bytes())
    primary_receipt = tmp_path / "primary.json"
    strong_receipt = tmp_path / "strong.json"
    primary_receipt.write_text("{}", encoding="utf-8")
    strong_receipt.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(f, "CALIBRATION", calibration)
    monkeypatch.setattr(f, "OUTPUT", tmp_path / "freeze.json")
    monkeypatch.setattr(f, "PRIMARY_ATTESTATION", primary_receipt)
    monkeypatch.setattr(f, "STRONG_ATTESTATION", strong_receipt)
    monkeypatch.setattr(f, "_attested_pin", lambda path, role: _pin(role))
    monkeypatch.setattr(f, "_peer_pin", lambda: _pin("peer"))
    monkeypatch.setattr(f, "_git_text", lambda *args: "fixture-commit")


def test_freeze_accepts_clean_sealed_manifests(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _patch_runtime_inputs(monkeypatch, tmp_path)
    source, spent, cohort, split = _manifests(tmp_path)
    report = f.freeze(
        source_manifest_path=source,
        spent_manifest_path=spent,
        cohort_path=cohort,
        split_path=split,
    )
    assert report["state"] == "FROZEN"
    assert report["fresh_outcomes_observed_before_freeze"] is False
    assert report["oracle_primary_eligible"] is False


def test_freeze_rejects_tampered_cohort_seal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _patch_runtime_inputs(monkeypatch, tmp_path)
    source, spent, cohort, split = _manifests(tmp_path)
    value = json.loads(cohort.read_text(encoding="utf-8"))
    value["entries"][0]["page_id"] = "tampered"
    cohort.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(f.FreezeRefused, match="cohort seal"):
        f.freeze(
            source_manifest_path=source,
            spent_manifest_path=spent,
            cohort_path=cohort,
            split_path=split,
        )


def test_freeze_rejects_spent_family_overlap_even_with_valid_spent_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _patch_runtime_inputs(monkeypatch, tmp_path)
    source, spent, cohort, split = _manifests(tmp_path)
    cohort_value = json.loads(cohort.read_text(encoding="utf-8"))
    spent_value = build_spent_manifest(
        exact_spent_ids=(),
        spent_family_ids=(cohort_value["entries"][0]["family_id"],),
    )
    spent.write_text(json.dumps(spent_value), encoding="utf-8")
    with pytest.raises(f.FreezeRefused, match="spent document family"):
        f.freeze(
            source_manifest_path=source,
            spent_manifest_path=spent,
            cohort_path=cohort,
            split_path=split,
        )


def test_freeze_rejects_tampered_evidence_split(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _patch_runtime_inputs(monkeypatch, tmp_path)
    source, spent, cohort, split = _manifests(tmp_path)
    value = json.loads(split.read_text(encoding="utf-8"))
    value["runtime_may_read_evaluation_side"] = True
    split.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(f.FreezeRefused, match="split digest"):
        f.freeze(
            source_manifest_path=source,
            spent_manifest_path=spent,
            cohort_path=cohort,
            split_path=split,
        )
