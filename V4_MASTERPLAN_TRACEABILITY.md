# Structara v4 masterplan traceability

**Release status:** **Production Reject**

- Authority: `D:\Structara_World_Class_Autonomous_Knowledge_Platform_FINAL_Completion_Masterplan_v4_KO_2026-07-31.md`
- Snapshot: 2026-08-01 current release-candidate worktree
- Audit baseline: final implementation and local verification campaign
- Deployment truth: `docs/release/V4_DEPLOYMENT_MANIFEST.json`
- Detailed audit: `CURRENT_STATE_AUDIT_V4.md`

이 문서는 “코드가 있음”과 “production 증거가 있음”을 분리한다. 한 행의 상태는 해당
범위에서 가장 강한 미충족 조건을 반영한다.

## Status vocabulary

| 상태 | 의미 |
| --- | --- |
| implemented | 저장소 산출물이 존재하고 해당 범위의 로컬 검증이 완료됨 |
| local-contract | interface, schema, adapter, fixture, test는 있으나 실제 provider·scale·field 증거는 없음 |
| external-evidence-required | owner, 법무, 독립 평가, production 계정 또는 실제 운영 환경 증거가 필요함 |
| blocked | 알려진 실패, 상충, 누락된 hard gate 때문에 범위를 완료로 판정할 수 없음 |

현재 집계:

- §0–48: implemented 16, local-contract 24, external-evidence-required 2, blocked 7
- Wave 0–11: implemented 2, local-contract 6, external-evidence-required 0, blocked 4
- Definition of Done: implemented 8, local-contract 27, external-evidence-required 5, blocked 5
- §44–47 release-critical checks: implemented 4, local-contract 11,
  external-evidence-required 10, blocked 5

## §0–48 전수 매핑

| ID | Masterplan 범위 | 상태 | 현재 repository 증거 | release 경계 |
| --- | --- | --- | --- | --- |
| S00 | §0 문서 사용법과 권한 | implemented | `AGENTS.md`, authority chain, 이 ledger의 고정 status vocabulary | v4가 최종 authority이며 외부 증거를 로컬 완료로 대체하지 않음 |
| S01 | §1 최종 감사 판정 | implemented | `CURRENT_STATE_AUDIT_V4.md`와 machine-readable deployment snapshot | 결론은 Repository Release Candidate / Production Reject |
| S02 | §2 2026-07-31 추가 연구 결과 | local-contract | `REFERENCE_LEDGER.md`, benchmark registry, pinned candidate metadata | 최신성·license·provider availability는 실행 시 다시 검증해야 함 |
| S03 | §3 최종 브랜드·제품 전략 | implemented | `STRUCTARA_BRAND_DECISIONS.md`, three-scene product narrative | 법적 상표·도메인 승인은 별도 production gate |
| S04 | §4 제품 Surface 최종 분리 | local-contract | `PAGE_MANIFEST.yml`, Quick Convert, Intake, Studio, Integrity route contracts | 새 surface의 최종 clean build와 hosted journey 증거 필요 |
| S05 | §5 Collection Ingestion Architecture | local-contract | collection API/scheduler/schema, resume·dedupe fixtures와 tests | 5,000 files/10GB 실제 interruption evidence 없음 |
| S06 | §6 다 때려넣기 UI/UX | local-contract | intake component와 collection manifest interaction contract | production upload, browser restart, 대량 selection E2E 없음 |
| S07 | §7 Static Preflight | local-contract | `packages/router` preflight features, clustering/sampling tests | 30,000-page calibration과 실측 latency 없음 |
| S08 | §8 크레딧·처리시간 예측 | local-contract | estimator, reserve/settle/refund ledger contracts와 deterministic tests | 실제 workload calibration, P50/P95 오차, merchant reconciliation 없음 |
| S09 | §9 Adaptive Routing | local-contract | router policy, provider selection, retry/fallback contracts | 실제 endpoint별 quality/cost/latency calibration 없음 |
| S10 | §10 완전 자율 검증 | local-contract | verifier/repair/event contracts, fail-closed states, live local journey | production provider와 rights-cleared hard-set no-human 증거는 외부 gate |
| S11 | §11 Numeric-Safe Hybrid | local-contract | authority hierarchy, source/cell provenance, numeric validation tests | 실제 DART/SEC mixed-corpus hard-set 결과 없음 |
| S12 | §12 Parser 평가·승격 | blocked | locked Tier-0 registry, GT isolation, critical/reproducibility contracts | candidate endpoints, Public Core 3회, private sets, signed report 없음 |
| S13 | §13 Knowledge Compiler | local-contract | CIR/domain-pack compiler, note/entity/relation and deterministic render contracts | 실제 precision model 및 rights-cleared corpus 품질 증거 없음 |
| S14 | §14 Knowledge Blueprint Modules | local-contract | domain-pack module registry와 blueprint schemas/tests | tenant sandbox 및 production module signing evidence 없음 |
| S15 | §15 Canonical Knowledge Model | implemented | canonical CIR/AKMP schemas, generated types, compatibility gates | schema 승격은 compatibility check를 계속 통과해야 함 |
| S16 | §16 Retrieval | local-contract | BM25/vector/graph fusion, filters, rerank, numeric verifier code/tests | production store, DART/SEC retrieval benchmark, source-miss 0 증거 없음 |
| S17 | §17 Deployable Knowledge Package | local-contract | deterministic exporters와 Obsidian/ontology/Neo4j/RAG contracts | 실제 downstream import, round-trip, signed package evidence 없음 |
| S18 | §18 Processing Theater | local-contract | ordered processing events, live workspace reducer, reduced-motion contract | deployed real-job stream과 fake-progress 금지 E2E가 필요함 |
| S19 | §19 결과 화면 | local-contract | result KPIs, package cards, integrity and source-navigation surfaces | production-generated result와 package import journey 미검증 |
| S20 | §20 Integrity Console 재설계 | local-contract | integrity grouping, reason/evidence/action UI contract | live quarantine/repair API와 customer decision journey 미검증 |
| S21 | §21 디자인 리부트 원칙 | implemented | restrained composition, product-first hierarchy, registered visual families | 최종 release screenshot review는 §45에서 별도 차단됨 |
| S22 | §22 Asset Quality Reset | implemented | first-party asset ledger, provenance, naming/hash validators, 3-variant records | license/brand clearance는 외부 gate |
| S23 | §23 Hero 완전 재제작 | implemented | static-first hero, GLB LOD, responsive derivatives, fallback and budgets | field LCP는 §32에서 실패 상태 |
| S24 | §24 Raw vs Compiled | implemented | same-source transformation component와 product captures | customer dataset 품질 주장은 하지 않음 |
| S25 | §25 Proof asset | implemented | source-to-proof visual, exact-coordinate regression and lineage fixture | 실제 production result 증거와 구분함 |
| S26 | §26 Security asset | implemented | first-party security architecture asset와 provenance record | 그림은 security assessment를 대체하지 않음 |
| S27 | §27 페이지별 디자인 우선순위 | implemented | `PAGE_MANIFEST.yml`, registered routes, 532 current-worktree captures | field behavior는 별도 performance gate |
| S28 | §28 Design System 정리 | implemented | token single source, typography/components, Storybook/build contracts | owner Figma source sync는 외부 handoff |
| S29 | §29 Motion | local-contract | purposeful motion tokens/loops와 reduced-motion fallback/tests | real device jank와 long-session performance evidence 없음 |
| S30 | §30 모바일 | implemented | 360/390/768 contracts, current captures, Chromium/WebKit mobile emulation | physical mobile monitoring은 external field evidence |
| S31 | §31 Accessibility | local-contract | Axe, keyboard/focus, reduced-motion, forced-colors contracts | screen reader, 200%, actual high contrast, Edge/device sign-off 없음 |
| S32 | §32 Performance | blocked | asset budgets와 보존 Lighthouse report | LCP 3.2s가 2.5s 목표 실패, 최신 INP/field p75와 scale evidence 없음 |
| S33 | §33 Security·Privacy | external-evidence-required | repository/deployment validators, security suites, live web headers | 독립 pentest, production RLS/IDOR, provider sandbox 증거 필요 |
| S34 | §34 Billing·Pricing | external-evidence-required | credits ledger, hard-cap/refund contracts, pricing claim boundary | owner price book, merchant/KYC, webhook 및 invoice reconciliation 필요 |
| S35 | §35 Admin·Operations | blocked | local health/queue/DLQ/model lifecycle control contracts | production API routes 404, actual admin/alerts/restore/cost operations 없음 |
| S36 | §36 Data Model 추가 | local-contract | SQL migrations, collection/estimate/verification/quarantine models | managed PostgreSQL migration 및 tenant/RLS evidence 없음 |
| S37 | §37 API 계약 | local-contract | OpenAPI, canonical schemas, API tests와 compatibility check | live `/v1` endpoint revision이 배포되지 않음 |
| S38 | §38 Event Contract | local-contract | versioned processing schemas, generated TypeScript, ordering/idempotency tests | production broker/reconnect/1,000-client evidence 없음 |
| S39 | §39 Public Benchmark | blocked | exact registry, immutable prediction/isolation and report-signing contracts | full 3x raw outputs, official+critical reports, signed publication 없음 |
| S40 | §40 자동 Gold | local-contract | deterministic/synthetic/metamorphic/round-trip fixtures | independent annotation QA와 private holdout approval 없음 |
| S41 | §41 실행 파일·코드 감사 대상 | implemented | frontend/router/retrieval/API/scheduler/benchmark/asset audit inventory | 이후 변경은 동일 inventory로 재감사해야 함 |
| S42 | §42 단일 실행 Campaign | blocked | wave별 artifacts와 local checkpoints 일부 존재 | Wave 0, 3, 4, 10, 11 hard gate가 열려 있음 |
| S43 | §43 에이전트 운영 규칙 | implemented | `AGENTS.md`, no-secret/fail-closed/evidence-boundary 규칙 | mock·TODO·manual 의존을 완료로 부를 수 없음 |
| S44 | §44 테스트 | local-contract | 1,119 Python, 184 Vitest, 71 E2E, 10 browser-matrix, 1 live journey 통과 | target-scale, physical-device, independent security evidence는 외부 gate |
| S45 | §45 Visual Quality Gate | implemented | 94/100, A01–A06 94–97, Critical 0, High 0, 532 current captures | field CWV와 external legal sign-off는 Production Gate |
| S46 | §46 Product Gate | local-contract | ingestion/credits/authority/compiler/export와 live local journey | rights-cleared corpus, production provider, downstream field import는 외부 gate |
| S47 | §47 Production Gate | blocked | Vercel web deployment는 Ready | latest SHA, revision, benchmark, providers, drills, legal 조건 미충족 |
| S48 | §48 최종 Definition of Done | blocked | 아래 45개 item별 ledger | implemented 6개 외에는 production 완료로 승격할 수 없음 |

## Wave 0–11 전수 매핑

| ID | Wave | 상태 | 현재 repository 증거 | release 경계 |
| --- | --- | --- | --- | --- |
| W00 | Wave 0 — Baseline & Deploy Truth | blocked | current audit, live probe, deployment manifest, branch/asset/control inventory | deployed/latest 불일치와 revision 미노출 |
| W01 | Wave 1 — Collection Ingestion | local-contract | collection APIs, manifests, resume/dedupe/version tests와 intake UI | 5,000-file/10GB actual resume 없음 |
| W02 | Wave 2 — Preflight & Credits | local-contract | static features, sample estimator, reserve/settle/refund contracts | calibration 및 real reconciliation evidence 없음 |
| W03 | Wave 3 — Autonomous Routing | local-contract | region attempts, authority geometry materialization, stale-verification revocation, quarantine and live local journey | production provider/hard-set evidence 없음 |
| W04 | Wave 4 — Parser Benchmarks | blocked | candidates/registry/evaluators/smoke contracts | provider smoke, Public Core 3회, private hard sets, champion report 없음 |
| W05 | Wave 5 — Knowledge Compiler | local-contract | schemas, domain packs, deterministic compilation/tests | actual precision-model corpus evaluation 없음 |
| W06 | Wave 6 — Retrieval | local-contract | hybrid retrieval/filter/rerank/numeric verifier code/tests | production store 및 DART/SEC benchmark 없음 |
| W07 | Wave 7 — Package | local-contract | Obsidian/ontology/Neo4j/RAG exporters와 round-trip fixtures | production import 및 signed package evidence 없음 |
| W08 | Wave 8 — Brand/Asset Reset | implemented | first-party master, variants, captures, motion, hash/provenance/score gates | final legal/brand clearance는 Production Gate |
| W09 | Wave 9 — Page Redesign | implemented | registered routes, 94/100 visual gate, 532 captures, 10-run browser matrix | canonical field performance는 Wave 11 외부 gate |
| W10 | Wave 10 — Operations | blocked | admin/telemetry/security/chaos local contracts | actual load, restore, billing, alert, canary evidence 없음 |
| W11 | Wave 11 — Release | blocked | local QA와 claim boundaries, web deployment Ready | latest CI/deploy SHA, CWV, live smoke, rollback rehearsal 없음 |

## §44–47 release-critical checks

### §44 Test gate

| ID | 요구사항 | 상태 | 현재 증거와 미충족 조건 |
| --- | --- | --- | --- |
| G44-UNIT | Unit/Contract 전 범위 | implemented | 1,119 Python tests, 184 Vitest tests, Ruff, mypy, strict TypeScript 통과 |
| G44-E2E | collection-to-package E2E | local-contract | 71 deterministic E2E와 real local API/database journey 통과; target-scale/provider evidence는 외부 |
| G44-VISUAL | 7 viewport와 state matrix | implemented | 532 actual-route captures와 fail-closed current-build/worktree validator 통과 |
| G44-BROWSER | Chromium/Firefox/WebKit/Edge/mobile | local-contract | 10/10 Chromium/Firefox/WebKit/installed Edge 및 mobile widths; physical-device sign-off 없음 |
| G44-A11Y | Axe/keyboard/screen-reader/zoom/contrast/motion | local-contract | 4/4 automated projects, keyboard, 200%, forced colors, motion 통과; physical screen-reader sign-off 없음 |
| G44-PERF | masterplan scale 및 CWV | blocked | LCP 3.2s 실패, 5,000 files/10GB/30,000 pages/1,000 SSE/100 uploads 없음 |
| G44-SECURITY | IDOR/RLS/upload/parser/XSS/webhook/credit | external-evidence-required | 로컬 validator/suites는 통과, independent production assessment와 drills 없음 |

### §45 Visual Quality Gate

| ID | 요구사항 | 상태 | 현재 증거와 미충족 조건 |
| --- | --- | --- | --- |
| G45-SCORE | 12차원 합계 90+ | implemented | current-worktree weighted score 94/100; rubric and evidence in `VISUAL_QA_REPORT.md` |
| G45-ZERO | Critical/High 및 금지 결함 0 | implemented | Critical 0, High 0; 532-capture automated inspection and representative manual review |

### §46 Product Gate

| ID | 요구사항 | 상태 | 현재 증거와 미충족 조건 |
| --- | --- | --- | --- |
| G46-01 | Collection upload complete | local-contract | collection/upload API와 UI 계약; production journey 없음 |
| G46-02 | Resume tested | local-contract | deterministic resume tests; 10GB/browser restart 없음 |
| G46-03 | Dedupe tested | local-contract | hash/idempotency tests; production object store evidence 없음 |
| G46-04 | Preflight estimate calibrated | local-contract | estimator tests; real calibration set 없음 |
| G46-05 | Credits reserve/settle/refund | local-contract | ledger/invariant tests; merchant reconciliation 없음 |
| G46-06 | No manual dependency | local-contract | autonomous verified path and fail-closed quarantine contracts pass locally; production provider journey remains external |
| G46-07 | Critical error escape 0 | external-evidence-required | private hard-set와 production incident evidence 필요 |
| G46-08 | Knowledge architecture generated | local-contract | deterministic blueprint/compiler contract; real corpus acceptance 없음 |
| G46-09 | All export packages import | local-contract | fixture round-trip; 실제 target versions 전체 import 없음 |
| G46-10 | Retrieval source miss 0 | external-evidence-required | rights-cleared DART/SEC benchmark 결과 없음 |

### §47 Production Gate

| ID | 요구사항 | 상태 | 현재 증거와 미충족 조건 |
| --- | --- | --- | --- |
| G47-01 | latest branch deployed | blocked | deployment가 latest HEAD보다 먼저 생성됨 |
| G47-02 | commit SHA visible | blocked | Vercel inspect와 `/api/health`에 SHA 없음 |
| G47-03 | real endpoint revisions | blocked | live `/v1/health/*`와 `/v1/admin/health`가 404 |
| G47-04 | Public Core 3× | blocked | full same-environment run artifacts 없음 |
| G47-05 | private hard sets | external-evidence-required | rights-cleared corpus와 independent approval 필요 |
| G47-06 | signed report | external-evidence-required | immutable raw outputs와 approval/signing key evidence 없음 |
| G47-07 | security/load/restore | external-evidence-required | production-like environment drill evidence 없음 |
| G47-08 | actual payment connector | external-evidence-required | merchant/KYC/webhook/reconciliation evidence 없음 |
| G47-09 | actual email/auth | external-evidence-required | production IdP와 verified sender evidence 없음 |
| G47-10 | legal/brand clearance | external-evidence-required | counsel/owner approvals 필요 |
| G47-11 | canary/rollback | external-evidence-required | same-revision canary와 one-change rollback record 없음 |

## §48 Definition of Done 전수 매핑

### Brand

| ID | 요구사항 | 상태 | 현재 증거와 미충족 조건 |
| --- | --- | --- | --- |
| DOD-BRAND-01 | 10초 내 문서를 지식 시스템으로 만든다 이해 | implemented | hero/copy/IA가 같은 promise를 사용함 |
| DOD-BRAND-02 | 세 signature scene | implemented | Drop Everything, Watch Knowledge Form, Receive a Knowledge System |
| DOD-BRAND-03 | generic AI aesthetic 없음 | implemented | first-party product-specific assets와 restrained design gate |
| DOD-BRAND-04 | P0 assets 90+ | implemented | asset quality ledger와 hash/provenance validators |

### Ingestion

| ID | 요구사항 | 상태 | 현재 증거와 미충족 조건 |
| --- | --- | --- | --- |
| DOD-INGESTION-01 | 폴더째 | local-contract | folder manifest/intake contract; hosted actual folder journey 없음 |
| DOD-INGESTION-02 | 5,000 files/10GB | blocked | 명시된 scale/interruption 결과 없음 |
| DOD-INGESTION-03 | pause/resume | local-contract | state/idempotency tests; real large upload 없음 |
| DOD-INGESTION-04 | browser restart | local-contract | resume token/session contract and browser E2E; 10GiB production interruption evidence 없음 |
| DOD-INGESTION-05 | dedupe | local-contract | hash and duplicate transition tests; production store 없음 |
| DOD-INGESTION-06 | partial failure isolation | local-contract | deterministic failure scenarios; real provider/object-store drill 없음 |

### Credits

| ID | 요구사항 | 상태 | 현재 증거와 미충족 조건 |
| --- | --- | --- | --- |
| DOD-CREDITS-01 | fast and sampled estimate | local-contract | estimator interface/tests; workload calibration 없음 |
| DOD-CREDITS-02 | P50/P95 | local-contract | quantile output contract; field error distribution 없음 |
| DOD-CREDITS-03 | hard cap | local-contract | policy and UI contract; production billing evidence 없음 |
| DOD-CREDITS-04 | actual settle | local-contract | idempotent ledger settle tests; actual merchant 없음 |
| DOD-CREDITS-05 | automatic refund | local-contract | refund/reversal invariants; invoice reconciliation 없음 |

### Intelligence

| ID | 요구사항 | 상태 | 현재 증거와 미충족 조건 |
| --- | --- | --- | --- |
| DOD-INTELLIGENCE-01 | adaptive routing | local-contract | router policy/tests; real model calibration 없음 |
| DOD-INTELLIGENCE-02 | region recovery | local-contract | attempt/fallback contracts; provider E2E 없음 |
| DOD-INTELLIGENCE-03 | authority numeric | local-contract | source/cell authority and verifier tests; private hard set 없음 |
| DOD-INTELLIGENCE-04 | no human dependency | local-contract | verified autonomous path, recovery, and terminal-state tests; production provider hard set 없음 |
| DOD-INTELLIGENCE-05 | unresolved/quarantine honest | implemented | unresolved items cannot complete, stale authority is revoked, quarantine and Integrity truth boundaries are tested |

### Knowledge

| ID | 요구사항 | 상태 | 현재 증거와 미충족 조건 |
| --- | --- | --- | --- |
| DOD-KNOWLEDGE-01 | directory/MOC | local-contract | blueprint and deterministic render tests; real corpus acceptance 없음 |
| DOD-KNOWLEDGE-02 | notes/entities/relations | local-contract | canonical model/compiler tests; precision model quality 없음 |
| DOD-KNOWLEDGE-03 | Obsidian | local-contract | exporter and fixture import; current desktop version matrix 없음 |
| DOD-KNOWLEDGE-04 | ontology | local-contract | deterministic ontology export; consumer validation 없음 |
| DOD-KNOWLEDGE-05 | Neo4j | local-contract | graph package contract; managed Neo4j import 없음 |
| DOD-KNOWLEDGE-06 | RAG | local-contract | chunk/provenance package contract; production retrieval evaluation 없음 |
| DOD-KNOWLEDGE-07 | provenance | implemented | source-map/CIR lineage, export hashes and regression tests |

### UX

| ID | 요구사항 | 상태 | 현재 증거와 미충족 조건 |
| --- | --- | --- | --- |
| DOD-UX-01 | actual Processing Theater | local-contract | ordered live-event component; deployed real-job run 없음 |
| DOD-UX-02 | no fake progress | local-contract | event-to-UI contract; reconnect/provider loss E2E 없음 |
| DOD-UX-03 | mobile | implemented | 360/390/768 current captures and browser-engine matrix pass |
| DOD-UX-04 | accessible | local-contract | Axe/keyboard/200%/forced colors/reduced motion pass; physical screen-reader sign-off 없음 |
| DOD-UX-05 | source proof ≤2 clicks | local-contract | proof navigation UI/tests; production-generated result journey 없음 |

### Quality

| ID | 요구사항 | 상태 | 현재 증거와 미충족 조건 |
| --- | --- | --- | --- |
| DOD-QUALITY-01 | Public Core | blocked | locked registry만 있고 full three-run result 없음 |
| DOD-QUALITY-02 | Finance/General/Robustness | blocked | approved private hard sets와 run artifacts 없음 |
| DOD-QUALITY-03 | Knowledge Compiler | external-evidence-required | rights-cleared corpus, model endpoint and independent quality approval 필요 |
| DOD-QUALITY-04 | Retrieval | external-evidence-required | production store와 DART/SEC source-miss evaluation 필요 |
| DOD-QUALITY-05 | visual/asset 90+ | implemented | P0 asset ledger 90+와 regression/hash gates |
| DOD-QUALITY-06 | Critical/High 0 | external-evidence-required | final release reviewer/security/visual sign-off 필요 |

### Operations

| ID | 요구사항 | 상태 | 현재 증거와 미충족 조건 |
| --- | --- | --- | --- |
| DOD-OPERATIONS-01 | telemetry | local-contract | OTel/metrics/rules contracts; live SLO/alert delivery 없음 |
| DOD-OPERATIONS-02 | admin | local-contract | local queue/DLQ/model controls; production API 404 |
| DOD-OPERATIONS-03 | billing | external-evidence-required | ledger tests만 있고 merchant/invoice evidence 없음 |
| DOD-OPERATIONS-04 | deletion | local-contract | scheduler/API deletion tests; production object/database proof 없음 |
| DOD-OPERATIONS-05 | backup/restore | blocked | timed isolated restore와 measured RPO/RTO 없음 |
| DOD-OPERATIONS-06 | incident | external-evidence-required | runbook은 있으나 actual drill/on-call/alert delivery 없음 |
| DOD-OPERATIONS-07 | canary/rollback | blocked | same-revision canary와 recorded rollback rehearsal 없음 |

## Promotion rule

`Production Reject`는 문서 편집이나 로컬 mock 결과만으로 변경할 수 없다. 모든 `blocked`
행을 해소하고, 모든 `external-evidence-required` 행을 한 immutable release revision에
연결한 다음, clean hosted CI와 matching deployment manifest를 생성해야 한다. 그 전에는
`promotion_authorized=false`다.
