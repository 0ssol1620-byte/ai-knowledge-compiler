# 디자인 결정 기록

`DESIGN_MASTER_V3.md` §0.5가 요구하는 W-1 선행 결정과, 그 결정이 설계도에 미치는 영향을 기록한다.
설계도와 충돌하는 내용이 여기 있으면 **이 파일이 이긴다**(설계도 §0.2 권한 순서 3위: "승인된 정적 시안(decision.md 기록)").

| | |
| --- | --- |
| 기준 문서 | `DESIGN_MASTER_V3.md` (`DESIGN-MASTER-V3-KO-20260807`) |
| 코드 기준선 | `main@7ac5098` |
| W-1 상태 | **5건 전부 결정됨 (2026-08-07)** — W0 착수 가능 |

---

## W-1 게이트

### G-A · 제품명 → **FOLYNTA로 개명**

결정일 2026-08-07.

**선행 작업** — W0보다 **먼저** 개명 PR을 머지한다. 이 PR은 **시각 변경을 포함하지 않는다.**

```
클래스 접두사      st-        → fl-
에셋 접두사        STR-       → FLY-
글리프 스프라이트   public/brand/structara-glyphs.svg
컴포넌트 파일명     structara-*.tsx  12개
콘텐츠 모듈        structara-content.ts · structara-diagrams.ts
CSS 파일명         src/app/structara.css
메타데이터         layout.tsx · manifest.ts · opengraph-image.tsx
푸터 고지          "Structara is a working name pending brand clearance." → 삭제 또는 갱신
계약 문서          AGENTS.md · STRUCTARA_BRAND_DECISIONS.md
디자인 시스템 경로  design-system/ai-knowledge-compiler/ → design-system/folynta/
                  (이 파일과 DESIGN_MASTER_V3.md 를 함께 이동)
```

**영향** — 설계도 §4.2의 브랜드 근거("FOLYNTA = folio, 펼친 지면은 이 이름에서만 나온다")가 **살아난다.** 대응면 형태의 정당성을 제품 사실만으로 방어할 필요가 없어졌다.

**주의** — 상표 clearance는 별개 트랙이다. clearance 결과가 부정적이면 이 결정과 개명 PR을 되돌려야 하므로, 개명 PR은 revert 가능한 단일 커밋으로 유지한다.

---

### G-B · 서체 획득 → **Wanted Sans Variable (OFL) + 설계도 §7.2 B안**

결정일 2026-08-07.

```
서체        Wanted Sans Variable   OFL · 가변 · 라틴+한글 단일 소스
조달 비용    0
리드타임     0
```

**선정 근거**

- **Pretendard를 배제한 이유** — 라틴이 문자 그대로 Inter 파생이다(제작자가 Inter를 명시적으로 크레딧). 설계도 §7.1의 "Inter는 템플릿 신호" 논거가 한글에도 그대로 적용된다. 한국 시장의 사실상 기본값이라 "서체를 고르지 않았다"로 읽힌다.
- **Wanted Sans를 고른 이유** — OFL이면서 가변이고, 라틴과 한글을 한 곳에서 같이 그렸다(설계도 §7.2가 요구하는 획 두께·스트레스 정합이 설계 단계에서 이미 맞춰져 있다). 시장 기본값이 아니다.
- **SUIT 배제** — 가변이지만 2,668자 커버리지라 사용자 생성 콘텐츠에서 결자가 난다.
- **IBM Plex Sans KR 배제** — 라틴-한글 페어링은 가장 정교하나(한글 베이스라인 22%를 라틴 공존용으로 조정) **가변이 아니다.**
- **유료·커스텀 보류** — 커스텀은 라틴 $40–80k / 4–8개월 + 한글 9–24개월이다(Toss는 7개월에 2,350자만 확보). Sandoll 웹폰트는 **CDN 전용이라 self-host 요구와 자격 미달**이며 페이지 텍스트가 벤더로 전송된다. 영구·self-host·PV 과금이 확인된 유일한 벤더는 Typotheque다.

**§7.2 B안(Linear 우회로)을 함께 적용한다** — 스톡으로 읽히지 않게 만드는 세 기법이다.

```
OpenType feature 전역 적용     Wanted Sans의 대체자 세트를 조사해 지정
비정수 웨이트 축 사용           400/500/600 금지. 예: 510 / 590
크기 의존 트래킹                Display에서 음수, 본문에서 0으로 수렴
```

**재검토 시점** — W6 종료 시. 그때 Typotheque 견적을 받아 교체 여부를 판단한다.

---

### G-C · TIER 1 3D → **폐기. Hero를 드롭존으로**

결정일 2026-08-07. 설계도 §9.2 A안.

**사문화되는 설계도 절 — 구현하지 않는다**

```
§9.3   12종 문서 실루엣 규격표          전량 폐기
§9.3   GLB 제작 파이프라인 · 폴백 계약   폐기
§23.1  W8 웨이브                       삭제
§25.4  "12개 오브젝트를 실루엣만으로 구분 가능한가"  검사 항목에서 제거
```

**확정되는 것**

```
§12.2  Hero 3상태 (기본 → 호버/포커스 → 드롭 후 실제 컴파일)  확정 사양
§9.1   TIER 1 은 "Signature = 동작하는 어포던스" 로 재정의
       TIER 2 · TIER 3 은 그대로 유효
```

**즉시 조치** — `structara-webgl-scene.tsx`와 `structara-hero.tsx`의 WebGL 경로를 제거한다. G-C와 무관하게 현행 무한 패럴랙스는 설계도 §10.4 위반이므로, 폐기 결정으로 통째로 해소한다. `three` / `@react-three/fiber` / `@react-three/drei` 의존성도 함께 제거해 §22 초기 JS 예산을 확보한다.

**보존** — `assets/3d/derivatives/`는 삭제하지 않는다. Hero 포스터(`STR-HOME-T2-HERO-EN-*`)는 대응면 우측 초기 상태 또는 배경으로 계속 쓴다.

---

### G-D · 한국어 로케일 → **도입**

결정일 2026-08-07.

**열리는 트랙** — 시각 설계 범위 밖이며 별도로 관리한다.

```
i18n 라우팅        next.config.ts + /ko 세그먼트
hreflang           §13 공통 완료 조건에 추가
번역               마케팅 카피 34개 라우트 + 제품 UI 문자열
KO/EN 전환 UI      §12.1 nav 우측 (동작하는 것만 만든다 — §14.3)
```

**활성화되는 설계도 절**

```
§7.4   :lang(ko) 오버라이드 전문
§13    hreflang · KO 스크린샷을 공통 완료 조건에 복원
§21.3  증거 요구를 "7 뷰포트 × KO/EN × reduced-motion" 으로 복원
§20    검증 뷰포트에 KO 축 추가
```

**G-D와 무관하게 W0에서 고치는 것** — 현행 `text-wrap: balance` 3곳과 `word-break: keep-all` 4곳이 언어 게이트 없이 걸려 있다. `:lang(en)` / `:lang(ko)`로 감싼다.

---

### G-E · `SourceRef`에 rotation / cropbox 추가 → **가능. 협의 진행**

결정일 2026-08-07.

**전제** — 백엔드 계약 변경이므로 `CONTRIBUTING.md`의 절차를 따른다: ADR 작성 → 정본 JSON Schema 변경 → 클라이언트 타입 → 회귀 테스트.

**필요한 필드**

```
SourceRef.page_rotation     0 | 90 | 180 | 270
SourceRef.cropbox           원본 좌표계의 CropBox / MediaBox 오프셋
```

**해소되는 것** — 설계도 §14.4의 7단계 좌표 파이프라인이 온전히 구현 가능해진다. 회전·CropBox 문서에서도 스레드가 정확해지고, IoU ≥0.95 골든 테스트 20건이 성립한다. §2.4 전략의 두 번째 조각("값을 클릭하면 원문 스팬이 보인다")이 살아난다.

**W4 착수 전까지 스키마가 확정되지 않으면** 설계도 §4.4에 따라 해당 문서는 `threads=[]`로 두고 좌표 없는 선을 그리지 않는다.

---

## 설계도 개정 사항

머지 이후 조사에서 드러난 오류다. 다음 설계도 개정 시 본문에 반영한다. **그 전까지는 이 절이 설계도보다 우선한다.**

### A-01 · §22 폰트 예산 ≤90KB는 한국어에서 달성 불가능

실측이다.

```
Pretendard Variable 전체            2.06 MB
KS X 1001 서브셋 (정적 1웨이트)      267 KB
동적 서브셋 청크 1개                 ~35 KB
  → 한국어 문장 하나가 5–15개 청크를 끌어온다
```

**교체 예산**

```
/en                    ≤ 60 KB      하드 예산. 라틴 가변 서브셋 1개
/ko 마케팅 첫 화면       ≤ 180 KB     빌드타임 서브셋 기준
/ko 제품 UI 첫 화면      ≤ 250 KB     unicode-range 청크 기준
/ko 정상 상태           ≤ 400 KB
```

### A-02 · 한글에 가변 축을 쓰면 예산이 두 배가 된다

```
음절당 바이트   정적 1웨이트 청크    ~70–100 B
              가변(wght) 청크     ~150–200 B
```

**결정** — **가변 축은 라틴에만 둔다.** 한글은 빌드타임에 `fonttools varLib.instancer`로 **정적 2웨이트(400 / 600)**를 뽑아 쓴다. §7.2 B안의 "비정수 웨이트 스톱"은 라틴 축에만 적용된다.

### A-03 · `next/font`는 `unicode-range`를 지원하지 않는다

2023-03부터 열려 있는 이슈다(vercel/next.js #47309). `declarations`로 우회 가능하나 그 호출이 만드는 **모든** `@font-face`에 동일하게 적용되어 청크별 지정이 불가능하다.

**결정**

```
라틴 서체    next/font/local 유지 (adjustFontFallback 이득이 있다)
한글 서체    src/app/ 의 전역 CSS 에 @font-face 직접 작성
            파일은 public/fonts/ 에 두고 critical 청크 1–2개만 <link rel=preload>
선언 위치    한글 서체는 /ko 레이아웃 세그먼트 안에서만 선언한다
            (EN 방문자가 한글 폰트를 preload 하지 않도록)
```

설계도 §7.2의 "어느 쪽이든 `next/font/local`로 self-host"는 라틴에만 해당한다.

### A-04 · 한글 광학 크기 보정 방식

`size-adjust`는 같은 페이스 안의 라틴 글리프까지 함께 스케일하고 Safari 17+를 요구한다. **`:lang(ko)`의 `--fs-scale` 토큰 방식을 쓴다**(설계도 §7.4가 이미 그렇게 쓰여 있다). 시작값 `1.06`, `line-height: 1.65`, `word-break: keep-all`.

### A-05 · 서체 지정 교체

설계도 §7.1의 서체 표에서 `Pretendard Variable` · `Inter` · `Newsreader` 지정을 **`Wanted Sans Variable` 단일 패밀리**로 교체한다. `--st-serif`(미정의 변수)는 에디토리얼 세리프를 도입하지 않기로 하고 참조 5곳을 제거한다.

`JetBrains Mono`(`--font-mono`)는 유지한다.

---

## 아직 열려 있는 것

```
□ 상표 clearance 결과                     G-A 를 되돌릴 수 있다
□ 액센트 색상각 확정                       §6.2 — 시안 3안에서 결정
□ 사진 예외를 열 것인가                     §15.4 — 커미션 사진 1–3장
□ 검증 뷰포트 4폭 / 7종 통일                §20 · AGENTS.md 와 불일치
□ Hero 카피 3방향 중 선택                   §3.3 — §25.1 블라인드 테스트로
□ 정적 시안 승인                           Hero · Navigation · Proof · Live Compile
                                         승인 전 구현 코드 작성 금지 (§24.1)
```

**정적 시안 승인이 없으면 W1 이후로 넘어가지 않는다.** W0는 시안과 무관한 기반 작업이므로 지금 착수 가능하다.
