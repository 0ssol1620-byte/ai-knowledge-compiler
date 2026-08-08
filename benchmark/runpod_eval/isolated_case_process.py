"""Run one inference case in a bounded process group."""

from __future__ import annotations

import os
import signal
import subprocess
import time
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class IsolatedProcessResult:
    return_code: int
    timed_out: bool
    stdout: str
    stderr: str


def run_isolated_process(
    command: list[str],
    *,
    timeout_seconds: int | float,
    terminate_grace_seconds: int | float = 5,
) -> IsolatedProcessResult:
    if not command or timeout_seconds <= 0 or terminate_grace_seconds <= 0:
        raise ValueError("isolated process command and timeouts must be positive")
    popen = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        start_new_session=os.name == "posix",
    )
    try:
        stdout, stderr = popen.communicate(timeout=timeout_seconds)
        return IsolatedProcessResult(popen.returncode, False, stdout, stderr)
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            os.killpg(popen.pid, signal.SIGTERM)
        else:
            popen.terminate()
        deadline = time.monotonic() + terminate_grace_seconds
        while popen.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        if popen.poll() is None:
            if os.name == "posix":
                os.killpg(popen.pid, signal.SIGKILL)
            else:
                popen.kill()
        stdout, stderr = popen.communicate()
        return IsolatedProcessResult(popen.returncode, True, stdout, stderr)


__all__ = ["IsolatedProcessResult", "run_isolated_process"]
