"""The freeze ladder for IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R4.

THIS IS AN ADAPTER, NOT A FORK, for the reason V2R2's and V2R3's were: the V2R1
freezer is ~1,900 lines of receipt envelopes, digest recomputation, chain-link
verification and refusal logic that must behave IDENTICALLY here, and copying it
would create a second implementation of the same machinery, free to drift.

IT ADAPTS THE SAME BASE V2R2 AND V2R3 ADAPTED, not their adapters. Chaining
adapter onto adapter would make V2R4's behaviour depend on V2R3's overrides
still being correct for a study they were not written for, and V2R3's tooling is
frozen evidence that must not be edited.

THAT SHARED BASE IS A HAZARD, and it is SCOPED rather than merely detected.
Every adapter over this base rebinds names on ONE imported module object, so a
permanent rebind at import time makes correctness depend on which adapter
imported last. That is not a theoretical worry twice over: it made 21 of 24 V2R2
gate tests assert things about V2R1 and pass, and the first version of the V2R3
adapter rebound at import and turned eight of V2R2's adapter tests red in a
single pytest process by stealing the base out from under them. `_bound()`
applies the bindings for ONE RUNG and restores them afterwards -- on the error
path too -- so importing this module changes nothing for anybody else.

FOUR COMPANIONS, NOT THREE. V2R3 sealed three; V2R4 seals a fourth on the
scorer rung, and the reason it exists is INC-V2-067:

  * rung 0 proves ROOT DISJOINTNESS through `root_identity` before any fetch,
    AND SEPARATION FROM SFI3_ROOT_RESERVATION_V1 on container identity. The
    second half replaced an INVARIANT_8 population that could not exist: SFI3's
    cohort is downstream of this study's PASS, so requiring disjointness from
    SFI3 MATERIAL made a circular gate whose only exits were opening SFI3 early
    or passing vacuously over an empty population (INC-V2-036).
  * rung 1 refuses unless `v2r3_state_table.check_contract()` returns
    SATISFIABLE, the protocol's declared rows are the executable rows, AND the
    scientific core crossed from V2R3R1 with every remaining difference
    predeclared. It does NOT claim the projection is IDENTICAL -- that claim was
    false, and the checker that would have to prove it refuses on this pair.
  * rung 3 proves disjointness from every spent universe independently of the
    enumerator's filter.
  * rung 4 proves DECLARED == GRADED == RECEIPT, with the graded set obtained by
    EXECUTING the grading function. V2R3R1 froze a scorer that graded one
    invariant against a pass rule naming eight; nothing between the two ever
    compared them, and 300 pairs were spent establishing one answer.
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
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import freeze_migration_closure_v2r1 as base  # noqa: E402
import v2r4_attestation as att  # noqa: E402
import v2r4_grading as grading  # noqa: E402

FreezeRefused = base.FreezeRefused

PROTOCOL = NS / "protocols" / "IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R4.yaml"
FRAME_MODULE = NS / "acquisition" / "sources_v2r4.py"
CORPUS = NS / "artifacts" / "development" / "v2r4_corpus"
MEASUREMENT_GLOB = "identity-change-migration-closure-v2r4--*.json"

CONSISTENCY_TESTS = "tests/test_v2r3_contract_consistency.py"

_OVERRIDE_TARGETS = (
    "PROTOCOL",
    "FRAME_MODULE",
    "MEASUREMENT_GLOB",
    "_load_frame",
    "_nothing_has_been_measured",
    "freeze_acquisition_frame",
    "freeze_protocol",
    "freeze_universe",
    "freeze_scorer",
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
            "the V2R1 freezer no longer defines "
            f"{missing}. An override that lands on nothing is not an override, and "
            "a V2R4 run would silently inherit another study's settings. Fix the "
            "adapter rather than the base: the predecessors' tooling is frozen "
            "evidence."
        )


_verify_override_targets()


@dataclass(frozen=True)
class V2R4Workspace(base.Workspace):
    """The base Workspace with the V2R4 protocol as its default.

    Rebinding `base.PROTOCOL` is NOT enough: a dataclass bakes its field defaults
    into the generated `__init__` when the class is created, so `base.Workspace()`
    would keep handing out the older protocol path however many module globals
    were reassigned.
    """

    protocol: Path = PROTOCOL


def workspace() -> Any:
    return V2R4Workspace()


def _load_frame() -> Any:
    sys.path.insert(0, str(NS / "acquisition"))
    try:
        import sources_v2r4
    except Exception as error:  # pragma: no cover -- the frame is a hard dependency
        raise FreezeRefused(f"cannot load the acquisition frame: {error}") from error
    return sources_v2r4


#: What this adapter must have in force on the shared base while a rung runs.
#: One table, consulted by the applier and by the check, so the two cannot list
#: different names.
def _bindings() -> dict[str, Any]:
    return {
        "PROTOCOL": PROTOCOL,
        "FRAME_MODULE": FRAME_MODULE,
        "MEASUREMENT_GLOB": MEASUREMENT_GLOB,
        "_load_frame": _load_frame,
        "_nothing_has_been_measured": _nothing_has_been_measured,
        "Workspace": V2R4Workspace,
    }


@contextmanager
def _bound() -> Iterator[None]:
    """Hold the shared base pointed at V2R4 for the duration of one rung.

    SCOPED, NOT PERMANENT. The bindings are restored on the way out even when the
    rung raises, so a refused freeze does not leave the base pointed somewhere
    another study's code would then read.
    """
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
    one of these out from under the adapter, in which case the `setattr` above
    quietly creates a NEW attribute nothing reads and the rung would run against
    the base's own defaults while looking configured.
    """
    wrong = [
        f"base.{name} is {getattr(base, name, None)!r}"
        for name, value in _bindings().items()
        if getattr(base, name, None) is not value
    ]
    if wrong:
        raise FreezeRefused(
            "the shared base module did not take this adapter's bindings: "
            f"{wrong}. Proceeding would freeze against another study's settings "
            "and report success."
        )


def _nothing_has_been_measured(ws: Any) -> tuple[bool, list[str]]:
    """Is V2R4 still entirely upstream of any outcome-bearing data?"""
    blocking: list[str] = []

    if CORPUS.exists() and any(CORPUS.iterdir()):
        blocking.append(f"acquired material exists at {base._rel(CORPUS, ws.root)}")

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
    "domain_attestation": (att.attest_domain, att.verify_domain),
}


def _require_every_declared_companion_is_wired(protocol: dict[str, Any]) -> set[str]:
    """The protocol's attestation stems and this table are the SAME SET.

    A stem the protocol declares and this table omits is a rung that would never
    be attested while the protocol says it is; a stem here that the protocol does
    not declare would refuse at write time with a confusing error. Set equality
    on full identifiers, both directions -- the same shape as the invariant
    domain check, for the same reason.

    TAKES THE PROTOCOL RATHER THAN READING IT. An earlier version read the YAML
    from disk AT IMPORT, which made every importer inherit whatever was on disk
    at that moment and put an active-protocol global behind an `import`
    statement. The check belongs at the rung, where the protocol it is checking
    is the protocol the rung is about.
    """
    declared = {key for key in protocol["freeze"]["stems"] if key.endswith("_attestation")}
    wired = set(COMPANIONS)
    if declared != wired:
        raise FreezeRefused(
            "the protocol's attestation rungs and the freezer's companion table "
            f"disagree.\n  declared not wired: {sorted(declared - wired)}\n"
            f"  wired not declared: {sorted(wired - declared)}\n"
            "A rung the protocol names and the freezer never writes is a proof "
            "that exists only in prose."
        )
    return declared


def require_protocol_binding(ws: Any | None = None) -> dict[str, Any]:
    """The protocol on disk is the one rung 1 froze, and it wires these rungs.

    TWO CHECKS, ONE PLACE, because they answer the same question from opposite
    ends: `PROTOCOL` is a PATH, and a path is a filename rather than a binding
    until something compares its digest to what was sealed. The base's
    `require_frozen_protocol` does that comparison -- and also verifies the LINK
    to the frame rung, so a protocol sealed against a superseded frame refuses
    rather than passing on its own intact digest.

    Called from the gate and from each companion write. NOT at import: an
    import-time protocol read makes correctness depend on what was on disk when
    somebody happened to import this module.
    """
    ws = ws or workspace()
    with _bound():
        receipt = base.require_frozen_protocol(ws)
        protocol = base.load_protocol(ws.protocol)
        attested = _require_every_declared_companion_is_wired(protocol)
    return {
        "held": True,
        "protocol_id": protocol["protocol_id"],
        "protocol_sha256": receipt["protocol_sha256"],
        "attestation_rungs": sorted(attested),
        "checked": (
            "the protocol file still hashes to what rung 1 sealed, its link to the "
            "frame rung in force is intact, and every attestation stem it declares "
            "has a writer and a verifier wired here"
        ),
    }


def _companion(stem_key: str, ws: Any) -> dict[str, Any]:
    """Write the companion attestation for a rung, or verify the one that exists.

    A base rung is idempotent -- it returns ALREADY_FROZEN rather than writing a
    second receipt -- so its companion has to be too, and for the same reason:
    re-running a rung must not silently produce a second, differently-attested
    version of the same freeze.
    """
    writer, verifier = COMPANIONS[stem_key]
    protocol = base.load_protocol(ws.protocol)
    #: The wiring check runs HERE, against the protocol this rung is about,
    #: rather than at import against whatever was on disk when somebody imported
    #: this module. Rung 0 has no frozen protocol to bind yet, so the digest half
    #: belongs at the gate; the set equality does not depend on it.
    _require_every_declared_companion_is_wired(protocol)
    if base.latest_receipt(base.stem_for(protocol, stem_key), ws.receipts) is not None:
        return {"state": "ALREADY_ATTESTED", **verifier(ws)}
    return writer(ws)


def freeze_acquisition_frame(ws: Any | None = None) -> dict[str, Any]:
    """Rung 0, then its companion carrying root disjointness AND SFI3 separation.

    Both proofs are computed BEFORE the base rung so a failing proof never leaves
    a frozen frame behind, and sealed AFTER it because the attestation binds the
    receipt the base writes.
    """
    ws = ws or workspace()
    with _bound():
        if CORPUS.exists() and any(CORPUS.iterdir()):
            raise FreezeRefused(
                f"{base._rel(CORPUS, ws.root)} already holds acquired material. The "
                "frame is sealed BEFORE acquisition; sealing it afterwards would "
                "record what was done rather than constrain what may be done."
            )
        att.prove_root_disjointness()
        att.prove_sfi3_separation()
        result = base.freeze_acquisition_frame(ws)
        result["frame_attestation"] = _companion("frame_attestation", ws)
        return result


def freeze_protocol(ws: Any | None = None) -> dict[str, Any]:
    """Rung 1, then its companion carrying consistency AND the allowed delta.

    Refuses before the base rung unless the contract is satisfiable, the
    protocol's declared rows are the executable rows, and the scientific core
    crossed from V2R3R1 with every remaining difference predeclared.
    """
    ws = ws or workspace()
    with _bound():
        att.prove_contract_consistency()
        att.prove_allowed_delta()
        result = base.freeze_protocol(ws)
        result["protocol_attestation"] = _companion("protocol_attestation", ws)
        return result


def freeze_universe(ws: Any | None = None) -> dict[str, Any]:
    """Rung 3, then its companion proving disjointness from every spent cohort.

    The enumerator already subtracts them, and this does not trust it. A filter
    and a proof written as one piece of code agree by construction and prove
    nothing; written separately, a silent failure in either is visible.
    """
    ws = ws or workspace()
    with _bound():
        protocol = base.load_protocol(ws.protocol)
        stem = base.stem_for(protocol, "universe")
        #: THE BASE RUNG IS NOT IDEMPOTENT. `freeze_acquisition_frame` and
        #: `freeze_protocol` both return ALREADY_FROZEN when their receipt
        #: exists; `base.freeze_universe` rebuilds and writes UNCONDITIONALLY.
        #: Running rung 3 twice therefore produced a second universe receipt --
        #: content-identical, new run id -- which became the rung "in force" and
        #: orphaned the companion attestation bound to the first. Nothing drifted
        #: scientifically, but a chain in which the sealed proof names a receipt
        #: that is no longer authoritative is a broken chain, and it broke by
        #: being run again rather than by anything changing. INC-V2-078.
        #:
        #: The guard is HERE and not in the base: the base is spent-run evidence
        #: for three closed studies and is not edited.
        already = base.latest_receipt(stem, ws.receipts)
        if already is not None:
            return {
                "state": "ALREADY_FROZEN",
                "rung": 3,
                "receipt": already["_receipt_path"],
                "run_id": already["provenance"]["run_id"],
                "pair_count": already.get("pair_count"),
                "universe_sha256": already.get("universe_sha256"),
                "why_not_rewritten": (
                    "rung 3 is frozen. Re-deriving it would write a second receipt "
                    "under a new run id, silently move which one is in force, and "
                    "orphan the companion attestation bound to the first. Use "
                    "`supersede-universe` if the universe genuinely has to change."
                ),
                "universe_attestation": _companion("universe_attestation", ws),
            }
        result = base.freeze_universe(ws)
        if base.latest_receipt(stem, ws.receipts) is None:  # pragma: no cover
            raise FreezeRefused("the universe freeze reported success but wrote no receipt")
        result["universe_attestation"] = _companion("universe_attestation", ws)
        return result


def freeze_scorer_acceptance(ws: Any | None = None) -> dict[str, Any]:
    """Rung 4, then its companion proving DECLARED == GRADED == RECEIPT.

    The domain equality is computed BEFORE the base rung. A scorer frozen against
    an acceptance domain it does not actually grade is exactly what V2R3R1 froze,
    and the freeze is the last moment at which that costs nothing.
    """
    ws = ws or workspace()
    with _bound():
        att.prove_invariant_domain()
        result = base.freeze_scorer(ws)
        result["domain_attestation"] = _companion("domain_attestation", ws)
        return result


# ---------------------------------------------------------------------------
# the V2R4 execution gate
#
# The base gate verifies protocol -> universe -> scorer -> exclusions and knows
# nothing about the four V2R4 proofs. Inheriting it would let the chain report
# READY with no immutable receipt binding them, which is the same false-
# provenance seam one level up. THE V2R4 SCORER CALLS THIS AND NEVER THE BASE.


def require_v2r4_execution_preconditions(ws: Any | None = None) -> dict[str, Any]:
    """Everything the base gate checks, plus the four attestations, recomputed."""
    ws = ws or workspace()
    #: Before anything else: the protocol on disk is the one rung 1 sealed, its
    #: link to the frame in force is intact, and every attestation rung it
    #: declares is wired here. `PROTOCOL` is a PATH, and a path is a filename
    #: rather than a binding until its digest is compared to what was frozen.
    binding = require_protocol_binding(ws)
    with _bound():
        ready = base.require_execution_preconditions(ws)

        #: The base gate REPORTS prior measurements. A closure runs exactly once,
        #: so here it REFUSES on them -- a report is not a refusal, and "already
        #: measured" printed beside READY is a state this study must not be able
        #: to reach.
        already = ready.get("already_measured") or []
        if already:
            raise FreezeRefused(
                f"a V2R4 measurement already exists: {already}. A closure runs "
                "EXACTLY ONCE. Its corpus is spent and no rescore is permitted."
            )

        attestations = att.verify_all(ws)

        #: Recomputed at the gate as well as at rung 4, because the gate is the
        #: last thing that runs before the scorer and the two are separated by
        #: rung 5. A domain that held at the freeze and does not hold now would
        #: otherwise be discovered by reading the result.
        domain = grading.require_domain()
        exclusions = grading.require_exclusion_domain()

    return {
        **ready,
        "gate": "require_v2r4_execution_preconditions",
        "protocol_binding": binding,
        "companion_attestations": {
            name: {"receipt": entry["attestation"], "recomputed": True}
            for name, entry in attestations.items()
        },
        "root_disjointness": attestations["frame_attestation"]["recomputed"]["root_disjointness"],
        "sfi3_separation": attestations["frame_attestation"]["recomputed"]["sfi3_separation"],
        "contract_consistency": attestations["protocol_attestation"]["recomputed"][
            "contract_consistency"
        ],
        "allowed_delta": attestations["protocol_attestation"]["recomputed"]["allowed_delta"],
        "spent_disjointness": attestations["universe_attestation"]["recomputed"],
        "invariant_domain": domain,
        "exclusion_domain": exclusions,
    }


# ---------------------------------------------------------------------------
# apply the overrides to the imported module, then expose the base commands


#: NOTHING IS REBOUND AT IMPORT. `_bound()` applies these for the duration of
#: one rung and restores them afterwards, so importing this module cannot change
#: how another study's adapter behaves in the same process.


#: `STAGES` in the base module captured direct references when it was defined,
#: so rebinding a function name there does not reach it. The V2R4 table is built
#: from it and the wrapped rungs replace their entries by name.
#:
#: EVERY inherited stage is wrapped, not just the ones with V2R4-specific
#: behaviour. An inherited stage called raw reads the base's OWN defaults, and
#: the failure is silent in the direction that matters: `scorer` once refused
#: with "rung 3 is already frozen" because it had resolved V2R1's protocol, found
#: V2R1's scorer stem, and found V2R1's receipt. Nothing about that refusal said
#: it was talking about a different study.
def _wrap(name: str, stage: Any) -> Any:
    def bound_stage(*args: Any, **kwargs: Any) -> Any:
        with _bound():
            return stage(*args, **kwargs)

    bound_stage.__name__ = f"bound_{name}"
    bound_stage.__doc__ = (
        f"`{name}` from the shared base, run with this adapter's bindings in force."
    )
    return bound_stage


def supersede_universe_attestation(ws: Any | None = None) -> dict[str, Any]:
    """Re-seal rung 3's companion so its sealed proof covers every spent cohort.

    Not a rung. A repair path, guarded like the base `supersede_*` family: it
    refuses the moment a V2R4 outcome has been read, and it refuses a re-seal
    that would not widen what the attestation proves. See
    `v2r4_attestation.supersede_universe_attestation` for why it was needed.
    """
    ws = ws or workspace()
    with _bound():
        return att.supersede_universe_attestation(ws)


STAGES: dict[str, Any] = {name: _wrap(name, stage) for name, stage in base.STAGES.items()}
#: The five with V2R4-specific behaviour replace their entries outright; each
#: already enters `_bound()` itself.
STAGES["frame"] = freeze_acquisition_frame
STAGES["protocol"] = freeze_protocol
STAGES["universe"] = freeze_universe
STAGES["scorer"] = freeze_scorer_acceptance
#: The inherited `gate` points at the base precondition check, which knows
#: nothing about the four V2R4 proofs. Overridden by name so a chain cannot
#: report READY without them.
STAGES["gate"] = require_v2r4_execution_preconditions
#: A repair path, not a rung. Named in the table so it is reachable from the
#: CLI and visible in `--help`, rather than being a function only a human who
#: had read the module knew to import.
STAGES["supersede-universe-attestation"] = supersede_universe_attestation


def _require_every_overridden_stage_exists() -> None:
    """Each name replaced above was a real stage before it was replaced.

    A typo would ADD a stage nobody calls while leaving the inherited one in
    place, and the ladder would run the base's version while this table looked
    configured.
    """
    replaced = ("frame", "protocol", "universe", "scorer", "gate")
    missing = [name for name in replaced if name not in base.STAGES]
    if missing:
        raise RuntimeError(
            f"these stages are overridden here but do not exist in the base: "
            f"{missing}. An override that adds a stage nobody calls leaves the "
            "inherited one running."
        )
    #: Additions are legitimate, but only DECLARED ones. Without this half the
    #: check above passes for a misspelled override -- the typo simply becomes an
    #: addition, and the inherited rung keeps running unnoticed. Anything in this
    #: table that is neither inherited nor named here is that typo.
    added = ("supersede-universe-attestation",)
    stray = sorted(set(STAGES) - set(base.STAGES) - set(added))
    if stray:
        raise RuntimeError(
            f"these stage names exist only in the V2R4 table and are not declared "
            f"additions: {stray}. A misspelled override reaches nothing and leaves "
            "the base rung running under the name it was meant to replace."
        )


_require_every_overridden_stage_exists()


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
