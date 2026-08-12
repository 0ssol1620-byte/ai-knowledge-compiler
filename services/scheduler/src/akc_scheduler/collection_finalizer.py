"""HMAC-authenticated client for the collection semantic/package finalizer."""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from typing import Protocol

import httpx
from akc_api.collection_schemas import CollectionFinalizerRequest
from akc_api.models import OutboxEvent


def canonical_finalizer_body(payload: CollectionFinalizerRequest) -> bytes:
    return (
        json.dumps(
            payload.model_dump(mode="json"),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


class CollectionFinalizer(Protocol):
    async def finalize(self, event: OutboxEvent) -> None: ...


class HttpCollectionFinalizer:
    """Submit one scheduler-leased event without granting scheduler user authority."""

    def __init__(
        self,
        *,
        endpoint_url: str,
        hmac_secret: bytes,
        timeout_seconds: float,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if len(hmac_secret) < 32:
            raise ValueError("collection finalizer HMAC secret must contain at least 32 bytes")
        self._endpoint_url = endpoint_url
        self._hmac_secret = hmac_secret
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=False,
            trust_env=False,
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    @staticmethod
    def _payload(event: OutboxEvent) -> CollectionFinalizerRequest:
        try:
            payload = CollectionFinalizerRequest(
                event_id=event.id,
                tenant_id=uuid.UUID(str(event.payload["tenant_id"])),
                collection_id=uuid.UUID(str(event.payload["collection_id"])),
                processing_job_id=uuid.UUID(str(event.payload["processing_job_id"])),
                architecture_plan_id=uuid.UUID(str(event.payload["architecture_plan_id"])),
                actor_user_id=uuid.UUID(str(event.payload["actor_user_id"])),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("collection_finalizer_payload_invalid") from exc
        if (
            event.event_type != "collection.semantic.compile.requested.v1"
            or event.aggregate_type != "collection_processing"
            or event.aggregate_id != payload.processing_job_id
            or event.tenant_id != payload.tenant_id
        ):
            raise ValueError("collection_finalizer_event_scope_mismatch")
        return payload

    async def finalize(self, event: OutboxEvent) -> None:
        payload = self._payload(event)
        body = canonical_finalizer_body(payload)
        signature = (
            "sha256="
            + hmac.new(
                self._hmac_secret,
                body,
                hashlib.sha256,
            ).hexdigest()
        )
        try:
            response = await self._client.post(
                self._endpoint_url,
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-AKC-Collection-Finalizer-Signature": signature,
                },
            )
        except httpx.HTTPError as exc:
            raise RuntimeError("collection_finalizer_transport_failed") from exc
        if not 200 <= response.status_code < 300:
            raise RuntimeError(f"collection_finalizer_http_{response.status_code}")


__all__ = [
    "CollectionFinalizer",
    "HttpCollectionFinalizer",
    "canonical_finalizer_body",
]
