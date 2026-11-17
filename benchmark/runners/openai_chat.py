"""vLLM OpenAI-compatible chat endpoint, one page image per request (no vendor code)."""

from __future__ import annotations

import base64
import os
from collections.abc import Callable
from typing import Any

from .base import RunnerConfig
from .vlm import ResponseRefused, exchange, require_revision

# ponytail: one generic prompt for every model; per-model card prompts are unverified (A0).
PROMPT = "Transcribe this page to Markdown. Keep reading order. Do not add commentary."
GENERATION = {"temperature": 0.0, "max_tokens": 8192}


def _extract(model: str) -> Callable[[dict[str, Any]], tuple[str, dict[str, Any]]]:
    def extract(response: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        if response.get("model") != model:
            raise ResponseRefused("served model differs from the pinned model id")
        choice = response["choices"][0]
        if choice.get("finish_reason") != "stop":
            raise ResponseRefused(f"finish_reason {choice.get('finish_reason')!r} is not stop")
        content = choice["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            raise ResponseRefused("empty completion")
        usage = response.get("usage")
        return content, usage if isinstance(usage, dict) else {}

    return extract


def run_chat(
    provider: str,
    model: str,
    payload: dict[str, Any],
    *,
    endpoint: str | None,
    revision: str,
    allow_network: bool,
) -> dict[str, Any]:
    require_revision(revision)
    config = RunnerConfig(provider, revision, endpoint, allow_network)

    def build(mime: str, image: bytes) -> tuple[dict[str, Any], dict[str, str]]:
        url = f"data:{mime};base64,{base64.b64encode(image).decode('ascii')}"
        request = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": url}},
                        {"type": "text", "text": PROMPT},
                    ],
                }
            ],
            **GENERATION,
        }
        headers: dict[str, str] = {}
        token = os.getenv("AKC_BENCHMARK_PROVIDER_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return request, headers

    receipt_base = {
        "provider": provider,
        "model": model,
        "prompt": PROMPT,
        "generation": GENERATION,
        "input_mode": "page_image_data_url",
    }
    return exchange(
        config, payload, build=build, extract=_extract(model), receipt_base=receipt_base
    )
