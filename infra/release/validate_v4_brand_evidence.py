"""Validate the v4 brand and signature-asset evidence contracts."""

from __future__ import annotations

import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
SIGNATURE_IDS = ("A01", "A02", "A03", "A04", "A05", "A06")
COMPOSITION_IDS = ("A", "B", "C")
DECISIONS = {"KEEP", "POLISH", "REBUILD", "REMOVE"}
TRUTH_CLASSES = {"T0", "T1", "T2", "T3", "T4"}

ASSET_WEIGHTS = {
    "brand_fit": 15,
    "message_clarity": 15,
    "product_truth": 15,
    "ownability": 12,
    "composition": 10,
    "typography_and_material": 8,
    "responsive": 7,
    "accessibility": 5,
    "performance": 6,
    "provenance_and_license": 7,
}
VISUAL_WEIGHTS = {
    "brand_distinctiveness": 15,
    "category_comprehension": 10,
    "asset_craft": 15,
    "product_truth": 12,
    "composition": 10,
    "typography": 8,
    "interaction": 8,
    "motion_purpose": 6,
    "responsive": 6,
    "accessibility": 5,
    "performance": 3,
    "claim_truth": 2,
}
ZERO_CONDITIONS = {
    "generic_ai_hero",
    "fake_product",
    "broken_crop",
    "tiny_key_text",
    "dead_cta",
    "mobile_overflow",
    "reduced_motion_information_loss",
}


class BrandEvidenceError(ValueError):
    """Raised when brand evidence would allow an unsupported approval."""


def load_yaml(path: Path) -> dict[str, Any]:
    """Load a mapping-valued YAML document."""

    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise BrandEvidenceError(f"{path.name} must contain a mapping")
    return value


def as_mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise BrandEvidenceError(f"{label} must be a mapping")
    return value


def as_sequence(value: object, label: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise BrandEvidenceError(f"{label} must be a sequence")
    return value


def require(condition: bool, message: str) -> None:
    if not condition:
        raise BrandEvidenceError(message)


def validate_quality_gates(gates: Mapping[str, Any]) -> None:
    """Validate exact v4 weights and fail-closed current evidence."""

    approval = as_mapping(gates.get("approval_policy"), "approval_policy")
    require(approval.get("score_minimum") == 90, "score minimum must be 90")
    require(
        approval.get("critical_findings_required") == 0,
        "critical findings requirement must be zero",
    )
    require(
        approval.get("high_findings_required") == 0,
        "high findings requirement must be zero",
    )
    require(
        approval.get("actual_page_screenshots_required") is True,
        "actual page screenshots must be mandatory",
    )
    require(
        approval.get("current_worktree_required") is True,
        "approval must require current-worktree evidence",
    )

    asset_weights = as_mapping(
        as_mapping(gates.get("asset_rubric"), "asset_rubric").get("weights"),
        "asset_rubric.weights",
    )
    visual_weights = as_mapping(
        as_mapping(gates.get("visual_rubric"), "visual_rubric").get("weights"),
        "visual_rubric.weights",
    )
    require(dict(asset_weights) == ASSET_WEIGHTS, "asset rubric must match v4 section 22.6")
    require(sum(asset_weights.values()) == 100, "asset rubric must total 100")
    require(dict(visual_weights) == VISUAL_WEIGHTS, "visual rubric must match v4 section 45.1")
    require(sum(visual_weights.values()) == 100, "visual rubric must total 100")

    finding_policy = as_mapping(gates.get("finding_policy"), "finding_policy")
    require(
        set(as_sequence(finding_policy.get("blocking_severities"), "blocking severities"))
        == {"Critical", "High"},
        "Critical and High must both block approval",
    )
    require(
        set(as_sequence(finding_policy.get("required_zero_conditions"), "zero conditions"))
        == ZERO_CONDITIONS,
        "required-zero conditions must match v4 section 45.2",
    )

    composition_policy = as_mapping(gates.get("composition_policy"), "composition_policy")
    candidates = as_sequence(
        composition_policy.get("required_candidates"), "composition candidates"
    )
    candidate_ids = tuple(
        as_mapping(candidate, "composition candidate").get("id") for candidate in candidates
    )
    require(candidate_ids == COMPOSITION_IDS, "composition candidates must be A, B, and C")
    require(
        composition_policy.get("all_three_required_before_approval") is True,
        "all three static compositions must precede approval",
    )

    capture_policy = as_mapping(gates.get("capture_policy"), "capture_policy")
    require(
        tuple(as_sequence(capture_policy.get("exact_widths_px"), "capture widths"))
        == (1920, 1440, 1280, 1024, 768, 390, 360),
        "capture widths must match the seven-width v4 visual matrix",
    )
    require(
        set(as_sequence(capture_policy.get("required_modes"), "capture modes"))
        == {"default", "reduced_motion"},
        "default and reduced-motion captures are required",
    )
    require(
        set(as_sequence(capture_policy.get("required_languages"), "capture languages"))
        == {"en", "ko"},
        "English and Korean capture evidence is required",
    )

    current = as_mapping(gates.get("current_evidence"), "current_evidence")
    score_map = as_mapping(current.get("signature_asset_scores"), "signature asset scores")
    require(tuple(score_map) == SIGNATURE_IDS, "current evidence must enumerate A01 through A06")
    if current.get("approval") is True:
        require(
            isinstance(current.get("visual_score"), int)
            and current["visual_score"] >= approval["score_minimum"],
            "approval requires a measured visual score of at least 90",
        )
        require(current.get("critical_findings") == 0, "approval requires zero Critical findings")
        require(current.get("high_findings") == 0, "approval requires zero High findings")
        require(
            all(isinstance(score, int) and score >= 90 for score in score_map.values()),
            "approval requires every signature asset to score at least 90",
        )
        require(
            bool(current.get("actual_page_capture_records")),
            "approval requires current actual-page capture records",
        )


def validate_ledger(ledger: Mapping[str, Any], root: Path = ROOT) -> None:
    """Validate signature coverage, truth boundaries, and source evidence paths."""

    signatures = as_sequence(ledger.get("signature_assets"), "signature_assets")
    records = [as_mapping(record, "signature asset") for record in signatures]
    ids = tuple(record.get("asset_id") for record in records)
    require(ids == SIGNATURE_IDS, "ledger must enumerate A01 through A06 exactly once and in order")

    for record in records:
        asset_id = str(record["asset_id"])
        require(record.get("decision") in DECISIONS, f"{asset_id} has an invalid decision")
        require(
            record.get("truth_class") in TRUTH_CLASSES,
            f"{asset_id} has an invalid truth class",
        )
        require(
            tuple(as_sequence(record.get("composition_candidates"), f"{asset_id} compositions"))
            == COMPOSITION_IDS,
            f"{asset_id} must specify all three static compositions",
        )
        require(
            record.get("provisional_composition") in COMPOSITION_IDS,
            f"{asset_id} must select a provisional composition",
        )
        require(
            bool(as_sequence(record.get("actual_data_contract"), f"{asset_id} data contract")),
            f"{asset_id} must declare an actual data contract",
        )
        for relative in as_sequence(record.get("source_refs"), f"{asset_id} source refs"):
            require(isinstance(relative, str), f"{asset_id} source reference must be text")
            require(
                (root / relative).is_file(),
                f"{asset_id} source evidence is missing: {relative}",
            )

        license_record = as_mapping(record.get("license"), f"{asset_id} license")
        require(
            license_record.get("generated_with_ai") is False,
            f"{asset_id} may not use generated evidence",
        )
        evidence_path = license_record.get("evidence_path")
        if not isinstance(evidence_path, str):
            raise BrandEvidenceError(f"{asset_id} needs license evidence")
        require((root / evidence_path).is_file(), f"{asset_id} license evidence is missing")

        qa = as_mapping(record.get("qa"), f"{asset_id} qa")
        if qa.get("approved") is True:
            require(
                isinstance(qa.get("score"), int) and qa["score"] >= 90,
                f"{asset_id} approval requires a score of at least 90",
            )
            require(qa.get("critical_findings") == 0, f"{asset_id} has Critical findings")
            require(qa.get("high_findings") == 0, f"{asset_id} has High findings")
            require(
                bool(qa.get("actual_page_capture_set")),
                f"{asset_id} approval requires an actual-page capture set",
            )

    families = as_sequence(ledger.get("existing_families"), "existing_families")
    for family_value in families:
        family = as_mapping(family_value, "existing family")
        require(family.get("decision") in DECISIONS, "existing family has an invalid decision")
        for relative in as_sequence(family.get("evidence_paths"), "family evidence paths"):
            require(isinstance(relative, str), "family evidence path must be text")
            require((root / relative).is_file(), f"family evidence is missing: {relative}")


def validate_art_direction_board(text: str) -> None:
    """Require all composition and signature briefs plus the no-approval boundary."""

    for marker in (
        "A — Editorial Source",
        "B — Proof-First Product",
        "C — Knowledge Architecture",
        *SIGNATURE_IDS,
        "not screenshot evidence",
        "Production art approval is not",
    ):
        require(marker in text, f"art direction board is missing: {marker}")


def validate_repository(root: Path = ROOT) -> None:
    gates = load_yaml(root / "VISUAL_QUALITY_GATES.yml")
    ledger = load_yaml(root / "ASSET_REMEDIATION_LEDGER.yml")
    board = (root / "ART_DIRECTION_BOARD.md").read_text(encoding="utf-8")
    validate_quality_gates(gates)
    validate_ledger(ledger, root)
    validate_art_direction_board(board)


def main() -> int:
    try:
        validate_repository()
    except (OSError, yaml.YAMLError, BrandEvidenceError) as exc:
        print(f"v4 brand evidence validation failed: {exc}")
        return 1
    print("v4 brand evidence validation passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
