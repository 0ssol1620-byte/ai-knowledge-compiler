# FOLYNTA visual QA report

## Release baseline

The 2026-07-31 remediation treats FOLYNTA as one connected, source-verifiable
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

- legal/domain clearance for `FOLYNTA`
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
