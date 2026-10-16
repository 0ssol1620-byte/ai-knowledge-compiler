# Complementarity vs Ovis (quality leader)

Baseline = **ovis** (alone #1). Question: who complements ovis failures?

## `text`

Ovis alone: **0.9710** (n=1557, wrong@0.05≈203)

### Rank by oracle gain vs ovis

| rank | peer | oracle_gain | oracle_score | rescue_given_ovis_wrong |
| --- | --- | --- | --- | --- |
| 1 | flash | +0.0063 | 0.9773 | 13.8% |
| 2 | opus | +0.0060 | 0.9770 | 16.3% |
| 3 | paddle | +0.0058 | 0.9768 | 12.8% |
| 4 | glm | +0.0057 | 0.9767 | 16.3% |
| 5 | deepseek | +0.0049 | 0.9759 | 11.3% |

### Rank by rescue rate (P(peer OK | ovis wrong))

| rank | peer | rescue_rate |
| --- | --- | --- |
| 1 | glm | 16.3% |
| 2 | opus | 16.3% |
| 3 | flash | 13.8% |
| 4 | paddle | 12.8% |
| 5 | deepseek | 11.3% |

## `formula`

Ovis alone: **0.9129** (n=313, wrong@0.05≈164)

### Rank by oracle gain vs ovis

| rank | peer | oracle_gain | oracle_score | rescue_given_ovis_wrong |
| --- | --- | --- | --- | --- |
| 1 | paddle | +0.0192 | 0.9321 | 14.6% |
| 2 | flash | +0.0144 | 0.9273 | 10.4% |
| 3 | opus | +0.0133 | 0.9262 | 11.6% |
| 4 | glm | +0.0125 | 0.9254 | 4.9% |
| 5 | deepseek | +0.0103 | 0.9232 | 7.3% |

### Rank by rescue rate (P(peer OK | ovis wrong))

| rank | peer | rescue_rate |
| --- | --- | --- |
| 1 | paddle | 14.6% |
| 2 | opus | 11.6% |
| 3 | flash | 10.4% |
| 4 | deepseek | 7.3% |
| 5 | glm | 4.9% |

## `table`

Ovis alone: **0.9486** (n=458, wrong@0.05≈131)

### Rank by oracle gain vs ovis

| rank | peer | oracle_gain | oracle_score | rescue_given_ovis_wrong |
| --- | --- | --- | --- | --- |
| 1 | paddle | +0.0167 | 0.9654 | 19.8% |
| 2 | glm | +0.0061 | 0.9547 | 9.2% |
| 3 | deepseek | +0.0050 | 0.9536 | 9.9% |
| 4 | flash | +0.0043 | 0.9529 | 6.1% |
| 5 | opus | +0.0002 | 0.9489 | 0.0% |

### Rank by rescue rate (P(peer OK | ovis wrong))

| rank | peer | rescue_rate |
| --- | --- | --- |
| 1 | paddle | 19.8% |
| 2 | deepseek | 9.9% |
| 3 | glm | 9.2% |
| 4 | flash | 6.1% |
| 5 | opus | 0.0% |

## `reading_order`

Ovis alone: **0.8871** (n=1638, wrong@0.05≈617)

### Rank by oracle gain vs ovis

| rank | peer | oracle_gain | oracle_score | rescue_given_ovis_wrong |
| --- | --- | --- | --- | --- |
| 1 | opus | +0.0106 | 0.8978 | 8.1% |
| 2 | flash | +0.0075 | 0.8946 | 5.3% |
| 3 | paddle | +0.0068 | 0.8940 | 5.3% |
| 4 | glm | +0.0067 | 0.8938 | 3.7% |
| 5 | deepseek | +0.0057 | 0.8929 | 4.2% |

### Rank by rescue rate (P(peer OK | ovis wrong))

| rank | peer | rescue_rate |
| --- | --- | --- |
| 1 | opus | 8.1% |
| 2 | paddle | 5.3% |
| 3 | flash | 5.3% |
| 4 | deepseek | 4.2% |
| 5 | glm | 3.7% |

