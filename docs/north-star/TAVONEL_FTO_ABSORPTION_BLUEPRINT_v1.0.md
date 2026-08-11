# TAVONEL — TECHNOLOGY ABSORPTION · FTO-AWARE IMPLEMENTATION BLUEPRINT v1.0 FINAL
## 선행 특허·논문·오픈소스 기술 흡수 분석 + 적용 설계 + A/B 평가 + 라이선스/FTO + 특허/논문 전략

**문서 상태:** FINAL IMPLEMENTATION BLUEPRINT / RESEARCH & LEGAL INTAKE SOURCE OF TRUTH  
**작성 기준:** 2026-08-11 KST  
**적용 대상:** `TAVONEL_ULTIMATE_PRODUCTION_RESEARCH_IMPLEMENTATION_MASTERPLAN_v5.0_FINAL_KO_2026-08-11.md`  
**공개 브랜드:** **TAVONEL — The Knowledge Compiler**  
**핵심 목적함수:** **Minimum Cost to Trusted Output**  
**핵심 제품 질문:** **원본 문서 하나가 바뀌면 어떤 AI의 어떤 지식이 지금부터 틀린가?**  
**핵심 구현 원칙:** **흡수는 복제가 아니다. 표준은 매핑하고, 오픈소스는 검증 후 사용하며, 논문은 clean-room challenger로 구현하고, 활성 특허는 design-around한다.**

---

# 0. 문서의 지위와 경계

## 0.1 이 문서가 해결하는 문제

기존 TAVONEL v5는 다음을 이미 최상위 계약으로 정의했다.

```text
Same Corpus
→ Multi-Family Model Arena
→ Document Performance Map
→ Router Oracle Dataset
→ Shadow Router
→ Recovery
→ Trusted Knowledge IR
→ Change Intelligence
→ Versioned Agent World State
```

이번 문서는 그 위에 다음 질문의 답을 붙인다.

1. 선행 논문·특허·오픈소스의 어떤 기술이 TAVONEL 어느 모듈과 대응하는가?
2. 그 기술을 코드로 직접 사용할 수 있는가, 원리만 독립 구현해야 하는가, 아니면 적극적으로 회피 설계해야 하는가?
3. 기존 방법을 흡수했을 때 TAVONEL 구조를 어떻게 더 강하게 바꿀 것인가?
4. 실제로 좋아졌는지 어떤 동일 조건 실험으로 증명할 것인가?
5. 무엇이 공개 가능한 표준/오픈소스이고, 무엇을 우리 특허 또는 영업비밀로 남길 것인가?

## 0.2 이 문서가 아닌 것

본 문서는 다음을 대신하지 않는다.

- 변리사의 국가별 Freedom-to-Operate 법률의견
- 특정 특허 청구항에 대한 침해/비침해 최종 판단
- 오픈소스·모델·데이터셋 라이선스의 법률 자문
- 아직 공개되지 않은 특허 출원 검색
- 실제 Model Arena 결과
- 아직 수행하지 않은 A/B 실험의 성능 주장

공개 특허의 법적 상태 표시는 검색 시점의 참고정보이며, 상용 출시 전에는 미국·한국·PCT/EP 등 목표 국가별 전문 검토가 필요하다.

## 0.3 근거 표기

이 문서의 판단은 내부적으로 네 종류로 구분한다.

- **[REPO-EVIDENCE]** 업로드된 TAVONEL v5, gap matrix, FOLYNTA benchmark, 현재 repository 감사 로그에서 확인된 사실
- **[PRIMARY-RESEARCH]** 논문 원문, 표준기관, 공식 오픈소스 저장소, 공식 특허 공개문헌에서 확인된 사실
- **[V1-DESIGN]** 위 근거를 TAVONEL에 적용하기 위한 본 문서의 설계 결정
- **[LEGAL-HOLD]** 라이선스·특허·모델 약관 검토 전 코드/배포를 금지하는 항목

## 0.4 충돌 시 우선순위

1. 본 문서의 `LEGAL-HOLD`, `DO NOT COPY`, `DESIGN-AROUND` 규칙
2. TAVONEL v5의 protected core / evidence / migration / phase gate
3. 실제 repository와 immutable receipt
4. 본 문서의 challenger 설계
5. 외부 논문·프로젝트의 예제 구현

외부 연구가 좋아 보여도 기존 protected core를 같은 조건의 no-regression 증거 없이 교체하지 않는다.

---

# 1. Executive Decision — 무엇을 흡수할 것인가

## 1.1 즉시 채택할 것 — P0/P1

### A. `CompilationActionKey + Content-Addressable Artifact Cache`

Bazel의 action cache/CAS와 Nix의 content addressing 원리를 TAVONEL 방식으로 축약하여 즉시 적용한다.

```text
Evidence/Input hashes
+ compiler/parser/model exact revisions
+ prompt/schema/policy versions
+ deterministic parameters
= CompilationActionKey

ActionKey hit
→ immutable output reuse

ActionKey miss
→ execute
→ validate
→ R2 CAS write
→ receipt commit
```

이 기능은 GPU/API 중복 비용, 동일 결과 재처리, selective recompilation 비용을 동시에 줄인다.

### B. `Alignment-First Heterogeneous Semantic Diff`

현재 semantic diff 앞에 다음 계층을 challenger로 추가한다.

```text
Version A / Version B
→ typed elements: text/table/formula/figure
→ spatial + structural + content compatibility
→ one-to-one cross-version alignment
→ type-specific difference reasoning
→ stable claim identity / semantic diff
```

텍스트 위치 이동이나 표 재배치가 의미 변경으로 오판되는 것을 줄이는 목적이다.

### C. `Adaptive-k Retrieval`

고정 Top-K를 기본값으로 두지 않고 query별 similarity distribution으로 context size를 결정하는 lightweight baseline을 추가한다. BSD-3-Clause 구현을 dependency 후보로 평가할 수 있다.

### D. `PROV-O + SHACL Export/Validation Mapping`

TAVONEL Canonical IR이 내부 truth를 유지하되 외부 ontology/RDF export에는 W3C PROV-O와 SHACL을 활용한다.

- PROV-O: Entity / Activity / Agent / derivation / revision / primary source 매핑
- SHACL: exported graph 구조·필수 provenance·시간·권한 metadata 검증

내부 schema를 RDF에 종속시키지 않는다. 표준은 interoperability adapter다.

### E. `Access-Path Conformance Matrix`

현재 PostgreSQL RLS/worker authorization 작업에 Governed Shared Memory의 실제 실패를 반영한다.

```text
Search
GET by ID / guessed UUID
Graph traversal
Evidence lookup
Export
Webhook
API
MCP resource/tool
```

모든 접근 경로가 동일한 tenant/project/permission 결과를 내는지 자동 비교한다.

## 1.2 Arena challenger로 먼저 검증할 것 — P1/P2

### F. `Marginal-Gain Router`

RouteLMT의 핵심 통찰을 document execution에 맞게 변형한다.

> “이 페이지가 어려운가?”보다 “대체 모델이 현재 모델보다 얼마나 더 좋아질 가능성이 있는가?”를 예측한다.

TAVONEL의 기존 blind quality detector가 실패했으므로, absolute quality/difficulty 대신 **incremental trusted-output gain**을 직접 학습하는 challenger가 더 합리적이다.

### G. `RouteLLM Baseline Adapters`

RouteLLM의 Apache-2.0 evaluation/router framework에서 다음을 벤치마크 baseline으로 흡수한다.

- matrix-factorization preference router
- similarity-weighted ranking router
- classifier router
- threshold/calibration evaluation pattern

코드를 core에 복사해 고정하지 않고 `arena/baselines/routellm_adapter`로 격리한다.

### H. `Visual Retrieval Lane — ColPali/ColQwen + ViDoRe`

문서 파싱 결과만으로 retrieval하지 않는다.

```text
Text/Knowledge Retrieval
+
Visual Page Late-Interaction Retrieval
+
Lexical/Metadata Retrieval
→ Rerank / evidence package
```

표·차트·도식·복잡한 시각 레이아웃에서 visual lane이 incremental recall을 만드는지 ViDoRe 및 TAVONEL corporate QA로 검증한다.

### I. `Version-Aware Intent Routing`

VersionRAG에서 다음 원리를 clean-room challenger로 흡수한다.

- latest/current query
- historical as-of query
- change/diff query
- explicit version query
- implicit version conflict query

질문 intent에 따라 version graph 경로와 time/authority filtering을 다르게 적용한다.

### J. `State-to-Draft Freshness Auditor`

최종 Answer 생성 후 “답에 명시되지 않은 낡은 전제”를 찾는 후단 검증기를 추가한다.

```text
World-state transitions
→ draft answer
→ old→new candidate transitions
→ evidence quotation pinning
→ chronology validation
→ stale dependency found?
   PASS / REPAIR / ABSTAIN
```

Retrieval이 최신이어도 LLM이 오래된 전제를 reasoning에 재사용하는 문제를 방어한다.

### K. `Tamper-Evident Provenance Ledger`

MemLineage의 원리를 일반적으로 흡수하되 코드는 독립 구현한다.

- hash-chained/Merkle-batched receipt
- per-tenant signing key or managed signing service
- derived-from DAG
- verification summary

초기에는 모든 knowledge row를 실시간 Merkle tree에 넣지 않는다. publication/enterprise audit/agent action receipt부터 시작한다.

## 1.3 후순위 또는 규모 증거 후에만 — P3+

- Cedar: action/policy schema validation과 application-level authorization 후보
- OpenFGA: cross-application object relationship 권한이 PostgreSQL RLS로 감당하기 어려워질 때
- Differential Dataflow: dependency graph incremental maintenance가 실제 병목일 때
- Full cryptographic per-memory/claim signing: 엔터프라이즈 수요와 비용을 확인한 뒤
- SmartChunk RL planner: Adaptive-k/structure-aware retrieval보다 충분한 추가 이득이 있을 때
- VisRAG end-to-end parsing-free path: visual challenger가 source-evidence contract를 만족할 때

## 1.4 사용하지 않거나 design-around할 것

### Active patent / RED

- IBM `US11605028B2`: first model → QoS 비교 → second model 조건 실행이라는 넓은 sequential inference claim과 직접 겹치는 표현을 피한다.
- Palantir Universal Data Pipeline family: generic versioned dataset/build catalog/stale dependency/selective rebuild를 우리 독립 발명처럼 구현·마케팅하지 않는다.
- Palantir propagated-deletion family: generic source change→derivation graph→downstream rebuild claim을 피한다.
- Oracle dynamic lineage family: generic provenance+temporal lineage를 독립 발명으로 주장하지 않는다.

### No explicit code license / YELLOW

- RepoDoc repository
- VersionRAG repository(명확한 라이선스 확인 전)
- SmartChunk implementation(공식 재사용 가능한 code license 확인 전)
- Heterogeneous Cross-Version Differencing implementation
- MemLineage / StateAuditor implementation

논문을 읽고 기능 요구사항과 평가 baseline은 만들 수 있지만, 소스 코드를 복사·번역·포팅하지 않는다.

---

# 2. Adoption Classification

| 등급 | 의미 | 허용 행위 | 필수 조건 |
|---|---|---|---|
| **BLUE** | 공개 표준 | adapter/export/validation 구현 | 표준 version pin + conformance tests |
| **GREEN** | 명확한 permissive OSS | dependency/fork/adapter 가능 | exact commit/license/NOTICE/SBOM/model license 확인 |
| **YELLOW** | 논문은 공개, 코드 라이선스 불명/부재 | clean-room 독립 구현·baseline 재현 | 코드 복사 금지, ADR, 독립 구현 evidence |
| **ORANGE** | 코드와 model/data 약관이 다름 | code 사용 가능, weights/data는 별도 승인 | commercial terms/data policy/model license review |
| **RED** | 활성 특허 또는 높은 FTO 위험 | design-around 및 비교 분석만 | 변리사 claim chart 전 상용 핵심 경로 금지 |
| **GRAY** | 현재 범위 대비 과도한 복잡도 | 보류 | 측정된 병목/유료 수요 필요 |

## 2.1 중요한 법적 원칙

1. **OSS license permission ≠ patent FTO.**
2. Apache-2.0의 contributor patent grant는 해당 contributor가 허여할 수 있고 contribution/work에 필연적으로 침해되는 범위에 관한 것이지, 제3자 특허까지 정리해주지 않는다.
3. GitHub public repository에 LICENSE가 없으면 상업적 복사·수정·배포 권한이 있다고 가정하지 않는다.
4. code license와 model weight license, dataset license, hosted API terms는 별개다.
5. 논문 아이디어의 독립 구현도 특허 침해 가능성과는 별개다.
6. FTO는 목표 국가와 실제 제품 청구항 조합을 기준으로 판단한다.

---

# 3. Current TAVONEL Module Map

## 3.1 Protected Core — 유지

[REPO-EVIDENCE]

```text
akc_cir.inspection
akc_cir.recovery_policy
akc_cir.reconciler
akc_cir.identity
entity / authority / temporal / security labels
akc_cir.semantic_diff
akc_cir.dependency
akc_cir.recompilation
akc_cir.world_state
```

이들은 외부 기술 흡수로 “교체”하지 않는다. challenger adapter를 붙이고 같은 조건에서 no-regression이 확인된 경우에만 promotion한다.

## 3.2 현재 공백 또는 부분 구현

[REPO-EVIDENCE]

- secure ingestion/preflight/R2 manifest
- reference renderer/page profiler/model registry
- calibrated economic router/route receipt
- Model Arena/Oracle Dataset
- structure-aware/adaptive retrieval
- API/CLI/MCP/connectors
- Health Scan
- cinematic product experience
- enterprise hardening

외부 기술 흡수는 이 공백을 우선 채운다. 이미 잘 동작하는 compiler core를 연구 욕심으로 재작성하지 않는다.

## 3.3 현재 benchmark가 주는 설계 제약

[REPO-EVIDENCE]

- 5,132 public documents
- 99.98% completion은 accuracy가 아님
- recovery-required 1,797 중 1,796 recovery
- olmOCR 80.6%
- low-quality scans 36.9%
- recovery ON 80.6 vs OFF 53.7
- 384/384 byte-identical across 3 repeats
- blind ranking이 random/length-only를 이기지 못함
- healthy raw GPU $1.23/1k pages, whole campaign $5.92/1k pages

따라서 흡수 기술은 다음을 증명해야 한다.

```text
평균 accuracy만 상승         → 불충분
hard slice 회복              → 필요
operational cost 포함        → 필요
reproducibility              → 필요
source/evidence preservation → 필요
trust gate/abstention        → 필요
```


---

# 4. Master Technology Absorption Matrix

## 4.1 Routing / Execution / Risk

| External method | Primary contribution | TAVONEL mapping | License / IP | Decision |
|---|---|---|---|---|
| **AdaParse** | document/page-wise parser assignment, predicted accuracy + hardware/resource orchestration | Profiler, Model Arena baseline, Router challenger | MIT code; generic routing prior art dense | **GREEN — benchmark adapter, 일부 scheduling pattern 흡수** |
| **RouteLLM** | preference router, MF/weighted ranking/BERT, threshold evaluation | Model Arena router baselines | Apache-2.0 | **GREEN — isolated baseline dependency** |
| **RouteLMT** | absolute difficulty보다 strong-vs-weak marginal gain 예측 | Economic Router objective | paper-only implementation basis | **YELLOW — clean-room challenger, HIGH priority** |
| **SCoRE / SCRC** | selected outputs에 대한 conformal risk control | TrustGate calibration research | paper; assumptions strict | **YELLOW — offline challenger only** |
| **BCEA** | answer / acquire evidence / abstain 3-way policy, acquisition 후 재보정 필요 | Recovery evidence acquisition | paper-only | **YELLOW — structured crop/rerender path experiment** |
| **IBM US11605028B2** | first model QoS threshold → second model | broad sequential model inference | active US patent | **RED — design-around marker** |

## 4.2 Document Version / Diff / Identity

| External method | Primary contribution | TAVONEL mapping | License / IP | Decision |
|---|---|---|---|---|
| **Heterogeneous Element-Aware Cross-Version Differencing** | typed element alignment before diff; spatial/content/structure compatibility | pre-diff alignment layer | paper, reusable code not established | **YELLOW — clean-room HIGH priority** |
| **VersionRAG** | hierarchical version graph + intent-specific retrieval | Revision Graph, Ask intent routing | repo license not confirmed | **YELLOW — concepts/benchmark only** |
| **RepoDoc** | bidirectional impact propagation + selective regeneration | Dependency/Impact challenger | repo has no visible LICENSE | **YELLOW/RED — clean-room algorithm baseline; Palantir FTO overlay** |
| **Palantir Universal Data Pipeline** | versioned datasets, build catalog, stale dependency rebuild | design-around boundary for Knowledge CI/CD | active patent family | **RED — do not mirror generic build-catalog claim** |
| **Palantir propagated deletion** | source deletion/change propagation downstream | design-around boundary | active patent family | **RED** |
| **Oracle dynamic lineage** | temporal provenance/lineage lifecycle | design-around boundary | active family | **RED** |

## 4.3 Retrieval / Chunking / Visual Evidence

| External method | Primary contribution | TAVONEL mapping | License / IP | Decision |
|---|---|---|---|---|
| **Adaptive-k Retrieval** | query-specific number of passages, no tuning/extra LLM | Retrieval candidate sizing | BSD-3-Clause | **GREEN — immediate baseline** |
| **SmartChunk** | query-aware abstraction/chunk planner | multi-granular retrieval | paper/code terms not pinned | **YELLOW — challenger after simple baselines** |
| **Structure-aware tabular chunking** | row-tree/key-value/structural boundary preservation | table chunk compiler | paper | **YELLOW — clean-room HIGH value** |
| **SetR / set-level passage selection** | passage set selection rather than independent top-k | context package optimization | BSD-3-Clause source candidate | **GREEN — later benchmark** |
| **FunnelRAG** | coarse-to-fine retrieval | retrieval execution planner | research | **YELLOW — benchmark pattern** |
| **ColPali/ColQwen** | visual late-interaction page retrieval | visual retrieval lane | code license to pin; model licenses differ | **ORANGE — ColQwen Apache weights preferred; Gemma variants separate review** |
| **ViDoRe** | visual document retrieval benchmark | Visual Retrieval Arena | MIT | **GREEN — benchmark dependency** |
| **VisRAG** | parsing-free visual RAG | visual control baseline | Apache-2.0 code; model weights conditional | **ORANGE — benchmark only first** |
| **Infinity** | high-throughput serving for embeddings/rerank/ColPali | embedding/retrieval serving | MIT | **GREEN — serving candidate if benchmark wins** |

## 4.4 Provenance / Integrity / Interoperability

| External method | Primary contribution | TAVONEL mapping | License / IP | Decision |
|---|---|---|---|---|
| **W3C PROV-O** | interoperable Entity/Activity/Agent provenance | RDF/JSON-LD export adapter | W3C Recommendation | **BLUE — adopt** |
| **W3C SHACL** | RDF graph validation constraints/results/severity | ontology export validation | W3C Recommendation | **BLUE — adopt** |
| **pySHACL** | SHACL validation engine | export conformance test | Apache-2.0 | **GREEN — candidate dependency** |
| **OpenLineage** | Run/Job/Dataset events + custom facets | execution/compile lineage interoperability | Apache-2.0 | **GREEN/BLUE — use adapter, not internal truth** |
| **SLSA provenance** | verifiable where/when/how artifact produced | model/parser/container/compile artifact attestation | official specification | **BLUE — adapt concepts** |
| **in-toto** | ordered step attestations and supply-chain integrity | compiled artifact attestation envelope | Apache-licensed ecosystem | **BLUE/GREEN — evaluate minimal envelope** |
| **Witness** | attestation collection/verification | CI/release evidence signing | Apache-2.0 | **GREEN — optional enterprise/release track** |
| **MemLineage** | signed entries + Merkle log + derivation DAG | tamper-evident knowledge/agent lineage | paper/no verified code license | **YELLOW — independent prototype** |

## 4.5 Memory Freshness / Governance / Authorization

| External method | Primary contribution | TAVONEL mapping | License / IP | Decision |
|---|---|---|---|---|
| **StateAuditor** | state→draft reverse audit for hidden stale dependencies | Ask post-generation freshness auditor | paper-only | **YELLOW — HIGH priority challenger** |
| **Governed Shared Memory** | leakage/stale/contradiction/provenance failure modes; direct-ID bypass finding | access-path tests, memory/world governance | paper | **YELLOW — requirements absorption** |
| **GateMem** | utility + access control + forgetting benchmark | multi-principal knowledge governance suite | paper/dataset terms to pin | **YELLOW — benchmark concepts** |
| **Cedar** | formally analyzable RBAC/ABAC policy + schema validation | application/action policy layer | Apache-2.0 | **GREEN but HOLD — evaluate after RLS plane stabilizes** |
| **OpenFGA** | Zanzibar-inspired ReBAC/FGA | cross-system relationship permissions | Apache-2.0 | **GREEN but HOLD — only on measured need** |
| **OPA** | general-purpose policy engine | infra/API policy option | Apache-2.0 | **GREEN but not preferred for initial app authorization** |

## 4.6 Incremental Build / Reuse

| External method | Primary contribution | TAVONEL mapping | License / IP | Decision |
|---|---|---|---|---|
| **Bazel remote cache** | action hash→result metadata + CAS | CompilationActionKey / R2 CAS | open tooling/design pattern | **BLUE/GREEN principle — adopt now** |
| **Nix content addressing** | output identity from content, deterministic reuse | immutable artifact identity | open ecosystem/design pattern | **BLUE/GREEN principle — adopt now** |
| **Differential Dataflow** | efficient incremental computation over changing data | large-scale dependency/impact engine | permissive OSS; exact version pin needed | **GRAY — scale-triggered experiment only** |

---

# 5. Target Architecture After Absorption

```text
SOURCE / CONNECTOR / UPLOAD
        ↓
PRE-FLIGHT + REFERENCE RENDER
        ↓
PAGE/DOCUMENT PROFILER
        ↓
┌──────────────────────────────────────────────────────────┐
│ ROUTING CONTROL PLANE                                    │
│ Deterministic safety policy                              │
│ + Marginal-gain economic selector                        │
│ + data-policy/license/provider-health constraints        │
└──────────────────────────────────────────────────────────┘
        ↓
EXECUTION ATTEMPT
        ↓
SOURCE-GROUNDED INSPECTION
        │
        ├ PASS → trusted candidate
        │
        ├ ACQUIRE → crop/rerender/native path/additional evidence
        │
        ├ RECOVER → same execution or independent model family
        │
        └ ABSTAIN/REVIEW
        ↓
DOCUMENT RECONCILER
        ↓
CANONICAL KNOWLEDGE IR
        ↓
PROV-O/OpenLineage adapters + immutable receipt
        ↓
HETEROGENEOUS ELEMENT ALIGNMENT ACROSS VERSIONS
        ↓
STABLE CLAIM IDENTITY + AUTHORITY/APPLICABILITY/TIME
        ↓
TYPED DEPENDENCY + BIDIRECTIONAL IMPACT
        ↓
CompilationActionKey / CAS reuse
        ↓
SELECTIVE RECOMPILE
        ↓
SHACL/internal invariant validation
        ↓
ATOMIC WORLD-STATE PUBLISH
        ↓
MULTI-REPRESENTATION RETRIEVAL
├ lexical
├ compiled text/claim/entity/table
├ version graph
└ visual page late-interaction
        ↓
LLM DRAFT
        ↓
STATE-TO-DRAFT FRESHNESS AUDITOR
        ↓
ANSWER / REPAIR / ABSTAIN
        ↓
AGENT CONSUMPTION + TAMPER-EVIDENT LINEAGE
```

## 5.1 기존 protected core와의 관계

```text
NEW challenger layers
    ↓
compatibility adapters
    ↓
EXISTING protected core
```

- Inspector/Recovery는 유지하고 새로운 evidence-acquisition operator를 추가한다.
- Identity는 유지하고 alignment-first 후보를 입력 보조자로 둔다.
- Semantic Diff/Dependency/Recompile/World State는 유지하고 CAS/action-key 및 bidirectional explanation을 추가한다.
- 새 retrieval/freshness auditor는 core 뒤의 consumption plane에 추가한다.

---

# 6. Workstream A — Dual-Layer Economic Router

## 6.1 문제 정의

기존 blind quality score는 실제 campaign에서 유효한 selection signal이 아니었다. 따라서 router는 다음 두 질문을 분리한다.

```text
Q1. 이 route가 보안·신뢰·입력·license/data-policy 조건상 허용되는가?
Q2. 허용된 route 중 어느 것이 incremental trusted-output gain 대비 가장 경제적인가?
```

Q1은 deterministic policy, Q2는 Arena-trained selector가 담당한다.

## 6.2 Route policy layers

### Layer 0 — Admission

- model capability verified
- exact revision pinned
- provider data policy permits tenant classification
- input modality supported
- license approved
- budget/circuit healthy

### Layer 1 — Deterministic Safety

- high-risk numeric/contract/safety page
- unsupported blank/encrypted/corrupt
- prompt-injection classification
- required evidence type
- no-network/self-hosted requirement

### Layer 2 — Marginal Gain Prediction

각 candidate `m`에 대해 다음을 예측한다.

```text
P(trusted | page, current_attempt, m)
IncrementalGain(m | current_attempt)
ExpectedCost(m)
ExpectedLatency(m)
CorrelationPenalty(m, prior_models)
```

### Layer 3 — Decision

```text
minimize Expected Total Loss

subject to:
- trust floor
- business risk
- permission/data policy
- deadline
- remaining budget
```

## 6.3 Canonical schemas

```yaml
route_candidate:
  candidate_id: rc_...
  model_registry_id: ...
  execution_lane: LOCAL_FAST | LOCAL_BULK | API_SYNC | API_BATCH
  family: DOCUMENT_SPECIALIST | GENERAL_MULTIMODAL | VERIFIER
  estimated:
    trusted_probability: null
    marginal_gain: null
    cost_usd: null
    latency_ms: null
  constraints:
    data_policy_allowed: true
    license_allowed: true
    modality_supported: true
  correlation_group: ...
  calibrated_on: null
```

```yaml
route_decision:
  route_decision_id: rd_...
  profile_id: ...
  attempt_id: ...
  deterministic_policy_version: ...
  learned_selector_version: ...
  calibrated: false
  selected_candidate_id: ...
  public_reason_codes:
    - COMPLEX_TABLE
    - PRIMARY_ATTEMPT_FAILED_STRUCTURE_GATE
  internal_receipt_ref: secret://...
  budget_before: ...
  budget_after_reserved: ...
```

## 6.4 Baselines in Model Arena

동일 1,000-page Arena에서 최소:

1. always champion
2. always cheapest API
3. always strongest API
4. static route class
5. AdaParse-style predicted parser quality
6. RouteLLM MF
7. RouteLLM BERT/classifier
8. marginal-gain selector
9. marginal-gain + deterministic guard
10. TAVONEL full recovery policy

## 6.5 Avoiding IBM sequential-inference claim overlap

[V1-DESIGN / LEGAL-HOLD]

독립 발명과 상용 구현 문서에서 다음 표현만으로 기술을 정의하지 않는다.

```text
first result < QoS threshold
→ run second model
```

TAVONEL의 실제 중심은:

- source-derived failure classification
- materially different recovery operation by failure cause
- evidence acquisition/rerender vs operational retry vs independent-family semantic recovery
- compiled evidence/structural invariant gate
- trusted-state promotion or fail-closed
- multi-stage outcome lineage

상용 출시 전 Patent 1 claim chart와 함께 FTO counsel review가 필요하다.

## 6.6 Router acceptance gates

- catastrophic trust violation: 0 on critical holdout
- no worse than static safety baseline on required-trust coverage
- lower `$ / Trusted Page`
- lower/equal severe regression rate
- hard-slice incremental recovery gain positive
- no customer data online exploration
- model/provider failure classified separately from document failure
- route receipt reproducible from frozen inputs/policy/model snapshot

---

# 7. Workstream B — Risk-Controlled Evidence Acquisition

## 7.1 4-way terminal/action model

```text
ANSWER / ACCEPT
ACQUIRE MORE EVIDENCE
ESCALATE / RECOVER
ABSTAIN / REVIEW
```

단순 confidence threshold 한 개로 결정하지 않는다.

## 7.2 Evidence acquisition operators

문서 failure class별:

- higher-DPI rerender
- deskew/rotate/contrast normalization
- crop specific table/cell/figure region
- page-neighbor inclusion
- native PDF/OOXML representation 추가
- visual retrieval로 relevant page 재탐색
- independent parser output 요청
- exact source region 확대

## 7.3 BCEA에서 가져올 핵심 교훈

추가 evidence를 중간에 획득하면 기존 calibration 분포가 변한다. 따라서:

```text
base score로 calibration
→ test에서 acquire 후 더 좋은 score로 교체
```

같은 순진한 방식은 금지한다.

Acquisition policy 전체를 포함한 결과로 다시 calibration하거나, guarantee claim을 하지 않는다.

## 7.4 Conformal research boundary

Conformal guarantee를 외부 claim으로 쓰려면:

- calibration/test exchangeability 또는 명시적 shift assumption
- fixed policy/version
- target risk definition
- finite-sample protocol
- post-acquisition recalibration
- slice/tenant drift monitoring

이 필요하다. 초기 제품에서는 `calibrated=false`와 empirical selective-risk curves만 제공한다.

## 7.5 Metrics

- risk among accepted/trusted outputs
- coverage
- acquisition rate
- average additional cost
- recovery yield
- calibration error
- drift by document slice
- false abstention
- dangerous acceptance

---

# 8. Workstream C — Multi-Representation Retrieval

## 8.1 왜 하나의 index로는 부족한가

```text
Exact numeric/table claim
→ compiled structured units가 강함

Visual diagram/chart/layout
→ visual page retrieval이 강함

Exact identifier/contract code
→ lexical search가 강함

Current/superseded question
→ version graph가 강함

Relationship/impact question
→ entity/dependency graph가 강함
```

따라서 TAVONEL은 retrieval backend 하나를 제품 정체성으로 삼지 않는다.

## 8.2 Retrieval lanes

### Lane A — Permission/Temporal/Authority Filter

모든 candidate generation보다 먼저 또는 candidate access 시 반드시 적용한다.

### Lane B — Lexical

- exact ID
- product code
- legal clause number
- quoted phrase

### Lane C — Compiled Semantic

- claim/unit/chunk/table row
- dense embedding
- entity/relationship expansion

### Lane D — Version Graph

- latest/current
- as-of/known-at
- change history
- explicit revision

### Lane E — Visual Page

ColQwen/ColPali-style page image late interaction.

## 8.3 ColPali adoption constraints

- `colpali-engine` code license exact release pin
- checkpoint license separate
- Gemma-based models require Gemma terms
- Apache-2.0 ColQwen checkpoint 우선 검토
- image embedding index size/latency 측정
- query-token→page-patch similarity map은 interpretability 보조일 뿐 exact source proof가 아님
- hit는 반드시 source page artifact와 연결

## 8.4 Adaptive-k baseline

```python
# conceptual pseudocode
scores = retrieve_candidates(query, max_k=K_MAX)
threshold = estimate_cutoff_from_score_distribution(scores)
k = clamp(number_above(threshold), K_MIN, K_MAX)
return scores[:k]
```

실제 구현은 BSD-3-Clause upstream adapter 또는 독립 wrapper로 pin한다.

## 8.5 Query-aware granularity

```yaml
retrieval_intent:
  type: EXACT_EVIDENCE | FACT | TABLE | PROCEDURE | ENTITY | RELATION | CHANGE | HISTORICAL | IMPACT
  preferred_units:
    - TABLE_CELL
    - CLAIM
  version_mode: CURRENT
  visual_lane: OPTIONAL
  max_context_budget: 12000
```

## 8.6 Retrieval fusion

초기에는 학습된 complex fusion보다 명시적 baseline부터:

```text
permission/time/authority filter
→ lexical + dense + visual candidates
→ reciprocal rank / normalized score fusion
→ source diversity / version correctness
→ reranker
→ adaptive context package
```

## 8.7 Retrieval A/B

- fixed-k vs Adaptive-k
- text-only vs visual-only vs fused
- flat chunks vs structure-aware units
- no-version vs version-aware
- no-authority vs authority-aware
- same downstream LLM/settings

Metrics:

- retrieval recall@budget
- critical evidence recall
- version-correct recall
- unauthorized candidate rate = 0
- context tokens
- latency/cost
- downstream QA/citation


---

# 9. Workstream D — Alignment-First Semantic Diff

## 9.1 현재 위험

문서 두 버전을 곧바로 text diff 또는 semantic embedding으로 비교하면 다음을 혼동할 수 있다.

- 동일 문장이 다른 페이지로 이동
- 표 행/열 재배치
- caption/figure 번호 변경
- 문단 split/merge
- layout/export renderer 차이
- 실제 의미 변경

따라서 “무엇이 같은 element인가?”와 “그 element 안에서 무엇이 바뀌었는가?”를 분리한다.

## 9.2 Element model

```yaml
document_element:
  element_id: el_...
  version_id: sv_...
  type: TEXT | HEADING | TABLE | TABLE_ROW | TABLE_CELL | FORMULA | FIGURE | CAPTION | FOOTNOTE
  page_index: 16
  bbox: [x0, y0, x1, y1]
  structural_path: [section_3, subsection_2, table_4]
  content_hash: ...
  normalized_representation_ref: ...
  visual_feature_ref: ...
  semantic_embedding_ref: ...
  evidence_ref: ...
```

## 9.3 Compatibility signals

- **Spatial:** normalized page/region position, neighborhood
- **Structural:** hierarchy path, table header, figure-caption relation
- **Content:** lexical/semantic similarity, numeric set, formula tree
- **Type:** element type compatibility
- **Context:** preceding/following aligned elements
- **Identity:** existing stable ID evidence

Missing signal을 0으로 처리하지 않고 availability-aware renormalization 또는 abstain을 사용한다. 이는 기존 TAVONEL identity 원칙과 일치한다.

## 9.4 Matching algorithm

1. exact evidence/content hash candidates
2. same structural neighborhood candidates
3. type-compatible approximate candidates
4. compatibility matrix
5. constrained one-to-one assignment
6. unmatched ADD/DELETE
7. low-margin/ambiguous → review/branch/split

```python
# conceptual pseudocode
for type_group in element_types:
    candidates = build_candidates(old[type_group], new[type_group])
    matrix = compatibility_scores(candidates)
    matching = constrained_bipartite_assignment(matrix)
    for pair in matching:
        if pair.margin < AMBIGUITY_MARGIN:
            emit_review(pair)
        else:
            emit_alignment(pair)
```

Threshold는 현재 uncalibrated이며 Knowledge Evolution Suite에서 결정한다.

## 9.5 Type-specific difference reasoning

### Text/Heading

- token/semantic edit
- modality/negation/obligation (`may`→`must`)
- named entity/numeric/date/unit
- scope/exception

### Table

- header alignment
- row/column identity
- merged-cell changes
- cell value/unit/sign
- row move vs value change

### Formula

- parsed expression/tree equivalence
- symbol/value changes
- rendering-only change

### Figure/Chart

- image hash/visual similarity
- caption/legend/axis label changes
- chart data if native source available
- visual-only uncertainty flag

## 9.6 Integration point

```text
Source versions
→ Reference Render + Native Structure
→ Element Extraction
→ Alignment Receipt
→ Stable Claim Identity
→ Semantic Change Object
→ Dependency/Impact
```

기존 `akc_cir.identity`는 최종 stable unit assignment를 계속 소유한다. alignment layer는 candidate evidence를 제공한다.

## 9.7 Benchmark — Knowledge Evolution Suite

Mutation classes:

- pure layout move
- section reordering
- table row move
- table cell numeric change
- typo-only
- date/effective period
- may→must
- exception add/remove
- clause split/merge
- figure replacement
- OCR degradation only

Metrics:

- alignment precision/recall/F1
- semantic change precision/recall
- layout-only false positive
- critical numeric change recall
- identity false merge/false split
- downstream impact recall
- selective/full equivalence

## 9.8 Acceptance

- critical semantic mutation recall = 100% on controlled high-risk set
- pure layout change false semantic invalidation below agreed threshold
- no critical false merge
- ambiguous pairs remain reviewable, not silently merged
- reason/evidence path retained

---

# 10. Workstream E — Version-Aware Knowledge Retrieval

## 10.1 Version graph

```yaml
source_revision_edge:
  from_version_id: sv_old
  to_version_id: sv_new
  relation: SUPERSEDES | AMENDS | CORRECTS | BRANCHES_FROM | DUPLICATE_OF | EXPORT_OF
  declared_by_source: true|false
  inferred: true|false
  evidence_refs: []
  confidence: null
```

File timestamps alone are not authority.

## 10.2 Query intent classes

```text
CURRENT_FACT
AS_OF
KNOWN_AT
CHANGE_BETWEEN
WHY_CHANGED
EXPLICIT_VERSION
VERSION_CONFLICT
APPLICABILITY
```

Examples:

- “현재 보증기간은?” → CURRENT_FACT
- “2025년 3월 당시에는?” → AS_OF
- “작년 문서와 뭐가 달라?” → CHANGE_BETWEEN
- “왜 3년이라고 답했어?” → WHY_CHANGED + provenance

## 10.3 Retrieval plan

```text
Query
→ Intent classifier/rules
→ Time/authority/applicability constraints
→ Version graph traversal
→ Candidate knowledge units
→ Exact evidence package
→ LLM
```

Intent classifier는 제품 truth가 아니다. explicit date/version regex와 structured filters를 먼저 사용하고, LLM intent는 보조한다.

## 10.4 VersionRAG clean-room boundary

VersionRAG의 결과와 task framing은 benchmark inspiration으로 사용하지만, 라이선스 확인 전 repository code를 복사하지 않는다. TAVONEL implementation은 Canonical IR, authority/applicability, bitemporal fields와 기존 graph를 기반으로 독립 구현한다.

## 10.5 Version QA suite

- explicit current/latest
- explicit historical
- amendment/errata
- undeclared change
- conflicting active documents
- scoped customer exception
- valid time vs known time
- no applicable answer

Result states:

```text
ANSWERED
CONFLICTED
NO_APPLICABLE_CLAIM
UNKNOWN_AUTHORITY
INSUFFICIENT_EVIDENCE
```

---

# 11. Workstream F — Provenance Interoperability and Tamper Evidence

## 11.1 Internal truth first

TAVONEL Canonical IR과 receipt는 내부 source of truth다. W3C/OpenLineage/SLSA는 외부 호환 layer다.

```text
Internal Evidence/Attempt/Compile Objects
        ↓ adapters
PROV-O / OpenLineage / in-toto-style Attestation / JSON-LD
```

## 11.2 PROV-O mapping

| TAVONEL | PROV-O |
|---|---|
| Source version / render / raw output / compiled unit | `prov:Entity` |
| Parse / inspect / recover / reconcile / compile / publish | `prov:Activity` |
| Worker / model provider / user / agent | `prov:Agent` |
| generated output | `prov:wasGeneratedBy` |
| source dependency | `prov:wasDerivedFrom` |
| revised knowledge | `prov:wasRevisionOf` |
| exact original source | `prov:hadPrimarySource` |
| actor attribution | `prov:wasAssociatedWith` |

TAVONEL-specific fields are namespaced extensions.

## 11.3 OpenLineage custom facets

Core entities:

- Job: compilation recipe/logical operation
- Run: specific attempt or world-state build
- Dataset: source artifact / compiled export / index snapshot

Custom facets:

```json
{
  "tavonelTrustFacet": {
    "_producer": "tavonel://compiler",
    "_schemaURL": "tavonel://schemas/openlineage/trust-facet/v1",
    "trustState": "TRUSTED",
    "failureCodes": [],
    "evidenceCoverage": 1.0,
    "worldStateId": "ws_..."
  }
}
```

OpenLineage로 내부 authorization/world-state semantics를 대체하지 않는다.

## 11.4 SHACL validation profiles

Profiles:

- `TAVONEL-MinimalEvidenceShape`
- `TAVONEL-CurrentClaimShape`
- `TAVONEL-TemporalClaimShape`
- `TAVONEL-ExportableEntityShape`
- `TAVONEL-AgentConsumptionShape`

Example conceptual Turtle:

```turtle
:tavonelClaimShape a sh:NodeShape ;
  sh:targetClass :KnowledgeClaim ;
  sh:property [
    sh:path :hasEvidence ;
    sh:minCount 1 ;
    sh:severity sh:Violation
  ] ;
  sh:property [
    sh:path :worldStateId ;
    sh:minCount 1 ;
    sh:maxCount 1
  ] .
```

SHACL은 export validation이고 production IR validation은 typed schema + deterministic invariants를 유지한다.

## 11.5 Attestation envelope

```yaml
attestation:
  subject:
    artifact_sha256: ...
  predicate_type: tavonel://attestation/compile/v1
  predicate:
    source_manifest_sha256: ...
    action_key: ...
    compiler_revision: ...
    parser_model_revisions: [...]
    policy_version: ...
    prompt_schema_hashes: [...]
    produced_at: ...
    worker_identity: ...
    validation_receipt_sha256: ...
  signature:
    key_id: ...
    algorithm: Ed25519 | managed-KMS
```

## 11.6 Tamper-evident ledger staged design

### Stage 1 — Hash Chain

```text
receipt_n.hash = H(receipt_n.body || receipt_{n-1}.hash)
```

적용 대상:

- world-state publish
- public benchmark receipt
- customer export manifest
- high-risk agent consumption/action

### Stage 2 — Merkle Batch

시간/tenant 단위 batch root 생성, root를 KMS key로 서명.

### Stage 3 — External transparency/verification option

고객 요구 시 external log/attestation storage를 검토한다. 고객 데이터/secret은 root/summary만 외부화한다.

## 11.7 Key management

- per-environment signing keys
- KMS/HSM preferred for production
- tenant-specific signing optional
- rotation and verification chain
- no private key in worker container
- signer service accepts only hash/metadata allowlist

## 11.8 Metrics

- receipt verification success
- missing lineage edges
- derivation-depth reconstruction
- tamper detection
- signing overhead
- storage growth
- public-safe VSA/summary generation

---

# 12. Workstream G — Bidirectional Impact and Content-Addressed Recompilation

## 12.1 Design principle

Palantir-style generic “dataset dependency build”를 구현 아이덴티티로 삼지 않는다. TAVONEL graph는 다음을 구분한다.

```text
Source Evidence
Semantic Claim
Entity / Relation
Authority / Applicability / Time
Knowledge Unit
Retrieval Artifact
Answer / Agent Consumption
```

## 12.2 Typed dependency edges

```text
DERIVED_FROM_EVIDENCE
DEPENDS_ON_CONTENT
DEPENDS_ON_STRUCTURE
USES_ENTITY
USES_AUTHORITY_RULE
USES_TEMPORAL_FACT
USES_PERMISSION
INDEXED_IN
RETRIEVED_IN
CITED_BY
CONSUMED_BY_AGENT
DISPLAYED_IN_EXPORT
```

## 12.3 Bidirectional operations

### Forward Impact

> 이 source change가 어디까지 영향을 주는가?

### Backward Explanation

> 이 answer/agent context는 어떤 source/evidence/rule 때문에 stale한가?

```yaml
impact_reason_path:
  change_id: ch_...
  target_id: agent_context_...
  path:
    - evidence_cell_B4_v2
    - claim_warranty_period
    - unit_policy_current
    - retrieval_package_44
    - agent_context_9
  reason_codes:
    - NUMERIC_VALUE_CHANGED
    - ACTIVE_AUTHORITY_UPDATED
```

## 12.4 CompilationActionKey

```text
ActionKey = SHA256(canonical_json({
  input_evidence_hashes,
  input_unit_versions,
  compiler_revision,
  parser/model revisions,
  prompt/schema hashes,
  authority/applicability policy version,
  chunk/retrieval policy version,
  deterministic parameters,
  target export profile
}))
```

Secrets, timestamps unrelated to output, worker hostname는 key에 넣지 않는다.

## 12.5 CAS layout on R2

```text
cas/sha256/ab/cd/<fullhash>/artifact
cas/sha256/ab/cd/<fullhash>/metadata.json
ac/<action-key>/result.json
```

- immutable write
- hash verify
- tenant access metadata separate
- encryption/retention policy
- no cross-tenant artifact reuse unless content confidentiality policy explicitly permits

## 12.6 Cache safety

Cache hit도 validation을 생략하지 않는다.

- artifact hash verified
- producer/version policy allowed
- source permission still valid
- tenant/data policy compatible
- output schema compatible
- not revoked/quarantined

## 12.7 Recompile flow

```text
Change set
→ exact dirty set
→ ActionKey calculation
→ cache hits reused
→ misses executed
→ validation
→ candidate world state
→ full/selective equivalence checks
→ atomic publish
```

## 12.8 Differential Dataflow trigger

다음이 실제로 측정될 때만 연구한다.

- graph edges > agreed threshold
- impact traversal p95 SLO miss
- frequent micro-updates
- PostgreSQL recursive traversal/cached closure cost가 병목
- selective recompute scheduling이 dominant CPU/cost

그 전에는 PostgreSQL + typed adjacency + cached reachability로 유지한다.

## 12.9 Design-around documentation

각 ADR에 다음을 기록한다.

- 일반 data pipeline build catalog와 다른 기술적 대상
- source evidence/semantic claim/authority/time/agent consumption 요소
- generic stale dataset rebuild를 독립 발명으로 주장하지 않음
- actual claim chart reference

---

# 13. Workstream H — State-to-Draft Freshness Auditor

## 13.1 문제

최신 state를 retrieval했어도 LLM의 draft가 과거 전제를 암묵적으로 사용할 수 있다.

Example:

```text
Stored state:
old preference = economy shipping
new preference = fastest shipping

Draft:
“비용을 아끼기 위해 일반 배송을 선택했습니다.”
```

Draft가 old preference를 직접 인용하지 않아 일반 fact checker가 놓칠 수 있다.

## 13.2 TAVONEL adaptation

```text
Current relevant world-state transitions
→ LLM draft
→ candidate stale dependency extraction
→ deterministic evidence pinning
→ chronology/authority/applicability validation
→ repair instruction
→ regenerated answer
→ final evidence audit
```

## 13.3 Transition object

```yaml
state_transition:
  logical_claim_id: claim_warranty
  old_unit_version_id: kuv_1
  new_unit_version_id: kuv_2
  old_value: 2 years
  new_value: 3 years
  transition_type: SUPERSESSION
  valid_from: 2026-08-01
  known_at: ...
  evidence_old: ...
  evidence_new: ...
  verified_chronology: true
  semantic_supersession_status: RESOLVED
```

StateAuditor 원 논문은 provenance/chronology 검증과 semantic supersession을 구분한다. TAVONEL은 authority/applicability engine의 resolved status가 있을 때만 “old is superseded”로 사용한다.

## 13.4 Audit result

```yaml
freshness_audit:
  status: PASS | REPAIR_REQUIRED | ABSTAIN
  stale_dependencies:
    - transition_id: ...
      draft_span: ...
      reason: OLD_POLICY_ASSUMPTION
  unsupported_claims: []
  repair_context_ref: ...
```

## 13.5 Safety

- auditor LLM 자체가 truth oracle 아님
- quotations/evidence IDs deterministic verification
- invalid transition proposals discarded
- high-risk repair 후 재-audit
- repeated failure → abstain/review

## 13.6 Benchmark

`TAVONEL FreshnessBench`:

- updated policy but draft uses old implication
- changed user/customer preference
- amended contract exception
- current fact retrieval correct but reasoning stale
- false invalidation controls
- no-change controls

Metrics:

- implicit stale dependency recall
- false repair rate
- final answer accuracy
- cost/latency
- repair success
- abstention rate

---

# 14. Workstream I — Authorization and Governance Absorption

## 14.1 Current decision

PostgreSQL RLS remains the data-plane enforcement boundary. Current worker authorization work is not replaced by Cedar/OpenFGA/OPA.

```text
Control Plane
→ atomic job claim / lease
→ tenant/project/job context
→ Worker Service Plane RLS
→ scoped data access
```

## 14.2 External research lesson: all access paths

Governed Shared Memory found a system where search respected scope but direct GET-by-ID bypassed subtenant scope. TAVONEL therefore defines a conformance matrix.

| Path | Tenant | Project | Principal | World state | Evidence permission | Expected |
|---|---|---|---|---|---|---|
| search | A | P1 | user1 | current | allowed | pass |
| GET unit by UUID | A | P1 | user1 | current | allowed | same result |
| guessed UUID tenant B | A | P1 | user1 | current | forbidden | deny/zero |
| graph traversal | A | P1 | user1 | current | allowed subset | pass |
| source preview | A | P1 | user1 | current | source ACL | pass/deny |
| export | A | P1 | user1 | snapshot | export policy | pass/deny |
| MCP `knowledge.get` | A | P1 | user1 | current | same policy | identical |

## 14.3 Cedar evaluation position

Cedar strengths:

- purpose-built authorization
- RBAC/ABAC
- schema validation
- default deny
- analyzability/formal verification emphasis
- Apache-2.0

Recommended future use:

- Agent action authorization
- policy authoring validation
- high-level workspace/resource/action decisions
- “who may invoke what tool on which entity under what context”

Not recommended now:

- replacing PostgreSQL row filtering
- dual-writing every RLS policy immediately
- introducing a second source of truth before parity testing

## 14.4 OpenFGA evaluation position

Use only if relationship permissions become cross-system and graph-like:

```text
user → member_of → team
team → owns → project
project → contains → knowledge
agent → delegated_by → user
```

Current relational schema/RLS can handle core tenant/project scope. OpenFGA becomes valuable when many applications need a shared authorization graph.

## 14.5 OPA position

OPA is powerful and broad, but initial TAVONEL application authorization benefits from Cedar’s narrower, typed/schema-validated model. OPA remains an infrastructure/compliance candidate, not a default app permission dependency.

## 14.6 Policy-engine adoption gate

- measured policy complexity
- more than one consuming application
- duplicated/contradictory app policies
- need for offline validation/explanation
- performance benchmark
- RLS/policy parity tests
- operational burden acceptable

---

# 15. Technology Intake and Clean-Room Process

## 15.1 Required intake record

```yaml
technology_intake:
  id: tech_...
  name: ...
  source_type: STANDARD | PAPER | OSS | PATENT | API
  source_urls: []
  snapshot_date: 2026-08-11
  exact_commit_or_version: ...
  code_license: ...
  model_license: ...
  dataset_license: ...
  patent_family_refs: []
  intended_use: BASELINE | DEPENDENCY | CLEAN_ROOM | DESIGN_AROUND | REJECT
  data_policy_review: ...
  security_review: ...
  owner: ...
  status: DISCOVERED | REVIEWED | APPROVED | BLOCKED | RETIRED
```

## 15.2 Direct OSS dependency workflow

1. exact repository/commit/tag
2. LICENSE/NOTICE scan
3. transitive dependency license scan
4. model/dataset terms separate
5. SBOM entry
6. vulnerability scan
7. sandboxed evaluation
8. same-condition benchmark
9. ADR approval
10. pin with upgrade policy

## 15.3 Clean-room workflow

적용 대상: paper-only 또는 no-license repo.

1. researcher writes requirement-level summary, no source snippets
2. independent implementer receives only paper/spec and internal contract
3. no code copy/translation
4. independent tests and expected behavior
5. provenance record of sources read by each agent
6. similarity/source audit if necessary

## 15.4 Patent design-around workflow

1. independent claims extracted
2. claim element matrix
3. TAVONEL actual implementation mapping
4. omitted/substantially different elements documented
5. alternative architecture selected for technical reasons
6. counsel review before commercial activation
7. marketing language aligned with design-around

## 15.5 No-license rule

Publicly readable code is not automatically reusable. No LICENSE → code copy/fork/dependency 금지. Paper methods can be independently reimplemented subject to patent review.

---

# 16. Experiment Program — Technology Absorption OS

## 16.1 General experiment contract

Every absorption proposal must have:

```yaml
experiment:
  hypothesis: ...
  baseline: ...
  challenger: ...
  corpus_manifest_sha256: ...
  split: ...
  frozen_settings: ...
  primary_metrics: []
  safety_metrics: []
  cost_metrics: []
  promotion_gate: ...
  rollback: ...
```

## 16.2 Router Experiment R1

### Hypothesis

Marginal-gain routing beats absolute difficulty/quality routing on `$ / Trusted Page` without increasing critical failures.

### Baselines

- static class router
- AdaParse-style predicted parser preference
- RouteLLM MF/BERT
- absolute trust probability

### Challenger

- marginal gain + guard + family-correlation penalty

### Corpus

- Model Arena v1 1,000 pages
- family-level holdout
- Failure Zoo weighted report

### Metrics

- oracle regret
- cost/trusted page
- severe regression
- hard-slice recovery
- unnecessary frontier escalation

## 16.3 Evidence Acquisition Experiment R2

Compare:

- abstain only
- rerender only
- crop/zoom
- native+visual dual input
- alternate model
- calibrated acquire/escalate/abstain policy

No conformal guarantee claim until calibration assumptions and post-acquisition protocol are met.

## 16.4 Diff Experiment D1

```text
Existing TAVONEL identity/diff
vs
Alignment-first challenger
```

Corpus:

- controlled mutation suite
- DART/SEC amendments
- exported Office→PDF pairs
- real revision families

Metrics:

- critical semantic recall
- layout-only false positive
- identity merge/split
- downstream impact quality

## 16.5 Retrieval Experiment Q1

Factorial but stage-gated:

```text
fixed-k vs adaptive-k
flat chunk vs structure-aware
text vs visual vs fused
no-version vs version-aware
```

Start pairwise, not full combinatorial explosion.

## 16.6 Freshness Experiment F1

```text
retrieval-only answer
vs
answer + state-to-draft auditor
```

Metrics:

- implicit stale dependency recall
- false correction
- answer accuracy
- cost
- latency

## 16.7 Provenance Experiment P1

- internal receipt only
- hash chain
- Merkle batch + signature

Measure:

- verification throughput
- storage overhead
- failure recovery
- audit usability
- external export compatibility

## 16.8 Authorization Experiment A1

Access-path matrix across:

- REST search/get/history/evidence/export
- MCP tools/resources
- background worker
- direct SQL fixtures

Critical requirement: same principal/context yields equivalent allow/deny across paths.

## 16.9 Incremental Build Experiment I1

- no cache/full rebuild
- ActionKey/CAS full pipeline
- selective rebuild + CAS

Measure:

- work avoided
- exact output equivalence
- cache hit rate
- invalid hit rate = 0
- time/cost

---

# 17. Promotion Decision Framework

## 17.1 Promote

Technology becomes production candidate only if:

- primary metric improves materially
- no critical safety regression
- cost/latency acceptable
- exact license/model/data terms approved
- FTO status acceptable
- rollback and observability exist
- current protected core no-regression passes

## 17.2 Keep as specialized lane

Overall average가 낮아도 특정 slice에서 unique incremental recovery가 있으면 specialist lane으로 유지한다.

Example:

```text
Model X overall dominated
but degraded scan recovery +18%
→ R7_DEGRADED_SCAN specialist, not global champion
```

## 17.3 Reject

- no unique quality/recovery niche
- Pareto dominated
- license/FTO unacceptable
- operational complexity exceeds benefit
- source/evidence contract broken
- non-determinism unacceptable for compile path

## 17.4 Hold

Potential benefit exists but current corpus/scale does not justify complexity.

---

# 18. Prioritized Implementation Roadmap

## P0 — Architecture Hygiene and Cheap Wins

1. Technology intake registry
2. License/SBOM gate
3. CompilationActionKey schema
4. R2 CAS/action-cache prototype
5. PROV-O export mapping
6. SHACL export validator
7. Access-path conformance matrix
8. RouteLLM/AdaParse baseline adapters in Arena only
9. Adaptive-k retrieval baseline

## P1 — High-Value Challengers

1. Marginal-gain router
2. Alignment-first heterogeneous diff
3. ColQwen visual retrieval lane + ViDoRe/TAVONEL benchmark
4. table-aware chunking
5. version-intent retrieval
6. state-to-draft freshness auditor prototype
7. bidirectional impact explanation paths

## P2 — Trust and Interoperability

1. OpenLineage custom facets
2. hash-chained publication/compile receipts
3. Merkle-batched signed audit receipts
4. in-toto/SLSA-inspired release attestations
5. FreshnessBench/GovernanceBench
6. clean-room RepoDoc baseline comparison

## P3 — Scale/Demand Triggered

1. Cedar application/action policy pilot
2. OpenFGA cross-app permission graph if needed
3. differential dataflow impact prototype
4. full visual parsing-free route
5. cryptographic per-consumption lineage

---

# 19. Repository Change Plan

## 19.1 Suggested packages/services

```text
/packages
  /technology-registry
  /provenance-standards
  /policy-conformance
  /arena-baselines

/services
  /action-cache
  /visual-retrieval
  /freshness-auditor
  /attestation

/benchmarks
  /absorption
    /router
    /diff
    /retrieval
    /freshness
    /governance
    /cache

/docs
  /research/absorption
  /legal/technology-intake
  /adr
```

Existing repo structure가 다르면 logical boundaries를 우선하고 대규모 파일 이동은 피한다.

## 19.2 Feature flags

```yaml
ABSORB_ACTION_CACHE: false
ABSORB_PROV_O_EXPORT: false
ABSORB_SHACL_VALIDATION: false
ABSORB_ROUTER_MARGINAL_GAIN_SHADOW: false
ABSORB_ROUTELLM_BASELINE_ONLY: true
ABSORB_DIFF_ALIGNMENT_SHADOW: false
ABSORB_VISUAL_RETRIEVAL_SHADOW: false
ABSORB_ADAPTIVE_K: false
ABSORB_VERSION_INTENT: false
ABSORB_FRESHNESS_AUDITOR_SHADOW: false
ABSORB_HASH_CHAIN_RECEIPTS: false
ABSORB_CEDAR_PILOT: false
ABSORB_OPENFGA_PILOT: false
```

## 19.3 Database additions

### Technology Registry

```sql
create table technology_components (
  component_id uuid primary key,
  name text not null,
  source_type text not null,
  exact_version text,
  source_url text not null,
  code_license text,
  model_license text,
  dataset_license text,
  patent_risk text not null,
  approval_state text not null,
  intake_receipt_key text not null,
  created_at timestamptz not null default now()
);
```

### Action Cache

```sql
create table compilation_action_results (
  tenant_id uuid not null,
  action_key text not null,
  result_artifact_sha256 text not null,
  result_object_key text not null,
  trust_state text not null,
  producer_receipt_key text not null,
  created_at timestamptz not null,
  invalidated_at timestamptz,
  primary key (tenant_id, action_key)
);
```

Cross-tenant cache reuse는 별도 policy/consent 없이 금지한다.

### Alignment receipts

```sql
create table element_alignments (
  alignment_id uuid primary key,
  tenant_id uuid not null,
  old_element_id uuid not null,
  new_element_id uuid not null,
  element_type text not null,
  signal_values jsonb not null,
  assignment_margin double precision,
  status text not null,
  receipt_object_key text not null
);
```

### Freshness audits

```sql
create table freshness_audits (
  audit_id uuid primary key,
  tenant_id uuid not null,
  consumption_id uuid not null,
  world_state_id uuid not null,
  status text not null,
  stale_dependency_refs jsonb not null,
  model_id text,
  receipt_key text not null,
  created_at timestamptz not null default now()
);
```

## 19.4 Event additions

```text
technology.intake.approved
cache.action.hit
cache.action.miss
diff.alignment.completed
retrieval.visual.completed
answer.freshness.failed
attestation.published
policy.path_conformance.failed
```

---

# 20. Test Catalog

```text
test_unlicensed_repository_cannot_be_approved_dependency
test_model_license_is_separate_from_code_license
test_active_patent_component_requires_design_around_status
test_action_key_changes_when_model_revision_changes
test_action_key_ignores_worker_hostname_and_wall_clock
test_cache_hit_revalidates_permission_and_trust
test_cross_tenant_cache_reuse_default_denied
test_route_baseline_cannot_activate_outside_arena
test_marginal_gain_router_holdout_is_family_disjoint
test_evidence_acquisition_requires_post_policy_recalibration_flag
test_alignment_preserves_layout_move_as_same_element
test_alignment_flags_numeric_cell_change
test_alignment_ambiguous_pair_abstains
test_visual_retrieval_hit_maps_to_source_page
test_visual_similarity_map_is_not_exact_provenance
test_adaptive_k_respects_context_budget
test_version_current_query_excludes_superseded_claim
test_version_conflict_remains_conflicted
test_prov_export_roundtrip_retains_primary_source
test_shacl_rejects_claim_without_evidence
test_hash_chain_detects_modified_receipt
test_merkle_root_verifies_batch
test_freshness_auditor_pins_quote_to_exact_evidence
test_freshness_auditor_rejects_unverified_transition
test_search_and_get_by_id_have_identical_scope
test_mcp_and_rest_authorization_parity
test_impact_backward_path_reaches_exact_source_evidence
test_selective_recompile_with_cache_equals_full_compile
```

---

# 21. FMEA — Potential Technical and Legal Failures

| ID | Failure | Impact | Detection | Mitigation |
|---|---|---|---|---|
| ABS-001 | OSS license is assumed from public repo | legal exposure | intake CI | no LICENSE → blocked |
| ABS-002 | code license permissive, model weights restricted | commercial block | model registry | separate model license gate |
| ABS-003 | Apache patent grant misunderstood as full FTO | infringement risk | legal audit | claim chart/counsel |
| ABS-004 | paper code copied despite no license | copyright risk | provenance/code review | clean-room split |
| ABS-005 | routing baseline leaks into production | uncalibrated decisions | feature flag audit | arena-only package boundary |
| ABS-006 | marginal gain overfits Arena pages | production regression | family holdout | frozen holdout/new policy version |
| ABS-007 | evidence acquisition breaks calibration | false trust claim | calibration test | recalibrate full policy/no guarantee claim |
| ABS-008 | visual retrieval increases recall but loses exact provenance | unsupported answers | evidence gate | map hit to original page + compiled evidence |
| ABS-009 | visual index cost explodes | poor unit economics | index/GPU telemetry | specialist lane, pooling, TTL |
| ABS-010 | alignment falsely merges distinct clauses | history corruption | adversarial revision suite | asymmetric threshold/review |
| ABS-011 | layout-only edit causes full invalidation | unnecessary recompile | mutation suite | alignment-first typed diff |
| ABS-012 | ActionKey excludes a meaningful policy/model input | stale cache hit | cache equivalence tests | canonical key schema/version |
| ABS-013 | ActionKey includes nondeterministic metadata | zero cache hits | hit-rate audit | key allowlist |
| ABS-014 | cache leaks identical customer artifact across tenants | confidentiality breach | tenant security tests | tenant namespace/default no sharing |
| ABS-015 | PROV-O adapter becomes internal truth | architecture rigidity | schema review | internal IR canonical |
| ABS-016 | SHACL validation differs by engine/SPARQL behavior | inconsistent export | multi-engine fixture | Core-first, pin engine/version |
| ABS-017 | hash chain signer key exposed to worker | forged receipts | secret scan/threat model | isolated signer/KMS |
| ABS-018 | freshness auditor repairs correct answer incorrectly | semantic regression | no-change controls | evidence+chronology gates/re-audit |
| ABS-019 | direct GET path bypasses search permissions | tenant leakage | path conformance suite | centralized policy/RLS |
| ABS-020 | Cedar/OpenFGA duplicates RLS source of truth | inconsistent auth | parity telemetry | one authoritative layer per decision |
| ABS-021 | generic incremental rebuild copies active patented pattern | FTO risk | IP review | evidence/claim/world-state design-around |
| ABS-022 | prior-art method becomes public before filing | patent loss risk | disclosure gate | patent-first publication |
| ABS-023 | benchmark gains are vendor/evaluator-specific | false marketing | same-condition report | slice/evaluator caveats |
| ABS-024 | research prototype adds excessive complexity | solo-founder drag | complexity budget | stage-gated adoption |

---

# 22. Security and Privacy Requirements

## 22.1 Technology evaluation isolation

- only public/synthetic/approved corpus in Model Arena
- customer content not added to public/common router training without explicit future opt-in system
- API provider route allowed only by tenant data policy
- raw page images/outputs retained per test policy
- external research services receive no production secrets

## 22.2 Provenance data minimization

External provenance exports may reveal filenames, user identities, model prompts or tenant structure. Public/export profiles must support:

- pseudonymous IDs
- redacted source paths
- sanitized model/provider metadata
- hash-only references
- VSA-like summary rather than full attestation

## 22.3 Visual retrieval index security

Visual embeddings may leak information and are tenant data.

- tenant namespace/RLS
- encryption at rest
- deletion propagation
- no public/shared index by default
- model/data policy receipt

---

# 23. Patent / Trade Secret / Paper Mapping After Absorption

## 23.1 Patent Family A — keep narrow

### Candidate

**Failure-Class-Aware Trusted Document Intelligence Execution and Recovery**

Absorbed prior art means independent claim must not be generic router/cascade.

Protectable candidate combination:

```text
source-grounded failure finding
→ operational/semantic/evidence/disagreement classification
→ materially different operator by class
→ independent-family escalation when semantic
→ structural/evidence acceptance gate
→ trusted-state promotion or abstention
→ outcome receipt feeding future economic policy
```

### Trade secret

- actual feature vector
- marginal-gain model
- route weights
- correlation group definitions
- model performance map
- recovery thresholds/prompts

## 23.2 Patent Family B — primary strategic family

### Candidate

**Evidence-Linked Semantic Change Propagation and Selective AI Knowledge Recompilation**

Absorbed Palantir/RepoDoc prior art means novelty cannot be dependency rebuild alone.

Candidate combination:

```text
source evidence-region revision
→ typed heterogeneous alignment
→ stable semantic claim continuity/change
→ authority/applicability/valid-time recomputation
→ retrieval/agent consumption stale scope
→ selective knowledge recompilation
→ source/structure validation
→ atomic organizational world-state promotion
```

### Trade secret

- compatibility scoring
- identity thresholds/one-to-one assignment recipe
- authority/applicability rules
- dependency fan-out/cutoff
- impact priority

## 23.3 Paper program

### Paper A — Recovery Runtime

External comparison:

- confidence/QoS cascades
- AdaParse parser routing
- TAVONEL failure-class operators

### Paper B — Model Arena / Marginal Gain

- absolute quality/difficulty vs marginal gain
- local OCR/VLM + frontier API
- `$ / Trusted Page`
- incremental recovery yield
- family correlation

### Paper C — Living Knowledge

- RepoDoc/Palantir/data lineage vs evidence/claim/agent consumption
- alignment-first change
- authority/time
- atomic world state

### Paper D — Same Intelligence, Better World

- Raw PDF
- Basic RAG
- TAVONEL
- same LLM
- plus state-to-draft freshness auditor ablation

## 23.4 Publication firewall

Public before filing:

- product behaviors
- aggregate benchmark
- WHAT/WHY
- standards used

Withhold before filing:

- specific recovery decision mechanics
- alignment/identity formula
- route marginal-gain feature design
- dependency/impact algorithm details
- freshness auditor prompt/rules
- raw outcome map

---

# 24. Definition of Done

Technology Absorption Program v1은 다음이 모두 충족될 때 완료다.

1. 모든 외부 기술이 BLUE/GREEN/YELLOW/ORANGE/RED/GRAY로 분류됐다.
2. 직접 dependency에는 exact version/license/NOTICE/SBOM가 있다.
3. model/data/API terms가 code license와 별도로 기록됐다.
4. no-license code는 production tree에 복사되지 않았다.
5. active patent candidates는 design-around ADR와 claim-chart task를 가진다.
6. RouteLLM/AdaParse는 Arena baseline으로 격리됐다.
7. marginal-gain router가 family holdout에서 평가됐다.
8. acquisition/abstention policy는 calibration 상태를 정직하게 표시한다.
9. alignment-first diff challenger가 Knowledge Evolution Suite에서 평가됐다.
10. Adaptive-k가 fixed-k baseline과 비교됐다.
11. visual retrieval lane이 source page/evidence contract를 유지한다.
12. version-aware retrieval이 current/as-of/change/conflict QA를 통과한다.
13. PROV-O export와 SHACL validation이 round-trip/negative fixtures를 통과한다.
14. ActionKey/CAS가 exact equivalence와 permission safety를 통과한다.
15. state-to-draft freshness auditor가 no-change false repair control을 통과한다.
16. Search/GET/graph/export/API/MCP access parity가 검증됐다.
17. absorbed technology가 protected core를 회귀시키지 않았다.
18. public claims는 measured campaign receipts만 사용한다.
19. 특허 Family A/B의 absorbed prior-art boundary가 invention disclosures에 반영됐다.
20. rollback/feature flags가 production activation 전에 존재한다.

---

# 25. Final Claude Code Implementation Command

```text
You are the lead research-and-implementation orchestrator for the TAVONEL Technology Absorption Program.

SOURCE OF TRUTH
Read TAVONEL_TECHNOLOGY_ABSORPTION_FTO_IMPLEMENTATION_BLUEPRINT_v1.0_FINAL_KO_2026-08-11.md in full.
Also read the current TAVONEL v5 masterplan, the prior-art research file, the current gap matrix, the FOLYNTA evidence receipts, and current repository audit records.

MISSION
Absorb useful prior art without copying unlicensed code, violating model/data terms, weakening protected-core evidence, or reproducing high-risk active patent claim patterns.
Every external method is a versioned challenger, standard adapter, direct dependency, design-around marker, or rejected item—never an untracked idea pasted into production.

FIRST ACTIONS
1. Inspect current repository and map actual modules to this blueprint.
2. Create docs/research/absorption/TECHNOLOGY_INTAKE_REGISTER.md.
3. Create machine-readable technology registry schema.
4. Record exact repository/tag/commit/license/model/data terms for each proposed dependency.
5. Block every no-license or unresolved component from dependency installation.
6. Create ADRs for IBM sequential-inference and Palantir/Oracle lineage design-around boundaries.
7. Run current protected-core and benchmark checks before modifications.
8. Create a clean checkpoint.

IMPLEMENTATION ORDER
P0:
- technology/license/SBOM intake gate
- CompilationActionKey + tenant-scoped R2 CAS prototype
- PROV-O export adapter
- SHACL validation profile
- access-path authorization conformance tests
- Arena-only RouteLLM/AdaParse baseline adapters
- Adaptive-k baseline

P1:
- marginal-gain router in shadow/Arena only
- alignment-first heterogeneous diff challenger
- ColQwen/ColPali visual retrieval challenger with ViDoRe and TAVONEL corpora
- structure/table-aware retrieval units
- version-intent retrieval
- state-to-draft freshness auditor prototype
- bidirectional impact reason paths

P2:
- OpenLineage custom facets
- hash-chain receipts
- Merkle-batch signed publication/compile receipts
- SLSA/in-toto-inspired attestation export
- FreshnessBench/GovernanceBench

DO NOT
- Do not copy code from repositories with no explicit license.
- Do not treat an Apache/MIT/BSD code license as third-party patent clearance.
- Do not activate external router code in production before Arena/holdout gates.
- Do not replace protected Inspector/Recovery/Identity/Diff/Dependency/Recompile/WorldState without same-condition no-regression evidence.
- Do not claim conformal guarantees without satisfying and documenting assumptions, calibration and post-acquisition policy.
- Do not let visual retrieval hits become exact provenance without mapping back to immutable source pages/evidence.
- Do not introduce Cedar, OpenFGA, OPA or Differential Dataflow without the specified demand/scale gate.
- Do not expose routing weights, identity scoring, performance maps, dependency cutoffs or prompts publicly.
- Do not describe generic routing, provenance or selective rebuild as TAVONEL inventions.

CLEAN-ROOM RULE
For YELLOW methods, a research agent writes requirements and tests; an independent implementer receives only the paper/spec/internal contract—not source code. Record which external materials each agent accessed.

EVIDENCE
Each challenger produces:
- exact source/version/license receipt
- corpus and split hash
- frozen config
- quality/safety/cost/latency results
- negative results
- promotion/reject decision
- rollback
- claim status

AUTONOMY
Proceed without repeated product questions when this document decides the issue.
Ask only for unavailable credentials, paid services, legal approval, customer consent, or irreversible production actions.

FINAL REPORT
Report each technology as APPROVED_DEPENDENCY, APPROVED_STANDARD_ADAPTER, CLEAN_ROOM_CHALLENGER, DESIGN_AROUND_ONLY, HOLD, or REJECTED, with receipts and measured rationale.
```

---

# APPENDIX A — Primary Source Ledger

Snapshot: 2026-08-11 KST. Exact current versions/status must be rechecked before dependency pin, filing, or public publication.

## Routing / Risk

- AdaParse paper: https://arxiv.org/abs/2505.01435
- AdaParse repository: https://github.com/7shoe/AdaParse
- RouteLLM repository: https://github.com/lm-sys/RouteLLM
- RouteLMT: https://arxiv.org/abs/2604.22520
- IBM Sequential Model Inference: https://patents.google.com/patent/US11605028B2/en
- SCoRE: https://arxiv.org/abs/2603.24704
- Selective Conformal Risk Control: https://arxiv.org/abs/2512.12844
- Learning Conformal Abstention: https://arxiv.org/abs/2502.06884
- BCEA: https://arxiv.org/abs/2606.16667

## Diff / Version / Impact

- Heterogeneous Cross-Version Differencing: https://arxiv.org/abs/2607.14117
- VersionRAG: https://arxiv.org/abs/2510.08109
- RepoDoc paper: https://arxiv.org/abs/2604.26523
- RepoDoc repository: https://github.com/SYSUSELab/RepoDoc
- Palantir Universal Data Pipeline: https://patents.google.com/patent/US20170097950A1/en
- Palantir propagated deletion family example: https://patents.google.com/patent/US12229121B2/en
- Oracle dynamic lineage example: https://patents.google.com/patent/US20180052878A1/en

## Retrieval

- Adaptive-k paper: https://aclanthology.org/2025.emnlp-main.1017/
- Adaptive-k repository: https://github.com/megagonlabs/adaptive-k-retrieval
- SmartChunk: https://arxiv.org/abs/2602.22225
- ColPali repository: https://github.com/illuin-tech/colpali
- ViDoRe benchmark: https://github.com/illuin-tech/vidore-benchmark
- VisRAG: https://github.com/OpenBMB/VisRAG
- Infinity: https://github.com/michaelfeil/infinity

## Provenance / Integrity

- W3C PROV-O: https://www.w3.org/TR/prov-o/
- W3C SHACL: https://www.w3.org/TR/shacl/
- OpenLineage: https://github.com/OpenLineage/OpenLineage
- SLSA provenance: https://slsa.dev/spec/v1.2/provenance
- SLSA attestation model: https://slsa.dev/spec/v1.2/attestation-model
- in-toto: https://in-toto.io/
- MemLineage: https://arxiv.org/abs/2605.14421

## Freshness / Governance

- StateAuditor: https://arxiv.org/abs/2608.01619
- Governed Shared Memory: https://arxiv.org/abs/2606.24535
- GateMem: https://arxiv.org/abs/2606.18829

## Authorization

- Cedar: https://github.com/cedar-policy/cedar
- Cedar validation docs: https://docs.cedarpolicy.com/policies/validation.html
- OpenFGA: https://github.com/openfga/openfga
- OPA: https://github.com/open-policy-agent/opa

## Incremental Build

- Bazel remote caching: https://bazel.build/remote/caching
- Nix content addressing: https://releases.nixos.org/nix/nix-2.28.2/manual/store/derivation/outputs/content-address.html
- Differential Dataflow: https://github.com/TimelyDataflow/differential-dataflow

---

# APPENDIX B — Direct Use Decision Summary

## Can use now after normal intake

- AdaParse code: MIT, Arena adapter/scheduling patterns
- RouteLLM: Apache-2.0, Arena baseline
- Adaptive-k: BSD-3-Clause, retrieval baseline
- ViDoRe: MIT, benchmark
- VisRAG code: Apache-2.0, but model terms separate
- Infinity: MIT
- OpenLineage: Apache-2.0
- Cedar/OpenFGA/OPA: Apache-2.0, but architecture adoption gated
- W3C PROV-O/SHACL: standards adapters

## Can use only after model/data terms review

- ColPali/ColQwen checkpoints
- VisRAG weights
- any Hugging Face model/dataset
- commercial API model inputs/retention terms

## Clean-room only unless license later confirmed

- RepoDoc code
- VersionRAG code
- Heterogeneous diff code
- SmartChunk code
- MemLineage/StateAuditor code

## Design-around / counsel review

- IBM sequential inference patent
- Palantir pipeline/selective rebuild families
- Oracle dynamic lineage family

---

# APPENDIX C — Non-Claims

이 문서 작성만으로 다음은 사실이 아니다.

- marginal-gain router가 기존 router보다 우수하다
- visual retrieval이 TAVONEL QA를 개선한다
- alignment-first diff가 현재 identity보다 낫다
- freshness auditor가 stale answer를 감소시킨다
- content-addressed cache가 특정 비율의 비용을 절감한다
- conformal risk guarantee가 TAVONEL production distribution에 적용된다
- Family A/B가 특허 가능하거나 FTO 문제가 없다
- listed OSS/model가 현재 commercial use에 모두 허용된다

모든 성능·비용·법적 claim은 별도의 immutable evidence 또는 전문 의견이 필요하다.

---

# END
