# Structara v6 병렬 Runtime·RunPod 운영 Runbook

이 runbook은 v6 병렬 parse control plane을 운영하고 장애를 복구하는 절차다. `docs/runbooks/gpu-provider-jobs.md`의 durable provider 경계와 함께 적용한다. 이 문서의 어떤 smoke 절차도 모델 품질 또는 production Champion을 증명하지 않는다.

## 운영 불변식

다음 조건은 편의를 위해 완화할 수 없다.

- Pod가 HTTP 200을 반환해도 결과는 `ParseAttempt` candidate일 뿐이다.
- plan 시 필요한 L0–L6 validator identity와 revision을 pin한다.
- mandatory validator의 passing receipt가 없으면 acceptance와 credit consume 모두 금지한다.
- authority mismatch는 native 또는 model agreement로 덮지 않는다.
- 다수결만으로 candidate를 선택하지 않는다.
- retry, hedge, straggler, shadow, unresolved, quarantined output은 사용자에게 과금하지 않는다.
- repair, retry, hedge는 원본 attempt를 수정하지 않고 새 child attempt를 만든다.
- overlap page는 context-only이며 한 page에는 정확히 한 primary owner만 있다.
- unresolved는 manifest에 남기고, quarantined·failed는 기본 export에서 제외한다.
- endpoint 정리는 provider GET 404와 tagged orphan audit까지 끝나야 완료다.

## 구성요소와 책임

```text
AdaptiveShardPredictor / DeterministicShardPlanner
  -> AutonomousV6PipelineCoordinator checkpoint/CAS saga
  -> DurableParallelOrchestrator.persist_plan
  -> dispatch/start
  -> durable GPU invocation
  -> scheduler parallel_v6 output admission
  -> receive_output (OUTPUT_RECEIVED -> VALIDATING)
  -> L0-L6 validator receipts
  -> authority-first arbitration
  -> atomic accepted block + credit consume
  -> post-accept semantic impact invalidation + single refund + recovery
  -> recovery / continuity merge
  -> fail-closed document finalization
  -> snapshot/API/SSE-backed product UI
```

| 계층 | 주요 경로 | 책임 |
| --- | --- | --- |
| domain core | `packages/parallel-runtime/src/akc_parallel_runtime/` | deterministic decision, state, validation, recovery, merge, credit invariants |
| durable adapter | `services/api/src/akc_api/parallel_orchestrator.py` | tenant/document scope lock, atomic rows/events/credits, replay conflict detection |
| persistence | `parallel_models.py`, `parallel_runtime_store.py`, migrations `0031`/`0032` | 10 tables, append-only evidence/invalidation, single-refund integrity, RLS, least privilege |
| provider bridge | `gpu_jobs.py`, scheduler `parallel_v6_admission.py` | exact envelope/result attestation; output receipt only, no implicit acceptance |
| autonomous scheduler | `autonomous_v6_pipeline.py`, `trusted_v6_admission.py` | progress digest/CAS checkpoint, persisted Ed25519 exact-context admission, bounded recovery/hedge, crash-safe resume |
| event contract | `packages/cir-python/src/akc_cir/collection_events.py` | 16 canonical v1 events and ordering/state validation |
| read model/UI | `parallel_api.py`, `apps/web/src/components/v6/` | tenant-safe snapshot, truthful parallel/recovery/integrity state |
| benchmark/RunPod | `benchmark/v6/`, `infra/runpod/v6/` | exact-three, ledger, provider API, spend and cleanup receipts |

## 사전 점검

1. release 후보 commit과 dirty 상태를 기록한다.
2. candidate/dataset/pool registry의 hash와 license 상태를 확인한다.
3. 실행 모델의 model revision, artifact manifest, image digest, adapter, prompt, decoding, GPU/CUDA identity가 모두 immutable인지 확인한다.
4. inference container에는 GT를 mount하지 않는다. evaluator만 locked GT를 읽는다.
5. PostgreSQL migrations `0031_parallel_pod_runtime`, `0032_accepted_block_invalidations`가 적용됐고 runtime 역할이 migration owner가 아닌지 확인한다.
6. object store presigned URL, validator/evaluator capacity, database capacity와 provider quota를 확인한다.
7. `RUNPOD_API_KEY`는 secret manager가 현재 process에만 주입한다. 파일 경로, 값, header, provider error body를 로그에 남기지 않는다.

로컬 계약 점검:

```powershell
$env:PYTHONPATH = 'packages\parallel-runtime\src'
.\.venv\Scripts\python.exe -m pytest -q packages\parallel-runtime\tests
.\.venv\Scripts\python.exe -m pytest -q benchmark\tests\v6
.\.venv\Scripts\python.exe -m ruff check packages\parallel-runtime benchmark\v6 benchmark\tests\v6 infra\runpod\v6
$env:MYPYPATH = 'packages\parallel-runtime\src'
.\.venv\Scripts\python.exe -m mypy --strict packages\parallel-runtime\src\akc_parallel_runtime
.\.venv\Scripts\python.exe -m benchmark.v6.preflight
```

`preflight`의 정상적인 현재 release 경계는 local contract pass와 production reject가 동시에 나타나는 것이다. 외부 증거가 없는 상태에서 production pass가 나오면 오히려 release blocker로 취급한다.

## 정상 처리 절차

### 1. Plan과 validator pin

- `ParallelRuntimeScope`의 tenant, collection, document, document version, processing job을 먼저 고정한다.
- page descriptor와 continuity signal로 deterministic plan을 만든다.
- 모든 page가 정확히 한 primary ownership에 포함되는지, overlap은 context-only인지 확인한다.
- L0–L6 validator의 key/revision 전체를 plan context에 pin한다.
- 같은 operation key replay는 byte-equivalent plan만 허용한다.

정상 결과:

- `parse_shards.status=PLANNED`
- shard별 `shard.planned.v1` 하나
- plan replay 시 새 shard/event 없음

### 2. Dispatch와 start

- capability, model/image identity, infrastructure health, semantic health, data policy를 통과한 worker만 선택한다.
- queue priority와 tenant round-robin fairness를 유지하고 large shard를 size-aware bin packing한다.
- dispatch는 immutable child attempt를 만들고 `shard.dispatched.v1`을 같은 transaction에 기록한다.
- provider invocation은 `parse_attempts.provider_invocation_id`와 1:1로 결합한다.
- network 호출을 DB write transaction 안에서 실행하지 않는다.

정상 상태:

```text
CREATED -> QUEUED -> RUNNING
```

### 3. GPU output admission

GPU request의 `options.parallel_v6` envelope는 tenant/collection/job/document/version/shard/attempt, input/request SHA-256, output object key, model revision, runtime image digest, adapter version을 고정한다.

provider result가 오면 scheduler는 다음을 모두 재검증한다.

- provider invocation과 result의 tenant/job/input/output scope
- exact model/runtime/adapter identity
- result manifest와 object SHA-256
- persisted shard/attempt/document version scope
- signed `parallel_v6_verification` envelope의 canonical signature와 validator revision binding
- persisted admission envelope의 pinned Ed25519 public key·key ID와 서명된 envelope metadata
- tenant/collection/job/document/version/source/shard/submission/attempt/dispatch/recipe/worker/provider/output/candidate material/model/runtime/release exact binding

`PRODUCTION_SIGNED` enum, 임의 64-hex digest, always-true verifier, process-local self assertion은 production evidence가 아니다. 승인된 immutable reader와 pinned public key가 구성되지 않으면 production mode는 의도적으로 실패해야 한다. payload·candidate·attempt·job·release 변경, 다른 key, 다른 context replay도 모두 거부한다.

성공해도 이 단계는 output만 저장한다.

```text
RUNNING -> OUTPUT_RECEIVED -> VALIDATING
event: attempt.output.received.v1
```

이 단계에서 `accepted_blocks` 또는 credit consume이 생기면 즉시 hard fail로 간주한다.

### 4. Validation과 arbitration

Validator pipeline:

```text
L0 Transport
L1 Structural
L2 Native comparison
L3 Authority
L4 Differential
L5 Multimodal
L6 Downstream
```

- required level마다 정확히 pin된 validator key/revision의 append-only receipt를 기록한다.
- `failed`, `abstained`, `unavailable`, hard fail, missing receipt는 acceptance 불가다.
- authority-required work는 exact authority가 없으면 model agreement로 강등하지 않는다.
- hard-gate failed candidate는 score 계산 전에 제외한다.
- 해결되지 않은 충돌은 `unresolved`, `recovery_required` 또는 `quarantined`로 유지한다.

### 5. Acceptance와 credit

acceptance는 다음을 한 DB transaction에서 처리한다.

1. scope, shard, attempt, output hash를 다시 lock하고 확인한다.
2. mandatory validator receipts와 arbitration decision을 다시 확인한다.
3. logical block single winner를 생성한다.
4. canonical `credit_settlement_key`로 credit consume을 정확히 한 번 기록한다.
5. attempt와 shard를 accepted로 전이한다.
6. `attempt.accepted.v1`을 기록한다.

허용된 billable final state:

```text
verified
authority_verified
cross_model_verified
auto_repaired  # base/repair lineage와 provenance 필수
```

다음 상태의 credit amount는 항상 0이다.

```text
retry / hedge / straggler / shadow
unresolved / quarantined / failed
```

같은 settlement key replay가 다른 amount, logical block, attempt 또는 artifact를 주장하면 처리하지 말고 incident를 연다.

### 6. Recovery와 continuity

Semantic failure는 가능한 가장 작은 범위에서 복구한다.

```text
cell -> row -> table -> region -> page -> page_group
```

- base attempt와 diff를 보존한다.
- preprocessing variant, alternate model/worker와 route lineage를 기록한다.
- repair도 모든 required validator를 다시 통과해야 한다.
- 이미 완료된 문서의 accepted output이 quarantine되면 `Document=PROCESSING`, `ProcessingJob=running`으로 되돌리고 `completed_at`과 terminal scheduler checkpoint를 회수한다.
- `parallel_v6_recovery` projection의 epoch, invalidation set hash, revoked checkpoint hash를 보존한다.
- 원 ACCEPTED attempt/block은 immutable history로 남기고, 같은 shard의 새 `RECOVERY` attempt가 generation 2 이상의 active block을 만들도록 한다.
- continuity merge는 ownership, overlap dedupe, marginal 제거, heading/paragraph/list/table/figure-caption/footnote order를 검증한다.
- page·block·row/source provenance conservation 실패 시 Markdown을 내보내지 않는다.

### 7. Finalization

문서 finalization 전에 다음을 확인한다.

- required shard가 모두 accepted이거나 정책상 non-blocking unresolved manifest에 명시됨
- quarantined와 failed shard는 export에서 제외됨
- accepted block과 credit ledger가 1:1 일치함
- accepted block에 현재 job·document version·generation·arbitration·content SHA가 직접 결속됨
- invalidation이 존재하는 block은 active manifest와 customer charge에서 제외되고 refund가 정확히 한 번 결속됨
- continuity merge receipt가 현재 accepted inputs와 같은 hash를 참조함
- source refs와 page coverage가 완전함

`document.finalized.v1`은 이 확인과 document state update가 같은 transaction에서 성공한 뒤에만 기록한다.

복구 후 re-finalization은 invalidated block마다 더 높은 active generation이 존재하는지 확인한다. quarantine 또는 finalization replay는 완료된 recovery epoch, refund, 새 consume, RecoveryTask, shard 상태를 다시 생성하거나 후퇴시켜서는 안 된다.

## RunPod endpoint lifecycle

CLI는 기본이 dry run이다. 실제 provider 호출은 `--execute`를 명시하고 process-local `RUNPOD_API_KEY`가 있을 때만 수행한다. receipt path는 새 파일이어야 하며 기존 evidence를 덮어쓰지 않는다.

### 1. Evidence root와 dry run

```powershell
$EvidenceRoot = 'D:\release-evidence\structara-v6\cohort-<id>'
New-Item -ItemType Directory -Path $EvidenceRoot

.\.venv\Scripts\python.exe -m infra.runpod.v6 `
  --receipt-out "$EvidenceRoot\01-create-dry-run.json" `
  create --spec 'D:\secure\endpoint-spec.json' --idempotency-key 'idem-<64hex>'
```

spec에는 secret value를 넣지 않는다. model revision, image digest, GPU pool, worker bounds, scaling, timeout, run tag가 cohort manifest와 일치해야 한다.

### 2. Inventory와 create

```powershell
.\.venv\Scripts\python.exe -m infra.runpod.v6 --execute `
  --receipt-out "$EvidenceRoot\00-inventory-before.json" inventory

.\.venv\Scripts\python.exe -m infra.runpod.v6 --execute `
  --receipt-out "$EvidenceRoot\02-create-live.json" `
  create --spec 'D:\secure\endpoint-spec.json' --idempotency-key 'idem-<64hex>'
```

create 후 run tag와 exact endpoint ID를 inventory로 재확인한다. 같은 tag의 예상하지 않은 endpoint가 있으면 dispatch하지 말고 orphan/runaway incident로 전환한다.

### 3. 정확히 3회 cohort

```powershell
.\.venv\Scripts\python.exe -m infra.runpod.v6 --execute `
  --receipt-out "$EvidenceRoot\03-dispatch.json" `
  cohort-dispatch --manifest 'D:\secure\cohort-manifest.json'

.\.venv\Scripts\python.exe -m infra.runpod.v6 --execute `
  --receipt-out "$EvidenceRoot\04-status.json" `
  cohort-status --manifest 'D:\secure\cohort-manifest.json'

.\.venv\Scripts\python.exe -m infra.runpod.v6 --execute `
  --receipt-out "$EvidenceRoot\05-report.json" `
  cohort-report --manifest 'D:\secure\cohort-manifest.json'
```

- ledger는 dispatch intent를 provider write 전에 기록한다.
- provider가 acknowledgement한 job은 재실행 시 resume하며 다시 dispatch하지 않는다.
- write outcome이 ambiguous하면 자동 retry하지 않는다. inventory/status와 provider support evidence로 원래 job을 확인하기 전까지 hard stop한다.
- run-1/2/3 prediction·log·official·critical root를 절대 섞지 않는다.

### 4. Billing 조회

```powershell
.\.venv\Scripts\python.exe -m infra.runpod.v6 --execute `
  --receipt-out "$EvidenceRoot\06-provider-billing.json" `
  billing --bucket-size hour --last-n 24 --endpoint-id '<endpoint-id>'
```

provider spend와 user charge는 별도 ledger다. billing API가 0 records를 반환해도 반영 지연 또는 invoice lag를 배제할 수 없으므로 “무료” 또는 “actual cost 0”으로 확정하지 않는다. 최종 release 보고서는 provider invoice reconciliation 시각과 hash를 포함해야 한다.

### 5. Drain·delete·absence·orphan audit

cleanup은 model/output/evaluator evidence를 영구 보존한 뒤 실행한다.

```powershell
.\.venv\Scripts\python.exe -m infra.runpod.v6 --execute `
  --receipt-out "$EvidenceRoot\07-cleanup.json" `
  cohort-cleanup --manifest 'D:\secure\cohort-manifest.json' `
  --confirm-endpoint-id '<endpoint-id>' `
  --evidence-receipt-sha256 'sha256:<64hex>' `
  --artifacts-uploaded --grace-window-elapsed

.\.venv\Scripts\python.exe -m infra.runpod.v6 --execute `
  --receipt-out "$EvidenceRoot\08-orphan-audit.json" `
  audit-orphans --run-tag 'v6-cohort-<id>' `
  --deleted-endpoint-id '<endpoint-id>'
```

cleanup 완료 조건:

- queue empty
- in-flight 0
- artifacts uploaded
- evidence persisted and hashed
- grace window elapsed
- exact target confirmation
- provider GET 404 receipt
- same run tag orphan endpoint 0

`delete` acknowledgement만으로는 완료가 아니다.

## 2026-08-01 control smoke reference

이 기록은 운영 절차가 실제 provider와 연결됨을 확인한 control evidence다.

| 필드 | 값 |
| --- | --- |
| endpoint | `gjg2egc4wwvuts` — provider absent 확인 |
| run tag | `v6-control-smoke-20260801-01` |
| image | `runpod/serverless-hello-world@sha256:4da901aa929597f5f545753882530176dc63c5dead7b126ba6eec9a67b7bac7b` |
| 3 job status | 모두 `COMPLETED` |
| provider delay | 5,077 / 4,967 / 4,921 ms |
| provider execution | 149 / 139 / 153 ms |
| pre-cleanup billing | 0 records; 최종 실제 비용으로 단정 금지 |
| cleanup | `GET_404_NOT_FOUND`, `sha256:d968ac2e2702a40db4ecb5c95b5866c043f2d7c2ae40a32f6783efa149e4abbb` |
| orphan audit | passed, orphan 0, `sha256:a875a4c897ddbd88e36cfea8545619c8f4e96c539708d7e05d2eaa9892898671` |

hello-world output은 model quality, parser accuracy, public benchmark repeat 또는 Champion evidence가 아니다.

## 장애 대응

### HTTP 200 + semantic failure

1. output receipt를 보존한다.
2. attempt를 acceptance하지 않고 semantic reason으로 reject한다.
3. worker/model/image semantic health를 갱신한다.
4. canary reproduction 조건을 평가한다.
5. threshold 충족 시 drain 또는 quarantine한다.
6. 최근 영향 attempt를 찾고 아직 accepted 전이면 격리한다.
7. 최소 범위 recovery 또는 alternate independent model을 새 child attempt로 실행한다.
8. false verified 가능성이 있으면 release와 billing을 동결하고 영향분석을 연다.

### Worker OOM/crash/timeout

1. failure domain을 infrastructure로 기록한다.
2. 같은 output이나 attempt를 덮어쓰지 않는다.
3. bounded policy에 따라 다른 worker/GPU/image의 새 child attempt를 만든다.
4. memory slope, checksum, image identity 문제가 있으면 worker를 drain한다.
5. provider compute cost는 telemetry에 남기되 실패 attempt를 user billing하지 않는다.

### Ambiguous provider write

1. 동일 요청을 자동 재전송하지 않는다.
2. hash-chain ledger의 intent와 마지막 acknowledged event를 보존한다.
3. provider inventory와 known job status로 원래 write를 조회한다.
4. 결과를 식별할 수 없으면 cohort를 hard stop하고 spend incident를 연다.
5. 새 endpoint/cohort는 기존 resource 부재 또는 명시적 폐기 증거 후에만 만든다.

### Straggler

1. predicted p95 × 1.2 초과 또는 마지막 5–10% outlier인지 확인한다.
2. shard/attempt당 hedge 한도를 확인한다.
3. independent compatible worker에 새 unbillable child를 만든다.
4. 첫 verified result만 accept한다.
5. 나머지는 cancel 가능하면 cancel하고, 완료되면 challenger evidence와 provider cost만 기록한다.

### Validator unavailable 또는 revision mismatch

- mandatory validator면 unresolved 또는 recovery로 보낸다.
- validator identity를 즉석에서 바꾸거나 optional로 강등하지 않는다.
- 새 revision을 사용하려면 새 plan/release identity와 compatibility review가 필요하다.

### Credit mismatch 또는 duplicate charge

1. 신규 acceptance와 settlement를 즉시 중단한다.
2. `accepted_blocks.credit_settlement_key`와 credit ledger consume entry를 대조한다.
3. 같은 key의 content drift, 둘 이상의 consume, billable state mismatch를 hard fail한다.
4. 원본 ledger를 수정하지 말고 보상 entry 또는 승인된 reconciliation workflow를 사용한다.
5. incident가 닫힐 때까지 G8/MP6/G9를 reject로 유지한다.

### Cost anomaly 또는 orphan endpoint

1. 새로운 dispatch를 중지하되 기존 evidence를 삭제하지 않는다.
2. run tag로 endpoint inventory를 수집한다.
3. in-flight와 artifact upload를 확인한 뒤 정확한 endpoint만 drain한다.
4. exact ID confirmation으로 delete하고 GET 404를 받는다.
5. tagged orphan audit가 0이 될 때까지 incident를 닫지 않는다.

## 운영 조회

사용자-facing snapshot:

```text
GET /v1/collections/{collection_id}/parallel/documents/{document_id}
```

과거 evidence를 명시적으로 조회하거나 active lineage를 고정할 때에는 두 query parameter를 항상 함께 전달한다.

```text
?processing_job_id={uuid}&document_version_id={version}
```

한쪽만 전달하면 422, scope가 없으면 404, active job/version이 모호하거나 새 active job이 아직 materialize되지 않았으면 409다. 기본 조회도 오직 하나의 unambiguous active scope 또는 active가 없을 때 최신 materialized scope만 선택한다.

snapshot에서 최소 확인할 항목:

- total과 반환된 row 수, truncation flag
- 응답의 processing job ID, document version ID, processing job status
- shard/attempt state counts
- active page ownership 수
- validator current state
- unresolved/quarantined shard 수
- accepted block과 credit ledger mismatch count
- provider GPU milliseconds와 cost 존재 여부

shard, attempt, validation, accepted/invalidation, recovery, continuity, arbitration, consume/refund ledger와 SSE URL은 모두 선택된 job/version lineage로 제한돼야 한다. 다른 세대의 hard fail, refund, cost가 섞이면 incident로 취급한다.

DB를 직접 수정하지 않는다. read-only 운영 질의는 tenant scope를 명시하고 다음을 대조한다.

```sql
SELECT status, count(*) FROM parse_shards
WHERE tenant_id = :tenant_id AND document_id = :document_id
GROUP BY status;

SELECT state, billing_disposition, count(*) FROM parse_attempts
WHERE tenant_id = :tenant_id AND shard_id = ANY(:shard_ids)
GROUP BY state, billing_disposition;

SELECT final_state, billable, count(*), sum(credit_amount)
FROM accepted_blocks
WHERE tenant_id = :tenant_id AND document_id = :document_id
GROUP BY final_state, billable;
```

## Release와 rollback

Production promotion 전에는 다음이 한 immutable release identity에 묶여야 한다.

- exact source commit과 clean CI
- model/dataset/runtime/prompt/decoding/evaluator identity
- Public Core candidate/incumbent 정확히 3회
- private/robustness/knowledge/package/retrieval evidence
- actual model speedup, GPU seconds, provider billing reconciliation
- failure bundles와 semantic health drills
- endpoint cleanup와 orphan 0 receipts
- signed external evidence와 unresolved Champion Matrix 해소

hard fail 시 narrowest route/pool을 먼저 비활성화하고, last signed application/config/model tuple로 rollback한다. DB evidence row를 편집하거나 terminal attempt를 재사용하지 않는다. 자세한 application rollback 절차는 `docs/runbooks/deployment-rollback.md`를 따른다.
