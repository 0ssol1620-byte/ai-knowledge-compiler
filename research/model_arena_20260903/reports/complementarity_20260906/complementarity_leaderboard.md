# Complementarity Leaderboard

Peers ranked vs **paddle** baseline. Higher rescue / higher oracle gain = more complementary.

## `text`

### Rank by rescue rate (P(peer OK | paddle wrong), tau=0.05)

| rank | peer | rescue_rate | n_paddle_wrong | n_pages |
| --- | --- | --- | --- | --- |
| 1 | ovis | 44.0% | 316 | 1557 |
| 2 | opus | 35.8% | 316 | 1557 |
| 3 | flash | 34.2% | 316 | 1557 |
| 4 | deepseek | 30.1% | 316 | 1557 |
| 5 | glm | 22.8% | 316 | 1557 |

### Rank by oracle gain vs paddle

| rank | peer | oracle_gain | oracle_score | paddle_alone | peer_alone | n_pages |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | ovis | 0.0194 | 0.9768 | 0.9574 | 0.9710 | 1557 |
| 2 | flash | 0.0172 | 0.9746 | 0.9574 | 0.9551 | 1557 |
| 3 | opus | 0.0170 | 0.9744 | 0.9574 | 0.9104 | 1557 |
| 4 | deepseek | 0.0145 | 0.9720 | 0.9574 | 0.9416 | 1557 |
| 5 | glm | 0.0125 | 0.9699 | 0.9574 | 0.9154 | 1557 |

## `formula`

### Rank by rescue rate (P(peer OK | paddle wrong), tau=0.05)

| rank | peer | rescue_rate | n_paddle_wrong | n_pages |
| --- | --- | --- | --- | --- |
| 1 | flash | 15.2% | 158 | 313 |
| 2 | opus | 13.3% | 158 | 313 |
| 3 | ovis | 11.4% | 158 | 313 |
| 4 | deepseek | 8.9% | 158 | 313 |
| 5 | glm | 5.1% | 158 | 313 |

### Rank by oracle gain vs paddle

| rank | peer | oracle_gain | oracle_score | paddle_alone | peer_alone | n_pages |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | flash | 0.0206 | 0.9338 | 0.9132 | 0.8593 | 313 |
| 2 | ovis | 0.0189 | 0.9321 | 0.9132 | 0.9129 | 313 |
| 3 | opus | 0.0175 | 0.9308 | 0.9132 | 0.8542 | 313 |
| 4 | deepseek | 0.0137 | 0.9269 | 0.9132 | 0.8741 | 313 |
| 5 | glm | 0.0096 | 0.9229 | 0.9132 | 0.7040 | 313 |

## `table`

### Rank by rescue rate (P(peer OK | paddle wrong), tau=0.05)

| rank | peer | rescue_rate | n_paddle_wrong | n_pages |
| --- | --- | --- | --- | --- |
| 1 | ovis | 22.2% | 135 | 458 |
| 2 | deepseek | 9.6% | 135 | 458 |
| 3 | flash | 9.6% | 135 | 458 |
| 4 | glm | 6.7% | 135 | 458 |
| 5 | opus | n/a | 135 | 458 |

### Rank by oracle gain vs paddle

| rank | peer | oracle_gain | oracle_score | paddle_alone | peer_alone | n_pages |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | ovis | 0.0166 | 0.9654 | 0.9487 | 0.9486 | 458 |
| 2 | flash | 0.0075 | 0.9563 | 0.9487 | 0.8707 | 458 |
| 3 | deepseek | 0.0060 | 0.9547 | 0.9487 | 0.8822 | 458 |
| 4 | glm | 0.0042 | 0.9530 | 0.9487 | 0.4986 | 458 |
| 5 | opus | 0.0011 | 0.9498 | 0.9487 | 0.4597 | 458 |

## `reading_order`

### Rank by rescue rate (P(peer OK | paddle wrong), tau=0.05)

| rank | peer | rescue_rate | n_paddle_wrong | n_pages |
| --- | --- | --- | --- | --- |
| 1 | ovis | 18.9% | 720 | 1638 |
| 2 | opus | 15.8% | 720 | 1638 |
| 3 | flash | 14.7% | 720 | 1638 |
| 4 | deepseek | 11.9% | 720 | 1638 |
| 5 | glm | 4.4% | 720 | 1638 |

### Rank by oracle gain vs paddle

| rank | peer | oracle_gain | oracle_score | paddle_alone | peer_alone | n_pages |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | opus | 0.0247 | 0.8943 | 0.8696 | 0.8325 | 1638 |
| 2 | ovis | 0.0244 | 0.8940 | 0.8696 | 0.8871 | 1638 |
| 3 | flash | 0.0209 | 0.8905 | 0.8696 | 0.8623 | 1638 |
| 4 | deepseek | 0.0164 | 0.8860 | 0.8696 | 0.8500 | 1638 |
| 5 | glm | 0.0083 | 0.8780 | 0.8696 | 0.7873 | 1638 |
