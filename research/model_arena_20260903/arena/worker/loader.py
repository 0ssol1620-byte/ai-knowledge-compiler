"""Load ``adapter.py`` and ``canonical.py`` out of the runtime directory.

The runtime directory is baked into the image (or unpacked from the bootstrap
bundle) at ``/opt/arena/runtime``. It is campaign-controlled code, not model
output, so importing it by file path is safe; the worker still refuses to run
if the module does not expose the contracted entry points.

Entry points (contract addendum, see the lane report):

* ``adapter.py`` exposes ``create_adapter() -> ArenaModelAdapter`` **or** a
  module-level ``ADAPTER`` instance.
* ``canonical.py`` exposes ``canonicalize(raw: RawOutput) -> CanonicalOutput``.
"""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Final

from arena.worker import canonical_default
from arena.worker.adapter_api import ArenaModelAdapter, CanonicalOutput, RawOutput
from arena.worker.config import WorkerConfigError, require_runtime_dir

ADAPTER_MODULE_NAME: Final = "arena_runtime_adapter"
CANONICAL_MODULE_NAME: Final = "arena_runtime_canonical"
ADAPTER_FILE: Final = "adapter.py"
CANONICAL_FILE: Final = "canonical.py"
DEFAULT_CANONICALIZER_SOURCE: Final = "arena.worker.canonical_default"

Canonicalize = Callable[[RawOutput], CanonicalOutput]


def import_module_from_path(module_name: str, path: Path) -> ModuleType:
    """Import ``path`` under ``module_name`` without touching ``sys.path``."""
    if not path.is_file():
        raise WorkerConfigError(f"module not found: {path}")
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise WorkerConfigError(f"cannot build an import spec for {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module


def _sole_adapter_class(module: ModuleType) -> type[object] | None:
    """The one ``*Adapter`` class the module itself defines, if there is exactly one.

    Ambiguity fails closed: two candidate classes mean the worker would be
    guessing which model it is about to attribute output to.
    """
    candidates = [
        value
        for name, value in vars(module).items()
        if isinstance(value, type)
        and name.endswith("Adapter")
        and getattr(value, "__module__", None) == module.__name__
    ]
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        names = sorted(candidate.__name__ for candidate in candidates)
        raise WorkerConfigError(
            f"{module.__file__} defines {len(candidates)} adapter classes ({names}); "
            "expose create_adapter() to say which one the worker must run"
        )
    return None


def load_adapter(runtime_dir: Path) -> ArenaModelAdapter:
    """Instantiate the runtime's model adapter.

    Discovery order, all explicit: ``create_adapter()``, then a module-level
    ``ADAPTER``, then the single ``*Adapter`` class the module defines.
    """
    adapter_path = require_runtime_dir(runtime_dir) / ADAPTER_FILE
    if not adapter_path.is_file():
        raise WorkerConfigError(
            f"adapter not found: {adapter_path} (ARENA_RUNTIME_DIR={runtime_dir})"
        )
    module = import_module_from_path(ADAPTER_MODULE_NAME, adapter_path)
    factory = getattr(module, "create_adapter", None)
    adapter_class = None if callable(factory) or hasattr(module, "ADAPTER") else (
        _sole_adapter_class(module)
    )
    if callable(factory):
        adapter = factory()
    elif hasattr(module, "ADAPTER"):
        adapter = module.ADAPTER
    elif adapter_class is not None:
        try:
            adapter = adapter_class()
        except TypeError as exc:
            raise WorkerConfigError(
                f"{runtime_dir / ADAPTER_FILE}: {adapter_class.__name__}() needs arguments; "
                "expose create_adapter() instead"
            ) from exc
    else:
        raise WorkerConfigError(
            f"{runtime_dir / ADAPTER_FILE} exposes no create_adapter(), no ADAPTER and no "
            "single *Adapter class"
        )
    if not isinstance(adapter, ArenaModelAdapter):
        raise WorkerConfigError(
            f"{runtime_dir / ADAPTER_FILE} produced {type(adapter).__name__}, which does not "
            "implement arena.worker.adapter_api.ArenaModelAdapter"
        )
    return adapter


def load_canonicalizer(runtime_dir: Path) -> tuple[Canonicalize, str]:
    """Return ``(canonicalize, source_label)``.

    Falling back to the passthrough converter is a labelled decision, not a
    silent one: the label is reported on ``/v1/ready`` and in every receipt the
    controller builds from it.
    """
    path = require_runtime_dir(runtime_dir) / CANONICAL_FILE
    if not path.is_file():
        return canonical_default.canonicalize, DEFAULT_CANONICALIZER_SOURCE
    module = import_module_from_path(CANONICAL_MODULE_NAME, path)
    func = getattr(module, "canonicalize", None)
    if not callable(func):
        raise WorkerConfigError(f"{path} does not expose a callable canonicalize(raw)")
    return func, str(path)


__all__ = [
    "ADAPTER_FILE",
    "CANONICAL_FILE",
    "DEFAULT_CANONICALIZER_SOURCE",
    "Canonicalize",
    "import_module_from_path",
    "load_adapter",
    "load_canonicalizer",
]
