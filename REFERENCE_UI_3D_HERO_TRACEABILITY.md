# Structara Reference UI + 3D Hero traceability

Authority: `D:\Structara_Reference_UI_Integration_Landing_3D_Hero_Implementation_Masterplan_FINAL_KO_2026-08-02.md`
Authority SHA-256: `86e883fc1a017ca945bada6c2f43844e4a9d46cba04c9ec5d10d05288ed1ebb0`

## Section ledger

| Masterplan section                            | Repository evidence                                                                                          | State                                         |
| --------------------------------------------- | ------------------------------------------------------------------------------------------------------------ | --------------------------------------------- |
| 0–2 Purpose, brand invariants, trust boundary | `STRUCTARA_BRAND_DECISIONS.md`, `AGENTS.md`, truth-class attributes                                          | implemented                                   |
| 3 shadcn/ui role and wrapper boundary         | `THIRD_PARTY_COMPONENT_REGISTER.yml`, existing semantic app components                                       | implemented without new source copy           |
| 4 Aceternity patterns                         | `raw-compiled-compare.tsx`, `transformation-story.tsx`, `structara-proof-demo.tsx`                           | reimplemented                                 |
| 5 Magic UI patterns                           | `knowledge-flow.tsx`, `product-film-dialog.tsx`, existing knowledge tree                                     | reimplemented                                 |
| 6 21st.dev patterns                           | `upload-panel.tsx`, `collection-intake.tsx`, register                                                        | audited pattern reference                     |
| 7 React Bits patterns                         | Blender document stack, settled scene, sticky story                                                          | reimplemented                                 |
| 8 selection matrix                            | `THIRD_PARTY_COMPONENT_REGISTER.yml`                                                                         | complete                                      |
| 9 landing story                               | homepage order: hero, problem, compare, transformation, product, proof, flow, benchmark, film, security, CTA | implemented                                   |
| 10 Books-to-Knowledge-Plane hero              | Blender master, desktop/tablet GLB, AVIF/WebP posters, lazy R3F, one-shot timeline                           | implemented                                   |
| 11 post-hero sections                         | compare, sticky story, proof, flow, film components                                                          | implemented                                   |
| 12 product application                        | existing app shell, processing, review, knowledge, upload state surfaces                                     | retained and verified in full E2E             |
| 13 design tokens                              | `structara.css` warm canvas/ink/blue/evidence system                                                         | implemented                                   |
| 14 code structure and external-code rule      | Structara-owned marketing components; no page import from `reference/`                                       | enforced                                      |
| 15 motion governance                          | one main motion per section, finite beam, one-shot hero, native reduced-motion CSS                           | implemented                                   |
| 16 responsive contract                        | 1920/1440/1280/1024/768/390/360 compositions and mobile poster path                                           | complete; 9/9 browser matrix and 532/532 captures |
| 17 accessibility contract                     | native range, explicit compare buttons, text alternatives, native dialog, captions/transcript                | complete; axe/WCAG and Lighthouse accessibility 100 |
| 18 performance contract                       | poster-first, idle dynamic R3F, 1.11 MB LOD0, 0.63 MB LOD1, mobile WebGL off                                 | desktop 99/LCP 0.9s; mobile simulated 76/LCP 4.7s documented below |
| 19 real data and copy                         | DART public fixture and measured five-candidate benchmark snapshot                                           | implemented                                   |
| 20 license/source governance                  | `THIRD_PARTY_COMPONENT_REGISTER.yml`, no preview media or Pro code                                           | complete for repository use                   |
| 21 implementation phases                      | static, interactions, 3D, product integration, QA sequence                                                   | phases 0–5 complete                           |
| 22 QA matrix                                  | unit, Playwright, engine/viewport matrix, current-worktree capture                                            | complete                                      |
| 23 visual score                               | `VISUAL_QA_REPORT.md`                                                                                        | 94/100 approved at repository gate            |
| 24 Codex execution rules                      | unit-scoped implementation and direct visual review                                                          | followed                                      |
| 25 Definition of Done                         | this ledger plus final gate outputs                                                                          | repository DoD complete; named external gates remain |
| 26 official source registry                   | `THIRD_PARTY_COMPONENT_REGISTER.yml` and authority source list                                               | complete                                      |
| 27 final execution decision                   | first-party hero plus selectively reimplemented interaction principles                                       | implemented                                   |

## Hero deliverables

| Required artifact                    | Actual artifact                                                                    |
| ------------------------------------ | ---------------------------------------------------------------------------------- |
| editable Blender master              | `assets/3d/master/hero-master.blend`                                               |
| desktop GLB                          | `apps/web/public/hero/hero-documents-master.glb`                                   |
| tablet GLB                           | `apps/web/public/hero/hero-documents-tablet.glb`                                   |
| scene report                         | `assets/3d/source-models/hero-scene.yml`                                           |
| desktop/tablet/mobile/reduced poster | `apps/web/public/hero/STR-HOME-T2-HERO-EN-*.avif`                                  |
| runtime scene                        | `apps/web/src/components/structara-webgl-scene.tsx`                                |
| capability boundary                  | `apps/web/src/components/structara-hero.tsx`                                       |
| tests                                | `structara-hero.test.tsx`, `reference-integration.test.tsx`, Playwright visual/E2E |

## Honest open gates

- Final local Lighthouse: desktop 99/100/100/100 with LCP 0.9s; mobile simulated 76/100/100/100 with LCP 4.7s. The mobile performance target is an explicitly documented block caused by the current shared global CSS payload; accessibility, best-practices, and SEO are 100. Field p75 Core Web Vitals remain unmeasured until canonical traffic exists.
- Legal clearance of the Structara name and commercial pricing remain owner-controlled external gates.
- No external component source was copied, so no original source hash is represented as an installed dependency; official repository revisions are recorded for research reproducibility.
