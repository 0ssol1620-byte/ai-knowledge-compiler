#!/usr/bin/env python3
"""Freeze SFIR4's deterministic roster and closed post-capacity protocol."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

NS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(NS))
sys.path.insert(0, str(NS / "tools"))

import sfir4_core_conformance as conformance  # noqa: E402
import sfir4_execution as sx  # noqa: E402
import sfir4_execution_closure as closure  # noqa: E402
import sfir4_protocol as protocol  # noqa: E402
from acquisition import sources_sfir4 as sources  # noqa: E402


def _ref(root: Path, path: Path) -> dict[str, str]:
    return protocol.exact_ref(root, path)


def _resolved(root: Path, ref: Mapping[str, Any]) -> Path:
    return protocol._resolve_ref(root, ref)


def _candidate_order(family: str, row: Mapping[str, Any]) -> tuple[str, str]:
    material = "\0".join(
        (sources.SELECTION_SALT, protocol.PROTOCOL_ID, family, str(row["lineage_id"]))
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest(), str(row["lineage_id"])


def _verified_inputs(
    root: Path,
    charter_ref: Mapping[str, Any],
    capacity_ref: Mapping[str, Any],
    spent_ref: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], Path, dict[str, Any]]:
    charter = protocol.verify_authority(root, charter_ref, protocol.CHARTER_SCHEMA)
    capacity = protocol.verify_authority(root, capacity_ref, protocol.CAPACITY_SCHEMA)
    spent = protocol.verify_spent_authority(root, spent_ref)
    if (
        capacity.get("state") != "CAPACITY_PASS"
        or capacity.get("formula") != "Q_f=min(1000,floor(0.8*C_f))"
        or capacity.get("charter") != dict(charter_ref)
        or capacity.get("spent_identity_authority") != dict(spent_ref)
    ):
        raise protocol.SFIR4Refused("capacity authority upstream bindings drifted")
    metadata_ref = capacity.get("metadata")
    if not isinstance(metadata_ref, Mapping):
        raise protocol.SFIR4Refused("capacity authority has no exact metadata reference")
    metadata_path = _resolved(root, metadata_ref)
    if _ref(root, metadata_path) != dict(metadata_ref):
        raise protocol.SFIR4Refused("capacity metadata digest moved")
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise protocol.SFIR4Refused("capacity metadata cannot be read exactly") from error
    protocol._assert_metadata_only(metadata)
    if (
        not isinstance(metadata, dict)
        or metadata.get("schema") != protocol.CAPACITY_INPUT_SCHEMA
        or metadata.get("protocol_id") != protocol.PROTOCOL_ID
        or not isinstance(metadata.get("families"), dict)
        or set(metadata["families"]) != set(sources.FAMILIES)
    ):
        raise protocol.SFIR4Refused("capacity metadata top-level contract drifted")
    return charter, capacity, spent, metadata_path, metadata


def _selected_roster(
    capacity: Mapping[str, Any],
    spent: Mapping[str, Any],
    metadata: Mapping[str, Any],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, int]]:
    quotas = capacity.get("Q")
    counts = capacity.get("C")
    if (
        not isinstance(quotas, Mapping)
        or set(quotas) != set(sources.FAMILIES)
        or not isinstance(counts, Mapping)
        or set(counts) != set(sources.FAMILIES)
    ):
        raise protocol.SFIR4Refused("capacity family C/Q domain drifted")
    spent_ids = {
        str(value) for key in ("container_ids", "lineage_ids", "alias_ids") for value in spent[key]
    }
    selected: dict[str, list[dict[str, Any]]] = {}
    capability_counts = {name: 0 for name in sources.CAPABILITY_ENDPOINTS}
    global_ids: set[str] = set()
    for family in sources.FAMILIES:
        block = metadata["families"].get(family)
        if not isinstance(block, Mapping):
            raise protocol.SFIR4Refused(f"{family} metadata block is malformed")
        candidates = block.get("candidates")
        dispositions = block.get("root_dispositions")
        if not isinstance(candidates, list) or not isinstance(dispositions, list):
            raise protocol.SFIR4Refused(f"{family} candidate/disposition domain is malformed")
        declared = {
            sources.discovery_root_id(family, root_id) for root_id in sources.declared_roots(family)
        }
        disposition_roots = [
            row.get("discovery_root_id") for row in dispositions if isinstance(row, Mapping)
        ]
        if len(dispositions) != len(declared) or set(disposition_roots) != declared:
            raise protocol.SFIR4Refused(f"{family} dispositions do not cover exact roots")
        if any(
            not isinstance(row, Mapping)
            or row.get("state")
            not in {
                "COMPLETE",
                "EXCLUDED_INCOMPLETE_ROOT_DISPOSITION",
                "UNAVAILABLE_ROOT_DISPOSITION",
                "ZERO_CANDIDATE_ROOT_DISPOSITION",
            }
            for row in dispositions
        ):
            raise protocol.SFIR4Refused(f"{family} disposition state is malformed")
        complete = {
            str(row["discovery_root_id"])
            for row in dispositions
            if isinstance(row, Mapping) and row.get("state") == "COMPLETE"
        }
        identities: set[str] = set()
        for row in candidates:
            if not isinstance(row, Mapping):
                raise protocol.SFIR4Refused(f"{family} candidate is not an object")
            protocol._validate_candidate(family, row, declared, spent_ids)
            if row.get("discovery_root_id") not in complete:
                raise protocol.SFIR4Refused(f"{family} incomplete root contributed a candidate")
            normalized = {
                value.casefold()
                for value in (
                    str(row["container_id"]),
                    str(row["lineage_id"]),
                    *(str(value) for value in row["alias_ids"]),
                )
            }
            if normalized & identities or normalized & global_ids:
                raise protocol.SFIR4Refused("capacity identity domains collide")
            identities.update(normalized)
            global_ids.update(normalized)
        quota = quotas[family]
        count = counts[family]
        per_root_key = {
            "git_docs": "max_candidates_per_repository",
            "regulation_ecfr": "max_candidates_per_title",
            "encyclopedia_wikipedia": "max_candidates_per_category",
        }[family]
        if any(
            sum(row["discovery_root_id"] == root_id for row in candidates)
            > sources.SOURCE_POOLS[family][per_root_key]
            for root_id in declared
        ):
            raise protocol.SFIR4Refused(f"{family} per-root candidate cap drifted")
        expected_arithmetic = {
            "complete_roots": len(complete),
            "excluded_or_unavailable_roots": len(declared) - len(complete),
            "candidates_from_complete_roots": len(candidates),
            "candidates_from_incomplete_roots": 0,
        }
        if (
            isinstance(quota, bool)
            or not isinstance(quota, int)
            or isinstance(count, bool)
            or not isinstance(count, int)
            or count != len(candidates)
            or quota != min(1000, (8 * count) // 10)
            or count < 750
            or quota < 600
            or capacity.get("root_disposition_arithmetic", {}).get(family) != expected_arithmetic
        ):
            raise protocol.SFIR4Refused(f"{family} capacity C/Q arithmetic drifted")
        ordered = sorted(
            (dict(row) for row in candidates),
            key=lambda row: _candidate_order(family, row),
        )
        rows = ordered[:quota]
        if len(rows) != quota:
            raise protocol.SFIR4Refused(f"{family} cannot fill exact sealed quota")
        for row in rows:
            for endpoint in sources.CAPABILITY_ENDPOINTS:
                capability_counts[endpoint] += int(row["capability_exercise"][endpoint])
        selected[family] = rows
    if (
        sum(map(len, selected.values())) < sx.MIN_TOTAL
        or sum(len(rows) >= sx.MIN_PER_FAMILY for rows in selected.values()) < sx.MIN_FAMILIES
        or any(value < sx.MIN_EXERCISING for value in capability_counts.values())
    ):
        raise protocol.SFIR4Refused("deterministic roster misses frozen analysis floors")
    return selected, capability_counts


def freeze_roster(
    root: Path,
    charter_ref: Mapping[str, Any],
    capacity_ref: Mapping[str, Any],
    spent_ref: Mapping[str, Any],
    destination: Path,
    generated_at: str,
) -> Path:
    # Before anything is sealed: is the instrument being frozen recoverable at
    # all?  INC-V2-089 lost 29 files that 20 receipts pinned, because the whole
    # research tree was untracked and a pin over unrecoverable bytes is a
    # statement with nothing behind it.  A freeze that cannot be reproduced is
    # not a freeze.
    closure.require_recoverable()
    # And: is the Protected Core that would actually import the one whose
    # semantics the paper claims?  A revision can be clean, committed and
    # byte-identical and still not implement the algorithm under study --
    # 79dd3b7 is exactly that.  Recoverability and conformance are separate
    # questions and a freeze needs both.
    conformance.require_conformant()
    _, capacity, spent, metadata_path, metadata = _verified_inputs(
        root, charter_ref, capacity_ref, spent_ref
    )
    selected, capability_counts = _selected_roster(capacity, spent, metadata)
    return protocol.write_immutable(
        destination,
        {
            "schema": protocol.ROSTER_SCHEMA,
            "protocol_id": protocol.PROTOCOL_ID,
            "generated_at": generated_at,
            "state": "LINEAGE_ROSTER_FROZEN",
            "charter": dict(charter_ref),
            "capacity": dict(capacity_ref),
            "spent_identity_authority": dict(spent_ref),
            "metadata": _ref(root, metadata_path),
            "ordering": (
                "sha256(selection_salt + NUL + protocol_id + NUL + family + NUL "
                "+ lineage_id),ascending"
            ),
            "Q": dict(capacity["Q"]),
            "capability_exercising_counts": capability_counts,
            "families": selected,
        },
    )


def _verify_execution_manifest(root: Path, path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise protocol.SFIR4Refused("execution manifest is absent")
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise protocol.SFIR4Refused("execution manifest is unreadable") from error
    if (
        not isinstance(body, dict)
        or body.get("schema") != sx.EXECUTION_TOOLCHAIN_SCHEMA
        or body.get("protocol_id") != protocol.PROTOCOL_ID
        or not isinstance(body.get("generated_at"), str)
        or not body["generated_at"]
        or body.get("content_digest")
        != sx.canonical_sha({key: value for key, value in body.items() if key != "content_digest"})
        or body != sx.execution_toolchain_manifest(body["generated_at"])
    ):
        raise protocol.SFIR4Refused("execution manifest is not the exact current closed tree")
    return body


def freeze_protocol(
    root: Path,
    protocol_yaml: Path,
    charter_ref: Mapping[str, Any],
    capacity_ref: Mapping[str, Any],
    roster_ref: Mapping[str, Any],
    spent_ref: Mapping[str, Any],
    execution_manifest: Path,
    destination: Path,
    generated_at: str,
) -> Path:
    # Before anything is sealed: is the instrument being frozen recoverable at
    # all?  INC-V2-089 lost 29 files that 20 receipts pinned, because the whole
    # research tree was untracked and a pin over unrecoverable bytes is a
    # statement with nothing behind it.  A freeze that cannot be reproduced is
    # not a freeze.
    closure.require_recoverable()
    # And: is the Protected Core that would actually import the one whose
    # semantics the paper claims?  A revision can be clean, committed and
    # byte-identical and still not implement the algorithm under study --
    # 79dd3b7 is exactly that.  Recoverability and conformance are separate
    # questions and a freeze needs both.
    conformance.require_conformant()
    _, capacity, spent, metadata_path, metadata = _verified_inputs(
        root, charter_ref, capacity_ref, spent_ref
    )
    roster = protocol.verify_authority(root, roster_ref, protocol.ROSTER_SCHEMA)
    expected_families, expected_capabilities = _selected_roster(capacity, spent, metadata)
    if (
        roster.get("state") != "LINEAGE_ROSTER_FROZEN"
        or roster.get("charter") != dict(charter_ref)
        or roster.get("capacity") != dict(capacity_ref)
        or roster.get("spent_identity_authority") != dict(spent_ref)
        or roster.get("metadata") != _ref(root, metadata_path)
        or roster.get("Q") != capacity.get("Q")
        or roster.get("families") != expected_families
        or roster.get("capability_exercising_counts") != expected_capabilities
    ):
        raise protocol.SFIR4Refused("roster does not reconstruct from exact capacity metadata")
    document = yaml.safe_load(protocol_yaml.read_text(encoding="utf-8"))
    if (
        not isinstance(document, dict)
        or document.get("schema") != "tavonel.sfir4.protocol.v1"
        or document.get("protocol_id") != protocol.PROTOCOL_ID
        or document.get("state") != "PROSPECTIVE_POST_CAPACITY"
        or document.get("result_blind_design") is not True
        or document.get("authority_requirements")
        != {
            "charter": protocol.CHARTER_SCHEMA,
            "capacity": protocol.CAPACITY_SCHEMA,
            "roster": protocol.ROSTER_SCHEMA,
            "spent_identity": protocol.SPENT_SCHEMA,
            "execution_manifest": sx.EXECUTION_TOOLCHAIN_SCHEMA,
            "exact_path_sha256_and_content_digest": True,
            "no_glob_latest_or_newest": True,
        }
        or document.get("capacity")
        != {
            "quota_formula": "Q_f=min(1000,floor(0.8*C_f))",
            "minimum_C_per_family": 750,
            "minimum_Q_per_family": 600,
            "complete_root_dispositions_only": True,
            "exhaustive_finite_roots": True,
        }
        or document.get("analysis_floor")
        != {
            "total_pairs": 300,
            "families": 3,
            "per_family_pairs": 60,
            "exercising_minimum": {"E5": 29, "E6": 29, "E9": 29},
        }
        or document.get("execution")
        != {
            "acquisition_authorized_after_protocol_freeze": True,
            "acquisition_max_workers": 2,
            "acquisition_in_flight_per_worker": 2,
            "scoring_authorized_at_protocol_freeze": False,
            "score_exactly_once": True,
            "scoring_requires_exactly_once_acquisition_authority": True,
            "corpus_spent_on_first_payload_read": True,
            "non_scorable_means_unscored": True,
            "acceptance_requires_exact_pass": True,
            "gpu_before_primary_pass": "forbidden",
        }
    ):
        raise protocol.SFIR4Refused("post-capacity protocol semantics drifted")
    manifest = _verify_execution_manifest(root, execution_manifest)
    manifest_ref = {
        **_ref(root, execution_manifest),
        "content_digest": manifest["content_digest"],
        "schema": manifest["schema"],
    }
    return protocol.write_immutable(
        destination,
        {
            "schema": protocol.PROTOCOL_FREEZE_SCHEMA,
            "protocol_id": protocol.PROTOCOL_ID,
            "generated_at": generated_at,
            "state": "PROTOCOL_FROZEN",
            "protocol": _ref(root, protocol_yaml),
            "charter": dict(charter_ref),
            "capacity": dict(capacity_ref),
            "roster": dict(roster_ref),
            "spent_identity_authority": dict(spent_ref),
            "execution_manifest": manifest_ref,
            "acquisition_authorized": True,
            "scoring_authorized": False,
            "score_exactly_once": True,
            "scoring_requires_exactly_once_acquisition_authority": True,
        },
    )


def _parse_ref(value: str) -> dict[str, str]:
    path, separator, digest = value.partition("#")
    if not separator:
        raise argparse.ArgumentTypeError("exact refs use PATH#sha256:HEX")
    return {"path": path, "sha256": digest}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    roster = subparsers.add_parser("roster")
    freeze = subparsers.add_parser("protocol")
    for command in (roster, freeze):
        command.add_argument("--root", type=Path, default=sx.ROOT)
        command.add_argument("--charter", type=_parse_ref, required=True)
        command.add_argument("--capacity", type=_parse_ref, required=True)
        command.add_argument("--spent", type=_parse_ref, required=True)
        command.add_argument("--destination", type=Path, required=True)
        command.add_argument("--generated-at", required=True)
    freeze.add_argument("--roster", type=_parse_ref, required=True)
    freeze.add_argument("--protocol-yaml", type=Path, required=True)
    freeze.add_argument("--execution-manifest", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "roster":
            output = freeze_roster(
                args.root,
                args.charter,
                args.capacity,
                args.spent,
                args.destination,
                args.generated_at,
            )
        else:
            output = freeze_protocol(
                args.root,
                args.protocol_yaml,
                args.charter,
                args.capacity,
                args.roster,
                args.spent,
                args.execution_manifest,
                args.destination,
                args.generated_at,
            )
        print(json.dumps({"state": "SEALED", "path": sx.relative(output)}, indent=2))
        return 0
    except protocol.SFIR4Refused as error:
        print(json.dumps({"state": "REFUSED", "why": str(error)}, indent=2), file=sys.stderr)
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
