"""Parses .github/workflows/baked-confirmatory-images.yml (D5) and asserts its
safety-critical shape: workflow_dispatch only, a required no-default arming
string, and every build/publish side effect gated behind it.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_PATH = ROOT / ".github/workflows/baked-confirmatory-images.yml"
BASELINE_MODEL_IMAGE_WORKFLOW = ROOT / ".github/workflows/baked-model-image.yml"

_ARMED_STEP_NAME_KEYWORDS = ("build", "sbom", "scan", "receipt", "upload")


@pytest.fixture(scope="module")
def workflow_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def workflow(workflow_text: str) -> dict:
    return yaml.safe_load(workflow_text)


def test_only_workflow_dispatch_trigger() -> None:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    parsed = yaml.safe_load(text)
    triggers = parsed[True]
    assert set(triggers) == {"workflow_dispatch"}
    assert "push" not in triggers
    assert "pull_request" not in triggers
    assert "schedule" not in triggers


def test_confirm_ghcr_push_input_is_required_string_with_no_default(workflow: dict) -> None:
    inputs = workflow[True]["workflow_dispatch"]["inputs"]
    confirm_input = inputs["confirm_ghcr_push"]
    assert confirm_input["required"] is True
    assert confirm_input["type"] == "string"
    assert "default" not in confirm_input


def test_target_input_is_required_with_no_default(workflow: dict) -> None:
    inputs = workflow[True]["workflow_dispatch"]["inputs"]
    target_input = inputs["target"]
    assert target_input["required"] is True
    assert "default" not in target_input


def test_five_downstream_steps_are_all_gated_by_the_arming_condition(workflow: dict) -> None:
    steps = workflow["jobs"]["baked-confirmatory-image"]["steps"]
    gated_steps = [step for step in steps if "if" in step]
    gated_names = [step.get("name", step.get("uses", "<unnamed>")) for step in gated_steps]

    assert len(gated_steps) == 5, f"expected exactly 5 gated steps, found: {gated_names}"
    for step in gated_steps:
        assert step["if"] == "steps.arming_gate.outputs.armed == 'true'", (
            f"step {step.get('name')!r} is not gated by the arming output: {step['if']!r}"
        )

    joined_names = " ".join(name.lower() for name in gated_names)
    for keyword in _ARMED_STEP_NAME_KEYWORDS:
        assert keyword in joined_names, (
            f"no gated step name mentions {keyword!r}; gated steps were: {gated_names}"
        )


def test_arming_gate_uses_case_sensitive_bash_comparison_not_gha_equality(
    workflow_text: str,
) -> None:
    assert 'if [ "$CONFIRM_GHCR_PUSH" = "PUBLISH-IMMUTABLE-IMAGE" ]' in workflow_text
    # Never expressed as a workflow-level `==` string comparison, which GitHub
    # Actions evaluates case-insensitively.
    assert "inputs.confirm_ghcr_push ==" not in workflow_text


def test_workflow_never_references_runpod_provider_surfaces(workflow_text: str) -> None:
    lowered = workflow_text.lower()
    for forbidden in ("api.runpod.ai", "rest.runpod.io", "pod_client", "qualification_pod"):
        assert forbidden not in lowered, f"workflow unexpectedly references {forbidden!r}"


def test_baked_model_image_workflow_is_byte_for_byte_unchanged() -> None:
    # This file predates D1-D6 and must not be touched by this round. Compare
    # its on-disk content against the git HEAD blob directly.
    git_executable = shutil.which("git")
    assert git_executable is not None, "git executable not found on PATH"
    result = subprocess.run(
        [git_executable, "show", "HEAD:.github/workflows/baked-model-image.yml"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    committed_text = result.stdout
    on_disk_text = BASELINE_MODEL_IMAGE_WORKFLOW.read_text(encoding="utf-8")
    assert on_disk_text == committed_text, (
        ".github/workflows/baked-model-image.yml differs from the committed HEAD version"
    )
