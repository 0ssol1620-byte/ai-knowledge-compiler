"""Counterfactual cost of a TAVONEL variant (masterplan section 23.1).

The rule that matters: **never the sum of all models.** A variant that routed
4% of its pages to a specialist costs the primary run plus those 4%, not the
whole arena. This module therefore prices exactly the ``(model, page)`` pairs
the frozen replay manifest says were served, and reports the all-models figure
separately, labelled as a contrast only.

Three cost components, kept apart (masterplan section 12.5):

* **inference** — GPU seconds on the page times the pod's listed rate;
* **overhead** — the non-inference billed seconds of that model's pods,
  amortised over the pages it produced, so startup and idle are not free;
* **escalation** — the Opus lane has no GPU cost; its receipts carry an
  api-equivalent list price, which is what is reported. Never ``$0/page``.

Recovery jobs that have not run yet cost ``null`` with a reason. A page whose
pod rate or timing is missing is counted as unpriced, never as zero.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from arena.constants import CAMPAIGN_ID
from arena.tavonel import guards, jsonio, variants
from arena.tavonel.errors import MissingInputError
from arena.tavonel.paths import ArenaPaths

COST_SCHEMA = "tavonel.arena.counterfactual-cost.v1"

COST_MODEL = {
    "calibrated": False,
    "inference": "receipt total_ms / 1000 * pod listed_rate_usd_per_hour / 3600",
    "overhead_allocation": (
        "per model: (billed_seconds - useful_inference_seconds) * rate / 3600, summed over "
        "that model's pods and divided by the pages it produced"
    ),
    "rule": "primary + actually routed specialists + recovery overhead + escalation estimate",
    "subscription": "api_equivalent_list_price_usd from the page receipt; never zero",
}


@dataclass(frozen=True, slots=True)
class PodRates:
    rate_by_pod: Mapping[str, float]
    overhead_usd_by_model: Mapping[str, float]


@dataclass(frozen=True, slots=True)
class VariantCostReport:
    path: Path
    variant: str
    total_usd: float | None
    priced_pages: int
    unpriced_pages: int
    all_models_contrast_usd: float | None


def load_pod_rates(paths: ArenaPaths) -> PodRates:
    """Rates per pod and non-inference cost per model from the pod ledger."""
    rates: dict[str, float] = {}
    overhead: dict[str, float] = {}
    ledger = paths.cost_ledger
    if not ledger.is_file():
        return PodRates(rate_by_pod={}, overhead_usd_by_model={})
    for row in guards.iter_jsonl_guarded(ledger, what="pod cost ledger"):
        pod_id = row.get("pod_id")
        rate = row.get("listed_rate_usd_per_hour")
        if not isinstance(pod_id, str) or not isinstance(rate, int | float):
            continue
        rates[pod_id] = float(rate)
        model_key = row.get("model_key")
        billed = row.get("billed_seconds")
        useful = row.get("useful_inference_seconds")
        if (
            isinstance(model_key, str)
            and isinstance(billed, int | float)
            and isinstance(useful, int | float)
        ):
            non_useful = max(0.0, float(billed) - float(useful))
            overhead[model_key] = overhead.get(model_key, 0.0) + non_useful * float(rate) / 3600.0
    return PodRates(rate_by_pod=rates, overhead_usd_by_model=overhead)


def _pages_produced(paths: ArenaPaths, model_key: str) -> int:
    receipts = paths.receipts_dir(model_key)
    guards.assert_readable(receipts)
    if not receipts.is_dir():
        return 0
    return sum(1 for path in receipts.glob("*.json") if path.is_file())


@dataclass(frozen=True, slots=True)
class PageCost:
    usd: float | None
    gpu_seconds: float | None
    basis: str
    reason: str | None


def page_cost(
    paths: ArenaPaths, model_key: str, case_key: str, rates: PodRates
) -> PageCost:
    """Price one served page from its receipt and its pod's listed rate."""
    receipt_path = paths.receipt_path(model_key, case_key)
    if not receipt_path.is_file():
        return PageCost(None, None, "unpriced", "no page receipt on disk")
    receipt = guards.read_json_guarded(receipt_path, what="page receipt")

    if receipt.get("runtime_mode") == "subscription":
        estimate = receipt.get("api_equivalent_list_price_usd")
        if isinstance(estimate, int | float) and not isinstance(estimate, bool):
            return PageCost(float(estimate), None, "api_equivalent_list_price", None)
        return PageCost(
            None,
            None,
            "unpriced",
            "subscription page with no api_equivalent_list_price_usd in its receipt",
        )

    total_ms = receipt.get("total_ms")
    if not isinstance(total_ms, int | float) or isinstance(total_ms, bool):
        return PageCost(None, None, "unpriced", "receipt carries no total_ms")
    gpu_seconds = float(total_ms) / 1000.0
    pod_id = receipt.get("pod_id")
    rate = rates.rate_by_pod.get(pod_id) if isinstance(pod_id, str) else None
    if rate is None:
        return PageCost(
            None,
            gpu_seconds,
            "unpriced",
            "no pod ledger row with listed_rate_usd_per_hour for this page's pod",
        )
    return PageCost(round(gpu_seconds * rate / 3600.0, 8), gpu_seconds, "gpu_seconds_rate", None)


def _served_pages(paths: ArenaPaths, variant: str) -> list[tuple[str, str]]:
    """``(model_key, case_key)`` pairs the replay manifest says were served."""
    manifest = paths.replay_manifest(variant)
    if not manifest.is_file():
        raise MissingInputError(
            f"{manifest} is absent; run `python -m arena.tavonel replay --variant {variant}` "
            "before pricing the variant"
        )
    served: list[tuple[str, str]] = []
    for row in guards.iter_jsonl_guarded(manifest, what="replay manifest"):
        if row.get("unresolved"):
            continue
        model_key = row.get("chosen_model_key")
        case_key = row.get("case_key")
        if isinstance(model_key, str) and isinstance(case_key, str):
            served.append((model_key, case_key))
    return served


def _recovery_summary(paths: ArenaPaths, variant: str) -> dict[str, Any]:
    plan = paths.variant_recovery_plan(variant)
    if not plan.is_file():
        return {
            "planned_jobs": 0,
            "type_counts": {},
            "usd": None,
            "reason": "no recovery plan for this variant",
        }
    counts: dict[str, int] = {}
    total = 0
    for row in guards.iter_jsonl_guarded(plan, what="recovery plan"):
        recovery_type = row.get("recovery_type")
        if isinstance(recovery_type, str):
            counts[recovery_type] = counts.get(recovery_type, 0) + 1
            total += 1
    return {
        "planned_jobs": total,
        "type_counts": dict(sorted(counts.items())),
        "usd": None,
        "reason": (
            "recovery jobs are planned but not executed; their GPU cost does not exist yet "
            "and is not estimated here"
        ),
    }


def _all_models_contrast(
    paths: ArenaPaths, rates: PodRates, model_keys: Sequence[str]
) -> tuple[float | None, dict[str, Any]]:
    """What running every model over every page it produced actually cost."""
    total = 0.0
    priced_any = False
    detail: dict[str, Any] = {}
    for model_key in sorted(model_keys):
        pages = _pages_produced(paths, model_key)
        overhead = rates.overhead_usd_by_model.get(model_key)
        subtotal = 0.0
        priced = 0
        receipts = paths.receipts_dir(model_key)
        if receipts.is_dir():
            for path in sorted(receipts.glob("*.json")):
                cost = page_cost(paths, model_key, path.stem, rates)
                if cost.usd is not None:
                    subtotal += cost.usd
                    priced += 1
        if overhead is not None:
            subtotal += overhead
        if priced or overhead is not None:
            priced_any = True
            total += subtotal
        detail[model_key] = {
            "pages_produced": pages,
            "priced_pages": priced,
            "subtotal_usd": round(subtotal, 6) if (priced or overhead is not None) else None,
        }
    return (round(total, 6) if priced_any else None), detail


def variant_cost(paths: ArenaPaths, *, variant: str) -> VariantCostReport:
    """Price one variant from its frozen replay manifest."""
    canonical_variant = variants.normalize_variant(variant)
    rates = load_pod_rates(paths)
    served = _served_pages(paths, canonical_variant)

    per_model: dict[str, dict[str, Any]] = {}
    priced_pages = 0
    unpriced_pages = 0
    unpriced_reasons: dict[str, int] = {}
    total = 0.0
    any_price = False

    for model_key, case_key in served:
        entry = per_model.setdefault(
            model_key,
            {
                "pages_served": 0,
                "priced_pages": 0,
                "unpriced_pages": 0,
                "gpu_seconds": 0.0,
                "inference_usd": 0.0,
                "overhead_usd": None,
                "subtotal_usd": None,
                "basis": set(),
            },
        )
        entry["pages_served"] += 1
        cost = page_cost(paths, model_key, case_key, rates)
        entry["basis"].add(cost.basis)
        if cost.gpu_seconds is not None:
            entry["gpu_seconds"] += cost.gpu_seconds
        if cost.usd is None:
            entry["unpriced_pages"] += 1
            unpriced_pages += 1
            reason = cost.reason or "unpriced"
            unpriced_reasons[reason] = unpriced_reasons.get(reason, 0) + 1
            continue
        entry["priced_pages"] += 1
        entry["inference_usd"] += cost.usd
        priced_pages += 1

    for model_key, entry in per_model.items():
        overhead_total = rates.overhead_usd_by_model.get(model_key)
        produced = _pages_produced(paths, model_key)
        share: float | None = None
        if overhead_total is not None and produced > 0:
            share = round(overhead_total / produced * int(entry["pages_served"]), 8)
        entry["overhead_usd"] = share
        entry["inference_usd"] = round(float(entry["inference_usd"]), 8)
        entry["gpu_seconds"] = round(float(entry["gpu_seconds"]), 6)
        entry["basis"] = sorted(entry["basis"])
        if entry["priced_pages"] or share is not None:
            subtotal = float(entry["inference_usd"]) + (share or 0.0)
            entry["subtotal_usd"] = round(subtotal, 8)
            total += subtotal
            any_price = True
        else:
            entry["subtotal_usd"] = None
        if share is None:
            entry["overhead_unavailable_reason"] = (
                "no pod ledger rows for this model, so its startup and idle time cannot be "
                "attributed"
            )

    recovery = _recovery_summary(paths, canonical_variant)
    contrast, contrast_detail = _all_models_contrast(
        paths, rates, sorted({model for model, _ in served} | set(_models_with_receipts(paths)))
    )

    total_usd = round(total, 6) if any_price else None
    pages = len(served)
    payload: dict[str, Any] = {
        "schema": COST_SCHEMA,
        "campaign_id": CAMPAIGN_ID,
        "variant": canonical_variant,
        "variant_directory": variants.variant_dir_name(canonical_variant),
        "cost_model": COST_MODEL,
        "never_sum_all_models": True,
        "per_model": {key: per_model[key] for key in sorted(per_model)},
        "recovery": recovery,
        "totals": {
            "pages_served": pages,
            "priced_pages": priced_pages,
            "unpriced_pages": unpriced_pages,
            "unpriced_reasons": dict(sorted(unpriced_reasons.items())),
            "total_usd": total_usd,
            "usd_per_1000_pages": (
                None
                if total_usd is None or priced_pages == 0
                else round(total_usd / priced_pages * 1000.0, 6)
            ),
        },
        "all_models_full_run_usd_for_contrast_only": contrast,
        "all_models_contrast_detail": contrast_detail,
    }
    if variants.is_oracle(canonical_variant):
        payload["deployability"] = variants.ORACLE_LABEL
        payload["oracle_note"] = (
            "the oracle needs every candidate's output, so its true cost is the all-models "
            "figure, not the served-pages figure"
        )
    jsonio.write_json_atomic(paths.variant_cost_path(canonical_variant), payload)

    return VariantCostReport(
        path=paths.variant_cost_path(canonical_variant),
        variant=canonical_variant,
        total_usd=total_usd,
        priced_pages=priced_pages,
        unpriced_pages=unpriced_pages,
        all_models_contrast_usd=contrast,
    )


def _models_with_receipts(paths: ArenaPaths) -> list[str]:
    if not paths.runs.is_dir():
        return []
    return sorted(entry.name for entry in paths.runs.iterdir() if (entry / "receipts").is_dir())


__all__ = [
    "COST_MODEL",
    "COST_SCHEMA",
    "PageCost",
    "PodRates",
    "VariantCostReport",
    "load_pod_rates",
    "page_cost",
    "variant_cost",
]
