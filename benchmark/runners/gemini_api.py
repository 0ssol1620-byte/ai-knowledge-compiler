"""Gemini API runner (synchronous ``generateContent``, one page per request) and the Batch
REST helpers the hosted arm submits through (``benchmark.screen.hosted``).

The model id is required and an alias is refused; no default exists. A hosted id names no
weights revision, so the runner takes none and every receipt says ``revision_attested:
false``; the served ``modelVersion`` must still equal the pinned id. The key travels in the
``x-goog-api-key`` header only. ``run`` opens with the shared door (``base.guarded``): the key
is read and the endpoint checked (allow-listed shape, no spelling of a credential) before any
other argument is looked at, and everything after it runs inside the exit guard
(``base.seal``), so no refusal or result can carry the key. Refusal messages are fixed strings.
``thinking_config`` (bounded) and ``media_resolution`` are required and recorded; a
``thinkingLevel`` is one of the REST enum names (the Gemini 4 model pages list levels only).
Parts marked ``thought`` are not transcription; a ``thought`` field that is not a bool is a
malformed response.

One request body for sync and batch: ``request_body`` builds the ``GenerateContentRequest``
the sync call posts and every inline batch request carries, byte for byte. The batch helpers
(create, get, list, delete) each go through the door and the exit guard; their endpoints are
built here from the pinned base and a job name of the documented shape ``batches/<id>``, so a
name a provider returns cannot steer a request elsewhere. Inline requests only: the Files-API
upload path (its upload URL carries a query string) is not used.
"""

from __future__ import annotations

import base64
import json
import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from .base import RunnerConfig, RunnerUnavailable, guarded, request_bytes, require_clean_endpoint
from .vlm import GENERIC_PROMPT, ResponseRefused, exchange, render_settings

PROVIDER = "gemini_api"
PROMPT = GENERIC_PROMPT
GENERATION = {"temperature": 0.0, "maxOutputTokens": 8192}
MAX_THINKING_BUDGET = 32_768
# ThinkingConfig.thinkingLevel, REST reference (THINKING_LEVEL_UNSPECIFIED is not a bound)
THINKING_LEVELS = frozenset({"MINIMAL", "LOW", "MEDIUM", "HIGH", "XHIGH"})
API_BASE = "https://generativelanguage.googleapis.com/v1beta"
BATCH_MAX_RESPONSE_BYTES = 64 * 1024 * 1024
_PINNED = re.compile(r"^gemini-\d+(\.\d+)*(-[a-z0-9]+)+$")
_ENDPOINT_MODEL = re.compile(r"/models/([^/:]+):generateContent$")
_MEDIA_RESOLUTION = re.compile(r"^MEDIA_RESOLUTION_[A-Z_]+$")
# The reference documents the format ``batches/{batch_id}`` but not the id's alphabet.
_JOB_NAME = re.compile(r"^batches/[A-Za-z0-9_-]{1,128}$")


def check_model(model: str | None, endpoint: str | None) -> str:
    """Return the pinned model id; it may come from the endpoint path but never defaults."""
    require_clean_endpoint(endpoint)
    path = endpoint or ""
    if model is None:
        match = _ENDPOINT_MODEL.search(path)
        model = match.group(1) if match else None
    if not model:
        raise RunnerUnavailable("gemini runner requires an explicit model id")
    if "latest" in model or _PINNED.fullmatch(model) is None:
        raise RunnerUnavailable("gemini model id is an alias or not a pinned id")
    if endpoint is not None and not path.endswith(f"/models/{model}:generateContent"):
        raise RunnerUnavailable("gemini endpoint does not name the requested model id")
    return model


def _thinking(value: Any) -> dict[str, Any]:
    """Exactly one bound: thinkingBudget 0..MAX (never -1, dynamic) or a thinkingLevel."""
    if not isinstance(value, dict):
        raise RunnerUnavailable("gemini runner requires thinking_config")
    allowed = {"thinkingBudget", "thinkingLevel", "includeThoughts"}
    if not value or set(value) - allowed:
        raise RunnerUnavailable("thinking_config has unknown or no keys")
    bounds = [key for key in ("thinkingBudget", "thinkingLevel") if key in value]
    if len(bounds) != 1:
        raise RunnerUnavailable("thinking_config needs exactly one of thinkingBudget/thinkingLevel")
    budget = value.get("thinkingBudget")
    if "thinkingBudget" in value and not (
        type(budget) is int and 0 <= budget <= MAX_THINKING_BUDGET
    ):
        raise RunnerUnavailable(f"thinkingBudget must be an int in 0..{MAX_THINKING_BUDGET}")
    level = value.get("thinkingLevel")
    if "thinkingLevel" in value and not (isinstance(level, str) and level in THINKING_LEVELS):
        raise RunnerUnavailable("thinkingLevel must be MINIMAL, LOW, MEDIUM, HIGH or XHIGH")
    if "includeThoughts" in value and type(value["includeThoughts"]) is not bool:
        raise RunnerUnavailable("includeThoughts must be a bool")
    return dict(value)


def config(
    *,
    revision: str | None = None,
    model: str | None = None,
    thinking_config: Any = None,
    media_resolution: Any = None,
    endpoint: str | None = None,
) -> dict[str, Any]:
    if revision:
        raise RunnerUnavailable("a hosted model is pinned by model id; revision must be empty")
    pinned = check_model(model, endpoint)
    thinking = _thinking(thinking_config)
    if not (
        isinstance(media_resolution, str)
        and _MEDIA_RESOLUTION.fullmatch(media_resolution)
        and media_resolution != "MEDIA_RESOLUTION_UNSPECIFIED"
    ):
        raise RunnerUnavailable("gemini runner requires an explicit media_resolution")
    return {
        "provider": PROVIDER,
        "model": pinned,
        "prompt": PROMPT,
        "prompt_source": "generic: hosted model, no vendor document-parsing prompt pinned",
        "generation": {
            **GENERATION,
            "thinkingConfig": thinking,
            "mediaResolution": media_resolution,
        },
        "thought_parts": "excluded_from_transcription",
        "input_mode": "page_image_inline_data",
        **render_settings(),
    }


def request_body(pinned: Mapping[str, Any], mime: str, image: bytes) -> dict[str, Any]:
    """The ``GenerateContentRequest`` for one page: the sync body and each inline batch request."""
    return {
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
                    {"text": pinned["prompt"]},
                ],
            }
        ],
        "generationConfig": pinned["generation"],
    }


def _extract(model: str) -> Callable[[dict[str, Any]], tuple[str, Any, bool]]:
    def extract(response: dict[str, Any]) -> tuple[str, Any, bool]:
        if response.get("modelVersion") != model:
            raise ResponseRefused("served_model_differs")
        feedback = response.get("promptFeedback")
        if feedback is not None and not isinstance(feedback, dict):
            raise ResponseRefused("malformed_response")
        if feedback is not None and feedback.get("blockReason"):
            raise ResponseRefused("prompt_blocked")
        candidate = response["candidates"][0]
        if candidate.get("finishReason") != "STOP":
            raise ResponseRefused("finish_reason_not_stop")
        parts = candidate["content"]["parts"]
        if not isinstance(parts, list):
            raise ResponseRefused("empty_completion")
        texts = []
        for part in parts:
            if type(part.get("thought", False)) is not bool:
                raise ResponseRefused("malformed_response")
            if part.get("thought") is True:
                continue  # reasoning, not the page
            text = part.get("text", "")
            if not isinstance(text, str):
                raise ResponseRefused("empty_completion")
            texts.append(text)
        return "".join(texts), response.get("usageMetadata"), False

    return extract


def run(
    case: dict[str, Any],
    *,
    endpoint: str | None,
    revision: str | None = None,
    allow_network: bool = False,
    model: str | None = None,
    thinking_config: Any = None,
    media_resolution: Any = None,
) -> dict[str, Any]:
    return guarded(
        "GEMINI_API_KEY",
        endpoint,
        PROVIDER,
        case,
        lambda key: _run(
            key,
            case,
            endpoint=endpoint,
            revision=revision,
            allow_network=allow_network,
            model=model,
            thinking_config=thinking_config,
            media_resolution=media_resolution,
        ),
        model_revision=model,
    )


def _run(
    key: str | None,
    case: dict[str, Any],
    *,
    endpoint: str | None,
    revision: str | None,
    allow_network: bool,
    model: str | None,
    thinking_config: Any,
    media_resolution: Any,
) -> dict[str, Any]:
    """Everything after the door; ``guarded`` runs it inside the exit guard."""
    if not key:
        raise RunnerUnavailable("GEMINI_API_KEY is not set")
    pinned = config(
        revision=revision,
        model=model,
        thinking_config=thinking_config,
        media_resolution=media_resolution,
        endpoint=endpoint,
    )
    run_config = RunnerConfig(PROVIDER, pinned["model"], endpoint, allow_network)

    def build(mime: str, image: bytes) -> tuple[dict[str, Any], dict[str, str]]:
        return request_body(pinned, mime, image), {"x-goog-api-key": key}

    return exchange(
        run_config, case, build=build, extract=_extract(pinned["model"]), receipt_base=pinned
    )


# --- Batch REST helpers -----------------------------------------------------------------------


def job_name(value: object) -> str:
    """A batch job name of the documented shape; anything else is refused before any use."""
    if not isinstance(value, str) or _JOB_NAME.fullmatch(value) is None:
        raise RunnerUnavailable("batch job name is not batches/<id> of letters, digits, _ or -")
    return value


def batch_create_body(display_name: str, entries: Sequence[Mapping[str, Any]]) -> bytes:
    """The ``batchGenerateContent`` body: ``entries`` are ``{"request", "metadata": {"key"}}``."""
    batch = {"displayName": display_name, "inputConfig": {"requests": {"requests": list(entries)}}}
    return json.dumps({"batch": batch}, ensure_ascii=False, sort_keys=True).encode("utf-8")


def _rest(
    method: str,
    path: str,
    body: bytes | None,
    *,
    allow_network: bool,
    query: dict[str, str] | None = None,
) -> dict[str, Any]:
    """One batch REST call through the door and the exit guard. Returns the sealed result:
    ``{http_status, content_type, raw_b64}``, or a failure row when the answer carried a
    credential. The raw bytes are not interpreted here."""
    endpoint = API_BASE + path

    def produce(key: str | None) -> dict[str, Any]:
        if not key:
            raise RunnerUnavailable("GEMINI_API_KEY is not set")
        headers = {"x-goog-api-key": key}
        if body is not None:
            headers["Content-Type"] = "application/json"
        status, content_type, raw = request_bytes(
            RunnerConfig(PROVIDER, "", endpoint, allow_network),
            method,
            body,
            headers,
            query=query,
            max_response_bytes=BATCH_MAX_RESPONSE_BYTES,
        )
        return {
            "http_status": status,
            "content_type": content_type,
            "raw_b64": base64.b64encode(raw).decode("ascii"),
        }

    return guarded("GEMINI_API_KEY", endpoint, PROVIDER, {"benchmark_case_id": None}, produce)


def batch_create(model: str, body: bytes, *, allow_network: bool) -> dict[str, Any]:
    pinned = check_model(model, None)
    return _rest(
        "POST", f"/models/{pinned}:batchGenerateContent", body, allow_network=allow_network
    )


def batch_get(name: str, *, allow_network: bool) -> dict[str, Any]:
    return _rest("GET", "/" + job_name(name), None, allow_network=allow_network)


def batch_list(page_token: str | None, *, allow_network: bool) -> dict[str, Any]:
    query = None if page_token is None else {"pageToken": page_token}
    return _rest("GET", "/batches", None, allow_network=allow_network, query=query)


def batch_delete(name: str, *, allow_network: bool) -> dict[str, Any]:
    return _rest("DELETE", "/" + job_name(name), None, allow_network=allow_network)
