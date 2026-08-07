<a id="title"></a>
# 지식 컴파일러 디자인 마스터플랜 v3

FACING PAGES · 대응면 시스템 · 코드 대조 및 외부 재검증 완료판 · 2026-08-07

|  |  |
| --- | --- |
| 문서 ID | `DESIGN-MASTER-V3-KO-20260807` |
| 대체 대상 | `TAVONEL_DESIGN_MASTER_V2_FACING_PAGES_KO` 전문 |
| 상태 | 시각 설계 단일 진실 · W-1 게이트 통과 전 구현 착수 금지 |
| 범위 | 브랜드 · 프론트엔드 디자인 · UI/UX **전용** (백엔드 비대상) |
| 코드 기준선 | `0ssol1620-byte/ai-knowledge-compiler` `main@7ac5098` `apps/web` 전수 대조 |
| 외부 기준선 | 경쟁사 9곳 · 레퍼런스 11곳 · 스킬 12종 · 플랫폼 지원 현황 직접 확인 |

<a id="how-to-read"></a>
## 이 문서를 읽는 법

v2는 두 축에서 사실과 달랐다. 하나는 **코드** — 문서가 지시하는 파일·라우트·라이브러리 상당수가 저장소에 없거나 다른 이름으로 있었다. 다른 하나는 **시장** — "2026-08-06 실측 완료"로 표기된 경쟁사·레퍼런스·스킬 판정 다수가 반증됐다. v3는 그 결과를 본문에 흡수했다. 정정 주석은 남기지 않았다. 무엇이 바뀌었는지는 [§0.4](#v2-refuted)에 목록으로만 둔다.

**세 종류의 문장이 섞여 있다.** 구분해서 읽어야 한다.

- **[확정]** — 이 문서의 권한으로 정한다. 이견은 `decision.md`를 거친다.
- **[권장]** — 근거와 함께 제시하되 오너가 뒤집을 수 있다. 뒤집으면 연쇄 영향을 같이 적었다.
- **[게이트]** — 오너가 정하기 전까지 착수할 수 없다. [§0.5](#w-1)에 5건이 있다.

* * *

<a id="authority"></a>
## 0. 이 문서의 권한

<a id="supersede"></a>
### 0.1 대체 관계

이 문서는 기존 마스터플랜의 **시각 설계 부분 전체**와 v2를 대체한다. 백엔드·모델·검증·복구·크레딧·릴리스 계약은 기존 문서를 그대로 따른다.

| 그대로 유지 | 이 문서가 대체 |
| --- | --- |
| 백엔드 API · SSE · durable event 계약 | 브랜드 시각 언어 전체 |
| 진실성 경계 (Claim Register, 상태 용어, 과장 금지) | 홈 구성 · Hero · Proof · Knowledge의 형태 |
| 접근성 · 성능 **목표치** | 컬러 · 타이포 · 그리드 · 모션 · 표면 토큰 |
| 법률 · 상표 판단 | 에셋 조달 정책 · 컴포넌트 · 스킬 스택 |
|  | 검수 방식 전체 |

<a id="conflict-order"></a>
### 0.2 충돌 시 권한 순서

```text
1. 사실 · 법률 · 보안 진실
2. 이 문서
3. 승인된 정적 시안 (decision.md 기록)
4. 실측된 외부 스킬 규칙 (§17)
5. 프레임워크 기본값
```

저장소 루트 `AGENTS.md`의 "설계 권한 순서" 2·3위(마스터플랜 / 브랜드 스킬)를 이 문서로 교체한다. 두 파일이 서로 다른 순서를 담으면 세션마다 다른 답이 나온다. [§24.1](#agents-md) 참조.

외부 스킬은 이 문서를 **정교화할 수는 있어도 재정의할 수 없다.**

<a id="done"></a>
### 0.3 완료의 정의

```text
파일이 존재함              ≠ 완료
테스트 통과                ≠ 최고급 디자인
visual baseline 갱신       ≠ Creative 승인
에이전트 자체 점수 94점     ≠ 통과
```

```text
승인된 정적 시안
+ 실제 제품 데이터
+ 브라우저 증거 (7 뷰포트 × reduced-motion)
+ 비교 판정 통과 (§25)
+ 독립 승인 기록
= 완료
```

<a id="v2-refuted"></a>
### 0.4 v2에서 반증된 전제

v3를 신뢰하려면 v2의 무엇이 틀렸는지 알아야 한다. 아래는 v3가 **본문을 다시 쓴** 이유다. 근거는 [부록 C](#sources)에 있다.

**코드 대조에서 (2026-08-07 · `main@7ac5098`)**

| v2의 서술 | 실제 |
| --- | --- |
| 제품명 TAVONEL | 코드 전체가 **Structara**. `tavonel` 문자열 0건. TAVONEL는 미병합 브랜치에만 |
| 홈이 7개 씬 / 8개 섹션, `01`–`08` 번호 라벨 | `<section>` **11개**, 번호는 `01`–`04`만 두 군데 |
| 전 페이지 명도가 거의 일정 | `--st-night` 다크 면이 **이미 4곳**. 문제는 대비 부재가 아니라 리듬 부재 |
| 삭제 대상에 "로고 캐러셀" | 홈에 **원래 없다** |
| `styles/tokens.css` 전문 | 그 디렉터리가 없다. 토큰은 CSS 4개 파일 16,048줄에 분산 |
| `next/font/local` self-host | `next/font` 0건, `@font-face` 0건. 실효 서체는 로컬 Aptos 스택 |
| 에디토리얼 서체 Newsreader | 미설치. `--st-serif`를 5곳이 쓰는데 **정의된 적이 없다** |
| KO/EN 이중 토큰 | **KO 로케일 자체가 없다.** `<html lang="en">` 하드코딩 |
| 기능 아이콘은 Lucide | `@phosphor-icons/react` |
| "출시 시 3D OFF를 뒤집는다" | **R3F 3D가 이미 라이브.** 다만 6초 후 무한 패럴랙스가 돈다 |
| PDF.js 렌더 · rotation/CropBox/DPR 정규화 · IoU ≥0.95 | `pdfjs-dist` 미설치. `bbox.ts` 55줄이 `/10 → CSS %` 가 전부. IoU 테스트 0건 |
| T1 라우트에 `/product/compile` | 없는 라우트. 실제는 `/product/convert` |
| Sidebar 240px (접힘 56px) | 트랙 256px / 요소 240px 불일치, 접힘 64px. Context bar 없음 |
| 레거시 CSS 제거 순서에 `tavonel.css` | 없는 파일. 가장 큰 `globals.css`(8,777줄)가 목록에서 누락 |
| 루트 `CLAUDE.md` | 없다. 실제 계약 파일은 `AGENTS.md` |
| 검증 뷰포트 7종 | Playwright 프로젝트 2개 |

**외부 재검증에서**

| v2의 서술 | 실제 |
| --- | --- |
| 진짜 문서를 홈 주인공으로 놓는 곳 없음 | **Mistral의 Hero가 이미 실제 렌더 문서 4종 + JSON 출력** |
| 근거를 보여주며 조작 가능한 곳 없음 | Docsumo 홈에 `Click a field to see its source` + 신뢰도 + 페이지 앵커 |
| 실패·보류를 보여주는 곳 **하나도 없다** | Extend · LandingAI · Docsumo · Reducto 전부 불확실성을 노출한다 |
| grounding 지표를 공개하는 곳 없음 | Extend **RealDoc-Bench**가 bbox F1/mAP를 IoU ≥0.5로 채점해 공개 |
| 이 형태를 쓰는 경쟁사 0곳 | Resend · Retool · Cursor가 좌-소스/우-결과를 쓴다. **카테고리 기본값이다** |
| 섹션 수 Stripe·Databricks 15 | 실측 **둘 다 6**. Linear가 ~10으로 더 많다. 지표 자체를 폐기한다 |
| Linear는 `#5e6ad2` 하나만 | 4단 램프 + 시맨틱 그린. 그리고 Stripe `#635BFF`와 같은 계열이다 |
| Vercel · Linear가 다크/라이트 교차 | **Linear는 단일 다크.** 교차하는 곳은 Cursor · Clerk · Sierra · Anthropic |
| shadcn 80+ 컴포넌트, shadow-sm 제거 필요 | 64개. Card에 shadow 유틸리티가 **없다** (`ring-1`을 쓴다) |
| `emil-design-eng` 미확인 (라우터 서문) | 완결된 지식베이스. §10의 수치 결손을 직접 메운다 |
| OpenAI `frontend-skill` 404 | 접근 가능. **회피 서체로 Inter를 명시한다** |

<a id="w-1"></a>
### 0.5 W-1 · 선행 결정 5건 [게이트]

시각 작업보다 먼저 닫아야 한다. 하나라도 열려 있으면 W0에 착수하지 않는다.

**G-A · 제품명** — TAVONEL인가 Structara인가.

```text
코드는 전부 Structara다. 푸터에 "Structara is a working name pending brand clearance." 가 있다.
TAVONEL 선택 시  → 시각 변경을 포함하지 않는 개명 PR을 먼저 머지한다.
                   (클래스 st-, 에셋 STR-, 글리프 스프라이트, 메타데이터, AGENTS.md,
                    STRUCTARA_BRAND_DECISIONS.md 전부)
Structara 선택 시 → §4.2의 "folio = TAVONEL" 브랜드 근거가 소멸한다.
                   대응면의 정당성을 제품 사실(원문↔지식)로만 다시 세워야 한다.
결정 전까지 브랜드 자산(심볼 · 워드마크 · 글리프) 제작을 착수하지 않는다.
```

**G-B · 서체 획득** — 이 문서에서 가장 큰 결손이다. [§7](#type) 참조.

```text
A. 커스텀/독점 라이선스 커밋   최고 효과. 비용·기간 큼. 브랜드 clearance와 함께 결정
B. Linear 우회로 [권장]         스톡 가변 서체 + OpenType feature + 비정수 웨이트 + 크기 의존 트래킹
C. 유료 라이선스                무료 배포가 없는 서체. 한글 페어링은 여전히 별도 과제
```

**G-C · TIER 1 3D** — 폐기 / 마크 축소 / 원안 유지. [§9.2](#tier1) 참조. **폐기 권장.** 폐기하면 Hero가 어포던스가 되고([§12.2](#act1)) 예산이 플랫폼 크래프트([§18](#platform))로 전용된다.

**G-D · KO 로케일 도입 여부** — 도입하면 i18n · hreflang · 번역이 별도 트랙으로 열린다. 미도입이면 [§7.4](#ko-type)의 한글 토큰은 보류 상태로 두고 `text-wrap: balance`의 언어 게이트만 지금 건다.

**G-E · `SourceRef`에 rotation / cropbox 추가** — 백엔드 API 계약 변경이므로 시각 설계 범위 밖이다. 미승인 시 [§2.4](#strategy) 전략의 세 조각 중 둘이 무너진다. 착수 전 백엔드 합의 필요.

**부수 결정 3건** — 사진 예외를 열 것인가([§15.4](#photo)) · 액센트 색상각을 벤치마크에서 얼마나 벌릴 것인가([§6.2](#accent)) · 검증 뷰포트를 4폭(현행 `AGENTS.md`)과 7종([§20](#responsive)) 중 어느 쪽으로 통일할 것인가.

* * *

<a id="part-1"></a>
# PART I · 포지셔닝

<a id="current"></a>
## 1. 현재 상태 — 코드가 말하는 것

라이브 사이트는 기존 명세를 **구조적으로는 충실히 따랐다.** 홈 11개 섹션, 측정되지 않은 지표는 `Not measured`로 표기, 조작된 로고·인용 0건, 금지 미학 회피. 명세는 대부분 지켜졌다. 결과가 의도와 어긋난 것은 실행 실패가 아니라 **명세의 형태 문제**다.

<a id="root-cause"></a>
### 1.1 근본 원인

기존 문서군이 동시에 요구한 것 — 3D 기본 OFF, AI 이미지 금지, free-asset-first, 임의 도형 금지, custom 시각물 승인 전 착수 금지, 스톡 사진 전면 제한, bento/카드월/글래스/그라디언트/파티클 금지.

이 교집합에서 에이전트가 승인 없이 안전하게 만들 수 있는 것은 **텍스트 · 1px 보더 · 표**뿐이다. 결과가 정확히 그것이다.

**금지 목록은 추함을 막을 뿐 아름다움을 만들지 않는다.**

<a id="secondary-cause"></a>
### 1.2 부차 원인 — 실측 근거 포함

| \# | 원인 | 증상 | 근거 |
| --- | --- | --- | --- |
| D-01 | 명세가 *인벤토리*만 규정하고 *형태*를 규정하지 않음 | 섹션은 다 있는데 기억에 남는 게 없음 | — |
| D-02 | 홈 11개 섹션의 시각 무게가 사실상 동등 | 위계 없음, 시선이 멈출 곳 없음 | `marketing-landing.tsx:50–341` |
| D-03 | 명도 대비는 있으나 배치가 하드컷이 아님 | 어두운 면이 흩어져 사건으로 읽히지 않음 | `--st-night` 면 4곳: `.st-transformation` · `.st-security-band` · `.st-footer` · `.st-route-cta` |
| D-04 | `01`–`04` 번호 라벨이 두 섹션에서 노출 | 프레젠테이션 덱 문법 | `marketing-landing.tsx:21,27,33,39` 및 `:290` |
| D-05 | 진실성 경계를 고객 화면 1층에 노출 | 세일즈 페이지가 내부 감사 보고서로 읽힘 | `st-benchmark` 4행이 전부 `Not measured` |
| D-06 | 브랜드 확정을 상표 clearance 뒤로 미룸 | 시각 앵커 부재 → 폰트+선으로 회귀 | 푸터의 working-name 고지 |
| D-07 | 실제 제품 픽셀이 홈에 **0장** | 무엇을 파는지가 글로만 설명됨 | `public/product/*.webp` 6장은 `/product/*`에서만 사용 |
| D-08 | 서체가 스톡 기본값 | 크래프트의 1순위 신호가 비어 있음 | Aptos/Pretendard/Inter 스택. `--st-serif`는 미정의 |
| D-09 | 서명 순간이 없음 | 기억에 남을 지점이 0개 | 유일한 후보인 WebGL 씬은 6초 후 무한 패럴랙스로 흐른다 |
| D-10 | Creative 점수를 구현 주체가 자체 채점 | 낮은 품질이 통과 판정 | — |

<a id="already-good"></a>
### 1.3 이미 충족된 것 — 다시 만들지 않는다

```text
홈 <table> 0개                      st-metric-table 은 div/span 그리드
setInterval 기반 진행률 0건          src 전체 0건
Google Fonts CDN link 0건
skip-to-content 링크                 layout.tsx:69
Hero LCP = 포스터 이미지             priority <Image>, AVIF 71KB (예산 140KB 내)
SSE durable event 25종 · 시퀀스 갭 복구 · 중복 제거 · replay      event-reducer.ts
진행률은 8단계 가중 실측 · ETA 없음   weightedOverallProgress
죽은 버튼 CI 검사                    scripts/verify-button-contracts.mjs (범위는 §14.3에서 확장)
조작된 로고 · 인용 0건               structara-content.ts:596 이 명시적으로 배제
캡처 파이프라인                      scripts/capture-*.mjs → assets/product · assets/public-proof
R3F 3D 씬 · dynamic import · 게이트   structara-hero.tsx (무한 패럴랙스만 제거하면 된다)
```

<a id="pivot"></a>
### 1.4 방향 전환

```text
BEFORE   금지 목록 → 안전한 최소 출력 → 무해하지만 무성격
AFTER    단일 형태 확정 → 픽셀 고정 → 반복 → 소유 가능한 시각 언어
```

* * *

<a id="competition"></a>
## 2. 경쟁 지형

2026-08-07 기준 Reducto · LandingAI(ADE) · Unstructured · LlamaParse · Mistral Document AI · Docsumo · Extend를 직접 확인했다. Chunkr · Datalab은 SPA로 렌더 불가 — **미확인 상태를 유지한다.**

<a id="cliche"></a>
### 2.1 카테고리 클리셰 — 우리가 하면 안 되는 것

```text
헤드라인 문법
  "[동사] + [messy / complex / hardest] documents → [structured / AI-ready / clean] data"
  LlamaParse 가 전형: "Parse transforms messy documents into AI-ready data at scale"
  Reducto "Turn documents into data." · Extend "your hardest documents"
  Unstructured "Transform complex, unstructured data into clean, structured data" (부제)
  Chunkr title tag "Complex documents to high-quality data"  ← 가장 순수한 사례

기능 나열
  Parse / Extract / Split (+ Classify)
  Reducto · LandingAI · Extend 가 거의 같은 단어를 쓴다

증거 방식
  아티팩트에서 분리된 숫자 하나
  Reducto "5,000,000,000 pages processed" · LandingAI "99.16% of DocVQA"
  Unstructured "87% of the Fortune 1000" · Mistral "98%+ accuracy"

CTA
  무료 시작 + 영업 문의 좌우 배치
```

**주의** — v2가 "섹션 골격을 7개 사 중 6개가 공유한다"고 적은 것은 과장이다. 실측하면 FAQ는 2곳, 후기 섹션은 4곳, 보안 섹션은 3곳뿐이다. **골격이 아니라 문형과 증거 방식이 겹친다.**

<a id="white-space"></a>
### 2.2 실제 빈 공간 — 3개

v2가 적은 네 항목 중 셋은 이미 점유돼 있다. 남은 것은 아래 셋이며, **v3의 전략 전체가 여기 걸린다.**

| 빈 공간 | 왜 비어 있는가 |
| --- | --- |
| **업로드 → 값 클릭 → 인용 스팬**을 한 화면에서 | Docsumo는 클릭-소스만(고정 문서), Unstructured는 업로드만(소스 없음). **둘을 합친 곳이 없다** |
| **실패한 문서가 Hero에 있는 상태** | 불확실성을 파는 곳은 많다. 그러나 전부 "우리가 잡아주는 기능"이지 "우리가 틀렸다"가 아니다. 보류 중인 실물을 첫 화면에 두는 곳은 없다 |
| **citation-to-answer 충실도**를 공개 지표로 | 위치 정확도(bbox)는 Extend가 이미 공개한다. "이 인용이 이 값을 실제로 뒷받침하는가"를 재는 곳은 없다 |

**이미 점유된 것 — 우리가 이긴다고 주장할 수 없는 것**

```text
문서를 홈 주인공으로          Mistral 이 한다 (실제 렌더 문서 4종 + JSON). 다만 정적이다
citation 을 인터랙션으로       Docsumo 가 한다. 다만 고정 문서이고, 페이지 중간이며, 운영팀 언어다
grounding 지표 공개           Extend RealDoc-Bench (Apache-2.0, IoU ≥0.5 헝가리안 매칭,
                             bbox·블록타입 F1 / adjusted F1 / mAP)
불확실성 노출                 Extend "Flag uncertainty before production"
                             LandingAI "Confidence scoring surfaces results that may need human review"
                             Docsumo "Review Failed" 상태 + 100% 미만 신뢰도
                             Reducto "VLMs make corrections to mistakes"
```

<a id="threat"></a>
### 2.3 경쟁 위협 — 순위가 바뀌었다

**1순위는 Extend다.** 홈에 경쟁사 벤치마크 표를 직접 올린다.

```text
Extend Parse 2.0   95.7%
Gemini 3.5 Flash   89.04%
Azure DI           88.8%
AWS Textract       70.5%
+ "Read the benchmark" → Apache-2.0 공개 저장소 + HF 데이터셋 + eval CLI
+ 자기 약점을 문서화한다: "The gap appears in denser structured regions"
```

**증거 제시에서 우리보다 앞서 있다.** "클릭해 들어갈 수 있는 증거가 없다"는 v2의 전제는 여기서 무너진다.

**2순위는 Docsumo다.** 인터랙션 자체를 이미 갖고 있다 — `Every field has a confidence score and a source span`, `Click a field to see its source`, 페이지 앵커(`doc-001.pdf · pg 1`), 신뢰도 100/99/98/97%. 약점은 위치(13개 섹션 중 5–6번째)와 언어(개발자가 아니라 운영팀)다.

**LandingAI는 여전히 말하고 보여주지 않는다.** 부제에 `Fully auditable, traceable`이 있고 필러가 Accuracy / Proof / Speed 셋인데, Hero는 `lottie-animation-data-hero.webp` — 추상 Lottie다.

**Mistral은 형태를 이미 갖고 있다.** Hero가 계약서 3페이지 · 인보이스 · 통계 표 · 손글씨 수식 유도와 각각의 JSON 출력이다. **정적이라는 것만이 우리의 여지다.**

<a id="strategy"></a>
### 2.4 전략 — 조각을 합치는 것

> 트레이서빌리티를 더 크게 주장하지 않는다.
> **홈페이지 자체가 증명이 되게 만든다.**

**근거가 "아무도 안 한다"가 아니다.**

```text
문서를 주인공으로            Mistral 이 한다.   차이 = 정적 ↔ 조작 가능
citation 을 인터랙션으로      Docsumo 가 한다.   차이 = 고정 문서 ↔ 사용자 문서
grounding 지표               Extend 가 공개한다. 차이 = 위치 정확도 ↔ 인용-답변 충실도
실패를 보여주기              모두가 "잡아준다"고 판다. 차이 = 기능 ↔ 실물

→ 우리 주장은 "우리만 한다"가 아니라
  "네 조각이 흩어져 있고, 합치면 그게 제품의 형태와 같은 모양이다" 이다.
```

**[확정] 이 전략은 세 조각을 다 갖추지 못하면 성립하지 않는다.**

```text
□ 사용자가 자기 문서를 올릴 수 있어야 한다     → §12.2 Hero 를 어포던스로
□ 값을 클릭하면 원문 스팬이 보여야 한다        → §14.4 좌표 계약이 전제 조건
□ 보류된 것이 보류된 채로 남아야 한다          → §11 R3 흉터. 유일한 순수 공백

셋 중 하나라도 빠지면 이미 있는 경쟁사보다 못한 화면이 된다.
특히 셋째가 빠지면 남는 건 "Docsumo + 업로드" 일 뿐이다.
```

* * *

<a id="brand-copy"></a>
## 3. 브랜드 전략과 카피

<a id="category"></a>
### 3.1 카테고리 정의

```text
The Knowledge Compiler

흩어진 원문 자료를 사람과 AI가 함께 쓰는
구조화 · 검증 · 연결 · 이동 가능한 지식으로 변환한다.
```

다음 중 어느 하나로도 정의되지 않는다: PDF Converter · OCR API · Document Parser · RAG Preprocessor · Knowledge Graph Builder.

<a id="personality"></a>
### 3.2 브랜드 성격

```text
Editorial Precision          편집자의 정밀함
Quiet Intelligence           조용한 지능 — 과시하지 않음
Evidence-first               근거가 먼저
Legible Technicality         기술적이되 읽힘
Premium without decoration   장식 없는 고급
Trust through visibility     숨기지 않아서 생기는 신뢰
```

<a id="hero-copy"></a>
### 3.3 Hero 카피

§2.1의 문형을 1행에서 뺀다.

**Direction 1 — 근거 우선 [권장]**

```text
KO 1행    모든 결과는
          정확한 원문으로 돌아갑니다.
EN 1행    Every output returns
          to its source.
KO 부제   문서를 구조화하고 원문 근거로 검증해,
          사람과 AI가 함께 재사용할 수 있는 지식으로 컴파일합니다.
```

**Direction 2 — 보류 우선, 더 공격적**

```text
KO 1행    검증되지 않은 것은 결과에 넣지 않습니다.
EN 1행    Nothing enters your knowledge unverified.
```

**Direction 3 — 기존 유지**

```text
KO 1행    흩어진 문서를 하나의 검증된 지식으로.
```

→ 클리셰 리스크. A/B에서 열세면 즉시 폐기.

세 방향을 **동일 레이아웃 · 동일 데이터**로 만들어 [§25.1](#g1)의 블라인드 테스트로 결정한다. 이 결정은 오너가 한다.

**현행 H1은 `Your AI is only as good as the knowledge it receives.`** — 11단어로 [§25.3](#g3)의 10단어 상한 경계에 걸린다. 세 방향 모두 10단어 이하로 만든다.

<a id="cta"></a>
### 3.4 CTA 체계

```text
Primary     Start compiling        (전 사이트 문구 고정)
Secondary   Inspect the proof      (Hero · Proof 라우트)
Enterprise  Talk to sales          (Footer · Pricing · Security)
```

- 섹션당 primary 1개. 홈 전체에서 primary는 **2회**(Hero, Close).
- 두 CTA의 라벨은 반드시 다르다. Figma(`Get started` 2회)와 Clerk(`Start building for free`를 Hero 안에서만 2회)이 범한 실수다.
- CTA 3개 배치 금지.

**현행 위반** — `Build your knowledge`가 홈 1회 렌더에 **4회**(Hero · Close · 헤더 · 푸터) 나온다. 헤더/푸터를 각각 다른 문구로 바꾼다.

<a id="forbidden-copy"></a>
### 3.5 금지 표현

```text
100% 정확 · 완벽한 이해 · zero hallucination
업계 최고 · 최고의 모델 · 혁신적 · 획기적 · 최첨단
Production verified / Public benchmark verified   (외부 게이트 전)
공포 마케팅 ("PDF는 AI가 이해 못합니다")
Parse / Extract / Split 기능 나열                  ← 카테고리 클리셰
"messy documents into clean data" 계열 문형        ← 카테고리 클리셰
"Build the future of ..." 류 공허 헤드라인          ← AI 슬롭 신호
```

<a id="part-2"></a>
# PART II · 시각 언어

<a id="facing-pages"></a>
## 4. 단일 형태 — FACING PAGES / 대응면

<a id="form"></a>
### 4.1 형태 정의

사이트의 모든 장면은 하나의 형태를 변주한다.

```text
┌──────────────────────┬─┬──────────────────────┐
│                      │ │                      │
│      VERSO           │S│        RECTO         │
│      원문면            │P│        지식면          │
│  실제 문서 페이지       │I│  구조화·검증된 산출물    │
│  (따뜻한 종이)          │N│  (백색 / 계기면)       │
│                      │E│                      │
│      ●───────────────┼─┼──────────────▶ ●     │
│      근거 스레드        │ │                      │
└──────────────────────┴─┴──────────────────────┘
```

- **VERSO(좌)** — 언제나 원문. 실제 렌더된 페이지.
- **SPINE(중앙)** — 1px 규칙선 + 40–72px 간격. 접힌 folio의 등.
- **RECTO(우)** — 언제나 산출물.
- **THREAD** — 좌측 bbox에서 우측 행으로 **실제 좌표로 계산된** 곡선.

<a id="why-form"></a>
### 4.2 왜 이 형태인가 — 그리고 무엇이 진짜 차별점인가

**좌우 대응 자체는 크래프트가 아니라 카테고리 기본값이다.** 벤치마크 3곳(Linear · Stripe · Vercel)에는 없지만, 개발자 도구 한 단계 아래에서는 흔하다.

```text
resend.com   ① Node SDK 코드(좌) → HTTP 200 + 이메일 ID(우)
             ② React 이메일 컴포넌트(좌) → 렌더된 "Welcome to ACME" 이메일(우)
                ← 원문면/결과면의 문자 그대로의 사례
retool.com   프롬프트(좌) → 생성된 대시보드(우)
cursor.com   에디터/CLI(좌) → localhost:3000 프리뷰(우)
```

**차별점은 형태가 아니라 좌측의 성질이다.**

```text
Resend   좌 = 개발자가 쓴 코드      (사람이 만든 것)
Retool   좌 = 사용자가 친 프롬프트   (사람이 만든 것)
Cursor   좌 = 에디터 상태           (사람이 만든 것)
──────────────────────────────────────────────────
우리     좌 = 우리가 통제하지 않은 실제 문서 페이지
         그리고 스레드가 그 페이지의 실제 좌표에서 계산된다
         그리고 검증되지 않은 것은 우측에 도달하지 못한 채 남는다
```

**[확정] 아래 셋 중 둘째와 셋째가 이 컨셉을 방어한다.** 첫째만으로는 Resend와 같은 화면이다. 따라서 [§14.4](#coord) 좌표 계약과 [§11.2](#live-rules) R3 흉터는 부가 기능이 아니라 **성립 조건**이다.

| 요구 | 충족 |
| --- | --- |
| 10초 카테고리 이해 | 좌우 대응이 곧 "문서 → 검증된 지식" |
| 제품 진실성 | 좌우 모두 실제 데이터. 플레이스홀더가 들어갈 자리가 물리적으로 없다 |
| 에셋 교착 해소 | 스톡·AI 이미지 없이 성립. 재료는 "실제 페이지"와 "실제 UI" |
| 성능 | DOM + SVG + 이미지. WebGL 불필요 — 2026년에는 오히려 강점([§9.1](#depth-tiers)) |
| 브랜드 소유 | **G-A에 종속.** Structara 확정 시 folio 근거는 소멸하고 제품 사실로만 방어한다 |

<a id="fractal"></a>
### 4.3 프랙탈 — 5개 스케일에서 반복

| 스케일 | 구현 |
| --- | --- |
| 사이트 | 전체가 verso/recto 비대칭 그리드 |
| 섹션 | Hero · Proof · Knowledge가 모두 대응면 |
| 컴포넌트 | Proof 카드 \= 좌 crop / 우 결과 |
| 행 | 표의 각 행 좌측에 8px 원문 마커 |
| 요소 | Evidence chip \= 두 면 + 실 모양의 4×10px 글리프 |

<a id="form-forbidden"></a>
### 4.4 이 컨셉의 금지

- 좌우를 바꾸지 않는다. 원문은 **항상** 좌측 (RTL 로케일 예외).
- **좌표 없는 장식 스레드 금지.** 좌표가 없으면 `threads=[]`로 둔다. 임시로 선을 그려두는 것은 허용되지 않는다.
- 한 화면에 스레드 4개 이상 동시 활성 금지 (1–3개).
- 대응면 안에 카드 그리드를 넣지 않는다.

* * *

<a id="materials"></a>
## 5. 2재질 시스템 — PAPER ↔ INSTRUMENT

현재 사이트의 실패는 밝기가 없어서가 아니라 **밝기가 의미와 묶여 있지 않아서**다. `--st-night` 다크 면이 이미 4곳에 있지만 어느 것도 "여기서부터 제품이다"를 뜻하지 않는다. 어둠이 섹션 장식으로 흩어져 있으니 스크롤에 사건이 생기지 않는다.

|  | PAPER | INSTRUMENT |
| --- | --- | --- |
| 의미 | 원문, 사람의 언어, 편집 | 컴파일러, 기계의 정밀, 제품 |
| 사용처 | Hero 카피, 원문면, Trust, Footer, 공개 라우트 본문 | 제품 앱 전체, 홈의 제품 실연, Proof 계기부 |
| 타이포 | 에디토리얼 (큰 디스플레이, 넓은 여백) | 조밀·계기적 (13–14px, tabular) |
| 라디우스 | 2–4px | 6–8px |
| 깊이 | 알파 헤어라인 + 배경 명도차. **장식 그림자 금지** | 알파 헤어라인 + 1단계. **어포던스 그림자 허용** |

<a id="the-cut"></a>
### 5.1 시그니처 순간 — The Cut

Hero(PAPER) 다음에 **화면 전폭 INSTRUMENT가 하드 컷으로 잘려 들어온다.** 페이드가 아니다. 경계에는 evidence 색 1px 규칙선 하나만 둔다.

```text
[ PAPER   Hero (어포던스)              88vh ]
──── 컷 ────
[ INSTRUMENT   Live Compile   전폭 · 76vh ]
──── 컷 ────
[ PAPER   Proof                        ]
[ INSTRUMENT   Knowledge   전폭 · 68vh ]
[ PAPER   Trust · Close                ]
```

**근거 사이트를 정정한다.** v2는 Vercel·Linear를 근거로 들었으나 실측하면 **Linear는 처음부터 끝까지 단일 다크**이고 Vercel의 라이트/다크는 밴드가 아니라 테마 모드 변형이다. 실제로 밴드를 교차시키는 곳은 **cursor.com · clerk.com · sierra.ai · anthropic.com**이다. Cursor를 비교 대상에 추가한다([§25.2](#g2)).

<a id="material-risk"></a>
### 5.2 재질 리스크 — PAPER가 AI 슬롭 신호와 겹친다

2026-06 공개된 AI 디자인 슬롭 디텍터(50규칙, 42개 빌드 수기 채점)의 **1번 규칙**이 정확히 이것이다.

```text
"Warm Accent — amber-and-cream palette signaling 'tasteful AI startup'"

같은 디텍터의 다른 규칙
  Dark Glow        다크 위 컬러 글로우 그림자
  Eyebrow Chrome   대문자 라벨 + 장식 점 + 뒤따르는 규칙선   ← §12.1 eyebrow 사양
  Safe Green       인디고를 금지하면 나오는 에메랄드 대체재
  근거 없는 세리프와 이탤릭
```

> [단일 출처 · 신뢰도 중] 2차 출처 한 곳이다. 그러나 우리 사양과 정확히 겹치므로 대응한다.

따뜻한 종이 + 세리프 + near-black은 2025년에는 차별화였고(Anthropic · Harvey), 2026년 중반에는 LLM의 기본 출력이다. **재질을 바꾸지는 않는다. 특정성으로 번다.**

```text
[확정] 대응 4건
□ --paper-1 을 근거 있는 실제 종이에서 뽑는다. 지종·평량을 decision.md 에 기록한다
□ 그레인을 CSS 노이즈로 넣되 종이처럼 거동하게 만든다 (§15.3)
□ 액센트에서 앰버 · 테라코타 · 에메랄드를 제외한다 (전부 디텍터 반사 항목)
□ eyebrow 를 "대문자 라벨 + 점 + 규칙선" 조합에서 바꾼다 (§12.1)
```

* * *

<a id="tokens"></a>
## 6. 디자인 토큰

현행 코드에는 `src/styles/` 디렉터리가 없다. 토큰은 `src/app/{globals,product-shell,enterprise-refresh,structara}.css` 4개 파일 16,048줄에 분산돼 있고, 뒤에 적재되는 파일이 앞 파일의 `:root`를 통째로 덮는다. 아래는 **신규 생성물**이며 이관 계획은 [§23.2](#css-removal)에 있다.

<a id="tokens-css"></a>
### 6.1 `src/styles/tokens.css` [확정]

**적재 순서** — `layout.tsx`에서 **가장 먼저** import한다. 현행 4개 CSS보다 앞이다.

```css
:root {
  color-scheme: light dark;

  /* ── PAPER surface ──────────────────────────────── */
  --paper-0:      oklch(100%  0     0);          /* #FFFFFF  recto / 지식면 */
  --paper-1:      oklch(96.6% 0.006 84);         /* #F7F5F1  verso / 원문면 */
  --paper-2:      oklch(93.5% 0.012 84);         /* #EFEBE3  함몰면, 코드, 인용 */
  --ink-0:        oklch(16%   0.012 250);        /* #0B0D10 */
  --ink-1:        oklch(30%   0.014 250);        /* #2B3038 */
  --ink-2:        oklch(50%   0.012 250);        /* #626A76 */
  --ink-3:        oklch(63%   0.010 250);        /* #8B929C */

  /* ── INSTRUMENT surface ─────────────────────────── */
  --inst-0:       oklch(14%   0.010 250);        /* #0A0C10 */
  --inst-1:       oklch(18%   0.011 250);        /* #12151B */
  --inst-2:       oklch(22%   0.012 250);        /* #191D25 */
  --inst-ink-0:   oklch(94%   0.005 250);        /* #EDF0F4 */
  --inst-ink-1:   oklch(74%   0.010 250);        /* #A6AEBA */
  --inst-ink-2:   oklch(54%   0.012 250);        /* #6B7481 */

  /* ── RULES — 알파다. 하드코딩 헥스가 아니다 (§6.3) ── */
  --rule-paper-1: oklch(16% 0.012 250 / 6%);
  --rule-paper-2: oklch(16% 0.012 250 / 12%);
  --rule-inst-1:  oklch(100% 0 0 / 5%);
  --rule-inst-2:  oklch(100% 0 0 / 9%);

  /* ── SEMANTIC (색상각은 G-E 결정 후 고정) ────────── */
  --brand:        oklch(48% 0.20 265);   --brand-d:    oklch(72% 0.14 265);
  --brand-hover:  oklch(53% 0.20 265);
  --brand-press:  oklch(42% 0.19 265);
  --evidence:     oklch(60% 0.11 210);   --evidence-d: oklch(78% 0.11 210);
  --verified:     oklch(48% 0.10 165);   --verified-d: oklch(74% 0.11 165);
  --review:       oklch(52% 0.12  70);   --review-d:   oklch(78% 0.12  70);
  --danger:       oklch(50% 0.17  25);   --danger-d:   oklch(74% 0.16  25);

  /* ── SPACING (4px base) ─────────────────────────── */
  --s-1:4px;   --s-2:8px;   --s-3:12px;  --s-4:16px;
  --s-5:24px;  --s-6:32px;  --s-7:48px;  --s-8:64px;
  --s-9:96px;  --s-10:128px; --s-11:160px; --s-12:200px;

  /* ── RADIUS ─────────────────────────────────────── */
  --r-paper:2px;  --r-paper-lg:4px;
  --r-inst:6px;   --r-inst-lg:8px;
  --r-media:12px;

  /* ── DEPTH — 어포던스 전용 (§6.3) ────────────────── */
  --depth-focus:   0 0 0 3px oklch(48% 0.20 265 / 30%);
  --depth-hover:   0 1px 2px oklch(16% 0.012 250 / 5%);
  --depth-overlay: 0 1px 0 oklch(0% 0 0 / 50%), 0 8px 24px -12px oklch(0% 0 0 / 60%);

  /* ── MOTION ─────────────────────────────────────── */
  --t-1: 90ms;  --t-2: 140ms; --t-3: 200ms;
  --t-4: 280ms; --t-5: 420ms;
  --e-out:   cubic-bezier(0.23, 1, 0.32, 1);
  --e-inout: cubic-bezier(0.77, 0, 0.175, 1);
  --e-drawer: cubic-bezier(0.32, 0.72, 0, 1);
}
```

**`--t-cine`는 정의하지 않는다.** Hero 시네마틱은 토큰이 아니라 장면 스크립트로 관리한다([§9](#depth)).

**OKLCH를 쓰는 이유** — Widely available(2025-11)이고, 명도 축이 지각적으로 균일해서 PAPER↔INSTRUMENT 대응 램프를 수치로 맞출 수 있다. `color-mix()`도 Widely available이므로 상태 색은 램프를 손으로 나열하지 않고 혼합으로 만든다.

<a id="accent"></a>
### 6.2 색 사용 규칙

```text
중립 (종이 · 잉크 · 계기면)   90%
브랜드                        2%
Evidence                     2%
상태색                        3%
기타                          3%
```

**[확정] 규칙은 "액센트 1 헥스"가 아니라 "액센트 1 색상 + 상태 램프"다.** 실측하면 Linear도 4단 램프(`#5e6ad2` / `#5e69d1` / `#7170ff` / `#828fff`) + 시맨틱 그린을 쓴다. Vercel은 3액센트, Anthropic은 8액센트다. 규율은 **색상각을 하나로 묶는 것**이지 값을 하나로 묶는 것이 아니다.

브랜드 색이 나타날 수 있는 곳은 4곳뿐이다 — ① Primary CTA 배경 ② 활성 라우트 2px 마커 ③ 포커스 링 ④ 스레드가 활성화된 순간. **로고에도 쓰지 않는다.**

**[게이트 부수] 색상각을 벤치마크에서 벌린다.** 현행 후보 `oklch(48% 0.20 265)`는 Linear `#5e6ad2`, Stripe `#635BFF`와 같은 인디고 계열이다 — 벤치마크 3곳 중 2곳과 겹친다. 앰버·테라코타·에메랄드(슬롭 디텍터 반사 항목)와 인디고(벤치마크 중복)를 동시에 피하는 구간은 **청록–시안 계열(약 200–230°)** 과 **깊은 청자–남색(약 250–260°)** 이다. Evidence 색과 충돌하지 않도록 브랜드는 250–260°, Evidence는 200–210°로 둔다. 정확한 값은 시안 3안에서 결정한다.

**한 뷰포트에 비중립 색상이 2개 이상 보이면(고객 로고 제외) 실패다.**

<a id="surfaces"></a>
### 6.3 표면 — 알파 헤어라인과 조율된 깊이

**[확정] 1px 규칙선은 틀린 프리미티브다.**

```text
v2          1px solid --rule-1 (#E4E0D8 하드코딩)
Linear 실제  rgba(255, 255, 255, 0.05) ~ 0.08

알파 보더는 아래 면을 타고 흐르므로 다크/라이트 전환, 중첩 면,
스크린샷 위에서 전부 살아남는다. 하드코딩 헥스는 면이 바뀌는 순간 어긋난다.
```

**[확정] "그림자 0"도 벤치마크와 모순된다.** Linear는 그림자를 쓴다 — inset `0 0 12px rgba(0,0,0,.2)`, 드롭다운 `0 4px 12px`, 포커스 링 `0 0 0 3px`, 버튼 호버 `0 1px 2px`. **조율된 깊이지 장식이 아니다.** 전면 금지는 장식이 아니라 어포던스를 제거한다.

```text
허용   포커스 링          --depth-focus     모든 면
       버튼/행 호버        --depth-hover     모든 면
       팝오버 · 모달 · 드로어  --depth-overlay   모든 면

금지   카드에 기본 그림자
       섹션 컨테이너에 그림자
       컬러 글로우 (슬롭 디텍터 항목)
       PAPER 면의 장식적 깊이 — 깊이는 알파 헤어라인과 배경 명도차로만
```

**라디우스** — 5토큰 스케일만. **중첩 시 안쪽 반경 \= 바깥 반경 − 패딩.** 한 페이지에 6px/10px/20px이 섞이면 스크린샷에서 감지된다. 현행은 border-radius 선언 195건 중 토큰 사용이 23건(12%)이고 리터럴이 23종이다 — W0의 실질 작업량이다.

**모든 섹션을 rounded card로 감싸지 않는다.**

<a id="grid"></a>
### 6.4 그리드와 리듬

```text
content max      1320px
columns          12
gutter           24px
margin           clamp(24px, 5vw, 72px)
readable max     680px
```

**대응면 배분** — 이 비율만 허용한다.

| 장면 | verso : recto |
| --- | --- |
| Hero | 5 : 7 |
| Proof | 7 : 5 |
| Knowledge | 4 : 8 |
| Trust | 6 : 6 |

6:6은 Trust 한 곳에서만. **균등 분할은 지루하다.**

**세로 리듬**

```text
Hero                  min(88vh, 920px)
INSTRUMENT 전폭 면      76vh / 68vh
PAPER 섹션 (1440)      상 128px / 하 160px
PAPER 섹션 (모바일)     상 72px  / 하 88px
섹션 경계             1px --rule-paper-1, 전폭
```

`clamp(96px, 12vw, 184px)` 같은 동일 패딩 반복 금지. 임의값(`padding: 73px`) 금지 — 전부 4px 배수. **현행 gap 53종 · padding 204종 중 5·7·9·11·13px이 대량이다.** W0에서 전면 재작성한다.

컨테이너는 1320px이지만 **Hero와 제품 실연은 전폭으로 breakout**한다.

<a id="repetition"></a>
### 6.5 반복 상한 (자동 검사 대상)

한 뷰포트 안에:

- 동일 크기·동일 형태 요소 **4개 초과 금지**
- 카드 컴포넌트 홈 전체 **6개 초과 금지**
- 연속된 카드 그리드 섹션 **2개 초과 금지** — 사이에 전폭 구성을 넣는다
- `<table>` 홈에 **0개**
- primary CTA 섹션당 1개

**현행 위반** — `st-pillars` 4 · `st-use-cases` 4 · `st-chapters` 4가 연속 3섹션에 걸쳐 있고 카드형 `article`이 14개다.

* * *

<a id="type"></a>
## 7. 타이포그래피

**이 절이 v2의 가장 큰 결손이었다.** v2에는 서체 *선택*만 있고 *획득 전략*이 없었으며, 선택한 서체가 2026년의 템플릿 신호였다.

<a id="type-why"></a>
### 7.1 왜 서체가 1순위인가

조사한 상위 사이트 중 자체 서체를 출하하지 않는 곳은 Linear 하나뿐이다.

```text
OpenAI Sans              openai.com
Cursor Gothic            cursor.com          + Berkeley Mono Variable
Anthropic Sans / Serif   anthropic.com       3종 커스텀 패밀리
PPLX Sans / Serif / Mono perplexity.ai       variable
Geist / Mono / Pixel     vercel.com          + 숫자 전용 DSEG7 Classic
figmaSans / figmaMono    figma.com           웨이트 320 (비표준)
Harvey Serif / Sans      harvey.ai
sohne-var                stripe.com          웨이트 축 1–1000
TWK Lausanne             ramp.com            독점 라이선스
Arcadia                  mercury.com         독점 라이선스
```

**Inter는 정확히 반대 신호다.** 큐레이션 사이트 서체 사용 순위 1위(664회, 2위의 약 1.7배)이고, 디자인 스튜디오의 AI-슬롭 진단 첫 항목이 "Inter as default"이며, **OpenAI 공식 frontend-skill이 회피 대상 스택으로 Inter를 명시한다**(`avoid default stacks: Inter, Roboto, Arial, system`). **Pretendard도 같은 문제다** — 한글판 Inter다.

<a id="type-acquire"></a>
### 7.2 획득 전략 [게이트 G-B]

```text
A. 커스텀 / 독점 라이선스 커밋
   Latin 커스텀 또는 무료 배포 없는 유료 서체 + 한글 가변 패밀리(Sandoll/Yoon 계열)를
   획 두께 · 스트레스 각도가 맞도록 페어링.
   최고 효과. 비용·기간 큼. 브랜드 clearance(G-A)와 함께 결정.

B. Linear 우회로 [권장 — 즉시 착수 가능]
   스톡 가변 서체를 쓰되 스톡으로 안 읽히게 만든다. Linear의 실제 수법:
     · OpenType feature 전역 적용        cv01, ss03  (a/g 대체자 — Inter의 서명을 지운다)
     · 비정수 웨이트 축 사용             510 / 590   (400/500/600 금지)
     · 크기 의존 트래킹                  64px에서 −1.408px → 본문 0
   이 셋만으로도 "스톡 Inter"에서 벗어난다. v2에 이 기법이 한 줄도 없었다.

C. 유료 라이선스만
   Söhne · TWK Lausanne · Arcadia 급. 한글 페어링은 여전히 별도 과제.
```

**어느 쪽이든 결정과 함께 확정해야 하는 것**

```text
□ 가변 축 운용 계획 — 사용할 웨이트 스톱, opsz 사용 여부
□ 크기별 트래킹 함수 — 단일 letter-spacing 값 금지
□ 한글–라틴 획 두께 정합 기준 — x-height 비, 스트레스 각도
□ 로딩 전략 — preload 대상, font-display, subset 범위, 총 페이로드 ≤90KB
□ self-host 방식 — next/font/local. Google Fonts CDN link 금지 (현행 0건 유지)
```

<a id="type-scale"></a>
### 7.3 스케일 (1440)

| 역할 | size / line | tracking | weight |
| --- | --- | --- | --- |
| Display 1 | 72 / 76 | −0.03em | 620 |
| Display 2 | 52 / 58 | −0.025em | 600 |
| Title 1 | 34 / 42 | −0.02em | 600 |
| Title 2 | 24 / 32 | −0.015em | 600 |
| Lead | 20 / 32 | −0.005em | 400 |
| Body | 17 / 30 | 0 | 400 |
| Small | 15 / 24 | 0 | 400 |
| Label | 12 / 16 | +0.08em | 500 (mono, 대문자) |

**B안을 택하면 weight를 620 → 590, 600 → 510처럼 비정수 스톱으로 옮긴다.** 표의 값은 A/C안 기준이다.

**현행 실측** — `font-size` 선언 667건 / 고유값 **72종**, 이름 있는 크기 토큰 **0개**. 최빈값이 `10px`(120) `11px`(118) `9px`(84) `8px`(78)이고 **≤8px 선언이 100건**이다. `rem` 기반 크기는 0건 — 200% 줌·사용자 폰트 크기 대응이 재설계 대상이다. weight 24종, line-height 26종, letter-spacing 29종이 공존한다. 위 8행으로 수렴시키는 것이 W0의 실질 작업량이다.

**[확정] 본문·UI 최소 크기 12px.** 현행 ≤8px 100건은 전수 상향한다.

<a id="ko-type"></a>
### 7.4 한글 오버라이드 [게이트 G-D]

한글은 광학적으로 작게 읽히고 줄바꿈 규칙이 다르다. **같은 px를 쓰면 실패한다.**

```css
:lang(ko) {
  --fs-scale: 1.03;
  --lh-body: 1.75;               /* Latin 1.55 → KO 1.75 */
  --tracking-display: -0.012em;  /* Latin −0.03em은 한글에서 뭉친다 */
}

:lang(ko) h1, :lang(ko) h2, :lang(ko) h3 {
  word-break: keep-all;
  text-wrap: initial;
  letter-spacing: var(--tracking-display);
}

:lang(ko) p { word-break: normal; }

@media (max-width: 480px) {
  :lang(ko) h1 { word-break: normal; }
}
```

**KO 로케일이 아직 없다.** `<html lang="en">` 하드코딩, `:lang()` 규칙 0건, i18n 설정 0건, hreflang 0건. G-D 결정 전까지 이 블록은 보류다.

**[확정] 단 이것 하나는 G-D와 무관하게 지금 고친다.** 현행 `text-wrap: balance`가 언어 게이트 없이 3곳(`structara.css:441, 784, 1986`)에 걸려 있고, `word-break: keep-all`도 4곳에 게이트 없이 있다. `:lang(en)` / `:lang(ko)`로 감싼다.

**Hero 헤드라인은 언어별로 개별 설계한다.** 같은 px에서 한글은 15–20% 더 많은 세로 공간을 차지한다. 번역해 고정 박스에 넣는 것이 아니라 **언어별로 단어 수를 세어 개행을 수동 지정**한다.

<a id="type-rules"></a>
### 7.5 공통 규칙

- 최대 행폭 **EN 60–72자 / KO 34–40자.** `max-width: 65ch`를 산문 컨테이너에만 (카드에 걸지 않는다).
- 본문 line-height 1.5–1.6, 헤딩 1.05–1.2. **전역 단일 값 금지.**
- Display : Body 비율 **≥ 3.5 : 1** (72/17 \= 4.2).
- 숫자는 전부 `font-variant-numeric: tabular-nums`.
- mono는 ID · 해시 · 좌표 · 이벤트명 **한 가지 용도**에만. 본문 문장에 mono 금지 (슬롭 디텍터 항목).
- Display 1은 페이지당 1회. Display 2는 최대 4회.
- 곡선 따옴표, 말줄임은 `…` 문자, 단위 앞은 non-breaking space.
- 헤딩에 `text-wrap: balance`(`:lang(en)`만), 본문에 `text-wrap: pretty`.
- 브랜드명 · 식별자에 `translate="no"`. 날짜·숫자는 `Intl` API.

* * *

<a id="identity"></a>
## 8. 브랜드 아이덴티티

**G-A 결정 전까지 착수하지 않는다.** 아래는 확정 후의 사양이다.

<a id="symbol"></a>
### 8.1 심볼 기하

```text
캔버스 24 × 24, stroke 1.75, 라운드 조인 없음

좌면(Source)     x 3–10,  y 3–21    상단 모서리 1.5 절단 (페이지 접힘)
스파인           x 11.5,  y 4–20    1px 수직선
우면(Knowledge)  x 14–21, y 6–18    상단 정렬, 좌면보다 짧음
스레드           (10,15) → (14,11)   각도 −34°
```

- 좌면이 우면보다 **길다** — 원문은 많고 지식은 압축된다.
- **−34°는 사이트의 유일한 대각선 각도**다. 스레드·화살표·그래프 엣지 전부 이 각도 계열.
- 16px에서 세 요소가 분리되어 보여야 한다. 안 보이면 우면을 줄이지 말고 stroke를 2.0으로.

<a id="wordmark"></a>
### 8.2 워드마크

- 대문자, 본문 서체의 620(또는 B안의 대응 스톱), tracking `+0.14em`.
- 심볼–워드마크 간격 \= 심볼 폭 × 0.5.
- 그라디언트 금지 · mono 워드마크 금지 · 심볼 회전 금지.
- 잠금: 수평 / 스택 / 심볼 단독 / KO 병기 (KO는 0.62배 `--ink-2`).

**현행** — `brand-mark.tsx`는 SVG가 아니라 `<span>`×2 + `<i>` 조합이다. 심볼은 신규 제작이다.

<a id="glyphs"></a>
### 8.3 구조 글리프 P0 12종

`page · block · table · figure · formula · evidence · verified · review · note · entity · relation · package`

- 24px 마스터, optical stroke 1.5px, 16/20/24/32 각각 힌팅.
- **전부 대응면 기하에서 파생** — 두 면 + −34°의 변주.
- 기능 아이콘은 **`@phosphor-icons/react`** (현행 39개 import). 브랜드 글리프와 **절대 혼용 금지.** 아이콘 라이브러리를 교체하지 않는다 — 79개 컴포넌트를 건드리는 일이며 시각 이득이 없다.
- 아이콘 폰트 금지. 인라인 SVG 스프라이트만.

**현행** — 스프라이트는 이미 있다(`public/brand/structara-glyphs.svg` + `structara-glyph.tsx`). 다만 선언 18종 중 마케팅에서 쓰이는 것은 6종이다. W0에서 12종으로 재정의하고 미사용 심볼을 제거한다.

<a id="part-3"></a>
# PART III · 깊이 · 모션 · 실시간

<a id="depth"></a>
## 9. 깊이 정책

"시네마틱하게 보이게 하자"와 "처리 과정을 실시간으로 보여주자"는 **서로 다른 문제**다.

| 요구 | 올바른 해법 | 잘못된 해법 |
| --- | --- | --- |
| 카테고리를 감각적으로 각인 | 어포던스 있는 Hero (또는 3D 한 장면) | 전 페이지 3D |
| 처리 과정을 실시간으로 | **이벤트 구동 2D 계기판** | 3D 파티클 · 추상 흐름 |

<a id="depth-tiers"></a>
### 9.1 3계층

```text
TIER 1  Signature      Hero 단 하나. G-C 결정 대상 (§9.2)
TIER 2  Live 2.5D      제품 실시간 화면. DOM/SVG/Canvas + CSS 깊이 단서 + 스크롤 구동 CSS
TIER 3  Micro depth    카드 스택 3장까지(각 2px), 페이지 썸네일 종이 두께,
                       그 외 깊이는 §6.3의 어포던스 3종에만
```

<a id="tier1"></a>
### 9.2 TIER 1 재판정 [게이트 G-C]

**현재 상태** — R3F 3D 씬이 **이미 라이브**다(`structara-webgl-scene.tsx`, `next/dynamic({ssr:false})`). GLB는 로드하지 않고 전부 절차적 프리미티브다. 타임라인은 `Math.min(elapsed, 6)`로 6초 클램프되지만 **그 이후 포인터 패럴랙스가 무한 지속**된다 — [§10.4](#motion-forbidden)의 금지 조항 위반이며 G-C 결정과 무관하게 즉시 제거한다.

**시장 판정 — 3D는 프리미엄 B2B에서 빠지는 중이다.**

```text
· Awwwards Site of the Day 9일치 중 B2B는 사실상 0 (음악·패션·영화·에이전시 포트폴리오)
· B2B 트렌드 조사가 "무거운 3D · WebGL 경험"을 회피 항목으로 분류
· Spline 씬 하나가 첫 렌더 전 800kB–2MB JS
· 모바일 페이지 중 JS 애니메이션 라이브러리를 싣는 비율 18.4%
· Vercel 자신의 지침: "avoid autoplay — animate in response to user actions"
  → 자동재생 원샷 시네마틱은 공표된 표준과 정면 충돌한다

반면 상위 3곳 중 2곳의 Hero 는 3D 가 아니라 동작하는 어포던스다
  vercel.com  "Drop to deploy" — 홈에서 파일을 떨어뜨리면 실제로 배포된다
  cursor.com  대화형 데모 (alt: "Interactive demo for sighted users")
  retool.com  프롬프트 입력 → 옆에서 대시보드 생성

3D 가 살아있는 곳은 씬이 아니라 마크로 쓸 때다
  resend.com  cube.mp4 / 3d-react.mp4 를 정지물처럼 쓰는 짧은 루프
```

**세 선택지**

```text
A. TIER 1 폐기, Hero 를 어포던스로  [권장]
   §2.4 의 첫 조각(사용자 업로드)을 Hero 로 끌어올린다.
   "문서를 여기에 놓아 보세요" → 실제로 컴파일이 시작된다.
   형태(대응면)는 그대로다 — 좌측이 사용자가 놓은 문서가 될 뿐이다.
   3D 예산 전부가 §18 플랫폼 크래프트로 전용된다.
   그리고 §2.2 의 첫 번째 빈 공간을 첫 화면에서 점유한다.

B. TIER 1 을 마크로 축소  (Resend 방식)
   12종 실루엣 씬을 만들지 않는다. 짧은 렌더 루프 또는 정지 렌더를 섹션 마크로만 쓴다.
   assets/3d/derivatives 의 기존 자산(hero-master.glb 456KB, 시안 PNG 3장,
   hero-loop-12s.mp4)을 재사용할 수 있다 — 전부 현재 미참조 상태다.

C. 원안 유지  (5.4초 원샷 + 완전 정지)
   지금의 무한 패럴랙스보다는 낫다.
   그러나 §22 예산·자동재생 금지와 계속 다투고,
   §25.4 스쿼트 테스트의 "3D 를 끈 포스터 상태에서도 메시지가 전달되는가"를
   통과한다면 애초에 3D 가 필요 없다는 뜻이 된다 — 이 자기모순을 안고 간다.
```

**A안을 택할 경우 폐기되는 것** — [§9.3](#silhouette)의 12종 실루엣 규격표, GLB 제작 파이프라인, W8 웨이브 전체. **유지되는 것** — 포스터 이미지(현행 `STR-HOME-T2-HERO-EN-*`, AVIF 71KB)를 Hero 배경 또는 대응면 우측 초기 상태로 계속 쓴다.

<a id="silhouette"></a>
### 9.3 12종 문서 실루엣 규격 (B·C안 전용)

동일 사각형 반복이 이전 Hero 실패의 핵심이었다. 아래를 벗어난 오브젝트는 만들 수 없다.

| \# | 종류 | 비율 | 두께 | 표면 식별 요소 |
| --- | --- | --- | --- | --- |
| 1 | Annual report | 3:4 세로 | 두꺼움 | 재무 표 그리드 + 섹션 밴드 |
| 2 | Research paper | 3:4 세로 | 얇음 | 2단 조판 + 수식 |
| 3 | Technical manual | 4:5 세로 | 두꺼움 | 챕터 탭 + 도해 박스 |
| 4 | Contract | 3:4 세로 | 중간 | 번호 조항 + 서명란 |
| 5 | Slide deck | 16:10 가로 | 얇음 | 썸네일 그리드 |
| 6 | Spreadsheet | 4:3 가로 | 얇음 | 조밀 셀 격자 |
| 7 | Scanned archive | 3:4, **2° 기울임** | 중간 | 종이 노이즈 + 스캔 밴딩 |
| 8 | Policy | 3:4 세로 | 중간 | § 번호 리스트 |
| 9 | Data dictionary | 5:4 가로 | 얇음 | 스키마 컬럼 |
| 10 | Support logs | 3:2 가로 | 매우 얇음 | 타임스탬프 행 |
| 11 | Public filing | 3:4 세로 | 중간 | 접수번호 + 표 |
| 12 | Personal notes | 1:1 정사각 | 매우 얇음 | 짧은 메모 + 링크 |

세로 3종 · 가로 4종 · 정사각 1종이 섞이고 두께는 4단계로 분포한다. **실루엣만 보고 종류를 구분할 수 있어야 한다.**

**제작 순서 (역순 금지)** — 정적 키프레임 3안(1440·390) → 오너 선택 + `decision.md` 커밋 → Blender 마스터(실제 페이지 텍스처 베이크) → glTF Transform 압축 → R3F 유한 타임라인 → 포스터 굽기 → 성능·폴백 검증.

**폴백 계약** — `width < 1024` · `prefers-reduced-motion` · `Save-Data` · WebGL2 없음 · 저메모리 · 컨텍스트 소실 → 최종 프레임 포스터(AVIF ≤140KB) 정적 표시.

**현행 게이트를 1024로 통일한다.** 지금은 JS가 `max-width: 960px`, CSS가 별도 규칙이다. 그리고 **WebGL2 지원 검사 · 컨텍스트 소실 처리 · 에러 바운더리가 전부 없다** — B·C안이면 신규 구현이다.

* * *

<a id="motion"></a>
## 10. 모션 시스템

v2는 규칙만 있고 수치가 없었다. 아래는 `emilkowalski/skills`의 공개 표준을 실측해 흡수한 값이다.

<a id="motion-semantics"></a>
### 10.1 의미 매핑 — 목록 밖의 애니메이션은 삭제

| 의미 | 모션 | 시간 |
| --- | --- | --- |
| 수집(intake) | 아래에서 쌓임 + 그룹핑 | `--t-4` |
| 파싱 | 국소 페이드 인 (이동 없음) | `--t-2` |
| 문제 발견 | 해당 영역만 격리 (앰버 테두리, 흔들림 없음) | `--t-3` |
| 복구 | 좌우 비교 슬라이드 | `--t-5` |
| 검증 | 체크리스트 순차 + 스레드 그리기 | `--t-5` |
| 지식 형성 | 트리 노드/엣지 성장 | `--t-4` |
| 완료 | 정지 + 봉인 배지 | `--t-3` |

<a id="motion-rules"></a>
### 10.2 하드 규칙 — 수치 포함

```text
지속시간
  버튼 피드백        100–160ms      버튼 누름 scale(0.97) @ 160ms
  툴팁 · 팝오버      125–200ms
  드롭다운           150–250ms
  모달 · 드로어      200–500ms      (드로어는 --e-drawer)
  UI 상태 전환 상한   300ms          → --t-1 ~ --t-4 만 사용

이징
  진입 · 퇴장        ease-out       --e-out  cubic-bezier(0.23, 1, 0.32, 1)
  화면 내 이동       ease-in-out    --e-inout
  호버 · 색상        ease
  등속               linear
  UI 에 ease-in 금지 — 사용자가 가장 주시하는 첫 순간을 지연시킨다

스프링 (쓰는 경우)  duration 0.5 / bounce 0.2   범위 0.1–0.3

등장               scale(0.9–0.97) + opacity.  scale(0) 금지
transform-origin   트리거에 고정. 팝오버에 center 금지
스태거             30–80ms. 스태거가 상호작용을 막지 않는다
속성               transform / opacity 만. transition: all 금지
방식               keyframes 보다 transition (중단 가능)
호버               @media (hover: hover) and (pointer: fine) 로 게이트
비대칭             퇴장이 진입보다 빠르다

빈도 규칙
  하루 100회 이상 쓰는 동작 → 애니메이션 없음
  키보드 개시 동작          → 절대 애니메이션 없음
```

**교정 순서** — `삭제 → 축소 → 이징 → 원점/물리 → 중단 가능 → GPU → 비대칭 타이밍 → 폴리시 → 접근성·일관성`. 태도는 **기본은 지적, 승인은 획득하는 것.**

<a id="motion-exception"></a>
### 10.3 300ms 예외

| 범주 | 상한 | 근거 |
| --- | --- | --- |
| 모든 UI 상태 전환 | **≤ 300ms** | `--t-1`~`--t-4` |
| 서사 전환 (스레드 그리기, 복구 비교) | ≤ 420ms (`--t-5`) | 정보 전달 목적. 사유를 컴포넌트 주석에 기재 |
| Hero one-shot (C안 선택 시만) | 5\.4초 1회 | UI 애니메이션이 아님. 입력을 막지 않고 언제든 중단 가능 |

<a id="motion-forbidden"></a>
### 10.4 금지

```text
무한 루프 · 무한 beam · 마퀴
무한 지속 패럴랙스              ← 현행 WebGL 씬이 위반 중. 즉시 제거
spring overshoot
전역 패럴랙스
완료된 결과에 shimmer
타이핑 시뮬레이션
모든 요소에 진입 애니메이션
스크롤 위치에 따라 화면을 가로지르는 이동
제품 앱 내부의 영구 애니메이션 (하나도 없다)
컬러 글로우 (§5.2 슬롭 디텍터 항목)
```

`prefers-reduced-motion`에서 **정보 손실 0** — 최종 상태를 즉시 표시한다. 감쇠이지 제거가 아니다(젠틀한 페이드는 유지).

<a id="motion-impl"></a>
### 10.5 구현 방식 [확정]

**JS 없는 모션을 기본으로 한다.** 2026년의 크래프트 신호다.

```text
진입          @starting-style + transition        JS 0
상태 전환      transition + @property (커스텀 속성 애니메이션)
스크롤 리빌    animation-timeline: view()          Chrome + Safari 26
              → Firefox 미지원. IntersectionObserver 폴백 필수
스레드 그리기  @property <length-percentage> + stroke-dashoffset transition
오버레이      popover + <dialog> + @starting-style  → JS 오버레이 라이브러리 불필요
```

`framer-motion` 등 애니메이션 라이브러리를 도입하지 않는다. 현행에도 없다([§16.1](#components)).

* * *

<a id="live-compile"></a>
## 11. Live Compile — 실시간 시각화

"문서가 어떻게 처리되는지 실시간으로"는 여기서 해결한다. 3D가 아니라 **durable event를 그대로 그리는 계기판**이다. Temporal · Prefect · GitHub Actions · Dagster · Airbyte · Vercel · Datadog의 실행 UI를 조사해 도출했다.

<a id="live-baseline"></a>
### 11.1 현행 기준선 — 데이터 계층은 이미 완성돼 있다

```text
있는 것
  SSE          @microsoft/fetch-event-source 2.0.1
               GET /v1/jobs/{id}/events · Last-Event-ID 재개 · 백오프 1s→30s + 지터
  이벤트 계약   durable event 25종 · schema_version "1.0" · sequence 양의 정수 zod 검증
  순서 보장     중복 제거(윈도 512) · 시퀀스 갭 버퍼링 · gap replay · 드레인
  이중화       10s 스냅샷 폴링 + 60s SSE 침묵 폴백
  진행률       8단계 가중 실측 weightedOverallProgress · ETA 없음
  SR 공지      4000ms 스로틀 + 5% 양자화
  setInterval  0건

없는 것 — 시각화 계층 전체
  처리 레인 구조 · 페이지 칩의 선 스타일 인코딩 · 분기 궤적 · 흉터 ·
  quarantine · 마일스톤 레일 · 2단 이벤트 배칭 · REPLAY 재생 컴포넌트

지금 금지 조항을 위반하는 것
  processing-workspace.tsx 데모 경로가 진행률 68% 를 하드코딩한다 (:147)
  단계 진행률 88/72/44/26/0 도 리터럴이다 (:39-43)
  → setInterval 은 아니지만 "가짜 진행률" 조항에 정확히 걸린다. 즉시 수정.
```

<a id="live-rules"></a>
### 11.2 설계 규칙 8가지

**R1 · 안정된 정체성, 추가형 시도 기록** — 한 페이지는 영원히 하나의 칩이다. 재시도는 **attempt 레코드를 추가**할 뿐 새 칩을 만들지 않는다. 재시도된 칩에는 `2/2` 배지가 붙는다. *(`PageSummary.attempt`에 `number`·`status`·`route`·`escalation`이 이미 있고 UI는 `quality`만 읽는다 — 백엔드 변경 없이 구현 가능하다.)*

**R2 · 상태를 두 번 인코딩한다** — 색만으로 표현하지 않는다.

```text
solid    실행 중
dashed   재시도 중          ← 색이 아니라 선 스타일이 재시도를 말한다
dotted   대기
hatched  복구 후 검증됨
```

WCAG 1.4.1(색에만 의존 금지)도 동시에 만족한다.

**R3 · 복구된 단위는 흉터를 남긴다**

최종 상태가 초록이어도 "recovered" 표식과 시도 횟수가 남는다. 런 요약은 항상 이렇게 읽힌다.

```text
420 verified  (1 after recovery)   ·  1 unresolved
```

빨강이 아무 흔적 없이 초록으로 바뀌는 것은 **금지**다. **이것이 [§2.2](#white-space)의 세 빈 공간 중 유일한 순수 공백이며, 이 제품의 신뢰 서사다.**

**R4 · 실패는 모달도 토스트도 아니다** — 실패는 자기 레인 자리에 **고정**되고, Inspector를 한 번 자동으로 열고, 마일스톤 레일에 남는다. 토스트는 사라진다. finding은 사라지면 안 된다.

**R5 · 진행률은 세는 것이지 추정하는 것이 아니다**

```text
184 of 421 pages · lane PRECISION 41 of 44
```

분모를 모르면 단조 증가 카운트 + 단계명만 표시한다. **퍼센트도 ETA도 만들어내지 않는다.**

**R6 · 2단 이벤트 처리** — 마일스톤(단계 시작, finding, 복구, 검증)은 즉시 스트리밍. 나머지는 초당 2건 이하로 배칭·집계한다(`×37 pages classified`). 사용자가 스크롤하면 자동 스크롤이 멈추고 `N new` 점프 알약이 뜬다.

**R7 · 범위 복구는 범위가 보여야 한다** — 실패한 페이지에서 **분기선을 그려** Recovery 레인으로 내려갔다가 원래 레인으로 돌아온다. 런 전체가 재시작된 것처럼 보이면 실패다.

**R8 · 모션은 선택, 상태는 필수** — 모든 펄스·시머는 `prefers-reduced-motion: no-preference` 뒤에. `role="status"` polite 영역은 **마일스톤만** 알린다. 모든 레인·칩은 키보드 접근 가능하고 텍스트 상태 라벨을 갖는다.

<a id="live-layout"></a>
### 11.3 레이아웃

```text
┌ 런 헤더 44px  ● LIVE · COLLECTION 8F3A · 184 of 421 pages · t+07.4s ┐
│              현재 단계 한 문장(평문)                                  │
├────────────┬───────────────────────────────────────────────────────┤
│ NATIVE     │ ← 페이지 칩이 좌→우로 흐름                             │
│ cpu        │   in-flight 3 · done 41 · flagged 0 · retried 0        │
├────────────┼───────────────────────────────────────────────────────┤
│ FAST       │ ▣ ▣ ▣ ▣ ▣                                            │
├────────────┼───────────────────────────────────────────────────────┤
│ PRECISION  │ ▣ ▣ ▤ ▣          ← ▤ = dashed = 재시도 중              │
├────────────┼───────────────────────────────────────────────────────┤
│ RECOVERY   │      ╰──▶ ▤ ──▶ ▣✓   ← 분기해 내려갔다 돌아오는 궤적    │
├────────────┴──────────────────────┬────────────────────────────────┤
│ MILESTONES (평문 + mono 이벤트명)   │ 카운터 4종 + Finding Inspector │
└───────────────────────────────────┴────────────────────────────────┘
```

**레인 이름을 API에 맞춘다.** 현행 `route_label`은 `Native | OCR | Fast | Precision | Fallback` 5종이고 `RECOVERY` 값이 없다. 레인은 **표시 개념**으로 두고 `Recovery`는 attempt 번호 ≥2에서 파생한다 — 백엔드 계약 변경 없이 가능하다.

<a id="inspector"></a>
### 11.4 Finding Inspector

우측 340px. finding이 생기면 자동으로 열린다.

```text
탭 3개
  Finding      검증이 무엇을 잡았는가 + 페이지 썸네일 + expected vs extracted
  Attempts     Attempt 1 접힘 / Attempt 2 펼침 (실패한 것만 자동 펼침)
  Verification 최종적으로 무엇이 통과시켰는가
```

```text
Table 14 may be incomplete
Expected rows   62
Extracted rows  56
Affected area   lower region · p.47

Attempt 1 · Expanded crop     60/62    Rejected
Attempt 2 · Overlap tiles     62/62    Candidate
  Row count        Pass
  Numeric facts    Pass
  Source coverage  Pass
Final                                  Accepted (recovered)
```

- 실패를 붉은 경고로 과장하지 않는다. `--review-d` 앰버 + 침착한 문장.
- unresolved는 **채우지 않고** unresolved로 남긴다.
- **대기·재시도 상태를 별도 패널로 유배 보내지 않는다.** 그것이 속한 단위에 붙여서 렌더한다.

**현행 `ReviewDrawer` 위에 얹는다. 버리지 않는다.** 이미 있는 것 — 우측 `aside role="dialog" aria-modal` + 포커스 트랩, severity 정렬, category 라벨 4종, A/B 후보 비교 그리드, 문서 전역 규칙 + 해시 바인딩 확인 시트, 액션 5종. 없는 것 — 3탭 구조, attempt 이력 렌더, expected vs extracted, validator 체크리스트, 페이지 썸네일 인라인, 자동 열림, `Accepted (recovered)` 표기.

<a id="milestones"></a>
### 11.5 마일스톤 문장 규칙

평문과 mono 이벤트명을 **같은 행**에 병기한다. 왼쪽은 고객용, 오른쪽은 개발자용.

```text
t+3.2s  ●  검증 미통과 — 영역 격리                      verification.failed
t+3.8s  ●  복구 범위 계산 · 하단 영역                     recovery.planned
t+5.2s  ●  복구 후보 생성 · 62 / 62 rows                candidate.generated
t+6.3s  ●  검증됨 · 수용 · p.047                        candidate.accepted
```

원시 이벤트 전체는 `모든 이벤트 보기` 토글 뒤에 둔다.

<a id="same-component"></a>
### 11.6 마케팅과 제품이 같은 컴포넌트를 쓴다

|  | 데이터 원천 | 표시 |
| --- | --- | --- |
| 홈 ACT 2 | 녹화된 durable event log 재생 | 상태바에 `REPLAY · 시간 압축 6×` 명시 |
| 제품 앱 | SSE 실시간 | `● LIVE` |

**컴포넌트는 하나다.** `setInterval` 시뮬레이션이나 **진행률 리터럴**이 코드에 존재하면 실패로 간주한다. 동결 event log는 [§15.2](#plates)의 fixture로 관리한다.

<a id="live-perf"></a>
### 11.7 성능·접근성 계약

```text
이벤트 → UI 반영 배치 100ms (≤10Hz)
동시 애니메이션 요소 ≤ 24
페이지 칩 가상화 (표시 ≤ 40, 나머지 집계) — react-virtuoso
마일스톤 최대 7행
scene model 은 sequence 로 memoize
상태는 색 + 형태 + 텍스트 3중
reduced-motion: 칩이 이동하지 않고 최종 위치에 즉시 표시, 정보 손실 0
```

<a id="live-forbidden"></a>
### 11.8 이 화면의 금지

```text
DAG 를 주 실시간 뷰로 사용
원시 로그 테일을 주인공으로
추정 기반 퍼센트 바
진행률 리터럴 (예: 68%)
실패한 칩을 흔적 없이 초록으로 변경
레인과 분리된 별도 "에러" 패널
10초 초과 작업에 스피너
가짜 진행률 · 뒤로 가는 진행률 · 100% 근처에서 멈춘 바
```

<a id="part-4"></a>
# PART IV · 화면 설계

<a id="home"></a>
## 12. 홈페이지 — 6막

```text
ACT 0   Navigation                     PAPER        72px
ACT 1   Hero — 대응면 + 어포던스         PAPER        88vh
ACT 2   The Compiler Running           INSTRUMENT   전폭 76vh   ← 시그니처
ACT 3   Return to Source               PAPER        자동
ACT 4   The Knowledge It Leaves        INSTRUMENT   전폭 68vh
ACT 5   Trust, Measured                PAPER        자동
ACT 6   Close                          PAPER        56vh
Footer                                 PAPER
```

**현행 11개 섹션 → 6막 매핑**

```text
현행 marketing-landing.tsx                        6막
  1  st-home-hero        H1 + 카피 + 3D 씬        → ACT 1 (형태 교체: 대응면 + 드롭존)
  2  st-problem          Powerful models…         → 삭제 (ACT 1 카피로 흡수)
  3  st-transformation   4챕터 01–04 · 다크 밴드   → ACT 2 로 대체 (Live Compile)
  4  st-demo-section     StructaraProofDemo       → ACT 3 (실제 워크벤치로 교체)
  5  st-pillars          4카드                     → 삭제
  6  st-public-proof     DART / SEC 2카드          → ACT 3 하단 mono 바로 흡수
  7  st-benchmark        metric 그리드 4행         → /benchmarks 로 이동
  8  st-use-cases        4카드 01–04               → 삭제
  9  st-security-band    policy orbit             → ACT 5 로 재구성
 10  st-manifesto        4문장                     → ACT 6 카피로 흡수
 11  st-home-final       CTA                      → ACT 6
     st-footer (shell)                            → Footer 유지
```

**삭제** — 벤치마크 수치 그리드(→ `/benchmarks`), `01`–`04` 번호 라벨, 4등분 카드 3세트, `st-problem`의 빈 `<i>` mock, 반복 CTA(`Build your knowledge` 4회 → 2회).

**섹션 수를 크래프트 지표로 쓰지 않는다.** 실측하면 Vercel 5 · Stripe 6 · Databricks 6 · Linear ~10 · Cursor ~17 · Resend 13이다. 상관관계가 없다. 6막은 **서사 구조**의 결정이지 개수 최적화가 아니다.

<a id="act0"></a>
### 12.1 ACT 0 — Navigation

```text
높이       72px (스크롤 후 60px)
배경       Hero 상단 투명 → 스크롤 8px 후 --paper-0 96% + blur 8px + 하단 알파 헤어라인
좌         심볼 20px + 워드마크 15px + │ + "The Knowledge Compiler" 12px mono
중앙       Product   Solutions   Proof   Research      (15px, 간격 32px)
우         Sign in(텍스트 링크) · [Start compiling](36px, --brand)
```

- 상단 링크 **4개**. Security · Pricing · Developers는 메가 패널 안으로.
- 채워진 버튼은 **정확히 1개**. 보조 인증은 텍스트 링크.
- **메가 패널 ≤ 12 링크, 펼침 총합 ≤ 25.**

**규칙을 정정한다.** v2는 "상단 ≤6"을 판별식으로 삼았으나 실측하면 Vercel 4 · Stripe 5 · Linear 6 · Databricks 6으로 **전원 통과**한다. 차이는 펼쳤을 때다 — Databricks **117개**, Retool 38개. **판별식은 상단 개수가 아니라 펼침 깊이다.**

**현행과의 차이** — 지금은 상단 6개(`Product · Solutions · Demo · Research · Security · Pricing`), 헤더 높이 68px, 스크롤 임계 24px, 드롭다운이 360px 1컬럼이고 **제품 픽셀이 0장**이다. KO/EN 토글은 없다.

**Product 메가 패널 — 대응면 형태 유지**

```text
720 × 320, 좌 4 : 우 8
좌 240px   Convert / Verify / Knowledge / Graph / Connect + 각 한 줄 가치 문장
우 480px   호버 중인 항목의 실제 제품 캡처 crop (16:10, --r-media)
           하단 mono 캡션: 실제 라우트 경로
```

우측 crop은 이미 있는 `public/product/{processing,review,knowledge,graph,exports}.webp`를 [§15.2](#plates)로 재생성해 쓴다.

**eyebrow 사양 변경 [확정]** — "대문자 라벨 + 장식 점 + 뒤따르는 규칙선"은 슬롭 디텍터 항목이다([§5.2](#material-risk)). 점과 규칙선을 빼고 **대문자 mono 라벨 단독** 또는 **라벨 + 좌측 8px 원문 마커**([§4.3](#fractal)의 행 스케일과 같은 형태)로 바꾼다.

**KO/EN 토글은 G-D 결정 전까지 만들지 않는다.** 동작하지 않는 토글은 [§14.3](#affordance) 위반이다.

**모바일 390** — 전체 화면 시트, 제품 여정 순서, primary CTA 하단 고정, 배경 스크롤 잠금, **닫을 때 포커스 복귀**, 타깃 44px. 현행 시트는 스크롤 잠금만 있고 포커스 복귀·트랩이 없다. 그리고 모바일에만 `Workspace → /app/home`이 있어 데스크톱과 항목이 다르다 — 통일한다.

<a id="act1"></a>
### 12.2 ACT 1 — Hero

**[권장 · G-C A안] Hero가 동작한다.** 상위 3곳 중 2곳의 Hero는 이미지가 아니라 어포던스다 — Vercel `Drop to deploy`, Cursor 대화형 데모, Retool 프롬프트→대시보드. 그리고 이것이 [§2.2](#white-space)의 첫 번째 빈 공간을 첫 화면에서 점유하는 유일한 방법이다.

```text
┌ margin 72 ┬──── 5col (500px) ────┬ 40 ┬───── 7col (700px) ─────┬ 72 ┐
│           │  eyebrow (mono 12)   │    │  ╔═══════════════════╗ │    │
│           │  H1  Display 1 · 2행  │    │  ║ 메타바 28px       ║ │    │
│           │  (수동 개행)          │    │  ╟─────────┬─────────╢ │    │
│           │  Lead 20/32 · 2행     │    │  ║ SOURCE  │ RESULT  ║ │    │
│           │  [CTA] [CTA]         │    │  ║ 실제    │ 검증된   ║ │    │
│           │  ─ trust strip ─     │    │  ║ 페이지  ●─┼─▶ 표    ║ │    │
│           │                      │    │  ╚═════════╧═════════╝ │    │
│           │                      │    │  드롭 존 + mono 캡션    │    │
└───────────┴──────────────────────┴────┴────────────────────────┴────┘
```

**세 상태를 갖는다.**

```text
① 기본     공개 필기(10-K p.31)가 이미 컴파일된 상태로 놓여 있다.
           좌 = 실제 PDF 렌더, 우 = 실제 제품 표 컴포넌트, 스레드 활성.
           LCP 는 좌측 포스터 이미지다. JS 로 그리지 않는다.
② 호버/포커스  액자 전체가 드롭 타깃임을 알린다.
           "당신의 문서로 해보세요 — 여기에 놓으세요"  (알파 헤어라인 강조 + 커서)
③ 드롭 후   실제 컴파일이 시작되고 좌측이 사용자 문서로 교체된다.
           ACT 2 의 Live Compile 이 그대로 인라인으로 열린다.
           실패·보류가 나오면 그대로 보여준다 — 숨기지 않는 것이 이 화면의 논지다.
```

- 액자: `--paper-0`, 알파 헤어라인, `--r-media`, **장식 그림자 없음**.
- 메타바: `AAPL · FORM 10-K · FY2025 · PAGE 31` ····· `VERIFIED`
- 스레드: 원문 셀 bbox → 결과 행. `--evidence` 1.25px, 끝점 3px 원. **좌표에서 계산된다.**

**trust strip** (mono 12px, `--ink-3`)

```text
SOURCE-LINKED OUTPUT · KO DART / US SEC · NO UNVERIFIED CLAIMS
```

**Hero 금지** — 수치 배지, 고객 로고, 별점, "AI 기반" 류 수식어, CTA 3개, 카드(OpenAI frontend-skill: `Never use cards in the hero`).

**모션 (①→② 상태 전환 중심, 자동재생 최소)**

| 구간 | 동작 |
| --- | --- |
| 0\.0–0.4 | 액자 페이드인 + 원문면 (`@starting-style`) |
| 0\.4–1.2 | 원문 위 블록 bbox 3개 순차 페이드 (각 120ms) |
| 1\.2–2.0 | 결과면 24px slide-in, 행 6개 순차 (스태거 60ms) |
| 2\.0–2.9 | 스레드 `stroke-dashoffset` 900ms, 도착 시 셀 하이라이트 |
| 2\.9–3.6 | `VERIFIED` 배지, 정지 |

루프 없음. replay 글리프 제공. reduced-motion은 최종 프레임 정적. 390에서는 세로 스택 + 수직 스레드, 모션 2단계로 축약.

**3안 비교 의무** — 컨셉(대응면)은 고정, 변주만 비교.

| 방향 | 변주 |
| --- | --- |
| A · Frame | 하나의 액자 안 좌우 대응 **(권장)** |
| B · Overlap | 원문면 위에 결과면이 12% 겹쳐 떠 있음 |
| C · Full-bleed verso | 원문면이 화면 우측 끝까지 잘려 나가고 결과면이 그 위에 |

<a id="act2"></a>
### 12.3 ACT 2 — The Compiler Running

[§11](#live-compile)의 Live Compile을 그대로 배치한다. 전폭 76vh, `--inst-0`, 상하 evidence 1px.

```text
오버레이 H2 (좌상단, Title 2, 3초 후 페이드아웃)
  문서가 지식이 되는 과정을 숨기지 않습니다.
```

번호 라벨 없음. 섹션 제목도 없다. 데이터 원천은 동결 event log 재생이며 상태바에 `REPLAY · 시간 압축 6×`를 명시한다. **사용자가 ACT 1에서 문서를 드롭했다면 이 자리가 `● LIVE`로 바뀐다.**

<a id="act3"></a>
### 12.4 ACT 3 — Return to Source

```text
좌측 문단 (5col, readable 680max)
  Title 1   중요한 결과는 언제든 정확한 원문으로 돌아갑니다.
  Body      두 문장. 그 이상 금지.
  링크      전체 Proof 열기 →

전폭 워크벤치 (max 1320 · 620px · --paper-0 · 알파 헤어라인)
┌ 페이지 레일 96 ┬ 실제 PDF 캔버스 (7col) ┬ 결과 인스펙터 (5col) ┐
│ 썸네일 세로   │ PDF.js 실제 렌더        │ [Markdown][Table]    │
│              │ bbox 오버레이           │ [Note][Graph][Receipt]│
│              │ 확대(고배율 재렌더)      │ 선택 행 하이라이트     │
└──────────────┴────────────────────────┴──────────────────────┘
하단 mono 바   KO 기본 DART · EN 기본 SEC · [Korea·DART][U.S.·SEC] 상시 노출
```

- 결과 행 호버 → 좌측 bbox 활성 + 스레드. 반대 방향도 동작.
- 키보드: `↑↓` 결과 이동, `Enter` 고정, `Esc` 해제. 드래그 대체 수단 필수.
- **DOM으로 재작성한 표를 원문으로 표시하는 것은 즉시 리젝트 사유.** 현행 데모 `SamplePaper`가 손으로 쓴 `<table>`을 `Original` 헤더 아래 렌더한다 — 위반 상태다.
- 확대는 CSS `scale`이 아니라 **해당 영역 고배율 재렌더**다. 렌더된 픽셀을 확대하면 흐려진다.

<a id="act4"></a>
### 12.5 ACT 4 — The Knowledge It Leaves

```text
전폭 · 68vh · --inst-0
좌 4col   File Tree (Sources/Notes/Entities/Relations/MOCs/Exports)
중 5col   선택된 Atomic Note (실제 마크다운 렌더, 상단 출처 칩)
우 3col   Local Graph (20–40 노드) + 하단 Package Manifest
```

- 세 패널의 **선택 상태 동기화** — 노트를 고르면 트리가 스크롤되고 그래프 노드가 강조된다.
- 그래프 엣지는 −34° 계열만. 곡선 남발 금지. **근거 없는 엣지 표시 금지.**
- 그래프 대체 수단으로 entity/relation 표 **항상 제공**.
- 4등분 카드 배치 금지.

<a id="act5"></a>
### 12.6 ACT 5 — Trust, Measured

```text
좌 6col   Title 1  검증되지 않은 것은 결과에 넣지 않습니다.
          원칙 3줄 (규칙선 구분, 카드 아님)
            안전한 곳에서는 빠르게
            필요한 곳에서는 정밀하게
            근거 없이는 아무것도 수용하지 않습니다
          링크  측정 방법론 →   보안 아키텍처 →

우 6col   Trust Boundary 다이어그램 (단일 SVG)
          Browser → Quarantine → Verified Source →
          Isolated Worker → Derived Knowledge → Purge
          6박스 나열 금지 — 하나의 연속된 경로, 경계는 점선,
          정책 레일은 우측 세로 라벨
```

각 노드 하단에 mono 10px로 `Designed / Repository-tested / Deployed / Independently assessed` 중 정확한 상태. 미달성을 숨기지 않는다.

<a id="act6"></a>
### 12.7 ACT 6 — Close

```text
높이 56vh · --paper-1 · 좌측 정렬 (에디토리얼, 중앙 정렬 아님)
Display 2   당신의 문서에는 이미 AI가 필요로 하는 것이 들어 있습니다.
            우리는 그것을 쓸 수 있게 만듭니다.
CTA         [Start compiling]   Talk to sales →
배경        우측 하단에 심볼 320px, --paper-2 단색(질감)
```

이 페이지의 primary CTA는 여기가 마지막이다.

* * *

<a id="public-routes"></a>
## 13. 공개 라우트 — 템플릿 3종

라우트를 개별 디자인하지 않는다. 공개 라우트는 `structara-content.ts`의 `PUBLIC_PAGES` **34개**가 전부다.

**T1 · Proof Route** — `/product/convert` `/product/verify` `/demo/dart` `/demo/sec` `/demo/research-paper` `/demo/course-material`

```text
Hero-lite(PAPER 48vh) → 전폭 워크벤치(실제 데이터)
→ 설명 3블록(규칙선 구분, 카드 아님) → 관련 라우트 2개 → CTA
```

**T2 · Instrument Route** — `/product` `/product/knowledge` `/product/graph` `/product/connect` `/demo`

```text
Hero-lite(PAPER 40vh) → INSTRUMENT 전폭 실연(72vh)
→ 기능 3항목(좌 라벨 / 우 실제 crop = 대응면 반복) → CTA
```

**T3 · Editorial Route** — 나머지 23개 (`/solutions/*` `/benchmarks` `/research` `/security` `/pricing` `/customers` `/developers/*` `/company/*` `/legal/*`)

```text
좌 200px 목차(sticky) │ 본문 680max │ 우 240px 메타·상태
표와 수치는 여기에만 존재한다.
```

**공통 완료 조건** — 고유 H1 · 고유 첫 문장(홈 복제 금지) · 실제 증거 1개 이상 · 1440/390 스크린샷 · metadata/canonical/OG · **JSON-LD**([§19](#ai-readable)) · 죽은 CTA 0.

`hreflang`과 KO 스크린샷은 G-D 결정 후에 조건에 추가한다.

**이미 되어 있는 것 — 다시 만들지 않는다**

```text
generateMetadata (title/description/canonical/openGraph)   [...slug]/page.tsx:9-23
sitemap.ts        / + PUBLIC_PAGES 34개 = 35 URL
robots.ts         /app/ /documents/ /login /signup /onboarding /forgot-password /sso 차단
opengraph-image.tsx  next/og 런타임 생성 1200×630   → plate-og-* 를 따로 만들지 않는다
```

`sitemap.ts`의 `priority`가 `/benchmarks`에 `0.7`을 주는데 T3 핵심 증거 라우트이므로 상향한다.

* * *

<a id="product-app"></a>
## 14. 제품 앱 UI (INSTRUMENT)

<a id="shell"></a>
### 14.1 앱 셸

```text
Sidebar    240px (접힘 64px)   --inst-1, 우측 --rule-inst-1
Topbar     48px                --inst-0, 하단 --rule-inst-1
Context    48px                프로젝트/컬렉션 + 상태 + 액션
Workbench  나머지
```

**수치를 코드에 맞춰 정정했다.** 현행은 그리드 트랙 `--sidebar-width: 256px`인데 그 안의 `<aside>`가 240px이라 **불일치가 이미 있다** — 240px 한 값으로 통일한다. 접힘은 **64px 유지**(v2의 56px 폐기 — 아이콘 24px + 좌우 20px이 4px 배수로 떨어진다). Context bar는 새로 만들지 않고 **기존 `st-app-context`(현재 min-height 126px)를 48px로 축소**한다.

- 활성 표시: 좌측 2px `--brand-d` 마커 + 배경 `--inst-2`. **알약 배경 금지.** *(현행이 이미 `box-shadow: inset 2px 0`로 맞다. 색과 면만 바꾼다. 단 같은 선택자가 네 파일에서 경쟁 중이므로 W7에서 하나로 접는다.)*
- 플로팅 글래스 카드 금지. 패널 경계는 알파 헤어라인.
- Command Palette(`⌘K`) 필수. **현행은 열리지만 입력창이 동작하지 않는다** — 검색을 구현하거나 입력창을 제거한다([§14.3](#affordance)).
- 밀도 3종: Comfortable(행 40px) / Compact(32px) / Presentation(48px). 현행 0건 — 신규.

<a id="screen-contracts"></a>
### 14.2 화면별 계약

| 화면 | 라우트 · 컴포넌트 | 반드시 보여야 하는 것 | 절대 금지 |
| --- | --- | --- | --- |
| **Intake** | `/quick-convert` · `upload-panel.tsx` | 폴더 드롭 → manifest → hash/dedupe → preflight 견적(P50/P95/상한) → 승인 시트 | 파일 1개씩 업로드 후 대기, 가짜 % |
| **Processing Studio** | `/workspace`, `/documents/[id]/processing` | [§11](#live-compile) 전체 | setInterval, 진행률 리터럴, 타이핑 시뮬레이션 |
| **Proof Workbench** | `/documents/[id]/sources` · `source-viewer.tsx` | 실제 PDF, 정규화 bbox, Markdown/Table/Note/Graph/Receipt | DOM 재작성 표를 원문으로 |
| **Knowledge Studio** | `/knowledge-bases` · `knowledge-studio.tsx` | Tree·Note·Graph 동기화, 모든 노트에 출처 칩 | 근거 없는 관계 엣지 |
| **Review Studio** | `/review` · `review-studio.tsx` + `review-drawer.tsx` | 원문 crop 우선, 후보 A/B, validator 체크리스트, 과금 영향 | 사람 검수를 필수 단계처럼 표현 |
| **Exports** | `export-dialog.tsx` 모달 · `/app/exports` | 패키지별 validation 상태·해시·import 검증 결과 | 미검증 패키지를 동일 시각 취급 |
| **Usage/Billing** | `/usage`, `/app/usage` · `billing-management.tsx` | reserved/used/refunded, 실패·unresolved 미과금 명시 | 임의 요금제 발명 |

*v2의 "Integrity Console"이라는 화면은 존재하지 않는다 — `/review`의 Review Studio다.*

**현행 격차**

```text
Intake              폴더 업로드(webkitdirectory) 0건 · manifest/hash/dedupe UI 0건
                    preflight 견적과 승인 게이트는 있다 ✓
Processing Studio   §11.1 참조
Proof Workbench     §14.4 참조. PDF.js 없음. 데모가 <table> 을 "Original" 로 표시 중
Knowledge Studio    3패널 동기화 0건 · 그래프는 하드코딩 직선 SVG · entity/relation 표 0건
Review Studio       A/B 후보 · validator · 문서 전역 규칙 · 해시 확인 상당 부분 구현 ✓
                    과금 영향 표시 0건
Exports             unresolved_conflict_count 필드는 있으나 렌더 0건
Usage/Billing       실패·unresolved 미과금 명시 0건
```

<a id="affordance"></a>
### 14.3 Affordance 무결성

상호작용 가능해 보이는 모든 요소는 다음 중 하나여야 한다.

1. 실제로 동작한다
2. `disabled` + 비활성 사유 + 사용 가능 시점
3. 버튼 시맨틱 없는 순수 라벨
4. 제거한다

"나중에 연결할 버튼"은 존재할 수 없다.

**검사기는 이미 있다. 범위를 넓힌다.** `scripts/verify-button-contracts.mjs`가 `pnpm interactions:check`로 돈다.

```text
현재 검사    <button> 중 disabled 아닌 것이
             onClick / type="submit" / formAction / 스프레드 중 하나를 갖는가

추가할 것    preventDefault 만 하는 핸들러
             빈 콜백 () => {}
             404 타깃 (href 가 PUBLIC_PAGES 34개 + src/app 라우트 트리에 실재하는가)
             포커스만 되는 요소 (tabIndex 만 있고 동작 없음)
             <a> · role="button" 요소        ← 현재 tagName === "button" 만 검사
             비활성 사유·사용 가능 시점 문구 유무
```

**현재 알려진 위반** — Command Palette 입력창이 `value`/`onChange` 없이 렌더된다. `<input>`이라 지금 검사기에 안 걸린다.

<a id="coord"></a>
### 14.4 Proof 좌표 계약 [게이트 G-E 종속]

```text
raw bbox
→ source 좌표계
→ CropBox / MediaBox 보정
→ rotation 정규화 (0/90/180/270)
→ [0,1] 정규화 저장
→ PDF.js viewport 변환
→ DPR 독립 오버레이
```

골든 테스트 20건, **IoU ≥ 0.95.** 케이스: portrait / 90 / 180 / 270 / CropBox / DPR 1·2 / zoom 50·100·200 / resize / 가상화 재활용 / 병합 셀 / multi-bbox / 버전 불일치(stale 표시 후 자동 투영 금지).

**현행은 7단계 중 1단계만 있다.**

```text
raw bbox              서버가 bbox1000(0–1000 정수)로 이미 정규화해 전달
source 좌표계          없음 — 클라이언트는 원본 좌표계를 모른다
CropBox / MediaBox     없음 — 해당 문자열 0건
rotation 정규화        없음 — 회전은 UI 의 CSS transform 일 뿐. bbox.ts 에 회전 항 없음
                      SourceRef 에 rotation 필드도 없다        ← G-E 대상
[0,1] 정규화           bbox1000ToUnit / unitToBbox1000 존재. 다만 렌더러는 안 쓴다
PDF.js viewport        PDF.js 자체가 없다. 원문은 thumbnail_url 이미지 1장
DPR 독립               없음 — devicePixelRatio 참조 0건

bbox.ts 전체 55줄. 실제 투영은 bbox1000 / 10 → CSS % 가 전부다.
bbox.test.ts 는 2건 (왕복 1 + 역전 거부 1). IoU 테스트 0건.
```

**W4 실질 작업**

```text
1. pdfjs-dist 도입 + dynamic import + 워커 번들링
2. SourceRef 에 page rotation / cropbox 원본 메타 추가        ← G-E. 백엔드 합의 필요
3. bbox.ts → lib/facing/normalize.ts 확장: rotation · cropbox · DPR
4. lib/facing/thread.ts 신설: bbox → SVG path
   (현행 "스레드"는 구현이 아니라 CSS 로 고정된 1px 가로 div 다)
5. 골든 픽스처 20건 + IoU 어서션
```

**2번이 승인되지 않으면** 회전·CropBox 문서에서 스레드가 어긋난다. 그 경우 [§4.4](#form-forbidden)에 따라 해당 문서는 `threads=[]`로 두고 좌표 없는 선을 그리지 않는다 — 화면이 비는 것이 틀린 선을 그리는 것보다 낫다.

<a id="part-5"></a>
# PART V · 재료 · 컴포넌트 · 플랫폼

<a id="assets"></a>
## 15. 에셋

<a id="asset-problem"></a>
### 15.1 문제와 해결

기존 정책(free-asset-first + AI 생성 금지 + 임의 도형 금지 + custom 승인 필수)은 **올바르지만 대안을 주지 않았다.** 그래서 시각 재료가 고갈됐다.

**[확정] 모든 마케팅 시각물을 실제 제품 컴포넌트에서 결정론적으로 생성한다.** 스톡도 AI 이미지도 필요 없어진다.

<a id="plates"></a>
### 15.2 Plate Pipeline — 신설이 아니라 확장이다

동등한 파이프라인이 **이미 다른 경로에 있다.** 새 디렉터리를 만들면 중복 파이프라인 2개가 생긴다.

```text
현행
  apps/web/scripts/capture-product-assets.mjs   Playwright → 제품 라우트 14개
                                                → assets/product/screenshots/en/{1440x900,390x844}
                                                파일명 STR-PRODUCT-T0-<NAME>-EN-1440x900-v01.webp
                                                + hashes.sha256 + capture-manifest.json
  apps/web/scripts/capture-product-loops.mjs    → assets/product/recordings (WebM + MP4)
  apps/web/scripts/capture-dart-proof-assets.mjs → assets/public-proof/dart
```

**확장 명세**

```text
apps/web/scripts/           ← 기존 위치 유지. tools/plates/ 를 새로 만들지 않는다
  plates.config.ts          신규 — 플레이트 정의(라우트, 뷰포트, 상태, 셀렉터, fixture)
  capture-plates.mjs        신규 — 기존 capture-*.mjs 3개를 이 설정 위로 통합
apps/web/tools/plates/fixtures/   신규 — 동결 공개 원문(10-K, DART) + 동결 event log
assets/product/plates/      신규 출력. 기존 screenshots/recordings 는 유지 후 이관
```

**규칙**

- 캡처 대상은 **production과 동일한 컴포넌트**다. 별도 목업 금지. *(현행 스크립트가 이미 실제 라우트를 연다.)*
- **fixture 해시를 파일명에 넣는다** — `plate-<id>-<fixtureHash>@2x.avif`. 매니페스트에만 두면 stale 감지가 사람 눈에 안 보인다.
- 1440×900 @2x **AVIF**. 현행 WebP는 히어로 에셋(AVIF)과 포맷이 갈려 있다 — AVIF로 통일한다. 동영상은 WebM(VP9) ≤900KB, 무음.
- CI가 재생성 후 diff → 시각 회귀 감지. *(현행은 수동 실행.)*
- **동결 event log를 fixture로 추가한다** — [§12.3](#act2) 재생의 데이터 원천이며 현재 없다.

**필수 플레이트 P0**

```text
plate-hero-source        Hero 원문면 (10-K p.31)
plate-hero-result        Hero 결과면
plate-theater-*          ACT 2 프레임 시퀀스 / WebM
plate-proof-*            ACT 3 워크벤치 상태 4종
plate-knowledge-*        ACT 4 트리 / 노트 / 그래프
plate-nav-product-*      메가 패널 crop 5종
```

`plate-og-*`는 만들지 않는다 — `opengraph-image.tsx`가 런타임 생성하며 캐시·배포 면에서 유리하다. `public/hero/*-OG-*` 정적 파일은 이미 미참조다.

<a id="texture"></a>
### 15.3 질감과 표면 재료

```text
그레인      CSS 노이즈 (SVG feTurbulence 또는 반복 그라디언트). 외부 텍스처 파일 불필요
            §5.2 대응 — 종이처럼 거동해야 한다: 명도에 따라 강도가 변하고,
            확대해도 픽셀 격자가 드러나지 않으며, INSTRUMENT 면에서는 사라진다
다이어그램   손으로 그린 SVG. 토큰 색만. --34° 각도 계열만
로고·글리프   자체 벡터 마스터. AI 생성물 최종 사용 금지
3D          G-C 결정에 종속 (§9.2)
```

<a id="photo"></a>
### 15.4 사진 정책 [게이트 부수]

v2는 "사진 0장"이었다. **최상위 관행과 반대다.**

```text
stripe.com     커미션 사진 4장 — 자사 평행사변형을 실제 세계 기하에서 발견시킨다
               (교차로 항공샷 · 매장 · 현관 · 신문 키오스크)
anthropic.com  다큐멘터리 사진을 아이덴티티 프로그램에 포함
cursor.com     실제 팀 사진
```

현재의 수는 "사진 없음"이 아니라 \*\*"스톡이 아닌, 특정한, 커미션 사진"\*\*이다. 사진이 하나도 없으면 **회사가 실재한다는 신호를 만들 수단이 없다.**

**[권장] 한 곳만 예외를 연다.** `/company/about` 또는 Footer 상단에 커미션 사진 1–3장. 스톡·AI 생성은 계속 금지. 마케팅 홈과 제품 라우트에는 여전히 사진 0장.

<a id="dead-assets"></a>
### 15.5 미참조 자산 정리

```text
public/hero/            24개 중 20개 미참조
                        CONCEPT-A/B/C 6 · REDUCED 2 · OG 2 · OBJECT-* 6
                        MULTI-LOOP mp4/webm 2 · TABLET/MOBILE webp 2
assets/3d/derivatives/  전량 미참조 — hero-master.glb 456KB · hero-master-low.glb 282KB
                        hero-composition-a/b/c.png (시안 3안) · hero-poster 5.1MB
                        hero-loop-12s.mp4 · hero-object-*.png 3장
```

**G-C 결정 전에 삭제하지 않는다.** B안을 택하면 `hero-master.glb`와 시안 3안이 그대로 재사용 대상이다. A안 확정 후 W9 삭제 원장에 올린다.

* * *

<a id="components"></a>
## 16. 컴포넌트 소스

<a id="comp-baseline"></a>
### 16.1 현재 상태 — 외부 UI 컴포넌트가 0개다

```text
components.json          없음
shadcn / Radix           미설치
tailwindcss              미설치 · @tailwind / @apply 0건
postcss / autoprefixer   미설치
현행 UI                  손으로 쓴 순수 CSS 16,048줄 (5개 파일)
                         + CSS Module 1개 + clsx 2.1.1
설치된 UI 계열 의존성      @phosphor-icons/react 2.1.10
                         react-virtuoso 4.18.11
                         @uiw/react-codemirror 4.25.11  (정적 import — 분리 필요)
                         three / @react-three/fiber / @react-three/drei
애니메이션 라이브러리       없음  ← 유지한다 (§10.5)
```

shadcn 채택은 "15개에서 1개로 줄이는 일"이 아니라 \*\*"0개에서 1개를 새로 들이는 일"\*\*이다. 진짜 비용은 셋이다 — Tailwind가 함께 온다 · 토큰 체계가 둘로 갈린다 · 마케팅 초기 JS 예산에 영향한다.

**[확정] 마케팅 라우트에는 shadcn 컴포넌트를 쓰지 않는다.** 제품 앱 표면에만 도입한다.

<a id="comp-verdict"></a>
### 16.2 판정

| 소스 | 판정 | 근거 |
| --- | --- | --- |
| **shadcn/ui** | **채택 — 유일한 기반** | MIT. 공식 인덱스 **64개** 컴포넌트(v2의 "80+"는 과장). Resizable · Sidebar · Data Table · Chart · Command · Scroll Area · Empty · Field · Input Group · Spinner · Toast 전부 실재 |
| Magic UI File Tree | 거절 → 자체 제작 | MIT는 맞다. 그러나 **가상화 없음 · 제어형 확장 API 없음**(`initialExpandedItems`만, `onExpandedChange` 없음). [§12.5](#act4)는 "그래프 클릭 → 트리 확장"이 필수 |
| Aceternity Lens | 거절 → 자체 제작 | **렌더된 픽셀을 확대**한다. PDF canvas 위에서 흐려진다 |
| Aceternity Compare | 거절 | 설치 시 `@aceternity/sparkles` 동반 요구 (확인) |
| Aceternity File Upload | 거절 | 문서화된 prop이 `onChange:(files:File[])` **하나뿐**. 폴더·진행률·파일별 상태 없음 |
| 21st.dev | 거절 | **컴포넌트별 라이선스 비공개**(사이트 어디에도 명시 없음), 무료 등급 하루 2개 복사. *v2의 "CLI 설치 없음"은 틀렸다 — shadcn CLI 명령을 제공한다.* 거절 사유는 라이선스 하나로 충분하다 |
| Aceternity 전반 | 거절 | 라이선스가 **오픈소스가 아니다** — 프로프라이어터리. 테마·템플릿·파생 상품 제작 금지 조항 있음 |
| React Bits | 전면 거절 | MIT + **Commons Clause** |

<a id="comp-install"></a>
### 16.3 설치 계약

```bash
pnpm dlx shadcn@latest init --base base
pnpm dlx shadcn@latest add resizable sidebar scroll-area command \
  data-table chart tabs dialog sheet drawer progress table badge \
  tooltip popover dropdown-menu toggle-group skeleton empty spinner field
```

- **`--base`는 `base` | `radix` | `aria` 세 값이고 기본값은 `base`(Base UI)다.** v2의 "기본값 미확인"은 해결됐다 — 2026-07 체인지로그가 `New projects now use Base UI by default`라고 명시한다. `base`로 고정하고 `components.json`을 커밋한다.
- **`shadow-sm` 일괄 제거 패스는 폐기한다.** 현행 Card에 shadow 유틸리티가 없고 `ring-1 ring-foreground/10`을 쓴다. Popover에도 0건. **`ring-1`이 [§6.3](#surfaces)의 알파 헤어라인 방침과 잘 맞으므로 그대로 두고 색만 토큰으로 맵핑한다.**
- shadcn semantic color(`background`/`foreground`/`muted`/`card`/`popover`)는 **PAPER·INSTRUMENT를 각각 테마로 정의**해 매핑. 페이지에서 `bg-card` 직접 사용 금지.
- **shadcn skill을 켠다** — `components.json`을 감지해 `shadcn info --json`을 매 상호작용에 주입한다. API 환각 방지에 직접 효과가 있다.
- 서드파티 레지스트리가 필요하면 **공식 Registry Directory**(`ui.shadcn.com/docs/directory`)를 본다. 임의 목록을 유지하지 않는다.
- 한 제품 표면에 두 base를 섞지 않는다.

<a id="build-ourselves"></a>
### 16.4 직접 만들어야 하는 것

| 대상 | 이유 | 현행 |
| --- | --- | --- |
| `FacingPages` 전체 | 기성품에 없다 | 0건. 유사물은 CSS % 고정 mock |
| PDF 페이지 + bbox 오버레이 + 고배율 재렌더 | 어느 레지스트리에도 없다 | 이미지 + bbox 오버레이 + zoom/rotate는 있다. **PDF.js가 없다** |
| 폴더 인테이크 | `webkitdirectory` + 동시성 제한 큐 + 파일별 재시도 | `webkitdirectory` 0건 |
| Live Compile | shadcn Data Table/Chart + **`react-virtuoso`** | 데이터 계층 완성, 시각화 0건 |
| Knowledge 트리 | 가상화 + 제어형 확장 | 정적 목록 |
| Knowledge 그래프 | — | 하드코딩 `M…L…` 직선 SVG |

**[확정] 가상화는 `react-virtuoso`로 통일한다.** 이미 설치돼 있다. v2가 지정한 `@tanstack/react-virtual`은 미설치이며, 두 가상화 라이브러리를 함께 두는 것은 "외부 설치 최소" 원칙과 정면으로 어긋난다.

**[권장] 그래프는 자체 SVG로 만든다.** React Flow · Sigma 둘 다 미설치다. 우리 제약(노드 20–40, 엣지가 −34° 계열로 제한, 근거 없는 엣지 금지, 표 대체 수단 필수)이면 자유 배치·드래그·핸들 모델은 대부분 쓰이지 않고 번들만 커진다. 레이아웃 계산만 `lib/facing/graph-layout.ts`로 분리한다. 외부 도입이 필요하다고 판단되면 `decision.md`에 사유를 남기고 승인을 받는다.

<a id="dir-contract"></a>
### 16.5 디렉터리 계약

```text
components/
  ui/                shadcn 원본 (수정 최소, 페이지에서 직접 import 금지)
  <brand>/
    brand/           symbol, wordmark, glyphs
    facing/          FacingPages, SourcePlate, ResultPlate, EvidenceThread
    nav/  hero/  theater/  proof/  knowledge/  trust/
    instrument/      앱 셸, 패널, 데이터 행
```

디렉터리명은 G-A 결정에 종속된다.

```tsx
type FacingPagesProps = {
  ratio: '5:7' | '7:5' | '4:8' | '6:6'
  source: SourcePlateProps      // 실제 페이지 렌더 또는 plate
  result: ResultPlateProps      // 실제 컴포넌트
  threads: EvidenceThread[]     // 좌표 필수. 빈 배열이면 스레드 없음
  surface: 'paper' | 'instrument'
  frame?: boolean
}
```

`FacingPages`가 이 시스템의 **단 하나의 핵심 컴포넌트**다. `threads`는 [§14.4](#coord)가 끝나기 전까지 빈 배열로만 쓸 수 있다.

**현행 → 목표 이관**

```text
tavonel/brand/       ← brand-mark.tsx · structara-glyph.tsx (+ 심볼 신규)
tavonel/facing/      ← 신규
tavonel/nav/         ← structara-marketing-shell.tsx 의 header/footer 분리
tavonel/hero/        ← structara-hero.tsx (+ webgl-scene, G-C 종속)
tavonel/theater/     ← 신규
tavonel/proof/       ← structara-proof-demo.tsx + workspace/source-viewer.tsx 공용부
tavonel/knowledge/   ← knowledge-studio.tsx 분해
tavonel/trust/       ← 신규
tavonel/instrument/  ← app-shell.tsx + workspace/* 패널

삭제 후보 (참조 0건)
  benchmark-lab.tsx                  export 되지만 import 하는 곳 없음
  structara-pattern.tsx 미사용 5종    page-grid · semantic-blocks · evidence-paths
                                     node-constellation · compilation-layers
  structara-glyph.tsx 미사용 12종
  .marketing-site 계열 CSS 전량       어떤 .tsx 도 이 클래스를 붙이지 않는다
  .st-poster-pages · .st-page-visual  대응 .tsx 없음
```

* * *

<a id="skills"></a>
## 17. 스킬 스택

| 스킬 | 판정 | 실측 (2026-08-07) |
| --- | --- | --- |
| **Vercel `web-design-guidelines`** | **1순위 채택** | 얇은 로더가 맞다 — 다만 그 로더는 `vercel-labs/agent-skills` 쪽이고 `web-interface-guidelines` 저장소는 규칙 전문을 담는다. 어느 쪽이든 `main` 참조라 **핀 고정 없음** → vendoring + 커밋 해시 고정 |
| **Emil `review-animations`** | **채택** | 10규칙 + 9단계 교정 순서 전부 확인. [§10.2](#motion-rules)가 이 값이다 |
| **Emil `emil-design-eng`** | **채택** | v2의 "미확인 · 라우터 서문"은 틀렸다. 4단계 애니메이션 결정 프레임워크 · 구체 cubic-bezier · 요소별 지속시간 · 컴포넌트 패턴 · 제스처 감쇠 · 코드리뷰 표 포맷을 갖춘 **완결된 지식베이스**다 |
| **OpenAI `frontend-skill`** | **채택** | v2의 "404"는 틀렸다. 접근 가능하다. 규칙: full-bleed hero · `No cards by default. Never use cards in the hero` · 서체 2개 이하 + 액센트 1개 · `Ship at least 2-3 intentional motions` · 금지 목록(hero cards, stat strips, logo clouds, pill soup, floating dashboards) · **회피 스택에 Inter 명시** · 착수 전 **visual thesis / content plan / interaction thesis** 3종 |
| Vercel `react-best-practices` | 채택(엔지니어링) | 8범주 **70규칙** (README의 "40+"는 낡은 값) |
| shadcn skills | **채택** | 조건부가 아니라 도입과 동시에 켠다 |
| Emil `pick-ui-library` | 제한 사용 | 16개 라이브러리 5범주. `package.json`을 먼저 읽고 기존 도구와 경쟁하면 지적하는 방식이라 실제 충돌은 적다. 동점 판정용 |
| **`pbakaus/impeccable`** | **채택 (신규)** | Apache-2.0. **59개 결정론적 디텍터 규칙을 AI 없이 CLI로 실행.** [§25.3](#g3) 검사기를 처음부터 짤 이유가 없다 |
| **`Leonxlnx/taste-skill`** | **조건부 채택 (신규)** | MIT. anti-slop 프레임워크. [§5.2](#material-risk) 리스크 **상시 감시용으로만**. 시안 생성에는 쓰지 않는다 |
| `vercel-labs/react-view-transitions` | 채택 (신규) | [§18](#platform)과 직결 |
| `greensock/gsap-skills` | 보류 | [§10.5](#motion-impl)가 CSS 우선을 정했다. 스크롤 모션을 JS로 가야 할 때만 재검토 |
| `ui-ux-pro-max` | **거절** | 84 스타일 · 192 팔레트 · 74 페어링을 **생성**하는 엔진. 우리가 확정한 레이어를 다시 만들어 낸다 |

<a id="absorbed"></a>
### 17.1 흡수한 규칙

```text
숫자 열에 font-variant-numeric: tabular-nums
헤딩에 text-wrap: balance          ← :lang(en) 에만. KO 는 금지 (§7.4)
본문에 text-wrap: pretty
말줄임 … 문자, 곡선 따옴표, 단위 앞 non-breaking space
transform / opacity 만 애니메이션. transition: all 금지
애니메이션은 중단 가능해야 함. 자동재생보다 사용자 개시
:focus 대신 :focus-visible. outline-none 은 대체 없이 금지
이미지에 명시적 width/height, 접힘 아래는 loading="lazy"
50개 초과 리스트는 가상화
헤딩 앵커에 scroll-margin-top
모달에 overscroll-behavior: contain
SVG 변형은 <g> 래퍼에
입력에 autocomplete/name, 붙여넣기 차단 금지,
  제출 버튼은 요청 시작 전까지 활성, 이메일·코드는 spellcheck 끄기
상태를 URL 에 반영, 딥링크 지원, 파괴적 동작은 확인 요구
브랜드명·식별자는 translate="no", 날짜·숫자는 Intl API
플레이스홀더는 … 로 끝낸다
```

<a id="skill-ops"></a>
### 17.2 운영 규칙

```text
1. 한 작업에 스킬을 겹쳐 실행하지 않는다
     설계 패스 (emil-design-eng + openai frontend-skill)
     → 구현 패스 (shadcn skill + react-best-practices)
     → 감사 패스 (web-design-guidelines + impeccable)
     → 모션 패스 (review-animations)
2. command.md 는 저장소에 vendoring 하고 커밋 해시를 기록한다
3. 스킬이 새 팔레트·새 디자인 시스템·새 라이브러리 설치를 제안하면 거절한다
4. taste-skill 은 감시에만 쓴다. 생성에 쓰면 §5.2 리스크를 스스로 불러온다
```

* * *

<a id="platform"></a>
## 18. 플랫폼 크래프트

**v2에 이 절이 통째로 없었다.** 2026년에 이것들을 쓰지 않는 것이 "낡음"이다. 아래는 2026-08 기준 지원 현황 실측이다.

<a id="platform-safe"></a>
### 18.1 지금 안전한 것

```text
Widely available — 자유롭게 사용
  @container · 컨테이너 스타일 쿼리 · @layer · color-mix() · OKLCH · <dialog>
  text-wrap: balance

Newly available — 안전
  @property            애니메이션 가능한 커스텀 속성   → 스레드 그리기에 직결
  @starting-style      JS 없는 진입 애니메이션
  popover              JS 오버레이 라이브러리 대체
  content-visibility   §22 가 요구하면서 현행 0건
  field-sizing         2026-06 Baseline 진입
  동일문서 View Transitions   Firefox 144 포함 전 엔진
```

<a id="platform-progressive"></a>
### 18.2 폴백을 두고 쓰는 것

```text
scroll-driven animation-timeline    Chrome + Safari 26. Firefox 없음 (~85%)
                                    → IntersectionObserver 폴백 필수
animation-trigger                   Chrome 145+. 리빌 전용
cross-document View Transitions     Firefox 없음
                                    @view-transition { navigation: auto }
                                    주의: <meta name="view-transition"> 문법은 폐기됨
                                    4초 타임아웃 · ::view-transition-old/new 에 object-fit: cover
anchor positioning                  Chrome 125 / Safari 26 / Firefox 147 (~76%)
                                    → Floating UI 대체 가능
text-wrap: pretty                   Firefox 없음. 순수 가산이므로 그냥 쓴다
speculationrules                    Chrome only. 공짜 성능 이득
```

<a id="platform-apply"></a>
### 18.3 [확정] 적용 지점

```text
@layer               W0 부터 모든 신규 CSS 를 계층으로 선언한다
                     → §23.2 레거시 제거가 특정성 싸움 없이 끝난다
@property + transition   스레드 그리기 · 진행 링 · 게이지
@starting-style      모달 · 드로어 · 팝오버 진입 (JS 0)
popover + <dialog>   Command Palette · 메가 패널 · Review Drawer
content-visibility   INSTRUMENT 전폭 면 · 긴 목록
animation-timeline   섹션 리빌 (IntersectionObserver 폴백)
anchor positioning   툴팁 · 팝오버 위치 (Floating UI 도입하지 않는다)
@container           대응면 컴포넌트 — 뷰포트가 아니라 컨테이너 폭으로 5:7 → 세로 스택 전환
speculationrules     공개 라우트 프리페치
```

<a id="contrast"></a>
### 18.4 대비 기준 [확정]

**WCAG 2에서 APCA로 전환한다.** 상호작용 상태는 정지 상태보다 높은 대비를 요구한다. `contrast-color()`는 Baseline 2026 세트에 있으므로 토큰 파생에 쓴다. WCAG 2.2 AA는 여전히 최저선으로 유지한다([§21](#a11y)).

* * *

<a id="ai-readable"></a>
## 19. AI 가독성

**v2에 이 절이 없었다.** 그리고 이 제품에는 특별히 맞는 논거가 있다 — **"AI가 쓸 수 있는 지식"을 파는 사이트가 정작 AI에게 읽히지 않는 것은 그 자체로 모순이다.**

```text
□ llms.txt              사이트 구조 · 카테고리 정의 · 핵심 사실의 LLM 용 요약
                        진실성 경계를 여기에도 적용한다 — 측정되지 않은 것은 그렇게 쓴다
□ agents.json / agent-card.json
□ 전 페이지 JSON-LD (schema.org)
                        SoftwareApplication (제품 라우트)
                        Dataset (벤치마크 · 공개 필기 fixture)
                        TechArticle (research · developers)
                        FAQPage (해당 라우트에만)
□ 의미 있는 헤딩 위계 + 평문 가치 제안
                        AI 요약이 인용 가능한 형태로. 이미지 안에만 있는 주장 금지
□ 모든 이미지에 실질적 alt — 장식 이미지는 alt=""
```

> [신뢰도 중] 독립된 두 스튜디오가 2026년 최대 변화로 지목한다. 둘 다 2차 출처다. 그러나 비용이 낮고 위 논거가 별도로 성립하므로 채택한다.

[§13](#public-routes) 공통 완료 조건에 `JSON-LD`를 넣었다.

<a id="part-6"></a>
# PART VI · 반응형 · 접근성 · 성능

<a id="responsive"></a>
## 20. 반응형

| 뷰포트 | 대응면 처리 |
| --- | --- |
| ≥1280 | 좌우 대응, 3-pane 제품 화면 |
| 1024–1279 | 대응 유지하되 6:6, 제품은 2-pane + 드로어 |
| 768–1023 | 세로 대응(원문 위 / 결과 아래), 스레드 수직 |
| ≤767 | 세로 대응 + 탭 전환(Source / Result), 데스크톱 축소 금지 |

**[확정] 경계를 4개로 정리한다 — `1280 · 1024 · 768`.** 현행은 전부 `max-width`이고 **16종**이 쓰인다(430 · 480 · 560 · 620 · 640 · 700 · 760 · 767 · 820 · 900 · 960 · 1023 · 1100 · 1120 · 1180 · 1279). 실제로 레이아웃이 바뀌는 주요 경계는 1180(데스크톱 내비 숨김) · 1023(제품 2-pane) · 960(WebGL 게이트) · 900(사이드바 72px) · 767(사이드바 숨김) · 700(하단 고정 내비)이다. W0에서 4개로 수렴시키고 나머지 12개를 제거한다. **WebGL 게이트도 1024로 옮긴다**(현재 960).

**대응면 컴포넌트는 `@container`로 전환한다** — 뷰포트가 아니라 컨테이너 폭에 반응해야 `FacingPages`를 어느 자리에 놓아도 같은 규칙이 돈다([§18.3](#platform-apply)).

**검증 뷰포트 [게이트 부수]** — `1920 · 1440 · 1280 · 1024 · 768 · 390 · 360` 7종. 현행 `playwright.config.ts`는 프로젝트 **2개**(Desktop Chrome · iPhone 13)뿐이고 `AGENTS.md`는 **4폭**(1920/1440/1024/390)을 요구한다. **셋이 서로 다르다 — 하나로 통일해야 한다.** 7종을 택하면 `AGENTS.md`를 같이 고친다.

모바일은 **재구성**이지 축소가 아니다. 390에서 Hero 헤드라인 개행은 언어별 수동 지정. 1920+에서 행 길이를 늘리지 않는다(인스펙터 max 420, 페이지 레일 max 300).

* * *

<a id="a11y"></a>
## 21. 접근성 — WCAG 2.2 AA 최저선 + APCA

```text
스레드는 시각 보조일 뿐 — 동일 정보를 텍스트로 제공
  예: "Table 14, page 31, block 7 — verified"
PDF 오버레이에 접근 가능한 블록 리스트 병행
그래프에 entity / relation 표 대체 필수
드래그(비교 슬라이더, 패널 리사이즈)에 키보드 대체 필수
포커스 링 2px, 대비 3:1 이상, 가려지지 않음, :focus-visible
  → outline: 0 은 대체 없이 금지. 현행 6곳이 위반 중
최소 타깃 24×24 (모바일 주요 액션 44×44)
200% 줌에서 가로 스크롤 0
  → 현행은 rem 기반 크기가 0건이라 이 조건을 구조적으로 못 지킨다 (§7.3)
SSE 갱신은 마일스톤만 aria-live="polite" — 전체 스트림 금지
role="alert" 와 aria-live="polite" 를 섞지 않는다
aria-busy 는 신뢰하지 않는다 (지원 미흡) — status 영역으로 대체
forced-colors 대응
skip-to-content 링크 제공  ← 현행 충족
대화형 데모에 실질적 alt/label
  cursor.com 의 "Interactive demo for sighted users" 가 좋은 사례다
```

**중복 유틸리티 정리** — 현행에 `.sr-only`와 `.visually-hidden`이 같은 목적으로 둘 다 있다. 하나로 합치고 `clip-path` 폴백을 추가한다.

**`prefers-reduced-motion` 블록이 4개, 범위와 값이 서로 다르다**(0.01ms vs 1ms). 하나로 통일하되 **제거가 아니라 감쇠**로 정의한다([§10.4](#motion-forbidden)).

* * *

<a id="perf"></a>
## 22. 성능 예산

| 지표 | 목표 | 실패 시 |
| --- | --- | --- |
| Mobile Lighthouse | ≥ 90 | 배포 차단 |
| Lab LCP | ≤ **2\.0s** | 배포 차단 |
| INP | ≤ 200ms | 배포 차단 |
| CLS | ≤ 0.05 | 배포 차단 |
| 마케팅 초기 JS | ≤ 180KB gzip | 리뷰 |
| Hero 포스터 | ≤ 140KB AVIF | 리뷰 |
| 3D 자산 (G-C B·C안) | GLB ≤1.5MB (텍스처 ≤1MB) | 리뷰 |
| ACT 2 WebM | ≤ 900KB, lazy | 리뷰 |
| 폰트 | ≤ 90KB subset, preload, swap | 리뷰 |

- Hero LCP는 반드시 **포스터 이미지**. JS로 그리지 않는다. *(현행 충족 — AVIF 71KB / WebP 58KB.)*
- INSTRUMENT 전폭 면은 `content-visibility: auto` + 뷰포트 진입 시 로드. *(현행 0건.)*
- PDF.js · 그래프 · 에디터 · R3F는 전부 dynamic import. *(현행 R3F만. `@uiw/react-codemirror`가 정적 import라 워크스페이스 번들에 상시 포함된다 — 분리 필요.)*
- 이벤트 UI 배치 ≤10Hz. 리스트 가상화.
- 1,000페이지 문서: thumbnail DOM ≤30, full canvas ≤3, overlay 현재±1. *(현행 상한 코드 0건.)*
- `next.config.ts`에 **`images` 설정이 전혀 없다** — `formats`·`deviceSizes`를 명시하지 않으면 2880×1800 원본이 그대로 나갈 수 있는 경로가 생긴다. W0에서 명시한다.

**[확정] 측정 인프라부터 만든다.** 저장소에 Lighthouse 리포트도 CI 게이트도 없다. 만들지 않으면 이 절 전체가 선언으로 남는다.

* * *

<a id="part-7"></a>
# PART VII · 실행

<a id="repo"></a>
## 23. 저장소 운영

<a id="waves"></a>
### 23.1 브랜치 · 웨이브

```text
브랜치   agent/<brand>-design-facing-pages-v1
PR 상한  40 files / PR · 한 PR = 한 개의 크리에이티브 결정
```

| Wave | 내용 | 산출 |
| --- | --- | --- |
| **W-1** | **오너 결정 5건 (§0.5)** | `decision.md` |
| W0 | 토큰·타이포·그리드·글리프 12종 · `@layer` 골격 · 검사기 · Lighthouse CI · 즉시수정 3건 | `tokens.css`, 글리프 SVG, 검사기 |
| W1 | `FacingPages` + **Hero 3안 정적 시안**(1440/390) | 시안 6장 + `decision.md` |
| W2 | Navigation + Hero(승인된 1안, 어포던스 포함) | 라이브 Hero |
| W3 | Plate Pipeline 통합 + ACT 2 Live Compile | 플레이트 세트, 재생 UI |
| W4 | ACT 3 Proof 워크벤치 (PDF.js 도입, golden bbox 20) | IoU ≥0.95 |
| W5 | ACT 4·5·6 + Footer | 홈 완성 |
| W6 | 라우트 템플릿 T1/T2/T3 + JSON-LD + llms.txt | 공개 라우트 |
| W7 | 앱 셸 INSTRUMENT 전환 | 제품 화면 |
| W8 | Hero 3D (G-C B·C안 선택 시에만) | GLB + 포스터 |
| W9 | 레거시 CSS 제거 + 미참조 자산 정리 + 최종 QA | 삭제 원장, 증거 번들 |

**W0의 즉시 수정 3건** — 현행 코드가 이미 리젝트 조항에 걸린다.

```text
① WebGL 무한 패럴랙스 제거          §10.4
② 데모 워크스페이스 68% 하드코딩 제거  §11.1
③ text-wrap: balance 를 :lang(en) 로 게이트   §7.4
```

<a id="css-removal"></a>
### 23.2 레거시 CSS 제거

대상은 5개 파일 **16,048줄**이다. v2의 목록(`enterprise-refresh → structara* → tavonel.css`)은 틀렸다 — `tavonel.css`는 `main`에 없고, 가장 큰 두 파일이 빠져 있었다.

```text
현행 적재 순서 (layout.tsx:7-10, 뒤가 앞을 덮는다)
  1  src/app/globals.css            8,777줄   앱 셸·워크스페이스·마케팅이 뒤섞임
  2  src/app/product-shell.css      1,367줄   .app-frame 스킨 + 대시보드
  3  src/app/enterprise-refresh.css   794줄   :root 토큰 재정의 + 마케팅 오버레이
  4  src/app/structara.css          4,715줄   마케팅 시스템 + 제품 셸 재스킨(중복)
  5  components/analytics-live.module.css  395줄   CSS Module (독립)

제거 순서 (덮는 쪽부터)
  ① enterprise-refresh.css    :root 재정의를 tokens.css 로 흡수 후 삭제
                              (--font-ui Aptos 오버라이드가 여기 있다)
  ② structara.css 제품부       3215줄 이후 .app-frame/.sidebar/.nav-item/.topbar 재스킨
                              → W7 에서 instrument 계층으로 이관 후 삭제
  ③ product-shell.css          ②와 같은 선택자를 다루므로 함께 정리
  ④ structara.css 마케팅부      1~3214줄. W2~W6 장면 이관 후 삭제
  ⑤ globals.css                가장 마지막. 워크스페이스 의존이 가장 크다
  ⑥ analytics-live.module.css  독립. 미정의 --font-sans 만 수정
```

**같은 선택자를 여러 파일이 다투는 지점**

```text
:root 토큰            globals:1-69 ⟷ enterprise-refresh:9-39           (후자 승)
:root 다크            globals:83-114 ⟷ enterprise-refresh:50-78
.app-frame 토큰       product-shell:8-37 ⟷ enterprise-refresh:311 ⟷ structara:3216
.app-frame .nav-item.active   네 파일이 경쟁
.app-frame .sidebar   product-shell(다크) ⟷ structara(라이트) — 모순된 정의가 공존
.marketing-site       globals:4408 · enterprise-refresh:112
                      → 어떤 .tsx 도 이 클래스를 붙이지 않는다. 전량 죽은 CSS, 즉시 삭제 가능
prefers-reduced-motion  4개 블록이 서로 다른 범위·값
```

**`@layer`를 W0에 도입하면 이 이관이 특정성 싸움 없이 끝난다.** 신규 CSS를 `@layer tokens, base, components, utilities`로 선언하고 레거시는 계층 밖에 두면, 레거시가 무엇을 하든 신규가 이긴다.

**미정의인데 참조되는 변수** — `--text-primary`(9곳) · `--st-serif`(5곳) · `--evidence`(3곳) · `--warning-text`(2곳) · `--warning-subtle`(1곳) · `--font-sans`(1곳). W0에서 흡수하거나 삭제한다.

<a id="file-structure"></a>
### 23.3 파일 구조

```text
apps/web/src/
  styles/
    tokens.css          §6.1                              [신규]
    foundations.css     reset, 타이포 역할, :lang 오버라이드  [신규]
    surfaces.css        paper / instrument 면 정의          [신규]
  components/<brand>/   §16.5                             [신규 + 기존 이관]
  scenes/
    hero/  theater/  proof/  knowledge/  trust/           [신규]
  lib/
    facing/thread.ts       bbox → path                    [신규]
    facing/normalize.ts    좌표 정규화                      [신규 — bbox.ts 확장]
    facing/graph-layout.ts 그래프 레이아웃                  [신규]
    plates/                플레이트 로더                    [신규]
apps/web/scripts/         §15.2 (tools/plates/ 가 아니라 여기)
apps/web/tools/plates/fixtures/   동결 원문 + 동결 event log  [신규]
apps/web/public/llms.txt          §19                     [신규]
design-system/<brand>/
  DESIGN_MASTER_V3.md     이 문서
  decision.md             정적 시안 · 게이트 결정 기록        [신규]
  vendored/command.md     web-interface-guidelines 고정본 + 커밋 해시  [신규]
```

**`docs/design/`을 새로 만들지 않는다.** `design-system/{structara,ai-knowledge-compiler}/MASTER.md`가 이미 있다. 새로 파면 디자인 진실 소스가 세 곳이 된다.

* * *

<a id="agent-contract"></a>
## 24. 에이전트 계약

<a id="agents-md"></a>
### 24.1 `AGENTS.md` 갱신 + `CLAUDE.md` 신설

**루트에 `CLAUDE.md`는 없다. 실제 계약 파일은 `AGENTS.md`다.** 새 파일을 그냥 추가하면 [§0.2](#conflict-order)의 권한 순서가 깨진다.

```text
현행 AGENTS.md 가 이미 규정하는 것
  필수 컨텍스트   .agents/skills/structara-brand-experience/SKILL.md
                  .agents/skills/structara-asset-director/SKILL.md
                  STRUCTARA_BRAND_DECISIONS.md · PAGE_MANIFEST.yml
  설계 권한 순서   진실·안전·법률 → Structara 마스터플랜 → 브랜드 스킬
                  → 승인된 디자인 결정 → 라우트 브리프 → 외부 스킬 → 라이브러리 기본값
  기술 기본값      Next App Router · CSS 변수를 토큰 진실 소스로 · R3F + 정적 폴백
                  "PDF.js and virtualized document surfaces where applicable"
  증거 요구        1920 / 1440 / 1024 / 390 + reduced motion → VISUAL_QA_REPORT.md
```

**고쳐야 할 4줄**

```text
1. "Structara 마스터플랜" → 이 문서 경로로 교체 (설계 권한 2위)
2. 증거 뷰포트 4폭 → §20 결정에 맞춰 통일
3. "PDF.js and virtualized document surfaces" → 현재 미설치임을 명시하거나 W4 도입 예정으로 표기
4. STRUCTARA_BRAND_DECISIONS.md 참조 → G-A 결정 후 파일명 정리
```

**`CLAUDE.md` (루트, 신규 — 얇게 둔다)**

```markdown
# 프론트엔드 규칙

이 저장소의 에이전트 계약은 AGENTS.md 다. 먼저 읽는다.
시각 설계의 단일 진실은 design-system/<brand>/DESIGN_MASTER_V3.md 다.
이 파일과 충돌하는 제안은 거절한다.

## 절대 규칙
- 모든 장면은 FacingPages(좌 원문 / 우 산출물)의 변주다. 좌우를 바꾸지 않는다.
- 좌표 없는 장식 스레드를 그리지 않는다. 좌표가 없으면 threads=[] 로 둔다.
- 깊이는 포커스 링 · 호버 · 오버레이 세 곳에만. 카드·섹션에 그림자를 넣지 않는다.
- 보더는 알파다. 하드코딩 헥스 규칙선을 쓰지 않는다.
- 브랜드 색은 primary CTA · 활성 마커 · 포커스 링 · 활성 스레드 4곳에만.
- 한 뷰포트에 동일 형태 요소 4개 초과 금지. 홈에 <table> 0개.
- 진행률을 setInterval 로 만들지 않는다. 진행률 리터럴(예: 68%)도 금지한다.
- DOM 으로 재작성한 표를 "원문"으로 표시하지 않는다.
- 실패한 단위를 흔적 없이 성공으로 바꾸지 않는다.
- UI 애니메이션 300ms 미만, ease-out 진입, transform/opacity 만.
  무한 지속 애니메이션을 만들지 않는다. 자동재생보다 사용자 개시를 택한다.
- 헤딩의 text-wrap: balance 는 :lang(en) 에만. :lang(ko) 에는 word-break: keep-all.
- 동작하지 않는 컨트롤을 만들지 않는다.
- 새 CSS 는 @layer 안에 쓴다.

## 새 의존성
외부 UI 컴포넌트는 shadcn/ui 하나다. 가상화는 react-virtuoso.
아이콘은 @phosphor-icons/react. 애니메이션 라이브러리를 추가하지 않는다.
추가 설치가 필요하면 먼저 이유를 design-system/<brand>/decision.md 에 적고 승인을 받는다.

## 게이트
W-1 결정 5건이 decision.md 에 없으면 W0 에 착수하지 않는다.
Hero·Navigation·Proof·Live Compile 은 정적 시안 3안 승인 전 구현 코드를 쓰지 않는다.

## 자기 승인 금지
구현한 세션은 자신의 결과를 승인하지 않는다.
```

<a id="subagents"></a>
### 24.2 서브에이전트 역할 분리

같은 컨텍스트가 설계·구현·심사를 다 하면 [§1.2](#secondary-cause) D-10이 반복된다.

| 에이전트 | 역할 | 도구 제한 |
| --- | --- | --- |
| `design-scout` | 레퍼런스 조사, 시안 옵션 생성 | 읽기 + 웹만. **쓰기 금지** |
| `builder` | 구현 | 전체 |
| `design-critic` | [§25](#qa) 판정 수행 | **읽기 전용.** 코드 수정 금지 |
| `a11y-perf-auditor` | web-design-guidelines + react-best-practices + impeccable 감사 | 읽기 + 브라우저 |

`design-critic`은 **builder와 다른 세션**이어야 한다. 이것이 자기 승인을 막는 유일한 구조적 장치다.

<a id="task-contract"></a>
### 24.3 작업 단위 계약

OpenAI frontend-skill의 3종 thesis를 흡수했다.

```yaml
task_id:
scene:                 # 한 번에 한 장면
visual_thesis:         # 한 문장 — 무드 / 재질 / 에너지
content_plan:          # 이 장면이 전달할 사실 목록
interaction_thesis:    # 사용자가 여기서 무엇을 할 수 있는가 (없으면 "없음"이라고 쓴다)
inputs:                # 승인된 시안, fixture, 이벤트 로그
outputs:               # 파일 목록
tests:                 # 추가한 테스트
evidence:              # 스크린샷 경로 (7 뷰포트 × reduced-motion)
gates:                 # 통과/미통과
stop_conditions:       # 무엇을 만나면 멈추는가
rollback:              # 되돌리는 방법
```

<a id="stop"></a>
### 24.4 중단 조건

```text
승인된 정적 시안이 없는 장면을 구현하라는 요청
W-1 결정 5건 중 해당 항목이 열려 있음
새 외부 컴포넌트 설치가 필요해 보임
토큰에 없는 색을 써야 할 것 같음
실제 데이터 없이 화면을 채워야 할 상황
백엔드 API 계약 변경이 필요함 (G-E 계열)
성능 예산 초과가 예상됨
접근성 요구와 시각 요구가 충돌
```

* * *

<a id="qa"></a>
## 25. 검수

기존 100점 루브릭은 현재 화면에 94점을 줬다. 절대 점수는 자기 승인을 막지 못한다. 폐기한다.

<a id="g1"></a>
### 25.1 G-1 · 블라인드 카테고리 테스트

- 대상 8명, 노출 10초, 사이트 이름 가림.
- 질문: "이 회사는 무엇을 하는가?"
- 통과: **8명 중 6명 이상**이 "문서를 구조화·검증된 지식으로 바꾸는 제품"에 해당하는 답.
- 실패 응답 예: "AI 도구", "데이터 분석", "문서 관리".
- **[§3.3](#hero-copy)의 Hero 카피 3방향도 여기서 결정한다.**

<a id="g2"></a>
### 25.2 G-2 · 강제 비교 판정

동일 뷰포트에서 나란히 놓고 **순위를 매긴다.** 점수가 아니라 순위다.

비교 대상 **4곳**\: **Linear · Stripe · Vercel · Cursor.** *(Cursor를 추가한다 — 실제로 다크/라이트 밴드를 교차시키고 Hero가 대화형이라 우리 사양과 직접 비교된다.)*

| 축 | 판정 |
| --- | --- |
| 타이포 크래프트 | 최하위면 실패 |
| **서체 소유** | **스톡 서체를 그대로 쓰면 자동 최하위**([§7](#type)) |
| 여백 · 리듬 | 최하위면 실패 |
| 위계 명확성 | 최하위면 실패 |
| 색 절제 | 최하위면 실패 |
| 표면 프리미티브 | 알파 보더 대 하드코딩 헥스 — 최하위면 실패 |
| **Hero가 동작하는가** | 상위 4곳 중 2곳이 어포던스다. 정적이면 감점 |
| **서명 순간이 있는가** | 하나도 없으면 실패. "무해하지만 무성격"으로 되돌아간 것이다 |
| **제품 실물 존재감** | **1위여야 함** |

**섹션 수와 nav 상단 링크 수는 판정 축에서 폐기한다.** 실측하면 상관관계가 없다([§12](#home), [§12.1](#act0)).

**제품 실물 기준선** — Linear가 홈 면적의 \*\*약 70%\*\*를 실제 제품 UI로 채운다. 우리 목표를 \*\*≥65%\*\*로 둔다(v2의 45%는 낮다).

<a id="g3"></a>
### 25.3 G-3 · 기계 검사

**`pbakaus/impeccable`(59규칙, CLI, AI 불필요) 위에 아래를 얹는다.** 처음부터 짜지 않는다.

```text
구성
□ 홈 뷰포트당 동일 형태 반복 요소 ≤ 4
□ 홈 전체 카드 컴포넌트 ≤ 6
□ 연속 카드 그리드 섹션 ≤ 2
□ 홈에 <table> 0개                                  현행 ✓
□ 섹션당 primary CTA 1개 · 홈 전체 primary 2회
□ Hero CTA 정확히 2개, 라벨이 서로 다름
□ Hero 에 카드 0개                          [신설]
□ H1 ≤ 10단어, 부제 ≤ 25단어
□ nav 상단 링크 ≤ 6 AND 펼침 총합 ≤ 25       [수정]

시각
□ 실제 제품 픽셀 면적 비율 ≥ 65% (홈)        [상향]
□ 명도 히스토그램에 PAPER / INSTRUMENT 두 봉우리
□ 한 뷰포트 비중립 색상 ≤ 1 (고객 로고 제외)
□ 장식 그림자 0건 (포커스·호버·오버레이는 허용)  [수정]
□ 보더가 전부 알파 값                        [신설]
□ Display : Body 비율 ≥ 3.5 : 1
□ 본문 measure EN 60–72자
□ 라디우스 값이 5토큰 스케일 밖인 경우 0건
□ 임의 spacing 값(4px 배수 아님) 0건
□ 본문·UI 최소 크기 12px                     [신설]

동작
□ 가로 오버플로 0 (7 뷰포트)
□ 200% 줌에서 가로 스크롤 0                  [신설]
□ 콘솔 에러 0
□ 죽은 컨트롤 0 (<a> · role=button · 404 타깃 포함)  [확장]
□ reduced-motion 정보 손실 0
□ 무한 지속 애니메이션 0건                    [신설]
□ setInterval 기반 진행률 0건                 현행 ✓
□ 진행률 리터럴 0건                          [신설]

자산 · 코드 위생
□ :lang(ko) 헤딩에 text-wrap: balance 0건
□ Google Fonts CDN link 0건                  현행 ✓
□ 미참조 정적 에셋 0건                        [신설]
□ 미정의 CSS 변수 참조 0건                    [신설]
□ 미사용 CSS 클래스 0건                       [신설]
□ 3D 자산 합계 ≤ 2.5MB, 모바일 WebGL 미로드
□ 모든 이미지에 alt (장식은 alt="")           [신설]
□ JSON-LD 파싱 통과                          [신설]
```

**현행 위반 상태** — 이 목록을 지금 돌리면 최소 11항이 실패한다. 카드 14개, 연속 카드 그리드 3, primary 4회, 제품 픽셀 0%, PAPER 그림자 5건, 라디우스 리터럴 23종, spacing 5·7·9·11·13px 대량, `text-wrap: balance` 게이트 없음 3건, 진행률 리터럴, 미참조 에셋 20+, 미정의 변수 6종.

<a id="g4"></a>
### 25.4 G-4 · 스쿼트 테스트

25% 축소 + 그레이스케일 + 블러 8px에서:

- 시선이 멈추는 지점이 페이지당 2–3곳으로 식별되는가
- 대응면 형태가 인식되는가
- 균일한 회색 밭으로 보이지 않는가
- **3D를 끈 상태에서도 메시지가 전달되는가** — 실패 시 3D 의존, 리젝트
- (B·C안) 12개 오브젝트를 실루엣만으로 구분 가능한가

<a id="g5"></a>
### 25.5 G-5 · Live Compile 진실성 검사

```text
□ "실패 → 복구 → 검증" 궤적이 한 번 이상 관찰되는가
□ 복구된 단위에 흉터(recovered 표식 + 시도 횟수)가 남는가
□ 모든 수치가 이벤트 로그와 일치하는가 (로그 대조)
□ quarantine / unresolved 가 화면에 존재하는가
□ 재시도가 색이 아니라 선 스타일로도 표현되는가
□ 표시된 진행률이 전부 실측 파생인가 (리터럴 0건)
```

<a id="approval"></a>
### 25.6 승인 권한

- 구현한 세션은 승인할 수 없다.
- **G-1과 G-2는 사람만 판정한다.**
- 승인 기록 없이 visual baseline 갱신 금지.

<a id="reject"></a>
### 25.7 즉시 리젝트

```text
DOM 재작성 표를 원문으로 표시              ← 현행 데모가 위반 중
좌표 없는 장식 스레드                      ← 현행 마케팅이 위반 중
무한 지속 애니메이션                        ← 현행 WebGL 씬이 위반 중
진행률 리터럴                              ← 현행 데모 워크스페이스가 위반 중
플레이트 대신 목업 이미지 사용
좌우 대응 순서 반전
카드 그리드가 대응면을 대체
Hero 에 카드
번호 라벨 노출
홈에 벤치마크 수치 표
로고 캐러셀 추가
"messy documents into clean data" 계열 헤드라인
Parse / Extract / Split 기능 나열
승인 전 baseline 갱신 · 자기 세션 승인
죽은 CTA 1개 이상 · 모바일이 데스크톱 축소
전부 초록으로 끝나는 처리 장면
```

<a id="appendix"></a>
# 부록

<a id="baseline"></a>
## A. 현행 코드 기준선

`0ssol1620-byte/ai-knowledge-compiler` · `main@7ac5098` · `apps/web` (2026-08-07)

```text
규모
  라우트          25개 (src/app)
  컴포넌트        79개 .tsx  (workspace/ 13개 포함)
  라이브러리       44개 .ts
  CSS             5개 파일 16,048줄
  스크립트         capture-*.mjs 3개 + verify-button-contracts.mjs

스택
  next 16.2.12 · react 19.2.8 · typescript 5.9.3
  zustand 5.0.14 · @tanstack/react-query 5.101.4 · zod 4.4.3
  @microsoft/fetch-event-source 2.0.1
  @phosphor-icons/react 2.1.10 · react-virtuoso 4.18.11 · clsx 2.1.1
  @uiw/react-codemirror 4.25.11  (정적 import)
  three 0.180.0 · @react-three/fiber 9.4.0 · @react-three/drei 10.7.6
  unified/remark/rehype 마크다운 파이프라인 · date-fns · hash-wasm
  미설치: tailwindcss · shadcn · radix · pdfjs-dist · 애니메이션 라이브러리
          @tanstack/react-virtual · react-flow · sigma

없는 것
  src/styles/ · tokens.css · docs/design/ · CLAUDE.md · components.json
  next/font (0건) · @font-face (0건) · :lang() (0건) · i18n · hreflang
  content-visibility (0건) · @layer · @container
  density 스위처 · webkitdirectory · 처리 레인 · quarantine · Finding Inspector

이미 맞는 것
  홈 <table> 0 · setInterval 0 · Google Fonts 0 · skip-link ✓
  Hero LCP = priority 포스터 (AVIF 71KB)
  SSE durable event 25종 + 시퀀스 갭 복구 + 중복 제거 + replay
  진행률 8단계 가중 실측 · ETA 없음
  죽은 버튼 CI 검사 (범위 제한적)
  조작된 로고·인용 0건
  R3F 3D dynamic import + reduced-motion/saveData 게이트

주요 수치
  --sidebar-width 256px / 접힘 64px / aside 240px  (불일치)
  --topbar-height 48px
  font-size 선언 667건 · 고유값 72종 · ≤8px 100건 · rem 0건
  border-radius 195건 중 토큰 사용 23건 (12%)
  breakpoint 16종 (전부 max-width)
  public/hero 24개 중 20개 미참조 · assets/3d/derivatives 전량 미참조
  미정의 참조 변수 6종
```

* * *

<a id="checklist"></a>
## B. 착수 체크리스트

**W-1 · 오너 결정 — 전부 닫히기 전 W0 착수 금지**

```text
□ G-A  제품명 확정 — TAVONEL / Structara                     §0.5
□ G-B  서체 획득 — 커스텀 / Linear 우회로 / 유료 라이선스      §7.2  [권장 B]
□ G-C  TIER 1 3D — 폐기 / 마크 축소 / 원안 유지               §9.2  [권장 폐기]
□ G-D  KO 로케일 도입 여부                                    §7.4
□ G-E  SourceRef 에 rotation / cropbox 추가 (백엔드 합의)      §14.4

부수
□ 사진 예외 1곳을 열 것인가                                   §15.4
□ 액센트 색상각 — 인디고(벤치마크 중복)·앰버/에메랄드(슬롭) 회피  §6.2
□ 검증 뷰포트 4폭 / 7종 통일                                  §20
```

**W0 · 착수**

```text
승인 · 배치
□ 이 문서를 시각 설계 단일 진실로 승인
□ design-system/<brand>/ 에 배치, AGENTS.md 권한 순서 갱신     §24.1
□ CLAUDE.md 를 얇게 신설                                      §24.1
□ agent/<brand>-design-facing-pages-v1 생성

토큰 · 기반
□ src/styles/tokens.css 신설 + layout.tsx 최상단 import         §6.1
    OKLCH · 알파 보더 · 깊이 3종 · 모션 토큰
□ @layer tokens, base, components, utilities 골격              §23.2
□ 서체 로딩 (G-B 결정 반영) — next/font/local · preload · subset  §7.2
□ 글리프 12종 재정의 + 미사용 심볼 제거                          §8.3

검사 · 측정
□ pbakaus/impeccable 도입 후 §25.3 항목 추가                    §25.3
□ verify-button-contracts.mjs 6항목 확장                       §14.3
□ Lighthouse CI + 7 뷰포트 Playwright 프로젝트                  §20 · §22
□ next.config.ts 에 images 설정 명시                            §22

스킬
□ shadcn skill · emil-design-eng · openai frontend-skill 활성화  §17
□ web-interface-guidelines vendoring + 커밋 해시 기록            §17
□ 작업 단위 계약에 3종 thesis 흡수                              §24.3

AI 가독성
□ llms.txt · JSON-LD 초안                                      §19

즉시 수정 3건 — 현행이 리젝트 조항에 걸린다
□ WebGL 무한 패럴랙스 제거                                     §10.4
□ 데모 워크스페이스 68% 하드코딩 제거                            §11.1
□ text-wrap: balance 를 :lang(en) 로 게이트                     §7.4

정지선
□ Hero 3안 + 카피 3방향 제작
□ ★ 여기서 반드시 멈춘다 — 오너가 선택
□ decision.md 커밋
□ 그 이후에만 W2 구현 시작
```

* * *

<a id="sources"></a>
## C. 출처와 신뢰 등급

**1차 — 직접 확인 (2026-08-07)**

```text
코드      0ssol1620-byte/ai-knowledge-compiler main@7ac5098 apps/web 전수
          + origin/agent/tavonel-* 4개 브랜치 (TAVONEL 자산 소재 확인)
          + 루트 AGENTS.md · STRUCTARA_BRAND_DECISIONS.md · PAGE_MANIFEST.yml
          + design-system/{structara,ai-knowledge-compiler}/MASTER.md

경쟁사     reducto.ai · landing.ai · unstructured.io · llamaindex.ai/llamaparse
          mistral.ai/solutions/document-ai · docsumo.com · extend.ai
          github.com/extend-hq/realdoc-bench (Apache-2.0, IoU 채점 코드)

레퍼런스   linear.app (+/brand) · stripe.com (+/newsroom/brand-assets)
          vercel.com (+/font, /design/guidelines) · anthropic.com · cursor.com
          resend.com · clerk.com · retool.com · sierra.ai · figma.com · databricks.com

스킬      ui.shadcn.com/docs/{components,cli,skills,components-json,directory}
          ui.shadcn.com/docs/changelog/2026-07-{base-ui-default,react-aria}
          github.com/vercel-labs/{web-interface-guidelines,agent-skills}
          github.com/emilkowalski/skills
          github.com/openai/skills + developers.openai.com/blog
          21st.dev/pricing · ui.aceternity.com/licence
          magicuidesign/magicui LICENSE · DavidHDev/react-bits LICENSE
          nextlevelbuilder/ui-ux-pro-max-skill SKILL.md
          pbakaus/impeccable · Leonxlnx/taste-skill · greensock/gsap-skills

플랫폼    webstatus.dev · web.dev/baseline/2026 · web.dev/blog/interop-2026
          webkit.org (Safari 26.0 · 26.4 · 26.6) · developer.chrome.com/release-notes
```

**2차 — 추출 도구 · 스튜디오 · 트레이드**

```text
CSS 추출   design-extractor.com · design.withfudge.com · wtfont.app
           shadcn.io/design/* · designmd.cc/benchmarks/*
           → 실제로 출하된 값의 증거이며, 의도의 증거는 아니다
서체 순위   maxibestof.one/typefaces/popular
갤러리      land-book.com · awwwards.com · siteinspire.com
스튜디오    solodesign.cc (AI 슬롭 디텍터 50규칙) · 925studios.co · studiomeyer.io
           wandr.studio · fontfabric.com · utsubo.com
           annnimate.com/state-of-web-animation (HTTP Archive 파생)
```

**신뢰 등급**

| 절 | 등급 | 근거 |
| --- | --- | --- |
| §1 · §A · 각 절의 "현행" 기술 | **1차** | 코드 직접 확인 |
| §2 경쟁 지형 | **1차** (7곳) | 마케팅 페이지 직접 확인. Chunkr · Datalab은 미확인 |
| §7.1 서체 · §25.2 비교 축 | **1차 + 2차** | 사이트 직접 확인 + CSS 추출 도구 교차 |
| §18 플랫폼 지원 현황 | **1차** | 브라우저 벤더 · 상태 데이터 |
| §17 스킬 판정 | **1차** | 저장소 · 문서 직접 확인 |
| §5.2 AI 슬롭 신호 | **2차 · 단일 출처** | **가장 약한 근거. 무게를 낮게 둘 것** |
| §19 AI 가독성 | **2차 · 두 곳 독립** | 중간. 별도 논거로 보강했다 |

**확인하지 못한 것**

```text
브라우저 렌더 검증 없음
  폴드 점유율 · 뷰포트당 색상 수 · 스크롤 트리거 동작 · 호버 거동은 전부 미확인
Chunkr · Datalab
  SPA 라 렌더 불가. Datalab 은 /app/forge/parse 파싱 앱을 갖고 있어
  §2.2 빈 공간 판정에 실제 구멍이 남아 있다
Docsumo 의 "Click a field to see its source"
  진짜 인터랙션인지 자동재생 목업인지 텍스트 추출로만 확인했다
opsz(광학 사이징) B2B 채택 현황
  1차 출처를 찾지 못했다. 이 문서는 주장하지 않는다
```

* * *

<a id="changes"></a>
## D. v2 대비 변경 요약

| 항목 | v2 | v3 |
| --- | --- | --- |
| 경쟁 전략 근거 | "아무도 안 한다" | **"조각으로는 다 있고, 아무도 합치지 않았다"** |
| 빈 공간 | 5개 (3개 반증됨) | **3개** — 업로드+클릭+스팬 / 실패한 문서를 Hero에 / citation-to-answer |
| 1순위 위협 | LandingAI | **Extend** (홈에 벤치마크 표 + 공개 저장소) |
| 서체 | Inter + Pretendard 지정 | **획득 전략 절 신설.** Inter는 회피 대상 |
| 표면 | 1px 하드코딩 규칙선, 그림자 0 | **알파 보더 + 어포던스 깊이 3종** |
| 색 | 액센트 1 헥스 | **액센트 1 색상 + 상태 램프.** OKLCH |
| Hero | 정적 액자 + 3.6초 모션 | **어포던스 (드롭존)** — G-C 폐기 시 |
| 3D | 결정 번복 ("OFF를 뒤집는다") | **이미 라이브. 재판정 게이트** — 폐기 권장 |
| 모션 | 규칙만 | **수치 명세 + JS 없는 구현 방식** |
| 플랫폼 크래프트 | 없음 | **§18 신설** |
| AI 가독성 | 없음 | **§19 신설** |
| 비교 대상 | Linear · Stripe · Vercel | **+ Cursor** |
| 비교 축 | 5개 (섹션 수 · nav 수 포함) | **9개.** 섹션 수 · nav 수 폐기, 서체 소유 · Hero 동작 · 서명 순간 추가 |
| 제품 픽셀 목표 | ≥45% | **≥65%** (Linear 실측 ~70%) |
| 기계 검사 | 24항 | **35항**, `impeccable` 59규칙 위에 얹음 |
| 레거시 CSS 목록 | 3개 (`tavonel.css` 포함, 없는 파일) | **5개 16,048줄**, 적재 순서·경쟁 선택자 명시 |
| 에이전트 계약 | `CLAUDE.md` 신설 | **`AGENTS.md` 갱신 + `CLAUDE.md` 얇게** |
| 오너 게이트 | 없음 | **W-1 5건 + 부수 3건** |

* * *

이 문서는 코드와 시장을 각각 한 번씩 실측해 쓰였다. 두 기준선 모두 시간이 지나면 낡는다. 다음 개정 시 §A와 §C를 먼저 다시 확인할 것.
