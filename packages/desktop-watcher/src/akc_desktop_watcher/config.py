"""Watcher configuration (JSON always; YAML when PyYAML is installed).

Example JSON — see config.example.json:

    {
      "collection_id": "11111111-...",
      "job_id": null,
      "stability_window_seconds": 1.0,
      "poll_interval_seconds": 0.1,
      "journal_path": "akc-desktop-watcher-journal.jsonl",
      "event_sink_path": "akc-desktop-watcher-events.jsonl",
      "reconcile_on_start": true,
      "roots": [
        {"path": "C:/Users/me/Inbox",
         "source_root_id": "22222222-...",
         "exclude_globs": ["~$*", "*.tmp", ".git/**"]}
      ]
    }
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

_UUID36 = re.compile(r"^[0-9a-f-]{36}$")


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class RootConfig:
    path: Path  # absolute
    exclude_globs: tuple[str, ...] = ()
    source_root_id: str | None = None


@dataclass(frozen=True)
class WatcherConfig:
    roots: tuple[RootConfig, ...]
    collection_id: str
    job_id: str | None = None
    stability_window_seconds: float = 1.0
    poll_interval_seconds: float = 0.1
    journal_path: str = "akc-desktop-watcher-journal.jsonl"
    event_sink_path: str | None = None
    reconcile_on_start: bool = True
    initial_manifest_revision: int = 0

    @classmethod
    def from_file(cls, path: Path | str) -> WatcherConfig:
        file_path = Path(path)
        suffix = file_path.suffix.casefold()
        text = file_path.read_text(encoding="utf-8")
        if suffix in {".yaml", ".yml"}:
            try:
                import yaml  # type: ignore[import-untyped,unused-ignore]
            except ImportError as exc:  # pragma: no cover - env dependent
                raise ConfigError(
                    f"YAML config requires PyYAML ({exc}); install extra 'yaml' or use JSON"
                ) from exc
            data = yaml.safe_load(text)
        else:
            data = json.loads(text)
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: object) -> WatcherConfig:
        if not isinstance(data, dict):
            raise ConfigError("config root must be an object")
        allowed = {
            "roots",
            "collection_id",
            "job_id",
            "stability_window_seconds",
            "poll_interval_seconds",
            "journal_path",
            "event_sink_path",
            "reconcile_on_start",
            "initial_manifest_revision",
        }
        unknown = sorted(set(data) - allowed)
        if unknown:
            raise ConfigError(f"unknown config keys: {unknown}")

        roots_raw = data.get("roots")
        if not isinstance(roots_raw, list) or not roots_raw:
            raise ConfigError("'roots' must be a non-empty list")
        roots: list[RootConfig] = []
        for index, item in enumerate(roots_raw):
            roots.append(_parse_root(item, index))

        collection_id = data.get("collection_id")
        if not isinstance(collection_id, str) or not _UUID36.match(collection_id):
            raise ConfigError("'collection_id' must be a lowercase uuid string")

        job_id = data.get("job_id")
        if job_id is not None and (not isinstance(job_id, str) or not _UUID36.match(job_id)):
            raise ConfigError("'job_id' must be null or a lowercase uuid string")

        window = data.get("stability_window_seconds", 1.0)
        if not isinstance(window, int | float) or isinstance(window, bool) or window <= 0:
            raise ConfigError("'stability_window_seconds' must be > 0")

        poll = data.get("poll_interval_seconds", 0.1)
        if not isinstance(poll, int | float) or isinstance(poll, bool) or poll <= 0:
            raise ConfigError("'poll_interval_seconds' must be > 0")

        journal_path = data.get("journal_path", "akc-desktop-watcher-journal.jsonl")
        if not isinstance(journal_path, str) or not journal_path.strip():
            raise ConfigError("'journal_path' must be a non-empty string")

        event_sink_path = data.get("event_sink_path")
        if event_sink_path is not None and (
            not isinstance(event_sink_path, str) or not event_sink_path.strip()
        ):
            raise ConfigError("'event_sink_path' must be null or a non-empty string")

        reconcile = data.get("reconcile_on_start", True)
        if not isinstance(reconcile, bool):
            raise ConfigError("'reconcile_on_start' must be a boolean")

        initial_rev = data.get("initial_manifest_revision", 0)
        if isinstance(initial_rev, bool) or not isinstance(initial_rev, int) or initial_rev < 0:
            raise ConfigError("'initial_manifest_revision' must be an integer >= 0")

        return cls(
            roots=tuple(roots),
            collection_id=collection_id,
            job_id=job_id,
            stability_window_seconds=float(window),
            poll_interval_seconds=float(poll),
            journal_path=journal_path,
            event_sink_path=event_sink_path,
            reconcile_on_start=reconcile,
            initial_manifest_revision=initial_rev,
        )


def _parse_root(item: object, index: int) -> RootConfig:
    if not isinstance(item, dict):
        raise ConfigError(f"roots[{index}] must be an object")
    unknown = sorted(set(item) - {"path", "exclude_globs", "source_root_id"})
    if unknown:
        raise ConfigError(f"roots[{index}] unknown keys: {unknown}")
    raw_path = item.get("path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ConfigError(f"roots[{index}].path must be a non-empty string")
    path = Path(raw_path).expanduser().resolve()
    if not path.exists() or not path.is_dir():
        raise ConfigError(f"roots[{index}].path does not exist or is not a directory: {path}")

    globs_raw = item.get("exclude_globs", [])
    if not isinstance(globs_raw, list) or any(not isinstance(g, str) for g in globs_raw):
        raise ConfigError(f"roots[{index}].exclude_globs must be a list of strings")

    source_root_id = item.get("source_root_id")
    if source_root_id is not None and (
        not isinstance(source_root_id, str) or not _UUID36.match(source_root_id)
    ):
        raise ConfigError(f"roots[{index}].source_root_id must be null or a uuid string")

    return RootConfig(
        path=path,
        exclude_globs=tuple(globs_raw),
        source_root_id=source_root_id,
    )
