"""Shared exchange for page-image runners (vLLM chat endpoints, Gemini).

The raw response bytes are captured and hashed before anything parses them. A refused or
malformed response is returned as a *failure result*: a dict that carries the raw bytes
and deliberately violates the parser-output schema, so the screen runner stores it
(immutable raw output) and records ``contract_failed`` instead of dropping the page. No retry.
Only "nothing came back" (no network authority, transport error) raises ``RunnerUnavailable``.
A page that cannot become an image (over the pixel cap, outside the document, unreadable
PDF, a page pdfium cannot load or render, unsupported type) raises ``PageRefused``: a
page-level result with its own reason, decided before any call.

Every result returned here is plain JSON (strings, finite numbers, a flat usage map), so the
caller can always serialise and store it. Provider-controlled structures are never copied
into a result, only their raw bytes; refusal reasons are fixed tokens, never provider text.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import math
import re
import time
from collections.abc import Callable
from typing import Any

from .base import (
    RunnerConfig,
    RunnerUnavailable,
    post_bytes,
    require_clean_endpoint,
    seal,
)

_REVISION = re.compile(r"^[0-9a-f]{40,64}$")
RENDER_SCALE = 2.0  # 144 dpi; the image digest is recorded in every receipt
MAX_RENDER_PIXELS = 2880 * 2880  # same cap as the OvisOCR2 stage-2 runner; a PDF is hostile input
GENERIC_PROMPT = "Transcribe this page to Markdown. Keep reading order. Do not add commentary."
REFUSAL_REASONS = frozenset(
    {
        "malformed_response",
        "response_not_object",
        "empty_completion",
        "served_model_differs",
        "finish_reason_not_stop",
        "prompt_blocked",
        "output_token_cutoff",  # finishReason MAX_TOKENS: the API's own cutoff was reached
        "output_tokens_over_bound",  # candidates + thoughts above maxOutputTokens
    }
)


class ResponseRefused(ValueError):
    """The provider answered, but not with a usable transcription (reason: a fixed token)."""

    def __init__(self, reason: str) -> None:
        if reason not in REFUSAL_REASONS:
            raise ValueError("unknown refusal reason")
        super().__init__(reason)


class PageRefused(ValueError):
    """The page cannot be sent as an image; ``reason`` is a fixed token, never document text."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def require_revision(revision: str) -> None:
    if not isinstance(revision, str) or _REVISION.fullmatch(revision) is None:
        raise RunnerUnavailable("runner requires an exact 40-64 hex model revision")


def config_sha256(document: dict[str, Any]) -> str:
    """Digest of a runner's pinned config: what ``screen.Candidate.config_sha256`` carries."""
    body = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def render_settings() -> dict[str, Any]:
    """How a PDF page becomes the image a model sees; part of every page-image config."""
    return {
        "renderer": "pypdfium2",
        "render_scale": RENDER_SCALE,
        "max_render_pixels": MAX_RENDER_PIXELS,
    }


def render_pdf_page(data: bytes, page_index: int, scale: float) -> tuple[bytes, dict[str, Any]]:
    """Render one page to PNG; returns the bytes and the render receipt. Closes what it opens."""
    try:
        import pypdfium2  # type: ignore[import-untyped]  # lazy: only PDF pages need it
        import pypdfium2.version as pdfium_version  # type: ignore[import-untyped]
    except ImportError as exc:
        raise RunnerUnavailable("pypdfium2 is required to render PDF pages") from exc
    try:
        pdf = pypdfium2.PdfDocument(data)
    except pypdfium2.PdfiumError as exc:
        raise PageRefused("page_pdf_unreadable") from exc
    try:
        if not 0 <= page_index < len(pdf):
            raise PageRefused("page_index_out_of_range")
        try:
            page = pdf[page_index]
        except pypdfium2.PdfiumError as exc:  # inside /Count, but the page object is broken
            raise PageRefused("page_unrenderable") from exc
        try:
            width, height = page.get_size()
            if not (math.isfinite(width) and math.isfinite(height) and width > 0 and height > 0):
                raise PageRefused("page_size_invalid")
            if width * height * scale * scale > MAX_RENDER_PIXELS:
                raise PageRefused("page_over_pixel_cap")
            try:
                bitmap = page.render(scale=scale)
            except pypdfium2.PdfiumError as exc:
                raise PageRefused("page_unrenderable") from exc
            try:
                image = bitmap.to_pil()
                try:
                    pixels = (int(image.size[0]), int(image.size[1]))
                    if pixels[0] * pixels[1] > MAX_RENDER_PIXELS:
                        raise PageRefused("page_over_pixel_cap")
                    buffer = io.BytesIO()
                    image.save(buffer, format="PNG")
                finally:
                    image.close()
            finally:
                bitmap.close()
        finally:
            page.close()
    finally:
        pdf.close()
    return buffer.getvalue(), {
        **render_settings(),
        "render_scale": scale,
        "renderer_version": str(pdfium_version.PYPDFIUM_INFO),
        "pdfium_version": str(pdfium_version.PDFIUM_INFO),
        "rendered_pixels": [pixels[0], pixels[1]],
    }


def page_image(payload: dict[str, Any]) -> tuple[str, bytes, dict[str, Any] | None]:
    """(mime, image bytes, render receipt, or None when the source already is an image)."""
    source = payload.get("source")
    if not isinstance(source, dict):
        raise RunnerUnavailable("page-image runner needs an approved source, not a synthetic case")
    data = base64.b64decode(source["bytes_base64"])
    content_type = source.get("content_type")
    if isinstance(content_type, str) and content_type.startswith("image/"):
        return content_type, data, None
    if content_type == "application/pdf":
        index = payload.get("page_index")
        if not isinstance(index, int) or isinstance(index, bool):
            raise RunnerUnavailable("PDF source needs an integer page_index")
        png, render = render_pdf_page(data, index, RENDER_SCALE)
        return "image/png", png, render
    raise PageRefused("page_content_type_unsupported")


def failure(
    config: RunnerConfig, payload: dict[str, Any], reason: str, receipt: dict[str, Any]
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "benchmark_case_id": payload["benchmark_case_id"],
        "provider": config.provider,
        "model_revision": config.model_revision,
        "failure": {"reason": reason},
        "receipt": {**receipt, "revision_attested": False},
    }


def _flat_usage(usage: Any) -> dict[str, int | float]:
    """Token counts only: finite numbers under short string keys. Anything else stays in the
    raw bytes; copying it would let a provider make the result unserialisable."""
    if not isinstance(usage, dict):
        return {}
    return {
        key: value
        for key, value in usage.items()
        if isinstance(key, str)
        and len(key) <= 64
        and isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(value)
        and abs(value) < 2**53
    }


def exchange(
    config: RunnerConfig,
    payload: dict[str, Any],
    *,
    build: Callable[[str, bytes], tuple[dict[str, Any], dict[str, str]]],
    extract: Callable[[dict[str, Any]], tuple[str, Any, bool]],
    receipt_base: dict[str, Any],
    unavailable_statuses: frozenset[int] = frozenset(),
) -> dict[str, Any]:
    """``build(mime, image)`` -> (request JSON, headers);
    ``extract(response)`` -> (text, usage, whether the response attests the pinned revision).
    A status in ``unavailable_statuses`` (e.g. a rate limit) is ``RunnerUnavailable`` before
    anything is stored, so the page is retried rather than frozen as a failure row.
    The exchange runs inside ``seal``: a result or error that would carry a credential is
    replaced before it leaves the runner."""
    if not config.model_revision:
        raise RunnerUnavailable("runner requires a pinned model revision")
    require_clean_endpoint(config.endpoint)
    return seal(
        config,
        payload,
        lambda: _exchange(
            config,
            payload,
            build=build,
            extract=extract,
            receipt_base=receipt_base,
            unavailable_statuses=unavailable_statuses,
        ),
    )


def _exchange(
    config: RunnerConfig,
    payload: dict[str, Any],
    *,
    build: Callable[[str, bytes], tuple[dict[str, Any], dict[str, str]]],
    extract: Callable[[dict[str, Any]], tuple[str, Any, bool]],
    receipt_base: dict[str, Any],
    unavailable_statuses: frozenset[int],
) -> dict[str, Any]:
    mime, image, render = page_image(payload)
    request, headers = build(mime, image)
    body = json.dumps(request, ensure_ascii=False, sort_keys=True).encode("utf-8")
    receipt = {
        **receipt_base,
        "config_sha256": config_sha256(receipt_base),
        "model_revision": config.model_revision,
        "endpoint": config.endpoint,
        "image_mime": mime,
        "image_sha256": hashlib.sha256(image).hexdigest(),
        "render": render,
        "request_sha256": hashlib.sha256(body).hexdigest(),
    }
    started = time.perf_counter()
    status, content_type, raw = post_bytes(
        config, body, {"Content-Type": "application/json", **headers}
    )
    latency_ms = (time.perf_counter() - started) * 1000.0
    if status in unavailable_statuses:
        raise RunnerUnavailable("benchmark provider is unavailable")
    return finish(config, payload, receipt, status, content_type, raw, latency_ms, extract)


def finish(
    config: RunnerConfig,
    payload: dict[str, Any],
    receipt: dict[str, Any],
    status: int,
    content_type: str,
    raw: bytes,
    latency_ms: float,
    extract: Callable[[dict[str, Any]], tuple[str, Any, bool]],
) -> dict[str, Any]:
    """One answer to a result or a failure row: the raw bytes go into the receipt before any
    parsing. Shared by the sync exchange and each entry of a collected batch."""
    receipt = dict(receipt)
    receipt.update(
        http_status=status,
        response_content_type=content_type,
        raw_response_sha256=hashlib.sha256(raw).hexdigest(),
        raw_response_b64=base64.b64encode(raw).decode("ascii"),
    )
    if status != 200:
        return failure(config, payload, f"http_{status}", receipt)
    try:
        decoded = json.loads(raw)
        if not isinstance(decoded, dict):
            raise ResponseRefused("response_not_object")
        text, usage, attested = extract(decoded)
        if not isinstance(text, str) or not text.strip():
            raise ResponseRefused("empty_completion")
        text.encode("utf-8")  # a lone surrogate would make the result unstorable
    except Exception as exc:  # raw is already in the receipt: any parse failure is a failure row
        reason = str(exc) if isinstance(exc, ResponseRefused) else "malformed_response"
        return failure(config, payload, reason, receipt)
    receipt["usage"] = _flat_usage(usage)
    receipt["revision_attested"] = attested is True
    return {
        "schema_version": "1.0",
        "benchmark_case_id": payload["benchmark_case_id"],
        "provider": config.provider,
        "model_revision": config.model_revision,
        "text": text,
        "reading_order": [],
        "blocks": [],
        "generated_claims": [],
        "metrics": {"latency_ms": latency_ms, "receipt": receipt},
        "warnings": [],
    }
