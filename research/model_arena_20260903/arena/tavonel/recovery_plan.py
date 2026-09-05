"""Plan the recovery work that replay cannot fake (MP section 24; contract 3.6).

Some recoveries are a selection over outputs that already exist — those are
handled by ``replay.py`` at no extra cost. These are not: overlap tiling, a
crop, a region extract, a higher-DPI rerender, an alternative prompt and a
safer config all need **new inference** on the page.

This module only plans them. It runs nothing, spends nothing, and touches no
GPU: it emits contract 3.6 rows with a ``recovery_job_id`` for the controller
to execute later, and their cost stays separated from the base arena cost.

Every ``recovery_config`` names a *strategy* rather than fabricated geometry.
This lane has no bounding boxes and will not invent one to fill a field.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from arena.constants import CAMPAIGN_ID
from arena.tavonel import freeze, guards, jsonio, variants
from arena.tavonel.errors import MissingInputError
from arena.tavonel.paths import ArenaPaths

RECOVERY_ROW_SCHEMA = "tavonel.arena.recovery-job.v1"

# Named, uncalibrated recovery parameters. Nothing here has been measured.
RECOVERY_CONFIGS: Mapping[str, Mapping[str, Any]] = {
    "overlap_tiling": {
        "axis": "vertical",
        "calibrated": False,
        "overlap_ratio": 0.15,
        "strategy": "split the page into overlapping tiles and stitch the outputs",
        "tiles": 2,
    },
    "crop": {
        "calibrated": False,
        "margin_ratio": 0.02,
        "region_selection": "largest_table_region_detected_at_execution",
        "strategy": "re-run the page cropped to its dominant region",
    },
    "region_extract": {
        "calibrated": False,
        "margin_ratio": 0.02,
        "max_regions": 4,
        "region_selection": "table_regions_detected_at_execution",
        "strategy": "re-run each detected table region separately",
    },
    "higher_dpi": {
        "calibrated": False,
        "max_long_side_px": 4096,
        "render_scale": 2.0,
        "strategy": "re-render the source page at a higher scale before inference",
    },
    "alternative_prompt": {
        "calibrated": False,
        "prompt_id_resolved_at_execution": True,
        "prompt_strategy": "the model's alternate official prompt from prompt_registry",
        "strategy": "re-run with the model's other official prompt",
    },
    "safer_config": {
        "batch_size": 1,
        "calibrated": False,
        "max_concurrency_per_worker": 1,
        "max_tokens_scale": 0.75,
        "strategy": "re-run with the conservative runtime settings",
    },
}


@dataclass(frozen=True, slots=True)
class RecoveryPlanReport:
    variant: str
    variant_plan_path: Path
    merged_plan_path: Path
    row_count: int
    merged_row_count: int
    type_counts: Mapping[str, int]


def _config_for(recovery_type: str) -> tuple[dict[str, Any], str]:
    config = RECOVERY_CONFIGS.get(recovery_type)
    if config is None:
        raise MissingInputError(f"no recovery config defined for type {recovery_type!r}")
    payload = dict(config)
    return payload, jsonio.prefixed(jsonio.json_sha256_hex(payload))


def _base_job_id(paths: ArenaPaths, model_key: str, case_key: str) -> str:
    """The primary run's ``inference_job_id``, read from its signals record."""
    signals_path = paths.signals_path(model_key, case_key)
    if signals_path.is_file():
        record = guards.read_json_guarded(signals_path, what="signals record")
        run = record.get("run")
        if isinstance(run, dict) and isinstance(run.get("inference_job_id"), str):
            return str(run["inference_job_id"])
    receipt_path = paths.receipt_path(model_key, case_key)
    if receipt_path.is_file():
        receipt = guards.read_json_guarded(receipt_path, what="page receipt")
        if isinstance(receipt.get("inference_job_id"), str):
            return str(receipt["inference_job_id"])
    raise MissingInputError(
        f"{model_key}/{case_key}: no inference_job_id in the signals record or the page "
        "receipt, so a recovery job cannot be bound to the run it recovers"
    )


def build_recovery_rows(
    paths: ArenaPaths,
    decisions: Sequence[Mapping[str, Any]],
    *,
    round_number: int = 1,
) -> list[dict[str, Any]]:
    """Contract 3.6 rows for every page whose frozen decision asked for recovery."""
    rows: list[dict[str, Any]] = []
    for record in sorted(decisions, key=lambda item: str(item["case_key"])):
        types = record.get("recovery_types") or []
        if not record.get("recovery_required") or not isinstance(types, list):
            continue
        case_key = str(record["case_key"])
        model_key = str(record.get("primary"))
        base_job_id = _base_job_id(paths, model_key, case_key)
        for recovery_type in types:
            if not isinstance(recovery_type, str):
                continue
            config, config_sha = _config_for(recovery_type)
            job_id = jsonio.json_sha256_hex(
                {
                    "campaign_id": CAMPAIGN_ID,
                    "inference_job_id_of_base": base_job_id,
                    "recovery_config_sha256": config_sha,
                    "recovery_type": recovery_type,
                    "round": round_number,
                }
            )
            rows.append(
                {
                    "schema": RECOVERY_ROW_SCHEMA,
                    "recovery_job_id": job_id,
                    "base_inference_job_id": base_job_id,
                    "case_key": case_key,
                    "sample_id": record.get("sample_id"),
                    "model_key": model_key,
                    "recovery_type": recovery_type,
                    "recovery_config": config,
                    "recovery_config_sha256": config_sha,
                    "round": round_number,
                    "trigger_signals": list(record.get("escalation_reason") or []),
                    "planned_before_gt": True,
                }
            )
    return rows


def _merge_plans(paths: ArenaPaths, fresh: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Union of every per-variant plan on disk, deduplicated by recovery_job_id."""
    merged: dict[str, dict[str, Any]] = {}
    for variant in variants.VARIANT_IDS:
        path = paths.variant_recovery_plan(variant)
        if not path.is_file():
            continue
        for row in guards.iter_jsonl_guarded(path, what="recovery plan"):
            job_id = row.get("recovery_job_id")
            if isinstance(job_id, str):
                merged[job_id] = dict(row)
    for fresh_row in fresh:
        job_id = fresh_row.get("recovery_job_id")
        if isinstance(job_id, str):
            merged[job_id] = dict(fresh_row)
    return [merged[key] for key in sorted(merged)]


def plan_recovery(
    paths: ArenaPaths, *, variant: str, round_number: int = 1
) -> RecoveryPlanReport:
    """Write the recovery plan for one frozen variant, and refresh the merged plan."""
    canonical_variant = variants.normalize_variant(variant)
    decisions = freeze.load_route_decisions(paths, canonical_variant)
    rows = build_recovery_rows(paths, decisions, round_number=round_number)

    variant_path = paths.variant_recovery_plan(canonical_variant)
    jsonio.write_jsonl_atomic(variant_path, rows)

    merged = _merge_plans(paths, rows)
    jsonio.write_jsonl_atomic(paths.recovery_plan, merged)

    counts: dict[str, int] = {}
    for row in rows:
        recovery_type = str(row["recovery_type"])
        counts[recovery_type] = counts.get(recovery_type, 0) + 1

    return RecoveryPlanReport(
        variant=canonical_variant,
        variant_plan_path=variant_path,
        merged_plan_path=paths.recovery_plan,
        row_count=len(rows),
        merged_row_count=len(merged),
        type_counts=dict(sorted(counts.items())),
    )


__all__ = [
    "RECOVERY_CONFIGS",
    "RECOVERY_ROW_SCHEMA",
    "RecoveryPlanReport",
    "build_recovery_rows",
    "plan_recovery",
]
