# Frontend rules

Moved out of `CLAUDE.md` when that file became the project constitution. These
are the binding UI rules; the constitution carries the short version and points
here.

The agent contract is `AGENTS.md`. The visual source of truth is
`design-system/tavonel/DESIGN_MASTER_V3.md`; where it and
`design-system/tavonel/decision.md` disagree, decision.md wins.

## Absolute

- Every scene is a variation on FacingPages (source left, output right). The
  sides do not swap.
- No decorative threads without coordinates. Without coordinates, `threads=[]`.
- Depth appears in exactly three places: focus ring, hover, overlay. No shadows
  on cards or sections.
- Borders are alpha. No hardcoded hex rules (`--rule-*` tokens).
- The brand colour appears in four places: primary CTA, active marker, focus
  ring, active thread.
- No more than four identical shapes in one viewport. Zero `<table>` on home.
- Progress is never a `setInterval`, and never a literal (no "68%").
- A DOM-rebuilt table is never presented as the source.
- A unit that failed is never turned into a success without a trace.
- UI animation under 300ms, ease-out on entry, transform and opacity only. No
  infinite animation. User-initiated over autoplay.
- `text-wrap: balance` on `:lang(en)` only; `:lang(ko)` gets `word-break:
  keep-all`.
- No control that does not work.
- New CSS goes inside `@layer`.

## Dependencies

One external component library: shadcn/ui. Virtualization: react-virtuoso.
Icons: `@phosphor-icons/react`. No additional animation library.

3D is reinstated as of 2026-08-09 — see the constitution. The stack is Three.js,
React Three Fiber and drei, added back deliberately and measured. No paid scene
dependency.

Anything else: write the reason in `design-system/tavonel/decision.md` and get
approval first.

## Gates

```
pnpm --filter @akc/web interactions:check    §14.3 affordance integrity
pnpm --filter @akc/web exec impeccable detect src    §25.3 machine checks
pnpm --filter @akc/web test:e2e              behaviour + 7 viewports
pnpm --filter @akc/web lighthouse            §22 performance budget
```

Hero, Navigation, Proof and Live Compile need static comp approval before
implementation code is written (§24.1).
