# Native coordinate facts v1 — offline DRAFT

Repository: `0ssol1620-byte/ai-knowledge-compiler`; exact PR91 base
`f62a1b4a4bfea1ac555a7ac8f43b6bfb8de648c2`. Apply after the frozen
`native-cir-v1-DRAFT-review-fix-1.patch` (SHA256
`042f9f70ca6141e00da78c27e200398c33c87748af8f9a878f81bccb8e46340d`).
Independent review is required. This additive slice has no HTTP integration.

## Foundation handoff and file boundary

```python
from akc_product_core.native_cir import parse_native_request
from akc_product_core.native_facts import project_native_facts, NativeFactsDraft
from akc_cir.base import canonical_json

request = parse_native_request(native_request_bytes)
draft = project_native_facts(request)
sidecar_bytes = canonical_json(draft).encode("utf-8")
restored = NativeFactsDraft.model_validate_json(sidecar_bytes)
```

The input is exactly the frozen `NativeCIRRequest` contract described in
`NATIVE_CIR_V1_DRAFT.md`, including all document CIR and provenance references.
The entry point reserializes and fully revalidates the request, even if an
in-memory model or nested metadata was mutated after initial validation.
Caller-supplied approval booleans remain rejected. Processing receipt IDs
are retained references; they do not qualify the caller or approve processing.

New production code is confined to
`packages/product-core/src/akc_product_core/native_facts.py`; the other two
new files are the focused test module and this contract. The frozen validator,
API, semantic compiler, journal, package writer and CandidateWorld are unchanged.
There are no parser, network, provider, filesystem or evaluation calls in this
projection. Foundation must not route live requests to it or treat it as an
approved processing path. The reserved signed HTTP route still returns 403
`CORE_NATIVE_PROCESSING_DISABLED`; `/v2/compile` remains unchanged.

## Exact serialized output

`NativeFactsDraft` uses the existing strict CIR `ContractModel` and camelCase
JSON aliases. Unknown fields are rejected. Its required output fields are:

| Field | Meaning |
|---|---|
| `schemaVersion` | `tavonel.product_core.native_facts_draft.v1` |
| `projectionVersion` | `tavonel.native_cell_facts.v1` |
| `status` | `review_required` |
| `approvalStatus` | `unbound` |
| `candidatePromotion` | literal `false` |
| `requestId`, `idempotencyKey`, `requestedAt` | original request values |
| `inputSha256` | `sha256:` digest of canonical validated request UTF-8 bytes |
| `tenantId`, `workspaceId`, `collectionId` | bound original scopes |
| `inputDocumentOrder` | original request document version IDs in input order |
| `canonicalDocuments` | complete original CIR, ordered by source ID |
| `documents` | provenance envelopes and projected tables, ordered by source ID |
| `evidence` | one original-locator evidence record per original cell |
| `reviewReasons` | sorted, deterministic reason strings |

Each document retains `nativeId`, `connectorType`, `sourceId`, `sourceVersionId`,
`immutableObjectKey`, `cirObjectKey`, `contentSha256`, `cirSha256`, and
`processingReceiptId`. Its `tables` retain `tableId`, `blockId`,
`blockContentSha256`, original range `sourceRefs`, `producerHeaderRowCount`,
`headerStatus`, empty `headerBindings`, `reviewReasons` and ordered `rows`.
Rows retain `rowIndex0`, `absoluteRow1`, and ordered original `cells`.

Each cell fact retains `factId`, `evidenceId`, original `cellId`,
`nativeAddress`, `absoluteRow1`, relative `rowIndex0`/`columnIndex0`,
`rowSpan`/`columnSpan`, optional original `valueType`, verbatim `rawText` and
`normalizedText`, and a discriminated `observation`:

```json
{"kind":"source_cell_value","value":"0"}
```

Ordinary observations use the exact original raw string; numeric zero is
retained and no numeric extraction or semantic assertion is made.

```json
{"kind":"formula_expression","evaluated":false,
 "expressionStatus":"available","expression":"=1+2",
 "cachedTextInformational":"0"}
```

Any formula field or formula quality flag selects `formula_expression`, never
an observed numeric value. Original formula text is retained when available;
otherwise `expressionStatus` is `unavailable` and `expression` is absent when
serialized with `exclude_none=True`. Optional cached text is informational only.
There is no computed result, including for cached zero, and no formula execution.

Each evidence record retains `evidenceId`, `factId`, `documentId`,
`documentVersionId`, `cirSha256`, original `cellId`, `tableId`, `blockId`,
`blockContentSha256`, and all original cell `sourceRefs`. No PDF geometry is
invented. Full CIR separately preserves sheet metadata, formula flags, formats
and every other original field.

## Unresolved headers, identity and bounds

Producer header counts are copied without promotion. Zero or inferred header
counts stay `unknown`; explicit labels remain unproven. Explicit duplicate,
blank or merged header candidates are marked `ambiguous`. `headerBindings` is
always empty. Headers never suppress original cells or infer column meaning.
Only original cells and populated rows are emitted: merged anchors appear once,
with their spans, and covered/absent cells and rows are never synthesized.

Table ordering uses original sheet index, block order and ID; cells use original
relative row, column and ID. Fact/evidence identifiers are SHA256-derived from
projection version, scopes, document/version and CIR digests, block/table/cell
identity and complete original locators. Equal text at different coordinates
has distinct evidence. The canonical input digest also binds original document
order through `inputDocumentOrder`.

Deserializing a draft reconstructs and revalidates the full input envelope,
checks its digest, recomputes the projection, and requires exact equality.
Duplicate or dangling evidence/facts, altered values, locators, scopes, version
or digest, extra bindings and missing/duplicate CIR documents fail validation.
This is integrity binding to the supplied CIR, not authenticated approval.

All frozen request/CIR/table/cell bounds still apply. Serialized canonical draft
output is separately capped at 32 MiB; it includes full CIR, facts and evidence.
No existing request or package limit is raised. Facts remain a separate offline
sidecar: the frozen hashed package already includes complete document CIR;
this patch does not silently add the sidecar to that package or enable download
through HTTP. A later reviewed packaging change must bind any sidecar bytes.

Root reasons always include `NATIVE_PROCESSING_APPROVAL_UNBOUND` and
`NATIVE_TABLE_SEMANTICS_UNRESOLVED`. Table reasons include
`NATIVE_HEADERS_UNVERIFIED`, and applicable undeclared/inferred/ambiguous header
or unevaluated/unavailable formula reasons.

## Evidence and remaining boundary

The focused run passed 101 tests: 38 coordinate-facts tests, 52 frozen native
validator/package tests, 5 Product-Core API tests and 6 existing bridge tests.
Ruff and strict mypy passed for the additive source. Fixtures come from the
existing XLSX parser and cover normal, merged, Unicode, zero, duplicate header,
locator and formula cases, plus deterministic mutation rejection.

The new BEA projection rerun is UNRUN: this slice prohibits network access and
the prior workbook/CIR was retained only in memory. Prior parser/package
evidence (21 sheets, 13,006 cells) is not evidence for this new projection.
An existing local hash-verified workbook or complete CIR is needed to measure
the draft size and verify all BEA facts/locators without lifting limits.
