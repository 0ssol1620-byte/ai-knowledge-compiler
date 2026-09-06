# TAVONEL Public Document Parsing Model Arena — 2026-09-03

Campaign `TAVONEL-MODEL-ARENA-PUBLIC-20260903-V1`: one full pass of 12
candidates (11 open document parsers/VLMs on RunPod + Claude Opus 5 through the
Claude Code subscription surface) over ParseBench 2,078 + OmniDocBench 1,651 +
olmOCR-Bench 1,403 = 5,132 pages, followed by TAVONEL Recovery / Adaptive /
Opus-escalation replay on the frozen outputs.

Masterplan: `D:\TAVONEL_PUBLIC_DOC_PARSING_MODEL_ARENA_EXECUTION_MASTERPLAN_2026-09-03.md`.
Interfaces between lanes: `ARENA_CONTRACT.md`.

This is an independent experiment namespace (masterplan §2.5). It does not
read or modify the SFIR frozen state under `research/tavonel_eval_v2` or any
sealed evidence under `docs/evidence`.

## Inputs already on disk

| benchmark | staged PNG inputs | dataset revision | evaluator clone |
|---|---:|---|---|
| ParseBench | 2,078 `benchmark/datasets/staged-public-core/parsebench/inputs` | `2805a1d9…` | `benchmark/cache/parsebench` @ `1d460294` |
| OmniDocBench | 1,651 `…/omnidocbench/inputs` | `aa1ee96d…` | `benchmark/cache/omnidoc` @ `193627ae` |
| olmOCR-Bench | 1,403 `…/olmocr-bench/inputs` | `54a96a6f…` | `benchmark/cache/olmocr` @ `cfa88c1e` |

Ground truth stays under `benchmark/datasets/acquired/public-core` and the
evaluator clones. The inference plane references only the staged PNGs.

## Phases (masterplan §32)

0 Freeze → 1 Runtime qualification (canary) → 2 Full open-model run →
3 Opus subscription run → 4 Freeze outputs → 5 TAVONEL route freeze →
6 Selective real recovery → 7 Official scoring → 8 Analysis → 9 Cleanup →
10 Final report.

## Paid-action gate

Nothing in this tree spends money without `--execute`, and the controller
refuses a Full Run for a model whose canary has not passed. Provisioning GPU
pods, creating the R2 transport bucket and starting the Opus full run are
founder decisions recorded in `receipts/`.

## Commands

```
.venv/Scripts/python.exe -m pytest research/model_arena_20260903/tests -q
.venv/Scripts/python.exe -m ruff check research/model_arena_20260903
.venv/Scripts/python.exe -m mypy research/model_arena_20260903/arena
.venv/Scripts/python.exe -m arena.manifest build        # source_manifest.jsonl, campaign_manifest.json, canary_selection.json
.venv/Scripts/python.exe -m arena.registry resolve      # model_registry.json, evaluator_registry.json
.venv/Scripts/python.exe -m arena.controller preflight  # dry run
.venv/Scripts/python.exe -m arena.controller canary --model paddleocr_vl_1_6 --execute
.venv/Scripts/python.exe -m arena.opus canary
```

Run the `arena` module commands from the namespace root or with
`PYTHONPATH=research/model_arena_20260903`.
