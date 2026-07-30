"""Financial-integrity evidence for payment-backed credit purchases."""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import AsyncIterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
import pytest_asyncio
from akc_api.main import create_app
from akc_api.models import (
    AuditEvent,
    Checkout,
    CreditAccount,
    CreditGrant,
    CreditLedger,
    Dispute,
    Payment,
    PaymentEvent,
    Reconciliation,
    Refund,
    Reversal,
)
from akc_api.payments import payment_webhook_signature
from akc_api.services import credit_entry
from akc_api.settings import Settings
from pydantic import ValidationError
from sqlalchemy import func, select

_SUPPORT_KEY = "payment-api-verification-support-key"
_WEBHOOK_SECRET = "payment-test-webhook-secret-material-2026"  # noqa: S105


@pytest_asyncio.fixture
async def payment_api(
    tmp_path: Path,
) -> AsyncIterator[tuple[httpx.AsyncClient, Any]]:
    settings = Settings(
        env="test",
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'payments.db').as_posix()}",
        data_dir=tmp_path / "data",
        local_background_tasks=False,
        local_analysis_worker_enabled=False,
        clamav_enabled=False,
        allow_development_antivirus_bypass=True,
        test_support_key=_SUPPORT_KEY,
        payments_enabled=True,
        payment_provider="fake",
        payment_merchant_id="merchant_test",
        payment_webhook_secret=_WEBHOOK_SECRET,
        operation_account_limit=1000,
        operation_tenant_limit=1000,
    )
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=True)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            yield client, app


async def _register_verified(
    client: httpx.AsyncClient,
    *,
    email: str = "billing-owner@example.test",
) -> dict[str, Any]:
    registered = await client.post(
        "/v1/auth/register",
        json={
            "email": email,
            "password": "correct horse battery staple",
            "display_name": "Billing Owner",
            "tenant_name": f"Billing {uuid.uuid4()}",
        },
    )
    assert registered.status_code == 201, registered.text
    captured = await client.post(
        "/__test__/verification-token",
        headers={"X-AKC-Test-Support-Key": _SUPPORT_KEY},
        json={"email": email},
    )
    assert captured.status_code == 200, captured.text
    verified = await client.post(
        "/v1/auth/verify-email",
        json={"token": captured.json()["token"]},
    )
    assert verified.status_code == 200, verified.text
    return verified.json()


async def _checkout(client: httpx.AsyncClient, *, pack_code: str = "starter_krw") -> dict[str, Any]:
    response = await client.post(
        "/v1/billing/checkouts",
        headers={"Idempotency-Key": f"checkout-{uuid.uuid4()}"},
        json={"pack_code": pack_code},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _event(
    *,
    event_id: str,
    event_type: str,
    tenant_id: str,
    checkout_id: str,
    payment_id: str = "pay_test_001",
    amount_minor: int = 4_900,
    currency: str = "KRW",
    refund_id: str | None = None,
    dispute_id: str | None = None,
    created: int | None = None,
) -> bytes:
    data: dict[str, Any] = {
        "tenant_id": tenant_id,
        "checkout_id": checkout_id,
    }
    if event_type != "checkout.expired":
        data.update(
            {
                "payment_id": payment_id,
                "amount_minor": amount_minor,
                "currency": currency,
            }
        )
    if refund_id is not None:
        data["refund_id"] = refund_id
    if dispute_id is not None:
        data["dispute_id"] = dispute_id
    return json.dumps(
        {
            "id": event_id,
            "type": event_type,
            "created": created or int(time.time()),
            "data": data,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


async def _send_event(
    client: httpx.AsyncClient,
    body: bytes,
    *,
    timestamp: int | None = None,
    secret: str = _WEBHOOK_SECRET,
) -> httpx.Response:
    signed_at = timestamp or int(time.time())
    return await client.post(
        "/v1/payments/webhooks/fake",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Payment-Timestamp": str(signed_at),
            "X-Payment-Signature": payment_webhook_signature(
                secret,
                timestamp=signed_at,
                raw_body=body,
            ),
        },
    )


async def _settle(
    client: httpx.AsyncClient,
    *,
    registration: dict[str, Any],
    checkout: dict[str, Any],
    payment_id: str = "pay_test_001",
    event_id: str = "evt_payment_succeeded_001",
) -> httpx.Response:
    return await _send_event(
        client,
        _event(
            event_id=event_id,
            event_type="payment.succeeded",
            tenant_id=registration["tenant_id"],
            checkout_id=checkout["id"],
            payment_id=payment_id,
            amount_minor=checkout["amount_minor"],
            currency=checkout["currency"],
        ),
    )


async def test_purchase_confirmation_grants_append_only_credit_exactly_once(
    payment_api: tuple[httpx.AsyncClient, Any],
) -> None:
    client, app = payment_api
    registration = await _register_verified(client)
    checkout = await _checkout(client)
    assert checkout["amount_minor"] == 4_900
    assert checkout["currency"] == "KRW"
    assert Decimal(checkout["credits"]) == Decimal("300")
    assert checkout["status"] == "open"
    assert checkout["checkout_url"].startswith("http://localhost:3000/")

    body = _event(
        event_id="evt_payment_succeeded_exactly_once",
        event_type="payment.succeeded",
        tenant_id=registration["tenant_id"],
        checkout_id=checkout["id"],
        payment_id="pay_exactly_once",
    )
    first = await _send_event(client, body)
    duplicate = await _send_event(client, body)
    second_provider_event = await _send_event(
        client,
        _event(
            event_id="evt_payment_succeeded_same_payment",
            event_type="payment.succeeded",
            tenant_id=registration["tenant_id"],
            checkout_id=checkout["id"],
            payment_id="pay_exactly_once",
        ),
    )
    assert first.status_code == 202, first.text
    assert first.json()["duplicate"] is False
    assert duplicate.status_code == 202, duplicate.text
    assert duplicate.json()["duplicate"] is True
    assert second_provider_event.status_code == 202, second_provider_event.text

    tenant_id = uuid.UUID(registration["tenant_id"])
    async with app.state.database.sessions() as session:
        account = await session.get(CreditAccount, tenant_id)
        grants = list(
            await session.scalars(select(CreditGrant).where(CreditGrant.tenant_id == tenant_id))
        )
        payment = await session.scalar(select(Payment).where(Payment.tenant_id == tenant_id))
        checkout_row = await session.get(Checkout, uuid.UUID(checkout["id"]))
        purchase_ledger_count = await session.scalar(
            select(func.count(CreditLedger.id)).where(
                CreditLedger.tenant_id == tenant_id,
                CreditLedger.operation_key.like("payment:%:credit-grant"),
            )
        )
    assert account is not None
    assert account.balance == Decimal("350")
    assert len(grants) == 1
    assert purchase_ledger_count == 1
    assert payment is not None and payment.status == "succeeded"
    assert checkout_row is not None and checkout_row.status == "completed"


async def test_signature_timestamp_and_event_id_collision_are_rejected(
    payment_api: tuple[httpx.AsyncClient, Any],
) -> None:
    client, app = payment_api
    registration = await _register_verified(client, email="signature@example.test")
    checkout = await _checkout(client)
    body = _event(
        event_id="evt_signature_guard",
        event_type="payment.failed",
        tenant_id=registration["tenant_id"],
        checkout_id=checkout["id"],
        payment_id="pay_signature_guard",
    )
    invalid = await _send_event(client, body, secret="x" * 40)
    expired = await _send_event(
        client,
        body,
        timestamp=int(time.time()) - 1_000,
    )
    accepted = await _send_event(client, body)
    collision_body = _event(
        event_id="evt_signature_guard",
        event_type="payment.failed",
        tenant_id=registration["tenant_id"],
        checkout_id=checkout["id"],
        payment_id="pay_signature_guard",
        amount_minor=4_899,
    )
    collision = await _send_event(client, collision_body)

    assert invalid.status_code == 401
    assert invalid.json()["error"]["code"] == "PAYMENT_WEBHOOK_SIGNATURE_INVALID"
    assert expired.status_code == 401
    assert expired.json()["error"]["code"] == "PAYMENT_WEBHOOK_TIMESTAMP_EXPIRED"
    assert accepted.status_code == 202
    assert collision.status_code == 409
    assert collision.json()["error"]["code"] == "PAYMENT_WEBHOOK_EVENT_ID_COLLISION"
    async with app.state.database.sessions() as session:
        count = await session.scalar(select(func.count(PaymentEvent.id)))
    assert count == 1


async def test_out_of_order_full_refund_is_applied_after_payment_confirmation(
    payment_api: tuple[httpx.AsyncClient, Any],
) -> None:
    client, app = payment_api
    registration = await _register_verified(client, email="ordering@example.test")
    checkout = await _checkout(client)
    refunded_first = await _send_event(
        client,
        _event(
            event_id="evt_refund_before_payment",
            event_type="payment.refunded",
            tenant_id=registration["tenant_id"],
            checkout_id=checkout["id"],
            payment_id="pay_out_of_order",
            refund_id="refund_out_of_order",
        ),
    )
    settled_later = await _settle(
        client,
        registration=registration,
        checkout=checkout,
        payment_id="pay_out_of_order",
        event_id="evt_success_after_refund",
    )
    assert refunded_first.status_code == 202, refunded_first.text
    assert settled_later.status_code == 202, settled_later.text

    tenant_id = uuid.UUID(registration["tenant_id"])
    async with app.state.database.sessions() as session:
        account = await session.get(CreditAccount, tenant_id)
        payment = await session.scalar(select(Payment).where(Payment.tenant_id == tenant_id))
        refund = await session.scalar(select(Refund).where(Refund.tenant_id == tenant_id))
        reversal = await session.scalar(
            select(Reversal).where(
                Reversal.tenant_id == tenant_id,
                Reversal.action == "refund",
            )
        )
    assert account is not None and account.balance == Decimal("50")
    assert payment is not None and payment.status == "refunded"
    assert refund is not None and refund.credits_requested == Decimal("300")
    assert reversal is not None
    assert reversal.applied_credits == Decimal("300")
    assert reversal.unrecovered_after == Decimal("0")


async def test_refund_never_makes_balance_negative_and_reconciliation_recovers_debt(
    payment_api: tuple[httpx.AsyncClient, Any],
) -> None:
    client, app = payment_api
    registration = await _register_verified(client, email="refund-floor@example.test")
    checkout = await _checkout(client)
    settled = await _settle(
        client,
        registration=registration,
        checkout=checkout,
        payment_id="pay_refund_floor",
        event_id="evt_refund_floor_success",
    )
    assert settled.status_code == 202, settled.text
    tenant_id = uuid.UUID(registration["tenant_id"])
    async with app.state.database.sessions() as session:
        await credit_entry(
            session,
            tenant_id=tenant_id,
            operation_key="test:spend:reserve",
            entry_type="reserve",
            credits=Decimal("340"),
        )
        await credit_entry(
            session,
            tenant_id=tenant_id,
            operation_key="test:spend:consume",
            entry_type="consume",
            credits=Decimal("340"),
        )
        await session.commit()

    refunded = await _send_event(
        client,
        _event(
            event_id="evt_refund_floor_full",
            event_type="payment.refunded",
            tenant_id=registration["tenant_id"],
            checkout_id=checkout["id"],
            payment_id="pay_refund_floor",
            refund_id="refund_floor_full",
        ),
    )
    assert refunded.status_code == 202, refunded.text
    async with app.state.database.sessions() as session:
        account = await session.get(CreditAccount, tenant_id)
        initial_reversal = await session.scalar(
            select(Reversal).where(
                Reversal.tenant_id == tenant_id,
                Reversal.action == "refund",
            )
        )
        assert account is not None
        assert account.balance == Decimal("0")
        assert account.reserved == Decimal("0")
        assert initial_reversal is not None
        assert initial_reversal.applied_credits == Decimal("10")
        assert initial_reversal.unrecovered_after == Decimal("290")
        await credit_entry(
            session,
            tenant_id=tenant_id,
            operation_key="test:future-credit",
            entry_type="grant",
            credits=Decimal("40"),
        )
        await session.commit()

    reconciled = await client.post(
        "/v1/billing/reconciliations",
        headers={"Idempotency-Key": "refund-debt-reconciliation"},
    )
    assert reconciled.status_code == 201, reconciled.text
    assert reconciled.json()["repaired"] >= 1
    assert reconciled.json()["outstanding_credits"] == "250.000000"
    async with app.state.database.sessions() as session:
        account = await session.get(CreditAccount, tenant_id)
        reversals = list(
            await session.scalars(
                select(Reversal)
                .where(Reversal.tenant_id == tenant_id)
                .order_by(Reversal.created_at, Reversal.id)
            )
        )
        run = await session.scalar(
            select(Reconciliation).where(Reconciliation.tenant_id == tenant_id)
        )
    assert account is not None
    assert account.balance == Decimal("0")
    assert account.reserved == Decimal("0")
    assert reversals[-1].action == "debt_recovery"
    assert reversals[-1].applied_credits == Decimal("40")
    assert reversals[-1].unrecovered_after == Decimal("250")
    assert run is not None and run.status == "completed"


async def test_partial_refunds_use_cumulative_minor_units_without_rounding_drift(
    payment_api: tuple[httpx.AsyncClient, Any],
) -> None:
    client, app = payment_api
    registration = await _register_verified(client, email="partial-refund@example.test")
    checkout = await _checkout(client)
    settled = await _settle(
        client,
        registration=registration,
        checkout=checkout,
        payment_id="pay_partial_refunds",
        event_id="evt_partial_refunds_success",
    )
    assert settled.status_code == 202, settled.text
    for sequence in (1, 2):
        refunded = await _send_event(
            client,
            _event(
                event_id=f"evt_partial_refund_{sequence}",
                event_type="payment.refunded",
                tenant_id=registration["tenant_id"],
                checkout_id=checkout["id"],
                payment_id="pay_partial_refunds",
                refund_id=f"refund_partial_{sequence}",
                amount_minor=2_450,
            ),
        )
        assert refunded.status_code == 202, refunded.text

    tenant_id = uuid.UUID(registration["tenant_id"])
    async with app.state.database.sessions() as session:
        account = await session.get(CreditAccount, tenant_id)
        payment = await session.scalar(select(Payment).where(Payment.tenant_id == tenant_id))
        refunds = list(
            await session.scalars(
                select(Refund)
                .where(Refund.tenant_id == tenant_id)
                .order_by(Refund.created_at, Refund.id)
            )
        )
    assert account is not None and account.balance == Decimal("50")
    assert payment is not None and payment.status == "refunded"
    assert [row.credits_requested for row in refunds] == [
        Decimal("150"),
        Decimal("150"),
    ]


async def test_dispute_holds_then_chargeback_consumes_only_held_credits(
    payment_api: tuple[httpx.AsyncClient, Any],
) -> None:
    client, app = payment_api
    registration = await _register_verified(client, email="dispute@example.test")
    checkout = await _checkout(client)
    settled = await _settle(
        client,
        registration=registration,
        checkout=checkout,
        payment_id="pay_dispute",
        event_id="evt_dispute_success",
    )
    assert settled.status_code == 202
    opened = await _send_event(
        client,
        _event(
            event_id="evt_dispute_opened",
            event_type="payment.dispute.opened",
            tenant_id=registration["tenant_id"],
            checkout_id=checkout["id"],
            payment_id="pay_dispute",
            dispute_id="dispute_full",
        ),
    )
    assert opened.status_code == 202, opened.text
    tenant_id = uuid.UUID(registration["tenant_id"])
    async with app.state.database.sessions() as session:
        account = await session.get(CreditAccount, tenant_id)
        dispute = await session.scalar(select(Dispute).where(Dispute.tenant_id == tenant_id))
    assert account is not None
    assert account.balance == Decimal("350")
    assert account.reserved == Decimal("300")
    assert dispute is not None and dispute.held_credits == Decimal("300")

    lost = await _send_event(
        client,
        _event(
            event_id="evt_dispute_lost",
            event_type="payment.dispute.lost",
            tenant_id=registration["tenant_id"],
            checkout_id=checkout["id"],
            payment_id="pay_dispute",
            dispute_id="dispute_full",
            created=int(time.time()) + 1,
        ),
    )
    assert lost.status_code == 202, lost.text
    async with app.state.database.sessions() as session:
        account = await session.get(CreditAccount, tenant_id)
        dispute = await session.scalar(select(Dispute).where(Dispute.tenant_id == tenant_id))
        payment = await session.scalar(select(Payment).where(Payment.tenant_id == tenant_id))
    assert account is not None
    assert account.balance == Decimal("50")
    assert account.reserved == Decimal("0")
    assert dispute is not None
    assert dispute.status == "lost"
    assert dispute.reversed_credits == Decimal("300")
    assert dispute.outstanding_credits == Decimal("0")
    assert payment is not None and payment.status == "charged_back"


async def test_amount_mismatch_is_dead_lettered_without_payment_or_credit(
    payment_api: tuple[httpx.AsyncClient, Any],
) -> None:
    client, app = payment_api
    registration = await _register_verified(client, email="mismatch@example.test")
    checkout = await _checkout(client)
    mismatch = await _send_event(
        client,
        _event(
            event_id="evt_amount_mismatch",
            event_type="payment.succeeded",
            tenant_id=registration["tenant_id"],
            checkout_id=checkout["id"],
            payment_id="pay_amount_mismatch",
            amount_minor=1,
        ),
    )
    assert mismatch.status_code == 202, mismatch.text
    assert mismatch.json()["status"] == "dead_letter"
    tenant_id = uuid.UUID(registration["tenant_id"])
    async with app.state.database.sessions() as session:
        event = await session.scalar(
            select(PaymentEvent).where(PaymentEvent.tenant_id == tenant_id)
        )
        payment_count = await session.scalar(
            select(func.count(Payment.id)).where(Payment.tenant_id == tenant_id)
        )
        purchase_grants = await session.scalar(
            select(func.count(CreditGrant.id)).where(CreditGrant.tenant_id == tenant_id)
        )
        dlq_audit = await session.scalar(
            select(AuditEvent).where(
                AuditEvent.tenant_id == tenant_id,
                AuditEvent.action == "billing.payment_event.dead_lettered",
            )
        )
    assert event is not None
    assert event.last_error_code == "PAYMENT_AMOUNT_OR_CURRENCY_MISMATCH"
    assert payment_count == 0
    assert purchase_grants == 0
    assert dlq_audit is not None


def test_production_payment_configuration_fails_closed() -> None:
    with pytest.raises(ValidationError, match="fake payment provider"):
        Settings(
            env="production",
            payments_enabled=True,
            payment_provider="fake",
        )
    with pytest.raises(ValidationError, match="merchant id"):
        Settings(
            env="production",
            payments_enabled=True,
            payment_provider="merchant",
        )
    with pytest.raises(ValidationError, match="at least 32 bytes"):
        Settings(
            env="production",
            payments_enabled=True,
            payment_provider="merchant",
            payment_merchant_id="merchant_live",
            payment_webhook_secret="too-short",  # noqa: S106
        )
