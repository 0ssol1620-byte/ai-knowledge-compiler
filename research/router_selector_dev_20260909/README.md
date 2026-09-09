# Grouped document-selector development diagnostic — 2026-09-09

**Result: no demonstrated improvement. Do not promote this selector.**

This is a new, CPU-only experiment over the already-spent September Arena outputs. It is NOT a fresh holdout result, a benchmark publication, a model qualification or a test of the new text-region document executor.

## Question and fixed protocol

Can a shallow learned selector use only a primary parser's visible output and source-render measurements to decide when invoking one additional parser improves the inherited information-loss metric?

Primary: `ovisocr2`. Alternate: `paddleocr_vl_1_6`. Both are research candidates; these names do not change live routing.

The protocol was recorded before evaluator scores were opened: five grouped folds, maximum tree depth two, minimum leaf size 64, seven fixed candidate quantiles for training splits, 12 input features, seed 20260909 and 2,000 grouped bootstrap resamples. Each test fold is predicted only by a tree trained on the other folds. The training-selected constant is a separate control.

The group key is the source basename with the page suffix removed; exact duplicate source hashes are joined before folds are assigned. This controls page siblings and exact duplicates, but is NOT independently validated publisher-family separation or comprehensive near-duplicate exclusion. The corpus was already used in prior research and therefore cannot become a fresh confirmatory test by repartitioning it.

The policy module accepts only primary-output and source-render numeric features: presence, text/line size, table/formula markers, digits, replacements, duplicated lines, aspect ratio and low-resolution image statistics. It never receives alternate output, file paths, benchmark class labels or evaluator scores. The offline training/evaluation module is separate from the runtime policy and never imported by the live router.

## Exact observed results

All **1,651 source-manifest inputs** stay in the denominator, grouped into **1,443 groups**. Primary output missing: zero. Evaluator score missing: ten for each parser, charged loss 1.0 by the inherited convention and reported separately. These ten missing grades are not described as failed extraction.

Lower loss is better. This uses the older frozen OmniDoc composite, not a new full-spectrum document information-retention metric.

| Arm | Mean inherited loss |
|---|---:|
| Ovis fixed primary | 0.06159654398030075 |
| Paddle fixed alternate | 0.07411844545909123 |
| Training-selected constant | 0.06159654398030075 |
| Grouped out-of-fold selector | 0.061869939644809316 |
| Two-model Oracle, diagnostic only | 0.05448231155350548 |

The selector changed 72/1,651 decisions (4.36099%). It improved 26, harmed 34 and left 1,591 unchanged. Mean loss reduction versus primary was **-0.00027339566450856466**. The conditional grouped-bootstrap 95% interval was **[-0.0007741944079954228, +0.00012932541484353543]**.

The interval conditions on already-trained out-of-fold predictions; it does not include full training/model-selection uncertainty. Even on that narrower interpretation it does not demonstrate a positive gain.

Every unit first invokes the primary, and a switch invokes an additional parser. Therefore the invocation-count proxy is 1.04361 per input, not 1.0. This is NOT measured dollar cost, GPU time or service latency. Actual GPU cost, live latency and SCLR are explicitly null. No visual independent verifier or Native comparator is included in this experiment.

## Interpretation

Do not add this shallow switcher to customer processing. It spends additional invocations without a demonstrated reduction in the inherited loss. This does NOT prove that adaptive routing, different features, region recovery or independent evidence verification cannot work.

The actionable finding is narrower: simple primary-output/render features with this two-parser shallow learner are insufficient to justify promotion. Next development should prioritize source-grounded detection and selection signals, measured recovery correctness and the missing Native comparison, rather than deploy a switch merely because its code passes tests. Any new hypothesis must receive a new protocol/version; do not retune this run on its evaluation outcomes.

## Reproducibility and file boundaries

Two fixed-protocol runs produced identical out-of-fold prediction hashes and identical loss values. Initial run source bytes are preserved under `RUN_CODE` with hashes checked against its pre-evaluation freeze. The second run includes import/style cleanup only; no feature, depth, leaf, split, seed or threshold change was made after seeing results.

Run directories relative to the current isolated worktree:

- `.chatgpt2codex/selector-grouped-development-20260909/`
- `.chatgpt2codex/selector-grouped-development-20260909-reproduction/`

Each carries `FREEZE.json`, `VISIBLE_FEATURES.json`, `OOF_PREDICTIONS.json` and `RESULT.json`. Code, prior evaluator/binding files, source manifest and observed primary output hashes are recorded. Existing Arena output matrices and old research receipts are not changed.

The driver uses the prior `router-v2-replay` worktree read-only and its exact inherited score loaders. Full standalone redistribution is not claimed. A clean reproduction must provide those paths and the original stored Arena artifacts. The seven protocol tests cover runtime input isolation, grouping, learner determinism and interval arithmetic.

Example, from an environment with repository dependencies and `akc_cir` available:

```text
python research/router_selector_dev_20260909/evaluate.py --replay-root <existing-replay-worktree> --output <current-worktree>/.chatgpt2codex/<new-exclusive-directory>
```

The output must be a new directory within this worktree's scratch. The driver refuses overwriting evidence.

## Related primary research, not transferred results

- AdaParse, *An Adaptive Parallel PDF Parsing and Resource Scaling Engine* (2025): parser allocation combines data-driven quality preferences with resource orchestration. Its task, training and measurements differ from this diagnostic. https://arxiv.org/abs/2505.01435
- RouteLLM, *Learning to Route LLMs with Preference Data* (2024; revised 2025): illustrates learned routing between models under quality/cost tradeoffs. It is not evidence that a document parser preserves source facts, layout or citations. https://arxiv.org/abs/2406.18665

No result from these papers is claimed as TAVONEL performance. None substitutes for the source-grounding, model qualification, fresh holdout or customer-data gates in TAVONEL's own blueprint.
