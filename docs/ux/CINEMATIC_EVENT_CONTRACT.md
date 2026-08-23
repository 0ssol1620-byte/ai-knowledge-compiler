# Cinematic Event Contract — Canonical ProductEvent 대비 Divergence 기록

> 근거: `TAVONEL_CINEMATIC_COMPILATION_REPLAY_MASTER_SPEC_v2.0_FINAL_KO_2026-08-23.md`
> §9(ProductEvent · Replay · Live 계약) 및 Phase 1(Event contract)
> 기준 커밋: `4466642` (integration/g0-consolidation) · 작성: agent/p0-cinematic-event-contract

## 1. Phase 1 산출물 (canonical 정본)

스펙 §9.2 권장 정본을 다음과 같이 배치했다.

| 산출물 | 경로 |
| --- | --- |
| JSON Schema | `packages/contracts/product-event.schema.json` |
| Python 타입 + validator (stdlib 전용) | `packages/contracts/src/akc_contracts/product_event.py` |
| TypeScript 타입 + type guard | `apps/web/src/lib/cinematic/product-event.generated.ts` |
| Conformance 테스트 | `tests/unit/test_product_event_contract.py` |

비고: `packages/contracts/src` 는 wheel 패키지(`[tool.hatch.build.targets.wheel]`)에는
아직 등록하지 않았고 루트 `pyproject.toml` 의 `tool.pytest.ini_options.pythonpath` 에만
추가했다. 판매(wheel) 포함 여부는 producer conformance(Phase 1 후반)와 함께 결정할 것.

### Canonical envelope (§9.4)

```
schema_version = "1.0" (pinned)
event_id       : 비어있지 않은 문자열
event_type     : 등록된 22종 중 하나 (§9.3 A 8종 + B 14종)
sequence       : integer >= 1, scope별 monotonic (§9.6)
occurred_at    : RFC 3339 문자열
monotonic_offset_ms? : number (선택, replay 결정론용)
mode           : "demo" | "live"
scope          : { kind: "job", job_id, document_id?, page_number? }
               | { kind: "collection", collection_id, job_id? }
               | { kind: "demo", fixture_id? }
payload        : unknown (envelope 레벨에서 불투명, 타입별 payload contract은 별도)
```

모든 레벨에서 `additionalProperties: false` — 알 수 없는 키는 거부한다(드리프트 생산자는
조용히 절반만 렌더되는 대신 validation 실패로 드러난다).

## 2. Envelope 레벨 대조 — `apps/web/src/lib/product-event.ts` vs canonical

| # | 항목 | canonical (§9.4) | 현행 product-event.ts | 판정 |
| --- | --- | --- | --- | --- |
| E1 | `schema_version` | `"1.0"` const | `z.literal("1.0")` (L39,198) | ✅ 일치 |
| E2 | `event_id` | string ≥1 | `z.string().min(1)` (L199) | ✅ 일치 |
| E3 | `sequence` | integer ≥ 1 | `z.number().int().positive()` (L200) | ✅ 일치 |
| E4 | `occurred_at` | 비어있지 않은 문자열(format: date-time) | `z.string().min(1)` (L201) | ✅ 일치 (형식 검사 강도 차이는 허용 범위) |
| E5 | `monotonic_offset_ms` | **있음** (선택 number) | **없음** | ❌ 누락 — canonical 신규 필드. replay seek/결정론 해싱에서 필요 |
| E6 | `mode` | `"demo" \| "live"` | `z.enum(["demo","live"])` (L220) | ✅ 일치 |
| E7 | `scope` union | job/collection/demo (§9.4 그대로) | 동일한 3-kind discriminated union (L172-195) | ✅ 일치 |
| E8 | 최상위 `collection_id` | **없음**(scope.collection_id 뿐) | legacy 선택 필드 (L212, normalize L633-642) | ❌ 불일치 — canonical은 거부(additionalProperties:false). 마이그레이션 필요 |
| E9 | 최상위 `document_id` / `page_number` | **없음**(job scope 내부에만) | legacy 선택 필드 (L221-223) | ❌ 불일치 — 동일. world-projection이 이 최상위 필드를 직접 읽는다(§4 참조) |
| E10 | `event_type` enum | 22종(§9.3 A+B) | `REUSED_EVENT_TYPES`(8) + `PROPOSED_EVENT_TYPES`(14) = 동일 22종 (L52-96) | ✅ 이름 전부 일치 |

### event_type 이름 대조 상세

**A. 이미 backend 이름이 존재하는 8종 — 이름 일치 확인**

`collection.discovery.progress.v1`, `file.discovered.v1`, `file.duplicate.detected.v1`,
`page.route.selected.v1`, `verification.failed.v1`, `recovery.completed.v1`,
`entity.resolved.v1`, `relation.created.v1`

→ `akc_cir.collection_events.CollectionEventType` (packages/cir-python/src/akc_cir/collection_events.py L21-98)과
문자열까지 전부 일치. **이름은 문제가 아니며, 문제는 payload 계약이다(§3).**

**B. client proposal 14종 — 이름 일치 확인**

`revision.family.detected.v1`, `document.profiled.v1`, `document.rerouted.v1`,
`knowledge.unit.created.v1`, `conflict.detected.v1`, `authority.resolved.v1`,
`source.revision.created.v1`, `world_state.activated.v1`, `impact.detected.v1`,
`recompile.progress.v1`, `recompile.completed.v1`, `answer.resolution.started.v1`,
`answer.source.resolved.v1`, `answer.emitted.v1`

→ 스펙 §9.3 B 리스트와 전부 일치. 단 **producer가 없다**(fixture-only, product-event.ts L63-91).

**C. §9.3 C 후보 8종 미포함 근거**

`source.connection.authorized.v1` 등 C 리스트는 "새 backend event를 만들기 전 receipt/artifact에서
derive 가능한지 검토" 대상이다(스펙 L1616-1631). 정본 enum에 넣으면 미확정 이름이 계약처럼
보이므로 의도적으로 제외했다. DERIVED beat로 확정될 때 enum에 추가한다.

## 3. Payload 불일치 — A 8종 상세 (실측)

Backend 필수 payload 출처: `COLLECTION_EVENT_REQUIRED_PAYLOAD_FIELDS`
(packages/cir-python/src/akc_cir/collection_events.py, `_contract(...)` 정의).
Client 선언 출처: apps/web/src/lib/product-event.ts 의 zod payload.
identity 필드는 backend가 payload 안에 요구하고 client는 envelope.scope로 옮겼다는
구조적 차이가 공통으로 깔려 있다.

| event_type | backend 필수 payload | client zod payload | 불일치 판정 |
| --- | --- | --- | --- |
| `collection.discovery.progress.v1` | `collection_id, source_root_id, discovered_files, discovered_bytes, manifest_revision` (L123-131) | `discovered_files` 필수 + `files_total` 선택 (L235-241) | ❌ client 모르는 필드 4개, `files_total`은 backend에 없음(클라 전용) |
| `file.discovered.v1` | `collection_id, source_root_id, discovered_files, discovered_bytes, manifest_revision` — **file_name 없음** (L150-158) | `file_name ∥ discovered_files` refine + `sha256_prefix` (L254-270) | ❌ 실프레임엔 파일명이 없음 → `namedFiles` 채우려면 어댑터가 이름을 지어내야 함(금지). bytes/manifest_revision 미인식 |
| `file.duplicate.detected.v1` | `duplicate_files, processing_credits` (+id) (L193-195) | `duplicates_total` 필수 + `sha256_prefix` (L272-278) | ❌ **필드명 불일치**: `duplicates_total` vs `duplicate_files`. 실프레임 drop 확정 |
| `page.route.selected.v1` | `page_count, route_counts, route_policy_versions` (+ids) (L353-361) | `lane` 필수 + `attempt, reason, page_count` 선택 (L304-312) | ❌ client `lane`은 backend `route_counts`에서 유도해야 함. `attempt/reason`은 fixture 전용, backend엔 없음 |
| `verification.failed.v1` | `state, reason_codes` (+ids) (L403-411) | `finding_code, detail` 둘 다 필수 (L314-320) | ❌ **완전히 다른 필드쌍**. 실프레임 drop 확정 |
| `recovery.completed.v1` | `document_id, shard_id, recovery_task_id, result_attempt_id, recovery_level, final_state` (+collection_id) (L826-834) | `attempt?, final_state?, verified: true(literal)` (L331-344) | ❌ backend엔 `verified`가 없어 client literal이 실프레임을 항상 거부. `result_attempt_id` vs `attempt` 의미차 |
| `entity.resolved.v1` | `entity_count, scope` (+ids) (L480-487) | `entity_id ∥ entity_count` refine + `entity_type, label, scope` 선택 (L357-374) | ⚠️ 부분 호환 — count+scope면 통과 가능하나 client `payload.scope` 문자열과 envelope `scope` 객체가 이름으로 충돌, `label` 부재 |
| `relation.created.v1` | `relation_count, evidence_bound` (+ids) (L488-495) | `relation_id ∥ relation_count` + named-relation refine (L376-402) | ⚠️ 부분 호환 — `evidence_bound`는 backend 필수인데 client는 선택으로만 인식 |

결론(product-event.ts 헤더 주석 L26-31의 실측과 부합): **같은 이름이 계약은 아니다.**
현 파서(`parseProductEvent`)에 실제 collection 스트림 프레임을 흘리면 상당수가
validation 실패로 drop된다. 이것이 §9.2의 P0 blocker이며, 닫는 순서는
canonical envelope(본 커밋) → producer/parser conformance(Phase 1 후속)이다.

## 4. Projection 영향 — `apps/web/src/lib/world-projection.ts`

| # | 위치 | 문제 | canonical 기준 조치 |
| --- | --- | --- | --- |
| W1 | L262-267, 288, 305, 321 (`event.page_number`) | legacy 최상위 `page_number` 직접 참조 — canonical엔 없고 `scope.job.page_number`로만 존재 | adapter가 scope로부터 채워주거나 projection이 `scope.kind==="job"` 분기로 읽도록 변경 |
| W2 | recompile (product-event.ts L516-523 ↔ projection L427-435) | client는 payload.`change_id` 필수로 요구. 스펙 §9.5.1 예제의 `recompile.completed.v1` payload엔 `change_id`가 없고 `candidate_world_state_id`, `equivalence_receipt_id`가 있다 | payload contract 수렴 시 projection에 world-state/equivalence-receipt 수신 경로 신설 필요 |
| W3 | impact (product-event.ts L489-499 ↔ projection L403-413) | 스펙 §9.5.1 예제 payload의 `reason_paths[][]`를 client/projection이 모두 모른다(무시됨) | DERIVED 노출 검토 전까지는 무시 허용 — 단 계약 문서로 고지(본 표) |
| W4 | `scopeKey` L176-185 (`demo:*`) | 모든 demo 이벤트가 커서 하나를 공유 — §9.6 "scope별 sequence" 원칙과 충돌 소지. 서로 다른 fixture를 한 스트림에서 섞어 재생하면 gap 표시가 왜곡될 수 있음 | 다중 fixture 재생을 허용하는 시점에 `demo:<fixture_id>` 커서로 세분화 검토 |
| W5 | 전체 | `monotonic_offset_ms` 미사용 | replay seek/구간 재생 결정론이 필요해지면 projection 진입 전 normalize 단계에서 도입 |

## 5. 후속 조치 (Phase 1 잔여)

1. **producer conformance**: `akc_cir.collection_events` → canonical envelope 발행 경로(adapter) 구현 — payload에 `collection_id` 등을 남길지 scope로 올릴지 확정.
2. **parser conformance**: `parseProductEvent`를 generated type + payload contracts 기반으로 교체.
3. **fixture conformance**: demo fixture 전수를 `validate_envelope`로 검사.
4. **legacy 제거(E8/E9/W1)**: additive rollout 종료 후 최상위 `collection_id/document_id/page_number` 삭제.
5. B-14종 producer 착수 시 본 enum 유지, C-8종은 DERIVED 확정분만 추가.

— 문서 끝. 본 문서는 "측정된 diverge"만 기록한다. 추측성 주장 추가 금지.
