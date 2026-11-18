"""The CI step that runs benchmark/tests must see the same import path pytest has.

``packages/absorption`` is kept out of the wheel on purpose and reaches tests only through
pytest's ``pythonpath``; a bare ``unittest discover`` ignores that list and the screen tests
then fail to import (hosted run 44218955986). The step keeps ``unittest discover`` (seconds,
not the 15 minutes the whole suite takes under pytest) and builds PYTHONPATH from pyproject.
"""

from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STEP = "Run benchmark metric tests"
EXPECTED_CODE = (
    "import tomllib,os;print(os.pathsep.join(tomllib.load(open('pyproject.toml','rb'))"
    "['tool']['pytest']['ini_options']['pythonpath']))"
)
SNIPPET = re.compile(r'PYTHONPATH="\$\(python -c "(?P<code>[^"]+)"\)"')


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


def test_step_keeps_unittest_and_takes_path_from_pyproject() -> None:
    cmd = _step_command()
    assert "-m unittest discover -s benchmark/tests" in cmd, cmd
    assert "-m pytest" not in cmd, cmd
    m = SNIPPET.search(cmd)
    assert m, "step must set PYTHONPATH from pyproject.toml"
    assert m["code"] == EXPECTED_CODE, m["code"]


def test_absorption_reaches_tests_only_through_pytest_pythonpath() -> None:
    cfg = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert "packages/absorption/src" in cfg["tool"]["pytest"]["ini_options"]["pythonpath"]
    wheel = cfg["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]
    assert not any("absorption" in p for p in wheel)


def test_every_src_package_a_benchmark_test_imports_is_on_the_pyproject_path() -> None:
    # The class that broke the job: a benchmark test imports a package that lives in a
    # packages/*/src dir missing from pyproject's pythonpath (which is now the step's path).
    cfg = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    on_path = {
        Path(p).as_posix().rstrip("/") for p in cfg["tool"]["pytest"]["ini_options"]["pythonpath"]
    }
    imported: set[str] = set()
    for f in (ROOT / "benchmark/tests").glob("*.py"):
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                imported |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imported.add(node.module.split(".")[0])
    homes = {
        pkg.name: src.relative_to(ROOT).as_posix()
        for src in ROOT.glob("packages/*/src")
        for pkg in src.iterdir()
        if pkg.is_dir()
    }
    assert "akc_absorption" in imported, (
        "guard is stale: no benchmark test imports the screen package"
    )
    missing = {n: homes[n] for n in imported & homes.keys() if homes[n] not in on_path}
    assert not missing, f"imported packages whose src dir is not on the step's path: {missing}"
