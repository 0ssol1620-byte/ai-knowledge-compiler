"""Every real runtime directory must load through the worker's loader.

This is the B2 ↔ C1/C2/C3 seam. It runs on a CPU box with no GPU and no
network, which is the point: a runtime whose heavy imports leak to module
scope, or that exposes no entry point the worker recognises, fails here rather
than on a paid pod.
"""

from __future__ import annotations

import sys

import pytest
from arena.constants import GPU_MODEL_KEYS, NAMESPACE_ROOT
from arena.worker.adapter_api import ArenaModelAdapter
from arena.worker.loader import (
    ADAPTER_MODULE_NAME,
    CANONICAL_MODULE_NAME,
    load_adapter,
    load_canonicalizer,
)

RUNTIMES_ROOT = NAMESPACE_ROOT / "runtimes"


@pytest.fixture(autouse=True)
def _clear_runtime_modules() -> None:
    """Each runtime imports under the same module name; never reuse a stale one."""
    for name in (ADAPTER_MODULE_NAME, CANONICAL_MODULE_NAME):
        sys.modules.pop(name, None)


@pytest.mark.parametrize("model_key", GPU_MODEL_KEYS)
def test_runtime_adapter_loads_without_a_gpu(model_key: str) -> None:
    runtime_dir = RUNTIMES_ROOT / model_key
    if not (runtime_dir / "adapter.py").is_file():
        pytest.skip(f"runtimes/{model_key}/adapter.py does not exist yet")

    adapter = load_adapter(runtime_dir)
    assert isinstance(adapter, ArenaModelAdapter)
    assert adapter.model_key == model_key, (
        "adapter.model_key must equal the runtime directory it lives in, or a receipt "
        "would attribute output to the wrong model"
    )

    canonicalize, source = load_canonicalizer(runtime_dir)
    assert callable(canonicalize)
    assert source.endswith("canonical.py") or source == "arena.worker.canonical_default"
