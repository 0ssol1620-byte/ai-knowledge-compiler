"""D-T-live stub: the TAVONEL live product path behind the same adapter contract.

Product limits are the live capability manifest's (``at_most_5_mib_per_source``,
``at_most_80_pages_per_source``; VENDOR-COMPARISON-PREREG arms D-T-live) and refuse a document
before any request, as the product does. The response is read as Foundation's
``CollectionOcrRegion`` list (nextjs/lib/collection-compiler.ts:106-117): paragraph text ordered
by page and reading order. This joins text only; converting page, paragraph and bbox1000 into
each evaluator's input format is lane AT-6. The endpoint is FD-10's to decide, so it is None.
"""

from __future__ import annotations

from typing import Any

from .base import Adapter, Document, Failure, ResponseShape, Status, UsageValue

MAX_SOURCE_BYTES = 5 * 1024 * 1024
MAX_PAGES = 80
REGIONS_SOURCE = "Foundation nextjs/lib/collection-compiler.ts:106-117 CollectionOcrRegion"


class TavonelLiveStub(Adapter):
    vendor = "tavonel_live"
    wire_source = f"response read as {REGIONS_SOURCE}; endpoint decided by FD-10"
    default_shape = ResponseShape(source=REGIONS_SOURCE, markdown=("regions",))

    def preflight(self, document: Document) -> None:
        if len(document.pdf) > MAX_SOURCE_BYTES:
            raise Failure(
                Status.SIZE_REJECTED, f"{len(document.pdf)} bytes > {MAX_SOURCE_BYTES} limit"
            )
        if document.pages > MAX_PAGES:
            raise Failure(Status.SIZE_REJECTED, f"{document.pages} pages > {MAX_PAGES} limit")

    def decode(
        self, payload: Any, shape: ResponseShape
    ) -> tuple[str, int | None, dict[str, UsageValue]]:
        regions = payload.get("regions") if isinstance(payload, dict) else None
        if not isinstance(regions, list):
            raise Failure(Status.MALFORMED_RESPONSE, "regions: not a list")
        rows = []
        for region in regions:
            if not isinstance(region, dict):
                raise Failure(Status.MALFORMED_RESPONSE, "region: not an object")
            page, order, text = region.get("pageNumber1"), region.get("order"), region.get("text")
            if not (
                type(page) is int and type(order) is int and isinstance(text, str) and page >= 1
            ):
                raise Failure(
                    Status.MALFORMED_RESPONSE, "region needs int pageNumber1, int order, str text"
                )
            rows.append((page, order, text))
        return "\n\n".join(text for _, _, text in sorted(rows)), None, {}
