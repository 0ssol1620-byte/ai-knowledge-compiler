"""Unit tests for the olmOCR-2-7B-1025-FP8 runtime (lane C3).

No GPU, no network, no torch/vllm/transformers/olmocr. The toolkit prompt source
and the Pillow image preparer are both injected, so the tests cover the drift check
and the resize accounting without installing either dependency.
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

MODEL_KEY = "olmocr2"
RUNTIME_DIR = Path(__file__).resolve().parents[2] / "runtimes" / MODEL_KEY

#: Verbatim from olmocr/prompts/prompts.py at tag v0.4.27.
TOOLKIT_PROMPT = (
    "Attached is one page of a document that you must process. "
    "Just return the plain text representation of this document as if you were "
    "reading it naturally. Convert equations to LateX and tables to HTML.\n"
    "If there are any figures or charts, label them with the following markdown "
    "syntax ![Alt text describing the contents of the figure]"
    "(page_startx_starty_width_height.png)\n"
    "Return your output as markdown, with a front matter section on top specifying "
    "values for the primary_language, is_rotation_valid, rotation_correction, "
    "is_table, and is_diagram parameters."
)


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


class FakeBackend:
    def __init__(self, response: Mapping[str, Any] | None = None) -> None:
        self.response: Mapping[str, Any] = response if response is not None else _completion("x")
        self.calls: list[Mapping[str, Any]] = []

    def chat(self, payload: Mapping[str, Any], timeout_s: float) -> Mapping[str, Any]:
        self.calls.append(payload)
        return self.response

    def provenance(self) -> Mapping[str, Any]:
        return {"backend": "fake"}


class FakePromptSource:
    def __init__(self, prompt: str = TOOLKIT_PROMPT) -> None:
        self._prompt = prompt

    def build_prompt(self) -> str:
        return self._prompt

    def describe(self) -> Mapping[str, Any]:
        return {"source": "fake", "olmocr_version": "0.4.27"}


class FakeImagePreparer:
    def __init__(self, *, resized: bool = True) -> None:
        self.resized = resized
        self.requested_target: int | None = None

    def prepare(self, image_path: Path, target_longest: int) -> Any:
        self.requested_target = target_longest
        return adapter_mod.PreparedImage(
            png_bytes=image_path.read_bytes(),
            width=target_longest if self.resized else 900,
            height=int(target_longest * 1.4) if self.resized else 700,
            source_width=2480,
            source_height=3508,
            resized=self.resized,
        )

    def describe(self) -> Mapping[str, Any]:
        return {"preparer": "fake"}


def _completion(content: str, finish_reason: str = "stop") -> dict[str, Any]:
    return {
        "choices": [{"message": {"content": content}, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 9},
    }


@pytest.fixture
def weights_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "weights"
    directory.mkdir()
    largest = directory / "model-00001-of-00003.safetensors"
    largest.write_bytes(b"fp8 bytes")
    digest = "sha256:" + hashlib.sha256(largest.read_bytes()).hexdigest()
    (directory / adapter_mod.WEIGHTS_SIDECAR_NAME).write_text(
        json.dumps(
            {
                "repo": "allenai/olmOCR-2-7B-1025-FP8",
                "revision": "40bd7202494b8264ee17ada08b401b5aab7a9ce1",
                "largest_file": largest.name,
                "largest_file_sha256": digest,
                "files_manifest_sha256": "sha256:" + "2" * 64,
                "cache_hit": False,
            }
        ),
        encoding="utf-8",
    )
    return directory


def _config(weights_dir: Path, **overrides: Any) -> AdapterConfig:
    inference_config: dict[str, Any] = {
        "endpoint": "http://127.0.0.1:8100/v1/chat/completions",
        "served_model_name": "olmocr",
        "max_tokens": 8000,
        "temperature": 0.0,
        "target_longest_image_dim": 1288,
        "hash_weights_on_load": False,
    }
    inference_config.update(overrides.pop("inference_config", {}))
    return AdapterConfig(
        model_key=MODEL_KEY,
        model_repo=overrides.pop("model_repo", "allenai/olmOCR-2-7B-1025-FP8"),
        model_revision=overrides.pop(
            "model_revision", "40bd7202494b8264ee17ada08b401b5aab7a9ce1"
        ),
        weights_dir=weights_dir,
        prompt_id="olmocr2_no_anchoring_v4_yaml_v1",
        prompt_text=overrides.pop("prompt_text", TOOLKIT_PROMPT),
        inference_config=inference_config,
        inference_config_sha256="sha256:" + "3" * 64,
    )


def _page(tmp_path: Path) -> PageInput:
    image = tmp_path / "page.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n page")
    return PageInput(
        inference_job_id="b" * 64,
        sample_id="olmocr:bench_data/pdfs/arxiv_math/2502.15977_pg21#p0",
        case_key="olmocr-bench-2502-15977-pg21",
        benchmark="olmocr",
        image_path=image,
        source_sha256="sha256:" + hashlib.sha256(image.read_bytes()).hexdigest(),
        width=2480,
        height=3508,
        metadata={"page_index": 0, "media_type": "pdf"},
    )


def _ready(weights_dir: Path, backend: FakeBackend, **kwargs: Any) -> Any:
    preparer = kwargs.pop("preparer", FakeImagePreparer())
    adapter = adapter_mod.OlmOcr2Adapter(backend, FakePromptSource(), preparer)
    adapter.load(_config(weights_dir, **kwargs))
    return adapter


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
    assert spec["model_revision"] == "40bd7202494b8264ee17ada08b401b5aab7a9ce1"
    assert "@sha256:" in spec["base_image"]
    assert spec["license"]["status"] == "approved"


def test_runtime_json_records_the_toolkit_pin() -> None:
    config = json.loads((RUNTIME_DIR / "runtime.json").read_text(encoding="utf-8"))[
        "inference_config"
    ]
    assert config["toolkit_tag"] == "v0.4.27"
    assert len(config["toolkit_revision"]) == 40
    assert config["toolkit_prompt_builder"].endswith("build_no_anchoring_v4_yaml_prompt")
    assert config["target_longest_image_dim"] == 1288
    assert config["max_tokens"] == 8000


def test_ampere_pools_are_excluded_because_fp8_needs_sm89() -> None:
    """Masterplan 13.3 says 4090/A40; A40 is Ampere and does not do native FP8."""
    spec = json.loads((RUNTIME_DIR / "runtime.json").read_text(encoding="utf-8"))
    assert not any("A40" in pool or "A100" in pool for pool in spec["gpu_pool_priority"])
    notes = " ".join(spec["notes"])
    assert "8.9" in notes and "A40" in notes


# ---------------------------------------------------------- import hygiene


def _module_level_imports(path: Path) -> set[str]:
    """Top-level import names only; imports inside functions do not count."""
    names: set[str] = set()
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_adapter_imports_without_a_gpu_stack() -> None:
    imported = _module_level_imports(RUNTIME_DIR / "adapter.py")
    assert imported.isdisjoint({"torch", "vllm", "transformers", "olmocr", "PIL", "numpy"})


def test_adapter_satisfies_the_frozen_protocol() -> None:
    assert isinstance(adapter_mod.OlmOcr2Adapter(), ArenaModelAdapter)


# ------------------------------------------------------------------- load


def test_load_happy_path(weights_dir: Path) -> None:
    adapter = adapter_mod.OlmOcr2Adapter(FakeBackend(), FakePromptSource(), FakeImagePreparer())
    receipt = adapter.load(_config(weights_dir))
    assert receipt.model_revision == "40bd7202494b8264ee17ada08b401b5aab7a9ce1"
    assert receipt.runtime_provenance["prompt_source"]["olmocr_version"] == "0.4.27"


def test_load_fails_closed_on_prompt_drift(weights_dir: Path) -> None:
    """The registered prompt and the installed toolkit's prompt must agree (D34)."""
    adapter = adapter_mod.OlmOcr2Adapter(FakeBackend(), FakePromptSource(), FakeImagePreparer())
    with pytest.raises(AdapterError) as caught:
        adapter.load(_config(weights_dir, prompt_text="a prompt somebody edited"))
    assert caught.value.error_class == "MODEL_LOAD"
    assert adapter_mod.TOOLKIT_PROMPT_BUILDER in str(caught.value)
    assert "prompt_kind=toolkit" in str(caught.value)


# ------------------------------------------------------------ D34 prompt kind


def test_runtime_json_declares_the_kind_the_adapter_implements() -> None:
    spec = json.loads((RUNTIME_DIR / "runtime.json").read_text(encoding="utf-8"))
    assert spec["prompt_kind"] == "toolkit"
    assert spec["prompt_kind"] == adapter_mod.PROMPT_KIND
    assert (
        spec["inference_config"]["toolkit_prompt_builder"] == adapter_mod.TOOLKIT_PROMPT_BUILDER
    )


def test_the_registry_file_is_what_the_pinned_toolkit_builds() -> None:
    """Lane R's file must be byte-identical to build_no_anchoring_v4_yaml_prompt()."""
    registry_dir = Path(__file__).resolve().parents[2] / "prompt_registry"
    spec = json.loads((RUNTIME_DIR / "runtime.json").read_text(encoding="utf-8"))
    prompt_file = registry_dir / f"{spec['prompt_id']}.txt"
    assert prompt_file.is_file(), f"D17: {prompt_file.name} must exist"
    raw = prompt_file.read_bytes()
    assert raw == TOOLKIT_PROMPT.encode("utf-8"), (
        "the registry holds a different prompt than the pinned toolkit builds; "
        "the anchored build_finetuning_prompt is NOT this runtime's prompt"
    )
    recorded = json.loads((registry_dir / "sha256.json").read_text(encoding="utf-8"))
    assert recorded[spec["prompt_id"]] == "sha256:" + hashlib.sha256(raw).hexdigest()


def test_load_records_the_verified_prompt_hash(weights_dir: Path) -> None:
    adapter = adapter_mod.OlmOcr2Adapter(FakeBackend(), FakePromptSource(), FakeImagePreparer())
    receipt = adapter.load(_config(weights_dir))
    expected = hashlib.sha256(TOOLKIT_PROMPT.encode("utf-8")).hexdigest()
    assert receipt.runtime_provenance["prompt_kind"] == "toolkit"
    assert receipt.runtime_provenance["prompt_sha256"] == f"sha256:{expected}"


def test_the_wire_carries_the_toolkit_prompt_not_the_registry_copy(
    weights_dir: Path, tmp_path: Path
) -> None:
    """prompt_kind=toolkit: what is sent is what load() built and verified."""
    backend = FakeBackend()
    adapter = adapter_mod.OlmOcr2Adapter(backend, FakePromptSource(), FakeImagePreparer())
    adapter.load(_config(weights_dir))
    adapter.infer(_page(tmp_path))
    content = backend.calls[-1]["messages"][0]["content"]
    text_parts = [part["text"] for part in content if part["type"] == "text"]
    assert text_parts == [TOOLKIT_PROMPT]


def test_load_fails_closed_when_nothing_can_be_verified_against(weights_dir: Path) -> None:
    adapter = adapter_mod.OlmOcr2Adapter(FakeBackend(), FakePromptSource(), FakeImagePreparer())
    with pytest.raises(AdapterError) as caught:
        adapter.load(_config(weights_dir, prompt_text=""))
    assert caught.value.error_class == "MODEL_LOAD"
    assert "neither prompt_sha256 nor prompt_text" in str(caught.value)


def test_load_rejects_a_revision_mismatch(weights_dir: Path) -> None:
    adapter = adapter_mod.OlmOcr2Adapter(FakeBackend(), FakePromptSource(), FakeImagePreparer())
    with pytest.raises(AdapterError) as caught:
        adapter.load(_config(weights_dir, model_revision="f" * 40))
    assert caught.value.error_class == "MODEL_LOAD"


def test_load_rejects_a_checksum_mismatch(weights_dir: Path) -> None:
    (weights_dir / "model-00001-of-00003.safetensors").write_bytes(b"different")
    adapter = adapter_mod.OlmOcr2Adapter(FakeBackend(), FakePromptSource(), FakeImagePreparer())
    with pytest.raises(AdapterError) as caught:
        adapter.load(_config(weights_dir))
    assert caught.value.error_class == "CHECKSUM"


def test_toolkit_prompt_source_reports_a_missing_toolkit() -> None:
    with pytest.raises(AdapterError) as caught:
        adapter_mod.ToolkitPromptSource().build_prompt()
    assert caught.value.error_class == "DEPENDENCY"


# ------------------------------------------------------------------ infer


def test_infer_uses_the_toolkit_target_and_sampling(weights_dir: Path, tmp_path: Path) -> None:
    backend = FakeBackend(_completion("---\nprimary_language: en\n---\nBody"))
    preparer = FakeImagePreparer()
    adapter = _ready(weights_dir, backend, preparer=preparer)
    adapter.infer(_page(tmp_path))
    assert preparer.requested_target == 1288
    payload = backend.calls[0]
    assert payload["max_tokens"] == 8000
    assert payload["temperature"] == 0.0
    assert payload["model"] == "olmocr"
    content = payload["messages"][0]["content"]
    assert content[0]["text"] == TOOLKIT_PROMPT
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_infer_records_the_resize_in_warnings_and_native_json(
    weights_dir: Path, tmp_path: Path
) -> None:
    adapter = _ready(weights_dir, FakeBackend(_completion("---\nis_table: False\n---\nText")))
    raw = adapter.infer(_page(tmp_path))
    assert any("resampled from 2480x3508" in w for w in raw.warnings)
    assert raw.native_json is not None
    assert raw.native_json["image"]["resized"] is True
    assert raw.native_json["image"]["target_longest_image_dim"] == 1288


def test_infer_says_so_when_no_resize_happened(weights_dir: Path, tmp_path: Path) -> None:
    adapter = _ready(
        weights_dir,
        FakeBackend(_completion("---\nis_table: False\n---\nText")),
        preparer=FakeImagePreparer(resized=False),
    )
    raw = adapter.infer(_page(tmp_path))
    assert any("never upscaled" in w for w in raw.warnings)


def test_infer_flags_a_missing_front_matter(weights_dir: Path, tmp_path: Path) -> None:
    adapter = _ready(weights_dir, FakeBackend(_completion("Just a markdown body.")))
    raw = adapter.infer(_page(tmp_path))
    assert any("no YAML front matter" in w for w in raw.warnings)


def test_infer_flags_truncation_but_keeps_the_bytes(weights_dir: Path, tmp_path: Path) -> None:
    adapter = _ready(weights_dir, FakeBackend(_completion("---\nx: 1\n---\nhalf", "length")))
    raw = adapter.infer(_page(tmp_path))
    assert f"{adapter_mod.SEMANTIC_ERROR_PREFIX}OUTPUT_TRUNCATED" in raw.warnings
    assert raw.raw_text.endswith("half")
    assert raw.semantic_error_class == "OUTPUT_TRUNCATED"


def test_infer_flags_an_empty_response(weights_dir: Path, tmp_path: Path) -> None:
    adapter = _ready(weights_dir, FakeBackend(_completion("")))
    raw = adapter.infer(_page(tmp_path))
    assert f"{adapter_mod.SEMANTIC_ERROR_PREFIX}OUTPUT_EMPTY" in raw.warnings
    assert raw.semantic_error_class == "OUTPUT_EMPTY"


def test_infer_semantic_error_class_is_none_on_a_clean_response(
    weights_dir: Path, tmp_path: Path
) -> None:
    adapter = _ready(
        weights_dir, FakeBackend(_completion("---\nprimary_language: en\n---\nBody text"))
    )
    raw = adapter.infer(_page(tmp_path))
    assert raw.semantic_error_class is None


def test_infer_rejects_a_malformed_response(weights_dir: Path, tmp_path: Path) -> None:
    adapter = _ready(weights_dir, FakeBackend({"choices": [{"message": {"content": 7}}]}))
    with pytest.raises(AdapterError) as caught:
        adapter.infer(_page(tmp_path))
    assert caught.value.error_class == "OUTPUT_MALFORMED"


def test_front_matter_parser_handles_the_documented_shape() -> None:
    parsed = adapter_mod.parse_front_matter(
        "---\nprimary_language: en\nis_rotation_valid: True\n"
        "rotation_correction: 0\nis_table: False\nis_diagram: False\n---\nBody"
    )
    assert parsed == {
        "primary_language": "en",
        "is_rotation_valid": "True",
        "rotation_correction": "0",
        "is_table": "False",
        "is_diagram": "False",
    }
    assert adapter_mod.parse_front_matter("no front matter here") is None


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


def _native(front: Mapping[str, str] | None, resized: bool = True) -> dict[str, Any]:
    return {
        "front_matter": dict(front) if front is not None else None,
        "image": {
            "source_width": 2480,
            "source_height": 3508,
            "served_width": 1288,
            "served_height": 1822,
            "resized": resized,
            "target_longest_image_dim": 1288,
        },
    }


def test_canonicalize_lifts_front_matter_out_of_the_markdown() -> None:
    text = (
        "---\nprimary_language: en\nis_rotation_valid: True\nrotation_correction: 0\n"
        "is_table: False\nis_diagram: False\n---\n# Heading\n\nBody text.\n"
    )
    front = {
        "primary_language": "en",
        "is_rotation_valid": "True",
        "rotation_correction": "0",
        "is_table": "False",
        "is_diagram": "False",
    }
    result = canonical_mod.canonicalize(_raw(text, _native(front)))
    assert result.markdown.startswith("# Heading")
    assert "primary_language" not in result.markdown
    assert result.elements is not None
    kinds = [element["kind"] for element in result.elements]
    assert "olmocr_front_matter" in kinds
    assert "arena_image_handling" in kinds
    assert result.lossy is False


def test_canonicalize_keeps_a_table_and_a_formula_verbatim() -> None:
    text = (
        "---\nis_table: True\n---\n"
        "<table><tr><td>Q1</td></tr></table>\n\n\\(E = mc^2\\)\n"
    )
    result = canonical_mod.canonicalize(_raw(text, _native({"is_table": "True"})))
    assert "<table><tr><td>Q1</td></tr></table>" in result.markdown
    assert "\\(E = mc^2\\)" in result.markdown


def test_canonicalize_reports_missing_front_matter_keys() -> None:
    result = canonical_mod.canonicalize(
        _raw("---\nprimary_language: en\n---\nBody", _native({"primary_language": "en"}))
    )
    joined = " ".join(result.conversion_notes)
    assert "front matter omitted" in joined
    assert "is_table" in joined


def test_canonicalize_records_a_rotation_report_without_acting_on_it() -> None:
    front = {"rotation_correction": "90", "is_rotation_valid": "False"}
    text = "---\nrotation_correction: 90\n---\nB"
    result = canonical_mod.canonicalize(_raw(text, _native(front)))
    joined = " ".join(result.conversion_notes)
    assert "rotation_correction='90'" in joined
    assert "recorded, not acted on" in joined


def test_canonicalize_falls_back_to_raw_text_without_front_matter() -> None:
    result = canonical_mod.canonicalize(_raw("Body only", _native(None)))
    assert result.markdown == "Body only"
    assert any("no parseable YAML front matter" in n for n in result.conversion_notes)


def test_canonicalize_empty_output_is_flagged_lossy() -> None:
    result = canonical_mod.canonicalize(
        _raw("", None, warnings=("arena.semantic_error_class=OUTPUT_EMPTY",))
    )
    assert result.markdown == ""
    assert result.lossy is True


def test_canonicalize_truncated_output_is_flagged_lossy() -> None:
    result = canonical_mod.canonicalize(
        _raw(
            "---\nis_table: False\n---\nhalf a sen",
            _native({"is_table": "False"}),
            warnings=("arena.semantic_error_class=OUTPUT_TRUNCATED",),
        )
    )
    assert result.lossy is True
    assert result.markdown == "half a sen"


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


def test_bootstrap_carries_an_architecture_preflight_olmocr2() -> None:
    from incident_checks import assert_architecture_preflight

    assert_architecture_preflight("olmocr2")


def test_the_preflight_names_this_checkpoints_architecture_olmocr2() -> None:
    """A preflight that does not name what it expects would pass on any checkpoint."""
    from incident_checks import read_runtime_script

    text = read_runtime_script("olmocr2", "bootstrap.sh")
    assert 'EXPECTED_MODEL_TYPE = "qwen2_5_vl"' in text
    assert 'EXPECTED_ARCH = "Qwen2_5_VLForConditionalGeneration"' in text
    assert "CONFIG_MAPPING_NAMES" in text
    assert "ModelRegistry.get_supported_archs()" in text


def test_the_framework_floor_audit_is_recorded_olmocr2() -> None:
    """D: the audit result lives in provenance.json, and runtime.json's notes say so.

    It is not a top-level runtime.json field because runtime.schema.json is
    ``additionalProperties: false`` and belongs to another lane; loosening that
    schema to hold an audit record would be the wrong fix.
    """
    import json

    from incident_checks import load_runtime_json, runtime_dir

    provenance = json.loads(
        (runtime_dir("olmocr2") / "provenance.json").read_text(encoding="utf-8")
    )
    audit = provenance["framework_floor_audit"]
    for field in ("required", "image_ships", "action", "evidence"):
        assert audit[field], f"framework_floor_audit.{field} is empty"
    assert all(url.startswith("https://") for url in audit["evidence"])
    notes = load_runtime_json("olmocr2")["notes"]
    joined = " ".join(notes) if isinstance(notes, list) else notes
    assert "framework_floor_audit" in joined


def test_entrypoint_makes_a_model_server_failure_sticky_olmocr2() -> None:
    """Exiting is what RunPod restarts, so a start failure holds the container."""
    from incident_checks import assert_sticky_model_server_failure

    assert_sticky_model_server_failure("olmocr2")
