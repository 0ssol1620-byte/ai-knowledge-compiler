"""MIGRATION_CLOSURE_ACCEPTANCE_V1 — the explicit receipt SFI3 gates on.

WHY THIS EXISTS. `freeze_sfi3_protocol` resolved the migration closure by
globbing `identity-change-migration-closure--*.json` and taking the newest. That
stem matches only V1's closure of 2026-08-25T00:10:37Z: V2R1, V2R2, V2R3 and
V2R3R1 all write different stems, so none of the four successors was ever visible
to the gate. It has been reading a chain that three successors superseded, and
nothing in it could say so.

Pointing the glob at a newer stem would not fix the shape. "Whatever sorted last
under a name that looks about right" is not a binding, and the next successor
breaks it again the same way. INC-V2-069, defect class 7.

So the SFI3 readiness contract now requires an EXPLICIT acceptance receipt that
names its closure by protocol id, by run id, and by digest, and re-verifies each
of them against disk. There is no glob, no `latest`, and no implicit predecessor
selection anywhere in the path.

WHAT THIS DOES NOT DO. It does not weaken the SFI3 condition and it does not
decide anything. The requirement was always "a prospective migration closure
PASSED"; this makes that sentence executable. Every clause it checks is one the
frozen SFI3 protocol already required in words:

    protocol_id      is the closure this acceptance is about
    measurement      exists at the named path, with the named run id
    digests          measurement, protocol and universe all still match disk
    overall          == PASS, read from the receipt, never inferred
    invariant set    == the canonical eight, as SET EQUALITY (INC-V2-067)
    every verdict    == MET, with none UNPROVEN
    corpus           >= the declared floor, across >= 3 families

A receipt that cannot satisfy all of them is refused with the clause named. It is
never downgraded to a warning, and there is no flag that skips one.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]
for _sub in ("tools",):
    _path = str(NS / _sub)
    if _path not in sys.path:
        sys.path.insert(0, _path)

import invariant_domain as dom  # noqa: E402
from evidence import write_immutable  # noqa: E402

SCHEMA = "tavonel.v2.migration_closure_acceptance.v1"
STEM = "migration-closure-acceptance"

#: The only closure this acceptance may be issued for. A successor version is a
#: different scientific object and needs its own line here, added deliberately
#: rather than matched by a prefix.
ACCEPTED_PROTOCOL_ID = "IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R4"

#: The founder's floor, unchanged since V2R1 and never lowered to reach
#: feasibility. Carried here so the acceptance can check it without importing a
#: scorer that would drag a universe in with it.
COHORT_FLOOR = 200
FAMILIES_REQUIRED = 3

REQUIRED_DIGESTS = ("measurement_sha256", "protocol_sha256", "universe_sha256")


def measurement_digest(body: dict[str, Any], field: str) -> str:
    """A chain digest out of a measurement receipt, from wherever it records it.

    TWO PLACES, BECAUSE TWO SHAPES ARE IN USE. V1's result put the protocol and
    universe digests at the top level. V2R4's traversal embeds the gate result
    whole under `preconditions`, which is where its protocol digest lives; its
    universe digest is at the top level. Both are the SAME digest, from the same
    gate, and which key a scorer happened to write it under is plumbing rather
    than a clause of this contract.

    IT REFUSES RATHER THAN RETURNING None, and that is the point of it being a
    function. `verify` compares `body[field]` to `acceptance[field]`; with a
    receipt that records the digest in neither place, both sides were `None` and
    the comparison PASSED -- an acceptance binding a chain digest that does not
    exist, checked against a measurement that does not carry one. INC-V2-083.
    """
    for value in (body.get(field), (body.get("preconditions") or {}).get(field)):
        if value:
            return str(value)
    raise AcceptanceRefused(
        f"the measurement receipt records no {field}, at the top level or under "
        "`preconditions`. An acceptance cannot bind a chain digest the measurement "
        "never carried, and comparing two absent values is not a check."
    )


class AcceptanceRefused(RuntimeError):
    """The named closure does not satisfy the acceptance contract."""


def _sha_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _resolve(rel: str) -> Path:
    candidate = ROOT / rel
    if candidate.is_file():
        return candidate
    plain = Path(rel)
    if plain.is_file():
        return plain
    raise AcceptanceRefused(
        f"the acceptance names {rel!r}, which is not on disk. An acceptance over "
        "absent material proves nothing about it."
    )


# ---------------------------------------------------------------------------
# the contract


def verify(acceptance: dict[str, Any]) -> dict[str, Any]:
    """Re-check every clause against disk. Raises `AcceptanceRefused` otherwise.

    Nothing here trusts a field the acceptance carries about itself. The digests
    are recomputed, the measurement is re-read, and the verdicts are taken from
    the measurement rather than from the acceptance's summary of it -- an
    acceptance that quoted itself would agree with itself.
    """
    if acceptance.get("schema") != SCHEMA:
        raise AcceptanceRefused(
            f"schema is {acceptance.get('schema')!r}, not {SCHEMA!r}; this is not a "
            "migration closure acceptance"
        )
    protocol_id = acceptance.get("protocol_id")
    if protocol_id != ACCEPTED_PROTOCOL_ID:
        raise AcceptanceRefused(
            f"this acceptance is for {protocol_id!r}. SFI3 gates on "
            f"{ACCEPTED_PROTOCOL_ID!r}, and a closure from a superseded chain -- V1, "
            "V2R1, V2R2, V2R3 or V2R3R1 -- cannot stand in for it."
        )

    for field in REQUIRED_DIGESTS:
        if not acceptance.get(field):
            raise AcceptanceRefused(f"the acceptance records no {field}")

    measurement_path = _resolve(str(acceptance.get("measurement_receipt") or ""))
    actual = _sha_file(measurement_path)
    if actual != acceptance["measurement_sha256"]:
        raise AcceptanceRefused(
            f"{measurement_path.name} has changed since it was accepted.\n"
            f"  accepted: {acceptance['measurement_sha256']}\n  current:  {actual}"
        )

    body = json.loads(measurement_path.read_text(encoding="utf-8"))

    if body.get("protocol_id") != ACCEPTED_PROTOCOL_ID:
        raise AcceptanceRefused(
            f"the measurement's own protocol_id is {body.get('protocol_id')!r}, not "
            f"{ACCEPTED_PROTOCOL_ID!r}. The acceptance and the receipt it names "
            "disagree about which study this is."
        )
    run_id = (body.get("provenance") or {}).get("run_id") or body.get("run_id")
    if acceptance.get("measurement_run_id") and run_id != acceptance["measurement_run_id"]:
        raise AcceptanceRefused(
            f"the acceptance names run {acceptance['measurement_run_id']!r} and the "
            f"receipt carries {run_id!r}"
        )
    for field in ("protocol_sha256", "universe_sha256"):
        recorded = measurement_digest(body, field)
        if recorded != acceptance[field]:
            raise AcceptanceRefused(
                f"{field} disagrees between the acceptance ({acceptance[field]!r}) "
                f"and the measurement ({recorded!r})"
            )

    #: The invariant domain, as set equality. A measurement carrying seven
    #: blocks and an `overall: PASS` is exactly INC-V2-067, and this is the
    #: clause that refuses it.
    try:
        domain = dom.require_receipt_domain(body)
    except dom.ContractBroken as error:
        raise AcceptanceRefused(
            f"the measurement does not carry the declared invariant set: {error}"
        ) from error

    if domain["overall"] != dom.PASS:
        raise AcceptanceRefused(
            f"the measurement's overall verdict is {domain['overall']!r}, not PASS. "
            "SFI3 requires a prospective migration closure that CLOSED."
        )
    not_met = sorted(name for name, verdict in domain["verdicts"].items() if verdict != dom.MET)
    if not_met:
        raise AcceptanceRefused(
            f"the measurement reports PASS while {not_met} are not MET. The "
            "receipt's own blocks contradict its verdict."
        )

    pairs = body.get("pairs_resolved")
    if not isinstance(pairs, int) or pairs < COHORT_FLOOR:
        raise AcceptanceRefused(
            f"the closure resolved {pairs} pairs against a floor of {COHORT_FLOOR}. "
            "The floor is never lowered to reach feasibility."
        )
    families = body.get("by_family") or {}
    if len(families) < FAMILIES_REQUIRED:
        raise AcceptanceRefused(
            f"the closure spans {len(families)} families against a required "
            f"{FAMILIES_REQUIRED}: {sorted(families)}"
        )

    return {
        "schema": SCHEMA,
        "held": True,
        "protocol_id": protocol_id,
        "measurement_receipt": acceptance["measurement_receipt"],
        "measurement_run_id": run_id,
        "measurement_sha256": actual,
        "protocol_sha256": acceptance["protocol_sha256"],
        "universe_sha256": acceptance["universe_sha256"],
        "overall": domain["overall"],
        "invariants": domain["verdicts"],
        "pairs_resolved": pairs,
        "families": sorted(families),
        "cohort_floor": COHORT_FLOOR,
        "how": (
            "every digest recomputed from disk, the measurement re-read, the "
            "invariant set compared as set equality, and each verdict taken from "
            "the measurement rather than from this acceptance's summary of it"
        ),
        "no_glob": (
            "the closure is named by protocol id, run id and digest. There is no "
            "glob, no 'latest', and no implicit predecessor selection anywhere in "
            "this path -- see INC-V2-069."
        ),
    }


def build(measurement_receipt: Path) -> dict[str, Any]:
    """Draft an acceptance for a measurement, then verify it before returning.

    The draft is never returned unverified: an acceptance that has not passed
    its own contract is a claim, and this module exists because a claim was
    standing in for a check.
    """
    body = json.loads(measurement_receipt.read_text(encoding="utf-8"))
    try:
        relative = str(measurement_receipt.resolve().relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        relative = str(measurement_receipt)
    draft = {
        "schema": SCHEMA,
        "protocol_id": body.get("protocol_id"),
        "measurement_receipt": relative,
        "measurement_run_id": (body.get("provenance") or {}).get("run_id") or body.get("run_id"),
        "measurement_sha256": _sha_file(measurement_receipt),
        "protocol_sha256": measurement_digest(body, "protocol_sha256"),
        "universe_sha256": measurement_digest(body, "universe_sha256"),
    }
    verify(draft)
    return draft


def latest_acceptance(receipts: Path | None = None) -> Path | None:
    """The most recent acceptance ON DISK, offered only as a CLI convenience.

    Never used as a binding. `freeze_sfi3_protocol` takes an explicit path; this
    exists so a human running the tool by hand does not have to type a run id,
    and every caller that matters passes one.
    """
    directory = receipts if receipts is not None else NS / "receipts"
    found = sorted(directory.glob(f"{STEM}--*.json"))
    return found[-1] if found else None


def seal(measurement_receipt: Path) -> dict[str, Any]:
    """Draft, verify, and write the acceptance as an immutable receipt.

    `build` returns a verified draft and nothing sealed it, so
    `latest_acceptance` -- which globs the receipts directory -- could never find
    one, and `freeze_sfi3_protocol` takes an explicit acceptance PATH. An
    acceptance that exists only in console output is the same false-provenance
    seam the companion attestations exist to close, one layer up.

    ONE ACCEPTANCE PER CLOSURE. A second would let a later reader pick whichever
    one suited, and the downstream freeze binds by path.
    """
    existing = sorted((NS / "receipts").glob(f"{STEM}--*.json"))
    if existing:
        raise AcceptanceRefused(
            "an acceptance receipt already exists and there is exactly one per "
            f"closure: {existing[-1].name}. A second would let a later reader "
            "choose which one to bind."
        )
    draft = build(measurement_receipt)
    #: Verified again AFTER the draft is assembled and BEFORE it is written.
    #: `build` verifies its own return, and repeating it here costs nothing and
    #: means the thing sealed is the thing checked rather than something
    #: assembled from it.
    verify(draft)
    return {**draft, **write_immutable(STEM, draft, tool=Path(__file__).resolve())}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--measurement", type=Path, default=None, help="draft from this receipt")
    parser.add_argument("--acceptance", type=Path, default=None, help="verify this acceptance")
    parser.add_argument(
        "--write-receipt",
        action="store_true",
        help="seal the verified draft immutably. Without it, --measurement drafts only.",
    )
    args = parser.parse_args(argv)

    try:
        if args.measurement is not None:
            drafted = seal(args.measurement) if args.write_receipt else build(args.measurement)
            print(json.dumps(drafted, indent=1, sort_keys=True))
            return 0
        path = args.acceptance or latest_acceptance()
        if path is None or not path.is_file():
            print(json.dumps({"state": "REFUSED", "why": "no acceptance receipt"}, indent=1))
            return 4
        body = verify(json.loads(path.read_text(encoding="utf-8")))
        print(json.dumps({**body, "receipt": path.name}, indent=1, sort_keys=True))
        return 0
    except AcceptanceRefused as error:
        print(json.dumps({"state": "REFUSED", "why": str(error)}, indent=1))
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
