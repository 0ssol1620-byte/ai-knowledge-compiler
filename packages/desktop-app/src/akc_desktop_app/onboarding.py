"""Onboarding guidance printed after ``init`` (§17 flow).

Order matters: Health Scan first (it estimates compile work and surfaces
sensitive files before anything is compiled), then the first world compile,
then MCP connection. Every step is advisory text plus the exact command to
run; nothing here mutates the user's workspace.

Time-to-first-world: milestones are appended to ``<home>/logs/ttfw.jsonl``
by the CLI as they happen; :mod:`akc_desktop_app.ttfw` does the arithmetic.
"""

from __future__ import annotations

from pathlib import Path

from .config import DesktopAppConfig, WorkspaceEntry
from .ttfw import (
    PHASE_HEALTH_SCAN_COMPLETED,
    PHASE_INIT_COMPLETED,
    PHASE_INIT_STARTED,
    TtfwLog,
)


def print_next_steps(out, config: DesktopAppConfig, entry: WorkspaceEntry, slug: str) -> None:
    """Print the three-step onboarding guide after a successful init."""
    home = config.home
    watcher_json = home / "workspaces" / slug / "watcher.json"
    snippet = home / "mcp" / "claude-desktop-snippet.json"
    python = _python_hint()

    def say(line: str = "") -> None:
        print(line, file=out)

    say()
    say("온보딩 다음 단계:")
    say()
    say("  [1/3] Health Scan 실행 제안 — 컴파일 전 민감정보·중복·날짜 문제를 점검합니다.")
    report_json = home / "workspaces" / slug / "health-report.json"
    say(f'        {python} -m akc_health_scan "{entry.path}" --json "{report_json}"')
    say("        (다음부터: akc-desktop init --run-health-scan 옵션으로 즉시 실행 가능)")
    say()
    say("  [2/3] 첫 월드 컴파일 — compiler-runtime 트랙이 연결되면 여기에 표시된 명령으로")
    say("        첫 월드를 발행하세요. 월드가 발행되면 status가 이를 감지해")
    say("        time-to-first-world 를 기록합니다.")
    say(f"        월드 스토어: {config.world_store}")
    say()
    say("  [3/3] MCP 연결 — 생성된 스니펫을 MCP 클라이언트(Claude Desktop 등) 설정에 붙여넣으세요.")
    say(f"        스니펫: {snippet}")
    say(f"        watcher 설정(참고용): {watcher_json}")
    say("        serve 실행: akc-desktop serve   (watcher 백그라운드 + MCP stdio 동시 구동)")
    say()
    say("진행 상황 확인: akc-desktop status")


def log_init_milestones(home: Path, workspace_name: str) -> None:
    """Append init_started/init_completed if this is their first occurrence."""
    log = TtfwLog(home / "logs" / "ttfw.jsonl")
    if log.first_timestamp(PHASE_INIT_STARTED) is None:
        log.record(PHASE_INIT_STARTED, workspace=workspace_name)
    log.record(PHASE_INIT_COMPLETED, workspace=workspace_name)


def log_health_scan(home: Path, workspace_name: str) -> None:
    TtfwLog(home / "logs" / "ttfw.jsonl").record(
        PHASE_HEALTH_SCAN_COMPLETED, workspace=workspace_name
    )


def _python_hint() -> str:
    import shutil

    exe = shutil.which("python") or shutil.which("python3") or sys_executable()
    return exe


def sys_executable() -> str:
    import sys

    return sys.executable
