# TAVONEL UI 적용·확장 기획안

**대상 저장소:** `0ssol1620-byte/ai-knowledge-compiler`  
**기획 범위:** 기존 제품의 진실성·접근성·성능 계약을 보존하면서, 최근에 설계한 **컴파일 과정의 인터랙티브 서사**와 **제품 탐색 경험**을 실제 TAVONEL 제품에 흡수한다.

## 1. 결론

이 저장소는 단순한 랜딩 페이지가 아니라, 이미 마케팅·데모·처리 워크스페이스·지식 베이스·관리 화면까지 이어지는 **실제 제품 구조**를 갖추고 있습니다. 따라서 방금 만든 독립 랜딩 페이지의 화면을 그대로 옮기는 방식은 권장하지 않습니다. 특히 올리브·라임 토큰, 생성 이미지, 추정 수치, 추상 궤도 그래픽은 현재의 TAVONEL 디자인 권한 및 제품 증거 원칙과 충돌할 수 있습니다.[1] [2]

> 적용해야 할 것은 **색상과 장식**이 아니라, 사용자가 “원본 → 구조화 → 검증 → 지식”의 변환을 스크롤과 상호작용으로 이해하게 하는 **정보 구조와 인터랙션 모델**입니다.

가장 먼저 `/`의 기존 `tv-transformation` 챕터를 **실제 DART fixture를 기반으로 한 스크롤형 Compiler Journey**로 재구성합니다. 그다음 `/workspace`의 처리 화면에서 동일한 언어를 사용해, 마케팅에서 약속한 변환이 제품 안에서 어떻게 확인·검토·내보내기로 이어지는지 연결합니다. 제품 카드는 새로 꾸미는 카드월이 아니라, 기존 `/product/convert`, `/product/verify`, `/product/knowledge`로 연결되는 명확한 세 개의 진입점으로 구성합니다.[3] [4]

| 적용 원칙 | 기획 결정 |
| --- | --- |
| 브랜드 형태 | **Facing Pages**: 왼쪽은 원문, 오른쪽은 구조화된 결과, 중앙은 실제 근거 연결만 표시 |
| 재질 체계 | 마케팅은 PAPER, 실제 처리·검토 화면은 INSTRUMENT로 구분 |
| 시각 자료 | 생성 이미지 대신 현재 DART fixture, 실제 제품 컴포넌트, 기존 glyph를 사용 |
| 상태 표현 | 가짜 진행률·과장된 수치 없이 `완료 · 처리 중 · 보류 · 검토 필요`만 실제 데이터로 표시 |
| 모션 | 스크롤 단계 전환·소스 선택·호버 피드백만 제공하고, reduced motion에서도 같은 정보 유지 |

## 2. 현재 제품에서 활용할 기반

홈은 `HeroComp`, `TrialRunFilm`, 공개 DART proof demo, 변환 챕터, 보안·사용 사례·마감 CTA로 이미 구성되어 있습니다. 특히 기존 `ChapterVisual`은 동일한 공개 filing fixture에서 페이지·블록·엔터티·출력 목적지를 렌더링하므로, 새 인터랙티브 경험의 가장 안전한 데이터 기반입니다. 새 화면은 이 증거를 대체하지 않고, 현재 `tv-transformation`의 네 개 정적 챕터를 더 이해하기 쉬운 상태 전환 경험으로 승격해야 합니다.[3]

제품 측면에서는 `/workspace`가 가장 가치가 높습니다. 이 화면은 이미 처리 단계, 원본 페이지 레일, `SourceViewer`, 결과 `MarkdownWorkspace`, 검토 드로어, 내보내기 대화상자를 가지고 있습니다. 따라서 별도의 “대시보드형 컴파일러”를 새로 만들지 않고, 이 화면에 **원문·결과·검토의 관계를 더 명확히 보여주는 컴파일 상태 언어**를 적용하는 것이 맞습니다.[5]

전역 레이아웃은 토큰 레이어를 먼저 불러오고 마케팅과 인증된 앱 셸을 분리합니다. UI는 `src/styles/tokens.css`를 단일 토큰 원천으로 유지하고, 새 CSS는 `@layer` 안에 추가해야 합니다. 인증 앱에 마케팅용 대형 모션이나 무거운 이미지 의존성을 끌고 들어가지 않는 것이 초기 JS 예산과 셸 분리 원칙에도 부합합니다.[6]

## 3. 목표 사용자 흐름

새 UI의 핵심은 방문자가 하나의 구체적 문서에서 시작해, 결과가 왜 신뢰할 수 있는지를 단계적으로 확인하도록 만드는 것입니다. 각 단계는 클릭·키보드·스크롤 중 어느 방식으로도 전환되며, 소스와 결과의 연결은 실제 좌표가 있을 때만 나타납니다. 좌표가 없으면 선을 장식으로 그리지 않고, 해당 항목을 “원문 위치 미연결” 상태로 명시합니다.[2]

| 단계 | 방문자에게 보여줄 질문 | 실제 화면 재료 | 연결되는 제품 행동 |
| --- | --- | --- | --- |
| 1. Source | “무엇을 읽고 있나?” | DART 원본 페이지·블록·표 | `/intake` 또는 Hero drop zone으로 문서 제공 |
| 2. Structure | “무엇이 문서 구조로 확인됐나?” | heading, paragraph, table의 typed block | `SourceViewer`에서 블록 선택 |
| 3. Evidence | “이 결과는 어디서 왔나?” | source line, page, bbox, review 상태 | `ReviewDrawer`에서 근거로 이동 |
| 4. Knowledge | “어디에 재사용할 수 있나?” | notes, entities, relations, export package | `/workspace`, `/app/knowledge-bases`, export 흐름 |

## 4. 첫 번째 적용: 홈페이지 Compiler Journey

### 배치와 구성

`TrialRunFilm` 뒤, 현재 `tv-transformation`이 위치한 곳을 **Compiler Journey**로 교체합니다. Hero의 승인된 Frame 구성과 DART proof demo는 보존합니다. Journey는 데스크톱에서 좌측의 원문면과 우측의 결과면을 유지하고, 중앙 spine에는 선택된 단계의 실제 근거 연결만 표시합니다. 모바일에서는 원문 → 결과 → 단계 설명 순으로 한 단계씩 쌓아, 가로 축소로 인해 소스가 사라지지 않게 합니다.

단계 레일은 `button` 기반 탭 패턴으로 구현합니다. `IntersectionObserver`는 스크롤로 현재 단계를 갱신하되, 사용자가 버튼을 클릭하거나 키보드로 포커스를 이동해도 같은 상태를 만들 수 있어야 합니다. 단계 변화는 140–280ms 범위의 opacity·transform 전환만 사용하고, `prefers-reduced-motion`에서는 동일한 상태를 즉시 교체합니다.[1] [2]

| 컴포넌트 | 역할 | 데이터·상태 계약 |
| --- | --- | --- |
| `CompilerJourney` | 섹션 전체와 활성 단계 소유 | `activeStep`, keyboard navigation, reduced-motion 분기 |
| `CompilerStageRail` | 네 단계의 설명·선택·진입점 | `aria-current`, 실제 route link, 허위 metric 금지 |
| `FacingEvidencePanel` | 원문 좌측과 결과 우측 렌더 | `DART_PUBLIC_FIXTURE`, 실제 `sourceLine`, `threads=[]` 허용 |
| `CompilerStageVisual` | 단계별로 달라지는 source/result 표현 | 현재 `ChapterVisual`의 fixture 표현을 재사용·분리 |
| `ProductEntryStrip` | 세 제품 진입점 | `/product/convert`, `/product/verify`, `/product/knowledge`로만 연결 |

### 제품 카드 호버 원칙

제품 카드는 기존 공개 product route를 가리키는 세 개의 얕은 진입점입니다. 호버 시 카드는 1–2px 상승 또는 배경 명도 변화, 좌측 원문 crop의 미세한 확대, 우측 화살표 이동만 허용합니다. 기본 그림자·무의미한 숫자·자동 회전·카드 안의 두 번째 카드 구조는 사용하지 않습니다. 키보드 포커스에도 호버와 같은 정보가 나타나야 하며, 카드 전체가 하나의 목적지를 가진 링크여야 합니다.

| 카드 | 목적지 | 방문자 가치 | 호버에서 드러나는 실제 정보 |
| --- | --- | --- | --- |
| Convert | `/product/convert` | 문서를 구조화된 블록으로 읽기 | 원문 block type → typed block |
| Verify | `/product/verify` | 결과를 원문 근거로 점검하기 | result → page · block · bbox |
| Knowledge | `/product/knowledge` | 검증된 구조를 재사용하기 | blocks → notes · entities · relations |

## 5. 두 번째 적용: 처리 워크스페이스의 Calm Precision

`/workspace`는 새 브랜드 언어를 제품에 증명하는 첫 번째 장소입니다. 현재 구조를 유지하되, 상단 pipeline과 중앙 3패널의 역할을 더 명확히 나눕니다. 기존의 `SourceViewer`는 VERSO, `MarkdownWorkspace`는 RECTO, `ReviewDrawer`는 신뢰 경계를 설명하는 검토면이 됩니다. 이때 마케팅의 큰 카피·대형 stage card·강한 배경 전환을 그대로 들여오지 않습니다.[5]

우선순위는 다음과 같습니다. 첫째, pipeline stage에 실제 상태와 명확한 blocked/review 상태를 추가합니다. 둘째, 원문 블록을 선택하면 결과 블록과 검토 항목이 함께 강조되도록 source-linked focus를 통합합니다. 셋째, 모바일 탭을 단순한 컨테이너 전환이 아니라 “현재 근거 → 결과 → 검토”라는 문맥 보존 흐름으로 다듬습니다. 데모 fixture에서는 “SAMPLE · Demo snapshot” 표기를 유지하고, 라이브 세션에서는 실제 SSE event만으로 상태를 갱신합니다.[5]

## 6. 구현 순서와 PR 경계

현재 로컬 작업 트리는 `integration/g0-consolidation` 브랜치이며 `apps/web/next-env.d.ts`에 미커밋 변경이 있습니다. UI 작업은 이 변경을 건드리지 않는 별도 브랜치에서 시작하고, reset·checkout·대규모 CSS 재작성 없이 작은 PR로 병합하는 것을 전제로 합니다.

| 순서 | PR 단위 | 변경 범위 | 완료 기준 |
| --- | --- | --- | --- |
| 0 | Static composition sign-off | Navigation·Proof·Live Compile의 승인 시안 확정 | 승인 기록 없이는 해당 표면 구현을 시작하지 않음 |
| 1 | `feat(web): source-backed compiler journey` | `/`, `MarketingLanding`, 신규 Journey 컴포넌트·스타일 | 기존 DART proof와 hero를 유지하며 4단계가 실제 fixture로 전환 |
| 2 | `feat(web): product entry interactions` | product entry strip와 product route 연결 | hover·focus·touch가 같은 목적지와 정보를 제공 |
| 3 | `feat(web): workspace evidence focus` | `/workspace`, source/result/review 상태 연동 | 선택한 근거가 세 표면에서 일관되게 강조 |
| 4 | `test(web): visual and interaction evidence` | Playwright, a11y, visual baseline, reduced motion | 7개 폭·KO/EN·reduced motion과 기존 빌드 게이트 통과 |

## 7. 승인·검증 기준

현재 디자인 결정 기록에는 Navigation, Proof, Live Compile의 정적 시안 승인이 아직 열려 있다고 명시되어 있습니다. 따라서 Journey의 최종 배치·섹션 간 하드 컷·Proof와의 경계는 코드 작성 전에 정적 시안으로 먼저 확정해야 합니다. 반면 승인된 Hero Frame, 근거 우선 카피 방향, TAVONEL 제품명, 255° 브랜드 색상각, 3D 제거 원칙은 유지합니다.[2]

검증은 저장소의 표준을 그대로 따릅니다. `lint`, `typecheck`, unit test, interaction check, e2e, production build, Lighthouse를 실행하고, 1920·1440·1280·1024·768·390·360px에서 한국어·영어·reduced motion을 확인합니다. 마케팅은 실제 공개 proof 또는 명시적 sample fixture만 사용하고, 제품은 실제 event·source reference가 없는 상태를 성공처럼 보이게 만들지 않습니다.[1] [4]

## 8. 바로 다음 의사결정

실행을 시작하기 전에 아래 세 가지를 확정하면 됩니다. 첫째, 첫 구현 범위를 **홈의 Journey + 세 제품 진입점**으로 한정할지 결정합니다. 둘째, Journey의 실제 fixture를 DART 하나로 유지할지, SEC fixture까지 병렬로 제공할지 선택합니다. 셋째, Navigation·Proof·Live Compile의 정적 시안을 승인한 뒤 첫 PR을 시작합니다. 이 순서라면 기존 제품의 증거 기반을 훼손하지 않고, 방금 설계한 인터랙티브 경험을 TAVONEL의 실제 UI 체계로 발전시킬 수 있습니다.

## References

[1]: https://github.com/0ssol1620-byte/ai-knowledge-compiler/blob/bd0fb33/AGENTS.md "TAVONEL Agent Instructions"
[2]: https://github.com/0ssol1620-byte/ai-knowledge-compiler/blob/bd0fb33/design-system/tavonel/decision.md "TAVONEL design decisions"
[3]: https://github.com/0ssol1620-byte/ai-knowledge-compiler/blob/bd0fb33/apps/web/src/components/marketing-landing.tsx "Current marketing landing composition"
[4]: https://github.com/0ssol1620-byte/ai-knowledge-compiler/blob/bd0fb33/PAGE_MANIFEST.yml "Route and evidence manifest"
[5]: https://github.com/0ssol1620-byte/ai-knowledge-compiler/blob/bd0fb33/apps/web/src/components/workspace/processing-workspace.tsx "Processing workspace"
[6]: https://github.com/0ssol1620-byte/ai-knowledge-compiler/blob/bd0fb33/apps/web/src/app/layout.tsx "Root layout and style order"
