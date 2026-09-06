"""The model identity chain must reach every failure state it claims.

Three layers are deliberately kept apart, because collapsing them is how a
programme convinces itself it pinned something it did not: the source register
carries *family* evidence (a model card), the candidate registry carries the
**expected exact revision**, and the attestation carries the identity that
**actually executed**.

A model card without a revision is not evidence that nothing was pinned. This
repository does pin one, in `benchmark/v6/candidate-registry.yaml`; what is
missing is the runtime qualification against it. The tests below hold that
distinction in place, and hold apart two states that call for opposite actions:
`MODEL_RUNTIME_NOT_READY` means build the runtime, `MODEL_IDENTITY_MISMATCH`
means something ran that should not have.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load(relative: str, name: str) -> Any:
    path = ROOT / relative
    if not path.exists():
        pytest.skip(f"{relative} is not present")
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def identity() -> Any:
    return load(
        "research/experiments/H1-W6-SAME-INTELLIGENCE-01/scripts/model_identity_v8.py",
        "t_model_identity_v8")


def registry(revision: str | None = "a" * 40, *, extra: bool = False) -> dict[str, Any]:
    candidates = [{
        "id": "qwen3.6-27b", "execution_state": "artifact_manifest_and_runtime_pending",
        "identity": {"repository": "Qwen/Qwen3.6-27B", "revision": revision},
        "conditions": [],
    }]
    if extra:
        candidates.append(dict(candidates[0]))
    return {"candidates": candidates}


def attestation(identity: Any, revision: str = "a" * 40) -> dict[str, Any]:
    payload = dict.fromkeys(identity.REQUIRED_ATTESTATION_FIELDS, "value")
    payload["checkpoint_revision"] = revision
    return payload


def test_the_shipped_identity_controls_separate(identity):
    assert identity.identity_controls()["separates"]


def test_the_expected_revision_is_read_from_the_candidate_registry(identity):
    """Not a constant in the gate: a copy would drift from the registry."""
    result = identity.expected_identity()
    assert result["state"] == "EXPECTED_REVISION_PINNED"
    assert result["source"] == "benchmark/v6/candidate-registry.yaml"
    assert len(result["expected_revision"]) == 40


def test_the_live_repository_pins_an_expected_revision(identity):
    """The distinction P0.2 names: a model card without a revision is not
    evidence that the programme pinned none."""
    assert identity.expected_identity()["expected_revision"]


def test_the_runtime_registry_is_not_yet_qualified_against_it(identity):
    """If this starts passing as QUALIFIED, the runtime was qualified --- which
    is progress, not a test failure; update it deliberately when that happens."""
    state = identity.runtime_registry_state()
    if state["state"] == "QUALIFIED":
        pytest.skip("the runtime registry has been qualified")
    assert state["state"] == "NOT_QUALIFIED"
    assert state["unqualified_fields"]


def test_a_matching_revision_reconciles(identity):
    result = identity.reconcile(attestation(identity),
                                expected=identity.expected_identity(registry()))
    assert result["state"] == "MODEL_IDENTITY_RECONCILED"
    assert result["may_proceed"]


def test_a_differing_revision_is_a_mismatch_and_refuses(identity):
    result = identity.reconcile(attestation(identity, "b" * 40),
                                expected=identity.expected_identity(registry()))
    assert result["state"] == "MODEL_IDENTITY_MISMATCH"
    assert not result["may_proceed"]
    assert "do NOT overwrite the candidate registry" in result["action"]


def test_an_absent_attestation_is_not_ready_rather_than_a_mismatch(identity):
    """Different states, because they call for different actions."""
    result = identity.reconcile(None, expected=identity.expected_identity(registry()))
    assert result["state"] == "MODEL_RUNTIME_NOT_READY"
    assert result["state"] != "MODEL_IDENTITY_MISMATCH"


@pytest.mark.parametrize("field", sorted([
    "checkpoint_revision", "model_file_manifest_sha256", "tokenizer_identity",
    "tokenizer_hash", "quantization", "serving_runtime", "serving_runtime_version",
    "runtime_image_digest", "model_attestation"]))
def test_every_attestation_field_is_required(identity, field):
    payload = attestation(identity)
    del payload[field]
    result = identity.reconcile(payload, expected=identity.expected_identity(registry()))
    assert result["state"] == "MODEL_RUNTIME_NOT_READY"
    assert field in result["missing_attestation_fields"]


def test_quantization_is_part_of_executed_identity(identity):
    """bf16 and a quantized load of the same checkpoint are different identities.

    The runtime registry records `quantization: review_required`, so this is an
    open field rather than a formality: pinning the revision while the served
    weights differ would make the chain look intact and be false.
    """
    assert "quantization" in identity.REQUIRED_ATTESTATION_FIELDS


def test_a_freeze_pinning_a_third_revision_is_a_mismatch(identity):
    """A freeze that agrees with neither registry is a lock on nothing."""
    result = identity.reconcile(attestation(identity),
                                expected=identity.expected_identity(registry()),
                                frozen_revision="c" * 40)
    assert result["state"] == "MODEL_IDENTITY_MISMATCH"


def test_a_registry_without_a_revision_is_ambiguous_not_reconciled(identity):
    result = identity.reconcile(attestation(identity),
                                expected=identity.expected_identity(registry(None)))
    assert result["state"] == "REGISTRY_AMBIGUOUS"


def test_a_duplicated_candidate_id_is_ambiguous(identity):
    """Two entries share the repository; matching on it alone would pick one."""
    result = identity.expected_identity(registry(extra=True))
    assert result["state"] == "REGISTRY_AMBIGUOUS"


def test_the_candidate_is_selected_by_id_not_by_repository(identity):
    """`qwen3.6-27b-page-parse` shares the repository and is a different candidate."""
    assert identity.CANDIDATE_ID == "qwen3.6-27b"
    assert identity.expected_identity()["candidate_id"] == "qwen3.6-27b"


def test_no_fallback_is_permitted_for_w6(identity):
    """The serving registry may declare one; W6 refuses it independently."""
    state = identity.runtime_registry_state()
    result = identity.fallback_is_forbidden_here(state)
    assert result["fallback_permitted_for_w6"] is False
    for forbidden in ("qwen3.5", "Gemma", "provider API", "session model"):
        assert forbidden in result["why"]


def test_the_refusal_does_not_depend_on_the_registry_declaring_no_fallback(identity):
    """It must refuse whether or not a fallback recipe happens to be declared."""
    with_recipe = identity.fallback_is_forbidden_here(
        {"declared_fallback_recipe": "knowledge_precision_v1"})
    without = identity.fallback_is_forbidden_here({"declared_fallback_recipe": None})
    assert with_recipe["fallback_permitted_for_w6"] is False
    assert without["fallback_permitted_for_w6"] is False
