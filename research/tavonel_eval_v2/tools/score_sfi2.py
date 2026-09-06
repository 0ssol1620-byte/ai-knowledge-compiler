#!/usr/bin/env python3
"""Score SFI2 against all seven endpoints. One writer, one receipt, no acquisition.

The founder's ruling on this study is narrower than V1's in exactly one way, and
the whole tool is shaped by it:

    V2 PASS requires all E1-E7 to be exercised and met where applicable.
    E5/E6 may not be SKIPPED.

V1 failed on three grounds and two of them were absences — E5 and E6 reported
SKIPPED_NEVER_EXERCISED because nothing in that run rebuilt an artifact. This
scorer cannot produce that outcome by accident and cannot produce a PASS despite
it: E5 and E6 are read from a real rebuild summary or they are SKIPPED, and a
SKIPPED endpoint fails the study.

What this tool refuses to do:

* it never fetches, and it never re-admits. Admission is the worker's
  deterministic reduction, pinned by `reduction_digest`.
* it never answers E5 or E6 from facts. Facts describe what the IR recognised;
  equivalence and stale escape are claims about rebuilt artifacts, and a scorer
  that answered them from facts would be inventing the programme's central
  result rather than measuring it.
* it never reports an endpoint met because nothing exercised it.
* it never lowers the cohort floor to reach a verdict. 200 pairs and 3 families
  were fixed before any count existed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
for _sub in ("tools", "acquisition", "canonicalization", "compiler", "source_fact_ir"):
    sys.path.insert(0, str(NS / _sub))
sys.path.insert(0, str(NS))

from common import canonical_sha, now, rel, sha_file  # noqa: E402
from evidence import write_immutable  # noqa: E402

#: E1-E4 and E7 are measured from facts, and they are measured the SAME way V1
#: measured them. Importing rather than restating is deliberate: a
#: re-implementation that drifted by a line would make the two studies
#: incomparable while looking like a repeat, and the point of V2 is to be a
#: comparable repeat of V1 on a changed system.
from score_sfi1 import FAILED, MET, SKIPPED, endpoint_rows, summary  # noqa: E402

ACQUISITION = NS / "artifacts" / "development" / "sfi2" / "sfi2_acquisition.json"
PROTOCOL = NS / "protocols" / "SOURCE_FACT_IR_HELDOUT_V2.yaml"

FACT_ENDPOINTS: tuple[str, ...] = (
    "E1_no_unclassified_changed_regions",
    "E2_no_recognized_but_unrepresented",
    "E3_no_silent_loss_in_a_complete_scope",
    "E4_no_reference_or_locator_only_clean_miss",
    "E7_unresolved_fails_closed",
)
REBUILD_ENDPOINTS: tuple[str, ...] = (
    "E5_no_confirmed_selective_stale_escape",
    "E6_exact_selective_vs_clean_equivalence",
)
ENDPOINTS: tuple[str, ...] = (
    "E1_no_unclassified_changed_regions",
    "E2_no_recognized_but_unrepresented",
    "E3_no_silent_loss_in_a_complete_scope",
    "E4_no_reference_or_locator_only_clean_miss",
    "E5_no_confirmed_selective_stale_escape",
    "E6_exact_selective_vs_clean_equivalence",
    "E7_unresolved_fails_closed",
)

#: (endpoint id, key in the rebuild summary, violation count, named cases).
#: Module level so the integration gate can assert every key here exists in what
#: `rebuild_equivalence.summarise` actually writes. It did not, and a mismatch
#: went unnoticed through a run.
REBUILD_BLOCKS: tuple[tuple[str, str, str, str], ...] = (
    (
        "E5_no_confirmed_selective_stale_escape",
        "E5_confirmed_selective_stale_escape",
        "pairs_with_confirmed_escape",
        "confirmed",
    ),
    (
        "E6_exact_selective_vs_clean_equivalence",
        "E6_exact_selective_vs_clean_equivalence",
        "pairs_divergent",
        "divergent",
    ),
)

#: Fixed by the founder before any count existed. Restated here so that lowering
#: one is a visible edit to a scoring tool rather than an argument in a shell.
COHORT_FLOOR_PAIRS = 200
FAMILIES_REQUIRED = 3


class NotFrozen(RuntimeError):
    """Scoring an unfrozen protocol is scoring nothing."""


def frozen_protocol() -> dict[str, Any]:
    """The freeze receipt, or a refusal.

    Same rule as V1 and for the same reason: a scorer that runs against a draft
    produces a number whose rules could still move to fit it.
    """
    freezes = sorted((NS / "receipts").glob("sfi2-protocol-freeze--*.json"))
    if not freezes:
        raise NotFrozen(
            "no sfi2-protocol-freeze receipt exists. The protocol must be frozen "
            "before a single fresh lineage is read."
        )
    body = json.loads(freezes[-1].read_text(encoding="utf-8"))
    actual = sha_file(PROTOCOL)
    if body.get("protocol_sha256") != actual:
        raise NotFrozen(
            f"the protocol has moved since it was frozen: {actual} is not "
            f"{body.get('protocol_sha256')}"
        )
    #: the receipt path, because the freeze receipt carries no top-level run_id
    #: and a scored result whose provenance pointer is null cannot be followed
    #: back to the freeze it claims.
    body["receipt_path"] = rel(freezes[-1])
    return body


def score_rebuild(rebuild: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """E5 and E6, from the rebuild summary and from nothing else.

    `pairs_that_could_have_exhibited` is the denominator that decides whether the
    endpoint may be called met at all. Zero means the cohort never put the
    endpoint at risk. The founder forbade SKIPPED here, which is a requirement on
    the COHORT — it must contain pairs where a stale artifact could have escaped
    — not a licence for the scorer to call an unexercised endpoint met.
    """
    verdicts: dict[str, dict[str, Any]] = {}
    if not rebuild:
        for endpoint in REBUILD_ENDPOINTS:
            verdicts[endpoint] = {
                "verdict": SKIPPED,
                "why": (
                    "no rebuild summary in the acquisition artifact. Nothing in this "
                    "run rebuilt an artifact, so the endpoint was not measured"
                ),
                "violations": None,
                "pairs_exercising": 0,
            }
        return verdicts

    #: (endpoint id, key in the rebuild summary, violation count, named cases).
    #: The endpoint id and the summary key are DIFFERENT STRINGS for E5 and the
    #: difference is not cosmetic: the protocol names the endpoint for the
    #: property it asserts ("no confirmed escape"), while the executor names its
    #: block for what it measured ("confirmed escape"). Assuming they were the
    #: same string is what made the first scored run report E5 as never
    #: exercised while 14 confirmed escapes sat in the receipt beside it.
    for endpoint, summary_key, violated_key, names_key in REBUILD_BLOCKS:
        if summary_key not in rebuild:
            #: A key the executor does not write is a contract break, not an
            #: unexercised endpoint. Reporting it as SKIPPED would be a scorer
            #: describing its own bug as a property of the cohort.
            raise KeyError(
                f"the rebuild summary has no block {summary_key!r}; the scorer and "
                f"the executor disagree about the contract, and {endpoint} cannot "
                "be read from it"
            )
        block = rebuild[summary_key]
        exercising = int(block.get("pairs_that_could_have_exhibited", 0))
        violations = int(block.get(violated_key, 0))
        if not exercising or not block.get("gate_power"):
            verdicts[endpoint] = {
                "verdict": SKIPPED,
                "why": (
                    "no judged supported pair in this cohort could have exhibited it. "
                    "The rebuild ran; the cohort did not put the endpoint at risk"
                ),
                "violations": violations,
                "pairs_exercising": 0,
            }
            continue
        verdicts[endpoint] = {
            "verdict": MET if violations == 0 else FAILED,
            "why": None,
            "violations": violations,
            "pairs_exercising": exercising,
            #: named cases, never counts alone. A count cannot be checked against
            #: a rebuild and the ruling is about named artifacts.
            "cases": block.get(names_key, []),
        }
    return verdicts


def score(rows: list[dict[str, Any]], rebuild: dict[str, Any] | None) -> dict[str, Any]:
    """Endpoint verdicts, each with the power that earned it."""
    verdicts: dict[str, Any] = {}
    for endpoint in FACT_ENDPOINTS:
        violations = sum(row[endpoint][0] for row in rows)
        exercising = sum(1 for row in rows if row[endpoint][1])
        if not exercising:
            verdicts[endpoint] = {
                "verdict": SKIPPED,
                "why": "no pair in this cohort could have violated it",
                "violations": 0,
                "pairs_exercising": 0,
            }
            continue
        verdicts[endpoint] = {
            "verdict": MET if violations == 0 else FAILED,
            "why": None,
            "violations": violations,
            "pairs_exercising": exercising,
        }
    verdicts.update(score_rebuild(rebuild))
    return {endpoint: verdicts[endpoint] for endpoint in ENDPOINTS}


def cohort_gates(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """The two composition requirements, checked as gates rather than as prose.

    A study that meets every endpoint on 40 pairs from one family has not shown
    what this study set out to show, and the floor was fixed before any count
    existed so that this check could never become an argument.
    """
    families = sorted({row["family"] for row in rows})
    return {
        "pairs_scored": len(rows),
        "pairs_required": COHORT_FLOOR_PAIRS,
        "pairs_met": len(rows) >= COHORT_FLOOR_PAIRS,
        "families": families,
        "families_required": FAMILIES_REQUIRED,
        "families_met": len(families) >= FAMILIES_REQUIRED,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--acquisition", default=str(ACQUISITION))
    arguments = parser.parse_args(argv)

    freeze = frozen_protocol()

    path = Path(arguments.acquisition)
    if not path.exists():
        print(f"no acquisition artifact at {rel(path)}; nothing to score", file=sys.stderr)
        return 3
    acquired = json.loads(path.read_text(encoding="utf-8"))

    rows = [endpoint_rows(pair) for pair in acquired["admitted"]]
    rebuild = acquired.get("rebuild")
    verdicts = score(rows, rebuild)
    gates = cohort_gates(rows)

    failed = [name for name, row in verdicts.items() if row["verdict"] == FAILED]
    skipped = [name for name, row in verdicts.items() if row["verdict"] == SKIPPED]
    short = [
        name
        for name, met in (("pairs", gates["pairs_met"]), ("families", gates["families_met"]))
        if not met
    ]

    body: dict[str, Any] = {
        "schema": "tavonel.v2.sfi2_score.v1",
        "protocol": rel(PROTOCOL),
        "protocol_sha256": sha_file(PROTOCOL),
        "protocol_freeze_receipt": freeze["receipt_path"],
        "split": "held_out",
        "predecessor": {
            "study": "SOURCE_FACT_IR_HELDOUT_V1",
            "verdict": "FAIL",
            "standing": "frozen, never rescored; its corpus is development material",
        },
        "acquisition": rel(path),
        "acquisition_sha256": sha_file(path),
        "reduction_digest": acquired.get("reduction_digest"),
        "generated_at": now(),
        "summary": summary(rows),
        "cohort_gates": gates,
        "endpoints": verdicts,
        "endpoints_failed": failed,
        "endpoints_skipped": skipped,
        "cohort_gates_short": short,
        "rebuild_summary_present": bool(rebuild),
        "verdict": "PASS" if not failed and not skipped and not short else "FAIL",
        "verdict_rule": (
            "PASS requires every one of the seven endpoints MET, plus the cohort "
            "floor. A FAILED endpoint fails the study; a SKIPPED endpoint fails it "
            "too, because an endpoint that was never exercised has not been "
            "satisfied, it has been avoided. E5 and E6 in particular may not be "
            "SKIPPED: V1 failed on exactly that absence and this study exists to "
            "answer them."
        ),
        "rows": rows,
        "rebuild": rebuild,
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }
    body["result_digest"] = canonical_sha(
        {
            "endpoints": {name: row["verdict"] for name, row in verdicts.items()},
            "summary": body["summary"],
            "cohort_gates": {
                "pairs_scored": gates["pairs_scored"],
                "families": gates["families"],
            },
        }
    )

    written = write_immutable(
        "sfi2-native-provenance", body, tool=Path(__file__).resolve(), protocol=PROTOCOL
    )
    print(
        json.dumps(
            {
                **written,
                "verdict": body["verdict"],
                "failed": failed,
                "skipped": skipped,
                "cohort_short": short,
            },
            indent=2,
        )
    )
    return 0 if body["verdict"] == "PASS" else 4


if __name__ == "__main__":
    raise SystemExit(main())
