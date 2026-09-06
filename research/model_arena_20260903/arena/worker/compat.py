"""Names the pod-side code needs that the oldest pod interpreter does not have.

Everything under ``arena/worker`` and ``runtimes/<key>/*.py`` (``arena/core`` is
deliberately *not* bundled, see ``arena/worker/bundle.py``) is shipped in the
bundle and executed by the *image's* Python, and the
paddleocr_vl_1_6 official image runs 3.10.16 (D65, pod ``kfvy42gzo6ikt3``:
``ImportError: cannot import name 'UTC' from 'datetime'`` after the genai
server had come up and the weights were paid for). The controller venv is
newer, so ``ruff`` (UP017) and the type checker would happily keep writing the
3.11 spellings; this module is the one place the older spelling is allowed,
and ``tests/worker/test_pod_python_floor.py`` refuses the 3.11 names anywhere
else in the pod-side tree.
"""

from __future__ import annotations

import sys
from datetime import timezone
from enum import Enum

# datetime.UTC is 3.11+. Same singleton, older name.
UTC = timezone.utc  # noqa: UP017 - pod images may run Python 3.10

if sys.version_info >= (3, 11):  # noqa: UP036 - the pod floor is 3.10, not the venv
    from enum import StrEnum
else:  # pragma: no cover - exercised only on a 3.10 pod interpreter

    class StrEnum(str, Enum):  # noqa: UP042 - this *is* the 3.10 backport
        """enum.StrEnum for 3.10: members are str, str() is the value."""

        def __str__(self) -> str:
            return str(self.value)

        @staticmethod
        def _generate_next_value_(
            name: str, start: int, count: int, last_values: list[object]
        ) -> str:
            return name.lower()


__all__ = ["UTC", "StrEnum"]
