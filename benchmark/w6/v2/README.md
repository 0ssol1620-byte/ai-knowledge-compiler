# W6 Benchmark v2 — protocol-valid pilot harness

Implements the adjudicated v2 protocol (`preregistration.yaml`, frozen before
results) at pilot scale: **Raw documents vs Basic RAG vs TAVONEL compiled
world** over an identical frozen question set and one pinned model.

## Layout

- `preregistration.yaml` — frozen manifest: sources, arms, rubric, decision rules
- `credentials.py` — labelled-file/env key loading (never logs secrets)
- `llm.py` — OpenRouter client: pin/fallback probe, retries, usage ledger
- `acquisition.py` — 30s per-fetch timeout, 20-min step budget, cache, failure ledger
- `retrieval.py` — deterministic hashed-BoW retrieval (RAG arm + world retrieval)
- `compile_world.py` — TAVONEL arm: typed elements w/ provenance (pilot-grade, DEVIATION-02)
- `questions.py` — QA generation -> questions.frozen.json before any arm runs
- `grading.py` — critical match + single judge call scoring all three arms
- `arms.py` — raw / rag / tavonel answer builders
- `run_pilot.py` — phase orchestrator
- `tests/` — offline unit tests (no network, no secrets)

## Run

```bash
python -m benchmark.w6.v2.run_pilot --worktree-root .                  # full pipeline
python -m benchmark.w6.v2.run_pilot --worktree-root . --skip-acquire   # warm cache only
```

Credentials: set `OPENROUTER_API_KEY`, or let the harness parse the line
labelled *Openrouter* in `D:/Github_API.txt`. The secret never appears in
stdout, logs, reports, or commits.

Results land in `benchmark/results/w6-v2-pilot/` (see SUMMARY.md there).

## Honesty contract

Failures, timeouts, deadline stops and inconclusive effect sizes are recorded
verbatim in the artifacts. A BLOCKED verdict with a cause diagnosis is a
legitimate outcome of this pilot; deleting evidence is not.
