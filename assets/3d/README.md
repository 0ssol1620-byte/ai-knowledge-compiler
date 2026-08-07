# FOLYNTA signature hero

Truth class: T2 first-party designed brand object.

The complete hero family is generated from
`tools/assets/build_folynta_hero.py` with Blender 4.5 LTS. It contains no
external mesh, HDRI, texture, font, stock media, or generated image.

## Canonical object family

1. source-page stack
2. document heading
3. document line
4. heading block
5. paragraph block
6. formula block
7. figure block
8. caption block
9. evidence frame
10. evidence diagonal
11. knowledge node
12. evidence node
13. knowledge edge
14. transformation label

The Blender scene remains the editable master. `hero-master.glb` is LOD0;
`hero-master-low.glb` is LOD1; responsive AVIF/WebP posters are LOD2.

## Material bible

- Paper light: warm neutral, roughness 0.86. Used for source pages and the
  lightest structured blocks.
- Paper: cool neutral, roughness 0.82. Used to distinguish extracted structure.
- Ink: near-black, roughness 0.50. Used only for source hierarchy and headings.
- Graphite: neutral gray, roughness 0.45. Used for secondary graph objects.
- Cobalt: restrained metallic 0.08, roughness 0.28, low emission 0.70. Marks
  meaningful transformation and selected knowledge nodes.
- Evidence cyan: metallic 0.04, roughness 0.30, low emission 0.70. Reserved for
  provenance frames and verified links.
- Warm studio: neutral floor, roughness 0.92. It provides a quiet editorial
  field without an external HDRI.

No glass, chrome, holographic shader, rainbow reflection, or decorative
particle material is allowed.

## Lighting bible

- Key: 1250 W area light, 5 m disk, upper-left/front.
- Fill: 850 W area light, 4 m disk, right/front.
- Rim: 950 W area light, 3 m disk, rear.
- World: warm neutral at 0.28 strength.

The hierarchy must keep paper readable, cobalt controlled, cyan distinguishable,
and shadows soft enough for text overlay. Lighting must not imply a generated
product screenshot.

## Camera bible

- Master camera: 56 mm, position `(0.55, -8.8, 6.3)`, aimed at
  `(0.55, 0, 0.18)`.
- Desktop: master framing with intentional upper breathing room.
- Tablet: `(0.45, -9.5, 6.9)`.
- Mobile: `(0.50, -10.9, 7.4)`.
- OG: `(0.55, -9.2, 6.0)`.

Object scale and perspective remain consistent across derivatives. Cropping may
change, but the transformation direction always reads left-to-right:
source → structure → evidence → knowledge.

## Motion

The 12-second master has one explanatory sequence:

1. source pages settle,
2. semantic blocks separate,
3. evidence frames resolve,
4. edges connect,
5. knowledge nodes appear,
6. the scene rests.

It runs at 12 fps and has no audio. Product surfaces do not use this loop.
Reduced-motion surfaces use the resolved static poster with identical meaning.

## Reproduction

```powershell
& D:\CodexTools\blender-4.5.9\blender.exe --background --python tools\assets\build_folynta_hero.py
.\.venv\Scripts\python.exe tools\assets\build_derivatives.py --ffmpeg D:\CodexTools\ffmpeg\ffmpeg-8.1.2-essentials_build\bin\ffmpeg.exe
pnpm assets:validate
```
