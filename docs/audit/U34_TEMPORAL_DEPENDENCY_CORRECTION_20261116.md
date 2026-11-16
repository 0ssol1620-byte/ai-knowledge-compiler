# U34 — temporal and dependency correction (F30-03, F30-04), 2026-11-16

Base `6b3a27bf`. Defect fix inside Protected Core (`akc_cir.temporal`, `akc_cir.dependency`); no rewrite, no signature change beyond one additive field.

## What was wrong

- **F30-03** `TemporalFact.known_at()` treated `recorded_at=None` as "recorded", so `as_of(known_at=…)` and `replay_context()` served a fact the system never timestamped as if it had been known at any past moment (forward leak). Latent: no service path calls `TemporalTimeline` yet; it is where the D14 temporal query would have gone live.
- **F30-04** `DependencyGraph.impact_of()` found only cycles that close on the BFS path that first reached them. `root->b, root->c, b->c, c->b` returned `cycles_detected == ()`. The affected set was always complete; only the cycle report (wire field `impact.cycles`, MCP `trace_impact.cycles_detected`, `rebuild_order`) under-reported.

## What changed

- `temporal.py`: `known_at()` requires `recorded_at is not None`. `AsOfAnswer.excluded_unrecorded` (additive, default `()`) lists such facts, kept apart from `excluded_unknown` (unknown validity); `describe()` mentions it; `replay_context()` carries it (filtered by `logical_ids`). Current mode (`known_at=None`) still serves the fact. `history()`, `contradictions()` take no system-time cutoff and are unchanged.
- `dependency.py`: BFS untouched (paths, depths, affected set identical). After it, an iterative Tarjan SCC over `seeds + affected`, using the same `_successors(…, as_of)` (so inert relations and edges not live at `as_of` are ignored; DEPENDS_ON/DERIVED_FROM upstream and SUPPORTS/CONSUMED_BY/EXPORTS_TO/INVALIDATES downstream all covered). Any SCC of size > 1 not already covered by a lineage cycle is appended as `(*sorted(members), first)`. Existing entries and their order are kept.

The two proposed patches in `d00/_scratch/proposed` were read against the real code and applied as written; nothing in them was rejected.

## Tests

`tests/unit/test_f30_regressions.py` (new, 20 cases) and `TestTraceImpactSiblingCycle` in `packages/local-mcp/tests/test_read_surface.py`. Written first: 16 failed on the base. After the fix all pass. Required suites: 208 passed, 3 failed. The 3 failures are `test_stdio_roundtrip.py` (server subprocess closes stdout in this local env) and fail identically on the base. Callers (`test_p0_spine`, `test_recompilation_diagnostic`, `test_product_core_*`): 118 passed. `ruff check` clean and `mypy` clean on both modules.

## Shadow (Protected Core ladder, local only)

Script and output under `D:/CodexProjects/v34-lanes/receipts/u34-shadow/` (`shadow_plugin.py`, `shadow_*.json|txt`). Every `impact_of()` call made while running the existing fixtures was replayed on the base module.

| Fixture set | calls | affected/depth/path | truncated/unknown | cycles differ |
|---|---|---|---|---|
| product-core (`test_product_core_*`) | 1887 | identical | identical | 0 |
| compiler-runtime (`test_p0_spine`, `test_knowledge_cicd_pipeline`, `test_recompilation`, absorption diagnostic) | 427 | identical | identical | 13 calls |

All 13 differences are additions: the compiler-runtime graph (claim CONSUMED_BY doc, doc INVALIDATES claim) holds loops the base missed (3-4 node components); no base cycle was removed or reordered. Only `affected_ids` is consumed there, so output is unchanged; only `plan.cycles_detected` grows. The product-core graph is acyclic in its fixtures, so its wire payload is unchanged.

## Still required

- Independent reviewer (separate agent, no implementation context); this note is author-side evidence.
- The wider D12 100-revision-pair equivalence (cold rebuild vs selective) is not provided by this change.
- A cyclic product-core graph would change `impact.cycles` bytes and the candidate digest; none exists in the corpus tried, so confirm on a recorded corpus before rollout.
- D12 should decide whether to expose a dedicated `cyclic_components` field instead of overloading the path tuple.
