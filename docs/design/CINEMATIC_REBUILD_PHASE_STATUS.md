# Cinematic rebuild — phase status

## Authority

1. `D:\TAVONEL_MANUS_COMPLETE_WEBSITE_EXPERIENCE_FREE_ASSET_MASTER_BRIEF_2026-08-21.md`
2. `D:\TAVONEL_FINAL_KNOWLEDGE_COMPILER_CINEMATIC_DESIGN_MASTER_SPEC_KO_2026-08-20.md`
3. earlier TAVONEL briefs, then current code

That order is the 2026-08-21 brief's own §0.1. Both documents rule that the
current implementation is an **asset, semantic and technical donor only** — not
the visual or UX authority. This rebuild is therefore a blank slate under
`apps/web/src/experience/`, not a refactor of the existing marketing pages.

The newer brief is addressed to **Manus**, and its §1 and §28.4 concern
migrating the deployed Manus preview at `tavoknowledg-gsohphae.manus.space`.
**The founder ruled on 2026-08-21 that production is built in this repository**;
the Manus brief is a specification, and its Phase 0 preview audit does not
apply. Building here also makes §3.2's "Film → Tutorial → Tool" continuity real
rather than aspirational, because the cinematic and `/app` share a codebase.

## Status: PARTIAL

The four canonical scenes exist and are verified. Everything downstream is
gated.

| Phase (2026-08-21 §33) | Status |
|---|---|
| 0 — audit Manus preview, classify KEEP/ADAPT/REPLACE | NOT_APPLICABLE — production is built here, not migrated from the preview |
| 1 — free-first asset board + licence manifest | PARTIAL — gate built and tested; curation needs founder go-ahead |
| 2 — four canonical scenes at final art quality | IMPLEMENTED — awaiting founder gate |
| 3 — Home closed loop | TESTED — all 24 beats render, timeline proven, founder gate still open |
| 4–7 — remaining pages | NOT_STARTED |
| 8 — responsive / reduced / fallback / licences / performance | NOT_STARTED |
| 9 — founder gate | NOT_STARTED |

## Phase 3 — the Home closed loop

Live at **`/experience`**. The whole board as settled stills is at
**`/experience/board`**.

**One implementation, three surfaces.** `experience/scenes/home-stage.tsx`
renders every beat H00–H23. The live page drives it from the semantic timeline;
the keyframe review renders it frozen at each gate shot; the board renders all
24. The separate `dom/keyframes.tsx` mock-ups were **deleted** — an approval
surface that draws the frames separately from the thing that ships approves
something that does not exist.

- `motion/semantic-timeline.ts` — one clock, beats addressed by shot id, nothing
  schedules itself (§28.1). Hand-written rather than GSAP: the §22 script budget
  is a ratchet, and what was needed is smaller than a tween library.
- `scenes/narration.ts` — §18.3's text equivalent, apart from the component so
  a test can prove all 24 beats are narrated without a DOM.
- `scenes/experience-home.tsx` — controls, keyboard, reduced-motion, temporal
  spine, accessibility mirror, closing CTA.

The film does not autoplay. A curtain holds the first frame behind one button,
and the full narrative is readable as text below without ever pressing it.

### What capturing the board and looking at it found

Same method as Phase 2, same result — the defects were invisible in code:

- **A world-state integrity violation in the founder's own gate frame.** H16
  displayed the recompiled values (`November 3, 2026`) under a strip reading
  `WORLD STATE SAMPLE-018291 · CURRENT`. §21.3 forbids exposing partial world
  state as ACTIVE. H15/H16 now read `· RECOMPILING`, and in-flight values are
  set at reduced weight with a `· RECOMPILING` mark. A test asserts it.
- **The question vanished while it was being answered.** H10–H12 showed four
  dates with nothing to be four answers *to*. The query now echoes in E3.
- **Three separate text overruns** — a shard box narrower than its own value, a
  boundary label pushed off the right edge, an evidence locator that lost
  "row 4". All three are now caught by a gate that measures instrument-voice
  text arithmetically (the mono advance makes it exact) and asserts it sits
  inside the artboard. Verified by mutation: reverting one fix reddens it.
- **Two illegible permission-boundary labels**, anchored to `points[0]` — one
  printed on top of a territory, one with the boundary stroke through it. Now
  placed above the topmost vertex on a backing plate, clamped to the safe area.
- **H22's four systems enclosed empty stage.** The authored boundary quads sat
  in the corners while every territory sat between them — four labelled boxes
  containing nothing, which is the opposite of the beat's claim. Boundaries are
  now computed from the territories they actually contain.
- **The evidence page was two-thirds empty.** Paper may be the brightest surface
  in the composition (§22.3); it may not be the emptiest. Table raised, page
  shortened, locator printed as page furniture.

### A test bug worth recording

The overflow gate passed while the defect it was written for was live. A single
`/…/g` regex shared across the 24 per-shot tests carried `lastIndex` between
them and silently matched nothing after the first use — so the gate reported
green over an unmeasured frame. **A gate that has never been seen to fail is not
evidence.** It is now built per test and was mutation-tested before being
believed.

### The clock is proven, not assumed

`motion/semantic-timeline.test.tsx` drives a stubbed `requestAnimationFrame` and
shows the sequence walking all 24 checkpoints, publishing each exactly once,
settling at the end, holding a checkpoint until its shot settles, and clamping a
30-second delta from a restored tab to a single beat.

This exists because the browser preview in this environment never composites
frames, so rAF never fires and `/experience` sits on H00 — which looks exactly
like a broken timeline and is not one (`document.hidden === true`, 0 frames in
one second). The live page could not be verified by watching it here.

## The four canonical scenes

Review at **`/experience/keyframes`**. Capture with
`pnpm --filter @akc/web keyframes:capture <baseUrl> <outDir>` — writes all four
at canonical 1440×900 in both full and reduced-motion contexts.

| Scene | Copy | Shot | Was |
|---|---|---|---|
| A | YOUR WORK IS EVERYWHERE | H01 | A-01 |
| B | COMPILED KNOWLEDGE OBJECT | H06 | A-07 |
| C | YOUR DIGITAL WORLD, COMPILED | H08 | A-09 |
| D | ONLY AFFECTED KNOWLEDGE IS UPDATED | H16 | C-03 |

**The two briefs name the same four scenes independently.** The 2026-08-20 spec
§20.1 gates full implementation on four founder-approved frames; the 2026-08-21
brief §33/§34 PHASE 2 names four canonical scenes to finish first. They agree.
That is why this gate survived the supersession when the shot board around it
did not.

## What the 2026-08-21 brief changed

### Shot board — replaced

`experience/manifest/shots.ts` now carries H00–H23 from §5.3. The previous
A-00…E-03 board is kept in the same file as `SUPERSEDED_2026_08_20_BOARD`
rather than deleted, on the product's own rule that a superseded fact stays
historical and inspectable.

- 27 beats → 24, retimed throughout
- `SOURCE REGISTRATION` added as its own beat (H02)
- `CATEGORY LOCK` split out of the world reveal (H07 + H08)
- selective recompilation moved from 36.00–39.20s to 42.20–46.40s

**Two beats have no successor and that may be an oversight:**

- `A-02` MESS / SCALE WITHOUT CHAOS
- `A-04` ROUTE / RECOVER MICRO-PROOF — the one-second beat that showed the
  compiler does not hide its own failures. Nothing else in the sequence makes
  that claim. A contract test asserts this omission stays recorded.

### Typography — narrowed

§22.4 tightens every band §12.2 set. The newer values are in `styles/tvx.css`:

| Role | Was | Now |
|---|---|---|
| Hero H1 | 60–68px | 56–66px, line-height 1.02–1.08 |
| Query | 32–38px | 30–36px |
| Secondary | 18–22px | 20–28px |
| Numeric | 42–54px | 38–46px |
| Technical label | 11–12px | **minimum 12px** |
| Copy max width | 580px | ~620px |

The 12px floor was a live violation: the instrument voice was set at 11px, and
in-SVG labels ran as low as 8px. All raised; the C-03 affected objects were
resized to hold 12px text and the marketing-freeze object moved left to stay
inside its x700–1160 box.

### Fonts — resolved

§22.4 replaces the licensed-face list with a free-first policy: evaluate
Fontshare, prefer SIL OFL, record a licence per family. **This closes the open
gap the previous status doc flagged.** Wanted Sans is SIL OFL and already
self-hosted here, so the editorial voice is compliant rather than a placeholder
waiting on a purchase. Söhne / ABC Diatype / Suisse Intl are no longer required.
The instrument voice still runs on a system mono stack — an open choice now, not
a blocked one.

### Newly in scope

- **IA expands** from 7 routes to ~20 (§4.1), each with an assigned cinematic
  intensity (§3.4) and its own reject conditions.
- **Stock photography and video** at 10–15% of Home (§5.5), under a free-first
  acquisition policy (§17) with a mandatory licence receipt per asset (§17.4).
  No manifest entry, no production use.
- **Procedural-first proprietary assets** (§19) — Fact Stack, Identity Capsule,
  Project Territory and the rest built in WebGL/SVG/DOM rather than modelled by
  hand. This validates the fallback-tier-first approach already taken.

### Unresolved conflict inside the new brief

§5.2 puts the Guided→Scale handover at ~50.2s. §5.3's table runs ANSWER to 52.0
and EVIDENCE DIVE to 55.4, with the first scale beat starting at 55.4. The gap
is 5.2s.

§5.2 says "approximately" and its numbers are carried unchanged from the
2026-08-20 board, whose beats they did fit; §5.3 is the new material. That
suggests the table is right and §5.2 is stale. `CONTROL_MODE_BOUNDARIES` carries
both values and a `unresolvedConflict` flag rather than picking one silently. If
the intent really is a hard 50.2s handover, three beats move.

## Defects found by capturing the frames and looking at them

- **The world was invisible.** A linear presence→colour ramp put most
  territories within a few values of the graphite stage. Fixed with a contrast
  floor, an eased ramp and a key-light edge — not by brightening the stage,
  which §22.3 rules out.
- **The world stopped short of the frame.** The outer ring now reaches r=820,
  which at the 0.58 vertical squash puts the lowest islands past y=900.
- **A rejected-placement seam.** Territories landing in editorial territory were
  clamped just right of the guard, stacking into a vertical column no ring had
  asked for. Now reflected across the centroid.
- **The A-01 hero folio was labelled with the wrong filename**, beside the
  calendar.
- **The Fact Stack was a third of its box** and its source plate overran its own
  edge. Rebuilt to fill 240×250; the locator moved to the Evidence Console.
- **Two A-09 labels rendered through their territories.**
- **After the 12px rise:** the compile-report technical line wrapped and orphaned
  "RECOMPILATION"; the email filename grew until it crossed the meeting note.
  Both are §32.6 failures. Fixed by tightening tracking on that one line and
  moving the far object.

One contract test caught a wrong assumption of mine rather than a code defect: I
had asserted E1 and E2 must not overlap. The spec's own zones overlap by 70px on
purpose — E2 is the stage the camera frames, not a box copy may not enter, and
§6.4 constrains *density*, not rectangle intersection. Asserting non-overlap
would have moved the world to satisfy a rule nobody wrote.

## Verification

`tsc --noEmit` clean · `eslint src/experience src/app/experience
--max-warnings=0` clean · **117 tests pass** (36 experience contracts, 12 asset
gate, 64 stage gates, 5 timeline).

Capture with `pnpm --filter @akc/web keyframes:capture <baseUrl> <outDir>` —
writes the gate frames and all 24 board beats at canonical 1440×900, in both
full and reduced-motion contexts.

Both ESLint and `tsc` die with a V8 out-of-memory fault while the dev server is
running. That is memory pressure, not a repository condition — stop the server
and they pass. Worth knowing before anyone spends an hour on the wrong bug.

## Known gaps, named rather than closed

- **Label collision.** The four H08 labels are hand-placed against the authored
  topology. That does not scale to the Explore act's budget. §13.4's
  priority-based collision system is not faked here.
- **Responsive.** §32.6 defines seven review viewports. The canonical scenes are
  judged at 1440×900; recomposition per §27.1 is Phase 8.
- **H22's outer two boundaries still sprawl.** CODE and TICKETS seed on isolated
  outer-ring territories, so their clusters reach further than the inner two.
  They contain real material now, which was the defect; the shape is not yet
  good.
- **H06 leaves the left 60% of the frame empty.** That follows the spec — §5.4
  gives the beat no public copy — but it is worth a founder's eye at the gate
  rather than a silent assumption that empty was intended.
- **No WebGL yet.** `three` / `@react-three/fiber` / `@react-three/drei` are not
  installed. The §19.7 fallback tier is what exists. Reinstating them also means
  re-deriving the §22 script budget from a new measurement.

## Phase 1 — what exists

The **enforcement half is built**:

- `experience/assets/asset-manifest.ts` — the §17.4 receipt schema and the §31
  release gate
- `src/content/asset-manifest.json` — currently empty; no third-party asset has
  entered the repository
- `src/content/license-ledger.md` — generated, never hand-edited
  (`pnpm --filter @akc/web assets:ledger`)
- 12 tests covering the licence rules

§31 writes the gate as `third_party_asset AND no_manifest_entry => FAIL`, which
would need the build to know which files are third-party. It cannot: all it sees
is a file on disk. So the rule is inverted and fails closed — **every** file
under the asset root needs an entry declaring its origin, and third-party
entries carry the full receipt. An undeclared file is a violation whatever its
origin. The gate also refuses an unchecked `commercial_use_checked` (Mixkit
ships Free and Restricted items side by side), a provider outside the §17.2
stack, a §17.3 mood-reference URL used in production, and a synthetic fixture
claiming to depict real evidence.

The **curation half has not started**: §33 Phase 1 wants 20–30 candidate clips
and stills from Pexels / Unsplash / Mixkit and HDRI/PBR from Poly Haven /
ambientCG, graded into TAVONEL tone as a contact sheet. That means downloading
third-party files, which needs an explicit founder go-ahead before it happens.

## Open decisions — founder only

1. **Approve or reject the four canonical scenes**, now including H07 as scene
   C's companion frame. Phase 3 was built past this gate on an explicit
   instruction to proceed; the gate itself is still open, and Phases 4–9 have
   not started.
2. **Go-ahead to download stock assets** for the Phase 1 contact sheet.
3. **The §5.2 / §5.3 boundary**, above.
4. **A-04's dropped trust beat** — deliberate compression, or restore it?

## Route note

`/experience/*` was added to the bare-route list in `components/app-shell.tsx`.
Without it the authenticated shell's session probe replaced the opening of the
film with a "could not verify your session" panel.
