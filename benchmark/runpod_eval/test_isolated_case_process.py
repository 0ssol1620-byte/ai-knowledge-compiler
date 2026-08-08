import sys

from isolated_case_process import run_isolated_process


def test_isolated_process_returns_captured_success() -> None:
    result = run_isolated_process(
        [sys.executable, "-c", "print('bounded')"],
        timeout_seconds=5,
    )

    assert result.return_code == 0
    assert result.timed_out is False
    assert result.stdout.strip() == "bounded"


def test_isolated_process_kills_timeout() -> None:
    result = run_isolated_process(
        [sys.executable, "-c", "import time; time.sleep(5)"],
        timeout_seconds=0.1,
        terminate_grace_seconds=0.1,
    )

    assert result.timed_out is True
    assert result.return_code != 0
