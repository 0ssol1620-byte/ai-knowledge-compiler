from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
V01 = ROOT / "research" / "experiments" / "SEM-RISK-CONF-01"
V02 = Path(__file__).resolve().parent
AMENDMENT = V02 / "transport-amendment.json"
FREEZE = V02 / "receipts" / "transport-amendment-freeze.json"

IDENTICAL_FILES = (
    "protocol.json",
    "selection-manifest.json",
    "receipts/protocol-freeze.json",
    "receipts/selection-seal.json",
    "run_lane_a_native.py",
    "build_inference_manifests.py",
    "evaluate_confirmatory.py",
)
TRANSPORT_FILES = (
    "freeze_transport_amendment.py",
    "acquire_selected_inputs.py",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def canonical_sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def main() -> int:
    if AMENDMENT.exists() or FREEZE.exists():
        raise SystemExit("transport amendment already frozen; immutable")

    identical: dict[str, str] = {}
    for rel in IDENTICAL_FILES:
        source = V01 / rel
        target = V02 / rel
        if not source.is_file() or not target.is_file():
            raise RuntimeError(f"required frozen file missing: {rel}")
        source_hash = sha256_file(source)
        target_hash = sha256_file(target)
        if source_hash != target_hash:
            raise RuntimeError(f"V02 science artifact differs from V01: {rel}")
        identical[rel] = source_hash

    protocol = json.loads((V02 / "protocol.json").read_text(encoding="utf-8"))
    selection = json.loads((V02 / "selection-manifest.json").read_text(encoding="utf-8"))
    protocol_freeze = json.loads((V02 / "receipts" / "protocol-freeze.json").read_text(encoding="utf-8"))
    selection_seal = json.loads((V02 / "receipts" / "selection-seal.json").read_text(encoding="utf-8"))
    if sha256_file(V02 / "protocol.json") != protocol_freeze.get("protocol_sha256"):
        raise RuntimeError("copied protocol does not match the original freeze receipt")
    if sha256_file(V02 / "selection-manifest.json") != selection_seal.get("selection_sha256"):
        raise RuntimeError("copied selection does not match the original selection seal")
    if selection.get("counts") != {"development_exclusions": 18, "lane_a": 64, "lane_b": 64, "total": 128}:
        raise RuntimeError("scientific selection counts changed")

    # Reverify every source hash that V01 froze.  This protects the scientific
    # implementation while the transport layer is amended around it.
    verified_source_hashes: dict[str, str] = {}
    for rel, expected in protocol.get("source_hashes", {}).items():
        path = ROOT / rel
        if not path.is_file():
            raise RuntimeError(f"frozen science source missing: {rel}")
        observed = sha256_file(path)
        if observed != expected:
            raise RuntimeError(f"frozen science source changed after V01 freeze: {rel}")
        verified_source_hashes[rel] = observed

    transport_hashes = {rel: sha256_file(V02 / rel) for rel in TRANSPORT_FILES}
    amendment: dict[str, Any] = {
        "schema": "tavonel.semantic-risk.confirmatory.transport-amendment.v1",
        "scientific_experiment_id": protocol["experiment_id"],
        "transport_version": "V02",
        "classification": "TRANSPORT_ONLY_AMENDMENT_BEFORE_CONFIRMATORY_OBSERVATION",
        "parent_protocol_sha256": protocol_freeze["protocol_sha256"],
        "parent_selection_sha256": selection_seal["selection_sha256"],
        "scientific_parameters_changed": False,
        "selected_cases_changed": False,
        "routing_policy_changed": False,
        "evaluation_changed": False,
        "model_identity_changed": False,
        "ground_truth_observed_before_amendment": False,
        "gpu_inference_observed_before_amendment": False,
        "v01_transport_failure": {
            "stage": "input_acquisition",
            "http_status": 404,
            "persisted_files": {"lane_a_images": 64, "lane_a_source_pdfs": 64, "lane_b_images": 0},
            "result_rows": 0,
            "ground_truth_acquired": False,
            "gpu_seconds": 0.0,
            "cause": "current v1.6 annotation image_path is a basename while repository storage path is under images/",
        },
        "amended_transport_rule": {
            "lane_a": "unchanged exact selected tree paths at source-native pre-deletion revision",
            "lane_b": (
                "paginate the complete exact-revision images tree, index by basename, and require exactly one tree path "
                "for every already-selected basename before any Lane B download"
            ),
            "pagination": "follow RFC5988 Link rel=next until absent; fail on repeated cursor/url",
            "resolution_fail_closed": True,
            "download_retries": {
                "attempts": 3,
                "retry_statuses": [429, 500, 502, 503, 504],
                "backoff_seconds": [1.0, 2.0],
                "other_http_statuses": "fail immediately",
            },
        },
        "byte_identical_v01_artifacts": identical,
        "verified_v01_frozen_source_hashes": verified_source_hashes,
        "transport_source_hashes": transport_hashes,
    }
    V02.mkdir(parents=True, exist_ok=True)
    (V02 / "receipts").mkdir(parents=True, exist_ok=True)
    AMENDMENT.write_text(json.dumps(amendment, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    freeze = {
        "transport_version": "V02",
        "parent_protocol_sha256": protocol_freeze["protocol_sha256"],
        "parent_selection_sha256": selection_seal["selection_sha256"],
        "transport_amendment_sha256": sha256_file(AMENDMENT),
        "transport_source_hashes": transport_hashes,
        "science_identity_sha256": canonical_sha({"identical": identical, "frozen_sources": verified_source_hashes}),
    }
    FREEZE.write_text(json.dumps(freeze, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"transport_version": "V02", "frozen": True, "scientific_parameters_changed": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
