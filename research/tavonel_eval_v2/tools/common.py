"""Neutral utilities for the v2 research namespace.

Deliberately narrow. This module may be imported by acquisition,
canonicalisation, the selective compiler and the report writers. It must never
be imported by ``oracle/independent_full_build.py``: the independent full
rebuild stands on the standard library alone so that a defect here cannot be
common-mode across both sides of an equivalence comparison. The comparator does
not import it either.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
NS = ROOT / "research" / "tavonel_eval_v2"


def now() -> str:
    return datetime.now(UTC).isoformat()


def sha_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def sha_text(text: str) -> str:
    return sha_bytes(text.encode("utf-8"))


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_sha(value: Any) -> str:
    return sha_bytes(canonical_json(value).encode("utf-8"))


def rel(path: Path) -> str:
    return str(Path(path).resolve().relative_to(ROOT)).replace("\\", "/")


def write_hashed(path: Path, body: dict[str, Any], field: str = "receipt_sha256") -> str:
    """Write ``body`` with a self-hash over every other key."""
    bare = {key: value for key, value in body.items() if key != field}
    body[field] = canonical_sha(bare)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(body, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return body[field]


def git(*args: str) -> str:
    out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False)
    return out.stdout.strip()


def git_head() -> str:
    return git("rev-parse", "HEAD")


def worktree_dirty_paths() -> list[str]:
    lines = git("status", "--porcelain").splitlines()
    return sorted(line[3:].strip().strip('"') for line in lines if line.strip())
