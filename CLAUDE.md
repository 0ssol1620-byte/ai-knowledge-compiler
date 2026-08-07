# 프론트엔드 규칙

이 저장소의 에이전트 계약은 AGENTS.md 다. 먼저 읽는다.
시각 설계의 단일 진실은 design-system/folynta/DESIGN_MASTER_V3.md 다.
설계도와 design-system/folynta/decision.md 가 충돌하면 decision.md 가 이긴다.
이 파일과 충돌하는 제안은 거절한다.

## 절대 규칙

- 모든 장면은 FacingPages(좌 원문 / 우 산출물)의 변주다. 좌우를 바꾸지 않는다.
- 좌표 없는 장식 스레드를 그리지 않는다. 좌표가 없으면 threads=[] 로 둔다.
- 깊이는 포커스 링 · 호버 · 오버레이 세 곳에만. 카드·섹션에 그림자를 넣지 않는다.
- 보더는 알파다. 하드코딩 헥스 규칙선을 쓰지 않는다 (--rule-\* 토큰).
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

## 3D

TIER 1 3D 는 폐기됐다 (decision.md G-C). Hero 는 드롭존이다.
three · @react-three/fiber · @react-three/drei 는 W0 에서 제거했다. 다시 넣지 않는다.
설계도 §9.3 (12종 문서 실루엣 · GLB 파이프라인) 과 W8 은 사문화됐다.
WebGL 이 필요해 보이면 멈추고 물어본다.

## 새 의존성

외부 UI 컴포넌트는 shadcn/ui 하나다. 가상화는 react-virtuoso.
아이콘은 @phosphor-icons/react. 애니메이션 라이브러리를 추가하지 않는다.
추가 설치가 필요하면 먼저 이유를 design-system/folynta/decision.md 에 적고 승인을 받는다.

## 게이트

W-1 결정 5건이 decision.md 에 없으면 W0 에 착수하지 않는다.
Hero·Navigation·Proof·Live Compile 은 정적 시안 3안 승인 전 구현 코드를 쓰지 않는다.

## 검사

```
pnpm --filter @akc/web interactions:check   §14.3 어포던스 무결성
pnpm --filter @akc/web exec impeccable detect src   §25.3 기계 검사 기반
pnpm --filter @akc/web test:e2e             동작 + 7뷰포트 증거
pnpm --filter @akc/web lighthouse           §22 성능 예산
```

## 자기 승인 금지

구현한 세션은 자신의 결과를 승인하지 않는다.
G-1(블라인드 카테고리 테스트)과 G-2(강제 비교 판정)는 사람만 판정한다.
