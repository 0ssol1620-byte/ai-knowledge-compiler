"""``python -m arena.reports build --out reports/ [--evidence]`` argument parsing."""

from __future__ import annotations

from pathlib import Path

from arena.reports.cli import main


def test_cli_build_writes_reports_under_out_dir(campaign_root: Path) -> None:
    out_dir = campaign_root / "reports"
    exit_code = main(["build", "--out", str(out_dir)])
    assert exit_code == 0
    assert (out_dir / "LEADERBOARD.md").is_file()


def test_cli_build_evidence_flag_writes_evidence_dir(campaign_root: Path) -> None:
    out_dir = campaign_root / "reports"
    exit_code = main(["build", "--out", str(out_dir), "--evidence"])
    assert exit_code == 0
    assert (campaign_root / "evidence" / "FINAL_EVIDENCE_MANIFEST.json").is_file()


def test_cli_build_without_evidence_flag_skips_it(campaign_root: Path) -> None:
    out_dir = campaign_root / "reports"
    main(["build", "--out", str(out_dir)])
    assert not (campaign_root / "evidence" / "FINAL_EVIDENCE_MANIFEST.json").is_file()
