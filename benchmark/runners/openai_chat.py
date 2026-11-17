"""vLLM OpenAI-compatible chat endpoint, one page image per request (no vendor code).

Each candidate pins its own prompt, generation settings and input order in a ``ChatProfile``;
``config`` turns that into the document whose digest is the candidate's ``config_sha256``.
The server is launched with ``--served-model-name <repo>@<revision>``: the request names it
and the response must echo it, so a receipt with ``revision_attested: true`` was answered by
a server that was launched for that revision. Anything else is a failure row.
The optional bearer token is read through ``base.read_credential`` (an endpoint that contains
it is refused) and travels in the Authorization header only.
"""

from __future__ import annotations

import base64
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from .base import RunnerConfig, read_credential
from .vlm import ResponseRefused, exchange, render_settings, require_revision


@dataclass(frozen=True)
class ChatProfile:
    provider: str
    model: str  # Hugging Face repository id
    prompt: str
    prompt_source: str  # the card quoted, or "generic: ..." when the card publishes none
    generation: Mapping[str, Any]  # request-body fields sent as-is (vLLM extra params included)
    text_first: bool = False


def config(profile: ChatProfile, revision: str) -> dict[str, Any]:
    require_revision(revision)
    return {
        "provider": profile.provider,
        "model": profile.model,
        "served_model_name": f"{profile.model}@{revision}",
        "prompt": profile.prompt,
        "prompt_source": profile.prompt_source,
        "generation": dict(profile.generation),
        "content_order": "text_first" if profile.text_first else "image_first",
        "input_mode": "page_image_data_url",
        **render_settings(),
    }


def _extract(served: str) -> Callable[[dict[str, Any]], tuple[str, Any, bool]]:
    def extract(response: dict[str, Any]) -> tuple[str, Any, bool]:
        if response.get("model") != served:
            raise ResponseRefused("served_model_differs")
        choice = response["choices"][0]
        if choice.get("finish_reason") != "stop":
            raise ResponseRefused("finish_reason_not_stop")
        content = choice["message"]["content"]
        if not isinstance(content, str):
            raise ResponseRefused("empty_completion")
        return content, response.get("usage"), True

    return extract


def run_chat(
    profile: ChatProfile,
    payload: dict[str, Any],
    *,
    endpoint: str | None,
    revision: str,
    allow_network: bool,
) -> dict[str, Any]:
    pinned = config(profile, revision)
    token = read_credential("AKC_BENCHMARK_PROVIDER_TOKEN", endpoint)
    run_config = RunnerConfig(profile.provider, revision, endpoint, allow_network)

    def build(mime: str, image: bytes) -> tuple[dict[str, Any], dict[str, str]]:
        url = f"data:{mime};base64,{base64.b64encode(image).decode('ascii')}"
        parts: list[dict[str, Any]] = [
            {"type": "image_url", "image_url": {"url": url}},
            {"type": "text", "text": profile.prompt},
        ]
        if profile.text_first:
            parts.reverse()
        request = {
            "model": pinned["served_model_name"],
            "messages": [{"role": "user", "content": parts}],
            **pinned["generation"],
        }
        headers: dict[str, str] = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return request, headers

    return exchange(
        run_config,
        payload,
        build=build,
        extract=_extract(pinned["served_model_name"]),
        receipt_base=pinned,
    )


def runner(
    profile: ChatProfile,
) -> tuple[Callable[..., dict[str, Any]], Callable[..., dict[str, Any]]]:
    """(run, config) for one profile, in the registry's calling convention."""

    def run(
        case: dict[str, Any], *, endpoint: str | None, revision: str, allow_network: bool = False
    ) -> dict[str, Any]:
        return run_chat(
            profile, case, endpoint=endpoint, revision=revision, allow_network=allow_network
        )

    def pinned_config(*, revision: str) -> dict[str, Any]:
        return config(profile, revision)

    return run, pinned_config
