from __future__ import annotations

import copy
import json
from pathlib import Path

from infra.release.validate_v4_traceability import (
    EXPECTED_DOD_IDS,
    EXPECTED_GATE_IDS,
    EXPECTED_SECTION_IDS,
    EXPECTED_WAVE_IDS,
    MANIFEST_PATH,
    ROOT,
    TRACEABILITY_PATH,
    extract_status_rows,
    validate_manifest_document,
    validate_repository,
    validate_traceability_text,
)


def test_v4_release_evidence_is_complete_and_fail_closed() -> None:
    assert validate_repository() == []


def test_v4_traceability_has_exact_required_identifier_counts() -> None:
    markdown = TRACEABILITY_PATH.read_text(encoding="utf-8")
    identifiers = {identifier for identifier, _status in extract_status_rows(markdown)}

    assert set(EXPECTED_SECTION_IDS) <= identifiers
    assert set(EXPECTED_WAVE_IDS) <= identifiers
    assert set(EXPECTED_DOD_IDS) <= identifiers
    assert set(EXPECTED_GATE_IDS) <= identifiers
    assert len(EXPECTED_SECTION_IDS) == 49
    assert len(EXPECTED_WAVE_IDS) == 12
    assert len(EXPECTED_DOD_IDS) == 45
    assert len(EXPECTED_GATE_IDS) == 30


def test_v4_traceability_rejects_missing_section_and_invalid_status() -> None:
    markdown = TRACEABILITY_PATH.read_text(encoding="utf-8")
    missing = markdown.replace("| S48 |", "| OMITTED-S48 |", 1)
    valid_row_start = "| S00 | §0 문서 사용법과 권한 | implemented |"
    invalid_row_start = "| S00 | §0 문서 사용법과 권한 | done |"
    invalid = markdown.replace(valid_row_start, invalid_row_start, 1)

    assert "traceability identifier S48 is missing" in validate_traceability_text(missing)
    assert any("S00 has invalid status" in error for error in validate_traceability_text(invalid))


def test_v4_manifest_rejects_promotion_or_unproven_sha_claim() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    promoted = copy.deepcopy(manifest)
    promoted["promotion_authorized"] = True
    promoted["deployment"]["latest_commit_confirmed_deployed"] = True

    errors = validate_manifest_document(promoted)
    assert any("promotion_authorized" in error for error in errors)
    assert any("latest_commit_confirmed_deployed" in error for error in errors)


def test_v4_validator_reports_missing_artifacts(tmp_path: Path) -> None:
    assert validate_repository(tmp_path) == [
        "missing V4_MASTERPLAN_TRACEABILITY.md",
        "missing CURRENT_STATE_AUDIT_V4.md",
        "missing docs/release/V4_DEPLOYMENT_MANIFEST.json",
    ]


def test_manifest_path_is_inside_repository() -> None:
    assert MANIFEST_PATH.is_relative_to(ROOT)
