# TAVONEL visual QA report

## 2026-09-26 standalone film repair

The `/film` scene had a real layout defect in the 2026-09-24 Linux CI capture:
the route was wrapped in authenticated dashboard chrome and its retired
`public/styles/structara.css` film rules were never loaded. The model labels and
values consequently ran together. The route now renders without dashboard
chrome, loads scoped film styles, and gives the five-model comparison a full
width desktop surface. The mobile comparison scrolls horizontally with a
visible instruction and keyboard focus. The film heading now describes the
same-page comparison rather than claiming a measured routing advantage, the
mobile header retains the measurement date, and the display brand is TAVONEL.

Local verification: TypeScript, focused ESLint, three film component tests,
67 web unit files/383 tests, interaction-contract check, Impeccable detection,
and production build pass. A one-run mobile Lighthouse check of `/film` reported
performance 96, accessibility 100, best practices 100, SEO 100, LCP 2.7s,
and CLS 0 on the final build.
The new browser layout assertion passes at 1920, 1440, 1280, 1024, 768, 390,
and 360px plus 1440 reduced motion; axe-core WCAG 2.2 AA checks report zero
violations on the 390px measured scene. Production-build captures at all eight
conditions, with SHA-256 provenance, are in
`docs/audit/visual/2026-09-26/README.md`. The local dependency junction used
Next.js 16.2.12, while the lockfile declares 16.3.3; exact-version confirmation
must come from CI.

**FOUNDER VISUAL REVIEW REQUIRED.** The eleven older approved Linux screenshot
baselines remain unchanged. The homepage, benchmark, legal, and product route
differences still need independent review; this repair does not approve those
screens or clear the public legal-policy placeholder. Do not deploy or merge a
production release based on the film repair alone.

## 2026-09-23 CI repair and Knowledge Studio review

This section is the latest local assessment for `codex/ci-repair-20260923`.
The 2026-07-31 baseline below is historical; its "no critical findings" and
"all gates pass" conclusions do not describe this branch. The local product
was run in explicit demo mode, so fixture content is not customer proof.

The Knowledge Studio previously had no usable relationship-card styling, and
its fixed 240px sidebar overlaid the 72px navigation track at 768px. At 1024
and 1280px, the three-column studio exceeded the available content width while
the document itself reported no horizontal overflow. The branch now sizes the
sidebar to its grid track, switches the studio to two panes before its columns
stop fitting, restores search and perspective controls on mobile, and uses a
source/evidence card composition with an accessible table alternative. The
browser matrix now asserts that the sidebar cannot overlap the content.

Automated local evidence:

- Web ESLint, strict TypeScript, Next.js production build, 67 Vitest files / 383
  tests, interaction contracts (169 files, 72 routes, zero blocking findings),
  and Impeccable detection: pass.
- Browser matrix: 9/9 projects pass across 360, 390, 768, 1024, 1280, 1440,
  and 1920px, plus desktop Firefox and WebKit. A 360px processing-tab failure
  was traced to clicking before client hydration and fixed in the test's
  navigation readiness boundary.
- The public-route evidence suite passes 80/80 checks across the same seven
  widths and a 1440px reduced-motion project, including horizontal overflow,
  200% homepage zoom, and console-error assertions.
- Lighthouse: four public routes, three mobile runs each, pass all configured
  blocking assertions. The unused-JavaScript advisory remains on each route.
- Knowledge Studio screenshots were captured at all seven required widths
  with reduced motion in a demo-mode production build. The earlier 768px
  capture exposed the sidebar overlap; the recapture shows the header and
  workspace fully inside the viewport. See
  `docs/audit/visual/2026-09-23/README.md` for source and SHA-256 provenance.
- After the first remote CI run, the Knowledge Studio CSS was brought back
  within the V3 blueprint ratchet (422/422 legacy small-font findings and
  39/39 legacy breakpoint findings). The seven-width Chromium plus Firefox
  and WebKit matrix passed again (9/9), and all seven screenshots were
  recaptured from the changed production build. The relationship cards now
  start below the canvas header rather than floating midway down the view.

Release blockers remain:

- The desktop visual-regression suite has six screenshot mismatches, including
  the homepage and Knowledge Studio on Windows. The eleven approved Linux
  images were present but Playwright looked in its default snapshot folder;
  this branch now points the test at the checked-in platform-specific baselines
  and captures at their 1440px width. A local rerun compares the real files and
  fails on the homepage: current 1440 × 16,587px versus approved 1440 ×
  7,791px, with 52% of pixels different. The approved baselines have not been
  overwritten. **FOUNDER VISUAL REVIEW REQUIRED** before approving a new
  composition or its baselines.
- The Linux CI artifact for run `35850962952` shows the 1280px marketing
  homepage at 15,882px tall. The visual review also shows long stretches of
  whitespace and repeated text-led sections on the product pages. A green
  screenshot test made by copying these captures into the baseline would
  certify the current composition, not solve the buyer-journey problem.
- The accessibility matrix fails its visible-text minimum (12px) and core
  control minimum (14px) on multiple marketing and product routes. The home
  sample document contains visible 5–11px text; some processing controls are
  8–11px and marketing calls to action are 13px. Forced colors and desktop
  200% scaling passed, but the small-text findings remain release work. The
  Knowledge Studio search field was raised to 14px in this branch; the
  cross-route typography debt is not resolved.
- Browser and screenshot checks used the local demo fixture. They cannot
  establish production readiness, paid-checkout eligibility, legal approval,
  or customer-data authorization.

These passing checks do not grant visual or release approval.

## Release baseline

The 2026-07-31 remediation treats TAVONEL as one connected, source-verifiable
system: English-default marketing, authentication, onboarding, product,
document, knowledge, enterprise, administration, pricing, public proof, and
developer surfaces. The release baseline is a repository release candidate, not
a production go-live claim.

## Current critical findings

None in the executed local scope.

## Trust and interaction findings fixed

- Next.js no longer builds with `ignoreBuildErrors: true`; the production build
  now executes its TypeScript phase.
- Quick Convert previously displayed 50 MB while accepting 256 MB. UI and client
  policy now share a 50 MB-per-file, 30-file contract.
- Quick Convert no longer promises folder upload because no directory input is
  implemented on that surface.
- External-processing copy now states the real policy boundary: private-first,
  with explicit workspace consent required before external providers are used.
- The JTC DART demonstration previously placed an absolute rectangle near a
  table cell. The detached overlay is removed and the exact revenue value cell
  is the selected evidence target.
- Generic app header CTAs previously rendered as buttons without handlers. Every
  `/app/*` header CTA now resolves to an internal route and is covered by route
  mapping and browser regression tests.
- Fixed product fixtures previously exposed filters, tabs, version actions,
  outline controls, graph nodes, and review actions as enabled buttons without a
  mutation contract. These controls are now explicitly disabled and explain
  that an authorized connected workspace is required.
- Demo administration and settings pages now identify themselves as
  illustrative snapshots. Write-looking controls are disabled in demo mode;
  live mode still renders the live components.
- Custom Next.js verification output directories are ignored by Git and ESLint,
  preventing generated bundles from polluting source lint results.

## Current automated release evidence

Executed with Node.js 22.14.0 and pnpm 11.9.0:

- ESLint with zero warnings: pass
- strict TypeScript: pass
- Next.js 16.2.12 production build: pass
  - optimized compilation: pass
  - internal TypeScript phase: pass
  - page-data collection: pass
  - static-page generation: pass
  - build-trace collection: pass
- Vitest: 21 files and 72 tests passed
- Playwright: 24 passed and 4 intentional project-scope skips
- TypeScript-AST interaction gate: 0 enabled dead buttons
- all registered public routes on desktop: successful response, one H1, unique
  title, and no horizontal overflow
- all registered app/document routes on desktop: successful response, one H1,
  route information architecture, no horizontal overflow, and valid app header
  action destinations where applicable
- Quick Convert contract: desktop and mobile pass
- JTC exact revenue-cell evidence: desktop and mobile pass
- demo administration/settings non-writable boundary: desktop and mobile pass
- shell actions, fixed Knowledge/Review/API/Processing studios, and unconfigured
  SSO/recovery boundaries: desktop and mobile pass
- representative mobile auth, onboarding, product, and document surfaces: pass
- reduced motion: pass
- Axe representative WCAG A/AA suite: no violations
- asset manifest: 9 assets verified
- deterministic asset names: 119 files verified
- cryptographic derivative hashes: 21 verified
- canonical contracts TypeScript check: pass

## Viewport evidence

The current Playwright run covers Desktop Chrome and the iPhone 13 device
profile. The repository also retains the earlier 1440 × 900, 1024 × 768, and
390 × 844 manual evidence described by the preceding baseline. Those exact
manual captures were not regenerated in this remediation, so they are retained
as prior evidence rather than presented as a new measurement.

The current browser run verifies:

- marketing ↔ product round trip
- complete public/app route crawls on desktop
- representative product and document flows on mobile
- Quick Convert at desktop and mobile sizes
- DART proof at desktop and mobile sizes
- demo administration/settings boundaries at desktop and mobile sizes
- reduced motion
- CSP nonce and hardened headers
- representative Axe checks

## Proof-system assessment

The canonical UI coordinate space remains integer `bbox1000`, normalized to the
post-rotation page. The source viewer applies the same rectangle to the preview
and overlay layer, with zoom and rotation applied to their common parent. The
DART marketing proof does not claim to be a PDF-coordinate overlay; it now marks
the exact deterministic XBRL-derived revenue cell in the rendered source table
and links it to receipt, taxonomy, source line, unit, and archive hash.

## Claim and benchmark boundary

- The public benchmark snapshot remains `unavailable`; unmeasured values render
  as unavailable rather than zero or an invented score.
- The DART fixture is public-source product evidence, not a benchmark quality
  result.
- Customer logos, quotes, certifications, security attestations, benchmark
  victories, and commercial prices remain absent unless registered evidence is
  available.
- Training-pool language is limited to explicit opt-in and approved workspace
  policy; the blocked absolute training claim is not published as product copy.

## Performance evidence boundary

The retained Lighthouse artifact from the preceding baseline reports
Performance 93, Accessibility 100, Best Practices 96, SEO 100, LCP 3.2 s, TBT
40 ms, CLS 0, and no console errors under its recorded simulated-mobile lab
conditions. Lighthouse was not rerun in this remediation. Production p75 LCP,
INP, and CLS require a canonical deployment and real traffic.

The root layout intentionally remains dynamically rendered because a
per-request CSP nonce is applied by `src/proxy.ts`. Static conversion without a
replacement nonce design is not an acceptable performance optimization.

## Remaining owner or deployment gates

- legal/domain clearance for `TAVONEL`
- final licensed wordmark and owner design-source synchronization
- approved commercial price book
- consented customer or participant evidence
- rights-cleared benchmark corpus and real model/hardware/cost/canary evidence
- production IdP, payment, email, and optional external-provider configuration
- deployed header scan, operational drills, canonical-domain RUM, and field Core
  Web Vitals

## Release conclusion

The locally executable visual, trust, interaction, accessibility, contract, and
asset gates pass. Production release still depends on the external gates above.
No status label should be interpreted as replacing those missing artifacts.
