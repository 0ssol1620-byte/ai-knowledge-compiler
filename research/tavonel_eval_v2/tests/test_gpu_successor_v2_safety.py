import sys
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import gpu_successor_v2_safety as safety


def test_inner_caps_are_strictly_inside_founder_ceilings():
    assert safety.INNER_GPU_HOURS < safety.EXTERNAL_GPU_HOURS
    assert safety.INNER_USD < safety.EXTERNAL_USD
    assert safety.CAPS.maximum_seconds == Decimal("20700")


def test_projection_requires_live_rate_source_and_holds_inside_margin():
    body = safety.projected_launch_gate(
        projected_gpu_seconds=3600,
        live_hourly_rate_usd="2.50",
        rate_source="runpod-read-only-offer-snapshot:sha256:" + "a" * 64,
    )
    assert body["held"] is True
    assert body["operational_caps"] == {"gpu_hours": 5.75, "usd": 38.0}
    with pytest.raises(safety.SafetyRefused, match="source"):
        safety.projected_launch_gate(
            projected_gpu_seconds=3600, live_hourly_rate_usd=2.5, rate_source=""
        )


@pytest.mark.parametrize(
    "seconds,rate",
    [(20701, 1), (20700, Decimal("38") * 3600 / Decimal("20700") + 1)],
)
def test_projection_refuses_either_inner_cap(seconds, rate):
    with pytest.raises(safety.SafetyRefused, match="operational"):
        safety.projected_launch_gate(
            projected_gpu_seconds=seconds,
            live_hourly_rate_usd=rate,
            rate_source="provider offer receipt",
        )


def test_live_kill_fires_at_not_after_inner_boundary():
    assert safety.live_kill_required(gpu_seconds=20700, cost_usd=0)
    assert safety.live_kill_required(gpu_seconds=0, cost_usd=38)
    assert not safety.live_kill_required(gpu_seconds=20699, cost_usd="37.99")


def test_terminal_requires_final_billing_and_absence():
    with pytest.raises(safety.SafetyRefused, match="absence"):
        safety.terminal_billing_gate(
            provider_final_gpu_seconds=100,
            provider_final_cost_usd=1,
            provider_absent=False,
            billing_evidence_source="provider invoice",
        )
    held = safety.terminal_billing_gate(
        provider_final_gpu_seconds=100,
        provider_final_cost_usd=1,
        provider_absent=True,
        billing_evidence_source="provider final usage receipt",
    )
    assert held["last_poll_snapshot_is_not_final_billing"] is True


def test_terminal_refuses_operational_overrun_even_below_founder_ceiling():
    with pytest.raises(safety.SafetyRefused, match="operational"):
        safety.terminal_billing_gate(
            provider_final_gpu_seconds=20701,
            provider_final_cost_usd=1,
            provider_absent=True,
            billing_evidence_source="provider final usage receipt",
        )
