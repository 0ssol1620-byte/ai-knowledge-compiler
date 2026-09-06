"""Controls for the additive V2R4 -> SFI3 reservation handoff."""

from __future__ import annotations

import ast
import copy
import json
import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
TOOLS = NS / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import v2r4_sfi3_reservation_handoff as bridge  # noqa: E402


@pytest.fixture(scope="module")
def green_body() -> dict:
    return bridge.build()


def _reader_mutating(monkeypatch, target: Path, mutate):
    original = bridge._read_json

    def reader(path: Path):
        body = original(path)
        if path == target:
            body = copy.deepcopy(body)
            mutate(body)
        return body

    monkeypatch.setattr(bridge, "_read_json", reader)


def test_00_green_exact_handoff_passes_and_freeze_has_no_pointer(monkeypatch, green_body):
    assert bridge.verify(green_body)["held"] is True
    assert green_body["declared_containers_sha256"] == bridge.canonical_sha(
        green_body["declared_containers"]
    )
    assert green_body["declared_container_counts"] == {
        "git_docs": 44,
        "regulation_ecfr": 88,
        "sec_edgar": 0,
    }
    assert green_body["separation_corroboration"]["collision_count"] == 0
    calls = []
    monkeypatch.setattr(
        bridge,
        "write_immutable",
        lambda *args, **kwargs: calls.append((args, kwargs)) or {"receipt": "fixture"},
    )
    frozen = bridge.freeze()
    assert frozen["written"]["receipt"] == "fixture"
    assert calls[0][1]["pointer"] is False


def test_01_wrong_reservation_receipt_path_fails(monkeypatch):
    monkeypatch.setattr(bridge, "RESERVATION_PATH", bridge.FRAME_ATTESTATION_PATH)
    with pytest.raises(bridge.HandoffRefused, match="wrong exact receipt path"):
        bridge.build()


def test_02_wrong_reservation_file_sha_fails(monkeypatch):
    monkeypatch.setattr(bridge, "RESERVATION_FILE_SHA256", "sha256:" + "0" * 64)
    with pytest.raises(bridge.HandoffRefused, match="file digest mismatch"):
        bridge.build()


def test_03_reservation_created_after_measurement_fails(monkeypatch):
    _reader_mutating(
        monkeypatch,
        bridge.RESERVATION_PATH,
        lambda body: body["provenance"].update(
            {"generated_at": "2026-08-26T07:00:00+00:00"}
        ),
    )
    with pytest.raises(bridge.HandoffRefused, match="chronology failed"):
        bridge.build()


def test_04_reservation_content_digest_mismatch_fails(monkeypatch):
    _reader_mutating(
        monkeypatch,
        bridge.RESERVATION_PATH,
        lambda body: body.update({"content_digest": "sha256:" + "1" * 64}),
    )
    with pytest.raises(bridge.HandoffRefused, match="equivalence failed"):
        bridge.build()


def test_05_sfi3_frame_module_digest_mismatch_fails(monkeypatch):
    _reader_mutating(
        monkeypatch,
        bridge.RESERVATION_PATH,
        lambda body: body.update({"frame_module_sha256": "sha256:" + "2" * 64}),
    )
    with pytest.raises(bridge.HandoffRefused, match="equivalence failed"):
        bridge.build()


def test_06_replacement_module_digest_mismatch_fails(monkeypatch):
    _reader_mutating(
        monkeypatch,
        bridge.RESERVATION_PATH,
        lambda body: body.update({"replacement_module_sha256": "sha256:" + "3" * 64}),
    )
    with pytest.raises(bridge.HandoffRefused, match="equivalence failed"):
        bridge.build()


def test_07_wrong_historical_frame_attestation_fails(monkeypatch):
    monkeypatch.setattr(bridge, "FRAME_ATTESTATION_PATH", bridge.ACQUISITION_FRAME_PATH)
    with pytest.raises(bridge.HandoffRefused, match="wrong exact receipt path"):
        bridge.build()


def test_08_historical_frame_attestation_digest_mismatch_fails(monkeypatch):
    monkeypatch.setattr(bridge, "FRAME_ATTESTATION_FILE_SHA256", "sha256:" + "4" * 64)
    with pytest.raises(bridge.HandoffRefused, match="file digest mismatch"):
        bridge.build()


def test_09_declared_container_drift_fails_verification(monkeypatch, green_body):
    original = bridge._extract_declared_containers

    def drifted(frame):
        containers = original(frame)
        return {**containers, "git_docs": [*containers["git_docs"], "drift/example"]}

    monkeypatch.setattr(bridge, "_extract_declared_containers", drifted)
    with pytest.raises(bridge.HandoffRefused):
        bridge.verify(green_body)


def test_10_one_v2r4_sfi3_container_collision_fails(monkeypatch):
    stored = bridge._read_json(bridge.RESERVATION_PATH)
    reserved_identity = stored["declared_roots"]["git_docs"][0]
    original = bridge._extract_declared_containers

    def collided(frame):
        containers = original(frame)
        git = list(containers["git_docs"])
        git[0] = reserved_identity
        return {**containers, "git_docs": sorted(git)}

    monkeypatch.setattr(bridge, "_extract_declared_containers", collided)
    with pytest.raises(bridge.HandoffRefused, match="reserved for SFI3"):
        bridge.build()


def test_11_missing_declared_containers_fails_strict_schema(green_body):
    malformed = copy.deepcopy(green_body)
    malformed.pop("declared_containers")
    with pytest.raises(bridge.HandoffRefused, match="key set is invalid"):
        bridge.verify(malformed)


def test_12_extra_undeclared_container_fails(green_body):
    malformed = copy.deepcopy(green_body)
    malformed["declared_containers"]["git_docs"].append("extra/not-frozen")
    malformed["declared_containers_sha256"] = bridge.canonical_sha(
        malformed["declared_containers"]
    )
    with pytest.raises(bridge.HandoffRefused, match="does not equal"):
        bridge.verify(malformed)


def test_13_bridge_has_no_route_to_sfi3_payload_or_revisions():
    tree = ast.parse(Path(bridge.__file__).read_text(encoding="utf-8"))
    forbidden_imports = {
        "requests",
        "httpx",
        "urllib",
        "payload_cache",
        "fetch_corpus",
        "fetch_chains",
        "sources_sfi3",
        "sfi3_worker",
        "score_sfi3",
    }
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    assert not (imports & forbidden_imports)
    calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert not ({"fetch", "expand", "list_revisions", "read_payload"} & calls)


def test_14_bridge_never_reads_v2r4_scientific_result_values(monkeypatch, tmp_path):
    tree = ast.parse(Path(bridge.__file__).read_text(encoding="utf-8"))
    forbidden_keys = {
        "overall",
        "invariants",
        "pair_count",
        "pairs_resolved",
        "by_family",
        "violations",
        "gpu_seconds",
        "estimated_cost_usd",
    }
    literals = {
        node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    assert not (literals & forbidden_keys)

    measurement = tmp_path / "measurement.json"
    measurement.write_bytes(
        b'{"overall": THIS_IS_NOT_JSON_AND_MUST_NOT_BE_PARSED}\n'
        + json.dumps(
            {
                "provenance": {
                    "run_id": bridge.MEASUREMENT_RUN_ID,
                    "receipt_stem": "identity-change-migration-closure-v2r4",
                    "generated_at": "2026-08-26T06:49:47.942276+00:00",
                }
            }
        ).encode("utf-8")
    )
    monkeypatch.setattr(bridge, "MEASUREMENT_PATH", measurement)
    monkeypatch.setattr(bridge, "_verify_exact_file", lambda *args, **kwargs: None)
    assert bridge._measurement_metadata()["run_id"] == bridge.MEASUREMENT_RUN_ID


def test_15_original_historical_attestation_is_byte_identical():
    assert bridge.sha_file(bridge.FRAME_ATTESTATION_PATH) == (
        "sha256:669894efdec510450558c5531b54bab1e9e36459b3f052be661cfd1da909a879"
    )
