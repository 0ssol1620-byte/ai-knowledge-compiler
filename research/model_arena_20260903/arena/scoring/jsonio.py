"""Deterministic, atomic, long-path-safe file IO for the scoring lane.

Three Windows-and-integrity concerns are handled once, here, rather than at
every call site.

*Long paths.* ParseBench ships source names 199 characters long and
OmniDocBench ships CJK names; an evaluator input path built from them passes
the 260-character MAX_PATH limit. :func:`io_path` returns the ``\\\\?\\``
extended-length form on Windows so a write neither fails nor - worse -
silently reports "missing" through ``Path.is_file``.

*Atomic writes.* ``<name>.tmp`` -> fsync -> rename (masterplan section 15.8).
A crash leaves a ``.tmp`` no reader looks at, never a half-written score.

*One JSON shape.* Everything this lane writes is UTF-8 with sorted keys, so
two runs over the same inputs produce byte-identical files and a digest is
worth quoting.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

__all__ = [
    "canonical_json",
    "canonical_sha256",
    "io_path",
    "prefixed",
    "read_json",
    "read_jsonl",
    "read_text",
    "sha256_bytes",
    "sha256_file",
    "sha256_hex",
    "utc_now_iso",
    "write_bytes_atomic",
    "write_json_atomic",
    "write_jsonl_atomic",
    "write_text_atomic",
]


def io_path(path: Path) -> Path:
    """The form of ``path`` the OS will accept for a file operation.

    On Windows an absolute path is returned in its extended-length form; every
    other case is returned unchanged.
    """

    if os.name != "nt" or not path.is_absolute():
        return path
    text = str(path)
    if text.startswith("\\\\?\\"):
        return path
    if text.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + text.lstrip("\\"))
    return Path("\\\\?\\" + text)


def canonical_json(value: Any) -> str:
    """Sorted-key JSON with a stable separator set. ``NaN`` is refused."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
        allow_nan=False,
    )


def _compact_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def prefixed(hex_digest: str) -> str:
    return f"sha256:{hex_digest}"


def sha256_bytes(data: bytes | str) -> str:
    return prefixed(sha256_hex(data))


def canonical_sha256(value: Any) -> str:
    """Digest of a value's compact canonical JSON, without writing a file."""

    return sha256_bytes(_compact_json(value))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with io_path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return prefixed(digest.hexdigest())


def read_text(path: Path) -> str:
    return io_path(path).read_text(encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(read_text(path))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Every JSON object in a ``.jsonl`` file. A non-object line is an error."""

    rows: list[dict[str, Any]] = []
    with io_path(path).open("r", encoding="utf-8") as handle:
        for number, raw in enumerate(handle, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{number} is not valid JSON: {exc}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{number} is not a JSON object")
            rows.append(value)
    return rows


def write_bytes_atomic(path: Path, data: bytes) -> str:
    """Write bytes atomically; return ``"sha256:<hex>"`` read back from disk."""

    target = io_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    with tmp.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    digest = sha256_bytes(data)
    on_disk = sha256_file(tmp)
    if on_disk != digest:  # pragma: no cover - filesystem corruption
        tmp.unlink(missing_ok=True)
        raise OSError(f"atomic write verification failed for {path}")
    os.replace(tmp, target)
    return digest


def write_text_atomic(path: Path, text: str) -> str:
    return write_bytes_atomic(path, text.encode("utf-8"))


def write_json_atomic(path: Path, payload: Mapping[str, Any]) -> str:
    return write_text_atomic(path, canonical_json(payload) + "\n")


def write_jsonl_atomic(path: Path, rows: Iterable[Mapping[str, Any]]) -> str:
    body = "".join(_compact_json(row) + "\n" for row in rows)
    return write_text_atomic(path, body)


def utc_now_iso() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
