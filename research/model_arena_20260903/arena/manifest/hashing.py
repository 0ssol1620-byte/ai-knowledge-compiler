"""Small hashing helpers shared across ``arena.manifest``.

Kept intentionally tiny and dependency-free (stdlib only) so it can be
imported from a CPU box or a test with no optional packages installed.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def canonical_json(value: Any) -> str:
    """Deterministic JSON text: sorted keys, no ASCII-escaping, tight separators."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


__all__ = ["canonical_json", "sha256_bytes", "sha256_file", "sha256_text"]
