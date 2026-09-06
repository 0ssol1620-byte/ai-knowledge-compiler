#!/usr/bin/env python3
"""The pre-arm gates for corpus-v7: PROTOCOL_V2 §3 leakage, §4 pool, §5 baseline.

Nothing here runs an arm and nothing here sees an outcome. These are the gates a
question set has to pass *before* the three arms are allowed to execute, and a
set that breaches §3 is discarded rather than reported.

v1 died with median query↔oracle overlap 1.0 and Recall@1 0.9969 — a task that
could not fail — and every criterion below exists because of a specific way that
went wrong. §5's bounds are two-sided for that reason: a ceiling is a failure by
rule, not a triumph.

**Frozen before any measurement, because it changes what is measured:**

- The index is every section unit of **both** revisions of every article that
  produced a question (§4). Indexing only the before revision, as the v1/v2
  baseline did, hides the temporal ambiguity that is the phenomenon under test.
- Baseline validity is measured on the **primary endpoint class** — all 293
  revision-sensitive questions — plus a deterministic hash-ordered sample of
  **300 controls**. Scoring all 2,522 controls costs hours of BM25 and would not
  change a rate estimated on 300. The sample is by `question_id` hash order,
  fixed here, before any score exists.
- The retrieval query is `query_current`. Leakage is measured for all three §2
  template forms separately, because they are different queries and an average
  over them would hide a breach in one.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import re
import statistics
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
EXP = HERE.parent
ROOT = EXP.parents[2]
B = ROOT / "research/experiments/H1-B-REAL-REVISION-01"
ADAPTER = B / "scripts/run_public_real_revision_holdout_v3.py"
BASELINE = HERE / "validate_baseline.py"
PROTOCOL = EXP / "PROTOCOL_V2_2026-08-19.md"

#: PROTOCOL_V2 §3.
LEAKAGE = {"median_max": 0.50, "p90_max": 0.75, "verbatim_max": 0}
#: PROTOCOL_V2 §5. Upper bounds bind exactly as hard as lower bounds.
VALIDITY = {
    "recall_at_1": (0.30, 0.90),
    "recall_at_5": (0.60, 0.98),
    "tie_rate_max": 0.05,
    "median_overlap_max": 0.50,
    "p90_overlap_max": 0.75,
    "same_document_top1_share_max": 0.80,
    "candidate_entropy_min_bits": 1.5,
    "revision_leaking_queries_max": 0,
}
CONTROL_SAMPLE = 300


def canonical_sha256(value: Any) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


VALUE_TOKEN = re.compile(r"[a-z0-9]{2,}")
#: Wikitext markup that survives normalisation as a word and is not part of any
#: answer. Left in, it makes a gold value unlocalisable for a formatting reason.
MARKUP_TOKENS = {"br", "nbsp", "https", "http", "www", "ref", "small", "sup",
                 "sub", "flagicon", "nowrap"}


def value_tokens(text: str) -> set[str]:
    return {t for t in VALUE_TOKEN.findall(text.lower()) if t not in MARKUP_TOKENS}


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = (len(ordered) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return ordered[int(k)]
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def entropy_bits(scores: list[float]) -> float:
    positive = [s for s in scores if s > 0]
    total = sum(positive)
    if total <= 0 or len(positive) < 2:
        return 0.0
    return -sum((s / total) * math.log2(s / total) for s in positive)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--question-set", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()

    adapter = load(ADAPTER, "w6v7_adapter")
    base = load(BASELINE, "w6v7_baseline")
    tokens, BM25 = base.tokens, base.BM25

    qs = json.loads(args.question_set.read_text(encoding="utf-8"))
    questions = qs["questions"]

    # ---- index: both revisions of every article with a question (§4) -------
    by_subject: dict[str, dict[str, Any]] = {}
    for q in questions:
        by_subject.setdefault(q["subject"], q)

    units: list[dict[str, Any]] = []
    for subject, q in sorted(by_subject.items()):
        for side in ("before", "after"):
            text = (EXP / q[f"relative_{side}_path"]).read_text(encoding="utf-8")
            revision = adapter.Revision(
                title=subject, revid=q[f"{side}_revision_id"], parentid=0,
                timestamp=q[f"{side}_timestamp"], mw_sha1="", text=text)
            snapshots, _shape = adapter.section_units(revision)
            for snapshot in snapshots:
                if len(tokens(snapshot.text)) >= 20:
                    units.append({
                        "doc": subject, "side": side,
                        "revision_id": q[f"{side}_revision_id"],
                        "unit": snapshot.logical_id, "text": snapshot.text,
                    })

    index = BM25([tokens(u["text"]) for u in units])
    unit_text_lower = [u["text"].lower() for u in units]

    # ---- oracle: the unit of the target revision carrying the gold value ---
    # This is a *value-presence* test and deliberately not the frozen retrieval
    # tokenizer. That tokenizer drops pure numerals and short words, which is
    # right for BM25 and wrong here: "1995" and "AB" are answers. A raw substring
    # test is also wrong -- section_units normalises the body, so `Group&nbsp;1`
    # in the wikitext is `Group 1` in the unit and a substring match misses it.
    # Measured on the 293 primary questions: substring localises 205, the frozen
    # tokenizer 249, this matcher 265.
    unit_value_tokens = [value_tokens(u["text"]) for u in units]

    def oracle_for(q: dict[str, Any], side: str, gold: str) -> int | None:
        wanted = value_tokens(gold)
        if not wanted:
            return None
        best = None
        for i, u in enumerate(units):
            if u["doc"] != q["subject"] or u["side"] != side:
                continue
            # Prefer the shortest carrying unit: the infobox lead rather than a
            # section that happens to repeat the value.
            if wanted <= unit_value_tokens[i] and (
                best is None or len(units[i]["text"]) < len(units[best]["text"])
            ):
                best = i
        return best

    primary = [q for q in questions if q["question_class"] == "revision_sensitive"]
    controls = sorted(
        (q for q in questions if q["question_class"] == "simple_retrieval"),
        key=lambda q: q["question_id"],
    )[:CONTROL_SAMPLE]

    # ---- §3 leakage, per template form -------------------------------------
    forms = ("query_current", "query_as_of", "query_provenance")
    leakage: dict[str, Any] = {}
    for form in forms:
        overlaps, verbatim, scored = [], 0, 0
        title_share: list[float] = []
        without_title: list[float] = []
        for q in primary:
            idx = oracle_for(q, "after", q["gold_current"])
            if idx is None:
                continue
            scored += 1
            qt = set(tokens(q[form]))
            ot = set(tokens(units[idx]["text"]))
            shared_tokens = qt & ot
            overlaps.append(len(shared_tokens) / (len(qt) or 1))
            subject_tokens = set(tokens(q["subject"]))
            title_share.append(
                len(shared_tokens & subject_tokens) / (len(shared_tokens) or 1))
            # DIAGNOSTIC ONLY -- not a gate, and the gate above is not computed
            # from it. What section 3 would measure if the subject's own name were
            # excluded from the query. It answers one question: is the breach
            # answer leakage, or is it the article containing its own title?
            residual = qt - subject_tokens
            without_title.append(len(residual & ot) / (len(residual) or 1))
            if q[form].strip().lower() in unit_text_lower[idx]:
                verbatim += 1
        med, p90 = statistics.median(overlaps) if overlaps else 0.0, percentile(overlaps, 0.90)
        leakage[form] = {
            "questions_scored": scored,
            "median_overlap": round(med, 4),
            "p90_overlap": round(p90, 4),
            "verbatim_containment": verbatim,
            "median_share_of_overlap_from_subject_title": (
                round(statistics.median(title_share), 4) if title_share else 0.0),
            "DIAGNOSTIC_median_overlap_excluding_subject_tokens": (
                round(statistics.median(without_title), 4) if without_title else 0.0),
            "DIAGNOSTIC_p90_overlap_excluding_subject_tokens": (
                round(percentile(without_title, 0.90), 4)),
            "diagnostic_note": (
                "the two DIAGNOSTIC_ fields are not thresholds and did not enter the gate "
                "verdict. They separate two causes of a section 3 breach: answer wording "
                "leaking into the query, and the oracle passage containing the subject's "
                "own name."),
            "passes": (med <= LEAKAGE["median_max"] and p90 <= LEAKAGE["p90_max"]
                       and verbatim <= LEAKAGE["verbatim_max"]),
        }
    leakage_gate = all(v["passes"] for v in leakage.values())

    # ---- §5 baseline validity on query_current -----------------------------
    evaluated = primary + controls
    hits1 = hits5 = ties = same_doc = 0
    gaps: list[float] = []
    overlaps: list[float] = []
    entropies: list[float] = []
    unresolved = 0
    scored_items: list[dict[str, Any]] = []

    for q in evaluated:
        side = "after"
        gold = q["gold_current"]
        idx = oracle_for(q, side, gold)
        if idx is None:
            unresolved += 1
            continue
        scores = index.scores(tokens(q["query_current"]))
        order = sorted(range(len(scores)), key=lambda i: (-scores[i], i))
        top = order[:10]
        if len(order) > 1 and scores[order[0]] == scores[order[1]]:
            ties += 1
        if len(order) > 1:
            gaps.append(scores[order[0]] - scores[order[1]])
        entropies.append(entropy_bits([scores[i] for i in top]))
        if units[order[0]]["doc"] == q["subject"]:
            same_doc += 1
        if idx == top[0]:
            hits1 += 1
        if idx in top[:5]:
            hits5 += 1
        qt = set(tokens(q["query_current"]))
        ot = set(tokens(units[idx]["text"]))
        overlaps.append(len(qt & ot) / (len(qt) or 1))
        scored_items.append({
            "question_id": q["question_id"], "class": q["question_class"],
            "oracle_unit": units[idx]["unit"], "rank1": units[order[0]]["unit"],
        })

    n = len(scored_items) or 1

    # revision leakage: a query token present in exactly one of the two revisions
    revision_leaking = 0
    for q in primary:
        before = (EXP / q["relative_before_path"]).read_text(encoding="utf-8").lower()
        after = (EXP / q["relative_after_path"]).read_text(encoding="utf-8").lower()
        for form in forms:
            for t in set(tokens(q[form])):
                if (t in before) != (t in after):
                    revision_leaking += 1
                    break
            else:
                continue
            break

    measured = {
        "candidate_pool_units": len(units),
        "questions_scored": len(scored_items),
        "oracle_unresolved": unresolved,
        "recall_at_1": round(hits1 / n, 4),
        "recall_at_5": round(hits5 / n, 4),
        "tie_rate": round(ties / n, 4),
        "same_document_top1_share": round(same_doc / n, 4),
        "median_query_oracle_overlap": round(statistics.median(overlaps), 4) if overlaps else 0.0,
        "p90_query_oracle_overlap": round(percentile(overlaps, 0.90), 4),
        "median_candidate_entropy_bits": (
            round(statistics.median(entropies), 4) if entropies else 0.0),
        "median_score_gap": round(statistics.median(gaps), 4) if gaps else 0.0,
        "p25_score_gap": round(percentile(gaps, 0.25), 4),
        "revision_leaking_queries": revision_leaking,
    }

    lo1, hi1 = VALIDITY["recall_at_1"]
    lo5, hi5 = VALIDITY["recall_at_5"]
    checks = {
        "recall_at_1_within_bounds": lo1 <= measured["recall_at_1"] <= hi1,
        "recall_at_5_within_bounds": lo5 <= measured["recall_at_5"] <= hi5,
        "tie_rate": measured["tie_rate"] <= VALIDITY["tie_rate_max"],
        "median_overlap": (
            measured["median_query_oracle_overlap"] <= VALIDITY["median_overlap_max"]),
        "p90_overlap": measured["p90_query_oracle_overlap"] <= VALIDITY["p90_overlap_max"],
        "same_document_top1_share": (
            measured["same_document_top1_share"] <= VALIDITY["same_document_top1_share_max"]),
        "candidate_entropy": (
            measured["median_candidate_entropy_bits"] >= VALIDITY["candidate_entropy_min_bits"]),
        "revision_leakage": (
            measured["revision_leaking_queries"] <= VALIDITY["revision_leaking_queries_max"]),
    }
    # §4 distractor competitiveness
    checks["distractor_median_gap_positive"] = measured["median_score_gap"] > 0
    checks["distractor_p25_below_3x_median"] = (
        measured["p25_score_gap"] < 3 * measured["median_score_gap"])

    baseline_gate = all(checks.values())

    receipt: dict[str, Any] = {
        "schema": "tavonel.w6-v7-pre-arm-gates.v1",
        "experiment": "H1-W6-SAME-INTELLIGENCE-01",
        "generated_at": datetime.now(UTC).isoformat(),
        "protocol": "PROTOCOL_V2_2026-08-19.md",
        "protocol_sha256": "sha256:" + hashlib.sha256(PROTOCOL.read_bytes()).hexdigest(),
        "question_set_sha256": qs.get("receipt_sha256"),
        "corpus_root_sha256": qs.get("corpus_root_sha256"),
        "frozen_before_measurement": {
            "index": "every section unit of both revisions of every article with a question",
            "baseline_sample": (
                f"all {len(primary)} revision-sensitive questions plus the first "
                f"{CONTROL_SAMPLE} controls by question_id hash order"),
            "retrieval_query_form": "query_current",
        },
        "leakage_thresholds": LEAKAGE,
        "leakage_by_template_form": leakage,
        "leakage_gate": leakage_gate,
        "validity_thresholds": VALIDITY,
        "measured": measured,
        "checks": checks,
        "baseline_gate": baseline_gate,
        "cleared_to_run_arms": leakage_gate and baseline_gate,
        "endpoint_status": "NOT_RUN",
        "what_this_is_not": [
            "not a result -- no arm has been executed",
            "not a measure of answer correctness; retrieval validity only",
        ],
        "external_gpu_cost_usd": 0.0,
        "network_access": False,
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"index units: {len(units)}   scored: {len(scored_items)}   "
          f"oracle unresolved: {unresolved}")
    print("-- leakage (PROTOCOL_V2 section 3) --")
    for form, v in leakage.items():
        print(f"  {'PASS' if v['passes'] else 'FAIL':<5} {form:<18} "
              f"median={v['median_overlap']:<7} p90={v['p90_overlap']:<7} "
              f"verbatim={v['verbatim_containment']}")
    print("-- baseline validity (section 5) + pool (section 4) --")
    for k, ok in checks.items():
        print(f"  {'PASS' if ok else 'FAIL':<5} {k}")
    for k, v in measured.items():
        print(f"     {k:<34} {v}")
    print(f"cleared to run arms: {receipt['cleared_to_run_arms']}")
    print(f"wrote {args.output.resolve().relative_to(ROOT).as_posix()}")
    return 0 if receipt["cleared_to_run_arms"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
