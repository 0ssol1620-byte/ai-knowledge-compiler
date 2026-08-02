# FOLYNTA website v3 visual QA report

Review date: 2026-08-02

Authority: `D:\FOLYNTA_WEBSITE_TOTAL_CREATIVE_REBUILD_MASTERPLAN_FINAL_v3_FREE_ASSET_FIRST_NO_GENERATION_DEFAULT_KO_2026-08-02.md`

## Verdict

**Repository visual quality gate: 96/100 — approved.**

- Critical findings: 0
- High findings: 0
- Automated capture blockers: 0
- Current-worktree captures: 560/560 passed
- Approved visual baselines: 11/11 passed
- Browser/viewport matrix: 9/9 passed
- Lighthouse accessibility: 100 desktop and 100 mobile

This approval applies to the exact local release candidate. It does not claim
legal clearance, independent human creative approval, production provider
readiness, field Core Web Vitals, or consented customer evidence.

## Weighted review

| Criterion              |  Weight |  Score | Evidence                                                                    |
| ---------------------- | ------: | -----: | --------------------------------------------------------------------------- |
| Brand distinctiveness  |      15 |     15 | Deterministic Folio Synthesis direction; no generic generated imagery       |
| Category comprehension |      10 |     10 | Seven-scene source-to-knowledge narrative and one final collection action   |
| Asset craft            |      15 |     14 | T0/T1 source-first assets; 11 manifest records and 29 verified derivatives  |
| Product truth          |      12 |     12 | Durable event replay, source-native proof, and explicit fixture boundaries  |
| Composition            |      10 |     10 | Product evidence remains primary from 360 through 1920 px                   |
| Typography             |       8 |      8 | Bilingual hierarchy, 12 px text floor, 14 px core-control floor             |
| Interaction            |       8 |      8 | Zero enabled dead controls; market and locale switches remain explicit      |
| Motion purpose         |       6 |      6 | Finite state transitions and full reduced-motion information parity         |
| Responsive             |       6 |      6 | Seven widths, two locales, and two motion modes; no blocking overflow       |
| Accessibility          |       5 |      5 | Axe, forced colors, keyboard, 200% text, target-size, and contrast checks   |
| Performance            |       3 |      1 | Desktop lab performance 100; simulated mobile 88; field data remains open   |
| Claim truth            |       2 |      1 | Repository claims are bounded; legal and independent review remain external |
| **Total**              | **100** | **96** | **Pass (minimum 90)**                                                       |

## Executed evidence

- ESLint and strict TypeScript: passed with zero warnings or errors.
- Vitest and contracts: 52 files, 228 tests passed.
- Python: 1,489 tests verified. One Argon2 allocation failure occurred while
  builds competed for memory; the affected test passed immediately in an
  isolated retry.
- Playwright: 79 passed, 17 intentional project-scope skips, zero failures.
- Accessibility matrix: forced colors, 200% text, WCAG A/AA, keyboard and
  target-size contracts passed.
- Browser matrix: Chromium at 360, 390, 768, 1024, 1280, 1440 and 1920 px;
  Firefox and WebKit at 1440 px; 9/9 passed.
- In-app browser: KO at 1440, 1024 and 390 px plus EN at 390 px; exact seven
  scenes, no page overflow, no broken images, and no console warnings/errors.
- Visual regression: 11/11 approved route baselines passed.
- Current-worktree capture: 560/560 passed across 13 routes, seven homepage
  scenes, English/Korean, default/reduced motion, and seven widths.
- Asset validation: 11 manifest assets, 136 names, and 29 derivatives verified.
- Interaction contract: zero enabled dead controls.
- Storybook and Next.js 16.2.12 production builds: passed.

## Lighthouse lab results

| Profile          | Performance | Accessibility | Best practices | SEO |      LCP | CLS |   TBT |
| ---------------- | ----------: | ------------: | -------------: | --: | -------: | --: | ----: |
| Desktop          |         100 |           100 |            100 | 100 |   749 ms |   0 |  0 ms |
| Simulated mobile |          88 |           100 |            100 | 100 | 3,757 ms |   0 | 21 ms |

These measurements were taken with Lighthouse 12.8.2 against the production
standalone build. They are reproducible lab evidence, not canonical-domain
field p75 Core Web Vitals.

## Motion review

| Before                              | After                                                             | Why                                                                      |
| ----------------------------------- | ----------------------------------------------------------------- | ------------------------------------------------------------------------ |
| Historical decorative WebGL hero    | Static-first Folio Synthesis HTML/CSS scene                       | Keeps the signature visual legible, deterministic, and inexpensive       |
| Ambient or timer-like progress risk | Frozen durable-event replay with finite 120/160 ms state feedback | Motion now communicates real state and never invents processing progress |
| Motion-dependent emphasis           | Reduced-motion parity with the same content and controls          | Preserves comprehension and access without animation                     |

Motion verdict: **Approve.** No infinite loop, layout-property animation,
`transition: all`, scale-from-zero entrance, or reduced-motion content loss was
found.

## External gates that remain open

- legal and domain clearance for the FOLYNTA working name
- independent human creative review and physical assistive-technology review
- owner-approved commercial pricing
- consented customer proof and rights-cleared full public benchmark evidence
- production identity, payment, email, and external-model provider configuration
- canonical-domain security scan, operational drills, and field p75 CWV

The repository release candidate is approved; stronger production or public
evidence claims remain fail-closed until the relevant external evidence exists.
