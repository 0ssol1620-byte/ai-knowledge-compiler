"""Shared helpers for the runtime adapter tests.

``runtimes/<model_key>/`` is not a Python package: each directory is copied into
its own image as ``/opt/arena/runtime/`` and must stay self-contained, so three
lanes each ship a module literally named ``adapter.py``. These helpers load one
by path under a unique ``sys.modules`` name so the three cannot shadow each other.

Every runtime lane (C1, C2, C3) may use this file. Add helpers, do not change the
signature of one another lane already calls.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

NAMESPACE_ROOT = Path(__file__).resolve().parents[2]
RUNTIMES_ROOT = NAMESPACE_ROOT / "runtimes"


def runtime_dir(model_key: str) -> Path:
    return RUNTIMES_ROOT / model_key


def load_runtime_module(model_key: str, module_name: str) -> ModuleType:
    """Import ``runtimes/<model_key>/<module_name>.py`` under a collision-free name."""

    qualified = f"arena_runtime_{model_key}_{module_name}"
    cached = sys.modules.get(qualified)
    if cached is not None:
        return cached
    path = runtime_dir(model_key) / f"{module_name}.py"
    if not path.is_file():
        raise FileNotFoundError(f"no {module_name}.py for runtime {model_key}: {path}")
    spec = importlib.util.spec_from_file_location(qualified, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot build an import spec for {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[qualified] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(qualified, None)
        raise
    return module


def load_runtime_json(model_key: str) -> dict[str, Any]:
    """Read ``runtimes/<model_key>/runtime.json``."""

    path = runtime_dir(model_key) / "runtime.json"
    loaded: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise TypeError(f"{path} is not a JSON object")
    return loaded


def write_synthetic_png(path: Path, *, width: int = 64, height: int = 96) -> bytes:
    """Write a small white PNG and return its bytes.

    Requires pillow, which ARENA_CONTRACT §0 guarantees on every worker.
    """

    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (width, height), (255, 255, 255)).save(path, format="PNG")
    return path.read_bytes()
