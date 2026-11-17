"""Mistral OCR on Mistral's own API (``POST /v1/ocr``), one page image per request, synchronous.

The model id is a required parameter and must be one of the GA ids listed here exactly; the
retired ``mistral-ocr-4-0``, every alias (``mistral-ocr-4``, ``mistral-ocr-latest``) and every
other spelling are refused before any call. The page goes as a PNG data URL from
``vlm.page_image``: the same renderer, scale and pixel cap every local candidate gets. The
key (``MISTRAL_API_KEY``) travels as ``Authorization: Bearer`` in the header only; ``run``
opens with the shared door and everything after it runs inside the exit guard. The response
must name the pinned id (``model``), hold exactly one page and report ``pages_processed`` 1;
a 429 is ``RunnerUnavailable`` before anything is stored, so the page is retried on the next
run instead of being frozen as a failure row. ``served_ids`` (the ids a response may name)
refuses the retired id and every alias as ``model`` does. A caller that planned the page
image passes its sha256; any other image raises ``ImageDiffers`` before the request is sent.
Mistral Batch is not used.
"""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Callable, Collection
from typing import Any

from .base import RunnerConfig, RunnerUnavailable, guarded
from .vlm import ResponseRefused, exchange, render_settings

PROVIDER = "mistral_ocr_4"
CREDENTIAL = "MISTRAL_API_KEY"
# Exact GA ids (docs.mistral.ai/getting-started/models snapshot 6155ede1..., intake register).
# A new GA id is added here by a reviewed change, never matched by a pattern; mistral-ocr-4-0
# was retired by Mistral on 2026-09-30 and is therefore absent.
GA_MODEL_IDS = frozenset({"mistral-ocr-4-1"})
RETIRED_MODEL_IDS = frozenset({"mistral-ocr-4-0"})
ALIAS_MODEL_IDS = frozenset({"mistral-ocr-4", "mistral-ocr-latest"})
OPTIONS = {"include_image_base64": False}  # the page text only; extracted images are not wanted


class ImageDiffers(ValueError):
    """The page image is not the one the caller planned; nothing was sent."""


def accepted_ids(model: str, served_ids: Collection[str] | None) -> frozenset[str]:
    """The closed set of ids a response may name for ``model``: exact strings from the hosted
    spec, never the retired id, an alias or a ``latest`` spelling; by default ``model`` alone."""
    if isinstance(served_ids, str):
        raise RunnerUnavailable("served ids are a collection of exact ids")
    accepted = frozenset(served_ids) if served_ids else frozenset({model})
    refused = RETIRED_MODEL_IDS | ALIAS_MODEL_IDS
    for served in accepted:
        if not isinstance(served, str) or not served:
            raise RunnerUnavailable("a served id is not a plain id")
        if served.casefold() in refused or "latest" in served.casefold():
            raise RunnerUnavailable("a served id is an alias or the retired id")
    return accepted


def config(*, revision: str | None = None, model: str | None = None) -> dict[str, Any]:
    if revision:
        raise RunnerUnavailable("a hosted model is pinned by model id; revision must be empty")
    if not isinstance(model, str) or not model:
        raise RunnerUnavailable("mistral runner requires an explicit model id")
    if model not in GA_MODEL_IDS:
        raise RunnerUnavailable("mistral model id is an alias or not a pinned GA id")
    return {
        "provider": PROVIDER,
        "model": model,
        "protocol": "mistral_ocr_v1",
        "input_mode": "page_image_data_url",
        "options": dict(OPTIONS),
        **render_settings(),
    }


def _extract(
    model: str, served_ids: Collection[str] | None = None
) -> Callable[[dict[str, Any]], tuple[str, Any, bool]]:
    """``served_ids``: the closed set of ids the response may name for ``model`` (exact strings
    from the hosted spec, never a pattern; ``accepted_ids``); by default the pinned id alone."""
    accepted = accepted_ids(model, served_ids)

    def extract(response: dict[str, Any]) -> tuple[str, Any, bool]:
        if response.get("model") not in accepted:
            raise ResponseRefused("served_model_differs")
        pages = response.get("pages")
        usage = response.get("usage_info")
        processed = usage.get("pages_processed") if isinstance(usage, dict) else None
        if not isinstance(pages, list) or len(pages) != 1 or type(processed) is not int:
            raise ResponseRefused("malformed_response")
        if processed != 1 or not isinstance(pages[0], dict):
            raise ResponseRefused("malformed_response")
        text = pages[0].get("markdown")
        if not isinstance(text, str):
            raise ResponseRefused("empty_completion")
        return text, usage, False

    return extract


def run(
    case: dict[str, Any],
    *,
    endpoint: str | None,
    revision: str | None = None,
    allow_network: bool = False,
    model: str | None = None,
    served_ids: Collection[str] | None = None,
    image_sha256: str | None = None,
) -> dict[str, Any]:
    def body(key: str | None) -> dict[str, Any]:  # after the door, inside the exit guard
        if not key:
            raise RunnerUnavailable("MISTRAL_API_KEY is not set")
        pinned = config(revision=revision, model=model)
        run_config = RunnerConfig(PROVIDER, pinned["model"], endpoint, allow_network)

        extract = _extract(pinned["model"], served_ids)  # an alias is refused before any call

        def build(mime: str, image: bytes) -> tuple[dict[str, Any], dict[str, str]]:
            if image_sha256 is not None and hashlib.sha256(image).hexdigest() != image_sha256:
                raise ImageDiffers("the page image differs from the planned image")
            url = f"data:{mime};base64,{base64.b64encode(image).decode('ascii')}"
            request = {
                "model": pinned["model"],
                "document": {"type": "image_url", "image_url": url},
                **pinned["options"],
            }
            return request, {"Authorization": f"Bearer {key}"}

        return exchange(
            run_config,
            case,
            build=build,
            extract=extract,
            receipt_base=pinned,
            unavailable_statuses=frozenset({429}),
        )

    return guarded(CREDENTIAL, endpoint, PROVIDER, case, body, model_revision=model)
