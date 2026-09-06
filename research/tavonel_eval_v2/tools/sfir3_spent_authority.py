"""Compose SFIR3's spent set from SFIR2's exact comprehensive authority.

The SFIR2 failure happened within the Git family before its family exit; the
exact failing Git root is not known.  eCFR and Wikipedia were not reached.
SFIR3 conservatively reserves every statically declared SFIR2 Git root. It
does not reserve SFIR2 eCFR or Wikipedia roots because those families were
provably not reached. It does not invent a wildcard reservation for the unvisited
dynamic eCFR title/part universe; historical eCFR identities remain excluded
through the comprehensive SFIR2 authority.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import sfir3_protocol as protocol

try:
    from acquisition import sources_sfir3 as sources
except ImportError:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from acquisition import sources_sfir3 as sources

SFIR2_SPENT_SHA256 = "sha256:89806ddf659e3bb296fbb3e3eaece4e11d6d669ad7598ad71b4e49b140c46d31"
SFIR2_CHARTER_SHA256 = "sha256:d54ef39bc569ab1482655fadd83e54bf07c6c212f719ec6e5a2172b6585e6a31"
SFIR2_FAILURE_SHA256 = "sha256:83b43161d056087318aa02d24c8621688b38881b254f12949f8e73caa242dbde"


def _load_exact(
    root: Path, ref: Mapping[str, Any], expected_sha: str, expected_schema: str
) -> tuple[Path, dict[str, Any]]:
    path = protocol._resolve_ref(root, ref)
    if ref["sha256"] != expected_sha:
        raise protocol.SFIR3Refused(f"wrong frozen predecessor digest for {ref['path']}")
    body = json.loads(path.read_text(encoding="utf-8"))
    if body.get("schema") != expected_schema:
        raise protocol.SFIR3Refused(f"wrong frozen predecessor schema for {ref['path']}")
    return path, body


def compose_spent_authority(
    root: Path,
    sfir2_spent_ref: Mapping[str, Any],
    sfir2_charter_ref: Mapping[str, Any],
    sfir2_failure_ref: Mapping[str, Any],
    destination: Path,
    generated_at: str,
) -> Path:
    spent_path, spent = _load_exact(
        root, sfir2_spent_ref, SFIR2_SPENT_SHA256, "tavonel.sfir2.spent_identity_authority.v1"
    )
    charter_path, _charter = _load_exact(
        root, sfir2_charter_ref, SFIR2_CHARTER_SHA256, "tavonel.sfir2.design_charter_freeze.v1"
    )
    failure_path, failure = _load_exact(
        root, sfir2_failure_ref, SFIR2_FAILURE_SHA256, "tavonel.sfir2.capacity_probe_failure.v1"
    )
    if (
        failure.get("protocol_id") != "SOURCE_FACT_IR_INDEPENDENT_REPLICATION_V2"
        or failure.get("state") != "TERMINAL_PRE_PAYLOAD_CAPACITY_INSTRUMENT_REFUSAL"
        or failure.get("reason") != "FROZEN_GIT_REVISION_CHRONOLOGY_REFUSAL"
        or failure.get("failure_stage") != "GIT_DOCS_FAMILY_BEFORE_FAMILY_EXIT"
        or failure.get("exact_root_unknown") is not True
        or failure.get("families_not_reached") != ["regulation_ecfr", "encyclopedia_wikipedia"]
        or failure.get("capacity_metadata_written") is not False
    ):
        raise protocol.SFIR3Refused("SFIR2 failure is not the expected terminal pre-payload state")
    if any(
        failure.get(key) is not False
        for key in (
            "payload_opened",
            "diff_opened",
            "source_fact_computed",
            "endpoint_outcome_computed",
            "score_attempted",
        )
    ):
        raise protocol.SFIR3Refused("SFIR2 failure does not prove pre-payload termination")
    if failure.get("charter") != dict(sfir2_charter_ref) or failure.get(
        "spent_identity_authority"
    ) != dict(sfir2_spent_ref):
        raise protocol.SFIR3Refused("SFIR2 failure predecessor references drifted")

    containers = set(spent.get("container_ids") or [])
    lineages = set(spent.get("lineage_ids") or [])
    aliases = set(spent.get("alias_ids") or [])
    if not containers or not lineages or not aliases:
        raise protocol.SFIR3Refused("SFIR2 comprehensive spent authority is incomplete")
    try:
        sources.assert_disjoint_from_comprehensive_spent(containers, aliases)
    except RuntimeError as error:
        raise protocol.SFIR3Refused(str(error)) from error

    reserved_git = [sources.discovery_root_id("git_docs", repo) for repo in sources.SFIR2_GIT_ROOTS]
    containers.update(reserved_git)

    derivation = {
        "failure_stage": "GIT_DOCS_FAMILY_BEFORE_FAMILY_EXIT",
        "failure_reason": failure.get("reason"),
        "exact_root_unknown": True,
        "families_not_reached": ["regulation_ecfr", "encyclopedia_wikipedia"],
        "reserve_all_sfir2_git_roots": True,
        "reserve_unreached_sfir2_wikipedia_roots": False,
        "reserve_unreached_ecfr_title_part_wildcard": False,
        "historical_ecfr_exclusion_source": "sfir2_comprehensive_spent_identity_authority",
    }
    return protocol._write_immutable(
        destination,
        {
            "schema": protocol.SPENT_AUTHORITY_SCHEMA,
            "protocol_id": protocol.PROTOCOL_ID,
            "generated_at": generated_at,
            "state": "COMPLETE_COMPOSED_SPENT_AUTHORITY",
            "predecessor_sources": {
                "sfir2_comprehensive_spent": protocol.exact_ref(root, spent_path),
                "sfir2_design_charter": protocol.exact_ref(root, charter_path),
                "sfir2_terminal_failure": protocol.exact_ref(root, failure_path),
            },
            "derivation": derivation,
            "reserved_sfir2_declared_roots": {
                "git_docs": sorted(reserved_git),
                "regulation_ecfr": [],
                "encyclopedia_wikipedia": [],
            },
            "container_ids": sorted(containers),
            "lineage_ids": sorted(lineages),
            "alias_ids": sorted(aliases),
        },
    )


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--sfir2-spent", type=Path, required=True)
    parser.add_argument("--sfir2-charter", type=Path, required=True)
    parser.add_argument("--sfir2-failure", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--generated-at", required=True)
    args = parser.parse_args(argv)
    refs = [
        protocol.exact_ref(args.root, path)
        for path in (args.sfir2_spent, args.sfir2_charter, args.sfir2_failure)
    ]
    path = compose_spent_authority(args.root, *refs, args.destination, args.generated_at)
    print(path.as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
