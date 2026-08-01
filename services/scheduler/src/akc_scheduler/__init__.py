"""Durable transactional outbox and signed webhook scheduler."""

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .autonomous_v6_pipeline import (
        AdmissionEvidenceKind,
        AdmittedProviderCandidate,
        AutonomousV6PipelineCoordinator,
        AutonomousV6RuntimePort,
        PipelineCheckpoint,
        PipelineCheckpointConflict,
        PipelineCheckpointStore,
        PipelineContractError,
        PipelineExecutionMode,
        PipelineInventory,
        PipelinePhase,
        PipelineRunResult,
        ProviderPoll,
        ProviderPollState,
        RouteEstimateBinding,
        ShardCheckpoint,
        ShardPhase,
        SqlAlchemyProcessingJobCheckpointStore,
        SubmissionReceipt,
        V6PipelineJobSpec,
    )
    from .trusted_v6_admission import (
        PersistedAdmissionEnvelopeReader,
        PersistedEd25519AdmissionVerifier,
        TrustedAdmissionContext,
        TrustedAdmissionError,
        TrustedAdmissionVerifier,
        admission_receipt_sha256,
        build_trusted_admission_payload,
        sign_trusted_admission_envelope,
    )
from .database import (
    SchedulerDatabaseCapability,
    SchedulerDatabasePrivilegeError,
    create_dispatch_engine,
    create_gpu_engine,
    create_scheduler_engine,
    verify_dispatch_database,
    verify_gpu_database,
    verify_scheduler_database,
)
from .gpu_jobs import GpuInvocationWorker, GpuResultConflict, GpuWorkerPolicy
from .scheduler import (
    WEBHOOK_EVENT_TYPES,
    DurableScheduler,
    delivery_claim_statement,
    dispatch_claim_statement,
    endpoint_accepts_event,
    exponential_backoff_seconds,
    outbox_claim_statement,
)
from .settings import SchedulerSettings
from .webhooks import (
    HostAllowlist,
    SecretDecryptionError,
    WebhookDeliveryError,
    WebhookDnsError,
    WebhookHostNotAllowedError,
    WebhookHttpClient,
    WebhookHttpError,
    WebhookPayloadError,
    WebhookResponse,
    WebhookSecretIntegrityError,
    WebhookTargetError,
    canonical_webhook_body,
    decrypt_secret,
    decrypt_webhook_secret,
    encrypt_secret,
    encrypt_webhook_secret,
    generate_webhook_secret,
    parse_retry_after,
    sign_webhook_payload,
    validate_webhook_url,
    verify_secret_hash,
    webhook_headers,
)

_AUTONOMOUS_V6_EXPORTS = frozenset(
    {
        "AdmissionEvidenceKind",
        "AdmittedProviderCandidate",
        "AutonomousV6PipelineCoordinator",
        "AutonomousV6RuntimePort",
        "PipelineCheckpoint",
        "PipelineCheckpointConflict",
        "PipelineCheckpointStore",
        "PipelineContractError",
        "PipelineExecutionMode",
        "PipelineInventory",
        "PipelinePhase",
        "PipelineRunResult",
        "ProviderPoll",
        "ProviderPollState",
        "RouteEstimateBinding",
        "ShardCheckpoint",
        "ShardPhase",
        "SqlAlchemyProcessingJobCheckpointStore",
        "SubmissionReceipt",
        "V6PipelineJobSpec",
    }
)
_TRUSTED_V6_EXPORTS = frozenset(
    {
        "PersistedAdmissionEnvelopeReader",
        "PersistedEd25519AdmissionVerifier",
        "TrustedAdmissionContext",
        "TrustedAdmissionError",
        "TrustedAdmissionVerifier",
        "admission_receipt_sha256",
        "build_trusted_admission_payload",
        "sign_trusted_admission_envelope",
    }
)


def __getattr__(name: str) -> Any:
    """Load the optional v6 runtime only when a caller requests its API."""

    if name in _AUTONOMOUS_V6_EXPORTS:
        module = import_module(".autonomous_v6_pipeline", __name__)
        value = getattr(module, name)
        globals()[name] = value
        return value
    if name in _TRUSTED_V6_EXPORTS:
        module = import_module(".trusted_v6_admission", __name__)
        value = getattr(module, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "WEBHOOK_EVENT_TYPES",
    "AdmissionEvidenceKind",
    "AdmittedProviderCandidate",
    "AutonomousV6PipelineCoordinator",
    "AutonomousV6RuntimePort",
    "DurableScheduler",
    "GpuInvocationWorker",
    "GpuResultConflict",
    "GpuWorkerPolicy",
    "HostAllowlist",
    "PersistedAdmissionEnvelopeReader",
    "PersistedEd25519AdmissionVerifier",
    "PipelineCheckpoint",
    "PipelineCheckpointConflict",
    "PipelineCheckpointStore",
    "PipelineContractError",
    "PipelineExecutionMode",
    "PipelineInventory",
    "PipelinePhase",
    "PipelineRunResult",
    "ProviderPoll",
    "ProviderPollState",
    "RouteEstimateBinding",
    "SchedulerDatabaseCapability",
    "SchedulerDatabasePrivilegeError",
    "SchedulerSettings",
    "SecretDecryptionError",
    "ShardCheckpoint",
    "ShardPhase",
    "SqlAlchemyProcessingJobCheckpointStore",
    "SubmissionReceipt",
    "TrustedAdmissionContext",
    "TrustedAdmissionError",
    "TrustedAdmissionVerifier",
    "V6PipelineJobSpec",
    "WebhookDeliveryError",
    "WebhookDnsError",
    "WebhookHostNotAllowedError",
    "WebhookHttpClient",
    "WebhookHttpError",
    "WebhookPayloadError",
    "WebhookResponse",
    "WebhookSecretIntegrityError",
    "WebhookTargetError",
    "admission_receipt_sha256",
    "build_trusted_admission_payload",
    "canonical_webhook_body",
    "create_dispatch_engine",
    "create_gpu_engine",
    "create_scheduler_engine",
    "decrypt_secret",
    "decrypt_webhook_secret",
    "delivery_claim_statement",
    "dispatch_claim_statement",
    "encrypt_secret",
    "encrypt_webhook_secret",
    "endpoint_accepts_event",
    "exponential_backoff_seconds",
    "generate_webhook_secret",
    "outbox_claim_statement",
    "parse_retry_after",
    "sign_trusted_admission_envelope",
    "sign_webhook_payload",
    "validate_webhook_url",
    "verify_dispatch_database",
    "verify_gpu_database",
    "verify_scheduler_database",
    "verify_secret_hash",
    "webhook_headers",
]
