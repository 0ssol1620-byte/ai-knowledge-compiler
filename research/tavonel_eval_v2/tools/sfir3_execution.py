#!/usr/bin/env python3
"""Fail-closed execution contracts for the independent SFIR3 study."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]
PROTOCOL_ID = "SOURCE_FACT_IR_INDEPENDENT_REPLICATION_V3"

SCHEMAS = {
    "charter": "tavonel.sfir3.design_charter_freeze.v1",
    "capacity": "tavonel.sfir3.capacity_census_authority.v1",
    "roster": "tavonel.sfir3.lineage_freeze.v1",
    "protocol_freeze": "tavonel.sfir3.protocol_freeze.v1",
}

FRAME_AUTHORITY = NS / "receipts" / "sfir3-frame-authority.json"
SCORE_AUTHORITY = NS / "receipts" / "sfir3-score-authority.json"
ACCEPTANCE_AUTHORITY = NS / "receipts" / "sfir3-acceptance-authority.json"
ACQUISITION_SPENT_AUTHORITY = NS / "receipts" / "sfir3-acquisition-spent-authority.json"
ACQUISITION_SPENT_SCHEMA = "tavonel.sfir3.acquisition_spent_authority.v1"
ACQUISITION = NS / "artifacts" / "development" / "sfir3" / "sfir3_acquisition.json"
OBSERVATION_DIR = NS / "artifacts" / "development" / "sfir3" / "observations"
PAYLOAD_CACHE = NS / "artifacts" / "development" / "sfir3_cache"
ECFR_PART_CACHE_ROOT = NS / "artifacts" / "development" / "sfir3_cache" / "ecfr_raw_parts"

EXECUTION_TOOLCHAIN_SCHEMA = "tavonel.sfir3.execution_manifest.v1"
EXECUTION_SOURCE_TREES = (
    NS / "acquisition",
    NS / "canonicalization",
    NS / "compiler",
    NS / "source_fact_ir",
)
EXECUTION_ENTRYPOINTS = (
    NS / "tools" / "sfir3_protocol.py",
    NS / "tools" / "sfir3_spent_authority.py",
    NS / "tools" / "probe_sfir3_capacity.py",
    NS / "tools" / "sfir3_execution.py",
    NS / "tools" / "sfir3_worker.py",
    NS / "tools" / "verify_sfir3_frame.py",
    NS / "tools" / "score_sfir3.py",
    NS / "tools" / "sfir3_acceptance.py",
    # Reused native scientific implementation is frozen by exact bytes too.
    NS / "tools" / "sfir1_worker.py",
    NS / "tools" / "sfi1_worker.py",
    NS / "tools" / "sfi2_worker.py",
    NS / "tools" / "score_sfi1.py",
    NS / "tools" / "score_sfi3.py",
    NS / "acquisition" / "ecfr_raw_part_cache.py",
    NS / "acquisition" / "payload_cache.py",
    NS / "tools" / "common.py",
    NS / "tools" / "evidence.py",
)

MIN_TOTAL = 300
MIN_FAMILIES = 3
MIN_PER_FAMILY = 60
MIN_EXERCISING = 29
EXERCISE_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "E5_no_confirmed_selective_stale_escape": ("E5",),
    "E6_exact_selective_vs_clean_equivalence": ("E6",),
    "E9_every_detected_typed_change_creates_a_rebuild_request": ("E9",),
}
ENDPOINTS = (
    "E1_no_unclassified_changed_regions",
    "E2_no_recognized_but_unrepresented",
    "E3_no_silent_loss_in_a_complete_scope",
    "E4_no_reference_or_locator_only_clean_miss",
    "E5_no_confirmed_selective_stale_escape",
    "E6_exact_selective_vs_clean_equivalence",
    "E7_unresolved_fails_closed",
    "E8_no_rebuild_required_artifact_carried_without_execution",
    "E9_every_detected_typed_change_creates_a_rebuild_request",
)
PRIMARY_ENDPOINTS = tuple(name for name in ENDPOINTS if not name.startswith("E8_"))
VETO_ENDPOINT = next(name for name in ENDPOINTS if name.startswith("E8_"))


class Refused(RuntimeError):
    """An immutable SFIR3 authority or scientific binding was not satisfied."""


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def canonical_sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def read_json(path: Path) -> dict[str, Any]:
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise Refused(f"cannot read immutable JSON {path}: {error}") from error
    if not isinstance(body, dict):
        raise Refused(f"{path} is not a JSON object")
    return body


def execution_component_paths() -> dict[str, Path]:
    paths = set(EXECUTION_ENTRYPOINTS)
    for tree in EXECUTION_SOURCE_TREES:
        if not tree.is_dir():
            raise Refused(f"SFIR3 execution source tree is absent: {tree}")
        paths.update(path for path in tree.rglob("*.py") if "__pycache__" not in path.parts)
    components: dict[str, Path] = {}
    for path in sorted(paths, key=lambda item: item.as_posix()):
        if not path.is_file():
            raise Refused(f"SFIR3 execution component is absent: {path}")
        try:
            name = path.resolve().relative_to(NS.resolve()).as_posix()
        except ValueError as error:
            raise Refused(f"SFIR3 execution component escapes namespace: {path}") from error
        components[name] = path
    return components


def execution_toolchain_manifest(generated_at: str | None = None) -> dict[str, Any]:
    components = {
        name: {"path": relative(path), "sha256": sha_file(path)}
        for name, path in execution_component_paths().items()
    }
    body = {
        "schema": EXECUTION_TOOLCHAIN_SCHEMA,
        "protocol_id": PROTOCOL_ID,
        "coverage": {
            "strategy": "closed_python_source_trees_plus_explicit_entrypoints",
            "source_trees": [
                tree.resolve().relative_to(NS.resolve()).as_posix()
                for tree in EXECUTION_SOURCE_TREES
            ],
            "entrypoints": [
                path.resolve().relative_to(NS.resolve()).as_posix()
                for path in EXECUTION_ENTRYPOINTS
            ],
            "component_count": len(components),
            "reused_modules_are_hash_bound": True,
        },
        "components": components,
    }
    if generated_at is not None:
        body["generated_at"] = generated_at
    body["content_digest"] = canonical_sha(body)
    return body


def write_execution_manifest(path: Path, generated_at: str) -> dict[str, Any]:
    """Write the external manifest once; the protocol freeze binds this file."""
    if not isinstance(generated_at, str) or not generated_at:
        raise Refused("generated_at is required for the execution manifest")
    body = execution_toolchain_manifest(generated_at)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as error:
        raise Refused(f"immutable SFIR3 execution manifest already exists: {path}") from error
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(body, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")
    return body


def verify_receipt(kind: str, path: Path, expected_sha256: str) -> dict[str, Any]:
    if kind not in SCHEMAS:
        raise Refused(f"unknown SFIR3 binding kind {kind!r}")
    if not path.is_file() or sha_file(path) != expected_sha256:
        raise Refused(f"exact {kind} receipt is absent or its digest moved")
    try:
        import sfir3_protocol

        body = sfir3_protocol.verify_authority(ROOT, path, expected_sha256, SCHEMAS[kind])
    except Exception as error:
        raise Refused(f"invalid exact {kind} authority: {error}") from error
    return {
        "kind": kind,
        "path": relative(path),
        "sha256": expected_sha256,
        "schema": body["schema"],
        "body": body,
    }


def verify_design_bindings(specs: dict[str, tuple[Path, str]]) -> dict[str, Any]:
    if set(specs) != set(SCHEMAS):
        raise Refused(f"all and only four exact SFIR3 bindings are mandatory: {sorted(SCHEMAS)}")
    verified = {kind: verify_receipt(kind, *specs[kind]) for kind in SCHEMAS}
    frozen = verified["protocol_freeze"]["body"]
    for kind in ("charter", "capacity", "roster"):
        held = verified[kind]
        if frozen.get(kind) != {"path": held["path"], "sha256": held["sha256"]}:
            raise Refused(f"protocol freeze does not bind the exact {kind} authority")
    try:
        import sfir3_protocol

        spent_ref = frozen.get("spent_identity_authority")
        if not isinstance(spent_ref, dict):
            raise sfir3_protocol.SFIR3Refused(
                "protocol freeze has no exact spent identity authority"
            )
        sfir3_protocol.verify_spent_authority(ROOT, spent_ref)
    except Exception as error:
        raise Refused(f"invalid exact spent identity authority: {error}") from error
    capacity = verified["capacity"]["body"]
    roster = verified["roster"]["body"]
    charter_ref = {key: verified["charter"][key] for key in ("path", "sha256")}
    capacity_ref = {key: verified["capacity"][key] for key in ("path", "sha256")}
    if (
        capacity.get("charter") != charter_ref
        or capacity.get("spent_identity_authority") != spent_ref
        or roster.get("charter") != charter_ref
        or roster.get("capacity") != capacity_ref
        or roster.get("spent_identity_authority") != spent_ref
    ):
        raise Refused("SFIR3 charter/capacity/roster/spent cross-bindings drifted")
    manifest_ref = frozen.get("execution_manifest")
    if not isinstance(manifest_ref, dict) or set(manifest_ref) != {
        "path",
        "sha256",
        "content_digest",
        "schema",
    }:
        raise Refused("protocol freeze has no exact external SFIR3 execution manifest")
    manifest_path = (ROOT / str(manifest_ref["path"])).resolve()
    if not manifest_path.is_file() or sha_file(manifest_path) != manifest_ref["sha256"]:
        raise Refused("exact external SFIR3 execution manifest is absent or moved")
    manifest = read_json(manifest_path)
    if (
        manifest.get("schema") != "tavonel.sfir3.execution_manifest.v1"
        or manifest.get("protocol_id") != PROTOCOL_ID
    ):
        raise Refused("external execution manifest schema or protocol moved")
    claimed_digest = manifest.get("content_digest")
    if claimed_digest != canonical_sha(
        {key: value for key, value in manifest.items() if key != "content_digest"}
    ):
        raise Refused("external execution manifest content_digest is invalid")
    if (
        manifest_ref["schema"] != manifest["schema"]
        or manifest_ref["content_digest"] != claimed_digest
    ):
        raise Refused("protocol freeze execution-manifest schema or content_digest moved")
    generated_at = manifest.get("generated_at")
    if not isinstance(generated_at, str) or not generated_at:
        raise Refused("external execution manifest has no generated_at")
    current = execution_toolchain_manifest(generated_at)
    if manifest != current:
        raise Refused(
            "external execution manifest is not the exact current closed SFIR3 component set"
        )
    required_flags = {
        "acquisition_authorized": True,
        "scoring_authorized": False,
        "score_exactly_once": True,
        "scoring_requires_exactly_once_acquisition_authority": True,
    }
    if any(frozen.get(name) is not value for name, value in required_flags.items()):
        raise Refused(
            "protocol freeze does not carry the exact acquisition/scoring authorization flags"
        )
    return {
        kind: {key: row[key] for key in ("path", "sha256", "schema")}
        for kind, row in verified.items()
    }


def reverify_recorded_bindings(recorded: Any) -> dict[str, Any]:
    if not isinstance(recorded, dict) or set(recorded) != set(SCHEMAS):
        raise Refused("acquisition does not carry all four exact SFIR3 design bindings")
    specs: dict[str, tuple[Path, str]] = {}
    for kind, row in recorded.items():
        if (
            not isinstance(row, dict)
            or set(row) != {"path", "sha256", "schema"}
            or row["schema"] != SCHEMAS[kind]
        ):
            raise Refused(f"recorded {kind} binding has an unexpected shape")
        path = Path(str(row["path"]))
        specs[kind] = (
            (ROOT / path).resolve() if not path.is_absolute() else path,
            str(row["sha256"]),
        )
    return verify_design_bindings(specs)


def _nonempty(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise Refused(f"roster candidate has no {label}")
    return value


def roster_candidates(roster_receipt: dict[str, Any], _receipt_path: Path) -> list[dict[str, Any]]:
    """Read the selected rows directly from the exact lineage-freeze authority."""
    try:
        import sfir3_protocol
        from acquisition import sources_sfir3 as sources

        if (
            roster_receipt.get("schema") != SCHEMAS["roster"]
            or roster_receipt.get("protocol_id") != PROTOCOL_ID
        ):
            raise sfir3_protocol.SFIR3Refused("lineage freeze schema or protocol moved")
        families = roster_receipt.get("families")
        quotas = roster_receipt.get("Q")
        if not isinstance(families, dict) or set(families) != set(sources.FAMILIES):
            raise sfir3_protocol.SFIR3Refused("lineage freeze family domain moved")
        if not isinstance(quotas, dict) or set(quotas) != set(sources.FAMILIES):
            raise sfir3_protocol.SFIR3Refused("lineage freeze quota domain moved")
        spent_ref = roster_receipt.get("spent_identity_authority")
        if not isinstance(spent_ref, dict):
            raise sfir3_protocol.SFIR3Refused("lineage freeze has no spent authority")
        spent = sfir3_protocol.verify_spent_authority(ROOT, spent_ref)
        spent_ids = (
            set(spent["container_ids"]) | set(spent["lineage_ids"]) | set(spent["alias_ids"])
        )
    except Exception as error:
        raise Refused(f"invalid exact lineage-freeze authority: {error}") from error
    candidates: list[dict[str, Any]] = []
    for family in sources.FAMILIES:
        rows = families[family]
        quota = quotas[family]
        if (
            not isinstance(rows, list)
            or isinstance(quota, bool)
            or not isinstance(quota, int)
            or len(rows) != quota
        ):
            raise Refused(f"lineage freeze {family} rows do not equal frozen Q")
        declared = {
            sources.discovery_root_id(family, root) for root in sources.declared_roots(family)
        }
        for row in rows:
            if not isinstance(row, dict):
                raise Refused(f"lineage freeze {family} contains a non-object candidate")
            try:
                sfir3_protocol._validate_candidate(family, row, declared, spent_ids)
            except sfir3_protocol.SFIR3Refused as error:
                raise Refused(str(error)) from error
            candidates.append(row)
    seen_lineages: set[str] = set()
    seen_subjects: set[str] = set()
    seen_aliases: set[str] = set()
    clean: list[dict[str, Any]] = []
    for index, row in enumerate(candidates):
        if not isinstance(row, dict):
            raise Refused(f"roster candidate {index} is not an object")
        discovery_root = _nonempty(row.get("discovery_root_id"), "discovery_root_id")
        lineage = _nonempty(row.get("lineage_id"), "lineage_id")
        root = _nonempty(row.get("root_container_id"), "root_container_id")
        container = _nonempty(row.get("container_id"), "container_id")
        family = _nonempty(row.get("family"), "family")
        if lineage in seen_lineages:
            raise Refused(f"duplicate lineage_id {lineage}")
        aliases = row.get("alias_ids")
        if (
            not isinstance(aliases, list)
            or any(not isinstance(item, str) or not item for item in aliases)
            or len(aliases) != len(set(aliases))
        ):
            raise Refused(f"roster candidate {lineage} has invalid alias_ids")
        # A discovery root may equal a root container for repository/category
        # sources, so it is validated separately from the alias collision set.
        if set(aliases) & {root, container, lineage}:
            raise Refused(f"roster candidate {lineage} aliases collide with root/container/lineage")
        normalized_aliases = {item.casefold() for item in aliases}
        normalized_subjects = {lineage.casefold(), container.casefold()}
        if (
            normalized_aliases & seen_aliases
            or normalized_aliases & seen_subjects
            or normalized_subjects & seen_aliases
            or normalized_subjects & seen_subjects
        ):
            raise Refused(f"roster candidate {lineage} collides in the global identity domain")
        flags = row.get("capability_exercise")
        if set(flags or {}) != {"E5", "E6", "E9"} or any(
            type(flags[key]) is not bool for key in flags
        ):
            raise Refused(f"roster candidate {lineage} has no exact E5/E6/E9 capability booleans")
        if family not in {"git_docs", "regulation_ecfr", "encyclopedia_wikipedia"}:
            raise Refused(f"roster candidate {lineage} has an unknown family")
        discovery_prefix = {
            "git_docs": "git:",
            "regulation_ecfr": "ecfr:title:",
            "encyclopedia_wikipedia": "wikipedia:en:category:",
        }[family]
        if not discovery_root.startswith(discovery_prefix):
            raise Refused(f"roster candidate {lineage} has an invalid discovery_root_id")
        seen_lineages.add(lineage)
        seen_aliases.update(normalized_aliases)
        seen_subjects.update(normalized_subjects)
        clean.append(dict(row))
    return clean


def exercise_eligibility(flags: dict[str, bool]) -> dict[str, Any]:
    return {
        endpoint: {
            "eligible": all(flags.get(name) is True for name in requirements),
            "requirements": list(requirements),
            "observed": {name: flags.get(name) is True for name in requirements},
            "outcomes_inspected": False,
        }
        for endpoint, requirements in EXERCISE_REQUIREMENTS.items()
    }


def deterministic_reduce(candidates: Iterable[dict[str, Any]]) -> dict[str, Any]:
    admitted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ordinal, candidate in enumerate(candidates):
        lineage = str(candidate.get("lineage_id") or "")
        if not lineage or lineage in seen:
            rejected.append(
                {"ordinal": ordinal, "lineage_id": lineage, "code": "INVALID_OR_DUPLICATE"}
            )
            continue
        seen.add(lineage)
        row = dict(candidate)
        row["roster_ordinal"] = ordinal
        row["exercise_eligibility"] = exercise_eligibility(row["capability_exercise"])
        admitted.append(row)
    return {
        "admitted": admitted,
        "rejected": rejected,
        "reduction_digest": canonical_sha(
            {
                "admitted": [(r["roster_ordinal"], r["lineage_id"]) for r in admitted],
                "rejected": rejected,
            }
        ),
    }


def exclusive_json(path: Path, body: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    bare = {key: value for key, value in body.items() if key != "authority_sha256"}
    body["authority_sha256"] = canonical_sha(bare)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as error:
        raise Refused(f"single immutable authority already exists: {path}") from error
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(body, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")


def verify_fixed_authority(path: Path, expected: Path, schema: str) -> dict[str, Any]:
    if path.resolve() != expected.resolve():
        raise Refused(f"{path} is not the single authority {expected}; alternates are refused")
    body = read_json(path)
    if body.get("schema") != schema:
        raise Refused(f"authority schema is {body.get('schema')!r}, not {schema!r}")
    claimed = body.get("authority_sha256")
    bare = {key: value for key, value in body.items() if key != "authority_sha256"}
    if claimed != canonical_sha(bare):
        raise Refused("authority self-digest is invalid")
    return body


def verify_acquisition_spent_binding(
    binding: Any, expected_design_bindings: dict[str, Any]
) -> dict[str, Any]:
    """Resolve the one pre-payload corpus-spend authority and its design chain."""
    if not isinstance(binding, dict) or set(binding) != {"path", "sha256", "schema"}:
        raise Refused("acquisition has no exact acquisition-spent authority binding")
    if binding.get("schema") != ACQUISITION_SPENT_SCHEMA:
        raise Refused("acquisition-spent authority schema moved")
    path = (ROOT / str(binding.get("path") or "")).resolve()
    if path != ACQUISITION_SPENT_AUTHORITY.resolve():
        raise Refused("acquisition-spent authority is not the fixed SFIR3 authority")
    if not path.is_file() or sha_file(path) != binding.get("sha256"):
        raise Refused("exact acquisition-spent authority is absent or moved")
    body = verify_fixed_authority(path, ACQUISITION_SPENT_AUTHORITY, ACQUISITION_SPENT_SCHEMA)
    if (
        body.get("protocol_id") != PROTOCOL_ID
        or body.get("state") != "PAYLOAD_READ_AUTHORIZED_CORPUS_SPENT"
        or body.get("single_writer") is not True
        or body.get("design_bindings") != expected_design_bindings
    ):
        raise Refused("acquisition-spent authority does not bind the exact SFIR3 design chain")
    return body


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--write-execution-manifest", type=Path)
    parser.add_argument("--generated-at")
    args = parser.parse_args(argv)
    try:
        if not args.write_execution_manifest or not args.generated_at:
            raise Refused("--write-execution-manifest and --generated-at are required")
        body = write_execution_manifest(args.write_execution_manifest, args.generated_at)
        print(
            json.dumps(
                {
                    "state": "SEALED",
                    "path": relative(args.write_execution_manifest),
                    "content_digest": body["content_digest"],
                },
                indent=2,
            )
        )
        return 0
    except Refused as error:
        print(
            json.dumps({"state": "REFUSED", "why": str(error)}, indent=2),
            file=__import__("sys").stderr,
        )
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
