"""The watchdog must never read an unanswered liveness probe as an idle Pod.

This is a regression guard for a failure that cost real work twice. The watchdog
is a cost backstop, so at its deadline it decides between stopping a Pod and
deleting it. Deleting is irreversible and takes the volume with it.

The probe answers over SSH using the address recorded when the Pod was
provisioned. A Pod that is stopped and restarted comes back on new ports, so
that address stops resolving while the Pod itself is perfectly busy. Treating
the resulting silence as "nothing is running" deleted four workers that were
mid-run, losing 117 of 372 documents.

These tests read the script rather than executing it, because running it would
require a live provider account. They pin the shape of the decision so the
three-state handling cannot be collapsed back into a boolean.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SCRIPT = Path(__file__).with_name("runpod_pod_watchdog.ps1")


@pytest.fixture(scope="module")
def source() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_probe_failure_is_a_distinct_state_from_no_work(source: str) -> None:
    # A non-zero exit means the probe could not answer, which is not the same as
    # answering "nothing is running".
    assert "$busyState = 'unknown'" in source
    assert re.search(r"if \(\$LASTEXITCODE -ne 0\) \{\s*\n\s*\$busyState = 'unknown'", source)


def test_only_a_confirmed_idle_pod_reaches_deletion(source: str) -> None:
    # Deletion is guarded by the state being exactly idle, so both 'busy' and
    # 'unknown' take the stop path.
    assert "if ($busyState -ne 'idle') {" in source
    stop_index = source.index("if ($busyState -ne 'idle') {")
    delete_index = source.index("-Method Delete -Uri $uri")
    assert stop_index < delete_index, "the stop branch must precede deletion"


def test_the_stop_path_exits_before_deleting(source: str) -> None:
    stop_index = source.index("if ($busyState -ne 'idle') {")
    delete_index = source.index("-Method Delete -Uri $uri")
    between = source[stop_index:delete_index]
    assert "exit 0" in between, "a stopped Pod must not fall through to deletion"


def test_an_unknown_liveness_is_recorded_in_the_receipt(source: str) -> None:
    # The receipt is the only trace of why a Pod ended, so an ambiguous probe has
    # to be distinguishable afterwards from a confirmed busy one.
    assert "stopped_at_deadline_liveness_unknown" in source
    assert "liveness_state = $busyState" in source


def test_the_reason_for_refusing_to_delete_is_written_down(source: str) -> None:
    assert "an unanswered probe is not proof of an idle Pod" in source


def test_a_watchdog_without_a_probe_still_deletes(source: str) -> None:
    # The backstop exists for Pods that are building or idling with no probe
    # configured, and that case must keep deleting or the cost guard is gone.
    assert "$busyState = 'idle'" in source
    assert "if ($LivenessProbeCommand) {" in source
