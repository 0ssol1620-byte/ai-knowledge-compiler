"""The CI step that runs benchmark/tests must see the same import path pytest has.

``packages/absorption`` is kept out of the wheel on purpose and reaches tests only through
pytest's ``pythonpath``; ``unittest discover`` ignores that list and the screen tests then
fail to import (hosted run 44218955986). The step therefore runs pytest, which also executes
the pytest-style screen tests that ``unittest discover`` would import and collect as zero.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STEP = "Run benchmark metric tests"


def _step_command() -> str:
    lines = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8").splitlines()
    idx = [i for i, ln in enumerate(lines) if ln.strip() == f"- name: {STEP}"]
    assert len(idx) == 1, f"expected exactly one step named {STEP!r}, found {len(idx)}"
    for ln in lines[idx[0] + 1 :]:
        if ln.strip().startswith("- name:"):
            break
        m = re.match(r"\s*run:\s*(.+)$", ln)
        if m:
            return m.group(1)
    raise AssertionError(f"step {STEP!r} has no single-line run")


def test_step_runs_pytest_not_unittest_discover() -> None:
    cmd = _step_command()
    assert "unittest" not in cmd, cmd
    assert re.search(r"-m pytest\b.*\bbenchmark/tests\b", cmd), cmd


def test_absorption_reaches_tests_only_through_pytest_pythonpath() -> None:
    cfg = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert "packages/absorption/src" in cfg["tool"]["pytest"]["ini_options"]["pythonpath"]
    wheel = cfg["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]
    assert not any("absorption" in p for p in wheel)


def test_every_benchmark_test_module_is_covered_by_the_step() -> None:
    # A module under benchmark/tests that imports akc_absorption (directly) is the class
    # that broke the job; the step must be the pytest one for any such module to import.
    users = [
        p.name
        for p in (ROOT / "benchmark/tests").glob("test_*.py")
        if "akc_absorption" in p.read_text(encoding="utf-8")
        or "benchmark.screen" in p.read_text(encoding="utf-8")
    ]
    assert users, "no benchmark test imports the screen package; guard is stale"
    assert "pytest" in _step_command()
