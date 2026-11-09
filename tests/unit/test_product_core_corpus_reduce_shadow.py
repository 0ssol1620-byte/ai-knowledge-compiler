"""TAVONEL_CORPUS_REDUCE_MODE: shadow records a receipt; off and shadow serve the same bytes."""

from __future__ import annotations

import importlib
import random
from datetime import UTC, datetime
from typing import Any

import pytest
from akc_cir.base import canonical_json
from akc_product_core.api import ProductCoreService
from akc_product_core.auth import sign_product_core_request
from akc_product_core.contracts import (
    CorpusPart,
    ProductCoreCompileRequest,
    ProductCoreDocument,
    ProductCoreRoute,
)

from benchmark.product_core_corpus_reduce import COLLECTION, RELEASE, TENANT, WORKSPACE, _document

SECRET = b"foundation-product-core-test-secret-32-bytes-minimum"
_RNG = random.Random(11)
DOCUMENTS = [
    _document(_RNG, 60, i, sentences=(text,))
    for i, text in enumerate(
        (
            "Acme Holdings reported revenue of 100 million in 2025.",
            "ACME HOLDINGS reported revenue of 120 million in 2025.",
            "The Agreement is binding on both parties.",
            "The Agreement is not binding on both parties.",
        )
    )
]


def _body(
    documents: list[ProductCoreDocument],
    request_id: str,
    *,
    part: CorpusPart | None,
    collection: str = COLLECTION,
) -> bytes:
    request = ProductCoreCompileRequest(
        request_id=request_id,
        idempotency_key=f"idem-{request_id}",
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        collection_id=collection,
        requested_at=datetime(2026, 11, 8, tzinfo=UTC),
        route=ProductCoreRoute(
            operation_class="initial_compile",
            quality_requirement="standard",
            max_cost_credits=100,
            max_latency_ms=60_000,
            privacy_policy="foundation_synthetic_only",
        ),
        documents=tuple(documents),
        corpus_part=part,
    )
    return canonical_json(
        request.model_dump(mode="json", by_alias=True, exclude_none=True)
    ).encode()


def _post(service: ProductCoreService, body: bytes, request_id: str) -> tuple[int, Any]:
    headers = sign_product_core_request(
        body=body,
        request_id=request_id,
        timestamp=int(datetime.now(tz=UTC).timestamp()),
        secret=SECRET,
    )
    return service.compile(body=body, headers=headers)


def _corpus_bodies(*, second_collection: str = COLLECTION) -> list[tuple[bytes, str]]:
    return [
        (
            _body(
                [DOCUMENTS[0], DOCUMENTS[2]],
                "corpus-part-0",
                part=CorpusPart(corpus_id="corpus-shadow", part_index=0, part_count=2),
            ),
            "corpus-part-0",
        ),
        (
            _body(
                [DOCUMENTS[1], DOCUMENTS[3]],
                "corpus-part-1",
                part=CorpusPart(corpus_id="corpus-shadow", part_index=1, part_count=2),
                collection=second_collection,
            ),
            "corpus-part-1",
        ),
    ]


def _serve(mode: str, bodies: list[tuple[bytes, str]]) -> tuple[ProductCoreService, list[Any]]:
    service = ProductCoreService(
        hmac_secret=SECRET,
        core_release_digest=RELEASE,
        corpus_reduce_mode=mode,  # type: ignore[arg-type]
    )
    return service, [_post(service, body, request_id) for body, request_id in bodies]


def test_off_is_the_default_and_records_nothing() -> None:
    service = ProductCoreService(hmac_secret=SECRET, core_release_digest=RELEASE)
    assert service.corpus_reduce_mode == "off"
    for body, request_id in _corpus_bodies():
        assert _post(service, body, request_id)[0] == 200
    assert list(service.shadow_events) == []


def test_shadow_records_one_receipt_and_serves_exactly_what_off_serves() -> None:
    bodies = _corpus_bodies()
    _, served_off = _serve("off", bodies)
    shadow, served_shadow = _serve("shadow", bodies)
    assert served_shadow == served_off
    assert [status for status, _ in served_shadow] == [200, 200]
    events = list(shadow.shadow_events)
    assert [event["event"] for event in events] == ["corpus_reduce_shadow"]
    receipt = events[0]
    assert receipt["partCount"] == 2
    assert receipt["documentCount"] == 4
    assert receipt["candidatePromotion"] is False
    assert receipt["crossPartEntityCount"] >= 1  # Acme Holdings in both parts
    assert receipt["crossPartContradictionCount"] == 1  # 100 vs 120 million, across the seam
    assert [row["requestId"] for row in receipt["inputs"]] == ["corpus-part-0", "corpus-part-1"]
    assert [row["outputSha256"] for row in receipt["inputs"]] == [
        payload["receipt"]["outputSha256"] for _, payload in served_shadow
    ]


def test_a_shadow_refusal_is_logged_and_changes_nothing_served() -> None:
    bodies = _corpus_bodies(second_collection="collection-elsewhere")
    _, served_off = _serve("off", bodies)
    shadow, served_shadow = _serve("shadow", bodies)
    assert served_shadow == served_off
    events = list(shadow.shadow_events)
    assert [(event["event"], event.get("code")) for event in events] == [
        ("corpus_reduce_shadow_refused", "REDUCE_PART_SCOPE_MISMATCH")
    ]


def test_shadow_ignores_a_compile_that_is_not_a_corpus_part() -> None:
    shadow, served = _serve("shadow", [(_body(DOCUMENTS, "single", part=None), "single")])
    assert served[0][0] == 200
    assert list(shadow.shadow_events) == []


def test_an_incomplete_corpus_is_held_not_reduced() -> None:
    shadow, _ = _serve("shadow", _corpus_bodies()[:1])
    assert list(shadow.shadow_events) == []


def test_unknown_mode_is_refused_by_the_service() -> None:
    with pytest.raises(ValueError, match="corpus reduce mode"):
        ProductCoreService(
            hmac_secret=SECRET,
            core_release_digest=RELEASE,
            corpus_reduce_mode="on",  # type: ignore[arg-type]
        )


def test_part_index_must_be_below_part_count() -> None:
    with pytest.raises(ValueError, match="partIndex"):
        CorpusPart(corpus_id="corpus-x", part_index=2, part_count=2)


@pytest.mark.parametrize(
    ("value", "expected"), [(None, "off"), ("off", "off"), ("shadow", "shadow")]
)
def test_environment_mode(
    monkeypatch: pytest.MonkeyPatch, value: str | None, expected: str
) -> None:
    monkeypatch.setenv("TAVONEL_PRODUCT_CORE_HMAC", SECRET.decode())
    monkeypatch.setenv("TAVONEL_CORE_RELEASE_DIGEST", RELEASE)
    if value is None:
        monkeypatch.delenv("TAVONEL_CORPUS_REDUCE_MODE", raising=False)
    else:
        monkeypatch.setenv("TAVONEL_CORPUS_REDUCE_MODE", value)
    main = importlib.reload(importlib.import_module("akc_product_core.__main__"))
    assert main.app.state.product_core_service.corpus_reduce_mode == expected


@pytest.mark.parametrize("value", ["on", "true", "SHADOW"])
def test_environment_mode_on_or_unknown_fails_the_process_by_name(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("TAVONEL_PRODUCT_CORE_HMAC", SECRET.decode())
    monkeypatch.setenv("TAVONEL_CORE_RELEASE_DIGEST", RELEASE)
    monkeypatch.setenv("TAVONEL_CORPUS_REDUCE_MODE", value)
    with pytest.raises(RuntimeError, match="TAVONEL_CORPUS_REDUCE_MODE"):
        importlib.reload(importlib.import_module("akc_product_core.__main__"))
