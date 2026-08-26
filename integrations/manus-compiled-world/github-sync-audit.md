# GitHub 동기화 감사 기록

## 2026-08-26 확인 사항

원격 GitHub 저장소 [`0ssol1620-byte/ai-knowledge-compiler`](https://github.com/0ssol1620-byte/ai-knowledge-compiler)의 기본 브랜치는 `main`이며, 확인 시점의 최신 커밋은 `bd0fb33` (`fix(web): mark sample-data-badge as client component`)였다.

이 저장소는 현재 Manus 프로젝트와 직접 교체 가능한 작업본이 아니다. GitHub 저장소는 Next.js 기반의 별도 엔터프라이즈 제품 구조이며, 자체적인 `/intake`, `/workspace`, `/app/*` 라우트와 독립 검증 체계를 가진다. 반면 현재 Manus 프로젝트는 React/Vite·Express·tRPC·MySQL 기반의 고객 직접 수집·컴파일 작업공간이다. 따라서 파일 전체를 덮어쓰는 방식의 동기화는 금지하고, TAVONEL 디자인·제품 계약·개별 기능을 선택적으로 이식하는 방식만 검토한다.

## RunPod 경계

GitHub 저장소의 `infra/runpod/README.md`는 모델 릴리스 산출물과 벤치마크 증거가 완성되기 전에는 RunPod 엔드포인트를 활성화하지 않도록 정의한다. 배포 비밀값은 공급자 제어면 또는 승인된 비밀 관리 도구에만 보관해야 하며, 저장소 커밋·브라우저 클라이언트·테넌트 전체 저장소 자격 증명에는 포함하지 않는다.

현재 Manus TAVONEL의 직접 업로드·원본 보존·서버 LLM 기반 컴파일에는 RunPod가 필요하지 않다. 실제 GPU OCR 또는 모델 실행 경로를 새로 도입할 때에만, 사용자 제공 `D:\Github_API.txt`에서 필요한 RunPod 항목을 서버 전용 비밀값으로 옮기고, 엔드포인트·콜백 인증·HMAC·허용 호스트·비용 한도를 별도 검토한다.
