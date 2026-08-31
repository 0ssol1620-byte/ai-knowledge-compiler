from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

EXPERIMENT = Path(__file__).resolve().parent
PROTOCOL = EXPERIMENT / "protocol.json"
PROTOCOL_FREEZE = EXPERIMENT / "receipts" / "protocol-freeze.json"
SELECTION = EXPERIMENT / "selection-manifest.json"
SELECTION_SEAL = EXPERIMENT / "receipts" / "selection-seal.json"
OUTPUT = EXPERIMENT / "outputs" / "lane-a-native"
SUMMARY = OUTPUT / "run-summary.json"
RECEIPT = EXPERIMENT / "receipts" / "lane-a-native-freeze.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def canonical_sha(value: Any) -> str:
    return sha256_bytes(canonical_bytes(value))


def git_head() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=EXPERIMENT,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def main() -> int:
    if RECEIPT.exists():
        raise SystemExit("lane A native freeze already exists; immutable")

    # 1. Re-verify protocol.json and selection-manifest.json hashes still match
    # their frozen receipts before proceeding.
    for path in (PROTOCOL, PROTOCOL_FREEZE, SELECTION, SELECTION_SEAL):
        if not path.is_file():
            raise RuntimeError(f"required artifact missing: {path}")
    protocol_freeze = json.loads(PROTOCOL_FREEZE.read_text(encoding="utf-8"))
    selection_seal = json.loads(SELECTION_SEAL.read_text(encoding="utf-8"))
    protocol_sha256 = sha256_file(PROTOCOL)
    selection_sha256 = sha256_file(SELECTION)
    if protocol_sha256 != protocol_freeze.get("protocol_sha256"):
        raise RuntimeError("protocol.json no longer matches its frozen receipt")
    if selection_sha256 != selection_seal.get("selection_sha256"):
        raise RuntimeError("selection-manifest.json no longer matches its sealed receipt")

    # 2. Confirm the native run summary exists and carries the expected
    # invariants for a GPU-free, ground-truth-isolated Lane A native run.
    if not SUMMARY.is_file():
        raise RuntimeError(f"run summary missing: {SUMMARY}")
    summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
    if summary.get("input_count") != 64:
        raise RuntimeError(f"expected input_count == 64, got {summary.get('input_count')!r}")
    if summary.get("gpu_seconds") != 0.0:
        raise RuntimeError(f"expected gpu_seconds == 0.0, got {summary.get('gpu_seconds')!r}")
    if summary.get("ground_truth_mounted") is not False:
        raise RuntimeError(f"expected ground_truth_mounted is False, got {summary.get('ground_truth_mounted')!r}")

    # 3. Re-hash every one of the 65 files in outputs/lane-a-native/
    # independently, and cross-check each case file's independently computed
    # hash against the artifact_sha256 the runner itself recorded.
    case_files = sorted(p for p in OUTPUT.iterdir() if p.is_file() and p.name != "run-summary.json")
    if len(case_files) != 64:
        raise RuntimeError(f"expected 64 case files, found {len(case_files)}")

    self_reported = {case["case_id"]: case.get("artifact_sha256") for case in summary.get("cases", [])}
    case_artifact_sha256: dict[str, str] = {}
    mismatches: list[str] = []
    for path in case_files:
        stem = path.stem
        recomputed = sha256_file(path)
        case_artifact_sha256[stem] = recomputed
        expected = self_reported.get(stem)
        if expected is None:
            raise RuntimeError(f"run-summary.json has no case entry for {stem}")
        if recomputed != expected:
            mismatches.append(stem)
    if mismatches:
        raise RuntimeError(f"independently recomputed hash mismatch for cases: {mismatches}")

    native_output_summary_sha256 = sha256_file(SUMMARY)

    # 4. Confirm there are exactly 65 files in outputs/lane-a-native/ (64 case
    # files + run-summary.json) — no stray extras.
    all_files = sorted(p for p in OUTPUT.iterdir() if p.is_file())
    if len(all_files) != 65:
        raise RuntimeError(f"expected exactly 65 files in {OUTPUT}, found {len(all_files)}: {[p.name for p in all_files]}")

    # Derive failure class distribution from each case's recorded error field.
    failure_classes: dict[str, int] = {}
    for path in case_files:
        record = json.loads(path.read_text(encoding="utf-8"))
        error = record.get("error")
        if error is not None:
            failure_classes[error] = failure_classes.get(error, 0) + 1

    # 5. Record the environment — the pypdf version actually installed is the
    # reproducibility anchor for the Lane A native-peer signal since the repo
    # pins a range (>=6.15,<7), not an exact version.
    environment = {
        "python_version": platform.python_version(),
        "pypdf_version": importlib.metadata.version("pypdf"),
        "platform": sys.platform,
    }

    receipt: dict[str, Any] = {
        "schema": "tavonel.sem-risk-conf.lane-a-native-freeze.v1",
        "frozen_at": datetime.now(UTC).isoformat(),
        "git_head": git_head(),
        "protocol_sha256": protocol_sha256,
        "selection_sha256": selection_sha256,
        "native_output_summary_sha256": native_output_summary_sha256,
        "case_artifact_sha256": case_artifact_sha256,
        "input_count": summary["input_count"],
        "completed": summary["completed"],
        "failed": summary["failed"],
        "failure_classes": failure_classes,
        "gpu_seconds": summary["gpu_seconds"],
        "estimated_cost_usd": summary["estimated_cost_usd"],
        "ground_truth_mounted": summary["ground_truth_mounted"],
        "environment": environment,
    }
    receipt["freeze_sha256"] = canonical_sha(receipt)

    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "frozen": True,
                "input_count": receipt["input_count"],
                "completed": receipt["completed"],
                "failed": receipt["failed"],
                "case_hash_matches": len(case_artifact_sha256) - len(mismatches),
                "case_hash_mismatches": len(mismatches),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
