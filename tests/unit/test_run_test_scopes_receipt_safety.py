"""`--self-test` must never speak for the repository.

The positive control runs no scope. Its receipt therefore carries an empty
`scopes` list and `repository_green: false` -- a receipt that reads as a red
repository while measuring nothing at all. Written to the canonical path it
destroys the last real full-run result, and because that file is untracked it
cannot be recovered from git.

That happened twice: the 2026-08-19T23:44Z snapshot (3,011 / 2,965 / 0 / 46) and
the 2026-08-20T09:56Z snapshot (3,043 / 2,996 / 0 / 47) are both gone and survive
only as numbers quoted in an incident record. **Neither is restored by this fix
and neither is claimed to be.** This guards the next one.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "repro" / "run_test_scopes.py"
CANONICAL = ROOT / "docs" / "repro" / "TEST_SCOPE_STATUS.json"
SELF_TEST = ROOT / "docs" / "repro" / "TEST_SCOPE_SELF_TEST.json"


@pytest.fixture(autouse=True)
def _keep_the_committed_self_test_receipt() -> Iterator[None]:
    """Put `TEST_SCOPE_SELF_TEST.json` back the way this run found it.

    These tests run the real tool, and the tool writes its receipt to a fixed
    tracked path — so a plain `pytest tests/unit` leaves the working tree dirty
    with a receipt nobody asked for. In a git worktree that receipt is also
    *wrong*: the tool resolves `.venv` relative to the repository root, and a
    worktree has none, so it records `is_project_interpreter: false` while its
    own `running_interpreter` field shows the project interpreter. Committed
    carelessly that publishes a false negative about the interpreter guard.

    Restoring is the isolation this file can have without weakening what it
    asserts: the tests below must observe what the real tool really writes, so
    the write cannot be redirected to `tmp_path`. The venv probe itself is the
    tool's defect to fix, not this test's.
    """
    before = SELF_TEST.read_bytes() if SELF_TEST.exists() else None
    try:
        yield
    finally:
        if before is None:
            SELF_TEST.unlink(missing_ok=True)
        else:
            SELF_TEST.write_bytes(before)


def test_self_test_does_not_touch_the_canonical_receipt() -> None:
    """The regression itself: run --self-test, require the canonical file unchanged."""
    before = CANONICAL.read_bytes() if CANONICAL.exists() else None

    result = subprocess.run(  # noqa: S603
        [sys.executable, str(TOOL), "--self-test"],
        capture_output=True, text=True, check=False, cwd=ROOT)
    assert result.returncode == 0, result.stdout + result.stderr

    after = CANONICAL.read_bytes() if CANONICAL.exists() else None
    assert after == before, (
        "--self-test rewrote docs/repro/TEST_SCOPE_STATUS.json. A control run that "
        "executed no scope must not be able to overwrite the receipt that records a "
        "real full-suite result."
    )


def test_self_test_still_writes_its_own_receipt() -> None:
    """Redirecting the write must not silently discard the control's result."""
    subprocess.run(  # noqa: S603
        [sys.executable, str(TOOL), "--self-test"],
        capture_output=True, text=True, check=False, cwd=ROOT)
    assert SELF_TEST.is_file(), "the control run produced no receipt of its own"
    payload = json.loads(SELF_TEST.read_text(encoding="utf-8"))
    assert payload["scopes"] == [], "a control-only run must record no scopes"
    assert payload["repository_green"] is False
    assert payload["repository_green_evaluated"] is False
    assert payload["positive_control"]["separates"] is True, (
        "the guard must still demonstrate that it refuses an injected failure"
    )


def test_a_control_only_receipt_cannot_be_read_as_a_repository_verdict() -> None:
    """`repository_green_evaluated` is what distinguishes 'red' from 'not measured'."""
    if not SELF_TEST.is_file():
        subprocess.run(  # noqa: S603
            [sys.executable, str(TOOL), "--self-test"],
            capture_output=True, text=True, check=False, cwd=ROOT)
    payload = json.loads(SELF_TEST.read_text(encoding="utf-8"))
    assert payload["repository_green"] is False
    assert payload["repository_green_evaluated"] is False
    assert "absence of a run is not a pass" in payload["repository_green_note"]
