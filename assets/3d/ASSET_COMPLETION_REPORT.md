# Asset Completion Report

## Asset

Source-to-Knowledge signature hero family.

## Route and purpose

Homepage hero and launch/editorial derivatives. The scene explains the category
in one visual: source pages become structured blocks, evidence links, and
connected knowledge.

## Truth class

T2 — first-party designed brand object.

## Source and generation

Procedural Blender 4.5 LTS source at
`tools/assets/build_tavonel_hero.py`. No AI image generation and no external
asset.

## Master and derivatives

- editable master: `assets/3d/master/hero-master.blend`
- runtime LOD0: `assets/3d/derivatives/hero-master.glb`
- runtime LOD1: `assets/3d/derivatives/hero-master-low.glb`
- 11 resolved PNG source renders
- 11 AVIF and 11 WebP delivery derivatives
- H.264 MP4 and VP9 WebM 12-second loops
- three composition variants
- three transparent object extractions

## License and provenance

First-party. Geometry, materials, text, light, animation, and camera are
produced entirely by the repository script. SHA-256, dimensions, and bytes are
recorded in `assets/registry/generated-assets.json`.

## Accessibility

The asset is decorative in the homepage because the adjacent heading and copy
state the full meaning. It uses an empty alt attribute. Reduced motion receives
the resolved poster; no information depends on animation or WebGL.

## Performance

The desktop AVIF is below 100 KB, tablet/mobile AVIFs below 50 KB, and the WebM
loop below 100 KB. The server-rendered poster is the baseline; WebGL is idle
loaded only on capable non-mobile, non-Save-Data, non-reduced-motion clients.

## Remaining risks

Legal clearance of the TAVONEL working name is owner-controlled and does not
alter this generic first-party object family.

## Final status

Production-ready after route-level browser and Lighthouse gates pass.
