"""Run from the namespace root: ``python -m pytest tests -q``.

``karena`` resolves the 2026-09-03 Arena package from ``KARENA_ARENA_ROOT`` or the
sibling ``research/model_arena_20260903`` checkout, and refuses to import without it.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
