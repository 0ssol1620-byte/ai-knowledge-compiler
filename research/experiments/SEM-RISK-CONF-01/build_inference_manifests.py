from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

EXPERIMENT = Path(__file__).resolve().parent
PROTOCOL = EXPERIMENT / "protocol.json"
FREEZE = EXPERIMENT / "receipts" / "protocol-freeze.json"
SELECTION = EXPERIMENT / "selection-manifest.json"
SELECTION_SEAL = EXPERIMENT / "receipts" / "selection-seal.json"
ACQUISITION = EXPERIMENT / "receipts" / "acquisition-receipt.json"
OUTPUT_DIR = EXPERIMENT / "inference-manifests"
RECEIPT = EXPERIMENT / "receipts" / "inference-manifest-seal.json"


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def bound_manifest(*, benchmark_id: str, revision: str, inputs: list[dict[str, str]]) -> dict[str, Any]:
    content: dict[str, Any] = {
        "schema": "folynta.public-core-inference-inputs.v1",
        "benchmark_id": benchmark_id,
        "dataset_revision": revision,
        "ground_truth_mounted": False,
        "input_count": len(inputs),
        "source_count": len(inputs),
        "complete_input_coverage": True,
        "complete_source_coverage": True,
        "inputs": inputs,
    }
    digest = "sha256:" + hashlib.sha256(canonical(content).encode()).hexdigest()
    return {**content, "content_sha256": digest}


def main() -> int:
    if OUTPUT_DIR.exists() or RECEIPT.exists():
        raise SystemExit("inference manifests already exist; refusing ambiguous resume")
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    selection = json.loads(SELECTION.read_text(encoding="utf-8"))
    selection_seal = json.loads(SELECTION_SEAL.read_text(encoding="utf-8"))
    acquisition = json.loads(ACQUISITION.read_text(encoding="utf-8"))
    if sha256_file(PROTOCOL) != freeze.get("protocol_sha256"):
        raise RuntimeError("protocol hash mismatch")
    if sha256_file(SELECTION) != selection_seal.get("selection_sha256"):
        raise RuntimeError("selection hash mismatch")
    if acquisition.get("ground_truth_acquired") is not False:
        raise RuntimeError("ground truth isolation invariant violated")

    acquired = {
        (str(item["lane"]), str(item["kind"]), str(item["page_stem"])): item
        for item in acquisition["files"]
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=False)
    manifests: dict[str, str] = {}
    for lane, cases, revision in (
        ("a", selection["lane_a"], protocol["dataset"]["source_native_pre_deletion_revision"]),
        ("b", selection["lane_b"], protocol["dataset"]["current_v1_6_revision"]),
    ):
        inputs: list[dict[str, str]] = []
        for case in cases:
            stem = str(case["page_stem"])
            item = acquired.get((lane, "image", stem))
            if item is None:
                raise RuntimeError(f"acquired image missing for lane {lane} case {stem}")
            local = EXPERIMENT / str(item["path"])
            root = EXPERIMENT / "corpus" / f"lane-{lane}" / "images"
            relative = local.relative_to(root).as_posix()
            if sha256_file(local) != item["sha256"]:
                raise RuntimeError(f"image hash mismatch for {stem}")
            inputs.append(
                {
                    "case_id": stem,
                    "input_relative_path": relative,
                    "input_sha256": str(item["sha256"]),
                }
            )
        manifest = bound_manifest(
            benchmark_id=f"sem-risk-conf-01-lane-{lane}",
            revision=str(revision),
            inputs=inputs,
        )
        path = OUTPUT_DIR / f"lane-{lane}-public-core.json"
        path.write_text(canonical(manifest) + "\n", encoding="utf-8")
        manifests[lane] = sha256_file(path)

    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text(
        json.dumps(
            {
                "experiment_id": protocol["experiment_id"],
                "protocol_sha256": sha256_file(PROTOCOL),
                "selection_sha256": sha256_file(SELECTION),
                "manifests": manifests,
                "ground_truth_mounted": False,
                "paddle_repeats": {"lane_a": 1, "lane_b": 3},
                "specialist_repeats": {"lane_a": 1, "lane_b": 1},
            },
            indent=2,
            sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"manifests": manifests, "ground_truth_mounted": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
