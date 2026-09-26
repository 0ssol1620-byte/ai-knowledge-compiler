"""builder_pod_plan.py: dry-run spec generation, determinism, and validation.

Nothing here calls RunPod. Every assertion is about the *shape* and
*repeatability* of the generated spec/script.
"""

from __future__ import annotations

import pytest
from builder_pod_plan import (
    BuilderPodPlan,
    BuilderPodPlanError,
    build_on_pod_script,
    render_plan,
)

_TEST_KEY = (
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIexampleexampleexampleexampleexampleexamp arena-builder"
)


def _plan(**overrides: object) -> BuilderPodPlan:
    defaults: dict[str, object] = {
        "model_key": "paddleocr_vl_1_6",
        "pod_name": "arena-builder-paddleocr-vl-1-6",
        "disk_gb": 40,
        "volume_gb": 0,
        "ssh_public_key": _TEST_KEY,
    }
    defaults.update(overrides)
    return BuilderPodPlan(**defaults)  # type: ignore[arg-type]


def test_provider_request_is_gpu_free() -> None:
    plan = _plan()
    request = plan.provider_request_dry_run()
    assert request["computeType"] == "CPU"
    assert "gpuTypeIds" not in request
    assert request["containerDiskInGb"] == 40


def test_redacted_request_never_carries_the_real_key() -> None:
    plan = _plan()
    redacted = plan.redacted_request()
    assert redacted["env"]["PUBLIC_KEY"] == "redacted"
    assert _TEST_KEY not in render_plan(plan)


def test_render_plan_is_deterministic() -> None:
    plan_one = _plan()
    plan_two = _plan()
    assert render_plan(plan_one) == render_plan(plan_two)


@pytest.mark.parametrize(
    "field,bad_value",
    [
        ("model_key", "Not-Valid-Key"),
        ("pod_name", "wrong-prefix-paddleocr"),
        ("disk_gb", 10),
        ("disk_gb", 500),
        ("volume_gb", -1),
        ("ssh_public_key", "not-an-ssh-key at all"),
    ],
)
def test_invalid_fields_raise(field: str, bad_value: object) -> None:
    with pytest.raises(BuilderPodPlanError):
        _plan(**{field: bad_value})


def test_build_on_pod_script_is_deterministic_for_same_inputs() -> None:
    kwargs = dict(
        model_key="paddleocr_vl_1_6",
        dockerfile="runtimes/paddleocr_vl_1_6/Dockerfile",
        context_dir=".",
        registry_target="ghcr.io/0ssol1620-byte/tavonel-arena/paddleocr_vl_1_6",
        image_tag="20260903",
    )
    first = build_on_pod_script(**kwargs)
    second = build_on_pod_script(**kwargs)
    assert first == second


def test_build_on_pod_script_differs_for_different_model_keys() -> None:
    base_kwargs = dict(
        dockerfile="runtimes/x/Dockerfile",
        context_dir=".",
        registry_target="ghcr.io/0ssol1620-byte/tavonel-arena/x",
        image_tag="20260903",
    )
    one = build_on_pod_script(model_key="paddleocr_vl_1_6", **base_kwargs)
    two = build_on_pod_script(model_key="mineru_pipeline", **base_kwargs)
    assert one != two


def test_build_on_pod_script_never_contains_a_literal_token() -> None:
    script = build_on_pod_script(
        model_key="paddleocr_vl_1_6",
        dockerfile="runtimes/paddleocr_vl_1_6/Dockerfile",
        context_dir=".",
        registry_target="ghcr.io/0ssol1620-byte/tavonel-arena/paddleocr_vl_1_6",
        image_tag="20260903",
    )
    assert "ARENA_REGISTRY_TOKEN" in script  # reads it...
    assert "unset ARENA_REGISTRY_TOKEN" in script  # ...and unsets it
    # No hardcoded credential-looking literal anywhere in the generated text.
    for marker in ("ghp_", "rpa_", "AKIA"):
        assert marker not in script


def test_build_on_pod_script_refuses_without_token_at_runtime() -> None:
    script = build_on_pod_script(
        model_key="paddleocr_vl_1_6",
        dockerfile="runtimes/paddleocr_vl_1_6/Dockerfile",
        context_dir=".",
        registry_target="ghcr.io/0ssol1620-byte/tavonel-arena/paddleocr_vl_1_6",
        image_tag="20260903",
    )
    assert "ARENA_REGISTRY_TOKEN is not set" in script
    assert "exit 1" in script


@pytest.mark.parametrize(
    "field,bad_value",
    [
        ("model_key", "Bad Key"),
        ("dockerfile", "line\none\ntwo"),
        ("context_dir", ""),
        ("registry_target", "no\x00null"),
        ("image_tag", ""),
    ],
)
def test_build_on_pod_script_rejects_malformed_inputs(field: str, bad_value: str) -> None:
    kwargs = dict(
        model_key="paddleocr_vl_1_6",
        dockerfile="runtimes/paddleocr_vl_1_6/Dockerfile",
        context_dir=".",
        registry_target="ghcr.io/0ssol1620-byte/tavonel-arena/paddleocr_vl_1_6",
        image_tag="20260903",
    )
    kwargs[field] = bad_value
    with pytest.raises(BuilderPodPlanError):
        build_on_pod_script(**kwargs)
