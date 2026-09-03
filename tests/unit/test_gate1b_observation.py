from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).parents[2] / "infra" / "postgres" / "gate1b_observation.py"
SPEC = importlib.util.spec_from_file_location("gate1b_observation", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def snapshot(
    *, attempts: int, grants: int, backlog: int, claimable: int, zero: int, starved: int
) -> bytes:
    q = 'queue="gpu_provider_invocations"'
    return (
        f"akc_claim_poll_attempts_total{{{q}}} {attempts}\n"
        f"akc_claim_poll_grants_total{{{q}}} {grants}\n"
        f"akc_claim_poll_backlog{{{q}}} {backlog}\n"
        f"akc_claim_poll_claimable{{{q}}} {claimable}\n"
        f"akc_claim_poll_consecutive_zero_polls{{{q}}} {zero}\n"
        f"akc_claim_poll_starved{{{q}}} {starved}\n"
    ).encode()


def test_gate1b_passes_only_when_explicit_volume_and_safety_checks_hold() -> None:
    receipt = MODULE.evaluate(
        snapshot(attempts=100, grants=80, backlog=3, claimable=2, zero=0, starved=0),
        snapshot(attempts=140, grants=110, backlog=5, claimable=4, zero=0, starved=0),
        min_attempts=40,
        min_grants=30,
    )

    assert receipt.status == "PASS"
    assert receipt.attempts_delta == 40
    assert receipt.grants_delta == 30
    assert receipt.blockers == ()
    assert receipt.before_sha256 != receipt.after_sha256


def test_gate1b_blocks_on_real_starvation_even_when_volume_is_high() -> None:
    receipt = MODULE.evaluate(
        snapshot(attempts=100, grants=80, backlog=3, claimable=2, zero=0, starved=0),
        snapshot(attempts=200, grants=150, backlog=12, claimable=12, zero=3, starved=1),
        min_attempts=50,
        min_grants=20,
    )

    assert receipt.status == "BLOCKED"
    assert "starvation_clear" in receipt.blockers


def test_gate1b_blocks_if_operator_requested_observation_volume_was_not_seen() -> None:
    receipt = MODULE.evaluate(
        snapshot(attempts=100, grants=80, backlog=0, claimable=0, zero=0, starved=0),
        snapshot(attempts=104, grants=82, backlog=0, claimable=0, zero=2, starved=0),
        min_attempts=20,
        min_grants=10,
    )

    assert receipt.status == "BLOCKED"
    assert set(receipt.blockers) >= {"attempts_observed", "grants_observed"}


def test_gate1b_rejects_impossible_claimable_backlog_shape() -> None:
    receipt = MODULE.evaluate(
        snapshot(attempts=10, grants=5, backlog=1, claimable=1, zero=0, starved=0),
        snapshot(attempts=20, grants=10, backlog=2, claimable=3, zero=0, starved=0),
        min_attempts=10,
        min_grants=5,
    )

    assert receipt.status == "BLOCKED"
    assert "claimable_not_above_backlog" in receipt.blockers


def test_gate1b_requires_all_six_series_for_the_selected_queue() -> None:
    incomplete = b'akc_claim_poll_attempts_total{queue="gpu_provider_invocations"} 1\n'
    with pytest.raises(ValueError, match="missing Gate 1B metrics"):
        MODULE.parse_snapshot(incomplete.decode())


def test_gate1b_refuses_to_invent_an_observation_threshold() -> None:
    before = snapshot(attempts=1, grants=1, backlog=0, claimable=0, zero=0, starved=0)
    after = snapshot(attempts=2, grants=2, backlog=0, claimable=0, zero=0, starved=0)
    with pytest.raises(ValueError, match="min-attempts"):
        MODULE.evaluate(before, after, min_attempts=0, min_grants=0)
