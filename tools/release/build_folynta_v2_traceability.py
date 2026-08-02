"""Build a fail-closed, line-addressable FOLYNTA v2 traceability ledger.

Every indexed heading, checkbox, and normative statement becomes a ledger row.
Rows are OPEN unless an explicit override supplies a truthful status and local
evidence. DONE is rejected when any referenced local artifact is missing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

STATUSES = {
    "DONE",
    "PARTIAL",
    "OPEN",
    "EXTERNAL_BLOCKED",
    "APPROVAL_REQUIRED",
    "NOT_APPLICABLE",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("index", type=Path)
    parser.add_argument("overrides", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    return parser.parse_args()


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def row_id(kind: str, line: int) -> str:
    return f"{kind}-{line:04d}"


def normalize_evidence(repo_root: Path, evidence: object) -> list[dict[str, str]]:
    if not isinstance(evidence, list):
        raise ValueError("evidence must be a list")
    normalized: list[dict[str, str]] = []
    for item in evidence:
        if not isinstance(item, dict):
            raise ValueError("evidence entries must be objects")
        path = str(item.get("path", "")).strip().replace("\\", "/")
        claim = str(item.get("claim", "")).strip()
        if not path or not claim:
            raise ValueError("evidence path and claim are required")
        candidate = (repo_root / path).resolve()
        try:
            candidate.relative_to(repo_root.resolve())
        except ValueError as exc:
            raise ValueError(f"evidence escapes repository: {path}") from exc
        normalized.append(
            {
                "path": path,
                "claim": claim,
                "exists": str(candidate.exists()).lower(),
            }
        )
    return normalized


def build_rows(index: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for kind, source_key in (
        ("H", "headings"),
        ("C", "checkboxes"),
        ("N", "normative_lines"),
    ):
        values = index.get(source_key, [])
        if not isinstance(values, list):
            raise ValueError(f"index {source_key} must be a list")
        for value in values:
            if not isinstance(value, dict):
                raise ValueError(f"index {source_key} entries must be objects")
            line = int(value["line"])
            rows.append(
                {
                    "requirement_id": row_id(kind, line),
                    "kind": {"H": "heading", "C": "checkbox", "N": "normative"}[kind],
                    "source_line": line,
                    "text": str(value["text"]),
                    "status": "OPEN",
                    "owner": "implementation",
                    "evidence": [],
                    "blocker": "explicit evidence mapping pending",
                    "notes": "",
                }
            )
    return sorted(rows, key=lambda row: (row["source_line"], row["kind"]))


def main() -> None:
    args = parse_args()
    repo_root = args.repo_root.resolve()
    index = load_object(args.index)
    overrides = load_object(args.overrides)
    source = index.get("source")
    if not isinstance(source, dict) or not source.get("sha256"):
        raise ValueError("index source identity is missing")
    if overrides.get("source_sha256") != source["sha256"]:
        raise ValueError("override source_sha256 does not match indexed masterplan")

    rows = build_rows(index)
    by_id = {row["requirement_id"]: row for row in rows}
    override_rows = overrides.get("requirements", {})
    if not isinstance(override_rows, dict):
        raise ValueError("override requirements must be an object")
    unknown = sorted(set(override_rows) - set(by_id))
    if unknown:
        raise ValueError(f"unknown requirement overrides: {unknown}")

    for requirement_id, override in override_rows.items():
        if not isinstance(override, dict):
            raise ValueError(f"override must be an object: {requirement_id}")
        status = str(override.get("status", ""))
        if status not in STATUSES:
            raise ValueError(f"invalid status for {requirement_id}: {status}")
        evidence = normalize_evidence(repo_root, override.get("evidence", []))
        if status == "DONE":
            if not evidence:
                raise ValueError(f"DONE requires evidence: {requirement_id}")
            missing = [item["path"] for item in evidence if item["exists"] != "true"]
            if missing:
                raise ValueError(f"DONE evidence missing for {requirement_id}: {missing}")
        row = by_id[requirement_id]
        row.update(
            status=status,
            owner=str(override.get("owner", row["owner"])),
            evidence=evidence,
            blocker=str(override.get("blocker", "")),
            notes=str(override.get("notes", "")),
        )

    counts = Counter(row["status"] for row in rows)
    result = {
        "schema_version": "2.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "source": source,
        "semantics": {
            "default_status": "OPEN",
            "done_requires_existing_local_evidence": True,
            "external_or_human_approval_may_not_be_self_completed": True,
            "missing_measurements_may_not_be_zero_filled": True,
        },
        "counts": {
            "total": len(rows),
            **{status: counts.get(status, 0) for status in sorted(STATUSES)},
        },
        "requirements": rows,
    }
    result["ledger_sha256"] = canonical_sha256(result)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
