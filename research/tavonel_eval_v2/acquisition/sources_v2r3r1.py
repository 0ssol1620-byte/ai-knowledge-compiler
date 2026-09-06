"""The V2R3R1 acquisition frame: a prohibition, not a traversal.

WHY A FRAME AT ALL WHEN NOTHING IS ACQUIRED. Rung 0 exists so that the rules
deciding WHAT enters the study are sealed before any content can influence them.
The parent already discharged that obligation for this material: it declared 40
git roots, 44 eCFR roots and an issuer rule, froze them, and only then fetched.
Those declarations are not re-made here and this file contains no root list, no
quota, no container cap and no stopping rule -- restating them would create a
second declaration of a frozen thing, which is the defect that produced the
parent's own hand-maintained quota/share divergence.

WHAT THIS FRAME SEALS INSTEAD is the one decision the successor actually makes:
that its only legal candidate set is exactly the parent's frozen 300 rows. The
selection freedom rung 0 exists to remove is here removed to zero by
construction. What remains to be sealed is that nobody widened it, narrowed it
or reordered it -- and that is what the exact-set attestation proves.

`FLOOR` and `FAMILIES_REQUIRED` are carried forward at the parent's values and
are NOT re-derived. They are the cohort sufficiency rule, they were declared
before any material existed, and the ruling forbids lowering them. They appear
here so the successor's frame can be read on its own without inferring the
sufficiency rule from a file it does not name.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

PROTOCOL_ID = "IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R3R1"
PARENT_PROTOCOL_ID = "IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R3"

MODE = "EXACT_CARRY_FORWARD"

#: The parent's frozen universe is the complete candidate universe. Named by
#: receipt stem rather than by path, because the receipt that matters is
#: whichever one is in force, and a pinned path could silently point at a
#: superseded file.
CANDIDATE_SOURCE_RECEIPT_STEM = "identity-change-migration-closure-v2r3-universe"

#: Carried forward at the parent's values. Not re-derived and never lowered.
FLOOR = 200
FAMILIES_REQUIRED = 3

#: The parent's realised composition. Declared so that a change is a refusal
#: rather than a recomputation that agrees with whatever it happened to read.
PAIR_COUNT = 300
BY_FAMILY: Mapping[str, int] = MappingProxyType(
    {"git_docs": 133, "regulation_ecfr": 104, "sec_edgar": 63}
)

NETWORK = "FORBIDDEN"
REACQUISITION = "FORBIDDEN"

#: Everything this frame refuses to contain. Written as a declaration rather
#: than left as an absence, because "there is no traversal here" is a claim a
#: reader should be able to check against something.
NO_SELECTION_SURFACE: Mapping[str, str] = MappingProxyType(
    {
        "roots": "none. The parent declared and froze them before fetching.",
        "quotas": "none. 300 in, 300 out.",
        "container_caps": "none. Nothing is traversed.",
        "stopping_rule": "none. There is no acquisition to stop.",
        "ordering_salt": "none. The parent's order is inherited verbatim.",
        "filter": (
            "none, not even a trivially-true one. A no-op filter is one edit from "
            "being a selection function and nothing downstream could tell."
        ),
        "subset_choice": "none. Any subset of 300 is a chosen subset.",
        "oversampling": "none. There is nothing to sample from.",
    }
)

ALL_OR_NOTHING = (
    "the 300 pairs are eligible only because no outcome was observed and there is "
    "zero selection freedom. Removing a troublesome pair, replacing an unreadable "
    "row, rebalancing families, adding a pair, changing traversal or changing "
    "exclusions each destroys that basis. There is no partial salvage: abandon "
    "carry-forward and acquire a fresh cohort."
)

WHY_NO_REFETCH = (
    "re-fetching could return changed source bytes, which would no longer be exact "
    "carry-forward. The already-frozen raw and canonical bytes on disk are the "
    "material; their digests are recomputed locally and must match."
)


def frame_declaration() -> dict[str, object]:
    """What rung 0 of this chain seals, as a plain value.

    Returned rather than assembled at freeze time so that the freezer pins a
    declaration this module owns, instead of pinning whatever the freezer chose
    to gather.
    """
    return {
        "protocol_id": PROTOCOL_ID,
        "parent_protocol_id": PARENT_PROTOCOL_ID,
        "mode": MODE,
        "candidate_source_receipt_stem": CANDIDATE_SOURCE_RECEIPT_STEM,
        "pair_count": PAIR_COUNT,
        "by_family": dict(BY_FAMILY),
        "floor": FLOOR,
        "families_required": FAMILIES_REQUIRED,
        "network": NETWORK,
        "reacquisition": REACQUISITION,
        "no_selection_surface": dict(NO_SELECTION_SURFACE),
        "all_or_nothing": ALL_OR_NOTHING,
        "why_no_refetch": WHY_NO_REFETCH,
        "what_this_frame_does_not_restate": (
            "the parent's roots, quotas, caps, order salt and stopping rule. They "
            "were declared and frozen before any material existed and are not "
            "re-made here; a second declaration of a frozen thing is free to drift "
            "from the first."
        ),
    }
