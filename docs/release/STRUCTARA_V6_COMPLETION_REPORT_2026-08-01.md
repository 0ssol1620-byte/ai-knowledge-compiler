# Structara v6 구현 완료·Production Gate Truth Report

- 보고일: 2026-08-01
- 기준 마스터플랜: `Structara_FINAL_Parallel_Pod_Adaptive_Routing_Autonomous_Verification_Masterplan_v6_KO_2026-08-01.md`
- 문서 ID: `STRUCTARA-PARALLEL-POD-ADAPTIVE-ROUTING-AUTONOMOUS-VERIFICATION-V6-KO-20260801`
- 저장소: `0ssol1620-byte/ai-knowledge-compiler`
- 브랜치: `agent/structara-ultra-premium-rebuild`
- canonical web: `https://structara-knowledge-compiler.vercel.app`
- 구현 판정: **v6 local architecture and control-plane implementation complete for the recorded scope**
- production promotion 판정: **REJECT**
- Champion 판정: **UNRESOLVED — production primary 선택 금지**

## 결론

v6의 병렬 runtime 핵심은 코드, 데이터 모델, event contract, API read model, scheduler admission, UI, benchmark control plane과 RunPod lifecycle로 구현됐다. 출력은 candidate로만 받아들이고, pin된 validator evidence와 authority-first arbitration을 통과한 single winner만 accepted·billable이 되도록 fail closed한다. retry·hedge·straggler·unresolved·quarantined work의 사용자 중복 과금을 막고, region recovery와 document continuity merge도 immutable lineage 위에서 동작한다.

또한 실제 RunPod endpoint를 만들어 정확히 3개 control job을 완료하고, endpoint 삭제 후 provider GET 404와 tagged orphan 0을 확인했다.

그러나 이 실제 실행은 공식 hello-world image를 사용한 **control-plane smoke**다. mandatory OCR/Parser/Knowledge Compiler 모델, 세 Public Core suite, private hard set, robustness set, 실제 model speedup·verified-page cost, failure drills, package/retrieval 품질과 signed external release evidence는 수행 완료되지 않았다. 따라서 마스터플랜의 최종 production 정의와 G9는 충족되지 않았고, 그 사실을 코드와 문서가 명시적으로 거부한다.

## 완료된 구현

### 1. 병렬 domain core

`packages/parallel-runtime`에 provider/database 비의존 domain core가 추가됐다.

- model/runtime stack별 endpoint pool 격리
- adaptive shard sizing과 deterministic shard plan
- continuity group atomicity와 overlap context-only ownership
- document/page/region/recovery router, capability·health·policy filtering
- quality-cost-latency-failure objective와 shadow promotion fence
- cascade, high-risk speculative execution, hedge, straggler replication
- immutable attempt state machine과 full parent/root lineage
- infrastructure/semantic failure 분리와 dual worker health
- L0–L6 validator pipeline과 mandatory evidence pin
- authority-first arbitration과 majority-only 금지
- cell→row→table→region→page→page-group recovery
- cross-page table, heading, paragraph, list, figure-caption, footnote continuity merge
- verified-only fail-closed finalization
- exactly-once credit reservation/settlement과 duplicate compute telemetry
- deterministic benchmark aggregation과 same-environment repeat identity

### 2. Durable API·database 통합

다음 10개 table이 migration `0031_parallel_pod_runtime.py`, `0032_accepted_block_invalidations.py`와 ORM에 정의됐다.

```text
parse_shards
parse_attempts
attempt_validations
worker_health
semantic_health_events
continuity_edges
accepted_blocks
recovery_tasks
arbitration_decisions
accepted_block_invalidations
```

보호 계약:

- tenant/document/job/version scope cross-check
- row lock 기반 operation serialization
- content-bound idempotent replay
- append-only validation, semantic health, continuity, accepted block, arbitration evidence
- terminal/output attempt immutability
- PostgreSQL RLS와 `akc_dispatch_worker`·`akc_gpu_worker` 최소 권한
- mandatory validator key/revision missing 또는 mismatch 시 acceptance 금지
- accepted block과 credit ledger consume의 atomic exactly-once 결합
- validation digest와 arbitration basis를 서버가 canonical persisted receipt에서 재계산
- accepted block을 job·document version·generation·arbitration·content SHA에 직접 결속
- 사후 semantic quarantine 시 영향 block을 서버가 발견하고 append-only invalidation·정확히 1회 refund·recovery를 원자적으로 생성
- 이미 완료된 문서에서 semantic quarantine이 발생하면 `Document=PROCESSING`, `ProcessingJob=running`으로 publishability를 회수하고 terminal scheduler checkpoint를 제거한 뒤 해시 결합 recovery epoch를 기록
- 동일 shard의 과거 ACCEPTED attempt는 불변으로 보존하면서 새 `RECOVERY` attempt와 generation 2 active block을 허용하고, 재-finalize와 quarantine/finalization replay가 상태·환불·재차감·recovery를 중복 생성하지 않도록 보장
- finalizer가 active accepted block의 provenance·coverage·canonical manifest를 검증하고 빈 shard 또는 다른 version의 결과를 거부
- unresolved/quarantined/failed finalization은 non-billable

`DurableParallelOrchestrator`는 plan, dispatch, start, output receipt, validation, arbitration, accept/reject, hedge, health, recovery, continuity, finalization을 동일한 durable scope와 event journal에 결합한다.

`AutonomousV6PipelineCoordinator`는 `ProcessingJob.progress`의 digest/CAS checkpoint 위에서 plan → route → dispatch → signed admission → L0–L6 validation → arbitration → bounded recovery/hedge → continuity → finalization을 실행한다. provider submit 직후 checkpoint 전에 crash가 나도 결정적 operation key로 재개하며 같은 submit 또는 customer settlement를 반복하지 않는다. production mode에서는 enum 또는 64-hex digest의 자기 주장, test/mock verifier, 미고정 키를 신뢰하지 않는다. 영속 저장소에서 읽은 봉투를 pinned Ed25519 public key로 검증하고 tenant/collection/job/document/version/source/shard/submission/attempt/dispatch/recipe/worker/provider/output/candidate material/model/runtime/release identity가 정확히 일치할 때만 production admission으로 인정한다.

### 3. GPU result admission

GPU invocation의 `parallel_v6` envelope는 다음 identity를 고정한다.

- tenant, collection, processing job, document, document version
- shard와 attempt
- expected input/shard/request SHA-256
- exact output object key
- model revision, runtime image digest, adapter version

Scheduler는 provider result와 persisted scope를 다시 대조하고 signed verification envelope를 검증한다. 이 admission은 `attempt.output.received.v1`과 `VALIDATING`까지 진행할 뿐, HTTP 200을 accepted 또는 billable로 변환하지 않는다. malformed, unknown, cross-scope, hash/revision drift는 provider completion까지 함께 rollback하도록 구현됐다. 서명 봉투의 payload와 key ID, 서명 시각, payload digest도 함께 서명 범위에 들어가며 payload/candidate 변조, 다른 attempt/job/release replay, unpinned key는 fail closed한다.

### 4. Event·API·UI

마스터플랜 §42의 16개 event가 CIR contract와 generated TypeScript contract에 반영됐다.

```text
shard.planned.v1
shard.dispatched.v1
attempt.started.v1
attempt.output.received.v1
attempt.validation.failed.v1
attempt.accepted.v1
attempt.rejected.v1
attempt.hedged.v1
worker.semantic.degraded.v1
worker.draining.v1
worker.quarantined.v1
recovery.region.requested.v1
recovery.completed.v1
continuity.merge.started.v1
continuity.merge.completed.v1
document.finalized.v1
```

API snapshot은 tenant/project/collection/document scope에 더해 하나의 `processing_job_id`·`document_version_id` lineage를 선택한다. 명시적 pair가 불완전하거나 잘못됐거나, active job/version이 모호하거나 아직 materialize되지 않았으면 4xx로 fail closed한다. shard, attempt, validation, accepted/invalidation, recovery, continuity, arbitration, consume/refund ledger를 선택된 lineage로만 집계하고 응답과 SSE URL에도 그 identity를 노출하므로 과거 job/version의 hard fail·refund·cost가 현재 결과에 섞이지 않는다.

v6 Processing Theater는 canonical event로만 concurrent page, recovery, verified, integrity, credit impact, pool/attempt/validator/GPU telemetry를 표시한다. unsupported schema, replay gap, conflicting sequence와 missing cost는 synthetic success 또는 synthetic zero로 보정하지 않고 fail-closed warning으로 노출한다.

### 5. Benchmark·RunPod control plane

`benchmark/v6`와 `infra/runpod/v6`에 다음이 구현됐다.

- 45 candidate registry; required 28
- 16 model-isolated disabled pool registry
- 3 Public Core suite의 immutable dataset/evaluator lock
- GT-isolated environment identity
- deterministic document-preserving benchmark sharding
- exactly-three same-environment repeat plan과 isolated roots
- Ed25519 signed evidence contract
- G0–G9 및 MP0–MP6 promotion computation
- unresolved Champion Matrix
- RunPod REST v2 management/queue/billing client
- zero implicit provider retry와 write-ahead idempotency
- append-only tamper/truncation-detecting hash-chain ledger
- provider spend와 accepted-only user billing 분리
- drain/delete/GET 404/orphan audit lifecycle
- soft cost alert와 duplicate/error/idle runaway hard stop

현재 preflight snapshot:

| 항목 | 값 |
| --- | ---: |
| candidates | 45 |
| required candidates | 28 |
| pinned model revisions | 20 |
| pinned revisions among required | 18 |
| promotion-eligible required | 0 |
| model pools | 16 |
| Public Core suites | 3 |
| required repeats per suite/cohort | 3 |
| local contract gate | pass |
| production gate | reject |

## 실제 RunPod control smoke

### 실행 identity

| 필드 | 실제 값 |
| --- | --- |
| cohort | `cohort-control-20260801` |
| run tag | `v6-control-smoke-20260801-01` |
| endpoint | `gjg2egc4wwvuts` |
| image | `runpod/serverless-hello-world@sha256:4da901aa929597f5f545753882530176dc63c5dead7b126ba6eec9a67b7bac7b` |
| GPU pool request | `AMPERE_16` |
| worker bounds | min 0, max 4 |
| scaling | queue delay 0.5 seconds |
| expected control budget | USD 0.10 |
| environment SHA-256 | `sha256:33cad48c7a4693cb6a9326839993e9d1978a9849e25b59a6d6a2159724519df7` |
| repeat plan SHA-256 | `sha256:43d96f8961532841143a43b7cfdd29cd49925adac0c152937c7edf7bea2a80d2` |

### 정확히 3회 결과

| Repeat | Provider status | Delay | Execution | Output SHA-256 |
| ---: | --- | ---: | ---: | --- |
| 1 | `COMPLETED` | 5,077 ms | 149 ms | `sha256:07cf55095ef805a89c07bf3d4764b07352a8f4b2cc3df166e89d2193131536bd` |
| 2 | `COMPLETED` | 4,967 ms | 139 ms | `sha256:07cf55095ef805a89c07bf3d4764b07352a8f4b2cc3df166e89d2193131536bd` |
| 3 | `COMPLETED` | 4,921 ms | 153 ms | `sha256:07cf55095ef805a89c07bf3d4764b07352a8f4b2cc3df166e89d2193131536bd` |

관측 평균은 delay 약 4,988.3 ms, provider execution 147.0 ms다. 이 수치는 hello-world control workload에만 해당하며 OCR 모델 속도나 multi-worker speedup으로 일반화하지 않는다.

### 비용과 cleanup

| 항목 | 실제 관측 |
| --- | --- |
| pre-cleanup billing query | 0 records, provider total field `0` |
| follow-up billing query | `artifacts/v6-runpod-smoke/06-provider-cost-followup.json`: 0 records, provider total field `0`, user charge `null` |
| follow-up receipt | `sha256:5df2e2354ae1f7310c49e69dcec862bd6e874ae68a6d84cf8d780bf154ccd499` |
| 비용 판정 | **미정산·미확정** — 두 조회 모두 빈 records였지만 provider billing 반영 지연을 배제할 수 없어 무료 또는 actual cost 0으로 단정하지 않음 |
| user charge | model acceptance가 없는 control smoke이므로 customer charge 증거로 사용하지 않음 |
| cleanup provider observation | `GET_404_NOT_FOUND` at `2026-08-01T07:10:45.825363Z` |
| cleanup receipt | `sha256:d968ac2e2702a40db4ecb5c95b5866c043f2d7c2ae40a32f6783efa149e4abbb` |
| orphan audit | passed; active 0, tagged 0, orphan 0 |
| orphan receipt | `sha256:a875a4c897ddbd88e36cfea8545619c8f4e96c539708d7e05d2eaa9892898671` |

원시 receipt는 local ignored path `artifacts/v6-runpod-smoke/`에 있다. 후속 비용 조회까지 빈 records였다는 사실은 provider의 최종 정산·invoice 증거가 아니며 MP6 또는 actual model cost gate를 닫지 않는다. Git에 포함되지 않는다는 점 때문에, final external evidence package에는 별도 immutable store URI와 hash/signature를 기록해야 한다.

### 이 smoke가 증명하지 않는 것

- MinerU, PaddleOCR-VL, DeepSeek-OCR, Infinity Parser 또는 기타 candidate inference
- Parser accuracy, numeric exactness, row/page omission 또는 false verified 0
- OmniDocBench, ParseBench, olmOCR-Bench 3회 반복
- single-worker 대비 multi-worker speedup
- actual model GPU-seconds와 verified-page cost
- Knowledge Compiler, package import, retrieval quality
- production Champion 또는 router promotion

## 검증 상태

이 표는 2026-08-01 local release-candidate 회귀 결과와 focused 증거를 함께 기록한다. 테스트는 현재 worktree에서 통과했지만, 이 보고서와 deployment manifest 자체도 release commit에 포함되므로 작성 시점에 그 최종 commit SHA를 자기 참조 없이 확정할 수 없다. commit 직후 생성하는 attestation 또는 후속 deployment receipt에서 release SHA, clean hosted CI, Vercel deployment identity를 결합해야 한다.

| 검증 범위 | 관측 결과 | 상태 |
| --- | --- | --- |
| 전체 Python suite | 1,440 passed in 554.13s | local pass; release commit binding pending |
| web Vitest | `pnpm --filter @akc/web test`: 42 files, 200 tests passed, 192.71s | authoritative local pass; release commit binding pending |
| deterministic E2E | optimized standalone demo build에서 71 passed / 15 intentional skipped, 2.3m | pass; 의도된 skip은 failure로 변환하지 않음 |
| browser matrix | 9/9 passed | Chromium 360/390/768/1024/1280/1440/1920 + Firefox + WebKit |
| v4 brand evidence | 532 captures / 0 blocking | pass |
| 768 reduced-motion CLS | 12회 + 6회 반복 모두 CLS 0 | pass |
| Next.js production build | green | local production build pass |
| parallel runtime domain suite | 144 passed | pass, final snapshot |
| benchmark/v6 suite | 53 passed | candidate/release/gate/receipt replay 차단 포함 |
| P0/P1 closure focused | 45 passed in 55.23s | post-finalization 회수·generation 2 recovery, job/version snapshot 격리, migration, Ed25519 admission 포함 |
| autonomous scheduler SQLite saga·security | 14 passed | success, bounded recovery, straggler, crash resume, production mock/spoof/tamper/replay/unpinned-key rejection |
| scheduler full suite | 111 passed | pass |
| v6 web focused | 18 passed | pass, final snapshot |
| RunPod v2 client/coordinator subset | 14 passed | pass; included in benchmark/v6 suite |
| SQLite Alembic 0001→0032/head/check/down-to-0031/up/check | pass | local dialect proof only |
| PostgreSQL RLS/role/trigger contract | structural tests pass | managed PostgreSQL runtime proof pending |
| local dependency·repository security | pip-audit/pnpm audit/Bandit policy checks pass | independent external assessment는 아님 |
| hosted CI on release SHA | pending | release blocker |
| production deploy/live revision match | pending | release blocker |

## Gate 판정

### G0–G9

| Gate | 판정 | 이유 |
| --- | --- | --- |
| G0 Identity | blocked | required candidate의 artifact/image/license identity가 모두 완결되지 않음 |
| G1 Runtime | blocked | mandatory model cold/warm/restart/cache/leak receipts 없음 |
| G2 Public Core | blocked | candidate/incumbent full suites exact-three raw evidence 없음 |
| G3 Private Critical | blocked | approved authority/private set와 critical 0 evidence 없음 |
| G4 Robustness | blocked | Real5, Korean MDPBench, mutation/adversarial runs 없음 |
| G5 Knowledge | blocked | required compiler models의 real corpus evidence 없음 |
| G6 Package | blocked | actual target imports/round trip/SHACL/Neo4j/RAG evidence 없음 |
| G7 Retrieval | blocked | actual citation/source-miss/numeric/abstention evaluation 없음 |
| G8 Operations | partial | live RunPod control lifecycle와 cleanup은 증명; model cost/autoscale/alerts/rollback/managed service는 미증명 |
| G9 Production | reject | 모든 선행 gate를 통과하지 못함 |

### MP0–MP6

| Gate | 판정 | 이유 |
| --- | --- | --- |
| MP0 Sharding | local pass | deterministic ownership/context/page conservation tests |
| MP1 Parallelism | partial | control exact-three는 실제; model speedup/queue balance/accepted billing은 미측정 |
| MP2 Failure | partial | local state/drill tests만 있고 실제 provider kill/OOM/network evidence 없음 |
| MP3 Semantic Health | partial | silent error/quarantine local tests만 있고 actual bad-worker replay 없음 |
| MP4 Arbitration | local pass | authority priority, majority-only 금지, unresolved 보존 |
| MP5 Continuity | partial | deterministic fixtures는 통과; 실제 장문 corpus evidence 없음 |
| MP6 Cost | partial | endpoint cleanup/orphan 0; final invoice/model cost/speedup 미완료 |

## 열린 외부 차단 조건

### 모델과 runtime

1. 28 required candidate 모두 exact artifact manifest SHA-256, image digest, license receipt를 채운다.
2. 각 모델을 isolated image/pool에서 cold 3/3, warm 20/20, restart 3/3, offline cache와 GPU leak check까지 수행한다.
3. import/readiness 실패는 root cause와 reproduction bundle을 남긴다.

### Benchmark와 품질

1. OmniDocBench, ParseBench, olmOCR-Bench를 candidate와 incumbent 각각 동일 환경에서 정확히 3회 수행한다.
2. OmniDocBench의 research-only/noncommercial, olmOCR-Bench의 review-required 상태를 권리 검토 없이 public/commercial claim에 사용하지 않는다.
3. Real5-OmniDocBench, Korean MDPBench, private finance/long-table/Korean/research/real-world/security/mutation sets를 승인된 manifest와 GT 격리로 실행한다.
4. numeric critical, authority row omission, page omission, false verified가 실제 hard set에서 0임을 증명한다.

### 성능·비용·장애

1. 같은 model/environment/workload의 1-worker baseline과 2/4/8-worker cohort를 비교한다.
2. wall-clock, GPU-seconds, startup/warmup/idle/retry/overlap/duplicate waste, page·accepted-page·verified-page 비용을 기록한다.
3. provider billing history와 최종 invoice를 대사한다.
4. kill, OOM, network loss, cache corruption, semantic canary failure, straggler, quarantine, affected replay를 실제 endpoint에서 실행한다.

### Product·package·release

1. 실제 collection upload부터 package/export까지 canonical event 기반 E2E를 production-like stack에서 수행한다.
2. Obsidian, RDF/OWL/SHACL, Neo4j, RAG와 retrieval을 실제 target versions에 import하고 round-trip한다.
3. managed PostgreSQL migration, least-privilege roles, RLS, append-only triggers와 rollback을 검증한다.
4. raw output, evaluator results, failures, cost, cleanup receipts를 release commit/model/dataset/runtime identity에 묶고 external Ed25519 key로 서명한다.
5. clean hosted CI와 production deployment가 같은 release SHA를 노출하는지 live verify한다.

## Champion과 public claim

`benchmark/v6/champion-matrix.yaml`의 8개 page class primary는 현재 모두 `null`과 `unresolved`다. `korean_financial_table`, `english_filing`, `cross_page_table`의 recovery/authority hint는 primary Champion 선택이 아니다.

다음 표현은 금지한다.

- “Public Core 3회 완료”
- “production Champion 선정”
- “실제 OCR 모델 비용 0”
- “5× worker speedup 달성”
- “numeric critical 0”
- “모든 v6 production gate 통과”

해당 claim은 동일 immutable release의 signed actual evidence가 생긴 뒤에만 허용한다.

## Release 결론

```yaml
local_v6_architecture: implemented
runpod_control_smoke: passed
runpod_endpoint_cleanup: passed
orphan_endpoint_count: 0
mandatory_model_runs: not_completed
public_core_exact_three: not_completed
private_and_robustness_runs: not_completed
actual_model_speedup_and_cost: not_completed
signed_external_evidence: not_completed
champion_matrix: unresolved
production_promotion: rejected
```

v6는 “실패하거나 조용히 오독한 Pod의 출력도 성공으로 보이는 시스템”을 피하도록 구현됐다. 동시에 문서의 정직성 원칙에 따라, local implementation과 control smoke를 전체 model-quality completion으로 확장해 선언하지 않는다.
