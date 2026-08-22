# 갭 감사 ④ — Team/Enterprise: 청사진 §9·§10·§36-P2·§33.2 vs team/enterprise 코드

## 증거 헤더 (Evidence Header)

| 항목 | 값 |
|---|---|
| 감사 일자 | 2026-08-23 (KST) |
| 대상 커밋 | `9e9d69a` — "docs(g0): record the final verification results - all local gates pass" |
| 감사 워크트리 / 브랜치 | `D:/CodexProjects/ai-knowledge-compiler-audit-team` / `agent/tavonel-audit-team` (본 문서가 커밋되는 위치) |
| 청사진 | `D:/TAVONEL_INDUSTRY_LEADING_FINAL_MASTER_BLUEPRINT_2026-08-22_KO.md` — §9 (L910–981), §10 (L982–1065), §29.3 (L2992–3011), §33.2 (L3369–3416), §36-P2 (L3698–3713), §39.2 (L3836–3839) |
| 판독 코드 | `services/api/src/akc_api/`: team_api.py(1,000행 전체), team_models.py, project_access.py, project_access_api.py, project_access_models.py, abuse.py, abuse_controls.py, deletions.py(서두+핵심 경로), vault_merge.py, block_merge.py, auth_api.py(OIDC/테넌트 부트스트랩), main.py(라우터 마운트·테넌트 생성·settings), models.py(ReviewItem), services.py(audit) |
| 판독 마이그레이션 | `migrations/versions/` 0012_team_collaboration, 0015_project_access, 0019_oidc_mfa_auth, 0033–0037(worker authz 계열) 전수 제목 확인 |
| 판독 패키지/게이트 | `packages/security/src/akc_security/`(tenant_context.py 포함 11모듈), `infra/postgres/verify_postgres_gate.py` |
| 판독 문서 | `docs/audit/V5_TENANT_SCOPE_SURVEY.md`, `V5_CLAIM_SITE_BEHAVIOR_MATRIX.md`, `V5_WORKER_PRIVILEGE_BOUNDARY.md`, `V5_WORKER_AUTHZ_DECISION_PACKAGE.md` |
| 방법 | 정적 판독(path:line 인용) + 부재 증명 grep(SCIM/SAML, decision ledger, approval workflow, release notes, OPA, OpenFGA, Cedar, CDC, SIEM, legal hold, write-back, marketplace, agent gateway/A2A, KMS, tenant_key — services/api/src·packages·apps 전체, 전부 0히트 또는 오타판) + 문서 claim-site 대조 |
| 테스트 증거 | `services/api/tests/test_team_collaboration.py`, `test_project_access.py`, `test_project_access_migration.py` 존재 |

**핵심 질문 즉답**

1. **team_api.py에 이미 무엇이 있는가** — 팀(워크스페이스) "생성" API는 없다(테넌트는 회원가입/OIDC 최초 등록 시 부트스트랩). 있는 것은 **초대 생성·목록·취소·수락 + 멤버 목록·역할 변경·멤버 제거** 7개 엔드포인트와 6역할 모델이다 (§1 표).
2. **§9.2 authority model(decision/authority workflow)은 코드로 존재하는가** — **존재하지 않는다.** `AuthorityFact`/`collection_authority.py`는 SEC/DART XBRL 수치 팩트 검증 수집용으로 이름만 같고 무관하다 (§2.2).
3. **§10.4 vertical packages 3종은 순수 미착수인가** — **예.** Engineering&Product Ops / Technical Support / Research&Regulated Knowledge 어느 쪽도 코드·문서·스키마 흔적이 0이다 (§3.2).
4. **"RLS 7/7 감사 통과"와 코드의 일치 여부** — 문서의 "7/7"은 **RLS 통과가 아니라 `BYPASSRLS`를 아직 보유 중인 워커 역할 수(7/7, 미제거)**이다. 코드 상태(제거 마이그레이션 부재, tenant_context inert 명시)와 문서는 **정확히 일치**한다 (§6).

---

## 0. 요약

**한 줄 결론:** Team 협업의 **보안 뼈대**(초대 토큰·멤버·역할·프로젝트 접근 2계층·테넌트 RLS·감사 이벤트·abuse 컨트롤)는 프로덕션 품질로 구현·테스트돼 있으나, 청사진이 Team의 본질로 규정한 **"world" 개념(§9.1), authority policy(§9.2), world release 파이프라인(§9.4)**과 **Enterprise 전 영역(§10)·P2 백로그 14종 중 13종은 미착수**다.

| 청사진 영역 | 항목 수 | 구현됨 | 부분 | 미착수 |
|---|---:|---:|---:|---:|
| §9.1 world 분리(7계층) | 7 | 0 | 2 (project scoping, private_mode 플래그) | 5 |
| §9.2 authority model | 6 구성요소 | 0 | 0 | 6 |
| §9.3 Team 기능 | 13 | 0 | 5 | 8 |
| §9.4 world release 게이트 | 7 | 0 | 0 | 7 |
| §10.2 Enterprise 핵심 기능 | 15 | 0 | 5 | 10 |
| §10.4 vertical packages | 3 | 0 | 0 | 3 |
| §36-P2 백로그 | 14 | 0 | 1 (SSO=OIDC만) | 13 |
| §33.2 Team 패키지 | 7 | 0 | 5 | 2 |
| §33.2 Enterprise 패키지 | 8 | 0 | 1 | 7 |

청사진 §29.3의 posture("Team/Enterprise = roadmap, 상용 기능처럼 표시 금지")는 **현재 코드와 모순 없이 유지 적절**이다. 초대/멤버 관리가 구현돼 있다는 사실이 "Team 제품 출시 가능"을 의미하지 않으며, world·authority·release라는 Team의 차별화 코어가 전부 빠져 있다.

---

## 1. team_api.py 실제 현황 (질문 ①)

라우터: `POST /v1/team/*` (`team_api.py:58`), main.py 마운트 확인(`main.py:9072-9073`).

| 기능 | 엔드포인트 | 증거 | 상태 |
|---|---|---|---|
| 초대 생성 | `POST /v1/team/invitations` | `team_api.py:402-525` — 역할 에스컬레이션 가드(`:229-240`), 도메인 분리 HMAC 토큰(평문 미저장, `:127-173`), 암호화 이메일 아웃박스(`:302-368`, 재시도/dead-letter), 부분 유니크 활성 수신자 슬롯 해제(`:452-467`), 감사 `team.invitation_created` | 구현됨 |
| 초대 목록 | `GET /v1/team/invitations` | `team_api.py:528-580` — 이메일은 암호화 아웃박스 복호화 시에만 노출 | 구현됨 |
| 초대 취소 | `DELETE /v1/team/invitations/{id}` | `team_api.py:583-640` — 역할 가드, dead-letter 전환 | 구현됨 |
| 초대 수락 | `POST /v1/team/invitations/accept` | `team_api.py:643-816` — 일회용 토큰+수신자 가명 비교(`:690-716`), 신규/기존 유저 처리, 마지막 상태 전이 원자 UPDATE(`:754-772`), MFA 분기, 세션 발급 | 구현됨 |
| 멤버 목록 | `GET /v1/team/members` | `team_api.py:819-845` | 구현됨 |
| 역할 변경 | `PATCH /v1/team/members/{user_id}` | `team_api.py:906-952` — 셀프 변경 금지(`:854-858`), 행 잠금, 마지막 owner 보호(`:885-903`), 감사 | 구현됨 |
| 멤버 제거 | `DELETE /v1/team/members/{user_id}` | `team_api.py:955-994` — 대상의 API 키 동시 폐기(`:974-982`) | 구현됨 |

- **역할 모델:** `owner|admin|editor|reviewer|viewer|billing` 6역할 (`team_api.py:63-65`, DB CHECK `team_models.py:68-71`). owner는 전역, admin은 4역할만 관리 가능(`:65`, `:229-232`).
- **테넌트(팀) 생성:** team_api에 없음. 이메일 가입 시 `main.py:1051-1057`, OIDC 최초 등록 시 `auth_api.py:917-930`에서 부트스트랩(생성자=owner). 워크스페이스 이름 변경/삭제 API는 없음. 관리자 설정은 `GET /settings`(`main.py:6633`)와 `PATCH /settings|/privacy`(`main.py:6674-6677`, retention·privacy)가 전부.
- **모델/스키마:** `team_invitations`+`team_invitation_deliveries` (`team_models.py:27-111, 114-170`) — 상태 머신 CHECK, 부분 유니크 인덱스, 만료 인덱스 포함.
- **테스트:** `test_team_collaboration.py` 존재.

**판정:** 초대/멤버/권한 관리 축은 구현됨. 그러나 §9.3이 요구하는 협업 기능(의사결정 장부, 승인 워크플로, world 릴리스 등)과는 무관한 **순수 IAM 서브셋**이다.

---

## 2. §9 Team 설계 대조

### 2.1 §9.1 — Personal world를 합치는 것이 아니다 (7계층 world 분리)

청사진(L912-925): `PRIVATE PERSONAL / SHARED BY OWNER / TEAM OFFICIAL / PROJECT SCOPED / ORG POLICY / EXTERNAL AUTHORITATIVE / RESTRICTED` 7계층. "개인 memory/private source는 명시적 공유 없이는 Team World evidence가 될 수 없다."

| world 계층 | 코드 증거 | 상태 |
|---|---|---|
| PRIVATE PERSONAL | 워크스페이스/월드 개념 자체가 없음 — 개인 world는 별도 personal plane 감사 영역 | 미착수 |
| SHARED BY OWNER | 공유 범위 표기 없음. `tenants.private_mode` 플래그만 존재(`models.py` Tenant, `main.py:6654`) | 미착수 |
| TEAM OFFICIAL | 테넌트 스코프 자체가 유사 역할이나 "official" 마킹 없음 | 부분(우연) |
| PROJECT SCOPED | `project_memberships` + `project_access.py:65-86` SQL predicate — **실제 구현됨** | 구현됨(1계층만) |
| ORG POLICY | 정책 엔진/마킹 없음 | 미착수 |
| EXTERNAL AUTHORITATIVE | authority 팩트는 XBRL 수치 한정(§2.2), world 계층 아님 | 미착수 |
| RESTRICTED | 마킹/라벨 체계 없음 | 미착수 |

**갭:** 코드의 격리 모델은 **tenant → project 2계층**뿐이다. 청사진의 7계층 world taxonomy와 "개인→팀 명시적 승격 없으면 병합 금지" 원칙을 집행하는 개념(world, marking, promotion)이 코드에 없다. 개인 데이터가 팀에 유입되는 경로 자체가 아직 제품화되지 않았으므로 무병합 원칙 위반 사례는 없지만, 원칙을 집행하는 메커니즘도 없다.

### 2.2 §9.2 — Team authority model (질문 ②)

청사진(L927-949): `approved product plan > unapproved meeting note > individual draft` 같은 **결정 authority 우위**를 authority+scope+applicability+effective window+explicit override+evidence status로 정책화.

| 구성요소 | 코드 증거 | 상태 |
|---|---|---|
| decision authority 순위 | grep `decision ledger/approval workflow` 0히트. 유사 없음 | 미착수 |
| authority | `collection_authority.py:1`("authority-fact ingestion for v4 collections"), `models.py:2988` `AuthorityFact` — **SEC/DART XBRL 수치 팩트 검증 수집**으로 무관 | 미착수(이명) |
| scope / applicability | 없음 | 미착수 |
| effective window | 문서 유효기간 개념 없음(문서 버저닝은 존재하나 authority와 무관) | 미착수 |
| explicit override | 없음 | 미착수 |
| evidence status 연동 | 없음 | 미착수 |

**판정:** **decision/authority workflow는 코드로 존재하지 않는다.** 가장 가까운 존재물 3개는 전부 다른 문제를 푼다 — ① `AuthorityFact`(재무 수치 팩트), ② `ReviewItem`(`models.py:1327-1365`, 문서 품질 리뷰 큐 — resolved_by/resolution 있으나 authority 서열과 무관), ③ `block_merge.py:63-109` 3-way 병합(모델 리런 vs 사용자 편집 충돌, 팀 결정 충돌 아님).

### 2.3 §9.3 — Team 기능 13개

| # | 청사진 기능 | 코드 증거 | 상태 |
|---|---|---|---|
| 1 | workspace ontology pack | grep `ontology` (services) 0히트 | 미착수 |
| 2 | identity federation | OIDC 바인딩+트랜잭션 `auth_api.py:1,21-31`, 마이그레이션 0019 | 부분 (OIDC 로그인만, 페더레이션 프로비저닝 아님) |
| 3 | source ownership | 소스 소유자 필드/이관 API 없음 | 미착수 |
| 4 | shared decision ledger | 0히트 | 미착수 |
| 5 | approval workflow | 0히트 (ReviewItem은 품질 리뷰) | 미착수 |
| 6 | conflict review queue | `ReviewItem`(`models.py:1327`)+`block_merge.py:63-109` — 문서 품질/리런 충돌용 | 부분 (팀 결정 충돌 아님) |
| 7 | team world release notes | 0히트 | 미착수 |
| 8 | permission-aware projections | `project_access.py:65-86` predicate가 목록/질의에 적용 가능 — projection(뷰/내보내기) 계층과의 연결은 미확인 | 부분 |
| 9 | SSO/SCIM | OIDC 있음(`auth_api.py`), **SCIM/SAML 0히트** | 부분 (SSO만) |
| 10 | audit export | `AuditEvent` 기록은 광범위(`services.py:158-171`, team 이벤트 6종), **export 엔드포인트 0히트** | 부분 |
| 11 | agent registry | 0히트 | 미착수 |
| 12 | consumption lineage | 0히트 | 미착수 |
| 13 | private/shared boundary visualizer | 0히트 | 미착수 |

### 2.4 §9.4 — Team world release (7단계 게이트)

청사진(L967-980): Candidate Team World → completeness/conflict/authority/permission closure/stale dependency/review threshold 체크 → atomic Active Team World.

코드에 candidate/active world 이중 상태와 승격 파이프라인이 없다(grep `candidate.*world|world.*promot|active world` 0히트). 세계 모델이 "DB의 현재 상태"라 승격 대상 world 자체가 없다. **전 단계 미착수.** 유사한 원자적 승격 패턴은 개인 쪽 문서 버전/활성 리비전 포인터(마이그레이션 0016-0017)에 존재하나 world 단위가 아니다.

---

## 3. §10 Enterprise 대조

### 3.1 §10.1 역할 + §10.2 핵심 기능 15개

| # | 청사진 기능 | 코드 증거 | 상태 |
|---|---|---|---|
| 1 | multi-tenant or isolated deployment | 단일 DB 멀티테넌시 + RLS(§6). isolated deployment 옵션 없음 | 부분 (multi-tenant만) |
| 2 | VPC/on-prem/air-gapped | 배포 옵션 코드 없음 | 미착수 |
| 3 | source-specific CDC/webhooks | grep debezium/cdc 0히트 | 미착수 |
| 4 | domain ontology packs | 0히트 | 미착수 |
| 5 | bi-temporal resolution | 문서 버전/활성 리비전(0016-0017)은 존재하나 유효기간(as-of valid) 질의 체계는 본 감사 범위 밖 — Team/Enterprise 신규 작업 없음 | 미착수(본 축) |
| 6 | purpose/marking/role/relationship permissions | role 2계층만(`project_access.py:16-42`). purpose/marking/relationship 없음 | 부분 |
| 7 | policy-as-code | OPA/policy 엔진 0히트 | 미착수 |
| 8 | candidate/active world promotion | 0히트 | 미착수 |
| 9 | audit/legal hold | AuditEvent 기록 있음, legal hold 0히트, export 없음 | 부분 |
| 10 | retention/deletion propagation | `deletions.py:1-25` 3단계 영구삭제(tombstone→오브젝트 purge→영수증), export 포함(`:283-288`), `tenants.data_retention_days` 설정(`main.py:6674` 패치 가능) | 부분 (단일 시스템 내. 외부 시스템/프로젝션 전파 없음) |
| 11 | HA/DR | 코드 흔적 없음(인프라 영역) | 미착수 |
| 12 | world delta subscriptions | outbox 이벤트(`OutboxEvent`)는 있으나 world delta 구독 상품 없음 | 미착수 |
| 13 | agent context gateway | 0히트 | 미착수 |
| 14 | controlled write-back | 0히트 | 미착수 |
| 15 | compliance evidence pack | 0히트 | 미착수 |

### 3.2 §10.4 Initial vertical packages (질문 ③)

| 패키지 | 청사진 소스 | 코드 증거 | 상태 |
|---|---|---|---|
| Engineering & Product Ops | specs/issues/Git/releases/decisions… | grep `vertical package` 0히트, 커넥터 흔적 없음 | **순수 미착수** |
| Technical Support / Service Ops | products/error logs/manuals/RMA… | 동일 — 흔적 0 | **순수 미착수** |
| Research & Regulated Knowledge | papers/datasets/claims/policies/effective dates… | 동일 — 흔적 0 | **순수 미착수** |

고위험 자동화 금지 단서("의료 진단·신용·채용·완전 자동 법률 판단 직접 자동화 금지", L1064)는 코드 제약으로도 존재하지 않으나, 미착수 상태라 실질 위험 없음.

---

## 4. §36-P2 백로그 14개 항목

| # | 백로그 | 코드 증거 | 상태 |
|---|---|---|---|
| 1 | SSO/SCIM | OIDC 완비(`auth_api.py`, 0019). **SCIM/SAML 0히트** | 부분 (SSO O / SCIM X) |
| 2 | shared/private federation | 0히트 (private_mode 플래그뿐) | 미착수 |
| 3 | OPA policy bundles | 0히트 | 미착수 |
| 4 | OpenFGA/Cedar evaluation | 0히트. §39.2 도입 게이트(L3836-3839)는 "RLS+policy engine이 측정된 관계/목적 케이스를 못 표현할 때+path parity test" — 게이트 트리거 사건 없음 | 미착수 (게이트 미발동, 정합) |
| 5 | VPC/on-prem | 0히트 | 미착수 |
| 6 | DB CDC | 0히트 | 미착수 |
| 7 | agent gateway | 0히트 | 미착수 |
| 8 | controlled write-back | 0히트 | 미착수 |
| 9 | SIEM | 0히트 | 미착수 |
| 10 | legal hold | 0히트 | 미착수 |
| 11 | tenant key management | KMS/tenant_key 0히트. 암호화 키는 검증 아웃박스용 단일 cipher(`VerificationPayloadCipher`) 수준 | 미착수 |
| 12 | compliance automation | 0히트 | 미착수 |
| 13 | A2A | 0히트 | 미착수 |
| 14 | marketplace | 0히트 | 미착수 |

**판정:** 14종 중 13종 미착수, 1종(SSO) 부분. P2는 착수 전 단계로 청사진 posture(roadmap)와 일치.

---

## 5. §33.2 패키지별 기능 대조

### Team 패키지 (L3393-3402, USD 30–70/user/month)

| 청사진 기능 | 코드 증거 | 상태 |
|---|---|---|
| shared world | 테넌트 공간 자체는 있으나 world 개념 없음 | 부분(우연) |
| permission/authority | permission 2계층 구현됨 / authority 없음 | 부분 |
| collaboration/review | ReviewItem(문서 품질) + block_merge(리런) — 협업 리뷰 상품 아님 | 부분 |
| SSO optional | OIDC 있음 | 부분 |
| team MCP/API | services/api에 MCP 0히트(REST API만). local MCP는 personal 감사 영역 | 미착수 |
| audit | AuditEvent 기록 O, export X | 부분 |
| admin | 멤버/역할 관리 + `PATCH /settings|/privacy`(`main.py:6674-6677`) | 부분 |

### Enterprise 패키지 (L3404-3412)

| 청사진 기능 | 상태 |
|---|---|
| annual platform contract / support/SLA | 비코드(상업 항목) — 범위외 |
| VPC/on-prem | 미착수 |
| premium connectors | 미착수 |
| policy | 미착수 |
| compliance | 미착수 |
| custom ontology | 미착수 |
| agent gateway | 미착수 |

**가격 방어선 점검(L3418-3425):** "permission/audit를 부가 보안 옵션으로만 판매 금지" — permission/audit이 코어에 내장돼 있는 현재 구조(RLS 기본, team API 표준 포함)는 이 반패턴과 정합.

---

## 6. RLS/보안 상태 — §29 문서 대조 (질문 ④)

**"RLS 7/7"의 실체.** 레포 문서의 7/7은 **`BYPASSRLS` 보유 워커 역할이 7개 중 7개(=아직 하나도 disarm 안 됨)**라는 뜻이다:

- `docs/audit/V5_CLAIM_SITE_BEHAVIOR_MATRIX.md:16` — "Worker roles disarmed: **none. `BYPASSRLS` is 7/7**", `:437,454` — "remains 7/7. **No disarm migration exists.**"
- `docs/audit/V5_WORKER_PRIVILEGE_BOUNDARY.md:7-10` — 2단계 계획 중 1단계(tenant context 주입)만 배송, 2단계(BYPASSRLS 제거)는 정책 서브쿼리가 NOBYPASSRLS 하에서 권한 오류를 내는 **스키마 속성 때문에 실행 불가**를 문서화.
- `packages/security/src/akc_security/tenant_context.py:9-11` — "This is currently **inert in production**: the seven worker roles still hold `BYPASSRLS`, which is what makes injecting the context safe to ship first."

**현재 코드와의 일치 검증:** ✅ **일치.** (a) 마이그레이션 전체에서 기존 7 워커 역할의 BYPASSRLS 제거( disarm) 문구 없음 — `NOBYPASSRLS`는 0002/0004/0005/0010 등에서 **신규 역할 생성 속성**으로만 등장; (b) 0034_dual_plane_authorization/0035_claim_broker/0037_gpu_post_claim_authorization은 경계를 좁히는 방향(claim broker, callback binding)으로 정합; (c) CI가 `7/7 (not yet removed)`를 출력한다는 기술(`V5_WORKER_AUTHZ_DECISION_PACKAGE.md:600`)과 코드 상태 모순 없음. 즉 "RLS 7/7 감사 통과"라는 표현은 문서를 오독한 것이고, 실제 claim은 **"BYPASSRLS 7/7 미제거(의도된 중간 상태)"**이며 코드가 그대로다.

**RLS 커버리지 현황(문서↔코드 대조):**

| 측정 | 값 | 증거 |
|---|---|---|
| 게이트가 검증하는 테넌트 테이블(ENABLE+FORCE+정책) | 31 | `V5_TENANT_SCOPE_SURVEY.md:85-88` |
| 게이트가 검증하는 프로젝트 스코프 테이블(RESTRICTIVE) | 25 | 상동 `:88-90`, `verify_postgres_gate.py:134-149` |
| 정책 존재 테이블 총계 | 106 | `tenant_context.py:12` |
| tenant_id 보유 + CI 미검증 테이블 | 53 | `V5_TENANT_SCOPE_SURVEY.md:92-120` ("CI가 안 볼 뿐 RLS 부재를 뜻하진 않음") |
| team 테이블 RLS | ENABLE+FORCE+tenant_isolation 정책 | `0012_team_collaboration.py:36-47` |
| project ACL | 12 직접 + 10+ 간접(조인 스코프) RESTRICTIVE 정책 | `0015_project_access.py:23-120` |

**Team 코드의 보안 품질(긍정 소견):** 초대 토큰은 도메인 분리 HMAC 해시만 저장(`team_api.py:139-144`), 모든 공개 실패를 단일 응답으로 붕괴(`:180-185`), 상수시간 비교(`:170-173, 690-716`), 수신자 이메일은 HMAC 가명만 DB 저장(`:188-193`), RLS 컨텍스트 명시 설정(`:380, 661`), 멱등 뮤테이션, 행 잠금 기반 last-owner 보호. abuse 축도 실패닫힘 Redis limiter+CAPTCHA(`abuse.py:391-486`, `abuse_controls.py:61-117`), 프로덕션 Redis 강제(`abuse.py:481-482`).

---

## 7. 종합 판정 및 권고

**판정.** Team/Enterprise 축은 **"IAM 기초공사 완료, 제품 코어 미착수"** 단계다. 구현된 것(초대·멤버·역할·프로젝트 접근·RLS·감사·deletion lifecycle)은 청사진 §9.3/§10.2 목록에서 각 1~2개 항목의 "부분"으로만 인정되고, Team의 차별화 본체인 **world taxonomy(§9.1)·authority policy(§9.2)·world release(§9.4)**는 코드 개념 자체가 없다. 청사진 §29.3의 "Team/Enterprise = roadmap" posture는 **유지가 옳다** — 초대 API 존재를 근거로 Team 기능을 상용처럼 표기하면 claim 위반이다.

**권고 우선순위.**
1. (P1 후계) §9.1 world 마킹 최소 집합 — `world_scope` 마킹(private/shared/official)과 "개인→팀 명시 승격" 경로를 먼저 정의해야 §9.2/§9.4가 붙을 수 있다.
2. §9.2 authority policy는 스키마(authority+scope+window+override)와 결정 레코드부터 — 기존 `ReviewItem` 확장 또는 별도 `decisions` 테이블.
3. audit export(§9.3-10)는 기존 `AuditEvent` 위에서 저비용 착수 가능 — Team 파일럿 전 필수.
4. OpenFGA/Cedar(§36-P2-4)는 §39.2 측정 필요 게이트가 아직 발동하지 않았으므로 지금 도입 금지 — 현 2계층 predicate 유지가 정답.
5. BYPASSRLS disarm(§6)는 Team/Enterprise 이전에 해소해야 할 보안 부채 — 단, `V5_WORKER_PRIVILEGE_BOUNDARY.md`가 기록한 스키마 속성 문제(정책 서브쿼리 권한)의 해법이 먼저다.

**이 감사가 확인하지 못한 것:** 런타임 동작(서버 기동·엔드투엔드 초대 플로우)은 실행하지 않았다 — 본 감사는 HEAD `9e9d69a` 정적 판독이다. `test_team_collaboration.py` 등 테스트 파일의 존재만 확인하고 실행하지 않았다.
