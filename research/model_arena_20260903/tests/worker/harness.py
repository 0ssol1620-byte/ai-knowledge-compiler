"""Start a real worker process-in-thread against a temporary runtime directory.

Everything a pod would provide is faked with files on disk: a runtime
directory holding ``runtime.json``/``adapter.py``/(optionally)``canonical.py``,
a state directory, and a process environment. The server itself is the real
one, bound to a loopback port, driven over real HTTP.
"""

from __future__ import annotations

import base64
import hashlib
import http.client
import json
import secrets
import socket
import threading
from collections.abc import Iterator, Mapping
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from arena.constants import CAMPAIGN_ID
from arena.worker.config import WorkerEnv
from arena.worker.server import ArenaHTTPServer, WorkerCore, create_server
from arena.worker.synthetic import render_synthetic_page
from arena.worker.util import config_sha256, sha256_label, utcnow

TESTS_DIR = Path(__file__).resolve().parent
MODEL_KEY = "paddleocr_vl_1_6"
MODEL_REVISION = "a" * 40
IMAGE_DIGEST = "sha256:" + "b" * 64

ADAPTER_SOURCE = '''"""Generated runtime adapter for the worker tests."""
from __future__ import annotations

import sys

if {tests_dir!r} not in sys.path:
    sys.path.insert(0, {tests_dir!r})

from fake_adapter import FakeAdapter


def create_adapter() -> FakeAdapter:
    return FakeAdapter()
'''

UPPERCASE_CANONICAL_SOURCE = '''"""Runtime canonicalizer that proves the runtime copy wins."""
from __future__ import annotations

from arena.worker.adapter_api import CanonicalOutput, RawOutput


def canonicalize(raw: RawOutput) -> CanonicalOutput:
    return CanonicalOutput(
        markdown=raw.raw_text.upper(),
        elements=None,
        conversion_notes=("uppercased-by-runtime",),
        lossy=True,
    )
'''

FAILING_CANONICAL_SOURCE = '''"""Runtime canonicalizer that always blows up."""
from __future__ import annotations

from arena.worker.adapter_api import CanonicalOutput, RawOutput


def canonicalize(raw: RawOutput) -> CanonicalOutput:
    raise RuntimeError("canonicalizer exploded on purpose")
'''


def free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def runtime_descriptor(**overrides: Any) -> dict[str, Any]:
    descriptor: dict[str, Any] = {
        "model_key": MODEL_KEY,
        "display_name": "Fake runtime for worker tests",
        "model_repo": "example-org/fake-model",
        "model_revision": MODEL_REVISION,
        "official_runtime": "custom",
        "runtime_version": "0.0.0",
        "base_image": "example/base@sha256:" + "c" * 64,
        "gpu_min_vram_gb": 24,
        "gpu_pool_priority": ["NVIDIA L40S"],
        "max_concurrency_per_worker": 2,
        "shard_size_hint": 100,
        "per_page_timeout_seconds": 30,
        "prompt_id": "fake_prompt_v1",
        "prompt_kind": "text",
        "inference_config": {"max_new_tokens": 4096},
        "weights": {
            "repo": "example-org/fake-model",
            "revision": MODEL_REVISION,
            "largest_file": "model.safetensors",
            "largest_file_sha256": "sha256:" + "d" * 64,
        },
        "weights_strategy": "baked",
        "runtime_mode_allowed": ["baked"],
        "official_source_urls": [],
        "license": {"id": "Apache-2.0", "url": "", "status": "unverified"},
        "notes": "test fixture",
    }
    descriptor.update(overrides)
    return descriptor


@dataclass
class WorkerHandle:
    core: WorkerCore
    server: ArenaHTTPServer
    token: str
    host: str
    port: int
    state_dir: Path
    runtime_dir: Path
    descriptor: dict[str, Any]
    prompt_sha256: str | None = None
    _counter: list[int] = field(default_factory=lambda: [0])

    # -- HTTP --------------------------------------------------------------

    def request(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None = None,
        *,
        token: str | None = None,
        send_auth: bool = True,
    ) -> tuple[int, Any]:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers: dict[str, str] = {}
        if send_auth:
            headers["Authorization"] = f"Bearer {self.token if token is None else token}"
        if body is not None:
            headers["Content-Type"] = "application/json"
        connection = http.client.HTTPConnection(self.host, self.port, timeout=60)
        try:
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            status = response.status
            raw = response.read().decode("utf-8")
        finally:
            connection.close()
        try:
            return status, json.loads(raw)
        except json.JSONDecodeError:
            return status, raw

    def get(self, path: str, **kwargs: Any) -> tuple[int, Any]:
        return self.request("GET", path, None, **kwargs)

    def post(
        self, path: str, payload: Mapping[str, Any] | None = None, **kwargs: Any
    ) -> tuple[int, Any]:
        return self.request("POST", path, payload, **kwargs)

    # -- helpers -----------------------------------------------------------

    def wait_for_stage(self, stages: tuple[str, ...], timeout: float = 30.0) -> dict[str, Any]:
        ticker = threading.Event()
        waited = 0.0
        step = 0.02
        body: Any = None
        while waited <= timeout:
            status, body = self.get("/v1/ready")
            assert status == 200, body
            if body["stage"] in stages:
                return dict(body)
            ticker.wait(step)
            waited += step
        raise AssertionError(f"worker never reached {stages}; last body={body}")

    def next_job_id(self) -> str:
        self._counter[0] += 1
        seed = f"{self.port}:{self._counter[0]}:{utcnow()}"
        return hashlib.sha256(seed.encode("utf-8")).hexdigest()

    def run_payload(self, **overrides: Any) -> dict[str, Any]:
        image = render_synthetic_page(width=480, height=640)
        payload: dict[str, Any] = {
            "campaign_id": CAMPAIGN_ID,
            "inference_job_id": self.next_job_id(),
            "sample_id": "omnidoc:images/PPT_1001115_eng_page_003",
            "case_key": "omnidocbench-58851882e7b39101a6f5756c",
            "benchmark": "omnidoc",
            "source_sha256": sha256_label(image),
            "image_b64": base64.b64encode(image).decode("ascii"),
            "width": 480,
            "height": 640,
            "prompt_id": str(self.descriptor["prompt_id"]),
            "prompt_sha256": self.prompt_sha256 or ("sha256:" + "d" * 64),
            "inference_config_sha256": config_sha256(self.descriptor["inference_config"]),
            "job_kind": "inference",
            "metadata": {"page_index": 0, "media_type": "pdf"},
        }
        payload.update(overrides)
        return payload


@contextmanager
def worker(
    tmp_path: Path,
    *,
    descriptor_overrides: Mapping[str, Any] | None = None,
    env_overrides: Mapping[str, str] | None = None,
    canonical_source: str | None = None,
    prompt_text: str | None = None,
    write_prompt: bool = True,
    prompt_via_env_file: bool = False,
    start: bool = True,
    wait_ready: bool = True,
) -> Iterator[WorkerHandle]:
    """A real worker over a temporary runtime directory.

    ``prompt_text`` defaults to a non-empty prompt for ``prompt_kind`` text and
    toolkit, and to the empty string for ``none`` (D34). ``write_prompt=False``
    leaves the registry file absent so a test can prove the worker fails closed;
    ``prompt_via_env_file=True`` routes through the ``ARENA_PROMPT_FILE``
    override instead of ``<registry>/<prompt_id>.txt``.
    """
    runtime_dir = tmp_path / "runtime"
    state_dir = tmp_path / "state"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)

    descriptor = runtime_descriptor(**dict(descriptor_overrides or {}))
    (runtime_dir / "runtime.json").write_text(
        json.dumps(descriptor, indent=2, sort_keys=True), encoding="utf-8"
    )
    (runtime_dir / "adapter.py").write_text(
        ADAPTER_SOURCE.format(tests_dir=str(TESTS_DIR)), encoding="utf-8"
    )
    if canonical_source is not None:
        (runtime_dir / "canonical.py").write_text(canonical_source, encoding="utf-8")

    # ARENA_CONTRACT 11.5 D17: prompt_registry/<prompt_id>.txt, resolved from
    # runtime.json's prompt_id. There is no "worker without a prompt" state.
    registry_dir = tmp_path / "prompt_registry"
    registry_dir.mkdir(parents=True, exist_ok=True)
    if prompt_text is None:
        prompt_text = "" if descriptor.get("prompt_kind") == "none" else "Transcribe this page.\n"
    prompt_path = (
        (tmp_path / "prompt-override.txt")
        if prompt_via_env_file
        else registry_dir / f"{descriptor['prompt_id']}.txt"
    )
    prompt_sha: str | None = None
    if write_prompt:
        # write_bytes, not write_text: on Windows text mode turns "\n" into
        # "\r\n" and the worker would hash different bytes than the controller.
        prompt_path.write_bytes(prompt_text.encode("utf-8"))
        prompt_sha = sha256_label(prompt_path.read_bytes())

    port = free_port()
    token = secrets.token_urlsafe(24)
    environment: dict[str, str] = {
        "ARENA_WORKER_TOKEN": token,
        "ARENA_MODEL_KEY": str(descriptor["model_key"]),
        "ARENA_MODEL_REVISION": str(descriptor["model_revision"]),
        "ARENA_RUNTIME_MODE": "baked",
        "ARENA_IMAGE_DIGEST": IMAGE_DIGEST,
        "ARENA_CAMPAIGN_ID": CAMPAIGN_ID,
        "ARENA_RUNTIME_DIR": str(runtime_dir),
        "ARENA_PROMPT_REGISTRY_DIR": str(registry_dir),
        "ARENA_STATE_DIR": str(state_dir),
        "ARENA_WORKER_HOST": "127.0.0.1",
        "ARENA_WORKER_PORT": str(port),
        "ARENA_WORKER_ID": f"{descriptor['model_key']}-w0-test",
        "ARENA_GPU_TYPE": "NVIDIA L40S",
        "RUNPOD_POD_ID": "pod-test",
        # Provenance shells out to pip freeze; keep the suite fast and let the
        # provenance test opt back in.
        "ARENA_PROVENANCE_AT_STARTUP": "0",
    }
    if prompt_via_env_file:
        environment["ARENA_PROMPT_FILE"] = str(prompt_path)
    environment.update(dict(env_overrides or {}))

    env = WorkerEnv.from_env(environment)
    server, core = create_server(env)
    handle = WorkerHandle(
        core=core,
        server=server,
        token=env.token,
        host="127.0.0.1",
        port=env.port,
        state_dir=state_dir,
        runtime_dir=runtime_dir,
        descriptor=descriptor,
        prompt_sha256=prompt_sha,
    )
    thread = threading.Thread(target=server.serve_forever, name="arena-test-http", daemon=True)
    thread.start()
    try:
        if start:
            core.start()
            if wait_ready:
                handle.wait_for_stage(("READY", "CRASHED"))
        yield handle
    finally:
        server.shutdown()
        core.stop()
        server.server_close()
        thread.join(timeout=10)
