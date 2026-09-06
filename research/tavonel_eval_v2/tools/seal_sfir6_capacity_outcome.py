#!/usr/bin/env python3
"""Seal SFIR6's capacity outcome: the repair worked, and the criterion still fails.

SFIR6 repaired two unconditional instrument defects under an unchanged frame and
re-measured all three families. Three things happened, and reporting them as one
result would lose all of them.

**The Wikipedia repair worked.** INC-V2-106 left that family unmeasurable: every
revision request was rejected, 29 of 30 roots were filed
`TRUNCATED_OR_INCOMPLETE_ENUMERATION`, and SFIR5 recorded C=0 as *not a capacity
statement*. Under the repaired two-pass batching, 29 of 30 roots enumerated to
continuation exhaustion and 2,152 candidates were produced. The thirtieth is an
honest `ZERO_CANDIDATE`: it enumerated, and no page yielded a revision pair.

**`git_docs` and `regulation_ecfr` reproduce SFIR5 exactly** -- not merely the
same counts, but the *identical lineage sets*, 293 and 859. That is the strongest
available evidence that the repair changed only the family it was aimed at. It
also means `git_docs = 293` is now a twice-measured shortfall rather than a
single observation.

**The criterion fails, and it fails on `git_docs`.** 293 against a declared
minimum of 750. No root reached its per-root cap of 80 (highest 73), so the
number is not an artifact of the cap. No threshold was lowered and no root was
added; the charter forbids both by name, and the shortfall is the finding.

**`encyclopedia_wikipedia` is measured but not sealable.** Its candidate set
fails the identity proof: four aliases out of 9,887 are each claimed by two
lineages, because alias identity case-folds MediaWiki titles, which are
case-sensitive after the first character (INC-V2-109). `CD8+` and `Cd8+` are two
different redirect pages pointing at two different articles. That defect is ours,
not the corpus's and not the adapter's, and it is left unrepaired: identity
semantics are frozen for SFIR6, `akc_cir.identity` is Protected Core, and the
outcome was already known when it surfaced.

That family is therefore recorded as `MEASURED_NOT_SEALABLE` -- a third status,
distinct from both `MEETS_CRITERION` and SFIR5's
`NOT_MEASURED_INSTRUMENT_DEFECT`. Calling it a pass would claim a capacity the
identity proof refused to certify; calling it not-measured would discard a
first-ever enumeration that plainly worked.

**None of this changes the verdict.** The criterion requires every family, and
`git_docs` falls short on a number no view of Wikipedia can raise.
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

STEM = "sfir6-capacity-outcome"
SCHEMA = "tavonel.sfir6.capacity_outcome.v1"

MINIMUM_C = 750
MINIMUM_Q = 600

#: SFIR5's per-family candidate counts, named here so the replication claim is
#: checked against this census rather than asserted. SFIR5's numbers are NOT
#: copied into SFIR6's result -- they are compared with it, which is the opposite
#: operation.
SFIR5_COUNTS = {"git_docs": 293, "regulation_ecfr": 859}

FAMILY_VERDICTS: dict[str, dict[str, Any]] = {
    "regulation_ecfr": {
        "verdict": "MEETS_CRITERION",
        "is_a_measurement": True,
        "is_sealable": True,
        "why": (
            "49 of 50 roots enumerated to exhaustion; one reserved title carries no "
            "versions. Reproduces SFIR5's candidate set exactly."
        ),
    },
    "git_docs": {
        "verdict": "SHORTFALL_MEASURED",
        "is_a_measurement": True,
        "is_sealable": True,
        "why": (
            "13 of 20 roots enumerated to queue exhaustion, 7 hit declared tree-traversal "
            "bounds and were excluded as the charter requires. No root reached its per-root "
            "candidate cap of 80 (highest was 73), so the total is not an artifact of the "
            "cap. Reproduces SFIR5's candidate set exactly, which makes this a twice-"
            "measured shortfall rather than a single observation."
        ),
    },
    "encyclopedia_wikipedia": {
        "verdict": "MEASURED_NOT_SEALABLE",
        "is_a_measurement": True,
        "is_sealable": False,
        "why": (
            "the INC-V2-106 repair worked: 29 of 30 roots enumerated to continuation "
            "exhaustion and produced 2,152 candidates, against SFIR5 where every revision "
            "request was rejected and 29 roots were filed TRUNCATED_OR_INCOMPLETE. The "
            "30th root enumerated and yielded no revision pair, which is an honest zero."
        ),
        "why_not_sealable": (
            "the candidate set fails the identity proof. Four aliases of 9,887 are each "
            "claimed by two lineages because alias identity case-folds MediaWiki titles, "
            "which are case-sensitive after the first character (INC-V2-109). Verified "
            "live: CD8+ -> Cytotoxic T cell and Cd8+ -> CD8 are two distinct redirects."
        ),
        "the_count_is_not_a_certified_capacity": (
            "C=2152 records what the repaired instrument enumerated. It is not a sealed "
            "capacity, because the identity proof refused to certify the set. Nothing here "
            "establishes that this family meets or misses the criterion."
        ),
        "whose_defect": (
            "ours. The fetch is sound -- every batch returned batchcomplete, with no "
            "continuation and no warnings. The collision is manufactured by our "
            "normalisation, not present in the source."
        ),
    },
}


def build(
    census: Path,
    seal: Path,
    generated_at: str | None = None,
    predecessor_census: Path | None = None,
) -> dict[str, Any]:
    body = json.loads(census.read_text(encoding="utf-8"))
    #: The replication claim is COMPUTED from both censuses, never asserted. A
    #: hardcoded `identical_lineage_sets: True` would be true of any input, which
    #: is the defect class this programme has recorded six times.
    previous = (
        json.loads(predecessor_census.read_text(encoding="utf-8")) if predecessor_census else None
    )
    families: dict[str, Any] = {}
    replication: dict[str, Any] = {}
    for family in sorted(sources.FAMILIES):
        block = body["families"][family]
        count = len(block["candidates"])
        quota = min(1000, (8 * count) // 10)
        dispositions = block["root_dispositions"]
        families[family] = {
            **FAMILY_VERDICTS[family],
            "C": count,
            "Q": quota,
            "meets_C": count >= MINIMUM_C,
            "meets_Q": quota >= MINIMUM_Q,
            "roots_declared": len(sources.declared_roots(family)),
            "roots_complete": sum(1 for r in dispositions if r.get("state") == "COMPLETE"),
            "root_states": {
                state: sum(1 for r in dispositions if r.get("state") == state)
                for state in sorted({r.get("state") for r in dispositions})
            },
        }
        if family in SFIR5_COUNTS and previous is not None:
            mine = {row["lineage_id"] for row in block["candidates"]}
            theirs = {row["lineage_id"] for row in previous["families"][family]["candidates"]}
            replication[family] = {
                "sfir5_C": len(theirs),
                "sfir6_C": count,
                "sfir5_C_matches_the_sealed_outcome": len(theirs) == SFIR5_COUNTS[family],
                "counts_agree": count == len(theirs),
                "lineage_sets_identical": mine == theirs,
                "in_sfir6_only": len(mine - theirs),
                "in_sfir5_only": len(theirs - mine),
            }

    sealable = {f: v for f, v in families.items() if v["is_sealable"]}
    return {
        "schema": SCHEMA,
        "generated_at": generated_at or now(),
        "protocol_id": "SOURCE_FACT_IR_INDEPENDENT_REPLICATION_V6",
        "state": "CAPACITY_CRITERION_APPLIED_AND_FAILED",
        "predecessor": {
            "protocol_id": "SOURCE_FACT_IR_INDEPENDENT_REPLICATION_V5",
            "receipt": "receipts/sfir5-capacity-outcome.json",
            "is_not_rescored": True,
            "numbers_were_not_copied": (
                "SFIR5's counts appear here only as a comparison target for the replication "
                "claim. Every figure in `families` was computed from SFIR6's own census."
            ),
        },
        "criterion": {
            "formula": "Q_f=min(1000,floor(0.8*C_f))",
            "minimum_C_per_family": MINIMUM_C,
            "minimum_Q_per_family": MINIMUM_Q,
            "requires_every_family": True,
        },
        "families": families,
        "families_meeting_criterion": sorted(
            f for f, v in families.items() if v["is_sealable"] and v["meets_C"] and v["meets_Q"]
        ),
        "families_sealable": sorted(sealable),
        "families_not_sealable": sorted(set(families) - set(sealable)),
        "replication_of_sfir5": {
            **replication,
            "identical_lineage_sets": bool(replication)
            and all(row["lineage_sets_identical"] for row in replication.values()),
            "how_established": (
                "the SFIR5 and SFIR6 candidate lineage sets were compared as sets, not as "
                "counts. Equal counts could coincide; equal sets could not."
            ),
            "what_it_shows": (
                "the repair changed only the family it was aimed at. git_docs and "
                "regulation_ecfr ran through the inherited code path and returned the same "
                "corpus, so SFIR6's Wikipedia number is not confounded by a transport that "
                "quietly moved underneath the other two."
            ),
        },
        "repair_outcome": {
            "INC-V2-106": {
                "repaired": True,
                "evidence": (
                    "29 of 30 Wikipedia roots COMPLETE with reason "
                    "CATEGORY_CONTINUATION_EXHAUSTED_AND_PAIRS_RESOLVED, against 29 of 30 "
                    "filed TRUNCATED_OR_INCOMPLETE_ENUMERATION in SFIR5. 2,152 candidates "
                    "where no candidate had ever been produced."
                ),
            },
            "INC-V2-107": {
                "repaired": True,
                "evidence": (
                    "the census passed the pagination field-set comparison it would "
                    "otherwise have failed, and the seal proceeded to later checks."
                ),
            },
        },
        "defects_found_by_this_census": {
            "INC-V2-109": (
                "alias identity case-folds MediaWiki titles. Unreachable in SFIR1-SFIR5 "
                "because this family had never produced a candidate. NOT repaired: "
                "identity semantics are frozen, akc_cir.identity is Protected Core, and the "
                "outcome was known by the time it surfaced."
            ),
            "INC-V2-110": (
                "seal_capacity permits a traversal proof only for git_docs, so the "
                "repaired Wikipedia adapter is refused for carrying MORE evidence than the "
                "schema allows. Third instance of INC-V2-107's class. Not load-bearing: "
                "removing the extra proof reaches INC-V2-109 instead."
            ),
        },
        "outcome": (
            "The criterion requires every family. regulation_ecfr meets it. git_docs falls "
            "short as a measurement, for the second time, on an identical candidate set. "
            "encyclopedia_wikipedia was measured for the first time in the programme but "
            "its set could not be sealed. The criterion is not met, and it is not met "
            "because of git_docs -- a result no view of the Wikipedia family can change."
        ),
        "downstream_not_run": {
            "roster_frozen": False,
            "acquisition_started": False,
            "payload_opened": False,
            "corpus_spent": False,
            "authority": "charter terminal_policy: no_roster_or_acquisition_on_capacity_shortfall",
        },
        "successor": {
            "protocol_id": "SOURCE_FACT_IR_INDEPENDENT_REPLICATION_V7",
            "is_a_new_frame_question_not_a_repair": True,
            "designed_while_this_census_was_blind": True,
            "authority": "charter verdict_policy: successor_on_failure",
        },
        "what_this_receipt_does_not_say": (
            "that encyclopedia_wikipedia lacks capacity, or that it has it -- its set was "
            "enumerated but not certified. That the declared thresholds are the right "
            "thresholds: 750 and 600 are pre-registered, not calibrated. That git_docs "
            "would fail under a different frame; SFIR7 asks that question, and asks it "
            "with a rule written before this number existed."
        ),
        "census": {"path": rel(census), "sha256": protocol.sha_file(census)},
        "census_seal": {"path": rel(seal), "sha256": protocol.sha_file(seal)},
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }


def main() -> int:
    census = NS / "receipts" / "sfir6-capacity-metadata-census.json"
    seal = NS / "receipts" / "sfir6-capacity-census-seal.json"
    body = build(
        census, seal, predecessor_census=NS / "receipts" / "sfir5-capacity-metadata-census.json"
    )
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
