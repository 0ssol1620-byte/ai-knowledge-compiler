# I1 — World-Semantic Live Producer Coverage

Status: **complete**. Narrowed deliverable per founder decision after I1.5's
recommendation B was approved: no longer "which backend event architecture
is canonical," only "which backend producer(s), if any, are authoritative
live inputs for each of the 8 world-semantic capabilities I1.5 approved
`ProductEvent`/`WorldProjection` to own." Written by the orchestrator from a
dispatched `researcher` agent's complete findings (no write access, same
pattern as I0/I1/I1.5/I2). Every claim tagged `observed`/`proven`/
`inferred`/`proposed`. Builds directly on
[`I1_CANONICAL_BACKEND_EVENT_RECONCILIATION.md`](I1_CANONICAL_BACKEND_EVENT_RECONCILIATION.md)
and [`I1.5_PRODUCT_READ_MODEL_RESPONSIBILITY_MAP.md`](I1.5_PRODUCT_READ_MODEL_RESPONSIBILITY_MAP.md) —
cites their settled findings rather than re-deriving them, and reports only
new grounding (mostly from `packages/cir-python/src/akc_cir/collection_events.py`,
`services/api/src/akc_api/models.py`, `services/api/src/akc_api/collection_schemas.py`
in the Security worktree, none of which prior I1/I1.5 passes opened
directly).

A missing producer is **not** permission to fabricate one in a future
adapter — every `NO PRODUCER YET` row below is a hard stop for that
capability's live wiring until a real backend producer exists.

---

## 1. discovery / source

- **Candidate producer(s)**: collection-plane discovery family
  (`collection.discovery.progress.v1`, `file.discovered.v1`,
  `file.duplicate.detected.v1`) via `_emit_collection_event()`
  (`collection_api.py`, Security/v5-cinematic/cinematic-v2 only — absent on
  `main`/product-app, reconfirming I1 §2/§4). Source provenance comes from
  the shared `Block` table (`models.py:780-805`:
  `document_id, page_id, bbox1000, polygon_norm, source_text, origin, engine, confidence`).
- **Transport**: `GET /v1/collections/{id}/events` (poll) and
  `/v1/collections/{id}/events/stream` (SSE), unconditionally mounted (I1
  §14.2). No REST endpoint for per-`Block` provenance found this session.
- **Exact available fields**: `collection.discovery.progress.v1`
  (`collection_events.py:123-131`): `collection_id, source_root_id,
  discovered_files:int, discovered_bytes:int, manifest_revision:int` —
  real field is `discovered_files`, not `files_discovered` as
  `ProductEvent`'s schema names it (independently confirmed: `grep
  discovered_files collection_events.py` → lines 127, 154). `file.duplicate.detected.v1`:
  `collection_id, duplicate_files:int, processing_credits:int`.
- **Missing fields**: `files_total` (optional in `ProductEvent`, absent in
  the real contract). `revision.family.detected.v1` and
  `document.profiled.v1` have **zero backend producer** — not in the
  `CollectionEventType` enum at all. `sourceRefLiteSchema` wants
  `document_label`, `page_number` (int), `locator`, `cell` — `Block` has
  `document_id`/`page_id` (UUIDs, not a 1-based page number) and no
  `locator`/`cell` field.
- **Safe transformation**: `discovered_files` → `filesDiscovered` (rename);
  `duplicate_files` → `duplicates`.
- **Unsafe inference**: fabricating `document_label`/`locator`/`cell` from
  `Block.bbox1000`/`polygon_norm` — no such derivation exists in code;
  `files_total` — nothing computes an expected total, only a running count.
- **Live-readiness: `PARTIAL`** — discovery counts are live-real on the
  collection plane (rename-only mapping) but only on branches other than
  `main`; two ProductEvent members have no producer at all; provenance's
  locator/cell fields are unsupported everywhere.
- **Plane**: discovery counts → collection plane. Provenance → the shared
  `Block` table, spanning both planes — argues against a single
  `CollectionWorldAdapter` owning source provenance outright.

## 2. entity / relation

- **Candidate producer(s)**: `entity.resolved.v1`/`relation.created.v1`
  (counts only, `collection_api.py:6991-7014`). **New finding**: `GET
  /collections/{collection_id}/knowledge` (`collection_api.py:7318-7326`)
  returns `CollectionKnowledgeResponse` with real per-record
  `EntityProjection`/`RelationProjection` (`collection_schemas.py:683-724`).
- **Transport**: SSE/poll for the counts event; a **separate REST poll
  endpoint** for full records — not SSE, not previously documented.
- **Exact available fields**: `EntityProjection`: `id: uuid, stable_key:
  str, entity_type: str, label: str, evidence_block_ids: list[str]`.
  `RelationProjection`: `id: uuid, document_id: uuid, subject_id: str,
  predicate: str, object_id: str, assertion_status: str, review_status:
  str, evidence_block_ids: list[str]`. Real SSE `entity.resolved.v1`
  payload (`collection_events.py:480-487`, independently confirmed via
  `grep entity_count`): only `collection_id, processing_job_id,
  entity_count:int, scope:str` — **no `entity_id` field in the contract at
  all**, confirming `ProductEvent`'s own comment that live entity
  resolution is count-only. Same shape for `relation.created.v1`.
- **Missing fields**: the SSE stream structurally cannot supply
  `entity_id`/`relation_id`/`from_entity_id`/`to_entity_id`. The poll
  endpoint *can* supply identity, but field names differ (`subject_id`/
  `object_id` vs. `ProductEvent`'s `from_entity_id`/`to_entity_id`), and
  whether `subject_id`/`object_id` always resolve to real `Entity.id`
  values was **not verified this session** — `Relation.subject_id`/
  `object_id` are `String(200)`, not FK-typed (`models.py:1473-1475`).
- **Safe transformation**: via the poll endpoint only — `id → entity_id`,
  `entity_type → entity_type`, `label → label`; `id → relation_id`,
  `predicate → predicate`.
- **Unsafe inference**: mapping `subject_id`/`object_id` straight to
  `from_entity_id`/`to_entity_id` without confirming FK validity is an
  unverified assumption, not yet safe. Deriving identity from the SSE
  count-only event would be fabrication.
- **Live-readiness: `PARTIAL`** — real per-record data exists and maps
  closely, but only through a poll endpoint the current SSE-oriented
  adapter design wasn't built to use; the SSE stream itself is structurally
  incapable of identity-level mapping.
- **Plane**: collection plane only. `main`/product-app has `Entity`/
  `Relation` tables but zero emitter and no REST endpoint found there —
  confirms I1.5's job-plane `ABSENT` finding holds even though the tables
  exist.

## 3. authority

- **Candidate producer(s)**: none for what `authority.resolved.v1` actually
  describes (multi-candidate knowledge-unit conflict resolution with a
  winner/basis/outcomes). Two *differently-scoped* concepts share the word
  "authority": `numeric.authority.verified.v1` (collection SSE, count
  only) and the `AuthorityMapping` table (`models.py:3033-3084`:
  `mapping_status` enum, `score`, `region_id`, `authority_fact_id`).
- **Transport**: `numeric.authority.verified.v1` via SSE/poll (count only).
  `AuthorityMapping` per-record data has no endpoint found — only an
  aggregate `authority_mapping_status_counts: dict[str,int]` in
  preflight/estimate responses.
- **Exact available fields**: `matched_authority_mapping_count:int`
  (independently confirmed: `grep matched_authority_mapping_count` →
  line 400); `AuthorityMapping.mapping_status/.score/.region_id/.authority_fact_id`
  (DB-only).
- **Missing fields**: `conflict_id`, `winner_unit_id`, `basis`
  (`current`/`authority`/`applicability`), `outcomes[]` with per-unit
  temporal status — none exist anywhere in either backend model.
- **Unsafe inference**: deriving a "winner"/"basis" from
  `AuthorityMapping.mapping_status` would conflate a *numeric-fact-to-
  source-region matching* problem with a *multi-candidate-knowledge-unit
  temporal-authority* problem — the same name-collision pattern I1.5
  already flagged elsewhere (§"Note on the name-collision pattern"). Must
  not be synthesized.
- **Live-readiness: `NO PRODUCER YET`**.
- **Plane**: n/a for the real capability; namesake artifacts live on the
  collection plane only.

## 4. temporal state

- **Candidate producer(s)**: none with `ACTIVE`/`SUPERSEDED`/`EXCEPTION`
  semantics at knowledge-unit granularity. Closest real analog:
  `FileVersion.status` (`models.py:3527-3574`, `CheckConstraint`:
  `candidate|active|superseded|rejected|purged`) — document/file-version-
  level, not knowledge-unit-level. `KnowledgeNote`/`Relation`/`Entity`
  carry only a boolean `is_active`, no three-state distinction, no
  `EXCEPTION` concept anywhere.
- **Transport**: `FileVersion` rows are written on upload but not emitted
  as any event and not exposed via any REST endpoint found — DB-only.
- **Exact available fields**: `FileVersion.status/.version_number/.parent_file_id/.source_sha256`.
- **Missing fields**: everything `TemporalStatus`-consuming call sites need
  (per I1.5: `ask/page.tsx:90`, `source/page.tsx:33`) — no producer ties a
  file-version state to a *knowledge-unit's* temporal applicability.
- **Unsafe inference**: mapping `FileVersion.status = "superseded"` onto a
  `TemporalStatus` for a *different entity* without a real schema link
  would fabricate a relationship that doesn't exist.
- **Live-readiness: `NO PRODUCER YET`**.
- **Plane**: n/a for the capability; `file_versions` itself is collection-
  plane-scoped.

## 5. source revision

- **Candidate producer(s)**: none for `source.revision.created.v1`'s cell-
  level edit semantics (`change_id`, `locator`, `cell`, `previous_value`,
  `new_value`). Closest real concept: `FileVersion` — a whole-file re-
  upload/version record, not a single-cell diff.
- **Transport**: none (DB-only, as above).
- **Exact available fields**: `FileVersion.version_number:int,
  .parent_file_id:uuid|None, .source_sha256:str, .status:str`.
- **Missing fields**: `change_id`, revision-level `document_id`, `locator`,
  `cell`, `previous_value`, `new_value` — zero matches for these field
  names or `source.revision.created`/`revision.family.detected` anywhere
  in `services/`. No cell-level diff granularity exists in the schema.
- **Safe transformation**: `version_number` → `revision` is a plausible
  rename *if* a producer for this were ever written — nothing produces it
  today.
- **Unsafe inference**: `previous_value`/`new_value` at cell granularity —
  no such data is captured by any table found; would have to be invented
  outright.
- **Live-readiness: `NO PRODUCER YET`**.
- **Plane**: collection plane, if this were ever built (`FileVersion` is
  `collection_id`-scoped).

## 6. change impact

- **Candidate producer(s)**: none. Grepped `services/` for
  `impact.detected`, `knowledge_units_affected`, `agent_contexts_stale`,
  `retrieval_packages_invalidated` — zero matches anywhere. No dependency-
  graph or agent-context-staleness table was found in `models.py` in the
  time available (not an exhaustive full-file read — `models.py` is large;
  flagged as not fully verified).
- **Missing fields**: all of `change_id`, `changed_unit_id`,
  `sources_changed`, `knowledge_units_affected`, `agent_contexts_stale`,
  `retrieval_packages_invalidated`.
- **Unsafe inference**: the entire payload would have to be invented. This
  is exactly the kind of capability `CLAUDE.md`'s protected-core
  dependency-graph module (`akc_cir.dependency`) implies should exist
  somewhere, but no wire-facing counterpart was found in the API layer
  this session.
- **Live-readiness: `NO PRODUCER YET`**.
- **Plane**: n/a — not found in either plane's producer inventory.

## 7. world activation

- **Candidate producer(s)**: none for the `world_state` concept itself
  (reconfirms I1 §6a — zero grep matches for `world_state`/`WorldState` in
  `services/`). Closest structural analog — **new finding**:
  `architecture.plan.compiled.v1` (collection plane,
  `collection_events.py:524-541`), carrying `entities:int, relations:int,
  knowledge_notes:int, documents:int, pages:int, verified_files:int`, plus
  a real `architecture_plan_id` and `plan_version:int`
  (`ArchitecturePlan.plan_version`, `models.py:3087-3121`, independently
  confirmed unique per `collection_id` via `uq_architecture_plan_version`).
- **Transport**: collection SSE/poll for `architecture.plan.compiled.v1`.
- **Exact available fields**: `architecture_plan_id, plan_version:int,
  integrity_sha256, verified_files:int, documents:int, pages:int,
  knowledge_notes:int, entities:int, relations:int,
  autonomously_isolated_legacy_reviews:int, credits_consumed:str,
  status:str`.
- **Missing fields**: `world_state_id` (would have to reuse
  `architecture_plan_id`, a different identity concept — a compile
  checkpoint, not a "world" snapshot); `previous_world_state_id` — no FK
  exists on `ArchitecturePlan`; only `plan_version:int` is stored, so a
  predecessor would have to be *derived* by querying `plan_version - 1`
  for the same `collection_id` rather than fabricated — a real, computable
  relationship, but not present on the wire today.
- **Safe transformation**: `entities`/`relations`/`knowledge_notes` counts
  → `worldTotals.*`, if `architecture.plan.compiled.v1` were adopted as
  this capability's producer — a real, if untested, rename.
- **Unsafe inference**: minting a `world_state_id` distinct from
  `architecture_plan_id`, or asserting `previous_world_state_id` without
  actually querying the prior `plan_version` row, would be fabrication.
- **Live-readiness: `NO PRODUCER YET`** for the `world_state` concept as
  designed (no lineage-tracking id, no "activation" semantics distinct
  from "compile completed") — the nearest analog is a genuinely different
  event with an unproven mapping, not classified `PARTIAL`.
- **Plane**: collection plane, if `architecture.plan.compiled.v1` were ever
  adopted for this purpose.

## 8. ASK / evidence

- **Candidate producer(s)**: none. Grepped `services/` for
  `answer.resolution`, `answer.emitted`, `answer.source.resolved` and
  related terms — zero matches. No QA/question-answering service,
  endpoint, or table was found in either plane in the time available.
- **Missing fields**: `question_id`, `question`, `answer`, `guarantees[]`
  (`label`/`held`/`because`), `trace[]` (≥2 steps), `source_ref` — all
  absent.
- **Unsafe inference**: the entire ASK plane would have to be invented.
  `evidence_bound: bool` (on `relation.created.v1`, `note.created.v1`) and
  `evidence_reference_kind` (on `integrity.decision.recorded.v1`) are the
  closest *adjacent* vocabulary but describe billing/compliance
  justification, not a trust-guarantee trace — the same wrong-abstraction
  pattern I1.5 already documented for `v6/event-model.ts`'s `evidenceRef`.
- **Live-readiness: `NO PRODUCER YET`**.
- **Plane**: n/a.

---

## Summary

| Capability | Status | Plane if any |
|---|---|---|
| discovery/source | `PARTIAL` | collection (discovery) + shared `Block` table (provenance) — spans both |
| entity/relation | `PARTIAL` | collection only |
| authority | `NO PRODUCER YET` | n/a (namesake artifacts on collection plane only) |
| temporal state | `NO PRODUCER YET` | n/a (namesake artifact `file_versions` on collection plane) |
| source revision | `NO PRODUCER YET` | collection, if ever built |
| change impact | `NO PRODUCER YET` | n/a |
| world activation | `NO PRODUCER YET` | collection, if `architecture.plan.compiled.v1` were adopted |
| ASK/evidence | `NO PRODUCER YET` | n/a |

**0 `LIVE SUPPORTED` / 2 `PARTIAL` / 6 `NO PRODUCER YET`.**

## Adapter-architecture implication

Every capability with any real evidence at all (discovery, entity/relation,
and the world-activation analog) is **collection-plane-scoped**, not
job-plane. Nothing found this session supports a `JobWorldEventAdapter` for
any of these 8 capabilities — the job plane (`akc_cir.events.EventType`,
`main`/product-app) has no producer for any of them; confirmed by direct
grep of its `EventType` enum (`DOCUMENT_KNOWLEDGE_NOTE_CREATED`/
`DOCUMENT_KNOWLEDGE_LINK_CREATED` exist as enum members but are never
emitted anywhere — dead code, `observed`).

The one capability that spans both planes (source provenance, via the
shared `Block` table) argues for a narrow, purpose-specific
`BlockProvenanceAdapter`-style reader rather than folding it into either a
collection or job adapter.

**This supports the founder's ruling against a monolithic `LiveEventAdapter`
— but the evidence argues for one real candidate adapter
(`CollectionWorldAdapter`, and even that only safely covers 2 of 8
capabilities today) rather than the two-plane split the ruling
anticipated. A `JobWorldEventAdapter` for these 8 world-semantic
capabilities specifically has no grounding in current code.** This is a
finding to weigh, not a decision made here.

## Not verified this session

- Whether `Relation.subject_id`/`object_id` always resolve to real
  `Entity.id` values (needed to confirm the entity/relation "safe" mapping
  is actually safe).
- Full read of `models.py` for any dependency/agent-context-staleness table
  (change impact) — only grep, not a full read of that large file.
- Whether the Product App worktree has moved past the commit checked here.
- Whether any of `event-reducer.test.ts`/`event-model.test.ts`/
  `world-projection.test.ts`/`test_collection_api.py` currently pass (I1
  §14.6's caveat still applies, unresolved here too).

## Files read (all read-only, no edits made)

`docs/integration/I1_CANONICAL_BACKEND_EVENT_RECONCILIATION.md`,
`docs/integration/I1.5_PRODUCT_READ_MODEL_RESPONSIBILITY_MAP.md`,
`apps/web/src/lib/product-event.ts`, `apps/web/src/lib/world-projection.ts`
(this worktree); `packages/cir-python/src/akc_cir/collection_events.py`,
`services/api/src/akc_api/models.py`, `services/api/src/akc_api/collection_api.py`,
`services/api/src/akc_api/collection_schemas.py` (Security worktree);
`services/api/src/akc_api/models.py`, `packages/cir-python/src/akc_cir/events.py`
(Product App worktree).
