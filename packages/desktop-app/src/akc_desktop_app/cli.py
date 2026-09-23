"""Single desktop entry point: ``akc-desktop {init,serve,status,uninstall}``.

argparse (stdlib) keeps the package dependency-free; typer would add an
unlocked dependency to a ``--frozen`` lockfile. User-facing strings are
Korean (Personal Pro audience); machine-readable output (``--json``) and
log phases are English.

Exit codes: 0 success, 1 runtime failure (e.g. uninstall safety trip),
2 configuration/usage error, 130 interrupted.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TextIO

from . import __version__
from .config import (
    ENV_TAVONEL_HOME,
    ConfigError,
    DesktopAppConfig,
    WorkspaceEntry,
    derive_source_root_id,
    load_config,
    new_collection_id,
    save_config,
    utc_now_iso,
)
from .mcp_setup import write_mcp_artifacts
from .onboarding import log_health_scan, log_init_milestones, print_next_steps
from .serve import EXIT_INTERRUPTED, EXIT_OK, run_serve
from .ttfw import TtfwLog, find_worlds
from .uninstall import UninstallSafetyError, execute_uninstall, plan_uninstall
from .watcher_setup import write_watcher_config

EXIT_FAILURE = 1
EXIT_USAGE = 2


def build_parser() -> argparse.ArgumentParser:
    # ``--config-home`` lives on a shared parent so it is accepted BOTH before
    # the subcommand (akc-desktop --config-home X status) and after it
    # (akc-desktop status --config-home X) — scripts and tests use the latter.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--config-home",
        default=None,
        metavar="DIR",
        help=f"Tavonel 홈 디렉터리 (기본: ~/.tavonel 또는 {ENV_TAVONEL_HOME} 환경변수)",
    )
    parser = argparse.ArgumentParser(
        prog="akc-desktop",
        parents=[common],
        description=(
            "Tavonel Personal Pro 데스크톱 엔트리포인트: 워크스페이스 등록(init), "
            "watcher+MCP 동시 구동(serve), 상태 확인(status), 생성물 정리(uninstall)."
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_p = subparsers.add_parser(
        "init", parents=[common], help="워크스페이스 등록 + watcher/MCP 설정 생성"
    )
    init_p.add_argument("path", help="워크스페이스 디렉터리")
    init_p.add_argument("--name", default=None, help="표시 이름(기본: 디렉터리 이름)")
    init_p.add_argument(
        "--exclude", action="append", default=[], metavar="GLOB", help="추가 제외 glob(반복 가능)"
    )
    init_p.add_argument(
        "--run-health-scan",
        action="store_true",
        help="등록 직후 Health Scan을 즉시 실행",
    )

    serve_p = subparsers.add_parser(
        "serve", parents=[common], help="watcher 백그라운드 + MCP stdio 동시 실행"
    )
    serve_p.add_argument(
        "--dry-run",
        action="store_true",
        help="watcher 시작 직후 종료(설정 검증용)",
    )
    serve_p.add_argument(
        "--watch-only",
        action="store_true",
        help="MCP 없이 watcher만 유지",
    )

    status_p = subparsers.add_parser(
        "status", parents=[common], help="등록 상태·월드·time-to-first-world 표시"
    )
    status_p.add_argument("--json", dest="as_json", action="store_true", help="JSON 출력")

    rm_p = subparsers.add_parser(
        "uninstall", parents=[common], help="akc-desktop 이 생성한 산출물만 제거"
    )
    rm_p.add_argument("--purge-config", action="store_true", help="config.json 까지 삭제")
    rm_p.add_argument("--dry-run", action="store_true", help="삭제 목록만 표시")
    rm_p.add_argument("--yes", action="store_true", help="확인 프롬프트 생략")

    return parser


def _resolve_home(args: argparse.Namespace) -> Path:
    raw = getattr(args, "config_home", None)
    if raw:
        return Path(raw).expanduser()
    from .config import default_home

    return default_home()


def cmd_init(args: argparse.Namespace, out: TextIO, err: TextIO) -> int:
    root = Path(args.path).expanduser()
    if not root.exists() or not root.is_dir():
        print(f"오류: 워크스페이스 디렉터리가 아닙니다: {root}", file=err)
        return EXIT_USAGE

    config = load_config(_resolve_home(args))
    resolved = str(root.resolve())

    existing = config.find_workspace(resolved)
    if existing is not None:
        print(f"이미 등록된 워크스페이스입니다: {existing.name} ({resolved})", file=out)
        print("제외 glob 을 바꾸려면 uninstall 후 다시 init 하세요.", file=out)
        return EXIT_OK

    name = args.name.strip() if args.name and args.name.strip() else root.name
    names = {ws.name for ws in config.workspaces}
    if name in names:
        print(f"오류: 워크스페이스 이름 '{name}' 이 이미 사용 중입니다.", file=err)
        return EXIT_USAGE

    entry = WorkspaceEntry(
        name=name,
        path=resolved,
        collection_id=new_collection_id(),
        source_root_id=derive_source_root_id(name, resolved),
        registered_at=utc_now_iso(),
        exclude_globs=tuple(dict.fromkeys(args.exclude)),
    )
    updated = DesktopAppConfig(
        home=config.home,
        schema_version=config.schema_version,
        workspaces=(*config.workspaces, entry),
        world_store_path=config.world_store_path,
        mcp=config.mcp,
        default_exclude_globs=config.default_exclude_globs,
    )
    saved = save_config(updated)
    slug = updated.workspace_slug(entry)
    watcher = write_watcher_config(updated, entry)
    mcp_artifacts = write_mcp_artifacts(updated)

    log_init_milestones(updated.home, name)

    print(f"등록 완료: {name} -> {resolved}", file=out)
    print(f"  config      : {saved}", file=out)
    print(f"  watcher 설정: {watcher.path}", file=out)
    print(f"  MCP 스니펫  : {mcp_artifacts.snippet_path}", file=out)

    if args.run_health_scan:
        code = _run_health_scan_inline(entry, slug, updated, out, err)
        if code != EXIT_OK:
            return code

    print_next_steps(out, updated, entry, slug)
    return EXIT_OK


def _run_health_scan_inline(
    entry: WorkspaceEntry, slug: str, config: DesktopAppConfig, out: TextIO, err: TextIO
) -> int:
    try:
        from akc_health_scan.config import HealthScanConfig
        from akc_health_scan.scanner import scan
    except ImportError:
        print(
            "akc_health_scan 미설치 — Health Scan 건너뜀 (온보딩 [1/3] 명령으로 나중에 실행)",
            file=err,
        )
        return EXIT_OK

    report_path = config.workspaces_meta_dir / slug / "health-report.json"
    print(f"Health Scan 실행 중: {entry.path}", file=err)
    report = scan(Path(entry.path), HealthScanConfig())
    payload = report.to_dict()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    log_health_scan(config.home, entry.name)
    print(f"  보고서: {report_path}", file=out)
    _print_health_summary(payload, out)
    return EXIT_OK


def _print_health_summary(payload: dict[str, object], out: TextIO) -> None:
    def section(key: str, sub_key: str) -> object:
        block = payload.get(key)
        if isinstance(block, dict):
            return block.get(sub_key)
        return None

    discovered = section("sources", "discovered_files")
    sensitive = section("sensitive_exposure", "findings")
    duplicates = section("duplicates", "exact_duplicate_clusters")
    estimate = payload.get("estimated_compile_work") or {}
    tokens = estimate.get("estimated_tokens") if isinstance(estimate, dict) else None

    print(f"  발견 파일     : {discovered}", file=out)
    print(f"  민감정보 항목 : {len(sensitive) if isinstance(sensitive, list) else '?'}", file=out)
    print(f"  정확 중복군   : {len(duplicates) if isinstance(duplicates, list) else '?'}", file=out)
    if isinstance(tokens, int):
        print(f"  컴파일 추정   : {tokens:,} tokens", file=out)


def cmd_serve(args: argparse.Namespace, out: TextIO, err: TextIO) -> int:
    config = load_config(_resolve_home(args))
    if not config.workspaces:
        print(
            "등록된 워크스페이스가 없습니다. 먼저 'akc-desktop init <경로>' 를 실행하세요.",
            file=err,
        )
        return EXIT_USAGE
    try:
        return run_serve(
            config,
            out=out,
            err=err,
            dry_run=args.dry_run,
            watch_only=args.watch_only,
        )
    except Exception as exc:  # WatcherSetupError 및 설정 오류를 사용자 언어로 변환
        print(f"오류: {exc}", file=err)
        return EXIT_USAGE


def cmd_status(args: argparse.Namespace, out: TextIO, err: TextIO) -> int:
    config = load_config(_resolve_home(args))

    worlds = find_worlds(config.world_store)
    from .serve import detect_and_log_worlds  # 로컬 임포트로 순환 회피

    detected = detect_and_log_worlds(config) if config.workspaces else []

    log = TtfwLog(config.ttfw_log)
    seconds = log.seconds_to_first_world()

    if args.as_json:
        payload = {
            "home": str(config.home),
            "workspaces": [ws.to_dict() for ws in config.workspaces],
            "world_store": str(config.world_store),
            "worlds": [
                {"world_id": w.world_id, "manifest": str(w.manifest_path)} for w in worlds
            ],
            "mcp": config.mcp.to_dict(),
            "ttfw": {
                "started_at": log.first_timestamp("init_started"),
                "first_world_at": log.first_timestamp("world_detected"),
                "seconds_to_first_world": seconds,
                "log": str(config.ttfw_log),
            },
            "artifacts": {
                "runtime_dir_exists": config.runtime_dir.exists(),
                "mcp_snippet_exists": (config.mcp_dir / "claude-desktop-snippet.json").exists(),
                "logs_exist": config.ttfw_log.exists(),
            },
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2), file=out)
        return EXIT_OK

    print(f"Tavonel 홈 : {config.home}", file=out)
    print(f"MCP 전송   : {config.mcp.transport}" + (
        f" (port {config.mcp.port})" if config.mcp.port is not None else ""
    ), file=out)
    print(f"월드 스토어: {config.world_store}", file=out)
    if not config.workspaces:
        print("워크스페이스: (없음 — 'akc-desktop init <경로>')", file=out)
    else:
        print("워크스페이스:", file=out)
        for ws in config.workspaces:
            slug = config.workspace_slug(ws)
            marker = "*" if ws.name in detected else " "
            print(
                f"  {marker} {ws.name}  {ws.path}",
                file=out,
            )
            print(
                f"      collection={ws.collection_id[:8]}…  등록={ws.registered_at}  메타={slug}/",
                file=out,
            )
    if worlds:
        print(f"발행된 월드({len(worlds)}): " + ", ".join(w.world_id for w in worlds), file=out)
    else:
        print("발행된 월드: (아직 없음)", file=out)
    print(log.summary(), file=out)
    return EXIT_OK


def cmd_uninstall(args: argparse.Namespace, out: TextIO, err: TextIO) -> int:
    config = load_config(_resolve_home(args))
    plan = plan_uninstall(config, purge_config=args.purge_config)

    if plan.empty and not config.workspaces:
        print("제거할 생성물이 없습니다.", file=out)
        return EXIT_OK

    print("삭제 예정인 생성물:", file=out)
    for directory in plan.directories:
        print(f"  dir  {directory}", file=out)
    for path in plan.files:
        print(f"  file {path}", file=out)
    if plan.config_file is not None:
        print(f"  file {plan.config_file}  (--purge-config)", file=out)
    for outside in plan.outside_home:
        print(f"  skip {outside}  (홈 밖/워크스페이스 내부라 제외)", file=out)
    print(
        f"보호 대상 원본 워크스페이스: {len(config.workspaces)}개"
        + ("".join(f"\n  - {ws.name}: {ws.path}" for ws in config.workspaces)),
        file=out,
    )

    if args.dry_run:
        print("dry-run: 아무것도 삭제하지 않았습니다.", file=out)
        return EXIT_OK

    if not args.yes and sys.stdin.isatty():
        answer = input("위 목록을 삭제할까요? [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            print("취소했습니다.", file=out)
            return EXIT_OK

    try:
        result = execute_uninstall(config, plan)
    except (UninstallSafetyError, OSError) as exc:
        print(f"오류: 제거 중 안전 검증 실패: {exc}", file=err)
        return EXIT_FAILURE

    print(
        f"제거 완료: 파일 {result.removed_files}건, 디렉터리 {result.removed_directories}건",
        file=out,
    )
    if result.kept_outside_home:
        print("홈 밖이라 남긴 경로: " + ", ".join(result.kept_outside_home), file=out)
    verified = (
        ", ".join(result.workspaces_verified) if result.workspaces_verified else "(해당 없음)"
    )
    print(f"원본 무영향 확인: {verified}", file=out)
    return EXIT_OK


_COMMANDS = {
    "init": cmd_init,
    "serve": cmd_serve,
    "status": cmd_status,
    "uninstall": cmd_uninstall,
}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = _COMMANDS[args.command]
    try:
        return handler(args, sys.stdout, sys.stderr)
    except ConfigError as exc:
        print(f"설정 오류: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except KeyboardInterrupt:
        print("\n중단되었습니다.", file=sys.stderr)
        return EXIT_INTERRUPTED


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
