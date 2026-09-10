#!/usr/bin/env python3
"""Score the spent-development SEC target-cell model and Router outputs."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import os
import random
import re
from collections import Counter
from pathlib import Path
from typing import Any

from score_sec_source_fact_holdout import displayed_expected_tokens

BENCHMARK_ID = "TAVONEL-SEC-TARGET-CELL-DEVELOPMENT-20260910-V1"
MODELS = ("mineru_vlm", "paddleocr_vl_1_6", "ovisocr2")
PRIMARY = ("ovisocr2", "paddleocr_vl_1_6")
RECOVERY = "mineru_vlm"
EXPECTED_REGIONS = 24
BOOTSTRAP_REPLICATES = 5_000
BOOTSTRAP_SEED = 20_260_910

_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_TAG_RE = re.compile(r"<[^>]+>")
_PAREN_NUMBER_RE = re.compile(r"\(\s*\$?\s*(\d[\d,]*(?:\.\d+)?%?)\s*\)")
_NUMBER_RE = re.compile(r"(?<![\w])([+-]?\$?\s*\d[\d,]*(?:\.\d+)?%?)(?![\w])")


class TargetCellScoreError(RuntimeError):
    pass


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_sha256(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return sha256_bytes(payload.encode("utf-8"))


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TargetCellScoreError(f"{path} must contain an object")
    return value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise TargetCellScoreError(f"{path}:{number} must contain an object")
        rows.append(value)
    return rows


def atomic_json(path: Path, value: object) -> None:
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


def normal_number(value: str) -> str:
    candidate = re.sub(r"\s+", "", value.replace("$", "").replace(",", ""))
    suffix = "%" if candidate.endswith("%") else ""
    if suffix:
        candidate = candidate[:-1]
    sign = ""
    if candidate.startswith(("+", "-")):
        sign, candidate = candidate[0], candidate[1:]
    if "." in candidate:
        integer, fraction = candidate.split(".", 1)
        integer = integer.lstrip("0") or "0"
        fraction = fraction.rstrip("0")
        candidate = integer if not fraction else f"{integer}.{fraction}"
    else:
        candidate = candidate.lstrip("0") or "0"
    if sign == "+" or candidate == "0":
        sign = ""
    return f"{sign}{candidate}{suffix}"


def critical_tokens(text: str) -> tuple[str, ...]:
    visible = html.unescape(text)
    visible = _IMAGE_RE.sub(" ", visible)
    visible = _TAG_RE.sub(" ", visible)
    visible = visible.replace("\\$", "$")
    visible = re.sub(r"(?<=\d)\s+%", "%", visible)
    negative_spans: list[tuple[int, int]] = []
    tokens: list[str] = []
    for match in _PAREN_NUMBER_RE.finditer(visible):
        value = normal_number(match.group(1))
        tokens.append(value if value == "0" else "-" + value.lstrip("+-"))
        negative_spans.append(match.span())
    for match in _NUMBER_RE.finditer(visible):
        if any(start <= match.start() and match.end() <= end for start, end in negative_spans):
            continue
        tokens.append(normal_number(match.group(1)))
    return tuple(sorted(tokens))


def load_outputs(root: Path, model: str) -> dict[str, dict[str, Any]]:
    model_root = root / model
    complete = read_json(model_root / "COMPLETE.json")
    if complete.get("benchmark_id") != BENCHMARK_ID or complete.get("truth_opened") is not True:
        raise TargetCellScoreError(f"{model}: benchmark/truth-state mismatch")
    if complete.get("pod_deleted") is not True or complete.get("teardown_errors") != []:
        raise TargetCellScoreError(f"{model}: teardown receipt is incomplete")
    rows = read_jsonl(model_root / "outputs.jsonl")
    if len(rows) != EXPECTED_REGIONS:
        raise TargetCellScoreError(f"{model}: output denominator is {len(rows)}")
    outputs: dict[str, dict[str, Any]] = {}
    for row in rows:
        region_id = str(row["region_id"])
        if region_id in outputs:
            raise TargetCellScoreError(f"{model}: duplicate region {region_id}")
        if row.get("benchmark_id") != BENCHMARK_ID or row.get("truth_opened") is not True:
            raise TargetCellScoreError(f"{model}: output identity mismatch for {region_id}")
        canonical_path = root / str(row["canonical_path"])
        if sha256_file(canonical_path) != row["canonical_sha256"]:
            raise TargetCellScoreError(f"{model}: canonical hash drift for {region_id}")
        tokens = critical_tokens(canonical_path.read_text(encoding="utf-8"))
        usable = (
            row.get("status") == "SUCCESS"
            and row.get("semantic_error_class") is None
            and bool(tokens)
        )
        outputs[region_id] = {"receipt": row, "tokens": tokens, "usable": usable}
    return outputs


def nearest_rank(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise TargetCellScoreError("empty percentile input")
    index = max(0, min(len(ordered) - 1, math.ceil(percentile * len(ordered)) - 1))
    return ordered[index]


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    keys = ("accepted", "signed_retained", "silent_critical_loss", "detected_failure")
    counts = {key: sum(bool(row[key]) for row in rows) for key in keys}
    return {
        "denominator": total,
        **{f"{key}_count": value for key, value in counts.items()},
        **{f"{key}_rate": round(value / total, 6) for key, value in counts.items()},
    }


def bootstrap_difference(
    details: list[dict[str, Any]], metric: str, model: str
) -> dict[str, Any]:
    issuers: dict[str, list[dict[str, Any]]] = {}
    for row in details:
        issuers.setdefault(str(row["ticker"]), []).append(row)
    names = sorted(issuers)
    rng = random.Random(BOOTSTRAP_SEED)  # noqa: S311 - deterministic bootstrap
    samples: list[float] = []
    for _ in range(BOOTSTRAP_REPLICATES):
        selected = [names[rng.randrange(len(names))] for _ in names]
        rows = [row for name in selected for row in issuers[name]]
        samples.append(
            sum(
                float(row["router"][metric]) - float(row["models"][model][metric])
                for row in rows
            )
            / len(rows)
        )
    observed = sum(
        float(row["router"][metric]) - float(row["models"][model][metric])
        for row in details
    ) / len(details)
    return {
        "difference": round(observed, 6),
        "ci95": [
            round(nearest_rank(samples, 0.025), 6),
            round(nearest_rank(samples, 0.975), 6),
        ],
        "clusters": len(names),
        "replicates": BOOTSTRAP_REPLICATES,
        "seed": BOOTSTRAP_SEED,
    }


def outcome(output: dict[str, Any], expected: str) -> dict[str, Any]:
    retained = Counter(output["tokens"])[expected] > 0
    accepted = bool(output["usable"])
    receipt = output["receipt"]
    return {
        "accepted": accepted,
        "signed_retained": retained,
        "silent_critical_loss": accepted and not retained,
        "detected_failure": not accepted,
        "semantic_error_class": receipt.get("semantic_error_class"),
        "tokens": list(output["tokens"]),
        "processing_ms": int(receipt["timings_ms"]["total_ms"]),
        "inference_ms": int(receipt["timings_ms"]["inference_ms"]),
    }


def adaptive_decision(outputs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    left, right = PRIMARY
    left_output = outputs[left]
    right_output = outputs[right]
    if (
        left_output["usable"]
        and right_output["usable"]
        and Counter(left_output["tokens"]) == Counter(right_output["tokens"])
    ):
        return {
            "selected_model": left,
            "reason": "primary_target_token_agreement",
            "recovery": False,
        }
    usable = [model for model in MODELS if outputs[model]["usable"]]
    for first_index, first in enumerate(usable):
        for second in usable[first_index + 1 :]:
            if Counter(outputs[first]["tokens"]) == Counter(outputs[second]["tokens"]):
                selected = left if left in (first, second) else first
                return {
                    "selected_model": selected,
                    "reason": f"recovery_agreement:{first}+{second}",
                    "recovery": True,
                }
    return {
        "selected_model": None,
        "reason": "no_target_token_corroboration",
        "recovery": True,
    }


def score(
    facts_path: Path,
    output_root: Path,
    execution_result_path: Path,
    scoring_commit: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if re.fullmatch(r"[0-9a-f]{40}", scoring_commit) is None:
        raise TargetCellScoreError("scoring commit must be a full lowercase Git SHA-1")
    facts = read_jsonl(facts_path)
    if len(facts) != EXPECTED_REGIONS:
        raise TargetCellScoreError("sealed fact denominator drift")
    fact_by_id = {str(row["region_id"]): row for row in facts}
    if len(fact_by_id) != EXPECTED_REGIONS:
        raise TargetCellScoreError("duplicate sealed facts")
    outputs = {model: load_outputs(output_root, model) for model in MODELS}
    if any(set(model_outputs) != set(fact_by_id) for model_outputs in outputs.values()):
        raise TargetCellScoreError("model output denominator differs from sealed facts")
    details: list[dict[str, Any]] = []
    facts_root = facts_path.parent
    for region_id in sorted(fact_by_id):
        fact = fact_by_id[region_id]
        _, expected, presentation_negative, presentation_percent = displayed_expected_tokens(
            fact, facts_root
        )
        model_rows = {
            model: outcome(outputs[model][region_id], expected) for model in MODELS
        }
        decision = adaptive_decision({model: outputs[model][region_id] for model in MODELS})
        selected_model = decision["selected_model"]
        selected = model_rows[str(selected_model)] if selected_model is not None else None
        accepted = selected is not None and bool(selected["accepted"])
        retained = accepted and selected is not None and bool(selected["signed_retained"])
        details.append(
            {
                "schema": "tavonel.sec_target_cell_scored_region.v1",
                "region_id": region_id,
                "ticker": fact["ticker"],
                "source_fact_sha256": fact["source_fact_sha256"],
                "expected_displayed_token": expected,
                "presentation_negative": presentation_negative,
                "presentation_percent": presentation_percent,
                "models": model_rows,
                "router": {
                    **decision,
                    "accepted": accepted,
                    "signed_retained": retained,
                    "silent_critical_loss": accepted and not retained,
                    "detected_failure": not accepted,
                },
            }
        )
    model_summaries = {
        model: summarize([row["models"][model] for row in details]) for model in MODELS
    }
    router_summary = summarize([row["router"] for row in details])
    best_fixed = min(
        MODELS,
        key=lambda model: (
            model_summaries[model]["silent_critical_loss_count"],
            -model_summaries[model]["signed_retained_count"],
            model,
        ),
    )
    complete = {model: read_json(output_root / model / "COMPLETE.json") for model in MODELS}
    rates = {model: float(complete[model]["provider_hourly_rate_usd"]) for model in MODELS}
    cost_latency: dict[str, Any] = {"models": {}}
    for model in MODELS:
        processing = [float(row["models"][model]["processing_ms"]) for row in details]
        inference = [float(row["models"][model]["inference_ms"]) for row in details]
        warm_cost = sum(inference) / 3_600_000 * rates[model]
        cost_latency["models"][model] = {
            "warm_inference_cost_per_1000_regions_usd": round(
                warm_cost / len(details) * 1_000, 6
            ),
            "processing_p50_ms": nearest_rank(processing, 0.5),
            "processing_p95_ms": nearest_rank(processing, 0.95),
        }
    router_processing: list[float] = []
    router_inference_cost = 0.0
    recovery_count = 0
    for row in details:
        primary_processing = max(float(row["models"][m]["processing_ms"]) for m in PRIMARY)
        router_inference_cost += sum(
            float(row["models"][m]["inference_ms"]) / 3_600_000 * rates[m]
            for m in PRIMARY
        )
        if row["router"]["recovery"]:
            recovery_count += 1
            primary_processing += float(row["models"][RECOVERY]["processing_ms"])
            router_inference_cost += (
                float(row["models"][RECOVERY]["inference_ms"])
                / 3_600_000
                * rates[RECOVERY]
            )
        router_processing.append(primary_processing)
    execution = read_json(execution_result_path)
    cost_latency["router"] = {
        "primary_models": list(PRIMARY),
        "recovery_model": RECOVERY,
        "model_region_calls": len(details) * len(PRIMARY) + recovery_count,
        "recovery_region_count": recovery_count,
        "warm_inference_cost_per_1000_regions_usd": round(
            router_inference_cost / len(details) * 1_000, 6
        ),
        "processing_p50_ms": nearest_rank(router_processing, 0.5),
        "processing_p95_ms": nearest_rank(router_processing, 0.95),
        "all_three_model_cold_start_experiment_cost_usd": float(
            execution["estimated_actual_gpu_cost_usd"]
        ),
    }
    result = {
        "schema": "tavonel.sec_target_cell_development_score.v1",
        "benchmark_id": BENCHMARK_ID,
        "scoring_commit": scoring_commit,
        "inputs": {
            "sealed_facts_sha256": sha256_file(facts_path),
            "execution_result_sha256": sha256_file(execution_result_path),
            "model_output_manifests": {
                model: sha256_file(output_root / model / "outputs.jsonl") for model in MODELS
            },
        },
        "tokenizer": (
            "numeric tokens; all whitespace removed inside a number; currency/comma normalized; "
            "parenthetical negative and spaced percent preserved; image links and tags removed"
        ),
        "model_results": model_summaries,
        "best_fixed_model": best_fixed,
        "router_result": router_summary,
        "router_policy": (
            "run Ovis and Paddle in parallel; accept complete non-empty target-token agreement; "
            "otherwise run MinerU and accept only an exactly corroborated token multiset"
        ),
        "router_minus_best_fixed": {
            "sclr": bootstrap_difference(details, "silent_critical_loss", best_fixed),
            "signed_retention": bootstrap_difference(details, "signed_retained", best_fixed),
        },
        "cost_latency": cost_latency,
        "evidence_class": "spent_development_target_crop",
        "source_truth_opened_before_crop_and_policy": True,
        "model_inputs_do_not_contain_truth": True,
        "public_claim": False,
        "production_promotion": False,
    }
    return details, result


def self_test() -> None:
    cases = {
        "$$\n0 \\quad \\$\n$$": ("0",),
        "### 1.750 % Senior": ("1.75%",),
        "( 206 )": ("-206",),
        "![](images/1_2_3.jpg)": (),
    }
    for text, expected in cases.items():
        observed = critical_tokens(text)
        if observed != expected:
            raise TargetCellScoreError(f"tokenizer self-test failed: {text!r} -> {observed}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--facts", type=Path, required=True)
    parser.add_argument("--model-output-root", type=Path, required=True)
    parser.add_argument("--execution-result", type=Path, required=True)
    parser.add_argument("--scoring-commit", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
    output_root = args.output_root.resolve()
    if output_root.exists():
        raise TargetCellScoreError(f"output root already exists: {output_root}")
    output_root.mkdir(parents=True)
    details, result = score(
        args.facts.resolve(),
        args.model_output_root.resolve(),
        args.execution_result.resolve(),
        args.scoring_commit,
    )
    write_jsonl(output_root / "SCORED_REGIONS.jsonl", details)
    result["scored_regions_sha256"] = sha256_file(output_root / "SCORED_REGIONS.jsonl")
    result["result_payload_sha256"] = canonical_sha256(result)
    atomic_json(output_root / "SCORE_RESULT.json", result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
