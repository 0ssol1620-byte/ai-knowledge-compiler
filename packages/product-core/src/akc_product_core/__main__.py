"""Environment-bound ASGI entrypoint for the Product-Core container."""

from __future__ import annotations

import os

from .api import create_product_core_app
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


app = create_product_core_app(
    hmac_secret=_required("TAVONEL_PRODUCT_CORE_HMAC").encode(),
    core_release_digest=_required("TAVONEL_CORE_RELEASE_DIGEST"),
    allow_customer_data=os.environ.get("TAVONEL_CORE_ALLOW_CUSTOMER_DATA") == "true",
    output_budget_bytes=_output_budget(),
)
