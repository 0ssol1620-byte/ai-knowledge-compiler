# EXP-0101 significance tests

> **NOT CLEARED FOR EXTERNAL DISCLOSURE.** Gate 6 is BLOCKED and the prior-art
> baseline was implemented without §15.3 role separation. Internal and
> exploratory use only — see `receipts/clean-room-provenance.json`.


*exact two-sided McNemar, paired at document-pair level. Holm-Bonferroni over every arm x slice reported here.*
*Reference arm: `current`.*

`arm better` counts cases the arm got right and the reference got wrong;
`reference better` the reverse. Concordant cases carry no information
about a difference and are not in the denominator.

| comparison | arm better | reference better | discordant | p (exact) | p (Holm) |
|---|---|---|---|---|---|
| `baseline::critical_detection` | 0 | 0 | 0 | 1.000e+00 | 1.000e+00 |
| `baseline::layout_false_invalidation` | 155 | 0 | 155 | 4.379e-47 | 8.758e-46 |
| `baseline::layout_false_positive` | 17 | 25 | 42 | 2.800e-01 | 1.000e+00 |
| `baseline::semantic_judgement` | 17 | 25 | 42 | 2.800e-01 | 1.000e+00 |
| `challenger::critical_detection` | 0 | 60 | 60 | 1.735e-18 | 2.602e-17 |
| `challenger::layout_false_invalidation` | 5 | 0 | 5 | 6.250e-02 | 4.375e-01 |
| `challenger::layout_false_positive` | 17 | 0 | 17 | 1.526e-05 | 1.678e-04 |
| `challenger::semantic_judgement` | 17 | 120 | 137 | 2.809e-20 | 4.494e-19 |
| `challenger_no_content::critical_detection` | 0 | 0 | 0 | 1.000e+00 | 1.000e+00 |
| `challenger_no_content::layout_false_invalidation` | 35 | 0 | 35 | 5.821e-11 | 7.567e-10 |
| `challenger_no_content::layout_false_positive` | 16 | 6 | 22 | 5.248e-02 | 4.198e-01 |
| `challenger_no_content::semantic_judgement` | 16 | 66 | 82 | 2.252e-08 | 2.702e-07 |
| `challenger_no_spatial::critical_detection` | 0 | 79 | 79 | 3.309e-24 | 5.956e-23 |
| `challenger_no_spatial::layout_false_invalidation` | 3 | 0 | 3 | 2.500e-01 | 1.000e+00 |
| `challenger_no_spatial::layout_false_positive` | 17 | 0 | 17 | 1.526e-05 | 1.678e-04 |
| `challenger_no_spatial::semantic_judgement` | 17 | 139 | 156 | 5.437e-25 | 1.033e-23 |
| `challenger_no_type_reasoning::critical_detection` | 0 | 60 | 60 | 1.735e-18 | 2.602e-17 |
| `challenger_no_type_reasoning::layout_false_invalidation` | 0 | 0 | 0 | 1.000e+00 | 1.000e+00 |
| `challenger_no_type_reasoning::layout_false_positive` | 12 | 0 | 12 | 4.883e-04 | 4.395e-03 |
| `challenger_no_type_reasoning::semantic_judgement` | 12 | 120 | 132 | 1.422e-23 | 2.417e-22 |
