> **SUPERSEDED — do not implement from this file.**
>
> This records the Structara design system, which the TAVONEL rename replaced
> on 2026-08-07. It is kept because `design-system/tavonel/decision.md` cites it
> as the `st-` prefix baseline and because the rationale for what was rejected
> here (bento grids, Inter as a visual signature, decorative motion) is still
> the reason those things stay out. Nothing in it is current: the name, the
> token prefix, the typeface, and the 3D scene have all changed.
>
> Current system: `design-system/tavonel/DESIGN_MASTER_V3.md`, with
> `design-system/tavonel/decision.md` overriding it where they disagree.

# Structara Design System

This file records the approved implementation system. The generated UI/UX
database recommendation was reviewed and rejected where it conflicted with the
brand masterplan: Structara is not a space-tech bento product, does not use
Inter as a visual signature, and does not use rounded card grids, hover scaling,
soft atmospheric gradients, or decorative motion.

## Brand posture

- Category: Knowledge Compiler
- Marketing mode: Cinematic Intelligence
- Product mode: Calm Precision
- Visual language: Editorial Intelligence
- Core sequence: Page → Structure → Evidence → Knowledge → Intelligence
- Default language: English; Korean is the first alternate locale

## Color

| Role       | Value     |
| ---------- | --------- |
| Canvas     | `#F5F3EE` |
| Paper      | `#FCFCFA` |
| Surface    | `#FFFFFF` |
| Ink        | `#101216` |
| Graphite   | `#34383F` |
| Muted      | `#69707C` |
| Line       | `#DEDFDC` |
| Soft line  | `#ECEDE9` |
| Brand      | `#315BE8` |
| Brand deep | `#2444B8` |
| Evidence   | `#2AA8BD` |
| Verified   | `#138067` |
| Review     | `#B36B13` |
| Danger     | `#C53737` |

Color never carries status alone. Every semantic state also has a label, icon,
shape, or pattern.

## Typography

- Use the local system/Pretendard variable stack; no external font request.
- Headlines use tight editorial spacing and strong line breaks.
- Product body copy is compact, neutral, and highly legible.
- Monospace is reserved for identifiers, hashes, code, coordinates, and logs.
- Serif is reserved for rendered document content, not product chrome.

## Layout and components

- Public pages use generous asymmetry, paper fields, hairline rules, and one
  strong thesis per viewport.
- Product pages use square or subtly rounded surfaces, stable columns, visible
  stage/provenance context, and dense but calm data tables.
- Prefer flat ledgers and divided sections to cards nested inside cards.
- One primary action per screen. Secondary actions remain text or outline.
- Touch targets are at least 44px. Focus indicators are always visible.

## Motion

- Motion must explain source-to-knowledge transformation or a state change.
- Product interaction transitions stay under 300ms and animate only opacity,
  transform, background, border, or color.
- Marketing scene reveals may take longer when they are rare and non-blocking.
- WebGL is progressively enhanced and never owns essential content.
- Reduced-motion mode removes travel, parallax, and WebGL while preserving
  immediate content and simple color/opacity feedback.

## 3D

- Production renderer: React Three Fiber / Three.js.
- The server-rendered poster is the first frame and permanent fallback.
- The visual metaphor is documents becoming structured, source-linked
  knowledge—not decorative blobs, planets, glass orbs, or particle spectacle.
- Mobile and constrained devices receive the poster without WebGL dependency.

## Forbidden patterns

- Indigo-to-violet marketing gradients
- Gradient-clipped headlines
- Bento-card accumulation
- Glassmorphism as decoration
- Pill and badge spam
- Fake logos, testimonials, certifications, accuracy, uptime, or customer counts
- Invented proof without dataset, version, method, and limitations
- Oversized diffuse shadows and excessive rounding
- Hover scale on ordinary cards or dense product UI
- Emoji or hand-drawn icons in product chrome
- Generic AI copy, sparkle motifs, and model-name-led product language

## Delivery gates

- All routes in `PAGE_MANIFEST.yml` render and expose a unique page title.
- Desktop 1440/1024 and mobile 390 layouts have no horizontal overflow.
- WCAG 2.2 AA automated scans are clean on representative public, auth, product,
  document, and admin surfaces.
- Keyboard navigation, focus order, reduced motion, loading, empty, error, and
  offline/degraded states are verified.
- Claims and third-party assets remain governed by the repository registers.
