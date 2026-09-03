# TAVONEL — 브랜딩 · 연출 · 가격 · 저장소 통합 전략

**작성:** 2026-08-29 (KST) · HEAD `656cb46` · branch `agent/folynta-trust-integration-v1`
**성격:** 조사·분석 문서. 공개 카피가 아니고, 가격을 확정하지 않는다.
**상태:** 이 문서의 판정은 모두 **제안**이다. `CLAUDE.md` §"What is not an agent's call"에 따라
가격 확정, 공개 문구, 공개 시점은 founder 결정이다.

> **비공개 경계:** §3의 단가·마진 수치는 `TAVONEL_MASTER_HANDOFF_2026-08-28.md` §43이
> trade secret으로 분류한 항목(cost/latency policy weights, routing thresholds)에 해당한다.
> **웹사이트·영업자료·논문 어디에도 그대로 옮기지 않는다.** 특히 측정 GPU 원가($1.23/1,000p)를
> 경쟁사 소매가 옆에 놓는 것은 `CLAUDE.md`가 명시적으로 금지한다.

---

## 0. 먼저 — 이미 결정되어 있는 것들

질문 7개 중 4개는 저장소 안에 **이미 답이 있고, 상당히 잘 되어 있다.** 처음부터 다시
기획하면 손해다. 확인된 것:

| 질문 | 이미 존재하는 것 | 위치 |
|---|---|---|
| 슬로건 | `THE KNOWLEDGE COMPILER` / `YOUR DIGITAL WORLD, COMPILED.` + 히어로 5줄 시퀀스 | `apps/web/src/experience/manifest/copy.ts` |
| 연출 기획 | H00–H23, 24 beat, 66초, 60fps, 카메라 프리셋, 내레이션까지 | `experience/manifest/shots.ts`, `scenes/narration.ts` |
| 개인/팀/기업 3단 확장 | `SCALE_COPY` — "YOUR PC ALREADY CONTAINS A WORLD" | `copy.ts` |
| 실시간 처리 연출 | SSE 기반 라이브 극장 (stage track, workbench, 병렬 뷰, 복구 패널) | `components/collection-processing-theater.tsx` |
| 가격 구조 | credit-first + 마진 플로어 + 하드캡 + Paddle 매핑, 근거 인용까지 | `tavonel-saas-foundation/docs/CREDIT_ECONOMICS.md`, `TRIAL_CREDIT_AND_PRICING_DECISION_2026-08-27.md` |
| 저장소 통합 | 3-repo → 2축(Core Engine + Product Platform) 수렴 결정 완료 | `tavonel-saas-foundation/docs/PRODUCT_CONVERGENCE_AUDIT_2026-08-28.md` |

따라서 이 문서는 **다시 기획하지 않는다.** 기존 결정을 검증하고, 실제로 비어 있거나
서로 충돌하는 지점만 다룬다. 새로 찾은 문제는 5개다.

---

## 1. 저장소 — 합칠 필요는 없다. 단, 충돌 하나가 남아 있다

### 1.1 이미 내려진 결정은 옳다

`PRODUCT_CONVERGENCE_AUDIT_2026-08-28.md`의 결론 — **history를 병합하지 않고
1 Product Platform + 1 Core Engine의 두 권한 축으로 수렴** — 은 맞는 판단이고 유지해야 한다.
이유는 세 가지다.

1. **런타임이 다르다.** Core Engine은 Python(`packages/cir-python`, `akc_cir.*`)이고
   Product는 TypeScript/Node다. 하나의 저장소로 합치면 두 CI가 서로를 붉게 만든다.
2. **변경 속도가 다르다.** Core는 Protected Core라서 replacement ladder(contract → shadow →
   benchmark → canary → rollout)를 타야 한다. Product는 주 단위로 바뀌어야 한다.
   같은 저장소면 느린 쪽 규율이 빠른 쪽을 막거나, 빠른 쪽이 느린 쪽 규율을 무너뜨린다.
3. **증거 무결성.** `research/`, `docs/evidence/`, `paper/`, 특허 증거는 hash로 고정되어 있다.
   제품 저장소와 섞이면 INC-V2-089(대량 source drift로 frozen bytes 복구 불가)가 재발한다.
   그 사고는 이미 한 번 났고 복구되지 않았다.

**따라서 답: 합치지 마라. 대신 경계를 코드로 강제하라.** Product는 Core의 Python 모듈을
직접 import하지 않고 versioned compile envelope 로만 호출한다 — 이미 audit이 명시한
그대로다.

### 1.2 그런데 감사가 놓친 충돌: **마케팅 표면이 두 개다**

audit은 "Next.js product/marketing"의 권위를 **Foundation**에 배정했다.
그런데 실제 물건은 이렇게 나뉘어 있다.

| 자산 | 위치 | 상태 |
|---|---|---|
| H00–H23 시네마틱 (24 beat, 타임라인, 내레이션, reduced-motion, 키프레임 캡처) | `ai-knowledge-compiler/apps/web/src/experience/` | Phase 3 TESTED, founder gate 대기 |
| 디자인 시스템(DESIGN_MASTER_V3, 18 structural glyph, 모션 매니페스트, 시각 QA 게이트) | `ai-knowledge-compiler/design-system/`, `MOTION_MANIFEST.yml` | 존재 |
| 실시간 처리 극장 (SSE 라이브) | `ai-knowledge-compiler/apps/web/src/components/` | 존재 |
| 공개 랜딩 + 가격 페이지 (Vite/React) | `tavonel-saas-foundation/client/` | 존재, 최신 |
| `/world` UX, 직접 파일/ZIP | `tavonel-compiled-world-activation/client/` | PORT 대상 |

**audit의 배정대로 실행하면 시네마틱과 디자인 시스템 전체가 donor 취급되어 버려진다.**
그건 이 프로젝트에서 가장 만들기 어려웠고 가장 차별적인 자산이다. Foundation의 랜딩은
잘 만들어졌지만 tenant/billing 계약을 증명하려고 만든 것이지 브랜드 자산이 아니다.

**제안 정정:**

```
Core Engine        ai-knowledge-compiler
                   = akc_cir + packages/* + research + evidence + paper
                     + design-system/ (시각 권위, 코드 아님)

Product Platform   신규 canonical (Foundation 계보)
                   = tenant/RLS/billing/credits/upload/job control-plane
                   + apps/web 에서 이식한 experience/ 시네마틱과 처리 극장
                   + Activation 에서 이식한 R2 immutable proof / RunPod receipt / CDR
```

즉 **billing·tenant는 Foundation이 권위, 비주얼·연출은 monorepo가 권위.**
audit의 표에서 "Next.js product/marketing … PORT ← Foundation" 한 줄만 뒤집으면 된다.
지금 뒤집지 않으면 Phase 4–7(나머지 20개 라우트)이 잘못된 저장소에서 시작한다.

### 1.3 운영 시 저장소 배치

```
tavonel-core          (private)  Python 엔진 + 연구/증거/논문/특허. 릴리스는 버전 태그된 worker 이미지.
tavonel-platform      (private)  제품 전체. 이게 배포되는 유일한 것.
tavonel-activation    (archive)  read-only. 이식 완료 후 새 기능 target 금지.
tavonel-saas-foundation (archive) 위와 동일. 이식 후 read-only.
```

archive 전환은 "포트 완료"가 아니라 **포트된 계약이 platform에서 테스트로 재현될 때** 한다.
Foundation의 Vitest 15 files/34 tests가 platform에서 그대로 녹색이 되는 것이 archive 조건이다.

---

## 2. 지금 가격이 적당한가 — **단가는 맞고, 단위가 틀렸다**

### 2.1 현재 설계 (Foundation, 2026-08-27)

```
접근 티어   Observer $29/mo · Studio $99/mo · Institution 협의   (GPU 크레딧 미포함)
크레딧 팩   Starter $12/100 · Builder $30/300 · Scale $75/800
크레딧 정의 1 credit = RTX4090 45 GPU-sec (A100 18s · H100 12s)
과금        ceil(observed_seconds / seconds_per_credit), 최소 예약 2 credit
가드레일    job 10 credit · workspace/day 20 credit · 30% all-in 원가 서킷브레이커
```

마진 플로어 SKU는 Scale, 순액 **$0.0884375/credit**. GPU 직접원가 $0.01375/credit → **15.5%**.
계산은 정확하고 인용도 1차 출처다. **여기까지는 문제 없다.**

### 2.2 발견 — 15.5%는 "건강한 워커"를 가정한 숫자다

Foundation의 크레딧 경제는 RunPod **리스트 가격**에만 대조됐고, 이 저장소가 이미 측정해
공개한 **자기 처리량 증거**와는 한 번도 대조된 적이 없다. 조인해 보면:

`docs/evidence/FOLYNTA_CAMPAIGN_RESULTS.md` §8 실측:

```
건강한 워커     600 pages / pod-hour   → $1.23 / 1,000 pages
캠페인 전체     125 pages / pod-hour   → $5.92 / 1,000 pages   (5,132 docs / 41.03 pod-hr)
격차            4.8×  ← "operational failure cost 4.8× the GPU budget of a clean run"
```

이 처리량을 크레딧 매핑에 넣으면:

| | 건강한 워커 | 캠페인 실측 |
|---|---:|---:|
| 45 GPU-sec 이 처리하는 페이지 | **7.5 p** | **1.56 p** |
| 페이지당 순매출 (Scale 플로어) | $0.01179 | $0.05664 |
| 페이지당 GPU 원가 (serverless 4090 $1.10/hr) | $0.00183 | $0.00880 |
| **순매출 대비 GPU 비중** | **15.5%** | **74.6%** |

**두 개의 결론이 나온다.**

**(1) 30% 서킷브레이커는 검증된 적 없는 구간 한가운데에 있다.**
15.5%와 74.6% 사이 어디가 진짜인지 아무도 모른다. 30%는 그 사이에 있으므로,
실운영이 캠페인 쪽에 가까우면 **디스패치가 자동 정지한다 = 제품이 선다.**
서킷브레이커가 잘못됐다는 뜻이 아니다. **정확히 설계대로 작동하면 서비스가 멈춘다는 뜻이고,
그 확률이 얼마인지 측정된 적이 없다는 뜻이다.**

완화 요인은 있다: 45초 매핑에는 이미 25% start/idle 버퍼가 들어 있고, 캠페인의 4.8×에는
flex worker(active 0 / max 1 / 90초 타임아웃) 구성이면 발생하지 않을 stall과 죽은 워커가
포함돼 있다. 그래서 이것은 **예측이 아니라 상한**이다. 하지만 상한이 브레이커의 2.5배라면
그건 파일럿 전에 측정할 항목이지, 출시하고 관찰할 항목이 아니다.

> **P0 측정:** 합성 P50/P95 벤치에서 재는 것은 초당 비용이 아니라
> **실효 pages/pod-hour와 그 분산**이다. 그 값이 나오기 전에는 크레딧 매핑을 고정하지 않는다.

**(2) 더 심각한 것 — 같은 크레딧이 고객에게 서로 다른 양을 준다.**

100페이지 문서 하나를 넣은 고객은 좋은 날 **14 크레딧**, 나쁜 날 **64 크레딧**을 낸다.
같은 파일, 같은 요청, 4.6배 청구. 고객이 예측할 수 없다.

이건 마진 문제가 아니라 **판매 불가능한 단위**다. 그리고 `TAVONEL_MASTERPLAN_v4.0.md` §18.6이
이미 못 박아둔 규칙을 위반한다:

> Customer-visible unit는 **예측 가능해야** 하고 internal cost ledger와 bounded margin으로
> 연결돼야 한다.

GPU-초를 그대로 파는 것은 **운영 실패를 고객에게 청구하는 것**이다. 그런데 TAVONEL의
헤드라인 증거는 정확히 그 반대를 판다 — 복구 런타임이 53.7 → 80.6을 만든다는 것.
**복구가 제품인데 복구 비용을 고객이 내는 구조**는 서사와 청구서가 정면으로 모순된다.

### 2.3 제안 — 앞은 페이지, 뒤는 GPU-초

```
고객이 보는 단위   1 credit = 처리된 페이지 1장 (복잡도 가중)
                  scan/저품질 ×1.7 · precision 라우트 ×2.5 · 지식 출력 ×1.15
                  ※ 가중치는 apps/web/.../tavonel-pricing-planner.tsx 에 이미 있는 모델
내부 원장         unit_type: GPU_SECOND 그대로 유지 (v4 §18.5 usage_receipt 변경 없음)
변환              페이지 ↔ GPU-초는 운영자가 흡수하는 리스크
```

핵심: **처리량 분산을 고객이 아니라 운영자가 진다.** 그게 이 제품이 파는 것이다.
그리고 이건 되돌릴 수 있는 결정이다 — 내부 원장은 GPU-초로 남으므로 언제든 재보정된다.

**단, 반드시 같이 가야 하는 것:** 페이지 단위로 팔면 병적 입력(1페이지에 표 400개)이
GPU-초를 폭발시킨다. 그래서 페이지 단위는 **문서당 GPU-초 상한**과 짝이어야 한다.
상한 초과 = 실패가 아니라 `NEEDS_REVIEW` 로 큐잉하고 크레딧을 반환한다. TAVONEL의
fail-closed 서사와 일치하고, 이미 human review 계약이 Foundation에 구현돼 있다.

### 2.4 시장 대비 — 페이지 단가는 이미 경쟁력 있다. 그런데 그 축에서 싸우면 안 된다

공개 소매가 (2026-08 조회, **인용이지 재현이 아니다**):

| 제공자 | 페이지당 |
|---|---:|
| Azure Document Intelligence / Textract 계열 일반 OCR | ~$0.0015 |
| LlamaParse (Fast → Agentic Plus) | $0.00125 → $0.056 |
| Reducto | $0.015 (배치 $0.012) |
| Unstructured | $0.03 |
| **TAVONEL Scale 플로어 환산 (건강한 워커)** | **~$0.0118** |

Reducto보다 싸고 Unstructured의 1/2.5다. **그래서 페이지당 가격을 웹사이트에 노출하면 안 된다.**
그 축에 서는 순간 Textract의 $0.0015가 기준선이 되고, TAVONEL은 "8배 비싼 OCR"이 된다.
파싱은 TAVONEL이 파는 것이 아니다.

반대편 앵커:

| 제공자 | 좌석당 |
|---|---:|
| Glean | ~$50–75/user/mo, 최소 ~100석 (생성형/에이전트 각 +$15) |
| Hebbia | 비공개, 좌석 $3K–10K/yr 보고, 엔터프라이즈 6자리 계약 |

**Observer $29 / Studio $99는 이 사이에서 위치가 애매하다.** 팀 기준으로는 Glean 대비
극도로 싸고(좋다), 개인 기준으로는 Obsidian·Notion 대역($10–20)보다 비싸다(나쁘다).
그리고 개인 티어에 GPU 크레딧이 0이라 **"내 PC를 컴파일한다"는 가장 매력적인 서사를 산 사람이
아무것도 실행할 수 없다.**

**제안 사다리:**

| 티어 | 가격 | 포함 | 존재 이유 |
|---|---:|---|---|
| Trial | $0 | 2 credit / 7일 / 1 job / 신원확인 필수 | 현행 유지. 남용 통제 설계가 좋다 |
| **Personal** | **$19/mo** | 로컬 PC 컴파일 + 월 소량 크레딧 **포함** | 지금 없는 층. PKM/Obsidian 채널의 진입점 |
| Studio | $99/mo | 워크스페이스·검토자·API·감사 | 현행 |
| Institution | 협의 | 정책·리전·SSO·SLA | 현행 |
| 크레딧 팩 | $12 / $30 / $75 | 초과분 선불 | 현행 유지 |

Observer $29는 **삭제**한다. 포함 크레딧이 없는 $29는 고객에게 "결제했는데 아직 아무것도
안 된다"는 경험을 준다 — 그건 이 제품이 절대 주면 안 되는 첫인상이다.
Personal $19는 소액 크레딧을 포함해서 그 구멍을 막고, 가격은 PKM 대역에 맞춘다.

### 2.5 크레딧으로 가는 게 맞나 — **맞다. 이유는 Foundation이 쓴 것보다 하나 더 있다**

Foundation의 근거(무제한 구독 = 무제한 GPU 노출, 도난 계정 손실 유한화)는 정확하다.
여기에 하나 더:

**크레딧은 이 제품의 유일한 정직한 단위다.** TAVONEL은 selective recompilation을 판다 —
"바뀐 것만 다시 컴파일한다". 그 가치는 **호출당 비용이 보일 때만 고객에게 전달된다.**
정액제면 고객은 아낀 재컴파일 비용을 볼 수 없고, 제품의 핵심 주장이 청구서에서 사라진다.

> 사용량 대시보드에 반드시 있어야 하는 지표: **work avoided.**
> "이번 달 12,400 페이지 중 1,180 페이지만 재컴파일됨 — 90.5% 회피."
> 이건 마케팅 문구가 아니라 원장에서 나오는 숫자다.
> (`v4 §18.5 usage_receipt` + audit의 "work-avoided telemetry"에 이미 근거가 있다.)

---

## 3. 연출 — 이미 있는 것과, 없는 것

### 3.1 있는 것

`experience/manifest/shots.ts`의 H00–H23은 **완성된 24 beat 시네마틱 보드**다.
VOID → MESS → REGISTER → DISCOVER → RESOLVE → COMPILE → CATEGORY → TRUTH → CHANGE →
ASK → EVIDENCE → SCALE → ACTIVATE. 66초, 60fps 프레임 법칙, 카메라 프리셋, 내레이션 텍스트,
reduced-motion 등가 경로까지 갖췄고 Phase 3는 TESTED다.

`collection-processing-theater.tsx`는 **SSE 실시간 처리 극장**이다. stage track, 이벤트 카운트,
병렬 워커 뷰(v6), 복구 패널, 하드캡 조정, 오프라인/재연결 상태까지 있다.

**즉 사용자가 요청한 "파일 넣으면 로딩→OCR 재가공을 실시간 시각화"는 이미 구현돼 있다.**
없는 것은 그 다음이다.

### 3.2 없는 것 1 — **디렉토리 아키텍처가 스스로 조립되는 장면**

사용자가 가장 정확하게 짚은 지점이고, 지금 가장 약한 곳이다.
그런데 이건 **연출 가능성이 가장 높은 비트**이기도 하다. 이유:

`FOLYNTA_CAMPAIGN_RESULTS.md` §6 실측 —

```
architecture plans stable across repeats       yes, all 7 blueprints
distinct blueprints produce distinct plans     yes
unresolved internal links in an emitted vault  0
```

**아키텍처 계획은 결정론적이고 반복 시 동일하다.** 그래서 이 애니메이션은 장식이 아니라
**실제 계획의 렌더링**이다 — `CLAUDE.md`의 "Motion encodes meaning. Decorative animation is
not shipped"를 정면으로 통과하는 유일한 종류의 3D다.

권장 비트 (H06 COMPILE과 H08 사이, 제품에서는 처리 극장의 마지막 스테이지):

```
COMPILE   파편이 canonical unit으로 응집        (기존 H06)
PLAN      ← 신규. 청사진 선택. 7개 중 하나가 선택되고 다른 6개는 흐려진다
ASSEMBLE  ← 신규. 디렉토리 트리가 위에서 아래로 스스로 접힌다.
                 파일이 폴더로 들어가는 게 아니라, 폴더가 파일들 사이에서 생겨난다
LINK      ← 신규. 파일 간 링크가 그어진다. 해결된 링크는 실선, 미해결은 붉은 파선
REFUSE    ← 신규, 그리고 가장 중요. 미해결 링크가 하나라도 있으면
                 볼트 전체가 방출되지 않고 **닫힌다**
WORLD     활성 세계 (기존 H08)
```

**REFUSE 비트를 반드시 넣어라.** 캠페인 실측은 1,000개 중 **404개가 거부**됐다 —
전부 컴파일러가 해결하지 못한 링크 때문이다. 경쟁사 데모는 100% 성공만 보여준다.
40%가 거부되는 장면을 보여주는 회사는 없고, **그게 정확히 이 제품이 파는 것**이다.
숨기면 평범한 파싱 데모가 되고, 보여주면 아무도 흉내낼 수 없는 장면이 된다.

거부 화면 문구는 이미 톤이 잡혀 있다: `"A vault with a broken link cannot be emitted, by design."`

### 3.3 없는 것 2 — **영화와 제품이 같은 언어인지 아무도 검사하지 않는다**

지금 두 개의 시각 시스템이 병렬로 존재한다: `experience/`(시네마틱)와
`components/*-theater`(제품 실시간). 같은 사건 — 문서 수집, OCR, 컴파일 — 을 서로 다른
컴포넌트가 서로 다른 형태로 그린다.

`CINEMATIC_REBUILD_PHASE_STATUS.md`가 이미 이 원칙을 세워뒀다:
*"§3.2's Film → Tutorial → Tool continuity real rather than aspirational, because the
cinematic and /app share a codebase."* — 그런데 실제로 공유되는 코드는 없다.

**제안:** 도형 어휘를 한 곳으로 뽑는다.

```
experience/world/{source-objects,semantic-objects,fact-stack,topology}.tsx
   ↑ 이 도형들이 제품 처리 극장의 노드 렌더러여야 한다
```

영화의 shard가 제품의 파일 카드와 같은 형태여야, 영화를 본 사람이 제품에서 그것을 알아본다.
이게 전환율의 실체다 — 랜딩에서 본 것과 로그인 후 본 것이 같은 물건일 때.

### 3.4 없는 것 3 — **개인 PC 연결의 첫 30초**

`SCALE_COPY.personal`("YOUR PC ALREADY CONTAINS A WORLD")은 카피만 있고 장면이 없다.
그런데 이게 가장 강한 훅이다. 사람들은 자기 PC가 얼마나 엉망인지 안다.

권장 장면 — **"당신의 PC를 스캔했습니다" 리포트를 컴파일 *전에* 보여준다:**

```
읽은 것        14,203 files · 8 formats · 2019–2026
중복           1,847 (같은 계약서 6개 버전)
모순           23 (같은 사실, 다른 값)
고아           412 (아무것도 참조하지 않고 아무것도 참조되지 않음)
현재 유효      ...아직 모름. 컴파일해야 알 수 있다.
```

이건 무료로 제공할 수 있고(GPU 거의 안 씀 — 메타데이터 스캔), 즉시 개인화되며,
"내 파일 8천 개 중 진짜는 뭐지"라는 불안을 정확히 건드린다. 그리고 이건
`health scan`이라는 이름으로 이미 v4 마스터플랜과 activation 저장소에 존재하는 개념이다.
**Health Scan을 로그인 없는 공개 진입점으로 승격**하는 것이 가장 값싼 전환 장치다.

---

## 4. 슬로건 — 카테고리는 유지, 히어로 첫 줄은 바꿔라

### 4.1 현재

```
BRAND_LOCK   TAVONEL / THE KNOWLEDGE COMPILER
HERO         YOUR WORK IS EVERYWHERE.
             Files. Email. Meetings. Code. Decisions.
             TAVONEL UNDERSTANDS WHAT THEY MEAN.
             People. Projects. Decisions. Facts.
             YOUR DIGITAL WORLD, COMPILED.
THESIS       TAVONEL turns scattered digital information into connected
             knowledge—and keeps it current as things change.
CLOSE        KNOW WHAT IS TRUE NOW. SEE WHAT CHANGED.
             RETURN EVERY ANSWER TO EVIDENCE.
```

### 4.2 판정

**`THE KNOWLEDGE COMPILER`는 유지한다.** 이유가 세 개다: 특허 명세의 언어이고, 논문의
언어이며, 경쟁사가 쓰지 않는 단어다. 카테고리를 스스로 만드는 회사만이 그 카테고리의
기준이 된다. 교육 비용이 들지만 그 비용은 이미 지불하기로 결정된 것이다.

**`YOUR DIGITAL WORLD, COMPILED.`는 히어로 클로징으로는 좋지만 첫 줄로는 약하다.**
이유: **메커니즘을 말하고 이익을 말하지 않는다.** "컴파일된다"가 왜 내게 좋은지 모른다.

**가장 강한 문장은 이미 저장소 안에 있고, 지금 맨 마지막에 놓여 있다:**

```
KNOW WHAT IS TRUE NOW.
```

이 다섯 단어가 이 제품의 전부다. 경쟁사 누구도 이 문장을 쓸 수 없다 — Glean도 Notion도
"찾아준다"고 하지 "지금 무엇이 참인지 안다"고 하지 못한다. 그게 temporal validity와
authority를 가진 시스템만 할 수 있는 주장이고, 그게 특허 청구항 1의 내용이다.

### 4.3 제안

```
카테고리 (불변)   TAVONEL — THE KNOWLEDGE COMPILER

히어로 1행        KNOW WHAT IS TRUE NOW.
히어로 2행        Your files change. Your AI doesn't know.
                  TAVONEL compiles what you know, and keeps it current.
클로징 (기존 유지) SEE WHAT CHANGED. RETURN EVERY ANSWER TO EVIDENCE.
```

층별 변주 — **"컴파일"을 개인에게 팔지 마라. 개인에게는 AI 성능을 팔아라:**

| 층 | 문장 |
|---|---|
| 개인 | **Point it at your PC. Your AI stops guessing.** (`YOUR PC ALREADY CONTAINS A WORLD`는 서브로) |
| 팀 | ONE PERSON HAS CONTEXT. A TEAM NEEDS SHARED TRUTH. *(현행 유지 — 좋다)* |
| 기업 | 현행 `NOW CONNECT THE COMPANY.` 유지 |
| 개발자/API | Not re-indexed. **Recompiled.** *(현재 optional punchline — API 층에서는 이게 헤드라인)* |

`NOT RE-INDEXED. RECOMPILED.`를 optional로 두지 마라. RAG를 아는 사람에게 이 두 단어는
전체 설명을 대체한다.

---

## 5. 노출 극대화 — 가장 큰 공백

브랜드·연출·가격에는 문서가 두껍게 있는데, **획득 채널에 대한 문서는 저장소에 하나도 없다.**
지금 이 상태로 출시하면 훌륭한 제품이 아무도 모르는 채로 서 있는다.

### 5.1 한 가지만 한다면 — 공개 문서 위의 프로그래매틱 Proof Lens

activation 저장소의 `brand-market-proposition`이 이미 **공개 SEC 원문 Proof Lens**를 만들었다.
그걸 마케팅 섹션 하나가 아니라 **색인 가능한 페이지 공장**으로 만든다.

```
/diff/{ticker}/10-K/{year}  →  {year+1}
  이 기업의 10-K에서 실제로 무엇이 바뀌었는가
  · 의미 변경 vs 표현 변경 구분
  · 무엇이 무엇에 영향을 주는가 (의존성)
  · 모든 값이 원문 위치로 돌아간다
```

왜 이게 최적인가:

- **주장 위험이 0이다.** 공개 문서, 검증 가능한 출력, 고객 데이터 없음.
  `CLAUDE.md`의 "receipt 없는 수치 주장 금지"를 위반하지 않는다 — 출력 자체가 receipt다.
- **차별점을 설명하지 않고 실행한다.** semantic diff와 temporal validity를 문장으로
  설명할 필요가 없다. 페이지가 그 자체로 제품이다.
- **검색 수요가 이미 존재한다.** "what changed in X 10-K"는 사람들이 실제로 찾는 질문이고
  현재 좋은 답이 없다.
- **무한하고 자동이다.** 티커 × 연도. 그리고 매년 새 문서가 나온다 —
  즉 **incremental recompilation이 자기 마케팅 자산을 유지보수한다.** 제품이 곧 콘텐츠 파이프라인.
- **DART 자격증명이 이미 있다** (`V5_COST_BUDGET.md` 확인). 한국 공시로 같은 것을 하면
  국내 검색에서 경쟁자가 아예 없다.

### 5.2 영화를 광고로 쓴다 (지금은 못 쓰게 돼 있다)

현재 영화는 **자동재생하지 않고 커튼 뒤에 버튼 하나로 잠겨 있다.** 접근성 판단으로는 옳지만
노출 관점에서는 최악이다. 66초짜리, 클릭해야 보이고, 링크로 잘라낼 수 없다.

이미 있는 도구로 해결된다: `pnpm --filter @akc/web keyframes:capture`.

```
정지 프레임 4장 (H01·H06·H08·H16)  →  OG 이미지 / X 카드 / 블로그 히어로
6–10초 루프 3개                     →  H16 "ONLY AFFECTED KNOWLEDGE IS UPDATED"가 최고
                                       (LinkedIn·X 자동재생 무음 환경에 맞춤)
전체 66초                           →  YouTube / 랜딩 (커튼 유지)
```

루프 하나가 문장 하나보다 강하다. H16은 "바뀐 것만 다시 계산된다"를 3초에 보여준다 —
이건 텍스트로 설명하면 한 문단이 걸린다.

### 5.3 개인 층을 유통 채널로 쓴다

Obsidian 볼트 익스포트가 이미 있다(4개 익스포트 타깃 중 하나, 미해결 링크 0 보장).
PKM 커뮤니티는 **자기가 쓰는 도구를 공개적으로 자랑하는 몇 안 되는 커뮤니티**다.
Personal $19 티어 + Health Scan 무료 진입점 + 볼트 익스포트 = 자연 확산 경로.

개인이 팀을 데려온다. 반대 방향(엔터프라이즈 영업 → 개인)은 시드 단계에서 작동하지 않는다.

### 5.4 하지 말 것

- 벤치마크 점수를 히어로에 올리는 것 — `D-006`은 등록된 증거 없는 성능 주장을 금지하고,
  80.6은 게시판 인용이 아니라 **자체 측정**이라 옆에 놓으면 재현 주장이 된다.
- 페이지당 가격 공개 — §2.4.
- GPU 원가($1.23) 언급 — `CLAUDE.md` 명시적 금지.
- "세계 최초" / "정확도 99.98%" — 후자는 **완료율**이지 정확도가 아니다 (`CLAUDE.md` 명시).

---

## 6. IP — 한 가지 해금 사항

특허 출원이 **2026-08-27에 완료**됐다 (KR 10-2026-0162417, 심사청구·납부 완료).

따라서: **그 명세서에 기재된 메커니즘은 이제 공개해도 신규성을 잃지 않는다.**
identity uncertainty containment, structural fact as impact root, selective regenerate/inherit,
inherited fingerprint validation, fail-closed atomic promotion — 이걸 웹사이트에서
보여주는 것이 이제 안전하다. 시네마틱 H00–H23 전체가 이 범위 안이다.

**단 두 가지 경계:**

1. **2026-08-27 이후에 새로 발명된 메커니즘은 자동으로 보호되지 않는다.**
   공개 전 IP sweep을 거친다 (`MASTER_HANDOFF §41`).
2. **연구 IP gate(SFIR9/GPU/논문)는 여전히 CLOSED다.** 제품 마케팅과 연구 공개는
   별개 게이트다. 웹사이트가 열린다고 arXiv가 열리는 것이 아니다.

---

## 7. 실행 순서

의존성 순서다. 우선순위가 아니라 **앞의 것이 뒤의 것을 정의하기 때문에** 이 순서다.

| # | 항목 | 왜 이 자리인가 | 결정 주체 |
|---|---|---|---|
| 1 | **시네마틱 4장 founder gate 승인/반려** | Phase 4–7 20개 라우트 전체가 여기서 막혀 있다. 시각 언어가 안 정해지면 아무것도 못 그린다 | **founder** |
| 2 | **마케팅 권위 저장소 정정** (§1.2) | 지금 안 뒤집으면 Phase 4가 잘못된 저장소에서 시작한다 | **founder** |
| 3 | **실효 pages/pod-hour 분산 측정** | 크레딧 매핑·서킷브레이커·페이지 단위 전환이 전부 이 숫자에 달려 있다 | 엔지니어링 |
| 4 | **크레딧 단위를 페이지로 전환** (§2.3) | 3번 결과로 가중치 확정. 내부 원장은 불변이라 되돌릴 수 있다 | founder 승인 |
| 5 | **Observer 삭제 / Personal $19 신설** | 4번과 같이 나가야 함 (포함 크레딧이 페이지 단위여야 의미가 있다) | **founder** |
| 6 | **PLAN/ASSEMBLE/LINK/REFUSE 4비트 추가** (§3.2) | 1번 승인 후. 시각 언어가 정해져야 그릴 수 있다 | 엔지니어링 |
| 7 | **도형 어휘 통합** (§3.3) | 6번과 병행 | 엔지니어링 |
| 8 | **Health Scan을 무료 공개 진입점으로** | 전환 장치. 5번 티어와 짝 | 엔지니어링 |
| 9 | **Proof Lens 프로그래매틱 페이지** (§5.1) | 가장 큰 획득 레버. 색인 시작이 빠를수록 좋다 | founder 승인 (공개 범위) |
| 10 | **키프레임 → 소셜 자산** (§5.2) | 1번 승인 즉시. 도구는 이미 있다 | 엔지니어링 |

**founder 결정이 필요한 것: 1, 2, 5, 그리고 4·9의 승인.** 나머지는 엔지니어링 작업이다.
1번이 열리지 않으면 6·7·10이 전부 대기한다 — 그래서 1번이 실질적 단일 병목이다.

---

## 부록 A — 출처

내부 (이 저장소):
`docs/evidence/FOLYNTA_CAMPAIGN_RESULTS.md` §6·§8 ·
`docs/north-star/TAVONEL_MASTERPLAN_v4.0.md` §9.8·§18.5–18.8 ·
`docs/audit/V5_COST_BUDGET.md` · `apps/web/src/experience/manifest/{shots,copy}.ts` ·
`docs/design/CINEMATIC_REBUILD_PHASE_STATUS.md` · `FOLYNTA_BRAND_DECISIONS.md`

내부 (다른 저장소, read-only):
`tavonel-saas-foundation/docs/{CREDIT_ECONOMICS,TRIAL_CREDIT_AND_PRICING_DECISION_2026-08-27,PRODUCT_CONVERGENCE_AUDIT_2026-08-28}.md` ·
`tavonel-compiled-world-activation/brand-market-proposition-20260826.md`

외부 (2026-08-29 조회, **인용이며 재현 아님**):
[Reducto pricing](https://reducto.ai/pricing) ·
[Reducto — Best Document Processing APIs 2026](https://llms.reducto.ai/best-document-processing-apis-2026) ·
[Glean pricing breakdown](https://coworker.ai/blog/glean-pricing) ·
[Hebbia pricing](https://www.hebbia.com/pricing) ·
[SaaS web design trends 2026](https://shift8web.ca/saas-web-design-trends-in-2026-how-modern-interfaces-drive-trust-trials-and-mrr/) ·
[Figma — web design trends](https://www.figma.com/resource-library/web-design-trends/)

Paddle / RunPod / R2 요율은 Foundation 문서의 1차 출처 인용을 그대로 사용했고 재조회하지 않았다.
**가격은 실행 시점에 다시 조회해 receipt에 pin한다** (v5 PART 7.2).

## 부록 B — 이 문서가 증명하지 않은 것

- §2.2의 74.6%는 **상한이지 예측이 아니다.** 캠페인 처리량은 pod 구성에서 측정됐고
  serverless flex 구성은 다르게 행동할 수 있다. §7-3 측정 전에는 어느 쪽도 주장하지 않는다.
- 시장 요율은 **조회한 것**이지 동일 조건 벤치마크가 아니다. 경쟁 점수를 재현했다고 말하지 않는다.
- Personal $19, Observer 삭제, 페이지 단위 전환은 **수요 검증이 없다.** 근거는
  경쟁 앵커와 내부 정합성이지 고객 증거가 아니다.
- 제안된 슬로건 변경은 테스트되지 않았다. `D-006`에 따라 공개 문구는 founder 승인 사항이다.
