# TAVONEL 웹사이트 — 디자인 권위 정정 · 델타 · 연출 실행 계획

**작성:** 2026-08-29 (KST) · HEAD `656cb46`
**성격:** 설계 계획. 새 디자인을 창작하지 않는다 — 권위 문서를 확정하고, 구현과의 차이를 재고 실행 순서를 만든다.
**선행:** `docs/strategy/GTM_PRICING_EXPERIENCE_STRATEGY_2026-08-29.md`

---

## 0. 결론 먼저

**웹사이트 디자인을 새로 기획할 필요가 없다. 이미 완전한 계약이 존재한다.**
문제는 **레포가 낡은 권위 문서를 따르고 있고, 구현이 대체된 보드를 구현했다**는 것이다.

```
레포가 믿고 있는 권위          실제 현행 권위
─────────────────────────    ────────────────────────────────
08-21 Manus 브리프  (1순위)  →  08-22 INDUSTRY_LEADING 블루프린트 (전략)
08-20 시네마틱 스펙 (2순위)  →  08-23 CINEMATIC_COMPILATION_REPLAY v2.0 (사이트)
                                08-28 PRODUCTIZATION MASTERPLAN (제품화)
                              ※ 08-21·08-20은 08-23 §0.1에서 7순위로 강등
```

결과: `apps/web/src/experience/`가 구현한 **H00–H23 / 66초 보드는 대체됐다.**
현행 계약은 **S00–S20 / 56초, 캔버스 1440×900**이다.

**이 문서가 하는 일 3가지:**
1. 권위 체인을 정정한다 (§1)
2. 구현 ↔ 스펙 델타를 사실로 잰다 — 무엇이 살고 무엇이 버려지는가 (§2–3)
3. 스펙이 **다루지 않은** 5가지를 채운다 (§8) — 여기가 실제 신규 설계 작업이다

---

## 1. 권위 정정 — 가장 먼저 고쳐야 할 것

### 1.1 08-23 스펙이 스스로 선언한 순서 (§0.1)

```
1. 사실 · 법률 · 보안 · 개인정보 · 실제 source/evidence
2. TAVONEL_INDUSTRY_LEADING_FINAL_MASTER_BLUEPRINT_2026-08-22_KO.md
3. 현재 저장소의 실제 코드 · 테스트 · 승인된 계약
4. TAVONEL_CINEMATIC_COMPILATION_REPLAY_MASTER_SPEC_v2.0_2026-08-23   ← 사이트 설계 정본
5. design-system/tavonel/DESIGN_MASTER_V3.md
6. design-system/tavonel/decision.md  (4가 명시적으로 대체하지 않은 항목)
7. 과거 SEC 전용 cinematic spec · Manus brief        ← 08-20 · 08-21 여기
8. ThreeUI · Aside · Apple 등 레퍼런스 시각 문법
9. 라이브러리 기본값
```

`docs/design/CINEMATIC_REBUILD_PHASE_STATUS.md`의 "Authority" 절이 이 순서로 교체되어야 한다.
**지금 안 고치면 Phase 4–7(나머지 라우트)이 대체된 보드 위에서 시작한다.**

### 1.2 08-23이 명시적으로 폐기한 것 (§0.2)

- SEC 단일 사실에서 시작하는 Home intro
- **일반 SaaS hero + 아래 feature section 구조**
- Hero의 FacingPages 고정 배치
- 녹화 영상 한 편을 별도 섹션에서 재생하는 방식
- 첫 방문자에게 고유명사·날짜·world ID를 맥락 없이 먼저 제시
- decorative 3D/particle을 제품 의미처럼 사용

### 1.3 08-23이 유지한 것 (§0.2 · §2.1)

컴파일러 시맨틱스 · 증거/출처/시간/권위 진실 계약 · FacingPages의 정확한 source→output 연결 ·
light-first 제품 UI · **현재 design token 체계** · Personal→Team→Enterprise 순서 ·
LIVE/SAMPLE 표시 계약 · DART/SEC 공개 증명 · reduced-motion/접근성/성능 게이트 ·
warm paper 표면 · Wanted Sans editorial typography · 실패·review·recovered 흔적을 지우지 않는 문법

**즉 디자인 시스템은 그대로다. 바뀌는 것은 Home의 서사 구조와 시간축이다.**

---

## 2. 구현 ↔ 스펙 델타 (2026-08-29 실측)

| 스펙 요구 | 저장소 현황 | 판정 |
|---|---|---|
| S00–S20 / 56.00s / 1440×900 | H00–H23 / **66s** (`shots.ts:25`) | **대체됨** |
| `packages/contracts/product-event.schema.json` | **없음** (`packages/contracts/`는 존재) | **P0 미착수** |
| `apps/web/src/components/cinematic/` (17개 컴포넌트) | **디렉토리 없음** | 미착수 |
| `apps/web/src/lib/cinematic/` (director/clock/replay-source 등) | **디렉토리 없음** | 미착수 |
| `apps/web/src/fixtures/showcase-world/v1/` | **없음** | 미착수 |
| `/demo/dart` · `/demo/sec` | `PAGE_MANIFEST.yml:136-137` **status: complete** | **재사용 가능** |
| `/demo/world` (샘플 World) | 없음 | 신규 |
| Three.js 선택적 층 | `three` **미설치**, G-C2 **미기록** | **2D 베이스라인만 허용** |
| ProductEvent → Projection → UI 방향 | `lib/{event-reducer,processing-scene-model,v6-collection-events}` 존재 | **도너로 살아남음** |
| SSE 실시간 처리 극장 | `collection-processing-theater.tsx` 존재 | **살아남음 = live onboarding 엔진** |

### 2.1 죽는 것

`experience/manifest/shots.ts`의 66초 24비트 타임라인과 `SUPERSEDED_2026_08_20_BOARD`.
**보존은 하되 실행 권위에서 제외한다** — 이 저장소의 규칙(대체된 사실은 삭제하지 않고 역사로 남김)대로.

### 2.2 사는 것 — H → S 구제 매핑

66초 보드가 헛되지 않았다. 대부분의 비트가 **개념적으로 S 보드에 대응**하며 렌더러·내레이션·
텍스트 오버런 게이트·좌표 안전영역 로직은 그대로 이식된다.

| 기존 H (66s) | 대응 S (56s) | 이식 판정 |
|---|---|---|
| H01 YOUR WORK IS EVERYWHERE | S01 SOURCE CONNECTION | 개념 동일, 시간 압축 (1.2s→0.80s) |
| H02–H05 MESS/REGISTER/DISCOVER | S02 DISCOVERY TIMELAPSE + S03 CLASSIFICATION | **분해** — S03(처리경로 선택)이 신규 |
| — | **S04 OCR / STRUCTURE READ** | **신규.** H보드에 OCR 전용 비트가 없었다 |
| H06 COMPILED KNOWLEDGE OBJECT | S05 SEMANTIC EXTRACTION | 유지 |
| H07 RESOLVE | S06 STABLE IDENTITY CONVERGENCE | 유지 |
| — | **S07 AUTHORITY + TIME RESOLUTION** | **신규 분리.** H는 TRUTH 하나로 뭉쳐 있었다 |
| — | **S08 ONTOLOGY + DEPENDENCY FORMATION** | **신규.** 변경 이전에 의존성을 먼저 설치 |
| — | **S09 PROJECTION FLASH** | **신규.** 하나의 truth → 여러 view |
| H08 YOUR DIGITAL WORLD, COMPILED | S10 FIRST WORLD PROMOTION | **유지 — 승인 게이트 4장 중 하나** |
| H09–H13 TRUTH | S11·S12·S13 EXPLAIN 3종 | **재구성.** 타임랩스에서 지나간 것을 되감아 설명 |
| H14 CHANGE | S14 AUTHORITATIVE SOURCE EDIT | 유지 |
| H15 | S15 SEMANTIC DIFF + IMPACT | 유지 |
| H16 ONLY AFFECTED KNOWLEDGE IS UPDATED | S16 SIGNATURE — SELECTIVE RECOMPILATION | **유지 — 승인 게이트, 최장 비트 4.80s** |
| H17 | S17 NEW WORLD PROMOTION | 유지 |
| H18–H19 ASK | S18 ASK THE CURRENT WORLD | 유지 |
| H20–H21 EVIDENCE | S19 EVIDENCE RETURN / FACING PAGES | 유지 |
| H22–H23 SCALE/ACTIVATE | **S20 CONTROL HANDOFF** | **의미 변경.** SCALE은 below-fold로 내려가고 S20은 "영화가 도구가 된다" |

**가장 큰 서사 변화 3가지:**

1. **첫 프레임부터 제품 안이다.** S00은 오리엔테이션(0.65s)이고 VOID가 없다.
   추상 → 제품이 아니라 **제품 → 제품**이다.
2. **타임랩스를 먼저 다 보여주고(0–14.5s) 나서 되감아 설명한다(14.5–25.5s).**
   H보드는 순차 설명이었다. 이건 §1.3의 "Show the transformation before explaining the intelligence".
3. **SCALE(개인/팀/기업)이 영화에서 빠진다.** below-fold로 간다.
   영화는 하나의 World만 다루고, 확장 서사는 스크롤이 담당한다.

---

## 3. 착수 전에 닫아야 하는 게이트 4개

전부 **결정**이지 구현이 아니다. 하나라도 열려 있으면 그 아래 작업이 전부 재작업된다.

### G1 · 권위 순서 정정 — **founder / 즉시**
`CINEMATIC_REBUILD_PHASE_STATUS.md`의 Authority 절을 §1.1로 교체.
비용 0, 리스크 0, 그런데 이걸 안 하면 나머지 전부가 잘못된 기준에서 돈다.

### G2 · 승인 게이트 4장을 **S 보드로 재지정** — **founder**
현재 게이트는 H01·H06·H08·H16이다. S 보드로 옮기면:

```
S02  DISCOVERY TIMELAPSE          — "빠르게 읽는다"는 체감이 성립하는가
S10  FIRST WORLD PROMOTION        — (기존 H08) 전체 변환의 완결
S16  SIGNATURE SELECTIVE RECOMPILE — (기존 H16) 시그니처 증명
S19  EVIDENCE RETURN / FACING PAGES — 신뢰의 마지막 증명
```

기존 H01·H06은 S01·S05로 흡수되므로 개별 게이트에서 내린다.
**S02와 S19를 새로 올린다** — 각각 "5초 테스트"와 "45초 테스트"를 통과시키는 프레임이기 때문이다(§1.2).

### G3 · G-C2 (3D 정책) — **founder**
스펙 §0.3이 명시적으로 요구하는 신규 결정이다. 현황:

```
decision.md G-C      TIER 1 3D 폐기, Hero는 드롭존           (2026-08-07, 유효)
CLAUDE.md            R3F 재도입                              (2026-08-09, 오너 판정)
apps/web/package.json  three 미설치                           (2026-08-29 실측)
decision.md G-C2     미기록
```

**즉 "3D를 다시 쓴다"는 오너 판정은 있는데 그 판정을 규율할 결정 문서가 없고 코드도 없다.**
스펙의 기본값은 명확하다 — **G-C2가 승인되지 않으면 DOM/SVG/Canvas 2.5D 베이스라인만 구현하고,
그 베이스라인만으로 전체 서사가 완결되어야 한다.**

**권고: G-C2를 지금 승인하지 말고 2D로 먼저 완주한다.** 이유:
- 스펙 §11.3이 이미 Three를 **0–15%**로 배정했다. 없어도 서사가 성립하도록 설계된 것이다.
- §18.4는 "WebGL을 LCP 게이트로 두지 않는다"고 못 박았다.
- §22 스크립트 예산이 이미 208,870 / 220,000 바이트다 (§7 참조). Three 350KB 청크는 지금 들어갈 자리가 없다.
- 2D 완주 후 성능 여유가 실측되면 그때 G-C2를 **측정 근거와 함께** 올린다.

### G4 · ProductEvent 정본 스키마 — **엔지니어링 P0, 그러나 진짜 임계경로**
스펙 §9.2가 blocker로 명시한 것:

> 현재 일부 event는 backend와 이름을 공유하지만 payload contract가 다르다.
> client parser가 real frame을 **drop**할 수 있는 상태를 먼저 닫아야 한다.

```
packages/contracts/
  product-event.schema.json        ← 없음
  product-event.generated.ts       ← 없음
  product-event.generated.py       ← 없음
```

**이게 실제 임계경로다.** 시각 작업이 아니라 이것이다. 이유:
영화·튜토리얼·라이브 온보딩이 **같은 렌더러**를 쓴다는 것이 스펙의 법칙 9번이다.
같은 렌더러를 쓰려면 세 입력(녹화 fixture · 실제 백엔드 · 라이브)이 **하나의 이벤트 어휘**여야 한다.
스키마 없이 만든 컴포넌트는 fixture에만 맞고 라이브에서 프레임을 떨군다.

---

## 4. 사이트 아키텍처

### 4.1 Home (§1.4)

```
┌─ ABOVE THE FOLD ────────────────────────────────────┐
│  Compilation Replay  0–56s                          │
│  S00 → S20, 마지막 프레임이 실제 도구가 된다        │
│  (자동재생 1회 조건부 · auto-loop 금지 · 스킵/리플레이) │
└──────────────────────────────────────────────────────┘
   ↓ below-the-fold = 보조 증거
1. Public Proof — DART / SEC        ← /demo/dart · /demo/sec 재사용 (이미 complete)
2. Personal → Team → Enterprise     ← SCALE_COPY 이전 위치
3. Security / local-first
4. Research / benchmarks
5. CTA
```

출력 형식(`Markdown`/`Obsidian`/`JSONL`)은 **Hero 초반에서 제거**하고 Projection 장면 이후 또는 하단에 배치.

### 4.2 라우트 계약 (§8.6)

```
/               cinematic recorded sample → tool handoff
/demo/world     open sample World          ← 신규. route manifest + test 동시 추가
/demo/dart      public DART proof          ← 존재, complete
/demo/sec       public SEC proof           ← 존재, complete
/app/...        authenticated live World   ← 존재
```

CTA 3단:

```
Primary    Scan your knowledge        → signup/onboarding canonical route
Secondary  Explore the sample world   → /demo/world
Tertiary   Inspect a public filing    → /demo/dart | /demo/sec
```

**존재하지 않는 라우트를 카피에 연결하지 않는다.** `/demo/world`를 만들기 전에는
Secondary CTA를 노출하지 않는다.

### 4.3 두 개의 World (§3.1) — 혼동하면 안 되는 계약

| | Comprehension World | Public Proof World |
|---|---|---|
| 목적 | 누구나 즉시 이해 | "예쁜 샘플만은 아니다" 증명 |
| 내용 | **명백한 fictional fixture** | 실제 DART/SEC 공개 문서 |
| 처리 | **실제 컴파일러로 실행하고 이벤트 스트림을 녹화** | 실제 raster/bbox/table/receipt |
| 표시 | `SAMPLE WORLD · FICTIONAL CONTENT · REAL COMPILER RUN` 상시 | LIVE 표시 |
| 집계 | production metric 합산 **금지** | — |
| 사용처 | Home 0–49.5s | S19 이후 `Inspect a public filing` |

fixture source set은 `Launch/` 9파일 + `repo/` (스펙 §3.1에 정확히 명시).
필수 의미 사건 13종(같은 Project 표현 차이, launch date 후보 3개, approved/draft/note 권위 차이,
rename, duplicate, OCR page, conflict, downstream impact 5개 이상, **무관 지식 100개 이상**, World v1→v2 …).

> **무관 지식 100개 이상**이 왜 필수인지가 중요하다. S16에서 "영향받은 것만 재컴파일"을
> 보여주려면 **움직이지 않는 것이 압도적으로 많아야** 한다. 7개가 다시 계산되는 장면은
> 100개가 가만히 있을 때만 의미가 있다.

### 4.4 숫자 계약 (§3.3)

스펙의 `12,841 sources` `4,182 entities` `21,407 relations` `7 affected units`는
**production literal이 아니다.** 전부 projection 바인딩으로 렌더한다.

```
{{projection.discovery.filesDiscovered}}
{{projection.worldTotals.entities}}
{{projection.worldTotals.relations}}
{{projection.recompile.recompiled}} / {{projection.recompile.worldUnitsTotal}}
```

하드코딩된 숫자가 화면에 나오면 `CLAUDE.md`의 "Never invent data to satisfy a schema" 위반이다.

### 4.5 고유명사 노출 법칙 (§3.2)

**0–14.5초 타임랩스에 고유명사를 넣지 않는다.**

```
허용   Projects · Research · Notes · Policies
       approved-launch-plan.pdf · meeting-notes.md · roadmap.xlsx
금지   Project Atlas · Alice · November 3   ← World 형성 후 확대 설명에서만
```

이유는 §1.2의 실패 조건에 명시돼 있다: *"Project Atlas가 뭔지 모르겠다"*가 나오면 실패다.
현재 `copy.ts`의 `TRUTH_COPY`는 `PROJECT ATLAS`를 쓰고 있다 — **generic subject로 교체해야 한다**
(`Launch Program` / `Launch date` / `Approved plan`).

---

## 5. 연출 계약 — S00–S20

시간·프레임은 스펙 §4가 정본이다. 아래는 **각 샷이 무엇을 필요로 하는가**를 붙인 실행 표다.
프레임 법칙: `start_frame = round(start_time × 60)`, 끝 프레임은 다음 샷 시작 −1.

### ACT 1 — WHOLE TRANSFORMATION (0.00–14.50s, 타임랩스)

| S | 시간 | 장면 | 필요한 것 |
|---|---|---|---|
| S00 | 0.00–0.65 | PRODUCT FRAME / ORIENTATION | 제품 shell 정지 프레임 = LCP 대상. SSR로 나와야 함 |
| S01 | 0.65–1.45 | SOURCE CONNECTION | 폴더/Obsidian/Git/Cloud 커넥터 글리프. Source Browser 36px row |
| S02 | 1.45–3.10 | **DISCOVERY TIMELAPSE** ★게이트 | tree depth + **실제 카운트**. Discovery Feed 7행 max |
| S03 | 3.10–4.20 | CLASSIFICATION STREAM | 확장자가 아니라 **처리 경로 선택**을 보여줌. Artifact Stream 88×116px, 동시 18개 max |
| S04 | 4.20–5.80 | OCR / STRUCTURE READ | 230×326px 선택 페이지 + bbox 1px + 스캔라인 1패스(opacity ≤0.45) |
| S05 | 5.80–7.20 | SEMANTIC EXTRACTION | 문서 → 의미 객체. Shape Grammar의 capsule/bar/plate로 변형 |
| S06 | 7.20–8.65 | STABLE IDENTITY CONVERGENCE | `SAME_IDENTITY_AS` neutral 1px 수렴 + merge 애니메이션 |
| S07 | 8.65–10.10 | AUTHORITY + TIME RESOLUTION | current fact(solid underline) vs superseded(faded strike) |
| S08 | 10.10–11.65 | ONTOLOGY + DEPENDENCY FORMATION | `DEPENDS_ON` 1.5px. **변경 전에 의존성을 먼저 설치** |
| S09 | 11.65–12.75 | PROJECTION FLASH | 하나의 truth → 여러 view. 여기서 Markdown/Obsidian/JSONL 등장 |
| S10 | 12.75–14.50 | **FIRST WORLD PROMOTION** ★게이트 | `cine.worldPayoff` 52/55. World version strip 160×28px |

### ACT 2 — ZOOM INTO INTELLIGENCE (14.50–25.50s, 되감아 설명)

| S | 시간 | 장면 | 핵심 |
|---|---|---|---|
| S11 | 14.50–17.80 | WHAT BELONGS TOGETHER | 3.30s — 타임랩스의 identity를 이해 가능 속도로 재생 |
| S12 | 17.80–21.40 | WHAT IS CURRENT | 3.60s — 쉬운 질문 형태로. 후보 3개 → 1개 |
| S13 | 21.40–25.50 | DEPENDENCY | 4.10s — 변경 **전에** 무엇이 무엇에 의존하는지 설치 |

> ACT 2가 없으면 ACT 1은 "멋있는데 뭔지 모르겠다"로 끝난다.
> 이 3샷이 §1.2의 15초→45초 이해 격차를 메우는 유일한 장치다.

### ACT 3 — SIGNATURE CAUSAL PROOF (25.50–40.10s)

| S | 시간 | 장면 | 핵심 |
|---|---|---|---|
| S14 | 25.50–28.30 | AUTHORITATIVE SOURCE EDIT | 원본 한 줄을 **실제로** 바꾼다. 원인이 명확해야 함 |
| S15 | 28.30–32.00 | SEMANTIC DIFF + IMPACT | 문자 변화 아님 — 의미 변화 + 파급. impact path 130ms/hop 1패스 |
| S16 | 32.00–36.80 | **SIGNATURE — SELECTIVE RECOMPILATION** ★게이트 | **4.80s, 최장.** dirty unit(dashed bracket) 7개만 움직이고 100+개는 정지 |
| S17 | 36.80–40.10 | NEW WORLD PROMOTION | atomic 활성화. v1→v2 version strip 전환 |

**S16이 이 사이트 전체의 존재 이유다.** 4.80초를 쓰는 유일한 샷이고,
설명 없이 보이게 하는 것이 목표다(`UPDATING WHAT CHANGED. NOT EVERYTHING ELSE.`).

**S17에서 반드시 지킬 것:** 검증 완료 전 값은 `· RECOMPILING`으로 표시한다.
(부분 world state를 ACTIVE로 노출 금지 — 이 규칙 위반이 이미 H16에서 한 번 잡혔다.)

### ACT 4 — PAYOFF & HANDOFF (40.10–56.00s)

| S | 시간 | 장면 | 핵심 |
|---|---|---|---|
| S18 | 40.10–44.80 | ASK THE CURRENT WORLD | Answer Object 520px, answer 54px tabular |
| S19 | 44.80–49.50 | **EVIDENCE RETURN / FACING PAGES** ★게이트 | source 48% / output 38% / spine 4–6%. thread drift <1px |
| S20 | 49.50–56.00 | CONTROL HANDOFF | **6.50s.** 영화가 끝나지 않고 도구가 된다. CTA 3단 |

`Every output returns to its source.`는 현재 Hero에 있다 → **S19 헤드라인으로 이동**한다(§2.1).

---

## 6. 디자인 시스템 — 한 장 요약

새로 만드는 것 없음. 아래는 스펙 §6–§7의 실행용 압축이다.

### 6.1 화면 비율 (§6.12) — 이게 "트렌디"의 반대이고, 그래서 옳다

```
paper / neutral   84%
instrument dark    8%
evidence           4%
brand              2%
review / danger    2%
```

**금지: glassmorphism · full-screen gradient · glow · 장식 shadow.**
2026 SaaS 트렌드 조사가 공통으로 지목하는 것(다크 + 소프트 그라디언트 + 글로우)을
이 제품은 **의도적으로 거부한다.** 이유는 취향이 아니다 — 이 제품이 파는 것은 **문서의 정직함**이고,
종이 위 잉크가 그 주장의 물질적 형태다. 경쟁 제품 전부가 보라색 글로우일 때
따뜻한 종이 화면은 카테고리 자체가 달라 보인다. **차별화가 곧 트렌드다.**

깊이는 luminance / occlusion / scale로만 만든다. evidence accent는 source path에만.
verified green은 축하가 아니라 상태 표시. review amber는 실패를 숨기지 않는다.

### 6.2 Shape Grammar (§6.9) — 모든 것을 구로 그리지 않는다

```
Document          72×96px 세로 종이 사각형
Scanned page      230×326px + 모서리 마크
Entity            124×40px 가로 캡슐
Person            캡슐 + 원형 원점 1개
Project           140×42px 이중선 캡슐
Claim             112×26px 가로 바 + source notch
Decision          120×34px 노치 사각형
Policy            120×34px 상단선 사각형
Evidence 발생     18×18px 네 모서리 브래킷
Current fact      claim + 실선 밑줄
Superseded        claim + 흐린 취소선      ← 삭제하지 않는다
Conflict          분할선 + amber
Dirty unit        점선 외곽 브래킷          ← 재빌드 필요
World state       160×28px monospace 버전 스트립
```

**금지: 모든 entity를 sphere로 · 모든 relation을 glowing line으로 · node 크기를 임의 중요도로 과장 ·
source와 entity가 같은 모양 · authority를 green badge로만.**

### 6.3 Motion (§7)

> **브랜드 모션 문장: TAVONEL moves only when reality, understanding, or control changes.**

```
Flash         80–160ms     감지 · 마커 · 마이크로 상태
Flow         180–350ms     artifact 이동 · merge · path
Scene        450–800ms     카메라/레이아웃 의미 전환
Meaning Hold 600–1,500ms   이해해야 하는 결과
```

리듬: **BURST → RESOLVE → HOLD.** (938개 파일 이벤트 ×40배속 → identity merge ×1 + 700ms hold)

카메라 동사는 5개뿐: PUSH IN · PULL OUT · LATERAL TRAVEL · DEPTH SHIFT · HOLD.
**360° orbit · barrel roll · game camera 없음.**

금지: spring · bounce · elastic · overshoot · idle orbit · breathing · perpetual shimmer ·
cursor parallax · scroll-jacked camera · fake typing · `top/left/width/height` 애니메이션.

**Motion truth class** — 이게 이 시스템의 핵심 규율이다:

```ts
type VisualTruthClass = "OBSERVED" | "DERIVED" | "AMBIENT";
```

OBSERVED/DERIVED만 label을 가질 수 있다. AMBIENT에는 semantic ID도 edge도 금지.
**dev overlay에서 각 모션의 class를 검사할 수 있어야 한다** — 장식이 의미인 척하는 것을
코드 수준에서 막는 장치다.

### 6.4 Compiler Rail (§8) — 진행률을 파랑 막대 하나로 그리지 않는다

```
DISCOVER → READ → RESOLVE → COMPILE → VERIFY → ACTIVATE
```

3층 진행감:

```
Macro   BUILDING A CURRENT WORLD
Meso    RESOLVE  3,829 / 4,117
Micro   Merged  launch-plan / LP-01
        Held    conflicting policy
        Read    scanned-approval.png
```

**규칙:** total을 실제로 알 때만 퍼센트. 모르면 count + active state.
ETA는 측정 모델과 confidence가 있을 때만. **failed/recovered를 success count에 흡수하지 않는다.**
재컴파일에서는 clean work를 움직이지 않는다. **`setInterval` 진행률 금지 — 모든 세그먼트는 실제 이벤트 카운트.**

### 6.5 Typography (§6.11) & Label budget (§6.5)

현재 Wanted Sans 스택 유지, **새 display font 추가 금지.**

```
cine.statement    44/48  (mobile 30/34)   주 명제, 첫 프레임 최대 2줄
cine.worldPayoff  52/55  (34/38)          compiled world
cine.answer       54/56  tabular (38/42)  현재 답
cine.status       12/16  mono             이벤트/상태
cine.micro        10/13  mono             world ID/해시
```

한 시점에 읽을 수 있는 label 최대: Discovery 6 · OCR 5 · Meaning 8 · Identity 6 ·
Current Truth 7 · World 8 · **Impact 9** · Recompile 6 · Ask 8 · Evidence 10.
충돌 마진 가로 12px / 세로 8px, hysteresis 18%, 카메라 이동 중 최대 4프레임마다 재계산.

한국어는 `word-break: keep-all`, 영어만 `text-wrap: balance`, 중요 숫자는 tabular,
**전부 대문자는 상태/브랜드에만**, 한 글자 고아 금지.

---

## 7. 렌더링 층과 성능 — 여기에 실제 충돌이 하나 있다

### 7.1 층 배분 (§11.3)

```
DOM        55–65%   타이포그래피 · 컨트롤 · source browser · answer
SVG        20–25%   evidence · dependency · progress · relation
Canvas      5–10%   조밀한 OCR bbox · artifact stream
Three.js    0–15%   선택적 World depth  ← G3 미승인 시 0%
Video          0%   인터랙티브 코어에서는 사용 안 함
```

로드 순서(§18.4): SSR shell → 정적 첫 프레임 → replay JSON + DOM/SVG → evidence asset →
(선택) WebGL → explore. **WebGL을 LCP 게이트로 두지 않는다.**

### 7.2 예산 충돌 — 정직하게 처리해야 하는 것

```
스펙 §18.3          cinematic shell incremental JS  ≤ 70KB gzip
                   sample replay manifest/events   ≤ 120KB gzip
                   SSR HTML + critical CSS         ≤ 150KB compressed

현재 실측           initial_script_transfer = 208,870 bytes / 220,000 budget
                   (PAGE_MANIFEST.yml:36)
```

**여유가 11KB밖에 없다.** 시네마틱 셸이 들어갈 자리가 지금은 없다.

`CLAUDE.md` §22가 이 상황을 정확히 규정한다:

> 래칫은 측정값이며 **빌드를 통과시키려고 올리지 않는다.** 페이지가 담는 내용이
> 의도적으로 바뀌면 래칫은 **새 측정에서 재도출**되고, 그것을 승인한 결정과 함께 기록된다.
> **그 둘은 다른 행위이며, 커밋은 어느 쪽인지 말해야 한다.**

따라서: Home이 56초 시연을 담기로 한 것은 **의도적 내용 변경**이므로 래칫 재도출이 정당하다.
단 **재도출 커밋에 "G-C2/S보드 채택 결정에 따른 재측정"이라고 명시**해야 하고,
초록으로 만들려고 올린 것이 아님이 커밋 메시지에서 드러나야 한다.

**단, 순서가 있다:** 시네마틱 셸을 **동적 import로 분리**해서 initial에 들어가지 않게 하는 것이
먼저다(§18.4의 로드 순서가 이미 그렇게 설계돼 있다). 그래도 넘치면 그때 재도출한다.

### 7.3 성능 목표 (§18.1–18.2)

```
field p75   LCP ≤ 2.5s · INP ≤ 200ms · CLS ≤ 0.1
frame       high desktop median ≤16.7ms · mobile DOM/SVG ≤33.3ms
lifecycle   ACTIVE→render · SETTLING→안정까지 · IDLE→freeze
            OFFSCREEN→stop · HIDDEN TAB→pause · CONTEXT LOST→2D fallback
```

**`IDLE → freeze`가 중요하다.** 이 사이트는 가만히 있을 때 **완전히 정지**한다.
법칙 5번 "Idle means still." 대부분의 경쟁 사이트가 영원히 떠다니는 파티클을 돌린다.

### 7.4 모바일은 축소가 아니라 재편집 (§16.4)

56초를 그대로 줄이지 않는다. **24–30초 별도 컷.**

```
sources → read/OCR → identity/current → world → change/impact
       → selective update → answer/evidence → CTA
```

named source 4개 · semantic entity 6개 · world node 최대 10개 · WebGL 기본 off ·
**가로 카메라 이동 없음, 세로 장면 전환** · 컨트롤 44×44px 이상.

---

## 8. 스펙이 다루지 않은 것 — 여기가 신규 설계 작업이다

08-23 스펙은 연출·시각·이벤트·성능을 거의 완벽하게 덮는다. 다음 5가지는 비어 있다.

### 8.1 크롤러가 보는 것이 정의돼 있지 않다 ★

Home이 56초 지시형 경험이 되면 **첫 화면에 색인 가능한 텍스트가 거의 없다.**
현재 `PAGE_MANIFEST`는 Lighthouse SEO 100을 기록하고 있는데, 그건 현행 편집형 페이지 기준이다.

**해법 — 이미 스펙 안에 있는 것을 재사용한다.** §17이 요구하는 것:

> reduced-motion 사용자는 **더 못한 페이지가 아니라 같은 논증**을 받는다.

그 reduced-motion 정적 논증 계층이 **곧 크롤러가 보는 계층**이다.
두 개를 따로 만들지 않는다. 하나를 만들고 두 역할을 준다.

```
<noscript> / reduced-motion / SSR 기본 마크업
= S00–S20의 서사를 텍스트와 정적 도형으로 완결한 문서
= 크롤러가 색인하는 것
= LCP 대상
= 접근성 경로
```

이게 되면 SEO·접근성·LCP·reduced-motion이 **한 번의 작업으로 동시에 해결**된다.
그리고 이건 이 제품의 주장과도 일치한다 — *구조가 있으면 표현은 여러 개로 투영된다*(S09).

**액션:** `experience/scenes/narration.ts`(24비트 내레이션, DOM 없이 테스트 가능)를
S보드 21비트로 재작성하고, 이것을 **SSR 기본 출력**으로 승격한다. 이미 절반은 만들어져 있다.

### 8.2 이해도 테스트에 방법이 없다 ★

스펙 §1.2는 5초/15초/45초 합격 기준과 **실패 답변 목록**까지 정의했다.
그런데 **누구에게 어떻게 묻는지가 없다.** 그리고 `CLAUDE.md`는 명확하다:

> 블라인드 범주 테스트와 강제 비교 판단은 **사람이** 한다.
> 구현하는 세션이 자기 결과를 승인하지 않는다.

**제안 프로토콜 (사이트 공개 전 필수):**

```
대상    n = 12 이상, TAVONEL을 모르는 사람
        (제품 팀 · 이 프로젝트를 아는 사람 제외)
자극    5초 노출 → 화면 가림 → 자유 서술
        15초 노출 → 자유 서술
        45초 노출 → 자유 서술
채점    §1.2의 6개 실패 답변에 해당하는가 (이진 판정, 채점자 2명)
합격    45초 시점에서 "원본이 바뀌면 영향받은 부분만 업데이트되고
        답이 근거로 돌아간다"를 자기 말로 재구성 ≥ 9/12
기록    응답 원문 보존. 실패 응답을 삭제하지 않는다
```

이 테스트를 통과하지 못하면 **연출을 고치는 것이지 카피를 늘리는 것이 아니다.**
설명이 더 필요하다는 것은 장면이 실패했다는 뜻이다.

### 8.3 소셜/OG 자산 계획이 없다

56초 영화는 링크로 자를 수 없다. 그런데 도구는 이미 있다
(`pnpm --filter @akc/web keyframes:capture`).

```
정지 프레임 4장  S02 · S10 · S16 · S19   → OG 이미지 · X 카드 · 블로그 히어로
6–10초 루프 3개  S16 최우선               → 무음 자동재생 환경(X/LinkedIn)
전체 56초                                → YouTube · Home
```

**S16 하나가 문장 하나보다 강하다.** "바뀐 것만 다시 계산된다"를 3초에 보여준다.
승인 게이트 4장(§3-G2)과 소셜 자산 4장을 **같은 프레임으로 통일**하면
승인받은 것만 밖에 나가는 구조가 자동으로 성립한다.

### 8.4 되돌아온 방문자의 기본 상태가 라우팅에 없다

스펙 §4.1이 규칙만 준다:

```
cinematic_intro_seen=v2 이후 기본 = S10 완료 상태, `Replay 56s` 제공
```

그런데 이건 **첫 방문자용 마케팅 사이트와 재방문자용 도구가 같은 URL**이라는 뜻이고,
캐시·SSR·OG 크롤러 각각에서 다르게 동작해야 한다.

```
크롤러 / 최초 SSR   → 정적 논증 계층 (§8.1)
첫 방문자           → S00부터 (조건부 auto-start 1회, auto-loop 금지)
재방문자            → S10 완료 상태 + Replay 버튼
reduced-motion      → 정적 논증 계층 + 수동 스텝
```

**쿠키/localStorage 기반 분기를 SSR에 넣으면 캐시가 깨진다.** 클라이언트 hydration 이후
전환하되, 전환이 CLS를 만들지 않도록 두 상태의 레이아웃 박스를 동일하게 잡는다.

### 8.5 한국어 레이블이 폭 예산을 깨뜨릴 수 있다

§6.5의 레이블 예산은 개수(6–10)와 마진(12px/8px)으로 정의돼 있는데,
한국어는 `word-break: keep-all`이라 **줄바꿈 지점이 영어보다 훨씬 적다.**
`SIGNATURE — SELECTIVE RECOMPILATION` 같은 레이블이 한국어로는 한 덩어리가 되어
안전영역을 넘을 수 있다.

**다행히 게이트가 이미 존재한다.** Phase 3 리뷰에서 만든 텍스트 오버런 게이트가
"instrument-voice 텍스트를 산술적으로 측정해 아트보드 안에 있는지 assert"한다.
**액션: 그 게이트를 한국어 로케일에서도 돌리고, ko/en 양쪽 7개 뷰포트를 시각 증거에 포함한다.**
(현재 캡처는 `ko_en_default_reduced_1920_1440_1024_390` — 768·1280·360이 빠져 있다.
`PAGE_MANIFEST` defaults는 7개 뷰포트를 요구한다.)

---

## 9. 실행 순서

의존성 순서다. 앞의 것이 뒤의 것을 정의한다.

| # | 작업 | 선행 | 주체 |
|---|---|---|---|
| 1 | **권위 순서 정정** (`CINEMATIC_REBUILD_PHASE_STATUS.md`) | — | founder 확인 |
| 2 | **승인 게이트를 S02·S10·S16·S19로 재지정** | 1 | **founder** |
| 3 | **G-C2 결정 기록 — 2D 베이스라인으로 진행 승인** | 1 | **founder** |
| 4 | **`packages/contracts/product-event.schema.json` + 생성기 + 적합성 테스트** | — | 엔지니어링 **P0 임계경로** |
| 5 | Comprehension World fixture 제작 및 **실제 컴파일러로 실행·녹화** | 4 | 엔지니어링 |
| 6 | `lib/cinematic/` — clock · director · replay-source · camera · layout | 4 | 엔지니어링 |
| 7 | **정적 논증 계층** (SSR = SEO = reduced-motion, §8.1) | 2 | 엔지니어링 |
| 8 | S02·S10·S16·S19 4장 최종 아트 품질 → **founder 게이트** | 5,6,7 | 엔지니어링 → founder |
| 9 | 나머지 17샷 + Compiler Rail + Discovery Feed | 8 | 엔지니어링 |
| 10 | 모바일 24–30초 별도 컷 | 9 | 엔지니어링 |
| 11 | `/demo/world` 라우트 + manifest/test | 9 | 엔지니어링 |
| 12 | below-fold 5개 섹션 (Public Proof → Scale → Security → Research → CTA) | 9 | 엔지니어링 |
| 13 | **이해도 테스트 n≥12** (§8.2) | 12 | **외부 인원 · founder** |
| 14 | 소셜/OG 자산 4장 + 루프 3개 | 8 | 엔지니어링 |
| 15 | 7 뷰포트 × ko/en 시각 증거 · 성능 예산 · 접근성 매트릭스 | 12 | 엔지니어링 |

**founder 결정 3개(1·2·3)가 지금 전부를 막고 있다.** 셋 다 문서 결정이고 구현 비용이 없다.

**엔지니어링 관점의 진짜 시작점은 4번이다.** 4번 없이 6번을 만들면
fixture에서만 동작하고 live에서 프레임을 떨구는 렌더러가 나온다 — 스펙 §9.2가 경고한 그대로다.

---

## 부록 — 이 문서가 주장하지 않는 것

- **08-23 스펙을 검토·승인하지 않았다.** 권위 순서는 그 문서가 스스로 선언한 것을 옮긴 것이고,
  그 선언을 채택할지는 founder 판단이다. 채택하지 않으면 §2 이하 전체가 무효다.
- **H→S 매핑(§2.2)은 추론이다.** 두 문서 어느 쪽도 이 대응표를 명시하지 않았다.
  비트 이름과 "핵심 이해" 열을 근거로 만든 것이며, 반증되면 매핑이 진다.
- §8의 5개 제안은 **스펙에 없는 것**이지 스펙이 틀렸다는 뜻이 아니다.
- 성능 예산 충돌(§7.2)은 현재 측정값(208,870B) 기준이며, 동적 import 분리 후 재측정 전까지
  래칫 재도출이 필요한지는 확정되지 않았다.
- 이해도 테스트 설계(§8.2)의 n=12와 9/12 기준은 **제안이며 통계적으로 검정되지 않았다.**
