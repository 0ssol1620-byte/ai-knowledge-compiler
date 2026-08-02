from __future__ import annotations

from pathlib import Path

import pytest

from benchmark.v6.contracts import EnvironmentIdentity
from benchmark.v6.registry import CandidateSpec


def sha(character: str) -> str:
    return "sha256:" + character * 64


@pytest.fixture
def environment() -> EnvironmentIdentity:
    return EnvironmentIdentity(
        application_commit="a" * 40,
        source_tree_sha256=sha("b"),
        candidate_id="candidate-ready",
        model_repository="org/model",
        model_revision="c" * 40,
        model_manifest_sha256=sha("d"),
        runtime_image_digest=sha("e"),
        gpu_class="A100_80GB",
        gpu_count=2,
        driver_version="575.51.03",
        cuda_version="12.8",
        framework_versions={"torch": "2.8.0", "vllm": "0.10.2"},
        prompt_sha256=sha("f"),
        decoding_sha256=sha("1"),
        dataset_id="parsebench",
        dataset_revision="dataset-2026-07-27+2805a1d9",
        dataset_manifest_sha256=sha("2"),
        evaluator_repository="run-llama/ParseBench",
        evaluator_commit="3" * 40,
        evaluator_manifest_sha256=sha("4"),
        network_policy_sha256=sha("5"),
    )


@pytest.fixture
def eligible_candidate() -> CandidateSpec:
    return CandidateSpec.from_mapping(
        {
            "id": "candidate-ready",
            "tier": "A",
            "kind": "parser",
            "role": "measured_candidate",
            "required": True,
            "execution_state": "external_run_complete",
            "promotion_eligible": True,
            "identity": {
                "repository": "org/model",
                "revision": "a" * 40,
                "artifact_sha256": sha("b"),
                "runtime_recipe": "infra/runpod/v6/recipes/candidate-ready",
            },
            "license": {
                "id": "Apache-2.0",
                "status": "approved",
                "commercial_use": "allowed",
            },
            "conditions": [],
        }
    )


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]
