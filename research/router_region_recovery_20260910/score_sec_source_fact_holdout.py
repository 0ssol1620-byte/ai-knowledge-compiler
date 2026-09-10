#!/usr/bin/env python3
"""Score the frozen SEC source-fact holdout after output-only routing is sealed."""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

from route_sec_source_fact_outputs import (
    ADJUDICATOR_MODEL,
    BENCHMARK_ID,
    EXPECTED_REGIONS,
    PRIMARY_MODELS,
    _normal_number,
    canonical_sha256,
    load_model_outputs,
    read_json,
    read_jsonl,
    sha256_file,
)

BOOTSTRAP_REPLICATES = 5_000
BOOTSTRAP_SEED = 20_260_910
EXPECTED_ISSUERS = 6
EXPECTED_FACTS_PER_ISSUER = 4


class HoldoutScoringError(RuntimeError):
    pass


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    payload = "".join(
        json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
        for row in rows
    )
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(payload, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def nearest_rank(values: list[float], percentile: float) -> float:
    if not values:
        raise HoldoutScoringError("cannot calculate a percentile over an empty sequence")
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(percentile * len(ordered)) - 1))
    return ordered[index]


def expected_tokens(fact: dict[str, Any]) -> tuple[str, str]:
    visible = _normal_number(str(fact["normalized_visible_value"]))
    sign = fact.get("sign")
    if sign not in (None, "", "+", "-"):
        raise HoldoutScoringError(f"unsupported ix sign for {fact['region_id']}: {sign!r}")
    signed = visible
    if sign == "-" and visible != "0":
        signed = "-" + visible.lstrip("+-")
    magnitude = signed.lstrip("+-")
    return magnitude, signed


def validate_facts(facts: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    if len(facts) != EXPECTED_REGIONS:
        raise HoldoutScoringError(
            f"sealed fact denominator is {len(facts)}, expected {EXPECTED_REGIONS}"
        )
    by_region: dict[str, dict[str, Any]] = {}
    issuer_counts: Counter[str] = Counter()
    for fact in facts:
        region_id = str(fact["region_id"])
        if region_id in by_region:
            raise HoldoutScoringError(f"duplicate sealed fact: {region_id}")
        ticker = str(fact["ticker"])
        issuer_counts[ticker] += 1
        expected_tokens(fact)
        by_region[region_id] = fact
    if len(issuer_counts) != EXPECTED_ISSUERS or set(issuer_counts.values()) != {
        EXPECTED_FACTS_PER_ISSUER
    }:
        raise HoldoutScoringError(f"issuer cluster drift: {dict(issuer_counts)}")
    return by_region


def validate_routes(
    routing_path: Path,
    decision_path: Path,
    expected_regions: set[str],
) -> dict[str, dict[str, Any]]:
    decision = read_json(decision_path)
    routes = read_jsonl(routing_path)
    if decision.get("benchmark_id") != BENCHMARK_ID:
        raise HoldoutScoringError("final decision benchmark mismatch")
    if decision.get("routing_manifest_sha256") != sha256_file(routing_path):
        raise HoldoutScoringError("final routing manifest hash drift")
    if decision.get("decision_manifest_sha256") != canonical_sha256(routes):
        raise HoldoutScoringError("final routing decision hash drift")
    by_region = {str(row["region_id"]): row for row in routes}
    if len(by_region) != EXPECTED_REGIONS or set(by_region) != expected_regions:
        raise HoldoutScoringError("final routing denominator differs from sealed facts")
    return by_region


def receipt_accepts(output: dict[str, Any]) -> bool:
    receipt = output["receipt"]
    return receipt.get("status") == "SUCCESS" and receipt.get("semantic_error_class") is None


def token_retention(
    output: dict[str, Any], magnitude: str, signed: str
) -> tuple[bool, bool]:
    token_counts = Counter(output["tokens"])
    magnitude_retained = token_counts[magnitude] > 0 or token_counts["-" + magnitude] > 0
    return magnitude_retained, token_counts[signed] > 0


def model_outcome(
    output: dict[str, Any], magnitude: str, signed: str
) -> dict[str, Any]:
    magnitude_retained, signed_retained = token_retention(output, magnitude, signed)
    accepted = receipt_accepts(output)
    return {
        "accepted": accepted,
        "detected_failure": not accepted,
        "magnitude_retained": magnitude_retained,
        "signed_retained": signed_retained,
        "silent_critical_loss": accepted and not signed_retained,
        "semantic_error_class": output["receipt"].get("semantic_error_class"),
        "inference_ms": int(output["receipt"]["timings_ms"]["inference_ms"]),
        "processing_ms": int(output["receipt"]["timings_ms"]["total_ms"]),
    }


def summarize_outcomes(outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    denominator = len(outcomes)
    counts = {
        "accepted": sum(bool(row["accepted"]) for row in outcomes),
        "detected_failure": sum(bool(row["detected_failure"]) for row in outcomes),
        "magnitude_retained": sum(bool(row["magnitude_retained"]) for row in outcomes),
        "signed_retained": sum(bool(row["signed_retained"]) for row in outcomes),
        "silent_critical_loss": sum(bool(row["silent_critical_loss"]) for row in outcomes),
    }
    return {
        "denominator": denominator,
        **{f"{key}_count": value for key, value in counts.items()},
        **{f"{key}_rate": round(value / denominator, 6) for key, value in counts.items()},
    }


def cluster_bootstrap_difference(
    details: list[dict[str, Any]],
    left: Callable[[dict[str, Any]], float],
    right: Callable[[dict[str, Any]], float],
) -> dict[str, Any]:
    by_issuer: dict[str, list[dict[str, Any]]] = {}
    for row in details:
        by_issuer.setdefault(str(row["ticker"]), []).append(row)
    issuers = sorted(by_issuer)
    observed = sum(left(row) - right(row) for row in details) / len(details)
    rng = random.Random(BOOTSTRAP_SEED)  # noqa: S311 - reproducible statistical bootstrap
    samples: list[float] = []
    for _ in range(BOOTSTRAP_REPLICATES):
        selected = [issuers[rng.randrange(len(issuers))] for _ in issuers]
        rows = [row for issuer in selected for row in by_issuer[issuer]]
        samples.append(sum(left(row) - right(row) for row in rows) / len(rows))
    return {
        "difference": round(observed, 6),
        "ci95_cluster_bootstrap": [
            round(nearest_rank(samples, 0.025), 6),
            round(nearest_rank(samples, 0.975), 6),
        ],
        "clusters": len(issuers),
        "replicates": BOOTSTRAP_REPLICATES,
        "seed": BOOTSTRAP_SEED,
    }


def cost_and_latency(
    details: list[dict[str, Any]], model_freeze: dict[str, Any]
) -> dict[str, Any]:
    model_rates = {
        model: float(values["provider_hourly_rate_usd"])
        for model, values in model_freeze["models"].items()
    }
    model_cold_costs = {
        model: float(values["reconciled_estimated_gpu_cost_usd"])
        for model, values in model_freeze["models"].items()
    }
    result: dict[str, Any] = {"models": {}}
    for model in PRIMARY_MODELS:
        processing = [float(row["models"][model]["processing_ms"]) for row in details]
        inference = [float(row["models"][model]["inference_ms"]) for row in details]
        inference_cost = sum(inference) / 3_600_000 * model_rates[model]
        result["models"][model] = {
            "regions": len(processing),
            "cold_start_experiment_cost_usd": round(model_cold_costs[model], 6),
            "cold_start_cost_per_1000_regions_usd": round(
                model_cold_costs[model] / len(processing) * 1_000, 6
            ),
            "warm_inference_cost_per_1000_regions_usd": round(
                inference_cost / len(processing) * 1_000, 6
            ),
            "processing_p50_ms": nearest_rank(processing, 0.5),
            "processing_p95_nearest_rank_ms": nearest_rank(processing, 0.95),
        }

    router_processing: list[float] = []
    router_inference_cost = 0.0
    for row in details:
        primary_ms = max(
            float(row["models"][model]["processing_ms"]) for model in PRIMARY_MODELS
        )
        total_ms = primary_ms
        for model in PRIMARY_MODELS:
            router_inference_cost += (
                float(row["models"][model]["inference_ms"]) / 3_600_000 * model_rates[model]
            )
        ovis = row["models"].get(ADJUDICATOR_MODEL)
        if ovis is not None:
            total_ms += float(ovis["processing_ms"])
            router_inference_cost += (
                float(ovis["inference_ms"]) / 3_600_000 * model_rates[ADJUDICATOR_MODEL]
            )
        router_processing.append(total_ms)
    router_cold_cost = float(model_freeze["total_reconciled_estimated_gpu_cost_usd"])
    result["router"] = {
        "regions": len(router_processing),
        "model_region_calls": int(model_freeze["model_region_calls"]),
        "cold_start_experiment_cost_usd": round(router_cold_cost, 6),
        "cold_start_cost_per_1000_regions_usd": round(
            router_cold_cost / len(router_processing) * 1_000, 6
        ),
        "warm_inference_cost_per_1000_regions_usd": round(
            router_inference_cost / len(router_processing) * 1_000, 6
        ),
        "processing_p50_ms": nearest_rank(router_processing, 0.5),
        "processing_p95_nearest_rank_ms": nearest_rank(router_processing, 0.95),
        "latency_definition": (
            "parallel primary processing maximum plus sequential adjudicator processing "
            "when invoked; excludes pod cold start and transfer"
        ),
    }
    return result


def score(
    facts_path: Path,
    primary_root: Path,
    adjudicator_root: Path,
    routing_root: Path,
    model_freeze_path: Path,
    scoring_commit: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if re.fullmatch(r"[0-9a-f]{40}", scoring_commit) is None:
        raise HoldoutScoringError("scoring commit must be a full lowercase Git SHA-1")
    facts = read_jsonl(facts_path)
    fact_by_region = validate_facts(facts)
    models: dict[str, dict[str, dict[str, Any]]] = {
        PRIMARY_MODELS[0]: load_model_outputs(primary_root, PRIMARY_MODELS[0]),
        PRIMARY_MODELS[1]: load_model_outputs(primary_root, PRIMARY_MODELS[1]),
        ADJUDICATOR_MODEL: load_model_outputs(
            adjudicator_root, ADJUDICATOR_MODEL, expected_regions=17
        ),
    }
    route_by_region = validate_routes(
        routing_root / "FINAL_ROUTING.jsonl",
        routing_root / "FINAL_DECISION.json",
        set(fact_by_region),
    )
    details: list[dict[str, Any]] = []
    for region_id in sorted(fact_by_region):
        fact = fact_by_region[region_id]
        magnitude, signed = expected_tokens(fact)
        model_results: dict[str, dict[str, Any]] = {}
        for model in PRIMARY_MODELS:
            model_results[model] = model_outcome(models[model][region_id], magnitude, signed)
        if region_id in models[ADJUDICATOR_MODEL]:
            model_results[ADJUDICATOR_MODEL] = model_outcome(
                models[ADJUDICATOR_MODEL][region_id], magnitude, signed
            )
        route = route_by_region[region_id]
        selected_model = route.get("selected_model")
        selected = model_results.get(str(selected_model)) if selected_model else None
        if selected is None:
            route_accepted = False
            route_magnitude = False
            route_signed = False
        else:
            route_accepted = bool(selected["accepted"])
            route_magnitude = route_accepted and bool(selected["magnitude_retained"])
            route_signed = route_accepted and bool(selected["signed_retained"])
        diagnostic_correct_models = [
            model
            for model, outcome in model_results.items()
            if outcome["accepted"] and outcome["signed_retained"]
        ]
        details.append(
            {
                "schema": "tavonel.sec_source_fact_scored_region.v1",
                "benchmark_id": BENCHMARK_ID,
                "region_id": region_id,
                "ticker": fact["ticker"],
                "source_fact_sha256": fact["source_fact_sha256"],
                "expected_magnitude_token": magnitude,
                "expected_signed_token": signed,
                "ix_sign": fact.get("sign"),
                "models": model_results,
                "router": {
                    "selected_model": selected_model,
                    "route_reason": route["route_reason"],
                    "raw_unresolved": bool(route["unresolved"]),
                    "accepted": route_accepted,
                    "detected_failure": not route_accepted,
                    "magnitude_retained": route_magnitude,
                    "signed_retained": route_signed,
                    "silent_critical_loss": route_accepted and not route_signed,
                },
                "diagnostic_oracle": {
                    "signed_retained": bool(diagnostic_correct_models),
                    "correct_models": diagnostic_correct_models,
                },
            }
        )

    summaries = {
        model: summarize_outcomes([row["models"][model] for row in details])
        for model in PRIMARY_MODELS
    }
    router_summary = summarize_outcomes([row["router"] for row in details])
    best_fixed = min(
        PRIMARY_MODELS,
        key=lambda model: (
            summaries[model]["silent_critical_loss_count"],
            -summaries[model]["signed_retained_count"],
            model,
        ),
    )
    oracle_summary: dict[str, Any] = {
        "denominator": len(details),
        "signed_retained_count": sum(
            bool(row["diagnostic_oracle"]["signed_retained"]) for row in details
        ),
    }
    oracle_summary["signed_retained_rate"] = round(
        oracle_summary["signed_retained_count"] / len(details), 6
    )
    raw_route_unresolved = sum(bool(row["router"]["raw_unresolved"]) for row in details)
    correct_abstentions = sum(
        bool(row["router"]["raw_unresolved"])
        and not bool(row["diagnostic_oracle"]["signed_retained"])
        for row in details
    )
    avoidable_abstentions = raw_route_unresolved - correct_abstentions
    model_freeze = read_json(model_freeze_path)
    if model_freeze.get("benchmark_id") != BENCHMARK_ID:
        raise HoldoutScoringError("model output freeze benchmark mismatch")
    cost_latency = cost_and_latency(details, model_freeze)
    paired = {
        "router_minus_best_fixed_sclr": cluster_bootstrap_difference(
            details,
            lambda row: float(row["router"]["silent_critical_loss"]),
            lambda row: float(row["models"][best_fixed]["silent_critical_loss"]),
        ),
        "router_minus_best_fixed_signed_retention": cluster_bootstrap_difference(
            details,
            lambda row: float(row["router"]["signed_retained"]),
            lambda row: float(row["models"][best_fixed]["signed_retained"]),
        ),
    }
    result = {
        "schema": "tavonel.sec_source_fact_holdout_score.v1",
        "benchmark_id": BENCHMARK_ID,
        "scoring_commit": scoring_commit,
        "input_hashes": {
            "sealed_facts_sha256": sha256_file(facts_path),
            "final_routing_sha256": sha256_file(routing_root / "FINAL_ROUTING.jsonl"),
            "model_output_freeze_sha256": sha256_file(model_freeze_path),
        },
        "metric_contract": {
            "displayed_magnitude_retention": (
                "normalized visible numeric magnitude occurs in the complete row output; "
                "sign ignored"
            ),
            "signed_retention": (
                "the frozen Inline XBRL sign attribute plus normalized visible numeric token occurs"
            ),
            "sclr": (
                "signed critical token is absent while the candidate is accepted; semantic output "
                "errors and router refusal are detected failures, not silent losses"
            ),
            "known_limitation": (
                "row-level crops can contain repeated equal numeric tokens; this endpoint does not "
                "prove cell-to-fact alignment or full-document fidelity"
            ),
        },
        "model_results": summaries,
        "best_fixed_primary": best_fixed,
        "router_result": router_summary,
        "abstention": {
            "raw_unresolved_count": raw_route_unresolved,
            "correct_abstention_count": correct_abstentions,
            "avoidable_abstention_count": avoidable_abstentions,
            "correct_abstention_definition": (
                "router unresolved and no executed accepted candidate retained the signed fact"
            ),
        },
        "diagnostic_oracle": oracle_summary,
        "route_regret": {
            "signed_retention_vs_best_fixed": round(
                summaries[best_fixed]["signed_retained_rate"]
                - router_summary["signed_retained_rate"],
                6,
            ),
            "signed_retention_vs_executed_oracle": round(
                oracle_summary["signed_retained_rate"] - router_summary["signed_retained_rate"],
                6,
            ),
        },
        "paired_issuer_cluster_bootstrap": paired,
        "cost_latency": cost_latency,
        "evidence_class": "development_fresh_holdout",
        "protocol_frozen_before_acquisition": True,
        "model_outputs_and_router_frozen_before_truth": True,
        "concrete_scoring_implementation_committed_after_truth_open": True,
        "public_claim": False,
        "production_promotion": False,
    }
    return details, result


def self_test() -> None:
    cases: list[tuple[dict[str, Any], tuple[str, str]]] = [
        (
            {"region_id": "a", "normalized_visible_value": "1,009", "sign": None},
            ("1009", "1009"),
        ),
        (
            {"region_id": "b", "normalized_visible_value": "206", "sign": "-"},
            ("206", "-206"),
        ),
        (
            {"region_id": "c", "normalized_visible_value": "1.750", "sign": None},
            ("1.75", "1.75"),
        ),
        (
            {"region_id": "d", "normalized_visible_value": "0", "sign": "-"},
            ("0", "0"),
        ),
    ]
    for fact, expected in cases:
        observed = expected_tokens(fact)
        if observed != expected:
            raise HoldoutScoringError(f"expected token self-test failed: {observed} != {expected}")
    values = [1.0, 2.0, 3.0, 4.0]
    if nearest_rank(values, 0.5) != 2.0 or nearest_rank(values, 0.95) != 4.0:
        raise HoldoutScoringError("nearest-rank self-test failed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--facts", type=Path, required=True)
    parser.add_argument("--primary-root", type=Path, required=True)
    parser.add_argument("--adjudicator-root", type=Path, required=True)
    parser.add_argument("--routing-root", type=Path, required=True)
    parser.add_argument("--model-freeze", type=Path, required=True)
    parser.add_argument("--scoring-commit", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
    output_root = args.output_root.resolve()
    if output_root.exists() and any(output_root.iterdir()):
        raise HoldoutScoringError(f"output root is not empty: {output_root}")
    details, result = score(
        args.facts.resolve(),
        args.primary_root.resolve(),
        args.adjudicator_root.resolve(),
        args.routing_root.resolve(),
        args.model_freeze.resolve(),
        args.scoring_commit,
    )
    output_root.mkdir(parents=True, exist_ok=True)
    write_jsonl(output_root / "SCORED_REGIONS.jsonl", details)
    result["scored_regions_sha256"] = sha256_file(output_root / "SCORED_REGIONS.jsonl")
    atomic_json(output_root / "SCORE_RESULT.json", result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
