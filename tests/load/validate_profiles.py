"""Validate guarded v4 scale profiles and fail-closed evidence receipts."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]
LOAD_DIR = Path(__file__).resolve().parent
CATALOG_PATH = LOAD_DIR / "profiles.json"
CATALOG_SCHEMA_PATH = LOAD_DIR / "scale-profile.schema.json"
EVIDENCE_SCHEMA_PATH = LOAD_DIR / "scale-evidence.schema.json"
SHA256_PREFIX = "sha256:"

EXPECTED_DIMENSIONS: dict[str, dict[str, int | bool]] = {
    "collection_manifest_5000": {
        "files": 5_000,
        "bytes_per_manifest_entry": 1_024,
        "manifest_bytes": 5_120_000,
    },
    "collection_resume_10gib": {
        "files": 10,
        "bytes_per_file": 1_073_741_824,
        "total_bytes": 10_737_418_240,
        "interrupt_after_bytes": 5_368_709_120,
        "browser_restart_boundary": True,
    },
    "preflight_30000_pages": {"known_pages": 30_000, "iterations": 1},
    "processing_ui_1000_pages": {"pages": 1_000},
    "workspace_10000_blocks": {"blocks": 10_000},
    "graph_5000_nodes": {"graph_nodes": 5_000},
    "sse_1000": {"virtual_users": 1_000, "duration_seconds": 300},
    "upload_100": {"virtual_users": 100, "iterations": 100},
    "enqueue_10000_pages": {
        "virtual_users": 1,
        "iterations": 1,
        "fixture_pages": 10_000,
    },
    "mixed_tenant_fairness": {
        "virtual_users": 20,
        "duration_seconds": 900,
        "tenants": 2,
    },
    "export_burst_100": {"virtual_users": 100, "iterations": 100},
}


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: root must be an object")
    return cast(dict[str, Any], value)


def _sha256(path: Path) -> str:
    return SHA256_PREFIX + hashlib.sha256(path.read_bytes()).hexdigest()


def _schema_errors(instance: dict[str, Any], schema_path: Path) -> list[str]:
    schema = _load_json(schema_path)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    return [
        f"{'.'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
        for error in sorted(validator.iter_errors(instance), key=lambda item: list(item.path))
    ]


def _commands(profile: dict[str, Any]) -> list[list[str]]:
    command = profile.get("command")
    if isinstance(command, list):
        return [cast(list[str], command)]
    commands = profile.get("commands")
    if not isinstance(commands, dict):
        return []
    return [cast(list[str], value) for value in commands.values() if isinstance(value, list)]


def validate_catalog() -> list[str]:
    catalog = _load_json(CATALOG_PATH)
    errors = _schema_errors(catalog, CATALOG_SCHEMA_PATH)
    profiles = cast(dict[str, dict[str, Any]], catalog.get("profiles") or {})

    actual_names = set(profiles)
    expected_names = set(EXPECTED_DIMENSIONS)
    if actual_names != expected_names:
        errors.append(
            "profiles: exact readiness set mismatch; "
            f"missing={sorted(expected_names - actual_names)} "
            f"unexpected={sorted(actual_names - expected_names)}"
        )

    for name, expected in EXPECTED_DIMENSIONS.items():
        profile = profiles.get(name)
        if profile is None:
            continue
        if profile.get("dimensions") != expected:
            errors.append(
                f"profiles.{name}.dimensions: expected {expected!r}, "
                f"got {profile.get('dimensions')!r}"
            )
        script_value = profile.get("script")
        script = ROOT / str(script_value)
        try:
            script.relative_to(ROOT)
        except ValueError:
            errors.append(f"profiles.{name}.script: path escapes repository")
            continue
        if not script.is_file():
            errors.append(f"profiles.{name}.script: missing {script_value}")
            continue
        script_text = script.read_text(encoding="utf-8")
        if "NONPRODUCTION_LOAD_ONLY" not in script_text and 'from "./safety.js"' not in script_text:
            errors.append(f"profiles.{name}.script: nonproduction guard is not visible")
        for command in _commands(profile):
            if str(script_value) not in command:
                errors.append(f"profiles.{name}: command does not bind its declared script")
        required_env = cast(list[str], profile.get("required_fixture_env") or [])
        if any(not name.startswith("AKC_") for name in required_env):
            errors.append(f"profiles.{name}.required_fixture_env: non-AKC variable")
        required_metrics = cast(list[str], profile.get("required_evidence_metrics") or [])
        if len(required_metrics) != len(set(required_metrics)):
            errors.append(f"profiles.{name}.required_evidence_metrics: duplicates are forbidden")

    resume = profiles.get("collection_resume_10gib") or {}
    phase_commands = resume.get("commands") or {}
    if set(phase_commands) != {"interrupt", "resume"}:
        errors.append(
            "profiles.collection_resume_10gib.commands: interrupt and resume are required"
        )
    if (profiles.get("upload_100") or {}).get("runner_env") != {
        "AKC_VUS": "100",
        "AKC_ITERATIONS": "100",
        "AKC_SYNTHETIC_CONFIRM": "NONPRODUCTION_SYNTHETIC_ONLY",
    }:
        errors.append("profiles.upload_100.runner_env: exact 100-VU/100-iteration binding required")

    return sorted(set(errors))


def validate_evidence(path: Path) -> list[str]:
    receipt = _load_json(path)
    errors = _schema_errors(receipt, EVIDENCE_SCHEMA_PATH)
    catalog = _load_json(CATALOG_PATH)
    profiles = cast(dict[str, dict[str, Any]], catalog["profiles"])
    profile_name = receipt.get("profile")
    profile = profiles.get(str(profile_name))
    if profile is None:
        errors.append(f"profile: unknown profile {profile_name!r}")
        return sorted(set(errors))

    if receipt.get("catalog_sha256") != _sha256(CATALOG_PATH):
        errors.append("catalog_sha256: does not bind the current profile catalog")
    script = ROOT / str(profile["script"])
    if script.is_file() and receipt.get("script_sha256") != _sha256(script):
        errors.append("script_sha256: does not bind the current harness script")

    fixture = cast(dict[str, Any], receipt.get("fixture") or {})
    observed_dimensions = cast(dict[str, Any], fixture.get("dimensions") or {})
    for key, expected in cast(dict[str, Any], profile["dimensions"]).items():
        if observed_dimensions.get(key) != expected:
            errors.append(
                f"fixture.dimensions.{key}: expected {expected!r}, "
                f"got {observed_dimensions.get(key)!r}"
            )

    execution = cast(dict[str, Any], receipt.get("execution") or {})
    if execution.get("status") != "passed":
        errors.append("execution.status: only passed receipts are gate-admissible")

    target = cast(dict[str, Any], receipt.get("target") or {})
    if target.get("production") is not False:
        errors.append("target.production: must be false")
    if target.get("environment") not in {"development", "staging", "performance"}:
        errors.append("target.environment: must be an explicit nonproduction class")
    if target.get("revision_verified") is not True:
        errors.append("target.revision_verified: independent revision evidence is required")
    if target.get("origin_allowlist_match") is not True:
        errors.append("target.origin_allowlist_match: exact-origin evidence is required")

    observations = cast(list[dict[str, Any]], receipt.get("observations") or [])
    names = [str(item.get("name")) for item in observations]
    if len(names) != len(set(names)):
        errors.append("observations: metric names must be unique")
    required_metrics = set(cast(list[str], profile["required_evidence_metrics"]))
    missing_metrics = required_metrics.difference(names)
    if missing_metrics:
        errors.append(f"observations: missing required metrics {sorted(missing_metrics)}")
    if any(item.get("passed") is not True for item in observations):
        errors.append("observations: every recorded threshold must pass")

    acceptance = cast(dict[str, Any], receipt.get("acceptance") or {})
    if acceptance.get("all_required_metrics_present") is not True:
        errors.append("acceptance.all_required_metrics_present: must be true")
    if acceptance.get("all_thresholds_passed") is not True:
        errors.append("acceptance.all_thresholds_passed: must be true")

    cleanup = cast(dict[str, Any], receipt.get("cleanup") or {})
    if profile.get("mutates_target") is True:
        if cleanup.get("required") is not True or cleanup.get("completed") is not True:
            errors.append("cleanup: mutating profiles require a completed cleanup receipt")
        if cleanup.get("receipt_sha256") is None:
            errors.append("cleanup.receipt_sha256: required for mutating profiles")

    declarations = cast(dict[str, Any], receipt.get("declarations") or {})
    if declarations != {
        "nonproduction_only": True,
        "deployment_performed_by_harness": False,
        "production_slo_proven": False,
        "release_gate_closed": False,
        "confirmation": "NONPRODUCTION_LOAD_ONLY",
    }:
        errors.append("declarations: receipt must remain diagnostic and nonproduction-only")
    return sorted(set(errors))


def emit_not_run(profile_name: str, output: Path) -> None:
    catalog = _load_json(CATALOG_PATH)
    profiles = cast(dict[str, dict[str, Any]], catalog["profiles"])
    if profile_name not in profiles:
        raise ValueError(f"unknown profile: {profile_name}")
    profile = profiles[profile_name]
    script = ROOT / str(profile["script"])
    zero_sha = SHA256_PREFIX + ("0" * 64)
    receipt: dict[str, Any] = {
        "schema_version": "1.0.0",
        "profile": profile_name,
        "catalog_sha256": _sha256(CATALOG_PATH),
        "script_sha256": _sha256(script),
        "harness_revision": "0" * 40,
        "target": {
            "origin": "https://nonproduction.invalid",
            "environment": "development",
            "production": False,
            "deployment_revision": "0" * 40,
            "revision_verified": False,
            "revision_evidence_sha256": None,
            "origin_allowlist_match": False,
            "origin_allowlist_sha256": None,
        },
        "fixture": {
            "synthetic": True,
            "customer_data": False,
            "manifest_sha256": zero_sha,
            "attestation_sha256": zero_sha,
            "dimensions": profile["dimensions"],
        },
        "execution": {
            "status": "not_run",
            "started_at": None,
            "finished_at": None,
            "exit_code": None,
            "command_sha256": None,
            "raw_summary_sha256": None,
        },
        "observations": [],
        "acceptance": {
            "all_required_metrics_present": False,
            "all_thresholds_passed": False,
        },
        "cleanup": {
            "required": bool(profile["mutates_target"]),
            "completed": False,
            "receipt_sha256": None,
        },
        "declarations": {
            "nonproduction_only": True,
            "deployment_performed_by_harness": False,
            "production_slo_proven": False,
            "release_gate_closed": False,
            "confirmation": "NONPRODUCTION_LOAD_ONLY",
        },
    }
    errors = _schema_errors(receipt, EVIDENCE_SCHEMA_PATH)
    if errors:
        raise ValueError("invalid not-run template: " + "; ".join(errors))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")


def print_commands(profile_name: str) -> None:
    catalog = _load_json(CATALOG_PATH)
    profiles = cast(dict[str, dict[str, Any]], catalog["profiles"])
    if profile_name not in profiles:
        raise ValueError(f"unknown profile: {profile_name}")
    profile = profiles[profile_name]
    print(f"profile={profile_name}")
    print("required_guard=AKC_LOAD_CONFIRM=NONPRODUCTION_LOAD_ONLY")
    required_env = ",".join(cast(list[str], profile["required_fixture_env"]))
    print(f"required_fixture_env={required_env}")
    runner_env = cast(dict[str, str], profile.get("runner_env") or {})
    for name, value in sorted(runner_env.items()):
        print(f"runner_env={name}={value}")
    for command in _commands(profile):
        print("command=" + " ".join(command))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--print-command", metavar="PROFILE")
    parser.add_argument("--emit-not-run", nargs=2, metavar=("PROFILE", "OUTPUT"))
    args = parser.parse_args()

    catalog_errors = validate_catalog()
    if catalog_errors:
        for error in catalog_errors:
            print(error)
        return 1
    if args.print_command:
        print_commands(args.print_command)
        return 0
    if args.emit_not_run:
        profile_name, output_value = args.emit_not_run
        emit_not_run(profile_name, Path(output_value))
        print(f"not-run evidence template written: {output_value}")
        return 0
    if args.evidence:
        evidence_errors = validate_evidence(args.evidence)
        if evidence_errors:
            for error in evidence_errors:
                print(error)
            return 1
        print("nonproduction scale evidence is gate-admissible")
        return 0
    print("nonproduction scale profile catalog validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
