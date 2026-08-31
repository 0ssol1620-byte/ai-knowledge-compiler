"""Tests for the SEM-RISK-CONF confirmatory GPU pod controller.

Every test uses ``httpx.MockTransport`` (or no transport at all). None of
these tests perform real network I/O, spend real money, or touch a real
GPU -- that is the entire point of this module.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest

from benchmark.v6.contracts import ContractError
from infra.runpod.v6.authorized_budget import AuthorizedSpendBudget
from infra.runpod.v6.confirmatory_pod_controller import (
    CANDIDATE_REGISTRY_RELATIVE_PATH,
    PROTOCOL_RELATIVE_PATH,
    ConfirmatoryPinResolution,
    ConfirmatoryRunPlan,
    GpuLifecycleStateError,
    LaneManifestInput,
    assert_upload_allowed,
    build_run_plan,
    execute,
    preflight,
    resolve_confirmatory_pins,
)
from infra.runpod.v6.pod_client import RunPodPodClient
from infra.runpod.v6.runtime_qualification import BakedRuntimeQualification

LANE_A_RELATIVE = "research/experiments/SEM-RISK-CONF-02/corpus/lane-a/images"
LANE_B_RELATIVE = "research/experiments/SEM-RISK-CONF-02/corpus/lane-b/images"
FAKE_API_KEY = "fake-test-key-not-a-real-runpod-credential"


# --------------------------------------------------------------------------
# Shared helpers (mirrors research/experiments/SEM-RISK-CONF-02/build_inference_manifests.py)
# --------------------------------------------------------------------------


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _bound_manifest(*, benchmark_id: str, dataset_revision: str, image_dir: Path) -> dict[str, Any]:
    inputs = []
    for path in sorted(image_dir.iterdir()):
        if not path.is_file():
            continue
        inputs.append(
            {
                "case_id": path.stem,
                "input_relative_path": path.name,
                "input_sha256": _sha256_file(path),
            }
        )
    content: dict[str, Any] = {
        "schema": "folynta.public-core-inference-inputs.v1",
        "benchmark_id": benchmark_id,
        "dataset_revision": dataset_revision,
        "ground_truth_mounted": False,
        "input_count": len(inputs),
        "source_count": len(inputs),
        "complete_input_coverage": True,
        "complete_source_coverage": True,
        "inputs": inputs,
    }
    digest = "sha256:" + hashlib.sha256(_canonical(content).encode("utf-8")).hexdigest()
    return {**content, "content_sha256": digest}


def _qualification_fields(*, image_digest: str, gpu_type: str) -> dict[str, Any]:
    """Synthetic, test-only fields for a hypothetical FUTURE baked runtime.

    None of this reflects the real candidate registry, which currently has
    no baked qualification for either candidate. This exists solely to
    exercise `execute()`'s state machine and cleanup mechanics in isolation
    from that (correct, current) real-world limitation.
    """

    smoke_hash = "sha256:" + "7" * 64
    return {
        "schema": "folynta.baked-runtime-qualification.v1",
        "generated_at": "2026-08-20T00:00:00+00:00",
        "source_commit": "a" * 40,
        "source_tree_sha256": "sha256:" + "b" * 64,
        "dockerfile_sha256": "sha256:" + "c" * 64,
        "image_digest": image_digest,
        "gpu_type": gpu_type,
        "cuda_version": "12.8",
        "framework_version": "test-runtime-0.0.0",
        "model_revision": "66317acc4c9fc17bd154591ce650735cd2855f3e",
        "model_artifact_sha256": "sha256:" + "d" * 64,
        "baked_runtime_file_sha256": "sha256:" + "e" * 64,
        "sbom_sha256": "sha256:" + "f" * 64,
        "vulnerability_scan_sha256": "sha256:" + "1" * 64,
        "critical_vulnerability_count": 0,
        "smoke_input_sha256": "sha256:" + "2" * 64,
        "smoke_prediction_sha256": smoke_hash,
        "smoke_expected_sha256": smoke_hash,
        "identity_verified": True,
        "model_artifact_verified": True,
        "smoke_passed": True,
        "passed": True,
    }


def _build_plan(
    *,
    pins: ConfirmatoryPinResolution,
    repo_root: Path,
    tmp_path: Path,
    image_digest: str | None = None,
    qualification: BakedRuntimeQualification | None = None,
    qualification_receipt_sha256: str | None = None,
    suffix: str = "",
) -> ConfirmatoryRunPlan:
    lane_a_dir = repo_root / LANE_A_RELATIVE
    lane_b_dir = repo_root / LANE_B_RELATIVE
    manifest_a = _bound_manifest(
        benchmark_id="sem-risk-conf-01-lane-a",
        dataset_revision="f5f559bddf50e36f7f9899d842d0006f13ce8afc",
        image_dir=lane_a_dir,
    )
    manifest_b = _bound_manifest(
        benchmark_id="sem-risk-conf-01-lane-b",
        dataset_revision="aa1ee96d106dbe53d0ae59474d75c6e6d9b53fec",
        image_dir=lane_b_dir,
    )
    manifest_a_path = tmp_path / f"lane-a-public-core{suffix}.json"
    manifest_b_path = tmp_path / f"lane-b-public-core{suffix}.json"
    manifest_a_path.write_text(_canonical(manifest_a), encoding="utf-8")
    manifest_b_path.write_text(_canonical(manifest_b), encoding="utf-8")

    seal = {
        "experiment_id": pins.scientific_experiment_id,
        "protocol_sha256": pins.protocol_sha256,
        "manifests": {
            "a": _sha256_file(manifest_a_path),
            "b": _sha256_file(manifest_b_path),
        },
        "ground_truth_mounted": False,
        "paddle_repeats": {"lane_a": 1, "lane_b": 3},
        "specialist_repeats": {"lane_a": 1, "lane_b": 1},
    }
    seal_path = tmp_path / f"inference-manifest-seal{suffix}.json"
    seal_path.write_text(json.dumps(seal, indent=2, sort_keys=True), encoding="utf-8")

    return build_run_plan(
        pins=pins,
        lane_a=LaneManifestInput(lane="a", manifest_path=manifest_a_path, input_dir=lane_a_dir),
        lane_b=LaneManifestInput(lane="b", manifest_path=manifest_b_path, input_dir=lane_b_dir),
        inference_manifest_seal_path=seal_path,
        hard_cap_usd="25",
        gpu_type="NVIDIA A40",
        maximum_runtime_hours="1",
        image_digest=image_digest,
        baked_runtime_qualification=qualification,
        baked_runtime_receipt_sha256=qualification_receipt_sha256,
    )


def _sequential_handler(
    responses: list[tuple[int, dict[str, Any] | None]],
) -> tuple[Callable[[httpx.Request], httpx.Response], list[httpx.Request]]:
    calls: list[httpx.Request] = []
    state = {"index": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        index = state["index"]
        state["index"] += 1
        status, body = responses[index]
        if body is None:
            return httpx.Response(status)
        return httpx.Response(status, headers={"content-type": "application/json"}, json=body)

    return handler, calls


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


@pytest.fixture
def pins(repo_root: Path) -> ConfirmatoryPinResolution:
    return resolve_confirmatory_pins(repo_root)


@pytest.fixture
def full_plan(
    repo_root: Path, pins: ConfirmatoryPinResolution, tmp_path: Path
) -> ConfirmatoryRunPlan:
    """A plan built entirely from the real, current registry state.

    No baked runtime qualification exists for either candidate right now,
    so any `PodCreateSpec` built from this plan is structurally BUILD_REQUIRED.
    """

    return _build_plan(pins=pins, repo_root=repo_root, tmp_path=tmp_path, suffix="-real")


@pytest.fixture
def armed_ready_plan(
    repo_root: Path, pins: ConfirmatoryPinResolution, tmp_path: Path
) -> ConfirmatoryRunPlan:
    """A plan carrying a synthetic, test-only baked qualification.

    This exists only to exercise `execute()`'s state machine and cleanup
    mechanics; it does not reflect the real candidate registry.
    """

    image_digest = "ghcr.io/tavonel/sem-risk-conf/paddleocr-vl-1.6@sha256:" + "a" * 64
    qualification = BakedRuntimeQualification.from_mapping(
        _qualification_fields(image_digest=image_digest, gpu_type="NVIDIA A40")
    )
    return _build_plan(
        pins=pins,
        repo_root=repo_root,
        tmp_path=tmp_path,
        image_digest=image_digest,
        qualification=qualification,
        qualification_receipt_sha256=qualification.receipt_sha256,
        suffix="-armed",
    )


# --------------------------------------------------------------------------
# 1. Pin resolution
# --------------------------------------------------------------------------


def test_pins_resolve_correctly_from_hash_verified_registry(
    pins: ConfirmatoryPinResolution,
) -> None:
    assert pins.primary.candidate_id == "paddleocr-vl-1.6"
    assert pins.primary.repository == "PaddlePaddle/PaddleOCR-VL-1.6"
    assert pins.primary.revision == "66317acc4c9fc17bd154591ce650735cd2855f3e"
    assert pins.primary.artifact_sha256 == (
        "sha256:40ca2a90af83f79a9adf2d5ddb7e32187e6956e45e5730119595be7305e06a53"
    )

    assert pins.specialist.candidate_id == "mineru-3.4.4-vlm"
    assert pins.specialist.repository == "opendatalab/MinerU"
    assert pins.specialist.revision == "79d6d8d79fb8f3ddba5cc34c07a16f0ec36f56c7"
    assert pins.specialist.artifact_sha256 == (
        "sha256:1611a8892cc0e7e287d31c4a1b5af87652f0f6e4a3f80276b92b4c71f982de84"
    )


# --------------------------------------------------------------------------
# 2. Tampered registry
# --------------------------------------------------------------------------


def test_tampered_registry_raises_contract_error(repo_root: Path, tmp_path: Path) -> None:
    tampered_root = tmp_path / "tampered-repo"
    (tampered_root / Path(PROTOCOL_RELATIVE_PATH).parent).mkdir(parents=True)
    (tampered_root / Path(CANDIDATE_REGISTRY_RELATIVE_PATH).parent).mkdir(parents=True)

    real_protocol = (repo_root / PROTOCOL_RELATIVE_PATH).read_bytes()
    (tampered_root / PROTOCOL_RELATIVE_PATH).write_bytes(real_protocol)

    real_registry = (repo_root / CANDIDATE_REGISTRY_RELATIVE_PATH).read_bytes()
    tampered_registry = real_registry + b"\n# tampered-for-test\n"
    (tampered_root / CANDIDATE_REGISTRY_RELATIVE_PATH).write_bytes(tampered_registry)

    with pytest.raises(ContractError, match="candidate registry hash"):
        resolve_confirmatory_pins(tampered_root)


def _write_synthetic_repo(
    tmp_path: Path,
    *,
    label: str,
    primary_artifact_sha256: str | None = "sha256:" + "9" * 64,
    specialist_commercial_use: str = "unknown",
    specialist_promotion_status: str = "research_comparator_only_license_review_required",
) -> Path:
    """Build a minimal, self-consistent registry+protocol pair for one edge case.

    Unlike `test_tampered_registry_raises_contract_error`, this does not reuse
    the real repo content -- it builds its own hash-consistent pair so a
    single field (artifact_sha256, or the promotion-status agreement) can be
    put in a state the real registry does not currently exhibit.
    """

    root = tmp_path / f"synthetic-repo-{label}"
    registry_path = root / CANDIDATE_REGISTRY_RELATIVE_PATH
    protocol_path = root / PROTOCOL_RELATIVE_PATH
    registry_path.parent.mkdir(parents=True)
    protocol_path.parent.mkdir(parents=True)

    primary_identity_line = (
        f'      artifact_sha256: "{primary_artifact_sha256}"'
        if primary_artifact_sha256 is not None
        else "      artifact_sha256: null"
    )
    registry_yaml = f"""
candidates:
  - id: paddleocr-vl-1.6
    identity:
      repository: "PaddlePaddle/PaddleOCR-VL-1.6"
      revision: "66317acc4c9fc17bd154591ce650735cd2855f3e"
{primary_identity_line}
      runtime_recipe: "benchmark/runpod_eval/paddleocr_vl_stage2.py"
    license:
      id: "Apache-2.0"
      status: approved
      commercial_use: allowed
  - id: mineru-3.4.4-vlm
    identity:
      repository: "opendatalab/MinerU"
      revision: "79d6d8d79fb8f3ddba5cc34c07a16f0ec36f56c7"
      artifact_sha256: "sha256:{'1' * 64}"
      runtime_recipe: "benchmark/runpod_eval/mineru_stage2.py"
    license:
      id: "AGPL-3.0-or-upstream-current"
      status: review_required
      commercial_use: {specialist_commercial_use}
"""
    registry_path.write_text(registry_yaml, encoding="utf-8")
    registry_sha256 = _sha256_file(registry_path)

    protocol = {
        "experiment_id": "SEM-RISK-CONF-SYNTHETIC",
        "source_hashes": {CANDIDATE_REGISTRY_RELATIVE_PATH: registry_sha256},
        "parser_roles": {
            "primary": "paddleocr-vl-1.6",
            "research_specialist": "mineru-3.4.4-vlm",
            "specialist_promotion_status": specialist_promotion_status,
        },
    }
    protocol_path.write_text(_canonical(protocol), encoding="utf-8")
    return root


def test_pin_resolution_rejects_missing_artifact_sha256(tmp_path: Path) -> None:
    root = _write_synthetic_repo(tmp_path, label="null-artifact", primary_artifact_sha256=None)
    with pytest.raises(ContractError, match="artifact_sha256"):
        resolve_confirmatory_pins(root)


def test_pin_resolution_rejects_promotion_status_disagreement(tmp_path: Path) -> None:
    # License says the specialist's commercial use is NOT allowed, but the
    # protocol falsely claims the specialist is promotable -- this must be
    # rejected rather than silently trusting either side.
    root = _write_synthetic_repo(
        tmp_path,
        label="promotion-disagreement",
        specialist_commercial_use="unknown",
        specialist_promotion_status="promotable",
    )
    with pytest.raises(ContractError, match="promotion eligibility disagrees"):
        resolve_confirmatory_pins(root)


# --------------------------------------------------------------------------
# 3. Specialist promotion eligibility
# --------------------------------------------------------------------------


def test_specialist_never_promotion_eligible_given_current_license(
    pins: ConfirmatoryPinResolution,
) -> None:
    assert pins.specialist.license_commercial_use != "allowed"
    assert pins.promotion_eligible is False


# --------------------------------------------------------------------------
# 4. Ground-truth-mounted manifest rejected
# --------------------------------------------------------------------------


def test_manifest_with_ground_truth_mounted_is_rejected(
    pins: ConfirmatoryPinResolution, repo_root: Path, tmp_path: Path
) -> None:
    lane_a_dir = repo_root / LANE_A_RELATIVE
    poisoned_manifest = {
        "schema": "folynta.public-core-inference-inputs.v1",
        "benchmark_id": "sem-risk-conf-01-lane-a-poisoned",
        "dataset_revision": "f5f559bddf50e36f7f9899d842d0006f13ce8afc",
        "ground_truth_mounted": True,
        "input_count": 1,
        "source_count": 1,
        "complete_input_coverage": True,
        "complete_source_coverage": True,
        "inputs": [
            {
                "case_id": "does-not-matter",
                "input_relative_path": "does-not-matter.jpg",
                "input_sha256": "sha256:" + "0" * 64,
            }
        ],
    }
    manifest_path = tmp_path / "poisoned-lane-a.json"
    manifest_path.write_text(_canonical(poisoned_manifest), encoding="utf-8")

    lane_b_dir = repo_root / LANE_B_RELATIVE
    manifest_b = _bound_manifest(
        benchmark_id="sem-risk-conf-01-lane-b",
        dataset_revision="aa1ee96d106dbe53d0ae59474d75c6e6d9b53fec",
        image_dir=lane_b_dir,
    )
    manifest_b_path = tmp_path / "lane-b-public-core.json"
    manifest_b_path.write_text(_canonical(manifest_b), encoding="utf-8")
    seal_path = tmp_path / "inference-manifest-seal.json"
    seal_path.write_text(
        json.dumps({"manifests": {}, "ground_truth_mounted": False}), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="ground-truth-free"):
        build_run_plan(
            pins=pins,
            lane_a=LaneManifestInput(lane="a", manifest_path=manifest_path, input_dir=lane_a_dir),
            lane_b=LaneManifestInput(
                lane="b", manifest_path=manifest_b_path, input_dir=lane_b_dir
            ),
            inference_manifest_seal_path=seal_path,
            hard_cap_usd="25",
            gpu_type="NVIDIA A40",
            maximum_runtime_hours="1",
        )


def test_run_plan_repeat_plan_and_output_layout_contract(
    full_plan: ConfirmatoryRunPlan,
) -> None:
    # paddle_repeats={"lane_a": 1, "lane_b": 3}, specialist_repeats={"lane_a": 1, "lane_b": 1}
    # from the seal fixture -- adaptive_repeat_indices() must turn those into
    # the real (1-based) repeat index tuples.
    assert full_plan.repeat_plan["paddle_lane_a"] == (1,)
    assert full_plan.repeat_plan["paddle_lane_b"] == (1, 2, 3)
    assert full_plan.repeat_plan["specialist_lane_a"] == (1,)
    assert full_plan.repeat_plan["specialist_lane_b"] == (1,)
    assert full_plan.output_layout_contract == "markdown-repeat-{repeat}/{case_id}.md"


# --------------------------------------------------------------------------
# 5. Upload allowlist is closed
# --------------------------------------------------------------------------


def test_upload_allowlist_is_closed(full_plan: ConfirmatoryRunPlan, tmp_path: Path) -> None:
    allowed_path = next(iter(full_plan.upload_allowlist))
    assert_upload_allowed(full_plan, allowed_path)  # must not raise

    outside_path = tmp_path / "not-a-manifest-input.jpg"
    outside_path.write_bytes(b"not a real input")
    with pytest.raises(ContractError, match="outside the closed allowlist"):
        assert_upload_allowed(full_plan, outside_path)


# --------------------------------------------------------------------------
# 6. execute(armed=False) raises immediately with zero network calls
# --------------------------------------------------------------------------


def test_execute_unarmed_raises_immediately_with_zero_requests(
    full_plan: ConfirmatoryRunPlan,
) -> None:
    budget = AuthorizedSpendBudget(campaign_id="sem-risk-conf-02-test", hard_cap_usd="25")
    handler, calls = _sequential_handler([])
    client = RunPodPodClient(api_key=FAKE_API_KEY, transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ContractError, match="not armed"):
            execute(full_plan, client=client, budget=budget, armed=False)
    finally:
        client.close()

    assert calls == []
    assert budget.reserved_usd == Decimal("0")
    assert budget.settled_usd == Decimal("0")


# --------------------------------------------------------------------------
# 7. preflight fails via require_ready() given the current registry state
# --------------------------------------------------------------------------


def test_preflight_fails_via_require_ready_given_current_registry_state(
    full_plan: ConfirmatoryRunPlan,
) -> None:
    budget = AuthorizedSpendBudget(campaign_id="sem-risk-conf-02-test", hard_cap_usd="25")

    with pytest.raises(ContractError, match="BUILD_REQUIRED"):
        preflight(full_plan, budget=budget)

    # The hard-cap reserve/release cycle must still complete cleanly even
    # though the readiness gate refuses the pod spec afterwards.
    assert budget.reserved_usd == Decimal("0")
    assert budget.settled_usd == Decimal("0")


def test_preflight_on_a_hypothetically_ready_plan_never_implies_launch(
    armed_ready_plan: ConfirmatoryRunPlan,
) -> None:
    """Even if a future round bakes a matching qualification, preflight

    must still never create anything -- it only ever returns PREFLIGHT_ONLY.
    """

    budget = AuthorizedSpendBudget(campaign_id="sem-risk-conf-02-test", hard_cap_usd="25")
    receipt = preflight(armed_ready_plan, budget=budget)
    assert receipt["state"] == "PREFLIGHT_ONLY"
    assert receipt["armed"] is False
    assert receipt["provision_receipt"] is None


# --------------------------------------------------------------------------
# 8. Mid-run exception still cleans up and re-raises
# --------------------------------------------------------------------------


def test_execute_mid_run_exception_still_cleans_up_and_reraises(
    armed_ready_plan: ConfirmatoryRunPlan,
) -> None:
    budget = AuthorizedSpendBudget(campaign_id="sem-risk-conf-02-test", hard_cap_usd="25")
    responses: list[tuple[int, dict[str, Any] | None]] = [
        (
            201,
            {
                "id": "sriskconfpod01",
                "name": "sem-risk-conf",
                "desiredStatus": "RUNNING",
                "gpu": {"displayName": "NVIDIA A40"},
            },
        ),
        (
            200,
            {"id": "sriskconfpod01", "name": "sem-risk-conf", "desiredStatus": "EXITED"},
        ),  # simulated mid-run failure: pod unexpectedly exited
        (202, None),  # delete
        (404, None),  # absence proof
    ]
    handler, calls = _sequential_handler(responses)
    client = RunPodPodClient(api_key=FAKE_API_KEY, transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(GpuLifecycleStateError, match="RUNNING"):
            execute(armed_ready_plan, client=client, budget=budget, armed=True, clock=lambda: 0.0)
    finally:
        client.close()

    assert len(calls) == 4
    assert calls[0].method == "POST"
    assert calls[2].method == "DELETE"
    assert budget.settled_usd == armed_ready_plan.hard_cap_usd
    assert budget.reserved_usd == Decimal("0")


# --------------------------------------------------------------------------
# 9. Watchdog deadline triggers the same delete path
# --------------------------------------------------------------------------


def test_execute_watchdog_deadline_triggers_cleanup(
    armed_ready_plan: ConfirmatoryRunPlan,
) -> None:
    budget = AuthorizedSpendBudget(campaign_id="sem-risk-conf-02-test", hard_cap_usd="25")
    responses: list[tuple[int, dict[str, Any] | None]] = [
        (
            201,
            {"id": "sriskconfpod02", "name": "sem-risk-conf", "desiredStatus": "RUNNING"},
        ),
        (
            200,
            {"id": "sriskconfpod02", "name": "sem-risk-conf", "desiredStatus": "RUNNING"},
        ),
        (202, None),
        (404, None),
    ]
    handler, calls = _sequential_handler(responses)
    client = RunPodPodClient(api_key=FAKE_API_KEY, transport=httpx.MockTransport(handler))
    fake_clock_values = iter([0.0, 10_000_000.0])
    try:
        with pytest.raises(GpuLifecycleStateError, match="watchdog"):
            execute(
                armed_ready_plan,
                client=client,
                budget=budget,
                armed=True,
                clock=lambda: next(fake_clock_values),
            )
    finally:
        client.close()

    assert len(calls) == 4
    assert calls[2].method == "DELETE"
    assert budget.settled_usd == armed_ready_plan.hard_cap_usd


# --------------------------------------------------------------------------
# 10. No secret material ever appears in a serialized receipt
# --------------------------------------------------------------------------


def test_preflight_receipt_has_no_secret_material(
    armed_ready_plan: ConfirmatoryRunPlan,
) -> None:
    budget = AuthorizedSpendBudget(campaign_id="sem-risk-conf-02-test", hard_cap_usd="25")
    receipt = preflight(armed_ready_plan, budget=budget)

    serialized = json.dumps(receipt, sort_keys=True, default=str)
    assert "AAAA-PREFLIGHT-ONLY-NOT-A-REAL-KEY" not in serialized
    assert "ssh-ed25519 AAAA" not in serialized
    assert '"PUBLIC_KEY"' not in serialized
    assert FAKE_API_KEY not in serialized


def test_execute_success_receipt_has_no_secret_material(
    armed_ready_plan: ConfirmatoryRunPlan,
) -> None:
    budget = AuthorizedSpendBudget(campaign_id="sem-risk-conf-02-test", hard_cap_usd="25")
    responses: list[tuple[int, dict[str, Any] | None]] = [
        (201, {"id": "sriskconfpod03", "name": "sem-risk-conf", "desiredStatus": "RUNNING"}),
        (200, {"id": "sriskconfpod03", "name": "sem-risk-conf", "desiredStatus": "RUNNING"}),
        (202, None),
        (404, None),
    ]
    handler, calls = _sequential_handler(responses)
    client = RunPodPodClient(api_key=FAKE_API_KEY, transport=httpx.MockTransport(handler))
    try:
        receipt = execute(
            armed_ready_plan, client=client, budget=budget, armed=True, clock=lambda: 0.0
        )
    finally:
        client.close()

    assert len(calls) == 4
    assert receipt["state"] == "SETTLED"
    assert receipt["armed"] is True
    assert receipt["ground_truth_uploaded"] is False

    serialized = json.dumps(receipt, sort_keys=True, default=str)
    assert FAKE_API_KEY not in serialized
    assert "ssh-ed25519 AAAA" not in serialized
    assert '"PUBLIC_KEY"' not in serialized


# --------------------------------------------------------------------------
# Bonus: no CLI / __main__ entry point
# --------------------------------------------------------------------------


def test_module_has_no_cli_entry_point() -> None:
    import infra.runpod.v6.confirmatory_pod_controller as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    assert 'if __name__ == "__main__"' not in source
    assert "import argparse" not in source
    assert "from_environment" not in source
