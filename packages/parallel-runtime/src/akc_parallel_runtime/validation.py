"""Seven-level deterministic validator pipeline with fail-closed evidence rules."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum, StrEnum

from .identity import canonical_sha256, require_sha256


class ValidationLevel(IntEnum):
    TRANSPORT = 0
    STRUCTURAL = 1
    NATIVE = 2
    AUTHORITY = 3
    DIFFERENTIAL = 4
    MULTIMODAL = 5
    DOWNSTREAM = 6


class ValidationSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    HARD = "hard"
    SECURITY = "security"


@dataclass(frozen=True, slots=True)
class EvidenceReceipt:
    source_ref: str
    sha256: str
    kind: str

    def __post_init__(self) -> None:
        if not self.source_ref or not self.kind:
            raise ValueError("evidence receipts require source_ref and kind")
        require_sha256(self.sha256, field_name="evidence sha256")


@dataclass(frozen=True, slots=True)
class ValidationFinding:
    level: ValidationLevel
    code: str
    severity: ValidationSeverity
    evidence: tuple[EvidenceReceipt, ...]
    detail: str = ""

    def __post_init__(self) -> None:
        if not self.code or len(self.code) > 100:
            raise ValueError("finding code is required and must be concise")
        if not self.evidence:
            raise ValueError("validation findings must reference immutable evidence")
        if len(self.detail) > 500:
            raise ValueError("finding detail must be concise")


@dataclass(frozen=True, slots=True)
class ValidationPolicy:
    expected_page_ids: tuple[str, ...]
    native_comparison_required: bool = False
    authority_required: bool = False
    differential_required: bool = False
    multimodal_required: bool = False
    downstream_required: bool = True
    minimum_source_coverage: float = 1.0

    def __post_init__(self) -> None:
        if not self.expected_page_ids or len(set(self.expected_page_ids)) != len(
            self.expected_page_ids
        ):
            raise ValueError("validation policy needs unique expected page ids")
        if not 0 <= self.minimum_source_coverage <= 1:
            raise ValueError("minimum_source_coverage must be between 0 and 1")

    def requires(self, level: ValidationLevel) -> bool:
        if level in {ValidationLevel.TRANSPORT, ValidationLevel.STRUCTURAL}:
            return True
        return {
            ValidationLevel.NATIVE: self.native_comparison_required,
            ValidationLevel.AUTHORITY: self.authority_required,
            ValidationLevel.DIFFERENTIAL: self.differential_required,
            ValidationLevel.MULTIMODAL: self.multimodal_required,
            ValidationLevel.DOWNSTREAM: self.downstream_required,
        }[level]


@dataclass(frozen=True, slots=True)
class CandidateObservation:
    http_status: int
    response_received: bool
    identity_matches: bool
    checksum_matches: bool
    schema_valid: bool
    size_valid: bool
    finish_reason_complete: bool
    timed_out: bool
    actual_page_ids: tuple[str, ...]
    block_count: int
    bbox_valid: bool
    reading_order_valid: bool
    output_nonempty: bool
    repetition_detected: bool
    source_coverage: float
    native_available: bool = False
    native_text_coverage: float | None = None
    native_numeric_exact: bool | None = None
    native_headings_match: bool | None = None
    native_object_count_match: bool | None = None
    authority_available: bool = False
    authority_numeric_exact: bool | None = None
    authority_period_unit_account_match: bool | None = None
    differential_available: bool = False
    differential_agreement: bool | None = None
    expected_invariants_hold: bool | None = None
    multimodal_available: bool = False
    visible_regions_complete: bool | None = None
    tables_uncut: bool | None = None
    captions_complete: bool | None = None
    hierarchy_valid: bool | None = None
    downstream_available: bool = False
    markdown_valid: bool | None = None
    package_import_valid: bool | None = None
    source_links_valid: bool | None = None
    retrieval_valid: bool | None = None
    evidence: tuple[tuple[ValidationLevel, tuple[EvidenceReceipt, ...]], ...] = ()

    def __post_init__(self) -> None:
        if self.http_status < 0 or self.block_count < 0:
            raise ValueError("HTTP status and block count cannot be negative")
        if not 0 <= self.source_coverage <= 1:
            raise ValueError("source coverage must be between 0 and 1")
        if self.native_text_coverage is not None and not 0 <= self.native_text_coverage <= 1:
            raise ValueError("native text coverage must be between 0 and 1")
        levels = [level for level, _ in self.evidence]
        if len(levels) != len(set(levels)):
            raise ValueError("evidence can be declared once per validation level")

    def evidence_for(self, level: ValidationLevel) -> tuple[EvidenceReceipt, ...]:
        return dict(self.evidence).get(level, ())


@dataclass(frozen=True, slots=True)
class LevelResult:
    level: ValidationLevel
    required: bool
    passed: bool
    reason_codes: tuple[str, ...]
    evidence: tuple[EvidenceReceipt, ...]


@dataclass(frozen=True, slots=True)
class ValidationResult:
    passed: bool
    hard_failure_count: int
    results: tuple[LevelResult, ...]
    findings: tuple[ValidationFinding, ...]
    digest: str


class ValidatorPipeline:
    """Evaluate objective invariants; optional levels never masquerade as proof."""

    @staticmethod
    def _checks(
        level: ValidationLevel,
        observation: CandidateObservation,
        policy: ValidationPolicy,
    ) -> tuple[tuple[str, bool], ...]:
        if level is ValidationLevel.TRANSPORT:
            return (
                ("response_missing", observation.response_received),
                ("http_status_failure", 200 <= observation.http_status < 300),
                ("identity_mismatch", observation.identity_matches),
                ("checksum_mismatch", observation.checksum_matches),
                ("schema_invalid", observation.schema_valid),
                ("response_size_invalid", observation.size_valid),
                ("incomplete_finish_reason", observation.finish_reason_complete),
                ("transport_timeout", not observation.timed_out),
            )
        if level is ValidationLevel.STRUCTURAL:
            return (
                ("page_coverage_mismatch", observation.actual_page_ids == policy.expected_page_ids),
                ("empty_output", observation.output_nonempty and observation.block_count > 0),
                ("bbox_invalid", observation.bbox_valid),
                ("reading_order_invalid", observation.reading_order_valid),
                ("repetition_detected", not observation.repetition_detected),
                (
                    "source_coverage_incomplete",
                    observation.source_coverage >= policy.minimum_source_coverage,
                ),
            )
        if level is ValidationLevel.NATIVE:
            return (
                ("native_evidence_unavailable", observation.native_available),
                (
                    "native_text_coverage_low",
                    observation.native_text_coverage is not None
                    and observation.native_text_coverage >= policy.minimum_source_coverage,
                ),
                ("native_numeric_mismatch", observation.native_numeric_exact is True),
                ("native_heading_mismatch", observation.native_headings_match is True),
                ("native_object_count_mismatch", observation.native_object_count_match is True),
            )
        if level is ValidationLevel.AUTHORITY:
            return (
                ("authority_evidence_unavailable", observation.authority_available),
                ("authority_numeric_mismatch", observation.authority_numeric_exact is True),
                (
                    "authority_dimension_mismatch",
                    observation.authority_period_unit_account_match is True,
                ),
            )
        if level is ValidationLevel.DIFFERENTIAL:
            return (
                ("differential_evidence_unavailable", observation.differential_available),
                ("differential_disagreement", observation.differential_agreement is True),
                ("differential_invariant_failure", observation.expected_invariants_hold is True),
            )
        if level is ValidationLevel.MULTIMODAL:
            return (
                ("multimodal_evidence_unavailable", observation.multimodal_available),
                ("visible_region_missing", observation.visible_regions_complete is True),
                ("table_cut_detected", observation.tables_uncut is True),
                ("caption_missing", observation.captions_complete is True),
                ("visual_hierarchy_invalid", observation.hierarchy_valid is True),
            )
        return (
            ("downstream_evidence_unavailable", observation.downstream_available),
            ("markdown_invalid", observation.markdown_valid is True),
            ("package_import_invalid", observation.package_import_valid is True),
            ("source_link_invalid", observation.source_links_valid is True),
            ("retrieval_invalid", observation.retrieval_valid is True),
        )

    def validate(
        self, observation: CandidateObservation, policy: ValidationPolicy
    ) -> ValidationResult:
        results: list[LevelResult] = []
        findings: list[ValidationFinding] = []
        for level in ValidationLevel:
            required = policy.requires(level)
            evidence = observation.evidence_for(level)
            if not required:
                results.append(
                    LevelResult(
                        level=level,
                        required=False,
                        passed=False,
                        reason_codes=("not_required_not_evidence",),
                        evidence=evidence,
                    )
                )
                continue
            failed_codes = [
                code
                for code, condition in self._checks(level, observation, policy)
                if not condition
            ]
            if not evidence:
                failed_codes.append(f"level_{level.value}_evidence_missing")
            failed_codes = sorted(set(failed_codes))
            passed = not failed_codes
            results.append(
                LevelResult(
                    level=level,
                    required=True,
                    passed=passed,
                    reason_codes=tuple(failed_codes),
                    evidence=evidence,
                )
            )
            for code in failed_codes:
                finding_evidence = evidence or (
                    EvidenceReceipt(
                        source_ref=f"validator://level/{level.value}/missing-evidence",
                        sha256=canonical_sha256(
                            {"level": level.value, "code": code, "missing": True}
                        ),
                        kind="validator_receipt",
                    ),
                )
                findings.append(
                    ValidationFinding(
                        level=level,
                        code=code,
                        severity=ValidationSeverity.HARD,
                        evidence=finding_evidence,
                    )
                )
        passed = all(result.passed for result in results if result.required)
        digest_payload = {
            "policy": policy,
            "results": tuple(results),
            "findings": tuple(findings),
            "passed": passed,
        }
        return ValidationResult(
            passed=passed,
            hard_failure_count=len(findings),
            results=tuple(results),
            findings=tuple(findings),
            digest=canonical_sha256(digest_payload),
        )


__all__ = [
    "CandidateObservation",
    "EvidenceReceipt",
    "LevelResult",
    "ValidationFinding",
    "ValidationLevel",
    "ValidationPolicy",
    "ValidationResult",
    "ValidationSeverity",
    "ValidatorPipeline",
]
