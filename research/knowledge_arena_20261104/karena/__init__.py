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

import os
import sys
from pathlib import Path
from typing import Final

__all__ = ["ARENA_ROOT", "CAMPAIGN_ID", "CAMPAIGN_SHORT", "NAMESPACE_ROOT"]

CAMPAIGN_ID: Final = "TAVONEL-KNOWLEDGE-ARENA-20261104-V1"
CAMPAIGN_SHORT: Final = "karena20261104"
NAMESPACE_ROOT: Final = Path(__file__).resolve().parent.parent


def _arena_root() -> Path:
    configured = os.environ.get("KARENA_ARENA_ROOT")
    candidates = [Path(configured)] if configured else []
    candidates.append(NAMESPACE_ROOT.parent / "model_arena_20260903")
    for candidate in candidates:
        if (candidate / "arena" / "__init__.py").is_file():
            return candidate.resolve()
    raise ImportError(
        "the 2026-09-03 Model Arena package `arena` is required and was not found "
        f"(looked in {[str(c) for c in candidates]}). Set KARENA_ARENA_ROOT to a checkout "
        "of research/model_arena_20260903 that contains arena/ (commit d9db24c)."
    )


ARENA_ROOT: Final = _arena_root()
if str(ARENA_ROOT) not in sys.path:
    sys.path.insert(0, str(ARENA_ROOT))
