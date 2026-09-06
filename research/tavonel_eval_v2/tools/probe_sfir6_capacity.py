#!/usr/bin/env python3
"""SFIR6's live capacity census: SFIR4's science, SFIR6's repaired instrument.

Thin for the same reason SFIR5's runner was thin. It enumerates nothing, selects
nothing, counts nothing and decides nothing. It runs `probe_sfir4_capacity` --
which re-hashes itself against SFIR4's charter before it starts -- with SFIR6's
transport, and seals the result under SFIR6's name.

What differs from SFIR5's runner is one line and one consequence: the transport
is `SFIR6Transport`, so `encyclopedia_wikipedia` is served by the repaired
adapter (INC-V2-106) while git and eCFR still run through the modules SFIR4
froze. Re-measuring those two under a changed code path would make SFIR6's
numbers incomparable with SFIR5's for reasons unrelated to the repair.

All three families are measured. No SFIR5 number is carried across, and the
verdict is whatever this census produces.
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
import probe_sfir5_capacity as runner5  # noqa: E402
import sfir4_protocol as protocol  # noqa: E402
import sfir5_transport as t5  # noqa: E402
import sfir6_charter as charter6  # noqa: E402
import sfir6_transport as t6  # noqa: E402
import sfir6_wikipedia as wiki  # noqa: E402
from acquisition import sources_sfir4 as sources  # noqa: E402

SEAL_SCHEMA = "tavonel.sfir6.capacity_census_seal.v1"


def run(
    root: Path,
    sfir6_charter_ref: Mapping[str, Any],
    sfir4_charter_ref: Mapping[str, Any],
    sfir4_freeze_ref: Mapping[str, Any],
    spent_ref: Mapping[str, Any],
    census_destination: Path,
    seal_destination: Path,
    generated_at: str,
) -> tuple[Path, Path]:
    if "pytest" in sys.modules or "unittest" in sys.modules:
        live_cohort_guard.refuse_under_test("probe_sfir6_capacity.run")

    frozen_path = root / sfir6_charter_ref["path"]
    if protocol.sha_file(frozen_path) != sfir6_charter_ref["sha256"]:
        raise charter6.SFIR6Refused("the SFIR6 charter freeze has moved since it was sealed")
    frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
    if (
        frozen.get("schema") != charter6.CHARTER_SCHEMA
        or frozen.get("state") != "FROZEN_PRE_CENSUS"
    ):
        raise charter6.SFIR6Refused("the SFIR6 charter freeze is not a frozen pre-census authority")
    for name, module in (
        ("sfir6_wikipedia", wiki),
        ("sfir6_transport", t6),
        ("sfir5_transport", t5),
        ("probe_sfir4_capacity", probe4),
    ):
        running = protocol.sha_file(Path(module.__file__))
        if frozen["toolchain"][name]["sha256"] != running:
            raise charter6.SFIR6Refused(f"{name} is not the module the charter froze")

    runner5.require_carried_charter(root, frozen, sfir4_charter_ref)
    runner5.require_freeze_covers_the_carried_charter(root, sfir4_freeze_ref, sfir4_charter_ref)

    paced = t6.SFIR6Transport()
    census_path = probe4.probe_capacity(
        root, sfir4_freeze_ref, spent_ref, census_destination, paced
    )
    census = json.loads(census_path.read_text(encoding="utf-8"))
    coverage = t5.require_family_coverage(
        ledger_families={row.family for row in paced.ledger.observations()},
        families_with_candidates=runner5._families_reporting_candidates(census),
    )
    seal: dict[str, Any] = {
        "schema": SEAL_SCHEMA,
        "protocol_id": charter6.PROTOCOL_ID,
        "generated_at": generated_at,
        "state": "CENSUS_SEALED",
        "executed_under": charter6.PROTOCOL_ID,
        "charter_freeze": dict(sfir6_charter_ref),
        "science_carried_from": dict(sfir4_charter_ref),
        "science_carried_from_freeze": dict(sfir4_freeze_ref),
        "spent_identity_authority": dict(spent_ref),
        "census_input": protocol.exact_ref(root, census_path),
        "census_input_protocol_id": census.get("protocol_id"),
        "what_the_census_input_protocol_id_means": (
            "the census input records SFIR4's protocol_id because it is SFIR4's probe "
            "and SFIR4's charter that produced it. The RUN is SFIR6's, with the "
            "Wikipedia adapter repaired per INC-V2-106."
        ),
        "family_coverage": coverage,
        "transport": paced.summary(),
        "wikipedia_adapter": "SFIR6_TWO_PASS_BATCHED_NO_RVLIMIT",
        "families_declared": sorted(sources.FAMILIES),
        "all_three_families_remeasured": True,
        "no_sfir5_number_reused": True,
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
    parser.add_argument("--sfir6-charter", type=Path, required=True)
    parser.add_argument("--sfir4-charter", type=Path, required=True)
    parser.add_argument("--sfir4-charter-freeze", type=Path, required=True)
    parser.add_argument("--spent", type=Path, required=True)
    parser.add_argument("--census-destination", type=Path, required=True)
    parser.add_argument("--seal-destination", type=Path, required=True)
    parser.add_argument("--generated-at", default=None)
    parser.add_argument("--live", action="store_true", required=True)
    args = parser.parse_args(argv)
    try:
        census, seal = run(
            args.root,
            protocol.exact_ref(args.root, args.sfir6_charter),
            protocol.exact_ref(args.root, args.sfir4_charter),
            protocol.exact_ref(args.root, args.sfir4_charter_freeze),
            protocol.exact_ref(args.root, args.spent),
            args.census_destination,
            args.seal_destination,
            args.generated_at or now(),
        )
    except (charter6.SFIR6Refused, protocol.SFIR4Refused, t5.FamilyCoverageRefused) as error:
        print(json.dumps({"state": "REFUSED", "why": str(error)}, indent=2), file=sys.stderr)
        return 4
    except (wiki.WikipediaProtocolError, wiki.WikipediaSemanticIncomplete) as error:
        print(
            json.dumps({"state": "ADAPTER_REFUSED", "why": str(error)}, indent=2), file=sys.stderr
        )
        return 6
    except t5.TransportBudgetExceeded as error:
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
