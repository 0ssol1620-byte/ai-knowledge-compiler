#!/usr/bin/env python3
"""How large must the untouched holdout be for the confirmatory A9 test?

The discovery set gave an effect estimate. It cannot also give a confirmatory
p-value, so the question is how many pages a fresh corpus needs before the test
has a real chance of detecting the effect if the effect is real.

The design is deliberately awkward and the power calculation has to respect it:
the gate abstains on a small minority of pages, so the 2x2 has one arm of ~9% of
the corpus. Power is governed by that small arm, not by the total. A rule of
thumb on the total would overstate power by a wide margin, which is exactly the
error that produces an underpowered confirmatory study.

Method: simulation rather than a closed form. A closed-form normal approximation
is unreliable at these cell counts -- the abstained arm at n=200 holds ~17 pages
with ~5 errors -- and the confirmatory test is Fisher's exact, so the power
calculation simulates the same test that will be run.

Effect sizes come from the discovery set and are *not* re-tuned here. Two are
carried:

  * the observed estimate, which is optimistic because the operating point was
    chosen on the same data (winner's curse);
  * a deliberately halved effect, because a confirmatory study sized on an
    optimistic estimate is the standard way these replicate at 40% power.

Nothing here reads the holdout. This file exists to be run *before* it does.
"""

from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path
from typing import Any

ALPHA = 0.05
TARGET_POWER = 0.80
TRIALS = 20000
SEED = 20260818


def _log_choose(n: int, k: int) -> float:
    """log C(n, k) via lgamma.

    The exact-integer form is correct but unusable here: this simulation calls
    the test about a million times and C(4800, 2400) is a 1,400-digit integer.
    lgamma keeps the exact test's decision while making it finish.
    """
    if k < 0 or k > n:
        return -math.inf
    return (
        math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)
    )


def fisher_exact_two_sided(a: int, b: int, c: int, d: int) -> float:
    rows, cols, total = (a + b, c + d), (a + c, b + d), a + b + c + d
    if total == 0 or 0 in rows or 0 in cols:
        return 1.0

    denominator = _log_choose(total, rows[0])

    def probability(x: int) -> float:
        return math.exp(
            _log_choose(cols[0], x) + _log_choose(cols[1], rows[0] - x) - denominator
        )

    observed = probability(a)
    low, high = max(0, rows[0] - cols[1]), min(rows[0], cols[0])
    return min(
        1.0,
        sum(
            p
            for p in (probability(x) for x in range(low, high + 1))
            if p <= observed * (1 + 1e-9)
        ),
    )


def power_at(
    n: int,
    abstention_rate: float,
    accepted_error: float,
    abstained_error: float,
    alpha: float,
    trials: int,
    seed: int,
) -> float:
    """Share of simulated holdouts where Fisher's exact test rejects.

    The abstained count is itself random -- the gate does not know in advance how
    many pages it will refuse -- so it is drawn per trial rather than fixed.
    """
    rng = random.Random(seed)  # noqa: S311 - a power simulation, not a key
    rejected = 0
    for _ in range(trials):
        # Counts are drawn directly rather than page by page. A per-page loop is
        # the same distribution and 4,800 times slower at the sizes this grid
        # reaches, which is enough to make the calculation not get run.
        abstained = rng.binomialvariate(n, abstention_rate)
        accepted = n - abstained
        bad_accepted = rng.binomialvariate(accepted, accepted_error)
        bad_abstained = rng.binomialvariate(abstained, abstained_error)
        p = fisher_exact_two_sided(
            bad_accepted,
            accepted - bad_accepted,
            bad_abstained,
            abstained - bad_abstained,
        )
        if p < alpha:
            rejected += 1
    return rejected / trials


def smallest_sufficient(
    abstention_rate: float,
    accepted_error: float,
    abstained_error: float,
    alpha: float,
    grid: tuple[int, ...],
    trials: int,
    seed: int,
) -> tuple[int | None, list[dict[str, Any]]]:
    curve = []
    answer = None
    for n in grid:
        value = power_at(
            n, abstention_rate, accepted_error, abstained_error, alpha, trials, seed
        )
        curve.append({"n": n, "power": value})
        if answer is None and value >= TARGET_POWER:
            answer = n
    return answer, curve


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cost-quality-receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    receipt = json.loads(args.cost_quality_receipt.resolve().read_text("utf-8"))
    configurations = receipt["configurations"]

    grid = (100, 150, 200, 300, 400, 600, 800, 1200, 1600, 2400, 3200, 4800)
    scenarios: dict[str, Any] = {}

    for name in ("stability_gate", "stability_and_agreement", "evidence_validity_gate"):
        gate = configurations[name]
        accepted = gate["accepted_pages"]
        abstained = receipt["page_count"] - accepted
        accepted_error = gate["errors_accepted"] / accepted
        abstained_error = gate["errors_abstained"] / abstained
        base = accepted_error

        for label, target in (
            ("observed_effect", abstained_error),
            # Halving the *difference*, not the rate: a winner's-curse discount
            # that keeps the direction and shrinks only what was selected on.
            ("halved_effect", base + (abstained_error - base) / 2.0),
        ):
            required, curve = smallest_sufficient(
                gate["abstention_rate"],
                accepted_error,
                target,
                ALPHA,
                grid,
                TRIALS,
                SEED,
            )
            scenarios[f"{name}::{label}"] = {
                "abstention_rate": gate["abstention_rate"],
                "accepted_error_rate": accepted_error,
                "abstained_error_rate": target,
                "risk_ratio": target / accepted_error if accepted_error else None,
                "smallest_n_reaching_80_percent_power": required,
                "power_at_the_discovery_set_size": power_at(
                    receipt["page_count"],
                    gate["abstention_rate"],
                    accepted_error,
                    target,
                    ALPHA,
                    TRIALS,
                    SEED,
                ),
                "power_curve": curve,
            }

    out = {
        "schema": "tavonel.a9-holdout-power.v1",
        "alpha": ALPHA,
        "target_power": TARGET_POWER,
        "test": "Fisher exact, two-sided, accepted versus abstained",
        "trials_per_point": TRIALS,
        "seed": SEED,
        "discovery_set_page_count": receipt["page_count"],
        "why_simulated": (
            "the abstained arm holds roughly 9 percent of the corpus, so cell "
            "counts are far too small for a normal approximation to be trusted; "
            "the simulation runs the same exact test the protocol will run"
        ),
        "winners_curse_note": (
            "The observed-effect row is optimistic: the operating point was chosen "
            "on the same data that produced the estimate. The halved-effect row is "
            "the number to size on."
        ),
        "scenarios": scenarios,
    }
    args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.output.resolve().write_text(
        json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    header = (
        f"{'scenario':44} {'abst':>6} {'acc err':>8} "
        f"{'abs err':>8} {'RR':>6} {'n@80%':>7} {'power@198':>10}"
    )
    print(header)
    for name, data in scenarios.items():
        required = data["smallest_n_reaching_80_percent_power"]
        print(
            f"{name:44} {data['abstention_rate']:6.3f} {data['accepted_error_rate']:8.3f} "
            f"{data['abstained_error_rate']:8.3f} "
            f"{(data['risk_ratio'] or 0):6.2f} "
            f"{(required if required else '>4800'):>7} "
            f"{data['power_at_the_discovery_set_size']:10.3f}"
        )
    print(f"receipt: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
