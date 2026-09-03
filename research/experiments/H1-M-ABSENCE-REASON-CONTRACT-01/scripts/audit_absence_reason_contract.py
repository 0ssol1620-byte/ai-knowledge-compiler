#!/usr/bin/env python3
"""Controlled implementation contract audit for claim A2's absence record.

Same shape as `H1-G-ATOMIC-PROMOTION-01`: freeze the pinned bytes and the
required test names first, then run and refuse if anything drifted. The audit
proves what the implementation records, not how often real documents trigger it.
"""

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
PROTOCOL = EXP / "PROTOCOL_2026-08-20.md"
SCRIPT = Path(__file__).resolve()
IDENTITY = ROOT / "packages" / "cir-python" / "src" / "akc_cir" / "identity.py"
CONTRACT_TEST = ROOT / "tests" / "unit" / "test_absence_reason_contract.py"
PINNED = (PROTOCOL, SCRIPT, IDENTITY, CONTRACT_TEST)

#: Recital observable -> the test that produces it. Two of these are break
#: controls: without them a vacuously passing audit would look identical.
REQUIRED = {
    "test_an_abstention_records_the_identities_of_the_present_signals": "recital: present",
    "test_an_abstention_records_the_identities_of_the_absent_signals": "recital: absent",
    "test_each_absent_signal_carries_an_enumerated_absence_reason": "recital: reason",
    "test_present_and_absent_are_disjoint_and_a_signal_is_never_zero_filled": "N4.4 no zero-fill",
    "test_an_absence_abstention_names_the_absent_critical_signal_in_its_reason": "operator record",
    "test_a_complete_evaluation_records_no_absence": "POSITIVE CONTROL",
    "test_an_absence_abstention_is_distinguishable_from_a_complete_evaluation": "recital: distinct",
    "test_an_absence_abstention_is_distinguishable_from_a_tie_abstention": "recital: distinct",
    "test_a_failure_to_evaluate_produces_no_decision_at_all": "recital: distinct",
    "test_the_absence_record_survives_serialization": "serialization",
    "test_the_contract_predicate_refuses_a_zero_filled_absence": "BREAK CONTROL",
    "test_the_contract_predicate_refuses_an_unenumerated_absence_reason": "BREAK CONTROL",
}

TRUST_BOUNDARY = (
    "Controlled implementation/unit-contract evidence only. It establishes what the live "
    "implementation records when an identity signal has no value. It does not measure how "
    "often absence occurs in real documents, and it does not establish that MissingReason "
    "enumerates every possible absence cause."
)


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
    source = CONTRACT_TEST.read_text(encoding="utf-8")
    return {name: f"def {name}" in source for name in REQUIRED}


def freeze(output: Path) -> int:
    presence = required_presence()
    if not all(presence.values()):
        missing = sorted(name for name, present in presence.items() if not present)
        raise RuntimeError(f"required contract tests missing before freeze: {missing}")
    seal: dict[str, Any] = {
        "schema": "tavonel.absence-reason-contract-audit-seal.v1",
        "experiment": "H1-M-ABSENCE-REASON-CONTRACT-01",
        "frozen_at": datetime.now(UTC).isoformat(),
        "evidence_class": "CONTROLLED_IMPLEMENTATION_CONTRACT_AUDIT",
        "pinned_files": {rel(path): sha(path) for path in PINNED},
        "required_contract_tests": REQUIRED,
        "pytest_targets": [rel(CONTRACT_TEST)],
        "decision_rule": (
            "PASS only if every required test remains present by name and pytest exits zero"
        ),
        "trust_boundary": TRUST_BOUNDARY,
    }
    write_hashed(output, seal, "seal_sha256")
    print(f"frozen {rel(output)}")
    return 0


def verify_seal(path: Path) -> dict[str, Any]:
    seal = json.loads(path.read_text(encoding="utf-8"))
    bare = {key: value for key, value in seal.items() if key != "seal_sha256"}
    if canonical_sha(bare) != seal["seal_sha256"]:
        raise RuntimeError("seal self-hash mismatch")
    live = {rel(item): sha(item) for item in PINNED}
    if seal["pinned_files"] != live:
        drifted = sorted(k for k, v in live.items() if seal["pinned_files"].get(k) != v)
        raise RuntimeError(f"pinned bytes drifted: {drifted}")
    return seal


def run(seal_path: Path, output: Path) -> int:
    seal = verify_seal(seal_path.resolve())
    presence = required_presence()
    command = [
        str(ROOT / ".venv" / "Scripts" / "python.exe"),
        "-m",
        "pytest",
        "-q",
        "-p",
        "no:randomly",
        rel(CONTRACT_TEST),
    ]
    result = subprocess.run(  # noqa: S603
        command, cwd=ROOT, capture_output=True, text=True, timeout=300, check=False
    )
    combined = (result.stdout + "\n" + result.stderr).strip()
    match = re.search(r"(\d+) passed", combined)
    passed_count = int(match.group(1)) if match else None
    success = result.returncode == 0 and all(presence.values())
    receipt: dict[str, Any] = {
        "schema": "tavonel.absence-reason-contract-audit.v1",
        "experiment": "H1-M-ABSENCE-REASON-CONTRACT-01",
        "generated_at": datetime.now(UTC).isoformat(),
        "evidence_class": "CONTROLLED_IMPLEMENTATION_CONTRACT_AUDIT",
        "claim_element": "A2 element 1",
        "seal_path": rel(seal_path),
        "seal_file_sha256": sha(seal_path),
        "seal_sha256": seal["seal_sha256"],
        "pinned_files": seal["pinned_files"],
        "required_contract_tests": presence,
        "all_required_contract_tests_present": all(presence.values()),
        "positive_control_present": presence["test_a_complete_evaluation_records_no_absence"],
        "break_controls_present": (
            presence["test_the_contract_predicate_refuses_a_zero_filled_absence"]
            and presence["test_the_contract_predicate_refuses_an_unenumerated_absence_reason"]
        ),
        "enumerated_absence_reasons": [
            "MODEL_UNAVAILABLE",
            "NOT_APPLICABLE",
            "RESOURCE_LIMIT",
            "ERROR",
        ],
        "absence_taxonomy_completeness_claimed": False,
        "command": command,
        "cwd": str(ROOT),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "pytest_exit_code": result.returncode,
        "pytest_passed_count": passed_count,
        "pytest_output_tail": combined[-4000:],
        "primary_success": success,
        "external_gpu_cost_usd": 0.0,
        "trust_boundary": TRUST_BOUNDARY,
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
