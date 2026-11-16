from __future__ import annotations

import socket
from decimal import Decimal
from pathlib import Path

import pytest

from benchmark.screen import campaign as camp
from benchmark.screen.campaign import Campaign, CampaignSpec, Stage, load_spec, reservation_plan
from benchmark.v6.contracts import ContractError
from benchmark.v6.ledger import EvidenceLedger


class FakeProvider:
    def __init__(self, *, delete_works: bool = True, leaked: tuple[str, ...] = ()) -> None:
        self.live: set[str] = set()
        self.leaked = set(leaked)
        self.delete_works = delete_works
        self.calls = 0

    def delete(self, resource_id: str) -> None:
        self.calls += 1
        if self.delete_works:
            self.live.discard(resource_id)

    def exists(self, resource_id: str) -> bool:
        self.calls += 1
        return resource_id in self.live

    def tagged_resource_ids(self, run_tag: str) -> list[str]:
        self.calls += 1
        return sorted(self.live | self.leaked)


def _spec() -> CampaignSpec:
    def st(i: str, cap: str, *req: str) -> Stage:
        return Stage(i, Decimal(cap), req, 1, "gpu")

    return CampaignSpec(
        "t-camp", "v6-t-camp", Decimal(100), (50, 80, 100),
        (st("S1", "55"), st("S2", "30", "S1"), st("S3", "15", "S2")),
    )


def _ledger(tmp_path: Path) -> EvidenceLedger:
    return EvidenceLedger(tmp_path / "l.jsonl", cohort_id="t", run_tag="v6-t-camp")


def _run(c: Campaign, stage: str, cost: str, rids: tuple[str, ...] = ()) -> None:
    c.reserve_stage(stage)
    c.complete_stage(stage, actual_cost_usd=cost, partial_results={"n": 1}, resource_ids=rids)


def test_real_spec_is_within_hard_cap() -> None:
    spec = load_spec()
    assert spec.hard_cap_usd == 350
    assert sum(s.cap_usd for s in spec.stages) == 260
    assert spec.stage("A2b").requires == ("A1", "A2a")


def test_reservation_over_stage_cap_refused(tmp_path: Path) -> None:
    c = Campaign(_spec(), _ledger(tmp_path), FakeProvider())
    with pytest.raises(ContractError, match="stage cap"):
        c.reserve_stage("S1", "55.01")
    assert c.budget.reserved_usd == 0


def test_missing_predecessor_receipt_refused(tmp_path: Path) -> None:
    c = Campaign(_spec(), _ledger(tmp_path), FakeProvider())
    with pytest.raises(ContractError, match="requires the S1 stage receipt"):
        c.reserve_stage("S2")
    _run(c, "S1", "10")
    c.reserve_stage("S2")


def test_alerts_fire_once_and_hundred_stops(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    c = Campaign(_spec(), ledger, FakeProvider())
    _run(c, "S1", "55")
    _run(c, "S2", "30")
    _run(c, "S3", "15")
    c._alerts()  # idempotent
    assert [p["percent"] for p in c._payloads("campaign.alert.v1")] == [50, 80, 100]
    assert c.stopped
    restarted = Campaign(_spec(), ledger, FakeProvider())
    restarted._alerts()
    assert len(restarted._payloads("campaign.alert.v1")) == 3
    with pytest.raises(ContractError, match="stopped"):
        restarted.reserve_stage("S1")


def test_dry_run_makes_no_network_or_provider_call(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def boom(*a: object, **k: object) -> None:
        raise AssertionError("network used in dry run")

    monkeypatch.setattr(socket.socket, "connect", boom)
    monkeypatch.setattr(socket, "getaddrinfo", boom)
    assert camp.main(["--dry-run"]) == 0
    assert '"A2b"' in capsys.readouterr().out
    assert reservation_plan(load_spec())[-1]["remaining_usd"] == "90"


def test_teardown_needs_404_and_empty_orphan_audit(tmp_path: Path) -> None:
    p = FakeProvider(delete_works=False)
    p.live.add("pod1")
    c = Campaign(_spec(), _ledger(tmp_path), p)
    c.reserve_stage("S1")
    with pytest.raises(ContractError, match="teardown"):
        c.complete_stage("S1", actual_cost_usd="1", partial_results={}, resource_ids=("pod1",))
    assert not c.has_receipt("S1")

    leaky = FakeProvider(leaked=("orphan9",))
    c2 = Campaign(_spec(), _ledger(tmp_path / "b"), leaky)
    c2.reserve_stage("S1")
    with pytest.raises(ContractError, match="teardown"):
        c2.complete_stage("S1", actual_cost_usd="1", partial_results={}, resource_ids=())
    assert not c2.has_receipt("S1")

    ok = FakeProvider()
    ok.live.add("pod1")
    c3 = Campaign(_spec(), _ledger(tmp_path / "c"), ok)
    _run(c3, "S1", "1", ("pod1",))
    assert c3.has_receipt("S1")


def test_partial_results_written_before_stop_and_teardown(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    c = Campaign(_spec(), ledger, FakeProvider())
    _run(c, "S1", "55")
    _run(c, "S2", "30")
    _run(c, "S3", "15")
    kinds = [e.event_type for e in ledger.replay()]
    last = len(kinds) - 1 - kinds[::-1].index("campaign.partial.v1")
    assert last < kinds.index("campaign.stopped.v1") < kinds.index(
        "campaign.teardown.v1", last
    )


def test_stop_sweeps_foreign_tagged_resources(tmp_path: Path) -> None:
    p = FakeProvider()
    c = Campaign(_spec(), _ledger(tmp_path), p)
    _run(c, "S1", "55")
    _run(c, "S2", "30")
    p.live.add("stray1")
    _run(c, "S3", "15")
    assert "stray1" not in p.live


class _Flaky(FakeProvider):
    """delete() works, but the first GET after it still shows the resource."""

    def __init__(self) -> None:
        super().__init__()
        self.stale = 1

    def delete(self, resource_id: str) -> None:
        self.live.discard(resource_id)

    def exists(self, resource_id: str) -> bool:
        if self.stale:
            self.stale -= 1
            return True
        return False

    def tagged_resource_ids(self, run_tag: str) -> list[str]:
        return []


def test_overspend_still_tears_down_stops_and_reloads(tmp_path: Path) -> None:
    p = FakeProvider()
    p.live.add("pod1")
    ledger = _ledger(tmp_path)
    c = Campaign(_spec(), ledger, p)
    c.reserve_stage("S1", "55")
    with pytest.raises(ContractError, match="exceeded"):
        c.complete_stage("S1", actual_cost_usd="400", partial_results={}, resource_ids=("pod1",))
    assert not p.live and c.stopped and not c.has_receipt("S1")
    assert [a["percent"] for a in c._payloads("campaign.alert.v1")] == [50, 80, 100]
    again = Campaign(_spec(), ledger, FakeProvider())
    assert again.stopped


def test_zero_or_negative_reservation_refused(tmp_path: Path) -> None:
    c = Campaign(_spec(), _ledger(tmp_path), FakeProvider())
    for bad in ("0", "-5"):
        with pytest.raises(ContractError, match="positive"):
            c.reserve_stage("S1", bad)


def test_zero_cap_stage_cannot_hide_cost(tmp_path: Path) -> None:
    local = Stage("L", Decimal(0), (), 1, "cpu")
    spec = CampaignSpec("t", "v6-t-camp", Decimal(100), (50,), (local,))
    c = Campaign(spec, _ledger(tmp_path), FakeProvider())
    c.reserve_stage("L")
    with pytest.raises(ContractError, match="exceeded"):
        c.complete_stage("L", actual_cost_usd="50", partial_results={}, resource_ids=())
    assert not c.has_receipt("L")


def test_failed_teardown_is_resumable(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    c = Campaign(_spec(), ledger, _Flaky())
    c.reserve_stage("S1")
    with pytest.raises(ContractError, match="teardown"):
        c.complete_stage("S1", actual_cost_usd="5", partial_results={}, resource_ids=("pod1",))
    c.complete_stage("S1", actual_cost_usd="5", partial_results={}, resource_ids=("pod1",))
    assert c.has_receipt("S1")
    assert len(c._payloads("campaign.stage_settled.v1")) == 1
    Campaign(_spec(), ledger, FakeProvider())  # replay loads


def test_teardown_attempts_every_resource_and_survives_errors(tmp_path: Path) -> None:
    class P(FakeProvider):
        def delete(self, resource_id: str) -> None:
            self.calls += 1
            if resource_id == "boom":
                raise RuntimeError("api down")
            if resource_id != "a":
                self.live.discard(resource_id)

    p = P()
    p.live.update({"a", "b", "boom"})
    c = Campaign(_spec(), _ledger(tmp_path), p)
    assert c.teardown("S1", ["a", "boom", "b"]) is False
    assert "b" not in p.live
    last = c._payloads("campaign.teardown.v1")[-1]
    assert last["done"] is False and last["confirmed_404"] == ["b"]


def test_ledger_run_tag_must_match_spec(tmp_path: Path) -> None:
    other = EvidenceLedger(tmp_path / "o.jsonl", cohort_id="t", run_tag="v6-other")
    with pytest.raises(ContractError, match="run_tag"):
        Campaign(_spec(), other, FakeProvider())
