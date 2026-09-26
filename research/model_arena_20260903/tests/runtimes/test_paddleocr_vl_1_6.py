"""Tests for runtimes/paddleocr_vl_1_6/.

The module loaders below duplicate what tests/runtimes/conftest.py offers, using
the same ``sys.modules`` key convention so nothing is imported twice. They are
local on purpose: conftest.py is shared by three runtime lanes building in
parallel, and these tests must not break when another lane edits it.

No GPU, no network, no paddle, no vllm. The heavy stack is replaced by a fake
backend injected through ``create_adapter``.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from arena.worker.adapter_api import AdapterConfig, AdapterError, PageInput, RawOutput

MODEL_KEY = "paddleocr_vl_1_6"
NAMESPACE_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_DIR = NAMESPACE_ROOT / "runtimes" / MODEL_KEY
RUNTIME_SCHEMA = NAMESPACE_ROOT / "arena" / "core" / "schemas" / "runtime.schema.json"

REQUIRED_RUNTIME_FIELDS = (
    "model_key", "display_name", "model_repo", "model_revision", "official_runtime",
    "runtime_version", "base_image", "gpu_min_vram_gb", "gpu_pool_priority",
    "max_concurrency_per_worker", "shard_size_hint", "per_page_timeout_seconds",
    "prompt_id", "inference_config", "weights_strategy", "runtime_mode_allowed",
    "official_source_urls", "license", "notes", "weights",
)
FORBIDDEN_TOP_LEVEL_IMPORTS = frozenset(
    {"paddleocr", "paddle", "paddlex", "vllm", "torch", "transformers", "mineru", "PIL"}
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
    """Never invent data to satisfy a schema: every null names itself."""
    unresolved = null_paths(document) + null_paths(provenance)
    pending = provenance.get("to_verify_in_canary")
    assert isinstance(pending, list) and pending
    joined = " ".join(str(item) for item in pending)
    for field in unresolved:
        assert field.rsplit(".", 1)[-1] in joined, f"null field {field} is undocumented"


def assert_schema_conformance(document: Mapping[str, Any]) -> list[str]:
    """Validate against A1's schema; return the json paths that still fail.

    Returning rather than asserting lets a runtime whose base image digest is
    genuinely unresolvable stay honest instead of carrying a fabricated digest.
    """
    if not RUNTIME_SCHEMA.is_file():
        return []
    import jsonschema

    validator = jsonschema.Draft202012Validator(
        json.loads(RUNTIME_SCHEMA.read_text(encoding="utf-8"))
    )
    return [error.json_path for error in validator.iter_errors(dict(document))]


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #

PAGE_JSON: dict[str, Any] = {
    "res": {
        "parsing_res_list": [
            {"block_label": "doc_title", "block_bbox": [10, 10, 90, 30], "block_content": "Title"},
            {"block_label": "text", "block_bbox": [10, 40, 90, 80], "block_content": "Body"},
        ]
    }
}


class FakeBackend:
    """Stands in for the pipeline client plus the genai_server subprocess."""

    def __init__(
        self,
        pages: Sequence[tuple[Mapping[str, Any], str]] | None = None,
        error: BaseException | None = None,
    ) -> None:
        self.pages = list(pages if pages is not None else [(PAGE_JSON, "# Title\n\nBody")])
        self.error = error
        self.started = False
        self.closed = False

    def start(self) -> Mapping[str, Any]:
        self.started = True
        return {"genai_server_command": ["paddleocr", "genai_server"], "pipeline_options": {}}

    def predict(self, image_path: Path) -> Sequence[tuple[Mapping[str, Any], str]]:
        if self.error is not None:
            raise self.error
        return self.pages

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
    directory.mkdir()
    (directory / "model.safetensors").write_bytes(payload)
    (directory / "arena-weights-revision.txt").write_text(revision, encoding="utf-8")
    return directory


def patched_spec(
    monkeypatch: pytest.MonkeyPatch, module: ModuleType, weights_dir: Path
) -> dict[str, Any]:
    """Point runtime_spec at a digest we can actually satisfy in a tmpdir."""
    import hashlib

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
        "prompt_text": "",
        "inference_config": document["inference_config"],
        "inference_config_sha256": "sha256:" + "0" * 64,
        "max_concurrency": document["max_concurrency_per_worker"],
        "device": "cuda:0",
    }
    defaults.update(overrides)
    return AdapterConfig(**defaults)


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
        "sha256:ad0b1f056a76967f9191cd06398e8babb21b49a4673a28c3de5fd31f481884db"
    )
    assert resolved["digest"] in load_runtime_json(MODEL_KEY)["base_image"]


def test_base_image_pins_the_documented_version_tag_by_digest() -> None:
    # `latest-*` moves by design, so the documented per-version tag form
    # (paddleocr<major>.<minor>-nvidia-gpu) is what is named; the digest is what
    # binds. paddleocr3.7-nvidia-gpu still does not exist on the registry.
    base_image = load_runtime_json(MODEL_KEY)["base_image"]
    assert base_image.startswith(
        "ccr-2vdh3abv-pub.cnc.bj.baidubce.com/paddlepaddle/"
        "paddleocr-vl:paddleocr3.6-nvidia-gpu@sha256:"
    )
    assert "paddleocr3.7-nvidia-gpu" not in base_image
    resolved = load_provenance_json(MODEL_KEY)["base_image_digest"]
    assert resolved["tag_that_does_not_exist"] == "paddleocr3.7-nvidia-gpu"
    # The aliases are recorded so a reader can re-resolve any of them and land
    # on the same image.
    assert {"latest-nvidia-gpu", "paddleocr3.6-nvidia-gpu"} <= set(
        resolved["aliases_same_digest"]
    )
    for name in ("Dockerfile", "bootstrap.sh"):
        text = (RUNTIME_DIR / name).read_text(encoding="utf-8")
        # An absent or moving tag may be named in a comment as the record of
        # what was checked; neither may appear in a line that runs.
        for line in executable_lines(text):
            assert "paddleocr3.7-nvidia-gpu" not in line, f"stale tag still used in {name}"
            assert "latest-nvidia-gpu" not in line, f"moving tag still used in {name}"
        assert "paddleocr3.6-nvidia-gpu" in text


def test_no_paddleocr_version_is_installed_over_the_official_image() -> None:
    # PaddleOCR v3.6.0 is the release that shipped PaddleOCR-VL-1.6, so the
    # official image already carries it and the 3.7.0 overlay this runtime used
    # to add is gone. The versions the image carries are asserted, not assumed.
    finding = load_provenance_json(MODEL_KEY)["paddleocr_version_finding"]
    assert "3.6.0" in finding["image_ships"]
    assert "3.6.0" in finding["runtime_requires"]
    assert finding["supersedes"]
    assert finding["evidence"]
    assert finding["residual_risk"]

    dockerfile = (RUNTIME_DIR / "Dockerfile").read_text(encoding="utf-8")
    bootstrap = (RUNTIME_DIR / "bootstrap.sh").read_text(encoding="utf-8")
    for name, text in (("Dockerfile", dockerfile), ("bootstrap.sh", bootstrap)):
        for line in executable_lines(text):
            assert "paddleocr[doc-parser]" not in line, (
                f"{name} still installs paddleocr over the official image"
            )
            assert "paddlex==" not in line, f"{name} invents a paddlex pin"
            assert "pip install -U" not in line, f"{name} upgrades in place"
    # The assertion is fail-closed: a moved tag or a re-tagged image stops the
    # build rather than silently changing the model.
    assert "expected paddleocr 3.6.0 / paddlex 3.6.1" in dockerfile
    assert 'PADDLEOCR_VERSION="3.6.0"' in bootstrap
    assert 'PADDLEX_VERSION="3.6.1"' in bootstrap
    assert "expected {want}" in bootstrap

    # Only the two things the official docs say this image still needs, plus the
    # arena's own weight-fetch client, are installed.
    for text in (dockerfile, bootstrap):
        assert "flash_attn-2.8.2" in text
        assert "paddleocr install_genai_server_deps vllm" in text
        assert "huggingface_hub[cli]==0.35.3" in text


def test_runtime_source_revision_is_the_release_that_shipped_the_model() -> None:
    document = load_runtime_json(MODEL_KEY)
    provenance = load_provenance_json(MODEL_KEY)
    # v3.6.0 = commit 0006f787..., and the image's own label records the same
    # short revision, which is what ties the pinned image to the pinned source.
    assert document["runtime_revision"] == "0006f7874c334ce9c0f497d8b6cce9cdc0b7363d"
    assert provenance["runtime_source_release_tag"] == "v3.6.0"
    assert provenance["runtime_source_revision"] == document["runtime_revision"]
    labels = provenance["base_image_digest"]["image_labels"]
    assert document["runtime_revision"].startswith(
        labels["org.opencontainers.image.revision"]
    )


def test_the_registry_enumeration_shows_nothing_newer_exists() -> None:
    # The choice of "the official image, unmodified" only holds while no newer
    # official image exists. The enumeration that established that is recorded,
    # repository by repository, so it can be redone.
    enumeration = load_provenance_json(MODEL_KEY)["registry_tag_enumeration"]
    repositories = enumeration["repositories"]
    assert isinstance(repositories, dict)
    for required in (
        "ccr-2vdh3abv-pub.cnc.bj.baidubce.com/paddlepaddle/paddleocr-vl",
        "ccr-2vdh3abv-pub.cnc.bj.baidubce.com/paddlepaddle/paddleocr-genai-vllm-server",
        "ccr-2vdh3abv-pub.cnc.bj.baidubce.com/paddlex/paddlex",
        "docker.io/paddlepaddle/paddle",
    ):
        assert required in repositories, f"{required} was not enumerated"
        assert repositories[required]
    assert enumeration["enumerated_at"]
    assert enumeration["method"]
    assert enumeration["conclusion"]


def test_runtime_json_pins_the_documented_production_path() -> None:
    document = load_runtime_json(MODEL_KEY)
    config = document["inference_config"]
    # The official docs warn that a bare VLM call is not the pipeline; the split
    # must stay in the pin, not just in the README.
    assert config["vl_rec_backend"] == "vllm-server"
    assert config["pipeline_version"] == "v1.6"
    assert document["official_runtime"] == "paddle"
    assert len(document["model_revision"]) == 40
    assert set(document["model_revision"]) <= set("0123456789abcdef")


def test_provenance_records_the_v6_registry_disagreement() -> None:
    # The repository moved after 2026-08-01. Keeping the older pin as provenance
    # is the honest option; quietly adopting it would be a fabricated resolution.
    cross_check = load_provenance_json(MODEL_KEY)["model_revision_cross_check"]
    assert cross_check["agrees"] is False
    assert cross_check["recorded_revision"] == "66317acc4c9fc17bd154591ce650735cd2855f3e"
    assert cross_check["recorded_revision"] != load_runtime_json(MODEL_KEY)["model_revision"]


def test_runtime_text_carries_no_secret_markers() -> None:
    for name in ("runtime.json", "provenance.json", "Dockerfile", "bootstrap.sh"):
        text = (RUNTIME_DIR / name).read_text(encoding="utf-8")
        for marker in ("rpa_", "sk-", "ghp_", "AKIA"):
            assert marker not in text, f"possible secret marker {marker!r} in {name}"


def test_every_runtime_file_exists() -> None:
    for name in ("runtime.json", "provenance.json", "adapter.py", "canonical.py",
                 "Dockerfile", "bootstrap.sh", "README.md"):
        assert (RUNTIME_DIR / name).is_file(), f"{name} is missing"


def executable_lines(text: str) -> list[str]:
    return [
        line for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def test_dockerfile_pins_and_never_upgrades() -> None:
    text = (RUNTIME_DIR / "Dockerfile").read_text(encoding="utf-8")
    assert all("pip install -U" not in line for line in executable_lines(text))
    assert "@${BASE_IMAGE_DIGEST}" in text  # base pinned by digest, fail closed
    assert "--revision" in text and "sha256sum -c" in text


def test_bootstrap_is_canary_only_and_pins() -> None:
    text = (RUNTIME_DIR / "bootstrap.sh").read_text(encoding="utf-8")
    assert all("pip install -U" not in line for line in executable_lines(text))
    assert "CANARY-ONLY" in text
    assert "/workspace/arena/weights/" in text
    assert "bootstrap-receipt.txt" in text
    assert "sha256sum -c" in text
    # ARENA_CONTRACT section 11.3 item 4: the bundle is already extracted.
    assert "ARENA_BUNDLE_URL" not in text


def test_bootstrap_respects_a_non_default_arena_root() -> None:
    """D54: the official image's USER paddleocr cannot write /opt
    (HOME=/home/paddleocr, from the image's own OCI config), so this must read
    ARENA_ROOT from the environment rather than hard-code /opt/arena."""
    text = (RUNTIME_DIR / "bootstrap.sh").read_text(encoding="utf-8")
    assert 'ARENA_ROOT="${ARENA_ROOT:-/opt/arena}"' in text


def test_bootstrap_falls_back_off_workspace_for_weights_when_not_writable() -> None:
    """D54: /workspace may be as unwritable as /opt for a non-root user; the
    weights and results directories must fall back under ARENA_ROOT."""
    text = (RUNTIME_DIR / "bootstrap.sh").read_text(encoding="utf-8")
    assert 'WEIGHTS_ROOT_DEFAULT="/workspace/arena/weights/${MODEL_KEY}"' in text
    assert 'WEIGHTS_ROOT_DEFAULT="${ARENA_ROOT}/weights/${MODEL_KEY}"' in text
    assert 'RESULTS_DIR_DEFAULT="${ARENA_ROOT}/results"' in text
    assert 'WEIGHTS_ROOT="${ARENA_WEIGHTS_DIR:-${WEIGHTS_ROOT_DEFAULT}}"' in text
    assert 'mkdir -p "${WEIGHTS_ROOT}" /workspace/arena/results' not in text


def test_bootstrap_pip_installs_fall_back_to_user_site_outside_a_venv() -> None:
    """D54: paddleocr-vl's PATH carries no venv (confirmed from the image's own
    OCI config), so a system-site pip install can need this fallback for real,
    unlike hpd_parsing's venv-owning image. Must not force --user inside a venv
    (pip refuses --user there)."""
    text = (RUNTIME_DIR / "bootstrap.sh").read_text(encoding="utf-8")
    assert "pip_install()" in text
    assert "--user" in text
    assert "sys.prefix == getattr(sys, 'base_prefix', sys.prefix)" in text
    assert 'pip_install "${FLASH_ATTN_WHEEL}"' in text
    assert 'pip_install "huggingface_hub[cli]==0.35.3"' in text
    # paddleocr's own installer CLI is not wrapped -- it is not a raw pip call,
    # so a --user retry cannot be forced through its argv (D54, documented as a
    # residual risk in the runtime bootstrap.sh comment).
    assert "paddleocr install_genai_server_deps vllm" in text


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


def test_runtime_spec_reads_the_file_on_disk(adapter_module: ModuleType) -> None:
    assert dict(adapter_module.runtime_spec()) == load_runtime_json(MODEL_KEY)


# --------------------------------------------------------------------------- #
# load(): happy path and every failure path
# --------------------------------------------------------------------------- #


def test_load_returns_a_receipt(
    adapter_module: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    document = load_runtime_json(MODEL_KEY)
    weights = make_weights(tmp_path, document["model_revision"])
    patched_spec(monkeypatch, adapter_module, weights)
    backend = FakeBackend()
    adapter = adapter_module.create_adapter(lambda cfg: backend)

    receipt = adapter.load(make_config(weights))

    assert backend.started is True
    assert receipt.model_key == MODEL_KEY
    assert receipt.model_revision == document["model_revision"]
    assert receipt.weights_sha256_manifest.startswith("sha256:")
    assert receipt.cache_hit is False
    assert receipt.runtime_provenance["official_runtime"] == "paddle"


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
    assert caught.value.error_class == "MODEL_LOAD"
    assert "digest mismatch" in str(caught.value)


def test_load_rejects_a_missing_revision_stamp(
    adapter_module: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    document = load_runtime_json(MODEL_KEY)
    weights = make_weights(tmp_path, document["model_revision"])
    patched_spec(monkeypatch, adapter_module, weights)
    (weights / "arena-weights-revision.txt").unlink()
    adapter = adapter_module.create_adapter(lambda cfg: FakeBackend())

    with pytest.raises(AdapterError) as caught:
        adapter.load(make_config(weights))
    assert caught.value.error_class == "MODEL_LOAD"


def test_load_rejects_a_user_prompt(
    adapter_module: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # PaddleOCR-VL's prompt lives inside the official pipeline. Accepting one
    # would silently leave the official path.
    document = load_runtime_json(MODEL_KEY)
    weights = make_weights(tmp_path, document["model_revision"])
    patched_spec(monkeypatch, adapter_module, weights)
    adapter = adapter_module.create_adapter(lambda cfg: FakeBackend())

    with pytest.raises(AdapterError) as caught:
        adapter.load(make_config(weights, prompt_text="transcribe this page"))
    assert caught.value.error_class == "MODEL_LOAD"


def test_load_rejects_a_foreign_model_key(
    adapter_module: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    document = load_runtime_json(MODEL_KEY)
    weights = make_weights(tmp_path, document["model_revision"])
    patched_spec(monkeypatch, adapter_module, weights)
    adapter = adapter_module.create_adapter(lambda cfg: FakeBackend())

    with pytest.raises(AdapterError):
        adapter.load(make_config(weights, model_key="mineru_vlm"))


def test_load_reports_a_backend_failure_as_model_load(
    adapter_module: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    document = load_runtime_json(MODEL_KEY)
    weights = make_weights(tmp_path, document["model_revision"])
    patched_spec(monkeypatch, adapter_module, weights)

    def explode(cfg: AdapterConfig) -> FakeBackend:
        raise RuntimeError("vLLM service never became ready")

    adapter = adapter_module.create_adapter(explode)
    with pytest.raises(AdapterError) as caught:
        adapter.load(make_config(weights))
    assert caught.value.error_class == "MODEL_LOAD"


# --------------------------------------------------------------------------- #
# infer()
# --------------------------------------------------------------------------- #


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
        inference_job_id="a" * 64,
        sample_id="omnidoc:images/PPT_1001115_eng_page_003",
        case_key="omnidocbench-58851882e7b39101a6f5756c",
        benchmark="omnidoc",
        image_path=png,
        source_sha256="sha256:" + "0" * 64,
        width=1654,
        height=2339,
        metadata={"page_index": 0, "media_type": "png"},
    )


def test_infer_returns_the_markdown_verbatim(
    adapter_module: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, png: Path
) -> None:
    backend = FakeBackend()
    adapter = _loaded(adapter_module, tmp_path, monkeypatch, backend)

    raw = adapter.infer(_page(png))

    assert raw.raw_text == "# Title\n\nBody"
    assert raw.output_format == "markdown"
    assert raw.warnings == ()
    # A well-formed, non-empty page carries no semantic verdict at all.
    assert raw.semantic_error_class is None
    assert raw.native_json is not None
    assert raw.native_json["pages"][0] == PAGE_JSON
    assert raw.timings_ms["inference_ms"] >= 0


def test_infer_warns_on_empty_output_but_does_not_fail(
    adapter_module: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, png: Path
) -> None:
    # Masterplan section 41: a valid blank source is not a failed extraction, and
    # the adapter is not the layer that decides which one this is.
    backend = FakeBackend(pages=[({"res": {}}, "")])
    adapter = _loaded(adapter_module, tmp_path, monkeypatch, backend)

    raw = adapter.infer(_page(png))

    assert raw.raw_text == ""
    assert "empty_output" in raw.warnings
    # ARENA_CONTRACT D3: SUCCESS with a semantic verdict, not an error.
    assert raw.semantic_error_class == "OUTPUT_EMPTY"


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
        (TimeoutError("request timed out"), "INFERENCE_TIMEOUT"),
        (RuntimeError("shape mismatch in attention"), "TENSOR_SHAPE"),
        (ValueError("unparsable result"), "OUTPUT_MALFORMED"),
        (Exception("something new"), "UNKNOWN"),
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


def test_warmup_runs_one_page(
    adapter_module: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, png: Path
) -> None:
    adapter = _loaded(adapter_module, tmp_path, monkeypatch, FakeBackend())
    receipt = adapter.warmup(png)
    assert receipt.schema_valid is True
    assert receipt.output_chars == len("# Title\n\nBody")


# --------------------------------------------------------------------------- #
# canonicalization fixtures
# --------------------------------------------------------------------------- #


def raw_output(text: str, **overrides: Any) -> RawOutput:
    defaults: dict[str, Any] = {
        "raw_text": text,
        "output_format": "markdown",
        "native_json": {"pages": [PAGE_JSON], "page_markdown": [text]},
        "usage": {},
        "timings_ms": {"preprocess_ms": 0, "inference_ms": 1, "postprocess_ms": 0},
        "warnings": (),
    }
    defaults.update(overrides)
    return RawOutput(**defaults)


def test_canonical_heading(canonical_module: ModuleType) -> None:
    out = canonical_module.canonicalize(raw_output("# Annual Report\n\nSome body text."))
    assert out.markdown == "# Annual Report\n\nSome body text."
    assert out.lossy is False


def test_canonical_table_is_untouched(canonical_module: ModuleType) -> None:
    table = "| a | b |\n| --- | --- |\n| 1 | 2 |"
    out = canonical_module.canonicalize(raw_output(table))
    assert out.markdown == table


def test_canonical_formula_is_untouched(canonical_module: ModuleType) -> None:
    formula = "$$E = mc^{2}$$"
    out = canonical_module.canonicalize(raw_output(formula))
    assert out.markdown == formula


def test_canonical_empty(canonical_module: ModuleType) -> None:
    out = canonical_module.canonicalize(
        raw_output("", native_json=None, warnings=("empty_output",))
    )
    assert out.markdown == ""
    assert "empty_raw_text" in out.conversion_notes
    assert "warning:empty_output" in out.conversion_notes
    assert out.elements is None
    assert out.lossy is False


def test_canonical_truncated_keeps_the_warning(canonical_module: ModuleType) -> None:
    # A canonicalizer may never drop a truncation warning (adapter_api docstring).
    out = canonical_module.canonicalize(
        raw_output("# Partial page\n\nThe text stops mid-sen", warnings=("output_truncated",))
    )
    assert "warning:output_truncated" in out.conversion_notes
    assert out.markdown.endswith("mid-sen")


def test_canonical_normalizes_whitespace_without_losing_content(
    canonical_module: ModuleType,
) -> None:
    out = canonical_module.canonicalize(raw_output("\r\n\r\n# T   \r\n\n\n\n\nBody\n\n\n"))
    assert out.markdown == "# T\n\n\nBody"
    assert out.lossy is False


def test_canonical_attaches_elements_from_the_pipeline_json(
    canonical_module: ModuleType,
) -> None:
    out = canonical_module.canonicalize(raw_output("# Title\n\nBody"))
    assert out.elements is not None
    assert [element["type"] for element in out.elements] == ["doc_title", "text"]
    assert out.elements[0]["bbox"] == [10, 10, 90, 30]
    assert out.elements[0]["content"] == "Title"


def test_canonical_never_invents_elements(canonical_module: ModuleType) -> None:
    out = canonical_module.canonicalize(
        raw_output("# Title", native_json={"pages": [{"res": {}}], "page_markdown": ["# Title"]})
    )
    assert out.elements is None
    assert any(note.startswith("no_elements_available") for note in out.conversion_notes)


def test_canonical_flags_an_unexpected_format(canonical_module: ModuleType) -> None:
    out = canonical_module.canonicalize(raw_output("text", output_format="html"))
    assert "unexpected_output_format:html" in out.conversion_notes


# =========================================================================
# 2026-09-03 GLM-OCR canary incident: fail fast and visibly, before a GPU
#
# The GLM-OCR canary reached the model-server start and died on a model_type its
# image's Transformers did not know; RunPod restarted the exited start command and
# the pod crash-looped while billing. These checks are string-level facts about the
# shipped scripts - no GPU, no network, no container runtime.
# =========================================================================


def test_bootstrap_carries_an_architecture_preflight_paddleocr_vl_1_6() -> None:
    from incident_checks import assert_architecture_preflight

    assert_architecture_preflight("paddleocr_vl_1_6")


def test_the_preflight_names_this_checkpoints_architecture_paddleocr_vl_1_6() -> None:
    """A preflight that does not name what it expects would pass on any checkpoint."""
    from incident_checks import read_runtime_script

    text = read_runtime_script("paddleocr_vl_1_6", "bootstrap.sh")
    assert 'EXPECTED_MODEL_TYPE = "paddleocr_vl"' in text
    assert 'EXPECTED_ARCH = "PaddleOCRVLForConditionalGeneration"' in text
    # the VLM stage is served by the genai_server's vLLM, so its registry decides
    assert "ModelRegistry.get_supported_archs()" in text
    assert "from paddleocr import PaddleOCRVL" in text


def test_the_framework_floor_audit_is_recorded_paddleocr_vl_1_6() -> None:
    """D: the audit result lives in provenance.json, and runtime.json's notes say so.

    It is not a top-level runtime.json field because runtime.schema.json is
    ``additionalProperties: false`` and belongs to another lane; loosening that
    schema to hold an audit record would be the wrong fix.
    """
    import json

    from incident_checks import load_runtime_json, runtime_dir

    provenance = json.loads(
        (runtime_dir("paddleocr_vl_1_6") / "provenance.json").read_text(encoding="utf-8")
    )
    audit = provenance["framework_floor_audit"]
    for field in ("required", "image_ships", "action", "evidence"):
        assert audit[field], f"framework_floor_audit.{field} is empty"
    assert all(url.startswith("https://") for url in audit["evidence"])
    notes = load_runtime_json("paddleocr_vl_1_6")["notes"]
    joined = " ".join(notes) if isinstance(notes, list) else notes
    assert "framework_floor_audit" in joined


def test_entrypoint_makes_a_model_server_failure_sticky_paddleocr_vl_1_6() -> None:
    """Exiting is what RunPod restarts, so a start failure holds the container."""
    from incident_checks import assert_sticky_model_server_failure

    assert_sticky_model_server_failure("paddleocr_vl_1_6")
