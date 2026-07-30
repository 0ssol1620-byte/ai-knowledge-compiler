"""Objective, provenance-aware quality gates."""

from .agreement import compare_engine_outputs
from .anomalies import markdown_anomalies, repeated_ngram_ratio, text_anomalies
from .evaluator import (
    HIGH_RISK_WEIGHTS,
    NORMAL_WEIGHTS,
    evaluate_quality,
    weighted_quality,
)
from .evidence import (
    source_coverage_ratio,
    validate_block_provenance,
    validate_knowledge_evidence,
    validate_relation_evidence,
)
from .models import (
    AgreementScore,
    FindingSeverity,
    QualityEvaluation,
    QualityFinding,
    QualityStatus,
    QualityVector,
)
from .numeric import NumericComparison, compare_numeric_tokens, extract_numeric_tokens
from .tables import table_numeric_fidelity, table_shape_fidelity, validate_table

__all__ = [
    "HIGH_RISK_WEIGHTS",
    "NORMAL_WEIGHTS",
    "AgreementScore",
    "FindingSeverity",
    "NumericComparison",
    "QualityEvaluation",
    "QualityFinding",
    "QualityStatus",
    "QualityVector",
    "compare_engine_outputs",
    "compare_numeric_tokens",
    "evaluate_quality",
    "extract_numeric_tokens",
    "markdown_anomalies",
    "repeated_ngram_ratio",
    "source_coverage_ratio",
    "table_numeric_fidelity",
    "table_shape_fidelity",
    "text_anomalies",
    "validate_block_provenance",
    "validate_knowledge_evidence",
    "validate_relation_evidence",
    "validate_table",
    "weighted_quality",
]
