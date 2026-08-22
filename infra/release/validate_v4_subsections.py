"""Validate exact subsection-level Structara v4 requirement traceability."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Final

ROOT: Final = Path(__file__).resolve().parents[2]
LEDGER_PATH: Final = ROOT / "docs" / "release" / "V4_SUBSECTION_REQUIREMENTS.json"
AUTHORITY_BASENAME: Final = (
    "Structara_World_Class_Autonomous_Knowledge_Platform_"
    "FINAL_Completion_Masterplan_v4_KO_2026-07-31.md"
)
VALID_STATUSES: Final = frozenset(
    {"implemented", "local-contract", "external-evidence-required", "blocked"}
)
VALID_BOUNDARIES: Final = frozenset({"local", "mixed", "external"})

_NUMBERED_COUNTS: Final = {
    0: 4,
    1: 3,
    2: 4,
    3: 5,
    4: 4,
    5: 11,
    6: 5,
    7: 6,
    8: 7,
    9: 6,
    10: 6,
    11: 6,
    12: 4,
    13: 7,
    14: 4,
    16: 5,
    17: 6,
    18: 8,
    19: 5,
    20: 4,
    21: 4,
    22: 6,
    23: 5,
    24: 3,
    25: 3,
    27: 10,
    28: 4,
    29: 3,
    30: 4,
    32: 3,
    33: 4,
    34: 3,
    35: 3,
    39: 4,
    40: 5,
    43: 4,
    44: 7,
    45: 2,
}
_PLAIN_SECTION_IDS: Final = (15, 26, 31, 36, 37, 38, 41, 46, 47, 48)
EXPECTED_SECTION_GROUP_IDS: Final = tuple(str(index) for index in range(49))
EXPECTED_ENTRY_IDS: Final = (
    *(
        f"{section}.{subsection}"
        for section, count in _NUMBERED_COUNTS.items()
        for subsection in range(1, count + 1)
    ),
    *(str(section) for section in _PLAIN_SECTION_IDS),
    "42",
    *(f"42.W{index}" for index in range(12)),
    *(f"Appendix.{letter}" for letter in "ABCDE"),
)

_CARDINALITY_SPEC: Final = """
0.1:7 0.2:8 0.3:10 0.4:9
1.1:11 1.2:10 1.3:4
2.1:7 2.2:11 2.3:10 2.4:7
3.1:1 3.2:5 3.3:3 3.4:6 3.5:7
4.1:6 4.2:14 4.3:7 4.4:15
5.1:8 5.2:2 5.3:1 5.4:7 5.5:9 5.6:5 5.7:6 5.8:6 5.9:8 5.10:3 5.11:7
6.1:3 6.2:4 6.3:11 6.4:12 6.5:4
7.1:17 7.2:5 7.3:7 7.4:4 7.5:5 7.6:5
8.1:5 8.2:12 8.3:6 8.4:3 8.5:5 8.6:7 8.7:10
9.1:4 9.2:6 9.3:4 9.4:9 9.5:8 9.6:5
10.1:8 10.2:8 10.3:8 10.4:5 10.5:3 10.6:5
11.1:3 11.2:4 11.3:12 11.4:9 11.5:5 11.6:6
12.1:4 12.2:5 12.3:6 12.4:8
13.1:1 13.2:8 13.3:3 13.4:6 13.5:7 13.6:5 13.7:2
14.1:11 14.2:7 14.3:6 14.4:10 15:4
16.1:6 16.2:13 16.3:2 16.4:6 16.5:4
17.1:12 17.2:9 17.3:7 17.4:6 17.5:5 17.6:2
18.1:5 18.2:1 18.3:3 18.4:6 18.5:22 18.6:6 18.7:6 18.8:7
19.1:1 19.2:8 19.3:6 19.4:5 19.5:6
20.1:2 20.2:8 20.3:4 20.4:7
21.1:2 21.2:5 21.3:2 21.4:10
22.1:2 22.2:4 22.3:6 22.4:7 22.5:4 22.6:14
23.1:2 23.2:4 23.3:4 23.4:8 23.5:7
24.1:1 24.2:5 24.3:1
25.1:6 25.2:6 25.3:1 26:4
27.1:9 27.2:5 27.3:3 27.4:6 27.5:4 27.6:3 27.7:4 27.8:5 27.9:4 27.10:5
28.1:6 28.2:6 28.3:6 28.4:10
29.1:6 29.2:4 29.3:5
30.1:4 30.2:5 30.3:2 30.4:2 31:11
32.1:6 32.2:9 32.3:5
33.1:10 33.2:5 33.3:4 33.4:6
34.1:7 34.2:2 34.3:5
35.1:13 35.2:7 35.3:11 36:26 37:15 38:13
39.1:6 39.2:9 39.3:5 39.4:5
40.1:4 40.2:3 40.3:10 40.4:8 40.5:5
41:6 42:2 42.W0:8 42.W1:9 42.W2:7 42.W3:6 42.W4:7 42.W5:8 42.W6:6
42.W7:6 42.W8:9 42.W9:9 42.W10:7 42.W11:8
43.1:7 43.2:10 43.3:1 43.4:5
44.1:11 44.2:11 44.3:10 44.4:5 44.5:6 44.6:8 44.7:11
45.1:13 45.2:9 46:10 47:12 48:45
Appendix.A:8 Appendix.B:39 Appendix.C:18 Appendix.D:7 Appendix.E:5
"""
EXPECTED_REQUIREMENT_COUNTS: Final = {
    identifier: int(count)
    for token in _CARDINALITY_SPEC.split()
    for identifier, count in (token.rsplit(":", 1),)
}
EXPECTED_TOTAL_REQUIREMENTS: Final = sum(EXPECTED_REQUIREMENT_COUNTS.values())
EXPECTED_AUTHORITY_SHA256: Final = (
    "b8ce82840df252633075e80fede87e8f0a44de57bde4265a20579e8616a15d68"
)
EXPECTED_AUTHORITY_LINE_COUNT: Final = 3411


def _is_nonempty_strings(value: object) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(item, str) and bool(item.strip()) for item in value)
    )


def _load_document(path: Path) -> tuple[dict[str, object] | None, list[str]]:
    errors: list[str] = []
    if not path.is_file():
        return None, [f"missing {path.name}"]
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        return None, [f"ledger is not strict UTF-8: {exc}"]
    if "\ufffd" in text:
        errors.append("ledger contains U+FFFD replacement characters")
    if "__SECTION_SENTINEL" in text:
        errors.append("ledger contains an assembly sentinel")
    if "github_api.txt" in text.lower():
        errors.append("ledger must never reference the credential file")
    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, [*errors, f"ledger is not valid JSON: {exc}"]
    if not isinstance(document, dict):
        return None, [*errors, "ledger root must be an object"]
    return document, errors


def _expected_heading_prefix(identifier: str) -> str:
    if identifier.startswith("Appendix."):
        return f"# Appendix {identifier.removeprefix('Appendix.')}."
    if identifier.startswith("42.W"):
        return f"## Wave {identifier.removeprefix('42.W')} "
    if "." in identifier:
        return f"## {identifier} "
    return f"# {identifier}."


def _validate_authority_snapshot(
    document: dict[str, object],
    entries: list[dict[str, object]],
    authority_path: Path,
) -> list[str]:
    errors: list[str] = []
    if not authority_path.is_file():
        return [f"authority file does not exist: {authority_path}"]
    raw = authority_path.read_bytes()
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        return [f"authority is not strict UTF-8: {exc}"]
    digest = hashlib.sha256(raw).hexdigest()
    if digest != EXPECTED_AUTHORITY_SHA256:
        errors.append(
            f"authority SHA-256 mismatch: expected {EXPECTED_AUTHORITY_SHA256}, got {digest}"
        )
    lines = text.splitlines()
    if len(lines) != EXPECTED_AUTHORITY_LINE_COUNT:
        errors.append(
            "authority line count mismatch: expected "
            f"{EXPECTED_AUTHORITY_LINE_COUNT}, got {len(lines)}"
        )
    authority = document.get("authority")
    if isinstance(authority, dict):
        if authority.get("sha256") != EXPECTED_AUTHORITY_SHA256:
            errors.append("ledger authority.sha256 does not match the locked snapshot")
        if authority.get("line_count") != EXPECTED_AUTHORITY_LINE_COUNT:
            errors.append("ledger authority.line_count does not match the locked snapshot")

    prior_end = 0
    for entry in entries:
        identifier = entry.get("id")
        source_lines = entry.get("source_lines")
        if not isinstance(identifier, str) or not isinstance(source_lines, list):
            continue
        if len(source_lines) != 2 or any(type(value) is not int for value in source_lines):
            continue
        start, end = source_lines
        if start <= prior_end:
            errors.append(f"{identifier} authority range overlaps the prior entry")
        prior_end = end
        if start > len(lines) or end > len(lines):
            errors.append(f"{identifier} authority range exceeds the locked snapshot")
            continue
        expected_prefix = _expected_heading_prefix(identifier)
        heading = lines[start - 1]
        if not heading.startswith(expected_prefix):
            errors.append(f"{identifier} source start does not match heading: {heading!r}")
    return errors


def _flatten_entries(
    document: dict[str, object],
) -> tuple[list[dict[str, object]], list[str]]:
    errors: list[str] = []
    flattened: list[dict[str, object]] = []
    sections = document.get("sections")
    if not isinstance(sections, list):
        return [], ["sections must be a list"]

    group_ids: list[str] = []
    for group in sections:
        if not isinstance(group, dict):
            errors.append("each section group must be an object")
            continue
        group_id = group.get("id")
        if isinstance(group_id, str):
            group_ids.append(group_id)
        entries = group.get("entries")
        if not isinstance(entries, list) or not entries:
            errors.append(f"section group {group_id!r} must have entries")
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                errors.append(f"section group {group_id!r} contains a non-object entry")
                continue
            resolved = dict(entry)
            for key in ("status", "boundary", "evidence_refs", "blockers"):
                resolved.setdefault(key, group.get(f"default_{key}"))
            resolved["section_group"] = group_id
            flattened.append(resolved)

    if tuple(group_ids) != EXPECTED_SECTION_GROUP_IDS:
        errors.append(
            f"section groups must be the exact ordered sequence 0 through 48; got {group_ids!r}"
        )

    appendices = document.get("appendices")
    if not isinstance(appendices, list):
        errors.append("appendices must be a list")
    else:
        for entry in appendices:
            if not isinstance(entry, dict):
                errors.append("each appendix must be an object")
                continue
            flattened.append(dict(entry))
    return flattened, errors


def _validate_evidence_sets(document: dict[str, object], root: Path) -> tuple[set[str], list[str]]:
    errors: list[str] = []
    evidence_sets = document.get("evidence_sets")
    if not isinstance(evidence_sets, dict) or not evidence_sets:
        return set(), ["evidence_sets must be a non-empty object"]
    known: set[str] = set()
    for name, paths in evidence_sets.items():
        if not isinstance(name, str) or not name:
            errors.append("evidence set names must be non-empty strings")
            continue
        known.add(name)
        if not _is_nonempty_strings(paths):
            errors.append(f"evidence set {name} must contain non-empty paths")
            continue
        assert isinstance(paths, list)
        if len(paths) != len(set(paths)):
            errors.append(f"evidence set {name} contains duplicate paths")
        for value in paths:
            assert isinstance(value, str)
            path = PurePosixPath(value)
            if path.is_absolute() or ".." in path.parts or "\\" in value:
                errors.append(f"evidence path must be safe and repository-relative: {value}")
                continue
            if not (root / Path(*path.parts)).is_file():
                errors.append(f"evidence path does not exist: {value}")
    return known, errors


def validate_document(document: dict[str, object], root: Path = ROOT) -> list[str]:
    """Return all subsection-ledger contract violations."""

    errors: list[str] = []
    if document.get("schema_version") != "1.0.0":
        errors.append("schema_version must be 1.0.0")
    if document.get("ledger_kind") != "v4_subsection_requirement_traceability":
        errors.append("unexpected ledger_kind")
    authority = document.get("authority")
    if not isinstance(authority, dict) or not str(authority.get("path", "")).endswith(
        AUTHORITY_BASENAME
    ):
        errors.append("ledger does not name the exact v4 authority masterplan")
    elif authority.get("sha256") != EXPECTED_AUTHORITY_SHA256:
        errors.append("authority.sha256 must retain the locked masterplan digest")
    elif authority.get("line_count") != EXPECTED_AUTHORITY_LINE_COUNT:
        errors.append("authority.line_count must retain the locked masterplan line count")
    release = document.get("release")
    if not isinstance(release, dict):
        errors.append("release must be an object")
    else:
        if release.get("verdict") != "Production Reject":
            errors.append("release verdict must remain Production Reject")
        if release.get("promotion_authorized") is not False:
            errors.append("promotion_authorized must remain false")

    known_evidence, evidence_errors = _validate_evidence_sets(document, root)
    errors.extend(evidence_errors)
    entries, flatten_errors = _flatten_entries(document)
    errors.extend(flatten_errors)
    identifiers = [entry.get("id") for entry in entries]
    string_ids = [identifier for identifier in identifiers if isinstance(identifier, str)]
    if len(string_ids) != len(entries):
        errors.append("every entry must have a string id")
    counts = Counter(string_ids)
    for counted_identifier, count in sorted(counts.items()):
        if count != 1:
            errors.append(f"entry {counted_identifier} appears {count} times")
    if set(string_ids) != set(EXPECTED_ENTRY_IDS):
        missing = sorted(set(EXPECTED_ENTRY_IDS) - set(string_ids))
        unexpected = sorted(set(string_ids) - set(EXPECTED_ENTRY_IDS))
        if missing:
            errors.append(f"missing exact subsection ids: {missing}")
        if unexpected:
            errors.append(f"unexpected subsection ids: {unexpected}")
    if len(entries) != len(EXPECTED_ENTRY_IDS):
        errors.append(f"expected {len(EXPECTED_ENTRY_IDS)} entries, got {len(entries)}")

    prior_start = 0
    total_requirements = 0
    for entry in entries:
        raw_identifier = entry.get("id")
        if not isinstance(raw_identifier, str):
            continue
        identifier = raw_identifier
        title = entry.get("title")
        if not isinstance(title, str) or not title.strip():
            errors.append(f"{identifier} must have a non-empty title")
        source_lines = entry.get("source_lines")
        if (
            not isinstance(source_lines, list)
            or len(source_lines) != 2
            or any(type(value) is not int for value in source_lines)
            or source_lines[0] < 1
            or source_lines[1] < source_lines[0]
        ):
            errors.append(f"{identifier} has invalid source_lines")
        else:
            start = source_lines[0]
            if start <= prior_start:
                errors.append(f"{identifier} source_lines are not in authority order")
            prior_start = start

        requirements = entry.get("requirements")
        if not _is_nonempty_strings(requirements):
            errors.append(f"{identifier} must have non-empty requirements")
            requirement_count = 0
        else:
            assert isinstance(requirements, list)
            requirement_count = len(requirements)
            total_requirements += requirement_count
            if len(requirements) != len(set(requirements)):
                errors.append(f"{identifier} contains duplicate requirements")
        expected_count = EXPECTED_REQUIREMENT_COUNTS.get(identifier)
        if expected_count is not None and requirement_count != expected_count:
            errors.append(
                f"{identifier} must retain {expected_count} requirements; got {requirement_count}"
            )

        status = entry.get("status")
        boundary = entry.get("boundary")
        evidence_refs = entry.get("evidence_refs")
        blockers = entry.get("blockers")
        if status not in VALID_STATUSES:
            errors.append(f"{identifier} has invalid status {status!r}")
        if boundary not in VALID_BOUNDARIES:
            errors.append(f"{identifier} has invalid boundary {boundary!r}")
        if not _is_nonempty_strings(evidence_refs):
            errors.append(f"{identifier} must reference evidence")
        else:
            assert isinstance(evidence_refs, list)
            unknown = sorted(set(evidence_refs) - known_evidence)
            if unknown:
                errors.append(f"{identifier} references unknown evidence sets: {unknown}")
        if status == "implemented":
            verification_refs = entry.get("verification_refs")
            if not _is_nonempty_strings(verification_refs):
                errors.append(f"{identifier} cannot be implemented without verification_refs")
            elif isinstance(verification_refs, list):
                unknown = sorted(set(verification_refs) - known_evidence)
                if unknown:
                    errors.append(f"{identifier} has unknown verification_refs: {unknown}")
            if blockers not in ([], None):
                errors.append(f"{identifier} cannot be implemented with blockers")
        elif not _is_nonempty_strings(blockers):
            errors.append(f"{identifier} must state a concrete blocker")
        if status == "external-evidence-required" and boundary != "external":
            errors.append(f"{identifier} external-evidence-required must use external boundary")

    if total_requirements != EXPECTED_TOTAL_REQUIREMENTS:
        errors.append(
            f"expected {EXPECTED_TOTAL_REQUIREMENTS} requirement items, got {total_requirements}"
        )
    return errors


def validate_repository(root: Path = ROOT, authority_path: Path | None = None) -> list[str]:
    """Validate the checked-in subsection ledger and all referenced evidence."""

    path = root / LEDGER_PATH.relative_to(ROOT)
    document, errors = _load_document(path)
    if document is not None:
        errors.extend(validate_document(document, root))
        entries, _flatten_errors = _flatten_entries(document)
        candidate = authority_path
        if candidate is None:
            authority = document.get("authority")
            configured_path = authority.get("path") if isinstance(authority, dict) else None
            if isinstance(configured_path, str):
                configured_candidate = Path(configured_path)
                if configured_candidate.is_file():
                    candidate = configured_candidate
        if candidate is not None:
            errors.extend(_validate_authority_snapshot(document, entries, candidate))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate the Structara v4 subsection requirement ledger."
    )
    parser.add_argument(
        "--authority",
        type=Path,
        help="Strictly compare line ranges and SHA-256 with an authority file.",
    )
    args = parser.parse_args()
    errors = validate_repository(authority_path=args.authority)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(
        "v4 subsection ledger valid: "
        f"{len(EXPECTED_ENTRY_IDS)} entries, "
        f"{EXPECTED_TOTAL_REQUIREMENTS} requirement items; "
        "verdict=Production Reject"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
