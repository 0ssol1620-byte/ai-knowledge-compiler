# UI reference implementation trace

This document records what was adopted from the UI masterplan references and
where it appears in the product. References are used as interaction and
information-architecture inputs, not as visual clones.

| Reference                   | Adopted principle                                                                      | Product implementation                                                                                                         |
| --------------------------- | -------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| Reducto Studio              | A visible document pipeline with inspectable parsing and extraction stages             | Processing Studio stage rail, page stream, source overlays, page-level route badges, and event-backed progress                 |
| Chunkr web interface        | Task-first entry and a viewer that makes structured output easy to inspect             | Quick Convert preflight, source/Markdown split view, page search, and evidence selection                                       |
| Linear UI refresh           | Calm navigation, consistent headers and controls, dimmed chrome around focused work    | Dark low-contrast sidebar, flat light work canvas, compact context header, and one cobalt action color                         |
| Vercel dashboard navigation | Clear separation between global navigation, workspace context, and operational content | Persistent public/product round trip, workspace switcher, command palette, and compact administration rail                     |
| Spline                      | Production-ready interactive 3D hero with React/Next.js delivery                       | Official Spline React runtime, environment-driven product scene, render-on-demand behavior, and native reduced-motion fallback |

## Deliberate differences

- No invented customer logos, quotes, benchmark victories, or production
  uptime claims.
- No decorative glassmorphism, neon gradients, floating blob art, or generic
  chatbot composition.
- No third-party scene is embedded without product ownership and an explicit
  runtime URL.
- The primary product experience remains fully usable when 3D is unavailable,
  disabled, slow, or reduced-motion is requested.

## Source links

- Reducto Studio: <https://docs.reducto.ai/studio/overview>
- Chunkr web interface: <https://docs.chunkr.ai/pages/get-started/web-interface>
- Linear UI refresh: <https://linear.app/changelog/2026-03-12-ui-refresh>
- Vercel dashboard navigation: <https://vercel.com/changelog/new-navigation-for-the-vercel-dashboard>
- Spline React runtime: <https://github.com/splinetool/react-spline>
- Spline optimization guidance:
  <https://docs.spline.design/exporting-your-scene/how-to-optimize-your-scene>
