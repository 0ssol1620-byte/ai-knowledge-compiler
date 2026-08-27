"""The freeze ladder for IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R3.

THIS IS AN ADAPTER, NOT A FORK, for the reason V2R2's was: the V2R1 freezer is
~1,900 lines of receipt envelopes, digest recomputation, chain-link verification
and refusal logic that must behave IDENTICALLY here, and copying it would create
a second implementation of the same machinery, free to drift.

IT ADAPTS THE SAME BASE V2R2 ADAPTED, not V2R2's adapter. Chaining adapter onto
adapter would make V2R3's behaviour depend on V2R2's overrides still being
correct for a study they were not written for, and V2R2's tooling is spent-run
evidence that must not be edited.

THAT SHARED BASE IS A HAZARD, and it is SCOPED rather than merely detected.
Every adapter over this base rebinds names on ONE imported module object, so a
permanent rebind at import time makes correctness depend on which adapter
imported last. That is not a theoretical worry twice over: it made 21 of 24 V2R2
gate tests assert things about V2R1 and pass, and the first version of THIS file
rebound at import and turned eight of V2R2's adapter tests red in a single pytest
process by stealing the base out from under them.

Detecting the collision was the first attempt and it was the wrong repair. A
refusal telling the operator to re-import in a different order is a correct
diagnosis of a design nobody should have to remember. `_bound()` applies these
bindings for the duration of ONE RUNG and restores them afterwards -- on the
error path too -- so importing this module changes nothing for anybody else.

THE OVERRIDES, named rather than performed silently:

    PROTOCOL          the V2R3 yaml, carried on every Workspace this module makes
    FRAME_MODULE      acquisition/sources_v2r3.py
    _load_frame       imports sources_v2r3
    MEASUREMENT_GLOB  the V2R3 measurement receipt name
    _nothing_has_been_measured
                      same two conditions, over the V2R3 corpus directory
    freeze_acquisition_frame
                      wrapped: real corpus path, plus the root-normalisation proof
    freeze_protocol   wrapped: the contract-consistency gate must PASS first
    freeze_universe   wrapped: disjointness from V2R1's 285 AND V2R2's 270

WHAT IS NEW RELATIVE TO V2R2'S LADDER, and why each is at the rung it is at:

  * rung 0 proves ROOT DISJOINTNESS through `root_identity` before any fetch.
    V2R2 declared 7 CFR 273 as a fresh root when SFI1 had spent its sections and
    VBC1 named it, because each sources module encodes roots differently and the
    scan matched one shape. A reader that BLOCKS on an uninterpretable shape is
    the repair; running it at rung 0 is what makes it a constraint rather than a
    post-mortem.
  * rung 1 refuses unless `v2r3_state_table.check_contract()` returns SATISFIABLE
    and the protocol's declared rows are the executable rows. V2R2's protocol
    froze a contract that required and forbade the same record, and nothing
    between the prose and the code ever compared them.
  * rung 3 proves disjointness from BOTH spent universes independently of the
    enumerator's filter.
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
import v2r3_attestation as att  # noqa: E402

FreezeRefused = base.FreezeRefused

PROTOCOL = NS / "protocols" / "IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R3.yaml"
FRAME_MODULE = NS / "acquisition" / "sources_v2r3.py"
CORPUS = NS / "artifacts" / "development" / "v2r3_corpus"
MEASUREMENT_GLOB = "identity-change-migration-closure-v2r3--*.json"

#: The two spent universes, read for LINEAGE IDS ONLY -- no verdict, no count,
#: no violated case. Both runs stand; both were adjudicated invalid instruments;
#: neither adjudication un-spends the material.
SPENT_UNIVERSE_STEMS = (
    ("v2r1", "identity-change-migration-closure-v2r1-universe", 285),
    ("v2r2", "identity-change-migration-closure-v2r2-universe", 270),
)

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
            "a V2R3 run would silently inherit another study's settings. Fix the "
            "adapter rather than the base: V2R1's and V2R2's tooling is spent-run "
            "evidence."
        )


_verify_override_targets()


@dataclass(frozen=True)
class V2R3Workspace(base.Workspace):
    """The base Workspace with the V2R3 protocol as its default.

    Rebinding `base.PROTOCOL` is NOT enough: a dataclass bakes its field
    defaults into the generated `__init__` when the class is created, so
    `base.Workspace()` would keep handing out the older protocol path however
    many module globals were reassigned.
    """

    protocol: Path = PROTOCOL


def workspace() -> Any:
    return V2R3Workspace()


def _load_frame() -> Any:
    sys.path.insert(0, str(NS / "acquisition"))
    try:
        import sources_v2r3
    except Exception as error:  # pragma: no cover -- the frame is a hard dependency
        raise FreezeRefused(f"cannot load the acquisition frame: {error}") from error
    return sources_v2r3


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
        "Workspace": V2R3Workspace,
    }


@contextmanager
def _bound() -> Iterator[None]:
    """Hold the shared base pointed at V2R3 for the duration of one rung.

    SCOPED, NOT PERMANENT, and that is the whole design. Every adapter over this
    base rebinds the same module object, so a permanent rebind at import time
    makes correctness depend on WHICH ADAPTER IMPORTED LAST -- which is not a
    theoretical worry twice over. It made 21 of 24 V2R2 gate tests assert things
    about V2R1 and pass, and when this adapter first rebound at import it turned
    eight of V2R2's adapter tests red in a single pytest process by stealing the
    base out from under them.

    Detecting the collision was the first attempt and it was the wrong repair: a
    refusal that tells the operator to re-import in a different order is a
    correct diagnosis of a design nobody should have to remember. Applying the
    bindings for the rung and restoring them afterwards removes the ordering
    question instead of reporting it.

    The bindings are restored on the way out even when the rung raises, so a
    refused freeze does not leave the base pointed somewhere another study's code
    would then read.
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

    Cheap, and not redundant with `_bound` setting them: it catches a base that
    has renamed one of these out from under the adapter, in which case the
    `setattr` above quietly creates a NEW attribute nothing reads and the rung
    would run against the base's own defaults while looking configured.
    `_verify_override_targets` catches that at import for names that vanish
    entirely; this catches the case where the value does not stick.
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
    """Is V2R3 still entirely upstream of any outcome-bearing data?"""
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
    if base.latest_receipt(base.stem_for(protocol, stem_key), ws.receipts) is not None:
        return {"state": "ALREADY_ATTESTED", **verifier(ws)}
    return writer(ws)


def freeze_acquisition_frame(ws: Any | None = None) -> dict[str, Any]:
    """Rung 0, then its immutable companion carrying the root-disjointness proof.

    The proof is computed BEFORE the base rung so a failing proof never leaves a
    frozen frame behind, and sealed AFTER it because the attestation binds the
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
        result = base.freeze_acquisition_frame(ws)
        result["frame_attestation"] = _companion("frame_attestation", ws)
        return result


def freeze_protocol(ws: Any | None = None) -> dict[str, Any]:
    """Rung 1, then its immutable companion carrying the consistency proof.

    Refuses before the base rung unless the contract is satisfiable and the
    protocol's declared rows are the executable rows.
    """
    ws = ws or workspace()
    with _bound():
        att.prove_contract_consistency()
        result = base.freeze_protocol(ws)
        result["protocol_attestation"] = _companion("protocol_attestation", ws)
        return result


def freeze_universe(ws: Any | None = None) -> dict[str, Any]:
    """Rung 3, then its immutable companion proving disjointness from both spent
    cohorts.

    The enumerator already subtracts them, and this does not trust it. A filter
    and a proof written as one piece of code agree by construction and prove
    nothing; written separately, a silent failure in either is visible.
    """
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
# the V2R3 execution gate
#
# The base gate verifies protocol -> universe -> scorer -> exclusions and knows
# nothing about the three V2R3 proofs. Inheriting it would let the chain report
# READY with no immutable receipt binding them, which is the same false-
# provenance seam one level up. THE V2R3 SCORER CALLS THIS AND NEVER THE BASE.


def require_v2r3_execution_preconditions(ws: Any | None = None) -> dict[str, Any]:
    """Everything the base gate checks, plus the three attestations, recomputed."""
    ws = ws or workspace()
    with _bound():
        ready = base.require_execution_preconditions(ws)

        #: The base gate REPORTS prior measurements. A closure runs exactly once,
        #: so here it REFUSES on them -- a report is not a refusal, and "already
        #: measured" printed beside READY is a state this study must not be able
        #: to reach.
        already = ready.get("already_measured") or []
        if already:
            raise FreezeRefused(
                f"a V2R3 measurement already exists: {already}. A closure runs "
                "EXACTLY ONCE. Its corpus is spent and no rescore is permitted."
            )

        attestations = att.verify_all(ws)

    return {
        **ready,
        "gate": "require_v2r3_execution_preconditions",
        "companion_attestations": {
            name: {"receipt": entry["attestation"], "recomputed": True}
            for name, entry in attestations.items()
        },
        "root_disjointness": attestations["frame_attestation"]["recomputed"],
        "contract_consistency": attestations["protocol_attestation"]["recomputed"],
        "spent_disjointness": attestations["universe_attestation"]["recomputed"],
    }


# ---------------------------------------------------------------------------
# apply the overrides to the imported module, then expose the base commands


#: NOTHING IS REBOUND AT IMPORT. `_bound()` applies these for the duration of
#: one rung and restores them afterwards, so importing this module cannot
#: change how another study's adapter behaves in the same process.


#: `STAGES` in the base module captured direct references when it was defined,
#: so rebinding a function name there does not reach it. The V2R3 table is built
#: from it and the three wrapped rungs replace their entries by name.
#: EVERY inherited stage is wrapped, not just the ones with V2R3-specific
#: behaviour. An inherited stage called raw reads the base's OWN defaults, and
#: the failure is silent in the direction that matters: `scorer` refused with
#: "rung 3 is already frozen" because it had resolved V2R1's protocol, found
#: V2R1's scorer stem, and found V2R1's receipt. Nothing about that refusal said
#: it was talking about a different study.
#:
#: While the bindings were applied permanently at import this happened to work,
#: which is exactly what made it a trap: the correct fix for the import-order
#: hazard exposed a second defect the hazard had been masking.
def _wrap(name: str, stage: Any) -> Any:
    def bound_stage(*args: Any, **kwargs: Any) -> Any:
        with _bound():
            return stage(*args, **kwargs)

    bound_stage.__name__ = f"bound_{name}"
    bound_stage.__doc__ = (
        f"`{name}` from the shared base, run with this adapter's bindings in force."
    )
    return bound_stage


STAGES: dict[str, Any] = {name: _wrap(name, stage) for name, stage in base.STAGES.items()}
#: The four with V2R3-specific behaviour replace their entries outright; each
#: already enters `_bound()` itself.
STAGES["frame"] = freeze_acquisition_frame
STAGES["protocol"] = freeze_protocol
STAGES["universe"] = freeze_universe
#: The inherited `gate` points at the base precondition check, which knows
#: nothing about the three V2R3 proofs. Overridden by name so a chain cannot
#: report READY without them.
STAGES["gate"] = require_v2r3_execution_preconditions


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
