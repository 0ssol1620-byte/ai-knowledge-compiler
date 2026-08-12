from __future__ import annotations

import copy
import json

from infra.release.validate_v4_subsections import (
    EXPECTED_AUTHORITY_LINE_COUNT,
    EXPECTED_AUTHORITY_SHA256,
    EXPECTED_ENTRY_IDS,
    EXPECTED_REQUIREMENT_COUNTS,
    EXPECTED_TOTAL_REQUIREMENTS,
    LEDGER_PATH,
    ROOT,
    validate_document,
    validate_repository,
)


def _document() -> dict[str, object]:
    value = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _entry(document: dict[str, object], identifier: str) -> dict[str, object]:
    sections = document["sections"]
    appendices = document["appendices"]
    assert isinstance(sections, list)
    assert isinstance(appendices, list)
    candidates = [
        entry
        for section in sections
        if isinstance(section, dict)
        for entry in section.get("entries", [])
        if isinstance(entry, dict)
    ]
    candidates.extend(entry for entry in appendices if isinstance(entry, dict))
    return next(entry for entry in candidates if entry.get("id") == identifier)


def test_v4_subsection_ledger_is_complete_and_fail_closed() -> None:
    assert validate_repository() == []
    assert len(EXPECTED_ENTRY_IDS) == 215
    assert len(EXPECTED_REQUIREMENT_COUNTS) == 215
    assert EXPECTED_TOTAL_REQUIREMENTS == 1_493


def test_v4_subsection_ledger_locks_authority_snapshot_and_utf8() -> None:
    raw = LEDGER_PATH.read_bytes()
    text = raw.decode("utf-8", errors="strict")
    document = json.loads(text)
    authority = document["authority"]

    assert "\ufffd" not in text
    assert "__SECTION_SENTINEL" not in text
    assert authority["sha256"] == EXPECTED_AUTHORITY_SHA256
    assert authority["line_count"] == EXPECTED_AUTHORITY_LINE_COUNT


def test_v4_subsection_ledger_rejects_missing_requirement() -> None:
    document = _document()
    altered = copy.deepcopy(document)
    requirements = _entry(altered, "10.2")["requirements"]
    assert isinstance(requirements, list)
    requirements.pop()

    errors = validate_document(altered, ROOT)
    assert "10.2 must retain 8 requirements; got 7" in errors
    assert any("expected 1493 requirement items" in error for error in errors)


def test_v4_subsection_ledger_rejects_unproven_implemented_claim() -> None:
    document = _document()
    altered = copy.deepcopy(document)
    entry = _entry(altered, "39.1")
    entry["status"] = "implemented"
    entry["blockers"] = []

    errors = validate_document(altered, ROOT)
    assert "39.1 cannot be implemented without verification_refs" in errors


def test_v4_subsection_ledger_keeps_html_metamorphic_boundary_honest() -> None:
    document = _document()
    requirements = _entry(document, "40.4")["requirements"]
    assert isinstance(requirements, list)

    assert "Receipt states production raster renderer not exercised" in requirements
    assert "Receipt states production OCR not exercised" in requirements


def test_v4_subsection_ledger_separates_v4_runtime_from_legacy_review_names() -> None:
    document = _document()
    section_groups = document["sections"]
    assert isinstance(section_groups, list)
    group_46 = next(
        group for group in section_groups if isinstance(group, dict) and group.get("id") == "46"
    )
    blocker = group_46["default_blockers"]
    assert isinstance(blocker, list)

    assert "autonomous isolation" in blocker[0]
    assert "legacy waiting_review/REVIEW_REQUIRED" in blocker[0]
    assert "not v4 execution authority" in blocker[0]
