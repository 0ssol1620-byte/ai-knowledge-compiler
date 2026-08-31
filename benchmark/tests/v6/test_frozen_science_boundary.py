"""Regression guard: nothing in D1-D6 may have disturbed the frozen
SEM-RISK-CONF-02 science boundary, the pinned runner files, or
confirmatory_pod_controller.py's inert-by-default shape.

Hash comparisons are reimplemented directly here (same approach as
research/experiments/SEM-RISK-CONF-02/verify_frozen_integrity.py) rather than
imported from that script, since it is a standalone script, not a package.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
V02 = ROOT / "research/experiments/SEM-RISK-CONF-02"
RECEIPTS = V02 / "receipts"
CANDIDATE_REGISTRY_PATH = ROOT / "benchmark/v6/candidate-registry.yaml"
PROTOCOL_PATH = V02 / "protocol.json"

PINNED_RUNNER_FILES = (
    "benchmark/runpod_eval/paddleocr_vl_stage2.py",
    "benchmark/runpod_eval/mineru_stage2.py",
    "benchmark/runpod_eval/input_contract.py",
    "benchmark/runpod_eval/isolated_case_process.py",
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# SEM-RISK-CONF-02 frozen artifact hashes vs their own receipts
# --------------------------------------------------------------------------


def test_protocol_json_hash_matches_protocol_freeze_receipt() -> None:
    protocol_freeze = _load_json(RECEIPTS / "protocol-freeze.json")
    assert _sha256_file(PROTOCOL_PATH) == protocol_freeze["protocol_sha256"]


def test_selection_manifest_hash_matches_selection_seal_receipt() -> None:
    selection_seal = _load_json(RECEIPTS / "selection-seal.json")
    assert _sha256_file(V02 / "selection-manifest.json") == selection_seal["selection_sha256"]


def test_transport_amendment_hash_matches_its_own_freeze_receipt() -> None:
    transport_freeze = _load_json(RECEIPTS / "transport-amendment-freeze.json")
    assert (
        _sha256_file(V02 / "transport-amendment.json")
        == transport_freeze["transport_amendment_sha256"]
    )
    # And the freeze receipt's parent pins must still agree with the current
    # protocol/selection hashes checked above.
    assert transport_freeze["parent_protocol_sha256"] == _sha256_file(PROTOCOL_PATH)
    assert transport_freeze["parent_selection_sha256"] == _sha256_file(
        V02 / "selection-manifest.json"
    )


def test_v02_copies_of_v01_scripts_match_the_transport_amendment_byte_identical_pins() -> None:
    transport_amendment = _load_json(V02 / "transport-amendment.json")
    byte_identical = transport_amendment["byte_identical_v01_artifacts"]
    relative_names = (
        "evaluate_confirmatory.py",
        "run_lane_a_native.py",
        "build_inference_manifests.py",
    )
    for relative_name in relative_names:
        expected_hash = byte_identical[relative_name]
        observed_hash = _sha256_file(V02 / relative_name)
        assert observed_hash == expected_hash, (
            f"{relative_name} no longer matches its byte-identical-to-V01 pin"
        )


# --------------------------------------------------------------------------
# Candidate registry and pinned runner files vs protocol.json source_hashes
# --------------------------------------------------------------------------


def test_candidate_registry_hash_matches_protocol_pin() -> None:
    protocol = _load_json(PROTOCOL_PATH)
    source_hashes = protocol["source_hashes"]
    expected = source_hashes["benchmark/v6/candidate-registry.yaml"]
    assert _sha256_file(CANDIDATE_REGISTRY_PATH) == expected


def test_all_four_pinned_runner_files_match_protocol_source_hashes() -> None:
    protocol = _load_json(PROTOCOL_PATH)
    source_hashes = protocol["source_hashes"]
    for relative_path in PINNED_RUNNER_FILES:
        expected = source_hashes[relative_path]
        observed = _sha256_file(ROOT / relative_path)
        assert observed == expected, f"{relative_path} no longer matches its protocol pin"


# --------------------------------------------------------------------------
# confirmatory_pod_controller.py inert-by-default shape
# --------------------------------------------------------------------------


def test_confirmatory_pod_controller_execute_defaults_to_unarmed() -> None:
    import inspect

    import infra.runpod.v6.confirmatory_pod_controller as module

    signature = inspect.signature(module.execute)
    assert signature.parameters["armed"].default is False


def test_confirmatory_pod_controller_has_no_main_or_cli() -> None:
    source = Path(
        __import__(
            "infra.runpod.v6.confirmatory_pod_controller", fromlist=["__file__"]
        ).__file__
    ).read_text(encoding="utf-8")
    assert 'if __name__ == "__main__"' not in source
    assert "import argparse" not in source
    assert "from_environment" not in source
