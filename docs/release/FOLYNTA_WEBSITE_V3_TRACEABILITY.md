# FOLYNTA Website v3 traceability

Authority: `D:\FOLYNTA_WEBSITE_TOTAL_CREATIVE_REBUILD_MASTERPLAN_FINAL_v3_FREE_ASSET_FIRST_NO_GENERATION_DEFAULT_KO_2026-08-02.md`

Authority SHA-256: `fa8ce3a01499fcc558c6bfdf63200849667bc7d774f74bcba86d970e288e8bb5`

Review date: 2026-08-02

## Truth boundary

- The public homepage uses only registered first-party T0/T1 evidence and the
  vendored shadcn/ui Resizable source component.
- Image generation was not used.
- DART and SEC are frozen, registered public filing fixtures. They are not
  customer, benchmark, field-performance, or live-product claims.
- The processing scene is a disclosed replay of persisted domain events. It has
  no timer-driven fake progress.
- The 18-page OmniDocBench subset stays `SHADOW`; no production parser promotion
  is implied.
- Legal clearance, commercial pricing, consented customer evidence, full public
  benchmark evidence, and field SLO evidence remain external gates.

## Homepage scene contract

| Order | Scene                     | Implementation                                         | Truth class                             |
| ----- | ------------------------- | ------------------------------------------------------ | --------------------------------------- |
| 01    | Folio Synthesis hero      | `StructaraHeroScene` + `SignatureScene`                | T1 first-party brand illustration       |
| 02    | Durable processing        | `HomepageProcessingScene` + `ProcessingSceneWorkbench` | T0 registered public fixture replay     |
| 03    | Public proof              | locale-aware DART/SEC switcher                         | T0 source-native filing evidence        |
| 04    | Compiler transformation   | four semantic compiler stages                          | T1 explanatory system                   |
| 05    | Knowledge system          | vault, note, graph, export from one fixture            | T0/T1 source-linked product explanation |
| 06    | Measured trust + security | frozen subset table and policy rail                    | T0 measured subset + T1 control diagram |
| 07    | Final CTA                 | one primary collection action                          | functional navigation                   |

The DOM contract is exactly:

`01-hero -> 02-processing -> 03-proof -> 04-transformation -> 05-knowledge -> 06-trust-security -> 07-final`

## Source-first component decisions

- `ADOPTED_SOURCE`: shadcn/ui Resizable, vendored under
  `apps/web/src/components/vendor/shadcn/` and adapted only through a thin
  FOLYNTA wrapper.
- `REJECTED`: Aceternity, Magic UI, 21st.dev, and React Bits candidates that did
  not satisfy the truth, license, finite-motion, or semantic requirements.
- `CUSTOM_APPROVED`: Folio Synthesis and market-aware source proof, because the
  required registered filing and provenance semantics are product-specific.
- The authoritative record is `THIRD_PARTY_COMPONENT_REGISTER.yml`; no
  behavior-only reimplementation is claimed.

## Route and localization contract

- KO defaults to the registered OpenDART receipt `20260730000413`.
- EN defaults to the registered Apple 2025 Form 10-K SEC filing.
- Users can explicitly switch markets without changing the underlying claim
  class or presenting a live benchmark.
- `/product/compile` is the canonical compiler narrative; the legacy
  `/product/convert` route remains available for compatibility.
- The primary signup flow remains Google-centered with accessible fallback
  states covered by the authentication tests.

## Browser evidence before release gates

| State         | Result                                                                                           |
| ------------- | ------------------------------------------------------------------------------------------------ |
| 1440 × 900 KO | 7 scenes, zero page overflow, zero broken images                                                 |
| 1024 × 768 KO | 7 scenes, zero page overflow, zero broken images                                                 |
| 390 × 844 KO  | 7 scenes, zero page overflow, zero broken images                                                 |
| 390 × 844 EN  | SEC default, 7 scenes, zero page overflow                                                        |
| Console       | zero warnings and zero errors                                                                    |
| Motion review | no infinite motion, layout-property animation, `transition: all`, or reduced-motion content loss |

## Release gates

This table is updated only from commands executed against the final tree.

| Gate                | Command                                   | Result                                                   |
| ------------------- | ----------------------------------------- | -------------------------------------------------------- |
| TypeScript          | `pnpm --filter @akc/web typecheck`        | PASS                                                     |
| ESLint              | `pnpm --filter @akc/web lint`             | PASS                                                     |
| Unit                | `pnpm test`                               | PASS — 228 Vitest + contracts TypeScript                 |
| Python              | `.venv\\Scripts\\python.exe -m pytest`    | PASS — 1,488 initial + 1 isolated resource retry = 1,489 |
| Assets              | `pnpm assets:validate`                    | PASS — 11 assets, 136 names, 29 derivatives              |
| Interactions        | `pnpm interactions:check`                 | PASS — 0 enabled dead controls                           |
| Production build    | `pnpm build`                              | PASS — Next.js 16.2.12 production build                  |
| E2E + accessibility | `pnpm test:e2e`                           | PASS — 79 passed, 17 intentional project skips           |
| Browser matrix      | `pnpm --filter @akc/web test:e2e:matrix`  | PASS — 9/9                                               |
| Visual regression   | `pnpm --filter @akc/web test:e2e:visual`  | PASS — 11/11                                             |
| Storybook           | `pnpm --filter @akc/web storybook:build`  | PASS                                                     |
| Responsive capture  | `pnpm --filter @akc/web brand:capture:v4` | PASS — 560/560, 0 blocking automated findings            |
| Lighthouse desktop  | Lighthouse 12.8.2 production build        | PASS — 100/100/100/100; LCP 749 ms, CLS 0, TBT 0 ms      |
| Lighthouse mobile   | Lighthouse 12.8.2 production build        | PASS — 88/100/100/100; LCP 3,757 ms, CLS 0, TBT 21 ms    |

## Governance note

The owner's instruction to execute the v3 masterplan is the implementation
authority for Folio Synthesis. Independent human creative review remains an
external governance gate; this document does not fabricate a second reviewer.
