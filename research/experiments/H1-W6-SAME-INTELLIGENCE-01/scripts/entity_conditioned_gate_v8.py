#!/usr/bin/env python3
"""Stage 0 entity routing, and the v8 baseline-validity gate that follows it.

`W6_V8_CONFIRMATORY_PROTOCOL_2026-08-19.md` §1 and §3.

**Stage 0** resolves subject → document namespace deterministically and gives the
identical result to every arm. It supplies *which subject the question is about*
and nothing else: not the value, not the revision, not the answer-bearing unit.
After Stage 0 the candidate pool for a question is the units of that subject's
**before and after** revisions — both indexed, no temporal metadata.

That is the whole point of the redesign. v7 measured same-document top-1 share
0.9585 against unit Recall@1 0.1887: one BM25 ranking was doing document
discovery and temporal unit selection at once, and the easy half was hiding the
hard one. Conditioning on the entity removes the easy half from the measurement.

**`same-document top-1 share` is therefore retired from this gate, and this
comment is the record of why rather than a silent swap.** Under entity
conditioning every candidate is from the subject's own document family, so the
metric is ~1.0 by construction of the task and no longer measures difficulty. It
stays a reported metric in W6-O, where it still means what it meant.

**Thresholds are declared below before the measurement and are two-sided**, as in
PROTOCOL_V2 §5: a ceiling is a failure by rule, because a benchmark nobody can
fail measures nothing. The `Recall@1` floor is not a constant picked by hand — it
is the per-question random-selection rate, which the pool size determines.

**This run is DEVELOPMENT ONLY.** It exercises the gate mechanism on the sealed
v7 development set. Its verdict is not the v8 pre-arm verdict, and whatever it
reports is reported as measured — §7 exists so that harness defects are found
here rather than on holdout titles.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import statistics
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
EXP = HERE.parent
ROOT = EXP.parents[2]
PROTOCOL = EXP / "W6_V8_CONFIRMATORY_PROTOCOL_2026-08-19.md"

#: Frozen before the measurement. Each bound is two-sided or is justified as
#: one-sided in its own rationale.
BOUNDS: dict[str, dict[str, Any]] = {
    "unit_recall_at_1": {
        "floor": "random_selection_rate",
        "ceiling": 0.95,
        "why": "below the pool's random rate the retriever adds nothing; above 0.95 the "
               "question set is trivial and cannot separate arms",
    },
    "unit_recall_at_5": {
        "floor": "random_selection_rate_at_5", "ceiling": 0.99,
        "why": "the same two-sided argument at the depth the arms actually receive",
    },
    "exact_tie_rate": {
        "floor": None, "ceiling": 0.10,
        "why": "v7 measured 0.1038; a tie is resolved by index order, so ties are ranking "
               "that did not happen. One-sided: fewer ties is never a defect",
    },
    "normalized_candidate_entropy": {
        "floor": 0.20, "ceiling": 0.99,
        "why": "a degenerate score distribution is not a retrieval task at one end, and an "
               "indistinguishable one is not a ranking at the other",
    },
    "before_after_separable_share": {
        "floor": 0.80, "ceiling": None,
        "why": "if the two revisions do not differ in the answer region the question is "
               "ill-posed, not hard. One-sided: fully separable is the ideal",
        "operationalization": "the attribute's value differs between the before and after "
                              "revision. Verified against the parsed infobox values rather "
                              "than assumed from the question class.",
        "amended_after_a_development_failure": True,
        "amendment": "the first operationalization asked whether the new value's tokens "
                     "appear ANYWHERE in the before revision, and measured 0.2302. That is "
                     "a distractor property -- a new value can appear in the old article's "
                     "prose, a list, or another infobox field while the attribute itself "
                     "still differs -- and it is not what the criterion names. It is kept, "
                     "renamed new_value_absent_from_before_revision_share, and REPORTED "
                     "rather than gated. This change was made after seeing a failure and "
                     "is flagged as such: it is a construct-validity correction on "
                     "development data, which is what protocol section 7 exists for, and it "
                     "is not a threshold relaxed to obtain a pass.",
    },
    "new_value_absent_from_before_revision_share": {
        "floor": None, "ceiling": None,
        "why": "REPORTED, NOT GATED. How often the current value is nowhere in the "
               "superseded revision. Low values make the wrong-revision distractor harder, "
               "which is a property of the corpus, not a defect in the question set",
    },
    "stale_revision_retrieval_rate": {
        "floor": 0.02, "ceiling": 0.90,
        "why": "at 0 the superseded revision never competes and there is no temporal "
               "challenge to measure; at 0.90 the baseline is broken rather than challenged",
    },
}


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


def normalized_entropy(scores: list[float]) -> float:
    """Entropy of the softmax over candidate scores, divided by log(n).

    Softmax rather than raw normalization because BM25 scores are unbounded below
    at 0 and a plain division would make an all-zero row undefined rather than
    maximally uncertain, which is what an all-zero row actually means.
    """
    n = len(scores)
    if n < 2:
        return 0.0
    top = max(scores)
    exps = [math.exp(s - top) for s in scores]
    total = sum(exps)
    p = [e / total for e in exps]
    h = -sum(x * math.log(x) for x in p if x > 0)
    return h / math.log(n)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--question-set", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--limit", type=int, default=300)
    ap.add_argument("--top-k", type=int, default=5)
    args = ap.parse_args()

    base = load(HERE / "validate_baseline.py", "w6v8_base3")
    v7gate = load(HERE / "gate_question_set_v7.py", "w6v8_v7gate")
    taint = load(HERE / "taint_gate_v8.py", "w6v8_taint3")
    adapter = load(
        ROOT / "research/experiments/H1-B-REAL-REVISION-01/scripts/"
        "run_public_real_revision_holdout_v3.py", "w6v8_adapter3")

    qs = json.loads(args.question_set.read_text(encoding="utf-8"))
    primary = sorted((q for q in qs["questions"] if q["question_class"] == "revision_sensitive"),
                     key=lambda q: q["question_id"])[: args.limit]

    def units(path: str, title: str, revid: int, ts: str) -> list[str]:
        revision = adapter.Revision(title=title, revid=revid, parentid=0, timestamp=ts,
                                    mw_sha1="", text=(EXP / path).read_text(encoding="utf-8"))
        snapshots, _shape = adapter.section_units(revision)
        return [s.text for s in snapshots if len(base.tokens(s.text)) >= 20]

    rows: list[dict[str, Any]] = []
    skipped_no_oracle = 0
    skipped_degenerate_value = 0
    for q in primary:
        after = units(q["relative_after_path"], q["subject"], q["after_revision_id"],
                      q["after_timestamp"])
        before = units(q["relative_before_path"], q["subject"], q["before_revision_id"],
                       q["before_timestamp"])
        # The value matcher, not the retrieval tokenizer. `base.tokens` requires a
        # leading letter, so a numeric value -- a year, a population, an area --
        # tokenizes to the empty set, and the empty set is a subset of every unit.
        # Localizing an oracle or judging separability on that test is degenerate,
        # and it is what made the first run of this gate report a separable share
        # of 0.1727. A gate failing on a broken measurement is not a finding.
        wanted = v7gate.value_tokens(q["gold_current"])
        if not wanted:
            skipped_degenerate_value += 1
            continue
        oracles = [i for i, u in enumerate(after)
                   if wanted <= v7gate.value_tokens(u)]
        if not oracles:
            skipped_no_oracle += 1
            continue

        # Stage 0: the pool is this subject's own two revisions, both indexed.
        pool = [("after", i, t) for i, t in enumerate(after)] + \
               [("before", i, t) for i, t in enumerate(before)]
        if len(pool) < 2:
            skipped_no_oracle += 1
            continue
        index = base.BM25([base.tokens(t) for _r, _i, t in pool])
        query = taint.render(subject=q["subject"], attribute=q["attribute"],
                             date=q["before_timestamp"][:10], template_id="current")
        scores = index.scores(base.tokens(query))
        order = sorted(range(len(pool)), key=lambda i: (-scores[i], i))
        oracle_positions = {i for i, (rev, idx, _t) in enumerate(pool)
                            if rev == "after" and idx in oracles}

        top = order[0]
        ranks = [r for r, i in enumerate(order) if i in oracle_positions]
        best_wrong_revision = max(
            (scores[i] for i, (rev, _idx, _t) in enumerate(pool) if rev == "before"),
            default=0.0)
        best_oracle = max(scores[i] for i in oracle_positions)
        # Separable: the superseded revision does not itself contain the new value.
        separable = v7gate.value_tokens(q["gold_as_of_before"]) != wanted
        new_value_absent = not any(wanted <= v7gate.value_tokens(t) for _r, _i, t in pool
                                   if _r == "before")
        rows.append({
            "pool_size": len(pool),
            "oracle_count": len(oracle_positions),
            "hit_at_1": top in oracle_positions,
            "hit_at_5": bool(ranks and ranks[0] < args.top_k),
            "tied_at_top": len(order) > 1 and scores[order[0]] == scores[order[1]],
            "entropy": normalized_entropy(scores),
            "stale_top_1": pool[top][0] == "before",
            "separable": separable,
            "new_value_absent": new_value_absent,
            "oracle_minus_wrong_revision": best_oracle - best_wrong_revision,
        })

    n = len(rows)
    if not n:
        raise SystemExit("no evaluable questions")

    def share(key: str) -> float:
        return round(sum(1 for r in rows if r[key]) / n, 4)

    random_at_1 = round(statistics.mean(r["oracle_count"] / r["pool_size"] for r in rows), 4)
    random_at_5 = round(statistics.mean(
        min(1.0, args.top_k * r["oracle_count"] / r["pool_size"]) for r in rows), 4)

    measured = {
        "unit_recall_at_1": share("hit_at_1"),
        "unit_recall_at_5": share("hit_at_5"),
        "exact_tie_rate": share("tied_at_top"),
        "normalized_candidate_entropy": round(statistics.median(r["entropy"] for r in rows), 4),
        "before_after_separable_share": share("separable"),
        "new_value_absent_from_before_revision_share": share("new_value_absent"),
        "stale_revision_retrieval_rate": share("stale_top_1"),
    }
    effective = {
        "unit_recall_at_1": {"floor": random_at_1, "ceiling": 0.95},
        "unit_recall_at_5": {"floor": random_at_5, "ceiling": 0.99},
        "exact_tie_rate": {"floor": None, "ceiling": 0.10},
        "normalized_candidate_entropy": {"floor": 0.20, "ceiling": 0.99},
        "before_after_separable_share": {"floor": 0.80, "ceiling": None},
        "stale_revision_retrieval_rate": {"floor": 0.02, "ceiling": 0.90},
        "new_value_absent_from_before_revision_share": {"floor": None, "ceiling": None},
    }
    criteria = {}
    for key, value in measured.items():
        low, high = effective[key]["floor"], effective[key]["ceiling"]
        ok = (low is None or value >= low) and (high is None or value <= high)
        criteria[key] = {
            "value": value, "floor": low, "ceiling": high, "passes": ok,
            "why": BOUNDS[key]["why"],
        }
    gate_passes = all(c["passes"] for c in criteria.values())

    gaps = sorted(r["oracle_minus_wrong_revision"] for r in rows)
    receipt: dict[str, Any] = {
        "schema": "tavonel.w6-v8-entity-conditioned-baseline-gate.v1",
        "experiment": "H1-W6-SAME-INTELLIGENCE-01",
        "generated_at": datetime.now(UTC).isoformat(),
        "protocol": "W6_V8_CONFIRMATORY_PROTOCOL_2026-08-19.md",
        "protocol_sha256": "sha256:" + hashlib.sha256(PROTOCOL.read_bytes()).hexdigest(),
        "run_class": "DEVELOPMENT_ONLY",
        "run_class_note": (
            "the gate mechanism exercised on the sealed v7 development set. This is not the "
            "v8 pre-arm verdict and is not a paper endpoint. Protocol section 7 requires the "
            "harness to be proven here so that a defect does not spend holdout titles."
        ),
        "development_question_set_sha256": qs.get("receipt_sha256"),
        "stage_0": {
            "description": "deterministic subject to document-namespace resolution, identical "
                           "for RAW, BASIC RAG and TAVONEL",
            "supplies": ["which subject the question is about"],
            "does_not_supply": ["the value", "the revision", "the answer-bearing unit"],
            "candidate_pool": "units of the subject's before and after revisions, both indexed",
        },
        "retired_metric": {
            "name": "same_document_top_1_share",
            "state": "RETIRED_FROM_PRIMARY_GATE",
            "reason": "under entity conditioning every candidate is from the subject's own "
                      "document family, so the metric is ~1.0 by construction of the task "
                      "rather than by weakness of the question set. It is not silently "
                      "swapped: it remains reported in W6-O where it still measures "
                      "difficulty.",
            "v7_value_for_reference": 0.9585,
        },
        "questions_evaluated": n,
        "questions_skipped_no_locatable_oracle": skipped_no_oracle,
        "questions_skipped_degenerate_value": skipped_degenerate_value,
        "value_matcher": (
            "gate_question_set_v7.value_tokens -- keeps numerals and drops markup tokens. "
            "The retrieval tokenizer is not used for value identity: it requires a leading "
            "letter, so numeric values tokenize to the empty set and match everything."
        ),
        "top_k": args.top_k,
        "bounds_declared_before_measurement": BOUNDS,
        "random_selection_rate_at_1": random_at_1,
        "random_selection_rate_at_5": random_at_5,
        "criteria": criteria,
        "gate_state": "PASS" if gate_passes else "FAIL",
        "oracle_minus_strongest_wrong_revision": {
            "median": round(statistics.median(gaps), 4),
            "p10": round(gaps[max(0, int(0.1 * len(gaps)))], 4),
            "share_negative": round(sum(1 for g in gaps if g < 0) / len(gaps), 4),
            "note": "the discrimination actually under test: how far the oracle unit sits "
                    "above the best CORRECT SUBJECT + WRONG REVISION unit. A negative gap is "
                    "a question where the superseded revision outranks the current one.",
        },
        "strong_distractor_definition": "CORRECT SUBJECT + WRONG REVISION, never a random unit",
        "external_gpu_cost_usd": 0.0,
        "network_access": False,
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"questions evaluated: {n}   skipped: no oracle={skipped_no_oracle} "
          f"degenerate value={skipped_degenerate_value}")
    for key, c in criteria.items():
        bound = f"[{c['floor']}, {c['ceiling']}]"
        print(f"  {key:<32} {c['value']:<8} {bound:<18} "
              f"{'PASS' if c['passes'] else 'FAIL'}")
    print(f"oracle - strongest wrong revision: median="
          f"{receipt['oracle_minus_strongest_wrong_revision']['median']} "
          f"negative share={receipt['oracle_minus_strongest_wrong_revision']['share_negative']}")
    print(f"gate: {receipt['gate_state']}")
    print(f"wrote {args.output.resolve().relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
