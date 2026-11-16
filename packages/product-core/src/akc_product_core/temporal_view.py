"""A bitemporal view of one compile, computed beside the candidate and never inside it."""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from akc_cir.temporal import TemporalFact, TemporalSource, TemporalTimeline

from .contracts import ProductCoreCompileRequest, ProductCoreCompileResponse


def timeline_from_compile(
    request: ProductCoreCompileRequest, response: ProductCoreCompileResponse
) -> tuple[TemporalTimeline, dict[str, datetime | None]]:
    """One `TemporalFact` per claim, plus claim logical id -> its document's `available_at`.

    Validity comes only from dates the source document declared. `recorded_at` is the
    request's `requested_at`: the moment the system recorded the claim, which is system time.
    """
    documents = {
        (document.source_id, document.source_version_id): document
        for document in request.documents
    }
    timeline = TemporalTimeline()
    available: dict[str, datetime | None] = {}
    objects = cast(
        "list[dict[str, Any]]", response.candidate.canonical_knowledge_model["objects"]
    )
    for item in objects:
        if item["kind"] != "claim":
            continue
        payload = item["payload"]
        document = documents.get((payload["sourceId"], payload["sourceVersionId"]))
        valid_from = document.valid_from if document else None
        valid_to = document.valid_to if document else None
        declared = valid_from is not None or valid_to is not None
        logical_id = payload["logicalId"]
        timeline.add(
            TemporalFact(
                logical_id=logical_id,
                value=payload["text"],
                valid_from=valid_from,
                valid_to=valid_to,
                recorded_at=request.requested_at,
                temporal_source=TemporalSource.EXPLICIT if declared else TemporalSource.UNKNOWN,
                evidence_id=payload["evidenceId"],
            )
        )
        available[logical_id] = document.available_at if document else None
    return timeline, available
