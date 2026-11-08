"""Environment-bound ASGI entrypoint for the Product-Core container."""

from __future__ import annotations

import os

from .api import CorpusReduceMode, create_product_core_app
from .compiler import OUTPUT_BUDGET_BYTES


def _required(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _output_budget(name: str = "TAVONEL_CORE_OUTPUT_BUDGET_BYTES") -> int:
    """Downward only: above the default, or not an integer, the process does not start."""
    raw = os.environ.get(name, str(OUTPUT_BUDGET_BYTES))
    try:
        value = int(raw)
    except ValueError:
        raise RuntimeError(f"{name} must be an integer byte count, got {raw!r}") from None
    if not 0 < value <= OUTPUT_BUDGET_BYTES:
        raise RuntimeError(f"{name} must be in (0, {OUTPUT_BUDGET_BYTES}], got {value}")
    return value


def _corpus_reduce_mode(name: str = "TAVONEL_CORPUS_REDUCE_MODE") -> CorpusReduceMode:
    """`off` (default) or `shadow`. `on` is refused: rollout waits on the equivalence gate."""
    raw = os.environ.get(name, "off")
    if raw == "off":
        return "off"
    if raw == "shadow":
        return "shadow"
    if raw == "on":
        raise RuntimeError(
            f"{name}=on is not available: corpus_reduce serves nothing until the split/whole "
            "equivalence benchmark passes 100% on a real corpus (ADR-008)"
        )
    raise RuntimeError(f"{name} must be off or shadow, got {raw!r}")


app = create_product_core_app(
    hmac_secret=_required("TAVONEL_PRODUCT_CORE_HMAC").encode(),
    core_release_digest=_required("TAVONEL_CORE_RELEASE_DIGEST"),
    allow_customer_data=os.environ.get("TAVONEL_CORE_ALLOW_CUSTOMER_DATA") == "true",
    output_budget_bytes=_output_budget(),
    corpus_reduce_mode=_corpus_reduce_mode(),
)
