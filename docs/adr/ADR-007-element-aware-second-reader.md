# ADR-007: The Second Reader Is Chosen Per Element, From Measurement

- Status: Proposed
- Date: 2026-09-23
- Owners: Platform, Research
- Founder decisions required before any part of this ships: §Activation

## Context

`RouteDecision.require_cross_check` has been a boolean since the router was
written. It says a page deserves a second read and says nothing about who
performs it. In practice that left the choice to whatever the caller had
available, which on this deployment is one model, so the "cross-check" was a
second opinion from the same opinion.

The Model Arena of 2026-09-05 ran thirteen open-weights readers over the whole
of OmniDocBench — 1,651 pages each, scored by the benchmark's own end2end
quick_match evaluator. The leaderboard it produced answers "who is best". That
turns out to be the wrong question to build a router on, for two reasons the
campaign measured rather than argued.

**The ranking is not stable across benchmarks.** On OmniDocBench text edit
distance, `ovisocr2` leads at 0.0290 and `paddleocr_vl_1_6` follows at 0.0426.
On olmOCR-Bench — 1,403 documents, 8,413 checks, same campaign — `mineru_vlm`
leads at 0.806, `olmocr2` is second at 0.799, `paddleocr_vl_1_6` is third at
0.781, and `ovisocr2` is **ninth at 0.679**. The model that leads one benchmark
sits in the bottom third of the other. On ParseBench chart extraction,
`mineru_vlm` scores 0.605 while nine of the twelve rows sit near 0.01: chart
reading is effectively a capability one model has and the others do not.

**Where a reader fails is more useful than how often.** The 2026-09-06
complementarity study re-used the per-page edit distances the campaign had
already produced — no new inference, no GPU spend — and asked a different
question: given the reader that ran, which other reader is right on the pages it
got wrong? With "wrong" as `edit > 0.05`:

| element | baseline | best rescuer | rescue rate | denominator |
| --- | --- | --- | --- | --- |
| text | paddleocr_vl_1_6 | ovisocr2 | 44.0% | 316 wrong of 1,557 scored |
| formula | paddleocr_vl_1_6 | infinity_parser2_flash | 15.2% | 158 wrong of 313 scored |
| table | paddleocr_vl_1_6 | ovisocr2 | 22.2% | 135 wrong of 458 scored |
| reading order | paddleocr_vl_1_6 | ovisocr2 | 18.9% | 720 wrong of 1,638 scored |

The formula row is the one that makes the table worth having: the best partner
for formulas is **not** the model that is best everywhere else. A router with
one partner for everything discards that.

Reversing the baseline shows the pairing is genuinely two-sided rather than a
ranking in disguise. Where `ovisocr2` is wrong, `paddleocr_vl_1_6` recovers
19.8% of table pages and 14.6% of formula pages — but only 12.8% of text pages,
which is worse than `glm_ocr` and `opus5` at 16.3%.

There is also a floor. Both readers are wrong together on 11.4% of text pages,
22.9% of table pages, 35.7% of reading-order pages and 44.7% of formula pages.
That is the ceiling of any two-model arrangement, and it is why a second read is
a recovery step and never a guarantee.

## Decision

### 1. The second reader is named in the decision, from measurement

`RouteDecision` gains two additive optional fields, `cross_check_route` and
`cross_check_element`. The engine fills them in one place —
`_require_ready_route`, which every non-terminal decision already passes
through — by asking the page which element dominates it and asking the rescue
table who recovers that element for the route that was chosen.

`require_cross_check` keeps its meaning and its type. Both new fields default to
`None`, so a decision serialized before this record still validates.

### 2. No measurement, no second read

`select_cross_check_peer` returns `None` when the baseline was never measured,
when no measured peer has a route, when every measured peer is unservable, or
when the measured rescue rate is zero. The decision then keeps
`require_cross_check` and gains the reason code `cross_check_peer_unavailable`.

The caller must treat that as *the check is unavailable*, not as *pick
something*. A second reader chosen without evidence is a guess wearing the word
"check", and it would be exactly the silent fallback `CLAUDE.md` forbids. There
is deliberately no default partner.

### 3. The element comes from measured page structure, never from a score

`dominant_element` compares `PageMetrics.formula_density` against
`PageMetrics.table_density` — two measured densities, against each other. No
absolute cut-off is involved, so nothing here depends on a threshold this
repository has not calibrated. A page with neither is a text page; a tie goes to
the table, which has the larger both-wrong floor of the two.

This is not the blind quality score the campaign published as *not supported*.
That hypothesis was a single scalar standing in for page difficulty. This is one
measured density compared with another to decide which of four measured tables
to read.

### 4. Reading order is measured but not routed on

The rescue table carries reading order and `dominant_element` never returns it.
Reading order is a property of a whole page rather than a region of it, and the
study scored it over a different page set (1,638 against 1,557 for text). A
caller that wants it must ask for it by name.

### 5. The registry says what the campaign found, including where it was wrong

- `ovisocr2` is added. It led OmniDocBench text and reading order and was
  **absent from `models.yaml` entirely**, so no route could ever have named it.
- `mineru_vlm` is added as its own entry. It is not a variant of the existing
  `mineru` row: `opendatalab/MinerU2.5-Pro-2605-1.2B` is a different repository
  from `opendatalab/PDF-Extract-Kit-1.0`.
- The existing `mineru` row is pinned to the pipeline it always was. It had
  `engine: mineru_pipeline` while `upstream_id` named the umbrella repository
  and `upstream_revision` was null. **The registry carried the variant that
  lost** — olmOCR-Bench 0.713 against `mineru_vlm`'s 0.806, and ParseBench chart
  0.008 against 0.605.

Every revision comes from `research/model_arena_20260903/model_registry.json`
(sha256 `83152ef9…`), resolved read-only from the Hugging Face and GitHub APIs
on 2026-09-05, and each entry carries a `revision_source` block naming it.

### 6. Chart extraction is recorded here and not routed on

`mineru_vlm`'s ParseBench chart result is the most lopsided finding of the
campaign and it is deliberately **not** wired into the router. ParseBench is a
different benchmark from the one the rescue table was built on, and mixing them
in one selector would compare across conditions. Routing on it needs its own
complementarity measurement first. `PageMetrics.chart_probability` exists and is
untouched by this record.

## What this does not change

Nothing is enabled. `rollout.traffic_percent` is 0 for every entry added or
touched, `recipes.parse_balanced_v1` keeps its `activation_blocker`, and no
licence field is altered. `ready_routes` is still computed per request from the
`model_registry` table, and `_binding` still refuses a row without an endpoint,
a revision, a runtime image digest, a model id and an adapter version —
`validate_registry_binding` additionally refuses one with no benchmark report.

On the current deployment `ready_routes` is `{native}`, so every decision this
record touches resolves to `cross_check_peer_unavailable`. That is the intended
state until activation.

No new feature flag is introduced. The registry row plus its `canary_percent`
already gate this, and a second gate with no measured need is a second thing to
get wrong.

## Activation — what is not an agent's call

This record can be accepted and the code can ship without any of the following.
None of it may be done by an implementation session.

1. **Licence review** for `ovisocr2`, `mineru_vlm` and `paddleocr_vl_1_6` —
   weights, dataset and runtime are three separate licences and all three sit at
   `review_required`. `unlicensed component in production` is a stop-the-line
   item.
2. **GPU serving**, which is spend. Each model needs a served endpoint before an
   immutable image digest exists to pin; the published PaddleOCR-VL image
   carries a floating `:latest-nvidia-gpu` tag and the other two were run from
   weights with no image at all.
3. **The `model_registry` rows**, which are production database writes.
4. **A no-regression benchmark of the pair**, because the rescue table is a
   ceiling measured by an oracle that always picks the better page. A real
   router does not know which one is better; it has to decide. What this table
   bounds is how much there is to win, not how much a shipped router wins.

### Order, when the founder chooses to proceed

    licence review  →  serve one model, pin its digest  →  registry row at
    canary 0  →  shadow the pair on a held-out corpus  →  compare against the
    single-reader baseline  →  canary  →  rollout

This is the replacement ladder from `CLAUDE.md`, unchanged. The legacy
single-reader path stays authoritative until a benchmark says the pair is not
worse.

## Consequences

- A cross-check that runs now says which reader ran it and which element chose
  them, in the decision and in the reason codes. It was previously unattributed.
- The rescue numbers live in one generated module bound to two artifact digests.
  `test_complementarity.py` re-reads both files and fails if a digit drifts, so
  the table cannot quietly stop matching the campaign.
- Two routes exist that cannot be served. That is visible and fail-closed rather
  than absent and silently unroutable, which is the state `ovisocr2` was in.
- The `mineru` correction means anything that read that row was reading an
  unpinned umbrella repository. Nothing in production consumed it —
  `model_registry` has no rows — so the correction costs nothing today.

## Evidence

| Artifact | sha256 |
| --- | --- |
| `research/model_arena_20260903/reports/complementarity_20260906/complementarity_rescue_matrix.json` | `5528b7ec9afde1fd450bd82563360cf884d5c6d85998232171bc97dfdac3d174` |
| `research/model_arena_20260903/reports/complementarity_20260906/complementarity_oracle_matrix.json` | `2efa03bc44824542c310a8fc10d0935b51317780240be4e4dc9717a0745bfaaf` |
| `research/model_arena_20260903/model_registry.json` | `83152ef92e2792a7ab3b2ef25fa9774115adfea2ebcd45363f7207764f8ee693` |

The OmniDocBench and olmOCR-Bench figures quoted in Context come from
`reports/full_compare_20260905/comparison_omnidoc_full.json` and
`reports/full_compare_20260905/LEADERBOARD_QUALITY_SPEED.json`, which are the
campaign's own runs of open-weights models on public benchmarks. They are ours,
not quoted leaderboard rows. No competitor's published row appears here.

`tau = 0.05` is the study's discrete threshold for calling a page wrong. **It is
not calibrated against a TAVONEL corpus.** Neither is any rate in the table a
statement about a customer's documents: it is a frozen record of one campaign on
one public benchmark, and §Activation item 4 exists because of that.
