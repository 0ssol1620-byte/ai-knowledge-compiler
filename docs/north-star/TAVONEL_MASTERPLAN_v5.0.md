# TAVONEL — ULTIMATE PRODUCTION RESEARCH & IMPLEMENTATION MASTERPLAN v5.0 FINAL
## Adaptive Economic Execution · Model Arena · Trusted Knowledge Compilation · Reality Synchronization · Evidence-First Product · Cinematic Experience · GTM · IP · AI-Native Solo Founder

**문서 상태:** FINAL SOURCE OF TRUTH v5.0 — MIGRATION + MODEL ARENA + AUTONOMOUS IMPLEMENTATION + COMMERCIAL EXECUTION CONTRACT  
**작성 기준:** 2026-08-11 KST  
**공개 브랜드:** **TAVONEL**  
**공개 카테고리:** **The Knowledge Compiler**  
**주 구현 에이전트:** **Claude / Claude Code**  
**기본 인프라:** Vercel + Cloudflare R2 + Cloudflare Queues + RunPod + Managed PostgreSQL/pgvector  
**현재 검증 baseline:** MinerU 3.4.4 + FOLYNTA/TAVONEL Recovery Runtime  
**핵심 원칙:** **Evidence, not adjectives. Every claim has a receipt.**  
**v5 핵심 목적함수:** **Minimum Cost to Trusted Output**  
**v5 신규 핵심:** **Same Corpus → Multi-Family Model Arena → Router Oracle Dataset → Production Routing Policy**

---

# DOCUMENT MAP

이 문서는 v4.0 FINAL의 제품·기술·웹·보안·GTM·IP 방향을 보존하면서, 2026-08-11 후속 논의에서 확정한 **GPT/Claude/Gemini/DeepSeek/Local OCR·Document VLM 동일 문서 비교**, **Batch/Bulk 평가**, **1,000-page Model Arena**, **DART/SEC real-world suite**, **Failure Zoo**, **Clean Control**, **Office Reality Suite**, **multi-page suite**, **$/Trusted Page 기반 routing calibration**을 최상위 실행 계약으로 승격한다.

충돌 시 우선순위:

1. 본 v5.0의 FINAL EXECUTION BOUNDARY / MODEL ARENA / DEFINITION OF DONE / PHASE GATES
2. 본 v5.0의 normative architecture / security / evidence / migration 규칙
3. 검증된 repository evidence, artifact hash, benchmark receipt
4. `v31-phase-gap-matrix.md`의 실제 현재 구현 상태
5. v4.0 FINAL 중 본 문서와 충돌하지 않는 상세 규칙
6. v3.1 및 이전 masterplan

## 절대 보존 규칙

- 역사적 `FOLYNTA` benchmark artifact 이름·hash·evaluator revision은 임의 변경하지 않는다.
- `99.98%`는 completion이며 accuracy가 아니다.
- `99.94%` recovery는 `1,796 / 1,797 recovery-required documents` denominator를 항상 동반한다.
- low-quality scan `36.9%` 약점과 blind-quality-detector negative result를 숨기지 않는다.
- 기존 Recovery / Reconciler / stable identity / semantic diff / dependency / recompilation / world state를 same-condition no-regression evidence 없이 재작성하지 않는다.
- GPT/Claude/DeepSeek/Gemini/Paddle/MinerU 등의 vendor·model 이름만으로 능력을 가정하지 않는다. exact model ID/revision/input mode/prompt/schema/date를 receipt로 pin한다.
- 다른 benchmark의 vendor score를 동일 조건 결과처럼 비교하지 않는다.
- Model Arena 결과는 제품 아키텍처를 **증명하기 위한 실험이 아니라 발견하기 위한 실험**이다. API-only가 더 낫다면 architecture를 수정한다.

---

# 전체 목차

- PART 0 — Executive Reset v5
- PART 1 — Verified Baseline & Current Gap
- PART 2 — V5 Reference Architecture
- PART 3 — Canonical Contracts & Database Design
- PART 4 — Industrial Ingestion
- PART 5 — Connector Control Plane
- PART 6 — Document & Page Profiler
- PART 7 — Model / Parser / Provider Registry
- PART 8 — TAVONEL Model Arena & Corpus Design **[NEW CORE]**
- PART 9 — Evaluation Protocol, Fairness & Prompt Tracks **[NEW CORE]**
- PART 10 — Adaptive Economic Router & Oracle Calibration
- PART 11 — Execution Scheduler, Batch/Bulk Lanes & RunPod Commit
- PART 12 — Inspector, Recovery & Document Reconciliation
- PART 13 — Canonical Knowledge IR & Trusted Knowledge
- PART 14 — Semantic Diff, Dependency, Impact & World State
- PART 15 — Retrieval, Ask & Agent Consumption
- PART 16 — Public API, CLI, SDK, Webhooks & MCP
- PART 17 — Product Experience & Cinematic Website
- PART 18 — Benchmark OS, Evidence & Research Publication
- PART 19 — Security, Privacy & Enterprise Hardening
- PART 20 — Observability, SRE, FinOps & Cost Model
- PART 21 — IP, Claims, Marketing & GTM
- PART 22 — Current Repository → V5 Migration Matrix
- PART 23 — V5 Dependency-Aware Implementation Phases
- PART 24 — Solo-Founder Critical Path
- PART 25 — FMEA / Potential Technical Issues & Remediation
- PART 26 — Repository Architecture, CI & Release Engineering
- PART 27 — AI-Native Solo-Founder Software Factory
- PART 28 — Test Catalog
- PART 29 — Operations Runbook Index
- PART 30 — Product & Website Copy Contract
- PART 31 — R&D / Evaluation Budget Strategy
- PART 32 — Final Definition of Done v5
- PART 33 — Launch Gates
- PART 34 — Final Autonomous Claude Code Command v5
- APPENDIX A — Model Arena Schemas
- APPENDIX B — Metrics & Cost Formulae
- APPENDIX C — Official Source Ledger
- APPENDIX D — Non-Claims / Withheld Claims

---

# PART 0 — EXECUTIVE RESET v5

## 0.1 최종 제품 정의

> **TAVONEL compiles fragmented organizational reality into trusted, temporal, traceable world state for AI and agents.**

한국어:

> **TAVONEL은 흩어진 조직의 현실을 AI와 Agent가 신뢰하고 추적하며 지속적으로 최신 상태로 사용할 수 있는 지식 세계로 컴파일한다.**

TAVONEL은 OCR service, PDF→Markdown converter, 특정 LLM wrapper, 단순 RAG builder, “Upload PDF → Chat” 제품이 아니다.

## 0.2 v5의 세 가지 최상위 질문

1. **어떤 모델이 최고인가?**가 아니라, **이 입력을 필요한 Trust Level로 만드는 최소 기대비용 경로는 무엇인가?**
2. **실패했는지 어떻게 아는가?** 그리고 operational failure와 semantic/model failure를 어떻게 분리하는가?
3. **실제 동일 문서에서 GPT·Claude·Gemini·DeepSeek·전문 OCR/VLM·TAVONEL adaptive pipeline 중 무엇이 품질/비용/속도/재현성의 Pareto frontier인가?**

## 0.3 v5의 중요한 전략적 추가

v4가 Router architecture를 설계했다면 v5는 Router가 무엇을 근거로 선택할지 **실험적으로 만들기 위한 Model Arena**를 정식 핵심 시스템으로 둔다.

```text
Representative Documents
        ↓
Same-condition Model Arena
        ↓
Model × Slice × Quality × Cost × Latency × Failure × Reproducibility
        ↓
Document Performance Map
        ↓
Router Oracle Dataset
        ↓
Shadow Economic Router
        ↓
Canary Production Policy
        ↓
Continuous Champion / Challenger Evaluation
```

## 0.4 제품 moat

모델은 교체 가능한 worker다. TAVONEL이 직접 소유해야 하는 것은:

- Industrial Ingestion
- Document/Page Profiler
- Model & Capability Registry
- **Model Arena / Evaluation OS**
- **Document Performance Map / Router Oracle Dataset**
- Adaptive Economic Router
- Failure Classification / Recovery Runtime
- Canonical Knowledge IR / Evidence Provenance
- Stable Semantic Identity
- Entity / Authority / Applicability / Temporal Resolution
- Semantic Diff / Typed Dependency / Impact
- Incremental Recompilation / Versioned World State
- Permission-first Consumption / Agent Lineage
- Evidence & Claims Governance
- Product Experience

## 0.5 실험 철학

TAVONEL은 “오픈소스가 싸고 API가 비싸다” 또는 “frontier가 무조건 더 정확하다”를 가정하지 않는다.

가능한 결과:

```text
A. Local champion + adaptive tail가 가장 경제적
B. Cheap API model을 primary로 쓰는 것이 더 경제적
C. Native extraction + API만으로 local GPU를 줄이는 것이 더 좋음
D. Privacy/on-prem 고객과 cloud 고객의 최적 architecture가 다름
```

어느 결과든 evidence가 이기면 architecture가 따라간다.

---

# PART 1 — VERIFIED BASELINE & CURRENT GAP

## 1.1 현재 benchmark baseline

2026-08-09 campaign:

| Suite | Documents | Evaluator revision |
|---|---:|---|
| ParseBench | 2,078 | `1d460294` |
| OmniDocBench | 1,651 | `193627ae` |
| olmOCR-Bench | 1,403 | `cfa88c1e` |
| **Total** | **5,132** | — |

Pipeline:

```text
MinerU 3.4.4 VLM engine
+
FOLYNTA/TAVONEL Recovery Runtime
```

## 1.2 증명된 Quality Vector

| Metric | Result |
|---|---:|
| Output completion | 5,131 / 5,132 = 99.98% |
| Recovery-required | 1,797 docs |
| Recovered | 1,796 / 1,797 = 99.94% |
| olmOCR overall | 80.6% (7,137 / 8,413 checks) |
| Text character match | 94.2% |
| Reading order match | 85.9% |
| Table structure | 95.5% |
| Table full | 92.6% |
| Reproducibility | 384 / 384 byte-identical across 3 repeats |

## 1.3 Document distribution matters

| Slice | Accuracy |
|---|---:|
| Standard digital | 99.0% |
| Headers/footers | 95.0% |
| Table-heavy | 88.5% |
| Academic/equations | 85.6% |
| Multi-column | 81.2% |
| Long/small type | 79.4% |
| Old scans/equations | 79.3% |
| **Low-quality scans** | **36.9%** |

따라서 단일 “TAVONEL accuracy”는 사용하지 않는다.

## 1.4 Recovery ablation

동일 model/corpus/evaluator/settings에서 recovery content만 제거:

```text
olmOCR overall        80.6 → 53.7
ParseBench table      0.9017 → 0.5321
ParseBench content    0.8376 → 0.5243
Omni text edit        0.0583 → 0.2640
Omni table TEDS       0.9257 → 0.7140
```

Recovery는 부가 기능이 아니라 Execution Control Plane의 핵심이다.

## 1.5 비용 baseline

```text
Healthy worker raw GPU       $1.23 / 1,000 pages
Whole campaign raw GPU       $5.92 / 1,000 pages
Healthy throughput           600 pages / pod-hour
Historical GPU               RTX 4090 @ $0.74/hour
```

둘 다 retail price가 아니다. Engineering/storage/support/margin 제외.

## 1.6 Retry evidence

Targeted retry 368개 중 315개가 byte-identical. 같은 모델·설정의 deterministic semantic failure에 blind retry를 반복하는 전략은 약하다.

반대로 충분한 wall-clock을 주자 이전 실패 3건 모두 MinerU가 완료했다. 따라서:

```text
Operational failure → same-model fresh worker / more wall-clock / rerender
Semantic failure    → alternate family / specialist / multimodal / verifier
```

## 1.7 Negative result

Blind quality ranking은 5,116 cases / 42,506 official failures에서 random이나 length-only를 이기지 못했다.

금지:

```text
quality_score < 0.6 → expensive_model
```

Profiler는 센서이고 Inspector는 explicit finding generator다.

## 1.8 현재 repository gap

현재 `v31-phase-gap-matrix.md`에 따르면 secure ingest, profiler/model registry, calibrated router, retrieval/API/MCP, Health Scan, cinematic hero, enterprise hardening은 아직 대부분 Not Built/Partial이다. 반면 Inspector/Recovery/Reconciler/Identity/Diff/Dependency/Recompile/World State는 Built 또는 보호할 자산이다.

따라서 지금이 Model Arena와 Router Oracle을 architecture에 넣기에 적절한 시점이다.

---

# PART 2 — V5 REFERENCE ARCHITECTURE

```text
SOURCES
Web · CLI · API · Drive · GCS · S3/R2 · SharePoint/OneDrive
        ↓
INDUSTRIAL INGESTION
Multipart · Resume · Preflight · Quarantine · Manifest · ACL
        ↓
REFERENCE OBSERVATION
Native structure · Reference render · Profiler · Risk class
        ↓
INTELLIGENCE CONTROL PLANE
Model Registry · Cost Snapshot · Route Policy · Budget · Provider Health
        ↓
ADAPTIVE EXECUTION
Native · MinerU · Paddle · DeepSeek · General Multimodal API · Frontier Verifier
        ↓
PROTECTED COMPILER CORE
Inspect · Recover · Reconcile · IR · Provenance · Identity
        ↓
TRUSTED KNOWLEDGE
Entity · Authority · Applicability · Bi-temporal · Epistemic · Permission
        ↓
CHANGE INTELLIGENCE
Semantic Diff · Dependency · Impact · Selective Recompile
        ↓
VERSIONED WORLD STATE
Atomic Publish · Rollback · Freshness
        ↓
CONSUMPTION
Ask · Retrieval · API · SDK · MCP · Agents · Exports

              ↕
        BENCHMARK / MODEL ARENA OS
Same corpus · Oracle matrix · Cost/latency · Reproducibility · Claims
```

## 2.1 Truth boundaries

- **R2/Object Storage:** immutable source/derived/evidence artifact truth
- **PostgreSQL:** workflow/identity/permission/publish/billing truth
- **Queue:** at-least-once work delivery; truth 아님
- **RunPod/API providers:** compute workers; truth 아님
- **Benchmark receipts:** append-only research truth

## 2.2 주요 불변식

1. Published claim은 exact evidence 또는 explicit unsupported state를 가진다.
2. Partial build는 ACTIVE world state가 될 수 없다.
3. Permission revoke는 background reindex/recompile보다 먼저 enforcement된다.
4. Queue duplicate/out-of-order가 side effect를 두 번 만들지 않는다.
5. Model capability/license/data policy가 Registry에서 승인되지 않으면 route candidate가 될 수 없다.
6. Arena 결과는 exact model/input/prompt/schema/evaluator를 pin한다.
7. Arena test set을 보고 route threshold/prompt를 튜닝하지 않는다.
8. Public claim은 approved receipt에서만 렌더링한다.

---

# PART 3 — CANONICAL CONTRACTS & DATABASE DESIGN

## 3.1 Core identity envelope

모든 domain object는 최소:

```yaml
identity:
  tenant_id: ten_...
  workspace_id: ws_...
  object_id: ...
  schema_version: ...
  created_at: ...
  source_lineage: ...
```

## 3.2 Artifact contract

```yaml
artifact:
  artifact_id: art_...
  type: SOURCE | RENDER | PARSER_RAW | RECONCILED | IR | EXPORT | RECEIPT
  object_key: ...
  sha256: ...
  bytes: ...
  media_type: ...
  producer:
    service: ...
    version: ...
    container_digest: ...
  inputs: [...]
  retention_class: ...
```

## 3.3 Public DTO와 trade-secret receipt 분리

Public:

```json
{"page":47,"state":"REROUTED","reason_category":"STRUCTURE_UNCERTAIN"}
```

Internal:

```json
{
  "profile_features":"secret/ref",
  "candidate_scores":"secret/ref",
  "expected_gain":0.12,
  "cost_matrix_snapshot":"secret/ref",
  "selected_model":"...",
  "policy_version":"..."
}
```

Internal receipt가 client bundle/API/analytics로 새지 않게 serializer/schema/view를 분리한다.

## 3.4 신규 Arena tables

```sql
create table arena_campaigns (
  id uuid primary key,
  name text not null,
  corpus_manifest_sha256 text not null,
  protocol_version text not null,
  created_at timestamptz not null,
  status text not null
);

create table arena_cases (
  id uuid primary key,
  campaign_id uuid not null,
  document_family_id text not null,
  page_or_document_id text not null,
  split text not null, -- CALIBRATION | EVAL | ROUTER_TRAIN | ROUTER_HOLDOUT
  slice_labels jsonb not null,
  source_artifact_id uuid not null,
  truth_ref text,
  unique(campaign_id, page_or_document_id)
);

create table arena_runs (
  id uuid primary key,
  campaign_id uuid not null,
  case_id uuid not null,
  model_registry_id uuid not null,
  input_track text not null,
  prompt_track text not null,
  exact_model_revision text not null,
  settings_hash text not null,
  raw_output_artifact_id uuid,
  normalized_output_artifact_id uuid,
  status text not null,
  latency_ms bigint,
  input_units jsonb,
  output_units jsonb,
  actual_cost_usd numeric,
  created_at timestamptz not null
);

create table arena_scores (
  run_id uuid not null,
  evaluator_id text not null,
  evaluator_revision text not null,
  metric_name text not null,
  value double precision,
  severity text,
  receipt_ref text not null,
  primary key(run_id, evaluator_id, metric_name)
);
```

## 3.5 Outcome map

Production route outcome는 Arena와 별도 namespace에 저장한다. Customer data를 benchmark corpus로 자동 편입하지 않는다.

---

# PART 4 — INDUSTRIAL INGESTION

## 4.1 대용량 기본 구조

```text
Browser / CLI / Connector
→ Upload Session
→ Presigned multipart direct to R2
→ Complete + checksum
→ Quarantine/Preflight
→ Source Manifest
→ Queue
→ Progressive processing
```

App server가 multi-GB source payload를 proxy하지 않는다.

## 4.2 Resumable requirements

- adaptive part size
- per-part receipt
- retry with jitter
- crash/browser restart resume
- whole-file SHA-256
- abandoned multipart cleanup
- IndexedDB/CLI checkpoint
- main thread에서 whole file hashing 금지

## 4.3 Progressive compilation

```text
Uploading           68%
Preflight           54%
Profiled            41%
Knowledge ready     19%
First answers       AVAILABLE (partial scope)
```

전체 upload 완료 전에도 완료된 파일부터 processing할 수 있다.

## 4.4 Preflight

- extension + magic/MIME
- PDF encryption/corruption/page count/JavaScript/actions
- OOXML archive safety/macros/OLE/external links/hidden content
- image pixel/decompression limits
- ZIP path traversal/nesting/expansion budget
- source-aware blank detection
- sandbox resource budgets

## 4.5 Backpressure

- tenant storage/page/job quota
- processing backlog cap
- daily/monthly spend cap
- interactive/standard/batch priority
- no GPU provision while only upload waits

---

# PART 5 — CONNECTOR CONTROL PLANE

## 5.1 Channels

```text
Small        Drag & Drop
Medium       CLI / watched folder
Enterprise   Drive · GCS · S3/R2 · OneDrive/SharePoint
```

## 5.2 Common algorithm

```text
Initial crawl
→ immutable source versions
→ ACL snapshot
→ durable cursor
→ notification/watch
→ delta fetch
→ permission fast lane
→ semantic diff/recompile
→ periodic reconciliation
```

Webhook/notification은 truth가 아니라 change hint다.

## 5.3 ACL invariant

```text
Source revoke observed
→ deny overlay active immediately
→ retrieval blocked
→ background recompile/index cleanup later
```

## 5.4 Priorities

P1 Google Drive + S3/R2  
P2 GCS + OneDrive/SharePoint  
P3 Confluence/Dropbox/Notion/GitHub only after paid demand

---

# PART 6 — DOCUMENT & PAGE PROFILER

Profiler는 `easy/hard` classifier가 아니라 versioned sensor다.

Feature groups:

- source format/size/page/native text
- language/script
- blur/contrast/skew/compression/blankness/small font
- single/multi-column/reading-order complexity
- table density/gridless/merged/nested/cross-page/numeric density
- formula/code density
- figure/chart/diagram/caption/arrows
- neighboring page/heading/document type
- business risk

Missing signal은 0이 아니라 explicit missing reason.

```yaml
feature:
  name: explicit_clause_id
  value: null
  state: MISSING_NOT_APPLICABLE
  reason: no_clause_identifier_found
```

Office는 native structure + sandboxed visual render dual path.

---

# PART 7 — MODEL / PARSER / PROVIDER REGISTRY

## 7.1 Candidate families

### Local / specialist

- MinerU 3.4.4 — historical champion baseline
- PaddleOCR-VL-1.6 — challenger
- DeepSeek-OCR-2 — challenger
- approved future document-specialist models

### General multimodal API

- OpenAI current image-capable models
- Anthropic current Claude vision/PDF-capable models
- Google current Gemini document/vision models
- optional Mistral OCR/API specialist

### Control models

- GPT-4o can remain as a historical/commercial control because users/vendors still reference it, but v5 does not assume it is the best current OpenAI choice.

## 7.2 Current official facts snapshot — 2026-08-11

- OpenAI current model catalog lists `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna`; latest OpenAI models support text+image input. Luna is positioned for cost-sensitive high-volume work.
- Claude active model catalog includes Sonnet 5/Opus 5/Haiku 4.5; Claude Message Batches supports vision and charges 50% of standard prices.
- Claude PDF processing combines extracted text and an image of each PDF page, so PDF cost is not equivalent to plain-text token cost.
- Gemini Batch is priced at 50% of equivalent interactive API and document processing supports large PDF workflows; exact model must be pinned at run time.
- DeepSeek-OCR-2 is a distinct image-to-text/document OCR model; do not infer vision capability from a text model name such as “Flash”.
- PaddleOCR-VL-1.6 is the current PaddleOCR-VL generation; vendor-reported scores are not substituted for TAVONEL same-condition results.

**가격·모델 가용성은 Arena 실행 시 Registry snapshot으로 다시 조회/검증하고, 문서의 숫자를 production price truth로 사용하지 않는다.**

## 7.3 Registry fields

```yaml
model:
  registry_id: ...
  provider: ...
  exact_model_id: ...
  exact_revision_or_snapshot: ...
  family: DOCUMENT_SPECIALIST | GENERAL_MULTIMODAL | FRONTIER_VERIFIER
  modalities: [TEXT, IMAGE, PDF]
  batch_supported: true|false
  native_pdf_supported: true|false
  structured_output: ...
  license_state: APPROVED | REVIEW | BLOCKED
  data_policy: ...
  context_limit: ...
  output_limit: ...
  price_snapshot: ...
  capability_probe_receipts: [...]
  lifecycle: SHADOW | CHALLENGER | CHAMPION | VERIFIER | DISABLED
```

## 7.4 Lifecycle

```text
DISCOVERED
→ LICENSE/DATA-POLICY REVIEW
→ CAPABILITY PROBE
→ PROMPT CALIBRATION
→ MODEL ARENA
→ SHADOW
→ CHALLENGER
→ CANARY
→ CHAMPION/VERIFIER
→ DEPRECATED
```

---

# PART 8 — TAVONEL MODEL ARENA & CORPUS DESIGN [NEW CORE]

## 8.1 목적

Model Arena는 “누가 1등인가?”를 찾는 leaderboard가 아니다.

목적:

1. 어떤 document slice에서 어떤 intelligence family가 강한지 측정
2. 동일 failure에서 어느 대체 모델이 incremental recovery를 만드는지 측정
3. API vs local의 실제 cost/latency/reproducibility 비교
4. Router Oracle Dataset 생성
5. TAVONEL adaptive pipeline 자체를 single-model baselines와 비교

## 8.2 Model Arena v1 — 1,000 pages

### A. Public Ground Truth — 400 pages

기존 세 benchmark에서 층화 추출.

권장 composition:

| Slice | Pages |
|---|---:|
| Clean digital | 60 |
| Table-heavy | 70 |
| Multi-column / reading order | 50 |
| Formula / academic | 50 |
| Low-quality / degraded scan | 60 |
| Small-font / long | 40 |
| Chart / figure / visual grounding | 40 |
| Headers/footers / tricky presence-absence | 30 |
| **Total** | **400** |

실제 benchmark별 분배는 slice와 official evaluator coverage를 동시에 맞춰 manifest로 고정한다.

### B. Real Corporate — 300 pages

#### DART 150

- 사업보고서
- 반기/분기보고서
- 감사보고서
- 재무제표/주석
- 표 밀집 공시
- 정정공시
- 긴 한글 문서
- 한/영 혼합
- 작은 글씨
- 이미지/스캔 첨부

#### SEC 150

- 10-K
- 10-Q
- 8-K
- amendments
- exhibits
- financial statements
- footnotes
- inline XBRL-linked financial tables

DART/SEC는 OCR 품질뿐 아니라 **Critical Numeric Fidelity, amendment/version, source evidence, downstream QA**를 평가한다.

### C. TAVONEL Failure Zoo — 200 pages

기존 campaign과 새 실험에서 실제 문제를 일으킨 case를 분류한다.

권장:

| Failure slice | Pages |
|---|---:|
| Degraded scans | 40 |
| Difficult tables | 40 |
| Reading order / multi-column | 30 |
| Formulas | 25 |
| Tiny text | 20 |
| Cross-page semantics | 15 |
| Blank / near-blank | 10 |
| Operational timeout/wall-clock incidents | 10 |
| Misc. difficult / disagreement | 10 |
| **Total** | **200** |

핵심 metric:

```text
Incremental Recovery Yield(model B | model A failure)
```

### D. Clean Control — 100 pages

- born-digital
- single column
- normal font
- simple table
- ordinary corporate report/manual

목적은 **비싼 모델을 쓰지 않아도 되는 영역**을 증명하는 것.

## 8.3 100-page Prompt Calibration Set — Arena와 분리

Arena 1,000페이지를 prompt tuning에 사용하지 않는다.

별도 100페이지 calibration set:

- public/training leakage를 피할 수 있는 별도 fixture 또는 dev split
- 각 slice 대표
- final Arena case와 document family overlap 금지

여기서 provider-optimized prompt/schema/image resolution을 결정하고 **freeze 후** Arena를 실행한다.

## 8.4 Router split

Arena 결과를 Router training에 사용하려면 document family 단위로 split한다.

```text
60% ROUTER_TRAIN
20% ROUTER_CALIBRATION
20% ROUTER_HOLDOUT
```

동일 보고서의 다른 페이지가 train과 holdout에 동시에 들어가지 않게 한다.

Router policy는 holdout label을 본 뒤 수정하면 새 policy version과 새 holdout이 필요하다.

## 8.5 Model Arena v2 — Multi-page

single-page parser score가 좋아도 document semantics가 깨질 수 있다.

추가 suite 후보:

- MPDocBench-Parse: multi-page semantic continuity, heading hierarchy, cross-page table, figure preservation
- Dr. DocBench: difficult/expert-domain long-document pages
- 새로운 source-traceable/degradation benchmark는 라이선스·방법론 검토 후 challenger suite로 추가

v2 목적:

```text
Page Accuracy
→ Document Continuity
→ Cross-page Semantics
→ Knowledge Compilation Readiness
```

## 8.6 Model Arena v3 — Office Reality Suite

200 files 권장:

```text
50 DOCX
50 PPTX
50 XLSX
50 original ↔ PDF export pairs
```

비교:

```text
Native XML/OOXML path
vs Visual render path
vs Dual-path reconciliation
vs Frontier/general multimodal
```

평가:

- hidden content
- formulas
- merged cells
- chart underlying data
- speaker notes
- layout/visual association
- export-induced information loss

## 8.7 Model Arena v4 — Knowledge Evolution Suite

같은 문서 family의 revision을 만들어:

- typo only
- numeric change
- may→must
- section move
- clause split/merge
- supersession
- effective date
- customer exception
- permission revoke

를 평가한다.

이 suite는 extraction model ranking이 아니라 **stable identity/diff/impact/recompile** 평가용.

---

# PART 9 — EVALUATION PROTOCOL, FAIRNESS & PROMPT TRACKS [NEW CORE]

## 9.1 Track I — Standardized Page-Image Capability

모든 vision-capable candidate에 **동일 renderer, 동일 page image, 동일 target schema**를 준다.

목적:

> 순수하게 같은 시각 입력에서 어떤 모델이 얼마나 잘 구조를 복원하는가?

고정:

- renderer/version
- resolution/DPI
- crop/page boundaries
- system/task instruction
- output schema
- temperature/reasoning mode where comparable
- max output budget

이 Track은 provider native PDF preprocessing advantage를 제거한다.

## 9.2 Track N — Native Provider Best-Practice

각 provider의 공식 권장 input path를 허용한다.

예:

- Claude PDF support
- Gemini Files/PDF document processing
- OpenAI file/image path
- local parser native PDF path

목적:

> 실제 production에서 해당 provider를 가장 잘 사용했을 때의 결과는?

Track I와 N을 섞어 하나의 “모델 score”로 만들지 않는다.

## 9.3 Track P — Provider-Optimized Prompt

100-page calibration set에서만 prompt/schema를 최적화한다.

Final Arena에서는 prompt freeze.

각 model receipt:

```yaml
prompt_receipt:
  prompt_id: ...
  calibration_corpus_sha256: ...
  system_prompt_sha256: ...
  user_template_sha256: ...
  output_schema_sha256: ...
  image_settings: ...
  reasoning_settings: ...
  temperature: ...
  max_output: ...
```

## 9.4 Track B — Batch/Bulk Economics

Batch는 quality track이 아니라 **execution/cost lane**으로도 측정한다.

- OpenAI Batch-supporting exact model
- Claude Message Batches
- Gemini Batch
- local RunPod async queue

Batch/interactive가 동일 모델 behavior를 제공한다고 무조건 가정하지 않는다. 30–50 case equivalence sample을 먼저 수행해 output/score drift를 확인한다.

## 9.5 Normalization layer

Public evaluator가 요구하는 Markdown/JSON으로 adapter가 변환하되 **모델 output에서 없는 의미를 추가하면 안 된다.**

Allowed normalization:

- deterministic schema field rename
- line ending/Unicode normalization
- provider envelope removal
- explicit coordinates unit conversion

Forbidden normalization:

- LLM으로 output repair 후 원 모델 score로 계산
- missing table cell을 다른 model에서 보충
- hallucinated bbox 생성
- evaluator label을 보고 output 수정

Repair pipeline을 평가하려면 별도 `PIPELINE` entry로 등록한다.

## 9.6 Candidate classes

최소 비교 baseline:

```text
A. MinerU 3.4.4 only
B. PaddleOCR-VL current approved
C. DeepSeek-OCR-2 current approved
D. Cheapest viable OpenAI image-capable batch candidate
E. Balanced OpenAI image-capable candidate
F. Claude cost-efficient/strong vision candidate
G. Gemini cost-efficient/strong document candidate
H. Optional specialist API (e.g., Mistral OCR) if licensing/cost permits
I. TAVONEL Adaptive Pipeline
```

모델 수가 너무 많으면 200-page screening 후 Pareto-dominated candidate를 제거한다.

## 9.7 Two-stage screening to save cost

### Stage 0 — 50-case capability smoke

- API schema works
- modality verified
- output format reasonable
- cost/tokens measured
- catastrophic behavior 없음

### Stage 1 — 200-page screening

모든 candidate 실행.

Pareto dominance 기준:

모델 X가 Y보다:

- 모든 주요 quality slice에서 낮거나 같고
- 더 비싸거나 같고
- 더 느리거나 같고
- 특별한 recovery niche도 없다면

full 1,000 Arena에서 제외 가능.

### Stage 2 — 1,000-page Arena

Pareto survivors + required controls + TAVONEL adaptive.

### Stage 3 — 5,132 full public expansion

Arena 결과에서 production 후보 2–4개만 전체 public suite로 확장.

### Stage 4 — DART/SEC expansion

representative sample에서 가치가 입증된 candidate만 수천~수만 page로 확대.

## 9.8 Reproducibility

128 stratified cases × 3 repeats 권장.

측정:

- exact byte identity
- normalized structural identity
- numeric identity
- semantic relation identity
- evaluator score variance
- latency variance

Closed API가 non-deterministic이어도 그 사실 자체가 Router/Verifier role 결정에 중요하다.

## 9.9 Human adjudication

사람이 필요한 경우:

- evaluator disagreement
- numeric/source ambiguity
- cross-page semantic relation
- chart meaning
- authority/applicability gold

2 annotators + adjudication; reviewer identity와 evidence 저장.

## 9.10 Benchmark leakage/contamination

- Prompt tuning은 final Arena 1,000에 금지
- model provider가 benchmark를 학습했을 가능성을 외부 score에서 제거할 수 없으므로 DART/SEC/Failure Zoo/held-out synthetic mutations를 함께 사용
- near-duplicate/document-family split
- public benchmark에 최적화된 routing을 customer generalization이라고 표현 금지

---

# PART 10 — ADAPTIVE ECONOMIC ROUTER & ORACLE CALIBRATION

## 10.1 Objective

```text
Minimize E[Total Cost]
+ latency penalty
+ untrusted-output risk
+ correlated-failure penalty

subject to:
Required Trust
Business Risk
Permission/Data Policy
Deadline
Budget
```

## 10.2 Router Oracle Matrix

Arena가 생성하는 핵심 table:

```text
case/page
× document features
× model/path
× quality metrics
× catastrophic failure
× latency
× actual cost
× retry/recovery
× reproducibility
```

Best permitted path per case를 oracle로 정의한다.

## 10.3 Router metrics

- Oracle Regret
- Trust Constraint Violation
- Catastrophic Miss Rate
- False Escalation
- Missed Escalation
- Cost vs Always-Local
- Cost vs Always-Cheap-API
- Cost vs Always-Frontier
- Quality non-inferiority
- Frontier/API tail fraction
- Route stability

## 10.4 Recovery utility

```text
Incremental Recovery Yield(B | A failed)
= B가 A의 실패 중 trust gate를 통과시킨 수 / A failure set

Cost per Incremental Recovery
= B escalation incremental cost / incrementally recovered pages
```

이 값이 단순 overall accuracy보다 fallback 모델 선택에 중요하다.

## 10.5 Bootstrap route policy

초기 deterministic:

```text
native digital simple → native/cheap + sample validation
standard page          → current champion
operational timeout    → same model fresh worker
complex table          → table specialist
formula                → formula/document specialist
low-quality scan       → degradation-strong model
chart/diagram          → general multimodal
high-risk disagreement → independent frontier verifier
unresolved             → review/fail closed
```

Arena holdout에서 검증 후만 production rollout.

## 10.6 Learned router later

- supervised outcome model in shadow
- off-policy evaluation
- constrained optimization
- human-approved policy version
- canary

고객 production traffic에서 무단 exploration/bandit 금지.

---

# PART 11 — EXECUTION SCHEDULER, BATCH/BULK LANES & RUNPOD COMMIT

## 11.1 Three execution lanes

### FAST LANE

사용자가 기다리는 Health Scan / interactive recovery.

- warm/self-hosted worker
- synchronous provider API if needed
- tight latency budget

### BULK LANE

대규모 corpus, nightly/backfill, low-priority revalidation.

- OpenAI/Claude/Gemini Batch when exact model supports
- RunPod queue/batch
- 24h-class turnaround acceptable

### RESEARCH LANE

Model Arena / benchmark / ablation.

- immutable manifests
- batch-preferred where quality-equivalent
- strict cost receipt

## 11.2 Batch official behavior snapshot

- Anthropic Message Batches: high-volume async, all active models supported, vision supported, 50% price, up to 100,000 requests or 256MB per batch, completion/expiry behavior documented.
- Gemini Batch: equivalent model interactive price의 50%, target turnaround 24h, file-based batch input recommended for large jobs.
- OpenAI exact model’s Batch endpoint/pricing must be taken from the current model page/Batch docs at run time; do not hardcode a global “always 50%” assumption if model-specific pricing page differs.

## 11.3 Cost capture

API:

```text
input tokens/image units
cached tokens
output tokens
batch/interactive tier
provider surcharge/tool fee
request failures/retries
```

Local:

```text
GPU seconds
GPU $/hour snapshot
cold start/load time
idle time attributable
retry time
CPU/render/storage operation
```

## 11.4 R2-before-ACK

1. input hash verify
2. inference
3. raw output validate
4. R2 upload
5. hash/HEAD verify
6. DB attempt receipt + outbox
7. queue ACK

## 11.5 Correlated provider failure

모든 worker가 1초 내 멈추는 형태는 document failure가 아니라 provider/account failure로 분류. 새 pod 구매를 반복하지 않고 circuit open.

---

# PART 12 — INSPECTOR, RECOVERY & DOCUMENT RECONCILIATION

Protected core 유지.

Failure taxonomy:

- operational: timeout/OOM/worker lost/provider stop/bootstrap/network/commit
- source/render: corrupt/encrypted/blank/render/low-resolution/skew
- extraction: empty nonblank/text missing/duplicate/reading order/table/numeric/formula/figure/cross-page
- knowledge: entity/authority/applicability/time/provenance/permission/injection

Recovery ladder:

```text
L0 ACCEPT
L1 RERENDER/DESKEW/RESOLUTION/SPLIT
L2 SAME-MODEL OPERATIONAL RETRY
L3 SPECIALIST/ALTERNATE FAMILY
L4 MULTI-PARSER RECONCILIATION
L5 GENERAL MULTIMODAL / FRONTIER VERIFIER
L6 DOCUMENT-LEVEL RECONCILIATION
L7 HUMAN REVIEW
L8 FAIL CLOSED
```

Consensus는 truth가 아니다. source correspondence + independent failure mode가 필요하다.

---

# PART 13 — CANONICAL KNOWLEDGE IR & TRUSTED KNOWLEDGE

현재 core는 adapter로 보존한다.

필수 fields:

- stable unit/version ID
- type/content/structure/hierarchy
- evidence refs
- entity/relation refs
- authority/status
- applicability
- valid/system time
- epistemic state
- permission scope
- derived_from/depends_on
- compiler/parser/model lineage

## 13.1 Evidence provenance

```text
Answer/Claim
→ Knowledge Unit
→ Parser/Reconciler artifact
→ Source Version
→ Page/Slide/Sheet
→ bbox/span/table-cell/OOXML node
```

좌표가 없으면 fabricated bbox 대신 `COORDINATE_UNAVAILABLE`.

## 13.2 Identity

- false merge > false split 비용
- current bootstrap thresholds는 calibrated claim 아님
- missing signals renormalize/abstain
- one-to-one assignment
- reversible split/merge

## 13.3 Authority/applicability/time

`latest wins` 금지.

Result states:

```text
RESOLVED
CONFLICTED
NO_APPLICABLE_CLAIM
UNKNOWN_AUTHORITY
REVIEW_REQUIRED
```

Bi-temporal:

```text
valid_time     현실에서 언제 사실인가
known_time     시스템은 언제 알았는가
```

---

# PART 14 — SEMANTIC DIFF, DEPENDENCY, IMPACT & WORLD STATE

```text
New Source Version
→ L0-L5 Diff
→ Stable Unit Matching
→ Typed Dependency
→ Impact Reason Paths
→ Dirty Set
→ Selective Recompile
→ Validate
→ Atomic ACTIVE pointer swap
→ Consumption invalidation/notification
```

Critical test:

```text
SelectiveRebuild(changes)
== RelevantSubset(FullRebuild(new_sources))
```

Critical impact false negative는 publish blocker.

Permission revoke는 semantic recompile보다 빠른 deny fast path.

---

# PART 15 — RETRIEVAL, ASK & AGENT CONSUMPTION

Filter order:

1. tenant/workspace
2. world state
3. permission
4. time
5. authority/applicability
6. epistemic/validation
7. lexical/vector candidates
8. graph/structure
9. rerank
10. evidence coverage

Ask UI:

```text
Question: 현재 보증기간은?

2 years
Current global policy · Effective 2026-08-01

Other candidates:
1 year · 2024 manual · SUPERSEDED
3 years · Customer A contract · SCOPED EXCEPTION

Evidence → Page 17 → Table 3 → Cell B4
```

Generic chatbot 아님.

---

# PART 16 — PUBLIC API, CLI, SDK, WEBHOOKS & MCP

API-first:

```text
Core API
├ Web
├ CLI
├ Python SDK
├ TypeScript SDK
├ Connectors
└ Read-only MCP
```

Initial MCP tools:

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

Write MCP는 auth/scope/audit/approval/idempotency/rollback/paid demand 전 금지.

---

# PART 17 — PRODUCT EXPERIENCE & CINEMATIC WEBSITE

## 17.1 Narrative

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

## 17.2 WOW moments

### WOW 1 — Documents → World

문서가 Markdown 아이콘으로 끝나지 않고 Customer/Contract/Product/Policy/Region/Time 관계로 재구성.

> **Don't give AI more documents. Give it a world it can understand.**

### WOW 2 — Change Propagation

```text
1 source changed
7 knowledge units affected
3 retrieval contexts stale
2 agent contexts impacted
RECOMPILING 7 / 12,841
```

> **When one fact changes, don't rebuild the world.**

### WOW 3 — Answer → Source

```text
Answer → Claim → Unit → Document → Page 17 → Table 3 → Cell B4
```

> **Every answer should have a way home.**

## 17.3 Design

**80% Calm · 20% Impossible Moment**

금지: generic glowing brain, meaningless particles/orb, gradient slop, stock robot, fake progress.

R3F/Three.js/GSAP은 product semantics를 시각화할 때만.

## 17.4 Real event projection

실제 app은 backend durable event를 UI projection에 사용한다.

```text
source.admitted
document.profiled
route.selected
inspection.failed
document.rerouted
recovery.completed
knowledge.created
conflict.detected
impact.detected
recompile.completed
world_state.activated
```

Sample mode와 real mode를 명시적으로 구분한다.

---

# PART 18 — BENCHMARK OS, EVIDENCE & RESEARCH PUBLICATION

## 18.1 Suite hierarchy

### A Public Reproducible

- ParseBench
- OmniDocBench
- olmOCR-Bench

### B Real Corporate

- DART
- SEC EDGAR/XBRL-linked

### C Stress/Failure Zoo

- degraded/old scan
- tiny text
- tables/formulas/charts
- cross-page
- photographed/rotated
- operational failures

### D Multi-page

- MPDocBench-Parse or approved successor
- document-level semantics

### E Production Golden

customer consent/contract/privacy를 통과한 real incidents only.

### F Office Reality

DOCX/PPTX/XLSX native-vs-visual.

### G Knowledge Evolution

revision/diff/impact/recompile.

## 18.2 Quality Vector

- completion/recovery/reproducibility
- text/read order/table/formula/chart
- semantic preservation
- critical numeric fidelity
- provenance
- identity/entity
- authority/applicability/time
- permission
- diff/impact/recompile
- downstream QA/citation/stale/conflict/abstention
- cost/latency

## 18.3 Critical Numeric Fidelity

- exact numeric match
- sign
- decimal/comma
- currency/unit
- date/period
- table-cell association
- evidence localization

## 18.4 End-to-end same-model ablation

동일 downstream LLM/settings:

```text
Raw PDF direct
vs Basic Parse + RAG
vs TAVONEL Compiled Knowledge
```

이 실험이 “TAVONEL knowledge layer가 실제 agent answer를 개선하는가”를 평가한다.

## 18.5 Single model vs adaptive pipeline

반드시 포함:

```text
MinerU only
Best OSS single
Cheapest viable API single
Best quality API single
TAVONEL adaptive
```

TAVONEL adaptive가 지는 경우도 그대로 기록한다.

## 18.6 Statistical rules

- paired same-document comparison
- bootstrap CI
- pass/fail paired tests where appropriate
- slice sample size
- evaluator variance separate
- effect size + cost
- multiple comparison caution
- no leaderboard claim across different corpus/evaluator

## 18.7 Claim pack

Every public claim:

```yaml
claim_id: ...
status: APPROVED | CONDITIONAL | WITHHELD | RETIRED
text: ...
numerator: ...
denominator: ...
corpus: ...
evaluator: ...
model/pipeline: ...
input_track: ...
prompt_track: ...
price_snapshot: ...
required_caveats: [...]
forbidden_phrasings: [...]
artifact_hashes: [...]
```

---

# PART 19 — SECURITY, PRIVACY & ENTERPRISE HARDENING

핵심:

- hostile upload / sandbox / no outbound tools
- tenant RLS / FORCE RLS
- connector least privilege / encrypted tokens
- provider data-policy filtering before routing
- prompt injection as data
- retention/deletion/backups
- supply-chain SBOM/signatures/model hashes
- audit
- restore drill
- no SOC2/ISO logo before actual certification

Arena에는 고객 문서를 자동 수집하지 않는다. Production Outcome Dataset와 publishable benchmark corpus를 분리한다.

---

# PART 20 — OBSERVABILITY, SRE, FINOPS & COST MODEL

## 20.1 Core cost metrics

```text
$/Input Page
$/Successful Page
$/Trusted Page
$/Recovered Page
$/Additional Quality Point
$/Trusted Knowledge Unit
$/World-State Change
```

## 20.2 Trusted Page

페이지가 workspace-required trust gate를 통과하고, critical evidence/structure 조건을 만족했을 때만 trusted.

단순 output 존재는 trusted가 아니다.

## 20.3 API cost

```text
API Cost = input units × input price
         + cached units × cached price
         + output units × output price
         + provider/tool fees
         + failed/retried requests attributable
```

PDF/document API는 extracted text + page-image 비용이 결합될 수 있으므로 plain-text tokens만으로 추정 금지.

## 20.4 Local cost

```text
Local Cost = GPU active seconds × $/GPU-second
           + attributable cold-start/load
           + retry/recovery GPU
           + render CPU/storage ops
           + idle leak attributable
```

`$/GPU hour`만 비교하지 않는다.

## 20.5 Arena cost estimator

Arena 시작 전 각 candidate 20–50 pages pilot로 actual usage를 수집.

```text
Projected Arena Cost = mean(slice cost/page) × target slice pages
```

각 slice 별로 separate estimate를 사용한다. Clean page 평균으로 degraded scan을 예측하지 않는다.

## 20.6 Budget gates

- per-candidate screening cap
- Arena total hard cap
- API/provider balance cap
- frontier model maximum fraction
- expansion only after Pareto gate
- failed batch retry cap

---

# PART 21 — IP, CLAIMS, MARKETING & GTM

## 21.1 Public abstraction

> **Every page doesn't need the same AI.**  
> **Failures shouldn't silently become knowledge.**  
> **Every answer should have a way home.**  
> **When one fact changes, don't rebuild the world.**  
> **Your AI shouldn't work at yesterday's company.**

## 21.2 New Arena marketing opportunity

Arena가 실제로 지지할 경우에만:

- “There is no single document accuracy.”
- “Different documents need different intelligence.”
- “Same corpus. Same evaluator. Different failure modes.”
- “Near-frontier quality at lower cost” 같은 문장은 **실제 same-condition adaptive 결과가 있을 때만**.

금지:

- model X beats model Y without same-condition run
- vendor score를 TAVONEL reproduced score로 표현
- cheapest/best claim without date/price/corpus

## 21.3 Data moat

- Document Performance Map
- Router Outcome Dataset
- Failure Zoo
- prompt/input/evaluator receipts
- operational failure corpus

세부 값은 trade secret; public은 aggregate evidence만.

---

# PART 22 — CURRENT REPOSITORY → V5 MIGRATION MATRIX

| Area | Current | v5 Action |
|---|---|---|
| Inspector/Recovery | Built | KEEP/ADAPT |
| Reconciler | Built | KEEP/ADAPT |
| Stable Identity | Built | KEEP |
| Entity/authority/temporal | Partial | ADAPT + Review |
| Diff/dependency/recompile/world state | Built | KEEP/ADAPT |
| Secure ingest | Missing | BUILD |
| Profiler/renderer/registry | Missing | BUILD |
| Legacy routing | Partial | SHADOW → REPLACE |
| **Model Arena / Oracle Dataset** | Missing | **BUILD BEFORE ACTIVE ROUTER** |
| Retrieval/API/MCP | Missing | BUILD |
| Health Scan | Missing | BUILD |
| Cinematic website | Partial | REPLACE visible experience |
| Connectors | Missing | BUILD staged |
| Billing | Missing | BUILD staged |
| Enterprise | Missing | BUILD after pilot |

Feature flags:

```text
V5_ARENA
V5_ARENA_BATCH
V5_DPM
V5_ORACLE_DATASET
V5_ROUTER_SHADOW
V5_ROUTER_CANARY
V5_API_PROVIDER_OPENAI
V5_API_PROVIDER_ANTHROPIC
V5_API_PROVIDER_GEMINI
V5_LOCAL_PADDLE
V5_LOCAL_DEEPSEEK_OCR2
```

---

# PART 23 — V5 DEPENDENCY-AWARE IMPLEMENTATION PHASES

## PHASE 0 — Baseline Freeze

- current repo/tests/deploy/evidence inventory
- v3.1 protected baseline tag
- v4/v5 migration matrix
- current claim hashes
- model/license/container inventory

**Exit:** historical evidence immutable and green baseline known.

## PHASE 1 — Contracts/Event/Schema Compatibility

- IDs/states/events/artifacts
- public/internal DTO
- Arena schemas
- outbox/inbox
- feature flags

**Exit:** Python/TS round-trip, N/N-1 compatibility.

## PHASE 2 — Industrial Ingestion

- direct R2 multipart/resume
- preflight/quarantine
- progressive processing
- quota/backpressure

**Exit:** large upload path safe/idempotent.

## PHASE 3 — Reference Renderer / Profiler / Model Registry

- reference render
- features/missing reasons
- exact model capabilities/licenses/prices
- provider adapters

**Exit:** every candidate has capability receipt.

## PHASE 4 — Model Arena Harness + Prompt Calibration **[NEW PRIORITY]**

- 100-page calibration corpus
- Track I/N/P/B
- raw + normalized artifact capture
- token/GPU/cost receipts
- official evaluator adapters

**Exit:** 50-case smoke and 200-page screening complete; no test leakage.

## PHASE 5 — Model Arena v1 1,000 Pages **[NEW PRIORITY]**

- 400 public
- 300 DART/SEC
- 200 Failure Zoo
- 100 Clean Control
- candidate Pareto analysis
- reproducibility subset
- single models + TAVONEL prototype adaptive baseline

**Exit:** DPM/Oracle matrix exists; survivors chosen by evidence.

## PHASE 6 — Execution Planner + Shadow Router

Arena oracle를 이용해 deterministic bootstrap policy를 만든다.

**Exit:** 100% shadow on named corpus/production-safe sample; no active routing yet.

## PHASE 7 — Scheduler/RunPod/Batch Lanes

- local adapters
- API batch adapters
- R2-before-ACK
- heartbeat/leases/circuit breaker
- cost ledger

**Exit:** chaos/idempotency/cost gates.

## PHASE 8 — Recovery/Review Integration

Protected recovery + semantic/operational split + alternate family + verifier.

**Exit:** historical recovery no regression; incremental recovery cost measured.

## PHASE 9 — Protected Compiler Core Production Integration

IR/provenance/identity/Office dual path/dedup/revision.

## PHASE 10 — Entity/Authority/Applicability/Temporal/Epistemic

## PHASE 11 — Diff/Impact/Recompile/Atomic World State

## PHASE 12 — Retrieval/Ask/Consumption Lineage

## PHASE 13 — Health Scan/Product Core

## PHASE 14 — Cinematic Website

## PHASE 15 — API/CLI/Connectors/Webhooks/SDK

## PHASE 16 — Read-only MCP

## PHASE 17 — Full Public 5,132 + Expanded DART/SEC Research Campaign

Arena Pareto survivors 2–4개 + TAVONEL adaptive만 확대.

**Exit:** same-condition publication receipts; limitations retained.

## PHASE 18 — Billing/Paid Pilot/GTM

## PHASE 19 — Enterprise Hardening

## PHASE 20 — Decision Replay/Write MCP/Simulation — GATED

---

# PART 24 — SOLO-FOUNDER CRITICAL PATH

가장 먼저:

```text
Baseline
→ Contracts
→ Ingestion
→ Profiler/Registry
→ 200-page Screening
→ 1,000-page Arena
→ Shadow Router
→ Recovery/Protected Core live
→ World State
→ Health Scan/Ask
→ Cinematic Site
→ One Connector/API
→ Pilot
```

Arena가 뒤로 밀리면 Router를 추측으로 구현하게 되므로 v5에서는 **Profiler/Registry 직후 우선 수행**한다.

---

# PART 25 — FMEA / NEW MODEL-ARENA RISKS

기존 v4 FMEA를 유지하며 아래를 추가한다.

| ID | Risk | Cause | Mitigation |
|---|---|---|---|
| ARENA-01 | PDF-native API가 image-only local보다 유리한 input을 받아 불공정 | input mode mismatch | Track I와 Track N 분리 |
| ARENA-02 | prompt를 final test에 맞춰 튜닝 | leakage | 별도 100-page calibration, final prompt freeze |
| ARENA-03 | 같은 문서 family가 train/holdout에 섞임 | page-level random split | family-level split/near-duplicate detection |
| ARENA-04 | vendor benchmark score를 local score와 직접 비교 | evaluator/corpus mismatch | same-condition rerun only |
| ARENA-05 | API normalization이 결과를 “고쳐” score 부풀림 | postprocessor overreach | deterministic normalization allowlist |
| ARENA-06 | Batch와 interactive behavior 차이 무시 | execution path drift | 30–50-case equivalence check |
| ARENA-07 | API 비용 추정이 plain-text token만 계산 | PDF/image token omission | actual usage receipts from pilot |
| ARENA-08 | Clean pages가 전체 평균을 지배 | easy distribution imbalance | slice reporting / weighted business analysis |
| ARENA-09 | Hard case만 보고 비싼 model을 primary로 선택 | no control group | Clean Control 100 pages |
| ARENA-10 | Public benchmark contamination | model training exposure | DART/SEC/Failure Zoo/held-out mutations 함께 사용 |
| ARENA-11 | 다중 candidate full-run 비용 폭증 | no screening | 50-case smoke → 200 screening → Pareto expansion |
| ARENA-12 | output truncation이 accuracy로 오인 | max output budget | truncation status/adequate max-output calibration |
| ARENA-13 | reasoning setting이 model간 과도하게 다름 | unfair optimization | standardized + optimized tracks separately |
| ARENA-14 | provider price 변동으로 old cost result 재현 불가 | live pricing | price snapshot/effective date receipt |
| ARENA-15 | API failure를 model failure로 집계 | provider outage | semantic vs provider failure separation |
| ARENA-16 | human adjudication bias | one reviewer | 2 annotators + adjudication + agreement |
| ARENA-17 | TAVONEL adaptive가 Arena 데이터를 과적합 | same data policy tuning | holdout freeze, policy versioning |
| ARENA-18 | frontier가 근소하게 좋다는 이유로 모든 page escalation | no marginal economics | cost per additional trusted/recovered page |

기존 핵심 FMEA도 계속 적용: upload resume, queue idempotency, RunPod provider-wide stop, false merge, ACL revoke, world-state atomicity, MCP auth, prompt injection, RLS, billing duplicate, website WebGL fallback, claim/IP leakage.

---

# PART 26 — REPOSITORY ARCHITECTURE, CI & RELEASE ENGINEERING

추가 benchmark 구조:

```text
benchmarks/
├ public/
├ dart/
├ sec/
├ arena/
│  ├ calibration/
│  ├ manifests/
│  ├ screening/
│  ├ eval/
│  ├ router-holdout/
│  └ reports/
├ failure-zoo/
├ office-reality/
├ multipage/
├ knowledge-evolution/
└ end-to-end/
```

Arena edit CI:

- manifest/hash check
- split leakage
- prompt freeze
- exact model registry ID
- evaluator revision
- normalization allowlist
- missing cost receipt
- claim generation disabled unless campaign FINALIZED

---

# PART 27 — AI-NATIVE SOLO-FOUNDER SOFTWARE FACTORY

Agent topology에 추가:

```text
benchmark-orchestrator
model-provider-adapter
prompt-calibration-auditor
corpus-split-auditor
cost-accountant
statistical-reviewer
router-oracle-analyst
```

Four-eyes:

```text
Implementer
→ deterministic CI
→ independent reviewer
→ evidence/statistical/security auditor
→ release manager
```

Arena prompt를 튜닝한 agent가 holdout 결과를 보고 같은 run의 claim을 승인하지 않는다.

---

# PART 28 — TEST CATALOG

신규 대표 tests:

```text
test_arena_calibration_and_eval_families_do_not_overlap
test_arena_case_manifest_is_immutable
test_same_render_hash_sent_to_all_track_i_models
test_native_pdf_track_is_not_merged_with_image_track
test_provider_prompt_is_frozen_before_eval
test_normalizer_cannot_invent_missing_table_cells
test_normalizer_cannot_generate_bbox_without_source
test_batch_interactive_equivalence_is_measured
test_model_registry_price_snapshot_is_pinned
test_api_cost_uses_actual_usage_receipt
test_local_cost_includes_retry_and_load_overhead
test_pareto_screening_preserves_unique_recovery_niche
test_clean_control_prevents_unnecessary_frontier_escalation
test_failure_zoo_reports_incremental_recovery_yield
test_router_holdout_is_not_used_for_policy_tuning
test_oracle_regret_is_reproducible
test_tavonel_adaptive_and_single_models_share_evaluator
test_reproducibility_subset_runs_three_times
test_public_claim_carries_input_track_and_prompt_track
```

기존 v4 tests 전부 계속 유효.

---

# PART 29 — OPERATIONS RUNBOOK INDEX

기존 RUN-001~020 유지 + 추가:

```text
RUN-021 Arena provider batch failure
RUN-022 Arena cost cap exceeded
RUN-023 Arena prompt/schema invalidation
RUN-024 Benchmark manifest contamination/leakage
RUN-025 Evaluator revision drift
RUN-026 Provider price/model retirement during campaign
RUN-027 Arena raw/normalized artifact mismatch
RUN-028 Router oracle recalibration rollback
```

---

# PART 30 — PRODUCT & WEBSITE COPY CONTRACT

Hero:

> **Your AI is only as reliable as the world it sees.**

Mechanism:

> **Every page doesn't need the same AI.**  
> **Failures shouldn't silently become knowledge.**  
> **Don't give AI more documents. Give it a world it can understand.**  
> **Finding information is easy. Knowing what is true now is harder.**  
> **When one fact changes, don't rebuild the world.**  
> **Every answer should have a way home.**

Arena/Evidence future copy — 승인된 경우만:

> **Same documents. Same evaluator. Different failure modes.**

> **We route by evidence, not model reputation.**

Forbidden:

- “GPT보다 정확하다” without same-condition approved campaign
- “frontier quality at 1/4 cost” before approved cost/quality receipt
- “100% accurate/perfect OCR/zero hallucination”

---

# PART 31 — R&D / EVALUATION BUDGET STRATEGY

## 31.1 기본 원칙

> **다음 $100가 어떤 uncertainty를 줄이는가?**

모든 모델에 5,132 pages를 바로 돌리지 않는다.

## 31.2 Stage-gated spend

### Stage 0 — capability/cost smoke

50 pages × candidates.

목적:

- exact input path 검증
- usage/token/GPU cost
- schema/output feasibility

### Stage 1 — 200-page screening

모든 candidate.

목적:

- obvious dominated models 제거
- unique specialist niches 발견

### Stage 2 — 1,000-page Arena

Pareto survivors + required controls + TAVONEL adaptive.

### Stage 3 — 5,132 full public

2–4 survivor paths only.

### Stage 4 — DART/SEC expansion

실제 enterprise value가 있는 slice만 확대.

## 31.3 Cost stop rules

- candidate projected cost exceeds budget with no unique expected value → stop
- first 50/200 pages에서 catastrophic issue → stop/repair before continuation
- provider batch retry cost cap
- full-run approval only after screening report

## 31.4 Ground truth cost

GPU/API보다 human adjudication이 더 비쌀 수 있다.

우선:

- official benchmark evaluator
- SEC XBRL/structured facts
- OpenDART metadata
- deterministic numeric/source anchors
- synthetic controlled mutations

을 사용해 자동 truth를 최대화하고, human은 ambiguous/high-risk에만.

---

# PART 32 — FINAL DEFINITION OF DONE v5

TAVONEL v5 launch candidate는 다음이 모두 사실일 때만 완료다.

## Architecture

1. Historical evidence와 protected core가 보존됐다.
2. Direct/resumable object-storage ingest가 production path다.
3. Profiler와 model registry가 versioned/capability/license/data-policy gated다.
4. Operational/semantic failure가 다른 recovery path를 가진다.
5. Every attempt가 immutable input/output/model/policy/cost lineage를 가진다.
6. Canonical IR/evidence/identity/authority/applicability/time/permission이 production path다.
7. Semantic diff→impact→selective recompile가 full-build equivalence를 통과한다.
8. World-state publish/rollback이 atomic이다.
9. Retrieval/Ask가 permission/time/authority를 similarity 전에 적용한다.

## Model Arena / Router **[NEW]**

10. Separate 100-page prompt calibration set이 존재하고 final Arena와 family overlap이 없다.
11. 1,000-page Model Arena manifest가 immutable/hash-bound다.
12. Arena가 Public 400 + DART/SEC 300 + Failure Zoo 200 + Clean Control 100을 포함한다.
13. Track I 동일 page image와 Track N native-provider path가 분리되어 보고된다.
14. Prompt/schema/settings가 evaluation 전에 freeze된다.
15. Raw provider output와 deterministic normalized output 모두 보존된다.
16. Batch/interactive equivalence sample이 존재한다.
17. API cost는 actual usage receipt, local cost는 actual GPU/runtime receipt를 사용한다.
18. Reproducibility subset이 3회 반복된다.
19. Model × slice × quality × latency × cost × failure × recovery map이 존재한다.
20. Router Oracle Dataset와 family-level train/calibration/holdout split이 존재한다.
21. Shadow Router의 oracle regret/trust violation/cost report가 있다.
22. Production canary는 holdout gate 통과 후에만 시작한다.
23. Single-model baselines와 TAVONEL adaptive pipeline이 동일 evaluator에서 비교된다.
24. Adaptive pipeline이 지면 결과를 숨기지 않는다.

## Evidence

25. Public benchmark denominator/evaluator/caveat가 유지된다.
26. Critical Numeric Fidelity가 DART/SEC에 존재한다.
27. Multi-page/Office/Evolution suite의 framework가 존재한다.
28. End-to-end Raw vs Basic RAG vs TAVONEL same-model experiment가 있다.
29. Negative result와 limitation이 claim pack에 유지된다.
30. Public claims는 approved hash-bound receipt로만 렌더된다.

## Security/Operations

31. Cross-tenant/RLS tests leak nothing.
32. ACL revoke가 reindex/recompile보다 먼저 차단된다.
33. Documents는 untrusted data이며 extraction model에 broad tools/network/secrets가 없다.
34. Provider data-policy가 Router candidate filtering에 실제 적용된다.
35. Backup/restore/delete/retention runbooks가 검증된다.
36. Internal usage ledger와 billing/provider invoice가 reconcile된다.
37. RunPod/provider-wide stop과 runaway cost circuit breaker가 검증된다.

## Product/Website

38. Landing이 MESS→RECOVER→WORLD→CHANGE→ASK를 체험시킨다.
39. 3 WOW moments가 decorative가 아니라 실제 product semantics다.
40. Ask가 generic chatbot으로 보이지 않는다.
41. Real app motion은 durable product events 기반이다.
42. Mobile/reduced-motion/no-WebGL/accessibility/CWV gate를 통과한다.
43. Health Scan이 real telemetry에서 finding을 만든다.
44. Evidence page가 Arena/benchmark methodology와 limitations를 보여준다.

## Commercial

45. 최소 1개 narrow paid pilot workflow가 작동한다.
46. unit economics가 $/Trusted Page 및 customer contribution margin으로 측정된다.
47. IP Disclosure Firewall과 claims gate가 publish path에 적용된다.
48. 없는 인증/성능/connector를 있다고 판매하지 않는다.

> **TAVONEL v5는 가장 좋은 모델을 선택했다고 완료되는 시스템이 아니다. 동일 현실에서 어떤 지능이 언제, 얼마에, 어떤 실패를 내는지 측정하고 그 증거를 실제 routing·recovery·knowledge integrity로 연결할 때 완료된다.**

---

# PART 33 — LAUNCH GATES

## Gate A — Internal Research Alpha

- Phase 0–5 완료
- 1,000-page Arena 완료
- no customer production routing

## Gate B — Internal Product Alpha

- Phase 6–12
- secure ingest → world state → Ask
- shadow/canary router

## Gate C — Design Partner

- Health Scan
- one connector/CLI
- explicit limitations
- bounded manual review

## Gate D — Paid Pilot

- usage/cost controls
- source permissions
- success metrics
- incident/rollback
- customer claim consent

## Gate E — Public Self-Serve

- upload/billing/support hardening
- deletion/retention
- reliable capacity
- evidence/security page
- onboarding/abuse controls

---

# PART 34 — FINAL AUTONOMOUS CLAUDE CODE COMMAND v5

```text
You are the lead implementation orchestrator for TAVONEL v5.0.

SOURCE OF TRUTH
Read TAVONEL_ULTIMATE_PRODUCTION_RESEARCH_IMPLEMENTATION_MASTERPLAN_v5.0_FINAL_KO_2026-08-11.md in full before changing code.
This v5 document supersedes conflicting v4/v3 phase, router, model-evaluation and benchmark instructions.
Historical benchmark artifacts, hashes, evaluator revisions and the FOLYNTA historical label are immutable.
Use v31-phase-gap-matrix.md only as a current-state baseline.

MISSION
Migrate the current repository to TAVONEL v5 through dependency-aware, evidence-gated phases.
Do not perform a monolithic rewrite.
Preserve the protected compiler core.
Build the Model Arena before activating the new Router so that routing policy is learned from same-condition evidence rather than assumptions.

PROTECTED CORE
Do not replace without same-condition no-regression evidence:
- akc_cir.inspection
- akc_cir.recovery_policy
- akc_cir.reconciler
- akc_cir.identity
- tested entity/authority/temporal/security logic
- akc_cir.semantic_diff
- akc_cir.dependency
- akc_cir.recompilation
- akc_cir.world_state
- all historical evidence artifacts and claim receipts

FIRST ACTIONS
1. Inspect repository, git state, deployments, migrations, CI, evidence, frontend, runtime, model/provider integrations and secrets references.
2. Run current tests/linters/builds and record known failures.
3. Verify historical artifact hashes; never rewrite them.
4. Create V5 migration, model-registry, Arena corpus, IP disclosure and cost-budget audit files.
5. Tag a clean protected baseline.
6. Implement canonical contracts and Arena schemas before feature coding that depends on them.

MODEL ARENA RULES
- Create a separate 100-page prompt calibration set. Do not tune prompts on final Arena pages.
- Build Model Arena v1 as exactly 1,000 pages unless a receipt documents a justified revision:
  400 Public Ground Truth,
  300 DART/SEC Real Corporate,
  200 TAVONEL Failure Zoo,
  100 Clean Control.
- Split Router data by document family, not random page.
- Evaluate Track I (same rendered page-image input) separately from Track N (provider-native best-practice PDF/document input).
- Preserve raw provider output. Normalization may only perform deterministic representation conversion and must not add missing semantic content.
- Pin exact model IDs/revisions/snapshots, provider API version, input mode, prompt/schema/settings, evaluator revision and price snapshot.
- Run a 50-case capability/cost smoke and 200-page screening before spending on the 1,000-page full Arena.
- Remove only Pareto-dominated candidates that have no unique recovery niche; keep required controls.
- Measure actual API usage and actual local GPU/runtime cost. Do not estimate PDF cost from text tokens alone.
- Test Batch vs interactive equivalence before treating them as identical execution paths.
- Run a stratified reproducibility subset three times.
- Record incremental recovery yield and cost per incremental recovered/trusted page.
- Compare single-model baselines with the TAVONEL adaptive pipeline using the same corpus and evaluator.
- Do not force the conclusion that hybrid/local is better. If API-only wins on trusted output, cost and operational simplicity, update the architecture through an ADR.

ROUTER RULES
- Optimize Minimum Expected Cost to Trusted Output, subject to trust/risk/permission/latency/data-policy constraints.
- No universal scalar blind quality score.
- Separate operational failure from semantic/model failure.
- Same-model retry only for operational/transient causes or explicit measured value.
- Semantic failure escalates to a materially independent family when possible.
- Frontier/general multimodal models are not truth oracles.
- Start Router in shadow mode. Activate only after family-level holdout gates.
- Never perform uncontrolled online exploration on customer production traffic.

EXECUTION RULES
- R2 is immutable artifact truth; PostgreSQL is workflow/permission/publish/billing truth.
- Queue delivery is at-least-once; consumers are idempotent.
- Worker ACK only after durable output and committed receipt.
- Never expose partial world state as ACTIVE.
- Permission revoke is enforced before background recompile/index cleanup.
- Treat documents as hostile data; extraction models get no broad tools/network/secrets.
- Public DTOs must never expose router features, thresholds, prompts, cost matrix or Outcome Dataset.

WEBSITE RULES
MESS → DISCOVER → ROUTE → RECOVER → WORLD → TRUTH → CHANGE → ASK → EVIDENCE → YOUR TURN.
Ask appears only after the compiled-world narrative and displays evidence/version/applicability/source trace.
Use actual product events in authenticated app; sample data must be labeled.
No generic AI chatbot, fake progress, decorative particle universe or unsupported metric.
Ship mobile, reduced-motion, no-WebGL and slow-network fallbacks.

EVIDENCE RULES
Every phase emits tests, benchmark/security/cost receipts, limitations, claim status and rollback.
Completion is never accuracy.
Different datasets/evaluators are never compared as same-condition scores.
The 36.9% low-quality scan limitation remains visible until a new same-condition campaign supersedes it.

AUTONOMY
Do not ask the user for choices already decided here.
Ask only for unavailable secrets/payment authorization, legal/business truth, customer consent or irreversible/destructive production action.

FINAL REPORT
Provide requirement-by-requirement status, Model Arena results, route oracle/regret, cost/trusted-page, recovery economics, benchmark/evidence receipts, deployment/rollback state, known limitations, claims approved/withheld, and paid-pilot readiness.
Do not claim completion from code presence alone.
```

---

# APPENDIX A — MODEL ARENA SCHEMAS

## A.1 Case manifest

```yaml
case:
  case_id: arena_...
  source_sha256: ...
  document_family_id: ...
  page_or_document: PAGE
  split: ROUTER_HOLDOUT
  origin: OLmOCR | OMNIDOC | PARSEBENCH | DART | SEC | FAILURE_ZOO | CLEAN_CONTROL
  slices:
    - TABLE_HEAVY
    - KOREAN
    - FINANCIAL
  risk_class: HIGH
  truth:
    evaluator_refs: [...]
    numeric_refs: [...]
  license/publication: ...
```

## A.2 Run receipt

```yaml
run:
  run_id: ...
  case_id: ...
  model_registry_id: ...
  exact_model_id: ...
  exact_revision: ...
  input_track: STANDARD_IMAGE | NATIVE_PROVIDER
  prompt_track: STANDARD | PROVIDER_OPTIMIZED
  batch_mode: true
  prompt_sha256: ...
  schema_sha256: ...
  input_artifact_sha256: ...
  raw_output_sha256: ...
  normalized_output_sha256: ...
  status: SUCCESS | PROVIDER_ERROR | TRUNCATED | INVALID_OUTPUT
  latency_ms: ...
  cost:
    actual_usd: ...
    price_snapshot_id: ...
  evaluator_receipts: [...]
```

## A.3 Router oracle row

```yaml
oracle:
  case_id: ...
  permitted_paths: [...]
  path_outcomes:
    - path: mineru
      trusted: true
      cost_usd: ...
      latency_ms: ...
      catastrophic: false
    - path: claude_batch
      trusted: true
      cost_usd: ...
      latency_ms: ...
  cheapest_trusted_path: mineru
  highest_quality_path: claude_batch
  business_risk_optimal_path: mineru
```

---

# APPENDIX B — METRICS & COST FORMULAE

```text
Output Completion
= produced outputs / offered inputs

Recovery Rate
= recovered / recovery-required

Trusted Page Yield
= pages meeting required trust gate / eligible pages

Cost per Trusted Page
= total attributable compute/API cost / trusted pages

Incremental Recovery Yield(B|A)
= failures of A recovered by B / failures of A presented to B

Cost per Incremental Recovery
= incremental escalation cost / incrementally trusted pages

Router Oracle Regret
= selected path loss - best permitted oracle path loss

Frontier Tail Fraction
= pages sent to expensive verifier / eligible pages

Recompile Reduction
= 1 - recompiled eligible units / total eligible units

World Sync Latency
= active new world-state time - source change observed time
```

External reporting은 각 metric의 denominator, corpus, version, time window, exclusions를 동반한다.

---

# APPENDIX C — OFFICIAL SOURCE LEDGER (2026-08-11 SNAPSHOT)

실행 직전 다시 확인하고 Registry에 pin한다.

## OpenAI

- Models catalog: https://developers.openai.com/api/docs/models
- GPT-4o model: https://developers.openai.com/api/docs/models/gpt-4o
- File inputs: https://developers.openai.com/api/docs/guides/file-inputs
- Image/vision inputs: https://developers.openai.com/api/docs/guides/images-vision
- Batch: https://developers.openai.com/api/docs/guides/batch

## Anthropic

- Models overview: https://docs.anthropic.com/en/docs/about-claude/models/overview
- Pricing: https://docs.anthropic.com/en/docs/about-claude/pricing
- PDF support: https://platform.claude.com/docs/en/build-with-claude/pdf-support
- Vision: https://docs.anthropic.com/en/docs/build-with-claude/vision
- Message Batches: https://platform.claude.com/docs/en/build-with-claude/batch-processing

## Google Gemini

- Document processing: https://ai.google.dev/gemini-api/docs/document-processing
- Batch API: https://ai.google.dev/gemini-api/docs/batch-api
- Pricing: https://ai.google.dev/gemini-api/docs/pricing

## Local / Open document models

- MinerU: https://github.com/opendatalab/MinerU
- PaddleOCR-VL-1.6: https://paddlepaddle.github.io/PaddleOCR/main/en/version3.x/algorithm/PaddleOCR-VL/PaddleOCR-VL-1.6.html
- DeepSeek-OCR-2: https://huggingface.co/deepseek-ai/DeepSeek-OCR-2

## Benchmarks

- olmOCR: https://github.com/allenai/olmocr
- olmOCR-bench dataset: https://huggingface.co/datasets/allenai/olmOCR-bench
- OmniDocBench: https://github.com/opendatalab/OmniDocBench
- ParseBench: https://github.com/run-llama/ParseBench
- MPDocBench-Parse paper: https://arxiv.org/abs/2605.22100
- Dr. DocBench paper: https://arxiv.org/abs/2606.01393

## DART / SEC

- OpenDART: https://opendart.fss.or.kr/guide/main.do
- SEC EDGAR APIs: https://www.sec.gov/search-filings/edgar-application-programming-interfaces

## Infrastructure / MCP / Security

- Cloudflare R2: https://developers.cloudflare.com/r2/
- Cloudflare Queues: https://developers.cloudflare.com/queues/
- RunPod: https://docs.runpod.io/
- MCP specification: https://modelcontextprotocol.io/specification/2026-07-28
- PostgreSQL RLS: https://www.postgresql.org/docs/current/ddl-rowsecurity.html
- OWASP File Upload: https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html
- OWASP Prompt Injection: https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html

---

# APPENDIX D — NON-CLAIMS / WITHHELD UNTIL MEASURED

본 v5가 설계했다고 해서 다음이 현재 사실이라는 뜻은 아니다.

- GPT/Claude/Gemini/DeepSeek/Paddle/MinerU의 TAVONEL Arena 순위
- GPT-4o Batch가 TAVONEL에 “충분하다”는 주장
- API-only가 local보다 싸다/비싸다는 일반화
- TAVONEL adaptive가 frontier single model보다 싸고 동급이라는 주장
- Model Arena 1,000-page 결과
- DART/SEC Critical Numeric Fidelity score
- Router Oracle Regret / route improvement
- Trusted Page Yield
- Model-specific cost per 1,000 pages
- Batch/interactive quality equivalence
- MPDocBench/Dr.DocBench result
- Office Reality Suite result
- Knowledge Evolution Suite result
- customer outcome / SOC 2 / ISO 27001 / patent grantability

이들은 해당 Phase의 immutable campaign receipt와 claim approval가 있을 때만 공개 claim으로 승격한다.

---

# FINAL NORTH STAR v5

> **TAVONEL의 moat는 가장 강한 OCR 모델을 가지고 있는 것이 아니다.**
>
> **동일한 현실을 여러 종류의 지능에게 실제로 읽혀보고, 어떤 문서에서 누가 어떤 실패를 내고 얼마의 비용이 드는지 증거로 축적한 뒤, 각 입력을 가장 경제적으로 신뢰 가능한 지식으로 만드는 경로를 선택하고, 실패를 복구하고, 출처·시간·관계·권한을 보존하며, 현실 변화가 생기면 영향을 받은 지식과 Agent Context만 다시 동기화하는 전체 시스템이다.**

고객이 사이트에서 느껴야 할 최종 감정:

> **“문서 AI인 줄 알았는데, 우리 AI가 살아갈 세계를 만들고 계속 최신으로 유지하는 시스템이었네.”**

---

# END OF TAVONEL ULTIMATE PRODUCTION RESEARCH & IMPLEMENTATION MASTERPLAN v5.0 FINAL
