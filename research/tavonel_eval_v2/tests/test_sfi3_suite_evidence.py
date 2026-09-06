"""Focused controls for the external, memory-bounded SFI3 suite recorder."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(NS / "tools"))

import record_sfi3_suite_evidence as recorder  # noqa: E402


def _sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _under(root: Path):
    return lambda path: path.resolve().relative_to(root).as_posix()


def test_enumeration_is_recursive_sorted_and_excludes_non_tests(tmp_path, monkeypatch):
    (tmp_path / "z").mkdir()
    (tmp_path / "z" / "test_b.py").write_text("", encoding="utf-8")
    (tmp_path / "test_a.py").write_text("", encoding="utf-8")
    (tmp_path / "z" / "helper.py").write_text("", encoding="utf-8")
    monkeypatch.setattr(recorder, "_relative", _under(tmp_path))
    assert [path.name for path in recorder.enumerate_tests(tmp_path)] == ["test_a.py", "test_b.py"]


def test_suite_manifest_binds_paths_bytes_and_pytest_arguments(tmp_path, monkeypatch):
    first = tmp_path / "test_a.py"
    first.write_text("one", encoding="utf-8")
    monkeypatch.setattr(recorder, "_relative", _under(tmp_path))
    before = recorder.suite_manifest((first,))
    first.write_text("two", encoding="utf-8")
    after = recorder.suite_manifest((first,))
    assert before["digest"] != after["digest"]
    assert before["pytest_args"] == list(recorder.PYTEST_ARGS)
    assert before["files"][0]["path"] == "test_a.py"


@pytest.mark.parametrize(
    ("xml", "expected"),
    [
        ('<testsuite tests="3" skipped="1" failures="0" errors="0"/>', (3, 1, 0, 0)),
        (
            '<testsuites><testsuite tests="2" skipped="0" failures="1" errors="0"/>'
            '<testsuite tests="4" skipped="2" failures="0" errors="1"/></testsuites>',
            (6, 2, 1, 1),
        ),
    ],
)
def test_junit_counts_are_machine_parsed(tmp_path, xml, expected):
    path = tmp_path / "junit.xml"
    path.write_text(xml, encoding="utf-8")
    counts = recorder.parse_junit(path)
    assert (counts.tests, counts.skipped, counts.failures, counts.errors) == expected


def test_junit_without_required_counts_is_refused(tmp_path):
    path = tmp_path / "junit.xml"
    path.write_text('<testsuite tests="1"/>', encoding="utf-8")
    with pytest.raises(ValueError, match="omits"):
        recorder.parse_junit(path)


def test_shard_streams_output_and_records_missing_junit_as_red(tmp_path, monkeypatch):
    test_file = tmp_path / "test_one.py"
    test_file.write_text("", encoding="utf-8")
    transcript = tmp_path / "output.log"
    junit = tmp_path / "missing.xml"
    monkeypatch.setattr(recorder, "ROOT", tmp_path)
    monkeypatch.setattr(recorder, "_relative", _under(tmp_path))
    monkeypatch.setattr(
        recorder,
        "shard_command",
        lambda _test, _junit: [sys.executable, "-c", "print('streamed-directly')"],
    )
    with transcript.open("xb") as output:
        result = recorder.run_shard(test_file, junit, output)
    assert result.exit_code == 0
    assert result.junit_error is not None
    assert "streamed-directly" in transcript.read_text(encoding="utf-8")
    assert recorder._aggregate_exit([result]) == 1


def test_shard_accepts_a_terminal_junit_and_hashes_it(tmp_path, monkeypatch):
    test_file = tmp_path / "test_one.py"
    test_file.write_text("", encoding="utf-8")
    transcript = tmp_path / "output.log"
    junit = tmp_path / "junit.xml"
    code = (
        "from pathlib import Path; "
        f"Path({str(junit)!r}).write_text("
        '\'<testsuite tests="7" skipped="2" failures="0" errors="0"/>\', encoding=\'utf-8\'); '
        "print('done')"
    )
    monkeypatch.setattr(recorder, "ROOT", tmp_path)
    monkeypatch.setattr(recorder, "_relative", _under(tmp_path))
    monkeypatch.setattr(
        recorder, "shard_command", lambda _test, _junit: [sys.executable, "-c", code]
    )
    with transcript.open("xb") as output:
        result = recorder.run_shard(test_file, junit, output)
    assert result.junit_error is None
    assert (result.tests, result.skipped, result.exit_code) == (7, 2, 0)
    assert result.junit_file_sha256 == _sha(junit)
    assert recorder._aggregate_exit([result]) == 0


def test_empty_or_incomplete_shards_can_never_aggregate_green():
    assert recorder._aggregate_exit([]) == 1
    incomplete = recorder.ShardResult(
        test_file="test_x.py",
        command=["python", "-m", "pytest"],
        exit_code=0,
        junit_file="junit.xml",
        junit_file_sha256=None,
        tests=0,
        skipped=0,
        failures=0,
        errors=0,
        peak_rss_bytes=None,
        junit_error="missing",
    )
    assert recorder._aggregate_exit([incomplete]) == 1


def test_main_writes_one_prior_run_receipt_only_after_all_shards_complete(
    tmp_path, monkeypatch, capsys
):
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    test_files = tuple(tests_dir / name for name in ("test_a.py", "test_b.py"))
    for path in test_files:
        path.write_text("", encoding="utf-8")
    fake_python = tmp_path / "python.exe"
    fake_python.write_text("", encoding="utf-8")
    fake_tool = tmp_path / "record_sfi3_suite_evidence.py"
    fake_tool.write_text("", encoding="utf-8")
    output_root = tmp_path / "outputs"
    calls: list[dict] = []

    monkeypatch.setattr(recorder, "ROOT", tmp_path)
    monkeypatch.setattr(recorder, "NS", tmp_path)
    monkeypatch.setattr(recorder, "TESTS", tests_dir)
    monkeypatch.setattr(recorder, "VENV_PYTHON", fake_python)
    monkeypatch.setattr(recorder.sys, "executable", str(fake_python))
    monkeypatch.setattr(recorder, "THIS_TOOL", fake_tool)
    monkeypatch.setattr(recorder, "OUTPUTS", output_root)
    monkeypatch.setattr(recorder, "TOOLING_DIRS", ())
    monkeypatch.setattr(recorder, "TOOLING_FILES", (fake_python,))
    monkeypatch.setattr(recorder, "_relative", _under(tmp_path))
    monkeypatch.setattr(recorder, "new_run_id", lambda _tool: "20260826T000000Z-testfixture")

    def fake_run(test_file, junit_file, transcript):
        transcript.write((test_file.name + "\n").encode())
        junit_file.write_text(
            '<testsuite tests="3" skipped="1" failures="0" errors="0"/>', encoding="utf-8"
        )
        return recorder.ShardResult(
            test_file=recorder._relative(test_file),
            command=["pytest", recorder._relative(test_file)],
            exit_code=0,
            junit_file=recorder._relative(junit_file),
            junit_file_sha256=_sha(junit_file),
            tests=3,
            skipped=1,
            failures=0,
            errors=0,
            peak_rss_bytes=123,
            junit_error=None,
        )

    def fake_write(stem, body, **kwargs):
        assert len(body["shards"]) == 2
        assert body["completed"] is True
        assert body["exit_code"] == 0
        assert body["test_count"] == 6
        assert body["skip_count"] == 2
        assert body["output_file_sha256"] == _sha(tmp_path / body["output_file"])
        assert kwargs["pointer"] is False
        calls.append(body)
        return {"receipt": "receipt.json", "receipt_file_sha256": "sha256:ok"}

    monkeypatch.setattr(recorder, "run_shard", fake_run)
    monkeypatch.setattr(recorder, "write_immutable", fake_write)
    assert recorder.main([]) == 0
    assert len(calls) == 1
    printed = json.loads(capsys.readouterr().out)
    assert printed["receipt"] == "receipt.json"
    assert printed["completed"] is True


def test_main_does_not_issue_a_green_receipt_for_a_lost_run(tmp_path, monkeypatch):
    """A killed process raises out of the runner; no receipt can be inferred."""
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    test_file = tests_dir / "test_a.py"
    test_file.write_text("", encoding="utf-8")
    fake_python = tmp_path / "python.exe"
    fake_python.write_text("", encoding="utf-8")
    fake_tool = tmp_path / "record_sfi3_suite_evidence.py"
    fake_tool.write_text("", encoding="utf-8")
    writes: list[object] = []
    monkeypatch.setattr(recorder, "ROOT", tmp_path)
    monkeypatch.setattr(recorder, "TESTS", tests_dir)
    monkeypatch.setattr(recorder, "VENV_PYTHON", fake_python)
    monkeypatch.setattr(recorder.sys, "executable", str(fake_python))
    monkeypatch.setattr(recorder, "THIS_TOOL", fake_tool)
    monkeypatch.setattr(recorder, "OUTPUTS", tmp_path / "outputs")
    monkeypatch.setattr(recorder, "TOOLING_DIRS", ())
    monkeypatch.setattr(recorder, "TOOLING_FILES", (fake_python,))
    monkeypatch.setattr(recorder, "_relative", _under(tmp_path))
    monkeypatch.setattr(recorder, "new_run_id", lambda _tool: "20260826T000001Z-lostfixture")
    monkeypatch.setattr(
        recorder,
        "run_shard",
        lambda *_args: (_ for _ in ()).throw(KeyboardInterrupt()),
    )
    monkeypatch.setattr(recorder, "write_immutable", lambda *args, **kwargs: writes.append(args))
    with pytest.raises(KeyboardInterrupt):
        recorder.main([])
    assert writes == []
