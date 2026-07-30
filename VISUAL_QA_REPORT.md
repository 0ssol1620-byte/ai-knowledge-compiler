# Structara Visual QA Report

## Baseline

The previous landing used the AI Knowledge Compiler identity, a conventional
SaaS hero, incomplete public navigation, and no Structara route system.

## Viewport matrix

Marketing: 1920 x 1080, 1440 x 900, 1280 x 800, 1024 x 768, 768 x 1024,
390 x 844, and 360 x 800.

Product: 1920 x 1080, 1440 x 900, 1280 x 800, 1024 x 768, 768 x 1024,
and 390 x 844.

The browser matrix covers the complete public route registry, the complete
canonical product route registry, representative narrow layouts, processing
source and result states, and reduced motion.

## Critical

None.

## High

None.

## Automated evidence

- ESLint: pass
- TypeScript: pass
- Next.js production build: pass
- Vitest: 54 passed
- Playwright: 14 passed, 4 intentional cross-project skips
- Axe: no violations on 11 representative public, auth, and product routes
- Lighthouse production:
  - Performance 96
  - Accessibility 100
  - Best Practices 96
  - SEO 100
  - First Contentful Paint 1.2 s
  - Largest Contentful Paint 2.7 s
  - Total Blocking Time 50 ms
  - Cumulative Layout Shift 0
- Python:
  - repository tests: 217 passed
  - core packages: 41 passed
  - scheduler and URL fetcher: 117 passed
  - benchmark: 24 passed
  - GPU common runtime: 22 passed
  - model registry, repository policy, and deployment contract: pass
- Mypy official CI scope: 136 source files clean
- Ruff: pass

The machine-readable Lighthouse report is
`artifacts/lighthouse/home-production.json`.

## Manual browser findings

- The homepage renders the server poster before WebGL hydration; no blank hero
  frame remains.
- The 11-section homepage reads as one editorial narrative rather than stacked
  template cards.
- Public and product shells share the same brand and provide explicit
  round-trip navigation.
- Narrow marketing layouts preserve the proof object; narrow product layouts
  switch to a usable bottom navigation.
- Authentication and onboarding remain uncluttered while preserving legal and
  security context.
- Processing, review, Markdown, sources, and versions surfaces preserve dense
  information hierarchy without nested application shells.
- No `transition: all`, layout-property animation, scale-from-zero interaction,
  or unbounded decorative motion is present in the Structara system.

## Accepted release notes

- Best Practices 96 is caused by the browser inspector warning on the dynamic
  nonce CSP and the deliberate `no-store` policy preventing back-forward cache;
  both are security behaviors, not visual or interaction defects.
- Final wordmark licensing, Figma synchronization, domain clearance, and the
  production canonical hostname require owner-controlled actions and do not
  block the code release.
