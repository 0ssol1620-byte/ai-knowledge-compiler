# TAVONEL Cinematic Compiled World: 경쟁 환경과 차별화 방향

## 관찰

Hebbia는 금융·법무·자문 조직을 대상으로 방대한 문서와 시장·파일·업무 시스템을 한 프로젝트 안에 모으는 방식으로 신뢰를 만든다.[1] Glean은 연결된 시스템을 검색·이해·생성·개인화·신뢰라는 흐름으로 설명하며, 권한과 실시간 색인을 핵심 제품 요소로 둔다.[2] Notion은 이미 존재하는 작업공간 내부에서 에이전트·검색·회의 기록·권한을 결합한다.[3] Oryzo는 실제 제품 증명보다는 하나의 강한 가상 세계를 끝까지 밀어붙이는 시네마틱한 전개와 상호작용적 유머가 주목을 만드는 사례다.[4]

TAVONEL은 이들 중 어느 한 제품의 UI 패턴을 모방하지 않는다. **“AI가 답을 만들어 낸다”가 아니라, 고객이 자신의 원본이 증거 경계를 유지한 채 지식 세계로 재구성되는 과정을 본다**는 고유한 제품 증명을 선택한다.

| 경쟁 환경의 강점 | TAVONEL이 더 강하게 보여줄 장면 | 제품 계약 |
| --- | --- | --- |
| 많은 연결 시스템 | 하나의 파일이 private perimeter 안으로 들어오는 순간 | 파일 바이트는 객체 저장소, 메타데이터만 SQL |
| 빠른 답변과 검색 | 답변 이전의 문서 구조·중복·근거 상태 | 결과마다 원본·복사본·검토 상태를 명시 |
| 자동화·에이전트 | 검토 가능한 컴파일 시퀀스 | 자동 제안과 고객 승인 상태를 분리 |
| 넓은 지식 그래프 | “Source → Structure → Evidence → Context”라는 좁고 깊은 변환 | 원문을 벗어난 관계는 근거 없이 그리지 않음 |
| 화려한 캠페인 연출 | 고객 데이터가 입자·평면·좌표·연결선으로 변하는 cinematic ingestion | 시각 효과가 처리 성공을 가장하지 않으며 실제 상태와 연결 |

## Cinematic product world

TAVONEL의 고유 자산 세계는 **Field Green의 private perimeter**, **parchment review surface**, **lime currentness signal**, **source orb**, **coordinate grid**, **evidence thread**로 구성한다. 홈에서 이 언어는 공개 filing으로 증명되고, 로그인 화면에서는 identity-bound perimeter로, 고객 작업공간에서는 파일 궤도와 컴파일 코어로 이어진다.

고객 흐름은 네 장면으로 고정한다. 첫 장면에서 파일·클라우드·파일 서버는 perimeter 밖의 source fragments로 나타난다. 두 번째 장면에서 OCR·레이아웃 읽기·중복 확인은 단순한 로딩 바가 아니라 각 조각이 중심 코어와 관계를 얻는 읽기 상태다. 세 번째 장면에서 불확실한 항목과 복사본은 별도 색으로 보존된다. 마지막 장면에서만 제안된 디렉터리·엔터티·지식 패키지가 나타나며, 모든 항목은 review-first 상태를 가진다.

## 실제 연결 아키텍처 선택

| 고객 경험 방식 | 적합한 원본 | 장점 | 준비 사항 |
| --- | --- | --- | --- |
| 브라우저 업로드와 클라우드 OAuth | 개인 문서, Drive·SharePoint 등 SaaS | 설치 없이 빠른 온보딩 | 서비스별 OAuth 앱·권한 범위·토큰 회전 설계 |
| 고객 환경의 수집 에이전트 | 사내 파일 서버·폐쇄망·대용량 저장소 | 파일 서버를 외부에 노출하지 않고 수집 | 고객 내부 에이전트, 네트워크 정책, 감사 로그 계약 |

첫 번째 공개 제품 버전은 실제 파일 업로드·S3 저장·중복 해시 탐지·AI 보조 구조 제안을 제공한다. 클라우드 OAuth와 파일 서버 수집은 각각의 권한 계약을 정한 후 활성화한다. 단, 둘 다 원본 접근 범위·삭제·동기화·감사 항목을 고객이 검토할 수 있는 connector perimeter 화면에서 보여줘야 한다.

## References

[1]: https://www.hebbia.com/ "Hebbia: Institutional Intelligence"
[2]: https://www.glean.com/enterprise-ai "Glean: Enterprise AI"
[3]: https://www.notion.com/product/ai "Notion AI"
[4]: https://oryzo.ai/ "Oryzo: fictional cinematic creative project"
