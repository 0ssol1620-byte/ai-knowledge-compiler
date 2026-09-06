"""Environment-bound ASGI entrypoint for the Product-Core container."""

from __future__ import annotations

import os

from .api import create_product_core_app


def _required(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


app = create_product_core_app(
    hmac_secret=_required("TAVONEL_PRODUCT_CORE_HMAC").encode(),
    core_release_digest=_required("TAVONEL_CORE_RELEASE_DIGEST"),
    allow_customer_data=os.environ.get("TAVONEL_CORE_ALLOW_CUSTOMER_DATA") == "true",
)
