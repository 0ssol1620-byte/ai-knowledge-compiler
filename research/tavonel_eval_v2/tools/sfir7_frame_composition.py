#!/usr/bin/env python3
"""Describe what the frozen roster is made of, before any census measures it.

The roster is frozen and its fingerprint is sealed, so this changes nothing about
what SFIR7 will visit. It exists because a limitation registered *after* a result
is an excuse, and a limitation registered before it is evidence.

What it reports is composition only -- languages, licences, rank range, overlap
with the roots earlier studies used. It computes no capacity, no yield and no
expectation. Whether 50 externally-selected repositories carry 750 typed facts is
the question the census answers, and nothing here is allowed to anticipate it.

The receipt binds to the roster fingerprint. If the roster ever moves, this
description stops describing it and says so.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

from acquisition import sources_sfir4 as sources  # noqa: E402

SCHEMA = "tavonel.sfir7.frame_composition.v1"
PROTOCOL_ID = "SOURCE_FACT_IR_INDEPENDENT_REPLICATION_V7"


class CompositionRefused(RuntimeError):
    """The description does not describe the roster it claims to."""


def describe(freeze: dict[str, Any], *, declared_licences: tuple[str, ...]) -> dict[str, Any]:
    roster = freeze["roster"]
    if len(roster) != freeze["selection"]["selected_count"]:
        raise CompositionRefused(
            f"freeze reports {freeze['selection']['selected_count']} selected roots but "
            f"carries {len(roster)}. A description of a roster that is not the roster."
        )
    languages = Counter(entry["primary_language"] or "(none declared)" for entry in roster)
    licences = Counter(entry["spdx_license_id_as_published"] for entry in roster)
    prior = {name.casefold() for name in sources.SOURCE_POOLS["git_docs"]["repositories"]}
    selected = {entry["name_with_owner"].casefold() for entry in roster}
    absent = [value for value in declared_licences if value not in licences]

    return {
        "schema": SCHEMA,
        "protocol_id": PROTOCOL_ID,
        "describes_roster_fingerprint": freeze["roster_fingerprint"],
        "roots": len(roster),
        "languages": dict(languages.most_common()),
        "licences_as_published": dict(licences.most_common()),
        "declared_licences_absent_from_the_roster": absent,
        "catalog_rank_value_range": [
            min(entry["catalog_rank_value"] for entry in roster),
            max(entry["catalog_rank_value"] for entry in roster),
        ],
        "overlap_with_earlier_git_roots": {
            "earlier_roots": len(prior),
            "shared": sorted(selected & prior),
            "count": len(selected & prior),
            "note": (
                "SFIR7 deliberately does not exclude the repositories SFIR1-SFIR4 "
                "used. Excluding them would be TAVONEL curating an external "
                "universe again, which is the habit this protocol exists to stop. "
                "Whether the external rule happens to reselect any of them is a "
                "diagnostic and never an input."
            ),
        },
        "registered_limitations": [
            {
                "id": "SFIR7-L1",
                "limitation": (
                    "the roster is dominated by one language ecosystem. "
                    f"{languages.most_common(1)[0][1]} of {len(roster)} roots are "
                    f"{languages.most_common(1)[0][0]}."
                ),
                "why_it_happens": (
                    "Libraries.io's SourceRank is computed over a catalogue whose "
                    "package managers are overwhelmingly npm, so the highest-ranked "
                    "repositories are the ones npm depends on most."
                ),
                "why_it_is_not_repaired": (
                    "balancing by language would be a TAVONEL judgement about which "
                    "repositories deserve to be in the universe, applied on top of an "
                    "external ordinal chosen precisely so that no such judgement is "
                    "made. A stratified rule is a defensible design and it is a "
                    "DIFFERENT design; adopting one now, with the roster in hand and "
                    "the census unrun, would mean choosing a frame while able to guess "
                    "at its yield."
                ),
                "what_it_threatens": (
                    "external validity. A capacity result over this roster speaks to "
                    "repositories like these, not to open-source documentation at "
                    "large. It does not threaten internal validity: the rule is "
                    "declared, deterministic and reproducible from the pinned digest."
                ),
            },
            {
                "id": "SFIR7-L2",
                "limitation": (
                    f"{len(absent)} of the {len(declared_licences)} declared licence "
                    "families do not appear in the roster at all: " + ", ".join(absent)
                    if absent
                    else "every declared licence family appears in the roster"
                ),
                "why_it_happens": (
                    "the allow-list was fixed before the snapshot was read, and rank "
                    "ordering decides which of its members survive into the top N. "
                    "Copyleft-licensed projects are rarer at the top of an "
                    "npm-weighted ordinal."
                ),
                "why_it_is_not_repaired": (
                    "the allow-list is an eligibility predicate, not a quota. Adding "
                    "a per-licence floor would be tuning the frame's composition after "
                    "seeing it."
                ),
            },
        ],
        "computes_no_capacity": True,
        "computes_no_yield": True,
        "census_started": False,
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    args = parser.parse_args()

    import sfir7_frame as frame

    freeze = json.loads(args.freeze.read_text(encoding="utf-8"))
    body = describe(freeze, declared_licences=frame.SPDX_ALLOWLIST)
    body["content_sha256"] = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    args.receipt.write_text(
        json.dumps(body, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps({k: body[k] for k in ("languages", "licences_as_published",
                                           "declared_licences_absent_from_the_roster")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
