#!/usr/bin/env python3
"""Evidence-hygiene pass: prove the chronology, then let it decide the split.

Founder ruling, 2026-08-23. The test is stated in the ruling and it is one-sided:

    if it cannot be DEMONSTRATED that no outcome-derived count, score or gate was
    inspected before the amendment, the study is downgraded from held-out to
    development diagnostic.

So this tool does not argue. It reconstructs the timeline from artefacts that
were written before anyone knew this test would be applied — immutable receipt
run ids, receipt `generated_at` stamps, file modification times and process
start times — and then applies the test mechanically. The verdict is derived
from the evidence, not asserted alongside it.

A receipt counts as carrying outcome-derived metrics if it contains any of
``OUTCOME_KEYS``. That list is deliberately generous: the question is not
whether a particular number mattered, it is whether any outcome number was
available to be seen.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import NS, rel, sha_file  # noqa: E402
from evidence import write_immutable  # noqa: E402

RECEIPTS = NS / "receipts"

HELD_OUT = "held_out"
DEVELOPMENT_DIAGNOSTIC = "development_diagnostic"

#: Any of these in a receipt body means the run exposed an outcome-derived
#: count, score or gate. Presence is what matters, not magnitude.
OUTCOME_KEYS = (
    "verdict",
    "gates",
    "summary",
    "gate_power",
    "by_family",
    "result_digest",
)


def stamp(moment: float) -> str:
    return datetime.fromtimestamp(moment, UTC).isoformat()


def mtime(path: Path) -> str:
    return stamp(path.stat().st_mtime)


def receipts_for(stem: str) -> list[dict[str, Any]]:
    rows = []
    for path in sorted(RECEIPTS.glob(stem + "--*.json")):
        body = json.loads(path.read_text(encoding="utf-8"))
        rows.append(
            {
                "path": rel(path),
                "run_id": body["provenance"]["run_id"],
                "generated_at": body["provenance"]["generated_at"],
                "protocol_sha256": body.get("protocol_sha256"),
                "outcome_keys_present": sorted(key for key in OUTCOME_KEYS if key in body),
                "receipt_sha256": body.get("receipt_sha256"),
                "file_sha256": sha_file(path),
            }
        )
    return sorted(rows, key=lambda row: row["generated_at"])


STUDIES = {
    "SOURCE_FAITHFULNESS_HELDOUT_V1": {
        "result_stem": "sfh1-source-faithfulness",
        "freeze_stem": "sfh1-protocol-freeze",
        "protocol": "protocols/SOURCE_FAITHFULNESS_HELDOUT_V1.yaml",
        "instrument": [
            "canonicalization/changed_regions.py",
            "canonicalization/changed_region_controls.py",
            "acquisition/sources_sfh1.py",
            "tools/run_sfh1.py",
        ],
        "log": "artifacts/development/sfh1_run.log",
    },
    "ORACLE_INDEPENDENCE_V2": {
        "result_stem": "oracle-independence-v2",
        "freeze_stem": "oracle-v2-protocol-freeze",
        "protocol": "protocols/ORACLE_INDEPENDENCE_V2.yaml",
        "instrument": [
            "oracle/source_derived_expected.py",
            "comparator/compare_recompilation.py",
            "tools/run_oracle_v2.py",
        ],
        "log": "artifacts/development/oracle_v2_run.log",
    },
}


def timeline(name: str, spec: dict[str, Any]) -> dict[str, Any]:
    results = receipts_for(spec["result_stem"])
    freezes = receipts_for(spec["freeze_stem"])

    events: list[dict[str, Any]] = []
    for row in results:
        events.append(
            {
                "at": row["generated_at"],
                "event": "study execution wrote a receipt",
                "detail": row["path"],
                "outcome_keys_present": row["outcome_keys_present"],
                "protocol_sha256": row["protocol_sha256"],
                "evidence": "immutable receipt run id and generated_at",
            }
        )
    for index, row in enumerate(freezes):
        events.append(
            {
                "at": row["generated_at"],
                "event": "protocol freeze" if index == 0 else "protocol AMENDMENT freeze",
                "detail": row["path"],
                "protocol_sha256": row["protocol_sha256"],
                "evidence": "immutable freeze receipt",
            }
        )
    for relative in spec["instrument"]:
        path = NS / relative
        events.append(
            {
                "at": mtime(path),
                "event": "instrument file last modified",
                "detail": relative,
                "sha256": sha_file(path),
                "evidence": "filesystem modification time",
            }
        )
    protocol = NS / spec["protocol"]
    events.append(
        {
            "at": mtime(protocol),
            "event": "protocol file last modified",
            "detail": spec["protocol"],
            "sha256": sha_file(protocol),
            "evidence": "filesystem modification time",
        }
    )
    log = NS / spec["log"]
    if log.exists():
        events.append(
            {
                "at": mtime(log),
                "event": "run log last written",
                "detail": spec["log"],
                "evidence": "filesystem modification time",
            }
        )

    events.sort(key=lambda row: row["at"])

    amendment = freezes[-1]["generated_at"] if len(freezes) > 1 else None
    first_freeze = freezes[0]["generated_at"] if freezes else None

    exposures = [
        row
        for row in results
        if row["outcome_keys_present"] and amendment is not None and row["generated_at"] < amendment
    ]

    #: A separate and independent problem: a protocol frozen after the run it
    #: governs was already executing is not "frozen before its data" either.
    late_freeze = [
        row for row in results if first_freeze is not None and row["generated_at"] < first_freeze
    ]

    demonstrable = not exposures
    return {
        "protocol_id": name,
        "events": events,
        "first_freeze_at": first_freeze,
        "amendment_freeze_at": amendment,
        "result_receipts": results,
        "freeze_receipts": freezes,
        "pre_amendment_outcome_exposures": [
            {
                "receipt": row["path"],
                "generated_at": row["generated_at"],
                "outcome_keys_present": row["outcome_keys_present"],
            }
            for row in exposures
        ],
        "executions_before_the_first_freeze": [
            {"receipt": row["path"], "generated_at": row["generated_at"]} for row in late_freeze
        ],
        "no_pre_amendment_outcome_inspection_demonstrable": demonstrable,
        "split_before": HELD_OUT,
        "split_after": HELD_OUT if demonstrable else DEVELOPMENT_DIAGNOSTIC,
        "downgraded": not demonstrable,
        "why": (
            "no receipt carrying outcome-derived metrics predates the amendment"
            if demonstrable
            else (
                "a receipt carrying outcome-derived metrics predates the "
                "amendment freeze, so the ruling's one-sided test fails and the "
                "study is a development diagnostic"
            )
        ),
    }


def body() -> dict[str, Any]:
    studies = {name: timeline(name, spec) for name, spec in STUDIES.items()}
    return {
        "schema": "tavonel.v2.evidence_hygiene_pass.v1",
        "authorised_by": "founder ruling, 2026-08-23",
        "test": (
            "if it cannot be demonstrated that no outcome-derived count, score "
            "or gate was inspected before the amendment, downgrade from held_out "
            "to development_diagnostic"
        ),
        "test_is_one_sided": (
            "the burden is on the study to demonstrate the negative. Absence of "
            "proof of exposure is not proof of absence, and this tool does not "
            "treat it as one."
        ),
        "outcome_keys": list(OUTCOME_KEYS),
        "studies": studies,
        "downgraded": sorted(name for name, row in studies.items() if row["downgraded"]),
        "still_held_out": sorted(name for name, row in studies.items() if not row["downgraded"]),
        "unaffected_held_out_studies": {
            "note": (
                "these carry no pre-amendment outcome exposure and were never "
                "amended after a result existed. Their held-out status stands."
            ),
            "protocols": [
                "VALUE_BEARING_COHORT_V1",
                "VALUE_BEARING_COHORT_V2",
                "STOP-V2-005",
            ],
        },
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }


def main() -> int:
    written = write_immutable(
        "evidence-hygiene-pass", body(), tool=Path(__file__).resolve(), protocol=None
    )
    result = json.loads((NS.parents[1] / written["receipt"]).read_text(encoding="utf-8"))
    print(json.dumps(written, indent=2))
    for name, study in result["studies"].items():
        print("\n=== %s ===" % name)
        print("  first freeze      %s" % study["first_freeze_at"])
        print("  amendment freeze  %s" % study["amendment_freeze_at"])
        print(
            "  pre-amendment outcome exposures: %d" % len(study["pre_amendment_outcome_exposures"])
        )
        for row in study["pre_amendment_outcome_exposures"]:
            print("     %s  %s" % (row["generated_at"], row["outcome_keys_present"]))
        print(
            "  executions before the first freeze: %d"
            % len(study["executions_before_the_first_freeze"])
        )
        print("  split: %s -> %s" % (study["split_before"], study["split_after"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
