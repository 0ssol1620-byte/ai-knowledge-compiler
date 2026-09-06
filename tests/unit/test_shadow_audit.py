from __future__ import annotations

from akc_cir.shadow_audit import ShadowAuditPolicy, run_shadow_audit, should_shadow_audit


def test_high_risk_is_always_shadowed() -> None:
    required, reason = should_shadow_audit(
        "chg-1", risk=0.9, policy=ShadowAuditPolicy(sample_rate=0)
    )
    assert required
    assert "high-risk" in reason


def test_zero_sample_rate_skips_low_risk() -> None:
    required, _ = should_shadow_audit(
        "chg-1", risk=0.1, policy=ShadowAuditPolicy(sample_rate=0)
    )
    assert not required


def test_equivalent_shadow_allows_selective_result() -> None:
    result = run_shadow_audit(
        change_id="chg-1",
        risk=0.9,
        full_rebuild={"a": "new", "b": "same"},
        selective_rebuild={"a": "new"},
        carried_over={"b": "same"},
    )
    assert result.ran
    assert not result.fallback_required
    assert result.safe_to_publish_selective


def test_shadow_mismatch_forces_safe_full_rebuild_fallback() -> None:
    result = run_shadow_audit(
        change_id="chg-2",
        risk=0.9,
        full_rebuild={"a": "new", "b": "new-b"},
        selective_rebuild={"a": "new"},
        carried_over={"b": "old-b"},
    )
    assert result.ran
    assert result.fallback_required
    assert result.equivalence is not None
    assert result.equivalence.stale_left_behind == ("b",)
    assert not result.safe_to_publish_selective