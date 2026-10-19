"""D-V-landingai: Agentic Document Extraction parse, DPT-3 Pro, synchronous (priority tier).

Wire facts come from competitor-protocol-receipts/web/landingai-credit-consumption.html
(sha256 64a6eeedb133…, retrieved 2026-10-17T01:27:20Z): the response has the ``markdown`` field,
and ``metadata.page_count``, ``metadata.output_markdown_chars``, ``metadata.billing.service_tier``
and ``metadata.billing.total_credits``. "DPT-3 Pro is the default" and "Synchronous Parse requests
run on the priority tier", so the headline arm sends no options. The endpoint URL and request
field names were not captured: ``endpoint`` stays None and the arm config is sent as given.
"""

from __future__ import annotations

from .base import Adapter, ResponseShape

RECEIPT = "competitor-protocol-receipts/web/landingai-credit-consumption.html sha256 64a6eeedb133"


class LandingAIAdapter(Adapter):
    vendor = "landingai"
    wire_source = f"documented response fields: {RECEIPT}; endpoint not captured"
    default_shape = ResponseShape(
        source=RECEIPT,
        markdown=("markdown",),
        page_count=("metadata", "page_count"),
        usage={
            "output_markdown_chars": ("metadata", "output_markdown_chars"),
            "service_tier": ("metadata", "billing", "service_tier"),
            "total_credits": ("metadata", "billing", "total_credits"),
        },
    )
