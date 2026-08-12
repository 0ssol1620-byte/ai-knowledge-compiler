# TAVONEL — FINAL NORTH STAR MASTERPLAN
## Product · Knowledge Architecture · Evidence · Temporal Integrity · Website · Cinematic 3D · Brand · GTM · Monetization · Claude Implementation

**문서 상태:** FINAL NORTH STAR v1.0  
**작성 기준일:** 2026-08-09 (KST)  
**공개 브랜드:** **TAVONEL**  
**카테고리:** **The Knowledge Compiler**  
**주 구현 에이전트:** **Claude / Claude Code**  
**핵심 인프라:** Vercel + Cloudflare R2 + RunPod + Managed Postgres/pgvector  
**핵심 시각 스택:** Three.js + React Three Fiber + GSAP/ScrollTrigger + Motion + 필요 시 Blender  
**유료 3D 의존성:** **없음. GetLayers/Spline 유료 scene을 필수 dependency로 사용하지 않는다.**

---

# 0. 이 문서의 역할

이 문서는 기능 아이디어 모음이 아니다.

**TAVONEL이 최종적으로 어떤 제품, 어떤 브랜드, 어떤 웹 경험, 어떤 수익모델, 어떤 기술 기반을 가져야 하는지를 하나의 North Star로 잠그는 실행 청사진이다.**

앞으로 구현 과정에서 새로운 아이디어가 생겨도 다음 질문을 먼저 통과해야 한다.

> **이 변경이 TAVONEL을 "AI가 믿을 수 있는 조직 지식을 지속적으로 컴파일하는 시스템"이라는 North Star에 더 가깝게 만드는가?**

그렇지 않다면 후순위 backlog로 보낸다.

이 문서는 특히 다음 문제를 방지한다.

- 기능이 늘어나며 정체성이 흐려지는 것
- PDF/OCR 제품으로 축소되는 것
- Palantir/Glean/DataHub를 전부 따라 만들려는 범위 폭발
- 홈페이지가 예쁘지만 제품의 본질을 전달하지 못하는 것
- 3D가 장식으로 전락하는 것
- 마케팅 claim이 실제 evidence보다 앞서가는 것
- Claude 세션이 바뀔 때마다 구현 방향이 달라지는 것
- frontend/backend/research/marketing이 서로 다른 이야기를 하는 것

---

# 1. 절대 변경하지 않는 North Star

## 1.1 한 문장

> **TAVONEL is the Knowledge Compiler for AI.**

## 1.2 제품 정의

> **Compile fragmented organizational knowledge into trusted, temporal, traceable context for AI and agents.**

## 1.3 핵심 문제 정의

> **Your AI is only as reliable as the reality it sees.**

## 1.4 변화에 대한 핵심 약속

> **When reality changes, your AI should know exactly what changed.**

## 1.5 기술적 핵심

> **Document-Semantic Lineage + Temporal Knowledge Integrity + Incremental Knowledge Recompilation**

## 1.6 대중적 설명

> 흩어진 문서와 조직 정보를 읽고 정리하는 데서 끝나지 않고,  
> **어떤 지식이 어디에서 왔고, 언제 유효하며, 무엇과 연결되고, 무엇이 바뀌면 어디까지 다시 고쳐야 하는지** 추적하는 Knowledge Compiler.

---

# 2. 가장 중요한 제품 철학

## 2.1 Better models cannot fix broken knowledge

모델이 더 강해져도 다음 문제는 자동으로 해결되지 않는다.

- 최신본과 폐기본 충돌
- 문서 속 숨은 적용 조건
- 표/도형/레이아웃 관계 손실
- 서로 다른 파일에 흩어진 사실
- 동일 entity의 alias
- 적용 시작/종료 시간
- 출처와 권위
- 권한
- downstream stale context

TAVONEL은 "AI가 PDF를 못 읽어서" 존재하는 제품이 아니다.

**AI가 충분히 똑똑해지면서 지식 환경의 품질이 다음 병목으로 올라오기 때문에 존재한다.**

## 2.2 Document Reading ≠ Knowledge Operations

단일 문서 독해와 조직 지식 운영은 다르다.

```text
Single document reading
- 몇 개 파일
- 현재 세션
- 일회성 Q&A
- 전체 원문 투입도 가능

Knowledge operations
- 수천~수십만 파일
- 중복/개정/폐기/충돌
- 지속 업데이트
- 여러 문서 간 관계
- 권한
- provenance
- production reliability
- agent consumption
```

## 2.3 TAVONEL의 적은 "낮은 OCR 점수"가 아니다

장기적으로 TAVONEL이 싸우는 대상은:

> **Stale AI Reality**

즉 현실이 바뀌었는데 AI가 보고 있는 조직 세계가 따라오지 못하는 상태다.

---

# 3. Evidence Baseline — 현재 실제로 증명된 것

이 섹션은 기존 내부 캠페인 `FOLYNTA_CAMPAIGN_RESULTS.md`의 evidence를 기반으로 한다.

**주의:** FOLYNTA는 기존 연구/캠페인 명칭이며 공개 브랜드는 TAVONEL이다.  
증거 파일명, artifact hash, receipt는 재현성 때문에 임의 rename하지 않는다.

## 3.1 Public benchmark campaign

총 **5,132 documents / 3 public benchmarks**

- ParseBench: 2,078
- OmniDocBench: 1,651
- olmOCR-Bench: 1,403

현재 extraction baseline:
- MinerU 3.4.4 VLM engine
- FOLYNTA/TAVONEL recovery runtime

## 3.2 Completion / recovery

- **5,131 / 5,132 produced output = 99.98% completion**
- 실제 recovery 대상: 1,797
- recovered: 1,796
- **99.94% recovery when recovery was required**

**절대 규칙:** 99.98%는 accuracy라고 말하지 않는다.

## 3.3 olmOCR-Bench

- overall: **80.6%**
- 7,137 / 8,413 checks
- 95% CI: 79.62–81.57

저품질 scan:
- **36.9%**
- 이 약점은 숨기지 않는다.

## 3.4 Recovery lane의 가치

동일 model / corpus / evaluator / settings에서 recovery만 제거:

```text
With recovery       80.6
Recovery disabled   53.7
```

이 숫자는 현재 TAVONEL의 중요한 제품 철학을 보여준다.

> **최고의 모델 하나보다 실패를 견디는 시스템이 중요하다.**

## 3.5 Reproducibility

128 cases per suite × 3 suites × 3 repeats:

- 384 / 384 documents: markdown byte-identical
- 384 / 384: terminal status stable

## 3.6 Compilation evidence

1,000 documents / 7 blueprints:

- architecture plans stable
- distinct blueprints → distinct plans
- unresolved internal links in emitted vault: **0**
- silent file loss across 5 merge policies: **0**
- 4 export targets:
  - Obsidian
  - Ontology
  - Neo4j
  - RAG

Fail-closed:
- 1,000 offered
- 596 compiled
- 404 refused due unresolved links/assets

이것은 제품의 중요한 신뢰 원칙으로 승격한다.

> **Broken knowledge should fail closed, not look successful.**

## 3.7 반증/약점도 공개

- blind quality detection hypothesis: **not supported**
- empty source vs empty result harness gap
- 일부 evaluator artifact
- low-quality scan weakness
- targeted quality retry의 improvement claim은 공식 re-evaluation/no-regression gate 완료 전 보류

## 3.8 브랜드 원칙으로 승격

### **Evidence, not adjectives.**

### **Every claim has a receipt.**

TAVONEL은 "world-class", "best", "99% accurate" 같은 증거 없는 형용사 대신 다음을 보여준다.

- corpus
- evaluator
- revision
- denominator
- CI
- artifact hash
- caveat
- failed hypothesis

---

# 4. 경쟁 구도와 우리가 차지할 자리

## 4.1 직접 복제하면 안 되는 영역

### Google / Enterprise Context
- context graph
- enterprise knowledge catalog
- governance
- MCP
- agent-ready enterprise context

### Glean
- enterprise search
- permissions-aware context
- people/content/activity graph
- connectors
- agent context

### DataHub
- lineage
- impact analysis
- metadata history
- context graph
- governance
- MCP

### Zep / Graphiti
- temporal knowledge graph
- bi-temporal fact history
- agent memory
- provenance

### Palantir
- operational ontology
- objects / relationships / actions
- agent operational layer

### LlamaIndex / Reducto / Unstructured
- parsing
- extraction
- document intelligence
- RAG ingestion

## 4.2 따라서 TAVONEL의 차별화는 "기능 하나"가 아니다

### 핵심 조합

1. **Evidence-level Provenance**
2. **Stable Semantic Identity**
3. **Document-Semantic Lineage**
4. **Temporal Knowledge Integrity**
5. **Knowledge Dependency Graph**
6. **Incremental Recompilation**
7. **Validation / Fail-closed**
8. **Interoperable outputs: API/MCP/RAG/Graph/Ontology**

## 4.3 우리가 소유할 질문

> **원본 문서 하나가 오늘 바뀌면, 어떤 AI의 어떤 지식이 지금부터 틀린 건지 알고 있습니까?**

이 질문을 제품 전체의 strategic wedge로 사용한다.

---

# 5. 최종 제품 아키텍처

```text
MESSY ORGANIZATIONAL REALITY
PDF / PPTX / DOCX / XLSX / Images / Scans
Drive / SaaS / API / Database
                │
                ▼
          TAVONEL INGEST
                │
                ▼
        PARSER / RECOVERY ROUTER
                │
        ┌───────┼────────┐
        ▼       ▼        ▼
      Text    Layout    Table/Figure
                │
                ▼
       CANONICAL KNOWLEDGE IR
                │
   ┌────────────┼────────────┐
   ▼            ▼            ▼
Evidence     Structure     Semantics
   │            │            │
   ▼            ▼            ▼
Source        Hierarchy      Entity
Page/Cell     Section        Relation
BBox          Procedure      Claim
   └────────────┼────────────┘
                ▼
          VERSION RESOLUTION
                │
                ▼
        TEMPORAL KNOWLEDGE
                │
                ▼
      DOCUMENT-SEMANTIC LINEAGE
                │
                ▼
       KNOWLEDGE DEPENDENCY GRAPH
                │
      ┌─────────┼──────────┐
      ▼         ▼          ▼
 Semantic    Impact      Integrity
   Diff       Trace       Validation
      │         │          │
      └─────────┼──────────┘
                ▼
      INCREMENTAL RECOMPILATION
                │
     ┌──────────┼───────────┐
     ▼          ▼           ▼
 Markdown     RAG      Knowledge Graph
 Obsidian              Ontology
     │          │           │
     └──────────┼───────────┘
                ▼
            API / MCP
                │
                ▼
            AI / AGENTS
                │
                ▼
       DECISION / ACTION / REPLAY
```

---

# 6. 인프라 최종안

## 6.1 Core stack

### Vercel / Next.js
역할:
- marketing site
- app UI
- API control plane
- auth/billing integration
- job creation
- job status
- server-side rendering / SEO
- MCP HTTP surface

금지:
- GPU-heavy processing을 Vercel function에서 수행하지 않는다.

### Cloudflare R2
역할:
- original source
- page images
- figures
- parser artifacts
- evidence snapshots
- compiled artifacts
- export bundles
- public benchmark receipts

업로드:
- browser → presigned PUT
- 대형 파일 → multipart
- API key browser 노출 금지

### RunPod
역할:
- VLM/OCR/parsing worker
- recovery lane
- alternate parser lane
- embedding optional
- compilation compute
- selective recompilation worker
- model cache

Network Volume:
- large models
- reusable model artifacts
- hot working set

**R2가 permanent source of truth이며 Network Volume은 cache/compute-oriented storage다.**

### Managed Postgres + pgvector
초기에는 이 하나로:
- knowledge IR metadata
- stable IDs
- versions
- temporal rows
- entities
- relations
- lineage edges
- dependency edges
- jobs
- audits
- vectors

를 처리한다.

Neo4j는 graph traversal이 실제 성능 병목이 된 뒤 도입한다.

---

# 7. R2 Storage Layout

```text
sources/
  {tenant}/{workspace}/{source_id}/{document_version_id}/original

artifacts/
  {tenant}/{workspace}/{document_version_id}/
    pages/
    images/
    tables/
    parser/
    canonical/

evidence/
  {tenant}/{workspace}/{evidence_id}/
    snapshot.json
    preview.webp

compiled/
  {tenant}/{workspace}/{compile_run_id}/
    markdown/
    obsidian/
    rag/
    ontology/
    neo4j/

exports/
  {tenant}/{workspace}/{export_id}/bundle.zip

public-evidence/
  campaigns/
  claims/
  receipts/
```

원칙:
- content sha256 저장
- evidence는 overwrite보다 version append
- presigned URLs short-lived
- tenant prefix isolation
- public claims artifact는 hash verify
- 원본 삭제 요청과 derived artifact 삭제 policy를 별도 관리

---

# 8. Canonical Knowledge IR

이것이 TAVONEL의 내부 "중간 언어"다.

모든 parser는 IR producer가 되고, 모든 export는 IR consumer가 된다.

```yaml
knowledge_unit:
  logical_id: ku_...
  version_id: kuv_...
  tenant_id: ...
  workspace_id: ...

  unit_type: paragraph | clause | table | table_row | table_cell |
             figure | caption | list | procedure | policy | claim | metadata

  content:
    text: ...
    normalized_text: ...
    structured_payload: {}

  structure:
    document_path: ["Warranty", "Coverage", "Exceptions"]
    heading_level: 2
    sequence_index: 142
    parent_logical_id: ...

  source:
    source_id: ...
    document_version_id: ...
    page: 17
    bbox: [x0, y0, x1, y1]
    span_start: ...
    span_end: ...
    source_hash: ...

  quality:
    parser: mineru
    parser_version: 3.4.4
    compiler_version: ...
    validation_state: verified | unverified | failed | recovered
    recovery_round: 0

  temporal:
    valid_from: null
    valid_to: null
    recorded_at: ...
    superseded_at: null
    temporal_source: explicit | inferred | unknown

  semantics:
    entities: []
    relationships: []
    claims: []

  lineage:
    derived_from: []
    depends_on: []
    supersedes: []

  governance:
    authority: unknown | informal | official | contractual
    permission_scope: []
    sensitivity: null
```

## 8.1 금지 규칙

- source가 없는 claim 생성 금지
- bbox 없는 source에 가짜 좌표 생성 금지
- 문서에 없는 날짜를 확정값으로 저장 금지
- `FINAL` filename만 보고 latest 확정 금지
- quality status와 semantic correctness를 혼동 금지

---

# 9. Stable Identity

Temporal + incremental compilation은 Stable ID가 없으면 성립하지 않는다.

## 9.1 Source

```text
source_id = hash(tenant + connector_type + connector_native_id_or_canonical_path)
```

## 9.2 Document version

```text
document_version_id = hash(source_id + content_sha256)
```

## 9.3 Evidence

```text
evidence_id =
hash(document_version_id + page + normalized_bbox + normalized_span_hash)
```

## 9.4 Knowledge logical ID

목표:
내용 일부가 바뀌어도 "동일한 policy clause"는 논리적 identity 유지.

초기 heuristic:
- source continuity
- heading/structural path
- semantic anchor
- neighbor anchors
- content similarity

불확실한 경우 자동 merge 금지.

---

# 10. Parser / Recovery Router

## 10.1 원칙

TAVONEL은 특정 OCR/parser에 종속되지 않는다.

```text
Input
  ↓
Document profiler
  ↓
Parser adapter
  ├ MinerU
  ├ PaddleOCR
  ├ future open parser
  ├ LlamaParse optional
  ├ Reducto optional
  └ custom VLM optional
  ↓
Canonical IR
```

## 10.2 현재 강점

기존 campaign에서 recovery runtime은 동일 pipeline score를 53.7 → 80.6으로 만든 핵심 operational layer였다.

따라서 Recovery는 숨은 내부 구현이 아니라 **제품 primitive**다.

## 10.3 Recovery state

```text
QUEUED
  ↓
RUNNING
  ├ success          → DELIVERED
  ├ timeout          → RECOVERY_PLANNED
  ├ worker lost      → RECOVERY_PLANNED
  ├ empty result     → SOURCE-AWARE CHECK
  └ provider failure → GLOBAL PAUSE

RECOVERY_PLANNED
  ↓
REROUTE / RETRY
  ↓
RECOVERED or FAILED_EXPLICIT
```

---

# 11. Evidence / Provenance Engine

모든 중요한 지식은 UI에서 원본까지 역추적 가능해야 한다.

```text
Knowledge Claim
    ↓
Knowledge Unit
    ↓
Evidence
    ↓
Document Version
    ↓
Page / Table / Cell / Region
```

### Evidence Inspector

```text
Warranty = 3 years

SOURCE
warranty_policy_v3.pdf

PAGE
17

REGION
Clause 4.2

VALID
2026-01-01 → Present

AUTHORITY
Official policy

STATUS
Verified / Recovered / Unverified
```

### API

```http
GET /v1/knowledge/{id}/evidence
GET /v1/evidence/{id}
GET /v1/evidence/{id}/preview
```

---

# 12. Semantic Diff

## L0 Binary
- hash changed?

## L1 Structural
- heading tree
- page blocks
- table shape
- figure refs

## L2 Evidence
- added
- removed
- modified
- moved

## L3 Semantic
- claim changed
- exception changed
- value changed
- condition changed
- step changed

## L4 Graph
- entity changed
- relationship added/removed
- authority changed
- temporal validity changed

Example:

```json
{
  "change_id": "chg_01",
  "changes": [{
    "kind": "modified_claim",
    "logical_id": "ku_warranty",
    "before": "2 years",
    "after": "3 years"
  }]
}
```

---

# 13. Temporal Model

## 13.1 두 시간축

### Valid Time
현실에서 사실이 유효했던 시간.

### System Time
TAVONEL이 그 사실을 알고 있던 시간.

```text
Warranty = 3 years

valid_from    2026-01-01
valid_to      null

recorded_at   2026-01-05
superseded_at null
```

이렇게 하면:

- "1월 3일 현실에서 정책은?"
- "1월 3일 당시 AI가 알고 있던 정책은?"

을 분리할 수 있다.

## 13.2 Temporal query

```text
knowledge.search(query, as_of)
entity.history(entity_id)
knowledge.diff(from, to)
```

---

# 14. Document-Semantic Lineage

TAVONEL이 장기적으로 가장 강하게 차별화할 수 있는 층.

```text
Source PDF
  ↓
Page 17
  ↓
Table 4 / Cell B7
  ↓
Evidence Block
  ↓
Normalized Claim
  ↓
Entity / Relation
  ↓
Knowledge Unit
  ↓
RAG Chunk
  ↓
Retrieved Context
  ↓
Agent Consumer
```

질문:
- 어디에서 왔는가?
- 어떻게 변환됐는가?
- 어떤 버전을 통과했는가?
- 누가 사용했는가?
- 변경되면 무엇이 stale인가?

---

# 15. Dependency Graph

Edge types:

```text
DERIVED_FROM
DEPENDS_ON
SUPPORTS
SUPERSEDES
REFERENCES
CONSUMED_BY
EXPORTS_TO
INVALIDATES
```

초기 저장:
- Postgres adjacency table
- recursive CTE

예:

```text
dependency_edges(
  from_id,
  to_id,
  edge_type,
  created_at,
  valid_from,
  valid_to
)
```

---

# 16. Incremental Recompilation — Knowledge CI/CD

## 16.1 Core sequence

```text
SOURCE CHANGE
    ↓
Semantic Diff
    ↓
Changed Knowledge Units
    ↓
Dependency Traversal
    ↓
Affected Artifacts
    ↓
Mark STALE
    ↓
Selective Recompile
    ↓
Validation
    ↓
Deploy
```

## 16.2 제품 UI 핵심 장면

```text
Warranty: 2y → 3y

Affected:
12 documents
41 knowledge units
8 RAG chunks
2 agent workflows

[ Recompile affected knowledge ]
```

## 16.3 가치

전체 corpus를 재처리하는 비용/시간 문제를 줄이고,
무엇을 다시 만들었는지 audit할 수 있게 한다.

---

# 17. Integrity Validation

## 17.1 Validation categories

- extraction completeness
- structural consistency
- internal link integrity
- source existence
- evidence anchoring
- temporal contradiction
- version conflict
- unresolved entity
- orphan relationship
- permission violation
- stale downstream artifact

## 17.2 Fail-closed

심각한 integrity error가 있으면:

```text
COMPILE BLOCKED
```

로 명시한다.

"대충 결과를 내는 것"보다 "왜 못 내는지 증명하는 것"을 선택한다.

---

# 18. API / MCP

MCP/API는 Core 이후에 붙인다.

## 18.1 Read tools

```text
knowledge.search
knowledge.as_of
knowledge.diff
knowledge.get
source.verify
entity.get
entity.history
impact.trace
```

## 18.2 Write tools — 후순위

```text
source.ingest
knowledge.recompile
workspace.sync
```

write/action은:
- permission
- approval
- audit
- idempotency

완성 후 노출.

## 18.3 Agent consumption log

```text
agent_request
  request_id
  agent_id
  retrieved_unit_versions[]
  evidence_ids[]
  tool_calls[]
  action
  timestamp
```

---

# 19. Decision Replay — 장기 Enterprise Killer Feature

문제:

> "왜 6월 3일 AI가 이 결정을 했는가?"

Replay:

```text
Knowledge state at T
+
Evidence at T
+
Permissions at T
+
Retrieved context
+
Tool inputs
+
Action
```

주의:
- "모델의 내부 사고 과정 재현"이라고 말하지 않는다.
- 재현 대상은 **입력 context / knowledge state / tool/action trace**다.

---

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

# 57. Implementation References — 2026-08-09 확인 기준

아래는 설계 판단에 사용한 공식/1차 자료다. 구현 시작 시 최신 버전을 다시 확인하고 lockfile에 pin한다.

## Claude / Claude Code
- Claude Code Project Memory / CLAUDE.md  
  https://docs.anthropic.com/en/docs/claude-code/memory
- Claude Code Hooks  
  https://docs.anthropic.com/en/docs/claude-code/hooks
- Claude Code Subagents  
  https://docs.anthropic.com/en/docs/claude-code/sub-agents

## 3D / Motion
- React Three Fiber Canvas  
  https://r3f.docs.pmnd.rs/api/canvas
- React Three Fiber Events  
  https://r3f.docs.pmnd.rs/api/events
- React Three Fiber Scaling Performance  
  https://r3f.docs.pmnd.rs/advanced/scaling-performance
- React Three Fiber Performance Pitfalls  
  https://r3f.docs.pmnd.rs/advanced/pitfalls
- GSAP ScrollTrigger  
  https://gsap.com/docs/v3/Plugins/ScrollTrigger/

## Storage / GPU
- Cloudflare R2 S3 API compatibility  
  https://developers.cloudflare.com/r2/api/s3/api/
- Cloudflare R2 Presigned URLs  
  https://developers.cloudflare.com/r2/api/s3/presigned-urls/
- Cloudflare R2 Upload Objects  
  https://developers.cloudflare.com/r2/objects/upload-objects/
- RunPod Network Volumes  
  https://docs.runpod.io/storage/network-volumes
- RunPod Serverless Storage  
  https://docs.runpod.io/serverless/storage/overview

## Competitive / category references
구현 전에 경쟁사 최신 product docs를 다시 확인한다.
- Google Cloud Knowledge / Context products
- OpenAI Enterprise / Frontier
- Palantir Ontology / MCP
- DataHub Context Graph / Lineage
- Zep / Graphiti
- Glean Enterprise Context
- LlamaIndex / LlamaParse
- Reducto
- Unstructured

---

# 58. FINAL COMMAND TO CLAUDE

새 Claude Code 세션에서 이 문서와 repository를 연 뒤 아래 원칙으로 시작한다.

```text
Read TAVONEL FINAL NORTH STAR MASTERPLAN in full.

Do not immediately implement.

First:
1. inspect the current repository,
2. map every existing subsystem to this North Star,
3. classify each item as:
   - already proven,
   - implemented but not proven,
   - partial,
   - missing,
   - conflicts with North Star,
4. preserve all currently verified benchmark evidence,
5. produce a gap matrix,
6. create/update CLAUDE.md with the project constitution,
7. propose a dependency-aware implementation sequence,
8. then begin Phase 0 and Phase 1 only.

Do not rebuild stable working systems unnecessarily.
Do not invent unsupported benchmark claims.
Do not replace the recovery runtime without evidence.
Do not use GetLayers or paid 3D dependencies.
Build the cinematic system with Three.js/R3F/GSAP and custom procedural visuals.
Do not consider the website complete until the WOW Architecture, responsive fallback,
reduced-motion path, benchmark evidence, and Health Scan conversion flow are implemented.

The final target is not a PDF converter.
The final target is TAVONEL:
The Knowledge Compiler.
```

---

# END OF FINAL NORTH STAR MASTERPLAN
