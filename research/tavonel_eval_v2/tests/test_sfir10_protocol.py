from __future__ import annotations

import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

import sfir9_protocol  # noqa: E402
import sfir10_protocol as p  # noqa: E402


def test_criterion_is_inherited_unchanged():
    assert p.MINIMUM_C == sfir9_protocol.MINIMUM_C == 750
    assert p.MAXIMUM_Q == sfir9_protocol.MAXIMUM_Q == 1000
    assert p.QUOTA_FRACTION_NUMERATOR == sfir9_protocol.QUOTA_FRACTION_NUMERATOR == 8
    assert p.QUOTA_FRACTION_DENOMINATOR == sfir9_protocol.QUOTA_FRACTION_DENOMINATOR == 10
    assert p.MINIMUM_Q == sfir9_protocol.MINIMUM_Q == 600


def test_execution_envelope_is_inherited_and_enforced():
    assert p.PERMITTED_RATE_WINDOWS == sfir9_protocol.PERMITTED_RATE_WINDOWS == 6
    assert p.USABLE_CHARGE_PER_WINDOW == sfir9_protocol.USABLE_CHARGE_PER_WINDOW == 4500
    assert p.PER_ROOT_CHARGE_ALLOWANCE == sfir9_protocol.PER_ROOT_CHARGE_ALLOWANCE == 540
    assert p.derive_n() == 50


def test_next_partition_is_mechanical_not_selected():
    assert p.SELECTION_SALT == sfir9_protocol.SELECTION_SALT
    assert p.PARTITION_COUNT == sfir9_protocol.PARTITION_COUNT == 64
    assert p.PREDECESSOR_PARTITION_INDEX == 0
    assert p.PARTITION_INDEX == 1
    assert p.PARTITION_INDEX == (p.PREDECESSOR_PARTITION_INDEX + 1) % p.PARTITION_COUNT


def test_rate_control_flow_is_inside_protocol_not_runner_discretion():
    terms = p.Protocol().freeze().terms()["rate_window_execution"]
    assert terms["segment_start_observations"] == 1
    assert terms["poll_during_segment"] is False
    assert terms["wait_inside_segment"] is False
    assert terms["segment_start_requires_remaining_at_least"] == 4500
    assert terms["request_reservation_provider_charges"] == 4
    assert terms["observe_every_response"] == [
        "x-ratelimit-remaining",
        "x-ratelimit-reset",
        "retry-after",
    ]


def test_protocol_digest_changes_if_partition_or_execution_policy_changes(monkeypatch):
    base = p.Protocol().freeze().digest()
    monkeypatch.setattr(p, "PARTITION_INDEX", 2)
    assert p.Protocol().freeze().digest() != base


def test_draft_cannot_authorise_actions():
    try:
        p.Protocol().require_frozen("roster generation")
    except p.ProtocolRefused:
        pass
    else:
        raise AssertionError("draft protocol authorised roster generation")
