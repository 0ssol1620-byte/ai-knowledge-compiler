# Product App — Current State and V2 Delta

Status: **P0 complete. P1 not started — blocked, see "Blocker" below.**
Scope: `apps/web/src` under the `/app/*` product namespace and its supporting
libs, as they exist on `agent/tavonel-product-app` at base commit `7ac5098`
(worktree: `D:\CodexProjects\ai-knowledge-compiler-product-app`).

This document is the honest current-state map requested for Phase P0. It does
not propose future design beyond what P1 needed, per `CLAUDE.md`'s rule that
current-state documents are baselines, not designs.

---

## 1. Method

Read directly, not from memory: every file under `apps/web/src/app/app/**`,
`apps/web/src/components/**` referenced from the product namespace, and the
supporting `apps/web/src/lib/**` modules. Cross-checked route inventory
against `PAGE_MANIFEST.yml`. Searched the whole repository (`apps`, `services`,
`packages`, `workers`, `docs`) for `ProductEvent`, `LiveEventAdapter`,
`WorldProjection`, `cinematic`, `WorldGraph`, `EventAdapter`, `Projection`.

## 2. Route inventory — `/app/*` product namespace

The entire namespace is served by **one catch-all route**:
`apps/web/src/app/app/[[...slug]]/page.tsx` → `StructaraAppPage`
(`apps/web/src/components/structara-app-page.tsx`, 966 lines). It switches on
the URL's first path segment and renders one of several inline sub-views, all
in a single file. `PAGE_MANIFEST.yml` lists the intended route surface:

```
/app/home
/app/projects
/app/projects/:projectId/{overview,documents,knowledge,graph,exports}
/app/jobs
/app/knowledge-bases
/app/benchmarks
/app/recipes
/app/exports
/app/api
/app/usage
/app/billing
/app/settings/{members,security,retention,integrations,notifications}
/app/admin/{jobs,workers,tenants,costs,incidents,audit}
```

**None of these render real data.** `StructaraAppPage` is a static sample
workspace: every button/input in it carries `disabled` plus
`title="Interactive controls require a connected workspace."` (or the
knowledge-studio equivalent), and every row of data (`projectRows`, `jobRows`,
`specializedSpecs`, the knowledge graph node list, etc.) is a hardcoded
literal array in the component file. There is no `fetch`, no `useQuery`, no
SSE subscription anywhere in this file. It is presentation-only marketing
scaffolding wearing app chrome — closer to a mockup screenshot than a working
page.

Two files outside this catch-all route *are* real, live-data components,
but neither is wired into the `/app/*` route tree today:
- `components/dashboard-live.tsx` — real `useQuery` against `/v1/dashboard`,
  proper loading/error states, feeds `WorkspaceDashboard`.
- `components/knowledge-studio.tsx` — real "no live base selected" honest
  empty state (no fabricated counts), but every interactive control is
  `disabled` the same way, and `NEXT_PUBLIC_AKC_DEMO_MODE` gates a demo
  layout that itself renders nothing populated in the excerpt reviewed.

## 3. What exists elsewhere in the app (outside `/app/*`) that is real

These are not under the `/app/*` namespace but are the strongest real
building blocks in the repo for document/evidence/change work:

| File | What it is |
|---|---|
| `lib/types.ts` | Real domain types: `CanonicalBlock`, `SourceRef` (document_id, page, bbox1000, sha256), `JobEvent`/`JobEventType` (22 real event names), `LiveJobState`, `ReviewItem`, `ProjectSummary`. This is a genuine provenance/evidence data model — not synthetic UI dressing. |
| `lib/event-reducer.ts` | Real, tested (`event-reducer.test.ts`) ordered-event reducer over `JobEvent` streams: sequence gap detection, replay buffering, block patch accumulation, stage-weighted progress. This is exactly the shape of state machine a live WORLD/CHANGE feed would need. |
| `components/workspace/source-viewer.tsx` (428 lines) | Real source/bbox evidence viewer tied to `SourceRef`. |
| `components/workspace/review-drawer.tsx` (427 lines) | Real review/accept-reject UI over `ReviewItem`. |
| `components/workspace/processing-workspace-live.tsx` (1169 lines) | Real live SSE-driven processing view, largest live component in the app. |
| `components/dashboard-live.tsx` + `components/workspace-dashboard.tsx` | Real dashboard data fetch/render split. |
| `components/app-shell.tsx` (436 lines) | Real global app chrome: sidebar nav, session check, command palette. **This is the global nav / app-shell on the freeze list — not edited by this work.** |

None of this is a knowledge-graph/entity/"world" browsing surface. It is all
document-job-pipeline surface (upload → process → review → export). It is
the right *kind* of real infrastructure (typed events, provenance refs,
tested reducer) but it answers "what happened to this document" not "what do
we know and how is it connected."

## 4. Contract check — `ProductEvent` / `LiveEventAdapter` / `WorldProjection`

**These do not exist in this repository.** Full-repo search (not limited to
`apps/web`) found:
- `WorldProjection` — 0 matches anywhere.
- `LiveEventAdapter` — 0 matches anywhere.
- `ProductEvent` — 1 match, in `services/api/src/akc_api/product_analytics.py`,
  and it is an unrelated concept: a `Literal[...]` union of analytics
  event-name strings (`ProductEventType`) used for backend telemetry logging,
  not a client-side contract, not consumed by any UI, and not shared with any
  "cinematic track."
- `cinematic` (case-insensitive) — 0 matches in `apps/web/src`.
- A file named `components/structara-webgl-scene.tsx` (207 lines, using
  `@react-three/fiber`/`three`, both present in `apps/web/package.json`) does
  exist, but nothing in the code or its imports references it as a "cinematic
  track" consuming a shared event/projection contract, and it is not
  referenced from anywhere under `/app/*`. `CLAUDE.md`'s 2026-08-09 entry
  says this exact file "do[es] not come back" after being removed for
  violating §10.4 — its presence in this base commit and that instruction
  are in tension; this document flags the discrepancy rather than resolving
  it, since resolving it is out of this task's scope.

**Conclusion: the shared substrate the brief calls "the ProductEvent /
LiveEventAdapter / WorldProjection contract — what both WORLD and the
cinematic track consume" has no code, no type, no doc, and no test anywhere
in this repository.** It is not a matter of finding the right file; it was
searched for by every name given, repo-wide, and by the concept ("cinematic",
"projection", "event adapter").

## 5. Existing WORLD/graph, SOURCE, CHANGE, ASK surfaces

| View called for | What exists today |
|---|---|
| **WORLD** (browse/search knowledge graph) | Nothing real. `KnowledgeOverview()` inside `structara-app-page.tsx` renders a fixed 5-node "graph" (`Company`, `Filing`, `Risk`, `Metric`, `Evidence`) as disabled buttons with no layout algorithm, no data source, no search, no filter. `knowledge-studio.tsx` is further along in honesty (real empty state, no fake counts) but has no working search/filter/graph-render logic behind `demoMode`. |
| **SOURCE** (trace to source doc/evidence) | The strongest existing piece. `workspace/source-viewer.tsx` + `SourceRef`/`CanonicalBlock` types + `DocumentOverview()`'s `sources` view all model page/bbox provenance for real. Not wired to any graph/entity concept — it's per-document, not per-entity. |
| **CHANGE** (lineage/temporal history) | `DocumentOverview()`'s `versions` view is a static 4-row hardcoded version list ("v4 · User edit + export · Today, 10:42" etc.), not backed by any data. `event-reducer.ts` is real but models job/processing lineage, not entity/knowledge lineage. No diff UI exists. |
| **ASK** (query/chat scoped to an object) | Nothing. Repo-wide search for chat/ask/copilot/assistant-affordance UI turned up only incidental word matches (settings copy, onboarding copy) — no chat input, no query affordance, no scoped-object Q&A component anywhere. |

## 6. Classification

| Item | Classification | Why |
|---|---|---|
| `components/structara-app-page.tsx` (all of it) | **REPLACE PRESENTATION** | Every route it serves is non-interactive sample data hardcoded in the component. There is no data/logic layer beneath it to reuse — the "layer" *is* the JSX literal. Nothing here can be kept as contract; it can only inform what the sample copy/IA intended. |
| `components/knowledge-studio.tsx` | **REPLACE PRESENTATION** | Same disabled-everything pattern; its one advantage (honest empty state instead of fake data) is a good instinct worth carrying forward in the new WORLD view, not a layer worth reusing structurally. |
| `lib/types.ts` (`CanonicalBlock`, `SourceRef`, `JobEvent*`, `ReviewItem`, `ProjectSummary`) | **KEEP** | Real, typed, already used by tested live components. The new SOURCE view should consume these types, not invent parallel ones. |
| `lib/event-reducer.ts` | **KEEP** | Tested, correct-shaped ordered-event reducer. Pattern (not necessarily the exact reducer) is the right model for a WORLD/CHANGE live feed if one is ever built against a real backend stream. |
| `components/workspace/source-viewer.tsx` | **REUSE BELOW PRESENTATION** | The bbox/provenance rendering logic and its relationship to `SourceRef` is sound; SOURCE-view-from-a-graph-object needs new entry points into it, not a rewrite of it. |
| `components/workspace/review-drawer.tsx`, `processing-workspace-live.tsx` | **DEFER** | Real and reusable in spirit, but out of scope for the WORLD→SOURCE→CHANGE→ASK slice — they belong to the job-processing surface, not the knowledge-graph surface. |
| `components/dashboard-live.tsx` / `workspace-dashboard.tsx` | **DEFER** | Real data-fetch pattern worth mirroring for API conventions; not part of this slice. |
| `components/app-shell.tsx` | **KEEP, frozen** | Real global nav/session shell. On the do-not-edit freeze list for this round (see §7). |
| WORLD (graph browse/search/filter/inspect) | **BLOCKED** | See §8 — no backend graph/entity data source, no `WorldProjection` contract, no existing graph rendering surface to extend. Building a real one requires either backend entity/graph endpoints or an explicit decision to build the whole vertical (contract + backend + frontend) as new work, which is outside an "existing contract, read-only" slice. |
| CHANGE (entity-level lineage/diff) | **BLOCKED** | Same root cause — no entity/knowledge-lineage data source exists (only job/processing lineage, which is a different object). |
| ASK (scoped query/chat) | **DEFER** | Real gap, but not blocked the same way — a scoped-query affordance can be built against any object type once WORLD/SOURCE/CHANGE have a real object to scope to. Blocked transitively by WORLD, not independently.|

## 7. Freeze list — do not edit directly this round

Per the task's shared-file freeze, the following exist and were located but
**not modified**:

- Root `package.json` — `D:\CodexProjects\ai-knowledge-compiler-product-app\package.json`
- `pnpm-lock.yaml` — repo root
- Global layout — `apps/web/src/app/layout.tsx`
- Global app-shell — `apps/web/src/components/app-shell.tsx`
- Global navigation — the `navigation`/`secondaryNavigation` arrays inside
  `app-shell.tsx` (same file)
- Global design tokens — `design-system/tavonel/` (per `CLAUDE.md`); also
  `.agents/skills/structara-brand-experience/assets/design-tokens.json`
- `ProductEvent`/`LiveEventAdapter`/`WorldProjection` contract files —
  **do not exist to freeze**; see §4 and §8
- Global auth — `apps/web/src/lib/auth-store.ts`, `lib/session.ts`, and the
  session-check logic inside `app-shell.tsx` (no separate `middleware.ts`
  exists in `apps/web`)
- CSP/security policy — `apps/web/src/proxy.ts` (no `middleware.ts`; CSP
  headers are set here)

## 8. Blocker

**The founder's brief for P1 is written against infrastructure this
repository does not have.** The instruction was explicit: use the
`ProductEvent`/`LiveEventAdapter`/`WorldProjection` contract "as it exists
today (read it, don't assume)" and treat it as shared, read-only substrate
for both WORLD and a "cinematic track." A full-repository search (not just
`apps/web`) for all three names, plus the underlying concepts (`cinematic`,
`WorldGraph`, `EventAdapter`, `Projection`), found none of them. There is
also no existing knowledge-graph/entity browsing surface of any kind — real
or mocked-with-real-data — to extend into a WORLD view; the two candidates
(`structara-app-page.tsx`'s `KnowledgeOverview()` and `knowledge-studio.tsx`)
are both fully static, non-interactive sample UI with zero data layer.

This means the P1 vertical slice as specified — "four views into one shared
world/graph state," consuming an existing `WorldProjection`/`LiveEventAdapter`
contract read-only — cannot be built as specified, because:

1. There is no graph/entity data source (backend or fixture) organized
   around semantic objects with identity/provenance/lineage to browse. The
   real data models that exist (`CanonicalBlock`, `JobEvent`) are
   document/job-pipeline shaped, not entity/knowledge-graph shaped.
2. There is no contract to read read-only, so any `WorldProjection`-shaped
   type introduced now would be **invented by this implementer**, not
   discovered — which contradicts the instruction to treat that contract as
   pre-existing and off-limits to modify, and contradicts `CLAUDE.md`'s
   Protected Core rule that no such foundational substrate is introduced
   without the compatibility-contract → shadow → benchmark → canary ladder,
   which is explicitly out of scope for an F2/vertical-slice round.
3. Fabricating both the contract and its data in the same change means the
   "read-only, existing contract" framing the brief relies on to keep this
   slice honest (no invented data presented as fact, no backend/API contract
   changes for presentation convenience) cannot be satisfied — inventing the
   contract *is* an API/data-contract decision, not a presentation-layer one.

Per the task's own instruction — *"do not wait for further confirmation
unless P0 finds a genuine architectural blocker — if it does, stop and
report the blocker instead of working around it"* — this is that blocker.
**P1 was not started.** No `WorldProjection`/`LiveEventAdapter`/`ProductEvent`
contract was fabricated, no new pages were built, and no demo/synthetic graph
data was invented to paper over the gap, because doing so would itself
violate the "use the existing contract, read-only" and "no invented data
presented as fact" constraints in the same brief.

### What would unblock this

One of:
- The founder/orchestrator confirms the contract lives in a different
  repository or branch not visible to this worktree, and points to it.
- A "Surface Integration" or backend track defines a minimal real
  `WorldProjection`-shaped contract (even a small, versioned one) that WORLD
  can legitimately treat as pre-existing, read-only substrate.
- The founder explicitly authorizes this track to *design* (not assume) a
  new contract as in-scope new work — at which point this becomes a
  different, larger task than "vertical slice on existing infrastructure"
  and should be re-scoped/re-profiled (likely F3, since it is a new
  cross-cutting data contract multiple future surfaces will depend on) rather
  than proceeding under the current F2 assumption.

## 9. Synthetic/demo fixtures available today

- `apps/web/src/lib/demo-data.ts` (203 lines) — exists, not yet read in
  detail beyond confirming presence; likely reusable for document/job demo
  data, not graph/entity data.
- `apps/web/src/lib/dart-public-fixture.ts` — DART annual report fixture,
  referenced by the sample copy throughout `structara-app-page.tsx`
  ("DART Annual Report" project).
- `apps/web/src/data/benchmark-public-snapshot.json` — benchmark data, not
  entity/graph shaped.
- `NEXT_PUBLIC_AKC_DEMO_MODE` — existing env flag already used by
  `app-shell.tsx` and `knowledge-studio.tsx` to gate demo behavior; the right
  flag to reuse for any future honestly-labeled demo/synthetic UI.

None of these are entity/graph/lineage shaped. They would need real work to
back a WORLD view even if the contract question were resolved.
