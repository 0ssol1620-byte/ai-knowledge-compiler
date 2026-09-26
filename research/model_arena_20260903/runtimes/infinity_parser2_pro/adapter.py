"""Infinity-Parser2-Pro adapter — official vLLM serving path from the model card.

Official sources (resolved 2026-09-03):

- https://huggingface.co/infly/Infinity-Parser2-Pro  (revision
  ``b27d470100514329fc6439aada8f16ccea5f9e2a``) — the ``vllm serve`` command, the
  doc2json prompt, ``min_pixels`` / ``max_pixels``, ``max_new_tokens=32768``,
  ``temperature=0.0``, ``top_p=1.0`` and ``chat_template_kwargs={"enable_thinking": False}``
  all come from that card verbatim.
- The ``infinity_parser2`` wrapper published from https://github.com/infly-ai/INF-MLLM
  is deliberately NOT used: that repository ships no LICENSE file, so its code is
  readable but not reusable. See ``runtime.json.notes`` and ``README.md``.

Nothing in this module imports torch, vllm, transformers or PIL, so it can be
imported and unit-tested on a CPU box. The HTTP backend is only constructed
inside :meth:`InfinityParser2ProAdapter.load`; tests inject a fake instead.
"""

from __future__ import annotations

import base64
import hashlib
import itertools
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from arena.worker.adapter_api import (
    AdapterConfig,
    AdapterError,
    LoadReceipt,
    PageInput,
    RawOutput,
    WarmupReceipt,
)

MODEL_KEY = "infinity_parser2_pro"
MODEL_REPO = "infly/Infinity-Parser2-Pro"

#: Written by ``Dockerfile`` / ``bootstrap.sh`` next to the weights. It records what
#: ``hf download --revision`` actually produced, so ``load`` can check the revision it
#: is serving instead of trusting the value it was asked for.
WEIGHTS_SIDECAR_NAME = ".arena_weights.json"

#: A page can fail semantically (empty, truncated, degenerate repetition) while its
#: bytes are still worth freezing (masterplan section 7). The adapter API has no field
#: for that, so the classification travels in ``RawOutput.warnings`` behind this prefix
#: and the worker is expected to map it onto ``error_class``. See
#: INTERFACE_CHANGES_PROPOSED in the lane report.
SEMANTIC_ERROR_PREFIX = "arena.semantic_error_class="

#: Consecutive repetitions of one non-trivial line before the output is called
#: degenerate. Uncalibrated: it is a tripwire for the QA gate, not a quality score.
REPETITION_RUN_THRESHOLD = 12

#: ARENA_CONTRACT D34. This adapter sends ``AdapterConfig.prompt_text`` verbatim as
#: the text part of the chat message (see ``_build_payload``) and carries no copy of
#: its own, so the registry file ``prompt_registry/infinity_parser2_pro_doc2json_v1.txt``
#: is the single source of the prompt bytes. An empty one is refused: a document
#: parser prompted with nothing is a different experiment, not a cheaper one.
PROMPT_KIND = "text"


@runtime_checkable
class ChatBackend(Protocol):
    """OpenAI-compatible ``/v1/chat/completions`` transport."""

    def chat(self, payload: Mapping[str, Any], timeout_s: float) -> Mapping[str, Any]: ...

    def provenance(self) -> Mapping[str, Any]: ...


class HttpChatBackend:
    """Stdlib-only client for the in-pod vLLM server. No third-party imports."""

    def __init__(self, endpoint: str, *, served_model_name: str) -> None:
        parsed = urllib.parse.urlparse(endpoint)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise AdapterError(
                "DEPENDENCY",
                f"endpoint must be a loopback http URL, got {endpoint!r}",
            )
        self._endpoint = endpoint
        self._served_model_name = served_model_name

    def chat(self, payload: Mapping[str, Any], timeout_s: float) -> Mapping[str, Any]:
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        request = urllib.request.Request(  # noqa: S310 - scheme checked in __init__
            self._endpoint,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_s) as response:  # noqa: S310
                decoded = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise AdapterError("INFERENCE_STALL", f"vLLM returned HTTP {exc.code}") from exc
        except TimeoutError as exc:
            raise AdapterError("INFERENCE_TIMEOUT", "vLLM request timed out") from exc
        except OSError as exc:
            raise AdapterError("INFRA_NETWORK", f"vLLM transport failure: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise AdapterError("OUTPUT_MALFORMED", "vLLM response was not JSON") from exc
        if not isinstance(decoded, dict):
            raise AdapterError("OUTPUT_MALFORMED", "vLLM response was not a JSON object")
        return decoded

    def provenance(self) -> Mapping[str, Any]:
        return {
            "backend": "vllm-openai-http",
            "endpoint": self._endpoint,
            "served_model_name": self._served_model_name,
        }


def read_weights_sidecar(weights_dir: Path) -> Mapping[str, Any]:
    """Read the build-time record of what was downloaded, or fail closed."""
    sidecar = weights_dir / WEIGHTS_SIDECAR_NAME
    try:
        text = sidecar.read_text(encoding="utf-8")
    except OSError as exc:
        raise AdapterError(
            "MODEL_LOAD",
            f"weights sidecar {sidecar} is missing; the image did not record a revision",
        ) from exc
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AdapterError("MODEL_LOAD", f"weights sidecar {sidecar} is not JSON") from exc
    if not isinstance(parsed, dict):
        raise AdapterError("MODEL_LOAD", f"weights sidecar {sidecar} is not a JSON object")
    return parsed


def weights_manifest_sha256(
    weights_dir: Path,
    sidecar: Mapping[str, Any],
    *,
    deep: bool,
) -> str:
    """sha256 over sorted ``(relative_path, file_sha256)`` pairs.

    ``deep=False`` returns an explicit ``unverified:<reason>`` string rather than a
    hash that looks like evidence it is not. Never invent a digest to fill a field.
    """
    if not deep:
        recorded = sidecar.get("files_manifest_sha256")
        if isinstance(recorded, str) and recorded:
            return recorded
        return "unverified:hash_weights_on_load=false and the image recorded no manifest"
    pairs: list[tuple[str, str]] = []
    for path in sorted(p for p in weights_dir.rglob("*") if p.is_file()):
        if path.name == WEIGHTS_SIDECAR_NAME:
            continue
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda handle=handle: handle.read(1024 * 1024), b""):  # type: ignore[misc]
                digest.update(chunk)
        pairs.append((path.relative_to(weights_dir).as_posix(), digest.hexdigest()))
    joined = "\n".join(f"{name}:{value}" for name, value in pairs)
    return "sha256:" + hashlib.sha256(joined.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def classify_output(text: str) -> str | None:
    """Return a semantic ``ERROR_CLASSES`` label for an output worth freezing anyway."""
    if not text.strip():
        return "OUTPUT_EMPTY"
    lines = [line.strip() for line in text.splitlines() if len(line.strip()) > 8]
    run = 1
    for previous, current in itertools.pairwise(lines):
        run = run + 1 if current == previous else 1
        if run >= REPETITION_RUN_THRESHOLD:
            return "OUTPUT_REPETITION"
    return None


class InfinityParser2ProAdapter:
    """``arena.worker.adapter_api.ArenaModelAdapter`` for Infinity-Parser2-Pro."""

    model_key = MODEL_KEY

    def __init__(self, backend: ChatBackend | None = None) -> None:
        self._backend = backend
        self._cfg: AdapterConfig | None = None
        self._load_receipt: LoadReceipt | None = None

    # -- lifecycle ---------------------------------------------------------

    def load(self, cfg: AdapterConfig) -> LoadReceipt:
        started = time.monotonic()
        if cfg.model_repo != MODEL_REPO:
            raise AdapterError(
                "MODEL_LOAD",
                f"adapter is pinned to {MODEL_REPO}, was asked for {cfg.model_repo}",
            )
        # D34 prompt_kind=text: the prompt arrives as text and is sent verbatim.
        if not cfg.prompt_text.strip():
            raise AdapterError(
                "MODEL_LOAD",
                f"prompt_kind={PROMPT_KIND}: AdapterConfig.prompt_text is empty for "
                f"prompt_id {cfg.prompt_id!r}; this runtime sends that text verbatim "
                "and will not run the model with no instruction",
            )
        sidecar = read_weights_sidecar(cfg.weights_dir)
        actual_revision = sidecar.get("revision")
        if actual_revision != cfg.model_revision:
            raise AdapterError(
                "MODEL_LOAD",
                f"weights on disk are revision {actual_revision!r}, "
                f"campaign pinned {cfg.model_revision!r}",
            )
        largest = sidecar.get("largest_file")
        expected = sidecar.get("largest_file_sha256")
        if not isinstance(largest, str) or not isinstance(expected, str):
            raise AdapterError(
                "MODEL_LOAD",
                "weights sidecar does not name the largest file and its sha256",
            )
        largest_path = cfg.weights_dir / largest
        if not largest_path.is_file():
            raise AdapterError("MODEL_LOAD", f"largest weight file {largest} is missing")
        observed = file_sha256(largest_path)
        if observed != expected:
            raise AdapterError(
                "CHECKSUM",
                f"{largest} hashes to {observed}, sidecar recorded {expected}",
            )
        deep = bool(cfg.inference_config.get("hash_weights_on_load", False))
        if self._backend is None:
            endpoint = cfg.inference_config.get("endpoint")
            served = cfg.inference_config.get("served_model_name", MODEL_KEY)
            if not isinstance(endpoint, str) or not isinstance(served, str):
                raise AdapterError(
                    "DEPENDENCY", "inference_config lacks endpoint/served_model_name"
                )
            self._backend = HttpChatBackend(endpoint, served_model_name=served)
        self._cfg = cfg
        receipt = LoadReceipt(
            model_key=MODEL_KEY,
            model_repo=cfg.model_repo,
            model_revision=str(actual_revision),
            weights_sha256_manifest=weights_manifest_sha256(cfg.weights_dir, sidecar, deep=deep),
            load_ms=int((time.monotonic() - started) * 1000),
            cache_hit=bool(sidecar.get("cache_hit", False)),
            runtime_provenance=self.runtime_provenance(),
        )
        self._load_receipt = receipt
        return receipt

    def warmup(self, synthetic_image: Path) -> WarmupReceipt:
        started = time.monotonic()
        raw = self._infer_path(
            synthetic_image,
            job_label="warmup",
            timeout_s=float(self._require_cfg().inference_config.get("warmup_timeout_s", 300)),
        )
        return WarmupReceipt(
            warmup_ms=int((time.monotonic() - started) * 1000),
            output_chars=len(raw.raw_text),
            schema_valid=raw.output_format in {"json", "markdown"},
            peak_vram_mb=raw.peak_vram_mb,
        )

    def infer(self, page: PageInput) -> RawOutput:
        cfg = self._require_cfg()
        timeout = float(cfg.inference_config.get("per_page_timeout_seconds", 600))
        return self._infer_path(page.image_path, job_label=page.case_key, timeout_s=timeout)

    def runtime_provenance(self) -> Mapping[str, Any]:
        provenance: dict[str, Any] = {
            "model_key": MODEL_KEY,
            "model_repo": MODEL_REPO,
            "official_runtime": "vllm",
            "runtime_wrapper": "none (INF-MLLM has no LICENSE; card vllm serve path used instead)",
        }
        if self._backend is not None:
            provenance["backend"] = dict(self._backend.provenance())
        if self._cfg is not None:
            provenance["prompt_id"] = self._cfg.prompt_id
            provenance["inference_config_sha256"] = self._cfg.inference_config_sha256
        return provenance

    def close(self) -> None:
        self._backend = None
        self._cfg = None

    # -- internals ---------------------------------------------------------

    def _require_cfg(self) -> AdapterConfig:
        if self._cfg is None or self._backend is None:
            raise AdapterError("MODEL_LOAD", "adapter used before load() completed")
        return self._cfg

    def _infer_path(self, image_path: Path, *, job_label: str, timeout_s: float) -> RawOutput:
        cfg = self._require_cfg()
        backend = self._backend
        if backend is None:  # pragma: no cover - guarded by _require_cfg
            raise AdapterError("MODEL_LOAD", "adapter used before load() completed")
        preprocess_started = time.monotonic()
        try:
            image_bytes = image_path.read_bytes()
        except OSError as exc:
            raise AdapterError("INPUT_DECODE", f"cannot read page image for {job_label}") from exc
        if not image_bytes:
            raise AdapterError("INPUT_DECODE", f"page image for {job_label} is empty")
        encoded = base64.b64encode(image_bytes).decode("ascii")
        media_type = str(cfg.inference_config.get("image_media_type", "image/png"))
        payload = self._build_payload(encoded, media_type, cfg)
        preprocess_ms = int((time.monotonic() - preprocess_started) * 1000)

        inference_started = time.monotonic()
        response = backend.chat(payload, timeout_s)
        inference_ms = int((time.monotonic() - inference_started) * 1000)

        postprocess_started = time.monotonic()
        text, finish_reason, usage = _extract_completion(response)
        warnings: list[str] = []
        if finish_reason == "length":
            warnings.append(f"{SEMANTIC_ERROR_PREFIX}OUTPUT_TRUNCATED")
            warnings.append("finish_reason=length; max_tokens reached")
        semantic = classify_output(text)
        if semantic is not None:
            warnings.append(f"{SEMANTIC_ERROR_PREFIX}{semantic}")
        # RawOutput.semantic_error_class takes one value (D3); a truncated
        # generation is the higher-priority verdict when both conditions hold.
        semantic_error_class = "OUTPUT_TRUNCATED" if finish_reason == "length" else semantic
        native_json = _try_parse_json_object(text)
        output_format = "json" if native_json is not None else "markdown"
        if native_json is None:
            warnings.append("model did not return a JSON object for the doc2json prompt")
        postprocess_ms = int((time.monotonic() - postprocess_started) * 1000)

        return RawOutput(
            raw_text=text,
            output_format=output_format,
            native_json=native_json,
            usage=usage,
            timings_ms={
                "preprocess_ms": preprocess_ms,
                "inference_ms": inference_ms,
                "postprocess_ms": postprocess_ms,
            },
            peak_vram_mb=None,
            first_token_at=None,
            warnings=tuple(warnings),
            semantic_error_class=semantic_error_class,
        )

    def _build_payload(
        self,
        encoded_image: str,
        media_type: str,
        cfg: AdapterConfig,
    ) -> dict[str, Any]:
        config = cfg.inference_config
        image_part: dict[str, Any] = {
            "type": "image_url",
            "image_url": {"url": f"data:{media_type};base64,{encoded_image}"},
        }
        for key in ("min_pixels", "max_pixels"):
            value = config.get(key)
            if value is not None:
                image_part[key] = value
        payload: dict[str, Any] = {
            "model": config.get("served_model_name", MODEL_KEY),
            "messages": [
                {
                    "role": "user",
                    "content": [image_part, {"type": "text", "text": cfg.prompt_text}],
                }
            ],
            "max_tokens": config.get("max_tokens", 32768),
            "temperature": config.get("temperature", 0.0),
            "top_p": config.get("top_p", 1.0),
        }
        chat_template_kwargs = config.get("chat_template_kwargs")
        if isinstance(chat_template_kwargs, Mapping):
            payload["chat_template_kwargs"] = dict(chat_template_kwargs)
        return payload


def _extract_completion(
    response: Mapping[str, Any],
) -> tuple[str, str | None, Mapping[str, Any]]:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise AdapterError("OUTPUT_MALFORMED", "vLLM response carried no choices")
    first = choices[0]
    if not isinstance(first, Mapping):
        raise AdapterError("OUTPUT_MALFORMED", "vLLM choice was not an object")
    message = first.get("message")
    if not isinstance(message, Mapping):
        raise AdapterError("OUTPUT_MALFORMED", "vLLM choice carried no message")
    content = message.get("content")
    if content is None:
        content = ""
    if not isinstance(content, str):
        raise AdapterError("OUTPUT_MALFORMED", "vLLM message content was not a string")
    finish_reason = first.get("finish_reason")
    usage = response.get("usage")
    return (
        content,
        finish_reason if isinstance(finish_reason, str) else None,
        dict(usage) if isinstance(usage, Mapping) else {},
    )


def _try_parse_json_object(text: str) -> Mapping[str, Any] | None:
    """Parse the doc2json envelope, tolerating a ```json fence. Never repairs content."""
    stripped = text.strip()
    if stripped.startswith("```"):
        newline = stripped.find("\n")
        if newline != -1:
            stripped = stripped[newline + 1 :]
        if stripped.rstrip().endswith("```"):
            stripped = stripped.rstrip()[: -len("```")]
        stripped = stripped.strip()
    if not stripped.startswith(("{", "[")):
        return None
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict):
        return parsed
    if isinstance(parsed, list):
        return {"elements": parsed}
    return None


__all__ = [
    "PROMPT_KIND",
    "ChatBackend",
    "HttpChatBackend",
    "InfinityParser2ProAdapter",
    "classify_output",
    "read_weights_sidecar",
    "weights_manifest_sha256",
]
