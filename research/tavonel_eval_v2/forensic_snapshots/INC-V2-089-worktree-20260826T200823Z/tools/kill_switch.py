#!/usr/bin/env python3
"""The single authority for "has the GPU successor study exceeded its caps."

Both `tools/launch_gpu_successor.py` (its in-process `Watchdog` and Runpod's
own platform-side `terminateAfter`) and any operator checking on a live run
independently should ask *this* module, not re-derive the arithmetic. The caps
themselves are never restated here -- they are imported from
`gpu_successor_preflight`, the one place `CAP_GPU_HOURS`/`CAP_USD` are
declared.

The property this module exists to guarantee, above all the others:

**unknown usage is a stop, not permission to continue.** A spend limit that
only fires when its own telemetry is readable is not a spend limit -- it is a
limit that silently disables itself exactly when something has already gone
wrong enough that usage cannot be read. `evaluate()` treats a missing value,
`runpod_provisioner.NOT_RETRIEVED`, or any value that is not a plain number
identically: as `STOP_CANNOT_TELL`, which this module's three-outcome
vocabulary keeps distinct from `STOP` (a trigger actually fired) precisely so
a caller -- or a reader of a receipt -- can tell "we know we're over" from "we
don't know, so we stopped anyway."

Two independent triggers, either sufficient alone: elapsed wall time against
`CAP_GPU_HOURS`, and accumulated cost against `CAP_USD`. Both are checked
against a threshold set *below* the cap by a declared margin -- see
`TIME_MARGIN_FRACTION`/`COST_MARGIN_FRACTION` -- so the switch fires before
the cap is reached, not at it or after it.

This module never reports success. There is no return value meaning "the run
is fine" -- only `CONTINUE` ("nothing here says to stop it"), `STOP` (a
trigger fired), or `STOP_CANNOT_TELL` (usage could not be read, which is
itself a stop). A caller looking for reassurance will not find it in this
module's vocabulary on purpose.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gpu_successor_preflight as gsp

#: Imported, never restated. If the preflight's caps ever change, this
#: module's defaults move with them automatically rather than drifting.
CAP_GPU_HOURS = gsp.CAP_GPU_HOURS
CAP_USD = gsp.CAP_USD
CAP_SECONDS = CAP_GPU_HOURS * 3600.0

#: The switch fires this fraction of each cap *before* the cap itself, not at
#: it. Declared, not measured: 5% of 6 hours is 18 minutes, 5% of $40 is $2.
#: Both are chosen to be generous relative to the latency a real stop has to
#: absorb -- the gap between "the threshold is crossed" and "the pod is
#: actually torn down" (a `threading.Timer` firing plus a teardown API call
#: in `launch_gpu_successor.Watchdog`, or the round-trip an operator takes to
#: read a usage figure and act on it independently of that watchdog). A
#: margin sized to arithmetic precision would be pointless here; the margin
#: has to cover reaction time, so it is sized against reaction time.
TIME_MARGIN_FRACTION = 0.05
COST_MARGIN_FRACTION = 0.05

CONTINUE = "CONTINUE"
STOP = "STOP"
STOP_CANNOT_TELL = "STOP_CANNOT_TELL"

#: The only three outcomes this module ever reports. Order matters for
#: `OUTCOMES.index`-style severity comparisons a caller might want, but
#: nothing here relies on that -- it is declared for completeness and for
#: tests that want to assert the vocabulary is exactly these three and no
#: others.
OUTCOMES: tuple[str, ...] = (CONTINUE, STOP, STOP_CANNOT_TELL)

#: The literal string `runpod_provisioner.NOT_RETRIEVED` uses when a real
#: usage read fails. Named here as a plain string, not imported, so this
#: module carries no import-time dependency on `httpx`/Runpod credentials --
#: `runpod_provisioner` requires a working `RunPodCredentialSet` at import
#: time via `RunpodPodProvisioner.__init__`'s default, and this module must
#: stay importable (and its tests runnable) with no credentials and no
#: network. The two modules are kept in agreement by
#: `test_not_retrieved_marker_matches_runpod_provisioners`, which imports
#: `runpod_provisioner.NOT_RETRIEVED` once, at test time, specifically to
#: catch drift.
NOT_RETRIEVED = "NOT_RETRIEVED"
UNKNOWN_MARKERS: tuple[str, ...] = (NOT_RETRIEVED,)


def _is_unknown(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value in UNKNOWN_MARKERS)


def _is_number(value: Any) -> bool:
    # bool is an int subclass in Python; a stray True/False must not pass as
    # a usage figure.
    return isinstance(value, (int, float)) and not isinstance(value, bool)


@dataclass(frozen=True)
class Usage:
    """What the switch needs to know about consumption so far.

    Either field may be `None`, the literal string `NOT_RETRIEVED`, or any
    other non-numeric value -- all three are treated identically, as unknown.
    A caller with a real number passes a real `int`/`float`; nothing else is
    accepted as "known."
    """

    elapsed_seconds: Any
    cost_usd: Any


def evaluate(
    usage: Usage,
    *,
    cap_seconds: float = CAP_SECONDS,
    cap_usd: float = CAP_USD,
    time_margin_fraction: float = TIME_MARGIN_FRACTION,
    cost_margin_fraction: float = COST_MARGIN_FRACTION,
) -> dict[str, Any]:
    """The one decision this module makes, as data, never a bare bool.

    `time_margin_fraction`/`cost_margin_fraction` are accepted as parameters
    (rather than hardcoded) so a test can exercise the threshold arithmetic
    at values other than the module default without monkeypatching a
    constant; production callers should leave them at the declared defaults.
    """
    time_threshold = cap_seconds * (1.0 - time_margin_fraction)
    cost_threshold = cap_usd * (1.0 - cost_margin_fraction)
    caps = {"cap_seconds": cap_seconds, "cap_usd": cap_usd}
    thresholds = {"time_seconds": time_threshold, "cost_usd": cost_threshold}

    elapsed_unknown = _is_unknown(usage.elapsed_seconds)
    cost_unknown = _is_unknown(usage.cost_usd)
    elapsed_unreadable = not elapsed_unknown and not _is_number(usage.elapsed_seconds)
    cost_unreadable = not cost_unknown and not _is_number(usage.cost_usd)

    triggers = {
        "elapsed_seconds_unknown": elapsed_unknown or elapsed_unreadable,
        "cost_unknown": cost_unknown or cost_unreadable,
    }

    if triggers["elapsed_seconds_unknown"] or triggers["cost_unknown"]:
        # Unknown -- whether an explicit marker, a missing value, or a value
        # this module cannot interpret as a number -- is never permission to
        # continue. This branch is checked first, before either numeric
        # trigger, so a partially-unknown usage (one field known, one not)
        # cannot be waved through on the strength of the field that happened
        # to be readable.
        return {
            "outcome": STOP_CANNOT_TELL,
            "reason": _unknown_reason(
                triggers["elapsed_seconds_unknown"], triggers["cost_unknown"]
            ),
            "triggers": triggers,
            "caps": caps,
            "thresholds": thresholds,
        }

    time_triggered = usage.elapsed_seconds >= time_threshold
    cost_triggered = usage.cost_usd >= cost_threshold
    triggers["elapsed_seconds_over_threshold"] = time_triggered
    triggers["cost_over_threshold"] = cost_triggered

    outcome = STOP if (time_triggered or cost_triggered) else CONTINUE
    reason = (
        _stop_reason(time_triggered, cost_triggered)
        if outcome == STOP
        else "elapsed time and cost both read below their margin-adjusted thresholds"
    )
    return {
        "outcome": outcome,
        "reason": reason,
        "triggers": triggers,
        "caps": caps,
        "thresholds": thresholds,
        "usage": {"elapsed_seconds": usage.elapsed_seconds, "cost_usd": usage.cost_usd},
    }


def _unknown_reason(elapsed_unknown: bool, cost_unknown: bool) -> str:
    parts = [
        name
        for name, flag in (("elapsed_seconds", elapsed_unknown), ("cost_usd", cost_unknown))
        if flag
    ]
    joined = " and ".join(parts)
    return (
        f"{joined} could not be read as a number; unknown usage is treated as a "
        "stop, never as permission to continue"
    )


def _stop_reason(time_triggered: bool, cost_triggered: bool) -> str:
    parts = []
    if time_triggered:
        parts.append("elapsed time crossed its margin-adjusted threshold")
    if cost_triggered:
        parts.append("accumulated cost crossed its margin-adjusted threshold")
    return "; ".join(parts)


# ---------------------------------------------------------------------------
# stateful wrapper -- idempotent firing
# ---------------------------------------------------------------------------


class KillSwitch:
    """Wraps `evaluate` with "have we already acted" bookkeeping.

    This class adds no second decision on top of `evaluate` -- `check` calls
    it and only it. What it adds is idempotence: `on_stop` runs at most once,
    on the first `check` call whose outcome is not `CONTINUE`, no matter how
    many more times `check` is called afterward (a caller polling in a loop
    must not tear the same thing down twice, or race two teardown calls
    against each other).
    """

    def __init__(
        self,
        on_stop: Any,
        *,
        cap_seconds: float = CAP_SECONDS,
        cap_usd: float = CAP_USD,
        time_margin_fraction: float = TIME_MARGIN_FRACTION,
        cost_margin_fraction: float = COST_MARGIN_FRACTION,
    ) -> None:
        self._on_stop = on_stop
        self._cap_seconds = cap_seconds
        self._cap_usd = cap_usd
        self._time_margin_fraction = time_margin_fraction
        self._cost_margin_fraction = cost_margin_fraction
        self.fired = False
        self.fire_count = 0
        self.last_result: dict[str, Any] | None = None

    def check(self, usage: Usage) -> dict[str, Any]:
        result = evaluate(
            usage,
            cap_seconds=self._cap_seconds,
            cap_usd=self._cap_usd,
            time_margin_fraction=self._time_margin_fraction,
            cost_margin_fraction=self._cost_margin_fraction,
        )
        self.last_result = result
        if result["outcome"] != CONTINUE:
            self.fire_count += 1
            if not self.fired:
                self.fired = True
                self._on_stop(result)
        return result


# ---------------------------------------------------------------------------
# CLI -- reads no live telemetry itself; a caller supplies the numbers
# ---------------------------------------------------------------------------


def _parse_usage_value(raw: str | None) -> Any:
    if raw is None:
        return None
    if raw in UNKNOWN_MARKERS:
        return raw
    try:
        return float(raw)
    except ValueError:
        return raw


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--elapsed-seconds",
        default=None,
        help="observed elapsed GPU wall time in seconds, or NOT_RETRIEVED, or omit for unknown",
    )
    parser.add_argument(
        "--cost-usd",
        default=None,
        help="observed accumulated cost in USD, or NOT_RETRIEVED, or omit for unknown",
    )
    args = parser.parse_args(argv)

    usage = Usage(
        elapsed_seconds=_parse_usage_value(args.elapsed_seconds),
        cost_usd=_parse_usage_value(args.cost_usd),
    )
    result = evaluate(usage)
    print(json.dumps(result, indent=2))
    return 0 if result["outcome"] == CONTINUE else 1


if __name__ == "__main__":
    raise SystemExit(main())
