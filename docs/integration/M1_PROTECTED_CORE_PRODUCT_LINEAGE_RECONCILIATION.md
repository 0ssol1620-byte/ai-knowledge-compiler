# M1 — Protected Core / Product Lineage Reconciliation

## 2026-08-14 CORRECTION — provenance re-verification by P1

**P1** (`agent/tavonel-protected-core-promotion`, worktree
`D:\CodexProjects\ai-knowledge-compiler-protected-core-promotion`), while
extracting the 10 domain-neutral modules this document recommends via
Option B, independently re-verified each module's introducing commit
rather than trusting this document's citation — per standing instruction
not to relay unverified provenance forward.

**What this document originally claimed** (§2, table): `identity.py`,
`inspection.py`, `recompilation.py`, `reconciler.py`, `recovery_policy.py`,
and `semantic_diff.py` all trace to `d7a6b30`, the single 495-file mixed
squash commit that also introduces the collection-plane (P2) work.

**What P1 found, checked directly:** `git diff-tree --no-commit-id
--name-only -r d7a6b30 | grep akc_cir` (against
`agent/folynta-trust-integration-v1`) shows `d7a6b30` touches only
`__init__.py`, `collection_events.py`, `events.py`, `knowledge_model.py`,
`py.typed`, `schema.py` in `akc_cir` — **none of the six** modules named
above. Each instead has its own dedicated, single-purpose introducing
commit: `identity.py` ← `3df65e8`, `inspection.py` ← `df843ed`,
`recompilation.py` ← `d7eb801` (same commit as `temporal.py`/`dependency.py`,
correctly cited elsewhere in this document), `reconciler.py` ← `06e94d4`,
`recovery_policy.py` ← `5f1c166`, `semantic_diff.py` ← `48eeb74`.

**This does not weaken this document's central finding — it strengthens
it.** None of the 10 P1 domain-neutral modules trace to the mixed
commit; their provenance is cleaner than originally reported, which is
consistent with (and reinforces) the recommendation that these 10 be
promoted as their own clean extraction (Option B), separate from the
genuinely mixed collection-plane material (Option C) and the Security
hardening/absorption material (Option D). The P1/P2/P3/P4 classification
table and the promotion recommendation are unchanged by this correction.
The original table below is preserved as written, not edited in place —
this block is the correction of record.

---

**Status: `M1 RECONCILIATION READY / FOUNDER DECISION REQUIRED`**
Research/reconciliation only. No merge, no cherry-pick, no push, no
migration, no code changes. Worktree
`D:\CodexProjects\ai-knowledge-compiler-m1`, branch
`agent/tavonel-m1-lineage-reconciliation`, base `origin/main`@`185d04b`.

Every factual claim below states the exact git ref it was checked against,
per the new worktree-scoped-verification rule — this document exists
because the previous round (W0) did not do this consistently.

---

## Correction to W0's framing, found independently during this pass

W0's summary that Protected Core Python modules are "entirely unwired" is
**only partially accurate**. Verified (`git grep`, scoped to
`services/api services/scheduler`, against `agent/folynta-trust-integration-v1`):

- **True (`OBSERVED`, zero matches):** `authority.py`, `temporal.py`,
  `dependency.py`, `world_state.py`, `identity.py`, `inspection.py`,
  `recompilation.py`, `reconciler.py`, `recovery_policy.py`,
  `semantic_diff.py` — none of these are imported by `services/api` or
  `services/scheduler`, even on the Security branch itself. They're only
  consumed by `packages/absorption`, a shadow-only research harness (its
  own README states: *"Protected Core ... is imported and called, never
  modified and never replaced"*; all `ABSORB_*` flags are false; excluded
  from wheel builds) — not a production path.
- **False as stated — `collection_events.py` is actually wired**
  (`OBSERVED`, orchestrator-reconfirmed independently): `services/api/src/akc_api/collection_api.py`
  and `models.py` import it directly, and the agent's fuller trace found
  `collection_integrity_decisions.py`, `collection_integrity_runtime.py`,
  `parallel_runtime_store.py`, `collection_semantic_runtime.py` also
  consuming its exports (`COLLECTION_EVENT_TYPES`, `validate_collection_event_payload`,
  `PageState`). This module is production-wired **on the Security branch**.

**Also found and independently reconfirmed by the orchestrator**: the root
`CLAUDE.md`'s "Protected Core" section (`OBSERVED` at line 108 in the
Security worktree) exists **only** on `agent/folynta-trust-integration-v1`
— `git show HEAD:CLAUDE.md` in this M1 worktree (`origin/main` lineage)
returns no "Protected Core" match at all. The name and the 8-module list
are a Security-branch documentary artifact; the Product lineage
(`main`/candidate/surface) has not yet documented this concept. This is
exactly the kind of ref-scoped fact this whole task exists to surface
correctly, and is itself evidence for why the earlier W0 spot-checks
produced false confidence.

---

## 1. Exact branch ancestry graph

All `OBSERVED` via `git merge-base` / `git rev-list --count`, run inside
`D:\CodexProjects\ai-knowledge-compiler-m1` (HEAD `185d04b`, no other
branch checked out — all comparisons via ref-scoped commands, no checkout
switches).

- `merge-base(origin/main, agent/folynta-trust-integration-v1)` = `185d04b`
  — Security branches directly off the main tip.
- `merge-base(origin/main, agent/tavonel-integration-candidate@0d5fbc8)` = `185d04b`.
- `merge-base(origin/main, agent/tavonel-surface-integration)` = `185d04b`.
- `merge-base(agent/folynta-trust-integration-v1, candidate)` = `185d04b`
  (same as main↔candidate) — **the I3 integration candidate contains zero
  Security-branch commits.**
- `merge-base(candidate, surface)` = `8ef8c62` — candidate and surface
  share a later common ancestor than `185d04b` (they diverge from each
  other, not from main directly).

Ahead/behind counts (`git rev-list --count`):
- `main..security` = 109, `security..main` = 0.
- `main..candidate` = 24, `candidate..main` = 0.
- `main..surface` = 12, `surface..main` = 0.
- `candidate..surface` = 2, `surface..candidate` = 14.
- `security..candidate` = 24, `candidate..security` = 109 (identical to
  `main..security`, independently confirming candidate carries zero
  Security commits).

**Graph:** `185d04b` (main tip) branches three ways — (a) Security
(`agent/folynta-trust-integration-v1`, +109 unique commits), (b) candidate
and surface, which share a later common ancestor `8ef8c62` and are
entangled with each other but carry nothing from Security.

---

## 2. File → commit provenance

All `OBSERVED` via `git log --diff-filter=A -- <path>` / `git show --stat`
against `agent/folynta-trust-integration-v1`.

| File | Introducing commit | Later modifications |
|---|---|---|
| `authority.py` | `d3a54e7` (standalone: "N17 applicability DSL and N19 injection defense") | none since |
| `temporal.py`, `dependency.py` | `d7eb801` ("dependency graph, incremental recompilation and the temporal model") | none since |
| `world_state.py` | `dba1c68` ("close the two holes the gap matrix named") | none since |
| `identity.py`, `inspection.py`, `recompilation.py`, `reconciler.py`, `recovery_policy.py`, `semantic_diff.py`, `collection_events.py`, `collection_api.py`, `collection_schemas.py`, `collection_authority.py` | `d7a6b30` ("complete Structara v4 and v6 platform" — single squash commit, 495 files, +121,191/-6,302, single parent, dated 2026-08-01) | `collection_api.py` further modified in `5aa9c33`, `c601126`, `03f6e6b` |
| `Collection.manifest_revision` field | `d7a6b30` | modified in `04c1724`, `5b06251`, `709a15f` |

`d7a6b30` is confirmed **not an ancestor** of `origin/main`, the candidate,
or surface (`git merge-base --is-ancestor d7a6b30 <ref>` → false for all
three; orchestrator independently reconfirmed against `origin/main`).

`akc_cir` package file-count comparison (`git ls-tree -r <ref> --
packages/cir-python/src/akc_cir`): 13 files on `main`/`candidate`/`surface`
(`__init__, base, errors, events, exports, knowledge, models,
normalization, prompts, py.typed, reading_order, safe_payload, schema`) vs.
28 files on Security — the 15 extra: `authority, collection_events,
dependency, entity, identity, inspection, knowledge_model, public_proof,
recompilation, reconciler, recovery_policy, semantic_diff, temporal,
trust, world_state`.

`models.py` comparison: identical blob hash across `main`/`candidate`/`surface`
(2404 lines, no `Collection` class). Security's `models.py` is a different
blob (4443 lines, `Collection`/`manifest_revision`/`discovered_files`/
`duplicate_files` present around lines 2406-2788).

---

## 3. Dependency closure

- **Reverse imports, re-verified directly** (`git grep` scoped to
  `services/api services/scheduler`, `agent/folynta-trust-integration-v1`):
  `resolve_authority`, `rank_claims`, `DependencyGraph`,
  `LogicalIdentityResolver`, `inspect_output`, `plan_recompilation`,
  `build_heading_hierarchy`, `arbitrate`, `diff_documents` — **zero uses**
  in either service directory, even on the Security branch. Orchestrator
  independently reran an equivalent grep and confirmed zero matches.
- These symbols' only consumer is `packages/absorption` (shadow-only,
  disabled by feature flag, excluded from production builds) — not present
  on `main`/`candidate`/`surface` at all.
- `collection_events.py`'s exports, by contrast, are consumed by real
  production modules on the Security branch (`collection_api.py` and
  `models.py` confirmed directly by the orchestrator; the agent's broader
  pass also found `collection_integrity_decisions.py`,
  `collection_integrity_runtime.py`, `parallel_runtime_store.py`,
  `collection_semantic_runtime.py`).
- **Generated frontend contract dependency**: `packages/contracts/src/generated-contracts.ts`
  is 111 lines on `origin/main`, 376 lines on Security — the extra content
  is machine-generated from `packages/contracts/schemas/collection-event.schema.json`
  and consumed by `apps/web/src/lib/collection-client.ts`,
  `collection-runtime-client.ts`, `v6-collection-events.ts`, and UI
  components (`collection-intake.tsx`, `collection-processing-theater.tsx`,
  `integrity-console.tsx`). None of these files exist on
  `main`/`candidate`/`surface`.
- `services/api/src/akc_api/database.py`'s `set_rls_context`/tenant
  handling is nearly identical between `origin/main` (195 lines) and
  Security (196 lines) — general tenant/RLS infrastructure already exists
  in the Product lineage; `collection_api.py` calling it is a standard
  pattern, not evidence of Security-specific coupling by itself.

---

## 4. Migration dependencies

`migrations/versions` listing (`git ls-tree -r <ref> -- migrations/versions`):
`origin/main`, candidate, and surface all share the identical 23-file list,
head `0023_trial_ingest.py`. Security adds 15 more files,
`0023_v4_collections.py` through `0037_gpu_post_claim_authorization.py`.

- `0023_v4_collections.py` contains a code comment (`OBSERVED`): *"Re-pointed
  at 0023_trial_ingest on the merge with main. Both revisions were
  originally siblings..."* — confirms this migration chain was graph-surgered
  onto `0023_trial_ingest` (already present in `185d04b`) as a single linear
  extension. Single head maintained.
- `0023_v4_collections.py` itself creates collection-scoped RLS policies
  (`ENABLE ROW LEVEL SECURITY`, `CREATE POLICY "{table}_collection_select/insert/update/delete"`)
  — standard per-table RLS for new tables, not an experimental
  Security-only policy.
- `0033_backfill_checkpoint_tenant_rls.py` and `0034_dual_plane_authorization.py`
  explicitly implement the `BYPASSRLS` 7-role state, tenant-scoped
  RESTRICTIVE policies, and dual-plane (worker/human) authorization —
  matching the session's known "canary B disarm"/"claim broker" work.
- **Introducing-commit split** (`git log --diff-filter=A`): `0023`–`0032`
  all trace to `d7a6b30` (the single product-feature squash commit).
  `0033`–`0037` trace to five separate, explicitly `feat(security):`-tagged
  commits (`ccbcd0b`, `c8de965`, `e170608`, `52189e2`, `4d214cc`). There is
  a clean commit-message boundary between the two groups.

---

## 5. Security coupling matrix / 6. P1–P4 classification

| Target | Introducing commit | Reverse import (services/api or scheduler) | RLS/schema coupling | Frontend contract coupling | Tests | Classification |
|---|---|---|---|---|---|---|
| `authority.py` | `d3a54e7` | 0 | none — pure domain logic | none | `test_authority.py` (324 lines, exists) | **P1** |
| `temporal.py`, `dependency.py` | `d7eb801` | 0 | none | none | `test_temporal.py` (309 lines), `test_dependency.py` (315 lines) | **P1** |
| `world_state.py` | `dba1c68` | 0 | none — pure domain | none | `test_world_state.py` (513 lines) | **P1** |
| `identity.py`, `inspection.py`, `recompilation.py`, `reconciler.py`, `recovery_policy.py`, `semantic_diff.py` | `d7a6b30` | 0 in services; consumed only by shadow-only `packages/absorption` | none | none | 300-560 line unit tests each, exist | **P1** |
| `collection_events.py` | `d7a6b30` | **Yes — real production wiring** | payload/data-contract validation only, not RLS itself | linked via `collection-event.schema.json` | `test_collection_api.py` etc. exist | **P2** — the contract shape is domain-neutral, but the surrounding Collection pipeline is tightly coupled |
| `Collection`/`CollectionSourceRoot` fields, `collection_api.py`, `collection_schemas.py`, migrations `0023`–`0032` | `d7a6b30` | tightly coupled to each other | **RLS policies embedded directly in the migrations** | `generated-contracts.ts` (376 lines) + multiple UI components | `test_collection_api.py`, `test_collection_authority.py` | **P2** — real domain feature, but schema+RLS+frontend contract must travel together |
| Migrations `0033`–`0037` (tenant RLS backfill, dual-plane, claim broker) | `ccbcd0b`, `c8de965`, `e170608`, `52189e2`, `4d214cc` | Security-only workflow | inseparable from `BYPASSRLS` 7-role state | none | Security's own tests only | **P3** |
| `packages/absorption` (entire package) | post-`d7a6b30`, multiple commits | research/challenger consumer only, no production path | none | none | own tests exist, shadow-only | **P4** |
| Root `CLAUDE.md` "Protected Core" section | Security-only | — documentation, not code | — | — | — | **P3 / documentary coupling** — names a concept the Product lineage has not yet documented |

## 7. Test evidence

All target unit test files (`test_authority.py`, `test_temporal.py`,
`test_dependency.py`, `test_world_state.py`, and equivalents for the
`d7a6b30` group) are confirmed **present** on `agent/folynta-trust-integration-v1`
via `git show <ref>:<path> | wc -l` (300-560 lines each). **Not executed
this pass** — existence confirmed, pass/fail status is `UNKNOWN`, out of
this read-only reconciliation's scope. Executing them (with a clear
worktree/branch/HEAD header per the new verification rule) should be a
precondition before any implementation phase treats them as passing.

---

## 8. Minimal promotion options — evidence-backed recommendation

**Option A (promote a clean existing commit sequence as-is) is ruled
out.** Nearly every target file traces to `d7a6b30`, a single 495-file,
121k-line squash commit that mixes P1 domain-neutral modules, P2
collection-plane (schema+RLS+frontend coupled), and adjacent Security
work in one commit. There is no existing clean sequence to promote
wholesale.

**No single option applies uniformly — the evidence supports different
options for different groups:**

- **P1 domain modules (`authority`, `temporal`, `dependency`,
  `world_state`, `identity`, `inspection`, `recompilation`, `reconciler`,
  `recovery_policy`, `semantic_diff`) → Option B (extract into a dedicated
  promotion branch).** These have zero reverse imports from
  `services/api`/`services/scheduler` even on the Security branch itself,
  no migration dependency (none of these modules reference any migration
  or DB table), and pure-domain unit tests with no DB/RLS imports observed.
  Structurally, extracting these specific files into a clean promotion
  branch (not the whole `d7a6b30` commit) is well-supported by the
  evidence — they were never coupled to anything Security-specific to
  begin with.
- **P2 collection-plane (`collection_events.py`, `Collection` model
  fields, `collection_api.py`/`collection_schemas.py`, migrations
  `0023`-`0032`, `generated-contracts.ts`) → Option C (keep Security-owned
  for now, explicit upstream dependency/rebase plan).** This is real,
  non-artificial coupling — RLS policies are embedded directly in the
  migrations, and the generated frontend contract wires multiple live UI
  components to this exact schema. Separating file-by-file would strip out
  the RLS enforcement or the frontend contract generation, which would be
  worse than the current state, not better. Whether this coupling is
  temporary is not something this reconciliation pass can determine —
  that's a founder call.
- **P3 (Security hardening migrations `0033`-`0037`, the `BYPASSRLS`/
  dual-plane/claim-broker work) and P4 (`packages/absorption`) → Option D
  (do not promote yet).** P3 is structurally inseparable from the current
  `BYPASSRLS 7/7`/`Gate 1B PENDING`/`Canary B BLOCKED` state, which this
  reconciliation is explicitly instructed not to touch or reinterpret. P4
  is shadow-only research infrastructure with no production consumer
  anywhere — not ready, and not blocking anything either.

**This combined recommendation is the founder decision point** — this
document does not choose a single path and does not authorize any
promotion implementation.

---

## Not verified this pass

- Whether the identified unit tests actually pass (existence only,
  execution out of scope for a read-only reconciliation).
- Detailed code review of `packages/absorption`'s `AlignmentAwareResolver`
  and its actual compliance with any identity-scheme contract — README
  level only.
- Full diff content of the candidate/surface branches' own 24/12 unique
  commits — ancestry and file-existence only, not reviewed line-by-line.
- How dependent `scripts/generate_contract_types.py` is on Security-only
  schema sources — script itself not read.

**Status: `M1 RECONCILIATION READY / FOUNDER DECISION REQUIRED`**
No merge, no cherry-pick, no push, no migration, no L1 resume authorized
by this document.
