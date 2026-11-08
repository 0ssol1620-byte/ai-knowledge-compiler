"""Minimal deployable FastAPI surface for Foundation-to-Core compilation."""

from __future__ import annotations

import json
from collections import OrderedDict, deque
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock
from typing import Any, Literal

from akc_cir.base import canonical_json, sha256_digest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from .auth import ProductCoreAuthenticationError, verify_product_core_request
from .compiler import (
    OUTPUT_BUDGET_BYTES,
    CoreOutputTooLargeError,
    ProductCoreCompiler,
    wire_payload,
)
from .contracts import ProductCoreCompileRequest, ProductCoreCompileResponse
from .corpus_reduce import CorpusReduceError, ReducePart, corpus_reduce

MAX_REQUEST_BYTES = 32 * 1024 * 1024
# The idempotency cache holds whole responses in process memory, so it is bounded twice: by
# entries and by bytes, whichever is reached first, evicting the least recently used. An evicted
# key is recompiled on retry (deterministic, same output) and no longer detects a 409 conflict.
# CACHE_MAX_BYTES counts serialised bytes. The resident pydantic objects measured 1.75x that
# (18.4 MB serialised -> 32.1 MB resident, tracemalloc), so the 256 MiB cap is ~450 MB resident.
CACHE_MAX_ENTRIES = 8
CACHE_MAX_BYTES = 256 * 1024 * 1024
# Shadow corpus_reduce (ADR-008) holds finished part payloads until every part of a corpus
# has arrived. Bounded by serialised bytes; the oldest corpus is dropped first, and said so.
SHADOW_MAX_BYTES = 128 * 1024 * 1024
CorpusReduceMode = Literal["off", "shadow"]


@dataclass(frozen=True, slots=True)
class _CachedResponse:
    work_sha256: str
    # A World, or a deterministic CORE_OUTPUT_TOO_LARGE body: the same work is refused the same
    # way, so a retry is answered without recompiling under the lock. Still a refusal.
    outcome: ProductCoreCompileResponse | dict[str, object]
    size_bytes: int


def _work_sha256(request: ProductCoreCompileRequest) -> str:
    """The digest of the work, without the attempt.

    `requestId` and `requestedAt` name one attempt; a caller retrying the same work under the
    same idempotency key sends new ones. Everything else -- documents, route, blueprint, prior
    World -- is the work, and a change to any of it under the same key is a conflict.
    """
    return sha256_digest(
        canonical_json(
            request.model_dump(mode="json", by_alias=True, exclude={"request_id", "requested_at"})
        )
    )


class ProductCoreService:
    """Fail-closed compile service with process-local idempotent replay."""

    def __init__(
        self,
        *,
        hmac_secret: bytes,
        core_release_digest: str,
        allow_customer_data: bool = False,
        output_budget_bytes: int = OUTPUT_BUDGET_BYTES,
        corpus_reduce_mode: CorpusReduceMode = "off",
    ) -> None:
        if corpus_reduce_mode not in ("off", "shadow"):
            raise ValueError(
                f"corpus reduce mode must be off or shadow, got {corpus_reduce_mode!r}"
            )
        if len(hmac_secret) < 32:
            raise ValueError("Product-Core HMAC secret must contain at least 32 bytes")
        self.hmac_secret = hmac_secret
        self.compiler = ProductCoreCompiler(
            core_release_digest=core_release_digest,
            output_budget_bytes=output_budget_bytes,
        )
        self.allow_customer_data = allow_customer_data
        self._cache: OrderedDict[tuple[str, str, str], _CachedResponse] = OrderedDict()
        self._cache_bytes = 0
        self._lock = Lock()
        self.corpus_reduce_mode = corpus_reduce_mode
        self._shadow: OrderedDict[tuple[str, str, str], dict[int, tuple[ReducePart, int]]] = (
            OrderedDict()
        )
        self._shadow_bytes = 0
        self._shadow_lock = Lock()
        # Every shadow event that was logged, newest last; for inspection, not for serving.
        self.shadow_events: deque[dict[str, Any]] = deque(maxlen=32)

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
        status, payload = self._compile(body=body, headers=headers)
        if status == 200 and self.corpus_reduce_mode == "shadow":
            self._shadow_reduce(body, payload)
        return status, payload

    def _compile(self, *, body: bytes, headers: dict[str, str]) -> tuple[int, dict[str, object]]:
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

        cache_key = (
            compile_request.tenant_id,
            compile_request.workspace_id,
            compile_request.idempotency_key,
        )
        with self._lock:
            work_sha256 = _work_sha256(compile_request)
            cached = self._cache.get(cache_key)
            if cached is not None:
                if cached.work_sha256 != work_sha256:
                    return 409, {"code": "CORE_IDEMPOTENCY_CONFLICT"}
                self._cache.move_to_end(cache_key)
                if isinstance(cached.outcome, dict):
                    return 422, cached.outcome
                # The same World, receipted to the attempt that was authenticated now. The
                # candidate and its output digest are the first attempt's, unchanged.
                replay = cached.outcome.model_copy(
                    update={
                        "receipt": cached.outcome.receipt.model_copy(
                            update={
                                "request_id": transport.request_id,
                                "input_sha256": transport.input_sha256,
                            }
                        )
                    }
                )
                return 200, wire_payload(replay)
            try:
                response = self.compiler.compile(
                    compile_request,
                    input_sha256=transport.input_sha256,
                )
            except CoreOutputTooLargeError as exc:
                refusal: dict[str, object] = {"code": "CORE_OUTPUT_TOO_LARGE", **exc.detail}
                # Numbers only: no document text reaches the log.
                print(
                    json.dumps(
                        {
                            "event": "core_output_too_large",
                            "requestId": compile_request.request_id,
                            **exc.detail,
                        },
                        separators=(",", ":"),
                    ),
                    flush=True,
                )
                self._remember(cache_key, work_sha256, refusal, refusal)
                return 422, refusal
            except ValueError as exc:
                return 422, {"code": "CORE_COMPILE_REJECTED", "reason": str(exc)}
            # The bytes the receipt digest was computed over: the site hashes them as sent.
            payload = wire_payload(response)
            self._remember(cache_key, work_sha256, response, payload)
            return 200, payload

    def _shadow_event(self, event: dict[str, Any]) -> None:
        # Digests, counts and codes only: no document text reaches the log.
        self.shadow_events.append(event)
        print(json.dumps(event, separators=(",", ":")), flush=True)

    def _shadow_reduce(self, body: bytes, payload: dict[str, object]) -> None:
        """Shadow only: reads the served payload, never changes it, never fails the compile.

        A part is held until every part of its corpus has been served by this process, then the
        corpus is reduced and the receipt logged. Nothing is returned to the caller.
        """
        # ponytail: process-local. On a multi-instance deployment the parts of one corpus can land
        # on different instances and that corpus is never reduced here; a durable shadow needs
        # Foundation to send the stored part Worlds to one reduce call (ADR-008, rollout step).
        request = ProductCoreCompileRequest.model_validate_json(body)
        spec = request.corpus_part
        if spec is None:
            return
        key = (request.tenant_id, request.workspace_id, spec.corpus_id)
        try:
            size = len(canonical_json(payload).encode("utf-8"))
            part = ReducePart.from_compile(
                corpus_id=spec.corpus_id,
                part_index=spec.part_index,
                part_count=spec.part_count,
                request=request,
                input_sha256=sha256_digest(body),
                response=payload,
            )
            ready: list[ReducePart] = []
            with self._shadow_lock:
                held = self._shadow.setdefault(key, {})
                if spec.part_index in held:
                    self._shadow_bytes -= held[spec.part_index][1]
                held[spec.part_index] = (part, size)
                self._shadow_bytes += size
                self._shadow.move_to_end(key)
                while self._shadow and self._shadow_bytes > SHADOW_MAX_BYTES:
                    dropped_key, dropped = self._shadow.popitem(last=False)
                    self._shadow_bytes -= sum(item[1] for item in dropped.values())
                    self._shadow_event(
                        {
                            "event": "corpus_reduce_shadow_evicted",
                            "corpusId": dropped_key[2],
                            "partsHeld": len(dropped),
                        }
                    )
                if key in self._shadow and len(self._shadow[key]) >= spec.part_count:
                    finished = self._shadow.pop(key)
                    self._shadow_bytes -= sum(item[1] for item in finished.values())
                    ready = [item[0] for item in finished.values()]
            if ready:
                _, receipt = corpus_reduce(ready)
                self._shadow_event({"event": "corpus_reduce_shadow", **receipt})
        except CorpusReduceError as exc:
            self._shadow_event(
                {
                    "event": "corpus_reduce_shadow_refused",
                    "corpusId": spec.corpus_id,
                    "code": exc.code,
                    "detail": exc.detail,
                }
            )
        except Exception as exc:  # the shadow must never fail the served compile
            self._shadow_event(
                {
                    "event": "corpus_reduce_shadow_error",
                    "corpusId": spec.corpus_id,
                    "error": type(exc).__name__,
                }
            )

    def _remember(
        self,
        key: tuple[str, str, str],
        work_sha256: str,
        outcome: ProductCoreCompileResponse | dict[str, object],
        payload: dict[str, object],
    ) -> None:
        # ponytail: sizes the entry by one extra serialisation (<= the 32 MiB output budget);
        # carry the byte count out of the compiler if that cost ever shows up.
        size = len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode())
        self._cache[key] = _CachedResponse(work_sha256, outcome, size)
        self._cache_bytes += size
        while self._cache and (
            len(self._cache) > CACHE_MAX_ENTRIES or self._cache_bytes > CACHE_MAX_BYTES
        ):
            _, evicted = self._cache.popitem(last=False)
            self._cache_bytes -= evicted.size_bytes


def create_product_core_app(
    *,
    hmac_secret: bytes,
    core_release_digest: str,
    allow_customer_data: bool = False,
    output_budget_bytes: int = OUTPUT_BUDGET_BYTES,
    corpus_reduce_mode: CorpusReduceMode = "off",
) -> FastAPI:
    service = ProductCoreService(
        hmac_secret=hmac_secret,
        core_release_digest=core_release_digest,
        allow_customer_data=allow_customer_data,
        output_budget_bytes=output_budget_bytes,
        corpus_reduce_mode=corpus_reduce_mode,
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
