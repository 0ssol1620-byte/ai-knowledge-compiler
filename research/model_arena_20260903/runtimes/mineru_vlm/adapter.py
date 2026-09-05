"""MinerU VLM (MinerU2.5-Pro-2605-1.2B) arena adapter.

Masterplan §14 is the reason this file has an extra guard the other runtimes do
not have. In the 2026-08 campaign this runtime ran at worker concurrency 3 and
failed 48 of 54 pages with tensor-shape errors, with a *different* set of pages
succeeding on each repeat. The rule since: concurrency per worker = 1, and
throughput comes from horizontal replicas only. ``load()`` refuses any other
value rather than trusting the caller.

The inference path is the documented ``vlm-engine`` backend of
``mineru.cli.common.do_parse``, invoked in-process so MinerU's ``ModelSingleton``
keeps the checkpoint warm across pages. ``vlm-engine`` is resolved by MinerU to a
concrete engine at call time; the adapter reads that resolution and fails closed
if it is not the engine ``runtime.json`` pins. Picking whichever engine happens
to be importable would be exactly the silent fallback the constitution forbids.

D59 (2026-09-04, real canary pod d4qo3kl49kai6v): MinerU still takes PDF bytes
under vlm-engine, via the same ``mineru.cli.common.read_fn`` the pipeline
backend uses. ``read_fn``'s own ``image_suffixes``/``pdf_suffixes`` lists are
declared *without* a leading dot (``"png"``, not ``".png"``) -- every caller
in MinerU's own CLI resolves a suffix the same dotless way. ``Path.suffix``
keeps the dot, so passing it straight through raised MinerU's own
``Exception(f"Unknown file suffix: {file_suffix}")`` on every page. See
``_mineru_file_suffix`` below.

Heavy imports live inside the default backend factory.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import platform
import sys
import tempfile
import threading
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

MODEL_KEY = "mineru_vlm"
REVISION_STAMP = "arena-weights-revision.txt"

# ARENA_CONTRACT D34 - prompt_kind "none".
#
# The MinerU vlm-engine backend takes no prompt: nothing in this file sends one and there is
# no text to reproduce. The registry file for runtime.json's prompt_id is
# therefore the empty file (sha256 of the empty string), and ``load()`` refuses
# a non-empty ``AdapterConfig.prompt_text`` rather than quietly leaving the
# official path.
OFFICIAL_PROMPT = ""
PROMPT_KIND = "none"
#: Masterplan section 14. Not a default, not tunable, not overridable.
REQUIRED_CONCURRENCY = 1


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
    provenance, the section 14 incident record and the open questions live
    beside it rather than being dropped.
    """
    path = Path(__file__).with_name("provenance.json")
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise AdapterError("DEPENDENCY", f"{path} must hold a JSON object")
    return document


class MineruVlmBackend(Protocol):
    """The narrow surface the adapter needs from MinerU."""

    def start(self) -> Mapping[str, Any]:
        """Resolve the VLM engine, load the checkpoint once, return provenance."""

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
    """Fail closed unless the baked checkpoint is the pinned revision."""
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
    """Tensor-shape errors get their own class - that is the §14 signature."""
    text = f"{type(exc).__name__}: {exc}".lower()
    if "shape" in text or "size mismatch" in text or "dimension" in text:
        return "TENSOR_SHAPE"
    if isinstance(exc, TimeoutError) or "timed out" in text or "timeout" in text:
        return "INFERENCE_TIMEOUT"
    if "out of memory" in text or "cuda oom" in text:
        return "CUDA_OOM"
    if "cuda" in text and "initializ" in text:
        return "CUDA_INIT"
    if isinstance(exc, (ValueError, TypeError, KeyError)):
        return "OUTPUT_MALFORMED"
    if isinstance(exc, OSError):
        return "INFRA_NETWORK"
    return "UNKNOWN"

def _block_count(native: Mapping[str, Any]) -> int | None:
    """MinerU's own count of what its layout step returned (D64 diagnostics)."""
    middle = native.get("middle_json")
    if not isinstance(middle, Mapping):
        return None
    pages = middle.get("pdf_info")
    if not isinstance(pages, list):
        return None
    total = 0
    for page in pages:
        if isinstance(page, Mapping):
            blocks = page.get("para_blocks")
            total += len(blocks) if isinstance(blocks, list) else 0
    return total



def _find_one(case_dir: Path, suffix: str, stem: str) -> Path | None:
    """The single ``<stem><suffix>`` file under the case dir, or None."""
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


class _OfficialMineruVlmBackend:
    """``aio_do_parse`` with the vlm-engine backend, batch size 1. GPU pod only.

    D79 (pod 8uzvgo0oj1vi43, 2026-09-04). MinerU exposes the same parse through
    two engines and they do not agree here. ``do_parse`` resolves 'auto' to
    ``vllm-engine`` and every page it produced on this stack came back with the
    layout answer ``]]<|><|><|><|>`` and an empty body; ``aio_do_parse``
    resolves to ``vllm-async-engine`` and produced the right markdown for the
    same page, in the same process, from the adapter's own kwargs. Four probes
    on pod x5kia8xy68w500 had already cleared the kwargs, the env and the
    calling thread, and the vendor's `mineru` command is correct because since
    3.4.4 it does not parse in its own process at all: it starts a local API
    server, and that server is on the async path. So the async engine is not a
    workaround here, it is the path the vendor actually ships.

    The loop is owned by this backend and lives on its own thread, the way the
    vendor's server owns one: the engine binds to the loop it was created on,
    so a fresh ``asyncio.run`` per page would abandon the cached predictor
    after the first one.
    """

    def __init__(self, cfg: AdapterConfig) -> None:
        self._cfg = cfg
        self._aio_do_parse: Any = None
        self._read_fn: Any = None
        self._loop: Any = None
        self._loop_thread: Any = None

    def start(self) -> Mapping[str, Any]:
        config = self._cfg.inference_config
        for key, value in dict(config["env"]).items():
            os.environ[str(key)] = str(value)

        # Only present inside the runtime image; mypy runs on a CPU box.
        from mineru.cli.common import (  # type: ignore[import-not-found]
            aio_do_parse,
            read_fn,
        )
        from mineru.utils.engine_utils import (  # type: ignore[import-not-found]
            get_vlm_engine,
        )

        # D64 (pod r0yal3hocpipsm, 2026-09-04): every page came back SUCCESS
        # with an empty body and nothing said why. The only record of what the
        # VLM answered at the layout step is mineru_vl_utils' *debug* line
        # ("Layout raw output: ..."), so the pod's loguru sink is set to DEBUG
        # on stderr, where the driver's post-run log capture (D62) can keep it.
        # Logging changes nothing about what is measured.
        with contextlib.suppress(Exception):  # diagnostics must never block the model
            from loguru import logger  # type: ignore[import-not-found]

            logger.remove()
            logger.add(sys.stderr, level="DEBUG", enqueue=False)

        resolved = str(get_vlm_engine(inference_engine="auto", is_async=True))
        expected = str(config["expected_vlm_engine"])
        if resolved != expected:
            raise AdapterError(
                "MODEL_LOAD",
                f"MinerU resolved vlm-engine to {resolved!r} but runtime.json pins "
                f"{expected!r}. Accepting whichever engine happens to be installed "
                "would change what is being measured; fix the image or the pin.",
            )
        self._aio_do_parse = aio_do_parse
        self._read_fn = read_fn
        self._loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(
            target=self._loop.run_forever, name="mineru-vlm-loop", daemon=True
        )
        self._loop_thread.start()
        return {
            "entrypoint": "mineru.cli.common.aio_do_parse",
            "backend": config["backend"],
            "resolved_vlm_engine": resolved,
            "batch_size": int(config["batch_size"]),
            "env": {str(k): str(v) for k, v in dict(config["env"]).items()},
        }

    def parse(self, image_path: Path, output_dir: Path, stem: str) -> None:
        if self._aio_do_parse is None or self._read_fn is None or self._loop is None:
            raise AdapterError("MODEL_LOAD", "MinerU VLM backend was never started")
        config = self._cfg.inference_config
        pdf_bytes = self._read_fn(image_path, _mineru_file_suffix(image_path))
        coroutine = self._aio_do_parse(
            output_dir=str(output_dir),
            pdf_file_names=[stem],
            pdf_bytes_list=[pdf_bytes],
            p_lang_list=[str(config["lang"])],
            backend=str(config["backend"]),
            formula_enable=bool(config["formula_enable"]),
            table_enable=bool(config["table_enable"]),
            f_draw_layout_bbox=bool(config["f_draw_layout_bbox"]),
            f_draw_span_bbox=bool(config["f_draw_span_bbox"]),
            f_dump_md=bool(config["f_dump_md"]),
            f_dump_middle_json=bool(config["f_dump_middle_json"]),
            f_dump_model_output=bool(config["f_dump_model_output"]),
            f_dump_orig_pdf=bool(config["f_dump_orig_pdf"]),
            f_dump_content_list=bool(config["f_dump_content_list"]),
            batch_size=int(config["batch_size"]),
        )
        future = asyncio.run_coroutine_threadsafe(coroutine, self._loop)
        future.result()

    def close(self) -> None:
        loop, thread = self._loop, self._loop_thread
        self._aio_do_parse = None
        self._read_fn = None
        self._loop = None
        self._loop_thread = None
        if loop is not None:
            loop.call_soon_threadsafe(loop.stop)
        if thread is not None:
            thread.join(timeout=30)
        if loop is not None:
            with contextlib.suppress(Exception):
                loop.close()


def _default_backend_factory(cfg: AdapterConfig) -> MineruVlmBackend:
    return _OfficialMineruVlmBackend(cfg)


class MineruVlmAdapter:
    """Implements ``arena.worker.adapter_api.ArenaModelAdapter``."""

    model_key = MODEL_KEY

    def __init__(
        self,
        backend_factory: Callable[[AdapterConfig], MineruVlmBackend] | None = None,
    ) -> None:
        self._backend_factory = backend_factory or _default_backend_factory
        self._backend: MineruVlmBackend | None = None
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
        # Masterplan section 14. Refuse rather than clamp: a caller that asked for
        # more concurrency has a wrong plan, and silently correcting it hides that.
        if cfg.max_concurrency != REQUIRED_CONCURRENCY:
            raise AdapterError(
                "MODEL_LOAD",
                f"mineru_vlm runs at concurrency {REQUIRED_CONCURRENCY} only "
                f"(masterplan section 14: 48/54 tensor-shape failures at concurrency 3); "
                f"got max_concurrency={cfg.max_concurrency}. Scale with replicas.",
            )
        if cfg.prompt_text:
            raise AdapterError(
                "MODEL_LOAD",
                "the MinerU vlm-engine backend takes no prompt; a non-empty prompt "
                "would leave the official path",
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
            "concurrency_policy": dict(spec["inference_config"]["concurrency_policy"]),
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
        with tempfile.TemporaryDirectory(prefix="arena-mineru-vlm-") as workdir:
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
        print(
            f"[arena] mineru_vlm page {stem}: markdown_chars={len(markdown)} "
            f"blocks={_block_count(native)}",
            file=sys.stderr,
            flush=True,
        )

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
    for name in ("mineru", "mineru-vl-utils", "torch", "transformers", "accelerate", "vllm"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def create_adapter(
    backend_factory: Callable[[AdapterConfig], MineruVlmBackend] | None = None,
) -> MineruVlmAdapter:
    return MineruVlmAdapter(backend_factory=backend_factory)
