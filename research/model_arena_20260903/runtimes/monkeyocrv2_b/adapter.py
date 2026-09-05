"""MonkeyOCRv2-B-Parsing adapter — drives the official parsing pipeline.

Official sources (resolved 2026-09-03):

- https://huggingface.co/zenosai/MonkeyOCRv2-B-Parsing @
  ``de7a993bd0f39a97b122dac767e82ae04935bce4``
- https://github.com/Yuliang-Liu/MonkeyOCRv2 @
  ``d46699fb6a4c71d61588e4a71fce03bff4f1ba33`` — ``parsing/serve.py`` starts vLLM
  with the model's own registration module, ``parsing/parse.py`` drives
  ``parsing/core_runner.py::run_pipeline``, and the recognition prompts live in
  ``core_runner.ALL_PROMPT``.

The document-parsing path is two stages: a layout pass over the whole page, then
per-block recognition with the block's own prompt. Reimplementing that here would
mean inventing a prompt the vendor did not publish, so this adapter **calls the
vendor's own pipeline** and only owns the arena's bookkeeping around it.

``core_runner`` imports torch and PIL, so it is loaded inside
:meth:`MonkeyOcrV2BAdapter.load` through an injectable collaborator. Nothing heavy
is imported at module scope and tests substitute a fake pipeline.
"""

from __future__ import annotations

import hashlib
import itertools
import json
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

MODEL_KEY = "monkeyocrv2_b"
MODEL_REPO = "zenosai/MonkeyOCRv2-B-Parsing"
WEIGHTS_SIDECAR_NAME = ".arena_weights.json"
SEMANTIC_ERROR_PREFIX = "arena.semantic_error_class="
REPETITION_RUN_THRESHOLD = 12

#: parse.py v2 default. Larger pages are downscaled by the official preprocessor.
OFFICIAL_MAX_PIXELS = 1003520
#: serve.py v2 default.
OFFICIAL_SERVED_MODEL_NAME = "MonkeyOCRv2"
#: run_pipeline writes ``<out>/markdowns/<stem>.md`` and ``<out>/jsons/<stem>.json``.
MARKDOWN_SUBDIR = "markdowns"
JSON_SUBDIR = "jsons"

#: ARENA_CONTRACT D34. MonkeyOCRv2's parsing path is not driven by one prompt: the
#: vendor's ``parsing/core_runner.py`` holds a per-element mapping (``ALL_PROMPT``)
#: and picks a prompt per detected block. This adapter never reimplements those
#: strings -- it reads them out of the installed toolkit and refuses to serve when
#: they do not hash to the registry entry for ``prompt_id``.
PROMPT_KIND = "toolkit"

#: The one symbol that produces the prompt bytes for this revision.
TOOLKIT_PROMPT_SYMBOL = "core_runner.ALL_PROMPT"


@dataclass(frozen=True, slots=True)
class PipelinePageResult:
    """One page as the official pipeline produced it."""

    markdown: str
    content_json: Mapping[str, Any] | None
    usage: Mapping[str, Any] = field(default_factory=dict)
    stage_timings_ms: Mapping[str, int] = field(default_factory=dict)


def render_prompt_mapping(mapping: Mapping[str, str]) -> str:
    """Render a task-prompt mapping into the exact bytes the registry file holds.

    The rendering is the one lane R already wrote into
    ``prompt_registry/monkeyocrv2_b_official_pipeline_prompts_v1.txt``: the
    ARENA_CONTRACT section 2 canonical JSON of the mapping -- ``sort_keys=True``,
    ``separators=(",", ":")``, ``ensure_ascii=True``, no trailing
    newline. Escaping non-ASCII is what makes the bytes independent of the reader's
    encoding; the pinned mapping happens to be pure ASCII, so this pins the rule
    before a non-ASCII block prompt upstream can make the two renderings disagree.
    Sorting rather than following the dict's own order means a cosmetic
    reordering upstream does not read as prompt drift, while any change to a prompt
    string still does.

    For ``core_runner.ALL_PROMPT`` at runtime revision
    ``d46699fb6a4c71d61588e4a71fce03bff4f1ba33`` the result is 831 bytes and hashes to
    ``sha256:3384d4732fd91113b9f7989e488dba575f65225d745a30b797364e12df47dca4``
    (11 keys: Caption, END2END, Formula, LAYOUT, List-item, Page-footer, Page-header,
    Section-header, Table, Text, Title), which is what ``prompt_registry/sha256.json``
    records for this prompt_id.
    """

    if not mapping:
        raise AdapterError(
            "DEPENDENCY", f"{TOOLKIT_PROMPT_SYMBOL} is empty; the toolkit is not the pinned one"
        )
    for key in sorted(mapping):
        value = mapping[key]
        if not isinstance(value, str) or not value:
            raise AdapterError(
                "DEPENDENCY", f"{TOOLKIT_PROMPT_SYMBOL}[{key!r}] is not a non-empty string"
            )
    return json.dumps(dict(mapping), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def registered_prompt_sha256(cfg: AdapterConfig) -> str:
    """The registry hash the rendered prompt mapping must match, as bare hex.

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
        f"prompt_text for prompt_id {cfg.prompt_id!r}, so {TOOLKIT_PROMPT_SYMBOL} "
        "cannot be verified against the registry",
    )


@runtime_checkable
class ToolkitPromptSource(Protocol):
    """Reads the prompt mapping out of the installed toolkit, or a test double."""

    def build_prompt_text(self) -> str: ...

    def describe(self) -> Mapping[str, Any]: ...


class CoreRunnerPromptSource:
    """Reads ``core_runner.ALL_PROMPT`` from the vendor package on PYTHONPATH."""

    def __init__(self) -> None:
        self._keys: tuple[str, ...] = ()

    def build_prompt_text(self) -> str:
        try:
            import core_runner  # type: ignore[import-not-found]
        except ImportError as exc:
            raise AdapterError(
                "DEPENDENCY",
                "MonkeyOCRv2 parsing/core_runner is not importable; "
                "the image must put parsing/ on PYTHONPATH",
            ) from exc
        mapping = getattr(core_runner, "ALL_PROMPT", None)
        if not isinstance(mapping, Mapping):
            raise AdapterError(
                "DEPENDENCY", f"{TOOLKIT_PROMPT_SYMBOL} is missing or not a mapping"
            )
        self._keys = tuple(sorted(mapping))
        return render_prompt_mapping(mapping)

    def describe(self) -> Mapping[str, Any]:
        return {"source": TOOLKIT_PROMPT_SYMBOL, "element_types": list(self._keys)}


@runtime_checkable
class ParsingPipeline(Protocol):
    """The official MonkeyOCRv2 parsing pipeline, or a test double for it."""

    def parse_page(self, image_path: Path, timeout_s: float) -> PipelinePageResult: ...

    def describe(self) -> Mapping[str, Any]: ...


class OfficialParsingPipeline:
    """Calls ``parsing/core_runner.py::run_pipeline`` on a one-image directory.

    This is exactly what ``parsing/parse.py`` does for a single input, minus the
    CLI. It never reimplements a prompt and never post-edits the markdown.
    """

    def __init__(self, weights_dir: Path, config: Mapping[str, Any]) -> None:
        self._weights_dir = weights_dir
        self._config = dict(config)
        self._runner: Any | None = None

    def _load_runner(self) -> Any:
        if self._runner is not None:
            return self._runner
        try:
            # The missing-stub ignore lives on the first import of this module,
            # in CoreRunnerPromptSource.build_prompt_text; a second one is unused.
            import core_runner
        except ImportError as exc:
            raise AdapterError(
                "DEPENDENCY",
                "MonkeyOCRv2 parsing/core_runner is not importable; "
                "the image must put parsing/ on PYTHONPATH",
            ) from exc
        self._runner = core_runner
        return core_runner

    def parse_page(self, image_path: Path, timeout_s: float) -> PipelinePageResult:
        core_runner = self._load_runner()
        started = time.monotonic()
        workdir = Path(tempfile.mkdtemp(prefix="arena-monkey-"))
        try:
            input_dir = workdir / "in"
            output_dir = workdir / "out"
            input_dir.mkdir(parents=True)
            staged = input_dir / image_path.name
            shutil.copyfile(image_path, staged)

            backend_config = core_runner.BackendConfig(
                model_path=str(self._weights_dir),
                server_url=str(self._config.get("server_url", "http://127.0.0.1:8888")),
                served_model_name=str(
                    self._config.get("served_model_name", OFFICIAL_SERVED_MODEL_NAME)
                ),
                max_pixels=int(self._config.get("max_pixels", OFFICIAL_MAX_PIXELS)),
                request_timeout=int(timeout_s),
                http_max_retries=int(self._config.get("http_max_retries", 0)),
                http_retry_backoff=float(self._config.get("http_retry_backoff", 1.0)),
                server_max_inflight=int(self._config.get("server_max_inflight", 1024)),
                preprocess_batch_size=int(self._config.get("preprocess_batch_size", 1)),
                skip_preprocess=bool(self._config.get("skip_preprocess", False)),
            )
            pipeline_config = core_runner.PipelineConfig(
                input_path=str(input_dir),
                output_path=str(output_dir),
                backend=backend_config,
                page_max_inflight=int(self._config.get("page_max_inflight", 1)),
                draw_layout=bool(self._config.get("draw_layout", False)),
                end2end=bool(self._config.get("end2end", False)),
                skip_processed=False,
                retry_repeat=bool(self._config.get("retry_repeat", False)),
                retry_repeat_max_retries=0,
                keep_header_footer=bool(self._config.get("keep_header_footer", True)),
                use_base64=bool(self._config.get("use_base64", False)),
                show_progress_bar=False,
            )
            try:
                core_runner.run_pipeline(pipeline_config)
            except Exception as exc:  # broad on purpose: mapped onto the arena taxonomy
                raise AdapterError(
                    "POSTPROCESS", f"MonkeyOCRv2 pipeline raised {type(exc).__name__}"
                ) from exc
            markdown = _read_single(output_dir / MARKDOWN_SUBDIR, ".md")
            content_json = _read_single_json(output_dir / JSON_SUBDIR)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
        return PipelinePageResult(
            markdown=markdown,
            content_json=content_json,
            usage={},
            stage_timings_ms={"pipeline_ms": int((time.monotonic() - started) * 1000)},
        )

    def describe(self) -> Mapping[str, Any]:
        return {
            "pipeline": "MonkeyOCRv2 parsing/core_runner.run_pipeline",
            "runtime_repository": self._config.get("runtime_repository"),
            "runtime_revision": self._config.get("runtime_revision"),
            "server_url": self._config.get("server_url"),
            "end2end": bool(self._config.get("end2end", False)),
            "dflash_enabled": bool(self._config.get("dflash_enabled", False)),
        }


def _read_single(directory: Path, suffix: str) -> str:
    if not directory.is_dir():
        raise AdapterError("POSTPROCESS", f"pipeline produced no {directory.name}/ directory")
    matches = sorted(p for p in directory.iterdir() if p.suffix == suffix and p.is_file())
    if len(matches) != 1:
        raise AdapterError(
            "POSTPROCESS",
            f"expected exactly one {suffix} artifact in {directory.name}/, found {len(matches)}",
        )
    try:
        return matches[0].read_text(encoding="utf-8")
    except OSError as exc:
        raise AdapterError("POSTPROCESS", f"cannot read {matches[0].name}") from exc


def _read_single_json(directory: Path) -> Mapping[str, Any] | None:
    if not directory.is_dir():
        return None
    matches = sorted(p for p in directory.iterdir() if p.suffix == ".json" and p.is_file())
    if len(matches) != 1:
        return None
    try:
        parsed = json.loads(matches[0].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(parsed, dict):
        return parsed
    if isinstance(parsed, list):
        return {"blocks": parsed}
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


class MonkeyOcrV2BAdapter:
    """``ArenaModelAdapter`` for zenosai/MonkeyOCRv2-B-Parsing."""

    model_key = MODEL_KEY

    def __init__(
        self,
        pipeline: ParsingPipeline | None = None,
        prompt_source: ToolkitPromptSource | None = None,
    ) -> None:
        self._pipeline = pipeline
        self._prompt_source = prompt_source
        self._cfg: AdapterConfig | None = None
        self._prompt_sha256: str | None = None

    def load(self, cfg: AdapterConfig) -> LoadReceipt:
        started = time.monotonic()
        if cfg.model_repo != MODEL_REPO:
            raise AdapterError(
                "MODEL_LOAD",
                f"adapter is pinned to {MODEL_REPO}, was asked for {cfg.model_repo}",
            )
        if cfg.inference_config.get("dflash_enabled"):
            raise AdapterError(
                "MODEL_LOAD",
                "dflash_enabled is true: DFlash is a different checkpoint and a different "
                "serving stack (vLLM >= 0.25.1, CUDA >= 12.9) and is out of scope for this "
                "campaign; it is not a drop-in speed setting",
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
        # D34 prompt_kind=toolkit: read the vendor's own prompt mapping and refuse to
        # serve when it does not hash to the registry entry. Byte-exact per D8.
        if self._prompt_source is None:
            self._prompt_source = CoreRunnerPromptSource()
        built_prompt = self._prompt_source.build_prompt_text()
        built_sha256 = hashlib.sha256(built_prompt.encode("utf-8")).hexdigest()
        expected_sha256 = registered_prompt_sha256(cfg)
        if built_sha256 != expected_sha256:
            raise AdapterError(
                "MODEL_LOAD",
                f"prompt_kind={PROMPT_KIND}: {TOOLKIT_PROMPT_SYMBOL} in the installed "
                f"toolkit renders to sha256:{built_sha256}, registry {cfg.prompt_id!r} "
                f"recorded sha256:{expected_sha256}; the pipeline's prompts changed and "
                "that is a different experiment, not a warning",
            )
        self._prompt_sha256 = built_sha256
        if self._pipeline is None:
            self._pipeline = OfficialParsingPipeline(cfg.weights_dir, cfg.inference_config)
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
        timeout = float(cfg.inference_config.get("request_timeout", 300))
        return self._infer_path(page.image_path, timeout_s=timeout)

    def runtime_provenance(self) -> Mapping[str, Any]:
        provenance: dict[str, Any] = {
            "model_key": MODEL_KEY,
            "model_repo": MODEL_REPO,
            "official_runtime": "MonkeyOCRv2 parsing pipeline against a vLLM server",
        }
        if self._pipeline is not None:
            provenance["pipeline"] = dict(self._pipeline.describe())
        provenance["prompt_kind"] = PROMPT_KIND
        if self._prompt_source is not None:
            provenance["prompt_source"] = dict(self._prompt_source.describe())
        if self._prompt_sha256 is not None:
            provenance["prompt_sha256"] = f"sha256:{self._prompt_sha256}"
        if self._cfg is not None:
            provenance["prompt_id"] = self._cfg.prompt_id
            provenance["inference_config_sha256"] = self._cfg.inference_config_sha256
        return provenance

    def close(self) -> None:
        self._pipeline = None
        self._cfg = None

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
        if result.content_json is None:
            warnings.append("pipeline produced no jsons/ artifact for this page")

        stage = dict(result.stage_timings_ms)
        timings: dict[str, int] = {
            "preprocess_ms": int(stage.get("preprocess_ms", 0)),
            "inference_ms": int(stage.get("pipeline_ms", elapsed_ms)),
            "postprocess_ms": int(stage.get("postprocess_ms", 0)),
        }
        return RawOutput(
            raw_text=result.markdown,
            output_format="markdown",
            native_json=result.content_json,
            usage=dict(result.usage),
            timings_ms=timings,
            peak_vram_mb=None,
            first_token_at=None,
            warnings=tuple(warnings),
            semantic_error_class=semantic,
        )


__all__ = [
    "PROMPT_KIND",
    "TOOLKIT_PROMPT_SYMBOL",
    "CoreRunnerPromptSource",
    "MonkeyOcrV2BAdapter",
    "OfficialParsingPipeline",
    "ParsingPipeline",
    "PipelinePageResult",
    "ToolkitPromptSource",
    "classify_output",
    "read_weights_sidecar",
    "registered_prompt_sha256",
    "render_prompt_mapping",
    "weights_manifest_sha256",
]
