"""The olmOCR driver: importable on a box with none of the evaluator's deps."""

from __future__ import annotations

from pathlib import Path

import pytest
from arena.scoring.drivers import olmocr_driver


def test_the_module_imports_without_the_evaluator_dependencies() -> None:
    # pypdf and the checkout's own modules are imported inside run(), so a CPU
    # box with none of them installed can still parse arguments and be linted.
    assert olmocr_driver.SCHEMA == "tavonel.arena.olmocr-official-result.v1"


def test_arguments_are_all_required(tmp_path: Path) -> None:
    parser = olmocr_driver.build_parser()

    args = parser.parse_args(
        [
            "--evaluator-dir",
            str(tmp_path / "checkout"),
            "--bench-dir",
            str(tmp_path / "bench"),
            "--candidate",
            "paddleocr_vl_1_6",
            "--out",
            str(tmp_path / "out.json"),
        ]
    )

    assert args.candidate == "paddleocr_vl_1_6"
    assert args.out == tmp_path / "out.json"

    with pytest.raises(SystemExit):
        parser.parse_args(["--candidate", "x"])


def test_an_incomplete_checkout_is_refused_before_anything_runs(tmp_path: Path) -> None:
    checkout = tmp_path / "checkout"
    checkout.mkdir()

    with pytest.raises(SystemExit, match="checkout is incomplete"):
        olmocr_driver._load_official_modules(checkout)
