from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import jsonschema
import pytest

from benchmark.v6.contracts import ContractError, EnvironmentIdentity
from benchmark.v6.registry import CandidateRegistry


def test_registry_covers_every_mandatory_parser_and_compiler_fail_closed(
    repo_root: Path,
) -> None:
    registry = CandidateRegistry.load(repo_root / "benchmark/v6/candidate-registry.yaml")

    assert registry.schema_version == "6.0.0"
    assert len(registry.required_ids) == 28
    assert {
        "mineru-3.4.4-pipeline",
        "paddleocr-vl-1.6",
        "deepseek-ocr-2",
        "infinity-parser2-pro",
        "ovisocr2",
        "hunyuanocr-1.5",
        "glm-ocr",
        "native-authority-lane",
        "qwen3.6-27b",
        "codex-gpt-5.6-sol",
    }.issubset(set(registry.required_ids))
    assert registry.externally_blocked_required_ids == registry.required_ids
    assert all(
        not registry.get(candidate_id).promotion_eligible for candidate_id in registry.required_ids
    )
    assert sum(registry.get(item).model_revision_pinned for item in registry.required_ids) == 18
    assert registry.get("paddleocr-vl-1.6").revision == ("66317acc4c9fc17bd154591ce650735cd2855f3e")
    assert registry.get("deepseek-ocr-2").license_status == "approved"
    assert registry.get("hunyuanocr-1.5").license_status == "review_required"
    assert registry.get("chandra-ocr-2").license_status == "review_required"


def test_environment_identity_is_canonical_and_every_field_is_binding(
    environment: EnvironmentIdentity,
) -> None:
    first = environment.environment_sha256
    reordered = EnvironmentIdentity.from_mapping(
        {
            **environment.to_dict(),
            "framework_versions": {"vllm": "0.10.2", "torch": "2.8.0"},
        }
    )
    changed = replace(environment, gpu_class="H100_80GB")

    assert reordered.environment_sha256 == first
    assert changed.environment_sha256 != first
    assert environment.to_dict()["ground_truth_mounted_for_inference"] is False


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("model_revision", "main", "mutable alias"),
        ("runtime_image_digest", "latest", "exact sha256"),
        ("evaluator_commit", "unknown", "exact 40- or 64-hex"),
        ("ground_truth_mounted_for_inference", True, "ground truth"),
    ],
)
def test_environment_identity_rejects_mutable_or_leaky_values(
    environment: EnvironmentIdentity,
    field: str,
    value: object,
    message: str,
) -> None:
    with pytest.raises(ContractError, match=message):
        EnvironmentIdentity.from_mapping({**environment.to_dict(), field: value})


def test_environment_schema_accepts_runtime_identity(
    repo_root: Path,
    environment: EnvironmentIdentity,
) -> None:
    schema = json.loads(
        (repo_root / "benchmark/v6/schemas/environment-identity.schema.json").read_text(
            encoding="utf-8"
        )
    )
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(environment.to_dict(), schema)
