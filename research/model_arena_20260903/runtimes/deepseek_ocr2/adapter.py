"""DeepSeek-OCR-2 arena adapter — official Transformers inference path.

Official sources pinned by this module (fetched 2026-09-03):

- https://huggingface.co/deepseek-ai/DeepSeek-OCR-2  @ aaa02f3811945a91062062994c5c4a3f4c0af2b0
- https://github.com/deepseek-ai/DeepSeek-OCR-2      @ 2f3699ebbb96fa8af32212e8c170f2cc28730fad

The official OmniDocBench batch script is the vLLM one
(``DeepSeek-OCR2-vllm/run_dpsk_ocr2_eval_batch.py``); its knobs live in
``DeepSeek-OCR2-vllm/config.py``. This adapter takes that script's *configuration*
(prompt, base_size, image_size, crop_mode, greedy decoding, 8,192 max new tokens)
and executes it through the officially documented Transformers entry point
``AutoModel.infer(..., eval_mode=True)``, because the arena worker serves exactly
one page per HTTP request (ARENA_CONTRACT section 4) and the batch script's only
advantage is cross-page batching. Both deviations are recorded in README.md.

``eval_mode=True`` is used, not ``save_results=True``: it returns the model's
response as a string with no file side effects, which is what ``raw_text`` must
carry verbatim. Everything downstream of the string lives in ``canonical.py``.

Heavy imports (torch, transformers) happen inside ``load`` so this module imports
on a CPU box with neither installed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
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

MODEL_KEY = "deepseek_ocr2"
MODEL_REPO = "deepseek-ai/DeepSeek-OCR-2"
MODEL_REVISION = "aaa02f3811945a91062062994c5c4a3f4c0af2b0"

# DeepSeek-OCR2-vllm/config.py PROMPT, verbatim. The HF model card prints the
# same prompt with one trailing space; the OmniDocBench batch script does not.
# The batch script wins because it is the script that produced the official
# document-parsing numbers. README.md records the difference and both hashes.
OFFICIAL_PROMPT = "<image>\n<|grounding|>Convert the document to markdown."
PINNED_PROMPT_SHA256 = "sha256:00a105b332827a249e76115332aef75dfdf7578e026c25fef1a35662a81efa32"

WEIGHTS_RECEIPT_NAME = "arena-weights-receipt.json"
WEIGHTS_MANIFEST_NAME = "arena-weights-manifest.json"
LARGEST_WEIGHT_FILE = "model-00001-of-000001.safetensors"
LARGEST_WEIGHT_SHA256 = "sha256:d8ff67a424ba6f4dd077885eb9d6a05d2537e76fe5491f0e2a9b712f8c8870fa"

# config.py BASE_SIZE / IMAGE_SIZE / CROP_MODE; generate() kwargs from
# modeling_deepseekocr2.py's eval_mode branch.
DEFAULT_BASE_SIZE = 1024
DEFAULT_IMAGE_SIZE = 768
DEFAULT_CROP_MODE = True
DEFAULT_MAX_NEW_TOKENS = 8192
DEFAULT_NO_REPEAT_NGRAM_SIZE = 35

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
        f"{PINNED_PROMPT_SHA256}; the prompt text was edited without a receipt"
    )


def build_weights_manifest(weights_dir: Path) -> tuple[dict[str, str], str]:
    """Return ``({posix_relpath: "sha256:<hex>"}, manifest_sha256)``.

    The manifest hash is the sha256 of the canonical JSON of the mapping
    (``sort_keys=True``, ``separators=(",", ":")``, ``ensure_ascii=True``), which
    is the "sha256 over sorted (relative_path, file_sha256) pairs" the adapter
    interface asks for. The two arena bookkeeping files are excluded from it so
    that writing the receipt cannot change the value it records.
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
    largest = LARGEST_WEIGHT_FILE
    if largest not in entries:
        raise AdapterError(
            "MODEL_DOWNLOAD",
            f"{MODEL_KEY}: expected weight file {largest} missing from {weights_dir}",
        )
    receipt: dict[str, object] = {
        "model_key": MODEL_KEY,
        "model_repo": repo,
        "model_revision": revision,
        "largest_file": largest,
        "largest_file_sha256": entries[largest],
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
    """Fail closed unless the on-disk weights are the pinned revision, unmodified.

    Returns ``(revision, weights_sha256_manifest)`` recomputed from disk.
    """

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
    # None when the runtime does not expose it. The Transformers path does not,
    # so truncation is unknown here rather than reported as False.
    finish_reason: str | None
    usage: Mapping[str, Any]
    peak_vram_mb: int | None


class ModelBackend(Protocol):
    """The GPU-touching half of the adapter. Tests inject a fake implementation."""

    def generate(self, image_path: Path, prompt: str) -> BackendResult: ...

    def provenance(self) -> Mapping[str, Any]: ...

    def close(self) -> None: ...


BackendFactory = Callable[[AdapterConfig, Path], ModelBackend]


class TransformersBackend:
    """The official ``AutoModel.infer`` path. Imports torch/transformers on construction."""

    def __init__(self, cfg: AdapterConfig, weights_dir: Path) -> None:
        import torch  # type: ignore[import-not-found]
        from transformers import AutoModel, AutoTokenizer  # type: ignore[import-not-found]

        self._torch = torch
        self._scratch = Path(tempfile.mkdtemp(prefix="arena-deepseek-ocr2-"))
        self._base_size = int(cfg.inference_config.get("base_size", DEFAULT_BASE_SIZE))
        self._image_size = int(cfg.inference_config.get("image_size", DEFAULT_IMAGE_SIZE))
        self._crop_mode = bool(cfg.inference_config.get("crop_mode", DEFAULT_CROP_MODE))
        attn = str(cfg.inference_config.get("attn_implementation", "flash_attention_2"))
        self._tokenizer = AutoTokenizer.from_pretrained(str(weights_dir), trust_remote_code=True)
        model = AutoModel.from_pretrained(
            str(weights_dir),
            _attn_implementation=attn,
            trust_remote_code=True,
            use_safetensors=True,
        )
        self._model = model.eval().cuda().to(torch.bfloat16)

    def generate(self, image_path: Path, prompt: str) -> BackendResult:
        torch = self._torch
        if torch.cuda.is_available():
            torch.cuda.reset_peak_memory_stats()
        text = self._model.infer(
            self._tokenizer,
            prompt=prompt,
            image_file=str(image_path),
            output_path=str(self._scratch),
            base_size=self._base_size,
            image_size=self._image_size,
            crop_mode=self._crop_mode,
            save_results=False,
            eval_mode=True,
        )
        if not isinstance(text, str):
            raise AdapterError(
                "OUTPUT_MALFORMED",
                f"{MODEL_KEY}: infer(eval_mode=True) returned {type(text).__name__}, not str",
            )
        peak_vram_mb: int | None = None
        if torch.cuda.is_available():
            peak_vram_mb = int(torch.cuda.max_memory_allocated() // (1024 * 1024))
        return BackendResult(text=text, finish_reason=None, usage={}, peak_vram_mb=peak_vram_mb)

    def provenance(self) -> Mapping[str, Any]:
        import importlib.metadata as metadata
        import platform
        import sys

        torch = self._torch
        versions: dict[str, str | None] = {}
        for package in ("torch", "transformers", "tokenizers", "flash-attn", "pillow", "einops"):
            try:
                versions[package] = metadata.version(package)
            except metadata.PackageNotFoundError:
                versions[package] = None
        driver: str | None = None
        device_name: str | None = None
        if torch.cuda.is_available():
            device_name = str(torch.cuda.get_device_name(0))
            driver = str(getattr(torch.version, "cuda", None))
        return {
            "runtime": "transformers",
            "versions": versions,
            "torch_cuda_build": getattr(torch.version, "cuda", None),
            "cuda_runtime": driver,
            "gpu_name": device_name,
            "python": sys.version,
            "os": platform.platform(),
        }

    def close(self) -> None:
        shutil.rmtree(self._scratch, ignore_errors=True)


def _default_backend_factory(cfg: AdapterConfig, weights_dir: Path) -> ModelBackend:
    return TransformersBackend(cfg, weights_dir)


# Ordered, documented classification. Nothing here guesses beyond these anchors;
# anything unmatched is UNKNOWN so the controller sees an unclassified failure
# instead of a plausible-looking wrong class.
_ERROR_ANCHORS: tuple[tuple[str, str], ...] = (
    ("out of memory", "CUDA_OOM"),
    ("cuda error", "GPU_KERNEL"),
    ("cuda driver", "CUDA_INIT"),
    ("no kernel image is available", "GPU_KERNEL"),
    ("device-side assert", "GPU_KERNEL"),
    ("shape", "TENSOR_SHAPE"),
    ("size mismatch", "TENSOR_SHAPE"),
    ("flash_attn", "DEPENDENCY"),
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


class DeepSeekOCR2Adapter:
    """``arena.worker.adapter_api.ArenaModelAdapter`` for DeepSeek-OCR-2."""

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
            raise AdapterError(
                "MODEL_LOAD",
                f"{MODEL_KEY}: prompt {cfg.prompt_id!r} hashes to {prompt_sha256}, "
                f"the official OmniDocBench prompt hashes to {PINNED_PROMPT_SHA256}",
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
            # same thing and the adapter cannot tell them apart. Report the empty
            # response as-is with a flag; the QA gate decides.
            warnings.append("OUTPUT_EMPTY: model returned no non-whitespace characters")
            semantic_error_class = "OUTPUT_EMPTY"
        if result.finish_reason == "length":
            warnings.append("OUTPUT_TRUNCATED: generation stopped at the token cap")
            semantic_error_class = semantic_error_class or "OUTPUT_TRUNCATED"
        return RawOutput(
            raw_text=result.text,
            output_format="deepseek-ocr2-grounded-markdown",
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
                "official_runtime": "transformers",
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
