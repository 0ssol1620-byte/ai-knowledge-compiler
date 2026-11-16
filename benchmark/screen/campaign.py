"""Screening campaign runner: spend caps, predecessor receipts, teardown proof.

Pure orchestration over one AuthorizedSpendBudget and the v6 hash-chain ledger.
It never talks to a provider itself: a ``CampaignProvider`` is injected, and
dry-run mode needs none.  A stage is reserved at its cap before any provider
write, and a stage receipt (the next stage's precondition) exists only after
partial results are persisted AND every tagged resource is deleted, confirmed
by a provider GET 404, with an empty orphan audit.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Protocol

import yaml

from benchmark.v6.contracts import ContractError
from benchmark.v6.ledger import EvidenceLedger
from infra.runpod.v6.authorized_budget import AuthorizedSpendBudget
from infra.runpod.v6.client import OrphanAuditReceipt, ProviderAbsenceReceipt

SPEC_PATH = Path(__file__).with_name("campaign-screen-v1.yaml")


class CampaignProvider(Protocol):
    def delete(self, resource_id: str) -> None: ...

    def exists(self, resource_id: str) -> bool:
        """False means the provider GET answered 404."""
        ...

    def tagged_resource_ids(self, run_tag: str) -> Sequence[str]: ...


@dataclass(frozen=True, slots=True)
class Stage:
    id: str
    cap_usd: Decimal
    requires: tuple[str, ...]
    page_runs: int
    gpu: str


@dataclass(frozen=True, slots=True)
class CampaignSpec:
    campaign_id: str
    run_tag: str
    hard_cap_usd: Decimal
    alert_percents: tuple[int, ...]
    stages: tuple[Stage, ...]

    def stage(self, stage_id: str) -> Stage:
        for item in self.stages:
            if item.id == stage_id:
                return item
        raise ContractError(f"unknown campaign stage {stage_id!r}")


def load_spec(path: Path = SPEC_PATH) -> CampaignSpec:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw.get("provider_retry_count") != 0:
        raise ContractError("provider-side retries are not allowed (provider_retry_count: 0)")
    stages = tuple(
        Stage(
            id=str(s["id"]),
            cap_usd=Decimal(str(s["cap_usd"])),
            requires=tuple(s["requires"]),
            page_runs=int(s["page_runs"]),
            gpu=str(s["gpu"]),
        )
        for s in raw["stages"]
    )
    ids = {s.id for s in stages}
    if len(ids) != len(stages):
        raise ContractError("duplicate stage id")
    for s in stages:
        if not set(s.requires) <= ids:
            raise ContractError(f"stage {s.id} requires an unknown stage")
    hard_cap = Decimal(str(raw["hard_cap_usd"]))
    if sum((s.cap_usd for s in stages), Decimal(0)) > hard_cap:
        raise ContractError("stage caps exceed the campaign hard cap")
    return CampaignSpec(
        campaign_id=raw["campaign_id"],
        run_tag=raw["run_tag"],
        hard_cap_usd=hard_cap,
        alert_percents=tuple(int(p) for p in raw["alert_percents"]),
        stages=stages,
    )


def reservation_plan(spec: CampaignSpec) -> list[dict[str, object]]:
    """The dry-run plan: pure data, no ledger, no provider, no network."""
    running = Decimal(0)
    plan: list[dict[str, object]] = []
    for s in spec.stages:
        running += s.cap_usd
        plan.append(
            {
                "stage": s.id,
                "requires": list(s.requires),
                "reserve_usd": str(s.cap_usd),
                "cumulative_reserved_usd": str(running),
                "remaining_usd": str(spec.hard_cap_usd - running),
                "gpu": s.gpu,
                "page_runs": s.page_runs,
            }
        )
    return plan


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class Campaign:
    def __init__(
        self,
        spec: CampaignSpec,
        ledger: EvidenceLedger,
        provider: CampaignProvider | None = None,
    ) -> None:
        if ledger.run_tag != spec.run_tag:
            raise ContractError("ledger run_tag does not match the campaign spec")
        self.spec = spec
        self.ledger = ledger
        self.provider = provider
        self.budget = AuthorizedSpendBudget(
            campaign_id=spec.campaign_id, hard_cap_usd=spec.hard_cap_usd
        )
        # Rebuild spend state from the ledger so a restarted runner cannot double-reserve.
        reserved: dict[str, Decimal] = {}
        for event in ledger.replay():
            payload = event.payload
            stage_id = str(payload.get("stage"))
            if event.event_type == "campaign.stage_reserved.v1":
                amount = Decimal(str(payload["reserved_usd"]))
                reserved[stage_id] = amount
                if amount > 0:
                    self.budget.reserve(allocation_id=stage_id, maximum_cost_usd=amount)
            elif event.event_type == "campaign.stage_settled.v1":
                actual = Decimal(str(payload["actual_cost_usd"]))
                if reserved.get(stage_id, Decimal(0)) > 0:
                    try:
                        self.budget.settle(allocation_id=stage_id, actual_cost_usd=actual)
                    except ContractError:
                        # An overspend is recorded by settle before it raises; the
                        # ledger stays loadable and the runner stays stopped/blocked.
                        if actual <= reserved[stage_id]:
                            raise

    def _payloads(self, event_type: str) -> list[Mapping[str, object]]:
        return [e.payload for e in self.ledger.iter_type(event_type)]

    @property
    def stopped(self) -> bool:
        return bool(self._payloads("campaign.stopped.v1"))

    def has_receipt(self, stage_id: str) -> bool:
        return any(p["stage"] == stage_id for p in self._payloads("campaign.stage_receipt.v1"))

    def reserve_stage(
        self, stage_id: str, maximum_cost_usd: Decimal | str | None = None
    ) -> None:
        """Reserve worst-case cost. Call before any provider write for the stage."""
        if self.stopped:
            raise ContractError("campaign is stopped; no new reservations")
        stage = self.spec.stage(stage_id)
        for needed in stage.requires:
            if not self.has_receipt(needed):
                raise ContractError(f"stage {stage_id} requires the {needed} stage receipt")
        if any(p["stage"] == stage_id for p in self._payloads("campaign.stage_reserved.v1")):
            raise ContractError(f"stage {stage_id} is already reserved")
        amount = stage.cap_usd if maximum_cost_usd is None else Decimal(str(maximum_cost_usd))
        if amount > stage.cap_usd:
            raise ContractError(f"reservation exceeds the {stage_id} stage cap")
        if amount < 0 or (amount == 0 and stage.cap_usd != 0):
            raise ContractError(f"reservation for {stage_id} must be positive")
        if amount > 0:
            self.budget.reserve(allocation_id=stage_id, maximum_cost_usd=amount)
        self.ledger.append(
            "campaign.stage_reserved.v1", {"stage": stage_id, "reserved_usd": str(amount)}
        )

    def complete_stage(
        self,
        stage_id: str,
        *,
        actual_cost_usd: Decimal | str,
        partial_results: Mapping[str, object],
        resource_ids: Sequence[str],
    ) -> None:
        """Persist partial results, settle spend, tear down, then write the receipt."""
        reserved = [
            p for p in self._payloads("campaign.stage_reserved.v1") if p["stage"] == stage_id
        ]
        if not reserved:
            raise ContractError(f"stage {stage_id} was never reserved")
        actual = Decimal(str(actual_cost_usd))
        if actual < 0:
            raise ContractError("actual_cost_usd cannot be negative")
        reserved_usd = Decimal(str(reserved[0]["reserved_usd"]))
        settled = [p for p in self._payloads("campaign.stage_settled.v1") if p["stage"] == stage_id]
        if settled:
            # Resumed after a failed teardown: spend is already recorded, redo teardown only.
            actual = Decimal(str(settled[0]["actual_cost_usd"]))
        else:
            self.ledger.append(
                "campaign.partial.v1", {"stage": stage_id, "results": dict(partial_results)}
            )
            if reserved_usd > 0:
                try:
                    self.budget.settle(allocation_id=stage_id, actual_cost_usd=actual)
                except ContractError:
                    if actual <= reserved_usd:
                        raise
            self.ledger.append(
                "campaign.stage_settled.v1",
                {"stage": stage_id, "actual_cost_usd": str(actual)},
            )
        overspent = actual > reserved_usd
        self._alerts()
        ids = list(resource_ids)
        if self.stopped and self.provider is not None:
            # At the hard cap, sweep every tagged resource, not only this stage's.
            ids += [r for r in self.provider.tagged_resource_ids(self.spec.run_tag) if r not in ids]
        proven = self.teardown(stage_id, ids)
        if overspent:
            raise ContractError(f"{stage_id} cost {actual} exceeded its reservation {reserved_usd}")
        if not proven:
            raise ContractError(f"teardown of {stage_id} is not proven; no stage receipt")
        self.ledger.append("campaign.stage_receipt.v1", {"stage": stage_id})

    def _alerts(self) -> None:
        settled = self.budget.settled_usd
        fired = {p["percent"] for p in self._payloads("campaign.alert.v1")}
        for percent in self.spec.alert_percents:
            if percent in fired or settled * 100 < self.spec.hard_cap_usd * percent:
                continue
            self.ledger.append(
                "campaign.alert.v1", {"percent": percent, "settled_usd": str(settled)}
            )
            if percent >= 100:
                self.ledger.append("campaign.stopped.v1", {"reason": "hard_cap_reached"})

    def teardown(self, stage_id: str, resource_ids: Sequence[str]) -> bool:
        """Delete, confirm GET 404, then audit tagged orphans. True only if all hold."""
        if self.provider is None:
            raise ContractError("teardown needs a provider")
        confirmations: list[ProviderAbsenceReceipt] = []
        for rid in resource_ids:
            try:
                self.provider.delete(rid)
                gone = not self.provider.exists(rid)
            except Exception:
                gone = False  # any provider error means "not confirmed"
            if not gone:
                continue
            confirmations.append(ProviderAbsenceReceipt(rid, "GET_404_NOT_FOUND", _now()))
        tagged = tuple(sorted(self.provider.tagged_resource_ids(self.spec.run_tag)))
        audit = OrphanAuditReceipt(
            run_tag=self.spec.run_tag,
            active_endpoint_ids=(),
            tagged_endpoint_ids=tagged,
            orphan_endpoint_ids=tagged,
            missing_active_endpoint_ids=(),
            delete_confirmations=tuple(confirmations),
            observed_at=_now(),
        )
        done = len(confirmations) == len(resource_ids) and audit.passed
        self.ledger.append(
            "campaign.teardown.v1",
            {
                "stage": stage_id,
                "done": done,
                "orphan_ids": list(tagged),
                "confirmed_404": [c.endpoint_id for c in confirmations],
            },
        )
        return done


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args != ["--dry-run"]:
        print("usage: campaign.py --dry-run", file=sys.stderr)
        return 2
    print(json.dumps(reservation_plan(load_spec()), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
