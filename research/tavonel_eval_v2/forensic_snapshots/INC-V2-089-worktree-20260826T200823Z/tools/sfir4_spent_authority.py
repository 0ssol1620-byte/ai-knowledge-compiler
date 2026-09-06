"""Compose SFIR4 spent identities from the exact terminal SFIR3 chain."""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import sfir4_protocol as protocol
from acquisition import sources_sfir4 as sources

SFIR3_SPENT_SHA256 = "sha256:e9feb8678061b92ee41b524e5ea147a0d75455846ddd9bc2f3443b64e849f337"
SFIR3_CHARTER_SHA256 = "sha256:4a798d09ea02ac98b57593e6795e021313ca6650eb611dfe481490ece8d413be"
SFIR3_FAILURE_SHA256 = "sha256:531773f0aa1877f82e324611383cc69d29b9ca5a699b63ca68299953548d7273"


def _load_exact(
    root: Path, ref: Mapping[str, Any], digest: str, schema: str
) -> tuple[Path, dict[str, Any]]:
    path = protocol._resolve_ref(root, ref)
    if ref.get("sha256") != digest or protocol.sha_file(path) != digest:
        raise protocol.SFIR4Refused("wrong frozen SFIR3 predecessor digest")
    body = json.loads(path.read_text(encoding="utf-8"))
    if body.get("schema") != schema:
        raise protocol.SFIR4Refused("wrong frozen SFIR3 predecessor schema")
    return path, body


def compose_spent_authority(
    root: Path,
    sfir3_spent_ref: Mapping[str, Any],
    sfir3_charter_ref: Mapping[str, Any],
    sfir3_failure_ref: Mapping[str, Any],
    destination: Path,
    generated_at: str,
) -> Path:
    spent_path, spent = _load_exact(
        root, sfir3_spent_ref, SFIR3_SPENT_SHA256, "tavonel.sfir3.spent_identity_authority.v1"
    )
    charter_path, _ = _load_exact(
        root, sfir3_charter_ref, SFIR3_CHARTER_SHA256, "tavonel.sfir3.design_charter_freeze.v1"
    )
    failure_path, failure = _load_exact(
        root, sfir3_failure_ref, SFIR3_FAILURE_SHA256, "tavonel.sfir3.capacity_probe_failure.v1"
    )
    expected = {
        "protocol_id": "SOURCE_FACT_IR_INDEPENDENT_REPLICATION_V3",
        "state": "TERMINAL_PRE_PAYLOAD_CAPACITY_INSTRUMENT_REFUSAL",
        "reason": "FROZEN_GIT_TREE_METADATA_CONTENT_LENGTH_EXCEEDS_BOUND",
        "failure_stage": "GIT_DOCS_FAMILY_BEFORE_FAMILY_EXIT",
        "exact_root_unknown": True,
        "capacity_metadata_written": False,
        "payload_opened": False,
        "diff_opened": False,
        "source_fact_computed": False,
        "endpoint_outcome_computed": False,
        "score_attempted": False,
    }
    if any(failure.get(k) != v for k, v in expected.items()) or failure.get(
        "families_not_reached"
    ) != ["regulation_ecfr", "encyclopedia_wikipedia"]:
        raise protocol.SFIR4Refused("SFIR3 failure is not the exact pre-payload terminal state")
    if failure.get("charter") != dict(sfir3_charter_ref) or failure.get(
        "spent_identity_authority"
    ) != dict(sfir3_spent_ref):
        raise protocol.SFIR4Refused("SFIR3 predecessor cross-bindings drifted")
    containers = set(spent.get("container_ids") or [])
    lineages = set(spent.get("lineage_ids") or [])
    aliases = set(spent.get("alias_ids") or [])
    if not containers or not lineages or not aliases:
        raise protocol.SFIR4Refused("SFIR3 comprehensive spent authority is incomplete")
    sources.assert_disjoint_from_comprehensive_spent(containers, aliases)
    reserved_git = [sources.discovery_root_id("git_docs", repo) for repo in sources.SFIR3_GIT_ROOTS]
    containers.update(reserved_git)
    return protocol.write_immutable(
        destination,
        {
            "schema": protocol.SPENT_SCHEMA,
            "protocol_id": protocol.PROTOCOL_ID,
            "generated_at": generated_at,
            "state": "COMPLETE_COMPOSED_SPENT_AUTHORITY",
            "predecessor_sources": {
                "sfir3_comprehensive_spent": protocol.exact_ref(root, spent_path),
                "sfir3_design_charter": protocol.exact_ref(root, charter_path),
                "sfir3_terminal_failure": protocol.exact_ref(root, failure_path),
            },
            "derivation": {
                "failure_stage": expected["failure_stage"],
                "failure_reason": expected["reason"],
                "exact_root_unknown": True,
                "reserve_all_sfir3_git_roots": True,
                "reserve_unreached_sfir3_wikipedia_roots": False,
                "reserve_unreached_ecfr_title_part_wildcard": False,
            },
            "reserved_sfir3_declared_roots": {
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
    parser.add_argument("--sfir3-spent", type=Path, required=True)
    parser.add_argument("--sfir3-charter", type=Path, required=True)
    parser.add_argument("--sfir3-failure", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--generated-at", required=True)
    args = parser.parse_args(argv)
    refs = [
        protocol.exact_ref(args.root, path)
        for path in (args.sfir3_spent, args.sfir3_charter, args.sfir3_failure)
    ]
    path = compose_spent_authority(args.root, *refs, args.destination, args.generated_at)
    print(path.as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
