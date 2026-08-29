from __future__ import annotations

import json
from pathlib import Path

import pytest
import runpod_qualification as rq


def test_role_specs_bind_existing_pinned_runtime_inputs() -> None:
    strong = rq.discover_role_spec("strong")
    primary = rq.discover_role_spec("primary")
    assert strong.candidate_id == "mineru-3.4.4-vlm-c1"
    assert primary.candidate_id == "paddleocr-vl-1.6-fastdeploy-c8"
    for spec in (strong, primary):
        assert spec.base_image.startswith("runpod/pytorch@sha256:")
        assert len(spec.base_image_digest) == 71
        assert len(spec.model_artifact_digest) == 71
        assert (rq.REPO / spec.bootstrap_relpath).is_file()
        assert (rq.REPO / spec.prompt_relpath).is_file()


def test_plan_is_spent_only_bounded_and_secret_free() -> None:
    for role in ("strong", "primary"):
        plan = rq.plan(role)
        encoded = json.dumps(plan, sort_keys=True).casefold()
        assert plan["authority"] == "DEVELOPMENT_RUNTIME_QUALIFICATION_AUTHORIZED"
        assert plan["fresh_confirmatory_observation"] is False
        assert plan["sensitive_material_included"] is False
        assert plan["limits"] == {
            "pages": 1,
            "gpu_seconds": 10200,
            "estimated_external_cost_usd": 4.0,
            "max_hourly_rate_usd": 1.05,
        }
        assert "runpod_b" not in encoded
        assert "authorization" not in encoded
        assert "bearer " not in encoded


def test_read_runpod_b_never_transforms_value(tmp_path: Path) -> None:
    secret = "rp_" + "x" * 40
    path = tmp_path / "keys.txt"
    path.write_text(f"Other: no\nRunpod_B: {secret}\n", encoding="utf-8")
    assert rq.read_runpod_b(path) == secret


@pytest.mark.parametrize(
    "contents",
    [
        "Runpod: abcdefghijklmnopqrstuvwxyz\n",
        "Runpod_B: short\n",
        "Runpod_B: " + "x" * 30 + "\nRunpod_B: " + "y" * 30 + "\n",
    ],
)
def test_read_runpod_b_fails_closed(tmp_path: Path, contents: str) -> None:
    path = tmp_path / "keys.txt"
    path.write_text(contents, encoding="utf-8")
    with pytest.raises(rq.QualificationRefused):
        rq.read_runpod_b(path)


def test_provider_payload_is_qualification_only_and_bounded() -> None:
    spec = rq.discover_role_spec("strong")
    payload = rq.provider_payload(spec, "ssh-ed25519 AAAATEST paper2")
    assert payload["gpuCount"] == 1
    assert payload["interruptible"] is False
    assert payload["env"]["TAVONEL_R_QUALIFICATION_ONLY"] == "1"
    assert payload["env"]["MINERU_API_MAX_CONCURRENT_REQUESTS"] == "1"
    assert payload["imageName"] == spec.base_image
    assert payload["ports"] == ["22/tcp"]


def test_redacted_json_rejects_secret_bearing_field_names() -> None:
    for value in (
        {"authorization": "anything"},
        {"api_key": "anything"},
        {"nested": {"Runpod_B": "anything"}},
        {"header": "Bearer anything"},
    ):
        with pytest.raises(rq.QualificationRefused):
            rq._redacted_json(value)
