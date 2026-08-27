"""The V2R3R1 companion attestations: proofs that are frozen, not printed.

WHY COMPANIONS AT ALL. The shared base freezer writes its immutable receipt
INSIDE its return path, so a wrapper that computes a proof and then decorates
the returned dictionary produces a proof that exists only in memory and in
console output. That is a false-provenance seam, and it is what the founder
audit caught in the parent chain before rung 0 ran. Each rung therefore writes a
SECOND immutable receipt that BINDS the base receipt it attests -- by path, by
run id and by the digest of the receipt FILE -- and carries its proof in its own
frozen body.

THE HELPERS ARE THE PARENT'S, ON PURPOSE. `v2r3_attestation` owns the binding,
pinning and verification machinery, and it is not spent-run evidence: it was
written for the parent chain but never bound to a measurement, because the
parent never produced one. Reimplementing it here would create a second copy of
the machinery that decides whether a proof is really frozen, free to drift from
the one every existing attestation was written by. What is NOT reused is its
FRAME proof: the parent's rung 0 proved root disjointness before a fetch, and
this chain fetches nothing.

WHAT EACH RUNG PROVES HERE:

    0a  frame       the inherited set is EXACTLY the parent's 300 rows, and
                    every one of the 1,200 payloads still hashes to what the
                    parent froze. No network, no re-fetch, no repair path.
    1a  protocol    the contract is SATISFIABLE and its prose agrees with its
                    executable rows -- AND the successor's scientific projection
                    is identical to the parent's. The second half is what makes
                    reusing unscored material legitimate rather than convenient.
    3a  universe    disjointness from BOTH spent universes, recomputed
                    independently of any filter, AND exact-set equality with the
                    parent's frozen universe. V2R3 is NOT a spent set: it is the
                    set being inherited, and the intersection with it is 300 by
                    design, which is why it is proven by equality rather than by
                    subtraction.

THE PARENT'S OWN ATTESTATIONS ARE NOT INHERITED. Verifying them would prove
something about a chain that is permanently non-executable, and they bind the
parent's scorer digest -- the digest this chain exists because the parent could
not keep.
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

import freeze_migration_closure_v2r1 as base  # noqa: E402
import v2r3_attestation as att  # noqa: E402
import v2r3r1_carry_forward as cf  # noqa: E402
import v2r3r1_semantics as sem  # noqa: E402

FreezeRefused = base.FreezeRefused

ATTESTATION_SCHEMA = "tavonel.v2.identity_change_migration_closure.v2r3r1_attestation.v1"

PARENT_UNIVERSE_STEM = "identity-change-migration-closure-v2r3-universe"
PARENT_NON_DISCLOSURE_STEM = "identity-change-migration-closure-v2r3-non-disclosure"
PARENT_DISPOSITION_STEM = "identity-change-migration-closure-v2r3-chain-disposition"

#: Files each attestation pins, relative to the namespace root. Declared rather
#: than gathered at write time, so "what was attested" is a decision and not a
#: record of whatever happened to be imported.
FRAME_PINS = (
    "acquisition/sources_v2r3r1.py",
    "tools/v2r3r1_carry_forward.py",
    "tools/enumerate_v2r3r1_universe.py",
)
PROTOCOL_PINS = (
    "protocols/IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R3R1.yaml",
    "protocols/IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R3.yaml",
    "tools/v2r3_state_table.py",
    "tools/v2r3_effective_identity.py",
    "tools/v2r3_quarantine_oracle.py",
    "tools/v2r3r1_semantics.py",
    "tests/test_v2r3_contract_consistency.py",
    "docs/COMPAT_IDENTITY_UNCERTAINTY_QUARANTINE.md",
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
            "frozen, but the V2R3R1-specific proof for that rung was never sealed, "
            "and a proof that exists only in console output is not a frozen proof."
        )
    return receipt


# ---------------------------------------------------------------------------
# the proofs


def prove_parent_disposition(ws: Any) -> dict[str, Any]:
    """The parent chain was adjudicated, and nothing was disclosed from it.

    Read from the two immutable receipts rather than restated. The eligibility
    of this chain's entire cohort rests on that adjudication, and a chain that
    asserted it in its own prose would be citing itself.
    """
    bindings = {}
    for name, stem in (
        ("non_disclosure", PARENT_NON_DISCLOSURE_STEM),
        ("disposition", PARENT_DISPOSITION_STEM),
    ):
        runs = base.runs_of(stem, ws.receipts)
        if not runs:
            raise FreezeRefused(
                f"the parent's {name} receipt is absent. This chain inherits an "
                "unscored cohort, and the record establishing that it is unscored is "
                "not optional."
            )
        body = json.loads(runs[-1].read_text(encoding="utf-8"))
        bindings[name] = {
            "receipt": base._rel(runs[-1], ws.root),
            "receipt_file_sha256": att._sha_file(runs[-1]),
            "run_id": (body.get("provenance") or {}).get("run_id"),
        }
        if body.get("outcome_disclosure") != "NONE_ESTABLISHED":
            raise FreezeRefused(
                f"the parent's {name} receipt records outcome_disclosure "
                f"{body.get('outcome_disclosure')!r}, not NONE_ESTABLISHED. Exact "
                "carry-forward is REFUSED and a fresh cohort is required."
            )
        bindings[name]["outcome_disclosure"] = body["outcome_disclosure"]

    disposition = json.loads(
        (ws.receipts / Path(bindings["disposition"]["receipt"]).name).read_text(encoding="utf-8")
    )
    if disposition.get("corpus_status") != "ACQUIRED_AND_FROZEN_BUT_UNSCORED":
        raise FreezeRefused(
            f"the parent's corpus status is {disposition.get('corpus_status')!r}, not "
            "ACQUIRED_AND_FROZEN_BUT_UNSCORED. Only unscored material may be carried "
            "forward."
        )
    if disposition.get("result_receipt_exists"):
        raise FreezeRefused("the parent's disposition records a result receipt")
    return {
        "held": True,
        "parent_chain_status": disposition.get("chain_status"),
        "parent_corpus_status": disposition.get("corpus_status"),
        "outcome_disclosure": "NONE_ESTABLISHED",
        "bindings": bindings,
        "why_this_is_read_and_not_restated": (
            "this chain's whole cohort is eligible because of that adjudication. A "
            "chain that asserted it in its own prose would be citing itself."
        ),
    }


def prove_exact_carry_forward() -> dict[str, Any]:
    return cf.prove_exact_carry_forward()


def prove_semantic_equivalence() -> dict[str, Any]:
    return sem.prove_semantic_equivalence()


def prove_contract_consistency() -> dict[str, Any]:
    return att.prove_contract_consistency()


def prove_spent_disjointness(ws: Any) -> dict[str, Any]:
    """Disjointness from V2R1's 285 and V2R2's 270, recomputed.

    V2R3 is deliberately NOT in the spent list. It is the set being inherited,
    the intersection with it is 300 by design, and it is proven by exact
    equality in `prove_exact_carry_forward` rather than by subtraction. Adding it
    here would make this chain refuse to inherit the material the ruling
    authorised it to inherit.
    """
    return att.prove_spent_disjointness(ws)


# ---------------------------------------------------------------------------
# writing


def attest_frame(ws: Any) -> dict[str, Any]:
    protocol = base.load_protocol(ws.protocol)
    return _write(
        "frame_attestation",
        {
            "rung": "0a",
            "rung_name": "frame_attestation",
            "attests": att._base_binding(base.stem_for(protocol, "acquisition_frame"), ws),
            "parent_universe": att._base_binding(PARENT_UNIVERSE_STEM, ws),
            "pinned_files": att._pins(FRAME_PINS),
            "parent_disposition": prove_parent_disposition(ws),
            "carry_forward": prove_exact_carry_forward(),
            "refuses_unless": (
                "every declared carry-forward delta is 0, the pair count is 300, "
                "every payload re-hashes to the parent's frozen digest, and the "
                "parent's outcome disclosure is NONE_ESTABLISHED"
            ),
        },
        ws,
    )


def attest_protocol(ws: Any) -> dict[str, Any]:
    protocol = base.load_protocol(ws.protocol)
    return _write(
        "protocol_attestation",
        {
            "rung": "1a",
            "rung_name": "protocol_attestation",
            "attests": att._base_binding(base.stem_for(protocol, "protocol"), ws),
            "pinned_files": att._pins(PROTOCOL_PINS),
            "contract_consistency": prove_contract_consistency(),
            "semantic_equivalence": prove_semantic_equivalence(),
            "refuses_unless": (
                "the state table is SATISFIABLE, the consistency suite passes, and "
                "the scientific projection of this protocol equals the parent's "
                "exactly"
            ),
        },
        ws,
    )


def attest_universe(ws: Any) -> dict[str, Any]:
    protocol = base.load_protocol(ws.protocol)
    return _write(
        "universe_attestation",
        {
            "rung": "3a",
            "rung_name": "universe_attestation",
            "attests": att._base_binding(base.stem_for(protocol, "universe"), ws),
            "parent_universe": att._base_binding(PARENT_UNIVERSE_STEM, ws),
            "spent_disjointness": prove_spent_disjointness(ws),
            "exact_set_equality": _prove_frozen_universe_equals_parent(ws),
            "v2r3_is_not_a_spent_set": (
                "it is the set being inherited. Its intersection with this universe "
                "is 300 by design and is proven by equality, not by subtraction."
            ),
            "refuses_unless": (
                "both spent intersections are empty AND this chain's frozen universe "
                "is exactly the parent's, row for row and digest for digest"
            ),
        },
        ws,
    )


def _prove_frozen_universe_equals_parent(ws: Any) -> dict[str, Any]:
    """Compare THIS chain's frozen universe receipt to the parent's.

    Distinct from the carry-forward proof at rung 0a, which compares the parent's
    receipt to the rows about to be enumerated. This one runs after rung 3 and
    asks the later question: is the set that actually got FROZEN here the set
    that was carried? A proof at rung 0 says nothing about what rung 3 sealed.
    """
    protocol = base.load_protocol(ws.protocol)
    frozen = base.latest_receipt(base.stem_for(protocol, "universe"), ws.receipts)
    if frozen is None:
        raise FreezeRefused("this chain's universe is not frozen")
    parent = cf.load_parent(ws.receipts)
    equality = cf.compare(parent["pairs"], frozen["pairs"])
    return {
        **equality,
        "parent_universe_sha256": parent.get("universe_sha256"),
        "frozen_universe_sha256": frozen.get("universe_sha256"),
        "compared": "this chain's FROZEN universe against the parent's frozen universe",
        "why_not_the_same_proof_as_rung_0a": (
            "rung 0a compares the parent's receipt to the rows about to be "
            "enumerated. This asks what rung 3 actually sealed. A proof about the "
            "input says nothing about the output."
        ),
    }


# ---------------------------------------------------------------------------
# verifying


def verify_frame(ws: Any) -> dict[str, Any]:
    receipt = _read("frame_attestation", ws)
    att._verify_base_binding(receipt["attests"], ws)
    att._verify_base_binding(receipt["parent_universe"], ws)
    att._verify_pins(receipt["pinned_files"], "the frame attestation")
    prove_parent_disposition(ws)
    fresh = prove_exact_carry_forward()
    recorded = receipt["carry_forward"]
    if fresh["parent_universe_sha256"] != recorded["parent_universe_sha256"]:
        raise FreezeRefused(
            "the parent's universe digest has changed since the frame was attested. "
            "Zero deltas against a different set is not the proof that was frozen."
        )
    if fresh["equality"] != recorded["equality"]:
        raise FreezeRefused(
            "the carry-forward equality no longer matches what was attested at rung 0."
        )
    return {"attestation": receipt["_receipt_path"], "recomputed": fresh}


def verify_protocol(ws: Any) -> dict[str, Any]:
    receipt = _read("protocol_attestation", ws)
    att._verify_base_binding(receipt["attests"], ws)
    att._verify_pins(receipt["pinned_files"], "the protocol attestation")
    fresh = prove_contract_consistency()
    if fresh["rows"] != receipt["contract_consistency"]["rows"]:
        raise FreezeRefused(
            "the executable state table no longer produces the rows that were "
            "attested at the protocol freeze."
        )
    equivalence = prove_semantic_equivalence()
    recorded = receipt["semantic_equivalence"]
    if equivalence["scientific_projection_sha256"] != recorded["scientific_projection_sha256"]:
        raise FreezeRefused(
            "the scientific projection has moved since the protocol was attested:\n"
            f"  attested: {recorded['scientific_projection_sha256']}\n"
            f"  current:  {equivalence['scientific_projection_sha256']}\n"
            "The cohort was inherited on the basis of the attested question."
        )
    return {
        "attestation": receipt["_receipt_path"],
        "recomputed": fresh,
        "semantic_equivalence": equivalence,
    }


def verify_universe(ws: Any) -> dict[str, Any]:
    receipt = _read("universe_attestation", ws)
    att._verify_base_binding(receipt["attests"], ws)
    att._verify_base_binding(receipt["parent_universe"], ws)
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
    equality = _prove_frozen_universe_equals_parent(ws)
    if (
        equality["frozen_universe_sha256"]
        != receipt["exact_set_equality"]["frozen_universe_sha256"]
    ):
        raise FreezeRefused(
            "this chain's frozen universe digest has changed since it was attested."
        )
    return {
        "attestation": receipt["_receipt_path"],
        "recomputed": fresh,
        "exact_set_equality": equality,
    }


def verify_all(ws: Any) -> dict[str, Any]:
    """All three, recomputed. The gate calls this; nothing else should skip it."""
    return {
        "frame_attestation": verify_frame(ws),
        "protocol_attestation": verify_protocol(ws),
        "universe_attestation": verify_universe(ws),
    }
