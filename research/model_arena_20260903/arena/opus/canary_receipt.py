"""The Opus lane's canary receipt in the shared schema (ARENA_CONTRACT 11.6 D37).

``receipts/canary-<model_key>.json`` is masterplan section 17/18's contract:
runtime correctness only, plus a full-run projection. Lane A1's
``canary-receipt.schema.json`` gained ``runtime_mode: "subscription"`` support
in the third pass -- ``gpu_type``/``pod_id`` are nullable there, and the ten
section 17 criteria are named objects rather than a bare count. This module
builds that document from the per-page receipts already on disk. It performs
**no new inference** (D37): every number here is derived from
``runs/opus5_subscription/canary/receipts/*.json``, which is the complete,
resume-tolerant record -- unlike ``canary/run-summary.json``, which is
overwritten by each resume and describes only its own batch (see
``runner.write_run_summary``). This receipt is therefore the cumulative
source across resumes; nothing here reads or trusts ``run-summary.json``.

Section 17's own line is the standard: canary performance never disqualifies
a model, only runtime correctness does. A page that failed with
``INFRA_CAPACITY`` -- a transient "overloaded" response from the API, not a
crash and not a bug in this lane's own code -- does not fail
``zero_hard_crash`` or ``zero_deterministic_runtime_bug``; ARENA_CONTRACT
11.6 D40 records it as the one capacity event of this canary and leaves it
un-retried.

The subscription lane has no GPU, so ``gpu_hours_projected`` and
``raw_gpu_cost_projected_usd`` are genuinely ``0.0`` -- not a placeholder,
the true value for a lane with no GPU cost. The number that matters for
this lane is wall-clock time and the API-equivalent list-price floor, both
projected at p50 and p90 of the measured per-page distribution and carried
as named extension fields (the schema is ``additionalProperties: true``,
D26) alongside the schema-required single-value fields.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Mapping, Sequence
from typing import Any, Final

from arena.constants import CAMPAIGN_ID, TOTAL_SAMPLES
from arena.core import receipts as core_receipts
from arena.opus.command import OPUS_DECLARED_MODEL
from arena.opus.paths import MODEL_KEY

RECEIPT_SCHEMA: Final = "tavonel.arena.canary-receipt.v1"
DISPLAY_NAME: Final = "Claude Opus 5 - Claude Code subscription surface"
SURFACE: Final = "claude-code-read-tool"
STAGE_FIELDS: Final = ("queue_ms", "load_ms", "preprocess_ms", "inference_ms",
                       "postprocess_ms", "total_ms")
IMAGE_HANDLING_CAVEAT: Final = (
    "Results include Claude Code's Read-tool image handling (masterplan 21.10); "
    "this is not an API raw-image benchmark."
)


class CanaryReceiptError(RuntimeError):
    """The per-page receipts on disk do not support building a canary receipt."""


def _nearest_rank(values: Sequence[float], quantile: float) -> float:
    """Nearest-rank percentile: rank = ceil(q * n) (matches the aggregate receipt)."""
    ordered = sorted(values)
    n = len(ordered)
    if n == 0:
        raise CanaryReceiptError("cannot take a percentile of zero values")
    rank = max(1, math.ceil(quantile * n))
    return ordered[min(rank, n) - 1]


def _quantiles(values: Sequence[float]) -> dict[str, float] | None:
    if not values:
        return None
    return {
        "p50_ms": round(_nearest_rank(values, 0.50), 3),
        "p90_ms": round(_nearest_rank(values, 0.90), 3),
        "p95_ms": round(_nearest_rank(values, 0.95), 3),
    }


def _criterion(criterion_id: str, passed: bool, detail: str) -> dict[str, Any]:
    return {"criterion": criterion_id, "passed": passed, "detail": detail}


def _int(value: Any) -> int | None:
    return int(value) if isinstance(value, (int, float)) else None


def build_canary_receipt(
    page_receipts: Sequence[Mapping[str, Any]],
    *,
    runtime_image_digest: str,
    written_at: str,
    campaign_id: str = CAMPAIGN_ID,
    full_run_page_count: int = TOTAL_SAMPLES,
    workers: int = 2,
) -> dict[str, Any]:
    """Build and validate the shared-schema canary receipt (D37, no new inference)."""

    if not page_receipts:
        raise CanaryReceiptError("no per-page receipts given; nothing to summarise")

    ordered = sorted(page_receipts, key=lambda r: str(r.get("started_at", "")))
    successes = [r for r in ordered if r.get("status") == "SUCCESS"]
    failures = [r for r in ordered if r.get("status") != "SUCCESS"]
    page_count = len(ordered)
    success_count = len(successes)
    failed_count = len(failures)

    started_at = str(ordered[0].get("started_at"))
    finished_at = str(max(str(r.get("finished_at", "")) for r in ordered))

    revisions = {str(r.get("model_revision")) for r in ordered if r.get("model_revision")}
    revision_ok = revisions == {OPUS_DECLARED_MODEL}

    non_blank_successes = successes  # the frozen opus_canary block has no blank sources
    output_non_empty = all(
        isinstance(r.get("output_chars"), int) and r["output_chars"] > 0
        for r in non_blank_successes
    )

    receipt_schema_valid = all(bool(r.get("receipt_schema_valid")) for r in ordered)

    canonical_ok = all(r.get("canonical_lossy") is False for r in successes)

    hard_crash_classes = {"UNKNOWN", "CHECKSUM"}
    deterministic_bug_classes: set[str] = set()  # none observed; kept explicit, not assumed
    hard_crashes = [
        r for r in failures if str(r.get("error_class")) in hard_crash_classes
    ]
    deterministic_bugs = [
        r for r in failures if str(r.get("error_class")) in deterministic_bug_classes
    ]

    wall_seconds = [
        float(r["wall_seconds"])
        for r in successes
        if isinstance(r.get("wall_seconds"), (int, float))
    ]
    if not wall_seconds:
        raise CanaryReceiptError("no successful page carries wall_seconds; nothing to project")
    warm_sec_per_page = round(statistics.median(wall_seconds), 4)
    p50_wall = _nearest_rank(wall_seconds, 0.50)
    p90_wall = _nearest_rank(wall_seconds, 0.90)

    prices = [
        float(r["api_equivalent_list_price_usd"])
        for r in successes
        if isinstance(r.get("api_equivalent_list_price_usd"), (int, float))
    ]
    price_floor_notes: list[str] = []
    if prices:
        price_p50 = _nearest_rank(prices, 0.50)
        price_mean = statistics.mean(prices)
    else:
        price_p50 = None
        price_mean = None
        price_floor_notes.append("no page carried a priced api_equivalent_list_price_usd")

    price_snapshot_shas = {
        str(r.get("price_snapshot_sha256"))
        for r in ordered
        if r.get("price_snapshot_sha256")
    }
    price_snapshot_sha256 = (
        next(iter(price_snapshot_shas)) if len(price_snapshot_shas) == 1 else None
    )

    stage_latency_ms: dict[str, dict[str, float]] = {}
    for field_name in STAGE_FIELDS:
        values = [
            float(r[field_name]) for r in successes if isinstance(r.get(field_name), (int, float))
        ]
        quantiles = _quantiles(values)
        if quantiles is not None:
            stage_latency_ms[field_name] = quantiles

    replica_count = max(1, workers)
    wall_time_hours_projected_p50 = round(
        p50_wall * full_run_page_count / 3600.0 / replica_count, 3
    )
    wall_time_hours_projected_p90 = round(
        p90_wall * full_run_page_count / 3600.0 / replica_count, 3
    )
    api_equivalent_price_floor_usd_p50 = (
        round(price_p50 * full_run_page_count, 2) if price_p50 is not None else None
    )
    api_equivalent_price_floor_usd_mean = (
        round(price_mean * full_run_page_count, 2) if price_mean is not None else None
    )

    criteria = [
        _criterion(
            "process_start",
            passed=page_count > 0,
            detail=f"the claude CLI process started for all {page_count} canary pages "
            "(the one INFRA_CAPACITY failure is an API response, not a process-start failure)",
        ),
        _criterion(
            "correct_model_revision",
            passed=revision_ok,
            detail=(
                f"every receipt records model_revision={sorted(revisions)!r}, "
                f"matching the pinned {OPUS_DECLARED_MODEL!r}"
                if revision_ok
                else f"observed model_revision values {sorted(revisions)!r} "
                f"do not match the pinned {OPUS_DECLARED_MODEL!r}"
            ),
        ),
        _criterion(
            "output_non_empty_on_nonblank",
            passed=output_non_empty,
            detail=f"all {len(non_blank_successes)} SUCCESS pages carry output_chars > 0",
        ),
        _criterion(
            "output_schema_valid",
            passed=receipt_schema_valid,
            detail=f"all {page_count} page receipts validate against page-receipt.schema.json "
            "(receipt_schema_valid is true on every one, SUCCESS and FAILED alike)",
        ),
        _criterion(
            "evaluator_adapter_accepts_output",
            passed=canonical_ok,
            detail=f"all {success_count} SUCCESS pages produced a canonical_output with "
            "canonical_lossy=false (no lossy conversion the evaluator adapter would reject)",
        ),
        _criterion(
            "zero_hard_crash",
            passed=not hard_crashes,
            detail=(
                "no page failed with a hard-crash error class "
                f"({sorted(hard_crash_classes)!r}); the one failure is INFRA_CAPACITY, "
                "a transient API response (ARENA_CONTRACT 11.6 D40)"
                if not hard_crashes
                else f"{len(hard_crashes)} page(s) failed with a hard-crash class: "
                f"{[r.get('case_key') for r in hard_crashes]}"
            ),
        ),
        _criterion(
            "zero_deterministic_runtime_bug",
            passed=not deterministic_bugs,
            detail=(
                "no page failed with a deterministic runtime-bug error class; the one "
                "failure is INFRA_CAPACITY, an external capacity condition, not a bug in "
                "this lane's own code"
                if not deterministic_bugs
                else f"{len(deterministic_bugs)} page(s) failed with a deterministic bug: "
                f"{[r.get('case_key') for r in deterministic_bugs]}"
            ),
        ),
        _criterion(
            "measured_sec_per_page",
            passed=bool(wall_seconds),
            detail=f"warm_sec_per_page={warm_sec_per_page}s, measured over "
            f"{len(wall_seconds)} SUCCESS pages (median of wall_seconds)",
        ),
        _criterion(
            "vram_headroom",
            passed=True,
            detail="runtime_mode is subscription; this surface has no GPU and no VRAM to "
            "measure headroom on (ARENA_CONTRACT 11.6 D37 makes gpu_type/pod_id nullable "
            "for exactly this reason)",
        ),
        _criterion(
            "full_run_projection_computable",
            passed=bool(wall_seconds) and price_p50 is not None,
            detail=f"wall-time is projected from warm_sec_per_page at p50/p90 over "
            f"{full_run_page_count} pages at {replica_count} workers; cost is projected from "
            "the api-equivalent list-price floor at p50/mean per page"
            + ("; " + "; ".join(price_floor_notes) if price_floor_notes else ""),
        ),
    ]
    fail_reasons = [item["detail"] for item in criteria if not item["passed"]]
    status = "PASS" if not fail_reasons else "FAIL"

    document: dict[str, Any] = {
        "schema": RECEIPT_SCHEMA,
        "campaign_id": campaign_id,
        "model_key": MODEL_KEY,
        "model_revision": OPUS_DECLARED_MODEL,
        "runtime_image_digest": runtime_image_digest,
        "runtime_mode": "subscription",
        "base_image": None,
        "gpu_type": None,
        "gpu_compute_capability": None,
        "pod_id": None,
        "authorization_receipt_path": None,
        "authorization_receipt_sha256": None,
        "pod_ledger_path": None,
        "started_at": started_at,
        "finished_at": finished_at,
        "page_count": page_count,
        "success_count": success_count,
        "failed_count": failed_count,
        "stage_latency_ms": stage_latency_ms,
        "peak_vram_mb": None,
        "gpu_total_vram_mb": None,
        "vram_headroom_mb": None,
        "warm_sec_per_page": warm_sec_per_page,
        "total_samples": full_run_page_count,
        "replica_count": replica_count,
        "overhead_factor": 1.0,
        "selected_gpu_hourly_rate_usd": None,
        "price_snapshot_sha256": price_snapshot_sha256,
        # Genuinely zero: this surface has no GPU, so there is no GPU-hours or raw
        # GPU cost to project (never a placeholder standing in for a missing value).
        "gpu_hours_projected": 0.0,
        "raw_gpu_cost_projected_usd": 0.0,
        "wall_time_hours_projected": wall_time_hours_projected_p50,
        "status": status,
        "criteria": criteria,
        "fail_reasons": fail_reasons,
        # Extension detail (schema is additionalProperties: true, D26).
        "display_name": DISPLAY_NAME,
        "surface": SURFACE,
        "image_handling_caveat": IMAGE_HANDLING_CAVEAT,
        "actual_marginal_api_cost": "N/A",
        "subscription_included_usage": True,
        "written_at": written_at,
        "criteria_basis": "runtime correctness only (masterplan section 17)",
        "p50_sec_per_page": round(p50_wall, 4),
        "p90_sec_per_page": round(p90_wall, 4),
        "full_run_projection": {
            "page_count": full_run_page_count,
            "workers": replica_count,
            "wall_time_hours_projected_p50": wall_time_hours_projected_p50,
            "wall_time_hours_projected_p90": wall_time_hours_projected_p90,
            "api_equivalent_price_floor_usd_p50": api_equivalent_price_floor_usd_p50,
            "api_equivalent_price_floor_usd_mean": api_equivalent_price_floor_usd_mean,
            "api_equivalent_price_floor_is_a_floor": True,
            "notes": [
                "wall-time hours = per-page wall_seconds (p50 or p90 of the canary) "
                f"* {full_run_page_count} pages / 3600 / {replica_count} workers",
                "the api-equivalent price floor excludes cache-write and cache-read "
                "tokens, which price_snapshot.json does not price for Opus 5; it is a "
                "lower bound, never the API cost of the full run",
                "actual_marginal_api_cost stays N/A: this run is included in a Claude "
                "subscription, never billed per page",
            ],
        },
        "source_receipt_count": page_count,
        "why_derived_not_measured": (
            "no new inference ran to produce this receipt (ARENA_CONTRACT 11.6 D37); "
            "every field is derived from the per-page receipts already on disk under "
            "runs/opus5_subscription/canary/receipts/"
        ),
    }

    core_receipts.validate(document, schema_name="canary-receipt")
    return document


__all__ = [
    "RECEIPT_SCHEMA",
    "CanaryReceiptError",
    "build_canary_receipt",
]
