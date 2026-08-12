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

MASTERPLAN_STATES = {
    "EVIDENCED",
    "IMPLEMENTED-LOCAL",
    "SHADOW",
    "TARGET-DESIGN",
    "EXTERNAL-BLOCKED",
    "PRODUCTION-REJECT",
    "PRODUCTION-APPROVED",
}

# The user delegated the website and visual-design work to another session. These
# source ranges are still indexed, but are explicitly excluded from this branch's
# execution scope instead of being silently counted as unfinished backend work.
OUT_OF_SCOPE_DESIGN_RANGES = (
    (335, 669),
    (2889, 2980),
    (3287, 4997),
    (5073, 5857),
    (5911, 6627),
    (6655, 7043),
)
MIXED_SCOPE_RANGES = ((7056, 7653),)
EXECUTION_SCOPES = {"NON_DESIGN", "MIXED", "OUT_OF_SCOPE_DESIGN"}

DEFAULT_MASTERPLAN_STATE = {
    "DONE": "EVIDENCED",
    "PARTIAL": "IMPLEMENTED-LOCAL",
    "OPEN": "TARGET-DESIGN",
    "EXTERNAL_BLOCKED": "EXTERNAL-BLOCKED",
    "APPROVAL_REQUIRED": "EXTERNAL-BLOCKED",
    "NOT_APPLICABLE": "EVIDENCED",
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


def execution_scope(line: int) -> str:
    if any(start <= line <= end for start, end in OUT_OF_SCOPE_DESIGN_RANGES):
        return "OUT_OF_SCOPE_DESIGN"
    if any(start <= line <= end for start, end in MIXED_SCOPE_RANGES):
        return "MIXED"
    return "NON_DESIGN"


def traceability_role(kind: str) -> str:
    return {
        "heading": "SECTION_ANCHOR",
        "checkbox": "ACCEPTANCE_ITEM",
        "normative": "NORMATIVE_CONSTRAINT",
    }[kind]


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
            normalized_kind = {"H": "heading", "C": "checkbox", "N": "normative"}[kind]
            text = str(value["text"])
            role = traceability_role(normalized_kind)
            if normalized_kind == "normative" and text.lstrip().startswith("#"):
                role = "SECTION_ANCHOR_ALIAS"
            if normalized_kind == "normative" and 102 <= line <= 113:
                role = "INFORMATIONAL_DEFINITION"
            scope = execution_scope(line)
            out_of_scope = scope == "OUT_OF_SCOPE_DESIGN"
            rows.append(
                {
                    "requirement_id": row_id(kind, line),
                    "kind": normalized_kind,
                    "traceability_role": role,
                    "execution_scope": scope,
                    "source_line": line,
                    "text": text,
                    "status": "NOT_APPLICABLE" if out_of_scope else "OPEN",
                    "masterplan_state": "TARGET-DESIGN",
                    "owner": "design-session" if out_of_scope else "implementation",
                    "evidence": [],
                    "blocker": (
                        "Delegated to the separate UI/UX session."
                        if out_of_scope
                        else "explicit evidence mapping pending"
                    ),
                    "notes": (
                        "Indexed for coverage but excluded from the non-design branch."
                        if out_of_scope
                        else ""
                    ),
                    "inherited_from": "",
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

    resolved_overrides: dict[str, dict[str, Any]] = {}

    def resolve_override(requirement_id: str, trail: tuple[str, ...] = ()) -> dict[str, Any]:
        cached = resolved_overrides.get(requirement_id)
        if cached is not None:
            return cached
        if requirement_id in trail:
            cycle = " -> ".join((*trail, requirement_id))
            raise ValueError(f"cyclic requirement override inheritance: {cycle}")
        raw = override_rows[requirement_id]
        if not isinstance(raw, dict):
            raise ValueError(f"override must be an object: {requirement_id}")
        parent_id = str(raw.get("inherits", "")).strip()
        inherited: dict[str, Any] = {}
        if parent_id:
            if parent_id not in override_rows:
                raise ValueError(
                    f"override inheritance target is not explicitly mapped: "
                    f"{requirement_id} -> {parent_id}"
                )
            inherited = resolve_override(parent_id, (*trail, requirement_id))
        resolved = {**inherited, **{key: value for key, value in raw.items() if key != "inherits"}}
        if parent_id:
            resolved["inherited_from"] = parent_id
        resolved_overrides[requirement_id] = resolved
        return resolved

    for requirement_id in override_rows:
        override = resolve_override(requirement_id)
        status = str(override.get("status", ""))
        if status not in STATUSES:
            raise ValueError(f"invalid status for {requirement_id}: {status}")
        masterplan_state = str(
            override.get("masterplan_state", DEFAULT_MASTERPLAN_STATE[status])
        )
        if masterplan_state not in MASTERPLAN_STATES:
            raise ValueError(
                f"invalid masterplan_state for {requirement_id}: {masterplan_state}"
            )
        row_scope = str(override.get("execution_scope", by_id[requirement_id]["execution_scope"]))
        if row_scope not in EXECUTION_SCOPES:
            raise ValueError(f"invalid execution_scope for {requirement_id}: {row_scope}")
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
            masterplan_state=masterplan_state,
            execution_scope=row_scope,
            owner=str(override.get("owner", row["owner"])),
            evidence=evidence,
            blocker=str(override.get("blocker", "")),
            notes=str(override.get("notes", "")),
            inherited_from=str(override.get("inherited_from", "")),
        )

    counts = Counter(row["status"] for row in rows)
    scope_counts = Counter(row["execution_scope"] for row in rows)
    actionable_rows = [
        row
        for row in rows
        if row["traceability_role"]
        in {"ACCEPTANCE_ITEM", "NORMATIVE_CONSTRAINT"}
    ]
    actionable_counts = Counter(row["status"] for row in actionable_rows)
    status_by_scope = {
        scope: {
            status: sum(
                1
                for row in rows
                if row["execution_scope"] == scope and row["status"] == status
            )
            for status in sorted(STATUSES)
        }
        for scope in sorted(scope_counts)
    }
    actionable_status_by_scope = {
        scope: {
            status: sum(
                1
                for row in actionable_rows
                if row["execution_scope"] == scope and row["status"] == status
            )
            for status in sorted(STATUSES)
        }
        for scope in sorted(scope_counts)
    }
    result = {
        "schema_version": "2.1",
        "generated_at": datetime.now(UTC).isoformat(),
        "source": source,
        "semantics": {
            "default_status": "OPEN",
            "done_requires_existing_local_evidence": True,
            "external_or_human_approval_may_not_be_self_completed": True,
            "missing_measurements_may_not_be_zero_filled": True,
            "section_anchors_are_not_acceptance_items": True,
            "design_rows_remain_indexed_but_are_out_of_scope_for_this_branch": True,
            "masterplan_state_vocabulary": sorted(MASTERPLAN_STATES),
            "ledger_sha256_excludes_generated_at": True,
        },
        "counts": {
            "total": len(rows),
            **{status: counts.get(status, 0) for status in sorted(STATUSES)},
        },
        "scope_counts": dict(sorted(scope_counts.items())),
        "status_by_scope": status_by_scope,
        "actionable_status_by_scope": actionable_status_by_scope,
        "actionable_counts": {
            "total": len(actionable_rows),
            **{status: actionable_counts.get(status, 0) for status in sorted(STATUSES)},
        },
        "requirements": rows,
    }
    result["ledger_sha256"] = canonical_sha256(
        {key: value for key, value in result.items() if key != "generated_at"}
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
