"""The D6/D7/D9/D10 gate: cost ceiling, receipts, licence, GPU pools."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from arena.controller.authorization_gate import (
    CANARY_MAX_POD_LIFETIME_HOURS,
    FULL_RUN_MAX_POD_LIFETIME_HOURS,
    GateError,
    authorize,
    effective_pod_lifetime_hours,
    estimate_pod_cost,
    license_gate,
    max_pod_lifetime_hours,
)
from arena.controller.gpu_pools import (
    GpuPoolError,
    latest_price_snapshot_path,
    load_price_snapshot,
    validate_pool,
)
from arena.controller.paths import CampaignPaths
from arena.controller.runtime_spec import RuntimeSpecError, load_runtime_spec
from tests.controller.conftest import (
    MODEL_KEY,
    write_authorization,
    write_catalog_snapshot,
    write_runtime_json,
)

NOW = datetime(2026, 9, 3, 13, 0, 0, tzinfo=UTC)


def _snapshot(paths: CampaignPaths) -> object:
    write_catalog_snapshot(paths)
    path = latest_price_snapshot_path(paths.provider_receipts_dir)
    assert path is not None
    return load_price_snapshot(path)


# ------------------------------------------------------------- D10 lifetime


def test_pod_lifetime_caps_are_two_and_six_hours() -> None:
    assert CANARY_MAX_POD_LIFETIME_HOURS == 2
    assert FULL_RUN_MAX_POD_LIFETIME_HOURS == 6
    assert max_pod_lifetime_hours("phase1_canary") == 2
    assert max_pod_lifetime_hours("phase2_full_run") == 6
    with pytest.raises(GateError):
        max_pod_lifetime_hours("phase9_imaginary")


# ----------------------------------------------------------- D6 cost ceiling


def test_the_estimate_takes_the_dearest_priced_gpu_in_the_pool(
    paths: CampaignPaths,
) -> None:
    snapshot = _snapshot(paths)
    estimate = estimate_pod_cost(
        model_key=MODEL_KEY,
        snapshot=snapshot,  # type: ignore[arg-type]
        gpu_pool_priority=("NVIDIA A40", "NVIDIA GeForce RTX 4090"),
        cloud="SECURE",
        gpu_count=1,
        hours=2.0,
    )
    # 0.69 (4090 secure) beats 0.44 (A40 secure): the scheduler may rent either.
    assert estimate.gpu_type_id == "NVIDIA GeForce RTX 4090"
    assert estimate.hourly_rate_usd == 0.69
    assert estimate.gpu_usd == pytest.approx(1.38)
    assert estimate.required_usd > estimate.gpu_usd  # container disk is included
    assert estimate.required_usd == pytest.approx(1.38 + 0.10 / 720 * 80 * 2)


def test_gpu_count_min_multiplies_the_ceiling(paths: CampaignPaths) -> None:
    snapshot = _snapshot(paths)
    single = estimate_pod_cost(
        model_key=MODEL_KEY,
        snapshot=snapshot,  # type: ignore[arg-type]
        gpu_pool_priority=("NVIDIA GeForce RTX 4090",),
        hours=2.0,
        gpu_count=1,
    )
    double = estimate_pod_cost(
        model_key=MODEL_KEY,
        snapshot=snapshot,  # type: ignore[arg-type]
        gpu_pool_priority=("NVIDIA GeForce RTX 4090",),
        hours=2.0,
        gpu_count=2,
    )
    assert double.gpu_usd == pytest.approx(single.gpu_usd * 2)


def test_an_unpriced_pool_raises_rather_than_costing_zero(paths: CampaignPaths) -> None:
    write_catalog_snapshot(
        paths,
        rows=[
            {
                "gpu_type_id": "NVIDIA A100-SXM4-40GB",
                "display_name": "A100 40GB",
                "memory_gb": 40,
                "secure_available": False,
                "community_available": True,
                "price_secure_usd_per_hour": 0.0,
                "price_community_usd_per_hour": 1.0,
            }
        ],
    )
    path = latest_price_snapshot_path(paths.provider_receipts_dir)
    assert path is not None
    snapshot = load_price_snapshot(path)
    with pytest.raises(GateError, match="cannot be projected"):
        estimate_pod_cost(
            model_key=MODEL_KEY,
            snapshot=snapshot,
            gpu_pool_priority=("NVIDIA A100-SXM4-40GB",),
            cloud="SECURE",
            hours=2.0,
        )


# --------------------------------------------------------- D6 authorization


def test_no_receipt_blocks_and_names_the_required_amount(paths: CampaignPaths) -> None:
    decision = authorize(
        paths=paths, phase="phase1_canary", model_key=MODEL_KEY, required_usd=1.5, now=NOW
    )
    assert decision.allowed is False
    assert "$1.50" in decision.reason
    assert "holds no authorization receipt" in decision.reason


def test_a_covering_receipt_allows_and_is_recorded(paths: CampaignPaths) -> None:
    receipt_path = write_authorization(paths, max_usd=25.0)
    decision = authorize(
        paths=paths, phase="phase1_canary", model_key=MODEL_KEY, required_usd=1.5, now=NOW
    )
    assert decision.allowed is True
    assert decision.receipt is not None
    assert decision.receipt.path == receipt_path
    record = decision.to_dict()
    assert record["authorization_receipt_sha256"] == decision.receipt.sha256
    assert record["required_usd"] == 1.5


def test_an_expired_receipt_blocks(paths: CampaignPaths) -> None:
    write_authorization(paths, expires_at="2026-09-03T12:00:00Z")
    decision = authorize(
        paths=paths, phase="phase1_canary", model_key=MODEL_KEY, required_usd=1.5, now=NOW
    )
    assert decision.allowed is False
    assert "expired" in decision.reason


def test_an_insufficient_ceiling_blocks(paths: CampaignPaths) -> None:
    write_authorization(paths, max_usd=0.5)
    decision = authorize(
        paths=paths, phase="phase1_canary", model_key=MODEL_KEY, required_usd=1.5, now=NOW
    )
    assert decision.allowed is False
    assert "max_usd=0.5" in decision.reason


def test_a_receipt_for_another_model_does_not_cover_this_one(paths: CampaignPaths) -> None:
    write_authorization(paths, model_keys=["glm_ocr"])
    decision = authorize(
        paths=paths, phase="phase1_canary", model_key=MODEL_KEY, required_usd=1.5, now=NOW
    )
    assert decision.allowed is False


def test_a_receipt_for_another_phase_does_not_cover_this_one(paths: CampaignPaths) -> None:
    write_authorization(paths, phase="phase1_canary", max_usd=500.0)
    decision = authorize(
        paths=paths, phase="phase2_full_run", model_key=MODEL_KEY, required_usd=1.5, now=NOW
    )
    assert decision.allowed is False
    assert "phase2_full_run" in decision.reason


def test_one_malformed_receipt_fails_the_whole_gate_closed(paths: CampaignPaths) -> None:
    write_authorization(paths, max_usd=500.0)
    (paths.authorizations_dir / "broken.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(GateError, match="unreadable"):
        authorize(
            paths=paths, phase="phase1_canary", model_key=MODEL_KEY, required_usd=1.0, now=NOW
        )


# ----------------------------------------------------------------- D7 licence


def test_a_blocked_licence_without_a_waiver_is_refused(paths: CampaignPaths) -> None:
    decision = license_gate(
        paths=paths, model_key="infinity_parser2_pro", statuses=("blocked", "approved")
    )
    assert decision.allowed is False
    assert "license-infinity_parser2_pro.json" in decision.reason


def test_a_founder_waiver_unblocks_that_model(paths: CampaignPaths) -> None:
    waiver = paths.license_waiver("infinity_parser2_pro")
    waiver.write_text(
        json.dumps({"model_key": "infinity_parser2_pro", "decided_by": "founder"}),
        encoding="utf-8",
    )
    decision = license_gate(
        paths=paths, model_key="infinity_parser2_pro", statuses=("blocked", None)
    )
    assert decision.allowed is True
    assert decision.waiver_sha256 is not None


def test_a_waiver_for_a_different_model_does_not_count(paths: CampaignPaths) -> None:
    waiver = paths.license_waiver("infinity_parser2_pro")
    waiver.write_text(json.dumps({"model_key": "glm_ocr"}), encoding="utf-8")
    decision = license_gate(paths=paths, model_key="infinity_parser2_pro", statuses=("blocked",))
    assert decision.allowed is False


def test_an_unblocked_licence_needs_no_waiver(paths: CampaignPaths) -> None:
    assert license_gate(paths=paths, model_key=MODEL_KEY, statuses=("verified",)).allowed


# ---------------------------------------------------------------- D9 pools


def test_an_unknown_gpu_name_is_reported_with_near_matches(paths: CampaignPaths) -> None:
    snapshot = _snapshot(paths)
    validation = validate_pool(
        MODEL_KEY,
        ("NVIDIA GeForce RTX 4090", "NVIDIA A4O"),
        snapshot,  # type: ignore[arg-type]
    )
    assert validation.ok is False
    assert validation.unknown == ("NVIDIA A4O",)
    assert "NVIDIA A40" in validation.suggestions["NVIDIA A4O"]
    assert "closest catalog ids" in validation.failure_lines()[0]


def test_a_known_pool_validates(paths: CampaignPaths) -> None:
    snapshot = _snapshot(paths)
    validation = validate_pool(
        MODEL_KEY,
        ("NVIDIA A40",),
        snapshot,  # type: ignore[arg-type]
    )
    assert validation.ok is True


def test_a_corrupt_snapshot_is_refused(paths: CampaignPaths, tmp_path: Path) -> None:
    broken = paths.provider_receipts_dir / "catalog-20260903T000000Z.json"
    broken.write_text(json.dumps({"captured_at": "x", "rows": []}), encoding="utf-8")
    with pytest.raises(GpuPoolError):
        load_price_snapshot(broken)


# ------------------------------------------------------- D5/D13 runtime.json


def test_runtime_json_supplies_gpu_count_and_the_stall_floor(paths: CampaignPaths) -> None:
    write_runtime_json(paths, gpu_count_min=2, per_page_timeout_seconds=900)
    view = load_runtime_spec(paths.runtime_json(MODEL_KEY), MODEL_KEY)
    assert view.gpu_count_min == 2
    assert view.per_page_timeout_seconds == 900
    assert view.license_blocked is False


def test_gpu_count_min_defaults_to_one(paths: CampaignPaths) -> None:
    write_runtime_json(paths)
    path = paths.runtime_json(MODEL_KEY)
    document = json.loads(path.read_text(encoding="utf-8"))
    del document["gpu_count_min"]
    path.write_text(json.dumps(document), encoding="utf-8")
    assert load_runtime_spec(path, MODEL_KEY).gpu_count_min == 1


def test_a_missing_runtime_json_is_reported(paths: CampaignPaths) -> None:
    with pytest.raises(RuntimeSpecError, match="is absent"):
        load_runtime_spec(paths.runtime_json("glm_ocr"), "glm_ocr")


def test_a_zero_page_timeout_is_refused(paths: CampaignPaths) -> None:
    write_runtime_json(paths, per_page_timeout_seconds=0)
    with pytest.raises(RuntimeSpecError, match="per_page_timeout_seconds"):
        load_runtime_spec(paths.runtime_json(MODEL_KEY), MODEL_KEY)


def test_a_persistent_volume_is_priced_into_the_ceiling(paths: CampaignPaths) -> None:
    """D24: a volume that is not priced is a cost the gate never saw."""

    snapshot = _snapshot(paths)
    common = {
        "model_key": MODEL_KEY,
        "snapshot": snapshot,
        "gpu_pool_priority": ("NVIDIA GeForce RTX 4090",),
        "cloud": "SECURE",
        "gpu_count": 1,
        "hours": 2.0,
    }
    without = estimate_pod_cost(**common)  # type: ignore[arg-type]
    with_volume = estimate_pod_cost(volume_gb=200, **common)  # type: ignore[arg-type]
    bigger_disk = estimate_pod_cost(container_disk_gb=300, **common)  # type: ignore[arg-type]

    assert with_volume.required_usd > without.required_usd
    assert bigger_disk.required_usd > without.required_usd
    # The GPU line is untouched; only the storage line moved.
    assert with_volume.gpu_usd == pytest.approx(without.gpu_usd)
    assert bigger_disk.gpu_usd == pytest.approx(without.gpu_usd)


def test_a_shorter_watchdog_is_what_gets_reserved() -> None:
    """D84. A run that kills its pod at 3 h must not reserve 6 h."""

    assert effective_pod_lifetime_hours("phase2_full_run") == 6
    assert effective_pod_lifetime_hours("phase2_full_run", 3) == 3
    assert effective_pod_lifetime_hours("phase1_canary", 1) == 1


def test_a_longer_request_is_clamped_to_the_d10_ceiling() -> None:
    """The knob narrows a lifetime and never widens one."""

    assert effective_pod_lifetime_hours("phase2_full_run", 24) == 6
    assert effective_pod_lifetime_hours("phase1_canary", 6) == 2


def test_a_fraction_rounds_up_so_the_reservation_covers_the_watchdog() -> None:
    """Reserving 2 h for a pod allowed 2.5 h would underprice it."""

    assert effective_pod_lifetime_hours("phase2_full_run", 2.5) == 3
    assert effective_pod_lifetime_hours("phase2_full_run", 0.25) == 1


def test_a_lifetime_of_zero_or_nonsense_is_refused() -> None:
    with pytest.raises(GateError):
        effective_pod_lifetime_hours("phase2_full_run", 0)
    with pytest.raises(GateError):
        effective_pod_lifetime_hours("phase2_full_run", -1)
    with pytest.raises(GateError):
        effective_pod_lifetime_hours("phase2_full_run", "soon")
    with pytest.raises(GateError):
        effective_pod_lifetime_hours("phase9_imaginary", 2)


def test_a_shorter_lifetime_costs_proportionally_less(paths: CampaignPaths) -> None:
    """The point of D84: the ceiling that blocked the campaign shrinks."""

    snapshot = _snapshot(paths)
    six = estimate_pod_cost(
        model_key=MODEL_KEY,
        snapshot=snapshot,  # type: ignore[arg-type]
        gpu_pool_priority=("NVIDIA GeForce RTX 4090",),
        hours=float(effective_pod_lifetime_hours("phase2_full_run")),
    )
    three = estimate_pod_cost(
        model_key=MODEL_KEY,
        snapshot=snapshot,  # type: ignore[arg-type]
        gpu_pool_priority=("NVIDIA GeForce RTX 4090",),
        hours=float(effective_pod_lifetime_hours("phase2_full_run", 3)),
    )
    assert three.required_usd == pytest.approx(six.required_usd / 2)


def test_a_full_run_gate_receipt_does_not_overwrite_the_canary_one(
    paths: CampaignPaths,
) -> None:
    """D85. One path per model meant the Full Run erased the canary's."""

    canary = paths.provision_gate_receipt("glm_ocr", "phase1_canary")
    full = paths.provision_gate_receipt("glm_ocr", "phase2_full_run")
    assert canary == paths.canary_provision_receipt("glm_ocr")
    assert canary != full
    assert full.name == "full-run-provision-glm_ocr.json"


def test_each_slice_of_a_full_run_keeps_its_own_gate_receipt(
    paths: CampaignPaths,
) -> None:
    """Thirty-one slices sharing one filename left one survivor."""

    first = paths.provision_gate_receipt("glm_ocr", "phase2_full_run", shard_index=0, shard_count=5)
    second = paths.provision_gate_receipt(
        "glm_ocr", "phase2_full_run", shard_index=1, shard_count=5
    )
    assert first != second
    assert first.name == "full-run-provision-glm_ocr-s0of5.json"
    assert len({first, second, paths.provision_gate_receipt("glm_ocr", "phase1_canary")}) == 3
