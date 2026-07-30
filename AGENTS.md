# Structara Agent Instructions

## Mission

Build Structara as an ultra-premium Knowledge Compiler brand and a precise,
source-verifiable enterprise product. Optimize for clarity, trust, craft,
accessibility, and measured performance rather than feature count.

## Mandatory context

Before UI, UX, copy, motion, or 3D work, read:

- `.agents/skills/structara-brand-experience/SKILL.md`
- `.agents/skills/structara-asset-director/SKILL.md` for every image, 3D,
  screenshot, diagram, texture, video, glyph, or sourced asset task
- `STRUCTARA_BRAND_DECISIONS.md`
- the active route in `PAGE_MANIFEST.yml`
- the relevant masterplan section

## Design authority

1. Truth, safety, privacy, and legal requirements
2. The Structara masterplan
3. The Structara Brand Skill
4. Approved design decisions
5. Approved route brief
6. External skills
7. Library defaults

## Build order

1. Semantic information architecture
2. Accessible components
3. Responsive composition
4. Functional interaction and real states
5. Motion and progressive 3D
6. Browser, accessibility, and performance QA

## Technical defaults

- Next.js App Router and strict TypeScript
- CSS variables as the token source of truth
- Accessible native semantics before custom widgets
- React Three Fiber for production 3D with a static fallback
- PDF.js and virtualized document surfaces where applicable
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
- Validate assets in the actual route at 1920, 1440, 1024, and 390 widths.

## Required evidence

Before completion, run lint, typecheck, unit, E2E, accessibility, visual,
production build, and Lighthouse checks that exist in the repository. Capture
marketing and product routes at 1920, 1440, 1024, and 390 widths, including
reduced motion. Record evidence in `VISUAL_QA_REPORT.md`.
