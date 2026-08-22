# G0 — Repository Reconciliation (integration/g0-consolidation)

Date: 2026-08-22 KST · Executor: Hermes agent session · Status: **G0 COMPLETE / ALL LOCAL GATES PASS — PUSH PENDING FOUNDER APPROVAL**

This is the G0 "capability → authoritative worktree → HEAD" reconciliation the
2026-08-22 master blueprint (§29.2 Repository governance, §35 Phase 0, §36 P0-1/2)
calls for, executed as an integration branch rather than a forced fast-forward of
`origin/main`.

---

## 1. Starting topology (evidence header per the worktree-scoped rule)

| Item | Value |
|---|---|
| Project/worktree | `D:\CodexProjects\ai-knowledge-compiler-g0` |
| Branch | `integration/g0-consolidation` |
| Base | `agent/tavonel-integration-core` @ `76f805d` (I4 COMMON CORE INTEGRATION REHEARSAL PASS) |
| Merged in | `agent/folynta-trust-integration-v1` @ `46edd90` (+119 commits over merge-base `185d04b`) |
| `origin/main` | `185d04b` (2026-08-09) — stalled 13 days; every active track diverged from it |

Lineage facts established before merging:

- The Security/Trust lineage (`folynta-trust-integration-v1`) had **absorbed the M2
  collection plane**: all 159 files M2 touched exist on it; **148/159 are
  byte-identical** (`git rev-parse` blob equality), the remaining 11 are strict
  supersets (`__init__.py` +282/-0, `services/api/main.py` +186/-33 trust routes).
- The P1 Protected Core modules (10 CIR files + 10 unit tests) promoted by I4 are
  **byte-identical** to the same-named files on the Security lineage
  (`git diff --numstat` between the two tips over `packages/cir-python/src/akc_cir/`
  shows only Security-lineage additions: `trust.py`, `entity.py`,
  `collection_events.py`, `knowledge_model.py`, `public_proof.py`, `schema.py` …;
  zero deletions against the I4 versions of shared modules).
- Migration chain is intact and linear across both lines:
  `0022_cdr_derivative_lineage → 0023_trial_ingest → 0023_v4_collections →
  0024_production_hybrid_retrieval → … → 0032_accepted_block_invalidations`.
  Duplicate numeric prefixes are distinct revision IDs chained by `down_revision`;
  alembic treats them as one head.
- No file deleted on either side was modified on the other (deleted∩touched = ∅).

## 2. Merge result

```
git merge --no-ff agent/folynta-trust-integration-v1   # base 76f805d
→ e54d381  merge: G0 consolidation - Security/Trust lineage into I4 common-core baseline
```

Exactly **two content conflicts**, both resolved deliberately:

### 2.1 `apps/web/src/app/usage/page.tsx` — kept I4 (ours)

I4 carries the founder decision: `/usage` is a live redirect to `/billing`
(`/billing` is the canonical billing surface; `/usage` returns later as a real
usage-analytics route). The Security lineage's change was a one-word copy edit
("Review" → "Inspect") targeting the paragraph that redirect removed.
Resolution: `--ours`.

### 2.2 `apps/web/src/components/app-shell.tsx` — kept SEC structure, ported I4 chrome

Two orthogonal changes collided on one file:

- **Security lineage (kept)**: perf rework `0b133eb` — `app-shell.tsx` became a
  slim marketing-route router; the entire authenticated chrome moved to a dynamic
  import of the new `apps/web/src/components/authenticated-shell.tsx` so zod +
  Phosphor no longer ship with marketing pages (§22 ratchet motivation).
- **I4 (ported)**: World nav entry, `AccountMenu` component replacing the static
  account link, `/billing` secondary-nav label replacing `/usage`, aria-label on
  primary nav, and the SOURCE/CHANGE/ASK reachability comment.

Resolution: `--theirs` for `app-shell.tsx`, then the I4 chrome changes were
re-applied onto `authenticated-shell.tsx` (icon imports minus `CaretDown` plus
`Globe`; nav arrays; `AccountMenu` swap at the old account-button site).

## 3. Contract fix riding on this branch

M2.1's finding was confirmed live in the merged tree: frontend zod schemas expected
`files_discovered` while every authority —
`packages/contracts/schemas/collection-event.schema.json`,
`akc_cir.collection_events` payload validation, and the real emitter at
`services/api/src/akc_api/collection_api.py:1330` — uses `discovered_files`. Live
`file.discovered.v1` / `collection.discovery.progress.v1` events therefore failed
frontend parsing and never reached the WORLD projection.

Fixed in `1f8763e`: renamed the key across `product-event.ts` (both schemas +
refine), `world-projection.ts`, `demo-workspace.ts` fixtures,
`product-event-scope.test.ts`. Frontend grep for `files_discovered` is now empty;
backend/schema names were already canonical and untouched.

## 4. Verification

(worktree-local `.venv` via `uv sync --extra dev --frozen`; node via
`pnpm install --frozen-lockfile` — single synchronous install per the I4 lesson.)

| Gate | Result |
|---|---|
| pytest `tests/unit` | **553 passed** in 90.8s (I4's 439 + Security-lineage suites) |
| pytest `tests/contract/test_collection_event_contract.py` | **324 passed** — confirms `discovered_files` is the canonical backend name |
| web typecheck (`tsc --noEmit`) | **pass** (exit 0) |
| web vitest | **65 files / 364 tests / 0 failed** (after the §4.1 fix; was 361 with 1 failed) |
| web production build | **pass** (exit 0, Next.js 16.2.12, full route table generated) |

### 4.1 `app-shell.test.tsx` — a merge regression, and a test that was never really passing

The first full `vitest` run after the merge returned `360 passed | 1 failed`.
The failure was in `app-shell.test.tsx`, exactly the file whose source
counterpart (`app-shell.tsx` / `authenticated-shell.tsx`) required the manual
conflict resolution in §2.2 — so it was treated as a real regression, not as
flake.

**Regression 1 — the accessible name moved off the nav.** The Security
lineage's perf rework put `aria-label="Primary navigation"` on the `<aside
className="sidebar">` wrapper, while the I4 chrome expected it on the `<nav>`
itself. `<aside>` exposes `role="complementary"`, so a
`role="navigation"` + name lookup could not match it. Fixed by giving the
landmarks distinct, accurate names: the wrapper is now
`aria-label="Workspace sidebar"`, and `aria-label="Primary navigation"` sits on
`<nav className="sidebar-nav">` — the element that actually is the navigation.
This is also the more correct accessibility markup of the two.

**Regression 2 (pre-existing, exposed here) — the suite was order-dependent.**
While verifying the fix, all three original cases were run individually with
`-t`. **Every one of them failed alone**, including the two that "passed" in the
full run. They were passing only as a group, each relying on module state warmed
by the previous case.

Root cause: after the §22 bundle split, `AppShell` is only a route decision and
reaches the chrome through `next/dynamic`. That boundary does not resolve under
jsdom, and `next/dynamic` is a CommonJS re-export
(`module.exports = require('./dist/shared/lib/dynamic')`) that Vite resolves
straight to the internal module — so a `vi.mock("next/dynamic", …)` never
reaches the component (verified directly: the mock factory ran, but the stub
never rendered). With `loading: () => null`, every chrome assertion was querying
an empty document. Rendering `AuthenticatedShell` directly was confirmed to
produce the full 16 KB of markup, isolating the lazy boundary as the sole cause.

Fix: assert the chrome contract against `AuthenticatedShell`, the component that
actually renders it, and give `AppShell` the assertions that are genuinely its
own — which routes get chrome and which are returned bare. The suite went from
3 order-dependent cases to **6 that each pass in isolation**.

Negative proof (per the project's standing discipline that a test must be shown
capable of failing): reverting the `aria-label` fix makes
`renders WORLD as workspace primary navigation` fail with the original error;
restoring it passes. `tsc --noEmit` is clean after both edits.


## 5. Not yet reconciled (explicitly out of scope here)

- `origin/main` itself still points at `185d04b`; promoting this branch is a
  separate founder-approved push (no pushes performed).
- L1/W1/E0/M1 design-only branches (READY docs, no code) — their plans should be
  scheduled off this baseline.
- Cinematic V2 line remains frozen pending founder visual GO (C02 choreography).
