from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from recovery_protocol import (  # noqa: E402
    FROZEN,
    Arm,
    EvidenceSplit,
    FreshCohortAuthority,
    ModelPin,
    ProtocolRefused,
    RecoveryProtocol,
    authorize_development_cache_preparation,
    authorize_development_runtime_qualification,
    authorize_gpu_stage,
)

SHA_A = "sha256:" + "a" * 64
SHA_B = "sha256:" + "b" * 64
SHA_C = "sha256:" + "c" * 64
SHA_D = "sha256:" + "d" * 64
SHA_E = "sha256:" + "e" * 64


def pin(role: str, suffix: str) -> ModelPin:
    return ModelPin(
        role=role,
        model_id=f"model-{suffix}",
        model_revision=f"rev-{suffix}",
        runtime_id=f"runtime-{suffix}",
        runtime_digest=SHA_A if suffix == "a" else SHA_B,
        prompt_or_schema_digest=SHA_C if suffix == "a" else SHA_D,
    )


def ready_protocol() -> RecoveryProtocol:
    return RecoveryProtocol(
        model_pins=(
            pin("primary", "a"),
            pin("peer", "b"),
            pin("strong", "c"),
        ),
        cohort=FreshCohortAuthority(
            corpus_id="fresh-family-heldout-v1",
            source_manifest_digest=SHA_A,
            spent_manifest_digest=SHA_B,
            selection_rule_digest=SHA_C,
        ),
        evidence_split=EvidenceSplit(
            split_salt_digest=SHA_D,
            trigger_anchor_ids=("anchor-1", "anchor-3"),
            evaluation_anchor_ids=("anchor-2", "anchor-4"),
        ),
        calibration_manifest_digest=SHA_E,
        metadata={"purpose": "fresh confirmatory recovery"},
    )


def test_draft_contains_all_primary_arms_and_oracle_is_diagnostic_only() -> None:
    terms = RecoveryProtocol().terms()
    assert terms["primary_arms"] == [
        Arm.PRIMARY_ONLY.value,
        Arm.ALWAYS_STRONG.value,
        Arm.PREDICTION_ONLY.value,
        Arm.DISAGREEMENT_ONLY.value,
        Arm.TAVONEL_EVIDENCE_RECOVERY.value,
    ]
    assert terms["oracle_diagnostic"]["primary_inference"] is False
    assert terms["policies"]["confirmatory_labels_visible_to_runtime"] is False
    assert terms["policies"]["accept_only_improved_using_confirmatory_ground_truth"] is False
    qualification = terms["gpu_guardrails"]["development_runtime_qualification"]
    assert qualification == {
        "max_pages": 50,
        "max_gpu_seconds": 10_800.0,
        "max_external_cost_usd": 10.0,
        "spent_inputs_only": True,
        "fresh_cohort_must_remain_unopened": True,
    }
    cache = terms["gpu_guardrails"]["development_cache_preparation"]
    assert cache == {
        "fresh_confirmatory_pages": 0,
        "max_gpu_seconds": 14_400.0,
        "max_external_cost_usd": 10.0,
        "max_persistent_volume_gb": 60,
        "fresh_cohort_must_remain_unopened": True,
        "purpose": (
            "prepare exact pinned runtime/model bytes on persistent storage before runtime "
            "qualification; this lane contributes no confirmatory observation"
        ),
    }


def test_prefreeze_metadata_rejects_secret_like_fields_recursively() -> None:
    protocol = RecoveryProtocol(metadata={"runtime": {"api_token": "never-store-this"}})
    with pytest.raises(ProtocolRefused, match="secret-like"):
        protocol.validate_draft()


def test_prefreeze_metadata_rejects_outcome_like_fields_recursively() -> None:
    protocol = RecoveryProtocol(metadata={"notes": {"accuracy": 0.99}})
    with pytest.raises(ProtocolRefused, match="outcome-like"):
        protocol.validate_draft()


def test_evidence_split_must_keep_trigger_and_evaluation_truth_disjoint() -> None:
    split = EvidenceSplit(
        split_salt_digest=SHA_A,
        trigger_anchor_ids=("same",),
        evaluation_anchor_ids=("same",),
    )
    with pytest.raises(ProtocolRefused, match="overlaps"):
        split.validate()


def test_fresh_cohort_refuses_spent_family_overlap() -> None:
    cohort = FreshCohortAuthority(
        corpus_id="not-fresh",
        source_manifest_digest=SHA_A,
        spent_manifest_digest=SHA_B,
        selection_rule_digest=SHA_C,
        family_overlap_with_spent=True,
    )
    with pytest.raises(ProtocolRefused, match="overlaps spent"):
        cohort.validate_pre_open()


def test_ready_to_freeze_requires_complete_pins_and_authorities() -> None:
    ready_protocol().validate_ready_to_freeze()
    with pytest.raises(ProtocolRefused, match="model"):
        RecoveryProtocol().validate_ready_to_freeze()


def test_protocol_digest_is_deterministic() -> None:
    left = ready_protocol()
    right = ready_protocol()
    assert left.digest() == right.digest()
    assert left.digest().startswith("sha256:")


def test_gpu_is_impossible_before_freeze_cohort_seal_and_cpu_gate() -> None:
    with pytest.raises(ProtocolRefused, match="frozen"):
        authorize_gpu_stage(
            protocol_state="PRE_FREEZE_DRAFT",
            cohort_sealed=True,
            cpu_gate_green=True,
            stage=1,
            pages=100,
            estimated_gpu_seconds=1_000,
            estimated_external_cost_usd=5,
        )
    with pytest.raises(ProtocolRefused, match="sealed"):
        authorize_gpu_stage(
            protocol_state=FROZEN,
            cohort_sealed=False,
            cpu_gate_green=True,
            stage=1,
            pages=100,
            estimated_gpu_seconds=1_000,
            estimated_external_cost_usd=5,
        )
    with pytest.raises(ProtocolRefused, match="CPU"):
        authorize_gpu_stage(
            protocol_state=FROZEN,
            cohort_sealed=True,
            cpu_gate_green=False,
            stage=1,
            pages=100,
            estimated_gpu_seconds=1_000,
            estimated_external_cost_usd=5,
        )


def test_gpu_stage_caps_and_stage_order_are_hard_failures() -> None:
    assert (
        authorize_gpu_stage(
            protocol_state=FROZEN,
            cohort_sealed=True,
            cpu_gate_green=True,
            stage=1,
            pages=100,
            estimated_gpu_seconds=1_000,
            estimated_external_cost_usd=5,
        )
        == "STAGE1_GPU_AUTHORIZED"
    )
    with pytest.raises(ProtocolRefused, match="page cap"):
        authorize_gpu_stage(
            protocol_state=FROZEN,
            cohort_sealed=True,
            cpu_gate_green=True,
            stage=1,
            pages=301,
            estimated_gpu_seconds=1_000,
            estimated_external_cost_usd=5,
        )
    with pytest.raises(ProtocolRefused, match="Stage 1 GREEN"):
        authorize_gpu_stage(
            protocol_state=FROZEN,
            cohort_sealed=True,
            cpu_gate_green=True,
            stage=2,
            pages=500,
            estimated_gpu_seconds=5_000,
            estimated_external_cost_usd=20,
        )
    assert (
        authorize_gpu_stage(
            protocol_state=FROZEN,
            cohort_sealed=True,
            cpu_gate_green=True,
            stage=2,
            pages=500,
            estimated_gpu_seconds=5_000,
            estimated_external_cost_usd=20,
            prior_gpu_stage_green=True,
        )
        == "STAGE2_GPU_AUTHORIZED"
    )


def test_development_runtime_qualification_is_prefreeze_and_spent_only() -> None:
    assert (
        authorize_development_runtime_qualification(
            protocol_state="PRE_FREEZE_DRAFT",
            fresh_cohort_opened=False,
            spent_development_only=True,
            pages=18,
            gpu_seconds=1_000,
            external_cost_usd=5,
        )
        == "DEVELOPMENT_RUNTIME_QUALIFICATION_AUTHORIZED"
    )
    with pytest.raises(ProtocolRefused, match="pre-freeze"):
        authorize_development_runtime_qualification(
            protocol_state=FROZEN,
            fresh_cohort_opened=False,
            spent_development_only=True,
            pages=18,
            gpu_seconds=1_000,
            external_cost_usd=5,
        )
    with pytest.raises(ProtocolRefused, match="before fresh cohort"):
        authorize_development_runtime_qualification(
            protocol_state="PRE_FREEZE_DRAFT",
            fresh_cohort_opened=True,
            spent_development_only=True,
            pages=18,
            gpu_seconds=1_000,
            external_cost_usd=5,
        )
    with pytest.raises(ProtocolRefused, match="spent development"):
        authorize_development_runtime_qualification(
            protocol_state="PRE_FREEZE_DRAFT",
            fresh_cohort_opened=False,
            spent_development_only=False,
            pages=18,
            gpu_seconds=1_000,
            external_cost_usd=5,
        )


def test_development_runtime_qualification_caps_external_spend() -> None:
    with pytest.raises(ProtocolRefused, match="page cap"):
        authorize_development_runtime_qualification(
            protocol_state="PRE_FREEZE_DRAFT",
            fresh_cohort_opened=False,
            spent_development_only=True,
            pages=51,
            gpu_seconds=1_000,
            external_cost_usd=5,
        )
    with pytest.raises(ProtocolRefused, match="GPU-seconds cap"):
        authorize_development_runtime_qualification(
            protocol_state="PRE_FREEZE_DRAFT",
            fresh_cohort_opened=False,
            spent_development_only=True,
            pages=18,
            gpu_seconds=10_801,
            external_cost_usd=5,
        )
    with pytest.raises(ProtocolRefused, match="external-cost cap"):
        authorize_development_runtime_qualification(
            protocol_state="PRE_FREEZE_DRAFT",
            fresh_cohort_opened=False,
            spent_development_only=True,
            pages=18,
            gpu_seconds=1_000,
            external_cost_usd=10.01,
        )


def test_development_cache_preparation_is_prefreeze_and_zero_fresh_pages() -> None:
    assert (
        authorize_development_cache_preparation(
            protocol_state="PRE_FREEZE_DRAFT",
            fresh_cohort_opened=False,
            gpu_seconds=7_200,
            external_cost_usd=5,
            persistent_volume_gb=60,
        )
        == "DEVELOPMENT_CACHE_PREPARATION_AUTHORIZED"
    )
    with pytest.raises(ProtocolRefused, match="pre-freeze"):
        authorize_development_cache_preparation(
            protocol_state=FROZEN,
            fresh_cohort_opened=False,
            gpu_seconds=7_200,
            external_cost_usd=5,
            persistent_volume_gb=60,
        )
    with pytest.raises(ProtocolRefused, match="before fresh cohort"):
        authorize_development_cache_preparation(
            protocol_state="PRE_FREEZE_DRAFT",
            fresh_cohort_opened=True,
            gpu_seconds=7_200,
            external_cost_usd=5,
            persistent_volume_gb=60,
        )


def test_development_cache_preparation_caps_gpu_cost_and_volume() -> None:
    with pytest.raises(ProtocolRefused, match="GPU-seconds cap"):
        authorize_development_cache_preparation(
            protocol_state="PRE_FREEZE_DRAFT",
            fresh_cohort_opened=False,
            gpu_seconds=14_401,
            external_cost_usd=5,
            persistent_volume_gb=60,
        )
    with pytest.raises(ProtocolRefused, match="external-cost cap"):
        authorize_development_cache_preparation(
            protocol_state="PRE_FREEZE_DRAFT",
            fresh_cohort_opened=False,
            gpu_seconds=7_200,
            external_cost_usd=10.01,
            persistent_volume_gb=60,
        )
    for bad_volume in (0, 61):
        with pytest.raises(ProtocolRefused, match="persistent-volume cap"):
            authorize_development_cache_preparation(
                protocol_state="PRE_FREEZE_DRAFT",
                fresh_cohort_opened=False,
                gpu_seconds=7_200,
                external_cost_usd=5,
                persistent_volume_gb=bad_volume,
            )
