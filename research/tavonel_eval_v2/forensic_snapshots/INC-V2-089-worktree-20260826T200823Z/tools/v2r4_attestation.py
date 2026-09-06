"""The V2R4 companion attestations: proofs that are frozen, not printed.

WHY COMPANIONS AT ALL. The shared base freezer writes its immutable receipt
INSIDE its return path, so a wrapper that computes a proof and then decorates
the returned dictionary produces a proof that exists only in memory and in
console output. That is a false-provenance seam, and it is what the founder
audit caught in the V2R3 chain before rung 0 ran. Each rung therefore writes a
SECOND immutable receipt that BINDS the base receipt it attests -- by path, by
run id and by the digest of the receipt FILE -- and carries its proof in its own
frozen body.

THE HELPERS ARE V2R3'S, ON PURPOSE. `v2r3_attestation` owns the binding, pinning
and verification machinery. Reimplementing it here would create a second copy of
the machinery that decides whether a proof is really frozen, free to drift from
the one every existing attestation was written by.

FOUR RUNGS, NOT THREE. V2R3 had three; V2R4 adds a fourth, and the reason it
exists is INC-V2-067.

    0a  frame     root disjointness through ONE canonicaliser, before any fetch,
                  AND separation from SFI3_ROOT_RESERVATION_V1 on container
                  identity. UNVERIFIABLE blocks in both directions.

    1a  protocol  the contract is SATISFIABLE and its prose agrees with its
                  executable rows -- AND the scientific core crossed from V2R3R1
                  intact, with every remaining difference predeclared. The
                  second half does NOT claim the projection is IDENTICAL: the
                  existing checker refuses on this pair, first on
                  `/cohort/floor_is_not_lowered`, a field V2R4 added precisely to
                  say the floor did not move. What it proves is
                  SCIENTIFIC_CORE_PRESERVED_WITH_PREDECLARED_HYGIENE_DELTAS.

    3a  universe  disjointness from every spent universe, recomputed
                  independently of the enumerator's filter.

    4a  domain    DECLARED == GRADED == RECEIPT, with the GRADED set obtained by
                  EXECUTING the grading function on a null population and reading
                  the keys it emits. This is the rung whose absence cost the
                  V2R3R1 corpus: a pass rule named eight invariants, the
                  instrument graded one, nothing compared the two, and 300 pairs
                  were spent establishing one answer. A domain read from a
                  declaration would have agreed with the declaration.

THE PREDECESSORS' ATTESTATIONS ARE NOT INHERITED. Verifying them would prove
something about chains that are spent, and they bind scorer digests this chain
exists because those scorers could not keep.
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
import invariant_domain  # noqa: E402
import root_identity as ri  # noqa: E402
import sfi3_root_reservation as reservation  # noqa: E402
import sources_v2r4 as frame  # noqa: E402
import v2r3_attestation as att  # noqa: E402
import v2r4_grading as grading  # noqa: E402
import v2r4_semantics_delta as delta  # noqa: E402

FreezeRefused = base.FreezeRefused

ATTESTATION_SCHEMA = "tavonel.v2.identity_change_migration_closure.v2r4_attestation.v1"

#: Files each attestation pins, relative to the namespace root. Named here
#: rather than gathered at write time so that "what was attested" is a
#: declaration and not a record of whatever happened to be imported.
FRAME_PINS = (
    "acquisition/sources_v2r4.py",
    "tools/root_identity.py",
    "tools/sfi3_root_reservation.py",
    "tools/probe_v2r4_roots.py",
)
PROTOCOL_PINS = (
    "protocols/IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R4.yaml",
    "protocols/IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R3R1.yaml",
    "tools/v2r3_state_table.py",
    "tools/v2r3_effective_identity.py",
    "tools/v2r3_quarantine_oracle.py",
    "tools/v2r4_semantics_delta.py",
    "tests/test_v2r3_contract_consistency.py",
    "docs/COMPAT_IDENTITY_UNCERTAINTY_QUARANTINE.md",
)
DOMAIN_PINS = (
    "protocols/IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R4.yaml",
    "tools/invariant_domain.py",
    "tools/v2r4_grading.py",
    "tools/rehearse_v2r4_closure.py",
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
            "frozen, but the V2R4-specific proof for that rung was never sealed, and "
            "a proof that exists only in console output is not a frozen proof."
        )
    return receipt


# ---------------------------------------------------------------------------
# the proofs


#: The frame this study screens. Named once, because the defect this constant
#: prevents was live in the first version of this file.
SELF_MODULE = "sources_v2r4"


def prove_root_disjointness(module: str = SELF_MODULE) -> dict[str, Any]:
    """Every V2R4 root against every root any other study ever declared.

    NOT DELEGATED TO THE PARENT, and the reason is not stylistic. V2R3's version
    hardcodes `sources_v2r3` in all three places it names a module, so calling it
    from here would have proved that V2R3's roots are disjoint -- a true
    statement about the wrong study -- and returned it under a rung that claims
    to be about V2R4. The first version of this file did exactly that. It is the
    same class as the 21 of 24 V2R2 gate tests that silently asserted things
    about V2R1 and passed.

    What is NOT copied is the part that must not drift: the canonicalisation, the
    UNVERIFIABLE policy and the set digest all still come from `root_identity`
    and the parent's helpers. Only the module name is this study's own, and it is
    a parameter rather than a literal so a successor does not repeat the mistake.

    UNVERIFIABLE BLOCKS on both sides. A shape the reader cannot interpret is not
    assumed disjoint: that assumption is how 7 CFR 273 -- SFI1-spent and a VBC1
    declared root -- entered the V2R2 frame.
    """
    prior = ri.prior_root_identities(exclude_modules={module})
    if prior["unverifiable_count"]:
        raise FreezeRefused(
            "prior sources modules hold root declarations this reader cannot "
            f"interpret: {prior['unverifiable'][:3]}. UNVERIFIABLE blocks; it is "
            "never assumed disjoint."
        )
    mine = ri.read_module_roots(module)
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
        "module": module,
        "prior_modules_read": len(prior["modules_read"]),
        "prior_identities": prior["identity_count"],
        "prior_by_family": prior["by_family"],
        "prior_unverifiable": 0,
        "prior_root_set_digest": att._canonical_root_digest(prior["identities"]),
        "roots_declared": len(mine["identities"]),
        "by_family": att._by_family(mine["identities"]),
        "unverifiable": 0,
        "clashes": 0,
        "screened_at_container_level_too": (
            "the git identity tuple carries a prefix, so the same repository under a "
            "different subtree reads as a different identity. Candidates were "
            "screened on owner/repo before being probed, which is STRICTER than this "
            "identity comparison and is what the frame records."
        ),
    }


def prove_sfi3_separation() -> dict[str, Any]:
    """V2R4's declared containers lie outside SFI3_ROOT_RESERVATION_V1.

    Container identity only. Nothing here opens an SFI3 payload, expands an SFI3
    category, counts a qualifying pair or reads a change outcome -- and it could
    not, because the reservation is built from source and root IDENTITY METADATA
    and refuses any family whose membership is not decidable from it.

    THE RESERVATION IS BUILT FRESH, not read back from a receipt. A separation
    proof against a stored copy of the thing it is separating from would agree
    with whatever that copy said.
    """
    built = reservation.build()
    held = reservation.require_separation(
        reservation=built,
        families=frame.declared_containers(),
        study=frame.PROTOCOL_ID,
    )
    return {
        **held,
        "sfi3_protocol_id": built["sfi3_protocol_id"],
        "sfi3_frame_module_sha256": built["frame_module_sha256"],
        "sfi3_replacement_module_sha256": built["replacement_module_sha256"],
        "why_a_reservation_and_not_a_cohort_comparison": (
            "SFI3's cohort does not exist and must not until V2R4 passes, because "
            "SFI3's freeze gate is downstream of MIGRATION_CLOSURE_ACCEPTANCE_V1. "
            "Requiring INVARIANT_8 to prove disjointness from SFI3 MATERIAL made a "
            "circular gate whose only exits were forbidden: open SFI3 early, or let "
            "the invariant pass vacuously over a population that is empty because it "
            "cannot yet be non-empty (INC-V2-036). Container identity is decidable "
            "now; a cohort comparison is not."
        ),
        "the_replacement_pool_is_inside_the_reservation": (
            "a container that is only a replacement candidate is still reserved. "
            "SFI3 may land there after an availability failure, and a V2R4 root "
            "sitting in the pool would silently narrow SFI3's escape route."
        ),
        "wikipedia_is_refused_not_reported_clean": (
            "reservation membership for encyclopedia_wikipedia is by category and is "
            "not decidable from identity metadata. The reservation REFUSES the family "
            "rather than reporting it disjoint, and V2R4 excludes it. 'We could not "
            "tell' and 'they do not overlap' are different answers."
        ),
    }


def prove_contract_consistency() -> dict[str, Any]:
    return att.prove_contract_consistency()


def prove_allowed_delta() -> dict[str, Any]:
    """The scientific core crossed from V2R3R1 intact. NOT a claim of identity.

    `v2r3r1_semantics.py` is preserved untouched -- it is historical evidence for
    the V2R3 -> V2R3R1 carry-forward decision, where the SAME UNSCORED 300 pairs
    crossed and exact equality was both true and required. V2R4 has a fresh
    protocol id, a fresh cohort, no carry-forward and full-eight grading, so exact
    equality is neither true nor required, and editing that checker to make this
    transition pass would have destroyed what it was built to detect.
    """
    return delta.prove_allowed_delta()


#: Every cohort whose lineages are spent, with the count each frozen receipt
#: must still hold. Read for LINEAGE IDS ONLY -- no verdict, no violation count,
#: no adjudication.
#:
#: FOUR, NOT TWO. V2R3's list names v2r1 and v2r2, because those were the only
#: spent cohorts when it was written. Delegating to it from here would have
#: proved V2R4 disjoint from the two OLDEST cohorts and said nothing about the
#: 300 lineages V2R3R1 measured -- the nearest, most recently drawn, most likely
#: to overlap material in the programme. Silence is not disjointness: a proof
#: that reports `holds` over the sets it happened to check, while never looking
#: at the one that matters most, is the shape this ledger keeps recording.
SPENT_UNIVERSE_STEMS: tuple[tuple[str, str, int], ...] = (
    ("v2r1", "identity-change-migration-closure-v2r1-universe", 285),
    ("v2r2", "identity-change-migration-closure-v2r2-universe", 270),
    ("v2r3", "identity-change-migration-closure-v2r3-universe", 300),
    ("v2r3r1", "identity-change-migration-closure-v2r3r1-universe", 300),
)


def prove_spent_disjointness(ws: Any) -> dict[str, Any]:
    """The frozen V2R4 universe against EVERY spent cohort, recomputed here.

    NOT DELEGATED TO THE PARENT, for the same reason the root proof is not: V2R3's
    version iterates V2R3's spent list, so calling it from here proves a true
    statement about a narrower question and returns it under a rung that claims to
    have proved the whole one.

    The enumerator already subtracts these and this does not trust it. A filter
    and a proof written as one piece of code agree by construction and prove
    nothing; written separately, a silent failure in either is visible.
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
                f"{label.upper()}'s frozen universe receipt is not on disk, so V2R4 "
                "cannot prove it avoided that spent cohort. An unprovable "
                "disjointness is not an assumed one."
            )
        source = runs[-1]
        body = json.loads(source.read_text(encoding="utf-8"))
        spent = {str(row["lineage_id"]) for row in body.get("pairs", ())}
        if len(spent) != expected:
            raise FreezeRefused(
                f"{source.name} holds {len(spent)} distinct lineages, not the "
                f"{expected} this attestation names for {label.upper()}. A cohort "
                "whose size has moved is not the cohort this proof was written for."
            )
        overlap = sorted(frozen & spent)
        intersections[label] = len(overlap)
        sources.append(
            {
                "study": label,
                "source_receipt": base._rel(source, ws.root),
                "source_receipt_sha256": att._sha_file(source),
                "spent_lineages": len(spent),
                "intersection": len(overlap),
                "overlapping": overlap[:6],
            }
        )
        if overlap:
            raise FreezeRefused(
                f"the frozen V2R4 universe shares {len(overlap)} lineage(s) with "
                f"{label.upper()}'s spent cohort: {overlap[:6]}. Spent material "
                "cannot be a prospective confirmatory denominator."
            )

    return {
        "proved": True,
        "frozen_pairs": len(frozen),
        "intersections": intersections,
        "sources": sources,
        "cohorts_checked": len(SPENT_UNIVERSE_STEMS),
        "read_for": (
            "lineage ids only. No predecessor's verdict, invariant outcome, "
            "violation count or adjudication is read here."
        ),
        "why_four_and_not_two": (
            "V2R3's list names v2r1 and v2r2 because those were the only spent "
            "cohorts when it was written. V2R3's 300 were carried forward unscored "
            "into V2R3R1 and MEASURED there, so they are spent for V2R4 -- and they "
            "are the nearest and most recently drawn material in the programme. A "
            "proof that omitted them would report `holds` while never looking at "
            "the cohort most likely to overlap."
        ),
        "independent_of_the_enumerator": (
            "the enumerator subtracts these sets during admission and this proof "
            "does not read its output. A filter and a proof written as one piece of "
            "code agree by construction and prove nothing."
        ),
    }


def prove_invariant_domain() -> dict[str, Any]:
    """DECLARED == GRADED == RECEIPT, on full identifiers, as SET EQUALITY.

    The graded set is obtained by EXECUTING `v2r4_grading.grade` on a null
    population and reading the keys it emits -- never by reading a list that says
    what it grades. A domain read from a declaration agrees with the declaration,
    which is exactly the check INC-V2-067 needed and did not have.

    A COUNT WOULD NOT DO. Eight declared and eight graded is satisfied by eight
    wrong names; only set equality on full identifiers rules that out.
    """
    domain = grading.require_domain()
    exclusions = grading.require_exclusion_domain()
    return {
        "held": True,
        "declared": list(domain["declared"]),
        "graded": list(domain["graded"]),
        "receipt_schema": list(domain["schema_required"]),
        "graded_by": (
            "EXECUTING v2r4_grading.grade on a null population and reading the "
            "invariant keys it emitted"
        ),
        "compared_as": "set equality on full identifiers, in both directions",
        "not_a_count": (
            "a count of eight is satisfied by eight wrong names. INC-V2-067 is what "
            "the absence of this comparison cost: a pass rule named eight "
            "invariants, the instrument graded one, nothing compared them, and 300 "
            "pairs were spent establishing one answer."
        ),
        "exclusion_domain": exclusions,
        "sfi3_is_not_an_exclusion_population": (
            grading.SFI3_SEPARATION_IS_A_RESERVATION_NOT_AN_INVARIANT
        ),
    }


# ---------------------------------------------------------------------------
# writing


def attest_frame(ws: Any) -> dict[str, Any]:
    roots = prove_root_disjointness()
    sfi3 = prove_sfi3_separation()
    return _write(
        "frame_attestation",
        {
            "rung": "0a",
            "rung_name": "frame_attestation",
            "attests": att._base_binding(
                base.stem_for(base.load_protocol(ws.protocol), "acquisition_frame"), ws
            ),
            "pinned_files": att._pins(FRAME_PINS),
            "root_disjointness": roots,
            "sfi3_separation": sfi3,
            "refuses_unless": (
                "unverifiable == 0 AND clashes == 0 AND every declared container "
                "lies outside SFI3_ROOT_RESERVATION_V1"
            ),
        },
        ws,
    )


def attest_protocol(ws: Any) -> dict[str, Any]:
    consistency = prove_contract_consistency()
    allowed = prove_allowed_delta()
    return _write(
        "protocol_attestation",
        {
            "rung": "1a",
            "rung_name": "protocol_attestation",
            "attests": att._base_binding(
                base.stem_for(base.load_protocol(ws.protocol), "protocol"), ws
            ),
            "pinned_files": att._pins(PROTOCOL_PINS),
            "contract_consistency": consistency,
            "allowed_delta": allowed,
            "refuses_unless": (
                "the state table is SATISFIABLE AND the consistency suite passes AND "
                "v2r4_semantics_delta returns "
                "SCIENTIFIC_CORE_PRESERVED_WITH_PREDECLARED_HYGIENE_DELTAS"
            ),
            "not_identical_and_does_not_claim_to_be": (
                "an earlier draft of this rung claimed the V2R3R1 -> V2R4 scientific "
                "projection is IDENTICAL and bound v2r3r1_semantics.py to prove it. "
                "That claim was FALSE: the checker refuses on this pair, and the "
                "first difference it reports is /cohort/floor_is_not_lowered -- a "
                "field this protocol added precisely to say the floor did NOT move."
            ),
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
            "attests": att._base_binding(
                base.stem_for(base.load_protocol(ws.protocol), "universe"), ws
            ),
            "spent_disjointness": proof,
            "refuses_unless": "every intersection is empty",
        },
        ws,
    )


def _why_superseded(
    was: set[str],
    now: set[str],
    widens: bool,
    rebinds: bool,
    prior: dict[str, Any],
    binding: dict[str, Any],
) -> str:
    """The reason, assembled from what actually moved rather than asserted.

    The first version of this hardcoded the delegation story, because that was
    the only reason a supersede had ever been needed. The second supersede was a
    REBIND -- the proof was already complete -- and the hardcoded prose would have
    sealed a receipt whose stated reason was false. A `why` that does not depend
    on what changed is not a reason, it is a label.
    """
    reasons: list[str] = []
    if widens:
        reasons.append(
            "the superseded receipt was written by a proof that delegated to V2R3's, "
            "which iterates V2R3's spent list. It proved disjointness from "
            f"{sorted(was)} and was silent on {sorted(now - was)} -- the nearest, "
            "most recently drawn spent cohorts in the programme."
        )
    if rebinds:
        reasons.append(
            "the superseded receipt binds universe run "
            f"{(prior.get('attests') or {}).get('run_id')}, but the rung in force is "
            f"{binding.get('run_id')}. An attestation of a receipt that is no longer "
            "authoritative does not attest the run that would execute."
        )
    return " ".join(reasons)


def supersede_universe_attestation(ws: Any) -> dict[str, Any]:
    """Re-seal rung 3's companion when its sealed proof covers too few cohorts.

    WHY THIS EXISTS, on the record rather than smoothed away. `prove_spent_
    disjointness` was first written here as a one-line delegation to V2R3's, and
    V2R3's iterates V2R3's spent list -- v2r1 and v2r2. The receipt it sealed
    therefore reported `holds` over the two OLDEST cohorts and said nothing about
    the 300 lineages V2R3R1 measured: the nearest, most recently drawn, most
    likely to overlap material in the programme. Nothing was contaminated -- the
    intersection is empty against all four, checked -- but a proof is not made
    complete by being lucky, and the sealed sentence claimed more than it had
    looked at. INC-V2-077, and the second instance of the delegation-to-parent
    class after `prove_root_disjointness`.

    The prior receipt is never deleted or rewritten. It is named here, with what
    it proved and what it did not.

    Guarded exactly as the base `supersede_universe` is, and for the same reason:
    reachable only while no V2R4 outcome has been read. A proof widened after a
    result is a proof that could have been steered by it.
    """
    protocol = base.load_protocol(ws.protocol)
    #: The measurement glob comes from THIS protocol's own `measurement` stem,
    #: not from `base.MEASUREMENT_GLOB`. That global is a module attribute the
    #: adapters rebind, and V2R2's adapter rebinds it PERMANENTLY at import, so
    #: whichever freezer was imported last decides which study's outcomes this
    #: guard looks for. A gate that can be aimed at another cohort's receipts by
    #: import order is not a gate. Same defect class, third instance.
    blocking = sorted(
        path.name for path in ws.receipts.glob(f"{base.stem_for(protocol, 'measurement')}--*.json")
    )
    if blocking:
        raise FreezeRefused(
            "the universe attestation may not be re-sealed: V2R4 has already been "
            "SCORED, and from that moment widening a disjointness proof could be "
            "steered by the result.\n  " + "\n  ".join(blocking)
        )

    stem = base.stem_for(protocol, "universe_attestation")
    prior = base.latest_receipt(stem, ws.receipts)
    if prior is None:
        raise FreezeRefused(
            "there is no frozen universe attestation to supersede. Use the "
            "`universe` rung, which writes it."
        )

    proof = prove_spent_disjointness(ws)
    was = {row["study"] for row in prior.get("spent_disjointness", {}).get("sources", ())}
    now = {row["study"] for row in proof["sources"]}
    widens = not (now <= was)

    #: A NO-OP MEANS BOTH HALVES ARE ALREADY RIGHT -- the same distinction the
    #: base `supersede_universe` draws. An attestation can be complete in what it
    #: proves and still bind a receipt that is no longer the rung in force, and
    #: refusing to re-seal that would be refusing to repair a broken chain
    #: because the proof had not moved. INC-V2-078 produced exactly that state.
    binding = att._base_binding(base.stem_for(protocol, "universe"), ws)
    rebinds = binding.get("run_id") != (prior.get("attests") or {}).get("run_id")

    if not widens and not rebinds:
        raise FreezeRefused(
            f"the sealed attestation already covers {sorted(was)}, this proof "
            f"computes {sorted(now)}, and it already binds the universe receipt in "
            "force. Superseding an attestation that is complete in both halves "
            "would produce a second receipt for the same fact and weaken the "
            "idempotency that keeps a rung from acquiring two differently-attested "
            "versions."
        )

    return _write(
        "universe_attestation",
        {
            "rung": "3a",
            "rung_name": "universe_attestation",
            "state": "SUPERSEDING",
            "attests": binding,
            "spent_disjointness": proof,
            "refuses_unless": "every intersection is empty",
            "supersedes": {
                "receipt": prior.get("_receipt_path"),
                "run_id": (prior.get("provenance") or {}).get("run_id"),
                "cohorts_proved": sorted(was),
                "cohorts_omitted": sorted(now - was),
                "widens_the_proof": widens,
                "rebinds_the_rung": rebinds,
                "superseded_binding_run_id": (prior.get("attests") or {}).get("run_id"),
                "why": _why_superseded(was, now, widens, rebinds, prior, binding),
                "was_it_wrong": (
                    "no. Every intersection this proof computes is empty, so the "
                    "frozen universe was never contaminated. What was wrong is what "
                    "the sealed receipt SAID -- its scope, or the receipt it named -- "
                    "not the material it was about."
                ),
                "permitted_because": (
                    "no V2R4 measurement receipt existed, checked mechanically. This "
                    "path shuts the moment an outcome has been read."
                ),
                "preserved": True,
            },
        },
        ws,
    )


def attest_domain(ws: Any) -> dict[str, Any]:
    proof = prove_invariant_domain()
    return _write(
        "domain_attestation",
        {
            "rung": "4a",
            "rung_name": "domain_attestation",
            "attests": att._base_binding(
                base.stem_for(base.load_protocol(ws.protocol), "scorer_acceptance"), ws
            ),
            "pinned_files": att._pins(DOMAIN_PINS),
            "invariant_domain": proof,
            "refuses_unless": (
                "DECLARED_INVARIANT_SET == GRADED_INVARIANT_SET == "
                "RECEIPT_INVARIANT_SET, as set equality on full identifiers, with "
                "GRADED obtained by executing the grading function"
            ),
        },
        ws,
    )


# ---------------------------------------------------------------------------
# verifying


def verify_frame(ws: Any) -> dict[str, Any]:
    receipt = _read("frame_attestation", ws)
    att._verify_base_binding(receipt["attests"], ws)
    att._verify_pins(receipt["pinned_files"], "the frame attestation")

    fresh_roots = prove_root_disjointness()
    if (
        fresh_roots["prior_root_set_digest"]
        != receipt["root_disjointness"]["prior_root_set_digest"]
    ):
        raise FreezeRefused(
            "the prior root set has changed since the frame was attested. Zero "
            "clashes against a different set is not the proof that was frozen."
        )

    fresh_sfi3 = prove_sfi3_separation()
    recorded = receipt["sfi3_separation"]
    if fresh_sfi3["content_digest"] != recorded["content_digest"]:
        raise FreezeRefused(
            "SFI3_ROOT_RESERVATION_V1 has changed since the frame was attested.\n"
            f"  frozen:  {recorded['content_digest']}\n"
            f"  current: {fresh_sfi3['content_digest']}\n"
            "Separation from a different reservation is not the separation that was "
            "proved, and the reservation may not be widened after V2R4 declares."
        )
    if fresh_sfi3["containers_checked"] != recorded["containers_checked"]:
        raise FreezeRefused(
            "V2R4 now declares a different number of containers than the separation "
            f"proof covered: {fresh_sfi3['containers_checked']} against "
            f"{recorded['containers_checked']}."
        )
    return {
        "attestation": receipt["_receipt_path"],
        "recomputed": {"root_disjointness": fresh_roots, "sfi3_separation": fresh_sfi3},
    }


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

    fresh_delta = prove_allowed_delta()
    recorded = receipt["allowed_delta"]
    if fresh_delta["verdict"] != recorded["verdict"]:
        raise FreezeRefused(
            f"the allowed-delta verdict is now {fresh_delta['verdict']}, not the "
            f"{recorded['verdict']} that was attested."
        )
    #: Compared as a SET of paths, not as a count. A delta count that happened to
    #: match while the paths moved would say the core is intact when a different
    #: part of the protocol had changed.
    was = {row["path"] for row in recorded["accepted_deltas"]}
    now = {row["path"] for row in fresh_delta["accepted_deltas"]}
    if was != now:
        raise FreezeRefused(
            "the set of accepted deltas has changed since the protocol was "
            f"attested. Added: {sorted(now - was)}. Removed: {sorted(was - now)}."
        )
    return {
        "attestation": receipt["_receipt_path"],
        "recomputed": {"contract_consistency": fresh, "allowed_delta": fresh_delta},
    }


def verify_universe(ws: Any) -> dict[str, Any]:
    receipt = _read("universe_attestation", ws)
    att._verify_base_binding(receipt["attests"], ws)
    fresh = prove_spent_disjointness(ws)
    recorded = receipt["spent_disjointness"]
    if fresh["frozen_pairs"] != recorded["frozen_pairs"]:
        raise FreezeRefused(
            f"the frozen universe now holds {fresh['frozen_pairs']} pairs, not the "
            f"{recorded['frozen_pairs']} that were attested."
        )
    #: COHORT SET EQUALITY, not a positional walk. The sealed receipt this
    #: verifier first met named two cohorts because it had been written by the
    #: PARENT's proof, which iterates the parent's spent list; the fresh proof
    #: names four. A `zip(..., strict=True)` catches that as a ValueError with no
    #: sentence attached, and a non-strict zip would have compared the two they
    #: share and reported agreement -- an attestation proving disjointness from
    #: the two oldest cohorts while silent on the nearest one. INC-V2-077.
    was_by_study = {row["study"]: row for row in recorded["sources"]}
    now_by_study = {row["study"]: row for row in fresh["sources"]}
    if set(was_by_study) != set(now_by_study):
        raise FreezeRefused(
            "the attested disjointness covers a different set of spent cohorts "
            "than this proof now computes.\n"
            f"  attested: {sorted(was_by_study)}\n"
            f"  current:  {sorted(now_by_study)}\n"
            "A sealed proof that omits a cohort does not become complete by being "
            "re-read. Re-seal it through `supersede-universe-attestation`."
        )
    for study, entry in sorted(now_by_study.items()):
        if entry["source_receipt_sha256"] != was_by_study[study]["source_receipt_sha256"]:
            raise FreezeRefused(
                f"{study.upper()}'s universe receipt has changed since the "
                "disjointness proof was frozen."
            )
    return {"attestation": receipt["_receipt_path"], "recomputed": fresh}


def verify_domain(ws: Any) -> dict[str, Any]:
    receipt = _read("domain_attestation", ws)
    att._verify_base_binding(receipt["attests"], ws)
    att._verify_pins(receipt["pinned_files"], "the domain attestation")
    fresh = prove_invariant_domain()
    recorded = receipt["invariant_domain"]
    for field in ("declared", "graded", "receipt_schema"):
        if set(fresh[field]) != set(recorded[field]):
            raise FreezeRefused(
                f"the {field} invariant set has changed since the domain was "
                f"attested.\n  frozen:  {sorted(recorded[field])}\n"
                f"  current: {sorted(fresh[field])}"
            )
    return {"attestation": receipt["_receipt_path"], "recomputed": fresh}


def verify_all(ws: Any) -> dict[str, Any]:
    """All four, recomputed. The gate calls this; nothing else should skip it."""
    return {
        "frame_attestation": verify_frame(ws),
        "protocol_attestation": verify_protocol(ws),
        "universe_attestation": verify_universe(ws),
        "domain_attestation": verify_domain(ws),
    }


#: Named so a reader can check the count without importing the base freezer, and
#: so a rung added here without a verifier is a visible omission rather than a
#: quiet one.
RUNGS = ("frame_attestation", "protocol_attestation", "universe_attestation", "domain_attestation")


def _require_every_rung_is_verified() -> None:
    """Every rung this module writes has a verifier, and `verify_all` calls it.

    A rung that is attested and never verified is a receipt, not a control: the
    freeze would record the proof and nothing would ever re-run it.
    """
    missing = [
        rung
        for rung in RUNGS
        if not callable(globals().get(f"attest_{rung.removesuffix('_attestation')}"))
        or not callable(globals().get(f"verify_{rung.removesuffix('_attestation')}"))
    ]
    if missing:
        raise RuntimeError(
            f"these rungs lack an attest/verify pair: {missing}. A rung that is "
            "attested and never verified is a receipt, not a control."
        )
    import inspect

    source = inspect.getsource(verify_all)
    absent = [rung for rung in RUNGS if rung not in source]
    if absent:
        raise RuntimeError(
            f"verify_all does not call {absent}. The gate calls verify_all, so a "
            "rung it skips is never re-proved at freeze time."
        )


_require_every_rung_is_verified()

__all__ = [
    "ATTESTATION_SCHEMA",
    "RUNGS",
    "attest_domain",
    "attest_frame",
    "attest_protocol",
    "attest_universe",
    "invariant_domain",
    "prove_allowed_delta",
    "prove_invariant_domain",
    "prove_root_disjointness",
    "prove_sfi3_separation",
    "verify_all",
    "verify_domain",
    "verify_frame",
    "verify_protocol",
    "verify_universe",
]
