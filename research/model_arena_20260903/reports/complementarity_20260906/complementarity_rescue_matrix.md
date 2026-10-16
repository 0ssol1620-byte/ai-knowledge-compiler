# Complementarity Rescue / Overlap Matrix

Discrete metrics at **tau=0.05** (wrong if edit > tau).
Rescue rate = `P(B correct | A wrong)`. Overlap = `P(B wrong | A wrong)`.

## Element: `text`

### Rescue rate matrix (diag = P(wrong) at tau)

| rescue P(col OK|row wrong); diag=P(wrong) | paddle | ovis | flash | deepseek | glm | opus |
| --- | --- | --- | --- | --- | --- | --- |
| paddle | 20.3% | 44.0% | 34.2% | 30.1% | 22.8% | 35.8% |
| ovis | 12.8% | 13.0% | 13.8% | 11.3% | 16.3% | 16.3% |
| flash | 37.9% | 47.8% | 21.5% | 29.6% | 20.6% | 28.1% |
| deepseek | 43.5% | 54.0% | 39.6% | 25.1% | 38.4% | 37.3% |
| glm | 42.0% | 59.6% | 36.8% | 42.8% | 27.0% | 40.1% |
| opus | 50.7% | 58.7% | 41.5% | 40.5% | 38.8% | 26.5% |

### Overlap P(B wrong | A wrong)

| overlap P(col wrong|row wrong) | paddle | ovis | flash | deepseek | glm | opus |
| --- | --- | --- | --- | --- | --- | --- |
| paddle | 20.3% | 56.0% | 65.8% | 69.9% | 77.2% | 64.2% |
| ovis | 87.2% | 13.0% | 86.2% | 88.7% | 83.7% | 83.7% |
| flash | 62.1% | 52.2% | 21.5% | 70.4% | 79.4% | 71.9% |
| deepseek | 56.5% | 46.0% | 60.4% | 25.1% | 61.6% | 62.7% |
| glm | 58.0% | 40.4% | 63.2% | 57.2% | 27.0% | 59.9% |
| opus | 49.3% | 41.3% | 58.5% | 59.5% | 61.2% | 26.5% |

### P(both wrong) on shared pages

| P(both wrong) | paddle | ovis | flash | deepseek | glm | opus |
| --- | --- | --- | --- | --- | --- | --- |
| paddle | 20.3% | 11.4% | 13.4% | 14.2% | 15.7% | 13.0% |
| ovis | 11.4% | 13.0% | 11.2% | 11.6% | 10.9% | 10.9% |
| flash | 13.4% | 11.2% | 21.5% | 15.2% | 17.1% | 15.5% |
| deepseek | 14.2% | 11.6% | 15.2% | 25.1% | 15.5% | 15.7% |
| glm | 15.7% | 10.9% | 17.1% | 15.5% | 27.0% | 16.2% |
| opus | 13.0% | 10.9% | 15.5% | 15.7% | 16.2% | 26.5% |

### Disagreement stats (pairwise)

| pair | n_pages | P_disagree | P(A wrong|disagree) | P_both_wrong | rescue_B|A_wrong | rescue_A|B_wrong |
| --- | --- | --- | --- | --- | --- | --- |
| deepseek+glm | 1557 | 62.0% | 37.8% | 15.5% | 38.4% | 42.8% |
| deepseek+opus | 1557 | 61.3% | 38.8% | 15.7% | 37.3% | 40.5% |
| flash+deepseek | 1557 | 54.8% | 35.1% | 15.2% | 29.6% | 39.6% |
| flash+glm | 1557 | 56.5% | 33.0% | 17.1% | 20.6% | 36.8% |
| flash+opus | 1557 | 58.3% | 34.1% | 15.5% | 28.1% | 41.5% |
| glm+opus | 1557 | 64.9% | 39.6% | 16.2% | 40.1% | 38.8% |
| ovis+deepseek | 1557 | 49.6% | 21.9% | 11.6% | 11.3% | 54.0% |
| ovis+flash | 1557 | 47.6% | 22.3% | 11.2% | 13.8% | 47.8% |
| ovis+glm | 1557 | 57.5% | 20.0% | 10.9% | 16.3% | 59.6% |
| ovis+opus | 1557 | 52.8% | 21.5% | 10.9% | 16.3% | 58.7% |
| paddle+deepseek | 1557 | 55.6% | 32.7% | 14.2% | 30.1% | 43.5% |
| paddle+flash | 1557 | 56.8% | 32.4% | 13.4% | 34.2% | 37.9% |
| paddle+glm | 1557 | 60.1% | 29.9% | 15.7% | 22.8% | 42.0% |
| paddle+opus | 1557 | 62.7% | 30.8% | 13.0% | 35.8% | 50.7% |
| paddle+ovis | 1557 | 48.9% | 36.3% | 11.4% | 44.0% | 12.8% |

### When Paddle is wrong: peer rescue

| peer | n_pages | n_paddle_wrong | rescue_rate | P(peer wrong|paddle wrong) | P(both wrong) |
| --- | --- | --- | --- | --- | --- |
| ovis | 1557 | 316 | 44.0% | 56.0% | 11.4% |
| flash | 1557 | 316 | 34.2% | 65.8% | 13.4% |
| deepseek | 1557 | 316 | 30.1% | 69.9% | 14.2% |
| glm | 1557 | 316 | 22.8% | 77.2% | 15.7% |
| opus | 1557 | 316 | 35.8% | 64.2% | 13.0% |

## Element: `formula`

### Rescue rate matrix (diag = P(wrong) at tau)

| rescue P(col OK|row wrong); diag=P(wrong) | paddle | ovis | flash | deepseek | glm | opus |
| --- | --- | --- | --- | --- | --- | --- |
| paddle | 50.5% | 11.4% | 15.2% | 8.9% | 5.1% | 13.3% |
| ovis | 14.6% | 52.4% | 10.4% | 7.3% | 4.9% | 11.6% |
| flash | 30.9% | 24.2% | 62.0% | 20.1% | 6.2% | 16.0% |
| deepseek | 24.6% | 20.4% | 18.8% | 61.0% | 6.3% | 16.2% |
| glm | 42.5% | 40.2% | 30.3% | 31.4% | 83.4% | 33.3% |
| opus | 28.6% | 24.5% | 15.1% | 16.7% | 9.4% | 61.3% |

### Overlap P(B wrong | A wrong)

| overlap P(col wrong|row wrong) | paddle | ovis | flash | deepseek | glm | opus |
| --- | --- | --- | --- | --- | --- | --- |
| paddle | 50.5% | 88.6% | 84.8% | 91.1% | 94.9% | 86.7% |
| ovis | 85.4% | 52.4% | 89.6% | 92.7% | 95.1% | 88.4% |
| flash | 69.1% | 75.8% | 62.0% | 79.9% | 93.8% | 84.0% |
| deepseek | 75.4% | 79.6% | 81.2% | 61.0% | 93.7% | 83.8% |
| glm | 57.5% | 59.8% | 69.7% | 68.6% | 83.4% | 66.7% |
| opus | 71.4% | 75.5% | 84.9% | 83.3% | 90.6% | 61.3% |

### P(both wrong) on shared pages

| P(both wrong) | paddle | ovis | flash | deepseek | glm | opus |
| --- | --- | --- | --- | --- | --- | --- |
| paddle | 50.5% | 44.7% | 42.8% | 46.0% | 47.9% | 43.8% |
| ovis | 44.7% | 52.4% | 47.0% | 48.6% | 49.8% | 46.3% |
| flash | 42.8% | 47.0% | 62.0% | 49.5% | 58.1% | 52.1% |
| deepseek | 46.0% | 48.6% | 49.5% | 61.0% | 57.2% | 51.1% |
| glm | 47.9% | 49.8% | 58.1% | 57.2% | 83.4% | 55.6% |
| opus | 43.8% | 46.3% | 52.1% | 51.1% | 55.6% | 61.3% |

### Disagreement stats (pairwise)

| pair | n_pages | P_disagree | P(A wrong|disagree) | P_both_wrong | rescue_B|A_wrong | rescue_A|B_wrong |
| --- | --- | --- | --- | --- | --- | --- |
| deepseek+glm | 313 | 95.2% | 62.8% | 57.2% | 6.3% | 31.4% |
| deepseek+opus | 313 | 85.6% | 68.3% | 51.1% | 16.2% | 16.7% |
| flash+deepseek | 313 | 83.4% | 69.7% | 49.5% | 20.1% | 18.8% |
| flash+glm | 313 | 93.6% | 64.8% | 58.1% | 6.2% | 30.3% |
| flash+opus | 313 | 78.6% | 68.7% | 52.1% | 16.0% | 15.1% |
| glm+opus | 313 | 97.1% | 85.5% | 55.6% | 33.3% | 9.4% |
| ovis+deepseek | 313 | 70.6% | 64.3% | 48.6% | 7.3% | 20.4% |
| ovis+flash | 313 | 78.9% | 60.3% | 47.0% | 10.4% | 24.2% |
| ovis+glm | 313 | 94.2% | 52.9% | 49.8% | 4.9% | 40.2% |
| ovis+opus | 313 | 80.5% | 60.3% | 46.3% | 11.6% | 24.5% |
| paddle+deepseek | 313 | 72.5% | 64.3% | 46.0% | 8.9% | 24.6% |
| paddle+flash | 313 | 82.1% | 58.8% | 42.8% | 15.2% | 30.9% |
| paddle+glm | 313 | 94.9% | 51.9% | 47.9% | 5.1% | 42.5% |
| paddle+opus | 313 | 81.2% | 58.7% | 43.8% | 13.3% | 28.6% |
| paddle+ovis | 313 | 65.2% | 67.2% | 44.7% | 11.4% | 14.6% |

### When Paddle is wrong: peer rescue

| peer | n_pages | n_paddle_wrong | rescue_rate | P(peer wrong|paddle wrong) | P(both wrong) |
| --- | --- | --- | --- | --- | --- |
| ovis | 313 | 158 | 11.4% | 88.6% | 44.7% |
| flash | 313 | 158 | 15.2% | 84.8% | 42.8% |
| deepseek | 313 | 158 | 8.9% | 91.1% | 46.0% |
| glm | 313 | 158 | 5.1% | 94.9% | 47.9% |
| opus | 313 | 158 | 13.3% | 86.7% | 43.8% |

## Element: `table`

### Rescue rate matrix (diag = P(wrong) at tau)

| rescue P(col OK|row wrong); diag=P(wrong) | paddle | ovis | flash | deepseek | glm | opus |
| --- | --- | --- | --- | --- | --- | --- |
| paddle | 29.5% | 22.2% | 9.6% | 9.6% | 6.7% | 0.0% |
| ovis | 19.8% | 28.6% | 6.1% | 9.9% | 9.2% | 0.0% |
| flash | 42.7% | 42.3% | 46.5% | 22.5% | 18.8% | 0.5% |
| deepseek | 35.4% | 37.6% | 12.7% | 41.3% | 11.6% | 0.5% |
| glm | 60.5% | 62.7% | 45.8% | 47.6% | 69.7% | 1.9% |
| opus | 69.7% | 70.6% | 52.5% | 57.8% | 29.8% | 97.4% |

### Overlap P(B wrong | A wrong)

| overlap P(col wrong|row wrong) | paddle | ovis | flash | deepseek | glm | opus |
| --- | --- | --- | --- | --- | --- | --- |
| paddle | 29.5% | 77.8% | 90.4% | 90.4% | 93.3% | 100.0% |
| ovis | 80.2% | 28.6% | 93.9% | 90.1% | 90.8% | 100.0% |
| flash | 57.3% | 57.7% | 46.5% | 77.5% | 81.2% | 99.5% |
| deepseek | 64.6% | 62.4% | 87.3% | 41.3% | 88.4% | 99.5% |
| glm | 39.5% | 37.3% | 54.2% | 52.4% | 69.7% | 98.1% |
| opus | 30.3% | 29.4% | 47.5% | 42.2% | 70.2% | 97.4% |

### P(both wrong) on shared pages

| P(both wrong) | paddle | ovis | flash | deepseek | glm | opus |
| --- | --- | --- | --- | --- | --- | --- |
| paddle | 29.5% | 22.9% | 26.6% | 26.6% | 27.5% | 29.5% |
| ovis | 22.9% | 28.6% | 26.9% | 25.8% | 26.0% | 28.6% |
| flash | 26.6% | 26.9% | 46.5% | 36.0% | 37.8% | 46.3% |
| deepseek | 26.6% | 25.8% | 36.0% | 41.3% | 36.5% | 41.0% |
| glm | 27.5% | 26.0% | 37.8% | 36.5% | 69.7% | 68.3% |
| opus | 29.5% | 28.6% | 46.3% | 41.0% | 68.3% | 97.4% |

### Disagreement stats (pairwise)

| pair | n_pages | P_disagree | P(A wrong|disagree) | P_both_wrong | rescue_B|A_wrong | rescue_A|B_wrong |
| --- | --- | --- | --- | --- | --- | --- |
| deepseek+glm | 458 | 86.7% | 45.1% | 36.5% | 11.6% | 47.6% |
| deepseek+opus | 458 | 98.5% | 41.5% | 41.0% | 0.5% | 57.8% |
| flash+deepseek | 458 | 61.8% | 64.7% | 36.0% | 22.5% | 12.7% |
| flash+glm | 458 | 85.2% | 50.8% | 37.8% | 18.8% | 45.8% |
| flash+opus | 458 | 98.9% | 46.8% | 46.3% | 0.5% | 52.5% |
| glm+opus | 458 | 98.5% | 69.6% | 68.3% | 1.9% | 29.8% |
| ovis+deepseek | 458 | 63.5% | 41.2% | 25.8% | 9.9% | 37.6% |
| ovis+flash | 458 | 63.5% | 40.5% | 26.9% | 6.1% | 42.3% |
| ovis+glm | 458 | 85.4% | 32.0% | 26.0% | 9.2% | 62.7% |
| ovis+opus | 458 | 98.9% | 28.9% | 28.6% | 0.0% | 70.6% |
| paddle+deepseek | 458 | 72.5% | 37.3% | 26.6% | 9.6% | 35.4% |
| paddle+flash | 458 | 74.7% | 36.8% | 26.6% | 9.6% | 42.7% |
| paddle+glm | 458 | 91.0% | 31.7% | 27.5% | 6.7% | 60.5% |
| paddle+opus | 458 | 99.6% | 29.6% | 29.5% | 0.0% | 69.7% |
| paddle+ovis | 458 | 69.4% | 39.0% | 22.9% | 22.2% | 19.8% |

### When Paddle is wrong: peer rescue

| peer | n_pages | n_paddle_wrong | rescue_rate | P(peer wrong|paddle wrong) | P(both wrong) |
| --- | --- | --- | --- | --- | --- |
| ovis | 458 | 135 | 22.2% | 77.8% | 22.9% |
| flash | 458 | 135 | 9.6% | 90.4% | 26.6% |
| deepseek | 458 | 135 | 9.6% | 90.4% | 26.6% |
| glm | 458 | 135 | 6.7% | 93.3% | 27.5% |
| opus | 458 | 135 | 0.0% | 100.0% | 29.5% |

## Element: `reading_order`

### Rescue rate matrix (diag = P(wrong) at tau)

| rescue P(col OK|row wrong); diag=P(wrong) | paddle | ovis | flash | deepseek | glm | opus |
| --- | --- | --- | --- | --- | --- | --- |
| paddle | 44.0% | 18.9% | 14.7% | 11.9% | 4.4% | 15.8% |
| ovis | 5.3% | 37.7% | 5.3% | 4.2% | 3.7% | 8.1% |
| flash | 14.8% | 19.0% | 44.0% | 9.4% | 6.0% | 12.5% |
| deepseek | 15.9% | 21.6% | 13.4% | 46.0% | 9.3% | 17.0% |
| glm | 26.1% | 36.2% | 27.2% | 26.5% | 56.8% | 28.8% |
| opus | 18.4% | 23.7% | 15.1% | 15.7% | 10.8% | 45.4% |

### Overlap P(B wrong | A wrong)

| overlap P(col wrong|row wrong) | paddle | ovis | flash | deepseek | glm | opus |
| --- | --- | --- | --- | --- | --- | --- |
| paddle | 44.0% | 81.1% | 85.3% | 88.1% | 95.6% | 84.2% |
| ovis | 94.7% | 37.7% | 94.7% | 95.8% | 96.3% | 91.9% |
| flash | 85.2% | 81.0% | 44.0% | 90.6% | 94.0% | 87.5% |
| deepseek | 84.1% | 78.4% | 86.6% | 46.0% | 90.7% | 83.0% |
| glm | 73.9% | 63.8% | 72.8% | 73.5% | 56.8% | 71.2% |
| opus | 81.6% | 76.3% | 84.9% | 84.3% | 89.2% | 45.4% |

### P(both wrong) on shared pages

| P(both wrong) | paddle | ovis | flash | deepseek | glm | opus |
| --- | --- | --- | --- | --- | --- | --- |
| paddle | 44.0% | 35.7% | 37.5% | 38.7% | 42.0% | 37.0% |
| ovis | 35.7% | 37.7% | 35.7% | 36.1% | 36.3% | 34.6% |
| flash | 37.5% | 35.7% | 44.0% | 39.9% | 41.4% | 38.5% |
| deepseek | 38.7% | 36.1% | 39.9% | 46.0% | 41.8% | 38.2% |
| glm | 42.0% | 36.3% | 41.4% | 41.8% | 56.8% | 40.5% |
| opus | 37.0% | 34.6% | 38.5% | 38.2% | 40.5% | 45.4% |

### Disagreement stats (pairwise)

| pair | n_pages | P_disagree | P(A wrong|disagree) | P_both_wrong | rescue_B|A_wrong | rescue_A|B_wrong |
| --- | --- | --- | --- | --- | --- | --- |
| deepseek+glm | 1638 | 38.7% | 60.3% | 41.8% | 9.3% | 26.5% |
| deepseek+opus | 1638 | 29.1% | 72.7% | 38.2% | 17.0% | 15.7% |
| flash+deepseek | 1638 | 23.1% | 69.6% | 39.9% | 9.4% | 13.4% |
| flash+glm | 1638 | 35.8% | 55.5% | 41.4% | 6.0% | 27.2% |
| flash+opus | 1638 | 25.6% | 70.9% | 38.5% | 12.5% | 15.1% |
| glm+opus | 1638 | 40.8% | 86.7% | 40.5% | 28.8% | 10.8% |
| ovis+deepseek | 1638 | 21.8% | 49.9% | 36.1% | 4.2% | 21.6% |
| ovis+flash | 1638 | 18.4% | 52.6% | 35.7% | 5.3% | 19.0% |
| ovis+glm | 1638 | 36.6% | 41.9% | 36.3% | 3.7% | 36.2% |
| ovis+opus | 1638 | 23.0% | 50.3% | 34.6% | 8.1% | 23.7% |
| paddle+deepseek | 1638 | 25.3% | 68.2% | 38.7% | 11.9% | 15.9% |
| paddle+flash | 1638 | 24.5% | 70.6% | 37.5% | 14.7% | 14.8% |
| paddle+glm | 1638 | 34.6% | 55.5% | 42.0% | 4.4% | 26.1% |
| paddle+opus | 1638 | 29.1% | 67.7% | 37.0% | 15.8% | 18.4% |
| paddle+ovis | 1638 | 18.1% | 83.2% | 35.7% | 18.9% | 5.3% |

### When Paddle is wrong: peer rescue

| peer | n_pages | n_paddle_wrong | rescue_rate | P(peer wrong|paddle wrong) | P(both wrong) |
| --- | --- | --- | --- | --- | --- |
| ovis | 1638 | 720 | 18.9% | 81.1% | 35.7% |
| flash | 1638 | 720 | 14.7% | 85.3% | 37.5% |
| deepseek | 1638 | 720 | 11.9% | 88.1% | 38.7% |
| glm | 1638 | 720 | 4.4% | 95.6% | 42.0% |
| opus | 1638 | 720 | 15.8% | 84.2% | 37.0% |
