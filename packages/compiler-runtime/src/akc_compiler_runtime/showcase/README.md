# Showcase fixture source set — "Launch"

Canonical Comprehension World corpus (master spec §3.1, §11.2; Phase 2).

Fictional content authored by the TAVONEL team. The files in this directory are
the SOURCE of truth for the recorded replay fixture under
`apps/web/src/fixtures/showcase-world/v1/`; `scripts/record_showcase.py` copies
them into a scratch workspace and compiles that copy with the real
`akc_compiler_runtime` pipeline (no synthetic events).

Semantic events planted on purpose:

- Same program, three spellings: "Atlas Project" / "Project Atlas" / "LP-01"
  (`approved-launch-plan.md`, `proposal-draft.md`, `meeting-notes.md`,
  `codename-brief.md`).
- Same person, three renderings: "Dana Reyes", `dana.reyes@atlas.example.com`,
  "Dana Reyes <dana.reyes@atlas.example.com>".
- Three launch-date candidates by authority: October 15 (official,
  approved plan), October 29 (draft proposal), November 12 (informal meeting
  note fallback).
- Effective date: customer notifications effective October 20, 2026
  (`schedule-events.md`).
- Rename scenario: `codename-brief.md` is renamed to `lp01-naming-brief.md`
  between world v1 and v2 during recording (exact-content rename).
- Downstream impact 5+: roadmap.md -> schedule-events.md,
  approved-launch-plan.md -> customer-update.md / repo/docs/release.md ->
  repo/README.md all hang off the approved launch date.

World v2 mutation applied by the recorder: the official plan's launch date is
edited from October 15, 2026 to November 3, 2026.
