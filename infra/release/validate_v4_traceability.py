"""Validate the Structara v4 release ledger and deployment truth snapshot."""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Final

ROOT: Final = Path(__file__).resolve().parents[2]
TRACEABILITY_PATH: Final = ROOT / "V4_MASTERPLAN_TRACEABILITY.md"
AUDIT_PATH: Final = ROOT / "CURRENT_STATE_AUDIT_V4.md"
MANIFEST_PATH: Final = ROOT / "docs" / "release" / "V4_DEPLOYMENT_MANIFEST.json"

AUTHORITY_BASENAME: Final = (
    "Structara_World_Class_Autonomous_Knowledge_Platform_"
    "FINAL_Completion_Masterplan_v4_KO_2026-07-31.md"
)
RELEASE_MARKER: Final = "**Release status:** **Production Reject**"
VALID_STATUSES: Final = frozenset(
    {"implemented", "local-contract", "external-evidence-required", "blocked"}
)

EXPECTED_SECTION_IDS: Final = tuple(f"S{index:02d}" for index in range(49))
EXPECTED_WAVE_IDS: Final = tuple(f"W{index:02d}" for index in range(12))
DOD_GROUP_COUNTS: Final = {
    "BRAND": 4,
    "INGESTION": 6,
    "CREDITS": 5,
    "INTELLIGENCE": 5,
    "KNOWLEDGE": 7,
    "UX": 5,
    "QUALITY": 6,
    "OPERATIONS": 7,
}
EXPECTED_DOD_IDS: Final = tuple(
    f"DOD-{group}-{index:02d}"
    for group, count in DOD_GROUP_COUNTS.items()
    for index in range(1, count + 1)
)
EXPECTED_GATE_IDS: Final = (
    "G44-UNIT",
    "G44-E2E",
    "G44-VISUAL",
    "G44-BROWSER",
    "G44-A11Y",
    "G44-PERF",
    "G44-SECURITY",
    "G45-SCORE",
    "G45-ZERO",
    *(f"G46-{index:02d}" for index in range(1, 11)),
    *(f"G47-{index:02d}" for index in range(1, 12)),
)
EXPECTED_IDS: Final = frozenset(
    (*EXPECTED_SECTION_IDS, *EXPECTED_WAVE_IDS, *EXPECTED_DOD_IDS, *EXPECTED_GATE_IDS)
)
TRACKED_ID_RE: Final = re.compile(
    r"(?:S\d{2}|W\d{2}|DOD-[A-Z]+-\d{2}|G(?:44|45)-[A-Z0-9]+|G(?:46|47)-\d{2})"
)
GIT_SHA_RE: Final = re.compile(r"[0-9a-f]{40}")


def extract_status_rows(markdown: str) -> list[tuple[str, str]]:
    """Extract tracked identifier and status cells from Markdown tables."""

    rows: list[tuple[str, str]] = []
    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if not line.startswith("|") or not line.endswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 3 or TRACKED_ID_RE.fullmatch(cells[0]) is None:
            continue
        rows.append((cells[0], cells[2]))
    return rows


def validate_traceability_text(markdown: str) -> list[str]:
    """Return all traceability coverage and status errors."""

    errors: list[str] = []
    if RELEASE_MARKER not in markdown:
        errors.append("traceability release marker must remain Production Reject")
    if AUTHORITY_BASENAME not in markdown:
        errors.append("traceability does not name the v4 authority masterplan")

    rows = extract_status_rows(markdown)
    identifiers = [identifier for identifier, _status in rows]
    counts = Counter(identifiers)
    for identifier, count in sorted(counts.items()):
        if count != 1:
            errors.append(f"traceability identifier {identifier} appears {count} times")

    observed_ids = set(identifiers)
    for identifier in sorted(EXPECTED_IDS - observed_ids):
        errors.append(f"traceability identifier {identifier} is missing")
    for identifier in sorted(observed_ids - EXPECTED_IDS):
        errors.append(f"unexpected traceability identifier {identifier}")

    for identifier, status in rows:
        if status not in VALID_STATUSES:
            allowed = ", ".join(sorted(VALID_STATUSES))
            errors.append(f"{identifier} has invalid status {status!r}; expected one of {allowed}")

    return errors


_MISSING: Final = object()


def _lookup(document: object, path: tuple[str, ...]) -> object:
    current = document
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return _MISSING
        current = current[key]
    return current


def validate_manifest_document(document: object) -> list[str]:
    """Validate that the deployment snapshot preserves fail-closed release truth."""

    errors: list[str] = []
    if not isinstance(document, dict):
        return ["deployment manifest root must be a JSON object"]

    required_values: dict[tuple[str, ...], object] = {
        ("schema_version",): "1.0.0",
        ("manifest_kind",): "v4_deployment_truth_snapshot",
        ("release_status",): "production_reject",
        ("promotion_authorized",): False,
        ("repository", "worktree_clean"): False,
        ("deployment", "state"): "ready",
        ("deployment", "deployed_commit_sha"): None,
        ("deployment", "commit_sha_exposed"): False,
        ("deployment", "latest_commit_confirmed_deployed"): False,
        ("deployment", "deployment_predates_latest_commit"): True,
        ("deployment", "deployed_latest_match"): False,
        ("live_probe", "health_payload", "commit_sha"): None,
        ("hosted_ci", "latest_commit_sha_covered"): False,
        ("decision", "verdict"): "Production Reject",
    }
    for path, expected in required_values.items():
        actual = _lookup(document, path)
        dotted_path = ".".join(path)
        if actual is _MISSING:
            errors.append(f"deployment manifest is missing {dotted_path}")
        elif actual != expected:
            errors.append(f"deployment manifest {dotted_path} must be {expected!r}, got {actual!r}")

    for sha_path in (
        ("repository", "latest_commit_sha"),
        ("hosted_ci", "latest_observed_run_sha"),
    ):
        value = _lookup(document, sha_path)
        if not isinstance(value, str) or GIT_SHA_RE.fullmatch(value) is None:
            errors.append(f"deployment manifest {'.'.join(sha_path)} must be a 40-char git SHA")

    latest_sha = _lookup(document, ("repository", "latest_commit_sha"))
    ci_sha = _lookup(document, ("hosted_ci", "latest_observed_run_sha"))
    if isinstance(latest_sha, str) and latest_sha == ci_sha:
        errors.append(
            "hosted CI SHA unexpectedly equals latest SHA while coverage is declared false"
        )

    routes = _lookup(document, ("live_probe", "routes"))
    route_statuses: dict[str, int] = {}
    if not isinstance(routes, list):
        errors.append("deployment manifest live_probe.routes must be a list")
    else:
        for route in routes:
            if not isinstance(route, dict):
                continue
            route_path = route.get("path")
            status_code = route.get("status_code")
            if isinstance(route_path, str) and type(status_code) is int:
                route_statuses[route_path] = status_code
    required_routes = {
        "/": 200,
        "/api/health": 200,
        "/admin": 200,
        "/benchmarks": 200,
        "/v1/health/live": 404,
        "/v1/health/ready": 404,
        "/v1/admin/health": 404,
    }
    for route_path, expected_status in required_routes.items():
        if route_statuses.get(route_path) != expected_status:
            errors.append(
                f"deployment manifest route {route_path} must retain observed status "
                f"{expected_status}"
            )

    gates = _lookup(document, ("open_external_gates",))
    if not isinstance(gates, list) or not gates:
        errors.append("deployment manifest must list open external gates")
    else:
        gate_ids: list[str] = []
        for gate in gates:
            if not isinstance(gate, dict):
                errors.append("each external gate must be a JSON object")
                continue
            gate_id = gate.get("id")
            if not isinstance(gate_id, str) or not gate_id:
                errors.append("each external gate must have a non-empty id")
            else:
                gate_ids.append(gate_id)
            if gate.get("status") != "open":
                errors.append(f"external gate {gate_id!r} must remain open in this snapshot")
        duplicate_gate_ids = [gate_id for gate_id, count in Counter(gate_ids).items() if count > 1]
        for gate_id in sorted(duplicate_gate_ids):
            errors.append(f"external gate {gate_id} is duplicated")

    blocker_count = _lookup(document, ("decision", "blocking_condition_count"))
    if type(blocker_count) is not int or blocker_count < 1:
        errors.append("deployment manifest must retain at least one blocking condition")

    return errors


def validate_repository(root: Path = ROOT) -> list[str]:
    """Validate all v4 release evidence files under ``root``."""

    errors: list[str] = []
    traceability_path = root / TRACEABILITY_PATH.relative_to(ROOT)
    audit_path = root / AUDIT_PATH.relative_to(ROOT)
    manifest_path = root / MANIFEST_PATH.relative_to(ROOT)

    if not traceability_path.is_file():
        errors.append(f"missing {traceability_path.relative_to(root).as_posix()}")
    else:
        errors.extend(validate_traceability_text(traceability_path.read_text(encoding="utf-8")))

    if not audit_path.is_file():
        errors.append(f"missing {audit_path.relative_to(root).as_posix()}")
    else:
        audit = audit_path.read_text(encoding="utf-8")
        if RELEASE_MARKER not in audit:
            errors.append("current-state audit release marker must remain Production Reject")
        if AUTHORITY_BASENAME not in audit:
            errors.append("current-state audit does not name the v4 authority masterplan")

    manifest: object = None
    if not manifest_path.is_file():
        errors.append(f"missing {manifest_path.relative_to(root).as_posix()}")
    else:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"deployment manifest is not valid JSON: {exc}")
        else:
            errors.extend(validate_manifest_document(manifest))

    if isinstance(manifest, dict) and audit_path.is_file():
        deployment_id = _lookup(manifest, ("deployment", "deployment_id"))
        audit = audit_path.read_text(encoding="utf-8")
        if isinstance(deployment_id, str) and deployment_id not in audit:
            errors.append("current-state audit does not reference the manifest deployment id")

    return errors


def main() -> int:
    """CLI entry point."""

    errors = validate_repository()
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(
        "v4 release traceability valid: 49 sections, 12 waves, 45 DoD items, "
        "30 release-critical checks; verdict=Production Reject"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
