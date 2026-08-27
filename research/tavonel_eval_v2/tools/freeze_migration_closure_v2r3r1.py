"""The freeze ladder for IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R3R1.

AN ADAPTER OVER THE SAME SHARED BASE the parent adapted, not over the parent's
adapter. Chaining adapter onto adapter would make this chain's behaviour depend
on the parent's overrides still being right for a study they were not written
for -- and the parent's chain is permanently non-executable, so its wiring is
exactly the thing not to inherit.

THE BINDINGS ARE SCOPED, for the reason the parent learned twice. Every adapter
over this base rebinds names on ONE module object, so a permanent rebind at
import time makes correctness depend on which adapter imported last. That is not
theoretical: it made 21 of 24 V2R2 gate tests assert things about V2R1 and pass,
and it turned eight of V2R2's adapter tests red when the parent first rebound at
import. `_bound()` applies the bindings for ONE RUNG and restores them
afterwards, on the error path too.

EVERY INHERITED STAGE IS WRAPPED, not only the ones with new behaviour. An
inherited stage called raw reads the base's OWN defaults, and the failure is
silent in the direction that matters: in the parent chain, `scorer` refused with
"rung 3 is already frozen" because it had resolved V2R1's protocol, found V2R1's
scorer stem and found V2R1's receipt. Nothing in that refusal said it was about
a different study.

WHAT DIFFERS FROM THE PARENT'S LADDER:

  * RUNG 0 DOES NOT REFUSE ON A NON-EMPTY CORPUS. The parent's rung 0 refused if
    acquired material already existed, because sealing a frame after acquisition
    records what was done rather than constraining what may be done. Here the
    material existing IS the premise: it is the parent's, already frozen, never
    scored. What rung 0 refuses on instead is a carry-forward that is not exact.
  * RUNG 0 PROVES EXACT CARRY-FORWARD rather than root disjointness. No root is
    declared here and nothing is fetched; the parent proved its roots before it
    fetched, and that proof is preserved in the parent's own receipts.
  * RUNG 1 ADDS SEMANTIC EQUIVALENCE to the contract-consistency gate. Inheriting
    unscored material is legitimate only while the successor asks the parent's
    question, so the projection equality is proven at the rung that seals the
    question.
  * RUNG 3 ADDS EXACT-SET EQUALITY against the parent's frozen universe, asked
    of what rung 3 actually SEALED rather than of what rung 0 carried.

THE BASE'S EXCLUSION POLICY STILL RUNS AT RUNG 3, deliberately. Disabling it
would prove nothing -- a filter that is switched off is not evidence that its
decisions are unchanged. Letting it run and then requiring its output to equal
the parent's row for row proves exactly that.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition"), str(NS / "compiler")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import freeze_migration_closure_v2r1 as base  # noqa: E402
import v2r3r1_attestation as att  # noqa: E402
import v2r3r1_carry_forward as cf  # noqa: E402

FreezeRefused = base.FreezeRefused

PROTOCOL = NS / "protocols" / "IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R3R1.yaml"
FRAME_MODULE = NS / "acquisition" / "sources_v2r3r1.py"

#: The PARENT's corpus, read only. This chain writes nothing into it.
CORPUS = NS / "artifacts" / "development" / "v2r3_corpus"
MEASUREMENT_GLOB = "identity-change-migration-closure-v2r3r1--*.json"

_OVERRIDE_TARGETS = (
    "PROTOCOL",
    "FRAME_MODULE",
    "MEASUREMENT_GLOB",
    "_load_frame",
    "_nothing_has_been_measured",
    "freeze_acquisition_frame",
    "freeze_protocol",
    "freeze_universe",
    "Workspace",
    "load_protocol",
    "latest_receipt",
    "stem_for",
    "STAGES",
)


def _verify_override_targets() -> None:
    missing = [name for name in _OVERRIDE_TARGETS if not hasattr(base, name)]
    if missing:
        raise RuntimeError(
            f"the V2R1 freezer no longer defines {missing}. An override that lands on "
            "nothing is not an override, and a V2R3R1 run would silently inherit "
            "another study's settings. Fix the adapter rather than the base: V2R1's "
            "and V2R2's tooling is spent-run evidence."
        )


_verify_override_targets()


@dataclass(frozen=True)
class V2R3R1Workspace(base.Workspace):
    """The base Workspace with the V2R3R1 protocol as its default.

    Rebinding `base.PROTOCOL` is not enough: a dataclass bakes its field defaults
    into the generated `__init__` when the class is created, so `base.Workspace()`
    would keep handing out an older protocol path however many module globals
    were reassigned.
    """

    protocol: Path = PROTOCOL


def workspace() -> Any:
    return V2R3R1Workspace()


def _load_frame() -> Any:
    sys.path.insert(0, str(NS / "acquisition"))
    try:
        import sources_v2r3r1
    except Exception as error:  # pragma: no cover -- the frame is a hard dependency
        raise FreezeRefused(f"cannot load the acquisition frame: {error}") from error
    return sources_v2r3r1


def _bindings() -> dict[str, Any]:
    return {
        "PROTOCOL": PROTOCOL,
        "FRAME_MODULE": FRAME_MODULE,
        "MEASUREMENT_GLOB": MEASUREMENT_GLOB,
        "_load_frame": _load_frame,
        "_nothing_has_been_measured": _nothing_has_been_measured,
        "Workspace": V2R3R1Workspace,
    }


@contextmanager
def _bound() -> Iterator[None]:
    """Hold the shared base pointed at V2R3R1 for the duration of one rung."""
    previous = {name: getattr(base, name) for name in _bindings()}
    for name, value in _bindings().items():
        setattr(base, name, value)
    try:
        _assert_bindings()
        yield
    finally:
        for name, value in previous.items():
            setattr(base, name, value)


def _assert_bindings() -> None:
    """The bindings actually took, right now.

    Not redundant with `_bound` setting them: it catches a base that has renamed
    one of these, in which case the `setattr` quietly creates a NEW attribute
    nothing reads and the rung runs against the base's own defaults while looking
    configured.
    """
    wrong = [
        f"base.{name} is {getattr(base, name, None)!r}"
        for name, value in _bindings().items()
        if getattr(base, name, None) is not value
    ]
    if wrong:
        raise FreezeRefused(
            "the shared base module did not take this adapter's bindings: "
            f"{wrong}. Proceeding would freeze against another study's settings and "
            "report success."
        )


def _nothing_has_been_measured(ws: Any) -> tuple[bool, list[str]]:
    """Is V2R3R1 still entirely upstream of any outcome-bearing data?

    THE CORPUS IS DELIBERATELY NOT A BLOCKER HERE. The parent's version of this
    check refused when acquired material existed, because a frame sealed after
    acquisition records rather than constrains. This chain acquires nothing and
    the material existing is its premise -- blocking on it would make rung 0
    unreachable and the guard would be measuring the wrong thing.
    """
    blocking: list[str] = []
    protocol = base.load_protocol(ws.protocol)
    for rung in ("universe", "scorer_acceptance", "exclusions", "measurement"):
        try:
            stem = base.stem_for(protocol, rung)
        except Exception as error:
            blocking.append(f"cannot read the stem for rung {rung!r}: {error}")
            continue
        if base.latest_receipt(stem, ws.receipts) is not None:
            blocking.append(f"rung {rung!r} has already frozen")
    return (not blocking), blocking


# ---------------------------------------------------------------------------
# wrapped rungs


#: stem key -> (writer, verifier). Named explicitly rather than derived from the
#: stem string: a getattr on a sliced name would keep working after a rename and
#: silently call the wrong verifier.
COMPANIONS: dict[str, tuple[Any, Any]] = {
    "frame_attestation": (att.attest_frame, att.verify_frame),
    "protocol_attestation": (att.attest_protocol, att.verify_protocol),
    "universe_attestation": (att.attest_universe, att.verify_universe),
}


def _companion(stem_key: str, ws: Any) -> dict[str, Any]:
    """Write the companion attestation for a rung, or verify the one that exists.

    A base rung is idempotent -- it returns ALREADY_FROZEN rather than writing a
    second receipt -- so its companion has to be too, and for the same reason.
    """
    writer, verifier = COMPANIONS[stem_key]
    protocol = base.load_protocol(ws.protocol)
    if base.latest_receipt(base.stem_for(protocol, stem_key), ws.receipts) is not None:
        return {"state": "ALREADY_ATTESTED", **verifier(ws)}
    return writer(ws)


def freeze_acquisition_frame(ws: Any | None = None) -> dict[str, Any]:
    """Rung 0, purpose-built for carry-forward, then its companion.

    NOT DELEGATED TO `base.freeze_acquisition_frame`, and that is a deliberate
    break from every other rung in this file. The base's rung 0 is a
    FRESH-ACQUISITION freeze: it requires `frame_digest()`, a `FAMILIES`
    traversal order, a `PRIMARY_TARGET` that strictly over-selects against the
    floor, and family quotas summing to it. None of those exist here, and the
    only way to satisfy them would be to invent an over-selection target for an
    acquisition that never happens -- a fabricated declaration written to satisfy
    a schema, which is the one thing this repository's rules forbid outright.

    Its emptiness guard would have been worse than useless: it checks
    `v2r1_corpus`, which is not this chain's corpus, so under this adapter it is
    a guard whose failure is impossible (INC-V2-036). The real precondition here
    is the opposite one -- the parent's corpus must be PRESENT -- and it is
    checked below.

    What IS reused is the receipt machinery: `write_receipt`, `latest_receipt`
    and `stem_for`, so the envelope, the run id derivation and the immutability
    refusal are the same ones every other receipt in this study was written by.
    And the body carries `frame_module_sha256`, which is the single field rung 1
    reads back through `require_frozen_frame`.
    """
    ws = ws or workspace()
    with _bound():
        if not CORPUS.exists() or not any(CORPUS.iterdir()):
            raise FreezeRefused(
                f"{base._rel(CORPUS, ws.root)} is empty. This chain inherits the "
                "parent's already-acquired material and fetches nothing, so an absent "
                "corpus is not something to acquire -- it is a missing premise."
            )

        protocol = base.load_protocol(ws.protocol)
        stem = base.stem_for(protocol, "acquisition_frame")
        frame = _load_frame()
        module_digest = base.sha_file(FRAME_MODULE)

        existing = base.latest_receipt(stem, ws.receipts)
        if existing is not None:
            if existing.get("frame_module_sha256") == module_digest:
                return {
                    "state": "ALREADY_FROZEN",
                    "receipt": existing["_receipt_path"],
                    "frame_module_sha256": module_digest,
                    "frame_attestation": _companion("frame_attestation", ws),
                }
            raise FreezeRefused(
                "the acquisition frame is already frozen at a different digest. A "
                "frozen frame is not amended in place.\n"
                f"  frozen:  {existing.get('frame_module_sha256')}\n"
                f"  current: {module_digest}"
            )

        #: Sufficiency lives in the protocol AND in the frame. They must agree,
        #: or one of them is decorative. Carried forward at the parent's values
        #: and never lowered.
        sufficiency = protocol.get("cohort_sufficiency") or {}
        if sufficiency.get("minimum_admitted_pairs") != frame.FLOOR:
            raise FreezeRefused(
                "the protocol's minimum_admitted_pairs and the frame's FLOOR disagree "
                f"({sufficiency.get('minimum_admitted_pairs')} vs {frame.FLOOR}). Two "
                "declarations of the same gate that differ means one of them is not "
                "the gate."
            )
        if sufficiency.get("minimum_families") != frame.FAMILIES_REQUIRED:
            raise FreezeRefused(
                "the protocol's minimum_families and the frame's FAMILIES_REQUIRED "
                f"disagree ({sufficiency.get('minimum_families')} vs "
                f"{frame.FAMILIES_REQUIRED})."
            )
        if sorted(sufficiency.get("target_families") or ()) != sorted(frame.BY_FAMILY):
            raise FreezeRefused(
                "the protocol's target_families and the frame's BY_FAMILY disagree "
                f"({sufficiency.get('target_families')} vs {sorted(frame.BY_FAMILY)})."
            )

        #: Proven BEFORE the receipt is written, so a failing carry-forward never
        #: leaves a frozen frame behind.
        disposition = att.prove_parent_disposition(ws)
        carried = cf.prove_exact_carry_forward(ws.receipts)

        body = {
            "rung": 0,
            "rung_name": "acquisition_frame",
            "protocol_id": protocol["protocol_id"],
            "parent_protocol_id": frame.PARENT_PROTOCOL_ID,
            "frame_module": base._rel(FRAME_MODULE, ws.root),
            "frame_module_sha256": module_digest,
            "frame_declaration": frame.frame_declaration(),
            "mode": frame.MODE,
            "sealed_before_acquisition": (
                "not applicable. This chain acquires nothing; the parent sealed the "
                "acquisition rules before its own fetch and that receipt is preserved."
            ),
            "parent_disposition": disposition,
            "carry_forward": carried,
            "why_rung_0_exists_here": (
                "rung 0 removes selection freedom before content can influence it. "
                "Under exact carry-forward that freedom is already zero by "
                "construction, so what this rung seals instead is that the inherited "
                "set was not widened, narrowed or reordered."
            ),
            "why_the_base_rung_is_not_used": (
                "the base rung 0 is a fresh-acquisition freeze requiring a traversal "
                "order, an over-selection target and quotas summing to it. Satisfying "
                "them here would mean inventing declarations for an acquisition that "
                "never happens."
            ),
        }
        return {
            "state": "FROZEN",
            "rung": 0,
            **base.write_receipt(stem, body, ws),
            "frame_attestation": _companion("frame_attestation", ws),
        }


def freeze_protocol(ws: Any | None = None) -> dict[str, Any]:
    """Rung 1, then its companion carrying consistency AND semantic equivalence."""
    ws = ws or workspace()
    with _bound():
        att.prove_contract_consistency()
        att.prove_semantic_equivalence()
        result = base.freeze_protocol(ws)
        result["protocol_attestation"] = _companion("protocol_attestation", ws)
        return result


def freeze_universe(ws: Any | None = None) -> dict[str, Any]:
    """Rung 3, then its companion proving spent-disjointness and exact equality."""
    ws = ws or workspace()
    with _bound():
        result = base.freeze_universe(ws)
        if (
            base.latest_receipt(
                base.stem_for(base.load_protocol(ws.protocol), "universe"), ws.receipts
            )
            is None
        ):  # pragma: no cover -- freeze_universe just wrote it
            raise FreezeRefused("the universe freeze reported success but wrote no receipt")
        result["universe_attestation"] = _companion("universe_attestation", ws)
        return result


# ---------------------------------------------------------------------------
# re-sealing the pre-scorer ladder
#
# WHY THIS EXISTS, recorded rather than smoothed over. Rungs 0 and 0a were frozen
# while `v2r3r1_carry_forward.py` still compared the parent's candidate manifest
# to its frozen universe POSITIONALLY. The two are in different orders by
# construction -- the manifest is in acquisition order, rung 3 sorts its output --
# so the comparison reported 300 mismatches and no missing lineages. Fixing it
# changed two files the frame attestation pins, and the attestation correctly
# went red.
#
# That is the parent chain's failure arriving one rung earlier, and the lesson is
# the same: FREEZING BEFORE THE CODE HAS SETTLED buys nothing and costs a rung.
# The difference is where the boundary falls. The protocol's `no_post_freeze_-
# change` rule bites AFTER RUNG 4; below it the base ladder has always had a
# declared supersede path, gated on nothing having been scored, and the base's
# own docstrings record two previous uses of it.
#
# So this re-seals rungs 0, 1 and 3 together, with fresh companion attestations,
# and refuses outright once rung 4 or 5 has frozen or any measurement exists. It
# is NOT an amend path for a frozen instrument, and it cannot become one: after
# rung 4 there is no route to it.


def _may_reseal(ws: Any) -> tuple[bool, list[str]]:
    """The re-seal gate: measurement-free AND below the protocol's own boundary.

    Deliberately NOT `_nothing_has_been_measured`, which also blocks on rung 3
    having frozen. That condition is the right one for a FRESH-ACQUISITION study,
    where a changed frame could reshape what gets fetched. Here nothing is
    fetched: the cohort is fixed by the parent's frozen receipt and proven equal
    to it row by row, so a frame edit cannot reach the material. Blocking on it
    would make the declared repair path unreachable while leaving the harm it
    guards against impossible either way.

    What it does block on is what actually matters, and it is stricter than the
    base's: no measurement receipt, and rung 4 not frozen -- which is exactly
    where `freeze.no_post_freeze_change` draws its line.
    """
    blocking: list[str] = []
    protocol = base.load_protocol(ws.protocol)
    for rung in ("scorer_acceptance", "exclusions", "measurement"):
        stem = base.stem_for(protocol, rung)
        if base.latest_receipt(stem, ws.receipts) is not None:
            blocking.append(
                f"rung {rung!r} has frozen; after rung 4 there is no amend path and no force flag"
            )
    if sorted(ws.receipts.glob(MEASUREMENT_GLOB)):
        blocking.append("a V2R3R1 measurement receipt exists")
    return (not blocking), blocking


def _fresh_companion(stem_key: str, ws: Any) -> dict[str, Any]:
    """Write a NEW companion attestation, never reuse the existing one.

    `_companion` is idempotent, which is right for a rung that returns
    ALREADY_FROZEN. It is wrong here: a re-sealed rung whose companion was merely
    re-verified would be attested by a proof made about the base receipt it
    replaced.
    """
    writer, _verifier = COMPANIONS[stem_key]
    return writer(ws)


def reseal_pre_scorer_chain(ws: Any | None = None) -> dict[str, Any]:
    """Re-seal rungs 0, 1 and 3 with fresh companions. Refuses after rung 4."""
    ws = ws or workspace()
    with _bound():
        clean, blocking = _may_reseal(ws)
        if not clean:
            raise FreezeRefused(
                "the pre-scorer ladder may not be re-sealed:\n  " + "\n  ".join(blocking)
            )

        protocol = base.load_protocol(ws.protocol)
        voided = {
            key: (
                base._rel(runs[-1], ws.root)
                if (runs := base.runs_of(base.stem_for(protocol, key), ws.receipts))
                else None
            )
            for key in (
                "acquisition_frame",
                "frame_attestation",
                "protocol",
                "protocol_attestation",
                "universe",
                "universe_attestation",
            )
        }

        #: The base's rung-1 and rung-3 supersede paths consult
        #: `_nothing_has_been_measured`. Bound to the re-seal gate for the
        #: duration of this operation only, so the ladder's own refusal logic
        #: still runs -- it is the CONDITION that is supplied here, not skipped.
        previous = base._nothing_has_been_measured
        base._nothing_has_been_measured = _may_reseal
        try:
            att.prove_parent_disposition(ws)
            cf.prove_exact_carry_forward(ws.receipts)
            att.prove_semantic_equivalence()

            frame_receipt = _reseal_frame(ws, protocol)
            frame_attestation = _fresh_companion("frame_attestation", ws)
            protocol_receipt = base.supersede_protocol(ws)
            protocol_attestation = _fresh_companion("protocol_attestation", ws)
            universe_receipt = base.supersede_universe(ws)
            universe_attestation = _fresh_companion("universe_attestation", ws)
        finally:
            base._nothing_has_been_measured = previous

    return {
        "state": "RESEALED",
        "voided": voided,
        "why": (
            "rungs 0 and 0a were frozen while the carry-forward comparison still "
            "matched the parent's candidate manifest to its frozen universe "
            "positionally. The two are in different orders by construction; fixing "
            "it changed two files the frame attestation pins."
        ),
        "boundary": (
            "reachable only while no measurement exists and rung 4 has not frozen, "
            "which is exactly where freeze.no_post_freeze_change draws its line."
        ),
        "frame": frame_receipt,
        "frame_attestation": frame_attestation,
        "protocol": protocol_receipt,
        "protocol_attestation": protocol_attestation,
        "universe": universe_receipt,
        "universe_attestation": universe_attestation,
    }


def _reseal_frame(ws: Any, protocol: dict[str, Any]) -> dict[str, Any]:
    """Rung 0 again, naming what it voids. Never deletes or rewrites the old one."""
    stem = base.stem_for(protocol, "acquisition_frame")
    prior = base.latest_receipt(stem, ws.receipts)
    if prior is None:
        raise FreezeRefused("there is no frozen frame to supersede; use the `frame` rung")
    frame = _load_frame()
    module_digest = base.sha_file(FRAME_MODULE)
    pins = att.att._pins(att.FRAME_PINS)
    if prior.get("frame_module_sha256") == module_digest and prior.get("pinned_files") == pins:
        raise FreezeRefused(
            "the frame module and every file its attestation pins are identical to "
            "what is frozen. There is nothing to supersede, and a second receipt for "
            "the same content makes the chain longer without making it truer."
        )
    body = {
        "rung": 0,
        "rung_name": "acquisition_frame",
        "protocol_id": protocol["protocol_id"],
        "parent_protocol_id": frame.PARENT_PROTOCOL_ID,
        "frame_module": base._rel(FRAME_MODULE, ws.root),
        "frame_module_sha256": module_digest,
        "frame_declaration": frame.frame_declaration(),
        "pinned_files": pins,
        "mode": frame.MODE,
        "supersedes": prior["_receipt_path"],
        "supersedes_run_id": prior["provenance"]["run_id"],
        "why_superseded": (
            "the carry-forward comparison it was frozen against matched the parent's "
            "candidate manifest to its frozen universe positionally, and the two are "
            "in different orders by construction. The superseded receipt is preserved."
        ),
        "parent_disposition": att.prove_parent_disposition(ws),
        "carry_forward": cf.prove_exact_carry_forward(ws.receipts),
    }
    return {"state": "RESEALED", "rung": 0, **base.write_receipt(stem, body, ws)}


# ---------------------------------------------------------------------------
# the V2R3R1 execution gate


def require_v2r3r1_execution_preconditions(ws: Any | None = None) -> dict[str, Any]:
    """Everything the base gate checks, plus every V2R3R1 attestation, recomputed."""
    ws = ws or workspace()
    with _bound():
        ready = base.require_execution_preconditions(ws)

        #: The base gate REPORTS prior measurements. A closure runs exactly once,
        #: so here it REFUSES on them -- a report is not a refusal, and "already
        #: measured" printed beside READY is a state this study must not reach.
        already = ready.get("already_measured") or []
        if already:
            raise FreezeRefused(
                f"a V2R3R1 measurement already exists: {already}. A closure runs "
                "EXACTLY ONCE. Its corpus is spent and no rescore is permitted."
            )

        attestations = att.verify_all(ws)

    return {
        **ready,
        "gate": "require_v2r3r1_execution_preconditions",
        "companion_attestations": {
            name: {"receipt": entry["attestation"], "recomputed": True}
            for name, entry in attestations.items()
        },
        "carry_forward": attestations["frame_attestation"]["recomputed"],
        "contract_consistency": attestations["protocol_attestation"]["recomputed"],
        "semantic_equivalence": attestations["protocol_attestation"]["semantic_equivalence"],
        "spent_disjointness": attestations["universe_attestation"]["recomputed"],
        "exact_set_equality": attestations["universe_attestation"]["exact_set_equality"],
    }


# ---------------------------------------------------------------------------
# stages


def _wrap(name: str, stage: Any) -> Any:
    def bound_stage(*args: Any, **kwargs: Any) -> Any:
        with _bound():
            return stage(*args, **kwargs)

    bound_stage.__name__ = f"bound_{name}"
    bound_stage.__doc__ = f"`{name}` from the shared base, run with this adapter's bindings."
    return bound_stage


STAGES: dict[str, Any] = {name: _wrap(name, stage) for name, stage in base.STAGES.items()}
STAGES["frame"] = freeze_acquisition_frame
STAGES["protocol"] = freeze_protocol
STAGES["universe"] = freeze_universe
#: The inherited `gate` points at the base precondition check, which knows
#: nothing about this chain's attestations. Overridden by name so the chain
#: cannot report READY without them.
STAGES["gate"] = require_v2r3r1_execution_preconditions
#: The base's supersede rungs are replaced by ONE command that re-seals the whole
#: pre-scorer ladder together. Offering them individually would let rung 0 be
#: superseded while rungs 1 and 3 still linked to the receipt it replaced.
for _name in ("supersede-frame", "supersede-protocol", "supersede-universe"):
    STAGES.pop(_name, None)
STAGES["reseal"] = reseal_pre_scorer_chain


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=tuple(STAGES))
    args = parser.parse_args(argv)
    try:
        result = STAGES[args.stage]()
    except FreezeRefused as error:
        print(json.dumps({"state": "REFUSED", "rung": args.stage, "why": str(error)}, indent=1))
        return 4
    print(json.dumps(result, indent=1, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
