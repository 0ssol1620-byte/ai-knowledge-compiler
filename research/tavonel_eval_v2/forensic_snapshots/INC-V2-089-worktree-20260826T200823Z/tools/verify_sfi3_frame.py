#!/usr/bin/env python3
"""Was the SFI3 frame exhausted, or did the run simply stop?

Step one of the completion order, before scoring and separate from it. Three
endings look identical inside an acquisition artifact:

    the run considered every candidate it had     -> exhausted
    the run met its quotas and stopped early      -> complete
    the run stopped for some other reason         -> NEITHER

The third is the one worth catching. A crashed pool, a truncated frame or a
silent break leaves a cohort smaller than it should be, and every downstream
number is then computed over it without complaint. The scorer would report
honest counts of a dishonest cohort, and nothing in the scored receipt would look
wrong, because nothing in it describes what was never attempted.

`assess` and `concerns` are IMPORTED from the V2 verifier rather than restated.
The V2 tool answered exactly this question and its arithmetic is unchanged; a
re-implementation that drifted by a line would make two studies incomparable
while looking like a repeat. This module owns only what genuinely differs: which
frame and which artifact.

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

#: One implementation of the three-way ending, shared with V2. See the module
#: docstring: importing is the point, not an economy.
from verify_sfi2_frame import (  # noqa: E402
    COMPLETE,
    EXHAUSTED,
    NEITHER,
    assess,
    concerns,
)

#: Re-exported deliberately. A caller importing the ending vocabulary from the V3
#: module must get the SAME three strings V2 used, or the two studies' endings
#: could diverge in name while claiming to be the same question.
__all__ = ["COMPLETE", "EXHAUSTED", "NEITHER", "assess", "concerns", "main", "quotas"]

ACQUISITION = NS / "artifacts" / "development" / "sfi3" / "sfi3_acquisition.json"
STEM = "sfi3-frame-verification"


def quotas() -> dict[str, int]:
    """The frozen family quotas, read from the frame module rather than restated.

    A quota restated in a verifier is a quota that can disagree with the one the
    acquisition actually used, and the verifier would then certify a cohort
    against numbers no run ever applied.
    """
    import sources_sfi3

    return dict(sources_sfi3.FAMILY_QUOTA)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--acquisition", default=str(ACQUISITION))
    parser.add_argument("--write-receipt", action="store_true")
    arguments = parser.parse_args(argv)

    path = Path(arguments.acquisition)
    if not path.exists():
        print(f"no acquisition artifact at {rel(path)}; nothing to verify", file=sys.stderr)
        return 3

    acquired = json.loads(path.read_text(encoding="utf-8"))
    found = assess(acquired, quotas())
    raised = concerns(found)

    body: dict[str, Any] = {
        "schema": "tavonel.v2.sfi3_frame_verification.v1",
        "study": "SOURCE_FACT_IR_HELDOUT_V3",
        "acquisition": rel(path),
        "acquisition_sha256": sha_file(path),
        "generated_at": now(),
        **found,
        "concerns": raised,
        #: Scoring a cohort whose ending is NEITHER would compute honest numbers
        #: over an unknown denominator. The scorer is not blocked by this tool —
        #: it is a separate step — so the judgement is stated plainly here instead.
        "scorable": found["ending"] in (EXHAUSTED, COMPLETE) and not raised,
        "reading": (
            "EXHAUSTED means every candidate the frame held was considered. "
            "COMPLETE means the quotas filled and the run stopped early, which is "
            "correct and leaves candidates unexamined. NEITHER means the run "
            "stopped for a reason this tool cannot name, and the cohort's size is "
            "not evidence of anything"
        ),
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }

    if arguments.write_receipt:
        body.update(write_immutable(STEM, body, tool=Path(__file__).resolve()))

    print(
        json.dumps(
            {
                "ending": body["ending"],
                "considered": body.get("considered"),
                "candidates": body.get("candidates"),
                "admitted": body.get("admitted"),
                "unaccounted": body.get("unaccounted"),
                "concerns": raised,
                "scorable": body["scorable"],
                "receipt": body.get("receipt"),
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0 if body["scorable"] else 4


if __name__ == "__main__":
    raise SystemExit(main())
