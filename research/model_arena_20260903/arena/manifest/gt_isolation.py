"""GT isolation audit (masterplan section 2.1, ``ARENA_CONTRACT.md`` section 1).

Fail-closed: every check runs independently of the builder's in-memory state
(it re-parses the written ``source_manifest.jsonl`` and re-walks the staged
input directories from scratch) so a bug that only manifests on disk is still
caught. The audit records ground-truth and evaluator directory *paths* only —
it never opens a file under them.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from arena.manifest.schema_fields import SOURCE_ROW_FIELDS

_SCHEMA = "tavonel.arena.gt-isolation-receipt.v1"
_ALLOWED_TOP_LEVEL_NAME = "inference-input-manifest.json"


class GtIsolationError(RuntimeError):
    """Raised when the audit cannot even be attempted (e.g. missing inputs)."""


@dataclass(frozen=True, slots=True)
class AuditCheck:
    name: str
    passed: bool
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "passed": self.passed, "detail": self.detail}


def _is_contained(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def _check_inputs_root_contents(benchmark: str, inputs_root: Path) -> AuditCheck:
    if not inputs_root.is_dir():
        return AuditCheck(
            name=f"inputs-root-whitelist:{benchmark}",
            passed=False,
            detail=f"inputs root does not exist: {inputs_root}",
        )
    violations: list[str] = []
    inputs_subdir = (inputs_root / "inputs").resolve()
    root_resolved = inputs_root.resolve()
    for path in inputs_root.rglob("*"):
        if not path.is_file():
            continue
        resolved = path.resolve()
        if resolved.parent == root_resolved and resolved.name == _ALLOWED_TOP_LEVEL_NAME:
            continue
        if _is_contained(resolved, inputs_subdir) and resolved.suffix.casefold() == ".png":
            continue
        violations.append(str(resolved))
    if violations:
        return AuditCheck(
            name=f"inputs-root-whitelist:{benchmark}",
            passed=False,
            detail=f"non-whitelisted file(s) inside inputs root: {violations[:10]}",
        )
    return AuditCheck(
        name=f"inputs-root-whitelist:{benchmark}",
        passed=True,
        detail=f"only .png files and {_ALLOWED_TOP_LEVEL_NAME} present under {inputs_root}",
    )


def _check_no_path_overlap(
    inputs_roots: Mapping[str, Path], acquired_root: Path, evaluator_cache_root: Path
) -> AuditCheck:
    violations: list[str] = []
    gt_roots = (("acquired", acquired_root), ("evaluator_cache", evaluator_cache_root))
    for gt_label, gt_root in gt_roots:
        for benchmark, inputs_root in inputs_roots.items():
            if _is_contained(gt_root, inputs_root):
                violations.append(f"{gt_label} root is inside inputs root of {benchmark}")
            if _is_contained(inputs_root, gt_root):
                violations.append(f"inputs root of {benchmark} is inside {gt_label} root")
    if violations:
        return AuditCheck(name="gt-inputs-path-overlap", passed=False, detail="; ".join(violations))
    return AuditCheck(
        name="gt-inputs-path-overlap",
        passed=True,
        detail="no containment between GT/evaluator roots and any inputs root",
    )


def _check_source_manifest_fields(source_manifest_path: Path) -> tuple[AuditCheck, int, int]:
    if not source_manifest_path.is_file():
        raise GtIsolationError(f"source manifest is missing: {source_manifest_path}")
    sample_ids: set[str] = set()
    case_keys: set[str] = set()
    duplicate_sample_ids: list[str] = []
    duplicate_case_keys: list[str] = []
    field_violations: list[str] = []
    row_count = 0
    with source_manifest_path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            row_count += 1
            row: Any = json.loads(line)
            if not isinstance(row, dict):
                field_violations.append(f"line {line_number}: row is not an object")
                continue
            keys = set(row.keys())
            if keys != SOURCE_ROW_FIELDS:
                extra = keys - SOURCE_ROW_FIELDS
                missing = SOURCE_ROW_FIELDS - keys
                field_violations.append(
                    f"line {line_number}: extra={sorted(extra)} missing={sorted(missing)}"
                )
            sample_id = str(row.get("sample_id"))
            case_key = str(row.get("case_key"))
            if sample_id in sample_ids:
                duplicate_sample_ids.append(sample_id)
            sample_ids.add(sample_id)
            if case_key in case_keys:
                duplicate_case_keys.append(case_key)
            case_keys.add(case_key)

    problems: list[str] = []
    if field_violations:
        problems.append(f"field whitelist violations: {field_violations[:10]}")
    if duplicate_sample_ids:
        problems.append(f"duplicate sample_id: {sorted(set(duplicate_sample_ids))[:10]}")
    if duplicate_case_keys:
        problems.append(f"duplicate case_key: {sorted(set(duplicate_case_keys))[:10]}")

    detail = (
        "; ".join(problems)
        if problems
        else f"{row_count} rows, all fields whitelisted, no duplicates"
    )
    check = AuditCheck(
        name="source-manifest-fields-and-uniqueness", passed=not problems, detail=detail
    )
    return check, row_count, len(sample_ids)


def _check_staged_manifests_gt_free(
    staged_manifests: Mapping[str, Mapping[str, Any]],
) -> AuditCheck:
    violations = [
        benchmark
        for benchmark, manifest in staged_manifests.items()
        if manifest.get("ground_truth_mounted") is not False
    ]
    if violations:
        return AuditCheck(
            name="staged-manifest-gt-free",
            passed=False,
            detail=f"ground_truth_mounted is not false for: {violations}",
        )
    return AuditCheck(
        name="staged-manifest-gt-free",
        passed=True,
        detail=f"ground_truth_mounted == false for all {len(staged_manifests)} staged manifests",
    )


def run_gt_isolation_audit(
    *,
    campaign_id: str,
    inputs_roots: Mapping[str, Path],
    acquired_root: Path,
    evaluator_cache_root: Path,
    source_manifest_path: Path,
    staged_manifests: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    checks: list[AuditCheck] = []
    for benchmark, inputs_root in sorted(inputs_roots.items()):
        checks.append(_check_inputs_root_contents(benchmark, inputs_root))
    checks.append(_check_no_path_overlap(inputs_roots, acquired_root, evaluator_cache_root))
    field_check, row_count, unique_sample_ids = _check_source_manifest_fields(source_manifest_path)
    checks.append(field_check)
    checks.append(_check_staged_manifests_gt_free(staged_manifests))

    passed = all(check.passed for check in checks)
    return {
        "schema": _SCHEMA,
        "campaign_id": campaign_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "passed": passed,
        "row_count": row_count,
        "unique_sample_id_count": unique_sample_ids,
        "checks": [check.as_dict() for check in checks],
        "gt_roots": [str(acquired_root), str(evaluator_cache_root)],
        "inputs_roots": [str(path) for _benchmark, path in sorted(inputs_roots.items())],
    }


def write_receipt(receipt: dict[str, Any], receipts_dir: Path) -> Path:
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    receipts_dir.mkdir(parents=True, exist_ok=True)
    path = receipts_dir / f"gt-isolation-{ts}.json"
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(tmp, path)
    return path


__all__ = ["GtIsolationError", "run_gt_isolation_audit", "write_receipt"]
