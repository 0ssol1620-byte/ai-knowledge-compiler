"""Fail-closed authority-to-geometry matching for financial numeric cells.

The parser is allowed to describe a table and locate its cells.  It is never
allowed to become the numeric authority when an OpenDART or SEC fact exists.
This module joins those two evidence planes with a constrained, deterministic
bipartite matcher and makes every unsafe outcome non-publishable.
"""

from __future__ import annotations

import math
import re
import unicodedata
from datetime import date
from decimal import Decimal
from difflib import SequenceMatcher
from enum import StrEnum
from typing import Annotated, Literal

from akc_cir import BBox1000, Confidence, ContractModel, NonEmptyStr, StableId
from pydantic import Field, field_validator, model_validator


class AuthoritySource(StrEnum):
    """Numeric sources permitted to overrule parser-rendered values."""

    DART_XBRL = "dart_opendart_xml_xbrl"
    SEC_INLINE_XBRL = "sec_inline_xbrl"


class GeometrySource(StrEnum):
    """Rendered geometry plane paired with an authority source."""

    PDF_CELL = "pdf_cell"
    RENDERED_HTML_REGION = "rendered_html_region"


class GeometryWordRole(StrEnum):
    VALUE = "value"
    LABEL = "label"
    ROW_HEADER = "row_header"
    COLUMN_HEADER = "column_header"


class NumericResolutionState(StrEnum):
    AUTHORITY_VERIFIED = "AUTHORITY_VERIFIED"
    UNRESOLVED = "UNRESOLVED"


class NumericMismatchCode(StrEnum):
    CRITICAL_NUMERIC_MISMATCH = "critical_numeric_mismatch"
    WRONG_SIGN = "wrong_sign"
    WRONG_UNIT_SCALE = "wrong_unit_scale"
    WRONG_PERIOD = "wrong_period"


PositiveScale = Annotated[int, Field(gt=0)]


class NumericCellKey(ContractModel):
    """Stable financial cell identity shared by authority and parser planes."""

    entity_id: StableId
    statement: NonEmptyStr
    concept: NonEmptyStr
    period_start: date | None = None
    period_end: date | None = None
    instant: date | None = None
    unit: NonEmptyStr
    scale: PositiveScale
    dimensions: dict[str, str] = Field(default_factory=dict)
    page: Annotated[int, Field(ge=1)]
    row_key: NonEmptyStr
    column_key: NonEmptyStr

    @field_validator("dimensions")
    @classmethod
    def validate_dimensions(cls, value: dict[str, str]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for key, member in value.items():
            clean_key = key.strip()
            clean_member = member.strip()
            if not clean_key or not clean_member:
                raise ValueError("dimension names and members must be non-empty")
            if clean_key in normalized:
                raise ValueError("dimension names must be unique after normalization")
            normalized[clean_key] = clean_member
        return dict(sorted(normalized.items()))

    @model_validator(mode="after")
    def validate_period(self) -> NumericCellKey:
        has_duration = self.period_start is not None or self.period_end is not None
        if self.instant is not None:
            if has_duration:
                raise ValueError("instant and duration periods are mutually exclusive")
            return self
        if self.period_start is None or self.period_end is None:
            raise ValueError("duration periods require both periodStart and periodEnd")
        if self.period_start > self.period_end:
            raise ValueError("periodStart must not exceed periodEnd")
        return self

    @property
    def authority_period_end(self) -> date:
        value = self.instant if self.instant is not None else self.period_end
        if value is None:  # pragma: no cover - protected by model validation
            raise ValueError("cell key has no authority period")
        return value


class DartXbrlProvenance(ContractModel):
    """OpenDART XML/XBRL fact and its corresponding source PDF."""

    source: Literal[AuthoritySource.DART_XBRL] = AuthoritySource.DART_XBRL
    entity_id: StableId
    receipt_number: Annotated[str, Field(pattern=r"^\d{14}$")]
    report_code: NonEmptyStr
    xml_fact_id: StableId
    xml_document_uri: NonEmptyStr
    pdf_document_uri: NonEmptyStr
    fact_period_start: date | None = None
    fact_period_end: date | None = None
    fact_instant: date | None = None

    @model_validator(mode="after")
    def validate_fact_period(self) -> DartXbrlProvenance:
        _validate_source_period(
            self.fact_period_start,
            self.fact_period_end,
            self.fact_instant,
        )
        return self


class SecInlineXbrlProvenance(ContractModel):
    """SEC Inline XBRL fact anchored to filing HTML and accession metadata."""

    source: Literal[AuthoritySource.SEC_INLINE_XBRL] = AuthoritySource.SEC_INLINE_XBRL
    entity_id: StableId
    accession_number: Annotated[str, Field(pattern=r"^\d{10}-\d{2}-\d{6}$")]
    form: NonEmptyStr
    inline_xbrl_fact_id: StableId
    filing_html_uri: NonEmptyStr
    fact_period_start: date | None = None
    fact_period_end: date | None = None
    fact_instant: date | None = None

    @field_validator("form")
    @classmethod
    def canonical_form(cls, value: str) -> str:
        return value.upper()

    @model_validator(mode="after")
    def validate_fact_period(self) -> SecInlineXbrlProvenance:
        _validate_source_period(
            self.fact_period_start,
            self.fact_period_end,
            self.fact_instant,
        )
        return self


AuthorityProvenance = Annotated[
    DartXbrlProvenance | SecInlineXbrlProvenance,
    Field(discriminator="source"),
]


class AuthorityNumericFact(ContractModel):
    """A value whose digits, sign, unit, and period come from filing authority."""

    fact_id: StableId
    key: NumericCellKey
    xbrl_label: NonEmptyStr
    value: Decimal
    provenance: AuthorityProvenance

    @field_validator("value")
    @classmethod
    def require_finite_value(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("authority values must be finite")
        return value

    @model_validator(mode="after")
    def bind_fact_to_filing(self) -> AuthorityNumericFact:
        if self.key.entity_id != self.provenance.entity_id:
            raise ValueError("authority key entity does not match filing entity")
        if (
            self.key.period_start != self.provenance.fact_period_start
            or self.key.period_end != self.provenance.fact_period_end
            or self.key.instant != self.provenance.fact_instant
        ):
            raise ValueError("authority key period does not match filing period")
        return self


class GeometryWord(ContractModel):
    text: NonEmptyStr
    bbox1000: BBox1000
    role: GeometryWordRole


class ParserNumericCell(ContractModel):
    """Parser-owned structure and geometry with its original numeric rendering."""

    parser_cell_id: StableId
    key: NumericCellKey
    geometry_source: GeometrySource
    source_document_uri: NonEmptyStr
    label: NonEmptyStr
    row_header: NonEmptyStr
    column_header: NonEmptyStr
    original_parser_number: NonEmptyStr
    parser_value: Decimal
    bbox1000: BBox1000
    words: tuple[GeometryWord, ...]

    @field_validator("parser_value")
    @classmethod
    def require_finite_value(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("parser values must be finite")
        return value

    @model_validator(mode="after")
    def require_cell_geometry(self) -> ParserNumericCell:
        value_words = tuple(word for word in self.words if word.role is GeometryWordRole.VALUE)
        if not value_words:
            raise ValueError("numeric cells require at least one value word")
        if any(_intersection_ratio(word.bbox1000, self.bbox1000) <= 0 for word in value_words):
            raise ValueError("value words must intersect the numeric cell bbox")
        return self


class GeometryMatcherConfig(ContractModel):
    """Auditable scoring policy; weights must describe a complete probability mass."""

    pdf_words_cells_weight: Annotated[float, Field(ge=0, le=1)] = 0.12
    xbrl_label_weight: Annotated[float, Field(ge=0, le=1)] = 0.15
    numeric_value_weight: Annotated[float, Field(ge=0, le=1)] = 0.15
    page_weight: Annotated[float, Field(ge=0, le=1)] = 0.10
    row_column_headers_weight: Annotated[float, Field(ge=0, le=1)] = 0.13
    statement_context_weight: Annotated[float, Field(ge=0, le=1)] = 0.10
    unit_scale_weight: Annotated[float, Field(ge=0, le=1)] = 0.10
    fuzzy_label_weight: Annotated[float, Field(ge=0, le=1)] = 0.15
    minimum_match_score: Confidence = 0.62
    minimum_label_similarity: Confidence = 0.78
    page_tolerance: Annotated[int, Field(ge=0, le=2)] = 0
    ambiguity_epsilon: Annotated[float, Field(ge=0, le=0.05)] = 0.000001

    @model_validator(mode="after")
    def validate_weight_mass(self) -> GeometryMatcherConfig:
        total = (
            self.pdf_words_cells_weight
            + self.xbrl_label_weight
            + self.numeric_value_weight
            + self.page_weight
            + self.row_column_headers_weight
            + self.statement_context_weight
            + self.unit_scale_weight
            + self.fuzzy_label_weight
        )
        if not math.isclose(total, 1.0, abs_tol=1e-9):
            raise ValueError("geometry matcher weights must sum to 1.0")
        return self


class GeometryMatchSignals(ContractModel):
    pdf_words_cells: Confidence
    xbrl_label: Confidence
    numeric_value: Confidence
    page: Confidence
    row_column_headers: Confidence
    statement_context: Confidence
    unit_scale: Confidence
    fuzzy_label: Confidence
    total: Confidence


class NumericAuthorityMerge(ContractModel):
    """Audit record for a structurally matched cell, publishable only if the batch passes."""

    authority_fact_id: StableId
    parser_cell_id: StableId
    key: NumericCellKey
    output_value: Decimal
    original_parser_number: NonEmptyStr
    original_parser_value: Decimal
    parser_value_in_authority_unit: Decimal
    source_bbox1000: BBox1000
    structure_source: Literal["parser"] = "parser"
    value_source: Literal["authority"] = "authority"
    bbox_source: Literal["geometry_matcher"] = "geometry_matcher"
    signals: GeometryMatchSignals
    mismatch_codes: tuple[NumericMismatchCode, ...] = ()


class NumericDiagnosticMatch(ContractModel):
    """Near-identity pair retained solely to explain a critical-key mismatch."""

    authority_fact_id: StableId
    parser_cell_id: StableId
    original_parser_number: NonEmptyStr
    source_bbox1000: BBox1000
    signals: GeometryMatchSignals
    mismatch_codes: tuple[NumericMismatchCode, ...]

    @field_validator("mismatch_codes")
    @classmethod
    def require_mismatch(
        cls,
        value: tuple[NumericMismatchCode, ...],
    ) -> tuple[NumericMismatchCode, ...]:
        if not value:
            raise ValueError("diagnostic matches require at least one mismatch")
        return value


class NumericHardGate(ContractModel):
    """The six v4 numeric release invariants.  Every counter must be zero."""

    critical_numeric_mismatch: Annotated[int, Field(ge=0)]
    unsupported_numeric_row: Annotated[int, Field(ge=0)]
    missing_authoritative_row: Annotated[int, Field(ge=0)]
    wrong_sign: Annotated[int, Field(ge=0)]
    wrong_unit_scale: Annotated[int, Field(ge=0)]
    wrong_period: Annotated[int, Field(ge=0)]
    passed: bool

    @model_validator(mode="after")
    def prevent_forged_pass(self) -> NumericHardGate:
        expected = all(
            count == 0
            for count in (
                self.critical_numeric_mismatch,
                self.unsupported_numeric_row,
                self.missing_authoritative_row,
                self.wrong_sign,
                self.wrong_unit_scale,
                self.wrong_period,
            )
        )
        if self.passed is not expected:
            raise ValueError("passed must equal the conjunction of all six zero gates")
        return self


class NumericGeometryResult(ContractModel):
    state: NumericResolutionState
    matches: tuple[NumericAuthorityMerge, ...]
    diagnostic_matches: tuple[NumericDiagnosticMatch, ...]
    publishable_matches: tuple[NumericAuthorityMerge, ...]
    hard_gate: NumericHardGate
    reason_codes: tuple[str, ...]
    billable: bool
    human_review_allowed: Literal[False] = False

    @model_validator(mode="after")
    def enforce_fail_closed_release(self) -> NumericGeometryResult:
        expected_state = (
            NumericResolutionState.AUTHORITY_VERIFIED
            if self.hard_gate.passed
            else NumericResolutionState.UNRESOLVED
        )
        if self.state is not expected_state:
            raise ValueError("numeric state must be derived from the hard gate")
        expected_publishable = self.matches if self.hard_gate.passed else ()
        if self.publishable_matches != expected_publishable:
            raise ValueError("failed numeric batches must expose no publishable matches")
        if self.billable is not self.hard_gate.passed:
            raise ValueError("only authority-verified numeric batches are billable")
        return self


def _normalize_label(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(re.findall(r"[\w]+", normalized, flags=re.UNICODE))


def _validate_source_period(
    period_start: date | None,
    period_end: date | None,
    instant: date | None,
) -> None:
    has_duration = period_start is not None or period_end is not None
    if instant is not None:
        if has_duration:
            raise ValueError("source instant and duration periods are mutually exclusive")
        return
    if period_start is None or period_end is None:
        raise ValueError("source duration periods require both start and end")
    if period_start > period_end:
        raise ValueError("source period start must not exceed end")


def _fuzzy_similarity(left: str, right: str) -> float:
    left_normalized = _normalize_label(left)
    right_normalized = _normalize_label(right)
    if not left_normalized or not right_normalized:
        return 0.0
    if left_normalized == right_normalized:
        return 1.0
    sequence = SequenceMatcher(None, left_normalized, right_normalized, autojunk=False).ratio()
    left_tokens = set(left_normalized.split())
    right_tokens = set(right_normalized.split())
    union = left_tokens | right_tokens
    token_score = len(left_tokens & right_tokens) / len(union) if union else 0.0
    containment = (
        min(len(left_normalized), len(right_normalized))
        / max(len(left_normalized), len(right_normalized))
        if left_normalized in right_normalized or right_normalized in left_normalized
        else 0.0
    )
    return min(1.0, max(sequence, token_score, containment))


def _intersection_ratio(inner: BBox1000, outer: BBox1000) -> float:
    ix1, iy1, ix2, iy2 = inner.as_tuple()
    ox1, oy1, ox2, oy2 = outer.as_tuple()
    intersection_width = max(0, min(ix2, ox2) - max(ix1, ox1))
    intersection_height = max(0, min(iy2, oy2) - max(iy1, oy1))
    inner_area = (ix2 - ix1) * (iy2 - iy1)
    return (intersection_width * intersection_height) / inner_area


def _period_equal(left: NumericCellKey, right: NumericCellKey) -> bool:
    return (
        left.period_start == right.period_start
        and left.period_end == right.period_end
        and left.instant == right.instant
    )


def _unit_scale_equal(left: NumericCellKey, right: NumericCellKey) -> bool:
    return _normalize_label(left.unit) == _normalize_label(right.unit) and left.scale == right.scale


def _dimensions_equal(left: NumericCellKey, right: NumericCellKey) -> bool:
    return {
        _normalize_label(key): _normalize_label(value) for key, value in left.dimensions.items()
    } == {_normalize_label(key): _normalize_label(value) for key, value in right.dimensions.items()}


def _source_compatible(fact: AuthorityNumericFact, cell: ParserNumericCell) -> bool:
    provenance = fact.provenance
    if isinstance(provenance, DartXbrlProvenance):
        return (
            cell.geometry_source is GeometrySource.PDF_CELL
            and cell.source_document_uri == provenance.pdf_document_uri
        )
    return (
        cell.geometry_source is GeometrySource.RENDERED_HTML_REGION
        and cell.source_document_uri == provenance.filing_html_uri
    )


def _structural_constraints(
    fact: AuthorityNumericFact,
    cell: ParserNumericCell,
    config: GeometryMatcherConfig,
) -> bool:
    authority = fact.key
    parser = cell.key
    if authority.entity_id != parser.entity_id:
        return False
    if _normalize_label(authority.statement) != _normalize_label(parser.statement):
        return False
    if _normalize_label(authority.concept) != _normalize_label(parser.concept):
        return False
    if not _dimensions_equal(authority, parser):
        return False
    if abs(authority.page - parser.page) > config.page_tolerance:
        return False
    if not _source_compatible(fact, cell):
        return False

    row_exact = _normalize_label(authority.row_key) == _normalize_label(parser.row_key)
    row_label = max(
        _fuzzy_similarity(fact.xbrl_label, cell.label),
        _fuzzy_similarity(authority.row_key, cell.row_header),
    )
    column_exact = _normalize_label(authority.column_key) == _normalize_label(parser.column_key)
    column_label = _fuzzy_similarity(authority.column_key, cell.column_header)
    return (row_exact or row_label >= config.minimum_label_similarity) and (
        column_exact or column_label >= config.minimum_label_similarity
    )


def _strict_constraints(
    fact: AuthorityNumericFact,
    cell: ParserNumericCell,
    config: GeometryMatcherConfig,
) -> bool:
    return (
        _structural_constraints(fact, cell, config)
        and _period_equal(fact.key, cell.key)
        and _unit_scale_equal(fact.key, cell.key)
    )


def _diagnostic_constraints(
    fact: AuthorityNumericFact,
    cell: ParserNumericCell,
    config: GeometryMatcherConfig,
) -> bool:
    if not _structural_constraints(fact, cell, config):
        return False
    return not _period_equal(fact.key, cell.key) or not _unit_scale_equal(fact.key, cell.key)


def _signal_scores(
    fact: AuthorityNumericFact,
    cell: ParserNumericCell,
    config: GeometryMatcherConfig,
) -> GeometryMatchSignals:
    label_words = " ".join(
        word.text for word in cell.words if word.role is not GeometryWordRole.VALUE
    )
    lexical_words = _fuzzy_similarity(fact.xbrl_label, label_words or cell.label)
    value_words = tuple(word for word in cell.words if word.role is GeometryWordRole.VALUE)
    geometry_coverage = sum(
        _intersection_ratio(word.bbox1000, cell.bbox1000) for word in value_words
    ) / len(value_words)
    words_cells = (lexical_words + geometry_coverage) / 2
    exact_label = float(_normalize_label(fact.xbrl_label) == _normalize_label(cell.label))
    xbrl_label = max(exact_label, _fuzzy_similarity(fact.xbrl_label, cell.row_header))
    parser_authority_value = cell.parser_value * cell.key.scale
    numeric_value = float(parser_authority_value == fact.value)
    page = max(0.0, 1.0 - abs(fact.key.page - cell.key.page) / (config.page_tolerance + 1))
    row_headers = _fuzzy_similarity(fact.key.row_key, cell.row_header)
    column_headers = _fuzzy_similarity(fact.key.column_key, cell.column_header)
    headers = (row_headers + column_headers) / 2
    statement = float(_normalize_label(fact.key.statement) == _normalize_label(cell.key.statement))
    unit_scale = float(_unit_scale_equal(fact.key, cell.key))
    fuzzy_label = _fuzzy_similarity(fact.xbrl_label, cell.label)
    total = (
        words_cells * config.pdf_words_cells_weight
        + xbrl_label * config.xbrl_label_weight
        + numeric_value * config.numeric_value_weight
        + page * config.page_weight
        + headers * config.row_column_headers_weight
        + statement * config.statement_context_weight
        + unit_scale * config.unit_scale_weight
        + fuzzy_label * config.fuzzy_label_weight
    )
    return GeometryMatchSignals(
        pdf_words_cells=min(1.0, max(0.0, words_cells)),
        xbrl_label=min(1.0, max(0.0, xbrl_label)),
        numeric_value=numeric_value,
        page=min(1.0, max(0.0, page)),
        row_column_headers=min(1.0, max(0.0, headers)),
        statement_context=statement,
        unit_scale=unit_scale,
        fuzzy_label=min(1.0, max(0.0, fuzzy_label)),
        total=min(1.0, max(0.0, total)),
    )


def _maximum_weight_assignment(weights: list[list[float | None]]) -> dict[int, int]:
    """Return row-to-column assignments using a square Hungarian construction.

    Every real row and column receives its own zero-valued dummy counterpart, so
    an ineligible edge is never selected merely to complete a permutation.
    """

    row_count = len(weights)
    column_count = len(weights[0]) if weights else 0
    if row_count == 0 or column_count == 0:
        return {}
    size = row_count + column_count
    invalid_weight = -1_000_000.0
    square = [[0.0 for _ in range(size)] for _ in range(size)]
    for row in range(row_count):
        for column in range(column_count):
            value = weights[row][column]
            square[row][column] = invalid_weight if value is None else value

    maximum = max(max(row) for row in square)
    costs = [[maximum - value for value in row] for row in square]
    potentials_rows = [0.0] * (size + 1)
    potentials_columns = [0.0] * (size + 1)
    matching = [0] * (size + 1)
    predecessor = [0] * (size + 1)
    for row in range(1, size + 1):
        matching[0] = row
        minimums = [math.inf] * (size + 1)
        used = [False] * (size + 1)
        column0 = 0
        while True:
            used[column0] = True
            row0 = matching[column0]
            delta = math.inf
            column1 = 0
            for column in range(1, size + 1):
                if used[column]:
                    continue
                current = (
                    costs[row0 - 1][column - 1] - potentials_rows[row0] - potentials_columns[column]
                )
                if current < minimums[column]:
                    minimums[column] = current
                    predecessor[column] = column0
                if minimums[column] < delta:
                    delta = minimums[column]
                    column1 = column
            for column in range(size + 1):
                if used[column]:
                    potentials_rows[matching[column]] += delta
                    potentials_columns[column] -= delta
                else:
                    minimums[column] -= delta
            column0 = column1
            if matching[column0] == 0:
                break
        while True:
            column1 = predecessor[column0]
            matching[column0] = matching[column1]
            column0 = column1
            if column0 == 0:
                break

    assignment: dict[int, int] = {}
    for column in range(1, size + 1):
        row = matching[column]
        if 1 <= row <= row_count and 1 <= column <= column_count:
            value = weights[row - 1][column - 1]
            if value is not None and value > 0:
                assignment[row - 1] = column - 1
    return assignment


def _ambiguous_nodes(
    weights: list[list[float | None]],
    assignment: dict[int, int],
    epsilon: float,
) -> tuple[set[int], set[int]]:
    ambiguous_rows: set[int] = set()
    ambiguous_columns: set[int] = set()
    for row, column in assignment.items():
        selected = weights[row][column]
        if selected is None:
            continue
        row_ties = {
            candidate
            for candidate, score in enumerate(weights[row])
            if candidate != column and score is not None and abs(score - selected) <= epsilon
        }
        column_ties = {
            candidate
            for candidate in range(len(weights))
            if candidate != row
            and weights[candidate][column] is not None
            and abs(weights[candidate][column] - selected) <= epsilon  # type: ignore[operator]
        }
        if row_ties or column_ties:
            ambiguous_rows.add(row)
            ambiguous_rows.update(column_ties)
            ambiguous_columns.add(column)
            ambiguous_columns.update(row_ties)
    return ambiguous_rows, ambiguous_columns


def _mismatch_codes(
    fact: AuthorityNumericFact,
    cell: ParserNumericCell,
) -> tuple[NumericMismatchCode, ...]:
    codes: list[NumericMismatchCode] = []
    parser_authority_value = cell.parser_value * cell.key.scale
    if parser_authority_value != fact.value:
        codes.append(NumericMismatchCode.CRITICAL_NUMERIC_MISMATCH)
    if (
        parser_authority_value != 0
        and fact.value != 0
        and (parser_authority_value > 0) != (fact.value > 0)
    ):
        codes.append(NumericMismatchCode.WRONG_SIGN)
    if not _unit_scale_equal(fact.key, cell.key):
        codes.append(NumericMismatchCode.WRONG_UNIT_SCALE)
    if not _period_equal(fact.key, cell.key):
        codes.append(NumericMismatchCode.WRONG_PERIOD)
    return tuple(codes)


def _make_merge(
    fact: AuthorityNumericFact,
    cell: ParserNumericCell,
    signals: GeometryMatchSignals,
) -> NumericAuthorityMerge:
    return NumericAuthorityMerge(
        authority_fact_id=fact.fact_id,
        parser_cell_id=cell.parser_cell_id,
        key=fact.key,
        output_value=fact.value,
        original_parser_number=cell.original_parser_number,
        original_parser_value=cell.parser_value,
        parser_value_in_authority_unit=cell.parser_value * cell.key.scale,
        source_bbox1000=cell.bbox1000,
        signals=signals,
        mismatch_codes=_mismatch_codes(fact, cell),
    )


def _reason_codes(gate: NumericHardGate, *, ambiguity: bool) -> tuple[str, ...]:
    reasons: list[str] = []
    if gate.critical_numeric_mismatch:
        reasons.append(NumericMismatchCode.CRITICAL_NUMERIC_MISMATCH.value)
    if gate.unsupported_numeric_row:
        reasons.append("unsupported_numeric_row")
    if gate.missing_authoritative_row:
        reasons.append("missing_authoritative_row")
    if gate.wrong_sign:
        reasons.append(NumericMismatchCode.WRONG_SIGN.value)
    if gate.wrong_unit_scale:
        reasons.append(NumericMismatchCode.WRONG_UNIT_SCALE.value)
    if gate.wrong_period:
        reasons.append(NumericMismatchCode.WRONG_PERIOD.value)
    if ambiguity:
        reasons.append("ambiguous_bipartite_match")
    return tuple(reasons)


def match_numeric_geometry(
    authority_facts: tuple[AuthorityNumericFact, ...],
    parser_cells: tuple[ParserNumericCell, ...],
    *,
    config: GeometryMatcherConfig | None = None,
) -> NumericGeometryResult:
    """Join authority values to parser geometry and enforce the six hard gates.

    Matching happens in two passes.  The first accepts only exact critical-key
    compatibility.  The second pairs otherwise identical cells solely to
    diagnose period or unit/scale faults.  Diagnostic pairs can never publish.
    """

    policy = config or GeometryMatcherConfig()
    facts = tuple(sorted(authority_facts, key=lambda item: item.fact_id))
    cells = tuple(sorted(parser_cells, key=lambda item: item.parser_cell_id))
    if len({fact.fact_id for fact in facts}) != len(facts):
        raise ValueError("authority fact IDs must be unique")
    if len({cell.parser_cell_id for cell in cells}) != len(cells):
        raise ValueError("parser cell IDs must be unique")

    signal_matrix = [[_signal_scores(fact, cell, policy) for cell in cells] for fact in facts]
    strict_weights: list[list[float | None]] = [
        [
            signals.total
            if _strict_constraints(fact, cell, policy)
            and signals.total >= policy.minimum_match_score
            else None
            for cell, signals in zip(cells, signal_row, strict=True)
        ]
        for fact, signal_row in zip(facts, signal_matrix, strict=True)
    ]
    strict_assignment = _maximum_weight_assignment(strict_weights)
    ambiguous_fact_rows, ambiguous_cell_columns = _ambiguous_nodes(
        strict_weights,
        strict_assignment,
        policy.ambiguity_epsilon,
    )

    accepted_assignment = {
        row: column
        for row, column in strict_assignment.items()
        if row not in ambiguous_fact_rows and column not in ambiguous_cell_columns
    }
    matched_fact_rows = set(accepted_assignment)
    matched_cell_columns = set(accepted_assignment.values())
    matches = tuple(
        _make_merge(facts[row], cells[column], signal_matrix[row][column])
        for row, column in sorted(accepted_assignment.items())
    )

    remaining_fact_rows = [
        row
        for row in range(len(facts))
        if row not in matched_fact_rows and row not in ambiguous_fact_rows
    ]
    remaining_cell_columns = [
        column
        for column in range(len(cells))
        if column not in matched_cell_columns and column not in ambiguous_cell_columns
    ]
    diagnostic_weights: list[list[float | None]] = [
        [
            signal_matrix[row][column].total
            if _diagnostic_constraints(facts[row], cells[column], policy)
            and signal_matrix[row][column].total >= policy.minimum_match_score
            else None
            for column in remaining_cell_columns
        ]
        for row in remaining_fact_rows
    ]
    relative_diagnostic_assignment = _maximum_weight_assignment(diagnostic_weights)
    diagnostic_assignment = {
        remaining_fact_rows[row]: remaining_cell_columns[column]
        for row, column in relative_diagnostic_assignment.items()
    }
    diagnostic_matches = tuple(
        NumericDiagnosticMatch(
            authority_fact_id=facts[row].fact_id,
            parser_cell_id=cells[column].parser_cell_id,
            original_parser_number=cells[column].original_parser_number,
            source_bbox1000=cells[column].bbox1000,
            signals=signal_matrix[row][column],
            mismatch_codes=_mismatch_codes(facts[row], cells[column]),
        )
        for row, column in sorted(diagnostic_assignment.items())
    )
    diagnosed_fact_rows = set(diagnostic_assignment)
    diagnosed_cell_columns = set(diagnostic_assignment.values())

    all_codes = tuple(code for match in matches for code in match.mismatch_codes) + tuple(
        code for match in diagnostic_matches for code in match.mismatch_codes
    )
    missing_authoritative = len(facts) - len(matched_fact_rows) - len(diagnosed_fact_rows)
    unsupported_parser = len(cells) - len(matched_cell_columns) - len(diagnosed_cell_columns)
    gate_values = {
        "critical_numeric_mismatch": all_codes.count(NumericMismatchCode.CRITICAL_NUMERIC_MISMATCH),
        "unsupported_numeric_row": unsupported_parser,
        "missing_authoritative_row": missing_authoritative,
        "wrong_sign": all_codes.count(NumericMismatchCode.WRONG_SIGN),
        "wrong_unit_scale": all_codes.count(NumericMismatchCode.WRONG_UNIT_SCALE),
        "wrong_period": all_codes.count(NumericMismatchCode.WRONG_PERIOD),
    }
    passed = all(value == 0 for value in gate_values.values())
    gate = NumericHardGate(**gate_values, passed=passed)
    ambiguity = bool(ambiguous_fact_rows or ambiguous_cell_columns)
    return NumericGeometryResult(
        state=(
            NumericResolutionState.AUTHORITY_VERIFIED
            if passed
            else NumericResolutionState.UNRESOLVED
        ),
        matches=matches,
        diagnostic_matches=diagnostic_matches,
        publishable_matches=matches if passed else (),
        hard_gate=gate,
        reason_codes=_reason_codes(gate, ambiguity=ambiguity),
        billable=passed,
    )


__all__ = [
    "AuthorityNumericFact",
    "AuthorityProvenance",
    "AuthoritySource",
    "DartXbrlProvenance",
    "GeometryMatchSignals",
    "GeometryMatcherConfig",
    "GeometrySource",
    "GeometryWord",
    "GeometryWordRole",
    "NumericAuthorityMerge",
    "NumericCellKey",
    "NumericDiagnosticMatch",
    "NumericGeometryResult",
    "NumericHardGate",
    "NumericMismatchCode",
    "NumericResolutionState",
    "ParserNumericCell",
    "SecInlineXbrlProvenance",
    "match_numeric_geometry",
]
