"""Prospective, pre-payload infrastructure for SFIR1.

The functions in this module seal four exact authorities in order: design
charter, metadata-only capacity census, deterministic lineage roster, and
protocol.  They accept explicit paths and file hashes only.  There is no
receipt discovery function by design.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

try:
    from acquisition import sources_sfir1 as sources
except ImportError:  # direct execution from research/tavonel_eval_v2/tools
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from acquisition import sources_sfir1 as sources


PROTOCOL_ID = sources.PROTOCOL_ID
CHARTER_SCHEMA = "tavonel.sfir1.design_charter_freeze.v1"
CAPACITY_SCHEMA = "tavonel.sfir1.capacity_census_authority.v1"
ROSTER_SCHEMA = "tavonel.sfir1.lineage_freeze.v1"
PROTOCOL_FREEZE_SCHEMA = "tavonel.sfir1.protocol_freeze.v1"
CAPACITY_INPUT_SCHEMA = "tavonel.sfir1.capacity_metadata.v1"
SPENT_AUTHORITY_SCHEMA = "tavonel.sfir1.spent_identity_authority.v1"
ROSTER_ARTIFACT_SCHEMA = "tavonel.sfir1.frozen_roster.v1"
SPENT_SOURCE_GENERATIONS = frozenset(
    {"SFI1", "SFI2", "SFI3", "V1", "V2", "V2R1", "V2R2", "V2R3", "V2R3R1", "V2R4"}
)

AUTHORITY_SCHEMAS = frozenset(
    {CHARTER_SCHEMA, CAPACITY_SCHEMA, ROSTER_SCHEMA, PROTOCOL_FREEZE_SCHEMA}
)
FORBIDDEN_KEYS = frozenset(
    {
        "payload",
        "payload_bytes",
        "payload_text",
        "before_payload",
        "after_payload",
        "diff",
        "diffs",
        "sourcefact",
        "sourcefacts",
        "source_facts",
        "parsed_units",
        "endpoint_outcome",
        "endpoint_outcomes",
        "score",
        "verdict",
    }
)
SHA_PREFIX = "sha256:"


class SFIR1Refused(RuntimeError):
    """A prospective invariant failed; do not continue to the next rung."""


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def digest(value: Any) -> str:
    return SHA_PREFIX + hashlib.sha256(canonical_bytes(value)).hexdigest()


def sha_file(path: Path) -> str:
    return SHA_PREFIX + hashlib.sha256(path.read_bytes()).hexdigest()


def _content_digest(body: Mapping[str, Any]) -> str:
    return digest({key: value for key, value in body.items() if key != "content_digest"})


def _require_exact_keys(body: Mapping[str, Any], keys: set[str], label: str) -> None:
    actual = set(body)
    if actual != keys:
        raise SFIR1Refused(
            f"{label} keys differ: missing={sorted(keys - actual)}, extra={sorted(actual - keys)}"
        )


def _assert_metadata_only(value: Any, trail: tuple[str, ...] = ()) -> None:
    """Reject pre-freeze material while allowing an opaque ``payload_ref``.

    A reference is identity metadata.  Payload content is not.  The distinction
    is structural so a caller cannot relabel bytes as a note and pass them in.
    """
    if isinstance(value, Mapping):
        for raw_key, child in value.items():
            key = str(raw_key).casefold().replace("-", "_")
            if key in FORBIDDEN_KEYS:
                raise SFIR1Refused(
                    "pre-freeze metadata contains forbidden field "
                    + ".".join((*trail, str(raw_key)))
                )
            _assert_metadata_only(child, (*trail, str(raw_key)))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _assert_metadata_only(child, (*trail, str(index)))
    elif isinstance(value, (bytes, bytearray)):
        raise SFIR1Refused("binary material is forbidden before protocol freeze")


def _safe_subject(root: Path, subject: Mapping[str, Any]) -> Path:
    _require_exact_keys(subject, {"path", "sha256"}, "subject")
    relative = Path(str(subject["path"]))
    if relative.is_absolute() or ".." in relative.parts:
        raise SFIR1Refused("authority subject path must be repository-relative")
    path = (root / relative).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as error:
        raise SFIR1Refused("authority subject escapes repository") from error
    if not path.is_file():
        raise SFIR1Refused(f"authority subject does not exist: {relative.as_posix()}")
    if sha_file(path) != subject["sha256"]:
        raise SFIR1Refused(f"authority subject digest mismatch: {relative.as_posix()}")
    return path


def exact_ref(root: Path, path: Path, expected_sha256: str) -> dict[str, str]:
    resolved_root = root.resolve()
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(resolved_root)
    except ValueError as error:
        raise SFIR1Refused("referenced file is outside repository") from error
    actual = sha_file(resolved)
    if actual != expected_sha256:
        raise SFIR1Refused(f"explicit digest mismatch for {relative.as_posix()}")
    return {"path": relative.as_posix(), "sha256": actual}


def verify_authority(
    root: Path,
    path: Path,
    expected_sha256: str,
    expected_schema: str,
) -> dict[str, Any]:
    """Verify a caller-selected authority; never search for one."""
    if expected_schema not in AUTHORITY_SCHEMAS:
        raise SFIR1Refused(f"unsupported authority schema: {expected_schema}")
    exact_ref(root, path, expected_sha256)
    body = json.loads(path.read_text(encoding="utf-8"))
    if body.get("schema") != expected_schema:
        raise SFIR1Refused(f"authority schema {body.get('schema')!r} != {expected_schema!r}")
    if body.get("protocol_id") != PROTOCOL_ID:
        raise SFIR1Refused("authority belongs to another protocol")
    if body.get("content_digest") != _content_digest(body):
        raise SFIR1Refused("authority content_digest mismatch")
    _safe_subject(root, body.get("subject") or {})
    if expected_schema == CHARTER_SCHEMA:
        _verify_toolchain_bindings(root, body.get("toolchain") or {})
    if expected_schema == PROTOCOL_FREEZE_SCHEMA:
        _verify_execution_toolchain(root, body.get("execution_toolchain") or {})
    return body


def _tool_ref(root: Path, path: Path) -> dict[str, str]:
    resolved = path.resolve()
    if not resolved.is_file():
        raise SFIR1Refused(f"bound tool does not exist: {resolved}")
    try:
        label = resolved.relative_to(root.resolve()).as_posix()
    except ValueError:
        # Unit-test roots intentionally reuse the production implementation.
        # The absolute locator is still exact and its bytes are hash-bound.
        label = resolved.as_posix()
    return {"path": label, "sha256": sha_file(resolved)}


def _verify_toolchain_bindings(root: Path, toolchain: Mapping[str, Any]) -> None:
    _require_exact_keys(
        toolchain,
        {"sources_sfir1", "probe_sfir1_capacity", "sfir1_spent_authority"},
        "charter toolchain",
    )
    for name, ref in toolchain.items():
        _require_exact_keys(ref, {"path", "sha256"}, f"{name} binding")
        candidate = Path(str(ref["path"]))
        path = candidate if candidate.is_absolute() else root / candidate
        if not path.is_file() or sha_file(path) != ref["sha256"]:
            raise SFIR1Refused(f"{name} toolchain binding drifted")


def _verify_execution_toolchain(root: Path, manifest: Mapping[str, Any]) -> None:
    import sfir1_execution as execution

    _require_exact_keys(
        manifest,
        {"schema", "coverage", "components", "content_digest"},
        "execution toolchain manifest",
    )
    if manifest.get("schema") != execution.EXECUTION_TOOLCHAIN_SCHEMA:
        raise SFIR1Refused("execution toolchain schema drifted")
    expected_paths = execution.execution_component_paths()
    if set(manifest.get("components") or {}) != set(expected_paths):
        raise SFIR1Refused("execution toolchain component set drifted")
    expected_coverage = execution.execution_toolchain_manifest()["coverage"]
    if manifest.get("coverage") != expected_coverage:
        raise SFIR1Refused("execution toolchain coverage policy drifted")
    unsigned = {key: value for key, value in manifest.items() if key != "content_digest"}
    if manifest.get("content_digest") != execution.canonical_sha(unsigned):
        raise SFIR1Refused("execution toolchain content digest drifted")
    repository_root = Path(__file__).resolve().parents[3]
    for name, ref in manifest["components"].items():
        _require_exact_keys(ref, {"path", "sha256"}, f"execution component {name}")
        # A logical component name is itself a frozen namespace-relative path.
        # Refuse a manifest that relabels one file as another, even if the bytes
        # happen to be identical.
        expected = expected_paths[name].resolve()
        locator = Path(ref["path"])
        candidates = (
            [locator] if locator.is_absolute() else [root / locator, repository_root / locator]
        )
        path = next((candidate for candidate in candidates if candidate.is_file()), None)
        if path is None or path.resolve() != expected or sha_file(path) != ref["sha256"]:
            raise SFIR1Refused(f"execution component binding drifted: {name}")


def _write_immutable(path: Path, body: Mapping[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(body, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
    except FileExistsError as error:
        raise SFIR1Refused(f"immutable destination already exists: {path}") from error
    return path


def _seal_base(
    schema: str,
    subject: Mapping[str, str],
    generated_at: str,
    **fields: Any,
) -> dict[str, Any]:
    body = {
        "schema": schema,
        "protocol_id": PROTOCOL_ID,
        "generated_at": generated_at,
        "subject": dict(subject),
        **fields,
    }
    body["content_digest"] = _content_digest(body)
    return body


def _validate_charter(charter: Mapping[str, Any]) -> None:
    if charter.get("schema") != "tavonel.sfir1.pre_census_design_charter.v1":
        raise SFIR1Refused("wrong pre-census charter schema")
    if charter.get("protocol_id") != PROTOCOL_ID:
        raise SFIR1Refused("wrong charter protocol_id")
    if charter.get("status") != "DRAFT_PRE_CENSUS":
        raise SFIR1Refused("charter must be frozen while still DRAFT_PRE_CENSUS")
    if charter.get("result_blind") is not True or charter.get("gpu_authorized") is not False:
        raise SFIR1Refused("charter must be result-blind and pre-GPU")
    if charter.get("family_authorities") != dict(sources.FAMILY_AUTHORITIES):
        raise SFIR1Refused("charter family authorities drifted")
    capacity = charter.get("capacity_rule") or {}
    if capacity.get("formula") != "Q_f=min(1000,floor(0.8*C_f))":
        raise SFIR1Refused("capacity formula drifted")
    if capacity.get("minimum_q_per_family") != 600:
        raise SFIR1Refused("minimum family quota drifted")
    selection = charter.get("source_selection") or {}
    if selection.get("selection_salt") != sources.SELECTION_SALT:
        raise SFIR1Refused("selection salt drifted")
    if digest(selection.get("source_pools")) != digest(dict(sources.SOURCE_POOLS)):
        raise SFIR1Refused("finite source pools drifted")
    if digest(selection.get("pagination_contract")) != digest(dict(sources.PAGINATION_CONTRACT)):
        raise SFIR1Refused("pagination contract drifted")
    endpoints = charter.get("endpoint_rule") or {}
    if endpoints.get("primary_exercised_and_met") != [
        "E1",
        "E2",
        "E3",
        "E4",
        "E5",
        "E6",
        "E7",
        "E9",
    ]:
        raise SFIR1Refused("primary endpoint set/order drifted")
    if endpoints.get("veto_only") != "E8" or endpoints.get("no_skip") != ["E5", "E6", "E9"]:
        raise SFIR1Refused("E8 veto or no-skip contract drifted")
    floor = charter.get("analysis_floor") or {}
    if floor.get("total_pairs") != 300 or floor.get("families") != 3:
        raise SFIR1Refused("analysis total/family floor drifted")
    if floor.get("per_family_pairs") != 60:
        raise SFIR1Refused("per-family floor drifted")
    if floor.get("capability_exercising_pairs") != {"E5": 29, "E6": 29, "E9": 29}:
        raise SFIR1Refused("capability exercising floors drifted")


def freeze_design_charter(
    root: Path,
    charter_path: Path,
    destination: Path,
    generated_at: str,
    sources_path: Path | None = None,
    probe_path: Path | None = None,
    spent_builder_path: Path | None = None,
) -> Path:
    charter = yaml.safe_load(charter_path.read_text(encoding="utf-8"))
    _validate_charter(charter)
    subject = exact_ref(root, charter_path, sha_file(charter_path))
    body = _seal_base(
        CHARTER_SCHEMA,
        subject,
        generated_at,
        result_blind=True,
        payload_opened=False,
        frozen_design=digest(charter),
        source_selection_digest=digest(charter["source_selection"]),
        toolchain={
            "sources_sfir1": _tool_ref(root, sources_path or Path(sources.__file__)),
            "probe_sfir1_capacity": _tool_ref(
                root, probe_path or Path(__file__).with_name("probe_sfir1_capacity.py")
            ),
            "sfir1_spent_authority": _tool_ref(
                root, spent_builder_path or Path(__file__).with_name("sfir1_spent_authority.py")
            ),
        },
    )
    return _write_immutable(destination, body)


def _verify_spent_authority(root: Path, subject: Mapping[str, Any]) -> dict[str, Any]:
    path = _safe_subject(root, subject)
    body = json.loads(path.read_text(encoding="utf-8"))
    if body.get("schema") != SPENT_AUTHORITY_SCHEMA:
        raise SFIR1Refused("wrong spent identity authority schema")
    if body.get("content_digest") != _content_digest(body):
        raise SFIR1Refused("spent identity authority content_digest mismatch")
    if set(body) != {
        "schema",
        "generated_at",
        "container_ids",
        "lineage_ids",
        "alias_ids",
        "sources",
        "content_digest",
    }:
        raise SFIR1Refused("spent identity authority has an unexpected shape")
    if len(body["container_ids"]) != len(set(body["container_ids"])):
        raise SFIR1Refused("duplicate container in spent authority")
    if len(body["lineage_ids"]) != len(set(body["lineage_ids"])):
        raise SFIR1Refused("duplicate lineage in spent authority")
    if len(body["alias_ids"]) != len(set(body["alias_ids"])):
        raise SFIR1Refused("duplicate alias in spent authority")
    if not body["sources"]:
        raise SFIR1Refused("spent identity authority has no immutable sources")
    for ref in body["sources"]:
        _require_exact_keys(ref, {"generation", "path", "sha256", "schema"}, "spent source")
        if ref["generation"] not in SPENT_SOURCE_GENERATIONS:
            raise SFIR1Refused("spent source generation is not permitted")
        _safe_subject(root, {"path": ref["path"], "sha256": ref["sha256"]})
    return body


def build_spent_authority(
    root: Path,
    source_specs: Sequence[tuple[str, Path, str]],
    destination: Path,
    generated_at: str,
) -> Path:
    """Seal all prior corpus identities from explicit immutable JSON inputs.

    Each source is caller-selected as ``(generation, path, expected_sha256)``.
    Missing identity material, ambiguous shapes, unsupported generations and
    digest drift all refuse instead of silently declaring a corpus fresh.
    """
    if not source_specs:
        raise SFIR1Refused("at least one spent source is required")
    containers: set[str] = set()
    lineages: set[str] = set()
    aliases: set[str] = set()
    refs: list[dict[str, str]] = []
    for generation, path, expected_sha256 in source_specs:
        if generation not in SPENT_SOURCE_GENERATIONS:
            raise SFIR1Refused(f"unsupported spent generation {generation}")
        ref = exact_ref(root, path, expected_sha256)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SFIR1Refused(f"spent source is not immutable JSON: {ref['path']}") from error
        schema = raw.get("schema") if isinstance(raw, Mapping) else None
        if not isinstance(schema, str) or not schema.startswith("tavonel."):
            raise SFIR1Refused(f"spent source lacks a TAVONEL schema: {ref['path']}")
        found = 0
        stack = [raw]
        while stack:
            value = stack.pop()
            if isinstance(value, Mapping):
                for key, child in value.items():
                    folded = str(key).casefold().replace("-", "_")
                    target = (
                        lineages
                        if folded in {"lineage_id", "lineage_ids"}
                        else containers
                        if folded in {"container_id", "container_ids"}
                        else aliases
                        if folded in {"alias_id", "alias_ids", "redirect_alias", "redirect_aliases"}
                        else None
                    )
                    if target is not None:
                        values = child if isinstance(child, list) else [child]
                        for item in values:
                            if not isinstance(item, str) or not item.strip():
                                raise SFIR1Refused(f"malformed spent identity in {ref['path']}")
                            target.add(item.strip())
                            found += 1
                    elif isinstance(child, (Mapping, list)):
                        stack.append(child)
            elif isinstance(value, list):
                stack.extend(value)
        if found == 0:
            raise SFIR1Refused(f"spent source contributes no identities: {ref['path']}")
        refs.append({"generation": generation, **ref, "schema": schema})
    body = {
        "schema": SPENT_AUTHORITY_SCHEMA,
        "generated_at": generated_at,
        "container_ids": sorted(containers),
        "lineage_ids": sorted(lineages),
        "alias_ids": sorted(aliases),
        "sources": refs,
    }
    body["content_digest"] = _content_digest(body)
    return _write_immutable(destination, body)


def seal_capacity_census(
    root: Path,
    metadata_path: Path,
    charter_path: Path,
    charter_sha256: str,
    spent_subject: Mapping[str, Any],
    destination: Path,
    generated_at: str,
) -> Path:
    charter = verify_authority(root, charter_path, charter_sha256, CHARTER_SCHEMA)
    spent = _verify_spent_authority(root, spent_subject)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    _assert_metadata_only(metadata)
    _require_exact_keys(metadata, {"schema", "protocol_id", "families"}, "capacity metadata")
    if metadata["schema"] != CAPACITY_INPUT_SCHEMA or metadata["protocol_id"] != PROTOCOL_ID:
        raise SFIR1Refused("capacity metadata schema or protocol_id mismatch")
    if set(metadata["families"]) != set(sources.FAMILIES):
        raise SFIR1Refused("capacity metadata must contain exactly three declared families")

    spent_containers = set(spent["container_ids"])
    spent_aliases = set(spent["alias_ids"])
    spent_lineages = set(spent["lineage_ids"])
    seen_containers: set[str] = set()
    seen_lineages: set[str] = set()
    census: dict[str, dict[str, Any]] = {}
    for family in sources.FAMILIES:
        block = metadata["families"][family]
        _require_exact_keys(block, {"authority", "snapshot_id", "pagination", "candidates"}, family)
        if block["authority"] != sources.FAMILY_AUTHORITIES[family]:
            raise SFIR1Refused(f"{family} metadata authority drifted")
        pagination = block["pagination"]
        _require_exact_keys(
            pagination,
            {"pages_fetched", "exhausted", "rate_limit_retries", "cap_reached"},
            f"{family} pagination",
        )
        if pagination["exhausted"] is not True:
            raise SFIR1Refused(f"{family} pagination was not exhausted")
        if pagination["cap_reached"] is True:
            raise SFIR1Refused(f"{family} candidate cap was reached before exhaustion")
        if not isinstance(pagination["pages_fetched"], int) or pagination["pages_fetched"] < 1:
            raise SFIR1Refused(f"{family} pagination page count is invalid")
        candidates = block["candidates"]
        if not isinstance(candidates, list):
            raise SFIR1Refused(f"{family} candidates must be a list")
        family_lineages: set[str] = set()
        family_containers: set[str] = set()
        for row in candidates:
            _require_exact_keys(row, set(sources.CANDIDATE_FIELDS), "candidate")
            if row["family"] != family:
                raise SFIR1Refused("candidate family differs from enclosing family")
            lineage = str(row["lineage_id"])
            container = str(row["container_id"])
            root_container = str(row["root_container_id"])
            aliases = row["alias_ids"]
            payload_ref = row["payload_ref"]
            revision_id = row["revision_id"]
            revision_timestamp = row["revision_timestamp"]
            if not lineage or not container or not root_container:
                raise SFIR1Refused("candidate identity metadata cannot be empty")
            if (
                not isinstance(aliases, list)
                or any(not isinstance(value, str) or not value for value in aliases)
                or len(aliases) != len(set(aliases))
            ):
                raise SFIR1Refused("candidate aliases must be unique non-empty strings")
            try:
                if family == "git_docs":
                    repo = lineage.removeprefix("git:").split(":", 1)[0]
                    expected_root = sources.root_container_id(family, repository=repo)
                elif family == "regulation_ecfr":
                    parts = lineage.split(":")
                    expected_root = sources.root_container_id(family, title=parts[1], part=parts[2])
                else:
                    if not root_container.startswith("wikipedia:en:category:"):
                        raise ValueError("wrong Wikipedia category root")
                    expected_root = root_container
            except (IndexError, ValueError) as error:
                raise SFIR1Refused("candidate root identity is malformed") from error
            if root_container != expected_root:
                raise SFIR1Refused("candidate root identity drifted")
            for name, pair in (
                ("payload_ref", payload_ref),
                ("revision_id", revision_id),
                ("revision_timestamp", revision_timestamp),
            ):
                if (
                    not isinstance(pair, Mapping)
                    or set(pair) != {"before", "after"}
                    or any(not isinstance(pair[k], str) or not pair[k] for k in ("before", "after"))
                ):
                    raise SFIR1Refused(
                        f"candidate {name} must be an exact before/after metadata pair"
                    )
            if revision_id["before"] == revision_id["after"]:
                raise SFIR1Refused("candidate revisions must be distinct")
            if revision_timestamp["before"] >= revision_timestamp["after"]:
                raise SFIR1Refused("candidate revision timestamps are not chronological")
            flags = row["capability_exercise"]
            if set(flags) != set(sources.CAPABILITY_ENDPOINTS) or any(
                type(flags[name]) is not bool for name in sources.CAPABILITY_ENDPOINTS
            ):
                raise SFIR1Refused("capability_exercise must carry E5/E6/E9 booleans")
            collisions = {root_container, container, lineage, *aliases} & (
                spent_containers | spent_lineages | spent_aliases
            )
            if collisions:
                raise SFIR1Refused(
                    f"spent root/container/lineage/alias collision: {sorted(collisions)[0]}"
                )
            if lineage in seen_lineages:
                raise SFIR1Refused(f"duplicate lineage across census: {lineage}")
            seen_lineages.add(lineage)
            family_lineages.add(lineage)
            family_containers.add(container)
            seen_containers.add(container)
        capacity = len(candidates)
        quota = min(1000, math.floor(0.8 * capacity))
        if quota < 600:
            raise SFIR1Refused(f"{family} Q_f={quota} is below frozen minimum 600")
        census[family] = {
            "authority": block["authority"],
            "snapshot_id": block["snapshot_id"],
            "C_f": capacity,
            "Q_f": quota,
            "container_count": len(family_containers),
            "candidate_digest": digest(candidates),
            "pagination": block["pagination"],
        }

    subject = exact_ref(root, metadata_path, sha_file(metadata_path))
    body = _seal_base(
        CAPACITY_SCHEMA,
        subject,
        generated_at,
        charter={
            "path": charter_path.resolve().relative_to(root.resolve()).as_posix(),
            "sha256": charter_sha256,
        },
        charter_content_digest=charter["content_digest"],
        charter_source_selection_digest=charter["source_selection_digest"],
        charter_toolchain=charter["toolchain"],
        spent_identity_authority=dict(spent_subject),
        metadata_only=True,
        payload_opened=False,
        quota_formula="Q_f=min(1000,floor(0.8*C_f))",
        families=census,
        total_candidates=len(seen_lineages),
        fresh_container_count=len(seen_containers),
    )
    return _write_immutable(destination, body)


def _candidate_order(row: Mapping[str, Any]) -> str:
    material = (
        sources.SELECTION_SALT
        + "\0"
        + PROTOCOL_ID
        + "\0"
        + str(row["family"])
        + "\0"
        + str(row["lineage_id"])
    ).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def freeze_roster(
    root: Path,
    metadata_path: Path,
    charter_path: Path,
    charter_sha256: str,
    capacity_path: Path,
    capacity_sha256: str,
    spent_subject: Mapping[str, Any],
    roster_destination: Path,
    authority_destination: Path,
    generated_at: str,
) -> tuple[Path, Path]:
    charter = verify_authority(root, charter_path, charter_sha256, CHARTER_SCHEMA)
    capacity = verify_authority(root, capacity_path, capacity_sha256, CAPACITY_SCHEMA)
    spent = _verify_spent_authority(root, spent_subject)
    if capacity.get("charter", {}).get("sha256") != charter_sha256:
        raise SFIR1Refused("capacity authority does not bind the selected charter")
    if capacity.get("spent_identity_authority") != dict(spent_subject):
        raise SFIR1Refused("capacity and roster use different spent authorities")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    _assert_metadata_only(metadata)
    if sha_file(metadata_path) != capacity["subject"]["sha256"]:
        raise SFIR1Refused("capacity metadata changed after census")

    selected: list[dict[str, Any]] = []
    for family in sources.FAMILIES:
        rows = metadata["families"][family]["candidates"]
        ordered = sorted(rows, key=lambda row: (_candidate_order(row), row["lineage_id"]))
        quota = capacity["families"][family]["Q_f"]
        family_selected = ordered[:quota]
        if len(family_selected) != quota:
            raise SFIR1Refused(f"{family} cannot fill frozen quota")
        selected.extend(
            {
                **row,
                "selection_rank": rank,
                "selection_key": _candidate_order(row),
                "provenance": {
                    "capacity_subject_sha256": capacity["subject"]["sha256"],
                    "capacity_authority_sha256": capacity_sha256,
                    "candidate_digest": capacity["families"][family]["candidate_digest"],
                },
            }
            for rank, row in enumerate(family_selected, start=1)
        )

    selected_ids = {
        identity
        for row in selected
        for identity in (
            row["root_container_id"],
            row["container_id"],
            row["lineage_id"],
            *row["alias_ids"],
        )
    }
    if selected_ids & (
        set(spent["container_ids"]) | set(spent["lineage_ids"]) | set(spent["alias_ids"])
    ):
        raise SFIR1Refused("selected roster intersects a spent root/container/lineage/alias")
    capability_counts = {
        endpoint: sum(bool(row["capability_exercise"][endpoint]) for row in selected)
        for endpoint in sources.CAPABILITY_ENDPOINTS
    }
    underpowered = {endpoint: count for endpoint, count in capability_counts.items() if count < 29}
    if underpowered:
        raise SFIR1Refused(
            "frozen roster cannot meet predeclared capability exercising floors: "
            + repr(underpowered)
        )
    roster = {
        "schema": ROSTER_ARTIFACT_SCHEMA,
        "protocol_id": PROTOCOL_ID,
        "generated_at": generated_at,
        "ordering": "sha256(selection_salt + NUL + protocol_id + NUL + family + NUL + lineage_id), ascending",
        "selection_salt": sources.SELECTION_SALT,
        "charter_sha256": charter_sha256,
        "capacity_sha256": capacity_sha256,
        "spent_identity_authority": dict(spent_subject),
        "payload_opened": False,
        "candidates": selected,
    }
    roster["content_digest"] = _content_digest(roster)
    _write_immutable(roster_destination, roster)
    subject = exact_ref(root, roster_destination, sha_file(roster_destination))
    authority = _seal_base(
        ROSTER_SCHEMA,
        subject,
        generated_at,
        charter={
            "path": charter_path.resolve().relative_to(root.resolve()).as_posix(),
            "sha256": charter_sha256,
        },
        charter_content_digest=charter["content_digest"],
        capacity={
            "path": capacity_path.resolve().relative_to(root.resolve()).as_posix(),
            "sha256": capacity_sha256,
        },
        capacity_content_digest=capacity["content_digest"],
        roster_content_digest=roster["content_digest"],
        spent_identity_authority=dict(spent_subject),
        deterministic_order=True,
        payload_opened=False,
        counts={
            family: sum(row["family"] == family for row in selected) for family in sources.FAMILIES
        },
        capability_exercise_counts=capability_counts,
    )
    _write_immutable(authority_destination, authority)
    return roster_destination, authority_destination


def freeze_protocol(
    root: Path,
    protocol_path: Path,
    charter_path: Path,
    charter_sha256: str,
    capacity_path: Path,
    capacity_sha256: str,
    roster_authority_path: Path,
    roster_authority_sha256: str,
    destination: Path,
    generated_at: str,
) -> Path:
    charter = verify_authority(root, charter_path, charter_sha256, CHARTER_SCHEMA)
    capacity = verify_authority(root, capacity_path, capacity_sha256, CAPACITY_SCHEMA)
    roster = verify_authority(root, roster_authority_path, roster_authority_sha256, ROSTER_SCHEMA)
    if capacity.get("charter", {}).get("sha256") != charter_sha256:
        raise SFIR1Refused("capacity does not bind exact charter")
    if roster.get("charter", {}).get("sha256") != charter_sha256:
        raise SFIR1Refused("roster does not bind exact charter")
    if roster.get("capacity", {}).get("sha256") != capacity_sha256:
        raise SFIR1Refused("roster does not bind exact capacity authority")
    protocol = yaml.safe_load(protocol_path.read_text(encoding="utf-8"))
    if (
        protocol.get("schema") != "tavonel.sfir1.protocol.v1"
        or protocol.get("protocol_id") != PROTOCOL_ID
    ):
        raise SFIR1Refused("wrong SFIR1 protocol subject")
    if protocol.get("status") != "AWAITING_EXACT_AUTHORITIES_AND_PROTOCOL_FREEZE":
        raise SFIR1Refused("protocol is not at its prospective freeze state")
    if protocol.get("gpu_authorized") is not False:
        raise SFIR1Refused("SFIR1 protocol freeze cannot authorize GPU")
    requirements = protocol.get("authority_requirements") or {}
    if requirements.get("spent_identity") != SPENT_AUTHORITY_SCHEMA or requirements.get(
        "charter_toolchain_bindings"
    ) != ["sources_sfir1", "probe_sfir1_capacity", "sfir1_spent_authority"]:
        raise SFIR1Refused("protocol spent/toolchain authority requirements drifted")
    protocol_capacity = protocol.get("capacity") or {}
    if protocol_capacity.get("minimum_C_per_family") != 750 or protocol_capacity.get(
        "candidate_fields"
    ) != list(sources.CANDIDATE_FIELDS):
        raise SFIR1Refused("protocol capacity candidate contract drifted")
    if (
        protocol_capacity.get("complete_pagination_required") is not True
        or protocol_capacity.get("truncate_at_cap") != "forbidden"
    ):
        raise SFIR1Refused("protocol pagination contract drifted")
    subject = exact_ref(root, protocol_path, sha_file(protocol_path))
    import sfir1_execution as execution

    execution_toolchain = execution.execution_toolchain_manifest()
    _verify_execution_toolchain(root, execution_toolchain)
    body = _seal_base(
        PROTOCOL_FREEZE_SCHEMA,
        subject,
        generated_at,
        charter={
            "path": charter_path.resolve().relative_to(root.resolve()).as_posix(),
            "sha256": charter_sha256,
        },
        charter_content_digest=charter["content_digest"],
        capacity={
            "path": capacity_path.resolve().relative_to(root.resolve()).as_posix(),
            "sha256": capacity_sha256,
        },
        capacity_content_digest=capacity["content_digest"],
        roster={
            "path": roster_authority_path.resolve().relative_to(root.resolve()).as_posix(),
            "sha256": roster_authority_sha256,
        },
        roster_content_digest=roster["content_digest"],
        roster_subject=roster["subject"],
        payload_opened=False,
        gpu_authorized=False,
        acquisition_authorized=True,
        scoring_authorized=False,
        scoring_requires_exactly_once_acquisition_authority=True,
        score_exactly_once=True,
        execution_toolchain=execution_toolchain,
    )
    return _write_immutable(destination, body)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    verify = sub.add_parser("verify-authority")
    verify.add_argument("--root", type=Path, required=True)
    verify.add_argument("--path", type=Path, required=True)
    verify.add_argument("--sha256", required=True)
    verify.add_argument("--schema", required=True, choices=sorted(AUTHORITY_SCHEMAS))
    freeze_charter = sub.add_parser("freeze-charter")
    freeze_charter.add_argument("--root", type=Path, required=True)
    freeze_charter.add_argument("--charter", type=Path, required=True)
    freeze_charter.add_argument("--destination", type=Path, required=True)
    freeze_charter.add_argument("--generated-at", required=True)
    freeze_charter.add_argument("--sources-tool", type=Path)
    freeze_charter.add_argument("--probe-tool", type=Path)
    freeze_charter.add_argument("--spent-builder-tool", type=Path)
    build_spent = sub.add_parser("build-spent-authority")
    build_spent.add_argument("--root", type=Path, required=True)
    build_spent.add_argument("--destination", type=Path, required=True)
    build_spent.add_argument("--generated-at", required=True)
    probe = sub.add_parser("probe-capacity")
    probe.add_argument("--root", type=Path, required=True)
    probe.add_argument("--charter", type=Path, required=True)
    probe.add_argument("--charter-sha256", required=True)
    probe.add_argument("--spent", type=Path, required=True)
    probe.add_argument("--spent-sha256", required=True)
    probe_mode = probe.add_mutually_exclusive_group(required=True)
    probe_mode.add_argument("--responses", type=Path, help="audited metadata API page transcript")
    probe_mode.add_argument(
        "--live", action="store_true", help="call only the frozen public metadata APIs"
    )
    probe.add_argument("--destination", type=Path, required=True)
    seal = sub.add_parser("seal-capacity")
    for p in (seal,):
        p.add_argument("--root", type=Path, required=True)
        p.add_argument("--metadata", type=Path, required=True)
        p.add_argument("--charter", type=Path, required=True)
        p.add_argument("--charter-sha256", required=True)
        p.add_argument("--spent", type=Path, required=True)
        p.add_argument("--spent-sha256", required=True)
        p.add_argument("--destination", type=Path, required=True)
        p.add_argument("--generated-at", required=True)
    roster = sub.add_parser("freeze-roster")
    roster.add_argument("--root", type=Path, required=True)
    roster.add_argument("--metadata", type=Path, required=True)
    roster.add_argument("--charter", type=Path, required=True)
    roster.add_argument("--charter-sha256", required=True)
    roster.add_argument("--capacity", type=Path, required=True)
    roster.add_argument("--capacity-sha256", required=True)
    roster.add_argument("--spent", type=Path, required=True)
    roster.add_argument("--spent-sha256", required=True)
    roster.add_argument("--roster-destination", type=Path, required=True)
    roster.add_argument("--authority-destination", type=Path, required=True)
    roster.add_argument("--generated-at", required=True)
    freeze = sub.add_parser("freeze-protocol")
    freeze.add_argument("--root", type=Path, required=True)
    freeze.add_argument("--protocol", type=Path, required=True)
    freeze.add_argument("--charter", type=Path, required=True)
    freeze.add_argument("--charter-sha256", required=True)
    freeze.add_argument("--capacity", type=Path, required=True)
    freeze.add_argument("--capacity-sha256", required=True)
    freeze.add_argument("--roster-authority", type=Path, required=True)
    freeze.add_argument("--roster-authority-sha256", required=True)
    freeze.add_argument("--destination", type=Path, required=True)
    freeze.add_argument("--generated-at", required=True)
    args = parser.parse_args(argv)
    if args.command == "verify-authority":
        body = verify_authority(args.root, args.path, args.sha256, args.schema)
        print(json.dumps(body, indent=2, sort_keys=True, ensure_ascii=False))
        return 0
    if args.command == "freeze-charter":
        path = freeze_design_charter(
            args.root,
            args.charter,
            args.destination,
            args.generated_at,
            args.sources_tool,
            args.probe_tool,
            args.spent_builder_tool,
        )
    elif args.command == "build-spent-authority":
        import sfir1_spent_authority as comprehensive_spent

        try:
            body = comprehensive_spent.assemble_spent_authority(args.root, args.generated_at)
            path = comprehensive_spent.write_spent_authority(args.destination, body)
        except comprehensive_spent.SpentAuthorityRefused as error:
            raise SFIR1Refused(str(error)) from error
    elif args.command == "probe-capacity":
        from probe_sfir1_capacity import LiveMetadataTransport, probe_capacity

        if args.live:
            transport = LiveMetadataTransport()
        else:
            pages = json.loads(args.responses.read_text(encoding="utf-8"))
            positions = {family: 0 for family in sources.FAMILIES}

            def transport(family: str, _request: Mapping[str, Any]) -> Mapping[str, Any]:
                index = positions[family]
                positions[family] += 1
                try:
                    return pages[family][index]
                except (KeyError, IndexError) as error:
                    raise SFIR1Refused(f"missing audited response page for {family}") from error

        path = probe_capacity(
            args.root,
            args.charter,
            args.charter_sha256,
            {
                "path": args.spent.resolve().relative_to(args.root.resolve()).as_posix(),
                "sha256": args.spent_sha256,
            },
            args.destination,
            transport,
        )
    elif args.command == "seal-capacity":
        path = seal_capacity_census(
            args.root,
            args.metadata,
            args.charter,
            args.charter_sha256,
            {
                "path": args.spent.resolve().relative_to(args.root.resolve()).as_posix(),
                "sha256": args.spent_sha256,
            },
            args.destination,
            args.generated_at,
        )
    elif args.command == "freeze-roster":
        paths = freeze_roster(
            args.root,
            args.metadata,
            args.charter,
            args.charter_sha256,
            args.capacity,
            args.capacity_sha256,
            {
                "path": args.spent.resolve().relative_to(args.root.resolve()).as_posix(),
                "sha256": args.spent_sha256,
            },
            args.roster_destination,
            args.authority_destination,
            args.generated_at,
        )
        print(json.dumps([p.as_posix() for p in paths]))
        return 0
    elif args.command == "freeze-protocol":
        path = freeze_protocol(
            args.root,
            args.protocol,
            args.charter,
            args.charter_sha256,
            args.capacity,
            args.capacity_sha256,
            args.roster_authority,
            args.roster_authority_sha256,
            args.destination,
            args.generated_at,
        )
    else:
        raise AssertionError(args.command)
    print(path.as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
