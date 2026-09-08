"""WP-R1 — permitted-plan Oracle ceiling on stored Arena outputs (Phase A).

Sections 35-37, 89-90. Computes, per benchmark and per page class:

  * every permitted SINGLE model plan
  * ALWAYS_ALL_RECONCILED  (FROZEN_RECONCILER_V1, GT-blind, frozen first)
  * PAGE_CLASS_CHAMPION    (best fixed single per page class, in-sample)
  * ORACLE_PERMITTED       (per unit, best of the permitted plans by hidden GT)

The Oracle picks ONE permitted plan for the whole unit. It never splices a
model's table onto another model's text -- that is the section 35 Frankenstein
rule. An element-wise ceiling is computed too, but it is labelled
ORACLE_ELEMENTWISE_FORBIDDEN and exists only to show how much of a naive
"oracle gain" is splicing that no production plan could deliver.

Both section 37 cohorts are reported: the intersection cohort, and
missing-as-failure over the union.

Diagnostic only. Not a public benchmark result, not a champion promotion.
"""

from __future__ import annotations

import csv
import json
import random
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bind import FOUNDER_EXCLUDED, arena_root, load_json, sha256_file, write_text_lf
from loss_vector import WEIGHTS
from reconciler import RECONCILER_ID, UNRESOLVED, cached_selection

HERE = Path(__file__).parent

FULL_COMPARE = "reports/full_compare_20260905"
OMNIDOC_GT = Path(
    r"D:\CodexProjects\ai-knowledge-compiler\benchmark\datasets\acquired"
    r"\public-core\omnidocbench\OmniDocBench.json"
)

# A unit is a hard fail when its loss exceeds this. Same tau the arena's own
# complementarity matrices use, so the two are comparable.
HARD_FAIL_TAU = 0.05

BOOTSTRAP_REPLICATES = 2000
BOOTSTRAP_SEED = "TAVONEL-ROUTER-ORACLE-CLUSTER-BOOTSTRAP-2026-09-08"

ELEMENT_TO_CLASS = {"text": "L1", "reading_order": "L3", "table": "L4", "formula": "L5"}

_PAGE_SUFFIX = re.compile(r"[_-](?:page|pg|p)[_-]?\d+$", re.IGNORECASE)


@dataclass
class Surface:
    """One scoreable surface: a benchmark (and facet) with per-unit losses."""

    key: str
    benchmark: str
    unit_label: str
    models: list[str]
    loss: dict[str, dict[str, float]]
    page_class: dict[str, str] = field(default_factory=dict)
    cluster: dict[str, str] = field(default_factory=dict)
    elements: dict[str, dict[str, dict[str, float]]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def all_units(self) -> list[str]:
        units: set[str] = set()
        for per_unit in self.loss.values():
            units |= per_unit.keys()
        return sorted(units)

    def intersection_units(self) -> list[str]:
        if not self.loss:
            return []
        sets = [set(per_unit) for per_unit in self.loss.values()]
        return sorted(set.intersection(*sets))


# --------------------------------------------------------------------------
# loaders
# --------------------------------------------------------------------------


def document_family(unit: str) -> str:
    stem = unit.rsplit("/", 1)[-1]
    for suffix in (".png", ".pdf", ".jpg"):
        stem = stem.removesuffix(suffix)
    trimmed = _PAGE_SUFFIX.sub("", stem)
    return trimmed or stem


def load_omnidoc(root: Path, bind: dict[str, Any]) -> Surface:
    per_model_elements: dict[str, dict[str, dict[str, float]]] = {}
    for model, entry in bind["models"].items():
        block = entry["benchmarks"]["omnidoc"]
        if not block["available"]:
            continue
        elements: dict[str, dict[str, float]] = {}
        for element, ref in block["artifacts"].items():
            if element == "table_teds":
                continue
            raw = load_json(root / ref["relative_path"])
            elements[element] = {k: min(max(float(v), 0.0), 1.0) for k, v in raw.items()}
        per_model_elements[model] = elements

    loss: dict[str, dict[str, float]] = {}
    for model, elements in per_model_elements.items():
        composite: dict[str, float] = {}
        units: set[str] = set()
        for per_unit in elements.values():
            units |= per_unit.keys()
        for unit in units:
            num = 0.0
            den = 0.0
            for element, per_unit in elements.items():
                if unit not in per_unit:
                    continue
                weight = WEIGHTS[ELEMENT_TO_CLASS[element]]
                num += weight * per_unit[unit]
                den += weight
            if den > 0:
                composite[unit] = num / den
        loss[model] = composite

    page_class: dict[str, str] = {}
    notes: list[str] = []
    if OMNIDOC_GT.is_file():
        for page in load_json(OMNIDOC_GT):
            info = page.get("page_info") or {}
            attr = info.get("page_attribute") or {}
            image = info.get("image_path")
            if image:
                page_class[str(image)] = "|".join(
                    [
                        str(attr.get("data_source", "?")),
                        str(attr.get("language", "?")),
                        str(attr.get("layout", "?")),
                    ]
                )
        notes.append(f"page classes from OmniDocBench GT page_attribute ({OMNIDOC_GT})")
    else:
        notes.append("OmniDocBench GT absent: page-class tables unavailable")

    surface = Surface(
        key="omnidoc",
        benchmark="omnidoc",
        unit_label="page",
        models=sorted(loss),
        loss=loss,
        page_class=page_class,
        cluster={},
        elements=per_model_elements,
        notes=notes,
    )
    for unit in surface.all_units():
        surface.cluster[unit] = document_family(unit)
        surface.page_class.setdefault(unit, "unlabelled")
    return surface


def load_olmocr(root: Path, bind: dict[str, Any]) -> Surface:
    loss: dict[str, dict[str, float]] = {}
    per_class: dict[str, dict[str, dict[str, float]]] = {}
    page_class: dict[str, str] = {}
    test_counts: dict[str, int] = {}
    for model, entry in bind["models"].items():
        block = entry["benchmarks"]["olmocr"]
        if not block["available"]:
            continue
        payload = load_json(root / block["artifacts"]["official_result"]["relative_path"])
        totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        by_type: dict[str, dict[str, list[int]]] = defaultdict(
            lambda: defaultdict(lambda: [0, 0])
        )
        for test in payload["tests"]:
            unit = str(test["pdf"])
            failed = 0 if test["passed"] else 1
            totals[unit][0] += failed
            totals[unit][1] += 1
            by_type[str(test["type"])][unit][0] += failed
            by_type[str(test["type"])][unit][1] += 1
            source = str(test["source_jsonl"])
            if source != "baseline":
                page_class[unit] = source
            test_counts[unit] = totals[unit][1]
        loss[model] = {u: f / n for u, (f, n) in totals.items() if n}
        for test_type, rows in by_type.items():
            per_class.setdefault(test_type, {})[model] = {
                u: f / n for u, (f, n) in rows.items() if n
            }

    surface = Surface(
        key="olmocr",
        benchmark="olmocr",
        unit_label="pdf page",
        models=sorted(loss),
        loss=loss,
        page_class=page_class,
        cluster={},
        elements={},
        notes=[
            "unit is the PDF page, loss = share of that page's olmOCR-Bench tests "
            "that failed. Choosing a different model per test on the same page "
            "would be region splicing (section 35), so the plan chooses per page.",
            f"tests per page range {min(test_counts.values())}-{max(test_counts.values())}",
        ],
    )
    surface.elements = {f"type:{k}": v for k, v in per_class.items()}
    for unit in surface.all_units():
        surface.cluster[unit] = document_family(unit)
        surface.page_class.setdefault(unit, "unlabelled")
    return surface


def _csv_scores(path: Path, column: str) -> dict[str, float]:
    out: dict[str, float] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            raw = row.get(column)
            if raw in (None, ""):
                continue
            out[str(row["test_id"])] = min(max(1.0 - float(str(raw)), 0.0), 1.0)
    return out


def load_parsebench(root: Path, bind: dict[str, Any], facet: str) -> Surface:
    column = "teds" if facet == "table" else "rule_pass_rate"
    loss: dict[str, dict[str, float]] = {}
    tags: dict[str, str] = {}
    for model, entry in bind["models"].items():
        block = entry["benchmarks"]["parsebench"]
        ref = block["artifacts"].get(facet) if block["available"] else None
        if ref is None:
            continue
        path = root / ref["relative_path"]
        loss[model] = _csv_scores(path, column)
        with path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                tags.setdefault(str(row["test_id"]), str(row.get("tags") or "untagged"))

    surface = Surface(
        key=f"parsebench:{facet}",
        benchmark="parsebench",
        unit_label="example",
        models=sorted(loss),
        loss=loss,
        page_class=tags,
        cluster={},
        elements={},
        notes=[f"per-example loss = 1 - {column}"],
    )
    for unit in surface.all_units():
        facet_dir = unit.rsplit("/", 1)[0] if "/" in unit else "root"
        surface.cluster[unit] = f"{facet_dir}/{document_family(unit)}"
        surface.page_class.setdefault(unit, "untagged")
    return surface


# --------------------------------------------------------------------------
# plans
# --------------------------------------------------------------------------


def build_plans(
    surface: Surface, units: list[str], selection: dict[str, str], missing_as_failure: bool
) -> dict[str, dict[str, float]]:
    """Per-unit loss for every permitted plan on this cohort."""

    def model_loss(model: str, unit: str) -> float | None:
        value = surface.loss.get(model, {}).get(unit)
        if value is None:
            return 1.0 if missing_as_failure else None
        return value

    plans: dict[str, dict[str, float]] = {}
    for model in surface.models:
        per_unit: dict[str, float] = {}
        for unit in units:
            value = model_loss(model, unit)
            if value is not None:
                per_unit[unit] = value
        plans[f"SINGLE:{model}"] = per_unit

    # ALWAYS_ALL + frozen reconciler: run every model, keep the one the frozen
    # GT-blind rule elects. UNRESOLVED is a full loss -- no silent fallback.
    # If the elected model produced output but this benchmark never scored it,
    # the unit is UNRESOLVED N/A: it is counted and reported, never quietly
    # dropped and never scored as if it had succeeded.
    reconciled: dict[str, float] = {}
    unscoreable = 0
    for unit in units:
        chosen = selection.get(unit, UNRESOLVED)
        if chosen == UNRESOLVED:
            reconciled[unit] = 1.0
            continue
        if chosen not in surface.models:
            unscoreable += 1
            if missing_as_failure:
                reconciled[unit] = 1.0
            continue
        value = model_loss(chosen, unit)
        reconciled[unit] = 1.0 if value is None else value
    plans["ALWAYS_ALL_RECONCILED"] = reconciled
    plans["__unscoreable__"] = {"ALWAYS_ALL_RECONCILED": float(unscoreable)}

    # Fixed page-class champion: one model per class, chosen on this very
    # cohort. In-sample and therefore optimistic -- it is a ceiling on fixed
    # routing, not an achievable policy.
    by_class: dict[str, list[str]] = defaultdict(list)
    for unit in units:
        by_class[surface.page_class.get(unit, "unlabelled")].append(unit)
    champion: dict[str, float] = {}
    champion_choice: dict[str, str] = {}
    for klass, class_units in by_class.items():
        best_model, best_mean = None, float("inf")
        for model in surface.models:
            values = [model_loss(model, u) for u in class_units]
            present = [v for v in values if v is not None]
            if not present:
                continue
            mean = sum(present) / len(present)
            if mean < best_mean:
                best_model, best_mean = model, mean
        if best_model is None:
            continue
        champion_choice[klass] = best_model
        for unit in class_units:
            value = model_loss(best_model, unit)
            if value is not None:
                champion[unit] = value
    plans["PAGE_CLASS_CHAMPION"] = champion
    plans["__champion_choice__"] = champion_choice  # type: ignore[assignment]

    # Permitted-plan Oracle: per unit, the best of the plans above. One plan
    # for the whole unit. No cross-model splicing.
    candidate_plans = [p for p in plans if p.startswith("SINGLE:")] + [
        "ALWAYS_ALL_RECONCILED"
    ]
    oracle: dict[str, float] = {}
    for unit in units:
        options = [plans[p][unit] for p in candidate_plans if unit in plans[p]]
        if options:
            oracle[unit] = min(options)
    plans["ORACLE_PERMITTED"] = oracle

    return plans


def elementwise_forbidden(
    surface: Surface, units: list[str], missing_as_failure: bool
) -> dict[str, float]:
    """Section 35 Frankenstein ceiling. NOT a permitted plan. Contrast only."""
    if not surface.elements or surface.benchmark != "omnidoc":
        return {}
    out: dict[str, float] = {}
    for unit in units:
        num = 0.0
        den = 0.0
        for element, cls in ELEMENT_TO_CLASS.items():
            weight = WEIGHTS[cls]
            values = [
                elements[element][unit]
                for elements in surface.elements.values()
                if element in elements and unit in elements[element]
            ]
            if not values:
                continue
            num += weight * min(values)
            den += weight
        if den > 0:
            out[unit] = num / den
        elif missing_as_failure:
            out[unit] = 1.0
    return out


# --------------------------------------------------------------------------
# statistics
# --------------------------------------------------------------------------


def summarize(per_unit: dict[str, float]) -> dict[str, Any]:
    if not per_unit:
        return {"n": 0, "mean_loss": None, "irr_proxy": None, "hard_fail": 0}
    values = list(per_unit.values())
    mean = sum(values) / len(values)
    return {
        "n": len(values),
        "mean_loss": mean,
        "irr_proxy": 1.0 - mean,
        "hard_fail": sum(1 for v in values if v > HARD_FAIL_TAU),
        "hard_fail_rate": sum(1 for v in values if v > HARD_FAIL_TAU) / len(values),
        "total_loss_units": sum(1 for v in values if v >= 1.0),
    }


def cluster_bootstrap(
    surface: Surface,
    plans: dict[str, dict[str, float]],
    units: list[str],
    replicates: int = BOOTSTRAP_REPLICATES,
) -> dict[str, Any]:
    """Cluster (document-family) bootstrap CIs for every plan and for headroom.

    The best fixed single is re-selected inside each replicate, so the headroom
    CI carries the selection uncertainty instead of pretending the winner was
    known in advance.
    """
    clusters: dict[str, list[str]] = defaultdict(list)
    for unit in units:
        clusters[surface.cluster.get(unit, unit)].append(unit)
    keys = sorted(clusters)
    if len(keys) < 2:
        return {"replicates": 0, "reason": "fewer than two clusters"}

    plan_names = [p for p in plans if not p.startswith("__")]
    sums: dict[str, list[float]] = {}
    counts: dict[str, list[int]] = {}
    for plan in plan_names:
        per_unit = plans[plan]
        sums[plan] = [sum(per_unit.get(u, 0.0) for u in clusters[k]) for k in keys]
        counts[plan] = [sum(1 for u in clusters[k] if u in per_unit) for k in keys]

    singles = [p for p in plan_names if p.startswith("SINGLE:")]
    draws: dict[str, list[float]] = {plan: [] for plan in plan_names}
    headroom: list[float] = []
    capture_denominator_zero = 0
    rng = random.Random(BOOTSTRAP_SEED)  # noqa: S311 - resampling, not crypto
    size = len(keys)
    index_range = range(size)
    for _ in range(replicates):
        idx = rng.choices(index_range, k=size)
        means: dict[str, float] = {}
        for plan in plan_names:
            total = sum(map(sums[plan].__getitem__, idx))
            n = sum(map(counts[plan].__getitem__, idx))
            if n:
                means[plan] = total / n
                draws[plan].append(total / n)
        if "ORACLE_PERMITTED" in means and singles:
            best_fixed = min(means[p] for p in singles if p in means)
            gap = best_fixed - means["ORACLE_PERMITTED"]
            headroom.append(gap)
            if gap <= 0:
                capture_denominator_zero += 1

    def ci(values: list[float]) -> dict[str, float | None]:
        if len(values) < 20:
            return {"lo": None, "hi": None}
        ordered = sorted(values)
        lo = ordered[int(0.025 * len(ordered))]
        hi = ordered[min(int(0.975 * len(ordered)), len(ordered) - 1)]
        return {"lo": lo, "hi": hi}

    return {
        "replicates": replicates,
        "seed": BOOTSTRAP_SEED,
        "cluster_unit": "document family",
        "n_clusters": size,
        "plan_mean_loss_ci95": {plan: ci(values) for plan, values in draws.items()},
        "headroom_best_fixed_minus_oracle_ci95": ci(headroom),
        "headroom_point": (sum(headroom) / len(headroom)) if headroom else None,
        "replicates_with_zero_headroom": capture_denominator_zero,
    }


def rescue_table(
    surface: Surface, units: list[str], replicates: int = 500
) -> list[dict[str, Any]]:
    """Appendix B: P(peer ok | primary wrong), joint fail, with cluster CIs."""
    clusters: dict[str, list[str]] = defaultdict(list)
    for unit in units:
        clusters[surface.cluster.get(unit, unit)].append(unit)
    keys = sorted(clusters)
    rng = random.Random(BOOTSTRAP_SEED + ":rescue")  # noqa: S311
    rows: list[dict[str, Any]] = []
    wrong: dict[str, dict[str, bool]] = {
        m: {u: surface.loss[m][u] > HARD_FAIL_TAU for u in units if u in surface.loss[m]}
        for m in surface.models
    }
    for primary in surface.models:
        for peer in surface.models:
            if peer == primary:
                continue
            per_cluster = []
            for key in keys:
                n_wrong = 0
                n_rescued = 0
                n_joint = 0
                for unit in clusters[key]:
                    if not wrong[primary].get(unit, False):
                        continue
                    if unit not in wrong[peer]:
                        continue
                    n_wrong += 1
                    if wrong[peer][unit]:
                        n_joint += 1
                    else:
                        n_rescued += 1
                per_cluster.append((n_rescued, n_joint, n_wrong))
            total_wrong = sum(c[2] for c in per_cluster)
            if total_wrong == 0:
                continue
            total_rescued = sum(c[0] for c in per_cluster)
            draws = []
            size = len(keys)
            for _ in range(replicates):
                idx = rng.choices(range(size), k=size)
                r = sum(per_cluster[i][0] for i in idx)
                w = sum(per_cluster[i][2] for i in idx)
                if w:
                    draws.append(r / w)
            draws.sort()
            lo = draws[int(0.025 * len(draws))] if len(draws) >= 20 else None
            hi = draws[min(int(0.975 * len(draws)), len(draws) - 1)] if len(draws) >= 20 else None
            rows.append(
                {
                    "primary": primary,
                    "peer": peer,
                    "n_primary_wrong": total_wrong,
                    "rescue_rate": total_rescued / total_wrong,
                    "rescue_ci95_lo": lo,
                    "rescue_ci95_hi": hi,
                    "joint_fail_rate": sum(c[1] for c in per_cluster) / total_wrong,
                }
            )
    rows.sort(key=lambda r: (r["primary"], -r["rescue_rate"]))
    return rows


# --------------------------------------------------------------------------
# driver
# --------------------------------------------------------------------------


def evaluate_surface(
    surface: Surface, selection: dict[str, str], cohort: str, scope: list[str]
) -> dict[str, Any]:
    missing_as_failure = cohort == "missing_as_failure"
    units = surface.all_units() if missing_as_failure else surface.intersection_units()
    plans = build_plans(surface, units, selection, missing_as_failure)
    champion_choice = plans.pop("__champion_choice__")
    unscoreable = plans.pop("__unscoreable__")
    forbidden = elementwise_forbidden(surface, units, missing_as_failure)
    if forbidden:
        plans["ORACLE_ELEMENTWISE_FORBIDDEN"] = forbidden

    summaries = {plan: summarize(per_unit) for plan, per_unit in plans.items()}
    for plan, count in unscoreable.items():
        summaries[plan]["unresolved_na"] = int(count)
    singles = {p: s for p, s in summaries.items() if p.startswith("SINGLE:") and s["n"]}
    best_fixed = min(singles, key=lambda p: singles[p]["mean_loss"]) if singles else None

    by_class: dict[str, dict[str, Any]] = {}
    class_units: dict[str, list[str]] = defaultdict(list)
    for unit in units:
        class_units[surface.page_class.get(unit, "unlabelled")].append(unit)
    for klass, members in sorted(class_units.items()):
        member_set = set(members)
        by_class[klass] = {
            "n_units": len(members),
            "champion_model": champion_choice.get(klass),
            "plans": {
                plan: summarize({u: v for u, v in per_unit.items() if u in member_set})
                for plan, per_unit in plans.items()
            },
        }

    boot = cluster_bootstrap(surface, plans, units)

    oracle_mean = summaries.get("ORACLE_PERMITTED", {}).get("mean_loss")
    best_mean = summaries[best_fixed]["mean_loss"] if best_fixed else None
    headroom = (best_mean - oracle_mean) if (best_mean is not None and oracle_mean) else None

    def capture(plan: str) -> float | None:
        mean = summaries.get(plan, {}).get("mean_loss")
        if mean is None or best_mean is None or not headroom:
            return None
        return float((best_mean - mean) / headroom)

    return {
        "cohort": cohort,
        "n_units": len(units),
        "n_units_intersection": len(surface.intersection_units()),
        "n_units_union": len(surface.all_units()),
        "models": surface.models,
        "exclusions": {
            model: sorted(set(units) - set(surface.loss.get(model, {})))[:5]
            for model in surface.models
            if len(set(units) - set(surface.loss.get(model, {}))) > 0
        },
        "exclusion_counts": {
            model: len(set(units) - set(surface.loss.get(model, {})))
            for model in surface.models
        },
        "models_excluded_from_surface": {
            model: "no per-unit score artifact for this benchmark"
            for model in scope
            if model not in surface.models
        },
        "plans": summaries,
        "best_fixed_single": best_fixed,
        "oracle_headroom_vs_best_fixed": headroom,
        "oracle_headroom_relative": (headroom / best_mean) if headroom and best_mean else None,
        "capture_ratio_section_90": {
            "formula": "(best_fixed_loss - plan_loss) / (best_fixed_loss - oracle_loss)",
            "ALWAYS_ALL_RECONCILED": capture("ALWAYS_ALL_RECONCILED"),
            "PAGE_CLASS_CHAMPION": capture("PAGE_CLASS_CHAMPION"),
            "TAVONEL_ROUTER": None,
            "TAVONEL_ROUTER_note": "Phase B. No replayed router exists in this lane.",
        },
        "by_page_class": by_class,
        "bootstrap": boot,
        "champion_choice": champion_choice,
    }


def fmt(value: Any, digits: int = 4) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def render_tables(results: dict[str, Any]) -> str:
    lines: list[str] = [
        "# Oracle ceiling tables — Phase A (stored outputs, GPU spend $0)",
        "",
        "Loss is lower-better. `IRR proxy = 1 - mean loss` over L1/L3/L4/L5 only "
        "(see LOSS_VECTOR_FREEZE.json). NOT a public benchmark result.",
        "",
    ]
    for key, surface_result in results["surfaces"].items():
        lines.append(f"## Surface `{key}`")
        lines.append("")
        for note in surface_result["notes"]:
            lines.append(f"- {note}")
        lines.append("")
        for cohort in ("intersection", "missing_as_failure"):
            block = surface_result["cohorts"][cohort]
            lines.append(f"### Cohort `{cohort}` (N = {block['n_units']} units)")
            lines.append("")
            lines.append(
                "| plan | n | mean loss | IRR proxy | hard fail (>0.05) | "
                "unresolved N/A | 95% CI |"
            )
            lines.append("| --- | ---: | ---: | ---: | ---: | ---: | --- |")
            ci_all = block["bootstrap"].get("plan_mean_loss_ci95", {})
            order = sorted(
                block["plans"],
                key=lambda p: (
                    block["plans"][p]["mean_loss"]
                    if block["plans"][p]["mean_loss"] is not None
                    else 9.0
                ),
            )
            for plan in order:
                summary = block["plans"][plan]
                ci = ci_all.get(plan, {})
                ci_text = (
                    f"[{fmt(ci.get('lo'))}, {fmt(ci.get('hi'))}]"
                    if ci.get("lo") is not None
                    else "n/a"
                )
                lines.append(
                    f"| `{plan}` | {summary['n']} | {fmt(summary['mean_loss'])} | "
                    f"{fmt(summary['irr_proxy'])} | {summary.get('hard_fail', 0)} | "
                    f"{summary.get('unresolved_na', 0)} | {ci_text} |"
                )
            lines.append("")
            head = block["bootstrap"].get("headroom_best_fixed_minus_oracle_ci95", {})
            lines.append(
                f"Best fixed single: `{block['best_fixed_single']}`. "
                f"Oracle headroom = {fmt(block['oracle_headroom_vs_best_fixed'])} "
                f"absolute loss ({fmt((block['oracle_headroom_relative'] or 0) * 100, 1)}% "
                f"relative), cluster-bootstrap 95% CI "
                f"[{fmt(head.get('lo'))}, {fmt(head.get('hi'))}] over "
                f"{block['bootstrap'].get('n_clusters')} document-family clusters."
            )
            lines.append("")
            capture = block["capture_ratio_section_90"]
            lines.append(
                f"Section 90 capture ratio — ALWAYS_ALL_RECONCILED "
                f"{fmt(capture['ALWAYS_ALL_RECONCILED'], 3)}, PAGE_CLASS_CHAMPION "
                f"{fmt(capture['PAGE_CLASS_CHAMPION'], 3)}, TAVONEL router n/a (Phase B)."
            )
            lines.append("")
        block = surface_result["cohorts"]["intersection"]
        classes = block["by_page_class"]
        if len(classes) > 1:
            lines.append("### Per page class (intersection cohort)")
            lines.append("")
            lines.append(
                "| page class | n | champion | champion loss | best single loss | "
                "oracle loss | headroom |"
            )
            lines.append("| --- | ---: | --- | ---: | ---: | ---: | ---: |")
            for klass, row in sorted(classes.items(), key=lambda kv: -kv[1]["n_units"])[:20]:
                plans = row["plans"]
                singles = {
                    p: s["mean_loss"]
                    for p, s in plans.items()
                    if p.startswith("SINGLE:") and s["mean_loss"] is not None
                }
                best = min(singles.values()) if singles else None
                oracle = plans.get("ORACLE_PERMITTED", {}).get("mean_loss")
                champ = plans.get("PAGE_CLASS_CHAMPION", {}).get("mean_loss")
                gap = (best - oracle) if (best is not None and oracle is not None) else None
                lines.append(
                    f"| `{klass}` | {row['n_units']} | `{row['champion_model']}` | "
                    f"{fmt(champ)} | {fmt(best)} | {fmt(oracle)} | {fmt(gap)} |"
                )
            lines.append("")
    lines.append("## Appendix B — complementarity (OmniDoc composite, tau = 0.05)")
    lines.append("")
    lines.append(
        "| primary | peer | n primary wrong | rescue P(peer ok \\| primary wrong) | "
        "95% CI | joint fail |"
    )
    lines.append("| --- | --- | ---: | ---: | --- | ---: |")
    for row in results["complementarity"]:
        lines.append(
            f"| `{row['primary']}` | `{row['peer']}` | {row['n_primary_wrong']} | "
            f"{fmt(row['rescue_rate'])} | [{fmt(row['rescue_ci95_lo'])}, "
            f"{fmt(row['rescue_ci95_hi'])}] | {fmt(row['joint_fail_rate'])} |"
        )
    lines.append("")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    root = arena_root()
    bind_path = HERE / "ARENA_BIND.json"
    if not bind_path.is_file():
        print("REFUSED: ARENA_BIND.json missing — run bind.py first", file=sys.stderr)
        return 2
    bind = load_json(bind_path)

    scope = [
        model
        for model, entry in bind["models"].items()
        if not entry["founder_excluded"] and entry["frozen_outputs"]["available"]
    ]

    surfaces: list[Surface] = [load_omnidoc(root, bind), load_olmocr(root, bind)]
    for facet in ("table", "chart", "text_content", "text_formatting"):
        surfaces.append(load_parsebench(root, bind, facet))

    cache_dir = HERE / ".cache"
    results: dict[str, Any] = {
        "schema": "tavonel.router_oracle.oracle_ceiling.v1",
        "phase": "A",
        "diagnostic_only": True,
        "not_a_public_benchmark_result": True,
        "not_a_champion_promotion": True,
        "arena_bind_sha256": sha256_file(bind_path),
        "loss_vector_freeze_sha256": sha256_file(HERE / "LOSS_VECTOR_FREEZE.json"),
        "reconciler_id": RECONCILER_ID,
        "reconciler_source_sha256": sha256_file(HERE / "reconciler.py"),
        "founder_excluded_models": list(FOUNDER_EXCLUDED),
        "model_scope": sorted(scope),
        "hard_fail_tau": HARD_FAIL_TAU,
        "surfaces": {},
    }

    for surface in surfaces:
        if not surface.models:
            continue
        selection_payload = cached_selection(root, surface.benchmark, scope, cache_dir)
        selection = selection_payload["selection"]
        results["surfaces"][surface.key] = {
            "benchmark": surface.benchmark,
            "unit_label": surface.unit_label,
            "notes": [
                *surface.notes,
                f"reconciler candidates resolved for "
                f"{len(selection_payload['candidate_counts'])} units; "
                f"{selection_payload['unresolved']} UNRESOLVED",
            ],
            "cohorts": {
                cohort: evaluate_surface(surface, selection, cohort, scope)
                for cohort in ("intersection", "missing_as_failure")
            },
        }

    omnidoc = surfaces[0]
    results["complementarity"] = rescue_table(omnidoc, omnidoc.intersection_units())

    out_json = HERE / "ORACLE_RESULTS.json"
    json_digest = write_text_lf(
        out_json,
        json.dumps(results, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
    )
    tables_path = HERE / "ORACLE_TABLES.md"
    tables_digest = write_text_lf(tables_path, render_tables(results))
    print(f"wrote {out_json} {json_digest}")
    print(f"wrote {tables_path} {tables_digest}")
    for key, block in results["surfaces"].items():
        inter = block["cohorts"]["intersection"]
        print(
            f"  {key}: N={inter['n_units']} best_fixed={inter['best_fixed_single']} "
            f"headroom={fmt(inter['oracle_headroom_vs_best_fixed'])}"
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
