from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmark.v6.contracts import ContractError
from infra.runpod.v6.pod_client import PodCreateSpec

ROOT = Path(__file__).resolve().parents[3]
VERIFY_SCRIPT = ROOT / "benchmark/runpod_eval/bootstrap_ovisocr2_m1.sh"
DOCKERFILE = ROOT / "infra/runpod/v6/images/ovisocr2-m1/Dockerfile"
START_SCRIPT = ROOT / "infra/runpod/v6/images/ovisocr2-m1/start-ssh.sh"
QUALIFICATION_SCRIPT = ROOT / "infra/runpod/v6/images/ovisocr2-m1/qualification_http.py"
SPECS = ROOT / "infra/runpod/v6/specs"


def test_runtime_verifier_performs_no_package_or_model_installation() -> None:
    script = VERIFY_SCRIPT.read_text(encoding="utf-8").lower()
    forbidden = (
        "apt-get ",
        "pip install",
        "uv pip",
        "conda install",
        "micromamba install",
        "hf download",
        "huggingface-cli download",
    )
    assert not any(marker in script for marker in forbidden)
    assert "sha256sum --check --strict" in script
    assert "folynta_baked_runtime_receipt_sha256" in script
    assert 'script_path=$(readlink -f "${bash_source[0]}")' in script
    assert 'sha256sum "$script_path"' in script


def test_baked_image_pins_base_model_revision_and_model_payload() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    assert "ARG BASE_IMAGE=docker.io/vllm/vllm-openai@sha256:" in dockerfile
    assert "FROM ${BASE_IMAGE}" in dockerfile
    assert "MODEL_REVISION=65c619d374b55d4152e85150fc1b003700bc1f0c" in dockerfile
    assert "MODEL_SAFETENSORS_SHA256=9270560288656ece" in dockerfile
    assert "hf download ATH-MaaS/OvisOCR2" in dockerfile
    assert "sha256sum --check --strict" in dockerfile
    assert "baked-runtime-receipt.txt" in dockerfile
    assert "qualification_http.py /opt/folynta/qualification-http.py" in dockerfile


def test_baked_image_has_http_only_qualification_path_before_ssh() -> None:
    start = START_SCRIPT.read_text(encoding="utf-8")
    qualification = QUALIFICATION_SCRIPT.read_text(encoding="utf-8")
    assert start.index("FOLYNTA_QUALIFICATION_ONLY") < start.index("PUBLIC_KEY")
    assert "exec python3 /opt/folynta/qualification-http.py" in start
    assert '"folynta.runtime-verification-evidence.v1"' in qualification
    assert '"public_benchmark_inference_allowed": False' in qualification
    assert 'FOLYNTA_QUALIFICATION_ONLY' in qualification
    assert 'MODEL_SHA256 = "9270560288656ece' in qualification
    assert '"smoke_prediction_sha256"' in qualification
    assert '"smoke_expected_sha256"' in qualification
    assert '"identity_verified": True' in qualification
    assert '"model_artifact_verified": True' in qualification
    assert '"smoke_passed": True' in qualification


def test_unpublished_baked_specs_fail_closed_before_paid_capacity() -> None:
    spec_paths = sorted(SPECS.glob("folynta-ovis-m1*.json"))
    assert len(spec_paths) == 4
    for path in spec_paths:
        raw = json.loads(path.read_text(encoding="utf-8"))
        assert raw["qualification_state"] == "BUILD_REQUIRED"
        assert raw["baked_image_source"] == (
            "infra/runpod/v6/images/ovisocr2-m1/Dockerfile"
        )
        assert raw["docker_entrypoint"] == []
        assert raw["docker_start_cmd"] == []
        raw["public_key"] = "ssh-ed25519 AAAATEST test"
        spec = PodCreateSpec.from_mapping(raw)
        with pytest.raises(ContractError, match="cannot create paid capacity"):
            spec.require_ready()
