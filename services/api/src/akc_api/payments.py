"""Provider-neutral credit purchases, signed webhook inbox, and reconciliation."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from typing import Any, Protocol, cast

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from akc_api.database import set_rls_context
from akc_api.models import (
    Checkout,
    CreditAccount,
    CreditGrant,
    Dispute,
    Payment,
    PaymentEvent,
    Reconciliation,
    Refund,
    Reversal,
    utcnow,
)
from akc_api.services import audit, credit_entry
from akc_api.settings import Settings

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{2,199}$")
_CREDIT_QUANTUM = Decimal("0.000001")
_MAX_MINOR_AMOUNT = 9_000_000_000_000
_KNOWN_EVENT_TYPES = frozenset(
    {
        "checkout.expired",
        "payment.succeeded",
        "payment.failed",
        "payment.refunded",
        "payment.dispute.opened",
        "payment.dispute.won",
        "payment.dispute.lost",
    }
)
_DATA_FIELDS = frozenset(
    {
        "tenant_id",
        "checkout_id",
        "payment_id",
        "refund_id",
        "dispute_id",
        "amount_minor",
        "currency",
    }
)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class CreditPack:
    code: str
    amount_minor: int
    currency: str
    credits: Decimal


CREDIT_PACKS: Mapping[str, CreditPack] = {
    "starter_krw": CreditPack(
        code="starter_krw",
        amount_minor=4_900,
        currency="KRW",
        credits=Decimal("300"),
    ),
    "pro_krw": CreditPack(
        code="pro_krw",
        amount_minor=29_900,
        currency="KRW",
        credits=Decimal("3000"),
    ),
    "starter_usd": CreditPack(
        code="starter_usd",
        amount_minor=399,
        currency="USD",
        credits=Decimal("300"),
    ),
    "pro_usd": CreditPack(
        code="pro_usd",
        amount_minor=2499,
        currency="USD",
        credits=Decimal("3000"),
    ),
}


class PaymentProviderUnavailable(RuntimeError):
    """Raised when checkout creation has no configured safe adapter."""


class PaymentWebhookError(ValueError):
    """Safe error returned before an event enters the financial inbox."""

    def __init__(self, code: str, *, status_code: int = 400) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


class PaymentEventError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class RetryablePaymentEvent(PaymentEventError):
    pass


class PermanentPaymentEvent(PaymentEventError):
    pass


@dataclass(frozen=True, slots=True)
class ProviderCheckout:
    provider_checkout_id: str | None
    checkout_url: str | None
    status: str


class PaymentProvider(Protocol):
    name: str

    async def create_checkout(self, checkout: Checkout) -> ProviderCheckout: ...

    async def aclose(self) -> None: ...


class FakePaymentProvider:
    """Credential-free local provider. It never performs network I/O."""

    name = "fake"

    def __init__(self, *, environment: str) -> None:
        if environment not in {"development", "test"}:
            raise ValueError("fake payment provider is development/test only")

    async def create_checkout(self, checkout: Checkout) -> ProviderCheckout:
        provider_id = f"fake_co_{checkout.id.hex}"
        return ProviderCheckout(
            provider_checkout_id=provider_id,
            checkout_url=(f"http://localhost:3000/billing/fake-checkout?checkout_id={checkout.id}"),
            status="open",
        )

    async def aclose(self) -> None:
        return None


class MerchantHandoffPaymentProvider:
    """No-network production handoff.

    A separately controlled merchant connector can claim the durable checkout
    and return signed events. The API itself never calls an external payment
    endpoint.
    """

    name = "merchant"

    async def create_checkout(self, checkout: Checkout) -> ProviderCheckout:
        return ProviderCheckout(
            provider_checkout_id=f"pending_{checkout.id.hex}",
            checkout_url=None,
            status="provider_pending",
        )

    async def aclose(self) -> None:
        return None


class DisabledPaymentProvider:
    name = "disabled"

    async def create_checkout(self, checkout: Checkout) -> ProviderCheckout:
        del checkout
        raise PaymentProviderUnavailable("payment_provider_unavailable")

    async def aclose(self) -> None:
        return None


def build_payment_provider(settings: Settings) -> PaymentProvider:
    if settings.payment_provider == "fake":
        return FakePaymentProvider(environment=settings.env)
    if settings.payment_provider == "merchant":
        return MerchantHandoffPaymentProvider()
    return DisabledPaymentProvider()


@dataclass(frozen=True, slots=True)
class ParsedPaymentEvent:
    provider_event_id: str
    event_type: str
    provider_created_at: datetime
    tenant_id: uuid.UUID
    checkout_id: uuid.UUID
    data: Mapping[str, Any]
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class PaymentEventReceipt:
    event: PaymentEvent
    duplicate: bool


def _json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise PaymentWebhookError("PAYMENT_WEBHOOK_DUPLICATE_JSON_KEY")
        value[key] = item
    return value


def _identifier(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise PaymentWebhookError(f"PAYMENT_WEBHOOK_INVALID_{field.upper()}")
    return value


def _uuid(value: Any, *, field: str) -> uuid.UUID:
    try:
        parsed = uuid.UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise PaymentWebhookError(f"PAYMENT_WEBHOOK_INVALID_{field.upper()}") from exc
    if str(parsed) != str(value).lower():
        raise PaymentWebhookError(f"PAYMENT_WEBHOOK_INVALID_{field.upper()}")
    return parsed


def _minor_amount(value: Any) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value <= 0
        or value > _MAX_MINOR_AMOUNT
    ):
        raise PaymentWebhookError("PAYMENT_WEBHOOK_INVALID_AMOUNT")
    return cast(int, value)


def _currency(value: Any, supported: frozenset[str]) -> str:
    if (
        not isinstance(value, str)
        or value not in supported
        or len(value) != 3
        or value != value.upper()
    ):
        raise PaymentWebhookError("PAYMENT_WEBHOOK_INVALID_CURRENCY")
    return value


def parse_payment_event(
    raw_body: bytes,
    *,
    supported_currencies: frozenset[str],
) -> ParsedPaymentEvent:
    try:
        payload = json.loads(raw_body, object_pairs_hook=_json_object)
    except PaymentWebhookError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PaymentWebhookError("PAYMENT_WEBHOOK_INVALID_JSON") from exc
    if not isinstance(payload, dict):
        raise PaymentWebhookError("PAYMENT_WEBHOOK_INVALID_ENVELOPE")
    if set(payload) != {"id", "type", "created", "data"}:
        raise PaymentWebhookError("PAYMENT_WEBHOOK_INVALID_ENVELOPE")
    provider_event_id = _identifier(payload["id"], field="event_id")
    event_type = _identifier(payload["type"], field="event_type")
    created = payload["created"]
    if (
        isinstance(created, bool)
        or not isinstance(created, int)
        or created <= 0
        or created > 253_402_300_799
    ):
        raise PaymentWebhookError("PAYMENT_WEBHOOK_INVALID_CREATED")
    try:
        provider_created_at = datetime.fromtimestamp(created, tz=UTC)
    except (OverflowError, OSError, ValueError) as exc:
        raise PaymentWebhookError("PAYMENT_WEBHOOK_INVALID_CREATED") from exc
    data = payload["data"]
    if not isinstance(data, dict) or not set(data).issubset(_DATA_FIELDS):
        raise PaymentWebhookError("PAYMENT_WEBHOOK_INVALID_DATA")
    if not {"tenant_id", "checkout_id"}.issubset(data):
        raise PaymentWebhookError("PAYMENT_WEBHOOK_INVALID_DATA")
    tenant_id = _uuid(data["tenant_id"], field="tenant_id")
    checkout_id = _uuid(data["checkout_id"], field="checkout_id")
    if event_type != "checkout.expired":
        required = {"payment_id", "amount_minor", "currency"}
        if not required.issubset(data):
            raise PaymentWebhookError("PAYMENT_WEBHOOK_INVALID_DATA")
        _identifier(data["payment_id"], field="payment_id")
        _minor_amount(data["amount_minor"])
        _currency(data["currency"], supported_currencies)
    if event_type == "payment.refunded":
        _identifier(data.get("refund_id"), field="refund_id")
    if event_type.startswith("payment.dispute."):
        _identifier(data.get("dispute_id"), field="dispute_id")
    return ParsedPaymentEvent(
        provider_event_id=provider_event_id,
        event_type=event_type,
        provider_created_at=provider_created_at,
        tenant_id=tenant_id,
        checkout_id=checkout_id,
        data=cast(Mapping[str, Any], data),
        payload=cast(dict[str, Any], payload),
    )


def payment_webhook_signature(
    secret: str,
    *,
    timestamp: int,
    raw_body: bytes,
) -> str:
    message = str(timestamp).encode("ascii") + b"." + raw_body
    digest = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return f"v1={digest}"


def verify_payment_webhook(
    *,
    secret: str,
    timestamp_header: str | None,
    signature_header: str | None,
    raw_body: bytes,
    tolerance_seconds: int,
    max_bytes: int,
    now: datetime | None = None,
) -> None:
    if len(raw_body) > max_bytes:
        raise PaymentWebhookError(
            "PAYMENT_WEBHOOK_TOO_LARGE",
            status_code=413,
        )
    if (
        timestamp_header is None
        or not timestamp_header.isascii()
        or not timestamp_header.isdigit()
        or len(timestamp_header) > 12
    ):
        raise PaymentWebhookError(
            "PAYMENT_WEBHOOK_TIMESTAMP_INVALID",
            status_code=401,
        )
    timestamp = int(timestamp_header)
    current = now or utcnow()
    if abs(int(current.timestamp()) - timestamp) > tolerance_seconds:
        raise PaymentWebhookError(
            "PAYMENT_WEBHOOK_TIMESTAMP_EXPIRED",
            status_code=401,
        )
    if signature_header is None or not signature_header.startswith("v1="):
        raise PaymentWebhookError(
            "PAYMENT_WEBHOOK_SIGNATURE_INVALID",
            status_code=401,
        )
    supplied = signature_header[3:]
    if len(supplied) != 64 or any(character not in "0123456789abcdef" for character in supplied):
        raise PaymentWebhookError(
            "PAYMENT_WEBHOOK_SIGNATURE_INVALID",
            status_code=401,
        )
    expected = payment_webhook_signature(
        secret,
        timestamp=timestamp,
        raw_body=raw_body,
    )[3:]
    if not hmac.compare_digest(supplied, expected):
        raise PaymentWebhookError(
            "PAYMENT_WEBHOOK_SIGNATURE_INVALID",
            status_code=401,
        )


def available_credit_packs(settings: Settings) -> tuple[CreditPack, ...]:
    return tuple(
        pack
        for pack in CREDIT_PACKS.values()
        if pack.currency in settings.supported_payment_currencies
    )


def credit_pack(settings: Settings, code: str) -> CreditPack:
    pack = CREDIT_PACKS.get(code)
    if pack is None or pack.currency not in settings.supported_payment_currencies:
        raise ValueError("credit_pack_not_found")
    return pack


async def create_credit_checkout(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    actor_id: uuid.UUID,
    pack: CreditPack,
    provider: PaymentProvider,
    settings: Settings,
) -> Checkout:
    if not settings.payments_enabled:
        raise PaymentProviderUnavailable("payments_disabled")
    if provider.name != settings.payment_provider:
        raise PaymentProviderUnavailable("payment_provider_mismatch")
    checkout = Checkout(
        tenant_id=tenant_id,
        created_by=actor_id,
        provider=provider.name,
        provider_checkout_id=None,
        pack_code=pack.code,
        amount_minor=pack.amount_minor,
        currency=pack.currency,
        credits=pack.credits,
        status="requested",
        checkout_url=None,
        expires_at=utcnow() + timedelta(seconds=settings.payment_checkout_ttl_seconds),
    )
    session.add(checkout)
    await session.flush()
    provider_result = await provider.create_checkout(checkout)
    checkout.provider_checkout_id = provider_result.provider_checkout_id
    checkout.checkout_url = provider_result.checkout_url
    checkout.status = provider_result.status
    await audit(
        session,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="billing.checkout.created",
        target_type="payment_checkout",
        target_id=str(checkout.id),
        metadata={
            "pack_code": pack.code,
            "amount_minor": pack.amount_minor,
            "currency": pack.currency,
            "provider": provider.name,
        },
    )
    await session.flush()
    return checkout


def _event_data(event: PaymentEvent) -> Mapping[str, Any]:
    data = event.payload_json.get("data")
    if not isinstance(data, dict):
        raise PermanentPaymentEvent("PAYMENT_EVENT_DATA_INVALID")
    return cast(Mapping[str, Any], data)


async def _checkout_for_event(
    session: AsyncSession,
    event: PaymentEvent,
) -> Checkout:
    data = _event_data(event)
    try:
        checkout_id = uuid.UUID(str(data["checkout_id"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise PermanentPaymentEvent("CHECKOUT_REFERENCE_INVALID") from exc
    checkout = await session.scalar(
        select(Checkout)
        .where(
            Checkout.tenant_id == event.tenant_id,
            Checkout.id == checkout_id,
        )
        .with_for_update()
    )
    if checkout is None:
        raise RetryablePaymentEvent("CHECKOUT_NOT_FOUND")
    if checkout.provider != event.provider:
        raise PermanentPaymentEvent("CHECKOUT_PROVIDER_MISMATCH")
    return checkout


def _event_money(
    event: PaymentEvent,
    *,
    supported_currencies: frozenset[str],
) -> tuple[str, int, str]:
    data = _event_data(event)
    try:
        provider_payment_id = _identifier(data["payment_id"], field="payment_id")
        amount_minor = _minor_amount(data["amount_minor"])
        currency = _currency(data["currency"], supported_currencies)
    except KeyError as exc:
        raise PermanentPaymentEvent("PAYMENT_EVENT_MONEY_MISSING") from exc
    except PaymentWebhookError as exc:
        raise PermanentPaymentEvent(exc.code) from exc
    return provider_payment_id, amount_minor, currency


async def _payment_for_event(
    session: AsyncSession,
    *,
    event: PaymentEvent,
    checkout: Checkout,
    supported_currencies: frozenset[str],
) -> tuple[Payment, int, str]:
    provider_payment_id, event_amount, event_currency = _event_money(
        event,
        supported_currencies=supported_currencies,
    )
    payment = await session.scalar(
        select(Payment)
        .where(
            Payment.provider == event.provider,
            Payment.provider_payment_id == provider_payment_id,
        )
        .with_for_update()
    )
    if payment is None:
        payment = Payment(
            tenant_id=event.tenant_id,
            checkout_id=checkout.id,
            provider=event.provider,
            provider_payment_id=provider_payment_id,
            amount_minor=checkout.amount_minor,
            currency=checkout.currency,
            credits=checkout.credits,
            status="pending",
        )
        session.add(payment)
        await session.flush()
    if (
        payment.tenant_id != event.tenant_id
        or payment.checkout_id != checkout.id
        or payment.amount_minor != checkout.amount_minor
        or payment.currency != checkout.currency
        or Decimal(payment.credits) != Decimal(checkout.credits)
    ):
        raise PermanentPaymentEvent("PAYMENT_IDENTITY_MISMATCH")
    return payment, event_amount, event_currency


def _credits_for_minor(payment: Payment, amount_minor: int) -> Decimal:
    if amount_minor >= payment.amount_minor:
        return Decimal(payment.credits)
    return (
        Decimal(payment.credits) * Decimal(amount_minor) / Decimal(payment.amount_minor)
    ).quantize(_CREDIT_QUANTUM, rounding=ROUND_DOWN)


async def _locked_credit_account(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
) -> CreditAccount:
    account = await session.scalar(
        select(CreditAccount).where(CreditAccount.tenant_id == tenant_id).with_for_update()
    )
    if account is None:
        account = CreditAccount(tenant_id=tenant_id)
        session.add(account)
        await session.flush()
    return account


def _available(account: CreditAccount) -> Decimal:
    return max(
        Decimal("0"),
        Decimal(account.balance) - Decimal(account.reserved),
    )


async def _existing_reversal(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    operation_key: str,
) -> Reversal | None:
    return cast(
        Reversal | None,
        await session.scalar(
            select(Reversal).where(
                Reversal.tenant_id == tenant_id,
                Reversal.operation_key == operation_key,
            )
        ),
    )


async def _append_reversal(
    session: AsyncSession,
    *,
    payment: Payment,
    operation_key: str,
    action: str,
    requested: Decimal,
    applied: Decimal,
    unrecovered_after: Decimal,
    refund: Refund | None = None,
    dispute: Dispute | None = None,
    event: PaymentEvent | None = None,
    ledger_entry_type: str | None = None,
    from_reserved: bool = False,
) -> Reversal:
    existing = await _existing_reversal(
        session,
        tenant_id=payment.tenant_id,
        operation_key=operation_key,
    )
    if existing is not None:
        return existing
    ledger = None
    if applied > 0:
        if ledger_entry_type is None:
            raise RuntimeError("ledger_entry_type_required")
        ledger = await credit_entry(
            session,
            tenant_id=payment.tenant_id,
            operation_key=f"{operation_key}:ledger",
            entry_type=ledger_entry_type,
            credits=applied,
            metadata={
                "payment_id": str(payment.id),
                "payment_adjustment": action,
                "from_reserved": from_reserved,
            },
        )
    reversal = Reversal(
        tenant_id=payment.tenant_id,
        payment_id=payment.id,
        refund_id=refund.id if refund else None,
        dispute_id=dispute.id if dispute else None,
        payment_event_id=event.id if event else None,
        credit_ledger_id=ledger.id if ledger else None,
        operation_key=operation_key,
        action=action,
        requested_credits=requested,
        applied_credits=applied,
        unrecovered_after=unrecovered_after,
    )
    session.add(reversal)
    await session.flush()
    return reversal


async def _grant_payment_credits(
    session: AsyncSession,
    *,
    payment: Payment,
    event: PaymentEvent,
) -> CreditGrant:
    existing = await session.scalar(
        select(CreditGrant).where(
            CreditGrant.tenant_id == payment.tenant_id,
            CreditGrant.payment_id == payment.id,
        )
    )
    if existing is not None:
        return existing
    operation_key = f"payment:{payment.id}:credit-grant"
    ledger = await credit_entry(
        session,
        tenant_id=payment.tenant_id,
        operation_key=operation_key,
        entry_type="grant",
        credits=Decimal(payment.credits),
        metadata={
            "payment_id": str(payment.id),
            "payment_event_id": str(event.id),
            "provider": payment.provider,
        },
    )
    grant = CreditGrant(
        tenant_id=payment.tenant_id,
        payment_id=payment.id,
        credit_ledger_id=ledger.id,
        operation_key=operation_key,
        credits=payment.credits,
    )
    session.add(grant)
    await session.flush()
    return grant


async def _latest_subject_outstanding(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    refund_id: uuid.UUID | None = None,
    dispute_id: uuid.UUID | None = None,
) -> Decimal:
    statement = select(Reversal).where(Reversal.tenant_id == tenant_id)
    if refund_id is not None:
        statement = statement.where(Reversal.refund_id == refund_id)
    elif dispute_id is not None:
        statement = statement.where(Reversal.dispute_id == dispute_id)
    else:
        raise ValueError("reversal subject required")
    row = await session.scalar(
        statement.order_by(Reversal.created_at.desc(), Reversal.id.desc()).limit(1)
    )
    return Decimal(row.unrecovered_after) if row else Decimal("0")


async def _apply_refund_adjustment(
    session: AsyncSession,
    *,
    payment: Payment,
    refund: Refund,
    event: PaymentEvent,
    requested: Decimal,
) -> None:
    account = await _locked_credit_account(session, tenant_id=payment.tenant_id)
    applied = min(requested, _available(account))
    outstanding = requested - applied
    await _append_reversal(
        session,
        payment=payment,
        refund=refund,
        event=event,
        operation_key=f"refund:{refund.id}:initial",
        action="refund",
        requested=requested,
        applied=applied,
        unrecovered_after=outstanding,
        ledger_entry_type="adjust" if applied > 0 else None,
    )
    refund.credits_requested = requested
    refund.credit_adjusted_at = utcnow()


async def _apply_pending_refunds(
    session: AsyncSession,
    *,
    payment: Payment,
) -> None:
    refunds = list(
        await session.scalars(
            select(Refund)
            .where(
                Refund.tenant_id == payment.tenant_id,
                Refund.payment_id == payment.id,
                Refund.status == "succeeded",
            )
            .order_by(Refund.created_at, Refund.id)
            .with_for_update()
        )
    )
    if not refunds:
        return
    events = {
        event.id: event
        for event in await session.scalars(
            select(PaymentEvent).where(
                PaymentEvent.tenant_id == payment.tenant_id,
                PaymentEvent.id.in_([refund.payment_event_id for refund in refunds]),
            )
        )
    }
    cumulative_minor = 0
    assigned = Decimal("0")
    for refund in refunds:
        cumulative_minor += refund.amount_minor
        if cumulative_minor > payment.amount_minor:
            raise PermanentPaymentEvent("REFUND_EXCEEDS_PAYMENT")
        target = _credits_for_minor(payment, cumulative_minor)
        requested = max(Decimal("0"), target - assigned)
        if refund.credit_adjusted_at is None:
            event = events.get(refund.payment_event_id)
            if event is None:
                raise PermanentPaymentEvent("REFUND_EVENT_MISSING")
            await _apply_refund_adjustment(
                session,
                payment=payment,
                refund=refund,
                event=event,
                requested=requested,
            )
        assigned += Decimal(refund.credits_requested)


async def _hold_open_dispute(
    session: AsyncSession,
    *,
    payment: Payment,
    dispute: Dispute,
    event: PaymentEvent | None,
    operation_suffix: str,
) -> None:
    if dispute.status != "open" or Decimal(dispute.held_credits) > 0:
        return
    grant = await session.scalar(
        select(CreditGrant).where(
            CreditGrant.tenant_id == payment.tenant_id,
            CreditGrant.payment_id == payment.id,
        )
    )
    if grant is None:
        dispute.outstanding_credits = dispute.requested_credits
        return
    account = await _locked_credit_account(session, tenant_id=payment.tenant_id)
    requested = Decimal(dispute.requested_credits)
    held = min(requested, _available(account))
    outstanding = requested - held
    await _append_reversal(
        session,
        payment=payment,
        dispute=dispute,
        event=event,
        operation_key=f"dispute:{dispute.id}:hold:{operation_suffix}",
        action="hold",
        requested=requested,
        applied=held,
        unrecovered_after=outstanding,
        ledger_entry_type="reserve" if held > 0 else None,
    )
    dispute.held_credits = held
    dispute.outstanding_credits = outstanding


async def _release_dispute_hold(
    session: AsyncSession,
    *,
    payment: Payment,
    dispute: Dispute,
    event: PaymentEvent,
) -> None:
    held = Decimal(dispute.held_credits)
    if held <= 0:
        dispute.outstanding_credits = Decimal("0")
        return
    await _append_reversal(
        session,
        payment=payment,
        dispute=dispute,
        event=event,
        operation_key=f"dispute:{dispute.id}:unhold",
        action="unhold",
        requested=held,
        applied=held,
        unrecovered_after=Decimal("0"),
        ledger_entry_type="release",
    )
    dispute.held_credits = Decimal("0")
    dispute.outstanding_credits = Decimal("0")


async def _chargeback_dispute(
    session: AsyncSession,
    *,
    payment: Payment,
    dispute: Dispute,
    event: PaymentEvent | None,
    operation_suffix: str,
) -> None:
    requested = Decimal(dispute.requested_credits)
    grant = await session.scalar(
        select(CreditGrant.id).where(
            CreditGrant.tenant_id == payment.tenant_id,
            CreditGrant.payment_id == payment.id,
        )
    )
    if grant is None:
        dispute.outstanding_credits = requested
        return
    reversed_before = Decimal(dispute.reversed_credits)
    remaining = max(Decimal("0"), requested - reversed_before)
    held = min(Decimal(dispute.held_credits), remaining)
    if held > 0:
        after_held = remaining - held
        await _append_reversal(
            session,
            payment=payment,
            dispute=dispute,
            event=event,
            operation_key=f"dispute:{dispute.id}:chargeback-held",
            action="chargeback",
            requested=remaining,
            applied=held,
            unrecovered_after=after_held,
            ledger_entry_type="adjust",
            from_reserved=True,
        )
        dispute.held_credits = Decimal("0")
        dispute.reversed_credits = reversed_before + held
        remaining = after_held
    if remaining > 0:
        account = await _locked_credit_account(
            session,
            tenant_id=payment.tenant_id,
        )
        applied = min(remaining, _available(account))
        outstanding = remaining - applied
        await _append_reversal(
            session,
            payment=payment,
            dispute=dispute,
            event=event,
            operation_key=(f"dispute:{dispute.id}:chargeback-available:{operation_suffix}"),
            action=("chargeback" if event is not None else "debt_recovery"),
            requested=remaining if event is not None else Decimal("0"),
            applied=applied,
            unrecovered_after=outstanding,
            ledger_entry_type="adjust" if applied > 0 else None,
        )
        dispute.reversed_credits = Decimal(dispute.reversed_credits) + applied
        remaining = outstanding
    dispute.outstanding_credits = remaining


async def _recover_refund_debt(
    session: AsyncSession,
    *,
    payment: Payment,
    refund: Refund,
    operation_suffix: str,
) -> Decimal:
    outstanding = await _latest_subject_outstanding(
        session,
        tenant_id=payment.tenant_id,
        refund_id=refund.id,
    )
    if outstanding <= 0:
        return Decimal("0")
    account = await _locked_credit_account(session, tenant_id=payment.tenant_id)
    applied = min(outstanding, _available(account))
    if applied <= 0:
        return outstanding
    after = outstanding - applied
    await _append_reversal(
        session,
        payment=payment,
        refund=refund,
        operation_key=f"refund:{refund.id}:recovery:{operation_suffix}",
        action="debt_recovery",
        requested=Decimal("0"),
        applied=applied,
        unrecovered_after=after,
        ledger_entry_type="adjust",
    )
    return after


async def _derive_payment_status(
    session: AsyncSession,
    *,
    payment: Payment,
) -> None:
    grant = await session.scalar(
        select(CreditGrant.id).where(
            CreditGrant.tenant_id == payment.tenant_id,
            CreditGrant.payment_id == payment.id,
        )
    )
    if grant is None:
        return
    disputes = list(
        await session.scalars(
            select(Dispute).where(
                Dispute.tenant_id == payment.tenant_id,
                Dispute.payment_id == payment.id,
            )
        )
    )
    if any(dispute.status == "lost" for dispute in disputes):
        payment.status = "charged_back"
        return
    if any(dispute.status == "open" for dispute in disputes):
        payment.status = "disputed"
        return
    refunded_minor = int(
        await session.scalar(
            select(func.coalesce(func.sum(Refund.amount_minor), 0)).where(
                Refund.tenant_id == payment.tenant_id,
                Refund.payment_id == payment.id,
                Refund.status == "succeeded",
            )
        )
        or 0
    )
    if refunded_minor >= payment.amount_minor:
        payment.status = "refunded"
    elif refunded_minor > 0:
        payment.status = "partially_refunded"
    else:
        payment.status = "succeeded"


async def _post_grant_adjustments(
    session: AsyncSession,
    *,
    payment: Payment,
    grant: CreditGrant,
) -> None:
    await _apply_pending_refunds(session, payment=payment)
    disputes = list(
        await session.scalars(
            select(Dispute)
            .where(
                Dispute.tenant_id == payment.tenant_id,
                Dispute.payment_id == payment.id,
            )
            .with_for_update()
        )
    )
    for dispute in disputes:
        if dispute.status == "open":
            await _hold_open_dispute(
                session,
                payment=payment,
                dispute=dispute,
                event=None,
                operation_suffix=f"grant-{grant.id}",
            )
        elif dispute.status == "lost" and Decimal(dispute.outstanding_credits) > 0:
            await _chargeback_dispute(
                session,
                payment=payment,
                dispute=dispute,
                event=None,
                operation_suffix=f"grant-{grant.id}",
            )


async def _handle_payment_succeeded(
    session: AsyncSession,
    *,
    event: PaymentEvent,
    settings: Settings,
) -> None:
    checkout = await _checkout_for_event(session, event)
    payment, event_amount, event_currency = await _payment_for_event(
        session,
        event=event,
        checkout=checkout,
        supported_currencies=settings.supported_payment_currencies,
    )
    if event_amount != checkout.amount_minor or event_currency != checkout.currency:
        raise PermanentPaymentEvent("PAYMENT_AMOUNT_OR_CURRENCY_MISMATCH")
    grant = await _grant_payment_credits(session, payment=payment, event=event)
    payment.paid_at = payment.paid_at or event.provider_created_at
    checkout.status = "completed"
    checkout.completed_at = checkout.completed_at or event.provider_created_at
    await _post_grant_adjustments(session, payment=payment, grant=grant)
    await _derive_payment_status(session, payment=payment)
    await audit(
        session,
        tenant_id=payment.tenant_id,
        actor_id=None,
        action="billing.payment.settled",
        target_type="payment",
        target_id=str(payment.id),
        metadata={
            "provider": payment.provider,
            "amount_minor": payment.amount_minor,
            "currency": payment.currency,
            "credits": str(payment.credits),
        },
    )


async def _handle_payment_failed(
    session: AsyncSession,
    *,
    event: PaymentEvent,
    settings: Settings,
) -> None:
    checkout = await _checkout_for_event(session, event)
    payment, event_amount, event_currency = await _payment_for_event(
        session,
        event=event,
        checkout=checkout,
        supported_currencies=settings.supported_payment_currencies,
    )
    if event_amount != checkout.amount_minor or event_currency != checkout.currency:
        raise PermanentPaymentEvent("PAYMENT_AMOUNT_OR_CURRENCY_MISMATCH")
    grant = await session.scalar(
        select(CreditGrant.id).where(
            CreditGrant.tenant_id == payment.tenant_id,
            CreditGrant.payment_id == payment.id,
        )
    )
    if grant is None and payment.status == "pending":
        payment.status = "failed"


async def _adverse_minor_total(
    session: AsyncSession,
    *,
    payment: Payment,
    include_refund: int = 0,
    include_lost_dispute: int = 0,
    exclude_dispute_id: uuid.UUID | None = None,
) -> int:
    refunded = int(
        await session.scalar(
            select(func.coalesce(func.sum(Refund.amount_minor), 0)).where(
                Refund.tenant_id == payment.tenant_id,
                Refund.payment_id == payment.id,
                Refund.status == "succeeded",
            )
        )
        or 0
    )
    dispute_statement = select(func.coalesce(func.sum(Dispute.amount_minor), 0)).where(
        Dispute.tenant_id == payment.tenant_id,
        Dispute.payment_id == payment.id,
        Dispute.status == "lost",
    )
    if exclude_dispute_id is not None:
        dispute_statement = dispute_statement.where(Dispute.id != exclude_dispute_id)
    lost = int(await session.scalar(dispute_statement) or 0)
    return refunded + lost + include_refund + include_lost_dispute


async def _handle_refund(
    session: AsyncSession,
    *,
    event: PaymentEvent,
    settings: Settings,
) -> None:
    checkout = await _checkout_for_event(session, event)
    payment, amount_minor, currency = await _payment_for_event(
        session,
        event=event,
        checkout=checkout,
        supported_currencies=settings.supported_payment_currencies,
    )
    if currency != payment.currency:
        raise PermanentPaymentEvent("REFUND_CURRENCY_MISMATCH")
    data = _event_data(event)
    try:
        provider_refund_id = _identifier(data["refund_id"], field="refund_id")
    except (KeyError, PaymentWebhookError) as exc:
        raise PermanentPaymentEvent("REFUND_ID_INVALID") from exc
    existing = await session.scalar(
        select(Refund).where(
            Refund.provider == event.provider,
            Refund.provider_refund_id == provider_refund_id,
        )
    )
    if existing is not None:
        if (
            existing.payment_id != payment.id
            or existing.amount_minor != amount_minor
            or existing.currency != currency
        ):
            raise PermanentPaymentEvent("REFUND_IDENTITY_MISMATCH")
        return
    adverse_total = await _adverse_minor_total(
        session,
        payment=payment,
        include_refund=amount_minor,
    )
    if adverse_total > payment.amount_minor:
        raise PermanentPaymentEvent("REFUND_EXCEEDS_PAYMENT")
    refund = Refund(
        tenant_id=payment.tenant_id,
        payment_id=payment.id,
        payment_event_id=event.id,
        provider=event.provider,
        provider_refund_id=provider_refund_id,
        amount_minor=amount_minor,
        currency=currency,
        status="succeeded",
    )
    session.add(refund)
    await session.flush()
    grant = await session.scalar(
        select(CreditGrant).where(
            CreditGrant.tenant_id == payment.tenant_id,
            CreditGrant.payment_id == payment.id,
        )
    )
    if grant is not None:
        await _apply_pending_refunds(session, payment=payment)
        await _derive_payment_status(session, payment=payment)
    await audit(
        session,
        tenant_id=payment.tenant_id,
        actor_id=None,
        action="billing.refund.recorded",
        target_type="payment_refund",
        target_id=str(refund.id),
        metadata={
            "amount_minor": amount_minor,
            "currency": currency,
        },
    )


async def _dispute_for_event(
    session: AsyncSession,
    *,
    payment: Payment,
    event: PaymentEvent,
    amount_minor: int,
    currency: str,
) -> Dispute:
    data = _event_data(event)
    try:
        provider_dispute_id = _identifier(
            data["dispute_id"],
            field="dispute_id",
        )
    except (KeyError, PaymentWebhookError) as exc:
        raise PermanentPaymentEvent("DISPUTE_ID_INVALID") from exc
    dispute = await session.scalar(
        select(Dispute)
        .where(
            Dispute.provider == event.provider,
            Dispute.provider_dispute_id == provider_dispute_id,
        )
        .with_for_update()
    )
    if dispute is None:
        dispute = Dispute(
            tenant_id=payment.tenant_id,
            payment_id=payment.id,
            provider=event.provider,
            provider_dispute_id=provider_dispute_id,
            amount_minor=amount_minor,
            currency=currency,
            status="open",
            requested_credits=_credits_for_minor(payment, amount_minor),
            opened_at=event.provider_created_at,
            last_event_created_at=event.provider_created_at,
        )
        session.add(dispute)
        await session.flush()
    elif (
        dispute.tenant_id != payment.tenant_id
        or dispute.payment_id != payment.id
        or dispute.amount_minor != amount_minor
        or dispute.currency != currency
    ):
        raise PermanentPaymentEvent("DISPUTE_IDENTITY_MISMATCH")
    return dispute


async def _handle_dispute(
    session: AsyncSession,
    *,
    event: PaymentEvent,
    settings: Settings,
) -> None:
    checkout = await _checkout_for_event(session, event)
    payment, amount_minor, currency = await _payment_for_event(
        session,
        event=event,
        checkout=checkout,
        supported_currencies=settings.supported_payment_currencies,
    )
    if currency != payment.currency or amount_minor > payment.amount_minor:
        raise PermanentPaymentEvent("DISPUTE_AMOUNT_OR_CURRENCY_MISMATCH")
    dispute = await _dispute_for_event(
        session,
        payment=payment,
        event=event,
        amount_minor=amount_minor,
        currency=currency,
    )
    if _aware(event.provider_created_at) < _aware(dispute.last_event_created_at):
        return
    state = event.event_type.rsplit(".", 1)[-1]
    if state == "opened":
        if dispute.status in {"won", "lost", "closed"}:
            return
        dispute.status = "open"
        await _hold_open_dispute(
            session,
            payment=payment,
            dispute=dispute,
            event=event,
            operation_suffix=f"event-{event.id}",
        )
    elif state == "won":
        if dispute.status == "lost":
            return
        await _release_dispute_hold(
            session,
            payment=payment,
            dispute=dispute,
            event=event,
        )
        dispute.status = "won"
        dispute.resolved_at = event.provider_created_at
    elif state == "lost":
        if dispute.status == "won":
            return
        adverse_total = await _adverse_minor_total(
            session,
            payment=payment,
            include_lost_dispute=amount_minor,
            exclude_dispute_id=dispute.id,
        )
        if adverse_total > payment.amount_minor:
            raise PermanentPaymentEvent("DISPUTE_EXCEEDS_PAYMENT")
        dispute.status = "lost"
        dispute.resolved_at = event.provider_created_at
        await _chargeback_dispute(
            session,
            payment=payment,
            dispute=dispute,
            event=event,
            operation_suffix=f"event-{event.id}",
        )
    dispute.last_event_created_at = event.provider_created_at
    await _derive_payment_status(session, payment=payment)
    await audit(
        session,
        tenant_id=payment.tenant_id,
        actor_id=None,
        action=f"billing.dispute.{state}",
        target_type="payment_dispute",
        target_id=str(dispute.id),
        metadata={
            "amount_minor": amount_minor,
            "currency": currency,
            "held_credits": str(dispute.held_credits),
            "outstanding_credits": str(dispute.outstanding_credits),
        },
    )


async def _process_payment_event(
    session: AsyncSession,
    *,
    event: PaymentEvent,
    settings: Settings,
) -> None:
    if event.event_type == "checkout.expired":
        checkout = await _checkout_for_event(session, event)
        if checkout.status not in {"completed", "cancelled"}:
            checkout.status = "expired"
        return
    if event.event_type == "payment.succeeded":
        await _handle_payment_succeeded(session, event=event, settings=settings)
        return
    if event.event_type == "payment.failed":
        await _handle_payment_failed(session, event=event, settings=settings)
        return
    if event.event_type == "payment.refunded":
        await _handle_refund(session, event=event, settings=settings)
        return
    if event.event_type.startswith("payment.dispute."):
        await _handle_dispute(session, event=event, settings=settings)
        return
    event.status = "ignored"
    event.processed_at = utcnow()


async def attempt_payment_event(
    session: AsyncSession,
    *,
    event: PaymentEvent,
    settings: Settings,
) -> str:
    if event.status in {"processed", "ignored"}:
        return event.status
    event.attempts += 1
    try:
        async with session.begin_nested():
            await _process_payment_event(session, event=event, settings=settings)
    except PermanentPaymentEvent as exc:
        event.status = "dead_letter"
        event.last_error_code = exc.code
        event.dead_lettered_at = utcnow()
        await audit(
            session,
            tenant_id=event.tenant_id,
            actor_id=None,
            action="billing.payment_event.dead_lettered",
            target_type="payment_event",
            target_id=str(event.id),
            metadata={"code": exc.code, "event_type": event.event_type},
        )
    except RetryablePaymentEvent as exc:
        event.last_error_code = exc.code
        if event.attempts >= settings.payment_event_max_attempts:
            event.status = "dead_letter"
            event.dead_lettered_at = utcnow()
            await audit(
                session,
                tenant_id=event.tenant_id,
                actor_id=None,
                action="billing.payment_event.dead_lettered",
                target_type="payment_event",
                target_id=str(event.id),
                metadata={"code": exc.code, "event_type": event.event_type},
            )
        else:
            event.status = "retry"
            event.next_attempt_at = utcnow() + timedelta(
                seconds=settings.payment_event_retry_seconds
            )
    except Exception:
        event.last_error_code = "PAYMENT_EVENT_PROCESSING_FAILED"
        if event.attempts >= settings.payment_event_max_attempts:
            event.status = "dead_letter"
            event.dead_lettered_at = utcnow()
            await audit(
                session,
                tenant_id=event.tenant_id,
                actor_id=None,
                action="billing.payment_event.dead_lettered",
                target_type="payment_event",
                target_id=str(event.id),
                metadata={
                    "code": event.last_error_code,
                    "event_type": event.event_type,
                },
            )
        else:
            event.status = "retry"
            event.next_attempt_at = utcnow() + timedelta(
                seconds=settings.payment_event_retry_seconds
            )
    else:
        if event.status != "ignored":
            event.status = "processed"
        event.last_error_code = None
        event.processed_at = utcnow()
    await session.flush()
    return event.status


async def ingest_payment_event(
    session: AsyncSession,
    *,
    provider: str,
    parsed: ParsedPaymentEvent,
    raw_body: bytes,
    settings: Settings,
) -> PaymentEventReceipt:
    payload_sha256 = hashlib.sha256(raw_body).hexdigest()
    existing = await session.scalar(
        select(PaymentEvent)
        .where(
            PaymentEvent.provider == provider,
            PaymentEvent.provider_event_id == parsed.provider_event_id,
        )
        .with_for_update()
    )
    if existing is not None:
        if existing.payload_sha256 != payload_sha256:
            raise PaymentWebhookError(
                "PAYMENT_WEBHOOK_EVENT_ID_COLLISION",
                status_code=409,
            )
        return PaymentEventReceipt(event=existing, duplicate=True)
    event = PaymentEvent(
        tenant_id=parsed.tenant_id,
        provider=provider,
        provider_event_id=parsed.provider_event_id,
        event_type=parsed.event_type,
        provider_created_at=parsed.provider_created_at,
        payload_sha256=payload_sha256,
        payload_json=parsed.payload,
        status="pending",
        next_attempt_at=utcnow(),
    )
    session.add(event)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        await set_rls_context(session, tenant_id=parsed.tenant_id)
        concurrent = await session.scalar(
            select(PaymentEvent).where(
                PaymentEvent.provider == provider,
                PaymentEvent.provider_event_id == parsed.provider_event_id,
            )
        )
        if concurrent is None or concurrent.payload_sha256 != payload_sha256:
            raise PaymentWebhookError(
                "PAYMENT_WEBHOOK_EVENT_ID_COLLISION",
                status_code=409,
            ) from None
        return PaymentEventReceipt(event=concurrent, duplicate=True)
    await attempt_payment_event(
        session,
        event=event,
        settings=settings,
    )
    return PaymentEventReceipt(event=event, duplicate=False)


async def retry_payment_event(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    event_id: uuid.UUID,
    actor_id: uuid.UUID,
    settings: Settings,
) -> PaymentEvent:
    event = await session.scalar(
        select(PaymentEvent)
        .where(
            PaymentEvent.tenant_id == tenant_id,
            PaymentEvent.id == event_id,
        )
        .with_for_update()
    )
    if event is None:
        raise LookupError("payment_event_not_found")
    if event.status not in {"retry", "dead_letter"}:
        return event
    event.status = "retry"
    event.next_attempt_at = utcnow()
    event.dead_lettered_at = None
    event.last_error_code = None
    await attempt_payment_event(session, event=event, settings=settings)
    await audit(
        session,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="billing.payment_event.retried",
        target_type="payment_event",
        target_id=str(event.id),
        metadata={"status": event.status},
    )
    return event


async def _outstanding_refund_total(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    refunds: Iterable[Refund],
) -> Decimal:
    total = Decimal("0")
    for refund in refunds:
        total += await _latest_subject_outstanding(
            session,
            tenant_id=tenant_id,
            refund_id=refund.id,
        )
    return total


async def reconcile_payments(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    actor_id: uuid.UUID | None,
    provider: str,
    settings: Settings,
) -> Reconciliation:
    run = Reconciliation(
        tenant_id=tenant_id,
        provider=provider,
        status="running",
        created_by=actor_id,
    )
    session.add(run)
    await session.flush()
    due_statement = (
        select(PaymentEvent)
        .where(
            PaymentEvent.tenant_id == tenant_id,
            PaymentEvent.provider == provider,
            PaymentEvent.status.in_(("pending", "retry")),
            PaymentEvent.next_attempt_at <= utcnow(),
        )
        .order_by(
            PaymentEvent.provider_created_at,
            PaymentEvent.received_at,
            PaymentEvent.id,
        )
        .limit(settings.payment_reconciliation_batch_size)
    )
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        due_statement = due_statement.with_for_update(skip_locked=True)
    due = list(await session.scalars(due_statement))
    run.events_scanned = len(due)
    for event in due:
        before = event.status
        status = await attempt_payment_event(
            session,
            event=event,
            settings=settings,
        )
        if status in {"processed", "ignored"}:
            run.events_processed += 1
        elif status == "retry":
            run.events_retried += 1
        elif status == "dead_letter":
            run.events_dead_lettered += 1
        if before == status == "retry":
            run.events_retried += 0

    settled_payments = list(
        await session.scalars(
            select(Payment)
            .where(
                Payment.tenant_id == tenant_id,
                Payment.provider == provider,
                Payment.paid_at.is_not(None),
            )
            .with_for_update()
        )
    )
    for payment in settled_payments:
        grant = await session.scalar(
            select(CreditGrant).where(
                CreditGrant.tenant_id == tenant_id,
                CreditGrant.payment_id == payment.id,
            )
        )
        if grant is None:
            run.mismatches += 1
            source_event = await session.scalar(
                select(PaymentEvent)
                .where(
                    PaymentEvent.tenant_id == tenant_id,
                    PaymentEvent.provider == provider,
                    PaymentEvent.event_type == "payment.succeeded",
                    PaymentEvent.payload_json["data"]["payment_id"].as_string()
                    == payment.provider_payment_id,
                )
                .order_by(PaymentEvent.provider_created_at, PaymentEvent.id)
            )
            if source_event is not None:
                grant = await _grant_payment_credits(
                    session,
                    payment=payment,
                    event=source_event,
                )
                run.repaired += 1
        if grant is not None:
            await _post_grant_adjustments(
                session,
                payment=payment,
                grant=grant,
            )
            await _derive_payment_status(session, payment=payment)

    refunds = list(
        await session.scalars(
            select(Refund).where(
                Refund.tenant_id == tenant_id,
                Refund.provider == provider,
                Refund.credit_adjusted_at.is_not(None),
            )
        )
    )
    for refund in refunds:
        refund_payment = await session.scalar(
            select(Payment).where(
                Payment.tenant_id == tenant_id,
                Payment.id == refund.payment_id,
            )
        )
        if refund_payment is not None:
            outstanding_before = await _latest_subject_outstanding(
                session,
                tenant_id=tenant_id,
                refund_id=refund.id,
            )
            after = await _recover_refund_debt(
                session,
                payment=refund_payment,
                refund=refund,
                operation_suffix=f"reconciliation-{run.id}",
            )
            if after < outstanding_before:
                run.repaired += 1
    disputes = list(
        await session.scalars(
            select(Dispute).where(
                Dispute.tenant_id == tenant_id,
                Dispute.provider == provider,
                Dispute.status == "lost",
                Dispute.outstanding_credits > 0,
            )
        )
    )
    for dispute in disputes:
        dispute_payment = await session.scalar(
            select(Payment).where(
                Payment.tenant_id == tenant_id,
                Payment.id == dispute.payment_id,
            )
        )
        if dispute_payment is not None:
            outstanding_before = Decimal(dispute.outstanding_credits)
            await _chargeback_dispute(
                session,
                payment=dispute_payment,
                dispute=dispute,
                event=None,
                operation_suffix=f"reconciliation-{run.id}",
            )
            if Decimal(dispute.outstanding_credits) < outstanding_before:
                run.repaired += 1

    run.outstanding_credits = await _outstanding_refund_total(
        session,
        tenant_id=tenant_id,
        refunds=refunds,
    ) + sum(
        (Decimal(dispute.outstanding_credits) for dispute in disputes),
        Decimal("0"),
    )
    run.status = "completed"
    run.completed_at = utcnow()
    await audit(
        session,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="billing.reconciliation.completed",
        target_type="payment_reconciliation",
        target_id=str(run.id),
        metadata={
            "provider": provider,
            "events_scanned": run.events_scanned,
            "events_dead_lettered": run.events_dead_lettered,
            "mismatches": run.mismatches,
            "repaired": run.repaired,
            "outstanding_credits": str(run.outstanding_credits),
        },
    )
    await session.flush()
    return run
