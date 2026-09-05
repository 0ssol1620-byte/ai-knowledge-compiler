"""Small helpers shared by the on-pod worker.

Standard library only. Every module under ``arena.worker`` is copied verbatim
into each model runtime image, so nothing here may import a third-party package
(``pillow`` is the single exception and it lives in ``synthetic.py``).
"""

from __future__ import annotations

import hashlib
import itertools
import json
import os
import re
import threading
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from arena.worker.compat import UTC

MAX_ERROR_CHARS: Final = 2000
REDACTED: Final = "[REDACTED]"


def utcnow() -> str:
    """ISO-8601 UTC with milliseconds, ``Z`` suffix."""
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def canonical_json_bytes(obj: Any) -> bytes:
    """Canonical JSON per ARENA_CONTRACT section 2 (sorted, compact, ASCII)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_label(data: bytes) -> str:
    """``sha256:<hex>`` — the file-identifying form used across the campaign."""
    return f"sha256:{sha256_hex(data)}"


def sha256_file_label(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def config_sha256(obj: Any) -> str:
    """Hash of a config object over its canonical JSON encoding."""
    return sha256_label(canonical_json_bytes(obj))


# --------------------------------------------------------------------------
# Redaction (ARENA_CONTRACT section 9, masterplan section 39)
# --------------------------------------------------------------------------

_SECRET_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"rpa_[A-Za-z0-9]{8,}"),
    re.compile(r"\bhf_[A-Za-z0-9]{8,}"),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"\bghp_[A-Za-z0-9]{8,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{8,}"),
    re.compile(r"\bAKIA[0-9A-Z]{8,}"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{12,}"),
    re.compile(r"(?i)\b(authorization|api[_-]?key|secret|password|token)\s*[=:]\s*\S+"),
)
_BLOB = re.compile(r"[A-Za-z0-9+/_\-]{40,}={0,2}")
_HEX_DIGEST = re.compile(r"[0-9a-fA-F]{32,64}")


def _blob_replacement(match: re.Match[str]) -> str:
    text = match.group(0)
    # sha256/sha1/md5 digests are identifiers, not secrets; keep them readable.
    if _HEX_DIGEST.fullmatch(text):
        return text
    return REDACTED


def redact(text: str) -> str:
    """Remove anything that looks like a credential from free text."""
    out = text
    for pattern in _SECRET_PATTERNS:
        out = pattern.sub(REDACTED, out)
    return _BLOB.sub(_blob_replacement, out)


def safe_error(error: BaseException | str, *, limit: int = MAX_ERROR_CHARS) -> str:
    """Secret-free, length-bounded message for a receipt or a log line."""
    text = error if isinstance(error, str) else f"{type(error).__name__}: {error}"
    text = redact(text.replace("\r", " "))
    if len(text) > limit:
        text = text[: limit - 3] + "..."
    return text


# --------------------------------------------------------------------------
# Atomic writes (masterplan section 15.8)
# --------------------------------------------------------------------------


_TMP_COUNTER = itertools.count()


def atomic_write_bytes(path: Path, data: bytes) -> str:
    """``<name>.<unique>.tmp`` → fsync → ``os.replace``. Returns ``sha256:<hex>``.

    The temp name carries pid, thread id and a counter because two jobs can
    legitimately target the same final path at the same time — an inference and
    a recovery pass over one ``case_key``, for instance. A shared ``<name>.tmp``
    made those two writers corrupt each other's file (and, on Windows, fail the
    rename outright).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    unique = f"{os.getpid()}.{threading.get_ident()}.{next(_TMP_COUNTER)}"
    tmp = path.parent / f"{path.name}.{unique}.tmp"
    try:
        with tmp.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return sha256_label(data)


def atomic_write_json(path: Path, obj: Any) -> str:
    payload = json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
    return atomic_write_bytes(path, payload + b"\n")


def jsonable(value: Any) -> Any:
    """Best-effort JSON projection that never raises and never invents data."""
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [jsonable(item) for item in value]
    return repr(value)


__all__ = [
    "MAX_ERROR_CHARS",
    "REDACTED",
    "atomic_write_bytes",
    "atomic_write_json",
    "canonical_json_bytes",
    "config_sha256",
    "jsonable",
    "redact",
    "safe_error",
    "sha256_file_label",
    "sha256_hex",
    "sha256_label",
    "utcnow",
]
