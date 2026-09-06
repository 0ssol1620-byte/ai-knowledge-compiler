from __future__ import annotations

import pytest
from akc_absorption.assurance_experiment import (
    ExperimentGuardrail,
    ExperimentObservation,
    ExperimentReceipt,
    ExperimentStage,
    ExperimentVariant,
    summarize_experiment,
)


def _observations():
    return [
        ExperimentObservation("bad-hit", True, True, recovered=True, latency_ms=20, gpu_seconds=1),
        ExperimentObservation("bad-miss", True, False, unresolved=True, latency_ms=10),
        ExperimentObservation("clean", False, False, latency_ms=5),
    ]


def test_metrics_include_quality_abstention_latency_and_cost_axes() -> None:
    metrics = summarize_experiment(_observations())
    assert metrics.samples == 3
    assert metrics.accuracy == pytest.approx(2 / 3)
    assert metrics.silent_corruption_precision == 1.0
    assert metrics.silent_corruption_recall == 0.5
    assert metrics.unresolved_rate == pytest.approx(1 / 3)
    assert metrics.recovery_rate == 1.0
    assert metrics.gpu_seconds == 1.0


def test_stage1_requires_cpu_green_and_hard_caps() -> None:
    guard = ExperimentGuardrail(stage1_max_samples=300, stage1_max_external_cost_usd=30)
    assert not guard.authorize(
        ExperimentStage.STAGE1_GPU,
        samples=100,
        estimated_gpu_seconds=100,
        estimated_external_cost_usd=1,
        cpu_gate_green=False,
    ).allowed
    assert guard.authorize(
        ExperimentStage.STAGE1_GPU,
        samples=300,
        estimated_gpu_seconds=100,
        estimated_external_cost_usd=1,
        cpu_gate_green=True,
    ).allowed
    assert not guard.authorize(
        ExperimentStage.STAGE1_GPU,
        samples=301,
        estimated_gpu_seconds=100,
        estimated_external_cost_usd=1,
        cpu_gate_green=True,
    ).allowed


def test_stage2_requires_stage1_green_and_large_is_never_automatic() -> None:
    guard = ExperimentGuardrail()
    assert not guard.authorize(
        ExperimentStage.STAGE2_GPU,
        samples=1000,
        estimated_gpu_seconds=1000,
        estimated_external_cost_usd=10,
        cpu_gate_green=True,
        prior_stage_green=False,
    ).allowed
    assert guard.authorize(
        ExperimentStage.STAGE2_GPU,
        samples=1000,
        estimated_gpu_seconds=1000,
        estimated_external_cost_usd=10,
        cpu_gate_green=True,
        prior_stage_green=True,
    ).allowed
    assert not guard.authorize(
        ExperimentStage.LARGE,
        samples=5000,
        estimated_gpu_seconds=1000,
        estimated_external_cost_usd=10,
        cpu_gate_green=True,
        prior_stage_green=True,
    ).allowed


def test_receipt_is_deterministic_and_rejects_secret_like_metadata() -> None:
    receipt = ExperimentReceipt.build(
        variant=ExperimentVariant.CALIBRATED,
        stage=ExperimentStage.CPU,
        corpus_id="silent-corruption-v1",
        observations=_observations(),
        metadata={"calibration_artifact_id": "cal_123"},
    )
    again = ExperimentReceipt.build(
        variant=ExperimentVariant.CALIBRATED,
        stage=ExperimentStage.CPU,
        corpus_id="silent-corruption-v1",
        observations=_observations(),
        metadata={"calibration_artifact_id": "cal_123"},
    )
    assert receipt.receipt_id == again.receipt_id
    with pytest.raises(ValueError, match="secret-like"):
        ExperimentReceipt.build(
            variant=ExperimentVariant.BASELINE,
            stage=ExperimentStage.CPU,
            corpus_id="x",
            observations=_observations(),
            metadata={"runpod_api_key": "must-never-be-recorded"},
        )