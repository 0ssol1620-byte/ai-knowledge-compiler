"""Exactly-once reservation and accepted-work-only credit settlement."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_EVEN, Decimal
from enum import StrEnum
from threading import RLock

from .identity import canonical_sha256, stable_id
from .models import ACCEPTED_VERIFICATION_STATES, AttemptKind, VerificationState

_QUANTUM = Decimal("0.000001")


def _credits(value: Decimal) -> Decimal:
    if not value.is_finite() or value < 0:
        raise ValueError("credit values must be finite and non-negative")
    return value.quantize(_QUANTUM, rounding=ROUND_HALF_EVEN)


class CreditEntryType(StrEnum):
    RESERVED = "reserved"
    CONSUMED = "consumed"
    RELEASED = "released"
    COMPUTE_TELEMETRY = "compute_telemetry"


class CreditConflictError(RuntimeError):
    pass


class CreditLimitExceeded(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CreditReservation:
    reservation_id: str
    account_id: str
    job_id: str
    reserved_credits: Decimal
    created_at: datetime
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class CreditEntry:
    entry_id: str
    reservation_id: str
    entry_type: CreditEntryType
    amount: Decimal
    occurred_at: datetime
    reason_code: str
    work_key: str | None
    attempt_id: str | None
    idempotency_key: str
    metadata_sha256: str


@dataclass(frozen=True, slots=True)
class SettlementResult:
    reservation_id: str
    work_key: str
    attempt_id: str
    user_credits_charged: Decimal
    billable: bool
    duplicate: bool
    reason_code: str
    entry: CreditEntry | None


@dataclass(slots=True)
class _ReservationState:
    reservation: CreditReservation
    consumed: Decimal = Decimal("0")
    released: Decimal = Decimal("0")

    @property
    def available(self) -> Decimal:
        return self.reservation.reserved_credits - self.consumed - self.released


class CreditLedger:
    def __init__(self) -> None:
        self._reservations: dict[str, _ReservationState] = {}
        self._keys: dict[str, tuple[str, object]] = {}
        self._charged_work: dict[tuple[str, str], SettlementResult] = {}
        self._entries: list[CreditEntry] = []
        self._lock = RLock()

    @staticmethod
    def _aware(value: datetime) -> None:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("credit ledger timestamps must be timezone-aware")

    def _idempotent(self, key: str, identity: str) -> object | None:
        existing = self._keys.get(key)
        if existing is None:
            return None
        existing_identity, result = existing
        if existing_identity != identity:
            raise CreditConflictError("credit idempotency key reused with different input")
        return result

    def reserve(
        self,
        *,
        account_id: str,
        job_id: str,
        amount: Decimal,
        occurred_at: datetime,
        idempotency_key: str,
    ) -> CreditReservation:
        amount = _credits(amount)
        self._aware(occurred_at)
        identity = canonical_sha256(
            {"operation": "reserve", "account_id": account_id, "job_id": job_id, "amount": amount}
        )
        with self._lock:
            existing = self._idempotent(idempotency_key, identity)
            if isinstance(existing, CreditReservation):
                return existing
            reservation_id = stable_id("reservation", account_id, job_id, idempotency_key)
            reservation = CreditReservation(
                reservation_id=reservation_id,
                account_id=account_id,
                job_id=job_id,
                reserved_credits=amount,
                created_at=occurred_at,
                idempotency_key=idempotency_key,
            )
            state = _ReservationState(reservation=reservation)
            self._reservations[reservation_id] = state
            entry = self._entry(
                reservation_id=reservation_id,
                entry_type=CreditEntryType.RESERVED,
                amount=amount,
                occurred_at=occurred_at,
                reason_code="job_credit_ceiling_reserved",
                work_key=None,
                attempt_id=None,
                idempotency_key=f"entry:{idempotency_key}",
                metadata={"account_id": account_id, "job_id": job_id},
            )
            self._entries.append(entry)
            self._keys[idempotency_key] = (identity, reservation)
            return reservation

    @staticmethod
    def _entry(
        *,
        reservation_id: str,
        entry_type: CreditEntryType,
        amount: Decimal,
        occurred_at: datetime,
        reason_code: str,
        work_key: str | None,
        attempt_id: str | None,
        idempotency_key: str,
        metadata: dict[str, object],
    ) -> CreditEntry:
        metadata_sha256 = canonical_sha256(metadata)
        return CreditEntry(
            entry_id=stable_id(
                "credit_entry",
                reservation_id,
                entry_type,
                work_key,
                attempt_id,
                idempotency_key,
                metadata_sha256,
            ),
            reservation_id=reservation_id,
            entry_type=entry_type,
            amount=amount,
            occurred_at=occurred_at,
            reason_code=reason_code,
            work_key=work_key,
            attempt_id=attempt_id,
            idempotency_key=idempotency_key,
            metadata_sha256=metadata_sha256,
        )

    def settle_work(
        self,
        *,
        reservation_id: str,
        work_key: str,
        attempt_id: str,
        attempt_kind: AttemptKind,
        verification_state: VerificationState,
        canonical_credits: Decimal,
        occurred_at: datetime,
        idempotency_key: str,
    ) -> SettlementResult:
        canonical_credits = _credits(canonical_credits)
        self._aware(occurred_at)
        identity = canonical_sha256(
            {
                "operation": "settle_work",
                "reservation_id": reservation_id,
                "work_key": work_key,
                "attempt_id": attempt_id,
                "attempt_kind": attempt_kind,
                "verification_state": verification_state,
                "canonical_credits": canonical_credits,
            }
        )
        with self._lock:
            existing = self._idempotent(idempotency_key, identity)
            if isinstance(existing, SettlementResult):
                return existing
            state = self._reservations[reservation_id]
            accepted = verification_state in ACCEPTED_VERIFICATION_STATES
            prior = self._charged_work.get((reservation_id, work_key))
            if prior is not None:
                result = SettlementResult(
                    reservation_id=reservation_id,
                    work_key=work_key,
                    attempt_id=attempt_id,
                    user_credits_charged=Decimal("0.000000"),
                    billable=False,
                    duplicate=True,
                    reason_code="logical_work_already_charged",
                    entry=None,
                )
            elif not accepted:
                result = SettlementResult(
                    reservation_id=reservation_id,
                    work_key=work_key,
                    attempt_id=attempt_id,
                    user_credits_charged=Decimal("0.000000"),
                    billable=False,
                    duplicate=attempt_kind
                    in {AttemptKind.HEDGE, AttemptKind.STRAGGLER, AttemptKind.SHADOW},
                    reason_code=f"{verification_state.value}_not_billable",
                    entry=None,
                )
            else:
                if canonical_credits > state.available:
                    raise CreditLimitExceeded("accepted work exceeds the remaining reservation")
                entry = self._entry(
                    reservation_id=reservation_id,
                    entry_type=CreditEntryType.CONSUMED,
                    amount=canonical_credits,
                    occurred_at=occurred_at,
                    reason_code="accepted_logical_work",
                    work_key=work_key,
                    attempt_id=attempt_id,
                    idempotency_key=f"entry:{idempotency_key}",
                    metadata={
                        "attempt_kind": attempt_kind.value,
                        "verification_state": verification_state.value,
                        "internal_attempt_surcharge": "0.000000",
                    },
                )
                state.consumed += canonical_credits
                self._entries.append(entry)
                result = SettlementResult(
                    reservation_id=reservation_id,
                    work_key=work_key,
                    attempt_id=attempt_id,
                    user_credits_charged=canonical_credits,
                    billable=True,
                    duplicate=False,
                    reason_code="accepted_logical_work",
                    entry=entry,
                )
                self._charged_work[(reservation_id, work_key)] = result
            self._keys[idempotency_key] = (identity, result)
            return result

    def record_compute_telemetry(
        self,
        *,
        reservation_id: str,
        attempt_id: str,
        attempt_kind: AttemptKind,
        gpu_seconds: Decimal,
        provider_cost: Decimal,
        occurred_at: datetime,
        idempotency_key: str,
    ) -> CreditEntry:
        gpu_seconds = _credits(gpu_seconds)
        provider_cost = _credits(provider_cost)
        self._aware(occurred_at)
        identity = canonical_sha256(
            {
                "operation": "compute_telemetry",
                "reservation_id": reservation_id,
                "attempt_id": attempt_id,
                "attempt_kind": attempt_kind,
                "gpu_seconds": gpu_seconds,
                "provider_cost": provider_cost,
            }
        )
        with self._lock:
            existing = self._idempotent(idempotency_key, identity)
            if isinstance(existing, CreditEntry):
                return existing
            if reservation_id not in self._reservations:
                raise KeyError(reservation_id)
            entry = self._entry(
                reservation_id=reservation_id,
                entry_type=CreditEntryType.COMPUTE_TELEMETRY,
                amount=Decimal("0.000000"),
                occurred_at=occurred_at,
                reason_code="duplicate_compute_recorded_not_billed",
                work_key=None,
                attempt_id=attempt_id,
                idempotency_key=f"entry:{idempotency_key}",
                metadata={
                    "attempt_kind": attempt_kind.value,
                    "gpu_seconds": gpu_seconds,
                    "provider_cost": provider_cost,
                    "user_credits": "0.000000",
                },
            )
            self._entries.append(entry)
            self._keys[idempotency_key] = (identity, entry)
            return entry

    def release_remaining(
        self,
        *,
        reservation_id: str,
        occurred_at: datetime,
        idempotency_key: str,
    ) -> CreditEntry:
        self._aware(occurred_at)
        identity = canonical_sha256(
            {"operation": "release_remaining", "reservation_id": reservation_id}
        )
        with self._lock:
            existing = self._idempotent(idempotency_key, identity)
            if isinstance(existing, CreditEntry):
                return existing
            state = self._reservations[reservation_id]
            amount = _credits(state.available)
            entry = self._entry(
                reservation_id=reservation_id,
                entry_type=CreditEntryType.RELEASED,
                amount=amount,
                occurred_at=occurred_at,
                reason_code="unused_reservation_released",
                work_key=None,
                attempt_id=None,
                idempotency_key=f"entry:{idempotency_key}",
                metadata={
                    "consumed": state.consumed,
                    "reserved": state.reservation.reserved_credits,
                },
            )
            state.released += amount
            self._entries.append(entry)
            self._keys[idempotency_key] = (identity, entry)
            return entry

    def balance(self, reservation_id: str) -> tuple[Decimal, Decimal, Decimal]:
        with self._lock:
            state = self._reservations[reservation_id]
            return state.consumed, state.released, state.available

    def entries(self, reservation_id: str | None = None) -> tuple[CreditEntry, ...]:
        with self._lock:
            if reservation_id is None:
                return tuple(self._entries)
            return tuple(
                entry for entry in self._entries if entry.reservation_id == reservation_id
            )


__all__ = [
    "CreditConflictError",
    "CreditEntry",
    "CreditEntryType",
    "CreditLedger",
    "CreditLimitExceeded",
    "CreditReservation",
    "SettlementResult",
]
