"""Pod cost ledger and campaign cost table (masterplan sections 42, 12.5).

The number that matters is not ``$/page``. It is the split between the seconds
that produced a page and the seconds that were billed anyway:

    operational_efficiency = useful_inference_seconds / billed_seconds

The 2026-08 campaign ran at roughly 4.8x overhead. Section 42's target is
1.1-1.3x. This module is what makes the difference measurable rather than
asserted, so every derived figure carries its denominator and a missing input
is ``None`` with a reason -- never a zero that averages away.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from arena.constants import CAMPAIGN_ID
from arena.controller.paths import CampaignPaths
from arena.controller.queue import PodRecord
from arena.core.receipts import ReceiptError, validate
from arena.provider.safety import utc_now_iso, write_jsonl_append

__all__ = [
    "CampaignCost",
    "CostError",
    "LedgerAppend",
    "PodLedgerRow",
    "append_pod_ledger",
    "build_ledger_row",
    "pod_ledger_record",
    "summarize",
]

SCHEMA: Final = "tavonel.arena.pod_cost_ledger.v1"


class CostError(RuntimeError):
    """The ledger cannot be computed from what is on record."""


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class PodLedgerRow:
    """One pod's life, masterplan section 42 fields plus contract section 3.3."""

    pod_id: str
    model_key: str
    gpu_type: str | None
    listed_rate_usd_per_hour: float | None
    # D57: listed_rate_usd_per_hour is the per-GPU rate; gpu_count is how many
    # GPUs this pod actually rented. Every derived cost figure below is
    # already multiplied by it.
    gpu_count: int
    provisioned_at: str | None
    model_ready_at: str | None
    last_job_finished_at: str | None
    terminated_at: str | None
    billed_seconds: float
    model_loading_seconds: float
    useful_inference_seconds: float
    retry_seconds: float
    idle_seconds: float
    estimated_provider_cost_usd: float | None
    useful_cost_usd: float | None
    wasted_cost_usd: float | None
    data_center_id: str | None
    price_snapshot_sha256: str | None
    runtime_mode: str | None
    # ARENA_CONTRACT section 11 D2/D6.
    provider_api_version: str | None = None
    authorization_receipt_path: str | None = None
    authorization_receipt_sha256: str | None = None
    # When the driver's own stop and delete calls were answered. These are the
    # controller's record, not the provider's: `terminated_at` is when the pod
    # row was settled, and these two say what was actually sent and when.
    stopped_at: str | None = None
    deleted_at: str | None = None
    unmeasured: tuple[str, ...] = ()
    campaign_id: str = CAMPAIGN_ID

    @property
    def wasted_gpu_seconds(self) -> float:
        """Billed seconds that produced no accepted page.

        The counterpart of ``wasted_cost_usd`` in seconds, so a run that
        rented a GPU and returned nothing -- a canary that never reached
        READY -- reports its whole billed life as wasted rather than as a
        zero that averages away.
        """

        return max(0.0, self.billed_seconds - self.useful_inference_seconds)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": SCHEMA,
            "campaign_id": self.campaign_id,
            "pod_id": self.pod_id,
            "model_key": self.model_key,
            "gpu_type": self.gpu_type,
            "listed_rate_usd_per_hour": self.listed_rate_usd_per_hour,
            "gpu_count": self.gpu_count,
            "provisioned_at": self.provisioned_at,
            "model_ready_at": self.model_ready_at,
            "last_job_finished_at": self.last_job_finished_at,
            "stopped_at": self.stopped_at,
            "deleted_at": self.deleted_at,
            "terminated_at": self.terminated_at,
            "billed_seconds": round(self.billed_seconds, 3),
            "model_loading_seconds": round(self.model_loading_seconds, 3),
            "useful_inference_seconds": round(self.useful_inference_seconds, 3),
            "retry_seconds": round(self.retry_seconds, 3),
            "idle_seconds": round(self.idle_seconds, 3),
            "wasted_gpu_seconds": round(self.wasted_gpu_seconds, 3),
            "estimated_provider_cost_usd": _round_or_none(self.estimated_provider_cost_usd),
            "useful_cost_usd": _round_or_none(self.useful_cost_usd),
            "wasted_cost_usd": _round_or_none(self.wasted_cost_usd),
            "data_center_id": self.data_center_id,
            "price_snapshot_sha256": self.price_snapshot_sha256,
            "runtime_mode": self.runtime_mode,
            "provider_api_version": self.provider_api_version,
            "authorization_receipt_path": self.authorization_receipt_path,
            "authorization_receipt_sha256": self.authorization_receipt_sha256,
            "unmeasured": list(self.unmeasured),
        }


def build_ledger_row(
    pod: PodRecord,
    *,
    useful_inference_seconds: float,
    retry_seconds: float = 0.0,
    stopped_at: str | None = None,
    deleted_at: str | None = None,
    now: datetime | None = None,
) -> PodLedgerRow:
    """Split a pod's billed time into loading / useful / retry / idle.

    Anything that cannot be measured from the recorded timestamps is named in
    ``unmeasured`` and left as ``None``. A pod with no provisioned_at has no
    billed seconds we can defend, so it reports zero seconds and an explicit
    gap rather than a guess.
    """

    provisioned = _parse(pod.provisioned_at)
    ready = _parse(pod.model_ready_at)
    terminated = _parse(pod.terminated_at) or now or datetime.now(tz=UTC)
    gaps: list[str] = []

    if provisioned is None:
        gaps.append("provisioned_at is absent; billed seconds cannot be derived")
        billed = 0.0
        loading = 0.0
    else:
        billed = max(0.0, (terminated - provisioned).total_seconds())
        if ready is None:
            gaps.append("model_ready_at is absent; model_loading_seconds cannot be split out")
            loading = 0.0
        else:
            loading = max(0.0, (ready - provisioned).total_seconds())
    if pod.terminated_at is None:
        gaps.append("terminated_at is absent; billed seconds are measured to now, not to teardown")

    useful = max(0.0, useful_inference_seconds)
    retry = max(0.0, retry_seconds)
    idle = max(0.0, billed - loading - useful - retry)
    if useful + retry + loading > billed and billed > 0:
        gaps.append(
            "reported work seconds exceed billed seconds; idle is floored at 0 and the "
            "split is not trustworthy"
        )

    rate = pod.listed_rate_usd_per_hour
    gpu_count = max(1, pod.gpu_count)
    if rate is None:
        gaps.append("no price snapshot row on this pod; cost cannot be estimated")
        estimated: float | None = None
        useful_cost: float | None = None
        wasted_cost: float | None = None
    else:
        # rate is per GPU (D57); a pod with more than one GPU bills for all of
        # them for every second it is up, not just one.
        estimated = billed / 3600.0 * rate * gpu_count
        useful_cost = useful / 3600.0 * rate * gpu_count
        wasted_cost = max(0.0, estimated - useful_cost)

    return PodLedgerRow(
        pod_id=pod.pod_id,
        model_key=pod.model_key,
        gpu_type=pod.gpu_type,
        listed_rate_usd_per_hour=rate,
        gpu_count=gpu_count,
        provisioned_at=pod.provisioned_at,
        model_ready_at=pod.model_ready_at,
        last_job_finished_at=pod.last_job_finished_at,
        terminated_at=pod.terminated_at,
        billed_seconds=billed,
        model_loading_seconds=loading,
        useful_inference_seconds=useful,
        retry_seconds=retry,
        idle_seconds=idle,
        estimated_provider_cost_usd=estimated,
        useful_cost_usd=useful_cost,
        wasted_cost_usd=wasted_cost,
        data_center_id=pod.data_center_id,
        price_snapshot_sha256=pod.price_snapshot_sha256,
        runtime_mode=pod.runtime_mode,
        provider_api_version=pod.provider_api_version,
        authorization_receipt_path=pod.authorization_receipt_path,
        authorization_receipt_sha256=pod.authorization_receipt_sha256,
        stopped_at=stopped_at,
        deleted_at=deleted_at,
        unmeasured=tuple(gaps),
    )


@dataclass(frozen=True, slots=True)
class CampaignCost:
    """Masterplan section 12.5's final figures, each with its denominator."""

    model_key: str | None
    pod_count: int
    billed_seconds: float
    useful_inference_seconds: float
    model_loading_seconds: float
    retry_seconds: float
    idle_seconds: float
    total_cost_usd: float | None
    successful_pages: int
    attempted_pages: int
    cost_per_1000_pages_usd: float | None
    cost_per_successful_page_usd: float | None
    gpu_seconds_per_page: float | None
    operational_efficiency: float | None
    idle_overhead_ratio: float | None
    retry_overhead_ratio: float | None
    startup_overhead_ratio: float | None
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": "tavonel.arena.campaign_cost.v1",
            "campaign_id": CAMPAIGN_ID,
            "model_key": self.model_key,
            "pod_count": self.pod_count,
            "billed_seconds": round(self.billed_seconds, 3),
            "useful_inference_seconds": round(self.useful_inference_seconds, 3),
            "model_loading_seconds": round(self.model_loading_seconds, 3),
            "retry_seconds": round(self.retry_seconds, 3),
            "idle_seconds": round(self.idle_seconds, 3),
            "total_cost_usd": _round_or_none(self.total_cost_usd),
            "successful_pages": self.successful_pages,
            "attempted_pages": self.attempted_pages,
            "cost_per_1000_pages_usd": _round_or_none(self.cost_per_1000_pages_usd),
            "cost_per_successful_page_usd": _round_or_none(self.cost_per_successful_page_usd, 6),
            "gpu_seconds_per_page": _round_or_none(self.gpu_seconds_per_page),
            "operational_efficiency": _round_or_none(self.operational_efficiency, 4),
            "idle_overhead_ratio": _round_or_none(self.idle_overhead_ratio, 4),
            "retry_overhead_ratio": _round_or_none(self.retry_overhead_ratio, 4),
            "startup_overhead_ratio": _round_or_none(self.startup_overhead_ratio, 4),
            "notes": list(self.notes),
        }

    def table_lines(self) -> list[str]:
        label = self.model_key or "campaign"
        return [
            f"{label}: {self.pod_count} pod(s), "
            f"{self.successful_pages}/{self.attempted_pages} pages succeeded",
            f"  billed {self.billed_seconds / 3600:.2f} GPU-h "
            f"(useful {self.useful_inference_seconds / 3600:.2f}, "
            f"load {self.model_loading_seconds / 3600:.2f}, "
            f"retry {self.retry_seconds / 3600:.2f}, "
            f"idle {self.idle_seconds / 3600:.2f})",
            f"  $/1,000 pages      {_fmt(self.cost_per_1000_pages_usd, '$', 2)}",
            f"  $/successful page  {_fmt(self.cost_per_successful_page_usd, '$', 5)}",
            f"  GPU seconds/page   {_fmt(self.gpu_seconds_per_page, '', 3)}",
            f"  operational eff.   {_fmt(self.operational_efficiency, '', 4)}"
            "  (useful / billed)",
            f"  idle overhead      {_fmt(self.idle_overhead_ratio, '', 4)}",
            f"  retry overhead     {_fmt(self.retry_overhead_ratio, '', 4)}",
            f"  startup overhead   {_fmt(self.startup_overhead_ratio, '', 4)}",
        ]


def summarize(
    rows: Iterable[PodLedgerRow],
    *,
    successful_pages: int,
    attempted_pages: int,
    model_key: str | None = None,
) -> CampaignCost:
    """Roll up ledger rows. Ratios are ``None`` when the denominator is zero."""

    materialized: Sequence[PodLedgerRow] = tuple(rows)
    billed = sum(row.billed_seconds for row in materialized)
    useful = sum(row.useful_inference_seconds for row in materialized)
    loading = sum(row.model_loading_seconds for row in materialized)
    retry = sum(row.retry_seconds for row in materialized)
    idle = sum(row.idle_seconds for row in materialized)

    priced = [row for row in materialized if row.estimated_provider_cost_usd is not None]
    notes: list[str] = []
    total_cost: float | None
    if not materialized:
        total_cost = None
        notes.append("no pod ledger rows; nothing has been provisioned yet")
    elif len(priced) != len(materialized):
        total_cost = None
        notes.append(
            f"{len(materialized) - len(priced)} of {len(materialized)} pods carry no price "
            "snapshot row; the campaign cost is not computable from record"
        )
    else:
        total_cost = sum(row.estimated_provider_cost_usd or 0.0 for row in priced)

    # D57: a pod with no terminated_at is still live and build_ledger_row
    # measures its billed seconds to *now*, not to teardown -- that number
    # keeps growing every time this is called and is not the same kind of
    # figure as a settled pod's. Rolling both into one total without saying
    # so is what made `cost` (21 pods, 11.34 GPU-h) look inconsistent with
    # the closed rows in cost/pod_ledger.jsonl (16 rows, 2.59 GPU-h): the
    # difference was live/in-flight pods, not lost or duplicated evidence.
    open_rows = [row for row in materialized if row.terminated_at is None]
    if open_rows:
        closed_rows = [row for row in materialized if row.terminated_at is not None]
        open_billed = sum(row.billed_seconds for row in open_rows)
        closed_billed = sum(row.billed_seconds for row in closed_rows)
        notes.append(
            f"{len(open_rows)} of {len(materialized)} pod(s) have no terminated_at and are "
            f"still billing; their {open_billed / 3600:.2f} GPU-h is measured to now, not to "
            "teardown, and will keep growing until they close. "
            f"{len(closed_rows)} pod(s) are settled, totaling {closed_billed / 3600:.2f} "
            "GPU-h -- that is what cost/pod_ledger.jsonl carries."
        )

    if successful_pages < 0 or attempted_pages < 0:
        raise CostError("page counts cannot be negative")

    return CampaignCost(
        model_key=model_key,
        pod_count=len(materialized),
        billed_seconds=billed,
        useful_inference_seconds=useful,
        model_loading_seconds=loading,
        retry_seconds=retry,
        idle_seconds=idle,
        total_cost_usd=total_cost,
        successful_pages=successful_pages,
        attempted_pages=attempted_pages,
        cost_per_1000_pages_usd=(
            None
            if total_cost is None or successful_pages == 0
            else total_cost / successful_pages * 1000.0
        ),
        cost_per_successful_page_usd=(
            None if total_cost is None or successful_pages == 0 else total_cost / successful_pages
        ),
        gpu_seconds_per_page=(None if successful_pages == 0 else billed / successful_pages),
        operational_efficiency=(None if billed <= 0 else useful / billed),
        idle_overhead_ratio=(None if billed <= 0 else idle / billed),
        retry_overhead_ratio=(None if billed <= 0 else retry / billed),
        startup_overhead_ratio=(None if billed <= 0 else loading / billed),
        notes=tuple(notes),
    )


@dataclass(frozen=True, slots=True)
class LedgerAppend:
    """Where a pod's billed row landed, and why (D28)."""

    path: Path
    validated: bool
    problem: str | None = None


def pod_ledger_record(
    row: PodLedgerRow, *, campaign_id: str = CAMPAIGN_ID
) -> dict[str, object]:
    """The ARENA_CONTRACT section 3.3 record for one pod's billed life.

    ``PodLedgerRow.to_dict`` is the controller's richer internal view;
    ``pod-ledger.schema.json`` is closed (``additionalProperties: false``) and
    carries only the section 3.3 fields. This is the projection onto that
    schema -- nothing is invented to fill it, so a pod with no price row
    produces a record that will not validate, and that failure is reported
    rather than papered over with a zero.

    Four fields deliberately do **not** appear here: ``provider_api_version``,
    ``stopped_at``, ``deleted_at`` and ``wasted_gpu_seconds``. Section 3.3 is
    "exactly MP section 42 plus ``model_key``, ``campaign_id``,
    ``data_center_id``, ``price_snapshot_sha256``, ``runtime_mode``", the
    schema enumerates exactly that and belongs to lane A1. They are kept in
    ``PodLedgerRow.to_dict`` (written to ``cost/pod-<pod_id>.json``) and in the
    canary driver receipt instead of being smuggled past a closed contract.
    """

    record: dict[str, object] = {
        "schema": "tavonel.arena.pod-ledger.v1",
        "campaign_id": campaign_id,
        "model_key": row.model_key,
        "runtime_mode": row.runtime_mode,
        "pod_id": row.pod_id,
        "gpu_type": row.gpu_type,
        "data_center_id": row.data_center_id,
        "listed_rate_usd_per_hour": row.listed_rate_usd_per_hour,
        "gpu_count": row.gpu_count,
        "price_snapshot_sha256": row.price_snapshot_sha256,
        "provisioned_at": row.provisioned_at,
        "model_ready_at": row.model_ready_at,
        "last_job_finished_at": row.last_job_finished_at,
        "terminated_at": row.terminated_at,
        "billed_seconds": round(row.billed_seconds, 3),
        "model_loading_seconds": round(row.model_loading_seconds, 3),
        "useful_inference_seconds": round(row.useful_inference_seconds, 3),
        "retry_seconds": round(row.retry_seconds, 3),
        "idle_seconds": round(row.idle_seconds, 3),
        "estimated_provider_cost_usd": _round_or_none(row.estimated_provider_cost_usd),
        "useful_cost_usd": _round_or_none(row.useful_cost_usd),
        "wasted_cost_usd": _round_or_none(row.wasted_cost_usd),
    }
    return record


def append_pod_ledger(paths: CampaignPaths, row: PodLedgerRow) -> LedgerAppend:
    """Append one section 3.3 row to ``cost/pod_ledger.jsonl`` (D28).

    A record that does not satisfy the schema is **not** dropped and **not**
    coerced. It goes to ``cost/pod_ledger_rejected.jsonl`` with the validation
    message attached, and the caller is told. Losing a cost record because a
    field was unmeasurable would hide money; writing a zero in its place would
    invent it. Neither is acceptable, so the record is kept where a human can
    see it and the campaign cost table stays honest about the gap.
    """

    record = pod_ledger_record(row)
    try:
        validate(record, "pod-ledger")
    except ReceiptError as exc:
        rejected = {**record, "validation_error": str(exc), "rejected_at": utc_now_iso()}
        write_jsonl_append(
            paths.cost_dir / "pod_ledger_rejected.jsonl",
            rejected,
            context="rejected pod ledger row",
        )
        return LedgerAppend(
            path=paths.cost_dir / "pod_ledger_rejected.jsonl",
            validated=False,
            problem=str(exc),
        )
    write_jsonl_append(paths.pod_ledger, record, context="pod ledger row")
    return LedgerAppend(path=paths.pod_ledger, validated=True)


def useful_seconds_by_pod(receipts: Iterable[Mapping[str, object]]) -> dict[str, float]:
    """Sum ``total_ms`` per pod from page receipts, SUCCESS rows only."""

    totals: dict[str, float] = {}
    for receipt in receipts:
        pod_id = receipt.get("pod_id")
        total_ms = receipt.get("total_ms")
        if not isinstance(pod_id, str) or not isinstance(total_ms, (int, float)):
            continue
        if receipt.get("status") != "SUCCESS":
            continue
        totals[pod_id] = totals.get(pod_id, 0.0) + float(total_ms) / 1000.0
    return totals


def retry_seconds_by_pod(receipts: Iterable[Mapping[str, object]]) -> dict[str, float]:
    """Seconds burned by receipts that did not produce an accepted page."""

    totals: dict[str, float] = {}
    for receipt in receipts:
        pod_id = receipt.get("pod_id")
        total_ms = receipt.get("total_ms")
        if not isinstance(pod_id, str) or not isinstance(total_ms, (int, float)):
            continue
        if receipt.get("status") == "SUCCESS":
            continue
        totals[pod_id] = totals.get(pod_id, 0.0) + float(total_ms) / 1000.0
    return totals


def _round_or_none(value: float | None, digits: int = 4) -> float | None:
    return None if value is None else round(value, digits)


def _fmt(value: float | None, prefix: str, digits: int) -> str:
    if value is None:
        return "unmeasured"
    return f"{prefix}{value:.{digits}f}"
