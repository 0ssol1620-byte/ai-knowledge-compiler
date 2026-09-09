"""Bounded candidate execution against independent, source-bound text witnesses.

This is an opt-in execution component, not a new production routing policy.
A passing comparison attests only the declared text region. It says nothing
about an unobserved image, table structure, reading order or the whole page.
Unmeasured or non-independent evidence is unresolved, never a confidence of 1.
There is no evaluator/ground-truth loader, network client or publish authority.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import re
import time
import unicodedata
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from .models import Route

_SHA = re.compile(r"^sha256:[a-f0-9]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/#-]{0,255}$")
_MAX_TEXT = 250_000


class EvidenceDisposition(StrEnum):
    VERIFIED_TEXT_REGION = "verified_text_region"
    UNRESOLVED = "unresolved"
    QUARANTINED = "quarantined"


@dataclass(frozen=True, slots=True)
class RegionBinding:
    source_version: str
    representation_sha256: str
    page_index0: int
    region_id: str
    bbox1000: tuple[int, int, int, int]

    def __post_init__(self) -> None:
        if not _SHA.fullmatch(self.source_version) or not _SHA.fullmatch(
            self.representation_sha256
        ):
            raise ValueError("SOURCE_DIGEST_REQUIRED")
        if (
            not _ID.fullmatch(self.region_id)
            or type(self.page_index0) is not int
            or self.page_index0 < 0
        ):
            raise ValueError("REGION_LOCATION_INVALID")
        if (
            not isinstance(self.bbox1000, tuple)
            or len(self.bbox1000) != 4
            or any(type(v) is not int for v in self.bbox1000)
        ):
            raise ValueError("REGION_GEOMETRY_INVALID")
        x0, y0, x1, y1 = self.bbox1000
        if not (0 <= x0 < x1 <= 1000 and 0 <= y0 < y1 <= 1000):
            raise ValueError("REGION_GEOMETRY_INVALID")


@dataclass(frozen=True, slots=True)
class TextObservation:
    binding: RegionBinding
    producer_id: str
    text: str
    output_sha256: str

    def __post_init__(self) -> None:
        if not _ID.fullmatch(self.producer_id) or len(self.text) > _MAX_TEXT:
            raise ValueError("OBSERVATION_LIMIT_OR_PRODUCER_INVALID")
        if self.output_sha256 != text_digest(self.text):
            raise ValueError("OBSERVATION_DIGEST_MISMATCH")


@dataclass(frozen=True, slots=True)
class IndependentTextWitness:
    observation: TextObservation
    # Must come from the trusted source adapter/authority, never an OCR response
    # field. The immutable value documents scope; it is not itself permission.
    source_evidence_id: str
    covers_declared_text_region: bool

    def __post_init__(self) -> None:
        if not _ID.fullmatch(self.source_evidence_id):
            raise ValueError("SOURCE_EVIDENCE_ID_INVALID")
        if type(self.covers_declared_text_region) is not bool:
            raise ValueError("WITNESS_COVERAGE_BOOLEAN_REQUIRED")


@dataclass(frozen=True, slots=True)
class EvidenceCheck:
    disposition: EvidenceDisposition
    reasons: tuple[str, ...]
    candidate_sha256: str | None
    witness_sha256: str | None


def text_digest(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _normalized(text: str) -> str:
    # NFC and whitespace only. Never remove punctuation, signs, units, currency,
    # case, decimal points or duplicated values to make a comparison pass.
    return " ".join(unicodedata.normalize("NFC", text).split())


def verify_text_region(
    expected: RegionBinding,
    candidate: TextObservation,
    witness: IndependentTextWitness | None,
) -> EvidenceCheck:
    if candidate.binding != expected:
        return EvidenceCheck(
            EvidenceDisposition.QUARANTINED,
            ("CANDIDATE_SOURCE_BINDING_MISMATCH",),
            candidate.output_sha256,
            None,
        )
    if witness is None:
        return EvidenceCheck(
            EvidenceDisposition.UNRESOLVED,
            ("INDEPENDENT_EVIDENCE_UNMEASURED",),
            candidate.output_sha256,
            None,
        )
    reference = witness.observation
    if reference.binding != expected:
        return EvidenceCheck(
            EvidenceDisposition.QUARANTINED,
            ("WITNESS_SOURCE_BINDING_MISMATCH",),
            candidate.output_sha256,
            reference.output_sha256,
        )
    reasons = []
    if reference.producer_id == candidate.producer_id:
        reasons.append("INDEPENDENT_EVIDENCE_REQUIRED")
    if not witness.covers_declared_text_region:
        reasons.append("WITNESS_COVERAGE_UNMEASURED")
    candidate_text, reference_text = _normalized(candidate.text), _normalized(reference.text)
    if not reference_text:
        reasons.append("EMPTY_WITNESS_NOT_BLANK_PAGE_PROOF")
    if not candidate_text:
        reasons.append("EMPTY_OUTPUT")
    if candidate_text != reference_text:
        reasons.append("TEXT_WITNESS_MISMATCH")
    return EvidenceCheck(
        EvidenceDisposition.UNRESOLVED if reasons else EvidenceDisposition.VERIFIED_TEXT_REGION,
        tuple(reasons),
        candidate.output_sha256,
        reference.output_sha256,
    )


@dataclass(frozen=True, slots=True)
class RegionAttempt:
    route: Route
    producer_id: str
    reserved_cost: float
    timeout_seconds: float

    def __post_init__(self) -> None:
        if self.route in {Route.UNRESOLVED, Route.QUARANTINE} or not _ID.fullmatch(
            self.producer_id
        ):
            raise ValueError("EXECUTION_ROUTE_INVALID")
        if not math.isfinite(self.reserved_cost) or self.reserved_cost < 0:
            raise ValueError("COST_RESERVATION_INVALID")
        if not math.isfinite(self.timeout_seconds) or not 0 < self.timeout_seconds <= 60:
            raise ValueError("ATTEMPT_TIMEOUT_INVALID")


@dataclass(frozen=True, slots=True)
class AttemptReceipt:
    route: Route
    producer_id: str
    reserved_cost: float
    elapsed_seconds: float
    reasons: tuple[str, ...]
    output_sha256: str | None


@dataclass(frozen=True, slots=True)
class RegionExecutionResult:
    binding: RegionBinding
    disposition: EvidenceDisposition
    accepted: TextObservation | None
    receipts: tuple[AttemptReceipt, ...]
    reasons: tuple[str, ...]
    reserved_cost: float
    # Explicitly cannot be treated as a World promotion or general page proof.
    verification_scope: str = "declared_text_region_only"


Provider = Callable[[RegionBinding], Awaitable[TextObservation]]


async def execute_text_region(
    *,
    binding: RegionBinding,
    witness: IndependentTextWitness | None,
    attempts: Sequence[RegionAttempt],
    providers: Mapping[Route, Provider],
    permitted_routes: frozenset[Route],
    cost_budget: float,
    deadline_seconds: float,
) -> RegionExecutionResult:
    """Try a primary then bounded alternate crops, checking every replacement.

    The caller must derive permitted_routes from tenant data policy and qualified
    provider bindings before invoking this component. No route is added here.
    Providers must propagate cancellation to their bounded worker; asyncio cannot
    terminate a non-cooperative external process. Their production adapter remains
    separately qualified. Reserved cost is NOT a measured invoice amount.
    """
    if not math.isfinite(cost_budget) or cost_budget < 0:
        raise ValueError("COST_BUDGET_INVALID")
    if not math.isfinite(deadline_seconds) or not 0 < deadline_seconds <= 180:
        raise ValueError("DEADLINE_INVALID")
    if not 1 <= len(attempts) <= 5:
        raise ValueError("ATTEMPT_COUNT_INVALID")
    if len({(a.route, a.producer_id) for a in attempts}) != len(attempts):
        raise ValueError("DUPLICATE_EXECUTION_ATTEMPT")
    for attempt in attempts:
        if attempt.route not in permitted_routes or attempt.route not in providers:
            raise ValueError("UNPERMITTED_OR_UNBOUND_ROUTE")
    receipts: list[AttemptReceipt] = []
    spent = 0.0
    started = time.monotonic()
    terminal_reasons: tuple[str, ...] = ("NO_VERIFIED_TEXT_REGION",)
    for attempt in attempts:
        remaining = deadline_seconds - (time.monotonic() - started)
        if remaining <= 0:
            terminal_reasons = ("EXECUTION_DEADLINE_REACHED",)
            break
        if spent + attempt.reserved_cost > cost_budget:
            terminal_reasons = ("EXECUTION_BUDGET_REACHED",)
            break
        spent += attempt.reserved_cost
        began = time.monotonic()
        observation: TextObservation | None = None
        check: EvidenceCheck | None = None
        try:
            async with asyncio.timeout(min(remaining, attempt.timeout_seconds)):
                observation = await providers[attempt.route](binding)
            if observation.producer_id != attempt.producer_id:
                check = EvidenceCheck(
                    EvidenceDisposition.QUARANTINED,
                    ("PROVIDER_IDENTITY_MISMATCH",),
                    observation.output_sha256,
                    None,
                )
            else:
                check = verify_text_region(binding, observation, witness)
            terminal_reasons = check.reasons or ("TEXT_REGION_VERIFIED",)
        except TimeoutError:
            terminal_reasons = ("PROVIDER_TIMEOUT",)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Exception messages can contain customer text or credentials.
            terminal_reasons = ("PROVIDER_FAILURE",)
        receipts.append(
            AttemptReceipt(
                attempt.route,
                attempt.producer_id,
                attempt.reserved_cost,
                time.monotonic() - began,
                terminal_reasons,
                observation.output_sha256 if observation else None,
            )
        )
        if check and check.disposition is EvidenceDisposition.QUARANTINED:
            return RegionExecutionResult(
                binding, check.disposition, None, tuple(receipts), terminal_reasons, spent
            )
        if check and check.disposition is EvidenceDisposition.VERIFIED_TEXT_REGION:
            return RegionExecutionResult(
                binding, check.disposition, observation, tuple(receipts), (), spent
            )
    return RegionExecutionResult(
        binding, EvidenceDisposition.UNRESOLVED, None, tuple(receipts), terminal_reasons, spent
    )
