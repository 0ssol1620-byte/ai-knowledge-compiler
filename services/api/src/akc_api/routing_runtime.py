"""Tenant-scoped routing inputs loaded atomically with processing work."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any

from akc_router import (
    DataPolicy,
    FeatureFlags,
    ProcessingMode,
    RiskTier,
    Route,
    RouteProfile,
    RouterContext,
)
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from akc_api.feature_flags import cohort_enabled, conditions_match
from akc_api.models import FeatureFlag, ModelRegistry, Project, Tenant

_REVISION = re.compile(r"^[0-9a-f]{40,64}$")
_IMAGE_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{1,159}$")
_ENDPOINT = re.compile(r"^[A-Za-z0-9_-]{3,80}$")

_PROFILE_MODE = {
    RouteProfile.FAST.value: ProcessingMode.SPEED,
    RouteProfile.BALANCED.value: ProcessingMode.BALANCED,
    RouteProfile.PRECISION.value: ProcessingMode.PRECISION,
    RouteProfile.PRIVATE.value: ProcessingMode.PRIVATE,
    RouteProfile.LONG.value: ProcessingMode.LONG_FORM_BETA,
}


@dataclass(frozen=True, slots=True)
class ProviderBinding:
    route: Route
    endpoint_id: str
    model_id: str
    model_revision: str
    runtime_image_digest: str
    adapter_version: str
    policy_version: str


@dataclass(frozen=True, slots=True)
class RoutingRuntime:
    tenant: Tenant
    project: Project
    context: RouterContext
    bindings: dict[Route, ProviderBinding]

    def provider_for(self, route: Route) -> ProviderBinding | None:
        return self.bindings.get(route)


def constrain_routing_runtime_for_page(
    runtime: RoutingRuntime,
    *,
    preflight_metrics: dict[str, Any],
) -> tuple[RoutingRuntime, bool]:
    """Disable external transfer when persisted detection says secrets exist."""

    sensitive_data = preflight_metrics.get("sensitive_data", {})
    has_secret = bool(isinstance(sensitive_data, dict) and sensitive_data.get("has_secret") is True)
    if not has_secret:
        return runtime, False
    context = runtime.context.model_copy(
        update={
            "ready_routes": frozenset(
                route for route in runtime.context.ready_routes if route != Route.MISTRAL_FALLBACK
            ),
            "data_policy": runtime.context.data_policy.model_copy(
                update={"external_api_allowed": False}
            ),
        }
    )
    return (
        RoutingRuntime(
            tenant=runtime.tenant,
            project=runtime.project,
            context=context,
            bindings=runtime.bindings,
        ),
        True,
    )


def _processing_mode(
    output_profile: dict[str, Any],
    requested_route_profile: str | None,
) -> ProcessingMode:
    profile = requested_route_profile or output_profile.get("route_profile")
    if isinstance(profile, str) and profile in _PROFILE_MODE:
        return _PROFILE_MODE[profile]
    raw_mode = output_profile.get("processing_mode", ProcessingMode.BALANCED.value)
    aliases = {
        "fast": ProcessingMode.SPEED,
        "long": ProcessingMode.LONG_FORM_BETA,
    }
    if isinstance(raw_mode, str):
        try:
            return ProcessingMode(raw_mode)
        except ValueError:
            return aliases.get(raw_mode, ProcessingMode.BALANCED)
    return ProcessingMode.BALANCED


def _registry_route(row: ModelRegistry) -> Route | None:
    identity = f"{row.endpoint} {row.model_id}".casefold().replace("-", "_")
    if "mistral" in identity:
        return Route.MISTRAL_FALLBACK
    if "unlimited" in identity or "long_ocr" in identity:
        return Route.UNLIMITED_LONG
    if "hpd" in identity:
        return Route.HPD_FAST
    if "paddle" in identity and "fast" in identity:
        return Route.PADDLE_FAST
    if "paddle" in identity and ("vl" in identity or "ocr" in identity):
        return Route.PADDLE_VL
    return None


def _binding(row: ModelRegistry, route: Route) -> ProviderBinding | None:
    revision = row.revision.casefold()
    image = row.runtime_image_digest.casefold()
    if (
        not _ENDPOINT.fullmatch(row.endpoint)
        or not _REVISION.fullmatch(revision)
        or not _IMAGE_DIGEST.fullmatch(image)
        or not _IDENTIFIER.fullmatch(row.model_id)
        or not _IDENTIFIER.fullmatch(row.adapter_version)
    ):
        return None
    return ProviderBinding(
        route=route,
        endpoint_id=row.endpoint,
        model_id=row.model_id,
        model_revision=revision,
        runtime_image_digest=image,
        adapter_version=row.adapter_version,
        policy_version=row.policy_version,
    )


def validate_registry_binding(row: ModelRegistry) -> ProviderBinding:
    """Validate an operator-managed registry recipe before lifecycle mutation."""

    route = _registry_route(row)
    if route is None:
        raise ValueError("model endpoint does not map to an approved route")
    binding = _binding(row, route)
    if binding is None:
        raise ValueError("model recipe contains an invalid immutable identifier")
    if not row.benchmark_report.strip():
        raise ValueError("model recipe requires a benchmark report reference")
    return binding


async def load_routing_runtime(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    requested_route_profile: str | None = None,
    external_processing_consent: bool = False,
    dominant_language: str | None = None,
) -> RoutingRuntime:
    """Load mode, tenant policy, flags and provider readiness under row locks."""

    tenant = await session.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
    project = await session.scalar(
        select(Project)
        .where(
            Project.tenant_id == tenant_id,
            Project.id == project_id,
            Project.deletion_requested_at.is_(None),
        )
        .with_for_update()
    )
    if tenant is None or project is None:
        raise LookupError("routing_scope_not_found")

    flag_rows = list(
        (
            await session.scalars(
                select(FeatureFlag)
                .where(
                    or_(
                        FeatureFlag.tenant_id == tenant_id,
                        FeatureFlag.tenant_id.is_(None),
                    )
                )
                .with_for_update()
            )
        ).all()
    )
    effective_flags: dict[str, bool] = {}
    for flag_row in sorted(
        flag_rows,
        key=lambda value: value.tenant_id is not None,
    ):
        effective_flags[flag_row.key] = conditions_match(
            flag_row.conditions if isinstance(flag_row.conditions, dict) else {},
            tenant_id=tenant_id,
        ) and cohort_enabled(
            tenant_id=tenant_id,
            key=flag_row.key,
            enabled=flag_row.enabled,
            percent=flag_row.rollout_percent,
        )

    registry_rows = list(
        (
            await session.scalars(
                select(ModelRegistry)
                .where(ModelRegistry.enabled.is_(True))
                .order_by(ModelRegistry.created_at.desc(), ModelRegistry.id.desc())
                .with_for_update()
            )
        ).all()
    )
    bindings: dict[Route, ProviderBinding] = {}
    for model_row in registry_rows:
        route = _registry_route(model_row)
        if route is None or route in bindings:
            continue
        if not cohort_enabled(
            tenant_id=tenant_id,
            key=f"model:{model_row.endpoint}:{model_row.revision}",
            enabled=model_row.enabled,
            percent=model_row.canary_percent,
        ):
            continue
        candidate = _binding(model_row, route)
        if candidate is not None:
            bindings[route] = candidate

    output_profile = project.output_profile if isinstance(project.output_profile, dict) else {}
    mode = _processing_mode(output_profile, requested_route_profile)
    if tenant.private_mode:
        mode = ProcessingMode.PRIVATE
    external_allowed = (
        external_processing_consent
        and tenant.external_transfer_allowed
        and not tenant.private_mode
        and mode != ProcessingMode.PRIVATE
    )
    flags = FeatureFlags(
        hpd_enabled=effective_flags.get("hpd_fast_route", False),
        paddle_fast_enabled=effective_flags.get("paddle_fast_route", False),
        unlimited_long_enabled=effective_flags.get("unlimited_long_doc", False),
        external_fallback_enabled=effective_flags.get(
            "external_mistral_fallback",
            False,
        ),
    )
    ready_routes: set[Route] = {Route.NATIVE}
    for route in bindings:
        if route == Route.HPD_FAST and not flags.hpd_enabled:
            continue
        if route == Route.PADDLE_FAST and not flags.paddle_fast_enabled:
            continue
        if route == Route.UNLIMITED_LONG and not flags.unlimited_long_enabled:
            continue
        if route == Route.MISTRAL_FALLBACK and (
            not flags.external_fallback_enabled or not external_allowed
        ):
            continue
        ready_routes.add(route)

    explicit_risk = str(output_profile.get("risk_tier", "")).casefold()
    high_risk = explicit_risk == RiskTier.HIGH.value or project.classification.casefold() in {
        "financial",
        "finance",
        "legal",
        "medical",
        "regulated",
    }
    policy_versions = sorted({binding.policy_version for binding in bindings.values()})
    policy_version = str(
        output_profile.get("router_policy_version")
        or (policy_versions[-1] if policy_versions else "router-2026-07-30.1")
    )
    context = RouterContext(
        mode=mode,
        dominant_language=dominant_language,
        risk_tier=RiskTier.HIGH if high_risk else RiskTier.NORMAL,
        feature_flags=flags,
        data_policy=DataPolicy(
            external_api_allowed=external_allowed,
            retention_days=tenant.data_retention_days,
            regional_restriction=tenant.region,
            private_processing=tenant.private_mode,
        ),
        ready_routes=frozenset(ready_routes),
        policy_version=policy_version,
    )
    return RoutingRuntime(
        tenant=tenant,
        project=project,
        context=context,
        bindings=bindings,
    )
