"""Campaign controller for the model arena (lane B1).

``python -m arena.controller <command>`` drives the campaign. Every command is
a dry run unless ``--execute`` is passed; a dry run opens no socket, provisions
nothing and still writes the receipt describing what it would have done.
"""

from __future__ import annotations

__all__ = [
    "canary",
    "cleanup",
    "cost",
    "events",
    "freeze",
    "ids_local",
    "paths",
    "plan",
    "preflight",
    "queue",
    "retry",
    "run",
    "scheduler",
    "watchdogs",
]
