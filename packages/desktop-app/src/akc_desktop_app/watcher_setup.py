"""Watcher config generation: Tavonel config.json -> desktop-watcher JSON.

Produces the exact schema ``akc_desktop_watcher.config.WatcherConfig``
accepts (see packages/desktop-watcher). The generated file lives under
``<home>/workspaces/<slug>/watcher.json`` so uninstall can remove it without
ever touching the user's workspace directory. Validation round-trips through
the real WatcherConfig parser when that package is importable.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from .config import DesktopAppConfig, WorkspaceEntry

WATCHER_CONFIG_VERSION = 1


class WatcherSetupError(RuntimeError):
    pass


@dataclass(frozen=True)
class GeneratedWatcherConfig:
    path: Path
    journal_path: Path
    event_sink_path: Path


def build_watcher_dict(config: DesktopAppConfig, entry: WorkspaceEntry) -> dict[str, object]:
    """Assemble the desktop-watcher JSON for one registered workspace."""
    slug = config.workspace_slug(entry)
    meta_dir = config.workspaces_meta_dir / slug
    runtime_dir = meta_dir / "runtime"
    return {
        "collection_id": entry.collection_id,
        "job_id": None,
        "stability_window_seconds": 1.0,
        "poll_interval_seconds": 0.1,
        "journal_path": str(runtime_dir / "journal.jsonl"),
        "event_sink_path": str(runtime_dir / "events.jsonl"),
        "reconcile_on_start": True,
        "roots": [
            {
                "path": str(Path(entry.path).expanduser().resolve()),
                "source_root_id": entry.source_root_id,
                "exclude_globs": list(config.effective_exclude_globs(entry)),
            }
        ],
    }


def write_watcher_config(config: DesktopAppConfig, entry: WorkspaceEntry) -> GeneratedWatcherConfig:
    """Write watcher.json atomically and validate it against the real parser."""
    payload = build_watcher_dict(config, entry)
    slug = config.workspace_slug(entry)
    meta_dir = config.workspaces_meta_dir / slug
    meta_dir.mkdir(parents=True, exist_ok=True)
    target = meta_dir / "watcher.json"
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, target)

    validate_watcher_dict(payload)

    journal = Path(str(payload["journal_path"]))
    events = Path(str(payload["event_sink_path"]))
    journal.parent.mkdir(parents=True, exist_ok=True)
    return GeneratedWatcherConfig(path=target, journal_path=journal, event_sink_path=events)


def build_serve_watcher_dict(config: DesktopAppConfig) -> dict[str, object]:
    """Combined multi-root watcher config covering every registered workspace."""
    if not config.workspaces:
        raise WatcherSetupError("no workspaces registered; run 'akc-desktop init' first")
    roots: list[dict[str, object]] = []
    for entry in config.workspaces:
        roots.append(
            {
                "path": str(Path(entry.path).expanduser().resolve()),
                "source_root_id": entry.source_root_id,
                "exclude_globs": list(config.effective_exclude_globs(entry)),
            }
        )
    runtime = config.runtime_dir
    return {
        "collection_id": config.workspaces[0].collection_id,
        "job_id": None,
        "stability_window_seconds": 1.0,
        "poll_interval_seconds": 0.1,
        "journal_path": str(runtime / "serve-journal.jsonl"),
        "event_sink_path": str(runtime / "serve-events.jsonl"),
        "reconcile_on_start": True,
        "roots": roots,
    }


def validate_watcher_dict(payload: dict[str, object]) -> None:
    """Round-trip through akc_desktop_watcher when installed (optional dep)."""
    try:
        from akc_desktop_watcher.config import ConfigError, WatcherConfig
    except ImportError:
        return  # desktop-watcher not installed; init still records its output
    try:
        WatcherConfig.from_dict(payload)
    except ConfigError as exc:
        raise WatcherSetupError(f"generated watcher config rejected: {exc}") from exc
