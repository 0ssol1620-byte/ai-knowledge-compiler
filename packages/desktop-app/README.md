# packages/desktop-app — `akc-desktop`

Personal Pro 데스크톱 패키징 기반(§17). 기존 로컬 컴포넌트(desktop-watcher,
local-mcp, health-scan, compiler-runtime)를 **단일 엔트리포인트 CLI**로 묶는
얇은 오케스트레이션 레이어다. 컴파일·감시·서빙 로직은 각 패키지에 남겨두고,
여기서는 등록/구동/상태/정리만 담당한다.

## 명령

| 명령 | 동작 |
| --- | --- |
| `akc-desktop init <경로>` | 워크스페이스 등록, `watcher.json` + MCP 클라이언트 스니펫 생성, 온보딩 안내 출력 |
| `akc-desktop serve` | watcher 백그라운드 스레드 + 읽기전용 MCP stdio 서버 동시 실행 (`--dry-run`, `--watch-only`) |
| `akc-desktop status [--json]` | 워크스페이스·발행된 월드·time-to-first-world 표시 |
| `akc-desktop uninstall` | 홈 디렉터리 안의 생성물만 제거하고 원본 워크스페이스 무영향을 해시로 검증 |

전역 옵션: `--config-home DIR`(테스트·포터블용), `--version`.

## 설정: `~/.tavonel/config.json`

```json
{
  "schema_version": 1,
  "workspaces": [
    {
      "name": "atlas-demo",
      "path": "D:/data/atlas-demo",
      "collection_id": "0f1e2d3c-...",
      "source_root_id": "a1b2c3d4-...",
      "registered_at": "2026-08-23T04:12:00+00:00",
      "exclude_globs": ["secret/**"]
    }
  ],
  "world_store_path": "~/.tavonel/world-state",
  "mcp": { "transport": "stdio", "port": null },
  "default_exclude_globs": ["~$*", "*.tmp", "~*", ".git/**", "Thumbs.db", ".DS_Store"]
}
```

- `collection_id`: uuid4, 최초 init 시 발급되어 고정.
- `source_root_id`: 이름+경로의 uuid5 → 재등록해도 저널 연속성 유지.
- `mcp.transport`: `stdio`(기본) 또는 `tcp`(+port).
- 제외 glob: 기본값 + 워크스페이스별 `exclude_globs` 병합.

홈 디렉터리는 `TAVONEL_HOME` 환경변수나 `--config-home` 으로 대체 가능
(테스트는 전부 이 경로를 tmp로 돌린다).

## 온보딩 흐름

1. `init` → Health Scan 실행 제안(`--run-health-scan` 으로 즉시 실행 가능)
2. 첫 월드 컴파일(compiler-runtime 트랙 연결 지점; 월드 스토어에 manifest가
   나타나면 `status`/`serve` 가 감지)
3. MCP 클라이언트(Claude Desktop 등)에 스니펫 붙여넣기

각 마일스톤은 `<home>/logs/ttfw.jsonl` 에 JSONL로 적히고, 첫 월드 발행 시
`init_started → world_detected` 경과가 계산된다(time-to-first-world).

## 의존성 정책

- CLI 자체는 stdlib(argparse)만 사용.
- `watchdog`(desktop-watcher), `mcp`(local-mcp), health-scan 은 **선택적**
  런타임 의존성 — 없으면 즉시 안내 메시지로 우아하게 저하한다.

## 테스트

```bash
uv run pytest packages/desktop-app/tests -q
```

Windows 서비스/시작프로그램 등록은 문서로만 제공한다:
[docs/desktop/RUNBOOK.md](../../docs/desktop/RUNBOOK.md).
