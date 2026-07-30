# AI Knowledge Compiler — Product Design System

> Source of truth: `AI_Knowledge_Compiler_Enterprise_UI_UX_Masterplan_FINAL_KO_2026-07-30`
>
> Scope: authenticated product UI. The marketing site has its own editorial
> composition, but uses the same color, type, accessibility, and evidence
> semantics.

## Product character

The interface communicates:

- verifiable
- precise
- compiled
- connected
- calm power
- transparent intelligence
- enterprise trust

AI symbolism is not a visual motif. Documents, typed blocks, provenance
threads, structured output, and evidence are the product imagery.

## Non-negotiable direction

- Product surfaces are light-first.
- Dark mode is optional, never inferred from the operating-system preference.
- The sidebar is quieter and darker than the work surface so content remains
  the focus.
- One operational region should normally use one surface. Group within it by
  spacing, alignment, and rules instead of nested cards.
- Color marks actions, evidence, and exceptional states. It is not decoration.
- Monospace is reserved for code, hashes, identifiers, and measured technical
  values.
- Korean product copy is primary. English is retained only for established
  formats, code, API concepts, and product names.

## Color tokens

| Role                 | Value     |
| -------------------- | --------- |
| App background       | `#F6F7F9` |
| Primary surface      | `#FFFFFF` |
| Secondary surface    | `#F7F8FA` |
| Primary text         | `#151922` |
| Secondary text       | `#4D5665` |
| Tertiary text        | `#737D8C` |
| Subtle border        | `#E1E4E9` |
| Strong border        | `#C9CED6` |
| Compiler Blue        | `#3157E0` |
| Compiler Blue active | `#2446C8` |
| Evidence Teal        | `#08785B` |
| Warning              | `#9A5B13` |
| Danger               | `#B42318` |
| Sidebar              | `#171B23` |
| Sidebar selected     | `#252D42` |

Raw colors belong in the token layer, not individual components.

## Typography

```css
--font-ui:
  "Pretendard Variable", "Inter", "Noto Sans KR", "Segoe UI Variable Text",
  "Apple SD Gothic Neo", system-ui, sans-serif;
--font-mono:
  "JetBrains Mono", "Cascadia Code", "SFMono-Regular", Consolas, monospace;
```

- Product body: `14px / 22px`
- Dense secondary copy: `12–13px / 18–20px`
- Panel title: `16px / 24px`, weight 600–650
- Page title: `28–36px / 34–44px`, weight 600–650
- Korean heading tracking must not be tighter than `-0.02em`.
- Use tabular numerals for comparable values.

## Spacing and density

Use the 4px base scale:

```text
2, 4, 6, 8, 12, 16, 20, 24, 32, 40, 48, 64, 80, 96
```

Spacing expresses relationships:

- 4–8px inside a label or tightly related group
- 12–20px inside dense controls and panels
- 24–40px between product sections
- 44–48px comfortable rows
- 32–36px compact enterprise rows

Do not stamp the same gap across every relationship.

## Radius and elevation

| Token | Value | Use                           |
| ----- | ----: | ----------------------------- |
| XS    |   4px | status, code                  |
| SM    |   6px | inputs, compact buttons       |
| MD    |   8px | product panels and dialogs    |
| LG    |  12px | large work surfaces           |
| XL    |  16px | marketing product frames only |
| Pill  | 999px | tags only                     |

Fixed navigation and product panels use borders, not shadows. Shadows are
reserved for popovers, the command palette, dialogs, and floating marketing
frames.

## App shell

- Top bar: 48px
- Expanded sidebar: 248–256px
- Collapsed sidebar: 56–64px
- Standard inspector: 360px
- Wide inspector: 440–520px
- Main workspace minimum: 640px

The sidebar may be dark. The main workspace remains light and materially
brighter. On mobile, navigation becomes a four-item bottom bar.

## Interaction

- Minimum touch target: 44×44px where space permits.
- Focus must remain visible.
- Icon-only controls require an accessible name and tooltip.
- Motion lasts 150–250ms and changes only meaningful properties.
- Never animate layout dimensions for decoration.
- `prefers-reduced-motion` disables non-essential motion.
- Status is communicated with text or icon plus text, never color alone.

## Quick Convert

The first state is a single document work surface:

1. Select or drop files.
2. Run security and structural preflight.
3. Show page routes, estimated time, and credit range.
4. Let the user choose Fast, Balanced, Precision, or Private.
5. Confirm the reserved maximum before processing.

Do not expose OCR, RAG, schema, model, or provider controls before they become
relevant.

## Prohibited patterns

- default dark mode
- repeated uppercase kickers
- generic AI imagery, glowing effects, or decorative gradients
- nested card stacks
- one-hue status boxes
- badge and pill proliferation
- tinted icon tiles
- monospace UI chrome
- ornamental `01 / 02 / 03` markers
- invented metrics or unsourced accuracy claims
- a three-column desktop layout merely scaled down on mobile
- sidebar and workspace with the same luminance
- color-only status communication

## Release checklist

- [ ] Light-first authenticated product
- [ ] Clear sidebar/workspace hierarchy
- [ ] No unnecessary heading kicker
- [ ] One surface per operational region
- [ ] Keyboard and screen-reader navigation
- [ ] WCAG 2.2 AA automated checks
- [ ] No horizontal overflow at 360, 768, 1440, and 1920px
- [ ] Reduced-motion behavior
- [ ] Real state labels; no fabricated evidence
- [ ] Visual inspection of marketing, home, upload, processing, review, and
      knowledge surfaces
