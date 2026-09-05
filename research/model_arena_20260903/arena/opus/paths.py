"""Filesystem layout and atomic-write helpers for the Opus lane.

Every path this lane writes lives under ``runs/opus5_subscription/`` or
``receipts/opus-*.json`` (ARENA_CONTRACT section 1). Nothing here writes outside
the campaign namespace.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Final

from arena.constants import NAMESPACE_ROOT

MODEL_KEY: Final = "opus5_subscription"

RUN_ROOT: Final = NAMESPACE_ROOT / "runs" / MODEL_KEY
RAW_DIR: Final = RUN_ROOT / "raw"
CANONICAL_DIR: Final = RUN_ROOT / "canonical"
RECEIPT_DIR: Final = RUN_ROOT / "receipts"
CANARY_DIR: Final = RUN_ROOT / "canary"
CHECKPOINT_PATH: Final = RUN_ROOT / "checkpoint.json"
RUN_SUMMARY_PATH: Final = RUN_ROOT / "run-summary.json"
CAMPAIGN_RECEIPT_DIR: Final = NAMESPACE_ROOT / "receipts"

PACKAGE_DIR: Final = Path(__file__).resolve().parent
PRICE_SNAPSHOT_PATH: Final = PACKAGE_DIR / "price_snapshot.json"
FALLBACK_PROMPT_PATH: Final = PACKAGE_DIR / "_fallback_prompt_v1.txt"
REGISTRY_PROMPT_PATH: Final = NAMESPACE_ROOT / "prompt_registry" / "opus5_transcription_v1.txt"

# ARENA_CONTRACT section 9: reject anything that looks like a credential before
# it reaches a receipt, a log line or a checkpoint.
_SECRET_PATTERNS: Final = (
    re.compile(r"rpa_[A-Za-z0-9]{8,}"),
    re.compile(r"\bhf_[A-Za-z0-9]{8,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}"),
    re.compile(r"\bghp_[A-Za-z0-9]{8,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bAKIA[0-9A-Z]{12,}"),
    re.compile(r"\bsk-ant-[A-Za-z0-9_-]{12,}"),
)

# A long opaque token: >= 60 base64 characters carrying upper case, lower case
# and digits. Deliberately narrower than "60 base64 characters" because a bare
# sha256 hex digest is 64 characters of [0-9a-f] and appears in every receipt.
_LONG_TOKEN_RE: Final = re.compile(r"[A-Za-z0-9+/]{60,}={0,2}")


class SecretLeakError(RuntimeError):
    """Raised when a value that is about to be persisted looks like a secret."""


def iter_strings(value: object) -> list[str]:
    """Flatten every string reachable from a JSON-ish value."""
    out: list[str] = []
    stack: list[object] = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, dict):
            stack.extend(item.keys())
            stack.extend(item.values())
        elif isinstance(item, (list, tuple)):
            stack.extend(item)
    return out


def assert_secret_free(value: object, *, where: str) -> None:
    """Fail closed if any reachable string matches a credential shape.

    The matched text is never echoed; only the pattern index and location are
    reported, so the error message itself cannot leak the secret.
    """
    for text in iter_strings(value):
        for index, pattern in enumerate(_SECRET_PATTERNS):
            if pattern.search(text):
                raise SecretLeakError(
                    f"{where}: a value matches secret pattern #{index}; refusing to persist it"
                )
        for match in _LONG_TOKEN_RE.finditer(text):
            token = match.group(0)
            if (
                any(c.islower() for c in token)
                and any(c.isupper() for c in token)
                and any(c.isdigit() for c in token)
            ):
                raise SecretLeakError(
                    f"{where}: a {len(token)}-character opaque token was found; "
                    "refusing to persist it"
                )


def canonical_json(payload: object) -> str:
    """Canonical JSON used for every hash in this campaign (contract section 2)."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_tagged(data: bytes) -> str:
    return f"sha256:{sha256_hex(data)}"


def atomic_write_bytes(path: Path, data: bytes) -> str:
    """Write ``data`` to ``path`` atomically; return ``"sha256:<hex>"``.

    Masterplan section 15.8: write ``<name>.tmp`` -> fsync -> rename. ``os.replace``
    is the atomic rename on Windows as well as POSIX.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    return sha256_tagged(data)


def atomic_write_text(path: Path, text: str) -> str:
    return atomic_write_bytes(path, text.encode("utf-8"))


def atomic_write_json(path: Path, payload: Any, *, where: str) -> str:
    """Validate secret-freedom, then write sorted-key UTF-8 JSON atomically."""
    assert_secret_free(payload, where=where)
    body = json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    return atomic_write_bytes(path, body.encode("utf-8"))


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


__all__ = [
    "CAMPAIGN_RECEIPT_DIR",
    "CANARY_DIR",
    "CANONICAL_DIR",
    "CHECKPOINT_PATH",
    "FALLBACK_PROMPT_PATH",
    "MODEL_KEY",
    "PACKAGE_DIR",
    "PRICE_SNAPSHOT_PATH",
    "RAW_DIR",
    "RECEIPT_DIR",
    "REGISTRY_PROMPT_PATH",
    "RUN_ROOT",
    "RUN_SUMMARY_PATH",
    "SecretLeakError",
    "assert_secret_free",
    "atomic_write_bytes",
    "atomic_write_json",
    "atomic_write_text",
    "canonical_json",
    "iter_strings",
    "read_json",
    "sha256_hex",
    "sha256_tagged",
]
