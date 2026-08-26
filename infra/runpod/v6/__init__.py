"""Provider-neutral RunPod v6 lifecycle and spend-safety contracts.

The public convenience exports are loaded lazily so build-evidence modules can
run without importing the HTTP client, orchestration, or optional YAML stack.
Importing this package has no network or credential side effects.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any, Final

_EXPORTS: Final = {
    "BillingHistory": (".client", "BillingHistory"),
    "BillingQuery": (".client", "BillingQuery"),
    "DeleteAcknowledgement": (".client", "DeleteAcknowledgement"),
    "DryRunReceipt": (".client", "DryRunReceipt"),
    "EndpointCreateSpec": (".client", "EndpointCreateSpec"),
    "EndpointPatch": (".client", "EndpointPatch"),
    "EndpointSummary": (".client", "EndpointSummary"),
    "OrphanAuditReceipt": (".client", "OrphanAuditReceipt"),
    "ProviderAbsenceReceipt": (".client", "ProviderAbsenceReceipt"),
    "QueueJob": (".client", "QueueJob"),
    "QueuePolicy": (".client", "QueuePolicy"),
    "RunPodClientError": (".client", "RunPodClientError"),
    "RunPodProtocolError": (".client", "RunPodProtocolError"),
    "RunPodV2Client": (".client", "RunPodV2Client"),
    "ScalingPolicy": (".client", "ScalingPolicy"),
    "WorkerBounds": (".client", "WorkerBounds"),
    "make_idempotency_key": (".client", "make_idempotency_key"),
    "CleanupFacts": (".orchestration", "CleanupFacts"),
    "EndpointLifecycle": (".orchestration", "EndpointLifecycle"),
    "EndpointState": (".orchestration", "EndpointState"),
    "PoolRegistry": (".orchestration", "PoolRegistry"),
    "SpendGuard": (".orchestration", "SpendGuard"),
    "SpendPolicy": (".orchestration", "SpendPolicy"),
    "SpendState": (".orchestration", "SpendState"),
    "audit_orphan_endpoints": (".orchestration", "audit_orphan_endpoints"),
    "Assignment": (".scheduling", "Assignment"),
    "BackpressureSnapshot": (".scheduling", "BackpressureSnapshot"),
    "QueuePriority": (".scheduling", "QueuePriority"),
    "WorkerObservation": (".scheduling", "WorkerObservation"),
    "WorkUnit": (".scheduling", "WorkUnit"),
    "dynamic_worker_target": (".scheduling", "dynamic_worker_target"),
    "fair_priority_order": (".scheduling", "fair_priority_order"),
    "select_worker": (".scheduling", "select_worker"),
    "should_scale_down": (".scheduling", "should_scale_down"),
    "size_aware_assignments": (".scheduling", "size_aware_assignments"),
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    """Resolve documented convenience exports only when a caller requests one."""
    try:
        module_name, attribute_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    value = getattr(import_module(module_name, __name__), attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_EXPORTS))
