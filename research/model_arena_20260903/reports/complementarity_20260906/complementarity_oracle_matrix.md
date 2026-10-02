# Complementarity Oracle Matrix

Continuous oracle (primary router ceiling). Page score = `1 - edit` (edit clipped to [0,1]).
`oracle_edit = mean(min(edit_A, edit_B))` on shared pages; `oracle_gain_A = oracle_score - alone_score_A`.

## Page counts

| element | paddle | ovis | flash | deepseek | glm | opus | all_intersect |
| --- | --- | --- | --- | --- | --- | --- | --- |
| text | 1557 | 1557 | 1557 | 1557 | 1557 | 1557 | 1557 |
| formula | 313 | 313 | 313 | 313 | 313 | 313 | 313 |
| table | 458 | 458 | 458 | 458 | 458 | 458 | 458 |
| reading_order | 1638 | 1638 | 1638 | 1638 | 1638 | 1638 | 1638 |

## Element: `text`

### Alone scores (all-model page intersection)

| model | n_pages | alone_mean_edit | alone_score (all-intersect) |
| --- | --- | --- | --- |
| paddle | 1557 | 0.0426 | 0.9574 |
| ovis | 1557 | 0.0290 | 0.9710 |
| flash | 1557 | 0.0449 | 0.9551 |
| deepseek | 1557 | 0.0584 | 0.9416 |
| glm | 1557 | 0.0846 | 0.9154 |
| opus | 1557 | 0.0896 | 0.9104 |

### Pairwise oracle scores (diag = alone)

| oracle_score | paddle | ovis | flash | deepseek | glm | opus |
| --- | --- | --- | --- | --- | --- | --- |
| paddle | 0.9574 | 0.9768 | 0.9746 | 0.9720 | 0.9699 | 0.9744 |
| ovis | 0.9768 | 0.9710 | 0.9773 | 0.9759 | 0.9767 | 0.9770 |
| flash | 0.9746 | 0.9773 | 0.9551 | 0.9690 | 0.9671 | 0.9699 |
| deepseek | 0.9720 | 0.9759 | 0.9690 | 0.9416 | 0.9679 | 0.9676 |
| glm | 0.9699 | 0.9767 | 0.9671 | 0.9679 | 0.9154 | 0.9671 |
| opus | 0.9744 | 0.9770 | 0.9699 | 0.9676 | 0.9671 | 0.9104 |

### Oracle gain (row = baseline model)

| oracle_gain (row=baseline) | paddle | ovis | flash | deepseek | glm | opus |
| --- | --- | --- | --- | --- | --- | --- |
| paddle | 0.0000 | 0.0194 | 0.0172 | 0.0145 | 0.0125 | 0.0170 |
| ovis | 0.0058 | 0.0000 | 0.0063 | 0.0049 | 0.0057 | 0.0060 |
| flash | 0.0195 | 0.0222 | 0.0000 | 0.0139 | 0.0120 | 0.0147 |
| deepseek | 0.0304 | 0.0343 | 0.0274 | 0.0000 | 0.0263 | 0.0260 |
| glm | 0.0545 | 0.0613 | 0.0517 | 0.0524 | 0.0000 | 0.0517 |
| opus | 0.0640 | 0.0666 | 0.0595 | 0.0572 | 0.0567 | 0.0000 |

### Paddle baseline + peer

| peer | n_pages | paddle_alone | peer_alone | oracle_score | oracle_gain_vs_paddle |
| --- | --- | --- | --- | --- | --- |
| ovis | 1557 | 0.9574 | 0.9710 | 0.9768 | 0.0194 |
| flash | 1557 | 0.9574 | 0.9551 | 0.9746 | 0.0172 |
| deepseek | 1557 | 0.9574 | 0.9416 | 0.9720 | 0.0145 |
| glm | 1557 | 0.9574 | 0.9154 | 0.9699 | 0.0125 |
| opus | 1557 | 0.9574 | 0.9104 | 0.9744 | 0.0170 |

## Element: `formula`

### Alone scores (all-model page intersection)

| model | n_pages | alone_mean_edit | alone_score (all-intersect) |
| --- | --- | --- | --- |
| paddle | 313 | 0.0868 | 0.9132 |
| ovis | 313 | 0.0871 | 0.9129 |
| flash | 313 | 0.1407 | 0.8593 |
| deepseek | 313 | 0.1259 | 0.8741 |
| glm | 313 | 0.2960 | 0.7040 |
| opus | 313 | 0.1458 | 0.8542 |

### Pairwise oracle scores (diag = alone)

| oracle_score | paddle | ovis | flash | deepseek | glm | opus |
| --- | --- | --- | --- | --- | --- | --- |
| paddle | 0.9132 | 0.9321 | 0.9338 | 0.9269 | 0.9229 | 0.9308 |
| ovis | 0.9321 | 0.9129 | 0.9273 | 0.9232 | 0.9254 | 0.9262 |
| flash | 0.9338 | 0.9273 | 0.8593 | 0.9139 | 0.8918 | 0.8974 |
| deepseek | 0.9269 | 0.9232 | 0.9139 | 0.8741 | 0.8968 | 0.9121 |
| glm | 0.9229 | 0.9254 | 0.8918 | 0.8968 | 0.7040 | 0.8964 |
| opus | 0.9308 | 0.9262 | 0.8974 | 0.9121 | 0.8964 | 0.8542 |

### Oracle gain (row = baseline model)

| oracle_gain (row=baseline) | paddle | ovis | flash | deepseek | glm | opus |
| --- | --- | --- | --- | --- | --- | --- |
| paddle | 0.0000 | 0.0189 | 0.0206 | 0.0137 | 0.0096 | 0.0175 |
| ovis | 0.0192 | 0.0000 | 0.0144 | 0.0103 | 0.0125 | 0.0133 |
| flash | 0.0746 | 0.0680 | 0.0000 | 0.0546 | 0.0326 | 0.0381 |
| deepseek | 0.0529 | 0.0492 | 0.0398 | 0.0000 | 0.0227 | 0.0380 |
| glm | 0.2189 | 0.2214 | 0.1878 | 0.1928 | 0.0000 | 0.1924 |
| opus | 0.0766 | 0.0720 | 0.0432 | 0.0579 | 0.0421 | 0.0000 |

### Paddle baseline + peer

| peer | n_pages | paddle_alone | peer_alone | oracle_score | oracle_gain_vs_paddle |
| --- | --- | --- | --- | --- | --- |
| ovis | 313 | 0.9132 | 0.9129 | 0.9321 | 0.0189 |
| flash | 313 | 0.9132 | 0.8593 | 0.9338 | 0.0206 |
| deepseek | 313 | 0.9132 | 0.8741 | 0.9269 | 0.0137 |
| glm | 313 | 0.9132 | 0.7040 | 0.9229 | 0.0096 |
| opus | 313 | 0.9132 | 0.8542 | 0.9308 | 0.0175 |

## Element: `table`

### Alone scores (all-model page intersection)

| model | n_pages | alone_mean_edit | alone_score (all-intersect) |
| --- | --- | --- | --- |
| paddle | 458 | 0.0513 | 0.9487 |
| ovis | 458 | 0.0514 | 0.9486 |
| flash | 458 | 0.1293 | 0.8707 |
| deepseek | 458 | 0.1178 | 0.8822 |
| glm | 458 | 0.5014 | 0.4986 |
| opus | 458 | 0.5403 | 0.4597 |

### Pairwise oracle scores (diag = alone)

| oracle_score | paddle | ovis | flash | deepseek | glm | opus |
| --- | --- | --- | --- | --- | --- | --- |
| paddle | 0.9487 | 0.9654 | 0.9563 | 0.9547 | 0.9530 | 0.9498 |
| ovis | 0.9654 | 0.9486 | 0.9529 | 0.9536 | 0.9547 | 0.9489 |
| flash | 0.9563 | 0.9529 | 0.8707 | 0.9171 | 0.9009 | 0.8913 |
| deepseek | 0.9547 | 0.9536 | 0.9171 | 0.8822 | 0.9071 | 0.8956 |
| glm | 0.9530 | 0.9547 | 0.9009 | 0.9071 | 0.4986 | 0.6940 |
| opus | 0.9498 | 0.9489 | 0.8913 | 0.8956 | 0.6940 | 0.4597 |

### Oracle gain (row = baseline model)

| oracle_gain (row=baseline) | paddle | ovis | flash | deepseek | glm | opus |
| --- | --- | --- | --- | --- | --- | --- |
| paddle | 0.0000 | 0.0166 | 0.0075 | 0.0060 | 0.0042 | 0.0011 |
| ovis | 0.0167 | 0.0000 | 0.0043 | 0.0050 | 0.0061 | 0.0002 |
| flash | 0.0855 | 0.0822 | 0.0000 | 0.0464 | 0.0301 | 0.0206 |
| deepseek | 0.0725 | 0.0714 | 0.0349 | 0.0000 | 0.0249 | 0.0133 |
| glm | 0.4544 | 0.4561 | 0.4023 | 0.4085 | 0.0000 | 0.1954 |
| opus | 0.4901 | 0.4892 | 0.4316 | 0.4358 | 0.2343 | 0.0000 |

### Paddle baseline + peer

| peer | n_pages | paddle_alone | peer_alone | oracle_score | oracle_gain_vs_paddle |
| --- | --- | --- | --- | --- | --- |
| ovis | 458 | 0.9487 | 0.9486 | 0.9654 | 0.0166 |
| flash | 458 | 0.9487 | 0.8707 | 0.9563 | 0.0075 |
| deepseek | 458 | 0.9487 | 0.8822 | 0.9547 | 0.0060 |
| glm | 458 | 0.9487 | 0.4986 | 0.9530 | 0.0042 |
| opus | 458 | 0.9487 | 0.4597 | 0.9498 | 0.0011 |

## Element: `reading_order`

### Alone scores (all-model page intersection)

| model | n_pages | alone_mean_edit | alone_score (all-intersect) |
| --- | --- | --- | --- |
| paddle | 1638 | 0.1304 | 0.8696 |
| ovis | 1638 | 0.1129 | 0.8871 |
| flash | 1638 | 0.1377 | 0.8623 |
| deepseek | 1638 | 0.1500 | 0.8500 |
| glm | 1638 | 0.2127 | 0.7873 |
| opus | 1638 | 0.1675 | 0.8325 |

### Pairwise oracle scores (diag = alone)

| oracle_score | paddle | ovis | flash | deepseek | glm | opus |
| --- | --- | --- | --- | --- | --- | --- |
| paddle | 0.8696 | 0.8940 | 0.8905 | 0.8860 | 0.8780 | 0.8943 |
| ovis | 0.8940 | 0.8871 | 0.8946 | 0.8929 | 0.8938 | 0.8978 |
| flash | 0.8905 | 0.8946 | 0.8623 | 0.8804 | 0.8790 | 0.8860 |
| deepseek | 0.8860 | 0.8929 | 0.8804 | 0.8500 | 0.8769 | 0.8860 |
| glm | 0.8780 | 0.8938 | 0.8790 | 0.8769 | 0.7873 | 0.8806 |
| opus | 0.8943 | 0.8978 | 0.8860 | 0.8860 | 0.8806 | 0.8325 |

### Oracle gain (row = baseline model)

| oracle_gain (row=baseline) | paddle | ovis | flash | deepseek | glm | opus |
| --- | --- | --- | --- | --- | --- | --- |
| paddle | 0.0000 | 0.0244 | 0.0209 | 0.0164 | 0.0083 | 0.0247 |
| ovis | 0.0068 | 0.0000 | 0.0075 | 0.0057 | 0.0067 | 0.0106 |
| flash | 0.0281 | 0.0323 | 0.0000 | 0.0181 | 0.0167 | 0.0237 |
| deepseek | 0.0359 | 0.0428 | 0.0304 | 0.0000 | 0.0268 | 0.0360 |
| glm | 0.0906 | 0.1065 | 0.0917 | 0.0895 | 0.0000 | 0.0932 |
| opus | 0.0618 | 0.0652 | 0.0535 | 0.0535 | 0.0480 | 0.0000 |

### Paddle baseline + peer

| peer | n_pages | paddle_alone | peer_alone | oracle_score | oracle_gain_vs_paddle |
| --- | --- | --- | --- | --- | --- |
| ovis | 1638 | 0.8696 | 0.8871 | 0.8940 | 0.0244 |
| flash | 1638 | 0.8696 | 0.8623 | 0.8905 | 0.0209 |
| deepseek | 1638 | 0.8696 | 0.8500 | 0.8860 | 0.0164 |
| glm | 1638 | 0.8696 | 0.7873 | 0.8780 | 0.0083 |
| opus | 1638 | 0.8696 | 0.8325 | 0.8943 | 0.0247 |
