"""WP-R10 Phase B — the offline router replay driver.

Runs every section 39 baseline that needs no planner over the stored Arena
output matrix, on the same six surfaces Phase A scored, and reports per arm:
information loss, IRR proxy, SCLR, route regret, escalation quality, unresolved
fraction, strong-model invocation, cost, GPU seconds, measured p50/p95/p99, and
cluster-bootstrap CIs including the section 17 Oracle capture ratio.

The two halves are kept apart on purpose: this driver imports ``features`` for
the runtime-visible half and ``scorer`` for the hidden half, and ``features``
imports ``scorer`` nowhere. Every `RouterReplayRecord` this emits carries
``hidden_evaluation_visible_to_runtime = False``.

Diagnostic research code, on spent development evidence.
NOT a public benchmark result. NOT a champion promotion.
"""

from __future__ import annotations

import argparse
import random
import statistics
import sys
import time
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
_ORACLE = HERE.parent / "router_oracle_20260908"
for _path in (HERE, _ORACLE):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import features as F  # noqa: E402
import scorer as S  # noqa: E402
from bind import load_json, sha256_file  # type: ignore[import-untyped]  # noqa: E402
from oracle import document_family  # type: ignore[import-untyped]  # noqa: E402

REPLAY_ID = "TAVONEL-ROUTER-REPLAY-2026-09-08-V1"
BOOTSTRAP_REPLICATES = 2000
BOOTSTRAP_SEED = "TAVONEL-ROUTER-REPLAY-CLUSTER-BOOTSTRAP-2026-09-08"

SURFACE_BENCHMARK = {
    "omnidoc": "omnidoc",
    "olmocr": "olmocr",
    "parsebench:table": "parsebench",
    "parsebench:chart": "parsebench",
    "parsebench:text_content": "parsebench",
    "parsebench:text_formatting": "parsebench",
}

FAILURE_APPENDIX_N = 20


# ---------------------------------------------------------------------------
# arms
# ---------------------------------------------------------------------------


def build_arms(models: Sequence[str]) -> list[Any]:
    """Every section 39 baseline that needs no planner. Frozen before scoring."""
    arms: list[Any] = [
        F.FixedModel(model=F.PRIMARY_MODEL, name="PRIMARY_ONLY"),
        *[F.FixedModel(model=model) for model in models],
        F.AlwaysAllReconciled(models=tuple(models)),
    ]
    for strong in F.STRONG_MODELS:
        arms.append(F.FixedModel(model=strong, name=f"ALWAYS_STRONG@{strong}"))
        arms.append(F.Escalating(trigger="prediction", strong=strong))
        arms.append(F.Escalating(trigger="disagreement", strong=strong))
        arms.append(F.Escalating(trigger="critical_token", strong=strong))
        arms.append(F.ReplayComposite(strong=strong, name=f"REPLAY_COMPOSITE_V1@{strong}"))
    # The production router, replayed. The reading-order sweep is the honest
    # treatment of a signal this corpus cannot measure; the sentinel variant
    # reproduces the C-09 production defect at corpus scale.
    for mode in ("balanced", "speed"):
        for assumption in (1.0, 0.0):
            arms.append(F.CoreRouter(mode=mode, reading_order_assumption=assumption))
        arms.append(
            F.CoreRouter(mode=mode, reading_order_assumption=1.0, worker_sentinels=True)
        )
    adapter = F.planner_adapter()
    if adapter is not None:
        arms.append(adapter)
    return arms


def ablation_arms(strong: str) -> list[Any]:
    """Section 18 ablations of REPLAY_COMPOSITE_V1, one leg at a time."""
    legs = {
        "no_disagreement": {"use_disagreement": False},
        "no_critical_loss_detector": {"use_critical_token": False},
        "no_reconciler": {"use_reconciler": False},
        "no_cost_objective": {"use_cost_objective": False},
        "no_prediction": {"use_prediction": False},
    }
    return [
        F.ReplayComposite(strong=strong, name=f"ABLATION:{label}@{strong}", **kwargs)
        for label, kwargs in legs.items()
    ]


NOT_MEASURABLE_ABLATIONS = {
    "no_preflight": (
        "the corpus has no arrival-time preflight lane; every signal here is post-render"
    ),
    "no_authority": (
        "no authority source (SEC/XBRL/OpenDART) exists in the repository or the corpus"
    ),
    "no_region_recovery": "the Arena stores whole-page outputs only; no region crops were ever run",
    "no_independent_verifier": "no verifier gate exists to switch off (WP-R9 is NOT_STARTED)",
    "no_speculation": "speculative execution produces no separate stored artifact to withhold",
    "no_queue_state": "queue depth at decision time is not recorded per unit",
    "no_cold_start": "cold start is a per-pod property in the ledger, not a per-unit one",
    "no_temporal_or_identity": "single-version corpus; no second version of any document exists",
    "no_template_memory": "no per-cluster outcome memory exists to ablate",
    "full_replay_vs_incremental": "needs a multi-version corpus",
}


# ---------------------------------------------------------------------------
# per-arm evaluation on one surface
# ---------------------------------------------------------------------------


def evaluate_arm(
    arm: Any,
    surface: Any,
    units: Sequence[F.UnitFeatures],
    gt: dict[str, str],
    opportunities: dict[str, dict[str, int]],
    canonical_text: dict[tuple[str, str], str],
    oracle_loss: dict[str, float],
    primary_wrong: dict[str, bool],
    cost: dict[str, Any],
    critical_memo: dict[tuple[str, str], tuple[int, float, tuple[str, ...]]],
) -> dict[str, Any]:
    per_unit_loss: dict[str, float] = {}
    regret: list[float] = []
    latency_ms: list[float] = []
    unresolved = 0
    escalated = 0
    strong_invoked = 0
    escalated_and_needed = 0
    needed = 0
    sclr_units = 0
    critical_events = 0
    critical_opportunities = 0
    route_cost = 0.0
    route_gpu_seconds = 0.0
    missing_latency = 0
    reasons: dict[str, int] = defaultdict(int)

    per_model_cost = cost["per_model"]
    for unit in units:
        key = unit.unit_key
        plan = arm.plan(unit)
        loss = 1.0 if plan.accepted is None else S.unit_loss(surface, plan.accepted, key)
        per_unit_loss[key] = loss
        regret.append(loss - oracle_loss.get(key, 1.0))
        critical_opportunities += sum((opportunities.get(key) or {}).values())
        events = 0
        if plan.accepted is not None:
            memo_key = (plan.accepted, key)
            if memo_key not in critical_memo:
                gt_text = gt.get(key)
                output_text = canonical_text.get(memo_key)
                critical_memo[memo_key] = (
                    S.hidden_critical_loss(gt_text, output_text)
                    if (gt_text and output_text is not None)
                    else (0, 0.0, ())
                )
            events = critical_memo[memo_key][0]
        critical_events += events
        if plan.accepted is not None and events > 0:
            sclr_units += 1
        if plan.accepted is None:
            unresolved += 1
            if plan.unresolved_reason:
                reasons[plan.unresolved_reason] += 1
        if plan.escalate:
            escalated += 1
        if any(model in F.STRONG_MODELS for model in plan.routes):
            strong_invoked += 1
        want = primary_wrong.get(key, False)
        needed += int(want)
        escalated_and_needed += int(want and plan.escalate)

        unit_latency = 0.0
        have_latency = bool(plan.routes)
        for model in plan.routes:
            row = per_model_cost.get(model)
            if row is not None:
                route_cost += float(row.get("cost_per_1000_pages_usd") or 0.0) / 1000.0
                billed = float(row.get("billed_seconds") or 0.0)
                pages = float(row.get("pages_basis") or 0.0)
                route_gpu_seconds += (billed / pages) if pages else 0.0
            out = unit.outputs.get(model)
            if out is None or out.inference_ms is None:
                have_latency = False
            else:
                unit_latency += out.inference_ms
        if have_latency:
            latency_ms.append(unit_latency)
        else:
            missing_latency += 1

    n = len(units)
    losses = list(per_unit_loss.values())
    mean_loss = sum(losses) / n if n else None
    return {
        "arm": arm.name,
        "n_units": n,
        "mean_loss": mean_loss,
        "irr_proxy": (1.0 - mean_loss) if mean_loss is not None else None,
        "hard_fail": sum(1 for v in losses if v > S.HARD_FAIL_TAU),
        "hard_fail_rate": (
            sum(1 for v in losses if v > S.HARD_FAIL_TAU) / n if n else None
        ),
        "route_regret_mean": (sum(regret) / n) if n else None,
        "unresolved_fraction": unresolved / n if n else None,
        "unresolved_reasons": dict(sorted(reasons.items(), key=lambda kv: -kv[1])),
        "escalation_fraction": escalated / n if n else None,
        "strong_invocation_fraction": strong_invoked / n if n else None,
        "escalation_recall": (escalated_and_needed / needed) if needed else None,
        "escalation_precision": (escalated_and_needed / escalated) if escalated else None,
        "false_escalation_rate": ((escalated - escalated_and_needed) / n) if n else None,
        "missed_escalation_rate": ((needed - escalated_and_needed) / n) if n else None,
        "escalation_denominator_needed": needed,
        "sclr_unit_rate": sclr_units / n if n else None,
        "sclr_silent_units": sclr_units,
        "sclr_opportunity_rate": (
            critical_events / critical_opportunities if critical_opportunities else None
        ),
        "sclr_critical_events": critical_events,
        "sclr_critical_opportunities": critical_opportunities,
        "cost_usd_per_1000_units": (route_cost / n * 1000.0) if n else None,
        "gpu_seconds_per_unit": (route_gpu_seconds / n) if n else None,
        "latency_ms": _percentiles(latency_ms, missing_latency, n),
        "_per_unit_loss": per_unit_loss,
    }


def to_replay_record(arm_name: str, unit: F.UnitFeatures, plan: F.UnitPlan) -> Any:
    """Emit the Appendix D contract record for one replayed decision.

    Built here, in the driver, from the runtime-visible plan only. The
    `hidden_evaluation_visible_to_runtime` literal is what makes this a valid
    replay record, and `RouterReplayRecord` refuses any other value.
    """
    from akc_router.execution_plan import RouterReplayRecord, VerificationPolicy
    from akc_router.models import Route

    disposition = "unresolved" if plan.accepted is None else "accepted"
    return RouterReplayRecord(
        unit_id=unit.unit_key,
        features_revision=F.FEATURE_BUILDER_ID,
        router_revision=f"{REPLAY_ID}:{arm_name}",
        allowed_routes=tuple(
            route
            for route, model in F.ROUTE_TO_ARENA_MODEL.items()
            if model is not None
            for route in (Route(route),)
        ),
        selected_plan=plan.accepted or "UNRESOLVED",
        speculative_plans=tuple(plan.speculative),
        escalations=("escalated",) if plan.escalate else (),
        verification=(
            VerificationPolicy.PEER_AGREEMENT if plan.escalate else VerificationPolicy.NONE
        ),
        final_disposition=disposition,
        hidden_evaluation_visible_to_runtime=False,
    )


def _percentiles(values: list[float], missing: int, n: int) -> dict[str, Any]:
    """Measured inference latency only. Queue and cold start are NOT included."""
    if not values:
        return {
            "p50": None,
            "p95": None,
            "p99": None,
            "basis": "UNKNOWN",
            "note": "no per-page receipt carried inference_ms for this arm's routes",
            "units_without_latency": missing,
        }
    ordered = sorted(values)

    def pct(fraction: float) -> float:
        index = min(int(fraction * len(ordered)), len(ordered) - 1)
        return ordered[index]

    return {
        "p50": pct(0.50),
        "p95": pct(0.95),
        "p99": pct(0.99),
        "mean": statistics.fmean(ordered),
        "basis": "sum of per-page receipt inference_ms over invoked routes",
        "excludes": ["queue_ms", "load_ms (cold start)", "preprocess/postprocess"],
        "units_measured": len(ordered),
        "units_without_latency": missing,
        "coverage": len(ordered) / n if n else None,
    }


# ---------------------------------------------------------------------------
# cluster bootstrap: plan means, headroom, and section 17 capture ratio
# ---------------------------------------------------------------------------


def capture_bootstrap(
    surface: Any,
    arm_losses: dict[str, dict[str, float]],
    single_arms: Sequence[str],
    oracle_name: str,
    units: Sequence[str],
    replicates: int = BOOTSTRAP_REPLICATES,
) -> dict[str, Any]:
    clusters: dict[str, list[str]] = defaultdict(list)
    for unit in units:
        clusters[surface.cluster.get(unit, document_family(unit))].append(unit)
    keys = sorted(clusters)
    if len(keys) < 2:
        return {"replicates": 0, "reason": "fewer than two clusters"}

    sums: dict[str, list[float]] = {}
    counts: dict[str, list[int]] = {}
    for arm, per_unit in arm_losses.items():
        sums[arm] = [sum(per_unit.get(u, 0.0) for u in clusters[k]) for k in keys]
        counts[arm] = [sum(1 for u in clusters[k] if u in per_unit) for k in keys]

    draws: dict[str, list[float]] = {arm: [] for arm in arm_losses}
    capture: dict[str, list[float]] = {arm: [] for arm in arm_losses}
    headroom: list[float] = []
    degenerate = 0
    rng = random.Random(BOOTSTRAP_SEED)  # noqa: S311 - resampling, not crypto
    size = len(keys)
    for _ in range(replicates):
        idx = rng.choices(range(size), k=size)
        means: dict[str, float] = {}
        for arm in arm_losses:
            total = sum(map(sums[arm].__getitem__, idx))
            count = sum(map(counts[arm].__getitem__, idx))
            if count:
                means[arm] = total / count
                draws[arm].append(total / count)
        singles = [means[a] for a in single_arms if a in means]
        if not singles or oracle_name not in means:
            continue
        best_fixed = min(singles)
        gap = best_fixed - means[oracle_name]
        headroom.append(gap)
        if gap <= 0:
            degenerate += 1
            continue
        for arm, mean in means.items():
            capture[arm].append((best_fixed - mean) / gap)

    def ci(values: list[float]) -> dict[str, float | None]:
        if len(values) < 20:
            return {"lo": None, "hi": None}
        ordered = sorted(values)
        return {
            "lo": ordered[int(0.025 * len(ordered))],
            "hi": ordered[min(int(0.975 * len(ordered)), len(ordered) - 1)],
        }

    return {
        "replicates": replicates,
        "seed": BOOTSTRAP_SEED,
        "cluster_unit": "document family",
        "n_clusters": size,
        "mean_loss_ci95": {arm: ci(values) for arm, values in draws.items()},
        "capture_ratio_ci95": {arm: ci(values) for arm, values in capture.items()},
        "capture_ratio_point": {
            arm: (sum(values) / len(values)) if values else None
            for arm, values in capture.items()
        },
        "headroom_ci95": ci(headroom),
        "headroom_point": (sum(headroom) / len(headroom)) if headroom else None,
        "replicates_with_zero_headroom": degenerate,
        "note": (
            "2,000 replicates in pure Python (numpy is absent from this venv), "
            "the same deviation from PAPER2 section 10's 10,000 that Phase A "
            "recorded. Adequate for a 95% interval, inadequate for a tail "
            "p-value -- and no p-value is reported."
        ),
    }


# ---------------------------------------------------------------------------
# disagreement conditionals (matrix E-5, blueprint section 92)
# ---------------------------------------------------------------------------


def disagreement_conditionals(
    surface: Any, units: Sequence[F.UnitFeatures], models: Sequence[str]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for i, left in enumerate(models):
        for right in models[i + 1 :]:
            agree_wrong = agree_n = dis_wrong = dis_n = both_wrong_agree = 0
            for unit in units:
                key = unit.unit_key
                if key not in surface.loss.get(left, {}) or key not in surface.loss.get(
                    right, {}
                ):
                    continue
                sim = unit.sim(left, right)
                if sim is None:
                    continue
                left_wrong = surface.loss[left][key] > S.HARD_FAIL_TAU
                right_wrong = surface.loss[right][key] > S.HARD_FAIL_TAU
                if sim >= F.AGREEMENT_TAU:
                    agree_n += 1
                    agree_wrong += int(left_wrong)
                    both_wrong_agree += int(left_wrong and right_wrong)
                else:
                    dis_n += 1
                    dis_wrong += int(left_wrong)
            total = agree_n + dis_n
            if not total:
                continue
            rows.append(
                {
                    "model_a": left,
                    "model_b": right,
                    "n_scored": total,
                    "agreement_rate": agree_n / total,
                    "p_error_given_agreement": (agree_wrong / agree_n) if agree_n else None,
                    "p_error_given_disagreement": (dis_wrong / dis_n) if dis_n else None,
                    "p_both_wrong_and_agree": both_wrong_agree / total,
                    "n_agree": agree_n,
                    "n_disagree": dis_n,
                }
            )
    rows.sort(key=lambda r: -r["p_both_wrong_and_agree"])
    return rows


# ---------------------------------------------------------------------------
# catastrophic failure appendix (matrix E-6, program section 55)
# ---------------------------------------------------------------------------


def failure_appendix(
    surface: Any,
    units: Sequence[F.UnitFeatures],
    gt: dict[str, str],
    canonical_text: dict[tuple[str, str], str],
    oracle_loss: dict[str, float],
    models: Sequence[str],
    limit: int = FAILURE_APPENDIX_N,
) -> list[dict[str, Any]]:
    by_key = {unit.unit_key: unit for unit in units}
    candidates = [
        key
        for key in surface.all_units()
        if oracle_loss.get(key, 1.0) > S.HARD_FAIL_TAU and key in by_key
    ]
    candidates.sort(
        key=lambda k: (-oracle_loss.get(k, 1.0), -S.unit_loss(surface, F.PRIMARY_MODEL, k))
    )
    rows: list[dict[str, Any]] = []
    for key in candidates[:limit]:
        unit = by_key[key]
        best_model = min(models, key=lambda m: S.unit_loss(surface, m, key))
        accepted = canonical_text.get((F.PRIMARY_MODEL, key))
        gt_text = gt.get(key, "")
        events, risk, kinds = (
            S.hidden_critical_loss(gt_text, accepted) if (gt_text and accepted) else (0, 0.0, ())
        )
        sim = unit.sim(F.PRIMARY_MODEL, F.PEER_MODEL)
        rows.append(
            {
                "unit": key,
                "page_class": surface.page_class.get(key, "unlabelled"),
                "oracle_best_permitted_loss": oracle_loss.get(key),
                "oracle_best_permitted_model": best_model,
                "primary_model": F.PRIMARY_MODEL,
                "primary_loss": S.unit_loss(surface, F.PRIMARY_MODEL, key),
                "reconciler_choice": unit.reconciler_choice,
                "detected_by_blind_predictor": unit.blind_risk.get(F.PRIMARY_MODEL),
                "detected_by_disagreement": (sim is None or sim < F.AGREEMENT_TAU),
                "primary_peer_similarity": sim,
                "detected_by_critical_token_verifier": (
                    unit.critical_token_risk >= F.CRITICAL_TOKEN_TAU
                ),
                "hidden_critical_loss_events": events,
                "hidden_critical_loss_kinds": list(kinds),
                "hidden_critical_loss_max_risk": risk,
                "gt_chars": len(gt_text),
                "primary_output_chars": len(accepted or ""),
                "not_derivable_from_stored_outputs": [
                    "peer result after escalation (no escalated run exists)",
                    "authority source disposition (no authority lane exists)",
                    "final customer disposition (the replay has no world state)",
                ],
            }
        )
    return rows


# ---------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=HERE)
    parser.add_argument("--surfaces", nargs="*", default=sorted(SURFACE_BENCHMARK))
    parser.add_argument("--replicates", type=int, default=BOOTSTRAP_REPLICATES)
    args = parser.parse_args(argv)

    started = time.time()
    root = F.arena_root()
    bind_path = _ORACLE / "ARENA_BIND.json"
    bind = load_json(bind_path)
    models = sorted(
        model
        for model, entry in bind["models"].items()
        if not entry["founder_excluded"] and entry["frozen_outputs"]["available"]
    )
    cache_dir = HERE / ".cache"

    # 1. The SCLR denominator is frozen BEFORE anything is scored.
    freeze_path = args.out / "SCLR_OPPORTUNITY_FREEZE.json"
    opportunity_freeze = S.build_opportunity_freeze(list(SURFACE_BENCHMARK))
    freeze_digest = S.write_json(freeze_path, opportunity_freeze)
    print(f"froze SCLR opportunities -> {freeze_path} {freeze_digest}")

    # 2. The policy parameters are frozen before anything is scored, too.
    policy_freeze = {
        "schema": "tavonel.router_replay.policy_freeze.v1",
        "replay_id": REPLAY_ID,
        "frozen_before_scoring": True,
        **F.frozen_policy_parameters(),
        "bootstrap": {"replicates": args.replicates, "seed": BOOTSTRAP_SEED},
        "hard_fail_tau": S.HARD_FAIL_TAU,
        "model_scope": models,
    }
    policy_path = args.out / "REPLAY_POLICY_FREEZE.json"
    policy_digest = S.write_json(policy_path, policy_freeze)
    print(f"froze policy parameters -> {policy_path} {policy_digest}")

    surfaces = S.load_surfaces(root, bind)
    unit_cache: dict[str, list[F.UnitFeatures]] = {}
    text_cache: dict[str, dict[tuple[str, str], str]] = {}
    results: dict[str, Any] = {
        "schema": "tavonel.router_replay.results.v1",
        "replay_id": REPLAY_ID,
        "phase": "B",
        "diagnostic_only": True,
        "not_a_public_benchmark_result": True,
        "not_a_champion_promotion": True,
        "hidden_evaluation_visible_to_runtime": False,
        "arena_bind_sha256": sha256_file(bind_path),
        "sclr_opportunity_freeze_sha256": freeze_digest,
        "replay_policy_freeze_sha256": policy_digest,
        "model_scope": models,
        "hard_fail_tau": S.HARD_FAIL_TAU,
        "not_measurable_ablations": NOT_MEASURABLE_ABLATIONS,
        "surfaces": {},
    }

    for key in args.surfaces:
        benchmark = SURFACE_BENCHMARK[key]
        surface = surfaces[key]
        if not surface.models:
            continue
        if benchmark not in unit_cache:
            print(f"building runtime-visible features for {benchmark} ...", flush=True)
            built, built_texts = F.load_or_build_units(root, benchmark, models, cache_dir)
            unit_cache[benchmark] = built
            text_cache[benchmark] = built_texts
        scored_units = set(surface.all_units())
        units = [u for u in unit_cache[benchmark] if u.unit_key in scored_units]
        print(f"{key}: {len(units)} units with a score, {len(surface.models)} models")

        gt = S.ground_truth(key)
        opportunities = opportunity_freeze["surfaces"][key]["per_unit"]
        texts = text_cache[benchmark]
        critical_memo: dict[tuple[str, str], tuple[int, float, tuple[str, ...]]] = {}
        oracle_loss = {
            unit.unit_key: S.oracle_unit_loss(
                surface, unit.unit_key, surface.models, unit.reconciler_choice
            )
            for unit in units
        }
        primary_wrong = {
            unit.unit_key: S.unit_loss(surface, F.PRIMARY_MODEL, unit.unit_key)
            > S.HARD_FAIL_TAU
            for unit in units
        }
        cost = F.load_cost(root)

        arms = build_arms(surface.models) + [
            arm for strong in F.STRONG_MODELS for arm in ablation_arms(strong)
        ]
        evaluated: dict[str, dict[str, Any]] = {}
        for arm in arms:
            evaluated[arm.name] = evaluate_arm(
                arm,
                surface,
                units,
                gt,
                opportunities,
                texts,
                oracle_loss,
                primary_wrong,
                cost,
                critical_memo,
            )

        # The Oracle arm is diagnostic: it is the per-unit permitted-plan
        # minimum, computed with hidden truth. It is never a policy.
        evaluated["ORACLE_DIAGNOSTIC"] = {
            "arm": "ORACLE_DIAGNOSTIC",
            "n_units": len(units),
            "mean_loss": (
                sum(oracle_loss[u.unit_key] for u in units) / len(units) if units else None
            ),
            "diagnostic_only": True,
            "note": "hidden ground truth chose this plan. Never a router result.",
            "_per_unit_loss": {u.unit_key: oracle_loss[u.unit_key] for u in units},
        }
        evaluated["ORACLE_DIAGNOSTIC"]["irr_proxy"] = (
            1.0 - evaluated["ORACLE_DIAGNOSTIC"]["mean_loss"]
            if evaluated["ORACLE_DIAGNOSTIC"]["mean_loss"] is not None
            else None
        )

        arm_losses = {name: row.pop("_per_unit_loss") for name, row in evaluated.items()}
        singles = [
            name
            for name in (f"SINGLE:{model}" for model in surface.models)
            if name in evaluated
        ]
        boot = capture_bootstrap(
            surface,
            arm_losses,
            singles,
            "ORACLE_DIAGNOSTIC",
            [u.unit_key for u in units],
            replicates=args.replicates,
        )
        best_fixed = min(
            (name for name in singles if evaluated[name]["mean_loss"] is not None),
            key=lambda name: evaluated[name]["mean_loss"],
            default=None,
        )
        results["surfaces"][key] = {
            "benchmark": benchmark,
            "unit_label": surface.unit_label,
            "n_units_scored": len(units),
            "n_units_union": len(surface.all_units()),
            "models": surface.models,
            "gt_completeness": S.GT_COMPLETENESS.get(key),
            "primary_model_scored_on_this_surface": F.PRIMARY_MODEL in surface.models,
            "escalation_need_definition": (
                f"the primary ({F.PRIMARY_MODEL}) output for that unit scores worse "
                f"than tau={S.HARD_FAIL_TAU}; if the primary is not scored on this "
                "surface every unit reads as needing escalation and the escalation "
                "columns are meaningless"
            ),
            "best_fixed_single": best_fixed,
            "arms": evaluated,
            "bootstrap": boot,
            "disagreement_conditionals": disagreement_conditionals(
                surface, units, surface.models
            ),
            "failure_appendix": failure_appendix(
                surface, units, gt, texts, oracle_loss, surface.models
            ),
            "notes": list(surface.notes),
        }
        if benchmark not in {
            SURFACE_BENCHMARK[k] for k in args.surfaces[args.surfaces.index(key) + 1 :]
        }:
            text_cache.pop(benchmark, None)
            unit_cache.pop(benchmark, None)

    results["cost_and_latency_caveats"] = [
        "Cost is raw GPU provider cost from the campaign ledger, under an "
        "exploratory scheduling pattern with a 0.66 idle overhead ratio. It is "
        "never a per-page price and never sits beside a retail price.",
        "opus5_subscription has no pod ledger: its cost is UNMEASURED, not zero, "
        "so every arm that invokes it reports an INCOMPLETE cost.",
        "Latency is measured inference_ms from the per-page receipts. Queue time "
        "and cold start are excluded and are NOT modelled.",
        "An arm's latency is the SUM over the routes it invoked, i.e. sequential "
        "execution. Parallel speculation would be lower; nothing here measures it.",
    ]
    results["arena_report_anomalies"] = [
        "glm_ocr's OmniDoc board row (text Edit 0.0444) disagrees with its own "
        "per-page rows (0.0846); ANOMALY_NOTES.md explains it as a SUCCESS-only "
        "rescore over a 1,599-page filtered GT. This replay uses the full-corpus "
        "per-page rows, the conservative choice, exactly as Phase A did.",
        "reports/full_compare_20260905/STATUS.md contains unrendered PowerShell "
        "template literals instead of substituted values and must not be quoted.",
    ]
    results["runtime_seconds"] = round(time.time() - started, 1)

    out_json = args.out / "REPLAY_RESULTS.json"
    digest = S.write_json(out_json, results)
    print(f"wrote {out_json} {digest}")
    tables = args.out / "REPLAY_TABLES.md"
    tables_digest = _write_text(tables, render_tables(results))
    print(f"wrote {tables} {tables_digest}")

    manifest = build_manifest(
        results, args.out, bind_path, freeze_digest, policy_digest, digest, tables_digest
    )
    manifest_path = args.out / "MANIFEST.json"
    print(f"wrote {manifest_path} {S.write_json(manifest_path, manifest)}")
    return 0


def _write_text(path: Path, text: str) -> str:
    import hashlib

    data = text.encode("utf-8")
    path.write_bytes(data)
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def build_manifest(
    results: dict[str, Any],
    out: Path,
    bind_path: Path,
    freeze_digest: str,
    policy_digest: str,
    results_digest: str,
    tables_digest: str,
) -> dict[str, Any]:
    root = F.arena_root()
    inputs = {
        "arena_root": str(root),
        "source_manifest": sha256_file(root / "source_manifest.jsonl"),
        "arena_bind": sha256_file(bind_path),
        "loss_vector_freeze": sha256_file(_ORACLE / "LOSS_VECTOR_FREEZE.json"),
        "oracle_results": sha256_file(_ORACLE / "ORACLE_RESULTS.json"),
        "reconciler_source": sha256_file(_ORACLE / "reconciler.py"),
        "frozen_manifests": {
            model: sha256_file(root / "frozen_outputs" / model / "manifest.jsonl")
            for model in results["model_scope"]
            if (root / "frozen_outputs" / model / "manifest.jsonl").is_file()
        },
    }
    return {
        "schema": "tavonel.router_replay.manifest.v1",
        "replay_id": REPLAY_ID,
        "generated_by": "research/router_replay_20260908/replay.py",
        "code_sha256": {
            name: sha256_file(HERE / name)
            for name in ("features.py", "scorer.py", "replay.py")
        },
        "commands": [
            "uv sync",
            "ARENA_ROOT=<arena> .venv/Scripts/python.exe research/router_replay_20260908/replay.py",
            "pytest research/router_replay_20260908/tests -q",
        ],
        "inputs": inputs,
        "outputs": {
            "SCLR_OPPORTUNITY_FREEZE.json": freeze_digest,
            "REPLAY_POLICY_FREEZE.json": policy_digest,
            "REPLAY_RESULTS.json": results_digest,
            "REPLAY_TABLES.md": tables_digest,
        },
        "runtime_seconds": results.get("runtime_seconds"),
        "gpu_spend_usd": 0,
        "paid_actions": "none - stored outputs only, CPU only, no network",
        "claim_status": (
            "diagnostic research on spent development evidence; "
            "NOT a public benchmark result"
        ),
    }


# ---------------------------------------------------------------------------
# tables
# ---------------------------------------------------------------------------


def fmt(value: Any, digits: int = 4) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def render_tables(results: dict[str, Any]) -> str:
    lines = [
        "# Router replay tables — Phase B (stored outputs, GPU spend $0)",
        "",
        "Loss is lower-better. `IRR proxy = 1 - mean loss` over L1/L3/L4/L5 only",
        "(`LOSS_VECTOR_FREEZE.json`). **NOT a public benchmark result. NOT a champion",
        "promotion.** Missing and failed outputs are full losses and stay in every",
        "denominator. `ORACLE_DIAGNOSTIC` sees hidden truth and is never a router result.",
        "",
    ]
    for key, block in results["surfaces"].items():
        lines += [
            f"## Surface `{key}` — {block['n_units_scored']} units, "
            f"{len(block['models'])} models",
            "",
            f"Ground truth for SCLR: {block['gt_completeness']}",
            "",
            "| arm | n | mean loss | 95% CI | IRR proxy | hard fail | regret | "
            "unresolved | escalation | strong | SCLR/unit | SCLR/opp | $/1k | "
            "GPU s/unit | p50 ms | p95 ms | p99 ms |",
            "| --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | "
            "---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        ci_all = block["bootstrap"].get("mean_loss_ci95", {})
        order = sorted(
            block["arms"],
            key=lambda a: (
                block["arms"][a]["mean_loss"]
                if block["arms"][a].get("mean_loss") is not None
                else 9.0
            ),
        )
        for name in order:
            row = block["arms"][name]
            ci = ci_all.get(name, {})
            ci_text = (
                f"[{fmt(ci.get('lo'))}, {fmt(ci.get('hi'))}]"
                if ci.get("lo") is not None
                else "n/a"
            )
            lat = row.get("latency_ms") or {}
            lines.append(
                f"| `{name}` | {row.get('n_units')} | {fmt(row.get('mean_loss'))} | "
                f"{ci_text} | {fmt(row.get('irr_proxy'))} | {row.get('hard_fail', 'n/a')} | "
                f"{fmt(row.get('route_regret_mean'))} | "
                f"{fmt(row.get('unresolved_fraction'), 3)} | "
                f"{fmt(row.get('escalation_fraction'), 3)} | "
                f"{fmt(row.get('strong_invocation_fraction'), 3)} | "
                f"{fmt(row.get('sclr_unit_rate'), 4)} | "
                f"{fmt(row.get('sclr_opportunity_rate'), 4)} | "
                f"{fmt(row.get('cost_usd_per_1000_units'), 2)} | "
                f"{fmt(row.get('gpu_seconds_per_unit'), 2)} | "
                f"{fmt(lat.get('p50'), 0)} | {fmt(lat.get('p95'), 0)} | "
                f"{fmt(lat.get('p99'), 0)} |"
            )
        lines.append("")
        boot = block["bootstrap"]
        lines += [
            f"Best fixed single: `{block['best_fixed_single']}`. Oracle headroom "
            f"{fmt(boot.get('headroom_point'))} "
            f"[{fmt((boot.get('headroom_ci95') or {}).get('lo'))}, "
            f"{fmt((boot.get('headroom_ci95') or {}).get('hi'))}] over "
            f"{boot.get('n_clusters')} document-family clusters.",
            "",
            "### Section 17 Oracle capture ratio "
            "`(best_fixed - arm) / (best_fixed - oracle)`",
            "",
            "| arm | capture | 95% CI |",
            "| --- | ---: | --- |",
        ]
        points = boot.get("capture_ratio_point") or {}
        cis = boot.get("capture_ratio_ci95") or {}
        for name in sorted(points, key=lambda a: -(points[a] if points[a] is not None else -9)):
            ci = cis.get(name, {})
            lines.append(
                f"| `{name}` | {fmt(points[name], 3)} | "
                f"[{fmt(ci.get('lo'), 3)}, {fmt(ci.get('hi'), 3)}] |"
            )
        lines += ["", "### Disagreement conditionals (section 92), worst pairs", ""]
        lines += [
            "| a | b | n | agree rate | P(a wrong \\| agree) | P(a wrong \\| disagree) | "
            "P(both wrong AND agree) |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
        ]
        for row in block["disagreement_conditionals"][:12]:
            lines.append(
                f"| `{row['model_a']}` | `{row['model_b']}` | {row['n_scored']} | "
                f"{fmt(row['agreement_rate'], 3)} | "
                f"{fmt(row['p_error_given_agreement'], 3)} | "
                f"{fmt(row['p_error_given_disagreement'], 3)} | "
                f"{fmt(row['p_both_wrong_and_agree'], 3)} |"
            )
        lines += ["", "### Catastrophic failure appendix (top units the Oracle also fails)", ""]
        lines += [
            "| unit | page class | oracle loss | best model | primary loss | "
            "blind risk | disagreed? | L2 flagged? | critical events |",
            "| --- | --- | ---: | --- | ---: | ---: | :-: | :-: | ---: |",
        ]
        for row in block["failure_appendix"][:10]:
            lines.append(
                f"| `{row['unit']}` | {row['page_class']} | "
                f"{fmt(row['oracle_best_permitted_loss'])} | "
                f"`{row['oracle_best_permitted_model']}` | {fmt(row['primary_loss'])} | "
                f"{fmt(row['detected_by_blind_predictor'], 3)} | "
                f"{'yes' if row['detected_by_disagreement'] else 'no'} | "
                f"{'yes' if row['detected_by_critical_token_verifier'] else 'no'} | "
                f"{row['hidden_critical_loss_events']} |"
            )
        lines.append("")
    lines += ["## Ablations that are NOT measurable from stored outputs", ""]
    lines += ["| ablation | reason |", "| --- | --- |"]
    for name, reason in sorted(results["not_measurable_ablations"].items()):
        lines.append(f"| `{name}` | {reason} |")
    lines += ["", "## Cost and latency caveats", ""]
    lines += [f"- {note}" for note in results["cost_and_latency_caveats"]]
    lines += ["", "## Arena report anomalies that travel with every number above", ""]
    lines += [f"- {note}" for note in results["arena_report_anomalies"]]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
