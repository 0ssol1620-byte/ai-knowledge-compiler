"""Whole-GPU VRAM sampling for the worker (stdlib + ``nvidia-smi`` only).

The worker cannot measure VRAM in-process. Most runtimes here serve the model
from a *separate* process the worker never owns -- vLLM, the paddle genai
server, MinerU's vlm server, olmocr, monkeyocr, hpd, GLM-OCR -- so
``torch.cuda.max_memory_allocated`` inside the worker sees nothing and every
page receipt of the 2026-09-03 GLM-OCR canary carried ``peak_vram_mb: null``.

So the measurement is the whole device, read from ``nvidia-smi``: the used
memory of every configured GPU, sampled around each page and kept at its
maximum. That number is not this model's private footprint -- anything else
running on the card is inside it -- which is exactly why every consumer is told
the source (``vram_measurement_source: "nvidia-smi"``) rather than being left
to assume a per-process figure.

When ``nvidia-smi`` is absent or unreadable the numbers stay ``null`` and the
reason travels with them. A zero would be indistinguishable from a GPU that
genuinely holds nothing.
"""

from __future__ import annotations

import shutil
import subprocess
import threading
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Final

from arena.worker.util import redact

NVIDIA_SMI_TIMEOUT: Final = 10.0
# Fast enough to catch a decode-time spike on a page that runs a few hundred
# milliseconds, cheap enough that the subprocess never competes with inference.
DEFAULT_SAMPLE_INTERVAL_SECONDS: Final = 0.25
MEASUREMENT_SOURCE_NVIDIA_SMI: Final = "nvidia-smi"
MEASUREMENT_SOURCE_ADAPTER: Final = "adapter"

QUERY_FIELDS: Final = "index,memory.used,memory.total"


@dataclass(frozen=True, slots=True)
class GpuMemoryReading:
    """One ``nvidia-smi`` read, summed over the configured devices.

    ``used_mb``/``total_mb`` are ``None`` exactly when ``unavailable_reason``
    is set; there is no third state where a number was guessed.
    """

    used_mb: int | None
    total_mb: int | None
    device_count: int
    unavailable_reason: str | None = None

    @property
    def available(self) -> bool:
        return self.used_mb is not None


Reader = Callable[[], GpuMemoryReading]


def _unavailable(reason: str) -> GpuMemoryReading:
    return GpuMemoryReading(
        used_mb=None, total_mb=None, device_count=0, unavailable_reason=redact(reason)[:400]
    )


def query_gpu_memory(devices: Sequence[int] | None = None) -> GpuMemoryReading:
    """Read used/total memory (MiB) for ``devices``, or every visible GPU.

    Multi-GPU is summed, because a worker holding two cards has a footprint
    across both and a headroom check against one of them would be wrong.
    """

    executable = shutil.which("nvidia-smi")
    if executable is None:
        return _unavailable("nvidia-smi not found on PATH")
    try:
        completed = subprocess.run(
            [executable, f"--query-gpu={QUERY_FIELDS}", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=NVIDIA_SMI_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return _unavailable(f"nvidia-smi failed: {exc}")
    if completed.returncode != 0:
        return _unavailable(f"nvidia-smi exited {completed.returncode}")

    wanted = None if devices is None else {int(index) for index in devices}
    used_total = 0
    total_total = 0
    matched = 0
    for row in completed.stdout.splitlines():
        if not row.strip():
            continue
        parts = [part.strip() for part in row.split(",")]
        if len(parts) < 3 or not all(part.isdigit() for part in parts[:3]):
            return _unavailable(f"unparsable nvidia-smi row: {row.strip()!r}")
        index, used, total = int(parts[0]), int(parts[1]), int(parts[2])
        if wanted is not None and index not in wanted:
            continue
        used_total += used
        total_total += total
        matched += 1

    if matched == 0:
        return _unavailable(
            "nvidia-smi returned no rows"
            if wanted is None
            else f"nvidia-smi reported no GPU with index in {sorted(wanted)}"
        )
    return GpuMemoryReading(used_mb=used_total, total_mb=total_total, device_count=matched)


class VramWindow:
    """The maximum ``memory.used`` observed while one page was in flight."""

    __slots__ = ("_lock", "peak_used_mb", "sample_count", "total_mb", "unavailable_reason")

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.peak_used_mb: int | None = None
        self.total_mb: int | None = None
        self.unavailable_reason: str | None = None
        self.sample_count = 0

    def observe(self, reading: GpuMemoryReading) -> None:
        with self._lock:
            self.sample_count += 1
            if reading.used_mb is None:
                # Keep only the first reason: later ones are the same failure
                # repeated once per sampling tick.
                if self.unavailable_reason is None:
                    self.unavailable_reason = reading.unavailable_reason
                return
            if self.peak_used_mb is None or reading.used_mb > self.peak_used_mb:
                self.peak_used_mb = reading.used_mb
            if reading.total_mb is not None:
                self.total_mb = reading.total_mb


class VramSampler:
    """One-shot reads, plus a background thread that keeps a per-page maximum.

    ``devices=None`` means every GPU ``nvidia-smi`` reports, which is what the
    pods here run: one worker, whatever the pod was rented with.
    """

    def __init__(
        self,
        *,
        devices: Sequence[int] | None = None,
        interval: float = DEFAULT_SAMPLE_INTERVAL_SECONDS,
        reader: Callable[[Sequence[int] | None], GpuMemoryReading] = query_gpu_memory,
    ) -> None:
        self._devices = None if devices is None else tuple(devices)
        self._interval = interval
        self._reader = reader

    def read(self) -> GpuMemoryReading:
        return self._reader(self._devices)

    @contextmanager
    def track(self) -> Iterator[VramWindow]:
        """Sample around and during the block; the window holds the maximum.

        A sample is taken on entry and on exit even when the block is shorter
        than one interval, so a fast page still produces a measurement.
        """

        window = VramWindow()
        window.observe(self.read())
        stop = threading.Event()

        def loop() -> None:
            while not stop.wait(self._interval):
                try:
                    window.observe(self.read())
                except Exception:  # pragma: no cover - the reader already traps its own
                    return

        thread = threading.Thread(target=loop, name="arena-vram-sampler", daemon=True)
        thread.start()
        try:
            yield window
        finally:
            stop.set()
            thread.join(timeout=NVIDIA_SMI_TIMEOUT + self._interval)
            window.observe(self.read())


__all__ = [
    "DEFAULT_SAMPLE_INTERVAL_SECONDS",
    "MEASUREMENT_SOURCE_ADAPTER",
    "MEASUREMENT_SOURCE_NVIDIA_SMI",
    "NVIDIA_SMI_TIMEOUT",
    "GpuMemoryReading",
    "Reader",
    "VramSampler",
    "VramWindow",
    "query_gpu_memory",
]
