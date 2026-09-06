"""Re-run the current production selective-invalidation semantics against the oracle."""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "packages" / "cir-python" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "absorption" / "src"))

from akc_absorption.evolution_suite import build_suite  # noqa: E402
from akc_absorption.recompilation_diagnostic import run_counterfactuals  # noqa: E402


def main() -> int:
    cases = build_suite(documents=30)
    outcomes = [run_counterfactuals(case)["actual"] for case in cases]
    receipt = {
        "schema_version": "tavonel.selective_invalidation.production_promotion.v1",
        "suite_documents": 30,
        "cases": len(outcomes),
        "mean_rebuild_fraction": statistics.fmean(
            outcome.rebuild_fraction for outcome in outcomes
        ),
        "min_rebuild_fraction": min(outcome.rebuild_fraction for outcome in outcomes),
        "max_rebuild_fraction": max(outcome.rebuild_fraction for outcome in outcomes),
        "equivalent_cases": sum(outcome.equivalent for outcome in outcomes),
        "stale_left_behind_total": sum(outcome.stale_left_behind for outcome in outcomes),
        "gate": {
            "all_cases_equivalent": all(outcome.equivalent for outcome in outcomes),
            "zero_stale_left_behind": all(
                outcome.stale_left_behind == 0 for outcome in outcomes
            ),
            "mean_rebuild_fraction_below_0_20": statistics.fmean(
                outcome.rebuild_fraction for outcome in outcomes
            )
            < 0.20,
        },
        "historical_context": {
            "prior_core_mean_rebuild_fraction": 1.0,
            "source": "DIAG-B-01 committed historical receipt; corpus generation has since changed, so this is context rather than a paired statistical comparison",
        },
        "external_cost_usd": 0.0,
    }
    destination = ROOT / "research" / "experiments" / "DIAG-B-01" / "receipts"
    path = destination / "production-semantic-channel-promotion.json"
    path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, sort_keys=True))
    return 0 if all(receipt["gate"].values()) else 2


if __name__ == "__main__":
    raise SystemExit(main())