# E0 — ASK/Evidence Capability Architecture

**Status: `E0 ASK/EVIDENCE ARCHITECTURE READY`**
Research/design only. No production implementation. No migrations. Worktree
`D:\CodexProjects\ai-knowledge-compiler-e0`, branch `agent/tavonel-e0-ask-evidence`,
base `origin/main`@`185d04b`, isolated from the parallel W1 worktree.

W0 (read-only reconciliation, `docs/integration/W0_WORLD_SEMANTIC_SOURCE_OF_TRUTH_RECONCILIATION.md`
in the Surface Integration worktree) classified ASK/evidence as the only
genuine **`S4`** capability — no complete backend capability at any layer.
This document confirms that classification independently and designs the
capability from first principles, reusing existing primitives wherever they
already exist rather than inventing parallel ones.

---

## Summary

ASK/evidence is confirmed `S4` — the ASK query path itself does not exist
anywhere in this worktree (no endpoint, no Question/Answer model, no
query-time retrieval call). But far more reusable raw material already
exists than expected:

- **`SourceRef`** (`packages/cir-python/src/akc_cir/models.py:73-96`) — the
  block/page/bbox provenance schema, independently verified present.
- **`Claim`** (`packages/cir-python/src/akc_cir/knowledge.py:39-50`) — an
  already-defined "assertion + source blocks + confidence" model, built for
  the document-compile pipeline but structurally exactly what an
  evidence-bound claim needs. Independently verified present.
- **`ConflictCandidate`** (`knowledge.py:121-135`) — a two-statement conflict
  model, `resolution: str = "unresolved"`, `requires_review: bool = True` by
  default. No automatic authority-ranking logic exists anywhere.
- **`packages/retrieval`** — a complete tenant/project-ACL-enforcing search
  engine that is **completely dormant**. Independently verified: zero
  importers anywhere in the repository outside its own package and tests.
  `InMemoryVectorStore` is explicitly marked development-only in its own
  docstring; no production vector store is wired.
- **Document version / active-state pattern** — `document.active_version`
  (independently verified at `services/api/src/akc_api/models.py:474`) plus
  `DocumentVersion.status ∈ {source_verified, processed, archived}`, and
  `archive_active_document_version()` /
  `clear_active_document_projection()` (`services/api/src/akc_api/document_versions.py:528-613`)
  which flips `is_active=False` on derived knowledge (`DocumentSemanticClassification`,
  `KnowledgeNote`, `Relation`) rather than deleting it. This is an existing,
  production pattern for temporal applicability and revision stability — it
  does not need to be reinvented.
- **ACL revoke** — `revoke_project_member()` (`project_access_api.py:279`)
  and `revoke_api_key()` deactivate immediately, with no wait on background
  reindexing — directly usable as the enforcement point for ASK's permission
  boundary.

**Important correction to the product contract's assumed depth:** native PDF
table extraction does not exist in this worktree — `pdf_parser.py` never
calls `add_table`. Table/cell coordinates only exist for (a) structured
office formats (xlsx/docx/pptx/html) as structural `native_object_id`
locations, not pixel bbox, or (b) documents that go through the OCR/vision
pipeline (`visual_gpu.py`), which does produce bbox + per-cell confidence.
"Table/cell where available" is therefore genuinely conditional on document
type — the design below does not promise uniform table/cell precision.

**Contradiction found, not resolved here:** the root `CLAUDE.md`'s Protected
Core list (`akc_cir.inspection`, `akc_cir.recovery_policy`, `akc_cir.reconciler`,
`akc_cir.identity`, `akc_cir.semantic_diff`, `akc_cir.dependency`,
`akc_cir.recompilation`, `akc_cir.world_state`) does not exist in this
worktree's `akc_cir` package. Independently verified — the actual module
list is `base, errors, events, exports, knowledge, models, normalization,
prompts, reading_order, safe_payload, schema`. This is either a
different-branch/worktree location, a renamed module set, or a
not-yet-implemented plan described as present tense. **This needs a founder
answer, not an inference** — E0's design below does not claim to reuse those
modules, and no statement here should be read as reusing them.

---

## Existing reusable primitives (verified)

| Primitive | Location | Reuse role in ASK design |
|---|---|---|
| `SourceRef` | `akc_cir/models.py:73-96` | Base of the evidence locator — unmodified |
| `BBox1000` | `akc_cir/models.py:16-32` | Normalized bbox coordinate, reused as-is |
| `CanonicalBlock`/`CanonicalTable`/`CanonicalCell` | `akc_cir/models.py:99-206` | Source of `source_refs` for any evidence locator — validators already require provenance to construct one |
| `Claim` | `akc_cir/knowledge.py:39-50` | Reused unmodified as `AskClaim`'s shape |
| `ConflictCandidate` | `akc_cir/knowledge.py:121-135` | Reused as the authority/conflict surfacing mechanism — no new ranking logic added |
| `akc_retrieval.RetrievalQuery`/`EvidenceHit`/`RetrievalService` | `packages/retrieval/src/akc_retrieval/*` | The retrieval boundary — dormant but complete; needs activation, not reinvention |
| `document.active_version` + `DocumentVersion.status` + `is_active` cascade | `services/api/src/akc_api/models.py`, `document_versions.py` | Temporal applicability and revision-stability mechanism |
| `revoke_project_member`/`revoke_api_key` | `services/api/src/akc_api/project_access_api.py`, `main.py` | Permission enforcement point, live query-time check |
| `VisualTableBlock`/`VisualSourceRef` | `services/api/src/akc_api/visual_gpu.py:49-118` | The only path that guarantees cell-level bbox + confidence today |
| `ModelRunRecord` | `akc_cir/models.py:209-235` | Existing provenance precision baseline for the "model boundary" design below |
| `deterministic_id` | `packages/native-parsers/src/akc_native_parsers/models.py:119-121` | Reused for stable locator IDs |

**Note on naming collision:** the root `CLAIM_REGISTER.yml` is a *public
marketing claims register* (unrelated concept, despite the shared word
"claim") — not to be confused with `akc_cir.knowledge.Claim` anywhere this
document or its descendants are read.

## Genuinely missing primitives

- Any Question/Answer model or endpoint.
- Any query-time retrieval invocation (embedding calls, indexing triggers —
  none exist; `akc_retrieval` has no caller).
- A validation gate that checks an LLM-produced claim's `source_block_ids`
  are actually a subset of the evidence blocks retrieval returned — nothing
  in the current codebase does this today; required new code, not reuse.
- Native PDF table extraction (a separate, out-of-scope decision — see MVP
  section).

---

## Proposed data model

Reuses `SourceRef` and `Claim` unmodified; adds three new types.

```
AskEvidenceLocator (new — wraps SourceRef with a stable identifier)
  - source_ref: SourceRef                 # reused unmodified
  - locator_id: StableId                  # deterministic_id("evloc", document_id,
                                           #   document_version_id, block_id or
                                           #   table_id/cell_id, page_index0)
  - granularity: enum(DOCUMENT | PAGE | BLOCK | TABLE | CELL)
  - content_hash: Sha256                  # snapshot of CanonicalBlock.content_hash
                                           #   at citation time

AskClaim = akc_cir.knowledge.Claim         # reused as-is, no new fields

AskAnswer (new — query-time artifact)
  - answer_id: StableId
  - question_text: str
  - world_state_ref: { document_version_id set, query timestamp }
  - claims: tuple[AskClaim, ...]
  - evidence_locators: tuple[AskEvidenceLocator, ...]
  - model_run_id: StableId                # reuses ModelRunRecord
  - tenant_id, project_ids: ACL context snapshot (audit-only, never re-exposed)
  - fail_closed: bool                     # true => claims/locators empty, answer is a refusal
```

## Query lifecycle

1. **Query boundary**: `document.active_version` by default. A caller may
   pin an explicit historical `document_version_id`; the response must then
   carry an explicit "archived version" flag (derived from
   `DocumentVersion.status`). Implicit mixing of versions is not permitted.
2. **Retrieval boundary**: uses `akc_retrieval.RetrievalQuery` as-is —
   `tenant_id` + explicit `project_ids` pre-scoping is mandatory; a request
   without `project_ids` is rejected, not defaulted to "search everything."
3. **Permission enforcement**: project membership is checked live at query
   time against the same table `revoke_project_member` writes to — not
   trusted from a potentially-stale search index. `RetrievalService`
   already re-validates candidate tenant/project on return; ASK adds no new
   trust in the index layer.
4. **Retrieval → evidence**: `EvidenceHit.evidence_block_ids` resolve to
   `CanonicalBlock.source_refs`, from which `AskEvidenceLocator`s are built.
5. **Temporal applicability**: any evidence candidate whose
   `document_version_id` is not the document's `active_version` (and wasn't
   explicitly requested) is excluded — reusing the existing `is_active`
   filtering pattern already applied to `KnowledgeNote`/`Relation`, not a
   new mechanism.
6. **Model boundary**: the frontier LLM only synthesizes the answer text
   from retrieved evidence. Retrieval, evidence-locator construction, and
   claim-to-evidence mapping are deterministic, non-LLM code. **New
   required gate**: the server must verify each claim's `source_block_ids`
   is a subset of the block IDs retrieval actually returned — this
   validation does not exist today and must be built new; nothing currently
   stops a model from citing a block it was never given.

## Evidence lifecycle

- **Citability**: `locator_id` is a deterministic hash of
  `document_id + document_version_id + block/table/cell id + page_index0`
  (reusing the existing `deterministic_id` pattern) — stable/reproducible
  given a fixed version.
- **Revision stability**: when a document recompiles into a new version,
  existing evidence locators are never deleted — they remain dereferenceable
  via their embedded `document_version_id`, but responses mark them
  "superseded" once that version's `status` becomes `archived`. No automatic
  remapping to the new version — remapping is a semantic judgment the system
  should not make silently (would violate the fail-closed-on-integrity
  principle).
- **Permission leak prevention**: public/internal DTOs are separate types.
  Public evidence responses expose only `document_id`, `page_number`,
  `bbox1000`, and a cited text snippet — never retrieval score, route
  features, cost matrix, or prompts. Every locator dereference re-checks
  project membership at call time rather than trusting a baked-in
  permission at locator-creation time.

## Failure semantics (fail-closed)

- If retrieval is unavailable (its current real production state — the
  activation preconditions for `akc_retrieval` are unmet), ASK returns "cannot
  answer with evidence" rather than falling back to unsupported model-only
  knowledge.
- If a claim's `source_block_ids` fails the subset-of-evidence check, that
  claim is dropped from the answer; if zero claims remain, the whole answer
  becomes a fail-closed refusal.

## Authority (conflicting sources)

No automatic ranking. `ConflictCandidate`'s existing default
(`resolution="unresolved"`, `requires_review=True`) is kept as-is: when two
sources answer the same question differently, both are surfaced with an
explicit "multiple sources disagree" state, never auto-resolved.

## Claim representation: compiled at query time, not stored

Recommendation: compile claims fresh per query, persisting only a minimal
audit receipt (`model_run_id`, `world_state_ref`, evidence locator list).
Reasoning: `Claim` is already pure data, cheap to recompute; querying fresh
against `active_version` avoids ever answering from a state that was current
at storage time but has since drifted; full ephemerality alone would fail
the evidence-artifact-by-sha256 requirement at audit time, so the minimal
receipt is required, not optional.

---

## MVP recommendation

Today's real extraction precision varies by document type — the MVP does
not promise uniform depth:

- Native-text PDFs: page + block bbox, no tables (none extracted today).
- Structured office documents: structural cell/table location, not pixel bbox.
- Scanned/OCR-routed documents: bbox + per-cell confidence available.

**Recommended sequence:**

1. Ship ASK at document/page-granularity evidence only. Prerequisite:
   activate `akc_retrieval` for real (fix embedding model pin, corpus
   indexing, deletion propagation, recall validation — replace
   `InMemoryVectorStore`).
2. Introduce `AskAnswer`/`AskClaim`/`AskEvidenceLocator` at document/page
   granularity, plus the new source_block_ids subset-validation gate.
3. Make the fail-closed path (no evidence → refusal) the first thing tested
   and audited — lowest risk, highest audit value, ship first.
4. Add block/table/cell-level evidence per document type in a later phase —
   the missing native-PDF table extraction is a separate decision outside
   E0's scope (either add native table parsing or force all PDFs through
   the vision pipeline).
5. Authority/conflict UI reuses `ConflictCandidate`'s existing
   unresolved+requires-review state; no auto-ranking in the MVP.

---

## Trade-secret / disclosure considerations

- `akc_retrieval`'s provider-attestation logic (reranker identity/revision
  pinning, double ACL re-validation) and its `RetrievalQuery` window
  constants (candidate_k 30-100, top_k 5-15) fall directly under
  `CLAUDE.md`'s "never expose route features, scores, thresholds, prompts,
  cost matrix" rule — a public version of this document must generalize or
  omit these numbers and the specific provider/model names (Qwen3
  Embedding/Reranker).
- The `deterministic_id` hash construction and `content_hash` computation
  are internal reproducibility mechanisms an outside party could copy
  directly — a public artifact should state the property ("locators are
  deterministically stable") without the exact hash input ordering.
- The Protected Core module-name contradiction above needs a founder
  answer before any implementation phase — this document does not resolve
  it and does not claim reuse of modules that could not be found.

---

## Confirmed not investigated (time-boxed out)

- `packages/quality/src/akc_quality/evidence.py`, `tables.py`, `numeric.py`
  — file existence noted, contents not read.
- Postgres pgvector extension/index provisioning — the "dormant" finding for
  `akc_retrieval` is based on the import graph, not storage provisioning.
- W0's primary document was not directly accessible from this isolated
  worktree; this document's summary of W0 is second-hand and should be
  cross-checked against the primary W0 artifact before being treated as
  equivalent to it.

**Status: `E0 ASK/EVIDENCE ARCHITECTURE READY`**
