"""GLM-OCR adapter — the official glmocr SDK in self-hosted mode.

Official sources (resolved 2026-09-03):

- https://huggingface.co/zai-org/GLM-OCR @ ``ca5d8b3e287e52589e37c28385d9655ee4372f9d``
  — "For document parsing tasks, we strongly recommend using our official SDK …
  the SDK integrates PP-DocLayoutV3 and provides a complete pipeline for document
  parsing, including layout analysis and structured output generation."
- https://github.com/zai-org/GLM-OCR @ ``v0.1.5`` =
  ``98ef9846c7045774ff5391a50139e5cbe2850b54`` — ``glmocr/config.yaml`` holds every
  default this runtime uses, and ``glmocr.GlmOcr`` is the pipeline entry point.

The SDK is the model's official runtime, so this adapter drives it instead of
posting a bare ``Text Recognition:`` prompt at the raw checkpoint — that would be a
materially weaker configuration than the one the vendor benchmarks.

Two safety rails that are contract, not taste:

1. **MaaS mode is refused.** ``glmocr``'s shipped default is
   ``pipeline.maas.enabled: true``, which forwards pages to Zhipu's hosted API. This
   campaign measures the open model, and sending the founder's corpus to a third
   party is not something an adapter decides. ``load`` raises on ``maas_enabled``,
   and ``_verify_resolved_config`` re-checks the value the SDK itself resolved.
2. **No retries.** The SDK's ``retry_max_attempts`` is forced to 0; retry policy
   belongs to the controller (masterplan §15.9).

How the SDK is configured is not a free choice. ``glmocr.api.GlmOcr.__init__`` at
v0.1.5 takes ``config_path`` -- a YAML path -- plus a fixed set of keyword
overrides, and forwards ``**kwargs`` straight into ``load_config``, where an
unrecognised name is dropped without a word. Handing it ``config=<dict>`` therefore
looks like configuring the pipeline and configures nothing: the shipped
``glmocr/config.yaml`` wins, and its ``pipeline.maas.enabled`` is ``true``. So this
adapter renders its settings to a YAML file and passes ``config_path``, which is
what the SDK README's self-hosted section tells the operator to edit, and then
verifies against ``GlmOcr.config_model`` that the file actually took.

``glmocr`` pulls in torch, so it is imported inside ``load`` through an injectable
collaborator and tests substitute a fake.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import os
import shutil
import tempfile
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
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

MODEL_KEY = "glm_ocr"
MODEL_REPO = "zai-org/GLM-OCR"
WEIGHTS_SIDECAR_NAME = ".arena_weights.json"
SEMANTIC_ERROR_PREFIX = "arena.semantic_error_class="
REPETITION_RUN_THRESHOLD = 12

#: Where the PP-DocLayoutV3 checkpoint really is, when it is not where
#: ``runtime.json`` pins it. See ``resolve_layout_model_dir``.
LAYOUT_DIR_ENV = "ARENA_LAYOUT_DIR"

#: glmocr/config.yaml v0.1.5, ``pipeline.page_loader.task_prompt_mapping``. The model
#: card's "Prompt Limited" section says these are the only document-parsing prompts
#: GLM-OCR supports.
OFFICIAL_TASK_PROMPTS = {
    "text": "Text Recognition:",
    "formula": "Formula Recognition:",
    "table": "Table Recognition:",
}
OFFICIAL_SERVED_MODEL_NAME = "glm-ocr"

#: ARENA_CONTRACT D34. GLM-OCR is not prompted with one free-text instruction: the
#: SDK picks a task prefix per detected region from the mapping above and sends it
#: with the region image. There is therefore no single "prompt string" to hand the
#: adapter; what this runtime pins is the whole mapping, and ``load`` fails closed
#: when it does not hash to the registry entry for ``prompt_id``.
PROMPT_KIND = "toolkit"


def build_official_prompt_text() -> str:
    """Render the exact bytes ``prompt_registry/<prompt_id>.txt`` holds.

    The rendering is the one lane R already wrote into
    ``prompt_registry/glm_ocr_official_sdk_task_prompts_v1.txt``: the ARENA_CONTRACT
    section 2 canonical JSON of the mapping -- ``sort_keys=True``,
    ``separators=(",", ":")``, ``ensure_ascii=True``, no trailing newline. Escaping
    non-ASCII is what makes the bytes independent of the reader's encoding; the
    v0.1.5 mapping happens to be pure ASCII, so this pins the rule before a
    non-ASCII task prefix upstream can make the two renderings disagree.
    For SDK revision ``98ef9846c7045774ff5391a50139e5cbe2850b54`` (v0.1.5) that is
    90 bytes::

        {"formula":"Formula Recognition:","table":"Table Recognition:","text":"Text Recognition:"}

    hashing to
    ``sha256:3d62ac2e6e72a4064fdbbc5d8b045111133f663fb774e9eb0483933f36cf5e67``,
    which is what ``prompt_registry/sha256.json`` records for this prompt_id.
    """

    return json.dumps(
        dict(OFFICIAL_TASK_PROMPTS), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )


def registered_prompt_sha256(cfg: AdapterConfig) -> str:
    """The registry hash the built prompt text must match, as a bare hex digest.

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
        f"prompt_text for prompt_id {cfg.prompt_id!r}, so the SDK task prompts cannot "
        "be verified against the registry",
    )


@dataclass(frozen=True, slots=True)
class SdkPageResult:
    """One page as ``glmocr`` produced it."""

    markdown: str
    json_result: Mapping[str, Any] | None
    usage: Mapping[str, Any] = field(default_factory=dict)
    stage_timings_ms: Mapping[str, int] = field(default_factory=dict)


@runtime_checkable
class GlmOcrPipeline(Protocol):
    """The official ``glmocr`` pipeline, or a test double for it."""

    def parse_page(self, image_path: Path, timeout_s: float) -> SdkPageResult: ...

    def describe(self) -> Mapping[str, Any]: ...


class OfficialSdkPipeline:
    """Wraps ``glmocr.GlmOcr`` configured for the local vLLM server."""

    def __init__(self, config: Mapping[str, Any]) -> None:
        self._config = dict(config)
        self._parser: Any | None = None
        self._sdk_version: str | None = None
        self._config_dir: Path | None = None
        self._config_path: Path | None = None

    def _ensure_parser(self) -> Any:
        if self._parser is not None:
            return self._parser
        from importlib.metadata import PackageNotFoundError
        from importlib.metadata import version as package_version

        try:
            from glmocr import GlmOcr  # type: ignore[import-not-found]
        except ImportError as exc:
            raise AdapterError(
                "DEPENDENCY",
                f"the glmocr SDK is not importable ({exc}); this runtime is defined by it",
            ) from exc
        try:
            self._sdk_version = package_version("glmocr")
        except PackageNotFoundError as exc:
            raise AdapterError(
                "DEPENDENCY", "glmocr is importable but not an installed distribution"
            ) from exc
        layout_dir = Path(self._layout_model_dir())
        if not layout_dir.is_dir():
            raise AdapterError(
                "MODEL_LOAD",
                f"layout model directory {layout_dir} does not exist; glmocr passes it "
                "straight to PPDocLayoutV3ImageProcessor.from_pretrained, which would "
                "read it as a Hugging Face repo id and download an unpinned checkpoint",
            )
        config_path = self._write_sdk_config()
        try:
            self._parser = GlmOcr(
                config_path=str(config_path), layout_device=self._layout_device()
            )
        except TypeError as exc:
            raise AdapterError(
                "DEPENDENCY",
                f"glmocr {self._sdk_version} does not accept the arena's constructor "
                "arguments; the SDK revision and runtime.json disagree",
            ) from exc
        except ImportError as exc:
            # glmocr/layout/__init__.py turns an ImportError from layout_detector
            # into a deferred one raised here, when Pipeline() is built.
            raise AdapterError(
                "DEPENDENCY",
                f"glmocr {self._sdk_version} could not build its self-hosted pipeline: {exc}",
            ) from exc
        self._verify_resolved_config(self._parser)
        return self._parser

    def _layout_device(self) -> str:
        return str(self._config.get("layout_device", "cuda:0"))

    def _layout_model_dir(self) -> str:
        return resolve_layout_model_dir(self._config)

    def _write_sdk_config(self) -> Path:
        """Render ``sdk_config()`` to the YAML file ``GlmOcr(config_path=...)`` reads.

        The SDK has no dict entry point. ``load_config(path, **overrides)`` merges a
        YAML document under a fixed set of named overrides, and the README's
        self-hosted section says to edit the YAML; this writes that YAML instead of
        editing the copy inside the installed wheel.
        """
        if self._config_path is not None:
            return self._config_path
        # Imported here, not at module scope: PyYAML is a glmocr dependency, and
        # this module must stay importable without the SDK's stack.
        import yaml

        directory = Path(tempfile.mkdtemp(prefix="arena-glmocr-"))
        path = directory / "config.yaml"
        path.write_text(
            yaml.safe_dump(self.sdk_config(), sort_keys=True, allow_unicode=False),
            encoding="utf-8",
        )
        self._config_dir = directory
        self._config_path = path
        return path

    def _verify_resolved_config(self, parser: Any) -> None:
        """Prove the SDK resolved what this adapter asked for, or fail closed.

        ``load_config`` also reads ``GLMOCR_*`` environment variables, a ``.env``
        file and the shipped ``config.yaml``, and ``GlmOcr.__init__`` flips to MaaS
        on its own when it finds ``ZHIPU_API_KEY``/``GLMOCR_API_KEY``. A config that
        did not take looks exactly like one that did, so the two rails in the module
        docstring are read back off ``GlmOcr.config_model`` rather than assumed.
        """
        pipeline = getattr(getattr(parser, "config_model", None), "pipeline", None)
        if pipeline is None:
            raise AdapterError(
                "DEPENDENCY",
                f"glmocr {self._sdk_version} exposes no config_model.pipeline, so this "
                "adapter cannot verify that MaaS is off and the layout model is local",
            )
        wanted = self.sdk_config()["pipeline"]
        maas_enabled = getattr(getattr(pipeline, "maas", None), "enabled", None)
        if maas_enabled is not False:
            raise AdapterError(
                "MODEL_LOAD",
                f"glmocr resolved pipeline.maas.enabled={maas_enabled!r}: MaaS mode "
                "forwards every page to Zhipu's hosted API instead of the local server",
            )
        checks: tuple[tuple[str, str, Any], ...] = (
            ("ocr_api", "api_host", wanted["ocr_api"]["api_host"]),
            ("ocr_api", "api_port", wanted["ocr_api"]["api_port"]),
            ("ocr_api", "retry_max_attempts", 0),
            ("layout", "model_dir", wanted["layout"]["model_dir"]),
            ("page_loader", "task_prompt_mapping", wanted["page_loader"]["task_prompt_mapping"]),
        )
        for section, key, expected in checks:
            observed = getattr(getattr(pipeline, section, None), key, None)
            if isinstance(expected, dict):
                observed = dict(observed) if isinstance(observed, Mapping) else observed
            if observed != expected:
                raise AdapterError(
                    "MODEL_LOAD",
                    f"glmocr resolved {section}.{key}={observed!r}, this runtime asked "
                    f"for {expected!r}; the config file did not take",
                )

    def close(self) -> None:
        parser = self._parser
        self._parser = None
        if parser is not None:
            closer = getattr(parser, "close", None)
            if callable(closer):
                # The self-hosted pipeline runs worker threads; dropping the
                # reference alone leaves them behind.
                closer()
        if self._config_dir is not None:
            shutil.rmtree(self._config_dir, ignore_errors=True)
            self._config_dir = None
            self._config_path = None

    def sdk_config(self) -> dict[str, Any]:
        """Build the SDK's own config dict from the frozen inference_config.

        Every value here is a glmocr/config.yaml key. Deviations from the SDK's
        shipped defaults are exactly two and both are recorded in runtime.json:
        ``maas.enabled`` false and ``retry_max_attempts`` 0.
        """
        config = self._config
        return {
            "pipeline": {
                "maas": {"enabled": False},
                "ocr_api": {
                    "api_host": config.get("api_host", "127.0.0.1"),
                    "api_port": config.get("api_port", 8080),
                    "api_path": config.get("api_path", "/v1/chat/completions"),
                    "api_mode": "openai",
                    "model": config.get("served_model_name", OFFICIAL_SERVED_MODEL_NAME),
                    "request_timeout": config.get("request_timeout", 120),
                    "retry_max_attempts": 0,
                },
                "max_workers": config.get("max_workers", 8),
                "page_loader": {
                    "max_tokens": config.get("max_tokens", 8192),
                    "temperature": config.get("temperature", 0.0),
                    "top_p": config.get("top_p", 0.00001),
                    "top_k": config.get("top_k", 1),
                    "repetition_penalty": config.get("repetition_penalty", 1.1),
                    "min_pixels": config.get("min_pixels", 12544),
                    "max_pixels": config.get("max_pixels", 71372800),
                    "image_expect_length": config.get("image_expect_length", 6144),
                    "image_format": config.get("image_format", "JPEG"),
                    "t_patch_size": config.get("t_patch_size", 2),
                    "patch_expand_factor": config.get("patch_expand_factor", 1),
                    "task_prompt_mapping": dict(OFFICIAL_TASK_PROMPTS),
                },
                "layout": {
                    "model_dir": self._layout_model_dir(),
                    "threshold": config.get("layout_threshold", 0.3),
                    "batch_size": config.get("layout_batch_size", 1),
                    "workers": 1,
                },
                "result_formatter": {"output_format": config.get("output_format", "both")},
            }
        }

    def parse_page(self, image_path: Path, timeout_s: float) -> SdkPageResult:
        parser = self._ensure_parser()
        started = time.monotonic()
        try:
            result = parser.parse(str(image_path))
        except Exception as exc:  # broad on purpose: mapped onto the arena taxonomy
            raise AdapterError(
                "POSTPROCESS", f"glmocr pipeline raised {type(exc).__name__}"
            ) from exc
        markdown = _first_str(result, ("markdown", "md_result", "markdown_result"))
        if markdown is None:
            raise AdapterError("POSTPROCESS", "glmocr result carried no markdown")
        json_result = getattr(result, "json_result", None)
        return SdkPageResult(
            markdown=markdown,
            json_result=json_result if isinstance(json_result, Mapping) else None,
            usage={},
            stage_timings_ms={"pipeline_ms": int((time.monotonic() - started) * 1000)},
        )

    def describe(self) -> Mapping[str, Any]:
        return {
            "pipeline": "glmocr.GlmOcr (self-hosted)",
            "sdk_repository": self._config.get("sdk_repository"),
            "sdk_revision": self._config.get("sdk_revision"),
            "sdk_version": self._sdk_version,
            "layout_model_repo": self._config.get("layout_model_repo"),
            "layout_model_revision": self._config.get("layout_model_revision"),
            "layout_model_dir": self._layout_model_dir(),
            "layout_device": self._layout_device(),
            "sdk_config_path": str(self._config_path) if self._config_path else None,
            "maas_enabled": False,
        }


def _first_str(obj: Any, names: tuple[str, ...]) -> str | None:
    for name in names:
        value = getattr(obj, name, None)
        if isinstance(value, str):
            return value
    return None


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


def weights_manifest_sha256(weights_dir: Path, sidecar: Mapping[str, Any], *, deep: bool) -> str:
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


def resolve_layout_model_dir(config: Mapping[str, Any]) -> str:
    """Where the PP-DocLayoutV3 checkpoint is on *this* pod.

    ``runtime.json``'s ``inference_config`` is frozen and hashed, so it holds one
    path: the baked ``/opt/arena/weights/...``. The bootstrap path cannot use it --
    the bundle template unpacks to ``/opt/arena`` and ``bootstrap.sh`` fetches both
    checkpoints under ``/workspace`` -- so it exports ``ARENA_LAYOUT_DIR``, exactly
    as ``ARENA_WEIGHTS_DIR`` moves the primary weights for the worker. Reading the
    override here is what keeps one frozen config valid in both runtime modes.

    This is the 2026-09-03 pod jdwdnvg8a2rzx6 failure: vLLM came up, and ``load``
    then looked for the layout model under the baked path while the file sat in the
    bootstrap one.
    """
    override = (os.environ.get(LAYOUT_DIR_ENV) or "").strip()
    if override:
        return override
    directory = config.get("layout_model_dir")
    return directory.strip() if isinstance(directory, str) else ""


def verify_layout_model(config: Mapping[str, Any]) -> Mapping[str, Any]:
    """Check the second model the SDK pipeline depends on, or fail closed.

    PP-DocLayoutV3 is a separate checkpoint with a separate Apache-2.0 licence. It is
    pinned and hashed like the primary model; serving with an unpinned layout model
    would make the pipeline unreproducible while looking fine.
    """
    directory = resolve_layout_model_dir(config)
    expected = config.get("layout_model_largest_file_sha256")
    name = config.get("layout_model_largest_file")
    if not directory or not isinstance(expected, str) or not isinstance(name, str):
        raise AdapterError(
            "MODEL_LOAD",
            "inference_config does not pin the PP-DocLayoutV3 layout model the SDK needs",
        )
    path = Path(directory) / name
    if not path.is_file():
        raise AdapterError("MODEL_LOAD", f"layout model file {name} is missing under {directory}")
    observed = file_sha256(path)
    if observed != expected:
        raise AdapterError(
            "CHECKSUM", f"layout model {name} hashes to {observed}, runtime.json pinned {expected}"
        )
    return {
        "repo": config.get("layout_model_repo"),
        "revision": config.get("layout_model_revision"),
        "model_dir": directory,
        "largest_file": name,
        "largest_file_sha256": observed,
        "license": "Apache-2.0 (separate from the MIT model licence)",
    }


class GlmOcrAdapter:
    """``ArenaModelAdapter`` for zai-org/GLM-OCR through the official SDK."""

    model_key = MODEL_KEY

    def __init__(self, pipeline: GlmOcrPipeline | None = None) -> None:
        self._pipeline = pipeline
        self._cfg: AdapterConfig | None = None
        self._layout_provenance: Mapping[str, Any] | None = None
        self._prompt_sha256: str | None = None

    def load(self, cfg: AdapterConfig) -> LoadReceipt:
        started = time.monotonic()
        if cfg.model_repo != MODEL_REPO:
            raise AdapterError(
                "MODEL_LOAD",
                f"adapter is pinned to {MODEL_REPO}, was asked for {cfg.model_repo}",
            )
        if cfg.inference_config.get("maas_enabled"):
            raise AdapterError(
                "MODEL_LOAD",
                "maas_enabled is true: MaaS mode forwards every page to Zhipu's hosted "
                "API instead of running the open model, and no adapter decides that",
            )
        # D34 prompt_kind=toolkit: the task-prompt mapping this adapter hands the SDK
        # must hash to the registry entry for prompt_id. Byte-exact per D8.
        built_prompt = build_official_prompt_text()
        built_sha256 = hashlib.sha256(built_prompt.encode("utf-8")).hexdigest()
        expected_sha256 = registered_prompt_sha256(cfg)
        if built_sha256 != expected_sha256:
            raise AdapterError(
                "MODEL_LOAD",
                f"prompt_kind={PROMPT_KIND}: the glmocr task prompts this adapter sends "
                f"hash to sha256:{built_sha256}, registry {cfg.prompt_id!r} recorded "
                f"sha256:{expected_sha256}; a prompt drift is a different experiment",
            )
        self._prompt_sha256 = built_sha256
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
        self._layout_provenance = verify_layout_model(cfg.inference_config)
        if self._pipeline is None:
            self._pipeline = OfficialSdkPipeline(cfg.inference_config)
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
            schema_valid=raw.output_format == "markdown",
            peak_vram_mb=raw.peak_vram_mb,
        )

    def infer(self, page: PageInput) -> RawOutput:
        cfg = self._require_cfg()
        timeout = float(cfg.inference_config.get("request_timeout", 120))
        return self._infer_path(page.image_path, timeout_s=timeout)

    def runtime_provenance(self) -> Mapping[str, Any]:
        provenance: dict[str, Any] = {
            "model_key": MODEL_KEY,
            "model_repo": MODEL_REPO,
            "official_runtime": "glmocr SDK (self-hosted) against a vLLM server",
        }
        if self._pipeline is not None:
            provenance["pipeline"] = dict(self._pipeline.describe())
        if self._layout_provenance is not None:
            provenance["layout_model"] = dict(self._layout_provenance)
        provenance["prompt_kind"] = PROMPT_KIND
        provenance["task_prompt_mapping"] = dict(OFFICIAL_TASK_PROMPTS)
        if self._prompt_sha256 is not None:
            provenance["prompt_sha256"] = f"sha256:{self._prompt_sha256}"
        if self._cfg is not None:
            provenance["prompt_id"] = self._cfg.prompt_id
            provenance["inference_config_sha256"] = self._cfg.inference_config_sha256
        return provenance

    def close(self) -> None:
        pipeline = self._pipeline
        self._pipeline = None
        self._cfg = None
        # The official pipeline owns SDK worker threads and a rendered config file.
        closer = getattr(pipeline, "close", None)
        if callable(closer):
            closer()

    # -- internals ---------------------------------------------------------

    def _require_cfg(self) -> AdapterConfig:
        if self._cfg is None or self._pipeline is None:
            raise AdapterError("MODEL_LOAD", "adapter used before load() completed")
        return self._cfg

    def _infer_path(self, image_path: Path, *, timeout_s: float) -> RawOutput:
        self._require_cfg()
        pipeline = self._pipeline
        if pipeline is None:  # pragma: no cover - guarded above
            raise AdapterError("MODEL_LOAD", "adapter used before load() completed")
        if not image_path.is_file():
            raise AdapterError("INPUT_DECODE", f"page image {image_path.name} is missing")

        started = time.monotonic()
        result = pipeline.parse_page(image_path, timeout_s)
        elapsed_ms = int((time.monotonic() - started) * 1000)

        warnings: list[str] = []
        semantic = classify_output(result.markdown)
        if semantic is not None:
            warnings.append(f"{SEMANTIC_ERROR_PREFIX}{semantic}")
        if result.json_result is None:
            warnings.append("glmocr returned no json_result for this page")

        stage = dict(result.stage_timings_ms)
        return RawOutput(
            raw_text=result.markdown,
            output_format="markdown",
            native_json=result.json_result,
            usage=dict(result.usage),
            timings_ms={
                "preprocess_ms": int(stage.get("preprocess_ms", 0)),
                "inference_ms": int(stage.get("pipeline_ms", elapsed_ms)),
                "postprocess_ms": int(stage.get("postprocess_ms", 0)),
            },
            peak_vram_mb=None,
            first_token_at=None,
            warnings=tuple(warnings),
            semantic_error_class=semantic,
        )


__all__ = [
    "LAYOUT_DIR_ENV",
    "OFFICIAL_TASK_PROMPTS",
    "PROMPT_KIND",
    "GlmOcrAdapter",
    "GlmOcrPipeline",
    "OfficialSdkPipeline",
    "SdkPageResult",
    "build_official_prompt_text",
    "classify_output",
    "read_weights_sidecar",
    "registered_prompt_sha256",
    "resolve_layout_model_dir",
    "verify_layout_model",
    "weights_manifest_sha256",
]
