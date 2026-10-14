# G1-11 producer: hook contract and source review status

Parent independently reviewed corrected producer SHA-256 `45b79076d347c97b8a400a0e1af7a54b94bf6ecd1713f7ce6747fb7ff991ef44`: all four prior findings are structurally resolved, with no new blocking regression. The optional joined-harness source connection and new synthetic connection contracts are now completed; final scenario/harness successor review remains **PENDING**. The hook intentionally attempts only the `normal` and `failed` inputs; the other five members and complete per-file monitoring remain explicit gaps. This is not completion of all seven runtime inputs. Actual runtime is **NOT_RUN** and whole-G1 acceptance is **UNKNOWN**. This documentation correction preserves every code/test source and the frozen successor packet. The parent alone publishes, integrates and operates.

## Provenance

Starting packet: interrupted Library file `libfile_8c4034361f4481918de09776bdebc669`, version 0, ZIP SHA-256 `95fc01e87083ae35eed414aa8420249ba72cf2a2a2106d512c306786537d3e53`. Preserved corrected producer SHA-256: `45b79076d347c97b8a400a0e1af7a54b94bf6ecd1713f7ce6747fb7ff991ef44`.

Core base is private tree `2b9dfca13ab38fddc3d8360757b5e03f2700a184`. Parent-reconstructed original three-path producer candidate is private tree `316ed07289df04cdf4d6c977a99f51724e68a7ff`, with original producer SHA-256 `1b4dd91043371b16764938a0a194f923177c2579c1a6c9d07a571c4ec9ccdc4c`. Original joined-harness SHA-256 is `7fc33d7b21ced931b6fcad5cf4d1fc8d59375f35a9841b78f4a91ca192340910`. Tree IDs establish no published or runtime commit.

Foundation is **private final44 overlay tree** `5018218e4da424ddf22f5cb1f824a27b4a9e6b0d`, **based on public commit** `f89074fd68406654e44e570d2823ae3a4da9cb24`. The public commit's actual tree is `55a0137121854566c2ffd3260818375bc48eb09c`. Earlier five-file matches and current seven-source matches bind selected bytes only; they cannot equate whole private/public trees.

`g1-11-harness-connection-source-binding.json` lists seven exact-overlay inputs: `nextjs/lib/compile-job-authority.ts`, `nextjs/lib/intake-approval.ts`, `nextjs/lib/usage-pricing.ts`, `nextjs/lib/intake-triage-rollout.ts`, `nextjs/app/api/v1/uploads/triage/receipt/route.ts`, `nextjs/app/api/uploads/capability/route.ts`, and `quarantine-sidecar/foundation-cdr-worker/src/sanitize.ts`. Its runtime pair is **NOT_BOUND**. These hashes are source provenance, not execution evidence.

## Retained validation

`selected-check-receipt.json` records **11/11 PASS** for the new producer correction contracts and successful producer syntax checking. The coordinator accidentally ran the same eleven synthetic cases twice. The parent verified only the second retained raw result: exit 0, eleven distinct contracts passed. First raw stdout was overwritten and is unverifiable; second stdout/stderr were retained and script indentation corrected without another execution. This is not 22 distinct checks, and no old 21-test pass applies to current modified bytes. These are structural checks only. The modified legacy 21-test fixtures/title remain **UNRUN**; prior completed checks were not repeated. This documentation author ran no tests. `REVIEW.md` records exact retained receipt hashes.

The interruption/static receipt's unchanged original harness, mismatched draft scenario and unauthored connection contracts are historical evidence. The completed offline successor is Library `libfile_9df5ea2cea4c8191889a64a891713692` v0, ZIP SHA-256 `c180876a73c3759b90e100bb0b1969057d429481c3dfdf66d82c2a4f8d7129ad`. Its harness SHA-256 is `493683356c7a0a46dfde39cab64377c103ead76809de3b5349b76a05559666c7`, scenario SHA-256 is `9a87a68b7f943245f86bb9ee88b99b25f0bc6382e493600a523022b083c3c652`, and final new connection-test SHA-256 is `7ab34bc0a7b4615e1ffc71eee179da04c5e30630e46ebe7c4e745e09c897bd63`. The first run covered 19 distinct new contracts: 18 PASS and 1 FAIL. One test-only negative mock source ID was corrected, then only that failed contract passed in a selected run. Thus 19 distinct contracts have coverage; there was no final full-file 19/19 rerun. Both final code modules passed syntax checks. These are `SYNTHETIC_CONTRACT_TEST` results, separate from the retained producer eleven; neither set establishes actual runtime success. Independent parent successor review remains pending.

## Constructor and observation contract

Use `createRuntimeProducer({evidence_kind, members, execution_binding})`. Evidence kind is fixed at construction to `RUNTIME_RECEIPT` or `SYNTHETIC_CONTRACT_TEST`; synthetic data cannot be upgraded. Seven member bindings copy `id`, `source_id`, `source_version`, `source_sha256`, `acl_scope`, and `authority_binding: null | {principal_ref_sha256, workspace_key, acl_scope}`. Fixture `expected` is never read. The copied/frozen authority binding is a caller mapping assertion, not a grant or authenticated proof, and its ACL scope must equal the owner label.

Execution binding `{run_id, foundation_commit, core_commit}` is immutable at construction (run ID at most 512 characters; commits 40 lowercase hex). Null/absent binding permits only no-observation NOT_RUN. Recorders reject unbound runs; optional `produce(bindings)` must match exactly and cannot relabel a journal.

Every observation requires `context: {principalRef, workspaceKey, aclScope}`. Principal references are immediately SHA-256 hashed over UTF-8 bytes. Before apply, every touched member's authority must match hashed principal, workspace and exact ACL scope. Request-level observations must match at least one bound member and cannot become per-file facts. Separate ACL scopes need separate observations.

Methods: `recordMapping`, `recordQuote`, `recordApproval`, `recordConfirm`, `recordTriage`, `recordQualification`, `recordAccessDecision`, `recordCdrOcr`, `recordCompile`, `recordSettlement`, `recordEffect`, `produce`. Each recorder uses its method-specific camelCase fields; there is no `recordUpload`. `produce()` returns `{runtimeResults, sidecar}`.

## Hook obligations

These describe the required evidence contract. The optional call path now invokes the actual scenario and producer APIs, records actual replies for the two selected inputs, and persists a PARTIAL checkpoint and producer pair before ledger success. The source includes checks for the independent candidate `manifestDigest`, job digest and verified receipt digest. These connections have scoped synthetic contract evidence; actual product execution has not occurred. The following obligations remain necessary for any runtime projection, including the five unattempted members.

| Boundary | Required evidence | Limit |
| --- | --- | --- |
| Fixture load | Frozen manifest `runtime_status`, `files`, `relative_path`, `byte_length`, `declared_mime_type` and owner identity fields. | Do not substitute draft `runtime/members/path/bytes` schema or expected outcomes. |
| Identity mapping | Explicit member-to-`fileKey`/content-hash mapping through `recordMapping`, then actual `documentId` when observed. | Upload/confirm alone does not establish mapping. |
| Quote/approval/confirm/capability | Actual statuses, codes and per-file reply fields through the respective methods. | Request-level failures do not establish per-file facts. |
| External ACL | `recordAccessDecision` with mapped `fileKey`, `boundary: external_authorization`, matching principal/context, actual `allowed/denied`, status and reason. | Every projection needs actual per-member access. Whole-request 403, authority assertion and triage ACL hash are insufficient. |
| Triage | Actual product scope, revision, ACL observations and choices. | Supplied rollout is off; no missing receipt may be invented. |
| CDR/OCR/compile | Actual stage replies, job `documentIds`, candidate `sourceDocuments`, separate job/candidate manifest digests and `receiptVerification`. | Candidate document/version set must be unique and exactly cover the actual job; versions match sanitized observations. Record failures only when returned. |
| Settlement | Actual final row; positive settled credits establish `charged: true`. | Reserved/released-zero rows do not prove no charge. |
| Effects | Actual activity evidence or available complete per-file monitoring claim. | Global counters and missing calls cannot establish false effects. |

## Scoped false effects

A false `content_read`, `transferred`, `processed` or `charged` requires caller-supplied `monitoring.complete: true`, an exact scope and `monitoring.receiptSha256`. Whitelisted scope fields must equal the constructor run/head pair, member/file mapping, fixture labels, hashed principal, workspace and effect:

`run_id`, `foundation_commit`, `core_commit`, `id`, `file_key`, `source_id`, `source_version`, `source_sha256`, `acl_scope`, `principal_ref_sha256`, `workspace_key`, `effect`.

The receipt must equal `monitoringReceiptSha256(scope)`: SHA-256 hex over UTF-8 canonical `{complete: true, scope}` containing exactly those string fields, with sorted object keys and JSON value encoding. Wrong scope/digest is rejected before apply. Anyone can compute the digest. It **binds caller-supplied data only**, authenticates no monitor, proves no completeness and proves no effects were absent.

The actual harness has **no complete per-file monitor**. Do not fabricate `complete: true`, false effects or receipts from refusal, missing calls, no observed activity or workspace-global counters. Missing effect evidence leaves members unprojected/PARTIAL.

## Output and evidence limits

No accepted observation yields NOT_RUN, empty dispositions and null `run_id`, `foundation_commit`, `core_commit`, `stage_receipt_sha256`. With observations, structural COMPLETED requires all seven projected members and no rejections; otherwise status is PARTIAL. Every projection needs authority, actual per-member ACL and other required facts/effects. The producer never emits FAILED. Conflicting terminal results stay unprojected without invented precedence.

Journal/member digests include immutable execution binding, owner/authority bindings and validated hashed contexts. They authenticate no observation. The sidecar keeps `observations_authenticated: false`, `actual_runtime_pass_claimed: false`, `qualification: NOT_CUSTOMER_QUALIFIED`, `whole_G1_acceptance: UNKNOWN`.

Extra `authorization`, `uploadUrl`, `documentText` fields are ignored; `principalRef` is hashed; rejection errors omit input values. Allowed generic `code`, `reasonCode`, `basis`, `fileKey`, `documentId`, `run_id` fields can retain URLs or tokens. This narrow whitelist provides **no general redaction** guarantee. Triage product identities remain separate from owner labels; triage `workspaceKey` is retained but not compared with context `workspaceKey`.

Offline hook/connection source and scoped synthetic contract evidence are completed as recorded above; final independent exact-base scenario/harness successor parent review remains pending. Any future actual run needs an authorized target/budget, exact run/head pair, real available per-member ACL decisions, actual triage receipts and per-file effect evidence. Existing viewer ACL code requires an authenticated native/provider principal and source binding. Existing triage routes return `INTAKE_TRIAGE_DISABLED` while the code-owned rollout is false. No complete per-file effect monitor is connected. No runtime, whole-G1 or customer admission follows from this source or synthetic checks.
