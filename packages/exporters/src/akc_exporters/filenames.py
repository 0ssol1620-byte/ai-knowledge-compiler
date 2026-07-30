"""Portable, deterministic filenames for Vault and ZIP exports."""

from __future__ import annotations

import re
import unicodedata
from pathlib import PurePosixPath

from akc_cir import sha256_digest
from akc_security import safe_relative_path

_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


def portable_slug(value: str, *, fallback: str = "untitled", max_length: int = 96) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = "".join(
        character for character in normalized if not unicodedata.category(character).startswith("C")
    )
    normalized = re.sub(r'[<>:"/\\|?*#^[\]]+', " ", normalized)
    normalized = re.sub(r"\s+", "-", normalized).strip("-. ")
    normalized = re.sub(r"-{2,}", "-", normalized)
    if not normalized:
        normalized = fallback
    if normalized.upper() in _RESERVED:
        normalized = f"_{normalized}"
    return normalized[:max_length].rstrip("-. ") or fallback


def stable_markdown_filename(title: str, stable_id: str) -> str:
    slug = portable_slug(title, max_length=80)
    suffix = sha256_digest(stable_id)[7:15]
    return f"{slug}--{suffix}.md"


def collision_key(path: str) -> str:
    safe = safe_relative_path(path)
    return unicodedata.normalize("NFC", safe).casefold()


def with_collision_suffix(path: str, seed: str) -> str:
    safe = safe_relative_path(path)
    candidate = PurePosixPath(safe)
    suffix = sha256_digest(seed)[7:15]
    return str(candidate.with_name(f"{candidate.stem}--{suffix}{candidate.suffix}"))
