"""A retry of the same work is the same World, receipted to the retry; other work conflicts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from akc_cir.base import canonical_json, sha256_digest
from akc_product_core import ProductCoreCompiler, ProductCoreCompileRequest
from akc_product_core.api import create_product_core_app
from akc_product_core.compiler import _wire_numbers
from akc_product_core.contracts import PreviousWorldSnapshot
from fastapi.testclient import TestClient

from .test_product_core_api import SECRET, _signed
from .test_product_core_bridge import RELEASE, _document, _request

KEY = "idem-semantic-work"


def _attempt(
    request_id: str,
    *,
    text: str = "Revenue is 100 million won.",
    minutes_later: int = 0,
    previous: PreviousWorldSnapshot | None = None,
) -> tuple[ProductCoreCompileRequest, bytes]:
    request = _request(
        (_document("filing-a", text),), request_id=request_id, previous=previous
    ).model_copy(
        update={
            "idempotency_key": KEY,
            "requested_at": datetime(2026, 9, 30, 9, 0, tzinfo=UTC)
            + timedelta(minutes=minutes_later),
        }
    )
    body = canonical_json(request.model_dump(mode="json", by_alias=True, exclude_none=True))
    return request, body.encode()


def _post(client: TestClient, request_id: str, body: bytes) -> tuple[int, dict[str, object]]:
    response = client.post("/v2/compile", content=body, headers=_signed(body, request_id))
    return response.status_code, response.json()


def _site_digest(value: object) -> str:
    """The digest the site computes: its canonical form has no `1.0`, only `1`."""
    return sha256_digest(canonical_json(_wire_numbers(value)))


def _client() -> TestClient:
    return TestClient(create_product_core_app(hmac_secret=SECRET, core_release_digest=RELEASE))


def test_retry_with_new_request_id_and_time_replays_the_world_bound_to_the_retry() -> None:
    client = _client()
    _, first_body = _attempt("attempt-1")
    _, retry_body = _attempt("attempt-2", minutes_later=3)
    assert first_body != retry_body

    first_status, first = _post(client, "attempt-1", first_body)
    retry_status, retry = _post(client, "attempt-2", retry_body)

    assert (first_status, retry_status) == (200, 200)
    assert retry["candidate"] == first["candidate"]
    first_receipt, retry_receipt = first["receipt"], retry["receipt"]
    assert isinstance(first_receipt, dict) and isinstance(retry_receipt, dict)
    assert retry_receipt["requestId"] == "attempt-2"
    assert retry_receipt["inputSha256"] == sha256_digest(retry_body)
    assert first_receipt["inputSha256"] == sha256_digest(first_body)
    assert retry_receipt["outputSha256"] == _site_digest(retry["candidate"])
    assert retry_receipt["outputSha256"] == first_receipt["outputSha256"]
    assert retry_receipt["candidatePromotion"] is False


def test_changed_document_content_under_the_same_key_conflicts() -> None:
    client = _client()
    _, first_body = _attempt("attempt-1")
    _, changed_body = _attempt("attempt-2", text="Revenue is 120 million won.")

    assert _post(client, "attempt-1", first_body)[0] == 200
    status, payload = _post(client, "attempt-2", changed_body)
    assert (status, payload) == (409, {"code": "CORE_IDEMPOTENCY_CONFLICT"})


def test_changed_route_under_the_same_key_conflicts() -> None:
    client = _client()
    _, first_body = _attempt("attempt-1")
    request, _ = _attempt("attempt-2")
    changed = request.model_copy(
        update={"route": request.route.model_copy(update={"quality_requirement": "standard"})}
    )
    changed_body = canonical_json(
        changed.model_dump(mode="json", by_alias=True, exclude_none=True)
    ).encode()

    assert _post(client, "attempt-1", first_body)[0] == 200
    assert _post(client, "attempt-2", changed_body)[0] == 409


def test_changed_operation_or_prior_world_under_the_same_key_conflicts() -> None:
    compiler = ProductCoreCompiler(core_release_digest=RELEASE)
    worlds = []
    for index, text in enumerate(("Revenue is 100 million won.", "Revenue is 90 million won.")):
        seed, _ = _attempt(f"seed-{index}", text=text)
        built = compiler.compile(seed, input_sha256="sha256:" + "c" * 64).candidate
        worlds.append(
            PreviousWorldSnapshot(
                world_state_id=built.world_state_id,
                manifest_digest=built.manifest_digest,
                units=built.units,
                artifact_hashes=built.artifact_hashes,
            )
        )
    client = _client()
    _, initial_body = _attempt("attempt-1")
    _, from_first_body = _attempt("attempt-2", previous=worlds[0])
    _, from_second_body = _attempt("attempt-3", previous=worlds[1])

    assert _post(client, "attempt-1", initial_body)[0] == 200
    # Initial compile -> incremental compile: a different operation under the same key.
    assert _post(client, "attempt-2", from_first_body)[0] == 409

    other = _client()
    assert _post(other, "attempt-2", from_first_body)[0] == 200
    # Same operation, different prior World.
    assert _post(other, "attempt-3", from_second_body)[0] == 409


def test_receipt_digest_matches_the_sites_form_when_scores_and_confidence_are_integral() -> None:
    """Official authority scores 1.0 and an OCR confidence of 1.0 must not break the receipt."""
    request, _ = _attempt("attempt-1")
    document = request.documents[0]
    region = document.regions[0].model_copy(update={"confidence": 1.0, "authority": "official"})
    request = request.model_copy(
        update={"documents": (document.model_copy(update={"regions": (region,)}),)}
    )
    body = canonical_json(request.model_dump(mode="json", by_alias=True, exclude_none=True))
    status, payload = _post(_client(), "attempt-1", body.encode())

    assert status == 200
    python_form = sha256_digest(canonical_json(payload["candidate"]))
    receipt = payload["receipt"]
    assert isinstance(receipt, dict)
    assert '"authorityScore":1.0' in canonical_json(payload["candidate"])
    assert receipt["outputSha256"] == _site_digest(payload["candidate"])
    assert receipt["outputSha256"] != python_form
