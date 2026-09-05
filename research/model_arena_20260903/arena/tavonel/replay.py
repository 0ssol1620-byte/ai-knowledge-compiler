"""Offline composite replay of a frozen route set (MP section 23).

Every model already produced its output once. A TAVONEL variant is therefore a
*selection* over those frozen files, not a new inference run — which is the
campaign's largest cost saving and the reason the route decisions had to be
frozen first.

This writes two things per variant:

* ``tavonel/adaptive_replay/<variant>/manifest.jsonl`` — one row per page
  naming the chosen model, the frozen file it points at and that file's hash;
* ``tavonel/adaptive_replay/<variant>/canonical/<case_key>.md`` — a **copy**
  (not a symlink: the scoring lane must see a plain tree, and Windows hosts
  cannot be assumed to allow links) so lane E2 can score the composite exactly
  as if it were another model.

A page whose chosen model has no frozen output is written as ``unresolved``
with a reason. It is never filled with the primary's text and never emitted as
an empty file: an unresolved page must stay visible (CLAUDE.md, fail closed).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from arena.constants import CAMPAIGN_ID
from arena.tavonel import freeze, guards, jsonio, outputs, variants
from arena.tavonel.errors import IntegrityError
from arena.tavonel.paths import ArenaPaths

REPLAY_ROW_SCHEMA = "tavonel.arena.replay-row.v1"
REPLAY_SUMMARY_SCHEMA = "tavonel.arena.replay-summary.v1"


@dataclass(frozen=True, slots=True)
class ReplayReport:
    variant: str
    manifest_path: Path
    canonical_dir: Path
    summary_path: Path
    total: int
    resolved: int
    unresolved: int
    manifest_sha256: str
    model_page_counts: Mapping[str, int]


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def replay_variant(paths: ArenaPaths, *, variant: str) -> ReplayReport:
    """Materialise the composite output tree for one frozen variant."""
    canonical_variant = variants.normalize_variant(variant)
    decisions = freeze.load_route_decisions(paths, canonical_variant)
    available = outputs.load_outputs(paths)
    oracle = variants.is_oracle(canonical_variant)

    rows: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    resolved = 0

    for record in sorted(decisions, key=lambda item: str(item["case_key"])):
        case_key = str(record["case_key"])
        chosen_model = str(record["final_model"])
        ref = available.get(chosen_model, {}).get(case_key)
        row: dict[str, Any] = {
            "schema": REPLAY_ROW_SCHEMA,
            "campaign_id": CAMPAIGN_ID,
            "variant": canonical_variant,
            "case_key": case_key,
            "sample_id": record.get("sample_id"),
            "benchmark": record.get("benchmark"),
            "primary_model_key": record.get("primary"),
            "chosen_model_key": chosen_model,
            "final_model": chosen_model,
            "decision": record.get("decision"),
            "decision_sha256": record.get("decision_sha256"),
            "escalation_stage": record.get("escalation_stage"),
            "number_of_model_calls": record.get("number_of_model_calls"),
            "recovery_required": record.get("recovery_required", False),
            "recovery_types": record.get("recovery_types", []),
        }
        if oracle:
            row["deployability"] = variants.ORACLE_LABEL

        if ref is None:
            row.update(
                {
                    "unresolved": True,
                    "unresolved_reason": (
                        f"no frozen output for {chosen_model} on this page; the composite has "
                        "no text for it and it must not be counted as a success"
                    ),
                    "chosen_canonical_path": None,
                    "chosen_canonical_sha256": None,
                    "chosen_raw_path": None,
                    "chosen_raw_sha256": None,
                    "composite_canonical_path": None,
                    "composite_canonical_sha256": None,
                }
            )
            rows.append(row)
            continue

        guards.assert_readable(ref.canonical_path)
        data = ref.canonical_path.read_bytes()
        digest = jsonio.prefixed(jsonio.sha256_hex(data))
        if ref.canonical_sha256 is not None and ref.canonical_sha256 != digest:
            raise IntegrityError(
                f"{ref.canonical_path}: the bytes on disk hash to {digest} but the frozen "
                f"manifest recorded {ref.canonical_sha256}"
            )
        destination = paths.replay_canonical_path(canonical_variant, case_key)
        composite_sha = jsonio.write_bytes_atomic(destination, data)
        resolved += 1
        counts[chosen_model] = counts.get(chosen_model, 0) + 1
        row.update(
            {
                "unresolved": False,
                "unresolved_reason": None,
                "output_source": ref.source,
                "chosen_canonical_path": _relative(ref.canonical_path, paths.root),
                "chosen_canonical_sha256": digest,
                "chosen_raw_path": (
                    None if ref.raw_path is None else _relative(ref.raw_path, paths.root)
                ),
                "chosen_raw_sha256": ref.raw_sha256,
                "composite_canonical_path": _relative(destination, paths.root),
                "composite_canonical_sha256": composite_sha,
            }
        )
        rows.append(row)

    manifest_path = paths.replay_manifest(canonical_variant)
    manifest_sha = jsonio.write_jsonl_atomic(manifest_path, rows)

    summary: dict[str, Any] = {
        "schema": REPLAY_SUMMARY_SCHEMA,
        "campaign_id": CAMPAIGN_ID,
        "variant": canonical_variant,
        "variant_directory": variants.variant_dir_name(canonical_variant),
        "manifest_sha256": manifest_sha,
        "total_cases": len(rows),
        "resolved_cases": resolved,
        "unresolved_cases": len(rows) - resolved,
        "pages_per_model": dict(sorted(counts.items())),
        "composite_layout": "canonical/<case_key>.md (copies, not links)",
    }
    if oracle:
        summary["deployability"] = variants.ORACLE_LABEL
    jsonio.write_json_atomic(paths.replay_summary(canonical_variant), summary)

    return ReplayReport(
        variant=canonical_variant,
        manifest_path=manifest_path,
        canonical_dir=paths.replay_canonical_dir(canonical_variant),
        summary_path=paths.replay_summary(canonical_variant),
        total=len(rows),
        resolved=resolved,
        unresolved=len(rows) - resolved,
        manifest_sha256=manifest_sha,
        model_page_counts=dict(sorted(counts.items())),
    )


__all__ = ["REPLAY_ROW_SCHEMA", "REPLAY_SUMMARY_SCHEMA", "ReplayReport", "replay_variant"]
