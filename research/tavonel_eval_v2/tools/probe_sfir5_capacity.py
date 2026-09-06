#!/usr/bin/env python3
"""SFIR5's live metadata-only capacity census.

This module is deliberately thin, and the thinness is the design. It does not
enumerate, does not select, does not count and does not decide anything. It runs
SFIR4's probe, against SFIR4's charter, with SFIR5's transport, and then seals
what came out under SFIR5's name.

Three properties follow from that, and none of them is a promise:

**The science cannot have drifted.** `probe_sfir4_capacity.probe_capacity`
re-hashes itself against the charter it is handed before it does anything, and
the charter is SFIR4's own file at its own digest. Family definitions, roots,
inclusion rules, C_f, Q_f, caps, salt, identity rules -- none of them are
restated anywhere in SFIR5, so there is no second copy that could disagree.

**The census input will say SFIR4.** `probe_capacity` writes
`protocol_id: SOURCE_FACT_IR_INDEPENDENT_REPLICATION_V4` into its output, because
it IS SFIR4's algorithm. That field is correct and it is also the most
mistakable thing here, so the seal this module writes binds the census input by
digest and records `executed_under: ..._V5`. A census input must never be read as
an SFIR4 result on the strength of that field alone -- SFIR4 is sealed as a
terminal operational stop and produced no census.

**Every family lands in the response ledger.** SFIR4's chain covered one family
of three (INC-V2-102). `require_family_coverage` runs before the seal and refuses
a census whose ledger is missing a family that reported candidates.

Nothing here opens a payload, and nothing here evaluates the capacity criterion.
A census that ends early writes nothing at all.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import live_cohort_guard  # noqa: E402
import probe_sfir4_capacity as probe4  # noqa: E402
import sfir4_protocol as protocol  # noqa: E402
import sfir5_charter as charter  # noqa: E402
import sfir5_transport as transport  # noqa: E402
from acquisition import sources_sfir4 as sources  # noqa: E402

SEAL_SCHEMA = "tavonel.sfir5.capacity_census_seal.v1"


def _verify_sfir5_charter(root: Path, freeze_ref: Mapping[str, Any]) -> dict[str, Any]:
    """The SFIR5 charter freeze must be the one on disk, and must still describe
    the transport that is about to run.

    Re-checking the transport here rather than trusting the seal is the
    INC-V2-092 lesson: a pin written once and never compared again is a pin over
    bytes nothing reads.
    """
    path = root / freeze_ref["path"]
    if protocol.sha_file(path) != freeze_ref["sha256"]:
        raise charter.SFIR5Refused("the SFIR5 charter freeze has moved since it was sealed")
    body = json.loads(path.read_text(encoding="utf-8"))
    if body.get("schema") != charter.CHARTER_SCHEMA or body.get("state") != "FROZEN_PRE_CENSUS":
        raise charter.SFIR5Refused("the SFIR5 charter freeze is not a frozen pre-census authority")
    running = protocol.sha_file(Path(transport.__file__))
    if body["toolchain"]["sfir5_transport"]["sha256"] != running:
        raise charter.SFIR5Refused(
            "the transport that would run is not the transport the charter froze"
        )
    return body


def _families_reporting_candidates(census: Mapping[str, Any]) -> set[str]:
    """Which families the census says it found something in.

    The independent side of the coverage comparison. It is read from the census
    body rather than from the transport, so a family that produced candidates
    while recording no response evidence is a contradiction between two
    structures instead of an agreement between two silences.
    """
    return {
        family
        for family, block in census.get("families", {}).items()
        if isinstance(block, Mapping) and block.get("candidates")
    }


def require_carried_charter(
    root: Path, frozen: Mapping[str, Any], sfir4_charter_ref: Mapping[str, Any]
) -> None:
    """The SFIR4 charter handed to the probe must be the one SFIR5 sealed.

    Both halves, and both are refusals on their own. Path alone would accept the
    right filename holding different bytes -- which is the whole scenario a
    digest exists to catch -- and digest alone would accept the right bytes
    reached by a path the seal never named.
    """
    offered = root / sfir4_charter_ref["path"]
    carried = frozen["carried_forward_by_reference"]
    if not offered.is_file():
        raise charter.SFIR5Refused("the SFIR4 charter offered to the census is absent")
    digest = "sha256:" + hashlib.sha256(offered.read_bytes()).hexdigest()
    if carried["sha256"] != digest:
        raise charter.SFIR5Refused(
            "the SFIR4 charter offered is not the bytes SFIR5 carries forward"
        )
    if carried["charter"] != str(sfir4_charter_ref["path"]).replace("\\", "/").removeprefix(
        "research/tavonel_eval_v2/"
    ):
        raise charter.SFIR5Refused(
            "the SFIR4 charter offered is not at the path SFIR5 carries forward"
        )


def require_freeze_covers_the_carried_charter(
    root: Path, freeze_ref: Mapping[str, Any], sfir4_charter_ref: Mapping[str, Any]
) -> dict[str, Any]:
    """The SFIR4 charter FREEZE handed to the probe must seal the carried YAML.

    Two artifacts, two roles, and conflating them is how a census ends up running
    against a charter nobody carried forward: `probe_capacity` consumes the
    freeze receipt, while SFIR5's carry-forward names the YAML. Accepting both as
    independent inputs would let a caller pass a freeze of some OTHER charter
    alongside the right YAML, and every individual check would still pass. This
    is the join.
    """
    path = root / freeze_ref["path"]
    if protocol.sha_file(path) != freeze_ref["sha256"]:
        raise charter.SFIR5Refused("the SFIR4 charter freeze has moved since it was sealed")
    body = json.loads(path.read_text(encoding="utf-8"))
    if body.get("schema") != protocol.CHARTER_SCHEMA or body.get("state") != "FROZEN_PRE_CENSUS":
        raise charter.SFIR5Refused("the SFIR4 charter freeze is not a frozen pre-census authority")
    if body.get("charter") != dict(sfir4_charter_ref):
        raise charter.SFIR5Refused(
            "the SFIR4 charter freeze seals a different charter from the one SFIR5 carries "
            f"forward: it seals {body.get('charter')}"
        )
    return body


def run(
    root: Path,
    sfir5_charter_ref: Mapping[str, Any],
    sfir4_charter_ref: Mapping[str, Any],
    sfir4_freeze_ref: Mapping[str, Any],
    spent_ref: Mapping[str, Any],
    census_destination: Path,
    seal_destination: Path,
    generated_at: str,
) -> tuple[Path, Path]:
    """Run the census and seal it, or refuse and write nothing."""
    # INC-V2-100: a live traversal started from a test run is a real traversal.
    # Written inline rather than behind a helper because `anti_blocker_audit`
    # detects the guard by finding `sys.modules` in the module's own text, and a
    # guard it cannot see is a guard it cannot report missing.
    if "pytest" in sys.modules or "unittest" in sys.modules:
        live_cohort_guard.refuse_under_test("probe_sfir5_capacity.run")
    frozen = _verify_sfir5_charter(root, sfir5_charter_ref)
    require_carried_charter(root, frozen, sfir4_charter_ref)
    require_freeze_covers_the_carried_charter(root, sfir4_freeze_ref, sfir4_charter_ref)

    paced = transport.PacedObservingTransport()
    census_path = probe4.probe_capacity(
        root, sfir4_freeze_ref, spent_ref, census_destination, paced
    )
    census = json.loads(census_path.read_text(encoding="utf-8"))

    coverage = transport.require_family_coverage(
        ledger_families={row.family for row in paced.ledger.observations()},
        families_with_candidates=_families_reporting_candidates(census),
    )

    seal: dict[str, Any] = {
        "schema": SEAL_SCHEMA,
        "protocol_id": charter.PROTOCOL_ID,
        "generated_at": generated_at,
        "state": "CENSUS_SEALED",
        "executed_under": charter.PROTOCOL_ID,
        "charter_freeze": dict(sfir5_charter_ref),
        "science_carried_from": dict(sfir4_charter_ref),
        "science_carried_from_freeze": dict(sfir4_freeze_ref),
        "spent_identity_authority": dict(spent_ref),
        "census_input": protocol.exact_ref(root, census_path),
        "census_input_protocol_id": census.get("protocol_id"),
        "what_the_census_input_protocol_id_means": (
            "the census input records SFIR4's protocol_id because it is SFIR4's "
            "probe and SFIR4's charter that produced it. The RUN is SFIR5's. SFIR4 "
            "is sealed as a terminal operational stop and produced no census; this "
            "artifact must never be presented as an SFIR4 result."
        ),
        "family_coverage": coverage,
        "transport": paced.summary(),
        "families_declared": sorted(sources.FAMILIES),
        "capacity_criterion_evaluated_here": False,
        "payload_opened": False,
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }
    seal["content_sha256"] = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(seal, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    return census_path, protocol.write_immutable(seal_destination, seal)


def main(argv: list[str] | None = None) -> int:
    import argparse

    from common import now

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=NS.parents[1])
    parser.add_argument("--sfir5-charter", type=Path, required=True)
    parser.add_argument("--sfir4-charter", type=Path, required=True)
    parser.add_argument("--sfir4-charter-freeze", type=Path, required=True)
    parser.add_argument("--spent", type=Path, required=True)
    parser.add_argument("--census-destination", type=Path, required=True)
    parser.add_argument("--seal-destination", type=Path, required=True)
    parser.add_argument("--generated-at", default=None)
    parser.add_argument(
        "--live",
        action="store_true",
        required=True,
        help="required, so a live census is never started by accident",
    )
    args = parser.parse_args(argv)
    try:
        census, seal = run(
            args.root,
            protocol.exact_ref(args.root, args.sfir5_charter),
            protocol.exact_ref(args.root, args.sfir4_charter),
            protocol.exact_ref(args.root, args.sfir4_charter_freeze),
            protocol.exact_ref(args.root, args.spent),
            args.census_destination,
            args.seal_destination,
            args.generated_at or now(),
        )
    except (charter.SFIR5Refused, protocol.SFIR4Refused, transport.FamilyCoverageRefused) as error:
        print(
            json.dumps({"state": "REFUSED", "why": str(error)}, indent=2),
            file=sys.stderr,
        )
        return 4
    except transport.TransportBudgetExceeded as error:
        print(
            json.dumps({"state": "TERMINAL_TRANSPORT_BUDGET", "why": str(error)}, indent=2),
            file=sys.stderr,
        )
        return 5
    print(
        json.dumps(
            {"state": "SEALED", "census": census.as_posix(), "seal": seal.as_posix()}, indent=2
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
