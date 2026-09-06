"""Deterministic JSON, hashing and atomic-write helpers for this lane.

Two properties matter here and are tested:

* **Determinism.** Every record this lane writes is canonical JSON
  (``sort_keys=True``, no spaces, ASCII-escaped) so its sha256 is stable across
  runs and hosts. Nothing hashed carries a wall-clock timestamp.
* **Atomicity.** ARENA_CONTRACT section 3.10: write ``<name>.tmp``, flush,
  fsync, rename with ``os.replace`` (atomic on Windows too).
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path
from typing import Any

from arena.tavonel.errors import TavonelError

SHA256_PREFIX = "sha256:"


def canonical_json(payload: object) -> str:
    """Canonical JSON text used for every id and every hash in this lane."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_hex(data: bytes | str) -> str:
    raw = data.encode("utf-8") if isinstance(data, str) else data
    return hashlib.sha256(raw).hexdigest()


def prefixed(hex_digest: str) -> str:
    """File-identifying hashes are written ``sha256:<hex>`` (contract section 2)."""
    return f"{SHA256_PREFIX}{hex_digest}"


def json_sha256_hex(payload: object) -> str:
    """Bare hex sha256 over canonical JSON — the shape used for job ids."""
    return sha256_hex(canonical_json(payload))


def record_digest(record: Mapping[str, Any], *, exclude: Iterable[str] = ()) -> str:
    """Bare hex sha256 of ``record`` with ``exclude`` fields removed.

    Used for ``signals_sha256`` and ``decision_sha256``: the digest field cannot
    be part of the body it digests.
    """
    dropped = set(exclude)
    body = {key: value for key, value in record.items() if key not in dropped}
    return json_sha256_hex(body)


def _atomic_write_bytes(path: Path, data: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    return prefixed(sha256_hex(data))


def write_bytes_atomic(path: Path, data: bytes) -> str:
    """Write ``data`` atomically; return the ``sha256:<hex>`` of the bytes written."""
    return _atomic_write_bytes(path, data)


def write_text_atomic(path: Path, text: str) -> str:
    return _atomic_write_bytes(path, text.encode("utf-8"))


def write_json_atomic(path: Path, payload: object) -> str:
    """Write canonical JSON plus a trailing newline; return its ``sha256:<hex>``."""
    return _atomic_write_bytes(path, (canonical_json(payload) + "\n").encode("utf-8"))


def write_jsonl_atomic(path: Path, rows: Iterable[Mapping[str, Any]]) -> str:
    body = "".join(canonical_json(row) + "\n" for row in rows)
    return _atomic_write_bytes(path, body.encode("utf-8"))


def load_json_object(path: Path) -> dict[str, Any]:
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise TavonelError(f"unreadable JSON at {path}: {exc}") from exc
    if not isinstance(parsed, dict):
        raise TavonelError(f"{path}: a JSON object is required, got {type(parsed).__name__}")
    return parsed


def iter_jsonl_objects(path: Path) -> Iterator[dict[str, Any]]:
    """Yield JSON objects from a JSONL file, refusing anything that is not one."""
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                parsed = json.loads(stripped)
            except ValueError as exc:
                raise TavonelError(f"{path}:{line_number}: not JSON: {exc}") from exc
            if not isinstance(parsed, dict):
                raise TavonelError(f"{path}:{line_number}: row is not a JSON object")
            yield parsed


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


__all__ = [
    "SHA256_PREFIX",
    "canonical_json",
    "iter_jsonl_objects",
    "json_sha256_hex",
    "load_json_object",
    "prefixed",
    "read_text",
    "record_digest",
    "sha256_hex",
    "write_bytes_atomic",
    "write_json_atomic",
    "write_jsonl_atomic",
    "write_text_atomic",
]
