# SEC Source-Bound Target-Cell Development Result

Status: **POSITIVE COMPONENT SIGNAL · NEGATIVE ROUTER SUPERIORITY · DEVELOPMENT ONLY**

## Change under test

The earlier SEC holdout sent a complete table row to each model. Its Router
compared complete row token multisets and produced 11 refusals, ten of which
were avoidable. This follow-up used the already-bound `target_bbox1000` to crop
the exact fact area with fixed padding, then upscaled the crop without adding a
fact value or label to the runtime manifest.

This crop and its policy were designed after the source truth opened. It is a
spent-development experiment and cannot serve as a fresh confirmatory result.

## Execution

- 24 source-bound target-cell crops from the same six SEC filings.
- MinerU, Paddle, and Ovis ran on all 24 inputs: 72 calls total.
- Every worker response was bound to the input hash, model revision, runtime
  bundle, and benchmark id.
- All models returned 24 transport successes. Semantic and empty-token output
  remained a detected failure.
- The three pods were drained and deleted. A separate provider inventory found
  zero live pods.
- Reconciled RunPod cost: USD 0.372642.
- Two scoring runs were byte-identical.
- 241 Router package, unit, and Apple 290-page public-corpus tests passed.
- 61 replay and Oracle-math tests passed.
- Ruff passed for the complete region-recovery research directory; strict mypy
  passed for the five execution, routing, and scoring modules.

## Result

| System | Signed fact retention | SCLR | Detected/unresolved | Warm USD/1k | p50 | p95 |
|---|---:|---:|---:|---:|---:|---:|
| Ovis fixed | 100.0% | 0.0% | 0.0% | 0.019725 | 156 ms | 280 ms |
| MinerU fixed | 95.8% | 0.0% | 4.2% | 0.096367 | 765 ms | 842 ms |
| Paddle fixed | 79.2% | 0.0% | 20.8% | 0.121518 | 669 ms | 696 ms |
| Target-cell Router | 95.8% | 0.0% | 4.2% | 0.161013 | 678 ms | 1,447 ms |

The Router starts Ovis and Paddle in parallel. It accepts only an identical,
non-empty target-token multiset; otherwise it invokes MinerU and requires a
corroborated multiset. It invoked recovery on five regions and simulated 53
calls. One zero-valued region remained unresolved because both secondary
outputs were empty even though Ovis was correct.

Target-cell execution changes the component result materially: Ovis preserved
24/24 rendered values, signs, and percent markers. However, the adaptive policy
does not beat Ovis fixed on this set. It is slower, more expensive, and refuses
one case that Ovis gets right. No Router-superiority claim is supported.

## Engineering decision

Use this result to qualify Ovis as a **target-cell specialist candidate** and to
keep exact bbox-bound recovery in the execution planner. Do not make the current
three-model voting policy authoritative. The next Router must choose across
source classes, for example:

- authoritative native Inline XBRL for source facts;
- Ovis target-region recovery for visual-only critical cells;
- Paddle or MinerU only when a route-time risk or independent verifier justifies
  the additional call;
- unresolved when source identity, target alignment, sign, unit, or evidence
  binding is missing.

A new mixed-source holdout must be selected and frozen before opening truth. It
must include native structured sources, PDF tables, scans, layout-heavy pages,
Office/Korean cases, semantic empty outputs, and target-alignment failures. Only
that evaluation can test whether page/region routing beats the best fixed
specialist while preserving lower cost and latency.

Exact hashes and metrics are in `SEC_TARGET_CELL_RESULT_FREEZE.json`.
