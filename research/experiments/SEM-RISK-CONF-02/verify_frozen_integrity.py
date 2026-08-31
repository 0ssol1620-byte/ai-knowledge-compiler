"""Read-only frozen-integrity verifier for SEM-RISK-CONF-02.

This script performs NO mutation of any frozen artifact. It only reads
files already frozen by `freeze_transport_amendment.py` and the
acquisition step, recomputes their hashes, and writes exactly one new
timestamped receipt under `receipts/integrity-verifications/`.

It takes no arguments and never overwrites a prior verification receipt.
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
V01 = ROOT / "research" / "experiments" / "SEM-RISK-CONF-01"
V02 = Path(__file__).resolve().parent
RECEIPTS = V02 / "receipts"
VERIFICATIONS_DIR = RECEIPTS / "integrity-verifications"

EXPECTED_COUNTS = {"development_exclusions": 18, "lane_a": 64, "lane_b": 64, "total": 128}
EXPECTED_TOTAL_BYTES = 121465686
EXPECTED_FILE_COUNT = 192


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def canonical_sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def add_check(checks: list[dict[str, Any]], name: str, expected: Any, observed: Any) -> bool:
    ok = expected == observed
    checks.append({"name": name, "expected": expected, "observed": observed, "pass": ok})
    return ok


def git_head() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except Exception as exc:  # pragma: no cover - defensive, environment dependent
        return f"UNKNOWN: {exc}"


def run_v02_transport_science_checks(checks: list[dict[str, Any]]) -> None:
    protocol_path = V02 / "protocol.json"
    selection_path = V02 / "selection-manifest.json"
    amendment_path = V02 / "transport-amendment.json"

    protocol = load_json(protocol_path)
    selection = load_json(selection_path)
    amendment = load_json(amendment_path)
    protocol_freeze = load_json(RECEIPTS / "protocol-freeze.json")
    selection_seal = load_json(RECEIPTS / "selection-seal.json")
    transport_freeze = load_json(RECEIPTS / "transport-amendment-freeze.json")
    acquisition = load_json(RECEIPTS / "acquisition-receipt.json")

    protocol_sha = sha256_file(protocol_path)
    add_check(checks, "protocol_sha256 matches protocol-freeze.json", protocol_freeze.get("protocol_sha256"), protocol_sha)
    add_check(
        checks,
        "protocol_sha256 matches transport-amendment-freeze.json.parent_protocol_sha256",
        transport_freeze.get("parent_protocol_sha256"),
        protocol_sha,
    )
    add_check(
        checks,
        "protocol_sha256 matches acquisition-receipt.json.protocol_sha256",
        acquisition.get("protocol_sha256"),
        protocol_sha,
    )

    selection_sha = sha256_file(selection_path)
    add_check(checks, "selection_sha256 matches selection-seal.json", selection_seal.get("selection_sha256"), selection_sha)
    add_check(
        checks,
        "selection_sha256 matches transport-amendment-freeze.json.parent_selection_sha256",
        transport_freeze.get("parent_selection_sha256"),
        selection_sha,
    )
    add_check(
        checks,
        "selection_sha256 matches acquisition-receipt.json.selection_sha256",
        acquisition.get("selection_sha256"),
        selection_sha,
    )

    amendment_sha = sha256_file(amendment_path)
    add_check(
        checks,
        "transport-amendment.json sha256 matches transport-amendment-freeze.json.transport_amendment_sha256",
        transport_freeze.get("transport_amendment_sha256"),
        amendment_sha,
    )

    # byte-identical-to-V01 artifacts
    identical = amendment.get("byte_identical_v01_artifacts", {})
    for rel, expected_hash in identical.items():
        v01_path = V01 / rel
        v02_path = V02 / rel
        v01_exists = v01_path.is_file()
        v02_exists = v02_path.is_file()
        add_check(checks, f"byte-identical artifact exists: {rel} (V01)", True, v01_exists)
        add_check(checks, f"byte-identical artifact exists: {rel} (V02)", True, v02_exists)
        if v01_exists and v02_exists:
            v01_hash = sha256_file(v01_path)
            v02_hash = sha256_file(v02_path)
            add_check(checks, f"byte-identical artifact V01==V02: {rel}", v01_hash, v02_hash)
            add_check(checks, f"byte-identical artifact V01 matches recorded hash: {rel}", expected_hash, v01_hash)
            add_check(checks, f"byte-identical artifact V02 matches recorded hash: {rel}", expected_hash, v02_hash)

    # verified frozen source hashes
    verified_sources = amendment.get("verified_v01_frozen_source_hashes", {})
    for rel, expected_hash in verified_sources.items():
        path = ROOT / rel
        exists = path.is_file()
        add_check(checks, f"frozen source exists: {rel}", True, exists)
        if exists:
            observed_hash = sha256_file(path)
            add_check(checks, f"frozen source hash matches: {rel}", expected_hash, observed_hash)

    # science_identity_sha256 recomputation
    science_identity = canonical_sha({"identical": identical, "frozen_sources": verified_sources})
    add_check(
        checks,
        "science_identity_sha256 recomputation matches transport-amendment-freeze.json",
        transport_freeze.get("science_identity_sha256"),
        science_identity,
    )

    # selection-manifest.json counts
    add_check(checks, "selection-manifest.json counts", EXPECTED_COUNTS, selection.get("counts"))


def run_input_inventory_checks(checks: list[dict[str, Any]]) -> dict[str, Any]:
    acquisition = load_json(RECEIPTS / "acquisition-receipt.json")
    files = acquisition.get("files", [])

    add_check(checks, "acquisition-receipt.json file_count field", EXPECTED_FILE_COUNT, acquisition.get("file_count"))
    add_check(checks, "acquisition-receipt.json files array length", EXPECTED_FILE_COUNT, len(files))

    missing_files: list[str] = []
    hash_mismatches: list[str] = []
    size_mismatches: list[str] = []
    total_bytes_observed = 0
    for entry in files:
        rel_path = entry.get("path", "")
        abs_path = V02 / rel_path
        expected_hash = entry.get("sha256")
        expected_bytes = entry.get("bytes")
        if not abs_path.is_file():
            missing_files.append(rel_path)
            continue
        observed_hash = sha256_file(abs_path)
        observed_bytes = abs_path.stat().st_size
        total_bytes_observed += observed_bytes
        if observed_hash != expected_hash:
            hash_mismatches.append(rel_path)
        if observed_bytes != expected_bytes:
            size_mismatches.append(rel_path)

    add_check(checks, "all 192 inventory files exist on disk", [], missing_files)
    add_check(checks, "all 192 inventory files sha256 match recorded value", [], hash_mismatches)
    add_check(checks, "all 192 inventory files byte size matches recorded value", [], size_mismatches)

    recorded_total = sum(entry.get("bytes", 0) for entry in files)
    add_check(checks, "sum of recorded byte sizes equals acquisition-receipt.json.total_bytes", acquisition.get("total_bytes"), recorded_total)
    add_check(checks, "recorded total_bytes equals expected constant", EXPECTED_TOTAL_BYTES, acquisition.get("total_bytes"))
    add_check(checks, "sum of on-disk observed byte sizes equals recorded total_bytes", acquisition.get("total_bytes"), total_bytes_observed)

    # distribution by (lane, kind)
    distribution: dict[str, int] = {}
    for entry in files:
        key = f"{entry.get('lane')}:{entry.get('kind')}"
        distribution[key] = distribution.get(key, 0) + 1
    expected_distribution = {"a:image": 64, "a:source_pdf": 64, "b:image": 64}
    add_check(checks, "distribution by (lane, kind)", expected_distribution, distribution)

    # page_stems match selection-manifest.json
    selection = load_json(V02 / "selection-manifest.json")
    selection_lane_a_stems = {item["page_stem"] for item in selection.get("lane_a", [])}
    selection_lane_b_stems = {item["page_stem"] for item in selection.get("lane_b", [])}
    inventory_lane_a_stems = {entry["page_stem"] for entry in files if entry.get("lane") == "a"}
    inventory_lane_b_stems = {entry["page_stem"] for entry in files if entry.get("lane") == "b"}
    add_check(
        checks,
        "inventory lane_a page_stems match selection-manifest.json lane_a",
        sorted(selection_lane_a_stems),
        sorted(inventory_lane_a_stems),
    )
    add_check(
        checks,
        "inventory lane_b page_stems match selection-manifest.json lane_b",
        sorted(selection_lane_b_stems),
        sorted(inventory_lane_b_stems),
    )

    add_check(checks, "acquisition-receipt.json ground_truth_acquired is False", False, acquisition.get("ground_truth_acquired"))
    add_check(checks, "acquisition-receipt.json gpu_seconds == 0.0", 0.0, acquisition.get("gpu_seconds"))
    add_check(
        checks,
        "acquisition-receipt.json lane_b_unique_transport_resolutions == 64",
        64,
        acquisition.get("lane_b_unique_transport_resolutions"),
    )
    add_check(checks, "acquisition-receipt.json transport_version == V02", "V02", acquisition.get("transport_version"))

    return {
        "file_count": acquisition.get("file_count"),
        "total_bytes": acquisition.get("total_bytes"),
        "distribution": distribution,
        "missing_files": missing_files,
        "hash_mismatches": hash_mismatches,
        "size_mismatches": size_mismatches,
    }


def run_ground_truth_absence_checks(checks: list[dict[str, Any]]) -> tuple[bool, list[str]]:
    acquisition = load_json(RECEIPTS / "acquisition-receipt.json")
    protocol = load_json(V02 / "protocol.json")

    expected_paths = {entry["path"] for entry in acquisition.get("files", [])}

    corpus_root = V02 / "corpus"
    actual_paths: set[str] = set()
    if corpus_root.is_dir():
        for path in corpus_root.rglob("*"):
            if path.is_dir():
                continue
            if "__pycache__" in path.parts:
                continue
            rel = path.relative_to(V02).as_posix()
            actual_paths.add(rel)

    extraneous = sorted(actual_paths - expected_paths)
    missing_from_corpus = sorted(expected_paths - actual_paths)

    add_check(checks, "corpus/ file set exactly equals acquisition-receipt.json 192-file path set (no extras)", [], extraneous)
    add_check(checks, "corpus/ file set exactly equals acquisition-receipt.json 192-file path set (no missing)", [], missing_from_corpus)

    dev_exclusion_stems = set(protocol.get("development_exclusion", {}).get("page_stems", []))
    leaked_dev_stems: list[str] = []
    for stem in dev_exclusion_stems:
        for path in actual_paths:
            if stem in path:
                leaked_dev_stems.append(f"{stem} -> {path}")
    add_check(checks, "no development-exclusion page_stem appears anywhere in corpus/", [], leaked_dev_stems)

    ground_truth_absent = not extraneous and not leaked_dev_stems

    outputs_exists = (V02 / "outputs").exists()
    inference_manifests_exists = (V02 / "inference-manifests").exists()
    checks.append(
        {
            "name": "outputs/ directory existence snapshot (informational)",
            "expected": "recorded",
            "observed": outputs_exists,
            "pass": True,
        }
    )
    checks.append(
        {
            "name": "inference-manifests/ directory existence snapshot (informational)",
            "expected": "recorded",
            "observed": inference_manifests_exists,
            "pass": True,
        }
    )

    return ground_truth_absent, extraneous


def main() -> int:
    checks: list[dict[str, Any]] = []

    run_v02_transport_science_checks(checks)
    input_inventory = run_input_inventory_checks(checks)
    ground_truth_absent, corpus_extraneous_files = run_ground_truth_absence_checks(checks)

    environment = {
        "python_version": platform.python_version(),
        "sys_platform": sys.platform,
        "git_head": git_head(),
    }

    all_checks_passed = all(c["pass"] for c in checks)

    VERIFICATIONS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt_path = VERIFICATIONS_DIR / f"verification-{timestamp}.json"
    # Guarantee append-only: never overwrite a prior receipt. Timestamps are
    # unique to the second; if a collision somehow occurs, suffix instead of
    # clobbering.
    if receipt_path.exists():
        suffix = 1
        while True:
            candidate = VERIFICATIONS_DIR / f"verification-{timestamp}-{suffix}.json"
            if not candidate.exists():
                receipt_path = candidate
                break
            suffix += 1

    receipt: dict[str, Any] = {
        "schema": "tavonel.sem-risk-conf.frozen-integrity-verification.v1",
        "verified_at": timestamp,
        "git_head": environment["git_head"],
        "all_checks_passed": all_checks_passed,
        "checks": checks,
        "input_inventory": input_inventory,
        "ground_truth_absent": ground_truth_absent,
        "corpus_extraneous_files": corpus_extraneous_files,
        "environment": environment,
    }
    receipt["receipt_sha256"] = canonical_sha(receipt)

    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(json.dumps({"all_checks_passed": all_checks_passed, "receipt_path": str(receipt_path)}, sort_keys=True))

    if not all_checks_passed:
        failed = [c["name"] for c in checks if not c["pass"]]
        print(json.dumps({"failed_checks": failed}, sort_keys=True), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
