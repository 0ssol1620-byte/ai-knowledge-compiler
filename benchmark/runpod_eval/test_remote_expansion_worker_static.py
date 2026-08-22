from __future__ import annotations

import re
from pathlib import Path

import pytest

# The stall watchdog fires at 2100 s, so a per-case timeout has to stay below it
# for case isolation to happen before the whole worker is declared stalled. The
# operational lane was tightened to 900 s after the live run measured a 144 s p99
# and a 808 s longest success, so the lanes no longer share one constant.
STALL_WATCHDOG_SECONDS = 2100


@pytest.mark.parametrize(
    "name",
    ["remote_run_operational_retry.sh", "remote_run_mineru_quality_retry.sh"],
)
def test_remote_retry_runners_accept_expansion_worker_indices(name: str) -> None:
    source = (Path(__file__).with_name(name)).read_text(encoding="utf-8")

    assert '"$worker_index" =~ ^[0-9]{1,2}$' in source
    assert "10#$worker_index > 99" in source
    assert "worker index must be between 0 and 99" in source
    assert '"$worker_index" =~ ^[0-3]$' not in source
    assert "--batch-size 1" in source
    timeout = re.search(r"--timeout-seconds (\d+)", source)
    assert timeout is not None, "retry runner must pin a per-case timeout"
    # A success as long as 808 s was observed live, so the bound must clear it.
    assert 900 <= int(timeout.group(1)) < STALL_WATCHDOG_SECONDS


@pytest.mark.parametrize(
    "name",
    [
        "launch_operational_retry_workers.py",
        "launch_mineru_quality_retry_workers.py",
    ],
)
def test_retry_launchers_allow_case_timeout_before_stall_watchdog(name: str) -> None:
    source = (Path(__file__).with_name(name)).read_text(encoding="utf-8")

    assert "2100 60 {result_root}" in source
