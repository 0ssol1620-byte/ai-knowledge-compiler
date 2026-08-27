"""The freeze ladder for IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R2.

THIS IS AN ADAPTER, NOT A FORK, and the choice is deliberate. The V2R1 freezer
is ~1,900 lines of receipt envelopes, digest recomputation, chain-link
verification and refusal logic that must behave IDENTICALLY here; copying it
would create a second implementation of the same machinery, free to drift, which
is the defect this study has recorded against itself more than once. So V2R2
imports it and overrides exactly the parts that are genuinely V2R1-specific.

V2R1's own tooling is NOT edited. Its scorer digest is bound inside the
adjudication receipt, its run is spent, and its re-run guard refuses; changing
that file after the fact would break the reproducibility of a receipt the
founder ordered preserved. Every override below is applied to the imported
module object inside THIS process only.

THE OVERRIDES, named rather than performed silently:

    PROTOCOL          the V2R2 yaml, carried on every Workspace this module makes
    FRAME_MODULE      acquisition/sources_v2r2.py
    _load_frame       imports sources_v2r2
    MEASUREMENT_GLOB  the V2R2 measurement receipt name
    _nothing_has_been_measured
                      same two conditions, over the V2R2 corpus directory
    freeze_acquisition_frame
                      wrapped, so the pre-acquisition check runs against the
                      corpus path that actually exists
    freeze_universe   wrapped, to prove disjointness from V2R1's spent 285

A PATCH THAT SILENTLY MISSES IS WORSE THAN NO PATCH. `_verify_override_targets`
runs at import and raises if any name above has vanished from the base module,
so a rename there becomes an immediate failure here instead of a V2R2 run that
quietly used V2R1's protocol path.

WHY THE WRAPPED FRAME CHECK EXISTS. The base's pre-acquisition guard tests
`ws.root / "artifacts" / "development" / "v2r1_corpus"`, but `ws.root` is the
REPOSITORY root and the corpus lives under `research/tavonel_eval_v2/`. That
path never existed, so the guard could not fire -- a guard placed where its
failure is impossible, which is INC-V2-036's shape exactly. It is recorded
against V2R1 rather than repaired there, and V2R2 checks the real path first.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition"), str(NS / "compiler")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import freeze_migration_closure_v2r1 as base  # noqa: E402

FreezeRefused = base.FreezeRefused

PROTOCOL = NS / "protocols" / "IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R2.yaml"
FRAME_MODULE = NS / "acquisition" / "sources_v2r2.py"
CORPUS = NS / "artifacts" / "development" / "v2r2_corpus"
MEASUREMENT_GLOB = "identity-change-migration-closure-v2r2--*.json"

#: V2R1's frozen universe receipt, read for LINEAGE IDS ONLY -- no verdict, no
#: count, no violated case.
V2R1_UNIVERSE_STEM = "identity-change-migration-closure-v2r1-universe"

_OVERRIDE_TARGETS = (
    "PROTOCOL",
    "FRAME_MODULE",
    "MEASUREMENT_GLOB",
    "_load_frame",
    "_nothing_has_been_measured",
    "freeze_acquisition_frame",
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
            "a V2R2 run would silently inherit V2R1's settings. Fix the adapter "
            "rather than the base: V2R1's tooling is spent-run evidence."
        )


_verify_override_targets()


@dataclass(frozen=True)
class V2R2Workspace(base.Workspace):
    """The base Workspace with the V2R2 protocol as its default.

    Rebinding `base.PROTOCOL` is NOT enough and the reason is easy to miss: a
    dataclass bakes its field defaults into the generated `__init__` when the
    class is created, so `base.Workspace()` would keep handing out V2R1's
    protocol path however many module globals were reassigned. Subclassing
    regenerates `__init__` with the new default, and `base.Workspace` is then
    rebound to this class so the base module's own `ws or Workspace()` calls --
    resolved as module globals at call time -- pick it up.
    """

    protocol: Path = PROTOCOL


def workspace() -> Any:
    return V2R2Workspace()


def _load_frame() -> Any:
    sys.path.insert(0, str(NS / "acquisition"))
    try:
        import sources_v2r2
    except Exception as error:  # pragma: no cover -- the frame is a hard dependency
        raise FreezeRefused(f"cannot load the acquisition frame: {error}") from error
    return sources_v2r2


def _nothing_has_been_measured(ws: Any) -> tuple[bool, list[str]]:
    """Is V2R2 still entirely upstream of any outcome-bearing data?

    The base's two conditions, unchanged in substance: no acquired material, and
    no rung after the protocol frozen. Only the corpus directory differs.
    """
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


def v2r1_spent_lineages(ws: Any) -> tuple[frozenset[str], dict[str, Any]]:
    """The 285 spent lineage ids, with the receipt they came from.

    Read for IDS ONLY. No verdict, no violation count and no violated case is
    read here, and V2R1 is never a denominator in this study -- neither a
    positive one nor a negative one.
    """
    receipts = sorted(ws.prior_receipts.glob(f"{V2R1_UNIVERSE_STEM}--*.json"))
    if not receipts:
        raise FreezeRefused(
            "V2R1's frozen universe receipt is not on disk, so V2R2 cannot prove it "
            "avoided the spent 285. An unprovable disjointness is not an assumed one."
        )
    source = receipts[-1]
    body = json.loads(source.read_text(encoding="utf-8"))
    ids = frozenset(str(row["lineage_id"]) for row in body.get("pairs", ()))
    if not ids:
        raise FreezeRefused(
            f"{source.name} declares no pairs. A disjointness proof against an empty "
            "set proves nothing, and this study does not accept vacuous proofs."
        )
    return ids, {
        "source_receipt": base._rel(source, ws.root),
        "source_receipt_sha256": base.sha_file(source),
        "distinct_lineages": len(ids),
        "read_for": (
            "lineage ids only. No V2R1 verdict, count or violated case is read, and "
            "the INVALID_INSTRUMENT_CONTRACT adjudication is neither re-opened nor "
            "re-interpreted here."
        ),
    }


# ---------------------------------------------------------------------------
# wrapped rungs


def freeze_acquisition_frame(ws: Any | None = None) -> dict[str, Any]:
    """Rung 0, with the pre-acquisition check pointed at the real corpus path."""
    ws = ws or workspace()
    if CORPUS.exists() and any(CORPUS.iterdir()):
        raise FreezeRefused(
            f"{base._rel(CORPUS, ws.root)} already holds acquired material. The frame "
            "is sealed BEFORE acquisition; sealing it afterwards would record what "
            "was done rather than constrain what may be done."
        )
    return base.freeze_acquisition_frame(ws)


def freeze_universe(ws: Any | None = None) -> dict[str, Any]:
    """Rung 3, plus an INDEPENDENT proof of disjointness from V2R1's spent 285.

    The enumerator already subtracts them, and this does not trust it. A filter
    and a proof written as one piece of code agree by construction and prove
    nothing; written separately, a silent failure in either is visible.
    """
    ws = ws or workspace()
    result = base.freeze_universe(ws)

    protocol = base.load_protocol(ws.protocol)
    receipt = base.latest_receipt(base.stem_for(protocol, "universe"), ws.receipts)
    if receipt is None:  # pragma: no cover -- freeze_universe just wrote it
        raise FreezeRefused("the universe freeze reported success but wrote no receipt")

    frozen = {str(row["lineage_id"]) for row in receipt.get("pairs", ())}
    spent, meta = v2r1_spent_lineages(ws)
    overlap = sorted(frozen & spent)
    if overlap:
        raise FreezeRefused(
            "the frozen universe intersects V2R1's SPENT 285, which means the "
            "enumerator's exclusion and this proof disagree and one of them is "
            f"broken: {overlap[:6]}"
        )

    result["v2r1_spent_disjointness"] = {
        "proved": True,
        "frozen_pairs": len(frozen),
        "spent_lineages": len(spent),
        "intersection": 0,
        **meta,
    }
    return result


# ---------------------------------------------------------------------------
# apply the overrides to the imported module, then expose the base commands


base.PROTOCOL = PROTOCOL
base.FRAME_MODULE = FRAME_MODULE
base.MEASUREMENT_GLOB = MEASUREMENT_GLOB
base._load_frame = _load_frame
base._nothing_has_been_measured = _nothing_has_been_measured
base.Workspace = V2R2Workspace

#: `STAGES` in the base module captured direct references when it was defined,
#: so rebinding a function name there does not reach it. The V2R2 table is built
#: from it and the two wrapped rungs replace their entries by name.
STAGES: dict[str, Any] = dict(base.STAGES)
STAGES["frame"] = freeze_acquisition_frame
STAGES["universe"] = freeze_universe


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
