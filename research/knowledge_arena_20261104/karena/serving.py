"""One open-weights candidate on one RunPod pod, served by the pinned vLLM image.

Everything with money or secrets attached is the 2026-09-03 Arena's code:
``RunPodPodsClient`` (dry by default, no write retries, idempotent create,
adopt-or-refuse on name clash), ``poll_until_ready`` (deadline, crash-loop and
fatal-log detection), the secret-free guard and the cost-ledger arithmetic.
This module adds only what an LLM pod needs on top: the ``vllm serve`` args,
an API key the vLLM server enforces, and an OpenAI-compatible chat call.
"""

from __future__ import annotations

import json
import secrets
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

import httpx
from arena.controller.run import POD_MISSING, poll_until_ready
from arena.provider.runpod_pods import REDACTED_ENV_KEYS, Pod, PodSpec, RunPodPodsClient
from arena.provider.safety import register_live_secret
from arena.provider.secrets import Secret
from arena.provider.worker_client import (
    PROXY_HOST_TEMPLATE,
    WorkerHTTPError,
    WorkerTransportError,
)

__all__ = ["ChatResult", "LlmPodSpec", "VllmEndpoint", "new_api_key", "vllm_args"]

VLLM_PORT: Final = 8000
API_KEY_ENV: Final = "VLLM_API_KEY"


def new_api_key() -> Secret:
    value = "kar" + secrets.token_hex(24)
    register_live_secret(value)
    return Secret(value, label=API_KEY_ENV)


def vllm_args(row: Mapping[str, Any], *, served_name: str, max_model_len: int) -> tuple[str, ...]:
    """``vllm serve`` arguments; everything that changes outputs is pinned here and receipted."""

    return (
        str(row["exact_model_id"]),
        "--revision",
        str(row["exact_revision"]),
        "--tokenizer-revision",
        str(row["exact_revision"]),
        "--served-model-name",
        served_name,
        "--max-model-len",
        str(max_model_len),
        "--gpu-memory-utilization",
        "0.90",
        "--seed",
        "0",
        "--generation-config",
        "vllm",
        "--port",
        str(VLLM_PORT),
    )


@dataclass(frozen=True, slots=True)
class LlmPodSpec(PodSpec):
    """A baked ``vllm/vllm-openai`` pod: REST v2 ``cmd`` (exec form) goes to the image ENTRYPOINT.

    v2 ``args`` is one raw string; ``cmd`` is the argument list, so no shell splitting.
    """

    args: tuple[str, ...] = ()
    api_key: Secret | None = None
    extra_payload: Mapping[str, object] = field(default_factory=dict)

    def env(self) -> dict[str, str]:
        values = PodSpec.env(self)
        if self.api_key is not None:
            values[API_KEY_ENV] = self.api_key.reveal()
        return values

    def to_payload(self, gpu_type_id: str) -> dict[str, object]:
        payload = PodSpec.to_payload(self, gpu_type_id)
        payload["cmd"] = list(self.args)
        payload.update(self.extra_payload)
        return payload

    def redacted_payload(self, gpu_type_id: str) -> dict[str, object]:
        payload = self.to_payload(gpu_type_id)
        payload["env"] = {
            key: ("<redacted>" if key in REDACTED_ENV_KEYS or key == API_KEY_ENV else value)
            for key, value in sorted(self.env().items())
        }
        return payload


@dataclass(frozen=True, slots=True)
class ChatResult:
    http_status: int | None
    content: str | None
    finish_reason: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    latency_ms: int
    raw_body: str
    error: str | None


class VllmEndpoint:
    """The vLLM OpenAI-compatible server behind the RunPod proxy."""

    def __init__(
        self,
        pod_id: str,
        *,
        api_key: Secret,
        served_name: str,
        base_url: str | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout_seconds: float = 300.0,
    ) -> None:
        self.base_url = base_url or PROXY_HOST_TEMPLATE.format(pod_id=pod_id, port=VLLM_PORT)
        self.served_name = served_name
        self._key = api_key
        self._http = httpx.Client(
            timeout=httpx.Timeout(timeout_seconds, connect=20.0),
            transport=transport,
            headers={"User-Agent": "tavonel-karena/1"},
        )

    def close(self) -> None:
        self._http.close()

    def _auth(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._key.reveal()}"}

    def ready(self) -> Mapping[str, object]:
        """``arena.controller.run.WorkerPort.ready`` over ``GET /v1/models``."""

        url = f"{self.base_url}/v1/models"
        try:
            response = self._http.get(url, headers=self._auth(), timeout=20.0)
        except httpx.HTTPError as exc:
            raise WorkerTransportError(type(exc).__name__, url=url) from None
        if response.status_code != 200:
            raise WorkerHTTPError(
                f"HTTP {response.status_code}", status_code=response.status_code, url=url
            )
        try:
            ids = [item["id"] for item in response.json()["data"]]
        except (ValueError, KeyError, TypeError):
            return {"stage": "LOADING"}
        return {"stage": "READY" if self.served_name in ids else "LOADING"}

    def heartbeat(self) -> Mapping[str, object]:  # pragma: no cover - WorkerPort surface only
        return self.ready()

    def chat(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        schema: Mapping[str, Any],
        schema_name: str,
        params: Mapping[str, Any],
        chat_template_kwargs: Mapping[str, Any],
    ) -> ChatResult:
        body = {
            "model": self.served_name,
            "messages": list(messages),
            "temperature": params["temperature"],
            "seed": params["seed"],
            "max_tokens": params["max_tokens"],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "schema": {k: v for k, v in schema.items() if k not in {"$schema", "title"}},
                    "strict": True,
                },
            },
            "chat_template_kwargs": dict(chat_template_kwargs),
        }
        started = time.monotonic()
        try:
            response = self._http.post(
                f"{self.base_url}/v1/chat/completions", headers=self._auth(), json=body
            )
        except httpx.HTTPError as exc:
            return ChatResult(
                None, None, None, None, None, _ms(started), "", f"transport: {type(exc).__name__}"
            )
        raw = response.text
        if response.status_code != 200:
            return ChatResult(
                response.status_code,
                None,
                None,
                None,
                None,
                _ms(started),
                raw,
                f"HTTP {response.status_code}",
            )
        try:
            parsed = json.loads(raw)
            choice = parsed["choices"][0]
            usage = parsed.get("usage") or {}
            return ChatResult(
                200,
                choice["message"].get("content"),
                choice.get("finish_reason"),
                usage.get("prompt_tokens"),
                usage.get("completion_tokens"),
                _ms(started),
                raw,
                None,
            )
        except (ValueError, KeyError, IndexError, TypeError):
            return ChatResult(
                200, None, None, None, None, _ms(started), raw, "envelope unparseable"
            )


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def wait_until_ready(
    client: RunPodPodsClient,
    pod: Pod,
    endpoint: VllmEndpoint,
    *,
    deadline_seconds: float,
    progress: Any,
    check: Any = None,
) -> tuple[str, tuple[str, ...]]:
    """The Arena's readiness poll, unchanged, with this pod's status and log readers.

    ``check`` runs before every poll (STOP file, budget); an exception from it ends
    the wait and the caller deletes the pod.
    """

    def status() -> str | None:
        if check is not None:
            check()
        current = client.get_pod(pod.pod_id)
        if current is None:
            return POD_MISSING
        return current.status if isinstance(current, Pod) else None

    def logs() -> Sequence[Mapping[str, object]]:
        tail = client.get_logs(pod.pod_id, tail=200, total_seconds=8.0)
        return tail if isinstance(tail, tuple) else ()

    return poll_until_ready(
        endpoint,  # type: ignore[arg-type]  # only .ready() is called during the poll
        max_attempts=None,
        poll_seconds=15.0,
        deadline_seconds=deadline_seconds,
        pod_status=status,
        log_tail=logs,
        progress=progress,
    )
