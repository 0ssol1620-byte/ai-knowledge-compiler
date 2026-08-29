from __future__ import annotations

import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

import sfir10r1_protocol as predecessor  # noqa: E402
import sfir10r2_protocol as p  # noqa: E402


def test_criterion_is_inherited_unchanged():
    assert p.MINIMUM_C == predecessor.MINIMUM_C == 750
    assert p.MAXIMUM_Q == predecessor.MAXIMUM_Q == 1000
    assert p.QUOTA_FRACTION_NUMERATOR == predecessor.QUOTA_FRACTION_NUMERATOR == 8
    assert p.QUOTA_FRACTION_DENOMINATOR == predecessor.QUOTA_FRACTION_DENOMINATOR == 10
    assert p.MINIMUM_Q == predecessor.MINIMUM_Q == 600


def test_execution_envelope_is_inherited_unchanged():
    assert p.PERMITTED_RATE_WINDOWS == predecessor.PERMITTED_RATE_WINDOWS == 6
    assert p.USABLE_CHARGE_PER_WINDOW == predecessor.USABLE_CHARGE_PER_WINDOW == 4500
    assert p.PER_ROOT_CHARGE_ALLOWANCE == predecessor.PER_ROOT_CHARGE_ALLOWANCE == 540
    assert p.CANDIDATE_EXTENSIONS == predecessor.CANDIDATE_EXTENSIONS
    assert p.derive_n() == predecessor.derive_n() == 50


def test_next_partition_is_mechanical_after_spent_r1_partition_one():
    assert predecessor.PARTITION_INDEX == 1
    assert p.SELECTION_SALT == predecessor.SELECTION_SALT
    assert p.PARTITION_COUNT == predecessor.PARTITION_COUNT == 64
    assert p.PREDECESSOR_PARTITION_INDEX == 1
    assert p.PARTITION_INDEX == 2
    assert p.PARTITION_INDEX == (p.PREDECESSOR_PARTITION_INDEX + 1) % p.PARTITION_COUNT


def test_exclusivity_preflight_is_frozen_in_protocol_terms():
    terms = p.Protocol().freeze().terms()["rate_window_execution"]
    preflight = terms["exclusive_credential_preflight"]
    assert terms["segment_start_observations"] == 1
    assert terms["poll_during_segment"] is False
    assert terms["wait_inside_segment"] is False
    assert terms["segment_start_requires_remaining_before_preflight_at_least"] == 4510
    assert terms["segment_start_requires_remaining_after_preflight_at_least"] == 4500
    assert preflight == {
        "endpoint": "https://api.github.com/repos/octocat/Hello-World",
        "requests": 10,
        "require_request_id": True,
        "require_unique_request_ids": True,
        "require_unit_delta_each_response": True,
        "reconcile_exact_charges": 10,
        "wait_seconds": 0,
        "failure_policy": "SEGMENT_NOT_STARTED_RETRY_ALLOWED",
        "cohort_contact_before_success": False,
        "scientific_data_consumed": False,
    }
    assert terms["request_reservation_provider_charges"] == 4


def test_protocol_digest_changes_if_partition_or_preflight_policy_changes(monkeypatch):
    base = p.Protocol().freeze().digest()
    monkeypatch.setattr(p, "PARTITION_INDEX", 3)
    assert p.Protocol().freeze().digest() != base
    monkeypatch.setattr(p, "PARTITION_INDEX", 2)
    monkeypatch.setattr(p, "EXCLUSIVITY_PREFLIGHT_REQUESTS", 9)
    assert p.Protocol().freeze().digest() != base


def test_draft_cannot_authorise_actions():
    try:
        p.Protocol().require_frozen("roster generation")
    except p.ProtocolRefused:
        pass
    else:
        raise AssertionError("draft protocol authorised roster generation")
