# Oracle Ceiling Report — Phase A, WP-R0 / WP-R1

**Lane C1 `router-oracle` · 2026-09-08 · branch `agent/router-oracle` · base `d9db24c`**

> **This is NOT a public benchmark result.** It is an internal diagnostic on
> outputs that were already produced and already scored by the
> `TAVONEL-MODEL-ARENA-PUBLIC-20260903-V1` campaign. No number here may be
> published, quoted to a customer, or compared with a vendor leaderboard.
>
> **This is NOT a champion promotion.** No model is promoted, no route is
> changed, no threshold is calibrated. The Oracle reads hidden ground truth;
> blueprint §39 calls that arm `ORACLE_DIAGNOSTIC` and it is never eligible
> for a primary claim.
>
> **Cost of this lane: $0.** No GPU, no pod, no paid API, no re-inference.
> Everything below is arithmetic over stored files.

---

## 1. What was done

| Work package | Output | sha256 |
| --- | --- | --- |
| WP-R0 bind | `ARENA_BIND.json` | `2043db650e6f5d0018532b3751de202ed718745b4c4435737563e228b5b52d76` |
| Loss vector freeze | `LOSS_VECTOR_FREEZE.json` | `3efe23857653e95eaa6663dc83441c4ddee21f1fb90f168601ece2e761640d62` |
| WP-R1 Oracle | `ORACLE_RESULTS.json` | `b16799b15fd02acc45c5886d5b9085e87863d74b4ac8c9706c7e77dc1e67ea42` |
| WP-R1 tables | `ORACLE_TABLES.md` | `5512a2de8ddbb8aa7c958402d5b8a5ff934448d357803bddc4aee4dab4aa8b4c` |

Source modules: `bind.py`, `loss_vector.py`, `reconciler.py`, `oracle.py`,
`tests/test_oracle_math.py`. `ruff` and `mypy --strict` clean; 13 tests pass.

The arena tree (`research/model_arena_20260903/` in the MAIN checkout) was
opened read-only. `git status` there is unchanged.

---

## 2. Bind (§83 steps 1-2, WP-R0)

13 registry models. **1 FOUNDER_EXCLUDED** (`infinity_parser2_pro`, receipt
`FOUNDER_EXCLUDE_INFINITY_2026-09-04.md`, H100x2 burn under soft-cap
pressure) — it has no scored artifact on any benchmark and is absent from
every table below. **12 models in scope.**

Per-unit artifacts actually available:

| Benchmark | Models with per-unit rows | Unit | N |
| --- | ---: | --- | ---: |
| OmniDocBench | 10 of 12 | page | 1,651 scored / 1,641 with a scoreable element |
| olmOCR-Bench | 12 of 12 | PDF page | 1,403 pages / 8,413 tests |
| ParseBench | 12 of 12 | example | 495-568 per facet |

**Incomplete, recorded not dropped (§37):**

- `olmocr2` and `unlimited_ocr` have an `omnidoc_raw/` directory but **no
  per-page edit files** — only an aggregate `metric_result.json`. They are
  excluded from the OmniDoc surface and named in
  `models_excluded_from_surface`.
- `deepseek_ocr2` and `infinity_parser2_flash` each miss 4 ParseBench table
  examples (intersection 495, union 503).
- `deepseek_ocr2` carries 21 olmOCR `candidate_errors`, `unlimited_ocr` 4.
- ParseBench **layout is excluded entirely** for every model: the freezes hold
  markdown only and prepare emitted empty layout predictions
  (`elements_available=false`). Scoring it would score the harness.

**Runtime identity is weaker than the blueprint wants.** `container_digest` is
`null` for **all 13 models** — lane F never resolved an immutable image digest.
Identity is pinned only by `identity_source` (`runtimes/<model>/runtime.json`)
plus `inference_config_sha256`. §95 asks for "runtime images"; this campaign
cannot supply them. Frozen manifests also carry `model_revision: null` and
`runtime_image_digest: null`.

**Cross-check that the bind is reading the right files.** Recomputing each
model's OmniDoc mean text-block edit from the per-page rows reproduces the
published leaderboard to 4 decimals for **9 of 10** models. The single
exception is `glm_ocr`: per-page rows give **0.0846**, the board row quotes
**0.0444**. `ANOMALY_NOTES.md` explains it — the 0.0444 REF row is a
SUCCESS-only rescore over a 1,599-page filtered GT, and only its aggregate was
installed; the per-page rows in `omnidoc_raw/glm_ocr/` are still the full-1,651
scoring. **This analysis uses the full-corpus per-page rows**, because they are
the only ones aligned to the same page keys as the other nine models. That
makes `glm_ocr` look worse here than on the board, and it makes the Oracle
*more* conservative, not less.

---

## 3. Loss vector freeze (§31, §33)

Frozen **before** `oracle.py` was first run. Weights are structural — read off
the taxonomy, not off any observed score.

| Class | §31 name | Weight | Signal in the stored artifacts |
| --- | --- | ---: | --- |
| L0 | File/Page | hard override | frozen-manifest FAILED; unit absent from a score file. **No signal for `duplicate page`.** |
| L1 | Text | 0.40 | OmniDoc text_block edit · olmOCR `present`/`absent`/`baseline` · ParseBench text_content |
| L2 | Critical Token | 0.00 | **NO SIGNAL** |
| L3 | Structure | 0.15 | OmniDoc reading_order edit · olmOCR `order` · ParseBench text_formatting. **No signal for heading / paragraph / list.** |
| L4 | Table | 0.30 | OmniDoc table edit + per-table TEDS · olmOCR `table` · ParseBench TEDS/GriTS. **No signal for merged cell / continuation / footnote.** |
| L5 | Formula | 0.15 | OmniDoc display_formula edit · olmOCR `math` |
| L6 | Visual | 0.00 | **PARTIAL** — ParseBench `chart` only. No signal for figure / diagram / caption / labels / relationships. |
| L7 | Evidence/Provenance | 0.00 | **NO SIGNAL** |
| L8 | Temporal/Identity | 0.00 | **NO SIGNAL** |

A weight of 0.00 here means *unmeasurable from stored outputs*. It never means
unimportant, and no row was filled with an invented proxy.

Two consequences that bind everything downstream:

1. **SCLR (§32) is not computable in Phase A.** It needs L2 critical-token
   opportunities and an accept/refuse decision. The stored artifacts have
   neither. The blueprint's candidate headline endpoint cannot be measured
   until a critical-token detector exists (WP-R7).
2. **"IRR" below is an IRR *proxy*** over L1/L3/L4/L5 only. It is not the §33
   IRR, which spans L0-L8.

---

## 4. Permitted plans (§35 — no Frankenstein)

Frozen before scoring:

- `SINGLE:<model>` — one per in-scope model with per-unit rows.
- `ALWAYS_ALL_RECONCILED` — run every model, elect one output with
  **FROZEN_RECONCILER_V1** (see `reconciler.py`, written and committed before
  any score was read): normalize each candidate to a markdown-stripped token
  set, score each candidate by mean Jaccard agreement with the others, take
  the argmax, break ties by **lexicographic model key** (deliberately not by
  quality rank — ordering by rank would leak evaluation truth into a rule that
  must be blind). No candidate → `UNRESOLVED`, which scores as full loss, never
  a silent fallback.
- `PAGE_CLASS_CHAMPION` — best fixed single per page class, using the
  benchmark's own labels (OmniDoc `page_attribute` data_source|language|layout;
  olmOCR `source_jsonl`; ParseBench `tags`). Chosen **in-sample**, so it is an
  optimistic ceiling on fixed routing, not an achievable policy.
- `ORACLE_PERMITTED` — per unit, the best of the above. **One plan for the
  whole unit.** No region- or element-level splicing across models.

`ORACLE_ELEMENTWISE_FORBIDDEN` is also computed on OmniDoc — the §35
Frankenstein that takes each element from whichever model wins it. It is
labelled forbidden and reported only for contrast.

Both §37 cohorts are reported everywhere: **intersection** and
**missing-as-failure** (a missing unit scores 1.0).

---

## 5. Appendix A — result table (intersection cohort)

IRR proxy = `1 - mean loss`. Hard fail = unit loss > 0.05 (the same τ the
arena's own complementarity matrices use). CIs are cluster bootstraps over
document families, 2,000 replicates, seed
`TAVONEL-ROUTER-ORACLE-CLUSTER-BOOTSTRAP-2026-09-08`, best-fixed re-selected
inside each replicate.

### 5.1 OmniDocBench — 1,641 pages, 1,435 document-family clusters

| System | mean loss | IRR proxy | hard fail | unresolved N/A | 95% CI on loss | median s/page | GPU $/1k pages |
| --- | ---: | ---: | ---: | ---: | --- | ---: | ---: |
| `ORACLE_ELEMENTWISE_FORBIDDEN` *(not a plan)* | 0.0364 | 0.9636 | 303 | 0 | [0.0326, 0.0403] | — | — |
| **`ORACLE_PERMITTED`** | **0.0390** | **0.9610** | 330 | 0 | [0.0351, 0.0429] | — | — |
| `PAGE_CLASS_CHAMPION` (in-sample) | 0.0513 | 0.9487 | 456 | 0 | [0.0468, 0.0559] | per class | per class |
| **best fixed single — `ovisocr2`** | **0.0559** | **0.9441** | 460 | 0 | [0.0508, 0.0609] | 4.0 | 4.84 |
| `ALWAYS_ALL_RECONCILED` | 0.0646 | 0.9354 | 464 | **199** | [0.0586, 0.0705] | not measurable | not measurable |
| `SINGLE:paddleocr_vl_1_6` | 0.0685 | 0.9315 | 594 | 0 | [0.0631, 0.0738] | 4.0 | 4.92 |
| `SINGLE:hpd_parsing` | 0.0720 | 0.9280 | 561 | 0 | [0.0658, 0.0784] | 3.0 | 20.78 |
| `SINGLE:mineru_vlm` | 0.0762 | 0.9238 | 603 | 0 | [0.0696, 0.0828] | 5.0 | 1.00 |
| `SINGLE:infinity_parser2_flash` | 0.0819 | 0.9181 | 668 | 0 | [0.0756, 0.0884] | n/a | 0.80 |
| `SINGLE:monkeyocrv2_b` | 0.0889 | 0.9111 | 657 | 0 | [0.0818, 0.0961] | 6.0 | 5.60 |
| `SINGLE:deepseek_ocr2` | 0.0930 | 0.9070 | 703 | 0 | [0.0857, 0.1009] | 27.0 | 11.35 |
| `SINGLE:mineru_pipeline` | 0.1274 | 0.8726 | 847 | 0 | [0.1183, 0.1358] | 4.0 | 4.95 |
| `SINGLE:opus5_subscription` | 0.1649 | 0.8351 | 850 | 0 | [0.1533, 0.1770] | n/a | UNMEASURED |
| `SINGLE:glm_ocr` | 0.1717 | 0.8283 | 901 | 0 | [0.1592, 0.1841] | 5.0 | 8.57 |

**Oracle headroom = 0.0169 absolute loss over the best fixed single
(`ovisocr2` 0.0559 → Oracle 0.0390), i.e. 30.3 % of the best fixed single's
loss removed. Cluster-bootstrap 95 % CI [0.0140, 0.0201]. Denominator: 1,641
pages in 1,435 document-family clusters.**

The missing-as-failure cohort is identical for the single plans (all ten models
score every unit of this surface). It differs only for
`ALWAYS_ALL_RECONCILED`, which rises to 0.1780 because its 199 unresolved
units become full losses.

### 5.2 olmOCR-Bench — 1,403 PDF pages / 8,413 tests, 1,367 clusters

| System | mean loss | IRR proxy | hard fail | 95% CI |
| --- | ---: | ---: | ---: | --- |
| **`ORACLE_PERMITTED`** | **0.0615** | **0.9385** | 299 | [0.0540, 0.0699] |
| `PAGE_CLASS_CHAMPION` (in-sample) | 0.1128 | 0.8872 | 476 | [0.1018, 0.1237] |
| **best fixed single — `mineru_vlm`** | **0.1381** | **0.8619** | 550 | [0.1256, 0.1504] |
| `SINGLE:olmocr2` | 0.1396 | 0.8604 | 570 | [0.1279, 0.1517] |
| `SINGLE:paddleocr_vl_1_6` | 0.1468 | 0.8532 | 584 | [0.1330, 0.1608] |
| `ALWAYS_ALL_RECONCILED` | 0.2077 | 0.7923 | 706 | [0.1935, 0.2217] |
| `SINGLE:ovisocr2` | 0.2462 | 0.7538 | 771 | [0.2308, 0.2612] |
| `SINGLE:glm_ocr` *(worst)* | 0.3627 | 0.6373 | 1048 | [0.3461, 0.3805] |

**Oracle headroom = 0.0766 absolute (55.5 % relative), 95 % CI [0.0678,
0.0823], over 1,403 pages in 1,367 clusters.**

The unit is the **page**, not the test: picking a different model for the
`order` test and the `table` test of the same page is region splicing, which
§35 forbids.

Per page class (headroom, intersection cohort): `table_tests` 0.0761 ·
`old_scans` 0.0989 · `old_scans_math` 0.0773 · `long_tiny_text` 0.0547 ·
`multi_column` 0.0530 · `arxiv_math` 0.0489 · `headers_footers` 0.0152. The
class champion is a *different model in six of seven classes*
(`opus5_subscription`, `paddleocr_vl_1_6`, `olmocr2`, `mineru_vlm`,
`unlimited_ocr`) — no single model owns the corpus.

### 5.3 ParseBench (per facet; layout excluded as N/A)

| Facet | N | best fixed single | loss | Oracle loss | headroom | 95% CI | clusters |
| --- | ---: | --- | ---: | ---: | ---: | --- | ---: |
| table (1−TEDS) | 495 | `opus5_subscription` | 0.1834 | 0.0875 | 0.0958 (52.3 %) | [0.0820, 0.1086] | 93 |
| chart | 568 | `mineru_vlm` | 0.3952 | 0.3383 | 0.0569 (14.4 %) | [0.0351, 0.0867] | 99 |
| text_content | 506 | `opus5_subscription` | 0.0886 | 0.0708 | 0.0178 (20.1 %) | [0.0119, 0.0252] | 506 |
| text_formatting | 476 | `opus5_subscription` | 0.2579 | 0.2163 | 0.0416 (16.1 %) | [0.0288, 0.0554] | 476 |

`opus5_subscription` wins three of four ParseBench facets, but it is an
external subscription API: data egress, unmeasured cost, unmeasured latency,
provider policy. §8 of the blueprint already rules it out as a default customer
path. Its wins are a reason to keep an adjudicator route, not to route
customers through it.

---

## 6. Appendix B — complementarity with CIs

Rescue = `P(peer loss ≤ 0.05 | primary loss > 0.05)` on the OmniDoc composite,
cluster-bootstrapped (500 replicates, document-family clusters). Full matrix in
`ORACLE_TABLES.md`; the two rows §9 of the blueprint cares about:

| Primary | Peer | n primary wrong | rescue | 95% CI | joint fail |
| --- | --- | ---: | ---: | --- | ---: |
| `paddleocr_vl_1_6` | `ovisocr2` | 594 | 30.8 % | [27.1 %, 34.1 %] | 69.2 % |
| `paddleocr_vl_1_6` | `hpd_parsing` | 594 | 24.7 % | [21.1 %, 28.4 %] | 75.3 % |
| `paddleocr_vl_1_6` | `mineru_vlm` | 594 | 20.4 % | [17.0 %, 23.6 %] | 79.6 % |
| `ovisocr2` | `paddleocr_vl_1_6` | 460 | 10.7 % | [8.0 %, 13.8 %] | 89.3 % |
| `ovisocr2` | `hpd_parsing` | 460 | 10.7 % | [8.1 %, 13.6 %] | 89.3 % |
| `ovisocr2` | `mineru_vlm` | 460 | 10.2 % | [7.2 %, 13.2 %] | 89.8 % |

These are **composite-loss** rescue rates, so they are lower than the
text-element-only rates the arena already published
(`complementarity_rescue_matrix.json`: paddle→ovis text rescue 44.0 %). The
arena's own numbers are quoted, not recomputed; this table is the composite
view with the CIs §Appendix B asks for.

The asymmetry survives with CIs: when Paddle is wrong, Ovis saves the page
about three times as often as the reverse. **Joint failure is the dominant
mode everywhere** — 69-90 % of the time the peer is also wrong. That is the
single most important number for Phase B: a disagreement-only escalation
trigger inherits a large blind spot no matter which peer is chosen.

---

## 7. §90 capture ratio

`capture = (best_fixed_loss − plan_loss) / (best_fixed_loss − oracle_loss)`

| Surface | ALWAYS_ALL_RECONCILED | PAGE_CLASS_CHAMPION | TAVONEL router |
| --- | ---: | ---: | --- |
| omnidoc | **−0.513** | 0.269 | Phase B |
| olmocr | **−0.910** | 0.330 | Phase B |
| parsebench:table | −0.295 | 0.000 | Phase B |
| parsebench:chart | −10.489 | 0.184 | Phase B |
| parsebench:text_content | −0.390 | 0.350 | Phase B |
| parsebench:text_formatting | −9.904 | 0.001 | Phase B |

Two findings, both negative, both important:

1. **The frozen GT-blind reconciler captures none of the headroom — it is
   worse than the best fixed single on every surface.** Free-text agreement
   elects the *typical* output, not the *correct* one, and the typical output
   is dragged toward whatever the weak models agree on. On ParseBench chart it
   is catastrophic (−10.5) because eleven of twelve models emit essentially no
   chart content, so the medoid is always one of the eleven. `ALWAYS_ALL` is
   also the most expensive plan by construction: it runs everything. This is
   the §74 always-all baseline behaving exactly as the blueprint suspected —
   and it is evidence *for* an evidence-guided router, not for consensus.
2. **A fixed page-class champion captures only 27-35 % of the headroom** even
   when chosen in-sample on the same data it is scored on. The remaining
   two-thirds is genuinely per-page and cannot be reached by any static
   per-class assignment.

Caveat on the champion: OmniDoc has **85 page classes over 1,641 pages**
(mean 19 pages/class). That is heavy in-sample overfitting, and the true
out-of-sample capture is *below* 0.269.

---

## 8. Anti-Frankenstein cost (§35)

On OmniDoc, the forbidden element-wise ceiling is 0.0364 against the permitted
page-level Oracle's 0.0390. Splicing buys **0.0026**, about 15 % of the
0.0169 headroom.

**Page-level plan selection reaches roughly 85 % of even the cheating
ceiling.** The §35 constraint is cheap, and region-level routing (WP-R2's
`RegionExecutionPlan`) should be justified on a different basis than
OmniDoc-style aggregate loss — the region case has to be made on critical
tokens and tables, which this corpus cannot measure.

---

## 9. Go / no-go (§36, §89)

**GO — proceed to Phase B offline router replay.**

§36's decision rule is "Oracle gain small → reconsider router complexity;
Oracle gain large → offline replay". The gain is large and it is not a
rounding artifact:

- OmniDoc: 30.3 % of the best fixed single's loss, CI [0.0140, 0.0201], lower
  bound well clear of zero, over 1,435 document clusters.
- olmOCR: 55.5 %, CI [0.0678, 0.0823], over 1,367 clusters.
- ParseBench table: 52.3 %, CI [0.0820, 0.1086].
- Both §37 cohorts agree; the conclusion does not depend on how missing output
  is treated.
- Every surface has a different best fixed single (`ovisocr2`, `mineru_vlm`,
  `opus5_subscription`, `mineru_vlm`) and olmOCR has a different champion in
  six of seven page classes. There is no universal champion to route to.

**But the GO is narrow, and three conditions ride with it:**

1. **Nothing yet shows the headroom is *capturable*.** The only two GT-blind
   policies measured here capture 0 % (reconciler, negative) and ≤35 %
   (in-sample class champion). Phase B must beat those with runtime-visible
   features or the §89 gate fails at the next step, not this one.
2. **Region-level routing is not justified by this evidence** (§8 above).
   Build page-level first.
3. **The headline endpoint is still unmeasured.** SCLR is the metric the
   blueprint wants to lead with, and it is out of reach until L2 exists.

---

## 10. Limitations — what this cannot say

- **SCLR is not measured.** No L2 critical-token annotations, no accept/refuse
  decision in the stored outputs. Needs a detector (WP-R7) and an anchor set.
- **IRR is a proxy** over L1/L3/L4/L5. L0 duplicate-page, L2, L6 beyond chart,
  L7 and L8 have no signal at all in this campaign.
- **No provenance or temporal evidence.** L7/L8 need a different corpus.
- **Latency is ledger-only** and is per-job wall time from the queue database,
  not GPU kernel time, on a heterogeneous hardware mix. `opus5_subscription`
  and `infinity_parser2_flash` have no speed row at all.
- **Cost is campaign operational cost, not a serving cost.** The campaign
  `idle_overhead_ratio` is **0.66** — two thirds of billed GPU time was idle
  pods. `hpd_parsing` at $20.78/1k with 3 s/page is an idle artifact, not a
  model property. These are raw GPU provider costs and never sit beside a
  retail price. `opus5_subscription` cost is **UNMEASURED**, not zero.
- **No EVC (§42).** Queue, cold start, retry, speculative peer, verification
  and human review are not in these ledgers.
- **The page-class champion is in-sample** and the OmniDoc class count (85) is
  large relative to N. Treat 0.269 as an upper bound.
- **`ALWAYS_ALL` cost is not modelled**, only its quality. It is by
  construction the most expensive plan.
- **Runtime identity is incomplete**: no container digests anywhere.
- **The reconciler is whole-page token-set Jaccard.** It is order-blind and has
  no region granularity. A better GT-blind reconciler may exist; this one is
  frozen and this is its result.
- **This corpus is spent evidence.** Per PAPER2 §2, it cannot score a fresh
  confirmatory claim. Phase C needs a sealed fresh cohort.

---

## 11. §95 research receipt — what could be filled

| Field | Value |
| --- | --- |
| experiment_id | `TAVONEL-ROUTER-ORACLE-PHASE-A-2026-09-08` |
| git_sha | base `d9db24c1bda2079f0933123d1c54607b3b93197b`, branch `agent/router-oracle` |
| corpus_manifest_sha | `source_manifest.jsonl` sha256 in `ARENA_BIND.json` (5,132 rows: 1,651 omnidoc + 1,403 olmocr + 2,078 parsebench) |
| spent_manifest_sha | **MISSING** — no spent manifest exists for this campaign |
| router_policy_sha | **N/A** — no router ran (Phase A) |
| portfolio_sha | frozen-manifest sha256 per model, in `ARENA_BIND.json` |
| runtime images | **MISSING** — `container_digest` null for all 13 models |
| GPU identity | per-pod `gpu_type` in `cost/pod-*.json`; mixed 4090 / A6000 / L40S / H100 |
| preflight revision | **N/A** — no preflight in Phase A |
| loss detector revision | **N/A** — no detector exists yet (WP-R7) |
| verifier revision | **N/A** — no verifier exists yet (WP-R9) |
| evaluator revision | pinned in `ARENA_BIND.json` → `evaluators`: olmOCR `cfa88c1e…`, dataset rev `54a96a6f…`, dataset manifest sha256 recorded |
| random seed | `TAVONEL-ROUTER-ORACLE-CLUSTER-BOOTSTRAP-2026-09-08` (2,000 replicates); rescue `…:rescue` (500) |
| cost | **$0** this lane. Campaign ledger: $591.02 total, 54,445 successful pages |
| failures | per-model FAILED counts and per-benchmark availability in `ARENA_BIND.json`; exclusion tables in `ORACLE_RESULTS.json` |

Deviation from PAPER2 §10: that document specifies 10,000 bootstrap
replicates. This lane used **2,000** (500 for the pairwise rescue matrix) to
stay inside a pure-Python runtime with no numpy in the environment. 2,000 is
adequate for the 95 % interval reported and inadequate for tail p-values —
which is fine, because no p-value is reported here. Phase B should restore
10,000.

---

## 12. Reproduce

```
cd research/router_oracle_20260908
python bind.py          # refuses (exit 2) if a bound artifact has no digest source
python loss_vector.py
python oracle.py        # first run ~25 min: reads ~62k frozen canonical outputs
python -m pytest tests -q
```

`ARENA_ROOT` overrides the arena location. The reconciler caches its election
under `.cache/` keyed by benchmark and model set; delete it to recompute.
