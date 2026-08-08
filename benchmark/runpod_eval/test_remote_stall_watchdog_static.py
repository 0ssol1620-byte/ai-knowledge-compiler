from pathlib import Path

SCRIPT = Path(__file__).with_name("remote_stall_watchdog.sh")


def test_watchdog_covers_full_operational_and_quality_retry_runners() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert "run-mineru-" in text
    assert "remote_run_operational_retry" in text
    assert "remote_run_mineru_quality_retry" in text
    assert 'output_dir="$(sed -n' in text
    assert 'output_dir" != "$result_root/"*' in text
    assert 'suite="${output_dir#"$result_root/"}"' in text


def test_watchdog_keeps_bounded_stall_and_poll_validation() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert "stall_seconds < 300" in text
    assert "poll_seconds < 10" in text
    assert 'wc -l || true' in text
    assert "suite_stall_detected" in text
    assert "pkill -TERM -f 'mineru.cli.fast_api'" in text
