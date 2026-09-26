"""HPD-Parsing arena adapter - official customized-vLLM image + documented API.

Masterplan section 15.1 singles this model out: its engine is a customized vLLM
build (0.17.1 + dynamic request forking + P-MTP speculative decoding), so the
official Docker image is the runtime and nothing is compiled on the pod.

The documented inference surface is an OpenAI-compatible chat completion with a
fixed prompt, ``document parsing with fork.``, and a single base64 PNG. The
adapter speaks that HTTP API with the standard library rather than the ``openai``
package: the API is the contract, and the worker must run with stdlib + pillow
plus whatever the image already ships (ARENA_CONTRACT.md section 0).

No heavy import happens at module import time.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
import urllib.error
import urllib.request
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

MODEL_KEY = "hpd_parsing"
REVISION_STAMP = "arena-weights-revision.txt"

# ARENA_CONTRACT D34 - prompt_kind "text".
#
# This is the exact text the adapter sends and the exact text that must be in
# prompt_registry/<runtime.json prompt_id>.txt. It is a module-level constant so
# the registry lane can read it without executing anything: the prompt is not
# built, templated or formatted anywhere in this file.
OFFICIAL_PROMPT = "document parsing with fork."
PROMPT_KIND = "text"
OUTPUT_FORMAT = "hpd_blocks"

# The entrypoint exports this when it owns the model-server process (D19).
SERVER_MANAGED_BY_ENV = "ARENA_MODEL_SERVER_MANAGED_BY"
ENTRYPOINT_MANAGED = "entrypoint"
# D19 floor: never treat a server as failed before twenty minutes have passed.
READY_DEADLINE_FLOOR_SECONDS = 1200


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
    provenance, cross-checks and open questions live beside it rather than
    being dropped.
    """
    path = Path(__file__).with_name("provenance.json")
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise AdapterError("DEPENDENCY", f"{path} must hold a JSON object")
    return document


class HpdBackend(Protocol):
    """The narrow surface the adapter needs from the official server."""

    def start(self) -> Mapping[str, Any]:
        """Bring the engine up and return provenance."""

    def complete(self, image_b64: str) -> Mapping[str, Any]:
        """Return the OpenAI-compatible chat completion payload."""

    def close(self) -> None: ...


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
    """Fail closed unless the pinned revision and both checkpoints are present."""
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
    # The official tutorial requires both config.json files to exist and the
    # directory layout to stay intact; P-MTP is the speculative decoding model.
    for relative in ("config.json", "P-MTP/config.json"):
        if not (weights_dir / relative).is_file():
            raise AdapterError("MODEL_LOAD", f"required file {relative} is missing")
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
    if "shape" in text and ("mismatch" in text or "invalid" in text):
        return "TENSOR_SHAPE"
    if isinstance(exc, urllib.error.HTTPError):
        return "OUTPUT_MALFORMED" if 400 <= exc.code < 500 else "INFRA_NETWORK"
    if isinstance(exc, (OSError, urllib.error.URLError)):
        return "INFRA_NETWORK"
    if isinstance(exc, (ValueError, TypeError, KeyError)):
        return "OUTPUT_MALFORMED"
    return "UNKNOWN"


def build_request_body(
    image_b64: str, config: Mapping[str, Any], prompt_text: str = OFFICIAL_PROMPT
) -> dict[str, Any]:
    """Exactly the body the official client example sends.

    D34 prompt_kind "text": the text sent is ``AdapterConfig.prompt_text``,
    which ``load()`` has already refused unless it equals ``OFFICIAL_PROMPT``.
    The default keeps the constant readable for the registry lane.
    """
    if not prompt_text:
        raise AdapterError("MODEL_LOAD", "HPD-Parsing refuses an empty prompt (D34)")
    return {
        "model": str(config["served_model_name"]),
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{image_b64}"},
                    },
                    {"type": "text", "text": prompt_text},
                ],
            }
        ],
        "max_tokens": int(config["max_tokens"]),
        "temperature": config["temperature"],
    }


def read_completion(payload: Mapping[str, Any]) -> tuple[str, str | None, Mapping[str, Any]]:
    """(text, finish_reason, usage) from an OpenAI-compatible response."""
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise AdapterError("OUTPUT_MALFORMED", "chat completion carried no choices")
    first = choices[0]
    if not isinstance(first, Mapping):
        raise AdapterError("OUTPUT_MALFORMED", "chat completion choice is not an object")
    message = first.get("message")
    content = message.get("content") if isinstance(message, Mapping) else None
    if content is None:
        content = ""
    if not isinstance(content, str):
        raise AdapterError("OUTPUT_MALFORMED", "chat completion content is not a string")
    finish = first.get("finish_reason")
    usage = payload.get("usage")
    return content, finish if isinstance(finish, str) else None, (
        dict(usage) if isinstance(usage, Mapping) else {}
    )


def _wait_for_http(url: str, timeout_seconds: int) -> None:
    deadline = time.monotonic() + timeout_seconds
    last = "no attempt made"
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
    raise AdapterError("MODEL_LOAD", f"HPD-Parsing engine never became ready at {url}: {last}")


def build_server_plan(
    weights_dir: Path, inference_config: Mapping[str, Any]
) -> dict[str, Any]:
    """The `vllm serve` launch plan: argv, env, readiness probe and deadline.

    ARENA_CONTRACT D19 moved process ownership of the model server from the
    adapter to ``entrypoint.sh``. Both callers render the command from this one
    builder - ``entrypoint.sh`` through ``adapter.py --print-server-plan`` and
    ``_OfficialHpdBackend`` when nothing else started the server - so the two
    cannot drift into launching different engines.
    """
    server = dict(inference_config["server"])
    model_path = str(weights_dir)
    speculative = dict(server["speculative_config"])
    speculative["model"] = str(Path(model_path) / "P-MTP")
    argv = [
        "vllm",
        "serve",
        model_path,
        "--trust-remote-code",
        "--port",
        str(server.get("port", inference_config["port"])),
        "--served-model-name",
        str(inference_config["served_model_name"]),
        "--max-model-len",
        str(server["max_model_len"]),
        "--limit-mm-per-prompt",
        json.dumps(server["limit_mm_per_prompt"], separators=(",", ":")),
        "--gpu-memory-utilization",
        str(server["gpu_memory_utilization"]),
        "--attention-backend",
        str(server["attention_backend"]),
        "--attention-config",
        json.dumps(server["attention_config"], separators=(",", ":")),
        "--enable-chunked-prefill",
        "--enable-prefix-caching",
        "--speculative-config",
        json.dumps(speculative, separators=(",", ":")),
    ]
    return {
        "argv": argv,
        "env": {str(k): str(v) for k, v in dict(server["env"]).items()},
        "ready_probe": str(server["ready_probe"]),
        "ready_timeout_seconds": max(
            int(server["ready_timeout_seconds"]), READY_DEADLINE_FLOOR_SECONDS
        ),
    }


def entrypoint_owns_the_server() -> bool:
    """True when entrypoint.sh already started the model server (D19)."""
    return os.environ.get(SERVER_MANAGED_BY_ENV, "").strip().lower() == ENTRYPOINT_MANAGED


class _OfficialHpdBackend:
    """`vllm serve` with the documented flags, then the documented HTTP API."""

    def __init__(self, cfg: AdapterConfig) -> None:
        self._cfg = cfg
        self._server: subprocess.Popen[bytes] | None = None
        self._timeout = int(runtime_spec()["per_page_timeout_seconds"])

    def start(self) -> Mapping[str, Any]:
        config = self._cfg.inference_config
        plan = build_server_plan(Path(self._cfg.weights_dir), config)
        if entrypoint_owns_the_server():
            # D19: entrypoint.sh started the engine, proved it ready and traps
            # its own exit to stop it. Re-probe here so a server that died
            # between the entrypoint's poll and load() is a MODEL_LOAD failure
            # rather than a per-page one, then leave the process alone.
            _wait_for_http(plan["ready_probe"], READY_DEADLINE_FLOOR_SECONDS)
            return {
                "server_command": plan["argv"],
                "server_env": sorted(plan["env"]),
                "server_managed_by": ENTRYPOINT_MANAGED,
            }
        env = dict(os.environ)
        env.update(plan["env"])
        self._server = subprocess.Popen(
            plan["argv"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _wait_for_http(plan["ready_probe"], int(plan["ready_timeout_seconds"]))
        return {
            "server_command": plan["argv"],
            "server_env": sorted(plan["env"]),
            "server_managed_by": "adapter",
        }

    def complete(self, image_b64: str) -> Mapping[str, Any]:
        config = self._cfg.inference_config
        body = json.dumps(
            build_request_body(image_b64, config, self._cfg.prompt_text)
        ).encode("utf-8")
        url = f"{str(config['server_url']).rstrip('/')}/chat/completions"
        request = urllib.request.Request(  # noqa: S310 - loopback URL from runtime.json
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self._timeout) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict):
            raise AdapterError("OUTPUT_MALFORMED", "chat completion is not a JSON object")
        return payload

    def close(self) -> None:
        server = self._server
        self._server = None
        if server is None or server.poll() is not None:
            return
        server.terminate()
        try:
            server.wait(timeout=60)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=60)


def _default_backend_factory(cfg: AdapterConfig) -> HpdBackend:
    return _OfficialHpdBackend(cfg)


class HpdParsingAdapter:
    """Implements ``arena.worker.adapter_api.ArenaModelAdapter``."""

    model_key = MODEL_KEY

    def __init__(
        self,
        backend_factory: Callable[[AdapterConfig], HpdBackend] | None = None,
    ) -> None:
        self._backend_factory = backend_factory or _default_backend_factory
        self._backend: HpdBackend | None = None
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
        if cfg.prompt_text != OFFICIAL_PROMPT:
            raise AdapterError(
                "MODEL_LOAD",
                "HPD-Parsing fixes its prompt at 'document parsing with fork.'; "
                f"got {cfg.prompt_text!r}",
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
            "runtime_dependency_pins": dict(provenance.get("runtime_dependency_pins", {})),
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
            schema_valid=raw.output_format == OUTPUT_FORMAT,
            peak_vram_mb=raw.peak_vram_mb,
        )

    def infer(self, page: PageInput) -> RawOutput:
        backend = self._backend
        if backend is None:
            raise AdapterError("MODEL_LOAD", "infer() called before load()")
        if not page.image_path.is_file():
            raise AdapterError("INPUT_DECODE", f"page image {page.image_path} does not exist")
        try:
            image_b64 = base64.b64encode(page.image_path.read_bytes()).decode("ascii")
        except OSError as exc:
            raise AdapterError("INPUT_DECODE", f"{type(exc).__name__}: {exc}") from exc

        started = time.perf_counter()
        try:
            payload = backend.complete(image_b64)
        except AdapterError:
            raise
        except Exception as exc:
            raise AdapterError(classify_exception(exc), f"{type(exc).__name__}: {exc}") from exc
        inference_ms = int((time.perf_counter() - started) * 1000)

        text, finish_reason, usage = read_completion(payload)
        warnings: list[str] = []
        if finish_reason == "length":
            warnings.append("output_truncated")
        if not text.strip():
            warnings.append("empty_output")
        elif "<BLOCK>" not in text:
            warnings.append("no_block_markers")
        # ARENA_CONTRACT D3. Three conditions are visible from the server's own
        # response and none of them is inferred: an empty body, a completion the
        # engine stopped at max_tokens, and a non-empty body carrying none of the
        # <BLOCK> markers the official tutorial defines as this model's format.
        # Emptiness wins over truncation because it is the more specific fact.
        semantic_error_class: str | None = None
        if not text.strip():
            semantic_error_class = "OUTPUT_EMPTY"
        elif finish_reason == "length":
            semantic_error_class = "OUTPUT_TRUNCATED"
        elif "<BLOCK>" not in text:
            semantic_error_class = "OUTPUT_MALFORMED"
        return RawOutput(
            raw_text=text,
            output_format=OUTPUT_FORMAT,
            native_json={"finish_reason": finish_reason, "response": dict(payload)},
            usage=usage,
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
    for name in ("vllm", "torch", "transformers", "flashinfer-python"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def create_adapter(
    backend_factory: Callable[[AdapterConfig], HpdBackend] | None = None,
) -> HpdParsingAdapter:
    return HpdParsingAdapter(backend_factory=backend_factory)


def render_server_plan(weights_dir: Path | None = None) -> str:
    """The launch plan as the tab-separated lines ``entrypoint.sh`` parses.

    One record per line: ``probe``, ``timeout``, ``env`` (``KEY=VALUE``) and one
    ``argv`` per argument. No value may contain a tab or a newline; the builder
    emits only values that come from runtime.json, and this function refuses
    anything else rather than letting the shell mis-split it.
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
