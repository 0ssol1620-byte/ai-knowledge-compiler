# TAVONEL visual QA report

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

## 2026-09-27 CI baseline follow-up

The legacy `enterprise-refresh.css` layer contained twelve labels below the
approved 12px floor and four nonstandard responsive breakpoints. Those labels
now use 12px; the responsive rules use the approved 1280, 1024, and 768px
boundaries with exclusive upper bounds. Two privacy-card labels were also
raised to 12px, and two existing 767px queries now use `width < 768px`, which
preserves their previous boundary behavior. The source blueprint ratchet is
now 421 small-text declarations and 39 nonstandard breakpoints; both hold.

The affected home and `/solutions/enterprise` routes are scheduled for
automated screenshots at 1920, 1440, 1280, 1024, 768, 390, and 360px plus
reduced motion in the exact-head CI artifact. Those captures, visual baseline
comparison, accessibility, build, and Lighthouse results are pending for this
change. **FOUNDER VISUAL REVIEW REQUIRED** before visual acceptance.

## 2026-09-27 Linux baseline capture

The first imported eleven desktop snapshots were copied from the artifact's `e2e/visual-baselines/` folder. That folder contains the older FOLYNTA composition; it was **not** the live `toHaveScreenshot` output. Exact-head run `36286642134` at `d348c3c` exposed the mistake: the current TAVONEL home measured 1440×16620, while the imported FOLYNTA home measured 1440×7851. The eleven current images now come from that run's `test-results/*-actual.png` captures, with the desktop viewport fixed at 1440×900. The marketing-home actual capture had identical SHA-256 across all three retries; the complete run artifact remains available for comparison. These images establish a regression reference, not composition or customer-experience approval. The seven-width and reduced-motion captures remain separate evidence. **FOUNDER VISUAL REVIEW REQUIRED** before visual acceptance.

Exact-head run `36287478291` passed the new desktop comparison, then its browser matrix found a compact-width Knowledge Studio title compressed to zero width by the header's inline metrics. The header now gives the title a full first row and wraps the metrics under 768px. The matrix also expected the single-pane processing navigation at 768 and 1024px even though that product shell only renders it through 700px; that assertion now follows the actual breakpoint and still checks the mobile controls at 360 and 390px. The refreshed matrix and seven-width captures must pass before this repair is accepted. **FOUNDER VISUAL REVIEW REQUIRED**.

## 2026-09-27 legacy typography accessibility repair

Exact-head run `36288116092` passed the desktop visual comparison, three-browser matrix, seven-width and reduced-motion captures, PostgreSQL boundary checks, Lighthouse, and the Python/Web suites. Its final accessibility step exposed legacy visible text below 12px and controls below 14px. Commit `4a8b806` lifts 398 legacy CSS declarations from 6–11px to the 12px floor, raises affected interactive controls to 14px, and gives page-scale sample facsimiles readable text alternatives. The blueprint small-text ratchet fell from 421 to 23; the accessibility test itself was not changed. A separate Claude Opus 5.5 worktree reported 7 accessibility cases passed with the intentional mobile 200% skip, 104 seven-width/reduced-motion evidence cases passed, TypeScript, changed-file ESLint, 383 Vitest cases, and blueprint check passed locally. The parent independently confirmed the committed diff has no whitespace errors and the blueprint check passes.

The new typography alters visual composition, so existing screenshots are not an approval of this version. Exact-head GitHub run `36290289174` passed Web/contracts, Lighthouse, the live-browser journey, PostgreSQL role boundaries, and the infrastructure/contract checks; the visual comparison failed against the former small-text screenshots. Its eleven expected/actual/diff pairs are retained in the run artifact and the local `visual-a11y-4a8b806/REVIEW.html` review sheet outside the repository. Because the workflow stops after a visual mismatch, the later matrix, evidence, and accessibility steps were skipped in that run. In a separate Windows development-server run, all seven Chromium widths and WebKit passed; Firefox first hit a transient `NS_BINDING_ABORTED` navigation error, then passed on a focused retry. The Claude Opus worktree's local accessibility and evidence results above are not Linux exact-head CI results. Windows standalone startup also hit an `EPERM` resolving React under `.next/standalone`; the development-server matrix does not prove that startup path.

Any visual baseline update requires a recorded human G-1/G-2 review under `DESIGN_MASTER_V3.md` §25.6; automated passes alone cannot supply that approval. **FOUNDER VISUAL REVIEW REQUIRED**.

## 2026-09-27 full-resolution product review after comparison failure

Inspection of the eleven full-resolution Linux actual images exposed defects already present in the previous pixel baselines: the Knowledge Studio graph and connected relations collided; `/projects` rendered its summary, toolbar, and table close to browser defaults; `/integrity` rendered its status register, queue, and inspector without their intended hierarchy. These are visible defects, not acceptable visual changes to ratify. The first request to approve the eleven-image comparison was withdrawn in commentary after discovery; the former snapshots are not proposed as a new creative baseline.

The Knowledge Studio Graph, Notes, Relations, and Evidence views now have responsive structure, readable relation rows, labeled evidence cards, keyboard-reachable scrolling regions, and a sidebar width constrained at the 768px rail breakpoint. Separate Windows dev-server captures at 1440, 768, 390, and 360px in Korean and English were inspected. The subagent reported no route overflow, text collisions, visible text below 12px, or controls below 14px in those captures; route-specific axe checks showed no WCAG A/AA violations on the four views at 1440 and 390px. A focused Knowledge Studio browser test passed ten consecutive desktop/mobile runs. Copies of the screenshots are in the private `knowledge-fix/graph` and `knowledge-fix/tabs` audit folders outside the repository; they are implementation evidence, not approval.

The Projects and Integrity surfaces now have page-specific CSS in `apps/web/src/app/operations-surfaces.css`. Windows dev-server full-page captures at all seven widths plus reduced-motion captures at 1440 and 390px are retained in the private `ops-surfaces-fix/` audit folder outside the repository. Their local browser checks reported zero document overflow and zero visible text below 12px. Targeted Projects/Integrity functional and accessibility checks passed after a forced-colors cold-compile timeout was rerun. The screenshots also expose an existing fixed mobile navigation bar over the middle of a full-page capture; actual scroll-end clearance still needs direct confirmation. The 768px sidebar overrun is addressed by the Knowledge Studio change and needs verification in the combined tree.

These repairs are integrated only in the local PR #82 checkout as of this report. Existing Linux pixel baselines for three product routes now necessarily fail, and exact-head Linux browser/accessibility/visual acceptance has not run on the combined code. Full-web and founder G-1/G-2 checks remain open. **FOUNDER VISUAL REVIEW REQUIRED**.

After integration, the parent ran the blueprint check (23/23 small-text and 39/39 breakpoint ratchets held), changed-file ESLint, TypeScript, all 67 Web Vitest files / 383 tests, and a local production build; all passed. The local `next` executable resolved to 16.2.12 while the declared current package is 16.3.6 because the Windows dependency synchronization was interrupted near completion, so this build is not an exact-lockfile release receipt. `interactions:check` initially found four stale internal links and one false positive: the named, keyboard-focusable `tabpanel` had `aria-labelledby` rather than `aria-label`. The links now target existing Docs, Privacy, Projects, and Knowledge routes; the guard accepts either accessible naming relation. It reports zero blocking findings, with 110 nonblocking disabled-control reason advisories still present across legacy components. `impeccable detect src` initially flagged two 3px side accents on an existing system composition; the accents were reduced to 1px and the detector now passes. CI and browser checks must be rerun after these last edits. **FOUNDER VISUAL REVIEW REQUIRED**.
