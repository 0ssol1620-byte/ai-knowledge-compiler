"""PaddleOCR-VL 1.6 arena adapter - official doc-parser pipeline + vLLM service.

The official documentation opens with a warning that calling the 0.9B VLM
directly through Transformers, vLLM, SGLang or FastDeploy is *not* equivalent
to running the PaddleOCR-VL pipeline. The documented production path, and the
one implemented here, is the split described in the pipeline tutorial:

    PaddleOCR client  (layout analysis + the rest of the workflow, PaddlePaddle)
        |  vl_rec_backend="vllm-server", vl_rec_server_url=http://127.0.0.1:8118/v1
        v
    `paddleocr genai_server --backend vllm`   (VLM stage only, loopback)

ARENA_CONTRACT D19 gives ``entrypoint.sh`` the server process: it renders the
launch plan from ``build_server_plan`` (through ``--print-server-plan``), polls
the readiness probe, runs the worker as a child and stops the server from a
trap. When ``ARENA_MODEL_SERVER_MANAGED_BY=entrypoint`` this adapter attaches to
that service and never spawns a second one; when nothing else started it (a
developer running the adapter directly), ``load()`` starts and ``close()`` reaps
it, so two-stage readiness still covers engine boot.

Every heavy import happens inside the default backend factory, never at module
import: this module must import on a CPU box with no paddle and no vllm.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
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

MODEL_KEY = "paddleocr_vl_1_6"
REVISION_STAMP = "arena-weights-revision.txt"

# ARENA_CONTRACT D34 - prompt_kind "none".
#
# The PaddleOCR-VL pipeline builds its own prompt per detected block inside
# paddleocr; nothing in this file sends a prompt and there is no text to
# reproduce. The registry file for runtime.json's prompt_id is therefore the
# empty file, and ``load()`` refuses a non-empty ``AdapterConfig.prompt_text``
# rather than quietly leaving the official path.
OFFICIAL_PROMPT = ""
PROMPT_KIND = "none"

# The entrypoint exports this when it owns the model-server process (D19).
SERVER_MANAGED_BY_ENV = "ARENA_MODEL_SERVER_MANAGED_BY"
ENTRYPOINT_MANAGED = "entrypoint"
# D19 floor: never treat a server as failed before twenty minutes have passed.
READY_DEADLINE_FLOOR_SECONDS = 1200

# PaddleX markdown payloads are dicts keyed by one of these, or a bare string.
_MARKDOWN_KEYS = ("markdown_texts", "markdown_text", "text")


@lru_cache(maxsize=1)
def runtime_spec() -> Mapping[str, Any]:
    """The co-located runtime.json. The adapter never hardcodes a pin."""
    path = Path(__file__).with_name("runtime.json")
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise AdapterError("DEPENDENCY", f"{path} must hold a JSON object")
    return document


@lru_cache(maxsize=1)
def provenance_spec() -> Mapping[str, Any]:
    """The co-located provenance.json.

    runtime.json is validated against arena/core/schemas/runtime.schema.json,
    which is closed (``additionalProperties: false``). Resolution provenance,
    cross-checks and the open questions therefore live beside it rather than
    being dropped: none of it is invented, and none of it is hidden.
    """
    path = Path(__file__).with_name("provenance.json")
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise AdapterError("DEPENDENCY", f"{path} must hold a JSON object")
    return document


class PaddleVlBackend(Protocol):
    """The narrow surface the adapter needs from the official stack."""

    def start(self) -> Mapping[str, Any]:
        """Bring the VLM service and the pipeline client up; return provenance."""

    def predict(self, image_path: Path) -> Sequence[tuple[Mapping[str, Any], str]]:
        """Return one (result_json, markdown) pair per page PaddleX emitted."""

    def close(self) -> None: ...


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def weights_manifest_sha256(weights_dir: Path) -> str:
    """sha256 over sorted (relative_path, file_sha256) pairs (adapter_api)."""
    rows = [
        (path.relative_to(weights_dir).as_posix(), sha256_file(path))
        for path in sorted(weights_dir.rglob("*"))
        if path.is_file()
    ]
    payload = json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def verify_weights(weights_dir: Path, expected_revision: str) -> tuple[str, bool]:
    """Fail closed unless the baked tree is the pinned revision.

    The build writes ``arena-weights-revision.txt`` next to the checkpoint after
    ``hf download --revision``; here the stamp *and* the sha256 of the largest
    weight file are re-checked against runtime.json. Returns
    ``(weights_manifest_sha256, cache_hit)``.
    """
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
    """Map a runtime exception onto ERROR_CLASSES without guessing a cause."""
    text = f"{type(exc).__name__}: {exc}".lower()
    if isinstance(exc, TimeoutError) or "timed out" in text or "timeout" in text:
        return "INFERENCE_TIMEOUT"
    if "out of memory" in text or "cuda oom" in text:
        return "CUDA_OOM"
    if "cuda" in text and "initializ" in text:
        return "CUDA_INIT"
    if "shape" in text and ("mismatch" in text or "invalid" in text):
        return "TENSOR_SHAPE"
    if isinstance(exc, (OSError, urllib.error.URLError)):
        return "INFRA_NETWORK"
    if isinstance(exc, (ValueError, TypeError, KeyError)):
        return "OUTPUT_MALFORMED"
    return "UNKNOWN"


def markdown_payload(value: Any) -> str:
    """Extract Markdown from a PaddleX Markdown payload (dict or string)."""
    if isinstance(value, dict):
        for key in _MARKDOWN_KEYS:
            candidate = value.get(key)
            if isinstance(candidate, str):
                return candidate
        return ""
    if isinstance(value, str):
        return value
    return ""


def _wait_for_http(url: str, timeout_seconds: int) -> None:
    deadline = time.monotonic() + timeout_seconds
    last: str = "no attempt made"
    while time.monotonic() < deadline:
        try:
            request = urllib.request.Request(url, method="GET")  # noqa: S310 - loopback literal
            with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
                if 200 <= int(response.status) < 400:
                    return
                last = f"status {response.status}"
        except Exception as exc:
            last = f"{type(exc).__name__}: {exc}"
        time.sleep(2.0)
    raise AdapterError("MODEL_LOAD", f"VLM service never became ready at {url}: {last}")


def build_server_plan(
    weights_dir: Path, inference_config: Mapping[str, Any]
) -> dict[str, Any]:
    """The `paddleocr genai_server` launch plan: argv, env, probe and deadline.

    ARENA_CONTRACT D19 moved process ownership of the VLM service from the
    adapter to ``entrypoint.sh``. Both callers render the command from this one
    builder - ``entrypoint.sh`` through ``adapter.py --print-server-plan`` and
    ``_OfficialPaddleVlBackend`` when nothing else started the server - so the
    two cannot drift into launching different services on the same port.
    """
    server = dict(inference_config["genai_server"])
    argv = [
        "paddleocr",
        "genai_server",
        "--model_name",
        str(server["model_name"]),
        "--model_dir",
        str(weights_dir),
        "--host",
        str(server["host"]),
        "--port",
        str(server["port"]),
        "--backend",
        str(server["backend"]),
    ]
    backend_config = server.get("backend_config")
    if backend_config:
        argv.extend(["--backend_config", str(backend_config)])
    return {
        "argv": argv,
        "env": {},
        "ready_probe": str(server["ready_probe"]),
        "ready_timeout_seconds": max(
            int(server["ready_timeout_seconds"]), READY_DEADLINE_FLOOR_SECONDS
        ),
    }


def entrypoint_owns_the_server() -> bool:
    """True when entrypoint.sh already started the VLM service (D19)."""
    return os.environ.get(SERVER_MANAGED_BY_ENV, "").strip().lower() == ENTRYPOINT_MANAGED


class _OfficialPaddleVlBackend:
    """The documented pipeline-client + genai_server split. GPU pod only."""

    def __init__(self, cfg: AdapterConfig) -> None:
        self._cfg = cfg
        self._server: subprocess.Popen[bytes] | None = None
        self._pipeline: Any = None

    def start(self) -> Mapping[str, Any]:
        config = self._cfg.inference_config
        plan = build_server_plan(Path(self._cfg.weights_dir), config)
        command = plan["argv"]
        if entrypoint_owns_the_server():
            # D19: entrypoint.sh started the service, proved it ready and traps
            # its own exit to stop it. Re-probe so a service that died between
            # that poll and load() is a MODEL_LOAD failure, then leave it alone.
            _wait_for_http(plan["ready_probe"], READY_DEADLINE_FLOOR_SECONDS)
            managed_by = ENTRYPOINT_MANAGED
        else:
            self._server = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            _wait_for_http(plan["ready_probe"], int(plan["ready_timeout_seconds"]))
            managed_by = "adapter"

        # Only present inside the runtime image; mypy runs on a CPU box.
        from paddleocr import (  # type: ignore[import-not-found]
            PaddleOCRVL,
        )

        options: dict[str, Any] = {
            "pipeline_version": config["pipeline_version"],
            "device": config["device"],
            "vl_rec_backend": config["vl_rec_backend"],
            "vl_rec_server_url": config["vl_rec_server_url"],
            "vl_rec_max_concurrency": config["vl_rec_max_concurrency"],
            "vl_rec_api_model_name": config["vl_rec_api_model_name"],
        }
        self._pipeline = PaddleOCRVL(**options)
        return {
            "genai_server_command": command,
            "pipeline_options": options,
            "server_managed_by": managed_by,
        }

    def predict(self, image_path: Path) -> Sequence[tuple[Mapping[str, Any], str]]:
        if self._pipeline is None:
            raise AdapterError("MODEL_LOAD", "PaddleOCR-VL pipeline was never started")
        pages: list[tuple[Mapping[str, Any], str]] = []
        for item in self._pipeline.predict(str(image_path)):
            value = getattr(item, "json", None)
            value = value() if callable(value) else value
            if not isinstance(value, dict):
                raise AdapterError("OUTPUT_MALFORMED", "PaddleX result exposes no JSON object")
            markdown = getattr(item, "markdown", None)
            markdown = markdown() if callable(markdown) else markdown
            text = markdown_payload(markdown)
            if not text:
                payload = value.get("res", value)
                nested = payload.get("markdown") if isinstance(payload, dict) else None
                text = markdown_payload(nested)
            pages.append((value, text))
        return pages

    def close(self) -> None:
        self._pipeline = None
        server = self._server
        self._server = None
        if server is None or server.poll() is not None:
            return
        server.terminate()
        try:
            server.wait(timeout=30)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=30)


def _default_backend_factory(cfg: AdapterConfig) -> PaddleVlBackend:
    return _OfficialPaddleVlBackend(cfg)


class PaddleOcrVlAdapter:
    """Implements ``arena.worker.adapter_api.ArenaModelAdapter``."""

    model_key = MODEL_KEY

    def __init__(
        self,
        backend_factory: Callable[[AdapterConfig], PaddleVlBackend] | None = None,
    ) -> None:
        self._backend_factory = backend_factory or _default_backend_factory
        self._backend: PaddleVlBackend | None = None
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
                "PaddleOCR-VL takes no user prompt; its prompt is fixed inside the "
                "official pipeline. A non-empty prompt would leave the official path.",
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
            "base_image": spec["base_image"],
            "base_image_digest": os.environ.get(
                "ARENA_IMAGE_DIGEST", provenance.get("base_image_digest")
            ),
            "runtime_source_repository": provenance.get("runtime_source_repository"),
            "runtime_source_revision": provenance.get("runtime_source_revision"),
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
        started = time.perf_counter()
        try:
            pages = backend.predict(page.image_path)
        except AdapterError:
            raise
        except Exception as exc:
            raise AdapterError(classify_exception(exc), f"{type(exc).__name__}: {exc}") from exc
        inference_ms = int((time.perf_counter() - started) * 1000)

        page_markdown = [text for _, text in pages]
        raw_text = "\n\n".join(text for text in page_markdown if text.strip())
        warnings: list[str] = []
        if not pages:
            warnings.append("no_pages_returned")
        if not raw_text.strip():
            warnings.append("empty_output")
        # ARENA_CONTRACT D3: the semantic verdict this adapter can actually see.
        # An empty page is a SUCCESS with OUTPUT_EMPTY (masterplan section 41),
        # not an operational failure. The pipeline returns whole pages rather
        # than a token stream, so truncation is not observable here and the
        # field stays None instead of guessing.
        semantic_error_class = "OUTPUT_EMPTY" if not raw_text.strip() else None
        return RawOutput(
            raw_text=raw_text,
            output_format="markdown",
            native_json={
                "pages": [dict(payload) for payload, _ in pages],
                "page_markdown": page_markdown,
            },
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
    """Section 38 provenance. A package that is absent is null, never "0"."""
    import importlib.metadata

    versions: dict[str, str | None] = {}
    for name in ("paddleocr", "paddlepaddle-gpu", "paddlex", "vllm", "transformers", "torch"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def create_adapter(
    backend_factory: Callable[[AdapterConfig], PaddleVlBackend] | None = None,
) -> PaddleOcrVlAdapter:
    """Factory the worker server calls; tests inject a fake backend here."""
    return PaddleOcrVlAdapter(backend_factory=backend_factory)


def render_server_plan(weights_dir: Path | None = None) -> str:
    """The launch plan as the tab-separated lines ``entrypoint.sh`` parses.

    One record per line: ``probe``, ``timeout``, ``env`` (``KEY=VALUE``) and one
    ``argv`` per argument. No value may contain a tab or a newline; every value
    comes from runtime.json, and anything else is refused here rather than
    letting the shell mis-split it.
    """
    if weights_dir is None:
        raw = os.environ.get("ARENA_WEIGHTS_DIR", "").strip()
        if not raw:
            raise AdapterError(
                "DEPENDENCY",
                "ARENA_WEIGHTS_DIR is unset; the server plan needs the weights directory",
            )
        weights_dir = Path(raw)
    plan = build_server_plan(weights_dir, runtime_spec()["inference_config"])
    lines = [
        f"probe\t{plan['ready_probe']}",
        f"timeout\t{int(plan['ready_timeout_seconds'])}",
    ]
    lines.extend(f"env\t{key}={value}" for key, value in sorted(plan["env"].items()))
    lines.extend(f"argv\t{argument}" for argument in plan["argv"])
    for line in lines:
        if "\n" in line or line.count("\t") != 1:
            raise AdapterError("DEPENDENCY", f"server plan line is not shell-safe: {line!r}")
    return "\n".join(lines) + "\n"


def _main(argv: list[str]) -> int:
    """`python adapter.py --print-server-plan` for entrypoint.sh (D19).

    Nothing heavy is imported on this path: it reads runtime.json and prints.
    """
    if argv != ["--print-server-plan"]:
        sys.stderr.write("usage: adapter.py --print-server-plan\n")
        return 2
    sys.stdout.write(render_server_plan())
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised by entrypoint.sh on the pod
    raise SystemExit(_main(sys.argv[1:]))
