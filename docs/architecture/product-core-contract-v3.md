# Product-Core contract v3 — OCR by reference, asynchronous compile (design)

- **Status:** Proposed. Design only. This file changes no code, no test, no flag, no deployment, no
  limit, no public sentence, no price and no evidence artifact. Nothing here is implemented.
- **Decision:** register row **D-27** (source PHASE1-CRITIC D-27, alias T-F5), class `agent-now`,
  lane `NEW:T9`. Adopted default, verbatim: "Core가 OCR을 R2 참조로 읽고 compile은 비동기
  dispatch로 한다. 32 MiB를 넘는 전송은 1단계 측정 뒤에 정한다" (`REG:36`).
- **Adoption:** the founder adopted every register default on 2026-10-17: "파운더 결정은 모두
  실서비스에서 업계 1위 될 수 있도록 너가 추천한 방향으로 진행해서 완료할 수 있도록해줘"
  (`REG:3`). That is the adoption of the direction. It is not an approval of any wording, number,
  credential or deployment in this file.
- **Written:** 2026-10-19 by an agent (lane T9-DESIGN). The session that writes this does not
  approve it. An independent reviewer does.
- **What the row binds the code lane to** (`REG:36`, `executesVia`): v2 requests stay valid; a
  sha256 mismatch on R2 bytes fails the compile; a compile longer than 52 s completes across turns.
  Prerequisites: P2-36 (T7 measurement, done, §5), FH-18 (Core R2 read credential, at deploy) and
  T-F8 (worker deploy).

## Why this file lives here

The row names code paths, not a document path. `docs/architecture/` holds the other design
documents for Core boundaries (`canonical-ir.md`, `multimodal-retrieval.md`). The Foundation half
of the same plan is ADR-0004, Part C (`ADR4`), and the Core table-lane half is ADR-009 (lane T6).
This file is the Core half of Part C.

## Short paths

| Alias    | Path                                                                                                  | Pin                                                                 |
| -------- | ----------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------- |
| `CORE`   | this repository, `D:\CodexProjects\handoff-1002\core-DOCS`                                            | base `codex/tavonel-p0p2-productization` 75cc3ea                    |
| `FND`    | `D:\CodexProjects\handoff-1002\fnd-DOCS`                                                              | `main` 4c80bb30 (= tavonel.com)                                     |
| `WORKER` | `FND quarantine-sidecar/foundation-cdr-worker`                                                        | same                                                                |
| `UX`     | `D:\CodexProjects\ai-knowledge-compiler\outputs\tavonel-research-replan-20261013\ux-program-20261017` | —                                                                   |
| `REG`    | `UX\DECISION-REGISTER-2026-10-17.md` (pair `.json`)                                                   | sha256 `5935276d…71d7c6dc` (`.json` `86234c93…4120d3`)              |
| `PLAN`   | `UX\TABLE-EXTRACTION-AND-LIMITS-DESIGN-2026-10-17.md`                                                 | sha256 `09e20ffe…ba77c132`                                          |
| `T7`     | `UX\table-limits-receipts\PRODUCT-PATH-OCR-TIMING.json` and `.md`                                     | sha256 `7c5b1fe1…de872a5b` (`.md` `059529d7…77998b87`)              |
| `FIT`    | `UX\table-limits-receipts\FIT-AND-PAYLOAD.json`                                                       | sha256 `ace09a54…42f40f3d59`                                        |
| `T5`     | `UX\core-lanes\T5\RECEIPT.json`                                                                       | sha256 `4539740e…fe60909`; branch `codex/ocr-page-range-20261017`   |
| `ADR4`   | Foundation `docs/adr/0004-page-range-processing-and-ceiling.md`                                       | branch `codex/ux-tab-20261017`, commit 64add1a7, Proposed, unmerged |
| `SD`     | `UX\SERVICE-DEFINITION-2026-10-17.md`                                                                 | sha256 `c7783dd7…0b528dee`                                          |

Line numbers are for the pinned trees above. `PLAN` and `ADR4` cite an older Core tree (p0p2
3ffe927), so their `contracts.py:52` and `:57` are `:96` and `:108` here. The **deployed** Core v2
is production `dpl_ARpeXMfVcWmjfje6DNDCAwAGyV35` of 2026-09-30, and 75cc3ea was merged, not
deployed (`SD:13`). Every Core line below describes source, not the running service.

## 1. Contract v2 today — the call path

| #   | Step                                                                                                                                                                                                                                                                                                                                | Where                                                                                                                                                            |
| --- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | A cron calls the worker route every minute. The route lives 60 s.                                                                                                                                                                                                                                                                   | `FND nextjs/vercel.json:14-15`; `FND nextjs/app/api/internal/jobs/run/route.ts:22`, `:56`                                                                        |
| 2   | The compile job takes its lease by moving to `structuring`. A job already in `structuring` is skipped until the lease is 5 minutes old.                                                                                                                                                                                             | `FND nextjs/lib/compile-job-worker.ts:78`, `:313-326`                                                                                                            |
| 3   | Foundation reads each `ocr.json` from R2 with its own signer (Object Read & Write on the Foundation bucket), capped at 4 MiB per object.                                                                                                                                                                                            | `FND nextjs/lib/collection-compile-run.ts:146`, `:196-200`; `FND nextjs/lib/r2-objects.ts:14`, `:208-232`; `FND docs/FOUNDATION_R2_SIGNER_TOKEN_2026-08-28.md:3` |
| 4   | Foundation validates every body: readable JSON, schema allowlist and key set, regions present, v3 reader gates.                                                                                                                                                                                                                     | `FND nextjs/lib/collection-compile-run.ts:208-223`, `:257-265`, `:266-287`                                                                                       |
| 5   | Foundation builds `compile_request.v2`. Every region travels inline. `ocrObjectKey` travels beside it. The idempotency key is the document binding, not the attempt.                                                                                                                                                                | `FND nextjs/lib/core-runtime-v2.ts:241-332`; key `:276-278`; `ocrObjectKey` `:299`; regions `:318-329`                                                           |
| 6   | Foundation signs the raw body and POSTs `/v2/compile`, waiting at most `maxLatencyMs` = 52,000 ms (60 s turn less an 8,000 ms reserve).                                                                                                                                                                                             | `FND nextjs/lib/core-runtime-v2.ts:729-747`; `FND nextjs/lib/execution-budget.ts:41`, `:52`, `:55`, `:58`                                                        |
| 7   | Core refuses bodies above 32 MiB, verifies the HMAC (timestamp within 300 s), validates the schema, then refuses customer data unless enabled.                                                                                                                                                                                      | `CORE packages/product-core/src/akc_product_core/api.py:22`, `:61-86`; `auth.py:51-94`, `:57`; `contracts.py:13-14`, `:203-239`                                  |
| 8   | Core replays by (tenant, workspace, idempotency key) and answers 409 when the same key carries different work. Without `TAVONEL_CORE_JOURNAL_PATH` the replay cache is in process memory.                                                                                                                                           | `CORE …/api.py:90-141`; `journal.py:28-37`, `:97-124`; `__main__.py:21`                                                                                          |
| 9   | Core checks that both object keys are immutable and content-addressed, but a failure is only a review reason, and Core never reads either object. Core has no object-store client: no `boto3`, `botocore`, `R2_`, `s3.`, `urllib.request` or `httpx` under `packages/product-core/src`. Its runtime dependencies are four packages. | `CORE …/compiler.py:278-280`, `:517-548`; `CORE infra/product-core/vercel/requirements.txt:1-4`                                                                  |
| 10  | Core answers synchronously with the whole candidate inline. Foundation checks the receipt (request ID, input digest, output digest of the candidate bytes).                                                                                                                                                                         | `CORE …/contracts.py:269-308`; `FND nextjs/lib/core-runtime-v2.ts:776-803`                                                                                       |
| 11  | Any failed dispatch fails the job, except a reading-listing disagreement, which is deferred.                                                                                                                                                                                                                                        | `FND nextjs/lib/compile-job-worker.ts:333-391`                                                                                                                   |

Core v2 runs as one Vercel Python function, `maxDuration` 300 s (`CORE infra/product-core/vercel/vercel.json:3-8`).

### What reading the path showed

These are facts from reading source. None was reproduced end to end.

1. **The first bound a dense document hits is Foundation's 4 MiB read, not Core's 4.5 MB.** The
   73-page dense document's OCR body is 4,463,100 B (`FIT` `ocrPayload`). 4 MiB is 4,194,304 B
   (`r2-objects.ts:14`), so it is over by 268,796 B [calc]. The refusal surfaces as
   `OCR_BINDING_INVALID` (`collection-compile-run.ts:208-210`): a size limit reported as a binding
   failure. `PLAN:92` and `ADR4` name the Vercel request body (4.5 MB, `PLAN:92`) as the next
   bound. In this tree the Foundation read cap comes first.
2. **A Core timeout ends the job.** `core-runtime-v2.ts:750-761` and ADR-0003 call
   `CORE_V2_TIMEOUT` retryable (`FND docs/adr/0003-core-execution-budget-and-async-dispatch.md:61-64`).
   The durable worker still sets the job to `failed` on it (`compile-job-worker.ts:384-391`).
   Asynchronous dispatch needs "pending" to be a separate outcome.
3. **A job that stays in `structuring` is retried only after the lease goes stale.** The deferral path
   re-advances the row to `structuring` (`compile-job-worker.ts:368-382`). The next turn then skips
   it until 5 minutes have passed (`:78`, `:324-326`). As written, a multi-turn compile advances
   once per 5 minutes, not once a minute.
4. **The v3 digest needs its own idempotency key.** Core binds a key to a work digest and returns
   409 when the same key comes back with different work (`api.py:104-105`, `:120-121`). A v3 body
   for the same documents has a different work digest from the v2 body. So v3 cannot reuse
   `core-runtime-v2.ts:276-278` unchanged.
5. **Deletion would miss new objects.** The R2 deletion inventory scans each document's prefixes
   and named World keys exactly (`FND nextjs/lib/source-deletion-inventory-r2.ts:111-135`). An
   object under a new prefix is not covered until it is added.
6. **There is still a hidden 80-page cap.** The completed-read record refuses `observedPageCount`
   above 80 (`FND shared/completedReadReceipt.ts:66`), which `T5` also found. v3 reference mode
   takes `ocrSha256` from that record (§2.2), so it inherits the cap until the cap moves with the
   intake ceiling.

## 2. Contract v3

v3 has two parts. Each has its own flag and can ship on its own.

- **v3-R:** Core reads OCR by reference. This removes OCR bytes from Foundation's read and from the
  Core request body.
- **v3-A:** compile is dispatched asynchronously. This removes the 52 s ceiling.

### 2.1 Wire

- **Endpoint.** `POST /v3/compile` is new. `/v2/compile` and both v2 schemas are unchanged
  (`api.py:191-199`, `contracts.py:13-14`). A v2 request stays valid for as long as §4 step 6 has
  not run.
- **Request** `tavonel.product_core.compile_request.v3` is the v2 model (`contracts.py:203-239`)
  with three changes:
  1. **Each document carries `regions` (inline, as in v2) or `ocrSha256` (by reference), never
     both.** Both or neither is a 422. Inline v3 lets v3-A ship without v3-R.
  2. **`ocrPolicy.requireReaderV3` (boolean)** carries the gate that `FOUNDATION_OCR_CONFLICT_V3_REQUIRED`
     applies before dispatch today (`collection-compile-run.ts:275-277`). In reference mode Core
     enforces it before it compiles. Foundation no longer holds the body, so it cannot.
  3. **`checkpoints`: list of `{connectorType, nativeId, objectKey}`** names the documents already
     compiled in earlier turns (§2.3). It is progress, not work: it is excluded from the work
     digest, as `requestId`, `requestedAt` and `maxLatencyMs` already are (`journal.py:28-37`).
- **Idempotency.** The v3 key is `compile-v3-` plus the same binding hash. It never collides with a
  v2 key (§1 finding 4). A job records the contract version of its first dispatch and keeps it
  until it settles.
- **Authentication.** It is the v2 scheme unchanged: the same headers, the same HMAC and the same
  300 s window (`auth.py:30-94`). There is no new transport secret.
- **Customer data.** The `approved_customer_data` refusal (`api.py:82-86`) runs before any R2 read.

### 2.2 v3-R — Core reads OCR from R2 by reference

**Where `ocrSha256` comes from.** It is the digest the worker computes over the durable `ocr.json`
winner (`WORKER src/ocr.ts:128`). It travels in the completed-read facts (`WORKER src/index.ts:76-90`,
`ocrSha256` at `:83`) and is stored through `settle_foundation_completed_read_v1`
(`FND nextjs/lib/completed-read-proof.ts:35`). Foundation reads it back through
`read_foundation_completed_read_v1` (`:59`). When there is no completed-read record, Foundation does
not guess. It dispatches v2 inline and records the route reason `CORE_V3_REFERENCE_UNAVAILABLE` on
the job. This is an explicit route with a stated reason, not a silent fallback.

**Core reads one object in eight steps.** Each step can stop the read with the code shown.

1. **Key check, before any network call.** The key must sit under `immutable/{tenant}/{workspace}/`,
   be the `ocr.json` sibling of `immutableObjectKey` (`WORKER src/keys.ts:76-81`) and pass the
   predicate Core already has (`compiler.py:517-548`). In v3-R a failure is a hard refusal, not a
   review reason, because Core is about to use a credential: `CORE_OCR_REFERENCE_INVALID`, zero R2
   requests.
2. **Signed GET.** This is a SigV4 GET with the standard library (`hmac`, `hashlib`, `urllib.request`).
   It adds no new dependency, so no new intake row (`CORE docs/ip/TECHNOLOGY_INTAKE_REGISTER.yaml`).
   Foundation's equivalent is `r2-objects.ts:208-232`.
3. **Bounded streaming read.** The cap is 24 MiB, the size the worker will persist
   (`WORKER src/ocr.ts:101`). The bytes are hashed while streaming. The cap joins the P2-18
   cross-tree test, so the two numbers cannot drift apart.
4. **Refuse PDF bytes** (`%PDF` prefix), as Foundation does today (`r2-objects.ts:218`, `:226`).
5. **`sha256(bytes) == ocrSha256`**, else `CORE_OCR_DIGEST_MISMATCH`. The register's acceptance
   clause sits in this step.
6. **Body parity.** Core runs the same checks Foundation runs today (`collection-compile-run.ts:208-287`),
   which mirror the worker's qualifier (`WORKER src/ocr.ts:376-396`), with one Core code per
   Foundation code. The test is one fixture per code, run on both sides.
7. **Source binding.** `inputSha256` must equal `contentSha256` and `sourceImmutableKey` must equal
   `immutableObjectKey`.
8. **Reader provenance.** `readerRevision`, `readerBindingSha256` and `recognitionConflictCount`
   must match the request (`contracts.py:101-107`, `:119-170`).

Documents are read one at a time, so memory peaks at one OCR body. The receipt gains
`ocrReads[]`: `{nativeId, objectKey, sha256, byteLength, schemaVersion}`. That shows which bytes
the World was compiled from.

### 2.3 v3-A — asynchronous dispatch, receipt, idempotent resend

**Model: a resumable compile, driven by turns, with checkpoints held by the caller.** Core keeps no
job state between calls.

1. **Each turn re-sends the same work** with a new `requestId` and timestamp, plus the checkpoints
   written so far.
2. **Core verifies every checkpoint.** It reads each one by reference, with the same reader as
   §2.2, and checks three things:
   - the MAC;
   - `content_digest() == output_digest` (`journal.py:240-241`);
   - `scope_digest` equals the scope Core derives for this request (`compiler.py:174-187`). The
     scope includes the Core release digest, so a checkpoint from another release never matches.
3. **Core compiles the next documents.** It takes them in the same sorted order the SQLite journal
   uses (`journal.py:216-217`), one fragment each, with the existing
   `compile_fragments(request, document_keys)` (`compiler.py:189-195`). Before starting another
   document it checks the time. It stops once the time left is shorter than the longest fragment it
   has computed in this call. The budget is `route.maxLatencyMs` counted from arrival. No new
   constant is introduced.
4. **Core answers.**
   - **Documents still remain:** `202` with `tavonel.product_core.compile_progress.v3`. The body
     carries `requestId`, `inputSha256`, `workSha256`, `coreReleaseDigest`, `documentsTotal`,
     `documentsCompleted`, and `issuedCheckpoints[]`. Each checkpoint has `objectKey`, `sha256` and
     the checkpoint bytes.
   - **Every fragment exists:** `200` with `compile_response.v3`. Core builds it with the existing
     `reduce_fragments` (`compiler.py:243-255`). The body has the v2 shape plus `ocrReads[]`,
     `checkpointsUsed[]` and `contractVersion`.
5. **Foundation writes each issued checkpoint before the next turn.** It writes the exact bytes
   create-once, with the same 409/412 → `exists` handling as `putWorkspaceCollectionCandidate`
   (`r2-objects.ts:255-270`). Then it checks that the sha256 of the written bytes equals the one Core
   issued. A failed write leaves progress where it was (R2 before ACK).

**Checkpoint object.** The checkpoint wraps the existing `_Fragment` encoding
(`journal.py:54-95`) as `tavonel.product_core.checkpoint.v1`. Its MAC is computed with a subkey
derived from the transport secret by HMAC over a fixed label, so no new secret is needed. The key is
deterministic, so a resend lands on the same object and a release change lands on a new one. Nothing
is ever overwritten:
`immutable/{ws}/{ws}/collections/{collectionId}/{workHex}/core-checkpoints/{releaseHex}/{sha256(connectorType + "\n" + nativeId) hex}.json`.
The checkpoints hold content derived from customer documents. The T9 code lane must add this prefix
to the deletion inventory (§1 finding 5) and to `isKeyInsideWorkspacePrefix`-style predicates
(`FND nextjs/lib/immutable-keys.ts:41-69`).

**Why this model.**

- **It reuses the algorithm the SQLite journal already runs on one host.** That algorithm is: one
  committed fragment per document, then resume, then one reduction (`journal.py:97-104`,
  `:209-240`).
- **It needs only the credential FH-18 already names.** Core stays read-only.
- **It keeps each kind of truth where the runtime invariants put it.** Workflow truth stays in
  Foundation's Postgres job row and lease. Artifact truth stays in R2.
- **It does not depend on how the platform treats a function after its response is sent.** That
  was not verified.
- **Correctness does not depend on the time check.** A call that overruns becomes `CORE_V2_TIMEOUT`.
  The only loss is the document in flight, which the next turn recomputes deterministically.

**The alternative, not chosen.** Core could hold the journal itself: a shared store implementing
`FencedCompileStore` (`fencing.py:35-62`), with Postgres holding the lease and R2 holding the
payloads. That gives Core write credentials to a store, which no register row grants. It is FS-6.

**Foundation's job worker changes in three places.**

- **A `202` is pending, not failed.** The job stays in `structuring` and records a deferral, the
  same way the reading-disagreement path does (`compile-job-worker.ts:333-382`). The bound is that
  path's existing count, `MAX_READING_DEFERRALS` (`:98`). No new number is added.
- **Authorization is checked again on every turn.** That happens before dispatch and again before
  projection (`collection-compile-run.ts:299`, `:328`, `:443`). A revoke takes effect at the next
  turn, not at the end of the compile.
- **The turn cadence.** As read, it is one advance per 5 minutes (§1 finding 3). A parked state that
  the next minute's turn may pick up would need one migration, which the founder applies (FS-8).

### 2.4 Known ceilings that v3 does not remove

- **One document per turn.** A single document whose fragment takes longer than one call's budget
  still cannot complete. Compile time against page count has not been measured
  (`ADR4`, "Compile time against page count was not measured"). If the benchmark (§4 step 3) finds
  such a document, the way out is a sub-document fragment (its own ADR, touching `compiler.py`) or
  a longer turn. Vercel Pro allows up to 800 s (`PLAN:94`), and that is a plan decision (FS-7).
- **The response stays inline.** The final `200` carries the candidate inline, as v2 does. Whatever
  bound applies to v2 responses applies unchanged. It has not been measured.
- **The Core contract caps** stay as they are: 100,000 regions per document, 100,000 pages,
  500 documents and 900,000 ms (`contracts.py:108`, `:100`, `:215`, `:199`).

## 3. Failure classes

The runtime invariants keep operational failure (infrastructure) apart from semantic failure (what
the compiler concluded). A third class, **integrity**, is kept apart from both. A retry does not fix
it, and the compiler was not wrong. It corresponds to the stop-the-line item "source or evidence
hash mismatch".

| Code (proposed unless cited)                                                                                                                                                                 | Class                                | Retry                           | Credits                | Who acts                                                  |
| -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------ | ------------------------------- | ---------------------- | --------------------------------------------------------- |
| `CORE_COMPILE_PENDING` (202)                                                                                                                                                                 | not a failure                        | next turn                       | none for this turn     | worker                                                    |
| `CORE_V2_TIMEOUT`, `CORE_V2_UNAVAILABLE` (`core-runtime-v2.ts:761`)                                                                                                                          | operational                          | yes, the same idempotent work   | none                   | worker                                                    |
| `CORE_OCR_READ_UNAVAILABLE` (R2 5xx, network, timeout)                                                                                                                                       | operational                          | yes                             | none                   | worker                                                    |
| `CORE_JOURNAL_UNAVAILABLE` (`api.py:107`)                                                                                                                                                    | operational                          | yes                             | none                   | worker                                                    |
| `FOUNDATION_CHECKPOINT_WRITE_FAILED`                                                                                                                                                         | operational                          | yes; progress does not advance  | none                   | worker                                                    |
| `CORE_OCR_CREDENTIAL_UNCONFIGURED`, `CORE_V3_DISABLED`                                                                                                                                       | operational (configuration)          | no, until configured            | none                   | operator                                                  |
| `CORE_V3_DOCUMENT_EXCEEDS_TURN` (no fragment produced after the deferral bound)                                                                                                              | operational (capacity)               | no                              | none                   | founder (FS-7)                                            |
| `CORE_REQUEST_INVALID` (`api.py:76-79`), `CORE_OCR_REFERENCE_INVALID`, `CORE_OCR_BODY_INVALID`, `CORE_OCR_REGIONS_REQUIRED`, `CORE_OCR_V3_READER_REQUIRED`, `CORE_OCR_TOO_LARGE`             | contract (input)                     | no                              | none                   | the side that built the input                             |
| `CORE_OCR_DIGEST_MISMATCH`, `CORE_OCR_SOURCE_BINDING_INVALID`, `CORE_OCR_PROVENANCE_MISMATCH`, `CORE_CHECKPOINT_INVALID` (MAC or digest), `CORE_IDEMPOTENCY_CONFLICT` (`api.py:105`, `:121`) | integrity, stop the line             | never automatically             | none                   | founder and on-call; the compile stays failed and visible |
| `CORE_OCR_OBJECT_MISSING` (404 on a recorded key)                                                                                                                                            | integrity; it may also be a deletion | no; recheck authorization first | none                   | worker, then operator                                     |
| `CORE_COMPILE_REJECTED` (`api.py:109`, `:135`); status `review_required` / `rejected` (`contracts.py:304`); `CORE_V2_REJECTED` (`collection-compile-run.ts:414`)                             | semantic                             | no                              | per today's settlement | reviewer                                                  |

Whether a failed Core compile is charged is not changed by this design. Settlement rules stay
where they are.

## 4. Ladder: compatibility contract → shadow → benchmark → canary → rollout → deprecate

No step raises an intake ceiling. Ceilings move only with the stage-1 receipt (§5) and the rule in
`FND shared/intakeCeiling.ts`.

| Step                     | What                                                                                                                                                                                                                                                                                                                                                                               | Exit (receipt)                                                                                                                                                                                                                                                | Who                                                                        | Rollback                                                                        |
| ------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------- | ------------------------------------------------------------------------------- |
| 1 Compatibility contract | **Core** (agent/* worktree): v3 models, `/v3/compile` behind `TAVONEL_CORE_V3_ENABLED` (unset → `CORE_V3_DISABLED`), the R2 reader, the checkpoint envelope. **Foundation** (branch): v3 client, the worker's pending outcome, the v3 idempotency key, the checkpoint prefix in deletion and key predicates, the 24 MiB cap in the P2-18 cross-tree test. Every flag defaults off. | The §6 tests pass, including every existing `tests/unit/test_product_core_*.py`. CI green at head. Independent reviewer, 0 blockers.                                                                                                                          | agent                                                                      | revert; nothing deployed                                                        |
| 2 Shadow                 | Core **Preview** deployment with v3 and the Preview read credential. A harness on the evaluation tenant (FH-01) runs v2 and v3 on the same inputs. A v3 result is never projected or persisted as a candidate.                                                                                                                                                                     | `CORE-V3-SHADOW-RECEIPT.json`: per pair, both `outputSha256` and the inputs. Exit count is FS-1.                                                                                                                                                              | founder-hands deploy and credential (FH-06 path, FH-18); agent harness     | unset the flag; remove the Preview credential                                   |
| 3 Benchmark              | Same-condition runs on fixtures that already have receipts: T7 SYNTHETIC 10/40/80 pages (`T7`), and the F5 60- and 73-page documents (`FIT`). The baseline is the in-process `ProductCoreCompiler.compile` on the same inputs. For documents v2 cannot carry (§1 finding 1), the comparison is v3 against the in-process compile.                                                  | `CORE-V3-BENCHMARK-RECEIPT.json`: per-document fragment seconds against pages, reduce seconds, checkpoint bytes, R2 read seconds, turns to finish. Pass when `outputSha256` is equal on every fixture and one compile longer than 52 s finishes across turns. | agent (evaluation tenant)                                                  | —                                                                               |
| 4 Canary                 | Production Core with v3 (FH-06) and the Production read credential (FH-18). Foundation `TAVONEL_CORE_V3_MODE=canary` with an allowlist in `TAVONEL_CORE_V3_CANARY_WORKSPACES`.                                                                                                                                                                                                     | The FS-2 cohort and duration, with zero integrity-class failures and no operational failure left unrecovered.                                                                                                                                                 | founder-hands Core deploy and env; Foundation by the main-merge delegation | mode unset → v2; checkpoints are additive objects, so there is no data rollback |
| 5 Rollout                | `TAVONEL_CORE_V3_MODE=on`. Core still accepts v2.                                                                                                                                                                                                                                                                                                                                  | Rollout receipt. Public copy and limit changes stay with D-29 (hold) (`REG:83`).                                                                                                                                                                              | founder-hands Core deploy; agent receipt                                   | mode back to `canary`                                                           |
| 6 Deprecate              | Remove `/v2/compile` only. v2 test fixtures stay as historical evidence.                                                                                                                                                                                                                                                                                                           | Zero v2 calls over the FS-3 window.                                                                                                                                                                                                                           | founder                                                                    | redeploy the prior Core                                                         |

Core v2 deploys from a p0p2-branch Vercel project, outside the main-merge delegation. So every Core
deploy above is founder-hands (`REG:134`, C15; `REG:65`, S6-03).

## 5. Transfers above 32 MiB — what stage 1 must measure first

**Where 32 MiB comes from.** It is Cloud Run's HTTP/1 request limit for the source → CDR POST
(`PLAN:81`, platform documentation, with 64 KiB framing at `cdr-cloudrun/app.py:659`). It is also
Core's own body cap (`api.py:22`). Under v3-R, Core's request carries references, not regions, so
Core leaves this question. The only leg that can cross 32 MiB is the source → CDR POST.

**Today's intake ceilings,** all constants: 5 MiB and 80 pages accepted
(`FND shared/intakeCeiling.ts:25`, `:27`, `:29`, `:33`, `:35`; `WORKER src/keys.ts:4`;
`cdr-cloudrun/app.py:50`, `:52`). The CDR output and the GPU input are 18 MiB
(`cdr-cloudrun/app.py:51`; `workers/foundation-ocr-gpu/app.py:24`). The worker refuses OCR results
above 80 pages, 50,000 regions or 4,000,000 characters (`WORKER src/ocr.ts:387`, `:390`, `:395`).
The database refuses more than 5,242,880 bytes (`FND supabase/migrations/0051_intake_ceiling_and_gate_evidence.sql:47`,
`:87`, `:131`).

**What T7 measured** (SYNTHETIC, internal diagnostic, not a public claim; `T7.md:8-16`):

- **Single-request mode.** A dense scan sent as one request fits 85 s (`WORKER src/ocr.ts:167`) up
  to about 30–35 pages [calc]. Warm, 10 pages took 27.8 s, 40 pages 96.2 s and 80 pages 218.5 s.
- **Range mode.** 80 pages sent in 10-page ranges took 23.8–26.4 s per request, 0 of 8 over 85 s.
  This is the mode `T5` implemented behind a flag.
- **Cold start.** Two cold requests both went unanswered on the test endpoint. This proves nothing
  about the production cold path (`T7` `notProven`).
- **CDR replica** (not the deployed service):
  - 5 MiB holds about 8 pages of 200 dpi greyscale scan;
  - the 18 MiB output holds about 43 pages, at about 431 KB per page of output;
  - A4 documents of 71–80 pages fail the pixel budget whatever their content.

**What this means.** In stage 1 the binding constraints are 5 MiB intake and 18 MiB CDR output, both
far below 32 MiB. 32 MiB is not the next wall for scans. The register defers the decision until the
stage-1 measurement (`REG:36`; `PLAN:122`, `:133`).

**What stage 1 has not measured yet.**

- range CDR (A4.2, not implemented);
- the worker isolate's memory at larger sources (`PLAN` A2 #2);
- the deployed CDR rather than a replica;
- v3-R and v3-A themselves (§4 step 3).

**When those receipts exist:**

- **Stage-1 ceiling at or below 32 MiB less 64 KiB:** no transfer above 32 MiB is needed, and the
  question closes.
- **Above that:** the founder picks HTTP/2 end to end or a read from GCS over Private Google Access
  (`PLAN:81`). That is FS-5.

## 6. Tests the T9 code lane owes, failure paths included

1. Every existing v2 test still passes, unchanged.
2. v3 inline gives the same `outputSha256` as v2 for the same documents.
3. v3-R gives the same `outputSha256` as v3 inline for the same bytes.
4. A digest mismatch gives `CORE_OCR_DIGEST_MISMATCH`. Nothing is compiled and no checkpoint is
   issued.
5. A key outside the prefix, or one that is not the sibling, gives `CORE_OCR_REFERENCE_INVALID`. A
   fake client counts zero requests.
6. An R2 5xx gives `CORE_OCR_READ_UNAVAILABLE` (retryable). A 404 gives `CORE_OCR_OBJECT_MISSING`.
   An object over 24 MiB gives `CORE_OCR_TOO_LARGE` without being fully buffered.
7. Each Foundation pre-dispatch code has its Core counterpart, both run on one fixture.
8. With a fake clock, a compile longer than one 52 s budget finishes across turns. Its output equals
   the in-process single call.
9. A resent turn produces identical checkpoint bytes. The create-once write reports `exists` and no
   duplicate appears.
10. A tampered checkpoint gives `CORE_CHECKPOINT_INVALID`. After a release change the checkpoint
    lands on a new key and is recomputed, never overwritten.
11. v2 then v3 for one binding produces two keys and no 409.
12. The flag off makes `/v3/compile` refuse, and v2 is untouched. A missing credential refuses v3-R
    while inline v3 still runs.
13. A `202` leaves the job in `structuring` with a deferral recorded, not `failed`. A revoke
    between turns stops the next turn.

## 7. Credentials

| Credential                                | State                                | Scope                                                                                                                                   | Env (named by this contract)                                                                                                                                                                                |
| ----------------------------------------- | ------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **FH-18, Core R2 read** (`REG:114`)       | founder-hands, not issued            | Cloudflare R2 API token with Object Read only, on `tavonel-saas-foundation-quarantine` only (`FND nextjs/lib/r2-synthetic-canary.ts:5`) | `TAVONEL_CORE_R2_ACCOUNT_ID`, `TAVONEL_CORE_R2_BUCKET`, `TAVONEL_CORE_R2_ACCESS_KEY_ID`, `TAVONEL_CORE_R2_SECRET_ACCESS_KEY`, on the Core v2 Vercel project: Preview at step 2 (FS-4), Production at step 4 |
| Core transport HMAC                       | exists, reused                       | —                                                                                                                                       | `TAVONEL_PRODUCT_CORE_HMAC` (Core, `__main__.py:18`), `FOUNDATION_CORE_V2_HMAC` (Foundation, `core-runtime-v2.ts:186`); the checkpoint subkey is derived, not stored                                        |
| Foundation R2 signer                      | exists, reused for checkpoint writes | Object Read & Write, this bucket (`FND docs/FOUNDATION_R2_SIGNER_TOKEN_2026-08-28.md:3`)                                                | `R2_ACCOUNT_ID`, `R2_BUCKET`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` (`r2-synthetic-canary.ts:33-40`)                                                                                                   |
| Core write credential (store or database) | **not needed** under §2.3            | —                                                                                                                                       | only if FS-6 is taken                                                                                                                                                                                       |

**The read token's scope is the whole bucket.** That includes `quarantine/` raw uploads. The
restriction to `immutable/…/ocr.json` and checkpoint keys is enforced in Core code (§2.2 step 1).
Whether R2 can scope a token to a prefix was not checked. Check it when the token is issued.

## 8. FOUNDER-SET

No value below is set by this document.

| ID   | Question                                                                                                                                         |
| ---- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| FS-1 | How many v2/v3 shadow pairs, and over what period, with zero `outputSha256` mismatches, before canary?                                           |
| FS-2 | Which workspaces form the canary beyond the evaluation tenant, and for how long before rollout?                                                  |
| FS-3 | How long must v2 traffic be zero before `/v2/compile` is removed?                                                                                |
| FS-4 | Does the Core Preview environment get the read credential for shadow? What is the rotation interval for the FH-18 token?                         |
| FS-5 | After the stage-1 receipt, and only if the ceiling it supports exceeds 32 MiB less 64 KiB: HTTP/2 end to end, or GCS over Private Google Access? |
| FS-6 | If the benchmark shows checkpoint responses too large to carry, does Core get write credentials for its own journal (§2.3, alternative)?         |
| FS-7 | If one document cannot finish in one turn: a longer turn (Vercel plan, `PLAN:94`) or a sub-document fragment ADR?                                |
| FS-8 | Is a one-minute turn cadence worth a job-store migration (§1 finding 3), applied through FH-07?                                                  |

## 9. Not verified

- Whether `TAVONEL_CORE_JOURNAL_PATH` or `TAVONEL_CORE_ALLOW_CUSTOMER_DATA` is set on the deployed
  Core, and which source it was built from beyond `SD:13`.
- Whether `FOUNDATION_COMPLETED_READ_ENABLED` is `true` on the deployed worker. Without it, no
  `ocrSha256` is recorded and v3-R routes to v2.
- Any compile time, fragment size, reduce time or R2 read time for Core. None was measured.
- Vercel's behaviour for a request or response above 4.5 MB. Not reproduced (`PLAN:92`).
- §1 finding 1 end to end: it was read, not run.
