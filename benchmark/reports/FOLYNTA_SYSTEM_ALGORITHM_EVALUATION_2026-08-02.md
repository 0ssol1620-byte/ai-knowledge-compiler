# FOLYNTA 비디자인 알고리즘 검증 리포트

- 전체: 356개
- 통과: 356개
- 실패/오류/건너뜀: 0/0/0
- 결정적 계약 Gate: `PASS`
- 코드 커버리지: 81.61% (Gate 80%, `PASS`)
- line/branch: 9768/11391, 2513/3658

## 영역별 결과

| 영역 | 테스트 | 통과 | 실패 | Gate | 핵심 계약 |
|---|---:|---:|---:|---|---|
| 페이지 분류·비용 예측·적응형 라우팅 | 51 | 51 | 0 | PASS | 객관 특징 분류, 준비된 경로만 선택, 비공개 데이터 외부 전송 금지 |
| 크레딧·비용·결제 원장 | 36 | 36 | 0 | PASS | 검증 승인된 논리 작업만 1회 과금하고 retry·hedge·실패는 중복 과금하지 않음 |
| 품질·수치·표·근거 검증 | 63 | 63 | 0 | PASS | critical finding과 authority mismatch가 점수·다수결을 우회하지 못함 |
| 침묵 실패·이상 결과·worker health 탐지 | 30 | 30 | 0 | PASS | HTTP 200이어도 의미 오류를 실패로 처리하고 오염 worker를 격리함 |
| 최소 범위 재시도·선택 복구·무효화 | 42 | 42 | 0 | PASS | cell→row→table→region→page 순서의 최소 범위 복구와 완전한 lineage 보존 |
| 문서→지식 아키텍처·검색·패키지 | 30 | 30 | 0 | PASS | 노트·엔티티·관계·아키텍처·패키지가 원문 근거와 동일한 canonical identity를 유지함 |
| 상태기계·동시성·결정 추적·보안 경계 | 104 | 104 | 0 | PASS | idempotency, append-only history, first-verified, tenant/object scope가 깨지지 않음 |

## 고정 오류 주입 코퍼스 정량 결과

| 알고리즘 | 코퍼스 | 지표 | 결과 |
|---|---:|---|---:|
| 페이지 분류 | 12 | accuracy | 1.000 |
| 품질 이상 탐지 | 6 | precision/recall/F1 | 1.000 / 1.000 / 1.000 |
| 실패 원인 분류 | 24 | accuracy | 1.000 |
| 복구 specialist 선택 | 7 | accuracy | 1.000 |
| 라우팅·escalation | 10 | decision accuracy | 1.000 |
| 중복 시도 과금 | 32 | charged credits | 0.000000 |

- Golden Gate: `PASS`
- 경계: PASS proves deterministic golden-contract behavior only; it does not prove real-distribution or private-holdout accuracy.

## 전체 백엔드 회귀

| 테스트 | 통과 | 실패 | 오류 | 스킵 | Gate |
|---:|---:|---:|---:|---:|---|
| 1489 | 1489 | 0 | 0 | 0 | PASS |

- 범위: API·상태기계·보안·스케줄러·삭제·과금·검색·지식 패키지·모델 평가 도구 회귀
- 이 Gate는 현재 코드베이스 회귀 무결성을 증명하며 실운영 SLO를 대신하지 않는다.

## 판정 경계

- 증명됨: 고정 입력에 대한 결정 규칙, 상태 보존성, 과금 불변식, 오류 주입 대응, 지식 패키지 근거 계약
- 아직 증명되지 않음: 현실 분포 전체의 분류 정확도, private holdout 품질, production invoice와 provider telemetry의 장기 calibration
- 따라서 이 리포트는 서비스 알고리즘의 결정적 기능·안전 계약 통과 증거이며, 현실 분포 전체 정확도나 private holdout 합격을 대신하지 않는다.

## 추가 Gate

| Gate | 상태 |
|---|---|
| Public empirical corpus | PARTIAL |
| Private holdout | EXTERNAL_BLOCKED |
| Production calibration | PARTIAL |
