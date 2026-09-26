# Triple-overlap OmniDoc comparison (Infinity ∩ GLM ∩ Opus)

- Triple-overlap case_keys (all benches): **1498**
- OmniDoc subset scored: **531** pages (filtered GT); per-case joinable: **528**
- Cloud cost: **$0** (local CPU only)
- Edit_dist: lower better; TEDS: higher better

## Aggregate metrics

| Model | text Edit↓ | formula Edit↓ | table Edit↓ | table TEDS↑ | reading_order Edit↓ |
|---|---:|---:|---:|---:|---:|
| `infinity_parser2_pro` | 0.0360 | 0.1375 | 0.0967 | 0.8973 | 0.1280 |
| `glm_ocr` | 0.8572 | 0.8597 | 0.8989 | 0.0889 | 0.8764 |
| `opus5_subscription` | 0.0690 | 0.1276 | 0.5339 | 0.8277 | 0.1464 |

## Head-to-head (pages with all three per-case rows)

N common per-case pages: 528

### By mean of available element Edit_dist (lower wins)
- `infinity_parser2_pro`: **258**
- `glm_ocr`: **11**
- `opus5_subscription`: **131**
- `TIE`: **128**

### By text_block Edit_dist (lower wins)
- `infinity_parser2_pro`: **136**
- `glm_ocr`: **11**
- `opus5_subscription`: **132**
- `TIE`: **221**

### By table TEDS where all three have tables (higher wins); pages=153
- `infinity_parser2_pro`: **100**
- `glm_ocr`: **3**
- `opus5_subscription`: **23**
- `TIE`: **27**

## Blockers / not scored
- parsebench (1 page): Levenshtein DLL ImportError on Windows
- olmocr (966 pages): not run in this pass (driver path ready but deferred after OmniDoc)

