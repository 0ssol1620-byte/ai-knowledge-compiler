from __future__ import annotations

import pytest

from tools.release.run_folynta_recovery_campaign import evaluate_payload


def test_recovery_campaign_receipt_binds_all_three_gates() -> None:
    digest = "sha256:" + "1" * 64
    environment = "sha256:" + "a" * 64
    payload = {
        "candidate_id": "paddle",
        "benchmark_id": "omnidocbench",
        "finalist": False,
        "failure_labels": [
            {
                "item_id": "page-1",
                "failure_codes": ["T01"],
                "scope_level": "row",
                "scope_id": "row-1",
                "should_recover": True,
            }
        ],
        "failure_predictions": [
            {
                "item_id": "page-1",
                "failure_codes": ["T01"],
                "scope_level": "row",
                "scope_id": "row-1",
                "request_recovery": True,
            }
        ],
        "recovery_cases": [
            {
                "item_id": "page-1",
                "initial_correct": False,
                "selective_final_correct": True,
                "full_replay_correct": True,
                "recovery_attempted": True,
                "recovery_verified": True,
                "selective_latency_seconds": 1,
                "full_replay_latency_seconds": 2,
                "selective_cost": 1,
                "full_replay_cost": 2,
            }
        ],
        "repeat_observations": [
            {
                "run_id": "full-1",
                "candidate_id": "paddle",
                "benchmark_id": "omnidocbench",
                "environment_sha256": environment,
                "scope": "full",
                "prediction_hashes": [["page-1", digest]],
                "score": 1,
            },
            *[
                {
                    "run_id": f"audit-{index}",
                    "candidate_id": "paddle",
                    "benchmark_id": "omnidocbench",
                    "environment_sha256": environment,
                    "scope": "stratified_audit",
                    "prediction_hashes": [["page-1", digest]],
                    "score": 1,
                }
                for index in range(1, 4)
            ],
        ],
    }

    receipt = evaluate_payload(payload)

    assert receipt["gate"] == "PASS"
    assert receipt["failure_detection"]["gate_passed"] is True
    assert receipt["recovery"]["absolute_uplift"] == 1
    assert receipt["adaptive_repeats"]["required_full_runs"] == 1
    assert str(receipt["receipt_sha256"]).startswith("sha256:")


def test_recovery_campaign_receipt_rejects_unbound_candidate_identity() -> None:
    digest = "sha256:" + "1" * 64
    environment = "sha256:" + "a" * 64
    payload = {
        "candidate_id": "declared-candidate",
        "benchmark_id": "benchmark",
        "finalist": False,
        "failure_labels": [
            {
                "item_id": "page-1",
                "failure_codes": ["T01"],
                "scope_level": "row",
                "scope_id": "row-1",
                "should_recover": True,
            }
        ],
        "failure_predictions": [
            {
                "item_id": "page-1",
                "failure_codes": ["T01"],
                "scope_level": "row",
                "scope_id": "row-1",
                "request_recovery": True,
            }
        ],
        "recovery_cases": [
            {
                "item_id": "page-1",
                "initial_correct": False,
                "selective_final_correct": True,
                "full_replay_correct": True,
                "recovery_attempted": True,
                "recovery_verified": True,
                "selective_latency_seconds": 1,
                "full_replay_latency_seconds": 2,
                "selective_cost": 1,
                "full_replay_cost": 2,
            }
        ],
        "repeat_observations": [
            {
                "run_id": "full-1",
                "candidate_id": "different-candidate",
                "benchmark_id": "benchmark",
                "environment_sha256": environment,
                "scope": "full",
                "prediction_hashes": [["page-1", digest]],
                "score": 1,
            },
            *[
                {
                    "run_id": f"audit-{index}",
                    "candidate_id": "different-candidate",
                    "benchmark_id": "benchmark",
                    "environment_sha256": environment,
                    "scope": "stratified_audit",
                    "prediction_hashes": [["page-1", digest]],
                    "score": 1,
                }
                for index in range(1, 4)
            ],
        ],
    }

    with pytest.raises(ValueError, match="candidate_id"):
        evaluate_payload(payload)
