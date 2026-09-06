# TAVONEL visual QA report

## Release baseline

Date: 2026-09-02 (Asia/Seoul)

Authority: `D:\TAVONEL_COMPETITIVE_WEB_WORKSPACE_MASTERPLAN_2026-09-01.md`,
the repository design authority, route manifest, and source-verifiable product
contracts. This is a local release-candidate assessment, not evidence that the
current `tavonel.com` deployment has been replaced.

Visual decision: **FOUNDER VISUAL REVIEW REQUIRED**

## Masterplan coverage

- Public IA implements Product, Solutions, Integrations, Security, Pricing,
  Enterprise, Research, Customers, Resources, Docs, Changelog, Demo, Login,
  and Signup. Unsupported customer stories and benchmark claims stay
  unpublished rather than being fabricated.
- The landing page implements all 12 prescribed scenes: hero; Read; Structure;
  World; Use; interactive proof; outputs; compile-before-retrieval; solutions;
  integrations; security; and pricing CTA.
- Pricing separates customer-facing dollars and included pages from the
  internal credit ledger. Free, Developer, Team, Scale, and Enterprise use one
  canonical catalog shared by UI and API.
- Workspace IA provides Home, Sources, World, Ask, Review, Activity, Projects,
  Connections, API, Usage, and Settings, with the prescribed five mobile tabs.
- Compile Cinema exposes source discovery and eight honest stages without
  converting unknown work into fake percentages. Completion routes into
  Review, World, export, and source-linked proof.
- World implements Graph, Directory, Ontology, Evidence, Versions, and Files.
  Citation viewing uses the actual source capability and fails closed when the
  document is unavailable.
- Ask, retrieval, and citations abstain when evidence is insufficient. Review
  preserves reason, source location, evidence, and decision context.
- Connections distinguish connected, available, and planned integrations;
  secrets remain server-side. Privacy mode and focus/details behavior are
  available in the authenticated shell.
- English and Korean public, onboarding, landing, and trial-film journeys are
  locale-aware. The language switch is keyboard-operable and persists through
  the locale endpoint.
- The 17-event product analytics contract is implemented without granting the
  analytics layer mutation or proof authority.

## Automated evidence

Executed against the production build with Node.js 22.14.0 and pnpm 11.9.0:

- ESLint: pass, zero warnings.
- Strict TypeScript: pass.
- Vitest: 60 files, 388 tests passed.
- API contract suite: 43 tests passed.
- Interaction AST gate: 171 files and 78 routes checked, zero blocking issues;
  104 non-blocking advisories.
- Impeccable source scan: pass.
- Next.js 16.2.12 production build: pass, including compilation, internal
  TypeScript, page-data collection, static generation, and build traces.
- Playwright production suite: 234 passed, 22 intentional project-scope skips,
  zero failures across desktop, mobile, seven evidence widths, and reduced
  motion.
- Axe representative WCAG A/AA checks: zero violations in the executed scope.
- Public-route console and page errors: zero in the executed scope.
- Horizontal overflow: absent across all registered evidence routes and widths;
  the homepage also passes at 200% zoom.
- Unapproved proof routes: confirmed unpublished.

## Viewport evidence

Fresh full-page PNG evidence is stored under
`apps/web/artifacts/visual-qa/2026-09-02/`.

- Widths: 1920, 1440, 1280, 1024, 768, 390, and 360 CSS pixels.
- Reduced motion: separate 1440 x 900 pass.
- Captures: 32 total, covering marketing home, product overview, compiled
  world, and workspace home in each evidence project.
- Visual regression: production baselines pass.
- Direct visual inspection: desktop landing, 390 px product overview, and 390
  px workspace home inspected for hierarchy, clipping, navigation, and content
  continuity.

Automated screenshots establish repeatable evidence, not human taste approval.
The founder gate remains open.

## Lighthouse

`pnpm --filter @akc/web lighthouse` passed all blocking assertions on 2026-09-02.
The run measured `/`, `/product`, `/security`, and `/pricing` three times each at
390 x 844 simulated mobile conditions.

- Performance: 93-96.
- Accessibility: 100 on all 12 runs.
- Best Practices: 100 on all 12 runs.
- SEO: 100 on all 12 runs.
- Best-of-three LCP: home 2856 ms, product 2844 ms, security 2689 ms, pricing
  2833 ms; the configured deploy ratchet is 2900 ms.
- TBT: 46-94 ms. CLS: 0-0.03.
- Transferred script: 164751-176999 bytes, below the 200000-byte ratchet.
- Lighthouse continues to report the configured non-blocking unused-JavaScript
  warning. It is retained as optimization debt rather than hidden or relaxed.

The product screenshot was moved from eager priority loading to native lazy
loading after it was measured competing with the mobile H1. The threshold was
not changed.

## Truth boundaries

- Public benchmark values remain unavailable until the required corpus,
  hardware, model, cost, canary, and signed evidence gates pass.
- No customer logo, quote, certification, commercial result, or security
  attestation is invented.
- Demo workspace data is explicitly marked as deterministic demo state.
  Production paths continue to use APIs and fail closed.
- Production IdP, payment, email, deployed-header, operational-drill, and RUM
  evidence remain deployment gates, not local UI claims.
- Legal/domain clearance, owner-approved commercial pricing, and founder visual
  approval remain owner gates.

## Conclusion

The locally executable masterplan implementation passes the current lint,
type, unit, API, interaction, browser, accessibility, responsive, production
build, and Lighthouse gates. Public deployment parity and founder visual
approval are deliberately not claimed by this report.
