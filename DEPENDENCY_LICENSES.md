# Dependency and skill register

| Name                       | Version/source                      | License observed              | Bundled | Use                            |
| -------------------------- | ----------------------------------- | ----------------------------- | ------- | ------------------------------ |
| Next.js                    | `16.2.12`                           | MIT                           | Yes     | App Router                     |
| React                      | `19.2.8`                            | MIT                           | Yes     | UI runtime                     |
| Three.js                   | `0.180.0`                           | MIT                           | Yes     | Progressive hero scene         |
| React Three Fiber          | `9.4.0`                             | MIT                           | Yes     | React WebGL renderer           |
| Drei                       | `10.7.6`                            | MIT                           | Yes     | R3F helpers                    |
| Phosphor Icons             | `2.1.10`                            | MIT                           | Yes     | Consistent interface icons     |
| UI UX Pro Max              | local skill                         | License metadata inconsistent | No      | Internal research only         |
| Emil Design Engineering    | local skill                         | Upstream repository guidance  | No      | Internal craft review          |
| Structara Brand Experience | project guidance                    | Proprietary project guidance  | No      | Brand authority                |
| Source Atlas               | OpenAI image generation, 2026-07-30 | Project-owned generated asset | Yes     | Public-proof editorial plate   |
| Evidence Field             | OpenAI image generation, 2026-07-30 | Project-owned generated asset | Yes     | Security-policy material field |

Reviewed: 2026-07-30. Package lock is the source of truth for transitive
versions. No external skill database is redistributed with the product.

Spline is not included in the production dependency graph. The masterplan's
Spline references informed camera prototyping only; the shipped scene uses
Three.js and React Three Fiber with a code-owned poster fallback.

The two generated raster assets contain no supplied third-party image, logo,
customer mark, legible document content, or fabricated metric. Optimized WebP
files are stored under `apps/web/public/images/brand/`; the prompts required
original tactile paper studies and explicitly excluded brand marks, watermarks,
fake interfaces, and stock-photo styling.
