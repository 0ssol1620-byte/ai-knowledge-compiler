# ADR-007: Universal Source Front-End and Capability Manifest

- Status: Proposed — founder decisions resolved 2026-09-06
- Date: 2026-09-06
- Owners: Core, Product Platform, Security
- Source: `D:\TAVONEL_PRODUCTION_GRADE_UNIVERSAL_SOURCE_KNOWLEDGE_COMPILER_MASTER_BLUEPRINT_2026-09-06.md` §0, §5–§12,
  §16, §22, §48, §62, §66; the verified seam map `D:\CodexProjects\uskc-lanes\P0_SEAM_MAP_2026-09-06.md`

## Context

The compile contract between the product and the core is already source-centric (`CompileJobEnvelope.source`
carries `sourceId`, `sourceVersionId`, an immutable object key and a SHA-256), but everything below it is a
document/PDF/OCR pipeline:

- The site accepts eleven MIME types, hard-coded in five mutually inconsistent places
  (`shared/qualifiedDocumentInputs.ts`, its byte-duplicate `nextjs/lib/qualified-input.ts`, the workspace `accept`
  attribute, `pipeline-board.tsx`'s rejection copy, the homepage list). Content disarm converts every accepted Office,
  ODF and image input to a PDF before anything reads it (`shared/documentProcessing.ts` requires
  `outputMimeType === "application/pdf"`), so a spreadsheet's cells and formulas never reach the compiler as cells and
  formulas. The blueprint's §0.4 rule — native first, visual second, reconcile — is inverted by construction.
- Evidence is one flat model, `SourceRef` (`akc_cir/models.py`), shaped for pages and bounding boxes, embedded by value
  in blocks, cells, tables, knowledge objects and exporters, and digested into `CanonicalKnowledgeObject.hash`.
- There is no reader abstraction: two disjoint entry points (`parse_pdf_to_cir`, `parse_non_pdf_to_cir`) dispatched on
  a filename extension; the only registry pattern in the repo (`akc_router.providers.ProviderRegistry`) serves the
  GPU OCR/VLM router.
- `approved_customer_data` exists as a type but is an unconditional refusal with no enumerated preconditions, and the
  live request builder hard-codes `foundation_synthetic_only`.
- There is no `document_versions` table; every re-upload is a new `documents` row; object keys carry no tenant segment.

The blueprint's thesis is that the moat is compiler semantics (identity, typed change, evidence lineage, verified
selective recompilation), and that the input layer must be generalised so every source family enters the same
lifecycle. This record decides the six foundations of that generalisation (blueprint §66) and the honesty rules that
govern how they are described.

## Decision

1. **Source domain.** `Source`, `SourceVersion` and `SourceRepresentation` (`tavonel.source.v2`,
   `tavonel.source_version.v2`, `tavonel.source_representation.v1`) become the product's storage vocabulary, additive
   to `documents`. In this phase `sourceId = documents.id`, one version per row, no `parentVersionId`; same-logical-
   source detection is a later product decision. Every derived artifact (normalized PDF, OCR JSON, canonical IR) is a
   representation with `derivedFrom` lineage inside one source version and a `lossy` flag. The original representation
   is never rewritten. Object keys follow the live workspace-scoped layout; no tenant segment is invented.
2. **ReaderProvider plane.** Readers are plug-ins behind a `ReaderProvider` protocol and a `ReaderRegistry`
   (`akc_readers`) that resolves by declared capability — MIME pattern, source family, feature list — never by provider
   or model name; every entry pins a revision and a runtime digest; every call yields a run receipt with a frozen
   `FailureClass`. The current PDF/OCR path is the first provider, wrapped unchanged and labelled for what it does. The
   registry is a new layer above the router's `ProviderRegistry`, read-only toward it.
3. **Capability Manifest.** One typed manifest (`tavonel.capability_manifest.v1`) is the single source of truth for what
   the deployment reads. The upload whitelist, the `/sources` page, `/api/v1/capabilities`, the docs and the upload UI
   derive from it. A `VERIFIED_NATIVE` or `VERIFIED_HYBRID` status requires a qualification receipt (sha256 of a
   committed §27 suite result) and a date; without both the ceiling is `BEST_EFFORT`. Unlisted formats are
   `UNSUPPORTED` and refused. The first manifest therefore has no VERIFIED entry, and Office/ODF entries carry
   `converted_to_pdf_before_reading`.
4. **EvidenceLocator v2.** A discriminated union (`tavonel.evidence_locator.v2`: pdf, image, docx, xlsx, pptx, email,
   json, xml, code, cad, media, database, api) is added as a **sibling** of `SourceRef`, never a replacement; the legacy
   page + bbox1000 is exactly the `pdf` variant through a lossless adapter. A locator that does not resolve against its
   representation is `Unresolved`, and knowledge citing it is not promotable. Protected Core modules are not modified;
   non-paginated anchors get their own id function in the new module.
5. **Customer-data gate.** `approved_customer_data` is accepted only with a `CustomerDataGateDecision` whose seventeen
   named preconditions are all satisfied with evidence and whose tenant and workspace match the envelope. Without a
   decision the envelope validator's behaviour is unchanged. The live request builder keeps its `foundation_synthetic_only`
   literal. `activationPolicy.customerData.enabled` is `false`. Enabling it is a founder action outside any agent's
   authority. Derived knowledge is never more permissive than the intersection of its governing source ACLs.
6. **Honesty of description.** The website, the API and the workspace read the same manifest and the same claim-state
   vocabulary. No public surface says "supports every file", "100% accurate", "never hallucinates", "perfect parsing",
   "best OCR", "never stale", "always current" or "industry-leading" without evidence. A tier, a receipt or a count that
   would have to be typed by hand is shown as absent with a reason.

## Consequences

- Adding a source family becomes: implement a `ReaderProvider`, run the §27 qualification suite, commit the receipt,
  add the manifest entry. No website edit, no upload-whitelist edit.
- The legacy PDF/OCR path is not "fixed" by this record; it is named honestly. Native readers for XLSX/DOCX/PPTX (P1)
  and any change to the CDR "PDF out" contract are separate decisions.
- Existing hashes (`CanonicalKnowledgeObject.hash`, `RetrievalUnit.contentDigest`) are untouched because the union is a
  sibling and the site-side serializer is deferred.
- Two migrations (0049 source domain, 0050 customer-data gate/ACL) are additive; nothing in `documents` is dropped or
  renamed; legacy ids resolve through the adapter.
- Every threshold and every tier remains `IMPLEMENTED_NOT_PROVEN` until a corpus-backed receipt exists
  (`docs/audit/V4_MIGRATION_MATRIX.md` vocabulary).

## Founder resolutions folded into this record (2026-09-06)

The open list in `FOUNDER_DECISIONS_2026-09-06.md` (kept as history) was resolved by the founder the same day; the
binding text is `USKC_FOUNDER_DECISIONS_RESOLVED_2026-09-06.md`. The resolutions that change or sharpen the decision
above:

- **Source lineage (B-1).** `sourceId = documents.id`, one version per row, is a compatibility shim, not the canonical
  semantics. Canonical is `Source → many SourceVersion`, built in P1-A from connector stable object ids, canonical
  URIs / provider keys and explicit replace operations, with lineage evidence. A filename alone never identifies the
  same Source; when identity is undecidable the result is a new Source or an unresolved identity, never a guess.
- **Tenant ≠ Workspace (B-2).** Tenant is the organization / security / billing / policy boundary; Workspace is the
  working knowledge boundary. The new types carry both ids as distinct fields and columns; neither is derived from the
  other. Today's workspace-only object keys are not migrated here; a v2 key layout is its own migration and ADR.
- **Original vs. normalized (B-8).** The pre-CDR bytes are the immutable `original` where retained — encrypted,
  isolated, non-executable, policy-controlled, access-audited. The CDR-sanitized PDF is `normalized`, never `original`.
  If retention deletes the original, its digest, tombstone and provenance remain and the Source's reprocessing
  capability is recorded as reduced.
- **Audit table (B-6).** `enterprise_audit_events` is the canonical log for customer source/data security events;
  `foundation_developer_audit_events` stays for developer/API/configuration acts. No third table.
- **Customer data (B-10).** Stays off. The gate is per tenant + workspace so that, once every precondition has
  evidence, allowlisted beta tenants can be enabled first; global availability is a separate later decision.
- **Connector qualification blocker (B-7).** Google Drive's `trashed = false` query yields no tombstone; this is a
  production blocker, not an accepted limitation. Tombstone, delete, permission-change and move/rename semantics must be
  implemented and verified before any connector is `VERIFIED`.
- **Reader plane dependency (Lane C, conflict C-1).** `akc_readers` imports the `FailureCode` enum from
  `akc_cir.inspection` read-only, so the failure-class mapping cannot drift from the Protected Core's list. This is the
  one permitted core dependency of the reader plane; nothing in Protected Core is called, subclassed or modified. The
  Reader Registry and the router's `ProviderRegistry` stay separate abstractions (B-4); the router's registry is not
  subclassed because it resolves by provider name and by GPU route.
- **Anchor identity (Lane E).** Two anchor-id functions exist by design: `identity.evidence_id()` (Protected Core,
  page-based) stays authoritative for every paginated locator — the `pdf` variant's anchor **is** the legacy evidence
  id, or the adapter is not lossless; `locator_anchor_id()` (new module, path-based) serves the non-paginated variants.
  The locator's `locatorKind` decides which function applies; a source is never indexed under both for the same unit.
  `sourceVersionId == document_version_id` is the interim alias of the B-1 shim. `PdfLocator.to_legacy(*, document_id)`
  takes the document id explicitly because the frozen locator schema carries none (contract amendment C-E-1). Whether
  a resolved excerpt (≤ 2,000 characters of customer content) may ever be persisted or displayed is decided at P1-C,
  before the site serializer exists; in P0 excerpts live only in memory.
- **`FailureClass` in two packages (Lanes C and E).** `akc_cir` must not import from `akc_readers` (the reader plane
  sits above the compiler core), so both packages transliterate the frozen list and each carries a test that pins it to
  `enums.v1.json`; integration adds one cross-check test so the two enums cannot drift apart.
- **Gate events and organizations (Lane F).** `enterprise_audit_events.organization_id` is `NOT NULL` and references
  `enterprise_organizations`, so a workspace with no organization row cannot record a gate event and therefore cannot be
  approved for customer data. That is the intended fail-closed direction and follows from B-2 (Tenant = organization).
  The live compile request still sets `tenantId = workspaceId` and the envelope key check only agrees with the live
  `immutable/<workspaceId>/<workspaceId>/` layout because of it; this conflation is recorded, not fixed, in P0 and is the
  first item of the v2 key-layout ADR. Microsoft Graph scopes (`Files.Read.All`, `Sites.Read.All`) are tenant-wide and
  are narrowed in P2 connector work, not here.
- **Adapter signature (Lane AB, C-AB-1).** `documentToSource(document, observed: SourceObservation)` replaces the
  contract's one-argument form: `DocumentMetadata` carries no byte length, timestamps or immutable key, and the adapter
  is pure, so those values are passed in rather than invented.
- **Public wording (A-1, A-2, A-3, A-4, A-6).** Handled by Lane G after Lane D: hero "Your AI needs more than
  searchable files. It needs a current, traceable world."; evidence wording "Every compiled fact stays traceable to its
  exact source location." with per-source examples and no implied unqualified locators; `/sources` in primary
  navigation; homepage connectors restructured by status (qualified / beta / enterprise-assisted / unsupported) and
  only where code-backed; `/trust` evidence links; `/status` with no blank value.
- **Third-party components (C-1…C-7).** PyMuPDF not adopted; MinerU **not excluded** — its current code licence is
  re-pinned as a receipt at the exact revision (the earlier register row's AGPL premise is corrected there); HWP v5
  `REVIEW_REQUIRED`, `pyhwp` not used, `python-hwpx` is the HWPX candidate pending qualification; no ODA purchase;
  NeMo Retriever reference-only; Unstructured hosted API not used; Google Document AI reference/fallback with a dated
  price receipt.

## Compliance

Lanes AB, C, D, E, F of `USKC_LANE_CONTRACT_2026-09-06.md` implement this record. Frozen artifacts:
`contract/enums.v1.json` (sha256 3c668dc9…), `contract/evidence-locator.v2.schema.json` (13608314…),
`contract/capability-manifest.v1.schema.json` (4795fe89…).

Landed in this repository on `agent/uskc-integration` (2026-09-06), core lanes C and E only:

| Frozen artifact | Committed copies in this repo | sha256 |
|---|---|---|
| `enums.v1.json` | `packages/readers/src/akc_readers/contract/enums.v1.json`, `packages/contracts/schemas/uskc-enums.v1.json` | `3c668dc9…f11d1` |
| `evidence-locator.v2.schema.json` | `packages/readers/src/akc_readers/contract/evidence-locator.v2.schema.json`, `packages/contracts/schemas/evidence-locator.v2.schema.json` | `13608314…4f8ff9c6` |

Both pairs are byte-identical to the frozen originals and to each other; each package carries a test that pins the
digest, so the two copies cannot drift. `capability-manifest.v1.schema.json` belongs to lane D and lives in the site
repository; nothing in this repository consumes it yet.

The lanes' own reports are `docs/uskc/USKC_LANE_REPORT_C.md` and `docs/uskc/USKC_LANE_REPORT_E.md`; the integration
record is `docs/uskc/USKC_INTEGRATION_REPORT_CORE.md`. Every module this record adds is `IMPLEMENTED_NOT_PROVEN`
(`docs/audit/V4_MIGRATION_MATRIX.md`): no §27 qualification receipt exists, so no capability is `VERIFIED_*`, and
nothing here is wired into the live compile path.
