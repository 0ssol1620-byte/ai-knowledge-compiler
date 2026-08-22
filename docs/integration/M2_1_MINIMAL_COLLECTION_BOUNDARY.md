# M2.1 — Minimal Collection Live-Slice Boundary

**Status: `M2.1 MINIMAL LIVE-SLICE BOUNDARY READY`**
Research/design only. Worktree `D:\CodexProjects\ai-knowledge-compiler-collection-minimal`,
branch `agent/tavonel-collection-minimal`, base `0d5fbc8`.

M2 answered "can the collection plane exist without Security hardening
(`0033`-`0037`)?" — yes. This document answers the narrower question the
founder posed: what is the minimum honest dependency closure L1 actually
needs, walking backward from L1's real attempted signal rather than
forward from `collection_api.py`'s full import list.

---

## Correction to the shorthand everyone (including W0) has been repeating

`Collection.manifest_revision`/`discovered_files`/`duplicate_files` was
treated as three columns on one table. Direct model inspection (orchestrator-
reconfirmed at `services/api/src/akc_api/models.py:2387-2410` and `:2685`,
worktree `D:\CodexProjects\ai-knowledge-compiler` on
`agent/folynta-trust-integration-v1`) shows:

- **`manifest_revision`** — real `Collection` column (line 2406).
- **`discovered_files`** — **not a column anywhere.** It's a payload key
  inside the durable `CollectionEvent.payload` JSON, computed as
  `len(created)` and emitted in the `file.discovered.v1` event
  (`collection_api.py:1330`, orchestrator-reconfirmed).
- **`duplicate_files`** — a real column, but on `CollectionUploadSession`
  (line 2685), a **different table**, not `Collection`.

This doesn't change L1's viability, but it changes exactly what "the data
closure" means — one column, one JSON-payload key on a separate durable
event log, and one column on a third table.

## L1's real target, re-confirmed from L1's own report

L1 (worktree `D:\CodexProjects\ai-knowledge-compiler-l1`, branch
`agent/tavonel-live-world-slice-l1`, HEAD `0d5fbc8` == its own base, clean)
never wrote code — it reported `BLOCKED` before implementing anything,
because none of the collection-plane backend exists on the I3/Product
lineage at all. This document assumes M1/P1/M2's prior finding — that the
code exists cleanly on `agent/folynta-trust-integration-v1` — and asks what
subset of it L1 would actually need if promoted.

---

## Three closures — exact file/symbol lists

### Data closure (schema truth — not narrowable below what M2 already promoted for this table family)

- Migration `0023_v4_collections.py` — creates both `collections` and
  `collection_events` tables in the same file. The discovery signal
  genuinely needs both; M2's broader 10-migration bundle also stands up
  `collection_source_roots`, `collection_upload_sessions`, and
  preflight/estimate/processing tables the discovery signal doesn't touch,
  but `0023` itself cannot be shrunk further without editing it.
- `services/api/src/akc_api/models.py` — specifically the `Collection`
  class (2387-2456) and `CollectionEvent` class (4359-4394). The file is
  imported as a whole (one SQLAlchemy declarative `Base` — architecturally
  normal, not accidental coupling; splitting it is not evidence-supported).

### Event/transport closure

- `packages/cir-python/src/akc_cir/collection_events.py` (whole file,
  1427 lines) — `CollectionEventType`, `COLLECTION_EVENT_PAYLOAD_CONTRACTS`,
  `validate_collection_event_payload`. **Self-contained**: imports only
  `.base` and `.safe_payload` within `akc_cir` — orchestrator-reconfirmed
  zero imports of `authority`/`temporal`/`dependency`/`world_state` (the
  Protected Core modules P1 separately promoted). Fully portable on its own.
- `services/api/src/akc_api/collection_api.py` — narrowly, only
  `_collection()` (431-460) and `stream_collection_events()` (5012+) are
  functionally required for the SSE transport path. `get_collection_events()`
  (4676-4763, the REST poll alternative) additionally pulls in
  `ArchitecturePlan`/`ProcessingJob`/`CollectionEventSnapshot` — unnecessary
  for a discovery-only signal, so SSE is the narrower choice.
- `services/api/src/akc_api/project_access.py` — `project_access_predicate()` only.
- `services/api/src/akc_api/database.py` — `set_rls_context`, session helpers.
- `collection.discovery.progress.v1`'s contract exists
  (`collection_events.py:123-131`) but is **never emitted anywhere** —
  orchestrator-reconfirmed zero matches for its emission in `collection_api.py`
  vs. one match for `file.discovered.v1`. Dormant contract, not evidence of
  a second working producer.

### Product normalization closure

- `apps/web/src/lib/product-event.ts` — **a real, orchestrator-reconfirmed
  field-name contract mismatch**: the backend emits `discovered_files`
  (`collection_events.py:127,154`; `collection_api.py:1330`), but the
  frontend's `fileDiscovered`/`discoveryProgress` zod schemas expect
  `files_discovered` (`product-event.ts:238,254-267`, reconfirmed directly
  in the L1 worktree). This is a schema **correction**, not new code — the
  reducer logic in `world-projection.ts`'s `reduceProductEvent` already has
  the right cases wired, just against the wrong field names.
- A new, narrow adapter (`live-collection-event-source.ts` or equivalent) —
  does not exist today (only `demo-world-source.ts`'s fixture source
  exists) — implementing `ProductEventSource` against
  `/collections/{id}/events/stream`, mapping SSE frames to `ProductEvent`
  with `scope: {kind: "collection", collection_id}`, `mode: "live"`. Small,
  genuinely new, isolated.

---

## M2's 159-file bundle — what's excludable vs. genuinely required

**Excludable for this minimal slice** (present in M2's bundle, confirmed by
reading the full bodies of `_collection()`/`stream_collection_events()`/
`get_collection_events()` — none reference these): `akc_domain_packs` + 7
domain packs, `akc_quality.{autonomous,numeric_geometry}`,
`akc_retrieval.{postgres,numeric}`, `akc_router.estimation`,
`akc_exporters.knowledge_package`, `akc_telemetry` collection metrics,
`collection_authority.py`, `collection_integrity_decisions.py`,
`collection_metadata_backfill.py`, `collection_probe.py`,
`collection_processing.py`, `collection_region_runtime.py`,
`collection_retrieval_api.py`, `collection_retrieval_runtime.py`,
`collection_semantic_runtime.py`, scheduler's `collection_finalizer`,
`generated-contracts.ts` regeneration pipeline. **Caveat**: this exclusion
only holds if the module boundary is redrawn — importing `collection_api.py`
wholesale still pulls all of this in transitively at Python import time even
though none of it is functionally exercised by the three needed functions.

**Genuinely required, unavoidable**: `collections`/`collection_events`
tables + `0023_v4_collections.py`, `Collection`/`CollectionEvent` model
classes, `akc_cir.collection_events` module, `_collection()`, one of the
two event-read endpoints (SSE preferred), `project_access_predicate`,
`set_rls_context`.

**Explicit exclusion confirmations** (per the founder's required list):
- `admin_health` — not referenced by any of the three needed functions; M2 independently confirmed the same.
- `/v1/proofs/{id}/crop` — not found anywhere in the discovery-relevant code path; needs `packages/security`, doubly confirmed unnecessary.
- Router quarantine rewrite — `akc_router` is used by preflight/estimate endpoints only, not by `_collection()`/`stream_collection_events()`/`get_collection_events()`.
- Exporter stack — used by package/export endpoints elsewhere in the file, not by discovery-read.
- Retrieval stack — used by retrieval/estimate endpoints, not by discovery-read.
- Broad Structara v4/v6 functionality — the source commit (`d7a6b30`, "complete Structara v4 and v6 platform") bundles collections/preflight/estimation/processing/packaging/export/quarantine review together; none of the non-collection pieces are touched by discovery-count read.

---

## Proposed narrow extraction (evidence-based, not diagram-driven)

The coupling between the discovery-read path and the rest of
`collection_api.py` is genuinely accidental: three functions
(`_collection()`, `stream_collection_events()`, optionally
`get_collection_events()`) live inside a 5000+-line file that imports
`akc_domain_packs`/`akc_exporters`/`akc_retrieval`/`akc_router` at module
scope for unrelated endpoints elsewhere in the same file. Verified by
reading the full bodies of the three functions, not inferred from file
organization. A narrow module (e.g. `collection_read_boundary.py`)
containing just these three functions plus their direct imports
(`Collection`, `CollectionEvent`, `Project`, `project_access_predicate`,
`set_rls_context`, `akc_cir.collection_events`) would eliminate the
transitive `akc_domain_packs`/`akc_exporters`/`akc_retrieval`/`akc_router`
import chain without losing functionality. This is a proposal for future
implementation, not something built in this research pass.

---

## Not verified this pass

- Whether `collection.discovery.progress.v1`'s dormancy reflects planned-but-
  unbuilt aggregate progress or dead code — no trace of scheduler/worker
  code for a second emitter beyond `collection_api.py`.
- Whether `0023_v4_collections.py` can be split to create only
  `collections`/`collection_events` without its other tables — file not
  read in full to check if table creation is already segmented.
- Browser-side RLS/tenant-scoping/auth-header behavior for a `text/event-stream`
  `EventSource` client — `apps/web` auth plumbing not checked for
  streaming-specific auth requirements.
- Whether `product-event.contract.test.ts` (referenced in prose in
  `product-event.ts`'s own comments and in three `docs/integration/I*.md`
  files) exists on any other branch — not found in the L1 worktree, not
  searched elsewhere.

## Contradictions / uncertainty

- The task's own framing (and W0's prior terminology) treated all three
  fields as `Collection` columns; only one is. Not a contradiction between
  sources so much as an imprecision everyone has been repeating — flagged
  per the instruction to verify rather than trust prior terminology.
- `product-event.ts`'s comments assert a pinning test measures the
  field-mismatch; that test file doesn't exist in this checkout, but the
  underlying mismatch is independently verifiable by reading the two
  schemas side by side (done here, confirmed), so the claim holds even
  though its named evidence file is absent.

**Status: `M2.1 MINIMAL LIVE-SLICE BOUNDARY READY`**
