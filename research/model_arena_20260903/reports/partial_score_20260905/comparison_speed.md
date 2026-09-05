# Speed comparison (per-page latency)

Generated: **2026-09-05 09:36 KST**
Source: `queue/campaign.sqlite` SUCCESS `started_at`→`finished_at`

**How to read:** `median sec/page` ↓ is the fairest single-stream speed proxy. `serial pages/h` = 3600/median. Campaign wall pages/h is **not** fair (parallel pods).

| Rank | Model | n | median sec/page ↓ | p90 sec/page | serial pages/h ↑ | campaign wall pages/h | role |
|---:|---|---:|---:|---:|---:|---:|---|
| 1 | `hpd_parsing` | 5117 | 3.0 | 7.0 | 1200.0 | 252.0 | primary |
| 2 | `mineru_pipeline` | 5132 | 4.0 | 13.0 | 900.0 | 223.8 | primary |
| 3 | `ovisocr2` | 5132 | 4.0 | 10.0 | 900.0 | 289.0 | primary |
| 4 | `paddleocr_vl_1_6` | 5117 | 4.0 | 9.0 | 900.0 | 266.9 | primary |
| 5 | `glm_ocr` | 5064 | 5.0 | 13.0 | 720.0 | 189.7 | primary |
| 6 | `mineru_vlm` | 5117 | 5.0 | 8.0 | 720.0 | 237.9 | primary |
| 7 | `monkeyocrv2_b` | 5093 | 6.0 | 16.0 | 600.0 | 225.8 | primary |
| 8 | `olmocr2` | 5132 | 13.0 | 33.0 | 276.9 | 205.5 | primary |
| 9 | `deepseek_ocr2` | 5132 | 27.0 | 60.0 | 133.3 | 220.1 | primary |
| 10 | `unlimited_ocr` | 5107 | 29.0 | 61.0 | 124.1 | 222.2 | primary |
| — | `infinity_parser2_pro` | 1521 | 9.0 | 15.0 | 400.0 | 105.7 | reference |

## Caveats
- Latency is per-job wall time (started_at to finished_at), not pure GPU kernel time.
- serial_pages_per_hour = 3600/median_sec_per_page (single-stream equivalent).
- campaign_wall_pages_per_hour includes concurrent workers/pods — not fair hardware-normalized speed.
- Hardware mix differs across models; Opus is subscription API, not pod GPU.
- GLM includes empty re-inference history; sick pods may skew early latency.
- Infinity is FOUNDER_EXCLUDED — reference only.

JSON: `reports/partial_score_20260905/comparison_speed.json`