# Structara asset QA report

## Release assets

| Asset family                   | Truth |  Score | Result |
| ------------------------------ | ----- | -----: | ------ |
| Source-to-Knowledge hero       | T2    | 94/100 | Pass   |
| Canonical product capture pack | T0    | 97/100 | Pass   |
| Architecture diagram system    | T1    | 95/100 | Pass   |
| Structural glyph family        | T2    | 94/100 | Pass   |
| Pattern and texture families   | T2    | 92/100 | Pass   |

All P0 assets exceed the 90-point threshold. Truth and license critical issues:
zero.

## Evidence

- Hero: desktop WebGL resolves to 12 restrained nodes; mobile, reduced-motion,
  Save-Data, and WebGL-unavailable paths retain the server poster.
- Product capture: 18 desktop and 5 mobile images are captured from actual
  routes with stable sample data and reduced motion.
- Product marketing: `/product` and five product detail routes use optimized
  T0 captures instead of generated dashboard imagery.
- Diagrams: 12 definitions share the same glyph, grid, and evidence-line
  language; each has an ordered screen-reader equivalent.
- Glyphs: all 18 glyphs use one optical grid and are visually verified in the
  live Product diagram.
- Patterns/textures: code-owned, seam-safe, token-driven, and visually limited
  to low-opacity support.
- External/AI production assets: none.

## Automatic blocks checked

- no generated product evidence, benchmark, customer, logo, certification, or
  security claim
- no unknown license or source URL
- no essential text embedded in a generated image
- no mobile-only desktop crop
- no hero without fallback
- no chrome orb, purple field, robot, random particle, or glass dashboard
