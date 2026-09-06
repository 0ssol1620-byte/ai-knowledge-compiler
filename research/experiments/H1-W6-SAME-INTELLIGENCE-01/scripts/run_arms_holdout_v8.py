#!/usr/bin/env python3
"""The W6 v8 confirmatory run. Four arms, one frozen model, one holdout.

This is `run_arms_dev_v8.py`'s pipeline with the stub replaced by the attested
runtime. Everything that decides a number --- retrieval, budgets, scoring,
statistics, controls --- is the same code, pinned by the same digests in
`receipts/v8-config-freeze.json`. The differences are the ones a confirmatory run
must have:

- the model is real, and the freeze's attestation is re-checked against the
  runtime that answers, not merely quoted;
- the question set must carry `run_class: HOLDOUT_CONFIRMATORY`;
- latency, context utilization, prompt/completion tokens and GPU cost are
  measured per arm, because a representation that wins by spending ten times the
  context has not won the thing the paper claims;
- `RAW_CONTEXT_OVERFLOW` is a recorded outcome, never a quiet truncation.

**The control cohort is here deliberately.** `simple_retrieval` questions are
attributes whose value did **not** change between the two revisions. They are the
control for the obvious failure mode of a temporal system: an arm that wins the
primary by always preferring the later revision should show nothing on the
control, and an arm that has broken something will. The cohort is capped and
selected in `question_id` order, both fixed in the freeze, so it cannot be chosen
on an outcome.

`--development-dry-run` runs the whole thing against the extractive stub on the
development question set. That is how this file is verified before a holdout
title is spent on it; its output is `DEVELOPMENT_ONLY` and is never an endpoint.
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
RECEIPTS = EXP / "receipts"
PROTOCOL = EXP / "W6_V8_CONFIRMATORY_PROTOCOL_2026-08-19.md"
FREEZE = RECEIPTS / "v8-config-freeze.json"


def canonical_sha256(value: Any) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def display(path: Path) -> str:
    """Repo-relative when it can be, absolute otherwise.

    A progress message must not be able to fail the run it reports on, and
    `relative_to` raises for the temporary output directory a dry run uses.
    """
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def verify_freeze(freeze: dict[str, Any]) -> list[dict[str, Any]]:
    """Re-check every pinned source. A confirmatory run on drifted code is not one."""
    drift = []
    for name, digest in (freeze.get("arm_source_hashes") or {}).items():
        path = HERE / name
        if not path.exists():
            drift.append({"source": name, "state": "MISSING"})
        elif file_sha256(path) != digest:
            drift.append({"source": name, "state": "CHANGED"})
    return drift


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--question-set", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--freeze", type=Path, default=FREEZE)
    ap.add_argument("--base-url", help="the attested runtime's OpenAI-compatible base URL")
    ap.add_argument("--development-dry-run", action="store_true",
                    help="verify this harness against the extractive stub on development "
                         "data. Output is DEVELOPMENT_ONLY and is never an endpoint.")
    ap.add_argument("--primary-limit", type=int, default=200)
    ap.add_argument("--control-limit", type=int, default=150)
    ap.add_argument("--pod-cost-per-hour-usd", type=float, default=0.0)
    args = ap.parse_args()

    arms = load(HERE / "arms_v8.py", "w6h_arms")
    scoring = load(HERE / "scoring_v8.py", "w6h_scoring")
    base = load(HERE / "validate_baseline.py", "w6h_base")
    v7gate = load(HERE / "gate_question_set_v7.py", "w6h_v7g")
    adapter = load(
        ROOT / "research/experiments/H1-B-REAL-REVISION-01/scripts/"
        "run_public_real_revision_holdout_v3.py", "w6h_adapter")

    freeze = json.loads(args.freeze.read_text(encoding="utf-8")) if args.freeze.exists() \
        else None
    if not args.development_dry_run:
        if not freeze:
            print("refusing: no config freeze. The endpoint is produced under the lock.")
            return 2
        drift = verify_freeze(freeze)
        if drift:
            print(f"refusing: {len(drift)} pinned sources drifted since the freeze")
            for item in drift:
                print(f"  {item['state']}: {item['source']}")
            return 2
        if not args.base_url:
            print("refusing: --base-url is required; there is no fallback model")
            return 2

    qs = json.loads(args.question_set.read_text(encoding="utf-8"))
    if not args.development_dry_run and qs.get("run_class") != "HOLDOUT_CONFIRMATORY":
        print(f"refusing: the question set is {qs.get('run_class')}, not "
              "HOLDOUT_CONFIRMATORY. Development questions cannot produce the endpoint.")
        return 2

    def cohort(name: str, limit: int) -> list[dict[str, Any]]:
        return sorted((q for q in qs["questions"] if q["question_class"] == name),
                      key=lambda q: q["question_id"])[:limit]

    primary = cohort("revision_sensitive", args.primary_limit)
    controls = cohort("simple_retrieval", args.control_limit)

    if args.development_dry_run:
        model: Any = None
        context_tokens = 32000
        model_identity = arms.ExtractiveDevelopmentModel(lambda _q: []).identity
        decoding = {"deterministic": True, "temperature": 0.0}
    else:
        vllm = load(HERE / "vllm_model_v8.py", "w6h_vllm")
        attestation = freeze["model_attestation"]
        model = vllm.VLLMChatModel(base_url=args.base_url,
                                   model_name=freeze["model_identity"]["name"],
                                   attestation=attestation)
        live = model.answer("Reply with exactly one word: ready.", "none")
        if not live.get("raw_output"):
            print("refusing: the runtime did not answer the liveness call")
            return 3
        context_tokens = freeze["model_context_tokens"]
        model_identity = model.identity
        decoding = model.decoding
        if decoding["temperature"] != freeze["decoding"]["temperature"] or \
                decoding["max_tokens"] != freeze["decoding"]["max_tokens"]:
            print("refusing: the client's decoding is not the frozen decoding")
            return 3

    arms.MODEL_CONTEXT_TOKENS = context_tokens

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

    def run_cohort(questions: list[dict[str, Any]], label: str) -> dict[str, Any]:
        outcomes: dict[str, list[Any]] = {a: [] for a in arms.ARMS}
        latency_ms: dict[str, list[float]] = {a: [] for a in arms.ARMS}
        budget: dict[str, list[dict[str, Any]]] = {a: [] for a in arms.ARMS}
        usage: dict[str, dict[str, int]] = {
            a: {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0} for a in arms.ARMS}
        hard_negative: dict[str, dict[str, int]] = {
            a: {"correct_revision_top_1": 0, "wrong_revision_top_1": 0,
                "answer_from_stale_evidence": 0} for a in arms.ARMS}
        raw_overflow: list[dict[str, Any]] = []
        wall: dict[str, float] = {a: 0.0 for a in arms.ARMS}
        evaluated = 0
        skipped_no_oracle = 0

        for q in questions:
            pool = units_of(q)
            wanted = v7gate.value_tokens(q["gold_current"])
            oracle_indices = {u.index for u in pool
                              if u.revision == "after"
                              and wanted <= v7gate.value_tokens(u.text)}
            if not oracle_indices:
                skipped_no_oracle += 1
                continue
            evaluated += 1

            local_model = model
            if args.development_dry_run:
                local_model = arms.ExtractiveDevelopmentModel(
                    lambda _question, q=q: [q["gold_current"], q["gold_as_of_before"]])
            query = q["query_current"]

            for arm in arms.ARMS:
                fn = arms.ADAPTERS[arm]
                started = time.perf_counter()
                try:
                    evidence = (fn(pool, query, oracle_indices, as_of=None)
                                if arm == "TAVONEL" else fn(pool, query, oracle_indices))
                except arms.RawContextOverflow as overflow:
                    raw_overflow.append({"question_id": q["question_id"],
                                         "subject": q["subject"], "stage": "budget",
                                         "reason": str(overflow)})
                    outcomes[arm].append(scoring.score_answer(
                        response={"answer": None, "abstained": True},
                        gold_current=q["gold_current"],
                        gold_as_of_before=q["gold_as_of_before"], answerable=True,
                        cited_revision=None, oracle_revision="after"))
                    budget[arm].append({"source_tokens": 0, "truncated": False,
                                        "units_available": len(pool),
                                        "units_omitted": len(pool),
                                        "oracle_omitted_by_truncation": False,
                                        "context_utilization": 0.0,
                                        "raw_context_overflow": True})
                    elapsed = (time.perf_counter() - started) * 1000
                    latency_ms[arm].append(elapsed)
                    wall[arm] += elapsed / 1000
                    continue

                try:
                    response = local_model.answer(query, evidence.as_context())
                except Exception as error:
                    name = type(error).__name__
                    if name == "ContextOverflow":
                        # The served window refused the prompt. A measured fact
                        # about this run, recorded, never truncated away.
                        raw_overflow.append({"question_id": q["question_id"],
                                             "subject": q["subject"], "stage": "serving",
                                             "reason": str(error)[:500]})
                        outcomes[arm].append(scoring.score_answer(
                            response={"answer": None, "abstained": True},
                            gold_current=q["gold_current"],
                            gold_as_of_before=q["gold_as_of_before"], answerable=True,
                            cited_revision=None, oracle_revision="after"))
                        budget[arm].append({
                            "source_tokens": evidence.source_tokens, "truncated": False,
                            "units_available": evidence.units_available,
                            "units_omitted": evidence.units_omitted,
                            "oracle_omitted_by_truncation": False,
                            "context_utilization": evidence.context_utilization,
                            "raw_context_overflow": True})
                        elapsed = (time.perf_counter() - started) * 1000
                        latency_ms[arm].append(elapsed)
                        wall[arm] += elapsed / 1000
                        continue
                    # Anything else is a serving failure and must not be scored as
                    # an abstention: that would report an outage as a finding.
                    raise

                elapsed = (time.perf_counter() - started) * 1000
                latency_ms[arm].append(elapsed)
                wall[arm] += elapsed / 1000
                usage[arm]["calls"] += 1
                usage[arm]["prompt_tokens"] += int(response.get("prompt_tokens") or 0)
                usage[arm]["completion_tokens"] += int(
                    response.get("completion_tokens") or 0)

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
                    "source_tokens": evidence.source_tokens,
                    "truncated": evidence.truncated,
                    "units_available": evidence.units_available,
                    "units_omitted": evidence.units_omitted,
                    "oracle_omitted_by_truncation": evidence.oracle_omitted_by_truncation,
                    "context_utilization": evidence.context_utilization,
                    "raw_context_overflow": False})
                top = evidence.units[0] if evidence.units else None
                if top is not None:
                    key = ("correct_revision_top_1" if top.revision == "after"
                           else "wrong_revision_top_1")
                    hard_negative[arm][key] += 1
                if cited == "before":
                    hard_negative[arm]["answer_from_stale_evidence"] += 1

        if not evaluated:
            return {"cohort": label, "evaluated": 0,
                    "state": "NO_EVALUABLE_QUESTIONS",
                    "questions_skipped_no_locatable_oracle": skipped_no_oracle}

        def rates(arm: str) -> dict[str, float]:
            rows = outcomes[arm]
            n = len(rows)
            return {field: round(sum(1 for r in rows if getattr(r, field)) / n, 4)
                    for field in ("answer_correct", "evidence_correct",
                                  "right_answer_stale_evidence", "temporal_correct",
                                  "stale_answer", "provenance_localized",
                                  "unsupported_assertion", "abstained",
                                  "abstention_appropriate")}

        def cost(arm: str) -> float | None:
            if not args.pod_cost_per_hour_usd:
                return None
            return round(wall[arm] / 3600.0 * args.pod_cost_per_hour_usd, 6)

        def budget_summary(arm: str) -> dict[str, Any]:
            rows = budget[arm]
            n = len(rows)
            return {
                "median_source_tokens": round(
                    stats.median(r["source_tokens"] for r in rows), 1),
                "max_source_tokens": max(r["source_tokens"] for r in rows),
                "truncation_rate": round(sum(1 for r in rows if r["truncated"]) / n, 4),
                "oracle_omitted_by_truncation_rate": round(
                    sum(1 for r in rows if r["oracle_omitted_by_truncation"]) / n, 4),
                "median_context_utilization": round(
                    stats.median(r["context_utilization"] for r in rows), 4),
                "raw_context_overflow_count": sum(1 for r in rows
                                                  if r.get("raw_context_overflow")),
                "median_latency_ms": round(stats.median(latency_ms[arm]), 3),
                "total_wall_seconds": round(wall[arm], 3),
                "prompt_tokens": usage[arm]["prompt_tokens"],
                "completion_tokens": usage[arm]["completion_tokens"],
                "inference_cost_usd": cost(arm),
                "inference_cost_basis": (
                    "arm wall-clock share of the attested pod's hourly price"
                    if args.pod_cost_per_hour_usd else
                    "not measured: no pod price was supplied"),
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
            field: scoring.paired_comparison("TAVONEL", "BASIC_RAG",
                                             vector("TAVONEL", field),
                                             vector("BASIC_RAG", field))
            for field in ("stale_answer", "temporal_correct", "evidence_correct",
                          "provenance_localized", "unsupported_assertion",
                          "abstention_appropriate", "right_answer_stale_evidence")
        }
        return {
            "cohort": label,
            "evaluated": evaluated,
            "questions_skipped_no_locatable_oracle": skipped_no_oracle,
            "rates": {a: rates(a) for a in arms.ARMS},
            "budget": {a: budget_summary(a) for a in arms.ARMS},
            "hard_negative": hard_negative,
            "raw_context_overflow": raw_overflow,
            "comparisons": comparisons,
            "secondary_TAVONEL_vs_BASIC_RAG": secondary,
            "secondary_holm": scoring.holm(
                {k: v["mcnemar_exact_p"] for k, v in secondary.items()}),
        }

    started_at = datetime.now(UTC)
    primary_result = run_cohort(primary, "revision_sensitive")
    control_result = run_cohort(controls, "simple_retrieval_control") if controls else {
        "cohort": "simple_retrieval_control", "evaluated": 0,
        "state": "NO_CONTROL_QUESTIONS_IN_SET"}

    shared = {
        "model_identity": model_identity,
        "decoding": decoding,
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

    run_class = "DEVELOPMENT_ONLY" if args.development_dry_run else "HOLDOUT_CONFIRMATORY"
    receipt: dict[str, Any] = {
        "schema": "tavonel.w6-v8-confirmatory-arm-run.v1",
        "experiment": "H1-W6-SAME-INTELLIGENCE-01",
        "generated_at": datetime.now(UTC).isoformat(),
        "started_at": started_at.isoformat(),
        "protocol": PROTOCOL.name,
        "protocol_sha256": file_sha256(PROTOCOL),
        "run_class": run_class,
        "run_class_note": (
            "the extractive stub performs no inference; this output verifies the harness "
            "and is never an endpoint" if args.development_dry_run else
            "the attested frozen model answered every question; this is the W6 endpoint"),
        "config_freeze_sha256": (freeze or {}).get("receipt_sha256"),
        "question_set": args.question_set.name,
        "question_set_sha256": qs.get("receipt_sha256"),
        "question_set_run_class": qs.get("run_class"),
        "source_hashes": {name: file_sha256(HERE / name) for name in
                          ("arms_v8.py", "scoring_v8.py", "build_question_set_v8.py",
                           "taint_gate_v8.py", "residual_overlap_v8.py",
                           "entity_conditioned_gate_v8.py", "vllm_model_v8.py",
                           "run_arms_holdout_v8.py")},
        "shared_configuration": shared,
        "fairness_contract": fairness,
        "controls": {"fairness": fairness_ctl, "scoring": scoring_ctl,
                     "statistics": stats_ctl, "all_separate": controls_separate},
        "primary": primary_result,
        "control_cohort": control_result,
        "control_cohort_meaning": (
            "attributes whose value did not change between the two revisions. An arm that "
            "wins the primary by always preferring the later revision shows no advantage "
            "here; a harness that has broken something does."
        ),
        "reporting_rule": "effect size, paired interval and discordant counts accompany "
                          "every p-value; no comparison is reported alone",
        "cost": {
            "pod_cost_per_hour_usd": args.pod_cost_per_hour_usd or None,
            "note": "arm cost is the arm's wall-clock share of the attested pod's price; "
                    "it excludes model download and server start-up, which are recorded "
                    "in the runtime qualification receipt",
        },
        "network_access": not args.development_dry_run,
    }
    if model is not None and hasattr(model, "usage_summary"):
        receipt["model_usage_total"] = model.usage_summary()
    receipt["receipt_sha256"] = canonical_sha256(receipt)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")

    print(f"run class : {run_class}")
    print(f"primary   : {primary_result.get('evaluated')} evaluated")
    for arm in arms.ARMS:
        rate = (primary_result.get("rates") or {}).get(arm, {})
        print(f"  {arm:<15} answer={rate.get('answer_correct')} "
              f"evidence={rate.get('evidence_correct')} "
              f"stale={rate.get('stale_answer')}")
    print(f"control   : {control_result.get('evaluated')} evaluated")
    print(f"controls separate: {controls_separate}")
    print(f"wrote {display(args.output)}")
    return 0 if controls_separate else 1


if __name__ == "__main__":
    raise SystemExit(main())
