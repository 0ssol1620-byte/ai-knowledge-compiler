"""olmOCR-2-7B-1025-FP8 adapter — the official olmOCR toolkit path.

Official sources (resolved 2026-09-03):

- https://huggingface.co/allenai/olmOCR-2-7B-1025-FP8 (revision
  ``40bd7202494b8264ee17ada08b401b5aab7a9ce1``): "The best way to use this model is
  via the olmOCR toolkit", and "this model expects as input a single document image,
  rendered such that the longest dimension is 1288 pixels".
- https://github.com/allenai/olmocr @ ``v0.4.27`` =
  ``1e139a5ea61f1668164e6b63357d7284a8391615``: ``olmocr/pipeline.py`` builds the
  request with ``build_no_anchoring_v4_yaml_prompt()``, ``max_tokens = 8000`` and
  ``temperature = 0.0`` on the first attempt, against a vLLM server started with
  ``--served-model-name olmocr --max-model-len 16384 --limit-mm-per-prompt
  '{"video": 0}'``.

Two things this module refuses to do silently:

1. It will not run against a prompt that differs from what the installed toolkit
   builds. ``load`` compares the registered prompt text with
   ``olmocr.prompts.build_no_anchoring_v4_yaml_prompt()`` and fails closed on drift.
2. It will not pretend that resampling a staged PNG to 1288 px is the same act as
   the toolkit's ``pdftoppm`` re-render. Every page records ``resize_policy``,
   the source dimensions and the served dimensions.

Nothing heavy is imported at module scope; ``PIL`` and ``olmocr`` are only touched
inside ``load``/``infer`` through injectable collaborators, so tests run on CPU.
"""

from __future__ import annotations

import base64
import hashlib
import io
import itertools
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
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

MODEL_KEY = "olmocr2"
MODEL_REPO = "allenai/olmOCR-2-7B-1025-FP8"
WEIGHTS_SIDECAR_NAME = ".arena_weights.json"
SEMANTIC_ERROR_PREFIX = "arena.semantic_error_class="
REPETITION_RUN_THRESHOLD = 12

#: olmocr/pipeline.py v0.4.27, ``--target_longest_image_dim`` default.
TOOLKIT_TARGET_LONGEST_IMAGE_DIM = 1288
#: olmocr/pipeline.py v0.4.27, ``build_page_query``.
TOOLKIT_MAX_TOKENS = 8000
TOOLKIT_SERVED_MODEL_NAME = "olmocr"

#: ARENA_CONTRACT D34. The prompt is not a literal in this file: the installed
#: olmocr toolkit builds it (see :class:`ToolkitPromptSource` and
#: ``runtime.json.inference_config.toolkit_prompt_builder``), and ``load`` refuses to
#: serve when the built text does not hash to what the registry recorded.
PROMPT_KIND = "toolkit"
#: The one call that produces the prompt bytes for this revision. Lane R reproduces
#: ``prompt_registry/olmocr2_no_anchoring_v4_yaml_v1.txt`` from exactly this, at
#: toolkit revision ``inference_config.toolkit_revision``.
TOOLKIT_PROMPT_BUILDER = "olmocr.prompts.build_no_anchoring_v4_yaml_prompt"


@dataclass(frozen=True, slots=True)
class PreparedImage:
    png_bytes: bytes
    width: int
    height: int
    source_width: int
    source_height: int
    resized: bool


@runtime_checkable
class ChatBackend(Protocol):
    def chat(self, payload: Mapping[str, Any], timeout_s: float) -> Mapping[str, Any]: ...

    def provenance(self) -> Mapping[str, Any]: ...


@runtime_checkable
class PromptSource(Protocol):
    """Builds the prompt exactly as the installed toolkit revision does."""

    def build_prompt(self) -> str: ...

    def describe(self) -> Mapping[str, Any]: ...


@runtime_checkable
class ImagePreparer(Protocol):
    def prepare(self, image_path: Path, target_longest: int) -> PreparedImage: ...

    def describe(self) -> Mapping[str, Any]: ...


class HttpChatBackend:
    """Stdlib-only client for the in-pod vLLM server."""

    def __init__(self, endpoint: str, *, served_model_name: str) -> None:
        parsed = urllib.parse.urlparse(endpoint)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise AdapterError(
                "DEPENDENCY", f"endpoint must be a loopback http URL, got {endpoint!r}"
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


class ToolkitPromptSource:
    """Reads the prompt from the installed ``olmocr`` package, never from a copy."""

    def __init__(self) -> None:
        self._version: str | None = None

    def build_prompt(self) -> str:
        from importlib.metadata import PackageNotFoundError
        from importlib.metadata import version as package_version

        try:
            from olmocr.prompts import (  # type: ignore[import-not-found]
                build_no_anchoring_v4_yaml_prompt,
            )
        except ImportError as exc:
            raise AdapterError(
                "DEPENDENCY",
                "the olmocr toolkit is not importable; this runtime is defined by it",
            ) from exc
        try:
            self._version = package_version("olmocr")
        except PackageNotFoundError as exc:
            raise AdapterError(
                "DEPENDENCY", "olmocr is importable but not an installed distribution"
            ) from exc
        built = build_no_anchoring_v4_yaml_prompt()
        if not isinstance(built, str) or not built.strip():
            raise AdapterError("DEPENDENCY", "olmocr prompt builder returned no text")
        return built

    def describe(self) -> Mapping[str, Any]:
        return {
            "source": "olmocr.prompts.build_no_anchoring_v4_yaml_prompt",
            "olmocr_version": self._version,
        }


class PillowImagePreparer:
    """Resample the staged PNG so its longest side is the toolkit's target.

    Never upscales: a page staged smaller than the target is served as-is and the
    receipt says so. Upsampling would invent detail the source does not carry.
    """

    def prepare(self, image_path: Path, target_longest: int) -> PreparedImage:
        try:
            from PIL import Image
        except ImportError as exc:
            raise AdapterError("DEPENDENCY", "Pillow is not available in this image") from exc
        try:
            with Image.open(image_path) as image:
                image.load()
                source_width, source_height = image.size
                longest = max(source_width, source_height)
                if longest <= 0:
                    raise AdapterError("INPUT_DECODE", f"{image_path.name} has a zero dimension")
                if longest <= target_longest:
                    return PreparedImage(
                        png_bytes=image_path.read_bytes(),
                        width=source_width,
                        height=source_height,
                        source_width=source_width,
                        source_height=source_height,
                        resized=False,
                    )
                scale = target_longest / longest
                width = max(1, round(source_width * scale))
                height = max(1, round(source_height * scale))
                resampled = image.convert("RGB").resize(
                    (width, height), Image.Resampling.LANCZOS
                )
                buffer = io.BytesIO()
                resampled.save(buffer, format="PNG")
                png_bytes = buffer.getvalue()
        except OSError as exc:
            raise AdapterError("INPUT_DECODE", f"cannot decode {image_path.name}") from exc
        return PreparedImage(
            png_bytes=png_bytes,
            width=width,
            height=height,
            source_width=source_width,
            source_height=source_height,
            resized=True,
        )

    def describe(self) -> Mapping[str, Any]:
        return {"preparer": "pillow-lanczos", "upscales": False}


def read_weights_sidecar(weights_dir: Path) -> Mapping[str, Any]:
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


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def weights_manifest_sha256(
    weights_dir: Path, sidecar: Mapping[str, Any], *, deep: bool
) -> str:
    if not deep:
        recorded = sidecar.get("files_manifest_sha256")
        if isinstance(recorded, str) and recorded:
            return recorded
        return "unverified:hash_weights_on_load=false and the image recorded no manifest"
    pairs: list[str] = []
    for path in sorted(p for p in weights_dir.rglob("*") if p.is_file()):
        if path.name == WEIGHTS_SIDECAR_NAME:
            continue
        relative = path.relative_to(weights_dir).as_posix()
        pairs.append(f"{relative}:{file_sha256(path)[len('sha256:') :]}")
    return "sha256:" + hashlib.sha256("\n".join(pairs).encode("utf-8")).hexdigest()


def classify_output(text: str) -> str | None:
    if not text.strip():
        return "OUTPUT_EMPTY"
    lines = [line.strip() for line in text.splitlines() if len(line.strip()) > 8]
    run = 1
    for previous, current in itertools.pairwise(lines):
        run = run + 1 if current == previous else 1
        if run >= REPETITION_RUN_THRESHOLD:
            return "OUTPUT_REPETITION"
    return None


def registered_prompt_sha256(cfg: AdapterConfig) -> str:
    """The registry hash the built prompt must match, as a bare hex digest.

    ARENA_CONTRACT D34 names ``AdapterConfig.prompt_sha256``; the orchestrator added
    the field on 2026-09-03 (11.6) and the worker fills it from the resolved
    ``prompt_registry/<prompt_id>.txt``. It is typed ``str | None``, so when the
    worker leaves it unset the registry text delivered in ``prompt_text`` -- the
    bytes of that same file -- is hashed instead, which is the same number by
    construction. When neither is available there is nothing to verify against and
    the load is refused rather than run unverified. Nothing here falls back to
    trusting the toolkit.
    """

    declared = cfg.prompt_sha256
    if declared is not None and declared.strip():
        # D35: "sha256:<hex>" and bare hex are the same value. Normalise the case
        # BEFORE stripping the prefix, so an upper-cased spelling is not silently
        # kept whole and then compared against a bare digest that can never match.
        return declared.strip().lower().removeprefix("sha256:")
    if cfg.prompt_text:
        return hashlib.sha256(cfg.prompt_text.encode("utf-8")).hexdigest()
    raise AdapterError(
        "MODEL_LOAD",
        f"prompt_kind={PROMPT_KIND}: the worker supplied neither prompt_sha256 nor "
        f"prompt_text for prompt_id {cfg.prompt_id!r}, so the toolkit-built prompt "
        "cannot be verified against the registry",
    )


class OlmOcr2Adapter:
    """``ArenaModelAdapter`` for allenai/olmOCR-2-7B-1025-FP8."""

    model_key = MODEL_KEY

    def __init__(
        self,
        backend: ChatBackend | None = None,
        prompt_source: PromptSource | None = None,
        image_preparer: ImagePreparer | None = None,
    ) -> None:
        self._backend = backend
        self._prompt_source = prompt_source
        self._image_preparer = image_preparer
        self._cfg: AdapterConfig | None = None
        self._prompt_text: str | None = None
        self._prompt_sha256: str | None = None

    def load(self, cfg: AdapterConfig) -> LoadReceipt:
        started = time.monotonic()
        if cfg.model_repo != MODEL_REPO:
            raise AdapterError(
                "MODEL_LOAD",
                f"adapter is pinned to {MODEL_REPO}, was asked for {cfg.model_repo}",
            )
        sidecar = read_weights_sidecar(cfg.weights_dir)
        if sidecar.get("revision") != cfg.model_revision:
            raise AdapterError(
                "MODEL_LOAD",
                f"weights on disk are revision {sidecar.get('revision')!r}, "
                f"campaign pinned {cfg.model_revision!r}",
            )
        largest = sidecar.get("largest_file")
        expected = sidecar.get("largest_file_sha256")
        if not isinstance(largest, str) or not isinstance(expected, str):
            raise AdapterError(
                "MODEL_LOAD", "weights sidecar does not name the largest file and its sha256"
            )
        largest_path = cfg.weights_dir / largest
        if not largest_path.is_file():
            raise AdapterError("MODEL_LOAD", f"largest weight file {largest} is missing")
        observed = file_sha256(largest_path)
        if observed != expected:
            raise AdapterError(
                "CHECKSUM", f"{largest} hashes to {observed}, sidecar recorded {expected}"
            )

        if self._prompt_source is None:
            self._prompt_source = ToolkitPromptSource()
        toolkit_prompt = self._prompt_source.build_prompt()
        # D34 prompt_kind=toolkit: the built text is hashed and compared with the
        # registry's hash. Byte-exact per D8 -- sha256 of the UTF-8 bytes, nothing
        # stripped, nothing normalised.
        built_sha256 = hashlib.sha256(toolkit_prompt.encode("utf-8")).hexdigest()
        expected_sha256 = registered_prompt_sha256(cfg)
        if built_sha256 != expected_sha256:
            raise AdapterError(
                "MODEL_LOAD",
                f"prompt_kind={PROMPT_KIND}: {TOOLKIT_PROMPT_BUILDER} at the installed "
                f"toolkit revision builds a prompt hashing to sha256:{built_sha256}, "
                f"registry {cfg.prompt_id!r} recorded sha256:{expected_sha256}; "
                "a prompt drift is a different experiment, not a warning",
            )
        self._prompt_text = toolkit_prompt
        self._prompt_sha256 = built_sha256
        if self._image_preparer is None:
            self._image_preparer = PillowImagePreparer()
        if self._backend is None:
            endpoint = cfg.inference_config.get("endpoint")
            served = cfg.inference_config.get("served_model_name", TOOLKIT_SERVED_MODEL_NAME)
            if not isinstance(endpoint, str) or not isinstance(served, str):
                raise AdapterError(
                    "DEPENDENCY", "inference_config lacks endpoint/served_model_name"
                )
            self._backend = HttpChatBackend(endpoint, served_model_name=served)
        self._cfg = cfg
        deep = bool(cfg.inference_config.get("hash_weights_on_load", True))
        return LoadReceipt(
            model_key=MODEL_KEY,
            model_repo=cfg.model_repo,
            model_revision=str(sidecar.get("revision")),
            weights_sha256_manifest=weights_manifest_sha256(cfg.weights_dir, sidecar, deep=deep),
            load_ms=int((time.monotonic() - started) * 1000),
            cache_hit=bool(sidecar.get("cache_hit", False)),
            runtime_provenance=self.runtime_provenance(),
        )

    def warmup(self, synthetic_image: Path) -> WarmupReceipt:
        started = time.monotonic()
        raw = self._infer_path(synthetic_image, timeout_s=300.0)
        return WarmupReceipt(
            warmup_ms=int((time.monotonic() - started) * 1000),
            output_chars=len(raw.raw_text),
            schema_valid=raw.native_json is not None,
            peak_vram_mb=raw.peak_vram_mb,
        )

    def infer(self, page: PageInput) -> RawOutput:
        cfg = self._require_cfg()
        timeout = float(cfg.inference_config.get("per_page_timeout_seconds", 300))
        return self._infer_path(page.image_path, timeout_s=timeout)

    def runtime_provenance(self) -> Mapping[str, Any]:
        provenance: dict[str, Any] = {
            "model_key": MODEL_KEY,
            "model_repo": MODEL_REPO,
            "official_runtime": "olmocr toolkit against a vLLM OpenAI-compatible server",
        }
        provenance["prompt_kind"] = PROMPT_KIND
        provenance["prompt_builder"] = TOOLKIT_PROMPT_BUILDER
        if self._prompt_sha256 is not None:
            provenance["prompt_sha256"] = f"sha256:{self._prompt_sha256}"
        if self._prompt_source is not None:
            provenance["prompt_source"] = dict(self._prompt_source.describe())
        if self._image_preparer is not None:
            provenance["image_preparer"] = dict(self._image_preparer.describe())
        if self._backend is not None:
            provenance["backend"] = dict(self._backend.provenance())
        if self._cfg is not None:
            provenance["prompt_id"] = self._cfg.prompt_id
            provenance["inference_config_sha256"] = self._cfg.inference_config_sha256
        return provenance

    def close(self) -> None:
        self._backend = None
        self._cfg = None
        self._prompt_text = None

    # -- internals ---------------------------------------------------------

    def _require_cfg(self) -> AdapterConfig:
        if self._cfg is None or self._backend is None or self._image_preparer is None:
            raise AdapterError("MODEL_LOAD", "adapter used before load() completed")
        return self._cfg

    def _require_prompt(self) -> str:
        if self._prompt_text is None:
            raise AdapterError("MODEL_LOAD", "adapter used before load() verified the prompt")
        return self._prompt_text

    def _infer_path(self, image_path: Path, *, timeout_s: float) -> RawOutput:
        cfg = self._require_cfg()
        backend = self._backend
        preparer = self._image_preparer
        if backend is None or preparer is None:  # pragma: no cover - guarded above
            raise AdapterError("MODEL_LOAD", "adapter used before load() completed")

        preprocess_started = time.monotonic()
        target = int(
            cfg.inference_config.get(
                "target_longest_image_dim", TOOLKIT_TARGET_LONGEST_IMAGE_DIM
            )
        )
        prepared = preparer.prepare(image_path, target)
        encoded = base64.b64encode(prepared.png_bytes).decode("ascii")
        media_type = str(cfg.inference_config.get("image_media_type", "image/png"))
        payload: dict[str, Any] = {
            "model": cfg.inference_config.get("served_model_name", TOOLKIT_SERVED_MODEL_NAME),
            "messages": [
                {
                    "role": "user",
                    "content": [
                        # D34 prompt_kind=toolkit: what goes on the wire is the text
                        # the toolkit built and load() verified, never a copy.
                        {"type": "text", "text": self._require_prompt()},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{media_type};base64,{encoded}"},
                        },
                    ],
                }
            ],
            "max_tokens": cfg.inference_config.get("max_tokens", TOOLKIT_MAX_TOKENS),
            "temperature": cfg.inference_config.get("temperature", 0.0),
        }
        preprocess_ms = int((time.monotonic() - preprocess_started) * 1000)

        inference_started = time.monotonic()
        response = backend.chat(payload, timeout_s)
        inference_ms = int((time.monotonic() - inference_started) * 1000)

        postprocess_started = time.monotonic()
        text, finish_reason, usage = _extract_completion(response)
        warnings: list[str] = []
        if prepared.resized:
            warnings.append(
                "image resampled from "
                f"{prepared.source_width}x{prepared.source_height} to "
                f"{prepared.width}x{prepared.height} (longest side {target}, lanczos)"
            )
        else:
            warnings.append(
                "image served at source size "
                f"{prepared.source_width}x{prepared.source_height}; "
                f"already at or below the {target} px target, never upscaled"
            )
        if finish_reason == "length":
            warnings.append(f"{SEMANTIC_ERROR_PREFIX}OUTPUT_TRUNCATED")
            warnings.append("finish_reason=length; max_tokens reached")
        semantic = classify_output(text)
        if semantic is not None:
            warnings.append(f"{SEMANTIC_ERROR_PREFIX}{semantic}")
        # RawOutput.semantic_error_class takes one value (D3); a truncated
        # generation is the higher-priority verdict when both conditions hold.
        semantic_error_class = "OUTPUT_TRUNCATED" if finish_reason == "length" else semantic
        front_matter = parse_front_matter(text)
        if front_matter is None and text.strip():
            warnings.append("output carried no YAML front matter block")
        postprocess_ms = int((time.monotonic() - postprocess_started) * 1000)

        native_json: dict[str, Any] = {
            "front_matter": front_matter,
            "image": {
                "source_width": prepared.source_width,
                "source_height": prepared.source_height,
                "served_width": prepared.width,
                "served_height": prepared.height,
                "resized": prepared.resized,
                "target_longest_image_dim": target,
            },
        }
        return RawOutput(
            raw_text=text,
            output_format="markdown",
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


def parse_front_matter(text: str) -> dict[str, str] | None:
    """Split the toolkit's YAML front matter without a YAML dependency.

    The prompt fixes the shape: ``---`` newline, ``key: value`` lines, ``---``.
    Values are kept as the strings the model wrote. Nothing is coerced or inferred.
    """
    stripped = text.lstrip()
    if not stripped.startswith("---"):
        return None
    lines = stripped.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    fields: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return fields
        if ":" not in line:
            return None
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return None


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


__all__ = [
    "PROMPT_KIND",
    "TOOLKIT_PROMPT_BUILDER",
    "ChatBackend",
    "HttpChatBackend",
    "ImagePreparer",
    "OlmOcr2Adapter",
    "PillowImagePreparer",
    "PreparedImage",
    "PromptSource",
    "ToolkitPromptSource",
    "classify_output",
    "parse_front_matter",
]
