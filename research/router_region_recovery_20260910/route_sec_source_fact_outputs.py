#!/usr/bin/env python3
"""Route frozen SEC source-fact outputs without reading sealed source truth."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any

BENCHMARK_ID = "TAVONEL-SEC-SOURCE-FACT-HOLDOUT-20260910-V1"
PRIMARY_MODELS = ("mineru_vlm", "paddleocr_vl_1_6")
ADJUDICATOR_MODEL = "ovisocr2"
CHEAPER_PRIMARY = "paddleocr_vl_1_6"
EXPECTED_REGIONS = 24

_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_TAG_RE = re.compile(r"<[^>]+>")
_SPACED_PAREN_RE = re.compile(r"\(\s*((?:\d\s+){1,8}\d)\s*\)")
_PAREN_NUMBER_RE = re.compile(r"\(\s*\$?\s*(\d[\d,]*(?:\.\d+)?%?)\s*\)")
_NUMBER_RE = re.compile(r"(?<![\w])([+-]?\$?\s*\d[\d,]*(?:\.\d+)?%?)(?![\w])")


class RouterDecisionError(RuntimeError):
    pass


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_sha256(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return sha256_bytes(payload.encode("utf-8"))


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(
        json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
        for row in rows
    )
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(payload, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RouterDecisionError(f"{path} must contain an object")
    return value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise RouterDecisionError(f"{path}:{number} must contain an object")
        rows.append(value)
    return rows


def _normal_number(value: str) -> str:
    candidate = value.replace("$", "").replace(",", "").replace(" ", "")
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
    if sign == "+":
        sign = ""
    if candidate == "0":
        sign = ""
    return f"{sign}{candidate}{suffix}"


def critical_token_multiset(text: str) -> tuple[str, ...]:
    """Return normalized numeric/date/sign tokens visible in one model output."""

    visible = html.unescape(text)
    visible = _IMAGE_RE.sub(" ", visible)
    visible = _TAG_RE.sub(" ", visible)
    visible = visible.replace("\\$", "$")
    visible = _SPACED_PAREN_RE.sub(lambda match: f"({match.group(1).replace(' ', '')})", visible)
    negative_spans: list[tuple[int, int]] = []
    tokens: list[str] = []
    for match in _PAREN_NUMBER_RE.finditer(visible):
        value = _normal_number(match.group(1))
        tokens.append(value if value == "0" else f"-{value.lstrip('+-')}")
        negative_spans.append(match.span())
    for match in _NUMBER_RE.finditer(visible):
        if any(start <= match.start() and match.end() <= end for start, end in negative_spans):
            continue
        tokens.append(_normal_number(match.group(1)))
    return tuple(sorted(tokens))


def load_model_outputs(root: Path, model: str) -> dict[str, dict[str, Any]]:
    model_root = root / model
    complete = read_json(model_root / "COMPLETE.json")
    if complete.get("benchmark_id") != BENCHMARK_ID or complete.get("truth_opened") is not False:
        raise RouterDecisionError(f"{model}: run identity or truth boundary mismatch")
    if complete.get("pod_deleted") is not True or complete.get("teardown_errors") != []:
        raise RouterDecisionError(f"{model}: pod teardown is not complete")
    receipts = read_jsonl(model_root / "outputs.jsonl")
    if len(receipts) != EXPECTED_REGIONS:
        raise RouterDecisionError(f"{model}: output denominator is {len(receipts)}, expected 24")
    by_region: dict[str, dict[str, Any]] = {}
    for receipt in receipts:
        region_id = str(receipt["region_id"])
        if region_id in by_region:
            raise RouterDecisionError(f"{model}: duplicate region {region_id}")
        if receipt.get("benchmark_id") != BENCHMARK_ID or receipt.get("truth_opened") is not False:
            raise RouterDecisionError(f"{model}: output identity mismatch for {region_id}")
        canonical_path = root / str(receipt["canonical_path"])
        if sha256_file(canonical_path) != receipt["canonical_sha256"]:
            raise RouterDecisionError(f"{model}: canonical hash drift for {region_id}")
        text = canonical_path.read_text(encoding="utf-8")
        tokens = critical_token_multiset(text)
        by_region[region_id] = {
            "receipt": receipt,
            "tokens": tokens,
            "token_multiset_sha256": canonical_sha256(list(tokens)),
        }
    return by_region


def primary_decisions(primary_root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    mineru = load_model_outputs(primary_root, PRIMARY_MODELS[0])
    paddle = load_model_outputs(primary_root, PRIMARY_MODELS[1])
    if set(mineru) != set(paddle):
        raise RouterDecisionError("primary model denominators differ")
    decisions: list[dict[str, Any]] = []
    for region_id in sorted(mineru):
        mineru_tokens = mineru[region_id]["tokens"]
        paddle_tokens = paddle[region_id]["tokens"]
        agrees = Counter(mineru_tokens) == Counter(paddle_tokens)
        decisions.append(
            {
                "schema": "tavonel.sec_source_fact_primary_route.v1",
                "benchmark_id": BENCHMARK_ID,
                "region_id": region_id,
                "mineru_token_multiset_sha256": mineru[region_id]["token_multiset_sha256"],
                "paddle_token_multiset_sha256": paddle[region_id]["token_multiset_sha256"],
                "mineru_token_count": len(mineru_tokens),
                "paddle_token_count": len(paddle_tokens),
                "primary_agreement": agrees,
                "selected_model": CHEAPER_PRIMARY if agrees else None,
                "needs_adjudicator": not agrees,
                "truth_opened": False,
            }
        )
    adjudication_ids = [row["region_id"] for row in decisions if row["needs_adjudicator"]]
    summary = {
        "schema": "tavonel.sec_source_fact_primary_route_summary.v1",
        "benchmark_id": BENCHMARK_ID,
        "regions": len(decisions),
        "primary_agreement_count": len(decisions) - len(adjudication_ids),
        "adjudication_count": len(adjudication_ids),
        "adjudication_region_ids": adjudication_ids,
        "adjudication_region_ids_sha256": canonical_sha256(adjudication_ids),
        "primary_output_manifest_sha256": canonical_sha256(
            {
                model: [
                    {
                        "region_id": region_id,
                        "canonical_sha256": outputs[region_id]["receipt"]["canonical_sha256"],
                    }
                    for region_id in sorted(outputs)
                ]
                for model, outputs in ((PRIMARY_MODELS[0], mineru), (PRIMARY_MODELS[1], paddle))
            }
        ),
        "tokenization": (
            "numeric tokens with comma/currency normalization, parenthetical negatives "
            "and percent preservation"
        ),
        "lower_historical_cost_primary": CHEAPER_PRIMARY,
        "truth_opened": False,
    }
    return decisions, summary


def final_decisions(
    primary_root: Path, adjudicator_root: Path
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    mineru = load_model_outputs(primary_root, PRIMARY_MODELS[0])
    paddle = load_model_outputs(primary_root, PRIMARY_MODELS[1])
    ovis = load_model_outputs(adjudicator_root, ADJUDICATOR_MODEL)
    if set(mineru) != set(paddle) or set(mineru) != set(ovis):
        raise RouterDecisionError("model denominators differ")
    decisions: list[dict[str, Any]] = []
    for region_id in sorted(mineru):
        mineru_tokens = mineru[region_id]["tokens"]
        paddle_tokens = paddle[region_id]["tokens"]
        ovis_tokens = ovis[region_id]["tokens"]
        primary_agrees = Counter(mineru_tokens) == Counter(paddle_tokens)
        selected: str | None
        reason: str
        if primary_agrees:
            selected = CHEAPER_PRIMARY
            reason = "primary_agreement"
        elif Counter(ovis_tokens) == Counter(paddle_tokens):
            selected = PRIMARY_MODELS[1]
            reason = "ovis_corroborates_paddle"
        elif Counter(ovis_tokens) == Counter(mineru_tokens):
            selected = PRIMARY_MODELS[0]
            reason = "ovis_corroborates_mineru"
        else:
            selected = None
            reason = "no_complete_token_multiset_corroboration"
        decisions.append(
            {
                "schema": "tavonel.sec_source_fact_final_route.v1",
                "benchmark_id": BENCHMARK_ID,
                "region_id": region_id,
                "selected_model": selected,
                "route_reason": reason,
                "unresolved": selected is None,
                "model_token_multiset_sha256": {
                    PRIMARY_MODELS[0]: mineru[region_id]["token_multiset_sha256"],
                    PRIMARY_MODELS[1]: paddle[region_id]["token_multiset_sha256"],
                    ADJUDICATOR_MODEL: ovis[region_id]["token_multiset_sha256"],
                },
                "truth_opened": False,
            }
        )
    unresolved = [row["region_id"] for row in decisions if row["unresolved"]]
    summary = {
        "schema": "tavonel.sec_source_fact_final_route_summary.v1",
        "benchmark_id": BENCHMARK_ID,
        "regions": len(decisions),
        "resolved_count": len(decisions) - len(unresolved),
        "unresolved_count": len(unresolved),
        "unresolved_region_ids": unresolved,
        "unresolved_region_ids_sha256": canonical_sha256(unresolved),
        "decision_manifest_sha256": canonical_sha256(decisions),
        "truth_opened": False,
        "production_promotion": False,
    }
    return decisions, summary


def self_test() -> None:
    cases = {
        "Revenue $1,200 (45) 0 18.00 2.50%": ("-45", "0", "1200", "18", "2.5%"),
        "(6 5 8) — (1 2)": ("-12", "-658"),
        "<table><td>1,077</td></table>": ("1077",),
        "![](images/bbox_1_2_3_4.jpg) 95": ("95",),
        "April 30, 2026": ("2026", "30"),
        "": (),
    }
    for text, expected in cases.items():
        observed = critical_token_multiset(text)
        if observed != expected:
            raise RouterDecisionError(f"tokenization self-test failed: {text!r} -> {observed}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--primary-root", type=Path, required=True)
    parser.add_argument("--adjudicator-root", type=Path)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
    output_root = args.output_root.resolve()
    if output_root.exists() and any(output_root.iterdir()):
        raise RouterDecisionError(f"output root is not empty: {output_root}")
    if args.adjudicator_root is None:
        decisions, summary = primary_decisions(args.primary_root.resolve())
        name = "PRIMARY_ROUTING.jsonl"
        summary_name = "PRIMARY_DECISION.json"
    else:
        decisions, summary = final_decisions(
            args.primary_root.resolve(), args.adjudicator_root.resolve()
        )
        name = "FINAL_ROUTING.jsonl"
        summary_name = "FINAL_DECISION.json"
    output_root.mkdir(parents=True, exist_ok=True)
    write_jsonl(output_root / name, decisions)
    summary["routing_manifest_sha256"] = sha256_file(output_root / name)
    atomic_json(output_root / summary_name, summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
