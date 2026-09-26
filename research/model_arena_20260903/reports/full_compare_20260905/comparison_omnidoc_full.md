# OmniDoc full-corpus comparison — 2026-09-06 06:59 KST

Edit↓ lower better; TEDS↑ higher better.
GT = full OmniDocBench **1651** pages unless tag says filtered.
Driver: file-redirect OmniDoc (`_win_omnidoc_score_full.py`). Cloud cost **$0**.

## Settled leaderboard

| Rank | Model | text Edit↓ | formula Edit↓ | table Edit↓ | table TEDS↑ | reading_order Edit↓ | pages | elapsed_min | tag |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---|
| 1 | `paddleocr_vl_1_6` | 0.0426 | 0.0868 | 0.0513 | 0.9344 | 0.1304 | 1651 | 64.4 | settled_full_1651 |
| 2 | `infinity_parser2_flash` | 0.0449 | 0.1407 | 0.1293 | 0.8202 | 0.1377 | 1651 | 682.0 | settled_full_1651_priority_flash |
| 3 | `deepseek_ocr2` | 0.0584 | 0.1259 | 0.1178 | 0.7846 | 0.1500 | 1651 | — | settled_full_1651 |

## Reference / deferred

| Model | text Edit↓ | formula Edit↓ | table Edit↓ | table TEDS↑ | reading_order Edit↓ | pages | notes |
|---|---:|---:|---:|---:|---:|---:|---|
| `glm_ocr` *(ref)* | 0.0846 | 0.2960 | 0.5014 | 0.4874 | 0.2127 | 1651 | DEFERRED INVALIDATED; empty/PENDING residual; nonempty included |
| `opus5_subscription` *(ref)* | 0.0896 | 0.1458 | 0.5403 | 0.8284 | 0.1675 | 1651 | REF; 21 prepare-skipped under full GT |

## Pending
`hpd_parsing`, `infinity_parser2_pro`, `mineru_pipeline`, `mineru_vlm`, `monkeyocrv2_b`, `olmocr2`, `ovisocr2`, `unlimited_ocr`

## Highlights (settled so far)
- Best text Edit↓: `paddleocr_vl_1_6` = 0.0426
- Best table TEDS↑: `paddleocr_vl_1_6` = 0.9344

