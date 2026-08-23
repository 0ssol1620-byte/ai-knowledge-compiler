"""Consumption receipts record what an answer consumed, and cannot forget it.

Three properties are load-bearing here. A receipt mints a stable digest over
exactly its declared fields, so two records of the same consumption agree byte
for byte and any edited field changes the mint. The ledger chains those mints
through ``seq`` and ``prev_digest`` so editing, reordering, skipping or
truncating recorded history fails loudly at open instead of replaying quietly.
And queries answer from history alone: a claim that has since gone stale still
shows every past consumption of it, because append-only means *nothing* is
rewritten when the world moves on.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from akc_cir.consumption_receipt import (
    GENESIS_DIGEST,
    ConsumerType,
    ConsumptionLedger,
    ConsumptionOutcome,
    ConsumptionReceipt,
    LedgerTamperedError,
)

_T0 = datetime(2026, 8, 20, 9, 0, 0, tzinfo=UTC)


def _receipt(
    receipt_id: str = "cr_0001",
    *,
    requested_at: datetime = _T0,
    world_state_id: str = "ws_2026_08_20",
    claim_ids: tuple[str, ...] = ("claim_warranty_two_year",),
    consumer_type: ConsumerType = ConsumerType.ASK,
    outcome: ConsumptionOutcome = ConsumptionOutcome.CURRENT,
) -> ConsumptionReceipt:
    return ConsumptionReceipt(
        receipt_id=receipt_id,
        consumer_type=consumer_type,
        consumer_id="user_yspow",
        request_id="req_0001",
        query_tool="ask_as_of",
        requested_at=requested_at,
        world_state_id=world_state_id,
        claim_ids=claim_ids,
        evidence_ids=("ev_policy_pdf_p12",),
        permission_snapshot_ref="perm_snap_77",
        policy_revision="policy_rev_3",
        outcome=outcome,
        response_artifact_hash="sha256:" + "a" * 64,
    )


def _at(minute: int) -> datetime:
    return _T0 + timedelta(minutes=minute)


# ---------------------------------------------------------------------------
# Minting
# ---------------------------------------------------------------------------


class TestMint:
    def test_mint_is_deterministic_over_declared_fields(self) -> None:
        assert _receipt().mint() == _receipt().mint()

    def test_mint_covers_every_field(self) -> None:
        base = _receipt()
        edits = [
            _receipt(receipt_id="cr_0002"),
            _receipt(consumer_type=ConsumerType.MCP),
            _receipt(claim_ids=("claim_other",)),
            _receipt(outcome=ConsumptionOutcome.STALE),
            _receipt(requested_at=_at(1)),
        ]
        for edited in edits:
            assert edited.mint() != base.mint(), (
                f"changing {edited!r} must change the mint"
            )


# ---------------------------------------------------------------------------
# Appending and chain integrity
# ---------------------------------------------------------------------------


class TestAppend:
    def test_append_assigns_sequence_and_chains_digests(self, tmp_path: Path) -> None:
        ledger = ConsumptionLedger(tmp_path)
        first = ledger.append(_receipt("cr_0001"))
        second = ledger.append(_receipt("cr_0002", requested_at=_at(1)))

        assert first.seq == 1
        assert second.seq == 2
        assert first.prev_digest == GENESIS_DIGEST
        assert second.prev_digest == first.digest

    def test_appended_records_survive_reopen(self, tmp_path: Path) -> None:
        ledger = ConsumptionLedger(tmp_path)
        appended = [ledger.append(_receipt(f"cr_{i:04d}", requested_at=_at(i))) for i in range(3)]

        reopened = ConsumptionLedger(tmp_path)
        assert [r.seq for r in reopened.entries()] == [1, 2, 3]
        assert [r.receipt.receipt_id for r in reopened.entries()] == [
            "cr_0000",
            "cr_0001",
            "cr_0002",
        ]
        assert reopened.last_digest == appended[-1].digest
        assert len(reopened) == 3

    def test_one_fsynced_json_line_per_receipt(self, tmp_path: Path) -> None:
        ledger = ConsumptionLedger(tmp_path)
        ledger.append(_receipt())
        lines = (tmp_path / ConsumptionLedger.FILENAME).read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["seq"] == 1
        assert record["prev_digest"] == GENESIS_DIGEST
        assert record["digest"]


class TestTamperDetection:
    def test_editing_a_mid_chain_field_is_detected_at_open(self, tmp_path: Path) -> None:
        ledger = ConsumptionLedger(tmp_path)
        for i in range(3):
            ledger.append(_receipt(f"cr_{i:04d}", requested_at=_at(i)))

        path = tmp_path / ConsumptionLedger.FILENAME
        lines = path.read_text(encoding="utf-8").splitlines()
        forged = json.loads(lines[1])
        forged["receipt"]["claim_ids"] = ["claim_smuggled"]
        lines[1] = json.dumps(forged, sort_keys=True, separators=(",", ":"))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        with pytest.raises(LedgerTamperedError) as excinfo:
            ConsumptionLedger(tmp_path)
        assert excinfo.value.seq == 2

    def test_deleting_a_line_is_detected_as_a_gap(self, tmp_path: Path) -> None:
        ledger = ConsumptionLedger(tmp_path)
        for i in range(3):
            ledger.append(_receipt(f"cr_{i:04d}", requested_at=_at(i)))

        path = tmp_path / ConsumptionLedger.FILENAME
        lines = path.read_text(encoding="utf-8").splitlines()
        del lines[1]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        with pytest.raises(LedgerTamperedError):
            ConsumptionLedger(tmp_path)

    def test_verify_names_a_truncated_tail(self, tmp_path: Path) -> None:
        ledger = ConsumptionLedger(tmp_path)
        for i in range(3):
            ledger.append(_receipt(f"cr_{i:04d}", requested_at=_at(i)))

        path = tmp_path / ConsumptionLedger.FILENAME
        lines = path.read_text(encoding="utf-8").splitlines()
        path.write_text("\n".join(lines[:2]) + "\n", encoding="utf-8")
        with pytest.raises(LedgerTamperedError):
            ledger.verify()


class TestRefusals:
    def test_naive_requested_at_is_refused(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            _receipt(requested_at=datetime(2026, 8, 20, 9, 0, 0))

    def test_unknown_consumer_type_is_refused(self) -> None:
        with pytest.raises(ValueError):
            _receipt(consumer_type="cron")  # type: ignore[arg-type]

    def test_empty_required_ids_are_refused(self) -> None:
        with pytest.raises(ValueError):
            _receipt(receipt_id="  ")
        with pytest.raises(ValueError):
            _receipt(world_state_id="")


# ---------------------------------------------------------------------------
# Queries answer from history, even after the world moved on
# ---------------------------------------------------------------------------


class TestQueries:
    @pytest.fixture()
    def ledger_with_history(self, tmp_path: Path) -> ConsumptionLedger:
        ledger = ConsumptionLedger(tmp_path)
        # Two consumptions of claim_warranty..., one of claim_refund..., all in
        # ws_old. Later the world moves on and the warranty claim goes stale.
        ledger.append(
            _receipt(
                "cr_0001",
                requested_at=_at(0),
                claim_ids=("claim_warranty_two_year",),
                consumer_type=ConsumerType.ASK,
            )
        )
        ledger.append(
            _receipt(
                "cr_0002",
                requested_at=_at(10),
                world_state_id="ws_old",
                claim_ids=("claim_warranty_two_year", "claim_refund_window"),
                consumer_type=ConsumerType.MCP,
            )
        )
        ledger.append(
            _receipt(
                "cr_0003",
                requested_at=_at(30),
                world_state_id="ws_new",
                claim_ids=("claim_refund_window",),
                outcome=ConsumptionOutcome.STALE,
            )
        )
        return ledger

    def test_past_consumptions_of_a_claim_survive_it_going_stale(
        self, ledger_with_history: ConsumptionLedger
    ) -> None:
        # By minute 60 the warranty claim is stale in every live world -- the
        # ledger must still show who consumed it, and when.
        receipts = ledger_with_history.query_claims_before_stale(
            "claim_warranty_two_year", as_of=_at(60)
        )
        assert [r.receipt_id for r in receipts] == ["cr_0001", "cr_0002"]

    def test_as_of_bounds_the_claim_query(self, ledger_with_history: ConsumptionLedger) -> None:
        receipts = ledger_with_history.query_claims_before_stale(
            "claim_warranty_two_year", as_of=_at(5)
        )
        assert [r.receipt_id for r in receipts] == ["cr_0001"]

    def test_unknown_claim_queries_to_nothing(self, ledger_with_history: ConsumptionLedger) -> None:
        assert (
            ledger_with_history.query_claims_before_stale("claim_never_consumed", as_of=_at(99))
            == ()
        )

    def test_world_consumers_lists_who_consumed_a_world_state(
        self, ledger_with_history: ConsumptionLedger
    ) -> None:
        receipts = ledger_with_history.query_world_consumers("ws_old")
        assert [(r.consumer_type, r.receipt_id) for r in receipts] == [
            (ConsumerType.MCP, "cr_0002")
        ]
        # The current-world consumptions answer separately.
        current = ledger_with_history.query_world_consumers("ws_new")
        assert [r.receipt_id for r in current] == ["cr_0003"]
