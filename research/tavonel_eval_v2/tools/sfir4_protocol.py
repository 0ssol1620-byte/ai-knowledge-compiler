"""Immutable authority helpers for the separate SFIR4 protocol."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from collections.abc import Mapping
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

PROTOCOL_ID = "SOURCE_FACT_IR_INDEPENDENT_REPLICATION_V4"
SPENT_SCHEMA = "tavonel.sfir4.spent_identity_authority.v1"
CHARTER_SCHEMA = "tavonel.sfir4.design_charter_freeze.v1"
CAPACITY_INPUT_SCHEMA = "tavonel.sfir4.capacity_census_input.v1"
CAPACITY_SCHEMA = "tavonel.sfir4.capacity_census_authority.v1"
ROSTER_SCHEMA = "tavonel.sfir4.lineage_freeze.v1"
PROTOCOL_FREEZE_SCHEMA = "tavonel.sfir4.protocol_freeze.v1"
CAPACITY_INPUT_FIELDS = {"schema", "protocol_id", "families", "response_evidence"}
#: The census carries one hash-chained record of every metadata response it
#: observed.  A URL list says what was asked for; this says what came back.
RESPONSE_EVIDENCE_SCHEMA = "tavonel.sfir4.response_evidence.v1"
CAPACITY_FAMILY_FIELDS = {
    "authority",
    "snapshot_refs",
    "response_refs",
    "root_dispositions",
    "pagination",
    "candidates",
}
CAPACITY_DISPOSITION_FIELDS = {
    "discovery_root_id",
    "state",
    "reason",
    "snapshot_ref",
    "response_refs",
}
GIT_TRAVERSAL_PROOF_FIELDS = {
    "algorithm",
    "queue_exhausted",
    "tree_objects_fetched",
    "api_requests",
    "global_requests_before_root",
    "global_api_requests",
    "response_ref_count",
    "remaining_queue_entries",
    "aggregate_tree_metadata_bytes",
    "discovered_doc_paths",
    "retained_doc_paths",
    "path_to_sha_entries",
    "peak_queue_entries",
    "peak_path_to_sha_entries",
    "history_paths_completed",
}
CAPACITY_PAGINATION_FIELDS = {
    "roots_processed",
    "exhausted",
    "rate_limit_retries",
    "rate_limit_wait_seconds",
    "cap_reached",
}
SFIR3_PREDECESSORS = {
    "sfir3_comprehensive_spent": (
        "research/tavonel_eval_v2/receipts/sfir3-spent-identity-authority.json",
        "sha256:e9feb8678061b92ee41b524e5ea147a0d75455846ddd9bc2f3443b64e849f337",
        "tavonel.sfir3.spent_identity_authority.v1",
    ),
    "sfir3_design_charter": (
        "research/tavonel_eval_v2/receipts/sfir3-design-charter-freeze.json",
        "sha256:4a798d09ea02ac98b57593e6795e021313ca6650eb611dfe481490ece8d413be",
        "tavonel.sfir3.design_charter_freeze.v1",
    ),
    "sfir3_terminal_failure": (
        "research/tavonel_eval_v2/receipts/sfir3-capacity-failure-authority.json",
        "sha256:531773f0aa1877f82e324611383cc69d29b9ca5a699b63ca68299953548d7273",
        "tavonel.sfir3.capacity_probe_failure.v1",
    ),
}


class SFIR4Refused(RuntimeError):
    pass


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def _resolve_ref(root: Path, ref: Mapping[str, Any]) -> Path:
    if set(ref) != {"path", "sha256"} or not str(ref["sha256"]).startswith("sha256:"):
        raise SFIR4Refused("malformed exact reference")
    base = root.resolve()
    path = (base / str(ref["path"])).resolve()
    try:
        path.relative_to(base)
    except ValueError as error:
        raise SFIR4Refused("exact reference escaped repository root") from error
    return path


def exact_ref(root: Path, path: Path) -> dict[str, str]:
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(root.resolve()).as_posix()
    except ValueError as error:
        raise SFIR4Refused("authority path escaped repository root") from error
    return {"path": relative, "sha256": sha_file(resolved)}


def verify_authority(
    root: Path,
    path_or_ref: Path | Mapping[str, Any],
    sha_or_schema: str,
    schema: str | None = None,
) -> dict[str, Any]:
    """Verify either (root, exact_ref, schema) or (root, path, sha, schema)."""
    if isinstance(path_or_ref, Mapping):
        ref, expected_schema = path_or_ref, sha_or_schema
    else:
        if schema is None:
            raise SFIR4Refused("authority schema is required")
        ref, expected_schema = exact_ref(root, path_or_ref), schema
        if ref["sha256"] != sha_or_schema:
            raise SFIR4Refused("exact authority digest differs")
    path = _resolve_ref(root, ref)
    if not path.is_file() or sha_file(path) != ref["sha256"]:
        raise SFIR4Refused("exact authority is absent or changed")
    body = json.loads(path.read_text(encoding="utf-8"))
    if body.get("schema") != expected_schema or body.get("protocol_id") != PROTOCOL_ID:
        raise SFIR4Refused("authority schema or protocol moved")
    if expected_schema == CHARTER_SCHEMA:
        content_digest = body.get("content_sha256")
        core = dict(body)
        core.pop("content_sha256", None)
        expected = (
            "sha256:"
            + hashlib.sha256(
                json.dumps(core, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
        )
        if content_digest != expected:
            raise SFIR4Refused("charter content digest drifted")
    return body


def write_immutable(destination: Path, body: Mapping[str, Any]) -> Path:
    encoded = (json.dumps(dict(body), indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as error:
        raise SFIR4Refused("refusing any existing immutable authority destination") from error
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            destination.unlink(missing_ok=True)
        finally:
            raise
    return destination


def verify_spent(root: Path, ref: Mapping[str, Any]) -> dict[str, Any]:
    body = verify_authority(root, ref, SPENT_SCHEMA)
    if body.get("state") != "COMPLETE_COMPOSED_SPENT_AUTHORITY":
        raise SFIR4Refused("spent authority is not complete")
    for key in ("container_ids", "lineage_ids", "alias_ids"):
        values = body.get(key)
        if not isinstance(values, list) or values != sorted(set(values)):
            raise SFIR4Refused(f"spent {key} is not a sorted set")
    predecessors = body.get("predecessor_sources")
    if not isinstance(predecessors, Mapping) or set(predecessors) != set(SFIR3_PREDECESSORS):
        raise SFIR4Refused("spent authority predecessor set drifted")
    for key, (expected_path, expected_sha, expected_schema) in SFIR3_PREDECESSORS.items():
        predecessor = predecessors.get(key)
        if predecessor != {"path": expected_path, "sha256": expected_sha}:
            raise SFIR4Refused(f"spent predecessor {key} moved")
        predecessor_path = _resolve_ref(root, predecessor)
        if not predecessor_path.is_file() or sha_file(predecessor_path) != expected_sha:
            raise SFIR4Refused(f"spent predecessor {key} is absent or changed")
        predecessor_body = json.loads(predecessor_path.read_text(encoding="utf-8"))
        if predecessor_body.get("schema") != expected_schema:
            raise SFIR4Refused(f"spent predecessor {key} schema moved")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from acquisition import sources_sfir4 as sources

    expected_reserved = sorted(
        sources.discovery_root_id("git_docs", repo) for repo in sources.SFIR3_GIT_ROOTS
    )
    if body.get("reserved_sfir3_declared_roots") != {
        "git_docs": expected_reserved,
        "regulation_ecfr": [],
        "encyclopedia_wikipedia": [],
    }:
        raise SFIR4Refused("spent SFIR3 root reservations drifted")
    if not set(expected_reserved).issubset(body["container_ids"]):
        raise SFIR4Refused("spent containers omit reserved SFIR3 Git roots")
    derivation = body.get("derivation")
    if (
        not isinstance(derivation, Mapping)
        or derivation.get("reserve_all_sfir3_git_roots") is not True
        or derivation.get("exact_root_unknown") is not True
    ):
        raise SFIR4Refused("spent derivation does not conserve unknown SFIR3 root")
    return body


verify_spent_authority = verify_spent


def _validate_candidate(
    family: str, row: Mapping[str, Any], declared: set[str], spent_ids: set[str]
) -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from acquisition import sources_sfir4 as sources

    if set(row) != set(sources.CANDIDATE_FIELDS) or row.get("family") != family:
        raise SFIR4Refused("candidate fields or family drifted")
    if row.get("discovery_root_id") not in declared:
        raise SFIR4Refused("candidate escaped declared roots")
    aliases = row.get("alias_ids")
    capability = row.get("capability_exercise")
    if not isinstance(aliases, list) or aliases != sorted(set(aliases)):
        raise SFIR4Refused("candidate aliases are not a sorted set")
    if (
        not isinstance(capability, Mapping)
        or set(capability) != set(sources.CAPABILITY_ENDPOINTS)
        or any(type(capability[key]) is not bool for key in capability)
    ):
        raise SFIR4Refused("candidate capability booleans drifted")
    core = [row.get("root_container_id"), row.get("container_id"), row.get("lineage_id")]
    if any(not isinstance(value, str) or not value for value in core):
        raise SFIR4Refused("candidate core identity is empty")
    if set(aliases) & set(core):
        raise SFIR4Refused("candidate alias collides with a core identity")
    lineage_value = str(row["lineage_id"])
    bits = hashlib.sha256((sources.SELECTION_SALT + "\0" + lineage_value).encode()).digest()[0]
    expected_capability = {
        "E5": not bool(bits & 1),
        "E6": not bool(bits & 2),
        "E9": not bool(bits & 4),
    }
    if dict(capability) != expected_capability:
        raise SFIR4Refused("candidate capability assignment differs from frozen salt")
    identities = {*core, *aliases}
    if identities & spent_ids:
        raise SFIR4Refused("candidate overlaps spent identities")
    revisions = row.get("revision_id")
    timestamps = row.get("revision_timestamp")
    payload_refs = row.get("payload_ref")
    if any(
        not isinstance(value, Mapping) or set(value) != {"before", "after"}
        for value in (revisions, timestamps, payload_refs)
    ):
        raise SFIR4Refused("candidate before/after maps are malformed")
    if (
        any(
            not isinstance(revisions[key], str) or not revisions[key] for key in ("before", "after")
        )
        or revisions["before"] == revisions["after"]
    ):
        raise SFIR4Refused("candidate revisions are empty or equal")
    parsed_times: dict[str, datetime] = {}
    for key in ("before", "after"):
        value = timestamps[key]
        if not isinstance(value, str) or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z", value
        ):
            raise SFIR4Refused("candidate timestamp is not canonical UTC Z")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise SFIR4Refused("candidate timestamp is not parseable UTC") from error
        if parsed.utcoffset() != timedelta(0):
            raise SFIR4Refused("candidate timestamp is not UTC")
        parsed_times[key] = parsed
    if parsed_times["before"] >= parsed_times["after"]:
        raise SFIR4Refused("candidate timestamps are not strictly increasing")

    discovery = str(row["discovery_root_id"])
    root_container, container, lineage = core
    if family == "git_docs":
        repo = next(
            (
                repo
                for repo in sources.SOURCE_POOLS[family]["repositories"]
                if discovery == sources.discovery_root_id(family, repo)
            ),
            None,
        )
        prefix = f"git:{repo}:" if repo else ""
        if not repo or root_container != discovery or not lineage.startswith(prefix):
            raise SFIR4Refused("Git candidate locator identity shape drifted")
        path = lineage[len(prefix) :]
        if container != f"git:{repo}:document:{path}":
            raise SFIR4Refused("Git document container is not bound to its lineage path")
        if (
            not path
            or "\\" in path
            or path.startswith("/")
            or any(part in {"", ".", ".."} for part in path.split("/"))
        ):
            raise SFIR4Refused("Git candidate path is malformed")
        if any(not re.fullmatch(r"[0-9a-fA-F]{40}", revisions[key]) for key in ("before", "after")):
            raise SFIR4Refused("Git revision SHA is malformed")
        expected_refs = {
            key: f"github://{repo}/blob/{revisions[key]}/{path}" for key in ("before", "after")
        }
    elif family == "regulation_ecfr":
        matched = re.fullmatch(r"ecfr:(\d+):([^:]+):([^:]+)", container)
        if not matched or lineage != container:
            raise SFIR4Refused("eCFR candidate locator identity shape drifted")
        title, part, section = matched.groups()
        if discovery != sources.discovery_root_id(
            family, int(title)
        ) or root_container != sources.root_container_id(family, title=title, part=part):
            raise SFIR4Refused("eCFR candidate root identity shape drifted")
        parsed_revisions: dict[str, date] = {}
        for key in ("before", "after"):
            revision = revisions[key]
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", revision):
                raise SFIR4Refused("eCFR revision ID is not an exact date")
            try:
                parsed_revisions[key] = date.fromisoformat(revision)
            except ValueError as error:
                raise SFIR4Refused("eCFR revision ID is not a calendar date") from error
            if timestamps[key] != f"{revision}T00:00:00Z":
                raise SFIR4Refused("eCFR revision timestamp is not bound to revision date")
        if parsed_revisions["before"] >= parsed_revisions["after"]:
            raise SFIR4Refused("eCFR revisions are not strictly increasing")
        expected_refs = {
            key: f"ecfr://title/{title}/part/{part}/section/{section}?version={revisions[key]}"
            for key in ("before", "after")
        }
    elif family == "encyclopedia_wikipedia":
        container_match = re.fullmatch(r"wikipedia:en:pageid:([1-9]\d*)", container)
        lineage_match = re.fullmatch(r"wiki:en:([1-9]\d*)", lineage)
        if (
            not container_match
            or not lineage_match
            or container_match.group(1) != lineage_match.group(1)
            or root_container != discovery
        ):
            raise SFIR4Refused("Wikipedia candidate locator identity shape drifted")
        page_id = container_match.group(1)
        if any(not re.fullmatch(r"[1-9]\d*", revisions[key]) for key in ("before", "after")):
            raise SFIR4Refused("Wikipedia page or revision ID is not positive numeric")
        if any(
            not alias.startswith("wiki:en:title:") or not alias.removeprefix("wiki:en:title:")
            for alias in aliases
        ):
            raise SFIR4Refused("Wikipedia alias locator scheme drifted")
        expected_refs = {
            key: f"mediawiki://en.wikipedia.org/page/{page_id}/revision/{revisions[key]}"
            for key in ("before", "after")
        }
    else:
        raise SFIR4Refused("unknown candidate family")
    if dict(payload_refs) != expected_refs:
        raise SFIR4Refused("candidate payload locator scheme or revision binding drifted")


def freeze_design_charter(
    root: Path,
    charter_yaml: Path,
    protocol_module: Path,
    source_module: Path,
    probe: Path,
    spent_builder: Path,
    legacy_source_module: Path,
    legacy_metadata_adapter: Path,
    destination: Path,
    generated_at: str,
) -> Path:
    document = yaml.safe_load(charter_yaml.read_text(encoding="utf-8"))
    expected_capacity = {
        "formula": "Q_f=min(1000,floor(0.8*C_f))",
        "minimum_c_per_family": 750,
        "minimum_q_per_family": 600,
    }
    expected_git = {
        "mutable_branch_used_only_to_resolve_head_once": True,
        "bind_exact_head_commit_and_commit_tree_sha": True,
        "recursive_tree_parameter_forbidden": True,
        "traversal": "deterministic_fifo_bfs_over_exact_nonrecursive_tree_objects",
        "complete_requires_queue_exhaustion": True,
        "max_response_bytes": 16 * 1024 * 1024,
        "max_tree_objects_per_root": 158,
        "max_queue_entries": 256,
        "max_aggregate_tree_metadata_bytes_per_root": 512 * 1024 * 1024,
        "max_api_requests_per_root": 240,
        "max_api_requests_global": 4800,
        "max_retained_doc_paths_per_root": 80,
        "theoretical_request_formula": (
            "roots*(2+max_tree_objects_per_root+max_candidates_per_repository)"
        ),
        "max_traversal_identities_per_root": 512,
        "max_rate_limit_wait_seconds": 60,
        "max_total_rate_limit_wait_seconds": 180,
        "retryable_http_backoff_seconds": 5,
        "bound_or_truncation_disposition": "EXCLUDED_INCOMPLETE_ROOT_DISPOSITION",
        "incomplete_root_contributes_candidates": False,
    }
    if (
        not isinstance(document, dict)
        or document.get("protocol_id") != PROTOCOL_ID
        or document.get("state") != "PROSPECTIVE_PRE_CENSUS"
        or document.get("capacity_rule") != expected_capacity
        or document.get("git_tree_enumeration") != expected_git
        or document.get("payload_policy")
        != {
            "capacity_stage_metadata_only": True,
            "payload_open_forbidden": True,
            "diff_open_forbidden": True,
        }
        or document.get("terminal_policy")
        != {
            "no_live_census_before_charter_and_toolchain_freeze": True,
            "no_roster_or_acquisition_on_capacity_shortfall": True,
        }
        or document.get("result_blind_design") is not True
    ):
        raise SFIR4Refused("SFIR4 charter semantics are incomplete or drifted")
    charter_ref = exact_ref(root, charter_yaml)
    toolchain = {
        "sfir4_protocol": exact_ref(root, protocol_module),
        "sources_sfir4": exact_ref(root, source_module),
        "probe_sfir4_capacity": exact_ref(root, probe),
        "sfir4_spent_authority": exact_ref(root, spent_builder),
        "bound_sfir3_ecfr_wikipedia_sources": exact_ref(root, legacy_source_module),
        "bound_sfir3_ecfr_wikipedia_adapter": exact_ref(root, legacy_metadata_adapter),
    }
    core = {
        "schema": CHARTER_SCHEMA,
        "protocol_id": PROTOCOL_ID,
        "generated_at": generated_at,
        "state": "FROZEN_PRE_CENSUS",
        "charter": charter_ref,
        "toolchain": toolchain,
        "charter_digest": "sha256:" + hashlib.sha256(charter_yaml.read_bytes()).hexdigest(),
    }
    core["content_sha256"] = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(core, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    return write_immutable(destination, core)


def _assert_response_evidence(block: object) -> None:
    """The census must carry a verifiable record of what actually came back.

    Three things are checked, and each one has been a real failure mode
    somewhere in this study:

    * the chain recomputes -- an observation cannot be added, dropped or
      reordered after the fact without this failing;
    * the per-root request counts sum to the global count -- arithmetic that
      does not reconcile is arithmetic that was not measured;
    * every response was observed as bytes -- a run driven by an injected
      fetcher records synthesised digests, and a synthesised census must never
      be accepted as a live one.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import sfir4_response_evidence as evidence

    if not isinstance(block, Mapping):
        raise SFIR4Refused("capacity census carries no response evidence")
    if block.get("schema") != RESPONSE_EVIDENCE_SCHEMA:
        raise SFIR4Refused("capacity response-evidence schema moved")
    if not evidence.verify_chain(dict(block)):
        raise SFIR4Refused("capacity response-evidence chain does not recompute")
    totals = block.get("global")
    if not isinstance(totals, Mapping):
        raise SFIR4Refused("capacity response evidence carries no global arithmetic")
    if block.get("per_root_requests_sum") != totals.get("requests"):
        raise SFIR4Refused(
            "capacity response-evidence per-root request counts do not sum to the global count"
        )
    if not totals.get("sequence_is_dense"):
        raise SFIR4Refused("capacity response-evidence sequence has a gap")
    if not totals.get("all_observed"):
        raise SFIR4Refused(
            "capacity census contains synthesised responses; a simulated census "
            "is not a live one"
        )
    if not totals.get("requests"):
        raise SFIR4Refused("capacity census observed no responses at all")


def _assert_metadata_only(value: object, path: str = "$") -> None:
    forbidden = {
        "payload",
        "payload_bytes",
        "payload_text",
        "content",
        "text",
        "diff",
        "source_fact",
        "endpoint_outcome",
        "score",
    }
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key).casefold() in forbidden:
                raise SFIR4Refused(f"capacity metadata contains forbidden field at {path}.{key}")
            _assert_metadata_only(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _assert_metadata_only(child, f"{path}[{index}]")


def seal_capacity(
    root: Path,
    charter_ref: Mapping[str, Any],
    spent_ref: Mapping[str, Any],
    metadata_path: Path,
    destination: Path,
    generated_at: str,
) -> Path:
    charter = verify_authority(root, charter_ref, CHARTER_SCHEMA)
    spent = verify_spent(root, spent_ref)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    _assert_metadata_only(metadata)
    if (
        not isinstance(metadata, Mapping)
        or set(metadata) != CAPACITY_INPUT_FIELDS
        or metadata.get("schema") != CAPACITY_INPUT_SCHEMA
        or metadata.get("protocol_id") != PROTOCOL_ID
        or not isinstance(metadata.get("families"), Mapping)
    ):
        raise SFIR4Refused("capacity metadata schema moved")
    _assert_response_evidence(metadata.get("response_evidence"))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from acquisition import sources_sfir4 as sources

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import sfir4_identity_domain as identity_domain

    spent_ids = set(spent["container_ids"]) | set(spent["lineage_ids"]) | set(spent["alias_ids"])
    all_candidates: list[Mapping[str, Any]] = []
    identity_proof: dict[str, Any] = identity_domain.prove([])
    c_values: dict[str, int] = {}
    q_values: dict[str, int] = {}
    arithmetic: dict[str, Any] = {}
    for family, block in metadata.get("families", {}).items():
        if (
            family not in sources.FAMILIES
            or not isinstance(block, Mapping)
            or set(block) != CAPACITY_FAMILY_FIELDS
            or block.get("authority") != sources.FAMILY_AUTHORITIES[family]
        ):
            raise SFIR4Refused(f"{family} capacity block authority or fields drifted")
        dispositions = block.get("root_dispositions")
        candidates = block.get("candidates")
        if not isinstance(dispositions, list) or not isinstance(candidates, list):
            raise SFIR4Refused(f"{family} capacity block malformed")
        declared_list = [
            sources.discovery_root_id(family, value) for value in sources.declared_roots(family)
        ]
        declared = set(declared_list)
        pagination = block.get("pagination")
        retries_bound = (
            len(declared_list) * sources.PAGINATION_CONTRACT["maximum_retries_per_request"]
        )
        if (
            not isinstance(pagination, Mapping)
            or set(pagination) != CAPACITY_PAGINATION_FIELDS
            or pagination.get("roots_processed") != len(declared_list)
            or pagination.get("exhausted") is not True
            or pagination.get("cap_reached") is not False
            or isinstance(pagination.get("rate_limit_retries"), bool)
            or not isinstance(pagination.get("rate_limit_retries"), int)
            or not 0 <= pagination["rate_limit_retries"] <= retries_bound
            or isinstance(pagination.get("rate_limit_wait_seconds"), bool)
            or not isinstance(pagination.get("rate_limit_wait_seconds"), int)
            or not pagination["rate_limit_retries"]
            <= pagination["rate_limit_wait_seconds"]
            <= sources.MAX_TOTAL_RATE_LIMIT_WAIT_SECONDS
            or (pagination["rate_limit_retries"] == 0)
            != (pagination["rate_limit_wait_seconds"] == 0)
        ):
            raise SFIR4Refused(f"{family} pagination proof drifted")
        disposition_roots = [
            d.get("discovery_root_id") for d in dispositions if isinstance(d, Mapping)
        ]
        if (
            len(dispositions) != len(declared)
            or len(set(disposition_roots)) != len(disposition_roots)
            or disposition_roots != declared_list
        ):
            raise SFIR4Refused(f"{family} dispositions do not exactly cover declared roots")
        complete = {
            d.get("discovery_root_id") for d in dispositions if d.get("state") == "COMPLETE"
        }
        allowed_states = {
            "COMPLETE",
            "EXCLUDED_INCOMPLETE_ROOT_DISPOSITION",
            "UNAVAILABLE_ROOT_DISPOSITION",
            "ZERO_CANDIDATE_ROOT_DISPOSITION",
        }
        if any(d.get("state") not in allowed_states for d in dispositions):
            raise SFIR4Refused(f"{family} root disposition state malformed")
        previous_git_global = 0
        for disposition in dispositions:
            expected_disposition_fields = CAPACITY_DISPOSITION_FIELDS | (
                {"traversal_proof"} if family == "git_docs" else set()
            )
            if (
                not isinstance(disposition, Mapping)
                or set(disposition) != expected_disposition_fields
            ):
                raise SFIR4Refused(f"{family} root disposition fields drifted")
            if not isinstance(disposition.get("reason"), str) or not disposition["reason"]:
                raise SFIR4Refused(f"{family} root disposition reason is absent")
            refs = disposition.get("response_refs")
            if (
                not isinstance(refs, list)
                or not refs
                or any(not isinstance(value, str) or not value for value in refs)
            ):
                raise SFIR4Refused(f"{family} root disposition response refs are incomplete")
            if (
                not isinstance(disposition.get("snapshot_ref"), str)
                or not disposition["snapshot_ref"]
            ):
                raise SFIR4Refused(f"{family} root disposition snapshot ref is absent")
            if family == "git_docs":
                proof = disposition.get("traversal_proof")
                if (
                    not isinstance(proof, Mapping)
                    or set(proof) != GIT_TRAVERSAL_PROOF_FIELDS
                    or not isinstance(proof.get("api_requests"), int)
                    or not isinstance(proof.get("global_requests_before_root"), int)
                    or not isinstance(proof.get("global_api_requests"), int)
                    or proof.get("response_ref_count") != len(refs)
                    or proof["api_requests"] != len(refs)
                    or proof["global_api_requests"]
                    != proof["global_requests_before_root"] + proof["api_requests"]
                    or proof["global_requests_before_root"] < previous_git_global
                    or proof["global_api_requests"] > sources.MAX_GIT_API_REQUESTS_GLOBAL
                ):
                    raise SFIR4Refused("Git transport request arithmetic proof drifted")
                previous_git_global = proof["global_api_requests"]
            if family == "git_docs" and disposition.get("state") == "COMPLETE":
                proof = disposition.get("traversal_proof")
                if (
                    disposition.get("reason") != "NONRECURSIVE_TREE_BFS_QUEUE_EXHAUSTED"
                    or not isinstance(proof, Mapping)
                    or proof.get("algorithm") != "IMMUTABLE_NONRECURSIVE_TREE_BFS"
                    or proof.get("queue_exhausted") is not True
                    or proof.get("remaining_queue_entries") != 0
                    or not isinstance(proof.get("path_to_sha_entries"), int)
                    or not 1 <= proof["path_to_sha_entries"] <= sources.MAX_GIT_TREE_QUEUE_ENTRIES
                    or not isinstance(proof.get("peak_queue_entries"), int)
                    or not 1 <= proof["peak_queue_entries"] <= sources.MAX_GIT_TREE_QUEUE_ENTRIES
                    or not isinstance(proof.get("peak_path_to_sha_entries"), int)
                    or not 1
                    <= proof["peak_path_to_sha_entries"]
                    <= sources.MAX_GIT_TREE_QUEUE_ENTRIES
                    or proof["path_to_sha_entries"] != proof["tree_objects_fetched"]
                    or not isinstance(proof.get("tree_objects_fetched"), int)
                    or not 1
                    <= proof["tree_objects_fetched"]
                    <= sources.MAX_GIT_TREE_OBJECTS_PER_ROOT
                    or not isinstance(proof.get("api_requests"), int)
                    or not 1 <= proof["api_requests"] <= sources.MAX_GIT_API_REQUESTS_PER_ROOT
                    or not isinstance(proof.get("global_api_requests"), int)
                    or not 1 <= proof["global_api_requests"] <= sources.MAX_GIT_API_REQUESTS_GLOBAL
                    or not isinstance(proof.get("aggregate_tree_metadata_bytes"), int)
                    or not 0
                    <= proof["aggregate_tree_metadata_bytes"]
                    <= sources.MAX_GIT_TREE_AGGREGATE_BYTES_PER_ROOT
                    or not isinstance(proof.get("discovered_doc_paths"), int)
                    or proof["discovered_doc_paths"] < 0
                    or not isinstance(proof.get("retained_doc_paths"), int)
                    or not 0
                    <= proof["retained_doc_paths"]
                    <= sources.MAX_GIT_RETAINED_DOC_PATHS_PER_ROOT
                    or proof["retained_doc_paths"] > proof["discovered_doc_paths"]
                    or any("recursive" in value.casefold() for value in refs)
                ):
                    raise SFIR4Refused("Git COMPLETE traversal proof is not exact")
        expected_snapshots = [disposition["snapshot_ref"] for disposition in dispositions]
        expected_responses = [
            response for disposition in dispositions for response in disposition["response_refs"]
        ]
        if (
            block.get("snapshot_refs") != expected_snapshots
            or block.get("response_refs") != expected_responses
        ):
            raise SFIR4Refused(f"{family} aggregate evidence refs drifted")
        if any(row.get("discovery_root_id") not in complete for row in candidates):
            raise SFIR4Refused(f"{family} incomplete root contributed a candidate")
        per_root_counts = {root_id: 0 for root_id in declared}
        per_root_key = {
            "git_docs": "max_candidates_per_repository",
            "regulation_ecfr": "max_candidates_per_title",
            "encyclopedia_wikipedia": "max_candidates_per_category",
        }[family]
        for row in candidates:
            if (
                not isinstance(row, Mapping)
                or set(row) != set(sources.CANDIDATE_FIELDS)
                or row.get("family") != family
            ):
                raise SFIR4Refused(f"{family} candidate fields drifted")
            _validate_candidate(family, row, declared, spent_ids)
            # The collision proof is domain-separated and runs once over every
            # family, below.  It used to run here over a flat, casefolded,
            # cross-family set, which both refused legitimate candidates (a
            # string equality between unrelated corpora, or between two
            # documents in one container) and missed real ones
            # (``root_container_id`` was never in the set).
            all_candidates.append(row)
            per_root_counts[str(row["discovery_root_id"])] += 1
        # Proved over everything admitted so far, BEFORE any count threshold.
        # An identity defect is a more fundamental failure than a shortfall, and
        # whichever check runs first is the one the refusal reports.
        try:
            identity_proof = identity_domain.prove(all_candidates, spent_values=spent_ids)
        except identity_domain.IdentityDomainRefused as error:
            raise SFIR4Refused(f"capacity candidate identity proof failed: {error}") from error
        if any(
            value > sources.SOURCE_POOLS[family][per_root_key] for value in per_root_counts.values()
        ):
            raise SFIR4Refused(f"{family} per-root candidate cap exceeded")
        count = len(candidates)
        if count > sources.SOURCE_POOLS[family]["max_total_candidates"]:
            raise SFIR4Refused(f"{family} total candidate cap exceeded")
        quota = min(1000, (8 * count) // 10)
        if count < 750 or quota < 600:
            raise SFIR4Refused(f"{family} capacity shortfall")
        c_values[family], q_values[family] = count, quota
        arithmetic[family] = {
            "complete_roots": len(complete),
            "excluded_or_unavailable_roots": len(dispositions) - len(complete),
            "candidates_from_complete_roots": count,
            "candidates_from_incomplete_roots": 0,
        }
    if set(c_values) != {"git_docs", "regulation_ecfr", "encyclopedia_wikipedia"}:
        raise SFIR4Refused("capacity families are incomplete")
    if identity_proof["candidates"] != sum(c_values.values()):
        raise SFIR4Refused("identity proof does not cover every admitted candidate")
    return write_immutable(
        destination,
        {
            "schema": CAPACITY_SCHEMA,
            "protocol_id": PROTOCOL_ID,
            "generated_at": generated_at,
            "state": "CAPACITY_PASS",
            "formula": "Q_f=min(1000,floor(0.8*C_f))",
            "C": c_values,
            "Q": q_values,
            "root_disposition_arithmetic": arithmetic,
            "identity_domain_proof": identity_proof,
            "response_evidence_chain_head": metadata["response_evidence"]["chain_head"],
            "charter": dict(charter_ref),
            "spent_identity_authority": dict(spent_ref),
            "metadata": exact_ref(root, metadata_path),
            "frozen_toolchain": charter["toolchain"],
        },
    )


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    freeze = sub.add_parser("freeze-charter")
    for name in (
        "root",
        "charter",
        "protocol-module",
        "sources",
        "probe",
        "spent-builder",
        "legacy-sources",
        "legacy-adapter",
        "destination",
    ):
        freeze.add_argument("--" + name, type=Path, required=True)
    freeze.add_argument("--generated-at", required=True)
    seal = sub.add_parser("seal-capacity")
    for name in ("root", "charter", "spent", "metadata", "destination"):
        seal.add_argument("--" + name, type=Path, required=True)
    seal.add_argument("--charter-sha256", required=True)
    seal.add_argument("--spent-sha256", required=True)
    seal.add_argument("--generated-at", required=True)
    args = parser.parse_args(argv)
    if args.command == "freeze-charter":
        path = freeze_design_charter(
            args.root,
            args.charter,
            args.protocol_module,
            args.sources,
            args.probe,
            args.spent_builder,
            args.legacy_sources,
            args.legacy_adapter,
            args.destination,
            args.generated_at,
        )
    else:
        if (
            sha_file(args.charter) != args.charter_sha256
            or sha_file(args.spent) != args.spent_sha256
        ):
            raise SFIR4Refused("CLI exact digest arguments differ")
        path = seal_capacity(
            args.root,
            exact_ref(args.root, args.charter),
            exact_ref(args.root, args.spent),
            args.metadata,
            args.destination,
            args.generated_at,
        )
    print(path.as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
