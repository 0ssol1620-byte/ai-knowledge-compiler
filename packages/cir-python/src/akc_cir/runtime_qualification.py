"""Runtime qualification receipts (§14) — proof that what runs is what was proven.

A build receipt seals what was compiled (§29.2); it cannot certify that the
image actually pulled from the registry is that sealed image, on a GPU stack
anyone signed for, under a license the business may ship. The
:class:`RuntimeQualificationReceipt` binds exactly those facts: the immutable
container digest, the model artifact bytes and revision, the CUDA runtime
identity they ran against, SBOM and vulnerability evidence, the frozen smoke
suite outcome, benchmark scope, known failure modes, the cost and latency
receipts, and a rollback target for the day production disagrees.

:func:`evaluate` renders the one verdict downstream automation acts on:
``READY``, or ``NOT_READY`` with every gap named. The bar is deliberately
unglamorous — mandatory fields present, every required gate ``pass``, zero
high (and critical) vulnerabilities, a ``commercial_use_ok`` license, a
passing smoke run, and a rollback target. See
``infra/runpod/v6/RUNTIME_QUALIFICATION.md``: build integrity alone never
authorizes paid capacity.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Self

from pydantic import Field, StringConstraints, field_validator

from .base import ContractModel, NonEmptyStr, Sha256, TimestampedModel

__all__ = [
    "DEFAULT_REQUIRED_GATES",
    "CudaRuntimeIdentity",
    "GateStatus",
    "LicenseStatus",
    "PromotionStatus",
    "QualificationDecision",
    "QualificationPolicy",
    "QualificationStatus",
    "RuntimeGateResult",
    "RuntimeQualificationReceipt",
    "SmokeResult",
    "VulnScanRef",
    "VulnSeverityCounts",
    "evaluate",
    "runtime_qualification_json_schema",
]

#: Gates ``RUNTIME_QUALIFICATION.md`` demands before paid capacity: identity,
#: artifact, smoke. A policy may extend this set; nothing may shrink intent.
DEFAULT_REQUIRED_GATES: tuple[str, ...] = ("identity", "model_artifact", "smoke")

#: Immutable digests only. A mutable tag certifies a moving target.
ImmutableImageDigest = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*@sha256:[0-9a-f]{64}$"),
]


class LicenseStatus(StrEnum):
    """Commercial posture of everything baked into the image."""

    COMMERCIAL_USE_OK = "commercial_use_ok"
    RESTRICTED = "restricted"
    UNKNOWN = "unknown"


class PromotionStatus(StrEnum):
    """Lifecycle stage of the qualified artifact."""

    CANDIDATE = "candidate"
    QUALIFIED = "qualified"
    RETIRED = "retired"


class QualificationStatus(StrEnum):
    """Verdict consumed verbatim by pod specs, hence the loud values."""

    READY = "READY"
    NOT_READY = "NOT_READY"


class GateStatus(StrEnum):
    """Outcome of one named qualification gate."""

    PASS = "pass"  # noqa: S105 - a gate verdict, not a credential
    FAIL = "fail"
    SKIPPED = "skipped"


class SmokeResult(StrEnum):
    """Outcome of the frozen GPU smoke suite."""

    PASS = "pass"  # noqa: S105 - a smoke verdict, not a credential
    FAIL = "fail"
    NOT_RUN = "not_run"


class VulnSeverityCounts(ContractModel):
    """Trivy-style severity tallies from one scan report."""

    critical: int = Field(default=0, ge=0)
    high: int = Field(default=0, ge=0)
    medium: int = Field(default=0, ge=0)
    low: int = Field(default=0, ge=0)
    unknown: int = Field(default=0, ge=0)


class VulnScanRef(ContractModel):
    """Pointer at one vulnerability scan plus its headline counts."""

    report_ref: NonEmptyStr
    scanned_at: datetime
    severity_counts: VulnSeverityCounts

    @field_validator("scanned_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return value


class CudaRuntimeIdentity(ContractModel):
    """The exact driver/toolkit/GPU triple the image was exercised on."""

    driver_version: NonEmptyStr
    toolkit_version: NonEmptyStr
    gpu_name: NonEmptyStr


class RuntimeGateResult(ContractModel):
    """One named gate and how it resolved during qualification."""

    gate: NonEmptyStr
    status: GateStatus
    detail: str = ""


class QualificationPolicy(ContractModel):
    """What this deployment demands beyond the built-in minimum."""

    required_gates: tuple[NonEmptyStr, ...] = DEFAULT_REQUIRED_GATES


class RuntimeQualificationReceipt(TimestampedModel):
    """§14 receipt binding a runnable image to all of its evidence.

    Mandatory evidence fields are ``None`` until filled; absence is legal at
    construction and fatal at :func:`evaluate` — an unfinished receipt is a
    candidate, not a lie.
    """

    container_image_digest: ImmutableImageDigest
    model_artifact_sha256: Sha256
    model_revision: NonEmptyStr
    license_status: LicenseStatus
    sbom_ref: NonEmptyStr | None = None
    vuln_scan_ref: VulnScanRef | None = None
    cuda_runtime_identity: CudaRuntimeIdentity | None = None
    smoke_suite_id: NonEmptyStr | None = None
    smoke_result: SmokeResult | None = None
    benchmark_scope: tuple[NonEmptyStr, ...] = ()
    known_failure_modes: tuple[NonEmptyStr, ...] = ()
    cost_receipt_ref: NonEmptyStr | None = None
    latency_receipt_ref: NonEmptyStr | None = None
    rollback_target: NonEmptyStr | None = None
    promotion_status: PromotionStatus = PromotionStatus.CANDIDATE
    gates: tuple[RuntimeGateResult, ...] = ()

    def model_copy(self, *, update: Mapping[str, Any] | None = None, deep: bool = False) -> Self:
        """Amended copies re-validate.

        Pydantic skips validation on ``model_copy`` by default, which is
        precisely how a mutable ``:latest`` tag slips past an immutable-digest
        constraint via a "harmless" copy-and-edit. Every amended field here
        goes through the full model again; the ``deep`` flag is moot because
        the result is rebuilt from scratch either way.
        """
        if not update:
            return super().model_copy(update=update, deep=deep)
        # by_alias=False: the wire format is camelCase, but amendments (and
        # model_validate under populate_by_name) speak field names — mixing
        # the two vocabularies in one payload trips extra="forbid".
        payload = self.model_dump(by_alias=False)
        payload.update(update)
        return self.__class__.model_validate(payload)


class QualificationDecision(ContractModel):
    """The verdict :func:`evaluate` hands back, gaps spelled out."""

    status: QualificationStatus
    ready: bool
    missing_fields: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    failed_gates: tuple[str, ...] = ()


#: §14 evidence fields that must be populated before any other rule matters,
#: in declaration order so reports are deterministic.
_MANDATORY_FIELDS: tuple[str, ...] = (
    "sbom_ref",
    "vuln_scan_ref",
    "cuda_runtime_identity",
    "smoke_suite_id",
    "smoke_result",
    "cost_receipt_ref",
    "latency_receipt_ref",
    "rollback_target",
)

_FIELD_LABELS: dict[str, str] = {
    "sbom_ref": "SBOM reference (sbom_ref)",
    "vuln_scan_ref": "vulnerability scan reference (vuln_scan_ref)",
    "cuda_runtime_identity": "CUDA runtime identity (cuda_runtime_identity)",
    "smoke_suite_id": "smoke suite id (smoke_suite_id)",
    "smoke_result": "smoke result (smoke_result)",
    "cost_receipt_ref": "cost receipt reference (cost_receipt_ref)",
    "latency_receipt_ref": "latency receipt reference (latency_receipt_ref)",
    "rollback_target": "rollback target (rollback_target)",
}


def evaluate(
    receipt: RuntimeQualificationReceipt,
    policy: QualificationPolicy | None = None,
) -> QualificationDecision:
    """Render READY / NOT_READY for ``receipt`` under ``policy``.

    Ready requires: every mandatory §14 field present, every required gate
    ``PASS`` (a gate that is absent counts as failed), zero high and critical
    vulnerabilities, a ``commercial_use_ok`` license, a passing smoke run, and
    a rollback target. Retired receipts never qualify, whatever else they say.
    """
    policy = policy or QualificationPolicy()

    missing_fields: list[str] = []
    reasons: list[str] = []

    for field_name in _MANDATORY_FIELDS:
        if getattr(receipt, field_name) is None:
            missing_fields.append(field_name)
            label = _FIELD_LABELS[field_name]
            reasons.append(f"missing required §14 field: {label}")

    if not receipt.benchmark_scope:
        missing_fields.append("benchmark_scope")
        reasons.append("missing required §14 field: benchmark_scope is empty")

    if not receipt.gates:
        missing_fields.append("gates")
        reasons.append("missing required §14 field: gates has no recorded results")

    scan = receipt.vuln_scan_ref
    if scan is not None:
        counts = scan.severity_counts
        if counts.high > 0:
            reasons.append(
                f"vulnerability scan reports {counts.high} HIGH severity findings;"
                " policy requires 0"
            )
        if counts.critical > 0:
            reasons.append(
                f"vulnerability scan reports {counts.critical} CRITICAL severity"
                " findings; policy requires 0"
            )

    if receipt.license_status is not LicenseStatus.COMMERCIAL_USE_OK:
        reasons.append(
            f"license status '{receipt.license_status.value}' is not"
            f" '{LicenseStatus.COMMERCIAL_USE_OK.value}'"
        )

    if receipt.smoke_result is not None and receipt.smoke_result is not SmokeResult.PASS:
        reasons.append(
            f"smoke suite result '{receipt.smoke_result.value}' is not '{SmokeResult.PASS.value}'"
        )

    if receipt.promotion_status is PromotionStatus.RETIRED:
        reasons.append("promotion status 'retired': retired receipts never qualify")

    provided: dict[str, RuntimeGateResult] = {}
    for gate_result in receipt.gates:
        provided.setdefault(gate_result.gate, gate_result)
    failed_gates = tuple(
        name
        for name in policy.required_gates
        if (gate := provided.get(name)) is None or gate.status is not GateStatus.PASS
    )
    reasons.extend(f"required gate '{name}' did not pass" for name in failed_gates)

    ready = not missing_fields and not reasons and not failed_gates
    return QualificationDecision(
        status=QualificationStatus.READY if ready else QualificationStatus.NOT_READY,
        ready=ready,
        missing_fields=tuple(missing_fields),
        reasons=tuple(reasons),
        failed_gates=failed_gates,
    )


def runtime_qualification_json_schema() -> dict[str, Any]:
    """JSON schema of the §14 receipt in its camelCase wire format."""
    return RuntimeQualificationReceipt.model_json_schema(by_alias=True)
