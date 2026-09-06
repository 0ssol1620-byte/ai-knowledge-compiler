"""Compose SFIR2's spent set from SFIR1's exact comprehensive authority.

The SFIR1 failure happened within the Git family before its family exit; the
exact failing Git root is not known.  eCFR and Wikipedia were not reached.
SFIR2 nevertheless reserves every statically declared SFIR1 Git and
Wikipedia root.  It does not invent a wildcard reservation for the unvisited
dynamic eCFR title/part universe; historical eCFR identities remain excluded
through the comprehensive SFIR1 authority.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import sfir2_protocol as protocol

try:
    from acquisition import sources_sfir2 as sources
except ImportError:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from acquisition import sources_sfir2 as sources

SFIR1_SPENT_SHA256 = "sha256:cfc0f3d0e14fada3855660452691cd8a29543e39fab6f0035266024ba86c9bf5"
SFIR1_CHARTER_SHA256 = "sha256:b5ae12d49685ded7e8231986593f5f61de514cfd94b37c7c62c74c89cb2e040d"
SFIR1_FAILURE_SHA256 = "sha256:944b3ff6baff5b125c22ed96d4f222043d741c25cf54d7ea13156e34252deb6c"


def _load_exact(
    root: Path, ref: Mapping[str, Any], expected_sha: str, expected_schema: str
) -> tuple[Path, dict[str, Any]]:
    path = protocol._resolve_ref(root, ref)
    if ref["sha256"] != expected_sha:
        raise protocol.SFIR2Refused(f"wrong frozen predecessor digest for {ref['path']}")
    body = json.loads(path.read_text(encoding="utf-8"))
    if body.get("schema") != expected_schema:
        raise protocol.SFIR2Refused(f"wrong frozen predecessor schema for {ref['path']}")
    return path, body


def compose_spent_authority(
    root: Path,
    sfir1_spent_ref: Mapping[str, Any],
    sfir1_charter_ref: Mapping[str, Any],
    sfir1_failure_ref: Mapping[str, Any],
    destination: Path,
    generated_at: str,
) -> Path:
    spent_path, spent = _load_exact(
        root, sfir1_spent_ref, SFIR1_SPENT_SHA256, "tavonel.sfir1.spent_identity_authority.v1"
    )
    charter_path, _charter = _load_exact(
        root, sfir1_charter_ref, SFIR1_CHARTER_SHA256, "tavonel.sfir1.design_charter_freeze.v1"
    )
    failure_path, failure = _load_exact(
        root, sfir1_failure_ref, SFIR1_FAILURE_SHA256, "tavonel.sfir1.capacity_probe_failure.v1"
    )
    if failure.get("state") != "TERMINAL_PRE_PAYLOAD_CAPACITY_INSTRUMENT_REFUSAL":
        raise protocol.SFIR2Refused("SFIR1 failure is not the expected terminal pre-payload state")
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
        raise protocol.SFIR2Refused("SFIR1 failure does not prove pre-payload termination")
    if failure.get("charter") != dict(sfir1_charter_ref) or failure.get(
        "spent_identity_authority"
    ) != dict(sfir1_spent_ref):
        raise protocol.SFIR2Refused("SFIR1 failure predecessor references drifted")

    containers = set(spent.get("container_ids") or [])
    lineages = set(spent.get("lineage_ids") or [])
    aliases = set(spent.get("alias_ids") or [])
    if not containers or not lineages or not aliases:
        raise protocol.SFIR2Refused("SFIR1 comprehensive spent authority is incomplete")
    try:
        sources.assert_disjoint_from_comprehensive_spent(containers, aliases)
    except RuntimeError as error:
        raise protocol.SFIR2Refused(str(error)) from error

    reserved_git = [sources.discovery_root_id("git_docs", repo) for repo in sources.SFIR1_GIT_ROOTS]
    reserved_wiki = [
        sources.discovery_root_id("encyclopedia_wikipedia", category)
        for category in sources.SFIR1_WIKIPEDIA_ROOTS
    ]
    containers.update(reserved_git)
    containers.update(reserved_wiki)

    derivation = {
        "failure_stage": "GIT_DOCS_FAMILY_BEFORE_FAMILY_EXIT",
        "failure_reason": failure.get("reason"),
        "exact_root_unknown": True,
        "families_not_reached": ["regulation_ecfr", "encyclopedia_wikipedia"],
        "reserve_all_sfir1_git_roots": True,
        "reserve_all_sfir1_wikipedia_static_roots": True,
        "reserve_unreached_ecfr_title_part_wildcard": False,
        "historical_ecfr_exclusion_source": "sfir1_comprehensive_spent_identity_authority",
    }
    return protocol._write_immutable(
        destination,
        {
            "schema": protocol.SPENT_AUTHORITY_SCHEMA,
            "protocol_id": protocol.PROTOCOL_ID,
            "generated_at": generated_at,
            "state": "COMPLETE_COMPOSED_SPENT_AUTHORITY",
            "predecessor_sources": {
                "sfir1_comprehensive_spent": protocol.exact_ref(root, spent_path),
                "sfir1_design_charter": protocol.exact_ref(root, charter_path),
                "sfir1_terminal_failure": protocol.exact_ref(root, failure_path),
            },
            "derivation": derivation,
            "reserved_sfir1_declared_roots": {
                "git_docs": sorted(reserved_git),
                "regulation_ecfr": [],
                "encyclopedia_wikipedia": sorted(reserved_wiki),
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
    parser.add_argument("--sfir1-spent", type=Path, required=True)
    parser.add_argument("--sfir1-charter", type=Path, required=True)
    parser.add_argument("--sfir1-failure", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--generated-at", required=True)
    args = parser.parse_args(argv)
    refs = [
        protocol.exact_ref(args.root, path)
        for path in (args.sfir1_spent, args.sfir1_charter, args.sfir1_failure)
    ]
    path = compose_spent_authority(args.root, *refs, args.destination, args.generated_at)
    print(path.as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
