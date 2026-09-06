"""Whole-GPU VRAM measurement (arena/worker/vram.py) and its path to a receipt.

The real GLM-OCR canary of 2026-09-03 returned 15/15 SUCCESS pages whose
``peak_vram_mb`` was null, because the model lives in a server process the
worker does not own. These tests pin the replacement: ``nvidia-smi``, the whole
device, labelled as such -- and null with a reason when the binary is not
there, never a zero.
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from arena.core.receipts import validate
from arena.worker import vram as vram_module
from arena.worker.server import WorkerCore
from arena.worker.vram import (
    GpuMemoryReading,
    VramSampler,
    VramWindow,
    query_gpu_memory,
)
from harness import worker


class _Completed:
    def __init__(self, stdout: str, returncode: int = 0) -> None:
        self.stdout = stdout
        self.stderr = ""
        self.returncode = returncode


def _smi(monkeypatch: pytest.MonkeyPatch, stdout: str, *, returncode: int = 0) -> list[list[str]]:
    """Pretend nvidia-smi is on PATH and prints ``stdout``. Returns the argv log."""

    calls: list[list[str]] = []

    def fake_run(argv: Sequence[str], **_: Any) -> _Completed:
        calls.append(list(argv))
        return _Completed(stdout, returncode)

    monkeypatch.setattr(vram_module.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(vram_module.subprocess, "run", fake_run)
    return calls


def test_a_single_gpu_is_read_as_used_and_total(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _smi(monkeypatch, "0, 18240, 24564\n")

    reading = query_gpu_memory()

    assert reading.used_mb == 18240
    assert reading.total_mb == 24564
    assert reading.device_count == 1
    assert reading.unavailable_reason is None
    assert "--query-gpu=index,memory.used,memory.total" in calls[0]


def test_multi_gpu_is_summed_not_sampled(monkeypatch: pytest.MonkeyPatch) -> None:
    """A worker holding two cards has a footprint across both."""

    _smi(monkeypatch, "0, 18240, 24564\n1, 9000, 24564\n")

    reading = query_gpu_memory()

    assert reading.used_mb == 27240
    assert reading.total_mb == 49128
    assert reading.device_count == 2


def test_only_the_configured_devices_are_counted(monkeypatch: pytest.MonkeyPatch) -> None:
    _smi(monkeypatch, "0, 18240, 24564\n1, 9000, 24564\n")

    reading = query_gpu_memory(devices=[1])

    assert reading.used_mb == 9000
    assert reading.device_count == 1


def test_a_configured_device_that_is_not_there_is_not_a_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _smi(monkeypatch, "0, 18240, 24564\n")

    reading = query_gpu_memory(devices=[3])

    assert reading.used_mb is None
    assert reading.total_mb is None
    assert "index in [3]" in (reading.unavailable_reason or "")


def test_a_missing_binary_is_null_with_a_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(vram_module.shutil, "which", lambda name: None)

    reading = query_gpu_memory()

    assert reading.used_mb is None
    assert reading.total_mb is None
    assert reading.unavailable_reason == "nvidia-smi not found on PATH"
    assert not reading.available


def test_garbage_output_is_refused_rather_than_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    _smi(monkeypatch, "0, [N/A], 24564\n")

    reading = query_gpu_memory()

    assert reading.used_mb is None
    assert "unparsable nvidia-smi row" in (reading.unavailable_reason or "")


def test_a_nonzero_exit_and_a_timeout_both_report_why(monkeypatch: pytest.MonkeyPatch) -> None:
    _smi(monkeypatch, "", returncode=9)
    assert query_gpu_memory().unavailable_reason == "nvidia-smi exited 9"

    def explode(argv: Sequence[str], **_: Any) -> _Completed:
        raise subprocess.TimeoutExpired(list(argv), 10.0)

    monkeypatch.setattr(vram_module.subprocess, "run", explode)
    reason = query_gpu_memory().unavailable_reason or ""
    assert reason.startswith("nvidia-smi failed:")


def test_empty_output_is_null(monkeypatch: pytest.MonkeyPatch) -> None:
    _smi(monkeypatch, "\n\n")

    assert query_gpu_memory().unavailable_reason == "nvidia-smi returned no rows"


# -- the window ------------------------------------------------------------


def _reading(used: int | None, total: int | None = 24564) -> GpuMemoryReading:
    if used is None:
        return GpuMemoryReading(None, None, 0, "no nvidia-smi")
    return GpuMemoryReading(used, total, 1)


def test_the_window_keeps_the_maximum_not_the_last_sample() -> None:
    window = VramWindow()
    for used in (18240, 22000, 19100):
        window.observe(_reading(used))

    assert window.peak_used_mb == 22000
    assert window.total_mb == 24564
    assert window.sample_count == 3


def test_a_window_that_never_read_anything_stays_null() -> None:
    window = VramWindow()
    window.observe(_reading(None))
    window.observe(_reading(None))

    assert window.peak_used_mb is None
    assert window.unavailable_reason == "no nvidia-smi"


def test_the_sampler_samples_on_entry_and_exit_even_for_a_fast_block() -> None:
    """A 200 ms page must still produce a measurement."""

    values = iter([16000, 21000])
    sampler = VramSampler(
        interval=60.0,  # the thread never ticks inside the block
        reader=lambda _devices: _reading(next(values, 21000)),
    )
    with sampler.track() as window:
        pass

    assert window.sample_count >= 2
    assert window.peak_used_mb == 21000


def test_the_sampler_thread_catches_a_spike_between_entry_and_exit() -> None:
    values = iter([16000, 30000, 17000, 17000])
    sampler = VramSampler(
        interval=0.01,
        reader=lambda _devices: _reading(next(values, 17000)),
    )
    with sampler.track() as window:
        deadline = window
        while deadline.sample_count < 3:  # let the background thread tick
            pass

    assert window.peak_used_mb == 30000


# -- the page receipt ------------------------------------------------------


def test_a_page_carries_the_whole_gpu_peak_baseline_total_and_source(
    tmp_path: Path,
) -> None:
    with worker(tmp_path, start=False) as handle:
        handle.core.vram = VramSampler(
            interval=60.0, reader=lambda _devices: _reading(18240)
        )
        handle.core.start()
        handle.wait_for_stage(("READY",))

        status, body = handle.post("/v1/run", handle.run_payload())

    assert status == 200, body
    assert body["status"] == "SUCCESS", body
    assert body["peak_vram_mb"] == 18240
    assert body["baseline_vram_mb"] == 18240
    assert body["vram_total_mb"] == 24564
    assert body["vram_measurement_source"] == "nvidia-smi"
    validate(body, "worker-run-response")


def test_neither_source_measuring_leaves_the_peak_null_rather_than_zero() -> None:
    peak, source = WorkerCore._resolve_peak_vram(None, VramWindow())

    assert peak is None
    assert source is None


def test_without_nvidia_smi_the_adapters_own_figure_is_used_and_labelled(
    tmp_path: Path,
) -> None:
    """The fake adapter reports 2048 MiB in-process; the label must say so."""

    with worker(tmp_path, start=False) as handle:
        handle.core.vram = VramSampler(
            interval=60.0, reader=lambda _devices: _reading(None)
        )
        handle.core.start()
        ready = handle.wait_for_stage(("READY",))

        status, body = handle.post("/v1/run", handle.run_payload())

    assert status == 200, body
    assert body["peak_vram_mb"] == 2048
    assert body["vram_measurement_source"] == "adapter"
    # No device was read, so there is no headroom denominator to report.
    assert body["baseline_vram_mb"] is None
    assert body["vram_total_mb"] is None
    validate(body, "worker-run-response")

    # ready-response.schema.json is additionalProperties:false and has no VRAM
    # field, so the measurement rides in the free-form load_receipt.
    measured = ready["load_receipt"]["vram"]
    assert measured["measurement_source"] is None
    assert measured["scope"] == "whole-gpu"
    assert measured["unavailable_reason"] == "no nvidia-smi"
    validate(ready, "ready-response")


def test_the_ready_load_receipt_records_the_baseline_and_the_total(tmp_path: Path) -> None:
    with worker(tmp_path, start=False) as handle:
        handle.core.vram = VramSampler(
            interval=60.0, reader=lambda _devices: _reading(15870)
        )
        handle.core.start()
        ready = handle.wait_for_stage(("READY",))

    measured = ready["load_receipt"]["vram"]
    assert measured["baseline_vram_mb"] == 15870
    assert measured["vram_total_mb"] == 24564
    assert measured["at_load_start_mb"] == 15870
    assert measured["measurement_source"] == "nvidia-smi"
    validate(ready, "ready-response")
