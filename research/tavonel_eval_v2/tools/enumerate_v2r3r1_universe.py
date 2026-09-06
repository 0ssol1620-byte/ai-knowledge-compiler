"""Write the V2R3R1 candidate universe: the parent's 300 rows, unchanged.

NOT AN ADAPTER, deliberately. The V2R2/V2R3 enumerators traverse a fresh
acquisition manifest, detect cache-key collisions, apply an exclusion policy and
subtract spent sets in two passes. Every one of those is a decision about which
rows survive, and this chain is forbidden to make any such decision: the founder
ruling of 2026-08-26 permits exact carry-forward precisely because there is no
selection freedom left. Wrapping an enumerator and then disabling its judgement
would leave the judgement one edit away from re-enabling, and a reader could not
tell from the wrapper which of its behaviours were still live.

So this file copies. It reads the parent's frozen universe receipt, re-proves
every payload digest against disk, proves the row list is exactly the parent's,
and writes the result. The exclusion decisions are INHERITED as facts, not
re-decided: the parent's realised exclusion set was empty, and re-running an
exclusion policy here could produce a different empty set for a different
reason.

NO NETWORK. Nothing is fetched, nothing is re-canonicalised, and no file under
the parent's corpus directory is opened for writing.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import sources_v2r3r1 as frame  # noqa: E402
import v2r3r1_carry_forward as cf  # noqa: E402

OUT_DIR = NS / "artifacts" / "development" / "v2r3r1_universe"
OUT = OUT_DIR / "v2r3r1_universe_candidates.json"
SCHEMA = "tavonel.v2.identity_change_migration_closure.v2r3r1_universe_enumeration.v1"

CarryForwardRefused = cf.CarryForwardRefused

#: Upstream fields the downstream freezer reads off a candidate manifest. Carried
#: from the parent's manifest verbatim, because they record what the PARENT's
#: enumerator decided and this chain is not permitted to decide it again.
INHERITED_UPSTREAM = (
    "excluded",
    "exclusion_categories",
    "disjointness",
    "disjointness_subtraction",
)


def enumerate_universe() -> dict[str, Any]:
    """The parent's candidate manifest, carried forward with its rows untouched.

    THE INPUT IS THE PARENT'S MANIFEST, NOT ITS FROZEN UNIVERSE, and the
    distinction matters. The frozen universe is rung 3's OUTPUT: rung 3 consumed
    `raw_sha256_recorded`, re-hashed the file and emitted `raw_sha256` beside a
    verification flag. Feeding that output back in as input would not be a
    carry-forward -- it would be asking rung 3 to verify recomputed digests
    against themselves, which reports every side verified and proves nothing.

    So the parent's INPUT is carried forward, pinned by the digest the parent's
    frozen receipt recorded for it, and rung 3 re-runs its whole verification
    path over it: re-hashing all 1,200 payloads, re-detecting collisions,
    re-applying the exclusion policy. The 3a attestation then requires the OUTPUT
    to equal the parent's frozen universe row for row. That is strictly stronger
    than copying the output would have been -- a filter that is switched off
    proves nothing about its decisions, and one that runs and lands in the same
    place proves they are unchanged.
    """
    parent = cf.load_parent()
    frozen_rows = cf.carry_rows(parent)
    payloads = cf.verify_payload_digests(frozen_rows)
    equality = cf.compare(parent["pairs"], frozen_rows)
    manifest = cf.load_parent_manifest(parent)
    correspondence = cf.compare_candidates_to_frozen(manifest["pairs"], parent["pairs"])

    missing = [name for name in INHERITED_UPSTREAM if name not in manifest]
    if missing:
        raise CarryForwardRefused(
            f"the parent's candidate manifest does not carry {missing}. These record "
            "what the parent's enumerator decided; an absent one cannot be replaced "
            "by recomputing it here, because that would be this chain deciding which "
            "rows survive."
        )

    #: VERBATIM. Not rebuilt, not re-ordered, not filtered.
    rows = json.loads(json.dumps(manifest["pairs"]))

    families: dict[str, int] = {}
    for row in rows:
        families[row["family"]] = families.get(row["family"], 0) + 1

    return {
        "schema": SCHEMA,
        "protocol_id": frame.PROTOCOL_ID,
        "parent_protocol_id": frame.PARENT_PROTOCOL_ID,
        "path_taken": "EXACT_CARRY_FORWARD_OF_AN_UNSCORED_FROZEN_UNIVERSE",
        "network": "none",
        "reacquisition": "none",
        "pairs": rows,
        "pair_count": len(rows),
        "by_family": dict(sorted(families.items())),
        **{name: manifest[name] for name in INHERITED_UPSTREAM},
        "sufficiency": {
            "state": "SUFFICIENT"
            if len(rows) >= frame.FLOOR and len(families) >= frame.FAMILIES_REQUIRED
            else "INSUFFICIENT",
            "floor": frame.FLOOR,
            "families_required": frame.FAMILIES_REQUIRED,
            "inherited_not_re_derived": (
                "the floor and the family rule are the parent's, declared before any "
                "material existed and never lowered."
            ),
        },
        "disjointness_holds": True,
        "carry_forward": {
            "mode": "EXACT_SET",
            "parent_universe_receipt": cf.parent_universe_receipt().name,
            "parent_universe_sha256": parent.get("universe_sha256"),
            "parent_universe_run_id": (parent.get("provenance") or {}).get("run_id"),
            "parent_manifest": str(cf.PARENT_MANIFEST.relative_to(NS)),
            "parent_manifest_sha256": (parent.get("manifest") or {}).get("sha256"),
            "rows_taken": "verbatim from the parent's candidate manifest",
            "equality": equality,
            "candidate_correspondence": correspondence,
            "payload_verification": payloads,
        },
        "upstream_decisions_are_not_re_decided": (
            "collisions, exclusions and disjointness subtraction were decided once, "
            "by the parent's enumerator, over material that has not changed. They are "
            "carried as facts. Rung 3's OWN verification -- re-hashing every payload, "
            "re-detecting collisions, re-applying the exclusion policy -- still runs "
            "in full, and rung 3a requires its output to equal the parent's frozen "
            "universe exactly."
        ),
        "no_selection_function": dict(frame.NO_SELECTION_SURFACE),
        "frame": "research/tavonel_eval_v2/acquisition/sources_v2r3r1.py",
    }


def main() -> int:
    try:
        body = enumerate_universe()
    except CarryForwardRefused as error:
        print(json.dumps({"state": "REFUSED", "why": str(error)}, indent=1))
        return 4
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(body, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"[carry-forward] pairs {body['pair_count']} {body['by_family']}")
    print(f"[carry-forward] sufficiency {body['sufficiency']['state']}")
    print(
        "[carry-forward] payloads rehashed "
        f"{body['carry_forward']['payload_verification']['payloads_rehashed']}, "
        "every declared delta 0"
    )
    print(f"[carry-forward] -> {OUT.relative_to(NS)}")
    return 0 if body["pair_count"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
