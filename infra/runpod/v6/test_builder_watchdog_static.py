from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "tools/release/runpod_pod_watchdog.ps1"


def test_builder_watchdog_is_bounded_and_deletes_only_the_exact_pod() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "ValidatePattern('^[A-Za-z0-9][A-Za-z0-9_-]{2,63}$')" in text
    assert '"https://rest.runpod.io/v1/pods/$PodId"' in text
    assert "[DateTimeOffset]::UtcNow -lt $deadline" in text
    assert "Invoke-RestMethod -Method Delete -Uri $uri" in text
    assert "Start-Sleep -Seconds 60" in text
    assert "benchmark\\datasets\\private" in text
    assert "Remove-Item" not in text
