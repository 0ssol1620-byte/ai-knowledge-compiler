# Native World artifact manifest v1 — default-off DRAFT

This additive Core-only draft reduces complete native cell facts and full CIR into
a compact CanonicalKnowledgeModel and an immutable three-artifact manifest. It is
an offline observation projection requiring independent review. It does not create
a route, authorize native processing, persist artifacts, sign a Knowledge Package,
run semantic inference, or promote a candidate.

Basis: `0ssol1620-byte/ai-knowledge-compiler` Core revision
`2cc888aed974ddc839e474a3397e86683d0e514f`. The existing native CIR/facts and
CanonicalKnowledgeModel contracts are unchanged. The verified offline inline World draft
and its bounds/integrity correction stay frozen and are not dependencies here.

## Exact file boundary

Only these three additive paths belong to this patch:

- `packages/product-core/src/akc_product_core/native_world_manifest.py`
- `tests/unit/test_product_core_native_world_manifest.py`
- `docs/integration/NATIVE_WORLD_MANIFEST_V1_DRAFT.md`

There are no changes to `/v2/compile`, its OCR regions, existing transport DTOs,
PDF citation validation, compiler construction, parser, service configuration,
feature flags, permissions, quarantine, prep writer, or Foundation persistence.
The new module is not imported by a production route. Existing OCR behavior is
outside the new branch and its bytes and signatures are untouched.

## Offline input and output contract

```python
reduce_native_manifest(
    facts_body: bytes,
    cir_package_body: bytes,
    *, core_release_digest: str,
) -> NativeManifestReduction
```

`facts_body` is the complete existing `NativeFactsDraft` JSON
(`tavonel.product_core.native_facts_draft.v1`, projection
`tavonel.native_cell_facts.v1`), including all canonical documents, source
envelopes, rows/cells, facts and evidence. `cir_package_body` is the complete
existing `CandidatePackage` JSON returned by `serialize_native_draft` for exactly
the same canonical native request. No OCR/native mixture or partial document is
accepted. `core_release_digest` is an explicitly supplied `sha256:<64 lowercase
hex>` binding; it does not prove deployment or authority.

The return value is an offline Python container with `manifest` and
`canonical_model: bytes`. It is not a wire package. The model bytes are the one
new artifact. The two input byte sequences are referenced exactly as supplied;
they are not copied into the manifest or normalized for artifact digests.

`manifest_bytes(manifest)` emits sorted-key, compact UTF-8 JSON followed by one
LF. Its schema is `tavonel.product_core.native_world_artifact_manifest.v1`; its
projection profile is `tavonel.native_cell_observation_world.refs.v1`.

The manifest has these fields (camelCase on the wire):

| Fields | Meaning |
| --- | --- |
| `schemaVersion`, `projectionVersion`, `kind` | Exact versions above; kind `native_world_artifact_manifest`. |
| `operationClass`, `status`, `approvalStatus` | Fixed `initial_compile`, `review_required`, `unbound`. |
| `candidatePromotion`, `signatureStatus` | Fixed `false`, `external_signer_required`. |
| `tenantId`, `workspaceId`, `collectionId` | Complete request scope; collection satisfies the existing StableId contract. |
| `coreReleaseDigest`, `canonicalRequestSha256` | Release and reconstructed canonical native request bindings. |
| `worldStateId`, `manifestDigest` | Deterministic identities computed below. |
| `sources` | All sources, sorted uniquely by sourceId, with nativeId, sourceId, sourceVersionId, contentSha256, cirSha256 and processingReceiptId. |
| `artifacts` | Exactly three descriptors, in order: native_facts, full_cir_package, canonical_knowledge_model. |
| `cellCount`, `knowledgeObjectCount` | Exact complete-cell/evidence and complete-model membership counts. |
| `validation`, `reviewReasons` | Source/model integrity passed; semantics unbound, equivalence not_run, workAvoidedArtifacts 0; original reasons plus NATIVE_WORLD_SEMANTICS_UNBOUND. |

`parentWorldStateId` is `None` and omitted from emitted JSON. Supplying a previous
World is rejected; incremental/replacement transitions have no contract here.
Each descriptor contains `artifactId`, `kind`, `mediaType: application/json`,
`byteLength` and `sha256`. `artifactId` equals `<kind>_<sha256 hex>`; there is no
URL, mutable object key, fabricated signature, or storage capability.

World identity is `native_refs_ws_` plus SHA-256 hex of canonical JSON of the
one-element tuple containing the manifest fields before worldStateId and
manifestDigest. `manifestDigest` is SHA-256 of canonical manifest JSON plus LF,
excluding only manifestDigest. All artifacts, sources, scope, release, request,
counts and fixed review status therefore participate in both bindings.

## Complete compact model and resolution

The model uses the existing `canonical-knowledge-1.0.0` contract. Collection,
document, block and table CKOs link the entire original source structure. Every
original cell has exactly one observation CKO linked to exactly one evidence CKO.
Ordinary literal observations are unresolved Claims; formula expressions and
source errors are unresolved Notes. All have `native_extracted` origin and retain
original SourceRefs, including native locators containing `/`, without PDF bbox.
No Entity or Relation is inferred.

Observation and evidence payloads carry `profileVersion`,
`factsArtifactSha256`, `factId` and `evidenceId`. Observations additionally carry
`observationKind`: `source_cell_value`, `formula_expression`, or `source_error`.
Literal values, number formats, sheet metadata, formulas, spans and original
cell IDs remain authoritative in the complete referenced facts/CIR. They are
not duplicated per CKO. Header bindings remain empty and original ambiguity or
inferred-header review reasons survive. The full CIR retains sheet ordering and
all source metadata; this model introduces no new sheet-parent edge contract.
Formula expressions and informational caches are never evaluated.

```python
verify_native_manifest(manifest_body: bytes, artifacts: Mapping[str, bytes])
    -> VerifiedNativeManifest
resolve_native_cell(manifest_body: bytes, artifacts: Mapping[str, bytes],
                    *, evidence_id: str) -> ResolvedNativeCell
```

The artifact mapping must contain exactly the manifest's three artifact IDs.
Verification checks actual lengths and digests, strict JSON, complete native
facts/CIR validation, reconstructed request identity and exact full-CIR package
equality. It reprojects all CKOs and requires byte-identical model and canonical
manifest output. A coherent rehash of a changed model or omitted source fails.
Resolution performs that complete verification first, refuses missing evidence,
and returns original fact, evidence, CanonicalCell and sheet metadata. It does
not return an unverified reference as a citation or invent PDF geometry.

These checks prove internal consistency, not provenance or authorization. A
caller replacing an entire self-consistent graph and its hashes is not defeated
by unsigned hashes. A future trusted caller must bind an independently approved
manifest/release/scope and verified processing receipt before accepting data.
Self-supplied booleans and receipt strings are never qualification. The offline
helpers make no provenance qualification claim and remain disconnected from
live acceptance. Production acceptance is blocked pending that reviewed gate.

## Byte and construction bounds

Existing caps are unchanged: facts and full-CIR package each at most 32 MiB,
aggregate embedded CIR at most 8 MiB, at most 16 documents and 100,000 native
cells, with existing table/grid limits enforced before nested model validation.
The new compact model has a 32 MiB cap; the small manifest has a 32 KiB cap.
Duplicate JSON properties, non-finite constants, malformed UTF-8, duplicate IDs,
wrong versions, incomplete/altered facts, malformed tables and extra fields fail.

For the new model, exact projected UTF-8 bytes include sourceRefs, links,
payloads, separators, fixed-width hashes and final LF. Complete-model admission
happens before any typed CKO or its hash is constructed. Final serialization uses a bounded
JSON chunk stream and must equal the projected byte count. Oversized data refuses;
there is no truncation, partitioning, cap increase, or metadata/value loss.

The three blobs are individually bounded separate artifacts. Their aggregate
size is not admitted as a single existing 32 MiB Knowledge Package. The manifest
cannot be submitted to the current preparation writer, which accepts the existing
two-artifact preparation purpose only. A native World writer, purpose/permission,
atomic persistence and replay remain prerequisites. Foundation must not treat
this header as a signed, self-contained downloadable Knowledge Package.

## Measured local public scale probe

The official BEA `gdp4q24-3rd.xlsx` already present in the authorized workspace
was read in place, entirely in memory: 189,584 bytes, SHA-256
`5bcd570fc51e32d715faf5de09a8df5d5a5bc1bc851f8f0940036eb7874e095e`.
The existing parser produced 21 sheets and 13,006 cells. All cell values, types,
coordinates, spans, fact/evidence IDs and original locators matched after full
manifest artifact verification and re-projection. Fixed checks passed:
Table 1 U5 `2.4`, U41 `4.8`, T5 `3.1`, Contents C1 `March 27, 2025`.
66 zero cells and 302 merged anchors survived; this workbook has no formulas.
Synthetic tests cover unevaluated formula/cache variants separately.

| Artifact | Actual canonical UTF-8 bytes including LF |
| --- | ---: |
| Complete NativeFactsDraft | 25,769,061 |
| Existing full CIR CandidatePackage | 7,741,306 |
| Compact CanonicalKnowledgeModel, 26,077 CKOs | 30,948,366 |
| New manifest | 2,536 |

The compact model fits with 2,606,066 bytes of headroom. The three separate blobs
total 64,458,733 bytes; this is not a one-package fit claim. This one workbook
result does not establish a maximum supported workbook or collection size.
The final probe took 34.797 seconds, with peak working set 613,933,056 bytes, within an
enforced 2 GiB limit on its own process. No workbook, CIR, facts or model blob was
retained on disk; only small measurements were saved. No network, provider,
formula/macro/external-link execution, live route or flag activation occurred.

## Foundation integration boundary

Focused local checks passed: 52 new manifest tests plus 52 frozen inline World
tests and 90 existing native CIR/facts tests (194 total); Ruff lint and format
checks and strict production-module mypy passed. The existing FastAPI test
client emitted one deprecation warning. Installs, full clones, dependency copies,
builds, full-repository tests, live authorization/signing/persistence/retrieval,
tenant production isolation, quarantine and provider checks were not run. No
production acceptance or repository-wide green status is claimed.

For later reviewed integration, retain both complete existing input artifacts;
store the additional model and manifest as distinct immutable artifacts. Resolve
an observation through its exact facts digest, factId and evidenceId, verify all
three blobs and complete membership, then use the original native locator and
sheet metadata. A citation adapter must support native locators without applying
PDF bbox requirements to them. Do not feed this schema to the OCR `/v2/compile`
contract, infer semantics from table labels, publish a World, or reuse preparation
permission as World authorization. Approval/signing, a native World permission
and writer, Foundation projection/persistence, and live retrieval routing require
separate review. This draft leaves all of those gates closed.
