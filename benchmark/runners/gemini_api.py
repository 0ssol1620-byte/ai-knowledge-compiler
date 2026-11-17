"""Gemini API runner. The model id is required and an alias is refused; no default exists."""

from __future__ import annotations

import base64
import os
import re
from collections.abc import Callable
from typing import Any

from .base import RunnerConfig, RunnerUnavailable
from .vlm import ResponseRefused, exchange

PROVIDER = "gemini_api"
PROMPT = "Transcribe this page to Markdown. Keep reading order. Do not add commentary."
GENERATION = {"temperature": 0.0, "maxOutputTokens": 8192}
_PINNED = re.compile(r"^gemini-\d+(\.\d+)*(-[a-z0-9]+)+$")
_ENDPOINT_MODEL = re.compile(r"/models/([^/:]+):generateContent$")


def check_model(model: str | None, endpoint: str | None) -> str:
    """Return the pinned model id; it may come from the endpoint path but never defaults."""
    path = (endpoint or "").split("?", 1)[0]
    if model is None:
        match = _ENDPOINT_MODEL.search(path)
        model = match.group(1) if match else None
    if not model:
        raise RunnerUnavailable("gemini runner requires an explicit model id")
    if "latest" in model or _PINNED.fullmatch(model) is None:
        raise RunnerUnavailable(f"gemini model id {model!r} is an alias or not a pinned id")
    if not path.endswith(f"/models/{model}:generateContent"):
        raise RunnerUnavailable("gemini endpoint does not name the requested model id")
    return model


def _extract(model: str) -> Callable[[dict[str, Any]], tuple[str, dict[str, Any]]]:
    def extract(response: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        if response.get("modelVersion") != model:
            raise ResponseRefused("served modelVersion differs from the pinned model id")
        if response.get("promptFeedback", {}).get("blockReason"):
            raise ResponseRefused("prompt blocked")
        candidate = response["candidates"][0]
        if candidate.get("finishReason") != "STOP":
            raise ResponseRefused(f"finishReason {candidate.get('finishReason')!r} is not STOP")
        text = "".join(part.get("text", "") for part in candidate["content"]["parts"])
        if not text.strip():
            raise ResponseRefused("empty completion")
        usage = response.get("usageMetadata")
        return text, usage if isinstance(usage, dict) else {}

    return extract


def run(
    case: dict[str, Any],
    *,
    endpoint: str | None,
    revision: str,
    allow_network: bool = False,
    model: str | None = None,
) -> dict[str, Any]:
    model = check_model(model, endpoint)
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise RunnerUnavailable("GEMINI_API_KEY is not set")
    config = RunnerConfig(PROVIDER, revision, endpoint, allow_network)

    def build(mime: str, image: bytes) -> tuple[dict[str, Any], dict[str, str]]:
        request = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "inline_data": {
                                "mime_type": mime,
                                "data": base64.b64encode(image).decode("ascii"),
                            }
                        },
                        {"text": PROMPT},
                    ],
                }
            ],
            "generationConfig": GENERATION,
        }
        return request, {"x-goog-api-key": key}

    receipt_base = {
        "provider": PROVIDER,
        "model": model,
        "prompt": PROMPT,
        "generation": GENERATION,
        "input_mode": "page_image_inline_data",
    }
    return exchange(config, case, build=build, extract=_extract(model), receipt_base=receipt_base)
