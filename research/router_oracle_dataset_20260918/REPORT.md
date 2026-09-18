# Router Oracle Dataset v1 (ROD-v1) — OmniDocBench surface, spent 2026-09-03 Arena

**This is development evidence, not a public benchmark result and not a champion promotion.**
Every number is arithmetic over stored campaign files: no inference, no GPU, $0 of new spend.
Page-class features come from OmniDocBench ground-truth attributes, i.e. a *perfect* page
classifier. Every routed arm below is therefore an **upper bound** on what a real preflight can reach.

## Dataset

- Campaign `TAVONEL-MODEL-ARENA-PUBLIC-20260903-V1`; dataset id `ROD-v1-omnidoc-20260918`.
- Ground-truth pages 1,651; pages with text ground truth scored by all 9 paths **1,557** (94 pages have no text element and are excluded, recorded).
- Document families 1,340 (rule: image stem with a trailing _page_NNN or .pdf_NNN page suffix removed (same source document = same family); a page without such a suffix is its own family).
- Family-level split (masterplan v5 §8.4), seeded, written before any score was read:

| split | families | pages | DEGRADED | FORMULA | MULTI_COLUMN | SIMPLE | TABLE |
|---|---:|---:|---:|---:|---:|---:|---:|
| ROUTER_TRAIN | 792 | 920 | 20 | 59 | 342 | 297 | 202 |
| ROUTER_CALIBRATION | 277 | 320 | 10 | 19 | 122 | 97 | 72 |
| ROUTER_HOLDOUT | 271 | 317 | 17 | 19 | 104 | 109 | 68 |

- Trusted = text edit distance ≤ 0.05; catastrophic = edit ≥ 0.5; a FAILED/QUARANTINED job is a provider/operational failure and stays in the denominator.
- Cost and latency come from the campaign queue ledger per job (see POLICY_FREEZE.json notes); cost-imputed pages: none.
- Excluded paths and why: `olmocr2` — no per-page OmniDoc edit file in the campaign (aggregate only); `unlimited_ocr` — no per-page OmniDoc edit file in the campaign (aggregate only); `opus5_subscription` — closed API on a subscription surface: cost unmeasured (never zero), external egress not permitted by default; `infinity_parser2_pro` — FOUNDER_EXCLUDED 2026-09-04.

## Method

1. Bootstrap policy (masterplan v5 §10.5, Minimum Cost to Trusted Output): per page-class cell (page class x script family) fitted on ROUTER_TRAIN, choose the cheapest permitted path whose trusted rate meets the floor; cells with fewer than 20 TRAIN pages use the global choice.
2. The one knob (trust floor ∈ [0.8, 0.85, 0.9, 0.95]) is selected on ROUTER_CALIBRATION by lowest mean oracle regret. The holdout is opened exactly once per permitted set.
3. Metrics (masterplan v5 §10.3) on ROUTER_HOLDOUT: mean quality (1 - text edit), trusted rate, trust violation, catastrophic rate, cost per page, p50/p95 latency, oracle regret under the frozen utility policy {'quality_reward': '1', 'cost_penalty': '10', 'latency_penalty': '0', 'untrusted_penalty': '0.2', 'catastrophic_penalty': '0.5'}, cost vs always-X, route mix. `ORACLE_DIAGNOSTIC` reads hidden truth and is never a router result.
4. Quality and cost deltas carry a 95% cluster bootstrap interval (2000 replicates, resampling families).

## Permitted set `PRODUCTION_BOUND`

Permitted paths: `paddleocr_vl_1_6`, `hpd_parsing`.
Calibration (mean regret on ROUTER_CALIBRATION by trust floor): 0.8 → 0.0346, 0.85 → 0.0658, 0.9 → 0.0649, 0.95 → 0.0649. Selected floor **0.8**.

Fitted policy (page class | script family → path):

| cell | path |
|---|---|
| default | `paddleocr_vl_1_6` |
| DEGRADED|han | `paddleocr_vl_1_6` |
| DEGRADED|latin | `paddleocr_vl_1_6` |
| DEGRADED|mixed | `paddleocr_vl_1_6` |
| FORMULA|han | `paddleocr_vl_1_6` |
| FORMULA|latin | `paddleocr_vl_1_6` |
| MULTI_COLUMN|han | `hpd_parsing` |
| MULTI_COLUMN|latin | `paddleocr_vl_1_6` |
| MULTI_COLUMN|mixed | `paddleocr_vl_1_6` |
| SIMPLE|han | `paddleocr_vl_1_6` |
| SIMPLE|latin | `paddleocr_vl_1_6` |
| SIMPLE|mixed | `paddleocr_vl_1_6` |
| TABLE|han | `paddleocr_vl_1_6` |
| TABLE|latin | `paddleocr_vl_1_6` |
| TABLE|mixed | `paddleocr_vl_1_6` |

Holdout results (one opening):

| arm | n | mean quality | trusted | trust violation | catastrophic | provider/op failure | $/1k pages | p50 s | p95 s | mean regret | route mix |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `ORACLE_DIAGNOSTIC` | 317 | 0.9749 | 0.855 | 0.145 | 0.000 | 0.000 | 1.51 | 4.0 | 14.0 | 0.0000 | paddleocr_vl_1_6 274, hpd_parsing 43 |
| `BOOTSTRAP_MCTO` | 317 | 0.9630 | 0.792 | 0.208 | 0.003 | 0.000 | 1.74 | 4.0 | 11.0 | 0.0284 | paddleocr_vl_1_6 273, hpd_parsing 44 |
| `ALWAYS:hpd_parsing` | 317 | 0.9619 | 0.785 | 0.215 | 0.003 | 0.000 | 3.65 | 3.0 | 9.0 | 0.0499 | hpd_parsing 317 |
| `ALWAYS:paddleocr_vl_1_6` | 317 | 0.9611 | 0.792 | 0.208 | 0.003 | 0.000 | 1.21 | 5.0 | 14.0 | 0.0251 | paddleocr_vl_1_6 317 |

- Best single arm: `ALWAYS:hpd_parsing`. BOOTSTRAP_MCTO quality delta vs best single: **+0.0011** (95% CI -0.0069 to +0.0093).
- Cost delta per page vs current production champion `paddleocr_vl_1_6`: +0.52 $/1k (95% CI +0.32 to +0.78); cost ratio vs always-champion 1.43x, vs always-cheapest 1.43x, vs always-best-quality 0.48x.
- Oracle headroom over best single: 0.0130 quality; oracle capture ratio of BOOTSTRAP_MCTO: 0.083 (1.0 = oracle, 0 = best single, negative = worse than best single).

## Permitted set `OSS_PORTFOLIO`

Permitted paths: `deepseek_ocr2`, `glm_ocr`, `hpd_parsing`, `infinity_parser2_flash`, `mineru_pipeline`, `mineru_vlm`, `monkeyocrv2_b`, `ovisocr2`, `paddleocr_vl_1_6`.
Calibration (mean regret on ROUTER_CALIBRATION by trust floor): 0.8 → 0.0493, 0.85 → 0.0336, 0.9 → 0.0277, 0.95 → 0.0277. Selected floor **0.95**.

Fitted policy (page class | script family → path):

| cell | path |
|---|---|
| default | `ovisocr2` |
| DEGRADED|han | `ovisocr2` |
| DEGRADED|latin | `ovisocr2` |
| DEGRADED|mixed | `ovisocr2` |
| FORMULA|han | `ovisocr2` |
| FORMULA|latin | `ovisocr2` |
| MULTI_COLUMN|han | `ovisocr2` |
| MULTI_COLUMN|latin | `ovisocr2` |
| MULTI_COLUMN|mixed | `ovisocr2` |
| SIMPLE|han | `ovisocr2` |
| SIMPLE|latin | `ovisocr2` |
| SIMPLE|mixed | `glm_ocr` |
| TABLE|han | `ovisocr2` |
| TABLE|latin | `ovisocr2` |
| TABLE|mixed | `ovisocr2` |

Holdout results (one opening):

| arm | n | mean quality | trusted | trust violation | catastrophic | provider/op failure | $/1k pages | p50 s | p95 s | mean regret | route mix |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `ORACLE_DIAGNOSTIC` | 317 | 0.9835 | 0.909 | 0.091 | 0.000 | 0.000 | 0.80 | 4.0 | 11.0 | 0.0000 | mineru_vlm 121, ovisocr2 86, glm_ocr 47, mineru_pipeline 34, paddleocr_vl_1_6 13, monkeyocrv2_b 7, hpd_parsing 5, infinity_parser2_flash 2, deepseek_ocr2 2 |
| `ALWAYS:ovisocr2` | 317 | 0.9706 | 0.858 | 0.142 | 0.000 | 0.000 | 1.11 | 4.0 | 16.0 | 0.0260 | ovisocr2 317 |
| `BOOTSTRAP_MCTO` | 317 | 0.9684 | 0.861 | 0.139 | 0.003 | 0.003 | 1.11 | 4.0 | 16.0 | 0.0292 | ovisocr2 303, glm_ocr 14 |
| `ALWAYS:hpd_parsing` | 317 | 0.9619 | 0.785 | 0.215 | 0.003 | 0.000 | 3.65 | 3.0 | 9.0 | 0.0763 | hpd_parsing 317 |
| `ALWAYS:paddleocr_vl_1_6` | 317 | 0.9611 | 0.792 | 0.208 | 0.003 | 0.000 | 1.21 | 5.0 | 14.0 | 0.0514 | paddleocr_vl_1_6 317 |
| `ALWAYS:mineru_vlm` | 317 | 0.9551 | 0.779 | 0.221 | 0.016 | 0.000 | 0.74 | 5.0 | 12.0 | 0.0616 | mineru_vlm 317 |
| `ALWAYS:infinity_parser2_flash` | 317 | 0.9485 | 0.773 | 0.227 | 0.013 | 0.000 | 2.46 | 9.0 | 34.2 | 0.0850 | infinity_parser2_flash 317 |
| `ALWAYS:deepseek_ocr2` | 317 | 0.9455 | 0.748 | 0.252 | 0.016 | 0.000 | 5.99 | 24.0 | 72.0 | 0.1299 | deepseek_ocr2 317 |
| `ALWAYS:monkeyocrv2_b` | 317 | 0.9320 | 0.722 | 0.278 | 0.032 | 0.000 | 1.84 | 6.0 | 24.0 | 0.1149 | monkeyocrv2_b 317 |
| `ALWAYS:mineru_pipeline` | 317 | 0.9312 | 0.741 | 0.259 | 0.035 | 0.000 | 1.26 | 5.0 | 14.1 | 0.1076 | mineru_pipeline 317 |
| `ALWAYS:glm_ocr` | 317 | 0.9238 | 0.748 | 0.252 | 0.035 | 0.032 | 1.32 | 4.0 | 19.1 | 0.1143 | glm_ocr 317 |

- Best single arm: `ALWAYS:ovisocr2`. BOOTSTRAP_MCTO quality delta vs best single: **-0.0022** (95% CI -0.0093 to +0.0023).
- Cost delta per page vs current production champion `paddleocr_vl_1_6`: -0.10 $/1k (95% CI -0.27 to +0.06); cost ratio vs always-champion 0.92x, vs always-cheapest 1.49x, vs always-best-quality 1.00x.
- Oracle headroom over best single: 0.0129 quality; oracle capture ratio of BOOTSTRAP_MCTO: -0.171 (1.0 = oracle, 0 = best single, negative = worse than best single).

## Holdout Document Performance Map (all nine paths, per path)

| path | n | trusted | semantic fail | provider fail | operational fail | catastrophic | mean quality | mean $/page | mean s |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `deepseek_ocr2` | 317 | 237 | 80 | 0 | 0 | 5 | 0.9455 | 0.00599 | 29.1 |
| `glm_ocr` | 317 | 237 | 70 | 8 | 2 | 11 | 0.9238 | 0.00132 | 6.4 |
| `hpd_parsing` | 317 | 249 | 68 | 0 | 0 | 1 | 0.9619 | 0.00365 | 3.8 |
| `infinity_parser2_flash` | 317 | 245 | 72 | 0 | 0 | 4 | 0.9485 | 0.00246 | 12.0 |
| `mineru_pipeline` | 317 | 235 | 82 | 0 | 0 | 11 | 0.9312 | 0.00126 | 6.1 |
| `mineru_vlm` | 317 | 247 | 70 | 0 | 0 | 5 | 0.9551 | 0.00074 | 5.5 |
| `monkeyocrv2_b` | 317 | 229 | 88 | 0 | 0 | 10 | 0.9320 | 0.00184 | 9.0 |
| `ovisocr2` | 317 | 272 | 45 | 0 | 0 | 0 | 0.9706 | 0.00111 | 5.4 |
| `paddleocr_vl_1_6` | 317 | 251 | 66 | 0 | 0 | 1 | 0.9611 | 0.00121 | 5.9 |

Trusted rate by holdout cell (page class | script family), n ≥ 10 only:

| cell | n | `deepseek_ocr2` | `glm_ocr` | `hpd_parsing` | `infinity_parser2_flash` | `mineru_pipeline` | `mineru_vlm` | `monkeyocrv2_b` | `ovisocr2` | `paddleocr_vl_1_6` |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| DEGRADED|han | 12 | 0.50 | 0.75 | 0.67 | 0.75 | 0.50 | 0.67 | 0.75 | 0.92 | 0.67 |
| FORMULA|latin | 13 | 0.38 | 0.46 | 0.38 | 0.46 | 0.23 | 0.46 | 0.31 | 0.38 | 0.46 |
| MULTI_COLUMN|han | 44 | 0.55 | 0.57 | 0.68 | 0.57 | 0.68 | 0.66 | 0.52 | 0.82 | 0.68 |
| MULTI_COLUMN|latin | 57 | 0.81 | 0.81 | 0.84 | 0.82 | 0.81 | 0.82 | 0.81 | 0.91 | 0.86 |
| SIMPLE|han | 45 | 0.82 | 0.73 | 0.78 | 0.76 | 0.76 | 0.80 | 0.67 | 0.82 | 0.80 |
| SIMPLE|latin | 50 | 0.92 | 0.86 | 0.92 | 0.96 | 0.82 | 0.92 | 0.82 | 0.98 | 0.92 |
| SIMPLE|mixed | 14 | 0.71 | 0.93 | 0.86 | 0.93 | 0.93 | 0.79 | 0.86 | 0.86 | 0.86 |
| TABLE|han | 42 | 0.76 | 0.79 | 0.83 | 0.76 | 0.71 | 0.79 | 0.79 | 0.86 | 0.79 |
| TABLE|latin | 21 | 0.90 | 0.86 | 0.90 | 0.90 | 1.00 | 0.90 | 0.95 | 0.95 | 0.95 |

## Reading

- With a perfect page classifier and the production-bound paths, the class-conditional bootstrap policy is statistically indistinguishable from always-Paddle on quality and costs more (it sends multi-column Han pages to `hpd_parsing`, which ran on an H100 in this campaign).
- With the whole open-source portfolio it does not beat always-`ovisocr2`; the oracle headroom (about 1.3 quality points) is spread across paths in a way the page class does not predict. This agrees with the 2026-09-08 replay (no runtime-visible arm captured any oracle headroom).
- Consequence for the router: on this corpus the value is not in choosing a model per page class. It is in (a) promoting a better champion when one is licensed and qualified, (b) failure classification and recovery, and (c) cost. Masterplan v5 §8.3 ("Oracle gain 작음 → Router complexity 재검토") applies.
- Nothing here is a fresh holdout: the corpus was spent by earlier research, so this cannot become a confirmatory result by re-splitting it. A frozen unseen corpus and a paid run with receipts remain required.

## Integrity

- Dataset rows `router_oracle_dataset.jsonl` (git-ignored, Router Outcome Dataset is trade secret): sha256 `864d15704c69c197dd37ffd881a4e5484a798367d4f387746a2cdd9350b77b2e`.
- SPLIT_MANIFEST.json sha256 `50ee2d6c6bbfe89f2c5f6762b226edf1ee072e8ad29d902663afe3adff02e1d7`.
- Inputs (sha256):
  - `OmniDocBench.json` — `a45cd84b04ad8b793e775089640e6b681209abea33ead54c1828ddca35fae496`
  - `markdown_quick_match_text_block_per_page_edit.json` — `d507e4fb25d53ceecfe509e38b81abe76e3a02fc23c64acae6556060c65fcbef`
  - `markdown_quick_match_display_formula_per_page_edit.json` — `a68f4b4dd70f9d899cd24fd80a5d22ccf2d310719776641543a02ca026ccc0ca`
  - `markdown_quick_match_table_per_page_edit.json` — `7cb0eeda92dac038f7ae7db2f19352dc8aa8da990c4c0e104ea57182c7a63b76`
  - `markdown_quick_match_reading_order_per_page_edit.json` — `da9dc5290af33bee37bc8754289cef235287834d599979bb17526e08350d8a83`
  - `md_glm_ocr_quick_match_text_block_per_page_edit.json` — `1ea4e5d1a442a8cc460d8bd115ae6f67ae4bb2b6a0f133c7379e66d089236bdd`
  - `md_glm_ocr_quick_match_display_formula_per_page_edit.json` — `4fb678017092f8008c8f25050c2f37d992eca5cd584309ce3394410f9ee8748f`
  - `md_glm_ocr_quick_match_table_per_page_edit.json` — `90a7b7e3bae7acc4360900fa0a29b9298f40936d51396a3a44d9d61335f8c21a`
  - `md_glm_ocr_quick_match_reading_order_per_page_edit.json` — `1f8792892699e06944cc3577ed5261a877e725a425cba5f5ac2245b7cff0509c`
  - `md_hpd_parsing_quick_match_text_block_per_page_edit.json` — `1c3abe3870d9909b7f1caaa2bcbea0a9b6ba8b00bf0476f63fd966ccca649549`
  - `md_hpd_parsing_quick_match_display_formula_per_page_edit.json` — `c3fe3147f31b7946e12ceaecf5cf5b0bc702391a1f31300ad0a98fdb2a950e0e`
  - `md_hpd_parsing_quick_match_table_per_page_edit.json` — `f32b4f4426d3fff7190c6a1f910444a8bed701afe258385ecf29e58474ba86e8`
  - `md_hpd_parsing_quick_match_reading_order_per_page_edit.json` — `eb8e169edc76a8b039de4739b6a790e1788e5848ebe5b9286f736153d1215a86`
  - `md_infinity_parser2_flash_quick_match_text_block_per_page_edit.json` — `b1d1be73919755c23d81b23d01d390c6857c378f9d3383fe10dec2ffa48b41f8`
  - `md_infinity_parser2_flash_quick_match_display_formula_per_page_edit.json` — `5fda1ac94e86084d712f006dfe55121adefd68426977f6478e168fe960553c9a`
  - `md_infinity_parser2_flash_quick_match_table_per_page_edit.json` — `6e978b8680564528ac051fb95b8f3dc06ed5b707365aef22959b2d856a3ef5a3`
  - `md_infinity_parser2_flash_quick_match_reading_order_per_page_edit.json` — `af60fceb23b7c303ac9f13da4cd91684bfcaf11c16914371c5a2d678252ad03b`
  - `md_mineru_pipeline_quick_match_text_block_per_page_edit.json` — `9601f651abaca1ef91d2920d66ec078b0bd7ef6d23459a37ea2bc802d3f053a5`
  - `md_mineru_pipeline_quick_match_display_formula_per_page_edit.json` — `314c1574be93fa0ee28e9fafea63d3abbfd9edd4ffdb9a4c83877062a857a854`
  - `md_mineru_pipeline_quick_match_table_per_page_edit.json` — `a69a3aca57deae4842c8f6a427cead84afcec41d8df39b1b7840e932b4bea83e`
  - `md_mineru_pipeline_quick_match_reading_order_per_page_edit.json` — `99e6124ef5ec4248aa6230e3b27c655f2303b402c182b34cba757fe18ca5e7b5`
  - `md_mineru_vlm_quick_match_text_block_per_page_edit.json` — `bfa28b93ec331e35b7493422dee7977fbb70aae337b922fd6c6cb7879ba9fb84`
  - `md_mineru_vlm_quick_match_display_formula_per_page_edit.json` — `3d346e7eaa956d82f1b730e32c4222f308d2480d442b0a36dab6f2d3b61dc05c`
  - `md_mineru_vlm_quick_match_table_per_page_edit.json` — `012431cae1207ca6c52cf125659f06f02dccb01763cff0610a26a60f64307dba`
  - `md_mineru_vlm_quick_match_reading_order_per_page_edit.json` — `64891f855389cfd83c8c27e8a8d234e9adc3cdd3a8bfb179f7253e9105a83afd`
  - `md_monkeyocrv2_b_quick_match_text_block_per_page_edit.json` — `7836d30628321f27c73abad21dd79d0c5e02d45f6b47cfd1986d86ba52a2ad41`
  - `md_monkeyocrv2_b_quick_match_display_formula_per_page_edit.json` — `12f220ff9d4f118c2ba5c04bb95d1490d1b21daac4afd0b9fccf0539819dffbb`
  - `md_monkeyocrv2_b_quick_match_table_per_page_edit.json` — `001879ed356522a551bb1535e98f6924e89b4ded208000938f447bd56ad15e85`
  - `md_monkeyocrv2_b_quick_match_reading_order_per_page_edit.json` — `a4c289596554c06d3c65f8a154f267132fcf546df71f58307ef824490de8dd60`
  - `md_ovisocr2_quick_match_text_block_per_page_edit.json` — `529772fd8ee851854a0191610967339eed0a1300dc9d05d7491514e9b7e4ec2f`
  - `md_ovisocr2_quick_match_display_formula_per_page_edit.json` — `25b07619f45ef91d822689e54c1e85b9f634b33ec8d09fdf7424c84002c39c4d`
  - `md_ovisocr2_quick_match_table_per_page_edit.json` — `4783b0e3df0f29d7fc375a9a856078f98802086677621a1c863316abcb09ecf9`
  - `md_ovisocr2_quick_match_reading_order_per_page_edit.json` — `cc3c537c7c63f57177f2f74682591f43a378dd913c674a053c603d0dbe2f4eb5`
  - `markdown_quick_match_text_block_per_page_edit.json` — `d3eb815b15f833709123e41765d2a5939ec492097636cbd601cb53c268b575e2`
  - `markdown_quick_match_display_formula_per_page_edit.json` — `ef49329795b643846c76e111f6388457b2898a4e0abbf4e9c656825450c723ba`
  - `markdown_quick_match_table_per_page_edit.json` — `a1d6cb6592b66d3d67383894e41f6e90380b4886cbe8dcc41c00f6677c58950c`
  - `markdown_quick_match_reading_order_per_page_edit.json` — `f2047de305669991283e7f0bc6086caba874ad9fd8ebe1407275b007fc4c8a4d`
  - `campaign.sqlite` — `9f0f6d4de55fadf2553178e65b8fc4dfd4ec5d60ecf152c6f44c9c3a62e09fd8`

