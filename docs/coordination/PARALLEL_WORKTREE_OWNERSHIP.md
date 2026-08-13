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
- **Status:** `P0 COMPLETE (commit feabbd9) / P1 BLOCKED pending Surface Integration I0`. P0 correctly identified that `ProductEvent`/`LiveEventAdapter`/`WorldProjection` do not exist anywhere on `main` lineage and stopped rather than inventing or duplicating them — this is now resolved as a promotion task (see Surface Integration below), not a Product App scoping error.
- **Owned paths:** to be scoped further once P1 resumes; expected `apps/web/src/app/app/` or equivalent existing `/app` route tree, plus any new route-local components under a scoped subdirectory.
- **Read-only shared paths (frozen this round, per founder decision):** root `package.json`, `pnpm-lock.yaml`, global/root layout, global `app-shell`, global navigation, global design-token definitions, global auth middleware, global CSP/security policy. May inspect, document, propose diffs — must not edit directly.
- **`product-event.ts` / `live-event-adapter.ts` / `world-projection.ts` — reclassified from `BLOCKED / READ-ONLY` to `CONSUMER — NO OWNERSHIP`.** Owned by Surface Integration once I0 lands; Product App consumes via rebase onto the I0 foundation commit, never by hand-copying the files.
- **Proposed shared changes:** none yet — to be produced by P0/P1 and recorded here once real.
- **Dependencies added:** none yet. New-dependency rule: justify vs. existing stack, license-check, document, avoid duplicate-adding the same package Commercial Shell might also need (defer to Integration track if both need it and neither is blocked without it).
- **Integration requirements:** blocked on Surface Integration I0 (shared world contract promotion). Once I0 lands, Product App rebases onto it (preserving `feabbd9`) and P1 resumes automatically.
- **Merge dependency:** P1 completion depends on I0 landing first.

### 4. Commercial Shell
- **Status:** dispatching now — C0 bounded inventory → C1 honest route-local implementation.
- **Owned paths:** to be scoped by C0 audit; expected `/login`, `/signup`, `/pricing`, `/billing` (or canonical existing route), `/account`.
- **Read-only shared paths:** same frozen list as Product App.
- **Proposed shared changes:** none yet.
- **Dependencies added:** none yet. Same new-dependency rule as Product App.
- **Integration requirements:** TBD.
- **Merge dependency:** none yet.

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
- **Status:** opened narrowly, `INTEGRATION I0 — SHARED WORLD CONTRACT PROMOTION` dispatching now. Navigation/root-layout/app-shell integration (the originally-planned broader scope) is explicitly deferred to a later phase — not part of I0.
- **Owned paths:** `apps/web/src/lib/product-event.ts`, `apps/web/src/lib/live-event-adapter.ts`, `apps/web/src/lib/world-projection.ts`, and their contract/unit tests, once promoted.
- **Source provenance (founder-verified):** `ProductEvent` entered in V5 foundation commit `270875e`; `LiveEventAdapter`/`WorldProjection` introduced there, received correctness/boundary fixes in `f042563`. Cinematic V2 inherited them as KEEP contracts with **zero diff** from V2 base `3d2cb8c` through current cinematic HEAD (independently confirmed: `git diff 3d2cb8c HEAD -- <those three files>` in the cinematic-v2 worktree is empty).
- **Promotion method:** one clean I0 foundation commit bringing across only the neutral chain (the three files + tests), never the full `270875e` commit or any cinematic presentation code (`CameraDirector`, `VisualCue`, GSAP/R3F components, `event-labels.ts`).
- **Read-only shared paths:** none beyond the promoted files themselves — I0 does not touch navigation/layout/app-shell.
- **Proposed shared changes:** the promotion itself, tracked in I0's own commit; any semantic conflict between the V5/V2 contract and current backend/main behavior is grounds to stop and report rather than silently reconcile.
- **Dependencies added:** TBD — report presentation-only deps (GSAP/R3F/etc.) must NOT be dragged in as a side effect of promoting the contract layer.
- **Integration requirements:** Product App rebases onto the I0 commit once landed (never hand-copies the files). Cinematic V2 stays untouched — its copies already match the promoted baseline; ancestry reconciliation is deferred.
- **Merge dependency:** none yet — local commit only, no merge/push.

---

## Change log

- 2026-08-13 — file created. Product App and Commercial Shell worktrees added (base `main` @ `7ac5098`). Dispatching P0/C0 now.
- 2026-08-13 — Product App P0 complete (`feabbd9`), found `ProductEvent`/`LiveEventAdapter`/`WorldProjection` absent from `main` lineage, correctly stopped rather than inventing them. Founder confirmed via provenance that this is a promotion gap, not a missing-contract situation — the validated foundation exists off `main` in the V5/V2 lineage. Surface Integration worktree opened narrowly for `INTEGRATION I0` (contract promotion only, not full nav/layout integration). Product App's ownership of the three contract files reclassified `BLOCKED / READ-ONLY` → `CONSUMER — NO OWNERSHIP`.
