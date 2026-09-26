"""Content-hash cache keyed by path + size + mtime so re-runs are fast.

Persisted at ``receipts/manifest-hash-cache.json``. The cache is a pure speed
optimization over ``arena.manifest.hashing.sha256_file`` — a cache miss (new
file, changed size, changed mtime) always falls back to a real hash, so a
stale or deleted cache file can never produce a wrong manifest, only a slower
rebuild.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from arena.manifest.hashing import sha256_file

_SCHEMA = "tavonel.arena.manifest-hash-cache.v1"


class HashCache:
    def __init__(self, cache_path: Path) -> None:
        self._cache_path = cache_path
        self._entries: dict[str, dict[str, Any]] = {}
        self._dirty = False
        if cache_path.is_file():
            try:
                loaded: Any = json.loads(cache_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                loaded = {}
            if isinstance(loaded, dict):
                entries = loaded.get("entries")
                if isinstance(entries, dict):
                    self._entries = entries

    def hash_file(self, path: Path, *, cache_key: str) -> str:
        stat = path.stat()
        cached = self._entries.get(cache_key)
        if (
            isinstance(cached, dict)
            and cached.get("size") == stat.st_size
            and cached.get("mtime") == stat.st_mtime
            and isinstance(cached.get("sha256"), str)
        ):
            return str(cached["sha256"])
        digest = sha256_file(path)
        self._entries[cache_key] = {
            "size": stat.st_size,
            "mtime": stat.st_mtime,
            "sha256": digest,
        }
        self._dirty = True
        return digest

    def flush(self) -> None:
        if not self._dirty:
            return
        payload = {"schema": _SCHEMA, "entries": self._entries}
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._cache_path.with_name(self._cache_path.name + ".tmp")
        tmp.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self._cache_path)
        self._dirty = False


__all__ = ["HashCache"]
