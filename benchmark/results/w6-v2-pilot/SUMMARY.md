# W6 v2 pilot — Raw vs Basic RAG vs TAVONEL compiled world

## Evidence header

- experiment_id: W6-V2-PILOT (protocol v2)
- branch: agent/tavonel-w6-v2 cut from 9e9d69a
- preregistration sha256: see preregistration.snapshot.json (frozen before any result existed)
- pinned model: `n/a` (temperature 0, single-model rule)
- verdict: **BLOCKED_ACQUISITION**
- role: PILOT ONLY — harness validation and directional signal only

## Executive status

| Area | Status | Evidence boundary |
| --- | --- | --- |
| Preregistration freeze | DONE | manifest + snapshot hash written before acquisition |
| Acquisition | BLOCKED | acquisition-report.json item ledger; no silent drops |
| Question freeze | NOT REACHED | model phases never started on the blocked path; no questions.frozen.json exists |
| Arm execution | NOT REACHED | runs/*.jsonl include per-row api_failure flags |
| Grading | NOT REACHED | evaluation.json per-question grades + Wilson CIs |

## Acquisition cause diagnosis (BLOCKED)

- gate: usable=31 < required 40 -> BLOCKED_ACQUISITION (final)
- attempt 1 (preserved): 0/60 usable - every request http_403 (default User-Agent blocked by Wikimedia)
- attempt 2 (final, one authorised re-run): 31/60 usable (30 ok + 1 cache hit)
- all 29 failures are http_429 (rate limit); pattern begins at 'Great Barrier Reef', ~12th title in frozen order
- root cause: sequential fetches with no inter-request pacing; backoff (2s/4s) ignores Retry-After
- recommended remedy (NOT executed, per operator instruction): pace requests / honour Retry-After; the 31 cached docs remain reusable

## Deviations and blockers (recorded verbatim)

- **DEVIATION-01**: The v3 freeze list of 6,987 titles could not be located in the repository (searched: benchmark/, docs/, research/, scripts/, tools/, and all local linked worktrees; no dataset/title/freeze artifact with ~6,987 entries found). The pilot therefore freezes its own fresh 60-item source list below, in fixed order, BEFORE acquisition. Any future full run must first re-derive or re-freeze the v3 list; this pilot's list is not a substitute for it.
- **DEVIATION-02**: The 'TAVONEL compiled world' arm uses a pilot-grade compiler implemented in this harness (LLM extraction into typed elements with provenance ids), not the production services/api collection pipeline. It exercises the compile-then-retrieve shape, not the product's exact algorithms.
- **DEVIATION-03**: transport fixes (descriptive User-Agent header plus extract-path parsing, applied after the first BLOCKED_ACQUISITION; attempt-1 ledger preserved as acquisition-report.attempt1-blocked.json, 60/60 http_403 from Wikimedia's default-UA policy). Questions, evaluation criteria and success judgment rules are unchanged, so preregistration validity holds. Protocol unchanged.
- **BLOCKER-GIT-WORKTREE**: worktree checkout could not complete on this host (per-file multi-second disk; interrupted resets left the index partial). Harness and results live as untracked files under benchmark/w6/v2/ and benchmark/results/w6-v2-pilot/, ready to commit once the worktree index is repaired with a single `git reset --hard HEAD`.
