# FOLYNTA 비디자인 완료 감사

## 작업 패킷

```yaml
problem_ids:
  - FOLYNTA-FINAL-E2E-RESOLUTION-MASTERPLAN-KO-20260802
  - runtime-install-prohibition
  - algorithm-evidence-traceability
source_evidence:
  - D:/FOLYNTA_FINAL_END_TO_END_RESOLUTION_MASTERPLAN_v2_TRACEABILITY_COMPLETE_KO_2026-08-02.md
  - benchmark/reports/FOLYNTA_SYSTEM_ALGORITHM_EVALUATION_2026-08-02.md
  - docs/release/FOLYNTA_V2_TRACEABILITY_LEDGER.json
files_in_scope:
  - benchmark/**
  - packages/**
  - services/**
  - infra/**
  - tools/release/**
  - docs/release/**
files_out_of_scope:
  - apps/web/**
  - visual baselines
  - brand and creative assets
dependencies:
  - Python 3.12 and 3.13
  - PostgreSQL 17 disposable CI service
  - Cloudflare R2 read-only provider probe
  - RunPod Pod and Serverless read-only evidence surfaces
implementation:
  - deterministic algorithm evaluator and golden fixtures
  - role-separated R2 clients with production fail-closed settings
  - PostgreSQL RLS and role-boundary CI gate
  - fail-closed RunPod Pod client and baked-runtime qualification contract
  - line-addressable 791-row traceability ledger with scope and state semantics
tests:
  - focused algorithm suite
  - full backend regression on Python 3.12 and 3.13
  - parser sandbox, SSRF, encrypted-PDF, and isolation suite
  - PostgreSQL 17 RLS gate
  - model, security, infrastructure, and container-image CI
metrics:
  - deterministic algorithm pass count
  - algorithm and repository coverage
  - duplicate retry and hedge credit charge
  - provider-gate receipts and immutable hashes
cost_cap:
  - no paid Pod may be created from BUILD_REQUIRED image specifications
  - provider mutations require an approved secret destination and explicit receipt
stop_conditions:
  - private holdout or ground truth is unavailable
  - provider credential scope cannot be proved read-only
  - production deployment or restore target is not explicitly identified
  - an image lacks an immutable digest and baked runtime receipt
artifacts:
  - benchmark/reports/folynta-system-algorithm-evaluation-2026-08-02.json
  - benchmark/reports/folynta-system-algorithm-golden-evaluation-2026-08-02.json
  - benchmark/reports/folynta-r2-production-gate-2026-08-02.json
  - benchmark/reports/folynta-postgres-rls-ci-gate-2026-08-02.json
  - docs/release/FOLYNTA_V2_TRACEABILITY_LEDGER.json
rollback:
  - revert only the isolated non-design commits
  - retain immutable evaluation and provider receipts
  - keep production promotion fail closed
gate:
  code_and_contract: IMPLEMENTED-LOCAL
  empirical_model_qualification: SHADOW
  provider_and_operations: EXTERNAL-BLOCKED
  release: PRODUCTION-REJECT
status: PARTIAL
```

## 알고리즘 증거

| 영역 | 결정적 테스트 | 상태 | 증명 범위 |
|---|---:|---|---|
| 페이지 분류·비용 예측·적응형 라우팅 | 54 | 통과 | 특징 경계, 공개 증명 locale 선택, 준비된 경로, 개인정보 전송 제한 |
| 크레딧·비용·결제 원장 | 36 | 통과 | 승인된 논리 작업 1회 과금, retry·hedge 중복 과금 금지 |
| 품질·수치·표·근거 검증 | 67 | 통과 | critical finding 및 authority mismatch의 우회 금지 |
| 장애·이상·워커 건강 | 30 | 통과 | 인프라와 의미 장애 분리, unknown의 성공 승격 금지 |
| 최소 범위 재시도·복구·무효화 | 42 | 통과 | cell→row→table→region→page 복구와 lineage |
| 문서→지식 아키텍처·검색·패키지 | 30 | 통과 | canonical identity와 원문 근거 보존 |
| 상태·식별자·보안·격리 | 117 | 통과 | 멱등성, 테넌트 격리, 이미지 승격, 불변 증거, 권한 경계 |

이 결과는 고정된 결정적 계약을 증명한다. 현실 문서 분포의 분류 정확도, private holdout 성능,
복구 효율의 통계적 우월성, 실제 provider 비용 보정까지 증명하지는 않는다.

## 런타임 설치 금지 해결

- `infra/runpod/v6/images/ovisocr2-m1/Dockerfile`이 vLLM 기반 이미지, 패키지 버전,
  OvisOCR2 revision, 모델 payload SHA-256, SSH 서비스를 빌드 시점에 고정한다.
- `benchmark/runpod_eval/bootstrap_ovisocr2_m1.sh`은 설치나 다운로드를 수행하지 않는다.
  이미지 digest, baked receipt, 패키지 버전, 모델 hash, GPU identity만 검증한다.
- `BUILD_REQUIRED` 사양은 `RunPodPodClient.create_pod`에서 유료 capacity 생성 전에 거부된다.
- `READY` 승격에는 immutable image digest와 baked runtime receipt SHA-256이 모두 필요하다.

현재 baked image가 registry에 게시되지는 않았으므로 이 항목은 `IMPLEMENTED-LOCAL`이며,
게시 digest와 실행 영수증이 생기기 전에는 실환경 qualification을 주장하지 않는다.

## 추적성 판정

원장은 791개 source row를 모두 유지하면서 다음을 별도로 표시한다.

- `SECTION_ANCHOR`: 구조와 탐색을 위한 제목
- `ACCEPTANCE_ITEM`: 최종 점검표의 실행 항목
- `NORMATIVE_CONSTRAINT`: 금지·필수·보안 경계
- `OUT_OF_SCOPE_DESIGN`: 별도 UI/UX 세션에 위임된 행
- `NON_DESIGN`: 이 브랜치의 직접 실행 범위
- `MIXED`: 디자인과 백엔드 증거가 함께 필요한 범위

체크리스트는 검증된 본문 행을 `inherits`로 참조한다. 동일 증거를 복사해 서로 다른 상태로
표시하지 않으며, 상속 순환과 존재하지 않는 대상은 생성 단계에서 거부된다.

현재 ledger snapshot:

| 구분 | 합계 | DONE | PARTIAL | EXTERNAL_BLOCKED | APPROVAL_REQUIRED | NOT_APPLICABLE | OPEN |
|---|---:|---:|---:|---:|---:|---:|---:|
| 전체 source row | 791 | 18 | 75 | 3 | 3 | 413 | 279 |
| 실제 행동 항목 | 87 | 11 | 36 | 2 | 2 | 36 | 0 |
| 비디자인 행동 항목 | 46 | 6 | 36 | 2 | 2 | 0 | 0 |
| 혼합 범위의 백엔드 계약 | 5 | 5 | 0 | 0 | 0 | 0 | 0 |
| 디자인 세션 행동 항목 | 36 | 0 | 0 | 0 | 0 | 36 | 0 |

Ledger hash:

```text
sha256:8aedbe8958891ccf7a286ca4b20c78f8d404d39f0ca4cc61cabdca3155b4aa1c
```

전체 row의 `OPEN 279`는 실행 체크리스트가 아니라 아직 승격되지 않은 섹션 앵커다. 실제
행동 항목은 `OPEN 0`이며, 미완료 상태는 증거 수준에 따라 `PARTIAL`, `EXTERNAL_BLOCKED`,
`APPROVAL_REQUIRED`로 명시돼 있다.

## 외부 완료 조건

다음 조건은 로컬 구현이나 합성 테스트로 완료 처리하지 않는다.

1. Cloudflare에서 발급된 네 개의 제한형 R2 역할 자격증명과 설치 영수증
2. 동결된 private holdout manifest, ground truth, 데이터 소유자 승인
3. 프로덕션 PostgreSQL revision·migration·RLS·role 배포 영수증
4. RunPod Pod 평가의 provider invoice와 내부 비용·사용자 credit 대조
5. 프로덕션 PITR, 격리 restore, 리전 장애, credential rotation, model rollback 훈련
6. 법무의 상표·특허·공개 승인

이 조건이 없으므로 최종 출시 상태는 `PRODUCTION-REJECT`다. 이것은 구현 실패를 숨기기 위한
표현이 아니라, 마스터플랜이 요구한 증거 경계를 그대로 적용한 결과다.
