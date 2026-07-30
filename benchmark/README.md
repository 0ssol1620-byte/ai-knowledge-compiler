# AKC Golden Benchmark

This directory is the reproducible parser/routing benchmark contract. Official
model-card claims are candidate-discovery inputs only. Production claims and
promotion decisions require the same licensed internal corpus, output contract,
hardware class, tuning budget, and cost boundary.

## Local contract run

The committed corpus is harmless synthetic data. It validates schemas,
evaluators, reports, and provider adapters; it MUST NOT be used for quality
claims or model promotion.

```bash
python benchmark/run_benchmark.py \
  --ground-truth benchmark/ground-truth/synthetic-v1.jsonl \
  --provider local_mock \
  --output benchmark/reports/local-contract.jsonl

python benchmark/report.py \
  --input benchmark/reports/local-contract.jsonl \
  --output benchmark/reports/local-contract.md
```

## Real native parser lane

`native_document` reads immutable source bytes from an explicitly supplied
private corpus root. Each ground-truth row must include a relative `source`
object with `path`, display-only `filename`, `content_type`, and lowercase
SHA-256. Absolute paths, traversal, hash mismatches, and missing raw-artifact
storage fail closed. The runner invokes the same bounded PDF/Office/image/web/
text parser as the document worker; it never copies reference text or blocks
into candidate output.

```bash
python benchmark/run_benchmark.py \
  --ground-truth /approved/corpus/ground-truth.jsonl \
  --provider native_document \
  --corpus-root /approved/corpus/files \
  --raw-output-dir /private/evidence/raw/native \
  --output /private/evidence/native-scores.jsonl
```

The native revision is a SHA-256 over the parser source, Python runtime, and
all native parser dependency versions. Raw candidate output and source bytes
are separately hash-bound in each score record. The raw directory is private
evidence and must never be committed.

## External candidate lanes

Every provider listed in `manifest.yaml` is wired through an explicit adapter.
Network execution is fail-closed: it requires all of `--endpoint`,
`--model-revision`, `--allow-network`, a private raw-output directory, and an
exact hostname in `AKC_BENCHMARK_ENDPOINT_ALLOWLIST`. The endpoint must be
HTTPS, resolve only to public addresses, return JSON without redirects, and
attest the exact requested provider and immutable 40-64 character revision.
Provider credentials are accepted only through
`AKC_BENCHMARK_PROVIDER_TOKEN`; they are never command-line arguments.

For real cases, the runner reads a hash-bound file beneath `--corpus-root` and
sends only the bounded source plus non-label routing metadata. Ground-truth
text, expected blocks, reading order, and generated-claim annotations remain
inside the evaluator. Synthetic fixtures may include their harmless reference
content but remain `contract_test` results and cannot promote a model.

```bash
AKC_BENCHMARK_ENDPOINT_ALLOWLIST=parser.example.com \
AKC_BENCHMARK_PROVIDER_TOKEN=... \
python benchmark/run_benchmark.py \
  --ground-truth /approved/corpus/ground-truth.jsonl \
  --provider paddleocr_vl_1_6 \
  --corpus-root /approved/corpus/files \
  --raw-output-dir /private/evidence/raw/paddle \
  --endpoint https://parser.example.com/v1/parse \
  --model-revision 0123456789abcdef0123456789abcdef01234567 \
  --allow-network \
  --output /private/evidence/paddle-scores.jsonl
```

## Promotion run requirements

- private corpus manifest and immutable source hashes;
- corpus rights and split lineage;
- hidden holdout not used for tuning;
- exact model repository/revision and container image digest;
- CUDA, driver, framework, GPU/VRAM, decoding, DPI, batch, and concurrency;
- separately recorded cold/warm repetitions;
- failed pages retained as failures;
- immutable raw artifacts and report;
- fact class `internal_result`, never `official_claim`;
- all hard-fail metrics available from non-proxy evaluators.

Network runners are opt-in and accept only synthetic or approved benchmark
objects. Customer production documents are never benchmark inputs.

## OpenDART public source acquisition

`acquire_dart.py` creates a hash-bound private acquisition manifest from
OpenDART business-report source packages. It uses the official disclosure
search (`list.json`, detail `A001`) and original-document (`document.xml`)
contracts. The key is read from `AKC_DART_API_KEY` or one explicitly supplied
local credential file and is never written to a URL log, receipt, source
manifest, browser bundle, or exception.

```powershell
py -3 benchmark/acquire_dart.py `
  --begin-date 20260101 `
  --end-date 20260430 `
  --maximum-filings 10 `
  --credential-file D:\Github_API.txt `
  --confirm PUBLIC_DART_BENCHMARK_ONLY
```

The default target, `benchmark/datasets/private/dart`, is gitignored. Downloaded
source packages are public inputs, not labels. Every receipt therefore records
`labels_present=false` and `eligible_for_quality_claims=false`. A rights review,
frozen split, independent annotations, and the Gate 2 evidence bundle remain
mandatory before any score is published.

## Structured evaluator contract

Quality evaluators consume the structured fields in
`schemas/page-ground-truth.schema.json` and
`schemas/parser-output.schema.json`. They do not infer a table, formula, or
outline from prose. A metric is JSON `null` when its reference annotation is
absent or invalid; when a valid reference annotation exists but the parser
omits or corrupts the corresponding output, the score is `0`.

- `table_teds` is the legacy score-record key for AKC's dependency-free,
  deterministic table **structure** similarity. It serializes ordered
  table/row/cell topology (dimensions, header rows, coordinates, and spans) and
  applies normalized token edit distance. It is TEDS-style, not the official
  TEDS algorithm, and it does not compare cell text.
- `table_cell_exactness` compares cells by row, column, row span, column span,
  and NFC/whitespace-normalized text. Missing and extra cells and tables are
  penalized; tables are paired in reading order.
- `formula_edit_score` compares structured LaTeX in reading order using
  normalized character edit similarity. Outer math delimiters, whitespace,
  `\left`/`\right`, and a small documented set of equivalent Unicode operators
  are presentation-only normalization; identifiers and all other content
  remain case-sensitive.
- `heading_tree_score` uses `heading_outline`, or heading blocks carrying
  `heading_level` when the explicit outline is absent. Its weighted edit cost
  gives equal substitution weight to outline level and normalized heading
  text.
- `numeric_exact_match` compares ordered numeric tokens from page text.
  `date_unit_exact_match` separately compares ordered `dates` and `units` in
  `date_unit_annotations`; unit labels exclude their numeric amounts and remain
  case-sensitive. This catches `10 mg` versus `10 g` even when numeric tokens
  match.

Runtime measurements may fill only the latency, GPU, cost, and
`normalized_speed` fields, plus measured `review_time_ms`. Provider-supplied
runtime dictionaries cannot override evaluator-owned quality metrics.

## Complete section 22 metric surface

Evaluator version `22.4-22.8-v1.0.0` publishes every extraction, knowledge,
RAG, and router metric named by masterplan sections 22.4-22.7. The exact keys
and bounds are frozen in `schemas/score-record.schema.json`; the annotation
contracts are frozen in the ground-truth and parser-output schemas.

- Layout detection uses a deterministic, one-to-one greedy match at bbox IoU
  `0.50`, then computes detection precision/recall and block-type macro F1.
- Reading order publishes Kendall tau and Spearman rho in addition to the
  legacy pair-accuracy score.
- Table rows, columns, cells, spans, and multi-page merge edges are scored
  separately. `table_teds` remains the explicitly documented local surrogate;
  it is never represented as official TEDS.
- Knowledge note splits are matched by exact evidence-block sets. Relation,
  conflict, evidence, duplicate, unsupported-summary, and user-edit metrics
  require their explicit annotation structures.
- A human title score is accepted only with at least two reviewers, a
  non-empty rubric version, and a `sha256:` evidence digest. Otherwise it is
  `null`.
- RAG metrics are query-level Recall@5/10, MRR, nDCG@10, citation
  precision/recall, evidence-bound groundedness, stale-version rejection,
  unanswerable refusal, and multi-hop evidence completeness.
- Router metrics include all eight required measures. Cost and latency are
  emitted as deterministic per-document-class maps, not collapsed into a
  misleading global average.

`evaluators/merge_gate.py` implements the local section 22.8 comparison gate.
It fails closed on a missing case, schema-invalid score, critical-number
regression, unsupported-content growth, or excessive crash/OOM/timeout rate.
A variable-cost increase above 10% requires a separate explicit approval.
Passing this local gate does not close the licensed-corpus, real-model, canary,
or production evidence gates.

## Evaluator-backed hard failures

High-risk cases hard-fail on any available numeric or date/unit exactness score
below `1.00`. A structured table result is a `severe_table_error` when the
minimum available value among `table_teds` and `table_cell_exactness` is below
`0.50`; exactly `0.50` is not severe. The conservative initial threshold
implements ADR-005's severe-table review boundary without inventing a result
when table annotations are unavailable.
