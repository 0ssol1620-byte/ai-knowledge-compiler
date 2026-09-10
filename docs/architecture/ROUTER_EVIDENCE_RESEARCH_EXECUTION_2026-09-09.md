# Router evidence execution — research-led candidate, 2026-09-09

Status: IMPLEMENTED / LOCALLY TESTED CANDIDATE. No production routing authority, model promotion, fresh-holdout result or public benchmark claim. Base is the existing Router v2 PR #59 (2fcdf1a), not a replacement for its parent integration ladder.

## Confirmatory promotion boundary

`ModelEvidence` now requires an exact confirmatory receipt digest, the closed
evidence class `fresh_holdout`, and an explicit evaluated scope before a model
binding can become `QUALIFIED`. Spent-development, retrospective, proxy and
shadow results remain `CANDIDATE` even when their runtime, latency, licence and
failure-mode receipts are complete. The evidence fingerprint is included in
the portfolio revision, so replacing the receipt changes every bound execution
plan instead of silently reusing the old plan identity.

## 1. Research synthesis and deliberate limits

AdaParse (https://arxiv.org/html/2505.01435v1) studies document-to-parser allocation, preference-aligned quality prediction and parallel resource scheduling. It supports measuring dispatch and compute allocation as system components. It does not supply a trusted per-region proof that a financial sign, source version or exact citation survived.

RouteLLM (https://arxiv.org/html/2406.18665v4) studies preference-trained strong/weak model routing. Its relative-preference objective does not replace a source-integrity contract. No reference implementation from either project was imported into this production candidate. A future learned selector needs separate legal/FTO review and the existing shadow/calibration/holdout gates.

The pypdf image extraction documentation (https://pypdf.readthedocs.io/en/latest/user/extract-images.html) notes external decoding dependencies and that iterating all page images can raise a decoding exception. Our new Native pilot reproduced a concrete version of that problem. Installing a decoder, changing licensing boundaries, or dropping images silently was not used to make the run green.

Design choice for this candidate: prove narrow contracts first. Exact source binding and an independently sourced text witness support a declared text-region decision; they do not validate tables, diagrams, images, reading order or a whole World. Agreement among model outputs is never relabelled truth.

## 2. Scheduler defects reproduced before fixing

Seven new lifecycle tests on the unmodified PR59 scheduler produced six failures and one pass.

- Wave barriers were computed inside one model queue and ignored tasks already dispatched. A later Native wave could run while its prerequisite Paddle wave was still queued/running.
- Cancelling a running task did not change its state. It could still be delivered or retried after cancellation.

The fix computes the tenant's earliest active wave over all queues plus running tasks. Cancellation marks running work but retains its capacity until the worker returns. Completion of cancelled work cannot publish success, retry, or contaminate provider health. A cancelled-but-still-running task ID cannot be reused.

This preserves same-wave parallelism and independent-tenant progress. It does not assert that a real worker fleet or a multi-document dependency graph has already been integrated.

## 3. Source-bound text-region execution component

`evidence_execution.py` adds immutable binding/observation/witness/attempt/result types and a bounded async execution function.

Binding includes source revision SHA256, representation SHA256, page, region and exact normalized geometry. The observation content hash is checked. A missing, partial, same-producer or empty witness is not independent proof. Only NFC and whitespace normalization are allowed; signs, decimals, case, currency, units and duplicate content remain meaningful.

A caller supplies the permitted route set and qualified provider implementations. The component validates that set before work, reserves each attempt's declared cost, bounds time and attempt count, tries an alternate after an unresolved primary, checks every replacement, and refuses source/provider binding mismatches. Timeout and transport failure remain separate from content mismatch. CancelledError propagates instead of creating another expensive retry.

Critical caveats:

- The caller/source adapter must establish witness authenticity, complete scope and independence. Different producer strings alone are not a cryptographic independence certificate.
- `VERIFIED_TEXT_REGION` is not a whole-page success flag, OCR accuracy number, candidate-World promotion or legal/security approval.
- Async cancellation is cooperative. Hard termination of GPU/worker processes and remote cancellation remain adapter qualification work.
- Reserved cost is not observed billing. Measured GPU/API/queue/cold-start cost remains unknown here.
- This module has no network transport, evaluator loader, new model capability or global deployment switch.

## 4. Native observation arm and actual spent-data pilot

`native_observation.py` projects the existing native parser's source-bound CIR into per-page observations. Every declared page gets a row. Empty pages, missing geometry and missing text remain visible. Figure metadata is not counted as OCR text. Root and source-reference document/version identities are checked.

`capture_spent.py` selects up to eight public olmOCR samples per original source-path family, ordered by SHA256(sample_id), before parsing. The selection and every original source hash are frozen first. No evaluator outputs, annotations or new holdout are opened.

The first execution selected 56 samples across seven path families and retained all 56 rows: 33 text-observed, 13 without native text, and 10 parser failures. All ten failures reproduced as pypdf DependencyError at JBIG2 decoding; the installed code reports that the `jbig2dec` executable is unavailable. That is a runtime qualification gap, not measured OCR inaccuracy.

During review, the initial projection was also found to omit TITLE blocks. The correction now preserves TITLE, HEADING and PARAGRAPH, with an explicit regression. A separately frozen v2 run uses the identical source selection, preserves the v1 output, and labels decoder dependency failures `native_runtime_unqualified`. Final v2 counts belong to its RESULT.json, not this historical v1 paragraph.

The candidate arm is not yet inserted into the old replay score matrix. A 56-sample availability pilot does not close the previous 1,403-page Native evidence gap. Semantic correctness, table/image fidelity, source-quality adequacy and model superiority are unmeasured.

Final v2 execution retained the same 56 units: 33 text-observed, 13 native-text-unobserved and 10 runtime-unqualified because the external decoder was unavailable. The changed title projection did not change those availability counts; its text bytes are nevertheless separately frozen. No v1 receipt was rewritten.

The additional public-corpus integration suite executed all five exact Explore PDFs (290 declared pages), verified source hashes and emitted one Native observation per declared page. All five tests passed. This is a separate corpus/integration check, not a replacement for the olmOCR pilot and not evidence that all image/table information was correctly extracted.

## 5. Concrete completion programme

| Stage | Required implementation / experiment | Acceptance / current boundary |
|---|---|---|
| Scheduling correctness | Cross-route/running wave barrier; cancellation and duplicate-ID fencing | New failures reproduced and corrected; real fleet integration remains |
| Region verification | Version/representation/locator/hash-bound text witness; bounded attempts | Narrow contract implementation and synthetic tests; trusted witness adapters needed |
| Native coverage | Frozen Native per-page arm, no dropped empties/failures | 56-sample development pilot executed; full corpus scoring not yet run |
| Native runtime | Pin decoder dependencies, license/NOTICE, sandbox and image digest | JBIG2 dependency gap measured; no silent skipping |
| Worker connection | Arrival preflight -> per-document DAG -> bounded provider task dispatch -> durable receipts | Not delivered by this component-only PR |
| Multi-modal loss | Region inventory, table topology, formula and chart/figure coverage | Needs explicit witnesses/adjudication; exact text comparison does not solve it |
| Calibration | Family-separated development/calibration sets; train only on allowed runtime signals | No learned model/threshold fitted in this execution |
| Offline replay | Frozen policy and output lookup, independent held-back scoring, all missing retained | Compare best fixed, Native, existing router, candidate, strong-only, all-model baseline |
| Economic verification | Local/native time, billed GPU/API, cold/queue/retry/speculation, p95 per document | Only local pilot CPU/wall measurements exist |
| Fresh holdout | Open only after frozen development evidence shows value | Not consumed; no confirmation claim |
| Promotion | Exact-head CI, independent review, shadow parity, data-policy checks, bounded canary, rollback | All production switches remain unchanged |

## 6. Research protocol to complete the empirical claim

Primary safety endpoint: silent critical loss per critical opportunity, with coverage/abstention reported beside it. Secondary endpoints: omission, structured information loss, exact locator/version correctness, p50/p95, cost per input and per verified unit. Do not aggregate a missing image/table channel as zero loss.

Use document/family-level separation and bootstrap rather than treating repeated calls or multiple crops as independent documents. Bind input source, parser/model/runtime/image, preprocessing, provider prices, policy and scorer revisions. Learned selection is a challenger until calibrated. Hidden scores and ground truth belong only to the evaluator side. A fallback's text cannot be taken from the answer key or spliced by an oracle unavailable to production.

The relevant experiments are ablations, not merely model-count sweeps: no witness, no independent check, no recovery, no Native, page versus region, sequential versus speculative, old versus corrected scheduling, and verified abstention versus forced acceptance. Report unsupported results and refusals without quietly changing denominators.

## 7. Evidence and qualification

Local evidence is in the new worktree's `.chatgpt2codex` directory. Final implementation tests: 75 passed (new barrier/evidence/native projection tests plus existing execution tests). Ruff clean and strict mypy clean for the three changed/new runtime modules. Re-run the exact final commit in CI; these counts are not a production deployment receipt.

The five distinct public-corpus integration tests also passed. Total selected tests across these two final executions: 80, not counting repeats. The exact final pilot runtime/projection/selection digests are in native-spent-pilot-v2/FREEZE.json and RESULT.json; public-corpus observations are in native-public-observations/.

Historical files remain intact: barrier-before.log, native-spent-pilot/FREEZE.json, observations.jsonl, RESULT.json and FAILURE_DIAGNOSTICS.json. Corrected results use native-spent-pilot-v2. Logs do not contain credentials or customer document content. No GPU or paid inference ran.
