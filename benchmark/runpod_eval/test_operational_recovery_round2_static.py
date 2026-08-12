from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "tools"
    / "release"
    / "continue_folynta_operational_recovery_round2.ps1"
)
REMOTE_RUNNER = Path(__file__).with_name("remote_run_operational_retry.sh")


def test_round2_controller_continuously_supervises_stall_watchdog() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert "WATCHDOG_FAILED" in text
    assert "round2-stall-watchdog-restarted" in text
    assert "round2-stall-watchdog-restart-failed" in text
    assert "pgrep -f '$watchdogPattern'" in text
    assert "pgrep -n -f '$watchdogPattern'" in text
    assert "kill -0 $runnerPid" in text


def test_round2_controller_keeps_completion_ahead_of_watchdog_recovery() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert text.index("if ($status -eq 'COMPLETE')") < text.index(
        "if ($status -eq 'WATCHDOG_FAILED')"
    )


def test_round2_retry_uses_empirically_safe_fifteen_minute_case_timeout() -> None:
    text = REMOTE_RUNNER.read_text(encoding="utf-8")

    assert "--batch-size 1" in text
    assert "--timeout-seconds 900" in text
    assert "--timeout-seconds 1800" not in text


def test_round2_controller_reads_the_collectors_canonical_receipt_name() -> None:
    controller = SCRIPT.read_text(encoding="utf-8")
    collector = (
        Path(__file__).with_name("collect_operational_retry_worker.py")
    ).read_text(encoding="utf-8")

    canonical_name = 'f"{worker_name}-operational-retry-collection.json"'
    assert canonical_name in collector
    assert '"worker-{0:d2}-operational-retry-collection.json"' in controller
    assert '"worker-{0:d2}-collection-receipt.json"' not in controller
