from pathlib import Path

from deepseek_ocr2_stage2 import resolve_markdown


def test_prefers_returned_markdown(tmp_path: Path) -> None:
    (tmp_path / "result.mmd").write_text("persisted", encoding="utf-8")
    assert resolve_markdown(" returned ", tmp_path) == "returned"


def test_falls_back_to_vendor_mmd(tmp_path: Path) -> None:
    (tmp_path / "result.mmd").write_text("# Vendor result\n", encoding="utf-8")
    assert resolve_markdown(None, tmp_path) == "# Vendor result"


def test_empty_result_remains_empty(tmp_path: Path) -> None:
    assert resolve_markdown(None, tmp_path) == ""
