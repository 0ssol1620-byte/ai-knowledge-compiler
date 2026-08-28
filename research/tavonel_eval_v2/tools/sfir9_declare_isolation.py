#!/usr/bin/env python3
"""Assemble the real SFIR9 isolation declaration and put it through the gate.

This is a producer, not a component. It reads the ten components' bytes, names
the historical artifacts SFIR9 touches together with the reason each is
permissible, and hands the result to `sfir9_isolation_gate`, which is the
authority and is itself one of the ten. Nothing here decides anything the gate
does not decide; if this script were swapped, the gate's proof would still be the
thing recorded, and the closure still covers the gate.

**The two states are written side by side, on purpose.** The historical chain is
`FAIL` with 59 frozen drifts preserved, and SFIR9's prospective integrity is
evaluated on its own evidence. Neither number is allowed to stand in for the
other, and no attempt is made here to make the historical half green.

**Exactly one historical artifact is read, and it is read for what it says went
wrong.** `receipts/frozen-instrument-integrity.json` supplies the failure
taxonomy and the list of paths whose historical pins must never be treated as
certifying current source. It is declared `value_bearing = false` and never
opened for writing.

Run it to produce `receipts/sfir9-historical-isolation.json`.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import sfir9_execution_closure as closure_module  # noqa: E402
import sfir9_isolation_gate as gate  # noqa: E402

REPO = NS.parents[1]
DRIFT_RECEIPT = NS / "receipts/frozen-instrument-integrity.json"
OUTPUT = NS / "receipts/sfir9-historical-isolation.json"

#: The single historical artifact SFIR9 reads, and why that is permissible.
FAILURE_TAXONOMY_PURPOSE = "failure_taxonomy"


def historical_inputs() -> list[gate.HistoricalInput]:
    raw = DRIFT_RECEIPT.read_bytes()
    return [
        gate.HistoricalInput(
            path=DRIFT_RECEIPT.relative_to(REPO).as_posix(),
            sha256="sha256:" + hashlib.sha256(raw).hexdigest(),
            purpose=FAILURE_TAXONOMY_PURPOSE,
            value_bearing=False,
            why_not_scientific_authority=(
                "read for what it records about a failed reproducibility chain: "
                "which paths drifted from their frozen pins, and which receipts are "
                "therefore unusable as certification. No SFIR9 gate passes because "
                "of anything in this file, no threshold is derived from it, and no "
                "SFIR9 result is compared against one of its numbers. It is opened "
                "read-only and is never rewritten -- repairing it would destroy the "
                "record of the failure it exists to document."
            ),
        )
    ]


def declaration() -> gate.Sfir9Declaration:
    """The ten components, their freshly computed digests, and nothing borrowed."""
    components: dict[str, str] = {}
    digests: dict[str, str] = {}
    for component in closure_module.COMPONENTS:
        path = REPO / component.relative_path
        components[component.name] = component.relative_path
        digests[component.relative_path] = (
            "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        )
    return gate.Sfir9Declaration(
        components=components,
        historical_inputs=historical_inputs(),
        # Empty on purpose. No historical receipt is a prerequisite of an SFIR9
        # gate, and an entry here would be refused by the gate rather than
        # recorded.
        scientific_prerequisites=[],
        source_digests=digests,
        # SFIR9 freezes the current bytes afresh. It does not claim any component
        # continues a historical pin, and specifically not the 650766c4 pin whose
        # drift is preserved in the receipt above.
        claims_continuity_with_historical_pin=False,
    )


def build() -> dict[str, Any]:
    drift = gate.read_drift(DRIFT_RECEIPT)
    proof = gate.evaluate(declaration(), drift, root=REPO)
    return {
        **proof,
        "produced_by": {
            "path": Path(__file__).resolve().relative_to(REPO).as_posix(),
            "sha256": "sha256:"
            + hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "is_a_closure_component": False,
            "why_not": (
                "this assembles a declaration; the gate evaluates it. The gate is "
                "one of the ten and is covered by the execution closure, so a "
                "swapped producer cannot change what the gate concluded."
            ),
        },
    }


def main() -> int:
    receipt = build()
    OUTPUT.write_bytes(
        json.dumps(receipt, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    )
    historical = receipt["HISTORICAL_INSTRUMENT_INTEGRITY"]
    print(f"HISTORICAL_INSTRUMENT_INTEGRITY = {historical['state']}, "
          f"frozen drift = {historical['historical_frozen_drift_count']}, "
          f"preserved = {str(historical['preserved']).lower()}")
    print(f"SFIR9_PROSPECTIVE_INTEGRITY = "
          f"{receipt['SFIR9_PROSPECTIVE_INTEGRITY']['state']}")
    print(f"components = {len(receipt['SFIR9_PROSPECTIVE_INTEGRITY']['components'])}")
    print(f"historical authority dependencies = "
          f"{receipt['SFIR9_PROSPECTIVE_INTEGRITY']['sfir9_historical_authority_dependencies']}")
    print(f"written to {OUTPUT.relative_to(REPO).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
