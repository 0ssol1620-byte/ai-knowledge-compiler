"""Execute an existing document plan over bounded source-bound text regions.

Opt-in, in-process composition, not a production-policy replacement. The caller
supplies sandboxed, cancellation-cooperative providers and live authorization.
No network client, hidden evaluator, generic page-quality claim or World publish
operation exists here. Declared text verification is not visual/table fidelity.
"""

from __future__ import annotations

import asyncio
import math
import re
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, replace
from decimal import Decimal
from types import MappingProxyType
from typing import Literal

from .data_policy import filter_candidate_routes
from .evidence_execution import (
    EvidenceDisposition,
    IndependentTextWitness,
    Provider,
    RegionAttempt,
    RegionBinding,
    RegionExecutionResult,
    TextObservation,
    execute_text_region,
)
from .execution_plan import DocumentExecutionPlan
from .models import ProcessingMode, Route
from .portfolio import Portfolio

_SHA = re.compile(r"^sha256:[a-f0-9]{64}$")
_MAX_REGIONS = 4096
_MAX_CONCURRENT_REGIONS = 32


@dataclass(frozen=True, slots=True)
class DocumentSourceBinding:
    source_version_id: str
    source_sha256: str
    representation_sha256: str

    def __post_init__(self) -> None:
        if not self.source_version_id or len(self.source_version_id) > 256:
            raise ValueError("SOURCE_VERSION_ID_REQUIRED")
        if not _SHA.fullmatch(self.source_sha256) or not _SHA.fullmatch(self.representation_sha256):
            raise ValueError("DOCUMENT_SOURCE_DIGEST_REQUIRED")


@dataclass(frozen=True, slots=True)
class RegionWork:
    binding: RegionBinding
    witness: IndependentTextWitness | None
    attempts: tuple[RegionAttempt, ...]


@dataclass(frozen=True, slots=True)
class DocumentTextExecutionResult:
    plan_id: str
    source: DocumentSourceBinding
    regions: Mapping[str, RegionExecutionResult]
    reserved_cost: float
    elapsed_seconds: float
    disposition: Literal["verified_text_scope", "unresolved", "quarantined"]
    reasons: tuple[str, ...]
    verification_scope: Literal["declared_text_regions_only"] = "declared_text_regions_only"
    production_promotion: Literal[False] = False


def _unresolved(work: RegionWork, reason: str) -> RegionExecutionResult:
    return RegionExecutionResult(
        work.binding, EvidenceDisposition.UNRESOLVED, None, (), (reason,), 0.0
    )


async def execute_document_text_plan(
    *,
    plan: DocumentExecutionPlan,
    source: DocumentSourceBinding,
    regions: Mapping[str, RegionWork],
    providers: Mapping[Route, Provider],
    portfolio: Portfolio,
    qualified_routes: frozenset[Route],
    authorization_valid: Callable[[], bool],
    deadline_seconds: float,
    mode: ProcessingMode = ProcessingMode.BALANCED,
    secret_detected: bool = False,
    route_concurrency: Mapping[Route, int] | None = None,
) -> DocumentTextExecutionResult:
    """Execute bounded workers per wave, with recovery sharing one cost ledger.

    Queue time counts against the execution deadline and per-attempt timeout.
    Reservations include failed/timeout work; they are not measured invoices.
    Cross-document/tenant fairness and durable worker ownership remain the
    service scheduler's responsibility. The callback is trusted application
    authority, never text supplied by a document or an OCR response.
    """
    started = time.monotonic()
    plan = plan.model_copy(deep=True)
    if not math.isfinite(deadline_seconds) or not 0 < deadline_seconds <= 180:
        raise ValueError("DOCUMENT_DEADLINE_INVALID")
    if not plan.is_executable:
        raise ValueError("DOCUMENT_PLAN_NOT_EXECUTABLE")
    if plan.source_version_id != source.source_version_id:
        raise ValueError("DOCUMENT_PLAN_SOURCE_MISMATCH")
    if plan.portfolio_revision != portfolio.revision:
        raise ValueError("DOCUMENT_PORTFOLIO_REVISION_MISMATCH")
    if not math.isfinite(plan.cost_budget) or plan.cost_budget < 0:
        raise ValueError("DOCUMENT_BUDGET_INVALID")
    if not 1 <= plan.parallelism_budget <= _MAX_CONCURRENT_REGIONS:
        raise ValueError("DOCUMENT_EXECUTOR_CAPACITY_UNQUALIFIED")

    # Snapshot mutable callers before the first await. A plan or provider-map
    # mutation by another coroutine must not redirect already-authorized work.
    work = dict(regions)
    provider_map = dict(providers)
    by_wave: dict[int, list[str]] = {}
    wave_of: dict[str, int] = {}
    used_routes: set[Route] = set()
    for wave in plan.execution_waves:
        for unit_id in wave.unit_ids:
            if unit_id in wave_of:
                raise ValueError("DOCUMENT_UNIT_REPEATED")
            wave_of[unit_id] = wave.wave_index
            by_wave.setdefault(wave.wave_index, []).append(unit_id)
    if not 1 <= len(wave_of) <= _MAX_REGIONS or set(wave_of) != set(work):
        raise ValueError("DOCUMENT_REGION_INVENTORY_MISMATCH")
    for item in work.values():
        if item.binding.source_version != source.source_sha256 or (
            item.binding.representation_sha256 != source.representation_sha256
        ):
            raise ValueError("DOCUMENT_REGION_SOURCE_MISMATCH")
        if not isinstance(item.attempts, tuple) or not 1 <= len(item.attempts) <= 5:
            raise ValueError("DOCUMENT_REGION_ATTEMPTS_INVALID")
        if len({(a.route, a.producer_id) for a in item.attempts}) != len(item.attempts):
            raise ValueError("DUPLICATE_EXECUTION_ATTEMPT")
        used_routes.update(a.route for a in item.attempts)
    permitted = frozenset(
        filter_candidate_routes(
            used_routes, plan.data_policy, mode=mode, secret_detected=secret_detected
        ).permitted_routes
    )
    if (
        used_routes != permitted
        or not used_routes <= qualified_routes
        or (not used_routes <= provider_map.keys())
    ):
        raise ValueError("DOCUMENT_ROUTE_UNPERMITTED_OR_UNQUALIFIED")
    for wave in plan.execution_waves:
        binding = portfolio.binding(wave.lane)
        if (
            binding is None
            or not binding.is_promotable
            or any(work[unit].attempts[0].route is not binding.route for unit in wave.unit_ids)
        ):
            raise ValueError("DOCUMENT_PRIMARY_LANE_MISMATCH")

    dependencies: dict[str, set[str]] = {unit: set() for unit in work}
    for edge in plan.dependency_edges:
        if edge.from_unit_id not in work or edge.to_unit_id not in work:
            raise ValueError("DOCUMENT_DEPENDENCY_OUTSIDE_INVENTORY")
        if edge.blocking:
            # A valid layering proves acyclicity without accepting a cyclic plan
            # whose longest-path routine merely stopped after N iterations.
            if wave_of[edge.from_unit_id] >= wave_of[edge.to_unit_id]:
                raise ValueError("DOCUMENT_DEPENDENCY_WAVE_INVALID")
            dependencies[edge.to_unit_id].add(edge.from_unit_id)

    limits = dict(route_concurrency or {})
    if any(type(v) is not int or not 1 <= v <= _MAX_CONCURRENT_REGIONS for v in limits.values()):
        raise ValueError("DOCUMENT_ROUTE_CAPACITY_INVALID")
    semaphores = {
        route: asyncio.Semaphore(limits.get(route, plan.parallelism_budget))
        for route in used_routes
    }
    revoked = False
    quarantined = False
    spent = Decimal(0)
    ceiling = Decimal(str(plan.cost_budget))
    results: dict[str, RegionExecutionResult] = {}

    def authorized() -> bool:
        nonlocal revoked
        if revoked:
            return False
        try:
            revoked = authorization_valid() is not True
        except Exception:
            # No callback exception message or provider/customer text in receipts.
            revoked = True
        return not revoked

    def reserve(amount: float) -> bool:
        nonlocal spent
        value = Decimal(str(amount))
        if spent + value > ceiling:
            return False
        spent += value  # No await: atomic within this bounded event-loop execution.
        return True

    def wrap(route: Route) -> Provider:
        async def invoke(binding: RegionBinding) -> TextObservation:
            async with semaphores[route]:
                if not authorized() or quarantined:
                    raise PermissionError("EXECUTION_AUTHORITY_WITHHELD")
                return await provider_map[route](binding)

        return invoke

    wrapped = {route: wrap(route) for route in used_routes}
    for wave_index in sorted(by_wave):
        pending = iter(sorted(by_wave[wave_index]))

        async def worker(unit_ids: Iterator[str]) -> None:
            nonlocal quarantined
            for unit_id in unit_ids:
                item = work[unit_id]
                remaining = deadline_seconds - (time.monotonic() - started)
                if not authorized():
                    results[unit_id] = _unresolved(item, "EXECUTION_AUTHORIZATION_REVOKED")
                elif quarantined:
                    results[unit_id] = _unresolved(item, "DOCUMENT_QUARANTINED")
                elif remaining <= 0:
                    results[unit_id] = _unresolved(item, "DOCUMENT_DEADLINE_REACHED")
                elif any(
                    results[parent].disposition is not EvidenceDisposition.VERIFIED_TEXT_REGION
                    for parent in dependencies[unit_id]
                ):
                    results[unit_id] = _unresolved(item, "DEPENDENCY_NOT_VERIFIED")
                else:
                    result = await execute_text_region(
                        binding=item.binding,
                        witness=item.witness,
                        attempts=item.attempts,
                        providers=wrapped,
                        permitted_routes=permitted,
                        cost_budget=plan.cost_budget,
                        deadline_seconds=remaining,
                        reserve_cost=reserve,
                        authorization_valid=authorized,
                    )
                    results[unit_id] = result
                    if result.disposition is EvidenceDisposition.QUARANTINED:
                        quarantined = True

        # Only this many tasks exist, even for a many-thousand-region document.
        # TaskGroup cancels and awaits cooperative children on caller cancellation.
        async with asyncio.TaskGroup() as group:
            for _ in range(min(plan.parallelism_budget, len(by_wave[wave_index]))):
                group.create_task(worker(pending))

    authorized()  # Recheck before disclosing any previously accepted text.
    reason: tuple[str, ...] = ()
    disposition: Literal["verified_text_scope", "unresolved", "quarantined"]
    if quarantined or revoked:
        reason = ("EXECUTION_AUTHORIZATION_REVOKED" if revoked else "DOCUMENT_QUARANTINED",)
        results = {
            unit: replace(
                result,
                accepted=None,
                disposition=EvidenceDisposition.QUARANTINED
                if quarantined
                else EvidenceDisposition.UNRESOLVED,
                reasons=reason,
            )
            for unit, result in results.items()
        }
        disposition = "quarantined" if quarantined else "unresolved"
    elif all(r.disposition is EvidenceDisposition.VERIFIED_TEXT_REGION for r in results.values()):
        disposition = "verified_text_scope"
    else:
        disposition, reason = "unresolved", ("DOCUMENT_TEXT_SCOPE_INCOMPLETE",)
    return DocumentTextExecutionResult(
        plan.plan_id,
        source,
        MappingProxyType({unit: results[unit] for unit in work}),
        float(spent),
        time.monotonic() - started,
        disposition,
        reason,
    )
