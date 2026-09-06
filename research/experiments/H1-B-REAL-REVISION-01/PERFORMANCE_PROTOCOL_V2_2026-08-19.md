# Family B performance protocol v2 — frozen after attempt-1 scalability failure

Attempt 1 is preserved in `receipts/measured-performance-attempt1-incomplete-2026-08-19.json`.
It established two facts that must not be blended: (1) selective artifact rebuild can
be cheaper once a change set exists; (2) the current semantic identity/diff stage
can dominate and failed with `MemoryError` at 10k units. v2 therefore measures the
two stages separately instead of hiding the bottleneck.

## A. Full change-detection / identity scaling

Controlled documents with stable logical ids and exactly 1% semantic edits are run
through the production `diff_documents(..., level=SEMANTIC)` path at sizes
**100, 250, 500, 750, 1,000**. Each scale gets 1 warmup and 5 recorded runs; order
is ascending and all raw wall times are retained. This is descriptive scaling, not
a latency SLO. The already observed 10,000-unit `MemoryError` from attempt 1 is a
pinned limitation and is **not rerun** merely to fail again.

Report p50/p95 at each completed size and empirical log-log slope over median time.
No extrapolated 10k latency is called measured.

## B. Downstream selective recompilation scaling with a precomputed change set

This isolates the compiler stage after identity/change detection. At **1,000 and
10,000 units**, build deterministic SEMANTIC dependency graphs with one section
artifact per unit plus one document-index artifact. Exactly 1% of units are changed
under frozen seed `2026081909`; the `SemanticDiff` is constructed directly from
that already-known dirty set, so identity matching is intentionally outside this
stage.

Compare:
- full: rebuild and serialize all after-state artifacts;
- selective: production `plan_recompilation(PRECISE)` from the frozen dirty set,
  rebuild/serialize only `to_rebuild`, carry unchanged hashes, and verify the
  reconstructed map exactly equals an independent full oracle.

Use 3 warmups then 30 recorded trials/arm, alternating order. Report p50/p95 wall
time, actual JSONL bytes written, rebuild fraction, and Python `tracemalloc` peak.
The experimental full oracle used to score equivalence is prepared outside the
selective timer.

## Interpretation constraints

- Stage-B speedup is **not** an end-to-end ingest/update speedup claim.
- Stage-A 10k memory failure remains a current implementation limitation and must
  appear in paper threats/scalability discussion.
- Stage-B result is reportable only if every trial reconstructs the full oracle
  exactly with zero stale escape.
- Controlled graph distributions are not production workload distributions.
- GPU cost is `$0.00`; GPU does not solve Python identity/graph/hash scaling here.
- Protected Core is not modified for this performance experiment because the final
  fresh-seed B-EQUIV holdout has already been frozen and passed against current code.
