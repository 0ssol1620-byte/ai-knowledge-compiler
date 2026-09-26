"""Tests for runtimes/mineru_vlm/.

The loaders duplicate what tests/runtimes/conftest.py offers, using the same
``sys.modules`` key convention so nothing is imported twice. They are local on
purpose: conftest.py is shared by three runtime lanes building in parallel.

The tests that matter most here are the masterplan §14 concurrency guard and the
engine-resolution guard. Both must fail closed.
"""

from __future__ import annotations

import ast
import asyncio
import hashlib
import importlib.util
import json
import sys
import threading
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from arena.worker.adapter_api import AdapterConfig, AdapterError, PageInput, RawOutput

MODEL_KEY = "mineru_vlm"
PARSE_METHOD = "vlm"
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
    {"mineru", "torch", "torchvision", "transformers", "accelerate", "vllm", "paddleocr", "PIL"}
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


def executable_lines(text: str) -> list[str]:
    return [
        line for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #

MARKDOWN = "# Balance Sheet\n\n| item | 2026 |\n| --- | --- |\n| cash | 41 |"
CONTENT_LIST_V2: list[dict[str, Any]] = [
    {"type": "title", "text": "Balance Sheet", "page_idx": 0, "bbox": [1, 2, 3, 4]},
    {"type": "table", "table_body": "<table><tr><td>cash</td></tr></table>", "page_idx": 0},
]
MIDDLE_JSON: dict[str, Any] = {
    "pdf_info": [{"para_blocks": [{"type": "title", "bbox": [1, 2, 3, 4]}]}]
}
MODEL_JSON: list[dict[str, Any]] = [{"layout_dets": [], "page_info": {"page_no": 0}}]


class FakeBackend:
    """Writes the files MinerU's VLM backend writes."""

    def __init__(
        self,
        markdown: str | None = MARKDOWN,
        error: BaseException | None = None,
        start_error: BaseException | None = None,
        resolved_engine: str = "transformers",
    ) -> None:
        self.markdown = markdown
        self.error = error
        self.start_error = start_error
        self.resolved_engine = resolved_engine
        self.started = False
        self.closed = False
        self.calls: list[str] = []

    def start(self) -> Mapping[str, Any]:
        if self.start_error is not None:
            raise self.start_error
        self.started = True
        return {
            "entrypoint": "mineru.cli.common.do_parse",
            "backend": "vlm-engine",
            "resolved_vlm_engine": self.resolved_engine,
            "batch_size": 1,
            "env": {},
        }

    def parse(self, image_path: Path, output_dir: Path, stem: str) -> None:
        if self.error is not None:
            raise self.error
        self.calls.append(stem)
        case_dir = output_dir / stem / PARSE_METHOD
        case_dir.mkdir(parents=True)
        if self.markdown is not None:
            (case_dir / f"{stem}.md").write_text(self.markdown, encoding="utf-8")
        (case_dir / f"{stem}_middle.json").write_text(json.dumps(MIDDLE_JSON), encoding="utf-8")
        (case_dir / f"{stem}_model.json").write_text(json.dumps(MODEL_JSON), encoding="utf-8")
        (case_dir / f"{stem}_content_list_v2.json").write_text(
            json.dumps(CONTENT_LIST_V2), encoding="utf-8"
        )

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
        inference_job_id="d" * 64,
        sample_id="olmocr:bench_data/pdfs/arxiv_math/2502.15977_pg21#p0",
        case_key="olmocr-bench-2502-15977-pg21",
        benchmark="olmocr",
        image_path=png,
        source_sha256="sha256:" + "0" * 64,
        width=1654,
        height=2339,
        metadata={"page_index": 0, "media_type": "pdf"},
    )


# --------------------------------------------------------------------------- #
# D59: the official backend must hand MinerU's read_fn a suffix it recognises
# --------------------------------------------------------------------------- #


def test_mineru_file_suffix_strips_the_dot_path_suffix_keeps(
    adapter_module: ModuleType,
) -> None:
    # mineru.cli.common's image_suffixes/pdf_suffixes are bare tokens ("png",
    # "pdf"), never dotted; Path.suffix always keeps the dot.
    assert adapter_module._mineru_file_suffix(Path("page.png")) == "png"
    assert adapter_module._mineru_file_suffix(Path("page.PNG")) == "png"
    assert adapter_module._mineru_file_suffix(Path("doc.pdf")) == "pdf"


def test_official_backend_passes_dotless_suffix_to_read_fn(
    adapter_module: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    png: Path,
) -> None:
    """Reproduces the real canary's ``AdapterError: UNKNOWN: Exception: Unknown
    file suffix: .png`` (pod d4qo3kl49kai6v, after the vlm-engine preflight
    D59 already fixed): mineru.cli.common.read_fn raises that exact exception
    when handed a dotted suffix, because its own image_suffixes/pdf_suffixes
    lists hold bare tokens. This test exercises the real
    ``_OfficialMineruVlmBackend.parse`` input-conversion path with a real PNG
    fixture and a fake read_fn/do_parse pair standing in for MinerU itself -
    no GPU, no mineru import required.
    """
    document = load_runtime_json(MODEL_KEY)
    weights = make_weights(tmp_path, document["model_revision"])
    patched_spec(monkeypatch, adapter_module, weights)
    cfg = make_config(weights)
    backend = adapter_module._OfficialMineruVlmBackend(cfg)

    captured: dict[str, Any] = {}

    def fake_read_fn(path: Path, file_suffix: str) -> bytes:
        if file_suffix not in ("png", "jpeg", "jp2", "webp", "gif", "bmp", "jpg", "tiff", "pdf"):
            # The real mineru.cli.common.read_fn's own failure mode.
            raise Exception(f"Unknown file suffix: {file_suffix}")
        captured["read_fn_path"] = path
        captured["read_fn_suffix"] = file_suffix
        return b"official-pdf-bytes"

    async def fake_aio_do_parse(**kwargs: Any) -> None:
        captured["do_parse_kwargs"] = kwargs
        stem = kwargs["pdf_file_names"][0]
        case_dir = Path(kwargs["output_dir"]) / stem / PARSE_METHOD
        case_dir.mkdir(parents=True)
        (case_dir / f"{stem}.md").write_text("ok", encoding="utf-8")

    # D79: the backend parses on a loop it owns, the way the vendor's own
    # server does, so the test gives it one instead of a bare callable.
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    backend._read_fn = fake_read_fn
    backend._aio_do_parse = fake_aio_do_parse
    backend._loop = loop
    backend._loop_thread = thread

    output_dir = tmp_path / "backend-out"
    output_dir.mkdir()
    backend.parse(png, output_dir, "stem")

    assert captured["read_fn_path"] == png
    assert captured["read_fn_suffix"] == "png"
    assert captured["do_parse_kwargs"]["pdf_bytes_list"] == [b"official-pdf-bytes"]
    backend.close()


# --------------------------------------------------------------------------- #
# masterplan section 14 - the campaign's most important past incident
# --------------------------------------------------------------------------- #


def test_concurrency_is_pinned_to_one_everywhere() -> None:
    document = load_runtime_json(MODEL_KEY)
    assert document["max_concurrency_per_worker"] == 1
    policy = document["inference_config"]["concurrency_policy"]
    assert policy == {"per_worker": 1, "scale": "replicas_only"}
    assert document["inference_config"]["batch_size"] == 1
    assert document["inference_config"]["env"]["MINERU_API_MAX_CONCURRENT_REQUESTS"] == "1"


def test_load_refuses_any_concurrency_above_one(
    adapter_module: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # It refuses rather than clamping: a caller who asked for more has a wrong
    # plan, and silently correcting it hides the wrong plan.
    document = load_runtime_json(MODEL_KEY)
    weights = make_weights(tmp_path, document["model_revision"])
    patched_spec(monkeypatch, adapter_module, weights)
    backend = FakeBackend()
    adapter = adapter_module.create_adapter(lambda cfg: backend)

    with pytest.raises(AdapterError) as caught:
        adapter.load(make_config(weights, max_concurrency=3))

    assert caught.value.error_class == "MODEL_LOAD"
    assert "section 14" in str(caught.value)
    assert backend.started is False, "the guard must fire before the model loads"


def test_provenance_records_the_concurrency_incident() -> None:
    incidents = load_provenance_json(MODEL_KEY)["known_incidents"]
    concurrency = next(
        item for item in incidents if item["id"] == "masterplan-section-14-concurrency"
    )
    assert "48 of 54" in concurrency["summary"]
    assert concurrency["evidence"].endswith("MINERU_3_4_4_VLM_RUNTIME_DIAGNOSTIC_2026-08-01.md")
    assert "replicas" in concurrency["standing_rule"]


def test_documents_repeat_the_rule_where_someone_would_look() -> None:
    for name in ("README.md", "Dockerfile", "bootstrap.sh"):
        text = (RUNTIME_DIR / name).read_text(encoding="utf-8")
        assert "14" in text and "concurrency" in text.lower(), f"{name} omits the rule"


# --------------------------------------------------------------------------- #
# engine resolution must fail closed
# --------------------------------------------------------------------------- #


def test_runtime_json_pins_the_expected_vlm_engine() -> None:
    # D59: the base image is vllm/vllm-openai, so MinerU's
    # get_vlm_engine(inference_engine="auto") always resolves vlm-engine to
    # vllm-engine on it (vllm is importable), not transformers - confirmed by
    # a real canary FATAL on pod plz5obsz7ega3a. Pinning "transformers" here
    # was wrong for this image.
    # D79: and the engine it must resolve to is the async one. do_parse's
    # vllm-engine returned ']]<|><|><|><|>' for every page on this image while
    # aio_do_parse's vllm-async-engine parsed the same page correctly in the
    # same process, so the adapter is on the async path and the pin follows it.
    config = load_runtime_json(MODEL_KEY)["inference_config"]
    assert config["backend"] == "vlm-engine"
    assert config["expected_vlm_engine"] == "vllm-async-engine"
    assert load_runtime_json(MODEL_KEY)["official_runtime"] == "vllm"


def test_load_surfaces_an_engine_mismatch_as_model_load(
    adapter_module: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The real backend raises when get_vlm_engine("auto") disagrees with the pin.
    # Accepting whatever is installed would change what is measured while the
    # label stayed the same.
    document = load_runtime_json(MODEL_KEY)
    weights = make_weights(tmp_path, document["model_revision"])
    patched_spec(monkeypatch, adapter_module, weights)
    mismatch = AdapterError(
        "MODEL_LOAD",
        "MinerU resolved vlm-engine to 'vllm-engine' but runtime.json pins 'transformers'",
    )
    adapter = adapter_module.create_adapter(lambda cfg: FakeBackend(start_error=mismatch))

    with pytest.raises(AdapterError) as caught:
        adapter.load(make_config(weights))
    assert caught.value.error_class == "MODEL_LOAD"
    assert "vllm-engine" in str(caught.value)


def test_load_records_the_resolved_engine_in_provenance(
    adapter_module: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = _loaded(adapter_module, tmp_path, monkeypatch, FakeBackend())
    provenance = adapter.runtime_provenance()
    assert provenance["backend"]["resolved_vlm_engine"] == "transformers"
    assert provenance["backend"]["batch_size"] == 1
    assert provenance["concurrency_policy"] == {"per_worker": 1, "scale": "replicas_only"}


# --------------------------------------------------------------------------- #
# runtime.json
# --------------------------------------------------------------------------- #


def test_runtime_json_matches_the_contract() -> None:
    assert_runtime_contract(MODEL_KEY, load_runtime_json(MODEL_KEY))


def test_every_null_is_documented() -> None:
    assert_nulls_are_documented(load_runtime_json(MODEL_KEY), load_provenance_json(MODEL_KEY))


def test_runtime_json_validates_against_the_schema() -> None:
    if not RUNTIME_SCHEMA.is_file():
        pytest.skip("arena/core/schemas/runtime.schema.json has not landed yet")
    import jsonschema

    jsonschema.validate(
        instance=load_runtime_json(MODEL_KEY),
        schema=json.loads(RUNTIME_SCHEMA.read_text(encoding="utf-8")),
    )


def test_base_image_is_pinned_by_digest() -> None:
    assert load_runtime_json(MODEL_KEY)["base_image"].endswith(
        "@sha256:a230095847e93bd4df9888b33dab956fa9504537b828a23657d2b26fed57b5c9"
    )


def test_provenance_cross_check_agrees_with_the_2026_08_pin() -> None:
    # This is the only one of lane C1's four models whose weights pin is
    # unchanged since the previous campaign, and saying so is part of the record.
    cross_check = load_provenance_json(MODEL_KEY)["model_revision_cross_check"]
    assert cross_check["agrees"] is True
    assert cross_check["recorded_revision"] == load_runtime_json(MODEL_KEY)["model_revision"]


def test_provenance_pins_accelerate_to_the_version_that_worked() -> None:
    pins = load_provenance_json(MODEL_KEY)["runtime_dependency_pins"]
    assert pins["accelerate"] == "1.14.0"
    assert pins["transformers"] == "4.57.3"
    assert pins["mineru-vl-utils"] == "1.0.5"


def test_shard_size_reflects_that_this_is_the_slowest_lane() -> None:
    document = load_runtime_json(MODEL_KEY)
    historical = load_provenance_json(MODEL_KEY)["historical_evidence"]
    assert historical["seconds_per_page"] == 34.708
    assert document["shard_size_hint"] == 100


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
    assert "accelerate==1.14.0" in text
    assert "MINERU_API_MAX_CONCURRENT_REQUESTS=1" in text


def test_bootstrap_is_canary_only_and_records_the_engine() -> None:
    text = (RUNTIME_DIR / "bootstrap.sh").read_text(encoding="utf-8")
    assert all("pip install -U" not in line for line in executable_lines(text))
    assert "CANARY-ONLY" in text
    assert "resolved_vlm_engine" in text
    assert "concurrency_per_worker=1" in text


# --------------------------------------------------------------------------- #
# module hygiene
# --------------------------------------------------------------------------- #


def test_modules_import_without_the_heavy_stack(
    adapter_module: ModuleType, canonical_module: ModuleType
) -> None:
    assert adapter_module.MODEL_KEY == MODEL_KEY
    assert canonical_module.MODEL_KEY == MODEL_KEY
    assert adapter_module.REQUIRED_CONCURRENCY == 1
    for name in ("adapter.py", "canonical.py"):
        roots = top_level_import_roots(RUNTIME_DIR / name)
        assert not (roots & FORBIDDEN_TOP_LEVEL_IMPORTS), f"{name} imports a heavy package"


# --------------------------------------------------------------------------- #
# load() and infer()
# --------------------------------------------------------------------------- #


def test_load_rejects_a_wrong_weights_revision(
    adapter_module: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    weights = make_weights(tmp_path, "0" * 40)
    patched_spec(monkeypatch, adapter_module, weights)
    adapter = adapter_module.create_adapter(lambda cfg: FakeBackend())
    with pytest.raises(AdapterError) as caught:
        adapter.load(make_config(weights))
    assert "revision mismatch" in str(caught.value)


def test_load_rejects_a_tampered_checkpoint(
    adapter_module: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    document = load_runtime_json(MODEL_KEY)
    weights = make_weights(tmp_path, document["model_revision"])
    patched_spec(monkeypatch, adapter_module, weights)
    (weights / "model.safetensors").write_bytes(b"swapped")
    adapter = adapter_module.create_adapter(lambda cfg: FakeBackend())
    with pytest.raises(AdapterError) as caught:
        adapter.load(make_config(weights))
    assert "digest mismatch" in str(caught.value)


def test_load_rejects_a_prompt(
    adapter_module: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    document = load_runtime_json(MODEL_KEY)
    weights = make_weights(tmp_path, document["model_revision"])
    patched_spec(monkeypatch, adapter_module, weights)
    adapter = adapter_module.create_adapter(lambda cfg: FakeBackend())
    with pytest.raises(AdapterError):
        adapter.load(make_config(weights, prompt_text="transcribe"))


def test_infer_keeps_mineru_markdown_verbatim(
    adapter_module: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, png: Path
) -> None:
    backend = FakeBackend()
    adapter = _loaded(adapter_module, tmp_path, monkeypatch, backend)

    raw = adapter.infer(_page(png))

    assert raw.raw_text == MARKDOWN
    assert raw.output_format == "markdown"
    assert raw.native_json is not None
    assert raw.native_json["content_list_v2"] == CONTENT_LIST_V2
    # The VLM backend writes content_list_v2 but not content_list; that absence
    # is reported, not hidden.
    assert "missing_content_list" in raw.warnings


def test_infer_reports_a_missing_markdown_as_postprocess(
    adapter_module: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, png: Path
) -> None:
    adapter = _loaded(adapter_module, tmp_path, monkeypatch, FakeBackend(markdown=None))
    with pytest.raises(AdapterError) as caught:
        adapter.infer(_page(png))
    assert caught.value.error_class == "POSTPROCESS"


def test_infer_warns_on_an_empty_page_but_does_not_fail(
    adapter_module: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, png: Path
) -> None:
    adapter = _loaded(adapter_module, tmp_path, monkeypatch, FakeBackend(markdown=""))
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
        # The section 14 signature gets its own class, checked first.
        (RuntimeError("Tensor shape mismatch in concurrent VLM inference"), "TENSOR_SHAPE"),
        (RuntimeError("size mismatch for input_ids"), "TENSOR_SHAPE"),
        (RuntimeError("CUDA error: out of memory"), "CUDA_OOM"),
        (TimeoutError("timed out"), "INFERENCE_TIMEOUT"),
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


def test_warmup_runs_one_page(
    adapter_module: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, png: Path
) -> None:
    adapter = _loaded(adapter_module, tmp_path, monkeypatch, FakeBackend())
    receipt = adapter.warmup(png)
    assert receipt.schema_valid is True
    assert receipt.output_chars == len(MARKDOWN)


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
        "output_format": "markdown",
        "native_json": {
            "middle_json": MIDDLE_JSON,
            "model_json": MODEL_JSON,
            "content_list": None,
            "content_list_v2": CONTENT_LIST_V2,
        },
        "usage": {},
        "timings_ms": {"preprocess_ms": 0, "inference_ms": 1, "postprocess_ms": 0},
        "warnings": (),
    }
    defaults.update(overrides)
    return RawOutput(**defaults)


def test_canonical_heading(canonical_module: ModuleType) -> None:
    out = canonical_module.canonicalize(raw_output("# Balance Sheet\n\nBody."))
    assert out.markdown == "# Balance Sheet\n\nBody."
    assert out.lossy is False


def test_canonical_table_is_never_regenerated(canonical_module: ModuleType) -> None:
    out = canonical_module.canonicalize(raw_output(MARKDOWN))
    assert out.markdown == MARKDOWN


def test_canonical_formula(canonical_module: ModuleType) -> None:
    formula = "$$\\sum_{i=1}^{n} x_i$$"
    out = canonical_module.canonicalize(raw_output(formula))
    assert out.markdown == formula


def test_canonical_empty(canonical_module: ModuleType) -> None:
    out = canonical_module.canonicalize(
        raw_output("", native_json=None, warnings=("empty_output",))
    )
    assert out.markdown == ""
    assert out.elements is None
    assert "empty_raw_text" in out.conversion_notes
    assert "warning:empty_output" in out.conversion_notes
    assert out.lossy is False


def test_canonical_truncated_keeps_the_warning(canonical_module: ModuleType) -> None:
    out = canonical_module.canonicalize(
        raw_output("# Partial\n\nStops mid-sen", warnings=("output_truncated",))
    )
    assert "warning:output_truncated" in out.conversion_notes
    assert out.markdown.endswith("mid-sen")


def test_canonical_uses_content_list_v2_and_says_so(canonical_module: ModuleType) -> None:
    out = canonical_module.canonicalize(raw_output(MARKDOWN))
    assert out.elements is not None
    assert [element["type"] for element in out.elements] == ["title", "table"]
    assert out.elements[0]["bbox"] == [1, 2, 3, 4]
    assert "elements_from_content_list_v2" in out.conversion_notes


def test_canonical_falls_back_to_middle_json(canonical_module: ModuleType) -> None:
    out = canonical_module.canonicalize(
        raw_output(MARKDOWN, native_json={"middle_json": MIDDLE_JSON, "content_list_v2": []})
    )
    assert out.elements is not None
    assert out.elements[0]["source"] == "middle_json.para_blocks"


def test_canonical_never_invents_elements(canonical_module: ModuleType) -> None:
    out = canonical_module.canonicalize(
        raw_output(MARKDOWN, native_json={"content_list": None, "middle_json": None})
    )
    assert out.elements is None
    assert any(note.startswith("no_elements_available") for note in out.conversion_notes)


def test_canonical_normalizes_whitespace_without_losing_content(
    canonical_module: ModuleType,
) -> None:
    out = canonical_module.canonicalize(raw_output("\r\n# T   \r\n\n\n\n\nBody\n\n\n"))
    assert out.markdown == "# T\n\n\nBody"
    assert out.lossy is False


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


def test_bootstrap_carries_an_architecture_preflight_mineru_vlm() -> None:
    from incident_checks import assert_architecture_preflight

    assert_architecture_preflight("mineru_vlm")


def test_the_preflight_names_this_checkpoints_architecture_mineru_vlm() -> None:
    """A preflight that does not name what it expects would pass on any checkpoint."""
    from incident_checks import read_runtime_script

    text = read_runtime_script("mineru_vlm", "bootstrap.sh")
    assert 'EXPECTED_MODEL_TYPE = "qwen2_vl"' in text
    assert 'EXPECTED_ARCH = "Qwen2VLForConditionalGeneration"' in text
    assert "CONFIG_MAPPING_NAMES" in text
    # D59: the base image is vllm/vllm-openai, so get_vlm_engine("auto") always
    # resolves vlm-engine to vllm-engine on it (a real canary FATAL on pod
    # plz5obsz7ega3a confirmed it); "transformers" was wrong for this image.
    assert 'EXPECTED_ENGINE = "vllm-engine"' in text


def test_the_framework_floor_audit_is_recorded_mineru_vlm() -> None:
    """D: the audit result lives in provenance.json, and runtime.json's notes say so.

    It is not a top-level runtime.json field because runtime.schema.json is
    ``additionalProperties: false`` and belongs to another lane; loosening that
    schema to hold an audit record would be the wrong fix.
    """
    import json

    from incident_checks import load_runtime_json, runtime_dir

    provenance = json.loads(
        (runtime_dir("mineru_vlm") / "provenance.json").read_text(encoding="utf-8")
    )
    audit = provenance["framework_floor_audit"]
    for field in ("required", "image_ships", "action", "evidence"):
        assert audit[field], f"framework_floor_audit.{field} is empty"
    assert all(url.startswith("https://") for url in audit["evidence"])
    notes = load_runtime_json("mineru_vlm")["notes"]
    joined = " ".join(notes) if isinstance(notes, list) else notes
    assert "framework_floor_audit" in joined


def test_this_runtime_has_no_model_server_to_hold_mineru_vlm() -> None:
    """In-process inference: there is no separate server, so C is the preflight only."""
    from incident_checks import assert_no_model_server_to_hold

    assert_no_model_server_to_hold("mineru_vlm")
