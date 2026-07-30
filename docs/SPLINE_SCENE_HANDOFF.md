# Spline hero handoff

The landing page is already wired to the official Spline React runtime. It
uses a polished native evidence-compilation scene until a product-owned Spline
scene is supplied, and it always falls back to that scene when the visitor
prefers reduced motion.

## One external action

1. In Spline, create or remix a scene owned by the AI Knowledge Compiler
   workspace.
2. Export it for React/Next.js and copy the public `scene.splinecode` URL.
3. Set `NEXT_PUBLIC_AKC_SPLINE_SCENE_URL` in the web runtime environment and
   rebuild or restart the web application.

No source edit is required after the URL is available.

## Required scene contract

- Composition: source pages, typed blocks, provenance threads, verified
  Markdown, and a restrained knowledge graph.
- Interaction: pointer parallax only; the content and primary CTA must remain
  usable without the canvas.
- Motion: settle after the first transformation and avoid continuous idle
  animation.
- Accessibility: the native fallback remains the reduced-motion experience.
- Performance: one scene only, render on demand, compressed textures, reused
  materials, low polygon count, and no critical information rendered only in
  3D.
- Privacy: no user document content or tenant identifiers in the scene.

## Verification

Inspect the landing hero element:

- `data-scene-source="spline"` means the configured Spline scene is active.
- `data-scene-source="native-fallback"` means the URL is absent or reduced
  motion is enabled.
