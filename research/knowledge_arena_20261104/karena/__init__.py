"""TAVONEL knowledge Arena harness (campaign TAVONEL-KNOWLEDGE-ARENA-20261104-V1).

Tasks: ``doc_type`` (B2b), ``schema_induction`` (C1), ``typed_extraction`` (C2),
``grounded_answer`` (E3) and one table track at product DPI (D3).

This package does not re-implement the 2026-09-03 Model Arena. It imports its
RunPod client, secret reader, secret-free guard, readiness poll, circuit
breaker, budget watchdog and pod cost ledger from ``arena``. That code is not on
``main`` yet (it was committed as d9db24c on the research integration
branches), so the package refuses to import without it rather than carrying a
second copy.
"""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path
from typing import Final

__all__ = [
    "ARENA_ROOT",
    "ARENA_TREE_PIN",
    "CAMPAIGN_ID",
    "CAMPAIGN_SHORT",
    "NAMESPACE_ROOT",
    "arena_tree_sha256",
]

CAMPAIGN_ID: Final = "TAVONEL-KNOWLEDGE-ARENA-20261104-V1"
CAMPAIGN_SHORT: Final = "karena20261104"
NAMESPACE_ROOT: Final = Path(__file__).resolve().parent.parent
#: sha256 over every arena/**/*.py and *.json at d9db24c (path, NUL, file sha256, LF).
ARENA_TREE_PIN: Final = "469fecf4a260aa2975f8adc4384c6d4e2f0fcc90c5fb5415c020c7d53751774a"


def arena_tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    files = sorted(
        p
        for p in (root / "arena").rglob("*")
        if p.suffix in (".py", ".json") and "__pycache__" not in p.parts
    )
    for path in files:
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0" + hashlib.sha256(path.read_bytes()).hexdigest().encode() + b"\n")
    return digest.hexdigest()


def _arena_root() -> Path:
    configured = os.environ.get("KARENA_ARENA_ROOT")
    if not configured or not (Path(configured) / "arena" / "__init__.py").is_file():
        raise ImportError(
            "the 2026-09-03 Model Arena package `arena` is required: set KARENA_ARENA_ROOT "
            "to a checkout of research/model_arena_20260903 that contains arena/ "
            f"(commit d9db24c); got {configured!r}"
        )
    root = Path(configured).resolve()
    found = arena_tree_sha256(root)
    if found != ARENA_TREE_PIN:
        raise ImportError(
            f"arena/ under {root} hashes to {found}, not the pinned d9db24c tree "
            f"{ARENA_TREE_PIN}; a different Arena revision would change what is measured"
        )
    return root


ARENA_ROOT: Final = _arena_root()
if str(ARENA_ROOT) not in sys.path:
    sys.path.insert(0, str(ARENA_ROOT))
