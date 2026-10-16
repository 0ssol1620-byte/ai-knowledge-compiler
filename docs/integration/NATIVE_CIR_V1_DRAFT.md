# Native CIR v1 — closed Core draft

Base: `0ssol1620-byte/ai-knowledge-compiler`, PR 91,
`f62a1b4a4bfea1ac555a7ac8f43b6bfb8de648c2`.
Status: DRAFT, default closed, independent review required.

## Exact Foundation request contract

Reserved endpoint: `POST /v3/native-cir/compile`. Content is strict UTF-8 JSON;
UTF-16/32 payloads are rejected before JSON parsing, even with a valid body HMAC.
Existing `/v2/compile`, request/response v2, compiler, identity policy, journal,
PDF geometry validation and capability promotion remain unchanged.

Required top-level fields:

| Field | Contract |
|---|---|
| `schemaVersion` | exactly `tavonel.product_core.native_cir_request.v1` |
| `requestId`, `idempotencyKey` | existing Core Identifier syntax |
| `tenantId`, `workspaceId`, `collectionId` | existing Core Identifier syntax |
| `requestedAt` | timezone-aware timestamp |
| `documents` | 1–16 native envelopes; no OCR/mixed documents |

Each document requires `nativeId`, `connectorType`, `sourceId`,
`sourceVersionId`, `immutableObjectKey`, `cirObjectKey`, `contentSha256`,
`cirSha256`, `processingReceiptId`, and `canonicalDocument`. No optional client
approval/qualification flag exists. Unknown fields (including regions, OCR
keys, previous worlds, route policies and approval booleans) fail validation.

`canonicalDocument` is the **complete existing CanonicalDocument** in the exact
`model_dump(mode="json", by_alias=True, exclude_none=True)` representation;
`canonical_json` uses sorted keys, compact separators, UTF-8 Unicode and no NaN.
`cirSha256` is SHA-256 of those canonical UTF-8 bytes, prefixed `sha256:`.
Canonical defaults must be emitted; null optional fields must be omitted.
Coercions, text stripping or other normalization during validation are rejected.

This bounded producer profile is `cir-1.0.0`, structured XLSX headings/tables,
`metadata.nativeParser="akc-native-parsers"`, `nativeParserVersion="1.2.0"`.
Embedded assets, model runs and other native formats are outside this slice.
Full sheet metadata, table cells, merged spans, source value types, number
formats, formula text, raw Unicode/whitespace and all original locators survive.
Formula text is data; nothing calculates formulas, macros or external links.

Identity must match Core `source_id(tenantId, connectorType, nativeId)` and
`document_version_id(sourceId, contentSha256)`. The CIR tenant/document/version/
source digest and every nested block/table/cell SourceRef must match. IDs must
be unique, including across documents. Native locators use the existing
`xlsx/sheet/0000`, `/range/A1:B2`, `/cell/A1` forms; sheet indices, range dimensions
and cell positions must agree. No fabricated bbox, image or time geometry is
accepted. PDF validation is not changed. Table bounds/overlap/provenance and
block content hashes are validated; parent cycles and missing sheets fail.
The existing XLSX producer emits at most one canonical table per sheet. This
contract enforces that bound and requires each table's parent to be that sheet's
heading. Sheet state must be a string equal to `visible`, `hidden` or `veryHidden`;
malformed states produce the normal 422 response rather than escaping validation.

Immutable references must be:

```
immutable/{tenantId}/{workspaceId}/{uploadRevisionObjectId}/{sourceSha256Hex}/source.xlsx
immutable/{tenantId}/{workspaceId}/{uploadRevisionObjectId}/{sourceSha256Hex}/native-cir.json
```

The upload object ID may differ from the stable `nativeId`, as in v2. The keys
must share the same source directory and digest. This is reference binding,
not fetched-byte verification or proof of storage retention. `processingReceiptId`
is required provenance for future binding, **never** proof of approval.

## Authentication and actual HTTP responses

Use unchanged `sign_product_core_request`: headers
`x-tavonel-core-timestamp`, `x-tavonel-core-request-id`,
`x-tavonel-input-sha256`, `x-tavonel-core-signature`; HMAC-SHA256 signs
`timestamp + "\n" + requestId + "\n" + sha256(rawBody)` with the existing digest
prefix and 300-second maximum timestamp skew. Request ID must bind to JSON.

| Status | Actual behavior |
|---|---|
| 413 | `CORE_REQUEST_TOO_LARGE`, bounded stream before JSON parsing |
| 401 | existing transport error or `CORE_REQUEST_ID_MISMATCH` |
| 422 | `CORE_NATIVE_CIR_INVALID`, without reflecting input data |
| 403 | valid authenticated request: `CORE_NATIVE_PROCESSING_DISABLED` |

Every HTTP response uses `Cache-Control: no-store`. There is no successful HTTP
native compile, cache/journal write, route activation or flag to enable one.

The shared HMAC contract authenticates a body, not a named approved processing
caller or an intake/security approval receipt. Existing cap_v1 scopes and
runtime-qualification evidence do not supply this missing native intake binding.
Before opening this route, a separately reviewed server-side verifier must bind
caller identity, approval receipt, tenant/workspace/collection, immutable source
digest, CIR digest, producer/schema version, expiry and replay rules. It must
check immutable source/CIR bytes and revocation/security approval. Quarantine,
security integration, credentials and capability promotion are not implemented
or authorized by this draft. Foundation must keep native routing disabled.

## Offline response / package contract

`parse_native_request(bytes)` validates the envelope; `serialize_native_draft`
revalidates all nested data and returns `NativeCIRDraft`, not a v2 CandidateWorld
or semantic compile result. This explicitly uses the allowed validation/
serialization fallback until secure caller acceptance exists.

The response schema is `tavonel.product_core.native_cir_draft.v1`,
`status="review_required"`, `candidatePromotion=false`, with `requestId`,
`inputSha256` (canonical request bytes), `packageSha256`, `package` and
`reviewReasons=["NATIVE_PROCESSING_APPROVAL_UNBOUND"]`.
The package uses existing CandidatePackage/CandidatePackageFile contracts and
`signatureStatus="external_signer_required"`. It contains:

- `canonical/documents/{sourceVersionId}.json`: the entire original CIR plus LF.
- `provenance/native-cir-manifest.json`: source/CIR bindings, receipt reference,
  all document file hashes/sizes, `approvalStatus="unbound"`, promotion false.

Each file has SHA-256 of its exact UTF-8 content including LF; `packageSha256`
hashes canonical JSON of the complete CandidatePackage including the manifest.
This avoids the existing v2 package's model-only loss without changing v2 bytes.
Package signing, retrieval citations, semantic compilation and world publication
remain future work; no native citation is routed through PDF-only public DTOs.

## Limits and review boundary

32 MiB raw request (same as v2), 8 MiB aggregate canonical CIR, 16 documents,
10,000 blocks per document, 100,000 cells and occupied bounding-grid positions
per document; 100,000 aggregate cells; 512 sheets; maximum row 100,000 and column
1,024; nesting depth 32. Grid bounds are fenced **before** Pydantic expands
merged spans. Native package JSON is capped at 32 MiB; this new closed draft cap
does not raise any existing Foundation/package limit. Caller-specific existing
Foundation output limits still need independent review before routing.
No existing request, parser or package fence was lifted for BEA.

Files: new `packages/product-core/src/akc_product_core/native_cir.py`, additive
closed route in `api.py`, new `tests/unit/test_product_core_native_cir.py`, and
this document. `compiler.py`, `contracts.py`, `auth.py`, protected CIR modules,
worker/parser, Foundation and deployment configuration are unchanged.

Rollback: remove the reserved v3 route/import and new module; v2 retains the
same contracts and behavior. Independent review must approve the source patch;
this implementing session grants no approval and makes no public capability claim.
