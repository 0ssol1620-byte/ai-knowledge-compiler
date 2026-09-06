"""Reproducible CPU pilot for silent critical-token corruption detection."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "packages" / "cir-python" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "absorption" / "src"))

from akc_absorption.assurance_experiment import (  # noqa: E402
    ExperimentObservation,
    ExperimentReceipt,
    ExperimentStage,
    ExperimentVariant,
)
from akc_absorption.synthetic_corruption import generate_corruptions  # noqa: E402
from akc_cir.critical_tokens import verify_critical_tokens  # noqa: E402


def main() -> int:
    observations: list[ExperimentObservation] = []
    mutation_counts: dict[str, int] = {}
    for seed in range(40):
        source = (
            f"Warranty ID AB-{200 + seed} is valid on 2026-08-15. "
            f"Limit is -{10 + seed % 7}.5 kg and price USD {1_250 + seed}."
        )
        # One clean control per source protects precision from a positives-only
        # synthetic suite.
        clean = verify_critical_tokens(
            source, source, expected_identifiers=[f"AB-{200 + seed}"]
        )
        observations.append(
            ExperimentObservation(
                sample_id=f"clean-{seed:03d}",
                expected_corrupted=False,
                detected_corruption=not clean.passed,
            )
        )
        for corruption in generate_corruptions(source, seed=seed):
            if corruption.expected_failure_family != "critical_token" or not corruption.changed:
                continue
            report = verify_critical_tokens(
                source,
                corruption.corrupted,
                expected_identifiers=[f"AB-{200 + seed}"],
            )
            mutation_counts[corruption.kind.value] = (
                mutation_counts.get(corruption.kind.value, 0) + 1
            )
            observations.append(
                ExperimentObservation(
                    sample_id=f"{corruption.kind.value}-{seed:03d}",
                    expected_corrupted=True,
                    detected_corruption=not report.passed,
                )
            )

    receipt = ExperimentReceipt.build(
        variant=ExperimentVariant.CRITICAL_TOKEN_VERIFIER,
        stage=ExperimentStage.CPU,
        corpus_id="synthetic-critical-token-v1",
        observations=observations,
        metadata={
            "generator": "akc_absorption.synthetic_corruption",
            "verifier": "akc_cir.critical_tokens",
            "seed_start": 0,
            "seed_end_exclusive": 40,
            "mutation_counts": mutation_counts,
            "external_cost_usd": 0.0,
        },
    )
    destination = ROOT / "research" / "experiments" / "ASSURANCE-A-01" / "receipts"
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / "cpu-critical-token-pilot.json"
    path.write_text(
        json.dumps(receipt.as_record(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt.as_record()["metrics"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())