"""OvisOCR2 arena adapter — the official vLLM 0.22.1 model-card path, exactly.

Official source (fetched 2026-09-03):
https://huggingface.co/ATH-MaaS/OvisOCR2 @ 1fc9221b7823a371d6e97f92d527cc847e24e107

Masterplan §4 records that the previous TAVONEL measurement of this model was
abnormally low against the official OmniDocBench v1.6 score of 96.58, and §47 H3
asks whether re-running it on the official contract closes that gap. So this
adapter reproduces the model card's `OvisOCR2Parser` byte for byte where it
matters — prompt, chat template, pixel bounds, sampling, post-processing order —
and every place the previous run differed is listed in README.md with the
decision to keep or drop it. None of the previous run's inference-semantics
deviations are kept.

Heavy imports (vllm, PIL) happen inside ``load`` so this module imports on a CPU
box with neither installed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
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

MODEL_KEY = "ovisocr2"
MODEL_REPO = "ATH-MaaS/OvisOCR2"
MODEL_REVISION = "1fc9221b7823a371d6e97f92d527cc847e24e107"

# The model card's `prompt` local, reproduced verbatim including the leading
# newline and the single space before "Preserve". The card splits the literal
# around "<" + "img src=..." purely to stop the tag rendering in the card; the
# resulting string is what is reproduced here.
OFFICIAL_PROMPT = (
    "\nExtract all readable content from the image in natural human reading order "
    "and output the result as a single Markdown document. For charts or images, "
    'represent them using an HTML image tag: <img src="images/bbox_{left}_{top}'
    '_{right}_{bottom}.jpg" />, where left, top, right, bottom are bounding box '
    "coordinates scaled to [0, 1000). Format formulas as LaTeX. Format tables as "
    "HTML: <table>...</table>. Transcribe all other text as standard Markdown. "
    "Preserve the original text without translation or paraphrasing."
)
PINNED_PROMPT_SHA256 = "sha256:de9617f877f6110d22adf1a6ba2a96221189dc246fb1fef161e408d37bff5267"
# The prompt the 2026-08 TAVONEL run actually sent; published in
# benchmark/reports/OVISOCR2_0_9B_VLLM_CU129_OMNIDOCBENCH_DEMO_EVALUATION_2026-08-01.md.
# Kept here only so the adapter can name it when it refuses one.
PREVIOUS_TAVONEL_PROMPT_SHA256 = (
    "sha256:c0fb65bf41705f32189c0e2407d824db52a68a365024239b2029a7a283f64567"
)

WEIGHTS_RECEIPT_NAME = "arena-weights-receipt.json"
WEIGHTS_MANIFEST_NAME = "arena-weights-manifest.json"
LARGEST_WEIGHT_FILE = "model.safetensors"
LARGEST_WEIGHT_SHA256 = "sha256:9270560288656ece5cb3a6989001afcf5af8d223bceed4a423c33a008861d009"

# Model card OvisOCR2Parser.__init__ / .parse.
DEFAULT_GPU_MEMORY_UTILIZATION = 0.8
DEFAULT_TENSOR_PARALLEL_SIZE = 1
DEFAULT_GDN_PREFILL_BACKEND = "triton"
DEFAULT_MAX_TOKENS = 16384
DEFAULT_TEMPERATURE = 0.0
DEFAULT_MIN_PIXELS = 448 * 448
DEFAULT_MAX_PIXELS = 2880 * 2880

_HASH_CHUNK = 1024 * 1024


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_HASH_CHUNK), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _sha256_text(text: str) -> str:
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


if _sha256_text(OFFICIAL_PROMPT) != PINNED_PROMPT_SHA256:  # pragma: no cover - import guard
    raise RuntimeError(
        f"{MODEL_KEY}: OFFICIAL_PROMPT no longer hashes to its pin "
        f"{PINNED_PROMPT_SHA256}; hypothesis H3 depends on this string being exact"
    )


def build_weights_manifest(weights_dir: Path) -> tuple[dict[str, str], str]:
    """Return ``({posix_relpath: "sha256:<hex>"}, manifest_sha256)``.

    The manifest hash is the sha256 of the canonical JSON of the mapping
    (``sort_keys=True``, ``separators=(",", ":")``, ``ensure_ascii=True``). The
    two arena bookkeeping files are excluded so writing the receipt cannot change
    the value it records.
    """

    entries: dict[str, str] = {}
    for path in sorted(weights_dir.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(weights_dir).as_posix()
        if relative in {WEIGHTS_RECEIPT_NAME, WEIGHTS_MANIFEST_NAME}:
            continue
        entries[relative] = _sha256_file(path)
    return entries, _sha256_text(_canonical_json(entries))


def write_weights_receipt(weights_dir: Path, *, repo: str, revision: str) -> dict[str, object]:
    """Record what is actually on disk. Called from the Dockerfile, never at run time."""

    entries, manifest_sha256 = build_weights_manifest(weights_dir)
    if LARGEST_WEIGHT_FILE not in entries:
        raise AdapterError(
            "MODEL_DOWNLOAD",
            f"{MODEL_KEY}: expected weight file {LARGEST_WEIGHT_FILE} missing from {weights_dir}",
        )
    receipt: dict[str, object] = {
        "model_key": MODEL_KEY,
        "model_repo": repo,
        "model_revision": revision,
        "largest_file": LARGEST_WEIGHT_FILE,
        "largest_file_sha256": entries[LARGEST_WEIGHT_FILE],
        "file_count": len(entries),
        "weights_sha256_manifest": manifest_sha256,
    }
    (weights_dir / WEIGHTS_MANIFEST_NAME).write_text(
        _canonical_json(entries) + "\n", encoding="utf-8"
    )
    (weights_dir / WEIGHTS_RECEIPT_NAME).write_text(
        _canonical_json(receipt) + "\n", encoding="utf-8"
    )
    return receipt


def verify_weights(weights_dir: Path, *, expected_revision: str) -> tuple[str, str]:
    """Fail closed unless the on-disk weights are the pinned revision, unmodified."""

    receipt_path = weights_dir / WEIGHTS_RECEIPT_NAME
    if not receipt_path.is_file():
        raise AdapterError(
            "MODEL_LOAD",
            f"{MODEL_KEY}: no {WEIGHTS_RECEIPT_NAME} in {weights_dir}; the image did not "
            "record which revision it baked, so the loaded revision cannot be verified",
        )
    try:
        raw = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AdapterError("MODEL_LOAD", f"{MODEL_KEY}: unreadable weights receipt: {exc}") from exc
    if not isinstance(raw, dict):
        raise AdapterError("MODEL_LOAD", f"{MODEL_KEY}: weights receipt is not an object")
    recorded_revision = str(raw.get("model_revision", ""))
    if recorded_revision != expected_revision:
        raise AdapterError(
            "MODEL_LOAD",
            f"{MODEL_KEY}: weights on disk are revision {recorded_revision!r}, "
            f"configuration asks for {expected_revision!r}",
        )
    _, manifest_sha256 = build_weights_manifest(weights_dir)
    recorded_manifest = str(raw.get("weights_sha256_manifest", ""))
    if manifest_sha256 != recorded_manifest:
        raise AdapterError(
            "CHECKSUM",
            f"{MODEL_KEY}: weight files changed since the image was built "
            f"(manifest {manifest_sha256} != receipt {recorded_manifest})",
        )
    return recorded_revision, manifest_sha256


@dataclass(frozen=True, slots=True)
class BackendResult:
    """What one backend call produced. ``text`` is verbatim, never post-processed."""

    text: str
    finish_reason: str | None
    usage: Mapping[str, Any]
    peak_vram_mb: int | None


class ModelBackend(Protocol):
    """The GPU-touching half of the adapter. Tests inject a fake implementation."""

    def generate(self, image_path: Path, prompt: str) -> BackendResult: ...

    def provenance(self) -> Mapping[str, Any]: ...

    def close(self) -> None: ...


BackendFactory = Callable[[AdapterConfig, Path], ModelBackend]


class VllmBackend:
    """The model card's ``OvisOCR2Parser``, one page per call."""

    def __init__(self, cfg: AdapterConfig, weights_dir: Path) -> None:
        # vLLM's library entry point forks by default on Linux and CUDA cannot be
        # re-initialised in that child. This is an operational fix with no effect
        # on what the model emits; the effective value is reported in provenance
        # and the Dockerfile sets it too, so it is visible rather than implicit.
        os.environ.setdefault("VLLM_WORKER_MULTIPROC_METHOD", "spawn")

        from vllm import LLM, SamplingParams  # type: ignore[import-not-found]

        config = cfg.inference_config
        self._min_pixels = int(config.get("min_pixels", DEFAULT_MIN_PIXELS))
        self._max_pixels = int(config.get("max_pixels", DEFAULT_MAX_PIXELS))
        self._llm = LLM(
            model=str(weights_dir),
            tensor_parallel_size=int(
                config.get("tensor_parallel_size", DEFAULT_TENSOR_PARALLEL_SIZE)
            ),
            gpu_memory_utilization=float(
                config.get("gpu_memory_utilization", DEFAULT_GPU_MEMORY_UTILIZATION)
            ),
            gdn_prefill_backend=str(
                config.get("gdn_prefill_backend", DEFAULT_GDN_PREFILL_BACKEND)
            ),
        )
        self._sampling_params = SamplingParams(
            max_tokens=int(config.get("max_tokens", DEFAULT_MAX_TOKENS)),
            temperature=float(config.get("temperature", DEFAULT_TEMPERATURE)),
        )
        # Model card: the chat template is applied once, with enable_thinking=False.
        self._templated_prompt: str = self._llm.get_tokenizer().apply_chat_template(
            [
                {
                    "role": "user",
                    "content": [{"type": "image"}, {"type": "text", "text": cfg.prompt_text}],
                }
            ],
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False,
        )

    def generate(self, image_path: Path, prompt: str) -> BackendResult:
        from PIL import Image

        if _sha256_text(prompt) != PINNED_PROMPT_SHA256:
            raise AdapterError(
                "MODEL_LOAD",
                f"{MODEL_KEY}: the prompt changed after load(); the chat template was "
                "built from the loaded prompt and cannot be rebuilt per page",
            )
        try:
            with Image.open(image_path) as handle:
                image = handle.convert("RGB")
        except OSError as exc:
            raise AdapterError(
                "INPUT_DECODE", f"{MODEL_KEY}: cannot decode {image_path}: {exc}"
            ) from exc
        vllm_input = {
            "prompt": self._templated_prompt,
            "multi_modal_data": {"image": image},
            "mm_processor_kwargs": {
                "images_kwargs": {
                    "min_pixels": self._min_pixels,
                    "max_pixels": self._max_pixels,
                }
            },
        }
        outputs = self._llm.generate([vllm_input], self._sampling_params)
        if len(outputs) != 1:
            raise AdapterError(
                "OUTPUT_MALFORMED",
                f"{MODEL_KEY}: vLLM returned {len(outputs)} outputs for one page",
            )
        completion = outputs[0].outputs[0]
        prompt_token_ids = getattr(outputs[0], "prompt_token_ids", None)
        usage: dict[str, Any] = {
            "input_tokens": len(prompt_token_ids) if prompt_token_ids is not None else None,
            "output_tokens": len(completion.token_ids) if completion.token_ids else 0,
        }
        return BackendResult(
            text=completion.text,
            finish_reason=getattr(completion, "finish_reason", None),
            usage=usage,
            peak_vram_mb=None,
        )

    def provenance(self) -> Mapping[str, Any]:
        import importlib.metadata as metadata
        import platform
        import sys

        versions: dict[str, str | None] = {}
        for package in ("vllm", "torch", "transformers", "tokenizers", "pillow"):
            try:
                versions[package] = metadata.version(package)
            except metadata.PackageNotFoundError:
                versions[package] = None
        return {
            "runtime": "vllm",
            "versions": versions,
            "worker_multiproc_method": os.environ.get("VLLM_WORKER_MULTIPROC_METHOD"),
            "gdn_prefill_backend": DEFAULT_GDN_PREFILL_BACKEND,
            "python": sys.version,
            "os": platform.platform(),
        }

    def close(self) -> None:
        self._llm = None


def _default_backend_factory(cfg: AdapterConfig, weights_dir: Path) -> ModelBackend:
    return VllmBackend(cfg, weights_dir)


# Ordered, documented classification. Anything unmatched is UNKNOWN so the
# controller sees an unclassified failure instead of a plausible wrong class.
_ERROR_ANCHORS: tuple[tuple[str, str], ...] = (
    ("out of memory", "CUDA_OOM"),
    ("no available memory for the cache blocks", "CUDA_OOM"),
    ("cuda error", "GPU_KERNEL"),
    ("cuda driver", "CUDA_INIT"),
    ("no kernel image is available", "GPU_KERNEL"),
    ("device-side assert", "GPU_KERNEL"),
    ("shape", "TENSOR_SHAPE"),
    ("size mismatch", "TENSOR_SHAPE"),
    ("engine core", "INFERENCE_STALL"),
    ("no module named", "DEPENDENCY"),
    ("cannot identify image file", "INPUT_DECODE"),
    ("truncated file", "INPUT_DECODE"),
)


def classify_exception(exc: BaseException) -> str:
    if isinstance(exc, AdapterError):
        return exc.error_class
    message = f"{type(exc).__name__}: {exc}".lower()
    for anchor, error_class in _ERROR_ANCHORS:
        if anchor in message:
            return error_class
    return "UNKNOWN"


class OvisOCR2Adapter:
    """``arena.worker.adapter_api.ArenaModelAdapter`` for OvisOCR2."""

    model_key = MODEL_KEY

    def __init__(self, backend_factory: BackendFactory | None = None) -> None:
        self._backend_factory: BackendFactory = backend_factory or _default_backend_factory
        self._backend: ModelBackend | None = None
        self._cfg: AdapterConfig | None = None
        self._load_receipt: LoadReceipt | None = None

    # -- lifecycle ---------------------------------------------------------

    def load(self, cfg: AdapterConfig) -> LoadReceipt:
        if cfg.model_key != MODEL_KEY:
            raise AdapterError(
                "MODEL_LOAD", f"{MODEL_KEY}: configuration is for model_key {cfg.model_key!r}"
            )
        if cfg.model_repo != MODEL_REPO:
            raise AdapterError(
                "MODEL_LOAD", f"{MODEL_KEY}: configuration is for repo {cfg.model_repo!r}"
            )
        prompt_sha256 = _sha256_text(cfg.prompt_text)
        if prompt_sha256 != PINNED_PROMPT_SHA256:
            detail = ""
            if prompt_sha256 == PREVIOUS_TAVONEL_PROMPT_SHA256:
                detail = (
                    " — this is the 2026-08 TAVONEL prompt, which drops the leading newline "
                    "and breaks the line before 'Preserve the original text'; masterplan H3 "
                    "exists because of exactly this kind of drift"
                )
            raise AdapterError(
                "MODEL_LOAD",
                f"{MODEL_KEY}: prompt {cfg.prompt_id!r} hashes to {prompt_sha256}, "
                f"the official model-card prompt hashes to {PINNED_PROMPT_SHA256}{detail}",
            )
        weights_dir = Path(cfg.weights_dir)
        if not weights_dir.is_dir():
            raise AdapterError("MODEL_LOAD", f"{MODEL_KEY}: weights_dir {weights_dir} is not a dir")
        started = time.perf_counter()
        revision, manifest_sha256 = verify_weights(
            weights_dir, expected_revision=cfg.model_revision
        )
        try:
            backend = self._backend_factory(cfg, weights_dir)
        except AdapterError:
            raise
        except Exception as exc:
            raise AdapterError(
                classify_exception(exc), f"{MODEL_KEY}: backend construction failed: {exc}"
            ) from exc
        load_ms = int((time.perf_counter() - started) * 1000)
        self._backend = backend
        self._cfg = cfg
        receipt = LoadReceipt(
            model_key=MODEL_KEY,
            model_repo=cfg.model_repo,
            model_revision=revision,
            weights_sha256_manifest=manifest_sha256,
            load_ms=load_ms,
            cache_hit=False,
            runtime_provenance=backend.provenance(),
        )
        self._load_receipt = receipt
        return receipt

    def warmup(self, synthetic_image: Path) -> WarmupReceipt:
        backend, cfg = self._require_loaded()
        started = time.perf_counter()
        try:
            result = backend.generate(Path(synthetic_image), cfg.prompt_text)
        except AdapterError:
            raise
        except Exception as exc:
            raise AdapterError(
                classify_exception(exc), f"{MODEL_KEY}: warmup failed: {exc}"
            ) from exc
        return WarmupReceipt(
            warmup_ms=int((time.perf_counter() - started) * 1000),
            output_chars=len(result.text),
            schema_valid=isinstance(result.text, str),
            peak_vram_mb=result.peak_vram_mb,
        )

    def infer(self, page: PageInput) -> RawOutput:
        backend, cfg = self._require_loaded()
        image_path = Path(page.image_path)
        preprocess_started = time.perf_counter()
        if not image_path.is_file():
            raise AdapterError("INPUT_DECODE", f"{MODEL_KEY}: page image {image_path} is missing")
        actual = _sha256_file(image_path)
        if actual != page.source_sha256:
            raise AdapterError(
                "CHECKSUM",
                f"{MODEL_KEY}: page {page.case_key} image hashes to {actual}, "
                f"the job says {page.source_sha256}",
            )
        preprocess_ms = int((time.perf_counter() - preprocess_started) * 1000)

        inference_started = time.perf_counter()
        try:
            result = backend.generate(image_path, cfg.prompt_text)
        except AdapterError:
            raise
        except Exception as exc:
            raise AdapterError(
                classify_exception(exc),
                f"{MODEL_KEY}: inference failed on {page.case_key}: {exc}",
            ) from exc
        inference_ms = int((time.perf_counter() - inference_started) * 1000)

        warnings: list[str] = []
        semantic_error_class: str | None = None
        if not result.text.strip():
            # Section 41: a blank source page and a failed extraction are not the
            # same thing and the adapter cannot tell them apart.
            warnings.append("OUTPUT_EMPTY: model returned no non-whitespace characters")
            semantic_error_class = "OUTPUT_EMPTY"
        if result.finish_reason == "length":
            warnings.append(
                "OUTPUT_TRUNCATED: vLLM finish_reason=length at the 16,384-token cap"
            )
            semantic_error_class = semantic_error_class or "OUTPUT_TRUNCATED"
        return RawOutput(
            raw_text=result.text,
            output_format="markdown",
            native_json=None,
            usage=dict(result.usage),
            timings_ms={
                "preprocess_ms": preprocess_ms,
                "inference_ms": inference_ms,
                "postprocess_ms": 0,
            },
            peak_vram_mb=result.peak_vram_mb,
            first_token_at=None,
            warnings=tuple(warnings),
            semantic_error_class=semantic_error_class,
        )

    def runtime_provenance(self) -> Mapping[str, Any]:
        backend, _ = self._require_loaded()
        provenance = dict(backend.provenance())
        provenance.update(
            {
                "model_key": MODEL_KEY,
                "model_repo": MODEL_REPO,
                "model_revision": (
                    self._load_receipt.model_revision if self._load_receipt else None
                ),
                "official_runtime": "vllm",
                "prompt_sha256": PINNED_PROMPT_SHA256,
            }
        )
        return provenance

    def close(self) -> None:
        backend, self._backend = self._backend, None
        self._cfg = None
        self._load_receipt = None
        if backend is not None:
            backend.close()

    # -- internals ---------------------------------------------------------

    def _require_loaded(self) -> tuple[ModelBackend, AdapterConfig]:
        if self._backend is None or self._cfg is None:
            raise AdapterError("MODEL_LOAD", f"{MODEL_KEY}: adapter used before load()")
        return self._backend, self._cfg


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=f"{MODEL_KEY} runtime helper")
    parser.add_argument("--write-weights-receipt", type=Path, required=True)
    parser.add_argument("--repo", default=MODEL_REPO)
    parser.add_argument("--revision", default=MODEL_REVISION)
    args = parser.parse_args(argv)
    receipt = write_weights_receipt(
        args.write_weights_receipt, repo=args.repo, revision=args.revision
    )
    print(_canonical_json(receipt))
    return 0


if __name__ == "__main__":  # pragma: no cover - container build entry point
    raise SystemExit(_main())
