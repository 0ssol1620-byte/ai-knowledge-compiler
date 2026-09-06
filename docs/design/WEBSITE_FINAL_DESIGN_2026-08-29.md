# TAVONEL 웹사이트 — 경쟁사 분석 · 최종 연출 · 디자인 설계

**작성:** 2026-08-29 (KST) · HEAD `656cb46`
**선행:** `docs/design/WEBSITE_DESIGN_PLAN_2026-08-29.md` (권위 정정 · 델타 · 게이트)
**권위:** `D:\TAVONEL_CINEMATIC_COMPILATION_REPLAY_MASTER_SPEC_v2.0_FINAL_KO_2026-08-23.md` §0.1 순서
**성격:** 실행 설계. 경쟁사 수치는 2026-08-29 직접 측정값이며 **인용이지 재현이 아니다.**

---

# PART 1 — 경쟁사 웹사이트 실측 분석

## 1.1 방법

6개 사이트를 브라우저로 직접 열고 DOM에서 계산된 스타일을 추출했다.
주관적 인상이 아니라 `getComputedStyle` 값과 요소 카운트다.

## 1.2 측정 결과 (2026-08-29)

| | 배경 | 잉크 | 서체 | H1 | video | canvas | img | section |
|---|---|---|---|---|---:|---:|---:|---:|
| **Glean** | `#FFFFFF` + warm `#FBF6F4` + lime `#D8FD49` | `#333333` | Polysans Neutral | 56/53.76 w400 **ls −2.4px** | **12** | 0 | **129** | 15 |
| **Hebbia** | `#0E0B0B` | `#F4F1EB` | Selecta | *(h1 = 로고 16px)* | 2 | **2** | **576** | 9 |
| **Reducto** | `#F8F8F6` | `#310632` | reductosans | **84/92** w470 ls −0.8px | 9 | 0 | 80 | 11 |
| **Linear** | `#08090A` | `#F7F8F8` | Inter Variable | 64/64 w510 ls −1.408px | **0** | **0** | 38 | 8 |
| **Notion** | `#FFFFFF` | `rgba(0,0,0,.95)` | NotionInter | 64/64 **w700** ls −2.125px | **0** | **0** | 32 | 12 |
| **Palantir** | `#FFFFFF` | `#1E2124` | Alliance No.1 | **100/115** w400 ls −2px | 1 | 0 | 25 | 10 |
| **TAVONEL (계약)** | `paper-1` warm | `ink-0` | Wanted Sans | `cine.statement` **44/48** w510 ls −.025em | **0** | 5–10% | — | 영화 + 5 |

## 1.3 발견 7가지

### F1 · 라이브 렌더링 히어로는 아무도 하지 않는다 — 그러나 DOM만으로 최고가 될 수 있다

```
video 히어로   Glean 12 · Reducto 9   → 녹화 영상. 제품 상태가 아님
DOM 히어로     Linear 0/0 · Notion 0/0 → 실제 UI를 마크업으로 그림
canvas         Hebbia 2               → 유일. 그나마 장식적
```

**Linear는 video 0, canvas 0, 이미지 38개로 카테고리 최고 수준의 제품 히어로를 만든다.**
실제 이슈 카드, 활동 로그, 에이전트 대화를 전부 DOM으로 렌더한다.

두 가지 결론이 동시에 나온다:

1. **TAVONEL의 이벤트 구동 라이브 렌더러는 실제로 비어 있는 영역이다.** 경쟁사 히어로는
   전부 녹화본이거나 정적이다. "지금 실행 중인 컴파일"을 보여주는 곳이 없다.
2. **그런데 그걸 하려고 3D가 필요하지 않다.** Linear가 증명한다.
   → `WEBSITE_DESIGN_PLAN` §3-G3의 **2D 베이스라인 우선 결정을 이 데이터가 지지한다.**

### F2 · 따뜻한 종이는 이미 점유돼 있다 ★

Reducto가 `#F8F8F6` 배경 + `#310632` 딥 퍼플 잉크다. **TAVONEL의 paper-1과 거의 같은 자리다.**

따라서 **"따뜻한 종이"만으로는 차별화되지 않는다.** 문서 AI 영역에서 이미 쓰이고 있다.

TAVONEL의 실제 차별점은 종이가 아니라 **계기(instrument)의 문법**이다:

```
evidence 네 모서리 브래킷 18×18px
superseded 흐린 취소선          ← 삭제하지 않고 남긴다
dirty unit 점선 외곽 브래킷      ← 재빌드가 필요하다는 표시
conflict 분할선 + amber
world state 160×28px mono 버전 스트립
```

Reducto의 종이는 **깨끗하다.** TAVONEL의 종이는 **흔적이 있다.**
이건 취향 차이가 아니라 주장 차이다 — 우리는 실패와 대체를 지우지 않는다.
**§6.9 Shape Grammar가 브랜드의 실체이고, 색이 아니다.**

### F3 · Glean이 비용 서사로 피벗했다 ★ — 메시지 우선순위를 바꿔야 한다

Glean 홈의 현재 카피:

```
AI adoption is accelerating.
AI costs are accelerating faster.
01 Better answers.  02 Fewer tokens.  03 Lower cost to serve.
Average token savings YTD: [rolling odometer]
```

**Glean은 이제 "검색"이 아니라 "컨텍스트의 비용 효율"을 판다.**

이것은 TAVONEL의 selective recompilation 비용 논리와 **인접**하다.
`GTM_PRICING_EXPERIENCE_STRATEGY`에서 제안한 "work avoided" 지표도 같은 축이다.

**판정: 비용을 1차 메시지로 쓰지 않는다.** 그 축은 지금 훨씬 큰 회사가 예산을 태워 점유 중이다.
TAVONEL의 1차 메시지는 **정확성과 현재성**이어야 한다 — `KNOW WHAT IS TRUE NOW.`
비용(재컴파일 회피)은 **증명된 뒤 따라오는 2차 결과**로 배치한다. S16이 그 자리다.

### F4 · Palantir가 "Ontology"를 소유한다

Palantir 홈 H1 아래 첫 줄이 `The Ontology-Powered Operating System for the Modern Enterprise`이고,
페이지 전체가 Ontology를 고유명사로 쓴다.

**공개 카피에서 "ontology"를 쓰지 않는다.** 스펙의 S08 비트명
`ONTOLOGY + DEPENDENCY FORMATION`은 **내부 비트 이름으로만 유지**하고,
화면 레이블은 `RELATIONSHIPS` 또는 `WHAT DEPENDS ON WHAT`으로 간다.

### F5 · 타입 스케일이 카테고리 대비 작다 ★

```
Palantir  100/115 w400
Reducto    84/92  w470
Linear     64/64  w510
Notion     64/64  w700
Glean      56/53.76 w400
─────────────────────────
TAVONEL    44/48  w510   ← cine.statement
```

전원이 −0.8 ~ −2.4px 음수 트래킹, 웨이트 400–510(Notion만 700).
**TAVONEL만 44px다.** 1440×900 제품 프레임 *안쪽*이라 전체 화면 대비는 아니지만,
첫 명제가 카테고리 최소값보다 작으면 확신이 덜해 보인다.

**권고:** `cine.statement`를 **1440에서 52–56px**로 올린다(모바일 30/34 유지).
`cine.worldPayoff` 52px과 겹치므로 payoff를 **60/62**로 함께 올린다.
트래킹 −.025em은 카테고리 관행과 일치하니 유지.

> 이건 스펙 §6.11 수정 제안이다. 스펙 값을 임의로 바꾸지 않고 **결정으로 기록**한 뒤 바꾼다.

### F6 · 로고 월(logo wall)을 쓸 수 없다 — 그래서 더 나은 것을 쓴다

```
Hebbia   576 images  — 대부분 통합/데이터소스 로고 스크롤
Glean    129 images  — 고객 로고 + 인증 배지(ISO 42001 · HIPAA · SOC 2 · GDPR)
```

엔터프라이즈 신뢰 장치의 표준은 **빌린 신뢰**다: 고객 로고, 인증, 통합 로고.

TAVONEL은 `FOLYNTA_BRAND_DECISIONS` D-006에 따라 **등록된 증거 없는 고객 로고·인증·성능 주장을
쓸 수 없다.** 고객도 아직 없다.

**대체 장치: Public Proof.** 빌린 신뢰 대신 **검증 가능한 산출물**을 놓는다.

```
경쟁사      "Fortune 100의 62%가 씁니다"        → 확인 불가, 빌린 신뢰
TAVONEL     "이 공시 원문을 지금 여기서 열어보세요" → 즉시 확인 가능, 자체 신뢰
```

`/demo/dart` · `/demo/sec`가 이미 `complete` 상태다. **이게 로고 월 자리에 들어간다.**
고객이 없는 회사에게 이건 차선책이 아니라 **더 강한 장치**다.

### F7 · 섹션 수가 가장 적다 — 의도적이어야 한다

```
Glean 15 · Notion 12 · Reducto 11 · Palantir 10 · Hebbia 9 · Linear 8
TAVONEL 계획: 영화 + 5
```

무명 브랜드가 가장 적은 섹션으로 가는 것은 베팅이다. 성립하려면
**5개 섹션이 각각 서로 다른 반론 하나씩을 처리**해야 한다. §2.3에서 그렇게 배치했다.

### 1.4 요약 — 우리가 서는 자리

```
          제품이 히어로     실시간 이벤트 구동     흔적을 남기는 문법     검증가능 증거
Linear         ●                  ○                    ○                  ○
Hebbia         ●                  ○                    ○                  ○
Reducto        ○                  ○                    ○                  △
Glean          ○                  ○                    ○                  ○
Notion         ○                  ○                    ○                  ○
Palantir       ○                  ○                    ○                  ○
TAVONEL        ●                  ●                    ●                  ●
```

**네 축이 동시에 겹치는 곳은 없다.** 그리고 그 넷은 전부 제품이 실제로 하는 일이다 —
연출이 아니라 사실의 렌더링이다. 이것이 이 디자인의 방어선이다.

---

# PART 2 — 최종 사이트 설계

## 2.1 한 문장

> **Home은 회사 소개 페이지가 아니라, 56초 동안 실제 컴파일을 재생하고
> 마지막 프레임에서 방문자에게 조종간을 넘기는 제품이다.**

## 2.2 Above the fold — Compilation Replay (0–56s)

```
┌──────────────────────────────────────────────────────────┐
│ TAVONEL          THE KNOWLEDGE COMPILER                  │  cine.brand 14/18
│ ┌──────────────────────────────────────────────────────┐ │
│ │  1440 × 900 제품 스테이지                             │ │
│ │  Source Browser │ Main Stage │ Discovery Feed         │ │
│ │  ────────────── Compiler Rail 70px ─────────────────  │ │
│ │  DISCOVER → READ → RESOLVE → COMPILE → VERIFY → ACT   │ │
│ └──────────────────────────────────────────────────────┘ │
│  SAMPLE WORLD · FICTIONAL CONTENT · REAL COMPILER RUN    │  cine.micro 10/13 mono
│  [ ⏸ ] [ ⏭ Skip ] [ ↻ Replay 56s ]                       │  44×44 min
└──────────────────────────────────────────────────────────┘
```

- 자동재생은 **조건부 1회**: reduced-motion 아님 · 뷰포트 안 · shell ready · 사용자가 끄지 않음
- **auto-loop 금지**
- pause는 프레젠테이션 시계만 멈춘다 (컴파일러/이벤트 수집은 계속)
- 재방문자 기본 = S10 완료 상태 + `Replay 56s`

## 2.3 Below the fold — 5개 섹션, 각각 하나의 반론

| # | 섹션 | 처리하는 반론 | 장치 |
|---|---|---|---|
| 1 | **Public Proof** | *"샘플이라 예쁜 거 아냐?"* | `/demo/dart` `/demo/sec` 실제 공시 · 실제 bbox · 실제 receipt |
| 2 | **Personal → Team → Enterprise** | *"나한테 이게 왜 필요해?"* | 같은 World, 세 스케일. SaaS 탭 3개가 아니다 |
| 3 | **Security / local-first** | *"내 파일을 왜 너희한테?"* | quarantine → CDR → 격리 파서 → 권한 경계 |
| 4 | **Research / Benchmarks** | *"진짜 되는 건 맞아?"* | 인용은 인용으로, 자체 측정은 자체 측정으로 명시 |
| 5 | **CTA** | *"그래서 뭘 하면 돼?"* | 3단 CTA |

출력 형식(`Markdown` / `Obsidian` / `JSONL`)은 히어로에서 빼고 **S09 이후 또는 섹션 2 하단**.

**섹션 4 주의:** `D-006` — 등록된 증거 없는 성능 주장 금지.
경쟁 리더보드는 **인용**, 자체 측정(80.6)은 **자체 측정**으로 라벨링. 나란히 놓지 않는다.

## 2.4 CTA 3단 (§8.6)

```
Primary    Scan your knowledge        → signup / onboarding
Secondary  Explore the sample world   → /demo/world      ← 라우트 생기기 전엔 노출 금지
Tertiary   Inspect a public filing    → /demo/dart | /demo/sec   ← 지금 사용 가능
```

## 2.5 라우트

```
/               cinematic recorded sample → tool handoff
/demo/world     open sample World            [신규]
/demo/dart      public DART proof            [complete]
/demo/sec       public SEC proof             [complete]
/app/...        authenticated live World     [존재]
```

---

# PART 3 — 최종 연출: S00–S20

프레임 법칙 `start_frame = round(t × 60)` @ 60fps. 끝 프레임 = 다음 샷 시작 − 1.
**★ = founder 승인 게이트 프레임.**

## ACT 1 — WHOLE TRANSFORMATION · 0.00–14.50s

전체 변환을 먼저 다 보여준다. **설명하지 않는다.**

| S | 시간 | 장면 | 화면에서 일어나는 일 | 카메라 | 레이블 예산 |
|---|---|---|---|---|---:|
| S00 | 0.00–0.65 | PRODUCT FRAME | 제품 셸 정지 프레임. **SSR로 나오는 LCP 대상** | HOLD | — |
| S01 | 0.65–1.45 | SOURCE CONNECTION | 폴더·Obsidian·Git·Cloud가 Source Browser로 들어옴. 36px row | HOLD | 6 |
| S02★ | 1.45–3.10 | **DISCOVERY TIMELAPSE** | tree depth 확장 + **실제 카운트**. Feed 7행, ×40 배속 | PUSH IN | 6 |
| S03 | 3.10–4.20 | CLASSIFICATION STREAM | 확장자가 아니라 **처리 경로**를 고른다. 카드 88×116, 동시 18 | LATERAL | 6 |
| S04 | 4.20–5.80 | OCR / STRUCTURE READ | 230×326 페이지 + bbox 1px + 스캔라인 1패스 opacity ≤.45 | PUSH IN | 5 |
| S05 | 5.80–7.20 | SEMANTIC EXTRACTION | 종이 사각형 → capsule/bar/plate로 변형 | DEPTH SHIFT | 8 |
| S06 | 7.20–8.65 | STABLE IDENTITY CONVERGENCE | `SAME_IDENTITY_AS` 1px 수렴 + merge + **700ms HOLD** | HOLD | 6 |
| S07 | 8.65–10.10 | AUTHORITY + TIME | current(실선 밑줄) vs superseded(흐린 취소선). **900ms HOLD** | HOLD | 7 |
| S08 | 10.10–11.65 | DEPENDENCY FORMATION | `DEPENDS_ON` 1.5px. **변경 전에 의존성을 설치한다** | PULL OUT | 8 |
| S09 | 11.65–12.75 | PROJECTION FLASH | 하나의 truth → 여러 view. 여기서 출력 형식 등장 | PULL OUT | 6 |
| S10★ | 12.75–14.50 | **FIRST WORLD PROMOTION** | `cine.worldPayoff`. World version strip 160×28 mono | HOLD | 8 |

**카피 (§13.1)**

```
Watch scattered files become one current world.

DISCOVERING SOURCES → READING STRUCTURE → RESOLVING IDENTITIES
→ BUILDING RELATIONSHIPS → VERIFYING THE WORLD

YOUR DIGITAL WORLD, COMPILED.
Current. Connected. Source-linked.
```

**고유명사 금지 구간이다.** `Projects` `Research` `Notes` `Policies`
`approved-launch-plan.pdf` `meeting-notes.md`까지만.
`Project Atlas` · `Alice` · `November 3`은 여기서 나오면 안 된다.

> 현재 `copy.ts`의 `TRUTH_COPY.question`이 `WHEN IS PROJECT ATLAS LAUNCHING?`이다.
> **`Launch Program` / `Launch date`로 교체 필요.**

## ACT 2 — ZOOM INTO INTELLIGENCE · 14.50–25.50s

지나간 것을 **되감아** 이해 가능한 속도로 재생한다. ACT 1의 이해 격차를 메우는 유일한 장치.

| S | 시간 | 장면 | 핵심 질문 | 카메라 |
|---|---|---|---|---|
| S11 | 14.50–17.80 (3.30s) | WHAT BELONGS TOGETHER | *같은 것을 어떻게 알아보나* | PUSH IN |
| S12 | 17.80–21.40 (3.60s) | WHAT IS CURRENT | *후보 3개 중 무엇이 지금 유효한가* | HOLD |
| S13 | 21.40–25.50 (4.10s) | DEPENDENCY | *무엇이 무엇에 기대고 있나* | PULL OUT |

```
It knows what belongs together.
It knows which information is true now.
It knows what depends on what.
```

**S13이 S16의 사전 조건이다.** 의존성을 먼저 보여주지 않으면
"영향받은 것만 재컴파일"이 무슨 뜻인지 알 수 없다.

## ACT 3 — SIGNATURE CAUSAL PROOF · 25.50–40.10s

이 사이트가 존재하는 이유.

| S | 시간 | 장면 | 화면에서 일어나는 일 |
|---|---|---|---|
| S14 | 25.50–28.30 (2.80s) | AUTHORITATIVE SOURCE EDIT | 원본 한 줄을 **실제로** 바꾼다. 원인이 명확해야 함 |
| S15 | 28.30–32.00 (3.70s) | SEMANTIC DIFF + IMPACT | 문자 변화 아님. impact path **130ms/hop 1패스** |
| S16★ | 32.00–36.80 (**4.80s, 최장**) | **SELECTIVE RECOMPILATION** | dirty unit 7개만 움직이고 **100개 이상은 정지** |
| S17 | 36.80–40.10 (3.30s) | NEW WORLD PROMOTION | atomic 활성화. v1 → v2 version strip 전환 |

```
When reality changes, TAVONEL updates with it.

UPDATING WHAT CHANGED.
NOT EVERYTHING ELSE.
```

**S16 성립 조건 — fixture 설계에서 결정된다.**
7개가 다시 계산되는 장면은 **100개 이상이 가만히 있을 때만** 의미가 있다.
`Comprehension World`의 "무관 지식 100개 이상" 요구가 여기서 회수된다.
움직이지 않는 것이 화면 대부분을 차지해야 한다.

**S17 필수 규칙 — 이미 한 번 위반이 잡혔다.**
검증 완료 전 값은 `· RECOMPILING`으로 표시하고 가중치를 낮춘다.
부분 world state를 `CURRENT`로 노출하는 것은 금지다.

## ACT 4 — PAYOFF & HANDOFF · 40.10–56.00s

| S | 시간 | 장면 | 화면 |
|---|---|---|---|
| S18 | 40.10–44.80 (4.70s) | ASK THE CURRENT WORLD | Answer Object 520px · answer 54px tabular |
| S19★ | 44.80–49.50 (4.70s) | EVIDENCE RETURN / FACING PAGES | source ≥48% / output ≥38% / spine 4–6% · thread drift **<1px** |
| S20 | 49.50–56.00 (**6.50s**) | CONTROL HANDOFF | 영화가 끝나지 않고 도구가 된다 |

```
Your AI stops searching through files.
It reads the current world.

EVERY ANSWER HAS A WAY HOME.        ← 현재 Hero에 있던 문장. 여기로 이동

NOW COMPILE YOURS.
```

**S20이 6.50초로 두 번째로 긴 이유:** 여기서 컨트롤이 넘어간다.
컷 전환이 아니라 **같은 화면이 조작 가능해지는** 것이므로 인지 시간이 필요하다.

## 승인 게이트 4장 재지정

```
기존 (H보드)              신규 (S보드)              선정 이유
H01 WORK IS EVERYWHERE →  S02 DISCOVERY TIMELAPSE   5초 테스트를 통과시키는 프레임
H06 COMPILED OBJECT    →  (S05로 흡수)
H08 WORLD COMPILED     →  S10 FIRST WORLD PROMOTION 전체 변환의 완결
H16 ONLY AFFECTED      →  S16 SELECTIVE RECOMPILE   시그니처 · 최장 비트
                       →  S19 EVIDENCE RETURN       45초 테스트를 통과시키는 프레임
```

이 4장이 **동시에 소셜/OG 자산 4장**이다. 승인된 것만 밖에 나가는 구조가 자동으로 성립한다.

---

# PART 4 — 디자인 시스템 (실행용)

## 4.1 화면 비율 — 트렌드를 거부하는 근거

```
paper / neutral   84%      ← 종이
instrument dark    8%      ← 계기
evidence           4%      ← 증거 (source path에만)
brand              2%
review / danger    2%      ← 실패를 숨기지 않는다
```

**금지: glassmorphism · full-screen gradient · glow · 장식 shadow.**
2026 SaaS 트렌드가 공통으로 지목하는 다크+소프트 그라디언트+글로우를 의도적으로 거부한다.
깊이는 luminance / occlusion / scale로만 만든다.

**단, F2를 기억할 것** — 따뜻한 종이는 Reducto가 이미 쓴다.
차별점은 색이 아니라 §4.2의 흔적 문법이다.

## 4.2 Shape Grammar — 브랜드의 실체

```
Document          72×96      세로 종이 사각형
Scanned page      230×326    + 모서리 마크
Entity            124×40     가로 캡슐
Person            124×40     캡슐 + 원형 원점 1개
Project           140×42     이중선 캡슐
Claim             112×26     가로 바 + source notch
Decision          120×34     노치 사각형
Policy            120×34     상단선 사각형
Evidence 발생      18×18      네 모서리 브래킷
World state       160×28     mono 버전 스트립
Consumer           84×30     terminal/agent 마크

── 상태 표시 (이게 차별점이다) ──
Current fact       claim + 실선 밑줄
Superseded         claim + 흐린 취소선     ← 지우지 않는다
Conflict           분할선 + amber
Dirty unit         점선 외곽 브래킷        ← 재빌드 필요
Verified unit      evidence 색 작은 체크
```

**금지:** 모든 entity를 sphere · 모든 relation을 glowing line · node 크기를 임의 중요도로 과장 ·
source와 entity가 같은 모양 · authority를 green badge로만.

## 4.3 Edge Grammar

```
SUPPORTED_BY      evidence 1.25px solid   claim→evidence   draw once
EXTRACTED_FROM    evidence 1px            semantic→source  draw once
SAME_IDENTITY_AS  neutral 1px             candidates→entity merge
DEPENDS_ON        ink/evidence 1.5px      dependent→dep    impact 역방향
CONSUMED_BY       evidence 1.5px          knowledge→consumer
SUPERSEDES        review 1px dashed       newer→older      impact glow 없음
GOVERNS           ink-1 1.25px 이중 원점틱  policy→subject
CONFLICTS_WITH    review 1.25px 분할       대칭             방향 화살표 없음
active impact     evidence 2px            causal path      130ms/hop 1패스
```

## 4.4 Motion

> **TAVONEL moves only when reality, understanding, or control changes.**

```
Flash          80–160ms      감지 · 마커 · 마이크로 상태
Flow          180–350ms      artifact 이동 · merge · path
Scene         450–800ms      카메라/레이아웃 의미 전환
Meaning Hold  600–1,500ms    이해해야 하는 결과
```

**리듬: BURST → RESOLVE → HOLD**

```
938 file events   ×40 배속
identity merge    ×1 + 700ms HOLD
812 file events   ×50 배속
authority conflict ×1 + 900ms HOLD
```

**카메라 동사 5개:** PUSH IN · PULL OUT · LATERAL TRAVEL · DEPTH SHIFT · HOLD.
360° orbit · barrel roll · game camera 없음.

**금지:** spring · bounce · elastic · overshoot · idle orbit · breathing · perpetual shimmer ·
cursor parallax · scroll-jacked camera · fake typing · `top/left/width/height` 애니메이션.

**Motion truth class — 장식이 의미인 척하는 것을 코드로 막는 장치**

```ts
type VisualTruthClass = "OBSERVED" | "DERIVED" | "AMBIENT";
```

OBSERVED/DERIVED만 label 가능. AMBIENT에는 semantic ID도 edge도 금지.
**dev overlay에서 각 모션의 class를 검사할 수 있어야 한다.**

**이 규칙이 F1의 방어선이다.** 경쟁사가 파티클을 돌릴 때 우리가 정지해 있는 것은
게으름이 아니라 "움직이면 무언가 실제로 일어난 것"이라는 계약이기 때문이다.
`IDLE → freeze`.

## 4.5 Typography — F5 반영 제안

```
                          현행 스펙        제안        모바일
cine.brand              14/18 w590         유지        12/16
cine.statement          44/48 w510    →  52/56 w510    30/34
cine.worldPayoff        52/55 w510    →  60/62 w510    34/38
cine.answer             54/56 tabular      유지        38/42
cine.section            26/31 w560         유지        22/27
cine.body               16/24 w510         유지        15/22
cine.status             12/16 mono         유지        11/15
cine.label              11/14 w560         유지        10/13
cine.micro              10/13 mono         유지        10/13
```

트래킹 −.025em 유지 (카테고리 관행 −0.8 ~ −2.4px와 일치).
**새 display font 추가 금지** — Wanted Sans 유지.

```
영어    text-wrap: balance  (:lang(en) 에서만)
한국어  word-break: keep-all
숫자    중요 숫자는 tabular
대문자  상태/브랜드에만
mono    데이터에만, 브랜드 카피에 쓰지 않음
첫 프레임 주 명제 최대 2줄 · 한 글자 고아 금지
```

## 4.6 Label budget

| 상태 | 최대 | | 상태 | 최대 |
|---|---:|---|---|---:|
| Discovery | 6 | | World wide | 8 |
| OCR | 5 | | Impact | **9** |
| Meaning | 8 | | Recompile | 6 |
| Identity | 6 | | Ask | 8 |
| Current Truth | 7 | | Evidence | 10 |

충돌 마진 가로 12px / 세로 8px · hysteresis 18% · 카메라 이동 중 4프레임마다 재계산.

**한국어 주의:** `keep-all`이라 줄바꿈 지점이 영어보다 적다.
기존 텍스트 오버런 게이트(산술 측정 + 아트보드 내부 assert)를 **ko 로케일에서도 돌린다.**

## 4.7 Compiler Rail

```
DISCOVER → READ → RESOLVE → COMPILE → VERIFY → ACTIVATE
70px desktop / 56px compact · 6 stage · gap 8px · active track 2px · 컨트롤 ≥44px
```

3층:

```
Macro   BUILDING A CURRENT WORLD
Meso    RESOLVE  3,829 / 4,117
Micro   Merged  launch-plan / LP-01
        Held    conflicting policy
        Read    scanned-approval.png
```

**규칙:** total을 알 때만 퍼센트 · 모르면 count + active · ETA는 모델+confidence 있을 때만 ·
**failed/recovered를 success에 흡수 금지** · 재컴파일에서 clean work는 움직이지 않음 ·
**`setInterval` 진행률 금지, 모든 세그먼트는 실제 이벤트 카운트.**

단계별 표현이 다르다 — 파란 막대 하나로 전 과정을 그리지 않는다:

```
Discover  tree depth + 실제 count      Compile   affected unit segments
Read      artifact lanes               Verify    receipt tick + 미해결 흉터
OCR       page-edge markers            Activate  world version 전환
Resolve   identity convergence
```

## 4.8 숫자 계약

스펙의 `12,841` `4,182` `21,407` `7`은 **예시이지 production literal이 아니다.**

```
{{projection.discovery.filesDiscovered}}
{{projection.worldTotals.entities}}
{{projection.worldTotals.relations}}
{{projection.recompile.recompiled}} / {{projection.recompile.worldUnitsTotal}}
```

하드코딩된 숫자가 화면에 나오면 `CLAUDE.md`의
*"Never invent data to satisfy a schema"* 위반이다.

**그리고 이게 F6의 실행이다** — Glean은 롤링 오도미터로 통계를 굴린다.
TAVONEL의 모든 숫자는 실제 fixture 실행에서 나온다.

---

# PART 5 — 구현 계약

## 5.1 렌더링 층

```
DOM        55–65%   타이포그래피 · 컨트롤 · source browser · answer
SVG        20–25%   evidence · dependency · progress · relation
Canvas      5–10%   조밀한 OCR bbox · artifact stream
Three.js    0–15%   ← G-C2 미승인 = 0%. Linear가 0으로 가능함을 증명 (F1)
Video          0%   인터랙티브 코어에서는 사용 안 함
```

## 5.2 로드 순서 · 성능

```
A. SSR 편집형/제품 셸        ← LCP 대상
B. 정적 첫 프레임 (S00)
C. replay JSON + DOM/SVG 모션
D. evidence 에셋
E. (선택) WebGL
F. explore 밀도
```

```
field p75   LCP ≤ 2.5s · INP ≤ 200ms · CLS ≤ 0.1
frame       high desktop ≤16.7ms · mobile DOM/SVG ≤33.3ms
lifecycle   ACTIVE→render · SETTLING→안정까지 · IDLE→freeze
            OFFSCREEN→stop · HIDDEN→pause · CONTEXT LOST→2D fallback
```

**예산 충돌:** 현재 `initial_script_transfer = 208,870 / 220,000` (여유 11KB).
시네마틱 셸 ≤70KB gzip이 들어갈 자리가 없다.
**순서: ① 동적 import로 initial에서 분리 → ② 그래도 넘치면 래칫 재도출.**
재도출 커밋에는 "S보드 채택 결정에 따른 재측정"임을 명시한다
(`CLAUDE.md` §22 — 초록으로 만들려고 올리는 것과 다른 행위다).

## 5.3 모바일 — 축소가 아니라 재편집

56초를 줄이지 않는다. **24–30초 별도 컷.**

```
sources → read/OCR → identity/current → world → change/impact
       → selective update → answer/evidence → CTA
```

named source 4 · semantic entity 6 · world node ≤10 · WebGL off ·
**가로 카메라 이동 없음, 세로 장면 전환** · 컨트롤 ≥44×44px.

## 5.4 정적 논증 계층 — 하나로 네 가지를 해결한다

```
<noscript> / reduced-motion / SSR 기본 마크업
= S00–S20 서사를 텍스트 + 정적 도형으로 완결한 문서
= 크롤러가 색인하는 것       (SEO)
= LCP 대상                    (성능)
= 접근성 경로                 (WCAG 2.2 AA)
= reduced-motion 사용자의 동등한 논증  (§17)
```

**따로 만들지 않는다. 하나를 만들고 네 역할을 준다.**
`experience/scenes/narration.ts`(DOM 없이 테스트 가능한 내레이션)를 S보드 21비트로
재작성해 **SSR 기본 출력으로 승격**한다. 절반은 이미 만들어져 있다.

이것은 제품의 주장과도 일치한다 — *하나의 truth, 여러 projection* (S09).

## 5.5 상태 기계 진입점

```
크롤러 / 최초 SSR   → 정적 논증 계층
첫 방문자           → S00부터 (조건부 auto-start 1회)
재방문자            → S10 완료 + Replay 버튼   (cinematic_intro_seen=v2)
reduced-motion      → 정적 논증 계층 + 수동 스텝
```

쿠키/localStorage 분기를 SSR에 넣으면 캐시가 깨진다. hydration 이후 전환하되
**두 상태의 레이아웃 박스를 동일하게** 잡아 CLS를 만들지 않는다.

---

# PART 6 — 실행 순서

| # | 작업 | 선행 | 주체 |
|---|---|---|---|
| 1 | 권위 순서 정정 (`CINEMATIC_REBUILD_PHASE_STATUS.md`) | — | founder |
| 2 | 승인 게이트 → **S02 · S10 · S16 · S19** 재지정 | 1 | **founder** |
| 3 | **G-C2 = 2D 베이스라인 진행** 결정 기록 | 1 | **founder** |
| 4 | 타이포 스케일 상향 결정 (F5, `cine.statement` 52 / payoff 60) | 1 | **founder** |
| 5 | `packages/contracts/product-event.schema.json` + 생성기 + 적합성 테스트 | — | **엔지니어링 P0 임계경로** |
| 6 | Comprehension World fixture 제작 → **실제 컴파일러로 실행·녹화** | 5 | 엔지니어링 |
| 7 | `lib/cinematic/` — clock · director · replay-source · camera · layout | 5 | 엔지니어링 |
| 8 | **정적 논증 계층** (SSR = SEO = a11y = reduced-motion) | 2 | 엔지니어링 |
| 9 | `copy.ts` 고유명사 제거 (`PROJECT ATLAS` → `Launch Program`) | 2 | 엔지니어링 |
| 10 | S02·S10·S16·S19 4장 최종 아트 → **founder 게이트** | 6,7,8 | → founder |
| 11 | 나머지 17샷 + Compiler Rail + Discovery Feed | 10 | 엔지니어링 |
| 12 | 모바일 24–30초 컷 | 11 | 엔지니어링 |
| 13 | `/demo/world` 라우트 + manifest/test | 11 | 엔지니어링 |
| 14 | below-fold 5섹션 | 11 | 엔지니어링 |
| 15 | 소셜/OG 4장 + 루프 3개 (= 게이트 4장과 동일 프레임) | 10 | 엔지니어링 |
| 16 | 이해도 테스트 n≥12 (외부 인원) | 14 | **외부 · founder** |
| 17 | 7뷰포트 × ko/en 시각 증거 · 성능 · 접근성 매트릭스 | 14 | 엔지니어링 |

**founder 결정 4개(1–4)가 지금 전부를 막고 있다. 전부 문서 결정이고 구현 비용이 없다.**
**엔지니어링 시작점은 5번**이다. 스키마 없이 7번을 만들면 fixture에서만 도는 렌더러가 나온다.

---

## 부록 — 이 문서가 주장하지 않는 것

- 경쟁사 수치는 **2026-08-29 단일 시점의 홈 화면 측정**이다. A/B 변형·지역·로그인 상태에
  따라 다를 수 있고, **재현 실험이 아니라 인용**이다.
- Glean·Notion 등의 성능·채택 수치는 **그들이 자기 사이트에 쓴 주장**이며 검증하지 않았다.
- F5의 타이포 상향(52/60)은 **경쟁 앵커에 근거한 제안**이지 사용자 테스트 결과가 아니다.
  스펙 §6.11 값을 바꾸는 것이므로 `decision.md`에 결정으로 기록한 뒤 적용한다.
- H→S 매핑과 게이트 재지정은 **추론**이다. 두 스펙 어느 쪽도 이 대응을 명시하지 않았다.
- 08-23 스펙의 채택 자체가 founder 판단이다. 채택되지 않으면 PART 2–6이 무효다.
