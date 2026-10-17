from __future__ import annotations

import ast
import inspect
import json
import textwrap
from pathlib import Path

import pytest

from research.vendor_comparison_20261017 import run

ARM = "D-V-llamaparse"


def _write(path: Path, data: object) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _receipts(tmp_path: Path, fd1: object = None, fd2: object = None) -> list[str]:
    fd1 = {"decision": "FD-1", "approved_arms": [ARM]} if fd1 is None else fd1
    fd2 = {"decision": "FD-2", "spend_cap_usd": {ARM: 165}} if fd2 is None else fd2
    return [
        "--fd1-receipt",
        str(_write(tmp_path / "fd1.json", fd1)),
        "--fd2-receipt",
        str(_write(tmp_path / "fd2.json", fd2)),
    ]


def test_mock_run_writes_a_synthetic_report(tmp_path: Path) -> None:
    out = tmp_path / "report.json"
    assert run.main(["--out", str(out)]) == run.EXIT_OK
    report = json.loads(out.read_text(encoding="utf-8"))
    assert (report["label"], report["mode"], report["vendor_calls"]) == (
        "SYNTHETIC",
        "mock_replay",
        0,
    )
    assert report["all_expectations_met"] is True
    for arm, summary in report["summary"].items():
        rows = [r for r in report["rows"] if r["arm_id"] == arm]
        assert summary["completion"]["denominator"] == summary["N"] == len(rows)
        assert summary["completion"]["numerator"] == sum(r["status"] == "ok" for r in rows)
        assert all(r["markdown"] == "" for r in rows if r["status"] != "ok")


def test_mock_run_exits_nonzero_on_a_broken_expectation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    real = run.cases

    def tampered(fixture_dir: Path = run.FIXTURE_DIR) -> list[dict[str, object]]:
        cases = real(fixture_dir)
        cases[0] = {**cases[0], "expected": {"status": "SYNTHETIC-wrong"}}
        return cases

    monkeypatch.setattr(run, "cases", tampered)
    assert run.main(["--out", str(tmp_path / "r.json")]) == run.EXIT_EXPECTATION_MISMATCH


def test_execute_without_receipts_is_refused(capsys: pytest.CaptureFixture[str]) -> None:
    assert run.main(["--execute", "--arm", ARM]) == run.EXIT_REFUSED
    assert "FD-1 receipt not given" in capsys.readouterr().err


def test_execute_without_arm_is_refused(tmp_path: Path) -> None:
    assert run.execute_refusal(["--execute", *_receipts(tmp_path)]) == (
        "REFUSED: --execute needs --arm"
    )


@pytest.mark.parametrize(
    ("fd1", "fd2", "reason"),
    [
        ({"decision": "FD-2", "approved_arms": [ARM]}, None, "does not record decision FD-1"),
        ({"decision": "FD-1", "approved_arms": ["D-V-reducto"]}, None, "does not approve"),
        ({"decision": "FD-1", "approved_arms": f"x{ARM}x"}, None, "does not approve"),
        ({"decision": "FD-1"}, None, "does not approve"),
        (["FD-1"], None, "does not record decision FD-1"),
        (None, {"decision": "FD-2", "spend_cap_usd": {}}, "no positive spend cap"),
        (None, {"decision": "FD-2", "spend_cap_usd": {ARM: 0}}, "no positive spend cap"),
        (None, {"decision": "FD-2", "spend_cap_usd": {ARM: True}}, "no positive spend cap"),
        (None, {"decision": "FD-2", "spend_cap_usd": {ARM: "165"}}, "no positive spend cap"),
        (None, {"decision": "FD-1", "spend_cap_usd": {ARM: 165}}, "does not record decision FD-2"),
    ],
)
def test_execute_with_an_invalid_receipt_is_refused(
    tmp_path: Path, fd1: object, fd2: object, reason: str
) -> None:
    refusal = run.execute_refusal(["--execute", "--arm", ARM, *_receipts(tmp_path, fd1, fd2)])
    assert refusal is not None and refusal.startswith("REFUSED") and reason in refusal


def test_execute_with_missing_or_unreadable_receipt_file_is_refused(tmp_path: Path) -> None:
    argv = ["--execute", "--arm", ARM, *_receipts(tmp_path)]
    (tmp_path / "fd2.json").unlink()
    assert "FD-2 receipt file does not exist" in str(run.execute_refusal(argv))
    (tmp_path / "fd2.json").write_text("{not json", encoding="utf-8")
    assert "FD-2 receipt is not readable JSON" in str(run.execute_refusal(argv))


def test_execute_with_valid_receipts_is_still_refused_without_live_transport(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def must_not_run(*_args: object) -> None:
        raise AssertionError("the mock report ran under --execute")

    monkeypatch.setattr(run, "report", must_not_run)
    assert run.main(["--execute", "--arm", ARM, *_receipts(tmp_path)]) == run.EXIT_REFUSED
    assert "ships no live transport" in capsys.readouterr().err


def test_execute_gate_is_the_first_statement_of_main() -> None:
    main = ast.parse(textwrap.dedent(inspect.getsource(run.main))).body[0]
    assert isinstance(main, ast.FunctionDef)
    first = main.body[0]
    assert isinstance(first, ast.If)
    assert "execute_refusal" in ast.unparse(first.test)
    assert isinstance(first.body[-1], ast.Return)
