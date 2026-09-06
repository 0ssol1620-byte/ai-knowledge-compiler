"""Canonical JSON, sha256 and atomic writes (ARENA_CONTRACT sections 2 and 3.10)."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

#: ARENA_CONTRACT section 2: canonical JSON is sorted, tight and ASCII.
CANONICAL_SEPARATORS = (",", ":")


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=CANONICAL_SEPARATORS, ensure_ascii=True)


def canonical_sha256(payload: Any) -> str:
    """``sha256:<hex>`` over the canonical JSON of ``payload``."""
    digest = hashlib.sha256(canonical_json(payload).encode("ascii")).hexdigest()
    return f"sha256:{digest}"


def pretty_json(payload: Any) -> str:
    """Registry file text: sorted keys, 2-space indent, trailing newline."""
    return json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def write_json_atomic(path: Path, payload: Any) -> str:
    """Write ``payload`` to ``path`` via tmp + fsync + os.replace. Returns its sha256."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = pretty_json(payload)
    data = text.encode("utf-8")
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


__all__ = [
    "CANONICAL_SEPARATORS",
    "canonical_json",
    "canonical_sha256",
    "pretty_json",
    "write_json_atomic",
]
