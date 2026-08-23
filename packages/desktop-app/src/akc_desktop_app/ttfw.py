"""Time-to-first-world measurement log (JSONL, append-only).

Onboarding is a journey: ``init`` registers a workspace, the user eventually
runs a Health Scan, the compiler publishes the first world, and an MCP client
connects. Every milestone is appended to ``<home>/logs/ttfw.jsonl``::

    {"ts": "2026-08-23T04:12:00+00:00", "phase": "init_started",
     "workspace": "atlas-demo"}

``seconds_to_first_world`` measures ``init_started -> world_detected``; the
``world_detected`` phase is recorded idempotently by scanning the configured
world store for published manifests (see :func:`find_worlds`) whenever
``serve`` starts or ``status`` runs.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .config import utc_now_iso

__all__ = [
    "PHASE_HEALTH_SCAN_COMPLETED",
    "PHASE_INIT_COMPLETED",
    "PHASE_INIT_STARTED",
    "PHASE_MCP_READY",
    "PHASE_SERVE_STARTED",
    "PHASE_WORLD_DETECTED",
    "WorldRef",
    "TtfwLog",
    "find_worlds",
]

PHASE_INIT_STARTED = "init_started"
PHASE_INIT_COMPLETED = "init_completed"
PHASE_HEALTH_SCAN_COMPLETED = "health_scan_completed"
PHASE_SERVE_STARTED = "serve_started"
PHASE_WORLD_DETECTED = "world_detected"
PHASE_MCP_READY = "mcp_ready"


class WorldRef:
    """One published world found in the store (directory with a manifest)."""

    __slots__ = ("world_id", "manifest_path")

    def __init__(self, world_id: str, manifest_path: Path) -> None:
        self.world_id = world_id
        self.manifest_path = manifest_path

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"WorldRef({self.world_id!r})"


def find_worlds(world_store: Path) -> list[WorldRef]:
    """List published worlds: immediate child directories holding manifest.json.

    A missing store is not an error — nothing has been compiled yet.
    """
    store = Path(world_store)
    if not store.is_dir():
        return []
    worlds: list[WorldRef] = []
    for child in sorted(store.iterdir()):
        if not child.is_dir():
            continue
        manifest = child / "manifest.json"
        if manifest.is_file():
            worlds.append(WorldRef(child.name, manifest))
    return worlds


class TtfwLog:
    """Append-only JSONL milestone log with first-world arithmetic."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def record(self, phase: str, **fields: object) -> dict[str, object]:
        entry: dict[str, object] = {"ts": utc_now_iso(), "phase": phase, **fields}
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def entries(self) -> list[dict[str, object]]:
        if not self._path.exists():
            return []
        out: list[dict[str, object]] = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                out.append(item)
        return out

    def first_timestamp(self, phase: str) -> str | None:
        for item in self.entries():
            if item.get("phase") == phase and isinstance(item.get("ts"), str):
                return str(item["ts"])
        return None

    def has_world_for_any_workspace(self) -> bool:
        return any(item.get("phase") == PHASE_WORLD_DETECTED for item in self.entries())

    def seconds_to_first_world(self) -> float | None:
        """Elapsed seconds from the first ``init_started`` to the first world."""
        started = self.first_timestamp(PHASE_INIT_STARTED)
        detected = self.first_timestamp(PHASE_WORLD_DETECTED)
        if started is None or detected is None:
            return None
        begin = datetime.fromisoformat(started)
        end = datetime.fromisoformat(detected)
        return max((end - begin).total_seconds(), 0.0)

    def summary(self) -> str:
        seconds = self.seconds_to_first_world()
        if seconds is None:
            pending = (
                "world not compiled yet"
                if self.first_timestamp(PHASE_INIT_STARTED)
                else "no init recorded"
            )
            return f"time-to-first-world: not measured ({pending})"
        started = started_display(self.first_timestamp(PHASE_INIT_STARTED))
        detected = self.first_timestamp(PHASE_WORLD_DETECTED)
        return f"time-to-first-world: {seconds:.0f}s ({started} -> {detected})"


def started_display(ts: str | None) -> str:
    return ts if ts else "?"
