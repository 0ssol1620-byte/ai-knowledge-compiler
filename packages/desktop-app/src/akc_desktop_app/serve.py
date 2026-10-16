"""``serve`` — watcher background threads + read-only MCP stdio, one process.

Concurrency model:

- The desktop-watcher owns its own threads (watchdog Observer + scheduler);
  ``DesktopWatcher.start()`` returns immediately after they are live.
- The main thread then runs the MCP server over stdio, which blocks until the
  client disconnects or Ctrl+C arrives. Nothing from the watcher may ever
  touch stdout while the MCP server is running — stdout carries JSON-RPC —
  so all diagnostics go to stderr here.
- ``--dry-run`` starts the watcher and stops it again immediately without
  touching stdio; used by tests and by users verifying registration before
  wiring a real MCP client.
- ``--watch-only`` keeps watching when no MCP client should be attached yet.

Both heavy dependencies are optional at import time; when absent we fail
with explicit guidance instead of a traceback.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Protocol, TextIO

from .config import DesktopAppConfig
from .ttfw import PHASE_WORLD_DETECTED, TtfwLog, find_worlds
from .watcher_setup import WatcherSetupError, build_serve_watcher_dict

logger = logging.getLogger("akc_desktop_app.serve")

EXIT_OK = 0
EXIT_INTERRUPTED = 130


class WatcherLike(Protocol):
    """Minimal surface of akc_desktop_watcher.DesktopWatcher we rely on."""

    def start(self) -> None: ...

    def stop(self, timeout: float = 5.0) -> None: ...


class McpRunner(Protocol):
    """Blocking callable that serves MCP until the client disconnects."""

    def __call__(self) -> None: ...


def default_watcher_factory(config: DesktopAppConfig) -> Callable[[], WatcherLike]:
    """Build the real DesktopWatcher (lazy import; watchdog optional dep)."""

    def factory() -> WatcherLike:
        try:
            from akc_desktop_watcher import DesktopWatcher
            from akc_desktop_watcher.config import ConfigError, WatcherConfig
        except ImportError as exc:
            raise WatcherSetupError(
                "akc_desktop_watcher (watchdog) 가 설치되어 있지 않습니다. "
                "설치 예: uv sync --extra dev --group local-mcp"
            ) from exc
        payload = build_serve_watcher_dict(config)
        try:
            watcher_config = WatcherConfig.from_dict(payload)
        except ConfigError as exc:
            raise WatcherSetupError(f"serve watcher config rejected: {exc}") from exc
        watcher: WatcherLike = DesktopWatcher(watcher_config)
        return watcher

    return factory


def default_mcp_runner(config: DesktopAppConfig) -> McpRunner:
    """MCP stdio runner bound to the configured world store (lazy import)."""
    try:
        from akc_local_mcp.server import build_server
        from akc_local_mcp.settings import LocalMcpSettings
    except ImportError as exc:
        raise WatcherSetupError(
            "akc_local_mcp (mcp) 가 설치되어 있지 않습니다. "
            "설치 예: uv sync --extra dev --group local-mcp"
        ) from exc

    def run() -> None:
        settings = LocalMcpSettings(world_state_dir=Path(config.world_store))
        build_server(settings).run()

    return run


def detect_and_log_worlds(config: DesktopAppConfig) -> list[str]:
    """Log world_detected once when published worlds first appear."""
    worlds = find_worlds(Path(config.world_store))
    if not worlds:
        return []
    log = TtfwLog(config.ttfw_log)
    if not log.has_world_for_any_workspace():
        log.record(
            PHASE_WORLD_DETECTED,
            worlds=[world.world_id for world in worlds],
            store=str(config.world_store),
        )
    return [world.world_id for world in worlds]


def _wait_for_interrupt(err: TextIO) -> None:
    """Sleep until Ctrl+C; periodic wakeups keep signals deliverable."""
    stop = threading.Event()
    print("(waiting — Ctrl+C to stop)", file=err)
    try:
        while not stop.wait(0.5):
            time.sleep(0)
    except KeyboardInterrupt:
        pass


def run_serve(
    config: DesktopAppConfig,
    *,
    out: TextIO,
    err: TextIO,
    dry_run: bool = False,
    watch_only: bool = False,
    watcher_factory: Callable[[], WatcherLike] | None = None,
    mcp_runner: McpRunner | None = None,
) -> int:
    """Run serve; returns the process exit code."""
    if watcher_factory is None:
        watcher_factory = default_watcher_factory(config)

    roots = tuple(str(Path(ws.path)) for ws in config.workspaces)
    watcher = watcher_factory()
    watcher.start()
    logger.info("watcher started for %d root(s)", len(roots))
    try:
        if dry_run:
            print(
                f"dry-run: watcher started ({len(roots)} root(s)); stopping immediately.",
                file=out,
            )
            return EXIT_OK

        detected = detect_and_log_worlds(config)
        if detected:
            print(f"published worlds: {', '.join(detected)}", file=err)
        else:
            print("no published worlds yet; time-to-first-world timer still running.", file=err)

        if watch_only or mcp_runner is None:
            reason = "--watch-only" if watch_only else "MCP unavailable"
            print(f"{reason}: switching to watch-only mode.", file=err)
            _wait_for_interrupt(err)
            return EXIT_OK

        print("serving MCP on stdio (Ctrl+C to stop); watcher running in background.", file=err)
        try:
            mcp_runner()
        except KeyboardInterrupt:
            pass
        return EXIT_OK
    finally:
        watcher.stop()
        logger.info("watcher stopped")
