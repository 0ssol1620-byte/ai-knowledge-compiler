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
- cells recorded: 20

## Headline, per arm

Macro = every rubric criterion passed. Micro = mean fraction of criteria passed. A subject, adapter or judge failure is a zero that stays in the denominator.

| arm | n (denominator) | macro all-pass | micro mean-criteria | criteria passed | subject fail | adapter fail | judge fail |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `native_pdf` | 10 | 70.0% (7/10) | 94.4% | 94/100 | 0 | 0 | 0 |
| `compiled_context_pdf` | 10 | 40.0% (4/10) | 70.5% | 74/100 | 0 | 2 | 0 |

## Cost, tokens and latency, per arm

`api-equivalent list price` is a LIST-PRICE EQUIVALENT for a run billed to a Claude Max subscription. It is never an invoice amount. Input tokens are the sum of uncached, cache-creation and cache-read tokens; the arena price snapshot has no cache-token price, so where `cost complete` is false the money column covers uncached input and output only and **understates** the run.

| arm | n | input tokens | output tokens | p50 latency | p95 latency | subject $ (list-equiv) | judge $ (list-equiv) | cost complete |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `native_pdf` | 10 | 626,821 | 95,555 | 89.0s | 227.9s | $2.3891 | $0.2148 | False |
| `compiled_context_pdf` | 10 | 1,267,951 | 102,094 | 107.3s | 303.1s | $2.5527 | $0.2541 | False |

## Per domain

Every cell carries its own denominator: macro is `share (all-pass / n)`, micro is `share (criteria passed / criteria total)`.

| domain | native n | native macro | native micro | compiled n | compiled macro | compiled micro |
| --- | --- | --- | --- | --- | --- | --- |
| Construction | 1 | 100.0% (1/1) | 100.0% (17/17) | 1 | 100.0% (1/1) | 100.0% (17/17) |
| Healthcare | 1 | 100.0% (1/1) | 100.0% (5/5) | 1 | 0.0% (0/1) | 80.0% (4/5) |
| Insurance | 2 | 100.0% (2/2) | 100.0% (20/20) | 2 | 50.0% (1/2) | 50.0% (8/20) |
| Legal | 2 | 50.0% (1/2) | 95.8% (18/19) | 2 | 50.0% (1/2) | 95.8% (18/19) |
| Real Estate | 1 | 0.0% (0/1) | 75.0% (3/4) | 1 | 0.0% (0/1) | 50.0% (2/4) |
| STEM/Research | 3 | 66.7% (2/3) | 92.6% (31/35) | 3 | 33.3% (1/3) | 61.1% (25/35) |

## Pairwise delta (compiled_context_pdf − native_pdf)

Computed only over the **10** tasks that have a cell in both arms.

| metric | native | compiled | delta (pp) | paired n |
| --- | --- | --- | --- | --- |
| macro all-pass | 70.0% | 40.0% | -30.0 | 10 |
| micro mean-criteria | 94.4% | 70.5% | -23.9 | 10 |

### Secondary cut: only the tasks where a compiled packet actually existed

**A different denominator (n = 8), not a replacement headline.** The headline above keeps the adapter failures in the denominator, as the sealed failure policy requires. This cut drops them so that 'no packet existed for this document' can be told apart from 'the packet did not help'. Quoting this row without its denominator would be a misreport.

| metric | native | compiled | delta (pp) | n |
| --- | --- | --- | --- | --- |
| macro all-pass | 62.5% | 50.0% | -12.5 | 8 |
| micro mean-criteria | 93.1% | 88.1% | -4.9 | 8 |

## Hardest documents

Ranked by the sum of the two arms’ micro scores, hardest first; at most 15 rows. `NOT_RUN` means that arm has no cell for the task, which is never the same as a zero. `scanned?` is true when the compiled arm refused the document as `scanned_no_text_layer` — a zero that stays in the denominator.

| task | domain | pages | criteria | scanned? | native pass | compiled pass | native all-pass | compiled all-pass | failure |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `1b234b39` | STEM/Research | 73 | 7 | True | 7/7 | 0/7 | True | False | scanned_no_text_layer |
| `ce1c33a2` | Insurance | 8 | 12 | True | 12/12 | 0/12 | True | False | scanned_no_text_layer |
| `48e0e149` | Real Estate | 88 | 4 | False | 3/4 | 2/4 | False | False | - |
| `fc62a5ad` | STEM/Research | 12 | 18 | False | 14/18 | 15/18 | False | False | - |
| `e92d3194` | Healthcare | 8 | 5 | False | 5/5 | 4/5 | True | False | - |
| `88fb71c4` | Legal | 23 | 12 | False | 11/12 | 11/12 | False | False | - |
| `0104fdc6` | Insurance | 36 | 8 | False | 8/8 | 8/8 | True | True | - |
| `b8ca9504` | Legal | 18 | 7 | False | 7/7 | 7/7 | True | True | - |
| `4d221f2f` | Construction | 16 | 17 | False | 17/17 | 17/17 | True | True | - |
| `83864e26` | STEM/Research | 16 | 10 | False | 10/10 | 10/10 | True | True | - |

## Compiled arm: what Product Core actually produced

Per-document compile facts for every cell that had a packet. The full per-document rows are in the cell ledger under `evidence/`; this is their spread. `REGION_CITATION_UNAVAILABLE` counts the documents where at least one unit could not be cited to a region -- the defect that made the superseded v1 adapter degenerate.

- documents with a packet: **8**
- adapter versions in this run: `{'gdp-pdf-compiled-context/2-geometry': 8}`
- candidate lifecycle: `{'candidate': 5, 'review_required': 3}`
- documents with an unresolvable citation: **0**

| quantity | reported for | min | median | max | total |
| --- | --- | --- | --- | --- | --- |
| regions | 8 | 134 | 460 | 1,426 | 4,921 |
| claims | 8 | 0 | 136 | 529 | 1,482 |
| entities | 8 | 0 | 34 | 724 | 1,096 |
| relations | 8 | 0 | 93 | 2,012 | 2,610 |

## Compiled packet size against PDF pages

Characters and bytes are measured from the packet files. **Token counts are NOT_MEASURED**: this lane has no tokenizer for the surface’s model, and an estimate would be an invented number. The measured token totals are the per-arm figures in the cost table, which cover the whole conversation rather than the packet alone.

| metric | value |
| --- | --- |
| packets attached to a scored cell (n) | 8 |
| packet chars, min | 101,026 |
| packet chars, median | 390,731 |
| packet chars, max | 399,995 |
| packet chars per PDF page, median | 14,629 |
| packets truncated by the stated budget rule | 4 of 8 |
| packet tokens | NOT_RUN |

## Case candidates (the two arms disagree)

**5** paired tasks scored differently. Criterion numbers are 1-based indices into that task’s rubric in the out-of-repo catalog; rubric text and answer text stay in the restricted run store and are not reproduced here. A human opens the run-store record and pulls the excerpts.

| task | domain | pages | native | compiled | criteria gained by compiled | criteria lost by compiled | adapter |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `ce1c33a2` | Insurance | 8 | 12/12 | 0/12 | NOT_RUN | NOT_RUN | scanned_no_text_layer |
| `1b234b39` | STEM/Research | 73 | 7/7 | 0/7 | NOT_RUN | NOT_RUN | scanned_no_text_layer |
| `48e0e149` | Real Estate | 88 | 3/4 | 2/4 | NOT_RUN | NOT_RUN | - |
| `e92d3194` | Healthcare | 8 | 5/5 | 4/5 | NOT_RUN | NOT_RUN | - |
| `fc62a5ad` | STEM/Research | 12 | 14/18 | 15/18 | NOT_RUN | NOT_RUN | - |

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
