"""Mistral OCR on Mistral's own API (``POST /v1/ocr``), one page image per request, synchronous.

The model id is a required parameter and must be one of the GA ids listed here exactly; the
retired ``mistral-ocr-4-0``, every alias (``mistral-ocr-4``, ``mistral-ocr-latest``) and every
other spelling are refused before any call. The page goes as a PNG data URL from
``vlm.page_image``: the same renderer, scale and pixel cap every local candidate gets. The
key (``MISTRAL_API_KEY``) travels as ``Authorization: Bearer`` in the header only; ``run``
opens with the shared door and everything after it runs inside the exit guard. The response
must name the pinned id (``model``), hold exactly one page and report ``pages_processed`` 1;
a 429 is ``RunnerUnavailable`` before anything is stored, so the page is retried on the next
run instead of being frozen as a failure row. Mistral Batch is not used.
"""

from __future__ import annotations

import base64
from collections.abc import Callable
from typing import Any

from .base import RunnerConfig, RunnerUnavailable, guarded
from .vlm import ResponseRefused, exchange, render_settings

PROVIDER = "mistral_ocr_4"
CREDENTIAL = "MISTRAL_API_KEY"
# Exact GA ids (docs.mistral.ai/getting-started/models snapshot 6155ede1..., intake register).
# A new GA id is added here by a reviewed change, never matched by a pattern; mistral-ocr-4-0
# was retired by Mistral on 2026-09-30 and is therefore absent.
GA_MODEL_IDS = frozenset({"mistral-ocr-4-1"})
OPTIONS = {"include_image_base64": False}  # the page text only; extracted images are not wanted


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


def _extract(model: str) -> Callable[[dict[str, Any]], tuple[str, Any, bool]]:
    def extract(response: dict[str, Any]) -> tuple[str, Any, bool]:
        if response.get("model") != model:
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
) -> dict[str, Any]:
    def body(key: str | None) -> dict[str, Any]:  # after the door, inside the exit guard
        if not key:
            raise RunnerUnavailable("MISTRAL_API_KEY is not set")
        pinned = config(revision=revision, model=model)
        run_config = RunnerConfig(PROVIDER, pinned["model"], endpoint, allow_network)

        def build(mime: str, image: bytes) -> tuple[dict[str, Any], dict[str, str]]:
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
            extract=_extract(pinned["model"]),
            receipt_base=pinned,
            unavailable_statuses=frozenset({429}),
        )

    return guarded(CREDENTIAL, endpoint, PROVIDER, case, body, model_revision=model)
