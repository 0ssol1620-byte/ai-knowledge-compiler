#!/usr/bin/env python3
"""Windows path-length handling for the benchmark tools.

The public corpora carry filenames that are long by design: OmniDocBench keeps
the source document's full title, olmOCR-Bench embeds a content hash and a page
number, and ParseBench keeps the original report name. Nest any of those under a
staging or evaluation root and the resulting path passes the 260-character limit
that Windows still applies to most file APIs.

The failure is unhelpful when it happens. A copy stops partway with WinError 3
and leaves a half-populated tree, so the next step reads a corpus that is
quietly incomplete rather than one that is obviously broken. Every tool that
walks these trees needs the same fix, so it lives here once.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

__all__ = ["long_path", "safe_copy", "safe_exists", "safe_link_or_copy", "safe_makedirs"]


def long_path(path: Path | str) -> str:
    """Return a form of the path that is exempt from the 260-character limit.

    Non-Windows platforms have no such limit, so the path is returned unchanged
    and callers can use this unconditionally.
    """
    if os.name != "nt":
        return str(path)
    resolved = os.path.abspath(str(path))
    if resolved.startswith("\\\\?\\"):
        return resolved
    if resolved.startswith("\\\\"):
        return "\\\\?\\UNC\\" + resolved.lstrip("\\")
    return "\\\\?\\" + resolved


def safe_exists(path: Path | str) -> bool:
    return os.path.exists(long_path(path))


def safe_makedirs(path: Path | str) -> None:
    os.makedirs(long_path(path), exist_ok=True)


def safe_copy(source: Path | str, target: Path | str) -> None:
    safe_makedirs(Path(str(target)).parent)
    shutil.copy2(long_path(source), long_path(target))


def safe_link_or_copy(source: Path | str, target: Path | str) -> None:
    """Hard-link when the filesystem allows it, otherwise copy.

    Linking keeps a multi-gigabyte evaluation tree from being duplicated, but it
    fails across volumes and on some mounts, so the copy is the fallback rather
    than the default.
    """
    if not safe_exists(source):
        raise FileNotFoundError(source)
    safe_makedirs(Path(str(target)).parent)
    try:
        os.link(long_path(source), long_path(target))
    except OSError:
        shutil.copy2(long_path(source), long_path(target))
