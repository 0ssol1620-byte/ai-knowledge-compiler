# Dependency and skill register

| Name                       | Version/source   | License observed              | Bundled | Use                        |
| -------------------------- | ---------------- | ----------------------------- | ------- | -------------------------- |
| Next.js                    | `16.2.12`        | MIT                           | Yes     | App Router                 |
| React                      | `19.2.8`         | MIT                           | Yes     | UI runtime                 |
| Three.js                   | `0.180.0`        | MIT                           | Yes     | Progressive hero scene     |
| React Three Fiber          | `9.4.0`          | MIT                           | Yes     | React WebGL renderer       |
| Drei                       | `10.7.6`         | MIT                           | Yes     | R3F helpers                |
| Phosphor Icons             | `2.1.10`         | MIT                           | Yes     | Consistent interface icons |
| UI UX Pro Max              | local skill      | License metadata inconsistent | No      | Internal research only     |
| Emil Design Engineering    | local skill      | Upstream repository guidance  | No      | Internal craft review      |
| FOLYNTA Brand Experience | project guidance | Proprietary project guidance  | No      | Brand authority            |

Reviewed: 2026-07-30. Package lock is the source of truth for transitive
versions. No external skill database is redistributed with the product.

Spline is not included in the production dependency graph. The masterplan's
Spline references informed camera prototyping only; the shipped scene uses
Three.js and React Three Fiber with a code-owned poster fallback.

The Asset System v2.1 production set is entirely first-party: actual browser
captures, deterministic fixtures, code/SVG diagrams, procedural R3F geometry,
glyphs, patterns, and CSS textures. No stock, CC0, downloaded, or AI-generated
raster asset is shipped. Asset truth, source, usage, and SHA-256 records live in
`assets/registry/asset-manifest.yml`.
