# GAP AUDIT ③ — 제품/UX: 청사진 §5~§11 vs 두 프론트엔드 (A: apps/web, B: tavonel-blank-slate)

## 0. 증거 헤더 (Evidence header)

| 항목 | 값 |
| --- | --- |
| 감사 시각 | 2026-08-23 (KST) |
| 대상 저장소(A) | `D:/CodexProjects/ai-knowledge-compiler-g0`, HEAD `9e9d69a429910c9ddb4095ab0e9e0641c847fe05` ("docs(g0): record the final verification results") |
| 감사 워크트리 | `D:/CodexProjects/ai-knowledge-compiler-audit-product`, branch `agent/tavonel-audit-product` (HEAD과 동일 커밋) |
| 참조 앱(B, 읽기 전용) | `C:/Users/yspow/Documents/Codex/2026-08-20/tavonel-ui-tavonel-final-knowledge-compiler-3/outputs/tavonel-blank-slate` |
| 청사진 | `D:/TAVONEL_INDUSTRY_LEADING_FINAL_MASTER_BLUEPRINT_2026-08-22_KO.md` (4,173행) — §5 제품 포트폴리오(L415), §6 JTBD(L526), §7 제품 경험(L559, 10 core screens L579~700), §8 Personal Pro(L714), §9 Team(L910), §10 Enterprise(L982), §11 시스템 아키텍처(L1066) |
| FE 통합 전제 | `D:/CodexProjects/ai-knowledge-compiler-fe-adr/docs/adr/ADR-FRONTEND-CONSOLIDATION.md` — **Option 3 채택**: A(`apps/web`)가 유일한 프론트엔드 정본, B는 이식 소스로 사용 후 동결. 본 감사의 갭 서술은 이 전제를 따름 |
| 재현 수치 | A page.tsx **37** · A 비테스트 컴포넌트 **95** · A lib 모듈 **50** · B page.tsx **25** — 아래 명령으로 2026-08-23 본 호스트 재현 확인 |

```bash
cd apps/web && find src/app -name 'page.tsx' | wc -l                                  # 37
cd apps/web && find src/components -name '*.tsx' ! -name '*.test.*' | wc -l           # 95
cd apps/web && find src/lib -maxdepth 1 -name '*.ts' ! -name '*.test.*' | wc -l       # 50
find "$B/src/app" -name 'page.tsx' | wc -l                                            # 25
```

판정 어휘: **구현**(백엔드/실데이터 연결) · **부분**(화면·로직 존재, 범위/기능 일부) · **데모 전용**(픽스처/합성 데이터, 정직 라벨) · **미구현**(코드 부재).

---

## 1. 요약 판정

- **10 core screens(§7.2)**: A는 5화면을 라우트/컴포넌트로 보유(WORLD/CHANGE/ASK/REVIEW/EXPORT), 그러나 전부 **단일 샘플 픽스처 스코프**. B는 10화면 IA를 `/app/worlds/[worldId]` 한 페이지의 탭으로 **전부** 갖춘 유일한 앱(합성 Project Atlas). A에 아예 없는 화면: **Agents(§7.9) 전무**, **Current Truth 독립 화면 없음**(ask 결과에 흡수), **Projections 화면 전환 없음**(export 대체).
- **Health Scan(§5.2)**: A **전무**(코드 grep 0건). B `/health-scan` 존재 — **실분석 아님**: 11단계 브라우저 계약 데모, `HEALTH SCAN · SYNTHETIC` 라벨, 발견 수치 하드코딩(충돌 2/만료 4/식별자 충돌 1/근거 준비 18), 700ms 가짜 스캔 타이머, "no files accessed" 명시. 양쪽 모두 실제 로컬 분석기는 미구현.
- **§8.3 Personal Ontology 스키마(24개 entity type)**: 양쪽 **미구현**. A의 데모 월드는 6종 `EntityKind`(customer/contract/product/policy/region/document)만. 관계 스키마·버저닝·팩 개념 부재.
- **§8.4 자동 추론 안전구조(사용자 승인 게이트)**: 양쪽 **미구현**. `PROPOSED→…→ACTIVE` 상태 기계·migration plan 없음. A의 `PROPOSED_EVENT_TYPES`는 전혀 다른 의미(프로듀서 없는 이벤트 타입 목록). B는 Health Scan 6단계에서 identity merge 제안 승인 UI(merge/keep separate)를 **시연**만 — 유일한 참조 패턴.
- **Option 3 시사점**: B에서 이식 가치가 가장 큰 제품/UX 자산은 ① 10화면 IA 골격(AppExperience), ② review inbox 4단계 워크플로(accept→confirm→recompile→publish), ③ as-of/delta 프로젝션 뷰, ④ Health Scan 11단계 계약 데모, ⑤ agents 읽기전용 툴 테이블. 반면 Personal Ontology·승인 게이트·Health Scan 실분석·source connectors는 **B에도 없어 신규 구현**이며, Agents 화면은 UI 이식 전에 소비 영수증(consumption receipt) 데이터 원천이 백엔드에 먼저 필요.

---

## 2. §5 제품 포트폴리오

| 청사진 요구 | A (`apps/web`) 상태 | B (`blank-slate`) 상태 | 판정 | 증거 |
| --- | --- | --- | --- | --- |
| §5.1 Personal Pro — local-first desktop, files/Git/Obsidian/cloud, Personal Ontology, read-only MCP, Obsidian/directory/timeline projections | 인증 후 앱 존재(`/workspace`, `/app/world/*`, `/projects`, `/intake`, `/review`, `/documents/[id]/[view]`, `/knowledge-bases`, `/analytics`, `/activity`). 그러나 **desktop service·로컬 소스 연결·Personal Ontology·MCP 표면 없음** | `/product/personal` 마케팅 스토리("Your computer already contains a world") + Health Scan 데모가 Personal 여정 담당. 실기능 없음 | A 부분 / B 데모 전용 | A `src/app/**`, `components/authenticated-shell.tsx` L35-52 · B `src/experiences/scale/ScaleExperiences.tsx` L13-19 |
| §5.1 Team — shared workspace, identity federation, decision/authority workflow, SSO/SCIM, shared projections | `team-management.tsx` 실구현(`/v1/team/members` 조회·초대·역할 owner/admin/viewer). `/sso`는 **정직한 플레이스홀더**("Identity provider is not configured", 입력 비활성) | `/product/team`: private/shared 경계 토글 시각화 + 4단계 release flow 데모(Select projection→Inspect boundary→Assign reviewer→Publish TEAM-ATLAS-0001) | A 부분 / B 데모 전용 | A `components/team-management.tsx` L43-76, `app/sso/page.tsx` · B ScaleExperiences L25-26 |
| §5.1 Enterprise — VPC/on-prem, tenant/domain/purpose permissions, policy-as-code, audit/legal hold, promotion, agent gateway | `/admin`(owner/admin RBAC 게이트, model-operations, webhook 관리, DLQ 패널) 존재. **policy-as-code·audit export·legal hold UI 없음**(`admin-live.tsx` 내 audit grep 0건) | `/product/enterprise`: VPC/private 배포 선택 + "policy conformance demo" 버튼 — "architectural contract, not proof of a live customer deployment" 자체 명시 | A 부분 / B 데모 전용 | A `components/admin-live.tsx` L26-29 · B ScaleExperiences L42-43 |
| §5.2 Health Scan — 로컬 분석 11종 출력(sources/duplicates/identity collisions/conflicts/stale/broken links/sensitivity/projection readiness/compile work) | **전무** — `grep -rin "health.scan"` 결과 0건 | `/health-scan` 존재. 11단계 스텝(Mode→Sources→Exclusions→Manifest→Preview→Health→Ontology→Compile→Question→Evidence→Connect). Health 단계는 `HEALTH SCAN · SYNTHETIC` + 발견 수치 하드코딩 `[충돌 2, 만료 4, 식별자 충돌 1, 근거준비 18]`, 스캔은 `setTimeout 700ms` 연출. 상단 배지 "Browser contract demo · no files accessed" | **B 데모 전용 / A 미구현** | B `src/experiences/health-scan/HealthScanExperience.tsx` L8-27(전체 27행) |
| §5.3 개발자 제품 — MCP Server, API, SDK, CLI, evidence viewer, webhook, sample world | `/api-workflows`(API 콘솔 카피 페이지), `api-key-management.tsx`(실구현 `/v1/api-keys`), `webhook-management.tsx`(실구현) | `/developers`: read-only MCP 툴 계약 스니펙트(`resolve_current_fact({object, field, evidence:"required"})`) + current/as-of/delta/evidence/mcp 응답 시연(전부 픽스처) | A 부분 / B 데모 전용 | A `components/api-key-management.tsx` L31-43 · B `experiences/developers/DevelopersExperience.tsx` L13-19 |
| §5.4 우선순위 — "100 connector보다 5 source의 완전한 revision/freshness/permission semantics" | `/intake` = 컬렉션 매니페스트+사전견적(폴더 구조 보존), `upload-panel`. **P0 8종 중 Git/Obsidian/browser export/calendar/email 소스 UI 없음. P1 connector 전무** | Health Scan 1단계 소스 = projects/git/obsidian 3종 체크박스(데모) | A 부분(업로드 중심) / B 데모 전용 | A `app/intake/page.tsx` L1-20 · B HealthScanExperience L7 |

---

## 3. §6 JTBD 충족도

| JTBD (Personal) | A | B | 판정 |
| --- | --- | --- | --- |
| 1. "이 프로젝트의 현재 결정만 보여줘" | WORLD 뷰 + ask가 current term을 ACTIVE/SUPERSEDED 후보와 함께 응답 | truth 탭(현재 답+근거) | A 데모, B 데모 |
| 2. "지난주 이후 무엇이 바뀌었고 영향은?" | CHANGE 플레이가 impact.detected→recompile→activation 이벤트 스트림 재생 | changes/impact 탭 | A 데모(객체 1개), B 데모 |
| 3. "다른 이름으로 부른 파일 연결" | **없음** — entity merge UI 전무 | Health Scan 6단계 merge 제안(데모) | **미구현(A), 데모(B)** |
| 4. "어느 파일, 페이지, 셀에서 왔나" | source-viewer bbox1000 렌더링 + ask trace + `/documents/[id]/sources` | evidence 탭 4-hop 체인 | A 부분(가장 실체적), B 데모 |
| 5. "PC를 Obsidian vault로, 원본 불변" | export-dialog에 Obsidian Vault 프로필(+vault preview) — **생성된 지식 내보내기**일 뿐 PC 정리 아님 | projections/health-scan에서 언급만 | A 부분, B 데모 |
| 6. "폐기 문서 찾아줘" | review-studio가 risk-ordered findings 제공하나 parse/integrity 결함 중심. SUPERSEDED 상태 표시는 있음 | changes 탭 SUPERSEDED 라벨(데모) | 부분 |
| 7. "3개월 전 재현 (as-of)" | **없음** — as-of 질의 UI 전무 | projections 탭 as-of(Oct 16 → R7), developers asOf 응답(데모) | **미구현(A), 데모(B)** |
| 8. "Cursor/Claude가 내 world를 MCP로 읽게" | **없음** — MCP 표면 전무 | developers 페이지 계약 스니펙트(데모) | **미구현(A), 데모(B)** |

Team/Enterprise JTBD(§6.2~6.3)는 §9/§10 표와 동일 갭 — 승인 워크플로·감사 추적 UI가 양쪽 모두 데모 수준.

---

## 4. §7.2 핵심 10 화면 — 라우트 매핑 (본 감사의 핵심 표)

| # | 청사진 화면 | A 라우트/컴포넌트 | B 화면 | 판정 | 갭 |
| --- | --- | --- | --- | --- | --- |
| 1 | World Overview (sources/people/projects/decisions/facts/version/freshness/conflict count) | `/app/world` — 그래프 브라우즈+검색+kind 필터(URL 동기화), 객체/관계 카운트. 단 6종 kind 데모 픽스처. freshness·unresolved 카운트·last source change 헤더 없음 | AppExperience `overview` 탭 — current truth/world state/open reviews/evidence path 메트릭 | A 부분(데모) / B 데모 전용 | A에 freshness·충돌 카운트 등 §7.2-1 항목 미표출. 픽스처→실데이터 연결 필요 |
| 2 | Current Truth (후보 나열 + CURRENT·APPROVED·EFFECTIVE 결론) | 독립 화면 없음. ask 결과의 `resolved[]`(문서별 status 배지) + change 히스토리로 분산 | `truth` 탭 — 답+WHY THIS ANSWER(authority/valid time/locator) | A 부분 / B 데모 전용 | A는 "후보 3~4개 나열→결론" 구도가 화면 단위로 없음. ask에 흡수돼 있어 승격 필요 |
| 3 | Changes (무엇이/왜 그 분류/누가) | `/app/world/[entityId]/change` — **객체 1개(e_policy_warranty)만** `changeEligible` 게이트. 실제 이벤트 스트림을 공유 reducer로 재생(impact→recompile→world_state.activated), 관찰된 히스토리 누적 | `changes` 탭 — 4개 후보의 SUPERSEDED/UNAPPROVED/CURRENT/INCOMING 타임라인 | A 부분(데모) / B 데모 전용 | semantic/temporal/authority/permission 4분류 표출은 양쪽 모두 부분적. A는 다중 객체 확장 필요 |
| 4 | Impact (entities/claims/summaries/embeddings/projections/agents/reason path/rebuild plan) | `DEMO_IMPACT`+`IMPACT_LAYERS` = SOURCE/CLAIM/KNOWLEDGE/RETRIEVAL/AGENT 5계단 캐스케이드(7/12,841 이동) — change 플로우 안에 렌더 | `impact` 탭 — affected 4 / checked-unchanged 3 | A 부분(모델은 더 풍부, 픽스처) / B 데모 전용 | A의 5계단 모델이 청사진 8항목과 가장 근접하나 전부 fixture. 독립 라우트 없음(change에 종속) |
| 5 | Evidence (page/cell/span/image region/revision hash/status/permission/valid·system time) | `source-viewer.tsx` — 실제 bbox1000 오버레이 페이지 뷰어(회전/확대), `/documents/[id]/sources` provenance, ask `trace[]` | `evidence` 탭 — ANSWER→FACT→LOCATOR→SOURCE 4-hop + 소스 다이얼로그(행 하이라이트) | A 부분(가장 실체적) / B 데모 전용 | revision hash·valid/system time·permission 동시 표출 없음. image region 근거는 미확인 |
| 6 | Conflicts & Review Inbox (9종: entity merge/authority/validity overlap/missing date/contradiction/sensitive/permission/untracked build/stale consumer) | `/review`→integrity console(무결성 결함 큐+결정 패널, "Human decisions only where evidence stops") + `review-studio.tsx`(risk-ordered 큐, `/v1/review-items/{id}/resolve` 실호출, scope preview) — **parse/integrity 결함 중심** | `review` 탭 — 1건 권한 변경 리뷰: Accept incoming authority→Confirm affected set→Recompile 4 objects→Publish SAMPLE-018293 | A 부분 / B 데모 전용 | 청사진 9종 중 **entity merge·authority 충돌·sensitive source·stale consumer 유형의 큐가 양쪽 없음**. B의 4단계 게이트 워크플로는 이식 가치 최상 |
| 7 | Ask (8 intent: CURRENT/AS-OF/CHANGE/COMPARE/WHY/IMPACT/PROVENANCE/CONFLICT) | `/app/world/[entityId]/ask` — 단일 데모 질문, `askEligible` 객체만, "simulated query… no live model call" 정직 라벨. answer+guarantees+trace+source_ref 반환 | `ask` 탭 — RESOLVED ANSWER + ANSWER CONTRACT(status/scope/evidence) | A 부분(데모) / B 데모 전용 | 8 intent 중 CURRENT만. as-of/compare/why/impact 질의 타입 미구현. 실모델 연결 없음 |
| 8 | Projections (World/Graph/Directory/Obsidian/Timeline/Table/Evidence map/API view) | export-dialog 4프로필(Portable Markdown/Obsidian Vault/RAG JSONL/JSON-LD + vault preview, 실 downloadUrl), `knowledge-studio` 관점 전환(Document/Entity/Risk/**Timeline**/Evidence) | `projections` 탭 — current/**as-of**/**delta**/**semantic map** 4뷰 전환 | A 부분 / B 데모 전용 | A는 "내보내기 파일" 중심 — 청사진의 "같은 world의 뷰 전환" 경험 없음. Directory/Table/API view 양쪽 없음. B의 as-of/delta 전환은 이식 대상 |
| 9 | **Agents** (connected clients/consumed world state/consumed claims/MCP tools invoked/action requests/approvals/replay) | **전무** — `grep -rln "Agents\|MCP"` in components/app → 0건 | `agents` 탭 — 읽기 툴 테이블(discover_objects/resolve_current_fact/inspect_evidence=Read, publish_world=Denied "Human review required") + "browser sample cannot connect an external agent" | **A 미구현 / B 데모 전용** | **양쪽 모두 실 아님. A는 IA조차 없음.** UI 이식 전에 consumption receipt·tool 호출 로그의 백엔드 원천 필요(§11 Consumption Lineage plane) |
| 10 | Security (sources enabled/exclusions/cloud transmissions/model/provider/keys/retention/delete/revoke/audit export/permissions) | `/settings` — retention 기간+external processing policy(서버 연동, 권한 없으면 읽기 전용 안내), `api-key-management`(`/v1/api-keys`), admin RBAC | `security` 탭 — 4타일 정책 계약(읽기전용 소스/private evidence/audit state/agent authority) | A 부분 / B 데모 전용 | 소스별 enabled·exclusion 관리, cloud 전송 내역, 모델/프로바이더 표시, revoke 전파, audit export UI 없음 |

§7.1 Film→Tutorial→Tool: A `/film`(Evidence in Motion 60초 필름, FOLYNTA 브랜드)=DIRECTOR MODE, 데모 월드=GUIDED PROOF/EXPLORE, 인증 후 앱=REAL APP — 3단계는 존재하나 필름이 FOLYNTA 브랜드로 정합성 저해. B는 Health Scan 11단계가 GUIDED PROOF를 대체. §7.3 시각 원칙(측정치 라벨, no fake progress, no-WebGL 동등 인과)은 양쪽 모두 준수(각각 claims:check 게이트 / sample-mode 라벨).

---

## 5. §8 Personal Pro 설계

| 청사진 요구 | A | B | 판정 |
| --- | --- | --- | --- |
| §8.1 설치 10단계(LOCAL MODE→opt-in→exclusion→processing location→model/provider→compile preview→estimated work→ontology proposal→first build→evidence-backed question) | `tavonel-onboarding.tsx` 4단계(Goal/Document type/Privacy/First upload) — 10단계 중 3단계 부분 커버. processing location·estimated work/cost/storage·ontology proposal 단계 없음 | Health Scan 11단계가 청사진 10단계와 거의 1:1(Mode/Sources/Exclusions/Manifest/Preview/Health/Ontology/Compile/Question/Evidence/Connect) — 단 브라우저 데모 | A 부분(4/10) / B 데모 전용(구조 일치) |
| §8.1 기본 모드 4종(Local Only/Local+Approved Cloud/Private Cloud/Enterprise Managed) | onboarding Privacy 3선택지(외부처리 묻기/금지/승인 프로바이더) — 모드 계약 아님 | Health Scan 0단계 local/team/enterprise 3버튼 + Outbound Manifest 단계(원본 미전송/embeddings 스코프/diagnostics off 명시) | 양쪽 부분 |
| §8.2 P0 sources 8종(files, Markdown/Obsidian, PDF/DOCX/PPTX/XLSX, images, Git, browser export, calendar export, email archive) | 업로드+컬렉션 매니페스트만. Git·browser·calendar·email 소스 UI 없음 | Health Scan 1단계 projects/git/obsidian 3종(데모 체크박스) | **미구현(A)** / 데모(B) |
| §8.3 Personal Ontology — 24 entity type + 10 관계 예 | `EntityKind` 6종(customer/contract/product/policy/region/document, 데모 픽스처용). 24종 스키마·관계 타입·버저닝 전무. `relation.created.v1` 이벤트 타입만 존재 | project.atlas 객체 소수(데모). 스키마 정의 없음 | **양쪽 미구현** |
| §8.4 자동 추론 안전구조 — Observed→Candidate→review→versioned pack→migration→ACTIVE, 상태 6종(PROPOSED/ACCEPTED/REJECTED/DEPRECATED/MIGRATION_REQUIRED/ACTIVE) | **전무.** 주의: `product-event.ts` L76의 `PROPOSED_EVENT_TYPES`는 "프로듀서 없는 이벤트 타입" 목록으로 무관 | Health Scan 6단계 — "Identity is proposed, never silently merged" + merge/keep separate 승인 버튼(선택에 따라 open conflicts 2/3 변동). **승인 게이트의 참조 UI 패턴**이나 상태 기계·버저닝·migration plan 없음 | **양쪽 미구현** — B에 UI 패턴만 존재. 이 감사의 최대 안전 갭 |
| §8.5 차별적 답변 — 필수 출력 9종(answer/status/current-as-of/authority/evidence/conflict/last compiled/stale dependents/world_state_id) | ask가 answer+status(배지)+guarantees+trace+source_ref 반환. world_state는 reducer에 존재하나 응답에 `world_state_id` 미표출. conflict/stale dependents 필드 없음 | ask 탭 status/scope/evidence 3종 | 부분(양쪽) — 9종 중 4~5종 |
| §8.6 Personal MCP — Resources 8종 URI, Read tools 9, Controlled tools 5, 금지 6 | **전무** (`tavonel://`, `ask_current`, `request_recompile` 등 grep 0건) | developers 페이지 read-only MCP 계약 스니펙트 + agents 탭 Read/Denied 테이블(데모) — "publish_world Denied, Human review required"는 §8.6 금지 조항과 정합 | **미구현(A)** / 데모(B) |

---

## 6. §9 Team / §10 Enterprise

| 청사진 요구 | A | B | 판정 |
| --- | --- | --- | --- |
| §9.1 7개 가시성 구분(PRIVATE PERSONAL…RESTRICTED) | 없음 | product/team 데모의 PRIVATE/SHARED/STOPPED 3상태 | 미구현(A) / 데모(B) |
| §9.2 authority model(authority+scope+applicability+effective window+override+evidence status) | `RESOLUTION_BASIS`(current/authority/applicability)+`TEMPORAL_STATUS`(ACTIVE/SUPERSEDED/EXCEPTION) 계약 타입 존재 — 데모 스코프 | truth/changes 탭에서 authority 서열 시연 | A 부분(계약 타입) / B 데모 |
| §9.3 13 기능 중 보유 | 멤버/역할 관리(`/v1/team/*`)만. ontology pack·identity federation·source ownership·decision ledger·approval workflow·release notes·permission-aware projections·SSO/SCIM UI·audit export·agent registry·consumption lineage·boundary visualizer **전부 없음** | boundary visualizer+release flow 데모만 | A 1/13 부분 / B 데모 |
| §9.4 Team world release 7게이트 → atomic Active | 없음(개인 데모 월드의 activation만) | release flow 4단계 데모(TEAM-ATLAS-0001) | 미구현 / 데모 |
| §10.2 Enterprise 핵심 14기능 | admin RBAC·webhook 관리·DLQ·model-operations만. multi-tenant UI·policy-as-code·promotion UI·audit/legal hold·retention propagation·delta subscriptions·agent gateway·write-back control·compliance pack **전부 없음** | deployment 선택+policy conformance 데모 | A 3~4/14 부분 / B 데모 |
| §10.4 vertical packages 3종(Eng&ProdOps/Support/Research) | 없음 | 없음 | **양쪽 미구현** |

---

## 7. 갭 → Option 3 실행 매핑 (권고 작업 분해)

| 우선순위 | 갭 | Option 3 하의 조치 | 원천 |
| --- | --- | --- | --- |
| P0 | 10화면 IA 부재(A) — Agents 전무, Current Truth/Projections 화면 없음 | B AppExperience의 10탭 IA를 A `/app` 하위로 이식하되 A의 실 reducer(`reduceProductEvent`)/SSE에 연결. 탭→라우트 승격은 PAGE_MANIFEST 등록 필요 | B `AppExperience.tsx` L10-17 |
| P0 | §8.4 추론 안전구조·승인 게이트(양쪽 미구현) | 신규 구현: ontology proposal 상태 기계(6상태)+사용자 승인 UI. B Health Scan 6단계 merge 제안 패턴을 참조 카피 | 신규 + B 참조 |
| P0 | Health Scan 전무(A) | 1차: B 11단계 계약 데모 이식(정직 라벨 유지, claims:check 통과 확인). 2차: 로컬 분석기는 데스크톱 런타임 과제로 분리 | B `HealthScanExperience.tsx` |
| P1 | Review Inbox의 conflict taxonomy 미커버 | B review 탭의 4단계 게이트(accept→confirm→recompile→publish)를 A review-studio에 authority/merge 유형으로 추가. `/v1/review-items` 계약 확장은 백엔드 감사(②)와 합의 | B AppExperience review 탭 |
| P1 | as-of/delta 질의·프로젝션 없음(A) | B projections 탭 4뷰 전환 이식 + ask에 AS-OF intent 추가. 백엔드 resolver 의존(① 감사 영역) | B AppExperience projections 탭 |
| P1 | Agents 화면 데이터 원천 | UI 이식에 앞서 consumption receipt/MCP tool 로그 API 확인 — 없으면 화면을 "honest empty"로 출시(§35 no-fake-progress) | 신규 |
| P2 | §8.3 Ontology 24종 스키마 | `@akc/contracts`에 entity type/relation enum 추가 후 A UI에 스키마 뷰. B에는 원천 없음 | 신규 |
| P2 | Security 화면 미커버 항목(소스별 exclusion, audit export, revoke 전파) | A `/settings` 확장. B에는 원천 없음 | 신규 |
| P2 | §9/§10 대부분 | Team/Enterprise는 데모 스토리(B product/team, product/enterprise)를 마케팅으로 이식(ADR Step 5 범위)하고, 기능은 로드맵 §5.4 순서대로 후순위 | B ScaleExperiences |

---

## 8. 결론 (한국어 요약)

청사진 §5~§11 대조 결과, **B(tavonel-blank-slate)가 10 core screens의 IA를 전부 품은 유일한 앱**이지만 그 실체는 합성 Project Atlas 위의 정직한 데모(`Sample world · synthetic data` 라벨, 백엔드 호출은 결제 버튼 1곳뿐)이고, **A(apps/web)는 5개 화면을 실제 이벤트 reducer·백엔드 계약과 함께 갖추지만 픽스처 스코프에 머물며 Agents 화면이 전무**하다. Health Scan은 A에 존재하지 않고 B의 `/health-scan`은 11단계 계약 데모일 뿐 실분석기가 아니다(수치 하드코딩, "no files accessed"). §8.3 Personal Ontology 24종 스키마와 §8.4 자동 추론 안전구조(6상태+사용자 승인 게이트)는 **두 앱 어디에도 구현돼 있지 않으며** — 이것이 본 감사 영역의 최대 갭이다 — B의 identity-merge 승인 UI와 4단계 review 게이트가 유일한 참조 구현물이다. Option 3(A 정본+B 이식) 전제에서 즉시 이식 가능한 자산은 10탭 IA·Health Scan 데모·as-of/delta 뷰·agents 읽기전용 툴 테이블이고, Ontology 스키마·승인 게이트 상태 기계·Health Scan 실분석·source connectors는 양쪽에 원천이 없어 신규 구현이며, Agents 화면은 UI보다 consumption-lineage 데이터 원천이 선행 과제다.

## 부록 A — A(apps/web) 인벤토리 스냅샷 (2026-08-23)

- 라우트 37: 공개(`/`, `/home`, `/film`, `/benchmarks`, `/integrity`, `/notices`, `/design/*`), 인증(`/login`, `/signup`, `/forgot-password`, `/verify-email`, `/sso`), 앱(`/workspace`, `/app/world`, `/app/world/[entityId]{,/ask,/change,/source}`, `/projects`, `/intake`, `/review`, `/documents/[id]/[view]`, `/knowledge-bases`, `/analytics`, `/activity`, `/api-workflows`), 계정/운영(`/account`, `/billing`, `/usage`, `/settings`, `/admin`, `/onboarding`, `/quick-convert`, `/creative-review/*`)
- `/app/[[...slug]]` catch-all은 title/description/action 카피만 렌더하는 플레이스홀더(`APP_PAGE_COPY`, `lib/tavonel-content.ts` L940+) — jobs/recipes/exports/api 콘솔 등은 실기능 아님
- 핵심 계약: `product-event.ts`(zod 이벤트 22종, TEMPORAL_STATUS, RESOLUTION_BASIS), `world-projection.ts`(공유 reducer `reduceProductEvent`), `demo-workspace.ts`(데모 픽스처+이벤트 스케줄), `world-view-model.ts`

## 부록 B — B(tavonel-blank-slate) 인벤토리 스냅샷 (2026-08-23, 읽기 전용)

- 라우트 25 + api 3(`/api/billing/checkout`, `/api/billing/portal`, `/api/webhooks/stripe`): 마케팅(`/`, `/pricing`, `/product{,/personal,/team,/enterprise}`, `/health-scan`, `/evidence{,/sec,/sec-observatory}`, `/research`, `/developers`, `/docs`, `/security`, `/trust`, `/terms`, `/privacy`, `/asset-lab`), 앱(`/app`, `/app/worlds/[worldId]`), Clerk(`/sign-in`, `/sign-up`), 보호(`/workspace`, `/account`)
- 제품 경험의 전부는 `experiences/app/AppExperience.tsx`(61행, 10탭) + `lib/tavonel-world.ts`(98행, localStorage 지속 reducer) — 백엔드 호출 없음
