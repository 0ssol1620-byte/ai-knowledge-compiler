"""Unit tests for the MonkeyOCRv2-B-Parsing runtime (lane C3).

No GPU, no network, no torch/vllm. The official ``core_runner`` pipeline is
replaced by a fake that returns markdown and a block list, so the tests cover the
adapter's bookkeeping, the DFlash refusal and the artifact-layout contract without
cloning the vendor repository.
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
from arena.worker.adapter_api import (
    AdapterConfig,
    AdapterError,
    ArenaModelAdapter,
    PageInput,
    RawOutput,
)

MODEL_KEY = "monkeyocrv2_b"
RUNTIME_DIR = Path(__file__).resolve().parents[2] / "runtimes" / MODEL_KEY
REGISTRY_DIR = Path(__file__).resolve().parents[2] / "prompt_registry"


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"c3_{MODEL_KEY}_{name}", RUNTIME_DIR / name)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


adapter_mod = _load("adapter.py")
canonical_mod = _load("canonical.py")


# ---------------------------------------------------------------- fixtures


class FakePipeline:
    def __init__(
        self,
        markdown: str = "# Heading\n\nBody.",
        content_json: Mapping[str, Any] | None = None,
    ) -> None:
        self.markdown = markdown
        self.content_json = content_json
        self.calls: list[tuple[Path, float]] = []

    def parse_page(self, image_path: Path, timeout_s: float) -> Any:
        self.calls.append((image_path, timeout_s))
        return adapter_mod.PipelinePageResult(
            markdown=self.markdown,
            content_json=self.content_json,
            usage={},
            stage_timings_ms={"pipeline_ms": 42},
        )

    def describe(self) -> Mapping[str, Any]:
        return {"pipeline": "fake", "dflash_enabled": False}


#: ``parsing/core_runner.py::ALL_PROMPT`` verbatim at runtime revision
#: d46699fb6a4c71d61588e4a71fce03bff4f1ba33 (fetched from raw.githubusercontent.com
#: on 2026-09-03). The tests stand a stub ``core_runner`` module up with exactly this
#: so the D34 prompt check runs against the real strings without cloning the repo.
OFFICIAL_ALL_PROMPT = {
    "Caption": "Please output the text content from the image.",
    "List-item": "Please output the text content from the image.",
    "Page-footer": "Please output the text content from the image.",
    "Page-header": "Please output the text content from the image.",
    "Section-header": "Please output the text content from the image.",
    "Text": "Please output the text content from the image.",
    "Title": "Please output the text content from the image.",
    "Formula": "Please write out the expression of the formula in the image using LaTeX format.",
    "Table": "Please extract the table from the image and represent it in OTSL format.",
    "LAYOUT": (
        "Please output the categories and coordinates of the document elements in reading order."
    ),
    "END2END": (
        "List the document elements in reading order, including their categories, "
        "coordinates, and the content of each element."
    ),
}
#: The rendering runtime.json documents for this revision.
OFFICIAL_PROMPT_SHA256 = "3384d4732fd91113b9f7989e488dba575f65225d745a30b797364e12df47dca4"


@pytest.fixture(autouse=True)
def stub_core_runner() -> Any:
    """Install a stub ``core_runner`` carrying the vendor's real ALL_PROMPT."""

    module = ModuleType("core_runner")
    module.ALL_PROMPT = dict(OFFICIAL_ALL_PROMPT)  # type: ignore[attr-defined]
    previous = sys.modules.get("core_runner")
    sys.modules["core_runner"] = module
    try:
        yield module
    finally:
        if previous is None:
            sys.modules.pop("core_runner", None)
        else:
            sys.modules["core_runner"] = previous


@pytest.fixture
def weights_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "weights"
    directory.mkdir()
    largest = directory / "model.safetensors"
    largest.write_bytes(b"0.7B of pretend weights")
    digest = "sha256:" + hashlib.sha256(largest.read_bytes()).hexdigest()
    (directory / "preprocessor2.pth").write_bytes(b"preprocessor")
    (directory / adapter_mod.WEIGHTS_SIDECAR_NAME).write_text(
        json.dumps(
            {
                "repo": "zenosai/MonkeyOCRv2-B-Parsing",
                "revision": "de7a993bd0f39a97b122dac767e82ae04935bce4",
                "largest_file": largest.name,
                "largest_file_sha256": digest,
                "files_manifest_sha256": "sha256:" + "4" * 64,
                "cache_hit": False,
            }
        ),
        encoding="utf-8",
    )
    return directory


def _config(weights_dir: Path, **overrides: Any) -> AdapterConfig:
    inference_config: dict[str, Any] = {
        "server_url": "http://127.0.0.1:8888",
        "served_model_name": "MonkeyOCRv2",
        "max_pixels": 1003520,
        "request_timeout": 300,
        "http_max_retries": 0,
        "end2end": False,
        "dflash_enabled": False,
        "hash_weights_on_load": False,
    }
    inference_config.update(overrides.pop("inference_config", {}))
    return AdapterConfig(
        model_key=MODEL_KEY,
        model_repo=overrides.pop("model_repo", "zenosai/MonkeyOCRv2-B-Parsing"),
        model_revision=overrides.pop(
            "model_revision", "de7a993bd0f39a97b122dac767e82ae04935bce4"
        ),
        weights_dir=weights_dir,
        prompt_id="monkeyocrv2_b_official_pipeline_prompts_v1",
        prompt_text=overrides.pop(
            "prompt_text", adapter_mod.render_prompt_mapping(OFFICIAL_ALL_PROMPT)
        ),
        inference_config=inference_config,
        inference_config_sha256="sha256:" + "5" * 64,
    )


def _page(tmp_path: Path) -> PageInput:
    image = tmp_path / "page.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n page")
    return PageInput(
        inference_job_id="c" * 64,
        sample_id="parsebench:docs/chart/example_p101#p0",
        case_key="parsebench-example-p101",
        benchmark="parsebench",
        image_path=image,
        source_sha256="sha256:" + hashlib.sha256(image.read_bytes()).hexdigest(),
        width=1654,
        height=2339,
        metadata={"page_index": 0, "media_type": "pdf"},
    )


# ------------------------------------------------------------- runtime.json


def test_runtime_json_carries_every_contract_field() -> None:
    spec = json.loads((RUNTIME_DIR / "runtime.json").read_text(encoding="utf-8"))
    required = {
        "model_key",
        "display_name",
        "model_repo",
        "model_revision",
        "official_runtime",
        "runtime_version",
        "base_image",
        "gpu_min_vram_gb",
        "gpu_pool_priority",
        "max_concurrency_per_worker",
        "shard_size_hint",
        "per_page_timeout_seconds",
        "prompt_id",
        "inference_config",
        "weights_strategy",
        "runtime_mode_allowed",
        "official_source_urls",
        "license",
        "notes",
        "weights",
    }
    assert required <= set(spec)
    assert spec["model_revision"] == "de7a993bd0f39a97b122dac767e82ae04935bce4"
    assert "@sha256:" in spec["base_image"]
    assert spec["license"]["status"] == "approved"


def test_runtime_json_records_the_v2_runtime_repository_correction() -> None:
    """candidate-registry.yaml still names the v1 repo; that would not serve v2."""
    spec = json.loads((RUNTIME_DIR / "runtime.json").read_text(encoding="utf-8"))
    config = spec["inference_config"]
    assert config["runtime_repository"] == "https://github.com/Yuliang-Liu/MonkeyOCRv2"
    assert len(config["runtime_revision"]) == 40
    notes = " ".join(spec["notes"])
    assert "candidate-registry.yaml" in notes
    assert "v1 repository" in notes


def test_runtime_json_records_the_head_revision_divergence() -> None:
    notes = " ".join(
        json.loads((RUNTIME_DIR / "runtime.json").read_text(encoding="utf-8"))["notes"]
    )
    assert "2419139b7bcd3fda2689b2a83167172afba91c8b" in notes
    assert "byte-identical" in notes


def test_runtime_json_keeps_dflash_off_and_says_why() -> None:
    spec = json.loads((RUNTIME_DIR / "runtime.json").read_text(encoding="utf-8"))
    assert spec["inference_config"]["dflash_enabled"] is False
    notes = " ".join(spec["notes"])
    assert "DFLASH IS DELIBERATELY OFF" in notes
    assert "0.25.1" in notes


def test_runtime_json_states_the_gradio_omission() -> None:
    notes = " ".join(
        json.loads((RUNTIME_DIR / "runtime.json").read_text(encoding="utf-8"))["notes"]
    )
    assert "gradio" in notes and "pypdfium2" in notes


# ---------------------------------------------------------- import hygiene


def _module_level_imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_adapter_imports_without_a_gpu_stack() -> None:
    imported = _module_level_imports(RUNTIME_DIR / "adapter.py")
    assert imported.isdisjoint({"torch", "vllm", "transformers", "PIL", "core_runner", "numpy"})


def test_adapter_satisfies_the_frozen_protocol() -> None:
    assert isinstance(adapter_mod.MonkeyOcrV2BAdapter(), ArenaModelAdapter)


# ------------------------------------------------------------------- load


def test_load_happy_path(weights_dir: Path) -> None:
    adapter = adapter_mod.MonkeyOcrV2BAdapter(FakePipeline())
    receipt = adapter.load(_config(weights_dir))
    assert receipt.model_revision == "de7a993bd0f39a97b122dac767e82ae04935bce4"
    assert receipt.weights_sha256_manifest == "sha256:" + "4" * 64


def test_load_refuses_dflash(weights_dir: Path) -> None:
    """DFlash is a different checkpoint on a different stack, not a speed flag."""
    adapter = adapter_mod.MonkeyOcrV2BAdapter(FakePipeline())
    with pytest.raises(AdapterError) as caught:
        adapter.load(_config(weights_dir, inference_config={"dflash_enabled": True}))
    assert caught.value.error_class == "MODEL_LOAD"
    assert "DFlash" in str(caught.value)


def test_load_rejects_a_revision_mismatch(weights_dir: Path) -> None:
    adapter = adapter_mod.MonkeyOcrV2BAdapter(FakePipeline())
    with pytest.raises(AdapterError) as caught:
        adapter.load(_config(weights_dir, model_revision="9" * 40))
    assert caught.value.error_class == "MODEL_LOAD"


def test_load_rejects_a_checksum_mismatch(weights_dir: Path) -> None:
    (weights_dir / "model.safetensors").write_bytes(b"swapped weights")
    adapter = adapter_mod.MonkeyOcrV2BAdapter(FakePipeline())
    with pytest.raises(AdapterError) as caught:
        adapter.load(_config(weights_dir))
    assert caught.value.error_class == "CHECKSUM"


def test_load_deep_hash_covers_the_preprocessors_too(weights_dir: Path) -> None:
    adapter = adapter_mod.MonkeyOcrV2BAdapter(FakePipeline())
    receipt = adapter.load(
        _config(weights_dir, inference_config={"hash_weights_on_load": True})
    )
    assert receipt.weights_sha256_manifest.startswith("sha256:")
    assert receipt.weights_sha256_manifest != "sha256:" + "4" * 64


def test_official_pipeline_reports_a_missing_core_runner() -> None:
    # The autouse stub makes core_runner importable for the D34 prompt check; this
    # test is about the image that never put parsing/ on PYTHONPATH at all.
    sys.modules.pop("core_runner", None)
    pipeline = adapter_mod.OfficialParsingPipeline(Path("."), {})
    with pytest.raises(AdapterError) as caught:
        pipeline.parse_page(Path("nope.png"), 10.0)
    assert caught.value.error_class == "DEPENDENCY"


# ------------------------------------------------------------------ infer


def test_infer_returns_the_pipeline_markdown_verbatim(
    weights_dir: Path, tmp_path: Path
) -> None:
    pipeline = FakePipeline("# Title\n\n<table><tr><td>1</td></tr></table>")
    adapter = adapter_mod.MonkeyOcrV2BAdapter(pipeline)
    adapter.load(_config(weights_dir))
    raw = adapter.infer(_page(tmp_path))
    assert raw.raw_text == "# Title\n\n<table><tr><td>1</td></tr></table>"
    assert raw.output_format == "markdown"
    assert raw.timings_ms["inference_ms"] == 42
    assert pipeline.calls[0][1] == 300.0
    assert raw.semantic_error_class is None


def test_infer_flags_a_missing_json_artifact(weights_dir: Path, tmp_path: Path) -> None:
    adapter = adapter_mod.MonkeyOcrV2BAdapter(FakePipeline(content_json=None))
    adapter.load(_config(weights_dir))
    raw = adapter.infer(_page(tmp_path))
    assert any("no jsons/ artifact" in w for w in raw.warnings)


def test_infer_flags_an_empty_page(weights_dir: Path, tmp_path: Path) -> None:
    adapter = adapter_mod.MonkeyOcrV2BAdapter(FakePipeline(markdown="   \n"))
    adapter.load(_config(weights_dir))
    raw = adapter.infer(_page(tmp_path))
    assert f"{adapter_mod.SEMANTIC_ERROR_PREFIX}OUTPUT_EMPTY" in raw.warnings
    assert raw.semantic_error_class == "OUTPUT_EMPTY"


def test_infer_flags_degenerate_repetition(weights_dir: Path, tmp_path: Path) -> None:
    adapter = adapter_mod.MonkeyOcrV2BAdapter(
        FakePipeline(markdown="\n".join(["a repeated long line"] * 40))
    )
    adapter.load(_config(weights_dir))
    raw = adapter.infer(_page(tmp_path))
    assert f"{adapter_mod.SEMANTIC_ERROR_PREFIX}OUTPUT_REPETITION" in raw.warnings
    assert raw.semantic_error_class == "OUTPUT_REPETITION"


def test_infer_rejects_a_missing_page_file(weights_dir: Path, tmp_path: Path) -> None:
    adapter = adapter_mod.MonkeyOcrV2BAdapter(FakePipeline())
    adapter.load(_config(weights_dir))
    page = _page(tmp_path)
    page.image_path.unlink()
    with pytest.raises(AdapterError) as caught:
        adapter.infer(page)
    assert caught.value.error_class == "INPUT_DECODE"


def test_infer_before_load_is_refused(tmp_path: Path) -> None:
    adapter = adapter_mod.MonkeyOcrV2BAdapter(FakePipeline())
    with pytest.raises(AdapterError) as caught:
        adapter.infer(_page(tmp_path))
    assert caught.value.error_class == "MODEL_LOAD"


# -------------------------------------------------- artifact layout contract


def test_read_single_requires_exactly_one_artifact(tmp_path: Path) -> None:
    directory = tmp_path / "markdowns"
    directory.mkdir()
    with pytest.raises(AdapterError) as empty:
        adapter_mod._read_single(directory, ".md")
    assert empty.value.error_class == "POSTPROCESS"

    (directory / "a.md").write_text("A", encoding="utf-8")
    assert adapter_mod._read_single(directory, ".md") == "A"

    (directory / "b.md").write_text("B", encoding="utf-8")
    with pytest.raises(AdapterError) as many:
        adapter_mod._read_single(directory, ".md")
    assert many.value.error_class == "POSTPROCESS"


def test_read_single_reports_a_missing_directory(tmp_path: Path) -> None:
    with pytest.raises(AdapterError) as caught:
        adapter_mod._read_single(tmp_path / "markdowns", ".md")
    assert caught.value.error_class == "POSTPROCESS"


# ------------------------------------------------------------- canonical


def _raw(text: str, native: Mapping[str, Any] | None = None, **kwargs: Any) -> RawOutput:
    return RawOutput(
        raw_text=text,
        output_format="markdown",
        native_json=native,
        usage={},
        timings_ms={"preprocess_ms": 0, "inference_ms": 0, "postprocess_ms": 0},
        warnings=tuple(kwargs.pop("warnings", ())),
    )


def test_canonicalize_passes_markdown_through_and_lifts_blocks() -> None:
    native = {
        "blocks": [
            {"label": "Title", "bbox": [0, 0, 1, 1], "content": "Quarterly Results"},
            {"label": "Table", "bbox": [0, 2, 1, 3], "content": "<table></table>"},
        ]
    }
    result = canonical_mod.canonicalize(
        _raw("# Quarterly Results\n\n<table></table>\n\n$$E = mc^2$$", native)
    )
    assert result.markdown.startswith("# Quarterly Results")
    assert "$$E = mc^2$$" in result.markdown
    assert result.elements is not None
    assert [element["label"] for element in result.elements] == ["Title", "Table"]
    assert result.lossy is False


def test_canonicalize_flags_untranslated_otsl() -> None:
    result = canonical_mod.canonicalize(_raw("<fcel>1<fcel>2<nl>"))
    assert result.lossy is True
    assert any("OTSL" in note for note in result.conversion_notes)


def test_canonicalize_records_image_references_without_deleting_them() -> None:
    result = canonical_mod.canonicalize(_raw("Text\n\n![figure](images/fig_1.jpg)"))
    assert "![figure](images/fig_1.jpg)" in result.markdown
    assert any("image reference" in note for note in result.conversion_notes)


def test_canonicalize_empty_output_is_flagged_lossy() -> None:
    result = canonical_mod.canonicalize(
        _raw("", warnings=("arena.semantic_error_class=OUTPUT_EMPTY",))
    )
    assert result.markdown == ""
    assert result.lossy is True


def test_canonicalize_truncated_output_is_flagged_lossy() -> None:
    result = canonical_mod.canonicalize(
        _raw("half a sen", warnings=("arena.semantic_error_class=OUTPUT_TRUNCATED",))
    )
    assert result.lossy is True
    assert result.markdown == "half a sen"


def test_canonicalize_without_a_block_list_says_so() -> None:
    result = canonical_mod.canonicalize(_raw("# Heading", None))
    assert result.elements is None
    assert any("no block list" in note for note in result.conversion_notes)


# ------------------------------------------------------------ D34 prompt kind


def test_runtime_json_declares_the_kind_the_adapter_implements() -> None:
    spec = json.loads((RUNTIME_DIR / "runtime.json").read_text(encoding="utf-8"))
    assert spec["prompt_kind"] == "toolkit"
    assert spec["prompt_kind"] == adapter_mod.PROMPT_KIND


def test_render_prompt_mapping_matches_the_documented_hash() -> None:
    """The bytes lane R must write for prompt_registry/<prompt_id>.txt."""
    rendered = adapter_mod.render_prompt_mapping(OFFICIAL_ALL_PROMPT)
    assert json.loads(rendered) == OFFICIAL_ALL_PROMPT
    assert not rendered.endswith("\n")
    assert hashlib.sha256(rendered.encode("utf-8")).hexdigest() == OFFICIAL_PROMPT_SHA256
    spec = json.loads((RUNTIME_DIR / "runtime.json").read_text(encoding="utf-8"))
    assert any(OFFICIAL_PROMPT_SHA256 in str(note) for note in spec["notes"])
    # And it is byte-identical to the file lane R already wrote.
    registry = REGISTRY_DIR / f"{spec['prompt_id']}.txt"
    assert registry.read_bytes() == rendered.encode("utf-8")
    recorded = json.loads((REGISTRY_DIR / "sha256.json").read_text(encoding="utf-8"))
    assert recorded[spec["prompt_id"]] == f"sha256:{OFFICIAL_PROMPT_SHA256}"


def test_render_prompt_mapping_is_insensitive_to_key_order_only() -> None:
    reordered = dict(reversed(list(OFFICIAL_ALL_PROMPT.items())))
    assert adapter_mod.render_prompt_mapping(reordered) == adapter_mod.render_prompt_mapping(
        OFFICIAL_ALL_PROMPT
    )
    edited = dict(OFFICIAL_ALL_PROMPT, Table="Please extract the table as HTML.")
    assert adapter_mod.render_prompt_mapping(edited) != adapter_mod.render_prompt_mapping(
        OFFICIAL_ALL_PROMPT
    )


def test_load_reads_the_prompts_out_of_the_installed_toolkit(weights_dir: Path) -> None:
    adapter = adapter_mod.MonkeyOcrV2BAdapter(FakePipeline())
    receipt = adapter.load(_config(weights_dir))
    provenance = receipt.runtime_provenance
    assert provenance["prompt_kind"] == "toolkit"
    assert provenance["prompt_sha256"] == f"sha256:{OFFICIAL_PROMPT_SHA256}"
    assert provenance["prompt_source"]["source"] == "core_runner.ALL_PROMPT"


def test_load_fails_closed_when_the_toolkit_prompts_drift(
    weights_dir: Path, stub_core_runner: Any
) -> None:
    stub_core_runner.ALL_PROMPT["Table"] = "Please extract the table as HTML."
    adapter = adapter_mod.MonkeyOcrV2BAdapter(FakePipeline())
    with pytest.raises(AdapterError) as caught:
        adapter.load(_config(weights_dir))
    assert caught.value.error_class == "MODEL_LOAD"
    assert "core_runner.ALL_PROMPT" in str(caught.value)


def test_load_fails_closed_when_nothing_can_be_verified_against(weights_dir: Path) -> None:
    adapter = adapter_mod.MonkeyOcrV2BAdapter(FakePipeline())
    with pytest.raises(AdapterError) as caught:
        adapter.load(_config(weights_dir, prompt_text=""))
    assert caught.value.error_class == "MODEL_LOAD"
    assert "neither prompt_sha256 nor prompt_text" in str(caught.value)


def test_load_fails_closed_when_the_toolkit_is_not_importable(weights_dir: Path) -> None:
    sys.modules.pop("core_runner", None)
    adapter = adapter_mod.MonkeyOcrV2BAdapter(FakePipeline())
    with pytest.raises(AdapterError) as caught:
        adapter.load(_config(weights_dir))
    assert caught.value.error_class == "DEPENDENCY"


# --------------------------------------------------- source-resolution receipt


def test_receipt_agrees_with_runtime_json() -> None:
    """The receipt records what the official APIs returned; runtime.json must match."""
    spec = json.loads((RUNTIME_DIR / "runtime.json").read_text(encoding="utf-8"))
    receipt = json.loads(
        (RUNTIME_DIR / "source-resolution-receipt.json").read_text(encoding="utf-8")
    )
    checkpoint = receipt["checkpoint"]
    assert receipt["model_key"] == MODEL_KEY
    assert checkpoint["repo"] == spec["model_repo"]
    assert checkpoint["pinned_revision"] == spec["model_revision"]
    assert checkpoint["largest_file"]["name"] == spec["weights"]["largest_file"]
    assert checkpoint["largest_file"]["sha256"] == spec["weights"]["largest_file_sha256"]
    assert receipt["base_image"]["digest"] in spec["base_image"]
    assert receipt["not_verified"], "a receipt must say what it did not verify"


# =========================================================================
# 2026-09-03 GLM-OCR canary incident: fail fast and visibly, before a GPU
#
# The GLM-OCR canary reached the model-server start and died on a model_type its
# image's Transformers did not know; RunPod restarted the exited start command and
# the pod crash-looped while billing. These checks are string-level facts about the
# shipped scripts - no GPU, no network, no container runtime.
# =========================================================================


def test_bootstrap_carries_an_architecture_preflight_monkeyocrv2_b() -> None:
    from incident_checks import assert_architecture_preflight

    assert_architecture_preflight("monkeyocrv2_b")


def test_the_preflight_names_this_checkpoints_architecture_monkeyocrv2_b() -> None:
    """A preflight that does not name what it expects would pass on any checkpoint."""
    from incident_checks import read_runtime_script

    text = read_runtime_script("monkeyocrv2_b", "bootstrap.sh")
    assert 'EXPECTED_MODEL_TYPE = "monkeyocrv2"' in text
    assert 'EXPECTED_ARCH = "MonkeyOCRv2ForCausalLM"' in text
    # vllm v0.11.2's own registry does NOT carry this architecture: the vendor
    # module serve.py imports is what registers it, so the preflight imports it too
    assert 'VENDOR_MODULE = "modeling.modeling_monkeyocrv2_vllm_011"' in text
    assert "ModelRegistry.get_supported_archs()" in text


def test_the_framework_floor_audit_is_recorded_monkeyocrv2_b() -> None:
    """D: the audit result lives in provenance.json, and runtime.json's notes say so.

    It is not a top-level runtime.json field because runtime.schema.json is
    ``additionalProperties: false`` and belongs to another lane; loosening that
    schema to hold an audit record would be the wrong fix.
    """
    import json

    from incident_checks import load_runtime_json, runtime_dir

    provenance = json.loads(
        (runtime_dir("monkeyocrv2_b") / "provenance.json").read_text(encoding="utf-8")
    )
    audit = provenance["framework_floor_audit"]
    for field in ("required", "image_ships", "action", "evidence"):
        assert audit[field], f"framework_floor_audit.{field} is empty"
    assert all(url.startswith("https://") for url in audit["evidence"])
    notes = load_runtime_json("monkeyocrv2_b")["notes"]
    joined = " ".join(notes) if isinstance(notes, list) else notes
    assert "framework_floor_audit" in joined


def test_entrypoint_makes_a_model_server_failure_sticky_monkeyocrv2_b() -> None:
    """Exiting is what RunPod restarts, so a start failure holds the container."""
    from incident_checks import assert_sticky_model_server_failure

    assert_sticky_model_server_failure("monkeyocrv2_b")
