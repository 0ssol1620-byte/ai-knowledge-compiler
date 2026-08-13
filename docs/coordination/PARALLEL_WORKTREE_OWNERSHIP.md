# Parallel worktree ownership ledger

Coordination metadata for the six active TAVONEL tracks running in parallel
worktrees as of 2026-08-13. **This is not a source of architectural truth** —
it records who is touching what, so independent tracks don't race on the same
shared file. The Director Bible, the constitution (`CLAUDE.md`), and each
track's own docs remain authoritative for content.

Maintained centrally by the orchestrating session rather than edited live by
each subagent in place, because git worktrees do not share uncommitted state
with each other — a track's own worktree is the only place it can actually
see its own edits before they're committed. Each track reports its status
and this file is updated to match.

`Cinematic V5` is listed for completeness but is **not an active track** —
read-only historical/foundation evidence, frozen unless explicitly reopened.

---

## Active tracks

| # | Track | Worktree | Branch | Base |
|---|---|---|---|---|
| 1 | Security | `D:\CodexProjects\ai-knowledge-compiler` | `agent/folynta-trust-integration-v1` | — |
| 2 | Cinematic V2 | `D:\CodexProjects\ai-knowledge-compiler-cinematic-v2` | `agent/tavonel-cinematic-v2` | `agent/tavonel-v5-cinematic` |
| 3 | Product App | `D:\CodexProjects\ai-knowledge-compiler-product-app` | `agent/tavonel-product-app` | `main` |
| 4 | Commercial Shell | `D:\CodexProjects\ai-knowledge-compiler-commercial-shell` | `agent/tavonel-commercial-shell` | `main` |
| 5 | Research/Absorption | `D:\CodexProjects\ai-knowledge-compiler-research` | `agent/tavonel-absorption-research` | — |
| 6 | IP Research | `D:\CodexProjects\ai-knowledge-compiler-ip-research` | `agent/tavonel-ip-research` | — |
| 7 | Surface Integration | `D:\CodexProjects\ai-knowledge-compiler-surface-integration` | `agent/tavonel-surface-integration` | `main` @ `7ac5098` |

**Not active** — `Cinematic V5`, `D:\CodexProjects\ai-knowledge-compiler-v5-cinematic`, `agent/tavonel-v5-cinematic`. Historical/foundation evidence only.

Surface Integration is opened narrowly for **`INTEGRATION I0 — SHARED WORLD CONTRACT PROMOTION`** only —
navigation/root-layout/app-shell integration is explicitly deferred to a later phase, not part of I0.

---

## Per-track status

### 1. Security
- **Status:** `IMPLEMENTED / AUDITED PASS — Sonnet substitute, reduced independence`. `BYPASSRLS 7/7`. `Gate 1B PENDING`. `Canary B BLOCKED`.
- **Owned paths:** `services/scheduler/`, `packages/security/`, `migrations/versions/`, `infra/postgres/`, `docs/audit/V5_GPU_ACCESS_SITE_MATRIX.md`, `docs/audit/V5_WORKER_AUTHZ_DECISION_PACKAGE.md`.
- **Read-only shared paths:** none currently at risk of collision with other tracks (no frontend/app-shell overlap).
- **Proposed shared changes:** none pending.
- **Dependencies added:** none this round.
- **Integration requirements:** none pending — this track doesn't touch the Surface Integration surfaces.
- **Merge dependency:** none.
- **Note:** no new concrete Gate 1B task has been scoped in this session (Gate 1B requires real-workload observation infrastructure, not yet defined as an actionable step). Standing permission to continue precursor work; nothing new dispatched this round pending a concrete next task.

### 2. Cinematic V2
- **Status:** `PHASE 1 NORMATIVE ACCEPTANCE PASS / FOUNDER VISUAL REVIEW REQUIRED` — **FROZEN** at commit `5a01055`. No Acts 4–9, no `/` mount, no final audit, no merge, no push until founder GO. Only founder-requested visual corrections may reopen.
- **Owned paths:** `apps/web/src/components/cinematic-v2/`, `apps/web/src/lib/cinematic/`, `apps/web/src/app/cinematic-v2/`, `docs/design/`.
- **Read-only shared paths:** `apps/web/package.json`, `apps/web/src/components/app-shell.tsx` (touched once to add the `/cinematic-v2` bare-route entry — no further edits without founder request).
- **Proposed shared changes:** none pending until Phase 2.
- **Dependencies added:** `three`, `@react-three/fiber`, `graphology`, `pixelmatch`, `pngjs` — all licensed in `DEPENDENCY_LICENSES.md` within this worktree/branch.
- **Integration requirements:** the eventual `/` mount swap is explicitly deferred to founder GO, then to Surface Integration.
- **Merge dependency:** blocked on founder GO for Phase 2, then final independent audit.

### 3. Product App
- **Status:** `P1 READY` (commit `a4828b8`, on top of preserved `0c7a94b` P0 and I0-A's `eb26ba7`/`14a05bf`). WORLD/SOURCE/CHANGE/ASK verified end-to-end through the same `WorldProjection` (CHANGE 2→5 years visibly propagates to ASK). `SAMPLE WORLD` visibly labeled on every view. Explicitly **not disturbed** by I1/I2/M0 — founder directive: does not need live backend wiring to stay READY, not rewritten around I1 before the normalization contract settles. **Frozen from further rebase until M0 concludes.**
- **Owned paths:** to be scoped further as P1 lands; expected `apps/web/src/app/app/` or equivalent existing `/app` route tree, plus any new route-local components under a scoped subdirectory.
- **Read-only shared paths (frozen this round, per founder decision):** root `package.json`, `pnpm-lock.yaml`, global/root layout, global `app-shell`, global navigation, global design-token definitions, global auth middleware, global CSP/security policy. May inspect, document, propose diffs — must not edit directly.
- **`product-event.ts` / `world-projection.ts` — `CONSUMER — NO OWNERSHIP`**, sourced from Surface Integration I0-A (`READY`) via rebase, never hand-copied. **`live-event-adapter.ts` — not consumed yet**; I0-B is `BLOCKED`, and Product App must build its `EventSource` abstraction (`DemoFixtureEventSource` now, `LiveProductEventSource` swappable in later without a workspace rewrite) so the live-adapter gap doesn't block P1.
- **Proposed shared changes:** none yet — to be produced by P1 and recorded here once real.
- **Dependencies added:** none yet. New-dependency rule: justify vs. existing stack, license-check, document, avoid duplicate-adding the same package Commercial Shell might also need (defer to Integration track if both need it and neither is blocked without it).
- **Integration requirements:** every P1 surface fed by `DemoFixtureEventSource` must be explicitly labeled `SAMPLE WORLD` (or equivalent) — never implying customer data, live processing, or real-time backend support. When I1 resolves the canonical backend event boundary and I0-B unblocks, Product App swaps in `LiveProductEventSource` behind the same `EventSource` abstraction.
- **Merge dependency:** none blocking P1 itself; live-mode wiring depends on I0-B/I1.

### 4. Commercial Shell
- **Status:** `C0 COMPLETE / C1 READY` — commit `fdce8e7` on `agent/tavonel-commercial-shell`. Not merged, not pushed.
- **C0 findings:** real login/signup/session infra already wired (`POST /v1/auth/login|register`, `GET /v1/auth/session`); real provider-optional payment/credit ledger (`payments.py`) whose UI already renders an honest "no verified payment provider" state instead of fabricating checkout; real `plan_code` tenant gating with no priced self-serve catalog; real `/v1/api-keys` backend with previously zero frontend surface; real `/v1/auth/logout` previously never called from the frontend. `/login`, `/signup` verified real, untouched. `/pricing` verified real but lives on the cinematic marketing stack — left untouched, out of this track's scope.
- **C1 built:** `/account` (server-confirmed profile, real sign-out, owner/admin-gated API key management — new frontend on an already-real backend; explicitly states profile/password editing is unsupported rather than faking a save) and `/billing` (calm wrapper on the pre-existing honest `BillingManagement` component).
- **Verification:** `tsc --noEmit` clean; `vitest run` 79/79 pass (23 files, 7 new); `lint` fails on a pre-existing environment error reproducible on unmodified `main` too (not introduced by this change, flagged not hidden); live browser check not completed (an already-running preview server belonged to a different worktree — left untouched per no-cross-worktree-touch rule).
- **Owned paths:** `apps/web/src/app/account/`, `apps/web/src/app/billing/`, `apps/web/src/components/account-page.tsx`, `apps/web/src/components/api-key-management.tsx`.
- **Read-only shared paths:** same frozen list as Product App — confirmed zero diff on `package.json`/lockfile/app-shell/root-layout/global CSS.
- **Proposed shared changes:** `docs/commercial/PROPOSED_SHARED_CHANGES.md` — wire `/account` and `/billing` into `app-shell.tsx`'s `secondaryNavigation` (frozen this round); resolve `/usage` vs `/billing` overlap (product decision, not implementation); decide whether `/pricing` should eventually move off the cinematic marketing stack to the calm register.
- **Dependencies added:** none.
- **Integration requirements:** nav wiring for `/account`/`/billing`, deferred to Surface Integration's later (not-yet-scoped) navigation phase.
- **Merge dependency:** none blocking — ready whenever a merge round is authorized.

### 5. Research/Absorption
- **Status:** continuing independently. Last closed: FIX-B-01 four-item disposition (commit `9c329e6`), all four items closed and independently verified.
- **Owned paths:** `research/`, `docs/research/`.
- **Read-only shared paths:** none at risk (no frontend overlap).
- **Standing constraints:** preserve preregistration/evidence boundaries; do not tune implementation to make G3 metrics green; do not turn experimental findings into product claims without the agreed evidence bar.

### 6. IP Research
- **Status:** continuing independently.
- **Owned paths:** `docs/ip/`.
- **Standing constraints:** focus on technical embodiments becoming clearer through product implementation; do not expose trade-secret implementation detail in public-facing artifacts; keep inventor/conception records factual; AI is not an inventor; no infringement admissions in repository materials.

### 7. Surface Integration
- **I0 split into two independent sub-results, per founder decision, because the conflict found revealed two decisions that should not couple:**

**I0-A — SHARED READ-MODEL FOUNDATION — `READY`**
- **Owned paths:** `apps/web/src/lib/product-event.ts`, `apps/web/src/lib/world-projection.ts`, their tests, `demo-event-source.ts`, `demo-workspace.ts` (explicitly synthetic-fixture category, not contract semantics).
- **Commits:** `eb26ba7` (promotion), `14a05bf` (doc-accuracy follow-up). `ProductEvent` 13/13 tests, `WorldProjection` 29/29 tests, both pass clean.
- **Source provenance (founder-verified):** `ProductEvent` entered in V5 foundation commit `270875e`; `WorldProjection` introduced there, received correctness/boundary fixes in `f042563`. Cinematic V2 inherited them as KEEP contracts with **zero diff** from V2 base `3d2cb8c` through current cinematic HEAD.
- Sufficient on its own for Product App P1 to proceed honestly in SAMPLE mode.

**I0-B — LIVE BACKEND ADAPTER — `BLOCKED — canonical backend event model unresolved`**
- **Scope:** `live-event-adapter.ts`, `live-event-adapter.test.ts`, `product-event.contract.test.ts` — deliberately left **uncommitted, untracked** in the Integration worktree. Not promoted, not shimmed.
- **Why:** written against `akc_cir.collection_events.CollectionEventType` (introduced in `d7a6b30`), which is **not an ancestor of `main`** (independently verified: `git merge-base --is-ancestor d7a6b30 7ac5098` → not-an-ancestor). `main`'s actual event producer is a different, differently-keyed module (`akc_cir.events.EventType`), and `main`'s generated `@akc/contracts` has no `CollectionEventType` export at all. 8/8 real-payload mapping tests fail with `TypeError` against `main` — the agent correctly declined to commit this as working.
- **Resolution gate:** blocked on I1 (below). Neither "promote `collection_events` to `main`" nor "rewrite the adapter against `events.EventType`" was authorized — both were explicitly rejected as premature until I1 determines which model (or which combination) is actually canonical.

**INTEGRATION I1 — CANONICAL BACKEND EVENT MODEL — `READY` (accepted, with a refinement)**
- **Core finding, accepted as `proven`:** `EventType`/`JobEvent` (job plane) and `CollectionEventType`/`CollectionEvent` (collection plane) are different abstraction planes that coexist, not competing replacements — one scheduler failure path writes both in the same commit, and a tested bridge event (`processing.source_events.bridged.v1`) summarizes `JobEvent` rows into a `CollectionEvent`. Founder rejected the old "pick one canonical enum" framing.
- **Founder refinement (I0-B reframed, not superseded-as-wrong):** I0-B is not "one blocked adapter" — it's "multiple backend planes require an explicit normalization architecture." `ProductEvent` remains the single normalization boundary: `JobEvent → JobPlaneAdapter`, `CollectionEvent → CollectionPlaneAdapter`, future planes → their own adapters, all converging into one `ProductEvent` union → one `WorldProjection`. Product UI/Cinematic must not know which backend plane produced an event except via explicit provenance/scope metadata.
- **Full artifact (historical, not rewritten):** `docs/integration/I1_CANONICAL_BACKEND_EVENT_RECONCILIATION.md`.
- **Also found:** a migration-ancestry drift (Security's `0034`→`0037` chain descends from the collection-events/V4 lineage, not from `origin/main`'s actual current head) and a `CONTRACT GENERATION GAP` (`main`'s `EventType`/`JobEvent` has no generated frontend contract at all; the frontend's `JobEventType` is hand-maintained). Both spawned their own follow-up tasks below (M0, and a `CONTRACT GENERATION GAP` note carried into I2) rather than being solved inline.

**INTEGRATION I2 — PRODUCT EVENT NORMALIZATION CONTRACT — `READY` (design only, no implementation)**
- Commit `c36bd12` (with I1's doc, previously undelivered-uncommitted). Proposes: `scope: {kind: "job"|"collection"|"demo", ...}` discriminated envelope field, orthogonal to the existing `mode`; per-scope `lastSequenceByScope` cursor map replacing the single global `lastSequence`; an additive migration path (deprecate but keep top-level `collection_id`, mirror it for collection-scope frames, never fabricate it for job-scope frames) designed not to break Product App's current `a4828b8` consumption, with the one known risk (whether Product App reads `collection_id` at the top level anywhere) flagged as unverified rather than assumed safe. Recommends extending the existing `CollectionEventType` codegen pipeline to also cover `akc_cir.events` for the `CONTRACT GENERATION GAP`.
- **Note on process:** the dispatched `researcher` agent correctly did the full analytical work but declined to write the file itself (role scope), so the orchestrator authored the document directly from its complete findings and committed it.
- Produces `docs/integration/I2_PRODUCT_EVENT_NORMALIZATION_CONTRACT.md`: a discriminated `scope.kind` contract (e.g. `job` vs `collection`, exact shape derived from I1's field matrix, not invented) replacing the current unconditional `collection_id` requirement. No adapter may synthesize a missing identity merely to satisfy validation.
- Must specify: plane discriminator, mandatory identities per plane, optional identities and why, source provenance, sequence/idempotency semantics, event-timestamp semantics, fields unsafe to infer, backend-supported vs. fixture/proposed event types, mapping loss, `WorldProjection` compatibility, and a migration/backward-compatibility strategy from the current `ProductEvent` shape.
- Also recommends where the `CONTRACT GENERATION GAP` (Python `EventType`/`JobEvent` ↔ hand-written frontend `JobEventType`) should be solved — source of truth and codegen/schema-validation approach, not another hand-maintained enum. This is separate from Product P1.
- **Design only — the new plane adapters are NOT implemented yet.** Lower priority than M0 (below); M0's DAG findings inform which backend lineage is actually converging into `main`, which the new adapters must ultimately target.

**M0 — MAINLINE AND MIGRATION ANCESTRY RECONCILIATION — `ACTIVE`, higher priority than I2**
- Read-only reconciliation, opened because `origin/main`'s real tip (`185d04b`) is ahead of the `7ac5098` base every active branch (Product/Commercial/Surface Integration) is pinned to, and Security's later migration lineage does not descend from `origin/main`'s actual `0023_trial_ingest`.
- **Three required lineage graphs:** (1) git lineage — merge-base → `origin/main` → Security → Surface Integration → Product → Commercial, identifying commits present on one line but absent on others; (2) migration lineage — `revision`→`down_revision`→head per branch, explicitly identifying the divergent `0023` revisions, the collection-events introduction, the trial-ingest migration, the `0034`–`0037` Security migrations, and cross-lineage table assumptions; (3) schema dependency lineage — per divergent migration: creates/alters/depends-on/policy-role-assumptions.
- **Decision options to evaluate, not execute:** (A) rebase Security onto latest `main` and re-author its migration lineage, (B) merge divergent migration heads with an explicit Alembic merge revision, (C) promote prerequisite collection-event migrations first then Security, (D) another minimal ordering if evidence requires it. Chosen by evidence (a fresh `empty database → alembic upgrade head` must be deterministic and truthful, single-head invariant must still hold), not by prettiest git history.
- **Required artifact:** `docs/integration/M0_MAINLINE_MIGRATION_RECONCILIATION.md`.
- **Hard constraint — no active branch rebases before M0 concludes:** Product, Commercial, Surface Integration, and Security branches stay exactly where they are. No migration renumbering, no merge migration, until M0 reports.
- **Security implication:** this migration-ancestry finding does not invalidate prior Security measurements automatically, but is a blocker for any future production/mainline merge or Canary-B production interpretation until M0 resolves it. `BYPASSRLS 7/7` / `Gate 1B PENDING` / `Canary B BLOCKED` unchanged — no role disarm while mainline ancestry is unresolved.

- **Read-only shared paths:** none beyond the promoted I0-A files — no navigation/layout/app-shell touched by I0/I1/I2/M0.
- **Dependencies added:** none. Presentation-only deps (GSAP/R3F/etc.) confirmed not dragged into the shared layer.
- **Integration requirements:** Product App already rebased onto I0-A (`a4828b8`, preserved, not disturbed). Further rebases of any active branch are frozen until M0 concludes.
- **Merge dependency:** none yet — local commits only, no merge/push. No backend migration. No adapter shim created merely to make tests green. No migration rewrite. No Canary B.

---

## Change log

- 2026-08-13 — file created. Product App and Commercial Shell worktrees added (base `main` @ `7ac5098`). Dispatching P0/C0 now.
- 2026-08-13 — Product App P0 complete (`feabbd9`), found `ProductEvent`/`LiveEventAdapter`/`WorldProjection` absent from `main` lineage, correctly stopped rather than inventing them. Founder confirmed via provenance that this is a promotion gap, not a missing-contract situation — the validated foundation exists off `main` in the V5/V2 lineage. Surface Integration worktree opened narrowly for `INTEGRATION I0` (contract promotion only, not full nav/layout integration). Product App's ownership of the three contract files reclassified `BLOCKED / READ-ONLY` → `CONSUMER — NO OWNERSHIP`.
- 2026-08-13 — Commercial Shell C0/C1 complete (`fdce8e7`), independently verified: no frozen files touched, no fabricated payment/entitlement state, 79/79 tests pass. Ready pending a merge round.
- 2026-08-13 — Surface Integration I0 in progress found a genuine semantic conflict (not yet resolved): `main`'s real backend event module is `akc_cir.events.EventType`, but the V5 `LiveEventAdapter`/tests target `akc_cir.collection_events.CollectionEventType` (introduced in `d7a6b30`, not an ancestor of `main`). Agent resumed with instructions to report this as a founder-decision point rather than resolve it unilaterally.
- 2026-08-13 — Founder split I0 into I0-A (`READY`, `ProductEvent`/`WorldProjection`, commits `eb26ba7`/`14a05bf`) and I0-B (`BLOCKED`, live adapter, gated on new I1 reconciliation task). Product App resumes P1 immediately on I0-A in SAMPLE mode via a swappable `EventSource` abstraction — does not wait on I1. Commercial Shell stays `C1 READY`, holds for integration. I1 dispatched as a research/reconciliation task, not an implementation rewrite.
- 2026-08-13 — Product App P1 complete and independently verified (`a4828b8`): WORLD/SOURCE/CHANGE/ASK share one `WorldProjection`, `SAMPLE WORLD` visibly labeled, 133/133 tests pass, zero frozen-file diff. I1 complete and independently verified: job-plane/collection-plane coexistence proven, `ProductEvent` itself flagged as the weak link (no real producer, `collection_id` structurally unsatisfiable by the job plane). Founder accepted I1's core finding, refined I0-B into a normalization-architecture problem (I2), and opened M0 (higher priority than I2) after I1 surfaced a real `origin/main`/migration-ancestry drift. All active branches frozen from further rebase until M0 concludes.
