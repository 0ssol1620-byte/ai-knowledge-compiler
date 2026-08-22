# GAP AUDIT ② — 서비스 인프라 (청사진 §12·23~28 vs services/packages 대조)

## 증거 헤더

| 항목 | 값 |
|---|---|
| 감사 일자 | 2026-08-23 (KST) |
| 대상 커밋 | `9e9d69a` — docs(g0): record the final verification results - all local gates pass |
| 작업 브랜치/워크트리 | `agent/tavonel-audit-infra` @ `D:/CodexProjects/ai-knowledge-compiler-audit-infra` |
| 청사진 | `D:/TAVONEL_INDUSTRY_LEADING_FINAL_MASTER_BLUEPRINT_2026-08-22_KO.md` §12(l.1120–1264), §23(l.2192–2285), §24(l.2287–2435), §25(l.2437–2650), §26(l.2652–2752), §27(l.2754–2839), §28(l.2841–2914) |
| 대조 코드 범위 | `services/{api,scheduler,url-fetcher}/src`, `workers/`, `infra/`, `docker-compose.dev.yml`, `migrations/versions/`, `packages/`, `tests/` |
| 방법론 | API 라우트 전수 추출(91개), SQLAlchemy 테이블 전수 추출(55개), 마이그레이션 RLS 문 전수 카운트, 키워드 정규식 스캔(`connector|freshness|revision_identity|change_feed|delta_token|capability_token|tamper|hash_chain|prev_hash|merkle|obsidian|mcp|p95|access_path|specversion`), 테스트 파일명/테스트 함수명 인벤토리 |
| 판정 기준 | ✅ 구현(청사진 요구를 코드로 충족) · 🟨 부분(유사/편석 구현, 갭 명시) · ❌ 미구현(코드 부재) |

---

## 요약 (한국어)

이 리포지토리의 서비스 계층은 **"문서 분석 SaaS 파이프라인"(업로드→분석→검수→내보내기)** 으로서 실측상 견고하게 구축돼 있다. 반면 청사진 §12가 요구하는 **소스 커넥터/변경감지/신선도 계층은 데이터 모델부터 부재**한다(55개 테이블 중 `connector`·`freshness`·`change_feed`·`cursor`·`provider_revision` 관련 0건). 보안 P0(RLS 테넌트 격리, SSRF fail-closed, 삭제 영수증)와 저장소 결정(§28.5)은 청사진에 부합하며, §26.2의 세계(world) 중심 SLO 수치만 모니터링에 묶여 있지 않다. 핵심 갭 5종: **① §12 소스 어댑터 계약 전무, ② §23.4 capability token 부재, ③ §25.6 접근경로 동일성 매트릭스 테스트 부재, ④ §25.9 해시연쇄 감사 부재, ⑤ §26.2 신선도/세계 SLO 미계측**.

판정 분포: ✅ 6 · 🟨 17 · ❌ 10 (총 33행)

---

## §12 Source Connection · Change Detection · Freshness

| # | 청사진 항목 | 요구사항 | 코드 현황 (증거) | 판정 | 갭 / 권고 |
|---|---|---|---|---|---|
| 12-A | §12.2 Source adapter contract | connector_id, capabilities(change_feed/webhook/delta_token…), revision_identity(strategy), deletion_semantics, freshness_class 를 모든 connector가 구현 | **부재.** `models.py`(services/api/src/akc_api/models.py, 4,443행) 전체 55개 테이블에서 `connector|freshness|change_feed|cursor|provider_revision` 매치 0건(유일한 `etag`는 multipart upload part 용, models.py:ck_upload_parts_etag_hash). url-fetcher는 일회성 URL 수집기뿐 — `services/url-fetcher/src/akc_url_fetcher/fetcher.py:1` "Pinned-IP HTTPS fetcher", `worker.py:1` "Durable, lease-fenced URL ingestion worker". scheduler는 outbox fan-out/webhook 재시도/삭제 소비 — `services/scheduler/src/akc_scheduler/scheduler.py:1` "Durable outbox fan-out and webhook retry scheduler". 가장 근접한 원형: `CollectionSourceRoot.source_fingerprint`(models.py:2468), `CollectionFile.sha256/quick_fingerprint/last_modified_ms`(models.py:2543-2547) = content_hash revision identity의 부분 전신(클라이언트 주도 1회 스냅샷) | ❌ | 어댑터 계약 자체가 미착수. §12.2 YAML 계약을 pydantic ContractModel(packages/cir-python 패턴)로 정의하고 collection_source_roots를 첫 adapter로 승격하는 경로 권고 |
| 12-B | §12.3 Source별 change acquisition | USN/FSEvents/inotify/Git/Drive/Gmail 등 12종 소스별 획득 방식 | 부재. 파일 변경 감지 워처·CDC·provider webhook 수신 코드 없음(`watchdog|inotify|usn|fsevents|cdc` 스캔 0건). 수집은 사용자 업로드/URL 페치로만 발생 | ❌ | Personal 로컬 트랙(데스크톱 watch)과 별도 진행 필요. 현재는 F3(manual) 클래스만 존재하는 셈 |
| 12-C | §12.4 Event envelope | CloudEvents 호환 + 내부 semantic contract(specversion/type/source/id/subject/data.provider_revision/change_hint/cursor/idempotency_key) | **부분.** 트랜잭셔널 아웃박스 `OutboxEvent`(models.py:1983-2038: aggregate_type/event_type/payload JSON/available_at/published_at/dead_lettered_at/attempts)와 버전화 이벤트 카탈로그 ~52종(`packages/cir-python/src/akc_cir/collection_events.py:21-60`, 예 `file.discovered.v1`, `deletion.purge.requested.v1`) 존재. CloudEvents 공통 봉투 필드(specversion/subject/idempotency_key/cursor)는 없음 | 🟨 | event_type 버전닝 관례(.v1)는 우수. 봉투에 provider_revision·cursor·idempotency_key 확장 필요 |
| 12-D | §12.5 Event delivery semantics | at-least-once + idempotent apply + monotonic revision check + reconciliation = exactly-once logical transition. 11종 방어 | **부분.** at-least-once+DLQ 구현됨: webhook_deliveries 재시도/dead_lettered_at(models.py:2277-2295), dispatch DLQ 관리 API(`main.py:8109,8223,8275,8416` close/fallback/replay), 지수 백오프(`scheduler/retry_policy.py`). HTTP mutation 멱등성: `services/api/src/akc_api/idempotency.py:1` "Transaction-safe idempotency for tenant-scoped HTTP mutations"(migration 0008_global_mutation_idempotency). 웹훅 위조/replay 방어: HMAC 서명·DNS pinning(`akc_scheduler/webhooks.py:1-22`, `AKC_WEBHOOK_*` compose env). monotonic revision check·reconciliation은 소스 계층 부재로 미정의 | 🟨 | 배달 반쪽은 성숙. 소스 revision 비교 로직은 12-A 선행 후 착수 가능 |
| 12-E | §12.6 Freshness classes and SLO | F0~F4 클래스, last_observed_at/last_compiled_at/freshness_deadline/connector_health 노출 | 부재. freshness 관련 컬럼/메트릭 0건. url-fetch 큐 깊이·시도 횟수 메트릭만 존재(`akc_url_fetcher/telemetry.py`: akc_url_fetch_queue_depth, attempts_total) | ❌ | stale-but-current 방지(F4)는 §26.2 알림과 함께 설계 필요 |

## §23 MCP · API · SDK · A2A

| # | 청사진 항목 | 요구사항 | 코드 현황 (증거) | 판정 | 갭 / 권고 |
|---|---|---|---|---|---|
| 23-A | §23.2 API surface | /v1/compilations, /v1/worlds/active, /v1/worlds/{id}/delta, /v1/ask, /v1/compare, /v1/impact, /v1/entities, /v1/claims, /v1/evidence, /v1/reviews/{id}/decision, /v1/consumptions, /v1/projections, /v1/audit/export | **부분.** 실측 91개 라우트(services/api 전역 `@router.*` 추출): uploads/documents/jobs/pages/blocks/review-items/exports/credits/webhooks/admin·team·auth(MFA/OIDC). 세계/컴파일 표면(/v1/compilations, worlds, ask, projections, consumptions, audit/export)은 전무. review-items resolve(`main.py:5795`), exports 생성/다운로드(`main.py:6180-6574`)만 대응 | 🟨 | 현 API는 문서 분석 SaaS 표면. worlds/ask 계열은 g0 코어 패키지(akc_cir.world_state 등) 위에 라우팅 필요. OpenAPI 호환 게이트 존재(tests/contract/test_openapi_compatibility.py) — 확장 시 계약 갱신 선행 |
| 23-B | §23.3 Write/action separation | READ→PROPOSE→REQUEST ACTION(policy+approval)→EXECUTE(scoped credential+idempotency+receipt)→VERIFY | **부분.** "no source mutation"은 원칙적으로 성립 — 소스 시스템을 바꾸는 엔드포인트가 0개. 그러나 action 실행 프레임워크(approval, scoped credential, receipt) 부재. 멱등성 레이어(idempotency.py)와 영수증 테이블(audit_events, deletion_receipts)은 재사용 가능 | 🟨 | 소스 write-back 도입 전(§24.5 WRITE BACK 모드) capability token(23-C) 선행 필요 |
| 23-C | §23.4 Capability token | user/agent·tenant·tool·resource pattern·purpose·world_state_id·expiration·one-time·approval ID·max side effect·callback binding | **부재.** `capability[_ ]?token|cap_token` 코드 스캔 0건(services/workers/packages/migrations/tests 전체). 최근접: API 키 스코프(`tests/test_api_key_scopes.py`, api_keys 테이블 models.py) — tool/resource/purpose/world_state 바인딩 없음 | ❌ | A2A/에이전트 행동 이전에 반드시 필요. world_state_id 바인딩은 §31 Candidate D(World-Stamped Consumption)와 결합 설계 권고 |
| 23-D | §23.5 MCP security rules | OAuth 2.1/PKCE, audience validation, per-tool authz, SSRF 방어, output redaction, audit all calls 등 14항목 | **미구현(별도 트랙).** 이 워크트리에 MCP 서버 코드 0건(`FastMCP|mcp.server|modelcontextprotocol|stdio_server` 스캔 0). 로컬 MCP 서버는 별도 트랙(`agent/tavonel-local-mcp` 워크트리)에서 진행 중으로 확인. 하위 프리미티브는 이미 검증됨: SSRF fail-closed(`fetcher.py:16-20` 메타데이터 IP 차단, allowed_ports={443}), redirect 재검증(`tests/security/test_security_boundaries.py::test_public_url_and_each_redirect_are_revalidated`), 웹훅 DNS pinning(`webhooks.py:19-22` akc_security.validate_resolved_url) | ❌ (별도 트랙 진행 중) | 트랙 병합 시 §23.5 14항목 체크리스트를 수용 테스트로 변환할 것 |
| 23-E | §23.1 Webhook/Event 역할 | world delta/review/promotion/revoke notification | **부분.** outbound webhook endpoints/deliveries + 수동 replay API(`main.py:7522,7538,7572,7599,7641`), 암호화 시크릿(models.py:2268 encrypted_secret). world delta/promotion 이벤트 타입은 미존재(현재 job.completed/failed, export.completed 등 파이프라인 이벤트만 — models.py:2006-2028 부분 인덱스) | 🟨 | promotion/revoke 이벤트 추가 시 12-C 봉투 확장과 일괄 처리 |

## §24 Projection System — Obsidian · Directory · Graph

| # | 청사진 항목 | 요구사항 | 코드 현황 (증거) | 판정 | 갭 / 권고 |
|---|---|---|---|---|---|
| 24-A | §24.3 Obsidian vault export | TAVONEL World 디렉터리 구조 투영 | **구현.** `ExportProfile.OBSIDIAN`(`packages/cir-python/src/akc_cir/exports.py:20`), vault 파일 생성(`services/api/src/akc_api/artifacts.py:1102,1207-1240` — `export_markdown(profile=OBSIDIAN)` → `obsidian/` 프리픽스 다운로드), 볼트 조립기 `packages/exporters/src/akc_exporters/vault.py`(780행) "Obsidian Vault assembly", collection 경로 `collection_api.py:7681-7845` | ✅ | — |
| 24-B | §24.4 Markdown frontmatter | tavonel_entity_id/world_state_id/projection_version/status/effective_from/authority/source_evidence/last_compiled_at/generated | **부분.** `_note_frontmatter()` 존재(vault.py) + source_sha256/source map 계약(exports.py SourceMapEntry:41-49, block_id·revision·content_hash·source_refs 강제). 단 world_state_id·projection_version·generated:·DO_NOT_EDIT 스탬프는 0건(vault.py 내 `world_state` 매치 없음) | 🟨 | frontmatter에 world 스탬프 추가 — dual-truth 방지(Contract F)의 핵심 |
| 24-C | §24.5 Write-back policy | generated/read-only 기본, LOCAL NOTE/PROPOSE UPDATE/WRITE BACK 3모드, 무작정 canonical 취급 금지 | **부분.** conflict-safe merge 설계 존재: `MergePolicy/VaultConflict/VaultMergePlan/_ManagedSection`(vault.py 클래스 인벤토리), managed block 해시 `<!-- AKC:managed:start hash=sha256:... -->`(vault.py:41-45), 병합 프리뷰 테스트(`services/api/tests/test_vault_merge_preview.py`), 안전 마크다운 강제(vault.py:26 ensure_portable_markdown_safe). 3모드 워크플로우(사용자 선택 UX/API)는 미확인 | 🟨 | merge plan이 "managed 영역 외 사용자 편집 보존" 방향으로 구현돼 있어 LOCAL NOTE 흡수로 발전 가능 |
| 24-D | §24.6 Directory architecture packs | Developer/Sales/Research/Personal Admin 팩 | **구현.** `packages/domain-packs/src/akc_domain_packs/blueprints/` 7종(corporate-filings, course-materials, generic-mixed-corpus, legal-contracts, personal-knowledge, research-library, technical-documentation) + conformance cases(yaml), 제공 API `/domain-packs`, `/knowledge-blueprints`, `/knowledge-blueprints/plan`(`domain_api.py:38-75`), architecture plan 이벤트(collection_events.py ARCHITECTURE_PLAN_CREATED~COMPILED) | ✅ | — |
| 24-E | §24.7 Graph rendering rule | typed edges only, permission-aware, time/world selector, evidence drill-down | 부재. 그래프 렌더링/UI 코드 없음. entities/relations 테이블(models.py)과 pgvector 검색(packages/retrieval)만 존재 | ❌ | 웹앱에 Current Truth 화면이 있는지 product 감사(①) 영역 — 인프라 관점에서는 그래프 엔진 불필요(§28.5 원칙과 일치) |

## §25 Security · Privacy · Governance

| # | 청사진 항목 | 요구사항 | 코드 현황 (증거) | 판정 | 갭 / 권고 |
|---|---|---|---|---|---|
| 25-A | §25.5 Tenant isolation (P0) | tenant_id 전 객체, PostgreSQL RLS, app-level check, worker-scoped role, BYPASSRLS 금지, cross-tenant negative tests | **구현.** RLS 컨텍스트: `database.py:163-185`(set_config app.tenant_id/user_id, transaction-local), `packages/security/src/akc_security/tenant_context.py:262-270`. 마이그레이션 24개 파일에 RLS 문 83건(migrations/versions 전수 카운트; 0033_backfill_checkpoint_tenant_rls 등), 정책 clause 검증 테스트 다수(`test_v4_collection_migration.py:108-109`, `test_project_access_migration.py:87-88` 등). 워커별 DB 롤: compose `akc_scheduler_runtime/akc_dispatch_runtime/akc_analysis_runtime/akc_url_fetcher_runtime` 각각 별도 계정. cross-tenant/RLS 테스트 파일 16개(services/api/tests). 운영 알림: `infra/monitoring/prometheus-rules.yaml:51-57` AKCCrossTenantAccessDetected(sev0) | ✅ | P1(access-path matrix)은 25-B로 |
| 25-B | §25.6 Access-Path Conformance Matrix | 동일 identity+permission snapshot으로 Search/GET-by-ID/Graph/Evidence/Projection/Export/Webhook/REST/MCP/Agent context 11경로 결과 동일, unauthorized disclosure=0 | **부재.** `access[_ ]path|conformance matrix` 보안 의미 스캔 0건(domain-pack의 `conformance-cases`는 콘텐츠 적합성용, packages/domain-packs/*/tests/cases.yaml). 채널별 격리 테스트는 산발적으로 존재(`test_analysis_isolation.py`, `test_deletion_api.py`, `test_collection_api.py` 등 16개)하나 단일 매트릭스 하네스로 묶여 있지 않음. MCP/Agent context 경로는 미구현이라 매트릭스 자체가 9/11 경로만 커버 가능 | ❌ | permission-aware export가 이미 있으므로(artifacts export 경로) "동일 fixture로 N경로 순회 → 권한 결과 diff=0" 테스트 하네스를 먼저 만들 것. unauthorized disclosure=0 지표는 prometheus-rules에도 없음 |
| 25-C | §25.7 Prompt injection defense | source content is data, instruction provenance label, tool allowlist, human approval, canary secrets 등 12항목 | **부분.** `test_prompt_injection_is_detected_but_not_executed`, `test_markdown_and_table_html_reject_active_content`, CSV formula escape(tests/security/test_security_boundaries.py 11개 테스트), OOXML 매크로/path traversal 격리(같은 파일), 파서 샌드박스(workers/cpu-document/src/akc_worker_document/sandbox_runner.py, pids/mem limit compose analysis-worker, sandbox termination 알림 prometheus-rules.yaml:147-153), egress 정책 알림 AKCExternalEgressPolicyDenied(prometheus-rules.yaml:71-76). instruction provenance label·canary secrets·indirect injection benchmark는 부재 | 🟨 | 검출-비실행 원칙은 코드로 박혀 있음(강점). provenance label은 CIR BlockOrigin(exports.py:48)과 연결해 확장 가능 |
| 25-D | §25.8 Deletion and revoke | immediate deny→tombstone→discovery→purge→webhook→verification receipt, latency SLO | **부분.** `DeletionRequest` "Durable tombstone and immutable purge manifest"(models.py:2127-), `DeletionReceipt` target_id_hash+manifest_hash+deleted_count(models.py:2107-2124), 전용 durable consumer(`akc_scheduler/deletions.py:31-34` deletion.purge.requested.v1/retry), 삭제 API(`main.py:7056`), 백로그 SLO 알림 AKCDeletionBacklog>3600s(prometheus-rules.yaml:189-194, team: privacy). revoke 즉시 거부(immediate deny) 및 projection/index purge 연쇄는 세계 계층 부재로 미정의 | 🟨 | 영수증 해시 구조는 §25.9 해시연쇄로 확장하기 좋은 형태 |
| 25-E | §25.9 Tamper-evident audit | append-only table→immutable copy→hash-linked receipts→per-tenant signing→notary. promotion/action/export부터 적용 | **부분.** append 성격의 `AuditEvent`(models.py:2090-2104: actor/action/target/metadata_json/occurred_at) + 쓰기 실패 알림 AKCAuditWriteFailure "Immutable audit events cannot be written"(prometheus-rules.yaml:58-63) + 문서 버전 스냅샷 무결성 검증(`tests/test_document_versions.py:403` 객체 변조 감지, `test_document_version_api.py:445-448` 409 반환) + audit-evidence 전용 오브젝트 버킷(docker-compose.dev.yml:103 akc-audit-evidence). **hash-linked chain(prev_hash)/Merkle/per-tenant signing은 0건**(스캔 확인). audit export API(§23.2 /v1/audit/export)도 부재 | 🟨 | DeletionReceipt.manifest_hash와 audit-evidence 버킷이 이미 있어 "promotion/export 배치 해시연쇄" 1단계는 저비용 도입 가능 |
| 25-F | §25.1/25.2 Threat model & trust boundaries | 20 공격 시나리오, 6 trust boundary 선언 | **부분.** 문서: `docs/security/threat-model.md` 존재. 코드 방어: quarantine(ClamAV compose clamav 서비스, quarantine_items 테이블), default-deny 네트워크 정책(infra/kubernetes/base/network-policies.yaml: default-deny/allow-dns/ingress 분리), read_only 컨테이너+cap_drop ALL+no-new-privileges(compose x-service-defaults), supply-chain verified pins(infra/supply-chain/verified-pins.json), deployment validator(infra/security/validate_deployment.py). 20 시나리오와의 항목별 매핑 테이블은 없음 | 🟨 | OWASP Agentic/LLM Top 10 매핑을 threat-model.md에 코드 인용과 함께 갱신 권고 |
| 25-G | §25.3 Local-first privacy | raw local, encryption at rest, OS keystore, incognito, per-source retention, one-click revoke | **부분.** 서버형 구현: 메타데이터 암호화(0026/0027_collection_metadata_encryption_bridge, display_name/relative_path ciphertext models.py:2466/2531-2541), URL 인증 암호화(`akc_url_fetcher/security.py` ProtectedUrl/UrlSecretCodec "Secret-safe URL normalization and authenticated encryption"), webhook secret Fernet 암호화, AKC_PRIVATE_MODE=true 기본값(compose), privacy 설정 PATCH(`main.py:6675` /privacy). 로컬-first(데스크톱/OS keychain/로컬 모델)는 미구현 — §28.1 토폴로지 자체가 없음 | 🟨 | 개인정보 최소화 방향은 암호화 브리지로 실질 진전. local-first는 배포 토폴로지 갭(28-C)과 동일 문제 |

## §26 Reliability · Observability · SLO

| # | 청사진 항목 | 요구사항 | 코드 현황 (증거) | 판정 | 갭 / 권고 |
|---|---|---|---|---|---|
| 26-A | §26.2 Core SLO ↔ 모니터링 결합 | Personal: change detection p95 15s→5s, world activation p95 5m→60s, ASK p95 8s→4s, evidence open p95, availability, unauthorized disclosure=0, stale ACTIVE promotion=0, crash recovery RPO. Team: 99.95%, revoke ≤30s, audit durability ≥99.999% | **부분.** PrometheusRule이 존재하며 처리 파이프라인 SLO는 경보화됨(`infra/monitoring/prometheus-rules.yaml` 313행): job completion ≥95%(l.80-93), queue age >300s(l.94), cold-start p95 >60s(l.117-126), DLQ>10(l.127), deletion backlog >3600s(l.189-194), GPU cost $100/h(l.183-188), telemetry 계약 부재 시 promotion 차단(l.17-47 "Production promotion remains blocked until every required series is emitted"). **그러나 §26.2의 세계/신선도 SLO 지표(change detection, world activation, ASK latency, unauthorized disclosure, stale promotion)는 단 하나도 계측·경보되지 않음** — 해당 세계 기능 자체가 없기 때문 | 🟨 | 모니터링 골격(계약 강제 + sev0/1 등급 + runbook 링크)은 우수. worlds/ask 구현 시 동일 패턴으로 SLO 추가하는 것이 정석 경로 |
| 26-B | §26.3 Telemetry (traces/metrics/logs) | OTel 표준, 17 도메인 스팬(source.observe~agent.consume), 19 메트릭(freshness lag, activation latency, permission denies…), 민감 content log 금지 | **부분.** OTel wiring: `packages/telemetry/src/akc_telemetry/tracing.py:1` "Privacy-safe OpenTelemetry wiring for FastAPI"(OTLP grpc exporter) + redaction.py. 메트릭 계약 20+ 필수 시계열(prometheus-rules.yaml:18-42: akc_jobs_terminal_total, akc_audit_write_failure_total, akc_parallel_provider_cost_usd_total 등). 로그 마스킹(redaction.py). 단 스팬은 HTTP/작업 단위 — source.observe~world.promote 도메인 스팬 체인 없음. freshness lag·permission denies·activation latency 메트릭 없음 | 🟨 | metrics naming 관례(akc_*)와 계약 강제 알림은 그대로 재사용 가능 |
| 26-C | §26.4 Lineage interoperability | OpenLineage facet/adapter | **부분.** 자체 lineage는 존재: CDR derivative lineage(migration 0022_cdr_derivative_lineage), route_attempts/estimate_runs/page_fingerprints 테이블, PROV 스타일 source map(exports.py SourceMapEntry). OpenLineage 표준 어댑터/내보내기는 없음 | 🟨 | 외부 data-platform 연동 요구가 생길 때 어댑터 추가 (청사진도 facet/adapter로 여유 허용) |
| 26-D | §26.1 Reliability principles | failed update 시 old Active 유지, idempotent/resumable jobs, bounded recovery, per-stage receipts | **부분.** lease-fenced worker(url-fetcher worker.py:1, AKC_URL_FETCH_LEASE_SECONDS), attempt/backoff 상한(compose dispatch-worker: MAX_ATTEMPTS 5, LEASE 900s, BACKOFF MAX 300s), page-level 재시도(`main.py:5312` /pages/{id}/retry, migration 0013_page_attempts), checkpoint(0033_backfill_checkpoint_tenant_rls, collection_metadata_backfill_checkpoints 테이블), exactly-once 과금 알림(AKCParallelDuplicateCreditSuppressed prometheus-rules.yaml:256-262). Active World 격리 의미(old Active on failure)는 세계 런타임 부재로 N/A | 🟨 | 잡 신뢰성 프리미티브는 청사진 요구 수준. world promotion gate만 남음 |

## §27 Model · Router · Retrieval · Cost Strategy

| # | 청사진 항목 | 요구사항 | 코드 현황 (증거) | 판정 | 갭 / 권고 |
|---|---|---|---|---|---|
| 27-A | §27.3 Model registry | model_id/provider/revision/artifact_hash/license/data_policy/qualified_runtime/known_failures/promotion_eligible, research↔production 분리 | **구현(파서/임베딩 스코프).** `ModelRegistry`(models.py:2349-): endpoint/model_id/revision/runtime_image_digest/adapter_version/policy_version/lifecycle_state(champion/fallback/retired)/generation/canary_percent/benchmark_sha256(:2368)/recipe_sha256/approval_ref(:2370)/promoted_from_id/retired_at. 승격 게이트: generation 낙관적 잠금 + registry binding 검증(`main.py:7765-7790` MODEL_RECIPE_INVALID), rollback/retire(`main.py:7845,7919`), 공급자 revision 불일치 알림(AKCModelRevisionMismatch prometheus-rules.yaml:195-201), runtime qualification(infra/runpod/v6/runtime_qualification.py, qualification_pod.py) | ✅ | LLM 생성 스코프(cost_profile/known_failures)로 확장 시 §27.3 전체 키 수용 가능 |
| 27-B | §27.4 Router objective | Minimum Cost to Trusted Output, trusted output rate/critical false accept/cost-per-page 최적화 | **부분.** 파싱 라우터: `packages/router/src/akc_router/models.py:12-33` ProcessingMode(speed/balanced/precision/private)→RouteProfile(parse_fast_v1…parse_private_v1), 학습 라우팅 계약(estimation.py LearnedRouterShadowRecord:250, shadow 평가), parallel hedge 라우팅(parallel-runtime routing.py AdaptiveRouter:259, RouterPromotionDecision:227). 비용 측면: estimate_runs/cost_prediction_models/route_attempts 테이블, GPU cost 예산 알림. "trusted output rate 최적화 루프"는 quality 패키지(unsupported claim 알림 AKCUnsupportedAcceptedClaim l.171-176)와 분절 | 🟨 | 라우팅 프리미티브+비용 계측은 갖춰짐. objective 함수를 명시 코드로 승격할 것 |
| 27-C | §27.6 Cost controls | budget/hard caps/degrade-abstain/duplicate detection/batch | **부분.** credit ledger+중복 소비 억제(AKCCreditDoubleCharge l.177-182, duplicate suppressions l.256-262), 크레딧 예약/환불 이벤트(collection_events.py CREDITS_*), free tier abuse controls(abuse_controls.py, migration 0006_free_abuse_verification), GPU 예산 알림. 사용자 hard caps·cost forecast before initial compile는 estimate API(`main.py:3758` /documents/{id}/estimate)로 부분 존재 | 🟨 | — |

## §28 Deployment Topologies

| # | 청사진 항목 | 요구사항 | 코드 현황 (증거) | 판정 | 각주 |
|---|---|---|---|---|---|
| 28-A | §28.5 Storage decision | PostgreSQL=transactional canonical, object storage=CAS, vector index=derivative, graph projection은 measured need까지 PostgreSQL, 새 graph DB 금지, canonical 분산 금지 | **구현/부합.** `pgvector/pgvector:pg17` 단일 Postgres(docker-compose.dev.yml:18) — canonical 상태와 vector 파생을 같은 인스턴스에. 오브젝트 스토리지: MinIO 6버킷(akc-intake-quarantine/source-private/working-private/derived-private/exports-private/audit-evidence, compose:96-104, anonymous none), 드라이버 추상화(AKC_OBJECT_STORE_DRIVER=local 기본, s3-emulation profile). Redis는 선택 프로필(profiles:[durable-queue], compose:39-42). **별도 graph DB/vector DB 신설 없음 — 청사진 anti-overengineering 원칙 준수** | ✅ | — |
| 28-B | §28.3 Team SaaS 구성 | connector workers/event bus/compile workers/postgres/object CAS/indexes/policy service/world runtime/API-MCP gateway/observability | **부분.** 대응: 분석·dispatch·url-fetch·삭제 워커(compose services), k8s base(deletion-worker/gpu-worker/autoscaling/resource-policy/network-policies), migrate job(infra/kubernetes/jobs/migrate.yaml), OTel collector+Prometheus rules(infra/monitoring/), payment reconciliation cronjob. 미대응: connector workers, event bus(Redis 선택), world runtime, MCP gateway | 🟨 | 워커 패턴은 이미 "역할별 전용 DB 롤 + 전용 메트릭 포트"로 운영 등급. connector/world 두 블록이 빈칸 |
| 28-C | §28.1 Personal local | desktop shell+background service, encrypted local store, local CAS, localhost API/MCP, OS keychain, signed updater, crash-safe journal | 부재. 서버 SaaS 코드만 존재. localhost MCP는 별도 트랙(agent/tavonel-local-mcp) 진행 중. 데스크톱 셸/로컬 CAS/키체인/서명 업데이터 코드 없음 | ❌ | Personal Pro 트랙(제품 감사 ①과 배포 계획)에서 일괄 결정 필요 |
| 28-D | §28.4 Enterprise VPC/on-prem | customer-owned keys, private endpoints, SIEM, HSM/KMS, audit export | 부재(선택적 선행 조건만 존재: verified pins, deployment validator, network policies, read-only containers). SIEM export/HSM/BYOK 코드 없음 | ❌ | Phase 4 착수 전까지 문서 수준 유지가 합리적 (P2) |

---

## 종합 갭 목록 (우선순위)

| 우선순위 | 갭 | 근거 행 | 청사진 조항 |
|---|---|---|---|
| P0 | §12 소스 어댑터 계약 + freshness 필드 부재 — 자동 최신화의 전제 | 12-A, 12-B, 12-E | §12.2, §12.6 |
| P0 | §25.6 Access-Path Conformance Matrix 테스트 하네스 부재 (unauthorized disclosure=0 미측정) | 25-B | §25.6 |
| P0 | §23.4 capability token 부재 — 에이전트 action/world-stamped consumption의 전제 | 23-C | §23.4, §31 Candidate D |
| P1 | §25.9 감사 해시연쇄·서명 부재 (append-only 테이블+버킷까지만) | 25-E | §25.9 |
| P1 | §26.2 세계/신선도 SLO 미계측 — 모니터링 골격은 있으나 지표 자체가 없음 | 26-A | §26.2 |
| P1 | §24.4 projection frontmatter에 world_state_id/generated 스탬프 부재 | 24-B | §24.4, Contract F |
| P1 | §23.2 worlds/ask/projections/audit-export API 표면 부재 | 23-A | §23.2 |
| P2 | MCP 서버 — 별도 트랙(agent/tavonel-local-mcp) 진행 중, 본 워크트리 미구현 | 23-D | §23.1/23.5 |
| P2 | Personal local 토폴로지(desktop/localhost MCP/local CAS) 미착수 | 28-C | §28.1 |

## 확인된 강점 (청사진 부합)

- **§28.5 저장소 결정 준수**: pgvector 단일 Postgres + MinIO CAS + graph DB 신설 금지 원칙 그대로 (28-A).
- **§25.5 테넌트 격리 P0 완성도**: RLS 83문/24마이그레이션, 워커별 DB 롤, cross-tenant 음성 테스트 16파일, sev0 실시간 알림 (25-A).
- **§24 Projection의 실재**: Obsidian 프로필·볼트 조립기·conflict-safe merge plan·아키텍처 팩 7종은 청사진 산출물과 직결 (24-A, 24-D).
- **운영 신뢰성 프리미티브**: lease-fence·backoff 상한·DLQ replay·telemetry 계약 강제(promotion 차단)는 §26.1 원칙을 코드로 옮긴 형태 (12-D, 26-D).

*본 문서의 모든 파일:라인 인용은 커밋 `9e9d69a` 기준이며, 라인 번호는 해당 커밋 워크트리에서 실측했다.*
