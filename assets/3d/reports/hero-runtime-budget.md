# Hero runtime budget

The launch hero uses first-party procedural geometry instead of a downloaded
model or duplicate Blender/GLB payload.

- source pages: 3 boxes
- semantic blocks: 4 boxes
- evidence frame: 1 box
- nodes: 12 low-segment spheres
- relation/evidence paths: 18 lines
- textures: none
- external HDRI: none
- runtime DPR: 1–1.5
- mobile/tablet: static server poster
- reduced motion and Save-Data: static server poster
- animation: one 6-second state sequence, then a stable resolved composition

This remains substantially below the 150k-triangle, 100-draw-call, and 1MB
desktop targets. Production build and Lighthouse provide the release evidence.
