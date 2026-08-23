"""§5.2 (4) conflicting candidates: same stem, different content hashes."""

from __future__ import annotations

from typing import Any

from .identity import stem_of
from .inventory import FileRecord
from .models import HEURISTIC_LABEL


def analyze(records: list[FileRecord], digests: dict[str, str]) -> dict[str, Any]:
    grouped: dict[str, list[FileRecord]] = {}
    for record in records:
        digest = digests.get(record.rel_path)
        if digest is None:
            continue  # unhashable files take no part in conflict detection
        grouped.setdefault(stem_of(record.rel_path).casefold(), []).append(record)

    out_groups: list[dict[str, Any]] = []
    for stem, members in sorted(grouped.items()):
        if len(members) < 2:
            continue
        member_rows = sorted(
            (
                {
                    "path": m.rel_path,
                    "sha256": digests[m.rel_path],
                    "size_bytes": m.size_bytes,
                }
                for m in members
            ),
            key=lambda row: str(row["path"]),
        )
        distinct_hashes = {row["sha256"] for row in member_rows}
        if len(distinct_hashes) <= 1:
            continue  # identical copies belong to the duplicates section
        suffixes = {m.suffix for m in members}
        severity = "warn" if len(suffixes) < len(member_rows) else "info"
        out_groups.append({"stem": stem, "severity": severity, "members": member_rows})

    return {
        "label": HEURISTIC_LABEL,
        "groups": out_groups,
        "note": "same case-folded file stem with >=2 distinct sha256 content hashes",
    }
