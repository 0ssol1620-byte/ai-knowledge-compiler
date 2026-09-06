#!/usr/bin/env python3
"""Shared fail-closed execution contracts for the independent SFIR1 study.

This module is intentionally new authority.  It does not import, discover, or
modify any V2R4/SFI3 receipt.  Every upstream design object is supplied by exact
path and file digest; fixed downstream authorities make ambiguity impossible.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]
PROTOCOL_ID = "SOURCE_FACT_IR_INDEPENDENT_REPLICATION_V1"

SCHEMAS = {
    "charter": "tavonel.sfir1.design_charter_freeze.v1",
    "capacity": "tavonel.sfir1.capacity_census_authority.v1",
    "roster": "tavonel.sfir1.lineage_freeze.v1",
    "protocol_freeze": "tavonel.sfir1.protocol_freeze.v1",
}

FRAME_AUTHORITY = NS / "receipts" / "sfir1-frame-authority.json"
SCORE_AUTHORITY = NS / "receipts" / "sfir1-score-authority.json"
ACCEPTANCE_AUTHORITY = NS / "receipts" / "sfir1-acceptance-authority.json"
ACQUISITION = NS / "artifacts" / "development" / "sfir1" / "sfir1_acquisition.json"
OBSERVATION_DIR = NS / "artifacts" / "development" / "sfir1" / "observations"
ACQUISITION_SPENT_AUTHORITY = NS / "receipts" / "sfir1-acquisition-spent-authority.json"
PAYLOAD_CACHE = NS / "artifacts" / "development" / "sfir1_cache"

EXECUTION_TOOLCHAIN_SCHEMA = "tavonel.sfir1.execution_toolchain.v2"

# Hashing only the obvious entry points is not a scientific freeze.  The native
# pair driver loads extractor lanes dynamically, the provenance canonicaliser
# imports the span map flat, and the rebuild judge calls through the compiler
# package.  Those imports can change the measured endpoint outcomes without any
# entry-point byte changing.  Freeze the complete local implementation trees,
# plus every tool that can acquire, frame, score, accept, or verify the freeze.
# Standard-library modules are outside the repository and are instead part of
# the recorded runtime environment; no third-party scientific package is used
# by this path.
EXECUTION_SOURCE_TREES = (
    NS / "acquisition",
    NS / "canonicalization",
    NS / "compiler",
    NS / "source_fact_ir",
)
EXECUTION_ENTRYPOINTS = (
    NS / "tools" / "sfir1_protocol.py",
    NS / "tools" / "sfir1_execution.py",
    NS / "tools" / "sfir1_worker.py",
    NS / "tools" / "sfi1_worker.py",
    NS / "tools" / "sfi2_worker.py",
    NS / "tools" / "score_sfi1.py",
    NS / "tools" / "score_sfi3.py",
    NS / "tools" / "verify_sfir1_frame.py",
    NS / "tools" / "score_sfir1.py",
    NS / "tools" / "sfir1_acceptance.py",
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
    """A scientific authority or immutable binding was not satisfied."""


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def canonical_sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def execution_component_paths() -> dict[str, Path]:
    """Return the closed, deterministic local source set for SFIR1 execution.

    Keys are namespace-relative paths rather than friendly aliases so adding,
    removing, or renaming any Python module in a frozen tree changes the
    component domain as well as its digest.  This deliberately includes modules
    that are reached through ``importlib`` or flat ``sys.path`` imports.
    """
    paths = set(EXECUTION_ENTRYPOINTS)
    for tree in EXECUTION_SOURCE_TREES:
        if not tree.is_dir():
            raise Refused(f"SFIR1 execution source tree is absent: {tree}")
        paths.update(path for path in tree.rglob("*.py") if "__pycache__" not in path.parts)
    components: dict[str, Path] = {}
    for path in sorted(paths, key=lambda item: item.as_posix()):
        if not path.is_file():
            raise Refused(f"SFIR1 execution component is absent: {path}")
        try:
            name = path.resolve().relative_to(NS.resolve()).as_posix()
        except ValueError as error:
            raise Refused(f"SFIR1 execution component escapes namespace: {path}") from error
        components[name] = path
    return components


def execution_toolchain_manifest() -> dict[str, Any]:
    """Exact scientific implementation bytes that a protocol freeze must bind."""
    paths = execution_component_paths()
    components = {
        name: {"path": relative(path), "sha256": sha_file(path)} for name, path in paths.items()
    }
    coverage = {
        "strategy": "closed_python_source_trees_plus_explicit_entrypoints",
        "source_trees": [
            tree.resolve().relative_to(NS.resolve()).as_posix() for tree in EXECUTION_SOURCE_TREES
        ],
        "entrypoints": [
            path.resolve().relative_to(NS.resolve()).as_posix() for path in EXECUTION_ENTRYPOINTS
        ],
        "component_count": len(components),
    }
    body = {
        "schema": EXECUTION_TOOLCHAIN_SCHEMA,
        "coverage": coverage,
        "components": components,
    }
    body["content_digest"] = canonical_sha(body)
    return body


def relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve()).replace("\\", "/")


def read_json(path: Path) -> dict[str, Any]:
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise Refused(f"cannot read immutable JSON {path}: {error}") from error
    if not isinstance(body, dict):
        raise Refused(f"{path} is not a JSON object")
    return body


def verify_receipt(kind: str, path: Path, expected_sha256: str) -> dict[str, Any]:
    """Verify one explicitly named authority.  No search path exists here."""
    if kind not in SCHEMAS:
        raise Refused(f"unknown SFIR1 binding kind {kind!r}")
    if not path.is_file():
        raise Refused(f"exact {kind} receipt is absent: {path}")
    actual = sha_file(path)
    if actual != expected_sha256:
        raise Refused(f"exact {kind} digest mismatch: {actual} != {expected_sha256}")
    try:
        import sfir1_protocol

        body = sfir1_protocol.verify_authority(ROOT, path, expected_sha256, SCHEMAS[kind])
    except Exception as error:
        raise Refused(f"invalid exact {kind} authority: {error}") from error
    return {
        "kind": kind,
        "path": relative(path),
        "sha256": actual,
        "schema": body["schema"],
        "body": body,
    }


def verify_design_bindings(specs: dict[str, tuple[Path, str]]) -> dict[str, Any]:
    missing = [kind for kind in SCHEMAS if kind not in specs]
    if missing:
        raise Refused(f"all exact SFIR1 bindings are mandatory; missing {missing}")
    verified = {kind: verify_receipt(kind, *specs[kind]) for kind in SCHEMAS}
    frozen = verified["protocol_freeze"]["body"]
    for kind in ("charter", "capacity", "roster"):
        reference = frozen.get(kind)
        held = verified[kind]
        if reference != {"path": held["path"], "sha256": held["sha256"]}:
            raise Refused(f"protocol freeze does not bind the exact {kind} authority")
    return {
        kind: {key: row[key] for key in ("path", "sha256", "schema")}
        for kind, row in verified.items()
    }


def reverify_recorded_bindings(recorded: Any) -> dict[str, Any]:
    if not isinstance(recorded, dict) or set(recorded) != set(SCHEMAS):
        raise Refused("acquisition does not carry all four exact design bindings")
    specs: dict[str, tuple[Path, str]] = {}
    for kind, row in recorded.items():
        if not isinstance(row, dict) or set(row) != {"path", "sha256", "schema"}:
            raise Refused(f"recorded {kind} binding has an unexpected shape")
        if row["schema"] != SCHEMAS[kind]:
            raise Refused(f"recorded {kind} binding schema moved")
        path = Path(str(row["path"]))
        specs[kind] = (
            (ROOT / path).resolve() if not path.is_absolute() else path,
            str(row["sha256"]),
        )
    return verify_design_bindings(specs)


def roster_candidates(roster_receipt: dict[str, Any], receipt_path: Path) -> list[dict[str, Any]]:
    """Read the exact ordered roster bound by the lineage-freeze authority."""
    subject = roster_receipt.get("subject")
    if not isinstance(subject, dict) or set(subject) != {"path", "sha256"}:
        raise Refused("lineage freeze has no exact roster subject")
    path = (ROOT / str(subject["path"])).resolve()
    if not path.is_file() or sha_file(path) != subject["sha256"]:
        raise Refused("the exact lineage roster subject is absent or its digest moved")
    raw = read_json(path)
    if (
        raw.get("schema") != "tavonel.sfir1.frozen_roster.v1"
        or raw.get("protocol_id") != PROTOCOL_ID
    ):
        raise Refused("lineage roster subject has wrong schema or protocol")
    candidates = raw.get("candidates")
    if not isinstance(candidates, list):
        raise Refused("lineage roster candidates are not a list")
    seen: set[str] = set()
    clean: list[dict[str, Any]] = []
    for index, row in enumerate(candidates):
        if not isinstance(row, dict):
            raise Refused(f"roster candidate {index} is not an object")
        lineage = row.get("lineage_id")
        family = row.get("family")
        if not isinstance(lineage, str) or not lineage or lineage in seen:
            raise Refused(f"roster candidate {index} has missing or duplicate lineage_id")
        if not isinstance(family, str) or not family:
            raise Refused(f"roster candidate {lineage} has no family")
        flags = row.get("capability_exercise")
        if set(flags or {}) != {"E5", "E6", "E9"} or any(
            type(flags[key]) is not bool for key in flags
        ):
            raise Refused(
                f"roster candidate {lineage} has no exact E5/E6/E9 capability_exercise booleans"
            )
        seen.add(lineage)
        clean.append(dict(row))
    return clean


def exercise_eligibility(flags: dict[str, bool]) -> dict[str, Any]:
    """Pre-score power from capabilities only, never endpoint outcomes."""
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
    """Stable, outcome-blind reduction: roster order then unique lineage id."""
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
                "admitted": [(row["roster_ordinal"], row["lineage_id"]) for row in admitted],
                "rejected": rejected,
            }
        ),
    }


def exclusive_json(path: Path, body: dict[str, Any]) -> None:
    """Create one authority atomically enough to make a second writer refuse."""
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
