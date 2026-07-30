# Structara visual QA report

## Release baseline

The current build is one connected Structara system: English-default marketing,
authentication, onboarding, product, document, knowledge, enterprise, admin,
pricing, public proof, and developer surfaces. The previous generic dashboard
and disconnected landing identity are no longer the release baseline.

## Viewport evidence

Manual in-app browser review:

- homepage at 1440 × 900, 1024 × 768, and 390 × 844
- developer route at 1440 × 900
- pricing audience switch and estimator at 390 × 844
- DART proof tabs and mobile overflow at 390 × 844
- tablet navigation open and close at 1024 × 768
- console warning/error review on the current homepage

Automated Playwright review:

- all registered public routes on desktop with per-route heading and overflow
  assertions
- all registered app routes on desktop with route-specific IA assertions
- representative auth, onboarding, product, and document mobile routes
- marketing ↔ app round trip
- product evidence and deterministic diagram checks
- processing counts and source-linked output
- reduced motion
- WCAG A/AA Axe checks on representative public, auth, and product routes

## Critical

None.

## High findings fixed in this release

- 1024px header navigation crowded the brand and actions. Desktop navigation now
  changes to the explicit menu below 1180px.
- The mobile hero poster exposed only its upper breathing room before the
  object family. The mobile art-directed crop now brings source, evidence, and
  graph objects into the first asset frame without horizontal overflow.
- The DART demo used synthetic placeholder numbers. It now uses an acquired
  public JTC filing with receipt, taxonomy, source line, and hashes.
- Non-product marketing routes repeated one generic hero model. Solution,
  developer, proof/pricing, editorial/legal, and demo families now have distinct
  route visual systems.
- Pricing lacked the required audience switch and estimate controls. The page
  now includes six plan definitions, three audiences, page/scan/Precision/
  knowledge inputs, a recommended plan, credit range, and maximum credit draw.
- The mobile/desktop homepage E2E expected the retired synthetic-asset label.
  The assertion now matches the truthful first-party asset label.
- A healthy SSE heartbeat could indefinitely postpone durable-snapshot
  reconciliation while a terminal event was missed. The live workspace now
  gives terminal events presentation authority and independently reconciles the
  stored job snapshot every 10 seconds until terminal.

## Automated release evidence

- ESLint with zero warnings: pass
- strict TypeScript: pass
- Next.js production build: pass
- Vitest: 19 files, 56 tests passed
- Playwright: 16 passed, 4 intentional project-scope skips
- live API Playwright: 1 passed, including upload, compile, provenance, review,
  deterministic export, and deletion
- Axe: no A/AA violations in the representative route suite
- asset manifest, naming, and hashes: pass
- production Lighthouse mobile:
  - Performance 93
  - Accessibility 100
  - Best Practices 96
  - SEO 100
  - Largest Contentful Paint 3.2 s in simulated mobile lab
  - Total Blocking Time 40 ms
  - Cumulative Layout Shift 0
  - Speed Index 2.4 s
  - console errors: none
- Blender and derivative scripts: Ruff clean
- full repository backend evidence from the preceding release remains unchanged
  because this release touches frontend, documentation, and assets only

The Lighthouse machine-readable result is `work/lighthouse-home.json`. Field
p75 LCP/INP cannot exist until production traffic is available; the masterplan
field target remains LCP ≤2.5 s, INP ≤200 ms, CLS ≤0.1.

## Manual browser findings

- 1440 desktop preserves a balanced editorial split: copy remains primary and
  the signature object explains source → structure → evidence → knowledge.
- 1024 tablet uses a quiet two-action header and a fully operable menu.
- 390 mobile has no horizontal overflow; primary CTA, secondary CTA, trust line,
  art-directed hero, and output rail remain legible.
- The developer route uses a restrained code/evidence surface rather than the
  same marketing illustration.
- The pricing audience switch updates the plan set; estimator math is separately
  covered by deterministic unit tests.
- DART Original, Markdown, Vault, Graph, and Proof tabs expose distinct semantic
  states tied to the same public filing.
- The Graph state keeps the edge attached to an evidence record.
- Public and product shells retain a clear round trip.
- Browser console warnings and errors: none.

## AI-slop audit

The scanner reported 153 candidates in 11 pattern groups. Review disposition:

- accepted: real sequence numbers, graph node circles, monospace for code/hash/
  coordinates, source-document serif, functional focus underline, 2–3% paper
  texture gradients, and restrained hero circles required by the brand system
- rejected from production: generic generated editorial stills, atmospheric
  purple fields, chrome/glass AI objects, fake dashboards, fake customer proof,
  decorative particles, and generated product evidence
- no `transition: all`, `scale(0)`, `ease-in`, unbounded decorative loop, or
  layout-property animation exists in the Structara surface

## Accepted owner or deployment gates

- `Structara` remains a working name until legal/domain clearance.
- Currency pricing, overage, storage, and annual discount require an
  owner-approved price book; the current estimator truthfully reports credits.
- Final licensed wordmark and Figma source synchronization require owner access.
- Real participant/customer evidence requires consent and approval.
- Production p75 Core Web Vitals require a deployed canonical domain and traffic.
