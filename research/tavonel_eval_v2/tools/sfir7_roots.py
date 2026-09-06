#!/usr/bin/env python3
"""SFIR7's Git roots, read from the frozen roster rather than typed out.

SFIR4 declared its twenty repositories as a literal in `sources_sfir4`. SFIR7
cannot, and must not: its roots are whatever an external catalogue's published
ordinal selected, and writing them into a source file by hand would put a
transcription between the frame rule and the census. So this module reads
`receipts/sfir7-roster-freeze.json` and refuses if it is not the roster whose
fingerprint the freeze sealed.

**The pool's shape is inherited; only its members are new.** Extensions, the
per-root candidate cap and every request bound come from `sources_sfir4`, read
live. Nothing here restates a number that module owns, so a bound that moves
there moves here, and a bound that moves here alone cannot.

**The one derived figure is the total candidate cap**, and it is derived the way
SFIR4 derived its own: roots multiplied by the per-root cap. SFIR4's 1,600 is
20 x 80. SFIR7's is 50 x 80. That inherits the *rule* rather than the *number* --
carrying 1,600 across to a frame two and a half times larger would be a cap set
by a coincidence of history, and raising it after seeing a census would be the
forbidden act. It is fixed here, before any SFIR7 candidate exists.

**Identity is the catalogue's numeric id, not the address.** `expected_uuid`
returns the host repository id Libraries.io recorded in 2020, which is what the
census attests the live response against. `owner/repo` is only where it asks.
"""

from __future__ import annotations

import json
import sys
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Any

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

from acquisition import sources_sfir4 as sources  # noqa: E402

PROTOCOL_ID = "SOURCE_FACT_IR_INDEPENDENT_REPLICATION_V7"
FREEZE_PATH = NS / "receipts/sfir7-roster-freeze.json"
FAMILY = "git_docs"

#: SFIR7 measures one family. Not because the other two are uninteresting, but
#: because the frame question is about Git roots and re-measuring eCFR or
#: Wikipedia under a new frame would answer a question nobody asked.
FAMILIES = (FAMILY,)


class SFIR7RootsRefused(RuntimeError):
    """The roster on disk is not the roster the freeze sealed."""


@lru_cache(maxsize=1)
def frozen_roster() -> tuple[dict[str, Any], ...]:
    if not FREEZE_PATH.exists():
        raise SFIR7RootsRefused(
            f"{FREEZE_PATH.name} is absent. SFIR7 has no roots until its roster is frozen."
        )
    body = json.loads(FREEZE_PATH.read_text(encoding="utf-8"))
    if body.get("state") != "ROSTER_FROZEN":
        raise SFIR7RootsRefused(
            f"the roster receipt is in state {body.get('state')!r}, not ROSTER_FROZEN"
        )
    roster = body["roster"]
    _require_fingerprint(body, roster)
    seen_addresses: set[str] = set()
    seen_uuids: set[str] = set()
    for entry in roster:
        address = entry["name_with_owner"]
        if address.count("/") != 1:
            raise SFIR7RootsRefused(f"frozen address {address!r} is not owner/repo")
        if address in seen_addresses:
            raise SFIR7RootsRefused(f"frozen roster repeats the address {address!r}")
        if not entry["host_uuid"]:
            raise SFIR7RootsRefused(f"{address} was frozen without a host repository id")
        if entry["host_uuid"] in seen_uuids:
            raise SFIR7RootsRefused(
                f"frozen roster repeats host id {entry['host_uuid']!r}; two addresses for "
                "one repository would census the same tree twice"
            )
        seen_addresses.add(address)
        seen_uuids.add(entry["host_uuid"])
    return tuple(dict(entry) for entry in roster)


def _require_fingerprint(body: dict[str, Any], roster: list[dict[str, Any]]) -> None:
    """Recompute the fingerprint rather than trust the field beside it.

    A receipt that carries both a roster and a digest of that roster proves
    nothing if nobody recomputes the digest: the two are written by the same
    process at the same moment and agree by construction. This is the check that
    can actually fail -- an edited roster leaves the sealed digest behind.
    """
    import hashlib

    payload = json.dumps(roster, sort_keys=True, separators=(",", ":")).encode()
    recomputed = "sha256:" + hashlib.sha256(payload).hexdigest()
    if recomputed != body["roster_fingerprint"]:
        raise SFIR7RootsRefused(
            f"the roster on disk digests to {recomputed} but the freeze sealed "
            f"{body['roster_fingerprint']}. The roster has been edited since it was frozen."
        )


def declared_roots() -> tuple[str, ...]:
    """The addresses, in frozen rank order. Order is part of the freeze."""
    return tuple(entry["name_with_owner"] for entry in frozen_roster())


def expected_uuid(repository: str) -> str:
    for entry in frozen_roster():
        if entry["name_with_owner"] == repository:
            return str(entry["host_uuid"])
    raise SFIR7RootsRefused(f"{repository!r} is not a frozen SFIR7 root")


def max_total_candidates() -> int:
    """Roots x the inherited per-root cap, the way SFIR4 derived its own."""
    return len(declared_roots()) * int(
        sources.SOURCE_POOLS[FAMILY]["max_candidates_per_repository"]
    )


def git_pool() -> Any:
    """SFIR4's pool shape with SFIR7's members. Every bound read live."""
    inherited = sources.SOURCE_POOLS[FAMILY]
    return MappingProxyType(
        {
            "repositories": declared_roots(),
            "extensions": tuple(inherited["extensions"]),
            "max_candidates_per_repository": int(inherited["max_candidates_per_repository"]),
            "max_total_candidates": max_total_candidates(),
        }
    )


def inherited_bounds() -> dict[str, int]:
    """Every inherited constant that can stop or cut SFIR7's census.

    Reported into the census receipt so that a run cut short by a bound says
    which bound, with the value it had at the time. INC-V2-115 exists because a
    cap that binds the census was never written down anywhere a reader would
    look.
    """
    return {
        "max_git_api_requests_per_root": int(sources.MAX_GIT_API_REQUESTS_PER_ROOT),
        "max_git_api_requests_global": int(sources.MAX_GIT_API_REQUESTS_GLOBAL),
        "max_git_tree_objects_per_root": int(sources.MAX_GIT_TREE_OBJECTS_PER_ROOT),
        "max_git_tree_queue_entries": int(sources.MAX_GIT_TREE_QUEUE_ENTRIES),
        "max_candidates_per_repository": int(
            sources.SOURCE_POOLS[FAMILY]["max_candidates_per_repository"]
        ),
        "max_total_candidates_derived": max_total_candidates(),
        "max_total_candidates_inherited_literal": int(
            sources.SOURCE_POOLS[FAMILY]["max_total_candidates"]
        ),
    }
