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

The 2026-09-06 complementarity study records same-page comparisons against a
PaddleOCR-VL baseline. The committed full-compare summary contains a settled
1,651-page PaddleOCR-VL result but has null score fields for OvisOCR2. The
olmOCR-Bench and ParseBench score artifact cited in the earlier draft is not
committed. This decision therefore does not adopt cross-benchmark rankings or
an industry-leading claim. It uses only the committed overlapping-page matrices
below to describe a possible second reader, and keeps execution disabled.

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

There is also a measured floor for each named pair. Paddle and Ovis are both
wrong on 11.4% of text pages, 22.9% of table pages, 35.7% of reading-order
pages and 44.7% of formula pages. For the selected Paddle and Flash formula
pair, the both-wrong rate is 42.8%. These are campaign-specific limits on those
pairs, not a ceiling for every possible two-model arrangement. A second read is
a recovery step and never a guarantee.

## Decision

### 1. The second reader is named in the decision, from measurement

`RouteDecision` gains two additive optional fields, `cross_check_route` and
`cross_check_element`. The engine fills them in one place —
`_require_ready_route`, which every non-terminal decision already passes
through — by asking the page which element dominates it and asking the rescue
table who recovers that element for the route that was chosen.

`require_cross_check` keeps its meaning and its type. Both new fields default to
`None`, so a decision serialized before this record still validates. They are
in-process advisory fields and are deliberately excluded from serialized DTOs;
no worker or persisted decision may assume they survived a process boundary.

### 2. No measurement, no second read

`select_cross_check_peer` returns `None` when the baseline was never measured,
when no measured peer has a route, when every measured peer is unservable, or
when the measured rescue rate is zero. A measured baseline without a servable
peer keeps `require_cross_check` and gains the internal reason code
`cross_check_peer_unavailable`. An unmeasured baseline keeps its existing
cross-check policy and does not claim this measured-peer failure.

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
  and `upstream_revision` was null. This corrects identity; it does not establish
  a production quality ranking.

Every revision comes from `research/model_arena_20260903/model_registry.json`
(sha256 `292fd6f6…`), resolved read-only from the Hugging Face and GitHub APIs
on 2026-09-05, and each entry carries a `revision_source` block naming it.

### 6. Chart extraction is recorded here and not routed on

Chart routing is deliberately **not** wired into this selector. ParseBench is a
different benchmark from the one the committed rescue table was built on, and
the relevant score artifact is absent from this release. Routing on chart
probability needs its own same-condition complementarity measurement first.
`PageMetrics.chart_probability` exists and is untouched by this record.

## What this does not change

Nothing is enabled. `rollout.traffic_percent` is 0 for every entry added or
touched, `recipes.parse_balanced_v1` keeps its `activation_blocker`, and no
licence field is altered. `ready_routes` is still computed per request from the
`model_registry` table, and `_binding` still refuses a row without an endpoint,
a revision, a runtime image digest, a model id and an adapter version —
`validate_registry_binding` additionally refuses one with no benchmark report.

The selected peer remains unavailable unless an exact registry binding and a
tenant opt-in flag both exist. Both new flags default off. A production caller
does not dispatch the peer yet, so this remains decision logic in shadow.

## Activation — what is not an agent's call

This record can be accepted and the decision code can ship without the following
activation evidence. Delegated founder authority does not supply a licence,
served-image, production-registry, or same-condition benchmark receipt.

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

Tenant flags `ovis_vl_second_reader` and `infinity_flash_second_reader` default
to off. The production caller does not dispatch the selected second reader, and
there is no execution receipt. Keep both flags off until the serving revision
and digest match the registry and the pair passes a same-condition shadow run.

### Order, when the founder chooses to proceed

    licence review  →  serve one model, pin its digest  →  registry row at
    canary 0  →  shadow the pair on a held-out corpus  →  compare against the
    single-reader baseline  →  canary  →  rollout

This is the replacement ladder from `CLAUDE.md`, unchanged. The legacy
single-reader path stays authoritative until a benchmark says the pair is not
worse.

## Consequences

- A routing *decision* can now name the selected second reader and the element
  that chose it. This does not attest that a second read ran: production has no
  dispatcher or execution receipt for it yet.
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
| `research/model_arena_20260903/model_registry.json` | `292fd6f6176b017b0288dd6634d77f2be58c9c118d9a01bd3c91799a1570aa48` |
| `research/model_arena_20260903/reports/full_compare_20260905/comparison_omnidoc_full.json` | `80c5ae44bc27cbe7de98c9a1830a66a399a2dbb81c6a5176270977497cf979ad` |

The overlap measurements come from the two committed complementarity matrices.
The full-compare summary is included to show its incomplete score fields rather
than to claim a full-benchmark OvisOCR2 win. No competitor's published row is
treated as a same-condition result.

`tau = 0.05` is the study's discrete threshold for calling a page wrong. **It is
not calibrated against a TAVONEL corpus.** Neither is any rate in the table a
statement about a customer's documents: it is a frozen record of one campaign on
one public benchmark, and §Activation item 4 exists because of that.
