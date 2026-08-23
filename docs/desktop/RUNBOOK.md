# Desktop Runbook — Windows 상주 실행 (Personal Pro)

`akc-desktop` 의 백그라운드 상주는 **문서로만** 제공한다(코드로 서비스를
등록하지 않음). 아래 예시는 Windows 10/11 기준이며, 모든 경로/이름은
환경에 맞게 바꿔서 쓴다.

## 0. 전제

- 설치: 루트 venv 가 아니라 **패키지 자체 venv** 로 동기화한다.
  `cd /d D:\path\to\repo\packages\desktop-app` 후:

  ```bat
  UV_LINK_MODE=copy uv sync --extra dev --group runtime
  ```

  - `--extra dev`: pytest 등 테스트 도구
  - `--group runtime`: 실제 watcher(형제 패키지 path dep) + MCP SDK — `serve` 에 필요
- `akc_local_mcp` 는 아직 패키징 전(src-only, pyproject 없음)이므로 MCP 포함
  모드에서는 PYTHONPATH 에 소스 경로를 추가한다:

  ```bat
  set "PYTHONPATH=D:\path\to\repo\packages\local-mcp\src;%PYTHONPATH%"
  ```

- 설치 확인: `uv run akc-desktop --version` 이 `akc-desktop 0.1.0` 을 출력해야 한다.
- 최초 등록: `uv run akc-desktop init "D:\data\atlas-demo" --run-health-scan`
- 수동 구동 확인:
  - watcher 단독 검증: `uv run akc-desktop serve --dry-run`
  - MCP 포함 구동: PYTHONPATH 지정 후 `uv run akc-desktop serve` (Ctrl+C 로 종료)

## 1. 작업 스케줄러 등록 (로그온 시 serve 시작)

관리자 권한 cmd 하나로 끝난다. `schtasks` 예시:

```bat
schtasks /Create /TN "TavonelDesktopServe" ^
  /TR "\"C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python312\python.exe\" -m akc_desktop_app" ^
  /SC ONLOGON /RL LIMITED /F
```

주의:

- `/TR` 안의 python 경로는 `uv run python -c "import sys;print(sys.executable)"`
  으로 확인한 **프로젝트 venv 의 python** 이어야 한다. uv 전용 경로 예시:
  `%LOCALAPPDATA%\Packages\...` 가 아니라 `.venv\Scripts\python.exe`.
- 작업 이름은 고정(`TavonelDesktopServe`) — 삭제·조회 명령이 이 이름을 쓴다.
- ONLOGON 트리거는 로그온한 사용자 세션에서만 동작한다(부팅 즉시가 아님).

GUI 대안: 작업 스케줄러 → 작업 만들기 →

| 탭 | 값 |
| --- | --- |
| 일반 | "사용자가 로그온할 때만 실행", "가장 높은 권한으로 실행" 해제 |
| 트리거 | 새로 만들기 → 로그온할 때 → 특정 사용자 |
| 동작 | 프로그램 시작: `<venv>\Scripts\python.exe`, 인수 추가: `-m akc_desktop_app`, 시작 위치: 저장소 루트 |
| 설정 | "전원: 배터리 사용 시 중지" 체크 해제 권장 |

## 2. 시작프로그램 폴더 방식 (스케줄러보다 간단)

바로 가기 하나면 충분하다:

1. `Win+R` → `shell:startup`
2. 새 바로 가기 → 항목 위치:
   ```
   "D:\path\to\.venv\Scripts\python.exe" -m akc_desktop_app
   ```
3. 이름: `Tavonel Desktop Serve`

## 3. 로그 남기기

stdio 서버 특성상 stdout 은 JSON-RPC 전용이라 **화면/파일 출력은 stderr 와
저널 파일로만** 흐른다.

- watcher 저널/이벤트: `%USERPROFILE%\.tavonel\runtime\serve-journal.jsonl`,
  `serve-events.jsonl`
- 마일스톤(TTFW): `%USERPROFILE%\.tavonel\logs\ttfw.jsonl`
- 프로세스 stderr 를 파일로: schtasks 에서 직접 리다이렉트는 불가하므로,
  래퍼 배치를 만들어 등록한다:

```bat
@echo off
REM tavonel-serve.cmd — stderr 를 날짜별 파일로
cd /d D:\path\to\repo
"D:\path\to\.venv\Scripts\python.exe" -m akc_desktop_app 2>> "%USERPROFILE%\.tavonel\logs\serve-%DATE:.=-%.log"
```

## 4. 상태 점검 & 종료

아래 명령은 packages/desktop-app 의 venv 기준이다 (`cd packages\desktop-app` 후 실행).

```bat
:: 등록 상태 + 월드 + TTFW
uv run akc-desktop status

:: 프로세스 확인 (python -m akc_desktop_app)
tasklist /FI "IMAGENAME eq python.exe" /V | findstr akc_desktop_app

:: 정지 (PID 는 위에서 확인)
taskkill /PID <pid>

:: 등록된 스케줄러 작업 확인/삭제
schtasks /Query /TN "TavonelDesktopServe"
schtasks /Delete /TN "TavonelDesktopServe" /F
```

## 5. 제거 순서

1. `schtasks /Delete /TN "TavonelDesktopServe" /F` (또는 shell:startup 바로 가기 삭제)
2. `uv run akc-desktop uninstall` — 생성물만 제거되고 원본 워크스페이스는
   해시 비교로 무영향임을 증명해 준다.
3. 설정까지 지우려면: `uv run akc-desktop uninstall --purge-config`

## 6. 문제 해결

| 증상 | 확인 |
| --- | --- |
| `watchdog 미설치` 안내 | 패키지 디렉터리에서 `uv sync --extra dev --group runtime` 재실행 |
| `mcp 미설치` 안내 | PYTHONPATH 에 `packages\local-mcp\src` 추가 + `--group runtime` 으로 MCP SDK 설치 |
| status 에 월드가 계속 없음 | compiler-runtime 트랙의 발행 경로가 `world_store_path` 와 같은지 확인 |
| serve 가 바로 죽음 | `serve --dry-run` 으로 watcher 설정 검증 후 `~/.tavonel/logs/*.log` 확인 |
