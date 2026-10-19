# ADR-009: Tables Get Their Own Reader Lane, Shadow First

- Status: Proposed
- Date: 2026-10-17
- Owners: Platform, Research
- Founder decisions required before any part of this ships:
  [Founder-only decisions](#founder-only-decisions)
- Plan: the table/limits design of 2026-10-17, Parts B and C, task T6 (`PLAN:398`). The
  sections below follow the plan's §C8 outline (`PLAN:312-321`).
- Number: the plan names this record ADR-008 (`PLAN:310`). That number was taken afterwards
  by [ADR-008](ADR-008-entity-tie-review.md) (commit `1d4c111`, PR #91), so this is the next
  free one. Read the plan's "ADR-008" as this record wherever it appears.
- Companion: Foundation ADR-0004, `docs/adr/0004-page-range-processing-and-ceiling.md` in the
  Foundation repository (`tavonel-saas-foundation`). It is Proposed, on Foundation branch
  `codex/ux-tab-20261017` at `64add1a7`, and not on Foundation main. It owns the source
  ceiling and page-range processing. This record owns the table lane and changes nothing
  about the ceiling.

## Sources, and how to read a number here

Every number in this record sits beside one of these sources:

- `path:line` is a file in this repository at this record's commit.
- `FND:path:line` is a file in the Foundation repository at main `4c80bb30`, the tree the plan
  read as the live site (`PLAN:5`).
- `FND-TAB:path:line` is a file on Foundation branch `codex/ux-tab-20261017` at `64add1a7`.
- `ALIAS:line` is a line of a text file in the table below. `ALIAS` followed by `field` is a
  field of a JSON file in the table below.

No number here is a public claim, and none may be quoted as one. The Arena figures are an
internal research diagnostic on a dataset licensed `research-only-non-commercial`
(`EVALREG` `evaluators.omnidoc.dataset_license`). They are not measurements of TAVONEL
documents or of customer documents.

| Alias        | File                                                                                                                      | sha256                                                             |
| ------------ | ------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------ |
| `PLAN`       | `outputs/tavonel-research-replan-20261013/ux-program-20261017/TABLE-EXTRACTION-AND-LIMITS-DESIGN-2026-10-17.md`           | `09e20ffed8904fa0cea70c3454604b836df00a47df5c5cffe795dd22ba77c132` |
| `CRITIC`     | `outputs/tavonel-research-replan-20261013/ux-program-20261017/PHASE1-CRITIC-2026-10-17.md`                                | `667010c53a226f980241fc61b3581112cabae954867affc35e24eebf3f8efa81` |
| `ARENA`      | `research/model_arena_20260903/reports/full_compare_20260905/comparison_omnidoc_full.md`                                  | `39a9fd275b1b8f001803c6b830f79317903834dd94f7e1d488f4c49880d99014` |
| `EVALREG`    | `research/model_arena_20260903/evaluator_registry.json`                                                                   | `668eaa0fb6fc7f823ac88cb20b692dc4d45a2c114fd4d7a6e0f5457b454a380b` |
| `PADDLE`     | `infra/model-registry/serving-receipts/paddleocr_vl_1_6.serving-qualification.json` at commit `d6f77b8`                   | `6dbfffd6d10a2d9e2715ee1535a1c7f96c213244769609b8be90b037ec8d6747` |
| `F5C`        | `outputs/tavonel-research-replan-20261013/resume-20261015/gdp-20261015/F5C-IMAGE-ROLLOUT-RECEIPT.json`                    | `817db99ec9044af069888d323db9d687d93e318f7c7f39ae01ce87d3f8481399` |
| `T3R`        | `outputs/tavonel-research-replan-20261013/ux-program-20261017/core-lanes/T3/T3-RECEIPT.json`                              | `20db47bec16c4186bc3d415f21cd108b581ce59966f420a45a79e34f2ac8aa3c` |
| `T4R`        | `outputs/tavonel-research-replan-20261013/ux-program-20261017/core-lanes/T4/T4-LANE-RECEIPT.json`                         | `6a8a6c09c49ce7011683e791a3c8f91615beb028aed3861fc2e927d6dec6f8ac` |
| `SHADOW-SYN` | `outputs/tavonel-research-replan-20261013/ux-program-20261017/core-lanes/T4/TABLE-LANE-SHADOW-RECEIPT.SYNTHETIC.json`     | `8be776ee5a44c2fc5a08fe927d5169f4b69e3dcc2f1dc5dae62fabffed2bf271` |
| `TEDS-SYN`   | `outputs/tavonel-research-replan-20261013/ux-program-20261017/core-lanes/FIX-T4/TABLE-LANE-SHADOW-RECEIPT.SYNTHETIC.json` | `2345aed408c25fddc5b74de2c878c59d8328f4577fb571c0d5ba0825e1fd7fc6` |
| `ADR-0004`   | `FND-TAB:docs/adr/0004-page-range-processing-and-ceiling.md`                                                              | `c28bd546321e0af5a4f37c917a9edc5748c812bb8d7f0535aa7bb7282339225c` |
| `CONTRACT`   | `FND-TAB:shared/tableReadContract.ts` (unchanged since `922e950c`, where it was written)                                  | `5b47899f9a495f6e2badf2082c1de5d9e6dfc0fee4a1750e006b5ca833b2e669` |

`outputs/` and `research/model_arena_20260903/` are paths in the founder's Core working tree,
`D:/CodexProjects/ai-knowledge-compiler`. They are not on this branch. `ARENA` and `EVALREG`
were committed there at `d9db24c`, which is not an ancestor of this branch. `PADDLE` is on
branch `agent/router-second-reader-20260923` (PR #76) and is not on main; its hash is of the
blob at `d6f77b8`.

## Context

### What a table becomes today

| Stage                   | What it does                                      | What happens to a table                                                                               | Source                                                                                                   |
| ----------------------- | ------------------------------------------------- | ----------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| `cdr_sanitizer_v1`      | Rebuilds every allowed input as an image-only PDF | The cells and formulas of a DOCX or XLSX are gone here. This is the security design, not a defect     | `FND:quarantine-sidecar/cdr-cloudrun/app.py:61`; `FND:shared/capabilityManifest.ts:30-33`                |
| `foundation_ocr_gpu_v1` | Emits RapidOCR line regions                       | Every region is a paragraph                                                                           | `FND:workers/foundation-ocr-gpu/app.py:398`; `FND:workers/foundation-ocr-gpu/app.py:436`                 |
| Foundation to Core      | Sends the compile request                         | The region type is the literal `"paragraph"`                                                          | `FND:nextjs/lib/core-runtime-v2.ts:84`                                                                   |
| Core compile contract   | Accepts a region                                  | `block_type` defaults to paragraph and carries no table payload                                       | `packages/product-core/src/akc_product_core/contracts.py:67-72`                                          |
| Core compiler           | Turns a region into a `CanonicalBlock`            | Only `type` and `raw_text` are filled                                                                 | `packages/product-core/src/akc_product_core/compiler.py:678-680`                                         |
| CIR                     | Holds `CanonicalTable`, `CanonicalCell` and LaTeX | A table block without a `CanonicalTable` is refused, and a cell without a source reference is refused | `packages/cir-python/src/akc_cir/models.py:228-229`; `packages/cir-python/src/akc_cir/models.py:157-162` |

The gap is in the contract, not the model. A table reader bolted onto today's path would emit
`block_type=table` with no table payload, and CIR would refuse it. That refusal is correct
fail-closed behaviour and this record keeps it (`PLAN:151`).

### What the deployment says about itself

The live capability manifest, read on 2026-10-17, lists the PDF row as `BEST_EFFORT` with
reader plan `cdr_sanitizer_v1`, `foundation_ocr_gpu_v1`, preserving `page`, `paragraph_text`
and `bbox1000`, with `no_table_or_formula_extraction` among its known limitations and no
qualification receipt (`PLAN:23-32`). The source of those values is
`FND:shared/capabilityManifest.ts:74`, `FND:shared/capabilityManifest.ts:81` and
`FND:shared/capabilityManifest.ts:95`. A test asserts that no row carries a qualification
receipt or a verified tier (`FND:server/foundation/capabilityManifest.test.ts:267-271`).

### What competitors sell (quoted, not reproduced)

Reducto's documentation describes its product as reading "every page into LLM-ready text,
tables, and figures, preserving layout and reading order, with layout-aware chunking"
(`PLAN:36-38`, retrieved 2026-10-17 through a fetch tool's summary). Nothing was run against
it. The quote says what a competitor sells, not how well it does it, and it implies no
comparison with TAVONEL. It must be re-read from the original before any public use
(`PLAN:40`).

### What the candidates measured (internal diagnostic only)

- On the Arena's full OmniDocBench run of 1,651 pages, table TEDS was 0.9344 for
  `paddleocr_vl_1_6` and 0.9342 for `ovisocr2` (`ARENA:11-12`). The difference is too small to
  choose between them before a same-condition run on documents TAVONEL may use (`PLAN:169`).
- Where Paddle and Ovis are paired, both are wrong on 22.9% of table pages and 44.7% of
  formula pages (`docs/adr/ADR-007-element-aware-second-reader.md:46-48`). Even with both
  readers, almost half of the formula pages have no correct reading.
- A four-page serving smoke of `paddleocr_vl_1_6` stopped on the table page at
  `completion_tokens` 2048 with `finish_reason` `length` (`PADDLE` `pages[1]`), and the output
  head repeats `00`. The receipt itself says it proves no accuracy (`PADDLE` `does_not_prove`).
  A whole-page table read can be cut off, and a cut-off read must be refused (`PLAN:171`).
- No candidate is eligible to route. No registry row carries `approval_state`, `capabilities`,
  `data_policy` or `eligibility_evidence`, so no licence counts as approved today
  (`PLAN:179-182`; `PLAN:188`).

## Decision

### 1. A separate reader lane; the existing lane stays authoritative

```text
sanitized.pdf -> foundation_ocr_gpu_v1        (existing, authoritative) -> ocr.json, unchanged
              -> foundation_table_reader_v1   (new, shadow first)       -> table-read/{pageIndex0}.json
```

The new lane does not change a byte of the existing lane's output. That is the first
no-regression condition, and it is checked, not assumed (`PLAN:203-208`; `PLAN:280`). Table
output enters CIR with origin `ai_reconstructed` (`PLAN:210`).

### 2. The lane is triggered by element type, never by a quality comparison

The lane must never take the shape "run reader A, score its output, then conditionally run
reader B". The intake register holds that shape as `DESIGN_AROUND` for IBM US11605028B2
(`docs/ip/TECHNOLOGY_INTAKE_REGISTER.yaml:43-48`), and the constitution forbids routing on a
scalar blind quality score. Whether this design stays outside that `DESIGN_AROUND` family is
counsel's question, not this ADR's, under FTO-1
(`docs/ip/TECHNOLOGY_INTAKE_REGISTER.yaml:153-154`), founder decision F2.

The plan names the trigger as the element type that layout detects (`PLAN:209`). Nothing in
the pipeline detects a table region today: the existing reader emits paragraph lines only
(`CRITIC:60`). So:

- In shadow, the lane reads every page it is given, and `no_table` is an ordinary answer. There
  is no trigger yet, so there is no conditional execution for the `DESIGN_AROUND` gate to
  examine.
- Before canary, the layout source that finds table regions must be named, along with the
  input mode it implies (whole page or table crop). Both are same-condition fields, and both
  go to counsel with F2.

The confirmation in Decision 4 compares the two lanes' text after both have run. It decides
what becomes a claim, never whether a reader runs. Counsel reviews it with the trigger (F2,
`PLAN:380`).

### 3. The contract grows by version, not by inference

The reader writes `tavonel.table_read.v1`. Core receives tables only through a new
`compile_request.v3` (see [Contract](#contract)). Today's request schema is
`tavonel.product_core.compile_request.v2` (`packages/product-core/src/akc_product_core/contracts.py:13`),
and contract changes need a new ADR and a schema version bump (`docs/adr/README.md:5-6`).

### 4. One claim per confirmed data cell

As built in shadow by `table_cell_claims`
(`packages/product-core/src/akc_product_core/table_claims.py:726-774`):

- One claim per data cell whose text an existing OCR line region confirmed (`confirmedBy`) and
  whose column header path is confirmed too. The text is composed deterministically as
  `{column header path, joined by " / "}: {cell text}`
  (`packages/product-core/src/akc_product_core/table_claims.py:758`).
- The evidence is the value cell's source references first, then those of the header cells it
  used. `numeric_values` apply the sentence path's `_NUMBER` rule to the value text only, so a
  year in a header is context, not the cell's value
  (`packages/product-core/src/akc_product_core/table_claims.py:767-771`).
- An unconfirmed cell, a table with no header row, and a value under an unconfirmed or missing
  header produce no claim. Such a cell is shown as evidence and never promoted to a fact
  (`PLAN:250-251`).
- The plan's text also carries a row header path (`PLAN:249`). `table_read.v1` marks header
  rows only, so that half is absent, and it is never guessed from column 0 (`T3R`
  `설계와_다른_점_또는_남은_한계`). Adding row headers is a contract change, not an inference.
- Origin `ai_reconstructed` may sit in the extracted layer. CIR refuses only `ai_summarized`
  and `ai_inferred` there (`packages/cir-python/src/akc_cir/models.py:234-238`).

### 5. Formulas are shown, never claimed, in v1

A formula becomes a `formula` block with `formula_latex`, origin `ai_reconstructed`, at its
source position. It makes no claim. The reason is the both-wrong rate on formula pages in
[What the candidates measured](#what-the-candidates-measured-internal-diagnostic-only). Formula
claims wait for their own measurement (`PLAN:194`).

### 6. No coordinate is invented

- A cell box comes from the reader or does not exist. A cell without one keeps `bbox1000: null`;
  its source reference points at the table's box, and it is flagged
  `cell_located_by_table_bbox_only`. The UI then draws the table box, not a cell box
  (`PLAN:234`; `FND-TAB:shared/tableReadContract.ts:17-19`).
- `confirmedBy` links a cell to an existing OCR line region inside the table box whose text
  equals the cell text after whitespace normalisation. That region's box was measured by
  another reader, so it is not invented. Agreement is not accuracy (`PLAN:235`).

### 7. Native DOCX and XLSX tables are recorded, not designed

Reading cells from the original file needs no model and gives exact cells, which makes it the
cheapest trusted path. It also parses hostile bytes before disarm, so the isolation boundary
of ADR-004 must be decided first. That is the founder's call, and this record designs nothing
for it (`PLAN:195`).

## Contract

### `tavonel.table_read.v1`

One document per page, with exact keys at every level
(`FND-TAB:shared/tableReadContract.ts:206-208`):

```text
{ schemaVersion: "tavonel.table_read.v1",
  sourceImmutableKey, inputSha256,           // the same sanitized.pdf binding as ocr.json
  readerRevision, readerBindingSha256,       // image digest, model id and revision, prompt and schema digests
  pageIndex0, pageNumber1,
  pageStatus: "read" | "no_table" | "unreadable",
  tables: [{ tableId, bbox1000, rowCount, columnCount, headerRowCount, qualityFlags,
             cells: [{ cellId, rowIndex0, columnIndex0, rowSpan, columnSpan, text,
                       bbox1000 | null, confirmedBy: [regionId] }] }],
  formulas: [{ formulaId, bbox1000, latex, display: "inline" | "block" }],
  refusals: [{ bbox1000 | null, reasonCode }] }
```

The Foundation validator is `qualifyTableRead`
(`FND-TAB:shared/tableReadContract.ts:350`). Core mirrors it as `qualify_table_read`
(`packages/product-core/src/akc_product_core/table_claims.py:573`), with the same keys, bounds,
reason codes and refusal order, pinned to the same three SYNTHETIC fixtures by sha256
(`tests/unit/test_product_core_table_claims.py:34-42`).

### Reason codes

Every code names its failure class, so a reader that is down and a reader that was wrong are
never the same problem (`FND-TAB:shared/tableReadContract.ts:34-42`;
`packages/product-core/src/akc_product_core/table_claims.py:52-61`).

| Code                          | Class       | Result                                                                                                                        |
| ----------------------------- | ----------- | ----------------------------------------------------------------------------------------------------------------------------- |
| `TABLE_READER_UNAVAILABLE`    | operational | Only the existing lane is used. The manifest keeps `no_table_or_formula_extraction`. The page is never reported as "no table" |
| `TABLE_BINDING_MISMATCH`      | evidence    | The document fails whole and may be retried, like the OCR lane's retryable evidence error                                     |
| `TABLE_READ_SCHEMA_INVALID`   | semantic    | The document fails whole. Not in the plan's table; added for a document whose shape is wrong                                  |
| `TABLE_OUTPUT_TRUNCATED`      | semantic    | That table is unreadable and makes no claim. The existing paragraph regions stay                                              |
| `TABLE_GRID_INVALID`          | semantic    | Refused by the rule of `CanonicalTable.validate_grid`                                                                         |
| `TABLE_REGION_UNLOCATED`      | semantic    | Refused: the table has no usable box                                                                                          |
| `TABLE_CELL_TEXT_UNCONFIRMED` | semantic    | The cell makes no claim and is shown as evidence                                                                              |
| `FORMULA_LATEX_INVALID`       | semantic    | No formula block. The existing regions stay                                                                                   |

A document shows "M of N tables read", with the denominator, and links every unread table to
its page and box (`PLAN:266`).

### `compile_request.v3` (proposed, not built)

- `ProductCoreRegion` (`packages/product-core/src/akc_product_core/contracts.py:67`) gains two
  optional fields, `table` and `formula_latex`. A region with `block_type=table` must carry
  `table`, which is the CIR rule restated at the boundary
  (`packages/cir-python/src/akc_cir/models.py:228-229`).
- Every new field defaults to none, so a v2 request stays valid unchanged.
- The Foundation literal `"paragraph"` (`FND:nextjs/lib/core-runtime-v2.ts:84`) widens to
  `"paragraph" | "table" | "formula"`.
- The "OCR v3" that `contracts.py` already mentions is the OCR evidence version, not this
  request schema (`packages/product-core/src/akc_product_core/contracts.py:78`).

## Evidence and no-regression

### Same conditions

Both arms run on the same sanitized PDF bytes, render scale and GPU type; the same reader
image digest, model ID and revision, input mode, prompt digest, output schema digest and price
snapshot; the same corpus manifest hash and evaluator commit; and the same existing-lane image
digest (`PLAN:271-276`). The existing lane's digest today is the one in `F5C`
`images.new.ref`. The table metrics use the OmniDocBench evaluator at the commit in
`EVALREG` `evaluators.omnidoc.main_pin` (`PLAN:244`).

### Verdict

The lane is not worse only if all four hold (`PLAN:278-283`):

1. The existing lane's `ocr.json` is byte-identical on the same input.
2. Fact recall does not drop. For every gold table fact (page, row header, column header,
   value), count a claim whose evidence points at that table's box on that page. Count the old
   World and the new World the same way, and the new numerator over its denominator must be at
   least the old one.
3. Unsupported claims do not rise. A claim citing cell text found neither in gold nor in that
   page's OCR counts against its arm.
4. TEDS and cell exact match on the same pages are recorded with their denominators. No
   threshold is set, and no uncalibrated threshold is presented as a result.

### Corpus rights

OmniDocBench is internal diagnosis only (`EVALREG` `evaluators.omnidoc.dataset_license`). The
qualifying corpus must be cleared for the use: SYNTHETIC tables labelled as such, public
filings once their rights are checked, or customer documents under consent (`PLAN:285`). The
critic's merged default is narrower than the plan's: DART is internal measurement only, after
a legal check (`CRITIC:271`). Which corpus is used is F4.

### What exists today

- Stage contract: `table_read.v1` and its validator in Foundation, the Core mirror, the
  CanonicalTable mapping and the cell-claim rule, all shadow only. Nothing in the compile path
  imports them (`packages/product-core/src/akc_product_core/table_claims.py:3-7`).
- Stage shadow, offline: a harness that reads files on disk and writes a
  `tavonel.table_lane_shadow.v1` receipt (`research/table_lane_shadow/run_shadow.py:59`). Its
  receipts are built from SYNTHETIC fixtures, in which no reader ran (`T4R` `합성 영수증`).
  The first, `SHADOW-SYN`, has no TEDS (`SHADOW-SYN` `teds.reason`). An earlier version of
  this record gave the cause as the pinned evaluator not being on disk. That was wrong: a
  checkout at the pin sits in the founder tree under `benchmark/cache/omnidoc`. The second,
  `TEDS-SYN`, has TEDS from that evaluator, run offline on the same fixtures (`TEDS-SYN`
  `teds.status`; `research/table_lane_shadow/omnidoc_teds.py:262`). Without a checkout the
  `teds` block is `EVALUATOR_BLOCKED` and holds no value
  (`research/table_lane_shadow/omnidoc_teds.py:248`;
  `research/table_lane_shadow/run_shadow.py:432-440`).
- No reader has produced a single `table_read.v1` page. No benchmark exists.

## What this does not change

- The existing lane, its image and its `ocr.json`.
- Protected Core. `akc_cir.*` is untouched by the shadow work (`T3R` `건드리지_않은_것`). Cell
  claims enter as units of the existing compile path. Identity, reconciler, world state,
  semantic diff and recompilation are not modified (`PLAN:252`).
- The compile path. No compiler change and no new request schema ships with this record.
- The capability manifest. The row stays `BEST_EFFORT` and keeps
  `no_table_or_formula_extraction` until rollout. At rollout `readerPlan` gains the lane,
  `preserved` gains only what the pipeline actually emits, and the limitation is replaced by the
  exact residual ones. A `VERIFIED_*` status needs the whole-format suite, not a table receipt
  (`PLAN:303-306`).
- The source ceiling. That is ADR-0004's.

## Activation — not an agent's call

Nothing here may be enabled, built as an image, run on a GPU, deployed or described publicly by
an agent. The founder decides:

- the four licences of each candidate (weights, code, dataset, hosted runtime), recorded in the
  registry as `approval_state`. Clearing one clears none of the others;
- the reader image: built in-house with pinned weights, or a vendor-hosted digest;
- GPU spend for shadow, with a stated cap;
- the qualifying corpus and its rights;
- counsel review of the trigger under FTO-1;
- deployment of the worker, Core V2 and the RunPod endpoint;
- every public sentence, including the manifest's `knownLimitations` and `preserved`.

### Ladder

| Stage           | Work                                                                   | Passes when                                                                  | Gate                 | Source     |
| --------------- | ---------------------------------------------------------------------- | ---------------------------------------------------------------------------- | -------------------- | ---------- |
| Contract        | `table_read.v1`, validators, cell-claim projection, SYNTHETIC fixtures | A failure-path test per reason code; existing compile outputs byte-identical | Agent (T2, T3), done | `PLAN:291` |
| Shadow, offline | Harness from files on disk to receipt R2                               | Same input, same receipt hash; unlabelled gold and mixed corpora refused     | Agent (T4), done     | `PLAN:292` |
| Shadow, GPU     | Pinned reader image run outside the product path                       | Digest confirmed by pull; existing lane unchanged; R1 and R2                 | Founder: F1, F3      | `PLAN:293` |
| Benchmark       | The four-part verdict on a cleared corpus                              | All four conditions                                                          | Founder: F4          | `PLAN:294` |
| Canary          | `compile_request.v3` dispatch for allow-listed workspaces only         | Error and unreadable rates with denominators; rollback tested                | Founder: F2, F8      | `PLAN:295` |
| Rollout         | Everywhere, plus the manifest change                                   | Qualification receipt digest committed                                       | Founder: F7          | `PLAN:296` |
| Deprecate       | Remove the duplicate paragraph claims inside tables                    | Fact recall still holds                                                      | Benchmark            | `PLAN:297` |

In v5's order, reader comparison is PHASE 5
(`docs/north-star/TAVONEL_MASTERPLAN_v5.0.md:1789`), shadow is PHASE 6
(`docs/north-star/TAVONEL_MASTERPLAN_v5.0.md:1801`), batch lanes and the cost ledger are PHASE 7
(`docs/north-star/TAVONEL_MASTERPLAN_v5.0.md:1807`) and CIR integration is PHASE 9
(`docs/north-star/TAVONEL_MASTERPLAN_v5.0.md:1823`). Phase numbers are dependency order, not
priority.

## Founder-only decisions

No agent decides these, and this record does not infer them from the plan. Each row gives the
plan's decision (F) and the critic's merged decision (D). F5, F6 and F9 belong to ADR-0004's
ceiling work; they are listed so the set is complete.

| Decision | Question                                                                                                                                                                        | Plan's default                                                                                                           | Merged as | Source                   |
| -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ | --------- | ------------------------ |
| **F1**   | Approve the four licences of a table reader candidate and record `approval_state` in the registry                                                                               | Review `paddleocr_vl_1_6` alone, for shadow. Hold `mineru_vlm` until its runtime thresholds and notice duty are accepted | D-25      | `PLAN:379`; `CRITIC:265` |
| **F2**   | Counsel review of the trigger design (element-type trigger, after-the-fact agreement gate) against IBM US11605028B2 (FTO-1), including the layout source Decision 2 leaves open | Review before canary; shadow proceeds as research                                                                        | D-26      | `PLAN:380`; `CRITIC:266` |
| **F3**   | Build the reader image in-house with pinned weights, or use the vendor-hosted digest; and the shadow GPU spend cap                                                              | Build in-house; the cap is a stated amount set by the founder                                                            | D-25      | `PLAN:381`; `CRITIC:265` |
| **F4**   | The qualifying corpus: SYNTHETIC, public filings, consented customer documents                                                                                                  | SYNTHETIC plus public filings first; customer documents only after consent                                               | D-31      | `PLAN:382`; `CRITIC:271` |
| **F5**   | The architecture that raises the ceiling: Core reading OCR from R2, asynchronous compile, transfer above the documented HTTP/1 limit                                            | Reference read and asynchronous dispatch; decide the large transfer after the next stage is measured                     | D-27      | `PLAN:383`; `CRITIC:267` |
| **F6**   | Per-page metering and its credits                                                                                                                                               | Design the metering; every number is the founder's                                                                       | D-28      | `PLAN:384`; `CRITIC:268` |
| **F7**   | When `/sources`, pricing copy, the manifest's `knownLimitations` and `preserved` change, and whether any row moves to `VERIFIED_*`                                              | With the rollout receipt; a status change only after the whole-format suite                                              | D-29      | `PLAN:385`; `CRITIC:269` |
| **F8**   | Applying worker, Cloud Run, RunPod and Supabase migration changes in operation                                                                                                  | Per stage, each with a receipt and a rollback ID; outside the delegation to merge to main                                | D-20      | `PLAN:386`; `CRITIC:260` |
| **F9**   | The product-path OCR timing run on SYNTHETIC scans, which spends GPU money                                                                                                      | Approve, under a small cap                                                                                               | D-30      | `PLAN:387`; `CRITIC:270` |

## Receipts

What the plan asks for (`PLAN:325-334`), and what exists today:

| ID  | File                                             | Holds                                                                                           | Today                                                                                                                  |
| --- | ------------------------------------------------ | ----------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| R0  | `table-lane/CONTRACT-FIXTURES.json`              | SYNTHETIC fixtures and their sha256                                                             | Not written as a file. The three fixtures are pinned by sha256 in `tests/unit/test_product_core_table_claims.py:34-42` |
| R1  | `serving-receipts/<provider>.table-serving.json` | Pulled image digest, model ID and revision, GPU type, price snapshot, proves and does not prove | Not produced (F1, F3)                                                                                                  |
| R2  | `TABLE-LANE-SHADOW-RECEIPT.json`                 | Every input digest, per-page status and reason codes, TEDS, cell rates, `ocr.json` comparison   | SYNTHETIC only, `SHADOW-SYN`. No reader ran                                                                            |
| R3  | `TABLE-LANE-BENCHMARK-RECEIPT.json`              | The four-part verdict, both arms with denominators                                              | Not produced (F4)                                                                                                      |
| R4  | `TABLE-LANE-CANARY-RECEIPT.json`                 | Allow list, document and page denominators, unreadable rate, rollback test, deployment ID       | Not produced (F2, F8)                                                                                                  |
| R5  | Qualification receipt                            | The digest the manifest's `qualificationReceipt` will carry                                     | Not produced (F7)                                                                                                      |
| R6  | Licence snapshots, one per licence               | The bytes read and their sha256. Not a legal opinion                                            | Snapshots exist on the PR #76 branch only, not on main (`PLAN:187`)                                                    |
| R7  | Limit measurement, per stage                     | Seconds, memory, pixels and bytes per range                                                     | ADR-0004's                                                                                                             |

## Consequences and risks

- **Truncation.** The smoke run cut off a table page and repeated itself (`PADDLE`
  `pages[1]`). Whole-page input is the risky mode; a table crop needs the layout source that
  Decision 2 leaves open, and `TABLE_OUTPUT_TRUNCATED` refuses what is cut off (`PLAN:350`).
- **The confirmation gate costs recall.** A true cell that the other reader read differently
  never becomes a claim. Verdict condition 2 measures that cost (`PLAN:351`).
- **Cell identity.** Without row headers, a column header path is not unique within its column,
  so it cannot be the identity anchor the plan proposes (`PLAN:252`; `T3R`
  `설계와_다른_점_또는_남은_한계`). Whether identity holds when a row is inserted is unmeasured,
  and it is measured without changing Protected Core (`PLAN:352`).
- **Licences and supply chain.** A vendor registry image, a digest resolved from a floating
  tag, weights in the image that may not match the pinned revision, MinerU's runtime terms and
  OvisOCR2's separately licensed base model (`PLAN:353`).
- **Dataset rights.** No public sentence may rest on the OmniDocBench figures (`PLAN:354`).
- **Patent.** FTO-1 is open (`PLAN:355`).
- **Cost.** The lane's cost per document is unknown until a real R2 exists, because the share
  of pages that hold a table was never measured. Raw GPU cost is recorded per page and never
  beside credits or a retail price (`PLAN:341-342`).
- **Ceiling.** Everything about how large a source may be is ADR-0004's.

## Corrections to the plan

The plan read the founder's Core tree at `d5eabfa` (`PLAN:5`). This branch differs, and the
citations above use this branch.

- The ADR number, as stated in the header.
- CIR line numbers differ on this branch: `SourceRef`, `CanonicalCell`, `CanonicalTable`,
  `validate_grid` and the table-block rule are at
  `packages/cir-python/src/akc_cir/models.py:101`, `packages/cir-python/src/akc_cir/models.py:127`,
  `packages/cir-python/src/akc_cir/models.py:165`, `packages/cir-python/src/akc_cir/models.py:176`
  and `packages/cir-python/src/akc_cir/models.py:228-229`.
- The ADR-007 figures the plan cites as lines 40-41 and 54 of that file are at
  `docs/adr/ADR-007-element-aware-second-reader.md:33-34` and
  `docs/adr/ADR-007-element-aware-second-reader.md:46-48` here.
- The plan cites `ProductCoreRegion` in the Core V2 deployment source; on this branch it is at
  `packages/product-core/src/akc_product_core/contracts.py:67`.
- The claim text has no row header half, as Decision 4 records (`PLAN:249`; `T3R`
  `설계와_다른_점_또는_남은_한계`).
- `table_read.v1` allows a `cellId` shorter than CIR's three-character `StableId`
  (`packages/cir-python/src/akc_cir/base.py:35-38`). Core refuses such a document as
  `TABLE_READ_SCHEMA_INVALID` instead of renaming the cell (`T3R`
  `설계와_다른_점_또는_남은_한계`). Aligning the two minimums is a contract decision.

## Not verified

- That any candidate serves a well-formed `table_read.v1` page. No reader produces one yet.
- The layout source for table regions, and the crop input mode it would allow.
- How many pages of a TAVONEL or customer corpus hold a table.
- Whether the weights inside the Paddle image match the pinned revision (`PADDLE`
  `does_not_prove`).
- TEDS on any page, in any arm.
- That `PADDLE` and the licence snapshots have reached the remote main. Only local refs were
  read.

## Evidence

- The aliases in [Sources](#sources-and-how-to-read-a-number-here), each with its sha256.
- `tests/unit/test_product_core_table_claims.py` (T3) and
  `research/table_lane_shadow/test_run_shadow.py` (T4), with their failure paths.
- A mechanical check of this record: every unit that holds a number also holds a source; every
  `path:line` and `ALIAS:line` is opened and matched to the text it supports; every alias hash
  is recomputed; every JSON field cited resolves; and mutations of this text must each fail. The
  check and its result are `adr009_check.py` and `ADR-009-CHECK.json` under
  `outputs/tavonel-research-replan-20261013/ux-program-20261017/core-lanes/T6/`.
- Prettier 3.9.6, the formatter this repository pins (`package.json:28`), passes on this record
  and on the index.
