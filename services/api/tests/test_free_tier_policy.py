"""Boundary tests for daily free-tier caps and deduplication keys."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from akc_api.free_tier import (
    FreeTierCapExceeded,
    FreeTierCaps,
    FreeTierPolicyError,
    FreeUsageDelta,
    FreeUsageDimension,
    FreeUsageSnapshot,
    apply_free_usage,
    canonical_source_sha256,
    estimate_gpu_cost,
    is_free_plan,
    queue_priority_for_plan,
    seconds_until_utc_reset,
)


def test_caps_allow_exact_boundary_and_reject_one_more() -> None:
    now = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
    caps = FreeTierCaps(
        files=3,
        pages=100,
        gpu_cost_usd=Decimal("0.500000"),
    )
    current = FreeUsageSnapshot(
        usage_date=date(2026, 7, 29),
        files=2,
        pages=90,
        gpu_cost_usd=Decimal("0.400000"),
    )

    exact = apply_free_usage(
        current=current,
        delta=FreeUsageDelta(
            files=1,
            pages=10,
            gpu_cost_usd=Decimal("0.100000"),
        ),
        caps=caps,
        now=now,
    )
    assert exact.files == 3
    assert exact.pages == 100
    assert exact.gpu_cost_usd == Decimal("0.500000")

    with pytest.raises(FreeTierCapExceeded) as caught:
        apply_free_usage(
            current=exact,
            delta=FreeUsageDelta(files=1),
            caps=caps,
            now=now,
        )
    assert caught.value.dimension is FreeUsageDimension.FILES
    assert caught.value.retry_after_seconds == 43_200


@pytest.mark.parametrize(
    ("delta", "dimension"),
    [
        (FreeUsageDelta(pages=11), FreeUsageDimension.PAGES),
        (
            FreeUsageDelta(gpu_cost_usd=Decimal("0.100001")),
            FreeUsageDimension.GPU_COST_USD,
        ),
    ],
)
def test_each_cap_is_independently_enforced(
    delta: FreeUsageDelta,
    dimension: FreeUsageDimension,
) -> None:
    now = datetime(2026, 7, 29, 23, 59, 59, 500_000, tzinfo=UTC)
    with pytest.raises(FreeTierCapExceeded) as caught:
        apply_free_usage(
            current=FreeUsageSnapshot(
                usage_date=date(2026, 7, 29),
                files=2,
                pages=90,
                gpu_cost_usd=Decimal("0.400000"),
            ),
            delta=delta,
            caps=FreeTierCaps(
                files=3,
                pages=100,
                gpu_cost_usd=Decimal("0.500000"),
            ),
            now=now,
        )
    assert caught.value.dimension is dimension
    assert caught.value.retry_after_seconds == 1


def test_day_mismatch_and_invalid_usage_fail_closed() -> None:
    caps = FreeTierCaps(files=3, pages=100, gpu_cost_usd=Decimal("0.5"))
    with pytest.raises(FreeTierPolicyError):
        apply_free_usage(
            current=FreeUsageSnapshot(usage_date=date(2026, 7, 28)),
            delta=FreeUsageDelta(files=1),
            caps=caps,
            now=datetime(2026, 7, 29, tzinfo=UTC),
        )
    with pytest.raises(FreeTierPolicyError):
        FreeUsageDelta()
    with pytest.raises(FreeTierPolicyError):
        FreeUsageDelta(pages=-1)


def test_gpu_estimate_uses_exact_decimal_math() -> None:
    assert estimate_gpu_cost(
        visual_pages=7,
        per_visual_page_usd="0.0123456",
    ) == Decimal("0.086420")
    with pytest.raises(FreeTierPolicyError):
        estimate_gpu_cost(visual_pages=-1, per_visual_page_usd="0.1")
    with pytest.raises(FreeTierPolicyError):
        estimate_gpu_cost(visual_pages=1, per_visual_page_usd="NaN")


def test_source_hash_is_canonical_and_full_length() -> None:
    upper = "A" * 64
    assert canonical_source_sha256(f" {upper} ") == "a" * 64
    for invalid in ("a" * 63, "g" * 64, "sha256:" + "a" * 64):
        with pytest.raises(FreeTierPolicyError):
            canonical_source_sha256(invalid)


def test_free_work_receives_low_queue_priority() -> None:
    assert is_free_plan(" FREE ")
    assert queue_priority_for_plan("free") == 1
    assert queue_priority_for_plan("team") == 5


def test_utc_reset_delay_is_timezone_aware() -> None:
    assert seconds_until_utc_reset(datetime(2026, 7, 29, 23, 59, 59, 1, tzinfo=UTC)) == 1
