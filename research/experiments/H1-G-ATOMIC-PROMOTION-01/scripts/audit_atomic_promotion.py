#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
EXP = Path(__file__).resolve().parents[1]
PROTOCOL = EXP / "PROTOCOL_2026-08-19.md"
SCRIPT = Path(__file__).resolve()
WORLD = ROOT / "packages" / "cir-python" / "src" / "akc_cir" / "world_state.py"
BUILD = ROOT / "packages" / "cir-python" / "src" / "akc_cir" / "build_receipt.py"
WORLD_TEST = ROOT / "tests" / "unit" / "test_world_state.py"
BUILD_TEST = ROOT / "tests" / "unit" / "test_build_receipt.py"
PINNED = (PROTOCOL, SCRIPT, WORLD, BUILD, WORLD_TEST, BUILD_TEST)

REQUIRED = {
    "test_a_checksum_mismatch_blocks_the_publish": WORLD_TEST,
    "test_a_blocked_publish_leaves_the_old_state_serving": WORLD_TEST,
    "test_failed_validation_blocks_the_publish": WORLD_TEST,
    "test_an_unrun_permission_check_blocks_the_publish": WORLD_TEST,
    "test_a_rejected_candidate_cannot_be_published_on_a_retry": WORLD_TEST,
    "test_publishing_something_never_staged_is_refused": WORLD_TEST,
    "test_a_selective_build_without_an_equivalence_check_is_refused": WORLD_TEST,
    "test_a_selective_build_that_diverges_is_refused": WORLD_TEST,
    "test_a_successful_publish_emits_exactly_one_event": WORLD_TEST,
    "test_a_refused_publish_emits_nothing": WORLD_TEST,
    "test_rollback_restores_the_previous_state": WORLD_TEST,
    "test_rolling_back_to_an_unpublished_candidate_is_refused": WORLD_TEST,
    "test_a_receipt_from_the_prior_revision_is_refused": BUILD_TEST,
    "test_a_receipt_for_another_artifact_is_refused": BUILD_TEST,
    "test_a_receipt_describing_other_bytes_is_refused": BUILD_TEST,
    "test_inputs_that_moved_since_the_build_are_refused": BUILD_TEST,
    "test_editing_any_sealed_field_breaks_the_seal": BUILD_TEST,
    "test_an_untracked_builder_is_refused_rather_than_detected": BUILD_TEST,
    "test_the_permissive_path_downgrades_rather_than_passes": BUILD_TEST,
    "test_no_argument_combination_promotes_an_untracked_build": BUILD_TEST,
    "test_the_tracked_flag_cannot_be_restored_by_editing_the_receipt": BUILD_TEST,
}


def sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha(value: Any) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(body.encode()).hexdigest()


def rel(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT)).replace("\\", "/")


def write_hashed(path: Path, body: dict[str, Any], field: str) -> None:
    body[field] = canonical_sha(body)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def required_presence() -> dict[str, bool]:
    cache = {path: path.read_text(encoding="utf-8") for path in {WORLD_TEST, BUILD_TEST}}
    return {name: f"def {name}" in cache[path] for name, path in REQUIRED.items()}


def freeze(output: Path) -> int:
    presence = required_presence()
    if not all(presence.values()):
        missing = [name for name, present in presence.items() if not present]
        raise RuntimeError(f"required contract tests missing before freeze: {missing}")
    seal: dict[str, Any] = {
        "schema": "tavonel.atomic-promotion-audit-seal.v1",
        "frozen_at": datetime.now(UTC).isoformat(),
        "evidence_class": "CONTROLLED_IMPLEMENTATION_CONTRACT_AUDIT",
        "pinned_files": {rel(path): sha(path) for path in PINNED},
        "required_contract_tests": sorted(REQUIRED),
        "pytest_targets": [rel(WORLD_TEST), rel(BUILD_TEST)],
        "decision_rule": "PASS only if all required tests remain present and pytest exits zero",
    }
    write_hashed(output, seal, "seal_sha256")
    print(f"frozen {rel(output)}")
    return 0


def verify_seal(path: Path) -> dict[str, Any]:
    seal = json.loads(path.read_text(encoding="utf-8"))
    recorded = seal["seal_sha256"]
    bare = {key: value for key, value in seal.items() if key != "seal_sha256"}
    if canonical_sha(bare) != recorded:
        raise RuntimeError("seal self-hash mismatch")
    live = {rel(item): sha(item) for item in PINNED}
    if seal["pinned_files"] != live:
        raise RuntimeError("pinned implementation/test bytes drifted")
    return seal


def run(seal_path: Path, output: Path) -> int:
    seal = verify_seal(seal_path.resolve())
    presence = required_presence()
    command = [
        str(ROOT / ".venv" / "Scripts" / "python.exe"),
        "-m",
        "pytest",
        "-q",
        rel(WORLD_TEST),
        rel(BUILD_TEST),
    ]
    result = subprocess.run(  # noqa: S603
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    combined = (result.stdout + "\n" + result.stderr).strip()
    match = re.search(r"(\d+) passed", combined)
    passed_count = int(match.group(1)) if match else None
    success = result.returncode == 0 and all(presence.values())
    receipt: dict[str, Any] = {
        "schema": "tavonel.atomic-promotion-contract-audit.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "evidence_class": "CONTROLLED_IMPLEMENTATION_CONTRACT_AUDIT",
        "seal_path": rel(seal_path),
        "seal_file_sha256": sha(seal_path),
        "seal_sha256": seal["seal_sha256"],
        "pinned_files": seal["pinned_files"],
        "required_contract_tests": presence,
        "all_required_contract_tests_present": all(presence.values()),
        "command": command,
        "cwd": str(ROOT),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "pytest_exit_code": result.returncode,
        "pytest_passed_count": passed_count,
        "pytest_output_tail": combined[-4000:],
        "primary_success": success,
        "external_gpu_cost_usd": 0.0,
        "trust_boundary": (
            "Pass is controlled implementation/unit-contract evidence only. It does not prove "
            "distributed crash atomicity or complete capture of arbitrary builder reads."
        ),
    }
    write_hashed(output, receipt, "receipt_sha256")
    print(f"required tests present: {sum(presence.values())}/{len(presence)}")
    print(f"pytest passed count:    {passed_count}")
    print(f"primary success:        {success}")
    print(f"wrote {rel(output)}")
    return 0 if success else 2


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    freeze_parser = sub.add_parser("freeze")
    freeze_parser.add_argument("--output", required=True, type=Path)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--seal", required=True, type=Path)
    run_parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "freeze":
        return freeze(args.output)
    return run(args.seal, args.output)


if __name__ == "__main__":
    raise SystemExit(main())
