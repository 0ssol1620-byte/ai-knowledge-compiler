"""D-T-live stub: the TAVONEL live product path behind the same adapter contract.

Product limits are the live capability manifest's (``at_most_5_mib_per_source``,
``at_most_80_pages_per_source``; VENDOR-COMPARISON-PREREG arms D-T-live) and refuse a document
before any request, as the product does. The response is Foundation's ``CollectionOcrRegion``
list (nextjs/lib/collection-compiler.ts:106-117), read by the D-T-live evaluator adapter's own
``tavonel_live.read_regions`` (after collection-compiler.ts:520-541), so a body the adapter
would refuse is never an OK result here: an empty region list is ``EMPTY_OUTPUT``, any other body
it calls malformed is ``MALFORMED_RESPONSE``, and a table read or a non-paragraph block raises
``StructureNotImplemented`` out of ``parse``, because the status it maps to is the
preregistration's to decide, not this stub's. The markdown is the paragraph text in page and
reading order; converting page, paragraph and bbox1000 into each evaluator's input format is
lane AT-6. The endpoint is FD-10's to decide, so it is None.
"""

from __future__ import annotations

from typing import Any

from .base import Adapter, Document, Failure, ResponseShape, Status, UsageValue
from .tavonel_live import MalformedLiveOutput, read_regions

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
        try:
            regions = read_regions(payload)  # StructureNotImplemented propagates
        except MalformedLiveOutput as exc:
            if isinstance(payload, dict) and payload.get("regions") == []:
                return "", None, {}  # a success with no content: EMPTY_OUTPUT
            raise Failure(Status.MALFORMED_RESPONSE, str(exc)) from exc
        return "\n\n".join(region.text for region in regions), None, {}
