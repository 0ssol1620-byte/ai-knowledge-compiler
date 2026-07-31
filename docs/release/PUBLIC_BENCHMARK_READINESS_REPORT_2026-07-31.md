# Structara v2 Public Benchmark 준비도 및 제품 완료 검수 보고서

- 기준 문서: `Structara_World_Class_Brand_Product_Completion_Masterplan_FINAL_v2_Public_Benchmark_KO_2026-07-31.md`
- 저장소: `D:\CodexProjects\ai-knowledge-compiler`
- 평가일: 2026-07-31
- 현재 판정: **Repository Release Candidate / Shadow only / Production Reject**

## 1. 결론

저장소에서 자동화할 수 있는 v2 공개 벤치마크 기반과 제품·브랜드 회귀 검사는 구현했다. 다만 실제 모델 후보와 incumbent를 대상으로 한 Tier 2 Full Public Core가 실행되지 않았으므로 Parser 또는 Router를 Production으로 승격할 수 없다. 공개 점수도 생성하거나 추정하지 않았다.

Production Reject의 직접 사유는 다음과 같다.

1. 현재 RunPod 계정에서 조회되는 endpoint가 0개다. 비용이 발생할 수 있는 endpoint 생성은 저장소 구현 범위를 넘어 별도 운영 승인 대상이다.
2. OmniDocBench v1.7 전체, ParseBench 5개 차원 전체, olmOCR-Bench 전체 category에 대한 candidate/incumbent 3회 반복 결과가 없다.
3. 전체 실행이 없으므로 immutable prediction archive, official raw output, critical output, 비용·지연, 실패 페이지 묶음, signed report를 완결할 수 없다.
4. OmniDocBench 데이터셋은 research-only/non-commercial 조건으로 확인되어 상업적 사용·재배포 권리 검토가 필요하다.
5. 고정한 olmOCR-Bench evaluator 저장소에는 명시적인 라이선스 파일이 없어 법무·라이선스 승인이 필요하다.

이 판정은 구현 실패가 아니라, v2가 요구하는 증거가 아직 없는 상태를 정확히 차단한 결과다.

## 2. 구현 완료 범위

### 2.1 고정 Public Core Registry

`benchmark/benchmark-registry.lock.yaml`에 다음을 고정했다.

| Benchmark         | Evaluator commit                           | Dataset revision                           | Dataset manifest SHA-256                                           | 범위                                            |
| ----------------- | ------------------------------------------ | ------------------------------------------ | ------------------------------------------------------------------ | ----------------------------------------------- |
| OmniDocBench v1.7 | `193627ae9e97d89188468ed1ee3b7a856ff76044` | `aa1ee96d106dbe53d0ae59474d75c6e6d9b53fec` | `1902d23db1b0e409d774f1420306f9e9e82d1aa8638050f0fc8fd6b94c58aa99` | OCR, layout, table, formula, reading order, E2E |
| ParseBench        | `1d460294b3b9c57fb3fa944dc17a9c044c24d1e5` | `2805a1d940f95a203e0ae4b88be9934f7765b3fc` | `9e3a722a5db9e8e23273176827c06a30fe6a58a983850329db917fabcff6c30e` | 5개 공식 차원                                   |
| olmOCR-Bench      | `cfa88c1eb1c2ec4495c84d6820ffe85d33b7408c` | `54a96a6fb6a2bd3b297e59869491db4d3625b711` | `55f347b01850aec77d457f6b3b2b54ddf5adce6f451ed501e59995ec0e9bff15` | 전체 fact category                              |

온라인 검증은 GitHub의 정확한 commit과 Hugging Face의 전체 파일 목록·크기·blob/LFS identity를 다시 계산해 lock과 일치할 때만 통과한다. 현재 registry 자체 SHA-256은 `46e586268944309b1be69d5afcfb164f1c18643c47cbb350bda6cda5c4a22985`다.

Real5-OmniDocBench와 RealDocBench는 실행 가능한 공식 데이터셋·evaluator를 확인하지 못해 `research_watch`로, Dr. DocBench는 공개 challenge 안내만 있고 데이터·evaluator가 없어 `challenge_information_only`로 등록했다. 한국어 공개 세트도 공식성·권리·GT·evaluator가 함께 검증될 때까지 watch 상태다.

### 2.2 Fail-closed 실행 계약

`benchmark/public_suite.py`에 다음 계약을 구현했다.

- Structara CIR에서 OmniDocBench, ParseBench, olmOCR-Bench prediction 형식으로 변환하는 GT 비의존 adapter
- GT와 유사한 파일명을 prediction archive에서 차단
- prediction 파일별 SHA-256 및 archive SHA-256 고정, 쓰기 권한 제거, 재해시 검증
- prediction root와 evaluator-only GT root의 경로 격리 및 환경변수 노출 검사
- numeric/sign/decimal/unit/row/page/duplicate/evidence/silent omission, output corruption, false verified를 별도 critical gate로 평가
- candidate와 incumbent의 benchmark, dataset, evaluator, environment identity가 다르면 비교 거부
- overall 회귀, 차원별 1 percentage point 초과 회귀, runtime·missing·critical·GT leakage를 fail-closed 처리
- 정확히 3회 동일 환경 실행과 기본 0.5 percentage point metric span을 검사하는 reproducibility gate
- OpenSSL 외부 개인키가 있을 때만 서명하고, 키가 없으면 `unsigned_external_key_required`로 명시

CI는 Public Core registry를 온라인으로 재검증하며, 저장소 정책 validator도 lock을 오프라인으로 검사한다. dataset cache, GT, public run archive는 커밋 대상에서 제외했다.

### 2.3 제품·브랜드 완료 보강

v2 작업 중 실제 브라우저에서 확인된 결함도 함께 수정했다.

- Catch-all 하위에 둘 수 없던 Next.js OG/Twitter metadata route를 유효한 root route로 이동
- Projects workspace의 잘못된 locale 함수 import로 발생하던 런타임 오류 수정
- SEC proof와 Knowledge Studio의 중첩 `main` landmark 제거
- 임베드된 문서 Markdown의 H1을 앱 페이지 H1 아래 수준으로 이동해 문서 구조 충돌 제거
- `/app/projects`와 Knowledge Studio의 동작 가능한 header action 계약 복원
- 데모에서 실행할 수 없는 publish/audit export를 명시적 disabled control로 표시
- 모바일 아이콘-only 관점 제어에 접근 가능한 이름 제공
- hydration 직전 검색 입력이 초기 상태로 되돌아가는 경쟁을 차단
- 요청 locale과 하위 앱 콘텐츠가 어긋나던 영문 fallback 결함을 제거하고 locale 의존 route를 동적 렌더로 고정
- Zod를 nonce-only CSP와 호환되는 `jitless` 경로로 고정해 Firefox의 차단된 eval 로그 제거
- above-the-fold 제품 증거 이미지에 우선 로딩 힌트 적용
- Playwright를 프로덕션 빌드 기반으로 실행하고, desktop visual baseline과 별도 7 viewport/3 browser matrix의 책임을 분리

## 3. 실제 검증 증거

### 3.1 Public benchmark Tier 0

| 검증                                    | 결과                   | 해석                                                                           |
| --------------------------------------- | ---------------------- | ------------------------------------------------------------------------------ |
| Structara public-suite 단위·계약 테스트 | 11 passed              | adapter, freeze, isolation, critical, compare, 3-repeat, unsigned 경계 통과    |
| Registry online verification            | pass                   | 3개 evaluator commit과 dataset manifest 일치                                   |
| ParseBench official evaluator tests     | 198 passed             | evaluator 로직 실행 가능. 전체 데이터 점수가 아님                              |
| OmniDocBench compatibility smoke        | 5 passed, 1 deselected | Windows/Python 3.11 호환 환경에서 smoke 통과. 전체 공식 평가가 아님            |
| olmOCR-Bench evaluator smoke            | pass                   | import, Unicode normalization, baseline/repetition 계약 통과. 전체 점수가 아님 |

OmniDocBench upstream 고정 의존성의 `lxml==4.9.1`은 이 호스트의 Python 3.11 Windows wheel이 없어 그대로 설치되지 않았다. 호환 환경은 `lxml 6.1.1`과 UTF-8 모드로 smoke만 수행했다. 따라서 이를 공식 full 결과로 표시하지 않는다.

### 3.2 저장소·웹 회귀

| 검증                                 | 결과                                    |
| ------------------------------------ | --------------------------------------- |
| Python full pytest                   | 606 passed                              |
| Python Ruff                          | pass                                    |
| Python mypy                          | 136 source files, no issues             |
| Web Vitest                           | 22 files, 109 tests passed              |
| Web strict TypeScript                | pass                                    |
| Web ESLint                           | pass, zero warnings                     |
| Next.js production build             | pass                                    |
| Production Playwright                | 52 passed, 14 intentional scope skips   |
| Desktop visual regression            | 9 approved baselines passed             |
| Browser/viewport matrix              | 9 passed; Chromium, Firefox, WebKit      |
| Live API end-to-end journey          | 1 passed; provenance through export      |
| Asset manifest/name/hash             | 9 assets, 119 names, 21 hashes verified |
| Enabled dead-button contract         | 0                                       |
| Repository security/policy validator | pass                                    |

프로덕션 E2E는 데스크톱과 모바일 핵심 기능을 검증했고, 모바일에서 의도적으로 제외한 데스크톱 전용 visual baseline·명령 팔레트·중복 전체 route crawl은 각각 전용 데스크톱 또는 browser matrix에서 검증했다. live API 여정은 실제 로컬 API에서 등록, 검증, 업로드, 분석, 컴파일, SSE, export까지 통과했다.

Next.js 16.2.12의 Windows standalone trace는 `proxy.ts` 산출물 누락과 `.next/package.json` 복사 시점 경쟁을 간헐적으로 재현했다. 현재는 동일 보안 계약의 `middleware.ts` compatibility entry와 clean retry로 최종 build가 통과한다. 이는 제품 런타임 실패로 숨기지 않고 upstream 도구 체인 위험으로 유지한다.

## 4. 공개 주장 경계

현재 외부에 사용할 수 있는 문구는 다음 수준뿐이다.

- Public benchmark registry and evaluator revisions are pinned.
- Ground-truth-assisted inference is prohibited by the execution contract.
- Tier-0 adapter/evaluator smoke checks passed.

현재 사용할 수 없는 문구는 다음과 같다.

- Public benchmark verified
- OmniDocBench/ParseBench/olmOCR score 또는 leaderboard 비교
- production accuracy, world-class, best-in-class
- signed reproducibility report completed
- Production A 또는 production-ready parser

## 5. Production 승격을 위해 남은 실행

1. 승인된 비용 한도와 immutable image/model revision으로 RunPod endpoint 또는 동등 GPU 환경을 준비한다.
2. candidate와 incumbent를 동일 container, GPU, CUDA, decoding, DPI, batch, concurrency 환경에 고정한다.
3. inference role에서 GT mount와 GT 관련 환경변수가 0임을 증명한다.
4. 각 benchmark의 source-only inference를 실행하고 prediction을 즉시 freeze한다.
5. evaluator role에서만 GT를 mount해 official evaluator와 Structara critical evaluator를 실행한다.
6. 각 candidate와 incumbent를 정확히 3회 반복해 변동성, 비용, 지연을 기록한다.
7. 실패 페이지별 source, prediction, GT view, diff, route/parser/validator log, cost, reproduction command를 생성한다.
8. 라이선스 검토를 완료하고 허용 범위 밖의 dataset 또는 artifact를 R2나 공개 패키지로 복제하지 않는다.
9. 외부 서명키로 JSON/Markdown/HTML report를 서명한다.
10. Public Core와 Finance, Knowledge, Robustness, private unseen gate를 모두 통과한 경우에만 독립 승인자가 승격을 결정한다.

## 6. 최종 판정

코드·제품·재현성 기반은 release-candidate 수준으로 준비됐다. 그러나 v2의 핵심인 Full Public Core 실측이 아직 없으므로 최종 상태는 **Shadow only / Production Reject**다. 이 저장소는 누락된 증거를 성공으로 꾸미지 않고, 실제 전체 실행과 서명된 결과가 생길 때까지 승격을 차단한다.
