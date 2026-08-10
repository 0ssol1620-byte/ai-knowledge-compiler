"""Atomic world-state publish — §N22.

Invariant 13 is the property: an agent never sees a partial state. The tests that
matter most are the refusals, because the failure this prevents does not raise on
its own -- a half-published world answers questions consistently with neither the
old world nor the new, and nothing logs it.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from akc_cir.recompilation import EquivalenceReport, RecompilationPlan
from akc_cir.world_state import (
    PublicationManifest,
    PublishRefused,
    ValidationReceipt,
    WorldStateRegistry,
    WorldStateStatus,
    publication_manifest,
)

T0 = datetime(2026, 8, 10, 9, 0, tzinfo=UTC)
T1 = datetime(2026, 8, 10, 10, 0, tzinfo=UTC)
T2 = datetime(2026, 8, 10, 11, 0, tzinfo=UTC)

ARTIFACTS = {"chunk_88": "sha256:aaa", "vault_md": "sha256:bbb"}


def _manifest(world_state_id: str = "ws_2", **kw) -> PublicationManifest:
    return publication_manifest(
        world_state_id=world_state_id,
        compiler_version=kw.pop("compiler_version", "akc/1.4.0"),
        artifact_hashes=kw.pop("artifact_hashes", ARTIFACTS),
    )


def _receipt(**kw) -> ValidationReceipt:
    base = {
        "receipt_id": "vr_1",
        "checksums_verified": True,
        "permission_checked": True,
        "integrity_passed": True,
    }
    base.update(kw)
    return ValidationReceipt(**base)


def _registry() -> WorldStateRegistry:
    registry = WorldStateRegistry("ws_acme")
    registry.stage(world_state_id="ws_1", compiler_version="akc/1.4.0", built_at=T0)
    registry.publish(
        "ws_1",
        manifest=_manifest("ws_1"),
        receipt=_receipt(),
        artifacts=ARTIFACTS,
        activated_at=T0,
    )
    return registry


def _plan() -> RecompilationPlan:
    return RecompilationPlan(change_id="chg_1", targets=(), total_artifacts=2)


def _equivalent(ok: bool = True) -> EquivalenceReport:
    return EquivalenceReport(
        equivalent=ok,
        compared=2,
        diverged=() if ok else ("vault_md",),
        stale_left_behind=() if ok else ("vault_md",),
    )


# --------------------------------------------------------------------------
# §N22.2 — build alongside, never into
# --------------------------------------------------------------------------


def test_a_candidate_is_not_what_readers_see() -> None:
    registry = _registry()

    registry.stage(world_state_id="ws_2", compiler_version="akc/1.4.0", built_at=T1)

    assert registry.current is not None
    assert registry.current.world_state_id == "ws_1"


def test_publishing_swaps_the_pointer() -> None:
    registry = _registry()
    registry.stage(world_state_id="ws_2", compiler_version="akc/1.4.0", built_at=T1)

    result = registry.publish(
        "ws_2",
        manifest=_manifest(),
        receipt=_receipt(),
        artifacts=ARTIFACTS,
        activated_at=T1,
    )

    assert registry.current is not None
    assert registry.current.world_state_id == "ws_2"
    assert result.previous_world_state_id == "ws_1"


def test_only_one_world_state_is_ever_active() -> None:
    """§73.10's unique partial index, as a property."""
    registry = _registry()
    registry.stage(world_state_id="ws_2", compiler_version="akc/1.4.0", built_at=T1)
    registry.publish(
        "ws_2",
        manifest=_manifest(),
        receipt=_receipt(),
        artifacts=ARTIFACTS,
        activated_at=T1,
    )

    assert registry.active_count() == 1


def test_the_superseded_state_is_marked_not_deleted() -> None:
    registry = _registry()
    registry.stage(world_state_id="ws_2", compiler_version="akc/1.4.0", built_at=T1)
    registry.publish(
        "ws_2",
        manifest=_manifest(),
        receipt=_receipt(),
        artifacts=ARTIFACTS,
        activated_at=T1,
    )

    previous = registry.get("ws_1")
    assert previous is not None
    assert previous.status is WorldStateStatus.SUPERSEDED


def test_a_candidate_records_what_it_was_built_from() -> None:
    registry = _registry()

    candidate = registry.stage(
        world_state_id="ws_2", compiler_version="akc/1.4.0", built_at=T1
    )

    assert candidate.parent_world_state_id == "ws_1"


# --------------------------------------------------------------------------
# §N22.3 — verification precedes the swap
# --------------------------------------------------------------------------


def test_a_checksum_mismatch_blocks_the_publish() -> None:
    registry = _registry()
    registry.stage(world_state_id="ws_2", compiler_version="akc/1.4.0", built_at=T1)

    with pytest.raises(PublishRefused, match="checksum mismatch"):
        registry.publish(
            "ws_2",
            manifest=_manifest(),
            receipt=_receipt(),
            artifacts={"chunk_88": "sha256:aaa", "vault_md": "sha256:WRONG"},
            activated_at=T1,
        )


def test_a_blocked_publish_leaves_the_old_state_serving() -> None:
    """The point of verifying first: nothing was swapped, so nothing broke."""
    registry = _registry()
    registry.stage(world_state_id="ws_2", compiler_version="akc/1.4.0", built_at=T1)

    with pytest.raises(PublishRefused):
        registry.publish(
            "ws_2",
            manifest=_manifest(),
            receipt=_receipt(),
            artifacts={"chunk_88": "sha256:aaa"},
            activated_at=T1,
        )

    assert registry.current is not None
    assert registry.current.world_state_id == "ws_1"


def test_failed_validation_blocks_the_publish() -> None:
    registry = _registry()
    registry.stage(world_state_id="ws_2", compiler_version="akc/1.4.0", built_at=T1)

    with pytest.raises(PublishRefused, match="integrity validation failed"):
        registry.publish(
            "ws_2",
            manifest=_manifest(),
            receipt=_receipt(integrity_passed=False),
            artifacts=ARTIFACTS,
            activated_at=T1,
        )


def test_an_unrun_permission_check_blocks_the_publish() -> None:
    registry = _registry()
    registry.stage(world_state_id="ws_2", compiler_version="akc/1.4.0", built_at=T1)

    with pytest.raises(PublishRefused, match="permission check did not run"):
        registry.publish(
            "ws_2",
            manifest=_manifest(),
            receipt=_receipt(permission_checked=False),
            artifacts=ARTIFACTS,
            activated_at=T1,
        )


def test_a_rejected_candidate_cannot_be_published_on_a_retry() -> None:
    registry = _registry()
    registry.stage(world_state_id="ws_2", compiler_version="akc/1.4.0", built_at=T1)
    with pytest.raises(PublishRefused):
        registry.publish(
            "ws_2",
            manifest=_manifest(),
            receipt=_receipt(integrity_passed=False),
            artifacts=ARTIFACTS,
            activated_at=T1,
        )

    with pytest.raises(PublishRefused, match="another publish already claimed it"):
        registry.publish(
            "ws_2",
            manifest=_manifest(),
            receipt=_receipt(),
            artifacts=ARTIFACTS,
            activated_at=T1,
        )


def test_publishing_the_same_candidate_twice_is_refused() -> None:
    """Step 5's serializable re-read, and what the unique index enforces."""
    registry = _registry()
    registry.stage(world_state_id="ws_2", compiler_version="akc/1.4.0", built_at=T1)
    registry.publish(
        "ws_2",
        manifest=_manifest(),
        receipt=_receipt(),
        artifacts=ARTIFACTS,
        activated_at=T1,
    )

    with pytest.raises(PublishRefused, match="not a candidate"):
        registry.publish(
            "ws_2",
            manifest=_manifest(),
            receipt=_receipt(),
            artifacts=ARTIFACTS,
            activated_at=T2,
        )


def test_publishing_something_never_staged_is_refused() -> None:
    with pytest.raises(PublishRefused, match="never staged"):
        _registry().publish(
            "ws_ghost",
            manifest=_manifest(),
            receipt=_receipt(),
            artifacts=ARTIFACTS,
            activated_at=T1,
        )


# --------------------------------------------------------------------------
# §N22.4 — equivalence, and the missing check
# --------------------------------------------------------------------------


def test_a_selective_build_without_an_equivalence_check_is_refused() -> None:
    """A missing check is not a passing one."""
    registry = _registry()
    registry.stage(world_state_id="ws_2", compiler_version="akc/1.4.0", built_at=T1)

    with pytest.raises(PublishRefused, match="not a passing one"):
        registry.publish(
            "ws_2",
            manifest=_manifest(),
            receipt=_receipt(),
            artifacts=ARTIFACTS,
            activated_at=T1,
            plan=_plan(),
        )


def test_a_selective_build_that_diverges_is_refused() -> None:
    registry = _registry()
    registry.stage(world_state_id="ws_2", compiler_version="akc/1.4.0", built_at=T1)

    with pytest.raises(PublishRefused, match="does not match a full rebuild"):
        registry.publish(
            "ws_2",
            manifest=_manifest(),
            receipt=_receipt(equivalence=_equivalent(ok=False)),
            artifacts=ARTIFACTS,
            activated_at=T1,
            plan=_plan(),
        )


def test_a_selective_build_that_matches_publishes() -> None:
    registry = _registry()
    registry.stage(world_state_id="ws_2", compiler_version="akc/1.4.0", built_at=T1)

    result = registry.publish(
        "ws_2",
        manifest=_manifest(),
        receipt=_receipt(equivalence=_equivalent()),
        artifacts=ARTIFACTS,
        activated_at=T1,
        plan=_plan(),
    )

    assert result.world_state.status is WorldStateStatus.ACTIVE


def test_a_full_rebuild_needs_no_equivalence_check() -> None:
    """There is nothing to compare a full rebuild against."""
    registry = _registry()
    registry.stage(world_state_id="ws_2", compiler_version="akc/1.4.0", built_at=T1)

    result = registry.publish(
        "ws_2",
        manifest=_manifest(),
        receipt=_receipt(),
        artifacts=ARTIFACTS,
        activated_at=T1,
    )

    assert result.world_state.status is WorldStateStatus.ACTIVE


# --------------------------------------------------------------------------
# §N22.3 step 7 — the outbox row belongs to the transaction
# --------------------------------------------------------------------------


def test_a_successful_publish_emits_exactly_one_event() -> None:
    registry = _registry()
    registry.stage(world_state_id="ws_2", compiler_version="akc/1.4.0", built_at=T1)

    result = registry.publish(
        "ws_2",
        manifest=_manifest(),
        receipt=_receipt(),
        artifacts=ARTIFACTS,
        activated_at=T1,
    )

    assert len(result.outbox) == 1
    assert result.outbox[0]["type"] == "world_state.published"


def test_a_refused_publish_emits_nothing() -> None:
    """An event announcing a publish that did not happen desynchronises consumers."""
    registry = _registry()
    registry.stage(world_state_id="ws_2", compiler_version="akc/1.4.0", built_at=T1)

    with pytest.raises(PublishRefused):
        registry.publish(
            "ws_2",
            manifest=_manifest(),
            receipt=_receipt(integrity_passed=False),
            artifacts=ARTIFACTS,
            activated_at=T1,
        )

    assert registry.current is not None
    assert registry.current.world_state_id == "ws_1"


def test_the_event_carries_the_manifest_hash() -> None:
    registry = _registry()
    registry.stage(world_state_id="ws_2", compiler_version="akc/1.4.0", built_at=T1)
    manifest = _manifest()

    result = registry.publish(
        "ws_2",
        manifest=manifest,
        receipt=_receipt(),
        artifacts=ARTIFACTS,
        activated_at=T1,
    )

    assert result.outbox[0]["manifest_hash"] == manifest.manifest_hash


# --------------------------------------------------------------------------
# §N22.5 — rollback
# --------------------------------------------------------------------------


def test_rollback_restores_the_previous_state() -> None:
    registry = _registry()
    registry.stage(world_state_id="ws_2", compiler_version="akc/1.4.0", built_at=T1)
    registry.publish(
        "ws_2",
        manifest=_manifest(),
        receipt=_receipt(),
        artifacts=ARTIFACTS,
        activated_at=T1,
    )

    registry.rollback(to="ws_1", at=T2)

    assert registry.current is not None
    assert registry.current.world_state_id == "ws_1"


def test_rollback_does_not_delete_the_state_it_left() -> None:
    registry = _registry()
    registry.stage(world_state_id="ws_2", compiler_version="akc/1.4.0", built_at=T1)
    registry.publish(
        "ws_2",
        manifest=_manifest(),
        receipt=_receipt(),
        artifacts=ARTIFACTS,
        activated_at=T1,
    )

    registry.rollback(to="ws_1", at=T2)

    assert registry.get("ws_2") is not None
    assert "ws_2" in registry.history


def test_rolling_back_to_an_unpublished_candidate_is_refused() -> None:
    """Otherwise rollback becomes a way to publish something validation never saw."""
    registry = _registry()
    registry.stage(world_state_id="ws_2", compiler_version="akc/1.4.0", built_at=T1)

    with pytest.raises(PublishRefused, match="never published"):
        registry.rollback(to="ws_2", at=T2)


def test_rolling_back_to_the_current_state_is_refused() -> None:
    with pytest.raises(PublishRefused, match="already current"):
        _registry().rollback(to="ws_1", at=T2)


def test_rollback_emits_its_own_event() -> None:
    registry = _registry()
    registry.stage(world_state_id="ws_2", compiler_version="akc/1.4.0", built_at=T1)
    registry.publish(
        "ws_2",
        manifest=_manifest(),
        receipt=_receipt(),
        artifacts=ARTIFACTS,
        activated_at=T1,
    )

    result = registry.rollback(to="ws_1", at=T2)

    assert result.outbox[0]["type"] == "world_state.rolled_back"


# --------------------------------------------------------------------------
# The manifest
# --------------------------------------------------------------------------


def test_the_manifest_hash_does_not_depend_on_artifact_order() -> None:
    """Otherwise it changes on nothing and stops being evidence of anything."""
    left = publication_manifest(
        world_state_id="ws_1",
        compiler_version="akc/1.4.0",
        artifact_hashes={"a": "sha256:1", "b": "sha256:2"},
    )
    right = publication_manifest(
        world_state_id="ws_1",
        compiler_version="akc/1.4.0",
        artifact_hashes={"b": "sha256:2", "a": "sha256:1"},
    )

    assert left.manifest_hash == right.manifest_hash


def test_a_changed_artifact_changes_the_manifest_hash() -> None:
    left = publication_manifest(
        world_state_id="ws_1", compiler_version="akc/1.4.0", artifact_hashes={"a": "sha256:1"}
    )
    right = publication_manifest(
        world_state_id="ws_1", compiler_version="akc/1.4.0", artifact_hashes={"a": "sha256:9"}
    )

    assert left.manifest_hash != right.manifest_hash


def test_a_changed_compiler_version_changes_the_manifest_hash() -> None:
    """Same artifacts from a different compiler are not the same world."""
    left = publication_manifest(
        world_state_id="ws_1", compiler_version="akc/1.4.0", artifact_hashes=ARTIFACTS
    )
    right = publication_manifest(
        world_state_id="ws_1", compiler_version="akc/1.5.0", artifact_hashes=ARTIFACTS
    )

    assert left.manifest_hash != right.manifest_hash


def test_the_manifest_names_which_artifact_failed_verification() -> None:
    manifest = _manifest()

    assert manifest.verify({"chunk_88": "sha256:aaa", "vault_md": "sha256:X"}) == (
        "vault_md",
    )


def test_a_missing_artifact_fails_verification() -> None:
    assert _manifest().verify({"chunk_88": "sha256:aaa"}) == ("vault_md",)
