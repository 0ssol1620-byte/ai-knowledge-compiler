# G-C2 · CAUSAL CINEMATIC RENDERER — **초안. 승인되지 않음**

작성일 2026-08-29. 작성자: 구현 세션. **승인란은 비어 있다.**

이 문서는 `decision.md`에 들어갈 결정의 초안이다. 승인 전까지 이 문서는
아무것도 확정하지 않으며, 여기 적힌 어떤 항목도 구현 근거가 되지 못한다.

---

## 왜 이 결정이 필요한가

`TAVONEL_CINEMATIC_COMPILATION_REPLAY_MASTER_SPEC_v2.0_FINAL_KO_2026-08-23.md`
§0.3이 WebGL/3D를 이 결정에 걸어놓았다. 원문:

> 현재 `design-system/tavonel/decision.md`의 G-C는 TIER 1 3D를 폐기하고 Hero를
> dropzone으로 확정했다. 이 결정을 무시한 채 `three`를 다시 설치하면 안 된다.
>
> **G-C2가 승인되지 않으면 DOM/SVG/Canvas 2.5D baseline만 구현한다.**
> 그 baseline만으로도 전체 서사는 완결되어야 한다.

즉 3D를 켜는 조건은 "누가 3D를 원한다"가 아니라 **이 결정문이 승인 기록과 함께
존재하는가**이다. 구현 세션이 스스로 승인할 수 없다 (`CLAUDE.md` §Self-approval:
"The session that implements does not approve its own result").

## G-C와의 관계

G-C(2026-08-07)는 폐기되지 않는다. G-C2는 G-C의 **폐기 목록을 그대로 유지한 채**
좁은 예외를 하나 연다.

**G-C2가 승인되어도 계속 폐기 상태인 것** — §0.3이 명시한 목록 그대로:

```
decorative WebGL hero
idle orbit
pointer parallax
무한 particle background
제품 사실과 무관한 3D spectacle
```

`structara-webgl-scene.tsx`와 그 무한 패럴랙스는 §10.4 위반으로 제거됐고,
G-C2는 그것을 되살리지 않는다.

**새로 허용하는 범위** — §0.3 원문 그대로:

```
ProductEvent/WorldProjection에 종속된 causal visualization
실행 중이거나 replay되는 실제 semantic event만 motion을 발생
idle 상태에서 render freeze
DOM/SVG로 동일 의미를 제공하는 필수 baseline
isolated dynamic import
performance/adaptive-quality/reduced-motion gate
```

한 줄로: **motion의 원인이 제품 이벤트일 때만 3D가 존재한다.** 마우스가 움직여서
움직이는 것, 시간이 흘러서 움직이는 것, 예뻐서 움직이는 것은 전부 해당 없음이다.

## 승인 시 따라오는 의무

이 결정이 승인되면 아래는 선택이 아니라 완료 조건이다.

**1. baseline 우선.** DOM/SVG/Canvas 2.5D 경로가 먼저 완결되어야 한다. 3D는
그 위의 enhancement이고, 3D가 없어도 서사가 끝나야 한다 (§0.3). 08-02 v3
마스터플랜 §49의 파이프라인도 같은 순서다 — `Static storyboard → Blender → GLB
→ glTF Transform → R3F → poster/fallback`, 그리고 **"Hero assets only after
approved static."**

**2. 정적 시안 게이트가 먼저다.** v3 §59는 핵심 장면마다 1440·390 두 폭에서
동일 copy/data로 3 directions를 요구하고, `decision.md` 말미의 현행 규칙도
같은 말을 한다 — *"남은 정적 시안(Navigation · Proof · Live Compile) 승인 없이
해당 웨이브에 착수하지 않는다"*. Hero는 G-F로 승인됐으므로, 3D를 얹으려면
얹을 장면의 정적 시안이 먼저 승인돼 있어야 한다.

**3. §22 스크립트 예산이 움직인다.** `CLAUDE.md`가 이미 이 경우를 규정해뒀다:
예산은 **새 측정에서 재도출**되고, 그 재도출을 승인한 결정과 함께 기록된다.
빌드를 통과시키려고 올리는 것과는 다른 행위이며, **커밋 메시지가 둘 중
어느 쪽인지 말해야 한다.** 현재 홈페이지 First Load JS는 183 kB이고,
`three` + R3F는 여기에 수십 kB 단위로 얹힌다.

**4. 무료 의존성만.** `CLAUDE.md`: *"No paid 3D dependency. No GetLayers or
Spline scene as a required dependency."* `three` / `@react-three/fiber` /
`@react-three/drei`는 MIT다. 이 조항은 미학이 아니라 라이선스 조항이므로
시각 규칙 면제와 별개로 유지한다.

**5. GLB 예산과 폴백.** v3 §28.7 — poster LCP · GLB ≤1.5MB · mobile static ·
offscreen pause · DPR cap · no infinite loop. v5 마스터플랜 §2171·§2307도
mobile / reduced-motion / **no-WebGL** / slow-network 폴백을 게이트로 잡는다.

**6. Blender master가 없으면 GLB 경로는 못 연다.** §49의 파이프라인은 Blender를
전제한다. 이 세션은 Blender를 돌릴 수 없다. 따라서 승인 후에도 실제로 착수
가능한 것은 **procedural R3F**(GLB 없이 코드로 생성하는 지오메트리)뿐이고,
GLB 경로는 별도 인력·도구가 붙어야 한다.

## 승인하지 않을 경우

아무것도 막히지 않는다. §0.3이 요구하는 baseline은 이미 서 있다 — 56초 리플레이는
DOM + CSS로 돌고(§539: "실제 3D travel 없음. 2.5D perspective 0.8° 이하",
"WebGL 미마운트"), boundary/scale 도형은 SVG다. **현재 페이지는 3D 없이 완결된
상태이며, 그것이 §0.3이 요구한 바로 그 조건이다.**

## 승인란

```
결정: [ ] 승인   [ ] 반려   [ ] 보류
결정일:
결정자:
적용 범위(장면):
정적 시안 승인 여부:
§22 예산 재측정 근거:
```

승인되면 이 파일의 내용을 `decision.md`에 `### G-C2 · CAUSAL CINEMATIC
RENDERER` 항목으로 옮기고, 이 초안 파일은 삭제한다.
