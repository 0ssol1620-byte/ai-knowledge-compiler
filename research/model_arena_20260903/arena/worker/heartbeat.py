"""Worker heartbeat (masterplan section 15.4).

A background thread writes ``<state_dir>/heartbeat.json`` every
``HEARTBEAT_INTERVAL_SECONDS``. The file survives the process, so a controller
that finds a dead pod can still read how far the worker got; ``/v1/heartbeat``
serves the same object live.

GPU numbers come from ``nvidia-smi``. On a box without it the fields are
``null`` and ``gpu_metrics_unavailable_reason`` says why — a zero utilisation
would be indistinguishable from a genuinely idle GPU.
"""

from __future__ import annotations

import shutil
import subprocess
import threading
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Final

from arena.constants import HEARTBEAT_INTERVAL_SECONDS
from arena.worker.util import atomic_write_json, redact, utcnow

NVIDIA_SMI_TIMEOUT: Final = 10.0
Snapshot = Callable[[], Mapping[str, Any]]


def gpu_metrics() -> dict[str, Any]:
    """``gpu_util`` (percent) and ``vram_used`` (MiB) for the first visible GPU."""
    executable = shutil.which("nvidia-smi")
    if executable is None:
        return {
            "gpu_util": None,
            "vram_used": None,
            "gpu_metrics_unavailable_reason": "nvidia-smi not found on PATH",
        }
    try:
        completed = subprocess.run(
            [
                executable,
                "--query-gpu=utilization.gpu,memory.used",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=NVIDIA_SMI_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "gpu_util": None,
            "vram_used": None,
            "gpu_metrics_unavailable_reason": redact(f"nvidia-smi failed: {exc}")[:400],
        }
    if completed.returncode != 0:
        return {
            "gpu_util": None,
            "vram_used": None,
            "gpu_metrics_unavailable_reason": f"nvidia-smi exited {completed.returncode}",
        }
    rows = [row for row in completed.stdout.splitlines() if row.strip()]
    if not rows:
        return {
            "gpu_util": None,
            "vram_used": None,
            "gpu_metrics_unavailable_reason": "nvidia-smi returned no rows",
        }
    parts = [part.strip() for part in rows[0].split(",")]
    if len(parts) < 2 or not parts[0].isdigit() or not parts[1].isdigit():
        return {
            "gpu_util": None,
            "vram_used": None,
            "gpu_metrics_unavailable_reason": f"unparsable nvidia-smi row: {rows[0]!r}",
        }
    return {"gpu_util": int(parts[0]), "vram_used": int(parts[1])}


class HeartbeatWriter:
    """Periodic, atomic heartbeat writer."""

    def __init__(
        self,
        path: Path,
        snapshot: Snapshot,
        *,
        interval: float = HEARTBEAT_INTERVAL_SECONDS,
        gpu_reader: Callable[[], dict[str, Any]] = gpu_metrics,
    ) -> None:
        self.path = path
        self._snapshot = snapshot
        self._interval = interval
        self._gpu_reader = gpu_reader
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def sample(self) -> dict[str, Any]:
        """Build the heartbeat object without writing it.

        Two fields sit outside ``arena/core/schemas/heartbeat.schema.json`` on
        purpose. ``ts`` is when this heartbeat was written, which is how a
        controller tells a dead pod (``ts`` frozen) from one stuck on a single
        page (``ts`` advancing, ``last_progress_at`` frozen) — masterplan 15.5
        needs both. ``gpu_metrics_unavailable_reason`` appears only when
        ``gpu_util``/``vram_used`` are null, because a zero there is
        indistinguishable from a genuinely idle GPU.
        """
        payload: dict[str, Any] = {"ts": utcnow()}
        payload.update(self._snapshot())
        payload.update(self._gpu_reader())
        return payload

    def write_once(self) -> dict[str, Any]:
        payload = self.sample()
        with self._lock:
            atomic_write_json(self.path, payload)
        return payload

    def start(self) -> None:
        if self._thread is not None:
            return
        self.write_once()
        thread = threading.Thread(target=self._loop, name="arena-heartbeat", daemon=True)
        self._thread = thread
        thread.start()

    def stop(self, *, timeout: float = 5.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)
            self._thread = None

    def _loop(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                self.write_once()
            except OSError:  # pragma: no cover - disk full / unmounted volume
                continue


__all__ = ["NVIDIA_SMI_TIMEOUT", "HeartbeatWriter", "Snapshot", "gpu_metrics"]
