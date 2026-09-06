"""MinerU 3.4.x pipeline-backend arena adapter.

The official entrypoint is the ``mineru`` CLI. Spawning it once per page would
reload every pipeline model on every page, so this adapter calls the function
the CLI itself calls - ``mineru.cli.common.do_parse`` - in the worker process,
where MinerU's ``ModelSingleton`` keeps the models warm across pages. Same code
path, same parameters, one load.

MinerU takes PDF bytes; ``mineru.cli.common.read_fn`` is the documented
image-to-single-page-PDF converter and is used here, unmodified.

D59 (2026-09-04, real canary pod eymd8t51r6597g): ``read_fn``'s own
``image_suffixes``/``pdf_suffixes`` lists in ``mineru/cli/common.py`` are
declared *without* a leading dot (``"png"``, not ``".png"``) -- every caller
in MinerU's own CLI resolves a suffix the same dotless way, via
``guess_suffix_by_path``/``guess_suffix_by_bytes``. ``Path.suffix`` keeps the
dot, so passing it straight through raised MinerU's own
``Exception(f"Unknown file suffix: {file_suffix}")`` on every page. See
``_mineru_file_suffix`` below.

Heavy imports live inside the default backend factory. This module imports on a
CPU box with no torch and no mineru.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
import tempfile
import time
from collections.abc import Callable, Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

from arena.worker.adapter_api import (
    AdapterConfig,
    AdapterError,
    LoadReceipt,
    PageInput,
    RawOutput,
    WarmupReceipt,
)

MODEL_KEY = "mineru_pipeline"
REVISION_STAMP = "arena-weights-revision.txt"

# ARENA_CONTRACT D34 - prompt_kind "none".
#
# The MinerU pipeline backend takes no prompt: nothing in this file sends one and there is
# no text to reproduce. The registry file for runtime.json's prompt_id is
# therefore the empty file (sha256 of the empty string), and ``load()`` refuses
# a non-empty ``AdapterConfig.prompt_text`` rather than quietly leaving the
# official path.
OFFICIAL_PROMPT = ""
PROMPT_KIND = "none"


@lru_cache(maxsize=1)
def runtime_spec() -> Mapping[str, Any]:
    path = Path(__file__).with_name("runtime.json")
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise AdapterError("DEPENDENCY", f"{path} must hold a JSON object")
    return document


@lru_cache(maxsize=1)
def provenance_spec() -> Mapping[str, Any]:
    """The co-located provenance.json.

    runtime.json is validated against a closed schema, so resolution
    provenance, the upstream version discrepancy and the open questions live
    beside it rather than being dropped.
    """
    path = Path(__file__).with_name("provenance.json")
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise AdapterError("DEPENDENCY", f"{path} must hold a JSON object")
    return document


class MineruBackend(Protocol):
    """The narrow surface the adapter needs from MinerU."""

    def start(self) -> Mapping[str, Any]:
        """Load the pipeline models once; return provenance."""

    def parse(self, image_path: Path, output_dir: Path, stem: str) -> None:
        """Run one page; MinerU writes its own files under output_dir/stem/."""

    def close(self) -> None: ...


def _mineru_file_suffix(path: Path) -> str:
    """The file-suffix token ``mineru.cli.common.read_fn`` actually recognises.

    D59: ``read_fn``'s own ``image_suffixes``/``pdf_suffixes``/``office_suffixes``
    lists hold bare tokens ("png", "pdf" - never ".png", ".pdf"), matching what
    MinerU's own CLI always passes via ``guess_suffix_by_path``. ``Path.suffix``
    keeps the leading dot, so it is stripped here rather than passed through.
    """
    return path.suffix.lower().lstrip(".")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def weights_manifest_sha256(weights_dir: Path) -> str:
    rows = [
        (path.relative_to(weights_dir).as_posix(), sha256_file(path))
        for path in sorted(weights_dir.rglob("*"))
        if path.is_file()
    ]
    payload = json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def verify_weights(weights_dir: Path, expected_revision: str) -> tuple[str, bool]:
    """Fail closed unless the baked model tree is the pinned repository revision."""
    if not weights_dir.is_dir():
        raise AdapterError("MODEL_LOAD", f"weights directory {weights_dir} does not exist")
    stamp = weights_dir / REVISION_STAMP
    if not stamp.is_file():
        raise AdapterError(
            "MODEL_LOAD",
            f"{stamp} is missing; the image did not record which revision it baked",
        )
    recorded = stamp.read_text(encoding="utf-8").strip()
    if recorded != expected_revision:
        raise AdapterError(
            "MODEL_LOAD",
            f"weights revision mismatch: baked {recorded!r}, expected {expected_revision!r}",
        )
    weights = runtime_spec()["weights"]
    largest = weights_dir / str(weights["largest_file"])
    if not largest.is_file():
        raise AdapterError("MODEL_LOAD", f"pinned weight file {largest} is missing")
    observed = f"sha256:{sha256_file(largest)}"
    if observed != weights["largest_file_sha256"]:
        raise AdapterError(
            "MODEL_LOAD",
            f"{weights['largest_file']} digest mismatch: {observed} != "
            f"{weights['largest_file_sha256']}",
        )
    cache_hit = os.environ.get("ARENA_WEIGHTS_CACHE_HIT", "").lower() in {"1", "true", "yes"}
    return weights_manifest_sha256(weights_dir), cache_hit


def classify_exception(exc: BaseException) -> str:
    text = f"{type(exc).__name__}: {exc}".lower()
    if isinstance(exc, TimeoutError) or "timed out" in text or "timeout" in text:
        return "INFERENCE_TIMEOUT"
    if "out of memory" in text or "cuda oom" in text:
        return "CUDA_OOM"
    if "cuda" in text and "initializ" in text:
        return "CUDA_INIT"
    if "shape" in text and ("mismatch" in text or "invalid" in text or "size" in text):
        return "TENSOR_SHAPE"
    if isinstance(exc, (ValueError, TypeError, KeyError)):
        return "OUTPUT_MALFORMED"
    if isinstance(exc, OSError):
        return "INFRA_NETWORK"
    return "UNKNOWN"


def _find_one(case_dir: Path, suffix: str, stem: str) -> Path | None:
    """The single ``<stem><suffix>`` file under the case dir, or None.

    MinerU writes into ``<output>/<stem>/<parse_method>/``; the parse-method
    directory is not hardcoded here so the same reader works for every backend.
    Two matches are an error, never a silent pick.
    """
    wanted = f"{stem}{suffix}"
    candidates = sorted(
        path for path in case_dir.rglob("*") if path.is_file() and path.name == wanted
    )
    if len(candidates) > 1:
        raise AdapterError(
            "POSTPROCESS", f"MinerU wrote {len(candidates)} files named {wanted!r}"
        )
    return candidates[0] if candidates else None


def read_outputs(case_dir: Path, stem: str) -> tuple[str, dict[str, Any]]:
    """(markdown, native_json) from MinerU's own output files."""
    markdown_path = _find_one(case_dir, ".md", stem)
    if markdown_path is None:
        raise AdapterError("POSTPROCESS", f"MinerU wrote no markdown for {stem!r}")
    markdown = markdown_path.read_text(encoding="utf-8")
    native: dict[str, Any] = {}
    for key, suffix in (
        ("middle_json", "_middle.json"),
        ("model_json", "_model.json"),
        ("content_list", "_content_list.json"),
        ("content_list_v2", "_content_list_v2.json"),
    ):
        path = _find_one(case_dir, suffix, stem)
        if path is None:
            native[key] = None
            continue
        try:
            native[key] = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise AdapterError("OUTPUT_MALFORMED", f"{path.name} is not valid JSON: {exc}") from exc
    return markdown, native


class _OfficialMineruBackend:
    """``do_parse`` with the pipeline backend. GPU pod only."""

    def __init__(self, cfg: AdapterConfig) -> None:
        self._cfg = cfg
        self._do_parse: Any = None
        self._read_fn: Any = None

    def start(self) -> Mapping[str, Any]:
        config = self._cfg.inference_config
        for key, value in dict(config["env"]).items():
            os.environ[str(key)] = str(value)

        # Only present inside the runtime image; mypy runs on a CPU box.
        from mineru.cli.common import (  # type: ignore[import-not-found]
            do_parse,
            read_fn,
        )

        self._do_parse = do_parse
        self._read_fn = read_fn
        return {
            "entrypoint": "mineru.cli.common.do_parse",
            "backend": config["backend"],
            "parse_method": config["parse_method"],
            "env": {str(k): str(v) for k, v in dict(config["env"]).items()},
        }

    def parse(self, image_path: Path, output_dir: Path, stem: str) -> None:
        if self._do_parse is None or self._read_fn is None:
            raise AdapterError("MODEL_LOAD", "MinerU backend was never started")
        config = self._cfg.inference_config
        pdf_bytes = self._read_fn(image_path, _mineru_file_suffix(image_path))
        self._do_parse(
            output_dir=str(output_dir),
            pdf_file_names=[stem],
            pdf_bytes_list=[pdf_bytes],
            p_lang_list=[str(config["lang"])],
            backend=str(config["backend"]),
            parse_method=str(config["parse_method"]),
            formula_enable=bool(config["formula_enable"]),
            table_enable=bool(config["table_enable"]),
            f_draw_layout_bbox=bool(config["f_draw_layout_bbox"]),
            f_draw_span_bbox=bool(config["f_draw_span_bbox"]),
            f_dump_md=bool(config["f_dump_md"]),
            f_dump_middle_json=bool(config["f_dump_middle_json"]),
            f_dump_model_output=bool(config["f_dump_model_output"]),
            f_dump_orig_pdf=bool(config["f_dump_orig_pdf"]),
            f_dump_content_list=bool(config["f_dump_content_list"]),
        )

    def close(self) -> None:
        self._do_parse = None
        self._read_fn = None


def _default_backend_factory(cfg: AdapterConfig) -> MineruBackend:
    return _OfficialMineruBackend(cfg)


class MineruPipelineAdapter:
    """Implements ``arena.worker.adapter_api.ArenaModelAdapter``."""

    model_key = MODEL_KEY

    def __init__(
        self,
        backend_factory: Callable[[AdapterConfig], MineruBackend] | None = None,
    ) -> None:
        self._backend_factory = backend_factory or _default_backend_factory
        self._backend: MineruBackend | None = None
        self._cfg: AdapterConfig | None = None
        self._provenance: dict[str, Any] = {}

    def load(self, cfg: AdapterConfig) -> LoadReceipt:
        if cfg.model_key != MODEL_KEY:
            raise AdapterError("MODEL_LOAD", f"adapter is {MODEL_KEY}, got {cfg.model_key}")
        spec = runtime_spec()
        if cfg.model_repo != spec["model_repo"]:
            raise AdapterError(
                "MODEL_LOAD",
                f"model_repo mismatch: {cfg.model_repo!r} != {spec['model_repo']!r}",
            )
        if cfg.prompt_text:
            raise AdapterError(
                "MODEL_LOAD",
                "the MinerU pipeline backend takes no prompt; a non-empty prompt would "
                "leave the official path",
            )
        started = time.perf_counter()
        manifest, cache_hit = verify_weights(cfg.weights_dir, cfg.model_revision)
        try:
            backend = self._backend_factory(cfg)
            backend_provenance = backend.start()
        except AdapterError:
            raise
        except Exception as exc:
            raise AdapterError("MODEL_LOAD", f"{type(exc).__name__}: {exc}") from exc
        self._backend = backend
        self._cfg = cfg
        provenance = provenance_spec()
        self._provenance = {
            "model_key": MODEL_KEY,
            "official_runtime": spec["official_runtime"],
            "runtime_version": spec["runtime_version"],
            "runtime_source_repository": provenance.get("runtime_source_repository"),
            "runtime_source_revision": provenance.get("runtime_source_revision"),
            "upstream_version_discrepancy": dict(
                provenance.get("upstream_version_discrepancy", {})
            ),
            "base_image": spec["base_image"],
            "base_image_digest": os.environ.get(
                "ARENA_IMAGE_DIGEST", provenance.get("base_image_digest")
            ),
            "runtime_mode": os.environ.get("ARENA_RUNTIME_MODE"),
            "python": sys.version,
            "platform": platform.platform(),
            "backend": dict(backend_provenance),
            "packages": _package_versions(),
        }
        return LoadReceipt(
            model_key=MODEL_KEY,
            model_repo=cfg.model_repo,
            model_revision=cfg.model_revision,
            weights_sha256_manifest=f"sha256:{manifest}",
            load_ms=int((time.perf_counter() - started) * 1000),
            cache_hit=cache_hit,
            runtime_provenance=dict(self._provenance),
        )

    def warmup(self, synthetic_image: Path) -> WarmupReceipt:
        started = time.perf_counter()
        page = PageInput(
            inference_job_id="warmup",
            sample_id="warmup:synthetic",
            case_key="warmup-synthetic",
            benchmark="omnidoc",
            image_path=synthetic_image,
            source_sha256=f"sha256:{sha256_file(synthetic_image)}",
            width=0,
            height=0,
            metadata={"page_index": 0, "media_type": "png"},
        )
        raw = self.infer(page)
        return WarmupReceipt(
            warmup_ms=int((time.perf_counter() - started) * 1000),
            output_chars=len(raw.raw_text),
            schema_valid=raw.output_format == "markdown",
            peak_vram_mb=raw.peak_vram_mb,
        )

    def infer(self, page: PageInput) -> RawOutput:
        backend = self._backend
        if backend is None:
            raise AdapterError("MODEL_LOAD", "infer() called before load()")
        if not page.image_path.is_file():
            raise AdapterError("INPUT_DECODE", f"page image {page.image_path} does not exist")
        stem = page.case_key
        started = time.perf_counter()
        with tempfile.TemporaryDirectory(prefix="arena-mineru-") as workdir:
            output_dir = Path(workdir)
            try:
                backend.parse(page.image_path, output_dir, stem)
            except AdapterError:
                raise
            except Exception as exc:
                raise AdapterError(classify_exception(exc), f"{type(exc).__name__}: {exc}") from exc
            inference_ms = int((time.perf_counter() - started) * 1000)
            case_dir = output_dir / stem
            if not case_dir.is_dir():
                raise AdapterError(
                    "POSTPROCESS", f"MinerU produced no output directory for {stem!r}"
                )
            markdown, native = read_outputs(case_dir, stem)

        warnings: list[str] = []
        if not markdown.strip():
            warnings.append("empty_output")
        for key in ("middle_json", "model_json", "content_list"):
            if native.get(key) is None:
                warnings.append(f"missing_{key}")
        # ARENA_CONTRACT D3. MinerU returns a finished document rather than a
        # token stream, so an empty markdown body is the only semantic verdict
        # this adapter can see without inferring one. A missing side-car dump
        # stays a warning: the markdown itself is still what the model produced.
        semantic_error_class = "OUTPUT_EMPTY" if not markdown.strip() else None
        return RawOutput(
            raw_text=markdown,
            output_format="markdown",
            native_json=native,
            usage={},
            timings_ms={
                "preprocess_ms": 0,
                "inference_ms": inference_ms,
                "postprocess_ms": 0,
            },
            peak_vram_mb=None,
            first_token_at=None,
            warnings=tuple(warnings),
            semantic_error_class=semantic_error_class,
        )

    def runtime_provenance(self) -> Mapping[str, Any]:
        return dict(self._provenance)

    def close(self) -> None:
        backend = self._backend
        self._backend = None
        self._cfg = None
        if backend is not None:
            backend.close()


def _package_versions() -> dict[str, str | None]:
    import importlib.metadata

    versions: dict[str, str | None] = {}
    for name in ("mineru", "torch", "torchvision", "transformers", "onnxruntime", "vllm"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def create_adapter(
    backend_factory: Callable[[AdapterConfig], MineruBackend] | None = None,
) -> MineruPipelineAdapter:
    return MineruPipelineAdapter(backend_factory=backend_factory)
