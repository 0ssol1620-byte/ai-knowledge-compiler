"""Immutable companion attestations for the V2R3 freeze chain.

WHY THESE EXIST. The shared base freezer writes its immutable receipt INSIDE its
return path:

    body = {...}
    return {**body, **write_receipt(stem, body, ws)}

so a wrapper that computes a V2R3-only proof and then decorates the returned
dictionary produces a proof that exists in memory and in console output and
NOWHERE IN ANY FROZEN BODY. That is a false-provenance seam: the run looks
proved and the receipt records nothing. A console line saying a proof passed is
not a frozen proof.

WHY THE BASE IS NOT EDITED INSTEAD. V2R1's and V2R2's freeze machinery is
SPENT-RUN EVIDENCE. Their tool digests are bound inside receipts the founder
ordered preserved, and adding a hook to the base would change the tooling those
receipts were produced by. So each V2R3 rung writes a SECOND immutable receipt
that BINDS the base receipt it attests -- by path, by run id, and by the digest
of the receipt file as it sits on disk -- and carries the proof in its own body.

WHAT AN ATTESTATION IS NOT. It is not a second opinion about the base rung and
it never re-decides one. It answers exactly one question: at the moment this
base receipt was written, did the V2R3-specific proof hold, and against which
files.

THE GATE MUST CONSUME THEM. `verify_all` re-reads every attestation, re-verifies
it against the base receipt it claims to attest, recomputes every pinned digest,
and RE-RUNS all three proofs from scratch rather than trusting the recorded
finding. An attestation nothing reads is decorative (INC-V2-036), and an
attestation read but not recomputed only proves a file has not changed since it
was written -- which is not the same as the proof still holding.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import freeze_migration_closure_v2r1 as base  # noqa: E402
import root_identity as ri  # noqa: E402
import v2r3_state_table as state_table  # noqa: E402

FreezeRefused = base.FreezeRefused

ATTESTATION_SCHEMA = "tavonel.v2.identity_change_migration_closure.v2r3_attestation.v1"

#: Files each attestation pins, relative to the namespace root. Named here
#: rather than gathered at write time so that "what was attested" is a
#: declaration and not a record of whatever happened to be imported.
FRAME_PINS = (
    "acquisition/sources_v2r3.py",
    "tools/root_identity.py",
)
PROTOCOL_PINS = (
    "protocols/IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R3.yaml",
    "tools/v2r3_state_table.py",
    "tools/v2r3_effective_identity.py",
    "tools/v2r3_quarantine_oracle.py",
    "tests/test_v2r3_contract_consistency.py",
    "docs/COMPAT_IDENTITY_UNCERTAINTY_QUARANTINE.md",
)

CONSISTENCY_TESTS = "tests/test_v2r3_contract_consistency.py"

#: The two spent universes, read for LINEAGE IDS ONLY.
SPENT_UNIVERSE_STEMS = (
    ("v2r1", "identity-change-migration-closure-v2r1-universe", 285),
    ("v2r2", "identity-change-migration-closure-v2r2-universe", 270),
)


# ---------------------------------------------------------------------------
# helpers


def _sha_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _pins(names: tuple[str, ...]) -> dict[str, str]:
    pinned: dict[str, str] = {}
    for name in names:
        path = NS / name
        if not path.is_file():
            raise FreezeRefused(
                f"the attestation pins {name}, which is not on disk. An attestation "
                "over a file that does not exist proves nothing."
            )
        pinned[name] = _sha_file(path)
    return pinned


def _verify_pins(pinned: dict[str, str], where: str) -> None:
    drift = []
    for name, digest in sorted(pinned.items()):
        path = NS / name
        if not path.is_file():
            drift.append(f"{name} is gone")
        elif _sha_file(path) != digest:
            drift.append(f"{name} changed")
    if drift:
        raise FreezeRefused(
            f"{where} attests files that have since changed: {drift}. The proof was "
            "made about a different tree than the one that would run."
        )


def _base_binding(stem: str, ws: Any) -> dict[str, Any]:
    """Identify the base receipt this attestation is about, three ways.

    The path alone is not enough -- a receipt could be replaced -- and the run id
    alone is not enough either, because it lives inside the file it identifies.
    The file digest is what makes the binding checkable from outside.
    """
    runs = base.runs_of(stem, ws.receipts)
    if not runs:
        raise FreezeRefused(
            f"there is no {stem} receipt to attest. The companion attestation is "
            "written after its base rung, never instead of it."
        )
    target = runs[-1]
    body = json.loads(target.read_text(encoding="utf-8"))
    run_id = (body.get("provenance") or {}).get("run_id")
    if not run_id:
        raise FreezeRefused(f"{target.name} carries no provenance run id")
    return {
        "stem": stem,
        "receipt": base._rel(target, ws.root),
        "receipt_file_sha256": _sha_file(target),
        "receipt_body_sha256": body.get("receipt_sha256"),
        "run_id": run_id,
    }


def _verify_base_binding(binding: dict[str, Any], ws: Any) -> None:
    #: Resolved against the WORKSPACE root, not the module's, so the whole
    #: ladder stays exercisable against a temporary tree. A gate that can only
    #: run against the real receipts directory cannot be shown to come back red
    #: without writing evidence, and evidence written to prove a test is not
    #: evidence.
    target = Path(ws.root) / binding["receipt"]
    if not target.is_file():
        raise FreezeRefused(
            f"the base receipt this attestation binds is gone: {binding['receipt']}"
        )
    if _sha_file(target) != binding["receipt_file_sha256"]:
        raise FreezeRefused(
            f"{binding['receipt']} has changed since it was attested. Receipts are "
            "immutable; one that moved is not the artefact the proof was about."
        )
    #: The attestation must bind the receipt that is CURRENTLY in force, not an
    #: older one that happens to still be on disk. Otherwise a fresh base rung
    #: could be run and an attestation of its predecessor would still satisfy
    #: the gate.
    current = base.runs_of(binding["stem"], ws.receipts)
    if not current or base._rel(current[-1], ws.root) != binding["receipt"]:
        raise FreezeRefused(
            f"the attestation binds {binding['receipt']}, but the {binding['stem']} "
            "rung in force is "
            f"{base._rel(current[-1], ws.root) if current else 'absent'}. An "
            "attestation of a superseded rung does not attest the run that would "
            "execute."
        )


def _write(stem_key: str, body: dict[str, Any], ws: Any) -> dict[str, Any]:
    protocol = base.load_protocol(ws.protocol)
    stem = base.stem_for(protocol, stem_key)
    body = {"schema": ATTESTATION_SCHEMA, **body}
    return {**body, **base.write_receipt(stem, body, ws)}


def _read(stem_key: str, ws: Any) -> dict[str, Any]:
    protocol = base.load_protocol(ws.protocol)
    stem = base.stem_for(protocol, stem_key)
    receipt = base.latest_receipt(stem, ws.receipts)
    if receipt is None:
        raise FreezeRefused(
            f"the {stem_key} companion attestation is missing. Its base rung may have "
            "frozen, but the V2R3-specific proof for that rung was never sealed, and "
            "a proof that exists only in console output is not a frozen proof."
        )
    return receipt


# ---------------------------------------------------------------------------
# the three proofs, each recomputed from scratch every time it is asked for


def prove_root_disjointness() -> dict[str, Any]:
    """Every V2R3 root against every root any earlier study ever declared.

    UNVERIFIABLE BLOCKS. A shape the reader cannot interpret is not assumed
    disjoint: that assumption is how 7 CFR 273 -- SFI1-spent and a VBC1 declared
    root -- entered the V2R2 frame.
    """
    prior = ri.prior_root_identities(exclude_modules={"sources_v2r3"})
    if prior["unverifiable_count"]:
        raise FreezeRefused(
            "prior sources modules hold root declarations this reader cannot "
            f"interpret: {prior['unverifiable'][:3]}. UNVERIFIABLE blocks; it is "
            "never assumed disjoint."
        )
    mine = ri.read_module_roots("sources_v2r3")
    if mine["unverifiable"]:
        raise FreezeRefused(
            "this frame declares roots in shapes the reader cannot interpret: "
            f"{mine['unverifiable'][:3]}"
        )
    clashes = sorted(mine["identities"] & prior["identities"])
    if clashes:
        raise FreezeRefused(
            "this frame declares roots an earlier study already declared: "
            f"{clashes[:6]}. Reporting the overlap is not enough -- the row is "
            "removed before admission and disjointness re-proved over the survivors."
        )
    return {
        "proved": True,
        "reader": "tools/root_identity.py",
        "prior_modules_read": len(prior["modules_read"]),
        "prior_identities": prior["identity_count"],
        "prior_by_family": prior["by_family"],
        "prior_unverifiable": 0,
        "prior_root_set_digest": _canonical_root_digest(prior["identities"]),
        "v2r3_roots": len(mine["identities"]),
        "v2r3_by_family": _by_family(mine["identities"]),
        "v2r3_unverifiable": 0,
        "clashes": 0,
    }


def _canonical_root_digest(identities: frozenset[tuple[str, ...]]) -> str:
    """One digest over the whole prior root set.

    Pinned so that a later run cannot quietly compare against a DIFFERENT prior
    set -- a sources module added, removed or edited -- and report the same zero
    clashes. The count alone would not catch a swap.
    """
    payload = json.dumps(sorted(list(i) for i in identities), separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _by_family(identities: frozenset[tuple[str, ...]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for identity in identities:
        counts[identity[0]] = counts.get(identity[0], 0) + 1
    return dict(sorted(counts.items()))


def prove_contract_consistency() -> dict[str, Any]:
    """Satisfiable, and the same machine the protocol describes.

    Two separate properties and both are required. V2R2 would have failed the
    first; a protocol that quietly described something other than what it ran
    would fail the second.
    """
    try:
        report = state_table.check_contract()
    except state_table.ContractBroken as error:
        raise FreezeRefused(
            f"CONTRACT_BROKEN: {error}. A reachable state with contradictory "
            "obligations blocks the freeze. That state is what V2R2 executed on, "
            "and it establishes nothing about production."
        ) from error

    completed = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "pytest", CONSISTENCY_TESTS, "-q"],
        cwd=NS,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise FreezeRefused(
            "the protocol's declared state machine and the executable one disagree, "
            "so the freeze refuses. If prose and code disagree, the prose is not a "
            f"description of anything.\n{completed.stdout[-2000:]}"
        )
    for row in report["rows"]:
        if set(row["required"]) & set(row["forbidden"]):
            raise FreezeRefused(f"row {row} requires and forbids the same record")
    return {
        "proved": True,
        "state": report["state"],
        "reachable_rows": report["reachable_rows"],
        "rows": report["rows"],
        "required_intersect_forbidden_empty_for_every_row": True,
        "prose_matches_executable_rows": True,
        "checked_by": [
            "tools/v2r3_state_table.py::check_contract",
            CONSISTENCY_TESTS,
        ],
    }


def prove_spent_disjointness(ws: Any) -> dict[str, Any]:
    """The frozen V2R3 universe against both spent cohorts, recomputed here.

    The enumerator subtracts them and this does not trust it. A filter and a
    proof written as one piece of code agree by construction and prove nothing.
    """
    protocol = base.load_protocol(ws.protocol)
    universe = base.latest_receipt(base.stem_for(protocol, "universe"), ws.receipts)
    if universe is None:
        raise FreezeRefused("the universe is not frozen, so there is nothing to prove")
    frozen = {str(row["lineage_id"]) for row in universe.get("pairs", ())}
    if not frozen:
        raise FreezeRefused(
            "the frozen universe declares no pairs. A disjointness proof over an "
            "empty set proves nothing, and a closure over zero pairs is vacuous."
        )

    intersections: dict[str, int] = {}
    sources: list[dict[str, Any]] = []
    for label, stem, expected in SPENT_UNIVERSE_STEMS:
        runs = sorted(ws.prior_receipts.glob(f"{stem}--*.json"))
        if not runs:
            raise FreezeRefused(
                f"{label.upper()}'s frozen universe receipt is not on disk, so V2R3 "
                "cannot prove it avoided that spent cohort. An unprovable "
                "disjointness is not an assumed one."
            )
        source = runs[-1]
        body = json.loads(source.read_text(encoding="utf-8"))
        spent = {str(row["lineage_id"]) for row in body.get("pairs", ())}
        if len(spent) != expected:
            raise FreezeRefused(
                f"{source.name} holds {len(spent)} distinct lineages, not the "
                f"{expected} this protocol names for {label.upper()}."
            )
        overlap = sorted(frozen & spent)
        if overlap:
            raise FreezeRefused(
                f"the frozen universe intersects {label.upper()}'s SPENT cohort, so "
                "the enumerator's exclusion and this proof disagree and one of them "
                f"is broken: {overlap[:6]}"
            )
        intersections[label] = 0
        sources.append(
            {
                "study": label,
                "source_receipt": base._rel(source, ws.root),
                "source_receipt_sha256": _sha_file(source),
                "distinct_lineages": len(spent),
            }
        )
    return {
        "proved": True,
        "frozen_pairs": len(frozen),
        "intersections": intersections,
        "sources": sources,
        "read_for": (
            "lineage ids only. No V2R1 or V2R2 verdict, count or violated case is "
            "read, and neither INVALID_INSTRUMENT_CONTRACT adjudication is re-opened "
            "or re-interpreted here."
        ),
    }


# ---------------------------------------------------------------------------
# writing


def attest_frame(ws: Any) -> dict[str, Any]:
    proof = prove_root_disjointness()
    return _write(
        "frame_attestation",
        {
            "rung": "0a",
            "rung_name": "frame_attestation",
            "attests": _base_binding(
                base.stem_for(base.load_protocol(ws.protocol), "acquisition_frame"), ws
            ),
            "pinned_files": _pins(FRAME_PINS),
            "root_disjointness": proof,
            "refuses_unless": "unverifiable == 0 AND clashes == 0",
        },
        ws,
    )


def attest_protocol(ws: Any) -> dict[str, Any]:
    proof = prove_contract_consistency()
    return _write(
        "protocol_attestation",
        {
            "rung": "1a",
            "rung_name": "protocol_attestation",
            "attests": _base_binding(
                base.stem_for(base.load_protocol(ws.protocol), "protocol"), ws
            ),
            "pinned_files": _pins(PROTOCOL_PINS),
            "contract_consistency": proof,
            "refuses_unless": ("the state table is SATISFIABLE AND the consistency suite passes"),
        },
        ws,
    )


def attest_universe(ws: Any) -> dict[str, Any]:
    proof = prove_spent_disjointness(ws)
    return _write(
        "universe_attestation",
        {
            "rung": "3a",
            "rung_name": "universe_attestation",
            "attests": _base_binding(
                base.stem_for(base.load_protocol(ws.protocol), "universe"), ws
            ),
            "spent_disjointness": proof,
            "refuses_unless": "both intersections are empty",
        },
        ws,
    )


# ---------------------------------------------------------------------------
# verifying


def verify_frame(ws: Any) -> dict[str, Any]:
    receipt = _read("frame_attestation", ws)
    _verify_base_binding(receipt["attests"], ws)
    _verify_pins(receipt["pinned_files"], "the frame attestation")
    fresh = prove_root_disjointness()
    recorded = receipt["root_disjointness"]
    if fresh["prior_root_set_digest"] != recorded["prior_root_set_digest"]:
        raise FreezeRefused(
            "the prior root set has changed since the frame was attested. Zero "
            "clashes against a different set is not the proof that was frozen."
        )
    return {"attestation": receipt["_receipt_path"], "recomputed": fresh}


def verify_protocol(ws: Any) -> dict[str, Any]:
    receipt = _read("protocol_attestation", ws)
    _verify_base_binding(receipt["attests"], ws)
    _verify_pins(receipt["pinned_files"], "the protocol attestation")
    fresh = prove_contract_consistency()
    recorded = receipt["contract_consistency"]
    if fresh["rows"] != recorded["rows"]:
        raise FreezeRefused(
            "the executable state table no longer produces the rows that were "
            "attested at the protocol freeze."
        )
    return {"attestation": receipt["_receipt_path"], "recomputed": fresh}


def verify_universe(ws: Any) -> dict[str, Any]:
    receipt = _read("universe_attestation", ws)
    _verify_base_binding(receipt["attests"], ws)
    fresh = prove_spent_disjointness(ws)
    recorded = receipt["spent_disjointness"]
    if fresh["frozen_pairs"] != recorded["frozen_pairs"]:
        raise FreezeRefused(
            f"the frozen universe now holds {fresh['frozen_pairs']} pairs, not the "
            f"{recorded['frozen_pairs']} that were attested."
        )
    for entry, was in zip(fresh["sources"], recorded["sources"], strict=True):
        if entry["source_receipt_sha256"] != was["source_receipt_sha256"]:
            raise FreezeRefused(
                f"{entry['study'].upper()}'s universe receipt has changed since the "
                "disjointness proof was frozen."
            )
    return {"attestation": receipt["_receipt_path"], "recomputed": fresh}


def verify_all(ws: Any) -> dict[str, Any]:
    """All three, recomputed. The gate calls this; nothing else should skip it."""
    return {
        "frame_attestation": verify_frame(ws),
        "protocol_attestation": verify_protocol(ws),
        "universe_attestation": verify_universe(ws),
    }
