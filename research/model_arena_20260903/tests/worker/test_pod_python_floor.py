"""Everything that runs inside a pod must parse on the oldest interpreter an image ships.

Real canary 2026-09-03 (deepseek_ocr2, pod rgbpf4s0oq2e15): the pytorch/pytorch
2.6.0-cuda11.8 image runs Python 3.11 and the worker died at import time on a
PEP 695 type-parameter list (``def f[T](...)``), after the weights and the
preflight had already been paid for. The controller runs on the campaign venv,
but ``arena/worker`` (never ``arena/core``, see ``arena/worker/bundle.py``)
and every ``runtimes/<key>/*.py`` are shipped in the bundle and executed by the
image's own Python. Parse them with the
oldest floor we accept so the failure happens here, not on a GPU.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from arena.worker.bundle import ARENA_BUNDLED_DIRS, ARENA_BUNDLED_FILES

NAMESPACE = Path(__file__).resolve().parents[2]
POD_PYTHON_FLOOR = (3, 10)


def _pod_side_files() -> list[Path]:
    """Exactly what ``arena/worker/bundle.py`` ships, plus every runtime's code."""
    files = [NAMESPACE / name for name in ARENA_BUNDLED_FILES if name.endswith(".py")]
    for directory in ARENA_BUNDLED_DIRS:
        files += sorted((NAMESPACE / directory).rglob("*.py"))
    files += sorted((NAMESPACE / "runtimes").glob("*/*.py"))
    return files


@pytest.mark.parametrize("path", _pod_side_files(), ids=lambda p: str(p.relative_to(NAMESPACE)))
def test_pod_side_python_parses_on_the_floor_interpreter(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    try:
        ast.parse(source, filename=str(path), feature_version=POD_PYTHON_FLOOR)
    except SyntaxError as exc:  # pragma: no cover - the message is the point
        pytest.fail(
            f"{path.relative_to(NAMESPACE)}:{exc.lineno} needs Python newer than "
            f"{POD_PYTHON_FLOOR[0]}.{POD_PYTHON_FLOOR[1]}: {exc.msg}"
        )


def test_the_floor_check_actually_rejects_newer_syntax() -> None:
    with pytest.raises(SyntaxError):
        ast.parse("def f[T](x: T) -> T:\n    return x\n", feature_version=POD_PYTHON_FLOOR)


# Names that parse fine on 3.10 but do not exist there. ``ast.parse`` cannot
# see these; the paddleocr_vl_1_6 canary (pod kfvy42gzo6ikt3, Python 3.10.16)
# did: ``ImportError: cannot import name 'UTC' from 'datetime'`` after the
# genai server was up and the weights were paid for (ARENA_CONTRACT D65).
NEWER_THAN_FLOOR: dict[str, frozenset[str]] = {
    "datetime": frozenset({"UTC"}),
    "enum": frozenset({"StrEnum", "ReprEnum", "verify", "member", "nonmember"}),
    "typing": frozenset({"Self", "Never", "LiteralString", "TypeVarTuple", "Unpack",
                         "assert_never", "reveal_type", "dataclass_transform", "override",
                         "TypeAliasType"}),
    "asyncio": frozenset({"timeout", "TaskGroup"}),
    "contextlib": frozenset({"chdir"}),
    "hashlib": frozenset({"file_digest"}),
    "itertools": frozenset({"batched"}),
}
NEWER_MODULES = frozenset({"tomllib"})
COMPAT_MODULE = NAMESPACE / "arena" / "worker" / "compat.py"


def _newer_names_used(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[str] = []
    aliases: dict[str, str] = {}  # ``import datetime as dt`` -> {"dt": "datetime"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                aliases[alias.asname or alias.name] = alias.name
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            names = NEWER_THAN_FLOOR.get(node.module, frozenset())
            found += [f"from {node.module} import {a.name}" for a in node.names if a.name in names]
            if node.module in NEWER_MODULES or node.module.split(".")[0] in NEWER_MODULES:
                found.append(f"from {node.module} import ...")
        elif isinstance(node, ast.Import):
            found += [
                f"import {a.name}" for a in node.names if a.name.split(".")[0] in NEWER_MODULES
            ]
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            module = aliases.get(node.value.id, node.value.id)
            if node.attr in NEWER_THAN_FLOOR.get(module, frozenset()):
                found.append(f"{node.value.id}.{node.attr}")
    return found


@pytest.mark.parametrize("path", _pod_side_files(), ids=lambda p: str(p.relative_to(NAMESPACE)))
def test_pod_side_python_avoids_stdlib_names_newer_than_the_floor(path: Path) -> None:
    if path == COMPAT_MODULE:
        pytest.skip("the one place the older spellings live")
    used = _newer_names_used(path)
    assert not used, (
        f"{path.relative_to(NAMESPACE)} uses {used}, which Python "
        f"{POD_PYTHON_FLOOR[0]}.{POD_PYTHON_FLOOR[1]} does not have; "
        "take it from arena.worker.compat instead"
    )


def test_the_name_check_actually_catches_the_paddle_failure(tmp_path: Path) -> None:
    sample = tmp_path / "sample.py"
    lines = [
        "from datetime import UTC, datetime",
        "from enum import StrEnum",
        "import datetime as dt",
        "x = dt.UTC",
    ]
    sample.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert _newer_names_used(sample) == [
        "from datetime import UTC", "from enum import StrEnum", "dt.UTC"
    ]
