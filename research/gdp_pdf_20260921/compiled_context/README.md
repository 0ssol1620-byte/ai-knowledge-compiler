# What a TAVONEL compiled-context packet is, in this experiment

This file states exactly what the `compiled_context_pdf` arm puts in front of the model, and
exactly how that artifact was produced. Nothing here is a claim about quality; the numbers live
in `../evidence/report.md` and only for the cells that actually ran.

## Two adapter versions. v2 is the one that runs.

| | v1 `gdp-pdf-compiled-context/1` (superseded) | v2 `gdp-pdf-compiled-context/2-geometry` |
| --- | --- | --- |
| extractor | `pypdf`, page text only | `pymupdf`, text blocks **with geometry** |
| region granularity | one region per **page** | one region per **text block** (paragraph) |
| `bbox1000` | `None` on every region | measured, normalised to 0..1000 of the page box |
| route | `standard`, 1,000 credits, 900,000 ms | the product's own: `high_assurance`, 10 credits, 52,000 ms |
| `REGION_CITATION_UNAVAILABLE` | **every unit, 88/88 documents** | **0 units, 0 of 89 documents** |
| candidate lifecycle | `review_required` on 88/88 | `candidate` on 65/89, `review_required` on 24/89 |
| packets | `compiled_context_local_v1/` (kept, not overwritten) | `compiled_context_local_v2/` |

v1 was a degenerate stand-in for the product: with no geometry, Product Core correctly refused
to issue a resolvable citation for any unit, so every world came back `review_required` for a
reason that had nothing to do with the document. A result from v1 is evidence about
page-anchored text chunks, not about TAVONEL.

### A v1 statement that was wrong, corrected here

The v1 edition of this file said that `semantics/claims.jsonl`, `entities.jsonl` and
`relations.jsonl` "all compile empty" on this corpus. **That was false.** Re-reading the v1
packets shows 84 of the 88 had non-empty claims (median 162 claims, 35 entities, 71 relations
per document); only 4 were empty. The real v1 defect was the missing geometry, not missing
semantics. The claim is corrected rather than deleted, because a wrong statement in an evidence
file is itself a finding.

## The packet (v2)

One UTF-8 markdown file per task, `<task_id>.md`, written to the out-of-repo context directory
(`D:\CodexData\gdp-pdf-cache\<revision>\compiled_context_local_v2\`). It carries, in this order:

1. a header naming the Product Core runtime, the compile `status` and `lifecycle`, the
   `world_state_id`, the `manifest_digest`, and the number of review reasons;
2. a `## Budget` block **when and only when** the packet was truncated, naming every section
   that lost lines and how many of how many it kept;
3. `rag/chunks.jsonl` rendered as **retrieval chunks with their page number, their `bbox1000`
   and their evidence ids**;
4. `semantics/claims.jsonl`, `semantics/entities.jsonl`, `semantics/relations.jsonl`;
5. an **evidence locator index**, `evidenceId -> pageNumber1 + bbox1000`, projected from the
   chunks' own `evidenceRefs` so a claim's `evidence_id` resolves to a page and a box;
6. the compiled **source note** (`obsidian/Sources/<source_id>.md`);
7. the `validation/report.json` verdict verbatim.

Nothing is added that Product Core did not emit. The renderer is `render_packet()` in
`../compile_context.py`.

The compiled retrieval view comes before the source note on purpose: a reader that opens only
the head of the file sees the compiled, locator-carrying layer rather than the raw document
text, which the chunks already contain with anchors attached.

Each packet is recorded in `index.json` next to it with `packet_sha256`, `packet_bytes`,
`packet_chars`, `packet_lines`, `packet_budget`, `world_state_id`, `manifest_digest`,
`receipt_output_sha256`, `status`, `lifecycle` and a full `compile_stats` block. The run's
evidence rows carry `context_sha256` and `context_manifest_digest`, so every scored cell binds
to the exact packet bytes it saw.

### The budget rule, stated

`PACKET_BUDGET_CHARS = 400_000`. A packet over that is truncated **head-kept, tail-dropped**,
section by section, in this fixed order until it fits:

    source-note > semantics/relations > evidence-locators > semantics/entities
      > semantics/claims > chunks

The header, the budget notice and the validation report are never truncated. The source note
goes first because its text is already in the chunks with anchors; relations go early because a
relation is recoverable from a claim's own `entityIds`. Every truncation is printed in the
packet's own `## Budget` block and recorded in `index.json`. **Nothing is ever dropped
silently.**

Measured on this corpus: **53 of the 89** compiled packets hit the budget. Of those, the source
note was dropped entirely in 46, relations in 42, entities in 34, the evidence-locator index in
35 and claims in 15; the chunks themselves were partially cut in 15 and fully kept in 38.
Packet size, measured: min 16,152 characters, median 399,387, max 399,995; 135 / 3,928 / 39,547
lines. A packet of that length does not fit in one `Read` call, so the model pages it — that is
a property of the arm, recorded, not hidden.

## How it is produced locally, on CPU, for born-digital documents — IMPLEMENTED

`../compile_context.py` is the adapter. What the live product sends Product Core per region is
a page number, paragraph text and a thousandths bounding box, and nothing else
(`buildProductCoreV2Request`, `gates-lanes/gdp/nextjs/lib/core-runtime-v2.ts`). The adapter
produces exactly that:

1. `pymupdf` `page.get_text("blocks")` per page; image blocks and whitespace-only blocks are
   dropped;
2. each block's rectangle is put through `page.rotation_matrix` **before** normalising. On a
   rotated page `get_text` reports unrotated coordinates while `page.rect` is the rotated box;
   skipping the transform put 1,518 of this corpus's 85,117 blocks (1.8%) outside their own
   page. 98 pages of the corpus are rotated;
3. the rectangle is normalised to 0..1000 of the page box, **floor on the near edges and ceil
   on the far edges**, so the integer box contains the measured rectangle rather than
   approximating it — and so it always has the positive area the `BBox1000` contract requires;
4. reading order is top-to-bottom then left-to-right in the page's *displayed* space, tie-broken
   by the PDF's own block index so the order is total and stable;
5. regions go into a `ProductCoreDocument` (`content_sha256` = the PDF's sha256) and a
   `ProductCoreCompileRequest` with the product's own route: `initial_compile`,
   `high_assurance`, `maxCostCredits=10`, `maxLatencyMs=52_000`
   (`WORKER_MAX_DURATION_MS - WORKER_SETTLEMENT_RESERVE_MS`, `lib/execution-budget.ts`),
   `privacyPolicy=approved_customer_data`, `previousActiveWorld=None`;
6. `ProductCoreCompiler(core_release_digest=...).compile(request, input_sha256=...)` from
   `D:\CodexProjects\ai-knowledge-compiler-p0p2-productization\packages\product-core`, imported
   read-only via `sys.path`. That worktree is not modified.

### One thing the adapter must do that the wire shape does not show

Product Core derives an evidence id from `(document version, page, bbox1000, span text)`, with
the box quantised to a 2-per-mille grid by `normalize_bbox1000` and the text folded by
`normalize_text_for_identity`. Two regions that agree after both foldings **are the same
evidence**, and sending both makes the Core fail closed with
`canonical knowledge object IDs must be unique` — which it did, on three separate documents of
this corpus, before the adapter deduplicated. The causes were single glyphs drawn twice within
two per-mille of the same spot, and blocks differing only in whitespace or punctuation.

The adapter therefore drops a block whose `(page, normalize_bbox1000(bbox), normalize_text_for_identity(text))`
key it has already seen on that page, and counts it as `blocks_dropped_duplicate_evidence`
(**138 blocks across the corpus**). It calls the Core's own two normalisers, so the key is the
evidence discriminator itself rather than an approximation of it. No locator is lost: the
dropped block resolves to the same page and the same box as the one that was kept.

### Properties that matter for an evidence lane

- **Pure CPU, no external call.** The compiler and its retrieval module import no HTTP client,
  no LLM, no embedding model, no database and no object store. Retrieval is a hand-rolled BM25
  over lexical tokens.
- **Deterministic.** `requested_at` is frozen to a constant, so the same PDF compiles to the
  same `world_state_id`, `manifest_digest`, `receipt.output_sha256` and packet sha256 on every
  run. `compile_context.py --demo` compiles one document twice and asserts it, and also asserts
  that the geometry is in range, that no unit is `REGION_CITATION_UNAVAILABLE`, that claims and
  entities are non-empty, and that the packet is inside its budget.
- **No geometry is invented.** Every bbox is a rounding of a coordinate PyMuPDF measured. A page
  box with no area yields `bbox1000=None` and the Core would flag that unit honestly; it did not
  occur on this corpus (`blocks_without_bbox = 0`).

## What v2 actually compiled, measured

Over the **89** documents that compiled (11 refused, see below):

| quantity | min | median | max | total |
| --- | --- | --- | --- | --- |
| regions sent to Product Core | 2 | 510 | 7,114 | 84,891 |
| knowledge units | 2 | 510 | 7,114 | 84,891 |
| claims | 0 | 162 | 1,538 | 24,649 |
| entities | 0 | 36 | 1,373 | 8,146 |
| relations | 0 | 68 | 5,035 | 20,623 |
| retrieval chunks | 1 | 117 | 1,044 | 16,880 |
| review reasons | 0 | 0 | 29 | 103 |
| `REGION_CITATION_UNAVAILABLE` | 0 | 0 | **0** | **0** |

Lifecycle: **65 `candidate`, 24 `review_required`**. Every one of the 103 review reasons is a
semantic finding, not a missing citation: 101 `CONTRADICTION_CANDIDATE` and 2
`SEMANTIC_CLAIMS_EMPTY`. Two documents produced zero claims and are the two
`SEMANTIC_CLAIMS_EMPTY` rows; they are reported, not hidden.

Geometry, corpus totals: 4,355 pages, 4,281 with text, 98 rotated, 2,465 whitespace-only blocks
dropped, 138 duplicate-evidence blocks dropped, 12 blocks clamped to the page box, 0 blocks
without a bbox.

### Coverage on this corpus

Of the 100 GDP.pdf tasks: **89 compiled**, **11 refused** as `scanned_no_text_layer`
(`MIN_CHARS_PER_PAGE = 50`). v1 refused 12; `pymupdf` recovers a usable text layer from one
document that `pypdf` did not, which is the whole difference. The 11 refusals are a real limit
of the local path, not a sampling choice — they are recorded as
`adapter_failure = "scanned_no_text_layer"`, scored zero, and kept in the denominator, exactly
as the sealed failure policy requires.

Refused task ids (first 8 characters): `1b234b39`, `3c825f54`, `6070d5f8`, `685a9467`,
`7b61426a`, `aff4bf86`, `ce1c33a2`, `cf79b3db`, `efb22c1d`, `f3537e1f`, `f8e8f09e`.

## Scanned pages: the parser stage — FORECAST ONLY, NOTHING WAS RUN

For the refused documents the text layer is absent, so the parser stage would have to run first.
The arena's best open parser is the one to use:

| item | value | source |
| --- | --- | --- |
| model | `ovisocr2` | arena settled leaderboard |
| OmniDocBench text edit | 0.028989 (lower is better) | `research/model_arena_20260903/reports/full_compare_20260905/comparison_omnidoc_full.json`, `settled_leaderboard[0]` |
| pages measured | 1,651 | same row (`page_count`) |
| elapsed | 4,829.476 s, sequential | same row (`elapsed_seconds`) |
| derived rate | **2.9252 s/page** | 4829.476 / 1651 |
| GPU class and listed rate | RTX 4090 @ **$0.74/hr** | arena pod cost ledger, e.g. `research/model_arena_20260903/cost/pod-05wls3jidad65t.json` (`listed_rate_usd_per_hour`) |
| derived GPU cost | **$0.000601/page = $0.601 per 1,000 pages** | 2.9252 s × $0.74/3600 s |

Applied to this corpus:

| scope | pages | GPU-hours | raw GPU cost |
| --- | --- | --- | --- |
| the whole 100-document corpus | 4,592 | 3.73 | **$2.76** |

Four limits on those numbers, all of which must travel with them:

- This is **raw GPU cost at a listed hourly rate**. It is not a price, and it never sits beside
  a retail price (project constitution, Evidence section).
- The 2.9252 s/page rate is measured on **OmniDocBench pages on the arena's GPU**, not on
  GDP.pdf pages on this host. It is a forecast by transfer, not a measurement of this corpus.
- It excludes provisioning, model load and idle time. The arena's own ledgers show those are
  material: `pod-05wls3jidad65t.json` records 420 s of model loading and 1,300.7 s of wasted GPU
  seconds ($0.2674) against $0.7507 of useful cost.
- **Nothing was run.** No parser was executed, no GPU was provisioned, no external resource was
  allocated for this lane. `ovisocr2`'s text-edit score is quoted from the arena's own
  same-condition run; it is not re-derived here and it is not a vendor leaderboard row.

## Reproducing the packets

```
.venv\Scripts\python.exe compile_context.py --demo            # determinism + geometry self-check
.venv\Scripts\python.exe compile_context.py \
    --catalog     D:\CodexData\gdp-pdf-cache\<revision>\task_catalog.json \
    --context-dir D:\CodexData\gdp-pdf-cache\<revision>\compiled_context_local_v2
```

Requires `pymupdf` in the venv (`pip install pymupdf`; 1.28.2 was used here). The dataset, the
PDFs and every packet stay under `D:\CodexData\gdp-pdf-cache`. GDP.pdf is MIT on Hugging Face
and tagged not-for-training; it is not redistributed, not used for training, and attribution
goes to Surge AI.
