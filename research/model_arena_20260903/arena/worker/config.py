"""Worker startup configuration: process environment plus ``runtime.json``.

Two independent sources, deliberately loaded at two different moments:

* :class:`WorkerEnv` is read once, synchronously, before the socket is bound.
  A missing ``ARENA_WORKER_TOKEN`` is fatal here — an unauthenticated worker
  would accept jobs from anyone, so it must not start at all.
* :func:`load_runtime_config` runs inside the readiness thread. Anything wrong
  with the runtime directory leaves the process up in ``CRASHED`` so the
  controller can read the diagnosis over ``/v1/ready``.

:func:`resolve_prompt` belongs to the second group and needs both: the prompt
id and kind come from ``runtime.json``, the registry location from the pod
environment (ARENA_CONTRACT 11.5 D17/D34).
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from arena.constants import CAMPAIGN_ID, WORKER_PORT
from arena.worker.util import config_sha256, sha256_label

RUNTIME_MODES: Final = ("baked", "bootstrap", "subscription")
DEFAULT_RUNTIME_DIR: Final = Path("/opt/arena/runtime")
DEFAULT_STATE_DIR: Final = Path("/workspace/arena")
RUNTIME_JSON_NAME: Final = "runtime.json"

# ARENA_CONTRACT 11.5 D17: the prompt registry travels with the pod -- the
# bundle carries ``prompt_registry/`` and every baked Dockerfile copies it to
# ``/opt/arena/prompt_registry/``. The worker resolves the prompt from
# ``<registry>/<prompt_id>.txt`` where ``prompt_id`` comes from runtime.json.
DEFAULT_PROMPT_REGISTRY_DIR: Final = Path("/opt/arena/prompt_registry")

# ARENA_CONTRACT 11.5 D34. ``text``: the adapter sends AdapterConfig.prompt_text,
# which must be non-empty and equal the registry file. ``toolkit``: the official
# toolkit builds the prompt at run time and the adapter hashes what it built.
# ``none``: a pipeline with no prompt; the registry file is empty.
PROMPT_KINDS: Final = ("text", "toolkit", "none")

# ARENA_CONTRACT 11.5 D19: a runtime whose entrypoint starts a local model
# server (vLLM, paddlex) can answer "connection refused" for as long as the
# weights take to load. 20 minutes is the floor the decision names for the
# 7B-class models; the pod environment may raise it.
DEFAULT_MODEL_SERVER_WAIT_SECONDS: Final = 1200.0
DEFAULT_MODEL_SERVER_POLL_SECONDS: Final = 5.0

# ARENA_CONTRACT 11.5 D20: belt-and-braces beside the controller watchdog. The
# grace is how long a page already in flight may finish after the drain.
DEFAULT_POD_AGE_DRAIN_SECONDS: Final = 300.0

# D47: entrypoint.sh writes this file (reason + last 200 server-log lines) and
# sleeps forever when the model server dies or never becomes ready. The worker
# checks for it before ``_prepare`` loads anything, and on every /v1/ready
# call, so it never reports healthy over a runtime the entrypoint has already
# condemned.
DEFAULT_FATAL_FILE: Final = Path("/opt/arena/FATAL")

_TRUTHY: Final = frozenset({"1", "true", "yes", "on"})
_FALSY: Final = frozenset({"0", "false", "no", "off"})


class WorkerConfigError(RuntimeError):
    """Startup configuration is missing, malformed or internally inconsistent."""


def _required(env: Mapping[str, str], name: str) -> str:
    value = (env.get(name) or "").strip()
    if not value:
        raise WorkerConfigError(f"{name} is required and must not be empty")
    return value


def _flag(env: Mapping[str, str], name: str, *, default: bool) -> bool:
    raw = (env.get(name) or "").strip().lower()
    if not raw:
        return default
    if raw in _TRUTHY:
        return True
    if raw in _FALSY:
        return False
    raise WorkerConfigError(f"{name} must be one of {sorted(_TRUTHY | _FALSY)}, got {raw!r}")


def _positive_float(env: Mapping[str, str], name: str, *, default: float | None) -> float | None:
    """A positive number from the environment, or ``default`` when unset.

    Fail closed on garbage: a pod that read ``ARENA_MAX_POD_AGE_HOURS=six`` and
    silently fell back to "no limit" would keep billing after its deadline.
    """
    raw = (env.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise WorkerConfigError(f"{name} must be a number, got {raw!r}") from exc
    if value <= 0 or value != value or value == float("inf"):
        raise WorkerConfigError(f"{name} must be a finite positive number, got {raw!r}")
    return value


def _require_float(value: float | None) -> float:
    """Narrow a ``_positive_float`` call that was given a non-None default."""
    if value is None:  # pragma: no cover - only reachable on a coding error here
        raise WorkerConfigError("internal: a defaulted numeric setting resolved to None")
    return value


@dataclass(frozen=True, slots=True)
class WorkerEnv:
    """Everything the worker learns from its process environment."""

    model_key: str
    model_revision: str
    runtime_mode: str
    image_digest: str
    campaign_id: str
    runtime_dir: Path
    state_dir: Path
    # An explicit override. When it is None the prompt is resolved from the
    # registry directory and runtime.json's prompt_id (D17).
    prompt_file: Path | None
    prompt_registry_dir: Path
    weights_dir: Path | None
    fatal_file: Path
    worker_id: str
    pod_id: str | None
    gpu_type: str | None
    host: str
    port: int
    collect_provenance_at_startup: bool
    # D19: how long readiness may wait for a local model server that is still
    # loading (connection refused), and how often it retries.
    model_server_wait_seconds: float
    model_server_poll_seconds: float
    # D20: the pod's own lifetime fuse. ``None`` means the controller watchdog
    # is the only limit.
    max_pod_age_hours: float | None
    pod_age_drain_seconds: float
    device: str = "cuda:0"
    # Never logged, never serialized, never returned by ``public()``.
    token: str = field(repr=False, default="")

    @staticmethod
    def from_env(env: Mapping[str, str] | None = None) -> WorkerEnv:
        source: Mapping[str, str] = os.environ if env is None else env
        model_key = _required(source, "ARENA_MODEL_KEY")
        runtime_mode = _required(source, "ARENA_RUNTIME_MODE")
        if runtime_mode not in RUNTIME_MODES:
            raise WorkerConfigError(
                f"ARENA_RUNTIME_MODE must be one of {list(RUNTIME_MODES)}, got {runtime_mode!r}"
            )
        pod_id = (source.get("RUNPOD_POD_ID") or "").strip() or None
        worker_index = (source.get("ARENA_WORKER_INDEX") or "0").strip()
        default_worker_id = f"{model_key}-w{worker_index}-{pod_id or 'local'}"
        prompt_file_raw = (source.get("ARENA_PROMPT_FILE") or "").strip()
        prompt_registry_raw = (source.get("ARENA_PROMPT_REGISTRY_DIR") or "").strip()
        weights_dir_raw = (source.get("ARENA_WEIGHTS_DIR") or "").strip()
        port_raw = (source.get("ARENA_WORKER_PORT") or "").strip()
        try:
            port = int(port_raw) if port_raw else WORKER_PORT
        except ValueError as exc:
            raise WorkerConfigError(f"ARENA_WORKER_PORT must be an integer: {port_raw!r}") from exc
        return WorkerEnv(
            model_key=model_key,
            model_revision=_required(source, "ARENA_MODEL_REVISION"),
            runtime_mode=runtime_mode,
            image_digest=_required(source, "ARENA_IMAGE_DIGEST"),
            campaign_id=(source.get("ARENA_CAMPAIGN_ID") or "").strip() or CAMPAIGN_ID,
            runtime_dir=Path(
                (source.get("ARENA_RUNTIME_DIR") or "").strip() or DEFAULT_RUNTIME_DIR
            ),
            state_dir=Path((source.get("ARENA_STATE_DIR") or "").strip() or DEFAULT_STATE_DIR),
            prompt_file=Path(prompt_file_raw) if prompt_file_raw else None,
            prompt_registry_dir=Path(prompt_registry_raw or DEFAULT_PROMPT_REGISTRY_DIR),
            weights_dir=Path(weights_dir_raw) if weights_dir_raw else None,
            fatal_file=Path((source.get("ARENA_FATAL_FILE") or "").strip() or DEFAULT_FATAL_FILE),
            worker_id=(source.get("ARENA_WORKER_ID") or "").strip() or default_worker_id,
            pod_id=pod_id,
            gpu_type=(source.get("ARENA_GPU_TYPE") or "").strip() or None,
            host=(source.get("ARENA_WORKER_HOST") or "").strip() or "0.0.0.0",
            port=port,
            collect_provenance_at_startup=_flag(
                source, "ARENA_PROVENANCE_AT_STARTUP", default=True
            ),
            model_server_wait_seconds=_require_float(
                _positive_float(
                    source,
                    "ARENA_MODEL_SERVER_WAIT_SECONDS",
                    default=DEFAULT_MODEL_SERVER_WAIT_SECONDS,
                )
            ),
            model_server_poll_seconds=_require_float(
                _positive_float(
                    source,
                    "ARENA_MODEL_SERVER_POLL_SECONDS",
                    default=DEFAULT_MODEL_SERVER_POLL_SECONDS,
                )
            ),
            max_pod_age_hours=_positive_float(source, "ARENA_MAX_POD_AGE_HOURS", default=None),
            pod_age_drain_seconds=_require_float(
                _positive_float(
                    source,
                    "ARENA_POD_AGE_DRAIN_SECONDS",
                    default=DEFAULT_POD_AGE_DRAIN_SECONDS,
                )
            ),
            device=(source.get("ARENA_DEVICE") or "").strip() or "cuda:0",
            token=_required(source, "ARENA_WORKER_TOKEN"),
        )

    def public(self) -> dict[str, Any]:
        """Serializable view. The token is structurally absent, not blanked."""
        return {
            "campaign_id": self.campaign_id,
            "model_key": self.model_key,
            "model_revision": self.model_revision,
            "runtime_mode": self.runtime_mode,
            "runtime_image_digest": self.image_digest,
            "runtime_dir": str(self.runtime_dir),
            "state_dir": str(self.state_dir),
            "prompt_file": str(self.prompt_file) if self.prompt_file else None,
            "prompt_registry_dir": str(self.prompt_registry_dir),
            "weights_dir": str(self.weights_dir) if self.weights_dir else None,
            "fatal_file": str(self.fatal_file),
            "worker_id": self.worker_id,
            "pod_id": self.pod_id,
            "gpu_type": self.gpu_type,
            "device": self.device,
            "model_server_wait_seconds": self.model_server_wait_seconds,
            "model_server_poll_seconds": self.model_server_poll_seconds,
            "max_pod_age_hours": self.max_pod_age_hours,
            "pod_age_drain_seconds": self.pod_age_drain_seconds,
        }


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    """The validated contents of ``<runtime_dir>/runtime.json`` (contract section 6)."""

    model_key: str
    model_repo: str
    model_revision: str
    prompt_id: str
    prompt_kind: str
    inference_config: Mapping[str, Any]
    inference_config_sha256: str
    max_concurrency_per_worker: int
    per_page_timeout_seconds: float
    weights_dir: Path
    runtime_json_sha256: str
    raw: Mapping[str, Any]


_REQUIRED_RUNTIME_KEYS: Final = (
    "model_key",
    "model_repo",
    "model_revision",
    "prompt_id",
    "prompt_kind",
    "inference_config",
    "max_concurrency_per_worker",
    "per_page_timeout_seconds",
)


def require_runtime_dir(runtime_dir: Path) -> Path:
    """The single runtime lookup rule (ARENA_CONTRACT 11.3(5)).

    ``adapter.py``, ``canonical.py`` and ``runtime.json`` are found through
    ``ARENA_RUNTIME_DIR`` (default ``/opt/arena/runtime``) and nowhere else. A
    missing directory is fatal and says so: silently searching a second
    location is how a pod ends up attributing one model's output to another.
    """
    if not runtime_dir.exists():
        raise WorkerConfigError(
            f"runtime directory not found: {runtime_dir} "
            f"(ARENA_RUNTIME_DIR, default {DEFAULT_RUNTIME_DIR}); "
            "in bootstrap mode /opt/arena/bootstrap.sh creates it as a symlink to "
            "/opt/arena/runtimes/<model_key>"
        )
    if not runtime_dir.is_dir():
        raise WorkerConfigError(
            f"ARENA_RUNTIME_DIR is not a directory: {runtime_dir}"
        )
    return runtime_dir


def load_runtime_config(env: WorkerEnv) -> RuntimeConfig:
    """Read and validate ``runtime.json``; cross-check it against the pod env."""
    path = require_runtime_dir(env.runtime_dir) / RUNTIME_JSON_NAME
    if not path.is_file():
        raise WorkerConfigError(
            f"runtime descriptor not found: {path} "
            f"(ARENA_RUNTIME_DIR={env.runtime_dir})"
        )
    payload = path.read_bytes()
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WorkerConfigError(f"{path} is not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise WorkerConfigError(f"{path} must contain a JSON object")

    missing = [key for key in _REQUIRED_RUNTIME_KEYS if key not in data]
    if missing:
        raise WorkerConfigError(
            f"{path} is missing required keys: {missing}"
            + (
                "; prompt_kind is required by ARENA_CONTRACT 11.5 D34 (text|toolkit|none) "
                "and the worker cannot enforce a rule that was never declared"
                if "prompt_kind" in missing
                else ""
            )
        )

    prompt_kind = data["prompt_kind"]
    if prompt_kind not in PROMPT_KINDS:
        raise WorkerConfigError(
            f"{path}: prompt_kind must be one of {list(PROMPT_KINDS)} (D34), got {prompt_kind!r}"
        )

    model_key = str(data["model_key"])
    model_revision = str(data["model_revision"])
    if model_key != env.model_key:
        raise WorkerConfigError(
            f"adapter/model mismatch: {path} declares model_key {model_key!r} but "
            f"ARENA_MODEL_KEY is {env.model_key!r}; this pod would attribute one "
            "model's output to another"
        )
    if model_revision != env.model_revision:
        raise WorkerConfigError(
            f"runtime.json model_revision {model_revision!r} != "
            f"ARENA_MODEL_REVISION {env.model_revision!r}"
        )

    inference_config = data["inference_config"]
    if not isinstance(inference_config, dict):
        raise WorkerConfigError(f"{path}: inference_config must be a JSON object")

    concurrency = data["max_concurrency_per_worker"]
    if not isinstance(concurrency, int) or isinstance(concurrency, bool) or concurrency < 1:
        raise WorkerConfigError(
            f"{path}: max_concurrency_per_worker must be an integer >= 1, got {concurrency!r}"
        )

    timeout = data["per_page_timeout_seconds"]
    if isinstance(timeout, bool) or not isinstance(timeout, int | float) or timeout <= 0:
        raise WorkerConfigError(
            f"{path}: per_page_timeout_seconds must be a positive number, got {timeout!r}"
        )

    # The weights location is a pod fact, not a descriptor fact:
    # arena/core/schemas/runtime.schema.json is additionalProperties:false and
    # has no weights_dir, so it comes from the environment or the state dir.
    weights_dir = env.weights_dir or env.state_dir / "weights" / model_key

    return RuntimeConfig(
        model_key=model_key,
        model_repo=str(data["model_repo"]),
        model_revision=model_revision,
        prompt_id=str(data["prompt_id"]),
        prompt_kind=str(prompt_kind),
        inference_config=inference_config,
        inference_config_sha256=config_sha256(inference_config),
        max_concurrency_per_worker=concurrency,
        per_page_timeout_seconds=float(timeout),
        weights_dir=weights_dir,
        runtime_json_sha256=sha256_label(payload),
        raw=data,
    )


@dataclass(frozen=True, slots=True)
class ResolvedPrompt:
    """The prompt this worker will demand, and where it came from."""

    prompt_id: str
    prompt_kind: str
    path: Path
    text: str
    sha256: str
    source: str  # "ARENA_PROMPT_FILE" | "prompt_registry"


def prompt_path_for(env: WorkerEnv, runtime: RuntimeConfig) -> tuple[Path, str]:
    """Where ``<prompt_id>.txt`` lives, and which rule decided that (D17)."""
    if env.prompt_file is not None:
        return env.prompt_file, "ARENA_PROMPT_FILE"
    return env.prompt_registry_dir / f"{runtime.prompt_id}.txt", "prompt_registry"


def resolve_prompt(env: WorkerEnv, runtime: RuntimeConfig) -> ResolvedPrompt:
    """Read and validate the campaign prompt for this model (D17, D34).

    There is no "no prompt" state any more. Every model has a
    ``prompt_registry/<prompt_id>.txt``; a pipeline with no prompt declares
    ``prompt_kind = "none"`` and gets an empty file whose sha256 is the hash of
    the empty string. A missing file is fatal: a worker that shrugged and ran
    with an empty prompt would produce output nobody could attribute to a
    prompt, and the receipt would still carry a prompt_sha256.
    """
    path, source = prompt_path_for(env, runtime)
    if not path.is_file():
        raise WorkerConfigError(
            f"prompt file not found: {path} (resolved from {source}; "
            f"prompt_id={runtime.prompt_id!r}, prompt_kind={runtime.prompt_kind!r}). "
            "ARENA_CONTRACT 11.5 D17: the bundle carries prompt_registry/ and every "
            "baked image copies it to /opt/arena/prompt_registry/"
        )
    payload = path.read_bytes()
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise WorkerConfigError(f"{path} is not valid UTF-8: {exc}") from exc

    digest = sha256_label(payload)
    kind = runtime.prompt_kind
    if kind == "none":
        if payload:
            raise WorkerConfigError(
                f"{path}: prompt_kind is 'none' but the file holds {len(payload)} bytes; "
                "D34 requires an empty file whose sha256 is the hash of the empty string"
            )
    elif not text.strip():
        raise WorkerConfigError(
            f"{path}: prompt_kind is {kind!r} but the file is empty or blank; "
            "D34 requires the exact text the adapter sends (text) or the text the "
            "official toolkit builds for this revision (toolkit)"
        )

    return ResolvedPrompt(
        prompt_id=runtime.prompt_id,
        prompt_kind=kind,
        path=path,
        text=text,
        sha256=digest,
        source=source,
    )


__all__ = [
    "DEFAULT_FATAL_FILE",
    "DEFAULT_MODEL_SERVER_POLL_SECONDS",
    "DEFAULT_MODEL_SERVER_WAIT_SECONDS",
    "DEFAULT_POD_AGE_DRAIN_SECONDS",
    "DEFAULT_PROMPT_REGISTRY_DIR",
    "DEFAULT_RUNTIME_DIR",
    "DEFAULT_STATE_DIR",
    "PROMPT_KINDS",
    "RUNTIME_MODES",
    "ResolvedPrompt",
    "RuntimeConfig",
    "WorkerConfigError",
    "WorkerEnv",
    "load_runtime_config",
    "prompt_path_for",
    "require_runtime_dir",
    "resolve_prompt",
]
