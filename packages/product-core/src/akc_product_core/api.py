"""Minimal deployable FastAPI surface for Foundation-to-Core compilation."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import cast

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from .auth import ProductCoreAuthenticationError, verify_product_core_request
from .compiler import ProductCoreCompiler
from .contracts import ProductCoreCompileRequest
from .journal import JournalConflict, JournalCorrupt, SQLiteCompileJournal, compile_work_digest

MAX_REQUEST_BYTES = 32 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class _CachedResponse:
    work_sha256: str
    payload: dict[str, object]


class ProductCoreService:
    """Fail-closed compile service with optional durable single-host replay."""

    def __init__(
        self,
        *,
        hmac_secret: bytes,
        core_release_digest: str,
        allow_customer_data: bool = False,
        journal_path: str | Path | None = None,
    ) -> None:
        if len(hmac_secret) < 32:
            raise ValueError("Product-Core HMAC secret must contain at least 32 bytes")
        self.hmac_secret = hmac_secret
        self.compiler = ProductCoreCompiler(core_release_digest=core_release_digest)
        self.allow_customer_data = allow_customer_data
        self._cache: dict[tuple[str, str, str], _CachedResponse] = {}
        self._lock = Lock()
        self.journal = SQLiteCompileJournal(journal_path) if journal_path is not None else None

    def health(self) -> dict[str, object]:
        return {
            "status": "ok",
            "runtime": "tavonel-python-core-v2",
            "coreReleaseDigest": self.compiler.core_release_digest,
            "matchingPolicy": "legacy",
            "candidatePromotion": False,
            "customerDataEnabled": self.allow_customer_data,
        }

    def compile(self, *, body: bytes, headers: dict[str, str]) -> tuple[int, dict[str, object]]:
        if len(body) > MAX_REQUEST_BYTES:
            return 413, {"code": "CORE_REQUEST_TOO_LARGE"}
        try:
            transport = verify_product_core_request(
                body=body,
                headers=headers,
                secret=self.hmac_secret,
                now=datetime.now(tz=UTC),
            )
        except ProductCoreAuthenticationError as exc:
            return 401, {"code": exc.code}
        try:
            compile_request = ProductCoreCompileRequest.model_validate_json(body)
        except ValidationError as exc:
            return 422, {
                "code": "CORE_REQUEST_INVALID",
                "errors": exc.errors(include_input=False, include_url=False),
            }
        if compile_request.request_id != transport.request_id:
            return 401, {"code": "CORE_REQUEST_ID_MISMATCH"}
        if (
            compile_request.route.privacy_policy == "approved_customer_data"
            and not self.allow_customer_data
        ):
            return 403, {"code": "CORE_CUSTOMER_DATA_DISABLED"}

        # Request ID, timestamp and deadline describe an attempt, not the immutable work.
        # Replays still pass HMAC and privacy checks, then receive an attempt-bound receipt.
        work_sha256 = compile_work_digest(compile_request)
        cache_key = (
            compile_request.tenant_id,
            compile_request.workspace_id,
            compile_request.idempotency_key,
        )
        if self.journal is not None:
            try:
                payload = self.journal.compile(
                    compile_request,
                    compiler=self.compiler,
                    work_digest=work_sha256,
                    input_sha256=transport.input_sha256,
                )
            except JournalConflict:
                return 409, {"code": "CORE_IDEMPOTENCY_CONFLICT"}
            except (JournalCorrupt, sqlite3.Error):
                return 503, {"code": "CORE_JOURNAL_UNAVAILABLE"}
            except ValueError as exc:
                return 422, {"code": "CORE_COMPILE_REJECTED", "reason": str(exc)}
            payload["receipt"] = {
                **cast(dict[str, object], payload["receipt"]),
                "requestId": compile_request.request_id,
                "inputSha256": transport.input_sha256,
            }
            return 200, payload
        with self._lock:
            cached = self._cache.get(cache_key)
            if cached is not None:
                if cached.work_sha256 != work_sha256:
                    return 409, {"code": "CORE_IDEMPOTENCY_CONFLICT"}
                payload = dict(cached.payload)
                payload["receipt"] = {
                    **cast(dict[str, object], cached.payload["receipt"]),
                    "requestId": compile_request.request_id,
                    "inputSha256": transport.input_sha256,
                }
                return 200, payload
            try:
                response = self.compiler.compile(
                    compile_request,
                    input_sha256=transport.input_sha256,
                )
            except ValueError as exc:
                return 422, {"code": "CORE_COMPILE_REJECTED", "reason": str(exc)}
            payload = response.model_dump(mode="json", by_alias=True, exclude_none=True)
            self._cache[cache_key] = _CachedResponse(
                work_sha256=work_sha256,
                payload=payload,
            )
            return 200, payload


def create_product_core_app(
    *,
    hmac_secret: bytes,
    core_release_digest: str,
    allow_customer_data: bool = False,
    journal_path: str | Path | None = None,
) -> FastAPI:
    service = ProductCoreService(
        hmac_secret=hmac_secret,
        core_release_digest=core_release_digest,
        allow_customer_data=allow_customer_data,
        journal_path=journal_path,
    )
    app = FastAPI(title="TAVONEL Product Core", version="2.0.0")

    @app.get("/health")
    async def health() -> dict[str, object]:
        return service.health()

    @app.post("/v2/compile")
    async def compile_candidate(request: Request) -> JSONResponse:
        body = await request.body()
        status, payload = service.compile(body=body, headers=dict(request.headers))
        return JSONResponse(
            status_code=status,
            content=payload,
            headers={"Cache-Control": "no-store"},
        )

    app.state.product_core_service = service
    return app


__all__ = ["ProductCoreService", "create_product_core_app"]
