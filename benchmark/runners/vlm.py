"""Shared exchange for page-image runners (vLLM chat endpoints, Gemini).

The raw response bytes are captured and hashed before anything parses them. A refused or
malformed response is returned as a *failure result*: a dict that carries the raw bytes
and deliberately violates the parser-output schema, so the screen runner stores it
(immutable raw output) and records ``contract_failed`` instead of dropping the page. No retry.
Only "nothing came back" (no network authority, transport error) raises ``RunnerUnavailable``.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import time
from collections.abc import Callable
from typing import Any

from .base import RunnerConfig, RunnerUnavailable, post_bytes

_REVISION = re.compile(r"^[0-9a-f]{40,64}$")
RENDER_SCALE = 2.0  # 144 dpi; the image digest is recorded in every receipt
MAX_RENDER_PIXELS = 2880 * 2880  # same cap as the OvisOCR2 stage-2 runner; a PDF is hostile input


class ResponseRefused(ValueError):
    """The provider answered, but not with a usable transcription."""


def require_revision(revision: str) -> None:
    if not isinstance(revision, str) or _REVISION.fullmatch(revision) is None:
        raise RunnerUnavailable("runner requires an exact 40-64 hex model revision")


def render_pdf_page(data: bytes, page_index: int, scale: float) -> bytes:
    try:
        import pypdfium2  # type: ignore[import-untyped]  # lazy: only PDF pages need it
    except ImportError as exc:
        raise RunnerUnavailable("pypdfium2 is required to render PDF pages") from exc
    pdf = pypdfium2.PdfDocument(data)
    if not 0 <= page_index < len(pdf):
        raise RunnerUnavailable("page_index is outside the document")
    page = pdf[page_index]
    width, height = page.get_size()
    if width * height * scale * scale > MAX_RENDER_PIXELS:
        raise RunnerUnavailable("page would render above the pixel cap; refused")
    buffer = io.BytesIO()
    page.render(scale=scale).to_pil().save(buffer, format="PNG")
    return buffer.getvalue()


def page_image(payload: dict[str, Any]) -> tuple[str, bytes]:
    source = payload.get("source")
    if not isinstance(source, dict):
        raise RunnerUnavailable("page-image runner needs an approved source, not a synthetic case")
    data = base64.b64decode(source["bytes_base64"])
    content_type = source.get("content_type")
    if isinstance(content_type, str) and content_type.startswith("image/"):
        return content_type, data
    if content_type == "application/pdf":
        index = payload.get("page_index")
        if not isinstance(index, int) or isinstance(index, bool):
            raise RunnerUnavailable("PDF source needs an integer page_index")
        return "image/png", render_pdf_page(data, index, RENDER_SCALE)
    raise RunnerUnavailable(f"unsupported source content type {content_type!r}")


def _failure(
    config: RunnerConfig, payload: dict[str, Any], reason: str, receipt: dict[str, Any]
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "benchmark_case_id": payload["benchmark_case_id"],
        "provider": config.provider,
        "model_revision": config.model_revision,
        "failure": {"reason": reason},
        "receipt": receipt,
    }


def exchange(
    config: RunnerConfig,
    payload: dict[str, Any],
    *,
    build: Callable[[str, bytes], tuple[dict[str, Any], dict[str, str]]],
    extract: Callable[[dict[str, Any]], tuple[str, dict[str, Any]]],
    receipt_base: dict[str, Any],
) -> dict[str, Any]:
    """``build(mime, image)`` -> (request JSON, headers); ``extract(response)`` -> (text, usage)."""
    if not config.model_revision:
        raise RunnerUnavailable("runner requires a pinned model revision")
    mime, image = page_image(payload)
    request, headers = build(mime, image)
    body = json.dumps(request, ensure_ascii=False, sort_keys=True).encode("utf-8")
    receipt = {
        **receipt_base,
        "model_revision": config.model_revision,
        "endpoint": config.endpoint,
        "image_mime": mime,
        "image_sha256": hashlib.sha256(image).hexdigest(),
        "request_sha256": hashlib.sha256(body).hexdigest(),
    }
    started = time.perf_counter()
    status, content_type, raw = post_bytes(
        config, body, {"Content-Type": "application/json", **headers}
    )
    latency_ms = (time.perf_counter() - started) * 1000.0
    # raw bytes first, before any parsing
    receipt.update(
        http_status=status,
        response_content_type=content_type,
        raw_response_sha256=hashlib.sha256(raw).hexdigest(),
        raw_response_b64=base64.b64encode(raw).decode("ascii"),
    )
    if status != 200:
        return _failure(config, payload, f"http_{status}", receipt)
    try:
        decoded = json.loads(raw)
        if not isinstance(decoded, dict):
            raise ResponseRefused("response is not a JSON object")
        text, usage = extract(decoded)
    except Exception as exc:  # raw is already in the receipt: any parse failure is a failure row
        reason = str(exc) if isinstance(exc, ResponseRefused) else "malformed_response"
        return _failure(config, payload, reason, receipt)
    receipt["usage"] = usage
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
