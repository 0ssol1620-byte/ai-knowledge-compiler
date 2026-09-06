#!/usr/bin/env python3
"""Seal SFIR5's capacity outcome: the criterion was applied, and it failed.

This is the first receipt in the programme that records an *applied* capacity
criterion. SFIR1, SFIR2, SFIR3 and SFIR4 all stopped before reaching one --
`sfir4-terminal-operational-stop.json` says in as many words that SFIR4's
`scientific_threshold_evaluated` is `false`. SFIR5 completed a census, sealed it,
and the criterion was evaluated against it.

The result is a failure, and the failure has two causes that must not be
reported as one:

**`regulation_ecfr` meets the criterion.** C=859, Q=687, against C>=750 and
Q>=600.

**`git_docs` falls short, and that is a measurement.** C=293. Thirteen of twenty
roots enumerated to queue exhaustion; seven hit declared tree-traversal bounds
and were excluded, which the charter requires. No root reached its per-root
candidate cap, so the number is not an artifact of the cap. This is what the
declared frame yields under the declared bounds.

**`encyclopedia_wikipedia` was never measured, and its zero is not a capacity
statement.** Every revision request the adapter issued was rejected by the
endpoint. It supplies 50 page ids together with `rvlimit=2`, and MediaWiki
answers `invalidparammix`: those parameters "may only be used on a single page".
So `seen_batch != set(batch)` on every root, every root was filed
`TRUNCATED_OR_INCOMPLETE_ENUMERATION`, and no candidate could ever have been
produced. 29 of 30 roots show exactly that; the 30th enumerated an empty
category.

Reporting C=0 for that family as a capacity result would be the worst kind of
false negative available here -- a broken instrument's silence presented as a
measured absence. It is recorded as NOT_MEASURED and the criterion is reported
as inapplicable to it.

A separate defect is recorded because it would otherwise look like the cause:
`seal_capacity` refuses this census with "pagination proof drifted" before it
reaches any capacity arithmetic, because `CAPACITY_PAGINATION_FIELDS` compares
the pagination block by strict set equality and the INC-V2-098 repair added two
fields to that block without updating it. Corrected in memory, the refusal
becomes "capacity shortfall". The defect therefore does not change this outcome,
and that was established by running it, not by arguing it.

Nothing downstream runs. The charter's `terminal_policy` says
`no_roster_or_acquisition_on_capacity_shortfall`, so there is no roster, no
acquisition, no payload read and no corpus spent.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import sfir4_protocol as protocol  # noqa: E402
from acquisition import sources_sfir4 as sources  # noqa: E402
from common import now, rel  # noqa: E402

STEM = "sfir5-capacity-outcome"
SCHEMA = "tavonel.sfir5.capacity_outcome.v1"

MINIMUM_C = 750
MINIMUM_Q = 600

FAMILY_VERDICTS: dict[str, dict[str, Any]] = {
    "regulation_ecfr": {
        "verdict": "MEETS_CRITERION",
        "is_a_measurement": True,
        "why": "49 of 50 roots enumerated to exhaustion; one reserved title carries no versions",
    },
    "git_docs": {
        "verdict": "SHORTFALL_MEASURED",
        "is_a_measurement": True,
        "why": (
            "13 of 20 roots enumerated to queue exhaustion, 7 hit declared tree-traversal "
            "bounds and were excluded as the charter requires. No root reached its per-root "
            "candidate cap of 80 (highest was 73), so the total is not an artifact of the cap. "
            "This is what the declared frame yields under the declared bounds."
        ),
    },
    "encyclopedia_wikipedia": {
        "verdict": "NOT_MEASURED_INSTRUMENT_DEFECT",
        "is_a_measurement": False,
        "why": (
            "every revision request was rejected by the endpoint. The adapter supplies 50 "
            "page ids together with rvlimit=2; MediaWiki answers invalidparammix, because "
            "rvlimit 'may only be used on a single page'. Every root therefore failed the "
            "seen_batch == set(batch) check and was filed "
            "TRUNCATED_OR_INCOMPLETE_ENUMERATION. No candidate could have been produced by "
            "any input."
        ),
        "the_zero_is_not_a_capacity_statement": (
            "C=0 here records that the instrument never enumerated, not that the declared "
            "categories lack revised pages. Nothing in this programme establishes the "
            "capacity of this family in either direction."
        ),
    },
}


def build(census: Path, seal: Path, generated_at: str | None = None) -> dict[str, Any]:
    body = json.loads(census.read_text(encoding="utf-8"))
    families: dict[str, Any] = {}
    for family in sorted(sources.FAMILIES):
        block = body["families"][family]
        count = len(block["candidates"])
        quota = min(1000, (8 * count) // 10)
        declared = len(sources.declared_roots(family))
        complete = sum(1 for row in block["root_dispositions"] if row.get("state") == "COMPLETE")
        families[family] = {
            **FAMILY_VERDICTS[family],
            "C": count,
            "Q": quota,
            "meets_C": count >= MINIMUM_C,
            "meets_Q": quota >= MINIMUM_Q,
            "roots_declared": declared,
            "roots_complete": complete,
            "root_states": {
                state: sum(1 for row in block["root_dispositions"] if row.get("state") == state)
                for state in sorted({row.get("state") for row in block["root_dispositions"]})
            },
        }

    measured = {f: v for f, v in families.items() if v["is_a_measurement"]}
    return {
        "schema": SCHEMA,
        "generated_at": generated_at or now(),
        "protocol_id": "SOURCE_FACT_IR_INDEPENDENT_REPLICATION_V5",
        "state": "CAPACITY_CRITERION_APPLIED_AND_FAILED",
        "first_applied_criterion_in_the_programme": True,
        "why_that_is_notable": (
            "SFIR1 through SFIR4 each stopped before the criterion could be applied. "
            "SFIR4's stop receipt records scientific_threshold_evaluated: false. This is "
            "the first census in the programme that was completed and evaluated."
        ),
        "criterion": {
            "formula": "Q_f=min(1000,floor(0.8*C_f))",
            "minimum_C_per_family": MINIMUM_C,
            "minimum_Q_per_family": MINIMUM_Q,
            "requires_every_family": True,
        },
        "families": families,
        "families_meeting_criterion": sorted(
            f for f, v in families.items() if v["meets_C"] and v["meets_Q"]
        ),
        "families_measured": sorted(measured),
        "families_not_measured": sorted(set(families) - set(measured)),
        "outcome": (
            "The criterion requires every family. One family meets it, one falls short as "
            "a measurement, and one was not measured at all. The criterion is not met, and "
            "it cannot be met on this census whatever view is taken of the unmeasured "
            "family."
        ),
        "downstream_not_run": {
            "roster_frozen": False,
            "acquisition_started": False,
            "payload_opened": False,
            "corpus_spent": False,
            "authority": "charter terminal_policy: no_roster_or_acquisition_on_capacity_shortfall",
        },
        "seal_side_defect": {
            "what": (
                "seal_capacity refuses this census with 'encyclopedia_wikipedia pagination "
                "proof drifted' before reaching any capacity arithmetic. "
                "CAPACITY_PAGINATION_FIELDS compares the pagination block by strict set "
                "equality, and the INC-V2-098 repair added retries_total and "
                "transport_retries to that block without updating it."
            ),
            "consequence_if_uncorrected": (
                "seal_capacity would refuse EVERY census, for every family, whatever the "
                "data. It went unseen because all four SFIR4 runs died before producing a "
                "census, so this path had never been exercised on real output."
            ),
            "does_it_change_this_outcome": False,
            "how_that_was_established": (
                "the field set was corrected in memory and seal_capacity re-run against the "
                "same sealed census; the refusal became 'encyclopedia_wikipedia capacity "
                "shortfall'. Established by running it, not by arguing it. The frozen module "
                "on disk was not edited."
            ),
        },
        "what_this_receipt_does_not_say": (
            "that encyclopedia_wikipedia lacks capacity. Its instrument never enumerated, "
            "and a broken instrument's silence is not a measured absence. It also does not "
            "say that the two measured families are wrong -- git_docs fell short under "
            "declared bounds with no cap reached, and regulation_ecfr met the criterion."
        ),
        "census": {"path": rel(census), "sha256": protocol.sha_file(census)},
        "census_seal": {"path": rel(seal), "sha256": protocol.sha_file(seal)},
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }


def main() -> int:
    census = NS / "receipts" / "sfir5-capacity-metadata-census.json"
    seal = NS / "receipts" / "sfir5-capacity-census-seal.json"
    body = build(census, seal)
    body["content_sha256"] = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    written = protocol.write_immutable(NS / "receipts" / f"{STEM}.json", body)
    print(json.dumps({"state": body["state"], "path": written.as_posix()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
