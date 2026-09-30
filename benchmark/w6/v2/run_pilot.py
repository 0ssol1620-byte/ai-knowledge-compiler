"""W6 v2 pilot orchestrator.

Phases (each gated on the previous, all failures ledgered):
  acquire   -> acquisition-report.json + cache/
  freeze    -> questions.frozen.json (+ sha256 into run-manifest)
  compile   -> compiled-world.json
  answer    -> runs/{raw,rag,tavonel}.jsonl
  grade     -> evaluation.json
  report    -> SUMMARY.md

Usage:
  python -m benchmark.w6.v2.run_pilot --worktree-root
D:/CodexProjects/ai-knowledge-compiler-w6v2 [--skip-acquire]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import yaml

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from benchmark.w6.v2 import arms as arms_mod
from benchmark.w6.v2 import grading
from benchmark.w6.v2 import questions as questions_mod
from benchmark.w6.v2.acquisition import acquire_corpus
from benchmark.w6.v2.compile_world import WorldRetriever, compile_world, save_world
from benchmark.w6.v2.credentials import load_openrouter_key, redact
from benchmark.w6.v2.llm import OpenRouterClient
from benchmark.w6.v2.retrieval import RagIndex


def load_preregistration(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def append_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worktree-root", type=Path, required=True)
    parser.add_argument("--skip-acquire", action="store_true", help="reuse existing cache only")
    args = parser.parse_args(argv)

    root = args.worktree_root.resolve()
    prereg_path = root / "benchmark/w6/v2/preregistration.yaml"
    results_dir = root / "benchmark/results/w6-v2-pilot"
    runs_dir = results_dir / "runs"
    cache_dir = results_dir / "cache"
    results_dir.mkdir(parents=True, exist_ok=True)
    runs_dir.mkdir(parents=True, exist_ok=True)

    prereg = load_preregistration(prereg_path)
    registry = prereg["source_registry"]
    titles = prereg["frozen_source_list_head_60"]["items"][: int(registry["pilot_size"])]

    # ---- phase 0: freeze the preregistration snapshot BEFORE anything else --
    snapshot_path = results_dir / "preregistration.snapshot.json"
    write_json(
        snapshot_path,
        {
            "preregistration_sha256": sha256_file(prereg_path),
            "snapshot_taken_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "pilot_titles": titles,
        },
    )
    print(f"[freeze] preregistration sha256={sha256_file(prereg_path)[:16]}... snapshot written")

    # ---- phase 1: acquisition --------------------------------------------
    if not args.skip_acquire:
        report = acquire_corpus(
            titles=titles,
            endpoints=list(registry["endpoints"]),
            cache_dir=cache_dir,
            per_fetch_timeout_seconds=float(registry["per_fetch_timeout_seconds"]),
            max_attempts_per_item=int(registry["max_attempts_per_item"]),
            retry_backoff_seconds=tuple(registry["retry_backoff_seconds"]),
            phase_deadline_seconds=float(registry["phase_deadline_seconds"]),
            usable_document_min_chars=int(registry["usable_document_min_chars"]),
        )
        write_json(results_dir / "acquisition-report.json", report.to_dict())
        print(f"[acquire] counts={report.summary_counts()} usable={len(report.usable_documents)}")
    else:
        print("[acquire] skipped (--skip-acquire); reusing cache")

    # Rebuild documents from cache in frozen order (source ids must be stable).
    documents: dict[str, dict] = {}
    index = 0
    for title in titles:
        cache_path = (
            cache_dir
            / f"{hashlib.sha1(title.encode('utf-8'), usedforsecurity=False).hexdigest()}.json"
        )
        if not cache_path.exists():
            continue
        entry = json.loads(cache_path.read_text(encoding="utf-8"))
        source_id = f"src-{index:03d}"
        documents[source_id] = {
            "source_id": source_id,
            "title": title,
            "url": entry.get("url", ""),
            "text": entry["text"],
        }
        index += 1

    usable = len(documents)
    blocked = usable < int(registry["blocked_threshold_usable_documents"])
    if blocked:
        print(
            f"[gate] BLOCKED_ACQUISITION candidate: "
            f"usable={usable} < {registry['blocked_threshold_usable_documents']}"
        )
    else:
        print(f"[acquire] usable documents rebuilt from cache: {usable}")

    run_manifest: dict = {"usable_documents": usable, "blocked_acquisition": blocked}

    # ---- blocked short-circuit: diagnosis report without touching credentials
    if blocked:
        verdict = "BLOCKED_ACQUISITION"
        summary_payload = {
            "verdict": verdict,
            "usable_documents": usable,
            "diagnosis": "acquisition yielded fewer usable documents "
            "than the preregistered gate; see acquisition-report.json item ledger",
        }
        write_json(
            results_dir / "evaluation.json", {"verdict": verdict, "metrics": {}, "grades": []}
        )
        write_summary_md(
            results_dir / "SUMMARY.md",
            prereg,
            run_manifest | summary_payload,
            metrics={},
            pairwise=[],
        )
        print(f"[done] verdict={verdict}")
        return 0

    # ---- model probe -------------------------------------------------------
    import os

    model_spec = prereg["model"]
    client, pinned_model = OpenRouterClient.probe(
        primary=model_spec["primary"],
        fallback_order=list(model_spec["fallback_order"]),
        environment=dict(os.environ),
        credential_file=None,
    )
    key_preview = redact(load_openrouter_key())
    print(f"[model] pinned={pinned_model} key={key_preview}")
    run_manifest["pinned_model"] = pinned_model

    # ---- phase 2: question generation + freeze -----------------------------
    question_rows: list[dict] = []
    question_failures: list[dict] = []
    for source_id in sorted(documents):
        document = documents[source_id]
        try:
            question_rows.append(
                questions_mod.generate_question(
                    client, source_id=source_id, title=document["title"], text=document["text"]
                )
            )
        except Exception as exc:
            question_failures.append({"source_id": source_id, "error_class": type(exc).__name__})
    frozen_hash = questions_mod.freeze_questions(
        [
            {
                **row,
                "source_title": documents[row["source_id"]]["title"],
            }
            for row in question_rows
        ],
        results_dir / "questions.frozen.json",
    )
    print(
        f"[questions] frozen n={len(question_rows)} "
        f"failures={len(question_failures)} sha256={frozen_hash[:16]}..."
    )
    run_manifest["question_count"] = len(question_rows)
    run_manifest["question_failures"] = len(question_failures)
    run_manifest["questions_frozen_sha256"] = frozen_hash
    write_json(results_dir / "run-manifest.json", run_manifest)

    # ---- phase 3a: TAVONEL compilation -------------------------------------
    world = compile_world(client, documents)
    save_world(world, results_dir / "compiled-world.json")
    print(f"[compile] elements={len(world.elements)} doc_failures={len(world.compile_failures)}")
    run_manifest["world_elements"] = len(world.elements)
    run_manifest["world_compile_failures"] = world.compile_failures
    write_json(results_dir / "run-manifest.json", run_manifest)

    rag_index = RagIndex(
        documents,
        chunk_chars=int(prereg["arms"]["rag"]["chunk_chars"]),
        overlap_chars=int(prereg["arms"]["rag"]["chunk_overlap_chars"]),
    )
    world_retriever = WorldRetriever(world, documents)
    print(f"[index] rag chunks={rag_index.chunk_count}")

    # ---- phase 3b: answer all three arms ------------------------------------
    arm_rows = {
        "raw": arms_mod.run_raw_arm(client, documents, question_rows),
        "rag": arms_mod.run_rag_arm(client, rag_index, documents, question_rows),
        "tavonel": arms_mod.run_tavonel_arm(client, world_retriever, question_rows),
    }
    for arm, rows in arm_rows.items():
        path = runs_dir / f"{arm}.jsonl"
        path.unlink(missing_ok=True)
        append_jsonl(path, rows)
        failure_rate = sum(1 for row in rows if row["api_failure"]) / max(1, len(rows))
        print(f"[answer:{arm}] n={len(rows)} api_failure_rate={failure_rate:.3f}")

    # ---- phase 4: grading ---------------------------------------------------
    grades, metrics = grading.grade_run(client, question_items=question_rows, runs=arm_rows)
    pairwise = pairwise_table(metrics)
    verdict = decide_verdict(metrics, pairwise)
    evaluation_payload = {
        "verdict": verdict,
        "pinned_model": pinned_model,
        "question_count": len(question_rows),
        "metrics": metrics,
        "pairwise_differences": pairwise,
        "grades": grades,
        "llm_usage": client.usage.as_dict(),
    }
    write_json(results_dir / "evaluation.json", evaluation_payload)
    write_summary_md(
        results_dir / "SUMMARY.md", prereg, run_manifest | {"verdict": verdict}, metrics, pairwise
    )
    print(f"[done] verdict={verdict}")
    return 0


def pairwise_table(metrics: dict) -> list[dict]:
    names = ["raw", "rag", "tavonel"]
    table = []
    for a in names:
        for b in names:
            if a == b:
                continue
            diff = round(metrics[a]["accuracy"] - metrics[b]["accuracy"], 4)
            table.append(
                {"a": a, "b": b, "accuracy_diff": diff, "directional_signal": abs(diff) >= 0.10}
            )
    return table


def decide_verdict(metrics: dict, pairwise: list[dict]) -> str:
    for arm in ("raw", "rag", "tavonel"):
        if metrics[arm]["api_failure_rate"] > 0.20:
            return "INVALID_EXECUTION"

    def acc(name):
        return metrics[name]["accuracy"]

    tav_beats_both = acc("tavonel") - max(acc("raw"), acc("rag")) >= 0.10
    rag_leads = acc("rag") - max(acc("raw"), acc("tavonel")) >= 0.10
    raw_leads = acc("raw") - max(acc("rag"), acc("tavonel")) >= 0.10
    if tav_beats_both:
        return "TAVONEL_POSITIVE_SIGNAL"
    if rag_leads:
        return "RAG_LEADS_SIGNAL"
    if raw_leads:
        return "RAW_LEADS_SIGNAL"
    return "INCONCLUSIVE_PILOT"


def write_summary_md(
    path: Path, prereg: dict, manifest: dict, metrics: dict, pairwise: list[dict]
) -> None:
    lines: list[str] = []
    lines.append("# W6 v2 pilot — Raw vs Basic RAG vs TAVONEL compiled world\n")
    lines.append("## Evidence header\n")
    lines.append(
        f"- experiment_id: {prereg['experiment_id']} (protocol v{prereg['protocol_version']})"
    )
    lines.append(f"- branch: {prereg['worktree_branch']} cut from {prereg['git_commit_at_freeze']}")
    lines.append(
        "- preregistration sha256: see "
        "preregistration.snapshot.json (frozen before any result existed)"
    )
    lines.append(
        f"- pinned model: `{manifest.get('pinned_model', 'n/a')}` "
        f"(temperature 0, single-model rule)"
    )
    lines.append(f"- verdict: **{manifest.get('verdict', 'PENDING')}**")
    lines.append("- role: PILOT ONLY — harness validation and directional signal only\n")
    lines.append("## Executive status\n")
    lines.append("| Area | Status | Evidence boundary |")
    lines.append("| --- | --- | --- |")
    lines.append(
        "| Preregistration freeze | DONE | manifest + snapshot hash written before acquisition |"
    )
    blocked_now = manifest.get("verdict") == "BLOCKED_ACQUISITION"
    question_status = "DONE" if manifest.get("question_count") else "NOT REACHED"
    lines.append(
        f"| Acquisition | {'BLOCKED' if blocked_now else 'DONE'} "
        f"| acquisition-report.json item ledger; no silent drops |"
    )
    lines.append(
        f"| Question freeze | {question_status} | questions.frozen.json hash in run-manifest.json |"
    )
    lines.append(
        f"| Arm execution | {'DONE' if metrics else 'NOT REACHED'} "
        f"| runs/*.jsonl include per-row api_failure flags |"
    )
    lines.append(
        f"| Grading | {'DONE' if metrics else 'NOT REACHED'} "
        f"| evaluation.json per-question grades + Wilson CIs |"
    )
    lines.append("")
    if metrics:
        lines.append("## Metrics (primary: accuracy over identical frozen questions)\n")
        lines.append(
            "| arm | accuracy | Wilson 95% CI | critical-only "
            "| provenance hit | mean latency s | api-failure rate |"
        )
        lines.append("| --- | --- | --- | --- | --- | --- | --- |")
        for arm in ("raw", "rag", "tavonel"):
            m = metrics[arm]
            ci = m["wilson_ci_accuracy"]
            prov = m["provenance_hit_rate"]
            lines.append(
                f"| {arm} | {m['accuracy']:.3f} | [{ci[0]:.3f}, {ci[1]:.3f}] "
                f"| {m['critical_only_rate']:.3f} | {'n/a' if prov is None else f'{prov:.3f}'} "
                f"| {m['mean_latency_seconds']} | {m['api_failure_rate']:.3f} |"
            )
        lines.append("")
        lines.append("## Pairwise accuracy differences\n")
        lines.append("| a | b | diff | directional signal (>=0.10) |")
        lines.append("| --- | --- | --- | --- |")
        for row in pairwise:
            lines.append(
                f"| {row['a']} | {row['b']} | {row['accuracy_diff']:+.3f} "
                f"| {row['directional_signal']} |"
            )
        lines.append("")
        lines.append(
            "At pilot sample size these intervals are wide; per the frozen decision rules any "
            "difference below 10pp is recorded as inconclusive. No significance claim is made.\n"
        )
    lines.append("## Deviations and blockers (recorded verbatim)\n")
    for deviation in prereg.get("deviations", []):
        lines.append(f"- **{deviation['id']}**: {deviation['statement'].strip()}")
    lines.append(
        "- **DEVIATION-03**: transport fixes (descriptive User-Agent header plus extract-path "
        "parsing, applied after the first BLOCKED_ACQUISITION; attempt-1 ledger preserved as "
        "acquisition-report.attempt1-blocked.json, 60/60 http_403 from Wikimedia's default-UA "
        "policy). Questions, evaluation criteria and success judgment rules are unchanged, so "
        "preregistration validity holds. Protocol unchanged."
    )
    lines.append(
        "- **BLOCKER-GIT-WORKTREE**: worktree checkout could not complete on this host "
        "(per-file multi-second disk; interrupted resets "
        "left the index partial). Harness and results live as "
        "untracked files under benchmark/w6/v2/ and "
        "benchmark/results/w6-v2-pilot/, ready to commit once the "
        "worktree index is repaired with a single `git reset --hard HEAD`."
    )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
