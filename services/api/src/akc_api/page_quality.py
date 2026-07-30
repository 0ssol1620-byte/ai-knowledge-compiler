"""Measured page-quality gates shared by native analysis and compilation."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from akc_cir import CanonicalBlock, CanonicalTable
from akc_quality import (
    FindingSeverity,
    QualityEvaluation,
    QualityFinding,
    QualityStatus,
    QualityVector,
    compare_numeric_tokens,
    evaluate_quality,
    markdown_anomalies,
    repeated_ngram_ratio,
    text_anomalies,
    validate_table,
)
from akc_router import QualitySignal, detect_script_distribution
from pydantic import ValidationError


@dataclass(frozen=True, slots=True)
class PageQualityBlock:
    block_id: str
    block_type: str
    source_text: str
    candidate_text: str
    bbox1000: tuple[int, int, int, int] | None
    has_provenance: bool
    table: CanonicalTable | None = None
    table_invalid: bool = False
    confidence: float | None = None
    token_confidences: tuple[float, ...] = ()


@dataclass(frozen=True, slots=True)
class PageQualityAssessment:
    evaluation: QualityEvaluation
    signal: QualitySignal

    @property
    def vector_payload(self) -> dict[str, Any]:
        return self.evaluation.vector.model_dump(mode="json", by_alias=False)

    @property
    def findings_payload(self) -> list[dict[str, Any]]:
        return [
            finding.model_dump(mode="json", by_alias=False, exclude_none=True)
            for finding in self.evaluation.findings
        ]

    @property
    def evaluation_payload(self) -> dict[str, Any]:
        return self.evaluation.model_dump(mode="json", by_alias=False)


def quality_block_from_canonical(block: CanonicalBlock) -> PageQualityBlock:
    source_ref = block.source_refs[0] if block.source_refs else None
    bbox = source_ref.bbox1000.as_tuple() if source_ref and source_ref.bbox1000 else None
    return PageQualityBlock(
        block_id=block.id,
        block_type=block.type.value,
        source_text=block.raw_text or block.normalized_text or "",
        candidate_text=block.markdown or block.normalized_text or block.raw_text or "",
        bbox1000=bbox,
        has_provenance=bool(block.source_refs),
        table=block.table,
        confidence=block.confidence,
    )


def quality_block_from_record(block: Any) -> PageQualityBlock:
    raw_bbox = getattr(block, "bbox1000", None)
    bbox: tuple[int, int, int, int] | None = None
    if isinstance(raw_bbox, (list, tuple)) and len(raw_bbox) == 4:
        bbox = (
            int(raw_bbox[0]),
            int(raw_bbox[1]),
            int(raw_bbox[2]),
            int(raw_bbox[3]),
        )
    structured = getattr(block, "structured_content", None) or {}
    table_value = structured.get("table") if isinstance(structured, dict) else None
    table: CanonicalTable | None = None
    table_invalid = False
    if table_value is not None:
        try:
            table = CanonicalTable.model_validate(table_value)
        except ValidationError:
            table_invalid = True
    page_id = getattr(block, "page_id", None)
    source_refs = structured.get("sourceRefs", []) if isinstance(structured, dict) else []
    return PageQualityBlock(
        block_id=str(block.id),
        block_type=str(getattr(block, "block_type", "unknown")),
        source_text=str(getattr(block, "source_text", None) or ""),
        candidate_text=str(
            getattr(block, "markdown", None)
            or getattr(block, "normalized_text", None)
            or getattr(block, "source_text", None)
            or ""
        ),
        bbox1000=bbox,
        has_provenance=bool(page_id is not None or source_refs),
        table=table,
        table_invalid=table_invalid,
        confidence=getattr(block, "confidence", None),
    )


def _bounded_similarity(reference: str, candidate: str) -> float | None:
    if not reference and not candidate:
        return None
    if not reference:
        return None
    if not candidate:
        return 0.0
    # Page output is bounded upstream. This additional cap keeps the quality
    # gate deterministic under adversarially long single-page text.
    cap = 200_000
    return SequenceMatcher(
        None,
        reference[:cap],
        candidate[:cap],
        autojunk=False,
    ).ratio()


def _language_consistency(reference: str, candidate: str) -> float | None:
    reference_scripts = detect_script_distribution(reference)
    candidate_scripts = detect_script_distribution(candidate)
    if not reference_scripts and not candidate_scripts:
        return None
    if not reference_scripts:
        return None
    if not candidate_scripts:
        return 0.0
    scripts = set(reference_scripts) | set(candidate_scripts)
    distance = sum(
        abs(reference_scripts.get(script, 0.0) - candidate_scripts.get(script, 0.0))
        for script in scripts
    )
    return float(max(0.0, 1.0 - distance / 2.0))


def _charset_plausibility(candidate: str) -> float:
    if not candidate:
        return 0.0
    suspicious = 0
    meaningful = 0
    for character in candidate:
        if character in "\n\r\t":
            continue
        meaningful += 1
        category = unicodedata.category(character)
        if character == "\ufffd" or category in {"Cc", "Cs", "Cn"}:
            suspicious += 1
    if not meaningful:
        return 0.0
    return max(0.0, 1.0 - suspicious / meaningful * 20.0)


def _ocr_accuracy(blocks: tuple[PageQualityBlock, ...]) -> float | None:
    scores: list[float] = []
    for block in blocks:
        if block.confidence is None or not block.token_confidences:
            return None
        token_mean = sum(block.token_confidences) / len(block.token_confidences)
        scores.append(min(float(block.confidence), token_mean))
    return min(scores) if scores else None


def _layout_fidelity(blocks: tuple[PageQualityBlock, ...]) -> float | None:
    bounded = [block for block in blocks if block.bbox1000 is not None]
    if not bounded:
        return None
    valid = 0
    for block in bounded:
        assert block.bbox1000 is not None
        x1, y1, x2, y2 = block.bbox1000
        valid += int(
            all(0 <= coordinate <= 1000 for coordinate in block.bbox1000)
            and x1 < x2
            and y1 < y2
        )
    return valid / len(bounded)


def _penalty_score(
    findings: tuple[QualityFinding, ...],
    *,
    codes: frozenset[str] | None = None,
) -> float:
    selected = (
        tuple(finding for finding in findings if finding.code in codes)
        if codes is not None
        else findings
    )
    penalty = 0.0
    for finding in selected:
        penalty += {
            FindingSeverity.INFO: 0.02,
            FindingSeverity.WARNING: 0.08,
            FindingSeverity.ERROR: 0.30,
            FindingSeverity.CRITICAL: 1.0,
        }[finding.severity]
    return max(0.0, 1.0 - penalty)


def evaluate_page_quality(
    blocks: list[PageQualityBlock] | tuple[PageQualityBlock, ...],
    *,
    high_risk: bool = False,
    failed_attempts: int = 0,
    mandatory_ocr_accuracy: bool = False,
    requires_independent_verifier: bool = False,
    verification_agreement: float | None = None,
    verification_numeric_agreement: float | None = None,
    verification_table_agreement: float | None = None,
    verification_formula_agreement: float | None = None,
) -> PageQualityAssessment:
    """Evaluate only reproducible text, number, table, provenance and syntax evidence."""

    materialized = tuple(blocks)
    reference = "\n\n".join(
        block.source_text for block in materialized if block.source_text
    )
    candidate = "\n\n".join(
        block.candidate_text for block in materialized if block.candidate_text
    )
    source_repetition = repeated_ngram_ratio(reference) if reference else 0.0
    candidate_repetition = repeated_ngram_ratio(candidate) if candidate else 0.0
    ocr_accuracy = _ocr_accuracy(materialized)
    charset_plausibility = _charset_plausibility(candidate)
    findings: list[QualityFinding] = [
        *(
            finding
            for finding in text_anomalies(
                candidate,
                reference_length=len(reference) or None,
            )
            # Repetition already present in the extracted source is fidelity,
            # not a generated-output loop. Only excess repetition is unsafe.
            if finding.code != "text.repetition"
            or candidate_repetition > source_repetition + 0.08
        ),
        *markdown_anomalies(candidate),
    ]
    if mandatory_ocr_accuracy:
        if ocr_accuracy is None:
            findings.append(
                QualityFinding(
                    code="ocr.accuracy_missing",
                    severity=FindingSeverity.CRITICAL,
                    message=(
                        "Visual OCR output has no complete block and token "
                        "confidence evidence."
                    ),
                    metric="text_fidelity",
                )
            )
        elif ocr_accuracy < 0.85:
            findings.append(
                QualityFinding(
                    code="ocr.accuracy_below_threshold",
                    severity=FindingSeverity.CRITICAL,
                    message="Visual OCR confidence is below the admission threshold.",
                    metric="text_fidelity",
                    observed=ocr_accuracy,
                    threshold=0.85,
                )
            )
        if charset_plausibility < 0.98:
            findings.append(
                QualityFinding(
                    code="ocr.charset_implausible",
                    severity=FindingSeverity.CRITICAL,
                    message=(
                        "Visual OCR output contains implausible replacement "
                        "or control characters."
                    ),
                    metric="language_consistency",
                    observed=charset_plausibility,
                    threshold=0.98,
                )
            )
    if requires_independent_verifier:
        if verification_agreement is None:
            findings.append(
                QualityFinding(
                    code="verification.independent_missing",
                    severity=FindingSeverity.CRITICAL,
                    message="Risk-bearing visual OCR requires independent verifier agreement.",
                    metric="text_fidelity",
                )
            )
        elif verification_agreement < 0.90:
            findings.append(
                QualityFinding(
                    code="verification.agreement_below_threshold",
                    severity=FindingSeverity.CRITICAL,
                    message="Independent visual verifier agreement is below threshold.",
                    metric="text_fidelity",
                    observed=verification_agreement,
                    threshold=0.90,
                )
            )
    has_numeric = bool(reference and compare_numeric_tokens(reference, candidate).reference_tokens)
    if not reference:
        has_numeric = any(character.isdigit() for character in candidate)
    if requires_independent_verifier and has_numeric and verification_numeric_agreement != 1.0:
        findings.append(
            QualityFinding(
                code="verification.numeric_exact_missing",
                severity=FindingSeverity.CRITICAL,
                message="Numeric OCR content requires exact independent agreement.",
                metric="numeric_fidelity",
                observed=verification_numeric_agreement,
                threshold=1.0,
            )
        )
    if (
        requires_independent_verifier
        and any(block.block_type == "table" for block in materialized)
        and (
            verification_table_agreement is None
            or verification_table_agreement < 0.95
        )
    ):
        findings.append(
            QualityFinding(
                code="verification.table_structure_missing",
                severity=FindingSeverity.CRITICAL,
                message="Table OCR requires independent structure agreement.",
                metric="table_fidelity",
                observed=verification_table_agreement,
                threshold=0.95,
            )
        )
    if (
        requires_independent_verifier
        and any(block.block_type == "formula" for block in materialized)
        and (
            verification_formula_agreement is None
            or verification_formula_agreement < 0.95
        )
    ):
        findings.append(
            QualityFinding(
                code="verification.formula_missing",
                severity=FindingSeverity.CRITICAL,
                message="Formula OCR requires independent symbolic agreement.",
                metric="text_fidelity",
                observed=verification_formula_agreement,
                threshold=0.95,
            )
        )

    numeric_score: float | None = None
    if reference:
        numeric = compare_numeric_tokens(reference, candidate)
        # An empty token set is unknown, not evidence of perfect numeric
        # fidelity.  This distinction matters for high-risk documents.
        if numeric.reference_tokens or numeric.candidate_tokens:
            numeric_score = numeric.score
        if numeric.missing_tokens or numeric.unexpected_tokens:
            findings.append(
                QualityFinding(
                    code="numeric.token_mismatch",
                    severity=FindingSeverity.CRITICAL,
                    message="Numeric tokens differ from the extracted source.",
                    metric="numeric_fidelity",
                    observed=numeric.score,
                    threshold=1.0,
                )
            )

    missing_provenance = 0
    for block in materialized:
        if not block.has_provenance:
            missing_provenance += 1
            findings.append(
                QualityFinding(
                    code="provenance.block_missing",
                    severity=FindingSeverity.CRITICAL,
                    message="A persisted block has no page or canonical source reference.",
                    block_id=block.block_id,
                )
            )

    table_scores: list[float] = []
    for block in materialized:
        if block.block_type != "table":
            continue
        if block.table_invalid or block.table is None:
            findings.append(
                QualityFinding(
                    code="table.structure_invalid",
                    severity=FindingSeverity.CRITICAL,
                    message="A table block has no valid canonical table grid.",
                    block_id=block.block_id,
                    metric="table_fidelity",
                )
            )
            table_scores.append(0.0)
            continue
        table_findings = validate_table(block.table)
        findings.extend(table_findings)
        table_numeric = compare_numeric_tokens(
            "\n".join(cell.raw_text for cell in block.table.cells),
            block.candidate_text,
        ).score
        table_error = any(
            finding.severity in {FindingSeverity.ERROR, FindingSeverity.CRITICAL}
            for finding in table_findings
        )
        if table_error:
            findings.append(
                QualityFinding(
                    code="table.integrity_critical",
                    severity=FindingSeverity.CRITICAL,
                    message="Canonical table integrity failed a deterministic gate.",
                    block_id=block.block_id,
                    metric="table_fidelity",
                )
            )
        table_scores.append(0.0 if table_error else table_numeric)

    anomaly_findings = tuple(findings)
    markdown_codes = frozenset(
        {
            "markdown.multiple_h1",
            "markdown.heading_level_jump",
            "markdown.null_byte",
        }
    )
    hierarchy_codes = frozenset(
        {
            "markdown.multiple_h1",
            "markdown.heading_level_jump",
        }
    )
    repetition_excess = max(0.0, candidate_repetition - source_repetition)
    vector = QualityVector(
        text_fidelity=(
            _bounded_similarity(reference, candidate)
            if reference
            else ocr_accuracy
        ),
        numeric_fidelity=numeric_score,
        layout_fidelity=_layout_fidelity(materialized),
        table_fidelity=(min(table_scores) if table_scores else None),
        hierarchy_validity=(
            _penalty_score(anomaly_findings, codes=hierarchy_codes)
            if candidate
            else 0.0
        ),
        provenance_coverage=(
            (len(materialized) - missing_provenance) / len(materialized)
            if materialized
            else 0.0
        ),
        repetition_safety=(
            max(0.0, 1.0 - repetition_excess) if candidate else 0.0
        ),
        language_consistency=(
            _language_consistency(reference, candidate)
            if reference
            else charset_plausibility
        ),
        markdown_validity=(
            _penalty_score(anomaly_findings, codes=markdown_codes)
            if candidate
            else 0.0
        ),
    )
    evaluation = evaluate_quality(
        vector,
        findings=anomaly_findings,
        high_risk=high_risk,
        failed_attempts=failed_attempts,
        hard_failure=not bool(candidate.strip()),
    )
    finding_codes = {finding.code for finding in evaluation.findings}
    signal = QualitySignal(
        score=evaluation.overall_score,
        passed=evaluation.status
        in {QualityStatus.PASS, QualityStatus.PASS_WITH_WARNINGS},
        empty_output="text.empty" in finding_codes,
        repetition_failure="text.repetition" in finding_codes,
        critical_numeric_mismatch="numeric.token_mismatch" in finding_codes,
        critical_table_error=bool(
            {"table.structure_invalid", "table.integrity_critical"} & finding_codes
        ),
    )
    return PageQualityAssessment(evaluation=evaluation, signal=signal)
