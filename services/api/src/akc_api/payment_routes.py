"""HTTP boundary for provider-neutral billing and payment evidence."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal, cast

from akc_telemetry import record_abuse_control_decision
from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    status,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from akc_api.abuse import (
    IdentityHasher,
    RateLimitBackendUnavailable,
    RateLimitPolicy,
    rate_limit_http_exception,
)
from akc_api.database import get_session, set_rls_context
from akc_api.idempotency import idempotent_mutation
from akc_api.models import Checkout, Payment, PaymentEvent, Reconciliation, User
from akc_api.payments import (
    PaymentProvider,
    PaymentProviderUnavailable,
    PaymentWebhookError,
    available_credit_packs,
    create_credit_checkout,
    credit_pack,
    ingest_payment_event,
    parse_payment_event,
    reconcile_payments,
    retry_payment_event,
    verify_payment_webhook,
)
from akc_api.schemas import (
    CreditCheckoutCreate,
    CreditCheckoutResponse,
    CreditPackResponse,
    PaymentEventResponse,
    PaymentReconciliationResponse,
    PaymentResponse,
    PaymentWebhookResponse,
)
from akc_api.security import Principal, require_roles
from akc_api.settings import Settings

router = APIRouter(prefix="/v1")
SessionDep = Annotated[AsyncSession, Depends(get_session)]
BillingDep = Annotated[
    Principal,
    Depends(require_roles("owner", "admin", "billing")),
]


async def _verified_billing_user(
    session: AsyncSession,
    principal: Principal,
) -> User:
    user = await session.scalar(
        select(User).where(
            User.id == principal.user_id,
            User.is_active.is_(True),
        )
    )
    if user is None:
        raise HTTPException(status_code=401, detail={"code": "SESSION_REVOKED"})
    if user.email_verified_at is None:
        raise HTTPException(
            status_code=403,
            detail={"code": "EMAIL_VERIFICATION_REQUIRED"},
        )
    return user


async def _billing_rate_limit(request: Request, principal: Principal) -> None:
    settings: Settings = request.app.state.settings
    hasher = cast(IdentityHasher, request.app.state.identity_hasher)
    subject = hasher.pseudonymize(
        purpose="billing-tenant",
        value=str(principal.tenant_id),
    )
    try:
        decision = await request.app.state.rate_limiter.consume(
            control="billing",
            subject=subject,
            policy=RateLimitPolicy(
                limit=settings.operation_tenant_limit,
                window_seconds=settings.operation_window_seconds,
            ),
        )
    except RateLimitBackendUnavailable as exc:
        record_abuse_control_decision(control="billing", result="unavailable")
        raise HTTPException(
            status_code=503,
            detail={"code": "RATE_LIMIT_UNAVAILABLE"},
        ) from exc
    if not decision.allowed:
        record_abuse_control_decision(control="billing", result="limited")
        raise rate_limit_http_exception(decision)
    record_abuse_control_decision(control="billing", result="allowed")


def _payments_available(request: Request) -> tuple[Settings, PaymentProvider]:
    settings: Settings = request.app.state.settings
    provider = cast(PaymentProvider, request.app.state.payment_provider)
    if (
        not settings.payments_enabled
        or settings.payment_provider == "disabled"
        or provider.name != settings.payment_provider
    ):
        raise HTTPException(
            status_code=503,
            detail={"code": "PAYMENTS_UNAVAILABLE"},
        )
    return settings, provider


@router.get(
    "/billing/credit-packs",
    response_model=list[CreditPackResponse],
)
async def list_credit_packs(
    request: Request,
    principal: BillingDep,
    session: SessionDep,
) -> list[CreditPackResponse]:
    settings, _ = _payments_available(request)
    await _verified_billing_user(session, principal)
    return [
        CreditPackResponse(
            code=pack.code,
            amount_minor=pack.amount_minor,
            currency=pack.currency,
            credits=pack.credits,
        )
        for pack in available_credit_packs(settings)
    ]


@router.post(
    "/billing/checkouts",
    response_model=CreditCheckoutResponse,
    status_code=status.HTTP_201_CREATED,
)
@idempotent_mutation
async def create_checkout(
    payload: CreditCheckoutCreate,
    request: Request,
    principal: BillingDep,
    session: SessionDep,
) -> Checkout:
    settings, provider = _payments_available(request)
    await _verified_billing_user(session, principal)
    await _billing_rate_limit(request, principal)
    try:
        selected_pack = credit_pack(settings, payload.pack_code)
        checkout = await create_credit_checkout(
            session,
            tenant_id=principal.tenant_id,
            actor_id=principal.user_id,
            pack=selected_pack,
            provider=provider,
            settings=settings,
        )
    except ValueError as exc:
        if str(exc) == "credit_pack_not_found":
            raise HTTPException(
                status_code=404,
                detail={"code": "CREDIT_PACK_NOT_FOUND"},
            ) from exc
        raise
    except PaymentProviderUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "PAYMENTS_UNAVAILABLE"},
        ) from exc
    await session.commit()
    return checkout


@router.get(
    "/billing/checkouts/{checkout_id}",
    response_model=CreditCheckoutResponse,
)
async def get_checkout(
    checkout_id: uuid.UUID,
    principal: BillingDep,
    session: SessionDep,
) -> Checkout:
    await _verified_billing_user(session, principal)
    checkout = await session.scalar(
        select(Checkout).where(
            Checkout.tenant_id == principal.tenant_id,
            Checkout.id == checkout_id,
        )
    )
    if checkout is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "CHECKOUT_NOT_FOUND"},
        )
    return checkout


@router.get(
    "/billing/payments",
    response_model=list[PaymentResponse],
)
async def list_payments(
    principal: BillingDep,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[Payment]:
    await _verified_billing_user(session, principal)
    return list(
        await session.scalars(
            select(Payment)
            .where(Payment.tenant_id == principal.tenant_id)
            .order_by(Payment.created_at.desc(), Payment.id.desc())
            .limit(limit)
        )
    )


@router.post(
    "/payments/webhooks/{provider}",
    response_model=PaymentWebhookResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def receive_payment_webhook(
    provider: str,
    request: Request,
    session: SessionDep,
    payment_timestamp: Annotated[
        str | None,
        Header(alias="X-Payment-Timestamp"),
    ] = None,
    payment_signature: Annotated[
        str | None,
        Header(alias="X-Payment-Signature"),
    ] = None,
) -> PaymentWebhookResponse:
    settings: Settings = request.app.state.settings
    if (
        not settings.payments_enabled
        or provider != settings.payment_provider
        or provider == "disabled"
    ):
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"})
    raw_body = await request.body()
    try:
        verify_payment_webhook(
            secret=settings.effective_payment_webhook_secret,
            timestamp_header=payment_timestamp,
            signature_header=payment_signature,
            raw_body=raw_body,
            tolerance_seconds=settings.payment_webhook_tolerance_seconds,
            max_bytes=settings.payment_webhook_max_bytes,
        )
        parsed = parse_payment_event(
            raw_body,
            supported_currencies=settings.supported_payment_currencies,
        )
        await set_rls_context(session, tenant_id=parsed.tenant_id)
        receipt = await ingest_payment_event(
            session,
            provider=provider,
            parsed=parsed,
            raw_body=raw_body,
            settings=settings,
        )
    except PaymentWebhookError as exc:
        record_abuse_control_decision(
            control="payment_webhook",
            result=(
                "replay"
                if exc.code
                in {
                    "PAYMENT_WEBHOOK_TIMESTAMP_EXPIRED",
                    "PAYMENT_WEBHOOK_EVENT_ID_COLLISION",
                }
                else "invalid"
            ),
        )
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code},
        ) from exc
    await session.commit()
    record_abuse_control_decision(
        control="payment_webhook",
        result="duplicate" if receipt.duplicate else receipt.event.status,
    )
    return PaymentWebhookResponse(
        event_id=receipt.event.id,
        status=receipt.event.status,
        duplicate=receipt.duplicate,
    )


@router.get(
    "/billing/payment-events",
    response_model=list[PaymentEventResponse],
)
async def list_payment_events(
    principal: BillingDep,
    session: SessionDep,
    event_status: Annotated[
        Literal["pending", "retry", "processed", "ignored", "dead_letter"] | None,
        Query(alias="status"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[PaymentEvent]:
    await _verified_billing_user(session, principal)
    statement = select(PaymentEvent).where(
        PaymentEvent.tenant_id == principal.tenant_id
    )
    if event_status is not None:
        statement = statement.where(PaymentEvent.status == event_status)
    return list(
        await session.scalars(
            statement.order_by(
                PaymentEvent.received_at.desc(),
                PaymentEvent.id.desc(),
            ).limit(limit)
        )
    )


@router.post(
    "/billing/payment-events/{event_id}/retry",
    response_model=PaymentEventResponse,
)
@idempotent_mutation
async def retry_dead_lettered_payment_event(
    event_id: uuid.UUID,
    request: Request,
    principal: BillingDep,
    session: SessionDep,
) -> PaymentEvent:
    settings, _ = _payments_available(request)
    await _verified_billing_user(session, principal)
    await _billing_rate_limit(request, principal)
    try:
        event = await retry_payment_event(
            session,
            tenant_id=principal.tenant_id,
            event_id=event_id,
            actor_id=principal.user_id,
            settings=settings,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "PAYMENT_EVENT_NOT_FOUND"},
        ) from exc
    await session.commit()
    return event


@router.post(
    "/billing/reconciliations",
    response_model=PaymentReconciliationResponse,
    status_code=status.HTTP_201_CREATED,
)
@idempotent_mutation
async def run_payment_reconciliation(
    request: Request,
    principal: BillingDep,
    session: SessionDep,
) -> Reconciliation:
    settings, provider = _payments_available(request)
    await _verified_billing_user(session, principal)
    await _billing_rate_limit(request, principal)
    run = await reconcile_payments(
        session,
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        provider=provider.name,
        settings=settings,
    )
    await session.commit()
    return run


@router.get(
    "/billing/reconciliations/{reconciliation_id}",
    response_model=PaymentReconciliationResponse,
)
async def get_payment_reconciliation(
    reconciliation_id: uuid.UUID,
    principal: BillingDep,
    session: SessionDep,
) -> Reconciliation:
    await _verified_billing_user(session, principal)
    run = await session.scalar(
        select(Reconciliation).where(
            Reconciliation.tenant_id == principal.tenant_id,
            Reconciliation.id == reconciliation_id,
        )
    )
    if run is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "PAYMENT_RECONCILIATION_NOT_FOUND"},
        )
    return run
