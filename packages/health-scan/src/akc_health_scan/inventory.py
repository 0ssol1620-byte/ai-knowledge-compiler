"""Filesystem inventory shared by every §5.2 analyzer (local I/O only)."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from .config import HealthScanConfig


@dataclass(frozen=True)
class FileRecord:
    rel_path: str  # posix-style, relative to the scan root
    abs_path: str
    suffix: str  # lowercase; extension-less dotfiles keep their full name
    size_bytes: int


def classify_suffix(path: Path) -> str:
    suffix = path.suffix.lower()
    if not suffix and path.name.startswith("."):
        return path.name.lower()
    return suffix


def iter_files(root: Path, config: HealthScanConfig) -> list[FileRecord]:
    """Deterministic walk: sorted dirs/files, excluded dir names pruned."""
    records: list[FileRecord] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in config.excluded_dir_names)
        for name in sorted(filenames):
            full = Path(dirpath) / name
            try:
                size = full.stat().st_size
            except OSError:
                continue
            records.append(
                FileRecord(
                    rel_path=full.relative_to(root).as_posix(),
                    abs_path=str(full),
                    suffix=classify_suffix(full),
                    size_bytes=size,
                )
            )
    return records


def read_text(record: FileRecord, config: HealthScanConfig) -> str | None:
    """Decoded UTF-8 text, or None for oversized/unreadable/binary files."""
    if record.size_bytes > config.max_content_bytes:
        return None
    try:
        raw = Path(record.abs_path).read_bytes()
    except OSError:
        return None
    if b"\x00" in raw[:8192]:
        return None
    return raw.decode("utf-8", errors="replace")


def sha256_of(record: FileRecord, config: HealthScanConfig) -> tuple[str | None, str | None]:
    """Streaming sha256. Returns ``(hex_digest, error_reason)``, exactly one set."""
    if record.size_bytes > config.max_hash_bytes:
        return None, f"file exceeds max_hash_bytes ({record.size_bytes})"
    digest = hashlib.sha256()
    try:
        with open(record.abs_path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        return None, f"unreadable: {exc.__class__.__name__}"
    return digest.hexdigest(), None


def compute_digests(
    records: list[FileRecord], config: HealthScanConfig
) -> tuple[dict[str, str], list[dict[str, str]]]:
    digests: dict[str, str] = {}
    skipped: list[dict[str, str]] = []
    for record in records:
        hex_digest, reason = sha256_of(record, config)
        if hex_digest is None:
            assert reason is not None
            skipped.append({"path": record.rel_path, "reason": reason})
        else:
            digests[record.rel_path] = hex_digest
    return digests, skipped
