"""Standalone scripts run as subprocesses inside a pinned evaluator checkout.

Nothing here is imported by the rest of ``arena.scoring`` at run time. Each
driver is executed with the evaluator's own interpreter and dependencies, so
its heavy imports happen inside ``main`` and the module stays importable on a
box that has none of them (a test can check its argument parsing).
"""

from __future__ import annotations

__all__: list[str] = []
