"""Unit tests for the GLM-OCR runtime (lane C3).

No GPU, no network, no torch/vllm/glmocr. The official SDK pipeline is replaced by
a fake, so the tests cover the MaaS refusal, the second (layout) model's pin and
hash, and the SDK config the adapter would hand to ``glmocr.GlmOcr``.
"""

from __future__ import annotations

import ast
import copy
import hashlib
import importlib.metadata
import importlib.util
import json
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
import yaml
from arena.worker.adapter_api import (
    AdapterConfig,
    AdapterError,
    ArenaModelAdapter,
    PageInput,
    RawOutput,
)

MODEL_KEY = "glm_ocr"
RUNTIME_DIR = Path(__file__).resolve().parents[2] / "runtimes" / MODEL_KEY


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
        json_result: Mapping[str, Any] | None = None,
    ) -> None:
        self.markdown = markdown
        self.json_result = json_result
        self.calls: list[tuple[Path, float]] = []

    def parse_page(self, image_path: Path, timeout_s: float) -> Any:
        self.calls.append((image_path, timeout_s))
        return adapter_mod.SdkPageResult(
            markdown=self.markdown,
            json_result=self.json_result,
            usage={},
            stage_timings_ms={"pipeline_ms": 17},
        )

    def describe(self) -> Mapping[str, Any]:
        return {"pipeline": "fake", "maas_enabled": False}


@pytest.fixture(autouse=True)
def _no_inherited_layout_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """``resolve_layout_model_dir`` reads the environment; the tests own it."""
    monkeypatch.delenv(adapter_mod.LAYOUT_DIR_ENV, raising=False)


@pytest.fixture
def layout_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "layout"
    directory.mkdir()
    (directory / "model.safetensors").write_bytes(b"pp-doclayout-v3")
    return directory


@pytest.fixture
def weights_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "weights"
    directory.mkdir()
    largest = directory / "model.safetensors"
    largest.write_bytes(b"glm ocr weights")
    digest = "sha256:" + hashlib.sha256(largest.read_bytes()).hexdigest()
    (directory / adapter_mod.WEIGHTS_SIDECAR_NAME).write_text(
        json.dumps(
            {
                "repo": "zai-org/GLM-OCR",
                "revision": "ca5d8b3e287e52589e37c28385d9655ee4372f9d",
                "largest_file": largest.name,
                "largest_file_sha256": digest,
                "files_manifest_sha256": "sha256:" + "6" * 64,
                "cache_hit": False,
            }
        ),
        encoding="utf-8",
    )
    return directory


def _layout_digest(layout_dir: Path) -> str:
    data = (layout_dir / "model.safetensors").read_bytes()
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _config(weights_dir: Path, layout_dir: Path, **overrides: Any) -> AdapterConfig:
    inference_config: dict[str, Any] = {
        "api_host": "127.0.0.1",
        "api_port": 8080,
        "served_model_name": "glm-ocr",
        "layout_model_dir": str(layout_dir),
        "layout_model_repo": "PaddlePaddle/PP-DocLayoutV3_safetensors",
        "layout_model_revision": "97d101e6db2642e162a1d05392d1b0231c91033e",
        "layout_model_largest_file": "model.safetensors",
        "layout_model_largest_file_sha256": _layout_digest(layout_dir),
        "max_tokens": 8192,
        "temperature": 0.0,
        "top_p": 0.00001,
        "top_k": 1,
        "repetition_penalty": 1.1,
        "request_timeout": 120,
        "maas_enabled": False,
        "hash_weights_on_load": False,
    }
    inference_config.update(overrides.pop("inference_config", {}))
    return AdapterConfig(
        model_key=MODEL_KEY,
        model_repo=overrides.pop("model_repo", "zai-org/GLM-OCR"),
        model_revision=overrides.pop(
            "model_revision", "ca5d8b3e287e52589e37c28385d9655ee4372f9d"
        ),
        weights_dir=weights_dir,
        prompt_id="glm_ocr_official_sdk_task_prompts_v1",
        prompt_text=overrides.pop(
            "prompt_text", adapter_mod.build_official_prompt_text()
        ),
        inference_config=inference_config,
        inference_config_sha256="sha256:" + "7" * 64,
    )


def _page(tmp_path: Path) -> PageInput:
    image = tmp_path / "page.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n page")
    return PageInput(
        inference_job_id="d" * 64,
        sample_id="omnidoc:images/report_page_007",
        case_key="omnidocbench-report-007",
        benchmark="omnidoc",
        image_path=image,
        source_sha256="sha256:" + hashlib.sha256(image.read_bytes()).hexdigest(),
        width=1654,
        height=2339,
        metadata={"page_index": 0, "media_type": "image"},
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
    assert spec["model_revision"] == "ca5d8b3e287e52589e37c28385d9655ee4372f9d"
    assert "@sha256:" in spec["base_image"]
    assert spec["license"]["id"] == "MIT"
    assert spec["license"]["status"] == "approved"


def test_runtime_json_pins_the_second_model_the_pipeline_needs() -> None:
    config = json.loads((RUNTIME_DIR / "runtime.json").read_text(encoding="utf-8"))[
        "inference_config"
    ]
    assert config["layout_model_repo"] == "PaddlePaddle/PP-DocLayoutV3_safetensors"
    assert len(config["layout_model_revision"]) == 40
    assert config["layout_model_largest_file_sha256"].startswith("sha256:")
    assert len(config["layout_model_largest_file_sha256"]) == len("sha256:") + 64


def test_runtime_json_names_all_three_licence_surfaces() -> None:
    spec = json.loads((RUNTIME_DIR / "runtime.json").read_text(encoding="utf-8"))
    notes = " ".join(spec["notes"])
    assert "THREE LICENCE SURFACES" in notes
    assert "MIT" in notes and "Apache-2.0" in notes
    urls = " ".join(spec["official_source_urls"])
    assert "PP-DocLayoutV3_safetensors" in urls


def test_runtime_json_records_the_parameter_count_discrepancy() -> None:
    notes = " ".join(
        json.loads((RUNTIME_DIR / "runtime.json").read_text(encoding="utf-8"))["notes"]
    )
    assert "2,650,579,464" in notes
    assert "0.9B" in notes


def test_runtime_json_disables_maas() -> None:
    config = json.loads((RUNTIME_DIR / "runtime.json").read_text(encoding="utf-8"))[
        "inference_config"
    ]
    assert config["maas_enabled"] is False
    assert config["retry_max_attempts"] == 0


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
    assert imported.isdisjoint({"torch", "vllm", "transformers", "glmocr", "cv2", "numpy"})


def test_adapter_satisfies_the_frozen_protocol() -> None:
    assert isinstance(adapter_mod.GlmOcrAdapter(), ArenaModelAdapter)


# ------------------------------------------------------------------- load


def test_load_happy_path(weights_dir: Path, layout_dir: Path) -> None:
    adapter = adapter_mod.GlmOcrAdapter(FakePipeline())
    receipt = adapter.load(_config(weights_dir, layout_dir))
    assert receipt.model_revision == "ca5d8b3e287e52589e37c28385d9655ee4372f9d"
    layout = receipt.runtime_provenance["layout_model"]
    assert layout["revision"] == "97d101e6db2642e162a1d05392d1b0231c91033e"
    assert "Apache-2.0" in layout["license"]


def test_load_refuses_maas_mode(weights_dir: Path, layout_dir: Path) -> None:
    """MaaS forwards every page to a hosted API; no adapter decides that."""
    adapter = adapter_mod.GlmOcrAdapter(FakePipeline())
    with pytest.raises(AdapterError) as caught:
        adapter.load(_config(weights_dir, layout_dir, inference_config={"maas_enabled": True}))
    assert caught.value.error_class == "MODEL_LOAD"
    assert "hosted" in str(caught.value)


def test_load_rejects_a_tampered_layout_model(weights_dir: Path, layout_dir: Path) -> None:
    config = _config(weights_dir, layout_dir)
    (layout_dir / "model.safetensors").write_bytes(b"a different layout model")
    adapter = adapter_mod.GlmOcrAdapter(FakePipeline())
    with pytest.raises(AdapterError) as caught:
        adapter.load(config)
    assert caught.value.error_class == "CHECKSUM"


def test_load_rejects_a_missing_layout_model(weights_dir: Path, layout_dir: Path) -> None:
    config = _config(weights_dir, layout_dir)
    (layout_dir / "model.safetensors").unlink()
    adapter = adapter_mod.GlmOcrAdapter(FakePipeline())
    with pytest.raises(AdapterError) as caught:
        adapter.load(config)
    assert caught.value.error_class == "MODEL_LOAD"


def test_load_rejects_an_unpinned_layout_model(weights_dir: Path, layout_dir: Path) -> None:
    adapter = adapter_mod.GlmOcrAdapter(FakePipeline())
    with pytest.raises(AdapterError) as caught:
        adapter.load(
            _config(
                weights_dir, layout_dir, inference_config={"layout_model_largest_file_sha256": None}
            )
        )
    assert caught.value.error_class == "MODEL_LOAD"


def test_load_rejects_a_revision_mismatch(weights_dir: Path, layout_dir: Path) -> None:
    adapter = adapter_mod.GlmOcrAdapter(FakePipeline())
    with pytest.raises(AdapterError) as caught:
        adapter.load(_config(weights_dir, layout_dir, model_revision="e" * 40))
    assert caught.value.error_class == "MODEL_LOAD"


def test_load_rejects_a_checksum_mismatch(weights_dir: Path, layout_dir: Path) -> None:
    config = _config(weights_dir, layout_dir)
    (weights_dir / "model.safetensors").write_bytes(b"tampered")
    adapter = adapter_mod.GlmOcrAdapter(FakePipeline())
    with pytest.raises(AdapterError) as caught:
        adapter.load(config)
    assert caught.value.error_class == "CHECKSUM"


# -------------------------------------------------------------- sdk config


def test_sdk_config_uses_the_official_defaults_and_two_deviations() -> None:
    pipeline = adapter_mod.OfficialSdkPipeline(
        {
            "api_host": "127.0.0.1",
            "api_port": 8080,
            "served_model_name": "glm-ocr",
            "layout_model_dir": "/opt/layout",
            "maas_enabled": False,
        }
    )
    config = pipeline.sdk_config()["pipeline"]
    assert config["maas"]["enabled"] is False
    assert config["ocr_api"]["retry_max_attempts"] == 0
    assert config["page_loader"]["max_tokens"] == 8192
    assert config["page_loader"]["temperature"] == 0.0
    assert config["page_loader"]["top_p"] == 0.00001
    assert config["page_loader"]["top_k"] == 1
    assert config["page_loader"]["repetition_penalty"] == 1.1
    assert config["page_loader"]["task_prompt_mapping"] == adapter_mod.OFFICIAL_TASK_PROMPTS
    assert config["layout"]["model_dir"] == "/opt/layout"


def test_official_task_prompts_are_the_cards_three() -> None:
    assert adapter_mod.OFFICIAL_TASK_PROMPTS == {
        "text": "Text Recognition:",
        "formula": "Formula Recognition:",
        "table": "Table Recognition:",
    }


def test_official_pipeline_reports_a_missing_sdk() -> None:
    pipeline = adapter_mod.OfficialSdkPipeline({"layout_model_dir": "/opt/layout"})
    with pytest.raises(AdapterError) as caught:
        pipeline.parse_page(Path("nope.png"), 10.0)
    assert caught.value.error_class == "DEPENDENCY"


# ------------------------------------------------------------------ infer


def test_infer_returns_sdk_markdown_verbatim(
    weights_dir: Path, layout_dir: Path, tmp_path: Path
) -> None:
    pipeline = FakePipeline("# Report\n\n$$\\alpha$$", {"regions": [{"label": "text"}]})
    adapter = adapter_mod.GlmOcrAdapter(pipeline)
    adapter.load(_config(weights_dir, layout_dir))
    raw = adapter.infer(_page(tmp_path))
    assert raw.raw_text == "# Report\n\n$$\\alpha$$"
    assert raw.native_json == {"regions": [{"label": "text"}]}
    assert raw.timings_ms["inference_ms"] == 17
    assert pipeline.calls[0][1] == 120.0
    assert raw.semantic_error_class is None


def test_infer_flags_a_missing_json_result(
    weights_dir: Path, layout_dir: Path, tmp_path: Path
) -> None:
    adapter = adapter_mod.GlmOcrAdapter(FakePipeline(json_result=None))
    adapter.load(_config(weights_dir, layout_dir))
    raw = adapter.infer(_page(tmp_path))
    assert any("no json_result" in w for w in raw.warnings)


def test_infer_flags_an_empty_page(weights_dir: Path, layout_dir: Path, tmp_path: Path) -> None:
    adapter = adapter_mod.GlmOcrAdapter(FakePipeline(markdown=""))
    adapter.load(_config(weights_dir, layout_dir))
    raw = adapter.infer(_page(tmp_path))
    assert f"{adapter_mod.SEMANTIC_ERROR_PREFIX}OUTPUT_EMPTY" in raw.warnings
    assert raw.semantic_error_class == "OUTPUT_EMPTY"


def test_infer_rejects_a_missing_page_file(
    weights_dir: Path, layout_dir: Path, tmp_path: Path
) -> None:
    adapter = adapter_mod.GlmOcrAdapter(FakePipeline())
    adapter.load(_config(weights_dir, layout_dir))
    page = _page(tmp_path)
    page.image_path.unlink()
    with pytest.raises(AdapterError) as caught:
        adapter.infer(page)
    assert caught.value.error_class == "INPUT_DECODE"


def test_infer_before_load_is_refused(tmp_path: Path) -> None:
    adapter = adapter_mod.GlmOcrAdapter(FakePipeline())
    with pytest.raises(AdapterError) as caught:
        adapter.infer(_page(tmp_path))
    assert caught.value.error_class == "MODEL_LOAD"


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


def test_canonicalize_passes_markdown_through_and_lifts_regions() -> None:
    native = {
        "regions": [
            {"label": "doc_title", "bbox": [0, 0, 1, 1], "text": "Annual Report"},
            {"label": "table", "bbox": [0, 2, 1, 3], "text": "<table></table>"},
            {"label": "display_formula", "bbox": [0, 4, 1, 5], "text": "E = mc^2"},
        ]
    }
    result = canonical_mod.canonicalize(
        _raw("# Annual Report\n\n<table></table>\n\n$$E = mc^2$$", native)
    )
    assert result.markdown.startswith("# Annual Report")
    assert "<table></table>" in result.markdown
    assert "$$E = mc^2$$" in result.markdown
    assert result.elements is not None
    assert len(result.elements) == 3
    assert result.lossy is False


def test_canonicalize_always_records_the_sdk_post_processing() -> None:
    result = canonical_mod.canonicalize(_raw("Body"))
    assert any("post-processing" in note for note in result.conversion_notes)


def test_canonicalize_reports_unknown_labels_without_remapping() -> None:
    result = canonical_mod.canonicalize(_raw("Body", {"regions": [{"label": "marginalia"}]}))
    assert result.elements is not None
    assert result.elements[0]["label"] == "marginalia"
    assert any("kept verbatim" in note for note in result.conversion_notes)


def test_canonicalize_records_image_references() -> None:
    result = canonical_mod.canonicalize(_raw("Text\n\n![chart](images/chart_0.png)"))
    assert "![chart](images/chart_0.png)" in result.markdown
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


def test_canonicalize_without_a_region_list_says_so() -> None:
    result = canonical_mod.canonicalize(_raw("# Heading", None))
    assert result.elements is None
    assert any("no region list" in note for note in result.conversion_notes)


# ------------------------------------------------------------ D34 prompt kind

GLM_PROMPT_SHA256 = "3d62ac2e6e72a4064fdbbc5d8b045111133f663fb774e9eb0483933f36cf5e67"
REGISTRY_DIR = Path(__file__).resolve().parents[2] / "prompt_registry"


def test_runtime_json_declares_the_kind_the_adapter_implements() -> None:
    spec = json.loads((RUNTIME_DIR / "runtime.json").read_text(encoding="utf-8"))
    assert spec["prompt_kind"] == "toolkit"
    assert spec["prompt_kind"] == adapter_mod.PROMPT_KIND


def test_build_official_prompt_text_matches_the_documented_hash() -> None:
    """The bytes lane R must write for prompt_registry/<prompt_id>.txt."""
    built = adapter_mod.build_official_prompt_text()
    assert built == (
        '{"formula":"Formula Recognition:","table":"Table Recognition:",'
        '"text":"Text Recognition:"}'
    )
    assert hashlib.sha256(built.encode("utf-8")).hexdigest() == GLM_PROMPT_SHA256
    spec = json.loads((RUNTIME_DIR / "runtime.json").read_text(encoding="utf-8"))
    assert any(GLM_PROMPT_SHA256 in str(note) for note in spec["notes"])
    # And it is byte-identical to the file lane R already wrote.
    registry = REGISTRY_DIR / f"{spec['prompt_id']}.txt"
    assert registry.read_bytes() == built.encode("utf-8")
    recorded = json.loads((REGISTRY_DIR / "sha256.json").read_text(encoding="utf-8"))
    assert recorded[spec["prompt_id"]] == f"sha256:{GLM_PROMPT_SHA256}"


def test_load_records_the_verified_prompt_hash(weights_dir: Path, layout_dir: Path) -> None:
    adapter = adapter_mod.GlmOcrAdapter(FakePipeline())
    receipt = adapter.load(_config(weights_dir, layout_dir))
    provenance = receipt.runtime_provenance
    assert provenance["prompt_kind"] == "toolkit"
    assert provenance["prompt_sha256"] == f"sha256:{GLM_PROMPT_SHA256}"
    assert provenance["task_prompt_mapping"] == dict(adapter_mod.OFFICIAL_TASK_PROMPTS)


def test_load_fails_closed_when_the_registry_prompt_differs(
    weights_dir: Path, layout_dir: Path
) -> None:
    adapter = adapter_mod.GlmOcrAdapter(FakePipeline())
    with pytest.raises(AdapterError) as caught:
        adapter.load(_config(weights_dir, layout_dir, prompt_text="Text Recognition:"))
    assert caught.value.error_class == "MODEL_LOAD"
    assert GLM_PROMPT_SHA256 in str(caught.value)


def test_load_fails_closed_when_nothing_can_be_verified_against(
    weights_dir: Path, layout_dir: Path
) -> None:
    adapter = adapter_mod.GlmOcrAdapter(FakePipeline())
    with pytest.raises(AdapterError) as caught:
        adapter.load(_config(weights_dir, layout_dir, prompt_text=""))
    assert caught.value.error_class == "MODEL_LOAD"
    assert "neither prompt_sha256 nor prompt_text" in str(caught.value)


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


# ------------------------------------------- the transformers pin (2026-09-03)
#
# The pod failure these cover: bootstrap.sh completed, then ``vllm serve`` died in
# 10 s because the image's transformers did not know model_type ``glm_ocr``, and
# RunPod restarted the exited container into an invisible crash loop.

#: The dependency pins the fix carries alongside transformers, whose own version
#: lives in bootstrap.sh's ``TRANSFORMERS_PIN``. Both files must install the same
#: strings -- a baked image and a bootstrap pod that disagree on transformers are
#: two different runtimes.
ARCHITECTURE_PINS = {
    "hf-xet": "1.3.2",
    "huggingface_hub": "1.5.0",
    "tokenizers": "0.22.2",
}


def _shell_code(name: str) -> str:
    """The lines a shell or docker would run.

    Comments in these files quote the retracted claim and the removed ``exit 70``
    on purpose, so a test that greps the whole file cannot tell a fix from a
    description of one.
    """
    text = (RUNTIME_DIR / name).read_text(encoding="utf-8")
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )


def _bootstrap_transformers_pin() -> str:
    text = (RUNTIME_DIR / "bootstrap.sh").read_text(encoding="utf-8")
    match = re.search(r"^TRANSFORMERS_PIN=(\S+)$", text, re.MULTILINE)
    assert match is not None, "bootstrap.sh does not define TRANSFORMERS_PIN"
    return match.group(1)


def test_bootstrap_pins_transformers_to_one_exact_version() -> None:
    assert _bootstrap_transformers_pin() == "5.4.0"
    assert '"transformers==${TRANSFORMERS_PIN}"' in _shell_code("bootstrap.sh")


def test_the_pin_is_above_the_floor_the_vendor_documents() -> None:
    """5.3.0 is what the SDK README says, and it cannot import the SDK's own layout stage.

    ``glmocr/layout/layout_detector.py`` imports ``PPDocLayoutV3ImageProcessor``;
    transformers only exports that name from 5.4.0 (5.3.0 has the ``Fast`` suffix).
    """
    major, minor, _ = (int(part) for part in _bootstrap_transformers_pin().split("."))
    assert (major, minor) >= (5, 4), "the pin must clear the SDK's real floor, not its stated one"
    text = (RUNTIME_DIR / "bootstrap.sh").read_text(encoding="utf-8")
    assert "PPDocLayoutV3ImageProcessor" in text, "and the file must say why it is not 5.3.0"


def test_dockerfile_pins_the_transformers_bootstrap_pins() -> None:
    pin = f'"transformers=={_bootstrap_transformers_pin()}"'
    assert pin in _shell_code("Dockerfile"), f"Dockerfile does not install {pin}"


@pytest.mark.parametrize("package,version", sorted(ARCHITECTURE_PINS.items()))
def test_both_files_carry_the_same_dependency_pin(package: str, version: str) -> None:
    pin = f'"{package}=={version}"'
    for name in ("bootstrap.sh", "Dockerfile"):
        assert pin in _shell_code(name), f"{name} does not pin {pin}"


@pytest.mark.parametrize("name", ("bootstrap.sh", "Dockerfile"))
def test_the_pins_are_installed_without_resolving_deps(name: str) -> None:
    """--no-deps, or pip is free to move torch and vLLM underneath (masterplan 15.1)."""
    code = _shell_code(name)
    assert "pip install -U" not in code, f"{name}: `pip install -U` is forbidden"
    head = code[: code.index("transformers==")]
    assert "pip install" in head
    assert "--no-deps" in head.rsplit("pip install", 1)[1], (
        f"{name}: the transformers install does not pass --no-deps"
    )


def test_the_dockerfile_no_longer_asserts_a_floor_on_the_images_transformers() -> None:
    """The retracted claim, in the only place it was ever executable."""
    code = _shell_code("Dockerfile")
    assert 'at_least(transformers_version, "5.3.0")' not in code
    # The floors that were true of the base image stay asserted.
    assert 'at_least(torch_version, "2.10.0")' in code
    assert 'at_least(vllm.__version__, "0.17.0")' in code


def test_readme_retracts_the_false_assertion_claim() -> None:
    text = (RUNTIME_DIR / "README.md").read_text(encoding="utf-8")
    assert "It did not." in text, "the README must retract the claim, not just drop it"
    assert "92miysvw0wk4wq" in text, "and name the pod that proved it false"


def test_runtime_json_retracts_the_false_assertion_claim() -> None:
    notes = " ".join(
        json.loads((RUNTIME_DIR / "runtime.json").read_text(encoding="utf-8"))["notes"]
    )
    assert "the claim this note replaces was false" in notes
    assert "bootstrap.sh asserted nothing" in notes


def test_bootstrap_preflight_checks_all_three_things_before_a_server_starts() -> None:
    code = _shell_code("bootstrap.sh")
    assert '"glm_ocr" not in CONFIG_MAPPING_NAMES' in code, (
        "the preflight must check transformers' config mapping"
    )
    assert "ModelRegistry.get_supported_archs()" in code, (
        "the preflight must check vLLM's registry for the declared architecture"
    )
    assert "transformers.__version__ != pin" in code, (
        "the preflight must prove the pin actually landed"
    )
    assert "[arena] architecture preflight PASS" in code
    assert "[arena] FATAL architecture preflight" in code
    assert "exit 64" in code
    # ...and before entrypoint.sh, which is what starts vLLM.
    assert code.index("architecture preflight") < code.index(
        'exec "${RUNTIME_DIR}/entrypoint.sh"'
    )


def test_bootstrap_preflight_runs_after_the_weights_it_reads() -> None:
    """It reads ``<weights>/config.json``; fetch_weights.py is what puts it there."""
    code = _shell_code("bootstrap.sh")
    assert code.index("fetch_weights.py") < code.index("CONFIG_MAPPING_NAMES")


def test_bootstrap_receipt_records_the_pin_and_the_preflight() -> None:
    code = _shell_code("bootstrap.sh")
    receipt = code[: code.index('} > "${RECEIPT}"')]
    assert 'echo "transformers_pin=${TRANSFORMERS_PIN}"' in receipt
    assert 'echo "architecture_preflight=PASS ${PREFLIGHT}"' in receipt


def test_entrypoint_makes_a_model_server_failure_sticky_and_visible() -> None:
    """D19's exit 70 handed the pod back to RunPod, which restarted it forever."""
    code = _shell_code("entrypoint.sh")
    assert "exit 70" not in code, "exiting is what RunPod restarts"
    assert "/opt/arena/FATAL" in code
    assert 'echo "[arena] FATAL ${reason}" >&2' in code, (
        "arena.controller.run.FATAL_LOG_SIGNATURES matches on this exact prefix"
    )
    assert "sleep infinity" in code
    assert "FATAL_LOG_TAIL_LINES=200" in code
    assert 'tail -n "${FATAL_LOG_TAIL_LINES}" "${SERVER_LOG}"' in code


def test_entrypoint_writes_the_fatal_file_on_the_readiness_failure_path() -> None:
    code = _shell_code("entrypoint.sh")
    start = code.index("if ! wait_for_model_server")
    branch = code[start : code.index("\nfi", start)]
    assert "write_fatal" in branch
    assert "sleep infinity" in branch
    assert "exit" not in branch, "any exit on this path is a RunPod restart"


def test_entrypoint_keeps_the_server_log_in_the_pod_log_too() -> None:
    """The driver's readiness poll reads the pod log, not ${SERVER_LOG}."""
    assert '> >(tee -a "${SERVER_LOG}" >&2) 2>&1 &' in _shell_code("entrypoint.sh")


def test_the_fatal_prefix_is_the_one_the_controller_condemns_on() -> None:
    """Not a literal duplicated by hand: read it back out of the controller."""
    from arena.controller.run import FATAL_LOG_SIGNATURES

    markers = dict(FATAL_LOG_SIGNATURES)
    assert markers["[arena] FATAL"] == "MODEL_LOAD"
    assert "[arena] FATAL" in _shell_code("entrypoint.sh")


def test_receipt_records_the_evidence_behind_the_pin() -> None:
    receipt = json.loads(
        (RUNTIME_DIR / "source-resolution-receipt.json").read_text(encoding="utf-8")
    )
    resolution = receipt["dependency_resolution"]
    assert resolution["trigger"]["pod_id"] == "92miysvw0wk4wq"
    urls = " ".join(row["url"] for row in resolution["evidence"])
    for required in (
        "vllm-project/vllm/v0.19.0/requirements/common.txt",
        "vllm/model_executor/models/registry.py",
        "zai-org/GLM-OCR/v0.1.5/README.md",
        "pypi.org/pypi/transformers/5.3.0/json",
    ):
        assert required in urls, f"the receipt does not cite {required}"
    assert resolution["not_verified"], "a receipt must say what it did not verify"


def test_the_pin_the_receipt_records_is_the_pin_the_scripts_install() -> None:
    """One place to change it, not four that can drift apart."""
    receipt = json.loads(
        (RUNTIME_DIR / "source-resolution-receipt.json").read_text(encoding="utf-8")
    )
    pins = receipt["dependency_resolution"]["pins"]
    assert pins["transformers"] == _bootstrap_transformers_pin()
    dockerfile = _shell_code("Dockerfile")
    bootstrap = _shell_code("bootstrap.sh")
    assert f'"transformers=={pins["transformers"]}"' in dockerfile
    for package in ARCHITECTURE_PINS:
        pin = f'"{package}=={pins[package]}"'
        assert pin in bootstrap, f"bootstrap.sh disagrees with the receipt on {package}"
        assert pin in dockerfile, f"Dockerfile disagrees with the receipt on {package}"


def test_runtime_json_says_why_this_pin_and_not_the_newest() -> None:
    notes = " ".join(
        json.loads((RUNTIME_DIR / "runtime.json").read_text(encoding="utf-8"))["notes"]
    )
    assert "transformers==5.4.0" in notes
    assert "5.16.1" in notes, "the note must name the newest release it declined"
    assert "safetensors 0.7.0" in notes, "and why -- the pod's own versions"
    assert "NOT VERIFIED ON HARDWARE" in notes


# ------------------------ the SDK load path (2026-09-04, pod jdwdnvg8a2rzx6)
#
# vLLM initialised its engine at 18:38:17Z and the worker reported CRASHED about a
# minute later, with no captured reason. Reading glmocr 0.1.5 against this adapter
# found three defects on that path, and a fourth in the dependency set. These cover
# all four; none of them claims to be the root cause the pod did not record.


#: ``glmocr/config.yaml`` v0.1.5, the sections this adapter overrides. The value
#: that matters is ``maas.enabled``: the SDK ships it TRUE, so a config that does
#: not reach the SDK does not fall back to "local" -- it falls back to Zhipu.
SHIPPED_SDK_DEFAULTS: dict[str, Any] = {
    "maas": {"enabled": True},
    "ocr_api": {"api_host": "127.0.0.1", "api_port": 8080, "retry_max_attempts": 2},
    "layout": {"model_dir": "PaddlePaddle/PP-DocLayoutV3_safetensors"},
    "page_loader": {"task_prompt_mapping": None},
}


def _config_model(pipeline: Mapping[str, Any]) -> SimpleNamespace:
    """One level of attribute access, like the SDK's pydantic models.

    Sections become objects; their values stay what they are, so
    ``page_loader.task_prompt_mapping`` is still a dict.
    """
    sections = {
        key: SimpleNamespace(**value) if isinstance(value, Mapping) else value
        for key, value in pipeline.items()
    }
    return SimpleNamespace(pipeline=SimpleNamespace(**sections))


class FakeGlmOcr:
    """``glmocr.api.GlmOcr`` at v0.1.5: the signature, and the config resolution.

    ``config_path`` is a YAML path and there is no ``config`` parameter; anything
    else lands in ``**kwargs`` and is forwarded into ``load_config``, which drops
    names it does not know. This double keeps that behaviour so a test can tell a
    config that landed from one that was silently dropped.
    """

    def __init__(
        self,
        config_path: str | None = None,
        *,
        layout_device: str | None = None,
        **kwargs: Any,
    ) -> None:
        self.config_path = config_path
        self.layout_device = layout_device
        self.kwargs = kwargs
        self.closed = False
        merged = copy.deepcopy(SHIPPED_SDK_DEFAULTS)
        for section, values in self._document().items():
            if isinstance(values, Mapping):
                merged.setdefault(section, {}).update(values)
            else:
                merged[section] = values
        self.config_model = _config_model(merged)

    def _document(self) -> Mapping[str, Any]:
        if self.config_path is None:
            return {}
        loaded = yaml.safe_load(Path(self.config_path).read_text(encoding="utf-8"))
        return (loaded or {}).get("pipeline", {})

    def close(self) -> None:
        self.closed = True


class DeafGlmOcr(FakeGlmOcr):
    """The bug as it was: the settings never reach the SDK, MaaS stays on."""

    def _document(self) -> Mapping[str, Any]:
        return {}


class UnimportableGlmOcr:
    """``glmocr/layout/__init__.py`` re-raising a layout ImportError from Pipeline()."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise ImportError("cannot import name 'PPDocLayoutV3ImageProcessor' from 'transformers'")


@pytest.fixture
def install_fake_sdk(monkeypatch: pytest.MonkeyPatch) -> Any:
    def install(cls: type) -> ModuleType:
        module = ModuleType("glmocr")
        module.GlmOcr = cls  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "glmocr", module)
        monkeypatch.setattr(importlib.metadata, "version", lambda name: "0.1.5")
        return module

    return install


def _pipeline_config(layout_dir: Path, **overrides: Any) -> dict[str, Any]:
    config: dict[str, Any] = {
        "api_host": "127.0.0.1",
        "api_port": 8080,
        "served_model_name": "glm-ocr",
        "layout_model_dir": str(layout_dir),
        "layout_device": "cuda:0",
    }
    config.update(overrides)
    return config


def test_the_pipeline_configures_the_sdk_through_config_path(
    layout_dir: Path, install_fake_sdk: Any
) -> None:
    """``GlmOcr`` has no ``config`` parameter; a dict handed to it is dropped."""
    install_fake_sdk(FakeGlmOcr)
    pipeline = adapter_mod.OfficialSdkPipeline(_pipeline_config(layout_dir))
    parser = pipeline._ensure_parser()
    assert "config" not in parser.kwargs, "a `config` keyword is swallowed by **kwargs"
    assert parser.kwargs == {}, f"unknown keywords are dropped by load_config: {parser.kwargs}"
    assert parser.layout_device == "cuda:0"
    written = yaml.safe_load(Path(parser.config_path).read_text(encoding="utf-8"))
    assert written == pipeline.sdk_config(), "the file must carry the frozen settings"


def test_the_rendered_config_turns_maas_off_and_retries_to_zero(
    layout_dir: Path, install_fake_sdk: Any
) -> None:
    install_fake_sdk(FakeGlmOcr)
    pipeline = adapter_mod.OfficialSdkPipeline(_pipeline_config(layout_dir))
    resolved = pipeline._ensure_parser().config_model.pipeline
    assert resolved.maas.enabled is False
    assert resolved.ocr_api.retry_max_attempts == 0
    assert resolved.ocr_api.api_host == "127.0.0.1"
    assert resolved.ocr_api.api_port == 8080
    assert resolved.layout.model_dir == str(layout_dir)
    assert resolved.page_loader.task_prompt_mapping == adapter_mod.OFFICIAL_TASK_PROMPTS


def test_the_pipeline_refuses_a_config_the_sdk_did_not_apply(
    layout_dir: Path, install_fake_sdk: Any
) -> None:
    """The defect itself: the SDK keeps its shipped defaults and MaaS stays on."""
    install_fake_sdk(DeafGlmOcr)
    pipeline = adapter_mod.OfficialSdkPipeline(_pipeline_config(layout_dir))
    with pytest.raises(AdapterError) as caught:
        pipeline._ensure_parser()
    assert caught.value.error_class == "MODEL_LOAD"
    assert "maas" in str(caught.value).lower()


def test_the_pipeline_refuses_when_the_sdk_exposes_no_resolved_config(
    layout_dir: Path, install_fake_sdk: Any
) -> None:
    class NoConfigModel:
        def __init__(self, config_path: str | None = None, **kwargs: Any) -> None:
            self.config_path = config_path

    install_fake_sdk(NoConfigModel)
    pipeline = adapter_mod.OfficialSdkPipeline(_pipeline_config(layout_dir))
    with pytest.raises(AdapterError) as caught:
        pipeline._ensure_parser()
    assert caught.value.error_class == "DEPENDENCY"


def test_the_pipeline_refuses_a_layout_dir_that_would_be_read_as_a_repo_id(
    tmp_path: Path, install_fake_sdk: Any
) -> None:
    """glmocr hands model_dir to from_pretrained, which downloads a missing path."""
    install_fake_sdk(FakeGlmOcr)
    pipeline = adapter_mod.OfficialSdkPipeline(
        _pipeline_config(tmp_path / "not-there", layout_model_dir="PaddlePaddle/PP-DocLayoutV3")
    )
    with pytest.raises(AdapterError) as caught:
        pipeline._ensure_parser()
    assert caught.value.error_class == "MODEL_LOAD"
    assert "repo id" in str(caught.value)


def test_a_deferred_layout_import_error_is_a_dependency_failure(
    layout_dir: Path, install_fake_sdk: Any
) -> None:
    install_fake_sdk(UnimportableGlmOcr)
    pipeline = adapter_mod.OfficialSdkPipeline(_pipeline_config(layout_dir))
    with pytest.raises(AdapterError) as caught:
        pipeline._ensure_parser()
    assert caught.value.error_class == "DEPENDENCY"
    assert "PPDocLayoutV3ImageProcessor" in str(caught.value)


def test_close_closes_the_sdk_and_removes_the_rendered_config(
    layout_dir: Path, install_fake_sdk: Any
) -> None:
    install_fake_sdk(FakeGlmOcr)
    pipeline = adapter_mod.OfficialSdkPipeline(_pipeline_config(layout_dir))
    parser = pipeline._ensure_parser()
    config_path = Path(parser.config_path)
    assert config_path.is_file()
    pipeline.close()
    assert parser.closed is True, "the SDK pipeline owns worker threads"
    assert not config_path.exists()


def test_the_adapter_closes_the_pipeline_it_built(weights_dir: Path, layout_dir: Path) -> None:
    class ClosablePipeline(FakePipeline):
        def __init__(self) -> None:
            super().__init__()
            self.closed = False

        def close(self) -> None:
            self.closed = True

    pipeline = ClosablePipeline()
    adapter = adapter_mod.GlmOcrAdapter(pipeline=pipeline)
    adapter.load(_config(weights_dir, layout_dir))
    adapter.close()
    assert pipeline.closed is True


# ------------------------------------------------- ARENA_LAYOUT_DIR (D33/D48)


def test_resolve_layout_model_dir_defaults_to_the_frozen_config() -> None:
    resolved = adapter_mod.resolve_layout_model_dir({"layout_model_dir": "/opt/layout"})
    assert resolved == "/opt/layout"


def test_resolve_layout_model_dir_prefers_the_bootstrap_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(adapter_mod.LAYOUT_DIR_ENV, "/workspace/layout")
    resolved = adapter_mod.resolve_layout_model_dir({"layout_model_dir": "/opt/layout"})
    assert resolved == "/workspace/layout"


def test_load_finds_the_layout_model_where_bootstrap_put_it(
    weights_dir: Path, layout_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The pod jdwdnvg8a2rzx6 shape: frozen config says /opt, the file is elsewhere."""
    config = _config(
        weights_dir,
        layout_dir,
        inference_config={"layout_model_dir": "/opt/arena/weights/pp_doclayoutv3_safetensors"},
    )
    adapter = adapter_mod.GlmOcrAdapter(pipeline=FakePipeline())
    with pytest.raises(AdapterError) as caught:
        adapter.load(config)
    assert caught.value.error_class == "MODEL_LOAD"

    monkeypatch.setenv(adapter_mod.LAYOUT_DIR_ENV, str(layout_dir))
    receipt = adapter_mod.GlmOcrAdapter(pipeline=FakePipeline()).load(config)
    layout = receipt.runtime_provenance["layout_model"]
    assert layout["model_dir"] == str(layout_dir)


def test_sdk_config_sends_the_resolved_layout_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(adapter_mod.LAYOUT_DIR_ENV, "/workspace/layout")
    pipeline = adapter_mod.OfficialSdkPipeline({"layout_model_dir": "/opt/layout"})
    assert pipeline.sdk_config()["pipeline"]["layout"]["model_dir"] == "/workspace/layout"


def test_entrypoint_exports_the_directories_it_verified() -> None:
    code = _shell_code("entrypoint.sh")
    weights = 'export ARENA_WEIGHTS_DIR="${WEIGHTS_DIR}"'
    layout = 'export ARENA_LAYOUT_DIR="${LAYOUT_DIR}"'
    for line in (weights, layout):
        assert line in code, f"entrypoint.sh does not export {line}"
    assert code.index("fetch_layout_model.py") < code.index(layout)
    assert code.index(layout) < code.index("python3 -m arena.worker.server")


def test_entrypoint_goes_offline_before_the_worker_starts() -> None:
    """from_pretrained turns a missing local path into an unpinned download."""
    code = _shell_code("entrypoint.sh")
    assert "export HF_HUB_OFFLINE=1" in code
    assert "export TRANSFORMERS_OFFLINE=1" in code
    # After the two things that ARE allowed to download, and before the worker.
    assert code.index("fetch_layout_model.py") < code.index("export HF_HUB_OFFLINE=1")
    assert code.index("export HF_HUB_OFFLINE=1") < code.index("python3 -m arena.worker.server")


# ------------------------------------------------------------ import preflight


def _preflight_modules(name: str) -> tuple[str, ...]:
    """The ``MODULES = (...)`` tuple the import preflight in *name* walks."""
    text = (RUNTIME_DIR / name).read_text(encoding="utf-8")
    match = re.search(r"^MODULES = \((.*?)^\)$", text, re.MULTILINE | re.DOTALL)
    assert match is not None, f"{name} has no import preflight MODULES tuple"
    return tuple(re.findall(r'"([^"]+)"', match.group(1)))


def test_bootstrap_imports_what_the_adapter_will_import() -> None:
    modules = _preflight_modules("bootstrap.sh")
    for required in (
        "glmocr",
        "glmocr.api",
        "glmocr.config",
        "glmocr.pipeline.pipeline",
        "glmocr.dataloader.page_loader",
        "glmocr.postprocess.result_formatter",
        "glmocr.ocr_client",
    ):
        assert required in modules, f"the import preflight does not import {required}"


def test_the_preflight_imports_the_layout_leaf_not_the_package() -> None:
    """``glmocr/layout/__init__.py`` swallows the ImportError and defers it to Pipeline()."""
    modules = _preflight_modules("bootstrap.sh")
    assert "glmocr.layout.layout_detector" in modules
    assert "glmocr.layout" not in modules, "the package guard would mask the real error"


def test_the_preflight_imports_the_adapter_the_way_the_worker_does() -> None:
    from arena.worker.loader import ADAPTER_FILE, ADAPTER_MODULE_NAME

    code = _shell_code("bootstrap.sh")
    assert f'spec_from_file_location("{ADAPTER_MODULE_NAME}"' in code
    assert ADAPTER_FILE in code


def test_the_preflight_instantiates_nothing() -> None:
    """It runs before the GPU is touched; a detector or a GlmOcr here defeats that."""
    code = _shell_code("bootstrap.sh")
    block = code[code.index("IMPORT_PREFLIGHT=") : code.index("IMPORT_STATUS=$?")]
    assert "GlmOcr(" not in block
    assert "PPDocLayoutDetector(" not in block
    assert "cuda" not in block


def test_the_preflight_fails_closed_with_the_contract_message() -> None:
    code = _shell_code("bootstrap.sh")
    assert "[arena] FATAL import preflight: " in code
    block = code[code.index("IMPORT_STATUS=$?") : code.index("fetch_weights.py")]
    assert "exit 64" in block


def test_the_preflight_runs_after_the_installs_and_before_the_rest() -> None:
    code = _shell_code("bootstrap.sh")
    assert code.index('"glmocr==0.1.5"') < code.index("IMPORT_PREFLIGHT=")
    assert code.index('"transformers==${TRANSFORMERS_PIN}"') < code.index("IMPORT_PREFLIGHT=")
    # Before the weights, so a broken install costs no download...
    assert code.index("IMPORT_PREFLIGHT=") < code.index("fetch_weights.py")
    # ...and before the architecture preflight, which cannot see an SDK import.
    assert code.index("IMPORT_PREFLIGHT=") < code.index("CONFIG_MAPPING_NAMES")


def test_bootstrap_receipt_records_the_import_preflight() -> None:
    code = _shell_code("bootstrap.sh")
    receipt = code[: code.index('} > "${RECEIPT}"')]
    assert 'echo "import_preflight=PASS ${IMPORT_PREFLIGHT} modules"' in receipt


def test_the_dockerfile_walks_the_same_module_list() -> None:
    """A baked image that imports less than the bootstrap pod is a different runtime."""
    assert _preflight_modules("Dockerfile") == _preflight_modules("bootstrap.sh")


def test_the_preflight_detector_fires_on_a_script_without_one() -> None:
    """The greps above must be able to fail."""
    with pytest.raises(AssertionError):
        _preflight_modules("entrypoint.sh")


# ----------------------------------------------------- the undeclared dependency


def test_both_files_pin_the_dependency_the_sdk_forgot_to_declare() -> None:
    """glmocr's pyproject never names wordfreq; result_formatter.py imports it."""
    for name in ("bootstrap.sh", "Dockerfile"):
        assert '"wordfreq==3.1.1"' in _shell_code(name), f"{name} does not pin wordfreq"


def test_wordfreq_is_installed_with_its_dependencies() -> None:
    """msgpack, langcodes, ftfy and locate are not in the vLLM image."""
    for name in ("bootstrap.sh", "Dockerfile"):
        code = _shell_code(name)
        head = code[: code.index('"wordfreq==3.1.1"')]
        install = head.rsplit("pip install", 1)[1]
        assert "--no-deps" not in install, f"{name} installs wordfreq with --no-deps"


def test_the_receipt_records_the_wordfreq_pin_and_why() -> None:
    receipt = json.loads(
        (RUNTIME_DIR / "source-resolution-receipt.json").read_text(encoding="utf-8")
    )
    resolution = receipt["dependency_resolution"]
    assert resolution["pins"]["wordfreq"] == "3.1.1"
    evidence = " ".join(row["fact"] + row["reading"] for row in resolution["evidence"])
    assert "wordfreq" in evidence
    assert "PPDocLayoutV3ImageProcessor" in evidence


def test_the_receipt_names_the_adapter_defects_it_fixed() -> None:
    receipt = json.loads(
        (RUNTIME_DIR / "source-resolution-receipt.json").read_text(encoding="utf-8")
    )
    resolution = receipt["dependency_resolution"]
    assert resolution["second_trigger"]["pod_id"] == "jdwdnvg8a2rzx6"
    defects = resolution["adapter_defects"]
    assert len(defects) >= 3
    for row in defects:
        assert row["defect"] and row["fix"] and row["source"]
    calls = " ".join(row["call"] for row in defects)
    assert "GlmOcr(config=<dict>" in calls
    assert "layout_model_dir" in calls


def test_the_readme_count_matches_the_module_list() -> None:
    """This runtime already shipped one README claim that the code did not hold."""
    expected = len(_preflight_modules("bootstrap.sh")) + 2
    text = (RUNTIME_DIR / "README.md").read_text(encoding="utf-8")
    assert f"import preflight PASS {expected} modules" in text
