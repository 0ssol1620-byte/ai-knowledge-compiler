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

## 6. Wave 2 merges

Twelve completed branches were merged sequentially into
`integration/g0-consolidation` (base `9e9d69a`), each with `--no-ff`, one at a
time, no pushes performed. All twelve forked from exactly `9e9d69a`, and their
changed-file sets are pairwise disjoint, so every merge was taken cleanly by the
`ort` strategy — no conflicts occurred and none had to be resolved. In
particular the anticipated collisions did not materialize: only
`tracked-build-context` touches `packages/cir-python/src/akc_cir/__init__.py`,
and only `local-mcp` touches root `pyproject.toml`/`uv.lock`.

| # | Branch | Merge commit | Content |
|---|--------|--------------|---------|
| 1 | `agent/tavonel-runpod-readiness` ("rp-docs") | `e8dc6f7` | `infra/runpod/v6/PRODUCTION_GPU_READINESS.md` |
| 2 | `agent/tavonel-r2-docs` | `1ad098d` | `docs/release/r2-storage-provisioning.md` |
| 3 | `agent/tavonel-fe-adr` | `939cbb9` | `docs/adr/ADR-FRONTEND-CONSOLIDATION.md` |
| 4 | `agent/tavonel-audit-engine` | `7aeb3e0` | `docs/audit/GAP_AUDIT_ENGINE.md` |
| 5 | `agent/tavonel-audit-infra` | `a3e675c` | `docs/audit/GAP_AUDIT_INFRA.md` |
| 6 | `agent/tavonel-audit-product` | `140bb00` | `docs/audit/GAP_AUDIT_PRODUCT.md` |
| 7 | `agent/tavonel-audit-team` | `9e413eb` | `docs/audit/GAP_AUDIT_TEAM_ENTERPRISE.md` |
| 8 | `agent/tavonel-w6-v2` | `032f46d` | `benchmark/w6/v2/` harness + pilot results (52 files) |
| 9 | `agent/tavonel-tracked-build-context` ("tbc") | `b97ef2e` | `akc_cir` TBC + build receipt (+15 unit tests) |
| 10 | `agent/tavonel-id-sparse` | `e28bc14` | sparse identity blocking (+10 unit tests, bench script) |
| 11 | `agent/tavonel-desktop-watch` | `0fbc2e6` | new `packages/desktop-watcher/` (own uv.lock; not a root workspace member yet) |
| 12 | `agent/tavonel-local-mcp` | `7eb8b97` | new `packages/local-mcp/` + root `pyproject.toml`/`uv.lock` dependency-group |

Gate after every code-bearing merge (`UV_LINK_MODE=copy uv sync --extra dev
--frozen && .venv/Scripts/python.exe -m pytest tests/unit -q`), Python suite
only per wave scope (web/vitest excluded):

- after w6-v2 (`032f46d`): **553 passed** in 126.67s (baseline held)
- after tbc (`b97ef2e`): **568 passed** in 27.86s (+15)
- after id-sparse (`e28bc14`): **578 passed** in 25.91s (+10)
- after desktop-watch (`0fbc2e6`): **578 passed** in 29.69s
- after local-mcp (`7eb8b97`): **578 passed** in 25.86s

Final HEAD after the wave: `7eb8b97`; every sync ran frozen-clean against the
merged locks (local-mcp's lock addition installed without drift). The four GAP
audit docs landed side by side under `docs/audit/` as expected (distinct
filenames, no overlap).


## 7. Wave 3 merges

Seven P0-completion branches, merged `--no-ff` sequentially onto
`integration/g0-consolidation` (start: `2d27c2f`), document-bearing branches
first. Gate after every merge (`UV_LINK_MODE=copy uv sync --extra dev --frozen
&& .venv/Scripts/python.exe -m pytest tests/unit -q`):

| # | Branch | Merge commit | Content | Gate |
|---|--------|--------------|---------|------|
| 1 | `agent/tavonel-health-scan` | `567e9b1` | new `packages/health-scan/` local-only analyzer emitting blueprint §5.2 outputs | **578 passed** |
| 2 | `agent/tavonel-access-path` | `ceeda14` | §25.6 Access-Path Conformance harness (`services/api/tests/`, `docs/security/access-path-conformance.md`) | **578 passed** |
| 3 | `agent/tavonel-ontology-gates` | `0134f4b` | ontology induction, §16.5 quality gates, §8.4 approval-gate machine (+23) | **601 passed** |
| 4 | `agent/tavonel-id-ledger` | `31d568e` | append-only identity transition ledger w/ replay + tamper detection, migration `0038_identity_ledger` (+31) | **632 passed** |
| 5 | `agent/tavonel-answer-compiler` | `1496c3b` | §22.3 CompiledAnswer compiler (+36) | **668 passed** |
| 6 | `agent/tavonel-capability-token` | `69dd448` | cap_v1 capability tokens (stdlib mint/verify) + session-scoped issuance API (+49) | **717 passed** |
| 7 | `agent/tavonel-source-adapters` | `f001c65` | source adapter contract (git/obsidian) + cursor persistence, migration `0039_source_adapter_cursors` (+18) | **735 passed** |

Conflicts encountered and how they were resolved (semantic-first):

- `akc_cir/__init__.py` (`__all__`), merges 3 and 6: both sides appended
  entries at the same sorted positions; resolved as unions
  (`HiddenInputs`+`IllegalTransitionError`, `ObservedFile`+`Ontology*`,
  `Claims`/`CoOccurrence`, `InductionConfig`/`InMemoryRevocationStore`).
- `akc_cir/identity.py`, merge 4: HEAD's sparse-blocking `index:` parameter on
  `resolve()` collided with the branch's `recorder:` parameter. Unioned the
  signature and merged both docstring paragraphs; the bodies had integrated
  cleanly (index flow feeds `decide_pair(recorder=...)`).
- Migration graph, merge 7: `0039_source_adapter_cursors` was authored with
  `down_revision = "0037_gpu_post_claim_authorization"`, which would have forked
  the graph after id-ledger's `0038`. Rebased its `down_revision` to
  `"0038_identity_ledger"` inside merge commit `f001c65`; single-head verified
  via `tests/unit/test_migration_graph.py`.
- Forward-fix amended into `f001c65`: id-ledger's slot-ownership test asserted
  `0038` was *the* current head, which stopped holding once `0039` parented onto
  it; it now asserts the lasting invariant instead (exactly one head, and 0038
  is an ancestor of it).

`services/api/src/akc_api/main.py` and root `pyproject.toml` merged without
conflict (each touched by exactly one wave-3 branch). Final HEAD after the
wave: `f001c65`; final gate **735 passed** in ~26s. Nothing pushed.

## 8. Wave 4 merges

Nineteen branches (docs-bearing first, then code, then apps/web), merged
`--no-ff` sequentially onto `integration/g0-consolidation` (start: `4466642`).
Gate after every code-bearing merge (`UV_LINK_MODE=copy uv sync --extra dev
--frozen && .venv/Scripts/python.exe -m pytest tests/unit -q`). From merge 9
onward the sync gained an additional `--group local-mcp`: prompt-injection's
`tests/unit/test_injection_boundary.py` imports `akc_local_mcp`, whose
`mcp` dependency lives in the root `local-mcp` dependency-group, so the
wave-3 gate command alone could not collect the suite. The lockfile was not
touched (`--frozen` throughout).

| # | Branch | Merge commit | Content | Gate |
|---|--------|--------------|---------|------|
| 1 | `agent/p0-cinematic-event-contract` | `0dc753a` | cinematic product-event contract (`akc_contracts`, JSON Schema, generated TS types, `docs/ux/CINEMATIC_EVENT_CONTRACT.md`) | **803 passed** |
| 2 | `agent/p1-obsidian-projection` | `33b4dde` | `akc_cir.projection` — Obsidian vault projection | **813 passed** |
| 3 | `agent/p1-team-world-categories` | `6a2f792` | world categories: role-gated promotion + sharing policy | **852 passed** |
| 4 | `agent/p0-cinematic-showcase-fixture` | `ae28dfb` | showcase-world v1/v2 fixtures + `compiler-runtime` demo pipeline | **857 passed** |
| 5 | `agent/p0-e2e-spine` | `1b2c527` | P0 integration spine harness (`tests/integration/test_p0_spine.py`) | **857 passed** |
| 6 | `agent/p0-actionkey` | `0f5fb05` | action-key store (scoped capability surface) | **879 passed** |
| 7 | `agent/p0-consumption-replay` | `cccd8b0` | consumption replay envelopes over published snapshots | **904 passed** |
| 8 | `agent/p0-mcp-surface` | `bd43c4f` | local-mcp read surface (ask/as-of, entity, impact trace, compare) | **904 passed** |
| 9 | `agent/p1-prompt-injection` | `0d7390a` | §N19 injection boundary: `_labeled` prose sanitization + `ToolScopeGuard` | **921 passed** |
| 10 | `agent/p1-runtime-qualification` | `468aba2` | runtime qualification receipt (gates/license/vuln-scan smoke) | **948 passed** |
| 11 | `agent/p1-connector-freshness` | `f488c0c` | connector freshness dashboard, migration `0040_source_cursor_tenancy` | **948 passed** (migration graph 6 passed, single head) |
| 12 | `agent/p1-health-scan-integration` | `5d2e0f3` | health-scan API wired into `main.py` behind session auth | **948 passed** |
| 13 | `agent/p1-github-connector` | `985c477` | GitHub source adapter | **963 passed** |
| 14 | `agent/p1-google-connectors` | `9adfd61` | Gmail / Calendar / Drive source adapters | **968 passed** |
| 15 | `agent/p1-desktop-package` | `a00e324` | desktop app package (`packages/desktop-app`) + runbook | **968 passed** |
| 16 | `agent/p1-ask-live-wiring` | `fe87963` | `/v1/ask` router live wiring in `main.py` | **968 passed** |
| 17 | `agent/tavonel-e2e-fix` | `5436ed3` | apps/web Playwright E2E remediation + visual-regression baselines | **968 passed** |
| 18 | `agent/p1-live-surfaces` | `61b2c0a` | SAMPLE/LIVE data boundary (`lib/data-boundary.ts`) + world client stubs | **968 passed** |
| 19 | `agent/p1-ui-portability` | `4cd153a` | blank-slate design tokens ported as additive `tv-*` layer | **968 passed** |

Conflicts encountered and how they were resolved (semantic-first):

- `akc_cir/__init__.py` (`__all__` and imports), merges 3, 6, 7 and 10: each
  side appended entries at overlapping sorted positions; resolved as sorted
  unions every time (`SOURCES_FOLDER`/`TIMELINE_FOLDER`/`TARGET_MINIMUM_ROLE`,
  `Projection*`/`PromotionDecision`, `SharingPolicy`/`Snapshot*`,
  `WorldCategory`/`WorldManifest`/`WorldSnapshot`, `ActionKeyStore`,
  `SmokeResult`, `VulnScanRef`/`VulnSeverityCounts`, `reuse_guard`/
  `runtime_qualification_json_schema`, plus the `.replay`/`.runtime_qualification`
  import blocks).
- `local-mcp/server.py` + `tools.py`, merge 9: mcp-surface widened the tool
  surface (11 tools, provenance metadata `world_state_id`/`freshness`/
  `limitations`) while prompt-injection rewrote the three original tools with
  the scope guard and labeled prose. Unioned both: full tool import list +
  `TOOL_SCOPE_GUARD`/`ReasonCode` + `_outside_scope`, `PUBLISHABLE_STATUSES`
  alongside `TOOL_SCOPE_GUARD`/`_SANITIZE_FIELDS`/`_labeled`, and responses
  keep the provenance kwargs while `topic`/`claim` payloads pass through
  `_labeled`.
- Forward-fix amended into `0d7390a`: `test_injection_boundary.py` asserted a
  closed response key-set that predates mcp-surface's provenance metadata;
  the assertion now admits those three read-only fields (they authorise
  nothing) while keeping the no-execution-surface check intact.
- `main.py` router registration, merges 12 and 16: freshness, health-scan and
  ask each appended a router at the same anchor; all three registrations (and
  their comments) survive.
- Migration graph, merge 11: `0040_source_cursor_tenancy` parented cleanly on
  `0039`; single head re-verified via `tests/unit/test_migration_graph.py`
  (6 passed) immediately after the merge.
- apps/web merges (17–19): file-disjoint as expected, zero conflicts — but the
  wave gate caught that live-surfaces imports
  `@/components/data/sample-data-badge`, which had never been committed: the
  root `.gitignore` `data/` rule silently swallowed the
  `apps/web/src/components/data/` source directory. Fixed in follow-up commit
  `7e8db5c`: un-ignore the source dir (mirroring the existing
  `apps/web/src/data` exception) and add the generic badge renderer that
  renders `marked.badge.label` for sample envelopes and nothing for live.

apps/web gate once at final HEAD (`pnpm install && pnpm exec tsc --noEmit &&
pnpm exec vitest run`): install up-to-date, tsc clean, vitest **383 passed**
across 67 files (≥ the 364 expectation). Final merge HEAD `4cd153a`, final
HEAD including the web forward-fix `7e8db5c`; python gate **968 passed** in
~38s. Nothing pushed.
