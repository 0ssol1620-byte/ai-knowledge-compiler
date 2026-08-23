"""Replay rebuilds the context a past consumption saw, from immutable history.

The bitemporal rule carries the weight: a reconstruction is bounded by what
was *known* at consumption time, not by what is known now. A policy revision
backdated to look older than it is must not leak into a context that predates
its recording -- the agent that answered earlier was not wrong, it answered
from what was recorded then. And history itself is read-only: reconstructing
must leave every snapshot byte-identical.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from akc_cir.consumption_receipt import (
    ConsumerType,
    ConsumptionOutcome,
    ConsumptionReceipt,
)
from akc_cir.replay import (
    ContextPackage,
    PolicyRevision,
    ReplayError,
    reconstruct_context,
)

_T0 = datetime(2026, 8, 20, 9, 0, 0, tzinfo=UTC)

WORLD_HISTORY_DIR = "world-history"

SNAPSHOT_WS_OLD = {
    "world_state_id": "ws_2026_08_20",
    "workspace_id": "wspace_folynta",
    "status": "SUPERSEDED",
    "compiler_version": "cir_1.4.2",
    "built_at": "2026-08-20T08:55:00+00:00",
    "activated_at": "2026-08-20T08:56:00+00:00",
    "claims": [
        {
            "claim_id": "claim_warranty_two_year",
            "text": "The warranty covers parts and labour for two years from delivery.",
            "valid_from": "2024-01-01T00:00:00+00:00",
            "valid_until": "2026-08-20T10:00:00+00:00",
        },
        {
            "claim_id": "claim_refund_window",
            "text": "Refunds are accepted within 30 days of delivery.",
            "valid_from": None,
            "valid_until": None,
        },
    ],
    "evidence": [
        {"evidence_id": "ev_policy_pdf_p12", "kind": "pdf_page", "uri": "s3://docs/policy.pdf#p12"}
    ],
}


def _write_snapshot(history_dir: Path, snapshot: dict[str, object]) -> None:
    history_dir.mkdir(parents=True, exist_ok=True)
    path = history_dir / f"{snapshot['world_state_id']}.json"
    path.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")


@pytest.fixture()
def history_dir(tmp_path: Path) -> Path:
    world_history = tmp_path / WORLD_HISTORY_DIR
    _write_snapshot(world_history, SNAPSHOT_WS_OLD)
    return world_history


def _receipt(requested_at: datetime) -> ConsumptionReceipt:
    return ConsumptionReceipt(
        receipt_id="cr_0001",
        consumer_type=ConsumerType.ASK,
        consumer_id="user_yspow",
        request_id="req_0001",
        query_tool="ask_as_of",
        requested_at=requested_at,
        world_state_id="ws_2026_08_20",
        claim_ids=("claim_warranty_two_year",),
        evidence_ids=("ev_policy_pdf_p12",),
        permission_snapshot_ref="perm_snap_77",
        policy_revision="policy_rev_3",
        outcome=ConsumptionOutcome.CURRENT,
        response_artifact_hash="sha256:" + "a" * 64,
    )


def _at(minutes: int) -> datetime:
    """Minutes after the ws_old snapshot was built."""
    return _T0 + timedelta(minutes=minutes)


def _revisions() -> tuple[PolicyRevision, ...]:
    return (
        PolicyRevision(
            revision_id="policy_rev_3",
            known_at=_at(1),  # known one minute after build
            valid_from=datetime(2026, 8, 1, tzinfo=UTC),
            rules={"max_answer_age_seconds": 3600},
        ),
        # Backdated: claims to govern from long before, but was only recorded
        # much later. It must never reach backwards over its own recording.
        PolicyRevision(
            revision_id="policy_rev_9_backdated",
            known_at=_at(120),
            valid_from=datetime(2026, 7, 1, tzinfo=UTC),
            rules={"max_answer_age_seconds": 60},
        ),
    )


class TestReconstruction:
    def test_context_package_reflects_the_past_snapshot(self, history_dir: Path) -> None:
        package = reconstruct_context(_receipt(_at(5)), history_dir, _revisions())

        assert isinstance(package, ContextPackage)
        assert package.world_state.world_state_id == "ws_2026_08_20"
        assert package.world_state.status == "SUPERSEDED"
        assert [c.claim_id for c in package.claims] == ["claim_warranty_two_year"]
        assert (
            package.claims[0].text
            == "The warranty covers parts and labour for two years from delivery."
        )
        assert [e.evidence_id for e in package.evidence] == ["ev_policy_pdf_p12"]

    def test_three_clocks_are_pinned_and_ordered(self, history_dir: Path) -> None:
        package = reconstruct_context(_receipt(_at(5)), history_dir, _revisions())

        assert package.consumption_time == _at(5)
        assert package.valid_time == datetime(2026, 8, 20, 8, 55, 0, tzinfo=UTC)
        # Everything in the package was known by minute 5: the world at :56,
        # the policy at :01.
        assert package.known_time <= package.consumption_time
        assert package.known_time == max(
            datetime(2026, 8, 20, 8, 56, 0, tzinfo=UTC), _at(1)
        )

    def test_snapshot_claims_not_requested_are_not_included(self, history_dir: Path) -> None:
        receipt = _receipt(_at(5))
        other = ConsumptionReceipt(
            **{
                **{f.name: getattr(receipt, f.name) for f in receipt.__dataclass_fields__.values()},
                "claim_ids": ("claim_refund_window",),
                "evidence_ids": (),
            }
        )
        package = reconstruct_context(other, history_dir, _revisions())
        assert [c.claim_id for c in package.claims] == ["claim_refund_window"]
        assert package.evidence == ()


class TestBackdatedPolicy:
    def test_later_recorded_revision_never_reaches_backward(self, history_dir: Path) -> None:
        # The backdated rev_9 declares validity from July 1st -- before the
        # receipt -- but was recorded two hours later. The minute-5 answer ran
        # under rev_3, and replay must say so, not flatter the backdate.
        package = reconstruct_context(_receipt(_at(5)), history_dir, _revisions())
        assert package.policy_rev.revision_id == "policy_rev_3"

    def test_after_the_revision_is_known_it_applies(self, history_dir: Path) -> None:
        package = reconstruct_context(_receipt(_at(150)), history_dir, _revisions())
        assert package.policy_rev.revision_id == "policy_rev_9_backdated"
        assert package.known_time == _at(120)


class TestHistoryIsReadOnly:
    def test_reconstruction_leaves_every_snapshot_byte_identical(
        self, history_dir: Path
    ) -> None:
        before = {p.name: p.read_bytes() for p in sorted(history_dir.iterdir())}
        reconstruct_context(_receipt(_at(5)), history_dir, _revisions())
        after = {p.name: p.read_bytes() for p in sorted(history_dir.iterdir())}
        assert before == after


class TestRefusals:
    def test_missing_world_snapshot_is_an_error(self, tmp_path: Path) -> None:
        empty = tmp_path / "history"
        empty.mkdir()
        with pytest.raises(ReplayError, match="ws_2026_08_20"):
            reconstruct_context(_receipt(_at(5)), empty, _revisions())

    def test_no_policy_known_at_consumption_time_is_an_error(self, history_dir: Path) -> None:
        with pytest.raises(ReplayError, match="policy"):
            reconstruct_context(_receipt(_at(0)), history_dir, _revisions())

    def test_claim_absent_from_the_snapshot_is_an_error(self, history_dir: Path) -> None:
        receipt = _receipt(_at(5))
        smuggled = ConsumptionReceipt(
            **{
                **{f.name: getattr(receipt, f.name) for f in receipt.__dataclass_fields__.values()},
                "claim_ids": ("claim_from_the_future",),
            }
        )
        with pytest.raises(ReplayError, match="claim_from_the_future"):
            reconstruct_context(smuggled, history_dir, _revisions())

    def test_knowledge_newer_than_the_consumption_is_inconsistent(self, tmp_path: Path) -> None:
        # A snapshot claiming activation *after* the receipt was served cannot
        # be what the consumer saw.
        impossible = dict(SNAPSHOT_WS_OLD)
        impossible["activated_at"] = "2026-08-20T09:30:00+00:00"  # after _at(5)
        world_history = tmp_path / WORLD_HISTORY_DIR
        _write_snapshot(world_history, impossible)
        with pytest.raises(ReplayError):
            reconstruct_context(_receipt(_at(5)), world_history, _revisions())
