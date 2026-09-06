"""The gate that lets a money-spending command run (D6, D7, D10).

Until the integration pass, ``--execute`` answered every paid command with
"not authorized in this build phase". That was a build-phase stub, not a
policy. The policy is D6: a founder receipt under ``receipts/authorizations/``
whose phase, model scope, expiry and ``max_usd`` all cover the action.

Two properties are load bearing:

- **The cost estimate is conservative.** ``required_usd`` uses the *most
  expensive* priced GPU in the model's priority list, the full pod lifetime
  cap for the phase (2 h canary, 6 h full run -- D10), the model's
  ``gpu_count_min`` and the container disk. An estimate that came in under the
  real bill would be an authorization for a number nobody approved.
- **It fails closed and says why.** No receipt, an expired one, or one whose
  ceiling is below the estimate all end in ``EXIT_BLOCKED`` with the receipts
  that *were* found, their phases and ceilings, and the required amount --
  enough for the founder to write the missing receipt without guessing.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from arena.constants import BUDGET_HARD_CAP_USD, BUDGET_SOFT_CAP_USD, CAMPAIGN_ID
from arena.controller.gpu_pools import MAX_PRICE_SNAPSHOT_AGE_HOURS, snapshot_age_hours
from arena.controller.paths import CampaignPaths
from arena.controller.provision import DEFAULT_CONTAINER_DISK_GB
from arena.core.authorizations import (
    AuthorizationError,
    AuthorizationReceipt,
    format_timestamp,
    load_authorizations,
    select_authorization,
)
from arena.provider.runpod_pods import PriceSnapshot, RunPodClientError
from arena.provider.safety import iter_jsonl, read_json, sha256_file

__all__ = [
    "CANARY_MAX_POD_LIFETIME_HOURS",
    "CONTAINER_DISK_USD_PER_GB_MONTH",
    "FULL_RUN_MAX_POD_LIFETIME_HOURS",
    "VOLUME_USD_PER_GB_MONTH",
    "AuthorizationDecision",
    "CostEstimate",
    "CumulativeBudget",
    "GateError",
    "LicenseDecision",
    "authorize",
    "cumulative_budget",
    "effective_pod_lifetime_hours",
    "estimate_pod_cost",
    "license_gate",
    "max_pod_lifetime_hours",
]

# ARENA_CONTRACT section 11 D10.
CANARY_MAX_POD_LIFETIME_HOURS: Final = 2
FULL_RUN_MAX_POD_LIFETIME_HOURS: Final = 6

# RunPod's published container-disk list rate for a running pod. It is a list
# price, not a catalog-snapshot row, and the estimate says so; it is included
# because leaving it out would make the estimate cheaper than the bill.
CONTAINER_DISK_USD_PER_GB_MONTH: Final = 0.10
# ARENA_CONTRACT 11.5 D24: a persistent volume is billed too. The same
# published running-pod storage list rate is used, on the same footing and
# with the same caveat -- it is a list price, not a catalog row.
VOLUME_USD_PER_GB_MONTH: Final = 0.10
_HOURS_PER_MONTH: Final = 720.0

PHASE_FOR_LIFETIME: Final = {
    "phase1_canary": CANARY_MAX_POD_LIFETIME_HOURS,
    "phase2_full_run": FULL_RUN_MAX_POD_LIFETIME_HOURS,
    "phase3_opus_full_run": FULL_RUN_MAX_POD_LIFETIME_HOURS,
    "builder_pod": FULL_RUN_MAX_POD_LIFETIME_HOURS,
}


class GateError(RuntimeError):
    """The gate cannot be evaluated from what is on disk."""


def max_pod_lifetime_hours(phase: str) -> int:
    """D10: 2 h for a canary pod, 6 h for a full-run pod."""

    try:
        return PHASE_FOR_LIFETIME[phase]
    except KeyError:
        raise GateError(f"unknown phase {phase!r}") from None


def effective_pod_lifetime_hours(phase: str, requested: float | None = None) -> int:
    """What this pod is really allowed, in whole hours (D10, D84).

    The D10 ceiling is the most a pod of this phase may ever live. A run may
    ask for less, and when it does the pod is created with that shorter
    watchdog, so reserving the ceiling would price six hours for a pod the
    driver deletes at three. Asking for more than the ceiling gets the
    ceiling: this narrows a lifetime and never widens one.

    A fractional request rounds up, because the reservation must not be
    cheaper than the watchdog it stands for.
    """

    ceiling = max_pod_lifetime_hours(phase)
    if requested is None:
        return ceiling
    try:
        asked = float(requested)
    except (TypeError, ValueError):
        raise GateError(f"a pod lifetime of {requested!r} is not a number") from None
    if asked <= 0:
        raise GateError("a pod lifetime of zero hours cannot be authorized")
    return min(ceiling, max(1, math.ceil(asked)))


@dataclass(frozen=True, slots=True)
class CostEstimate:
    """What one pod could cost over its whole permitted lifetime."""

    model_key: str
    gpu_type_id: str
    cloud: str
    hourly_rate_usd: float
    gpu_count: int
    hours: float
    gpu_usd: float
    container_disk_gb: int
    container_disk_usd: float
    replicas: int
    required_usd: float
    price_snapshot_sha256: str
    price_row_sha256: str
    notes: tuple[str, ...] = ()
    volume_gb: int = 0
    volume_usd: float = 0.0
    price_snapshot_age_hours: float | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "model_key": self.model_key,
            "gpu_type_id": self.gpu_type_id,
            "cloud": self.cloud,
            "hourly_rate_usd": self.hourly_rate_usd,
            "gpu_count": self.gpu_count,
            "replicas": self.replicas,
            "max_pod_lifetime_hours": self.hours,
            "gpu_usd": round(self.gpu_usd, 4),
            "container_disk_gb": self.container_disk_gb,
            "container_disk_usd": round(self.container_disk_usd, 4),
            "volume_gb": self.volume_gb,
            "volume_usd": round(self.volume_usd, 4),
            "required_usd": round(self.required_usd, 4),
            "price_snapshot_sha256": self.price_snapshot_sha256,
            "price_snapshot_age_hours": (
                None
                if self.price_snapshot_age_hours is None
                else round(self.price_snapshot_age_hours, 3)
            ),
            "price_row_sha256": self.price_row_sha256,
            "basis": (
                "most expensive priced GPU in gpu_pool_priority, full lifetime cap, "
                "container disk and any persistent volume included (D24)"
            ),
            "notes": list(self.notes),
        }


def estimate_pod_cost(
    *,
    model_key: str,
    snapshot: PriceSnapshot,
    gpu_pool_priority: Sequence[str],
    cloud: str = "SECURE",
    gpu_count: int = 1,
    hours: float,
    container_disk_gb: int = 80,
    volume_gb: int = 0,
    replicas: int = 1,
    now: datetime | None = None,
) -> CostEstimate:
    """The conservative ceiling for ``replicas`` pods of this shape.

    The *dearest* priced GPU in the priority list wins, because the scheduler
    may rent any of them and an authorization has to cover the worst case. A
    pool whose every entry is unpriced on this tier raises: an unpriced GPU is
    a missing price, never a free one.
    """

    if hours <= 0:
        raise GateError("a pod lifetime of zero hours cannot be authorized")
    if gpu_count < 1 or replicas < 1:
        raise GateError("gpu_count and replicas must be positive")
    if container_disk_gb < 1:
        raise GateError("container disk must be positive")
    if volume_gb < 0:
        raise GateError("volume_gb must not be negative")

    priced: list[tuple[float, str]] = []
    missing: list[str] = []
    for gpu_type_id in gpu_pool_priority:
        try:
            row = snapshot.row(gpu_type_id)
        except RunPodClientError:
            missing.append(gpu_type_id)
            continue
        rate = row.rate_for(cloud)
        if rate is None:
            missing.append(gpu_type_id)
            continue
        priced.append((rate, gpu_type_id))
    if not priced:
        raise GateError(
            f"no GPU in {list(gpu_pool_priority)} carries a {cloud} price in catalog snapshot "
            f"{snapshot.snapshot_sha256()}; the canary cost cannot be projected"
        )
    rate, gpu_type_id = max(priced)
    gpu_usd = rate * gpu_count * hours * replicas
    disk_usd = (
        CONTAINER_DISK_USD_PER_GB_MONTH / _HOURS_PER_MONTH * container_disk_gb * hours * replicas
    )
    volume_usd = VOLUME_USD_PER_GB_MONTH / _HOURS_PER_MONTH * volume_gb * hours * replicas
    notes: list[str] = [
        "container disk uses the published $0.10/GB/month list rate, not a catalog row"
    ]
    if container_disk_gb != DEFAULT_CONTAINER_DISK_GB:
        notes.append(
            f"container disk is {container_disk_gb} GB, not the {DEFAULT_CONTAINER_DISK_GB} GB "
            "default; the difference is priced into required_usd (D24)"
        )
    if volume_gb:
        notes.append(
            f"a {volume_gb} GB persistent volume at $0.10/GB/month list rate is priced in (D24)"
        )
    if missing:
        notes.append(
            f"{len(missing)} pool entr{'y' if len(missing) == 1 else 'ies'} carry no {cloud} "
            f"price and were skipped: {', '.join(missing)}"
        )
    age = snapshot_age_hours(snapshot, now=now or datetime.now(tz=UTC))
    if age is not None and age > MAX_PRICE_SNAPSHOT_AGE_HOURS:
        notes.append(
            f"the catalog snapshot is {age:.1f} h old, past the "
            f"{MAX_PRICE_SNAPSHOT_AGE_HOURS:.0f} h freshness limit (D23)"
        )
    return CostEstimate(
        model_key=model_key,
        gpu_type_id=gpu_type_id,
        cloud=cloud,
        hourly_rate_usd=rate,
        gpu_count=gpu_count,
        hours=hours,
        gpu_usd=gpu_usd,
        container_disk_gb=container_disk_gb,
        container_disk_usd=disk_usd,
        volume_gb=volume_gb,
        volume_usd=volume_usd,
        replicas=replicas,
        required_usd=gpu_usd + disk_usd + volume_usd,
        price_snapshot_sha256=snapshot.snapshot_sha256(),
        price_row_sha256=snapshot.row(gpu_type_id).row_sha256(),
        price_snapshot_age_hours=age,
        notes=tuple(notes),
    )


@dataclass(frozen=True, slots=True)
class CumulativeBudget:
    """D22: what this campaign has already committed, plus this action.

    One receipt covering $25 must not authorize eleven $25 pods. The gate
    therefore adds up what earlier *live* provisioning lines already committed
    (their ``required_usd`` ceilings) and what the pod ledger says was actually
    billed, and refuses when this action would push the total past the soft
    cap. Dry-run provisioning lines are excluded on purpose: a dry run
    committed nothing and counting it would block the campaign on rehearsals.
    """

    committed_usd: float
    spent_usd: float
    required_usd: float
    soft_cap_usd: float
    hard_cap_usd: float
    provisioning_lines: int
    ledger_lines: int

    @property
    def projected_usd(self) -> float:
        return self.committed_usd + self.spent_usd + self.required_usd

    @property
    def over_hard_cap(self) -> bool:
        return self.projected_usd > self.hard_cap_usd

    @property
    def over_soft_cap(self) -> bool:
        return self.projected_usd > self.soft_cap_usd

    @property
    def allowed(self) -> bool:
        return not self.over_soft_cap

    def reason(self) -> str:
        if self.over_hard_cap:
            return (
                f"cumulative ${self.projected_usd:,.2f} (committed ${self.committed_usd:,.2f} + "
                f"billed ${self.spent_usd:,.2f} + this action ${self.required_usd:,.2f}) crosses "
                f"the ${self.hard_cap_usd:,.2f} HARD cap; nothing crosses it (D22)"
            )
        if self.over_soft_cap:
            return (
                f"cumulative ${self.projected_usd:,.2f} (committed ${self.committed_usd:,.2f} + "
                f"billed ${self.spent_usd:,.2f} + this action ${self.required_usd:,.2f}) crosses "
                f"the ${self.soft_cap_usd:,.2f} soft cap (D22)"
            )
        return (
            f"cumulative ${self.projected_usd:,.2f} stays under the ${self.soft_cap_usd:,.2f} "
            f"soft cap ({self.provisioning_lines} earlier provisioning line(s), "
            f"{self.ledger_lines} ledger row(s))"
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "committed_usd": round(self.committed_usd, 4),
            "spent_usd": round(self.spent_usd, 4),
            "required_usd": round(self.required_usd, 4),
            "projected_usd": round(self.projected_usd, 4),
            "soft_cap_usd": self.soft_cap_usd,
            "hard_cap_usd": self.hard_cap_usd,
            "provisioning_lines_counted": self.provisioning_lines,
            "pod_ledger_rows_counted": self.ledger_lines,
            "over_soft_cap": self.over_soft_cap,
            "over_hard_cap": self.over_hard_cap,
            "reason": self.reason(),
        }


def cumulative_budget(
    paths: CampaignPaths,
    *,
    required_usd: float,
    soft_cap_usd: float = BUDGET_SOFT_CAP_USD,
    hard_cap_usd: float = BUDGET_HARD_CAP_USD,
    campaign_id: str = CAMPAIGN_ID,
) -> CumulativeBudget:
    """Ceilings still outstanding plus billed actuals for this campaign (D22, D75).

    A pod is counted once. While it is provisioned and unbilled its *ceiling*
    stands for it, because nothing yet says what it will cost. The moment its
    billed row lands in ``cost/pod_ledger.jsonl`` the actual replaces the
    ceiling: a settled pod that kept its ceiling would be paid for twice, and
    after 46 canary pods that double count read as $148 against $10.50 of real
    spend -- enough on its own to refuse the Full Run at the section 15.13
    soft cap. The caps are unchanged; what changed is that a pod stops being
    counted twice (D75).
    """

    settled: set[str] = set()
    spent = 0.0
    ledger_lines = 0
    if paths.pod_ledger.is_file():
        for record in iter_jsonl(paths.pod_ledger):
            if not isinstance(record, Mapping):
                continue
            if record.get("campaign_id") != campaign_id:
                continue
            value = record.get("estimated_provider_cost_usd")
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                spent += float(value)
                ledger_lines += 1
                pod_id = record.get("pod_id")
                if isinstance(pod_id, str) and pod_id:
                    settled.add(pod_id)
    committed = 0.0
    provisioning_lines = 0
    if paths.pod_provisioning_ledger.is_file():
        for record in iter_jsonl(paths.pod_provisioning_ledger):
            if not isinstance(record, Mapping):
                continue
            if record.get("campaign_id") != campaign_id:
                continue
            if record.get("mode") != "live":
                continue
            pod_id = record.get("pod_id")
            if isinstance(pod_id, str) and pod_id in settled:
                # Its billed row is in ``spent`` already.
                continue
            value = record.get("required_usd")
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                committed += float(value)
                provisioning_lines += 1

    return CumulativeBudget(
        committed_usd=committed,
        spent_usd=spent,
        required_usd=max(0.0, required_usd),
        soft_cap_usd=soft_cap_usd,
        hard_cap_usd=hard_cap_usd,
        provisioning_lines=provisioning_lines,
        ledger_lines=ledger_lines,
    )


@dataclass(frozen=True, slots=True)
class AuthorizationDecision:
    allowed: bool
    reason: str
    phase: str
    model_key: str | None
    required_usd: float
    receipt: AuthorizationReceipt | None
    considered: tuple[str, ...]
    estimate: CostEstimate | None = None
    budget: CumulativeBudget | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "phase": self.phase,
            "model_key": self.model_key,
            "allowed": self.allowed,
            "reason": self.reason,
            "required_usd": round(self.required_usd, 4),
            "cumulative_budget": None if self.budget is None else self.budget.to_dict(),
            "authorization_receipt_path": (
                None if self.receipt is None else str(self.receipt.path)
            ),
            "authorization_receipt_sha256": (None if self.receipt is None else self.receipt.sha256),
            "authorization_max_usd": None if self.receipt is None else self.receipt.max_usd,
            "authorizations_considered": list(self.considered),
            "cost_estimate": None if self.estimate is None else self.estimate.to_dict(),
        }


def authorize(
    *,
    paths: CampaignPaths,
    phase: str,
    model_key: str | None,
    required_usd: float,
    now: datetime,
    estimate: CostEstimate | None = None,
    campaign_id: str = CAMPAIGN_ID,
) -> AuthorizationDecision:
    """D6. Returns a decision; the caller turns a refusal into EXIT_BLOCKED.

    Loading is fail closed: one malformed file in
    ``receipts/authorizations/`` raises rather than being skipped, because a
    gate that ignores what it cannot parse is not a gate.
    """

    directory = paths.authorizations_dir
    try:
        receipts = load_authorizations(directory, campaign_id=campaign_id)
    except AuthorizationError as exc:
        raise GateError(f"authorization receipts are unreadable: {exc}") from exc

    considered = tuple(_describe(receipt, now) for receipt in receipts)
    budget = cumulative_budget(paths, required_usd=required_usd, campaign_id=campaign_id)
    selected = select_authorization(
        receipts,
        phase=phase,
        model_key=model_key,
        now=now,
        required_usd=required_usd,
    )
    if selected is not None and not budget.allowed:
        # D22: a valid receipt is necessary, not sufficient. One $25 receipt
        # must not fund eleven $25 pods, and the caps are campaign-wide.
        return AuthorizationDecision(
            allowed=False,
            reason=(
                f"{selected.path.name} covers this action, but the campaign budget refuses it: "
                f"{budget.reason()}"
            ),
            phase=phase,
            model_key=model_key,
            required_usd=required_usd,
            receipt=selected,
            considered=considered,
            estimate=estimate,
            budget=budget,
        )
    if selected is not None:
        return AuthorizationDecision(
            allowed=True,
            reason=(
                f"{selected.path.name} authorizes {phase} for "
                f"{model_key or 'the campaign'} up to ${selected.max_usd:,.2f}; "
                f"this action needs ${required_usd:,.2f}. {budget.reason()}"
            ),
            phase=phase,
            model_key=model_key,
            required_usd=required_usd,
            receipt=selected,
            considered=considered,
            estimate=estimate,
            budget=budget,
        )

    if not receipts:
        detail = f"{directory} holds no authorization receipt"
    else:
        detail = f"{len(receipts)} receipt(s) found, none covering this action: " + "; ".join(
            considered
        )
    return AuthorizationDecision(
        allowed=False,
        reason=(
            f"no unexpired {phase} authorization covers "
            f"{model_key or 'the campaign'} at the required ${required_usd:,.2f}. {detail}"
        ),
        phase=phase,
        model_key=model_key,
        required_usd=required_usd,
        receipt=None,
        considered=considered,
        estimate=estimate,
        budget=budget,
    )


def _describe(receipt: AuthorizationReceipt, now: datetime) -> str:
    scope = "*" if receipt.model_keys is None else ",".join(receipt.model_keys)
    expiry = "never" if receipt.expires_at is None else format_timestamp(receipt.expires_at)
    state = "expired" if receipt.is_expired(now) else "valid"
    return (
        f"{receipt.path.name} [phase={receipt.phase} models={scope} "
        f"max_usd={receipt.max_usd} expires={expiry} {state}]"
    )


@dataclass(frozen=True, slots=True)
class LicenseDecision:
    allowed: bool
    reason: str
    model_key: str
    status: str | None
    waiver_path: Path | None
    waiver_sha256: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "model_key": self.model_key,
            "license_status": self.status,
            "allowed": self.allowed,
            "reason": self.reason,
            "waiver_path": None if self.waiver_path is None else str(self.waiver_path),
            "waiver_sha256": self.waiver_sha256,
        }


def license_gate(
    *,
    paths: CampaignPaths,
    model_key: str,
    statuses: Sequence[str | None],
) -> LicenseDecision:
    """D7. ``blocked`` anywhere refuses ``--execute`` without a founder waiver.

    ``statuses`` is every declaration the controller could read -- the
    runtime's ``license.status`` and the registry's -- because a model whose
    two sources disagree is exactly the case where taking the permissive one
    would be the silent fallback the campaign forbids.
    """

    blocked = [status for status in statuses if status == "blocked"]
    status = blocked[0] if blocked else next((s for s in statuses if s), None)
    if not blocked:
        return LicenseDecision(
            allowed=True,
            reason=f"license status {status or '<undeclared>'} does not block execution",
            model_key=model_key,
            status=status,
            waiver_path=None,
            waiver_sha256=None,
        )
    waiver = paths.license_waiver(model_key)
    if not waiver.is_file():
        return LicenseDecision(
            allowed=False,
            reason=(
                f"{model_key} has license.status 'blocked' and no founder waiver at "
                f"receipts/waivers/{waiver.name} (ARENA_CONTRACT section 11 D7)"
            ),
            model_key=model_key,
            status="blocked",
            waiver_path=None,
            waiver_sha256=None,
        )
    document = read_json(waiver)
    if not isinstance(document, dict) or document.get("model_key") != model_key:
        return LicenseDecision(
            allowed=False,
            reason=f"{waiver.name} does not name model_key {model_key!r}",
            model_key=model_key,
            status="blocked",
            waiver_path=waiver,
            waiver_sha256=sha256_file(waiver),
        )
    return LicenseDecision(
        allowed=True,
        reason=f"founder licence waiver on file ({waiver.name})",
        model_key=model_key,
        status="blocked",
        waiver_path=waiver,
        waiver_sha256=sha256_file(waiver),
    )
