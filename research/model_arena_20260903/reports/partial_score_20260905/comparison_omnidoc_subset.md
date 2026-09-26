# OmniDoc subset comparison (531 pages)

- GT filter: `reports/triple_overlap_20260904/omnidoc_gt_triple_overlap.json` (same 531-page subset as prior Infinity/Opus pass)
- Cloud cost: **$0**
- **GLM deferred** (empty re-run; prior GLM OmniDoc numbers untrusted — omitted)
- Infinity shown as prior reference only (`FOUNDER_EXCLUDED` from this campaign scoring)
- Edit_dist ↓ better; table TEDS ↑ better

| Model | source | pages | text Edit↓ | formula Edit↓ | table Edit↓ | table TEDS↑ | reading_order Edit↓ |
|---|---|---:|---:|---:|---:|---:|---:|
| `ovisocr2` | partial_score_20260905 | 531 | 0.0283 | 0.0937 | 0.0483 | 0.9544 | 0.1161 |
| `infinity_parser2_pro` | triple_overlap_20260904_reference | 531 | 0.0360 | 0.1375 | 0.0967 | 0.8973 | 0.1280 |
| `hpd_parsing` | partial_score_20260905 | 531 | 0.0414 | 0.1069 | 0.0887 | 0.8926 | 0.1277 |
| `deepseek_ocr2` | partial_score_20260905 | 531 | 0.0435 | 0.1320 | 0.1453 | 0.8267 | 0.1367 |
| `paddleocr_vl_1_6` | partial_score_20260905 | 531 | 0.0436 | 0.0889 | 0.0493 | 0.9442 | 0.1294 |
| `monkeyocrv2_b` | partial_score_20260905 | 531 | 0.0486 | 0.1469 | 0.1326 | 0.8435 | 0.1268 |
| `mineru_vlm` | partial_score_20260905 | 531 | 0.0513 | 0.0974 | 0.0731 | 0.9230 | 0.1355 |
| `mineru_pipeline` | partial_score_20260905 | 531 | 0.0544 | 0.2325 | 0.3835 | 0.8104 | 0.1478 |
| `opus5_subscription` | triple_overlap_20260904_reference | 531 | 0.0690 | 0.1276 | 0.5339 | 0.8277 | 0.1464 |

