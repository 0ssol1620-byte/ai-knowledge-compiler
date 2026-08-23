# Blank-slate design token port map

Status: W-P1 (first UI portability wave) · 2026-08-23
Branch: `agent/p1-ui-portability`

This document maps the design tokens of the external **tavonel-blank-slate**
reference implementation onto the token layer already defined in
`apps/web/src/styles/tokens.css`, records every name and value difference, and
lists the port priority used for the additive `--tv-*` layer introduced in the
same commit.

## Sources and authority

| Item | Value |
| --- | --- |
| Source repo (read-only) | `C:/Users/yspow/Documents/Codex/2026-08-20/tavonel-ui-tavonel-final-knowledge-compiler-3/outputs/tavonel-blank-slate` |
| Source master file | `design-system/tavonel/MASTER.md` (note: directory is `design-system/tavonel/`, not `design-system/tavonel-blank-slate/`) |
| Source token file | `src/app/globals.css` (`:root` block; there is no `src/styles/` directory in the source repo) |
| Target token layer | `apps/web/src/styles/tokens.css` (`@layer tokens`) |
| Namespace rule | New variables are added **only** under the `--tv-bs-*` prefix; no existing variable is renamed or re-valued |

**Authority override (must be respected when porting).** `MASTER.md` opens with
a TAVONEL AUTHORITY OVERRIDE (2026-08-21): its *generated* suggestions — the
App-Store landing pattern, Inter typography, the indigo/teal/amber default
palette (`#2563EB` / `#0891B2` / `#D97706`), glassmorphism, glow and ambient
light — are research output and were **rejected**. The production authority of
the blank-slate is its `globals.css`: graphite/bone surfaces, restrained cobalt
signal, Instrument Sans + IBM Plex Mono, flat surfaces and hairlines. This port
therefore ports the `globals.css` values and treats conflicting `MASTER.md`
tables as non-authoritative.

## 1. Color tokens

### Surface ramp (blank-slate `:root` → nearest existing token)

The existing layer speaks in two surface families — PAPER (light) and INSTRUMENT
(dark) — in OKLCH. The blank-slate speaks a single dark-first graphite/bone ramp
in hex.

| Blank-slate | Value | Nearest existing | Existing value | Relationship |
| --- | --- | --- | --- | --- |
| `--void-950` | `#050607` | `--inst-0` | `oklch(14% 0.01 250)` ≈ `#0A0C10` | Same role (deepest canvas); blank-slate is darker and hue-neutral |
| `--graphite-900` | `#0b0e10` | `--inst-1` | `oklch(18% 0.011 250)` ≈ `#12151B` | Same role (raised dark surface); slight lightness gap |
| `--graphite-800` | `#141a1d` | `--inst-2` | `oklch(22% 0.012 250)` ≈ `#191D25` | Same role; blank-slate leans teal, existing leans blue |
| `--steel-650` | `#344047` | `--ink-2` | `oklch(50% 0.012 250)` ≈ `#626A76` | Different roles: steel-650 is a mid *surface*, ink-2 is mid *ink* — no equivalent exists |
| `--fog-500` | `#8d969b` | `--inst-ink-2` | `oklch(54% 0.012 250)` ≈ `#6B7481` | Muted foreground; fog is lighter/cooler |
| `--bone-100` | `#ece8de` | `--inst-ink-0` | `oklch(94% 0.005 250)` ≈ `#EDF0F4` | Primary foreground; bone is warm (hue ~80°), inst-ink cool |
| `--paper-050` | `#f4efe5` | `--paper-1` | `oklch(96.6% 0.006 84)` ≈ `#F7F5F1` | Warm paper; near-match in lightness |

⚠️ **Name hazard:** the source name `--paper-050` collides visually with the
existing `--paper-0/-1/-2` family while meaning something different enough
(warm cream vs. pure-white recto). Bare-name porting is forbidden; everything
lands under `--tv-bs-*`.

### Signal / state colors

| Blank-slate | Value | Nearest existing | Existing value | Relationship |
| --- | --- | --- | --- | --- |
| `--signal-cobalt` | `#6d85ff` | `--brand` | `oklch(48% 0.2 255)` | Both the single brand action hue (~255–260°); cobalt is lighter/lower-chroma (a signal tint, not a fill) |
| `--signal-cool` | `#8aa5b5` | `--evidence` | `oklch(60% 0.11 210)` | Cool desaturated blue family; evidence is more saturated |
| `--warning-amber` | `#b88a48` | `--review` | `oklch(52% 0.12 70)` | Amber/review family; review is darker and redder |
| `--critical-oxide` | `#9d5752` | `--danger` | `oklch(50% 0.17 25)` | Danger family; oxide is muted brick vs. vivid red |

### Semantic aliases (shadcn-style set, blank-slate only)

The blank-slate also defines a full semantic set with no counterpart in the
existing layer: `--background/--foreground`, `--card(+foreground)`,
`--popover(+foreground)`, `--primary(+foreground)` (note: bone-on-graphite
*inverted* vs. our `--brand`), `--secondary(+foreground)`, `--muted(+foreground)`,
`--accent(+foreground)` (= cobalt), `--destructive` (= oxide), `--border`
(`rgba(236,232,222,.14)`), `--input` (`.12`), `--ring` (= cobalt). These are
ported verbatim under `--tv-bs-*`.

## 2. Typography

| Aspect | Blank-slate | Existing layer | Difference |
| --- | --- | --- | --- |
| Heading/body font | Instrument Sans (+ fallback stack) — `@theme inline --font-sans`; `Inter` from `MASTER.md` is **rejected** | none (font stacks live in route-level CSS; masterplan §6 keeps fonts out of the token layer for now) | Font stacks ported as new `--tv-bs-font-*` tokens only |
| Mono font | IBM Plex Mono (+ fallback stack) — machine-readable evidence only | none at token level | Same treatment |
| Type scale | No explicit scale; observed usage clusters across `src/**`: 8/9/10/11/12 px micro-labels (mostly Plex Mono), 13–19 px body, 22–30 px section heads, 34–48 px display, up to 72 px hero | none (components hardcode px today) | Scale is **derived from measured usage**, not from `MASTER.md` |

Ported scale (documented derivation, `--tv-bs-text-*`): 8 · 10 · 11 · 12 · 14 ·
18 · 22 · 34 · 46 · 72 px. These are observations, not a spec — future waves may
re-map them onto the masterplan type ramp.

## 3. Space / radius / motion

| Aspect | Blank-slate | Existing | Difference |
| --- | --- | --- | --- |
| Spacing | `MASTER.md` `--space-xs…3xl` = 4/8/16/24/32/48/64 px | `--s-1…12` = 4…200 px | **Values identical where they overlap — name difference only.** Not re-ported; existing `--s-*` stays authoritative |
| Radius | `--radius: 0.35rem` with ×0.5/×0.75/×1/×1.5 derivatives | `--r-paper 2px … --r-media 12px` | Different systems; blank-slate radii ported as `--tv-bs-radius*` |
| Easing | `--ease-reveal cubic-bezier(0.22,1,0.36,1)`, `--ease-camera cubic-bezier(0.16,1,0.3,1)` | `--e-out cubic-bezier(0.23,1,0.32,1)` | Near-identical feel, different curves; ported verbatim as `--tv-bs-ease-*`. (`--ease-camera` already equals legacy `--tv-ease-enter` in `apps/web/src/app/tavonel.css` — kept separate anyway to avoid coupling to an unlayered legacy file) |
| Durations | 160 ms UI transitions (header links, skip link); reduced-motion clamps to 0.16 s | `--t-1…5` = 90…420 ms | Overlaps `--t-2` (140 ms) closely; ported as `--tv-bs-duration-ui: 160ms` |
| Shadows | `MASTER.md --shadow-sm…xl` (rgba black lifts) | `--depth-hover/overlay` | **Not ported.** Adopted system is flat surfaces with hairlines (`MASTER.md` override; DESIGN_MASTER_V3 §6.3 depth-as-affordance) |

## 4. Rejected / deferred items (not ported)

| Item | Reason |
| --- | --- |
| `MASTER.md` palette table (`#2563EB`, `#0891B2`, `#D97706`, `#F8FAFC`, …) | Explicitly rejected by the blank-slate's own authority override |
| Inter font import | Same override; production uses Instrument Sans |
| `.btn-primary` amber CTA, `.card` shadow-lift hover, glassmorphism modal overlay | Generated component specs bound to rejected palette; structural pattern re-bound to production tokens instead (see §5) |
| GSAP Flip page-transition spec, ambient-light blobs, BlurView glass headers | Motion/glass effects outside the adopted system; masterplan owns motion via scene scripts |
| `MASTER.md --space-*` / `--shadow-*` variables as tokens | Values either identical to existing `--s-*` (spacing) or contradicting the flat-surface rule (shadows) |

## 5. Port priority and what landed in this wave

Priority order used:

1. **P1 — color ramp**: void/graphite/steel/fog/bone/paper + four signal/state
   colors + the semantic alias set. Foundation for every later wave; zero
   conflicts under the `--tv-bs-*` namespace.
2. **P2 — typography**: font stacks (Instrument Sans, IBM Plex Mono) and the
   measured type scale.
3. **P3 — shape/motion**: radius system, easings, UI duration.
4. **P4 — opt-in component classes**: `.tv-btn` (+ `--primary`/`--secondary`
   modifiers) and `.tv-card`, ported into `@layer components` inside
   `tokens.css`. Structure follows the `MASTER.md` component spec (12×24 px
   padding, 600 weight, 200 ms ease, hover lift −1 px / −2 px) but **colors bind
   only to ported production tokens** (bone-on-graphite primary, cobalt-outline
   secondary, graphite-900 card with hairline border instead of the rejected
   amber CTA / shadow lift). Transforms sit behind
   `prefers-reduced-motion: no-preference`.

Deliberately **not** done in this wave (breaking-change ban):

- No existing variable renamed, re-valued, or removed; the PAPER/INSTRUMENT/
  SEMANTIC ramps stay byte-identical.
- No markup, layout import list, or route touched — nothing references
  `.tv-btn`/`.tv-card` yet, so the rendered product cannot change.
- Component classes live in `@layer components`, which today loses to the
  unlayered legacy sheets; adoption happens per-route later without cascade
  surprises.

## 6. Verification record

Recorded in the commit message evidence block:
`pnpm install --frozen-lockfile` → `pnpm --filter @akc/web typecheck`
(`tsc --noEmit`) → `pnpm --filter @akc/web test` (`vitest run`), all green with
the pre-existing suite count intact.
