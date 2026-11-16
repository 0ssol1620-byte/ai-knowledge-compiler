# U34 — temporal and dependency correction (F30-03, F30-04), 2026-11-16

Base `6b3a27bf`. Defect fix inside Protected Core (`akc_cir.temporal`, `akc_cir.dependency`); no rewrite, no signature change beyond one additive field.

## What was wrong

- **F30-03** `TemporalFact.known_at()` treated `recorded_at=None` as "recorded", so `as_of(known_at=…)` and `replay_context()` served a fact the system never timestamped as if it had been known at any past moment (forward leak). Latent: no service path calls `TemporalTimeline` yet; it is where the D14 temporal query would have gone live.
- **F30-04** `DependencyGraph.impact_of()` found only cycles that close on the BFS path that first reached them. `root->b, root->c, b->c, c->b` returned `cycles_detected == ()`. The affected set was always complete; only the cycle report (wire field `impact.cycles`, MCP `trace_impact.cycles_detected`, `rebuild_order`) under-reported.

## What changed

- `temporal.py`: `known_at()` requires `recorded_at is not None`. `AsOfAnswer.excluded_unrecorded` (additive, default `()`) lists such facts, kept apart from `excluded_unknown` (unknown validity); `describe()` mentions it; `replay_context()` carries it (filtered by `logical_ids`). Current mode (`known_at=None`) still serves the fact. `history()`, `contradictions()` take no system-time cutoff and are unchanged.
- `dependency.py`: BFS untouched (paths, depths, affected set identical). After it, an iterative Tarjan SCC over `seeds + affected`, using the same `_successors(…, as_of)` (so inert relations and edges not live at `as_of` are ignored; DEPENDS_ON/DERIVED_FROM upstream and SUPPORTS/CONSUMED_BY/EXPORTS_TO/INVALIDATES downstream all covered). For every member of an SCC of size > 1 that no reported cycle touches yet, the shortest closed walk through it (BFS inside the component over the same `_successors(…, as_of)`, sorted successors, members taken in sorted order) is appended. Every entry of `cycles_detected` is therefore a real edge walk. (The first round appended the sorted member list, which for 3+ nodes is usually not a walk: reviewer REJECTED it, fixed in the follow-up commit.) Existing entries and their order are kept.

The two proposed patches in `d00/_scratch/proposed` were read against the real code and applied as written; nothing in them was rejected.

## Tests

`tests/unit/test_f30_regressions.py` (new, 20 cases) and `TestTraceImpactSiblingCycle` in `packages/local-mcp/tests/test_read_surface.py`. Round 1 figures (superseded by Round 3 below): written first, 16 failed on the base; required suites 208 passed, 3 failed. The 3 failures are `test_stdio_roundtrip.py` (server subprocess closes stdout in this local env) and fail identically on the base. Callers (`test_p0_spine`, `test_recompilation_diagnostic`, `test_product_core_*`): 118 passed. `ruff check` clean and `mypy` clean on both modules.

## Shadow (Protected Core ladder, local only)

Script and output under `D:/CodexProjects/v34-lanes/receipts/u34-shadow/` (`shadow_plugin.py`, `shadow_*.json|txt`). Every `impact_of()` call made while running the existing fixtures was replayed on the base module.

| Fixture set | calls | affected/depth/path | truncated/unknown | cycles differ | added cycles | every added cycle is a real walk |
|---|---|---|---|---|---|---|
| product-core (`test_product_core_*`) | 1887 | identical | identical | 0 | 0 | yes (vacuous) |
| compiler-runtime (`test_p0_spine`, `test_knowledge_cicd_pipeline`, `test_recompilation`, absorption diagnostic) | 427 | identical | identical | 13 calls | 49 | yes |

Re-run after the follow-up fix. All 13 differences are additions (49 added cycles, each checked hop by hop against the live successor edges: all real walks; the first round's sorted-list version failed this for 36 of 287 in this fixture set per the reviewer): the compiler-runtime graph (claim CONSUMED_BY doc, doc INVALIDATES claim) holds loops the base missed (3-4 node components); no base cycle was removed or reordered. Only `affected_ids` is consumed there, so output is unchanged; only `plan.cycles_detected` grows. The product-core graph is acyclic in its fixtures, so its wire payload is unchanged.

## Still required

- Independent reviewer (separate agent, no implementation context); this note is author-side evidence.
- The wider D12 100-revision-pair equivalence (cold rebuild vs selective) is not provided by this change.
- A cyclic product-core graph would change `impact.cycles` bytes and the candidate digest; none exists in the corpus tried, so confirm on a recorded corpus before rollout.
- D12 should decide whether to expose a dedicated `cyclic_components` field instead of overloading the path tuple.

## Follow-up (reviewer blocker: fabricated hops)

Tests added: 3-node sibling SCC (`root->a,b,c; a->c, c->b, b->a`, expects `a -> c -> b -> a`), 300 seeded random graphs (every reported cycle is a closed walk over live edges; round 3: every non-trivial reached SCC has a reported cycle inside it), 50 seeded DAGs report none, and a local-mcp `trace_impact` regression that every printed hop exists. They failed on the first-round code (65 failures); round 3 re-ran them and they pass. The 3 `test_stdio_roundtrip.py` failures are unchanged and fail on the untouched base (environment).

## Round 3 - linear cycle reporting

Reviewer measurement (`review-U34b/perf.py`, one seeded random SUPPORTS graph): the follow-up ran one BFS per uncovered member of a cyclic component, O(U*(V+E)). 2,000 nodes / 10,000 edges: base 0.01 s, previous HEAD 1.01 s; 5,000 / 25,000: base 0.03 s, previous HEAD 6.57 s; `cycles_detected` grew 22 -> 1,968 and inflated the wire field `impact.cycles`.

Contract change (lead decision): `cycles_detected` now guarantees that every cyclic component among the reached nodes is represented by at least one real closed walk. It no longer guarantees that every member of a component lies on a reported cycle. After the lineage walk, each non-trivial component that no reported cycle touches gets exactly one cycle: the shortest closed walk through its first member in sorted order, one BFS restricted to that component. Components already touched by a lineage cycle get nothing. BFS, `affected`, depths, `via`, `truncated`, `unknown` and the order of the lineage cycles (a prefix of the output) are unchanged.

Measured after the change (same `perf.py`, one seed, this worktree vs base `6b3a27bf`):

| nodes / edges | base | round 3 | cycles_detected base / round 3 |
|---|---|---|---|
| 500 / 2,500 | 0.00 s | 0.00 s | 24 / 24 |
| 2,000 / 10,000 | 0.01 s | 0.02 s | 26 / 26 |
| 5,000 / 25,000 | 0.02 s | 0.06 s | 22 / 22 |

Tests: the SCC property is now "every non-trivial reached SCC has a reported cycle inside it"; a latency guard (2,000 / 10,000, median of 3 under 0.5 s, `len(cycles) <= lineage cycles + non-trivial components`, lineage cycles a prefix) was added. Receipts: `D:/CodexProjects/v34-lanes/receipts/u34-r3/`. Local author-side evidence only: no gate is marked passed, no public claim is made, and the independent re-review is still required.

Shadow re-run (round 3, same fixtures, `receipts/u34-r3/out/`): product-core 1,887 calls and compiler-runtime 427 calls, affected/depth/path, truncated and unknown identical to base, cycles identical on every call (0 added cycles; the earlier 49 additions came from covering every member and are gone). Property check on seeded random graphs and DAGs (`u34-r3/random_check.py`, contract-adjusted): 0 errors. Suites: f30 regressions 372 passed; temporal, dependency, recompilation, knowledge_cicd_pipeline, world_state, p0_spine, absorption diagnostic, local-mcp, product_core_*: 669 passed, 3 failed (`test_stdio_roundtrip.py`, same on base). ruff and mypy clean.
