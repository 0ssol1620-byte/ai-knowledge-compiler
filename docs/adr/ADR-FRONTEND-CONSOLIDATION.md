# ADR-FRONTEND-CONSOLIDATION: 프론트엔드 정본 통합 — apps/web(A) vs tavonel-blank-slate(B)

- Status: Proposed
- Date: 2026-08-23
- Decides: 두 개의 Next.js 16 프론트엔드 자산 중 상용 서비스의 정본(canonical) 방향과 이행 순서
- Scope: 문서 전용. 이 ADR 자체는 코드를 변경하지 않는다.
- Evidence basis: 아래 §0 기재 경로·수치는 2026-08-23 로컬 재현값이다.

## 0. 증거 헤더 (Evidence header)

| 항목 | 값 |
| --- | --- |
| 비교 시각 | 2026-08-23 (KST) |
| 정본 저장소(A) | `D:/CodexProjects/ai-knowledge-compiler-g0`, branch `integration/g0-consolidation`, HEAD `9e9d69a` |
| 참조 앱(B) | `C:/Users/yspow/Documents/Codex/2026-08-20/tavonel-ui-tavonel-final-knowledge-compiler-3/outputs/tavonel-blank-slate` (git 관리 밖 Codex 산출물) |
| 청사진 | `docs/masterplan/AI_Knowledge_Compiler_Enterprise_UI_UX_Masterplan_FINAL_KO_2026-07-30.md` §34(Phase 1/2 로드맵), §35(Release gates) |
| B 판독 문서 | B:`AUTH_BILLING_IMPLEMENTATION_2026-08-23.md`(57행), B:`docs/FINAL_WEB_DELIVERY_MATRIX.md`(35행) |

재현 명령 (숫자 검증용):

```bash
# A 라우트/컴포넌트 수
find apps/web/src/app -name 'page.tsx' | wc -l          # 37
find apps/web/src/app -name 'layout.tsx' | wc -l        # 3
find apps/web/src/app/api -name 'route.ts' | wc -l      # 2
find apps/web/src/components -name '*.tsx' ! -name '*.test.*' | wc -l   # 95
find apps/web/src/lib -maxdepth 1 -name '*.ts' ! -name '*.test.*' | wc -l # 50
find apps/web/src \( -name '*.test.ts' -o -name '*.test.tsx' \) | wc -l  # 65
cd apps/web && pnpm vitest run                          # 단위 테스트 (§2.1 참조)
# B 라우트 수
find "$B/src/app" -name 'page.tsx' | wc -l              # 25
find "$B/src/app/api" -name 'route.ts' | wc -l          # 3
```

## 1. 배경 (Context)

동일 제품(TAVONEL / AI Knowledge Compiler)의 프론트엔드가 두 벌 존재한다.

- **앱 A** (`apps/web`, `@akc/web`): pnpm 모노레포 안의 실제 제품 서피스. `services/api`(Python, 모듈 77개)와 `@akc/contracts` 워크스페이스 계약으로 연결되어 있고, 인증 후 앱(월드 프로젝션·SSE 라이브 이벤트·업로드·리뷰·지식·관리자·계정/과금 UI)을 구현한다. 과금 UI는 백엔드 `/v1/billing/*`를 호출하지만 백엔드 결제 프로바이더가 `fake`(개발용)뿐이라 실결제는 불가하다(`services/api/src/akc_api/payments.py` L146–208).
- **앱 B** (`tavonel-blank-slate`): 상용 셸. Clerk 인증과 Stripe 구독(checkout·portal·webhook 서명검증)이 실구현되어 있고, 마케팅 28 라우트와 Health Scan·Project Atlas(`sampleMode` 픽스처) 샘플을 갖는다. 그러나 백엔드 호출은 결제 버튼 하나뿐(`src/components/BillingButton.tsx` — B 전체에서 유일한 `fetch()`)이고, 단위 테스트가 없다(Playwright 기반 `verify:*` 스크립트만 존재).

두 자산을 한 정본으로 수렴시키는 방향을 결정해야 한다.

## 2. 인벤토리

### 2.1 앱 A — `apps/web` (제품 정본 후보)

Next 16.2.12 · React 19.2.8 · `@akc/contracts workspace:*` · zod 4 · TanStack Query 5 · zustand 5 · `@microsoft/fetch-event-source`.

| 축 | 내용 | 증거 |
| --- | --- | --- |
| 라우트 | page 37 · layout 3 · api route 2(`/api/health`, `/api/locale`). 공개: `/`, `/home`, `/film`, `/benchmarks`, `/integrity`, `/notices`, 디자인/리뷰 페이지. 인증: `/login` `/signup` `/forgot-password` `/verify-email` `/sso`. 앱: `/workspace` `/app/world/*`(entity ask/change/source), `/projects` `/intake` `/review` `/documents/[id]/[view]` `/knowledge-bases` `/analytics` `/activity`. 계정/운영: `/account` `/billing` `/settings` `/usage` `/admin` `/api-workflows` `/onboarding` | `apps/web/src/app/**` |
| 컴포넌트 | 95개(비테스트 .tsx): `authenticated-shell`(424행), `auth-page`(register/login/OIDC 분기), `billing-management`(220행), `account-page`, `world`, `processing-scene-workbench`, `review-studio`, `knowledge-studio`, `benchmark-lab`, `webhook-management`, `dispatch-dlq-panel`, `team-management` 등 | `apps/web/src/components/**` |
| 계약(lib) | 50개 모듈: `api-client.ts`(zod eventEnvelope, SSE `streamJob` 재연속 backoff), `operations-contracts.ts`, `product-event.ts`+`world-projection.ts`(데모 픽스처와 라이브 SSE가 **같은 reducer** `reduceProductEvent`로 수렴 — 마케팅 표시와 제품 표시의 불일치가 구조적으로 차단됨), `event-reducer.ts`, `session.ts`(HttpOnly 쿠키 세션), `upload-policy.ts`, `quality-evidence.ts`, `claims.ts` | `apps/web/src/lib/**` |
| 인증 계약 | 백엔드 자체 세션(HttpOnly 쿠키): `/v1/auth/register·login·logout·session·verify-email·resend-verification`, OIDC 확장점 `/v1/auth/oidc/authorize·bind/authorize·callback`, MFA `/v1/auth/mfa/*` | `services/api/src/akc_api/auth_api.py` L252–697 |
| 과금 계약 | UI → `/v1/billing/credit-packs`, `/v1/billing/payments`, `/v1/billing/checkouts`. 백엔드 프로바이더: `fake`(dev/test 전용) 또는 `merchant`(미구성 시 `payment_provider_unavailable`) → **실결제 미연결** | `components/billing-management.tsx`; `akc_api/payments.py` |
| 테스트 | 단위 65파일(vitest), E2E 14스펙 × 4 playwright 설정(기본/live/matrix/reuse), axe 접근성, LHCI | `pnpm vitest run`, `playwright.*.config.ts` |
| 빌트인 게이트 | `lint --max-warnings=0`, `typecheck`, `interactions:check`(버튼 계약), `blueprint:check`, `claims:check`(증표 없는 수치 금지) | `apps/web/package.json` scripts |
| 문서 증표 | `docs/UI_IMPLEMENTATION_MATRIX.md`: EPIC-UI-001~013 모두 `LOCAL-CLOSED`(마케팅 셸→Processing Studio→Enterprise까지). `docs/FRONTEND_EVIDENCE_HANDOFF.md`: 공개 클레임 팩 `docs/evidence/folynta-public-claims-pack.json`(approved/conditional/withheld 상태 관리) | 해당 문서 |

단위 테스트 현황: 저장소 내 증표 `docs/coordination/G0_CONSOLIDATION_2026-08-22.md` L99 — "**web vitest | 65 files / 364 tests / 0 failed**". 부록: 본 ADR 작성일(2026-08-23) 본 호스트에서 `pnpm vitest run` 로컬 재현을 시도했으나 vitest threads worker 기동 타임아웃("Timeout waiting for worker to respond")으로 미완료 — 자원 제약 환경 이슈이며, 재현은 §6 Step 0 게이트에서 수행한다.

### 2.2 앱 B — `tavonel-blank-slate` (상용 셸)

Next 16.3.1 · `@clerk/nextjs ^7.8.0` · `stripe ^22.5.0` · Tailwind 4 · three/R3F/drei/gsap.

| 축 | 내용 | 증거 |
| --- | --- | --- |
| 라우트 | page 25 + api 3 = 28. 공개: `/` `/pricing` `/product{,/personal,/team,/enterprise}` `/health-scan` `/evidence{,/sec,/sec-observatory}` `/research` `/developers` `/docs` `/security` `/trust` `/terms` `/privacy` `/asset-lab` `/app/worlds/[worldId]`. Clerk: `/sign-in/[[...sign-in]]` `/sign-up/[[...sign-up]]`. 보호: `/workspace` `/account` `/api/billing/*`. Webhook: `/api/webhooks/stripe` | `src/app/**`, AUTH 문서 Routes 표 |
| 인증 구현 | `src/proxy.ts`: `clerkMiddleware` + `createRouteMatcher(["/workspace(.*)","/account(.*)","/api/billing(.*)"])` 보호. **키 미구성 시 fail-closed** — 보호 라우트는 `/sign-in?setup=required` 리다이렉트, UI가 계정을 시뮬레이션하지 않음 | `src/proxy.ts` |
| Stripe 구현 | `lib/stripe.ts`(server-only 싱글턴), `lib/service-config.ts`(서버 전용 Price allowlist, `sk_live_` 키는 `TAVONEL_LIVE_BILLING_APPROVED=true` 없으면 거부). checkout: 동일오리진 검사 + Clerk 인증 + plan allowlist + ToS consent collection. webhook: raw body + `Stripe-Signature` 검증 후 Clerk `privateMetadata`에 구독 상태 영속화 | `src/app/api/billing/{checkout,portal}/route.ts`, `src/app/api/webhooks/stripe/route.ts`, service-boundary JSON 15 checks PASS |
| 제품 샘플 | Project Atlas: `experience/fixtures/project-atlas.ts`(`sampleMode: true`, worldStateId `SAMPLE-018292`, 출처 Page 6·Row 4 명시) + `AppExperience`(61행) 렌더. Health Scan(27행) 등 10개 experience | `src/experiences/**` |
| 백엔드 호출 | **결제 버튼 1곳뿐** (`BillingButton.tsx` → `/api/billing/*`) — 나머지 전부 픽스처/정적 | B 전체 `fetch()` 검색 결과 |
| 테스트 | 단위 테스트 0. `verify:contracts·motion·visual·routes·app·service·quality` Playwright 스크립트 12개 | `scripts/*.mjs` |
| 증표 | `evidence/service/service-boundary-verification.json`(15 checks 전부 true), `runtime-boundary-verification.json`, route/visual/quality/app-quality/motion JSON + 스크린샷 | `evidence/**` |
| 외부 게이트(스스로 선언) | LIVE PROVIDER ACTIVATION / LEGAL REVIEW / FOUNDER VISUAL REVIEW REQUIRED — 라이브 키·도메인·실제 webhook 없음 | AUTH 문서 "Gates that cannot be automated here"; FINAL_WEB_DELIVERY_MATRIX "External gates" 표 |

### 2.3 나란히 놓은 본질

| 질문 | A | B |
| --- | --- | --- |
| 인증 후 무엇이 동작하나 | 실제 제품(업로드→처리→리뷰→내보내기, 월드 프로젝션, 라이브 SSE) | 픽스처 샘플(Project Atlas)과 안내 문구 |
| 돈이 어디서 발생하나 | credit-pack UI만 있고 프로바이더는 fake | Stripe 구독 checkout/portal/webhook 완성(테스트모드 검증까지) |
| 권한(entitlement)의 원천 | `services/api`(credit_policy, free_tier, team_models) | Clerk `privateMetadata`(웹훅이 기록) |
| 회귀 안전망 | 단위 65파일 + e2e 14 + 5종 게이트 스크립트 | 단위 0, verify:* 스모크/비주얼만 |
| 저장소 지배 | 모노레포 안, git 관리, PAGE_MANIFEST 등록 | git 밖 Codex 출력 디렉터리 |

## 3. 결정 지점 (Decision drivers)

- **D1 — 권한 일원화**: "이 사용자가 무엇을 할 수 있는가"의 최종 권한은 이미 `services/api`(플랜·크레딧·팀·유예정책)가 갖는다. 결제는 권한 바로 옆에 있어야 한다.
- **D2 — 회귀 안전망 보존**: A의 65 단위 파일·14 e2e·5 게이트는 유일한 자동 회귀 방어선이다. 어떤 안이든 이 망을 깨면 안 된다.
- **D3 — 저장소 지배(governance)**: 정본 상용 서피스가 버전관리 밖 디렉터리에 있으면 릴리스 추적·리뷰·CI가 불가능하다.
- **D4 — 출시 속도**: B의 결제/마케팅은 "라이브 활성화 체크리스트 8항목"만 남았다. 이 속도 이점을 무시해서는 안 된다.
- **D5 — 청사진 정합성(§34 Phase 1/2, §35 gates)**:
  - §34 Phase 1 *Marketing & Demo*(hero, interactive demo, benchmark preview, security/pricing, Web Vitals·reduced-motion exit) — B가 사실상 완성물.
  - §34 Phase 2 *Core SaaS*(onboarding, upload/preflight, jobs, Processing Studio, result/export; exit: 500페이지 job e2e, SSE reconnect) — A만 갖는다(EPIC-UI-004~010 LOCAL-CLOSED).
  - §35 Gate 3 Trust("no fake progress", evidence reachable) — A는 reducer 불변식으로 강제, B는 `sampleMode` 라벨로 준수. Gate 6 Enterprise(RBAC·audit UI)는 A만 보유.

## 4. 검토한 선택지

### Option 1 — B를 상용 셸(인증/과금/마케팅)로, A를 인증 후 앱 서피스로, API 연결

- **이주 비용**: 최초 비용 최소(도메인/호스트 분리 또는 리버스 프록시, Clerk↔api 세션 브리지, 양방향 내비게이션/로그아웃 연결). 그러나 **영구 비용**: 두 Next 앱을 계속 병행 배치·운영, 디자인 시스템 2벌, IA 2벌, B를 모노레포로 vendoring 해야 하는 추가 이사 비용.
- **위험**: (a) 사용자 여정이 매번 두 앱의 이음새를 통과(§35 Gate 1 브랜드 명료성이 이음새에서 깨짐). (b) **권한 이중화** — 구독 상태는 Clerk metadata, 크레딧/플랜은 services/api. 두 저장소가 영원히 동기화 문제를 안는다. (c) 결제 표면 2개(B 구독 vs A credit-pack)가 사용자에게 혼란. (d) B 절반에는 단위 테스트가 없음.
- **§34/35 정합성**: Phase 1=B, Phase 2=A로 1:1 대응되는 겉모습은 좋으나, Phase 1과 2가 **서로 다른 코드베이스**라는 것이 정합성의 본질을 흔든다. Gate 통과 판정이 앱 경계를 넘어 나뉜다.

### Option 2 — B에 A의 기능을 이식

- **이주 비용**: A의 95 컴포넌트·50 lib 모듈·계약 패키지·react-query/zustand/SSE 스택·65 테스트 파일·e2e 인프라를 B로 전부 옮기는 것 = A를 B 안에서 재건하는 작업. 주 단위 소요, 최고 비용.
- **위험**: 회귀 안전망(D2)을 이사 기간 전체에 걸쳐 상실. Tailwind4/three 스택과 A의 CSS 모듈 스택 충돌. 최악의 선택.
- **§34/35 정합성**: Phase 2 성과를 Phase 1 코드베이스로 옮기는 역방향 이행이라 로드맵 순서와 반대.

### Option 3 — A에 Clerk/Stripe를 이식 (B는 이식 소스로 사용 후 동결)

- **이주 비용**: 중간. 신규 코드 대부분은 B에서 **검증된 구현물을 이식**(stripe.ts, service-config.ts, checkout/portal/webhook 3라우트, proxy 패턴, pricing/policy 카피 ≈ 500~700행)하고, A측 작업은 (i) 인증 viewer 추상화, (ii) Clerk 도입과 services/api 세션 브리지 — **A 백엔드에 이미 OIDC 연합 코드가 존재**(`auth_api.py` L669+, Clerk를 OIDC IdP로 연결하면 신규 백엔드 코드 최소), (iii) webhook→api 권한 동기 엔드포인트 1개, (iv) billing-management에 구독 섹션 추가, (v) 정책/가격 정적 페이지 이식.
- **위험**: Clerk 도입이 A의 인증 플로우를 건드리는 것 자체. 완화: provider flag(`NEXT_PUBLIC_AUTH_PROVIDER=clerk|password`)로 이중 운행, 기존 65 테스트 파일이 회귀를 즉시 잡아줌(D2). fail-closed 패턴은 B에서 이미 검증됨.
- **§34/35 정합성**: Phase 2는 이미 A가 보유. Phase 1 물건(가격·정책·신뢰·데모 카피)을 A로 이식하면 **두 Phase가 하나의 코드베이스·하나의 권한 원천 위에서 연속**된다. Gate 1~6 판정이 단일 서피스에서 가능.

### 비교 요약

| 기준 | Opt 1 (B셸+A앱) | Opt 2 (B에 A 이식) | Opt 3 (A에 Clerk/Stripe 이식) |
| --- | --- | --- | --- |
| 초기 이주 비용 | 낮음 | 매우 높음 | 중간 |
| 영구 운영 비용 | 높음(앱 2벌+권한 동기) | 중간 | 낮음(앱 1벌) |
| 회귀 위험 | 낮음~중간 | 매우 높음 | 낮음(flag 이중운행) |
| 권한 일원화(D1) | ✗ 분열 | ✓ | ✓ (api가 권한, Clerk은 신원) |
| 저장소 지배(D3) | ✗(B가 git 밖) | △(vendoring 필요) | ✓ |
| 출시 속도(D4) | **최고** | 최저 | 중간(1~2주 규모) |
| §34 P1/P2 정합성 | 이음새 분리 | 역방향 | **연속 통합** |
| §35 gates 판정 | 경계 걸침 | 재획득 필요 | 단일 서피스 |

## 5. 결정 (Decision)

**Option 3를 채택한다 — `apps/web`(A)을 유일한 프론트엔드 정본으로 승격하고, B의 Clerk 인증·Stripe 과금·정책/가격 구현물을 이식한다. B는 이식 완료·동등성 게이트 통과까지 읽기 전용 참조로 동결한다.**

핵심 논거:

1. **권한의 원천이 A쪽에 있다**(D1). 결제를 Clerk metadata 쪽에 두면 권한이 둘로 갈라진다. Option 1은 결국 Option 3으로 재이전하게 되는 우회일 뿐이다 — 비용을 두 번 치른다.
2. **A의 테스트·게이트 인프라가 자산이다**(D2). 이식 작업은 기존 364+ 단위 테스트 아래에서 additively 진행되므로 회귀가 즉시 드러난다. Option 2는 이 망을 포기하고, Option 1은 사용자 서피스의 절반을 망 없이 운영한다.
3. **백엔드 브리지 비용이 생각보다 작다** — `services/api`는 OIDC 연합(`/v1/auth/oidc/*`), MFA, 세션 계약을 이미 구현했다. Clerk를 OIDC IdP로 연결하면 백엔드 신규 코드는 권한 동기 엔드포인트 1개로 수렴한다.
4. **B의 실가치는 코드 500~700행과 카피다** — 이것은 이식 가능하다. 반대로 A의 가치(133파일 컴포넌트·50 lib·65 테스트)는 이식 불가능한 규모다. 작은 쪽이 큰 쪽으로 수렴하는 것이 항상 저비용이다.
5. **청사진 정합성**(D5): Phase 2(Core SaaS)는 이미 달성돼 있고, Phase 1 물건을 이식하면 §35 전체 게이트를 하나의 서피스에서 판정할 수 있다.

**조건부 fallback**: 마케팅 공개일이 브리지 완성(Step 1~3)보다 앞서야 하는 hard deadline이 생기면, 한정 기간만 Option 1형 분리 배치(B 도메인=마케팅/결제, A 앱=제품)를 임시 허용한다. 단, 그 경우에도 Step 2의 세션 브리지는 공통 선행 작업이며, 분리 기간은 "임시"로 문서화하고 해소 기한을 명시한다.

## 6. 이행 계획 — 단계별 실행 체크리스트 (Option 3)

원칙: 각 단계는 독립 머지 가능, provider flag로 이중운행, 단계 종료 시 게이트 명령이 전부 green이어야 다음 단계 진행. 모든 경로는 저장소 루트 기준.

### Step 0 — 기준선 동결 (반나절)

- [ ] B 트리 지문 기록: `cd "<B>" && find . -type f -not -path './node_modules/*' | sort | xargs sha256sum > docs/evidence/adr-frontend-consolidation/tavonel-blank-slate.SHA256SUMS`
- [ ] A 기준 게이트 확인: `pnpm --filter @akc/web typecheck && pnpm --filter @akc/web lint && pnpm --filter @akc/web test && pnpm --filter @akc/web build`
- [ ] `services/api` 기준 확인: `uv run pytest services/api/tests -q`
- 검증: 위 네 명령 전부 성공. 실패 시 이식 착수 금지.

### Step 1 — 인증 viewer 추상화 (1일)

- [ ] 신규 `apps/web/src/lib/auth-viewer.ts`: 서버 경로용 `getViewer()` — 현재는 `/v1/auth/session` 쿠키 세션(`lib/session.ts`의 `normalizeSessionResponse` 재사용)을 감싸 `{userId, email}` 반환. Clerk는 Step 3에서 이 인터페이스 뒤에 들어온다.
- [ ] 신규 `apps/web/src/lib/auth-viewer.test.ts`(미인증·세션·형식 오류 3케이스)
- 검증: `pnpm --filter @akc/web test -- auth-viewer` 및 `pnpm --filter @akc/web typecheck`

### Step 2 — Clerk 도입 + services/api 세션 브리지 (2~3일, 가장 높은 리스크)

- [ ] `pnpm --filter @akc/web add @clerk/nextjs`
- [ ] `apps/web/src/proxy.ts` 재작성 — B `src/proxy.ts` 패턴 이식: matcher 유지, 보호 경로를 A 기준으로 조정(`/account(.*)`, `/billing(.*)`, `/settings(.*)`, `/workspace(.*)`, `/app(.*)`), **키 미구성 시 fail-closed**(보호 경로 → `/login?setup=required`), 공개 경로는 통과
- [ ] `apps/web/src/app/layout.tsx`: `<ClerkProvider>` 조건부 래퍼(설정 시에만)
- [ ] `apps/web/src/app/login/page.tsx`·`signup`: `NEXT_PUBLIC_AUTH_PROVIDER=clerk`일 때 Clerk 컴포넌트, `password`일 때 기존 `AuthPage`(이중운행)
- [ ] **세션 브리지**: Clerk 인증 후 `services/api`와 OIDC 연합 — Clerk를 OIDC IdP로 등록하고 기존 `/v1/auth/oidc/authorize`→`/oidc/callback` 흐름으로 AKC HttpOnly 세션 발급(백엔드 코드 변경 최소, `auth_api.py` 기존 경로 사용). `services/api` 설정(`settings.py` oidc issuer/client-id)만 추가
- [ ] e2e: `apps/web/e2e/workspace.spec.ts`에 clerk 모드 로그인 시나리오 추가(테스트 모드 키)
- 검증: `uv run pytest services/api/tests -k oidc -q` · `pnpm --filter @akc/web test` 전체 · `pnpm --filter @akc/web test:e2e -- workspace` · `pnpm --filter @akc/web interactions:check`

### Step 3 — Stripe 이식: checkout / portal / webhook (1~2일)

- [ ] 신규 `apps/web/src/lib/stripe-server.ts` ← B `src/lib/stripe.ts`(server-only 싱글턴)
- [ ] 신규 `apps/web/src/lib/billing-config.ts` ← B `src/lib/service-config.ts`: `BillablePlan(personal|team)`, `priceIdFor`, `billingConfigured`, **live-key 승인 게이트 유지**
- [ ] 신규 `apps/web/src/app/api/billing/checkout/route.ts` ← B 동명 라우트(동일오리진·인증·allowlist·ToS consent), 인증은 Step 1 `getViewer()` 경유
- [ ] 신규 `apps/web/src/app/api/billing/portal/route.ts` ← B 동명
- [ ] 신규 `apps/web/src/app/api/webhooks/stripe/route.ts` ← B 동명(raw body+`Stripe-Signature` 검증) **+ 확장**: Clerk metadata 영속화에 더해 `POST /v1/billing/provider-events`(HMAC 공유시크릿)로 services/api에 구독 이벤트 전파
- [ ] 백엔드 신규 `services/api/src/akc_api/billing_provider_events.py`(+`payment_routes.py` 라우터 등록): 서명 검증 후 `credit_policy`/`team_models`에 구독→플랜 반영. **services/api가 권한의 단일 원천으로 유지**
- [ ] `.env.example` 갱신: `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_PERSONAL`, `STRIPE_PRICE_TEAM`, `NEXT_PUBLIC_APP_URL`, live 승인 플래그
- [ ] 단위: B의 service-boundary 15체크를 `apps/web/src/lib/billing-config.test.ts` + 라우트 테스트로 이식(fail-closed·allowlist·라이브키 거부 포함)
- 검증: `pnpm --filter @akc/web test -- billing` · `uv run pytest services/api/tests -k billing -q` · stripe CLI로 테스트모드 webhook 서명 검증 1회

### Step 4 — 과금 UI 통합 (1일)

- [ ] `apps/web/src/components/billing-management.tsx`: 크레딧 팩 상단에 구독 섹션(Personal/Team 플랜 카드 → checkout 버튼, portal 링크) 추가 — B `BillingButton` 로직 이식
- [ ] `apps/web/src/components/account-page.tsx`: 플랜/구독 상태 표시를 **services/api 세션 응답**(권한 원천)에서 읽도록 하고 Clerk metadata 값은 표시 보조로 격하
- [ ] `apps/web/src/app/pricing/page.tsx` 신규 ← B `/pricing`(planCatalog 카피) — A 마케팅 셸(`tavonel-marketing-shell`) 톤으로
- [ ] `PAGE_MANIFEST.yml`에 `/pricing`·신규 API 라우트 등록
- 검증: `pnpm --filter @akc/web test` · `pnpm --filter @akc/web interactions:check` · `pnpm --filter @akc/web blueprint:check`

### Step 5 — 정책·신뢰 마케팅 이식 (Phase 1 정합성, 1~2일)

- [ ] B 정책/신뢰 페이지를 A 콘텐츠 컴포넌트로 이식: `terms` `privacy` `trust` `security`(`LegalDocument`/`ClaimStatus` 패턴) — A의 `structara-legal-register`, `claims.ts` 규약에 맞게 각 문장을 클레임 상태(approved/conditional)로 등록
- [ ] 홈/제품 카피: B `FINAL_WEB_DELIVERY_MATRIX.md`의 human study protocol 5항목을 A 마케팅 검증 스크립트로 채택(5초 설명 테스트 등)
- [ ] A 기존 브랜드 패밀리(tavonel/structara/folynta) 중 정본 노출 집합을 `PAGE_MANIFEST.yml`로 명시(비정본 데모 라우트는 비노출)
- 검증: `pnpm --filter @akc/web claims:check` (증표 없는 수치 import 금지 — B 카피 중 수치는 receipts 확인 후만) · `pnpm --filter @akc/web build` · `pnpm --filter @akc/web lighthouse`

### Step 6 — 동등성 게이트 통과 후 B 동결·종결 (반나절)

- [ ] 전체 게이트 재실행: `pnpm --filter @akc/web typecheck && pnpm --filter @akc/web lint && pnpm --filter @akc/web test && pnpm --filter @akc/web build && pnpm --filter @akc/web test:e2e` + `uv run pytest services/api/tests -q`
- [ ] 증표 아카이브: 게이트 출력·테스트모드 checkout 영수증을 `docs/evidence/adr-frontend-consolidation/`에 저장
- [ ] `AUTH_BILLING_IMPLEMENTATION_2026-08-23.md`의 Activation checklist 8항목을 운영 런북(`docs/runbooks/`)으로 이관(라이브 키·도메인·webhook 등록은 여전히 운영 게이트)
- [ ] B 디렉터리에 FROZEN 표기(README 상단) 및 이 ADR 링크 — 이후 B 변경 금지
- [ ] 이 ADR Status를 Accepted로 갱신

### 롤백 전략

각 단계 플래그: `NEXT_PUBLIC_AUTH_PROVIDER`(clerk|password), `NEXT_PUBLIC_BILLING_PROVIDER`(stripe|credit-packs-only). 플래그 되돌림만으로 Step 3~4는 즉시 이전 동작. Step 2 실패 시 password 플로우가 전역 fallback(ClerkProvider 미설정 시 프록시가 통과만 시킴).

## 7. 리스크와 완화

| 리스크 | 완화 |
| --- | --- |
| Clerk 도입이 기존 인증 e2e/단위 테스트 파괴 | provider flag 이중운행, Step 2를 독립 PR로, 기존 password 플로우 테스트 전량 유지 |
| Clerk↔AKC 세션 브리지의 토큰 수명 불일치 | OIDC 콜백이 발급하는 AKC HttpOnly 세션을 단일 진실로, Clerk 세션은 진입 수단으로만 취급 |
| webhook→api 동기 유실(네트워크 실패) | provider-events에 멱등키(provider_event_id) + 재시도 큐, 정기 대사(reconcile) 작업 런북화 |
| B 카피의 미승인 수치 유입 | `claims:check` 게이트 + approved/conditional/withheld 상태 등록 의무화 |
| 실결제 조기 활성화 | B의 live-key 승인 게이트(`TAVONEL_LIVE_BILLING_APPROVED`)와 Activation checklist를 그대로 계승 |

## 8. 결과 (Consequences)

- 긍정: 단일 Next 정본, 권한 단일 원천(services/api), 기존 364+ 단위 테스트로 보호받는 이식, §34 Phase1/2·§35 게이트를 한 서피스에서 판정, B의 검증된 결제 보안 패턴(server-only allowlist, fail-closed, raw-body 서명검증) 계승.
- 부정/비용: Clerk 도입 기간 인증 이중운행 복잡도, B 마케팅 비주얼(three.js 히어로 등) 일부는 A 톤으로 재작성 필요(이식이 아니라 참조), 마케팅 완성도가 B 수준으로 올라오기 전까지 Phase 1 물건은 A에서 2차 작성.
- B의 운명: 동등성 게이트 통과 후 읽기 전용 참조로 동결. Option 1(셸 분리)은 hard deadline 시의 한정 임시 전략으로만 유효.

## 9. 최종 요약 (한국어)

두 프론트엔드를 비교한 결과, **A(`apps/web`)를 정본으로 삼고 B(tavonel-blank-slate)의 Clerk 인증·Stripe 과금·정책/가격 구현물을 A로 이식하는 방향(Option 3)을 추천**한다. A는 백엔드(services/api 77모듈)와 계약으로 묶인 실제 제품 서피스로, 월드 프로젝션·SSE 라이브 이벤트·업로드·리뷰·관리자까지 구현하고 단위 65파일(364+)·e2e 14스펙·5종 게이트라는 회귀 안전망을 갖춘 반면, B는 Clerk+Stripe 결제(서명검증·fail-closed·15경계체크 PASS)와 마케팅 28라우트라는 좁고 단단한 상용 셸이지만 백엔드 호출이 결제 버튼 하나뿐이고 단위 테스트가 없다. 이식 규모는 작은 쪽(B 약 500~700행 + 카피)이 큰 쪽(A 133파일)으로 수렴하는 것이 원칙적으로 저비용이고, A 백엔드에 이미 OIDC 연합 코드가 있어 Clerk 세션 브리지 비용도 작다. 결정적 이유는 권한(entitlement)의 원천이다 — 구독 상태를 Clerk metadata에 두면(B 안) 권한이 둘로 갈라져 영구 동기화 비용을 낸다. B를 상용 셸로 두는 Option 1은 초기 비용은 가장 낮지만 두 앱 병행 운영·권한 분열·결제 표면 중복이라는 영구 비용을 남기며, 결국 Option 3으로 재이전하게 된다. B에 A를 이식하는 Option 2는 회귀 안전망을 상실한 채 A를 재건하는 최악의 경로다. 청사진(§34)으로 보면 Phase 1(Marketing & Demo)은 B가, Phase 2(Core SaaS)는 A가 이미 담당하므로, B의 Phase 1 물건을 A로 이식하면 두 페이즈가 하나의 코드베이스에서 연속되고 §35 전체 게이트를 단일 서피스에서 판정할 수 있다. 이행은 6단계(기준선 동결 → 인증 viewer 추상화 → Clerk+OIDC 브리지 → Stripe 3라우트 이식+api 권한 동기 → 과금 UI 통합 → 정책/신뢰 이식 후 B 동결)로, 각 단계는 provider flag 이중운행과 파일 단위 체크리스트·검증 명령을 갖춰 §6에서 바로 실행 가능하다.
