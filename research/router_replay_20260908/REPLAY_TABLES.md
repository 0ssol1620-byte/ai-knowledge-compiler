# Router replay tables — Phase B (stored outputs, GPU spend $0)

Loss is lower-better. `IRR proxy = 1 - mean loss` over L1/L3/L4/L5 only
(`LOSS_VECTOR_FREEZE.json`). **NOT a public benchmark result. NOT a champion
promotion.** Missing and failed outputs are full losses and stay in every
denominator. `ORACLE_DIAGNOSTIC` sees hidden truth and is never a router result.

## Surface `olmocr` — 1403 units, 12 models

Ground truth for SCLR: PARTIAL — the union of asserted `present`/`math`/`table` spans; a lower bound

| arm | n | mean loss | 95% CI | IRR proxy | hard fail | regret | unresolved | escalation | strong | SCLR/unit | SCLR/opp | $/1k | GPU s/unit | p50 ms | p95 ms | p99 ms | ledger s |
| --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `ORACLE_DIAGNOSTIC` | 1403 | 0.0615 | [0.0538, 0.0695] | 0.9385 | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| `SINGLE:mineru_vlm` | 1403 | 0.1381 | [0.1270, 0.1505] | 0.8619 | 550 | 0.0766 | 0.000 | 0.000 | 0.000 | 0.1012 | 0.0830 | 1.00 | 7.33 | n/a | n/a | n/a | 5.0 |
| `SINGLE:olmocr2` | 1403 | 0.1396 | [0.1284, 0.1512] | 0.8604 | 570 | 0.0781 | 0.000 | 0.000 | 0.000 | 0.0927 | 0.0461 | 7.64 | 37.19 | n/a | n/a | n/a | 13.0 |
| `PRIMARY_ONLY` | 1403 | 0.1468 | [0.1343, 0.1609] | 0.8532 | 584 | 0.0853 | 0.000 | 0.000 | 0.000 | 0.0870 | 0.0376 | 4.92 | 23.93 | 2565 | 5003 | 12101 | 4.0 |
| `SINGLE:paddleocr_vl_1_6` | 1403 | 0.1468 | [0.1343, 0.1609] | 0.8532 | 584 | 0.0853 | 0.000 | 0.000 | 0.000 | 0.0870 | 0.0376 | 4.92 | 23.93 | 2565 | 5003 | 12101 | 4.0 |
| `CORE_ROUTER@balanced,ro=0` | 1403 | 0.1468 | [0.1343, 0.1609] | 0.8532 | 584 | 0.0853 | 0.000 | 0.000 | 0.000 | 0.0870 | 0.0376 | 4.92 | 23.93 | 2565 | 5003 | 12101 | 4.0 |
| `CRITICAL_TOKEN_ONLY@opus5_subscription` | 1403 | 0.1508 | [0.1382, 0.1642] | 0.8492 | 576 | 0.0893 | 0.000 | 0.224 | 0.224 | 0.0891 | 0.0389 | n/a | n/a | 5887 | 42675 | 58410 | n/a |
| `PREDICTION_ONLY@opus5_subscription` | 1403 | 0.1524 | [0.1394, 0.1663] | 0.8476 | 595 | 0.0909 | 0.000 | 0.073 | 0.073 | 0.0870 | 0.0381 | n/a | n/a | 2599 | 18971 | 35896 | n/a |
| `PREDICTION_ONLY@unlimited_ocr` | 1403 | 0.1540 | [0.1411, 0.1680] | 0.8460 | 597 | 0.0925 | 0.000 | 0.073 | 0.073 | 0.0905 | 0.0388 | 7.04 | 34.32 | 2599 | 29813 | 52999 | 6.1 |
| `CRITICAL_TOKEN_ONLY@unlimited_ocr` | 1403 | 0.1571 | [0.1443, 0.1711] | 0.8429 | 611 | 0.0956 | 0.000 | 0.224 | 0.224 | 0.0962 | 0.0784 | 16.29 | 79.46 | 5877 | 57678 | 88118 | 14.5 |
| `ABLATION:no_disagreement@opus5_subscription` | 1403 | 0.1576 | [0.1451, 0.1714] | 0.8424 | 605 | 0.0961 | 0.000 | 0.247 | 0.247 | 0.0862 | 0.0347 | n/a | n/a | 5955 | 43811 | 60695 | n/a |
| `ABLATION:no_disagreement@unlimited_ocr` | 1403 | 0.1577 | [0.1451, 0.1716] | 0.8423 | 606 | 0.0962 | 0.000 | 0.247 | 0.247 | 0.0855 | 0.0456 | 16.97 | 82.83 | 5950 | 58054 | 88788 | 15.2 |
| `SINGLE:deepseek_ocr2` | 1403 | 0.1636 | [0.1508, 0.1766] | 0.8364 | 636 | 0.1021 | 0.000 | 0.000 | 0.000 | 0.0962 | 0.0478 | 11.35 | 55.20 | n/a | n/a | n/a | 27.0 |
| `DISAGREEMENT_ONLY@opus5_subscription` | 1403 | 0.1684 | [0.1571, 0.1811] | 0.8316 | 651 | 0.1069 | 0.000 | 0.293 | 0.293 | 0.0741 | 0.0381 | n/a | n/a | 6456 | 47173 | 100185 | n/a |
| `ABLATION:no_reconciler@opus5_subscription` | 1403 | 0.1722 | [0.1598, 0.1849] | 0.8278 | 644 | 0.1107 | 0.000 | 0.439 | 0.439 | 0.0798 | 0.0375 | n/a | n/a | 8130 | 51112 | 100185 | n/a |
| `ABLATION:no_critical_loss_detector@opus5_subscription` | 1403 | 0.1772 | [0.1647, 0.1909] | 0.8228 | 663 | 0.1157 | 0.000 | 0.293 | 0.293 | 0.0798 | 0.0345 | n/a | n/a | 6456 | 47173 | 100185 | n/a |
| `REPLAY_COMPOSITE_V1@opus5_subscription` | 1403 | 0.1811 | [0.1683, 0.1947] | 0.8189 | 664 | 0.1196 | 0.000 | 0.439 | 0.439 | 0.0798 | 0.0329 | n/a | n/a | 8130 | 51112 | 100185 | n/a |
| `ABLATION:no_prediction@opus5_subscription` | 1403 | 0.1811 | [0.1683, 0.1947] | 0.8189 | 664 | 0.1196 | 0.000 | 0.439 | 0.439 | 0.0798 | 0.0329 | n/a | n/a | 8130 | 51112 | 100185 | n/a |
| `ABLATION:no_cost_objective@opus5_subscription` | 1403 | 0.1823 | [0.1692, 0.1959] | 0.8177 | 663 | 0.1208 | 0.000 | 0.468 | 0.468 | 0.0791 | 0.0328 | n/a | n/a | 8469 | 51122 | 100185 | n/a |
| `ABLATION:no_critical_loss_detector@unlimited_ocr` | 1403 | 0.1839 | [0.1708, 0.1981] | 0.8161 | 670 | 0.1224 | 0.000 | 0.293 | 0.293 | 0.0805 | 0.0452 | 18.30 | 89.35 | 6369 | 59591 | 110995 | 16.5 |
| `DISAGREEMENT_ONLY@unlimited_ocr` | 1403 | 0.1863 | [0.1734, 0.2002] | 0.8137 | 676 | 0.1248 | 0.000 | 0.293 | 0.293 | 0.0862 | 0.0546 | 18.30 | 89.35 | 6369 | 59591 | 110995 | 16.5 |
| `REPLAY_COMPOSITE_V1@unlimited_ocr` | 1403 | 0.1876 | [0.1743, 0.2013] | 0.8124 | 671 | 0.1261 | 0.000 | 0.439 | 0.439 | 0.0805 | 0.0440 | 22.57 | 110.24 | 7833 | 71067 | 110995 | 20.7 |
| `ABLATION:no_prediction@unlimited_ocr` | 1403 | 0.1876 | [0.1743, 0.2013] | 0.8124 | 671 | 0.1261 | 0.000 | 0.439 | 0.439 | 0.0805 | 0.0440 | 22.57 | 110.24 | 7833 | 71067 | 110995 | 20.7 |
| `ABLATION:no_cost_objective@unlimited_ocr` | 1403 | 0.1884 | [0.1749, 0.2023] | 0.8116 | 671 | 0.1269 | 0.000 | 0.468 | 0.468 | 0.0805 | 0.0440 | 23.40 | 114.32 | 8291 | 71248 | 110995 | 21.6 |
| `ABLATION:no_reconciler@unlimited_ocr` | 1403 | 0.1935 | [0.1798, 0.2074] | 0.8065 | 692 | 0.1320 | 0.000 | 0.439 | 0.439 | 0.0962 | 0.0766 | 22.57 | 110.24 | 7833 | 71067 | 110995 | 20.7 |
| `ALWAYS_ALL_RECONCILED` | 1403 | 0.2077 | [0.1945, 0.2214] | 0.7923 | 706 | 0.1462 | 0.000 | 1.000 | 1.000 | 0.0734 | 0.0696 | n/a | n/a | n/a | n/a | n/a | n/a |
| `SINGLE:mineru_pipeline` | 1403 | 0.2081 | [0.1930, 0.2243] | 0.7919 | 758 | 0.1466 | 0.000 | 0.000 | 0.000 | 0.1939 | 0.1311 | 4.95 | 24.09 | n/a | n/a | n/a | 4.0 |
| `SINGLE:infinity_parser2_flash` | 1403 | 0.2295 | [0.2160, 0.2435] | 0.7705 | 780 | 0.1680 | 0.000 | 0.000 | 0.000 | 0.0912 | 0.0468 | 0.80 | 3.87 | n/a | n/a | n/a | n/a |
| `SINGLE:opus5_subscription` | 1403 | 0.2325 | [0.2177, 0.2477] | 0.7675 | 731 | 0.1710 | 0.019 | 0.000 | 1.000 | 0.0763 | 0.0429 | n/a | n/a | 19936 | 43314 | 63168 | n/a |
| `ALWAYS_STRONG@opus5_subscription` | 1403 | 0.2325 | [0.2177, 0.2477] | 0.7675 | 731 | 0.1710 | 0.019 | 0.000 | 1.000 | 0.0763 | 0.0429 | n/a | n/a | 19936 | 43314 | 63168 | n/a |
| `SINGLE:ovisocr2` | 1403 | 0.2462 | [0.2316, 0.2611] | 0.7538 | 771 | 0.1847 | 0.000 | 0.000 | 0.000 | 0.0841 | 0.0355 | 4.84 | 23.54 | 2733 | 6858 | 43649 | 4.0 |
| `SINGLE:unlimited_ocr` | 1403 | 0.2483 | [0.2337, 0.2634] | 0.7517 | 807 | 0.1868 | 0.002 | 0.000 | 1.000 | 0.1012 | 0.0797 | 29.17 | 142.97 | 32611 | 69065 | 90806 | 29.0 |
| `ALWAYS_STRONG@unlimited_ocr` | 1403 | 0.2483 | [0.2337, 0.2634] | 0.7517 | 807 | 0.1868 | 0.002 | 0.000 | 1.000 | 0.1012 | 0.0797 | 29.17 | 142.97 | 32611 | 69065 | 90806 | 29.0 |
| `SINGLE:monkeyocrv2_b` | 1403 | 0.2598 | [0.2451, 0.2752] | 0.7402 | 860 | 0.1983 | 0.000 | 0.000 | 0.000 | 0.1133 | 0.0901 | 5.60 | 27.25 | n/a | n/a | n/a | 6.0 |
| `SINGLE:hpd_parsing` | 1403 | 0.2997 | [0.2837, 0.3163] | 0.7003 | 917 | 0.2382 | 0.000 | 0.000 | 0.000 | 0.1069 | 0.0860 | 20.78 | 21.70 | 1020 | 3146 | 15667 | 3.0 |
| `CORE_ROUTER@speed,ro=0` | 1403 | 0.2997 | [0.2837, 0.3163] | 0.7003 | 917 | 0.2382 | 0.000 | 0.000 | 0.000 | 0.1069 | 0.0860 | 20.78 | 21.70 | 1020 | 3146 | 15667 | 3.0 |
| `SINGLE:glm_ocr` | 1403 | 0.3629 | [0.3459, 0.3802] | 0.6371 | 1048 | 0.3014 | 0.001 | 0.000 | 0.000 | 0.0834 | 0.0440 | 8.57 | 33.76 | n/a | n/a | n/a | 5.0 |
| `CORE_ROUTER@balanced,ro=1` | 1403 | 0.8954 | [0.8781, 0.9122] | 0.1046 | 1326 | 0.8339 | 0.840 | 0.000 | 0.000 | 0.0292 | 0.0129 | 0.79 | 3.84 | 2355 | 7265 | 17354 | 0.6 |
| `CORE_ROUTER@balanced,sentinels` | 1403 | 0.8954 | [0.8781, 0.9122] | 0.1046 | 1326 | 0.8339 | 0.840 | 0.000 | 0.000 | 0.0292 | 0.0129 | 0.79 | 3.84 | 2355 | 7265 | 17354 | 0.6 |
| `CORE_ROUTER@speed,sentinels` | 1403 | 0.8954 | [0.8781, 0.9122] | 0.1046 | 1326 | 0.8339 | 0.840 | 0.000 | 0.000 | 0.0292 | 0.0129 | 0.79 | 3.84 | 2355 | 7265 | 17354 | 0.6 |
| `CORE_ROUTER@speed,ro=1` | 1403 | 0.9169 | [0.9008, 0.9319] | 0.0831 | 1359 | 0.8554 | 0.840 | 0.000 | 0.000 | 0.0306 | 0.0186 | 3.33 | 3.48 | 1422 | 13212 | 16764 | 0.5 |

Best fixed single: `SINGLE:mineru_vlm`. Oracle headroom 0.0755 [0.0682, 0.0826] over 1367 document-family clusters.

### Section 17 Oracle capture ratio `(best_fixed - arm) / (best_fixed - oracle)`

| arm | capture | 95% CI |
| --- | ---: | --- |
| `ORACLE_DIAGNOSTIC` | 1.000 | [1.000, 1.000] |
| `SINGLE:mineru_vlm` | -0.017 | [-0.108, 0.000] |
| `SINGLE:olmocr2` | -0.038 | [-0.152, 0.000] |
| `PRIMARY_ONLY` | -0.133 | [-0.257, -0.022] |
| `SINGLE:paddleocr_vl_1_6` | -0.133 | [-0.257, -0.022] |
| `CORE_ROUTER@balanced,ro=0` | -0.133 | [-0.257, -0.022] |
| `CRITICAL_TOKEN_ONLY@opus5_subscription` | -0.186 | [-0.332, -0.056] |
| `PREDICTION_ONLY@opus5_subscription` | -0.206 | [-0.335, -0.082] |
| `PREDICTION_ONLY@unlimited_ocr` | -0.227 | [-0.352, -0.108] |
| `CRITICAL_TOKEN_ONLY@unlimited_ocr` | -0.270 | [-0.413, -0.144] |
| `ABLATION:no_disagreement@opus5_subscription` | -0.275 | [-0.424, -0.144] |
| `ABLATION:no_disagreement@unlimited_ocr` | -0.277 | [-0.424, -0.141] |
| `SINGLE:deepseek_ocr2` | -0.355 | [-0.501, -0.232] |
| `DISAGREEMENT_ONLY@opus5_subscription` | -0.421 | [-0.611, -0.265] |
| `ABLATION:no_reconciler@opus5_subscription` | -0.470 | [-0.663, -0.295] |
| `ABLATION:no_critical_loss_detector@opus5_subscription` | -0.537 | [-0.716, -0.382] |
| `REPLAY_COMPOSITE_V1@opus5_subscription` | -0.588 | [-0.777, -0.421] |
| `ABLATION:no_prediction@opus5_subscription` | -0.588 | [-0.777, -0.421] |
| `ABLATION:no_cost_objective@opus5_subscription` | -0.603 | [-0.796, -0.437] |
| `ABLATION:no_critical_loss_detector@unlimited_ocr` | -0.625 | [-0.812, -0.468] |
| `DISAGREEMENT_ONLY@unlimited_ocr` | -0.657 | [-0.836, -0.499] |
| `REPLAY_COMPOSITE_V1@unlimited_ocr` | -0.674 | [-0.864, -0.507] |
| `ABLATION:no_prediction@unlimited_ocr` | -0.674 | [-0.864, -0.507] |
| `ABLATION:no_cost_objective@unlimited_ocr` | -0.684 | [-0.878, -0.514] |
| `ABLATION:no_reconciler@unlimited_ocr` | -0.752 | [-0.944, -0.586] |
| `ALWAYS_ALL_RECONCILED` | -0.940 | [-1.189, -0.727] |
| `SINGLE:mineru_pipeline` | -0.946 | [-1.142, -0.763] |
| `SINGLE:infinity_parser2_flash` | -1.230 | [-1.499, -0.990] |
| `SINGLE:opus5_subscription` | -1.268 | [-1.588, -0.978] |
| `ALWAYS_STRONG@opus5_subscription` | -1.268 | [-1.588, -0.978] |
| `SINGLE:ovisocr2` | -1.451 | [-1.744, -1.198] |
| `SINGLE:unlimited_ocr` | -1.478 | [-1.762, -1.227] |
| `ALWAYS_STRONG@unlimited_ocr` | -1.478 | [-1.762, -1.227] |
| `SINGLE:monkeyocrv2_b` | -1.633 | [-1.926, -1.373] |
| `SINGLE:hpd_parsing` | -2.160 | [-2.511, -1.860] |
| `CORE_ROUTER@speed,ro=0` | -2.160 | [-2.511, -1.860] |
| `SINGLE:glm_ocr` | -2.997 | [-3.408, -2.644] |
| `CORE_ROUTER@balanced,ro=1` | -10.075 | [-11.282, -9.014] |
| `CORE_ROUTER@balanced,sentinels` | -10.075 | [-11.282, -9.014] |
| `CORE_ROUTER@speed,sentinels` | -10.075 | [-11.282, -9.014] |
| `CORE_ROUTER@speed,ro=1` | -10.359 | [-11.612, -9.268] |

### Disagreement conditionals (section 92), worst pairs

| a | b | n | agree rate | P(a wrong \| agree) | P(a wrong \| disagree) | P(both wrong AND agree) |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `hpd_parsing` | `unlimited_ocr` | 1400 | 0.851 | 0.602 | 0.943 | 0.417 |
| `ovisocr2` | `unlimited_ocr` | 1400 | 0.734 | 0.508 | 0.662 | 0.335 |
| `infinity_parser2_flash` | `ovisocr2` | 1403 | 0.751 | 0.506 | 0.706 | 0.321 |
| `hpd_parsing` | `ovisocr2` | 1403 | 0.689 | 0.593 | 0.789 | 0.316 |
| `glm_ocr` | `hpd_parsing` | 1401 | 0.585 | 0.673 | 0.850 | 0.310 |
| `glm_ocr` | `unlimited_ocr` | 1398 | 0.625 | 0.673 | 0.868 | 0.304 |
| `infinity_parser2_flash` | `monkeyocrv2_b` | 1403 | 0.694 | 0.497 | 0.690 | 0.301 |
| `infinity_parser2_flash` | `opus5_subscription` | 1377 | 0.739 | 0.537 | 0.604 | 0.301 |
| `monkeyocrv2_b` | `ovisocr2` | 1403 | 0.703 | 0.542 | 0.782 | 0.299 |
| `monkeyocrv2_b` | `unlimited_ocr` | 1400 | 0.694 | 0.547 | 0.762 | 0.296 |
| `glm_ocr` | `ovisocr2` | 1401 | 0.627 | 0.681 | 0.857 | 0.293 |
| `infinity_parser2_flash` | `unlimited_ocr` | 1400 | 0.669 | 0.510 | 0.648 | 0.287 |

### Catastrophic failure appendix (top units the Oracle also fails)

| unit | page class | oracle loss | best model | primary loss | blind risk | disagreed? | L2 flagged? | critical events |
| --- | --- | ---: | --- | ---: | ---: | :-: | :-: | ---: |
| `old_scans/80.pdf` | old_scans.jsonl | 0.8571 | `deepseek_ocr2` | 1.0000 | 0.000 | yes | no | 0 |
| `old_scans/77.pdf` | old_scans.jsonl | 0.8571 | `deepseek_ocr2` | 0.8571 | 0.000 | yes | no | 0 |
| `old_scans/81.pdf` | old_scans.jsonl | 0.8571 | `deepseek_ocr2` | 0.8571 | 0.000 | yes | no | 0 |
| `old_scans/92.pdf` | old_scans.jsonl | 0.8571 | `deepseek_ocr2` | 0.8571 | 0.000 | yes | yes | 0 |
| `multi_column/0a7e813e2010ecd8239725c32c859fe00c92_page_2_pg1.pdf` | multi_column.jsonl | 0.8333 | `deepseek_ocr2` | 0.8333 | 0.000 | yes | no | 0 |
| `old_scans/93.pdf` | old_scans.jsonl | 0.8333 | `deepseek_ocr2` | 0.8333 | 0.000 | yes | no | 0 |
| `tables/b5d9db350b31304da912832bcbafc47b64d8_pg2_pg1.pdf` | table_tests.jsonl | 0.8333 | `deepseek_ocr2` | 0.8333 | 0.000 | no | yes | 10 |
| `multi_column/0925342e1efabb7957efa34203f65d3cbc4d_page_9_pg1.pdf` | multi_column.jsonl | 0.8000 | `deepseek_ocr2` | 0.8000 | 0.000 | no | no | 0 |
| `old_scans_math/4_pg355.pdf` | old_scans_math.jsonl | 0.8000 | `deepseek_ocr2` | 0.8000 | 0.000 | no | yes | 0 |
| `old_scans/43.pdf` | old_scans.jsonl | 0.7500 | `infinity_parser2_flash` | 1.0000 | 0.000 | yes | no | 0 |

## Surface `omnidoc` — 1641 units, 10 models

Ground truth for SCLR: FULL — every layout block's text, latex and html from OmniDocBench.json

| arm | n | mean loss | 95% CI | IRR proxy | hard fail | regret | unresolved | escalation | strong | SCLR/unit | SCLR/opp | $/1k | GPU s/unit | p50 ms | p95 ms | p99 ms | ledger s |
| --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `ORACLE_DIAGNOSTIC` | 1641 | 0.0390 | [0.0352, 0.0428] | 0.9610 | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| `SINGLE:ovisocr2` | 1641 | 0.0559 | [0.0510, 0.0608] | 0.9441 | 460 | 0.0169 | 0.000 | 0.000 | 0.000 | 0.5619 | 0.0839 | 4.84 | 23.54 | 2253 | 11496 | 21689 | 4.0 |
| `ABLATION:no_cost_objective@opus5_subscription` | 1641 | 0.0600 | [0.0550, 0.0652] | 0.9400 | 504 | 0.0211 | 0.000 | 0.727 | 0.727 | 0.6600 | 0.0919 | n/a | n/a | 18362 | 105164 | 313901 | n/a |
| `ABLATION:no_critical_loss_detector@opus5_subscription` | 1641 | 0.0603 | [0.0552, 0.0654] | 0.9397 | 509 | 0.0213 | 0.000 | 0.608 | 0.608 | 0.6807 | 0.0964 | n/a | n/a | 14389 | 86906 | 313901 | n/a |
| `REPLAY_COMPOSITE_V1@opus5_subscription` | 1641 | 0.0604 | [0.0553, 0.0655] | 0.9396 | 507 | 0.0214 | 0.000 | 0.690 | 0.690 | 0.6722 | 0.0930 | n/a | n/a | 17412 | 97244 | 313901 | n/a |
| `ABLATION:no_prediction@opus5_subscription` | 1641 | 0.0604 | [0.0553, 0.0655] | 0.9396 | 507 | 0.0214 | 0.000 | 0.690 | 0.690 | 0.6722 | 0.0930 | n/a | n/a | 17412 | 97244 | 313901 | n/a |
| `ABLATION:no_disagreement@opus5_subscription` | 1641 | 0.0661 | [0.0610, 0.0713] | 0.9339 | 570 | 0.0271 | 0.000 | 0.286 | 0.286 | 0.8050 | 0.0998 | n/a | n/a | 6077 | 45040 | 132927 | n/a |
| `PRIMARY_ONLY` | 1641 | 0.0685 | [0.0635, 0.0736] | 0.9315 | 594 | 0.0295 | 0.000 | 0.000 | 0.000 | 0.8525 | 0.1095 | 4.92 | 23.93 | 2291 | 7027 | 13584 | 4.0 |
| `SINGLE:paddleocr_vl_1_6` | 1641 | 0.0685 | [0.0635, 0.0736] | 0.9315 | 594 | 0.0295 | 0.000 | 0.000 | 0.000 | 0.8525 | 0.1095 | 4.92 | 23.93 | 2291 | 7027 | 13584 | 4.0 |
| `CORE_ROUTER@balanced,ro=1` | 1641 | 0.0685 | [0.0635, 0.0736] | 0.9315 | 594 | 0.0295 | 0.000 | 0.000 | 0.000 | 0.8525 | 0.1095 | 4.92 | 23.93 | 2291 | 7027 | 13584 | 4.0 |
| `CORE_ROUTER@balanced,ro=0` | 1641 | 0.0685 | [0.0635, 0.0736] | 0.9315 | 594 | 0.0295 | 0.000 | 0.000 | 0.000 | 0.8525 | 0.1095 | 4.92 | 23.93 | 2291 | 7027 | 13584 | 4.0 |
| `CORE_ROUTER@balanced,sentinels` | 1641 | 0.0685 | [0.0635, 0.0736] | 0.9315 | 594 | 0.0295 | 0.000 | 0.000 | 0.000 | 0.8525 | 0.1095 | 4.92 | 23.93 | 2291 | 7027 | 13584 | 4.0 |
| `CORE_ROUTER@speed,sentinels` | 1641 | 0.0685 | [0.0635, 0.0736] | 0.9315 | 594 | 0.0295 | 0.000 | 0.000 | 0.000 | 0.8525 | 0.1095 | 4.92 | 23.93 | 2291 | 7027 | 13584 | 4.0 |
| `SINGLE:hpd_parsing` | 1641 | 0.0720 | [0.0660, 0.0787] | 0.9280 | 561 | 0.0331 | 0.000 | 0.000 | 0.000 | 0.6648 | 0.1050 | 20.78 | 21.70 | 1233 | 4309 | 12153 | 3.0 |
| `CORE_ROUTER@speed,ro=1` | 1641 | 0.0720 | [0.0660, 0.0787] | 0.9280 | 561 | 0.0331 | 0.000 | 0.000 | 0.000 | 0.6648 | 0.1050 | 20.78 | 21.70 | 1233 | 4309 | 12153 | 3.0 |
| `CORE_ROUTER@speed,ro=0` | 1641 | 0.0720 | [0.0660, 0.0787] | 0.9280 | 561 | 0.0331 | 0.000 | 0.000 | 0.000 | 0.6648 | 0.1050 | 20.78 | 21.70 | 1233 | 4309 | 12153 | 3.0 |
| `SINGLE:mineru_vlm` | 1641 | 0.0762 | [0.0693, 0.0826] | 0.9238 | 603 | 0.0372 | 0.000 | 0.000 | 0.000 | 0.8537 | 0.0949 | 1.00 | 7.33 | n/a | n/a | n/a | 5.0 |
| `SINGLE:infinity_parser2_flash` | 1641 | 0.0819 | [0.0760, 0.0883] | 0.9181 | 668 | 0.0429 | 0.000 | 0.000 | 0.000 | 0.6587 | 0.1162 | 0.80 | 3.87 | n/a | n/a | n/a | n/a |
| `SINGLE:monkeyocrv2_b` | 1641 | 0.0889 | [0.0817, 0.0962] | 0.9111 | 657 | 0.0500 | 0.000 | 0.000 | 0.000 | 0.7075 | 0.1087 | 5.60 | 27.25 | n/a | n/a | n/a | 6.0 |
| `CRITICAL_TOKEN_ONLY@opus5_subscription` | 1641 | 0.0913 | [0.0846, 0.0985] | 0.9087 | 679 | 0.0523 | 0.000 | 0.224 | 0.224 | 0.8373 | 0.1138 | n/a | n/a | 5344 | 42635 | 101102 | n/a |
| `SINGLE:deepseek_ocr2` | 1641 | 0.0930 | [0.0857, 0.1006] | 0.9070 | 703 | 0.0540 | 0.000 | 0.000 | 0.000 | 0.8641 | 0.1550 | 11.35 | 55.20 | n/a | n/a | n/a | 27.0 |
| `PREDICTION_ONLY@opus5_subscription` | 1641 | 0.0988 | [0.0907, 0.1067] | 0.9012 | 657 | 0.0598 | 0.000 | 0.127 | 0.127 | 0.8428 | 0.1270 | n/a | n/a | 2450 | 31387 | 76314 | n/a |
| `SINGLE:mineru_pipeline` | 1641 | 0.1274 | [0.1187, 0.1366] | 0.8726 | 847 | 0.0884 | 0.000 | 0.000 | 0.000 | 0.8665 | 0.1218 | 4.95 | 24.09 | n/a | n/a | n/a | 4.0 |
| `DISAGREEMENT_ONLY@opus5_subscription` | 1641 | 0.1288 | [0.1195, 0.1387] | 0.8712 | 767 | 0.0898 | 0.000 | 0.608 | 0.608 | 0.7118 | 0.1084 | n/a | n/a | 14389 | 86906 | 313901 | n/a |
| `ABLATION:no_disagreement@unlimited_ocr` | 1641 | 0.1334 | [0.1204, 0.1468] | 0.8666 | 628 | 0.0944 | 0.000 | 0.286 | 0.286 | 0.8141 | 0.1022 | 18.09 | 88.33 | 6055 | 69238 | 147370 | 16.3 |
| `ABLATION:no_reconciler@opus5_subscription` | 1641 | 0.1342 | [0.1245, 0.1445] | 0.8658 | 784 | 0.0953 | 0.000 | 0.690 | 0.690 | 0.7057 | 0.1138 | n/a | n/a | 17412 | 97244 | 313901 | n/a |
| `SINGLE:opus5_subscription` | 1641 | 0.1649 | [0.1530, 0.1764] | 0.8351 | 850 | 0.1259 | 0.013 | 0.000 | 1.000 | 0.6222 | 0.1213 | n/a | n/a | 18530 | 81442 | 295312 | n/a |
| `ALWAYS_STRONG@opus5_subscription` | 1641 | 0.1649 | [0.1530, 0.1764] | 0.8351 | 850 | 0.1259 | 0.013 | 0.000 | 1.000 | 0.6222 | 0.1213 | n/a | n/a | 18530 | 81442 | 295312 | n/a |
| `SINGLE:glm_ocr` | 1641 | 0.1717 | [0.1598, 0.1846] | 0.8283 | 901 | 0.1327 | 0.030 | 0.000 | 0.000 | 0.6216 | 0.0958 | 8.57 | 33.76 | n/a | n/a | n/a | 5.0 |
| `PREDICTION_ONLY@unlimited_ocr` | 1641 | 0.1761 | [0.1601, 0.1931] | 0.8239 | 666 | 0.1371 | 0.000 | 0.127 | 0.127 | 0.8428 | 0.1246 | 8.62 | 42.05 | 2449 | 39309 | 98793 | 7.7 |
| `ALWAYS_ALL_RECONCILED` | 1641 | 0.1780 | [0.1628, 0.1944] | 0.8220 | 663 | 0.1390 | 0.000 | 1.000 | 1.000 | 0.6527 | 0.0881 | n/a | n/a | n/a | n/a | n/a | n/a |
| `ABLATION:no_critical_loss_detector@unlimited_ocr` | 1641 | 0.2051 | [0.1872, 0.2223] | 0.7949 | 678 | 0.1661 | 0.000 | 0.608 | 0.608 | 0.6990 | 0.0991 | 27.50 | 134.42 | 14566 | 111491 | 188022 | 25.6 |
| `REPLAY_COMPOSITE_V1@unlimited_ocr` | 1641 | 0.2148 | [0.1967, 0.2329] | 0.7852 | 684 | 0.1759 | 0.000 | 0.690 | 0.690 | 0.6910 | 0.0958 | 29.90 | 146.18 | 17990 | 124823 | 197247 | 28.0 |
| `ABLATION:no_prediction@unlimited_ocr` | 1641 | 0.2148 | [0.1967, 0.2329] | 0.7852 | 684 | 0.1759 | 0.000 | 0.690 | 0.690 | 0.6910 | 0.0958 | 29.90 | 146.18 | 17990 | 124823 | 197247 | 28.0 |
| `ABLATION:no_cost_objective@unlimited_ocr` | 1641 | 0.2200 | [0.2016, 0.2376] | 0.7800 | 686 | 0.1810 | 0.000 | 0.727 | 0.727 | 0.6807 | 0.0950 | 30.96 | 151.41 | 19291 | 127440 | 198347 | 29.1 |
| `CRITICAL_TOKEN_ONLY@unlimited_ocr` | 1641 | 0.2750 | [0.2544, 0.2974] | 0.7250 | 804 | 0.2361 | 0.000 | 0.224 | 0.224 | 0.8410 | 0.1097 | 16.30 | 79.53 | 5318 | 67144 | 147370 | 14.5 |
| `DISAGREEMENT_ONLY@unlimited_ocr` | 1641 | 0.6255 | [0.5974, 0.6530] | 0.3745 | 1170 | 0.5865 | 0.000 | 0.608 | 0.608 | 0.7404 | 0.1082 | 27.50 | 134.42 | 14566 | 111491 | 188022 | 25.6 |
| `ABLATION:no_reconciler@unlimited_ocr` | 1641 | 0.7038 | [0.6774, 0.7291] | 0.2962 | 1262 | 0.6648 | 0.000 | 0.690 | 0.690 | 0.7349 | 0.1103 | 29.90 | 146.18 | 17990 | 124823 | 197247 | 28.0 |
| `ALWAYS_STRONG@unlimited_ocr` | 1641 | 1.0000 | [1.0000, 1.0000] | 0.0000 | 1641 | 0.9610 | 0.004 | 0.000 | 1.000 | 0.6606 | 0.1034 | 29.17 | 142.97 | 24196 | 110275 | 175968 | 29.0 |

Best fixed single: `SINGLE:ovisocr2`. Oracle headroom 0.0169 [0.0142, 0.0200] over 1435 document-family clusters.

### Section 17 Oracle capture ratio `(best_fixed - arm) / (best_fixed - oracle)`

| arm | capture | 95% CI |
| --- | ---: | --- |
| `ORACLE_DIAGNOSTIC` | 1.000 | [1.000, 1.000] |
| `SINGLE:ovisocr2` | 0.000 | [0.000, 0.000] |
| `ABLATION:no_cost_objective@opus5_subscription` | -0.251 | [-0.389, -0.120] |
| `ABLATION:no_critical_loss_detector@opus5_subscription` | -0.265 | [-0.416, -0.125] |
| `REPLAY_COMPOSITE_V1@opus5_subscription` | -0.270 | [-0.416, -0.135] |
| `ABLATION:no_prediction@opus5_subscription` | -0.270 | [-0.416, -0.135] |
| `ABLATION:no_disagreement@opus5_subscription` | -0.609 | [-0.871, -0.376] |
| `PRIMARY_ONLY` | -0.752 | [-1.064, -0.482] |
| `SINGLE:paddleocr_vl_1_6` | -0.752 | [-1.064, -0.482] |
| `CORE_ROUTER@balanced,ro=1` | -0.752 | [-1.064, -0.482] |
| `CORE_ROUTER@balanced,ro=0` | -0.752 | [-1.064, -0.482] |
| `CORE_ROUTER@balanced,sentinels` | -0.752 | [-1.064, -0.482] |
| `CORE_ROUTER@speed,sentinels` | -0.752 | [-1.064, -0.482] |
| `SINGLE:hpd_parsing` | -0.967 | [-1.312, -0.657] |
| `CORE_ROUTER@speed,ro=1` | -0.967 | [-1.312, -0.657] |
| `CORE_ROUTER@speed,ro=0` | -0.967 | [-1.312, -0.657] |
| `SINGLE:mineru_vlm` | -1.213 | [-1.605, -0.873] |
| `SINGLE:infinity_parser2_flash` | -1.556 | [-2.060, -1.140] |
| `SINGLE:monkeyocrv2_b` | -1.977 | [-2.572, -1.482] |
| `CRITICAL_TOKEN_ONLY@opus5_subscription` | -2.112 | [-2.726, -1.610] |
| `SINGLE:deepseek_ocr2` | -2.219 | [-2.845, -1.670] |
| `PREDICTION_ONLY@opus5_subscription` | -2.559 | [-3.239, -1.966] |
| `SINGLE:mineru_pipeline` | -4.266 | [-5.334, -3.392] |
| `DISAGREEMENT_ONLY@opus5_subscription` | -4.349 | [-5.332, -3.516] |
| `ABLATION:no_disagreement@unlimited_ocr` | -4.619 | [-5.857, -3.552] |
| `ABLATION:no_reconciler@opus5_subscription` | -4.670 | [-5.712, -3.774] |
| `SINGLE:opus5_subscription` | -6.500 | [-7.953, -5.261] |
| `ALWAYS_STRONG@opus5_subscription` | -6.500 | [-7.953, -5.261] |
| `SINGLE:glm_ocr` | -6.903 | [-8.475, -5.533] |
| `PREDICTION_ONLY@unlimited_ocr` | -7.174 | [-8.908, -5.617] |
| `ALWAYS_ALL_RECONCILED` | -7.290 | [-9.087, -5.733] |
| `ABLATION:no_critical_loss_detector@unlimited_ocr` | -8.878 | [-10.925, -7.087] |
| `REPLAY_COMPOSITE_V1@unlimited_ocr` | -9.459 | [-11.639, -7.565] |
| `ABLATION:no_prediction@unlimited_ocr` | -9.459 | [-11.639, -7.565] |
| `ABLATION:no_cost_objective@unlimited_ocr` | -9.767 | [-12.004, -7.789] |
| `CRITICAL_TOKEN_ONLY@unlimited_ocr` | -13.099 | [-15.870, -10.637] |
| `DISAGREEMENT_ONLY@unlimited_ocr` | -33.944 | [-40.651, -28.134] |
| `ABLATION:no_reconciler@unlimited_ocr` | -38.628 | [-46.056, -32.121] |
| `ALWAYS_STRONG@unlimited_ocr` | -56.296 | [-66.915, -47.042] |

### Disagreement conditionals (section 92), worst pairs

| a | b | n | agree rate | P(a wrong \| agree) | P(a wrong \| disagree) | P(both wrong AND agree) |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `infinity_parser2_flash` | `monkeyocrv2_b` | 1641 | 0.450 | 0.355 | 0.450 | 0.129 |
| `hpd_parsing` | `mineru_vlm` | 1641 | 0.487 | 0.307 | 0.375 | 0.129 |
| `deepseek_ocr2` | `infinity_parser2_flash` | 1641 | 0.480 | 0.334 | 0.515 | 0.128 |
| `hpd_parsing` | `infinity_parser2_flash` | 1641 | 0.495 | 0.272 | 0.411 | 0.120 |
| `hpd_parsing` | `ovisocr2` | 1641 | 0.519 | 0.300 | 0.387 | 0.116 |
| `infinity_parser2_flash` | `ovisocr2` | 1641 | 0.545 | 0.313 | 0.519 | 0.112 |
| `deepseek_ocr2` | `monkeyocrv2_b` | 1641 | 0.389 | 0.355 | 0.475 | 0.106 |
| `hpd_parsing` | `monkeyocrv2_b` | 1641 | 0.396 | 0.289 | 0.376 | 0.102 |
| `deepseek_ocr2` | `ovisocr2` | 1641 | 0.485 | 0.328 | 0.523 | 0.099 |
| `mineru_vlm` | `ovisocr2` | 1641 | 0.399 | 0.322 | 0.398 | 0.096 |
| `deepseek_ocr2` | `hpd_parsing` | 1641 | 0.419 | 0.327 | 0.502 | 0.093 |
| `monkeyocrv2_b` | `ovisocr2` | 1641 | 0.429 | 0.317 | 0.463 | 0.093 |

### Catastrophic failure appendix (top units the Oracle also fails)

| unit | page class | oracle loss | best model | primary loss | blind risk | disagreed? | L2 flagged? | critical events |
| --- | --- | ---: | --- | ---: | ---: | :-: | :-: | ---: |
| `jiaocaineedrop_jiaocai_needrop_en_2604.jpg` | exam_paper|simplified_chinese|three_column | 0.6670 | `mineru_pipeline` | 0.8758 | 0.000 | yes | no | 157 |
| `page-472c26e2-6bc2-4c05-9889-05132c87a8a9.png` | research_report|simplified_chinese|single_column | 0.5031 | `mineru_vlm` | 0.5031 | 0.365 | yes | no | 2 |
| `page-91b20bf2-3ad5-41f4-b739-4cc4b18ab1eb.png` | academic_literature|simplified_chinese|single_column | 0.4793 | `paddleocr_vl_1_6` | 0.4793 | 0.484 | yes | no | 40 |
| `page-8d707810-de48-43ba-81a7-b976918e7be2.png` | academic_literature|en_ch_mixed|single_column | 0.4785 | `glm_ocr` | 0.4928 | 0.616 | no | no | 27 |
| `jiaocaineedrop_jiaocai_needrop_en_349.jpg` | exam_paper|simplified_chinese|other_layout | 0.4373 | `mineru_pipeline` | 0.5347 | 0.000 | yes | yes | 237 |
| `page-5cb4b2fe-c14d-450e-9b97-4b6e7c99493b.png` | academic_literature|english|single_column | 0.4373 | `ovisocr2` | 0.4470 | 0.498 | yes | yes | 9 |
| `PPT_LEP power point presentation-English-FINAL-10-31-07_page_010.png` | PPT2PDF|english|single_column | 0.4205 | `deepseek_ocr2` | 0.4205 | 0.655 | no | no | 0 |
| `PPT_LEP power point presentation-English-FINAL-10-31-07_page_011.png` | PPT2PDF|english|single_column | 0.4191 | `hpd_parsing` | 0.4191 | 0.655 | no | no | 0 |
| `page-1cecd66d-3563-422a-a204-999bba0bb528.png` | academic_literature|english|single_column | 0.4151 | `mineru_vlm` | 0.4605 | 0.323 | yes | yes | 47 |
| `scihub_s12237-014-9873-7.pdf_4.jpg` | academic_literature|english|single_column | 0.3946 | `paddleocr_vl_1_6` | 0.3946 | 0.681 | yes | yes | 8 |

## Surface `parsebench:chart` — 568 units, 12 models

Ground truth for SCLR: PARTIAL — asserted chart labels and values only

| arm | n | mean loss | 95% CI | IRR proxy | hard fail | regret | unresolved | escalation | strong | SCLR/unit | SCLR/opp | $/1k | GPU s/unit | p50 ms | p95 ms | p99 ms | ledger s |
| --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `ORACLE_DIAGNOSTIC` | 568 | 0.3383 | [0.2529, 0.4131] | 0.6617 | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| `SINGLE:mineru_vlm` | 568 | 0.3952 | [0.3173, 0.4654] | 0.6048 | 357 | 0.0569 | 0.000 | 0.000 | 0.000 | 0.8081 | 0.4033 | 1.00 | 7.33 | n/a | n/a | n/a | 5.0 |
| `SINGLE:opus5_subscription` | 568 | 0.6930 | [0.5785, 0.7872] | 0.3070 | 416 | 0.3547 | 0.016 | 0.000 | 1.000 | 0.7289 | 0.4705 | n/a | n/a | 15554 | 24838 | 33841 | n/a |
| `ALWAYS_STRONG@opus5_subscription` | 568 | 0.6930 | [0.5785, 0.7872] | 0.3070 | 416 | 0.3547 | 0.016 | 0.000 | 1.000 | 0.7289 | 0.4705 | n/a | n/a | 15554 | 24838 | 33841 | n/a |
| `ABLATION:no_reconciler@opus5_subscription` | 568 | 0.8157 | [0.7335, 0.8828] | 0.1843 | 477 | 0.4774 | 0.000 | 0.516 | 0.516 | 0.8310 | 0.6193 | n/a | n/a | 10347 | 27450 | 33821 | n/a |
| `DISAGREEMENT_ONLY@opus5_subscription` | 568 | 0.8360 | [0.7564, 0.8984] | 0.1640 | 488 | 0.4977 | 0.000 | 0.454 | 0.454 | 0.8556 | 0.6444 | n/a | n/a | 5026 | 22329 | 29585 | n/a |
| `SINGLE:olmocr2` | 568 | 0.8795 | [0.8003, 0.9413] | 0.1205 | 515 | 0.5413 | 0.000 | 0.000 | 0.000 | 0.8539 | 0.7080 | 7.64 | 37.19 | n/a | n/a | n/a | 13.0 |
| `CRITICAL_TOKEN_ONLY@opus5_subscription` | 568 | 0.9477 | [0.9109, 0.9749] | 0.0523 | 540 | 0.6094 | 0.000 | 0.121 | 0.121 | 0.9384 | 0.7840 | n/a | n/a | 3268 | 24215 | 33466 | n/a |
| `SINGLE:unlimited_ocr` | 568 | 0.9860 | [0.9727, 0.9963] | 0.0140 | 563 | 0.6477 | 0.002 | 0.000 | 1.000 | 0.9771 | 0.8166 | 29.17 | 142.97 | 16894 | 33455 | 57647 | 29.0 |
| `ALWAYS_STRONG@unlimited_ocr` | 568 | 0.9860 | [0.9727, 0.9963] | 0.0140 | 563 | 0.6477 | 0.002 | 0.000 | 1.000 | 0.9771 | 0.8166 | 29.17 | 142.97 | 16894 | 33455 | 57647 | 29.0 |
| `REPLAY_COMPOSITE_V1@opus5_subscription` | 568 | 0.9864 | [0.9710, 0.9971] | 0.0136 | 561 | 0.6481 | 0.000 | 0.516 | 0.516 | 0.9806 | 0.8136 | n/a | n/a | 10347 | 27450 | 33821 | n/a |
| `ABLATION:no_cost_objective@opus5_subscription` | 568 | 0.9864 | [0.9710, 0.9971] | 0.0136 | 561 | 0.6481 | 0.000 | 0.521 | 0.521 | 0.9806 | 0.8136 | n/a | n/a | 10471 | 27766 | 33821 | n/a |
| `ABLATION:no_prediction@opus5_subscription` | 568 | 0.9864 | [0.9710, 0.9971] | 0.0136 | 561 | 0.6481 | 0.000 | 0.516 | 0.516 | 0.9806 | 0.8136 | n/a | n/a | 10347 | 27450 | 33821 | n/a |
| `ABLATION:no_critical_loss_detector@opus5_subscription` | 568 | 0.9868 | [0.9711, 0.9976] | 0.0132 | 561 | 0.6485 | 0.000 | 0.454 | 0.454 | 0.9789 | 0.8161 | n/a | n/a | 5026 | 22329 | 29585 | n/a |
| `PREDICTION_ONLY@opus5_subscription` | 568 | 0.9875 | [0.9752, 0.9960] | 0.0125 | 562 | 0.6492 | 0.000 | 0.011 | 0.011 | 0.9824 | 0.8311 | n/a | n/a | 1660 | 2447 | 14274 | n/a |
| `SINGLE:hpd_parsing` | 568 | 0.9879 | [0.9757, 0.9963] | 0.0121 | 563 | 0.6497 | 0.000 | 0.000 | 0.000 | 0.9824 | 0.8227 | 20.78 | 21.70 | 990 | 2121 | 4968 | 3.0 |
| `CORE_ROUTER@speed,ro=0` | 568 | 0.9879 | [0.9757, 0.9963] | 0.0121 | 563 | 0.6497 | 0.000 | 0.000 | 0.000 | 0.9824 | 0.8227 | 20.78 | 21.70 | 990 | 2121 | 4968 | 3.0 |
| `ABLATION:no_reconciler@unlimited_ocr` | 568 | 0.9880 | [0.9759, 0.9969] | 0.0120 | 564 | 0.6497 | 0.000 | 0.516 | 0.516 | 0.9824 | 0.8220 | 24.81 | 121.22 | 6623 | 35499 | 52387 | 23.0 |
| `ABLATION:no_disagreement@opus5_subscription` | 568 | 0.9881 | [0.9754, 0.9971] | 0.0119 | 562 | 0.6498 | 0.000 | 0.127 | 0.127 | 0.9842 | 0.8245 | n/a | n/a | 3282 | 24215 | 33466 | n/a |
| `DISAGREEMENT_ONLY@unlimited_ocr` | 568 | 0.9889 | [0.9766, 0.9976] | 0.0111 | 564 | 0.6506 | 0.000 | 0.454 | 0.454 | 0.9842 | 0.8258 | 23.01 | 112.41 | 4925 | 27763 | 39660 | 21.2 |
| `CRITICAL_TOKEN_ONLY@unlimited_ocr` | 568 | 0.9898 | [0.9790, 0.9974] | 0.0102 | 564 | 0.6515 | 0.000 | 0.121 | 0.121 | 0.9824 | 0.8294 | 13.30 | 64.83 | 3268 | 28835 | 46089 | 11.5 |
| `SINGLE:deepseek_ocr2` | 568 | 0.9900 | [0.9786, 0.9979] | 0.0100 | 564 | 0.6517 | 0.000 | 0.000 | 0.000 | 0.9859 | 0.8351 | 11.35 | 55.20 | n/a | n/a | n/a | 27.0 |
| `SINGLE:ovisocr2` | 568 | 0.9902 | [0.9784, 0.9984] | 0.0098 | 564 | 0.6519 | 0.000 | 0.000 | 0.000 | 0.9842 | 0.8141 | 4.84 | 23.54 | 1486 | 2871 | 4399 | 4.0 |
| `REPLAY_COMPOSITE_V1@unlimited_ocr` | 568 | 0.9902 | [0.9792, 0.9976] | 0.0098 | 564 | 0.6519 | 0.000 | 0.516 | 0.516 | 0.9824 | 0.8263 | 24.81 | 121.22 | 6623 | 35499 | 52387 | 23.0 |
| `ABLATION:no_disagreement@unlimited_ocr` | 568 | 0.9902 | [0.9792, 0.9976] | 0.0098 | 564 | 0.6519 | 0.000 | 0.127 | 0.127 | 0.9842 | 0.8304 | 13.45 | 65.59 | 3282 | 28835 | 46089 | 11.7 |
| `ABLATION:no_cost_objective@unlimited_ocr` | 568 | 0.9902 | [0.9792, 0.9976] | 0.0098 | 564 | 0.6519 | 0.000 | 0.521 | 0.521 | 0.9824 | 0.8263 | 24.96 | 121.97 | 6624 | 35725 | 52387 | 23.1 |
| `ABLATION:no_prediction@unlimited_ocr` | 568 | 0.9902 | [0.9792, 0.9976] | 0.0098 | 564 | 0.6519 | 0.000 | 0.516 | 0.516 | 0.9824 | 0.8263 | 24.81 | 121.22 | 6623 | 35499 | 52387 | 23.0 |
| `ABLATION:no_critical_loss_detector@unlimited_ocr` | 568 | 0.9907 | [0.9794, 0.9981] | 0.0093 | 564 | 0.6524 | 0.000 | 0.454 | 0.454 | 0.9824 | 0.8293 | 23.01 | 112.41 | 4925 | 27763 | 39660 | 21.2 |
| `PRIMARY_ONLY` | 568 | 0.9910 | [0.9800, 0.9982] | 0.0090 | 564 | 0.6527 | 0.000 | 0.000 | 0.000 | 0.9859 | 0.8359 | 4.92 | 23.93 | 1657 | 2422 | 3915 | 4.0 |
| `SINGLE:paddleocr_vl_1_6` | 568 | 0.9910 | [0.9800, 0.9982] | 0.0090 | 564 | 0.6527 | 0.000 | 0.000 | 0.000 | 0.9859 | 0.8359 | 4.92 | 23.93 | 1657 | 2422 | 3915 | 4.0 |
| `PREDICTION_ONLY@unlimited_ocr` | 568 | 0.9910 | [0.9800, 0.9982] | 0.0090 | 564 | 0.6527 | 0.000 | 0.011 | 0.011 | 0.9859 | 0.8366 | 5.23 | 25.44 | 1660 | 2447 | 8972 | 4.3 |
| `CORE_ROUTER@balanced,ro=0` | 568 | 0.9910 | [0.9800, 0.9982] | 0.0090 | 564 | 0.6527 | 0.000 | 0.000 | 0.000 | 0.9859 | 0.8359 | 4.92 | 23.93 | 1657 | 2422 | 3915 | 4.0 |
| `SINGLE:infinity_parser2_flash` | 568 | 0.9916 | [0.9807, 0.9988] | 0.0084 | 564 | 0.6534 | 0.000 | 0.000 | 0.000 | 0.9859 | 0.8330 | 0.80 | 3.87 | n/a | n/a | n/a | n/a |
| `SINGLE:mineru_pipeline` | 568 | 0.9921 | [0.9815, 0.9992] | 0.0079 | 564 | 0.6538 | 0.000 | 0.000 | 0.000 | 0.9842 | 0.8410 | 4.95 | 24.09 | n/a | n/a | n/a | 4.0 |
| `ALWAYS_ALL_RECONCILED` | 568 | 0.9921 | [0.9815, 0.9992] | 0.0079 | 564 | 0.6538 | 0.000 | 1.000 | 1.000 | 0.9859 | 0.8290 | n/a | n/a | n/a | n/a | n/a | n/a |
| `SINGLE:monkeyocrv2_b` | 568 | 0.9925 | [0.9826, 0.9992] | 0.0075 | 565 | 0.6542 | 0.018 | 0.000 | 0.000 | 0.9683 | 0.8170 | 5.60 | 27.25 | n/a | n/a | n/a | 6.0 |
| `SINGLE:glm_ocr` | 568 | 0.9965 | [0.9907, 1.0000] | 0.0035 | 566 | 0.6582 | 0.000 | 0.000 | 0.000 | 0.8151 | 0.5171 | 8.57 | 33.76 | n/a | n/a | n/a | 5.0 |
| `CORE_ROUTER@balanced,ro=1` | 568 | 1.0000 | [1.0000, 1.0000] | 0.0000 | 568 | 0.6617 | 0.993 | 0.000 | 0.000 | 0.0070 | 0.0054 | 0.03 | 0.17 | 808 | 1796 | 1796 | 0.0 |
| `CORE_ROUTER@balanced,sentinels` | 568 | 1.0000 | [1.0000, 1.0000] | 0.0000 | 568 | 0.6617 | 0.993 | 0.000 | 0.000 | 0.0070 | 0.0054 | 0.03 | 0.17 | 808 | 1796 | 1796 | 0.0 |
| `CORE_ROUTER@speed,ro=1` | 568 | 1.0000 | [1.0000, 1.0000] | 0.0000 | 568 | 0.6617 | 0.993 | 0.000 | 0.000 | 0.0070 | 0.0054 | 0.15 | 0.15 | 790 | 876 | 876 | 0.0 |
| `CORE_ROUTER@speed,sentinels` | 568 | 1.0000 | [1.0000, 1.0000] | 0.0000 | 568 | 0.6617 | 0.993 | 0.000 | 0.000 | 0.0070 | 0.0054 | 0.03 | 0.17 | 808 | 1796 | 1796 | 0.0 |

Best fixed single: `SINGLE:mineru_vlm`. Oracle headroom 0.0574 [0.0340, 0.0873] over 99 document-family clusters.

### Section 17 Oracle capture ratio `(best_fixed - arm) / (best_fixed - oracle)`

| arm | capture | 95% CI |
| --- | ---: | --- |
| `ORACLE_DIAGNOSTIC` | 1.000 | [1.000, 1.000] |
| `SINGLE:mineru_vlm` | 0.000 | [0.000, 0.000] |
| `SINGLE:opus5_subscription` | -5.589 | [-10.143, -2.798] |
| `ALWAYS_STRONG@opus5_subscription` | -5.589 | [-10.143, -2.798] |
| `ABLATION:no_reconciler@opus5_subscription` | -7.828 | [-13.231, -4.343] |
| `DISAGREEMENT_ONLY@opus5_subscription` | -8.187 | [-13.790, -4.556] |
| `SINGLE:olmocr2` | -8.983 | [-14.740, -5.322] |
| `CRITICAL_TOKEN_ONLY@opus5_subscription` | -10.231 | [-16.433, -6.134] |
| `SINGLE:unlimited_ocr` | -10.920 | [-17.330, -6.603] |
| `ALWAYS_STRONG@unlimited_ocr` | -10.920 | [-17.330, -6.603] |
| `REPLAY_COMPOSITE_V1@opus5_subscription` | -10.923 | [-17.308, -6.603] |
| `ABLATION:no_cost_objective@opus5_subscription` | -10.923 | [-17.308, -6.603] |
| `ABLATION:no_prediction@opus5_subscription` | -10.923 | [-17.308, -6.603] |
| `ABLATION:no_critical_loss_detector@opus5_subscription` | -10.930 | [-17.308, -6.603] |
| `PREDICTION_ONLY@opus5_subscription` | -10.948 | [-17.337, -6.604] |
| `SINGLE:hpd_parsing` | -10.954 | [-17.312, -6.602] |
| `CORE_ROUTER@speed,ro=0` | -10.954 | [-17.312, -6.602] |
| `ABLATION:no_reconciler@unlimited_ocr` | -10.955 | [-17.356, -6.627] |
| `ABLATION:no_disagreement@opus5_subscription` | -10.956 | [-17.348, -6.629] |
| `DISAGREEMENT_ONLY@unlimited_ocr` | -10.970 | [-17.356, -6.639] |
| `CRITICAL_TOKEN_ONLY@unlimited_ocr` | -10.988 | [-17.386, -6.652] |
| `SINGLE:deepseek_ocr2` | -10.990 | [-17.383, -6.654] |
| `SINGLE:ovisocr2` | -10.996 | [-17.385, -6.644] |
| `REPLAY_COMPOSITE_V1@unlimited_ocr` | -10.996 | [-17.396, -6.658] |
| `ABLATION:no_disagreement@unlimited_ocr` | -10.996 | [-17.396, -6.658] |
| `ABLATION:no_cost_objective@unlimited_ocr` | -10.996 | [-17.396, -6.658] |
| `ABLATION:no_prediction@unlimited_ocr` | -10.996 | [-17.396, -6.658] |
| `ABLATION:no_critical_loss_detector@unlimited_ocr` | -11.003 | [-17.396, -6.658] |
| `PRIMARY_ONLY` | -11.010 | [-17.404, -6.658] |
| `SINGLE:paddleocr_vl_1_6` | -11.010 | [-17.404, -6.658] |
| `PREDICTION_ONLY@unlimited_ocr` | -11.010 | [-17.404, -6.658] |
| `CORE_ROUTER@balanced,ro=0` | -11.010 | [-17.404, -6.658] |
| `SINGLE:infinity_parser2_flash` | -11.022 | [-17.429, -6.662] |
| `SINGLE:mineru_pipeline` | -11.030 | [-17.429, -6.669] |
| `ALWAYS_ALL_RECONCILED` | -11.030 | [-17.429, -6.669] |
| `SINGLE:monkeyocrv2_b` | -11.038 | [-17.441, -6.681] |
| `SINGLE:glm_ocr` | -11.113 | [-17.522, -6.710] |
| `CORE_ROUTER@balanced,ro=1` | -11.180 | [-17.620, -6.752] |
| `CORE_ROUTER@balanced,sentinels` | -11.180 | [-17.620, -6.752] |
| `CORE_ROUTER@speed,ro=1` | -11.180 | [-17.620, -6.752] |
| `CORE_ROUTER@speed,sentinels` | -11.180 | [-17.620, -6.752] |

### Disagreement conditionals (section 92), worst pairs

| a | b | n | agree rate | P(a wrong \| agree) | P(a wrong \| disagree) | P(both wrong AND agree) |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `hpd_parsing` | `unlimited_ocr` | 567 | 0.970 | 0.993 | 0.941 | 0.963 |
| `hpd_parsing` | `infinity_parser2_flash` | 568 | 0.965 | 0.993 | 0.950 | 0.958 |
| `infinity_parser2_flash` | `unlimited_ocr` | 567 | 0.966 | 0.993 | 1.000 | 0.958 |
| `hpd_parsing` | `ovisocr2` | 568 | 0.947 | 0.993 | 0.967 | 0.940 |
| `infinity_parser2_flash` | `ovisocr2` | 568 | 0.945 | 0.993 | 1.000 | 0.938 |
| `ovisocr2` | `unlimited_ocr` | 567 | 0.947 | 0.993 | 1.000 | 0.938 |
| `deepseek_ocr2` | `mineru_pipeline` | 568 | 0.898 | 0.992 | 1.000 | 0.891 |
| `infinity_parser2_flash` | `monkeyocrv2_b` | 558 | 0.880 | 0.992 | 1.000 | 0.873 |
| `monkeyocrv2_b` | `unlimited_ocr` | 557 | 0.878 | 0.994 | 1.000 | 0.871 |
| `hpd_parsing` | `monkeyocrv2_b` | 558 | 0.862 | 0.992 | 0.987 | 0.855 |
| `deepseek_ocr2` | `unlimited_ocr` | 567 | 0.857 | 0.992 | 1.000 | 0.850 |
| `deepseek_ocr2` | `infinity_parser2_flash` | 568 | 0.850 | 0.992 | 1.000 | 0.843 |

### Catastrophic failure appendix (top units the Oracle also fails)

| unit | page class | oracle loss | best model | primary loss | blind risk | disagreed? | L2 flagged? | critical events |
| --- | --- | ---: | --- | ---: | ---: | :-: | :-: | ---: |
| `chart/(Web_version)_E-Government_Survey_2024_1392024_p62` | chart | 1.0000 | `deepseek_ocr2` | 1.0000 | 0.000 | no | no | 8 |
| `chart/05021ff2-en_p19` | chart,need_estimate | 1.0000 | `deepseek_ocr2` | 1.0000 | 0.000 | no | no | 14 |
| `chart/2023-05-sigma-01-english_p23` | chart,need_estimate | 1.0000 | `deepseek_ocr2` | 1.0000 | 0.000 | yes | yes | 12 |
| `chart/2025-EIS_p108` | chart,need_estimate | 1.0000 | `deepseek_ocr2` | 1.0000 | 0.000 | yes | no | 10 |
| `chart/2025-EIS_p12` | chart,need_estimate | 1.0000 | `deepseek_ocr2` | 1.0000 | 0.000 | yes | no | 10 |
| `chart/2025-EIS_p35` | chart,need_estimate | 1.0000 | `deepseek_ocr2` | 1.0000 | 0.000 | yes | no | 10 |
| `chart/2025-EIS_p37` | chart,need_estimate | 1.0000 | `deepseek_ocr2` | 1.0000 | 0.000 | yes | no | 8 |
| `chart/2025-EIS_p41` | chart,need_estimate | 1.0000 | `deepseek_ocr2` | 1.0000 | 0.000 | yes | no | 9 |
| `chart/2025-EIS_p43` | chart,need_estimate | 1.0000 | `deepseek_ocr2` | 1.0000 | 0.000 | yes | no | 9 |
| `chart/2025-EIS_p45` | chart,need_estimate | 1.0000 | `deepseek_ocr2` | 1.0000 | 0.000 | yes | no | 10 |

## Surface `parsebench:table` — 503 units, 12 models

Ground truth for SCLR: FULL for tables — expected_markdown per document

| arm | n | mean loss | 95% CI | IRR proxy | hard fail | regret | unresolved | escalation | strong | SCLR/unit | SCLR/opp | $/1k | GPU s/unit | p50 ms | p95 ms | p99 ms | ledger s |
| --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `ORACLE_DIAGNOSTIC` | 503 | 0.0876 | [0.0651, 0.1119] | 0.9124 | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| `SINGLE:opus5_subscription` | 503 | 0.1839 | [0.1512, 0.2134] | 0.8161 | 358 | 0.0963 | 0.000 | 0.000 | 1.000 | 0.5507 | 0.0128 | n/a | n/a | 17690 | 53740 | 191206 | n/a |
| `ALWAYS_STRONG@opus5_subscription` | 503 | 0.1839 | [0.1512, 0.2134] | 0.8161 | 358 | 0.0963 | 0.000 | 0.000 | 1.000 | 0.5507 | 0.0128 | n/a | n/a | 17690 | 53740 | 191206 | n/a |
| `ABLATION:no_reconciler@opus5_subscription` | 503 | 0.1857 | [0.1477, 0.2179] | 0.8143 | 364 | 0.0981 | 0.000 | 0.571 | 0.571 | 0.4473 | 0.0125 | n/a | n/a | 15465 | 77762 | 248800 | n/a |
| `DISAGREEMENT_ONLY@opus5_subscription` | 503 | 0.1909 | [0.1503, 0.2235] | 0.8091 | 375 | 0.1033 | 0.000 | 0.410 | 0.410 | 0.4553 | 0.0152 | n/a | n/a | 11523 | 65614 | 248800 | n/a |
| `SINGLE:ovisocr2` | 503 | 0.2015 | [0.1682, 0.2263] | 0.7985 | 411 | 0.1140 | 0.000 | 0.000 | 0.000 | 0.3439 | 0.0654 | 4.84 | 23.54 | 3277 | 16175 | 40856 | 4.0 |
| `PREDICTION_ONLY@opus5_subscription` | 503 | 0.2076 | [0.1696, 0.2426] | 0.7924 | 369 | 0.1201 | 0.000 | 0.654 | 0.654 | 0.5268 | 0.0289 | n/a | n/a | 16896 | 66624 | 144955 | n/a |
| `ALWAYS_ALL_RECONCILED` | 503 | 0.2117 | [0.1675, 0.2418] | 0.7883 | 407 | 0.1241 | 0.000 | 1.000 | 1.000 | 0.3479 | 0.0549 | n/a | n/a | n/a | n/a | n/a | n/a |
| `ABLATION:no_cost_objective@opus5_subscription` | 503 | 0.2126 | [0.1743, 0.2386] | 0.7874 | 414 | 0.1250 | 0.000 | 0.867 | 0.867 | 0.3698 | 0.0838 | n/a | n/a | 22645 | 82485 | 248800 | n/a |
| `ABLATION:no_cost_objective@unlimited_ocr` | 503 | 0.2132 | [0.1726, 0.2451] | 0.7868 | 406 | 0.1256 | 0.000 | 0.867 | 0.867 | 0.3539 | 0.0652 | 35.04 | 171.39 | 32169 | 116703 | 210786 | 33.1 |
| `SINGLE:mineru_vlm` | 503 | 0.2137 | [0.1735, 0.2412] | 0.7863 | 407 | 0.1261 | 0.000 | 0.000 | 0.000 | 0.3360 | 0.0623 | 1.00 | 7.33 | n/a | n/a | n/a | 5.0 |
| `REPLAY_COMPOSITE_V1@opus5_subscription` | 503 | 0.2162 | [0.1744, 0.2439] | 0.7838 | 415 | 0.1286 | 0.000 | 0.571 | 0.571 | 0.3837 | 0.0849 | n/a | n/a | 15465 | 77762 | 248800 | n/a |
| `ABLATION:no_prediction@opus5_subscription` | 503 | 0.2162 | [0.1744, 0.2439] | 0.7838 | 415 | 0.1286 | 0.000 | 0.571 | 0.571 | 0.3837 | 0.0849 | n/a | n/a | 15465 | 77762 | 248800 | n/a |
| `REPLAY_COMPOSITE_V1@unlimited_ocr` | 503 | 0.2174 | [0.1725, 0.2503] | 0.7826 | 411 | 0.1298 | 0.000 | 0.571 | 0.571 | 0.3817 | 0.0665 | 26.40 | 129.04 | 16480 | 100604 | 184513 | 24.5 |
| `ABLATION:no_prediction@unlimited_ocr` | 503 | 0.2174 | [0.1725, 0.2503] | 0.7826 | 411 | 0.1298 | 0.000 | 0.571 | 0.571 | 0.3817 | 0.0665 | 26.40 | 129.04 | 16480 | 100604 | 184513 | 24.5 |
| `ABLATION:no_critical_loss_detector@opus5_subscription` | 503 | 0.2224 | [0.1779, 0.2524] | 0.7776 | 420 | 0.1348 | 0.000 | 0.410 | 0.410 | 0.4195 | 0.0889 | n/a | n/a | 11523 | 65614 | 248800 | n/a |
| `ABLATION:no_critical_loss_detector@unlimited_ocr` | 503 | 0.2229 | [0.1748, 0.2572] | 0.7771 | 417 | 0.1353 | 0.000 | 0.410 | 0.410 | 0.4155 | 0.0705 | 21.70 | 106.02 | 11855 | 84586 | 184513 | 19.9 |
| `ABLATION:no_disagreement@unlimited_ocr` | 503 | 0.2299 | [0.1828, 0.2650] | 0.7701 | 413 | 0.1423 | 0.000 | 0.465 | 0.465 | 0.3877 | 0.0741 | 23.33 | 113.98 | 13511 | 100604 | 184513 | 21.5 |
| `ABLATION:no_disagreement@opus5_subscription` | 503 | 0.2301 | [0.1859, 0.2599] | 0.7699 | 417 | 0.1425 | 0.000 | 0.465 | 0.465 | 0.3917 | 0.0925 | n/a | n/a | 13021 | 67856 | 186992 | n/a |
| `CRITICAL_TOKEN_ONLY@opus5_subscription` | 503 | 0.2340 | [0.1870, 0.2642] | 0.7660 | 409 | 0.1465 | 0.000 | 0.272 | 0.272 | 0.4394 | 0.0958 | n/a | n/a | 9754 | 56562 | 82166 | n/a |
| `SINGLE:hpd_parsing` | 503 | 0.2397 | [0.1966, 0.2686] | 0.7603 | 423 | 0.1521 | 0.000 | 0.000 | 0.000 | 0.4553 | 0.1077 | 20.78 | 21.70 | 2105 | 15403 | 23241 | 3.0 |
| `CORE_ROUTER@speed,ro=0` | 503 | 0.2397 | [0.1966, 0.2686] | 0.7603 | 423 | 0.1521 | 0.000 | 0.000 | 0.000 | 0.4553 | 0.1077 | 20.78 | 21.70 | 2105 | 15403 | 23241 | 3.0 |
| `ABLATION:no_reconciler@unlimited_ocr` | 503 | 0.2430 | [0.1886, 0.2786] | 0.7570 | 416 | 0.1554 | 0.000 | 0.571 | 0.571 | 0.4354 | 0.0855 | 26.40 | 129.04 | 16480 | 100604 | 184513 | 24.5 |
| `DISAGREEMENT_ONLY@unlimited_ocr` | 503 | 0.2450 | [0.1898, 0.2812] | 0.7550 | 420 | 0.1575 | 0.000 | 0.410 | 0.410 | 0.4513 | 0.0869 | 21.70 | 106.02 | 11855 | 84586 | 184513 | 19.9 |
| `CRITICAL_TOKEN_ONLY@unlimited_ocr` | 503 | 0.2525 | [0.1963, 0.2877] | 0.7475 | 422 | 0.1649 | 0.000 | 0.272 | 0.272 | 0.4274 | 0.1087 | 17.70 | 86.41 | 9593 | 70462 | 123964 | 15.9 |
| `SINGLE:unlimited_ocr` | 503 | 0.2528 | [0.2039, 0.2838] | 0.7472 | 420 | 0.1652 | 0.016 | 0.000 | 1.000 | 0.4314 | 0.0616 | 29.17 | 142.97 | 27916 | 92224 | 153231 | 29.0 |
| `ALWAYS_STRONG@unlimited_ocr` | 503 | 0.2528 | [0.2039, 0.2838] | 0.7472 | 420 | 0.1652 | 0.016 | 0.000 | 1.000 | 0.4314 | 0.0616 | 29.17 | 142.97 | 27916 | 92224 | 153231 | 29.0 |
| `PREDICTION_ONLY@unlimited_ocr` | 503 | 0.2591 | [0.2058, 0.2938] | 0.7409 | 421 | 0.1715 | 0.000 | 0.654 | 0.654 | 0.4692 | 0.0942 | 24.00 | 117.44 | 23608 | 101682 | 169884 | 23.0 |
| `SINGLE:infinity_parser2_flash` | 503 | 0.2606 | [0.2005, 0.2981] | 0.7394 | 409 | 0.1730 | 0.000 | 0.000 | 0.000 | 0.4612 | 0.0749 | 0.80 | 3.87 | n/a | n/a | n/a | n/a |
| `PRIMARY_ONLY` | 503 | 0.2650 | [0.2078, 0.3001] | 0.7350 | 426 | 0.1774 | 0.000 | 0.000 | 0.000 | 0.4592 | 0.1114 | 4.92 | 23.93 | 2854 | 16288 | 16894 | 4.0 |
| `SINGLE:paddleocr_vl_1_6` | 503 | 0.2650 | [0.2078, 0.3001] | 0.7350 | 426 | 0.1774 | 0.000 | 0.000 | 0.000 | 0.4592 | 0.1114 | 4.92 | 23.93 | 2854 | 16288 | 16894 | 4.0 |
| `CORE_ROUTER@balanced,ro=0` | 503 | 0.2650 | [0.2078, 0.3001] | 0.7350 | 426 | 0.1774 | 0.000 | 0.000 | 0.000 | 0.4592 | 0.1114 | 4.92 | 23.93 | 2854 | 16288 | 16894 | 4.0 |
| `SINGLE:olmocr2` | 503 | 0.2667 | [0.2239, 0.3020] | 0.7333 | 351 | 0.1791 | 0.000 | 0.000 | 0.000 | 0.5010 | 0.1341 | 7.64 | 37.19 | n/a | n/a | n/a | 13.0 |
| `SINGLE:monkeyocrv2_b` | 503 | 0.3012 | [0.2300, 0.3439] | 0.6988 | 423 | 0.2136 | 0.014 | 0.000 | 0.000 | 0.4254 | 0.0938 | 5.60 | 27.25 | n/a | n/a | n/a | 6.0 |
| `SINGLE:deepseek_ocr2` | 503 | 0.3031 | [0.2503, 0.3372] | 0.6969 | 445 | 0.2155 | 0.000 | 0.000 | 0.000 | 0.6660 | 0.1635 | 11.35 | 55.20 | n/a | n/a | n/a | 27.0 |
| `SINGLE:mineru_pipeline` | 503 | 0.3593 | [0.3212, 0.3866] | 0.6407 | 462 | 0.2717 | 0.000 | 0.000 | 0.000 | 0.6103 | 0.1393 | 4.95 | 24.09 | n/a | n/a | n/a | 4.0 |
| `SINGLE:glm_ocr` | 503 | 0.7077 | [0.6312, 0.7570] | 0.2923 | 473 | 0.6201 | 0.000 | 0.000 | 0.000 | 0.5070 | 0.1235 | 8.57 | 33.76 | n/a | n/a | n/a | 5.0 |
| `CORE_ROUTER@speed,ro=1` | 503 | 0.9611 | [0.9277, 0.9822] | 0.0389 | 499 | 0.8735 | 0.948 | 0.000 | 0.000 | 0.0159 | 0.0005 | 1.07 | 1.12 | 1072 | 4896 | 5856 | 0.2 |
| `CORE_ROUTER@balanced,ro=1` | 503 | 0.9614 | [0.9288, 0.9826] | 0.0386 | 501 | 0.8738 | 0.948 | 0.000 | 0.000 | 0.0179 | 0.0005 | 0.25 | 1.24 | 1741 | 5540 | 5891 | 0.2 |
| `CORE_ROUTER@balanced,sentinels` | 503 | 0.9614 | [0.9288, 0.9826] | 0.0386 | 501 | 0.8738 | 0.948 | 0.000 | 0.000 | 0.0179 | 0.0005 | 0.25 | 1.24 | 1741 | 5540 | 5891 | 0.2 |
| `CORE_ROUTER@speed,sentinels` | 503 | 0.9614 | [0.9288, 0.9826] | 0.0386 | 501 | 0.8738 | 0.948 | 0.000 | 0.000 | 0.0179 | 0.0005 | 0.25 | 1.24 | 1741 | 5540 | 5891 | 0.2 |

Best fixed single: `SINGLE:opus5_subscription`. Oracle headroom 0.0956 [0.0800, 0.1108] over 94 document-family clusters.

### Section 17 Oracle capture ratio `(best_fixed - arm) / (best_fixed - oracle)`

| arm | capture | 95% CI |
| --- | ---: | --- |
| `ORACLE_DIAGNOSTIC` | 1.000 | [1.000, 1.000] |
| `SINGLE:opus5_subscription` | -0.007 | [-0.107, 0.000] |
| `ALWAYS_STRONG@opus5_subscription` | -0.007 | [-0.107, 0.000] |
| `ABLATION:no_reconciler@opus5_subscription` | -0.021 | [-0.167, 0.167] |
| `DISAGREEMENT_ONLY@opus5_subscription` | -0.072 | [-0.269, 0.152] |
| `SINGLE:ovisocr2` | -0.193 | [-0.452, 0.000] |
| `PREDICTION_ONLY@opus5_subscription` | -0.257 | [-0.455, -0.070] |
| `ALWAYS_ALL_RECONCILED` | -0.288 | [-0.575, 0.007] |
| `ABLATION:no_cost_objective@opus5_subscription` | -0.304 | [-0.604, -0.054] |
| `ABLATION:no_cost_objective@unlimited_ocr` | -0.308 | [-0.583, -0.038] |
| `SINGLE:mineru_vlm` | -0.313 | [-0.606, -0.051] |
| `REPLAY_COMPOSITE_V1@opus5_subscription` | -0.340 | [-0.656, -0.058] |
| `ABLATION:no_prediction@opus5_subscription` | -0.340 | [-0.656, -0.058] |
| `REPLAY_COMPOSITE_V1@unlimited_ocr` | -0.348 | [-0.646, -0.045] |
| `ABLATION:no_prediction@unlimited_ocr` | -0.348 | [-0.646, -0.045] |
| `ABLATION:no_critical_loss_detector@opus5_subscription` | -0.401 | [-0.738, -0.096] |
| `ABLATION:no_critical_loss_detector@unlimited_ocr` | -0.402 | [-0.729, -0.063] |
| `ABLATION:no_disagreement@unlimited_ocr` | -0.478 | [-0.837, -0.124] |
| `ABLATION:no_disagreement@opus5_subscription` | -0.485 | [-0.872, -0.153] |
| `CRITICAL_TOKEN_ONLY@opus5_subscription` | -0.522 | [-0.887, -0.174] |
| `SINGLE:hpd_parsing` | -0.594 | [-1.090, -0.205] |
| `CORE_ROUTER@speed,ro=0` | -0.594 | [-1.090, -0.205] |
| `ABLATION:no_reconciler@unlimited_ocr` | -0.609 | [-1.013, -0.200] |
| `DISAGREEMENT_ONLY@unlimited_ocr` | -0.630 | [-1.056, -0.200] |
| `CRITICAL_TOKEN_ONLY@unlimited_ocr` | -0.708 | [-1.160, -0.264] |
| `SINGLE:unlimited_ocr` | -0.720 | [-1.159, -0.319] |
| `ALWAYS_STRONG@unlimited_ocr` | -0.720 | [-1.159, -0.319] |
| `PREDICTION_ONLY@unlimited_ocr` | -0.784 | [-1.229, -0.366] |
| `SINGLE:infinity_parser2_flash` | -0.796 | [-1.336, -0.269] |
| `PRIMARY_ONLY` | -0.843 | [-1.335, -0.380] |
| `SINGLE:paddleocr_vl_1_6` | -0.843 | [-1.335, -0.380] |
| `CORE_ROUTER@balanced,ro=0` | -0.843 | [-1.335, -0.380] |
| `SINGLE:olmocr2` | -0.890 | [-1.574, -0.405] |
| `SINGLE:monkeyocrv2_b` | -1.214 | [-1.915, -0.570] |
| `SINGLE:deepseek_ocr2` | -1.251 | [-1.825, -0.757] |
| `SINGLE:mineru_pipeline` | -1.866 | [-2.670, -1.288] |
| `SINGLE:glm_ocr` | -5.512 | [-6.944, -4.304] |
| `CORE_ROUTER@speed,ro=1` | -8.212 | [-9.957, -6.862] |
| `CORE_ROUTER@balanced,ro=1` | -8.216 | [-9.933, -6.874] |
| `CORE_ROUTER@balanced,sentinels` | -8.216 | [-9.933, -6.874] |
| `CORE_ROUTER@speed,sentinels` | -8.216 | [-9.933, -6.874] |

### Disagreement conditionals (section 92), worst pairs

| a | b | n | agree rate | P(a wrong \| agree) | P(a wrong \| disagree) | P(both wrong AND agree) |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `ovisocr2` | `unlimited_ocr` | 495 | 0.891 | 0.803 | 0.926 | 0.683 |
| `hpd_parsing` | `ovisocr2` | 503 | 0.881 | 0.824 | 0.967 | 0.682 |
| `hpd_parsing` | `unlimited_ocr` | 495 | 0.853 | 0.818 | 0.959 | 0.671 |
| `mineru_vlm` | `ovisocr2` | 503 | 0.827 | 0.779 | 0.954 | 0.626 |
| `deepseek_ocr2` | `mineru_vlm` | 499 | 0.802 | 0.858 | 0.990 | 0.619 |
| `mineru_vlm` | `unlimited_ocr` | 495 | 0.818 | 0.783 | 0.911 | 0.618 |
| `hpd_parsing` | `mineru_vlm` | 503 | 0.791 | 0.812 | 0.952 | 0.602 |
| `deepseek_ocr2` | `hpd_parsing` | 499 | 0.760 | 0.852 | 0.983 | 0.593 |
| `monkeyocrv2_b` | `ovisocr2` | 496 | 0.794 | 0.799 | 0.990 | 0.593 |
| `deepseek_ocr2` | `ovisocr2` | 499 | 0.760 | 0.847 | 1.000 | 0.587 |
| `monkeyocrv2_b` | `unlimited_ocr` | 488 | 0.762 | 0.801 | 0.957 | 0.584 |
| `deepseek_ocr2` | `unlimited_ocr` | 491 | 0.764 | 0.845 | 1.000 | 0.582 |

### Catastrophic failure appendix (top units the Oracle also fails)

| unit | page class | oracle loss | best model | primary loss | blind risk | disagreed? | L2 flagged? | critical events |
| --- | --- | ---: | --- | ---: | ---: | :-: | :-: | ---: |
| `table/SERFF_CA_random_pages 1_page46` | table,easy | 0.9673 | `deepseek_ocr2` | 0.9717 | 0.780 | no | no | 0 |
| `table/SERFF_CA_random_pages 1_page316` | table,easy | 0.8720 | `olmocr2` | 0.8745 | 0.783 | no | no | 3 |
| `table/SERFF_CA_random_pages 1_page283` | table,easy | 0.8481 | `infinity_parser2_flash` | 0.8603 | 0.577 | no | yes | 9 |
| `table/SERFF_CA_random_pages 1_page275` | table,easy | 0.8132 | `paddleocr_vl_1_6` | 0.8132 | 0.664 | no | no | 4 |
| `table/SERFF_CA_random_pages 1_page883` | table,easy | 0.7678 | `olmocr2` | 0.7953 | 0.588 | yes | yes | 19 |
| `table/SERFF_CA_random_pages 1_page1724` | table,easy | 0.7245 | `deepseek_ocr2` | 0.7405 | 0.946 | yes | no | 4 |
| `table/test_page1` | table,hard | 0.7025 | `opus5_subscription` | 0.7498 | 0.813 | no | no | 49 |
| `table/SERFF_CA_random_pages 1_page115` | table,easy | 0.6949 | `mineru_pipeline` | 0.7471 | 0.876 | no | no | 0 |
| `table/SERFF_CA_random_pages 1_page2248` | table,easy | 0.6920 | `infinity_parser2_flash` | 0.7272 | 0.691 | no | no | 0 |
| `table/Earnings Presentation (FY26 Q2)_page22` | table,easy | 0.6822 | `olmocr2` | 0.8185 | 0.622 | no | no | 8 |

## Surface `parsebench:text_content` — 506 units, 12 models

Ground truth for SCLR: PARTIAL — the bag-of-sentence keys only

| arm | n | mean loss | 95% CI | IRR proxy | hard fail | regret | unresolved | escalation | strong | SCLR/unit | SCLR/opp | $/1k | GPU s/unit | p50 ms | p95 ms | p99 ms | ledger s |
| --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `ORACLE_DIAGNOSTIC` | 506 | 0.0708 | [0.0597, 0.0826] | 0.9292 | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| `SINGLE:opus5_subscription` | 506 | 0.0886 | [0.0753, 0.1032] | 0.9114 | 202 | 0.0178 | 0.006 | 0.000 | 1.000 | 0.9763 | 0.6727 | n/a | n/a | 17551 | 53223 | 192216 | n/a |
| `ALWAYS_STRONG@opus5_subscription` | 506 | 0.0886 | [0.0753, 0.1032] | 0.9114 | 202 | 0.0178 | 0.006 | 0.000 | 1.000 | 0.9763 | 0.6727 | n/a | n/a | 17551 | 53223 | 192216 | n/a |
| `ALWAYS_ALL_RECONCILED` | 506 | 0.0955 | [0.0819, 0.1093] | 0.9045 | 213 | 0.0248 | 0.000 | 1.000 | 1.000 | 0.9842 | 0.6870 | n/a | n/a | n/a | n/a | n/a | n/a |
| `ABLATION:no_reconciler@opus5_subscription` | 506 | 0.1040 | [0.0920, 0.1166] | 0.8960 | 288 | 0.0332 | 0.000 | 0.397 | 0.397 | 0.9822 | 0.6930 | n/a | n/a | 5770 | 76788 | 252206 | n/a |
| `DISAGREEMENT_ONLY@opus5_subscription` | 506 | 0.1065 | [0.0947, 0.1189] | 0.8935 | 299 | 0.0357 | 0.000 | 0.326 | 0.326 | 0.9822 | 0.6963 | n/a | n/a | 5036 | 70572 | 252206 | n/a |
| `ABLATION:no_cost_objective@opus5_subscription` | 506 | 0.1167 | [0.1032, 0.1311] | 0.8833 | 292 | 0.0459 | 0.000 | 0.399 | 0.399 | 0.9822 | 0.6973 | n/a | n/a | 5770 | 76788 | 252206 | n/a |
| `REPLAY_COMPOSITE_V1@opus5_subscription` | 506 | 0.1167 | [0.1033, 0.1311] | 0.8833 | 292 | 0.0459 | 0.000 | 0.397 | 0.397 | 0.9822 | 0.6974 | n/a | n/a | 5770 | 76788 | 252206 | n/a |
| `ABLATION:no_prediction@opus5_subscription` | 506 | 0.1167 | [0.1033, 0.1311] | 0.8833 | 292 | 0.0459 | 0.000 | 0.397 | 0.397 | 0.9822 | 0.6974 | n/a | n/a | 5770 | 76788 | 252206 | n/a |
| `SINGLE:ovisocr2` | 506 | 0.1188 | [0.1016, 0.1376] | 0.8812 | 221 | 0.0480 | 0.000 | 0.000 | 0.000 | 0.9842 | 0.6901 | 4.84 | 23.54 | 1876 | 40849 | 41479 | 4.0 |
| `ABLATION:no_critical_loss_detector@opus5_subscription` | 506 | 0.1190 | [0.1057, 0.1333] | 0.8810 | 304 | 0.0482 | 0.000 | 0.326 | 0.326 | 0.9822 | 0.7006 | n/a | n/a | 5036 | 70572 | 252206 | n/a |
| `SINGLE:infinity_parser2_flash` | 506 | 0.1205 | [0.1041, 0.1375] | 0.8795 | 242 | 0.0497 | 0.000 | 0.000 | 0.000 | 0.9842 | 0.6971 | 0.80 | 3.87 | n/a | n/a | n/a | n/a |
| `SINGLE:unlimited_ocr` | 506 | 0.1288 | [0.1114, 0.1470] | 0.8712 | 249 | 0.0581 | 0.012 | 0.000 | 1.000 | 0.9723 | 0.6675 | 29.17 | 142.97 | 24695 | 72152 | 190980 | 29.0 |
| `ALWAYS_STRONG@unlimited_ocr` | 506 | 0.1288 | [0.1114, 0.1470] | 0.8712 | 249 | 0.0581 | 0.012 | 0.000 | 1.000 | 0.9723 | 0.6675 | 29.17 | 142.97 | 24695 | 72152 | 190980 | 29.0 |
| `ABLATION:no_cost_objective@unlimited_ocr` | 506 | 0.1306 | [0.1152, 0.1465] | 0.8694 | 309 | 0.0598 | 0.000 | 0.399 | 0.399 | 0.9842 | 0.7015 | 21.40 | 104.54 | 5289 | 81406 | 165150 | 19.6 |
| `REPLAY_COMPOSITE_V1@unlimited_ocr` | 506 | 0.1306 | [0.1152, 0.1465] | 0.8694 | 309 | 0.0598 | 0.000 | 0.397 | 0.397 | 0.9842 | 0.7015 | 21.34 | 104.26 | 5289 | 81406 | 165150 | 19.5 |
| `ABLATION:no_prediction@unlimited_ocr` | 506 | 0.1306 | [0.1152, 0.1465] | 0.8694 | 309 | 0.0598 | 0.000 | 0.397 | 0.397 | 0.9842 | 0.7015 | 21.34 | 104.26 | 5289 | 81406 | 165150 | 19.5 |
| `ABLATION:no_critical_loss_detector@unlimited_ocr` | 506 | 0.1326 | [0.1171, 0.1484] | 0.8674 | 319 | 0.0618 | 0.000 | 0.326 | 0.326 | 0.9842 | 0.7042 | 19.27 | 94.09 | 4860 | 67663 | 135824 | 17.5 |
| `ABLATION:no_reconciler@unlimited_ocr` | 506 | 0.1392 | [0.1228, 0.1561] | 0.8608 | 319 | 0.0684 | 0.000 | 0.397 | 0.397 | 0.9842 | 0.7045 | 21.34 | 104.26 | 5289 | 81406 | 165150 | 19.5 |
| `SINGLE:glm_ocr` | 506 | 0.1392 | [0.1218, 0.1569] | 0.8608 | 277 | 0.0685 | 0.000 | 0.000 | 0.000 | 0.9842 | 0.6955 | 8.57 | 33.76 | n/a | n/a | n/a | 5.0 |
| `DISAGREEMENT_ONLY@unlimited_ocr` | 506 | 0.1402 | [0.1239, 0.1568] | 0.8598 | 327 | 0.0694 | 0.000 | 0.326 | 0.326 | 0.9842 | 0.7071 | 19.27 | 94.09 | 4860 | 67663 | 135824 | 17.5 |
| `SINGLE:monkeyocrv2_b` | 506 | 0.1459 | [0.1275, 0.1660] | 0.8541 | 277 | 0.0752 | 0.016 | 0.000 | 0.000 | 0.9684 | 0.6884 | 5.60 | 27.25 | n/a | n/a | n/a | 6.0 |
| `SINGLE:mineru_vlm` | 506 | 0.1531 | [0.1358, 0.1708] | 0.8469 | 328 | 0.0823 | 0.000 | 0.000 | 0.000 | 0.9842 | 0.7117 | 1.00 | 7.33 | n/a | n/a | n/a | 5.0 |
| `CRITICAL_TOKEN_ONLY@opus5_subscription` | 506 | 0.1545 | [0.1377, 0.1730] | 0.8455 | 328 | 0.0837 | 0.000 | 0.126 | 0.126 | 0.9842 | 0.7134 | n/a | n/a | 4281 | 46694 | 70572 | n/a |
| `ABLATION:no_disagreement@opus5_subscription` | 506 | 0.1552 | [0.1381, 0.1737] | 0.8448 | 327 | 0.0845 | 0.000 | 0.134 | 0.134 | 0.9842 | 0.7130 | n/a | n/a | 4285 | 46694 | 78300 | n/a |
| `ABLATION:no_disagreement@unlimited_ocr` | 506 | 0.1592 | [0.1416, 0.1782] | 0.8408 | 332 | 0.0884 | 0.000 | 0.134 | 0.134 | 0.9842 | 0.7150 | 13.68 | 66.68 | 4285 | 57311 | 91507 | 11.9 |
| `CRITICAL_TOKEN_ONLY@unlimited_ocr` | 506 | 0.1611 | [0.1434, 0.1803] | 0.8389 | 336 | 0.0903 | 0.000 | 0.126 | 0.126 | 0.9842 | 0.7162 | 13.45 | 65.55 | 4281 | 57290 | 91507 | 11.7 |
| `PREDICTION_ONLY@opus5_subscription` | 506 | 0.1649 | [0.1474, 0.1836] | 0.8351 | 345 | 0.0941 | 0.000 | 0.012 | 0.012 | 0.9842 | 0.7203 | n/a | n/a | 1974 | 9871 | 19232 | n/a |
| `PREDICTION_ONLY@unlimited_ocr` | 506 | 0.1663 | [0.1488, 0.1849] | 0.8337 | 345 | 0.0955 | 0.000 | 0.012 | 0.012 | 0.9842 | 0.7221 | 5.26 | 25.62 | 1974 | 8914 | 19232 | 4.3 |
| `PRIMARY_ONLY` | 506 | 0.1672 | [0.1497, 0.1859] | 0.8328 | 345 | 0.0964 | 0.000 | 0.000 | 0.000 | 0.9842 | 0.7278 | 4.92 | 23.93 | 1970 | 8505 | 17542 | 4.0 |
| `SINGLE:paddleocr_vl_1_6` | 506 | 0.1672 | [0.1497, 0.1859] | 0.8328 | 345 | 0.0964 | 0.000 | 0.000 | 0.000 | 0.9842 | 0.7278 | 4.92 | 23.93 | 1970 | 8505 | 17542 | 4.0 |
| `CORE_ROUTER@balanced,ro=0` | 506 | 0.1672 | [0.1497, 0.1859] | 0.8328 | 345 | 0.0964 | 0.000 | 0.000 | 0.000 | 0.9842 | 0.7278 | 4.92 | 23.93 | 1970 | 8505 | 17542 | 4.0 |
| `SINGLE:olmocr2` | 506 | 0.1704 | [0.1520, 0.1896] | 0.8296 | 334 | 0.0997 | 0.000 | 0.000 | 0.000 | 0.9842 | 0.7421 | 7.64 | 37.19 | n/a | n/a | n/a | 13.0 |
| `SINGLE:hpd_parsing` | 506 | 0.1735 | [0.1537, 0.1948] | 0.8265 | 297 | 0.1027 | 0.000 | 0.000 | 0.000 | 0.9842 | 0.6911 | 20.78 | 21.70 | 1571 | 22664 | 44861 | 3.0 |
| `CORE_ROUTER@speed,ro=0` | 506 | 0.1735 | [0.1537, 0.1948] | 0.8265 | 297 | 0.1027 | 0.000 | 0.000 | 0.000 | 0.9842 | 0.6911 | 20.78 | 21.70 | 1571 | 22664 | 44861 | 3.0 |
| `SINGLE:deepseek_ocr2` | 506 | 0.1775 | [0.1588, 0.1979] | 0.8225 | 351 | 0.1068 | 0.000 | 0.000 | 0.000 | 0.9842 | 0.7209 | 11.35 | 55.20 | n/a | n/a | n/a | 27.0 |
| `SINGLE:mineru_pipeline` | 506 | 0.2145 | [0.1923, 0.2382] | 0.7855 | 380 | 0.1437 | 0.000 | 0.000 | 0.000 | 0.9842 | 0.7308 | 4.95 | 24.09 | n/a | n/a | n/a | 4.0 |
| `CORE_ROUTER@speed,ro=1` | 506 | 0.8040 | [0.7706, 0.8350] | 0.1960 | 476 | 0.7332 | 0.749 | 0.000 | 0.000 | 0.2431 | 0.1643 | 5.22 | 5.45 | 1428 | 23694 | 36010 | 0.8 |
| `CORE_ROUTER@balanced,ro=1` | 506 | 0.8076 | [0.7744, 0.8386] | 0.1924 | 484 | 0.7369 | 0.749 | 0.000 | 0.000 | 0.2431 | 0.1716 | 1.23 | 6.01 | 1751 | 4997 | 17065 | 1.0 |
| `CORE_ROUTER@balanced,sentinels` | 506 | 0.8076 | [0.7744, 0.8386] | 0.1924 | 484 | 0.7369 | 0.749 | 0.000 | 0.000 | 0.2431 | 0.1716 | 1.23 | 6.01 | 1751 | 4997 | 17065 | 1.0 |
| `CORE_ROUTER@speed,sentinels` | 506 | 0.8076 | [0.7744, 0.8386] | 0.1924 | 484 | 0.7369 | 0.749 | 0.000 | 0.000 | 0.2431 | 0.1716 | 1.23 | 6.01 | 1751 | 4997 | 17065 | 1.0 |

Best fixed single: `SINGLE:opus5_subscription`. Oracle headroom 0.0178 [0.0122, 0.0251] over 506 document-family clusters.

### Section 17 Oracle capture ratio `(best_fixed - arm) / (best_fixed - oracle)`

| arm | capture | 95% CI |
| --- | ---: | --- |
| `ORACLE_DIAGNOSTIC` | 1.000 | [1.000, 1.000] |
| `SINGLE:opus5_subscription` | 0.000 | [0.000, 0.000] |
| `ALWAYS_STRONG@opus5_subscription` | 0.000 | [0.000, 0.000] |
| `ALWAYS_ALL_RECONCILED` | -0.443 | [-1.181, 0.084] |
| `ABLATION:no_reconciler@opus5_subscription` | -0.929 | [-1.748, -0.324] |
| `DISAGREEMENT_ONLY@opus5_subscription` | -1.076 | [-1.935, -0.417] |
| `ABLATION:no_cost_objective@opus5_subscription` | -1.681 | [-2.942, -0.812] |
| `REPLAY_COMPOSITE_V1@opus5_subscription` | -1.682 | [-2.944, -0.813] |
| `ABLATION:no_prediction@opus5_subscription` | -1.682 | [-2.944, -0.813] |
| `SINGLE:ovisocr2` | -1.810 | [-3.286, -0.787] |
| `ABLATION:no_critical_loss_detector@opus5_subscription` | -1.817 | [-3.105, -0.897] |
| `SINGLE:infinity_parser2_flash` | -1.900 | [-3.318, -0.860] |
| `SINGLE:unlimited_ocr` | -2.394 | [-4.198, -1.189] |
| `ALWAYS_STRONG@unlimited_ocr` | -2.394 | [-4.198, -1.189] |
| `ABLATION:no_cost_objective@unlimited_ocr` | -2.492 | [-4.175, -1.315] |
| `REPLAY_COMPOSITE_V1@unlimited_ocr` | -2.493 | [-4.179, -1.317] |
| `ABLATION:no_prediction@unlimited_ocr` | -2.493 | [-4.179, -1.317] |
| `ABLATION:no_critical_loss_detector@unlimited_ocr` | -2.605 | [-4.306, -1.391] |
| `ABLATION:no_reconciler@unlimited_ocr` | -2.995 | [-4.882, -1.663] |
| `SINGLE:glm_ocr` | -2.995 | [-5.001, -1.599] |
| `DISAGREEMENT_ONLY@unlimited_ocr` | -3.050 | [-4.952, -1.684] |
| `SINGLE:monkeyocrv2_b` | -3.382 | [-5.627, -1.840] |
| `SINGLE:mineru_vlm` | -3.810 | [-5.969, -2.221] |
| `CRITICAL_TOKEN_ONLY@opus5_subscription` | -3.892 | [-6.155, -2.280] |
| `ABLATION:no_disagreement@opus5_subscription` | -3.937 | [-6.217, -2.297] |
| `ABLATION:no_disagreement@unlimited_ocr` | -4.165 | [-6.554, -2.474] |
| `CRITICAL_TOKEN_ONLY@unlimited_ocr` | -4.273 | [-6.687, -2.556] |
| `PREDICTION_ONLY@opus5_subscription` | -4.502 | [-6.950, -2.695] |
| `PREDICTION_ONLY@unlimited_ocr` | -4.582 | [-7.094, -2.747] |
| `PRIMARY_ONLY` | -4.630 | [-7.146, -2.772] |
| `SINGLE:paddleocr_vl_1_6` | -4.630 | [-7.146, -2.772] |
| `CORE_ROUTER@balanced,ro=0` | -4.630 | [-7.146, -2.772] |
| `SINGLE:olmocr2` | -4.804 | [-7.304, -2.911] |
| `SINGLE:hpd_parsing` | -5.001 | [-7.870, -2.961] |
| `CORE_ROUTER@speed,ro=0` | -5.001 | [-7.870, -2.961] |
| `SINGLE:deepseek_ocr2` | -5.233 | [-8.031, -3.183] |
| `SINGLE:mineru_pipeline` | -7.401 | [-11.133, -4.590] |
| `CORE_ROUTER@speed,ro=1` | -41.649 | [-59.720, -28.220] |
| `CORE_ROUTER@balanced,ro=1` | -41.861 | [-59.817, -28.434] |
| `CORE_ROUTER@balanced,sentinels` | -41.861 | [-59.817, -28.434] |
| `CORE_ROUTER@speed,sentinels` | -41.861 | [-59.817, -28.434] |

### Disagreement conditionals (section 92), worst pairs

| a | b | n | agree rate | P(a wrong \| agree) | P(a wrong \| disagree) | P(both wrong AND agree) |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `deepseek_ocr2` | `mineru_vlm` | 506 | 0.757 | 0.616 | 0.935 | 0.407 |
| `deepseek_ocr2` | `olmocr2` | 506 | 0.743 | 0.601 | 0.962 | 0.383 |
| `deepseek_ocr2` | `mineru_pipeline` | 506 | 0.690 | 0.590 | 0.924 | 0.379 |
| `deepseek_ocr2` | `paddleocr_vl_1_6` | 506 | 0.694 | 0.595 | 0.916 | 0.360 |
| `mineru_vlm` | `olmocr2` | 506 | 0.723 | 0.563 | 0.871 | 0.358 |
| `mineru_pipeline` | `mineru_vlm` | 506 | 0.674 | 0.648 | 0.964 | 0.352 |
| `mineru_vlm` | `paddleocr_vl_1_6` | 506 | 0.678 | 0.551 | 0.853 | 0.352 |
| `mineru_pipeline` | `olmocr2` | 506 | 0.662 | 0.639 | 0.971 | 0.332 |
| `olmocr2` | `paddleocr_vl_1_6` | 506 | 0.664 | 0.539 | 0.900 | 0.316 |
| `mineru_pipeline` | `paddleocr_vl_1_6` | 506 | 0.623 | 0.622 | 0.963 | 0.314 |
| `deepseek_ocr2` | `monkeyocrv2_b` | 498 | 0.719 | 0.581 | 0.971 | 0.255 |
| `deepseek_ocr2` | `unlimited_ocr` | 500 | 0.752 | 0.593 | 0.984 | 0.254 |

### Catastrophic failure appendix (top units the Oracle also fails)

| unit | page class | oracle loss | best model | primary loss | blind risk | disagreed? | L2 flagged? | critical events |
| --- | --- | ---: | --- | ---: | ---: | :-: | :-: | ---: |
| `text/text_multicolumns__2col` | text_content,multicolumns,easy | 0.9689 | `opus5_subscription` | 1.0000 | 0.000 | yes | no | 0 |
| `text/text_multilang__khmer` | text_content,multilang,easy | 0.8674 | `opus5_subscription` | 0.9896 | 0.000 | yes | no | 21 |
| `text/text_multilang__unknonw` | text_content,multilang,easy | 0.8448 | `monkeyocrv2_b` | 0.8881 | 0.000 | yes | no | 16 |
| `text/text_multilang__malayalam` | text_content,multilang,easy | 0.8258 | `opus5_subscription` | 0.9325 | 0.000 | yes | no | 37 |
| `text/text_handwritting__jp` | text_content,handwritting,hard | 0.7791 | `opus5_subscription` | 0.9703 | 0.686 | yes | no | 60 |
| `text/text_multilang__tamil` | text_content,multilang,easy | 0.7607 | `opus5_subscription` | 0.9755 | 0.348 | yes | no | 28 |
| `text/text_multilang__gujarati` | text_content,multilang,easy,hard | 0.7537 | `opus5_subscription` | 0.9922 | 0.000 | yes | no | 39 |
| `text/text_ocr__wnd` | text_content,ocr,hard | 0.7414 | `opus5_subscription` | 0.8372 | 0.000 | yes | yes | 28 |
| `text/text_multilang__tegulu` | text_content,multilang,easy | 0.7296 | `opus5_subscription` | 0.8174 | 0.000 | yes | no | 14 |
| `text/text_multilang__thailayout` | text_content,multilang,easy | 0.6819 | `opus5_subscription` | 0.9057 | 0.000 | yes | no | 151 |

## Surface `parsebench:text_formatting` — 476 units, 12 models

Ground truth for SCLR: PARTIAL — asserted heading/format spans only

| arm | n | mean loss | 95% CI | IRR proxy | hard fail | regret | unresolved | escalation | strong | SCLR/unit | SCLR/opp | $/1k | GPU s/unit | p50 ms | p95 ms | p99 ms | ledger s |
| --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `ORACLE_DIAGNOSTIC` | 476 | 0.2163 | [0.1953, 0.2397] | 0.7837 | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| `SINGLE:opus5_subscription` | 476 | 0.2579 | [0.2333, 0.2845] | 0.7421 | 303 | 0.0416 | 0.006 | 0.000 | 1.000 | 0.0777 | 0.0614 | n/a | n/a | 17874 | 54972 | 227310 | n/a |
| `ALWAYS_STRONG@opus5_subscription` | 476 | 0.2579 | [0.2333, 0.2845] | 0.7421 | 303 | 0.0416 | 0.006 | 0.000 | 1.000 | 0.0777 | 0.0614 | n/a | n/a | 17874 | 54972 | 227310 | n/a |
| `ABLATION:no_reconciler@opus5_subscription` | 476 | 0.4906 | [0.4582, 0.5218] | 0.5094 | 387 | 0.2742 | 0.000 | 0.387 | 0.387 | 0.1134 | 0.0785 | n/a | n/a | 5612 | 78300 | 252247 | n/a |
| `DISAGREEMENT_ONLY@opus5_subscription` | 476 | 0.5246 | [0.4923, 0.5554] | 0.4754 | 400 | 0.3083 | 0.000 | 0.315 | 0.315 | 0.1113 | 0.0798 | n/a | n/a | 4898 | 76788 | 252247 | n/a |
| `ABLATION:no_critical_loss_detector@opus5_subscription` | 476 | 0.6074 | [0.5767, 0.6397] | 0.3926 | 419 | 0.3911 | 0.000 | 0.315 | 0.315 | 0.1197 | 0.0890 | n/a | n/a | 4898 | 76788 | 252247 | n/a |
| `REPLAY_COMPOSITE_V1@opus5_subscription` | 476 | 0.6084 | [0.5790, 0.6400] | 0.3916 | 418 | 0.3921 | 0.000 | 0.387 | 0.387 | 0.1134 | 0.0851 | n/a | n/a | 5612 | 78300 | 252247 | n/a |
| `ABLATION:no_cost_objective@opus5_subscription` | 476 | 0.6084 | [0.5790, 0.6400] | 0.3916 | 418 | 0.3921 | 0.000 | 0.387 | 0.387 | 0.1134 | 0.0851 | n/a | n/a | 5612 | 78300 | 252247 | n/a |
| `ABLATION:no_prediction@opus5_subscription` | 476 | 0.6084 | [0.5790, 0.6400] | 0.3916 | 418 | 0.3921 | 0.000 | 0.387 | 0.387 | 0.1134 | 0.0851 | n/a | n/a | 5612 | 78300 | 252247 | n/a |
| `CRITICAL_TOKEN_ONLY@opus5_subscription` | 476 | 0.6147 | [0.5840, 0.6465] | 0.3853 | 421 | 0.3984 | 0.000 | 0.124 | 0.124 | 0.1639 | 0.1583 | n/a | n/a | 4281 | 46694 | 78300 | n/a |
| `SINGLE:mineru_vlm` | 476 | 0.6215 | [0.5924, 0.6504] | 0.3785 | 434 | 0.4052 | 0.000 | 0.000 | 0.000 | 0.1303 | 0.0929 | 1.00 | 7.33 | n/a | n/a | n/a | 5.0 |
| `SINGLE:monkeyocrv2_b` | 476 | 0.6421 | [0.6136, 0.6721] | 0.3579 | 439 | 0.4257 | 0.015 | 0.000 | 0.000 | 0.1429 | 0.1416 | 5.60 | 27.25 | n/a | n/a | n/a | 6.0 |
| `SINGLE:hpd_parsing` | 476 | 0.6541 | [0.6248, 0.6843] | 0.3459 | 435 | 0.4377 | 0.000 | 0.000 | 0.000 | 0.1261 | 0.0925 | 20.78 | 21.70 | 1572 | 23514 | 45270 | 3.0 |
| `CORE_ROUTER@speed,ro=0` | 476 | 0.6541 | [0.6248, 0.6843] | 0.3459 | 435 | 0.4377 | 0.000 | 0.000 | 0.000 | 0.1261 | 0.0925 | 20.78 | 21.70 | 1572 | 23514 | 45270 | 3.0 |
| `ABLATION:no_disagreement@opus5_subscription` | 476 | 0.6600 | [0.6319, 0.6910] | 0.3400 | 435 | 0.4437 | 0.000 | 0.132 | 0.132 | 0.1492 | 0.1548 | n/a | n/a | 4285 | 46694 | 82276 | n/a |
| `PREDICTION_ONLY@opus5_subscription` | 476 | 0.6626 | [0.6346, 0.6930] | 0.3374 | 437 | 0.4463 | 0.000 | 0.008 | 0.008 | 0.1576 | 0.1644 | n/a | n/a | 1977 | 8505 | 18977 | n/a |
| `PRIMARY_ONLY` | 476 | 0.6662 | [0.6392, 0.6957] | 0.3338 | 439 | 0.4499 | 0.000 | 0.000 | 0.000 | 0.1597 | 0.1648 | 4.92 | 23.93 | 1974 | 6657 | 18520 | 4.0 |
| `SINGLE:paddleocr_vl_1_6` | 476 | 0.6662 | [0.6392, 0.6957] | 0.3338 | 439 | 0.4499 | 0.000 | 0.000 | 0.000 | 0.1597 | 0.1648 | 4.92 | 23.93 | 1974 | 6657 | 18520 | 4.0 |
| `CORE_ROUTER@balanced,ro=0` | 476 | 0.6662 | [0.6392, 0.6957] | 0.3338 | 439 | 0.4499 | 0.000 | 0.000 | 0.000 | 0.1597 | 0.1648 | 4.92 | 23.93 | 1974 | 6657 | 18520 | 4.0 |
| `SINGLE:glm_ocr` | 476 | 0.6675 | [0.6390, 0.6957] | 0.3325 | 440 | 0.4512 | 0.000 | 0.000 | 0.000 | 0.1366 | 0.1149 | 8.57 | 33.76 | n/a | n/a | n/a | 5.0 |
| `PREDICTION_ONLY@unlimited_ocr` | 476 | 0.6675 | [0.6406, 0.6974] | 0.3325 | 439 | 0.4512 | 0.000 | 0.008 | 0.008 | 0.1576 | 0.1644 | 5.16 | 25.13 | 1977 | 8505 | 18977 | 4.2 |
| `ALWAYS_ALL_RECONCILED` | 476 | 0.6697 | [0.6382, 0.7012] | 0.3303 | 427 | 0.4534 | 0.000 | 1.000 | 1.000 | 0.0819 | 0.0640 | n/a | n/a | n/a | n/a | n/a | n/a |
| `SINGLE:deepseek_ocr2` | 476 | 0.6781 | [0.6515, 0.7077] | 0.3219 | 441 | 0.4618 | 0.000 | 0.000 | 0.000 | 0.1576 | 0.1219 | 11.35 | 55.20 | n/a | n/a | n/a | 27.0 |
| `ABLATION:no_disagreement@unlimited_ocr` | 476 | 0.6814 | [0.6541, 0.7115] | 0.3186 | 440 | 0.4650 | 0.000 | 0.132 | 0.132 | 0.1492 | 0.1574 | 13.62 | 66.39 | 4285 | 57290 | 106175 | 11.8 |
| `SINGLE:mineru_pipeline` | 476 | 0.6978 | [0.6716, 0.7256] | 0.3022 | 446 | 0.4815 | 0.000 | 0.000 | 0.000 | 0.2437 | 0.2179 | 4.95 | 24.09 | n/a | n/a | n/a | 4.0 |
| `ABLATION:no_critical_loss_detector@unlimited_ocr` | 476 | 0.7003 | [0.6727, 0.7296] | 0.2997 | 442 | 0.4839 | 0.000 | 0.315 | 0.315 | 0.1282 | 0.0947 | 18.95 | 92.52 | 4840 | 67663 | 165150 | 17.1 |
| `CRITICAL_TOKEN_ONLY@unlimited_ocr` | 476 | 0.7028 | [0.6759, 0.7308] | 0.2972 | 442 | 0.4864 | 0.000 | 0.124 | 0.124 | 0.1534 | 0.1600 | 13.37 | 65.19 | 4281 | 56658 | 106175 | 11.6 |
| `REPLAY_COMPOSITE_V1@unlimited_ocr` | 476 | 0.7066 | [0.6787, 0.7359] | 0.2934 | 443 | 0.4902 | 0.000 | 0.387 | 0.387 | 0.1218 | 0.0912 | 21.03 | 102.73 | 5263 | 81406 | 213918 | 19.2 |
| `ABLATION:no_cost_objective@unlimited_ocr` | 476 | 0.7066 | [0.6787, 0.7359] | 0.2934 | 443 | 0.4902 | 0.000 | 0.387 | 0.387 | 0.1218 | 0.0912 | 21.03 | 102.73 | 5263 | 81406 | 213918 | 19.2 |
| `ABLATION:no_prediction@unlimited_ocr` | 476 | 0.7066 | [0.6787, 0.7359] | 0.2934 | 443 | 0.4902 | 0.000 | 0.387 | 0.387 | 0.1218 | 0.0912 | 21.03 | 102.73 | 5263 | 81406 | 213918 | 19.2 |
| `SINGLE:ovisocr2` | 476 | 0.7151 | [0.6865, 0.7435] | 0.2849 | 443 | 0.4988 | 0.000 | 0.000 | 0.000 | 0.0882 | 0.0864 | 4.84 | 23.54 | 1901 | 40849 | 41491 | 4.0 |
| `SINGLE:infinity_parser2_flash` | 476 | 0.7299 | [0.6991, 0.7615] | 0.2701 | 444 | 0.5136 | 0.000 | 0.000 | 0.000 | 0.1471 | 0.1613 | 0.80 | 3.87 | n/a | n/a | n/a | n/a |
| `DISAGREEMENT_ONLY@unlimited_ocr` | 476 | 0.7409 | [0.7139, 0.7694] | 0.2591 | 450 | 0.5245 | 0.000 | 0.315 | 0.315 | 0.1345 | 0.0982 | 18.95 | 92.52 | 4840 | 67663 | 165150 | 17.1 |
| `ABLATION:no_reconciler@unlimited_ocr` | 476 | 0.7627 | [0.7368, 0.7901] | 0.2373 | 452 | 0.5464 | 0.000 | 0.387 | 0.387 | 0.1303 | 0.0943 | 21.03 | 102.73 | 5263 | 81406 | 213918 | 19.2 |
| `CORE_ROUTER@speed,ro=1` | 476 | 0.9320 | [0.9137, 0.9492] | 0.0680 | 465 | 0.7157 | 0.763 | 0.000 | 0.000 | 0.0399 | 0.0342 | 4.93 | 5.15 | 1595 | 23749 | 36010 | 0.7 |
| `CORE_ROUTER@balanced,ro=1` | 476 | 0.9415 | [0.9251, 0.9564] | 0.0585 | 469 | 0.7252 | 0.763 | 0.000 | 0.000 | 0.0483 | 0.0662 | 1.17 | 5.68 | 1774 | 5575 | 17065 | 0.9 |
| `CORE_ROUTER@balanced,sentinels` | 476 | 0.9415 | [0.9251, 0.9564] | 0.0585 | 469 | 0.7252 | 0.763 | 0.000 | 0.000 | 0.0483 | 0.0662 | 1.17 | 5.68 | 1774 | 5575 | 17065 | 0.9 |
| `CORE_ROUTER@speed,sentinels` | 476 | 0.9415 | [0.9251, 0.9564] | 0.0585 | 469 | 0.7252 | 0.763 | 0.000 | 0.000 | 0.0483 | 0.0662 | 1.17 | 5.68 | 1774 | 5575 | 17065 | 0.9 |
| `SINGLE:olmocr2` | 476 | 0.9799 | [0.9699, 0.9885] | 0.0201 | 474 | 0.7636 | 0.000 | 0.000 | 0.000 | 0.1639 | 0.1754 | 7.64 | 37.19 | n/a | n/a | n/a | 13.0 |
| `SINGLE:unlimited_ocr` | 476 | 0.9954 | [0.9899, 0.9992] | 0.0046 | 475 | 0.7791 | 0.013 | 0.000 | 1.000 | 0.1008 | 0.0785 | 29.17 | 142.97 | 24716 | 72152 | 294373 | 29.0 |
| `ALWAYS_STRONG@unlimited_ocr` | 476 | 0.9954 | [0.9899, 0.9992] | 0.0046 | 475 | 0.7791 | 0.013 | 0.000 | 1.000 | 0.1008 | 0.0785 | 29.17 | 142.97 | 24716 | 72152 | 294373 | 29.0 |

Best fixed single: `SINGLE:opus5_subscription`. Oracle headroom 0.0416 [0.0289, 0.0564] over 476 document-family clusters.

### Section 17 Oracle capture ratio `(best_fixed - arm) / (best_fixed - oracle)`

| arm | capture | 95% CI |
| --- | ---: | --- |
| `ORACLE_DIAGNOSTIC` | 1.000 | [1.000, 1.000] |
| `SINGLE:opus5_subscription` | 0.000 | [0.000, 0.000] |
| `ALWAYS_STRONG@opus5_subscription` | 0.000 | [0.000, 0.000] |
| `ABLATION:no_reconciler@opus5_subscription` | -5.776 | [-8.603, -3.845] |
| `DISAGREEMENT_ONLY@opus5_subscription` | -6.615 | [-9.797, -4.464] |
| `ABLATION:no_critical_loss_detector@opus5_subscription` | -8.675 | [-12.634, -5.875] |
| `REPLAY_COMPOSITE_V1@opus5_subscription` | -8.703 | [-12.652, -5.900] |
| `ABLATION:no_cost_objective@opus5_subscription` | -8.703 | [-12.652, -5.900] |
| `ABLATION:no_prediction@opus5_subscription` | -8.703 | [-12.652, -5.900] |
| `CRITICAL_TOKEN_ONLY@opus5_subscription` | -8.859 | [-13.005, -5.985] |
| `SINGLE:mineru_vlm` | -9.029 | [-13.215, -6.002] |
| `SINGLE:monkeyocrv2_b` | -9.543 | [-13.997, -6.423] |
| `SINGLE:hpd_parsing` | -9.836 | [-14.376, -6.629] |
| `CORE_ROUTER@speed,ro=0` | -9.836 | [-14.376, -6.629] |
| `ABLATION:no_disagreement@opus5_subscription` | -9.981 | [-14.534, -6.758] |
| `PREDICTION_ONLY@opus5_subscription` | -10.042 | [-14.734, -6.793] |
| `PRIMARY_ONLY` | -10.130 | [-14.790, -6.887] |
| `SINGLE:paddleocr_vl_1_6` | -10.130 | [-14.790, -6.887] |
| `CORE_ROUTER@balanced,ro=0` | -10.130 | [-14.790, -6.887] |
| `PREDICTION_ONLY@unlimited_ocr` | -10.163 | [-14.848, -6.911] |
| `SINGLE:glm_ocr` | -10.164 | [-14.759, -6.908] |
| `ALWAYS_ALL_RECONCILED` | -10.204 | [-14.710, -6.987] |
| `SINGLE:deepseek_ocr2` | -10.432 | [-15.235, -7.054] |
| `ABLATION:no_disagreement@unlimited_ocr` | -10.511 | [-15.415, -7.124] |
| `SINGLE:mineru_pipeline` | -10.914 | [-15.859, -7.432] |
| `ABLATION:no_critical_loss_detector@unlimited_ocr` | -10.968 | [-15.870, -7.486] |
| `CRITICAL_TOKEN_ONLY@unlimited_ocr` | -11.039 | [-16.070, -7.435] |
| `REPLAY_COMPOSITE_V1@unlimited_ocr` | -11.127 | [-16.137, -7.597] |
| `ABLATION:no_cost_objective@unlimited_ocr` | -11.127 | [-16.137, -7.597] |
| `ABLATION:no_prediction@unlimited_ocr` | -11.127 | [-16.137, -7.597] |
| `SINGLE:ovisocr2` | -11.337 | [-16.373, -7.719] |
| `SINGLE:infinity_parser2_flash` | -11.709 | [-16.994, -8.107] |
| `DISAGREEMENT_ONLY@unlimited_ocr` | -11.971 | [-17.252, -8.199] |
| `ABLATION:no_reconciler@unlimited_ocr` | -12.515 | [-18.018, -8.584] |
| `CORE_ROUTER@speed,ro=1` | -16.677 | [-23.819, -11.668] |
| `CORE_ROUTER@balanced,ro=1` | -16.912 | [-24.143, -11.835] |
| `CORE_ROUTER@balanced,sentinels` | -16.912 | [-24.143, -11.835] |
| `CORE_ROUTER@speed,sentinels` | -16.912 | [-24.143, -11.835] |
| `SINGLE:olmocr2` | -17.862 | [-25.589, -12.534] |
| `SINGLE:unlimited_ocr` | -18.245 | [-25.940, -12.827] |
| `ALWAYS_STRONG@unlimited_ocr` | -18.245 | [-25.940, -12.827] |

### Disagreement conditionals (section 92), worst pairs

| a | b | n | agree rate | P(a wrong \| agree) | P(a wrong \| disagree) | P(both wrong AND agree) |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `ovisocr2` | `unlimited_ocr` | 470 | 0.823 | 0.930 | 0.928 | 0.766 |
| `infinity_parser2_flash` | `unlimited_ocr` | 470 | 0.802 | 0.923 | 0.968 | 0.740 |
| `olmocr2` | `unlimited_ocr` | 470 | 0.732 | 0.997 | 0.992 | 0.730 |
| `infinity_parser2_flash` | `ovisocr2` | 476 | 0.809 | 0.922 | 0.978 | 0.718 |
| `deepseek_ocr2` | `unlimited_ocr` | 470 | 0.764 | 0.919 | 0.946 | 0.702 |
| `deepseek_ocr2` | `olmocr2` | 476 | 0.754 | 0.925 | 0.932 | 0.697 |
| `deepseek_ocr2` | `ovisocr2` | 476 | 0.763 | 0.926 | 0.929 | 0.697 |
| `infinity_parser2_flash` | `olmocr2` | 476 | 0.754 | 0.925 | 0.957 | 0.695 |
| `monkeyocrv2_b` | `unlimited_ocr` | 463 | 0.756 | 0.917 | 0.929 | 0.693 |
| `deepseek_ocr2` | `mineru_vlm` | 476 | 0.765 | 0.920 | 0.946 | 0.693 |
| `glm_ocr` | `ovisocr2` | 476 | 0.767 | 0.921 | 0.937 | 0.693 |
| `monkeyocrv2_b` | `ovisocr2` | 469 | 0.768 | 0.925 | 0.908 | 0.689 |

### Catastrophic failure appendix (top units the Oracle also fails)

| unit | page class | oracle loss | best model | primary loss | blind risk | disagreed? | L2 flagged? | critical events |
| --- | --- | ---: | --- | ---: | ---: | :-: | :-: | ---: |
| `text/text_dense__underline` | text_formatting,dense,hard | 1.0000 | `deepseek_ocr2` | 1.0000 | 0.000 | yes | yes | 1 |
| `text/text_multicolumns__2col` | text_formatting,multicolumns,easy | 1.0000 | `deepseek_ocr2` | 1.0000 | 0.000 | yes | no | 0 |
| `text/text_ocr__code` | text_formatting,ocr,hard | 1.0000 | `deepseek_ocr2` | 1.0000 | 0.000 | yes | yes | 10 |
| `text/text_ocr__mix` | text_formatting,ocr,hard | 1.0000 | `deepseek_ocr2` | 1.0000 | 0.000 | yes | yes | 0 |
| `text/text_ocr__ord-4000` | text_formatting,ocr,hard | 1.0000 | `deepseek_ocr2` | 1.0000 | 0.000 | no | no | 0 |
| `text/text_ocr__p4013` | text_formatting,ocr,hard | 1.0000 | `deepseek_ocr2` | 1.0000 | 0.000 | no | no | 0 |
| `text/text_simple__att10k` | text_formatting,simple,easy | 1.0000 | `deepseek_ocr2` | 1.0000 | 0.000 | yes | no | 65 |
| `text/text_simple__linenum` | text_formatting,simple,easy | 1.0000 | `deepseek_ocr2` | 1.0000 | 0.000 | yes | no | 0 |
| `text/text_simple__smithville` | text_formatting,simple,easy | 1.0000 | `deepseek_ocr2` | 1.0000 | 0.000 | no | no | 0 |
| `text/text_simple__endnote` | text_formatting,simple,hard | 0.9000 | `deepseek_ocr2` | 0.9000 | 0.000 | no | no | 0 |

## Ablations that are NOT measurable from stored outputs

| ablation | reason |
| --- | --- |
| `full_replay_vs_incremental` | needs a multi-version corpus |
| `no_authority` | no authority source (SEC/XBRL/OpenDART) exists in the repository or the corpus |
| `no_cold_start` | cold start is a per-pod property in the ledger, not a per-unit one |
| `no_independent_verifier` | no verifier gate exists to switch off (WP-R9 is NOT_STARTED) |
| `no_preflight` | the corpus has no arrival-time preflight lane; every signal here is post-render |
| `no_queue_state` | queue depth at decision time is not recorded per unit |
| `no_region_recovery` | the Arena stores whole-page outputs only; no region crops were ever run |
| `no_speculation` | speculative execution produces no separate stored artifact to withhold |
| `no_template_memory` | no per-cluster outcome memory exists to ablate |
| `no_temporal_or_identity` | single-version corpus; no second version of any document exists |

## Cost and latency caveats

- Cost is raw GPU provider cost from the campaign ledger, under an exploratory scheduling pattern with a 0.66 idle overhead ratio. It is never a per-page price and never sits beside a retail price.
- opus5_subscription has no pod ledger: its cost is UNMEASURED, not zero, so every arm that invokes it reports an INCOMPLETE cost.
- Latency is measured inference_ms from the per-page receipts. Queue time and cold start are excluded and are NOT modelled.
- An arm's latency is the SUM over the routes it invoked, i.e. sequential execution. Parallel speculation would be lower; nothing here measures it.

## Arena report anomalies that travel with every number above

- glm_ocr's OmniDoc board row (text Edit 0.0444) disagrees with its own per-page rows (0.0846); ANOMALY_NOTES.md explains it as a SUCCESS-only rescore over a 1,599-page filtered GT. This replay uses the full-corpus per-page rows, the conservative choice, exactly as Phase A did.
- reports/full_compare_20260905/STATUS.md contains unrendered PowerShell template literals instead of substituted values and must not be quoted.
