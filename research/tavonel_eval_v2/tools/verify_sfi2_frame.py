#!/usr/bin/env python3
"""Was the frame actually exhausted, or did the run simply stop?

Step one of the founder's completion order: *verify complete/exhausted frame*
before scoring. It is a separate tool and a separate question from scoring, and
it runs first, because the two failures it distinguishes look identical in an
artifact:

    the run considered every candidate it had          -> exhausted
    the run met its quotas and stopped early           -> complete
    the run stopped for some other reason              -> NEITHER

The third is the one worth catching. A crashed pool, a truncated frame or a
silent break would leave a cohort that is smaller than it should be, and every
downstream number would be computed over it without complaint — the scorer would
report honest counts of a dishonest cohort. Nothing in the scored receipt would
look wrong, because nothing in it describes what was never attempted.

This tool reads. It never fetches, never re-admits, never writes to the
acquisition artifact, and it does not score.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
for _sub in ("tools", "acquisition"):
    sys.path.insert(0, str(NS / _sub))
sys.path.insert(0, str(NS))

from common import now, rel, sha_file  # noqa: E402
from evidence import write_immutable  # noqa: E402

ACQUISITION = NS / "artifacts" / "development" / "sfi2" / "sfi2_acquisition.json"

EXHAUSTED = "EXHAUSTED_EVERY_CANDIDATE_CONSIDERED"
COMPLETE = "COMPLETE_ALL_QUOTAS_FILLED"
NEITHER = "NEITHER_STOPPED_FOR_ANOTHER_REASON"


def assess(acquired: dict[str, Any], quotas: dict[str, int]) -> dict[str, Any]:
    """Which of the three endings this run had, and the arithmetic behind it."""
    candidates = int(acquired.get("frame", {}).get("candidates", 0))
    considered = int(acquired.get("lineages_considered", 0))
    by_family: dict[str, int] = dict(acquired.get("by_family", {}))
    admitted = acquired.get("admitted", [])

    quotas_filled = {family: by_family.get(family, 0) >= quota for family, quota in quotas.items()}
    all_quotas_filled = all(quotas_filled.values())
    every_candidate_considered = considered >= candidates

    if all_quotas_filled:
        ending = COMPLETE
    elif every_candidate_considered:
        ending = EXHAUSTED
    else:
        ending = NEITHER

    #: The reconciliation that catches a lost result. Every considered lineage
    #: is either admitted or rejected with a code; a considered count larger
    #: than the two together means a result went missing between the pool and
    #: the reduction, which is exactly the kind of loss that leaves a smaller
    #: cohort looking like a complete one.
    rejected = acquired.get("rejected", [])
    accounted = len(admitted) + len(rejected)

    return {
        "ending": ending,
        "candidates_in_frame": candidates,
        "lineages_considered": considered,
        "candidates_never_considered": max(candidates - considered, 0),
        "admitted": len(admitted),
        "rejected": len(rejected),
        "accounted_for": accounted,
        "unaccounted": considered - accounted,
        "reconciles": considered == accounted,
        "by_family": by_family,
        "family_quota": dict(quotas),
        "quotas_filled": quotas_filled,
        "all_quotas_filled": all_quotas_filled,
        "every_candidate_considered": every_candidate_considered,
        "rejected_by_code": dict(sorted(acquired.get("rejected_by_code", {}).items())),
    }


def concerns(found: dict[str, Any]) -> list[str]:
    """What a reader must be told before the cohort is scored.

    Returned as findings rather than raised, because none of them make scoring
    impossible — they make it mean something narrower, and the narrowing belongs
    in the record beside the number rather than in an exception nobody sees.
    """
    raised: list[str] = []
    if found["ending"] == NEITHER:
        raised.append(
            f"the run stopped with {found['candidates_never_considered']} candidates "
            "never considered and not every quota filled. It neither exhausted the "
            "frame nor completed it, so the cohort is smaller than the frame allowed "
            "for a reason this artifact does not state"
        )
    if not found["reconciles"]:
        raised.append(
            f"{found['unaccounted']} considered lineages are neither admitted nor "
            "rejected. A result went missing between the pool and the reduction"
        )
    for family, filled in found["quotas_filled"].items():
        if not filled:
            got = found["by_family"].get(family, 0)
            want = found["family_quota"][family]
            raised.append(
                f"family {family} filled {got} of {want}. Reported as a shortfall; "
                "the quota is not lowered and the shortfall is not redistributed"
            )
    return raised


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--acquisition", default=str(ACQUISITION))
    parser.add_argument(
        "--write-receipt",
        action="store_true",
        help="record the assessment as an immutable receipt",
    )
    arguments = parser.parse_args(argv)

    path = Path(arguments.acquisition)
    if not path.exists():
        print(f"no acquisition artifact at {rel(path)}", file=sys.stderr)
        return 3

    import sources_sfi2 as frame_module

    acquired = json.loads(path.read_text(encoding="utf-8"))
    found = assess(acquired, dict(frame_module.FAMILY_QUOTA))
    raised = concerns(found)

    body = {
        "schema": "tavonel.v2.sfi2_frame_verification.v1",
        "acquisition": rel(path),
        "acquisition_sha256": sha_file(path),
        "reduction_digest": acquired.get("reduction_digest"),
        "frame_digest": acquired.get("frame", {}).get("digest"),
        "generated_at": now(),
        "assessment": found,
        "concerns": raised,
        "scorable": found["ending"] != NEITHER and found["reconciles"],
        "note": (
            "frame composition only. This tool does not score, does not re-admit and does not fetch"
        ),
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }

    if arguments.write_receipt:
        written = write_immutable("sfi2-frame-verification", body, tool=Path(__file__).resolve())
        body["receipt"] = written.get("receipt")

    print(json.dumps(body, indent=2, ensure_ascii=False))
    return 0 if body["scorable"] else 4


if __name__ == "__main__":
    raise SystemExit(main())
