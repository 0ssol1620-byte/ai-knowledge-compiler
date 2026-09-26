"""Unit tests for the Infinity-Parser2-Pro runtime (lane C3).

No GPU, no network, no torch/vllm/transformers. The adapter's HTTP transport is
replaced by a fake and the weights directory is a handful of small files with a
sidecar written by hand, exactly as ``fetch_weights.py`` would write it.
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
    CanonicalOutput,
    PageInput,
    RawOutput,
)

MODEL_KEY = "infinity_parser2_pro"
RUNTIME_DIR = Path(__file__).resolve().parents[2] / "runtimes" / MODEL_KEY


def _load(name: str) -> ModuleType:
    """Import a runtime module by path; runtimes are not a package on purpose."""
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
    """Records the payload it was handed and replays a scripted response."""

    def __init__(self, response: Mapping[str, Any] | None = None) -> None:
        self.response: Mapping[str, Any] = response if response is not None else _completion("{}")
        self.calls: list[Mapping[str, Any]] = []
        self.raises: Exception | None = None

    def chat(self, payload: Mapping[str, Any], timeout_s: float) -> Mapping[str, Any]:
        self.calls.append(payload)
        if self.raises is not None:
            raise self.raises
        return self.response

    def provenance(self) -> Mapping[str, Any]:
        return {"backend": "fake"}


def _completion(content: str, finish_reason: str = "stop") -> dict[str, Any]:
    return {
        "choices": [{"message": {"content": content}, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 22},
    }


@pytest.fixture
def weights_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "weights"
    directory.mkdir()
    largest = directory / "model-00006-of-00015.safetensors"
    largest.write_bytes(b"not really 32 GB")
    digest = "sha256:" + hashlib.sha256(largest.read_bytes()).hexdigest()
    (directory / adapter_mod.WEIGHTS_SIDECAR_NAME).write_text(
        json.dumps(
            {
                "repo": "infly/Infinity-Parser2-Pro",
                "revision": "b27d470100514329fc6439aada8f16ccea5f9e2a",
                "largest_file": largest.name,
                "largest_file_sha256": digest,
                "files_manifest_sha256": "sha256:" + "0" * 64,
                "cache_hit": True,
            }
        ),
        encoding="utf-8",
    )
    return directory


def _config(weights_dir: Path, **overrides: Any) -> AdapterConfig:
    inference_config: dict[str, Any] = {
        "endpoint": "http://127.0.0.1:8100/v1/chat/completions",
        "served_model_name": "infinity-parser2-pro",
        "max_tokens": 32768,
        "temperature": 0.0,
        "top_p": 1.0,
        "min_pixels": 2048,
        "max_pixels": 16777216,
        "chat_template_kwargs": {"enable_thinking": False},
        "hash_weights_on_load": False,
    }
    inference_config.update(overrides.pop("inference_config", {}))
    return AdapterConfig(
        model_key=MODEL_KEY,
        model_repo=overrides.pop("model_repo", "infly/Infinity-Parser2-Pro"),
        model_revision=overrides.pop(
            "model_revision", "b27d470100514329fc6439aada8f16ccea5f9e2a"
        ),
        weights_dir=weights_dir,
        prompt_id="infinity_parser2_pro_doc2json_v1",
        prompt_text=overrides.pop(
            "prompt_text", "- Extract layout information from the provided PDF image."
        ),
        inference_config=inference_config,
        inference_config_sha256="sha256:" + "1" * 64,
    )


def _page(tmp_path: Path) -> PageInput:
    image = tmp_path / "page.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n fake page bytes")
    return PageInput(
        inference_job_id="a" * 64,
        sample_id="omnidoc:images/PPT_1001115_eng_page_003",
        case_key="omnidocbench-58851882e7b39101a6f5756c",
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
    assert spec["model_key"] == MODEL_KEY
    assert spec["official_runtime"] in {"vllm", "transformers", "paddle", "mineru_cli", "custom"}
    assert spec["weights_strategy"] in {"baked", "volume_cache", "boot_download"}
    assert set(spec["runtime_mode_allowed"]) <= {"baked", "bootstrap"}


def test_runtime_json_pins_revision_and_base_image_by_digest() -> None:
    spec = json.loads((RUNTIME_DIR / "runtime.json").read_text(encoding="utf-8"))
    assert spec["model_revision"] == "b27d470100514329fc6439aada8f16ccea5f9e2a"
    assert len(spec["model_revision"]) == 40
    assert "@sha256:" in spec["base_image"]
    weights = spec["weights"]
    assert weights["repo"] == spec["model_repo"]
    assert weights["revision"] == spec["model_revision"]
    assert weights["largest_file_sha256"].startswith("sha256:")
    assert len(weights["largest_file_sha256"]) == len("sha256:") + 64


def test_license_is_verified_but_inf_mllm_is_still_named_as_unlicensed() -> None:
    """Founder decision 2026-09-03 verifies the CHECKPOINT's Apache-2.0 licence.

    The FTO rule still applies to the runtime wrapper repository: readable is not
    reusable. INF-MLLM's lack of a LICENSE file is unrelated to the checkpoint's
    licence and the note keeps naming it, because the design-around (no INF-MLLM
    code) still depends on that fact being true.
    """
    spec = json.loads((RUNTIME_DIR / "runtime.json").read_text(encoding="utf-8"))
    assert spec["license"]["status"] == "verified"
    assert spec["license"]["spdx_base"] == "Apache-2.0"
    assert spec["license"]["additional_terms"] is False
    notes = " ".join(spec["notes"])
    assert "INF-MLLM" in notes
    assert "NO LICENSE" in notes.upper()


def test_gpu_pools_are_80gb_class_and_tp_is_two() -> None:
    spec = json.loads((RUNTIME_DIR / "runtime.json").read_text(encoding="utf-8"))
    assert spec["gpu_min_vram_gb"] >= 160
    assert spec["inference_config"]["tensor_parallel_size"] == 2
    assert all("A100" in pool or "H100" in pool for pool in spec["gpu_pool_priority"])


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
    assert imported.isdisjoint({"torch", "vllm", "transformers", "PIL", "numpy"})
    assert imported.isdisjoint(_module_level_imports(RUNTIME_DIR / "canonical.py") & {"torch"})


def test_adapter_satisfies_the_frozen_protocol() -> None:
    assert isinstance(adapter_mod.InfinityParser2ProAdapter(), ArenaModelAdapter)


# ------------------------------------------------------------------- load


def test_load_happy_path(weights_dir: Path) -> None:
    adapter = adapter_mod.InfinityParser2ProAdapter(FakeBackend())
    receipt = adapter.load(_config(weights_dir))
    assert receipt.model_revision == "b27d470100514329fc6439aada8f16ccea5f9e2a"
    assert receipt.cache_hit is True
    assert receipt.weights_sha256_manifest == "sha256:" + "0" * 64


def test_load_reports_unverified_when_no_manifest_and_no_deep_hash(weights_dir: Path) -> None:
    """A missing digest is stated, never faked."""
    sidecar = weights_dir / adapter_mod.WEIGHTS_SIDECAR_NAME
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    del payload["files_manifest_sha256"]
    sidecar.write_text(json.dumps(payload), encoding="utf-8")
    adapter = adapter_mod.InfinityParser2ProAdapter(FakeBackend())
    receipt = adapter.load(_config(weights_dir))
    assert receipt.weights_sha256_manifest.startswith("unverified:")


def test_load_deep_hash_produces_a_real_manifest(weights_dir: Path) -> None:
    adapter = adapter_mod.InfinityParser2ProAdapter(FakeBackend())
    receipt = adapter.load(
        _config(weights_dir, inference_config={"hash_weights_on_load": True})
    )
    assert receipt.weights_sha256_manifest.startswith("sha256:")
    assert receipt.weights_sha256_manifest != "sha256:" + "0" * 64


def test_load_rejects_a_revision_mismatch(weights_dir: Path) -> None:
    adapter = adapter_mod.InfinityParser2ProAdapter(FakeBackend())
    with pytest.raises(AdapterError) as caught:
        adapter.load(_config(weights_dir, model_revision="0" * 40))
    assert caught.value.error_class == "MODEL_LOAD"


def test_load_rejects_a_checksum_mismatch(weights_dir: Path) -> None:
    (weights_dir / "model-00006-of-00015.safetensors").write_bytes(b"tampered")
    adapter = adapter_mod.InfinityParser2ProAdapter(FakeBackend())
    with pytest.raises(AdapterError) as caught:
        adapter.load(_config(weights_dir))
    assert caught.value.error_class == "CHECKSUM"


def test_load_rejects_a_missing_sidecar(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    adapter = adapter_mod.InfinityParser2ProAdapter(FakeBackend())
    with pytest.raises(AdapterError) as caught:
        adapter.load(_config(empty))
    assert caught.value.error_class == "MODEL_LOAD"


def test_load_rejects_a_different_repository(weights_dir: Path) -> None:
    adapter = adapter_mod.InfinityParser2ProAdapter(FakeBackend())
    with pytest.raises(AdapterError) as caught:
        adapter.load(_config(weights_dir, model_repo="infly/Infinity-Parser2-Flash"))
    assert caught.value.error_class == "MODEL_LOAD"


def test_infer_before_load_is_refused(tmp_path: Path) -> None:
    adapter = adapter_mod.InfinityParser2ProAdapter(FakeBackend())
    with pytest.raises(AdapterError) as caught:
        adapter.infer(_page(tmp_path))
    assert caught.value.error_class == "MODEL_LOAD"


def test_http_backend_refuses_a_non_loopback_endpoint() -> None:
    with pytest.raises(AdapterError) as caught:
        adapter_mod.HttpChatBackend("https://example.com/v1", served_model_name="x")
    assert caught.value.error_class == "DEPENDENCY"


# ------------------------------------------------------------------ infer


def test_infer_sends_the_official_sampling_values(weights_dir: Path, tmp_path: Path) -> None:
    backend = FakeBackend(_completion(json.dumps({"elements": []})))
    adapter = adapter_mod.InfinityParser2ProAdapter(backend)
    adapter.load(_config(weights_dir))
    adapter.infer(_page(tmp_path))
    payload = backend.calls[0]
    assert payload["max_tokens"] == 32768
    assert payload["temperature"] == 0.0
    assert payload["top_p"] == 1.0
    assert payload["chat_template_kwargs"] == {"enable_thinking": False}
    image_part = payload["messages"][0]["content"][0]
    assert image_part["min_pixels"] == 2048
    assert image_part["max_pixels"] == 16777216
    assert image_part["image_url"]["url"].startswith("data:image/png;base64,")
    assert payload["messages"][0]["content"][1]["text"].startswith("- Extract layout")


def test_infer_parses_the_doc2json_envelope(weights_dir: Path, tmp_path: Path) -> None:
    content = json.dumps(
        {"elements": [{"category": "title", "bbox": [0, 0, 10, 10], "text": "# Heading"}]}
    )
    adapter = adapter_mod.InfinityParser2ProAdapter(FakeBackend(_completion(content)))
    adapter.load(_config(weights_dir))
    raw = adapter.infer(_page(tmp_path))
    assert raw.output_format == "json"
    assert raw.native_json is not None
    assert raw.raw_text == content
    assert raw.usage["completion_tokens"] == 22


def test_infer_tolerates_a_json_fence_without_editing_raw_text(
    weights_dir: Path, tmp_path: Path
) -> None:
    content = '```json\n{"elements": []}\n```'
    adapter = adapter_mod.InfinityParser2ProAdapter(FakeBackend(_completion(content)))
    adapter.load(_config(weights_dir))
    raw = adapter.infer(_page(tmp_path))
    assert raw.native_json == {"elements": []}
    assert raw.raw_text == content, "raw_text must stay byte-identical to the model output"


def test_infer_flags_prose_instead_of_json(weights_dir: Path, tmp_path: Path) -> None:
    adapter = adapter_mod.InfinityParser2ProAdapter(FakeBackend(_completion("Just some text.")))
    adapter.load(_config(weights_dir))
    raw = adapter.infer(_page(tmp_path))
    assert raw.output_format == "markdown"
    assert any("did not return a JSON object" in w for w in raw.warnings)


def test_infer_flags_truncation_but_keeps_the_bytes(weights_dir: Path, tmp_path: Path) -> None:
    adapter = adapter_mod.InfinityParser2ProAdapter(
        FakeBackend(_completion('{"elements": [', finish_reason="length"))
    )
    adapter.load(_config(weights_dir))
    raw = adapter.infer(_page(tmp_path))
    assert f"{adapter_mod.SEMANTIC_ERROR_PREFIX}OUTPUT_TRUNCATED" in raw.warnings
    assert raw.raw_text == '{"elements": ['
    assert raw.semantic_error_class == "OUTPUT_TRUNCATED"


def test_infer_flags_an_empty_response(weights_dir: Path, tmp_path: Path) -> None:
    adapter = adapter_mod.InfinityParser2ProAdapter(FakeBackend(_completion("   ")))
    adapter.load(_config(weights_dir))
    raw = adapter.infer(_page(tmp_path))
    assert f"{adapter_mod.SEMANTIC_ERROR_PREFIX}OUTPUT_EMPTY" in raw.warnings
    assert raw.semantic_error_class == "OUTPUT_EMPTY"


def test_infer_semantic_error_class_is_none_on_a_clean_response(
    weights_dir: Path, tmp_path: Path
) -> None:
    adapter = adapter_mod.InfinityParser2ProAdapter(
        FakeBackend(_completion('{"elements": [{"category": "text", "text": "hi"}]}'))
    )
    adapter.load(_config(weights_dir))
    raw = adapter.infer(_page(tmp_path))
    assert raw.semantic_error_class is None


def test_infer_rejects_a_malformed_response(weights_dir: Path, tmp_path: Path) -> None:
    adapter = adapter_mod.InfinityParser2ProAdapter(FakeBackend({"choices": []}))
    adapter.load(_config(weights_dir))
    with pytest.raises(AdapterError) as caught:
        adapter.infer(_page(tmp_path))
    assert caught.value.error_class == "OUTPUT_MALFORMED"


def test_infer_rejects_an_unreadable_page(weights_dir: Path, tmp_path: Path) -> None:
    adapter = adapter_mod.InfinityParser2ProAdapter(FakeBackend())
    adapter.load(_config(weights_dir))
    page = _page(tmp_path)
    page.image_path.write_bytes(b"")
    with pytest.raises(AdapterError) as caught:
        adapter.infer(page)
    assert caught.value.error_class == "INPUT_DECODE"


def test_repetition_is_classified() -> None:
    degenerate = "\n".join(["the same long line repeated"] * 30)
    assert adapter_mod.classify_output(degenerate) == "OUTPUT_REPETITION"
    assert adapter_mod.classify_output("a real page of text") is None


# ------------------------------------------------------------- canonical


def _raw(native: Mapping[str, Any] | None, text: str = "", **kwargs: Any) -> RawOutput:
    return RawOutput(
        raw_text=text,
        output_format="json" if native is not None else "markdown",
        native_json=native,
        usage={},
        timings_ms={"preprocess_ms": 0, "inference_ms": 0, "postprocess_ms": 0},
        warnings=tuple(kwargs.pop("warnings", ())),
    )


def test_canonicalize_orders_heading_table_and_formula() -> None:
    native = {
        "elements": [
            {"category": "title", "bbox": [0, 0, 1, 1], "text": "# Quarterly Results"},
            {"category": "text", "bbox": [0, 2, 1, 3], "text": "Revenue grew."},
            {
                "category": "table",
                "bbox": [0, 4, 1, 5],
                "text": "<table><tr><td>1</td></tr></table>",
            },
            {"category": "formula", "bbox": [0, 6, 1, 7], "text": "E = mc^2"},
        ]
    }
    result = canonical_mod.canonicalize(_raw(native))
    assert isinstance(result, CanonicalOutput)
    assert result.lossy is False
    assert result.markdown.splitlines()[0] == "# Quarterly Results"
    assert "<table>" in result.markdown
    assert "$$\nE = mc^2\n$$" in result.markdown
    assert result.elements is not None
    assert len(result.elements) == 4


def test_canonicalize_does_not_double_wrap_a_formula() -> None:
    native = {"elements": [{"category": "formula", "text": "$$x^2$$"}]}
    result = canonical_mod.canonicalize(_raw(native))
    assert result.markdown == "$$x^2$$"


def test_canonicalize_drops_no_content_for_textless_figures() -> None:
    native = {
        "elements": [
            {"category": "figure", "bbox": [0, 0, 1, 1], "text": ""},
            {"category": "figure_caption", "bbox": [0, 2, 1, 3], "text": "Figure 1."},
        ]
    }
    result = canonical_mod.canonicalize(_raw(native))
    assert result.markdown == "Figure 1."
    assert result.elements is not None
    assert len(result.elements) == 2, "the figure element is recorded even with no text"
    assert any("figure element" in note for note in result.conversion_notes)


def test_canonicalize_empty_output_is_lossless_and_flagged() -> None:
    raw = _raw({"elements": []}, warnings=("arena.semantic_error_class=OUTPUT_EMPTY",))
    result = canonical_mod.canonicalize(raw)
    assert result.markdown == ""
    assert result.lossy is True


def test_canonicalize_truncated_output_is_marked_lossy() -> None:
    raw = _raw(
        {"elements": [{"category": "text", "text": "half a sen"}]},
        text="half a sen",
        warnings=("arena.semantic_error_class=OUTPUT_TRUNCATED",),
    )
    result = canonical_mod.canonicalize(raw)
    assert result.lossy is True
    assert result.markdown == "half a sen"


def test_canonicalize_falls_back_to_raw_text_when_json_is_absent() -> None:
    raw = _raw(None, text="plain prose the model returned")
    result = canonical_mod.canonicalize(raw)
    assert result.markdown == "plain prose the model returned"
    assert result.lossy is True
    assert result.elements is None


def test_canonicalize_reports_unknown_categories_without_remapping() -> None:
    native = {"elements": [{"category": "sidebar", "text": "note"}]}
    result = canonical_mod.canonicalize(_raw(native))
    assert result.elements is not None
    assert result.elements[0]["category"] == "sidebar"
    assert any("outside the model card's list" in n for n in result.conversion_notes)


# ------------------------------------------------------------ D34 prompt kind


def test_runtime_json_declares_the_kind_the_adapter_implements() -> None:
    spec = json.loads((RUNTIME_DIR / "runtime.json").read_text(encoding="utf-8"))
    assert spec["prompt_kind"] == "text"
    assert spec["prompt_kind"] == adapter_mod.PROMPT_KIND


def test_the_registry_file_exists_and_is_not_empty() -> None:
    """prompt_kind=text has no fallback: an absent or empty file is a dead runtime."""
    registry_dir = Path(__file__).resolve().parents[2] / "prompt_registry"
    spec = json.loads((RUNTIME_DIR / "runtime.json").read_text(encoding="utf-8"))
    prompt_file = registry_dir / f"{spec['prompt_id']}.txt"
    assert prompt_file.is_file(), f"D17: {prompt_file.name} must exist"
    raw = prompt_file.read_bytes()
    assert raw.strip(), "prompt_kind=text with an empty registry file cannot run"
    recorded = json.loads((registry_dir / "sha256.json").read_text(encoding="utf-8"))
    assert recorded[spec["prompt_id"]] == "sha256:" + hashlib.sha256(raw).hexdigest()


def test_the_registry_text_is_what_goes_on_the_wire(weights_dir: Path, tmp_path: Path) -> None:
    """prompt_kind=text: AdapterConfig.prompt_text is sent verbatim, not a copy."""
    backend = FakeBackend(_completion("{}"))
    adapter = adapter_mod.InfinityParser2ProAdapter(backend)
    adapter.load(_config(weights_dir, prompt_text="doc2json please"))
    adapter.infer(_page(tmp_path))
    content = backend.calls[-1]["messages"][0]["content"]
    text_parts = [part["text"] for part in content if part["type"] == "text"]
    assert text_parts == ["doc2json please"]


@pytest.mark.parametrize("empty", ["", "   \n\t"])
def test_load_refuses_an_empty_prompt(weights_dir: Path, empty: str) -> None:
    adapter = adapter_mod.InfinityParser2ProAdapter(FakeBackend())
    with pytest.raises(AdapterError) as caught:
        adapter.load(_config(weights_dir, prompt_text=empty))
    assert caught.value.error_class == "MODEL_LOAD"
    assert "prompt_kind=text" in str(caught.value)


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


def test_bootstrap_carries_an_architecture_preflight_infinity_parser2_pro() -> None:
    from incident_checks import assert_architecture_preflight

    assert_architecture_preflight("infinity_parser2_pro")


def test_the_preflight_names_this_checkpoints_architecture_infinity_parser2_pro() -> None:
    """A preflight that does not name what it expects would pass on any checkpoint."""
    from incident_checks import read_runtime_script

    text = read_runtime_script("infinity_parser2_pro", "bootstrap.sh")
    assert 'EXPECTED_MODEL_TYPE = "qwen3_5_moe"' in text
    assert 'EXPECTED_ARCH = "Qwen3_5MoeForConditionalGeneration"' in text
    # vllm issue #36236: a transformers-5-saved Qwen3.5-MoE config names its nested
    # text config qwen3_5_moe_text, which vLLM lines before 0.17.1 rejected at load
    assert 'EXPECTED_TEXT_MODEL_TYPE = "qwen3_5_moe_text"' in text
    assert "vllm.transformers_utils.configs import qwen3_5_moe" in text
    assert "ModelRegistry.get_supported_archs()" in text


def test_the_framework_floor_audit_is_recorded_infinity_parser2_pro() -> None:
    """D: the audit result lives in provenance.json, and runtime.json's notes say so.

    It is not a top-level runtime.json field because runtime.schema.json is
    ``additionalProperties: false`` and belongs to another lane; loosening that
    schema to hold an audit record would be the wrong fix.
    """
    import json

    from incident_checks import load_runtime_json, runtime_dir

    provenance = json.loads(
        (runtime_dir("infinity_parser2_pro") / "provenance.json").read_text(encoding="utf-8")
    )
    audit = provenance["framework_floor_audit"]
    for field in ("required", "image_ships", "action", "evidence"):
        assert audit[field], f"framework_floor_audit.{field} is empty"
    assert all(url.startswith("https://") for url in audit["evidence"])
    notes = load_runtime_json("infinity_parser2_pro")["notes"]
    joined = " ".join(notes) if isinstance(notes, list) else notes
    assert "framework_floor_audit" in joined


def test_entrypoint_makes_a_model_server_failure_sticky_infinity_parser2_pro() -> None:
    """Exiting is what RunPod restarts, so a start failure holds the container."""
    from incident_checks import assert_sticky_model_server_failure

    assert_sticky_model_server_failure("infinity_parser2_pro")
