# Current status

Structara is a **repository release candidate** as of 2026-07-31. The registered
marketing, authentication, onboarding, product, document, knowledge, enterprise,
and administration surfaces are implemented and pass the local release gates
listed below. This status is not a production go-live, legal-clearance,
commercial-pricing, or field-performance assertion.

# Completed repository scope

- one connected English-default Structara marketing and authenticated product
  system with round-trip navigation
- all routes registered in `PAGE_MANIFEST.yml`, with route-specific information
  architecture and no desktop horizontal overflow in the complete route crawl
- product, solution, demo, proof/pricing, developer, editorial, legal, document,
  knowledge, enterprise, and administration visual families
- functional pricing audience switch and bounded credit estimator
- public OpenDART JTC fixture with receipt `20260730000413`, taxonomy, source
  line, source hash, archive hash, and an explicit no-quality-claim boundary
- exact JTC revenue-cell selection in the proof demo; the previous detached
  absolute-position overlay has been removed
- Quick Convert contract aligned to 30 files and 50 MB per file; unsupported
  folder wording and the former 50 MB/256 MB contradiction have been removed
- private-first processing copy aligned with the actual consent contract:
  external providers require explicit workspace consent
- every generic `/app/*` header action resolves to an operable internal route;
  static fixture controls are visibly disabled instead of pretending to mutate
  data
- demo `/admin` and `/settings` surfaces are labeled illustrative and cannot
  perform write-looking operations; non-demo mode continues to use the live
  control components
- Next.js production builds no longer suppress TypeScript errors
- first-party Blender hero master, GLB LODs, responsive derivatives, product
  captures, structural glyphs, patterns, textures, and architecture diagrams
- deterministic asset naming, provenance records, and cryptographic hash gates
- no fabricated customer, benchmark, certification, security, or commercial
  pricing evidence
- v2 Public Core registry with exact OmniDocBench v1.7, ParseBench, and
  olmOCR-Bench evaluator/dataset revisions and full remote manifest hashes
- GT-free CIR adapters, immutable prediction freeze, isolation audit,
  Structara critical gate, candidate/incumbent comparison, exact three-run
  reproducibility gate, and external-key report signing contract

# Current local verification evidence

Executed with Node.js 22.14.0 and pnpm 11.9.0:

- ESLint: pass with zero warnings
- strict TypeScript: pass
- Next.js 16.2.12 production build: pass, including the internal TypeScript
  phase, static-page generation, and build-trace collection
- Vitest: 22 files and 109 tests passed
- Public benchmark contract tests: 11 passed
- production Playwright: 52 passed and 14 intentional project-scope skips
- desktop visual regression: 9 approved baselines passed
- browser/viewport matrix: 9 passed across Chromium, Firefox, and WebKit
- live-API Playwright: 1 end-to-end provenance/export journey passed
- TypeScript-AST button contract gate: 0 enabled dead controls
- registered public route crawl: pass
- registered app and document route crawl: pass
- Public Core online registry verification: pass
- official ParseBench evaluator tests: 198 passed
- OmniDocBench compatibility smoke: 5 passed, 1 deselected
- olmOCR-Bench evaluator import/normalization/baseline smoke: pass
- Quick Convert bounded/consent-aware contract: desktop and mobile pass
- JTC exact-cell proof and no detached overlay: desktop and mobile pass
- demo/live control-boundary checks: desktop and mobile pass
- shell notification/account actions, fixed studios, SSO, and recovery gates:
  desktop and mobile pass
- reduced-motion checks: pass
- Axe representative WCAG A/AA suite: no violations
- canonical contracts TypeScript check: pass
- asset manifest: 9 assets verified
- asset naming: 119 files verified
- asset hashes: 21 derivatives verified

The live-API Playwright journey was rerun and passed registration, verification,
upload, analysis, compilation, ordered SSE, and export against the real local
API. The retained Lighthouse artifact reports Performance 93, Accessibility
100, Best Practices 96, SEO 100, TBT 40 ms, and CLS 0 under its recorded lab
conditions; it is not field Core Web Vitals evidence.

# Intentional architecture boundary

The root layout remains dynamically rendered because `src/middleware.ts` issues
a per-request CSP nonce. Next.js 16 prefers the `proxy.ts` convention, but the
current Windows standalone trace path intermittently omits the renamed proxy
artifact. The middleware compatibility entry preserves the same nonce and
header contract until the upstream standalone artifact issue is resolved.
Removing dynamic rendering without replacing that nonce architecture would
weaken the security contract. Production caching and field performance must
therefore be assessed on the deployed canonical environment, not inferred from
route labels alone.

# Remaining owner or external gates

- legal and domain clearance for the working name `Structara`
- final licensed wordmark and owner Figma workspace synchronization
- owner-approved commercial price book for currency, overage, storage, and
  annual-discount values
- participant/customer consent for interviews, logos, testimonials, and stories
- rights-cleared benchmark corpora plus real model, hardware, cost, and canary
  evidence before publishing benchmark values
- three complete same-environment candidate/incumbent runs for OmniDocBench,
  ParseBench, and olmOCR-Bench, including official and Structara-critical raw
  outputs, GT-isolation evidence, failure artifacts, and a signed report
- production identity-provider, payment-provider, email-delivery, and external
  model-provider configuration where those features are enabled
- production canonical hostname, deployed security-header scan, operational
  drills, and field p75 Core Web Vitals

# Release interpretation

`complete` in repository manifests means that the route or artifact is
implemented and locally verified. It does not mean that the external gates above
have been satisfied. Release confidence must continue to be based on evidence,
not status labels alone.
