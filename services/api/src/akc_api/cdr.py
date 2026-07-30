"""Content Disarm and Reconstruction provider adapters."""

from __future__ import annotations

import httpx
from akc_security import (
    CdrRequest,
    CdrResult,
    CdrStatus,
    UnavailableCdrAdapter,
    validate_cdr_result,
)

from akc_api.settings import Settings


class HttpCdrAdapter:
    """Minimal, provider-neutral binary CDR protocol over HTTPS."""

    def __init__(self, settings: Settings) -> None:
        self._endpoint = (settings.cdr_endpoint_url or "").rstrip("/")
        self._api_key = settings.cdr_api_key
        self._max_output_bytes = settings.cdr_max_output_bytes
        self._client = httpx.AsyncClient(
            timeout=settings.cdr_timeout_seconds,
            follow_redirects=False,
        )

    async def ready(self) -> bool:
        try:
            response = await self._client.get(
                f"{self._endpoint}/health",
                headers=self._headers(),
            )
        except httpx.HTTPError:
            return False
        return response.status_code == 200

    async def sanitize(self, request: CdrRequest) -> CdrResult:
        try:
            response = await self._client.post(
                f"{self._endpoint}/v1/sanitize",
                headers={
                    **self._headers(),
                    "Content-Type": request.mime_type,
                    "X-AKC-Filename": request.filename,
                    "X-AKC-Source-SHA256": request.source_sha256,
                },
                content=request.payload,
            )
        except httpx.HTTPError:
            return CdrResult(
                status=CdrStatus.UNAVAILABLE,
                provider="http",
                revision="unavailable",
                reason_code="CDR_UNAVAILABLE",
            )
        if response.status_code == 415:
            return CdrResult(
                status=CdrStatus.UNSUPPORTED,
                provider="http",
                revision=response.headers.get("X-AKC-CDR-Revision", "unknown"),
                reason_code="CDR_UNSUPPORTED",
            )
        if response.status_code == 422:
            return CdrResult(
                status=CdrStatus.REJECTED,
                provider="http",
                revision=response.headers.get("X-AKC-CDR-Revision", "unknown"),
                reason_code="CDR_REJECTED",
            )
        if response.status_code != 200:
            return CdrResult(
                status=CdrStatus.UNAVAILABLE,
                provider="http",
                revision="unavailable",
                reason_code="CDR_UNAVAILABLE",
            )
        result = CdrResult(
            status=CdrStatus.SANITIZED,
            provider=response.headers.get("X-AKC-CDR-Provider", "http"),
            revision=response.headers.get("X-AKC-CDR-Revision", ""),
            sanitized_payload=response.content,
            sanitized_sha256=response.headers.get("X-AKC-SHA256"),
        )
        return validate_cdr_result(
            result,
            source_sha256=request.source_sha256,
            max_output_bytes=self._max_output_bytes,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    def _headers(self) -> dict[str, str]:
        if not self._api_key:
            return {}
        return {"Authorization": f"Bearer {self._api_key}"}


def build_cdr_adapter(settings: Settings) -> HttpCdrAdapter | UnavailableCdrAdapter:
    if settings.cdr_enabled and settings.cdr_provider == "http":
        return HttpCdrAdapter(settings)
    return UnavailableCdrAdapter()
