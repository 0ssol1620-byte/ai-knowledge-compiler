# TAVONEL asset QA report

## Release assets

| Asset family                     | Truth |  Score | Result |
| -------------------------------- | ----- | -----: | ------ |
| Blender Source-to-Knowledge hero | T2    | 96/100 | Pass   |
| Canonical product capture pack   | T0    | 97/100 | Pass   |
| Required product motion pack     | T0    | 96/100 | Pass   |
| OpenDART public proof pack       | T0    | 98/100 | Pass   |
| Architecture diagram system      | T1    | 95/100 | Pass   |
| Structural glyph family          | T2    | 94/100 | Pass   |
| Pattern and texture families     | T2    | 92/100 | Pass   |

All P0 families exceed the 90-point gate. Truth and license critical issues:
zero.

## Evidence

- Hero: one editable Blender master, 14 canonical object types, LOD0/1 GLB,
  LOD2 posters, three concepts, three transparent extractions, desktop/tablet/
  mobile/reduced/OG crops, and MP4/WebM motion.
- Hero delivery: desktop AVIF 71 KB, mobile AVIF 23 KB, WebM loop 57 KB. The
  static poster is complete before R3F enhancement.
- Product capture: 18 desktop and 5 mobile screens from real deterministic
  routes with stable sample data and reduced motion.
- Product motion: all 10 required interactions are captured as actual browser
  recordings in both WebM and H.264 MP4.
- Public proof: 10 OpenDART captures cover Original, Markdown, Vault, Graph,
  Proof, source cell, receipt, tablet, mobile, and route context.
- Public provenance: receipt `20260730000413`, extracted source hash
  `312d03bcd23951c21948021dc2ea115e2f5be58b7c5a1eb23d9dc9da1f98e6a3`,
  and an explicit prohibition on quality claims.
- Diagrams: 12 definitions share the same glyph, grid, and evidence-line
  language; each has an ordered screen-reader equivalent.
- Glyphs: all 18 use one optical grid and are reserved for brand/education,
  never as an unlabeled functional navigation replacement.
- Patterns/textures: code-owned, seam-safe, token-driven, and limited to
  low-opacity structural support.

## Automatic blocks checked

- asset manifest schema: pass
- 119 governed asset filenames: pass
- 21 registered derivative hashes: pass
- no generated product, benchmark, customer, logo, certification, or security
  evidence
- no unknown license or source
- no essential text embedded in generated imagery
- no hero without desktop/mobile/reduced-motion fallback
- no external or AI-generated production raster

## Motion review

| Before                            | After                                            | Why                                                                                                    |
| --------------------------------- | ------------------------------------------------ | ------------------------------------------------------------------------------------------------------ |
| No feel-breaking motion found     | Approved without remedial change                 | UI transitions are 100–180 ms; the 500–700 ms fades are limited to the rare cinematic hero enhancement |
| Hero WebGL could run continuously | Pauses offscreen and when the document is hidden | Prevents decorative background work                                                                    |
| Motion could replace meaning      | Resolved poster carries identical information    | Reduced motion, mobile, Save-Data, and WebGL failure retain the category explanation                   |

Verdict: **Approve**. No `transition: all`, `scale(0)`, `ease-in`, layout-property
animation, high-frequency keyframe, or reduced-motion violation is present in
the TAVONEL system.
