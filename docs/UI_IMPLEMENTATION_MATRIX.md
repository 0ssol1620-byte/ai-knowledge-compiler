# Enterprise UI/UX implementation matrix

- Assessed: 2026-07-30
- UI masterplan: `AI_Knowledge_Compiler_Enterprise_UI_UX_Masterplan_FINAL_KO_2026-07-30`
- Parent product masterplan: `AKC-MASTERPLAN-KO-20260729-V2`
- Scope: repository implementation and local deterministic evidence

`LOCAL-CLOSED` means the repository behavior and a proportionate local check
exist. It does not mean that production traffic, user research, a deployed
provider, legal approval, or an operating SLO has been proved.

## Epic backlog trace

| Epic | Status | Implemented repository surface | Evidence still outside the repository |
| --- | --- | --- | --- |
| `EPIC-UI-001` Design foundations | `LOCAL-CLOSED` | Semantic neutral/brand/evidence/AI/status tokens, typography stacks, 4/6/8px radius discipline, bounded shadows, focus-visible styles, reduced motion, reusable buttons/panels/dialogs, ESLint and Axe checks. | Brand review and assistive-technology usability sessions. |
| `EPIC-UI-002` Marketing shell | `LOCAL-CLOSED` | Public `/` nav, editorial hero, document-to-knowledge story, product proof, transparent benchmark methodology, enterprise controls, pricing, CTA, and footer. Demo facts are explicitly labeled. | Approved claims, current pricing, real customer logos, market evidence (`EG-10`, `EG-14`). |
| `EPIC-UI-003` 3D & motion | `LOCAL-CLOSED` | Dependency-free CSS 3D document→typed blocks→Markdown→graph scene, deterministic fallback, transform/opacity animation, and `prefers-reduced-motion` shutdown. Avoids a third-party scene runtime in the critical path. | Device-lab Core Web Vitals and production RUM (`EG-07`). |
| `EPIC-UI-004` Auth/onboarding | `LOCAL-CLOSED` | Registration, email ownership verification, session gate, honest sample-first entry, workspace creation, private-mode and external-provider policy surfaces. | Real IdP/OIDC tenant, deliverability, onboarding study, and enterprise SSO evidence (`EG-06`, `EG-13`). |
| `EPIC-UI-005` Upload/preflight | `LOCAL-CLOSED` | Browser-direct resumable multipart upload, incremental hashing, resume/retry, format/security preflight, route/output choices, and explicit upper-bound cost confirmation. | Production object-store, malware/CDR efficacy, and calibrated invoice evidence (`EG-02`, `EG-06`, `EG-09`). |
| `EPIC-UI-006` App shell | `LOCAL-CLOSED` | 48px top bar, 256/64px sidebar, command palette, dense context navigation, demo boundary, responsive 72px rail, mobile bottom navigation, and session-aware public/private routing. | Authenticated enterprise usability study. |
| `EPIC-UI-007` Processing Studio | `LOCAL-CLOSED` | Page rail, source viewer, overlays, raw text, live Markdown, multi-source provenance, pinned compare, review/export entry, measured metrics tray, SSE gap reducer, silence fallback, and mobile tabs. | Production-scale SSE/load/fairness results (`EG-07`). |
| `EPIC-UI-008` Review Studio | `LOCAL-CLOSED` | Dedicated desktop three-pane review, tablet decision layout, mobile queue→decision flow, issue severity, source/candidate/manual comparison, keyboard legend, direct actions, scope preview, audit and optimistic locking. | Human reviewer agreement and task-completion study (`EG-04`, `EG-11`). |
| `EPIC-UI-009` Result/export | `LOCAL-CLOSED` | Export summary, output profile selection, file-tree/package preview, Portable Markdown/Obsidian/RAG/JSON-LD generation, Vault collision preview, immutable artifact hashes and download flow. | Production object retention and customer reuse outcomes (`EG-08`, `EG-11`). |
| `EPIC-UI-010` Knowledge Studio | `LOCAL-CLOSED` | Notes/Graph/Entities/Relations/Evidence tabs, local graph, table alternative, evidence chain and round-trip affordances; live mode refuses invented nodes. | Large-graph performance and real-corpus usefulness evidence (`EG-04`, `EG-07`, `EG-11`). |
| `EPIC-UI-011` Benchmark Lab | `LOCAL-CLOSED` | Live analytics/benchmark route, methodology labeling, metric breakdown, comparison tables, unavailable states and failure-oriented evidence contracts. | Licensed corpus, real model/hardware runs, approved champion and canary evidence (`EG-03`–`EG-05`). |
| `EPIC-UI-012` Enterprise | `LOCAL-CLOSED` | Settings, member/role policy surfaces, retention/provider controls, webhook delivery operations, API workflows, usage/credit controls, model governance, DLQ operations and audit-oriented admin views. | Deployed SSO/SCIM/BYOK/legal hold/private cloud and independent control assessment (`EG-06`, `EG-13`). |
| `EPIC-UI-013` QA | `LOCAL-CLOSED` | 360/768/1440/1920 browser inspection, desktop/mobile Playwright, no-horizontal-overflow assertions, Axe WCAG A/AA scan, focus trap/restore, CSP nonce checks, reduced-motion CSS, lint/type/unit/build gates. | Real-device matrix, screen-reader sessions, visual-baseline approval, production RUM and performance regression history (`EG-07`). |

## Information architecture

| Surface | Route | State contract |
| --- | --- | --- |
| Marketing | `/` | Public editorial site; never renders private app navigation. |
| Home / projects | `/home`, `/projects` | Workspace evidence and honest demo/live separation. |
| Quick convert | `/quick-convert` | Security preflight before analysis or cost commitment. |
| Processing | `/workspace` | Source→structure→result with event and revision evidence. |
| Review | `/review` and workspace drawer | Risk-ordered decision workflow; all mutations audited. |
| Knowledge | `/knowledge-bases` | Graph plus accessible table/evidence alternatives. |
| Benchmark | `/benchmarks`, `/analytics` | Methodology-bound metrics; unavailable is not rendered as zero. |
| API workflow | `/api-workflows` | Quickstart and job workflow without leaking credentials. |
| Usage / settings | `/usage`, `/settings` | Credits, policy, provider, retention, member and webhook controls. |
| Operations | `/admin` | Dependency health, retry, model governance and DLQ disposition. |

## Local release evidence

- `ruff`: all Python source and tests pass.
- `pytest`: 576 tests pass.
- `vitest`: 52 tests pass.
- Playwright: 17 pass, 5 intentional project/profile skips.
- Next.js production build: all application routes compile.
- ESLint, TypeScript, Prettier: pass with zero warnings.
- Axe: no automated WCAG A/AA violations on marketing, home,
  processing, review, and knowledge surfaces.

## Honest open gates

All gates in `docs/release/EXTERNAL_GATES.md` remain open until immutable,
commit-bound operating evidence exists. In particular, local UI screenshots do
not prove production performance, licensed-corpus quality, security
assessment, legal approval, merchant reconciliation, or beta outcomes.
