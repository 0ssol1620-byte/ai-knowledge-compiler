#!/usr/bin/env python3
"""Fail-closed spend controls for ``GPU_SUCCESSOR_STUDY_V2``.

The founder ceilings remain six GPU hours and forty US dollars.  A paid run
is authorized against smaller *operational* limits so polling latency, output
retrieval, and provider teardown cannot turn an equality-at-the-boundary
calculation into an over-ceiling bill.  This module performs no network I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

EXTERNAL_GPU_HOURS = Decimal("6")
EXTERNAL_USD = Decimal("40")
INNER_GPU_HOURS = Decimal("5.75")
INNER_USD = Decimal("38")
INNER_GPU_SECONDS = INNER_GPU_HOURS * Decimal("3600")


class SafetyRefused(RuntimeError):
    """A spend estimate or observed-usage claim was not safely bounded."""


def _decimal(value: Any, label: str) -> Decimal:
    if isinstance(value, bool):
        raise SafetyRefused(f"{label} is not numeric")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as error:
        raise SafetyRefused(f"{label} is not numeric") from error
    if not number.is_finite() or number < 0:
        raise SafetyRefused(f"{label} is not a finite non-negative number")
    return number


@dataclass(frozen=True, slots=True)
class OperationalCaps:
    maximum_seconds: Decimal = INNER_GPU_SECONDS
    maximum_cost_usd: Decimal = INNER_USD
    external_seconds: Decimal = EXTERNAL_GPU_HOURS * Decimal("3600")
    external_cost_usd: Decimal = EXTERNAL_USD

    def __post_init__(self) -> None:
        if not Decimal("0") < self.maximum_seconds < self.external_seconds:
            raise SafetyRefused("operational time cap must be strictly inside founder ceiling")
        if not Decimal("0") < self.maximum_cost_usd < self.external_cost_usd:
            raise SafetyRefused("operational dollar cap must be strictly inside founder ceiling")


CAPS = OperationalCaps()


def projected_launch_gate(
    *,
    projected_gpu_seconds: Any,
    live_hourly_rate_usd: Any,
    rate_source: str,
) -> dict[str, Any]:
    """Require a current explicit rate and a projection inside both inner caps."""

    seconds = _decimal(projected_gpu_seconds, "projected_gpu_seconds")
    rate = _decimal(live_hourly_rate_usd, "live_hourly_rate_usd")
    if not isinstance(rate_source, str) or not rate_source.strip():
        raise SafetyRefused("live rate evidence source is required")
    projected_cost = rate * seconds / Decimal("3600")
    held = seconds <= CAPS.maximum_seconds and projected_cost <= CAPS.maximum_cost_usd
    if not held:
        raise SafetyRefused("projection exceeds the 5.75 GPU-hour or $38 operational limit")
    return {
        "held": True,
        "projected_gpu_seconds": float(seconds),
        "projected_gpu_hours": float(seconds / Decimal("3600")),
        "live_hourly_rate_usd": float(rate),
        "projected_cost_usd": float(projected_cost),
        "rate_source": rate_source,
        "operational_caps": {"gpu_hours": 5.75, "usd": 38.0},
        "founder_ceilings": {"gpu_hours": 6.0, "usd": 40.0},
    }


def live_kill_required(*, gpu_seconds: Any, cost_usd: Any) -> bool:
    """Fire at the inner boundary; callers must delete and prove absence."""

    seconds = _decimal(gpu_seconds, "gpu_seconds")
    cost = _decimal(cost_usd, "cost_usd")
    return seconds >= CAPS.maximum_seconds or cost >= CAPS.maximum_cost_usd


def terminal_billing_gate(
    *,
    provider_final_gpu_seconds: Any,
    provider_final_cost_usd: Any,
    provider_absent: bool,
    billing_evidence_source: str,
) -> dict[str, Any]:
    """Accept completion only with post-work final usage and positive deletion proof.

    The last polling snapshot is not final billing evidence.  The caller must
    supply a dedicated provider-derived usage observation immediately before
    deletion, after output retrieval, plus positive repeated absence proof.
    """

    seconds = _decimal(provider_final_gpu_seconds, "provider_final_gpu_seconds")
    cost = _decimal(provider_final_cost_usd, "provider_final_cost_usd")
    if provider_absent is not True:
        raise SafetyRefused("provider absence was not positively proven")
    if not isinstance(billing_evidence_source, str) or not billing_evidence_source.strip():
        raise SafetyRefused("provider final billing evidence source is required")
    if seconds > CAPS.external_seconds or cost > CAPS.external_cost_usd:
        raise SafetyRefused("final provider usage exceeded a founder ceiling")
    if seconds > CAPS.maximum_seconds or cost > CAPS.maximum_cost_usd:
        raise SafetyRefused("final provider usage exceeded an operational safety cap")
    return {
        "held": True,
        "provider_final_gpu_seconds": float(seconds),
        "provider_final_gpu_hours": float(seconds / Decimal("3600")),
        "provider_final_cost_usd": float(cost),
        "provider_absent": True,
        "billing_evidence_source": billing_evidence_source,
        "last_poll_snapshot_is_not_final_billing": True,
    }


__all__ = [
    "CAPS",
    "EXTERNAL_GPU_HOURS",
    "EXTERNAL_USD",
    "INNER_GPU_HOURS",
    "INNER_USD",
    "OperationalCaps",
    "SafetyRefused",
    "live_kill_required",
    "projected_launch_gate",
    "terminal_billing_gate",
]
