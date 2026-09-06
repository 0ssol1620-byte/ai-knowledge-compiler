#!/usr/bin/env python3
"""End-to-end development run of the four W6 arms. Not an endpoint.

`W6_V8_CONFIRMATORY_PROTOCOL_2026-08-19.md` §7: the whole pipeline is exercised
on development data so that a harness defect is paid for here rather than with
holdout titles.

**Every number this produces is a harness check.** The model is
`ExtractiveDevelopmentModel`, which performs no inference --- it returns the first
gold candidate that the supplied context actually contains. That makes each arm's
result a pure function of *which evidence it retrieved*, which is exactly what
verifies the plumbing and exactly what cannot be a claim about any model. The
receipt records `run_class: DEVELOPMENT_ONLY` and `model.is_real_model: false`,
and the arm comparison is labelled an evidence-selection check rather than a
result.

Three controls run in the same execution and gate the exit code: the fairness
contract must separate, the scorer must separate, and the statistics must
separate. A pipeline whose controls did not fire has not been verified.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import statistics as stats
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
EXP = HERE.parent
ROOT = EXP.parents[2]
PROTOCOL = EXP / "W6_V8_CONFIRMATORY_PROTOCOL_2026-08-19.md"


def canonical_sha256(value: Any) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--question-set", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--development-model-context-tokens", type=int, default=32000,
                    help="stands in for the frozen model context until Qwen3.6-27B is "
                         "attested. Recorded as a development value, never as the frozen "
                         "one; the freeze receipt carries the attested number.")
    args = ap.parse_args()

    arms = load(HERE / "arms_v8.py", "w6_arms")
    scoring = load(HERE / "scoring_v8.py", "w6_scoring")
    base = load(HERE / "validate_baseline.py", "w6_base4")
    v7gate = load(HERE / "gate_question_set_v7.py", "w6_v7g4")
    adapter = load(
        ROOT / "research/experiments/H1-B-REAL-REVISION-01/scripts/"
        "run_public_real_revision_holdout_v3.py", "w6_adapter4")

    qs = json.loads(args.question_set.read_text(encoding="utf-8"))
    primary = sorted((q for q in qs["questions"]
                      if q["question_class"] == "revision_sensitive"),
                     key=lambda q: q["question_id"])[: args.limit]

    def units_of(q: dict[str, Any]) -> list[Any]:
        out: list[Any] = []
        for side in ("before", "after"):
            revision = adapter.Revision(
                title=q["subject"], revid=q[f"{side}_revision_id"], parentid=0,
                timestamp=q[f"{side}_timestamp"], mw_sha1="",
                text=(EXP / q[f"relative_{side}_path"]).read_text(encoding="utf-8"))
            snapshots, _shape = adapter.section_units(revision)
            kept = [s for s in snapshots if len(base.tokens(s.text)) >= 20]
            for i, snapshot in enumerate(kept):
                out.append(arms.Unit(
                    text=snapshot.text, revision=side, revision_id=q[f"{side}_revision_id"],
                    path=q[f"relative_{side}_path"], index=i,
                    valid_from=q[f"{side}_timestamp"],
                    valid_to=q["after_timestamp"] if side == "before" else None))
        return out

    arms.MODEL_CONTEXT_TOKENS = args.development_model_context_tokens

    outcomes: dict[str, list[Any]] = {a: [] for a in arms.ARMS}
    latency_ms: dict[str, list[float]] = {a: [] for a in arms.ARMS}
    raw_overflow: list[dict[str, Any]] = []
    budget: dict[str, list[dict[str, Any]]] = {a: [] for a in arms.ARMS}
    hard_negative: dict[str, dict[str, int]] = {
        a: {"correct_revision_top_1": 0, "wrong_revision_top_1": 0,
            "answer_from_stale_evidence": 0} for a in arms.ARMS}
    evaluated = 0
    skipped_no_oracle = 0

    for q in primary:
        pool = units_of(q)
        wanted = v7gate.value_tokens(q["gold_current"])
        oracle_indices = {u.index for u in pool
                          if u.revision == "after" and wanted <= v7gate.value_tokens(u.text)}
        if not oracle_indices:
            skipped_no_oracle += 1
            continue
        evaluated += 1

        model = arms.ExtractiveDevelopmentModel(
            lambda _question, q=q: [q["gold_current"], q["gold_as_of_before"]])
        query = q["query_current"]

        for arm in arms.ARMS:
            fn = arms.ADAPTERS[arm]
            started = time.perf_counter()
            try:
                evidence = (fn(pool, query, oracle_indices, as_of=None)
                            if arm == "TAVONEL" else fn(pool, query, oracle_indices))
            except arms.RawContextOverflow as overflow:
                # Never truncated silently. The question is recorded and RAW is
                # reported separately; the paired TAVONEL vs BASIC_RAG endpoint is
                # unaffected because RAW is a floor, not the comparator.
                raw_overflow.append({"question_id": q["question_id"],
                                     "subject": q["subject"], "reason": str(overflow)})
                outcomes[arm].append(scoring.score_answer(
                    response={"answer": None, "abstained": True},
                    gold_current=q["gold_current"],
                    gold_as_of_before=q["gold_as_of_before"], answerable=True,
                    cited_revision=None, oracle_revision="after"))
                budget[arm].append({"source_tokens": 0, "truncated": False,
                                    "units_available": len(pool), "units_omitted": len(pool),
                                    "oracle_omitted_by_truncation": False,
                                    "context_utilization": 0.0,
                                    "raw_context_overflow": True})
                latency_ms[arm].append((time.perf_counter() - started) * 1000)
                continue
            response = model.answer(query, evidence.as_context())
            latency_ms[arm].append((time.perf_counter() - started) * 1000)

            # Which revision actually supplied the answer. Read from the evidence
            # the harness handed over, never from the model's own account of it.
            cited = None
            if response.get("answer"):
                answer_tokens = set(arms.tokens(response["answer"]))
                for unit in evidence.units:
                    if answer_tokens and answer_tokens <= set(arms.tokens(unit.text)):
                        cited = unit.revision
                        break

            outcomes[arm].append(scoring.score_answer(
                response=response, gold_current=q["gold_current"],
                gold_as_of_before=q["gold_as_of_before"], answerable=True,
                cited_revision=cited, oracle_revision="after"))
            budget[arm].append({
                "source_tokens": evidence.source_tokens, "truncated": evidence.truncated,
                "units_available": evidence.units_available,
                "units_omitted": evidence.units_omitted,
                "oracle_omitted_by_truncation": evidence.oracle_omitted_by_truncation,
                "context_utilization": evidence.context_utilization,
                "raw_context_overflow": False,
            })
            top = evidence.units[0] if evidence.units else None
            if top is not None:
                key = ("correct_revision_top_1" if top.revision == "after"
                       else "wrong_revision_top_1")
                hard_negative[arm][key] += 1
            if cited == "before":
                hard_negative[arm]["answer_from_stale_evidence"] += 1

    if not evaluated:
        raise SystemExit("no evaluable questions")

    def rates(arm: str) -> dict[str, float]:
        rows = outcomes[arm]
        n = len(rows)
        return {field: round(sum(1 for r in rows if getattr(r, field)) / n, 4)
                for field in ("answer_correct", "evidence_correct",
                              "right_answer_stale_evidence", "temporal_correct",
                              "stale_answer", "provenance_localized",
                              "unsupported_assertion", "abstained",
                              "abstention_appropriate")}

    def budget_summary(arm: str) -> dict[str, Any]:
        rows = budget[arm]
        n = len(rows)
        return {
            "median_source_tokens": round(stats.median(r["source_tokens"] for r in rows), 1),
            "max_source_tokens": max(r["source_tokens"] for r in rows),
            "truncation_rate": round(sum(1 for r in rows if r["truncated"]) / n, 4),
            "median_units_omitted": round(stats.median(r["units_omitted"] for r in rows), 1),
            "oracle_omitted_by_truncation_rate": round(
                sum(1 for r in rows if r["oracle_omitted_by_truncation"]) / n, 4),
            "median_context_utilization": round(
                stats.median(r["context_utilization"] for r in rows), 4),
            "raw_context_overflow_count": sum(1 for r in rows
                                              if r.get("raw_context_overflow")),
            "median_latency_ms": round(stats.median(latency_ms[arm]), 3),
            "inference_cost_usd": None,
            "inference_cost_note": (
                "null because no inference occurred. The development model is extractive; "
                "cost is measured once the frozen model is attested and running."
            ),
        }

    def vector(arm: str, field: str) -> list[bool]:
        return [getattr(r, field) for r in outcomes[arm]]

    comparisons = {
        "primary_TAVONEL_vs_BASIC_RAG": scoring.paired_comparison(
            "TAVONEL", "BASIC_RAG", vector("TAVONEL", "answer_correct"),
            vector("BASIC_RAG", "answer_correct")),
        "TAVONEL_vs_BASIC_RAG_PLUS": scoring.paired_comparison(
            "TAVONEL", "BASIC_RAG_PLUS", vector("TAVONEL", "answer_correct"),
            vector("BASIC_RAG_PLUS", "answer_correct")),
        "TAVONEL_vs_RAW_floor": scoring.paired_comparison(
            "TAVONEL", "RAW", vector("TAVONEL", "answer_correct"),
            vector("RAW", "answer_correct")),
    }
    secondary = {
        field: scoring.paired_comparison("TAVONEL", "BASIC_RAG", vector("TAVONEL", field),
                                         vector("BASIC_RAG", field))
        for field in ("stale_answer", "temporal_correct", "evidence_correct",
                      "provenance_localized", "unsupported_assertion",
                      "abstention_appropriate", "right_answer_stale_evidence")
    }
    holm = scoring.holm({k: v["mcnemar_exact_p"] for k, v in secondary.items()})

    shared = {
        "model_identity": arms.ExtractiveDevelopmentModel(lambda _q: []).identity,
        "decoding": {"deterministic": True, "temperature": 0.0},
        "answer_schema": "answer|abstained|evidence_present",
        "subject_routing": "stage_0_deterministic_subject_to_document_namespace",
        "scorer": "scoring_v8.score_answer",
        "top_k": arms.TOP_K,
        "context_budget_tokens": arms.CONTEXT_BUDGET_TOKENS,
        "question_set_sha256": qs.get("receipt_sha256"),
    }
    arm_configs = {a: dict(shared, temporal_metadata_supplied=(a == "TAVONEL"))
                   for a in arms.ARMS}
    fairness = arms.fairness_contract(arm_configs)
    fairness_ctl = arms.fairness_control(shared)
    scoring_ctl = scoring.scoring_control()
    stats_ctl = scoring.statistics_control()
    controls_separate = (fairness["holds"] and fairness_ctl["separates"]
                         and scoring_ctl["separates"] and stats_ctl["separates"])

    receipt: dict[str, Any] = {
        "schema": "tavonel.w6-v8-development-arm-run.v1",
        "experiment": "H1-W6-SAME-INTELLIGENCE-01",
        "generated_at": datetime.now(UTC).isoformat(),
        "protocol": "W6_V8_CONFIRMATORY_PROTOCOL_2026-08-19.md",
        "protocol_sha256": file_sha256(PROTOCOL),
        "run_class": "DEVELOPMENT_ONLY",
        "run_class_note": (
            "the model performs no inference, so each arm's result is a pure function of "
            "the evidence it retrieved. This verifies the pipeline end to end. It is not a "
            "result about any model and must never be reported as a paper endpoint."
        ),
        "arm_comparison_meaning": (
            "an evidence-selection check, not a model comparison. It answers whether the "
            "harness routes different evidence to different arms and scores it correctly."
        ),
        "question_set": args.question_set.name,
        "question_set_sha256": qs.get("receipt_sha256"),
        "questions_evaluated": evaluated,
        "questions_skipped_no_locatable_oracle": skipped_no_oracle,
        "source_hashes": {name: file_sha256(HERE / name) for name in
                          ("arms_v8.py", "scoring_v8.py", "build_question_set_v8.py",
                           "taint_gate_v8.py", "residual_overlap_v8.py",
                           "entity_conditioned_gate_v8.py", "run_arms_dev_v8.py")},
        "shared_configuration": shared,
        "fairness_contract": fairness,
        "controls": {
            "fairness": fairness_ctl, "scoring": scoring_ctl, "statistics": stats_ctl,
            "all_separate": controls_separate,
        },
        "rates_by_arm": {arm: rates(arm) for arm in arms.ARMS},
        "context_budget_by_arm": {arm: budget_summary(arm) for arm in arms.ARMS},
        "raw_context_budget_policy": arms.RAW_BUDGET_POLICY,
        "raw_context_budget_policy_note": (
            "founder decision of 2026-08-20, option B. RAW receives the whole before + "
            "after document pair against the frozen model context rather than the "
            "retrieval budget, because under the shared budget its floor was set by "
            "context capacity rather than by knowledge representation. The asymmetry "
            "favours the floor and is reported rather than hidden. RAW is a floor only; "
            "the primary comparison remains TAVONEL vs BASIC_RAG."
        ),
        "development_model_context_tokens": args.development_model_context_tokens,
        "development_model_context_note": (
            "a development stand-in, not the frozen value. The freeze receipt carries the "
            "attested Qwen3.6-27B context window."
        ),
        "raw_context_overflow": {
            "count": len(raw_overflow),
            "questions": raw_overflow[:10],
            "handling": "recorded, never silently truncated. RAW is scored as an "
                        "abstention on those questions and reported separately; the paired "
                        "TAVONEL vs BASIC_RAG primary endpoint is unaffected because RAW is "
                        "not the comparator.",
        },
        "temporal_hard_negative": hard_negative,
        "temporal_hard_negative_note": (
            "the hard negative is CORRECT SUBJECT + WRONG REVISION. wrong_revision_top_1 and "
            "answer_from_stale_evidence are the columns that show it directly."
        ),
        "primary_comparison": comparisons["primary_TAVONEL_vs_BASIC_RAG"],
        "comparisons": comparisons,
        "secondary_comparisons": secondary,
        "secondary_multiplicity": holm,
        "external_gpu_cost_usd": 0.0,
        "network_access": False,
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")

    print(f"questions evaluated: {evaluated}   skipped (no oracle): {skipped_no_oracle}")
    print(f"controls separate: {controls_separate}   fairness holds: {fairness['holds']}")
    for arm in arms.ARMS:
        r = rates(arm)
        b = budget_summary(arm)
        print(f"  {arm:<16} correct={r['answer_correct']:<7} "
              f"evidence={r['evidence_correct']:<7} stale={r['stale_answer']:<7} "
              f"trunc={b['truncation_rate']:<7} "
              f"oracle_lost={b['oracle_omitted_by_truncation_rate']}")
    p = comparisons["primary_TAVONEL_vs_BASIC_RAG"]
    print(f"primary TAVONEL vs BASIC_RAG: effect={p['absolute_effect']} "
          f"ci={p['paired_difference_ci95']} discordant={p['discordant_pairs']['total']} "
          f"p={p['mcnemar_exact_p']}")
    print(f"wrote {args.output.resolve().relative_to(ROOT).as_posix()}")
    return 0 if controls_separate else 1


if __name__ == "__main__":
    sys.exit(main())
