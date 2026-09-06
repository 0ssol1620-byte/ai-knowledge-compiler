from pathlib import Path

import pytest

from tools.release.monitor_folynta_runpod_credit import read_runpod_key


def test_read_runpod_key_accepts_colon_and_does_not_transform_secret(
    tmp_path: Path,
) -> None:
    credential = tmp_path / "credentials.txt"
    expected = "rpa_abcdefghijklmnopqrstuvwxyz0123456789"
    credential.write_text(f"GitHub: ignored\nRunpod: {expected}\n", encoding="utf-8")

    assert read_runpod_key(credential) == expected


@pytest.mark.parametrize("label", ["Runpod_A", "Runpod_B"])
def test_read_runpod_key_accepts_dual_key_labels(tmp_path: Path, label: str) -> None:
    credential = tmp_path / "credentials.txt"
    expected = "test-runpod-credential-value-1234567890"
    credential.write_text(f"{label}: {expected}\n", encoding="utf-8")

    assert read_runpod_key(credential) == expected


def test_read_runpod_key_rejects_missing_or_short_secret(tmp_path: Path) -> None:
    credential = tmp_path / "credentials.txt"
    credential.write_text("Runpod: short\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="missing or malformed"):
        read_runpod_key(credential)
