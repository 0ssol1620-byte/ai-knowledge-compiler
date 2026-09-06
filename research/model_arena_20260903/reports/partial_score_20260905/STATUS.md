# Partial freeze+score — 2026-09-05

Generated: **2026-09-05 09:08 KST**
Cloud cost: **$0** (local CPU OmniDoc evaluator only). Caps not raised. Infinity not touched. GLM/supervisor not TaskStopped.

## GLM deferred
`glm_ocr` empty re-run still in progress; freeze is `INVALIDATED`. Do **not** treat prior OmniDoc triple scores as final GLM results.

## Frozen (complete=true)
- `deepseek_ocr2`: success=5132 frozen_at=2026-09-04T20:53:55Z UTC
- `hpd_parsing`: success=5132 frozen_at=2026-09-04T20:54:09Z UTC
- `mineru_pipeline`: success=5132 frozen_at=2026-09-04T20:54:23Z UTC
- `mineru_vlm`: success=5132 frozen_at=2026-09-04T20:54:35Z UTC
- `monkeyocrv2_b`: success=5093 frozen_at=2026-09-04T20:54:46Z UTC
- `ovisocr2`: success=5132 frozen_at=2026-09-04T20:54:56Z UTC
- `paddleocr_vl_1_6`: success=5132 frozen_at=2026-09-04T20:53:36Z UTC

## Unsettled (skip)
- `glm_ocr`: unsettled=0 states={'FAILED': 60, 'QUARANTINED': 8, 'SUCCESS': 5109}
- `olmocr2`: unsettled=0 states={'SUCCESS': 5147}
- `unlimited_ocr`: unsettled=0 states={'FAILED': 25, 'SUCCESS': 5122}
- `infinity_parser2_pro`: unsettled=3611 states={'PENDING': 3611, 'SUCCESS': 1536}

## OmniDoc scored (531-page subset)
GT: `reports/triple_overlap_20260904/omnidoc_gt_triple_overlap.json` (same filter as prior Infinity/Opus). Edit↓ / TEDS↑.

| Model | text Edit↓ | formula Edit↓ | table Edit↓ | table TEDS↑ | reading_order Edit↓ |
|---|---:|---:|---:|---:|---:|
| `ovisocr2` | 0.0283 | 0.0937 | 0.0483 | 0.9544 | 0.1161 |
| `infinity_parser2_pro` *(ref)* | 0.0360 | 0.1375 | 0.0967 | 0.8973 | 0.1280 |
| `hpd_parsing` | 0.0414 | 0.1069 | 0.0887 | 0.8926 | 0.1277 |
| `deepseek_ocr2` | 0.0435 | 0.1320 | 0.1453 | 0.8267 | 0.1367 |
| `paddleocr_vl_1_6` | 0.0436 | 0.0889 | 0.0493 | 0.9442 | 0.1294 |
| `monkeyocrv2_b` | 0.0486 | 0.1469 | 0.1326 | 0.8435 | 0.1268 |
| `mineru_vlm` | 0.0513 | 0.0974 | 0.0731 | 0.9230 | 0.1355 |
| `mineru_pipeline` | 0.0544 | 0.2325 | 0.3835 | 0.8104 | 0.1478 |
| `opus5_subscription` *(ref)* | 0.0690 | 0.1276 | 0.5339 | 0.8277 | 0.1464 |

Highlights among settled models: **ovisocr2** best text+TEDS; **paddleocr_vl_1_6** strong tables (TEDS 0.944); **hpd_parsing** strong text.

## Other benches
- ParseBench: QA mostly green; **score not run** (Levenshtein Windows risk). monkeyocrv2_b QA incomplete (39 missing).
- olmOCR: QA green for all 7; **score not run** (needs file-redirect driver like OmniDoc).

## Blockers
- **glm_ocr**: re-run unsettled; INVALIDATED freeze; prior OmniDoc GLM numbers untrusted
- **olmocr2**: unsettled=0
- **unlimited_ocr**: unsettled=0
- **infinity_parser2_pro**: FOUNDER_EXCLUDED — reference-only in comparison
- **parsebench_score**: not run; prior Windows Levenshtein DLL ImportError risk
- **olmocr_score**: not run; official capture_output hang on Windows
- **full_corpus_omnidoc_1651**: too slow for multi-model; used 531-page subset
- **arena_scoring_score_cli**: capture_output=True hang; used file-redirect OmniDoc driver

## Paths
- report: `reports/partial_score_20260905`
- status_md: `reports/partial_score_20260905/STATUS.md`
- comparison_md: `reports/partial_score_20260905/comparison_omnidoc_subset.md`
- comparison_json: `reports/partial_score_20260905/comparison_omnidoc_subset.json`
- omnidoc_raw: `reports/partial_score_20260905/omnidoc_raw`
- driver: `reports/partial_score_20260905/_win_omnidoc_score_subset.py`

## Late updates
- `olmocr2` and `unlimited_ocr` reached unsettled=0 during this pass and were frozen (complete=true). Not OmniDoc-scored yet.
- `glm_ocr` jobs unsettled=0 but still INVALIDATED — **not** final-frozen/scored.
