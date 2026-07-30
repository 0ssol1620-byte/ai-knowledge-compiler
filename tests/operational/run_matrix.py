"""Run bounded operational scenarios and emit tamper-evident local receipts."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[2]
MATRIX_PATH = Path(__file__).with_name("scenario-matrix.json")
MAX_CAPTURE_CHARS = 8_000


def load_matrix() -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads(MATRIX_PATH.read_text(encoding="utf-8")),
    )


def resolve_command(command: list[str]) -> list[str]:
    return [sys.executable if value == "{python}" else value for value in command]


def git_revision() -> str | None:
    git = shutil.which("git")
    if git is None:
        return None
    result = subprocess.run(  # noqa: S603 - executable is resolved from PATH
        [git, "rev-parse", "HEAD"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    revision = result.stdout.strip()
    return revision if result.returncode == 0 and len(revision) == 40 else None


def digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def run_scenario(scenario: dict[str, Any]) -> dict[str, Any]:
    if scenario["class"] == "external_scale":
        raise ValueError("external-scale profiles require an explicitly approved deployment")
    if scenario.get("manual_opt_in"):
        raise ValueError("guarded chaos scenarios require direct operator opt-in")

    command = resolve_command(scenario["command"])
    started = time.monotonic()
    result = subprocess.run(  # noqa: S603 - command is selected from a versioned matrix
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=900,
    )
    duration_ms = round((time.monotonic() - started) * 1000)
    combined = result.stdout + "\n" + result.stderr
    return {
        "schema_version": "1.0.0",
        "scenario_id": scenario["id"],
        "matrix_id": "akc-operational-evidence-v1",
        "recorded_at": datetime.now(UTC).isoformat(),
        "git_revision": git_revision(),
        "command": command,
        "status": "passed" if result.returncode == 0 else "failed",
        "exit_code": result.returncode,
        "duration_ms": duration_ms,
        "output_sha256": digest(combined),
        "stdout_tail": result.stdout[-MAX_CAPTURE_CHARS:],
        "stderr_tail": result.stderr[-MAX_CAPTURE_CHARS:],
        "deployment_evidence": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--scenario")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    scenarios = load_matrix()["scenarios"]
    if args.list:
        for scenario in scenarios:
            print(f"{scenario['id']}\t{scenario['class']}\t{scenario['name']}")
        return 0
    if not args.scenario or args.output is None:
        parser.error("--scenario and --output are required unless --list is used")
    selected = next((item for item in scenarios if item["id"] == args.scenario), None)
    if selected is None:
        parser.error(f"unknown scenario: {args.scenario}")

    receipt = run_scenario(selected)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0 if receipt["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
