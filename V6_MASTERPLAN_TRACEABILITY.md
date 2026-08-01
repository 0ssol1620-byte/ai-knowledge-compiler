# Structara v6 마스터플랜 요구사항 추적표

- 기준 문서: `D:\Structara_FINAL_Parallel_Pod_Adaptive_Routing_Autonomous_Verification_Masterplan_v6_KO_2026-08-01.md`
- 문서 ID: `STRUCTARA-PARALLEL-POD-ADAPTIVE-ROUTING-AUTONOMOUS-VERIFICATION-V6-KO-20260801`
- 기준 버전: `6.0.0`
- 평가일: 2026-08-01
- 대상 저장소: `D:\CodexProjects\ai-knowledge-compiler`
- 대상 브랜치: `agent/structara-ultra-premium-rebuild`
- 최종 판정: **Production Reject — 로컬 구현 계약은 광범위하게 갖춰졌으나 필수 외부 모델·데이터·품질·비용 증거가 아직 완결되지 않음**

이 문서는 “코드가 존재한다”, “로컬 테스트가 통과한다”, “실제 외부 실행 증거가 있다”를 서로 다른 상태로 기록한다. RunPod control smoke는 실제 provider lifecycle 증거지만 OCR/Parser 모델 품질, Public Core, 실제 모델 비용 또는 Champion의 증거가 아니다.

## 상태 정의

| 상태 | 의미 |
| --- | --- |
| `implemented-local` | 실행 가능한 코드·스키마·로컬 테스트 계약이 존재한다. 외부 운영 증거를 뜻하지 않는다. |
| `control-proven` | 실제 RunPod control-plane 요청과 endpoint 정리 영수증으로 해당 제어 경로를 확인했다. 모델 품질 증거가 아니다. |
| `partial` | 일부 구현 또는 일부 실제 증거만 존재해 전체 요구사항을 충족하지 못한다. |
| `blocked-external` | 모델·데이터·라이선스·provider·managed service·서명 등 외부 증거 없이는 닫을 수 없다. |
| `research-backlog` | 의도적으로 production 승격 근거로 사용하지 않는 연구 항목이다. |
| `reject` | 필수 gate가 열려 있어 승격할 수 없다. |

## 증거 경계

1. `packages/parallel-runtime` 테스트는 상태기계, 불변성, 검증, arbitration, recovery, continuity, scheduling, credit 계약을 증명한다. 실제 GPU 성능이나 외부 모델 정확도를 증명하지 않는다.
2. `benchmark/v6`와 `infra/runpod/v6` 테스트는 identity, 정확히 3회 반복, hash-chain ledger, provider API, runaway 방지와 cleanup 계약을 증명한다. mock transport 결과는 production evidence가 아니다.
3. 2026-08-01 실제 RunPod control smoke는 endpoint 생성, 정확히 3개 queue job, provider 상태 조회, drain/delete/GET 404, orphan 0을 증명한다. 공식 hello-world image를 사용했으므로 OCR·Parser·Knowledge Compiler 평가로 간주하지 않는다.
4. Public Core, private hard set, robustness, knowledge/package/retrieval 품질, 모델별 비용·speedup, 최종 서명 evidence가 없으면 G9는 항상 거부한다.

## §0–§23 실행·벤치마크 요구사항

세부 benchmark/RunPod 계약 매핑은 `benchmark/v6/REQUIREMENTS_TRACEABILITY.md`에 있으며, 아래 표는 저장소 전체의 release 경계를 함께 기록한다.

| 절 | 요구사항 | 구현·증거 | 상태 | 남은 필수 조건 |
| --- | --- | --- | --- | --- |
| §0 | 비용 비차단, 중복·runaway만 중단 | `infra/runpod/v6/orchestration.py`의 `SpendPolicy`·`SpendGuard`; mandatory work를 soft cost alert로 차단하지 않음 | `implemented-local` | 모든 필수 실제 모델 실행과 최종 비용 대사 |
| §1 | 최신 모델·dataset identity 조사 | `benchmark/v6/candidate-registry.yaml`, `dataset-registry.lock.yaml`; 45 candidates, required 28, model revision pin 20/required 18 | `partial` | 모든 required artifact manifest, image digest, license receipt |
| §2 | authority·hard-fail 우선 평가 | `benchmark/v6/promotion.py`, `akc_parallel_runtime/arbitration.py`, `validation.py` | `implemented-local` | 실제 benchmark raw output과 authority-backed hard set |
| §3–§4 | Parser·Compiler registry | `candidate-registry.yaml`; 미확정 identity는 promotion 불가 | `partial` | mandatory image build/readiness/benchmark receipts |
| §5 | Agent mesh, GT 격리, 독립 검증 | `benchmark/v6/contracts.py`, `evidence.py`, dataset policy | `implemented-local` | 실제 inference/evaluator 분리 환경 영수증 |
| §6 | 모델별 runtime 격리·readiness | `infra/runpod/v6/pool-registry.yaml`의 16개 disabled isolated pool | `partial` | 모델별 cold 3/3, warm 20/20, restart 3/3, offline cache, leak |
| §7 | Stage 0–8 승격 파이프라인 | registry/preflight/repeat/promotion 계약 | `partial` | 실제 smoke, challenge, full public/private/robustness/E2E |
| §8 | Public Benchmark gate | 세 suite revision·manifest·evaluator pin, GT isolation, prediction freeze, exact-three 계약 | `blocked-external` | OmniDocBench·ParseBench·olmOCR-Bench 실제 전체 3회 |
| §9 | text/numeric/table/formula/layout/reliability/performance metrics | run/evidence schema와 hard-gate 계약 | `partial` | 실제 evaluator output과 critical metric 0 증거 |
| §10 | verified부터 quarantined까지 자율 상태 | `VerificationState`, `Finalizer`, DB checks, UI event model | `implemented-local` | 실제 모델 failure/recovery 결과 |
| §11 | 최소 범위 recovery·early exit | `recovery.py`, `routing.py`, orchestrator recovery methods | `implemented-local` | provider 기반 recovery drill과 실제 quality delta |
| §12 | Knowledge Compiler 평가 | 기존 compiler/domain/export 계약과 v6 promotion blocker | `partial` | required compiler 모델 실제 corpus 평가 |
| §13 | Obsidian/RDF/Neo4j/RAG/reproducibility | 기존 deterministic exporter·retrieval 계약 | `partial` | 실제 target import, round-trip, SHACL/Neo4j/retrieval 증거 |
| §14 | Retrieval 최종 평가 | 기존 hybrid retrieval·numeric verification 계약 | `partial` | DART/SEC 및 private corpus 실제 source-miss·citation 평가 |
| §15 | 비용·실시간 routing | cost/latency 필드, scheduling, actual control timings | `partial` | 모델별 verified-page cost, speedup, provider invoice reconciliation |
| §16 | RunPod 실행 계약 | live REST v2 client; 실제 endpoint `gjg2egc4wwvuts`, 3 jobs completed, GET 404 cleanup, orphan 0 | `control-proven` | 모델별 endpoint와 actual benchmark 비용/성능 |
| §17 | Wave M0–M12 | local control plane과 schema 대부분 구현 | `partial` | M2–M9 실제 모델/benchmark/package/retrieval 및 signed release evidence |
| §18 | 필수 산출물 | registry, schemas, preflight, champion template 존재 | `partial` | predictions, official/critical results, failures, cost CSV, signed manifest |
| §19 | G0–G9 | `evaluate_promotion`이 모든 G/MP gate와 signed external evidence를 요구 | `reject` | 아래 G0–G9 표의 열린 조건 전체 |
| §20 | Champion Matrix | 8 page class가 모두 `unresolved`; production 아닌 후보 승격 금지 | `reject` | 실제 동일환경 평가와 production decision |
| §21 | 강제 실행·금지사항 | HTTP 200·mock·추정 score·majority-only·duplicate charge가 승격 불가 | `implemented-local` | 필수 실제 실행 자체는 미완료 |
| §22 | v5 Definition of Done | fail-closed preflight가 false completion을 거부 | `reject` | runtime, full benchmark, knowledge/package/retrieval, signed cost evidence |
| §23 | 공식 source registry | source identifier와 일부 immutable revision 보존 | `partial` | 모든 upstream identity·license 독립 검토 |

## §24–§47 v6 요구사항

| 절 | 요구사항 | 구현·검증 경로 | 상태 | 증거 경계 또는 남은 조건 |
| --- | --- | --- | --- | --- |
| §24 | adaptive intake부터 fail-closed finalization까지 통합 | `packages/parallel-runtime`, `parallel_orchestrator.py`, migrations 0031/0032, persisted Ed25519 admission, `autonomous_v6_pipeline.py`, v6 UI | `implemented-local` | production provider/document E2E 필요 |
| §25 | 병렬 speedup·비용·cache·early exit·duplicate/idle 방지 | scheduling/credits/spend guard; control job delay·execution 기록 | `partial` | 같은 모델 1-worker 대비 multi-worker speedup과 최종 provider bill 없음 |
| §26 | 모델별 pool, warm/flex/evaluator/orchestrator | `topology.py`, `pool-registry.yaml`, `runpod/v6` | `partial` | required 모델별 실제 isolated pool boot/health 없음 |
| §27 | context-aware adaptive sharding·overlap ownership | `sharding.py`; deterministic, exact-one-owner, context-only overlap, document group 보존 테스트 | `implemented-local` | 실제 장문 cross-page corpus 성능 증거 |
| §28 | hierarchical router v2·quality/cost objective·shadow promotion | `routing.py`; capability/identity/health/policy filter와 deterministic objective, shadow promotion gate | `partial` | 측정 데이터로 학습·calibration한 router shadow/canary 없음 |
| §29 | cascade·speculative·hedge·straggler | `routing.py`, `scheduling.py`; high-risk 조건, p95 hedge, last-10% straggler, first verified, duplicate unbillable | `implemented-local` | 실제 slow/straggler provider drill과 speedup evidence |
| §30 | immutable ParseAttempt·lineage·idempotency | `attempts.py`, `parallel_models.py`, `parallel_runtime_store.py`; job/version/generation direct scope, typed arbitration, server-derived settlement key, terminal/output DB immutability trigger | `implemented-local` | managed PostgreSQL production write-role evidence |
| §31 | infrastructure failure와 semantic failure 분리 | `failures.py`, validator, scheduler GPU admission; HTTP 200은 output receipt일 뿐 acceptance 아님 | `implemented-local` | 실제 OOM/crash/semantic-corruption drill |
| §32 | infrastructure/semantic 이중 health·drain/quarantine/replay | `health.py`, `record_worker_health`, `worker_health`, `semantic_health_events`; 완료 상태 회수, terminal checkpoint 무효화, append-only accepted-block invalidation·single refund·generation 2 recovery | `implemented-local` | production canary·selective replay receipt |
| §33 | L0–L6 validator pipeline | `validation.py`; plan 시 모든 validator revision pin, required receipt 없으면 accept/charge 불가 | `implemented-local` | 실제 model output에 대한 authority/multimodal/downstream receipts |
| §34 | authority-first arbitration·majority 금지 | `arbitration.py`, `persist_arbitration`; conflicting authority는 unresolved·미과금 | `implemented-local` | 실제 candidate 비교와 authority dataset |
| §35 | cell→row→table→region→page→page_group recovery | `recovery.py`, `recovery_tasks`, orchestrator request/complete | `implemented-local` | 실제 recovery quality, cost, failure bundle |
| §36 | continuity graph·overlap dedupe·table/heading/figure/footnote merge | `continuity.py`, `continuity_edges`, orchestrator start/complete | `implemented-local` | 실제 장문 document merge benchmark |
| §37 | fail-closed finalization·accepted-only billing | `finalization.py`, `credits.py`, active `accepted_blocks`, canonical coverage/provenance manifest, atomic acceptance·credit consume·post-accept invalidation/refund, replay-safe re-finalization | `implemented-local` | production ledger reconciliation과 invoice 증거 |
| §38 | deterministic benchmark shard와 정확히 3회 동일 환경 | `benchmark/v6/sharding.py`, `repeats.py`, `runpod_coordinator.py`, hash-chain ledger | `partial` | control cohort 3회는 완료; 세 Public Core model cohort 3회는 미실행 |
| §39 | priority/fairness/size-aware/least-loaded/backpressure/dynamic scale | `scheduling.py` 양쪽 구현과 tests | `implemented-local` | 실제 queue balance, capacity, autoscale field evidence |
| §40 | learned router, mixture, meta-verifier, query reparse, template memory, active evaluation, conformal abstention | 일부 promotion/shadow 계약만 존재 | `research-backlog` | production 완료로 주장하지 않음 |
| §41 | worker/silent error/multi-pod/straggler/continuity/quarantine scenario | domain·API·scheduler·RunPod focused tests; finalize→quarantine→generation 2 recovery→re-finalize, bounded recovery, straggler hedge, submit 직후 crash resume, signed-evidence spoof/tamper/replay reject | `partial` | 실제 kill/OOM/network/cache/straggler/quarantine drill |
| §42 | 10 tables, 16 events, idempotency | migrations 0031/0032, `parallel_models.py`, `collection_events.py`, generated contract, PostgreSQL RLS/append-only/refund integrity/least privilege | `implemented-local` | managed PostgreSQL migration·role exercise와 production broker evidence |
| §43 | product 용어, technical view, Integrity Console, real Processing Theater | `apps/web/src/components/v6`, job/version-isolated snapshot·SSE, canonical events | `partial` | deployed real-job SSE/reconnect/E2E 필요 |
| §44 | P0–P9 waves | P0 architecture, P1 crash-resumable orchestrator saga, P2/P4–P6 local contract, P3 control smoke, P7 promotion fence, P9 UI/local integration | `partial` | P3 실제 model multi-pod, P7 trained shadow, P8 full benchmark, P9 production E2E |
| §45 | MP0–MP6 | promotion gate에 모두 mandatory; 아래 gate 표 참조 | `reject` | MP1–MP3·MP5–MP6 외부 operation evidence 필요 |
| §46 | v6 강제 실행 prompt | 금지사항이 코드·preflight·문서에서 fail closed | `implemented-local` | “실행 완료” 조건인 external raw/signed evidence 미완료 |
| §47 | v6 Definition of Done | local architecture와 control lifecycle은 구현·검증됨 | `reject` | target speedup, actual model cost, critical 0, real failures, full product/package/retrieval 필요 |

## v6 데이터베이스·이벤트 계약

### Tables 10/10

`parse_shards`, `parse_attempts`, `attempt_validations`, `worker_health`, `semantic_health_events`, `continuity_edges`, `accepted_blocks`, `recovery_tasks`, `arbitration_decisions`, `accepted_block_invalidations`

Migrations `0031_parallel_pod_runtime.py`와 `0032_accepted_block_invalidations.py`는 PostgreSQL에서 tenant RLS, append-only evidence trigger, terminal/output attempt immutability, job/version/generation/arbitration/content 결속, single-refund integrity, `akc_dispatch_worker`와 `akc_gpu_worker`의 최소 권한을 정의한다. SQLite 0001→0032 head/check/down-to-0031/up/head round-trip은 구조 검증용이며 PostgreSQL 운영 증거를 대체하지 않는다.

### Events 16/16

`shard.planned.v1`, `shard.dispatched.v1`, `attempt.started.v1`, `attempt.output.received.v1`, `attempt.validation.failed.v1`, `attempt.accepted.v1`, `attempt.rejected.v1`, `attempt.hedged.v1`, `worker.semantic.degraded.v1`, `worker.draining.v1`, `worker.quarantined.v1`, `recovery.region.requested.v1`, `recovery.completed.v1`, `continuity.merge.started.v1`, `continuity.merge.completed.v1`, `document.finalized.v1`

## Gate G0–G9

| Gate | 판정 | 현재 근거 | 닫히지 않은 조건 |
| --- | --- | --- | --- |
| G0 Identity | `blocked-external` | immutable schema와 일부 revision pin | required candidate artifact/runtime/license identity 미완료 |
| G1 Runtime | `blocked-external` | isolated pool·readiness contract | 모델별 cold/warm/restart/offline/leak receipt 없음 |
| G2 Public Core | `blocked-external` | 세 suite lock과 exact-three contract | 실제 candidate/incumbent 전체 3회 raw result 없음 |
| G3 Private Critical | `blocked-external` | authority·critical gate 구현 | 승인된 private hard set와 critical 0 결과 없음 |
| G4 Robustness | `blocked-external` | mutation/robustness registry | Real5, Korean MDPBench, mutation/adversarial 실행 없음 |
| G5 Knowledge | `blocked-external` | compiler/schema/evidence local contract | required model·rights-cleared corpus 품질 증거 없음 |
| G6 Package | `blocked-external` | deterministic exporter local contract | 실제 Obsidian/RDF/Neo4j/RAG import·round trip 없음 |
| G7 Retrieval | `blocked-external` | hybrid/numeric verification local contract | actual DART/SEC/private retrieval evaluation 없음 |
| G8 Operations | `partial` | 실제 RunPod create/3 jobs/delete/orphan 0; local no-double-billing contract | model endpoints, autoscale, actual bill, alerts, rollback, managed services |
| G9 Production | `reject` | 계산형 gate가 누락 증거를 거부 | G0–G8와 MP0–MP6 전체 통과 및 외부 서명 필요 |

## Gate MP0–MP6

| Gate | 판정 | 현재 근거 | 닫히지 않은 조건 |
| --- | --- | --- | --- |
| MP0 Sharding | `implemented-local` | deterministic ownership, context overlap, page conservation tests | release-bound real corpus evidence 권장 |
| MP1 Parallelism | `partial` | 실제 control jobs 3개와 local balance/no-duplicate 계약 | 실제 동일 모델 multi-worker speedup·balanced queue·accepted billing |
| MP2 Failure | `partial` | crash/OOM/timeout/retry/drain state tests | 실제 provider failure drill |
| MP3 Semantic Health | `partial` | silent error/canary/quarantine/impact local tests | 실제 bad-worker canary와 affected replay |
| MP4 Arbitration | `implemented-local` | authority priority, majority-only 금지, unresolved 보존·미과금 | actual candidate evidence 없이는 production gate 미통과 |
| MP5 Continuity | `partial` | long-table/heading/list/figure/footnote/dedupe local tests | actual long-document quality evidence |
| MP6 Cost | `partial` | control endpoint cleanup GET 404와 orphan 0; no-runaway/duplicate billing contract | final provider invoice, verified-page cost, model speedup·cost report |

## 실제 RunPod control smoke

| 항목 | 실제 관측 |
| --- | --- |
| 목적 | RunPod v2 control plane, exact-three coordinator, ledger, status, cleanup 검증 |
| endpoint | `gjg2egc4wwvuts` — 삭제 완료 |
| image | `runpod/serverless-hello-world@sha256:4da901aa929597f5f545753882530176dc63c5dead7b126ba6eec9a67b7bac7b` |
| jobs | 정확히 3개, 모두 `COMPLETED` |
| delay | 5,077 / 4,967 / 4,921 ms |
| execution | 149 / 139 / 153 ms |
| billing 조회 | cleanup 전 0 records; provider 반영 지연 가능성이 있어 무료 또는 실제 비용 0으로 확정하지 않음 |
| cleanup | provider `GET 404`; receipt `sha256:d968ac2e2702a40db4ecb5c95b5866c043f2d7c2ae40a32f6783efa149e4abbb` |
| orphan audit | passed, orphan 0; receipt `sha256:a875a4c897ddbd88e36cfea8545619c8f4e96c539708d7e05d2eaa9892898671` |
| 품질 증거 여부 | 아님. hello-world control job은 OCR/Parser/Compiler/Public Core/Champion 증거가 아니다. |

원시 control receipts는 의도적으로 Git에서 제외된 `artifacts/v6-runpod-smoke/`에 있다. 최종 release evidence로 사용할 때에는 승인된 외부 evidence store에 보존하고 release commit과 서명해야 한다.

## 로컬 검증 스냅샷

아래 수치는 최종 커밋 후보에서 재실행한 local snapshot이다. commit SHA·hosted CI·배포 identity는 post-commit attestation에서 결합한다.

| 범위 | 관측 결과 | 의미 |
| --- | --- | --- |
| parallel domain core | 144 passed | 순수 domain safety·determinism 계약 |
| benchmark/v6 full focused suite | 53 passed | registry, exact-three, cross-candidate/release/gate/receipt replay 차단 |
| P0/P1 closure focused | 45 passed in 55.23s | post-finalization 회수·generation 2 recovery, job/version snapshot 격리, migration, Ed25519 admission |
| autonomous scheduler SQLite saga·security | 14 passed | success, bounded recovery, straggler, crash resume, mock/spoof/tamper/replay/unpinned-key reject |
| scheduler full suite | 111 passed | scheduler 전체 회귀 |
| v6 web focused | 18 passed | event-backed UI와 fail-closed projection |
| RunPod v2 client/coordinator subset | 14 passed | provider adapter·exact-three·ledger 계약; 위 53개 suite에 포함 |
| full repository regression | 1,440 passed in 554.13s | 전체 Python 회귀 |
| web Vitest | 42 files / 200 passed | authoritative fork pool 실행 |
| deterministic browser E2E | optimized standalone에서 71 passed / 15 intentional skipped, 2.3m | desktop/mobile/accessibility/visual/product journeys |
| Ruff / strict mypy | green / 181 source files | 전체 lint와 Python 정적 타입 계약 |
| SQLite migration round trip | 0001→0032→0031→0032, 10 tables, legacy unique index 1→0 | generation 2 ACCEPTED history 호환 구조; managed PostgreSQL 증거는 아님 |

## 열린 외부 차단 조건

1. 28개 required candidate의 exact model artifact manifest, runtime image digest, license receipt를 완결한다.
2. 모델별 cold 3/3, warm 20/20, restart 3/3, offline cache, GPU leak/readiness를 실제로 수행한다.
3. OmniDocBench, ParseBench, olmOCR-Bench를 candidate와 incumbent의 동일 immutable 환경에서 정확히 3회 수행한다.
4. Real5-OmniDocBench, Korean MDPBench, private finance/long-table/Korean/research/real-world/security/mutation set을 권리와 GT 격리를 확인한 뒤 실행한다.
5. 실제 모델 multi-worker 1× 대비 speedup, GPU-seconds, idle/retry/duplicate waste, page·accepted-page·verified-page 비용을 provider billing과 대사한다.
6. 실제 kill/OOM/network/cache/semantic/straggler/quarantine/selective-replay drill을 수행한다.
7. Knowledge Compiler, package imports, retrieval, live product journey를 한 release identity에 결합한다.
8. raw predictions, official/critical outputs, failure bundles, cleanup receipts와 final cost를 외부 release key로 서명한다.
9. 모든 page-class Champion primary는 그 전까지 `null`과 `unresolved`를 유지한다.

## 승격 규칙

`benchmark/v6/preflight.py`가 `production_gate=reject`를 보고하는 동안, 또는 `benchmark/v6/champion-matrix.yaml`에 unresolved primary가 있는 동안 production Champion 승격은 금지한다. control smoke, mock transport, adapter test, 로컬 score 또는 모델 다수결로 이 규칙을 우회할 수 없다.
