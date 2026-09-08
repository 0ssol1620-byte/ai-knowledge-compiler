# Oracle ceiling tables — Phase A (stored outputs, GPU spend $0)

Loss is lower-better. `IRR proxy = 1 - mean loss` over L1/L3/L4/L5 only (see LOSS_VECTOR_FREEZE.json). NOT a public benchmark result.

## Surface `omnidoc`

- page classes from OmniDocBench GT page_attribute (D:\CodexProjects\ai-knowledge-compiler\benchmark\datasets\acquired\public-core\omnidocbench\OmniDocBench.json)
- reconciler candidates resolved for 1651 units; 0 UNRESOLVED

### Cohort `intersection` (N = 1641 units)

| plan | n | mean loss | IRR proxy | hard fail (>0.05) | unresolved N/A | 95% CI |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `ORACLE_ELEMENTWISE_FORBIDDEN` | 1641 | 0.0364 | 0.9636 | 303 | 0 | [0.0326, 0.0403] |
| `ORACLE_PERMITTED` | 1641 | 0.0390 | 0.9610 | 330 | 0 | [0.0351, 0.0429] |
| `PAGE_CLASS_CHAMPION` | 1641 | 0.0513 | 0.9487 | 456 | 0 | [0.0468, 0.0559] |
| `SINGLE:ovisocr2` | 1641 | 0.0559 | 0.9441 | 460 | 0 | [0.0508, 0.0609] |
| `ALWAYS_ALL_RECONCILED` | 1442 | 0.0646 | 0.9354 | 464 | 199 | [0.0586, 0.0705] |
| `SINGLE:paddleocr_vl_1_6` | 1641 | 0.0685 | 0.9315 | 594 | 0 | [0.0631, 0.0738] |
| `SINGLE:hpd_parsing` | 1641 | 0.0720 | 0.9280 | 561 | 0 | [0.0658, 0.0784] |
| `SINGLE:mineru_vlm` | 1641 | 0.0762 | 0.9238 | 603 | 0 | [0.0696, 0.0828] |
| `SINGLE:infinity_parser2_flash` | 1641 | 0.0819 | 0.9181 | 668 | 0 | [0.0756, 0.0884] |
| `SINGLE:monkeyocrv2_b` | 1641 | 0.0889 | 0.9111 | 657 | 0 | [0.0818, 0.0961] |
| `SINGLE:deepseek_ocr2` | 1641 | 0.0930 | 0.9070 | 703 | 0 | [0.0857, 0.1009] |
| `SINGLE:mineru_pipeline` | 1641 | 0.1274 | 0.8726 | 847 | 0 | [0.1183, 0.1358] |
| `SINGLE:opus5_subscription` | 1641 | 0.1649 | 0.8351 | 850 | 0 | [0.1533, 0.1770] |
| `SINGLE:glm_ocr` | 1641 | 0.1717 | 0.8283 | 901 | 0 | [0.1592, 0.1841] |

Best fixed single: `SINGLE:ovisocr2`. Oracle headroom = 0.0169 absolute loss (30.3% relative), cluster-bootstrap 95% CI [0.0140, 0.0201] over 1435 document-family clusters.

Section 90 capture ratio — ALWAYS_ALL_RECONCILED -0.513, PAGE_CLASS_CHAMPION 0.269, TAVONEL router n/a (Phase B).

### Cohort `missing_as_failure` (N = 1641 units)

| plan | n | mean loss | IRR proxy | hard fail (>0.05) | unresolved N/A | 95% CI |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `ORACLE_ELEMENTWISE_FORBIDDEN` | 1641 | 0.0364 | 0.9636 | 303 | 0 | [0.0326, 0.0403] |
| `ORACLE_PERMITTED` | 1641 | 0.0390 | 0.9610 | 330 | 0 | [0.0351, 0.0429] |
| `PAGE_CLASS_CHAMPION` | 1641 | 0.0513 | 0.9487 | 456 | 0 | [0.0468, 0.0559] |
| `SINGLE:ovisocr2` | 1641 | 0.0559 | 0.9441 | 460 | 0 | [0.0508, 0.0609] |
| `SINGLE:paddleocr_vl_1_6` | 1641 | 0.0685 | 0.9315 | 594 | 0 | [0.0631, 0.0738] |
| `SINGLE:hpd_parsing` | 1641 | 0.0720 | 0.9280 | 561 | 0 | [0.0658, 0.0784] |
| `SINGLE:mineru_vlm` | 1641 | 0.0762 | 0.9238 | 603 | 0 | [0.0696, 0.0828] |
| `SINGLE:infinity_parser2_flash` | 1641 | 0.0819 | 0.9181 | 668 | 0 | [0.0756, 0.0884] |
| `SINGLE:monkeyocrv2_b` | 1641 | 0.0889 | 0.9111 | 657 | 0 | [0.0818, 0.0961] |
| `SINGLE:deepseek_ocr2` | 1641 | 0.0930 | 0.9070 | 703 | 0 | [0.0857, 0.1009] |
| `SINGLE:mineru_pipeline` | 1641 | 0.1274 | 0.8726 | 847 | 0 | [0.1183, 0.1358] |
| `SINGLE:opus5_subscription` | 1641 | 0.1649 | 0.8351 | 850 | 0 | [0.1533, 0.1770] |
| `SINGLE:glm_ocr` | 1641 | 0.1717 | 0.8283 | 901 | 0 | [0.1592, 0.1841] |
| `ALWAYS_ALL_RECONCILED` | 1641 | 0.1780 | 0.8220 | 663 | 199 | [0.1621, 0.1944] |

Best fixed single: `SINGLE:ovisocr2`. Oracle headroom = 0.0169 absolute loss (30.3% relative), cluster-bootstrap 95% CI [0.0140, 0.0201] over 1435 document-family clusters.

Section 90 capture ratio — ALWAYS_ALL_RECONCILED -7.224, PAGE_CLASS_CHAMPION 0.269, TAVONEL router n/a (Phase B).

### Per page class (intersection cohort)

| page class | n | champion | champion loss | best single loss | oracle loss | headroom |
| --- | ---: | --- | ---: | ---: | ---: | ---: |
| `PPT2PDF|english|single_column` | 113 | `ovisocr2` | 0.0231 | 0.0231 | 0.0174 | 0.0058 |
| `research_report|simplified_chinese|single_column` | 112 | `ovisocr2` | 0.0981 | 0.0981 | 0.0904 | 0.0076 |
| `PPT2PDF|simplified_chinese|single_column` | 104 | `ovisocr2` | 0.0299 | 0.0299 | 0.0226 | 0.0073 |
| `book|english|single_column` | 101 | `ovisocr2` | 0.0513 | 0.0513 | 0.0365 | 0.0148 |
| `book|simplified_chinese|single_column` | 93 | `hpd_parsing` | 0.0929 | 0.0929 | 0.0777 | 0.0152 |
| `academic_literature|english|single_column` | 79 | `ovisocr2` | 0.1203 | 0.1203 | 0.1024 | 0.0179 |
| `newspaper|simplified_chinese|other_layout` | 74 | `ovisocr2` | 0.0448 | 0.0448 | 0.0276 | 0.0173 |
| `note|simplified_chinese|single_column` | 69 | `paddleocr_vl_1_6` | 0.0544 | 0.0544 | 0.0443 | 0.0101 |
| `academic_literature|english|1andmore_column` | 53 | `ovisocr2` | 0.0474 | 0.0474 | 0.0341 | 0.0133 |
| `magazine|english|other_layout` | 53 | `ovisocr2` | 0.0321 | 0.0321 | 0.0170 | 0.0151 |
| `note|en_ch_mixed|single_column` | 47 | `infinity_parser2_flash` | 0.0203 | 0.0203 | 0.0099 | 0.0104 |
| `newspaper|english|other_layout` | 45 | `ovisocr2` | 0.0385 | 0.0385 | 0.0247 | 0.0138 |
| `academic_literature|english|double_column` | 44 | `paddleocr_vl_1_6` | 0.0296 | 0.0296 | 0.0100 | 0.0196 |
| `colorful_textbook|simplified_chinese|single_column` | 40 | `ovisocr2` | 0.0430 | 0.0430 | 0.0303 | 0.0127 |
| `exam_paper|english|double_column` | 37 | `mineru_vlm` | 0.0238 | 0.0238 | 0.0147 | 0.0091 |
| `magazine|simplified_chinese|other_layout` | 32 | `hpd_parsing` | 0.0232 | 0.0232 | 0.0102 | 0.0129 |
| `newspaper|english|three_column` | 32 | `ovisocr2` | 0.0083 | 0.0083 | 0.0046 | 0.0037 |
| `exam_paper|simplified_chinese|double_column` | 31 | `ovisocr2` | 0.0424 | 0.0424 | 0.0311 | 0.0114 |
| `academic_literature|english|other_layout` | 28 | `ovisocr2` | 0.0683 | 0.0683 | 0.0518 | 0.0165 |
| `exam_paper|simplified_chinese|other_layout` | 27 | `hpd_parsing` | 0.1351 | 0.1351 | 0.1026 | 0.0325 |

## Surface `olmocr`

- unit is the PDF page, loss = share of that page's olmOCR-Bench tests that failed. Choosing a different model per test on the same page would be region splicing (section 35), so the plan chooses per page.
- tests per page range 2-40
- reconciler candidates resolved for 1403 units; 0 UNRESOLVED

### Cohort `intersection` (N = 1403 units)

| plan | n | mean loss | IRR proxy | hard fail (>0.05) | unresolved N/A | 95% CI |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `ORACLE_PERMITTED` | 1403 | 0.0615 | 0.9385 | 299 | 0 | [0.0540, 0.0699] |
| `PAGE_CLASS_CHAMPION` | 1403 | 0.1128 | 0.8872 | 476 | 0 | [0.1018, 0.1237] |
| `SINGLE:mineru_vlm` | 1403 | 0.1381 | 0.8619 | 550 | 0 | [0.1256, 0.1504] |
| `SINGLE:olmocr2` | 1403 | 0.1396 | 0.8604 | 570 | 0 | [0.1279, 0.1517] |
| `SINGLE:paddleocr_vl_1_6` | 1403 | 0.1468 | 0.8532 | 584 | 0 | [0.1330, 0.1608] |
| `SINGLE:deepseek_ocr2` | 1403 | 0.1636 | 0.8364 | 636 | 0 | [0.1499, 0.1776] |
| `ALWAYS_ALL_RECONCILED` | 1403 | 0.2077 | 0.7923 | 706 | 0 | [0.1935, 0.2217] |
| `SINGLE:mineru_pipeline` | 1403 | 0.2081 | 0.7919 | 758 | 0 | [0.1927, 0.2245] |
| `SINGLE:opus5_subscription` | 1403 | 0.2283 | 0.7717 | 731 | 0 | [0.2140, 0.2433] |
| `SINGLE:infinity_parser2_flash` | 1403 | 0.2295 | 0.7705 | 780 | 0 | [0.2154, 0.2439] |
| `SINGLE:ovisocr2` | 1403 | 0.2462 | 0.7538 | 771 | 0 | [0.2308, 0.2612] |
| `SINGLE:unlimited_ocr` | 1403 | 0.2483 | 0.7517 | 807 | 0 | [0.2339, 0.2635] |
| `SINGLE:monkeyocrv2_b` | 1403 | 0.2598 | 0.7402 | 860 | 0 | [0.2445, 0.2753] |
| `SINGLE:hpd_parsing` | 1403 | 0.2997 | 0.7003 | 917 | 0 | [0.2837, 0.3160] |
| `SINGLE:glm_ocr` | 1403 | 0.3627 | 0.6373 | 1048 | 0 | [0.3461, 0.3805] |

Best fixed single: `SINGLE:mineru_vlm`. Oracle headroom = 0.0766 absolute loss (55.5% relative), cluster-bootstrap 95% CI [0.0678, 0.0823] over 1367 document-family clusters.

Section 90 capture ratio — ALWAYS_ALL_RECONCILED -0.910, PAGE_CLASS_CHAMPION 0.330, TAVONEL router n/a (Phase B).

### Cohort `missing_as_failure` (N = 1403 units)

| plan | n | mean loss | IRR proxy | hard fail (>0.05) | unresolved N/A | 95% CI |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `ORACLE_PERMITTED` | 1403 | 0.0615 | 0.9385 | 299 | 0 | [0.0540, 0.0699] |
| `PAGE_CLASS_CHAMPION` | 1403 | 0.1128 | 0.8872 | 476 | 0 | [0.1018, 0.1237] |
| `SINGLE:mineru_vlm` | 1403 | 0.1381 | 0.8619 | 550 | 0 | [0.1256, 0.1504] |
| `SINGLE:olmocr2` | 1403 | 0.1396 | 0.8604 | 570 | 0 | [0.1279, 0.1517] |
| `SINGLE:paddleocr_vl_1_6` | 1403 | 0.1468 | 0.8532 | 584 | 0 | [0.1330, 0.1608] |
| `SINGLE:deepseek_ocr2` | 1403 | 0.1636 | 0.8364 | 636 | 0 | [0.1499, 0.1776] |
| `ALWAYS_ALL_RECONCILED` | 1403 | 0.2077 | 0.7923 | 706 | 0 | [0.1935, 0.2217] |
| `SINGLE:mineru_pipeline` | 1403 | 0.2081 | 0.7919 | 758 | 0 | [0.1927, 0.2245] |
| `SINGLE:opus5_subscription` | 1403 | 0.2283 | 0.7717 | 731 | 0 | [0.2140, 0.2433] |
| `SINGLE:infinity_parser2_flash` | 1403 | 0.2295 | 0.7705 | 780 | 0 | [0.2154, 0.2439] |
| `SINGLE:ovisocr2` | 1403 | 0.2462 | 0.7538 | 771 | 0 | [0.2308, 0.2612] |
| `SINGLE:unlimited_ocr` | 1403 | 0.2483 | 0.7517 | 807 | 0 | [0.2339, 0.2635] |
| `SINGLE:monkeyocrv2_b` | 1403 | 0.2598 | 0.7402 | 860 | 0 | [0.2445, 0.2753] |
| `SINGLE:hpd_parsing` | 1403 | 0.2997 | 0.7003 | 917 | 0 | [0.2837, 0.3160] |
| `SINGLE:glm_ocr` | 1403 | 0.3627 | 0.6373 | 1048 | 0 | [0.3461, 0.3805] |

Best fixed single: `SINGLE:mineru_vlm`. Oracle headroom = 0.0766 absolute loss (55.5% relative), cluster-bootstrap 95% CI [0.0678, 0.0823] over 1367 document-family clusters.

Section 90 capture ratio — ALWAYS_ALL_RECONCILED -0.910, PAGE_CLASS_CHAMPION 0.330, TAVONEL router n/a (Phase B).

### Per page class (intersection cohort)

| page class | n | champion | champion loss | best single loss | oracle loss | headroom |
| --- | ---: | --- | ---: | ---: | ---: | ---: |
| `arxiv_math.jsonl` | 522 | `opus5_subscription` | 0.0880 | 0.0880 | 0.0391 | 0.0489 |
| `headers_footers.jsonl` | 266 | `paddleocr_vl_1_6` | 0.0260 | 0.0260 | 0.0108 | 0.0152 |
| `multi_column.jsonl` | 231 | `olmocr2` | 0.1266 | 0.1266 | 0.0736 | 0.0530 |
| `table_tests.jsonl` | 188 | `mineru_vlm` | 0.1033 | 0.1033 | 0.0272 | 0.0761 |
| `old_scans.jsonl` | 98 | `olmocr2` | 0.4473 | 0.4473 | 0.3484 | 0.0989 |
| `long_tiny_text.jsonl` | 62 | `unlimited_ocr` | 0.1057 | 0.1057 | 0.0510 | 0.0547 |
| `old_scans_math.jsonl` | 36 | `opus5_subscription` | 0.1761 | 0.1761 | 0.0988 | 0.0773 |

## Surface `parsebench:table`

- per-example loss = 1 - teds
- reconciler candidates resolved for 2078 units; 0 UNRESOLVED

### Cohort `intersection` (N = 495 units)

| plan | n | mean loss | IRR proxy | hard fail (>0.05) | unresolved N/A | 95% CI |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `ORACLE_PERMITTED` | 495 | 0.0875 | 0.9125 | 224 | 0 | [0.0647, 0.1120] |
| `SINGLE:opus5_subscription` | 495 | 0.1834 | 0.8166 | 353 | 0 | [0.1504, 0.2104] |
| `PAGE_CLASS_CHAMPION` | 495 | 0.1834 | 0.8166 | 353 | 0 | [0.1504, 0.2104] |
| `SINGLE:ovisocr2` | 495 | 0.2018 | 0.7982 | 406 | 0 | [0.1673, 0.2272] |
| `ALWAYS_ALL_RECONCILED` | 495 | 0.2117 | 0.7883 | 402 | 0 | [0.1671, 0.2420] |
| `SINGLE:mineru_vlm` | 495 | 0.2139 | 0.7861 | 401 | 0 | [0.1717, 0.2430] |
| `SINGLE:hpd_parsing` | 495 | 0.2366 | 0.7634 | 416 | 0 | [0.1943, 0.2645] |
| `SINGLE:unlimited_ocr` | 495 | 0.2479 | 0.7521 | 412 | 0 | [0.1959, 0.2796] |
| `SINGLE:infinity_parser2_flash` | 495 | 0.2536 | 0.7464 | 402 | 0 | [0.1970, 0.2920] |
| `SINGLE:olmocr2` | 495 | 0.2605 | 0.7395 | 343 | 0 | [0.2203, 0.2907] |
| `SINGLE:paddleocr_vl_1_6` | 495 | 0.2640 | 0.7360 | 420 | 0 | [0.2059, 0.2980] |
| `SINGLE:deepseek_ocr2` | 495 | 0.2951 | 0.7049 | 437 | 0 | [0.2414, 0.3278] |
| `SINGLE:monkeyocrv2_b` | 495 | 0.3003 | 0.6997 | 417 | 0 | [0.2287, 0.3449] |
| `SINGLE:mineru_pipeline` | 495 | 0.3544 | 0.6456 | 454 | 0 | [0.3130, 0.3820] |
| `SINGLE:glm_ocr` | 495 | 0.7079 | 0.2921 | 465 | 0 | [0.6342, 0.7573] |

Best fixed single: `SINGLE:opus5_subscription`. Oracle headroom = 0.0958 absolute loss (52.3% relative), cluster-bootstrap 95% CI [0.0820, 0.1086] over 93 document-family clusters.

Section 90 capture ratio — ALWAYS_ALL_RECONCILED -0.295, PAGE_CLASS_CHAMPION 0.000, TAVONEL router n/a (Phase B).

### Cohort `missing_as_failure` (N = 503 units)

| plan | n | mean loss | IRR proxy | hard fail (>0.05) | unresolved N/A | 95% CI |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `ORACLE_PERMITTED` | 503 | 0.0876 | 0.9124 | 228 | 0 | [0.0648, 0.1108] |
| `SINGLE:opus5_subscription` | 503 | 0.1839 | 0.8161 | 358 | 0 | [0.1515, 0.2128] |
| `PAGE_CLASS_CHAMPION` | 503 | 0.1839 | 0.8161 | 358 | 0 | [0.1515, 0.2128] |
| `SINGLE:ovisocr2` | 503 | 0.2015 | 0.7985 | 411 | 0 | [0.1699, 0.2260] |
| `ALWAYS_ALL_RECONCILED` | 503 | 0.2117 | 0.7883 | 407 | 0 | [0.1692, 0.2418] |
| `SINGLE:mineru_vlm` | 503 | 0.2137 | 0.7863 | 407 | 0 | [0.1735, 0.2414] |
| `SINGLE:hpd_parsing` | 503 | 0.2397 | 0.7603 | 423 | 0 | [0.1968, 0.2694] |
| `SINGLE:unlimited_ocr` | 503 | 0.2528 | 0.7472 | 420 | 0 | [0.2031, 0.2826] |
| `SINGLE:infinity_parser2_flash` | 503 | 0.2606 | 0.7394 | 409 | 0 | [0.2022, 0.2968] |
| `SINGLE:paddleocr_vl_1_6` | 503 | 0.2650 | 0.7350 | 426 | 0 | [0.2087, 0.2990] |
| `SINGLE:olmocr2` | 503 | 0.2667 | 0.7333 | 351 | 0 | [0.2249, 0.3034] |
| `SINGLE:monkeyocrv2_b` | 503 | 0.3012 | 0.6988 | 423 | 0 | [0.2320, 0.3466] |
| `SINGLE:deepseek_ocr2` | 503 | 0.3031 | 0.6969 | 445 | 0 | [0.2505, 0.3360] |
| `SINGLE:mineru_pipeline` | 503 | 0.3593 | 0.6407 | 462 | 0 | [0.3183, 0.3898] |
| `SINGLE:glm_ocr` | 503 | 0.7077 | 0.2923 | 473 | 0 | [0.6310, 0.7570] |

Best fixed single: `SINGLE:opus5_subscription`. Oracle headroom = 0.0963 absolute loss (52.4% relative), cluster-bootstrap 95% CI [0.0797, 0.1101] over 94 document-family clusters.

Section 90 capture ratio — ALWAYS_ALL_RECONCILED -0.289, PAGE_CLASS_CHAMPION 0.000, TAVONEL router n/a (Phase B).

### Per page class (intersection cohort)

| page class | n | champion | champion loss | best single loss | oracle loss | headroom |
| --- | ---: | --- | ---: | ---: | ---: | ---: |
| `table,easy` | 424 | `opus5_subscription` | 0.1782 | 0.1782 | 0.0836 | 0.0946 |
| `table,hard` | 71 | `opus5_subscription` | 0.2141 | 0.2141 | 0.1108 | 0.1033 |

## Surface `parsebench:chart`

- per-example loss = 1 - rule_pass_rate
- reconciler candidates resolved for 2078 units; 0 UNRESOLVED

### Cohort `intersection` (N = 568 units)

| plan | n | mean loss | IRR proxy | hard fail (>0.05) | unresolved N/A | 95% CI |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `ORACLE_PERMITTED` | 568 | 0.3383 | 0.6617 | 320 | 0 | [0.2549, 0.4117] |
| `PAGE_CLASS_CHAMPION` | 568 | 0.3847 | 0.6153 | 347 | 0 | [0.3119, 0.4489] |
| `SINGLE:mineru_vlm` | 568 | 0.3952 | 0.6048 | 357 | 0 | [0.3161, 0.4609] |
| `SINGLE:opus5_subscription` | 568 | 0.6930 | 0.3070 | 416 | 0 | [0.5768, 0.7924] |
| `SINGLE:olmocr2` | 568 | 0.8795 | 0.1205 | 515 | 0 | [0.8012, 0.9432] |
| `SINGLE:unlimited_ocr` | 568 | 0.9860 | 0.0140 | 563 | 0 | [0.9726, 0.9966] |
| `SINGLE:hpd_parsing` | 568 | 0.9879 | 0.0121 | 563 | 0 | [0.9760, 0.9964] |
| `SINGLE:deepseek_ocr2` | 568 | 0.9900 | 0.0100 | 564 | 0 | [0.9787, 0.9981] |
| `SINGLE:ovisocr2` | 568 | 0.9902 | 0.0098 | 564 | 0 | [0.9795, 0.9983] |
| `SINGLE:paddleocr_vl_1_6` | 568 | 0.9910 | 0.0090 | 564 | 0 | [0.9804, 0.9983] |
| `SINGLE:infinity_parser2_flash` | 568 | 0.9916 | 0.0084 | 564 | 0 | [0.9808, 0.9986] |
| `SINGLE:mineru_pipeline` | 568 | 0.9921 | 0.0079 | 564 | 0 | [0.9818, 0.9991] |
| `ALWAYS_ALL_RECONCILED` | 568 | 0.9921 | 0.0079 | 564 | 0 | [0.9818, 0.9991] |
| `SINGLE:monkeyocrv2_b` | 568 | 0.9925 | 0.0075 | 565 | 0 | [0.9830, 0.9991] |
| `SINGLE:glm_ocr` | 568 | 0.9965 | 0.0035 | 566 | 0 | [0.9906, 1.0000] |

Best fixed single: `SINGLE:mineru_vlm`. Oracle headroom = 0.0569 absolute loss (14.4% relative), cluster-bootstrap 95% CI [0.0351, 0.0867] over 99 document-family clusters.

Section 90 capture ratio — ALWAYS_ALL_RECONCILED -10.489, PAGE_CLASS_CHAMPION 0.184, TAVONEL router n/a (Phase B).

### Cohort `missing_as_failure` (N = 568 units)

| plan | n | mean loss | IRR proxy | hard fail (>0.05) | unresolved N/A | 95% CI |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `ORACLE_PERMITTED` | 568 | 0.3383 | 0.6617 | 320 | 0 | [0.2549, 0.4117] |
| `PAGE_CLASS_CHAMPION` | 568 | 0.3847 | 0.6153 | 347 | 0 | [0.3119, 0.4489] |
| `SINGLE:mineru_vlm` | 568 | 0.3952 | 0.6048 | 357 | 0 | [0.3161, 0.4609] |
| `SINGLE:opus5_subscription` | 568 | 0.6930 | 0.3070 | 416 | 0 | [0.5768, 0.7924] |
| `SINGLE:olmocr2` | 568 | 0.8795 | 0.1205 | 515 | 0 | [0.8012, 0.9432] |
| `SINGLE:unlimited_ocr` | 568 | 0.9860 | 0.0140 | 563 | 0 | [0.9726, 0.9966] |
| `SINGLE:hpd_parsing` | 568 | 0.9879 | 0.0121 | 563 | 0 | [0.9760, 0.9964] |
| `SINGLE:deepseek_ocr2` | 568 | 0.9900 | 0.0100 | 564 | 0 | [0.9787, 0.9981] |
| `SINGLE:ovisocr2` | 568 | 0.9902 | 0.0098 | 564 | 0 | [0.9795, 0.9983] |
| `SINGLE:paddleocr_vl_1_6` | 568 | 0.9910 | 0.0090 | 564 | 0 | [0.9804, 0.9983] |
| `SINGLE:infinity_parser2_flash` | 568 | 0.9916 | 0.0084 | 564 | 0 | [0.9808, 0.9986] |
| `SINGLE:mineru_pipeline` | 568 | 0.9921 | 0.0079 | 564 | 0 | [0.9818, 0.9991] |
| `ALWAYS_ALL_RECONCILED` | 568 | 0.9921 | 0.0079 | 564 | 0 | [0.9818, 0.9991] |
| `SINGLE:monkeyocrv2_b` | 568 | 0.9925 | 0.0075 | 565 | 0 | [0.9830, 0.9991] |
| `SINGLE:glm_ocr` | 568 | 0.9965 | 0.0035 | 566 | 0 | [0.9906, 1.0000] |

Best fixed single: `SINGLE:mineru_vlm`. Oracle headroom = 0.0569 absolute loss (14.4% relative), cluster-bootstrap 95% CI [0.0351, 0.0867] over 99 document-family clusters.

Section 90 capture ratio — ALWAYS_ALL_RECONCILED -10.489, PAGE_CLASS_CHAMPION 0.184, TAVONEL router n/a (Phase B).

### Per page class (intersection cohort)

| page class | n | champion | champion loss | best single loss | oracle loss | headroom |
| --- | ---: | --- | ---: | ---: | ---: | ---: |
| `chart,need_estimate` | 309 | `mineru_vlm` | 0.4110 | 0.4110 | 0.4026 | 0.0084 |
| `chart` | 188 | `opus5_subscription` | 0.1881 | 0.1881 | 0.0649 | 0.1232 |
| `chart,3d_chart,need_estimate` | 68 | `mineru_vlm` | 0.8034 | 0.8034 | 0.7946 | 0.0088 |
| `chart,3d_chart` | 3 | `mineru_vlm` | 0.5000 | 0.5000 | 0.5000 | 0.0000 |

## Surface `parsebench:text_content`

- per-example loss = 1 - rule_pass_rate
- reconciler candidates resolved for 2078 units; 0 UNRESOLVED

### Cohort `intersection` (N = 506 units)

| plan | n | mean loss | IRR proxy | hard fail (>0.05) | unresolved N/A | 95% CI |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `ORACLE_PERMITTED` | 506 | 0.0708 | 0.9292 | 163 | 0 | [0.0597, 0.0834] |
| `PAGE_CLASS_CHAMPION` | 506 | 0.0824 | 0.9176 | 193 | 0 | [0.0708, 0.0955] |
| `SINGLE:opus5_subscription` | 506 | 0.0886 | 0.9114 | 202 | 0 | [0.0756, 0.1033] |
| `ALWAYS_ALL_RECONCILED` | 506 | 0.0955 | 0.9045 | 213 | 0 | [0.0824, 0.1101] |
| `SINGLE:ovisocr2` | 506 | 0.1188 | 0.8812 | 221 | 0 | [0.1017, 0.1388] |
| `SINGLE:infinity_parser2_flash` | 506 | 0.1205 | 0.8795 | 242 | 0 | [0.1047, 0.1389] |
| `SINGLE:unlimited_ocr` | 506 | 0.1288 | 0.8712 | 249 | 0 | [0.1111, 0.1491] |
| `SINGLE:glm_ocr` | 506 | 0.1392 | 0.8608 | 277 | 0 | [0.1222, 0.1599] |
| `SINGLE:monkeyocrv2_b` | 506 | 0.1459 | 0.8541 | 277 | 0 | [0.1269, 0.1658] |
| `SINGLE:mineru_vlm` | 506 | 0.1531 | 0.8469 | 328 | 0 | [0.1368, 0.1710] |
| `SINGLE:paddleocr_vl_1_6` | 506 | 0.1672 | 0.8328 | 345 | 0 | [0.1500, 0.1870] |
| `SINGLE:olmocr2` | 506 | 0.1704 | 0.8296 | 334 | 0 | [0.1516, 0.1911] |
| `SINGLE:hpd_parsing` | 506 | 0.1735 | 0.8265 | 297 | 0 | [0.1542, 0.1963] |
| `SINGLE:deepseek_ocr2` | 506 | 0.1775 | 0.8225 | 351 | 0 | [0.1586, 0.1985] |
| `SINGLE:mineru_pipeline` | 506 | 0.2145 | 0.7855 | 380 | 0 | [0.1934, 0.2391] |

Best fixed single: `SINGLE:opus5_subscription`. Oracle headroom = 0.0178 absolute loss (20.1% relative), cluster-bootstrap 95% CI [0.0119, 0.0252] over 506 document-family clusters.

Section 90 capture ratio — ALWAYS_ALL_RECONCILED -0.390, PAGE_CLASS_CHAMPION 0.350, TAVONEL router n/a (Phase B).

### Cohort `missing_as_failure` (N = 506 units)

| plan | n | mean loss | IRR proxy | hard fail (>0.05) | unresolved N/A | 95% CI |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `ORACLE_PERMITTED` | 506 | 0.0708 | 0.9292 | 163 | 0 | [0.0597, 0.0834] |
| `PAGE_CLASS_CHAMPION` | 506 | 0.0824 | 0.9176 | 193 | 0 | [0.0708, 0.0955] |
| `SINGLE:opus5_subscription` | 506 | 0.0886 | 0.9114 | 202 | 0 | [0.0756, 0.1033] |
| `ALWAYS_ALL_RECONCILED` | 506 | 0.0955 | 0.9045 | 213 | 0 | [0.0824, 0.1101] |
| `SINGLE:ovisocr2` | 506 | 0.1188 | 0.8812 | 221 | 0 | [0.1017, 0.1388] |
| `SINGLE:infinity_parser2_flash` | 506 | 0.1205 | 0.8795 | 242 | 0 | [0.1047, 0.1389] |
| `SINGLE:unlimited_ocr` | 506 | 0.1288 | 0.8712 | 249 | 0 | [0.1111, 0.1491] |
| `SINGLE:glm_ocr` | 506 | 0.1392 | 0.8608 | 277 | 0 | [0.1222, 0.1599] |
| `SINGLE:monkeyocrv2_b` | 506 | 0.1459 | 0.8541 | 277 | 0 | [0.1269, 0.1658] |
| `SINGLE:mineru_vlm` | 506 | 0.1531 | 0.8469 | 328 | 0 | [0.1368, 0.1710] |
| `SINGLE:paddleocr_vl_1_6` | 506 | 0.1672 | 0.8328 | 345 | 0 | [0.1500, 0.1870] |
| `SINGLE:olmocr2` | 506 | 0.1704 | 0.8296 | 334 | 0 | [0.1516, 0.1911] |
| `SINGLE:hpd_parsing` | 506 | 0.1735 | 0.8265 | 297 | 0 | [0.1542, 0.1963] |
| `SINGLE:deepseek_ocr2` | 506 | 0.1775 | 0.8225 | 351 | 0 | [0.1586, 0.1985] |
| `SINGLE:mineru_pipeline` | 506 | 0.2145 | 0.7855 | 380 | 0 | [0.1934, 0.2391] |

Best fixed single: `SINGLE:opus5_subscription`. Oracle headroom = 0.0178 absolute loss (20.1% relative), cluster-bootstrap 95% CI [0.0119, 0.0252] over 506 document-family clusters.

Section 90 capture ratio — ALWAYS_ALL_RECONCILED -0.390, PAGE_CLASS_CHAMPION 0.350, TAVONEL router n/a (Phase B).

### Per page class (intersection cohort)

| page class | n | champion | champion loss | best single loss | oracle loss | headroom |
| --- | ---: | --- | ---: | ---: | ---: | ---: |
| `text_content,simple,easy` | 156 | `ovisocr2` | 0.0337 | 0.0337 | 0.0254 | 0.0083 |
| `text_content,multicolumns,easy` | 84 | `ovisocr2` | 0.0483 | 0.0483 | 0.0361 | 0.0123 |
| `text_content,ocr,easy` | 60 | `opus5_subscription` | 0.0730 | 0.0730 | 0.0634 | 0.0096 |
| `text_content,ocr,hard` | 58 | `opus5_subscription` | 0.0923 | 0.0923 | 0.0820 | 0.0103 |
| `text_content,multilang,easy` | 45 | `opus5_subscription` | 0.2192 | 0.2192 | 0.2107 | 0.0085 |
| `text_content,misc,hard` | 24 | `opus5_subscription` | 0.1471 | 0.1471 | 0.1077 | 0.0394 |
| `text_content,dense,hard` | 14 | `monkeyocrv2_b` | 0.1019 | 0.1019 | 0.0697 | 0.0322 |
| `text_content,simple,hard` | 13 | `ovisocr2` | 0.1164 | 0.1164 | 0.0937 | 0.0227 |
| `text_content,handwritting,hard` | 12 | `opus5_subscription` | 0.1881 | 0.1881 | 0.1870 | 0.0011 |
| `text_content,multicolumns,hard` | 12 | `opus5_subscription` | 0.0611 | 0.0611 | 0.0546 | 0.0064 |
| `text_content,sparse,easy` | 12 | `ovisocr2` | 0.1109 | 0.1109 | 0.1055 | 0.0054 |
| `text_content,misc,easy` | 9 | `opus5_subscription` | 0.0566 | 0.0566 | 0.0421 | 0.0146 |
| `text_content,handwritting,easy` | 1 | `opus5_subscription` | 0.1387 | 0.1387 | 0.1387 | 0.0000 |
| `text_content,multicolumns,hard,easy` | 1 | `ovisocr2` | 0.1444 | 0.1444 | 0.1444 | 0.0000 |
| `text_content,multilang,easy,hard` | 1 | `opus5_subscription` | 0.7537 | 0.7537 | 0.7537 | 0.0000 |
| `text_content,multilang,hard` | 1 | `opus5_subscription` | 0.2990 | 0.2990 | 0.2990 | 0.0000 |
| `text_content,ocr,easy,hard` | 1 | `opus5_subscription` | 0.0121 | 0.0121 | 0.0121 | 0.0000 |
| `text_content,simple,easy,hard` | 1 | `unlimited_ocr` | 0.0390 | 0.0390 | 0.0390 | 0.0000 |
| `text_content,sparse,hard` | 1 | `monkeyocrv2_b` | 0.0667 | 0.0667 | 0.0667 | 0.0000 |

## Surface `parsebench:text_formatting`

- per-example loss = 1 - rule_pass_rate
- reconciler candidates resolved for 2078 units; 0 UNRESOLVED

### Cohort `intersection` (N = 476 units)

| plan | n | mean loss | IRR proxy | hard fail (>0.05) | unresolved N/A | 95% CI |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `ORACLE_PERMITTED` | 476 | 0.2163 | 0.7837 | 285 | 0 | [0.1943, 0.2382] |
| `PAGE_CLASS_CHAMPION` | 476 | 0.2579 | 0.7421 | 303 | 0 | [0.2318, 0.2831] |
| `SINGLE:opus5_subscription` | 476 | 0.2579 | 0.7421 | 303 | 0 | [0.2318, 0.2831] |
| `SINGLE:mineru_vlm` | 476 | 0.6215 | 0.3785 | 434 | 0 | [0.5926, 0.6492] |
| `SINGLE:monkeyocrv2_b` | 476 | 0.6421 | 0.3579 | 439 | 0 | [0.6125, 0.6710] |
| `SINGLE:hpd_parsing` | 476 | 0.6541 | 0.3459 | 435 | 0 | [0.6263, 0.6840] |
| `SINGLE:paddleocr_vl_1_6` | 476 | 0.6662 | 0.3338 | 439 | 0 | [0.6385, 0.6954] |
| `SINGLE:glm_ocr` | 476 | 0.6675 | 0.3325 | 440 | 0 | [0.6382, 0.6963] |
| `ALWAYS_ALL_RECONCILED` | 476 | 0.6697 | 0.3303 | 427 | 0 | [0.6392, 0.7016] |
| `SINGLE:deepseek_ocr2` | 476 | 0.6781 | 0.3219 | 441 | 0 | [0.6489, 0.7071] |
| `SINGLE:mineru_pipeline` | 476 | 0.6978 | 0.3022 | 446 | 0 | [0.6703, 0.7254] |
| `SINGLE:ovisocr2` | 476 | 0.7151 | 0.2849 | 443 | 0 | [0.6861, 0.7435] |
| `SINGLE:infinity_parser2_flash` | 476 | 0.7299 | 0.2701 | 444 | 0 | [0.6986, 0.7630] |
| `SINGLE:olmocr2` | 476 | 0.9799 | 0.0201 | 474 | 0 | [0.9697, 0.9882] |
| `SINGLE:unlimited_ocr` | 476 | 0.9954 | 0.0046 | 475 | 0 | [0.9895, 0.9992] |

Best fixed single: `SINGLE:opus5_subscription`. Oracle headroom = 0.0416 absolute loss (16.1% relative), cluster-bootstrap 95% CI [0.0288, 0.0554] over 476 document-family clusters.

Section 90 capture ratio — ALWAYS_ALL_RECONCILED -9.904, PAGE_CLASS_CHAMPION 0.001, TAVONEL router n/a (Phase B).

### Cohort `missing_as_failure` (N = 476 units)

| plan | n | mean loss | IRR proxy | hard fail (>0.05) | unresolved N/A | 95% CI |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `ORACLE_PERMITTED` | 476 | 0.2163 | 0.7837 | 285 | 0 | [0.1943, 0.2382] |
| `PAGE_CLASS_CHAMPION` | 476 | 0.2579 | 0.7421 | 303 | 0 | [0.2318, 0.2831] |
| `SINGLE:opus5_subscription` | 476 | 0.2579 | 0.7421 | 303 | 0 | [0.2318, 0.2831] |
| `SINGLE:mineru_vlm` | 476 | 0.6215 | 0.3785 | 434 | 0 | [0.5926, 0.6492] |
| `SINGLE:monkeyocrv2_b` | 476 | 0.6421 | 0.3579 | 439 | 0 | [0.6125, 0.6710] |
| `SINGLE:hpd_parsing` | 476 | 0.6541 | 0.3459 | 435 | 0 | [0.6263, 0.6840] |
| `SINGLE:paddleocr_vl_1_6` | 476 | 0.6662 | 0.3338 | 439 | 0 | [0.6385, 0.6954] |
| `SINGLE:glm_ocr` | 476 | 0.6675 | 0.3325 | 440 | 0 | [0.6382, 0.6963] |
| `ALWAYS_ALL_RECONCILED` | 476 | 0.6697 | 0.3303 | 427 | 0 | [0.6392, 0.7016] |
| `SINGLE:deepseek_ocr2` | 476 | 0.6781 | 0.3219 | 441 | 0 | [0.6489, 0.7071] |
| `SINGLE:mineru_pipeline` | 476 | 0.6978 | 0.3022 | 446 | 0 | [0.6703, 0.7254] |
| `SINGLE:ovisocr2` | 476 | 0.7151 | 0.2849 | 443 | 0 | [0.6861, 0.7435] |
| `SINGLE:infinity_parser2_flash` | 476 | 0.7299 | 0.2701 | 444 | 0 | [0.6986, 0.7630] |
| `SINGLE:olmocr2` | 476 | 0.9799 | 0.0201 | 474 | 0 | [0.9697, 0.9882] |
| `SINGLE:unlimited_ocr` | 476 | 0.9954 | 0.0046 | 475 | 0 | [0.9895, 0.9992] |

Best fixed single: `SINGLE:opus5_subscription`. Oracle headroom = 0.0416 absolute loss (16.1% relative), cluster-bootstrap 95% CI [0.0288, 0.0554] over 476 document-family clusters.

Section 90 capture ratio — ALWAYS_ALL_RECONCILED -9.904, PAGE_CLASS_CHAMPION 0.001, TAVONEL router n/a (Phase B).

### Per page class (intersection cohort)

| page class | n | champion | champion loss | best single loss | oracle loss | headroom |
| --- | ---: | --- | ---: | ---: | ---: | ---: |
| `text_formatting,simple,easy` | 152 | `opus5_subscription` | 0.2371 | 0.2371 | 0.1934 | 0.0436 |
| `text_formatting,multicolumns,easy` | 84 | `opus5_subscription` | 0.1985 | 0.1985 | 0.1662 | 0.0323 |
| `text_formatting,ocr,easy` | 55 | `opus5_subscription` | 0.2863 | 0.2863 | 0.2275 | 0.0588 |
| `text_formatting,ocr,hard` | 52 | `opus5_subscription` | 0.3187 | 0.3187 | 0.2643 | 0.0544 |
| `text_formatting,multilang,easy` | 43 | `opus5_subscription` | 0.2643 | 0.2643 | 0.2288 | 0.0355 |
| `text_formatting,misc,hard` | 20 | `opus5_subscription` | 0.3165 | 0.3165 | 0.2864 | 0.0301 |
| `text_formatting,dense,hard` | 12 | `opus5_subscription` | 0.4429 | 0.4429 | 0.3944 | 0.0485 |
| `text_formatting,handwritting,hard` | 11 | `opus5_subscription` | 0.4515 | 0.4515 | 0.4164 | 0.0350 |
| `text_formatting,multicolumns,hard` | 11 | `opus5_subscription` | 0.1274 | 0.1274 | 0.1274 | 0.0000 |
| `text_formatting,simple,hard` | 11 | `opus5_subscription` | 0.2561 | 0.2561 | 0.2561 | 0.0000 |
| `text_formatting,sparse,easy` | 10 | `opus5_subscription` | 0.1701 | 0.1701 | 0.0534 | 0.1167 |
| `text_formatting,misc,easy` | 9 | `opus5_subscription` | 0.2867 | 0.2867 | 0.2744 | 0.0123 |
| `text_formatting,multicolumns,hard,easy` | 1 | `opus5_subscription` | 0.0571 | 0.0571 | 0.0571 | 0.0000 |
| `text_formatting,multilang,easy,hard` | 1 | `opus5_subscription` | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| `text_formatting,multilang,hard` | 1 | `opus5_subscription` | 0.3387 | 0.3387 | 0.3387 | 0.0000 |
| `text_formatting,ocr,easy,hard` | 1 | `monkeyocrv2_b` | 0.3000 | 0.3000 | 0.3000 | 0.0000 |
| `text_formatting,simple,easy,hard` | 1 | `opus5_subscription` | 0.5455 | 0.5455 | 0.5455 | 0.0000 |
| `text_formatting,sparse,hard` | 1 | `opus5_subscription` | 0.0000 | 0.0000 | 0.0000 | 0.0000 |

## Appendix B — complementarity (OmniDoc composite, tau = 0.05)

| primary | peer | n primary wrong | rescue P(peer ok \| primary wrong) | 95% CI | joint fail |
| --- | --- | ---: | ---: | --- | ---: |
| `deepseek_ocr2` | `ovisocr2` | 703 | 0.3770 | [0.3442, 0.4142] | 0.6230 |
| `deepseek_ocr2` | `hpd_parsing` | 703 | 0.3129 | [0.2731, 0.3413] | 0.6871 |
| `deepseek_ocr2` | `paddleocr_vl_1_6` | 703 | 0.3001 | [0.2640, 0.3343] | 0.6999 |
| `deepseek_ocr2` | `mineru_vlm` | 703 | 0.2945 | [0.2609, 0.3286] | 0.7055 |
| `deepseek_ocr2` | `monkeyocrv2_b` | 703 | 0.2404 | [0.2104, 0.2749] | 0.7596 |
| `deepseek_ocr2` | `infinity_parser2_flash` | 703 | 0.2262 | [0.1918, 0.2566] | 0.7738 |
| `deepseek_ocr2` | `opus5_subscription` | 703 | 0.1991 | [0.1717, 0.2295] | 0.8009 |
| `deepseek_ocr2` | `glm_ocr` | 703 | 0.1607 | [0.1279, 0.1912] | 0.8393 |
| `deepseek_ocr2` | `mineru_pipeline` | 703 | 0.1579 | [0.1322, 0.1874] | 0.8421 |
| `glm_ocr` | `ovisocr2` | 901 | 0.5327 | [0.4989, 0.5670] | 0.4673 |
| `glm_ocr` | `hpd_parsing` | 901 | 0.4451 | [0.4146, 0.4772] | 0.5549 |
| `glm_ocr` | `mineru_vlm` | 901 | 0.4295 | [0.3943, 0.4581] | 0.5705 |
| `glm_ocr` | `paddleocr_vl_1_6` | 901 | 0.4040 | [0.3709, 0.4323] | 0.5960 |
| `glm_ocr` | `monkeyocrv2_b` | 901 | 0.3729 | [0.3403, 0.4049] | 0.6271 |
| `glm_ocr` | `deepseek_ocr2` | 901 | 0.3452 | [0.3140, 0.3762] | 0.6548 |
| `glm_ocr` | `infinity_parser2_flash` | 901 | 0.3418 | [0.3139, 0.3754] | 0.6582 |
| `glm_ocr` | `opus5_subscription` | 901 | 0.2686 | [0.2379, 0.2999] | 0.7314 |
| `glm_ocr` | `mineru_pipeline` | 901 | 0.2320 | [0.2059, 0.2586] | 0.7680 |
| `hpd_parsing` | `ovisocr2` | 561 | 0.2674 | [0.2327, 0.3044] | 0.7326 |
| `hpd_parsing` | `paddleocr_vl_1_6` | 561 | 0.2032 | [0.1731, 0.2360] | 0.7968 |
| `hpd_parsing` | `mineru_vlm` | 561 | 0.1533 | [0.1216, 0.1882] | 0.8467 |
| `hpd_parsing` | `deepseek_ocr2` | 561 | 0.1390 | [0.1095, 0.1679] | 0.8610 |
| `hpd_parsing` | `opus5_subscription` | 561 | 0.1355 | [0.1077, 0.1615] | 0.8645 |
| `hpd_parsing` | `mineru_pipeline` | 561 | 0.1176 | [0.0921, 0.1416] | 0.8824 |
| `hpd_parsing` | `monkeyocrv2_b` | 561 | 0.1176 | [0.0904, 0.1459] | 0.8824 |
| `hpd_parsing` | `infinity_parser2_flash` | 561 | 0.1159 | [0.0891, 0.1436] | 0.8841 |
| `hpd_parsing` | `glm_ocr` | 561 | 0.1087 | [0.0797, 0.1367] | 0.8913 |
| `infinity_parser2_flash` | `ovisocr2` | 668 | 0.3653 | [0.3307, 0.4064] | 0.6347 |
| `infinity_parser2_flash` | `paddleocr_vl_1_6` | 668 | 0.2889 | [0.2557, 0.3238] | 0.7111 |
| `infinity_parser2_flash` | `hpd_parsing` | 668 | 0.2575 | [0.2234, 0.2920] | 0.7425 |
| `infinity_parser2_flash` | `mineru_vlm` | 668 | 0.2545 | [0.2234, 0.2908] | 0.7455 |
| `infinity_parser2_flash` | `deepseek_ocr2` | 668 | 0.1856 | [0.1597, 0.2171] | 0.8144 |
| `infinity_parser2_flash` | `monkeyocrv2_b` | 668 | 0.1841 | [0.1586, 0.2135] | 0.8159 |
| `infinity_parser2_flash` | `opus5_subscription` | 668 | 0.1527 | [0.1215, 0.1851] | 0.8473 |
| `infinity_parser2_flash` | `mineru_pipeline` | 668 | 0.1377 | [0.1121, 0.1639] | 0.8623 |
| `infinity_parser2_flash` | `glm_ocr` | 668 | 0.1123 | [0.0868, 0.1388] | 0.8877 |
| `mineru_pipeline` | `ovisocr2` | 847 | 0.4864 | [0.4536, 0.5181] | 0.5136 |
| `mineru_pipeline` | `hpd_parsing` | 847 | 0.4156 | [0.3817, 0.4485] | 0.5844 |
| `mineru_pipeline` | `paddleocr_vl_1_6` | 847 | 0.3955 | [0.3642, 0.4279] | 0.6045 |
| `mineru_pipeline` | `mineru_vlm` | 847 | 0.3849 | [0.3529, 0.4173] | 0.6151 |
| `mineru_pipeline` | `monkeyocrv2_b` | 847 | 0.3377 | [0.3061, 0.3676] | 0.6623 |
| `mineru_pipeline` | `infinity_parser2_flash` | 847 | 0.3200 | [0.2882, 0.3523] | 0.6800 |
| `mineru_pipeline` | `deepseek_ocr2` | 847 | 0.3011 | [0.2686, 0.3333] | 0.6989 |
| `mineru_pipeline` | `opus5_subscription` | 847 | 0.2161 | [0.1874, 0.2456] | 0.7839 |
| `mineru_pipeline` | `glm_ocr` | 847 | 0.1830 | [0.1560, 0.2121] | 0.8170 |
| `mineru_vlm` | `ovisocr2` | 603 | 0.3151 | [0.2731, 0.3561] | 0.6849 |
| `mineru_vlm` | `paddleocr_vl_1_6` | 603 | 0.2156 | [0.1836, 0.2516] | 0.7844 |
| `mineru_vlm` | `hpd_parsing` | 603 | 0.2123 | [0.1823, 0.2429] | 0.7877 |
| `mineru_vlm` | `monkeyocrv2_b` | 603 | 0.1808 | [0.1500, 0.2139] | 0.8192 |
| `mineru_vlm` | `deepseek_ocr2` | 603 | 0.1774 | [0.1474, 0.2070] | 0.8226 |
| `mineru_vlm` | `infinity_parser2_flash` | 603 | 0.1741 | [0.1452, 0.2045] | 0.8259 |
| `mineru_vlm` | `opus5_subscription` | 603 | 0.1592 | [0.1316, 0.1893] | 0.8408 |
| `mineru_vlm` | `glm_ocr` | 603 | 0.1476 | [0.1198, 0.1765] | 0.8524 |
| `mineru_vlm` | `mineru_pipeline` | 603 | 0.1360 | [0.1100, 0.1625] | 0.8640 |
| `monkeyocrv2_b` | `ovisocr2` | 657 | 0.3546 | [0.3184, 0.3940] | 0.6454 |
| `monkeyocrv2_b` | `paddleocr_vl_1_6` | 657 | 0.2816 | [0.2458, 0.3126] | 0.7184 |
| `monkeyocrv2_b` | `mineru_vlm` | 657 | 0.2481 | [0.2165, 0.2796] | 0.7519 |
| `monkeyocrv2_b` | `hpd_parsing` | 657 | 0.2466 | [0.2095, 0.2796] | 0.7534 |
| `monkeyocrv2_b` | `opus5_subscription` | 657 | 0.1903 | [0.1589, 0.2210] | 0.8097 |
| `monkeyocrv2_b` | `deepseek_ocr2` | 657 | 0.1872 | [0.1582, 0.2167] | 0.8128 |
| `monkeyocrv2_b` | `infinity_parser2_flash` | 657 | 0.1705 | [0.1406, 0.2056] | 0.8295 |
| `monkeyocrv2_b` | `mineru_pipeline` | 657 | 0.1461 | [0.1176, 0.1730] | 0.8539 |
| `monkeyocrv2_b` | `glm_ocr` | 657 | 0.1400 | [0.1122, 0.1682] | 0.8600 |
| `opus5_subscription` | `ovisocr2` | 850 | 0.5000 | [0.4674, 0.5342] | 0.5000 |
| `opus5_subscription` | `paddleocr_vl_1_6` | 850 | 0.4365 | [0.3998, 0.4748] | 0.5635 |
| `opus5_subscription` | `hpd_parsing` | 850 | 0.4294 | [0.3961, 0.4651] | 0.5706 |
| `opus5_subscription` | `mineru_vlm` | 850 | 0.4035 | [0.3725, 0.4382] | 0.5965 |
| `opus5_subscription` | `monkeyocrv2_b` | 850 | 0.3741 | [0.3447, 0.4067] | 0.6259 |
| `opus5_subscription` | `deepseek_ocr2` | 850 | 0.3376 | [0.3028, 0.3690] | 0.6624 |
| `opus5_subscription` | `infinity_parser2_flash` | 850 | 0.3341 | [0.3046, 0.3653] | 0.6659 |
| `opus5_subscription` | `glm_ocr` | 850 | 0.2247 | [0.1952, 0.2565] | 0.7753 |
| `opus5_subscription` | `mineru_pipeline` | 850 | 0.2188 | [0.1930, 0.2479] | 0.7812 |
| `ovisocr2` | `hpd_parsing` | 460 | 0.1065 | [0.0813, 0.1365] | 0.8935 |
| `ovisocr2` | `paddleocr_vl_1_6` | 460 | 0.1065 | [0.0796, 0.1376] | 0.8935 |
| `ovisocr2` | `mineru_vlm` | 460 | 0.1022 | [0.0725, 0.1325] | 0.8978 |
| `ovisocr2` | `glm_ocr` | 460 | 0.0848 | [0.0587, 0.1119] | 0.9152 |
| `ovisocr2` | `infinity_parser2_flash` | 460 | 0.0783 | [0.0539, 0.1064] | 0.9217 |
| `ovisocr2` | `monkeyocrv2_b` | 460 | 0.0783 | [0.0557, 0.1024] | 0.9217 |
| `ovisocr2` | `opus5_subscription` | 460 | 0.0761 | [0.0536, 0.1016] | 0.9239 |
| `ovisocr2` | `mineru_pipeline` | 460 | 0.0543 | [0.0350, 0.0791] | 0.9457 |
| `ovisocr2` | `deepseek_ocr2` | 460 | 0.0478 | [0.0283, 0.0680] | 0.9522 |
| `paddleocr_vl_1_6` | `ovisocr2` | 594 | 0.3081 | [0.2710, 0.3405] | 0.6919 |
| `paddleocr_vl_1_6` | `hpd_parsing` | 594 | 0.2475 | [0.2114, 0.2841] | 0.7525 |
| `paddleocr_vl_1_6` | `monkeyocrv2_b` | 594 | 0.2054 | [0.1713, 0.2400] | 0.7946 |
| `paddleocr_vl_1_6` | `mineru_vlm` | 594 | 0.2037 | [0.1701, 0.2361] | 0.7963 |
| `paddleocr_vl_1_6` | `infinity_parser2_flash` | 594 | 0.2003 | [0.1701, 0.2310] | 0.7997 |
| `paddleocr_vl_1_6` | `opus5_subscription` | 594 | 0.1936 | [0.1616, 0.2321] | 0.8064 |
| `paddleocr_vl_1_6` | `deepseek_ocr2` | 594 | 0.1717 | [0.1431, 0.2020] | 0.8283 |
| `paddleocr_vl_1_6` | `mineru_pipeline` | 594 | 0.1380 | [0.1074, 0.1675] | 0.8620 |
| `paddleocr_vl_1_6` | `glm_ocr` | 594 | 0.0960 | [0.0710, 0.1201] | 0.9040 |

