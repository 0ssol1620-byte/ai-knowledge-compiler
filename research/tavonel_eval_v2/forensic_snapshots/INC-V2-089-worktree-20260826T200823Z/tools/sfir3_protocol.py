"""Fail-closed authority chain for the fresh SFIR3 independent replication."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

try:
    from acquisition import sources_sfir3 as sources
except ImportError:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from acquisition import sources_sfir3 as sources

PROTOCOL_ID = sources.PROTOCOL_ID
CHARTER_SCHEMA = "tavonel.sfir3.design_charter_freeze.v1"
CAPACITY_INPUT_SCHEMA = "tavonel.sfir3.capacity_metadata.v1"
CAPACITY_SCHEMA = "tavonel.sfir3.capacity_census_authority.v1"
SPENT_AUTHORITY_SCHEMA = "tavonel.sfir3.spent_identity_authority.v1"
ROSTER_SCHEMA = "tavonel.sfir3.lineage_freeze.v1"
PROTOCOL_FREEZE_SCHEMA = "tavonel.sfir3.protocol_freeze.v1"
SHA_PREFIX = "sha256:"
FORBIDDEN_KEYS = frozenset(
    {
        "payload",
        "payload_bytes",
        "text",
        "content",
        "diff",
        "sourcefacts",
        "source_facts",
        "endpoint_outcome",
        "score",
        "verdict",
    }
)


class SFIR3Refused(RuntimeError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def digest(value: Any) -> str:
    return SHA_PREFIX + hashlib.sha256(canonical_bytes(value)).hexdigest()


def sha_file(path: Path) -> str:
    return SHA_PREFIX + hashlib.sha256(path.read_bytes()).hexdigest()


def _content_digest(body: Mapping[str, Any]) -> str:
    return digest({k: v for k, v in body.items() if k != "content_sha256"})


def _assert_metadata_only(value: Any, trail: tuple[str, ...] = ()) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            token = str(key).casefold()
            if token in FORBIDDEN_KEYS:
                raise SFIR3Refused(
                    f"forbidden field during capacity census: {'.'.join((*trail, str(key)))}"
                )
            _assert_metadata_only(nested, (*trail, str(key)))
    elif isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            _assert_metadata_only(nested, (*trail, str(index)))


def _relative(root: Path, path: Path) -> str:
    resolved_root, resolved = root.resolve(), path.resolve()
    try:
        return resolved.relative_to(resolved_root).as_posix()
    except ValueError as error:
        raise SFIR3Refused("authority subject escaped repository root") from error


def exact_ref(root: Path, path: Path, expected_sha256: str | None = None) -> dict[str, str]:
    actual = sha_file(path)
    if expected_sha256 is not None and actual != expected_sha256:
        raise SFIR3Refused(f"explicit digest mismatch for {_relative(root, path)}")
    return {"path": _relative(root, path), "sha256": actual}


def _resolve_ref(root: Path, ref: Mapping[str, Any]) -> Path:
    if set(ref) != {"path", "sha256"} or not isinstance(ref.get("path"), str):
        raise SFIR3Refused("exact authority reference is malformed")
    path = (root / str(ref["path"])).resolve()
    _relative(root, path)
    if not path.is_file() or sha_file(path) != ref["sha256"]:
        raise SFIR3Refused(f"authority reference missing or drifted: {ref.get('path')}")
    return path


def verify_authority(
    root: Path, path: Path, expected_sha256: str, expected_schema: str
) -> dict[str, Any]:
    if sha_file(path) != expected_sha256:
        raise SFIR3Refused("authority digest mismatch")
    body = json.loads(path.read_text(encoding="utf-8"))
    if body.get("schema") != expected_schema or body.get("protocol_id") != PROTOCOL_ID:
        raise SFIR3Refused("authority schema or protocol mismatch")
    if body.get("content_sha256") != _content_digest(body):
        raise SFIR3Refused("authority content digest mismatch")
    return body


def _write_immutable(path: Path, body: Mapping[str, Any]) -> Path:
    if path.exists():
        raise SFIR3Refused(f"immutable destination already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    complete = dict(body)
    complete["content_sha256"] = _content_digest(complete)
    payload = json.dumps(complete, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(path, flags)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(payload)
    return path


def _tool_ref(root: Path, relative: str) -> dict[str, str]:
    path = root / relative
    if not path.is_file():
        raise SFIR3Refused(f"required tool is missing: {relative}")
    return exact_ref(root, path)


def _verify_charter_toolchain(root: Path, charter: Mapping[str, Any]) -> None:
    expected = {"sources_sfir3", "probe_sfir3_capacity", "sfir3_spent_authority"}
    if set(charter.get("toolchain", {})) != expected:
        raise SFIR3Refused("charter toolchain component set drifted")
    for ref in charter["toolchain"].values():
        _resolve_ref(root, ref)


def freeze_design_charter(
    root: Path, charter_yaml: Path, destination: Path, generated_at: str
) -> Path:
    charter = yaml.safe_load(charter_yaml.read_text(encoding="utf-8"))
    if (
        charter.get("schema") != "tavonel.sfir3.pre_census_design_charter.v1"
        or charter.get("protocol_id") != PROTOCOL_ID
    ):
        raise SFIR3Refused("wrong SFIR3 charter")
    if charter.get("status") != "DRAFT_PRE_CENSUS" or charter.get("result_blind") is not True:
        raise SFIR3Refused("charter is not prospectively result blind")
    if charter["capacity_rule"] != {
        "formula": "Q_f=min(1000,floor(0.8*C_f))",
        "minimum_c_per_family": 750,
        "minimum_q_per_family": 600,
    }:
        raise SFIR3Refused("capacity rule drifted")
    if charter["analysis_floor"] != {
        "total_pairs": 300,
        "families": 3,
        "per_family_pairs": 60,
        "capability_exercising_pairs": {"E5": 29, "E6": 29, "E9": 29},
    }:
        raise SFIR3Refused("analysis floor drifted")
    if charter.get("family_authorities") != dict(sources.FAMILY_AUTHORITIES):
        raise SFIR3Refused("family authority bindings drifted")
    if charter.get("candidate_fields") != list(sources.CANDIDATE_FIELDS):
        raise SFIR3Refused("candidate field contract drifted")
    expected_pagination = {
        key: list(value) if isinstance(value, tuple) else value
        for key, value in sources.PAGINATION_CONTRACT.items()
    }
    if charter.get("pagination_contract") != expected_pagination:
        raise SFIR3Refused("pagination policy drifted")
    if charter.get("prospective_root_policy") != {
        "continue_as_zero_candidate": [
            "HTTP_404",
            "HTTP_409",
            "HTTP_451",
            "UNAVAILABLE_ROOT",
            "TRUNCATED_OR_INCOMPLETE_ENUMERATION",
            "SNAPSHOT_DRIFT_DURING_ENUMERATION",
        ],
        "terminal_refusal": [
            "AUTHENTICATED_HTTP_401",
            "AUTHENTICATED_HTTP_403",
            "RATE_LIMIT_EXHAUSTION",
            "MALFORMED_RESPONSE",
            "UNKNOWN_PARTIAL_STATE",
        ],
        "zero_schema": "ZERO_CANDIDATE_ROOT_DISPOSITION",
        "count_rule": "C counts candidates only from roots dispositioned COMPLETE",
        "exhaustive_dispositions_required": True,
        "response_and_snapshot_refs_required": True,
    }:
        raise SFIR3Refused("prospective root failure policy drifted")
    if charter.get("resource_bounds") != {
        "metadata_response_bytes": sources.MAX_METADATA_RESPONSE_BYTES,
        "metadata_read_block_bytes": sources.METADATA_READ_BLOCK_BYTES,
        "ecfr_version_records_per_title": sources.SOURCE_POOLS["regulation_ecfr"][
            "max_version_records_per_title"
        ],
        "ecfr_version_aggregate_state_bytes": sources.MAX_ECFR_VERSION_AGGREGATE_STATE_BYTES,
        "acquisition_payload_bytes": 2_000_000,
        "acquisition_max_workers": 16,
        "acquisition_in_flight_per_worker": 2,
        "acquisition_payload_cache_total_bytes": 16 * 1024 * 1024 * 1024,
        "observation_spool_total_bytes": 8 * 1024 * 1024 * 1024,
        "scientific_evidence_per_file_bytes": 32 * 1024 * 1024,
        "ecfr_raw_part_bytes": 256 * 1024 * 1024,
        "ecfr_total_cache_bytes": 8 * 1024 * 1024 * 1024,
    }:
        raise SFIR3Refused("resource bounds drifted")
    endpoint = charter.get("endpoint_rule", {})
    if (
        endpoint.get("primary_exercised_and_met")
        != ["E1", "E2", "E3", "E4", "E5", "E6", "E7", "E9"]
        or endpoint.get("veto_only") != "E8"
        or endpoint.get("E8_required_violations") != 0
        or endpoint.get("no_skip") != ["E5", "E6", "E9"]
    ):
        raise SFIR3Refused("endpoint contract drifted")
    if charter.get("spent_identity_rule") != {
        "exact_predecessors": [
            "sfir2 comprehensive spent authority",
            "sfir2 frozen charter",
            "sfir2 terminal failure receipt",
        ],
        "spent_receipt_sha256": "sha256:89806ddf659e3bb296fbb3e3eaece4e11d6d669ad7598ad71b4e49b140c46d31",
        "charter_receipt_sha256": "sha256:d54ef39bc569ab1482655fadd83e54bf07c6c212f719ec6e5a2172b6585e6a31",
        "failure_receipt_sha256": "sha256:83b43161d056087318aa02d24c8621688b38881b254f12949f8e73caa242dbde",
        "reserve_all_sfir2_git_roots": True,
        "reserve_unreached_sfir2_wikipedia_roots": False,
        "reserve_unreached_ecfr_title_part_wildcard": False,
        "families_not_reached": ["regulation_ecfr", "encyclopedia_wikipedia"],
        "full_historical_disjointness_required": True,
    }:
        raise SFIR3Refused("spent identity predecessor contract drifted")
    if charter.get("stopping_rules") != [
        "any pre-freeze payload, diff, SourceFact, endpoint outcome, or score terminates SFIR3",
        "capacity shortfall terminates SFIR3 without roster, acquisition, score, or GPU",
        "no root, threshold, cap, family, endpoint, or disposition-policy change after charter freeze",
        "malformed or unknown partial metadata terminates rather than becoming zero candidates",
        "Git ancestry pairs with equal or nonmonotonic commit timestamps are deterministically ineligible and skipped, never a root or family refusal",
        "every emitted candidate still requires distinct immutable revisions and strictly increasing canonical UTC timestamps",
    ]:
        raise SFIR3Refused("stopping rules are incomplete")
    expected = {
        "selection_salt": sources.SELECTION_SALT,
        "git_repositories": list(sources.SOURCE_POOLS["git_docs"]["repositories"]),
        "ecfr_titles": list(sources.SOURCE_POOLS["regulation_ecfr"]["titles"]),
        "wikipedia_categories": list(
            sources.SOURCE_POOLS["encyclopedia_wikipedia"]["category_roots"]
        ),
    }
    if charter.get("source_selection") != expected:
        raise SFIR3Refused("charter source selection differs from executable finite pools")
    sources.assert_static_disjointness()
    toolchain = {
        "sources_sfir3": _tool_ref(root, "research/tavonel_eval_v2/acquisition/sources_sfir3.py"),
        "probe_sfir3_capacity": _tool_ref(
            root, "research/tavonel_eval_v2/tools/probe_sfir3_capacity.py"
        ),
        "sfir3_spent_authority": _tool_ref(
            root, "research/tavonel_eval_v2/tools/sfir3_spent_authority.py"
        ),
    }
    return _write_immutable(
        destination,
        {
            "schema": CHARTER_SCHEMA,
            "protocol_id": PROTOCOL_ID,
            "generated_at": generated_at,
            "state": "FROZEN_PRE_CENSUS",
            "charter": exact_ref(root, charter_yaml),
            "charter_digest": digest(charter),
            "toolchain": toolchain,
        },
    )


def verify_spent_authority(root: Path, ref: Mapping[str, Any]) -> dict[str, Any]:
    path = _resolve_ref(root, ref)
    return verify_authority(root, path, str(ref["sha256"]), SPENT_AUTHORITY_SCHEMA)


def verify_execution_manifest_ref(root: Path, ref: Mapping[str, Any]) -> dict[str, Any]:
    if (
        set(ref) != {"path", "sha256", "content_digest", "schema"}
        or ref.get("schema") != "tavonel.sfir3.execution_manifest.v1"
    ):
        raise SFIR3Refused("execution manifest enriched reference malformed")
    path = _resolve_ref(root, {"path": ref["path"], "sha256": ref["sha256"]})
    body = json.loads(path.read_text(encoding="utf-8"))
    if set(body) != {
        "schema",
        "protocol_id",
        "coverage",
        "components",
        "generated_at",
        "content_digest",
    }:
        raise SFIR3Refused("execution manifest body fields drifted")
    expected = digest({key: value for key, value in body.items() if key != "content_digest"})
    if (
        body.get("protocol_id") != PROTOCOL_ID
        or body.get("schema") != ref["schema"]
        or body.get("content_digest") != ref["content_digest"]
        or expected != body.get("content_digest")
    ):
        raise SFIR3Refused("execution manifest enriched reference mismatch")
    if (
        not isinstance(body.get("coverage"), Mapping)
        or not body["coverage"]
        or not isinstance(body.get("components"), Mapping)
        or not body["components"]
    ):
        raise SFIR3Refused("execution manifest coverage or component set missing")
    for component_ref in body["components"].values():
        _resolve_ref(root, component_ref)
    try:
        import sfir3_execution

        if root.resolve() != sfir3_execution.ROOT.resolve():
            raise SFIR3Refused("execution manifest can only be frozen at the repository root")
        generated_at = body.get("generated_at")
        if not isinstance(generated_at, str) or not generated_at:
            raise SFIR3Refused("execution manifest generated_at is missing")
        if body != sfir3_execution.execution_toolchain_manifest(generated_at):
            raise SFIR3Refused("execution manifest is not the exact current closed component set")
    except ImportError as error:
        raise SFIR3Refused("SFIR3 execution manifest verifier is unavailable") from error
    return body


def _validate_candidate(
    family: str, row: Mapping[str, Any], declared_roots: set[str], spent_ids: set[str]
) -> None:
    if set(row) != set(sources.CANDIDATE_FIELDS) or row.get("family") != family:
        raise SFIR3Refused(f"{family} candidate fields drifted")
    discovery = row.get("discovery_root_id")
    if discovery not in declared_roots:
        raise SFIR3Refused(f"{family} candidate escaped declared discovery roots")
    root_container, container, lineage = (
        row.get("root_container_id"),
        row.get("container_id"),
        row.get("lineage_id"),
    )
    aliases = row.get("alias_ids")
    if (
        not all(isinstance(value, str) and value for value in (root_container, container, lineage))
        or not isinstance(aliases, list)
        or any(not isinstance(value, str) or not value for value in aliases)
    ):
        raise SFIR3Refused(f"{family} candidate identities malformed")
    if family in {"git_docs", "encyclopedia_wikipedia"} and root_container != discovery:
        raise SFIR3Refused(f"{family} root identity mismatch")
    if family == "regulation_ecfr" and (
        not str(root_container).startswith("ecfr:") or str(root_container).startswith("ecfr:title:")
    ):
        raise SFIR3Refused("eCFR part root identity malformed")
    identity_domain = {str(root_container), str(container), str(lineage), *aliases}
    if len({value.casefold() for value in aliases}) != len(aliases):
        raise SFIR3Refused(f"{family} aliases are not unique after normalization")
    if {value.casefold() for value in aliases} & {
        str(root_container).casefold(),
        str(container).casefold(),
        str(lineage).casefold(),
    }:
        raise SFIR3Refused(f"{family} alias collides with root/container/lineage")
    if {value.casefold() for value in identity_domain} & {value.casefold() for value in spent_ids}:
        raise SFIR3Refused(f"{family} candidate collides with spent identity")
    for name in ("payload_ref", "revision_id", "revision_timestamp"):
        pair = row.get(name)
        if (
            not isinstance(pair, Mapping)
            or set(pair) != {"before", "after"}
            or any(not isinstance(value, str) or not value for value in pair.values())
        ):
            raise SFIR3Refused(f"{family} {name} malformed")
    revisions, timestamps = row["revision_id"], row["revision_timestamp"]
    if revisions["before"] == revisions["after"] or timestamps["before"] >= timestamps["after"]:
        raise SFIR3Refused(f"{family} revision chronology invalid")
    if not all(
        re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z", value)
        for value in timestamps.values()
    ):
        raise SFIR3Refused(f"{family} revision timestamps are not canonical RFC3339 UTC")
    try:
        parsed_timestamps = {
            side: datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
            for side, value in timestamps.items()
        }
    except ValueError as error:
        raise SFIR3Refused(f"{family} revision timestamp is not a real UTC instant") from error
    if parsed_timestamps["before"] >= parsed_timestamps["after"]:
        raise SFIR3Refused(f"{family} revision timestamps are not strictly increasing")
    flags = row.get("capability_exercise")
    if (
        not isinstance(flags, Mapping)
        or set(flags) != set(sources.CAPABILITY_ENDPOINTS)
        or any(type(value) is not bool for value in flags.values())
    ):
        raise SFIR3Refused(f"{family} capability strata malformed")
    refs = row["payload_ref"]
    if family == "git_docs":
        repository = next(
            (
                value
                for value in sources.SOURCE_POOLS[family]["repositories"]
                if sources.discovery_root_id(family, value) == discovery
            ),
            None,
        )
        prefix = f"git:{repository}:" if repository else ""
        if not prefix or not str(lineage).startswith(prefix):
            raise SFIR3Refused("Git lineage does not bind its declared repository")
        path = str(lineage)[len(prefix) :]
        if (
            container != lineage
            or root_container != discovery
            or aliases
            or not path
            or path.startswith("/")
            or "\\" in path
            or ".." in path.split("/")
            or not path.casefold().endswith(tuple(sources.SOURCE_POOLS[family]["extensions"]))
            or any(not re.fullmatch(r"[0-9a-f]{40}", value) for value in revisions.values())
            or refs
            != {
                side: f"github://{repository}/blob/{revisions[side]}/{path}"
                for side in ("before", "after")
            }
        ):
            raise SFIR3Refused("Git candidate identity/revision/locator binding is invalid")
    elif family == "regulation_ecfr":
        match = re.fullmatch(r"ecfr:title:(\d+)", str(discovery))
        root_match = re.fullmatch(r"ecfr:(\d+):([^:]+)", str(root_container))
        lineage_match = re.fullmatch(r"ecfr:(\d+):([^:]+):([^:]+)", str(lineage))
        if (
            not match
            or not root_match
            or not lineage_match
            or container != lineage
            or aliases
            or match.group(1) != root_match.group(1)
            or match.group(1) != lineage_match.group(1)
            or root_match.group(2) != lineage_match.group(2)
            or any(not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) for value in revisions.values())
            or refs
            != {
                side: (
                    f"ecfr://title/{match.group(1)}/part/{root_match.group(2)}/"
                    f"section/{lineage_match.group(3)}?version={revisions[side]}"
                )
                for side in ("before", "after")
            }
        ):
            raise SFIR3Refused("eCFR candidate identity/revision/locator binding is invalid")
    else:
        lineage_match = re.fullmatch(r"wiki:en:(\d+)", str(lineage))
        if (
            root_container != discovery
            or not lineage_match
            or container != f"wikipedia:en:pageid:{lineage_match.group(1)}"
            or not aliases
            or any(
                not value.startswith("wiki:en:title:")
                or value != value.casefold()
                or not value.removeprefix("wiki:en:title:").strip()
                for value in aliases
            )
            or any(not re.fullmatch(r"\d+", value) for value in revisions.values())
            or refs
            != {
                side: (
                    "mediawiki://en.wikipedia.org/page/"
                    f"{lineage_match.group(1)}/revision/{revisions[side]}"
                )
                for side in ("before", "after")
            }
        ):
            raise SFIR3Refused("Wikipedia candidate identity/revision/locator binding is invalid")


def seal_capacity_census(
    root: Path,
    charter_ref: Mapping[str, Any],
    spent_ref: Mapping[str, Any],
    metadata_path: Path,
    destination: Path,
    generated_at: str,
) -> Path:
    charter_path = _resolve_ref(root, charter_ref)
    charter = verify_authority(root, charter_path, str(charter_ref["sha256"]), CHARTER_SCHEMA)
    _verify_charter_toolchain(root, charter)
    spent = verify_spent_authority(root, spent_ref)
    spent_ids = set(spent["container_ids"]) | set(spent["lineage_ids"]) | set(spent["alias_ids"])
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    _assert_metadata_only(metadata)
    if (
        metadata.get("schema") != CAPACITY_INPUT_SCHEMA
        or metadata.get("protocol_id") != PROTOCOL_ID
    ):
        raise SFIR3Refused("capacity metadata schema mismatch")
    quotas: dict[str, int] = {}
    counts: dict[str, int] = {}
    dispositions: dict[str, int] = {}
    disposition_arithmetic: dict[str, dict[str, int]] = {}
    global_lineages: set[str] = set()
    global_containers: set[str] = set()
    global_aliases: set[str] = set()
    global_subject_ids: set[str] = set()
    for family in sources.FAMILIES:
        block = metadata.get("families", {}).get(family)
        if (
            not isinstance(block, Mapping)
            or block.get("pagination", {}).get("exhausted") is not True
        ):
            raise SFIR3Refused(f"{family} enumeration is not exhaustive")
        declared = {
            sources.discovery_root_id(family, root_id) for root_id in sources.declared_roots(family)
        }
        if block.get("authority") != sources.FAMILY_AUTHORITIES[family]:
            raise SFIR3Refused(f"{family} metadata authority drifted")
        if (
            not isinstance(block.get("response_refs"), list)
            or len(block["response_refs"]) < len(declared)
            or not isinstance(block.get("snapshot_refs"), list)
            or len(block["snapshot_refs"]) != len(declared)
        ):
            raise SFIR3Refused(f"{family} response or snapshot references incomplete")
        rows = block.get("root_dispositions")
        if (
            not isinstance(rows, list)
            or len(rows) != len(declared)
            or {row.get("discovery_root_id") for row in rows if isinstance(row, Mapping)}
            != declared
        ):
            raise SFIR3Refused(f"{family} root dispositions are not exhaustive")
        complete_roots = {
            row["discovery_root_id"] for row in rows if row.get("state") == "COMPLETE"
        }
        zero_roots = {
            row["discovery_root_id"]
            for row in rows
            if row.get("state") == "ZERO_CANDIDATE_ROOT_DISPOSITION"
        }
        allowed_states = {"COMPLETE", "ZERO_CANDIDATE_ROOT_DISPOSITION"}
        if any(row.get("state") not in allowed_states for row in rows):
            raise SFIR3Refused(f"{family} has nonterminal root disposition")
        for index, row in enumerate(rows):
            if set(row) != {
                "discovery_root_id",
                "state",
                "reason",
                "snapshot_ref",
                "response_refs",
            }:
                raise SFIR3Refused(f"{family} root disposition fields drifted")
            if (
                not isinstance(row.get("snapshot_ref"), str)
                or row["snapshot_ref"] != block["snapshot_refs"][index]
                or not isinstance(row.get("response_refs"), list)
                or not row["response_refs"]
                or any(value not in block["response_refs"] for value in row["response_refs"])
            ):
                raise SFIR3Refused(f"{family} root response/snapshot references drifted")
            reason = row.get("reason")
            if row.get("state") == "COMPLETE" and reason != "ENUMERATION_EXHAUSTED":
                raise SFIR3Refused(f"{family} COMPLETE root lacks exhaustion proof")
            if row.get("state") == "ZERO_CANDIDATE_ROOT_DISPOSITION" and not (
                isinstance(reason, str)
                and (
                    reason
                    in {
                        "UNAVAILABLE_ROOT",
                        "TRUNCATED_OR_INCOMPLETE_ENUMERATION",
                        "SNAPSHOT_DRIFT_DURING_ENUMERATION",
                    }
                    or reason.startswith(("HTTP_404", "HTTP_409", "HTTP_451"))
                )
            ):
                raise SFIR3Refused(
                    f"{family} zero-candidate reason is not prospectively authorized"
                )
        candidates = block.get("candidates")
        if not isinstance(candidates, list):
            raise SFIR3Refused(f"{family} candidates malformed")
        seen_lineages: set[str] = set()
        seen_containers: set[str] = set()
        seen_aliases: set[str] = set()
        for row in candidates:
            if not isinstance(row, Mapping):
                raise SFIR3Refused(f"{family} candidate is not an object")
            _validate_candidate(family, row, declared, spent_ids)
            alias_set = set(row["alias_ids"])
            normalized_aliases = {value.casefold() for value in alias_set}
            normalized_subjects = {
                row["lineage_id"].casefold(),
                row["container_id"].casefold(),
            }
            if (
                len(alias_set) != len(row["alias_ids"])
                or row["lineage_id"] in seen_lineages
                or row["container_id"] in seen_containers
                or alias_set & seen_aliases
                or normalized_aliases & global_subject_ids
                or normalized_subjects & global_aliases
                or normalized_aliases & global_aliases
                or normalized_subjects & global_subject_ids
            ):
                raise SFIR3Refused(f"{family} duplicate lineage/container/alias domain")
            seen_lineages.add(row["lineage_id"])
            seen_containers.add(row["container_id"])
            seen_aliases.update(row["alias_ids"])
            if (
                row["lineage_id"] in global_lineages
                or row["container_id"] in global_containers
                or alias_set & global_aliases
            ):
                raise SFIR3Refused("cross-family duplicate lineage/container/alias domain")
            global_lineages.add(row["lineage_id"])
            global_containers.add(row["container_id"])
            global_aliases.update(alias_set)
            global_aliases.update(normalized_aliases)
            global_subject_ids.update(normalized_subjects)
        eligible = [row for row in candidates if row.get("discovery_root_id") in complete_roots]
        if len(eligible) != len(candidates):
            raise SFIR3Refused(f"{family} counted a candidate from a non-COMPLETE root")
        per_root_cap = {
            "git_docs": "max_candidates_per_repository",
            "regulation_ecfr": "max_candidates_per_title",
            "encyclopedia_wikipedia": "max_candidates_per_category",
        }[family]
        root_counts = {
            root_id: sum(row["discovery_root_id"] == root_id for row in candidates)
            for root_id in declared
        }
        if any(
            value > sources.SOURCE_POOLS[family][per_root_cap] for value in root_counts.values()
        ):
            raise SFIR3Refused(f"{family} per-root candidate cap exceeded")
        count = len(candidates)
        quota = min(1000, math.floor(0.8 * count))
        if count < 750 or quota < 600:
            raise SFIR3Refused(f"{family} capacity shortfall: C={count}, Q={quota}")
        counts[family], quotas[family], dispositions[family] = count, quota, len(rows)
        disposition_arithmetic[family] = {
            "declared_roots": len(declared),
            "complete_roots": len(complete_roots),
            "zero_candidate_roots": len(zero_roots),
            "candidates_from_complete_roots": len(eligible),
            "candidates_from_zero_roots": sum(
                row["discovery_root_id"] in zero_roots for row in candidates
            ),
        }
    return _write_immutable(
        destination,
        {
            "schema": CAPACITY_SCHEMA,
            "protocol_id": PROTOCOL_ID,
            "generated_at": generated_at,
            "state": "CAPACITY_PASS",
            "charter": dict(charter_ref),
            "spent_identity_authority": dict(spent_ref),
            "metadata": exact_ref(root, metadata_path),
            "C": counts,
            "Q": quotas,
            "root_disposition_counts": dispositions,
            "root_disposition_arithmetic": disposition_arithmetic,
            "formula": "Q_f=min(1000,floor(0.8*C_f))",
        },
    )


def _candidate_order(family: str, row: Mapping[str, Any]) -> str:
    material = (
        sources.SELECTION_SALT + "\0" + PROTOCOL_ID + "\0" + family + "\0" + str(row["lineage_id"])
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def freeze_roster(
    root: Path,
    charter_ref: Mapping[str, Any],
    capacity_ref: Mapping[str, Any],
    spent_ref: Mapping[str, Any],
    metadata_path: Path,
    destination: Path,
    generated_at: str,
) -> Path:
    charter_path = _resolve_ref(root, charter_ref)
    charter = verify_authority(root, charter_path, str(charter_ref["sha256"]), CHARTER_SCHEMA)
    _verify_charter_toolchain(root, charter)
    capacity_path = _resolve_ref(root, capacity_ref)
    capacity = verify_authority(root, capacity_path, str(capacity_ref["sha256"]), CAPACITY_SCHEMA)
    if (
        capacity.get("charter") != dict(charter_ref)
        or capacity.get("spent_identity_authority") != dict(spent_ref)
        or capacity.get("metadata") != exact_ref(root, metadata_path)
    ):
        raise SFIR3Refused("capacity authority upstream bindings drifted")
    spent = verify_spent_authority(root, spent_ref)
    spent_ids = set(spent["container_ids"]) | set(spent["lineage_ids"]) | set(spent["alias_ids"])
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if (
        metadata.get("schema") != CAPACITY_INPUT_SCHEMA
        or metadata.get("protocol_id") != PROTOCOL_ID
    ):
        raise SFIR3Refused("roster metadata schema mismatch")
    selected: dict[str, list[dict[str, Any]]] = {}
    global_lineages: set[str] = set()
    global_containers: set[str] = set()
    global_aliases: set[str] = set()
    global_subject_ids: set[str] = set()
    capability_counts = {name: 0 for name in sources.CAPABILITY_ENDPOINTS}
    for family in sources.FAMILIES:
        declared = {
            sources.discovery_root_id(family, root_id) for root_id in sources.declared_roots(family)
        }
        candidates = metadata["families"][family]["candidates"]
        for row in candidates:
            _validate_candidate(family, row, declared, spent_ids)
        quota = capacity["Q"][family]
        ordered = sorted(
            candidates, key=lambda row: (_candidate_order(family, row), row["lineage_id"])
        )
        if len(ordered) < quota:
            raise SFIR3Refused(f"{family} cannot fill sealed quota")
        family_rows = ordered[:quota]
        for row in family_rows:
            aliases = set(row["alias_ids"])
            normalized_aliases = {value.casefold() for value in aliases}
            normalized_subjects = {
                row["lineage_id"].casefold(),
                row["container_id"].casefold(),
            }
            if (
                row["lineage_id"] in global_lineages
                or row["container_id"] in global_containers
                or aliases & global_aliases
                or normalized_aliases & global_subject_ids
                or normalized_subjects & global_aliases
                or normalized_aliases & global_aliases
                or normalized_subjects & global_subject_ids
            ):
                raise SFIR3Refused("cross-family roster identity collision")
            global_lineages.add(row["lineage_id"])
            global_containers.add(row["container_id"])
            global_aliases.update(aliases)
            global_aliases.update(normalized_aliases)
            global_subject_ids.update(normalized_subjects)
            for endpoint in sources.CAPABILITY_ENDPOINTS:
                capability_counts[endpoint] += int(row["capability_exercise"][endpoint])
        selected[family] = family_rows
    if (
        sum(map(len, selected.values())) < 300
        or any(len(rows) < 60 for rows in selected.values())
        or any(value < 29 for value in capability_counts.values())
    ):
        raise SFIR3Refused("deterministic roster misses frozen analysis floors")
    return _write_immutable(
        destination,
        {
            "schema": ROSTER_SCHEMA,
            "protocol_id": PROTOCOL_ID,
            "generated_at": generated_at,
            "state": "LINEAGE_ROSTER_FROZEN",
            "charter": dict(charter_ref),
            "capacity": dict(capacity_ref),
            "spent_identity_authority": dict(spent_ref),
            "metadata": exact_ref(root, metadata_path),
            "ordering": "sha256(selection_salt + NUL + protocol_id + NUL + family + NUL + lineage_id),ascending",
            "Q": dict(capacity["Q"]),
            "capability_exercising_counts": capability_counts,
            "families": selected,
        },
    )


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
    verified_bodies: dict[str, dict[str, Any]] = {}
    for ref, schema in (
        (charter_ref, CHARTER_SCHEMA),
        (capacity_ref, CAPACITY_SCHEMA),
        (roster_ref, ROSTER_SCHEMA),
        (spent_ref, SPENT_AUTHORITY_SCHEMA),
    ):
        path = _resolve_ref(root, ref)
        verified_bodies[schema] = verify_authority(root, path, str(ref["sha256"]), schema)
    protocol_body = yaml.safe_load(protocol_yaml.read_text(encoding="utf-8"))
    if (
        protocol_body.get("protocol_id") != PROTOCOL_ID
        or protocol_body.get("schema") != "tavonel.sfir3.protocol.v1"
    ):
        raise SFIR3Refused("protocol YAML mismatch")
    if protocol_body.get("authority_requirements") != {
        "charter": CHARTER_SCHEMA,
        "capacity": CAPACITY_SCHEMA,
        "roster": ROSTER_SCHEMA,
        "spent_identity": SPENT_AUTHORITY_SCHEMA,
        "execution_manifest": "tavonel.sfir3.execution_manifest.v1",
        "exact_path_sha256_and_content_digest": True,
        "no_glob_latest_or_newest": True,
    }:
        raise SFIR3Refused("protocol authority requirements drifted")
    if protocol_body.get("capacity") != {
        "quota_formula": "Q_f=min(1000,floor(0.8*C_f))",
        "minimum_C_per_family": 750,
        "minimum_Q_per_family": 600,
        "complete_root_dispositions_only": True,
        "exhaustive_finite_roots": True,
        "candidate_fields": list(sources.CANDIDATE_FIELDS),
    }:
        raise SFIR3Refused("protocol capacity contract drifted")
    if protocol_body.get("analysis_floor") != {
        "total_pairs": 300,
        "families": 3,
        "per_family_pairs": 60,
        "exercising_minimum": {"E5": 29, "E6": 29, "E9": 29},
    }:
        raise SFIR3Refused("protocol analysis floor drifted")
    if protocol_body.get("execution") != {
        "acquisition_authorized_after_protocol_freeze": True,
        "scoring_authorized_at_protocol_freeze": False,
        "score_exactly_once": True,
        "scoring_requires_exactly_once_acquisition_authority": True,
        "corpus_spent_on_first_payload_read": True,
        "gpu_before_primary_pass": "forbidden",
    }:
        raise SFIR3Refused("protocol execution contract drifted")
    raw_manifest = json.loads(execution_manifest.read_text(encoding="utf-8"))
    manifest_ref = {
        **exact_ref(root, execution_manifest),
        "content_digest": raw_manifest.get("content_digest"),
        "schema": raw_manifest.get("schema"),
    }
    verify_execution_manifest_ref(root, manifest_ref)
    charter = verified_bodies[CHARTER_SCHEMA]
    capacity = verified_bodies[CAPACITY_SCHEMA]
    roster = verified_bodies[ROSTER_SCHEMA]
    spent = verified_bodies[SPENT_AUTHORITY_SCHEMA]
    _verify_charter_toolchain(root, charter)
    if capacity.get("charter") != dict(charter_ref) or capacity.get(
        "spent_identity_authority"
    ) != dict(spent_ref):
        raise SFIR3Refused("capacity cross-binding mismatch")
    if (
        roster.get("charter") != dict(charter_ref)
        or roster.get("capacity") != dict(capacity_ref)
        or roster.get("spent_identity_authority") != dict(spent_ref)
    ):
        raise SFIR3Refused("roster cross-binding mismatch")
    if roster.get("Q") != capacity.get("Q"):
        raise SFIR3Refused("roster quotas differ from capacity authority")
    metadata_ref = capacity.get("metadata")
    if roster.get("metadata") != metadata_ref or not isinstance(metadata_ref, Mapping):
        raise SFIR3Refused("roster and capacity do not bind one exact metadata census")
    metadata_path = _resolve_ref(root, metadata_ref)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    _assert_metadata_only(metadata)
    if (
        metadata.get("schema") != CAPACITY_INPUT_SCHEMA
        or metadata.get("protocol_id") != PROTOCOL_ID
        or not isinstance(metadata.get("families"), Mapping)
        or set(metadata["families"]) != set(sources.FAMILIES)
        or capacity.get("state") != "CAPACITY_PASS"
        or capacity.get("formula") != "Q_f=min(1000,floor(0.8*C_f))"
    ):
        raise SFIR3Refused("capacity authority or metadata top-level contract drifted")
    spent_ids = set(spent["container_ids"]) | set(spent["lineage_ids"]) | set(spent["alias_ids"])
    expected_capability_counts = {name: 0 for name in sources.CAPABILITY_ENDPOINTS}
    all_subject_ids: set[str] = set()
    all_alias_ids: set[str] = set()
    roster_families = roster.get("families")
    if not isinstance(roster_families, Mapping) or set(roster_families) != set(sources.FAMILIES):
        raise SFIR3Refused("roster family domain drifted")
    for family in sources.FAMILIES:
        declared = {
            sources.discovery_root_id(family, root_id) for root_id in sources.declared_roots(family)
        }
        block = metadata.get("families", {}).get(family, {})
        candidates = block.get("candidates")
        if not isinstance(candidates, list):
            raise SFIR3Refused(f"{family} metadata candidate domain is malformed")
        dispositions = block.get("root_dispositions")
        if (
            block.get("authority") != sources.FAMILY_AUTHORITIES[family]
            or not isinstance(block.get("pagination"), Mapping)
            or block["pagination"].get("exhausted") is not True
            or not isinstance(block.get("response_refs"), list)
            or len(block["response_refs"]) < len(declared)
            or any(not isinstance(value, str) or not value for value in block["response_refs"])
            or not isinstance(block.get("snapshot_refs"), list)
            or len(block["snapshot_refs"]) != len(declared)
            or any(not isinstance(value, str) or not value for value in block["snapshot_refs"])
            or not isinstance(dispositions, list)
            or len(dispositions) != len(declared)
            or {row.get("discovery_root_id") for row in dispositions if isinstance(row, Mapping)}
            != declared
            or any(
                row.get("state") not in {"COMPLETE", "ZERO_CANDIDATE_ROOT_DISPOSITION"}
                for row in dispositions
            )
        ):
            raise SFIR3Refused(f"{family} capacity root arithmetic drifted")
        for index, row in enumerate(dispositions):
            if set(row) != {
                "discovery_root_id",
                "state",
                "reason",
                "snapshot_ref",
                "response_refs",
            }:
                raise SFIR3Refused(f"{family} root disposition fields drifted")
            if (
                row["snapshot_ref"] != block["snapshot_refs"][index]
                or not isinstance(row["response_refs"], list)
                or not row["response_refs"]
                or any(value not in block["response_refs"] for value in row["response_refs"])
            ):
                raise SFIR3Refused(f"{family} root evidence references drifted")
            reason = row.get("reason")
            if row["state"] == "COMPLETE" and reason != "ENUMERATION_EXHAUSTED":
                raise SFIR3Refused(f"{family} COMPLETE root lacks exhaustion proof")
            if row["state"] == "ZERO_CANDIDATE_ROOT_DISPOSITION" and not (
                isinstance(reason, str)
                and (
                    reason
                    in {
                        "UNAVAILABLE_ROOT",
                        "TRUNCATED_OR_INCOMPLETE_ENUMERATION",
                        "SNAPSHOT_DRIFT_DURING_ENUMERATION",
                    }
                    or reason.startswith(("HTTP_404", "HTTP_409", "HTTP_451"))
                )
            ):
                raise SFIR3Refused(f"{family} zero-root reason drifted")
        complete_roots = {
            row["discovery_root_id"] for row in dispositions if row.get("state") == "COMPLETE"
        }
        zero_roots = declared - complete_roots
        for row in candidates:
            _validate_candidate(family, row, declared, spent_ids)
            if row["discovery_root_id"] not in complete_roots:
                raise SFIR3Refused(f"{family} zero root contributed a candidate")
            aliases = {value.casefold() for value in row["alias_ids"]}
            subjects = {
                row["lineage_id"].casefold(),
                row["container_id"].casefold(),
            }
            if (
                aliases & all_alias_ids
                or aliases & all_subject_ids
                or subjects & all_alias_ids
                or subjects & all_subject_ids
            ):
                raise SFIR3Refused("capacity metadata identity domains collide")
            all_alias_ids.update(aliases)
            all_subject_ids.update(subjects)
        quota = capacity.get("Q", {}).get(family)
        if isinstance(quota, bool) or not isinstance(quota, int):
            raise SFIR3Refused(f"{family} capacity quota is malformed")
        count = len(candidates)
        expected_quota = min(1000, math.floor(0.8 * count))
        if (
            capacity.get("C", {}).get(family) != count
            or quota != expected_quota
            or count < 750
            or quota < 600
        ):
            raise SFIR3Refused(f"{family} capacity C/Q arithmetic drifted")
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
            raise SFIR3Refused(f"{family} capacity per-root cap drifted")
        expected_arithmetic = {
            "declared_roots": len(declared),
            "complete_roots": len(complete_roots),
            "zero_candidate_roots": len(zero_roots),
            "candidates_from_complete_roots": count,
            "candidates_from_zero_roots": 0,
        }
        if capacity.get("root_disposition_arithmetic", {}).get(family) != expected_arithmetic:
            raise SFIR3Refused(f"{family} root disposition arithmetic drifted")
        if capacity.get("root_disposition_counts", {}).get(family) != len(declared):
            raise SFIR3Refused(f"{family} root disposition count drifted")
        expected = sorted(
            candidates, key=lambda row: (_candidate_order(family, row), row["lineage_id"])
        )[:quota]
        if roster_families[family] != expected:
            raise SFIR3Refused(f"{family} roster is not the deterministic outcome-blind selection")
        for row in expected:
            for endpoint in sources.CAPABILITY_ENDPOINTS:
                expected_capability_counts[endpoint] += int(row["capability_exercise"][endpoint])
    if roster.get("capability_exercising_counts") != expected_capability_counts:
        raise SFIR3Refused("roster capability arithmetic drifted")
    return _write_immutable(
        destination,
        {
            "schema": PROTOCOL_FREEZE_SCHEMA,
            "protocol_id": PROTOCOL_ID,
            "generated_at": generated_at,
            "state": "PROTOCOL_FROZEN",
            "protocol": exact_ref(root, protocol_yaml),
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


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    verify = sub.add_parser("verify-authority")
    verify.add_argument("--root", type=Path, required=True)
    verify.add_argument("--path", type=Path, required=True)
    verify.add_argument("--sha256", required=True)
    verify.add_argument("--schema", required=True)
    charter = sub.add_parser("freeze-charter")
    charter.add_argument("--root", type=Path, required=True)
    charter.add_argument("--charter", type=Path, required=True)
    charter.add_argument("--destination", type=Path, required=True)
    charter.add_argument("--generated-at", required=True)
    capacity = sub.add_parser("seal-capacity")
    capacity.add_argument("--root", type=Path, required=True)
    capacity.add_argument("--charter", type=Path, required=True)
    capacity.add_argument("--charter-sha256", required=True)
    capacity.add_argument("--spent", type=Path, required=True)
    capacity.add_argument("--spent-sha256", required=True)
    capacity.add_argument("--metadata", type=Path, required=True)
    capacity.add_argument("--destination", type=Path, required=True)
    capacity.add_argument("--generated-at", required=True)
    roster = sub.add_parser("freeze-roster")
    roster.add_argument("--root", type=Path, required=True)
    roster.add_argument("--charter", type=Path, required=True)
    roster.add_argument("--charter-sha256", required=True)
    roster.add_argument("--capacity", type=Path, required=True)
    roster.add_argument("--capacity-sha256", required=True)
    roster.add_argument("--spent", type=Path, required=True)
    roster.add_argument("--spent-sha256", required=True)
    roster.add_argument("--metadata", type=Path, required=True)
    roster.add_argument("--destination", type=Path, required=True)
    roster.add_argument("--generated-at", required=True)
    freeze = sub.add_parser("freeze-protocol")
    freeze.add_argument("--root", type=Path, required=True)
    freeze.add_argument("--protocol", type=Path, required=True)
    freeze.add_argument("--charter", type=Path, required=True)
    freeze.add_argument("--charter-sha256", required=True)
    freeze.add_argument("--capacity", type=Path, required=True)
    freeze.add_argument("--capacity-sha256", required=True)
    freeze.add_argument("--roster", type=Path, required=True)
    freeze.add_argument("--roster-sha256", required=True)
    freeze.add_argument("--spent", type=Path, required=True)
    freeze.add_argument("--spent-sha256", required=True)
    freeze.add_argument("--execution-manifest", type=Path, required=True)
    freeze.add_argument("--destination", type=Path, required=True)
    freeze.add_argument("--generated-at", required=True)
    args = parser.parse_args(argv)
    if args.command == "verify-authority":
        verify_authority(args.root, args.path, args.sha256, args.schema)
        print("OK")
        return 0
    if args.command == "freeze-charter":
        path = freeze_design_charter(args.root, args.charter, args.destination, args.generated_at)
    elif args.command == "seal-capacity":
        path = seal_capacity_census(
            args.root,
            exact_ref(args.root, args.charter, args.charter_sha256),
            exact_ref(args.root, args.spent, args.spent_sha256),
            args.metadata,
            args.destination,
            args.generated_at,
        )
    elif args.command == "freeze-roster":
        path = freeze_roster(
            args.root,
            exact_ref(args.root, args.charter, args.charter_sha256),
            exact_ref(args.root, args.capacity, args.capacity_sha256),
            exact_ref(args.root, args.spent, args.spent_sha256),
            args.metadata,
            args.destination,
            args.generated_at,
        )
    else:
        path = freeze_protocol(
            args.root,
            args.protocol,
            exact_ref(args.root, args.charter, args.charter_sha256),
            exact_ref(args.root, args.capacity, args.capacity_sha256),
            exact_ref(args.root, args.roster, args.roster_sha256),
            exact_ref(args.root, args.spent, args.spent_sha256),
            args.execution_manifest,
            args.destination,
            args.generated_at,
        )
    print(path.as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
