# B-EQUIV under adversarial dependency graphs — and the reorder blind spot

`PATENT_FILING = NOT FILED`. `PAPER_SUBMISSION = NOT SUBMITTED`.

Receipt: `receipts/adversarial-graph-2026-08-19.json`
(seed `20260821`, 7 topologies × 7 shape classes × 60 cases = 2,940 runs).
External GPU cost: **$0.00**.

---

## 1. Why

Every earlier measurement used one topology: artifacts depending directly on
units, one hop, no cycles. Equivalence holding there says little about
equivalence holding where dependencies chain, loop, or mix channels.

The primary criterion is **equivalence**, not safety. A case where the planner
leaves an artifact stale and the gate blocks the run is an equivalence *failure
that was contained* — it is not a pass and is not counted as one. That
conflation is precisely how a weak B-EQUIV would be made to look strong.

## 2. What it found first: a pure reorder was invisible

Before any fix, `unit_reorder` was **0/60 equivalent in every topology**.

`DocumentShape` compared heading set, block count, table shapes and figure refs
— all order-insensitive. A revision with the same units, the same text, the same
headings and the same block count in a different order produced an *identical*
shape, **no changes at all**, and an empty structural scope. Nothing propagated,
and every artifact whose bytes depend on order was carried forward stale.

This is a real gap in `akc_cir.semantic_diff`, not a harness artifact; it was
confirmed by dumping the diff before touching anything.

`DocumentShape.unit_order` now carries the reading order as a sequence, and a
permutation with unchanged membership is reported as a structural change.
Insertions and removals were already reported at unit level, so the pure
permutation was the case that passed silently.

**It defaults to empty, so no existing caller changes behaviour.** An adapter
that does not declare an order is compared exactly as before — and keeps the
blind spot. That is a stated limitation of not declaring order, not a silent
change for callers who never had it.

## 3. Result after the fix

| topology | cases | equivalent | escape cases | blocked | **stale promoted** |
|---|---|---|---|---|---|
| direct | 420 | **420** | 0 | 0 | **0** |
| multi_hop (3 deep) | 420 | **420** | 0 | 0 | **0** |
| artifact → artifact | 420 | **420** | 0 | 0 | **0** |
| **cyclic** | 420 | **420** | 0 | 0 | **0** |
| mixed_channel | 420 | **420** | 0 | 0 | **0** |
| partial_edges | 420 | 396 | 24 | 24 | **0** |
| stale_declaration | 420 | 401 | 19 | 19 | **0** |

Failing cells, exhaustively: `partial_edges/text_only` (36/60) and
`stale_declaration/text_only` (41/60).

## 4. Reading this honestly

**Equivalence holds under every honest-declaration topology tested**, including
cycles and three-deep chains, across all seven shape-change classes — block
count, heading hierarchy, table shape, figure refs, reordering, and an ambiguous
identity firing together with a shape change.

**It fails exactly where the declaration is wrong**, and only there. That is not
equivalence being fragile; it is a planner being told the wrong graph. The
distinction matters for what may be claimed: selective recompilation is
equivalent to a full rebuild *given a correct dependency declaration*, and the
qualifier is load-bearing rather than decorative.

**Stale-promoted is 0 in all 2,940 runs**, including both broken-declaration
topologies — consistent with the declaration-mutation result, by the same
mechanism: the fingerprint comes from the build record, not the declaration.

## 5. What this does not show

- Generated graphs. Real adapters may have topologies not in this set.
- Seven topologies, not all of them: diamonds with conflicting channels,
  cross-document dependencies and very deep chains are untested.
- **Development data.** This suite found the reorder gap and the fix was made
  against it. A fresh-seed untouched holdout is still owed and is reserved for
  after the remaining work, run once.
- Nothing about compute or latency. Artifact counts are not compute.
