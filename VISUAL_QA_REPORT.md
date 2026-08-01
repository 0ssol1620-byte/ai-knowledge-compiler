# Structara v4 visual QA report

## Verdict

**Local Visual Quality Gate: 94/100 — Approved.**

- Critical findings: 0
- High findings: 0
- Medium evidence limitations: 3
- Deterministic visual baselines: 11/11 passed
- Accessibility projects: 4/4 passed
- Browser and responsive matrix: 9/9 passed
- Current-worktree capture matrix: 532/532 required

This approval applies to the repository release candidate and its exact build.
It is not a Production Ready claim. Canonical field performance, independent
assistive-technology review, and legal/brand/public-claim clearance remain open
external gates.

## Weighted score

| Criterion | Weight | Score | Evidence |
| --- | ---: | ---: | --- |
| Brand distinctiveness | 15 | 14 | Editorial source/proof/architecture language; restrained structural glyph system |
| Category comprehension | 10 | 10 | Source-to-knowledge proposition and primary actions are explicit |
| Asset craft | 15 | 13 | A01–A06 current-route scores are 94–97 |
| Product truth | 12 | 12 | T0–T2 boundaries and unavailable states remain visible |
| Composition | 10 | 9 | Product evidence dominates decorative support across the seven-width matrix |
| Typography | 8 | 8 | One hierarchy, bilingual line-break review, no key text below policy floors |
| Interaction | 8 | 8 | Enabled controls have routes or handlers; integrity actions are live-contract backed |
| Motion purpose | 6 | 5 | Event/state motion has full reduced-motion information parity |
| Responsive | 6 | 6 | 360–1920px matrix, no horizontal overflow or clipped core text |
| Accessibility | 5 | 5 | Axe, keyboard/focus, forced colors, 200% zoom, target-size contracts |
| Performance | 3 | 2 | Static-first/lazy asset policy passes; field CWV remains unmeasured |
| Claim truth | 2 | 2 | Demo, fixture, benchmark, security, and production boundaries are explicit |
| **Total** | **100** | **94** | **Pass (minimum 90)** |

## Executed evidence

The deterministic product suite completed with 77 passed tests, 17 intentional
project-scope skips, and zero failures. It includes eleven visual baselines,
forced colors, 200% desktop zoom, text/control floors, and WCAG A/AA checks.
The browser matrix completed nine runs across 360, 390, 768, 1024, 1280, 1440,
and 1920 widths using Chromium, Firefox, WebKit, and installed Microsoft Edge.

The live journey completed registration, verification, Quick Convert upload,
preflight, external-processing consent, compile, duplicate idempotency, SSE,
source/provenance navigation, integrity resolution, export download, and
deletion/purge against real local API and database processes.

The final capture contract covers:

- 13 actual routes and six named homepage signature scenes;
- 1920, 1440, 1280, 1024, 768, 390, and 360 widths;
- English and Korean;
- default and reduced-motion modes; and
- build ID plus revision, tracked diff, untracked content, and worktree-status
  hashes.

The fail-closed validator also checks every image hash and decoded dimension,
route status, console output, locale, main content, truth boundary, broken image,
CLS, target size, text floor, clipping, and horizontal overflow.

## Manual representative inspection

The production build was inspected at desktop and mobile widths for the landing
page, Integrity Console, and Knowledge Studio. The review found no broken image,
horizontal overflow, unnamed button, console error, or warning. English/Korean
switching, pressed state, truth disclosure, source/proof regions, and mobile
navigation remained coherent. A decorative structural SVG that clips at its
container edge is intentional background patterning, not content loss.

## Medium evidence limitations

1. Desktop Lighthouse is 99/100/100/100 with LCP 0.9s. Mobile simulated
   Lighthouse is 76/100/100/100 with LCP 4.7s; the shared global CSS payload is
   a documented performance block, while WebGL remains disabled on mobile.
2. Current canonical-domain field p75 LCP, INP, and CLS require real traffic.
3. Physical-device screen-reader and mobile-browser review requires an
   independent assistive-technology session.
4. Legal trademark, public-claim, dataset, model, and license clearance remains
   external to repository implementation.

No Medium item permits a stronger production claim. `Production Reject` remains
the correct platform gate until all external evidence in
`docs/release/EXTERNAL_GATES.md` is bound to one immutable release revision.
