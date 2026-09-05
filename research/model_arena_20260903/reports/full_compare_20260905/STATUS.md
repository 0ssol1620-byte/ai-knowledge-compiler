# Full campaign compare — 2026-09-05 (CORRECTED SCOPE)

Updated: **2026-09-05 18:23 KST**
Cloud cost: **$0** (local CPU only). Caps not raised. No GPU pods for scoring. Infinity **Pro** FOUNDER_EXCLUDED (no further Pro spend).

## FLASH OmniDoc STARTED + pod cleanup (2026-09-05 ~18:21 KST)
**Founder ask:** Flash inference DONE (5132 SUCCESS). Start OmniDoc full scoring for models still MISSING from `omnidoc_raw`; terminate idle flash pods.

### Flash prepare + score
- QA: PASS (1651/1651, 2 empty SUCCESS noted non-blocking)
- Prepare: `arena.scoring prepare --model infinity_parser2_flash --benchmark omnidoc --gt-path …/OmniDocBench.json` → **1651** md preds + `_prepare-receipt.json`
- Driver: `_priority_omnidoc_flash.py` (imports `_parallel_omnidoc.score_one`)
- Prefix: `md_infinity_parser2_flash` via `Path.absolute()` (not resolve)
- Workers: **2**
- Supervisor PID: **55832** (child 54992); `pdf_validation` live under `omnidoc_raw/infinity_parser2_flash/`
- Log: `priority_flash_omnidoc.log` / `.err.log`; receipt `priority_flash_launch.json`
- ETA: CPU saturated (pool 5 + opus/glm + flash) → **~2–3 h** wall for Flash OmniDoc 1651

### RunPod flash pod cleanup
- `flash_unsettled=0` (5132 SUCCESS across omnidoc/olmocr/parsebench)
- `RunPodV1Client.list_pods()` → **total_pods=0**, **flash_pods=0**
- Result: **nothing to terminate** (idle `arena-infinity-parser2-flash-*` already gone; billing already stopped)

### OmniDoc board (who’s done / inflight / missing)

| State | Models |
|---|---|
| **DONE** (run_summary rc=0) | `paddleocr_vl_1_6`, `deepseek_ocr2` |
| **INFLIGHT** (pdf_validation live; do NOT kill) | `hpd_parsing`, `mineru_pipeline`, `mineru_vlm`, `monkeyocrv2_b`, `ovisocr2`, `opus5_subscription`, `glm_ocr`, **`infinity_parser2_flash`** |
| **QUEUED** (pool `_parallel_omnidoc.py` ThreadPoolExecutor; start when slot frees) | `olmocr2`, `unlimited_ocr` |
| **MISSING from omnidoc_raw** (not started) | *(none — flash now inflight; olmocr2/unlimited queued)* |
| **EXCLUDED** | `infinity_parser2_pro` (FOUNDER_EXCLUDED) |

### Supervisors LIVE
- Pool: PID **23288** / **17688** `_parallel_omnidoc.py` (olmocr2+unlimited still queued behind current 5)
- Priority opus+glm: PID **22272** / **31832** `_priority_omnidoc_opus_glm.py`
- Priority flash: PID **55832** / **54992** `_priority_omnidoc_flash.py`

### Still missing after this wave
- Official metrics not yet harvested for: all INFLIGHT + QUEUED above
- After OmniDoc: olmOCR/ParseBench waves still TBD for flash / remaining models
- Pro stays off the main board

---

## Prior STATUS snapshot (retained)

# Full campaign compare — 2026-09-05 (CORRECTED SCOPE)

Updated: **2026-09-05 14:55 KST**
Cloud cost: **$0** (local CPU only). Caps not raised. No GPU pods. Infinity **Pro** FOUNDER_EXCLUDED (no further Pro spend).

## PRIORITY: Opus + GLM OmniDoc STARTED (2026-09-05 14:45 KST)
**Founder ask:** pull `opus5_subscription` + `glm_ocr` into full-page OmniDoc compare NOW (were only queued behind pool).

### How launched
- Driver: `_priority_omnidoc_opus_glm.py` (imports `_parallel_omnidoc.score_one`)
- Unique prefixes: `md_opus5_subscription`, `md_glm_ocr` (junctions; no shared `markdown_` clobber)
- Workers: **2** each (pool uses 3; CPU was 100% — added alongside, did **not** kill in-flight)
- Log: `priority_opus_glm_omnidoc.log` / `.err.log`
- Launch receipt: `priority_opus_glm_launch.json`

### PIDs / paths
- Supervisor PID: **22272** (relaunched 2026-09-05 14:55 KST after prefix fix)
- `pdf_validation` opus -> `omnidoc_raw/opus5_subscription/` (live ~253MB RSS)
- `pdf_validation` glm -> `omnidoc_raw/glm_ocr/` (live ~253MB RSS)
- Preds: Opus OmniDoc md **1630** nonempty; GLM **1599** nonempty + **47** empty (deferred)
- Opus content-filter FAILED pages naturally excluded (no pred)
- `infinity_parser2_pro` remains FOUNDER_EXCLUDED from main board

### Prefix fix (2026-09-05 14:55 KST)
- Bug: `_parallel_omnidoc.yaml_path` used `Path.resolve()` which followed `md_<model>` junctions → basename collapsed to `markdown` → all scorers wrote `markdown_quick_match_*` (clobber risk vs orphan deepseek).
- Fix: `yaml_path` now uses `Path.absolute()` (keeps `md_<model>` basename). OmniDoc `save_name` = `md_<model>_quick_match`.
- Priority opus/glm **killed and relaunched** with fixed configs (prediction paths now end in `md_opus5_subscription` / `md_glm_ocr`).
- Existing pool (hpd/mineru/monkey/ovis) + deepseek **left running** (founder: do not kill). They still have the pre-fix resolve() configs — **known clobber risk on `markdown_`**; recommend restart of pool after deepseek harvest, or accept deferred harvest via shared prefix.

### ETA
- Saturated 12-thread CPU + lower workers -> **~90-150 min** wall each; both parallel -> **~2-3 h**
- `comparison_omnidoc_full.md/json` refreshes via `_build_comparison.py` when each finishes

### Full-corpus (olmOCR + ParseBench)
- QA+prepare runner PID: **28372** (`_qa_prepare_opus_glm_corpus.py`) — earlier prepare refused missing QA reports; now QA then prepare
- After prepare green: enqueue `_parallel_olmocr.py opus5_subscription glm_ocr` (+ ParseBench when driver ready)
- GLM empties/deferred noted in NOTES

### Corpus prepare outcome (2026-09-05 14:51 KST)
| Model | olmOCR QA/prep | ParseBench QA/prep |
|---|---|---|
| opus5_subscription | PASS / wrote 1377 (26 skipped) | **RED** 465/2078 missing_case_keys — prepare refused |
| glm_ocr | **RED** 1401/1403 missing 2 keys — prepare refused | PASS / prepared |

- Opus olmOCR score attempted (`_parallel_olmocr.py opus5_subscription`) — see `olmocr_raw/opus5_subscription/` (rc details in logs)
- GLM olmOCR + Opus ParseBench blocked by section-44 QA gate until missing SUCCESS pages exist (note deferred; do not force)
- GLM ParseBench evaluator_input ready for later score

### Still LIVE (untouched)
- orphan `deepseek_ocr2` + pool `hpd_parsing` / `mineru_pipeline` / `mineru_vlm` / `monkeyocrv2_b` / `ovisocr2`
- original pool still queues `olmocr2`, `unlimited_ocr` (opus/glm SKIP if priority finishes first)

## Corrected scope (founder course-correction)
Not OmniDoc-1651-only. Analyze the **full ~5132-page campaign** across **all benches**:
- **omnidoc** ≈1651 pages → OmniDoc metrics (Edit↓ / TEDS↑)
- **olmocr** ≈1403 pages → olmOCR-bench metrics
- **parsebench** ≈2078 pages → ParseBench metrics
- Plus **corpus-wide non-judge stats** for every page (empty-rate, size distribution, SUCCESS/FAILED)

### Main board models
Settled GPU models + `glm_ocr` + `opus5_subscription` + `infinity_parser2_flash` **if enough SUCCESS** (Flash currently ~1888/5132 SUCCESS — include with coverage caveat).
**Exclude** `infinity_parser2_pro` from main board (reference-only if already scored; no more Pro work).

## Parallel plan
- CPU logical processors: **12** → target ≈ **5–6 concurrent model scorers**
- OmniDoc parallel driver: `_parallel_omnidoc.py`
  - Unique prediction dir aliases `md_<model>` → unique result prefixes (no shared `markdown_` clobber)
  - Per-model `match_workers=3`, `teds_workers=3` under load
  - File-redirect stdout/stderr (no `capture_output` hang)
- Keep orphan **deepseek_ocr2** mid-run; sequential 9–14h queue stopped
- olmOCR / ParseBench: file-redirect drivers next (prior blockers: Windows capture hang / Levenshtein DLL)

## Live OmniDoc runners (at STATUS write)
Parallel + orphan:
- `deepseek_ocr2` (orphan mid-run, prefix `markdown_`)
- `hpd_parsing`, `mineru_pipeline`, `mineru_vlm`, `monkeyocrv2_b`, `ovisocr2` (parallel, prefix `md_<model>`)
- Queued behind pool: `olmocr2`, `unlimited_ocr` — **opus5_subscription + glm_ocr PRIORITY STARTED**
- Done: `paddleocr_vl_1_6` (1651 pages, text Edit≈0.0426, TEDS≈0.9344, ~64 min)

## ETA (OmniDoc full 1651, parallel)
- ~60–80 min/model; with 5-wide pool remaining ≈ **2–3 hours** wall for OmniDoc wave (vs 9–14h sequential)
- olmOCR+ParseBench ETA TBD after driver bring-up

## Artifacts
- `STATUS.md` (this file)
- `NOTES.md`
- `corpus_coverage_5132.{md,json}` — non-judge 5132 stats (generating)
- `comparison_omnidoc_full.{md,json}` — OmniDoc leaderboard (updates as models finish)
- `omnidoc_raw/<model>/` — per-model OmniDoc artifacts
- `_parallel_omnidoc.py`, `_corpus_coverage.py`

## Blockers / notes
- ParseBench: prior Windows Levenshtein DLL ImportError risk
- olmOCR: official `capture_output` hang — need file-redirect like OmniDoc
- Flash: unsettled (PENDING 3240); score available SUCCESS only
- GLM: INVALIDATED / empties / PENDING residual — mark deferred
- Pro: FOUNDER_EXCLUDED

## Coverage % of planned 5132 (jobs SUCCESS / planned per bench)

| Model | OmniDoc% | olmOCR% | ParseBench% | All% | SUCCESS | PENDING/RUN | main |
|---|---:|---:|---:|---:|---:|---:|:---:|
| $(@{model=deepseek_ocr2; omnidoc_pct=100.30284675954; olmocr_pct=100.356379187455; parsebench_pct=100.240615976901; all_pct=100.292283710055; SUCCESS=5147; PENDING_or_RUNNING=0; main_board=True; by_benchmark_success=; planned=}.model) | 100.3 | 100.4 | 100.2 | 100.3 | 5147 | 0 | Y |
| $(@{model=glm_ocr; omnidoc_pct=97.8195033313144; olmocr_pct=100.570206699929; parsebench_pct=100.240615976901; all_pct=99.551831644583; SUCCESS=5109; PENDING_or_RUNNING=0; main_board=True; by_benchmark_success=; planned=}.model) | 97.8 | 100.6 | 100.2 | 99.6 | 5109 | 0 | Y |
| $(@{model=hpd_parsing; omnidoc_pct=100; olmocr_pct=100; parsebench_pct=100; all_pct=100; SUCCESS=5132; PENDING_or_RUNNING=0; main_board=True; by_benchmark_success=; planned=}.model) | 100 | 100 | 100 | 100 | 5132 | 0 | Y |
| $(@{model=infinity_parser2_flash; omnidoc_pct=32.5863113264688; olmocr_pct=99.7861724875267; parsebench_pct=0; all_pct=37.7630553390491; SUCCESS=1938; PENDING_or_RUNNING=3194; main_board=True; by_benchmark_success=; planned=}.model) | 32.6 | 99.8 | 0 | 37.8 | 1938 | 3194 | Y |
| $(@{model=infinity_parser2_pro; omnidoc_pct=32.7074500302847; olmocr_pct=70.6343549536707; parsebench_pct=0.240615976900866; all_pct=29.9298519095869; SUCCESS=1536; PENDING_or_RUNNING=3611; main_board=False; by_benchmark_success=; planned=}.model) | 32.7 | 70.6 | 0.2 | 29.9 | 1536 | 3611 | N |
| $(@{model=mineru_pipeline; omnidoc_pct=100.30284675954; olmocr_pct=100.356379187455; parsebench_pct=100.240615976901; all_pct=100.292283710055; SUCCESS=5147; PENDING_or_RUNNING=0; main_board=True; by_benchmark_success=; planned=}.model) | 100.3 | 100.4 | 100.2 | 100.3 | 5147 | 0 | Y |
| $(@{model=mineru_vlm; omnidoc_pct=102.119927316778; olmocr_pct=102.494654312188; parsebench_pct=101.684311838306; all_pct=102.045985970382; SUCCESS=5237; PENDING_or_RUNNING=0; main_board=True; by_benchmark_success=; planned=}.model) | 102.1 | 102.5 | 101.7 | 102 | 5237 | 0 | Y |
| $(@{model=monkeyocrv2_b; omnidoc_pct=100.30284675954; olmocr_pct=100.356379187455; parsebench_pct=98.3638113570741; all_pct=99.5323460639127; SUCCESS=5108; PENDING_or_RUNNING=0; main_board=True; by_benchmark_success=; planned=}.model) | 100.3 | 100.4 | 98.4 | 99.5 | 5108 | 0 | Y |
| $(@{model=olmocr2; omnidoc_pct=100.30284675954; olmocr_pct=100.356379187455; parsebench_pct=100.240615976901; all_pct=100.292283710055; SUCCESS=5147; PENDING_or_RUNNING=0; main_board=True; by_benchmark_success=; planned=}.model) | 100.3 | 100.4 | 100.2 | 100.3 | 5147 | 0 | Y |
| $(@{model=ovisocr2; omnidoc_pct=100.30284675954; olmocr_pct=100.356379187455; parsebench_pct=100.240615976901; all_pct=100.292283710055; SUCCESS=5147; PENDING_or_RUNNING=0; main_board=True; by_benchmark_success=; planned=}.model) | 100.3 | 100.4 | 100.2 | 100.3 | 5147 | 0 | Y |
| $(@{model=paddleocr_vl_1_6; omnidoc_pct=100; olmocr_pct=100; parsebench_pct=100; all_pct=100; SUCCESS=5132; PENDING_or_RUNNING=0; main_board=True; by_benchmark_success=; planned=}.model) | 100 | 100 | 100 | 100 | 5132 | 0 | Y |
| $(@{model=unlimited_ocr; omnidoc_pct=99.9394306480921; olmocr_pct=100.142551674982; parsebench_pct=99.4706448508181; all_pct=99.805144193297; SUCCESS=5122; PENDING_or_RUNNING=0; main_board=True; by_benchmark_success=; planned=}.model) | 99.9 | 100.1 | 99.5 | 99.8 | 5122 | 0 | Y |

## Parallel runners LIVE (2026-09-05 14:05 KST)
**UP now (6 OmniDoc concurrent on 12-thread CPU):**
- orphan: `deepseek_ocr2`
- pool: `hpd_parsing`, `mineru_pipeline`, `mineru_vlm`, `monkeyocrv2_b`, `ovisocr2`
- done: `paddleocr_vl_1_6` (full 1651)
- queued in same pool after slots free: `olmocr2`, `unlimited_ocr` (opus+glm **PRIORITY-STARTED** separately)

**Also running:**
- `_corpus_coverage.py` → empty-rate / size stats for all models (incl. Flash)
- `_prepare_olmocr_batch.py` (GT path fixed to `bench_data`)
- `_prepare_parsebench_batch.py`

**ParseBench:** Levenshtein OK in `benchmark/cache/parsebench/.venv` (prior blocker was wrong Python). Checkout under `scores/_evaluators/parsebench/...` not present yet — will use cache / checkout on score.

**Quick coverage file:** `coverage_pct_5132.json` (job SUCCESS / planned).
