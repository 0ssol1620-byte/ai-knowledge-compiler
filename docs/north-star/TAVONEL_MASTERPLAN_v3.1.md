# TAVONEL — ULTIMATE PRODUCTION RESEARCH & IMPLEMENTATION MASTERPLAN v3.1 EXTREME FINAL
## Adaptive Document Execution · Knowledge Integrity · Reality Synchronization · Temporal/Lineage · Knowledge CI/CD · Security · Evidence · Performance · Product · Website · GTM · AI-Native Solo Founder · Claude Code

**문서 상태:** FINAL SOURCE OF TRUTH v3.1 — AUTONOMOUS PHASED IMPLEMENTATION + COMMERCIAL EXECUTION CONTRACT
**작성 기준:** 2026-08-10 KST
**공개 브랜드:** **TAVONEL**
**카테고리:** **The Knowledge Compiler**
**주 구현 에이전트:** **Claude / Claude Code**
**기본 인프라:** Vercel + Cloudflare R2 + Cloudflare Queues + RunPod + Managed PostgreSQL/pgvector
**현재 검증 baseline:** MinerU 3.4.4 + 기존 FOLYNTA/TAVONEL Recovery Runtime
**핵심 원칙:** **Evidence, not adjectives. Every claim has a receipt.**

---

# v3.1 사용 선언

이 파일은 기존 v1.0의 제품·브랜드·웹·GTM 설계, v2.0의 production architecture, v3.0의 normative implementation methodbook을 통합하고, 최종 검수에서 확인된 semantic model·chunking·Office·connector·GPU scheduling·end-to-end evaluation·billing·GTM 실행 공백까지 닫는다.

- 실제 구현 기술 선택과 기본값
- 파일 형식별 preflight와 sandbox
- profiler feature 정의와 계산 방법
- cost-aware router의 실행 가능한 알고리즘
- bootstrap 임계값, calibration, abstention, 승격 규칙
- parser/model/license registry
- page/document 장애 탐지 알고리즘
- consensus·recovery·document reconciliation 방법론
- indirect prompt injection·RAG poisoning·악성 파일 대응
- stable identity·entity·authority·applicability·temporal resolution
- semantic diff·typed impact·selective recompile·atomic world-state publish
- at-least-once queue·outbox/inbox·idempotency·late/out-of-order event 처리
- R2/RunPod commit protocol과 비용·tail latency·DR
- permission-first retrieval·pgvector filtering·MCP 2026-07-28 보안
- model/container/schema upgrade와 공급망 provenance
- 삭제·보존·백업·복구·incident runbook
- benchmark·chaos·FMEA·competitive evaluation
- Health Scan·website·Gracian Code·pilot·수익화
- 1인 Founder가 AI로 구현·검수·배포하는 운영체계

## 중요한 현실성 원칙

이 문서 하나로 전체 구현을 계속 진행할 수는 있다. 그러나 **한 번의 무검증 대형 변경으로 전체를 완성하라는 뜻은 아니다.** 최종 명령은 Claude Code가 phase를 연속 실행하되, 각 phase마다 테스트·benchmark·security gate·evidence receipt·rollback checkpoint를 통과하도록 강제한다.

> **Single source of truth, not a single unsafe commit.**

## 규범 키워드

- **MUST / 반드시:** 미준수 시 구현 실패 또는 launch blocker.
- **MUST NOT / 금지:** 예외를 허용하지 않는다.
- **SHOULD / 원칙적으로:** 예외에는 Architecture Decision Record가 필요하다.
- **MAY / 선택:** 제품 수요나 benchmark로 필요성이 확인된 뒤 도입한다.

## 최종 우선순위

충돌 시 다음 순서로 판단한다.

1. 이 파일의 `PART B2 — v3.1 COMPLETENESS CLOSURE METHODBOOK`
2. 이 파일의 `PART B — v3.0 NORMATIVE IMPLEMENTATION METHODBOOK`
3. 이 파일의 `PART A — INHERITED v2.0 TECHNICAL CANON`
4. 이 파일의 `PART C — PRODUCT / WEBSITE / GTM CANON`
5. repository 안의 hash-verified evidence와 receipt
6. 기존 v1.0 및 과거 legacy 문서
7. 기존 구현

단, 이미 검증된 evidence 수치·artifact hash·역사적 `FOLYNTA` label은 이 문서가 임의로 변경하지 않는다.

## Claude가 사용자에게 다시 물어도 되는 것

다음 네 범주만 사용자 확인을 요구할 수 있다.

1. 실제 cloud/API secret 또는 결제 승인
2. 법률·라이선스·상표에 대한 최종 의사결정
3. 충돌한 기업 정책 중 무엇이 실제 business truth인지
4. 파괴적 production 작업 또는 되돌릴 수 없는 데이터 삭제

그 외 기술 선택은 이 문서의 default와 acceptance gate에 따라 자율 진행한다.

---

# PART A — INHERITED v2.0 TECHNICAL CANON

> 이 Part는 v2.0의 전체 production 설계를 보존한다. 뒤의 PART B2/PART B가 수치·상태·알고리즘·보안·운영 세부사항을 더 구체화하거나 변경할 경우 PART B2/PART B가 우선한다.

# 0. 이 문서의 목적과 우선순위

이 문서는 기존 `TAVONEL_FINAL_NORTH_STAR_MASTERPLAN_CLAUDE_IMPLEMENTATION_KO_2026-08-09.md`의 제품/브랜드/웹/GTM 설계를 폐기하지 않고, 실제 production 구현에 필요한 알고리즘·상태머신·스키마·실패모델·성능·보안·검증·Claude 운영체계를 추가해 **독립적으로 실행 가능한 차기 마스터**로 승격한 문서다.

이 문서 하나를 repository root 또는 `/docs/north-star/`에 넣으면 Claude Code가 다음을 수행할 수 있어야 한다.

1. 현재 구현을 보존하면서 gap을 전수 조사한다.
2. 문서 난이도 분류, parser routing, failure detection, recovery를 재설계한다.
3. page-level parsing에서 document-level reconciliation까지 구현한다.
4. Canonical Knowledge IR, provenance, stable identity, entity/authority/temporal resolution을 구현한다.
5. Semantic Diff → Dependency/Impact → Incremental Recompile → Validation → World State Publish를 닫힌 루프로 구현한다.
6. 속도·정확도·비용·tail latency를 함께 최적화한다.
7. benchmark와 chaos/failure injection으로 각 기능을 자동 검증한다.
8. Knowledge Health Scan, Evidence, Website, Gracian Code funnel까지 제품/마케팅을 기술 evidence와 연결한다.
9. 1인 founder가 직접 코드를 모두 읽지 않아도 되는 AI-native 개발/검수 체계를 만든다.

## 0.1 충돌 시 우선순위

1. 이 문서 v2.0
2. 기존 FINAL NORTH STAR v1.0
3. 실제 repository의 검증된 evidence/receipt
4. 기존 구현
5. 과거 실험/legacy 문서

**단, 기존 benchmark evidence의 역사적 수치와 artifact label은 v2.0이 임의로 변경하지 않는다.**

---

# 1. 절대 변경하지 않는 North Star

## 1.1 제품 한 문장

> **TAVONEL is the Knowledge Compiler for AI.**

## 1.2 외부 제품 정의

> **Compile fragmented organizational knowledge into trusted, temporal, traceable context for AI and agents.**

## 1.3 핵심 문제

> **Your AI is only as reliable as the reality it sees.**

## 1.4 변화에 대한 약속

> **When reality changes, your AI should know exactly what changed.**

## 1.5 내부 기술 정의

> **TAVONEL is an adaptive compilation and synchronization runtime for machine-understandable organizational reality.**

## 1.6 장기적으로 싸우는 적

> **Stale AI Reality**

현실은 바뀌었지만 AI가 사용하는 지식·관계·권한·시간·context가 과거에 머물러 있는 상태.

---

# 2. 현재 Evidence Baseline — 절대 왜곡 금지

기존 내부 캠페인 evidence를 그대로 보존한다.

## 2.1 Public benchmark

- ParseBench: 2,078 documents
- OmniDocBench: 1,651 documents
- olmOCR-Bench: 1,403 documents
- Total: 5,132 documents
- Pipeline baseline: MinerU 3.4.4 VLM engine + FOLYNTA/TAVONEL recovery runtime

## 2.2 Completion / recovery

- 5,131 / 5,132 produced output = **99.98% completion**
- 실제 recovery 필요 문서: 1,797
- recovered: 1,796
- recovery rate when required = **99.94%**

**99.98%를 accuracy라고 부르지 않는다.**

## 2.3 Accuracy/fidelity

- olmOCR-Bench overall: **80.6%**
- 95% CI: 79.62–81.57
- low-quality scans: **36.9%**
- OmniDocBench text character match: **94.2%**
- reading order match: **85.9%**
- table structure accuracy: **95.5%**
- table full accuracy: **92.6%**

## 2.4 Recovery ablation

동일 model/evaluator/corpus/settings에서 recovery content만 제거:

- recovery ON: 80.6
- recovery OFF: 53.7

이 결과는 현재의 가장 중요한 engineering evidence 중 하나다.

> **Reliability is a system property, not a model property.**

## 2.5 Reproducibility

- 384/384 documents byte-identical markdown across 3 repeats
- 384/384 terminal status stable

## 2.6 현재 알려진 약점

- low-quality scan 36.9%
- blind quality detection hypothesis not supported
- source blank vs output empty를 기존 harness가 완전히 구별하지 못했던 문제
- targeted quality retry improvement claim은 검증 완료 전 withheld

이 약점들은 삭제 대상이 아니라 **다음 알고리즘 설계의 입력**이다.

---

# 3. 2026-08 연구 업데이트가 주는 설계 결론

이 섹션은 기존 파일에서 직접 증명된 사실이 아니라 **2026-08-10 기준 외부 공식 문서/1차 연구를 조사한 결과**다.

## 3.1 상용 제품들도 이미 adaptive path를 사용한다

- Unstructured는 `auto / fast / hi_res / ocr_only / vlm` 전략을 분리한다.
- Reducto는 standard parsing 이후 필요할 때 text/table `agentic` enhancement를 켤 수 있다.
- Mistral OCR 4는 block type, bbox, confidence를 직접 노출한다.
- PaddleOCR-VL 1.6은 document parsing 성능과 real-world distortion 대응을 계속 강화했다.
- MinerU 3.4는 OCR pipeline 정확도/효율을 개선하고, 3.3 이후 parsing `effort` 개념을 강화했다.

**결론:** TAVONEL도 하나의 parser에 모든 문서를 보내는 방식이 아니라, document/page 특성과 실제 output quality에 따라 계산량을 달리해야 한다.

## 3.2 routing과 label-free quality estimation 연구가 실용 단계로 들어오고 있다

- Multi-Expert Routing 연구는 페이지별로 expert를 선택하는 구조를 평가한다.
- Consensus Entropy는 여러 VLM 결과 간 agreement를 ground-truth 없는 quality signal로 사용하고 adaptive routing에 활용한다.
- DocOCR-Eval은 label-scarce 환경에서 여러 OCR/MLLM의 결과를 이용해 tool selection을 근사한다.

**결론:** Router의 최종형은 고정 heuristic가 아니라 실제 production outcome으로 갱신되는 cost-aware model arbitration이 되어야 한다.

## 3.3 page accuracy만으로는 충분하지 않다

- MPDocBench-Parse는 cross-page text/table merge, hierarchy recovery, reading order, visual content에서 현 시스템들의 한계를 보여준다.
- Dr. DocBench는 일반 benchmark에서 강한 시스템도 expert-level/long-document 난이도에서 성능이 무너질 수 있음을 보여준다.
- PureDocBench는 benchmark 포화와 annotation/contamination 문제를 경고한다.

**결론:** page-level parser score와 document-level semantic integrity를 별도 KPI로 관리해야 한다.

## 3.4 속도 경쟁도 모델 하나가 아니라 execution architecture 문제다

- HPD-Parsing은 global layout coordination + block-level parallel decoding으로 throughput을 크게 높이는 방향을 보여준다.
- Training-free acceleration 연구는 lightweight draft + stronger VLM verification 패턴을 제안한다.

**결론:** TAVONEL은 `fast path → verify → escalate`를 기본 패턴으로 채택한다.

---

# 4. 최종 Production Architecture v2

```text
MESSY ORGANIZATIONAL REALITY
PDF / PPTX / DOCX / XLSX / Images / Scans / Drive / SaaS / API / DB
                                │
                                ▼
                    SOURCE PREFLIGHT & MANIFEST
                                │
                                ▼
                   DOCUMENT / PAGE PROFILER
                                │
                                ▼
                   COST-AWARE RISK ROUTER
                                │
                       EXECUTION PLAN
                                │
       ┌────────────────────────┼─────────────────────────┐
       ▼                        ▼                         ▼
   FAST PATH               STRUCTURED PATH            VLM PATH
native/rule-based          layout/table/etc.          hard visual
       └────────────────────────┼─────────────────────────┘
                                ▼
                      POST-PARSE INSPECTOR
                     ┌──────────┼───────────┐
                     ▼          ▼           ▼
                   ACCEPT    SUSPICIOUS     FAIL
                                │           │
                                └─────┬─────┘
                                      ▼
                         RECOVERY POLICY ENGINE
                                      │
             preprocess → reroute → ensemble → verify
                                      │
                                      ▼
                         DOCUMENT RECONCILER
              cross-page / hierarchy / table / caption
                                      │
                                      ▼
                         CANONICAL KNOWLEDGE IR v2
                                      │
             ┌────────────────────────┼──────────────────────┐
             ▼                        ▼                      ▼
         Evidence                Stable Identity         Semantics
             │                        │                      │
             ▼                        ▼                      ▼
         Provenance              Entity Resolution      Claims/Relations
             └────────────────────────┼──────────────────────┘
                                      ▼
                       AUTHORITY / APPLICABILITY
                                      │
                                      ▼
                     TEMPORAL + EPISTEMIC STATE
                                      │
                                      ▼
                  DOCUMENT-SEMANTIC LINEAGE
                                      │
                                      ▼
                     KNOWLEDGE DEPENDENCY GRAPH
                                      │
                 Semantic Diff → Typed Impact
                                      │
                                      ▼
                      SELECTIVE RECOMPILATION
                                      │
                                      ▼
                       INTEGRITY VALIDATION
                         ┌──────────┴──────────┐
                         ▼                     ▼
                       PASS                  BLOCK
                         │
                         ▼
                    WORLD STATE COMMIT
                         │
             ┌───────────┼───────────────┐
             ▼           ▼               ▼
          Markdown      RAG          Graph/Ontology
             └───────────┼───────────────┘
                         ▼
                    API / MCP / AGENTS
                         │
                         ▼
                AGENT CONSUMPTION LINEAGE
                         │
                         ▼
                       ACTION
                         │
                         ▼
                    REALITY CHANGES
                         └──────────────────────↺
```

---

# 5. Source Preflight — parser 이전의 안전/정확도 Gate

## 5.1 목적

Parser에게 넘기기 전에 원본이 처리 가능한지, 안전한지, 동일 source의 새 version인지 판정한다.

## 5.2 필수 manifest

```yaml
source_manifest:
  tenant_id: t_...
  workspace_id: w_...
  source_id: src_...
  upload_id: upl_...
  object_key: sources/...
  content_sha256: ...
  media_type_detected: application/pdf
  extension_original: .pdf
  file_size_bytes: 0
  page_count: null
  encrypted: false
  archive_member_count: null
  decompressed_estimate_bytes: null
  native_text_present: unknown
  created_at: ...
```

## 5.3 안전 규칙

- 확장자만 믿지 않는다. magic bytes/MIME sniffing 사용.
- Office macro 실행 금지.
- archive는 path traversal 차단.
- decompression ratio / decompressed size 상한.
- 최대 파일 크기, 최대 페이지, 최대 pixel dimension.
- parser worker는 untrusted-input sandbox/container로 취급.
- executable/active content를 source artifact로 저장하더라도 실행하지 않는다.
- 고객 source와 public evidence bucket 분리.
- presigned URL은 short-lived, tenant-scoped object key만 발급.

## 5.4 상태

```text
RECEIVED
→ HASHED
→ PREFLIGHT_OK
  ├ ENCRYPTED_NEEDS_PASSWORD
  ├ CORRUPT_SOURCE
  ├ UNSUPPORTED_TYPE
  ├ RESOURCE_LIMIT_BLOCKED
  └ SECURITY_BLOCKED
```

---

# 6. Document/Page Profiler — Router의 입력 생성

## 6.1 문서 전체 feature

```yaml
document_profile:
  format: pdf
  pages: 142
  bytes: ...
  native_text_ratio: 0.78
  image_page_ratio: 0.22
  language_candidates: [ko, en]
  mixed_language_score: ...
  repeated_layout_score: ...
  likely_document_types: [manual, policy]
  cross_page_table_prior: ...
  section_numbering_present: true
```

## 6.2 페이지 feature

### visual quality
- width/height
- estimated DPI
- blur score
- skew angle
- contrast
- background entropy
- JPEG/compression artifact score
- illumination nonuniformity
- warp/dewarp signal

### content
- native text chars
- text density
- image area ratio
- table likelihood
- formula likelihood
- chart/figure likelihood
- handwriting likelihood
- seal/signature likelihood
- number of columns
- vertical text likelihood

### structure
- detected block count
- overlap complexity
- heading likelihood
- list density
- footer/header repetition
- continuation signal from previous/next page
- table schema continuity

### anomaly
- Unicode replacement chars
- control chars
- font encoding mismatch
- native-text/render mismatch
- unexpectedly empty page
- duplicated native text

## 6.3 초기 구현 방식

**v2.0 초기에는 router용 별도 neural model을 만들지 않는다.**

1. deterministic features
2. rule-based route class
3. small calibration model(optional)
4. 실제 outcome 저장
5. 충분한 데이터가 쌓인 뒤 learned router로 교체

---

# 7. Route Classes — Easy/Hard가 아니라 실패 원인별 분류

```text
R0_NATIVE_TEXT
텍스트 추출이 안정적인 digital 문서

R1_SIMPLE_VISUAL
단순 스캔 / 단일 column

R2_LAYOUT_COMPLEX
multi-column / overlapping / unusual reading order

R3_TABLE_COMPLEX
merged cells / nested headers / table-heavy

R4_FORMULA_SCIENTIFIC
equation / scientific notation / technical diagrams

R5_DEGRADED_SCAN
blur / skew / low contrast / photograph / compression

R6_MIXED_MULTIMODAL
text + tables + figures + charts

R7_CROSS_PAGE
table/paragraph/section continuation risk high

R8_HANDWRITING
handwritten/mixed annotations

R9_UNKNOWN
profile confidence low / conflicting signals
```

한 문서 안에서도 페이지별 route class가 달라질 수 있다.

---

# 8. Parser/Model Registry

특정 모델명을 비즈니스 로직에 hard-code하지 않는다.

```yaml
parser_profile:
  parser_id: mineru_3_4_4_vlm
  family: mineru
  version: 3.4.4
  deployment: runpod
  image_digest: sha256:...
  capabilities:
    native_text: 0.8
    layout_complex: 0.8
    table_complex: 0.8
    formula: 0.8
    degraded_scan: 0.5
    handwriting: 0.4
    cross_page_native: 0.2
  supports:
    bbox: true
    confidence: false
    tables: true
    formulas: true
    images: true
  expected:
    cost_per_page: learned
    latency_p50_ms: learned
    latency_p95_ms: learned
  status: CHAMPION | CHALLENGER | SHADOW | DISABLED
```

## 8.1 초기 candidate pool

- 현재 검증 baseline: MinerU 3.4.4
- PaddleOCR-VL 1.6 계열: challenger candidate
- 기타 open-source parser: benchmark 통과 시 추가
- Mistral OCR 4 / Reducto / Unstructured: **경쟁 평가 또는 optional paid fallback**으로 별도 adapter 가능
- 자체 foundation OCR 모델 개발 금지

새 모델은 기존 baseline을 대체하지 않고 먼저 `SHADOW`로 평가한다.

---

# 9. Cost-Aware Risk Router — 핵심 알고리즘

## 9.1 목표

가장 강한 모델을 항상 사용하는 것이 아니다.

> **요구 품질을 만족하는 범위에서 예상 비용과 latency가 가장 낮은 route를 선택한다.**

품질 모드 `m`과 페이지 context `x`, parser action `a`에 대해:

```text
Choose a*

minimize:
    E[cost(a|x)]
  + λ_m · E[latency(a|x)]
  + μ_m · P(catastrophic_failure|x,a)

subject to:
    P(quality >= Q_m | x,a) >= τ_m
```

초기에는 이 확률을 정확히 안다고 가정하지 않는다. heuristic/rules와 과거 benchmark table로 근사한다.

## 9.2 초기 deterministic policy

```python
def choose_route(profile, mode, registry):
    if profile.native_text_ratio > HIGH and profile.visual_risk < LOW:
        return best(R0_NATIVE_TEXT, mode)

    risks = detect_route_risks(profile)

    if risks.cross_page:
        route = R7_CROSS_PAGE
    elif risks.degraded:
        route = R5_DEGRADED_SCAN
    elif risks.table_complex:
        route = R3_TABLE_COMPLEX
    elif risks.formula:
        route = R4_FORMULA_SCIENTIFIC
    elif risks.layout_complex:
        route = R2_LAYOUT_COMPLEX
    else:
        route = R1_SIMPLE_VISUAL

    return cheapest_parser_meeting_capability(route, mode)
```

## 9.3 절대 규칙

- router confidence가 낮으면 싼 route로 강제하지 않는다.
- `R9_UNKNOWN`은 Balanced 이상에서 최소 medium-strength parser.
- 저품질 scan을 native/fast path로 보낼 수 없다.
- table/formula를 감지했는데 해당 capability가 낮은 parser 선택 금지.
- routing 결과는 `route_reason[]`으로 설명 가능해야 한다.

## 9.4 Router output contract

```json
{
  "page": 17,
  "route_class": "R3_TABLE_COMPLEX",
  "parser_id": "paddle_vl_1_6",
  "confidence": 0.88,
  "reasons": ["merged_cell_risk", "table_area_ratio_high"],
  "estimated_cost": null,
  "estimated_latency_ms": null,
  "fallback_chain": [
    "mineru_3_4_4_vlm",
    "strong_verifier"
  ]
}
```

---

# 10. Learned Router v2.1 — production outcome로 학습

처음부터 contextual bandit를 production에 적용하지 않는다.

## 10.1 저장해야 하는 outcome dataset

```text
profile_features
route_class
parser_id
parser_config
quality_signals
official_eval_if_available
recovery_required
final_status
latency_ms
gpu_seconds
cost_estimate
human_review_outcome
```

## 10.2 1차 learned router

Gradient-boosted trees 또는 동급의 작고 설명 가능한 모델로 다음을 각각 예측:

- `P(parse_pass | x, parser)`
- expected structural fidelity
- expected table/formula risk
- expected latency p50/p95
- expected cost
- recovery probability

## 10.3 champion/challenger

- production champion은 안정된 router.
- challenger는 shadow mode에서 같은 page의 추천만 기록.
- production output에는 영향 없음.
- 충분한 labeled outcome 후 offline replay.
- quality regression이 없고 cost/latency frontier가 개선될 때만 promote.

## 10.4 exploration 금지

유료 고객 production에서 “학습을 위해” 무작위로 약한 parser를 보내지 않는다.

탐색은:
- benchmark corpus
- shadow mode
- explicit experimental workspace
에서만 한다.

---

# 11. Adaptive Execution Planner

Router가 page마다 parser를 골라도 무작정 page를 독립 dispatch하지 않는다.

## 11.1 page groups

- 같은 route/parser의 contiguous pages를 batch
- cross-page candidate는 adjacent window 유지
- table continuation 후보는 같은 worker 또는 reconciliation metadata 제공
- huge page는 독립 task

## 11.2 batch 계획

```text
Document 100 pages

1–25   R0_FAST
26–31  R3_TABLE
32–60  R0_FAST
61–64  R7_CROSS_PAGE
65–100 R1_SIMPLE
```

동일 parser batch를 묶되, final assembly는 원문 순서를 보존한다.

## 11.3 병렬화 원칙

- global layout/order 정보가 필요한 단계는 먼저 cheap pass.
- block/page content는 가능한 부분 병렬.
- final document reconciliation은 중앙 단계.
- “페이지별 성공”을 “문서 성공”으로 승격하기 전에 reconciliation 통과 필수.

---

# 12. Parser Adapter Contract

모든 parser는 아래 normalized output을 반환해야 한다.

```yaml
parser_result:
  parser_run_id: ...
  parser_id: ...
  page: 17
  raw_artifact_uri: r2://...
  blocks:
    - local_id: b1
      type: text | title | table | figure | equation | caption | ...
      text: ...
      bbox_normalized: [0.1,0.2,0.9,0.3]
      confidence_raw: null
      order: 12
      structured: {}
  warnings: []
  timing:
    queue_ms: ...
    cold_start_ms: ...
    inference_ms: ...
  resource:
    gpu_type: ...
    gpu_seconds: ...
```

Parser-specific confidence를 공통 confidence로 직접 비교하지 않는다. Calibration 없이 `0.9`와 `0.9`는 서로 다른 의미일 수 있다.

---

# 13. RunPod Execution Architecture

## 13.1 Source of truth

- **R2 = permanent source of truth**
- RunPod container disk = ephemeral
- Network Volume = model/cache/hot working set only
- final parser artifact는 worker 종료 전 R2에 commit

## 13.2 RunPod 함정

- Serverless job TTL은 queue 대기시간 + execution 시간을 모두 포함한다.
- result retention에 의존하지 않는다.
- Network Volume은 cold start를 줄일 수 있지만 특정 data center에 endpoint를 묶어 GPU 가용성을 낮출 수 있다.
- volume 미부착 endpoint도 유지해 provider failover 선택지를 남길 수 있다.

## 13.3 endpoint tier

초기 권장:

```text
parser-balanced
  queue endpoint
  min_workers: traffic에 따라 0 또는 1
  common models cached

parser-verified
  stronger GPU / larger memory
  max workers lower
  recovery/verification only
```

모델마다 endpoint를 무한히 만들지 않는다. 실제 cold-start/availability benchmark 후 조정한다.

## 13.4 job idempotency

```text
job_key =
hash(document_version_id + page_group + parser_id + parser_config_hash + compiler_version)
```

동일 job_key가 이미 `DELIVERED`이면 재실행하지 않는다.

## 13.5 worker completion protocol

1. result serialize
2. R2 upload
3. checksum verify
4. DB artifact row commit
5. only then job `DELIVERED`

---

# 14. Failure Taxonomy v2

```text
F0_SOURCE_CORRUPT
F1_SOURCE_UNSUPPORTED
F2_UPLOAD_STORAGE
F3_QUEUE_TIMEOUT
F4_WORKER_LOST
F5_MODEL_INIT
F6_MODEL_OOM
F7_PARSER_EXCEPTION
F8_EMPTY_OUTPUT
F9_SUSPICIOUSLY_SHORT
F10_DUPLICATED_CONTENT
F11_GARBLED_TEXT
F12_READING_ORDER
F13_TABLE_STRUCTURE
F14_FORMULA
F15_FIGURE_CAPTION
F16_CROSS_PAGE
F17_NATIVE_RENDER_DISAGREEMENT
F18_PARSER_DISAGREEMENT
F19_ENTITY_AMBIGUITY
F20_AUTHORITY_CONFLICT
F21_TEMPORAL_UNCERTAINTY
F22_LINEAGE_BROKEN
F23_DEPENDENCY_CYCLE_OR_EXPLOSION
F24_RECOMPILE_DIVERGENCE
F25_PERMISSION_VIOLATION
F26_STALE_WORLD_STATE
F27_COST_BUDGET_EXCEEDED
F28_SECURITY_BLOCKED
```

각 failure는:
- severity
- confidence
- evidence
- recoverable?
- recovery policy
를 갖는다.

---

# 15. Post-Parse Inspector — 장애 판별 두뇌

기존 campaign의 **blind quality detector 실패** 때문에 단일 점수 기반 detector를 사용하지 않는다.

## 15.1 독립 detector 그룹

### A. source-aware completeness
- blank source인지 먼저 확인
- source expected text/image coverage 대비 output coverage
- native text chars와 output chars ratio
- rendered foreground area 대비 parsed block coverage

### B. structural
- blocks out of page bounds
- excessive overlap
- order discontinuity
- impossible heading nesting
- list numbering break
- table row/column count anomaly

### C. textual
- replacement char ratio
- symbol burst
- repeated n-gram
- repeated entire block
- language mismatch
- very low alphanumeric ratio where not expected

### D. visual-semantic
- parser block bbox와 rendered page alignment
- table detected visually but no table output
- formula/figure likelihood high but missing corresponding block
- caption with no nearby figure

### E. cross-page
- incomplete sentence at page end + compatible continuation
- same table header/schema across page boundary
- numbering continuation
- heading structure continuity

### F. consensus
- suspicious page only second parser 실행
- normalized text/block/tree disagreement
- Consensus Entropy-like agreement signal

### G. downstream
- invalid IR
- provenance missing
- unsupported claim
- dangling internal link
- graph invariant failure

## 15.2 inspector result

```json
{
  "status": "SUSPICIOUS",
  "severity": "HIGH",
  "signals": [
    {"code":"F13_TABLE_STRUCTURE","score":0.91},
    {"code":"F18_PARSER_DISAGREEMENT","score":0.84}
  ],
  "recommended_action":"RECOVERY_REROUTE_TABLE"
}
```

## 15.3 fail policy

- catastrophic signal 1개면 fail 가능.
- weak signal 여러 개면 weighted vote.
- 단일 parser self-confidence만으로 PASS 금지.
- confidence threshold는 benchmark로 calibration.

---

# 16. Consensus / Agreement Algorithm

모든 page에 multi-parser를 돌리지 않는다.

```text
primary parse
   ↓
inspector
   ├ HIGH CONFIDENCE PASS → accept
   └ suspicious
        ↓
   secondary parser
        ↓
 agreement analysis
        ├ agree + source checks pass → accept/recovered
        ├ disagree → verifier/third route
        └ both fail → fail/review
```

## 16.1 agreement dimensions

- normalized text similarity
- block-type sequence similarity
- bbox IoU/alignment
- table grid similarity
- formula normalized equivalence
- reading-order edit distance

## 16.2 규칙

Agreement는 truth가 아니다. 두 모델이 같이 틀릴 수 있다.

따라서:
`agreement + source-aware checks + structural invariants`
가 함께 필요하다.

---

# 17. Recovery Policy Engine

Recovery는 “같은 걸 다시 돌리기”가 아니다.

## 17.1 Escalation Ladder

```text
L0 ACCEPT
L1 SAME PARSER + SAFE PREPROCESS
L2 SAME FAMILY DIFFERENT CONFIG
L3 DIFFERENT PARSER
L4 ENSEMBLE / AGREEMENT
L5 STRONG VLM VERIFIER
L6 DOCUMENT-LEVEL RECONCILIATION
L7 HUMAN REVIEW
L8 FAIL CLOSED
```

## 17.2 failure → action

| Failure | Primary recovery |
|---|---|
| F3 queue timeout | new healthy worker / TTL corrected |
| F4 worker lost | rerun same job on healthy worker |
| F6 OOM | smaller batch / larger GPU |
| F8 empty | blank-source check → rerender/DPI → alternate parser |
| F9 short | higher DPI / alternate parser |
| F10 duplicate | decoding/parser config change / alternate parser |
| F11 garbled | OCR/VLM route, language hint |
| F12 reading order | layout-aware route + document reconciler |
| F13 table | table-specialized/agentic route |
| F14 formula | formula-capable parser/verifier |
| F16 cross-page | adjacent-page joint reconciliation |
| F18 disagreement | verifier/third parser |
| F19 entity ambiguity | semantic resolver / human review |
| F20 authority conflict | authority engine / human rule |
| F21 temporal uncertainty | keep unknown/inferred, no fabricated date |
| F24 recompile divergence | block publish + full rebuild fallback |
| F25 permission | security block, never retry by broadening access |
| F27 cost budget | stop escalation / explicit partial status |

## 17.3 Safe preprocessing

허용:
- rotation normalize
- deskew
- DPI re-render
- grayscale/contrast normalization
- safe crop
- dewarp if confidence high

금지:
- source content를 의미적으로 바꾸는 generative “cleanup”을 원본 evidence로 취급
- upscale output을 원본으로 overwrite

모든 preprocessing artifact도 lineage에 남긴다.

## 17.4 retry storm 방지

```yaml
recovery_budget:
  max_attempts_per_page: 4
  max_gpu_seconds: ...
  max_wall_clock_seconds: ...
  max_cost: ...
  stop_on_same_failure_signature: true
```

global provider failure pattern을 감지하면 새 worker 구매/생성을 멈추고 circuit breaker.

---

# 18. Document Reconciler — v2 필수 Core

page parser가 모두 성공해도 document가 틀릴 수 있다.

## 18.1 처리 대상

- paragraph continuation
- list continuation
- table spanning pages
- figure-caption cross-page
- section hierarchy
- headers/footers repetition removal
- references/footnotes
- page-break-induced chunk split

## 18.2 candidate linking

인접 페이지 pair마다:

```text
continuation_score =
  w1 * sentence_boundary
+ w2 * semantic_similarity
+ w3 * layout_alignment
+ w4 * style_similarity
+ w5 * numbering_continuity
+ w6 * table_schema_similarity
```

## 18.3 table continuation

두 table이 다음을 만족하면 same-table candidate:
- adjacent pages
- column count compatible
- normalized header similarity
- x-position alignment
- style/border pattern compatible
- first table page-bottom / second page-top 위치

merge를 확정할 때 원본 cell provenance를 절대 잃지 않는다.

## 18.4 uncertain merge

- high confidence: auto merge
- medium: logical relation `CONTINUES`만 생성, physical merge 안 함
- high-risk domain/low confidence: review

---

# 19. Canonical Knowledge IR v2

v1의 IR을 확장한다.

```yaml
knowledge_unit:
  logical_id: ku_...
  version_id: kuv_...
  tenant_id: t_...
  workspace_id: w_...

  unit_type: paragraph | clause | table | table_row | table_cell |
             figure | caption | list | procedure | policy | claim | metadata

  content:
    text: ...
    normalized_text: ...
    structured_payload: {}

  structure:
    document_path: [...]
    heading_level: 2
    sequence_index: 142
    parent_logical_id: ...
    continuation_of: null

  source:
    source_id: ...
    document_version_id: ...
    page: 17
    bbox: [...]
    span_start: ...
    span_end: ...
    source_hash: ...
    render_artifact_id: ...

  extraction:
    parser_run_id: ...
    parser_id: ...
    parser_version: ...
    parser_confidence_raw: null
    route_class: R3_TABLE_COMPLEX
    recovery_round: 1
    preprocessing_chain: []

  quality:
    validation_state: VERIFIED | UNVERIFIED | FAILED | RECOVERED
    inspector_signals: []
    human_review_state: NONE | REQUIRED | RESOLVED

  temporal:
    valid_from: null
    valid_to: null
    recorded_at: ...
    superseded_at: null
    temporal_source: EXPLICIT | INFERRED | UNKNOWN
    temporal_evidence_ids: []

  epistemic:
    status: EXPLICIT_FACT | DERIVED | INFERRED | CONFLICTED | UNKNOWN
    confidence: null
    derivation_method: null

  semantics:
    entities: []
    relationships: []
    claims: []

  lineage:
    derived_from: []
    depends_on: []
    supersedes: []

  governance:
    authority: UNKNOWN | INFORMAL | OFFICIAL | CONTRACTUAL | SYSTEM_OF_RECORD
    scope: {}
    applicability: {}
    permission_scope: []
    sensitivity: null
```

## 19.1 원칙

- source 없는 claim 금지
- 가짜 bbox 금지
- unknown date를 확정값으로 저장 금지
- parser confidence와 semantic confidence 혼동 금지
- raw source → preprocessing → parser → IR 변환을 모두 lineage로 남김

---

# 20. Stable Identity v2

## 20.1 deterministic IDs

```text
source_id = hash(tenant + connector_type + connector_native_id_or_canonical_path)
document_version_id = hash(source_id + content_sha256)
evidence_id = hash(document_version_id + page + normalized_bbox + normalized_span_hash)
```

## 20.2 logical unit matching

새 version의 unit `u2`를 기존 `u1`과 같은 logical unit으로 볼지:

```text
identity_score =
  0.30 source_continuity
+ 0.20 structural_path_similarity
+ 0.20 semantic_anchor_similarity
+ 0.15 previous_neighbor_match
+ 0.15 next_neighbor_match
```

가중치는 초기 heuristic이며 fixture benchmark로 calibration한다.

## 20.3 정책

- high score: same logical id
- uncertain band: ambiguous mapping, review/keep separate
- low: new logical id
- **false merge cost > false split cost**

---

# 21. Entity Resolution

## 21.1 priority

1. deterministic external/native ID
2. explicit alias
3. exact structured attributes
4. context/relationship overlap
5. semantic similarity
6. LLM proposal

LLM proposal만으로 auto merge 금지.

## 21.2 entity candidate

```yaml
entity_candidate:
  entity_type: machine
  mentions: ["Machine 12","M-012","Asset_7782"]
  deterministic_ids: [...]
  merge_score: ...
  evidence_ids: [...]
  decision: AUTO | REVIEW | SPLIT
```

## 21.3 검증

- duplicate alias
- homonym
- entity merge precision
- entity split recall
- graph blast-radius after deliberate false merge injection

---

# 22. Authority / Applicability Resolution Engine

단순 `latest wins` 금지.

## 22.1 claim context

```yaml
claim_context:
  subject: warranty
  object: Product X
  customer: Customer A
  region: US
  contract: Contract C
  date: 2026-08-10
```

## 22.2 candidate rank factors

1. permission visibility
2. temporal validity
3. applicability/scope match
4. explicit exception/override
5. authority class
6. source status
7. specificity
8. recency — **마지막 쪽 요소**, 항상 최우선 아님

## 22.3 예

Global Policy:
- 3 years
- authority: OFFICIAL
- scope: all customers

Customer A Contract:
- 5 years
- authority: CONTRACTUAL
- scope: Customer A
- valid period explicit

Customer A 질문에는 contract가 우선할 수 있다.

## 22.4 unresolved

동등한 authority와 scope에서 conflicting claims가 남으면:
`CONFLICTED`
로 저장하고 AI에게 하나를 임의로 고르게 하지 않는다.

---

# 23. Temporal Model v2

## 23.1 두 시간축

- Valid Time: 현실에서 언제 사실이었는가
- System Time: TAVONEL이 언제 그 사실을 알았는가

## 23.2 unknown/inferred

문서에 “2026년부터”만 있으면 임의로 1월 1일을 만들지 않는다.

초기 구현:
- exact
- partial
- inferred
- unknown

필요 시 이후 uncertainty interval 확장.

## 23.3 transaction correctness

같은 entity/claim의 temporal interval 업데이트는 transaction 안에서 수행.
경합 시 lock/advisory lock 또는 serializable transaction retry 정책을 사용.

---

# 24. Epistemic / Uncertainty Layer

```text
EXPLICIT_FACT
문서에 직접 있음

DERIVED
deterministic transform

INFERRED
model/rule 추론

CONFLICTED
복수 source 충돌

UNKNOWN
근거 부족
```

숫자 confidence 하나보다 상태와 provenance를 우선한다.

---

# 25. Semantic Diff v2

## L0 Binary
content hash

## L1 Structural
heading tree / table structure / figure refs

## L2 Evidence
added / removed / modified / moved spans/cells

## L3 Semantic
claim/value/condition/exception/step

## L4 Graph
entity/relation/authority/validity

## L5 Operational
downstream behavior/policy impact

### 핵심 예
`may` → `must`

text diff는 작아도 L5 impact는 클 수 있다.

## 25.1 algorithm

1. stable identity alignment
2. deterministic structured diff
3. semantic candidate extraction
4. LLM/rule classification of change type
5. evidence anchoring
6. confidence
7. high-risk diff validation

---

# 26. Dependency Graph v2 — Typed Propagation

## 26.1 edge

```text
DERIVED_FROM
DEPENDS_ON
SUPPORTS
SUPERSEDES
REFERENCES
CONTINUES
CONSUMED_BY
EXPORTS_TO
INVALIDATES
```

## 26.2 invalidation semantics

| Edge | Default propagation |
|---|---|
| DERIVED_FROM | invalidate child |
| DEPENDS_ON | revalidate/invalidate |
| SUPPORTS | revalidate |
| SUPERSEDES | close validity/update resolution |
| REFERENCES | notify; do not auto-invalidate unless semantic dependency |
| CONTINUES | re-reconcile |
| CONSUMED_BY | mark consumer context stale |
| EXPORTS_TO | regenerate export |
| INVALIDATES | hard stale |

## 26.3 cycle protection

- traversal visited set
- max nodes/depth
- SCC detection for suspicious cycles
- lineage subgraph는 DAG invariant가 필요한 영역 별도 검사
- recursive CTE query limit + timeout

---

# 27. Impact Engine

## 27.1 input

`ChangeSet`

## 27.2 output

```yaml
impact_report:
  change_id: ...
  directly_changed_units: []
  invalidated_units: []
  revalidate_units: []
  affected_chunks: []
  affected_exports: []
  affected_agents: []
  unaffected_count: ...
  blocked_by_conflict: []
```

## 27.3 propagation

typed edge rule을 적용한 BFS/recursive CTE.

## 27.4 explosion protection

한 변경이 workspace 대부분을 invalidate하면:
- edge granularity audit
- route `IMPACT_EXPLOSION`
- full rebuild fallback 고려
- user에게 이유 표시

---

# 28. Incremental Recompilation

```text
SOURCE CHANGE
→ semantic diff
→ typed impact
→ mark stale
→ affected-only tasks
→ recompile
→ validate
→ compare invariants
→ atomic world-state publish
```

## 28.1 가장 중요한 invariant

> **Selective result must be equivalent to the relevant subset of a full rebuild.**

## 28.2 divergence

equivalence 실패:
- new world state publish 금지
- affected slice 또는 full rebuild fallback
- regression artifact 저장
- release gate failure

---

# 29. Cache Invalidation

cache key에 최소:

```text
logical_id
version_id
compiler_version
parser/model version
export schema version
permission scope hash
```

단순 content hash만으로 downstream summary/embedding cache를 유지하지 않는다.

---

# 30. Integrity Validator

## 30.1 categories

- extraction completeness
- structural consistency
- source existence
- evidence anchoring
- semantic unsupported claim
- entity ambiguity
- authority conflict
- temporal contradiction
- lineage break
- dependency invariant
- stale downstream
- permission boundary
- selective/full divergence

## 30.2 상태

```text
PARSED
STRUCTURED
COMPILED
VALIDATED
VERIFIED
```

파일이 출력됐다고 `SUCCESS`가 아니다.

## 30.3 fail-closed

critical:
`COMPILE_BLOCKED`

noncritical:
`PUBLISHED_WITH_WARNINGS`는 제한적으로만 허용하고 warning을 UI/API에 노출.

---

# 31. Human Review Queue

사람이 모든 문서를 검수하는 제품이 되어서는 안 된다.

**사람은 자동화가 확실하지 않은 작은 fraction만 본다.**

## 31.1 review types

- entity merge ambiguity
- authority conflict
- unknown effective date
- cross-page uncertain merge
- parser disagreement high-risk
- contract exception
- permission conflict

## 31.2 review decision provenance

```yaml
review_decision:
  review_id: ...
  object_type: claim
  object_id: ...
  decision: ...
  reviewer_id: ...
  evidence_ids: [...]
  reason: ...
  decided_at: ...
```

이 결정도 다음 version의 knowledge에 provenance로 남는다.

---

# 32. Versioned World State / Atomic Publish

Agent가 compile 중간 상태를 읽어서는 안 된다.

```text
world_state_id = ws_...
status = BUILDING | VALIDATING | ACTIVE | REJECTED | SUPERSEDED
```

## 32.1 publish protocol

1. all affected outputs staged
2. validation
3. permission checks
4. transaction commit
5. ACTIVE pointer swap
6. previous world state SUPERSEDED

Agent read API는 `ACTIVE`만 기본 조회.

---

# 33. Retrieval / RAG Layer

TAVONEL의 RAG는 제품의 끝이 아니라 consumer다.

## 33.1 retrieval order

1. permission filter
2. temporal/as-of filter
3. applicability/authority resolution
4. lexical + dense candidate
5. optional graph neighborhood
6. rerank
7. provenance attach

## 33.2 pgvector 주의

metadata filtering + ANN에서 recall 문제가 생길 수 있으므로:
- pgvector iterative scans 사용 검토
- partial index/partitioning은 실제 cardinality 기준
- filtered retrieval benchmark 별도
- 적은 corpus에서는 exact search도 비교

## 33.3 query output

항상:
- unit version
- evidence IDs
- authority
- valid time
- world_state_id
를 함께 반환.

---

# 34. API / MCP

## 34.1 Read-first

```text
knowledge.search
knowledge.get
knowledge.as_of
knowledge.diff
source.verify
entity.get
entity.history
impact.trace
world_state.current
```

## 34.2 MCP 2026-07-28 대응 원칙

- tool input validation
- proper access control
- rate limiting
- output sanitization
- sensitive write/action은 explicit consent/approval
- HTTP transport authorization은 최신 MCP authorization spec 준수

## 34.3 Write later

```text
source.ingest
knowledge.recompile
workspace.sync
```

write는 idempotency + audit + permission + approval gate.

---

# 35. Agent Consumption Lineage

```yaml
agent_consumption:
  request_id: ...
  tenant_id: ...
  agent_id: ...
  world_state_id: ...
  retrieved_unit_versions: [...]
  evidence_ids: [...]
  permissions_snapshot: ...
  tool_calls: [...]
  action: ...
  timestamp: ...
```

목적:

> source가 바뀌었을 때 과거/현재 어떤 agent context가 영향을 받았는가?

---

# 36. Decision Replay

재현 대상:
- knowledge/world state
- evidence
- permissions
- retrieved context
- tool inputs/outputs
- action trace

**모델의 숨은 내부 chain-of-thought을 재현한다고 주장하지 않는다.**

---

# 37. Performance Model — 고객 체감 속도

## 37.1 latency를 3개로 분리

### TTA — Time to Acknowledgement
upload accepted + manifest/preflight 시작

### TTFP — Time to First Parsed/Preview Result
첫 usable page/block

### TTUK — Time to Usable Knowledge
검색/export가 가능한 최소 world state

### TTCV — Time to Complete Verified
recovery/validation까지 끝난 상태

전체 batch가 끝날 때까지 아무것도 보여주지 않는 UX 금지.

## 37.2 progressive availability

```text
83 files
✓ preflight 83
✓ parsed 61
↻ recovery 4
✓ structured 45
✓ verified 31
```

실제 state machine을 그대로 표시하고 fake % 금지.

## 37.3 p50/p95/p99

평균 latency만 보고 출시 금지.

- parser queue p50/p95/p99
- inference
- recovery
- reconciliation
- compile
- total TTUK

---

# 38. Quality Modes

## FAST
- native/cheap path 우선
- recovery L2 정도까지
- 일반 검색/내부 초안

## BALANCED — default
- full inspector
- risk-based reroute
- recovery L4 정도

## VERIFIED
- high-risk pages ensemble/verifier
- stricter document validation
- L7 review 가능
- 계약/정책/compliance

mode는 단순 마케팅 label이 아니라 실제 routing/recovery budget과 연결.

---

# 39. Cost Control

## 39.1 budget

per:
- page
- document
- job
- workspace
- billing period

## 39.2 stop condition

- recovery attempts
- GPU seconds
- wall clock
- provider anomaly
- same failure signature

## 39.3 estimate

upload 직후 rough:
- pages
- route distribution
- expected GPU work
- credit range

estimate와 final billed usage 모두 telemetry에 저장.

---

# 40. Observability / Knowledge SLO

OpenTelemetry trace/metrics/log을 기본으로 한다.

## 40.1 trace span 예

```text
tavonel.ingest
tavonel.preflight
tavonel.profile
tavonel.route
tavonel.runpod.queue
tavonel.parse
tavonel.inspect
tavonel.recover
tavonel.reconcile
tavonel.ir
tavonel.diff
tavonel.impact
tavonel.recompile
tavonel.validate
tavonel.publish
```

## 40.2 제품 SLO 후보 — 출시 전 측정값으로 확정

- Knowledge Freshness SLO
- World Sync Latency
- Provenance Coverage
- Stale Context Rate
- Recovery Success
- Tail Latency
- Selective Recompile Equivalence Rate

숫자는 실제 benchmark/pilot 후 고정하고 마케팅 claim과 분리한다.

---

# 41. Security / Multitenancy

## 41.1 PostgreSQL

- 모든 tenant-owned table에 tenant_id
- Row-Level Security
- table owner bypass를 고려해 FORCE RLS 검토
- API service role separation
- test: cross_tenant_access_must_fail

## 41.2 R2

object key:
`{tenant}/{workspace}/...`

presigned URL은:
- exact key
- allowed method
- short expiry
- no broad bucket credential

## 41.3 processing sandbox

uploaded file은 hostile input으로 간주.
Parser worker 최소 권한.
network egress 필요 최소화.
host filesystem mount 금지.

## 41.4 secrets

- production secret를 Claude prompt/file에 평문 저장 금지
- GitHub Actions/Vercel/managed secret store
- local `.env` gitignore
- key rotation runbook

---

# 42. Event / Job Architecture

초기에는 Kafka 금지.

PostgreSQL-backed durable jobs + R2 events로 충분.

## 42.1 event

```text
source.uploaded
source.version.detected
parse.planned
parse.completed
recovery.requested
reconcile.completed
knowledge.compiled
knowledge.invalidated
recompile.completed
world_state.published
```

## 42.2 consumer

Postgres queue table + `FOR UPDATE SKIP LOCKED` 가능.
job claim/lease/heartbeat 필수.

## 42.3 idempotency

각 handler는 duplicate/reordered event에도 안전하게 설계.

event 자체 순서를 진실로 믿지 말고:
`source version/content hash/recorded_at`
로 state transition 검증.

---

# 43. R2 Production Rules

- browser direct upload: presigned URL
- large file: multipart
- incomplete multipart lifecycle
- original source immutable/versioned
- evidence append-only 선호
- public benchmark artifacts 별도 prefix/bucket
- critical evidence는 bucket lock/retention policy 검토
- R2 event notification은 ingest trigger로 활용 가능하나 business idempotency는 자체 구현

---

# 44. Benchmark Program v2 — 제품 개발의 심장

## Suite A — 기존 Public Extraction Baseline
- ParseBench
- OmniDocBench
- olmOCR-Bench
- existing receipts 유지

## Suite B — New Difficult Parsing
후보:
- MPDocBench-Parse
- Dr. DocBench
- PureDocBench
- industrial RAG-oriented OCR benchmark
- license/availability 확인 후 fixture pin

## Suite C — TAVONEL Router Bench
ground truth parser outcome matrix가 있는 page set.

## Suite D — Failure/Recovery Bench
failure injection + known expected recovery.

## Suite E — Knowledge Evolution Bench
versioned corpus + controlled mutation.

## Suite F — Agent Grounding Bench
plain RAG vs authority/temporal/provenance filtered context.

## Suite G — Security/Chaos
worker/storage/event/db/permission failure.

---

# 45. Router Benchmark

## 45.1 Oracle Matrix

페이지 `i`, parser `p`마다:
- quality
- latency
- cost
- failure status

를 측정.

## 45.2 metrics

### Routing Quality Regret
router가 고른 parser 품질과 oracle quality 차이.

### Cost Regret
동일 quality threshold를 만족하는 최저비용 대비 초과 비용.

### Latency Regret

### Escalation Rate

### Catastrophic Miss Rate
Hard page를 fast parser로 보내고 inspector도 놓친 비율.

**가장 중요: catastrophic miss.**

---

# 46. Failure Detector Benchmark

각 failure type을 label한 adversarial set.

측정:
- per-failure precision/recall
- high-severity recall
- false escalation
- silent corruption miss
- blank-source false positive

기존 blind detector 실패를 반복하지 않기 위해 aggregate 하나가 아니라 failure-type별 결과 공개.

---

# 47. Recovery Benchmark

각 recovery action에 대해:

```text
input failure
baseline output
recovery output
quality delta
cost delta
latency delta
terminal state
```

같은 model 재시도와 다른 model reroute를 분리해 효과 측정.

---

# 48. Cross-Page / Document Benchmark

fixture:
- split paragraph
- split table
- repeated header
- continuation list
- figure/caption next page
- section hierarchy crossing pages

metrics:
- continuation precision/recall
- table merge accuracy
- hierarchy accuracy
- false merge rate

false merge를 특히 비싸게 본다.

---

# 49. Knowledge Evolution Ground-Truth Corpus

TAVONEL의 차세대 proprietary research asset.

## 49.1 예

v1:
- warranty 2y
- manager A
- Product X active

v2:
- warranty 3y
- manager B
- Product X discontinued

Customer A contract:
- warranty 5y exception

## 49.2 ground truth

- exact changed evidence
- stable logical IDs
- entity merges/splits
- authority resolution
- temporal interval
- affected units/chunks/exports/agents
- unaffected set

## 49.3 metrics

- Semantic Diff precision/recall
- Impact precision/recall
- Selective/full equivalence
- Work Avoided
- World Sync Latency
- Cost Avoided

---

# 50. Competitive Evaluation Suite

경쟁사 “빠르고 정확하다”를 마케팅 숫자로 판단하지 않는다.

동일 corpus, 동일 timeout, 동일 page set으로:

- TAVONEL baseline
- TAVONEL adaptive
- MinerU standalone
- PaddleOCR-VL current pinned candidate
- Mistral OCR 4 API
- Reducto parse standard / agentic(where fair)
- Unstructured auto/vlm/hi_res
- 기타 경쟁사: 약관/API가 허용하고 비교 조건이 공정할 때

## 50.1 측정

- text fidelity
- table
- formula
- reading order
- hierarchy
- cross-page
- latency p50/p95
- failure rate
- cost/page
- downstream knowledge correctness

vendor internal claim을 TAVONEL reproduced result처럼 쓰지 않는다.

---

# 51. Chaos / Failure Injection

매 release 또는 nightly subset에:

- RunPod worker kill
- cold start
- queue backlog
- R2 transient failure
- duplicate source event
- out-of-order update
- DB reconnect
- stale lock
- parser empty
- parser duplicate
- model disagreement
- corrupt page
- old version arriving after new
- dependency cycle
- cross-tenant request
- recovery budget exhaustion

성공 조건:
- data loss 없음
- unverified knowledge publish 없음
- audit trace 존재
- fail closed 또는 automatic recovery
- cost circuit breaker 정상

---

# 52. Model Upgrade Policy

새 모델이 “더 좋아 보인다”는 이유로 production replacement 금지.

```text
NEW MODEL
→ adapter
→ public benchmark
→ router oracle matrix
→ difficult/cross-page suite
→ cost/latency
→ shadow
→ challenger
→ no-regression gate
→ champion
```

model version/container digest/prompt/config pin.

---

# 53. Knowledge Health Scan v2

## 외부 문장

> **See what your AI would get wrong.**

## 53.1 scan output

- likely duplicates
- version conflicts
- authority conflicts
- broken refs
- unresolved figures/assets
- parser/recovery events
- ambiguous entities
- temporal uncertainty
- stale candidate paths

## 53.2 AI Risk Simulation

정확한 “정답률 예측”이라고 과장하지 않는다.

대신:

```text
Potentially conflicting answer paths: 7
Potentially outdated answer paths: 12
Unsupported claims found: 8
Ambiguous entities: 4
```

각 항목은 evidence 클릭 가능.

## 53.3 Conversion

`Issue → Evidence → Blast radius → Compile workspace`

---

# 54. Product UX

필수 surface:

1. Workspace Overview
2. Ingest / live pipeline
3. Evidence Explorer
4. Recovery Inspector
5. Change Center
6. Impact Explorer
7. Timeline / As-of
8. Review Queue
9. Compile/Export
10. Health Scan report

Progress UI는 실제 state를 사용.

---

# 55. Website / Brand — v1 유지 + 증거 강화

핵심:
- Calm Intelligence + Precision + Evidence + Temporal Depth
- generic AI purple-neon 금지
- motion encodes meaning
- 3D는 장식이 아니라 source→structure→time→change→impact→recompile를 설명

Hero:
> **Your AI is only as reliable as the reality it sees.**

CTA:
> **Scan your knowledge →**

Interactive WOW:
`Warranty 2y → 3y`
→ affected count
→ selective recompile

---

# 56. Marketing Claim Ladder

## Level 0 — Philosophy
증거 숫자 없음.

## Level 1 — Existing verified evidence
현재 campaign receipts만.

## Level 2 — New parsing/router evidence
외부 공개 benchmark 재현 후.

## Level 3 — Knowledge CI/CD
Diff/Impact/Equivalence benchmark 완료 후.

## Level 4 — Customer outcome
pilot/customer consent + reproducible methodology.

**절대 순서를 건너뛰지 않는다.**

---

# 57. Gracian Code → TAVONEL Distribution Engine

```text
Insight / WOW
→ Technical mechanism
→ Big-tech / research proof
→ TAVONEL research
→ Evidence
→ Health Scan
→ Customer's own problem
→ Compile
→ Continuous Sync
→ Paid
```

콘텐츠에서 제품 이름을 매번 말하지 않는다.

내부 `TAVONEL BRIDGE SCORE`:
- 0 pure philosophy/science
- 1 indirect
- 2 knowledge/agent problem
- 3 technology explanation
- 4 proof/demo
- 5 CTA

5화 연속 3 이상 금지.

---

# 58. GTM 초기 집중

첫 고객:
> **문서가 자주 바뀌고, 틀리면 실제 비용이 큰 조직**

초기 vertical:
1. Technical documentation / support
2. Manufacturing/manuals
3. Policy/compliance

Contract/legal은 authority/temporal/review가 안정화된 후 공격적으로 확대.

---

# 59. Pricing Principle

페이지 단가만 front-and-center로 두지 않는다.

Value metric 후보:
- managed knowledge volume
- processed/change volume
- continuous sync
- history/retention
- recompile usage
- connectors
- SLA

Parser cost는 내부 unit economics.

---

# 60. AI-Native Solo Founder Operating Model

목표:
> **Founder가 모든 코드를 검수하는 대신, AI가 구현하고 자동 evidence가 판정한다.**

```text
FOUNDER
  ↓ North Star / priority
LEAD CLAUDE
  ├ architecture
  ├ parser-runtime
  ├ knowledge-integrity
  ├ benchmark
  ├ backend
  ├ frontend
  ├ security
  ├ evidence
  └ visual-QA
       ↓
AUTOMATED GATES
       ↓
PASS / FAIL SUMMARY
```

---

# 61. Claude Code Agent Topology

`.claude/agents/`

### lead-architect
cross-module contracts, phase orchestration

### adaptive-runtime
profiler/router/model registry/execution planner

### recovery-engineer
inspector/failure taxonomy/recovery/reconciler

### knowledge-integrity
IR/stable ID/entity/authority/temporal/uncertainty

### lineage-impact
lineage/dependency/diff/impact/recompile

### infra-runtime
R2/RunPod/Postgres/jobs/telemetry

### benchmark-scientist
datasets/evaluators/statistics/receipts

### security-review
upload isolation/RLS/MCP/secrets/abuse

### frontend-product
app surfaces

### cinematic-director
R3F/GSAP

### visual-qa
Playwright/screenshot/accessibility/mobile

### evidence-auditor
claim ↔ receipt ↔ hash

---

# 62. Claude Hooks / CI

Claude 판단에 맡기지 않을 자동 gate.

## Python
- ruff
- mypy
- targeted pytest

## TypeScript
- eslint
- tsc
- vitest

## DB
- migration graph single head
- schema drift
- RLS test

## Router/recovery
- benchmark smoke subset
- failure fixtures

## Knowledge
- IR schema
- stable ID property tests
- lineage invariants
- temporal fixtures
- impact fixtures
- selective equivalence

## Marketing
- forbidden claim patterns
- claims pack artifact hash

## Web
- Playwright
- screenshots desktop/mobile
- reduced motion
- Lighthouse/perf budget where stable

Claude Code hooks can run deterministic checks around edits/actions; complex verification can be delegated to agent hooks.

---

# 63. Repository Architecture v2

```text
tavonel/
├─ CLAUDE.md
├─ docs/
│  ├─ north-star/
│  │  └─ TAVONEL_PRODUCTION_NORTH_STAR_v2.md
│  ├─ architecture/
│  │  ├─ adaptive-routing.md
│  │  ├─ failure-taxonomy.md
│  │  ├─ recovery-policy.md
│  │  ├─ document-reconciler.md
│  │  ├─ canonical-ir.md
│  │  ├─ identity.md
│  │  ├─ authority-resolution.md
│  │  ├─ temporal.md
│  │  ├─ semantic-diff.md
│  │  ├─ dependency-impact.md
│  │  ├─ recompilation.md
│  │  ├─ world-state.md
│  │  ├─ observability.md
│  │  └─ security.md
│  ├─ evidence/
│  └─ design/
├─ apps/
│  ├─ web/
│  └─ api/
├─ services/
│  ├─ ingest/
│  ├─ profiler/
│  ├─ router/
│  ├─ inspector/
│  ├─ recovery/
│  ├─ reconciler/
│  ├─ compiler/
│  ├─ identity/
│  ├─ authority/
│  ├─ temporal/
│  ├─ diff/
│  ├─ lineage/
│  ├─ impact/
│  ├─ recompilation/
│  └─ validation/
├─ workers/
│  ├─ runpod/
│  └─ parsers/
├─ packages/
│  ├─ ir/
│  ├─ schemas/
│  ├─ parser-adapters/
│  ├─ model-registry/
│  ├─ telemetry/
│  ├─ client/
│  └─ ui/
├─ benchmarks/
│  ├─ public/
│  ├─ router/
│  ├─ failure/
│  ├─ cross-page/
│  ├─ knowledge-evolution/
│  └─ chaos/
├─ migrations/
├─ tests/
└─ .claude/
   ├─ agents/
   ├─ skills/
   ├─ commands/
   └─ settings.json
```

기존 repository가 안정적이면 물리적 이동을 강제하지 않는다. logical boundary가 우선.

---

# 64. 구현 순서 — v2 Dependency-Aware Phases

## PHASE 0 — Freeze / Repository Audit
- 현재 git state
- tests
- evidence
- env/service inventory
- active deployment
- current schemas
- benchmark reproduction
- v2 gap matrix

**Exit:** baseline receipt 생성.

## PHASE 1 — Test Harness First
- ground-truth fixture framework
- parser run receipts
- benchmark runner
- failure injection framework
- no-regression CLI

**Exit:** 변경 전 baseline 자동 재현.

## PHASE 2 — Source Preflight + Manifest
- hash
- MIME
- limits
- R2 layout
- immutable source versions

## PHASE 3 — Profiler + Model Registry
- page features
- route classes
- parser adapter metadata
- route explanation

## PHASE 4 — Deterministic Router + Execution Planner
- cost-aware rule
- page grouping
- RunPod job idempotency

## PHASE 5 — Inspector + Failure Taxonomy
- source-aware blank
- text/structure/anomaly
- parser disagreement framework

## PHASE 6 — Recovery Policy + Document Reconciler
- escalation ladder
- table/text/formula/cross-page recovery
- retry budget

## PHASE 7 — Canonical IR v2 + Provenance + Stable IDs
- existing compiler migration through adapter
- raw artifacts preserved

## PHASE 8 — Entity + Authority + Temporal + Epistemic
- conservative merge
- conflict state
- review queue

## PHASE 9 — Semantic Diff + Lineage + Dependency
- L0–L5
- typed edges

## PHASE 10 — Impact + Incremental Recompile
- stale marking
- full rebuild equivalence
- atomic world state

## PHASE 11 — Retrieval/API/MCP
- read-only
- permission
- as-of
- impact
- evidence

## PHASE 12 — Health Scan + Commercial
- scan
- risk paths
- report
- auth/billing/analytics

## PHASE 13 — Website / Cinematic / Evidence
- real product UI as marketing asset
- 3D semantic motion

## PHASE 14 — Competitive + New Public Research
- router/recovery/cross-page/evolution benchmarks
- publish approved claims

## PHASE 15 — Enterprise Hardening
- SSO/RBAC
- retention
- audit export
- connector change capture
- SLA/SLO

## PHASE 16 — Decision Replay / Simulation
실수요 후.

---

# 65. Phase별 Done Definition

어떤 phase도 다음을 모두 만족하지 않으면 done 아님.

1. code
2. tests
3. failure path
4. benchmark/fixture
5. telemetry
6. docs
7. tenant isolation where applicable
8. migration rollback
9. evidence receipt
10. no-regression
11. UI screenshot QA if surface exists
12. claim pack update if public metric affected

---

# 66. Launch Candidate Gate

## Core
- production ingestion
- deterministic manifest/version
- adaptive router
- inspector/recovery
- document reconciler
- IR/provenance
- stable IDs
- basic entity/authority/version
- semantic diff
- impact
- selective recompile
- validation/world-state

## Performance
- p50/p95 recorded
- no runaway retry
- cost budget
- progressive results
- cold-start behavior documented

## Reliability
- chaos subset
- no silent publish on critical failure
- recovery receipts
- full/selective equivalence

## Security
- tenant isolation
- RLS
- upload limits/sandbox
- secrets
- deletion path
- security contact

## Commercial
- Health Scan
- onboarding
- billing
- trial quotas
- analytics

## Evidence
- current claims pack
- limitations
- methodology
- reproducibility

---

# 67. 마케팅 성공을 위한 기술-콘텐츠 루프

```text
Engineering problem
↓
Controlled experiment
↓
Receipt
↓
Research note
↓
Gracian Code insight
↓
TAVONEL Evidence page
↓
Health Scan
↓
Customer corpus
↓
New failure cases
↓
Benchmark expansion
↓
Engineering
```

이 루프가 1인 TAVONEL의 scale advantage가 된다.

---

# 68. 가장 중요한 신규 proprietary assets

1. **Router Outcome Dataset**
   - 어떤 page에 어떤 parser가 실제로 잘 작동했는가

2. **Failure/Recovery Dataset**
   - 어떤 실패를 어떤 recovery가 해결했는가

3. **Knowledge Evolution Dataset**
   - source change → semantic diff → impact ground truth

4. **World Sync Benchmark**
   - 현실 변화가 agent-ready state로 반영되는 정확도/시간/비용

Foundation model 자체보다 이 데이터/알고리즘이 장기 moat가 될 수 있다.

---

# 69. 구현 중 절대 하지 않을 것

- 자체 OCR foundation model
- 자체 vector DB
- 자체 graph DB
- 자체 LLM
- Kafka/Kubernetes 조기 도입
- 모든 parser를 모든 page에 실행
- 한 confidence 숫자로 전체 품질 판정
- LLM이 source 없는 사실 생성
- 불확실한 entity 자동 merge
- latest timestamp만으로 authority 결정
- unknown 날짜 fabricate
- compile 중간 상태를 agent에 publish
- benchmark 통과 전 public superiority claim
- 경쟁사 self-reported score를 reproduced result처럼 표기
- 50 connector 선행 구현
- autonomous write-action 선행 구현

---

# 70. 연구/리서치 Reference — 2026-08-10 기준

구현 시작 시 다시 최신 확인하고 lockfile/image digest를 pin한다.

## Document parsing / routing / failure
- MinerU repository and releases
  https://github.com/opendatalab/MinerU
- PaddleOCR / PaddleOCR-VL docs
  https://github.com/PaddlePaddle/PaddleOCR
- Mistral OCR 4
  https://mistral.ai/news/ocr-4/
- Reducto Parse
  https://docs.reducto.ai/parse/overview
- Unstructured partition strategies
  https://docs.unstructured.io/open-source/concepts/partitioning-strategies
- Consensus Entropy
  https://arxiv.org/abs/2504.11101
- DocOCR-Eval
  https://arxiv.org/abs/2607.16203
- Multi-Expert Routing for Multi-Domain Low-Resource OCR
  https://arxiv.org/abs/2607.14041
- MPDocBench-Parse
  https://arxiv.org/abs/2605.22100
- Dr. DocBench
  https://arxiv.org/abs/2606.01393
- PureDocBench
  https://arxiv.org/abs/2605.07492
- HPD-Parsing
  https://arxiv.org/abs/2607.18839
- Training-Free Acceleration for Document Parsing VLMs
  https://arxiv.org/abs/2602.12957

## Infrastructure
- RunPod Serverless overview/settings/storage
  https://docs.runpod.io/serverless/overview
  https://docs.runpod.io/serverless/endpoints/endpoint-configurations
  https://docs.runpod.io/serverless/storage/overview
- Cloudflare R2 upload / presigned / events / lifecycle
  https://developers.cloudflare.com/r2/objects/upload-objects/
  https://developers.cloudflare.com/r2/api/s3/presigned-urls/
  https://developers.cloudflare.com/r2/buckets/event-notifications/
  https://developers.cloudflare.com/r2/buckets/object-lifecycles/
- pgvector
  https://github.com/pgvector/pgvector
- PostgreSQL current documentation
  https://www.postgresql.org/docs/current/

## Security / observability / MCP
- OWASP File Upload Cheat Sheet
  https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html
- OpenTelemetry
  https://opentelemetry.io/docs/
- MCP 2026-07-28 specification
  https://modelcontextprotocol.io/specification/2026-07-28

## Claude Code
- Overview
  https://docs.anthropic.com/en/docs/claude-code/overview
- Subagents
  https://docs.anthropic.com/en/docs/claude-code/sub-agents
- Hooks
  https://docs.anthropic.com/en/docs/claude-code/hooks
- GitHub Actions
  https://docs.anthropic.com/en/docs/claude-code/github-actions

---

# 71. 기존 v2.0 Autonomous Command — 실행 금지 / 역사적 참조만 유지

기존 v2.0 command의 실행문은 최종 Source of Truth에서 제거했다. 서로 다른 실행 명령이 한 파일 안에 공존하면 Claude Code가 과거 phase 순서나 v2 계약을 현재 규범으로 오인할 수 있기 때문이다.

- 이 섹션은 v2.0에 autonomous phased implementation 철학이 존재했다는 역사만 보존한다.
- 실제 실행 명령은 문서 최하단의 `N48. FINAL AUTONOMOUS CLAUDE CODE COMMAND — v3.1` 하나뿐이다.
- 과거 command가 필요하면 별도 v2.0 원본 artifact를 조회한다.

---

# 72. 최종 Done Definition

TAVONEL v2.0은 다음 질문에 실제 시스템과 evidence로 답할 수 있을 때 성공에 가까워진다.

1. 파일 뭉텅이를 넣으면 어떤 page가 왜 어떤 parser로 갔는가?
2. parser가 틀렸을 가능성을 어떻게 감지했는가?
3. 어떤 failure가 발생했고 왜 그 recovery를 선택했는가?
4. cross-page 의미는 보존됐는가?
5. 이 claim은 원본 어디에서 왔는가?
6. 이것과 저것은 같은 entity라는 근거는 무엇인가?
7. 서로 충돌하는 source 중 어느 것이 이 상황에 적용되는가?
8. 이 사실은 언제 유효했고 시스템은 언제 알았는가?
9. source 하나가 바뀌면 어떤 knowledge와 agent가 stale인가?
10. 전체를 다시 하지 않고 필요한 것만 rebuild했는가?
11. 부분 rebuild 결과가 full rebuild와 같은가?
12. 현재 agent가 보는 world state는 몇 시점의 상태인가?
13. 고객 A의 지식이 고객 B에게 절대 새지 않는가?
14. 평균이 아니라 p95/p99에서도 쓸 만한 속도인가?
15. 실패할 때 조용히 틀린 결과를 내지 않고 복구하거나 명시적으로 막는가?
16. 모든 외부 claim에 receipt가 있는가?

이 16개 중 하나라도 “모른다”면 그 부분은 아직 production-grade가 아니다.

---


# 73. Core Database Schema Blueprint

실제 ORM 이름은 repository 상황에 맞추되 **semantic contract는 변경하지 않는다.**

## 73.1 sources

```sql
sources(
  id text primary key,
  tenant_id text not null,
  workspace_id text not null,
  connector_type text not null,
  connector_native_id text,
  canonical_path text,
  created_at timestamptz not null,
  deleted_at timestamptz
)
```

Unique:
`(tenant_id, workspace_id, connector_type, connector_native_id)` where native id exists.

## 73.2 document_versions

```sql
document_versions(
  id text primary key,
  tenant_id text not null,
  workspace_id text not null,
  source_id text not null,
  content_sha256 text not null,
  r2_object_key text not null,
  media_type text not null,
  size_bytes bigint not null,
  page_count int,
  status text not null,
  recorded_at timestamptz not null,
  metadata jsonb not null default '{}'
)
```

Unique:
`(source_id, content_sha256)`.

## 73.3 page_profiles / route_decisions

```sql
page_profiles(
  document_version_id text not null,
  page_index int not null,
  profile_version text not null,
  features jsonb not null,
  created_at timestamptz not null,
  primary key(document_version_id, page_index, profile_version)
)

route_decisions(
  id text primary key,
  tenant_id text not null,
  document_version_id text not null,
  page_start int not null,
  page_end int not null,
  route_class text not null,
  parser_id text not null,
  decision_version text not null,
  confidence double precision,
  reasons jsonb not null,
  fallback_chain jsonb not null,
  created_at timestamptz not null
)
```

## 73.4 parser_runs

```sql
parser_runs(
  id text primary key,
  tenant_id text not null,
  document_version_id text not null,
  route_decision_id text,
  parser_id text not null,
  parser_version text not null,
  config_hash text not null,
  status text not null,
  attempt int not null,
  queue_ms bigint,
  cold_start_ms bigint,
  inference_ms bigint,
  gpu_seconds double precision,
  raw_artifact_key text,
  output_sha256 text,
  error_signature text,
  created_at timestamptz not null,
  finished_at timestamptz
)
```

## 73.5 failure_events / recovery_attempts

```sql
failure_events(
  id text primary key,
  tenant_id text not null,
  document_version_id text not null,
  page_index int,
  parser_run_id text,
  failure_code text not null,
  severity text not null,
  confidence double precision,
  evidence jsonb not null,
  created_at timestamptz not null
)

recovery_attempts(
  id text primary key,
  tenant_id text not null,
  failure_event_id text not null,
  escalation_level int not null,
  recovery_action text not null,
  parser_run_id text,
  cost_estimate numeric,
  result text not null,
  created_at timestamptz not null,
  finished_at timestamptz
)
```

## 73.6 evidence / knowledge units

```sql
evidence(
  id text primary key,
  tenant_id text not null,
  workspace_id text not null,
  document_version_id text not null,
  page_index int,
  bbox jsonb,
  span_start int,
  span_end int,
  source_hash text not null,
  artifact_key text,
  created_at timestamptz not null
)

knowledge_units(
  version_id text primary key,
  logical_id text not null,
  tenant_id text not null,
  workspace_id text not null,
  document_version_id text not null,
  unit_type text not null,
  content jsonb not null,
  structure jsonb not null,
  extraction jsonb not null,
  quality jsonb not null,
  temporal jsonb not null,
  epistemic jsonb not null,
  governance jsonb not null,
  compiler_version text not null,
  created_at timestamptz not null
)
```

Index:
- `(tenant_id, workspace_id, logical_id)`
- `(document_version_id)`
- time fields extracted to typed columns if query frequency warrants.

## 73.7 entities / mentions / relationships

```sql
entities(
  id text primary key,
  tenant_id text not null,
  workspace_id text not null,
  entity_type text not null,
  canonical_name text,
  external_ids jsonb not null,
  status text not null,
  created_at timestamptz not null
)

entity_mentions(
  id text primary key,
  entity_id text,
  knowledge_unit_version_id text not null,
  mention_text text not null,
  evidence_id text not null,
  resolution_state text not null,
  score double precision
)

relationships(
  id text primary key,
  tenant_id text not null,
  workspace_id text not null,
  subject_entity_id text not null,
  predicate text not null,
  object_entity_id text,
  object_value jsonb,
  valid_from timestamptz,
  valid_to timestamptz,
  recorded_at timestamptz not null,
  epistemic_status text not null,
  authority text not null,
  evidence_ids jsonb not null
)
```

## 73.8 claims

```sql
claims(
  id text primary key,
  tenant_id text not null,
  workspace_id text not null,
  logical_key text,
  subject jsonb not null,
  predicate text not null,
  value jsonb not null,
  scope jsonb not null,
  applicability jsonb not null,
  authority text not null,
  valid_from timestamptz,
  valid_to timestamptz,
  temporal_source text not null,
  epistemic_status text not null,
  confidence double precision,
  status text not null,
  evidence_ids jsonb not null,
  recorded_at timestamptz not null,
  superseded_at timestamptz
)
```

## 73.9 dependency_edges

```sql
dependency_edges(
  id bigserial primary key,
  tenant_id text not null,
  workspace_id text not null,
  from_id text not null,
  to_id text not null,
  edge_type text not null,
  propagation_policy text not null,
  valid_from timestamptz,
  valid_to timestamptz,
  created_at timestamptz not null
)
```

Indexes:
- `(tenant_id, workspace_id, from_id)`
- `(tenant_id, workspace_id, to_id)`
- `(edge_type)`

## 73.10 world_states

```sql
world_states(
  id text primary key,
  tenant_id text not null,
  workspace_id text not null,
  status text not null,
  compiler_version text not null,
  parent_world_state_id text,
  change_set_id text,
  built_at timestamptz not null,
  activated_at timestamptz,
  validation_receipt_id text
)
```

`ACTIVE` unique partial index per workspace.

## 73.11 jobs

```sql
jobs(
  id text primary key,
  job_key text not null unique,
  tenant_id text not null,
  workspace_id text not null,
  job_type text not null,
  payload jsonb not null,
  status text not null,
  priority int not null default 0,
  attempts int not null default 0,
  max_attempts int not null,
  lease_owner text,
  lease_until timestamptz,
  available_at timestamptz not null,
  created_at timestamptz not null,
  updated_at timestamptz not null
)
```

Worker claim:
`SELECT ... FOR UPDATE SKIP LOCKED`.

Lease expiration 후 job reclaim 가능.

## 73.12 agent_consumption

앞의 contract 그대로 persisted table.

---

# 74. State Machines — 구현 중 임의 변경 금지

## 74.1 Source

```text
RECEIVED
→ PREFLIGHT
→ ACCEPTED
  ├ BLOCKED
  ├ NEEDS_PASSWORD
  └ VERSION_CREATED
```

## 74.2 Parse Job

```text
PLANNED
→ QUEUED
→ RUNNING
→ ARTIFACT_UPLOADING
→ INSPECTING
  ├ DELIVERED
  ├ SUSPICIOUS
  └ FAILED
```

## 74.3 Recovery

```text
NONE
→ PLANNED
→ RUNNING
→ RECOVERED
  ├ REVIEW_REQUIRED
  └ FAILED_EXPLICIT
```

## 74.4 Compile

```text
STAGED
→ COMPILING
→ VALIDATING
  ├ VERIFIED
  ├ WARNINGS
  └ BLOCKED
```

## 74.5 World State

```text
BUILDING
→ VALIDATING
  ├ ACTIVE
  └ REJECTED

ACTIVE
→ SUPERSEDED
```

상태 transition은 DB transaction과 audit log 안에서 수행.

---

# 75. API Contract Blueprint

prefix:
`/v1`

## Sources

```text
POST   /uploads/presign
POST   /sources/complete
GET    /sources/{source_id}
GET    /sources/{source_id}/versions
POST   /sources/{source_id}/sync
```

## Jobs

```text
GET /jobs/{job_id}
GET /jobs/{job_id}/events
POST /jobs/{job_id}/cancel
```

## Knowledge

```text
POST /knowledge/search
GET  /knowledge/{logical_id}
GET  /knowledge/{logical_id}/history
GET  /knowledge/{logical_id}/evidence
```

Search request:

```json
{
  "workspace_id":"w_...",
  "query":"...",
  "as_of":"2026-08-10T12:00:00+09:00",
  "known_at":null,
  "world_state_id":null,
  "filters":{},
  "limit":20
}
```

## Evidence

```text
GET /evidence/{id}
GET /evidence/{id}/preview
```

## Change / Impact

```text
GET  /changes
GET  /changes/{id}
GET  /changes/{id}/impact
POST /changes/{id}/recompile
```

## Timeline

```text
GET /entities/{id}/history
GET /world-states
GET /world-states/{id}
```

## Review

```text
GET  /reviews
POST /reviews/{id}/decision
```

## Health Scan

```text
POST /health-scans
GET  /health-scans/{id}
GET  /health-scans/{id}/report
POST /health-scans/{id}/convert-to-workspace
```

모든 endpoint:
- tenant auth
- workspace authorization
- request ID
- audit where sensitive
- rate limit as appropriate

---

# 76. Receipt / Evidence Artifact Contract

모든 benchmark/claim은 machine-readable receipt를 생성한다.

```json
{
  "receipt_id":"rcpt_...",
  "study":"router-benchmark-v1",
  "created_at":"...",
  "git_commit":"...",
  "container_digests":{},
  "dataset":{
    "name":"...",
    "revision":"...",
    "manifest_sha256":"..."
  },
  "systems":[
    {
      "name":"tavonel-adaptive",
      "parser_versions":[],
      "config_hash":"..."
    }
  ],
  "metrics":{},
  "failures":{},
  "limitations":[],
  "artifacts":[
    {"path":"...","sha256":"..."}
  ],
  "claim_status":"INTERNAL_ONLY"
}
```

Claim status:

```text
INTERNAL_ONLY
WITHHELD
CONDITIONAL
APPROVED
DEPRECATED
```

Website는 `APPROVED`만 자동 노출 가능하도록 구성 가능.

---

# 77. Acceptance Matrix — Claude가 스스로 Done이라 말하지 못하게 하는 기준

| Subsystem | 필수 자동검증 |
|---|---|
| Preflight | corrupt/encrypted/zip-bomb/path traversal fixtures |
| Profiler | deterministic feature snapshot |
| Router | route reproducibility + oracle regret benchmark |
| Parser adapter | normalized schema contract |
| Inspector | failure-type precision/recall |
| Recovery | failure→action mapping + budget/circuit breaker |
| Reconciler | cross-page precision/recall + false merge |
| IR | JSON/Pydantic schema + round trip |
| Stable ID | mutation property tests |
| Entity | false merge adversarial fixtures |
| Authority | exception/scope/precedence cases |
| Temporal | bitemporal reconstruction |
| Diff | controlled mutation precision/recall |
| Dependency | typed propagation + cycle limits |
| Impact | exact ground-truth affected set |
| Recompile | full/selective equivalence |
| World State | no partial ACTIVE state |
| RAG | permission/time/authority filtered retrieval |
| MCP | auth/input validation/rate limit/read-only |
| RLS | cross-tenant negative tests |
| Jobs | duplicate/idempotent/reclaim/lease tests |
| RunPod | lost worker/TTL/OOM/retry simulation |
| R2 | multipart/hash/immutable version tests |
| Cost | budget kill-switch |
| Observability | required spans/metrics emitted |
| Health Scan | every finding links to evidence |
| Claims | every number links to receipt |
| Website | real capability only + screenshot QA |

---

# 78. Recommended Initial Test File Layout

```text
tests/
  preflight/
  profiler/
  router/
  parser_contract/
  inspector/
  recovery/
  reconciler/
  ir/
  identity/
  entity/
  authority/
  temporal/
  diff/
  dependency/
  impact/
  recompilation/
  world_state/
  retrieval/
  permissions/
  jobs/
  chaos/
  claims/

benchmarks/
  manifests/
  evaluators/
  receipts/
  reports/
```

대표 test names:

```text
test_blank_source_is_not_parser_failure
test_hard_table_never_routes_to_native_fast_path
test_low_confidence_route_has_safe_fallback
test_duplicate_job_key_is_idempotent
test_worker_loss_preserves_source_and_retries
test_cross_page_table_merges_without_losing_cell_provenance
test_uncertain_entity_does_not_auto_merge
test_customer_contract_overrides_global_policy_only_in_scope
test_unknown_effective_date_is_not_fabricated
test_may_to_must_is_operational_change
test_reference_edge_does_not_always_invalidate
test_dependency_cycle_is_bounded
test_selective_compile_equals_full_rebuild_subset
test_world_state_is_atomic
test_cross_tenant_search_returns_nothing
test_health_scan_finding_opens_source_evidence
```

---

# 79. Production Rollback Rules

각 phase는 rollback 가능한 migration/checkpoint를 가져야 한다.

- DB migration backward plan
- feature flag for new router
- parser champion rollback
- recovery policy version pin
- world_state rollback to previous ACTIVE
- website claims versioned separately

새 router/model 문제가 생기면:
`CHAMPION` pointer만 기존으로 되돌릴 수 있어야 한다.

---

# 80. 최종 Implementation Philosophy

TAVONEL v2에서 “완벽하게 구현”의 뜻은 버그가 0이라는 허위 약속이 아니다.

정확한 뜻은:

> **우리가 예상할 수 있는 실패를 명시적으로 모델링하고,
> 실패를 자동으로 감지하고, 가능한 경우 가장 적절한 경로로 복구하며,
> 복구할 수 없으면 조용히 틀린 결과를 publish하지 않고,
> 모든 판단과 결과를 evidence로 재검증할 수 있는 시스템을 만든다.**

이 원칙이 기존 Recovery Runtime에서 출발해:

```text
Document Recovery
→ Knowledge Recovery
→ Reality Synchronization
```

으로 확장되는 것이 TAVONEL의 기술적 계보다.

---

# END OF INHERITED v2.0 TECHNICAL CANON

---

# PART B — v3.0 NORMATIVE IMPLEMENTATION METHODBOOK

# N0. 최종 구현 결정표 — 선택지를 남기지 않는 기본값

아래는 greenfield 또는 현재 repository에 동등한 안정 구현이 없을 때 적용할 기본값이다. 현재 repository의 구현이 이미 검증되었으면 무조건 갈아엎지 않고 adapter boundary만 맞춘다.

| 영역 | 최종 기본값 | 교체 조건 |
|---|---|---|
| Web/control plane | Next.js + TypeScript strict | 기존 stack이 동일 acceptance를 통과할 때 유지 |
| Compiler/API | Python 3.12 계열 + FastAPI + Pydantic v2 + SQLAlchemy 2 + Alembic | ML 의존성 호환성 검증 후 major upgrade |
| Python tooling | `uv`, Ruff, mypy, pytest, Hypothesis | 기존 lock/tooling이 더 안정적이면 유지 |
| JS tooling | pnpm, ESLint, TypeScript, Vitest, Playwright | 기존 lockfile과 CI가 green이면 유지 |
| Metadata/transaction DB | Managed PostgreSQL, pgvector >= 0.8 | graph traversal가 실제 병목으로 측정될 때만 별도 graph DB |
| Object source of truth | Cloudflare R2 | enterprise BYOC 요구가 실제 매출로 검증될 때 adapter 추가 |
| Durable event transport | PostgreSQL transactional outbox + Cloudflare Queues | throughput/region 요구가 측정 한계를 넘을 때 교체 |
| GPU execution | RunPod Serverless endpoint pool | 특정 고객의 private/BYOC 요구 시 별도 adapter |
| PDF render/preflight | `pypdfium2` + `pypdf`/`pdfplumber` 계열 | license/quality review 후 대체 |
| OCR/parser champion | 현재 evidence가 있는 MinerU 3.4.4 image digest pin | challenger가 no-regression gate를 통과할 때 promote |
| OCR/parser challenger | PaddleOCR-VL-1.6 계열, 정확한 code/model license pin | benchmark/라이선스 승인 후 |
| Paid parser | competitive/shadow 또는 explicit paid fallback only | unit economics와 고객 요구 검증 후 |
| Embedding | adapter + pinned model/version | retrieval benchmark 승격 시 |
| Auth | 기존 provider 유지; greenfield는 managed OIDC provider behind adapter | enterprise SSO 수요 시 provider 확장 |
| Billing | Stripe adapter | 지역 결제 요구 시 추가 |
| Product analytics | PostHog 계열 adapter | 데이터 residency 요구 시 self-host/교체 |
| Error monitoring | Sentry 계열 + OpenTelemetry | vendor 교체 가능, telemetry contract는 고정 |
| Telemetry | OpenTelemetry SDK + Collector gateway | 교체 금지, exporter만 교체 |
| Container registry | GHCR 또는 동등 OCI registry | enterprise registry adapter |
| Supply-chain proof | SBOM + GitHub artifact attestation + Cosign verification | 동급 이상의 attestation 체계 |

## N0.1 라이선스 관련 최종 결정

- `PyMuPDF/MuPDF`는 AGPL 또는 상용 라이선스 조건을 가진다. **법률 검토와 상용 라이선스 승인 없이 proprietary SaaS 기본 의존성으로 채택하지 않는다.**
- `pypdfium2`는 자체 코드가 permissive license 계열이지만 PDFium third-party notices까지 SBOM에 포함한다.
- PaddleOCR code가 Apache-2.0이어도 transitive dependency와 model weight license를 별도로 검사한다.
- MinerU는 release/모델/하위 구성에 따라 license 맥락이 달라질 수 있으므로 `parser_registry.license_state=APPROVED`가 아니면 production route에 들어갈 수 없다.
- **코드 라이선스와 모델 weight 라이선스는 별도 필드로 관리한다.**

```yaml
license_record:
  component_id: mineru_3_4_4_vlm
  source_repo: ...
  source_commit: ...
  package_lock_hash: ...
  code_license_spdx: ...
  model_id: ...
  model_revision: ...
  model_license_spdx_or_custom: ...
  transitive_risk: []
  reviewed_at: ...
  reviewer: ...
  status: PENDING | APPROVED | RESTRICTED | BLOCKED
  notes: ...
```

`PENDING`, `RESTRICTED`, `BLOCKED` component는 production manifest 생성 단계에서 fail closed 한다.

---

# N1. 절대 불변 Architecture Invariants

1. **R2 object는 content-addressed immutable artifact다.** 같은 key overwrite를 일반 데이터 흐름에 사용하지 않는다.
2. **PostgreSQL은 workflow truth와 publish pointer의 source of truth다.** Queue는 전달 수단이지 진실 저장소가 아니다.
3. **Queue는 at-least-once다.** exactly-once를 마케팅·설계 문서에서 주장하지 않는다.
4. **모든 consumer는 idempotent다.** event duplicate·reorder·late arrival을 정상 입력으로 취급한다.
5. **parser output이 존재한다고 성공이 아니다.** `DELIVERED → INSPECTED → RECONCILED → VALIDATED → PUBLISHED`를 분리한다.
6. **document text는 untrusted data다.** 문서 속 명령을 system/tool instruction으로 해석하지 않는다.
7. **LLM은 proposal engine이다.** permission, identity, temporal truth, authority, state publish 같은 핵심 제어를 LLM 단독 판단에 맡기지 않는다.
8. **모든 claim은 evidence로 돌아갈 수 있어야 한다.** evidence 없는 claim은 production world state에 publish할 수 없다.
9. **unknown은 unknown으로 보존한다.** 임의 날짜·좌표·권위·관계를 생성하지 않는다.
10. **false merge는 false split보다 비싸다.** identity/entity 자동 병합은 보수적으로 한다.
11. **권한 필터는 retrieval 후가 아니라 retrieval 전 또는 동일 transaction의 강제 조건이다.**
12. **selective recompile 결과는 full rebuild의 관련 결과와 같아야 한다.** 불일치 시 publish block + full rebuild fallback.
13. **새 world state는 원자적으로 publish한다.** 부분 성공 state를 agent가 보지 못하게 한다.
14. **모델·prompt·schema·container는 versioned input이다.** 동일 output을 기대할 때 digest까지 재현한다.
15. **마케팅 claim은 receipt에 의해 생성된다.** 사람이 숫자를 수동 복사해 랜딩에 넣지 않는다.

---

# N2. End-to-End Trust Boundary

```text
BROWSER / CONNECTOR
  [untrusted bytes]
        │
        ▼
UPLOAD GATE
  checksum · quota · MIME · malware/CDR policy
        │
        ▼
QUARANTINE R2 PREFIX
        │
        ▼
PREFLIGHT SANDBOX
  no credentials · no outbound network · resource limits
        │
        ▼
RENDER / PARSE WORKERS
  untrusted content, tool-less model inference
        │
        ▼
NORMALIZED ARTIFACTS
  schema validation · checksum · prompt-injection labels
        │
        ▼
KNOWLEDGE COMPILER
  deterministic control + bounded LLM proposals
        │
        ▼
STAGING WORLD STATE
  permission · evidence · integrity validation
        │
        ▼
ATOMIC PUBLISH POINTER
        │
        ▼
RAG / API / MCP / AGENTS
  permission-scoped, read-only first, audited
```

## N2.1 Worker sandbox minimum

- rootless container 또는 동급 isolation
- read-only root filesystem
- writable ephemeral working directory만 제공
- Linux capabilities drop
- seccomp/AppArmor 적용 가능하면 활성화
- outbound network default deny; model artifact/R2 access만 allowlist
- cloud master secret 금지; short-lived scoped credential만 주입
- CPU, RAM, GPU, file descriptor, process, wall-clock limit
- decompression/render pixel budget
- source filename을 shell command에 직접 사용 금지
- Office macro/VBA/JavaScript 실행 금지

## N2.2 Prompt injection trust label

모든 source/evidence에 다음을 붙인다.

```yaml
content_security:
  trust_origin: USER_UPLOAD | CONNECTOR | INTERNAL_APPROVED | PUBLIC_WEB
  active_content_present: false
  indirect_prompt_injection:
    status: NOT_SCANNED | NONE_DETECTED | SUSPECTED | CONFIRMED
    indicators: []
  agent_instruction_eligible: false
```

`agent_instruction_eligible`는 일반 문서에서 항상 `false`다. 별도의 승인된 policy DSL만 실행 규칙으로 승격할 수 있다.

---

# N3. Source Preflight — 파일형식별 실제 방법

## N3.1 공통 처리 순서

```python
async def preflight(upload: UploadRef) -> PreflightResult:
    assert upload.object_key.startswith(f"quarantine/{upload.tenant_id}/")
    sha256 = stream_sha256(upload)
    detected_mime = libmagic_detect(upload)
    enforce_quota(upload.tenant_id, upload.size_bytes)
    enforce_extension_mime_policy(upload.original_name, detected_mime)
    malware_result = await malware_scan_if_configured(upload)
    resource_profile = inspect_container_format(upload, detected_mime)
    enforce_resource_limits(resource_profile)
    return build_manifest(...)
```

## N3.2 PDF

필수 검사:

- header/trailer/xref/EOF 구조 검사
- encrypted/password 필요 여부
- page count
- embedded file/JavaScript/action/form/XFA 존재 여부
- 각 page MediaBox/CropBox와 비정상 dimensions
- object count, stream compression ratio
- native text 존재량
- font encoding anomaly

기본 renderer는 `pypdfium2`로 pin한다. parser가 자체 renderer를 사용하더라도 **TAVONEL reference render**를 별도 생성하여 visual correspondence 검사에 사용한다.

## N3.3 DOCX/PPTX/XLSX

Office Open XML은 ZIP container로 취급한다.

- canonical path normalization 후 `../`, absolute path, duplicate conflicting member 차단
- member count, total expanded bytes, compression ratio 제한
- `[Content_Types].xml`과 관계 파일 검증
- external relationship URL 기록 및 fetch 금지
- macro-enabled format은 macro를 실행하지 않고 존재 사실만 표시
- XLSX formula는 계산하지 않는다. cached value와 formula를 함께 보존하고 `calculation_state`를 명시한다.
- PPTX reading order는 shape tree 순서만 믿지 않고 geometry와 placeholder relation을 함께 기록한다.

## N3.4 Images

- EXIF orientation normalize는 derived render로 생성하며 원본 보존
- image decompression bomb 방지
- width × height 상한
- alpha/CMYK/profile 변환 기록
- animated image는 frame count 제한 및 첫 frame-only 정책을 명시

## N3.5 Archive bundle

초기 launch에서 허용: ZIP. 그 외 archive는 명시적으로 disable.

부트스트랩 hard defaults:

```yaml
limits:
  max_upload_bytes_per_file: 2147483648       # 2 GiB, plan별 더 낮게 제한 가능
  max_pages_per_document: 5000
  max_archive_members: 10000
  max_expanded_bytes: 10737418240             # 10 GiB
  max_compression_ratio: 100
  max_render_pixels_per_page: 80000000
  max_embedded_file_depth: 1
```

이 값은 **보안 hard ceiling**이며 성능/가격 plan quota와 구분한다. 변경 시 security benchmark와 cost model을 다시 통과해야 한다.

---

# N4. Profiler Feature Contract — 계산 가능한 정의

각 feature는 `name`, `version`, `range`, `missing_reason`, `calibration_set`을 가진다. feature 계산 코드가 바뀌면 router model version도 바뀐다.

## N4.1 Sampling policy

문서 전체를 cheap profile하는 것이 기본이지만, 매우 긴 문서는 다음 sample로 초기 route plan을 만든다.

- 첫 3페이지
- 마지막 2페이지
- 균등 간격 최대 15페이지
- native text/image ratio가 급변하는 page
- file metadata가 가리키는 TOC/table page

실제 parsing 중 anomaly가 나오면 profile을 갱신한다. 최초 profile은 immutable history로 보존한다.

## N4.2 주요 feature

```yaml
page_profile:
  page_index: 16
  native_char_count: 1240
  native_text_area_ratio: 0.32
  native_text_coverage_estimate: 0.94
  native_render_alignment: 0.92
  image_area_ratio: 0.18
  blur_risk: 0.08
  skew_degrees: 0.3
  contrast_risk: 0.04
  compression_artifact_risk: 0.11
  photo_capture_probability: 0.02
  column_count_estimate: 2
  table_probability: 0.74
  table_area_ratio: 0.28
  merged_cell_probability: 0.42
  formula_probability: 0.06
  handwriting_probability: 0.01
  cross_page_continuation_probability: 0.37
  language_distribution: {ko: 0.7, en: 0.3}
  profile_confidence: 0.91
  feature_version: profiler_v1
```

## N4.3 계산 예

- `blur_risk`: 150 DPI grayscale reference render의 normalized Laplacian variance를 calibration distribution에 매핑한 0–1 risk.
- `skew_degrees`: dominant text-line angle의 robust median.
- `contrast_risk`: foreground/background separability의 inverse normalized score.
- `native_text_coverage_estimate`: native glyph bbox area와 cheap text-region detector area의 coverage ratio. detector가 unavailable이면 `missing_reason`을 남긴다.
- `native_render_alignment`: native text bbox와 rendered glyph/text-region의 spatial overlap 및 sample OCR string agreement를 결합.
- `table_probability`: line/grid cues + repeated aligned text cells + cheap layout model output.
- `cross_page_continuation_probability`: page-bottom incomplete block, next-page top alignment, repeated header/schema, list/section numbering을 결합.

## N4.4 Feature missing policy

missing 값을 0으로 채우지 않는다.

```yaml
feature_value:
  value: null
  missing_reason: MODEL_UNAVAILABLE | NOT_APPLICABLE | RESOURCE_LIMIT | ERROR
```

Router는 missing indicator를 별도 입력으로 사용하며, critical feature가 missing이면 route confidence를 낮춰 `R9_UNKNOWN` 또는 stronger path로 보낸다.

---

# N5. Deterministic Router v1 — 부트스트랩 알고리즘

## N5.1 부트스트랩 threshold

아래는 production claim이 아니라 초기 calibration 전 안전 기본값이다. `router_bootstrap_v1.yaml`에 보관하고 코드에 hard-code하지 않는다.

```yaml
native_fast_path:
  min_native_char_count: 80
  min_native_text_coverage: 0.85
  min_native_render_alignment: 0.90
  max_visual_risk: 0.25
  max_image_area_ratio: 0.35
  max_table_probability: 0.20
  max_formula_probability: 0.10

route_risk:
  degraded_if_blur_risk_gte: 0.60
  degraded_if_contrast_risk_gte: 0.60
  degraded_if_abs_skew_degrees_gte: 3.0
  degraded_if_photo_probability_gte: 0.50
  table_if_probability_gte: 0.55
  table_if_area_ratio_gte: 0.20
  table_if_merged_cell_probability_gte: 0.35
  formula_if_probability_gte: 0.45
  cross_page_if_probability_gte: 0.55
  unknown_if_profile_confidence_lt: 0.65
```

각 threshold는 route class별 ground-truth set에서 calibration한다. universal threshold라고 외부에 주장하지 않는다.

## N5.2 Quality mode

확률은 official accuracy가 아니라 **TAVONEL validation pass probability의 calibrated estimate**다.

```yaml
quality_modes:
  FAST:
    min_pass_probability_lcb: 0.80
    max_recovery_level: 3
    max_attempts: 2
    max_cost_multiplier: 2.0
    human_review: false
  BALANCED:
    min_pass_probability_lcb: 0.90
    max_recovery_level: 6
    max_attempts: 4
    max_cost_multiplier: 5.0
    human_review: optional
  VERIFIED:
    min_pass_probability_lcb: 0.97
    max_recovery_level: 7
    max_attempts: 6
    max_cost_multiplier: 12.0
    human_review: true_for_unresolved_high_risk
```

## N5.3 Parser choice

각 parser `p`에 대해 route class `r`의 lower confidence bound를 사용한다.

```text
utility(p) =
    quality_lcb(p,r)
  - alpha(mode) * normalized_cost(p,r)
  - beta(mode)  * normalized_latency_p95(p,r)
  - gamma(mode) * catastrophic_failure_risk(p,r)
```

선택 절차:

1. license/status/format/language capability로 parser 후보 필터.
2. mode의 `min_pass_probability_lcb`를 만족하는 parser만 남김.
3. 남은 parser 중 utility 최대 선택.
4. 하나도 만족하지 않으면 가장 높은 quality LCB를 고르고 `route_status=DEGRADED_CONFIDENCE`로 표시.
5. high-risk domain에서 VERIFIED이고 threshold 미달이면 자동 publish를 금지하고 review 경로를 준비.

```python
def choose_parser(profile, mode, registry):
    route = classify_route(profile)
    candidates = [p for p in registry if p.production_eligible(profile, route)]
    scored = []
    for p in candidates:
        pred = p.predict(route, profile)
        scored.append((p, pred, utility(pred, mode)))
    qualified = [x for x in scored if x[1].quality_lcb >= mode.min_lcb]
    if qualified:
        return max(qualified, key=lambda x: x[2])
    best = max(scored, key=lambda x: x[1].quality_lcb)
    return best.with_status("DEGRADED_CONFIDENCE")
```

## N5.4 Sticky routing

contiguous pages가 동일 layout template를 공유하면 parser를 불필요하게 교체하지 않는다. 단, page-level anomaly는 sticky constraint를 깨고 stronger route로 승격시킨다.

## N5.5 Router abstention

다음은 반드시 abstain/stronger route:

- critical features missing
- model registry confidence interval 너무 넓음
- novel document type OOD signal
- parser license/status 불명
- expected cost가 user budget을 넘지만 품질 하한도 만족하지 못함
- security/quarantine unresolved

---

# N6. Learned Router — 안전한 학습 방법

## N6.1 데이터 누수 금지

동일 source family/document version의 page가 train과 test에 나뉘지 않도록 group split한다. 고객 tenant별 distribution leakage를 확인한다.

## N6.2 1차 모델

parser별 별도 binary/ordinal predictor를 사용한다.

- `P(inspector_pass)`
- `P(document_reconcile_pass)`
- `P(recovery_needed)`
- structural/table/formula fidelity expectation
- latency p50/p95 quantile
- GPU seconds/cost

작고 설명 가능한 tree model부터 시작하며 isotonic 또는 Platt calibration으로 probability를 교정한다.

## N6.3 Promotion gate

challenger router는 다음을 모두 만족해야 한다.

- 동일 quality floor에서 routing regret 감소
- catastrophic miss 증가 0
- p95 cost 또는 latency 개선
- route class별 calibration error 허용치 이내
- Korean/English/low-quality/cross-page slice no-regression
- shadow 기간 동안 production output을 바꾸지 않음

## N6.4 Drift

- feature distribution PSI/KS 등 drift signal
- parser version upgrade 후 재교정
- 월별 또는 충분한 outcome 누적 시 offline replay
- online random exploration 금지

---

# N7. Parser Registry & Adapter — production eligible 조건

```yaml
parser_registry_entry:
  parser_id: paddleocr_vl_1_6
  code_repo: ...
  code_commit: ...
  model_id: PaddlePaddle/PaddleOCR-VL-1.6
  model_revision: ...
  container_digest: sha256:...
  config_schema_version: 1
  license_record_id: lic_...
  capabilities:
    formats: [pdf_page_image, png, jpeg]
    languages: [ko, en, ...]
    block_types: [text, title, table, formula, chart, seal]
    bbox: true
    raw_confidence: true
    cross_page_native: false
  benchmark_receipt_ids: []
  status: SHADOW | CHALLENGER | CHAMPION | QUARANTINED | DISABLED
```

production eligible은 다음 모두가 `true`여야 한다.

- license approved
- container signature verified
- SBOM generated
- known vulnerabilities policy 통과
- benchmark receipt exists
- output schema adapter test green
- deterministic config pinned
- secrets/data egress policy approved

## N7.1 Native/fast adapter

- PDF render: `pypdfium2`
- PDF metadata/split: `pypdf`
- structured object inspection: `pdfplumber/pdfminer.six` 계열
- DOCX: `python-docx` + OOXML relation parser
- XLSX: `openpyxl` read-only, formula와 cached value 동시 보존
- PPTX: `python-pptx` + geometry/order normalization
- HTML/XML: secure parser with external entity disabled

## N7.2 Model adapter isolation

parser-specific raw output을 IR로 바로 넣지 않는다.

```text
raw parser output
→ parser-specific schema validation
→ immutable raw artifact
→ normalized ParserResult
→ Inspector
→ Reconciler
→ Canonical IR
```

---

# N8. Failure Taxonomy v3 — Detection·Recovery와 1:1 연결

기존 F0–F28에 다음을 추가한다.

```text
F29_PROMPT_INJECTION_SUSPECTED
F30_DATA_POISONING_OR_POLICY_SMUGGLING
F31_SCHEMA_INCOMPATIBLE
F32_MODEL_OR_CONTAINER_UNVERIFIED
F33_LICENSE_NOT_APPROVED
F34_EVENT_DUPLICATE_OR_OUT_OF_ORDER
F35_WORLD_STATE_PUBLISH_RACE
F36_RLS_OR_TENANT_CONTEXT_MISSING
F37_RETRIEVAL_FILTER_RECALL_FAILURE
F38_DELETE_OR_RETENTION_INCOMPLETE
F39_BACKUP_RESTORE_VALIDATION_FAILED
F40_CONNECTOR_PERMISSION_DRIFT
F41_EMBEDDING_VERSION_MIXED
F42_MODEL_UPGRADE_REGRESSION
F43_HUMAN_REVIEW_STALE_OR_CONFLICTED
F44_EXTERNAL_REFERENCE_UNAVAILABLE
F45_ACTIVE_CONTENT_OR_MALWARE
F46_ARTIFACT_CHECKSUM_MISMATCH
F47_PROVENANCE_SIGNATURE_INVALID
F48_RATE_LIMIT_OR_ABUSE
```

모든 failure event contract:

```yaml
failure_event:
  failure_id: fail_...
  code: F13_TABLE_STRUCTURE
  stage: INSPECTOR
  severity: INFO | LOW | MEDIUM | HIGH | CRITICAL
  confidence: 0.93
  source_scope: page | document | workspace | tenant | provider
  evidence_refs: []
  signature: sha256:...
  recoverable: true
  policy_id: recovery_table_v2
  first_seen_at: ...
  correlated_group_id: ...
```

동일 signature가 반복되는지, 여러 worker에서 동시에 발생하는지로 local failure와 provider-wide failure를 구분한다.

---

# N9. Post-Parse Inspector — 실제 판정 방법

단일 quality score를 금지하고 detector vector를 저장한다.

## N9.1 Hard-fail detectors

다음은 threshold calibration 없이도 launch blocker다.

- nonblank source인데 output empty
- artifact checksum mismatch
- bbox가 page bounds 밖이거나 NaN/inf
- normalized schema invalid
- tenant/workspace mismatch
- required provenance missing
- license/container verification 실패
- permission violation
- recompile equivalence 실패
- prompt-injection content가 tool instruction으로 승격됨

## N9.2 Completeness detector

```text
coverage_ratio = parsed_foreground_area / max(expected_foreground_area, epsilon)
char_ratio = normalized_output_chars / max(reference_native_or_sample_ocr_chars, 1)
```

reference가 없는 경우 `UNKNOWN_REFERENCE`로 두고 visual block coverage를 사용한다. blank page classifier가 blank일 확률이 높을 때만 empty output을 허용한다.

## N9.3 Duplication detector

- repeated line/block hash frequency
- normalized 5-gram/10-gram repetition
- page-to-page duplicate body excluding header/footer
- decoder loop pattern

```text
dup_ratio = duplicated_non_header_chars / total_non_header_chars
```

threshold는 document type별 calibration하며, 법률 문서의 정상 반복 문구를 별도 처리한다.

## N9.4 Garble/language detector

- Unicode replacement/control ratio
- improbable script mixing
- tokenizer unknown/rare sequence
- language distribution vs profiler mismatch
- OCR confusable spike

## N9.5 Reading order detector

block centroids와 expected column order로 sequence graph를 만든 뒤:

- backward jumps
- column interleaving
- heading-before-body constraints
- caption proximity
- order edit distance

를 계산한다.

## N9.6 Table detector

- visual table probability 높지만 table output 없음
- cell bbox overlap/gap anomaly
- row/column span consistency
- header/body schema consistency
- HTML/JSON grid round-trip
- numeric column alignment

## N9.7 Formula detector

- formula region 누락
- LaTeX parse failure
- paired delimiters imbalance
- visual formula region과 output formula count mismatch

정답 검증이 불가능한 경우 VERIFIED로 승격하지 않고 `UNVERIFIED_FORMULA`를 남긴다.

## N9.8 Detector aggregation

```python
if any(signal.hard_fail for signal in signals):
    status = "FAIL"
elif catastrophic_risk(signals) >= catastrophic_threshold:
    status = "FAIL"
elif calibrated_failure_probability(signals) >= suspicious_threshold:
    status = "SUSPICIOUS"
else:
    status = "PASS"
```

`catastrophic_threshold`, `suspicious_threshold`는 route class/document type별 calibration table에 둔다. detector raw values를 삭제하지 않는다.

## N9.9 Benchmark gate

- catastrophic fixture recall = 100%
- overall failure recall target >= 95%
- false escalation rate target <= 15%
- failure type macro-F1를 별도 공개/내부 관리
- customer shadow corpus에서 silent corruption을 최우선으로 샘플링

이 수치는 launch internal target이며 달성 전 외부 claim 금지.

---

# N10. Consensus & Arbitration

## N10.1 실행 조건

secondary parser는 다음에만 실행한다.

- Inspector `SUSPICIOUS`
- VERIFIED mode의 high-risk block
- new parser shadow benchmark
- human review 요청

## N10.2 정규화

parser마다 다른 markdown을 직접 string compare하지 않는다.

```text
raw output
→ block normalization
→ whitespace/unicode normalization
→ block type alignment
→ bbox coordinate normalization
→ table grid normalization
→ formula normalization
→ agreement metrics
```

## N10.3 Agreement vector

```yaml
agreement:
  text_similarity: 0.94
  block_sequence_similarity: 0.89
  bbox_alignment: 0.91
  table_grid_similarity: 0.72
  reading_order_similarity: 0.86
  consensus_entropy: 0.28
```

## N10.4 Arbitration

- high agreement + source-aware checks pass: recovered/accept
- low agreement: third parser 또는 stronger verifier
- three-way conflict: human review/FAIL CLOSED
- majority vote만으로 source truth 확정 금지
- parser self-confidence는 calibration 후 보조 신호로만 사용

---

# N11. Recovery Policy — 품질·비용·시간을 함께 통제

## N11.1 Escalation ladder 의미

| Level | Action | 주 목적 |
|---|---|---|
| L0 | Accept | validated result |
| L1 | safe rerender/preprocess | rotation, DPI, contrast 등 |
| L2 | same parser/config variation | batch, decoding, language hint |
| L3 | alternate parser family | model-specific failure 회피 |
| L4 | conditional ensemble | disagreement 분석 |
| L5 | stronger VLM/verifier | difficult region |
| L6 | document-level joint reconcile | cross-page/hierarchy |
| L7 | human review | business/semantic ambiguity |
| L8 | fail closed | trustworthy output 불가능 |

## N11.2 Recovery selection

```python
def recovery_action(failure, history, mode, budget):
    if failure.code in SECURITY_CODES:
        return Block("SECURITY")
    if repeated_same_signature(history, n=2):
        return EscalateOrStop()
    for policy in policies.for_code(failure.code):
        if policy.level <= mode.max_level and budget.can_afford(policy):
            if not history.already_failed(policy.signature):
                return policy
    return HumanReview() if mode.allows_review else FailClosed()
```

## N11.3 Correlated failure circuit breaker

다음 조건이면 endpoint/provider circuit를 연다.

- 서로 다른 문서·worker에서 같은 모델 init/OOM/provider error가 짧은 시간에 동시 발생
- global stop 패턴
- queue delay가 TTL 예산을 지속적으로 잠식
- R2/API/DB dependency outage

circuit open 동안 새 비용을 쓰지 않고 queued jobs를 `PAUSED_DEPENDENCY`로 둔다.

## N11.4 Partial availability

한 문서의 일부 page가 검증되었어도 document-level 의미가 필요한 export는 `PARTIAL`로 표시한다. 검색 가능한 unit만 노출할 수 있으나, 누락 page와 confidence를 response에 명시한다.

---

# N12. Document Reconciler — 알고리즘 계약

## N12.1 Graph model

각 page block을 node로, candidate continuation을 edge로 만든다.

```text
Block(page_i, local_id)
  ├ NEXT_TEXT
  ├ CONTINUES_LIST
  ├ CONTINUES_TABLE
  ├ CAPTION_OF
  ├ FOOTNOTE_OF
  └ CHILD_OF_HEADING
```

## N12.2 Paragraph continuation score

```text
score =
  0.25 * sentence_boundary_compatibility
+ 0.20 * semantic_continuity
+ 0.15 * font_style_similarity
+ 0.15 * x_alignment
+ 0.10 * line_spacing_similarity
+ 0.10 * language_model_continuation
+ 0.05 * section_context_match
```

LLM continuation score는 tool-less classifier로만 사용하며 original text를 수정하지 않는다.

## N12.3 Table continuation score

```text
score =
  0.25 * normalized_header_similarity
+ 0.20 * column_count_compatibility
+ 0.20 * x_boundary_alignment
+ 0.10 * data_type_pattern_similarity
+ 0.10 * border_style_similarity
+ 0.10 * page_bottom_top_position
+ 0.05 * caption_or_table_id_match
```

- `>=0.90`: auto merge candidate, invariant 검사 후 merge
- `0.70–0.90`: `CONTINUES_TABLE` relation만 생성
- `<0.70`: separate

threshold는 bootstrap이며 benchmark로 교정한다.

## N12.4 Heading hierarchy

- numbering pattern (`1`, `1.1`, `가.`, `A.`)
- font/size/style
- geometric indentation
- TOC alignment
- repeated page header exclusion

을 결합한다. hierarchy cycle 및 level jump anomaly는 Inspector로 돌린다.

## N12.5 Merge invariant

- source cell/block provenance 모두 보존
- merge 후 원문 page span 복원 가능
- merge 전/후 structured payload round-trip
- uncertain physical merge 금지

---

# N13. Canonical Knowledge IR v3 — schema와 진화

## N13.1 Top-level contract

```yaml
knowledge_unit:
  schema_version: tavonel.ir/v3
  logical_id: ku_...
  version_id: kuv_...
  tenant_id: t_...
  workspace_id: w_...
  world_state_candidate_id: wsc_...

  unit_type: paragraph | clause | table | table_row | table_cell |
             figure | caption | list | procedure | policy | claim |
             metadata | code | formula | form_field

  content:
    original_text: ...
    normalized_text: ...
    structured_payload: {}
    content_language: [ko, en]

  structure:
    document_path: [...]
    heading_level: 2
    sequence_index: 142
    parent_logical_id: ...
    continuation_of: ...
    page_span: [17, 18]

  evidence_refs: [ev_...]
  extraction_ref: prun_...
  quality_ref: qres_...
  temporal_ref: tfact_...
  epistemic_ref: epi_...
  governance_ref: gov_...
  security_ref: sec_...
  semantic_refs:
    entities: []
    relationships: []
    claims: []
  lineage_refs:
    derived_from: []
    depends_on: []
    supersedes: []
```

## N13.2 Schema compatibility

- additive optional field: minor
- required field/meaning/type change: major
- every artifact records `schema_version`
- reader supports current major와 바로 이전 major migration path
- migration은 raw source를 재파싱하지 않고 가능한 deterministic transform으로 수행
- lossy migration은 새 version을 만들고 evidence receipt를 남김

## N13.3 JSON Schema

repository path:

```text
packages/schemas/tavonel-ir-v3.schema.json
services/compiler/tavonel_ir/models.py
packages/schemas/generated/tavonel-ir-v3.ts
```

Python schema에서 JSON Schema를 생성하고 TypeScript type을 생성한다. 서로 독립 수기 정의 금지.

---

# N14. Evidence & Provenance — 원문으로 돌아가는 계약

## N14.1 Evidence object

```yaml
evidence:
  evidence_id: ev_...
  document_version_id: dv_...
  source_object_hash: sha256:...
  page_index: 16
  bbox_normalized: [0.1, 0.2, 0.9, 0.3]
  span:
    start: 1042
    end: 1088
  table_cell:
    row: 4
    column: 2
    row_span: 1
    column_span: 1
  render_artifact_id: art_...
  extraction_artifact_id: art_...
  transformation_chain: [tx_...]
  integrity_hash: sha256:...
```

## N14.2 Provenance chain

```text
source object hash
→ render/preprocess artifact hash
→ parser image/config/model digest
→ raw parser artifact
→ normalized ParserResult
→ reconciled block
→ evidence
→ knowledge unit version
→ RAG chunk/graph relation
→ agent consumption
```

모든 edge는 actor, software version, timestamp, reason을 저장한다.

## N14.3 Provenance integrity

- artifact manifest hash
- CI build provenance
- container signature verification result
- public claim artifact sha256
- evidence preview는 원본 hash와 연결

---

# N15. Stable Semantic Identity — matching 방법론

## N15.1 Candidate generation

새 version unit마다 후보를 제한한다.

1. 같은 source lineage
2. 동일/인접 structural path
3. 이전/다음 anchor
4. semantic embedding top-k
5. explicit clause/table/section identifier

전 workspace global all-pairs 비교 금지.

## N15.2 Pair score

```text
score =
  0.25 * source_continuity
+ 0.20 * structural_path_similarity
+ 0.15 * explicit_identifier_match
+ 0.15 * semantic_similarity
+ 0.10 * previous_neighbor_match
+ 0.10 * next_neighbor_match
+ 0.05 * geometry_style_similarity
```

## N15.3 One-to-one assignment

section/window 내부 candidate graph에 Hungarian algorithm 또는 동등한 maximum-weight bipartite matching을 적용하여 하나의 old unit이 여러 new unit으로 임의 매칭되는 것을 막는다.

split/merge는 별도 relation으로 표현한다.

```text
SAME_AS_VERSION
SPLIT_INTO
MERGED_FROM
MOVED_FROM
```

## N15.4 Bootstrap thresholds

- `>=0.92`: auto same logical ID
- `0.75–0.92`: ambiguous, separate version candidate + review
- `<0.75`: new logical ID

route/document type별 calibration 전까지 보수적으로 적용한다.

## N15.5 Invariants

- deterministic rerun stable
- false merge fixture zero
- source reordering에서 logical identity 유지
- minor wording change 유지
- clause replacement는 new version/supersedes

---

# N16. Entity Resolution — evidence-first

## N16.1 Entity mention

```yaml
entity_mention:
  mention_id: em_...
  text: M-012
  normalized: m-012
  type_candidate: machine
  evidence_id: ev_...
  attributes: {plant: B, line: B}
  external_ids: {asset_id: Asset_7782}
```

## N16.2 Resolution hierarchy

1. system-of-record deterministic ID exact match
2. approved alias table
3. exact composite key
4. type + relationship/context overlap
5. name/semantic similarity
6. LLM proposal

LLM은 candidate를 제안할 뿐 merge transaction을 실행하지 않는다.

## N16.3 Merge thresholds

- deterministic key: auto
- high composite evidence: auto only when type and scope compatible
- ambiguous: review
- person/customer/contract 등 high-risk type는 stricter threshold

## N16.4 Undo

entity merge는 reversible operation으로 구현한다. merge decision과 이전 edges를 보존하여 split rollback이 가능해야 한다.

---

# N17. Authority / Applicability Resolution DSL

## N17.1 목적

여러 claim이 동시에 사실일 수 있으므로 `latest wins` 대신 context-specific resolver를 사용한다.

## N17.2 Rule contract

```yaml
resolution_rule:
  rule_id: warranty_contract_override_v1
  subject_type: warranty_policy
  when:
    all:
      - candidate.authority in [CONTRACTUAL]
      - candidate.scope.customer_id == query.customer_id
      - candidate.valid_time contains query.as_of
  precedence: 100
  outcome: PREFER
  evidence_requirement: EXPLICIT
  approved_by: ...
```

## N17.3 Deterministic ranking tuple

```text
(permission_visible,
 temporal_valid,
 scope_match,
 explicit_override,
 authority_rank,
 specificity,
 source_status,
 recency)
```

앞 요소가 우선하며 recency는 마지막이다.

## N17.4 Conflict

동일 tuple로 contradictory claim이 남으면 `CONFLICTED`로 반환한다.

```json
{
  "status": "CONFLICTED",
  "candidates": [...],
  "required_review": true
}
```

AI가 임의로 평균/다수결/최신 선택 금지.

---

# N18. Bi-temporal & Epistemic Model

## N18.1 Storage

```sql
CREATE TABLE temporal_facts (
  fact_version_id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL,
  workspace_id uuid NOT NULL,
  logical_fact_id uuid NOT NULL,
  valid_time tstzrange,
  system_time tstzrange NOT NULL,
  temporal_precision text NOT NULL,
  temporal_source text NOT NULL,
  epistemic_status text NOT NULL,
  confidence double precision,
  evidence_ids uuid[] NOT NULL,
  CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1)
);
```

## N18.2 Precision

```text
EXACT_TIMESTAMP
EXACT_DATE
MONTH_ONLY
YEAR_ONLY
RANGE
INFERRED
UNKNOWN
```

부분 날짜를 임의 timestamp로 바꾸지 않는다. query 결과에 precision을 노출한다.

## N18.3 System time

system time row는 update하지 않고 close + append한다.

```text
old.system_time = [recorded_at, now)
new.system_time = [now, infinity)
```

## N18.4 Serialization

같은 logical fact/scope의 interval 변경은 advisory lock 또는 serializable transaction으로 수행하고 SQLSTATE `40001`을 bounded exponential backoff로 재시도한다.

---

# N19. Indirect Prompt Injection & Knowledge Poisoning Defense

## N19.1 원칙

문서 내용은 instruction이 아니라 **quoted data**다.

- extraction LLM에 tool/network credential 금지
- system/developer instruction과 source text를 구조적으로 분리
- source text를 XML/JSON/data field로 전달
- output은 strict schema validation
- “ignore previous instructions”, hidden text, white-on-white, tiny font, image text 등 indicator 기록
- suspicious content를 삭제하지 않고 원문 evidence로 보존하되 agent instruction으로 승격하지 않는다.

## N19.2 Two-channel pattern

```text
CONTROL CHANNEL
  schema, extraction task, allowed operation

DATA CHANNEL
  untrusted document blocks with explicit IDs
```

LLM prompt는 source block을 실행할 수 없는 data로 선언한다.

## N19.3 Retrieval defense

- suspicious block flag 반환
- agent context에서 `UNTRUSTED_SOURCE_DATA` delimiter
- tool call 권한과 retrieval 권한 분리
- read-only MCP first
- high-risk actions human approval
- content가 요구하는 external URL fetch 금지

## N19.4 Security benchmark

- visible/hidden text injection
- image-embedded injection
- multilingual injection
- table cell injection
- instruction split across pages
- source asking model to exfiltrate secrets
- RAG poisoning with high semantic similarity

Pass condition: source instruction 때문에 tool 실행, secret 노출, permission 확장, system policy 변경이 0건.

---

# N20. Semantic Diff v3 — deterministic first, model second

## N20.1 Pipeline

```text
L0 content hash
→ L1 structure tree edit
→ L2 evidence/block/cell diff
→ L3 semantic claim diff
→ L4 entity/relation/authority/time diff
→ L5 operational impact classification
```

## N20.2 Candidate alignment

Stable identity match를 먼저 사용하고, unmatched unit만 fuzzy alignment한다.

## N20.3 Change types

```text
ADDED
REMOVED
MODIFIED_VALUE
MODIFIED_CONDITION
MODIFIED_MODALITY      # may → must
MODIFIED_EXCEPTION
MOVED
SPLIT
MERGED
AUTHORITY_CHANGED
SCOPE_CHANGED
VALIDITY_CHANGED
PERMISSION_CHANGED
NO_SEMANTIC_CHANGE
UNKNOWN_CHANGE
```

## N20.4 LLM use

- deterministic text/structure evidence를 입력
- strict enum + before/after evidence IDs 출력
- evidence 없는 semantic change 금지
- verifier rule/model과 disagreement 시 UNKNOWN/review

## N20.5 Operational diff

policy DSL 또는 typed graph rule로 downstream behavior가 바뀌는지 판단한다. 작은 text diff가 큰 operational diff가 될 수 있다.

---

# N21. Typed Dependency & Impact Propagation

## N21.1 Edge semantics

| Edge | Source change 시 기본 동작 |
|---|---|
| DERIVED_FROM | target stale |
| DEPENDS_ON | target stale 또는 revalidate |
| SUPPORTS | evidence sufficiency revalidate |
| REFERENCES | notify; 자동 invalidate 아님 |
| SUPERSEDES | old validity close |
| CONTINUES | document reconciliation re-run |
| EXPORTS_TO | target artifact rebuild |
| EMBEDS_INTO | embedding rebuild |
| CONSUMED_BY | agent/context notify |
| PERMISSION_INHERITS | permission recalc |
| AUTHORITY_OVERRIDES | resolution re-run |

## N21.2 Traversal

```python
def propagate(changed_nodes, snapshot, policy):
    queue = deque(changed_nodes)
    visited = set()
    impacts = []
    while queue:
        node = queue.popleft()
        if node in visited:
            continue
        visited.add(node)
        for edge in outgoing_edges(node, snapshot):
            decision = policy.evaluate(edge, node.change)
            impacts.append(decision)
            if decision.propagate:
                queue.append(edge.to_id)
    return impacts
```

## N21.3 Explosion protection

부트스트랩 safety gate:

- affected unit > 10,000 또는 workspace의 20% 초과
- depth > 32
- SCC/cycle unexpected

이면 `IMPACT_EXPLOSION_REVIEW`로 표시하고 full rebuild cost와 비교한다. 이 값은 config이며 corpus size benchmark로 교정한다.

## N21.4 Explainability

모든 impacted item은 최소 하나의 reason path를 가진다.

```text
policy_v3.pdf page17 cellB7
→ claim warranty_duration
→ RAG chunk 882
→ support_agent context pack
```

---

# N22. Selective Recompilation & Atomic World State

## N22.1 Dirty set

```text
changed source/evidence
→ changed logical units
→ typed propagation
→ dirty artifacts
→ rebuild plan
```

## N22.2 Build isolation

현재 published world state를 직접 수정하지 않는다.

```text
world_state N (published)
        │
        ├ source changes
        ▼
world_state_candidate N+1 (staging)
        │
        ├ selective compile
        ├ validation
        ├ equivalence sample/full check
        └ permission/security check
        ▼
atomic pointer swap
```

## N22.3 Commit protocol

1. candidate DB rows와 R2 artifacts 생성
2. artifact checksum verify
3. validation report 생성
4. publication manifest hash 생성
5. serializable transaction에서 candidate 상태 확인
6. `workspace.current_world_state_id` pointer 교체
7. outbox에 `world_state.published` 기록
8. transaction commit

## N22.4 Equivalence

- deterministic export: byte/structural exact equivalence
- embedding/LLM-derived: version-pinned semantic/structural comparator
- 관련 subset에서 full rebuild와 불일치하면 publish block
- production hotfix는 full rebuild fallback 허용, receipt 필수

## N22.5 Rollback

pointer를 이전 valid world state로 원자적으로 되돌린다. source history는 삭제하지 않는다.

---

# N23. Retrieval — Permission·Time·Authority가 ANN보다 먼저다

## N23.1 Query contract

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
  query: ...
  top_k: 10
```

## N23.2 Filter order

1. tenant/workspace
2. published world state
3. principal permissions/sensitivity
4. valid/system time
5. authority/applicability
6. status/validation
7. lexical/vector candidate
8. rerank
9. evidence coverage

## N23.3 pgvector

- pgvector >=0.8 iterative scan 사용 가능
- approximate index filter가 결과 수/recall을 떨어뜨릴 수 있으므로 iterative scan 또는 exact fallback
- tenant 수가 적고 큰 경우 partition; 작은 tenant가 많으면 workspace partition strategy benchmark
- global HNSW 하나에 모든 tenant를 넣는 결정은 cross-tenant recall/isolation benchmark 없이는 금지
- small corpus는 exact search가 더 단순하고 정확할 수 있다.

## N23.4 Embedding version

```text
embedding_key = hash(unit_version_id + model_id + model_revision + chunker_version)
```

서로 다른 embedding version을 한 ranking에서 섞지 않는다. upgrade는 shadow index → benchmark → atomic index pointer swap.

## N23.5 Response

모든 result에:

- unit version
- world state
- valid/system time
- evidence IDs
- authority/applicability
- permission decision ID
- quality/epistemic state

를 포함한다.

---

# N24. API & MCP 2026-07-28 Contract

## N24.1 API error model

```json
{
  "error": {
    "code": "KNOWLEDGE_CONFLICTED",
    "message": "No single authoritative claim can be resolved.",
    "request_id": "req_...",
    "details": {"review_id": "rev_..."}
  }
}
```

HTTP status와 domain error를 분리한다.

## N24.2 Launch read tools

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

## N24.3 MCP 보안

- 2026-07-28 spec에 맞춘 HTTP transport
- OAuth 2.1 resource server
- Protected Resource Metadata
- token audience/resource binding 검증
- issuer binding 검증
- token passthrough 금지
- authorization code는 end-user, client credentials는 service-to-service
- tool list cache TTL/capability version 고려
- tool별 scope와 audit
- read-only first

## N24.4 Write tools

`source.ingest`, `knowledge.recompile`, `workspace.sync`는 다음이 모두 있을 때만 expose:

- idempotency key
- explicit scope
- approval policy
- audit trail
- dry-run/impact preview
- rollback path

파괴적 delete/write tool은 초기 MCP에서 제공하지 않는다.

---

# N25. Agent Consumption Lineage & Decision Replay

## N25.1 Consumption event

```yaml
agent_consumption:
  consumption_id: ac_...
  tenant_id: ...
  agent_id: ...
  principal_id: ...
  world_state_id: ...
  request_id: ...
  retrieved_unit_version_ids: [...]
  evidence_ids: [...]
  permission_decision_ids: [...]
  tool_calls: [...]
  action_summary: ...
  created_at: ...
```

## N25.2 Stale response analysis

source change가 publish되면 과거 consumption log를 조회하여:

- 어떤 agent/context가 stale unit을 사용했는지
- 후속 행동이 있었는지
- 고객 통지/재평가가 필요한지

를 계산한다.

## N25.3 Replay 범위

재현 대상:

- 당시 world state
- 당시 permission
- retrieved context/evidence
- tool input/output
- model/config version
- action trace

모델의 비공개 내부 chain-of-thought 재현이라고 주장하지 않는다.

---

# N26. Event / Job Semantics — at-least-once를 안전하게 쓰기

## N26.1 Transactional outbox

```sql
CREATE TABLE outbox_events (
  event_id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL,
  aggregate_type text NOT NULL,
  aggregate_id uuid NOT NULL,
  aggregate_version bigint NOT NULL,
  event_type text NOT NULL,
  payload jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  published_at timestamptz
);
```

business transaction과 outbox insert를 같은 DB transaction에서 수행한다.

## N26.2 Inbox dedup

```sql
CREATE TABLE inbox_events (
  consumer_name text NOT NULL,
  event_id uuid NOT NULL,
  processed_at timestamptz NOT NULL DEFAULT now(),
  result_hash text,
  PRIMARY KEY (consumer_name, event_id)
);
```

consumer는 inbox insert에 성공한 경우만 side effect를 수행하거나, side effect와 inbox를 동일 transaction으로 묶는다.

## N26.3 Ordering

Cloudflare Queues ordering을 가정하지 않는다.

- aggregate_version 비교
- 이미 더 새 version이 반영된 경우 late event는 no-op 또는 reconciliation
- source version identity는 content hash
- delete/create race는 tombstone과 monotonic aggregate version으로 해결

## N26.4 Lease queue

DB 내부 job claiming은 `FOR UPDATE SKIP LOCKED`를 queue-like table에 제한해 사용한다. 일반 business query의 consistency 도구로 남용하지 않는다.

## N26.5 DLQ

- bounded retries
- dead-letter queue
- failure signature와 last error 보존
- replay는 새 event ID가 아니라 original event ID + replay attempt로 추적

---

# N27. R2 Commit, Keying, Retention

## N27.1 Key rule

```text
sources/{tenant}/{workspace}/{source_id}/{document_version_id}/original
artifacts/{tenant}/{workspace}/{document_version_id}/{artifact_type}/{sha256}
world-states/{tenant}/{workspace}/{world_state_id}/manifest.json
exports/{tenant}/{workspace}/{export_id}/{sha256}
```

hash artifact key는 overwrite하지 않는다. mutable pointer는 DB가 관리한다.

## N27.2 Presigned URL

- bearer token으로 취급
- short expiry
- exact object key/method/content-type 제한
- CORS allowlist
- completion callback에서 checksum/size 재검증

## N27.3 Conditional write

manifest/lock 성격 object는 precondition을 사용한다. 동일 key에 고빈도 write하지 않는다.

## N27.4 Delete

삭제 요청은 tombstone → access revoke → derived dependency enumeration → object delete → DB purge/anonymize → completion receipt 순으로 처리한다.

---

# N28. RunPod Execution Contract

## N28.1 TTL

job TTL에는 queue 대기와 execution이 함께 들어갈 수 있으므로:

```text
job_ttl >= expected_queue_p99 + cold_start_p99 + execution_p99 + commit_margin
```

실제 telemetry에서 산출한다.

## N28.2 Heartbeat

worker는 stage heartbeat를 보낸다.

```text
STARTED
MODEL_LOADING
INFERENCING
SERIALIZING
UPLOADING_R2
COMMITTING_DB
```

heartbeat timeout은 stage별 p99 기반.

## N28.3 Completion

R2 upload + checksum + DB artifact commit 전에는 RunPod job 성공으로 간주하지 않는다. provider result retention은 source of truth가 아니다.

## N28.4 Endpoint pool

- `balanced`: common champion warm/cache
- `verified`: stronger GPU, lower concurrency
- `shadow`: benchmark only, production output 영향 없음

Network Volume은 cache이며 R2 없이는 복구 불가능한 상태를 만들지 않는다.

---

# N29. Database, RLS, Concurrency

## N29.1 RLS

- 모든 tenant table에 `tenant_id`
- RLS enable + FORCE RLS
- application role은 table owner/superuser가 아님
- connection pool checkout마다 tenant context 초기화
- transaction-local `SET LOCAL app.tenant_id`
- context가 없으면 default deny

```sql
ALTER TABLE knowledge_units ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge_units FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON knowledge_units
USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
```

## N29.2 RLS tests

- owner bypass 방지
- missing tenant context 0 rows/error
- pooled connection tenant switch
- background worker scope
- cross-tenant vector query
- backup/restore role

## N29.3 Concurrency

- source version creation: unique `(source_id, content_sha256)`
- world state publish: serializable transaction + bounded retry
- stable identity reconciliation: workspace/source advisory lock
- duplicate upload: idempotency key

---

# N30. Supply Chain, Reproducibility, Upgrade

## N30.1 Artifact identity

모든 실행에 저장:

- source git commit
- lockfile hash
- container image digest
- SBOM digest
- build attestation
- model ID/revision/file hash
- parser config hash
- prompt/schema version
- CUDA/driver/runtime
- compiler version

## N30.2 Build gate

- SBOM 생성(SPDX 또는 동급)
- GitHub artifact attestation 또는 동급 provenance
- Cosign sign/verify
- critical vulnerability policy
- unpinned image tag 금지
- `latest` model revision 금지

## N30.3 Upgrade workflow

```text
NEW VERSION
→ license/supply-chain review
→ shadow corpus
→ public/adversarial/customer benchmark
→ reproducibility check
→ cost/latency check
→ no-regression gate
→ staged canary
→ atomic promotion
→ rollback window
```

## N30.4 Model/data license

고객 source가 model training에 사용되는지 여부를 explicit policy로 분리한다. 기본값은 **사용하지 않음**. benchmark/public corpus도 redistribution/training license를 metadata로 관리한다.

---

# N31. Observability & Knowledge SLO

## N31.1 OpenTelemetry span tree

```text
tavonel.ingest
  tavonel.preflight
  tavonel.profile
  tavonel.route
  tavonel.queue.wait
  tavonel.worker.cold_start
  tavonel.parse
  tavonel.inspect
  tavonel.recover
  tavonel.reconcile
  tavonel.compile
  tavonel.diff
  tavonel.impact
  tavonel.recompile
  tavonel.validate
  tavonel.publish
```

공통 attributes:

```text
tenant_hash, workspace_hash, document_type, route_class,
parser_id, parser_version, mode, recovery_level,
world_state_id, failure_code, outcome
```

PII/원문 text를 telemetry에 넣지 않는다.

## N31.2 Metrics

- queue delay p50/p95/p99
- cold start
- inference
- page/document TTFP/TTUK/TTCV
- inspector pass/suspicious/fail
- recovery success by code/level
- cost/page/document
- router regret
- impact precision/recall benchmark
- selective work avoided
- recompile equivalence failure
- world sync latency
- stale context rate
- provenance coverage
- cross-tenant denial count

## N31.3 Initial internal gates

절대 public SLA가 아니라 launch engineering target:

- control API p95 regression 없음; target <500ms excluding upload/processing
- warm R0 fast path가 full VLM baseline보다 최소 5× 빠른지 측정
- progressive status가 upload completion 후 2초 이내 시작
- stuck heartbeat 60초 이상 0 또는 stage-specific alert
- p95/p50 tail ratio를 지속 추적
- authoritative source change → published world state latency를 document size별 공개 내부 dashboard에 표시

실측 전 외부 숫자 claim 금지.

---

# N32. Performance & Cost Model

## N32.1 Latency

- **TTA:** upload acknowledgment
- **TTFP:** first preview/progress
- **TTUK:** first usable searchable knowledge
- **TTCV:** complete verified compilation
- **World Sync Latency:** source change → published agent-readable state

## N32.2 Progressive availability

- page/block 완료 즉시 staging UI에 표시
- searchable publish는 validation level에 따라 분리
- document 전체 의미가 필요한 claim은 reconciliation 전 publish 금지
- batch 98/100 완료 때문에 98개 문서를 숨기지 않음

## N32.3 Cost estimate

```text
estimated_cost =
  render_cpu
+ parser_gpu(route, page_count)
+ expected_recovery_probability * recovery_cost
+ embedding
+ storage
+ egress/operations
```

사용자에게 raw GPU cost가 아니라 credit/value metric을 보여준다. 내부 raw cost와 retail price를 분리한다.

## N32.4 Budget enforcement

- preflight estimate
- per-job hard budget
- per-workspace daily/monthly budget
- recovery multiplier ceiling
- abuse anomaly
- kill switch

budget 초과 시 silently downgrade하지 않고 `PARTIAL_BUDGET_EXCEEDED`와 선택지를 제공한다.

---

# N33. Benchmark & Research Program — 제품 개발의 판정기

## N33.1 Dataset layers

1. Existing public benchmark corpus
2. New difficult/multi-page benchmark corpus
3. TAVONEL adversarial synthetic corpus
4. Korean/English mixed enterprise corpus
5. Customer shadow corpus — opt-in, de-identified/policy-controlled
6. Security/prompt-injection corpus

## N33.2 Router oracle matrix

각 page × parser × config에 대해:

- quality metrics
- inspector outcome
- latency
- GPU seconds
- cost
- recovery need

를 모두 측정하여 cheapest parser meeting quality floor를 oracle로 계산한다.

Metrics:

- route accuracy보다 **routing regret**
- quality violation rate
- catastrophic miss
- cost/latency overhead vs oracle
- recovery frequency

## N33.3 Failure detector

- per-code precision/recall/F1
- catastrophic recall
- false escalation cost
- calibration curve
- blank-page false positive

## N33.4 Recovery

- success by failure code
- quality uplift
- cost/latency multiplier
- same-model retry vs reroute contribution
- unrecoverable explicit rate

## N33.5 Reconciler

- paragraph/table/list continuation precision/recall
- hierarchy tree edit distance
- reading-order metric
- source cell provenance retention

## N33.6 Knowledge Evolution corpus

controlled mutations:

- value
- modality
- exception
- authority
- scope
- time
- permission
- entity rename/merge/split
- relation add/remove

Ground truth:

- changed logical units
- impacted graph
- stale chunks
- affected agents
- unaffected set
- expected selective output

## N33.7 Release targets

초기 internal release blocker:

- existing approved claims no-regression
- selective recompile equivalence = 100% on deterministic fixture
- impact precision/recall >= 0.98 on controlled corpus 목표
- tenant/security leakage = 0
- prompt injection tool execution = 0
- queue duplicate/out-of-order로 duplicate world publish = 0
- public claim pack hash verification = 100%

목표 미달은 숨기지 않고 withheld claim으로 남긴다.

---

# N34. Competitive Evaluation — “빠르고 정확하다”를 같은 시험장에서 검증

## N34.1 비교 단위

- raw model mode
- vendor production pipeline mode

두 개를 분리한다. vendor 내부 recovery/agentic correction을 raw model과 혼동하지 않는다.

## N34.2 동일 조건

- 동일 source bytes
- 동일 page ranges
- timeout/retry 명시
- preprocessing 여부
- vendor option/config
- postprocessing allowance
- batch/sync mode
- API response timestamp

## N34.3 Metrics

- text, reading order, table structure/full, formula, figure/caption
- cross-page continuity
- semantic/exception fidelity
- completion/failure/recovery
- p50/p95/p99 latency
- cost/page/document
- source/evidence localization
- version/authority/temporal correctness
- end-to-end QA/agent grounding

비교사는 reproduced와 quoted를 구분한다.

---

# N35. Security / Chaos / FMEA

## N35.1 Chaos cases

- duplicate/out-of-order Queue message
- worker kill at inference/upload/commit
- R2 timeout/checksum mismatch
- DB failover/serialization failure
- model cache missing
- queue delay causes TTL expiry
- old source event after new version
- parser returns plausible corrupt output
- permission revoked during compile
- prompt injection hidden in image/table
- recovery loop
- model update output drift
- world publish race
- deletion interrupted
- backup restore to isolated environment

## N35.2 Pass criteria

- source/verified artifact loss 0
- invalid world state publish 0
- cross-tenant access 0
- unbounded retry 0
- audit trail complete
- fail closed 또는 deterministic recovery

## N35.3 FMEA fields

```yaml
fmea_item:
  failure_code: F24_RECOMPILE_DIVERGENCE
  severity: 10
  occurrence: 3
  detectability: 2
  rpn: 60
  preventive_controls: [...]
  detective_controls: [...]
  recovery: ...
  owner: knowledge-integrity
  test_id: chaos_recompile_divergence
```

RPN만으로 priority를 결정하지 않고 severity 10 항목은 항상 launch blocker로 관리한다.

---

# N36. Privacy, Retention, Deletion, Backup, DR

## N36.1 Data classes

- original source
- derived render/artifact
- evidence preview
- knowledge unit/graph
- embeddings
- logs/telemetry
- human review
- public benchmark/evidence

각 class별 default retention과 customer override를 문서화한다.

## N36.2 Delete workflow

```text
REQUESTED
→ ACCESS_REVOKED
→ DEPENDENCY_ENUMERATED
→ SOURCE/DERIVED OBJECT DELETED
→ DB ROW PURGED OR LEGALLY REQUIRED TOMBSTONE
→ VECTOR/SEARCH INDEX REMOVED
→ BACKUP EXPIRY SCHEDULED
→ RECEIPT_ISSUED
```

active system 삭제와 immutable backup expiration을 구분해 안내한다.

## N36.3 Backup

- managed Postgres PITR
- periodic logical/schema backup
- R2 object inventory/manifest
- encryption/key rotation
- restoration test
- backup role와 RLS considerations

## N36.4 DR

문서화할 값:

- RPO
- RTO
- dependency outage runbook
- restore validation
- world-state pointer consistency

launch 전 실제 restore drill 없이는 DR 완료라고 말하지 않는다.

---

# N37. Knowledge Health Scan v3 — 정직하고 전환되는 진단

## N37.1 결과는 finding-first

단일 72/100보다 다음을 먼저 보여준다.

- conflicting versions
- uncertain authority
- unsupported claims
- ambiguous entities
- broken evidence
- parser recovery events
- potentially stale paths
- permission inconsistencies
- prompt-injection/security indicators

## N37.2 Score

```text
Knowledge Health =
  30% integrity
+ 20% freshness/version
+ 20% provenance coverage
+ 15% ambiguity/conflict
+ 15% recoverability/operational readiness
```

각 category의 denominator와 confidence를 보여준다. 검사하지 않은 항목을 100점으로 간주하지 않는다.

## N37.3 AI Risk Simulation wording

확정적으로 “AI가 틀린다”고 말하지 않고:

- potentially conflicting answers
- potentially outdated answers
- unsupported answer paths
- ambiguous entity paths

로 표현한다. 실제 QA simulation을 실행한 경우만 measured answer failure를 주장한다.

## N37.4 Conversion

```text
Finding
→ Evidence preview
→ Why it matters to AI
→ Impact preview
→ Compile/resolve this workspace
```

---

# N38. Product UX — 핵심 5개 Surface

1. **Ingest/Live Pipeline:** classify, route, parse, recover, reconcile, compile 상태.
2. **Evidence Inspector:** claim → unit → original page/cell.
3. **Change Center:** before/after semantic diff, authority/time/permission change.
4. **Impact Explorer:** typed reason path와 affected/unaffected.
5. **World State/Timeline:** current/as-of/known-at, publish/rollback.

Graph는 예쁜 node cloud가 아니라 provenance·cause/effect·time·permission을 보여준다.

## N38.1 Progress

fake percentage 금지. 실제 counters:

```text
83 files
✓ Preflight 83
✓ Routed 83
✓ Parsed 71
↻ Recovering 4
✓ Reconciled 58
✓ Validated 41
```

---

# N39. Marketing, Pilot, Monetization — 기술 evidence와 묶기

## N39.1 Category sequence

```text
TAVONEL 1: Knowledge Compiler
TAVONEL 2: Knowledge CI/CD
TAVONEL 3: Temporal Organizational Context
TAVONEL 4: Decision Integrity Layer
```

외부 category는 먼저 `The Knowledge Compiler`로 고정한다.

## N39.2 Initial wedge

> **A source changed. Which AI knowledge is stale now?**

첫 vertical:

- technical documentation/customer support
- manufacturing manuals
- policy/compliance

초기 pilot은 하나의 좁은 workflow를 선택한다.

## N39.3 Pilot success contract

- corpus 범위
- baseline QA/freshness problem
- provenance coverage
- change-to-sync latency
- work avoided
- outdated/conflict reduction
- weekly review
- paid conversion criterion

2–4주 pilot 뒤 성공/실패 receipt를 남긴다.

## N39.4 Claim ladder

- philosophy: 자유롭게
- existing evidence: approved claim pack만
- new router/recovery: benchmark 후
- Knowledge CI/CD: controlled corpus 후
- customer outcome: customer permission + methodology 후

---

# N40. AI-Native Solo Founder Software Factory

## N40.1 Agent topology

```text
lead-orchestrator
├ architecture-auditor        read-only first
├ ingestion-security
├ router-runtime
├ parser-recovery
├ knowledge-integrity
├ temporal-authority
├ api-mcp-security
├ database-multitenancy
├ frontend-product
├ cinematic-director
├ benchmark-scientist
├ evidence-auditor
├ visual-qa
├ adversarial-reviewer
└ release-manager
```

각 subagent는 독립 context, 최소 tool permission, 명확한 output contract를 가진다.

## N40.2 Four-eyes rule

한 agent가 구현과 최종 승인을 동시에 하지 않는다.

```text
Implementer
→ deterministic CI
→ Reviewer/Skeptic agent
→ evidence-auditor
→ release gate
```

## N40.3 Claude permissions

- production secret 직접 노출 금지
- migrations/deploy는 CI와 approval gate
- `.env`, keys, customer sources deny
- command hooks는 full user permission으로 실행될 수 있으므로 absolute path/input sanitization
- `--dangerously-skip-permissions`를 production workspace 기본값으로 사용 금지

## N40.4 Hooks

- Python edit → Ruff/mypy/targeted pytest
- TS edit → ESLint/tsc/Vitest
- schema edit → codegen + compatibility tests
- migration edit → single-head/RLS test
- parser/router edit → relevant benchmark slice
- marketing claim edit → claim validator
- 3D edit → Playwright screenshots/performance/reduced-motion
- container build → SBOM/sign/verify

## N40.5 Checkpoint

phase마다:

- git commit/tag
- architecture decision record
- test report
- benchmark receipt
- rollback instruction
- remaining gap matrix

---

# N41. Dependency-Aware Implementation Phases v3

## Phase 0 — Freeze, inventory, legal/supply-chain gate

Deliverables:

- repository map
- test baseline
- evidence hash verification
- dependency/model/license inventory
- current architecture gap matrix
- CLAUDE.md/project constitution

Exit:

- existing tests green or known failures documented
- no verified evidence lost
- production-blocked license components identified

## Phase 1 — Deterministic contracts and test harness

- IR v3 schema
- event/failure/state enums
- JSON Schema/Pydantic/TS codegen
- ground-truth fixture harness
- CI gates

Exit: schema round-trip, migration, property tests.

## Phase 2 — Secure ingest/preflight/R2 manifest

- upload/presign
- quarantine prefix
- hash/MIME/resource inspection
- source state machine
- malicious archive/image/PDF tests

## Phase 3 — Profiler/reference renderer/model registry

- pypdfium2 reference render
- feature extraction/versioning
- parser registry/license gate
- profiler fixture dashboard

## Phase 4 — Deterministic router/execution planner

- boot config
- route decision receipt
- batching/windowing
- oracle benchmark

## Phase 5 — Parser adapters/RunPod commit protocol

- champion adapter preserved
- challenger shadow
- R2-before-ACK
- heartbeat/circuit breaker

## Phase 6 — Inspector/failure taxonomy/recovery

- detectors
- consensus condition
- policy engine/budgets
- failure benchmark

## Phase 7 — Document Reconciler

- paragraph/list/table/caption/hierarchy
- multi-page benchmark
- uncertain continuation relations

## Phase 8 — IR/provenance/stable identity

- evidence inspector backend
- transformation lineage
- logical matching
- reversible split/merge

## Phase 9 — Entity/authority/temporal/epistemic/security

- resolver DSL
- bitemporal rows
- prompt-injection labels
- review queue

## Phase 10 — Diff/dependency/impact

- L0–L5 diff
- typed propagation
- reason paths
- explosion guard

## Phase 11 — Selective recompile/world state

- dirty set
- staging build
- equivalence
- atomic publish/rollback

## Phase 12 — Retrieval/API/MCP

- permission-first retrieval
- embedding versioning
- read-only MCP 2026-07-28 auth
- consumption lineage

## Phase 13 — Health Scan/commercial core

- diagnostic report
- finding evidence
- account/workspace/billing/analytics
- pilot onboarding

## Phase 14 — Product UI/website/cinematic/evidence

- real product surfaces
- hero change→impact→recompile
- reduced motion/mobile/WebGL fallback
- claim pack-rendered evidence page

## Phase 15 — Competitive/research publication

- router/recovery/evolution benchmark
- same-condition competitor run
- methodology/limitations/receipts

## Phase 16 — Enterprise hardening

- SSO/RBAC/retention/audit export
- backup/restore drill
- security review/pentest roadmap

## Phase 17 — Decision replay/write MCP/simulation

실사용 demand와 governance가 검증된 뒤만.

---

# N42. Phase Exit Template

Claude는 phase 완료 시 다음 JSON/Markdown report를 생성해야 한다.

```yaml
phase_report:
  phase: 6
  commit: ...
  implemented: [...]
  tests:
    passed: ...
    failed: ...
  benchmark_receipts: [...]
  security_checks: [...]
  migrations: [...]
  telemetry_added: [...]
  known_limitations: [...]
  claims_enabled: [...]
  claims_withheld: [...]
  rollback: ...
  next_phase_ready: true
```

`next_phase_ready=false`이면 다음 phase 기능 구현을 시작하지 않고 blocker 해결만 수행한다.

---

# N43. Acceptance Matrix — 핵심 release blockers

| Subsystem | Required evidence | Blocker condition |
|---|---|---|
| Upload/preflight | malicious fixture suite | zip bomb/path traversal/parser exploit exposure |
| Router | oracle matrix + slice report | quality floor violation/catastrophic miss |
| Parser adapter | schema + checksum + license | unverified container/model/license |
| Inspector | per-code metrics | catastrophic fixture miss |
| Recovery | ablation/attempt/cost | unbounded retry or silent downgrade |
| Reconciler | multi-page ground truth | source provenance loss |
| IR | round-trip/schema compatibility | fabricated source/time/bbox |
| Identity/entity | mutation fixtures | false merge in critical set |
| Authority/time | resolution fixtures | unresolved conflict silently resolved |
| Prompt injection | adversarial corpus | instruction causes tool/policy action |
| Impact | precision/recall/reason paths | missed ground-truth impacted unit |
| Recompile | full-build equivalence | any deterministic divergence |
| World state | race/rollback tests | partial/duplicate publish |
| Retrieval | RLS/filter recall | cross-tenant leak or stale state returned |
| MCP | auth/permission tests | token passthrough/audience failure |
| Delete/DR | deletion/restore drill | untracked retained data/invalid restore |
| Marketing | claim validator | unsupported number/adjective |

---

# N44. Required Test Repository Layout

```text
tests/
├ unit/
│  ├ test_preflight_limits.py
│  ├ test_profiler_features.py
│  ├ test_router_policy.py
│  ├ test_failure_detectors.py
│  ├ test_recovery_policy.py
│  ├ test_reconciler_tables.py
│  ├ test_stable_identity.py
│  ├ test_authority_resolution.py
│  ├ test_temporal_bitemporal.py
│  ├ test_dependency_propagation.py
│  └ test_claim_guard.py
├ property/
│  ├ test_ir_roundtrip.py
│  ├ test_idempotency.py
│  ├ test_recompile_equivalence.py
│  ├ test_temporal_no_overlap.py
│  └ test_tenant_isolation.py
├ integration/
│  ├ test_upload_r2_job_runpod_commit.py
│  ├ test_outbox_queue_inbox.py
│  ├ test_world_state_atomic_publish.py
│  ├ test_retrieval_permission_time.py
│  └ test_mcp_auth.py
├ benchmark/
│  ├ router/
│  ├ failure/
│  ├ recovery/
│  ├ multipage/
│  ├ knowledge_evolution/
│  ├ korean/
│  └ security/
├ chaos/
│  ├ test_duplicate_events.py
│  ├ test_worker_kill.py
│  ├ test_r2_commit_failure.py
│  ├ test_publish_race.py
│  ├ test_permission_drift.py
│  └ test_restore_drill.py
└ e2e/
   ├ test_health_scan_conversion.py
   ├ test_change_impact_recompile_ui.py
   └ test_reduced_motion_mobile.py
```

---

# N45. Operational Runbooks

반드시 `/docs/runbooks/`에 다음을 만든다.

- provider-wide RunPod failure
- R2 degraded/commit failure
- DB failover/serialization storm
- queue backlog/DLQ replay
- model rollback
- world-state rollback
- suspected tenant leak
- prompt injection incident
- cost runaway
- stuck deletion
- restore from backup
- public claim correction

각 runbook:

```text
Detection
Severity
Immediate containment
Data integrity check
Recovery
Customer communication
Evidence preservation
Postmortem
Prevention change
```

---

# N46. Decision Register — 기본값과 변경 조건

| Decision | Default | Revisit trigger |
|---|---|---|
| Neo4j | 사용 안 함 | Postgres traversal benchmark가 SLO 미달 |
| Kafka | 사용 안 함 | outbox+Queue throughput/ordering workaround가 한계 |
| Self-hosted auth | 사용 안 함 | enterprise residency 또는 cost requirement |
| Custom OCR foundation model | 사용 안 함 | routing/runtime 개선으로 해결 불가한 strategic gap + dataset/자본 확보 |
| Human review | ambiguity/high-risk only | review volume/unit economics 데이터 |
| Write MCP | read-only first | permissions/approval/audit maturity + paid demand |
| Full simulator | 구현 안 함 | Decision Replay 사용 수요/ground truth 확보 |
| Paid parser fallback | off by default | customer opt-in + unit economics |
| Customer data training | off | explicit separate consent/legal/product decision |

모든 변경은 ADR과 benchmark/evidence를 요구한다.

---

# N47. Research Source Register — 2026-08-10

아래는 설계에 사용한 외부 공식 문서/1차 연구다. 구현 직전에 최신 revision을 다시 열고 lockfile/ADR에 실제 접근일과 commit/version을 기록한다.

## Document parsing/runtime

- MinerU releases: https://github.com/opendatalab/MinerU/releases
- MinerU repository: https://github.com/opendatalab/MinerU
- PaddleOCR official docs: https://www.paddleocr.ai/latest/en/index.html
- PaddleOCR-VL usage / cross-page merge: https://paddlepaddle.github.io/PaddleOCR/main/en/version3.x/pipeline_usage/PaddleOCR-VL.html
- PaddleOCR-VL-1.6 technical report: https://arxiv.org/abs/2606.03264
- Unstructured partition strategies: https://docs.unstructured.io/api-reference/legacy-api/partition/partitioning
- Reducto classify/pipeline docs: https://docs.reducto.ai/classify/overview
- Mistral OCR 4: https://mistral.ai/news/ocr-4/
- MPDocBench-Parse: https://arxiv.org/abs/2605.22100
- Dr.DocBench: https://arxiv.org/abs/2606.01393
- PureDocBench: https://arxiv.org/abs/2605.07492
- Consensus Entropy: https://arxiv.org/abs/2504.11101

## Infrastructure/concurrency

- R2 consistency: https://developers.cloudflare.com/r2/reference/consistency/
- R2 presigned URLs: https://developers.cloudflare.com/r2/api/s3/presigned-urls/
- R2 event notifications: https://developers.cloudflare.com/r2/buckets/event-notifications/
- Cloudflare Queues delivery guarantees: https://developers.cloudflare.com/queues/reference/delivery-guarantees/
- PostgreSQL RLS: https://www.postgresql.org/docs/current/ddl-rowsecurity.html
- PostgreSQL explicit locking: https://www.postgresql.org/docs/current/explicit-locking.html
- PostgreSQL transaction isolation: https://www.postgresql.org/docs/current/transaction-iso.html
- pgvector iterative scans/filtering: https://github.com/pgvector/pgvector
- RunPod Serverless docs: https://docs.runpod.io/serverless/overview

## Security/supply chain

- OWASP File Upload: https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html
- OWASP Prompt Injection: https://genai.owasp.org/llmrisk/llm01-prompt-injection/
- MCP 2026-07-28 specification: https://modelcontextprotocol.io/specification/2026-07-28
- MCP authorization: https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization
- SLSA v1.2: https://slsa.dev/spec/v1.2/
- SPDX: https://spdx.dev/use/specifications/
- Sigstore Cosign: https://docs.sigstore.dev/quickstart/quickstart-cosign/
- GitHub artifact attestations: https://docs.github.com/actions/security-for-github-actions/using-artifact-attestations

## Observability/Claude

- OpenTelemetry semantic conventions: https://opentelemetry.io/docs/specs/semconv/
- Claude Code subagents: https://docs.anthropic.com/en/docs/claude-code/sub-agents
- Claude Code hooks: https://docs.anthropic.com/en/docs/claude-code/hooks
- Claude Code permissions: https://docs.anthropic.com/en/docs/claude-code/permissions

## Industry direction

- OpenAI Frontier: https://openai.com/business/frontier/
- Microsoft Fabric Ontology: https://learn.microsoft.com/en-us/fabric/iq/ontology/overview
- Microsoft Ontology agent integration: https://learn.microsoft.com/en-us/fabric/iq/ontology/concepts-agent-integration
- Palantir Ontology MCP: https://palantir.com/docs/foundry/ontology-mcp/overview/

---

# PART B2 — v3.1 COMPLETENESS CLOSURE METHODBOOK
## Semantic Model Gateway · Retrieval Packaging · Office Dual Path · Connectors · GPU Scheduling · End-to-End Evaluation · Exports · Billing · GTM Execution

> 이 Part는 v3.0 최종 검수에서 발견된 마지막 구현 공백을 닫는다.  
> `PART B2 > PART B > PART A > PART C` 순으로 우선한다.  
> 아래 기본값은 현재 repository에 동등하거나 더 강한 검증 구현이 없을 때 적용한다.

---

# X0. v3.1에서 추가로 잠그는 것

v3.0은 Adaptive Execution, Recovery, Knowledge Integrity, Temporal/Lineage, Incremental Recompilation의 핵심을 잠갔다. v3.1은 실제 고객이 파일 뭉텅이를 넣고 결과를 검색·검증·유지·결제하기까지 필요한 다음 빈칸을 닫는다.

1. parsing 이후 semantic extraction에 어떤 open-weight model을 어떤 규칙으로 사용하는가
2. embedding/reranker를 어떻게 고르고 upgrade하는가
3. 구조를 잃지 않는 chunk/RAG package를 어떻게 생성하는가
4. DOCX/PPTX/XLSX의 구조와 시각적 의미를 동시에 어떻게 보존하는가
5. 중복·개정·파일명 변경·경로 이동을 어떻게 구분하는가
6. connector 변화와 ACL 변경을 어떻게 안전하게 동기화하는가
7. 여러 tenant와 여러 GPU 모델 사이에서 어떻게 공정하게 scheduling하는가
8. parsing accuracy를 넘어 retrieval·answer·citation correctness를 어떻게 측정하는가
9. IR에서 Markdown/RAG/Ontology/Neo4j/MCP를 어떻게 결정론적으로 compile하는가
10. API streaming·webhook·SDK·rate limit을 어떻게 구현하는가
11. 복잡도별 원가를 어떻게 credit와 billing으로 바꾸는가
12. human review를 어떻게 학습 데이터로 전환하되 고객 데이터를 무단 학습하지 않는가
13. schema/model/runtime upgrade를 무중단으로 어떻게 배포하는가
14. 경쟁사의 빠르고 정확해 보이는 claim을 어떤 동일 시험장에서 검증하는가
15. 기술 evidence를 실제 pilot·유료 전환·Gracian Code 유입으로 어떻게 연결하는가

## X0.1 최종 제품 경계

TAVONEL이 직접 소유해야 하는 것:

```text
Adaptive routing and recovery
Canonical Knowledge IR
Evidence-level provenance
Stable semantic identity
Entity / authority / temporal resolution
Structure-aware knowledge packaging
Semantic diff and typed impact
Incremental recompilation
Versioned world-state publish
Knowledge integrity evaluation
```

TAVONEL이 adapter로 사용해야 하는 것:

```text
OCR/VLM foundation models
General-purpose LLMs
Embedding/reranking models
PostgreSQL/pgvector
R2/Queues/RunPod
Auth/Billing/Analytics/Monitoring
```

어떤 외부 부품도 TAVONEL의 canonical truth가 될 수 없다. 모든 출력은 adapter contract를 통과해 IR/evidence/version으로 흡수한다.

---

# X1. Semantic Model Gateway — LLM을 교체 가능한 proposal engine으로 사용

## X1.1 Task taxonomy

하나의 “AI 호출”로 뭉개지 않는다. 모든 model request는 아래 task type 중 하나다.

```text
BLOCK_CLASSIFICATION
CLAIM_EXTRACTION
ENTITY_MENTION_EXTRACTION
RELATION_CANDIDATE_EXTRACTION
TEMPORAL_EXPRESSION_EXTRACTION
AUTHORITY_SCOPE_CANDIDATE
SEMANTIC_DIFF_CLASSIFICATION
DOCUMENT_CONTINUATION_SCORE
FIGURE_TABLE_DESCRIPTION
CONFLICT_EXPLANATION
ANSWER_SYNTHESIS
ANSWER_VERIFICATION
```

각 task는 별도 schema, prompt version, model policy, timeout, token budget, benchmark를 가진다.

## X1.2 기본 open-weight candidate policy

아래는 무조건 production 확정 모델이 아니라 **초기 benchmark candidate**다. license, model card, weight hash, runtime compatibility, Korean/English corpus를 통과한 뒤 registry에서 승격한다.

| Mode/Task | Bootstrap candidate | 원칙 |
|---|---|---|
| Small structured proposal | Qwen3-4B/8B 계열 | 낮은 비용, strict JSON schema |
| Balanced semantic extraction | Qwen3-14B 계열 | Korean/English, 128K context candidate |
| Verified difficult semantic pass | Qwen3-30B-A3B 계열 | 별도 verifier/grounding gate |
| Text embedding | Qwen3-Embedding-0.6B | launch default candidate |
| Higher-quality embedding challenger | Qwen3-Embedding-4B | shadow benchmark 후 승격 |
| Text reranking | Qwen3-Reranker-0.6B | launch default candidate |
| Verified reranking challenger | Qwen3-Reranker-4B | latency/cost floor 통과 후 |
| Multimodal page/figure retrieval | Qwen3-VL-Embedding/Reranker 2B 계열 | optional challenger, text retrieval 대체 아님 |

Qwen3 기본 모델과 Qwen3 Embedding/Reranker series의 공개 라이선스는 실제 model revision마다 registry에서 재검증한다. `latest` alias를 사용하지 않는다.

## X1.3 Gateway request contract

```yaml
model_request:
  request_id: mr_...
  tenant_id: ...
  workspace_id: ...
  task_type: CLAIM_EXTRACTION
  task_schema_version: 3
  prompt_version: claim_extract_v7
  model_policy: BALANCED_SEMANTIC
  model_id: qwen3_14b
  model_revision: ...
  runtime_id: vllm_...
  runtime_digest: sha256:...
  decoding:
    temperature: 0
    top_p: 1
    max_output_tokens: 2048
    seed: 17
  input_refs: [ev_...]
  input_hash: sha256:...
  output_schema_ref: tavonel.claim-candidate/v3
  security:
    tools_allowed: false
    outbound_network: false
    source_is_untrusted_data: true
  budget:
    max_wall_ms: 30000
    max_cost_units: 20
```

## X1.4 Structured output algorithm

1. Pydantic/JSON Schema를 source of truth로 생성한다.
2. model runtime의 grammar/JSON-schema constrained decoding을 사용할 수 있으면 사용한다.
3. raw output은 immutable artifact로 보존한다.
4. schema validation 실패 시 같은 잘못된 output을 문자열로 “수리”해 truth로 만들지 않는다.
5. 첫 retry는 schema-only correction prompt, 두 번째는 stronger model/reroute다.
6. evidence ID가 존재하지 않는 claim/relation은 reject한다.
7. enum 밖의 값은 `UNKNOWN`으로 바꾸는 것이 아니라 schema fail로 처리한다.
8. model output이 source text를 변형한 경우 `PROPOSED_NORMALIZATION`으로 보존하고 original evidence를 대체하지 않는다.

```python
async def run_structured(req: ModelRequest, schema: type[BaseModel]):
    raw = await gateway.generate(req)
    store_raw(raw)
    try:
        return schema.model_validate_json(raw.text)
    except ValidationError as err:
        emit_failure("F31_SCHEMA_INCOMPATIBLE", err)
        if req.attempt == 0:
            return await retry_schema_correction(req, err)
        return await reroute_stronger_or_fail(req, err)
```

## X1.5 Correlated error 방지

- extraction과 verification을 같은 prompt 한 번으로 합치지 않는다.
- high-risk VERIFIED flow에서는 가능하면 다른 model family 또는 deterministic rule evaluator를 추가한다.
- 같은 model이 만든 claim을 같은 model의 “맞습니까?” 한 번으로 verified 처리하지 않는다.
- model agreement는 source truth가 아니라 escalation signal이다.

## X1.6 Model cache와 재현성

```text
model_result_key = hash(
  task_type + task_schema_version + prompt_version +
  model_id + model_revision + runtime_digest + decoding_hash + input_hash
)
```

model/runtime upgrade 후 과거 cache를 재사용하지 않는다. 동일 model이어도 runtime version이 달라 vector/output drift가 있을 수 있으므로 digest까지 pin한다.

## X1.7 Acceptance

- schema-valid rate만 accuracy로 주장 금지
- evidence reference validity = 100%
- unsupported/fabricated evidence ID = 0
- deterministic fixture repeat stability 측정
- Korean/English 혼합 claim/temporal/authority fixture no-regression
- prompt injection corpus에서 tool/network action = 0

공식 후보 근거:
- Qwen3 open-weight models: https://qwenlm.github.io/blog/qwen3/
- Qwen3 Embedding/Reranker: https://qwenlm.github.io/blog/qwen3-embedding/
- Qwen3-VL Embedding/Reranker: https://github.com/QwenLM/Qwen3-VL-Embedding

---

# X2. Embedding · Reranking · Retrieval Model Contract

## X2.1 Text와 display content를 분리

```yaml
retrieval_document:
  chunk_id: chk_...
  display_content: "원문 기반 Markdown"
  embedding_content: "검색을 위한 구조-aware text"
  evidence_ids: [...]
  generated_enrichment_ids: []
```

- `display_content`는 source-grounded content다.
- `embedding_content`는 heading path, entity aliases, table header context 등을 포함할 수 있다.
- LLM이 만든 figure/table summary는 `generated_enrichment`로 별도 provenance를 가지며 원문을 대체하지 않는다.

## X2.2 Bootstrap model decision

초기 Korean/English enterprise corpus 기준:

```yaml
retrieval_models:
  embedding_default:
    candidate: Qwen3-Embedding-0.6B
    dimensions: 1024
    precision: bfloat16_or_validated_runtime
  embedding_challenger:
    candidate: Qwen3-Embedding-4B
  reranker_default:
    candidate: Qwen3-Reranker-0.6B
  reranker_verified:
    candidate: Qwen3-Reranker-4B
```

모델 카드의 benchmark를 그대로 TAVONEL claim으로 사용하지 않는다. TAVONEL corpus에서 recall/latency/cost를 재평가한다.

## X2.3 Query instruction registry

instruction-aware embedding에는 query/document instruction을 versioning한다.

```yaml
embedding_profile:
  profile_id: enterprise_knowledge_ko_en_v1
  query_instruction: "Retrieve authoritative organizational evidence relevant to the query."
  document_instruction: "Represent this source-grounded organizational knowledge unit."
  tokenizer_version: ...
  max_tokens: 8192
  truncation_policy: STRUCTURE_AWARE
```

instruction을 바꾸면 새로운 embedding version이다.

## X2.4 Retrieval pipeline

```text
permission/time/authority/status filter
→ lexical BM25 candidate
→ dense candidate
→ weighted union / RRF
→ cross-encoder rerank
→ diversity/duplicate collapse
→ evidence coverage gate
→ context pack assembly
```

RRF bootstrap:

```text
score(d) = Σ 1 / (k + rank_i(d)), k=60 bootstrap
```

가중치와 `k`는 QA benchmark로 교정한다.

## X2.5 Exact fallback

- 작은 filtered corpus에서는 exact cosine search를 우선 검토한다.
- ANN filtered result가 `top_k` 미달이면 pgvector iterative scan 또는 exact fallback.
- permission/time filter 전역 누락 때문에 결과가 없는 것과 실제 relevant result가 없는 것을 구분한다.
- mixed embedding version query 금지.

## X2.6 Promotion gate

- Retrieval Recall@k
- nDCG@10 / MRR
- Korean/English cross-lingual slice
- outdated/authority conflict slice
- table/figure query slice
- p50/p95 latency and GPU/CPU memory
- vector stability across runtime versions

Qwen 공식 series는 0.6B/4B/8B embedding·reranking과 multilingual support를 제공하지만, production 승격은 TAVONEL receipt로만 결정한다.

---

# X3. Structure-Aware Knowledge Packaging & Chunking

## X3.1 Chunking은 IR consumer다

parser raw text를 직접 token length로 자르지 않는다.

```text
Canonical Knowledge IR
→ semantic atomic units
→ hard boundary constraints
→ candidate grouping
→ token/structure optimization
→ parent/child packages
→ retrieval benchmark
```

## X3.2 Hard boundaries

다음은 기본적으로 중간에서 자르지 않는다.

- policy clause와 exception
- numbered procedure step + 조건/경고
- FAQ question-answer pair
- table header + row group
- figure + caption + explicit reference paragraph
- code block/formula block
- contract definition과 정의 대상
- list item과 해당 nested list

페이지 경계는 hard boundary가 아니다.

## X3.3 Atomic unit types

```text
PARAGRAPH
CLAUSE
PROCEDURE_STEP
LIST_GROUP
TABLE_HEADER
TABLE_ROW_GROUP
FIGURE_PACKAGE
FORMULA_PACKAGE
CODE_BLOCK
KEY_VALUE_GROUP
```

## X3.4 Bootstrap package profiles

```yaml
chunk_profiles:
  SEARCH_BALANCED:
    target_tokens: 700
    min_tokens: 180
    max_tokens: 1200
    max_units: 24
    preserve_hard_boundary: true
  LEGAL_POLICY:
    target_tokens: 900
    min_tokens: 220
    max_tokens: 1600
    preserve_clause_exception: true
  TECHNICAL_MANUAL:
    target_tokens: 650
    min_tokens: 160
    max_tokens: 1300
    preserve_procedure_warning: true
  TABLE:
    max_rows_per_chunk: 40
    repeat_header_context: true
```

숫자는 bootstrap이며 retrieval QA로 조정한다.

## X3.5 Grouping algorithm

```python
def build_chunks(units, profile, tokenizer):
    chunks = []
    current = []
    for unit in units:
        if violates_hard_boundary(current, unit):
            flush(current, chunks)
            current = []
        candidate = current + [unit]
        if token_count(candidate, tokenizer) > profile.max_tokens:
            if current:
                flush(current, chunks)
                current = [unit]
            else:
                current = split_large_unit_semantically(unit, profile)
        else:
            current = candidate
    flush(current, chunks)
    return attach_parent_context_and_evidence(chunks)
```

`split_large_unit_semantically`도 raw fixed-token split을 마지막 fallback으로만 사용한다.

## X3.6 Hierarchical package

```yaml
knowledge_chunk:
  chunk_id: chk_...
  chunk_version_id: chkv_...
  unit_version_ids: [...]
  parent_section_id: ku_...
  heading_path: [Warranty, Coverage, Exceptions]
  display_content: ...
  embedding_content: ...
  token_count: 734
  evidence_ids: [...]
  permission_scope: [...]
  valid_time: ...
  authority_context: ...
  chunker_version: structure_chunker_v3
```

## X3.7 Stable chunk identity

```text
chunk_logical_id = hash(
  workspace + chunk_profile + ordered_logical_unit_ids + parent_logical_id
)
```

content가 바뀌면 version ID만 바뀌고 logical identity는 가능한 한 유지한다.

## X3.8 Summaries와 enrichment

- table/figure summary는 검색 recall 보조용 derived artifact다.
- summary에는 생성 model/prompt/evidence/epistemic status를 붙인다.
- source 숫자/조건과 불일치하면 inspector fail.
- answer display에는 원문 content와 citation을 우선한다.

## X3.9 Evaluation

- chunk boundary correctness human-labeled sample
- retrieval Recall@5/10/20
- clause+exception 동시 retrieval
- procedure warning 누락률
- table header context accuracy
- chunk update blast radius
- fixed-token baseline 대비 quality/cost

Reducto/Docling 등도 block/structure-aware chunking을 제공하므로, TAVONEL 차별화는 chunking 자체가 아니라 **evidence·time·authority·permission·lineage가 보존된 stable chunk compilation**이다.

공식 참고:
- Reducto chunking: https://docs.reducto.ai/configs/parse/chunking-methods
- Docling supported chunk export: https://docling-project.github.io/docling/usage/supported_formats/

---

# X4. Office Document Dual Path — 구조와 시각을 동시에 보존

## X4.1 기본 원칙

DOCX/PPTX/XLSX는 텍스트 추출만으로 충분하지 않다. 두 경로를 병렬로 만든다.

```text
STRUCTURAL PATH
OOXML package → XML/relationship/style/chart/table/formula parse

VISUAL PATH
sandboxed LibreOffice headless render → PDF/page images → visual parser

RECONCILIATION
structural object ↔ rendered geometry/evidence
```

LibreOffice는 raw truth가 아니라 reference visual renderer다. version/container/filter를 pin한다.

## X4.2 LibreOffice sandbox

- fresh temporary user profile per job
- `--headless --norestore --nodefault --nolockcheck` 계열 검토
- macro/script 실행 금지
- outbound network deny
- external link update 금지
- wall-clock/RAM/CPU/process limit
- output directory 격리
- source file name shell interpolation 금지
- conversion log와 LibreOffice build ID 저장

## X4.3 DOCX

구조 path:

- paragraph/run/style
- numbering/list hierarchy
- heading outline
- table/merged cell
- footnote/endnote/comment
- hyperlink/external relationship
- image/alt text/caption
- section/page break/header/footer
- tracked changes 상태

visual path와 비교:

- reading order
- floating object/shape
- column layout
- page break
- caption proximity

tracked changes는 사용자 정책에 따라 `ACCEPTED_VIEW`, `REJECTED_VIEW`, `MARKUP_VIEW`를 명시하며 임의로 최종본 확정 금지.

## X4.4 PPTX

- slide order, section, title/body placeholder
- shape geometry/z-order/group
- speaker notes
- tables, SmartArt fallback, images, alt text
- chart relationship와 embedded workbook
- hidden slide 상태
- animation은 실행하지 않고 metadata만 기록

reading order는 XML tree만 믿지 않고 placeholder semantic role + geometry + z-order를 결합한다.

## X4.5 XLSX

- workbook/sheet visibility
- cell raw value, cached value, formula, number format
- merged cells, named ranges, tables, filters
- row/column hidden state
- comments/notes/hyperlinks
- chart series/source range
- external links/pivots/macros 존재 표시

formula는 실행하지 않는다. `formula`, `cached_value`, `calculation_mode`, `last_calculated_at_if_known`을 분리한다.

large worksheet는 used range만 맹신하지 않고 non-empty/style/merged/table/chart ranges를 profile한다.

## X4.6 Chart extraction

```yaml
chart_evidence:
  chart_type: line
  title: ...
  series:
    - name: Revenue
      category_range: Sheet1!A2:A13
      value_range: Sheet1!B2:B13
      cached_values: [...]
  visual_bbox: ...
  source_relationship_ids: [...]
```

chart source data가 없으면 visual figure로 처리하고 수치를 hallucinate하지 않는다.

## X4.7 Legacy DOC/XLS/PPT

legacy binary Office는 launch에서 별도 route class다.

- sandboxed LibreOffice conversion
- conversion artifact와 warning 보존
- high-risk VERIFIED mode에서는 source fidelity review
- unsupported object가 발견되면 partial/blocked 명시

## X4.8 Dual-path disagreement

구조 path에는 text가 있는데 visual render에서 보이지 않음:
- hidden text, tracked deletion, off-slide object, formula metadata 가능
- 무조건 노출하지 않고 visibility state를 적용

visual에는 보이는데 structure path에서 누락:
- drawing/textbox/embedded object 가능
- visual parser/recovery로 승격

## X4.9 Acceptance

- Office gold fixtures: columns, floating shapes, merged tables, hidden slides, formulas, charts
- structure↔visual evidence alignment
- macro/external link 실행 0
- conversion hang/OOM bounded
- original source hash와 render lineage 100%

공식 참고:
- LibreOffice headless conversion: https://wiki.documentfoundation.org/Faq/General/150
- Docling format coverage/reference model: https://docling-project.github.io/docling/usage/supported_formats/

---

# X5. Document Identity · Dedup · Revision Graph · Cross-Document Linking

## X5.1 Document-level identity tiers

```text
T0 exact bytes
T1 normalized container/content
T2 same source lineage revision
T3 near duplicate
T4 derivative/quoted subset
T5 unrelated
```

## X5.2 Fingerprints

```yaml
document_fingerprint:
  content_sha256: ...
  normalized_text_sha256: ...
  structure_hash: ...
  page_perceptual_hashes: [...]
  minhash_signature: [...]
  heading_signature: [...]
  table_signature: [...]
  connector_native_id: ...
  connector_revision_id: ...
```

## X5.3 Exact dedup

- 동일 tenant/workspace + content hash: 동일 document version 재사용
- 다른 source path에서 같은 hash: source alias를 추가하되 source ownership/history는 보존
- tenant 간 dedup storage optimization은 암호화/보안 경계 때문에 초기 금지

## X5.4 Near-duplicate candidate generation

- normalized text MinHash/LSH
- heading/section fingerprint
- page perceptual hash overlap
- connector path/name/time signal
- source lineage

전 corpus all-pairs 금지.

Bootstrap candidate threshold:

```yaml
near_duplicate:
  min_text_jaccard_estimate: 0.85
  min_page_hash_overlap: 0.70
  min_structure_similarity: 0.80
```

자동 동일본 확정 임계값이 아니라 candidate 생성값이다.

## X5.5 Revision graph

```text
Source
├ DocumentVersion v1
├ DocumentVersion v2 [derived_from v1]
├ DocumentVersion v3 [supersedes v2]
└ Branch v2-customerA [scope-specific override]
```

버전은 항상 선형이라고 가정하지 않는다. branch/merge/conflicting draft가 가능하다.

## X5.6 File name policy

`final`, `최종`, `real`, 날짜 문자열은 signal일 뿐 authority/version truth가 아니다.

## X5.7 Cross-document reference resolver

candidate signals:

- explicit filename/path/URL/ID
- section/table/figure identifier
- citation title/author/date
- connector native link
- semantic candidate

resolution states:

```text
RESOLVED_EXACT
RESOLVED_ALIAS
CANDIDATE
AMBIGUOUS
MISSING
FORBIDDEN_PERMISSION
```

permission이 없어 보이지 않는 target을 `MISSING`이라고 누설하지 않는다.

## X5.8 Merge policy

- duplicate source를 지우기보다 canonical + aliases
- source deletion과 knowledge version deletion 분리
- near duplicate는 human review/explicit policy
- merge/split reversible

## X5.9 Acceptance

- rename/move/copy/version branch fixtures
- same filename different content
- different filename same bytes
- near duplicate with one exception clause
- permission-hidden reference
- no silent source loss

---

# X6. Connector Change Capture & ACL Synchronization

## X6.1 Connector contract

```python
class Connector(Protocol):
    async def discover(self, cursor: Cursor | None) -> ChangePage: ...
    async def fetch_metadata(self, ref: NativeRef) -> SourceMetadata: ...
    async def fetch_content(self, ref: NativeRef, revision: str) -> ByteStream: ...
    async def fetch_permissions(self, ref: NativeRef, revision: str) -> ACLSnapshot: ...
    async def resolve_identity(self, ref: NativeRef) -> ConnectorIdentity: ...
    async def checkpoint(self, cursor: Cursor) -> None: ...
```

## X6.2 Change types

```text
CREATED
CONTENT_UPDATED
METADATA_UPDATED
RENAMED
MOVED
PERMISSION_UPDATED
DELETED
RESTORED
UNKNOWN_RESCAN_REQUIRED
```

## X6.3 Cursor/transaction rule

connector cursor를 source change가 durable DB/outbox에 기록되기 전에 advance하지 않는다.

```text
fetch change page
→ transaction: upsert source event + outbox + proposed cursor
→ commit
→ cursor acknowledged
```

## X6.4 Webhook + polling

- webhook은 low-latency hint
- polling/reconciliation은 completeness guarantee
- webhook duplicate/reorder 정상 처리
- periodic full inventory hash/revision reconciliation

## X6.5 Permission drift

source permission 변경은 content hash가 같아도 새로운 governance version이다.

```text
ACL change
→ permission graph diff
→ affected chunk/context cache invalidation
→ retrieval authorization re-test
→ world state publish
```

권한이 취소된 source는 새 request에서 즉시 차단해야 하며 background recompile 완료까지 기다리지 않는다. emergency deny-list/authorization source를 control plane에서 적용한다.

## X6.6 Initial connector order

1. Manual upload/folder ZIP
2. Git repository/directory
3. Google Drive 또는 SharePoint 중 실제 pilot이 요구하는 하나
4. 나머지는 paid demand 후

50개 connector를 미리 만들지 않는다.

## X6.7 Connector test kit

모든 connector adapter가 동일 contract test를 통과한다.

- duplicate event
- rename/move
- late old revision
- ACL revoke/grant
- delete/restore
- rate limit
- cursor expiration
- partial listing
- content stream interruption

## X6.8 External link policy

connector document 안의 external URL을 자동 fetch하지 않는다. 명시적으로 등록된 connector/source만 ingestion scope에 들어간다.

---

# X7. Multi-Tenant Scheduler · Backpressure · GPU Model Residency

## X7.1 Scheduler goals

- 한 대형 tenant가 전체 queue를 독점하지 않는다.
- cheap pages와 difficult pages를 같은 queue에 묶지 않는다.
- GPU model reload를 최소화하되 sticky routing이 품질을 희생하지 않는다.
- queue delay가 RunPod TTL을 잠식하기 전에 backpressure한다.
- cost budget이 quality policy를 몰래 낮추지 않는다.

## X7.2 Stage queues

```text
preflight_cpu
profile_cpu
parse_native_cpu
parse_champion_gpu
parse_challenger_gpu
verify_gpu
reconcile_cpu_gpu
compile_cpu
embedding_gpu
review_human
```

## X7.3 Job envelope

```yaml
scheduled_job:
  job_id: ...
  tenant_id: ...
  workspace_id: ...
  stage: parse_champion_gpu
  priority_class: INTERACTIVE | STANDARD | BATCH | SHADOW
  quality_mode: BALANCED
  deadline_at: ...
  estimated_gpu_seconds: 18.2
  estimated_vram_mb: 12400
  model_residency_key: mineru_3_4_4
  cost_budget_remaining: ...
  attempt: 0
  created_at: ...
```

## X7.4 Weighted fair scheduling

tenant별 deficit round robin 또는 weighted fair queue를 구현한다.

```text
quantum(tenant) = plan_weight × fairness_base
cost(job) = estimated_gpu_seconds × complexity_multiplier
```

interactive job에는 latency boost를 주되 batch starvation을 방지하는 aging을 적용한다.

## X7.5 Backpressure

- queue backlog/oldest age/cold-start p95/TTL budget 감시
- accepted work가 capacity를 넘으면 upload는 받을 수 있지만 정확한 queued state/estimate 제공
- hard saturation에서는 429/plan limit 또는 scheduled batch로 전환
- infinite queue promise 금지

## X7.6 VRAM estimator

```text
estimated_vram = model_weights
               + kv_or_activation(profile, batch)
               + renderer/image tensors
               + safety_margin
```

parser registry에 hardware profile별 measured peak를 저장한다.

## X7.7 Dynamic batching

- 동일 model/config/compatible image size bucket만 batch
- max wait window를 interactive/batch별 분리
- 한 oversized page가 batch 전체 OOM을 만들지 않게 isolate
- OOM 발생 시 batch bisect → lower concurrency → alternate worker
- 동일 OOM signature 반복 시 circuit breaker

## X7.8 Model residency

```text
residency_score = queued_work_seconds - reload_cost - idle_cost
```

hot pool은 telemetry 기반으로 조정한다. Network Volume/cache miss가 있어도 R2 artifact truth는 유지한다.

## X7.9 Deadline-aware recovery

recovery action 선택 전에 남은 deadline/TTL을 계산한다.

```python
if now + expected_action_p95 + commit_margin > deadline:
    return PartialOrFailClosed("INSUFFICIENT_TTL")
```

## X7.10 Acceptance

- noisy-neighbor test
- batch starvation test
- OOM/batch bisect test
- model cache eviction test
- TTL queue delay test
- cost budget hard stop
- p95 queue delay by plan/priority

Cloudflare Queues는 at-least-once delivery이며 pull consumer visibility timeout 이후 재전달될 수 있으므로 scheduler/inbox는 멱등해야 한다.

공식 참고:
- Cloudflare delivery: https://developers.cloudflare.com/queues/reference/delivery-guarantees/
- Pull consumers: https://developers.cloudflare.com/queues/configuration/pull-consumers/
- RunPod TTL: https://docs.runpod.io/serverless/endpoints/endpoint-configurations

---

# X8. End-to-End Search · Answer · Citation Evaluation

## X8.1 세 층을 분리

```text
Extraction fidelity
Retrieval/context fidelity
Answer/action fidelity
```

OCR가 맞아도 Retrieval/Authority가 틀리면 최종 실패다.

## X8.2 Retrieval ground truth

질문마다:

```yaml
qa_case:
  query: "Customer A의 현재 보증기간은?"
  principal: sales_user
  as_of: 2026-08-10
  known_at: 2026-08-10
  applicable_evidence_ids: [ev_contract_customerA]
  forbidden_evidence_ids: [ev_hr_private]
  conflicting_candidates: [...]
  expected_status: ANSWERABLE
```

## X8.3 Retrieval metrics

- Recall@k
- Precision@k
- MRR/nDCG
- authoritative evidence recall
- forbidden retrieval count
- stale evidence retrieval count
- conflict set completeness
- cross-document multi-hop recall

## X8.4 Answer metrics

- exact/semantic correctness
- condition/exception completeness
- temporal correctness
- authority/applicability correctness
- abstention correctness
- contradiction rate
- unsupported claim rate
- citation entailment
- citation completeness

## X8.5 Citation faithfulness

각 answer sentence/claim을 evidence span에 align한다.

```text
answer claim
→ supporting evidence candidate
→ entailment/lexical/numeric check
→ supported | partially_supported | unsupported | contradicted
```

numeric/date/modal word는 deterministic verifier를 우선한다.

## X8.6 LLM-as-judge 제한

- human-labeled calibration set 필요
- judge model/version/prompt 공개 내부 기록
- answer generator와 같은 model 단독 judge 금지
- judge disagreement/uncertainty 보존
- public claim은 official evaluator 또는 human audit와 함께

## X8.7 Online shadow evaluation

customer opt-in이 있을 때 production query를 de-identified shadow replay한다.

- 현재 pipeline vs challenger
- user-visible output은 champion만
- raw customer content training 기본 금지
- error sample은 access-controlled review queue

## X8.8 Agent action evaluation

write/action 전:

- selected evidence
- permission
- policy constraint
- dry-run impact
- expected side effect

을 fixture로 검증한다. answer benchmark 통과가 action safety를 의미하지 않는다.

## X8.9 Launch blockers

- cross-tenant/forbidden evidence retrieval 0
- high-risk QA unsupported claim 0 목표 on controlled fixtures
- unresolved authority conflict를 단일 답으로 반환 0
- stale world state silent response 0
- citation points to nonexistent evidence 0

---

# X9. Deterministic Blueprint Compiler & Export Contracts

## X9.1 One compiled core

```text
Canonical IR + World State
├ Markdown
├ Obsidian vault
├ RAG package
├ Ontology JSON/OWL-like adapter
├ Neo4j CSV/Cypher package
├ API/MCP resources
└ Evidence bundle
```

각 exporter가 parser raw output을 다시 해석하지 않는다.

## X9.2 Compile manifest

```yaml
compile_manifest:
  compile_run_id: cr_...
  world_state_id: ws_...
  compiler_version: ...
  blueprint_id: technical_docs_v2
  input_unit_versions: [...]
  output_artifacts:
    - type: OBSIDIAN
      object_key: ...
      sha256: ...
  unresolved_links: []
  refused_items: []
  validation_receipt_id: ...
```

## X9.3 Markdown

- heading hierarchy deterministic
- tables: HTML/Markdown 선택을 blueprint에 pin
- evidence comments/frontmatter optional
- source links stable URI
- generated summaries 명시
- same input/version → byte-identical target where deterministic

## X9.4 Obsidian

- safe filename normalization
- collision policy
- relative link resolution
- attachment copy/reference policy
- YAML frontmatter schema
- orphan/broken link fail-closed

## X9.5 RAG package

```json
{
  "chunk_id": "...",
  "content": "...",
  "embedding_content": "...",
  "metadata": {
    "world_state_id": "...",
    "evidence_ids": ["..."],
    "valid_time": "...",
    "authority": "...",
    "permission_scope": ["..."]
  }
}
```

## X9.6 Ontology/Neo4j

- entity/relation type registry
- deterministic IDs
- evidence/temporal properties
- edge validity
- no unresolved entity silently emitted
- schema version and import instructions

## X9.7 Blueprint compatibility

blueprint change도 compiler change다.

- blueprint version
- migration notes
- regression fixture
- output diff
- old consumer compatibility

## X9.8 Refusal as product behavior

broken source/evidence/link를 만나면:

```text
COMPILED
PARTIAL_WITH_EXPLICIT_REFUSALS
BLOCKED
```

중 하나를 반환한다. silent file loss 금지.

---

# X10. Public API · Streaming · Webhooks · SDK

## X10.1 Versioning

- REST path `/v1`
- OpenAPI contract source of truth
- additive backward-compatible change만 v1 내 허용
- breaking change는 new major + migration window

## X10.2 Long-running job pattern

```text
POST /v1/jobs
→ 202 Accepted
→ job_id/status_url/events_url
```

## X10.3 Progress

- primary: Server-Sent Events
- fallback: polling with ETag/If-None-Match
- WebSocket은 bidirectional 필요가 검증될 때만
- progress는 실제 stage/counter, fake percentage 금지

SSE event:

```yaml
event: job.stage.updated
data:
  job_id: ...
  stage: RECOVERING
  completed_items: 71
  total_items: 83
  world_state_candidate_id: ...
```

## X10.4 Webhooks

- HMAC signature + timestamp
- replay window
- event ID/idempotency
- exponential retry + DLQ
- customer endpoint failure가 core publish를 롤백하지 않음
- webhook payload에 presigned source URL/PII 최소화

## X10.5 Idempotency

모든 create/write endpoint:

```text
Idempotency-Key
request body hash
principal/tenant scope
expiry
stored response reference
```

같은 key 다른 body는 409.

## X10.6 Pagination

cursor-based, stable sort key. offset pagination은 large mutable collection 기본값으로 사용하지 않는다.

## X10.7 Large output

큰 result는 short-lived signed R2 URL + checksum/manifest. API가 수백 MB JSON을 inline으로 반환하지 않는다.

## X10.8 Cancellation

- best-effort cancel request
- running GPU job cancellation signal
- already committed immutable artifact는 orphan GC policy
- published world state는 cancel 대상 아님, rollback 사용

## X10.9 Rate limit

- principal, tenant, endpoint, compute budget별
- 429 + `Retry-After`
- abuse/upload bomb 별도 security limit

## X10.10 SDK

OpenAPI에서 TypeScript/Python client를 생성하고 handwritten wrapper는 ergonomic layer만 담당한다. SDK version과 API compatibility matrix를 유지한다.

---

# X11. Credits · Billing · Unit Economics

## X11.1 원가 단위와 고객 value metric 분리

내부에는 `Compute Work Unit(CWU)`을 사용한다.

```text
CWU = cpu_seconds*w_cpu
    + gpu_seconds_by_class*w_gpu
    + model_api_cost_normalized
    + storage/egress operations
    + recovery multiplier
```

고객에게 raw GPU cost를 노출하지 않는다.

## X11.2 Usage ledger

```yaml
usage_entry:
  usage_id: ...
  tenant_id: ...
  job_id: ...
  stage: PARSE
  route_class: R5_DEGRADED
  recovery_level: 3
  pages: 12
  cwu_estimated: 40
  cwu_actual: 47
  billable_credits: 50
  pricing_version: pricing_v1
  created_at: ...
```

append-only ledger + correction entry. 과거 row update 금지.

## X11.3 Estimate → authorize → reconcile

1. preflight estimate
2. credit/budget reservation
3. processing
4. actual usage reconciliation
5. unused reserve release
6. failure/refusal policy에 따른 billable calculation

## X11.4 Failure billing

- provider/system failure로 결과 없음: 고객 과금 금지 또는 자동 credit restore
- customer-corrupt/unsupported source: preflight 이후 heavy work 전에 명확히 중단
- recovery 성공: plan/mode 정의에 따라 포함 또는 추가 credit
- human review: 별도 value tier

정책을 가격 페이지에 명확히 쓴다.

## X11.5 Product pricing

외부 가격은 page 하나로 제품을 축소하지 않게:

```text
workspace / managed knowledge volume
+ initial compile volume
+ change/recompile volume
+ history/retention
+ connectors/API/MCP
+ SLA/governance
```

를 조합한다.

## X11.6 Margin dashboard

- revenue/CWU
- GPU/provider/model API cost
- recovery cost by failure code
- gross margin by plan/tenant
- p95 expensive jobs
- free Health Scan conversion/payback

## X11.7 Abuse protection

- free account identity/rate limit
- file/page/expanded-byte quotas
- repeated duplicate scans dedup
- crypto/mining/arbitrary GPU workload 불가
- cost anomaly auto-pause

---

# X12. Human Review · Feedback · Active Learning

## X12.1 Review label is provenance

```yaml
review_decision:
  review_id: ...
  task_type: ENTITY_MERGE
  candidate_refs: [...]
  decision: REJECT_MERGE
  evidence_ids: [...]
  reason_code: SAME_NAME_DIFFERENT_PERSON
  free_text_note: ...
  reviewer_id: ...
  reviewer_role: ...
  policy_version: ...
  decided_at: ...
```

## X12.2 Two-reviewer policy

high-risk authority/contract/person merge 또는 benchmark gold label은:

- independent 2 reviewers
- disagreement adjudication
- inter-annotator agreement 측정

1인 founder 초기에는 AI reviewer + founder adjudication이 가능하지만, AI끼리 합의했다고 gold truth로 보지 않는다.

## X12.3 Customer data training

기본값:

```text
customer_data_training = OFF
```

제품 개선 학습은 별도 explicit consent, retention, isolation, deletion policy가 있을 때만.

## X12.4 Active learning

production random exploration 금지. offline candidate selection:

- high uncertainty
- high impact
- high disagreement
- new/OOD route class
- recurring customer correction

review label로 router/inspector candidate를 재학습하고 shadow promotion gate를 거친다.

## X12.5 Review load control

- expected business impact × uncertainty × recurrence로 priority
- 같은 underlying conflict를 여러 번 review하지 않게 canonical review item
- SLA/aging
- resolved decision invalidation when source changes

## X12.6 Reviewer quality

- gold-check agreement
- overturn rate
- latency
- domain scope
- conflict of interest/audit

---

# X13. Zero-Downtime Schema · Model · Runtime Release

## X13.1 Database expand-migrate-contract

```text
EXPAND
add nullable/new tables/index concurrently

MIGRATE
backfill in bounded batches with checkpoint
optional dual-write/dual-read compare

CUTOVER
feature flag/pointer switch

CONTRACT
remove old path only after rollback window
```

## X13.2 Migration rules

- long table rewrite/lock 사전 측정
- `CREATE INDEX CONCURRENTLY` 등 managed Postgres 제약 검토
- migration timeout/lock timeout
- backfill idempotent cursor
- row count/hash/sample compare
- single migration head
- downgrade/forward-fix strategy 문서화

## X13.3 Schema registry

API/IR/event/receipt schema는 compatibility test를 가진다.

- producer new / consumer old
- producer old / consumer new
- unknown enum handling
- required field change 금지 within major

## X13.4 Feature flags

- tenant/workspace cohort
- shadow mode
- read path/writer path 분리
- emergency kill switch
- flag state도 audit/versioning

## X13.5 Model release train

```text
REGISTER
→ LICENSE/SBOM/SIGNATURE
→ OFFLINE BENCHMARK
→ SHADOW
→ CANARY TENANTS/INTERNAL
→ PROMOTE
→ OBSERVE
→ RETIRE AFTER REPROCESS/COMPAT WINDOW
```

## X13.6 Dual-world comparison

new compiler/model은 candidate world state를 만들고 current와 diff/QA를 비교한다. 바로 current pointer를 덮지 않는다.

## X13.7 Rollback

- code deploy rollback
- model registry promotion rollback
- world-state pointer rollback
- embedding index pointer rollback
- schema rollback 또는 forward-fix

각각 별도 runbook.

---

# X14. 2026 Competitive Reality — Vendor Claims를 같은 조건으로 읽기

## X14.1 현재 확인 가능한 vendor-reported facts

| Product | Vendor가 공개한 방향/수치 | TAVONEL이 해석할 때의 주의 |
|---|---|---|
| Mistral OCR 4 | bbox, block type, inline confidence, 170 languages, vendor-reported OlmOCRBench 85.20, API $4/1,000 pages, batch $2/1,000 | vendor benchmark/human preference; TAVONEL 동일 corpus 재현 필요 |
| PaddleOCR-VL-1.6 | 0.9B, vendor-reported OmniDocBench v1.6 96.3%, text/formula/table/chart enhancements | benchmark version/metric이 TAVONEL 80.6 olmOCR와 다름; 직접 숫자 비교 금지 |
| Reducto | classify/route/parse/extract/split/edit, specialized/agentic multipass, bbox citations, standard $0.015/credit with operation-dependent credits | production pipeline 강자; raw OCR가 아니라 workflow/UX/enterprise 경쟁 |
| Unstructured | auto/fast/hi_res/ocr_only/vlm adaptive strategies; fast vs high-resolution trade-off | router/adaptive execution이 이미 category expectation |
| Docling | many formats, unified representation, local execution, staged layout/table/OCR/VLM pipeline, chunk exports | 오픈소스 구성요소/benchmark challenger로 검토 가능 |

이 표는 2026-08-10 기준 vendor 공식 자료 요약이며, 가격·모델·benchmark는 launch/발행 직전 재검증한다.

## X14.2 경쟁사가 빨라 보이는 이유를 검증하는 체크리스트

- cached demo 여부
- sync vs async/batch
- first preview vs complete verified latency
- clean digital vs degraded scan
- single page vs multi-page reconciliation
- retries/agentic correction 포함 여부
- structural JSON vs display Markdown만
- human review 포함 여부
- response size/result URL 처리
- pricing mode/credit multiplier
- unsupported/failed document denominator

## X14.3 TAVONEL의 대응

TAVONEL은 “모든 parser보다 OCR가 높다”를 기본 positioning으로 삼지 않는다.

```text
Fast path on easy pages
Deep path on hard pages
Detect silent corruption
Recover by failure class
Preserve evidence and structure
Resolve version/time/authority
Trace change blast radius
Recompile only affected knowledge
```

## X14.4 Competitive benchmark report 형식

```yaml
competitive_run:
  vendor: mistral_ocr_4
  accessed_at: ...
  model_or_mode: ...
  pricing_snapshot: ...
  source_manifest_hash: ...
  retry_timeout_policy: ...
  preprocessing: ...
  results:
    completion: ...
    text: ...
    table: ...
    cross_page: ...
    p50_ms: ...
    p95_ms: ...
    cost: ...
  limitations: [...]
```

## X14.5 Strategic wedge

- Mistral/Paddle/Reducto가 parsing 성능을 높일수록 TAVONEL router는 더 좋은 부품을 사용할 수 있다.
- TAVONEL moat는 model lock-in이 아니라 `model arbitration + recovery + knowledge integrity + change intelligence`다.
- 경쟁사 parser를 paid fallback/challenger로 사용할 수 있어도 TAVONEL IR/lineage/world state는 유지한다.

공식 참고:
- Mistral OCR 4: https://mistral.ai/news/ocr-4/
- PaddleOCR-VL: https://paddlepaddle.github.io/PaddleOCR/main/en/version3.x/pipeline_usage/PaddleOCR-VL.html
- Reducto: https://docs.reducto.ai/overview
- Reducto pricing: https://reducto.ai/pricing
- Unstructured strategies: https://docs.unstructured.io/api-reference/legacy-api/partition/partitioning
- Docling: https://docling-project.github.io/docling/

---

# X15. GTM Execution System — 기술을 실제 매출로 전환

## X15.1 Initial ICP

첫 ICP를 넓게 “문서가 많은 기업”으로 잡지 않는다.

```text
문서가 자주 바뀐다
+ 틀린 답이 support/매출/compliance 비용을 만든다
+ 현재 RAG/AI를 이미 시도 중이다
+ source of truth가 여러 곳이다
+ evidence/최신성 문제를 직접 느낀다
```

초기 우선:

1. Technical documentation / customer support
2. Manufacturing equipment manuals/service bulletins
3. Policy/compliance knowledge

## X15.2 Pilot input contract

- 100–5,000 documents 정도의 좁은 corpus
- 대표 질문 30–100개
- 최근 변경 사례 5–20개
- source authority/ACL 담당자
- 성공 기준과 보안 범위

## X15.3 Pilot baseline

pilot 전에 측정:

- outdated answer rate
- conflicting answer rate
- unsupported citation rate
- manual update time
- full reindex/reprocess time/cost
- user trust/verification time

baseline 없이 “개선” 주장 금지.

## X15.4 Pilot demo sequence

```text
1. 자기 문서 Health Scan
2. 실제 충돌/구버전/evidence finding
3. 대표 질문에 source-grounded answer
4. source 한 곳 변경
5. semantic diff/impact path
6. affected-only recompile
7. updated answer + old world-state replay
```

## X15.5 Conversion offer

```text
Free/low-cost Health Scan
→ paid one-time compile/pilot
→ scheduled/connector continuous sync
→ temporal/impact/MCP
→ enterprise governance/SLA
```

## X15.6 12주 launch experiment cadence

### Weeks 1–2
- ICP 15명 인터뷰
- Health Scan problem wording 검증
- landing message 2개

### Weeks 3–4
- design partner 2–3곳
- corpus/pilot contract
- baseline QA 작성

### Weeks 5–8
- pilot execution
- weekly evidence report
- product friction log

### Weeks 9–10
- before/after receipt
- pricing/WTP interview
- case-study permission

### Weeks 11–12
- paid conversion
- second vertical 여부 결정
- only evidence-backed public launch

## X15.7 Funnel metrics

```text
Gracian episode view
→ profile/site CTR
→ Evidence/Research view
→ Health Scan start
→ upload complete
→ report viewed
→ finding opened
→ compile/pilot CTA
→ sales call
→ pilot started
→ pilot paid
→ continuous sync activated
```

Vanity view보다 `report_view → pilot` 전환을 본다.

## X15.8 Gracian Code content map

- broad human/AI insight: reach
- context/ontology/time/provenance: problem education
- recovery benchmark: engineering credibility
- change→impact→recompile: category creation
- case study: purchase confidence

제품 언급 비율은 계정 신뢰를 훼손하지 않게 유지하되, Knowledge Arc 이후에는 명확한 TAVONEL proof episode를 숨기지 않는다.

## X15.9 Weekly GTM experiment receipt

```yaml
gtm_experiment:
  hypothesis: "See what your AI would get wrong가 Start Free보다 scan start를 높인다"
  audience: technical_support_leads
  variant: ...
  metric: health_scan_start_rate
  sample: ...
  result: ...
  confounders: ...
  decision: KEEP | REJECT | RETEST
```

## X15.10 Sales truth rules

- 없는 certification/SLA/connector를 roadmap처럼 현재형 표현 금지
- benchmark completion과 accuracy 혼동 금지
- vendor 비교는 동일 조건 receipt가 있을 때만
- customer result는 고객 허락과 methodology 포함
- low-quality scan 약점 공개

---

# X16. Solo-Founder Critical Path — “모든 것”을 만들되 순서를 지킨다

## X16.1 첫 유료 pilot까지 반드시 필요한 vertical slice

```text
Secure Upload
→ Preflight
→ Existing MinerU + Recovery
→ Canonical IR/evidence
→ Version/semantic diff
→ Impact preview
→ affected-only compile/export
→ Health Scan report
→ basic account/billing/pilot workflow
```

다음은 pilot 전 blocker가 아니다.

- 50 connectors
- write MCP
- full autonomous agent runtime
- Neo4j
- complete simulation
- every industry blueprint
- SOC 2/ISO certification 완료

## X16.2 Demo의 세 장면

1. Documents → structured/evidence-backed knowledge
2. `2 years → 3 years` → exact blast radius
3. Recompile affected knowledge → synchronized world state

이 세 장면이 실제 backend와 연결되지 않으면 launch demo로 인정하지 않는다.

## X16.3 Founder time allocation

AI가 맡김:

- code generation
- test/fixture generation
- benchmark automation
- screenshot/visual QA first pass
- docs/receipt updates
- competitor documentation tracking

Founder가 유지:

- North Star/scope
- pilot/customer interview
- business truth/authority conflict
- final brand taste
- legal/claim approval

## X16.4 AI completion illusion 방지

Claude report에 다음이 없으면 done 아님.

```text
commit
changed files
acceptance tests
benchmark receipt
security result
screenshots if UI
known limitations
rollback
claim changes
```

## X16.5 Resource ceiling

- one primary DB
- one object store
- one queue family
- one GPU provider adapter launch
- one default embedding/reranker pair
- one or two vertical blueprints
- one connector after upload/Git

복잡도는 customer evidence가 있을 때만 늘린다.

---

# X17. v3.1 Final Closure Matrix

| Capability | Method fixed? | Required proof |
|---|---:|---|
| Open-weight semantic model use | Yes | task-level benchmark/schema/evidence |
| Embedding/reranking | Yes | retrieval QA + latency/cost |
| Structure-aware chunking | Yes | boundary/retrieval fixtures |
| Office structure + visual fidelity | Yes | dual-path gold corpus |
| Dedup/version graph | Yes | rename/copy/branch fixtures |
| Connector/ACL sync | Yes | contract/permission drift tests |
| Multi-tenant GPU scheduling | Yes | fairness/OOM/TTL chaos |
| Search/answer/citation accuracy | Yes | end-to-end QA corpus |
| Exports/blueprints | Yes | deterministic manifest/link integrity |
| API/stream/webhooks | Yes | OpenAPI/idempotency/replay tests |
| Credits/billing | Yes | append-only ledger/reconciliation |
| Human review learning | Yes | provenance/consent/adjudication |
| Zero-downtime upgrade | Yes | expand-migrate-contract/canary/rollback |
| Competitive truth | Yes | same-condition receipts |
| GTM/pilot conversion | Yes | baseline/pilot/experiment receipts |

## X17.1 최종 금지

- model benchmark를 product end-to-end accuracy로 표현
- generated summary를 original evidence로 표시
- source ACL revoke를 background reindex까지 허용
- fixed-token chunker 하나를 모든 문서에 적용
- Office native XML 또는 visual render 중 한쪽만 믿기
- queue order/exactly-once 가정
- one agent가 구현·검수·release 승인 모두 수행
- 마케팅을 product complete 이후로 미루기
- 근거 없는 “완벽”, “100%”, “가장 정확” claim

## X17.2 v3.1 Source additions

- Qwen3: https://qwenlm.github.io/blog/qwen3/
- Qwen3 Embedding/Reranker: https://qwenlm.github.io/blog/qwen3-embedding/
- Qwen3-VL Embedding: https://github.com/QwenLM/Qwen3-VL-Embedding
- LibreOffice conversion: https://wiki.documentfoundation.org/Faq/General/150
- Docling formats/model: https://docling-project.github.io/docling/
- Reducto parse/chunking/pricing: https://docs.reducto.ai/parse/overview , https://docs.reducto.ai/configs/parse/chunking-methods , https://reducto.ai/pricing
- Unstructured adaptive strategies: https://docs.unstructured.io/api-reference/legacy-api/partition/partitioning
- Mistral OCR 4: https://mistral.ai/news/ocr-4/
- PaddleOCR-VL: https://paddlepaddle.github.io/PaddleOCR/main/en/version3.x/pipeline_usage/PaddleOCR-VL.html
- Cloudflare Queues: https://developers.cloudflare.com/queues/reference/delivery-guarantees/
- RunPod endpoint TTL: https://docs.runpod.io/serverless/endpoints/endpoint-configurations

---


# PART C — PRODUCT / WEBSITE / GTM CANON PRESERVED FROM v1.0

> 아래 Part는 기존 v1.0에서 상세 설계된 Product UX, Health Scan, Brand, Cinematic Website, Pricing, GTM, Gracian Code funnel을 보존한다. 기술 상태나 claim이 PART B의 evidence gate를 통과하지 못하면 UI/마케팅에서 미래 기능을 현재 기능처럼 표현하지 않는다.

# 20. 제품 UX — 핵심 Surface

## 20.1 Workspace Overview

- Knowledge Health
- source count
- version conflicts
- unresolved evidence
- stale artifacts
- recovery events
- last synchronized

## 20.2 Ingest

사용자는:

```text
DROP EVERYTHING
PDF / PPTX / DOCX / XLSX / Images / Folder
```

하나의 영역에서 넣는다.

실시간:
- classify
- parse
- recover
- compile
- validate

## 20.3 Evidence Explorer

원본 ↔ Knowledge Unit ↔ Graph 연결.

## 20.4 Change Center

- changed sources
- semantic diff
- affected nodes
- pending recompilation

## 20.5 Timeline

- knowledge state over time
- policy version history
- as-of view

## 20.6 Graph

"예쁜 node graph"보다:
- cause/effect
- provenance
- impact
- time

에 집중.

## 20.7 Compile / Export

- AI-ready Markdown
- Obsidian
- RAG
- Ontology
- Neo4j
- API
- MCP

---

# 21. Knowledge Health Scan — 가장 중요한 Acquisition Product

일반 `Start Free` 대신:

> **See what your AI would get wrong.**

> **Run a Knowledge Health Scan.**

## 21.1 무료/저비용 입력

예:
- 20~100 documents
- limited pages/size
- local preview before full compile

## 21.2 결과

```text
83 files scanned

7 likely duplicates
4 version conflicts
9 broken references
3 operational recoveries
6 unresolved assets
8 potentially stale artifacts

Knowledge Health
72 / 100
```

## 21.3 Conversion

```text
Problem discovered
  ↓
Show evidence
  ↓
Show blast radius
  ↓
[ Compile this workspace ]
```

이것이 TAVONEL의 가장 중요한 PLG/lead-gen loop다.

---

# 22. Brand System

## 22.1 브랜드 역할

TAVONEL은 "AI magic company"가 아니다.

느낌:

> **Calm Intelligence + Precision + Evidence + Temporal Depth**

## 22.2 핵심 감정

- 신뢰
- 정교함
- 고급스러움
- 침착함
- 기술적 깊이
- 통제 가능성

## 22.3 금지 이미지

- glowing AI brain
- purple neon everywhere
- random particles
- 의미 없는 3D orb
- stock robot
- generic neural-network dots
- 과도한 glassmorphism
- 모든 텍스트 gradient
- "Powered by AI" 남발

## 22.4 Color philosophy

기본:
- warm graphite
- bone / ivory
- soft neutral grays

Accent:
- **하나의 strong signal color만 사용**
- 실제 state 변화에 의미 부여

예:
- normal → neutral
- verified → subtle
- changed → accent
- stale/critical → warning semantic color
- recompiled → restored state

최종 색상은 실제 accessibility contrast 테스트 후 확정.

## 22.5 Typography

- Main: high-quality sans
- Editorial statement: 제한적 serif 사용 가능
- 데이터/코드: mono

폰트 선택보다 hierarchy가 우선.

---

# 23. TAVONEL Website — 핵심 철학

## 23.1 웹사이트는 "설명서"가 아니다

TAVONEL 홈페이지는:

> **보는 순간 제품의 세계관을 이해하는 cinematic product experience**

여야 한다.

## 23.2 Show first, explain second

```text
Cinematic
  ↓
Short thesis
  ↓
Interactive proof
  ↓
Evidence
  ↓
User's own data
```

## 23.3 목표 반응

실패:
> "예쁜 사이트네."

성공:
> **"와. 내가 생각했던 문서 AI랑 완전히 다른데?"**

---

# 24. WOW Architecture

Threads의 구조를 웹으로 옮긴다.

```text
Strong hook
  ↓
Unexpected contradiction
  ↓
Visible mechanism
  ↓
Technical proof
  ↓
Intellectual insight
  ↓
Personal relevance
  ↓
Action
```

## WOW #1 — Thesis

Hero:

> **Your AI is only as reliable as the reality it sees.**

Sub:
> Compile fragmented organizational knowledge into trusted, temporal, traceable context.

## WOW #2 — Cinematic

사용자가 텍스트를 읽기 전에:

```text
Documents
  ↓
Structure
  ↓
Meaning
  ↓
Relationships
  ↓
Time
  ↓
Change
  ↓
Impact
  ↓
Recompile
```

를 본다.

## WOW #3 — Interactive product

사용자가 직접:

```text
2 years → 3 years
```

를 변경.

화면에서:
- impact pulse
- affected nodes
- stale state
- selective recompile

## WOW #4 — Insight

> **Your company is digital. Its meaning may not be.**

## WOW #5 — Evidence

> **Every claim has a receipt.**

실제 benchmark.

## WOW #6 — Personal

자기 문서를 올려 Health Scan 실행.

---

# 25. Cinematic Art Direction

## 25.1 목표

Luxury tech + enterprise trust.

명품스러움은 effect 수가 아니라:
- timing
- silence
- spacing
- material
- camera
- precision

에서 나온다.

## 25.2 전체 motion philosophy

### Motion must encode meaning.

예:
- 관계 생성 → line draw
- version change → time displacement
- stale state → controlled pulse
- recompile → local rearrangement
- verified → settle/lock

장식만 하는 animation 금지.

---

# 26. Hero Cinematic — 15초 Master Sequence

## Scene 0 — Stillness / 0–1.5s

화면:
- dark/warm neutral space
- 10~30 thin document planes
- 매우 느린 drift
- camera 거의 정지

텍스트:
> **Your AI is only as reliable as the reality it sees.**

느낌:
- 조용함
- 여백
- confidence

## Scene 1 — Source / 1.5–3.5s

문서 하나가 부드럽게 앞으로.

이름:
- warranty_final.pdf
- policy_v3.pdf
- price_2026.xlsx

한 문서가 열리며:
- page
- table
- heading
- clause

layer로 분리.

## Scene 2 — Structure / 3.5–5.5s

분리된 block들이 정렬.

line들이 관계를 만들기 시작.

Labels:
- Entity
- Policy
- Product
- Customer

## Scene 3 — Time / 5.5–7.5s

camera가 약 20~30° 회전.

Z/depth 축이 timeline으로 의미 전환.

```text
2024 — 2025 — 2026
```

동일 policy의 세 state가 공간에 겹쳐 보임.

## Scene 4 — Change / 7.5–9.5s

한 값:

```text
Warranty 2 years
```

가:

```text
3 years
```

로 변경.

변경은 과장된 explosion이 아니라 매우 선명한 state transition.

## Scene 5 — Impact / 9.5–11.5s

변경 node에서 dependency line을 따라 pulse.

오른쪽 작은 readout:

```text
12 documents
41 knowledge units
8 RAG chunks
2 agent workflows
affected
```

## Scene 6 — Recompile / 11.5–13.5s

affected subgraph만 움직이고 재정렬.

Unaffected graph는 정지.

이것이 **selective recompilation**을 시각적으로 설명한다.

Status:

> **Recompiling affected knowledge…**

→

> **Knowledge synchronized.**

## Scene 7 — Brand Lock / 13.5–15s

카메라 천천히 pull back.

graph/document elements가 완전한 logo를 만들 필요는 없다.
과한 logo gimmick 금지.

공간이 정돈된 상태에서:

**TAVONEL**
**The Knowledge Compiler**

CTA:
**Scan your knowledge →**

---

# 27. Hero Interaction

자동 재생 이후 사용자 제어 가능.

### Hover document
- 해당 source가 약간 전진
- related graph만 강조

### Click source
- evidence → knowledge lineage 펼침

### Drag/pointer parallax
- camera 1~2° 미세 이동
- 과도한 orbit 금지

### Scroll
- hero timeline을 narrative scroll로 자연스럽게 이어감

### Reduced motion
- animation 없이 4개의 static state frame + fade

---

# 28. Web 3D 기술 구현

## 28.1 유료 visual dependency 금지

**GetLayers 없음.**

우리가 직접 만든다.

## 28.2 Stack

```text
Three.js
React Three Fiber
@react-three/drei
GSAP
ScrollTrigger
Motion
Blender (optional)
```

## 28.3 Procedural primitives

구매 asset 없이 코드로 만든다.

```text
<DocumentPlane />
<DocumentStack />
<PageBlock />
<TableGrid />
<KnowledgeNode />
<RelationshipLine />
<TimelineRail />
<VersionGhost />
<ImpactPulse />
<StaleHalo />
<RecompileWave />
```

## 28.4 Blender 사용 조건

Blender는:
- custom logo geometry
- 특별한 macro object
- procedural code로 비효율적인 형태

에만 사용.

문서/graph/timeline은 코드로 생성.

---

# 29. Cinematic Implementation Architecture

```text
HeroCinematic
├── SceneRoot
├── CameraRig
├── LightingRig
├── DocumentField
├── ExtractionLayers
├── KnowledgeGraph
├── TemporalAxis
├── ChangeEvent
├── ImpactSystem
├── RecompileSystem
├── CinematicTimeline
└── FallbackPoster
```

GSAP timeline은 한 곳에서 관리.

```text
timeline
  .to(camera)
  .to(documents)
  .to(blocks)
  .to(graph)
  .to(timeAxis)
  .to(change)
  .to(impact)
  .to(recompile)
```

R3F 내부 fast animation은 React setState를 매 frame 호출하지 않고 refs/useFrame/GSAP target을 사용.

---

# 30. Performance Budgets — 3D가 브랜드를 망치지 않게

## 30.1 Desktop target

- first interaction 전에 site usable
- WebGL lazy mount 가능
- 60fps target on modern desktop
- 30fps 미만 지속 시 자동 degrade 고려

## 30.2 Mobile

Full hero를 그대로 축소하지 않는다.

- node count 감소
- document count 감소
- postprocessing 제거/축소
- shader 단순화
- camera motion 축소

## 30.3 Low power

adaptive DPR / demand rendering 고려.

## 30.4 Accessibility

`prefers-reduced-motion`:

- camera motion 제거
- auto cinematic 제거
- static sequence
- 모든 의미 텍스트/DOM으로 제공

## 30.5 Fallback

WebGL fail:
- poster
- short prerendered fallback
- product copy
- CTA

---

# 31. 홈페이지 Scroll Story

## Section 1 — CHAOS

시각:
흩어진 source documents.

카피:
> **Your company is digital. Its meaning may not be.**

## Section 2 — STRUCTURE

시각:
page / table / clause 분해.

카피:
> Preserve structure, not just text.

## Section 3 — MEANING

시각:
Entity + Relationship 생성.

카피:
> Knowledge is not a pile of documents. It is a system of relationships.

## Section 4 — TIME

시각:
timeline.

카피:
> Truth changes.

## Section 5 — CHANGE

시각:
semantic diff.

카피:
> When reality changes, know what changed.

## Section 6 — IMPACT

시각:
dependency pulse.

카피:
> Know what became stale before your AI does.

## Section 7 — RECOMPILE

시각:
local rebuild.

카피:
> Recompile only what changed.

## Section 8 — EVIDENCE

실제 benchmark.

카피:
> **Every claim has a receipt.**

## Section 9 — YOUR KNOWLEDGE

CTA:
> **See what your AI would get wrong.**

[ Run a Knowledge Health Scan ]

---

# 32. Product UI Design Language

## 32.1 Calm density

많은 정보를 보여주지만 "dashboard toy"처럼 보이지 않는다.

## 32.2 Border 최소화

구조는:
- spacing
- hierarchy
- typography
- subtle surface

로 전달.

## 32.3 Product UI를 marketing asset으로 사용

가짜 feature illustration 대신 실제:
- Evidence Inspector
- Change Center
- Timeline
- Impact Explorer
- Health Scan

을 landing에 넣는다.

## 32.4 Motion level

### Level 0
static UI

### Level 1
micro interaction 120–240ms

### Level 2
semantic state 250–700ms

### Level 3
narrative 1–5s

### Level 4
cinematic 10–15s

모든 section을 Level 4로 만들지 않는다.

---

# 33. Website IA

Top navigation:

```text
TAVONEL
Product
Solutions
Research
Evidence
Developers
Security
Pricing
[ Scan your knowledge ]
```

## Product
- Knowledge Compiler
- Evidence & Provenance
- Change Intelligence
- Temporal Knowledge
- Knowledge CI/CD

## Solutions
초기 3개만:
- Technical Documentation
- Policy / Compliance
- AI / RAG Infrastructure

## Research
- Benchmark methodology
- Recovery research
- Knowledge integrity research

## Evidence
- public claims
- receipts
- limitations
- reproducibility

## Developers
- API
- MCP
- export schemas
- IR documentation

## Security
- architecture
- retention
- data handling
- subprocessors
- security roadmap

---

# 34. Website Copy System

## Hero

**TAVONEL**
**The Knowledge Compiler**

> **Your AI is only as reliable as the reality it sees.**

> Compile fragmented organizational knowledge into trusted, temporal and traceable context for AI and agents.

CTA:
**Scan your knowledge →**

Secondary:
**See how it works**

## Section hook examples

> **Better models cannot fix broken knowledge.**

> **Your company is digital. Its meaning may not be.**

> **Knowledge changes. Your AI should know what changed.**

> **A source changed. Which AI answers are stale now?**

> **Don't rebuild everything. Recompile what changed.**

> **Every claim has a receipt.**

---

# 35. Evidence Section — 공개 claim governance

표시 가능한 승인 claim만 사용.

```text
5,132
public benchmark documents

99.98%
produced output
5,131 / 5,132

99.94%
recovered when recovery was required
1,796 / 1,797

80.6 vs 53.7
same pipeline, recovery enabled vs disabled
```

필수 caveat:
- completion ≠ accuracy
- benchmark definition
- denominator
- low-quality scan 36.9% 공개
- competitor leaderboard는 reproduced claim이 아니라 quoted reference
- $ GPU cost는 retail price와 비교 금지

CTA:
**Inspect methodology →**
**View receipts →**

---

# 36. Agent-Readable Website

TAVONEL 사이트 자체가 철학을 증명한다.

필수:
- semantic HTML
- JSON-LD
- Product schema
- Organization schema
- SoftwareApplication where appropriate
- docs with clear headings
- machine-readable pricing
- effective/updated dates
- changelog
- explicit API/OpenAPI
- MCP docs
- source/evidence metadata

원칙:

> 사람이 이해하기 좋은 사이트와 Agent가 구조적으로 읽기 좋은 사이트를 동시에 만든다.

---

# 37. Pricing / Monetization

페이지 단가만 전면에 두면 parser category로 내려간다.

## 37.1 가격 구조

### Developer
- free / limited
- Health Scan
- API evaluation
- small compile

### Builder
전략 범위:
- 약 $99–199/mo 검토
- small workspace
- provenance
- basic version history
- exports

### Pro
전략 범위:
- 약 $499–999/mo 검토
- scheduled sync
- temporal history
- impact analysis
- MCP
- team features

### Enterprise
- annual contract
- 초기 전략 범위 $30k+/year부터 검토
- volume, connectors, SLA에 따라 확장
- SSO/RBAC
- retention
- audit
- private/BYOC
- dedicated support

**위 숫자는 market positioning hypothesis이며 launch 전 willingness-to-pay 검증 필요.**

## 37.2 Value metric

seat 중심을 피한다.

고려:
- managed knowledge volume
- pages/documents processed
- change volume
- connector count
- active workspace
- compile/recompile usage
- retention/history
- SLA

## 37.3 Upsell

```text
Health Scan
  ↓
One-time Compile
  ↓
Continuous Sync
  ↓
Temporal / Impact
  ↓
MCP/API
  ↓
Enterprise Governance
```

---

# 38. GTM — 처음부터 모든 기업을 노리지 않는다

첫 고객:

> **문서가 자주 바뀌고, 틀리면 비용이 큰 조직**

## Priority verticals

1. Technical documentation / customer support
2. Manufacturing / industrial manuals
3. Policy / compliance
4. Contract operations / legal
5. AI/RAG infrastructure teams

## 대표 pain

- 구버전 답변
- 문서 변경이 RAG에 반영되지 않음
- 출처 추적 불가
- 영향범위 알 수 없음
- 전체 reindex/reprocess 비용
- agent가 stale context 사용

---

# 39. Gracian Code → TAVONEL Funnel

```text
GRACIAN CODE
"와, 이렇게 볼 수도 있네"
   ↓
TAVONEL Research
"기술적으로 진짜네"
   ↓
Evidence
"검증까지 했네"
   ↓
Knowledge Health Scan
"우리 회사도 문제 있네"
   ↓
Compile
   ↓
Continuous Knowledge
   ↓
Enterprise
```

제품 광고를 먼저 하지 않는다.

콘텐츠:
- 인간
- AI
- Context
- Knowledge
- Temporal
- Agent
- Reality

의 세계관을 쌓고 제품은 그 문제를 직접 해결하는 결과물로 등장.

---

# 40. Analytics / Conversion

필수 events:

```text
hero_view
hero_cinematic_complete
hero_demo_interact
evidence_open
methodology_open
health_scan_start
health_scan_upload_complete
health_scan_report_view
compile_cta
signup
first_compile
second_compile
mcp_activation
api_activation
team_invite
enterprise_contact
pilot_start
pilot_paid
```

핵심 funnel:

```text
Landing
→ WOW
→ Evidence
→ Health Scan
→ First Compile
→ Repeat Compile
→ Continuous Sync
→ MCP/API
→ Enterprise
```

---

# 41. Security / Enterprise Trust

SOC 2/ISO를 받기 전에도 Trust Center를 만든다.

공개:
- encryption
- tenant isolation
- data retention
- deletion
- model provider policy
- subprocessors
- auditability
- incident response
- security contact
- planned certifications

금지:
- 아직 없는 certification logo
- "SOC 2 compliant" 허위 표기

---

# 42. Claude Code 구현 운영체계

Claude를 장기 프로젝트 구현 에이전트로 사용한다.

## 42.1 Root CLAUDE.md

프로젝트 root에 반드시 둔다.

핵심 내용:

```markdown
# TAVONEL Project Constitution

## North Star
TAVONEL is The Knowledge Compiler.

## Never regress into
- PDF converter
- generic RAG builder
- generic graph viewer

## Core moat
- Evidence provenance
- Stable identity
- Document-Semantic Lineage
- Temporal integrity
- Incremental recompilation

## Brand
- Show first, explain second
- Calm luxury enterprise
- Motion encodes meaning
- No generic AI visual slop
- No paid GetLayers dependency

## Evidence
Never publish a numerical claim without a receipt.
Never call 99.98% completion accuracy.
Always preserve low-quality scan limitation.

## Implementation
- TypeScript strict
- Python typed
- migrations single-head
- tests required
- no silent fallback
- fail closed on integrity violations

## Visual QA
A page is not complete because it renders.
It is complete only after desktop/mobile/performance/reduced-motion visual QA.
```

CLAUDE.md는 짧고 강제성이 높은 규칙 중심으로 유지하고 상세 설계는 `/docs/architecture/`로 분리한다.

## 42.2 Claude subagents

`.claude/agents/` 또는 현행 Claude Code project subagent 방식에 맞춰:

### `backend-architect`
- IR
- temporal schema
- API
- jobs

### `knowledge-integrity`
- provenance
- semantic diff
- lineage
- dependency

### `gpu-runtime`
- RunPod
- parser routing
- recovery
- benchmark

### `frontend-product`
- dashboard
- component system

### `cinematic-director`
- R3F
- GSAP
- scene grammar
- art direction

### `visual-qa`
- screenshots
- responsive
- motion consistency
- AI-slop detection

### `evidence-auditor`
- claims
- denominator
- artifact/hash
- no unsupported claim

### `security-review`
- auth
- tenant isolation
- R2 paths
- presigned URLs
- audit

Subagent는 main context를 로그/검색으로 오염시키지 않도록 좁은 책임을 가진다.

## 42.3 Hooks

결정론적으로 강제할 항목은 Claude의 판단에 맡기지 않는다.

예:
- Python edit 후 ruff/targeted test
- TS edit 후 eslint/tsc
- migration 변경 후 migration graph validator
- claims pack 변경 후 hash/claim validator
- marketing claim 변경 후 forbidden wording check
- 3D scene 변경 후 performance smoke test

---

# 43. Suggested Repository Architecture

```text
tavonel/
├─ CLAUDE.md
├─ README.md
├─ docs/
│  ├─ north-star/
│  │  └─ TAVONEL_FINAL_NORTH_STAR_MASTERPLAN.md
│  ├─ architecture/
│  │  ├─ canonical-ir.md
│  │  ├─ temporal-model.md
│  │  ├─ lineage.md
│  │  ├─ recompilation.md
│  │  ├─ storage.md
│  │  └─ security.md
│  ├─ design/
│  │  ├─ brand-system.md
│  │  ├─ cinematic-storyboard.md
│  │  ├─ motion-grammar.md
│  │  └─ web-wow-architecture.md
│  └─ evidence/
│
├─ apps/
│  ├─ web/
│  │  ├─ app/
│  │  ├─ components/
│  │  ├─ scenes/
│  │  │  ├─ hero/
│  │  │  ├─ impact/
│  │  │  └─ timeline/
│  │  └─ lib/
│  └─ api/
│
├─ services/
│  ├─ compiler/
│  ├─ recovery/
│  ├─ diff/
│  ├─ lineage/
│  ├─ temporal/
│  └─ validation/
│
├─ workers/
│  ├─ runpod/
│  ├─ parsers/
│  └─ embeddings/
│
├─ packages/
│  ├─ ir/
│  ├─ schemas/
│  ├─ ui/
│  ├─ motion/
│  └─ client/
│
├─ migrations/
├─ tests/
└─ .claude/
   ├─ agents/
   ├─ commands/
   └─ settings.json
```

기존 repository 구조가 이미 안정적이면 강제 migration하지 말고 logical module boundary만 맞춘다.

---

# 44. 구현 우선순위 — 범위 폭발 방지

## PHASE 0 — Freeze / audit

- 현재 repository baseline
- test green
- evidence freeze
- FOLYNTA internal evidence와 TAVONEL public naming 분리
- North Star 문서 설치
- CLAUDE.md 설치

**Exit:** 기존 기능 regression 없음.

## PHASE 1 — Canonical IR + Stable IDs

- IR schema
- source/version/evidence IDs
- adapter boundary
- existing compilation target → IR consumer화

**Exit:** 동일 input 반복 compile에서 stable IDs 검증.

## PHASE 2 — Provenance

- source page/bbox/span
- Evidence Inspector
- claim → original source navigation

**Exit:** sample corpus에서 모든 supported derived unit가 source로 역추적.

## PHASE 3 — Version + Semantic Diff

- document version
- source continuity
- structure diff
- semantic diff
- conflict UI

**Exit:** versioned fixture에서 expected change set deterministic.

## PHASE 4 — Dependency + Impact

- dependency edges
- recursive impact traversal
- stale marking
- Impact Explorer

**Exit:** injected source change의 expected blast radius test 통과.

## PHASE 5 — Incremental Recompile

- affected-only pipeline
- cache invalidation
- validation
- compare full rebuild equivalence

**Exit:** selective result가 full rebuild의 relevant artifacts와 동일함을 prove.

## PHASE 6 — Temporal

- valid/system time
- as-of query
- history
- timeline UI

**Exit:** bitemporal fixtures에서 correct state reconstruction.

## PHASE 7 — API / MCP

- read-only 먼저
- search/as_of/diff/evidence/impact
- auth/rate limit/audit

**Exit:** external Claude/agent가 workspace를 read-only로 안전 조회.

## PHASE 8 — Health Scan / Commercial

- public scan
- report
- conversion
- billing
- account/workspace

## PHASE 9 — Cinematic Website

기술 core와 독립적으로 병행 가능하지만 final claim은 실제 구현 상태만 표현.

- hero scene
- scroll narrative
- interactive impact demo
- evidence section
- performance fallback

## PHASE 10 — Enterprise

- SSO
- RBAC
- retention
- connector framework
- audit export
- SLA observability

## PHASE 11 — Decision Replay / Simulation

실사용 demand가 확인된 뒤.

---

# 45. 구현 난이도별 "지금 만들지 않을 것"

초기 금지:

- 자체 OCR foundation model
- 자체 Vector DB
- 자체 graph database
- 자체 LLM
- 50개 connector
- agent runtime 플랫폼
- autonomous write-action
- multi-cloud enterprise deployment
- full what-if simulator
- 100개 dashboard
- 모든 산업 solution page

기성 부품을 쓰고 Compiler logic에 집중.

---

# 46. Test Strategy

## Unit
- stable ID
- diff
- temporal
- lineage
- dependency
- permission

## Property
- recompile idempotence
- lineage acyclic where required
- no orphan evidence
- fail-closed invariants

## Integration
- upload → R2
- job → RunPod
- result → IR
- compile → export

## Benchmark
기존 public benchmark 유지.

## Recompilation benchmark — 신규 필요

fixture:
- source v1
- controlled change v2
- known expected affected set

측정:
- precision/recall of affected artifact detection
- selective vs full rebuild equivalence
- work avoided
- latency
- cost

**이 신규 benchmark가 장기적으로 TAVONEL의 가장 중요한 proprietary/public research asset 후보다.**

---

# 47. 신규 Research Program

## Study A — Document-Semantic Lineage correctness

질문:
원본 evidence에서 파생 artifact까지 lineage가 얼마나 정확히 유지되는가?

## Study B — Impact detection

질문:
controlled source change가 downstream artifact 중 어디를 invalidate해야 하는지 얼마나 정확히 찾는가?

## Study C — Incremental equivalence

질문:
selective recompile 결과가 full rebuild 결과와 semantic/structural equivalent인가?

## Study D — Temporal correctness

질문:
as-of query가 known ground-truth history를 재구성하는가?

## Study E — Agent grounding benefit

질문:
plain RAG 대비 provenance/temporal filtered TAVONEL context가 outdated/conflict 질문에서 성능을 개선하는가?

---

# 48. Marketing Claim Ladder

## 지금 가능한 claim
기존 evidence만.

## 구현 후 가능한 claim
기능이 production-ready + test evidence 있을 때.

## benchmark 후 가능한 claim
impact/recompile performance.

절대 먼저 말하지 않는다.

---

# 49. Website Visual QA Gate

홈페이지는 다음을 통과해야 launch candidate가 된다.

### Brand
- generic AI template처럼 보이지 않는가?
- purple/blue AI cliché에 빠지지 않았는가?
- motion이 제품 의미를 전달하는가?

### WOW
- 5초 내 thesis WOW
- 15초 내 cinematic WOW
- 30초 내 product WOW
- 60초 내 evidence WOW

### Product clarity
- PDF converter로 오해되지 않는가?
- "change → impact → recompile"이 눈으로 보이는가?

### Trust
- benchmark caveat 표시
- unsupported claim 없음
- security 정보 접근 가능

### Performance
- responsive
- low-power fallback
- reduced motion
- no layout shift from canvas
- usable without WebGL

### Conversion
- CTA clearly visible
- Health Scan value obvious

---

# 50. Claude Implementation Workflow

Claude에게 "전체 완성해"라고 한 번에 시키지 않는다.

각 phase마다:

```text
1. Read North Star
2. Inspect current code
3. Produce gap report
4. Implement smallest coherent slice
5. Run tests
6. Visual/behavior QA
7. Compare against acceptance criteria
8. Update architecture docs
9. Commit checkpoint
10. Continue
```

## 각 작업 prompt의 필수 형식

```text
GOAL
SCOPE
SOURCE OF TRUTH
NON-GOALS
FILES TO INSPECT
IMPLEMENTATION CONSTRAINTS
ACCEPTANCE TESTS
VISUAL ACCEPTANCE
EVIDENCE REQUIREMENTS
DONE DEFINITION
```

---

# 51. Done Definition

"코드가 있음"은 done이 아니다.

Feature Done:

1. code implemented
2. tests green
3. failure path tested
4. docs updated
5. telemetry added
6. tenant isolation checked
7. visual QA if UI
8. evidence/claim updated if relevant
9. no North Star regression

Cinematic Done:

1. story understandable without body copy
2. desktop motion polished
3. mobile version intentionally redesigned
4. reduced-motion version
5. WebGL fallback
6. performance budget met
7. no generic AI visual cliché
8. product concept accurately represented

---

# 52. Launch Gate

## Product
- stable ingestion/recovery
- provenance
- versioning
- basic diff
- Health Scan
- core exports

## Evidence
- claims pack clean
- public benchmark page
- limitations public

## Website
- hero WOW
- interactive demo
- evidence
- health scan CTA
- security

## Operations
- no RunPod resource leak
- R2 lifecycle
- alerts
- job recovery
- billing protection

## Legal
- privacy
- terms
- DPA-ready structure
- trademark/domain checks separately complete

---

# 53. 3-Year Product Trajectory

## TAVONEL 1
**Knowledge Compiler**
- documents
- provenance
- structure
- version

## TAVONEL 2
**Knowledge CI/CD**
- semantic diff
- dependency
- impact
- selective recompile

## TAVONEL 3
**Temporal Organizational Context**
- valid/system time
- APIs
- MCP
- continuous sync

## TAVONEL 4
**Decision Integrity Layer**
- agent consumption lineage
- decision replay
- impact simulation
- policy-aware context

이 순서를 거꾸로 만들지 않는다.

---

# 54. 최종 브랜드 서사

### Act 1 — The problem

기업은 디지털화됐지만 의미는 아직 기계가 이해할 수 있는 상태가 아니다.

### Act 2 — The model paradox

AI가 더 똑똑해질수록 지식 구조의 결함이 더 잘 보인다.

### Act 3 — The compiler

인간이 만든 fragmented knowledge와 AI 사이에 compiler가 필요하다.

### Act 4 — Time

회사는 계속 변한다. 어제 만든 AI context는 오늘 stale할 수 있다.

### Act 5 — Integrity

변화가 생겼을 때 무엇이 영향을 받았는지 알고 필요한 부분만 다시 compile해야 한다.

### Act 6 — TAVONEL

> **The Knowledge Compiler**

---

# 55. 최종 홈페이지 감정 곡선

```text
0s      Intrigue
5s      "와"
15s     Understanding
30s     "이건 다르다"
45s     Trust
60s     Personal relevance
90s     Action
```

이 감정 곡선이 TAVONEL 웹사이트 디자인의 최종 KPI다.

---

# 56. 최종 한 줄

> **TAVONEL은 문서를 AI가 읽게 만드는 회사가 아니다.**
>
> **현실이 바뀔 때 AI가 믿는 세계도 정확하게 바뀌도록 만드는 Knowledge Compiler다.**

---

---

# FINAL PRECEDENCE REMINDER

- 최종 completeness closure(semantic models, chunking, Office, connectors, scheduling, evaluation, billing, GTM): PART B2 최우선.
- 구현 알고리즘·보안·운영·benchmark·phase gate: PART B 우선.
- 제품 철학·브랜드·웹 경험·GTM: PART C를 따르되 PART B의 evidence/claim gate가 우선.
- 기존 v2.0 설명은 맥락과 historical design rationale로 보존.
- 최종 실행 명령은 `N48` 하나뿐이다.


---

# FINAL EXECUTION BOUNDARY

아래 `N48`과 `N49`만 현재 구현 캠페인의 실행 명령과 최종 완료 계약이다. 이 아래에는 새로운 설계 canon이 존재하지 않는다.

# N48. FINAL AUTONOMOUS CLAUDE CODE COMMAND — v3.1

아래 블록이 이 파일 안의 모든 이전 Claude command를 대체한다.

```text
You are the lead implementation orchestrator for TAVONEL.

SOURCE OF TRUTH
Read this entire v3.1 EXTREME FINAL masterplan before changing code.
PART B2 is highest-priority normative method, followed by PART B; both override conflicting inherited v2/v1 language.
Preserve all verified benchmark evidence and historical artifact labels.

MISSION
Bring the existing repository to the TAVONEL v3.1 launch-candidate and paid-pilot-ready state through
continuous, dependency-aware, evidence-gated phases. Do not perform one unsafe
monolithic rewrite. Continue autonomously from phase to phase only when the current
phase exit gate passes.

FIRST ACTIONS — NO FEATURE CODING YET
1. Inspect the complete repository, git status, branches, migrations, CI, deployments,
   evidence artifacts, model/runtime code, frontend, secrets references, and docs.
2. Verify every existing evidence artifact and hash. Never rewrite historical receipts.
3. Produce /docs/audit/V3_GAP_MATRIX.md classifying every requirement as:
   PROVEN / IMPLEMENTED_NOT_PROVEN / PARTIAL / MISSING / CONFLICTING / BLOCKED_LICENSE.
4. Produce /docs/audit/V3_DEPENDENCY_AND_LICENSE_INVENTORY.md including code, model,
   weight, container, dataset, and transitive licenses.
5. Install or update the concise root CLAUDE.md constitution.
6. Create the required schemas, state/failure enums, phase report schema, ADR template,
   test harness, and CI gates before new product features.
7. Commit a Phase-0 checkpoint. Then execute the phases in N41 order.

AUTONOMY
Do not ask the user to choose technical libraries or algorithms already decided here.
Ask only for missing secrets/payment approval, legal/business-truth decisions, or
irreversible production/destructive actions.

IMPLEMENTATION RULES
- Preserve stable working systems unless replacement is proved better.
- R2 is permanent artifact truth; PostgreSQL is workflow/publish truth.
- Treat Queue delivery as at-least-once and make every consumer idempotent.
- Treat every uploaded document as hostile/untrusted data.
- Never grant parser/extraction LLMs tools, broad credentials, or outbound network.
- Never publish knowledge without evidence, permission, temporal, and integrity checks.
- Never fabricate bbox, dates, authority, confidence, or source.
- Never auto-resolve unresolved authoritative conflicts.
- Never expose write MCP before read-only auth, scopes, audits, approvals, idempotency,
  and rollback are complete.
- Never use unverified model/container/license artifacts in production.
- Never claim completion or accuracy without the exact receipt and denominator.

LOOP FOR EACH PHASE
A. Re-read the phase requirements and affected ADRs.
B. Inspect current implementation and preserve verified behavior.
C. Write or update ground-truth fixtures and failing tests first.
D. Implement the smallest coherent vertical slice.
E. Run unit, property, integration, security, benchmark, visual, and chaos tests that
   apply to the slice.
F. Have a separate reviewer/adversarial subagent inspect the diff and evidence.
G. Fix all blockers; do not suppress or weaken tests to pass.
H. Generate machine-readable receipts and the N42 phase report.
I. Update architecture/runbooks/known limitations/claim registry.
J. Commit/tag the rollback checkpoint.
K. Continue only if next_phase_ready=true.

FAILURE HANDLING
If a phase cannot pass, do not invent success. Preserve a working checkpoint, document
exact blockers and evidence, implement the safest partial result, and keep unsupported
claims WITHHELD. Never broaden permissions, remove caveats, or silently fall back to a
less trustworthy result.

VISUAL/PRODUCT RULES
The product and website are not done because they render. Validate desktop, mobile,
reduced-motion, WebGL fallback, performance, accessibility, real product data, and the
change→impact→selective-recompile narrative. No generic AI visual slop and no paid
GetLayers dependency.

FINAL LAUNCH-CANDIDATE DELIVERABLES
- Secure ingestion and adaptive routing/recovery runtime
- Open-weight semantic model gateway with strict structured-output contracts
- Versioned embedding/reranking and structure-aware knowledge packaging
- Dual-path Office parsing/rendering and cross-document version resolution
- Connector change/ACL synchronization and fair multi-tenant scheduling
- Document reconciliation and Canonical Knowledge IR v3
- Evidence-level provenance and stable semantic identity
- Entity/authority/applicability/temporal/epistemic resolution
- Prompt-injection and supply-chain controls
- Semantic diff, typed impact, selective recompilation, atomic world states
- Permission-first retrieval, read-only MCP, agent consumption lineage
- Knowledge Health Scan, append-only usage ledger, billing/onboarding/analytics
- End-to-end retrieval/answer/citation evaluation and deterministic export blueprints
- API/SSE/webhooks/SDK contracts with idempotency and rate limits
- Paid-pilot GTM workflow and experiment receipts
- Real product UI, cinematic website, evidence and Trust surfaces
- Competitive/research benchmarks with receipts and limitations
- Backup/restore, deletion, security, incident and rollback runbooks
- All CI/benchmark/security/visual launch gates green

The final target is not an OCR demo, PDF converter, generic RAG builder, or graph toy.
The final target is TAVONEL — The Knowledge Compiler — a trustworthy runtime that keeps
the world AI sees synchronized with changing organizational reality.
```

---

# N49. Final Definition of Done

TAVONEL v3.1 launch candidate는 다음이 모두 사실일 때만 완료다.

1. code exists and tests pass.
2. failure and recovery paths are exercised.
3. every core feature has ground truth or explicit limitation.
4. selective compilation is proven against full rebuild.
5. world state publish and rollback are atomic.
6. no tenant/permission/security fixture leaks data.
7. malicious document instructions cannot control tools or policies.
8. exact source, parser, model, schema, container and build lineage is reproducible.
9. customer deletion and backup restore are tested.
10. performance and cost are measured by p50/p95/p99 and route class.
11. public claims are rendered from approved receipts with caveats.
12. the Health Scan discovers a real problem and leads to a coherent paid workflow.
13. the website communicates change→impact→recompile without relying on body copy.
14. mobile, reduced-motion, accessibility and fallback paths pass.
15. every known limitation is visible and no withheld claim is published.
16. a rollback checkpoint and incident runbook exist for every production-critical phase.
17. the user does not need to manually read every line of AI-generated code because CI,
    benchmarks, reviewer agents and evidence gates provide independent verification.
18. structure-aware chunks preserve clause/exception, procedure/warning, and table-header context.
19. Office documents pass both structural and visual reconciliation without executing macros or links.
20. connector permission revocation is enforced before background recompilation completes.
21. retrieval, answers and citations pass end-to-end authority/time/permission fixtures.
22. usage credits reconcile against actual work with bounded customer-visible cost.
23. at least one narrow paid-pilot workflow is operable from Health Scan through continuous sync.

> **TAVONEL is complete only when it can prove not merely that it produced output, but that the knowledge it published is traceable, current, permission-correct, recoverable, and safe for AI to consume.**


---

# END OF TAVONEL ULTIMATE PRODUCTION RESEARCH & IMPLEMENTATION MASTERPLAN v3.1 EXTREME FINAL
