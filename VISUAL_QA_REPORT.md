# FOLYNTA v1 cinematic frontend visual QA report

Review date: 2026-08-03

Build ID: `fInuyY5S3_esZDbQXJ7SW`

Python regression: `1517 passed`, total coverage `88.27%`

Authority: `D:\FOLYNTA_NEAR_PERFECT_BACKEND_AND_CINEMATIC_WORLD_CLASS_FRONTEND_MASTERPLAN_FINAL_v1_KO_2026-08-03.md`

Authority SHA-256: `adc06f84ae9a6d7f455b8fcfec4d7afc8b9f83132b4f5baaaaee87254ae925c7`

## Verdict

**Repository visual, interaction, accessibility, and lab-performance gates: PASS.**

**Overall release gate: PRODUCTION-REJECT.**

Storybook static build and the connected live browser journey both pass. The
live journey covers registration, email verification, document upload,
analysis, compilation, SSE replay, provenance navigation, export, and purge.

The local release candidate implements the seven-act clean-room homepage and
passes every repository-owned visual gate. This does not substitute for the
masterplan's private Q1/Q2 labels, Q3 100,000-page field shadow, three-repeat
public benchmark, production-provider drills, independent beta, or legal and
commercial approvals.

## Final evidence

| Gate                       | Result                                                                                                                       |
| -------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| Responsive evidence        | 16/16 captures passed: KO/EN × default/reduced motion × 1920, 1440, 1024, 390                                                |
| Seven-scene contract       | Exact ordered scene IDs `01-product-film` through `07-final`                                                                 |
| Actual-source proof        | Official 2,276,931-byte DART PDF, page 30/121, rendered by PDF.js 6.2.108                                                    |
| PDF SHA-256                | `fb998430db82774afc0d69090383650421ab9a14e6e37c7f32821aa1c6a32eee`                                                           |
| Browser matrix             | 9/9 passed: Chromium at 360/390/768/1024/1280/1440/1920, Firefox 1440, WebKit 1440                                           |
| Accessibility matrix       | 7 passed, 1 intentional mobile duplicate skip; forced colors, 200% desktop text, 12px visible-text floor, 14px control floor |
| Visual regression          | 11/11 approved route baselines passed                                                                                        |
| Console and page errors    | 0 / 0 across all 16 captures                                                                                                 |
| Horizontal overflow        | Maximum 0px                                                                                                                  |
| Actual PDF canvas          | Minimum captured width 487px                                                                                                 |
| ESLint / strict TypeScript | PASS / PASS                                                                                                                  |
| Production build           | PASS, Next.js 16.2.12 standalone                                                                                             |

Evidence locations:

- `artifacts/folynta-v1-visual-qa/report.json`
- `artifacts/folynta-v1-visual-qa/{ko,en}/{default,reduced}/{viewport}/home.webp`
- `artifacts/lighthouse/folynta-v1-mobile.json`
- `artifacts/lighthouse/folynta-v1-desktop.json`
- `apps/web/e2e/visual-baselines/desktop/win32/visual-regression.spec.ts/`

## Lighthouse 12.8.2 lab results

| Profile          | Performance | Accessibility | Best practices | SEO |     LCP | CLS |  TBT | Initial script transfer |
| ---------------- | ----------: | ------------: | -------------: | --: | ------: | --: | ---: | ----------------------: |
| Simulated mobile |          97 |           100 |            100 | 100 | 2,407ms |   0 | 96ms |           208,870 bytes |
| Desktop          |         100 |           100 |            100 | 100 |   601ms |   0 |  0ms |           208,870 bytes |

The masterplan budgets are met: mobile performance ≥90, accessibility 100,
best practices ≥95, SEO ≥95, LCP ≤2.5s, CLS ≤0.1, TBT ≤200ms, and initial
script transfer below 220KB. These are local standalone lab measurements, not
canonical-domain field p75 Core Web Vitals.

## Scene review

| Scene                  | Product-truth and composition decision                                                        | Result |
| ---------------------- | --------------------------------------------------------------------------------------------- | ------ |
| 01 Product Film        | Static-first verified folio; no WebGL hero or generated proof                                 | PASS   |
| 02 Intake              | Local manifest, file classes, dedupe and excluded state before processing                     | PASS   |
| 03 Recovery Theater    | Detected → recovered → verified; Basic/Technical; no timer progress                           | PASS   |
| 04 Actual Source       | DART defaults in KO, SEC defaults in EN; actual PDF versus truthful Inline XBRL HTML boundary | PASS   |
| 05 Knowledge Formation | One receipt projects into vault, atomic note, relation and exports                            | PASS   |
| 06 Trust               | Verified, recovered-and-verified, unresolved and excluded remain distinct                     | PASS   |
| 07 Final               | One restrained document-upload CTA and truth-bound supporting copy                            | PASS   |

## Motion review

| Before                                       | After                                                                             | Why                                                                           |
| -------------------------------------------- | --------------------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| Built-in `ease` on color and border feedback | `cubic-bezier(0.23, 1, 0.32, 1)` with 140–180ms explicit-property transitions     | Strong ease-out feels responsive and never animates unrelated properties      |
| Potential first-load PDF work below the fold | Intersection-gated PDF.js and source-byte load with a stable intrinsic region     | Keeps product proof real while protecting initial render and layout stability |
| Historical decorative or timer-like motion   | Finite press/state feedback only; no loops, springs, fake progress, or WebGL hero | Every motion now explains state or input feedback                             |

Verdict: **Approve.** No feel-breaking regression, high-frequency animation,
`transition: all`, `scale(0)`, `ease-in`, layout-property animation, ungated
hover motion, or reduced-motion information loss remains. Active feedback is
interruptible CSS transition motion and stays below 300ms.

## External gates that remain open

- private Q1: 1,500 pages and at least 10,000 labeled facts
- private Q2: 5,000 pages and at least 30,000 labeled facts
- Q3 field shadow: 100,000 pages
- three-repeat rights-cleared public benchmark artifacts
- production RunPod billing/concurrency/fault evidence
- production R2 role, lifecycle, deletion and restoration evidence
- production Postgres RLS, backup and restoration drill evidence
- independent private-beta and assistive-technology evidence
- legal, domain, licensing, claim, and commercial approval

Until those artifacts exist, `PRODUCTION-REJECT` is mandatory even though the
repository-owned frontend gates pass.
