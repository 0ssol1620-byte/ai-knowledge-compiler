# TAVONEL knowledge Arena — 2026-11-04

Campaign `TAVONEL-KNOWLEDGE-ARENA-20261104-V1`. The shared harness that B2b
(document type), C1 (schema induction), C2 (typed extraction), D3 (tables at
product DPI) and E3 (grounded answer) are measured with before anything they
build reaches production (masterplan v5 PHASE 4–5, §9.7).

**Status: harness built and unit-tested; Stage 0 is a capability smoke on the
CALIBRATION split, not a result.** No number here is a public claim, a
calibrated threshold or a model ranking. Status vocabulary is the 2026-09-03
Arena's (`DESIGNED … RUNPOD_E2E_SMOKE … SCORED`).

## What is reused, not rewritten

The 2026-09-03 Model Arena (`research/model_arena_20260903/arena`, commit
`d9db24c`, which is **not on `main` yet**) supplies everything that touches
money or secrets: `RunPodPodsClient` (dry by default, no write retries,
idempotent create, adopt-or-refuse on a name clash), `poll_until_ready`
(readiness deadline, crash-loop and fatal-log detection), `CircuitBreaker`,
`BudgetWatchdog`, `build_ledger_row`, the secret-free guard and atomic writes,
`secrets.runpod_api_key` (value never printed or receipted). `karena` refuses to
import without it; point `KARENA_ARENA_ROOT` at a checkout that has `arena/`.
Tables are scored with OmniDocBench's own TEDS at the Arena's evaluator pin
`193627ae`, in that clone's venv (`KARENA_OMNIDOC_ROOT`).

## Layout

| path | tracked | what |
|---|---|---|
| `karena/` | yes | harness code |
| `prompt_registry/*_v1.{system,user}.txt` | yes | frozen prompts |
| `schemas/*.output.schema.json` | yes | frozen output schemas (also sent as vLLM structured output) |
| `config/tasks.json` | yes | sampling (greedy, seeded), Stage 0 size, repeats |
| `config/model_candidates.json` | yes | candidate registry rows |
| `freeze/FROZEN_v1.json` | yes | sha256 of every prompt, schema, config and case file |
| `inputs/`, `gold/`, `cases/`, `runs/`, `receipts/`, `cost/`, `evidence/` | **no** | fetched bytes, gold, cases, outputs, receipts, ledger |

This repository is public. Fetched documents, gold, outputs and receipts never
enter git (`.gitignore`); the freeze file carries only their hashes.

## Gold (public corpora only)

`python -m karena gold` (needs `KARENA_SEC_USER_AGENT="Org contact@domain"`,
SEC fair-access policy; the builder will not invent a contact):

| source | licence id recorded per document | gives |
|---|---|---|
| SEC EDGAR daily index + primary documents | `SEC-EDGAR-PUBLIC-FILING` (filer-authored public record; no licence grant) | form-type labels (10-K, 10-Q, 8-K, DEF 14A, S-1); typed values |
| SEC inline XBRL `ix:nonFraction` **and** XBRL `companyconcept` API | same | a value is gold only when both agree for the same accession and period |
| Federal Register API | `US-GOV-17USC105` | Rule / Proposed Rule / Notice / Presidential Document labels |
| 대한민국 정책브리핑 press releases | `KOGL-TYPE-1`, only when the page itself carries the 공공누리 제1유형 mark (alt text stored as evidence) | Korean documents (PDF text layer) |

Every licence record says `DECLARED_BY_SOURCE_NOT_LEGALLY_REVIEWED`. Fetches
are cached by sha256 under `inputs/raw` and indexed in `inputs/fetch_index.jsonl`;
`--offline` rebuilds from the cache byte-identically (sha256 ordering, no PRNG).

**Split.** CALIBRATION / EVALUATION is decided per document *family* (SEC CIK,
FR agency or presidential sub-type+month, KOGL ministry) by a salted hash;
`check_split_integrity` refuses any case set where a family crosses sides.
Prompt work happens on CALIBRATION only. Stage 0 runs on CALIBRATION, so the
EVALUATION split is still unseen.

## Tasks

| task | input | output (frozen schema) | deterministic scores | not measured until a person supplies it |
|---|---|---|---|---|
| `doc_type` (B2b) | first 6,000 chars | `{label, evidence_quote}` over 10 labels + `UNKNOWN` | macro-F1 with bootstrap CI, abstentions, confusions | — |
| `schema_induction` (C1) | 3 excerpts of one document type | entity / relation types, each with excerpt-id + verbatim example | example-quote validity, duplicate types, relation endpoints outside the schema | type recall vs a human reference schema (F-10) |
| `typed_extraction` (C2) | one statement-table excerpt + field/entity/period/unit | `{value, unit, evidence_quote}` | numeric exact match (CI), quote verbatim, quote contains the gold number | entity/relation span P/R/F1 (`span_prf` is ready; spans are F-10) |
| `grounded_answer` (E3) | question + 4 excerpts (1 gold + 3 other-company distractors; 1 in 5 cases has no gold → must abstain) | `{status, claims[{value, citations, quote}]}` | answer exact match, citation precision/recall, abstention both ways, unsupported claims | — |
| table @ product DPI (D3) | licensed PDF page rastered the product way | reader's HTML table | official TEDS / TEDS-structure, numeric-cell exact match | gold table HTML (D3 slice, F-10) |

Normalisation is only what v5 §9.5 allows (envelope removal, Unicode/line
endings, JSON parse + schema check). An output that fails is `INVALID_OUTPUT`;
nothing is repaired or re-asked.

**Product DPI.** `table_track.product_raster` repeats Foundation's two passes:
CDR (`quarantine-sidecar/cdr-cloudrun/app.py` @ fnd 5919ecd4) renders at
pypdfium2 scale 1.5 = 108 DPI under its 30 MP / 80 MP budgets, rebuilds an
image-only PDF, and the OCR worker renders that at scale 2.0. So the reader
sees a 108-DPI raster resampled to 144 DPI. `dpi=150/200` gives the D1/D3
comparison. Receipts record `product_parity: false` unless pypdfium2 is the
product's 5.13.0. Today's product reader (RapidOCR line OCR) emits no table
structure; its arm scores 0 by construction and is reported, not dropped.

## Candidates

`config/model_candidates.json` (`python -m karena registry` re-resolves from
Hugging Face). Five open-weights instruct rows, all `role: CANDIDATE`, each
pinned to an exact revision, with **code / weights / dataset / hosted-API
licences as four separate records** and `patent_fto: NOT_ASSESSED`. Every
`capabilities` field is `null` and may only be set alongside an Arena receipt
(`validate_rows` refuses otherwise). One `REFERENCE_ONLY` row for the Opus
subscription arm (arena.opus lane rules: subscription OAuth only, no API key,
no auto-switch, stops at the limit). No API-model arm: founder F-5/F-14.

## Running

```
cd research/knowledge_arena_20261104
export KARENA_ARENA_ROOT=<checkout with research/model_arena_20260903/arena>
python -m pytest tests -q
python -m karena gold                 # or: cases (rebuild from gold/), --offline
python -m karena freeze --version v1  # once; never overwritten
python -m karena verify --version v1
python -m karena stage0 --model qwen3_8b             # dry: writes plan.dry.json only
python -m karena stage0 --model qwen3_8b --execute   # paid; lane cap --budget (USD 60)
python -m karena score runs/stage0/<model>/<stamp>   # offline re-score
python -m karena table-smoke
```

`stage0 --execute`: verify freeze → registry row → 50 CALIBRATION cases per
task → price snapshot → refuse if worst case (highest listed rate × 3 h +
ledger spend) exceeds the cap → one pod `vllm/vllm-openai:v0.19.0@sha256:69234fc3…`
serving the pinned revision with an API key the server enforces (redacted in
every receipt) → Arena readiness poll → tasks, then a 10-case subset twice more
(×3) → pod deleted and the campaign pod list re-read → ledger row in
`cost/pod_ledger.jsonl` → `summary.json`. Between every batch: `STOP` file (here
or in the run dir), budget watchdog, circuit breaker on *operational* failures
only. A wrong answer is a semantic failure: scored, never retried. On a
subscription or usage limit the run stops and is not resumed automatically.

Per case: `runs/…/raw/<task>/<case>.r<n>.json` (provider body as received),
`normalized/…`, and one Appendix A.2 line in `receipts.jsonl` (model id,
revision, input track, prompt/schema/input/raw/normalised sha256, status,
latency, tokens, sampling, price snapshot id).

## How the lanes plug in

- **B2b** — rule baseline and BGE-M3 k-NN arms: produce `{label}` per
  `cases/doc_type.*.jsonl` case and score with `evaluators.doc_type_scores`;
  LLM arms run through `stage0`/the same runner with another registry row. Gate
  (+0.10 macro-F1 over the rule baseline, CI low > 0) is computed on EVALUATION
  after a new freeze, never on CALIBRATION.
- **C1** — add the human reference schemas as `truth.reference_schema` (new
  case version + new freeze); recall then switches from `NOT_MEASURED` to the
  exact-name lower bound, and semantic matching stays a person's call.
- **C2** — XBRL typed values are ready; add span gold and score entities and
  relations with `evaluators.span_prf`; the regex baseline is scored on the same
  gold.
- **D3** — build the slice (`case_id, pdf, page_index, gold_html, licence`),
  pass a reader callable to `table_track.score_tables(..., dpi=108)`; the
  baseline arm is `lambda image: None`.
- **E3** — `grounded_answer` cases + `evaluators.grounded_answer_scores`.
  `unsupported_claims` counts a claim as supported when it cites at least one
  excerpt that exists and its quote (3+ characters, whitespace-normalised)
  appears verbatim in one of the cited excerpts. It does **not** check that the
  quote contains the claimed value; a numeric-anchor check is E3's to add (new
  version, new freeze) before this is used as a grounding gate.

New prompts or schemas are a new version (`*_v2.*`) and a new freeze; a freeze
whose bytes moved stops the runner.
