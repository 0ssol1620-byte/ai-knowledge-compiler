from __future__ import annotations

from pathlib import Path

from infra.security.validate_repository import scan_secrets


def test_scan_secrets_still_reports_aws_access_key(tmp_path: Path) -> None:
    # Assembled at runtime so this source never holds a contiguous AKIA-shaped key.
    synthetic_key = "AKIA" + "SYNTHETIC0TEST00"
    (tmp_path / "leak.txt").write_text(f"key={synthetic_key}\n", encoding="utf-8")

    errors: list[str] = []
    scan_secrets(errors, root=tmp_path)

    assert errors == ["possible aws_access_key in leak.txt"]
