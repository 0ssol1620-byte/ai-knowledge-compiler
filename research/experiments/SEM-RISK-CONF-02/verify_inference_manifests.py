"""Read-only, independent verification of the D3 inference manifests.

This script performs NO mutation of any frozen artifact and does not touch
`build_inference_manifests.py`. It re-verifies the two generated manifests
(`inference-manifests/lane-a-public-core.json`,
`inference-manifests/lane-b-public-core.json`) through a DIFFERENT code path
than the generator: the frozen, already-tested `select_inference_inputs` /
`adaptive_repeat_indices` contract in `benchmark/runpod_eval/input_contract.py`.

`select_inference_inputs` enforces, among other things, that the on-disk
image inventory for a lane's `input_dir` is set-EQUAL to the manifest's file
set for `evidence_class="public-core"`. A clean (non-raising) call is
therefore the mechanical proof that no ground-truth file (or any other stray
file) sits alongside the images for either lane.

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
EXPERIMENT = Path(__file__).resolve().parent
ACQUISITION = EXPERIMENT / "receipts" / "acquisition-receipt.json"
INFERENCE_MANIFESTS = EXPERIMENT / "inference-manifests"
RECEIPTS = EXPERIMENT / "receipts"
VERIFICATIONS_DIR = RECEIPTS / "integrity-verifications"

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp"}
EXPECTED_INPUT_COUNT = 64
EXPECTED_CORPUS_FILE_COUNT = 192

sys.path.insert(0, str(ROOT / "benchmark" / "runpod_eval"))

from input_contract import adaptive_repeat_indices, select_inference_inputs  # noqa: E402


def canonical_sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


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


def verify_lane(lane: str) -> dict[str, Any]:
    manifest_path = INFERENCE_MANIFESTS / f"lane-{lane}-public-core.json"
    input_dir = EXPERIMENT / "corpus" / f"lane-{lane}" / "images"
    selection = select_inference_inputs(
        input_dir=input_dir,
        supported_extensions=SUPPORTED_EXTENSIONS,
        limit=0,
        evidence_class="public-core",
        expected_input_count=EXPECTED_INPUT_COUNT,
        input_manifest=manifest_path,
    )
    return {
        "content_sha256": selection.input_manifest_sha256,
        "input_count": len(selection.selected),
        "contract_complete": selection.complete_input_coverage,
        "benchmark_id": selection.benchmark_id,
        "dataset_revision": selection.dataset_revision,
    }


def verify_repeat_shapes() -> bool:
    single = adaptive_repeat_indices(evidence_class="public-core", repeats=1, repeat_start_index=1)
    finalist = adaptive_repeat_indices(evidence_class="public-core", repeats=3, repeat_start_index=1)
    return single == (1,) and finalist == (1, 2, 3)


def verify_corpus_unchanged() -> tuple[bool, list[str]]:
    acquisition = load_json(ACQUISITION)
    expected_paths = {entry["path"] for entry in acquisition.get("files", [])}

    corpus_root = EXPERIMENT / "corpus"
    actual_paths: set[str] = set()
    if corpus_root.is_dir():
        for path in corpus_root.rglob("*"):
            if path.is_dir():
                continue
            if "__pycache__" in path.parts:
                continue
            rel = path.relative_to(EXPERIMENT).as_posix()
            actual_paths.add(rel)

    extraneous = sorted(actual_paths - expected_paths)
    missing = sorted(expected_paths - actual_paths)
    ground_truth_absent = not extraneous and not missing and len(expected_paths) == EXPECTED_CORPUS_FILE_COUNT
    return ground_truth_absent, extraneous


def main() -> int:
    lane_a = verify_lane("a")
    lane_b = verify_lane("b")
    repeat_shapes_legal = verify_repeat_shapes()
    ground_truth_absent, corpus_extraneous_files = verify_corpus_unchanged()

    all_passed = (
        lane_a["contract_complete"] is True
        and lane_b["contract_complete"] is True
        and repeat_shapes_legal
        and ground_truth_absent
    )

    VERIFICATIONS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt_path = VERIFICATIONS_DIR / f"manifest-verification-{timestamp}.json"
    if receipt_path.exists():
        suffix = 1
        while True:
            candidate = VERIFICATIONS_DIR / f"manifest-verification-{timestamp}-{suffix}.json"
            if not candidate.exists():
                receipt_path = candidate
                break
            suffix += 1

    receipt: dict[str, Any] = {
        "schema": "tavonel.sem-risk-conf.manifest-verification.v1",
        "verified_at": timestamp,
        "git_head": git_head(),
        "lane_a": lane_a,
        "lane_b": lane_b,
        "ground_truth_absent": ground_truth_absent,
        "corpus_extraneous_files": corpus_extraneous_files,
        "repeat_shapes_legal": repeat_shapes_legal,
        "all_checks_passed": all_passed,
    }
    receipt["receipt_sha256"] = canonical_sha(receipt)

    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print(json.dumps({"all_checks_passed": all_passed, "receipt_path": str(receipt_path)}, sort_keys=True))

    if not all_passed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
