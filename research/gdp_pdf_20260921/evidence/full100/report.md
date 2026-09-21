# GDP.pdf — does compiled TAVONEL context help a frontier model?

**NOT OFFICIAL-COMPARABLE.** Three sealed deviations, all deliberate:

1. **Surface** `claude-code-read-tool` — the official condition disables tools; here the Read tool is enabled so the model pages through the PDF agentically.
2. **Judge** `claude-opus-5 (non-official)` — the official protocol names `gemini-3.5-flash`; no Gemini key is available in this lane.
3. **Dataset revision** — the sealed revision's `data.parquet` blob is stranded on a retired CDN host (403). The run is pinned to the head commit instead; both digests are in the manifest.

Nothing here is a same-condition comparison with any published GDP.pdf score, and no row may be quoted next to one.

## Run

- dataset revision run: `8d1efb32cb57baec2265bb84da03b30654761373`
- sealed revision (unreachable): `400e411fc344b1b8dd2a51e70a7ecdf469c05b3c`
- task set digest: `002416ec3b2b51083d74b403f8bba300ba85aca622efddb38c6b1b346b4c9381`
- tasks in catalog: 100
- seed: `gdp-pdf-20260921`
- cells recorded: 200

## Headline, per arm

Macro = every rubric criterion passed. Micro = mean fraction of criteria passed. A subject, adapter or judge failure is a zero that stays in the denominator.

| arm | n (denominator) | macro all-pass | micro mean-criteria | criteria passed | subject fail | adapter fail | judge fail |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `native_pdf` | 100 | 31.0% (31/100) | 79.3% | 1032/1275 | 1 | 0 | 1 |
| `compiled_context_pdf` | 100 | 27.0% (27/100) | 71.3% | 948/1275 | 1 | 11 | 0 |

## Cost, tokens and latency, per arm

`api-equivalent list price` is a LIST-PRICE EQUIVALENT for a run billed to a Claude Max subscription. It is never an invoice amount. Input tokens are the sum of uncached, cache-creation and cache-read tokens; the arena price snapshot has no cache-token price, so where `cost complete` is false the money column covers uncached input and output only and **understates** the run.

| arm | n | input tokens | output tokens | p50 latency | p95 latency | subject $ (list-equiv) | judge $ (list-equiv) | cost complete |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `native_pdf` | 100 | 27,229,987 | 1,049,711 | 98.7s | 299.8s | $26.2471 | $3.3430 | False |
| `compiled_context_pdf` | 100 | 24,154,317 | 1,052,221 | 116.5s | 345.3s | $26.3100 | $3.2732 | False |

## Per domain

Every cell carries its own denominator: macro is `share (all-pass / n)`, micro is `share (criteria passed / criteria total)`.

| domain | native n | native macro | native micro | compiled n | compiled macro | compiled micro |
| --- | --- | --- | --- | --- | --- | --- |
| Construction | 10 | 30.0% (3/10) | 73.7% (112/138) | 10 | 30.0% (3/10) | 72.4% (111/138) |
| Engineering | 10 | 10.0% (1/10) | 76.8% (84/113) | 10 | 10.0% (1/10) | 71.8% (85/113) |
| Finance/Investing | 9 | 11.1% (1/9) | 78.9% (86/101) | 9 | 33.3% (3/9) | 75.3% (83/101) |
| HR | 9 | 66.7% (6/9) | 92.1% (100/105) | 9 | 55.6% (5/9) | 89.9% (99/105) |
| Healthcare | 11 | 36.4% (4/11) | 75.8% (110/142) | 11 | 18.2% (2/11) | 82.6% (120/142) |
| Insurance | 9 | 44.4% (4/9) | 86.7% (132/152) | 9 | 22.2% (2/9) | 51.7% (81/152) |
| Legal | 7 | 42.9% (3/7) | 86.2% (79/93) | 7 | 28.6% (2/7) | 72.1% (72/93) |
| Manufacturing/Supply Chains | 10 | 20.0% (2/10) | 70.8% (100/153) | 10 | 40.0% (4/10) | 69.4% (94/153) |
| Real Estate | 10 | 10.0% (1/10) | 71.6% (95/119) | 10 | 0.0% (0/10) | 59.5% (88/119) |
| STEM/Research | 15 | 40.0% (6/15) | 82.9% (134/159) | 15 | 33.3% (5/15) | 68.8% (115/159) |

## Pairwise delta (compiled_context_pdf − native_pdf)

Computed only over the **100** tasks that have a cell in both arms.

| metric | native | compiled | delta (pp) | paired n |
| --- | --- | --- | --- | --- |
| macro all-pass | 31.0% | 27.0% | -4.0 | 100 |
| micro mean-criteria | 79.3% | 71.3% | -8.0 | 100 |

### Secondary cut: only the tasks where a compiled packet actually existed

**A different denominator (n = 89), not a replacement headline.** The headline above keeps the adapter failures in the denominator, as the sealed failure policy requires. This cut drops them so that 'no packet existed for this document' can be told apart from 'the packet did not help'. Quoting this row without its denominator would be a misreport.

| metric | native | compiled | delta (pp) | n |
| --- | --- | --- | --- | --- |
| macro all-pass | 31.5% | 30.3% | -1.1 | 89 |
| micro mean-criteria | 79.2% | 80.1% | +0.9 | 89 |

## Hardest documents

Ranked by the sum of the two arms’ micro scores, hardest first; at most 15 rows. `NOT_RUN` means that arm has no cell for the task, which is never the same as a zero. `scanned?` is true when the compiled arm refused the document as `scanned_no_text_layer` — a zero that stays in the denominator.

| task | domain | pages | criteria | scanned? | native pass | compiled pass | native all-pass | compiled all-pass | failure |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `758bb8e1` | Manufacturing/Supply Chains | 5 | 26 | False | 0/26 | 0/26 | False | False | TIMEOUT |
| `973081e7` | Real Estate | 1 | 4 | False | 1/4 | 0/4 | False | False | - |
| `e88c1006` | Finance/Investing | 168 | 6 | False | 1/6 | 1/6 | False | False | - |
| `0a9aff44` | Healthcare | 61 | 10 | False | 2/10 | 2/10 | False | False | - |
| `31fddf6a` | Construction | 19 | 5 | False | 1/5 | 1/5 | False | False | - |
| `6070d5f8` | Real Estate | 60 | 5 | True | 3/5 | 0/5 | False | False | scanned_no_text_layer |
| `cf79b3db` | Insurance | 5 | 8 | True | 5/8 | 0/8 | False | False | scanned_no_text_layer |
| `bffc3940` | Engineering | 5 | 17 | False | 2/17 | 9/17 | False | False | - |
| `3c825f54` | Legal | 7 | 6 | True | 4/6 | 0/6 | False | False | scanned_no_text_layer |
| `efb22c1d` | Insurance | 11 | 26 | True | 19/26 | 0/26 | False | False | scanned_no_text_layer |
| `f3537e1f` | Manufacturing/Supply Chains | 40 | 21 | True | 16/21 | 0/21 | False | False | scanned_no_text_layer |
| `685a9467` | Finance/Investing | 16 | 9 | True | 7/9 | 0/9 | False | False | scanned_no_text_layer |
| `f8e8f09e` | STEM/Research | 9 | 14 | True | 11/14 | 0/14 | False | False | scanned_no_text_layer |
| `678d01ed` | Construction | 16 | 5 | False | 2/5 | 2/5 | False | False | - |
| `aff4bf86` | Engineering | 1 | 7 | True | 6/7 | 0/7 | False | False | scanned_no_text_layer |

## Compiled arm: what Product Core actually produced

Per-document compile facts for every cell that had a packet. The full per-document rows are in the cell ledger under `evidence/`; this is their spread. `REGION_CITATION_UNAVAILABLE` counts the documents where at least one unit could not be cited to a region -- the defect that made the superseded v1 adapter degenerate.

- documents with a packet: **89**
- adapter versions in this run: `{'gdp-pdf-compiled-context/2-geometry': 89}`
- candidate lifecycle: `{'candidate': 65, 'review_required': 24}`
- documents with an unresolvable citation: **0**

| quantity | reported for | min | median | max | total |
| --- | --- | --- | --- | --- | --- |
| regions | 89 | 2 | 510 | 7,114 | 84,891 |
| claims | 89 | 0 | 162 | 1,538 | 24,649 |
| entities | 89 | 0 | 36 | 1,373 | 8,146 |
| relations | 89 | 0 | 68 | 5,035 | 20,623 |

## Compiled packet size against PDF pages

Characters and bytes are measured from the packet files. **Token counts are NOT_MEASURED**: this lane has no tokenizer for the surface’s model, and an estimate would be an invented number. The measured token totals are the per-arm figures in the cost table, which cover the whole conversation rather than the packet alone.

| metric | value |
| --- | --- |
| packets attached to a scored cell (n) | 89 |
| packet chars, min | 16,152 |
| packet chars, median | 399,387 |
| packet chars, max | 399,995 |
| packet chars per PDF page, median | 9,089 |
| packets truncated by the stated budget rule | 53 of 89 |
| packet tokens | NOT_RUN |

## Case candidates (the two arms disagree)

**51** paired tasks scored differently. Criterion numbers are 1-based indices into that task’s rubric in the out-of-repo catalog; rubric text and answer text stay in the restricted run store and are not reproduced here. A human opens the run-store record and pulls the excerpts.

| task | domain | pages | native | compiled | criteria gained by compiled | criteria lost by compiled | adapter |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `7b61426a` | Insurance | 7 | 19/19 | 0/19 | NOT_RUN | NOT_RUN | scanned_no_text_layer |
| `efb22c1d` | Insurance | 11 | 19/26 | 0/26 | NOT_RUN | NOT_RUN | scanned_no_text_layer |
| `f3537e1f` | Manufacturing/Supply Chains | 40 | 16/21 | 0/21 | NOT_RUN | NOT_RUN | scanned_no_text_layer |
| `ce1c33a2` | Insurance | 8 | 12/12 | 0/12 | NOT_RUN | NOT_RUN | scanned_no_text_layer |
| `f8e8f09e` | STEM/Research | 9 | 11/14 | 0/14 | NOT_RUN | NOT_RUN | scanned_no_text_layer |
| `0fd75f2a` | Healthcare | 46 | 0/11 | 10/11 | NOT_RUN | NOT_RUN | - |
| `1b234b39` | STEM/Research | 73 | 7/7 | 0/7 | NOT_RUN | NOT_RUN | scanned_no_text_layer |
| `685a9467` | Finance/Investing | 16 | 7/9 | 0/9 | NOT_RUN | NOT_RUN | scanned_no_text_layer |
| `bffc3940` | Engineering | 5 | 2/17 | 9/17 | NOT_RUN | NOT_RUN | - |
| `aff4bf86` | Engineering | 1 | 6/7 | 0/7 | NOT_RUN | NOT_RUN | scanned_no_text_layer |
| `9ef247ac` | Manufacturing/Supply Chains | 10 | 5/16 | 10/16 | NOT_RUN | NOT_RUN | - |
| `cf79b3db` | Insurance | 5 | 5/8 | 0/8 | NOT_RUN | NOT_RUN | scanned_no_text_layer |
| `ef0c1dae` | Manufacturing/Supply Chains | 6 | 9/14 | 14/14 | NOT_RUN | NOT_RUN | - |
| `3c825f54` | Legal | 7 | 4/6 | 0/6 | NOT_RUN | NOT_RUN | scanned_no_text_layer |
| `39305def` | Engineering | 29 | 10/12 | 7/12 | NOT_RUN | NOT_RUN | - |
| `6070d5f8` | Real Estate | 60 | 3/5 | 0/5 | NOT_RUN | NOT_RUN | scanned_no_text_layer |
| `bc7a2336` | Construction | 4 | 14/18 | 11/18 | NOT_RUN | NOT_RUN | - |
| `07bd6ec8` | Construction | 186 | 22/30 | 24/30 | NOT_RUN | NOT_RUN | - |
| `1972f647` | Real Estate | 133 | 17/19 | 15/19 | NOT_RUN | NOT_RUN | - |
| `3a57f0dd` | Insurance | 23 | 24/27 | 26/27 | NOT_RUN | NOT_RUN | - |
| `51a8912f` | Finance/Investing | 96 | 7/10 | 9/10 | NOT_RUN | NOT_RUN | - |
| `51dd4196` | STEM/Research | 18 | 8/9 | 6/9 | NOT_RUN | NOT_RUN | - |
| `5b8b9a5c` | Insurance | 148 | 9/15 | 11/15 | NOT_RUN | NOT_RUN | - |
| `7a635a6c` | HR | 32 | 7/7 | 5/7 | NOT_RUN | NOT_RUN | - |
| `8a33d88a` | Engineering | 20 | 10/14 | 12/14 | NOT_RUN | NOT_RUN | - |
| `8b7a7757` | Healthcare | 8 | 18/20 | 20/20 | NOT_RUN | NOT_RUN | - |
| `8e4302b1` | STEM/Research | 9 | 3/9 | 5/9 | NOT_RUN | NOT_RUN | - |
| `b8ca9504` | Legal | 18 | 7/7 | 5/7 | NOT_RUN | NOT_RUN | - |
| `d3577698` | STEM/Research | 25 | 25/27 | 27/27 | NOT_RUN | NOT_RUN | - |
| `07c2939f` | Legal | 81 | 17/27 | 16/27 | NOT_RUN | NOT_RUN | - |
| `0b20f122` | STEM/Research | 3 | 5/9 | 4/9 | NOT_RUN | NOT_RUN | - |
| `24cc14c6` | STEM/Research | 21 | 8/8 | 7/8 | NOT_RUN | NOT_RUN | - |
| `49aef554` | Engineering | 34 | 7/7 | 6/7 | NOT_RUN | NOT_RUN | - |
| `4f7c770c` | Manufacturing/Supply Chains | 12 | 9/10 | 10/10 | NOT_RUN | NOT_RUN | - |
| `54081561` | Construction | 14 | 14/18 | 15/18 | NOT_RUN | NOT_RUN | - |
| `56a40a31` | Healthcare | 13 | 12/12 | 11/12 | NOT_RUN | NOT_RUN | - |
| `5d172536` | Finance/Investing | 113 | 16/17 | 17/17 | NOT_RUN | NOT_RUN | - |
| `6281ab61` | Healthcare | 123 | 8/8 | 7/8 | NOT_RUN | NOT_RUN | - |
| `69d04c9a` | Real Estate | 6 | 5/5 | 4/5 | NOT_RUN | NOT_RUN | - |
| `726c7512` | HR | 15 | 9/11 | 10/11 | NOT_RUN | NOT_RUN | - |
| `85132bb8` | STEM/Research | 26 | 4/6 | 3/6 | NOT_RUN | NOT_RUN | - |
| `8a74919b` | Engineering | 27 | 27/29 | 28/29 | NOT_RUN | NOT_RUN | - |
| `957eb1d3` | Healthcare | 85 | 18/23 | 19/23 | NOT_RUN | NOT_RUN | - |
| `973081e7` | Real Estate | 1 | 1/4 | 0/4 | NOT_RUN | NOT_RUN | - |
| `9a33920e` | Healthcare | 88 | 10/10 | 9/10 | NOT_RUN | NOT_RUN | - |
| `9ab9663f` | Construction | 34 | 9/11 | 8/11 | NOT_RUN | NOT_RUN | - |
| `9cf542c7` | Engineering | 46 | 5/6 | 6/6 | NOT_RUN | NOT_RUN | - |
| `b3c898f3` | Finance/Investing | 12 | 4/5 | 5/5 | NOT_RUN | NOT_RUN | - |
| `b69eac3c` | Real Estate | 7 | 7/10 | 6/10 | NOT_RUN | NOT_RUN | - |
| `e593949e` | Manufacturing/Supply Chains | 39 | 4/7 | 3/7 | NOT_RUN | NOT_RUN | - |
| `fa00520d` | Real Estate | 8 | 16/21 | 17/21 | NOT_RUN | NOT_RUN | - |

## Case study

Raw prompts, answers and judge rationales are in the restricted run store, never in this repository. To fill a case study, open the run-store record for the task and copy in the excerpts by hand; leave every row below as NOT_RUN until then.

| field | value |
| --- | --- |
| task_id | NOT_RUN |
| domain | NOT_RUN |
| question | NOT_RUN |
| native answer excerpt | NOT_RUN |
| compiled answer excerpt | NOT_RUN |
| judge criteria the arms differ on | NOT_RUN |
| evidence locator (page / chunk / evidence id) | NOT_RUN |
| run-store path | NOT_RUN |

## Not run

The `fixed_control_retrieval_rerank` and `adaptive_router` arms of the sealed four-arm protocol were not executed in this lane. They are NOT_RUN, not zero.
