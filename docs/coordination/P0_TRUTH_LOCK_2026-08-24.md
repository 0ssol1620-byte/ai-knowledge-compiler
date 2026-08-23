# P0 Mission — Truth Lock (2026-08-24)

Mission: close the remaining gaps between main@7740d77 and a real Personal
Knowledge Compiler Alpha, per the 2026-08-22 master blueprint.

Every line below is classified: OBSERVED / PROVEN / INFERRED / PROPOSED /
BLOCKED.

## A. Repository state

| Item | Value | Status |
| --- | --- | --- |
| Worktree (authoritative) | `D:\CodexProjects\ai-knowledge-compiler-g0` | OBSERVED |
| Branch | `integration/g0-consolidation` (= pushed `main`) | OBSERVED |
| HEAD | `7740d772438a7c1fd201317fd8b9815da0d11469` | OBSERVED |
| Remote | `https://github.com/0ssol1620-byte/ai-knowledge-compiler.git` | OBSERVED |
| Dirty/clean | clean (0 files) | OBSERVED |
| Migration head | `0039_source_adapter_cursors` (single head, 0033–0039 chain) | OBSERVED |
| Unit baseline | **735 passed** in ~26s (`pytest tests/unit -q`) | PROVEN (re-run today) |
| Frontend build | last verified green pre-Wave-3; re-verify during this mission | PARTIAL |
| Vercel production | failing — `vercel.json` has `outputDirectory: "apps/web/.next"` while the project root is already the repo root → Vercel looks under `/vercel/path0/apps/web/apps/web/.next`. Fix = drop `outputDirectory` (framework detection handles monorepo via `buildCommand`'s filter) and let Next.js default apply; verify with a local `pnpm --filter @akc/web build`. If Vercel *project settings* also pin Root Directory=`apps/web`, that is a human-side setting change to document instead of a repo hack. | OBSERVED + PROPOSED |
| Unmerged branches | none required for P0; all Wave-2/3 work is merged | OBSERVED |
| Stash | 0 | OBSERVED |
| Worktrees on disk | 46 registered (historical capability trees; do not delete) | OBSERVED |

## B. What actually exists now (do NOT rebuild)

PROVEN by module presence + tests merged in Waves 2–3:

- CIR core/provenance, authority/temporal, semantic diff, dependency,
  selective recompilation (+ full-rebuild equivalence oracle), atomic
  world-state publish/promotion gates.
- Identity: sparse blocking resolution (10k MemoryError removed),
  transition ledger (0038).
- Answer Compiler §22.3–22.5 (intent ×10, CompiledAnswer, freshness
  auditor, outcomes incl. fail-closed NOT_AUTHORIZED).
- Ontology induction + quality gates + approval lifecycle.
- Source adapters contract (Git/Obsidian) + resumable cursors (0039).
- desktop-watcher (crash-safe journal replay), local read-only MCP
  (get_current_truth/get_evidence/search_world), Health Scan analyzer,
  capability token (cap_v1) + issue endpoint, TrackedBuildContext.
- Security: RLS tenant isolation, append-only audit_events, access-path
  conformance harness (10 paths measured, disclosure=0; audit-event gap
  xfailed honestly).

## C. Confirmed remaining P0 gaps (fresh inspection, not stale audit)

1. **CompilationActionKey / CAS reuse — MISSING** (no action-key file;
   recompilation.py has no cache identity). Blueprint §20. This blocks
   "selective work reduction" claims beyond the existing equivalence proof.
2. **ConsumptionReceipt — MISSING** (`consumption_lineage.py` existed only in
   an unmerged lineage; current tree has no such module). Blocks §21.5
   consumed-world chaining and all replay queries.
3. **Replay correctness — MISSING** (no replay module).
4. **Personal real-source E2E spine — MISSING as an integrated path.**
   Components exist separately (watcher, adapters, world runtime); nothing
   wires source-edit → new active world → changed answer end-to-end without
   manual steps. This is the acceptance demo (§27 of the mission).
5. **Live product surfaces** — WORLD/CHANGES/ASK/EVIDENCE still read demo
   fixtures in apps/web (sampleMode). SAMPLE/LIVE boundary not yet enforced.
6. **Obsidian projection profile** — exports.py has an OBSIDIAN target but no
   generated per-world directory architecture w/ provenance frontmatter.
7. **MCP surface breadth** — 3 tools exist; blueprint asks for ask_as_of,
   get_entity, get_claim, get_change, trace_impact, get_world,
   compare_worlds.
8. **Runtime qualification receipt fields** — partial (see GAP_AUDIT_ENGINE).
9. **W6 acquisition robustness** — pacing/backoff needed; protocol frozen.
10. **Vercel production red** (config fix above).

## D. Execution plan (this mission)

Wave A (parallel):
- A1 Personal E2E spine (real workspace fixture-on-disk + watcher→world
  pipeline runner + acceptance script)
- A2 CompilationActionKey + CAS reuse + sabotage tests
- A3 ConsumptionReceipt + replay foundation
- A4 MCP tool-surface completion (read-only)
- A5 Vercel config fix + local prod build verification

Wave B (after A): live surfaces wiring, Obsidian projection profile,
security access-path extension, W6 acquisition retry, runtime qualification
fields.

Hard targets unchanged: stale escape 0, invalid reuse 0, unauthorized
disclosure 0, partial activation 0, silent unresolved→current 0.
