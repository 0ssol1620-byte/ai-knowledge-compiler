"""Unit tests for the worker's helpers: config, redaction, atomic write, synthetic page."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from arena.constants import CAMPAIGN_ID
from arena.worker import provenance as provenance_module
from arena.worker.adapter_api import RawOutput
from arena.worker.canonical_default import PASSTHROUGH_NOTE, canonicalize
from arena.worker.config import (
    DEFAULT_MODEL_SERVER_POLL_SECONDS,
    DEFAULT_MODEL_SERVER_WAIT_SECONDS,
    DEFAULT_POD_AGE_DRAIN_SECONDS,
    DEFAULT_PROMPT_REGISTRY_DIR,
    WorkerConfigError,
    WorkerEnv,
    load_runtime_config,
    prompt_path_for,
    resolve_prompt,
)
from arena.worker.loader import load_adapter, load_canonicalizer
from arena.worker.synthetic import SyntheticPageError, render_synthetic_page, synthetic_page_png
from arena.worker.util import (
    atomic_write_bytes,
    atomic_write_json,
    config_sha256,
    jsonable,
    redact,
    safe_error,
    sha256_label,
)

BASE_ENV = {
    "ARENA_WORKER_TOKEN": "unit-test-value",
    "ARENA_MODEL_KEY": "paddleocr_vl_1_6",
    "ARENA_MODEL_REVISION": "a" * 40,
    "ARENA_RUNTIME_MODE": "baked",
    "ARENA_IMAGE_DIGEST": "sha256:" + "b" * 64,
}


# -- WorkerEnv --------------------------------------------------------------


def test_worker_env_defaults() -> None:
    env = WorkerEnv.from_env(BASE_ENV)
    assert env.campaign_id == CAMPAIGN_ID
    assert env.port == 8000
    assert env.host == "0.0.0.0"
    assert env.worker_id == "paddleocr_vl_1_6-w0-local"
    assert env.prompt_file is None
    assert env.collect_provenance_at_startup is True
    assert env.public()["worker_id"] == env.worker_id
    assert "token" not in env.public()
    assert env.token not in json.dumps(env.public())


@pytest.mark.parametrize(
    "missing",
    ["ARENA_WORKER_TOKEN", "ARENA_MODEL_KEY", "ARENA_MODEL_REVISION", "ARENA_IMAGE_DIGEST"],
)
def test_worker_env_requires_every_identity_field(missing: str) -> None:
    env = {key: value for key, value in BASE_ENV.items() if key != missing}
    with pytest.raises(WorkerConfigError, match=missing):
        WorkerEnv.from_env(env)


def test_worker_env_rejects_an_unknown_runtime_mode() -> None:
    with pytest.raises(WorkerConfigError, match="ARENA_RUNTIME_MODE"):
        WorkerEnv.from_env({**BASE_ENV, "ARENA_RUNTIME_MODE": "improvised"})


def test_worker_env_rejects_a_non_numeric_port() -> None:
    with pytest.raises(WorkerConfigError, match="ARENA_WORKER_PORT"):
        WorkerEnv.from_env({**BASE_ENV, "ARENA_WORKER_PORT": "eight thousand"})


def test_worker_env_rejects_an_unparsable_flag() -> None:
    with pytest.raises(WorkerConfigError, match="ARENA_PROVENANCE_AT_STARTUP"):
        WorkerEnv.from_env({**BASE_ENV, "ARENA_PROVENANCE_AT_STARTUP": "maybe"})


# -- runtime.json -----------------------------------------------------------


def _write_runtime(
    tmp_path: Path,
    *,
    env_overrides: dict[str, str] | None = None,
    **overrides: object,
) -> WorkerEnv:
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    descriptor: dict[str, object] = {
        "model_key": "paddleocr_vl_1_6",
        "model_repo": "example/repo",
        "model_revision": "a" * 40,
        "prompt_id": "p1",
        "prompt_kind": "text",
        "inference_config": {"max_new_tokens": 8},
        "max_concurrency_per_worker": 2,
        "per_page_timeout_seconds": 30,
    }
    descriptor.update(overrides)
    (runtime_dir / "runtime.json").write_text(json.dumps(descriptor), encoding="utf-8")
    return WorkerEnv.from_env(
        {
            **BASE_ENV,
            "ARENA_RUNTIME_DIR": str(runtime_dir),
            "ARENA_STATE_DIR": str(tmp_path / "s"),
            "ARENA_PROMPT_REGISTRY_DIR": str(tmp_path / "prompt_registry"),
            **{str(k): str(v) for k, v in dict(env_overrides or {}).items()},
        }
    )


def test_runtime_config_hashes_the_inference_config(tmp_path: Path) -> None:
    env = _write_runtime(tmp_path)
    runtime = load_runtime_config(env)
    assert runtime.inference_config_sha256 == config_sha256({"max_new_tokens": 8})
    assert runtime.runtime_json_sha256.startswith("sha256:")
    assert runtime.weights_dir == tmp_path / "s" / "weights" / "paddleocr_vl_1_6"
    assert runtime.per_page_timeout_seconds == 30.0


def test_runtime_config_missing_directory(tmp_path: Path) -> None:
    """11.3(5): ARENA_RUNTIME_DIR is the only lookup rule, and it fails closed."""
    env = WorkerEnv.from_env({**BASE_ENV, "ARENA_RUNTIME_DIR": str(tmp_path / "absent")})
    with pytest.raises(WorkerConfigError, match="runtime directory not found"):
        load_runtime_config(env)


def test_runtime_config_missing_file(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    env = WorkerEnv.from_env({**BASE_ENV, "ARENA_RUNTIME_DIR": str(runtime_dir)})
    with pytest.raises(WorkerConfigError, match="runtime descriptor not found"):
        load_runtime_config(env)


def test_runtime_config_rejects_a_model_key_mismatch(tmp_path: Path) -> None:
    env = _write_runtime(tmp_path, model_key="some_other_model")
    with pytest.raises(WorkerConfigError, match="ARENA_MODEL_KEY"):
        load_runtime_config(env)


def test_runtime_config_rejects_a_revision_mismatch(tmp_path: Path) -> None:
    env = _write_runtime(tmp_path, model_revision="f" * 40)
    with pytest.raises(WorkerConfigError, match="ARENA_MODEL_REVISION"):
        load_runtime_config(env)


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("max_concurrency_per_worker", 0, "max_concurrency_per_worker"),
        ("max_concurrency_per_worker", True, "max_concurrency_per_worker"),
        ("per_page_timeout_seconds", 0, "per_page_timeout_seconds"),
        ("per_page_timeout_seconds", "thirty", "per_page_timeout_seconds"),
        ("inference_config", [1, 2], "inference_config"),
    ],
)
def test_runtime_config_rejects_bad_values(
    tmp_path: Path, field: str, value: object, match: str
) -> None:
    env = _write_runtime(tmp_path, **{field: value})
    with pytest.raises(WorkerConfigError, match=match):
        load_runtime_config(env)


def test_runtime_config_rejects_broken_json(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    (runtime_dir / "runtime.json").write_text("{not json", encoding="utf-8")
    env = WorkerEnv.from_env({**BASE_ENV, "ARENA_RUNTIME_DIR": str(runtime_dir)})
    with pytest.raises(WorkerConfigError, match="not valid UTF-8 JSON"):
        load_runtime_config(env)


# -- prompt resolution (ARENA_CONTRACT 11.5 D17 / D34) ----------------------


def _write_prompt(tmp_path: Path, prompt_id: str, payload: bytes) -> Path:
    registry = tmp_path / "prompt_registry"
    registry.mkdir(parents=True, exist_ok=True)
    path = registry / f"{prompt_id}.txt"
    # write_bytes, not write_text: the hash must cover the exact bytes the
    # controller hashed, and Windows text mode would insert a CR.
    path.write_bytes(payload)
    return path


def test_runtime_config_requires_prompt_kind(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    descriptor = {
        "model_key": "paddleocr_vl_1_6",
        "model_repo": "example/repo",
        "model_revision": "a" * 40,
        "prompt_id": "p1",
        "inference_config": {},
        "max_concurrency_per_worker": 1,
        "per_page_timeout_seconds": 30,
    }
    (runtime_dir / "runtime.json").write_text(json.dumps(descriptor), encoding="utf-8")
    env = WorkerEnv.from_env({**BASE_ENV, "ARENA_RUNTIME_DIR": str(runtime_dir)})
    with pytest.raises(WorkerConfigError, match="prompt_kind"):
        load_runtime_config(env)


def test_runtime_config_rejects_an_unknown_prompt_kind(tmp_path: Path) -> None:
    env = _write_runtime(tmp_path, prompt_kind="free_text")
    with pytest.raises(WorkerConfigError, match="prompt_kind must be one of"):
        load_runtime_config(env)


def test_prompt_defaults_to_the_registry_path() -> None:
    env = WorkerEnv.from_env(BASE_ENV)
    assert env.prompt_registry_dir == DEFAULT_PROMPT_REGISTRY_DIR


def test_prompt_path_comes_from_the_registry_and_the_prompt_id(tmp_path: Path) -> None:
    env = _write_runtime(tmp_path)
    runtime = load_runtime_config(env)
    path, source = prompt_path_for(env, runtime)
    assert path == tmp_path / "prompt_registry" / "p1.txt"
    assert source == "prompt_registry"


def test_prompt_file_env_overrides_the_registry(tmp_path: Path) -> None:
    override = tmp_path / "override.txt"
    override.write_bytes(b"transcribe\n")
    env = _write_runtime(tmp_path, env_overrides={"ARENA_PROMPT_FILE": str(override)})
    runtime = load_runtime_config(env)
    resolved = resolve_prompt(env, runtime)
    assert resolved.source == "ARENA_PROMPT_FILE"
    assert resolved.path == override
    assert resolved.text == "transcribe\n"
    assert resolved.sha256 == sha256_label(b"transcribe\n")


def test_prompt_kind_text_hashes_the_exact_bytes(tmp_path: Path) -> None:
    _write_prompt(tmp_path, "p1", b"transcribe\n")
    env = _write_runtime(tmp_path)
    resolved = resolve_prompt(env, load_runtime_config(env))
    assert resolved.prompt_kind == "text"
    assert resolved.text == "transcribe\n"
    assert resolved.sha256 == sha256_label(b"transcribe\n")


def test_prompt_missing_file_fails_closed(tmp_path: Path) -> None:
    env = _write_runtime(tmp_path)
    runtime = load_runtime_config(env)
    with pytest.raises(WorkerConfigError, match="prompt file not found"):
        resolve_prompt(env, runtime)


@pytest.mark.parametrize("kind", ["text", "toolkit"])
def test_prompt_kind_text_and_toolkit_refuse_an_empty_file(tmp_path: Path, kind: str) -> None:
    _write_prompt(tmp_path, "p1", b"   \n")
    env = _write_runtime(tmp_path, prompt_kind=kind)
    runtime = load_runtime_config(env)
    with pytest.raises(WorkerConfigError, match="empty or blank"):
        resolve_prompt(env, runtime)


def test_prompt_kind_none_requires_an_empty_file(tmp_path: Path) -> None:
    _write_prompt(tmp_path, "p1", b"")
    env = _write_runtime(tmp_path, prompt_kind="none")
    resolved = resolve_prompt(env, load_runtime_config(env))
    assert resolved.text == ""
    assert resolved.sha256 == sha256_label(b"")


def test_prompt_kind_none_refuses_a_non_empty_file(tmp_path: Path) -> None:
    _write_prompt(tmp_path, "p1", b"a prompt that should not be here\n")
    env = _write_runtime(tmp_path, prompt_kind="none")
    runtime = load_runtime_config(env)
    with pytest.raises(WorkerConfigError, match="prompt_kind is 'none'"):
        resolve_prompt(env, runtime)


def test_prompt_refuses_bytes_that_are_not_utf8(tmp_path: Path) -> None:
    _write_prompt(tmp_path, "p1", b"\xff\xfe\x00")
    env = _write_runtime(tmp_path)
    runtime = load_runtime_config(env)
    with pytest.raises(WorkerConfigError, match="not valid UTF-8"):
        resolve_prompt(env, runtime)


def test_every_campaign_runtime_prompt_resolves_in_the_registry() -> None:
    """D17: prompt_registry/<prompt_id>.txt exists for every model in the namespace.

    This is the check that would have caught the first pass's gap: the bundle
    docstring promised a registry nothing packed, and no test looked.
    """
    from arena.constants import NAMESPACE_ROOT

    missing: list[str] = []
    for descriptor_path in sorted((NAMESPACE_ROOT / "runtimes").glob("*/runtime.json")):
        descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
        prompt_id = descriptor.get("prompt_id")
        if not isinstance(prompt_id, str):
            missing.append(f"{descriptor_path.parent.name}: no prompt_id")
            continue
        if not (NAMESPACE_ROOT / "prompt_registry" / f"{prompt_id}.txt").is_file():
            missing.append(f"{descriptor_path.parent.name}: prompt_registry/{prompt_id}.txt")
    assert missing == [], f"prompt files the worker could never resolve: {missing}"


# -- D19 / D20 environment settings -----------------------------------------


def test_worker_env_timing_defaults() -> None:
    env = WorkerEnv.from_env(BASE_ENV)
    assert env.model_server_wait_seconds == DEFAULT_MODEL_SERVER_WAIT_SECONDS
    assert env.model_server_wait_seconds >= 20 * 60, "D19 names 20 minutes as the floor"
    assert env.model_server_poll_seconds == DEFAULT_MODEL_SERVER_POLL_SECONDS
    assert env.pod_age_drain_seconds == DEFAULT_POD_AGE_DRAIN_SECONDS
    assert env.max_pod_age_hours is None


def test_worker_env_reads_the_pod_age_fuse() -> None:
    env = WorkerEnv.from_env({**BASE_ENV, "ARENA_MAX_POD_AGE_HOURS": "2"})
    assert env.max_pod_age_hours == 2.0


@pytest.mark.parametrize("bad", ["six", "0", "-1", "nan", "inf"])
def test_worker_env_refuses_a_nonsense_pod_age(bad: str) -> None:
    with pytest.raises(WorkerConfigError, match="ARENA_MAX_POD_AGE_HOURS"):
        WorkerEnv.from_env({**BASE_ENV, "ARENA_MAX_POD_AGE_HOURS": bad})


# -- loader -----------------------------------------------------------------

ADAPTER_CLASS_SOURCE = '''
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from arena.worker.adapter_api import (
    AdapterConfig,
    LoadReceipt,
    PageInput,
    RawOutput,
    WarmupReceipt,
)


class {name}:
    model_key = "paddleocr_vl_1_6"

    def load(self, cfg: AdapterConfig) -> LoadReceipt:
        return LoadReceipt(
            model_key=cfg.model_key,
            model_repo=cfg.model_repo,
            model_revision=cfg.model_revision,
            weights_sha256_manifest="sha256:" + "0" * 64,
            load_ms=1,
            cache_hit=False,
            runtime_provenance={{}},
        )

    def warmup(self, synthetic_image: Path) -> WarmupReceipt:
        return WarmupReceipt(warmup_ms=1, output_chars=1, schema_valid=True, peak_vram_mb=None)

    def infer(self, page: PageInput) -> RawOutput:
        return RawOutput(
            raw_text="ok",
            output_format="markdown",
            native_json=None,
            usage={{}},
            timings_ms={{"inference_ms": 1}},
        )

    def runtime_provenance(self) -> Mapping[str, Any]:
        return {{}}

    def close(self) -> None:
        return None
'''


def test_load_adapter_requires_a_known_entry_point(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    (runtime_dir / "adapter.py").write_text("VALUE = 1\n", encoding="utf-8")
    with pytest.raises(WorkerConfigError, match="create_adapter"):
        load_adapter(runtime_dir)


def test_load_adapter_accepts_a_sole_adapter_class(tmp_path: Path) -> None:
    """Seven of the eleven runtimes expose only the class, so this path carries them."""
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    (runtime_dir / "adapter.py").write_text(
        ADAPTER_CLASS_SOURCE.format(name="PaddleOcrVlAdapter"), encoding="utf-8"
    )
    adapter = load_adapter(runtime_dir)
    assert adapter.model_key == "paddleocr_vl_1_6"


def test_load_adapter_refuses_two_candidate_classes(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    second = ADAPTER_CLASS_SOURCE.format(name="SecondAdapter")
    body = second[second.index("class SecondAdapter") :]
    (runtime_dir / "adapter.py").write_text(
        ADAPTER_CLASS_SOURCE.format(name="FirstAdapter") + "\n\n" + body, encoding="utf-8"
    )
    with pytest.raises(WorkerConfigError, match="2 adapter classes"):
        load_adapter(runtime_dir)


def test_load_adapter_refuses_a_class_that_needs_arguments(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    (runtime_dir / "adapter.py").write_text(
        "class ThingAdapter:\n    def __init__(self, backend):\n        self.backend = backend\n",
        encoding="utf-8",
    )
    with pytest.raises(WorkerConfigError, match="needs arguments"):
        load_adapter(runtime_dir)


def test_load_adapter_refuses_an_object_that_is_not_an_adapter(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    (runtime_dir / "adapter.py").write_text(
        "def create_adapter():\n    return object()\n", encoding="utf-8"
    )
    with pytest.raises(WorkerConfigError, match="ArenaModelAdapter"):
        load_adapter(runtime_dir)


def test_load_adapter_missing_file(tmp_path: Path) -> None:
    with pytest.raises(WorkerConfigError, match="adapter not found"):
        load_adapter(tmp_path)


def test_load_canonicalizer_falls_back_with_a_label(tmp_path: Path) -> None:
    func, source = load_canonicalizer(tmp_path)
    assert source == "arena.worker.canonical_default"
    assert func is canonicalize


def test_load_canonicalizer_refuses_a_module_without_the_function(tmp_path: Path) -> None:
    (tmp_path / "canonical.py").write_text("VALUE = 1\n", encoding="utf-8")
    with pytest.raises(WorkerConfigError, match="canonicalize"):
        load_canonicalizer(tmp_path)


def test_passthrough_canonicalizer_adds_nothing() -> None:
    raw = RawOutput(
        raw_text="# heading\n\nbody",
        output_format="markdown",
        native_json=None,
        usage={},
        timings_ms={"inference_ms": 1},
    )
    result = canonicalize(raw)
    assert result.markdown == raw.raw_text
    assert result.lossy is False
    assert result.conversion_notes == (PASSTHROUGH_NOTE,)
    assert result.elements is None


# -- util -------------------------------------------------------------------


@pytest.mark.parametrize(
    "leaked",
    [
        "rpa_" + "A" * 30,
        "hf_" + "B" * 30,
        "sk-" + "C" * 30,
        "ghp_" + "D" * 30,
        "AKIA" + "E" * 16,
        "Bearer " + "F" * 40,
    ],
)
def test_redact_removes_credential_shapes(leaked: str) -> None:
    redacted = redact(f"call failed: {leaked} at the edge")
    assert leaked not in redacted
    assert "[REDACTED]" in redacted


def test_redact_keeps_content_hashes_readable() -> None:
    digest = "sha256:" + "0123456789abcdef" * 4
    assert redact(f"mismatch {digest}") == f"mismatch {digest}"


def test_safe_error_is_bounded_and_typed() -> None:
    message = safe_error(ValueError("tensor shape mismatch. " * 400))
    assert message.startswith("ValueError: ")
    assert len(message) <= 2000
    assert message.endswith("...")


def test_safe_error_redacts_before_truncating() -> None:
    # A very long unbroken token looks exactly like a leaked credential, so it
    # is redacted rather than truncated into something half-readable.
    assert safe_error(ValueError("Q" * 5000)) == "ValueError: [REDACTED]"


def test_atomic_write_leaves_no_temp_file(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "result.json"
    digest = atomic_write_json(target, {"b": 1, "a": 2})
    assert digest == sha256_label(target.read_bytes())
    assert json.loads(target.read_text(encoding="utf-8")) == {"a": 2, "b": 1}
    assert list(tmp_path.rglob("*.tmp")) == []

    atomic_write_bytes(target, b"replaced")
    assert target.read_bytes() == b"replaced"
    assert list(tmp_path.rglob("*.tmp")) == []


def test_jsonable_projects_without_raising(tmp_path: Path) -> None:
    projected = jsonable({"path": tmp_path, "tuple": (1, 2), "obj": object(), "n": None})
    assert projected["path"] == str(tmp_path)
    assert projected["tuple"] == [1, 2]
    assert isinstance(projected["obj"], str)
    assert projected["n"] is None
    json.dumps(projected)


# -- synthetic page ---------------------------------------------------------


def test_synthetic_page_is_a_real_deterministic_png(tmp_path: Path) -> None:
    first = render_synthetic_page()
    second = render_synthetic_page()
    assert first == second
    assert first.startswith(b"\x89PNG\r\n\x1a\n")

    path = synthetic_page_png(tmp_path / "warmup.png")
    assert path.read_bytes() == first

    pil = pytest.importorskip("PIL.Image")
    with pil.open(path) as image:
        assert image.size == (1240, 1754)
        colors = image.convert("L").getcolors(maxcolors=256)
        assert colors is not None
        values = {value for _, value in colors}
        assert min(values) < 40, "the page must contain black ink"
        assert max(values) > 200, "the page must contain white paper"


def test_synthetic_page_refuses_a_useless_size() -> None:
    with pytest.raises(SyntheticPageError, match="too small"):
        render_synthetic_page(width=10, height=10)


# -- provenance -------------------------------------------------------------


def test_provenance_without_subprocess_still_reports_a_freeze() -> None:
    facts = provenance_module.collect_provenance(
        image_digest="sha256:" + "0" * 64,
        adapter_provenance={"backend": "unit"},
        run_pip_freeze=False,
    )
    assert facts["pip_freeze_source"] == "importlib.metadata"
    assert facts["pip_freeze_sha256"] == sha256_label(facts["pip_freeze_text"].encode("utf-8"))
    assert facts["unavailable"]["pip_freeze"]
    assert facts["adapter"] == {"backend": "unit"}
    assert facts["versions"]["pillow"] is not None
    assert facts["versions"]["vllm"] is None
    assert "torch_runtime" in facts["unavailable"] or facts["versions"]["torch"] is not None
    json.dumps(facts)
