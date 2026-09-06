"""Schema and structural validation, including every rule that must go red."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from arena.constants import BENCHMARK_KEYS, MODEL_KEYS
from arena.registry.errors import SchemaValidationError
from arena.registry.evaluators import (
    EVALUATOR_REPOSITORIES,
    OBSERVED_HEADS,
    OLMOCR_TOOLKIT_REPOSITORY,
    RecordedGitRefResolver,
    resolve_evaluators,
)
from arena.registry.serialize import write_json_atomic
from arena.registry.validate import (
    EVALUATOR_SCHEMA_NAME,
    MODEL_SCHEMA_NAME,
    choose_schema,
    structural_evaluator_errors,
    structural_model_errors,
    validate_evaluator_registry,
    validate_model_registry,
)


def _evaluator_document() -> dict[str, Any]:
    heads = {url: OBSERVED_HEADS[key] for key, url in EVALUATOR_REPOSITORIES.items()}
    heads[OLMOCR_TOOLKIT_REPOSITORY] = OBSERVED_HEADS["_olmocr_toolkit"]
    return resolve_evaluators(RecordedGitRefResolver(heads))


def _minimal_model_record(model_key: str) -> dict[str, Any]:
    return {
        "schema": "tavonel.arena.model-registry-record.v1",
        "model_key": model_key,
        "display_name": model_key,
        "repo": "owner/name",
        "revision": "a" * 40,
        "weights": {
            "repo": "owner/name",
            "revision": "a" * 40,
            "largest_file": "model.safetensors",
            "largest_file_sha256": "sha256:" + "b" * 64,
            "size_bytes": 1,
        },
        "license": "mit",
        "license_detail": {
            "id": "mit",
            "url": "https://huggingface.co/owner/name",
            "status": "approved",
            "notes": "note",
        },
        "license_status": "approved",
        "license_evidence_url": "https://huggingface.co/owner/name",
        "license_notes": "note",
        "runtime_type": "vllm",
        "runtime_version": "vllm==1.0.0",
        "container_image": None,
        "container_digest": None,
        "cuda": None,
        "torch": None,
        "gpu_min_vram_gb": 24,
        "gpu_min_vram_gb_detail": {"value": 24, "estimated": True, "basis": "test"},
        "prompt_id": f"{model_key}_official_v1",
        "official_prompt_id": f"{model_key}_official_v1",
        "preprocess_config_id": f"{model_key}_official_preprocess_v1",
        "official_inference_config": {},
        "official_inference_config_sha256": "sha256:" + "c" * 64,
        "max_concurrency_per_worker": 1,
        "concurrency_policy": {"per_worker": 1, "scale": "replicas_only"},
        "concurrency_plan": {"scale_after_canary": "replicas_only", "reason": "test"},
        "recommended_gpu_pool": ["NVIDIA GeForce RTX 4090"],
        "gpu_pool_priority": ["NVIDIA GeForce RTX 4090"],
        "shard_size_hint": 100,
        "shard_size_hint_basis": "test",
        "code_repositories": [],
        "unresolved": [],
        "weights_strategy": "baked",
        "runtime_mode_allowed": ["baked"],
        "official_source_urls": ["https://huggingface.co/owner/name"],
        "resolved_at": "2026-09-03T00:00:00Z",
        "resolution_method": "test",
        "canary_status": "PENDING",
        "full_run_eligible": False,
        "historical_evidence": None,
        "previous_registry_revision": None,
        "revision_changed_since_2026_08": None,
    }


def _model_document() -> dict[str, Any]:
    models = {key: _minimal_model_record(key) for key in MODEL_KEYS}
    models["opus5_subscription"]["runtime_type"] = "subscription"
    models["opus5_subscription"]["runtime_mode_allowed"] = ["subscription"]
    models["opus5_subscription"]["revision"] = "claude-opus-5 (confirm via lane D probe)"
    models["opus5_subscription"]["weights"] = None
    models["opus5_subscription"]["repo"] = None
    models["opus5_subscription"]["gpu_min_vram_gb"] = None
    models["opus5_subscription"]["gpu_min_vram_gb_detail"] = {
        "value": None,
        "estimated": False,
        "basis": "not applicable",
    }
    return {"schema": "tavonel.arena.model-registry.v1", "models": models}


# --------------------------------------------------------------------------
# Schema selection.
# --------------------------------------------------------------------------


def test_schema_selection_names_the_file_it_used() -> None:
    for name in (MODEL_SCHEMA_NAME, EVALUATOR_SCHEMA_NAME):
        choice = choose_schema(name)
        assert choice.path.is_file()
        assert choice.source in ("arena/core/schemas", "arena/registry/fallback_schemas")


def test_missing_registry_file_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(SchemaValidationError, match="does not exist"):
        validate_model_registry(tmp_path / "model_registry.json")


# --------------------------------------------------------------------------
# Happy path.
# --------------------------------------------------------------------------


def test_a_well_formed_pair_validates(tmp_path: Path) -> None:
    write_json_atomic(tmp_path / "model_registry.json", _model_document())
    write_json_atomic(tmp_path / "evaluator_registry.json", _evaluator_document())
    model_report = validate_model_registry(tmp_path / "model_registry.json")
    evaluator_report = validate_evaluator_registry(tmp_path / "evaluator_registry.json")
    assert model_report.ok, model_report.render()
    assert evaluator_report.ok, evaluator_report.render()
    assert model_report.record_count == len(MODEL_KEYS)
    assert evaluator_report.record_count == len(BENCHMARK_KEYS)
    assert model_report.render().startswith("OK")


# --------------------------------------------------------------------------
# Structural rules that must go red.
# --------------------------------------------------------------------------


def test_missing_model_record_is_reported() -> None:
    document = _model_document()
    document["models"].pop("glm_ocr")
    assert any("missing records" in error for error in structural_model_errors(document))


def test_unknown_model_key_is_reported() -> None:
    document = _model_document()
    document["models"]["not_a_candidate"] = _minimal_model_record("not_a_candidate")
    errors = structural_model_errors(document)
    assert any("outside arena.constants.MODEL_KEYS" in error for error in errors)


def test_non_hex_gpu_revision_is_reported() -> None:
    document = _model_document()
    document["models"]["glm_ocr"]["revision"] = "main"
    assert any("not a 40-hex" in error for error in structural_model_errors(document))


def test_full_run_eligible_true_is_reported() -> None:
    document = _model_document()
    document["models"]["glm_ocr"]["full_run_eligible"] = True
    errors = structural_model_errors(document)
    assert any("full_run_eligible must stay false" in error for error in errors)


def test_pre_set_canary_status_is_reported() -> None:
    document = _model_document()
    document["models"]["glm_ocr"]["canary_status"] = "PASS"
    errors = structural_model_errors(document)
    assert any("canary_status must be PENDING" in error for error in errors)


def test_unknown_gpu_type_id_is_reported() -> None:
    document = _model_document()
    document["models"]["glm_ocr"]["gpu_pool_priority"] = ["NVIDIA MADE UP 9000"]
    errors = structural_model_errors(document)
    assert any("outside the catalog" in error for error in errors)


def test_empty_gpu_pool_is_reported() -> None:
    document = _model_document()
    document["models"]["glm_ocr"]["gpu_pool_priority"] = []
    errors = structural_model_errors(document)
    assert any("gpu_pool_priority is empty" in error for error in errors)


def test_mineru_vlm_concurrency_regression_is_reported() -> None:
    document = _model_document()
    document["models"]["mineru_vlm"]["concurrency_policy"] = {
        "per_worker": 3,
        "scale": "replicas_only",
    }
    document["models"]["mineru_vlm"]["max_concurrency_per_worker"] = 3
    errors = structural_model_errors(document)
    assert any("masterplan section 14" in error for error in errors)
    assert len([error for error in errors if "masterplan section 14" in error]) == 2


def test_opus_runtime_type_regression_is_reported() -> None:
    document = _model_document()
    document["models"]["opus5_subscription"]["runtime_type"] = "vllm"
    errors = structural_model_errors(document)
    assert any("must be 'subscription'" in error for error in errors)


def test_moved_pin_without_a_historical_lane_is_reported() -> None:
    document = _evaluator_document()
    document["evaluators"]["parsebench"]["historical_lane_required"] = False
    errors = structural_evaluator_errors(document)
    assert any("historical_lane_required must be true" in error for error in errors)


def test_pin_that_was_not_the_verified_head_is_reported() -> None:
    document = _evaluator_document()
    document["evaluators"]["omnidoc"]["main_pin"] = "f" * 40
    errors = structural_evaluator_errors(document)
    assert any("neither the verified upstream head" in error for error in errors)


def test_keeping_the_historical_pin_is_allowed_when_it_is_argued() -> None:
    document = _evaluator_document()
    record = document["evaluators"]["parsebench"]
    record["main_pin"] = record["historical_pin"]
    errors = structural_evaluator_errors(document)
    assert not any("neither the verified upstream head" in error for error in errors)


def test_a_pin_without_a_written_rationale_is_reported() -> None:
    document = _evaluator_document()
    document["evaluators"]["omnidoc"]["main_pin_rationale"] = "looks fine"
    errors = structural_evaluator_errors(document)
    assert any("main_pin_rationale is missing or too short" in error for error in errors)


def test_gt_path_outside_the_acquired_tree_is_reported() -> None:
    document = _evaluator_document()
    document["evaluators"]["omnidoc"]["gt_paths"].append(
        "benchmark/datasets/staged-public-core/omnidocbench/inputs"
    )
    errors = structural_evaluator_errors(document)
    assert any("outside the acquired ground-truth tree" in error for error in errors)


def test_schema_violation_is_reported_separately_from_structure(tmp_path: Path) -> None:
    document = _model_document()
    document["models"]["glm_ocr"]["official_inference_config_sha256"] = "not-a-hash"
    path = tmp_path / "model_registry.json"
    write_json_atomic(path, document)
    report = validate_model_registry(path)
    assert not report.ok
    assert any("glm_ocr" in error for error in report.schema_errors)
    assert report.render().startswith("FAIL")


def test_written_file_is_sorted_two_space_indented_with_a_trailing_newline(
    tmp_path: Path,
) -> None:
    path = tmp_path / "model_registry.json"
    write_json_atomic(path, {"b": 1, "a": {"z": 2, "y": 3}})
    text = path.read_text(encoding="utf-8")
    assert text.endswith("}\n")
    assert text.splitlines()[1].startswith('  "a"')
    assert list(json.loads(text)) == ["a", "b"]
    assert not list(tmp_path.glob("*.tmp"))


def test_deep_copy_of_a_document_does_not_leak_between_checks() -> None:
    document = _model_document()
    snapshot = copy.deepcopy(document)
    structural_model_errors(document)
    assert document == snapshot
