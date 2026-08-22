# GAP AUDIT ① — 엔진 코어: 청사진 §13~§22 vs 구현 대조

| 항목 | 값 |
|---|---|
| 감사 대상 레포 | `D:/CodexProjects/ai-knowledge-compiler-g0` |
| 감사 HEAD | `9e9d69a429910c9ddb4095ab0e9e0641c847fe05` (`docs(g0): record the final verification results - all local gates pass`) |
| 감사 워크트리 / 브랜치 | `D:/CodexProjects/ai-knowledge-compiler-audit-engine` / `agent/tavonel-audit-engine` |
| 청사진 | `D:/TAVONEL_INDUSTRY_LEADING_FINAL_MASTER_BLUEPRINT_2026-08-22_KO.md` (§13=L1266 … §22=L2108, §29 입증내역=L2916) |
| 대조 코드 | `packages/cir-python/src/akc_cir/` (실측 27 modules *.py, 약 11.1k LOC — 과제 기재 "41모듈"과 다름, 실측값 기준), `packages/{retrieval,router,quality,native-parsers,parallel-runtime,absorption,domain-packs,exporters,telemetry}/src`, `workers/*` (cpu-document, cpu-export, gpu-common, gpu-hpd, gpu-knowledge, gpu-parser, gpu-unlimited), 참조: `services/api`, `benchmark/v6`, `migrations` |
| 방법 | 청사진 §13~§22 전문 정독 → 섹션별 요구기능 목록화 → 모듈 전수 판독 + 레포 전체 키워드 검색(intent/freshness/purity/CAS/consumption_receipt 등 12회) → file:line 대조 |

**상태 판정기준**: `구현됨`(요구 기능이 코드로 존재하고 동작 근거 확보) / `부분`(핵심 일부만 존재 또는 청사진 세트의 일부만 커버) / `미구현`(레포 전역 검색에서도 부재) / `입증`(청사진 §29.1 [INT-01/02] controlled empirical evidence와 대응).

**총평**: 파이프라인 전반부(ingest 신뢰·identity·authority/temporal·diff·impact·selective 재컴파일·world promotion)는 계약 수준의 구현이 존재하고 그 일부는 §29.1 입증을 받았다. 반면 **§22 Answer Compiler는 사실상 전무**(intent 분류·answer contract·freshness auditor·answer outcomes 모두 0히트, retrieval lanes의 절반만 존재), **§16 Ontology는 선언적 blueprint만 있고 induction/evolution/quality gates가 없다**, **§20의 CompilationActionKey·purity classes·CAS가 없어 selective 재컴파일의 "고무결 재사용" 전제가 미완**이다.

---

## §13 Trusted Ingest · Parsing · Recovery (청사진 L1266–1383)

| # | 요구 기능 (청사진) | 상태 | 코드 증거 (file:line) | GAP / 비고 | 권고 |
|---|---|---|---|---|---|
| 13-a | ingest 체인: preflight→validate→structure profile→route→parse→inspect→critical-token→recovery→evidence package→candidate IR | **부분** | `workers/gpu-common/runtime.py:1091-1490`(Stage A–D 결과 검증), `services/api/src/akc_api/knowledge_pipeline.py`, `page_attempts.py`, `packages/cir-python/src/akc_cir/events.py:15-88`(ProcessingStage/PageState 전이), `inspection.py:306-370`(InspectionResult) | 단계별 검증기·이벤트는 견고하나 체인 전체를 묶는 단일 오케스트레이션 계약(각 단계 산출물의 필수 순서/봉인)은 API·worker에 분산되어 있고 CIR 레벨 계약이 아님 | P1 — 파이프라인 stage contract를 akc_cir 레벨로 끌어올려 단계 누락을 fail-closed화 |
| 13-b | preflight 11항목(archive bomb, MIME 불일치, malformed PDF, macro, 암호화, 외부 링크, prompt injection, PII, 페이지/자원 추정, license/residency, 중복 content-address) | **부분** | `packages/router/src/akc_router/preflight.py:36-94`(암호화·페이지/크기·난이도·`suspected_prompt_injection`), `packages/native-parsers/src/akc_native_parsers/security.py:105-190`(archive bomb: entry/member/압축해제 한도), `trust.py:52-77,120-200`(origin/injection scan), `services/api/src/akc_api/malware.py`, `quarantine_screening.py`, `pdf_passwords.py` | MIME-vs-extension, 외부 링크/참조, PII 분류, license/data-residency 정책 게이트, 중복 content-address 히트는 preflight 계약에 명시적 항목으로 없음(일부는 상위 서비스에 산재) | P1 — preflight 항목 체크리스트를 단일 PreflightReceipt 스키마로 통합, 누락 항목 구현 |
| 13-c | adaptive execution ladder(native→deterministic→visual→crop/rerender→alternate family→cross-parser→stronger verifier→human/abstain) | **구현됨 · 입증** | `packages/cir-python/src/akc_cir/recovery_policy.py:73-90`(RecoveryLevel L0–L8), `:92-118`(QualityMode FAST/BALANCED/VERIFIED 사다리 상한), `:120-133`(RecoveryOutcome BLOCK_SECURITY/HUMAN_REVIEW/FAIL_CLOSED…), `parallel-runtime/{arbitration,attempts,first_verified}.py` | 사다리 자체는 청사진과 동형. cross-parser verification은 L4 ensemble로 근사. **입증**: Family A recovery 5,132 public documents(§29.1 [INT-01], 단 effect size CI는 zero 포함) | P2 — L3 alternate family ↔ cross-parser 검증의 대응 관계를 문서화 |
| 13-d | critical semantic tokens 13카테고리(numbers/signs/decimals/percentages/currencies/units/dates/IDs/clauses/must-may-not/table cells/formula symbols/version numbers) | **부분** | `packages/retrieval/src/akc_retrieval/numeric.py:32-33,100-170`(unit·currency·decimal exact gate), `services/api/src/akc_api/collection_semantic_runtime.py:3087-3095`(최종 수치 답변 게이트), `packages/quality/src/akc_quality/{numeric_authority,table_conservation,tables}.py` | 수치·단위·통화·테이블 보존은 강함. signs/percentages/dates/IDs/clauses/must-may-not/formula symbols/version numbers를 아우르는 토큰 분류·검증 목록은 없음 | P1 — critical token taxonomy를 detector 레지스트리로 명시(누락 카테고리 fail-visible) |
| 13-e | evidence independence — correlated channels를 독립 증거로 합산 금지(8채널) | **부분** | `packages/quality/src/akc_quality/evidence_ladder.py:10-45`(EvidenceLevel 0–10, `minimum_independent_sources`, hard gates), `recovery_policy.py`(AgreementVector/arbitrate) | 독립 소스 최소 수 하한은 있으나 `SOURCE_NATIVE/RASTER_VISUAL/PARSER_FAMILY_A/B/...` 채널 유형 분류 자체가 없어 "같은 parser 재실행 2회 = 독립 2증거" 오평가를 구조적으로 막는 장치가 없음 | P1 — EvidenceChannel enum + 채널 상관 매트릭스 도입 |
| 13-f | outcome states 9종(VERIFIED…FAILED_TERMINAL), UNKNOWN≠PASS | **부분** | `knowledge_model.py:49-64`(KnowledgeVerificationState 7종), `inspection.py:164-195`(InspectionStatus+SECURITY_CODES F28-F45), `migrations/versions/0023_v4_collections.py:101-104`(page status), `0023:148`(UNRESOLVED 재시도) | 9종 단일 taxonomy 없음 — 계층마다 다른 enum. VERIFIED_WITH_LIMITATION/REJECTED_LICENSE(→F33)/FAILED_RETRYABLE(-TERMINAL) 대응 값은 흩어져 존재하나 매핑 표가 없음 | P2 — OutcomeState 통일 enum + 각 계층 매핑 정의 |
| 13-g | model/runtime qualification receipt 11항목(image digest, artifact hash, license, SBOM, vuln scan, GPU/CUDA qual, frozen smoke, cost/latency, benchmark scope, known failure modes, rollback target) | **부분** | `packages/cir-python/src/akc_cir/models.py:209-235`(ModelRunRecord: container_digest·runtime·prompt_sha256·hardware), `benchmark/v6/registry.py:40-160`(CandidateSpec: repository/revision/artifact_sha256/license_id/status/commercial_use/promotion_eligible fail-closed), `benchmark/v6/contracts.py:107,149-186`(runtime_image_digest sha256 필수), `benchmark/v6/promotion.py:27,64-161`(G0–G8+MP0–MP6 fail-closed arbitration, LICENSE_NOT_APPROVED blocker) | **SBOM·취약점 스캔·GPU/CUDA qualification·frozen smoke·cost/latency·known failure modes·rollback target은 receipt 항목으로 부재**. §29.2도 "formal immutable baked image / formal qualification receipt / READY runtime / 200-page Stage-1 campaign 미완"으로 자체 인정([INT-02]) | **P0** — qualification receipt 스키마에 누락 7항목을 필수 필드로 추가하고 무수점 승격 차단 |

---

## §14 Canonical Knowledge IR (L1385–1496)

| # | 요구 기능 | 상태 | 코드 증거 | GAP / 비고 | 권고 |
|---|---|---|---|---|---|
| 14-a | provider 비종속 내부 truth model → projection/adapter | **구현됨** | `models.py:238-288`(CanonicalDocument cir-1.0.0), `knowledge_model.py:98-238`(CanonicalKnowledgeObject, 해시 재현성 검증 :131-158), `exports.py:16-180`(ExportProfile/SourceMap/RagChunk) | graph DB/RDF 종속 없음. renderer-neutral 원칙(docstring 명시) 준수 | — |
| 14-b | 핵심 객체 17종(SourceSystem…Projection) | **부분** | `identity.py:119-190`(source/document_version/evidence/logical id 파생), `entity.py`, `knowledge.py:39-135`(Claim/RelationAssertion/ConflictCandidate), `dependency.py:91-122`(DependencyEdge), `world_state.py:171-184`(WorldState), `events.py:88-152`(EventType/ProcessingEvent) | **Decision 객체 ✗, Policy 객체 ✗(authority rules는 임시 dataclass), BuildReceipt ✗(ModelRunRecord+benchmark image receipt가 부분 대용), ConsumptionReceipt ✗(전역 0히트)**, Event는 처리 이벤트이지 세계 이벤트(Event/Decision 계열)가 아님 | **P0** — Decision/Policy/BuildReceipt/ConsumptionReceipt 모델 추가(§21.5·§22.3의 전제) |
| 14-c | Identity 9층 분리(source_system…world_state), rename/이동에 logical_unit_id 불변 | **부분** | `identity.py:66`(IDENTITY_SCHEME_VERSION), `:119-147,150-177,180-190`(src_/dv_/ev_/ku_ 프리픽스, 경로 시드라 rename에 강건) | entity_id/claim_id/artifact_id는 문자열 규약 수준, source_object_id 별도층 없음(native_id로 흡수) | P2 — id 프리픽스/네임스페이스 규약 문서화 |
| 14-d | Evidence locator(page/block/table/row/col/char_start/end/bbox + content_hash/render_hash) | **부분** | `models.py:73-96`(SourceRef: page+bbox1000+native_object_id+time range), `:99-117`(CanonicalCell row/col/span), `:176`(block content_hash) | char_start/char_end ✗, render_hash ✗, locator 조합 스키마(단일 JSON) 없음 — locator 요소들은 객체별로 분산 | P1 — 청사진형 Locator 스키마 통합, render_hash 추가 |
| 14-e | Claim schema(claim_id/predicate/typed object/authority_class/applicability/valid_time/known_time/status/permission_scope) | **부분** | `knowledge.py:39-49`(Claim: text+origin+source_block_ids+confidence **뿐**), `authority.py:105-157`(ScopedClaim: claim_id/value/authority/scope/valid_from/to/recorded_at/required_permission/evidence_id — 메모리 dataclass), `temporal.py:61-77`(TemporalFact bitemporal) | **canonical 영속 Claim 스키마가 없고 필요 속성이 3개 타입에 분산**. predicate/typed object/permission_scope_id는 ScopedClaim에도 부분(predicate ✗) | **P0** — §14.5 필드를 갖춘 영속 Claim 모델로 통합(authority/temporal과 동일 소스 사용) |
| 14-f | External standards adapter(PROV-O/SHACL/OpenLineage/CloudEvents/OTel/JSON-LD) | **부분** | `packages/exporters/src/akc_exporters/jsonld.py:5-33`(AKMP @context JSON-LD), `packages/telemetry/src/akc_telemetry/tracing.py`(OTel) | PROV-O ✗ SHACL ✗ OpenLineage ✗ CloudEvents ✗ — 이벤트 envelope은 자체 스키마(`events.py`) | P2 — 필요시 어댑터 추가(청사진도 "옵션"으로 규정) |

---

## §15 Stable Identity & Entity Resolution (L1498–1590)

| # | 요구 기능 | 상태 | 코드 증거 | GAP / 비고 | 권고 |
|---|---|---|---|---|---|
| 15-a | false merge 금지(성능 최적화로 merge 늘리기 금지) | **구현됨** | `identity.py:245-254`(MERGE_THRESHOLD 0.92 보수 밴드), `:245-247` critical signal 결여 시 AMBIGUOUS 강제, `entity.py:443`(high_risk_auto_merges) | 설계 의도가 코드·주석으로 이행됨 | — |
| 15-b | matching pipeline 10단계(exact ID→continuity→alias→structural path→neighbour→temporal→bounded candidate→pair scoring→constrained assignment→ambiguity→ledger) | **부분** | `identity.py:231-238`(신호 7종 가중치), `:384-431`(bounded candidate window), `:546-560`(재정규화 페어 스코어), `:769-831`(1:1 constrained assignment), `:198-218`(MATCHED/NEW/AMBIGUOUS+SPLIT/MERGE/MOVED 관계), `entity.py:50-159`(티어 기반 entity merge verdict/record) | **canonical aliases 단계 ✗**, temporal compatibility는 version_distance decay(:478-479) 수준, **transition ledger ✗(15-e)** | P1 |
| 15-c | scalable candidate generation O(n×M)(partition/ID index/ANN/block assignment/collision reconciliation) | **부분** | `identity.py:384-431`(window=24 top-M 캡, 구조 근접 정렬) | **`assign_one_to_one`이 여전히 full incoming×previous 스코어 행렬 + 전역 Hungarian(`:701-766,793-797`)** — §29.2 자체 인정 bottleneck(1k units p50≈10.48s, 10k MemoryError). 파티션·ID 인덱스·ANN·block-level assignment·cross-block reconciliation 전무 | **P0** — sparse bounded matching으로 교체(§29.2 지정 과제) |
| 15-d | identity states 8종(RESOLVED/AMBIGUOUS/UNRESOLVED/SPLIT_CANDIDATE/MERGE_CANDIDATE/REKEYED/ALIAS_ONLY/REVIEW_REQUIRED) | **부분** | `identity.py:198-203`(matched/new/ambiguous 3종), `:206-218`(LogicalRelation 4종) | UNRESOLVED/SPLIT_CANDIDATE/MERGE_CANDIDATE/REKEYED/ALIAS_ONLY/REVIEW_REQUIRED 상태 없음(SPLIT_INTO 등은 관계 라벨일 뿐 상태 머신이 아님) | P1 |
| 15-e | transition ledger(ALIAS/RENAME/MOVE/SPLIT/MERGE/REKEY/DEPRECATE/RESTORE × reason/evidence/world version/reviewer/rollback) | **미구현** | entity merge undo 최소 근거만: `entity.py:143-159`(MergeRecord에 previous_members/decided_by 보존) | logical unit 수준 전이 대장 부재. 전역 검색 `transition ledger|REKEY|DEPRECATE` 0히트(benchmark/v6/ledger.py는 runpod 실행 대장) | **P0** — identity transition ledger(world version 연계) 신설 |
| 15-f | metrics 10종(false merge/split rate, recall before assignment, replay fidelity 등) | **부분** | `recompilation.py:94-101`(work_avoided), `absorption/metrics.py`, §29.1 controlled 측정치 존재 | identity 품질 지표(false merge/split rate·candidate recall·assignment consistency·replay fidelity)를 상시 산출하는 코드 없음 — 측정은 일회성 캠페인으로만 존재 | P1 |

---

## §16 Ontology & Knowledge Architecture (L1592–1684) — ※ 과제 지정 정밀 확인 영역

| # | 요구 기능 | 상태 | 코드 증거 | GAP / 비고 | 권고 |
|---|---|---|---|---|---|
| 16-a | machine-understandable domain model(types/properties/relations/actions/constraints/authority/permission/lifecycle) | **부분** | `packages/domain-packs/src/akc_domain_packs/blueprints.py:58-108`(KnowledgeBlueprint: object_types/root_views/relation_policy/validators, 실행파일·URL 금지 `_FORBIDDEN_KEYS:20-32`), `domain-packs.yaml:1-40+`(study_pack/research_pack quality_rules), `knowledge_model.py:131-138`("model-inferred relations cannot enter the verified graph" 제약) | actions/permission/lifecycle 정의 슬롯 없음. relation_policy 3종(source_explicit/structured_derived/rule_derived)만 허용 | P1 |
| 16-b | 3층 구조(Universal Core 11타입 / Domain Pack 7도메인 / User Extension) | **미구현** | `domain-packs.yaml` 전수(팩 = 노트 유형 세트: concept/definition/claim/method…) | Universal Core 타입 세트·소프트웨어/세일즈/지원/연구/계약/금융/헬스케어 도메인 팩·사용자 확장 레이어 없음. healthcare 고위험 게이트 ✗ | **P0** |
| 16-c | ontology induction 10단계(observations→candidate types→frequency/conflict→proposal→approval→version→migration) | **미구현** | 전역 검색 `induction|schema_evolution|ontology_version` 0히트 | 후보 타입 제안·승인 워크플로·버전 부여 전무 | **P0** |
| 16-d | schema evolution(versioned ontology, migration preview, affected entities/projections/queries) | **미구현** | 동上. `migrations/`는 DB 스키마 전용 | ontology 버전 축이 world manifest에도 없음(21-d 연쇄 갭) | **P0** |
| 16-e | ontology quality gates 8종(typed relations/orphan type/evidence path/constraint coverage/pack conformance/source mapping completeness/migration reversibility/permission-aware visibility) | **미구현** | `packages/quality/`(문서·페이지·테이블 품질 전용: page_coverage/table_conservation/agreement…) | 온톨로지 대상 게이트 전무. 유일하게 근접한 제약은 knowledge_model.py:131-138의 model-inferred relation 차단 1건 | **P0** |

> **§16 결론**: "ontology induction/quality gates는 구현 여부 확인" 과제 기준 **둘 다 미구현**. 현재 구현은 정적 declarative blueprint(배포 패키지 아키텍처)이며 학습·진화하는 ontology 시스템이 아님.

---

## §17 Authority · Applicability · Temporal Truth (L1686–1797)

| # | 요구 기능 | 상태 | 코드 증거 | GAP / 비고 | 권고 |
|---|---|---|---|---|---|
| 17-a | current truth resolver(rule+evidence, latest-wins 금지) | **구현됨 · 입증** | `authority.py:217-226`(순위 튜플 permission_visible→temporal_valid→scope_match→explicit_override→authority_rank→specificity→source_status→recency), `:229-260`(rank_claims), `:263-314`(resolve_authority, 동률 CONFLICTED+review), `:317-347`(판결 요소 설명) | **입증**: 22 cells × 500 = 11,000 controlled cases, failed 0(§29.1 [INT-01]). weighted-sum이 아닌 lexicographic 튜플로 청사진 의도 정확 이행 | — |
| 17-b | Bi-temporal(valid time vs known time) | **구현됨** | `temporal.py:61-111`(TemporalFact 4축+temporal_source EXPLICIT/INFERRED/UNKNOWN), `:166-206`(as_of valid_at/known_at+unknown 정책), `:227-252`(contradictions 윈도우 겹침 검출) | 문서에 없는 날짜 발명 금지(§8.1)까지 검증기로 강제(:84-93) | — |
| 17-c | applicability dimensions 12종(org/team/project/product/region/customer/contract/jurisdiction/role/purpose/classification/lifecycle) | **부분** | `authority.py:94-99`(customer/region/contract/object)+scope dict(:146-152) | 12차원 중 4개 명명 지원. team/jurisdiction/role/purpose/data classification/lifecycle은 dict에는 넣을 수 있으나 context 바인딩·검증 없음 | P2 — dimension 레지스트리 |
| 17-d | conflict outcomes 11종 | **부분** | `authority.py:74-77`(RESOLVED/CONFLICTED/NO_CANDIDATE 3종) | RESOLVED_AS_OF/EQUAL_AUTHORITY_CONFLICT/OVERLAPPING_VALIDITY_CONFLICT/MISSING_VALIDITY/INAPPLICABLE/WITHDRAWN/SUPERSEDED/PERMISSION_HIDDEN/REVIEW_REQUIRED 미분화(WITHDRAWN/SUPERSEDED는 SourceStatus 랭킹 요소 :65-71로만 존재). temporal.py:114-128 included/excluded_unknown 공개는 근접 | P1 — outcome 세분화(감사 응답 축소) |
| 17-e | authority packs(Product Ops/Contracts 우선순위 preset, 수정 가능·versioned) | **부분** | `authority.py:48-62`(AuthorityClass DRAFT→REGULATORY 데이터화, tenant override 가능), `:160-182`(ResolutionRule DSL: precedence/outcome/evidence_requirement=EXPLICIT/approved_by) | 초기 vertical 팩 프리셋·버전 저장·로드 경로 없음(규칙은 코드 호출자가 주입) | P1 — pack 번들 파일+버전 필드 |
| 17-f | policy engine(P0 deterministic+PG constraints/RLS, P1 OPA/Rego, bundle versioning/simulation) | **부분** | deterministic rules ✓(同上), PostgreSQL RLS ✓(`migrations/versions/0001_full_domain.py` 등 6개 마이그레이션에 RLS), OPA ✗ bundle versioning ✗ simulation ✗ | P0 목표는 충족, P1 항목 전부 미착수(청사진도 P1/P2로 시한 설정) | P2 |

---

## §18 Change Intelligence (L1799–1871)

| # | 요구 기능 | 상태 | 코드 증거 | GAP / 비고 | 권고 |
|---|---|---|---|---|---|
| 18-a | 12 orthogonal channels(CONTENT_SEMANTIC/LOCATOR/STRUCTURAL/READING_ORDER/VISUAL/AUTHORITY/APPLICABILITY/TEMPORAL/PERMISSION/IDENTITY/DELETION/RESTORATION) + UNSETTLED=state | **부분** | `semantic_diff.py:62-96`(DiffLevel L0–L4 + ChangeKind 13종: MODIFIED_CLAIM/AUTHORITY_CHANGED/EVIDENCE_MOVED/UNIT_REMOVED/ENTITY_CHANGED/RELATIONSHIP_*/IDENTITY_UNRESOLVED) | ChangeKind가 채널 대용. **READING_ORDER/VISUAL/APPLICABILITY/TEMPORAL/PERMISSION/RESTORATION 채널 없음**(reading_order.py:1-40는 복원 모듈이지 diff 채널 아님). UNSETTLED≠channel 원칙은 IDENTITY_UNRESOLVED로 잘 이행(:94-96) | P1 — Channel enum 전환 |
| 18-b | alignment-first diff(text/table/formula/figure typing→spatial+structural+content 호환→1:1/split/merge→유형별 diff) | **부분** | `semantic_diff.py:309+`(diff_documents), `identity.py:769-831`(1:1 matching), `reconciler.py:302-585`(paragraph/table continuation score+cross-page merge), `reading_order.py:28-36`(5-stage order 복원) | 위치이동≠의미변경(evidence_moved 분리), 표 재배치(continuation+column pattern) 처리 ✓. figure/caption 관계 유지 ✗, split/merge alignment은 라벨만 있고 매칭 알고리즘은 1:1 전용 | P1 |
| 18-c | semantic diff output(channels[]+semantic_change+locator_change+confidence+resolution) | **부분** | `SemanticChange.as_record`(`semantic_diff.py:164-176`: kind/before/after/detail/candidates), `SemanticDiff.as_record`(:209-215) | channels 배열·locator_change 구조·confidence 필드 ✗ | P2 |
| 18-d | permission change ≠ semantic rebuild(deny fast→reauthorize→cache purge→policy상 rebuild) | **미구현** | 전역 검색 0히트. `services/api/src/akc_api/deletions.py`(삭제 라이프사이클), 프로젝트 접근 `project_access*.py` 존재하나 revoke→consumer 재인가 전파 경로 없음 | dependency 그래프에 PERMISSION 채널 자체가 없어(19-a 연쇄) 구현 불가 상태 | P1 |

---

## §19 Dependency · Impact · Invalidation (L1873–1953)

| # | 요구 기능 | 상태 | 코드 증거 | GAP / 비고 | 권고 |
|---|---|---|---|---|---|
| 19-a | typed dependency(sensitivity channels[]+role+ordinal 포함 엣지) | **부분** | `dependency.py:54-87`(EdgeType 8종+엣지별 전파 방향 UPSTREAM/DOWNSTREAM/INERT 선언), `:91-122`(DependencyEdge+temporal validity) | sensitivity 채널 목록·role(PRIMARY_INPUT)·ordinal 필드 ✗ — "어떤 change channel에 민감한지"(§14.2 DependencyEdge 정의) 미흡 | P1 |
| 19-b | artifact 유형별 민감 채널 매트릭스(embedding/citation/timeline/summary…) | **미구현** | — | artifact 유형 개념 자체가 없음(recompilation artifacts는 문자열 id) | P2 |
| 19-c | impact planner(channel-aware reverse edges→transitive closure→policy filters→direct/transitive→actions) | **부분** | `dependency.py:217-270`(impact_of: BFS·최단경로·사이클 검출·깊이 제한), `:117-122`+`:202-215`(live_at 시간 필터, 전파 방향별 역순회), `:272-300`(provenance_of 역질의) | direct/transitive는 depth로만 구분, policy(permission) 필터 ✗, **rebuild/reauthorize/delete/review 액션 분류 ✗**(stale 마킹만) | P1 |
| 19-d | completeness risk 방어 7종(tracked build context/auto input capture/lint/shadow rebuild/mutation tests/fail closed…) | **부분** | fail-closed publish ✓(`world_state.py:295-306`: selective인데 equivalence 없으면 거부), 독립 fingerprint 검증 ✓(`recompilation.py:247-295`) | tracked build context·자동 입력 캡처·declaration lint·random shadow full rebuild ✗. §29.2 자체 인정: "build receipt가 hidden input을 완전 포착한다는 보장 없음" | **P0** — TrackedBuildContext(청사진 지정 장기 핵심) 착수 |
| 19-e | impact output(직접/전이/permission-only/review 그룹) | **부분** | `dependency.py:125-169`(ImpactPath.describe, ImpactReport.by_kind/explain) | permission-only·review-required 그룹핑 ✗ | P2 |

---

## §20 Selective Recompilation & CAS (L1955–2033)

| # | 요구 기능 | 상태 | 코드 증거 | GAP / 비고 | 권고 |
|---|---|---|---|---|---|
| 20-a | CompilationActionKey(canonical input roles+hashes+parent+compiler/parser/model revision+prompt/schema/policy version+params+permission scope) | **미구현** | 전역 검색 `CompilationActionKey|action_key|purity` 0히트. 근접 없음(모델 revision은 ModelRunRecord, `models.py:209-235`에 산재) | role/ordinal 보존 입력 해시 개념 전무 — 캐시 재사용의 안전 전제 부재 | **P0** |
| 20-b | purity classes(PURE/PINNED_STOCHASTIC/IMPURE/UNTRACKED) | **미구현** | 同上 | UNTRACKED→DEGRADED_UNTRACKED·HIGH_INTEGRITY 금지 규칙 이행 불가 | **P0** |
| 20-c | build flow(ActionKey lookup→verified hit reuse→TrackedBuildContext→immutable artifact+receipt→world linkage) | **미구현** | 메모리상 plan/verify만(`recompilation.py`). CAS 저장소 없음 | — | **P0**(20-a/b와 동일 이니셔티브) |
| 20-d | full rebuild oracle(dev oracle/pre-release required/shadow audit/mismatch handling) | **부분 · 입증** | `recompilation.py:247-295`(verify_equivalence: diverged/stale_left_behind/unexpectedly_rebuilt), `world_state.py:295-306`(equivalence 없는 selective publish 거부=mismatch promotion block) | dev oracle+pre-release required+mismatch block ✓. random production shadow audit·forensic·safe full rebuild fallback·incident receipt ✗. **입증**: Family B fresh holdout 9 cells failed 0, full/selective p50 ≈ 4.31×, planned rebuild fraction ≈ 1.01% (§29.1, 단 identity/change detection 제외 downstream) | P1 — shadow audit 샘플러 |
| 20-e | selective compiler metrics 10종(dirty precision/recall, stale escape, cache hit, cost/update…) | **부분** | `recompilation.py:94-101`(work_avoided_fraction), `:226-244`(stale_left_behind=stale escape 검출) | dirty precision/recall·false invalidation·cache hit율·CPU/GPU s·cost per trusted update 산출 코드 없음 | P1 |

---

## §21 Versioned World-State Runtime (L2035–2106)

| # | 요구 기능 | 상태 | 코드 증거 | GAP / 비고 | 권고 |
|---|---|---|---|---|---|
| 21-a | lifecycle 7상태(BUILDING→CANDIDATE→VERIFYING→READY_FOR_PROMOTION→ACTIVE→SUPERSEDED→RETAINED/EXPIRED/DELETED) | **부분** | `world_state.py:55-63`(BUILDING/CANDIDATE/ACTIVE/SUPERSEDED/REJECTED/ROLLED_BACK 6종) | VERIFYING·READY_FOR_PROMOTION 중간 상태 ✗(검증은 publish 내 동기 수행), RETAINED/EXPIRED/DELETED ✗(retention 정책 없음) | P2 |
| 21-b | single ACTIVE truth(active pointer authoritative, atomic verify→seal→swap→event) | **구현됨(메모리)** | `world_state.py:254-342`(publish 8단계, CANDIDATe 재확인으로 직렬화 흉내 :271-281, outbox 이벤트 동시 발행 :330-341) | Postgres 영속 계약은 주석으로만 존재(`:193-201`), **migrations에 world_state 테이블·active pointer 유니크 부분 인덱스 없음**(전역 검색 0히트) — 단일 진실 소스가 아직 디스크에 없음 | **P0** — world_state 테이블+unique partial index+트랜잭션 swap 영속화 |
| 21-c | promotion gates 12종 | **부분** | hashes match ✓(`:285-291`), selective equivalence 필수 ✓(`:295-301`), ValidationReceipt(checksums/permission/integrity/equivalence, `:70-109`), rollback point 유효성 ✓(`:354-360`: 미발행 상태 롤백 금지) | input fingerprints live ✗, unresolved high-risk identity 게이트 ✗(entity.high_risk_auto_merges는 별도 조회일 뿐), authority/temporal invariant ✗, tracked-capture ✗, policy bundle version ✗, schema/ontology version 호환 ✗(버전 축 자체가 없음) | **P0**(16-d/21-d와 연쇄) |
| 21-d | world manifest 11필드(parent/source_manifest_hash/ontology_version/policy_bundle_version/compiler_version/artifact_root_hash/permission_snapshot_hash/built_at/activated_at/verification_receipt) | **부분** | `world_state.py:112-136`(world_state_id/compiler_version/artifact_hashes/manifest_hash — 순서무관 캐노니컬 해시 ✓), WorldState에 parent/built_at/activated_at/receipt id(:174-183) | ontology_version·policy_bundle_version·permission_snapshot_hash·source_manifest_hash ✗ | P1 |
| 21-e | rollback & replay(pointer rollback, consumed world IDs 보존, valid-then/knew-then/consumed-then 구분) | **부분** | rollback ✓(`world_state.py:344-383`), replay: valid-then/knew-then ✓(`temporal.py:279-302` replay_context) | consumed-then ✗ — ConsumptionReceipt 부재(14-b 연쇄)로 "에이전트가 그때 무엇을 소비했는지" 재현 불가 | **P0**(ConsumptionReceipt와 동일 이니셔티브) |

---

## §22 Query · Retrieval · Answer Compiler (L2108–2190) — ※ 과제 지정 정밀 확인 영역

| # | 요구 기능 | 상태 | 코드 증거 | GAP / 비고 | 권고 |
|---|---|---|---|---|---|
| 22-a | query intent 10종(CURRENT/AS_OF_VALID_TIME/AS_KNOWN_AT/EXPLICIT_VERSION/CHANGE/COMPARE/IMPACT/PROVENANCE/CONFLICT/EXPLORATORY_SEARCH) | **미구현** | 전역 검색 `AS_OF_VALID_TIME|AS_KNOWN_AT|EXPLORATORY_SEARCH|QueryIntent|query_intent` **0히트**(packages+services+workers). `akc_router`는 parse-model 라우팅(preflight/estimation/champion_matrix)이지 query intent 아님 | 질의 분류기 전무 — bi-temporal/as-of 기능(temporal.py)이 질의로 노출되는 경로 자체가 없음 | **P0** |
| 22-b | retrieval lanes 7종(lexical+vector+graph+metadata+temporal+authority+visual)→rerank→permission/current-world filter, adaptive context | **부분** | lexical BM25 ✓(`retrieval/postgres.py:129-162`), pgvector ✓(`:114-124`), graph lane ✓(`:165-190`), metadata filters ✓(`retrieval/models.py:34-64`), rerank+provider attestation ✓(`engine.py:185-221`), tenant/project ACL 검증 ✓(`engine.py:172-183`), media_kind(TEXT/IMAGE/TABLE/FORMULA) 필터 ✓(`models.py:20-24`) | **temporal lane ✗**(period_start/end 등 재무 period 필터만, valid-time 인덱스 아님), **authority lane ✗**, visual page lane ✗(media_kind 태깅만), **adaptive context ✗**(고정 candidate_k/top_k, engine.py:108,242) | **P0** — lanes 완성(특히 temporal/authority) + adaptive-K |
| 22-c | answer contract JSON(answer/world_state_id/intent/status/claims/evidence/authority/valid_time/conflicts/freshness/consumption_receipt_id) | **미구현** | 전역 검색 `answer_contract|AnswerContract|consumption_receipt` 0히트. 최근접: `collection_retrieval_api.py:44-94`(hits 응답), `collection_semantic_runtime.py:3087-3095`(수치 한정 final answer gate) | 세계 상태·신선도·충돌을 함께 서명하는 답변 봉투가 없음 — world_state_id를 답변이 인용하지 못함(§21.5 consumed-world 연쇄 갭) | **P0** |
| 22-d | state-to-draft freshness auditor(draft→assertion 추출→claim 바인딩→active transitions 대비→chronology→PASS/REPAIR/ABSTAIN) | **미구현** | 전역 검색 `freshness|stale premise|state.to.draft` 0히트(workers/gpu-common의 retrieval_status는 knowledge worker 후보 검증용으로 무관) | LLM stale prior 감사 장치 전무 | **P0** |
| 22-e | answer outcomes 9종(SUPPORTED/SUPPORTED_WITH_CONFLICT/PARTIALLY_SUPPORTED/UNRESOLVED/NO_CURRENT_ANSWER/PERMISSION_LIMITED/STALE_SOURCE/REVIEW_REQUIRED/ABSTAINED) | **미구현** | 전역 검색 0히트. authority ResolutionStatus 3종(§17-d)과 verification states가 부분 재료 | outcome vocabulary 전무 | **P0** |

> **§22 결론**: "Answer Compiler 5요소(intent/lanes/contract/freshness auditor/outcomes) 구현 여부 확인" 기준 — **lanes만 부분(7종 중 4종+rerank/ACL), 나머지 4요소(intent/contract/freshness auditor/outcomes)는 전부 미구현**. 이것은 개선이 아니라 미착수 상태이며, 제품 차별화 문장(§1.2 "당신의 AI가 무엇을 알고 언제 그렇게 됐는지")이 사용자에게 도달하는 마지막 1km가 코드에 없다는 뜻이다.

---

## 우선순위 요약

### P0 (제품 핵심 약속 or 안전 전제가 코드에 없음)
1. **§22 Answer Compiler 최소 계약** — intent 분류기, answer contract(§22.3 JSON), answer outcomes, state-to-draft freshness auditor. (22-a/c/d/e)
2. **§16 Ontology 시스템** — Universal Core/Domain Pack/User Extension 3층, induction, schema evolution(versioned ontology), quality gates. (16-b/c/d/e)
3. **§20 CAS 전제** — CompilationActionKey + purity classes + TrackedBuildContext 기반 build flow. (20-a/b/c, 19-d 연쇄)
4. **§15 Identity ledger + scale** — transition ledger 신설, sparse bounded matching으로 full-matrix Hungarian 교체(§29.2 지정 bottleneck). (15-c/e)
5. **§13.7 Qualification receipt 완성** — SBOM/vuln/GPU-CUDA/smoke/rollback target 등 누락 7항목 필수화(§29.2 자체 인정 미완).
6. **§21.2 World-state 영속화** — Postgres 테이블+active pointer 유니크 인덱스(현재 메모리 semantics만).
7. **§14 canonical Claim 통합 + Decision/Policy/BuildReceipt/ConsumptionReceipt 객체**. (14-b/e)

### P1
§13-b preflight 잔여 항목(MIME/PII/license/dedup) 통합 · §13-d critical token taxonomy · §13-e evidence channel independence · §15-d identity 상태 확장 · §15-f identity metrics 상시화 · §17-d conflict outcomes 세분화 · §17-e authority pack 번들링 · §18-a/d change channels+permission-change 경로 · §19-a/c sensitivity 채널+impact actions · §20-d shadow audit · §20-e metrics · §21-c/d 게이트·manifest 보강.

### P2
§13-f outcome enum 통일 · §14-c/d locator 스키마 통합·render_hash · §14-f PROV-O/SHACL/OpenLineage/CloudEvents 어댑터 · §17-c applicability dimension 레지스트리 · §17-f OPA 어댑터 · §19-b/e · §21-a lifecycle 상태 확장.

### 이미 입증된 것(청사진 §29.1 [INT-01] 대응, 코드 근거와 병기)
- **Family B selective recompilation**: holdout 9 cells failed 0, p50 ratio ≈ 4.31×, planned rebuild fraction ≈ 1.01% ↔ `recompilation.py` + `world_state.py` publish 게이트.
- **Authority/Temporal/Lineage**: 11,000 controlled cases failed 0 ↔ `authority.py`/`temporal.py`.
- **Family A recovery**: 5,132 public docs, association p=.032(효과크기 CI는 zero 포함 — 표현 유의) ↔ `recovery_policy.py`.
- GPU smoke(OvisOCR2 RTX 4090, HTTP 200, tokens 5/5) ↔ `benchmark/runpod_eval/*` [INT-02].

### 감사 방법론 주의
- 모듈 수는 실측 27(과제 기재 41과 불일치 — `__init__` 재출력/테스트 포함 추정으로 보임).
- "미구현" 판정은 레포 전역( packages/services/workers/migrations/benchmark ) 키워드 전수 검색에 근거하나, 미래 브랜치의 미병합 구현은 범위 외이다.
