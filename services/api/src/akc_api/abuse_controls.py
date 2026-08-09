"""Request-scoped abuse control helpers.

Extracted verbatim from ``main.py`` so routers outside that module can enforce
the same limits without importing it, which would be circular. ``main.py``
re-exports these names, so every existing call site keeps working and there is
one implementation rather than two.

The behaviour is unchanged on purpose. This is rate limiting and CAPTCHA
escalation: a "small improvement" made while moving it is how a limit quietly
stops applying.
"""

from __future__ import annotations

import uuid
from typing import cast

from akc_telemetry import record_abuse_control_decision
from fastapi import HTTPException, Request

from akc_api.abuse import (
    CaptchaProviderUnavailable,
    CaptchaRejectedError,
    CaptchaRequiredError,
    IdentityHasher,
    RateLimitBackendUnavailable,
    RateLimitDecision,
    RateLimitPolicy,
    TrustedProxyIdentityResolver,
    enforce_captcha,
    rate_limit_http_exception,
)


def client_subject(request: Request) -> str:
    """Pseudonymised caller identity. Never a raw address."""
    resolver = cast(
        TrustedProxyIdentityResolver,
        request.app.state.client_identity_resolver,
    )
    identity = resolver.resolve_request(request)
    return identity.pseudonym


def account_subject(request: Request, value: str) -> str:
    hasher = cast(IdentityHasher, request.app.state.identity_hasher)
    return hasher.pseudonymize(
        purpose="account",
        value=value.strip().casefold(),
    )


def tenant_subject(request: Request, tenant_id: uuid.UUID) -> str:
    hasher = cast(IdentityHasher, request.app.state.identity_hasher)
    return hasher.pseudonymize(
        purpose="tenant",
        value=str(tenant_id),
    )


async def consume_rate_control(
    request: Request,
    *,
    control: str,
    subjects: list[tuple[str, RateLimitPolicy]],
    captcha_action: str | None = None,
) -> None:
    """Charge every subject, then escalate to CAPTCHA if any of them asked for it.

    Fails closed: a limiter backend that cannot answer produces 503 rather than
    an allow. That matters most on anonymous surfaces, where an unbounded
    fallback would be the whole vulnerability.
    """
    captcha_required = False
    try:
        for subject, policy in subjects:
            decision: RateLimitDecision = await request.app.state.rate_limiter.consume(
                control=control,
                subject=subject,
                policy=policy,
            )
            if not decision.allowed:
                record_abuse_control_decision(control=control, result="limited")
                raise rate_limit_http_exception(decision)
            captcha_required = captcha_required or decision.captcha_required
    except RateLimitBackendUnavailable as exc:
        record_abuse_control_decision(control=control, result="unavailable")
        raise HTTPException(
            status_code=503,
            detail={"code": "ABUSE_CONTROL_UNAVAILABLE"},
        ) from exc
    if captcha_action is not None:
        try:
            await enforce_captcha(
                required=captcha_required,
                token=request.headers.get("X-Captcha-Token"),
                provider=request.app.state.captcha_provider,
                client_identity=client_subject(request),
                action=captcha_action,
            )
        except CaptchaRequiredError as exc:
            record_abuse_control_decision(control="captcha", result="required")
            raise HTTPException(
                status_code=403,
                detail={"code": "CAPTCHA_REQUIRED"},
            ) from exc
        except CaptchaRejectedError as exc:
            unavailable = isinstance(exc.__cause__, CaptchaProviderUnavailable)
            record_abuse_control_decision(
                control="captcha",
                result="unavailable" if unavailable else "rejected",
            )
            raise HTTPException(
                status_code=503 if unavailable else 403,
                detail={"code": ("CAPTCHA_UNAVAILABLE" if unavailable else "CAPTCHA_REJECTED")},
            ) from exc
    record_abuse_control_decision(control=control, result="allowed")
