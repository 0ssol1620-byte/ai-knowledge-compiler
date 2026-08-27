#!/usr/bin/env python3
"""Route A closure: the stopping record, and the end of the GPU authorisation.

The founder ruling names the record `STOP-V2-004`. That identifier is already
held by the P4d-Core-Semantic stop written on 2026-08-22, and the ledger is
append-only, so reusing it would overwrite evidence with evidence. The ruling
allows "an equivalent clear stopping record", and this is it at the next free
number, carrying the label the founder specified:

    STOP-V2-005 —
    EXACT_VALUE_MODEL_ENDPOINT_NOT_FEASIBLE_UNDER_DECLARED_PUBLIC_SOURCE_FRAME

Nothing here re-scores anything. The three failed preflights, their cohorts and
their receipts are read as they were written and cited by digest. No protocol,
extractor, scorer, bound, floor or family weighting is touched: the ruling
forbids fitting any of them to the observed result, and the point of a stopping
record is that it is what you write *instead* of moving a bar.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import NS, rel, sha_file  # noqa: E402
from evidence import write_immutable  # noqa: E402

STOP_ID = "STOP-V2-005"
LABEL = "EXACT_VALUE_MODEL_ENDPOINT_NOT_FEASIBLE_UNDER_DECLARED_PUBLIC_SOURCE_FRAME"
FOUNDER_LABEL = "STOP-V2-004"

MODEL_EXPERIMENT_STATUS = "NOT_RUN - PREDEFINED CPU PREFLIGHT INFEASIBLE"

#: Read-only, cited by digest, never re-scored.
EVIDENCE = {
    "model_endpoint_v1_protocol": "protocols/MODEL_ENDPOINT_V1.yaml",
    "model_endpoint_v1_preflight": (
        "receipts/model-endpoint-preflight--20260822T151517Z-43f9291f0970.json"
    ),
    "vbc1_protocol": "protocols/VALUE_BEARING_COHORT_V1.yaml",
    "vbc1_probe_cohort": "receipts/vbc1-probe-cohort--20260822T172038Z-6a613a7cdd69.json",
    "vbc1_probe_result": "receipts/vbc1-probe-result--20260822T172056Z-c718e6225611.json",
    "vbc2_protocol": "protocols/VALUE_BEARING_COHORT_V2.yaml",
    "vbc2_lineage_freeze": "receipts/vbc2-lineage-freeze--20260822T180457Z-45abaa4aeb52.json",
    "vbc2_cohort_complete": "receipts/vbc2-cohort--20260823T003429Z-7a819c36887d.json",
    "vbc2_preflight_final": "receipts/vbc2-preflight--20260823T003747Z-fdf18ce646cd.json",
    "value_fact_freeze": "receipts/value-fact-freeze--20260822T170435Z-7f50504835c5.json",
}

#: Frozen contract elements the ruling forbids fitting to the result. Recorded
#: with their digests so a later edit is visible rather than arguable.
UNCHANGED = {
    "twelve_revision_bound": "acquisition/sources_vbc2.py",
    "history_horizon_1460_days": "acquisition/sources_vbc2.py",
    "source_families_and_weighting": "acquisition/sources_vbc2.py",
    "value_scorer": "endpoint/value_scorer.py",
    "value_fact_taxonomy_and_extractor": "endpoint/value_fact.py",
    "cohort_floor_190": "tools/run_vbc2_preflight.py",
}

THREE_FAILURES = [
    {
        "protocol": "MODEL_ENDPOINT_V1",
        "population": "P4i locally-complete semantic-change questions",
        "n": 296,
        "survivors": 10,
        "why": (
            "a cohort selected for semantic change could not pose an exact-value "
            "question: 274 of 296 candidate pairs differed only in prose"
        ),
        "finding": "locally-complete semantic change != exact-value endpoint eligibility",
    },
    {
        "protocol": "VALUE_BEARING_COHORT_V1",
        "population": "45 fresh documents selected for value-bearing structure",
        "n": 174,
        "survivors": 0,
        "why": (
            "sources selected for value-bearing structure yielded no value-bearing "
            "revision under blind spaced-pair sampling: 174 properties read and "
            "paired, none moved"
        ),
        "finding": "value-bearing structure != observable value transition",
    },
    {
        "protocol": "VALUE_BEARING_COHORT_V2",
        "population": "2,271 fresh lineages walked complete by revision history",
        "n": 2271,
        "survivors": 3,
        "why": (
            "searching revision history for a moved value finds them at 3 in 2,271: "
            "1,107 lineages carry too few revisions in the horizon and 1,144 carry "
            "no qualifying transition inside the twelve-revision window"
        ),
        "finding": "value-bearing structure != frequently observable value transition",
    },
]


def digests(mapping: dict[str, str]) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for key, path in mapping.items():
        target = NS / path
        out[key] = {"path": rel(target), "sha256": sha_file(target)}
    return out


def body() -> dict[str, Any]:
    preflight = json.loads((NS / EVIDENCE["vbc2_preflight_final"]).read_text(encoding="utf-8"))
    return {
        "schema": "tavonel.v2.stopping_record.v1",
        "stop_id": STOP_ID,
        "label": LABEL,
        "founder_label": FOUNDER_LABEL,
        "identifier_note": (
            "the ruling names STOP-V2-004; that identifier is already held by the "
            "P4d-Core-Semantic stop of 2026-08-22 and the ledger is append-only, "
            "so this is the equivalent record at the next free number"
        ),
        "authorised_by": "founder ruling, 2026-08-23",
        "split": "development",
        "model_experiment_status": MODEL_EXPERIMENT_STATUS,
        "gpu_authorisation": {
            "state": "TERMINATED_FOR_THIS_RESEARCH_CYCLE",
            "seconds_used": 0,
            "spend_usd": 0.0,
            "ceiling_that_was_approved_usd": 40.0,
            "reinstatement": (
                "a new model study requires a separate protocol and a separate "
                "founder approval; this authorisation does not carry forward"
            ),
        },
        "vbc3_forbidden": (
            "no successor cohort may be created to chase the 190 floor. The floor, "
            "the bounds, the families, the weighting, the scorer and the taxonomy "
            "are not refitted to the observed yield"
        ),
        "final_result_preserved": {
            "lineages_walked": 2271,
            "lineages_available": 2271,
            "admitted": 3,
            "final_endpoint_cohort": 0,
            "NO_QUALIFYING_TRANSITION": 1144,
            "TOO_FEW_REVISIONS": 1107,
            "gpu_seconds": 0,
            "spend_usd": 0.0,
            "preflight_verdict": preflight["verdict"],
            "failed_gates": sorted(k for k, v in preflight["gates"].items() if not v),
            "passed_gates": sorted(k for k, v in preflight["gates"].items() if v),
        },
        "three_failures": THREE_FAILURES,
        "inc_v2_023_disposition": {
            "class": "POST_ACQUISITION_DIAGNOSTIC",
            "is_confirmatory_result": False,
            "not_to_be_called": (
                "the three post-fix exclusion reasons are a diagnostic of the "
                "locator, not a confirmatory result about the cohort"
            ),
            "effect_on_primary_stop_verdict": "none",
            "why_none": (
                "theoretical best case is 3 admitted of 3 admitted, and 3 < 190 under any locator"
            ),
            "repair_is_valid_forward": True,
        },
        "evidence": digests(EVIDENCE),
        "unchanged_frozen_contract": digests(UNCHANGED),
        "successor": "PAPER_CLOSURE_PROGRAM workstreams A, B and C",
    }


def main() -> int:
    written = write_immutable(
        "route-a-closure",
        body(),
        tool=Path(__file__).resolve(),
        protocol=NS / "protocols" / "VALUE_BEARING_COHORT_V2.yaml",
    )
    print(json.dumps(written, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
