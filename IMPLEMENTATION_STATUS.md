# Current status

Structara full-site rebuild from the v2.0 masterplan is implementation-complete
and awaiting the final GitHub CI release gate.

# Completed

- Masterplan audited end to end and converted into a page manifest
- Existing landing and app experience replaced by one coherent Structara system
- English established as the default language
- All public, authentication, onboarding, product, document, and admin routes
  implemented
- Marketing navigation and authenticated product navigation connected in both
  directions
- Progressive React Three Fiber hero implemented with persistent poster,
  reduced-motion, mobile, and WebGL failure fallbacks
- Responsive behavior verified for desktop, tablet, and mobile compositions
- Keyboard, landmark, focus, contrast, reduced-motion, and Axe checks completed
- No fabricated customer proof, certifications, scores, or availability claims
- Spline removed from the production dependency graph
- SEO metadata, Open Graph image, robots, sitemap, and web app manifest added
- Full frontend lint, type, unit, build, and E2E suites passed
- Safe Windows backend suites and repository validators passed
- Production Lighthouse release thresholds passed
- Asset System v2.1 implemented with truth classification, registry, hashes,
  source evidence, 18 glyphs, 6 patterns, 8 textures, 12 diagrams, 23 real
  product captures, and 8 real product motion loops
- Product marketing upgraded from illustrative UI to optimized T0 browser
  captures from the actual deterministic demo workspace
- Rejected AI-generated editorial stills removed; no generated or external
  raster asset remains in production

# Blockers

- `Structara` remains a working name pending owner legal and domain clearance.
- A final licensed wordmark and Figma source remain owner-controlled follow-up
  items. The production UI does not depend on either.
- The deployment environment must provide `NEXT_PUBLIC_SITE_URL` for canonical
  production URLs.

# Verification evidence

Evidence is recorded in `VISUAL_QA_REPORT.md` and the Pull Request. The complete
Python suite is delegated to Linux GitHub CI because Windows `spawn` recursively
re-enters the parent pytest command in multiprocessing isolation tests.
Asset-specific evidence is recorded in `ASSET_QA_REPORT.md` and
`assets/registry/asset-manifest.yml`.

# Next action

Push the implementation branch, open the Pull Request, and require all GitHub
checks to pass before release.
