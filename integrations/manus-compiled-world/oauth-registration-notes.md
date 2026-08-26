# TAVONEL OAuth 등록 기록

## Google Drive

- 운영자 Google Cloud 프로젝트: `TAVONEL Knowledge Compiler` (`tavonel-knowledge-compiler`)
- 동의 화면 브랜딩: `TAVONEL`
- 발급 중인 웹 클라이언트 이름: `TAVONEL Drive Connector — Production`
- 허용된 리디렉션 URI: `https://tavoknowledg-rm8cmlar.manus.space/api/connections/google-drive/callback`
- 고객 권한 원칙: 원본을 보존하고 읽기 전용 범위만 요청한다. 고객은 TAVONEL 서비스가 소유한 OAuth 앱의 동의 화면에서 승인만 한다.

## 보류 사항

- Google Cloud 콘솔에서 웹 클라이언트 생성 완료 후 Client ID와 Client Secret을 서버 전용 비밀값으로 저장한다.
- Microsoft Entra SharePoint 앱은 별도 운영자 등록과 서버 전용 비밀값 설정이 필요하다.

Microsoft의 한국 Business 플랜 페이지는 SharePoint 팀 사이트를 포함한 Microsoft 365 Business Basic을 제공하며, 표시 가격은 사용자당 월 ₩9,500(연간 결제, VAT 별도)이었다. 가입에는 신용 카드가 필요할 수 있고, 무료 평가판은 만료 시 유료 전환될 수 있으므로 TAVONEL 운영자 확인 없이 가입·결제를 진행하지 않는다. 출처: <https://www.microsoft.com/ko-kr/microsoft-365/business/microsoft-365-plans-and-pricing>.

## 검수 기록

개발 미리보기의 인증된 `/world` 화면에서 `First Compiled World`와 TAVONEL의 개인 경계·컴파일 스테이지가 정상적으로 렌더링되는 것을 2026-08-26에 확인했다. OAuth 승인 컨트롤은 아래쪽 Connector Perimeter에서 별도로 확인한다.

Google Drive 테스트 승인 중 Google은 TAVONEL OAuth 앱이 테스트 모드이며 허용 테스트 사용자가 없다고 응답했다. 브랜딩 화면에서 `0ssol1620@gmail.com` 지원 이메일과 TAVONEL 홈페이지·개인정보처리방침·서비스 약관 URL을 입력했고, 공개 URL을 지원할 `/privacy`와 `/terms` 경로를 구현했다. 이 변경을 저장한 뒤 테스트 사용자를 추가해야 한다. 프로덕션 공개에는 Google의 민감 범위 검증 및 승인된 도메인 검증이 별도로 필요하다.

2026-08-26에 Google Cloud 대상 설정에서 `0ssol1620@gmail.com`을 TAVONEL OAuth 테스트 사용자로 추가했다. 이제 해당 계정은 테스트 중인 Drive 읽기 전용 동의 화면을 통과할 수 있으며, 실제 콜백과 프로젝트 연결 상태를 다시 검증해야 한다.

테스트 사용자는 Google의 미확인 앱 안내를 통과했고, 최종 동의 화면에는 `Google Drive 파일 보기 및 다운로드` 읽기 전용 범위만 표시되었다. 최종 동의 후 Google이 프로덕션 콜백 URL로 리디렉션했지만, `tavoknowledg-rm8cmlar.manus.space`가 Manus 미납 청구로 차단되어 콜백 코드 교환과 연결 레코드의 `active` 전환은 완료되지 못했다. 이는 구현 오류가 아니라 공개 배포·청구 상태의 외부 차단이며, 해결 뒤 동일 승인 흐름을 다시 검증해야 한다.

`/privacy`와 `/terms` 공개 문서는 데스크톱 개발 미리보기에서 정상 렌더링되는 것을 확인했다. 인증 쿠키를 공유하지 않는 별도 캡처에서는 `/world`가 비인증 진입 상태로 비어 보일 수 있으므로, 파일 서버 제어면은 로그인된 운영자 브라우저에서 별도 검수한다.

로그인된 운영자 브라우저에서 `/world`는 최초 로드 중 일시적으로 `New Compiled World`를 보일 수 있으나, 쿼리 완료 후 `First Compiled World`, 원본 4개, `COPY` 관계 1개, 완료된 컴파일 결과를 복원했다.

`/privacy`와 `/terms`는 375px 모바일 검수에서도 문서 제목, 본문, 섹션 번호, 하단 링크가 한 열로 읽히며 가로 넘침 없이 렌더링됐다.

체크포인트 `4a189578` 저장 뒤 공개 도메인을 다시 확인했으나, 여전히 `Site unavailable due to unpaid billing` 화면을 반환했다. 따라서 공개 URL을 사용하는 Google Drive 콜백은 청구 상태가 정상화될 때까지 완료 검증할 수 없다.

체크포인트 `1d33ff39` 저장 후에도 `https://tavoknowledg-rm8cmlar.manus.space/world?checkpoint=1d33ff39`는 동일한 `Site unavailable due to unpaid billing` 화면을 반환했다. 현재 공개 고객 테스트와 Google Drive 콜백 재검증은 여전히 외부 청구 상태에 의해 차단된다.
