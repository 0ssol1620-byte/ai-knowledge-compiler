#!/usr/bin/env python3
"""Exact McNemar power analysis. Replaces "about 190" with a computed number.

The proposal previously said the study "needs roughly 190" questions. That is
the kind of phrase that survives review because nobody can check it. This
computes it, from parameters declared in the protocol rather than chosen to
produce a convenient answer:

    alpha                       0.05, two-sided
    effect                      0.15
    assumed discordant rate     0.30
    target power                >= 0.95
    hard minimum eligible Q1    190

Exact, not normal-approximation. McNemar's test conditions on the number of
discordant pairs, which is itself random, so power is computed by summing over
the binomial distribution of that count and, for each value, over the exact
binomial test's rejection region. A normal approximation would be optimistic at
exactly the sample sizes being argued about.

Stdlib only. No GPU, no network, no spend.
"""

from __future__ import annotations

import argparse
import json
import sys
from functools import lru_cache
from math import comb
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import NS, now, rel, sha_file  # noqa: E402
from evidence import write_immutable  # noqa: E402

PROTOCOL = NS / "protocols" / "SOURCE_LOCALITY_V2.yaml"

#: Declared parameters. These are protocol values, not tuning knobs.
ALPHA = 0.05
EFFECT = 0.15
DISCORDANT_RATE = 0.30
TARGET_POWER = 0.95
HARD_MINIMUM_ELIGIBLE_Q1 = 190


@lru_cache(maxsize=None)
def _binom_pmf(k: int, n: int, p: float) -> float:
    if k < 0 or k > n:
        return 0.0
    return comb(n, k) * (p**k) * ((1.0 - p) ** (n - k))


@lru_cache(maxsize=None)
def _rejection_region(n_disc: int, alpha: float) -> tuple[int, ...]:
    """The discordant splits at which the exact test rejects.

    Memoised because power() sums over every discordant count from 0 to n and
    required_n() binary-searches over n; without this the region is recomputed
    O(n^2) times for values that never change.
    """
    return tuple(b for b in range(n_disc + 1) if exact_binomial_rejects(b, n_disc, alpha))


def exact_binomial_rejects(b: int, n_disc: int, alpha: float) -> bool:
    """Does the exact two-sided binomial test at p = 0.5 reject on this split?

    ``b`` is the count in one discordant direction out of ``n_disc``. The
    two-sided exact p-value is the total probability of every outcome at most as
    likely as the observed one.
    """
    if n_disc == 0:
        return False
    observed = _binom_pmf(b, n_disc, 0.5)
    tolerance = observed * (1 + 1e-9)
    p_value = sum(
        _binom_pmf(k, n_disc, 0.5)
        for k in range(n_disc + 1)
        if _binom_pmf(k, n_disc, 0.5) <= tolerance
    )
    return p_value <= alpha


def power(
    n: int,
    effect: float = EFFECT,
    discordant_rate: float = DISCORDANT_RATE,
    alpha: float = ALPHA,
) -> float:
    """Exact power of McNemar's test at ``n`` paired observations.

    Under the alternative, a pair is discordant with probability
    ``discordant_rate``, and a discordant pair favours the better arm with
    probability ``0.5 + effect / (2 * discordant_rate)``. That parameterisation
    makes ``effect`` the difference in marginal proportions, which is what the
    protocol declares — not the within-discordant split, which is easy to
    confuse it with and which would flatter the design.
    """
    favour = 0.5 + effect / (2.0 * discordant_rate)
    if not 0.0 <= favour <= 1.0:
        raise ValueError("effect is impossible at this discordant rate")

    total = 0.0
    for n_disc in range(0, n + 1):
        weight = _binom_pmf(n_disc, n, discordant_rate)
        if weight < 1e-15:
            continue
        total += weight * sum(
            _binom_pmf(b, n_disc, favour) for b in _rejection_region(n_disc, alpha)
        )
    return total


def required_n(target: float = TARGET_POWER, ceiling: int = 600) -> int | None:
    """Smallest n reaching the target power. Searched, not assumed."""
    low, high = 10, ceiling
    if power(high) < target:
        return None
    while low < high:
        mid = (low + high) // 2
        if power(mid) >= target:
            high = mid
        else:
            low = mid + 1
    return low


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--eligible", type=int, default=None, help="observed eligible Q1")
    args = parser.parse_args()

    needed = required_n()
    curve = {n: round(power(n), 4) for n in (50, 100, 150, 190, 200, 250, 300)}

    body: dict[str, Any] = {
        "schema": "tavonel.v2.mcnemar_power.v1",
        "computed_at": now(),
        "method": "exact McNemar, summing over the binomial distribution of the discordant count",
        "not_normal_approximation_because": (
            "the normal approximation is optimistic at exactly the sample sizes "
            "under argument, and conditioning on a random discordant count is "
            "the property that makes the exact form necessary."
        ),
        "parameters": {
            "alpha": ALPHA,
            "sided": "two",
            "effect": EFFECT,
            "effect_definition": "difference in marginal proportions between the two arms",
            "assumed_discordant_pair_rate": DISCORDANT_RATE,
            "target_power": TARGET_POWER,
            "hard_minimum_eligible_Q1": HARD_MINIMUM_ELIGIBLE_Q1,
            "floor_status": (
                "conservative preregistered floor. Never lowered after seeing an eligibility count."
            ),
        },
        "computed_required_n_at_target_power": needed,
        "power_at_the_declared_floor": round(power(HARD_MINIMUM_ELIGIBLE_Q1), 4),
        "power_curve": curve,
        "tool": rel(Path(__file__).resolve()),
        "tool_sha256": sha_file(Path(__file__).resolve()),
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }
    if args.eligible is not None:
        body["observed_eligible_Q1"] = args.eligible
        body["power_at_observed_eligible"] = round(power(args.eligible), 4)
        body["meets_floor"] = args.eligible >= HARD_MINIMUM_ELIGIBLE_Q1

    written = write_immutable(
        "mcnemar-power", body, tool=Path(__file__).resolve(), protocol=PROTOCOL
    )
    print(
        json.dumps(
            {
                "required_n_for_power_0.95": needed,
                "power_at_190": body["power_at_the_declared_floor"],
                "power_curve": curve,
                **(
                    {"power_at_observed": body["power_at_observed_eligible"]}
                    if args.eligible is not None
                    else {}
                ),
                **written,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
