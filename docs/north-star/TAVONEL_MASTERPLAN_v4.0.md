# TAVONEL — ULTIMATE PRODUCTION RESEARCH & IMPLEMENTATION MASTERPLAN v4.0 FINAL
## Adaptive Economic Execution · Trusted Knowledge Compilation · Reality Synchronization · Evidence-First Product · Cinematic Experience · GTM · IP · AI-Native Solo Founder

**문서 상태:** FINAL SOURCE OF TRUTH v4.0 — MIGRATION + AUTONOMOUS IMPLEMENTATION + COMMERCIAL EXECUTION CONTRACT  
**작성 기준:** 2026-08-10 KST  
**공개 브랜드:** **TAVONEL**  
**공개 카테고리:** **The Knowledge Compiler**  
**주 구현 에이전트:** **Claude / Claude Code**  
**기본 인프라:** Vercel + Cloudflare R2 + Cloudflare Queues + RunPod + Managed PostgreSQL/pgvector  
**현재 검증 baseline:** MinerU 3.4.4 + FOLYNTA/TAVONEL Recovery Runtime  
**핵심 원칙:** **Evidence, not adjectives. Every claim has a receipt.**  
**v4 핵심 목적함수:** **Minimum Cost to Trusted Output**  

---

# DOCUMENT MAP

이 문서는 처음부터 끝까지 읽을 수 있지만, 실행 시에는 아래 순서로 사용한다.

1. **PART 0–1:** 제품 정의, 검증된 baseline, 현재 gap을 잠근다.
2. **PART 2–14:** backend, data, execution, knowledge, API/MCP의 normative architecture를 구현한다.
3. **PART 15–19:** 실제 제품 경험, benchmark/evidence, security, FinOps, IP/GTM을 backend와 같은 계약 위에 올린다.
4. **PART 20–21:** 현재 repository를 `KEEP / ADAPT / REPLACE / BUILD / DEPRECATE`로 전환하고 phase gate대로 진행한다.
5. **PART 22–27:** 1인 founder 운영, FMEA, repository/CI, Claude factory, test, runbook으로 실패와 운영을 닫는다.
6. **PART 28–31:** 외부 copy, 최종 완료 기준, launch gate, Claude Code 실행 명령을 따른다.
7. **APPENDIX A–E:** 계약 예시, 환경변수, metric, 공식 출처, 아직 주장하면 안 되는 항목을 확인한다.

## 전체 목차

- PART 0 — Executive Reset
- PART 1 — Verified Baseline & Current Gap
- PART 2 — V4 Reference Architecture
- PART 3 — Canonical Contracts & Database Design
- PART 4 — Industrial Ingestion
- PART 5 — Connector Control Plane
- PART 6 — Document & Page Profiler
- PART 7 — Model / Parser / Provider Registry
- PART 8 — Adaptive Economic Router
- PART 9 — Execution Scheduler & RunPod Commit Protocol
- PART 10 — Inspector, Recovery & Document Reconciliation
- PART 11 — Canonical Knowledge IR & Trusted Knowledge
- PART 12 — Semantic Diff, Dependency, Impact & World State
- PART 13 — Retrieval, Ask & Agent Consumption
- PART 14 — Public API, CLI, SDK, Webhooks & MCP
- PART 15 — Product Experience & Cinematic Website
- PART 16 — Benchmark OS & Evidence Architecture
- PART 17 — Security, Privacy & Enterprise Hardening
- PART 18 — Observability, SRE & FinOps
- PART 19 — IP, Claims, Marketing & GTM
- PART 20 — Current Repository → V4 Migration Matrix
- PART 21 — V4 Dependency-Aware Implementation Phases
- PART 22 — Solo-Founder Critical Path
- PART 23 — FMEA / Potential Technical Issues & Remediation Register
- PART 24 — Repository Architecture, CI & Release Engineering
- PART 25 — AI-Native Solo-Founder Software Factory
- PART 26 — Test Catalog
- PART 27 — Operations Runbook Index
- PART 28 — Final Product & Website Copy Contract
- PART 29 — Final Definition of Done
- PART 30 — Launch Gates
- PART 31 — Final Autonomous Claude Code Command v4.0
- APPENDIX A–E

---

# 이 문서를 사용하는 법

이 문서는 아이디어 모음이나 장기 비전 문서가 아니다.

이 파일 하나를 repository root 또는 `docs/north-star/`에 두고 Claude Code가 현재 repository를 검사한 뒤, 검증된 기존 코어를 보존하면서 TAVONEL v4를 단계적으로 구현·검수·배포·마케팅할 수 있도록 만든 **실행 계약**이다.

## 충돌 시 우선순위

1. 본 문서의 `FINAL EXECUTION BOUNDARY`, `FINAL DEFINITION OF DONE`, `V4 PHASE GATES`
2. 본 문서의 normative architecture / security / evidence / migration 규칙
3. 검증된 repository evidence, artifact hash, benchmark receipt
4. `v31-phase-gap-matrix.md`가 기록한 실제 현재 구현 상태
5. v3.1 Production Masterplan 중 본 문서와 충돌하지 않는 상세 구현 자산
6. v2/v1 및 과거 설계 문서
7. legacy drafts

## 절대 보존 규칙

- 기존 FOLYNTA benchmark artifact 이름, hash, evaluator revision, receipt를 TAVONEL로 임의 rename하거나 다시 쓰지 않는다.
- `99.98%` completion을 accuracy라고 부르지 않는다.
- `99.94%` recovery는 `1,796 / 1,797 recovery-required documents`라는 denominator를 항상 동반한다.
- low-quality scan `36.9%` 약점을 숨기지 않는다.
- blind quality detection이 실패했다는 negative result를 삭제하지 않는다.
- 현재 검증된 Recovery, Reconciler, stable identity, semantic diff, dependency, recompilation, world-state 구현을 검증 없는 재작성으로 대체하지 않는다.
- “완벽한 구현”은 오류가 절대 없다는 뜻이 아니다. 예상 가능한 실패를 명시적으로 모델링하고, 감지·격리·복구·abstain·rollback·evidence로 다루는 상태를 뜻한다.

## 문서 내 근거 구분

- **[BASELINE]** 첨부 benchmark/gap matrix 및 기존 evidence가 직접 지지하는 내용
- **[OFFICIAL]** 2026-08-10 기준 공식 문서·공식 API·원 논문·공식 repository로 확인한 내용
- **[V4 DECISION]** 위 근거에서 TAVONEL에 맞게 도출한 설계 판단
- **[PREDICTION]** 아직 업계 표준이나 제품 성능으로 확정되지 않은 조건부 방향

---

# PART 0 — EXECUTIVE RESET

## 0.1 TAVONEL의 최종 한 문장

> **TAVONEL compiles fragmented organizational reality into trusted, temporal, traceable world state for AI and agents.**

한국어:

> **TAVONEL은 흩어진 조직의 현실을 AI와 Agent가 신뢰하고 추적하며 지속적으로 최신 상태로 사용할 수 있는 지식 세계로 컴파일한다.**

## 0.2 TAVONEL이 아닌 것

TAVONEL은 다음으로 축소하지 않는다.

- PDF → Markdown converter
- OCR API wrapper
- 단일 multimodal model frontend
- “Upload PDF → Chat” 서비스
- 단순 RAG builder
- 단순 Knowledge Graph builder
- 문서 검색 UI
- 특정 foundation model reseller

최신 GPT, Claude, Gemini 같은 멀티모달 모델이 PDF 한두 개를 매우 잘 읽는다는 사실을 부정하지 않는다. TAVONEL의 존재 이유는 **Document Reading과 Knowledge Operations가 다르기 때문**이다.

```text
Single-document reading
- 몇 개 파일
- 현재 세션
- 일회성 독해/Q&A
- 모델에 전체 파일을 직접 넣어도 충분할 수 있음

Knowledge operations
- 수천~수백만 파일
- 중복·개정·폐기·충돌
- 표·차트·스캔·Office 혼합
- 지속 업데이트
- 권한·보존·삭제
- 출처·시간·적용범위
- 여러 Agent가 소비
- 실패 복구와 재현성
- 변경 영향과 선택적 재컴파일
```

## 0.3 v4가 해결하는 핵심 질문

1. **이 페이지를 어떤 지능에게 맡겨야 신뢰 기준을 가장 적은 비용으로 만족하는가?**
2. **처리 결과가 실패했거나 불확실하다는 사실을 어떻게 알아내는가?**
3. **한 원본이 바뀌면 어떤 Knowledge Unit·검색 인덱스·Agent Context가 stale이 되는가?**
4. **전체를 다시 만들지 않고 영향받은 부분만 어떻게 재컴파일하는가?**
5. **모든 답을 문서·페이지·표·셀·bbox까지 되감을 수 있는가?**
6. **이 AI가 알고 있는 회사는 몇 시 몇 분의 회사인가?**
7. **고객은 긴 설명 없이 사이트에서 이 차이를 어떻게 직접 체험하는가?**

## 0.4 v4의 가장 중요한 전략적 전환

### 기존 질문

> 어떤 OCR/VLM이 최고인가?

### v4 질문

> **이 입력을 요구된 Trust Level로 만드는 최소 기대비용 경로는 무엇인가?**

```text
Best Model
    ↓ 폐기
Minimum Expected Cost
subject to
Trust · Risk · Latency · Permission · Evidence constraints
```

모델은 교체 가능한 worker다. TAVONEL이 직접 소유해야 하는 것은 다음이다.

- Industrial Ingestion
- Document/Page Profiler
- Model & Capability Registry
- Adaptive Economic Router
- Failure Classification
- Recovery Runtime
- Canonical Knowledge IR
- Evidence-level Provenance
- Stable Semantic Identity
- Authority / Applicability / Temporal Resolution
- Semantic Diff / Typed Dependency / Impact
- Incremental Recompilation
- Versioned World State
- Agent Consumption Lineage
- Document Performance Map
- Router Outcome Dataset
- Evidence / Claims Governance
- Product Experience

## 0.5 Protected Core 선언

현재 gap matrix 기준 다음은 **v4 Protected Core**다.

| 영역 | 현재 상태 | v4 조치 |
|---|---|---|
| `akc_cir.inspection` | Built | **KEEP + EXTEND** |
| `akc_cir.recovery_policy` | Built | **KEEP + CONTROL-PLANE INTEGRATION** |
| `akc_cir.reconciler` | Built | **KEEP + DOCUMENT BENCHMARK** |
| `akc_cir.identity` | Built / N15 conformant | **KEEP; threshold 재보정 전 변경 금지** |
| entity / authority / temporal / injection labels | Partial/Built mix | **ADAPT; review queue 추가** |
| `akc_cir.semantic_diff` | Built | **KEEP + production event 연결** |
| `akc_cir.dependency` | Built | **KEEP + typed impact calibration** |
| `akc_cir.recompilation` | Built | **KEEP + full-build equivalence** |
| `akc_cir.world_state` | Built | **KEEP + atomic publish/rollback** |
| benchmark receipts / claims pack | Proven | **IMMUTABLE** |

현재 코어를 물리적으로 재배치하는 것은 필수가 아니다. logical boundary와 contract가 우선이다.

## 0.6 새로 만드는 v4 Control Plane

```text
SOURCES
Web · CLI · API · Drive · GCS · S3/R2 · SharePoint/OneDrive
        ↓
INDUSTRIAL INGESTION
Multipart · Resume · Preflight · Quarantine · Manifest · ACL
        ↓
INTELLIGENCE CONTROL PLANE
Profile · Registry · Plan · Schedule · Route · Budget
        ↓
ADAPTIVE EXECUTION
Native · MinerU · Operational Retry · Specialist · Multimodal · Frontier
        ↓
PROTECTED COMPILER CORE
Inspect · Recover · Reconcile · IR · Provenance · Identity
        ↓
TRUSTED KNOWLEDGE
Entity · Authority · Applicability · Bi-temporal · Epistemic
        ↓
CHANGE INTELLIGENCE
Semantic Diff · Dependency · Impact · Selective Recompile
        ↓
VERSIONED WORLD STATE
Atomic Publish · Rollback · Freshness SLO
        ↓
CONSUMPTION
Ask · Retrieval · API · SDK · MCP · Agents · Exports
```

## 0.7 핵심 외부 약속과 내부 비밀

### 외부에 보여줄 것

- 왜 모든 페이지를 같은 모델로 처리하지 않는가
- 실패가 조용히 지식이 되지 않는다는 것
- 답이 원문까지 추적된다는 것
- 원본 변경 시 영향받은 부분만 갱신된다는 것
- benchmark와 한계
- high-level architecture와 실제 제품 동작

### 영업비밀로 유지할 것

- Profiler의 전체 feature vector
- model selection weight/threshold
- escalation policy의 세부 규칙
- verifier prompt / calibration prompt
- 모델별 private cost-performance matrix
- Router Outcome Dataset
- failure heuristic의 조합
- stable identity 내부 scoring recipe
- dependency propagation scoring/cutoff
- customer-specific tuning

## 0.8 범위 통제

초기 paid pilot 전에 만들지 않을 것:

- 자체 OCR foundation model
- 자체 general-purpose LLM
- Kubernetes/Kafka 도입
- Neo4j hard dependency
- 모든 connector 동시 구현
- write-capable MCP
- autonomous Agent actions
- full decision simulation
- SOC 2/ISO 인증 획득 자체
- 모든 산업 vertical

측정된 병목이나 유료 수요 없이 범위를 확장하지 않는다.

---

# PART 1 — VERIFIED BASELINE & CURRENT GAP

## 1.1 공개 benchmark baseline

[BASELINE] 2026-08-09 campaign은 세 public suite의 5,132개 문서를 pinned official evaluator로 측정했다.

| Suite | 문서 수 | Evaluator revision |
|---|---:|---|
| ParseBench | 2,078 | `1d460294` |
| OmniDocBench | 1,651 | `193627ae` |
| olmOCR-Bench | 1,403 | `cfa88c1e` |
| **합계** | **5,132** | — |

Pipeline:

```text
MinerU 3.4.4 VLM engine
+
FOLYNTA/TAVONEL Recovery Runtime
```

## 1.2 현재 증명된 Quality Vector

| Dimension | 결과 | 외부 표현 조건 |
|---|---:|---|
| Output completion | 5,131 / 5,132 = 99.98% | accuracy라고 부르지 않음 |
| Recovery-required documents | 1,797 | denominator 명시 |
| Recovered | 1,796 / 1,797 = 99.94% | corpus completion과 혼동 금지 |
| olmOCR check pass rate | 80.6% | 7,137 / 8,413, CI 동반 |
| Text character match | 94.2% | OmniDocBench metric |
| Reading order match | 85.9% | OmniDocBench metric |
| Table structure | 95.5% | TEDS structure-only |
| Table full | 92.6% | TEDS |
| Reproducibility | 384 / 384 byte-identical x3 | audit sample임을 명시 |
| Broken internal links in emitted vault | 0 | 1,000-doc structural test |
| Silent file loss | 0 | 5 merge policies test |

## 1.3 문서 분포가 성능을 바꾼다는 증거

| 문서 유형 | olmOCR accuracy |
|---|---:|
| Standard digital | 99.0% |
| Headers/footers | 95.0% |
| Table-heavy | 88.5% |
| Academic + equations | 85.6% |
| Multi-column | 81.2% |
| Long/small type | 79.4% |
| Old scans + equations | 79.3% |
| Low-quality scans | **36.9%** |

[V4 DECISION] 따라서 TAVONEL은 단일 “정확도”를 제품 성능으로 사용하지 않는다. 성능은 다음 함수다.

```text
Performance = f(
  document distribution,
  page characteristics,
  task,
  model/version,
  route,
  recovery,
  evaluator,
  risk definition
)
```

## 1.4 Recovery의 증명된 가치

동일 model / corpus / evaluator / settings에서 recovery content만 제거한 ablation:

| | Recovery ON | Recovery OFF |
|---|---:|---:|
| olmOCR overall | 80.6 | 53.7 |
| Rule failures | 1,276 | 3,818 |
| ParseBench table GriTS | 0.9017 | 0.5321 |
| ParseBench content faithfulness | 0.8376 | 0.5243 |
| Omni text edit distance | 0.0583 | 0.2640 |
| Omni table TEDS | 0.9257 | 0.7140 |

[V4 DECISION] Recovery는 parser 뒤의 보조 기능이 아니라 **Execution Control Plane의 핵심**으로 승격한다.

## 1.5 운영 실패가 비용을 지배할 수 있다는 증거

| 구분 | GPU raw cost / 1,000 pages |
|---|---:|
| Healthy worker | $1.23 |
| Whole campaign | $5.92 |

- Healthy worker throughput: 600 pages/pod-hour
- Campaign GPU class: RTX 4090 @ $0.74/hour
- 전체 campaign 비용은 engineering/storage/egress/support/margin을 포함하지 않는다.

[V4 DECISION] 비용 최적화는 모델 단가뿐 아니라 timeout, worker loss, retry, cold start, idle GPU, provider-wide failure를 포함해야 한다.

## 1.6 재시도 설계에 주는 증거

Targeted retry 368개 중 315개가 byte-identical이었다. 같은 모델·같은 설정을 semantic failure에 무작정 재시도하는 것은 대개 새 정보를 만들지 못할 수 있다.

반면 이전에 출력하지 못한 3개는 충분한 wall-clock을 가진 동일 MinerU worker에서 모두 완료됐고, 2개는 alternate model보다 18–27배 많은 content를 만들었다.

[V4 DECISION]

```text
Operational Failure
→ same-model retry / fresh worker / more wall-clock / rerender

Semantic or model-family Failure
→ alternate family / multimodal / verifier
```

## 1.7 Negative result를 제품 설계에 반영

5,116 cases / 42,506 official failures에서 blind ranking은 random이나 length-only를 이기지 못했다.

따라서 다음을 금지한다.

```text
single_quality_score < threshold
→ expensive_model
```

Profiler는 관측 가능한 feature를 기록하는 센서이며, Inspector는 명시적 failure evidence를 생성한다. 둘을 근거 없이 하나의 “AI-ready score”로 합치지 않는다.

## 1.8 현재 repository gap의 v4 해석

| 영역 | v3.1 상태 | v4 처리 |
|---|---|---|
| Freeze/legal/supply-chain | Built | KEEP + v4 evidence pin |
| Contracts/test harness | Partial | ADAPT through compatibility contract |
| Secure ingest/preflight/R2 | Not built | BUILD FIRST |
| Profiler/renderer/model registry | Not built | BUILD FIRST |
| Router/execution planner | Partial | LEGACY KEEP + V4 SHADOW REPLACE |
| Parser/RunPod commit | Partial | ADAPT / formalize |
| Inspector/recovery | Built | PROTECTED CORE |
| Reconciler | Built | PROTECTED CORE |
| IR/provenance/identity | Built | PROTECTED CORE + schema adapter |
| Entity/authority/temporal | Partial | ADAPT + review queue |
| Diff/dependency/impact | Built | PROTECTED CORE |
| Recompile/world state | Built | PROTECTED CORE |
| Retrieval/API/MCP | Not built | BUILD after world-state path |
| Health Scan/commercial | Not built | BUILD from real telemetry |
| Product UI/website | Partial | IA/VISUAL REPLACE; infra selectively KEEP |
| Competitive/research | Partial | ADAPT to Benchmark OS |
| Enterprise hardening | Not built | BUILD after pilot path |
| Decision replay/write MCP | Not built | DEFER/GATED |

## 1.9 X1–X16 closure의 v4 배치

| v3.1 gap | v4 module |
|---|---|
| Semantic Model Gateway | Model Registry + Task Gateway |
| Embedding/reranking | Retrieval Contract |
| Structure-aware chunking | Knowledge Packaging Compiler |
| Office dual path | Secure Preflight + Reconciler |
| Dedup/revision graph | Source Identity / Revision Graph |
| Connector change/ACL | Connector Control Plane |
| Multi-tenant GPU scheduler | Execution Scheduler / FinOps |
| E2E answer/citation eval | Benchmark OS |
| Blueprint compiler/exports | Deterministic Target Compiler |
| API/stream/webhooks/SDK | Public Platform Surface |
| Credits/billing | Internal Usage Ledger + Billing Adapter |
| Human review/active learning | Review Queue + Outcome Feedback |
| Zero-downtime release | Compatibility/Canary/Pointer Swap |
| Competitive checklist | Same-condition Comparator Harness |
| GTM | Evidence Funnel + Health Scan |
| Solo-founder path | AI-Native Software Factory |

---

# PART 2 — V4 REFERENCE ARCHITECTURE

## 2.1 Architecture principles

1. **R2 is immutable artifact truth.**
2. **PostgreSQL is workflow, permission, identity and publish truth.**
3. **World state is versioned and atomically activated.**
4. **Cloudflare Queues delivery is at-least-once; every consumer is idempotent.**
5. **GPU worker success is acknowledged only after output and receipt are durable.**
6. **Untrusted documents never control tools, credentials, routing policy or authorization.**
7. **Retrieval permission/time/authority filters precede similarity ranking.**
8. **Model capabilities are registry facts with evidence, not assumptions.**
9. **Public product events are sanitized projections of internal receipts.**
10. **Every production claim is generated from an approved claim receipt.**

## 2.2 Logical service map

```text
apps/
├─ web                    Landing + App + Evidence + Research + Security
├─ api                    Public/API gateway, SSE, webhooks, auth
└─ worker-control         queue producers/consumers and orchestration

services/
├─ ingest                 upload session, connector sync, preflight
├─ source-identity        hash/dedup/revision graph
├─ profiler               page/document features + reference render
├─ registry               model/parser/provider/license/cost registry
├─ planner                execution DAG and budgets
├─ router                 deterministic/shadow/canary route decisions
├─ scheduler              tenant fairness, GPU residency, leases
├─ parser-adapters        native/MinerU/Paddle/DeepSeek/provider adapters
├─ inspector              failure evidence
├─ recovery               retry/escalation policy
├─ reconciler             document-level structure
├─ compiler               Canonical Knowledge IR
├─ identity               stable semantic identity
├─ knowledge-integrity    entity/authority/applicability/temporal/epistemic
├─ lineage                evidence/transformation/consumption lineage
├─ diff                   semantic changes
├─ dependency             typed graph
├─ impact                 affected-set computation
├─ recompilation          dirty-set and incremental build
├─ world-state            validate/publish/rollback
├─ retrieval              permission-first search/rerank
├─ answer                 grounded Ask output
├─ health-scan            findings from real telemetry
├─ review                 human review queue
├─ billing                usage ledger and invoice adapter
└─ evidence               benchmark/claim receipts
```

독립 microservice로 반드시 배포하라는 뜻은 아니다. 1인 개발 단계에서는 **modular monolith + queue workers**가 기본이다. 측정된 scaling/failure isolation 요구가 생길 때만 물리적으로 분리한다.

## 2.3 Data plane vs control plane

### Data plane

- source bytes
- rendered page images
- parser outputs
- IR artifacts
- compiled exports
- embeddings
- world-state snapshots

### Control plane

- upload/session state
- source manifest
- profile features
- model registry
- route policy/version
- execution plan/attempt
- inspection finding
- recovery decision
- review decision
- publish pointer
- usage/cost receipt
- claim state

Control plane 데이터가 유실되면 “무엇이 왜 만들어졌는지”를 재현할 수 없으므로 source bytes만큼 중요하다.

## 2.4 Persistence boundaries

### Cloudflare R2

- source immutable bytes
- quarantine objects
- normalized/rendered artifacts
- parser raw outputs
- reconciled document artifacts
- IR snapshots
- export bundles
- benchmark artifacts
- signed receipts
- optional cold backup packages

### Managed PostgreSQL

- tenants/workspaces/users/principals
- upload sessions/manifests
- source/document/version identities
- event inbox/outbox
- execution plans/attempts/leases
- profiles/model registry/policies
- findings/recovery/review
- semantic units/entities/claims/relations
- temporal/authority/applicability
- dependency/impact/world-state metadata
- permissions/audit/billing/claims

### pgvector

PostgreSQL extension으로 시작한다. 별도 vector database는 filtered recall, scale, cost에서 측정된 병목이 확인될 때만 검토한다.

### Optional cache

Redis/Durable Objects는 correctness truth로 사용하지 않는다. rate limiting, short-lived locks, progress projection처럼 유실 가능 cache에만 사용한다. 초기에는 PostgreSQL advisory lock/lease와 Cloudflare primitives로 충분한지 측정한다.

## 2.5 Event delivery model

Cloudflare Queues를 exactly-once로 가정하지 않는다.

```text
event produced
→ outbox row committed with domain transaction
→ relay publishes to queue
→ consumer inserts inbox(event_id)
→ duplicate event is acknowledged without repeating side effect
→ side effect writes idempotency receipt
```

### Canonical event envelope

```json
{
  "event_id": "evt_01...",
  "event_type": "document.profiled.v1",
  "occurred_at": "2026-08-10T12:34:56.000Z",
  "producer": "profiler@4.0.0",
  "tenant_id": "ten_...",
  "workspace_id": "ws_...",
  "subject_type": "document_version",
  "subject_id": "dv_...",
  "correlation_id": "corr_...",
  "causation_id": "evt_...",
  "schema_version": 1,
  "traceparent": "00-...",
  "payload_ref": "r2://.../events/evt_....json",
  "payload_sha256": "...",
  "visibility": "INTERNAL"
}
```

Queue message에는 128KB 한계와 민감정보 노출을 고려해 큰 payload 대신 R2/DB reference를 사용한다.

## 2.6 State machines

### Source state

```text
CREATED
→ UPLOADING
→ UPLOADED
→ QUARANTINED
→ PREFLIGHTING
→ ADMITTED | REJECTED | NEEDS_PASSWORD
→ VERSIONED
→ PROCESSING
→ COMPILED
→ ACTIVE | SUPERSEDED | DELETED
```

### Document processing state

```text
PENDING
→ PROFILED
→ PLANNED
→ EXECUTING
→ INSPECTING
→ ACCEPTED
   | RECOVERY_PLANNED
   | REVIEW_REQUIRED
   | FAILED_CLOSED
→ RECONCILED
→ IR_COMPILED
→ VALIDATED
→ STAGED
→ PUBLISHED
```

### Attempt state

```text
QUEUED
→ LEASED
→ STARTED
→ HEARTBEATING
→ OUTPUT_UPLOADED
→ RECEIPT_COMMITTED
→ ACKED

terminal alternatives:
TIMED_OUT | OOM | WORKER_LOST | PROVIDER_STOP | INVALID_OUTPUT | CANCELLED
```

### World state

```text
BUILDING
→ VALIDATING
→ ACTIVE
or
→ REJECTED

ACTIVE → SUPERSEDED
ACTIVE/SUPERSEDED → ROLLED_BACK_TO
```

## 2.7 Trust tiers

| Tier | 의미 | 허용 동작 |
|---|---|---|
| T0 RAW | 원본만 보존 | Agent 소비 금지 |
| T1 PARSED | text/layout output 존재 | 내부 검수만 |
| T2 STRUCTURED | document structure reconciled | 제한적 search 후보 |
| T3 EVIDENCED | source span/bbox/cell 연결 | grounded retrieval 후보 |
| T4 RESOLVED | authority/time/applicability/permission 통과 | Ask/API 사용 가능 |
| T5 VERIFIED | high-risk independent verification/review 통과 | critical workflow 후보 |

파일이 출력됐다고 `SUCCESS`가 아니다. 제품 UI와 API는 정확한 tier와 warning을 노출한다.

---

# PART 3 — CANONICAL CONTRACTS & DATABASE DESIGN

## 3.1 Identifier policy

- 외부 노출 ID: ULID/UUIDv7 기반 opaque identifier
- 내부 content identity: canonical bytes/hash + domain-specific stable ID
- 모든 ID 생성기는 tenant/workspace context를 명시적으로 받는다.
- filename/path를 identity로 사용하지 않는다.
- source bytes hash와 semantic identity를 분리한다.

대표 ID:

```text
ten_ workspace principal upload source source_version
file document document_version page artifact
profile model provider policy plan attempt finding
recovery review evidence unit unit_version entity claim relation
change dependency impact build world_state consumption receipt
```

## 3.2 Core tables — 최소 schema

```sql
create table tenants (
  id uuid primary key,
  name text not null,
  status text not null,
  created_at timestamptz not null default now()
);

create table workspaces (
  id uuid primary key,
  tenant_id uuid not null references tenants(id),
  name text not null,
  data_region text not null,
  retention_policy_id uuid,
  active_world_state_id uuid,
  created_at timestamptz not null default now(),
  unique (tenant_id, name)
);

create table source_versions (
  id uuid primary key,
  tenant_id uuid not null,
  workspace_id uuid not null,
  source_id uuid not null,
  content_sha256 text not null,
  byte_size bigint not null,
  mime_detected text not null,
  object_key text not null,
  source_state text not null,
  connector_revision text,
  acl_snapshot_id uuid,
  created_at timestamptz not null,
  deleted_at timestamptz,
  unique (tenant_id, workspace_id, content_sha256, object_key)
);

create table execution_attempts (
  id uuid primary key,
  tenant_id uuid not null,
  workspace_id uuid not null,
  plan_id uuid not null,
  input_artifact_id uuid not null,
  model_registry_id uuid not null,
  adapter_version text not null,
  attempt_no int not null,
  status text not null,
  lease_owner text,
  lease_expires_at timestamptz,
  started_at timestamptz,
  ended_at timestamptz,
  output_artifact_id uuid,
  error_class text,
  cost_receipt_id uuid,
  idempotency_key text not null unique
);
```

실제 migration에서는 enum을 PostgreSQL enum으로 잠그기보다 versioned lookup/check constraints 또는 domain type을 우선 검토한다. enum 추가가 무중단 배포를 방해하지 않도록 expand-contract를 사용한다.

## 3.3 Tenant isolation

모든 tenant-owned table에 `tenant_id`를 둔다. 단순 application filter만 믿지 않는다.

```sql
alter table source_versions enable row level security;
alter table source_versions force row level security;

create policy source_versions_tenant_policy
on source_versions
using (tenant_id = current_setting('app.tenant_id')::uuid)
with check (tenant_id = current_setting('app.tenant_id')::uuid);
```

필수 검증:

- RLS enabled인데 policy가 없으면 default-deny임을 테스트
- owner/bypassrls role을 request path에서 사용하지 않음
- background job도 tenant context 없이는 읽지 못함
- cross-tenant ID guessing test
- connection pool에서 tenant setting reset test

## 3.4 R2 object key layout

```text
/{environment}/{tenant_id}/{workspace_id}/
  sources/{source_id}/{source_version_id}/original
  quarantine/{upload_id}/...
  renders/{document_version_id}/{renderer_version}/page-{n}.webp
  parser-raw/{attempt_id}/output.json
  parser-raw/{attempt_id}/stdout.log.zst
  reconciled/{document_version_id}/{reconciler_version}.json
  ir/{build_id}/{document_version_id}.json
  evidence/{evidence_id}/region.webp
  world-states/{world_state_id}/manifest.json
  exports/{world_state_id}/{target}/{bundle}
  receipts/{receipt_type}/{receipt_id}.json
  events/{event_id}.json
```

Object key에는 원래 filename이나 민감한 고객명을 넣지 않는다. filename은 encrypted metadata로 관리한다.

## 3.5 Artifact contract

모든 artifact는 최소 다음을 가진다.

```yaml
artifact:
  artifact_id: art_...
  tenant_id: ten_...
  workspace_id: wsp_...
  type: SOURCE | RENDER | PARSER_RAW | RECONCILED | IR | EXPORT | RECEIPT
  object_key: ...
  sha256: ...
  bytes: 12345
  media_type: application/json
  producer:
    service: profiler
    version: 4.0.0
    container_digest: sha256:...
  inputs:
    - artifact_id: art_...
      sha256: ...
  created_at: ...
  retention_class: SOURCE | DERIVED | TEMPORARY | EVIDENCE
  encryption_key_ref: ...
```

## 3.6 Public DTO vs internal receipt

### Public route status

```json
{
  "page": 47,
  "state": "REROUTED",
  "reason_category": "STRUCTURE_UNCERTAIN",
  "started_at": "...",
  "completed_at": null
}
```

### Internal route receipt — 비공개

```json
{
  "route_receipt_id": "rr_...",
  "profile_version": "pf_4.0.0",
  "policy_version": "rp_4.0.0",
  "candidate_scores": [...],
  "feature_contributions": [...],
  "expected_quality_gain": 0.12,
  "expected_incremental_cost_usd": 0.0032,
  "risk_multiplier": 4.0,
  "selected_model": "...",
  "abstention_reasons": [],
  "trade_secret": true
}
```

API serializer와 database view를 분리해 내부 결정 recipe가 accidental API/log/analytics exposure로 새지 않게 한다.

## 3.7 Schema compatibility

- JSON Schema를 canonical contract로 유지
- Pydantic / TypeScript types를 codegen
- producer N과 consumer N/N-1 compatibility test
- unknown field는 보존하거나 명시적으로 reject
- breaking field removal은 최소 2-release deprecation
- event payload는 immutable; correction은 새 event
- historical receipt parser는 영구 보존

## 3.8 Outbox/inbox

```sql
create table event_outbox (
  event_id uuid primary key,
  aggregate_type text not null,
  aggregate_id uuid not null,
  event_type text not null,
  payload jsonb not null,
  created_at timestamptz not null default now(),
  published_at timestamptz,
  publish_attempts int not null default 0
);

create table event_inbox (
  consumer_name text not null,
  event_id uuid not null,
  received_at timestamptz not null default now(),
  processed_at timestamptz,
  result_hash text,
  primary key (consumer_name, event_id)
);
```

## 3.9 Mandatory invariants

1. Source bytes are immutable.
2. Every derived artifact has input lineage.
3. Every published claim has at least one evidence anchor or explicit `UNSUPPORTED` state.
4. No two ACTIVE world states exist per workspace.
5. A permission revoke excludes content before background index cleanup completes.
6. A failed build cannot move ACTIVE pointer.
7. A route decision names policy/model/profile versions.
8. Missing critical identity signals cause abstention, not confident normalization.
9. Stable identity matching is one-to-one unless an explicit split/merge review exists.
10. Every billable unit has one internal usage receipt and at most one invoice export.


---

# PART 4 — INDUSTRIAL INGESTION

## 4.1 목표

대용량 업로드는 UI component가 아니라 독립적인 distributed ingestion subsystem이다.

절대 구조:

```text
Browser → App Server → Entire File → GPU
```

권장 구조:

```text
Browser / CLI / Connector
        ↓
Upload Session API
        ↓
Presigned Multipart Upload
        ↓
Cloudflare R2 quarantine prefix
        ↓
Complete + checksum verification
        ↓
Preflight admission
        ↓
R2 event / Outbox
        ↓
Cloudflare Queue
        ↓
Profiler / Processing
```

웹/API 서버는 multi-GB payload를 중계하지 않는다.

## 4.2 Upload session contract

```yaml
upload_session:
  upload_id: upl_...
  tenant_id: ten_...
  workspace_id: wsp_...
  client_type: WEB | CLI | CONNECTOR | API
  filename_encrypted: ...
  claimed_media_type: ...
  total_bytes: ...
  expected_sha256: optional
  part_size_bytes: ...
  multipart_upload_id: ...
  expires_at: ...
  state: CREATED | UPLOADING | VERIFYING | COMPLETED | ABORTED | EXPIRED
  admitted_parts: 0
  failed_parts: 0
  idempotency_key: ...
```

## 4.3 Part sizing

[OFFICIAL] R2 multipart는 최대 10,000 parts, 5MiB–5GiB part, 최대 5TiB object를 지원한다. v4 기본 정책은 고정값 하나가 아니라 object 크기와 network quality에 따라 조정한다.

권장 bootstrap:

```text
< 100 MiB        single PUT 또는 8–16 MiB parts
100 MiB–5 GiB    32 MiB parts
5–50 GiB         64 MiB parts
> 50 GiB         max(64 MiB, ceil(size / 9500))
```

`9500`은 10,000 limit에 여유를 둔 값이다. 실제 operation cost와 browser memory를 benchmark해 조정한다.

## 4.4 Browser implementation

- File object 전체를 memory에 올리지 않는다.
- Web Worker에서 part checksum을 계산한다.
- UI thread에는 aggregate progress만 전송한다.
- 개별 파일 10,000개 progress를 매 frame React state에 넣지 않는다.
- virtualized detail list를 사용한다.
- 동시 업로드 기본 3–6개, mobile 2개부터 시작하고 RTT/실패율로 조정한다.
- part retry는 exponential backoff + full jitter.
- offline/online event로 resume.
- session metadata는 IndexedDB에 저장하되 credential/presigned secret은 최소화한다.
- browser crash 후 서버의 uploaded-part list와 reconcile한다.

## 4.5 Checksum strategy

- 전송 part checksum
- complete 후 전체 source SHA-256
- connector source가 제공하는 provider hash/etag는 보조 신호일 뿐 canonical SHA-256으로 간주하지 않는다.
- S3 multipart ETag를 content MD5라고 가정하지 않는다.
- hash 계산이 upload TTFF를 과도하게 늦추면 upload와 streaming hash를 병행한다.
- very large file에서는 server-side post-upload hash job을 허용하되 `HASH_PENDING` 동안 processing publish 금지.

## 4.6 Progressive compilation

전체 upload가 끝날 때까지 workspace를 막지 않는다.

```text
File A upload complete → preflight → profile → parse
File B still uploading
File C already compiling
```

UI counters:

```text
Uploading            8,492 / 12,482 files
Preflight complete   7,981
Profiled             6,730
Parsing              1,284
Recovered              219
Knowledge ready      4,506
First answers        AVAILABLE (scope: 4,506 files)
```

부분 answer에는 반드시 processed scope와 world-state completeness를 표시한다.

## 4.7 Time-to-value SLO

- Time to Upload Acknowledgement
- Time to First File Complete
- Time to First Classification
- Time to First Finding
- Time to First Knowledge
- Time to First Answer
- Time to Full Compilation

`전체 처리시간` 하나로 UX를 평가하지 않는다.

Bootstrap target는 claim이 아니라 내부 SLO로 관리한다.

```text
Upload acknowledgement p95       < 500 ms (presign metadata path)
First classification p95         < 15 s after first file complete
First Health finding p95         < 60 s for sample workspace
First knowledge p95              < 120 s for sample workspace
```

실제 region/network/corpus benchmark 후 조정한다.

## 4.8 Preflight and quarantine

모든 upload는 hostile input이다.

### 공통 검사

- extension allowlist와 magic bytes/MIME 비교
- size/page/dimension/archive expansion limit
- encrypted/password-protected detection
- malformed parser probe in sandbox
- file name/path traversal normalization
- null byte/control character
- decompression bomb estimate
- duplicate/canonical hash
- malware scanner/CDR integration hook
- outbound links/macros/external relationships inventory
- prompt-injection/security label scan

### 결과

```text
ADMITTED
REJECTED_UNSUPPORTED
REJECTED_MALICIOUS
REJECTED_LIMIT
NEEDS_PASSWORD
QUARANTINED_REVIEW
```

## 4.9 Format-specific preflight

### PDF

- header/trailer/xref validation
- encryption/password
- page count and page dimensions
- embedded files/JavaScript/actions
- native text ratio
- font/encoding anomalies
- huge image pixels
- reference renderer smoke render
- source-aware blank detection

### DOCX/PPTX/XLSX

- OOXML ZIP central directory safety
- archive expansion ratio
- macro/OLE/external link detection
- relationship target validation
- hidden sheets/slides/rows/columns inventory
- workbook formulas, merged cells, print areas
- native XML path + sandboxed visual render path
- LibreOffice conversion in network-disabled sandbox

### Images

- dimensions/pixel count
- decompression/format parser safety
- EXIF stripping policy
- orientation
- alpha/near-blank
- multi-frame formats

### Archives

- nested depth
- file count
- uncompressed bytes
- path traversal/symlink
- recursive archive policy
- per-tenant quota before expansion

## 4.10 Backpressure and admission control

입력 속도가 processing capacity보다 빠를 수 있다.

필수 정책:

- tenant storage quota
- workspace active-job quota
- maximum unprocessed pages
- maximum estimated GPU budget
- fair-share scheduling
- priority class: INTERACTIVE / STANDARD / BATCH / PILOT
- hard daily spend cap
- queue backlog alert
- capacity reservation only after source admitted

사용자에게 거짓 ETA를 주지 않는다.

```text
First results: likely 2–4 min
Full compilation: current range 22–35 min
Capacity: 8 workers active, 2,341 pages queued
```

## 4.11 Dedup before GPU

단계:

1. exact SHA-256 duplicate
2. normalized package/file duplicate
3. provider revision duplicate
4. near-duplicate candidate
5. revision/branch decision

Exact duplicate는 derived artifact reuse가 가능하지만 permission, source lineage, retention ownership은 각각 유지한다.

## 4.12 Upload failure runbook

| 증상 | 원인 후보 | 탐지 | 해결 |
|---|---|---|---|
| 37%에서 정지 | expired presign, network change | part heartbeat | URL refresh + resume |
| browser freeze | progress render storm/hash main thread | INP/long task | Web Worker + aggregate/virtualize |
| complete 후 object 없음 | multipart complete race | HEAD/checksum | complete idempotency + verify |
| 중복 part 비용 폭증 | retry duplication | part receipt | deterministic part number/idempotency |
| abandoned parts 누적 | browser exit | lifecycle inventory | abort job + R2 lifecycle |
| 잘못된 MIME | client header 신뢰 | magic mismatch | quarantine/reject |
| zip bomb | compressed size만 검사 | expansion estimate | sandbox budget kill |
| GPU가 upload 대기 | pod premature provision | idle span | queue threshold 이후 provision |

---

# PART 5 — CONNECTOR CONTROL PLANE

## 5.1 원칙

> **Small teams upload. Enterprises connect.**

Source ingestion channels:

```text
Small        Web Drag & Drop
Medium       CLI / resumable uploader / watched folder
Enterprise   Google Drive · GCS · S3/R2 · SharePoint/OneDrive
```

## 5.2 Connector state model

```text
CREATED
→ AUTHORIZING
→ INITIAL_CRAWL
→ ACTIVE
→ DEGRADED
→ REAUTH_REQUIRED
→ PAUSED
→ REVOKED
→ DELETED
```

저장:

- provider tenant/account ID
- granted scopes
- cursor/page token/delta link
- webhook/channel/subscription ID
- expiration
- last successful full reconciliation
- last event/cursor
- ACL snapshot version
- rate-limit state
- secret reference, never raw token in application table

## 5.3 Common connector algorithm

```text
Initial crawl
→ immutable source version ingestion
→ ACL snapshot
→ cursor checkpoint
→ subscription/watch registration

Notification arrives
→ verify signature/channel/subscription
→ enqueue lightweight change-check
→ fetch delta from last durable cursor
→ apply source/ACL changes transactionally
→ persist next cursor only after all changes durable
→ semantic diff/recompile async

Periodic reconciliation
→ detect missed/expired notifications
→ compare cursor/state
→ repair drift
```

Notification은 change data 자체가 아니라 “변화가 있음” 신호로 취급한다.

## 5.4 Google Drive

[OFFICIAL]

- Drive `changes` collection과 page token을 사용한다.
- push notification channel은 만료되며 자동 갱신되지 않는다.
- notification 후 API를 다시 호출해 실제 변경을 가져온다.
- Shared Drives를 명시적으로 처리한다.

구현:

- `startPageToken` durable 저장
- `changes.list` pagination 전체 적용 후 newStartPageToken commit
- watch channel renewal scheduler
- duplicate/out-of-order notification idempotency
- trashed/removed 처리
- shortcuts/Google-native Docs export policy
- permissions change는 별도 high-priority path
- export format version과 locale pin

위험:

- channel 만료 → periodic renewal + gap crawl
- permission revoke 지연 → ACL deny overlay를 즉시 publish
- Google Docs export가 바뀜 → raw export + renderer/version receipt
- rate limiting → per-user/project token bucket + backoff

## 5.5 Google Cloud Storage

[OFFICIAL] Pub/Sub notification은 object finalize, metadata update, delete 등의 event를 전달한다. legacy Object Change Notification에 의존하지 않는다.

구현:

- bucket notification/PubSub subscription
- generation/metageneration을 source revision으로 보존
- finalize 전 object 처리 금지
- delete/tombstone
- event duplicate/out-of-order idempotency
- periodic inventory reconciliation
- customer-managed encryption access failure handling

## 5.6 Amazon S3 / S3-compatible

[OFFICIAL] S3 event는 at-least-once이고 지연/중복될 수 있다. ordering은 object key의 `sequencer`를 사용할 수 있는 범위에서만 처리한다.

구현:

- versionId가 있으면 canonical revision key에 포함
- `sequencer` per key 비교
- EventBridge/SQS 또는 customer webhook adapter
- delete marker/versioned bucket
- multipart incomplete object 무시
- inventory periodic reconciliation
- SSE-KMS permission errors 별도 state

R2-compatible source도 동일 adapter contract를 따르되 provider capability를 registry에 기록한다.

## 5.7 Microsoft OneDrive / SharePoint

[OFFICIAL]

- Microsoft Graph `driveItem delta`와 deltaLink를 사용한다.
- change notification lifecycle subscription을 갱신한다.
- deleted facet와 permission change를 처리한다.

구현:

- site/drive/item stable IDs
- deltaLink durable commit
- shared link와 inheritance된 permission snapshot
- permission revoke fast path
- tenant admin consent state
- throttling `Retry-After`
- subscription renewal and lifecycle notification

## 5.8 ACL synchronization invariant

```text
Source permission revoked at t0
→ TAVONEL deny overlay active at t0 + bounded propagation
→ retrieval excludes immediately
→ background index/IR cleanup later
```

권한 revoke가 background reindex를 기다리게 하지 않는다.

## 5.9 Connector security

- least-privilege OAuth scope
- per-connector secret in managed secret store/KMS
- refresh token rotation/revocation
- token audience/issuer validation
- customer-visible authorized scopes
- read-only initial connectors
- connector worker outbound allowlist
- webhook anti-replay
- provider account deletion cleanup

## 5.10 Connector test matrix

- initial crawl interrupted/resumed
- cursor commit crash before/after apply
- duplicate notification
- event gap
- expired channel
- rename/move/copy/branch
- ACL grant/revoke
- delete/restore
- provider rate limit
- token revoked
- item too large/password protected
- connector full resync without duplicate world state

---

# PART 6 — DOCUMENT & PAGE PROFILER

## 6.1 역할

Profiler는 “쉬움/어려움” 결론을 내리는 model이 아니다.

> **Profiler is a versioned sensor.**

관측 가능한 document/page feature와 missing reason을 저장하고 Router/Benchmark가 사용한다.

## 6.2 Feature groups

### Source features

- input format
- byte size/page count
- native text presence/ratio
- scanned/photographed probability
- PDF producer/version
- encryption
- Office structure presence
- language/script distribution

### Visual quality

- render resolution
- blur estimate
- contrast
- skew/rotation
- compression artifacts
- near-blank ratio
- small-font density
- foreground/background entropy

### Layout

- single/multi-column
- reading-order complexity
- text block count/density
- header/footer repetition
- marginalia
- overlapping blocks
- page continuation cues

### Tables

- table probability/density
- grid/borderless
- row/column count estimate
- merged-cell cues
- nested table cues
- cross-page continuation
- numeric density
- footnote linkage

### Formula/code

- equation density
- inline/display formulas
- code block probability
- unusual glyph ratio

### Visual semantics

- figure/chart/diagram density
- caption proximity
- arrows/connectors
- legend/axis labels
- engineering drawing
- screenshot/UI

### Context

- neighboring page type
- section heading path
- document class
- prior parser outcomes for same revision family
- known risk class

## 6.3 Missing features

Missing signal을 0으로 기록하지 않는다.

```yaml
feature:
  name: explicit_clause_id
  value: null
  state: MISSING_NOT_APPLICABLE
  reason: no_clause_identifier_found
```

Critical feature가 없으면 Router는 abstain하거나 conservative path를 선택한다.

## 6.4 Reference rendering

- deterministic renderer/version pin
- default DPI bootstrap 150–200; route-specific higher DPI
- page pixel cap
- color profile normalization
- rotation applied/recorded
- render SHA-256
- native text layer와 image render 모두 보존
- renderer discrepancy test corpus

PDF reference render는 parser output과 독립된 ground observation으로 사용한다.

## 6.5 Office dual path

DOCX/PPTX/XLSX는 어느 한 경로도 단독 truth가 아니다.

```text
Native structure path
OOXML XML · styles · formulas · relationships · notes

Visual path
sandboxed render → pages/slides/sheets

Reconcile
structure ↔ visual position ↔ hidden content ↔ external links
```

- macro 실행 금지
- external URL fetch 금지
- formula calculation은 sandbox policy
- hidden sheet/slides는 visibility state와 함께 보존
- chart underlying data와 rendered chart 연결
- unsupported feature는 warning/visual-only state

## 6.6 Business risk classification

Risk는 model confidence가 아니다.

Bootstrap risk sources:

- workspace policy
- connector/folder classification
- document class
- detected critical field types
- customer-supplied labels

예:

```text
RISK_LOW       marketing draft, internal note
RISK_MEDIUM    manual, support content
RISK_HIGH      contract, policy, pricing, financial filing
RISK_CRITICAL  safety, regulated procedure, payment/permission rule
```

LLM이 독자적으로 risk를 낮추지 못한다. 높이는 signal로만 제한적으로 사용할 수 있다.

## 6.7 Profiler versioning

```text
profile_key = hash(
  source_version_id
  + renderer_version
  + profiler_version
  + feature_schema_version
)
```

Feature definition이 바뀌면 같은 이름으로 과거 값을 덮지 않는다.

## 6.8 Profiler validation

- synthetic fixtures
- public benchmark labels
- DART/SEC stratification labels
- inter-annotator agreement
- feature stability across repeated renders
- correlation is descriptive, not causal claim
- Router usefulness measured by out-of-sample route outcome, not classifier AUROC alone

---

# PART 7 — MODEL / PARSER / PROVIDER REGISTRY

## 7.1 Registry is executable policy data

모델 이름을 source code의 if/else에 박지 않는다.

```yaml
registry_entry:
  registry_id: mdl_...
  canonical_name: mineru-3.4.4
  family: DOCUMENT_VLM
  provider: SELF_HOSTED_RUNPOD
  official_source: ...
  provider_variant: null
  input_modalities: [PDF_PAGE_IMAGE, TEXT_LAYER]
  output_contracts: [BLOCK_JSON, MARKDOWN]
  tasks: [TEXT, TABLE, FORMULA, READING_ORDER]
  license_state: APPROVED | REVIEW | BLOCKED
  license_receipt: ...
  model_revision: ...
  code_revision: ...
  container_digest: sha256:...
  weights_digest: sha256:...
  capability_evidence: [...]
  data_policy:
    retention: ...
    training_use: ...
    region: ...
  resource_profile:
    min_vram_gb: ...
    preferred_gpu: [...]
  price_snapshot:
    effective_at: ...
    unit: GPU_SECOND | INPUT_TOKEN | PAGE
    amount: ...
  status: CHAMPION | CHALLENGER | SHADOW | VERIFIER | DISABLED
```

## 7.2 Capability evidence gate

이름만 보고 multimodal capability를 추정하지 않는다.

중요한 현재 사례:

- [OFFICIAL] `DeepSeek-V4-Flash` 공식 checkpoint/model card는 text-generation model로 공개되어 있다.
- [OFFICIAL] DeepSeek의 공식 multimodal 계열에는 Janus-Pro, document OCR 계열에는 DeepSeek-OCR-2가 별도로 존재한다.
- 따라서 provider가 `V4 Flash Vision` 같은 이름을 제공하면 공식 checkpoint인지 provider-side composite/wrapper인지 분리해야 한다.

Registry 필수 필드:

```text
input_modalities
provider_variant
official_checkpoint
capability_probe_receipt
API schema snapshot
```

Vision input capability receipt가 없으면 image/PDF route candidate가 될 수 없다.

## 7.3 v4 intelligence portfolio

### Tier 0 — Native / cheap

- native PDF text/layout hints
- OOXML structure
- metadata extraction
- simple render/OCR where appropriate

### Tier 1 — Current champion

- MinerU 3.4.4 + proven runtime

### Tier 2 — Operational recovery

- same model, fresh worker
- more wall-clock
- rerender/DPI/deskew/page split
- environment/bootstrap repair

### Tier 3 — Specialists

- PaddleOCR-VL/current approved document VLM
- DeepSeek-OCR-2/current approved document model
- formula/table/chart specialist
- deterministic native parser

### Tier 4 — Cost-effective general multimodal

- officially verified provider models with image/PDF support
- self-hosted or API
- mixed visual semantics, diagram/chart, reconciliation

### Tier 5 — Frontier verifier

- OpenAI/Anthropic/Google/Mistral or future provider
- high-risk disagreement/tail only
- not truth oracle

### Tier 6 — Review/fail closed

- human adjudication
- unresolved/blocked publish

## 7.4 Current official model facts to respect

- Claude PDF support processes text, pictures, charts and tables using vision; request/page/context limits still apply.
- Gemini document understanding processes PDF text/images/diagrams/charts/tables with native vision and has file/API constraints.
- OpenAI Responses API accepts image/file inputs and offers asynchronous Batch at lower cost for non-interactive evaluation workloads.
- Mistral OCR 4 advertises block/bbox/confidence capabilities and commercial page pricing, but must be run on the same corpus/evaluator before comparison.
- PaddleOCR-VL 1.6 official scores cannot be compared directly with TAVONEL’s current olmOCR result unless dataset/evaluator/revision are identical.

## 7.5 Adapter interface

```python
class ParserAdapter(Protocol):
    adapter_id: str
    registry_id: str

    def capability(self) -> Capability: ...
    def estimate(self, request: ParseRequest) -> CostLatencyEstimate: ...
    def prepare(self, request: ParseRequest) -> PreparedJob: ...
    def execute(self, job: PreparedJob) -> RawProviderResult: ...
    def normalize(self, raw: RawProviderResult) -> ParserArtifact: ...
    def healthcheck(self) -> HealthReceipt: ...
```

Adapter는 output을 바로 trusted IR로 publish하지 않는다. raw provider response를 보존하고 normalize/inspect/reconcile을 거친다.

## 7.6 Structured output

- JSON Schema version pin
- provider native structured output가 있더라도 post-validation
- unknown fields recorded
- truncated/invalid JSON recovery separate
- prompt/model/schema key로 cache
- provider refusal/safety output를 parse failure와 구분
- coordinate system normalized but original coordinate retained

## 7.7 Closed API use policy

- customer contract에서 provider use 허용 여부
- region/data retention/ZDR compatibility
- high-risk page only by default
- source crop/necessary pages only
- sensitive content minimization
- provider request/response IDs and cost receipt
- API output never `VERIFIED` solely because provider is frontier
- batch API는 benchmark/offline low-priority lane에 우선

## 7.8 Model lifecycle

```text
DISCOVERED
→ LICENSE_REVIEW
→ CAPABILITY_PROBED
→ BENCHMARKED
→ SHADOW
→ CHALLENGER
→ CANARY
→ CHAMPION
→ DEPRECATED
→ DISABLED
```

Promotion requires:

- same-condition benchmark
- no-regression by document slice
- cost/latency receipt
- catastrophic failure review
- license/security approval
- rollback pointer

## 7.9 Model/container supply chain

- model/code/container revision pin
- SBOM (SPDX/CycloneDX)
- Cosign signature/attestation
- SLSA provenance where practical
- weights hash
- dependency license inventory
- vulnerability scan
- startup health probe
- no unpinned `latest`
- production admission policy rejects BLOCKED/UNKNOWN license state

---

# PART 8 — ADAPTIVE ECONOMIC ROUTER

## 8.1 Objective

```text
Select path π that minimizes:

E[TotalCost(π)]
+ λ_latency · E[Latency(π)]
+ λ_failure · P(UntrustedOutput | π)
+ λ_correlation · CorrelatedFailureRisk(π)

subject to:
TrustProbability(π) ≥ workspace_required_trust
BusinessRiskConstraints satisfied
Provider/DataPolicy constraints satisfied
Budget and deadline constraints satisfied
```

`TrustProbability`는 bootstrap 단계에서 calibrated probability라고 주장하지 않는다. 초기에는 deterministic policy + empirical outcome bins를 사용하고 calibration 상태를 명시한다.

## 8.2 Route decision inputs

- page/document profile
- source/native structure
- document type
- business risk
- previous attempt/failure evidence
- document neighborhood
- model registry capabilities
- model performance map
- latency/cost snapshot
- provider health/circuit state
- tenant data policy
- budget/deadline

## 8.3 금지 입력/설계

- filename만으로 authoritative route
- model self-confidence 하나
- uncalibrated scalar “quality” 하나
- provider marketing benchmark
- unsupported multimodal assumption
- online production exploration without consent
- price snapshot missing model

## 8.4 Route classes

```text
R0_NATIVE_TEXT
R1_STANDARD_DOCUMENT
R2_TABLE_SPECIALIST
R3_FORMULA_ACADEMIC
R4_LOW_QUALITY_SCAN
R5_MIXED_MULTIMODAL
R6_CROSS_PAGE_RECONCILE
R7_OPERATIONAL_RETRY
R8_INDEPENDENT_VERIFIER
R9_HUMAN_FAIL_CLOSED
```

Route class는 model name이 아니다. Policy version에 따라 model mapping이 바뀐다.

## 8.5 Deterministic bootstrap policy

예시이며 calibration 전 public claim 금지:

```text
if operational_failure_detected:
    R7_OPERATIONAL_RETRY
elif native_text_high and layout_simple and risk <= MEDIUM:
    R0_NATIVE_TEXT + sample_visual_validation
elif table_density_high or merged_cell_cues:
    R2_TABLE_SPECIALIST
elif formula_density_high:
    R3_FORMULA_ACADEMIC
elif low_quality_scan_features:
    R4_LOW_QUALITY_SCAN
elif chart_or_diagram or parser_visual_semantic_gap:
    R5_MIXED_MULTIMODAL
elif cross_page_continuation:
    R6_CROSS_PAGE_RECONCILE
else:
    R1_STANDARD_DOCUMENT
```

## 8.6 Operational vs cognitive escalation

### Operational evidence

- timeout before model output
- provider-wide simultaneous stop
- OOM
- container/bootstrap missing
- transient network
- lease lost
- output uploaded but ACK missing

Action:

- same model/fresh worker
- longer wall-clock within budget
- corrected environment
- idempotent resume

### Semantic/model evidence

- repeated deterministic malformed table
- missing source region
- numeric conflict
- reading-order violation
- visual relation absent
- independent parser disagreement
- high-risk claim unsupported

Action:

- alternate model family
- specialist/general multimodal
- independent verifier
- review/fail closed

## 8.7 Expected incremental value

```text
IncrementalValue(candidate) =
  P(candidate resolves current failure | slice, evidence)
  × LossAvoided(risk)
  - IncrementalCost
  - LatencyPenalty
  - Privacy/ProviderPenalty
```

Router는 “가장 정확한 모델”이 아니라 현재 failure에 **추가 정보**를 제공할 가능성이 높은 모델을 선택한다.

## 8.8 Correlated failure penalty

같은 architecture/provider/prompt/output path의 모델 여러 개가 동의해도 독립 증거로 계산하지 않는다.

Registry에 family/provider/training lineage가 알려진 범위에서 기록하고, ensemble/verifier selection에 diversity penalty를 둔다.

```text
Consensus weight ≠ model count
Consensus weight = evidence independence × source correspondence
```

## 8.9 Route receipt

모든 decision은 재현 가능해야 한다.

```yaml
route_decision:
  receipt_id: ...
  profile_id: ...
  profile_schema: ...
  policy_id: ...
  registry_snapshot_id: ...
  budget_snapshot_id: ...
  candidates_considered: [...]
  candidates_blocked:
    - model: ...
      reason: LICENSE_BLOCKED | MODALITY_UNPROVEN | DATA_POLICY
  selected_route_class: R4_LOW_QUALITY_SCAN
  selected_model: ...
  reasons: [LOW_CONTRAST, SCANNED, NATIVE_TEXT_ABSENT]
  expected_cost: ...
  expected_latency: ...
  calibration_state: UNCALIBRATED_BOOTSTRAP
```

## 8.10 Shadow migration

Legacy router는 바로 삭제하지 않는다.

```text
Legacy decision → actual production
V4 decision     → shadow receipt only
```

Rollout:

```text
0% shadow only
5% low-risk canary
25% selected slices
50% production with automatic rollback
100% only after exit gate
```

Gate:

- catastrophic recall target met on named corpus
- failure recall and false escalation reported
- cost/trusted output improves or non-inferior
- no high-risk regression
- rollback tested

## 8.11 Learned router — later

Router Outcome Dataset가 충분히 쌓여도 처음부터 reinforcement/online bandit로 가지 않는다.

단계:

1. deterministic rules
2. supervised outcome prediction in shadow
3. off-policy evaluation
4. constrained optimization
5. human-approved policy version
6. canary

Production 사용자에게 자동 exploration을 수행하지 않는다.

## 8.12 Per-tenant policies

```yaml
workspace_policy:
  required_trust: T4
  max_cost_per_1000_pages: ...
  max_frontier_api_fraction: 0.01
  allowed_providers: [...]
  data_regions: [...]
  critical_document_classes: [CONTRACT, SAFETY, PRICING]
  human_review_required_for: [...]
  latency_class: STANDARD
```

---

# PART 9 — EXECUTION SCHEDULER & RUNPOD COMMIT PROTOCOL

## 9.1 Queue topology

```text
ingest-events
profile-jobs
parse-standard
parse-specialist
parse-multimodal
inspect-jobs
recovery-jobs
reconcile-jobs
compile-jobs
world-state-build
review-notifications
webhook-delivery
billing-export
```

초기에는 queue 수를 과도하게 늘리지 않고 priority/route fields로 통합할 수 있다. 다만 GPU residency가 다른 model family는 별도 queue가 cold-start와 batching에 유리할 수 있다.

## 9.2 At-least-once consumer contract

모든 job:

```text
idempotency_key = hash(
  input_artifact_hash
  + task
  + adapter/model revision
  + settings
  + schema version
)
```

동일 key completed receipt가 있으면 재사용한다. `RUNNING` lease가 만료되면 takeover한다.

## 9.3 R2-before-ACK

Worker success protocol:

1. input artifact hash verify
2. inference
3. raw output validate
4. output R2 upload
5. output HEAD/hash verify
6. attempt receipt DB transaction
7. outbox event commit
8. queue ACK

6 이전 worker crash → duplicate retry 가능, side effect safe. 6 이후 ACK crash → inbox/idempotency가 duplicate를 막는다.

## 9.4 Lease / heartbeat

```yaml
lease:
  owner: worker_...
  acquired_at: ...
  expires_at: ...
  heartbeat_interval_s: 15
  progress:
    pages_done: 34
    last_artifact_sha: ...
```

- provider network address가 restart 후 바뀔 수 있음을 고려
- probe 실패를 idle 증거로 사용하지 않음
- hard deadline 이전에 grace + output activity 확인
- worker-wide simultaneous stop은 account/provider failure로 분류

## 9.5 RunPod operating choices

[OFFICIAL]

- Serverless min workers 0이면 cold start가 존재한다.
- queue-based endpoint는 async/batch/retry에 적합하고 load-balanced endpoint는 성격이 다르다.
- network volume은 `/runpod-volume`에 mount되며 concurrent write safety를 애플리케이션이 보장해야 한다.
- container disk는 ephemeral할 수 있으므로 model/bootstrap을 image 또는 network volume에 둔다.
- balance 0/limit 상황이 provider-wide stop을 유발할 수 있으므로 billing alert와 circuit breaker가 필요하다.

## 9.6 GPU residency scheduler

목표:

- model load amortization
- tenant fairness
- OOM avoidance
- tail latency
- no idle burn

Scheduler input:

- model residency
- GPU memory requirement
- batch compatibility
- queue age
- tenant priority/share
- deadline
- estimated duration
- current spend

Simple bootstrap:

```text
weighted_fair_score =
  age_weight * queue_age
+ priority_weight * class
+ starvation_weight * tenant_wait
- load_penalty * model_cold_start
- cost_penalty * gpu_rate
```

## 9.7 Batching

Batch only when:

- same model/settings/input shape compatible
- deadline allows batch window
- per-item idempotency remains
- one bad input cannot poison entire batch without isolation

Interactive Health Scan은 작은 batch window, full corpus batch는 큰 window.

## 9.8 GPU selection

시간당 가격이 아니라 다음으로 benchmark한다.

```text
$/1,000 successful pages
$/recovered page
p95 latency/successful page
OOM rate
cold-start amortized cost
```

저렴한 GPU가 4배 느리면 더 비쌀 수 있다. 모델별 reference workload로 GPU matrix를 유지한다.

## 9.9 Provider circuit breakers

- model endpoint error rate
- provider-wide simultaneous stop
- cold-start p99
- cost anomaly
- output schema failure
- queue age

Circuit states:

```text
CLOSED → OPEN → HALF_OPEN → CLOSED
```

OPEN 시 alternate provider/model 또는 capacity admission control. 무한 retry 금지.

## 9.10 Retry budget

```yaml
retry_budget:
  operational_same_model: 1
  render_variant: 2
  alternate_family: 2
  frontier_verifier: 1
  total_cost_cap_usd: ...
  deadline: ...
```

Budget 소진 시 review/fail closed.

## 9.11 RunPod failure runbook

| Failure | 판별 | 대응 |
|---|---|---|
| Worker timeout | heartbeat/last output | same-model resume or larger wall-clock |
| OOM | stderr/metric | smaller batch, lower resolution, larger GPU |
| Container missing CLI | startup probe | immutable image/bootstrap gate |
| Pod killed by watchdog | provider state + active work | stop logic fix, lease-aware probe |
| All workers stop simultaneously | correlated timestamp | account/provider circuit; provisioning 중단 |
| Network volume write corruption | concurrent writer | content-addressed immutable paths + single-writer manifests |
| Cold-start tail | min worker/load span | selective warm pool or batch scheduling |
| Cost leak | pod active/no work | idle timeout + external reconciler |
| Output exists but job failed | R2/DB discrepancy | commit repair reconciler |


---

# PART 10 — INSPECTOR, RECOVERY & DOCUMENT RECONCILIATION

## 10.1 기존 구현 보존

`akc_cir.inspection`, `akc_cir.recovery_policy`, `akc_cir.reconciler`는 현재 Built 자산이다. v4는 이를 삭제하지 않고 다음 contract에 연결한다.

```text
Execution Attempt
→ Inspector Findings
→ Failure Classification
→ Recovery Policy
→ New Attempt / Reconcile / Review / Fail Closed
```

## 10.2 Inspector의 역할

Inspector는 universal truth detector가 아니다.

- source-aware invariant
- parser/output contract
- deterministic structural check
- evidence correspondence
- cross-output disagreement
- known failure signature

를 기반으로 **finding**을 만든다.

## 10.3 Failure taxonomy

### Infrastructure / operational

- WORKER_TIMEOUT
- WORKER_LOST
- PROVIDER_STOP
- OOM
- BOOTSTRAP_MISSING
- NETWORK_ERROR
- OUTPUT_COMMIT_INCOMPLETE

### Source/render

- SOURCE_CORRUPT
- SOURCE_ENCRYPTED
- BLANK_SOURCE
- RENDER_FAILURE
- LOW_RESOLUTION
- ROTATION_SKEW
- ARCHIVE_BOMB

### Extraction

- EMPTY_OUTPUT_NONBLANK_SOURCE
- TEXT_REGION_MISSING
- DUPLICATED_CONTENT
- READING_ORDER_INVALID
- TABLE_STRUCTURE_INVALID
- TABLE_CELL_MISALIGNMENT
- NUMERIC_CONFLICT
- FORMULA_INVALID
- CAPTION_ASSOCIATION_MISSING
- FIGURE_SEMANTIC_MISSING
- CROSS_PAGE_CONTINUATION_UNRESOLVED

### Knowledge integrity

- ENTITY_AMBIGUOUS
- AUTHORITY_CONFLICT
- APPLICABILITY_CONFLICT
- EFFECTIVE_DATE_UNKNOWN
- PROVENANCE_BROKEN
- PERMISSION_CONFLICT
- PROMPT_INJECTION_SUSPECTED

## 10.4 Source-aware blank handling

Empty output만 보고 failure로 간주하지 않는다.

```text
source near-blank + no meaningful native text
→ BLANK_SOURCE / correct empty possible

source contains nonblank regions + empty output
→ EMPTY_OUTPUT_NONBLANK_SOURCE / catastrophic
```

Reference render, pixel statistics, native text, object inventory를 함께 사용한다.

## 10.5 Deterministic checks

- page count preservation
- expected region coverage
- table row/column consistency
- duplicate block overlap
- numeric token preservation candidates
- heading hierarchy validity
- list numbering continuity
- bbox within page bounds
- evidence anchor refers to existing artifact
- markdown links resolve
- source/derived hash integrity

## 10.6 Numeric protection

DART/SEC/contract/pricing 문서는 text similarity와 별도로 critical tokens를 검사한다.

- amount
- percent
- date
- quantity
- currency
- unit
- decimal/comma
- sign/parentheses
- range

Parser A/B가 숫자에서 충돌하면 전체 paragraph confidence 평균으로 숨기지 않는다. `NUMERIC_CONFLICT`로 승격한다.

## 10.7 Consensus is not truth

두 parser가 동의해도 source correspondence가 없으면 verified가 아니다.

```text
Agreement
+ independent failure mode
+ source region correspondence
+ structural invariant
→ stronger evidence
```

같은 model family/prompt/provider 결과는 independence weight를 낮춘다.

## 10.8 Recovery ladder

```text
L0 ACCEPT
L1 RERENDER / DESKEW / RESOLUTION / SPLIT
L2 SAME-MODEL OPERATIONAL RETRY
L3 SPECIALIST ALTERNATE FAMILY
L4 MULTI-PARSER RECONCILIATION
L5 GENERAL MULTIMODAL / FRONTIER VERIFIER
L6 ADJACENT-PAGE / DOCUMENT-LEVEL RECONCILIATION
L7 HUMAN REVIEW
L8 FAIL CLOSED
```

각 단계는 trigger, budget, evidence requirement, terminal status를 가진다.

## 10.9 Recovery policy example

```yaml
policy:
  finding: TABLE_CELL_MISALIGNMENT
  source_class: FINANCIAL_FILING
  risk: HIGH
  actions:
    - rerender: {dpi: 240}
    - alternate_route: R2_TABLE_SPECIALIST
    - reconcile: {require_cell_evidence: true}
    - if_numeric_conflict: R8_INDEPENDENT_VERIFIER
  max_cost_usd: ...
  terminal_if_unresolved: REVIEW_REQUIRED
```

## 10.10 Document Reconciler

Page-level best output를 단순 concatenate하지 않는다.

Reconcile 대상:

- paragraph continuation
- list continuation
- heading hierarchy
- cross-page table
- repeated table header
- figure/caption
- footnote/source element
- section boundary
- split formula/code

### Cross-page table algorithm

1. adjacent page candidate detection
2. header similarity/column geometry
3. continuation markers and row semantics
4. deterministic merge proposal
5. provenance per cell 유지
6. ambiguous case는 `CONTINUATION_CANDIDATE`, 자동 merge 금지

## 10.11 Human review queue

사람이 모든 문서를 보는 제품이 되지 않는다. Review는 작은 high-value fraction에 집중한다.

Review types:

- parser disagreement high-risk
- numeric conflict
- entity merge/split
- authority/applicability conflict
- unknown effective date
- cross-page uncertain merge
- permission mismatch
- source injection/security

Review decision도 provenance다.

```yaml
review_decision:
  review_id: rev_...
  object_type: CLAIM | UNIT | ENTITY | RELATION | DOCUMENT
  object_id: ...
  decision: ACCEPT | REJECT | MERGE | SPLIT | OVERRIDE | UNRESOLVED
  reviewer_id: ...
  evidence_ids: [...]
  reason_code: ...
  note: ...
  decided_at: ...
  policy_version: ...
```

## 10.12 Recovery KPIs

- recovery-required denominator
- recovered / unrecovered
- recovery rounds
- incremental quality gain
- cost/recovered page
- p95 recovery latency
- false recovery/quality regression
- same-model retry yield
- alternate-family yield
- human review fraction
- failure class confusion

---

# PART 11 — CANONICAL KNOWLEDGE IR & TRUSTED KNOWLEDGE

## 11.1 v4 migration rule

현재 IR/identity 구현을 adapter 뒤에서 보존한다.

```text
V4 Execution Artifact
→ V4 Compatibility Adapter
→ Current CIR Core
→ V4 envelope/lineage additions
```

Top-level schema 전환은 expand → dual write → backfill → compare → pointer swap → contract 순으로 진행한다.

## 11.2 Canonical Knowledge IR v4 envelope

```yaml
knowledge_unit_version:
  unit_version_id: kuv_...
  stable_unit_id: ku_...
  tenant_id: ...
  workspace_id: ...
  world_state_build_id: ...
  type: HEADING | PARAGRAPH | CLAUSE | PROCEDURE | TABLE | ROW | CELL | FIGURE | CLAIM
  content:
    canonical_text: ...
    structured_value: optional
    language: ko
  structure:
    parent_id: ...
    order_key: ...
    heading_path: [...]
    associations: [...]
  evidence_refs: [...]
  entity_refs: [...]
  relation_refs: [...]
  authority:
    source_class: ...
    issuer: ...
    status: DRAFT | ACTIVE | SUPERSEDED | UNKNOWN
  applicability:
    product: ...
    region: ...
    customer: ...
    contract: ...
  temporal:
    valid_from: ...
    valid_to: ...
    recorded_at: ...
    superseded_at: ...
  epistemic:
    state: SUPPORTED | CONFLICTED | AMBIGUOUS | UNSUPPORTED | REVIEWED
    reasons: [...]
  permission_scope_id: ...
  derived_from: [...]
  depends_on: [...]
  compiler:
    schema_version: ...
    compiler_version: ...
    policy_version: ...
```

## 11.3 Evidence-level provenance

모든 published claim은 가능한 최소 source region으로 돌아간다.

```text
Claim
→ Knowledge Unit Version
→ Parser/Reconciler Artifact
→ Source Version
→ Page / slide / sheet
→ bbox / text span / table row-cell / OOXML node
```

Evidence fields:

- source version ID
- page/sheet/slide
- original coordinate system
- normalized bbox
- text span offsets
- table ID/row/column/cell span
- image crop artifact
- parser attempt and model version
- transformation steps
- source SHA-256

좌표를 추론해 만들어내지 않는다. 좌표가 없으면 `COORDINATE_UNAVAILABLE`로 기록한다.

## 11.4 Stable semantic identity

현재 구현의 보수적 원칙을 유지한다.

- false merge는 역사를 오염시키므로 false split보다 비싸다.
- merge threshold 0.92 / new identity floor 0.75는 현재 uncalibrated bootstrap이며 corpus calibration 전 public claim 금지.
- missing signals는 zero가 아니라 renormalized/abstain.
- one-to-one assignment.
- split/merge reversible provenance.

Signals 예:

- explicit identifier
- normalized heading path
- semantic content similarity
- structural neighborhood
- evidence location continuity
- entity/relation overlap
- revision graph context

## 11.5 Document identity / dedup / revision graph

구분해야 하는 것:

- same bytes duplicate
- same content renamed/moved
- derived export
- revision
- parallel branch
- copy with independent history
- merged document

Graph:

```text
SOURCE_A_v1
 ├─ RENAMED_TO → SOURCE_A_v1_path2
 ├─ REVISED_TO → SOURCE_A_v2
 └─ BRANCHED_TO → SOURCE_B_v1
```

자동 revision 판정은 high threshold, ambiguous는 review.

## 11.6 Entity resolution

- canonical entity ID와 mention 분리
- aliases/language/name normalization
- external identifiers 우선
- type/context/location/time
- same name ≠ same entity
- different name may be same entity
- conservative merge, reversible split
- customer-specific namespace

## 11.7 Authority resolution

`latest wins` 하나로 해결하지 않는다.

Authority signals:

- source class
- issuer/owner
- signed/approved status
- policy hierarchy
- contract override
- explicit supersession
- effective time
- scope/applicability
- customer-defined resolver DSL

결과:

```text
RESOLVED
CONFLICTED
NO_APPLICABLE_CLAIM
UNKNOWN_AUTHORITY
REVIEW_REQUIRED
```

## 11.8 Applicability

Claim이 맞아도 현재 질문에 적용되지 않을 수 있다.

- region
- legal entity
- customer/account
- product/version
- contract
- channel
- employee role
- valid time

Ask 결과에는 `Why this source`로 applicability reason path를 노출한다.

## 11.9 Bi-temporal knowledge

- `valid_time`: 현실에서 언제 사실인가
- `system/known_time`: 시스템은 언제 알았는가

Query:

```text
as_of = 2026-07-01
known_at = 2026-07-15
```

두 시간을 혼합하지 않는다. unknown date를 fabricate하지 않는다.

## 11.10 Epistemic state

확률 숫자 하나 대신 state + reason.

```text
SUPPORTED
SUPPORTED_WITH_WARNINGS
CONFLICTED
AMBIGUOUS
INSUFFICIENT_EVIDENCE
UNSUPPORTED
REVIEWED
```

## 11.11 Prompt injection / untrusted instructions

문서 안의 “이전 지시를 무시하라”, 외부 URL, hidden text는 data다.

- parser/semantic extraction model에 tool 권한 없음
- outbound network 없음
- system policy와 document text 분리
- indirect prompt injection label
- retrieved content가 authorization/policy를 변경하지 못함
- tool arguments는 deterministic validator 통과
- high-risk injection은 Health Scan finding

## 11.12 Structure-aware chunking

하나의 fixed-token chunker 금지.

Chunk type:

- clause + exception
- procedure + warning/prerequisite
- table header + row/cell
- FAQ pair
- section hierarchy
- figure + caption + referenced paragraph
- code + surrounding explanation

Chunk는 IR의 derived consumer package이며 source truth가 아니다.

```text
chunk_key = hash(
  unit_version_ids
  + chunker_version
  + target_consumer
  + embedding_model_revision
)
```

## 11.13 Deterministic target compiler

한 canonical core에서:

- AI-ready Markdown
- Obsidian vault
- RAG packages
- Ontology schema/data
- Neo4j-compatible export
- MCP resources
- source/evidence bundle

를 생성한다.

Target마다 별도 parser output을 다시 만들지 않는다.

## 11.14 Compile status

```text
PARSED
STRUCTURED
EVIDENCED
RESOLVED
COMPILED
VALIDATED
VERIFIED
```

Critical unresolved:

```text
COMPILE_BLOCKED
```

Noncritical warning publish는 workspace policy가 허용할 때만 가능하고 warning이 UI/API에 노출된다.

---

# PART 12 — SEMANTIC DIFF, DEPENDENCY, IMPACT & WORLD STATE

## 12.1 Change pipeline

```text
New Source Version
→ Source/Structural Diff
→ Semantic Unit Matching
→ Semantic Diff
→ Typed Dependency Traversal
→ Impact Set
→ Dirty Build
→ Validation
→ Atomic World-State Publish
→ Consumption Invalidation/Notification
```

## 12.2 Diff levels

```text
L0 bytes/hash
L1 layout/block
L2 text/token
L3 structure/hierarchy/table
L4 semantic claim/entity/relation
L5 operational meaning: authority/applicability/permission/time
```

예:

```text
"may" → "must"
```

문자 변화는 작지만 operational change가 크다.

## 12.3 Change types

- ADD / REMOVE / MODIFY
- MOVE / RENAME
- SPLIT / MERGE
- SUPERSEDE
- AUTHORITY_CHANGE
- APPLICABILITY_CHANGE
- EFFECTIVE_DATE_CHANGE
- PERMISSION_CHANGE
- EVIDENCE_CHANGE
- FORMAT_ONLY

## 12.4 Typed dependency edges

```text
DERIVED_FROM
EVIDENCE_FOR
REFERENCES
EXCEPTION_TO
SUPERSEDES
APPLIES_TO
DEPENDS_ON
EMBEDDED_AS
RETRIEVED_BY
CONSUMED_BY
PERMISSION_GOVERNS
```

모든 edge가 invalidation을 의미하지 않는다.

예:

- `DERIVED_FROM` source content change → 강한 propagation
- `REFERENCES` formatting-only change → 약한/no propagation
- `PERMISSION_GOVERNS` revoke → immediate access invalidation
- `EXCEPTION_TO` scope change → affected parent answers

## 12.5 Impact algorithm

```python
frontier = changed_nodes
visited = set()
while frontier:
    node = frontier.pop()
    for edge in outgoing(node):
        decision = propagation_policy(edge.type, change.type, context)
        if decision.invalidate and within_budget(edge):
            add_reason_path(node, edge)
            frontier.add(edge.target)
```

Output은 단순 node list가 아니라 reason path를 포함한다.

## 12.6 Explosion guard

Dependency graph 폭발을 막되 영향 누락을 숨기지 않는다.

- edge type별 propagation
- depth/branch budget
- high-fanout aggregate nodes
- cycle detection
- SCC condensation
- uncertainty escalation
- truncated impact는 `INCOMPLETE_IMPACT`로 fail/warn
- sampling으로 claim하지 않음

## 12.7 Dirty-set and recompile plan

```yaml
recompile_plan:
  build_id: bld_...
  source_change_ids: [...]
  dirty_units: [...]
  dirty_chunks: [...]
  dirty_embeddings: [...]
  dirty_exports: [...]
  stale_agent_contexts: [...]
  unaffected_proofs: [...]
  estimated_cost: ...
  estimated_latency: ...
```

## 12.8 Selective vs full rebuild equivalence

Controlled corpus에서:

```text
SelectiveRebuild(changes)
==
RelevantSubset(FullRebuild(new_sources))
```

Canonical serialization/hash와 semantic assertions를 비교한다.

False-negative impact는 최우선 catastrophic class다. False-positive recompile는 비용 문제지만 correctness를 망치지 않는다.

## 12.9 Atomic publish

1. affected outputs staging
2. validation
3. permission checks
4. evidence coverage
5. index consistency
6. transactionally world_state manifest commit
7. ACTIVE pointer swap
8. previous ACTIVE → SUPERSEDED
9. downstream event

중간 build를 Agent가 읽지 않는다.

## 12.10 Rollback

- pointer를 이전 valid world state로 원자적 전환
- source history 삭제 금지
- consumption lineage가 어느 state를 사용했는지 유지
- rollback event와 reason receipt
- index/compiled bundles compatible check

## 12.11 Freshness SLO

```text
Source change observed
→ ACL safe state
→ semantic diff complete
→ affected knowledge staged
→ ACTIVE world state updated
```

Metrics:

- Connector Detection Latency
- Permission Revocation Latency
- World Sync Latency
- Stale Exposure Window
- Recompile Reduction Ratio
- Impact Recall
- Recompile Precision

---

# PART 13 — RETRIEVAL, ASK & AGENT CONSUMPTION

## 13.1 Retrieval is a consumer, not the product core

TAVONEL은 RAG로 끝나지 않는다. Retrieval은 versioned world state를 소비하는 하나의 interface다.

## 13.2 Query contract

```yaml
retrieval_request:
  tenant_id: ...
  workspace_id: ...
  principal_id: ...
  permission_scopes: [...]
  world_state_id: current | ws_...
  as_of: ...
  known_at: ...
  authority_context: {}
  applicability_context: {}
  query: ...
  top_k: 10
  answer_mode: EVIDENCE_ONLY | GROUNDED_ANSWER
```

## 13.3 Filter order

1. tenant/workspace
2. ACTIVE/requested published world state
3. principal permissions/sensitivity
4. valid/system time
5. authority/applicability
6. validation/epistemic state
7. lexical + vector candidate
8. structure/graph neighborhood
9. rerank
10. evidence coverage

ANN 검색 후 permission filtering하는 구조를 금지한다.

## 13.4 Embedding contract

```text
embedding_key = hash(
  unit_or_chunk_version_id
  + embedding_model_id
  + model_revision
  + chunker_version
  + normalization_version
)
```

서로 다른 embedding version을 같은 ranking에서 무분별하게 섞지 않는다.

Upgrade:

```text
shadow index
→ retrieval benchmark
→ authority/time/permission fixtures
→ atomic index pointer swap
→ old index retention/rollback
```

## 13.5 pgvector

[OFFICIAL] approximate index의 metadata filter는 under-return 가능성이 있어 pgvector 0.8+ iterative scan 또는 exact fallback을 검토한다.

- small corpus: exact search baseline
- tenant/workspace filter selectivity benchmark
- HNSW/IVFFlat parameters receipt
- partition strategy는 cardinality 기반
- global index의 cross-tenant isolation/recall test

## 13.6 Hybrid retrieval

- lexical/BM25-style candidate
- dense semantic candidate
- structured metadata
- graph neighborhood
- table/numeric lookup
- reranker

질문 유형 classifier도 untrusted LLM 단독 결론이 아니라 deterministic/structured gateway를 사용한다.

## 13.7 Grounded answer contract

```yaml
answer:
  answer_text: ...
  world_state_id: ...
  completeness_scope: ...
  claims:
    - text: ...
      epistemic_state: SUPPORTED
      evidence_ids: [...]
      authority_reason: ...
      applicability_reason: ...
  conflicts: [...]
  limitations: [...]
  abstained: false
  consumption_id: con_...
```

Evidence가 없는 문장은 supported claim으로 표시하지 않는다.

## 13.8 Ask interface

일반 chatbot이 아니다.

> **Ask this world.**

답변 surface:

```text
ANSWER
2 years

WHY THIS ANSWER
Current · Official · Applies globally

SOURCE PATH
2026 Policy → Page 17 → Table 3 → Cell B4

CONFLICTS/EXCEPTIONS
2024 Manual: 1 year · superseded
Customer A Contract: 3 years · scoped exception

WORLD STATE
As of 2026-08-10 14:32 KST
```

## 13.9 Partial workspace answers

Compilation incomplete일 때:

- processed files/pages count
- world state coverage
- unprocessed sources
- answer limitation
- “complete”처럼 표현 금지

## 13.10 Agent Consumption Lineage

모든 search/answer/MCP consumption에 기록:

- principal/agent identity
- query hash and purpose
- world_state_id
- unit/chunk versions
- evidence IDs
- permission decision ID
- response/claim IDs
- downstream action reference if supplied

원본 변화 시 “어떤 Agent가 stale knowledge를 소비했는가”를 추적할 수 있다.

## 13.11 Raw AI vs TAVONEL benchmark/demo

동일 model을 사용한다.

왼쪽:

```text
Raw files → model
"It appears to be 1–3 years..."
```

오른쪽:

```text
TAVONEL world state → same model
"2 years; Customer A exception 3 years" + evidence
```

“우리 LLM이 더 좋다”가 아니라 **Same intelligence. Better world.**를 증명한다.

---

# PART 14 — PUBLIC API, CLI, SDK, WEBHOOKS & MCP

## 14.1 API-first

```text
Core API
├─ Web App
├─ CLI
├─ Python SDK
├─ TypeScript SDK
├─ Connectors
└─ MCP Server
```

별개의 business logic를 만들지 않는다.

## 14.2 Initial REST surface

```text
POST   /v1/upload-sessions
POST   /v1/upload-sessions/{id}/complete
POST   /v1/sources
GET    /v1/sources/{id}
POST   /v1/ingestions
GET    /v1/jobs/{id}
GET    /v1/jobs/{id}/events
GET    /v1/documents/{id}
GET    /v1/world-states/current
GET    /v1/world-states/{id}
POST   /v1/knowledge/search
POST   /v1/answers
POST   /v1/diffs
POST   /v1/impacts
GET    /v1/evidence/{id}
GET    /v1/health-reports/{id}
GET    /v1/reviews
POST   /v1/reviews/{id}/decisions
```

## 14.3 Async job model

Mutation response:

```json
{
  "job_id": "job_...",
  "status": "QUEUED",
  "status_url": "/v1/jobs/job_...",
  "events_url": "/v1/jobs/job_.../events"
}
```

Long job는 request connection에 묶지 않는다.

## 14.4 Streaming

- SSE first for product progress
- resumable `Last-Event-ID`
- event sequence per projection, not global queue order
- sanitized public event payload
- WebSocket은 bidirectional need가 증명될 때

## 14.5 Idempotency

- client `Idempotency-Key`
- tenant + endpoint + key scope
- request body hash mismatch reject
- result replay retention
- connector/webhook same contract

## 14.6 Error model

```json
{
  "error": {
    "code": "KNOWLEDGE_CONFLICTED",
    "message": "No single authoritative claim can be resolved.",
    "request_id": "req_...",
    "retryable": false,
    "details": {"review_id": "rev_..."}
  }
}
```

HTTP transport status와 domain error를 분리한다.

## 14.7 Webhooks

Events:

- ingestion.completed
- document.failed
- document.recovered
- knowledge.updated
- conflict.detected
- world_state.activated
- recompile.completed
- review.required
- usage.threshold_reached

Security:

- HMAC signature + timestamp
- replay window
- endpoint secret rotation
- delivery ID/idempotency
- retry/backoff/DLQ
- customer-visible delivery log
- test event

## 14.8 CLI

```bash
tavonel login
tavonel workspace select
tavonel ingest ./docs --workspace engineering
tavonel status job_...
tavonel watch ./docs
tavonel diff --from ws_1 --to ws_2
tavonel impact change_...
tavonel query "current warranty"
tavonel evidence ev_...
tavonel export --target obsidian
tavonel doctor
```

CLI requirements:

- resumable multipart
- local manifest/checkpoint
- checksum
- glob/ignore file
- dry-run
- machine-readable JSON
- nonzero exit codes
- keychain/secure token storage
- no production secret in shell history

## 14.9 SDK

Python/TypeScript 우선.

- generated API types
- async job helpers
- pagination
- retry policy respects retryable flag
- webhook verification
- upload helper
- SSE iterator
- request IDs/telemetry
- semantic versioning

## 14.10 MCP version and transport

[OFFICIAL] 2026-07-28 MCP stable specification에 맞춘 Streamable HTTP transport와 authorization profile을 구현한다.

초기 read-only tools:

```text
knowledge.search
knowledge.get
knowledge.as_of
knowledge.diff
source.verify
entity.get
entity.history
impact.trace
world_state.get
health.report.get
```

## 14.11 MCP authorization

- OAuth 2.1 resource server
- Protected Resource Metadata
- issuer binding
- resource/audience binding
- token passthrough 금지
- authorization code for end user
- client credentials for service account
- tool별 scope
- tenant/workspace binding
- output sanitization
- rate limit/audit

## 14.12 MCP resource design

Tools는 actions/query, Resources는 evidence/world-state artifacts로 분리한다.

- resource URI에 secret/filename 노출 금지
- signed short-lived evidence URL
- capability version/ETag
- page/table/cell metadata

## 14.13 Write MCP gate

다음이 모두 있을 때만:

- read-only production proof
- explicit scope
- idempotency
- dry-run/impact preview
- approval policy
- audit trail
- rollback
- permission model
- customer demand

초기에는 delete/destructive action을 제공하지 않는다.

---

# PART 15 — PRODUCT EXPERIENCE & CINEMATIC WEBSITE

## 15.1 v4 웹 전환

현재 product surfaces/evidence data 중 검증된 infrastructure는 살릴 수 있다. 그러나 다음은 전면 교체 대상이다.

### KEEP

- auth/session의 검증된 부분
- API client primitives
- evidence receipt data
- 유효한 upload/job components
- accessibility/test utilities

### ADAPT

- dashboard shell
- upload progress
- processing status
- evidence rendering

### REPLACE

- generic SaaS landing IA
- hero/feature-card 나열
- 현재 visual language
- fake progress/animation
- generic bottom-right chatbot

### BUILD

- cinematic narrative engine
- real event visualization
- Knowledge Health Scan
- Ask / Knowledge Console
- source zoom-back
- change→impact→recompile demo
- Raw AI vs TAVONEL
- Document Performance Map explorer

## 15.2 Site map

```text
/            Cinematic experience + demo + activation
/product     Five product layers and interactive mechanisms
/evidence    Benchmarks, methodology, limitations, receipts
/research    Technical papers, architecture, experiments
/security    Data handling, isolation, retention, deployment
/app         Actual product
/docs        API/CLI/SDK/MCP docs when ready
```

Navigation:

```text
TAVONEL
Product · Evidence · Research
Sign in · [Compile your knowledge]
```

초기에 불필요한 Solutions/Industries/Partners 메뉴를 늘리지 않는다.

## 15.3 Landing narrative

```text
MESS
→ DISCOVER
→ ROUTE
→ RECOVER
→ WORLD
→ TRUTH
→ CHANGE
→ ASK
→ EVIDENCE
→ YOUR TURN
```

사이트는 여러 섹션이 아니라 한 product world가 변형되는 연속 경험처럼 느껴져야 한다.

## 15.4 Hero / Scene 0 — MESS

Copy:

> **Your AI is only as reliable as the world it sees.**

Sub:

> Compile fragmented organizational knowledge into trusted, temporal, traceable context.

Visual:

- `policy_final.pdf`, `policy_final_v2.pdf`, `contract_A.pdf`, `pricing.xlsx`, scan 등
- hover/tap: `Version conflict`, `Complex table`, `Missing reference`
- 중앙: **This is what your AI sees.**

CTA:

- `Use sample workspace`
- `Try your files`

## 15.5 Scene 1 — DISCOVER / ROUTE / RECOVER

스크롤/interaction에 따라:

```text
Contract · Policy · Manual · Financial · Unknown
```

페이지 47이 멈춘다.

```text
STRUCTURE UNCERTAIN
→ REROUTING
→ RECOVERED
```

Copy:

> **Failures shouldn't silently become knowledge.**

실제 demo mode에서는 deterministic sample event stream, authenticated app에서는 실제 backend events.

## 15.6 WOW 1 — DOCUMENTS → WORLD

문서 카드가 Markdown 아이콘으로 끝나지 않는다.

```text
Customer A
↕ Contract 0182
↕ Product X
↕ Warranty Policy
↕ Korea
↕ Effective 2026-08
```

카메라가 빠지며 관계 세계가 나타난다.

Copy:

> **Don't give AI more documents. Give it a world it can understand.**

## 15.7 Scene 3 — TRUTH

`Warranty`를 선택하면:

```text
2024 Manual       1 year   SUPERSEDED
2026 Policy       2 years  ACTIVE
Customer A        3 years  CONTRACT EXCEPTION
```

Copy:

> **Finding information is easy. Knowing what is true now is harder.**

기술명 대신 동작을 보여준다.

## 15.8 WOW 2 — CHANGE PROPAGATION

사용자가 sample policy의 `2 years → 3 years`를 바꾼다.

```text
1 source changed
7 knowledge units affected
3 retrieval contexts stale
2 agent contexts impacted
RECOMPILING 7 / 12,841
```

관련 노드만 풀리고 재연결된다.

Copy:

> **When one fact changes, don't rebuild the world.**

## 15.9 Scene 5 — ASK

이제서야 입력창이 등장한다.

> **Ask this world.**

질문 예:

- What is the current warranty?
- Why is this source authoritative?
- What changed since the previous version?
- What would be affected if this policy changes?
- Show conflicting sources.

답은 evidence/version/applicability와 함께 표시한다.

## 15.10 WOW 3 — ANSWER → SOURCE

답을 클릭하면:

```text
Answer
→ Claim
→ Knowledge Unit
→ Source Document
→ Page 17
→ Table 3
→ Cell B4
```

카메라가 원본 region까지 되감긴다.

Copy:

> **Every answer should have a way home.**

## 15.11 Raw AI vs TAVONEL

Split screen:

```text
RAW AI
"It appears to be between 1 and 3 years..."

TAVONEL
2 years
Global policy · Effective date · Customer A exception · Evidence
```

Copy:

> **Same intelligence. Better world.**

## 15.12 Evidence scene

첫 화면에서 숫자를 난사하지 않는다. 제품 이해 후 3–4개만.

- 5,132 public benchmark documents
- 99.98% output completion
- 99.94% recovered among recovery-required docs
- 384/384 byte-identical outputs in reproducibility audit

Footnote:

> Performance varies materially by document type. Completion is not accuracy.

`Explore the evidence`로 full methodology.

## 15.13 Your Turn / Activation

> **Now show us your world.**

Buttons:

- Drop files
- Connect Google Drive
- Connect cloud storage
- Use sample workspace

업로드/연결 후 같은 visual world가 실제 tenant data로 전환된다.

## 15.14 Knowledge Health Scan

단일 `82/100`만 보여주지 않는다.

```text
742 pages analyzed
621 straightforward
83 structurally complex
21 recovered
7 version conflicts
4 unresolved references
3 potentially stale policy paths
```

Finding flow:

```text
Finding
→ Source preview
→ Why it matters to AI
→ Impact preview
→ [Compile / Resolve this workspace]
```

검사하지 않은 dimension을 100점으로 간주하지 않는다.

## 15.15 Real product event stream

Public projection event examples:

```text
upload.part_completed
source.admitted
document.profiled
route.selected
processing.started
inspection.failed
document.rerouted
recovery.completed
knowledge.created
conflict.detected
impact.detected
recompile.completed
world_state.activated
```

UI animation은 이 event에 반응한다. fake percentage 금지.

## 15.16 Visual design system

> **80% Calm · 20% Impossible Moment**

Base:

- warm graphite / bone / precise neutral
- high-quality sans + restrained editorial serif
- mono for evidence/data
- large whitespace
- thin grid and depth
- one signal accent color with semantic state

금지:

- generic glowing AI brain
- purple neon everywhere
- random particle universe
- meaningless orb
- excessive glassmorphism
- stock robots
- gradient text everywhere

## 15.17 3D/Motion stack

- React Three Fiber / Three.js
- GSAP ScrollTrigger or Motion where appropriate
- procedural geometry and product data structures
- Blender only for optimized authored assets if needed
- no paid scene hard dependency

3D는 실제 `Document → Unit → Claim → Entity → World` transformation에만 사용한다.

## 15.18 Performance budget

[OFFICIAL] Core Web Vitals p75 target:

- LCP ≤ 2.5s
- INP ≤ 200ms
- CLS ≤ 0.1

추가 내부 budget:

- initial JS route budget
- canvas lazy mount after meaningful content
- adaptive DPR
- object pooling/instancing
- texture/geometry compression
- no per-frame React state
- offscreen pause
- memory leak/context loss monitoring

## 15.19 Progressive enhancement

### Full

Desktop/high capability WebGL cinematic.

### Reduced

Mobile/low power simplified 2D/Canvas/SVG with same meaning.

### Reduced motion

`prefers-reduced-motion`에서 transition 최소화, scroll story를 static states로 제공.

### No WebGL / context lost

- semantic HTML/2D fallback
- `webglcontextlost/restored` handling
- product CTA/Health Scan still fully usable

## 15.20 Accessibility

- keyboard navigation
- focus order
- non-color state labels
- chart/table accessible alternative
- screen-reader narrative
- contrast tests
- no flashing/seizure-inducing motion
- motion pause
- captions/transcripts for demo

## 15.21 Website acceptance tests

- body copy 없이 30초 내 change→impact→recompile 이해
- PDF converter로 오해되지 않음
- generic chatbot으로 오해되지 않음
- source zoom-back works
- mobile intentional layout
- reduced-motion complete
- WebGL fallback complete
- Lighthouse/CWV budget
- Playwright visual regression
- claim text generated from claims pack
- no trade-secret receipt in client bundle/network


---

# PART 16 — BENCHMARK OS & EVIDENCE ARCHITECTURE

## 16.1 왜 단일 benchmark가 아닌가

같은 pipeline도 문서 분포에 따라 99.0%에서 36.9%까지 달라졌다. “TAVONEL 정확도” 하나는 다음을 숨긴다.

- 문서 유형
- task
- evaluator
- severity
- business impact
- route/recovery
- cost/latency

따라서 v4는 **Document Performance Map + Quality Vector + End-to-End Outcome**을 사용한다.

## 16.2 Suite architecture

### Suite A — Public Reproducible

- ParseBench
- OmniDocBench
- olmOCR-Bench

목적:

- external reproducibility
- parser/extraction comparison
- recovery ablation
- regression

공식 evaluator와 pinned revision을 변경하지 않는다. 새 evaluator version은 새 campaign ID다.

### Suite B — Real-World Corporate

현재 확보:

- DART
- SEC EDGAR

목적:

- 실제 회사 문서 분포
- long documents
- financial tables/footnotes
- version/amendment
- numeric fidelity
- corporate QA

### Suite C — Stress

의도적으로 어려운 page:

- degraded scans
- old scans/equations
- tiny font
- borderless/merged/nested tables
- cross-page tables
- multi-column
- photographed/rotated
- charts/diagrams
- corrupt/partial
- mixed Korean/English
- hidden/visual Office discrepancies

### Suite D — Production Golden Set

실제 고객 문제 중 계약/동의/비식별 정책을 통과한 사례.

- release regression
- incident recurrence
- connector/ACL
- authority/applicability
- review adjudication

Customer data를 무단 학습/공개하지 않는다.

## 16.3 DART corpus construction

[OFFICIAL] OpenDART는 공시 검색, 원본 파일, 기업 개황, 주요 재무정보 API를 제공한다.

Strata:

- 사업보고서
- 반기/분기보고서
- 감사보고서
- 정정공시
- 주요사항보고서
- 재무제표/주석
- 첨부 원본
- HTML/XML/PDF representation

Features:

- Korean digital text
- mixed English
- dense financial table
- footnote-heavy
- amendment/supersession
- very long filing
- chart/figure
- scanned attachment

Sampling은 기업 규모/산업/연도/문서 유형을 층화하고 동일 template 과대표집을 막는다.

## 16.4 SEC corpus construction

[OFFICIAL] SEC `data.sec.gov`는 submissions와 XBRL JSON을 제공하고, 10-K/10-Q/8-K/20-F 등 facts를 제공한다. XBRL을 **ground truth 후보**로 사용하되 filing의 context/unit/period/custom taxonomy를 정확히 매칭한다.

Strata:

- 10-K
- 10-Q
- 8-K
- 20-F/6-K
- amendments
- exhibits
- inline XBRL
- financial tables/footnotes

SEC access policy와 rate limit을 준수하고 bulk archives를 대량 수집에 우선한다.

## 16.5 Benchmark manifest

```yaml
campaign:
  campaign_id: camp_...
  created_at: ...
  source_manifests: [...]
  split_manifest_sha256: ...
  evaluator:
    name: ...
    revision: ...
    container_digest: ...
  pipeline:
    registry_snapshot: ...
    route_policy: ...
    recovery_policy: ...
    compiler_version: ...
  exclusions: [...]
  metrics: [...]
  claim_status: INTERNAL_ONLY
```

## 16.6 Leakage prevention

- train/dev/test split by document family/company/template/time
- near-duplicate detection across splits
- prompts/policies tuned on dev only
- hidden test labels
- repeated public benchmark optimization을 public generalization으로 포장 금지
- customer golden set는 model provider training에 전송 금지 unless explicit contract

## 16.7 TAVONEL Quality Vector

### Delivery / operations

- Completion Rate
- Crash/Timeout/OOM Rate
- Recovery Rate
- Unrecoverable Rate
- Reproducibility
- Cost and latency percentiles

### Extraction

- CER/WER/edit distance
- reading order
- block coverage
- table structure/full/cell
- formula
- chart/diagram extraction

### Semantic preservation

- heading-body
- clause-exception
- procedure-warning
- table-header/cell
- caption-figure
- footnote-element
- cross-page continuity
- hierarchy

### Knowledge integrity

- stable identity
- entity resolution
- version/revision
- authority/applicability
- provenance coverage
- temporal correctness
- permission correctness
- epistemic abstention

### Change intelligence

- semantic diff precision/recall
- impact recall/precision
- reason-path correctness
- recompile equivalence
- full-recompute avoided
- world sync latency

### Downstream

- QA correctness
- critical numeric correctness
- citation correctness
- evidence localization
- unsupported claim rate
- stale answer rate
- multi-document reasoning
- exception handling
- abstention correctness

## 16.8 Critical Numeric Fidelity

금액/비율/날짜/수량/단위/sign은 별도 평가한다.

```text
Numeric Exact Match
Unit Match
Sign Match
Cell Association
Period/Context Match
Evidence Localization
```

예:

`1,205억원` → `1,250억원`은 문자 edit distance가 작아도 catastrophic.

Severity-weighted report는 원 metric과 함께 표시하고 weight를 투명하게 공개한다.

## 16.9 Semantic Preservation gold annotation

Annotation unit:

- source region(s)
- semantic relation type
- expected hierarchy
- acceptable variants
- severity

Annotator 2인 + adjudication. Agreement를 보고하고 unresolved gold를 test에서 제외하거나 uncertain으로 유지한다.

## 16.10 Knowledge Integrity benchmark

Controlled mini-organizations를 만든다.

예:

```text
Global Warranty 1 year (old)
Global Warranty 2 years (current)
Customer A contract 3 years (exception)
Japan product family 1.5 years (regional)
```

질문:

- current global
- Customer A
- as-of old date
- known-at before update
- permission-restricted
- conflicting draft

정답은 answer뿐 아니라 authority/applicability/time reason path를 포함한다.

## 16.11 Change Evolution benchmark

Source mutations:

- typo/format only
- number change
- may→must
- section move
- clause split/merge
- supersession
- effective date
- permission revoke
- contract exception

Measure:

- diff classification
- stable identity continuity
- affected set recall
- unnecessary recompile
- resulting world state equivalence

## 16.12 End-to-end same-model ablation

동일 LLM, 동일 질문, 동일 generation settings:

```text
A. Raw PDF / direct multimodal
B. Basic parse + fixed chunk RAG
C. TAVONEL compiled knowledge
```

Measure:

- answer correctness
- numeric/table QA
- citations/evidence
- stale/conflict handling
- latency/cost
- abstention

이 실험이 `TAVONEL이 AI를 실제로 개선하는가`에 대한 가장 중요한 제품 evidence다.

## 16.13 Router benchmark

각 page × candidate model의 oracle matrix:

```text
quality
catastrophic failure
latency
GPU/API cost
retry
provider failure
```

Router metrics:

- oracle regret
- trust constraint violation
- cost vs always-champion
- cost vs always-frontier
- quality non-inferiority
- false escalation
- missed escalation
- route stability
- slice fairness

## 16.14 Economic metrics

```text
Cost / Input Page
Cost / Successful Page
Cost / Recovered Page
Cost / Additional Quality Point
Cost / Trusted Knowledge Unit
Cost / Active World-State Change
GPU Utilization
API Tail Fraction
Full Recompute Avoidance Ratio
```

### Cost per recovered page

```text
Incremental Recovery Cost
÷
Incrementally Recovered Pages
```

### Trusted Knowledge Yield

```text
Trusted Knowledge Yield =
Eligible input units promoted to required trust tier
÷
Total eligible input units
```

Denominator와 excluded states를 함께 공개한다.

## 16.15 Statistical reporting

- bootstrap confidence interval where appropriate
- paired comparison on same documents
- McNemar/paired bootstrap for pass/fail
- no unpaired leaderboard conclusion
- slice sample size
- multiple comparison caution
- effect size and cost, not p-value only
- evaluator variance separated from pipeline variance

## 16.16 No-regression gate

New model/router/retry candidate는 전체 평균만 좋아져도 통과하지 않는다.

Gate:

- catastrophic slices no regression
- low-quality scan measured
- numeric fidelity no regression
- reproducibility
- cost cap
- p95/p99 latency
- license/data policy
- prior approved claims remain valid or versioned

## 16.17 Evidence artifact structure

```text
docs/evidence/
├─ manifests/
├─ artifacts/
├─ evaluators/
├─ receipts/
├─ claims/
├─ reports/
└─ limitations/
```

Claim pack fields:

```yaml
claim:
  claim_id: ...
  status: APPROVED | CONDITIONAL | WITHHELD | RETIRED
  text: ...
  metric: ...
  numerator: ...
  denominator: ...
  corpus: ...
  evaluator: ...
  pipeline: ...
  effective_date: ...
  required_caveats: [...]
  forbidden_phrasings: [...]
  artifact_refs: [...]
  artifact_hashes: [...]
```

## 16.18 Evidence page

Landing의 짧은 proof 뒤 `/evidence`에서:

- methodology
- public suite
- DART/SEC real-world suite
- stress suite
- Document Performance Map
- recovery ablation
- cost
- limitations
- negative results
- reproducibility
- downloadable machine-readable claims pack

좋은 결과만 보여주는 leaderboard가 아니라 **Trust through evidence**.

---

# PART 17 — SECURITY, PRIVACY & ENTERPRISE HARDENING

## 17.1 Threat model

Assets:

- customer source documents
- credentials/connectors
- provenance/world state
- route/trade-secret dataset
- model prompts/policies
- audit/billing

Adversaries/failures:

- malicious upload
- prompt injection/RAG poisoning
- cross-tenant access
- compromised connector token
- parser/container supply-chain compromise
- insider/admin misuse
- model provider data leakage
- stale ACL
- webhook replay
- billing abuse
- accidental deletion
- evidence tampering

## 17.2 Upload security

[OFFICIAL OWASP-aligned]

- extension allowlist
- magic/MIME verification
- generated storage key
- size/dimension/page/archive limits
- storage outside public webroot
- quarantine
- sandbox
- malware/CDR hook
- no macro/link execution
- zip/XML bomb defense
- per-tenant quota

## 17.3 Parser sandbox

- non-root
- read-only filesystem except scoped temp
- no outbound network
- seccomp/AppArmor where available
- CPU/memory/time/file limits
- no cloud metadata access
- short-lived credential scoped to exact R2 prefixes
- clean worker/container after suspicious parse

## 17.4 Prompt injection defense

- document content is untrusted data, never instruction authority
- extraction/semantic models receive no tools
- policy/auth decisions deterministic
- retrieved text cannot grant permission
- external URL fetch disabled
- suspicious hidden text/white-on-white/instruction patterns labeled
- output encoding/sanitization
- red-team corpus

## 17.5 Tenant isolation

- RLS and force RLS
- tenant-scoped object key/token
- tenant context in every job/event
- no global cache key without tenant
- cross-tenant property tests
- support/admin access just-in-time with audit
- anonymized telemetry policy

## 17.6 Encryption and secrets

- TLS in transit
- provider-managed encryption at rest minimum
- optional customer-managed keys roadmap
- secrets in managed secret store, not DB/log
- connector refresh token encryption
- key rotation
- presigned URL short TTL/scope
- signed evidence URLs

## 17.7 Data retention/deletion

Retention classes:

- source
- derived
- temporary render
- audit/evidence
- backup

Deletion workflow:

```text
Customer request
→ authorization
→ tombstone/retrieval deny
→ active processing cancel
→ R2 object purge
→ derived/index purge
→ connector token revoke
→ backup expiry policy
→ deletion receipt
```

“delete”가 DB row만 숨기는 것으로 끝나지 않는다.

## 17.8 Model provider policy

Registry에:

- retention
- training use
- ZDR eligibility
- region
- data type restriction
- subprocessors

Workspace가 provider를 금지하면 Router candidate에서 deterministic하게 제거한다.

## 17.9 Identity and enterprise access

- OIDC first
- enterprise SAML via provider/gateway when demanded
- SCIM provisioning/deprovisioning after paid demand
- MFA/admin policies
- service accounts
- API key scopes/rotation
- session revocation

없는 SSO/SCIM을 marketing에 표시하지 않는다.

## 17.10 RBAC/ABAC

Roles만으로 부족한 source ACL을 attribute/context와 결합한다.

- workspace role
- source permission
- sensitivity
- region
- purpose
- time
- service account scope

Authorization decision ID를 retrieval/answer/consumption에 남긴다.

## 17.11 Audit

Audit events:

- login/token
- upload/connect/delete
- source/ACL change
- route/recovery/review
- world-state publish/rollback
- search/answer/evidence access
- admin/support access
- billing/claim changes

Tamper-evident append-only export와 customer audit export는 enterprise phase.

## 17.12 Supply-chain security

- lockfiles
- verified model/container pins
- SBOM
- Cosign signatures
- SLSA provenance/attestation
- vulnerability/license scan
- dependency update canary
- production admission policy
- secrets scanning

## 17.13 Backup and DR

Document:

- RPO
- RTO
- backup frequency
- encrypted backup
- cross-region policy
- R2 source manifest consistency
- DB/world-state pointer recovery
- connector cursor recovery

Launch 전에 restore drill:

1. isolated environment restore
2. ACTIVE world state pointer validation
3. evidence/source hash validation
4. permission test
5. query test
6. measured RTO/RPO receipt

## 17.14 Incident response

Severities:

- SEV0 cross-tenant/data exposure
- SEV1 incorrect active world state/permission stale
- SEV2 processing outage/cost runaway
- SEV3 localized failure

Runbooks:

- credential compromise
- connector token leak
- malicious parser artifact
- world-state rollback
- provider-wide GPU stop
- queue backlog/DLQ
- evidence tampering
- billing anomaly
- WebGL/frontend incident does not block core product

## 17.15 Compliance posture

초기:

- privacy/terms/DPA-ready architecture
- data inventory
- retention/deletion
- subprocessors
- security page
- incident/backup evidence

후속:

- SOC 2 / ISO 27001은 product/paid demand에 맞춰 진행
- 인증 전 로고/claim 금지

---

# PART 18 — OBSERVABILITY, SRE & FINOPS

## 18.1 OpenTelemetry

모든 path에 correlation:

```text
upload → source → profile → route → attempt → inspect → recover
→ reconcile → compile → impact → world state → retrieval → answer
```

Spans:

- `tavonel.upload.part`
- `tavonel.preflight`
- `tavonel.profile`
- `tavonel.route`
- `tavonel.model.inference`
- `tavonel.inspect`
- `tavonel.recovery`
- `tavonel.reconcile`
- `tavonel.compile`
- `tavonel.impact`
- `tavonel.world_state.publish`
- `tavonel.retrieve`
- `tavonel.answer`

민감 text/filename을 span attribute에 넣지 않는다.

## 18.2 SLO layers

### Ingestion

- acknowledgement
- upload success
- resume success
- preflight availability

### Processing

- job completion
- p50/p95/p99 by route
- worker loss
- recovery
- cost

### Knowledge

- provenance coverage
- world-state publish
- sync latency
- impact correctness
- permission correctness

### Product

- Time to First Knowledge
- Time to First Answer
- Health Scan completion
- Ask availability

## 18.3 Dashboards

- queue backlog/age
- active workers/model residency
- attempt status/error class
- route distribution
- recovery yield
- model quality/cost/latency
- per-tenant spend/quota
- world-state build/publish
- connector health/cursor lag
- API/MCP latency/errors
- claims/evidence status
- frontend CWV/WebGL failures

## 18.4 Alerts

- provider-wide correlated stops
- no heartbeat with active lease
- queue age threshold
- cost rate anomaly
- frontier tail fraction spike
- permission revoke latency
- world-state build stuck
- active pointer inconsistency
- cross-tenant test failure
- R2/DB artifact mismatch
- connector channel expiry
- webhook DLQ
- model registry license expiration/change

## 18.5 Internal usage ledger

Stripe/provider meter가 truth가 아니다. TAVONEL은 append-only internal ledger를 가진다.

```yaml
usage_receipt:
  receipt_id: ...
  tenant_id: ...
  workspace_id: ...
  job_id: ...
  unit_type: PAGE | GPU_SECOND | API_TOKEN | STORAGE_GB_DAY | VERIFIED_UNIT
  quantity: ...
  cost_basis: ...
  customer_billable: true
  pricing_version: ...
  occurred_at: ...
  idempotency_key: ...
```

Provider bill과 reconciliation한다.

## 18.6 Customer pricing unit

초기에는 복잡한 내부 cost를 그대로 고객에게 노출하지 않는다.

후보:

- included pages/credits
- complexity-weighted pages
- workspace subscription + overage
- enterprise annual + processing allowance

Customer-visible unit는 예측 가능해야 하고 internal cost ledger와 bounded margin으로 연결돼야 한다.

## 18.7 Stripe adapter

[OFFICIAL] Stripe meters/meter events는 usage aggregation과 usage-based billing을 지원한다. Meter event는 async processing될 수 있으므로 invoice sink로 사용하고 internal usage ledger와 reconcile한다.

- idempotent export
- 15 significant digit validation
- async error events
- daily reconciliation
- customer invoice preview
- billing alerts/spend cap

## 18.8 Budget enforcement

- tenant daily/monthly cap
- job estimate before execution
- soft warning/hard stop
- high-risk document override approval
- frontier model fraction cap
- storage retention cost
- abandoned multipart cleanup
- RunPod resource reconciler

## 18.9 Unit economics dashboard

```text
Revenue
- GPU raw cost
- API provider cost
- storage/operations
- queue/database
- support/review
= contribution margin
```

Slice by:

- customer
- document type
- route
- model
- failure class
- recovery tier

## 18.10 Chaos tests

- duplicate/out-of-order queue event
- worker killed after output upload before DB commit
- DB commit after queue retry
- R2 transient failure
- provider-wide stop
- account spend limit
- connector notification gap
- permission revoke during compile
- active pointer swap crash
- schema mixed versions
- Webhook endpoint timeout
- model returns malformed/poisoned output
- browser upload interruption

---

# PART 19 — IP, CLAIMS, MARKETING & GTM

## 19.1 IP disclosure firewall

각 기술마다 다음 registry를 만든다.

```yaml
ip_item:
  technology: Adaptive Economic Router
  patent_candidate: true
  filing_status: NOT_FILED | FILED | PUBLISHED | GRANTED
  trade_secret_components: [...]
  public_level: VALUE_ONLY | HIGH_LEVEL | PATENT_LEVEL | FULL_PUBLIC
  allowed_claims: [...]
  forbidden_details: [...]
  owner: ...
  review_before_publish: true
```

## 19.2 Patent vs trade secret

### Patent candidate

- semantic-quality/failure evidence 기반 distributed worker anomaly/recovery
- impact-scope calculation and selective reprocessing
- adaptive document execution high-level system
- document-semantic lineage and incremental recompilation
- world-state synchronization architecture

실제 청구범위는 변리사/선행기술 조사로 확정한다.

### Trade secret

- feature/weight/threshold
- routing/recovery recipe
- cost matrix
- private benchmarks/outcome data
- prompts/calibration
- dependency scoring
- customer tuning

[OFFICIAL] 한국의 공지예외가 존재하더라도 해외 권리와 신규성을 고려하면 핵심 공개 전 출원하는 것이 안전하다. 출원은 원칙적으로 18개월 후 공개될 수 있으므로 공개될 구조와 영업비밀 recipe를 분리한다.

## 19.3 Defense stack

```text
Patent       system/method structure
Trade Secret performance recipe/data
Copyright    code/UI/research
Trademark    TAVONEL / category assets
Data Moat    Performance Map / Outcome Dataset / Failure Corpus
Execution    operations/evidence/customer trust
```

## 19.4 Public marketing abstraction

### Adaptive Router

> **Every page doesn't need the same AI.**

### Recovery Runtime

> **Failures shouldn't silently become knowledge.**

### Provenance

> **Every answer should have a way home.**

### Incremental recompilation

> **When one fact changes, don't rebuild the world.**

### Temporal knowledge

> **Your AI shouldn't work at yesterday's company.**

WHY/WHAT/RESULT를 공개하고 결정적 HOW는 숨긴다.

## 19.5 Core homepage promise

> **Your AI can only reason over the world it sees. Make that world trustworthy.**

## 19.6 “There is no single document accuracy” positioning

```text
A clean digital report and a degraded financial scan are not the same problem.
That's why TAVONEL doesn't treat every page the same.
```

약점을 숨기는 대신 Router/Recovery의 존재 이유로 바꾼다.

## 19.7 Evidence depth model

### Level 1 — Executive, 5 seconds

- problem
- product
- difference

### Level 2 — Technical buyer, 2–5 minutes

- architecture
- security
- benchmark
- integrations

### Level 3 — Research/engineering, 30+ minutes

- manifests
- evaluator revisions
- ablations
- limitations
- negative results
- cost methods
- receipts/hashes

> **겉은 단순하게. 뒤는 무서울 정도로 깊게.**

## 19.8 Gracian Code funnel

```text
GRACIAN CODE
Attention / Insight
→ Problem Awareness
→ Technical Credibility
→ TAVONEL Research / Evidence
→ Knowledge Health Scan
→ Compile
→ Continuous Sync / Agent Context
→ Paid / Enterprise
```

Gracian Code는 광고 계정이 아니다.

프로필에서는 일찍:

> Building TAVONEL — The Knowledge Compiler

정도로 존재를 발견 가능하게 한다. 본문 CTA는 Bridge Score에 맞춘다.

## 19.9 R&D content engine

독점 소재:

- OCR vs multimodal
- one model vs model portfolio
- 문서마다 성능이 왜 다른가
- 실패가 조용히 통과하는 문제
- operational failure cost
- recovery ON/OFF
- 한 오류의 전파
- semantic diff/recompile
- AI가 알고 있는 회사의 시간

공개 benchmark 수치는 approved claims pack만 사용한다.

## 19.10 Initial wedge

첫 paid pilot은 좁게.

우선 후보:

1. technical documentation/customer support
2. manufacturing manuals
3. policy/compliance

선정 기준:

- stale/version conflict pain
- answer/evidence need
- regular change
- accessible decision maker
- bounded corpus
- pilot success measurable

## 19.11 Pilot contract

- corpus and permissions
- baseline QA/freshness issue
- accepted document types
- provenance target
- world sync target
- Health Scan findings
- weekly review
- limitations
- paid conversion criterion
- customer claim/publication permission

2–4주 후 성공뿐 아니라 실패 receipt도 남긴다.

## 19.12 Knowledge Health Scan as activation

사용자의 문서가 스스로 문제를 증명한다.

```text
Version conflicts
Broken evidence
Recovered pages
Ambiguous entities
Potentially stale paths
Permission inconsistencies
```

CTA:

> **See what your AI is actually seeing.**

## 19.13 Claims governance

- philosophy: 자유로운 관점, fact와 구분
- existing benchmark: approved claim only
- new Router/model: same-condition benchmark 후
- Knowledge CI/CD: controlled change corpus 후
- customer outcome: permission + methodology 후

Marketing copy edit도 CI claim validator를 통과한다.

---

# PART 20 — CURRENT REPOSITORY → V4 MIGRATION MATRIX

## 20.1 Migration categories

- **KEEP:** 검증된 구현 그대로
- **ADAPT:** contract/telemetry/security 추가
- **REPLACE:** shadow/canary로 대체
- **BUILD:** 신규
- **DEPRECATE:** 사용 중지 후 제거
- **DEFER:** demand/gate 전 미구현

## 20.2 Module matrix

| Module | Action | 상세 |
|---|---|---|
| `akc_cir.inspection` | KEEP/ADAPT | v4 finding schema/event 연결 |
| `akc_cir.recovery_policy` | KEEP/ADAPT | operational vs semantic actions |
| `akc_cir.reconciler` | KEEP/ADAPT | cross-page benchmark/provenance |
| `akc_cir.identity` | KEEP | threshold 변경 전 corpus calibration |
| entity/authority/temporal | ADAPT | review queue, API/world state integration |
| semantic_diff/dependency | KEEP/ADAPT | typed event/impact reason path |
| recompilation/world_state | KEEP/ADAPT | atomic publish/rollback gates |
| `akc_parallel_runtime.routing` | KEEP LEGACY → REPLACE | v4 shadow router, phased rollout |
| campaign parser harness | ADAPT | production adapter/registry contract |
| current evidence page | KEEP DATA / REPLACE UX | claims pack renderer |
| current landing | REPLACE | cinematic narrative |
| current upload | ADAPT/REPLACE | R2 multipart/progressive |
| retrieval/API/MCP | BUILD | permission-first/read-only |
| Health Scan/billing | BUILD | real telemetry/internal ledger |
| connectors | BUILD | Drive first, storage next |
| Decision replay/write MCP | DEFER | paid demand/governance gate |

## 20.3 Big-bang rewrite 금지

모든 replacement는:

```text
compatibility contract
→ shadow
→ benchmark
→ canary
→ rollout
→ deprecate
```

## 20.4 Feature flags

```text
V4_CONTRACTS
V4_INGEST
V4_PREFLIGHT
V4_PROFILER
V4_MODEL_REGISTRY
V4_SHADOW_ROUTER
V4_ROUTE_EXECUTION
V4_BENCHMARK_OS
V4_RETRIEVAL
V4_ASK
V4_HEALTH_SCAN
V4_CINEMATIC_LANDING
V4_CONNECTOR_DRIVE
V4_PUBLIC_API
V4_MCP_READ
```

Flags는 tenant/workspace/cohort 단위. kill switch와 audit.

## 20.5 Compatibility layer

- current CIR input/output adapters
- dual-write receipts
- current tests remain green
- old world-state reader retained during migration
- schema version negotiation
- no historical receipt rewrite


---

# PART 21 — V4 DEPENDENCY-AWARE IMPLEMENTATION PHASES

> Phase 번호는 priority가 아니라 dependency order다. 각 Phase는 code, test, evidence, rollback이 모두 있을 때만 종료한다. 외부 secret/payment/legal decision 외에는 비파괴적 Phase 사이에서 사용자 재확인을 요구하지 않는다.

## PHASE 0 — Baseline Freeze, IP & Supply-Chain Gate

### 목표

현재 proven evidence와 working core를 보호하고 v4 전환의 기준점을 만든다.

### 구현

- git status/branches/deployments/migrations inventory
- all existing tests/linters/builds 실행
- evidence artifact/hash 검증
- `v3.1-baseline` tag
- current architecture map
- dependency/model/container/dataset license inventory
- patent/publication freeze list
- IP Disclosure Registry skeleton
- root `CLAUDE.md` v4 constitution
- feature flag framework

### 산출물

```text
docs/audit/V4_BASELINE_RECEIPT.md
docs/audit/V4_MIGRATION_MATRIX.md
docs/audit/V4_LICENSE_AND_SUPPLY_CHAIN.md
docs/ip/V4_DISCLOSURE_REGISTRY.yaml
infra/supply-chain/verified-pins.json
```

### Exit gate

- existing green tests or documented known failures
- evidence hashes match
- protected core list accepted in repo docs
- no production-blocked license component silently active
- rollback/tag verified

### Rollback

No feature changes. Reset to baseline tag.

---

## PHASE 1 — Canonical Contracts, Event Schema & Compatibility Layer

### 목표

코드보다 먼저 v4 language를 잠근다.

### 구현

- canonical ID/state/failure/event enums
- JSON Schema/Pydantic/TS codegen
- artifact/event/manifest/profile/route/attempt/finding/review/world-state contracts
- public vs internal DTO separation
- current CIR compatibility adapter
- outbox/inbox migration
- schema compatibility test
- ADR template/phase receipt schema

### Tests

- JSON round-trip
- unknown field behavior
- N/N-1 producer/consumer
- property-based ID/state transition
- event duplicate
- migration graph single head
- RLS baseline

### Exit gate

- no current core regression
- event schemas generated in Python/TS
- protected historical receipts still parse
- public serializer cannot expose trade-secret fields

### Rollback

Feature flag off; compatibility adapter leaves current path unchanged.

---

## PHASE 2 — Secure Industrial Ingestion

### 목표

Browser/app server bottleneck 없이 안전하고 resumable한 production front end를 만든다.

### 구현

- upload session API
- R2 presigned single/multipart
- IndexedDB/CLI resume
- streaming checksum
- complete verification
- quarantine/admission states
- per-format preflight
- R2 manifest/object layout
- lifecycle/abandoned multipart cleanup
- queue event creation
- progressive processing
- quota/backpressure

### Tests

- 1B/100MB/5GB simulated files
- interruption/resume
- expired presign
- duplicate complete request
- part corruption
- zip bomb/path traversal
- password/encrypted PDF
- malicious OOXML relationship
- 10,000 files UI virtualization
- mobile/slow network

### Exit gate

- app server does not proxy source bytes
- resume does not restart from zero
- source hash/manifest durable
- malicious fixture quarantined
- first file can enter profile before workspace upload completes
- no GPU provisioned while only upload waits

### Rollback

`V4_INGEST` off; existing upload remains available during transition.

---

## PHASE 3 — Reference Renderer, Profiler & Model Registry

### 목표

Router가 사용할 versioned sensors와 verified capabilities를 만든다.

### 구현

- deterministic PDF reference renderer
- Office native/visual preflight
- page/document feature extraction
- missing feature reason
- business risk labels
- profiler dashboard for fixtures
- model/parser/provider registry
- license/capability/data-policy/cost snapshot
- capability probe harness
- DeepSeek/provider variant identity guard

### Tests

- repeated render/profile stability
- blank vs empty
- rotated/multi-column/table/formula/scans
- official modality mismatch blocked
- license BLOCKED cannot route
- provider price change versioned
- registry snapshot immutable

### Exit gate

- no scalar universal quality score
- all production candidates have capability/license receipts
- profile schema named/versioned
- model name alone cannot grant vision route

### Rollback

Profiler shadow only; existing parser path unchanged.

---

## PHASE 4 — Execution Planner & V4 Shadow Router

### 목표

Minimum Cost to Trusted Output를 deterministic shadow policy로 구현한다.

### 구현

- route classes R0–R9
- plan DAG
- candidate filtering
- cost/latency/risk constraints
- operational vs semantic decision
- abstention
- internal route receipt
- legacy vs v4 comparison
- budget policy
- shadow outcome recorder

### Tests

- unsupported modality blocked
- high-risk numeric conflict escalates
- low-risk digital document avoids frontier
- operational timeout uses same-model retry
- semantic repeat avoids identical retry loop
- budget exhaustion → review/fail closed
- deterministic route under same registry snapshot

### Exit gate

- 100% shadow receipts on selected benchmark
- no production decision yet
- route reasons reproducible
- trade-secret decision fields absent from public events

### Rollback

Shadow collector disabled; no path impact.

---

## PHASE 5 — Parser Adapters, Scheduler & RunPod Commit Protocol

### 목표

Campaign harness를 production-safe execution adapters로 바꾼다.

### 구현

- MinerU champion adapter
- existing Paddle/DeepSeek harness adapters normalized
- external multimodal adapter interface
- queue routing
- lease/heartbeat
- R2-before-ACK
- idempotency
- startup/health probe
- network volume/model cache policy
- circuit breaker
- multi-tenant weighted scheduling
- cost telemetry

### Tests

- kill worker at every commit step
- duplicate queue delivery
- output R2 exists but DB missing
- DB committed but ACK missing
- OOM/batch split
- provider-wide simultaneous stop
- missing model/bootstrap
- no idle pod leak
- concurrent network-volume write protection

### Exit gate

- duplicate delivery has one final side effect
- worker loss preserves source and resumes
- every attempt has output/error/cost receipt
- campaign champion behavior non-regressed
- idle resource reconciler verified

### Rollback

Champion pointer to existing harness/runtime; v4 scheduler flag off.

---

## PHASE 6 — Inspector/Recovery Integration & Review Queue

### 목표

Protected Recovery를 v4 Control Plane에 연결한다.

### 구현

- finding schema adapters
- expanded taxonomy
- source-aware blank
- numeric/structural checks
- retry/escalation ladder
- independent verifier contract
- document reconciler integration
- human review queue
- review provenance
- fail-closed publish gate

### Tests

- all historical recovery fixtures
- recovery ON/OFF campaign smoke
- same-model deterministic no-gain
- alternate-family recovery
- high-risk disagreement
- blank page correct empty
- review decision replay
- unresolved critical compile blocked

### Exit gate

- existing benchmark recovery behavior preserved
- operational/cognitive failure separation measured
- every recovery action names trigger/budget/receipt
- review queue supports required types

### Rollback

Use existing recovery policy version pointer.

---

## PHASE 7 — Benchmark OS & Document Performance Map

### 목표

모델/라우터/제품 성능을 문서 분포·품질·비용과 함께 측정한다.

### 구현

- public campaign runner
- DART/SEC manifests
- stress suite
- production golden set framework
- model oracle matrix
- DPM database
- Router Outcome Dataset
- cost/latency capture
- statistical report generator
- no-regression CLI
- claims pack v4

### Tests

- exact manifest reproducibility
- split leakage/near duplicates
- evaluator pin
- missing artifact/hash claim rejection
- slice reporting
- paired ablation
- negative result preservation

### Exit gate

- all candidate models tested on hard set before route promotion
- model×slice×cost data available
- Router shadow regret/cost report
- no public v4 performance claim yet unless approved

### Rollback

Benchmark data is append-only; no production path change.

---

## PHASE 8 — Protected Compiler Core Production Integration

### 목표

현재 Built 코어가 live ingestion/execution path에서 end-to-end 동작하게 한다.

### 구현

- execution artifact → current CIR compatibility adapter
- raw/reconciled/IR artifact lineage
- evidence inspector backend
- structure-aware chunking
- deterministic exports
- Office dual-path reconciliation
- document identity/dedup/revision graph
- stable ID dual-write comparison

### Tests

- current unit/property tests
- cross-page table/caption
- Office native vs visual fixtures
- exact duplicate/rename/revision/branch
- unresolved link fail-closed
- export determinism
- current vs v4 adapter equivalence

### Exit gate

- live admitted source reaches trusted IR
- all published units have evidence or explicit unsupported state
- no stable identity regression
- four exports deterministic from same core

### Rollback

Compatibility adapter pointer to current schema; dual-write artifacts retained.

---

## PHASE 9 — Entity, Authority, Applicability, Temporal & Epistemic

### 목표

문장을 읽는 수준에서 “무엇이 지금 누구에게 맞는가”를 해결한다.

### 구현

- entity mention/canonical model
- conservative resolver
- authority resolver DSL
- applicability contexts
- valid/system time
- conflict/unknown state
- prompt injection labels
- review UI integration
- permission scope propagation

### Tests

- same name/different person
- alias/same entity
- global vs customer contract
- old vs active policy
- unknown date not fabricated
- as-of/known-at
- conflict abstention
- permission scope inheritance

### Exit gate

- controlled mini-organization benchmark passes
- no `latest wins` shortcut
- unresolved authority does not publish single truth
- review provenance preserved

### Rollback

Use prior resolver policy; new states remain as warnings/unresolved.

---

## PHASE 10 — Change Intelligence & Atomic World State

### 목표

Source change부터 affected knowledge만 재컴파일하고 atomic publish까지 닫는다.

### 구현

- L0–L5 semantic diff
- typed dependency graph
- impact reason paths
- explosion guard
- dirty set
- selective target compiler
- full rebuild equivalence harness
- staged world state
- ACTIVE pointer swap
- rollback
- freshness metrics

### Tests

- format-only
- number change
- may→must
- move/split/merge/supersede
- permission revoke
- cycles/high fanout
- selective vs full equivalence
- crash before/during/after pointer swap
- concurrent source changes

### Exit gate

- no partial world state visible
- impact false negatives zero on critical fixture set
- selective relevant subset equals full build
- rollback drill
- sync latency receipt

### Rollback

Atomic pointer to previous ACTIVE state.

---

## PHASE 11 — Permission-First Retrieval & Ask

### 목표

동일 최신 world state를 Human/AI가 evidence와 함께 질의한다.

### 구현

- query contract
- permission/time/authority filters
- hybrid retrieval
- embedding/reranker registry
- index version/pointer swap
- grounded answer schema
- evidence localization
- consumption lineage
- Ask UI
- Raw vs TAVONEL sample demo

### Tests

- cross-tenant zero result
- ACL revoke immediate
- as-of/known-at
- authority/applicability
- filtered ANN recall/exact fallback
- citation/source region
- unsupported claim/abstention
- partial workspace scope

### Exit gate

- end-to-end QA/citation corpus report
- no permission filter after ANN-only path
- every supported claim evidence-linked
- Ask clearly differs from generic chat

### Rollback

Disable answer generation; evidence-only search remains or current app path.

---

## PHASE 12 — Knowledge Health Scan & Product Core

### 목표

실제 telemetry를 고객이 이해하고 행동할 수 있는 진단으로 만든다.

### 구현

- finding aggregation
- source preview
- version/conflict/recovery/stale/permission findings
- inspection coverage/denominator
- conversion workflow
- account/workspace onboarding
- review/resolution actions
- product analytics

### Tests

- no invented finding
- uninspected dimension not 100
- evidence click opens exact source
- impact preview
- compile CTA coherent
- customer data isolation

### Exit gate

- sample and real test workspace에서 유의미한 finding
- finding→evidence→resolution path
- Time to First Finding measured
- pilot workflow start possible

### Rollback

Health Scan is read-only; disable public activation if findings unreliable.

---

## PHASE 13 — Cinematic Landing & Product Visualization

### 목표

TAVONEL을 90초 안에 설명하지 않고 체험시키며 실제 app으로 이어간다.

### 구현

- MESS→YOUR TURN scenes
- deterministic sample event stream
- real event projection
- 3 WOW moments
- Ask/world/source zoom
- evidence scene
- upload/connect activation
- design system
- reduced motion/mobile/WebGL fallback
- claim pack renderer

### Tests

- visual regression
- desktop/mobile/tablet
- keyboard/screen reader
- reduced motion
- WebGL context loss
- Core Web Vitals
- no trade-secret payload
- copy/claim validation
- user comprehension test

### Exit gate

- 5s thesis, 15s mechanism, 30s difference, 60s trust, 90s action
- body copy 없이 change→impact→recompile 이해
- app activation same visual language
- generic AI cliché absent

### Rollback

Static semantic fallback landing remains deployable.

---

## PHASE 14 — Connectors, Public API, CLI, Webhooks & SDK

### 목표

고객이 파일을 옮기지 않고 연결하고, 시스템이 지속적으로 sync되게 한다.

### 구현 순서

1. Core API stabilization
2. CLI/resumable folder ingest
3. Google Drive
4. S3/R2-compatible
5. GCS
6. OneDrive/SharePoint
7. webhooks
8. Python/TS SDK

### Tests

- connector cursor crash/replay
- watch/subscription expiration
- missed notification reconciliation
- ACL grant/revoke
- API idempotency
- SSE resume
- webhook signature/replay/DLQ
- CLI crash/resume
- SDK compatibility

### Exit gate

- one production connector continuous sync
- ACL revoke invariant
- CLI/API use same core path
- webhook delivery/replay visibility

### Rollback

Pause connector, preserve cursor, fall back to manual sync/upload.

---

## PHASE 15 — Read-Only MCP

### 목표

Claude/other agents가 governed world state를 표준 interface로 읽게 한다.

### 구현

- MCP Streamable HTTP
- OAuth 2.1 resource server
- Protected Resource Metadata
- tools/resources
- scopes/audience binding
- audit/consumption lineage
- capability version
- rate limits

### Tests

- token audience/issuer/resource
- no token passthrough
- cross-tenant/tool scopes
- malformed tool input
- output sanitization
- permission/time/authority
- client compatibility

### Exit gate

- read-only only
- security review
- API/MCP result equivalence
- consumption lineage complete

### Rollback

Disable MCP endpoint without affecting API/Ask.

---

## PHASE 16 — Billing, Paid Pilot & GTM System

### 목표

Evidence 기반 제품을 실제 유료 workflow로 닫는다.

### 구현

- internal usage ledger
- cost reconciliation
- credits/pricing version
- Stripe meter adapter
- spend alerts/caps
- pilot onboarding
- weekly outcome report
- claim permission workflow
- Gracian/profile/product bridge

### Tests

- duplicate meter event
- invoice reconciliation
- failed job billing
- refunds/credits
- quota override
- pilot baseline vs outcome
- claim permission/withdrawal

### Exit gate

- one narrow paid pilot operable from Health Scan to continuous sync
- customer-visible usage bounded/reconciled
- contribution margin known
- no unsupported customer claim

### Rollback

Manual invoice/credit ledger; billing adapter disabled.

---

## PHASE 17 — Enterprise Hardening & Research Publication

### 목표

paid demand에 필요한 보안·운영·competitive evidence를 강화한다.

### 구현

- OIDC/SSO path
- RBAC/ABAC hardening
- retention/deletion
- audit export
- backup restore drill
- incident runbooks
- same-condition competitor benchmark
- DART/SEC methodology publication
- supply-chain attestations

### Exit gate

- restore drill receipt
- tenant/security fixture clean
- enterprise security page accurate
- publication passes IP/claim gate

---

## PHASE 18 — Decision Replay, Governed Write MCP & Simulation — GATED

### 진입 조건

- paid customer demand
- read MCP proven
- write authorization/approval/audit/rollback
- stable temporal world state
- patent/IP review

### 후보

- decision replay
- controlled source ingest/recompile tools
- what-if impact simulation
- governed actions

### 금지

초기 launch를 위해 이 Phase를 선행하지 않는다.

---

# PART 22 — SOLO-FOUNDER CRITICAL PATH

## 22.1 반드시 먼저

```text
Baseline/Contracts
→ Ingest
→ Profiler/Registry
→ Execution/Recovery
→ Benchmark OS
→ Protected Core live path
→ World State
→ Health Scan/Ask
→ Cinematic Landing
→ One connector/API
→ Pilot
```

## 22.2 나중에

- broad connector matrix
- SSO/SCIM
- write MCP
- Decision Replay
- simulation
- multiple vertical-specific products

## 22.3 Stop-the-line conditions

다음이면 새 기능을 중단하고 해결한다.

- cross-tenant leak
- unsupported claim published
- source/evidence hash mismatch
- world-state partial publish
- permission revoke delay beyond SLO
- runaway GPU/API spend
- historical evidence overwritten
- unlicensed model/component production use
- catastrophic benchmark regression


---

# PART 23 — FMEA / POTENTIAL TECHNICAL ISSUES & REMEDIATION REGISTER

아래 표는 launch 전 최소 검토 목록이다. `S`는 severity(1–5), `L`은 초기 likelihood(1–5)이며 실제 incident/benchmark 데이터로 재평가한다. 표의 대응은 코드·테스트·runbook으로 연결되지 않으면 완료가 아니다.

| ID | 영역 | 위험/증상 | 근본 원인 | 영향 | 예방 설계 | 탐지 | 복구 |
|---|---|---|---|---|---|---|---|
| ING-01 | Ingestion | 브라우저가 대량 파일에서 멈춤 | 개별 progress를 매 frame 렌더링하거나 main thread에서 hash | 업로드 UX 이탈 | Web Worker, aggregate counters, virtualized rows | Long Task/INP, memory telemetry | 동시성 축소, worker resume, static fallback |
| ING-02 | Ingestion | 대용량 파일 재업로드 반복 | single PUT, resume state 없음 | 시간/대역폭 낭비 | R2 multipart + IndexedDB/CLI checkpoint | part receipt reconciliation | uploaded parts 조회 후 이어받기 |
| ING-03 | Ingestion | multipart part 수 10,000 초과 | 고정된 작은 part size | 업로드 실패 | object size 기반 adaptive part sizing | session creation validation | 새 session/큰 part로 재개 |
| ING-04 | Ingestion | 완료된 object가 손상 | part/checksum/complete race | 잘못된 source truth | part checksum + final SHA-256 + HEAD | hash mismatch | quarantine, affected parts 재업로드 |
| ING-05 | Ingestion | abandoned multipart 비용 누적 | 브라우저 종료/complete 미호출 | R2 operation/storage 비용 | expiry/lifecycle/abort reconciler | age inventory | AbortMultipartUpload |
| ING-06 | Ingestion | 압축폭탄/파일폭탄 | compressed size만 신뢰 | DoS/비용 폭증 | depth/count/expanded-byte budget | sandbox counters | kill/quarantine/reject |
| ING-07 | Ingestion | MIME 위장 | client Content-Type 신뢰 | parser exploit | magic bytes + independent detector | extension/MIME mismatch finding | quarantine |
| ING-08 | Ingestion | password PDF가 무한 실패 | encrypted state 분류 없음 | retry 비용 | preflight encryption detection | repeated provider errors | NEEDS_PASSWORD terminal |
| ING-09 | Ingestion | GPU가 upload를 기다림 | pod를 upload 전에 provision | idle cost | object/queue buffer, threshold provision | GPU idle span | terminate/reconcile pod |
| ING-10 | Ingestion | queue backlog 무제한 | admission/backpressure 없음 | SLO/비용 붕괴 | tenant quota, backlog cap, spend cap | queue age/backlog | pause admission, batch/priority drain |
| ING-11 | Ingestion | 정상 빈 페이지를 parser failure로 판정 | empty output만 검사 | false recovery/비용 | source-aware blank detector | near-white/native-text fixture | reclassify BLANK_SOURCE |
| ING-12 | Ingestion | 파일명에서 tenant/개인정보 노출 | object key에 raw filename | privacy leak | opaque IDs, encrypted metadata | object inventory scan | rename/migrate keys, rotate links |
| CON-01 | Connector | Drive watch channel 만료 | renewal 없음 | 변경 누락 | expiration scheduler + periodic delta crawl | expiry alert/cursor lag | renew + gap reconciliation |
| CON-02 | Connector | notification 유실 | webhook을 truth로 간주 | stale world | notification is hint, durable delta cursor | periodic reconciliation | full/delta resync |
| CON-03 | Connector | ACL revoke가 늦게 반영 | background compile 뒤 permission 적용 | data exposure | immediate deny overlay | revocation latency metric | block retrieval, cleanup async |
| CON-04 | Connector | cursor를 너무 일찍 commit | change apply 전 checkpoint | 영구 누락 | apply transaction 후 cursor commit | cursor/apply receipt mismatch | rewind checkpoint/resync |
| CON-05 | Connector | 중복/out-of-order event | exactly-once/order 가정 | 중복 version/잘못된 delete | event id/version/sequencer idempotency | inbox duplicates | ignore/reconcile current provider state |
| CON-06 | Connector | Google-native export 변화 | provider export format 비고정 | 결과 drift | raw provider revision + export settings/version receipt | reproducibility diff | pin/alternate export/rebaseline |
| CON-07 | Connector | S3 multipart ETag를 MD5로 오인 | provider semantics 오해 | 잘못된 dedup | canonical SHA-256 별도 | hash inconsistency | rehash/migrate identity |
| CON-08 | Connector | token revoked/expired | refresh/re-auth workflow 없음 | sync 중단 | secret manager + REAUTH_REQUIRED state | 401/refresh failure | pause, customer reauth, cursor preserve |
| CON-09 | Connector | Shared Drive/SharePoint inheritance 오해 | simple owner ACL만 수집 | 권한 오류 | provider-specific ACL snapshot/inheritance | permission fixtures | deny conservative, review |
| CON-10 | Connector | full resync가 중복 world를 생성 | revision/idempotency 없음 | 비용/identity fork | provider item ID + revision graph | duplicate source versions | dedup/relink, reject duplicate publish |
| QUE-01 | Queue/Runtime | duplicate queue delivery로 중복 side effect | at-least-once 미대응 | 이중 비용/중복 publish | outbox/inbox + idempotency key | duplicate event metrics | return prior receipt |
| QUE-02 | Queue/Runtime | worker output 후 ACK 전에 죽음 | commit 순서 오류 | 재실행/비용 | R2-before-ACK + DB receipt | R2/DB reconciler | repair receipt, dedup retry |
| QUE-03 | Queue/Runtime | lease split-brain | clock/heartbeat/ownership 검증 부족 | 동시 처리 | lease token/fencing number | two owners metric | older fencing writes reject |
| QUE-04 | Queue/Runtime | 모든 pod 동시 정지 | account balance/provider incident | capacity 0 | correlated-failure circuit breaker/balance alert | timestamp cluster | admission pause, alternate lane |
| QUE-05 | Queue/Runtime | watchdog가 active worker 삭제 | liveness probe 부재/오래된 deadline | 작업 손실 | lease-aware current-address probe | delete while heartbeat | disable watchdog, resume from durable artifacts |
| QUE-06 | Queue/Runtime | container restart 후 모델/CLI 없음 | ephemeral disk 의존 | bootstrap 실패 | immutable image/network-volume cache/startup probe | healthcheck | rebuild/bootstrap, block ready |
| QUE-07 | Queue/Runtime | network volume corruption | concurrent mutable writes | model/artifact 손상 | content-addressed paths, immutable model cache, single writer | hash verification | quarantine cache/repopulate |
| QUE-08 | Queue/Runtime | OOM retry loop | same batch/settings 반복 | 비용 폭주 | OOM classification, batch/resolution reduction | OOM rate by route | split batch/larger GPU/fail closed |
| QUE-09 | Queue/Runtime | cold start p99 폭증 | min worker 0/model load | poor UX | warm pool only for interactive, residency scheduling | cold-start spans | route to warm/return range ETA |
| QUE-10 | Queue/Runtime | idle GPU leak | job completion과 resource teardown 분리 | 마진 붕괴 | external resource reconciler/idle timeout | GPU active no lease | terminate and incident receipt |
| MOD-01 | Model/Router | 모델 이름만 보고 vision 처리 | provider naming 혼동 | route failure | capability_evidence/input_modalities registry gate | capability probe failure | block model, correct registry |
| MOD-02 | Model/Router | 최신 모델 자동 champion | marketing score 신뢰 | regression | shadow/same-condition benchmark/canary | slice no-regression | champion pointer rollback |
| MOD-03 | Model/Router | Paddle/Mistral 등 다른 benchmark 직접 비교 | dataset/evaluator 차이 | 허위 claim | same corpus/evaluator run | claims validator | retract/conditional claim |
| MOD-04 | Model/Router | frontier model을 truth oracle로 취급 | 브랜드 신뢰 과잉 | 고신뢰 오답 | source correspondence + independent checks | verifier disagreement/source failure | review/fail closed |
| MOD-05 | Model/Router | same model retry 남발 | operational/semantic 미분류 | 비용 낭비 | failure-class-aware retry budget | byte-identical retry yield | skip to alternate family |
| MOD-06 | Model/Router | alternate model도 같은 failure | correlated family/prompt/data | 거짓 consensus | family/provider lineage + correlation penalty | same wrong answer rate | source verification/human |
| MOD-07 | Model/Router | uncalibrated scalar quality route | blind detector 실패 무시 | false escalation/miss | explicit findings + outcome map | named-corpus calibration state | shadow only/abstain |
| MOD-08 | Model/Router | Router가 비용만 최적화 | trust constraint 약함 | 저가 오답 | hard trust/risk constraints | constraint violation | policy rollback, reprocess |
| MOD-09 | Model/Router | Router가 품질만 최적화 | frontier 과호출 | 마진 붕괴 | expected incremental gain/cost caps | frontier fraction/cost | budget stop/cheaper challenger |
| MOD-10 | Model/Router | price 변경이 과거 route 재현을 깨뜨림 | live price만 저장 | receipt 불완전 | price snapshot/effective_at | missing snapshot | freeze snapshot/recompute estimate separately |
| MOD-11 | Model/Router | provider retention 정책과 tenant 계약 충돌 | data policy filter 없음 | 법적/보안 위험 | registry data policy + workspace allowlist | blocked candidate audit | reroute self-hosted/fail closed |
| MOD-12 | Model/Router | structured JSON 유효하지만 의미 누락 | schema만 검사 | silent failure | source/coverage/semantic invariants | missing region finding | alternate/review |
| MOD-13 | Model/Router | multipage prompt 반복/루프 | model/prompt limitation | garbled output | page/window limits, repetition detector | n-gram/output anomaly | split/re-prompt/alternate model |
| MOD-14 | Model/Router | nested/merged table 붕괴 | model capability mismatch | financial error | table specialist + cell evidence | table invariants/numeric conflict | rerender/alternate/review |
| MOD-15 | Model/Router | online exploration이 고객 output에 영향 | bandit experimentation | 품질/신뢰 위험 | offline/shadow only, explicit experiment cohort | experiment flag audit | disable, reprocess with champion |
| IR-01 | Knowledge Core | false entity/unit merge | threshold/assignment 공격적 | 역사 오염 | conservative threshold, one-to-one, abstain | merge audit/gold fixtures | reversible split + world rebuild |
| IR-02 | Knowledge Core | false split 과다 | 너무 보수적 | 중복 지식 | reviewable split candidates | duplicate clusters | human merge with provenance |
| IR-03 | Knowledge Core | missing signal을 0 처리 | 모델링 오류 | merge 불가능/왜곡 | renormalize + missing reason | feature audit | schema migration/recalculate |
| IR-04 | Knowledge Core | bbox를 추정해 생성 | parser 좌표 없음 | 가짜 provenance | COORDINATE_UNAVAILABLE | coordinate/source bounds test | remove fabricated evidence/recompile |
| IR-05 | Knowledge Core | generated summary를 source evidence로 사용 | lineage 혼동 | unsupported claim | original evidence type gate | evidence chain validator | downgrade claim/retrieve original |
| IR-06 | Knowledge Core | latest wins authority | scope/contract/time 무시 | 잘못된 정책 | resolver DSL + applicability | controlled policy fixtures | conflict/review |
| IR-07 | Knowledge Core | valid time와 known time 혼합 | single timestamp | decision replay 오류 | bitemporal schema/query | as-of/known-at tests | backfill/unknown state |
| IR-08 | Knowledge Core | Office XML만 신뢰 | visual relation 손실 | 표/슬라이드 오류 | native + visual dual path | reconciliation fixtures | render/reconcile/review |
| IR-09 | Knowledge Core | visual render만 신뢰 | hidden/formula/metadata 손실 | 의미 누락 | native + visual dual path | hidden/formula tests | native extraction/reconcile |
| IR-10 | Knowledge Core | fixed-token chunking | clause/exception 분리 | RAG 오답 | structure-aware chunker | boundary fixtures | rebuild consumer chunks |
| IR-11 | Knowledge Core | dependency graph 폭발 | untyped edges/cycles | recompile storm | typed propagation/SCC/budgets | fanout/impact size alert | truncate as incomplete/review |
| IR-12 | Knowledge Core | impact false negative | edge/matching 누락 | stale knowledge publish | critical recall gate/full-build equivalence | mutation benchmark | block publish/full rebuild |
| IR-13 | Knowledge Core | partial world state active | pointer swap before validate | Agent inconsistent | staging + atomic pointer | two ACTIVE/incomplete manifest check | rollback pointer |
| IR-14 | Knowledge Core | source deletion but derived remains searchable | cascade/deny 부족 | privacy leak | tombstone immediate deny + purge workflow | deletion audit | block retrieval/purge/rebuild |
| RET-01 | Retrieval/API | ANN 후 permission filter | approximate under-return/leak risk | wrong/missing results | permission/time filters first + iterative/exact fallback | cross-tenant/recall benchmark | disable index/exact path |
| RET-02 | Retrieval/API | embedding versions 혼합 | upgrade in place | ranking drift | versioned shadow index/pointer | mixed-version query check | rollback index pointer |
| RET-03 | Retrieval/API | citation이 답을 지지하지 않음 | retrieval citation만 붙임 | trust loss | claim-level evidence validation | citation entailment/evidence localization | abstain/repair answer |
| RET-04 | Retrieval/API | partial compilation 답이 완전한 척함 | scope metadata 누락 | 오해 | coverage scope in answer | incomplete state test | label/disable answer |
| RET-05 | Retrieval/API | API mutation 중복 | idempotency 없음 | 이중 ingest/billing | Idempotency-Key + body hash | duplicate request metric | replay prior result |
| RET-06 | Retrieval/API | SSE reconnect 시 event 누락 | resume cursor 없음 | UI 잘못된 상태 | Last-Event-ID/projection sequence | gap detection | snapshot + resume |
| RET-07 | Retrieval/API | webhook replay/forge | signature/timestamp 없음 | customer side effects | HMAC/timestamp/replay cache | invalid signature/replay count | rotate secret/disable endpoint |
| RET-08 | Retrieval/API | MCP token passthrough | downstream token 재사용 | 권한 침해 | resource server/audience binding/no passthrough | token audit tests | revoke/incident response |
| RET-09 | Retrieval/API | MCP tool scope 과다 | one broad scope | data exposure | tool-level scopes/workspace binding | authorization audit | disable tool/reissue token |
| RET-10 | Retrieval/API | write MCP 조기 공개 | approval/rollback 없음 | 파괴적 변경 | read-only gate | tool inventory CI | remove write tools/rollback |
| WEB-01 | Website/Product | 시네마틱이 fake data처럼 보임 | backend event와 분리 | 신뢰 하락 | sample/real mode 명시, actual event projection | event-to-UI contract test | static truthful state |
| WEB-02 | Website/Product | WebGL로 LCP/INP 악화 | hero 즉시 mount/과도 asset | 이탈/SEO | lazy canvas, adaptive DPR, semantic HTML first | CWV p75/long task | 2D/static fallback |
| WEB-03 | Website/Product | WebGL context loss로 화면 공백 | restore handler 없음 | 사용 불가 | contextlost/restored + fallback | client error telemetry | remount/static scene |
| WEB-04 | Website/Product | 모바일에서 desktop 3D 축소 | interaction/성능 부적합 | 나쁜 UX | intentional mobile 2D narrative | device visual tests | serve reduced experience |
| WEB-05 | Website/Product | reduced-motion 무시 | 모션 강제 | 접근성/신체 반응 | prefers-reduced-motion static states | a11y test | disable motion |
| WEB-06 | Website/Product | generic chatbot처럼 보임 | 첫 화면 chat box | wrapper 인식 | Ask after compiled world, evidence-rich UI | user comprehension test | reorder narrative |
| WEB-07 | Website/Product | Health Score가 허구 | 검사 안 한 항목 포함 | 신뢰/법적 위험 | finding-first, denominator/coverage | claims/data provenance test | remove score/recompute |
| WEB-08 | Website/Product | trade secret가 client bundle에 포함 | internal receipt serializing | IP 유출 | public DTO/view separation | bundle/network secret scan | rotate/remove/redeploy |
| SEC-01 | Security/Ops | 문서 prompt injection이 tool/policy 제어 | content와 instruction 혼합 | 데이터/행동 위험 | models no tools, deterministic auth, labels | red-team corpus | quarantine/reprocess |
| SEC-02 | Security/Ops | RLS connection pool tenant context 잔존 | reset 누락 | cross-tenant leak | transaction-local setting/reset tests | cross-tenant canary | kill pool/incident |
| SEC-03 | Security/Ops | support/admin broad access | standing privilege | insider risk | JIT scoped access + audit | admin access review | revoke/investigate |
| SEC-04 | Security/Ops | presigned URL 장기/과범위 | TTL/key scope 부적절 | source leak | short TTL exact object/method | URL policy tests | revoke token/change key path |
| SEC-05 | Security/Ops | provider API에 금지 데이터 전송 | Router data policy 누락 | contract breach | candidate filter/data minimization | egress audit | stop/reprocess/self-hosted |
| SEC-06 | Security/Ops | 삭제 후 backup에 영구 잔존 | backup lifecycle 불명확 | privacy noncompliance | documented backup expiry/cryptographic erase strategy | deletion receipt audit | expire/rotate keys |
| SEC-07 | Security/Ops | unsigned/unpinned model image | supply-chain tamper | code/data compromise | SBOM/Cosign/SLSA/admission gate | signature verify CI | block/rollback image |
| SEC-08 | Security/Ops | missing restore drill | backup이 실제 복구 불가 | 장기 outage | scheduled isolated restore | RTO/RPO receipt | fix backup/runbook |
| BIL-01 | Billing/FinOps | Stripe meter를 usage truth로 사용 | async/rejection | 청구 불일치 | internal append-only ledger | daily reconciliation | re-export/correction |
| BIL-02 | Billing/FinOps | failed/retried job 이중 청구 | attempt 기반 청구 | 고객 신뢰 하락 | billable outcome idempotency | usage receipt uniqueness | credit/reconcile |
| BIL-03 | Billing/FinOps | frontier 비용 runaway | tail gate/limit 없음 | 마진 붕괴 | tenant spend/frontier fraction caps | cost anomaly alert | circuit/open/manual approval |
| BIL-04 | Billing/FinOps | R2 small multipart operations 과다 | part size 너무 작음 | operation 비용 | adaptive part sizing/cost telemetry | Class A request rate | new sessions larger parts |
| GTM-01 | Claims/GTM | completion을 accuracy로 표현 | marketing 단순화 | 신뢰/법적 위험 | claim validator/forbidden phrases | CI copy scan | retract/correct |
| GTM-02 | Claims/GTM | 약점/negative result 삭제 | 성과 편향 | research credibility 하락 | append-only evidence/limitations | evidence auditor | restore/retire claim |
| GTM-03 | Claims/GTM | 출원 전 HOW 공개 | content/website oversharing | IP 상실 위험 | IP registry/publish approval | prepublish gate | remove content/legal review |
| GTM-04 | Claims/GTM | 제품 공개가 너무 늦음 | 콘텐츠와 제품 분리 | 유입 손실 | profile discovery + proof cadence | profile/CTA analytics | adjust bridge cadence |
| OPS-01 | Founder/Release | 한 Agent가 구현·검수·배포 승인 | confirmation bias | hidden defects | four-eyes agents + deterministic CI | release provenance | rollback/review |
| OPS-02 | Founder/Release | 한 번에 전면 rewrite | scope/verification 불가 | working core 파괴 | feature flags/phase checkpoints | diff size/green gates | revert phase commit |
| OPS-03 | Founder/Release | schema/model/runtime 동시 변경 | 원인 추적 불가 | incident 복잡 | one-axis canary/expand-contract | change correlation | rollback axis separately |
| OPS-04 | Founder/Release | 문서와 코드 drift | docs update gate 없음 | 다음 agent 방향 오류 | ADR/contracts/docs CI | gap matrix diff | update docs/block release |

## 23.1 FMEA 운영 규칙

1. 각 위험은 owner, test ID, alert, runbook, latest incident를 갖는다.
2. SEV0/SEV1 위험은 수동 체크리스트가 아니라 자동 gate가 기본이다.
3. incident가 발생하면 새 risk row 또는 기존 likelihood/severity를 갱신한다.
4. mitigation이 없는 위험은 release waiver와 만료일이 필요하다.
5. public limitation과 연결되는 위험은 claims pack에도 반영한다.

---

# PART 24 — REPOSITORY ARCHITECTURE, CI & RELEASE ENGINEERING

## 24.1 권장 repository logical structure

```text
tavonel/
├─ CLAUDE.md
├─ pyproject.toml
├─ package.json
├─ pnpm-workspace.yaml
├─ docker-compose.dev.yml
├─ docs/
│  ├─ north-star/
│  │  └─ TAVONEL_MASTERPLAN_v4.0.md
│  ├─ architecture/
│  │  ├─ source-ingestion.md
│  │  ├─ connector-control-plane.md
│  │  ├─ profiler.md
│  │  ├─ model-registry.md
│  │  ├─ economic-router.md
│  │  ├─ scheduler-runpod.md
│  │  ├─ inspection-recovery.md
│  │  ├─ canonical-ir.md
│  │  ├─ identity-authority-temporal.md
│  │  ├─ diff-impact-recompile.md
│  │  ├─ world-state.md
│  │  ├─ retrieval-ask.md
│  │  ├─ api-cli-mcp.md
│  │  ├─ security.md
│  │  ├─ observability-finops.md
│  │  └─ cinematic-product.md
│  ├─ adr/
│  ├─ audit/
│  ├─ evidence/
│  ├─ ip/
│  ├─ runbooks/
│  └─ design/
├─ apps/
│  ├─ web/
│  ├─ api/
│  └─ docs/
├─ services/
│  ├─ ingest/
│  ├─ connectors/
│  ├─ profiler/
│  ├─ registry/
│  ├─ planner/
│  ├─ router/
│  ├─ scheduler/
│  ├─ inspector/
│  ├─ recovery/
│  ├─ reconciler/
│  ├─ compiler/
│  ├─ identity/
│  ├─ knowledge_integrity/
│  ├─ lineage/
│  ├─ diff/
│  ├─ impact/
│  ├─ recompilation/
│  ├─ world_state/
│  ├─ retrieval/
│  ├─ answer/
│  ├─ health_scan/
│  ├─ review/
│  ├─ evidence/
│  └─ billing/
├─ workers/
│  ├─ runpod/
│  ├─ parsers/
│  ├─ renderer/
│  └─ connector_sync/
├─ packages/
│  ├─ schemas/
│  ├─ ir/
│  ├─ parser_adapters/
│  ├─ model_registry/
│  ├─ telemetry/
│  ├─ security/
│  ├─ api_client/
│  ├─ sdk_python/
│  ├─ sdk_typescript/
│  ├─ cli/
│  └─ ui/
├─ benchmarks/
│  ├─ public/
│  ├─ dart/
│  ├─ sec/
│  ├─ stress/
│  ├─ router/
│  ├─ failure/
│  ├─ semantic_preservation/
│  ├─ knowledge_integrity/
│  ├─ knowledge_evolution/
│  ├─ end_to_end/
│  └─ chaos/
├─ migrations/
├─ tests/
│  ├─ unit/
│  ├─ integration/
│  ├─ property/
│  ├─ contract/
│  ├─ security/
│  ├─ e2e/
│  ├─ visual/
│  └─ chaos/
├─ infra/
│  ├─ cloudflare/
│  ├─ runpod/
│  ├─ postgres/
│  ├─ supply-chain/
│  └─ monitoring/
└─ .claude/
   ├─ agents/
   ├─ skills/
   ├─ commands/
   └─ settings.json
```

기존 repository가 안정적이면 물리적 이동을 강제하지 않는다. module ownership, dependency direction, contract가 더 중요하다.

## 24.2 Dependency direction

```text
apps → public service interfaces
services → packages/contracts
workers → adapter contracts + services
packages/ir, schemas → lower-level only
protected core → no dependency on web/marketing/provider SDK
```

Provider SDK가 Canonical IR에 침투하지 않게 anti-corruption adapter를 둔다.

## 24.3 ADR mandatory decisions

- R2 as artifact truth
- PostgreSQL/RLS
- queue at-least-once/outbox-inbox
- modular monolith boundary
- model registry/capability gate
- router objective
- public/internal DTO split
- world state atomic publish
- read-only MCP
- website event projection
- evidence/claims governance

ADR에는 context, decision, alternatives, consequences, rollback, evidence를 포함한다.

## 24.4 CI stages

```text
1. format/lint
2. static typing
3. schema/codegen compatibility
4. unit/property tests
5. migration/RLS tests
6. contract/integration tests
7. targeted benchmark smoke
8. security/supply-chain
9. web unit/build
10. Playwright/visual/a11y
11. evidence/claim validator
12. container build/SBOM/sign
13. canary deploy
14. smoke/synthetic
15. release receipt
```

## 24.5 Python gate

- Ruff format/check
- mypy/pyright as selected and pinned
- pytest unit/integration/property
- coverage by critical module, not vanity global only
- mutation tests on authority/permission/impact rules where feasible

## 24.6 TypeScript gate

- ESLint
- `tsc --noEmit`
- Vitest
- schema generated-type drift
- dependency/bundle analysis
- Playwright

## 24.7 Database gate

- migration graph single head
- forward migration from prior release
- expand-contract compatibility
- RLS enabled/forced
- cross-tenant fixtures
- index plan regression for critical retrieval
- rollback strategy documented; destructive migration requires explicit approval

## 24.8 Router/recovery gate

Parser/router edit triggers:

- historical recovery fixtures
- named public smoke slices
- low-quality scan slice
- numeric/table slice
- same-model retry fixture
- route determinism
- cost estimate unit tests
- legacy vs v4 shadow diff

## 24.9 Knowledge gate

- IR schema round-trip
- stable ID property tests
- one-to-one assignment
- entity ambiguity
- authority/applicability
- valid/system time
- lineage integrity
- impact reason paths
- selective/full equivalence
- atomic world-state tests

## 24.10 API/MCP gate

- OpenAPI/type generation
- idempotency
- auth/scopes
- permission/time/authority
- webhook signature/replay
- MCP audience/resource binding
- no token passthrough
- read-only tool inventory

## 24.11 Web gate

- sample event story snapshots
- actual event projection contract
- desktop/mobile
- reduced-motion
- WebGL fallback/context loss
- keyboard/screen reader
- Core Web Vitals lab + real-user monitoring once deployed
- no secret/internal receipt in bundle/network

## 24.12 Marketing/evidence gate

- forbidden claims: `99% accurate`, `perfect`, `best`, `100%` without exact approved context
- completion/recovery denominator
- benchmark/evaluator/date
- low-quality scan limitation when relevant
- artifact hash exists
- claim status approved
- IP disclosure registry allows publication

## 24.13 Container/supply-chain gate

- pinned base image digest
- dependency lock
- SBOM
- vulnerability scan
- license scan
- Cosign sign/verify
- model weight hash
- startup probe
- no prod `latest`

## 24.14 Release strategy

```text
Dev
→ Preview
→ Shadow
→ Internal canary
→ 5% low-risk tenant cohort
→ 25%
→ 50%
→ 100%
```

각 단계에 automatic rollback threshold:

- error/cost/latency
- catastrophic failure
- permission/security
- world-state publish
- customer-visible regression

## 24.15 Release receipt

```yaml
release:
  release_id: rel_...
  git_sha: ...
  image_digests: [...]
  schema_version: ...
  model_registry_snapshot: ...
  route_policy: ...
  recovery_policy: ...
  tests: [...]
  benchmark_receipts: [...]
  known_limitations: [...]
  feature_flags: {...}
  rollback_to: rel_...
  approved_by: [implementer, reviewer, release_manager]
```

---

# PART 25 — AI-NATIVE SOLO-FOUNDER SOFTWARE FACTORY

## 25.1 Agent topology

```text
lead-orchestrator
├─ architecture-auditor          read-only first
├─ contract-schema-engineer
├─ ingestion-security
├─ connector-engineer
├─ profiler-registry
├─ router-runtime
├─ runpod-scheduler
├─ parser-recovery
├─ knowledge-integrity
├─ temporal-authority
├─ diff-impact-recompile
├─ retrieval-answer
├─ api-cli-mcp-security
├─ database-multitenancy
├─ frontend-product
├─ cinematic-director
├─ benchmark-scientist
├─ evidence-auditor
├─ ip-disclosure-auditor
├─ visual-qa-accessibility
├─ adversarial-reviewer
└─ release-manager
```

각 subagent는 독립 context, 최소 tool permission, 구체적 output contract를 가진다.

## 25.2 Four-eyes rule

```text
Implementer
→ deterministic CI
→ independent reviewer/skeptic
→ evidence/security reviewer
→ release manager
```

한 Agent가 구현과 최종 승인을 동시에 하지 않는다.

## 25.3 Claude Code permissions

- production secrets deny
- customer source deny unless explicit isolated task
- migrations/deploy approval gate
- destructive commands deny
- `.env`, keys, token files deny
- command hook input sanitization
- hooks execute with user permissions이므로 직접 검수
- `--dangerously-skip-permissions`를 production workspace default로 사용 금지

## 25.4 Hooks

- Python edit → Ruff/mypy/targeted pytest
- TS edit → ESLint/tsc/Vitest
- schema edit → codegen/compatibility
- migration edit → graph/RLS/expand-contract
- router edit → route fixture/benchmark smoke
- parser edit → failure/recovery slices
- IR/diff edit → property/equivalence
- API/MCP edit → auth/permission contract
- marketing copy edit → claims/IP validator
- 3D edit → screenshot/CWV/reduced-motion
- container build → SBOM/sign/verify

## 25.5 Task prompt contract

모든 Claude implementation task는 다음을 가진다.

```text
GOAL
SOURCE OF TRUTH
CURRENT PROVEN STATE
SCOPE
NON-GOALS
FILES/MODULES TO INSPECT
PROTECTED COMPONENTS
IMPLEMENTATION CONSTRAINTS
FAILURE MODES
ACCEPTANCE TESTS
SECURITY/TENANT TESTS
PERFORMANCE/COST BUDGET
VISUAL ACCEPTANCE (if UI)
EVIDENCE REQUIREMENTS
ROLLBACK
DONE DEFINITION
```

## 25.6 Phase workflow

```text
1. Read v4 relevant sections
2. Inspect code and baseline receipts
3. Produce phase gap report
4. Propose smallest coherent slice
5. Implement behind flag
6. Run deterministic checks
7. Run reviewer/adversarial agent
8. Generate evidence/phase receipt
9. Document rollback
10. Commit checkpoint
11. Continue only if gate passes
```

## 25.7 Context management

- root CLAUDE.md는 concise constitution
- detailed domain docs는 scoped skills
- codebase exploration은 read-only subagent
- benchmark logs/artifacts는 subagent summarization
- decisions는 ADR, conversation memory에 의존하지 않음
- phase report가 다음 세션 handoff

## 25.8 Agent output distrust

AI가 “완료했다”고 말하는 것은 evidence가 아니다.

완료 판정은:

- code exists
- deterministic tests
- benchmark/receipt
- independent review
- deployed smoke
- rollback

으로 한다.

## 25.9 Founder-only decisions

Claude가 묻거나 사용자 승인이 필요한 것:

- secrets/payment
- production/destructive action
- patent/legal/business truth
- customer data use/consent
- pricing/contract commitment
- irreversible provider/vendor commitment

이미 masterplan에서 결정된 library/algorithm은 반복 질문하지 않는다.

---

# PART 26 — TEST CATALOG

## 26.1 Representative tests

```text
test_upload_resume_does_not_repeat_completed_parts
test_upload_complete_is_idempotent
test_archive_bomb_is_quarantined
test_app_server_never_proxies_large_source_bytes
test_blank_source_is_not_parser_failure
test_nonblank_source_empty_output_is_catastrophic
test_profile_missing_signal_is_not_zero
test_unverified_vision_capability_cannot_route_images
test_blocked_license_model_cannot_enter_plan
test_same_registry_snapshot_routes_deterministically
test_operational_timeout_uses_same_model_retry
test_semantic_failure_skips_identical_retry_loop
test_high_risk_numeric_conflict_requires_verifier_or_review
test_route_budget_exhaustion_fails_closed
test_duplicate_queue_job_is_idempotent
test_worker_loss_after_r2_upload_repairs_receipt
test_worker_loss_before_r2_upload_retries_safely
test_stale_fencing_token_cannot_commit
test_provider_wide_stop_opens_circuit
test_runpod_resource_reconciler_terminates_idle_worker
test_cross_page_table_preserves_cell_provenance
test_office_dual_path_detects_visual_structural_mismatch
test_duplicate_rename_revision_branch_are_distinct
test_uncertain_entity_does_not_auto_merge
test_one_to_one_identity_assignment
test_customer_contract_overrides_global_policy_only_in_scope
test_unknown_effective_date_is_not_fabricated
test_as_of_and_known_at_are_independent
test_generated_summary_is_not_original_evidence
test_may_to_must_is_operational_change
test_reference_edge_does_not_always_invalidate
test_dependency_cycle_is_bounded
test_critical_impact_false_negative_blocks_publish
test_selective_compile_equals_full_build_relevant_subset
test_world_state_publish_is_atomic
test_world_state_rollback_restores_previous_active
test_acl_revoke_blocks_retrieval_before_reindex
test_cross_tenant_search_returns_nothing
test_filtered_ann_has_exact_fallback
test_embedding_versions_do_not_mix
test_answer_claims_are_supported_by_evidence
test_partial_workspace_answer_discloses_scope
test_sse_reconnect_resumes_without_gap
test_webhook_signature_and_replay_window
test_mcp_rejects_wrong_audience
test_mcp_never_passes_through_client_token
test_mcp_launch_tools_are_read_only
test_health_scan_finding_opens_exact_source
test_uninspected_health_dimension_is_not_scored_full
test_public_event_omits_route_trade_secrets
test_webgl_context_loss_falls_back
test_reduced_motion_story_remains_complete
test_claim_pack_rejects_missing_hash
test_completion_is_not_rendered_as_accuracy
test_failed_attempt_is_not_double_billed
test_usage_export_reconciles_with_internal_ledger
test_restore_drill_recovers_active_world_state
```

## 26.2 Property tests

- idempotent event handling
- stable serialization/hash
- identity assignment one-to-one
- split/merge reversibility
- world state single-active invariant
- permission monotonic deny on revoke
- selective/full equivalence
- public DTO subset of internal DTO

## 26.3 Performance tests

- upload concurrency/network profiles
- R2 part size cost
- profiler throughput
- model/GPU matrix
- queue backlog/cold start
- p50/p95/p99 route
- retrieval exact vs ANN filtered
- cinematic CPU/GPU/memory

## 26.4 Security tests

- path traversal
- archive bomb
- malicious PDF/OOXML
- prompt injection
- SSRF/external links
- cross-tenant IDs/cache
- API/MCP scope
- webhook replay
- secret/bundle scan
- supply-chain signature

---

# PART 27 — OPERATIONS RUNBOOK INDEX

```text
RUN-001 Upload session recovery
RUN-002 R2 multipart cleanup
RUN-003 Queue backlog and DLQ
RUN-004 RunPod worker/pod leak
RUN-005 Provider-wide GPU stop
RUN-006 Model rollback
RUN-007 Router policy rollback
RUN-008 Recovery regression
RUN-009 Connector cursor gap
RUN-010 ACL revoke emergency
RUN-011 World-state failed publish
RUN-012 World-state rollback
RUN-013 Cross-tenant/security incident
RUN-014 Source deletion request
RUN-015 Database restore
RUN-016 Evidence/claim correction
RUN-017 Billing reconciliation
RUN-018 Website/WebGL fallback incident
RUN-019 MCP credential incident
RUN-020 Supply-chain compromise
```

각 runbook:

- trigger
- severity
- first 5 minutes
- containment
- diagnosis
- recovery
- validation
- customer communication
- evidence preservation
- postmortem/action items

---

# PART 28 — FINAL PRODUCT & WEBSITE COPY CONTRACT

## 28.1 Hero

> **Your AI is only as reliable as the world it sees.**

> Compile fragmented organizational knowledge into trusted, temporal, traceable context.

## 28.2 Mechanism lines

> **Every page doesn't need the same AI.**

> **Failures shouldn't silently become knowledge.**

> **Don't give AI more documents. Give it a world it can understand.**

> **Finding information is easy. Knowing what is true now is harder.**

> **When one fact changes, don't rebuild the world.**

> **Every answer should have a way home.**

> **Your AI shouldn't work at yesterday's company.**

## 28.3 Activation

> **Now show us your world.**

> **See what your AI is actually seeing.**

## 28.4 Forbidden external phrases

- 99% accurate
- perfect OCR
- 100% reliable
- best-in-class without same-condition receipt
- zero hallucinations
- fully understands your company
- automatic truth
- no human review ever

---

# PART 29 — FINAL DEFINITION OF DONE

TAVONEL v4 launch candidate는 다음이 모두 사실일 때만 완료다.

## Architecture / product

1. Existing protected core and historical evidence are preserved.
2. Source bytes upload directly/resumably to object storage; app server does not proxy large payloads.
3. Secure preflight/quarantine handles supported formats and malicious fixtures.
4. Profiler and model registry are versioned, capability/license-gated and do not use a fake universal quality score.
5. V4 Router has shadow evidence, calibrated/explicit status, budget, abstention and rollback.
6. Operational failure and semantic/model failure take different recovery paths.
7. Every execution attempt has immutable input/output/model/policy/cost lineage.
8. Recovery and document reconciliation pass historical and new fixtures.
9. Canonical IR, evidence, stable identity, authority, applicability, temporal and permission rules operate on the production path.
10. Semantic diff → typed impact → selective recompile is proven against full rebuild on controlled corpora.
11. World-state publish/rollback is atomic; partial states are invisible.
12. Retrieval filters tenant/permission/time/authority before ranking.
13. Ask returns supported claims, evidence, conflict, applicability and world-state metadata.
14. Health Scan is generated from real telemetry, not invented AI scores.
15. One continuous connector and one CLI/API ingestion path are operable.
16. Read-only MCP passes authorization and consumption-lineage tests before release.

## Evidence / quality

17. Public benchmark results retain exact denominators/evaluator revisions/caveats.
18. DART/SEC real-world suite, stress suite and production golden framework exist.
19. Performance is reported as a vector and by document distribution.
20. Critical numeric fidelity and semantic preservation have named tests.
21. Router/model comparison includes quality, catastrophic failures, latency and cost.
22. End-to-end same-model Raw vs Basic RAG vs TAVONEL experiment exists before major performance claims.
23. Negative results and limitations are public where claims require them.
24. Every public claim is claim-pack generated and hash-bound.

## Security / operations

25. Uploaded documents are untrusted; parser/semantic workers have no broad tools/network/credentials.
26. Cross-tenant/RLS/security fixtures leak nothing.
27. Permission revocation blocks retrieval before background recompilation.
28. Connector tokens/secrets are scoped, encrypted and auditable.
29. Model/container/code supply-chain pins, SBOM and signatures are verified.
30. Deletion, retention, backup and restore drill are tested.
31. p50/p95/p99, queue age, cost, route, recovery and world-sync metrics exist.
32. RunPod/provider-wide stop, worker loss and cost leak runbooks are tested.
33. Internal usage ledger reconciles with billing provider and prevents double billing.

## Website / conversion

34. Landing communicates MESS→RECOVER→WORLD→CHANGE→ASK without relying on long body copy.
35. The three WOW moments are product-meaningful, not decorative.
36. Ask is not presented as a generic chatbot.
37. Sample animation is clearly sample; actual app uses real event projection.
38. Mobile, reduced-motion, accessibility, WebGL fallback and performance budgets pass.
39. Evidence and Security pages are accurate; nonexistent certifications are absent.
40. Knowledge Health Scan leads to a coherent compile/continuous-sync workflow.
41. At least one narrow paid pilot path is operational and unit economics are measured.

## AI-native implementation

42. One Agent does not implement and approve the same production-critical change.
43. Every Phase has checkpoint, ADR, tests, evidence and rollback.
44. Claude Code does not receive uncontrolled production secrets or destructive permissions.
45. Known gaps remain explicit; “done” is not asserted from prose alone.

> **TAVONEL is complete only when it can prove not merely that it produced output, but that the knowledge it published is traceable, current, permission-correct, recoverable, economically bounded, and safe for humans and AI agents to consume.**

---

# PART 30 — LAUNCH GATES

## Gate A — Internal Alpha

- Phase 0–10 complete
- secure upload to active world state
- protected core evidence clean
- no public customer data

## Gate B — Design Partner

- Ask/Health Scan
- one connector or CLI
- explicit limitations
- manual review/support acceptable
- billing manual/internal ledger

## Gate C — Paid Pilot

- bounded corpus/workflow
- source permissions
- pilot success contract
- usage/cost controls
- incident/rollback
- evidence/customer claim consent

## Gate D — Public Self-Serve

- resumable upload hardening
- automated billing/support
- deletion/retention
- reliability capacity
- public evidence/security
- abuse controls
- product onboarding

엔터프라이즈 기능 전체가 없어도 design partner/pilot은 가능하지만, 없는 기능을 있다고 판매하지 않는다.

---

# PART 31 — FINAL AUTONOMOUS CLAUDE CODE COMMAND v4.0

아래 명령은 이전 v1/v2/v3 implementation command를 대체한다.

```text
You are the lead implementation orchestrator for TAVONEL v4.0.

SOURCE OF TRUTH
Read TAVONEL_ULTIMATE_PRODUCTION_RESEARCH_IMPLEMENTATION_MASTERPLAN_v4.0_FINAL_KO_2026-08-10.md in full before changing code.
This v4 document supersedes conflicting prior architecture and phase instructions.
Historical evidence, benchmark artifacts, hashes, and FOLYNTA labels are immutable.
Use v31-phase-gap-matrix.md as the current-state baseline, not as future architecture.

MISSION
Migrate the current repository to TAVONEL v4 through dependency-aware, evidence-gated phases.
Do not perform a monolithic rewrite. Preserve the verified protected core and replace front/back surfaces behind compatibility contracts, feature flags, shadow execution, canaries, and rollback pointers.

PROTECTED CORE
Do not replace without a same-condition no-regression benchmark:
- akc_cir.inspection
- akc_cir.recovery_policy
- akc_cir.reconciler
- akc_cir.identity
- existing entity/authority/temporal logic where tested
- akc_cir.semantic_diff
- akc_cir.dependency
- akc_cir.recompilation
- akc_cir.world_state
- all evidence artifacts and claim receipts

FIRST ACTIONS — NO FEATURE CODING
1. Inspect the complete repository, git state, active deployments, migrations, CI, evidence, models, frontend, secrets references and current infrastructure.
2. Run all existing tests, linters, builds and non-destructive benchmark smoke checks.
3. Verify all historical artifact hashes. Never rewrite evidence.
4. Create/update:
   - docs/audit/V4_BASELINE_RECEIPT.md
   - docs/audit/V4_MIGRATION_MATRIX.md
   - docs/audit/V4_LICENSE_AND_SUPPLY_CHAIN.md
   - docs/ip/V4_DISCLOSURE_REGISTRY.yaml
   - concise root CLAUDE.md
5. Classify each requirement as PROVEN / IMPLEMENTED_NOT_PROVEN / PARTIAL / MISSING / CONFLICTING / BLOCKED_LICENSE / DEFERRED.
6. Commit/tag a clean v3.1 baseline checkpoint.
7. Implement Phase 1 contracts only after Phase 0 exits cleanly.

PHASE ORDER
0 Baseline/IP/Supply Chain
1 Contracts/Event Schemas/Compatibility
2 Secure Industrial Ingestion
3 Reference Renderer/Profiler/Model Registry
4 Execution Planner/V4 Shadow Router
5 Parser Adapters/Scheduler/RunPod Commit
6 Inspector/Recovery/Review Integration
7 Benchmark OS/Performance Map
8 Protected Compiler Core Production Integration
9 Entity/Authority/Applicability/Temporal/Epistemic
10 Diff/Impact/Recompile/Atomic World State
11 Permission-First Retrieval/Ask
12 Knowledge Health Scan/Product Core
13 Cinematic Landing/Product Visualization
14 Connectors/API/CLI/Webhooks/SDK
15 Read-Only MCP
16 Billing/Paid Pilot/GTM
17 Enterprise Hardening/Research
18 Decision Replay/Write MCP only when gated demand exists

OPERATING RULES
- R2 is immutable artifact truth; PostgreSQL is workflow, identity, permission and publish truth.
- Queue delivery is at-least-once. Every consumer must be idempotent.
- A worker may ACK only after output is durable and a receipt is committed.
- Treat every document as hostile data. Parsing models receive no tools, broad credentials or outbound network.
- Do not use a scalar blind quality score to route pages.
- Separate operational failure from semantic/model failure.
- Never infer multimodal capability from a product/model name; require registry capability evidence.
- Start V4 Router in shadow mode and roll out 0→5→25→50→100 only through gates.
- Optimize Minimum Cost to Trusted Output, not cheapest output or highest average benchmark alone.
- Never publish knowledge without evidence, permission, temporal, authority/applicability and integrity checks required by workspace policy.
- Never fabricate bbox, dates, identity, authority, confidence or sources.
- Never auto-resolve authoritative conflict when evidence is insufficient.
- Never expose intermediate/partial world state as ACTIVE.
- Never allow ACL revoke to wait for a background reindex.
- Never expose write MCP before read-only auth, scopes, audit, approval, idempotency and rollback are proven.
- Never publish unsupported marketing claims.
- Never expose internal route features, scores, thresholds, prompts, cost matrix or Router Outcome Dataset in public DTOs or client bundles.
- Do not add Kubernetes, Kafka, Neo4j or a custom foundation model without a measured bottleneck and ADR.

AI-NATIVE QUALITY RULE
An implementation agent cannot approve its own production-critical work.
For every phase:
Implementer → deterministic CI → independent reviewer/adversarial agent → evidence/security auditor → release manager.

PHASE COMPLETION CONTRACT
A phase is complete only when:
- code exists,
- tests and failure paths pass,
- telemetry exists,
- security/tenant checks pass,
- benchmark/evidence is produced where relevant,
- docs/ADR are updated,
- rollback is tested/documented,
- the phase report names remaining gaps,
- the repository is green.

AUTONOMY
Continue autonomously between non-destructive phases only when the exit gate passes.
Ask the user only for missing secrets/payment, legal/business truth, patent/publication decisions, customer-data consent, or irreversible production/destructive actions.
Do not repeatedly ask for technical choices already decided in the v4 source of truth.

FINAL REPORT
At the end, produce:
- requirement-by-requirement status,
- test/benchmark/evidence receipts,
- deployment and rollback state,
- current unit economics,
- known limitations,
- blocked legal/external items,
- paid-pilot readiness,
- explicit statement of anything not completed.
Do not claim completion from code presence alone.
```

---

# APPENDIX A — KEY CONTRACT EXAMPLES

## A.1 Page profile

```json
{
  "profile_id": "pf_...",
  "document_version_id": "dv_...",
  "page": 47,
  "schema_version": "4.0.0",
  "renderer": {"id":"pdfium","version":"...","dpi":180,"render_sha256":"..."},
  "features": {
    "native_text_ratio": {"value":0.02,"state":"PRESENT"},
    "table_density": {"value":0.71,"state":"PRESENT"},
    "merged_cell_cues": {"value":true,"state":"PRESENT"},
    "explicit_clause_id": {"value":null,"state":"MISSING_NOT_APPLICABLE","reason":"not_clause_document"}
  },
  "risk_class": "HIGH",
  "created_at": "..."
}
```

## A.2 Finding

```json
{
  "finding_id": "fd_...",
  "attempt_id": "att_...",
  "code": "NUMERIC_CONFLICT",
  "severity": "CRITICAL",
  "source_regions": ["ev_1"],
  "observations": [
    {"candidate":"A","value":"1,205"},
    {"candidate":"B","value":"1,250"}
  ],
  "recommended_actions": ["INDEPENDENT_VERIFIER","HUMAN_REVIEW"]
}
```

## A.3 Health finding

```json
{
  "finding_id":"khf_...",
  "category":"VERSION_CONFLICT",
  "title":"Three active-looking warranty sources disagree",
  "coverage":{"documents_inspected":83,"documents_total":83},
  "evidence_ids":["ev_..."],
  "potential_ai_risk":"Potentially conflicting answers",
  "impact_preview":{"knowledge_units":7,"agent_contexts":2},
  "claim_state":"MEASURED"
}
```

---

# APPENDIX B — ENVIRONMENT / SECRET INVENTORY

```text
DATABASE_URL
R2_ACCOUNT_ID
R2_BUCKET_SOURCE
R2_BUCKET_DERIVED
R2_ACCESS_KEY_ID
R2_SECRET_ACCESS_KEY
CLOUDFLARE_QUEUE_* bindings
RUNPOD_API_KEY
RUNPOD_ENDPOINT_* registry refs
OIDC_* / auth provider
GOOGLE_DRIVE_OAUTH_*
GCS_SERVICE_ACCOUNT_REF
MICROSOFT_GRAPH_OAUTH_*
STRIPE_SECRET_KEY
STRIPE_WEBHOOK_SECRET
OTEL_EXPORTER_*
SIGNING_KEY_REF / COSIGN policy
```

원칙:

- `.env.example`에는 이름/설명만
- production value는 managed secret store
- subagent/CI 최소 scope
- secret rotation/runbook
- log redaction test

---

# APPENDIX C — INTERNAL METRIC DEFINITIONS

```text
Output Completion = outputs produced / offered documents
Recovery Rate = recovered / recovery-required documents
Successful Page Cost = total relevant compute/API cost / pages meeting terminal success criteria
Recovered Page Cost = incremental recovery lane cost / incrementally recovered pages
Trusted Knowledge Yield = units promoted to required trust tier / eligible input units
Recompile Reduction = 1 - recompiled eligible units / total eligible units
World Sync Latency = ACTIVE world state time - source change observed time
Stale Exposure Window = permission/knowledge unsafe end - change observed
Router Oracle Regret = selected path loss - best permitted path loss
```

각 metric은 denominator, corpus, time window, exclusions, version을 가진다.

---

# APPENDIX D — OFFICIAL RESEARCH & IMPLEMENTATION SOURCE LEDGER

> 아래는 2026-08-10 기준 공식/1차 자료다. 실제 구현 시작/모델 promotion/가격 claim 직전에 다시 확인하고 registry/lockfile/receipt에 pin한다.

## Cloudflare R2 / Queues

- R2 overview: `https://developers.cloudflare.com/r2/`
- R2 presigned URLs: `https://developers.cloudflare.com/r2/api/s3/presigned-urls/`
- R2 multipart/upload: `https://developers.cloudflare.com/r2/objects/upload-objects/`
- R2 pricing: `https://developers.cloudflare.com/r2/pricing/`
- R2 event notifications: `https://developers.cloudflare.com/r2/buckets/event-notifications/`
- Queues overview: `https://developers.cloudflare.com/queues/`
- Queues delivery guarantees: `https://developers.cloudflare.com/queues/reference/delivery-guarantees/`
- Queues limits: `https://developers.cloudflare.com/queues/platform/limits/`

## RunPod

- Serverless overview: `https://docs.runpod.io/serverless/overview`
- Endpoint configuration: `https://docs.runpod.io/serverless/endpoints/endpoint-configurations`
- Queue/load-balanced behavior: `https://docs.runpod.io/serverless/endpoints/overview`
- Network volumes: `https://docs.runpod.io/storage/network-volumes`
- Storage overview: `https://docs.runpod.io/pods/storage/types`
- Billing APIs: `https://docs.runpod.io/api-reference-v2/billing/get-aggregated-billing-history`
- Pricing: `https://www.runpod.io/pricing`

## Connectors

- Google Drive changes: `https://developers.google.com/workspace/drive/api/guides/manage-changes`
- Google Drive push notifications: `https://developers.google.com/workspace/drive/api/guides/push`
- Google Cloud Storage Pub/Sub notifications: `https://cloud.google.com/storage/docs/pubsub-notifications`
- Amazon S3 event notifications: `https://docs.aws.amazon.com/AmazonS3/latest/userguide/EventNotifications.html`
- Microsoft Graph driveItem delta: `https://learn.microsoft.com/en-us/graph/api/driveitem-delta`
- Microsoft Graph change notifications: `https://learn.microsoft.com/en-us/graph/change-notifications-overview`

## MCP

- Current spec 2026-07-28: `https://modelcontextprotocol.io/specification/2026-07-28`
- Authorization: `https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization`
- Tools: `https://modelcontextprotocol.io/specification/2026-07-28/server/tools`
- Resources: `https://modelcontextprotocol.io/specification/2026-07-28/server/resources`
- Transports: `https://modelcontextprotocol.io/specification/2026-07-28/basic/transports`

## PostgreSQL / pgvector / OpenTelemetry

- PostgreSQL Row Security: `https://www.postgresql.org/docs/current/ddl-rowsecurity.html`
- pgvector: `https://github.com/pgvector/pgvector`
- OpenTelemetry semantic conventions: `https://opentelemetry.io/docs/specs/semconv/`

## Multimodal / document models

- MinerU: `https://github.com/opendatalab/MinerU`
- PaddleOCR-VL: `https://paddlepaddle.github.io/PaddleOCR/main/en/version3.x/algorithm/PaddleOCR-VL/PaddleOCR-VL-1.6.html`
- DeepSeek V4 Flash official model: `https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash`
- DeepSeek-OCR-2: `https://huggingface.co/deepseek-ai/DeepSeek-OCR-2`
- DeepSeek Janus-Pro: `https://huggingface.co/deepseek-ai/Janus-Pro-7B`
- Mistral OCR 4: `https://mistral.ai/news/ocr-4/`
- Claude PDF support: `https://docs.anthropic.com/en/docs/build-with-claude/pdf-support`
- Claude vision: `https://docs.anthropic.com/en/docs/build-with-claude/vision`
- Gemini document understanding: `https://ai.google.dev/gemini-api/docs/document-processing`
- OpenAI image inputs: `https://developers.openai.com/api/docs/guides/images-vision`
- OpenAI file inputs: `https://developers.openai.com/api/docs/guides/file-inputs`
- OpenAI Batch: `https://developers.openai.com/api/docs/guides/batch`

## Claude Code

- Subagents: `https://docs.anthropic.com/en/docs/claude-code/sub-agents`
- Hooks: `https://docs.anthropic.com/en/docs/claude-code/hooks`
- Permissions: `https://docs.anthropic.com/en/docs/claude-code/permissions`
- Settings: `https://docs.anthropic.com/en/docs/claude-code/settings`
- Skills: `https://docs.anthropic.com/en/docs/claude-code/skills`

## Security / supply chain

- OWASP File Upload Cheat Sheet: `https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html`
- OWASP Prompt Injection Prevention: `https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html`
- Sigstore/Cosign: `https://docs.sigstore.dev/cosign/`
- SLSA: `https://slsa.dev/spec/v1.1/`

## Web performance/accessibility

- Core Web Vitals: `https://web.dev/articles/vitals`
- R3F scaling performance: `https://r3f.docs.pmnd.rs/advanced/scaling-performance`
- R3F performance pitfalls: `https://r3f.docs.pmnd.rs/advanced/pitfalls`
- prefers-reduced-motion: `https://developer.mozilla.org/en-US/docs/Web/CSS/@media/prefers-reduced-motion`
- WebGL context lost/restored: `https://developer.mozilla.org/en-US/docs/Web/API/HTMLCanvasElement/webglcontextlost_event`

## DART / SEC

- OpenDART API: `https://opendart.fss.or.kr/guide/main.do`
- OpenDART introduction: `https://opendart.fss.or.kr/intro/main.do`
- SEC EDGAR data APIs: `https://www.sec.gov/search-filings/edgar-application-programming-interfaces`

## Billing / IP

- Stripe usage-based billing/meters: `https://docs.stripe.com/billing/subscriptions/usage-based`
- KIPO 공지예외: `https://www.kipo.go.kr/ko/kpoContentView.do?menuCd=SCD0200239`
- KIPO 특허 출원공개: `https://www.kipo.go.kr/ko/topMenuLink.do?menuCd=SCD0200110`
- WIPO Trade Secrets Guide: `https://www.wipo.int/publications/en/details.jsp?id=4748`

---

# APPENDIX E — SOURCE-DERIVED NON-CLAIMS

본 문서가 설계했다고 해서 다음이 현재 구현·측정·배포됐다는 뜻은 아니다.

- v4 Router accuracy/cost improvement
- DeepSeek/Claude/GPT/Gemini의 TAVONEL hard-set 결과
- DART/SEC end-to-end score
- Critical Numeric Fidelity 수치
- Knowledge Integrity benchmark score
- Trusted Knowledge Yield
- World Sync Latency SLO 달성
- connector/MCP production readiness
- SOC 2/ISO 27001
- customer outcome
- patent grantability/infringement freedom

이들은 각 Phase evidence를 통해서만 claim으로 승격한다.

---

# FINAL NORTH STAR

> **TAVONEL의 moat는 특정 OCR 모델이 아니다.**
>
> **어떤 현실을 어떤 지능에게 어떤 비용으로 읽히고, 실패를 감지하고, 다른 경로로 복구하고, 결과를 출처·시간·관계·권한이 보존된 지식으로 컴파일하며, 현실이 바뀔 때 영향을 받은 지식과 Agent Context만 다시 동기화하는 전체 시스템이다.**

그리고 고객이 사이트에서 느껴야 할 최종 감정은 한 문장이다.

> **“문서 AI인 줄 알았는데, 우리 AI가 살아갈 세계를 만드는 시스템이었네.”**

---

# END OF TAVONEL ULTIMATE PRODUCTION RESEARCH & IMPLEMENTATION MASTERPLAN v4.0 FINAL
