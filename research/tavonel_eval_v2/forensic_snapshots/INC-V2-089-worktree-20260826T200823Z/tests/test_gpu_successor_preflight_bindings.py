"""CPU-only binding tests for GPU successor protocol and model-pin preflight."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(NS / "tools"))

import freeze_gpu_successor_protocols as freeze  # noqa: E402
import gpu_successor_preflight as gsp  # noqa: E402
import resolve_gpu_successor_pin as resolver  # noqa: E402
from common import canonical_sha, sha_file  # noqa: E402


def _protocol(path: Path, *, schema: str, protocol_id: str) -> None:
    path.write_text(
        "\n".join(
            [
                f"schema: {schema}",
                f"protocol_id: {protocol_id}",
                f"study_id: {freeze.STUDY_ID}",
                "status: DRAFT_NOT_FROZEN",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _land_freeze(tmp_path: Path) -> tuple[Path, Path, Path, str]:
    study = tmp_path / "study.yaml"
    runtime = tmp_path / "runtime.yaml"
    _protocol(
        study,
        schema="tavonel.v2.protocol.gpu_successor_study.v1",
        protocol_id="GPU_SUCCESSOR_STUDY_V1",
    )
    _protocol(
        runtime,
        schema="tavonel.v2.protocol.gpu_successor_runtime.v1",
        protocol_id="GPU_SUCCESSOR_RUNTIME_V1",
    )
    body = freeze.build_freeze(study, runtime)
    body["provenance"] = {
        "schema": freeze.IMMUTABLE_ENVELOPE_SCHEMA,
        "immutable": True,
        "receipt_stem": freeze.STEM,
    }
    body["receipt_sha256"] = canonical_sha(body)
    receipt = tmp_path / "freeze.json"
    receipt.write_text(json.dumps(body, sort_keys=True), encoding="utf-8")
    return study, runtime, receipt, sha_file(receipt)


def test_bundle_freeze_binds_both_exact_specifications(tmp_path: Path) -> None:
    study, runtime, receipt, digest = _land_freeze(tmp_path)
    result = freeze.verify_freeze(
        receipt,
        digest,
        study_path=study,
        runtime_path=runtime,
    )
    assert result["passed"] is True
    assert result["checks"]["study_sha256"] is True
    assert result["checks"]["runtime_sha256"] is True


def test_bundle_freeze_refuses_receipt_digest_drift(tmp_path: Path) -> None:
    study, runtime, receipt, _digest = _land_freeze(tmp_path)
    result = freeze.verify_freeze(
        receipt,
        "sha256:" + "0" * 64,
        study_path=study,
        runtime_path=runtime,
    )
    assert result["passed"] is False
    assert "drift" in result["why"]


@pytest.mark.parametrize("which", ["study", "runtime"])
def test_bundle_freeze_refuses_either_specification_drifting(
    tmp_path: Path, which: str
) -> None:
    study, runtime, receipt, digest = _land_freeze(tmp_path)
    target = study if which == "study" else runtime
    target.write_text(target.read_text(encoding="utf-8") + "changed: true\n", encoding="utf-8")
    result = freeze.verify_freeze(
        receipt,
        digest,
        study_path=study,
        runtime_path=runtime,
    )
    assert result["passed"] is False
    assert result["checks"][f"{which}_sha256"] is False


def test_model_pin_loader_reads_nested_resolver_receipt() -> None:
    receipt = (
        NS
        / "receipts"
        / "gpu-successor-pin--20260823T082423Z-6902ef5f7efa.json"
    )
    result = gsp.load_model_pin_artifact(receipt, sha_file(receipt))
    assert result["passed"] is True
    assert result["kind"] == "resolver_receipt"
    assert result["resolved_pin"]["revision"] != "latest"


def test_model_pin_loader_refuses_nested_receipt_without_immutable_envelope(
    tmp_path: Path,
) -> None:
    path = tmp_path / "forged.json"
    path.write_text(json.dumps({"resolved_pin": {"repository": "x"}}), encoding="utf-8")
    result = gsp.load_model_pin_artifact(path, sha_file(path))
    assert result["passed"] is False
    assert result["kind"] == "resolver_receipt"


def test_model_pin_loader_accepts_exact_flat_sealed_export(tmp_path: Path) -> None:
    path = tmp_path / "pin.json"
    resolved = {
        "repository": "Qwen/Qwen3.6-27B",
        "revision": "6a9e13bd6fc8f0983b9b99948120bc37f49c13e9",
        "tokenizer_file_sha256": "sha256:" + "a" * 64,
        "capability_evidence": "attestation.json#config.json",
    }
    written = resolver.write_sealed_export(path, resolved)
    result = gsp.load_model_pin_artifact(path, written["sealed_export_file_sha256"])
    assert result["passed"] is True
    assert result["kind"] == "sealed_flat_export"
    assert result["resolved_pin"] == resolved


def test_model_pin_loader_refuses_flat_export_digest_drift(tmp_path: Path) -> None:
    path = tmp_path / "pin.json"
    resolver.write_sealed_export(
        path,
        {
            "repository": "repo",
            "revision": "1" * 40,
            "tokenizer_file_sha256": "sha256:" + "2" * 64,
        },
    )
    result = gsp.load_model_pin_artifact(path, "sha256:" + "0" * 64)
    assert result["passed"] is False
    assert "drift" in result["why"]


def test_flat_export_cannot_make_a_short_revision_exactly_pinned(tmp_path: Path) -> None:
    path = tmp_path / "pin.json"
    written = resolver.write_sealed_export(
        path,
        {
            "repository": "repo",
            "revision": "1234",
            "tokenizer_file_sha256": "sha256:" + "2" * 64,
        },
    )
    loaded = gsp.load_model_pin_artifact(path, written["sealed_export_file_sha256"])
    assert loaded["passed"] is True
    assert gsp.model_identity_pin(loaded["resolved_pin"])["pinned_by_exact_revision"] is False


def test_preflight_blocks_without_exact_freeze_and_model_pin_bindings(tmp_path: Path) -> None:
    body = gsp.run(
        manifest=tmp_path / "missing.json",
        model_pin={},
        runtime_image_digest="repo/image@sha256:" + "0" * 64,
    )
    assert "G_GSP_PROTOCOL_BUNDLE_FROZEN" in body["blocking_gates"]
    assert "G_GSP_MODEL_PIN_SOURCE_SEALED" in body["blocking_gates"]
