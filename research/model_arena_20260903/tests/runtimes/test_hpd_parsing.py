"""Tests for runtimes/hpd_parsing/.

The loaders duplicate what tests/runtimes/conftest.py offers, using the same
``sys.modules`` key convention so nothing is imported twice. They are local on
purpose: conftest.py is shared by three runtime lanes building in parallel.

No GPU, no network, no vllm. The customized engine is replaced by a fake that
returns OpenAI-compatible payloads.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from arena.worker.adapter_api import AdapterConfig, AdapterError, PageInput, RawOutput

MODEL_KEY = "hpd_parsing"
NAMESPACE_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_DIR = NAMESPACE_ROOT / "runtimes" / MODEL_KEY
RUNTIME_SCHEMA = NAMESPACE_ROOT / "arena" / "core" / "schemas" / "runtime.schema.json"
OFFICIAL_PROMPT = "document parsing with fork."

REQUIRED_RUNTIME_FIELDS = (
    "model_key", "display_name", "model_repo", "model_revision", "official_runtime",
    "runtime_version", "base_image", "gpu_min_vram_gb", "gpu_pool_priority",
    "max_concurrency_per_worker", "shard_size_hint", "per_page_timeout_seconds",
    "prompt_id", "inference_config", "weights_strategy", "runtime_mode_allowed",
    "official_source_urls", "license", "notes", "weights",
)
FORBIDDEN_TOP_LEVEL_IMPORTS = frozenset(
    {"paddleocr", "paddle", "paddlex", "vllm", "torch", "transformers", "mineru", "PIL", "openai"}
)


def load_runtime_module(model_key: str, module_name: str) -> ModuleType:
    qualified = f"arena_runtime_{model_key}_{module_name}"
    cached = sys.modules.get(qualified)
    if cached is not None:
        return cached
    path = NAMESPACE_ROOT / "runtimes" / model_key / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(qualified, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot build an import spec for {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[qualified] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(qualified, None)
        raise
    return module


def load_json(model_key: str, name: str) -> dict[str, Any]:
    path = NAMESPACE_ROOT / "runtimes" / model_key / name
    loaded: Any = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def load_runtime_json(model_key: str) -> dict[str, Any]:
    return load_json(model_key, "runtime.json")


def load_provenance_json(model_key: str) -> dict[str, Any]:
    return load_json(model_key, "provenance.json")


def top_level_import_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


def null_paths(document: Mapping[str, Any], prefix: str = "") -> list[str]:
    found: list[str] = []
    for key, value in document.items():
        path = f"{prefix}{key}"
        if value is None:
            found.append(path)
        elif isinstance(value, dict):
            found.extend(null_paths(value, f"{path}."))
    return found


def assert_runtime_contract(model_key: str, document: Mapping[str, Any]) -> None:
    """ARENA_CONTRACT.md section 6, plus the C-lane `weights` object."""
    missing = [field for field in REQUIRED_RUNTIME_FIELDS if field not in document]
    assert not missing, f"{model_key}/runtime.json is missing {missing}"
    assert document["model_key"] == model_key
    assert document["official_runtime"] in {
        "vllm", "transformers", "paddle", "mineru_cli", "custom"
    }
    assert document["weights_strategy"] in {"baked", "volume_cache", "boot_download"}
    modes = document["runtime_mode_allowed"]
    assert isinstance(modes, list) and modes and set(modes) <= {"baked", "bootstrap"}
    pools = document["gpu_pool_priority"]
    assert isinstance(pools, list) and pools
    assert all(isinstance(entry, str) and entry for entry in pools)
    urls = document["official_source_urls"]
    assert isinstance(urls, list) and urls
    assert all(isinstance(url, str) and url.startswith("https://") for url in urls)
    for field in (
        "gpu_min_vram_gb", "max_concurrency_per_worker",
        "shard_size_hint", "per_page_timeout_seconds",
    ):
        assert isinstance(document[field], int) and document[field] > 0
    assert isinstance(document["inference_config"], dict)
    assert isinstance(document["notes"], str) and document["notes"]
    licence = document["license"]
    assert isinstance(licence, dict)
    assert {"id", "url", "status"} <= set(licence)
    weights = document["weights"]
    assert isinstance(weights, dict)
    assert {"repo", "revision", "largest_file", "largest_file_sha256"} <= set(weights)
    assert weights["repo"] == document["model_repo"]
    assert weights["revision"] == document["model_revision"]
    digest = weights["largest_file_sha256"]
    assert isinstance(digest, str) and digest.startswith("sha256:")
    assert len(digest) == len("sha256:") + 64


def assert_nulls_are_documented(
    document: Mapping[str, Any], provenance: Mapping[str, Any]
) -> None:
    unresolved = null_paths(document) + null_paths(provenance)
    pending = provenance.get("to_verify_in_canary")
    assert isinstance(pending, list) and pending
    joined = " ".join(str(item) for item in pending)
    for field in unresolved:
        assert field.rsplit(".", 1)[-1] in joined, f"null field {field} is undocumented"


def assert_schema_conformance(document: Mapping[str, Any]) -> list[str]:
    if not RUNTIME_SCHEMA.is_file():
        return []
    import jsonschema

    validator = jsonschema.Draft202012Validator(
        json.loads(RUNTIME_SCHEMA.read_text(encoding="utf-8"))
    )
    return [error.json_path for error in validator.iter_errors(dict(document))]


def executable_lines(text: str) -> list[str]:
    return [
        line for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #

BLOCK_OUTPUT = (
    "<BLOCK>doc_title [12,30,900,80]<CHILD>Annual Report 2026"
    "<BLOCK>paragraph_title [12,100,900,140]<CHILD>Results"
    "<BLOCK>text [12,150,900,300]<CHILD>Revenue grew."
    "<BLOCK>image [12,320,900,700]"
)


def completion(text: str, finish_reason: str = "stop") -> dict[str, Any]:
    return {
        "id": "chatcmpl-test",
        "model": "HPD-Parsing",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text},
                     "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 1200, "completion_tokens": 340, "total_tokens": 1540},
    }


class FakeBackend:
    """Stands in for `vllm serve` plus the OpenAI-compatible client."""

    def __init__(
        self,
        payload: Mapping[str, Any] | None = None,
        error: BaseException | None = None,
    ) -> None:
        self.payload = payload if payload is not None else completion(BLOCK_OUTPUT)
        self.error = error
        self.started = False
        self.closed = False
        self.seen_image_b64: str | None = None

    def start(self) -> Mapping[str, Any]:
        self.started = True
        return {"server_command": ["vllm", "serve"], "server_env": ["MAX_PATCHES_WITH_RESIZE"]}

    def complete(self, image_b64: str) -> Mapping[str, Any]:
        if self.error is not None:
            raise self.error
        self.seen_image_b64 = image_b64
        return self.payload

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def adapter_module() -> ModuleType:
    return load_runtime_module(MODEL_KEY, "adapter")


@pytest.fixture
def canonical_module() -> ModuleType:
    return load_runtime_module(MODEL_KEY, "canonical")


@pytest.fixture
def png(tmp_path: Path) -> Path:
    path = tmp_path / "page.png"
    path.write_bytes(
        bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000020000000208060000"
            "00f478d4fa0000001649444154789c636060606000000004000165f8"
            "0f5d0000000049454e44ae426082"
        )
    )
    return path


def make_weights(tmp_path: Path, revision: str, payload: bytes = b"weights") -> Path:
    directory = tmp_path / "weights"
    (directory / "P-MTP").mkdir(parents=True)
    (directory / "model.safetensors").write_bytes(payload)
    (directory / "config.json").write_text("{}", encoding="utf-8")
    (directory / "P-MTP" / "config.json").write_text("{}", encoding="utf-8")
    (directory / "P-MTP" / "model.safetensors").write_bytes(b"mtp")
    (directory / "arena-weights-revision.txt").write_text(revision, encoding="utf-8")
    return directory


def patched_spec(
    monkeypatch: pytest.MonkeyPatch, module: ModuleType, weights_dir: Path
) -> dict[str, Any]:
    spec = dict(load_runtime_json(MODEL_KEY))
    digest = hashlib.sha256((weights_dir / "model.safetensors").read_bytes()).hexdigest()
    spec["weights"] = dict(spec["weights"], largest_file_sha256=f"sha256:{digest}")
    monkeypatch.setattr(module, "runtime_spec", lambda: spec)
    return spec


def make_config(weights_dir: Path, **overrides: Any) -> AdapterConfig:
    document = load_runtime_json(MODEL_KEY)
    defaults: dict[str, Any] = {
        "model_key": MODEL_KEY,
        "model_repo": document["model_repo"],
        "model_revision": document["model_revision"],
        "weights_dir": weights_dir,
        "prompt_id": document["prompt_id"],
        "prompt_text": OFFICIAL_PROMPT,
        "inference_config": document["inference_config"],
        "inference_config_sha256": "sha256:" + "0" * 64,
        "max_concurrency": document["max_concurrency_per_worker"],
        "device": "cuda:0",
    }
    defaults.update(overrides)
    return AdapterConfig(**defaults)


def _loaded(
    adapter_module: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    backend: FakeBackend,
) -> Any:
    document = load_runtime_json(MODEL_KEY)
    weights = make_weights(tmp_path, document["model_revision"])
    patched_spec(monkeypatch, adapter_module, weights)
    adapter = adapter_module.create_adapter(lambda cfg: backend)
    adapter.load(make_config(weights))
    return adapter


def _page(png: Path) -> PageInput:
    return PageInput(
        inference_job_id="b" * 64,
        sample_id="parsebench:docs/chart/report_p101#p0",
        case_key="parsebench-7f0a1c2d",
        benchmark="parsebench",
        image_path=png,
        source_sha256="sha256:" + "0" * 64,
        width=1654,
        height=2339,
        metadata={"page_index": 0, "media_type": "pdf"},
    )


# --------------------------------------------------------------------------- #
# runtime.json
# --------------------------------------------------------------------------- #


def test_runtime_json_matches_the_contract() -> None:
    assert_runtime_contract(MODEL_KEY, load_runtime_json(MODEL_KEY))


def test_every_null_is_documented() -> None:
    assert_nulls_are_documented(load_runtime_json(MODEL_KEY), load_provenance_json(MODEL_KEY))


def test_schema_conformance_including_the_now_resolved_base_image_digest() -> None:
    # The 401 that blocked this on 2026-09-03 was the unauthenticated first hop,
    # not a refusal: the registry advertises a Bearer realm and issues an
    # anonymous pull token. There is no documented schema exception left.
    failures = assert_schema_conformance(load_runtime_json(MODEL_KEY))
    assert failures == [], f"unexpected schema failures: {failures}"
    resolved = load_provenance_json(MODEL_KEY)["base_image_digest"]
    assert isinstance(resolved, dict)
    assert resolved["digest"] == (
        "sha256:1493923dd6b7e368c56b5497f2c82ade2599be9c69aa7498a71417b5c6d9948a"
    )
    assert resolved["digest"] in load_runtime_json(MODEL_KEY)["base_image"]


def test_runtime_json_pins_the_official_engine_and_flags() -> None:
    document = load_runtime_json(MODEL_KEY)
    config = document["inference_config"]
    server = config["server"]
    assert config["prompt_text"] == OFFICIAL_PROMPT
    assert config["max_tokens"] == 8000
    assert config["temperature"] == 0
    # Every one of these is copied from the official tutorial, not chosen here.
    assert server["env"]["MAX_PATCHES_WITH_RESIZE"] == "true"
    assert server["attention_backend"] == "FLASHINFER"
    assert server["max_model_len"] == 16384
    assert server["gpu_memory_utilization"] == 0.9
    assert server["speculative_config"]["method"] == "medusa"
    assert server["speculative_config"]["num_speculative_tokens"] == 6
    assert "0.17.1+hpdparsing" in document["runtime_version"]


def test_provenance_records_that_there_is_no_prior_pin() -> None:
    # HPD-Parsing is not a v6 candidate. Nulls here mean "nothing to compare",
    # which is a fact; inventing agreement would not be.
    cross_check = load_provenance_json(MODEL_KEY)["model_revision_cross_check"]
    assert cross_check["recorded_revision"] is None
    assert cross_check["agrees"] is None


def test_provenance_pins_the_customized_wheel() -> None:
    pins = load_provenance_json(MODEL_KEY)["runtime_dependency_pins"]
    assert pins["vllm"] == "0.17.1+hpdparsing"
    assert pins["vllm_wheel_url"].endswith(".whl")


def test_runtime_text_carries_no_secret_markers() -> None:
    for name in ("runtime.json", "provenance.json", "Dockerfile", "bootstrap.sh"):
        text = (RUNTIME_DIR / name).read_text(encoding="utf-8")
        for marker in ("rpa_", "sk-", "ghp_", "AKIA"):
            assert marker not in text, f"possible secret marker {marker!r} in {name}"


def test_every_runtime_file_exists() -> None:
    for name in ("runtime.json", "provenance.json", "adapter.py", "canonical.py",
                 "Dockerfile", "bootstrap.sh", "README.md"):
        assert (RUNTIME_DIR / name).is_file(), f"{name} is missing"


def test_dockerfile_pins_and_never_upgrades() -> None:
    text = (RUNTIME_DIR / "Dockerfile").read_text(encoding="utf-8")
    assert all("pip install -U" not in line for line in executable_lines(text))
    assert "@${BASE_IMAGE_DIGEST}" in text
    assert "--revision" in text and "sha256sum -c" in text
    assert "P-MTP/config.json" in text  # the tutorial requires both config files


def test_bootstrap_is_canary_only_and_pins() -> None:
    text = (RUNTIME_DIR / "bootstrap.sh").read_text(encoding="utf-8")
    assert all("pip install -U" not in line for line in executable_lines(text))
    assert "CANARY-ONLY" in text
    assert "bootstrap-receipt.txt" in text
    assert "vllm-0.17.1+hpdparsing" in text
    # ARENA_CONTRACT section 11.3 item 4: the bundle is already extracted.
    assert "ARENA_BUNDLE_URL" not in text


def test_bootstrap_respects_a_non_default_arena_root() -> None:
    """D54: the official image's USER hpd cannot write /opt (HOME=/home/hpd,
    from the image's own OCI config), so this must read ARENA_ROOT from the
    environment rather than hard-code /opt/arena."""
    text = (RUNTIME_DIR / "bootstrap.sh").read_text(encoding="utf-8")
    assert 'ARENA_ROOT="${ARENA_ROOT:-/opt/arena}"' in text
    assert 'mkdir -p "${WEIGHTS_ROOT}" /workspace/arena/results' not in text


def test_bootstrap_falls_back_off_workspace_for_weights_when_not_writable() -> None:
    """D54: /workspace may be as unwritable as /opt for a non-root user; the
    weights and results directories must fall back under ARENA_ROOT."""
    text = (RUNTIME_DIR / "bootstrap.sh").read_text(encoding="utf-8")
    assert 'WEIGHTS_ROOT_DEFAULT="/workspace/arena/weights/${MODEL_KEY}"' in text
    assert 'WEIGHTS_ROOT_DEFAULT="${ARENA_ROOT}/weights/${MODEL_KEY}"' in text
    assert 'RESULTS_DIR_DEFAULT="${ARENA_ROOT}/results"' in text
    assert 'WEIGHTS_ROOT="${ARENA_WEIGHTS_DIR:-${WEIGHTS_ROOT_DEFAULT}}"' in text


def test_bootstrap_pip_installs_fall_back_to_user_site_outside_a_venv() -> None:
    """D54: hpd-parsing-vllm's own venv (/home/hpd/venv, on PATH) is writable by
    the non-root hpd user, so this is mostly a no-op safety net here -- but the
    fallback must exist and must not force --user inside a venv (pip refuses
    --user there)."""
    text = (RUNTIME_DIR / "bootstrap.sh").read_text(encoding="utf-8")
    assert "pip_install()" in text
    assert "--user" in text
    assert "sys.prefix == getattr(sys, 'base_prefix', sys.prefix)" in text
    assert "pip_install \"${HPD_VLLM_WHEEL}\"" in text
    assert 'pip_install "huggingface_hub[cli]==0.35.3"' in text


# --------------------------------------------------------------------------- #
# module hygiene
# --------------------------------------------------------------------------- #


def test_modules_import_without_the_heavy_stack(
    adapter_module: ModuleType, canonical_module: ModuleType
) -> None:
    assert adapter_module.MODEL_KEY == MODEL_KEY
    assert canonical_module.MODEL_KEY == MODEL_KEY
    for name in ("adapter.py", "canonical.py"):
        roots = top_level_import_roots(RUNTIME_DIR / name)
        assert not (roots & FORBIDDEN_TOP_LEVEL_IMPORTS), f"{name} imports a heavy package"


def test_request_body_is_the_documented_one(adapter_module: ModuleType) -> None:
    config = load_runtime_json(MODEL_KEY)["inference_config"]
    body = adapter_module.build_request_body("QUJD", config)
    assert body["model"] == "HPD-Parsing"
    assert body["max_tokens"] == 8000
    assert body["temperature"] == 0
    content = body["messages"][0]["content"]
    assert content[0]["image_url"]["url"] == "data:image/png;base64,QUJD"
    assert content[1]["text"] == OFFICIAL_PROMPT


# --------------------------------------------------------------------------- #
# load()
# --------------------------------------------------------------------------- #


def test_load_returns_a_receipt(
    adapter_module: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = FakeBackend()
    adapter = _loaded(adapter_module, tmp_path, monkeypatch, backend)
    assert backend.started is True
    provenance = adapter.runtime_provenance()
    assert provenance["official_runtime"] == "vllm"
    assert provenance["runtime_dependency_pins"]["vllm"] == "0.17.1+hpdparsing"


def test_load_rejects_a_wrong_prompt(
    adapter_module: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The model fixes its own prompt. Substituting one silently would change what
    # is being measured while the label stayed the same.
    document = load_runtime_json(MODEL_KEY)
    weights = make_weights(tmp_path, document["model_revision"])
    patched_spec(monkeypatch, adapter_module, weights)
    adapter = adapter_module.create_adapter(lambda cfg: FakeBackend())
    with pytest.raises(AdapterError) as caught:
        adapter.load(make_config(weights, prompt_text="please transcribe"))
    assert caught.value.error_class == "MODEL_LOAD"


def test_load_requires_the_pmtp_checkpoint(
    adapter_module: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    document = load_runtime_json(MODEL_KEY)
    weights = make_weights(tmp_path, document["model_revision"])
    patched_spec(monkeypatch, adapter_module, weights)
    (weights / "P-MTP" / "config.json").unlink()
    adapter = adapter_module.create_adapter(lambda cfg: FakeBackend())
    with pytest.raises(AdapterError) as caught:
        adapter.load(make_config(weights))
    assert caught.value.error_class == "MODEL_LOAD"
    assert "P-MTP/config.json" in str(caught.value)


def test_load_rejects_a_wrong_weights_revision(
    adapter_module: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    weights = make_weights(tmp_path, "0" * 40)
    patched_spec(monkeypatch, adapter_module, weights)
    adapter = adapter_module.create_adapter(lambda cfg: FakeBackend())
    with pytest.raises(AdapterError) as caught:
        adapter.load(make_config(weights))
    assert caught.value.error_class == "MODEL_LOAD"
    assert "revision mismatch" in str(caught.value)


def test_load_rejects_a_tampered_checkpoint(
    adapter_module: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    document = load_runtime_json(MODEL_KEY)
    weights = make_weights(tmp_path, document["model_revision"])
    patched_spec(monkeypatch, adapter_module, weights)
    (weights / "model.safetensors").write_bytes(b"swapped for another model")
    adapter = adapter_module.create_adapter(lambda cfg: FakeBackend())
    with pytest.raises(AdapterError) as caught:
        adapter.load(make_config(weights))
    assert "digest mismatch" in str(caught.value)


# --------------------------------------------------------------------------- #
# infer()
# --------------------------------------------------------------------------- #


def test_infer_returns_the_block_stream_verbatim(
    adapter_module: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, png: Path
) -> None:
    backend = FakeBackend()
    adapter = _loaded(adapter_module, tmp_path, monkeypatch, backend)

    raw = adapter.infer(_page(png))

    assert raw.raw_text == BLOCK_OUTPUT
    assert raw.output_format == "hpd_blocks"
    assert raw.warnings == ()
    # A well-formed, complete answer carries no semantic verdict at all.
    assert raw.semantic_error_class is None
    assert raw.usage["completion_tokens"] == 340
    assert backend.seen_image_b64 is not None


def test_infer_flags_a_truncated_completion(
    adapter_module: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, png: Path
) -> None:
    backend = FakeBackend(payload=completion(BLOCK_OUTPUT, finish_reason="length"))
    adapter = _loaded(adapter_module, tmp_path, monkeypatch, backend)
    raw = adapter.infer(_page(png))
    assert "output_truncated" in raw.warnings
    assert raw.semantic_error_class == "OUTPUT_TRUNCATED"


def test_infer_flags_missing_block_markers(
    adapter_module: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, png: Path
) -> None:
    backend = FakeBackend(payload=completion("Just prose, no grammar."))
    adapter = _loaded(adapter_module, tmp_path, monkeypatch, backend)
    raw = adapter.infer(_page(png))
    assert "no_block_markers" in raw.warnings
    assert raw.semantic_error_class == "OUTPUT_MALFORMED"


def test_infer_flags_empty_output(
    adapter_module: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, png: Path
) -> None:
    backend = FakeBackend(payload=completion(""))
    adapter = _loaded(adapter_module, tmp_path, monkeypatch, backend)
    raw = adapter.infer(_page(png))
    assert "empty_output" in raw.warnings
    # Emptiness is the more specific fact and wins over a length stop.
    assert raw.semantic_error_class == "OUTPUT_EMPTY"


def test_infer_rejects_a_malformed_completion(
    adapter_module: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, png: Path
) -> None:
    backend = FakeBackend(payload={"choices": []})
    adapter = _loaded(adapter_module, tmp_path, monkeypatch, backend)
    with pytest.raises(AdapterError) as caught:
        adapter.infer(_page(png))
    assert caught.value.error_class == "OUTPUT_MALFORMED"


def test_infer_before_load_raises(adapter_module: ModuleType, png: Path) -> None:
    adapter = adapter_module.create_adapter(lambda cfg: FakeBackend())
    with pytest.raises(AdapterError) as caught:
        adapter.infer(_page(png))
    assert caught.value.error_class == "MODEL_LOAD"


def test_infer_rejects_a_missing_image(
    adapter_module: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = _loaded(adapter_module, tmp_path, monkeypatch, FakeBackend())
    with pytest.raises(AdapterError) as caught:
        adapter.infer(_page(tmp_path / "absent.png"))
    assert caught.value.error_class == "INPUT_DECODE"


@pytest.mark.parametrize(
    ("exception", "expected"),
    [
        (RuntimeError("CUDA error: out of memory"), "CUDA_OOM"),
        (TimeoutError("read timed out"), "INFERENCE_TIMEOUT"),
        (RuntimeError("shape mismatch during forking"), "TENSOR_SHAPE"),
        (ConnectionError("connection refused"), "INFRA_NETWORK"),
        (Exception("novel failure"), "UNKNOWN"),
    ],
)
def test_infer_classifies_backend_failures(
    adapter_module: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    png: Path,
    exception: BaseException,
    expected: str,
) -> None:
    adapter = _loaded(adapter_module, tmp_path, monkeypatch, FakeBackend(error=exception))
    with pytest.raises(AdapterError) as caught:
        adapter.infer(_page(png))
    assert caught.value.error_class == expected


def test_close_reaps_the_backend(
    adapter_module: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = FakeBackend()
    adapter = _loaded(adapter_module, tmp_path, monkeypatch, backend)
    adapter.close()
    assert backend.closed is True


# --------------------------------------------------------------------------- #
# canonicalization fixtures
# --------------------------------------------------------------------------- #


def raw_output(text: str, **overrides: Any) -> RawOutput:
    defaults: dict[str, Any] = {
        "raw_text": text,
        "output_format": "hpd_blocks",
        "native_json": {"finish_reason": "stop"},
        "usage": {},
        "timings_ms": {"preprocess_ms": 0, "inference_ms": 1, "postprocess_ms": 0},
        "warnings": (),
    }
    defaults.update(overrides)
    return RawOutput(**defaults)


def test_canonical_heading_map_is_fixed(canonical_module: ModuleType) -> None:
    out = canonical_module.canonicalize(raw_output(BLOCK_OUTPUT))
    assert out.markdown == (
        "# Annual Report 2026\n\n## Results\n\nRevenue grew."
    )
    assert out.lossy is False


def test_canonical_records_a_block_without_child_text(canonical_module: ModuleType) -> None:
    # The `image` block carries no text, so it contributes no Markdown - that is
    # representing absence, not dropping content. It still appears as an element.
    out = canonical_module.canonicalize(raw_output(BLOCK_OUTPUT))
    assert out.elements is not None
    assert [element["type"] for element in out.elements] == [
        "doc_title", "paragraph_title", "text", "image"
    ]
    assert out.elements[-1]["content"] is None
    assert out.elements[-1]["bbox"] == [12, 320, 900, 700]
    assert "blocks_without_child_text:1" in out.conversion_notes


def test_canonical_table(canonical_module: ModuleType) -> None:
    stream = "<BLOCK>table [0,0,10,10]<CHILD><table><tr><td>1</td></tr></table>"
    out = canonical_module.canonicalize(raw_output(stream))
    assert out.markdown == "<table><tr><td>1</td></tr></table>"


def test_canonical_formula(canonical_module: ModuleType) -> None:
    stream = "<BLOCK>formula [0,0,10,10]<CHILD>$$E = mc^{2}$$"
    out = canonical_module.canonicalize(raw_output(stream))
    assert out.markdown == "$$E = mc^{2}$$"


def test_canonical_empty(canonical_module: ModuleType) -> None:
    out = canonical_module.canonicalize(raw_output("", warnings=("empty_output",)))
    assert out.markdown == ""
    assert out.elements == ()
    assert "empty_raw_text" in out.conversion_notes
    assert "warning:empty_output" in out.conversion_notes
    assert out.lossy is False


def test_canonical_truncated_keeps_the_warning(canonical_module: ModuleType) -> None:
    stream = "<BLOCK>text [0,0,10,10]<CHILD>The sentence stops mid-w"
    out = canonical_module.canonicalize(raw_output(stream, warnings=("output_truncated",)))
    assert "warning:output_truncated" in out.conversion_notes
    assert out.markdown.endswith("mid-w")


def test_canonical_preserves_text_outside_the_grammar_and_flags_it(
    canonical_module: ModuleType,
) -> None:
    out = canonical_module.canonicalize(
        raw_output("stray preamble<BLOCK>text [0,0,1,1]<CHILD>Body")
    )
    assert out.markdown == "stray preamble\n\nBody"
    assert out.lossy is True
    assert "text_before_first_block_preserved_verbatim" in out.conversion_notes


def test_canonical_keeps_raw_text_when_there_is_no_grammar(
    canonical_module: ModuleType,
) -> None:
    out = canonical_module.canonicalize(raw_output("Plain prose with no markers."))
    assert out.markdown == "Plain prose with no markers."
    assert out.elements is None
    assert any(note.startswith("no_block_markers") for note in out.conversion_notes)
    assert out.lossy is False


def test_canonical_bbox_that_cannot_be_parsed_is_null_not_guessed(
    canonical_module: ModuleType,
) -> None:
    out = canonical_module.canonicalize(raw_output("<BLOCK>text [1,2]<CHILD>Body"))
    assert out.elements is not None
    assert out.elements[0]["bbox"] is None
    assert out.elements[0]["bbox_raw"] == "1,2"
    assert "blocks_with_unparsable_bbox:1" in out.conversion_notes


def test_canonical_flags_an_unexpected_format(canonical_module: ModuleType) -> None:
    out = canonical_module.canonicalize(raw_output("text", output_format="markdown"))
    assert "unexpected_output_format:markdown" in out.conversion_notes


# =========================================================================
# 2026-09-03 GLM-OCR canary incident: fail fast and visibly, before a GPU
#
# The GLM-OCR canary reached the model-server start and died on a model_type its
# image's Transformers did not know; RunPod restarted the exited start command and
# the pod crash-looped while billing. These checks are string-level facts about the
# shipped scripts - no GPU, no network, no container runtime.
# =========================================================================


def test_bootstrap_carries_an_architecture_preflight_hpd_parsing() -> None:
    from incident_checks import assert_architecture_preflight

    assert_architecture_preflight("hpd_parsing")


def test_the_preflight_names_this_checkpoints_architecture_hpd_parsing() -> None:
    """A preflight that does not name what it expects would pass on any checkpoint."""
    from incident_checks import read_runtime_script

    text = read_runtime_script("hpd_parsing", "bootstrap.sh")
    assert 'EXPECTED_MODEL_TYPE = "internvl_chat"' in text
    assert 'EXPECTED_ARCH = "InternVLChatModel"' in text
    # the model card requires the customized build, not a stock 0.17.1
    assert 'PINNED_VLLM_LOCAL = "hpdparsing"' in text
    assert "ModelRegistry.get_supported_archs()" in text


def test_the_framework_floor_audit_is_recorded_hpd_parsing() -> None:
    """D: the audit result lives in provenance.json, and runtime.json's notes say so.

    It is not a top-level runtime.json field because runtime.schema.json is
    ``additionalProperties: false`` and belongs to another lane; loosening that
    schema to hold an audit record would be the wrong fix.
    """
    import json

    from incident_checks import load_runtime_json, runtime_dir

    provenance = json.loads(
        (runtime_dir("hpd_parsing") / "provenance.json").read_text(encoding="utf-8")
    )
    audit = provenance["framework_floor_audit"]
    for field in ("required", "image_ships", "action", "evidence"):
        assert audit[field], f"framework_floor_audit.{field} is empty"
    assert all(url.startswith("https://") for url in audit["evidence"])
    notes = load_runtime_json("hpd_parsing")["notes"]
    joined = " ".join(notes) if isinstance(notes, list) else notes
    assert "framework_floor_audit" in joined


def test_entrypoint_makes_a_model_server_failure_sticky_hpd_parsing() -> None:
    """Exiting is what RunPod restarts, so a start failure holds the container."""
    from incident_checks import assert_sticky_model_server_failure

    assert_sticky_model_server_failure("hpd_parsing")
