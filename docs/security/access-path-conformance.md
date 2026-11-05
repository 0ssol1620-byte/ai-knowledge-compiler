# Access-Path Conformance Matrix — §25.6 11경로 권한 동등성

> **EVIDENCE HEADER**
>
> - Branch: `agent/tavonel-access-path` (worktree `ai-knowledge-compiler-apath`)
> - Base commit: `9e9d69a` (`docs(g0): record the final verification results - all local gates pass`)
> - Blueprint: `docs/north-star/TAVONEL_FTO_ABSORPTION_BLUEPRINT_v1.0.md` §1.1.E
>   `Access-Path Conformance Matrix` (L129~144) — 위임 문서 기준 §25.6.
> - Harness: `services/api/tests/test_access_path_conformance.py` (ASGI TestClient 수준,
>   실서버 구동 없음, 새 마이그레이션 없음)
> - 실행 명령:
>   `D:/CodexProjects/ai-knowledge-compiler-g0/.venv/Scripts/python.exe -m pytest services/api/tests/test_access_path_conformance.py -v`
>   (rootdir = 워크트리 루트, `pythonpath` ini로 워크트리 `services/api/src` 로드)
> - 목표 보장: 모든 접근 경로에서 동일한 tenant/project/permission 판정,
>   unauthorized disclosure = 0.

## 1. 매트릭스 정의 (경로 × 예상 결과)

측정 주체: 테넌트 A의 소유자(owner) 세션. 측정 대상: 테넌트 B에 직접 시드한 자원.
양수 컨트롤: 동일 경로를 B 소유자가 B 자원에 호출하면 200이어야 한다.

예상 결과 열의 의미:

- **판정**: 미인가 경로 요청의 허용 상태. `403/404`는 두 코드 모두 허용(거부)임을 뜻한다.
  단, 같은 경로에서 "존재하지 않는 임의 UUID"와 "타 테넌트 실존 UUID"의 상태 코드가
  달라지면 자원 존재 여부가 누출되므로 두 응답은 동일해야 한다(non-equivocation).
- **내용 누출**: 응답 본문(헤더 제외)에 B의 마커(프로젝트명·문서 제목·노트 내용·컬렉션명·
  proof evidence·B 사용자 이메일)가 포함되면 실패.
- **감사**: 거부 읽기 1건당 테넌트 A 범위의 `AuditEvent` 1건 이상 발행을 기대.

| # | path_id | 표면 (메서드 · 경로) | 청사진 범주 | 판정 | 내용 누출 | 감사 |
|---|---|---|---|---|---|---|
| 1 | `knowledge_document_get` | GET `/v1/documents/{id}` | GET by ID / guessed UUID | 403/404 | 0 허용 | 발행 기대 |
| 2 | `knowledge_provenance_evidence` | GET `/v1/documents/{id}/provenance` | Evidence lookup | 403/404 | 0 허용 | 발행 기대 |
| 3 | `knowledge_project_notes_graph` | GET `/v1/projects/{id}/knowledge` | Graph traversal | 403/404 | 0 허용 | 발행 기대 |
| 4 | `collection_integrity_view` | GET `/v1/collections/{id}/integrity` | API | 403/404 | 0 허용 | 발행 기대 |
| 5 | `collection_scene_projection` | GET `/v1/collections/{id}/scene` | API | 403/404 | 0 허용 | 발행 기대 |
| 6 | `collection_events_ledger` | GET `/v1/collections/{id}/events` | API | 403/404 | 0 허용 | 발행 기대 |
| 7 | `export_metadata_get` | GET `/v1/exports/{id}` | Export / API | 403/404 | 0 허용 | 발행 기대 |
| 8 | `export_download_content` | GET `/v1/exports/{id}/download` | Export | 403/404 + 바이트 비일치 | 0 허용 | 발행 기대 |
| 9 | `team_member_roster` | GET `/v1/team/members` | API | 200 (스코프 자체 필터) | 타 테넌트 멤버 0 | 발행 기대 |
| 10 | `proof_receipt` | GET `/v1/proofs/{id}` | Evidence lookup | 403/404 | 0 허용 | 발행 기대 |
| 11 | `trust_receipt_package` | GET `/v1/packages/{id}/trust-receipt` | Evidence lookup | 403/404 | 0 허용 | 발행 기대 |

경로 9(`team_member_roster`)만 성격이 다르다. 자원 식별자가 없는 테넌트 스코프
목록이므로 "타 테넌트 ID 지정"이 불가능하고, 대신 응답에 타 테넌트 멤버 식별 정보가
전혀 섞이지 않음을 검증한다. guessed-UUID 동등성 하위 검사는 자원 식별자가 있는
경로(1~8, 10, 11)에 적용한다.

## 2. 현재 녹색 집합 (실측)

실행: 2026-08-23, 워크트리 `ai-knowledge-compiler-apath` @ `9e9d69a`.

```text
12 items collected
11 passed, 1 xfailed in ~25s   (xfailed = test_denied_reads_emit_audit_events, strict)
```

경로 케이스 11개가 각각 검증한 것(전 경로 공통):

- 미인가 접근(A 주체 → B 자원): 자원 식별자 경로 10개는 전부 403/404 거부.
  스코프 목록 경로(`team_member_roster`)는 식별자가 없으므로 200이 정상이며
  응답에 요청자 테넌트 멤버만 포함됨을 확인.
- 내용 무누출: 응답 본문에 B 마커 6종(프로젝트명·문서 제목·노트 내용·컬렉션명·
  proof evidence·B 사용자 이메일)이 전 경로에서 0회 검출.
- 비-equivocation: 자원 식별자 경로에서 "타 테넌트 실존 UUID"와 "무작위 UUID"의
  상태 코드가 동일 — 자원 존재 여부가 판정으로 누출되지 않음.
- 양수 컨트롤: 소유자 본인 접근은 전 경로 200. `export_download_content`는
  시드 바이트와의 일치까지, `team_member_roster`는 본인 이메일 포함까지 확인.

감사 실측(`--runxfail` 관측): **11/11 경로 전부** 거부 읽기에서 `AuditEvent`
미발행 → GAP-2 확정, strict xfail로 고정.

커밋 기준 통과 판정: **xfail 아닌 케이스 전부 통과 + 네거티브/양수 컨트롤 포함 = 충족.**

## 3. GAP 섹션

정직 규칙에 따라, 현재 코드에서 확인된 격차를 하니스와 함께 기록한다.

1. **컬렉션 목록 읽기 표면 부재** — `GET /v1/collections`(테넌트 스코프 목록)가 아직
   존재하지 않는다(개별 조회 및 하위 리소스 조회만 존재). 따라서 "목록 경로"는
   개별 조회 경로(4~6)로 대체 검증했다. 목록 표면이 추가되면 매트릭스 12번 행으로
   확장해야 한다.
2. **거부 읽기에 대한 감사 이벤트 미발행** — 전 경로(11/11) 실측 결과, 미인가 읽기 거부 시
   `AuditEvent`가 발행되지 않는다(현재 감사는 auth/mutation/abuse 계열 위주).
   하니스는 이를 `xfail(strict=True)`로 고정해, 향후 거부 읽기 감사가 추가되면
   XPASS → 수집 실패로 반드시 사람 개입이 일어나도록 했다.
3. **청사진 범주 중 미포함 표면** — §1.1.E의 원 목록 중 Search(semantic retrieval
   search), Webhook deliveries, MCP resource/tool는 이번 11경로에 포함하지 않았다.
   Webhook은 `GET /v1/webhooks*` 표면이 존재하므로 후속 확장 대상 1순위다.
   MCP resource/tool는 표면 자체가 아직 없다.
4. **SQLite 어댑터에서의 RLS 한계** — `set_rls_context`는 PostgreSQL에서만
   `SET LOCAL`을 수행하고 SQLite 개발 어댑터에서는 no-op이다. 즉 이 하니스가
   실측하는 것은 애플리케이션 레이어의 tenant_id 필터 등가성이며, PostgreSQL RLS
   자체의 등가성은 별도 실측 과제다(하니스는 RLS 우회 없이 ASGI 계층만 관찰).

## 4. 하니스 사용법

```bash
# 워크트리 루트에서
D:/CodexProjects/ai-knowledge-compiler-g0/.venv/Scripts/python.exe \
  -m pytest services/api/tests/test_access_path_conformance.py -v
```

- 각 파라미터 케이스는 독립 앱 인스턴스(tmp_path sqlite)에서 두 테넌트를
  등록/시드하고, A→B 거부 판정 + 내용 무누출 + guessed-UUID 동등성 +
  B 자기 테넌트 양수 컨트롤을 순서대로 검증한다.
- 감사 관측치는 모듈 전역에 기록되며 마지막 테스트가 집계한다.
