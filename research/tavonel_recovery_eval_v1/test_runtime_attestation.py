from __future__ import annotations

import json
from pathlib import Path

import pytest
from runtime_attestation import (
    DEVELOPMENT_ONLY,
    RuntimeAttestation,
    RuntimeAttestationRefused,
    pin_files,
    sha256_file,
    verify_attestation_payload,
)

SHA_A = "sha256:" + "a" * 64
SHA_B = "sha256:" + "b" * 64
SHA_C = "sha256:" + "c" * 64
SHA_D = "sha256:" + "d" * 64


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "runner.py").write_text("print('ok')\n", encoding="utf-8")
    (repo / "prompt.json").write_text(json.dumps({"schema": "v1"}), encoding="utf-8")
    return repo


def make_attestation(repo: Path) -> RuntimeAttestation:
    pins = pin_files(repo, (("runner", "runner.py"), ("prompt", "prompt.json")))
    return RuntimeAttestation(
        role="primary",
        model_id="example/model",
        model_revision="rev-1",
        base_image="runpod/pytorch",
        base_image_digest=SHA_A,
        model_artifact_digest=SHA_B,
        prompt_schema_digest=SHA_C,
        file_pins=pins,
        qualification_input_manifest_digest=SHA_D,
        observed_runtime={"gpu": "test-gpu", "driver": "test-driver", "cost_per_hour_usd": 0.1},
    )


def test_attestation_validates_exact_repository_bytes(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    attestation = make_attestation(repo)
    attestation.validate(repo)
    assert attestation.evidence_class == DEVELOPMENT_ONLY
    assert attestation.digest().startswith("sha256:")
    assert attestation.as_dict()["sensitive_material_included"] is False
    assert attestation.as_dict()["fresh_confirmatory_observation"] is False


def test_changed_pinned_file_refuses(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    attestation = make_attestation(repo)
    (repo / "runner.py").write_text("print('changed')\n", encoding="utf-8")
    with pytest.raises(RuntimeAttestationRefused, match="digest mismatch"):
        attestation.validate(repo)


def test_secret_like_runtime_metadata_refuses(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    base = make_attestation(repo)
    poisoned = RuntimeAttestation(
        role=base.role,
        model_id=base.model_id,
        model_revision=base.model_revision,
        base_image=base.base_image,
        base_image_digest=base.base_image_digest,
        model_artifact_digest=base.model_artifact_digest,
        prompt_schema_digest=base.prompt_schema_digest,
        file_pins=base.file_pins,
        qualification_input_manifest_digest=base.qualification_input_manifest_digest,
        observed_runtime={"nested": {"authorization": "Bearer never-store"}},
    )
    with pytest.raises(RuntimeAttestationRefused, match="secret-like"):
        poisoned.validate(repo)


def test_non_development_evidence_class_refuses(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    base = make_attestation(repo)
    wrong = RuntimeAttestation(
        role=base.role,
        model_id=base.model_id,
        model_revision=base.model_revision,
        base_image=base.base_image,
        base_image_digest=base.base_image_digest,
        model_artifact_digest=base.model_artifact_digest,
        prompt_schema_digest=base.prompt_schema_digest,
        file_pins=base.file_pins,
        qualification_input_manifest_digest=base.qualification_input_manifest_digest,
        observed_runtime=base.observed_runtime,
        evidence_class="FRESH_CONFIRMATORY",
    )
    with pytest.raises(RuntimeAttestationRefused, match="development-only"):
        wrong.validate(repo)


def test_payload_verifier_recomputes_file_pins(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    payload = make_attestation(repo).as_dict()
    digest = verify_attestation_payload(payload, repo)
    assert digest.startswith("sha256:")


def test_path_escape_and_duplicate_pin_refuse(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    outside = tmp_path / "outside.py"
    outside.write_text("x = 1\n", encoding="utf-8")
    with pytest.raises(RuntimeAttestationRefused, match="escapes repository"):
        pin_files(repo, (("bad", "../outside.py"),))
    with pytest.raises(RuntimeAttestationRefused, match="duplicate pinned path"):
        pin_files(repo, (("one", "runner.py"), ("two", "runner.py")))


def test_sha256_file_is_exact_bytes(tmp_path: Path) -> None:
    path = tmp_path / "bytes.bin"
    path.write_bytes(b"abc")
    assert sha256_file(path) == (
        "sha256:ba7816bf8f01cfea414140de5dae2223"
        "b00361a396177a9cb410ff61f20015ad"
    )
