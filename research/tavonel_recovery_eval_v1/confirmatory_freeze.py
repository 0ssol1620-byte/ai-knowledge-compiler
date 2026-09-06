#!/usr/bin/env python3
"""Freeze Paper 2 confirmatory authority after runtime qualification and cohort sealing."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from confirmatory_execution import DISAGREEMENT_SIMILARITY_THRESHOLD, PREDICTION_ONLY_THRESHOLD
from confirmatory_selection import (
    STAGE1_FAMILY_QUOTAS,
    SourceCandidate,
    evidence_split_salt_digest,
)
from recovery_protocol import (
    EvidenceSplit,
    FreshCohortAuthority,
    ModelPin,
    RecoveryProtocol,
)
from runtime_attestation import verify_attestation_payload

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
OUTPUT = HERE / "receipts" / "confirmatory-freeze.json"
CALIBRATION = HERE / "CALIBRATION_POLICY_PRE_FREEZE.json"
PRIMARY_ATTESTATION = HERE / "receipts" / "runtime-qualification" / "primary.json"
STRONG_ATTESTATION = HERE / "receipts" / "runtime-qualification" / "strong.json"


class FreezeRefused(RuntimeError):
    pass


def _sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FreezeRefused(f"required freeze input is missing: {path.name}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise FreezeRefused(f"freeze input is not an object: {path.name}")
    return value


def _git_text(*args: str) -> str:
    result = subprocess.run(  # noqa: S603 - fixed git argv plus internal arguments only
        ["git", *args],  # noqa: S607 - repository follows the existing git-from-PATH convention
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise FreezeRefused(result.stderr.strip())
    return result.stdout.strip()


def _peer_pin() -> ModelPin:
    paths = (
        REPO / "packages" / "cir-python" / "src" / "akc_cir" / "parser_verification.py",
        REPO / "packages" / "cir-python" / "src" / "akc_cir" / "critical_tokens.py",
    )
    if any(not path.is_file() for path in paths):
        raise FreezeRefused("native/source peer implementation is missing")
    body = {str(path.relative_to(REPO)).replace("\\", "/"): _sha(path) for path in paths}
    runtime_digest = _digest(body)
    return ModelPin(
        role="peer",
        model_id="tavonel-native-source-evidence",
        model_revision=_git_text("rev-parse", "HEAD"),
        runtime_id="akc-cir-parser-verification+critical-tokens",
        runtime_digest=runtime_digest,
        prompt_or_schema_digest=runtime_digest,
    )


def _attested_pin(path: Path, role: str) -> ModelPin:
    payload = _load(path)
    digest = verify_attestation_payload(payload, REPO)
    if payload.get("role") != role:
        raise FreezeRefused(f"runtime attestation role mismatch: expected {role}")
    if payload.get("fresh_confirmatory_observation") is not False:
        raise FreezeRefused("runtime qualification observed fresh confirmatory data")
    if payload.get("sensitive_material_included") is not False:
        raise FreezeRefused("runtime qualification reports sensitive material")
    if payload.get("attestation_digest") != digest:
        raise FreezeRefused("runtime attestation digest does not recompute")
    return ModelPin(
        role=role,
        model_id=str(payload["model_id"]),
        model_revision=str(payload["model_revision"]),
        runtime_id=str(payload.get("base_image") or "qualified-runtime"),
        runtime_digest=digest,
        prompt_or_schema_digest=str(payload["prompt_schema_digest"]),
    )


def freeze(
    *, source_manifest_path: Path, spent_manifest_path: Path, cohort_path: Path, split_path: Path
) -> dict[str, Any]:
    if OUTPUT.exists():
        raise FreezeRefused("confirmatory freeze already exists; it is immutable")
    calibration = _load(CALIBRATION)
    if calibration.get("confirmatory_retuning_allowed") is not False:
        raise FreezeRefused("calibration manifest permits confirmatory retuning")
    if calibration["prediction_only"]["threshold"] != PREDICTION_ONLY_THRESHOLD:
        raise FreezeRefused("prediction-only threshold differs from committed execution code")
    if (
        calibration["disagreement"]["normalized_text_similarity_threshold"]
        != DISAGREEMENT_SIMILARITY_THRESHOLD
    ):
        raise FreezeRefused("disagreement threshold differs from committed execution code")
    if calibration["selection"]["stage1_equal_source_family_quota"] != dict(STAGE1_FAMILY_QUOTAS):
        raise FreezeRefused("selection quotas differ from committed selection code")

    source = _load(source_manifest_path)
    spent = _load(spent_manifest_path)
    cohort = _load(cohort_path)
    split = _load(split_path)
    if not str(source.get("schema") or "").strip():
        raise FreezeRefused("fresh source manifest lacks a schema")
    spent_body = {key: value for key, value in spent.items() if key != "spent_manifest_digest"}
    if _digest(spent_body) != spent.get("spent_manifest_digest"):
        raise FreezeRefused("spent manifest digest does not recompute")
    cohort_body = {key: value for key, value in cohort.items() if key != "cohort_seal_digest"}
    if _digest(cohort_body) != cohort.get("cohort_seal_digest"):
        raise FreezeRefused("fresh cohort seal does not recompute")
    split_body = {key: value for key, value in split.items() if key != "evidence_split_digest"}
    if _digest(split_body) != split.get("evidence_split_digest"):
        raise FreezeRefused("evidence split digest does not recompute")
    if cohort.get("entry_count") != sum(STAGE1_FAMILY_QUOTAS.values()):
        raise FreezeRefused("fresh cohort does not contain the prospectively fixed 300 pages")
    if cohort.get("scientific_outcomes_used_for_selection") is not False:
        raise FreezeRefused("fresh selection reports outcome-derived selection")
    if split.get("runtime_may_read_evaluation_side") is not False:
        raise FreezeRefused("runtime may read hidden evaluation evidence")
    if split.get("split_salt_digest") != evidence_split_salt_digest():
        raise FreezeRefused("evidence split salt drifted")

    exact_spent = set(map(str, spent.get("exact_spent_ids", ())))
    spent_families = set(map(str, spent.get("spent_family_ids", ())))
    cohort_candidates = [SourceCandidate.from_record(row) for row in cohort.get("entries", ())]
    if len(cohort_candidates) != cohort.get("entry_count"):
        raise FreezeRefused("fresh cohort entry count does not match its entries")
    if any(candidate.stable_id in exact_spent for candidate in cohort_candidates):
        raise FreezeRefused("fresh cohort contains an exact spent page identity")
    if any(candidate.family_id in spent_families for candidate in cohort_candidates):
        raise FreezeRefused("fresh cohort contains a spent document family")

    trigger = tuple(map(str, split.get("trigger_anchor_ids", ())))
    evaluation = tuple(map(str, split.get("evaluation_anchor_ids", ())))
    evidence_split = EvidenceSplit(
        split_salt_digest=str(split["split_salt_digest"]),
        trigger_anchor_ids=trigger,
        evaluation_anchor_ids=evaluation,
    )
    evidence_split.validate()

    authority = FreshCohortAuthority(
        corpus_id="tavonel-r-fresh-stage1-300",
        source_manifest_digest=_sha(source_manifest_path),
        spent_manifest_digest=_sha(spent_manifest_path),
        selection_rule_digest=str(cohort["cohort_seal_digest"]),
        cohort_seal_digest=None,
        family_overlap_with_spent=False,
    )
    primary = _attested_pin(PRIMARY_ATTESTATION, "primary")
    strong = _attested_pin(STRONG_ATTESTATION, "strong")
    peer = _peer_pin()
    protocol = RecoveryProtocol(
        model_pins=(primary, peer, strong),
        cohort=authority,
        evidence_split=evidence_split,
        calibration_manifest_digest=_sha(CALIBRATION),
        metadata={
            "purpose": "fresh confirmatory recovery",
            "baseline_commit": _git_text("log", "-1", "--format=%H", "--", str(HERE)),
        },
    )
    protocol.validate_ready_to_freeze()
    frozen_terms = RecoveryProtocol(
        state="FROZEN",
        model_pins=protocol.model_pins,
        cohort=protocol.cohort,
        evidence_split=protocol.evidence_split,
        calibration_manifest_digest=protocol.calibration_manifest_digest,
        metadata=protocol.metadata,
    )
    body = {
        "schema": "tavonel.recovery.confirmatory_freeze.v1",
        "state": "FROZEN",
        "protocol_digest": frozen_terms.digest(),
        "protocol_terms": frozen_terms.terms(),
        "source_manifest_sha256": _sha(source_manifest_path),
        "spent_manifest_sha256": _sha(spent_manifest_path),
        "cohort_manifest_sha256": _sha(cohort_path),
        "cohort_seal_digest": cohort["cohort_seal_digest"],
        "evidence_split_sha256": _sha(split_path),
        "evidence_split_digest": split["evidence_split_digest"],
        "calibration_sha256": _sha(CALIBRATION),
        "runtime_attestation_sha256": {
            "primary": _sha(PRIMARY_ATTESTATION),
            "strong": _sha(STRONG_ATTESTATION),
        },
        "peer_pin": {
            "model_id": peer.model_id,
            "model_revision": peer.model_revision,
            "runtime_digest": peer.runtime_digest,
        },
        "fresh_outcomes_observed_before_freeze": False,
        "threshold_retuning_after_freeze": False,
        "oracle_primary_eligible": False,
    }
    report = {**body, "freeze_digest": _digest(body)}
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


__all__ = ["FreezeRefused", "freeze"]
