"""Runtime boundary guard for the TAVONEL replay lane.

Masterplan section 2.1 and 2.2: the route decision is computed and frozen
*before* anything in this campaign is allowed to look at an answer key. This
lane is the part of the system that would invalidate the whole experiment if it
peeked, so the peeking is blocked mechanically rather than by convention.

Two mechanisms, both tested:

1. ``read_text_guarded`` / ``read_json_guarded`` / ``iter_jsonl_guarded`` are
   the only readers the rest of this package uses, and they refuse any path
   that resolves under a forbidden root.
2. ``tests/tavonel/test_gt_blindness.py`` greps this package's source for the
   answer-key vocabulary and fails when it appears outside the oracle module.

The forbidden roots are referenced through ``arena.constants`` identifiers on
purpose: writing the literal path text here would defeat the source scan.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

from arena.constants import ACQUIRED_PUBLIC_CORE_ROOT, EVALUATOR_CACHE_ROOT, REPO_ROOT
from arena.tavonel import jsonio
from arena.tavonel.errors import GtBoundaryViolation, MissingInputError

# Roots this lane must never open. The first two hold the answer keys and the
# evaluator sources (masterplan section 2.1). The rest are other people's
# frozen state, which lane E1 was told to leave alone.
FORBIDDEN_ROOTS: Sequence[Path] = (
    ACQUIRED_PUBLIC_CORE_ROOT,
    EVALUATOR_CACHE_ROOT,
    REPO_ROOT / "research" / "tavonel_eval_v2",
    REPO_ROOT / "research" / "tavonel_recovery_eval_v1",
    REPO_ROOT / "docs" / "evidence",
    REPO_ROOT / "docs" / "ip",
)


def _is_under(candidate: Path, root: Path) -> bool:
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def assert_readable(path: Path) -> Path:
    """Return the resolved path, or raise if it lives under a forbidden root."""
    resolved = Path(path).resolve()
    for root in FORBIDDEN_ROOTS:
        if _is_under(resolved, root.resolve()):
            raise GtBoundaryViolation(
                f"{resolved} lies under a root this lane may not read ({root}); "
                "masterplan section 2.1 forbids the inference/route plane from "
                "opening evaluator or answer-key data"
            )
    return resolved


def require_file(path: Path, *, what: str) -> Path:
    resolved = assert_readable(path)
    if not resolved.is_file():
        raise MissingInputError(f"{what} is absent: {resolved}")
    return resolved


def read_text_guarded(path: Path, *, what: str) -> str:
    return jsonio.read_text(require_file(path, what=what))


def read_json_guarded(path: Path, *, what: str) -> dict[str, Any]:
    return jsonio.load_json_object(require_file(path, what=what))


def iter_jsonl_guarded(path: Path, *, what: str) -> Iterator[dict[str, Any]]:
    yield from jsonio.iter_jsonl_objects(require_file(path, what=what))


__all__ = [
    "FORBIDDEN_ROOTS",
    "assert_readable",
    "iter_jsonl_guarded",
    "read_json_guarded",
    "read_text_guarded",
    "require_file",
]
