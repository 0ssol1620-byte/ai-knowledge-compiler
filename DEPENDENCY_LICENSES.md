# Dependency and skill register

| Name                       | Version/source   | License observed              | Bundled | Use                        |
| -------------------------- | ---------------- | ----------------------------- | ------- | -------------------------- |
| Next.js                    | `16.2.12`        | MIT                           | Yes     | App Router                 |
| React                      | `19.2.8`         | MIT                           | Yes     | UI runtime                 |
| Phosphor Icons             | `2.1.10`         | MIT                           | Yes     | Consistent interface icons |
| Wanted Sans Variable       | `1.0.3`          | SIL OFL 1.1                   | Yes     | Latin and Korean typeface  |
| impeccable                 | `3.5.0`          | Apache-2.0                    | No      | Anti-pattern checker (dev) |
| Lighthouse CI              | `0.15.1`         | Apache-2.0                    | No      | Performance budgets (dev)  |
| fontTools                  | `>=4.55,<5`      | MIT                           | No      | Font subsetting (dev)      |
| UI UX Pro Max              | local skill      | License metadata inconsistent | No      | Internal research only     |
| Emil Design Engineering    | local skill      | Upstream repository guidance  | No      | Internal craft review      |
| TAVONEL Brand Experience   | project guidance | Proprietary project guidance  | No      | Brand authority            |

Reviewed: 2026-08-07. Package lock is the source of truth for transitive
versions. No external skill database is redistributed with the product.

## Typeface

Wanted Sans Variable, © 2024 Wanted Lab, Inc., Reserved Font Name "Wanted Sans
Variable", from `wanteddev/wanted-sans` v1.0.3 under the SIL Open Font License
1.1. The license text ships beside the fonts at
`apps/web/public/fonts/OFL.txt`, as OFL §2 requires for redistribution.

Only derived subsets are committed, which OFL §1 permits:

| File | Contents | Size |
| ---- | -------- | ---- |
| `wanted-sans-latin-var.woff2` | Latin subset, full weight axis 400–1000 | 27.8 KB |
| `wanted-sans-ko-400.woff2` | Korean, static instance at 400 | 2.0 KB |
| `wanted-sans-ko-600.woff2` | Korean, static instance at 600 | 2.0 KB |

The Korean files are small because the build subsets to the Hangul the app
actually uses, which today is 8 syllables — Korean UI copy arrives with the
i18n track. `tools/fonts/build_fonts.py` regenerates all three; the 4.6 MB
source TTF is not committed.

No Google Fonts CDN link is used. Fonts are self-hosted (§7.2, §22).

No WebGL runtime is included in the production dependency graph. `three`,
`@react-three/fiber`, `@react-three/drei`, and `@types/three` were removed in W0
after `decision.md` G-C dropped TIER 1 3D; the hero now ships the poster image
alone. Spline was never a dependency — the masterplan's Spline references
informed camera prototyping only.

The Asset System v2.1 production set is entirely first-party: actual browser
captures, deterministic fixtures, code/SVG diagrams, procedural geometry
rendered offline, glyphs, patterns, and CSS textures. No stock, CC0, downloaded, or AI-generated
raster asset is shipped. Asset truth, source, usage, and SHA-256 records live in
`assets/registry/asset-manifest.yml`.
