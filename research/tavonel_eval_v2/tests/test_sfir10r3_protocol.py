from __future__ import annotations

import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

import sfir10r2_protocol as predecessor  # noqa: E402
import sfir10r3_protocol as p  # noqa: E402


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


def test_selection_mechanically_advances_from_spent_partition_two():
    assert predecessor.PARTITION_INDEX == 2
    assert p.SELECTION_SALT == predecessor.SELECTION_SALT
    assert p.PARTITION_COUNT == predecessor.PARTITION_COUNT == 64
    assert p.PREDECESSOR_PARTITION_INDEX == 2
    assert p.PARTITION_INDEX == 3
    assert p.PARTITION_INDEX == (p.PREDECESSOR_PARTITION_INDEX + 1) % p.PARTITION_COUNT


def test_shared_token_accounting_policy_is_frozen_in_protocol_terms():
    terms = p.Protocol().freeze().terms()["rate_window_execution"]
    preflight = terms["accounting_sanity_preflight"]
    assert terms["segment_start_observations"] == 1
    assert terms["poll_during_segment"] is False
    assert terms["wait_inside_segment"] is False
    assert preflight["requests"] == 10
    assert preflight["require_request_id"] is True
    assert preflight["require_unique_request_ids"] is True
    assert preflight["minimum_delta_each_response"] == 1
    assert preflight["external_extra_permitted"] is True
    assert terms["minimum_attributable_charge_per_network_hop"] == 1
    assert terms["require_reset_header"] is True
    assert terms["unattributed_extra_policy"] == (
        "RECORD_AS_EXTERNAL_INTERFERENCE_NEVER_CREDIT_TO_YIELD"
    )
    assert terms["provider_cost_claim_policy"] == "WITHHOLD_UNLESS_ZERO_UNATTRIBUTED_EXTRA"
    assert terms["capacity_claim_depends_on_exact_provider_cost"] is False
    assert terms["request_reservation_minimum_attributable_charges"] == 4


def test_protocol_digest_changes_if_partition_or_accounting_policy_changes(monkeypatch):
    base = p.Protocol().freeze().digest()
    monkeypatch.setattr(p, "PARTITION_INDEX", 4)
    assert p.Protocol().freeze().digest() != base
    monkeypatch.setattr(p, "PARTITION_INDEX", 3)
    monkeypatch.setattr(p, "ACCOUNTING_PREFLIGHT_REQUESTS", 9)
    assert p.Protocol().freeze().digest() != base


def test_external_interference_cannot_be_credited_to_capacity():
    terms = p.Protocol().freeze().terms()["rate_window_execution"]
    assert "response bodies" in terms["why_interference_cannot_inflate_capacity"]
    assert p.MINIMUM_ATTRIBUTABLE_CHARGE_PER_NETWORK_HOP == 1
    assert p.CAPACITY_CLAIM_DEPENDS_ON_EXACT_PROVIDER_COST is False


def test_draft_cannot_authorise_actions():
    try:
        p.Protocol().require_frozen("roster generation")
    except p.ProtocolRefused:
        pass
    else:
        raise AssertionError("draft protocol authorised roster generation")
