# TAVONEL Agent Instructions

## Mission

Build TAVONEL as an ultra-premium Knowledge Compiler brand and a precise,
source-verifiable enterprise product. Optimize for clarity, trust, craft,
accessibility, and measured performance rather than feature count.

## Mandatory context

Before UI, UX, copy, motion, or 3D work, read:

- `.agents/skills/tavonel-brand-experience/SKILL.md`
- `.agents/skills/tavonel-asset-director/SKILL.md` for every image, 3D,
  screenshot, diagram, texture, video, glyph, or sourced asset task
- `TAVONEL_BRAND_DECISIONS.md`
- the active route in `PAGE_MANIFEST.yml`
- the relevant section of `design-system/tavonel/DESIGN_MASTER_V3.md`

## Design authority

1. Truth, safety, privacy, and legal requirements
2. `design-system/tavonel/DESIGN_MASTER_V3.md`
3. `design-system/tavonel/decision.md` — gate decisions and approved static
   comps. Where it contradicts the masterplan, it wins.
4. The TAVONEL Brand Skill
5. Approved route brief
6. External skills
7. Library defaults

## Build order

1. Semantic information architecture
2. Accessible components
3. Responsive composition
4. Functional interaction and real states
5. Motion
6. Browser, accessibility, and performance QA

## Technical defaults

- Next.js App Router and strict TypeScript
- CSS variables as the token source of truth; `src/styles/tokens.css` is the
  token layer and new CSS goes inside `@layer`
- Accessible native semantics before custom widgets
- No WebGL. `decision.md` G-C dropped TIER 1 3D and W0 removed `three`,
  `@react-three/fiber`, and `@react-three/drei`. The hero is a drop zone.
- PDF.js is **not installed**. `pdfjs-dist` arrives in W4 together with the
  `SourceRef` rotation/cropbox contract (G-E). Until then the source surface is
  a thumbnail image, and document virtualization is `react-virtuoso` only.
- Source-linked fixtures; no fabricated proof

## Asset routing

- Classify every asset T0–T4 before production.
- Source order is actual product/public proof, code/SVG, custom 3D, image
  generation, then licensed external media.
- Never use image generation for product evidence, benchmarks, customers,
  security claims, certifications, or logos.
- Search/downloaded assets require source, creator, license, commercial-use
  evidence, SHA-256, and an allowed-use scope before repository intake.
- Store generated masters and provenance; web exports are derivatives.
- Validate assets in the actual route at all seven verification widths below.

## Verification viewports

`1920 · 1440 · 1280 · 1024 · 768 · 390 · 360`, plus a reduced-motion pass.

This file used to ask for four widths while the masterplan asked for seven and
`playwright.config.ts` ran two. W0 settled it on seven — see
`design-system/tavonel/DESIGN_MASTER_V3.md` §20 — and the config now has one
project per width running `e2e/evidence.spec.ts`.

## Required evidence

Before completion, run lint, typecheck, unit, E2E, accessibility, visual,
production build, and Lighthouse checks that exist in the repository:

```
pnpm --filter @akc/web lint
pnpm --filter @akc/web typecheck
pnpm --filter @akc/web test
pnpm --filter @akc/web interactions:check
pnpm --filter @akc/web exec impeccable detect src
pnpm --filter @akc/web test:e2e
pnpm --filter @akc/web build
pnpm --filter @akc/web lighthouse
```

Capture marketing and product routes at the seven widths, including reduced
motion. Record evidence in `VISUAL_QA_REPORT.md`.
