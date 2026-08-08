# Web and design handoff

The mirror of `FRONTEND_EVIDENCE_HANDOFF.md`, pointing the other way. What the
marketing surface now does, what is enforced automatically, what is left, and
which of it needs a decision rather than work.

Live at **https://tavonel.vercel.app** — frontend only. The backend is not
deployed, so the app runs in demo mode and the hero reads a dropped file in the
browser and says so.

## Read these first

| file | what it is |
|---|---|
| `design-system/tavonel/DESIGN_MASTER_V3.md` | the blueprint. `[확정]` binds, `[게이트]` needs the owner |
| `design-system/tavonel/decision.md` | **overrides the blueprint where they disagree.** Amendments A-01…A-11, plus the open list |
| `docs/PARALLEL_SESSIONS.md` | ownership split, merge order, the two silent-failure hazards |

decision.md is the one to read second. The blueprint is the plan; decision.md
is what actually happened to it, including the places the plan was wrong.

## The gates, and why they exist

Every rule here was at some point written down and then quietly broken. These
run in CI and each one has caught a real regression — twice, the regression was
the author's own, in the same session the gate was written.

```
scripts/check_migration_chain.py       one Alembic head. Two branches off the
                                       same parent merge cleanly in git and
                                       then refuse to run
scripts/check_openapi_compat.py        no breaking contract change
apps/web/scripts/verify-blueprint.mjs  [확정] items checkable from source.
                                       src/styles is zero-tolerance; legacy
                                       ratchets down only
apps/web/scripts/verify-claims.mjs     forbidden phrasings and withheld
                                       figures may not reach the site; the
                                       render copy must match the delivered pack
```

Baselines in those files are measurements, not targets. Lower them when work
removes violations. **Never raise one to make a build pass** — the same rule
`lighthouserc.json` states for the performance ratchet, and for the same reason.

## What the marketing page does now

Section order, which is the argument:

```
1  hero              a real page facsimile with blocks at stored bbox
                     coordinates, threads to the extracted values, and a drop
                     zone that reads the visitor's own file
2  recorded run      a Playwright capture of the ingest path actually running
                     against the live API. Not animated
3  proof explorer    one DART filing traced through original, Markdown, vault,
                     graph and receipt
4  accuracy          80.6% with its mandatory context, and the eight-row
                     document-type table including the 36.9% low-quality row
5  recovery          80.6 against 53.7 with only the recovery lane removed
6  campaign scale    completion and recovery rates with their denominators,
                     the pipeline stages, and the reserved slot
```

Items 4–6 come entirely from the claims pack. Nothing there is transcribed.

### The claims pack is the source

`apps/web/src/data/claims/public-claims-pack.json` is a copy of
`docs/evidence/folynta-public-claims-pack.json`. `verify-claims` compares them
as parsed JSON and fails on drift. **Numbers are never edited in either.**

`lib/claims.ts` returns a figure and its mandatory context in one object, so a
component takes both. `claimFigure()` throws for a withheld claim rather than
returning a blank. That is structural, not advisory: dropping the sentence
takes deliberate effort.

## What is left

### Needs a decision, not work

```
상표 clearance              can reverse G-A and the whole TAVONEL rename
사진 예외 (§15.4)            commissioned photography, 1-3 images
정적 시안 승인               Navigation, Proof, Live Compile — §24.1 blocks
                            W2/W3/W4 until each is approved
§5.2 지종 선정               three real stocks researched with published
                            specs; the OKLCH needs a measured swatch and
                            cannot be derived from CIE whiteness. See A-11
페이지 길이                  15 screens. The sections after the evidence are
                            assertion rather than evidence and are the cut
                            candidates. A copy decision
```

### Needs work, ordered by what unblocks what

```
1  merge #33 and #34       urgent. #34 carries migration 0023 and the main.py
                           quarantine extraction. agent/folynta-trust-
                           integration-v1 has its own 0023 off the same parent,
                           so one of them must land first and the other rebase
2  must_say_en for 5       backend regenerates the pack; the page then renders
   claims                  English instead of Korean for completion-rate,
                           recovery-rate, both recovery counterfactuals and
                           compilation-guarantees
3  quality-retry           the reserved slot reads its own status from the
                           pack. Dropping in the regenerated pack is the whole
                           change; no component edit
4  backend deploy          flips trial ingest from browser-only to a real
                           compile. One flag, and PR #34 is green
5  the full eight-stage    the current recording covers five stages honestly.
   recording               The rest needs GPU workers. Record on the machine
                           that has them and hand over a webm
6  §22 budget              LCP cause corrected in A-09 — it is initial JS, not
                           TTFB. W2/W7 replace the pages that carry it
```

## Things that will bite

**The pack's rules are not review notes.** Completion 99.98% is not accuracy;
calling it accuracy is forbidden. 80.6% may not appear without the per-type
spread. The low-quality scan row may not be removed. `benchmark_slice` values
are internal filenames and must never render. All four are enforced, but only
the greppable half — a new component that renders a figure without its context
is caught by the tests, not by the scanner.

**Two of my own tests were wrong in the same way.** Both counted the
implementation's own expression instead of the requirement, so they passed
while the page was broken. When adding a check here, assert what must be true,
not what the code happens to do.

**`git checkout` will not undo an untracked file.** A negative-control probe
left a planted value in a new file and it reached the rendered page before a
screenshot caught it. Restart the dev server after changing a JSON the app
imports; Next caches those modules.

## Recording another run

The API runs locally against SQLite with no worker:

```
AKC_TRIAL_INGEST_ENABLED=true
AKC_DATABASE_URL=sqlite+aiosqlite:///...
AKC_WEB_ORIGINS=http://127.0.0.1:3000     # not AKC_CORS_ALLOW_ORIGINS,
                                          # which is silently ignored
```

and the web app needs `NEXT_PUBLIC_AKC_TRIAL_INGEST_ENABLED=true` pointing at
it. Record with Playwright's `video` option — `recordVideo` in `test.use` is a
context option the runner does not forward and produces no file.
