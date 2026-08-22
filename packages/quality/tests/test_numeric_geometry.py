from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from akc_cir import BBox1000
from akc_quality import (
    AuthorityNumericFact,
    AuthoritySource,
    DartXbrlProvenance,
    GeometryMatcherConfig,
    GeometrySource,
    GeometryWord,
    GeometryWordRole,
    NumericCellKey,
    NumericHardGate,
    NumericMismatchCode,
    NumericResolutionState,
    ParserNumericCell,
    SecInlineXbrlProvenance,
    match_numeric_geometry,
)
from pydantic import ValidationError

DAY = date(2025, 12, 31)
START = date(2025, 1, 1)
PDF_URI = "r2://filings/dart/20250731000001.pdf"
XML_URI = "r2://filings/dart/20250731000001.xml"
SEC_URI = "https://www.sec.gov/Archives/edgar/data/320193/report.htm"


def _key(
    *,
    entity_id: str = "corp001",
    concept: str = "ifrs-full:Revenue",
    period_start: date | None = START,
    period_end: date | None = DAY,
    instant: date | None = None,
    unit: str = "KRW",
    scale: int = 1_000_000,
    page: int = 72,
    row_key: str = "revenue",
    column_key: str = "current_year",
    dimensions: dict[str, str] | None = None,
) -> NumericCellKey:
    return NumericCellKey(
        entity_id=entity_id,
        statement="CONSOLIDATED_INCOME_STATEMENT",
        concept=concept,
        period_start=period_start,
        period_end=period_end,
        instant=instant,
        unit=unit,
        scale=scale,
        dimensions=dimensions or {},
        page=page,
        row_key=row_key,
        column_key=column_key,
    )


def _dart_fact(
    *,
    fact_id: str = "fact-revenue-current",
    key: NumericCellKey | None = None,
    label: str = "매출액",
    value: Decimal = Decimal("123000000"),
) -> AuthorityNumericFact:
    cell_key = key or _key()
    return AuthorityNumericFact(
        fact_id=fact_id,
        key=cell_key,
        xbrl_label=label,
        value=value,
        provenance=DartXbrlProvenance(
            entity_id=cell_key.entity_id,
            receipt_number="20250731000001",
            report_code="11011",
            xml_fact_id=f"xml-{fact_id}",
            xml_document_uri=XML_URI,
            pdf_document_uri=PDF_URI,
            fact_period_start=cell_key.period_start,
            fact_period_end=cell_key.period_end,
            fact_instant=cell_key.instant,
        ),
    )


def _cell(
    *,
    parser_cell_id: str = "cell-revenue-current",
    key: NumericCellKey | None = None,
    label: str = "매출액",
    row_header: str = "revenue",
    column_header: str = "current year",
    original: str = "123",
    value: Decimal = Decimal("123"),
    geometry_source: GeometrySource = GeometrySource.PDF_CELL,
    source_document_uri: str = PDF_URI,
) -> ParserNumericCell:
    return ParserNumericCell(
        parser_cell_id=parser_cell_id,
        key=key or _key(),
        geometry_source=geometry_source,
        source_document_uri=source_document_uri,
        label=label,
        row_header=row_header,
        column_header=column_header,
        original_parser_number=original,
        parser_value=value,
        bbox1000=BBox1000((600, 300, 780, 340)),
        words=(
            GeometryWord(
                text=label,
                bbox1000=BBox1000((100, 300, 250, 340)),
                role=GeometryWordRole.ROW_HEADER,
            ),
            GeometryWord(
                text=original,
                bbox1000=BBox1000((620, 305, 760, 335)),
                role=GeometryWordRole.VALUE,
            ),
        ),
    )


def test_dart_authority_value_replaces_parser_value_and_retains_audit_geometry() -> None:
    fact = _dart_fact()
    cell = _cell(original="00123.0", value=Decimal("123"))

    result = match_numeric_geometry((fact,), (cell,))

    assert result.state is NumericResolutionState.AUTHORITY_VERIFIED
    assert result.hard_gate.passed
    assert result.billable and not result.human_review_allowed
    assert result.publishable_matches == result.matches
    merged = result.matches[0]
    assert merged.output_value == Decimal("123000000")
    assert merged.parser_value_in_authority_unit == Decimal("123000000")
    assert merged.original_parser_number == "00123.0"
    assert merged.original_parser_value == Decimal("123")
    assert merged.source_bbox1000 == cell.bbox1000
    assert merged.structure_source == "parser"
    assert merged.value_source == "authority"
    assert merged.signals.pdf_words_cells > 0


def test_sec_inline_xbrl_requires_and_matches_rendered_html_region() -> None:
    key = _key(
        entity_id="cik0000320193",
        concept="us-gaap:Assets",
        period_start=None,
        period_end=None,
        instant=DAY,
        unit="USD",
        scale=1,
        page=4,
        row_key="assets",
    )
    fact = AuthorityNumericFact(
        fact_id="sec-assets-current",
        key=key,
        xbrl_label="Total assets",
        value=Decimal("364980000000"),
        provenance=SecInlineXbrlProvenance(
            entity_id=key.entity_id,
            accession_number="0000320193-25-000079",
            form="10-k",
            inline_xbrl_fact_id="ix-assets-current",
            filing_html_uri=SEC_URI,
            fact_instant=DAY,
        ),
    )
    cell = _cell(
        key=key,
        label="Total assets",
        row_header="assets",
        original="364980000000",
        value=Decimal("364980000000"),
        geometry_source=GeometrySource.RENDERED_HTML_REGION,
        source_document_uri=SEC_URI,
    )

    result = match_numeric_geometry((fact,), (cell,))

    assert result.hard_gate.passed
    assert fact.provenance.source is AuthoritySource.SEC_INLINE_XBRL
    assert fact.provenance.form == "10-K"
    assert result.matches[0].source_bbox1000 == cell.bbox1000


@pytest.mark.parametrize(
    ("parser_value", "expected_sign"),
    [
        (Decimal("124"), 0),
        (Decimal("-123"), 1),
    ],
)
def test_numeric_or_sign_mismatch_is_a_non_billable_unresolved_batch(
    parser_value: Decimal,
    expected_sign: int,
) -> None:
    result = match_numeric_geometry(
        (_dart_fact(),),
        (_cell(value=parser_value, original=str(parser_value)),),
    )

    assert result.state is NumericResolutionState.UNRESOLVED
    assert not result.billable
    assert result.publishable_matches == ()
    assert result.matches[0].output_value == Decimal("123000000")
    assert result.matches[0].original_parser_number == str(parser_value)
    assert result.hard_gate.critical_numeric_mismatch == 1
    assert result.hard_gate.wrong_sign == expected_sign
    assert NumericMismatchCode.CRITICAL_NUMERIC_MISMATCH in result.matches[0].mismatch_codes


def test_zero_mismatch_is_numeric_but_not_falsely_classified_as_a_sign_error() -> None:
    result = match_numeric_geometry(
        (_dart_fact(),),
        (_cell(value=Decimal("0"), original="-"),),
    )
    assert result.hard_gate.critical_numeric_mismatch == 1
    assert result.hard_gate.wrong_sign == 0


def test_wrong_unit_and_scale_are_diagnosed_without_false_structural_release() -> None:
    wrong_key = _key(unit="USD", scale=1_000)
    result = match_numeric_geometry(
        (_dart_fact(),),
        (_cell(key=wrong_key, value=Decimal("123")),),
    )

    assert result.matches == ()
    assert len(result.diagnostic_matches) == 1
    assert result.hard_gate.wrong_unit_scale == 1
    assert result.hard_gate.missing_authoritative_row == 0
    assert result.hard_gate.unsupported_numeric_row == 0
    assert NumericMismatchCode.WRONG_UNIT_SCALE in result.diagnostic_matches[0].mismatch_codes
    assert result.publishable_matches == ()


def test_wrong_period_is_diagnosed_and_never_sent_to_human_review() -> None:
    wrong_period = _key(
        period_start=date(2024, 1, 1),
        period_end=date(2024, 12, 31),
    )
    result = match_numeric_geometry((_dart_fact(),), (_cell(key=wrong_period),))

    assert result.state is NumericResolutionState.UNRESOLVED
    assert result.hard_gate.wrong_period == 1
    assert result.hard_gate.missing_authoritative_row == 0
    assert result.hard_gate.unsupported_numeric_row == 0
    assert result.human_review_allowed is False
    assert "wrong_period" in result.reason_codes


def test_missing_and_unsupported_rows_are_counted_for_nonmatching_identity() -> None:
    unrelated_key = _key(concept="ifrs-full:Cash", row_key="cash")
    result = match_numeric_geometry(
        (_dart_fact(),),
        (_cell(key=unrelated_key, label="cash", row_header="cash"),),
    )

    assert result.hard_gate.missing_authoritative_row == 1
    assert result.hard_gate.unsupported_numeric_row == 1
    assert result.diagnostic_matches == ()
    assert result.publishable_matches == ()


def test_bipartite_constraints_map_reversed_current_and_prior_columns() -> None:
    prior_key = _key(
        period_start=date(2024, 1, 1),
        period_end=date(2024, 12, 31),
        column_key="prior_year",
    )
    current_fact = _dart_fact(fact_id="fact-current", value=Decimal("123000000"))
    prior_fact = _dart_fact(
        fact_id="fact-prior",
        key=prior_key,
        value=Decimal("99000000"),
    )
    current_cell = _cell(parser_cell_id="cell-z-current")
    prior_cell = _cell(
        parser_cell_id="cell-a-prior",
        key=prior_key,
        column_header="prior year",
        original="99",
        value=Decimal("99"),
    )

    result = match_numeric_geometry(
        (prior_fact, current_fact),
        (current_cell, prior_cell),
    )

    assert result.hard_gate.passed
    assert {(match.authority_fact_id, match.parser_cell_id) for match in result.matches} == {
        ("fact-current", "cell-z-current"),
        ("fact-prior", "cell-a-prior"),
    }


def test_equal_score_duplicate_geometry_is_rejected_as_ambiguous() -> None:
    first = _cell(parser_cell_id="cell-duplicate-a")
    second = _cell(parser_cell_id="cell-duplicate-b")

    result = match_numeric_geometry((_dart_fact(),), (second, first))

    assert result.matches == ()
    assert result.hard_gate.missing_authoritative_row == 1
    assert result.hard_gate.unsupported_numeric_row == 2
    assert "ambiguous_bipartite_match" in result.reason_codes
    assert result.state is NumericResolutionState.UNRESOLVED


def test_wrong_geometry_plane_or_source_document_cannot_match() -> None:
    wrong_plane = _cell(
        geometry_source=GeometrySource.RENDERED_HTML_REGION,
        source_document_uri=SEC_URI,
    )
    result = match_numeric_geometry((_dart_fact(),), (wrong_plane,))
    assert result.hard_gate.missing_authoritative_row == 1
    assert result.hard_gate.unsupported_numeric_row == 1


def test_dimension_mismatch_cannot_be_hidden_by_label_or_value_similarity() -> None:
    dimensional_fact = _dart_fact(key=_key(dimensions={"ifrs:SegmentsAxis": "corp:CloudMember"}))
    parser = _cell(key=_key(dimensions={"ifrs:SegmentsAxis": "corp:RetailMember"}))
    result = match_numeric_geometry((dimensional_fact,), (parser,))
    assert result.hard_gate.missing_authoritative_row == 1
    assert result.hard_gate.unsupported_numeric_row == 1


def test_cell_key_requires_exactly_one_well_formed_period() -> None:
    with pytest.raises(ValidationError, match="both periodStart and periodEnd"):
        _key(period_start=START, period_end=None)
    with pytest.raises(ValidationError, match="mutually exclusive"):
        _key(instant=DAY)
    with pytest.raises(ValidationError, match="must not exceed"):
        _key(period_start=DAY, period_end=START)
    with pytest.raises(ValidationError):
        _key(scale=0)


def test_authority_provenance_is_bound_to_entity_and_period() -> None:
    key = _key()
    provenance = DartXbrlProvenance(
        entity_id="corp999",
        receipt_number="20250731000001",
        report_code="11011",
        xml_fact_id="xml-fact-001",
        xml_document_uri=XML_URI,
        pdf_document_uri=PDF_URI,
        fact_period_start=START,
        fact_period_end=DAY,
    )
    with pytest.raises(ValidationError, match="entity"):
        AuthorityNumericFact(
            fact_id="fact-invalid-entity",
            key=key,
            xbrl_label="매출액",
            value=Decimal("1"),
            provenance=provenance,
        )
    with pytest.raises(ValidationError, match="period"):
        AuthorityNumericFact(
            fact_id="fact-invalid-period",
            key=key,
            xbrl_label="매출액",
            value=Decimal("1"),
            provenance=provenance.model_copy(
                update={"entity_id": key.entity_id, "fact_period_end": START}
            ),
        )


def test_parser_cell_requires_a_value_word_inside_its_bbox() -> None:
    base = _cell()
    with pytest.raises(ValidationError, match="value word"):
        ParserNumericCell(
            **base.model_dump(exclude={"words"}),
            words=(
                GeometryWord(
                    text="123",
                    bbox1000=BBox1000((10, 10, 20, 20)),
                    role=GeometryWordRole.VALUE,
                ),
            ),
        )


def test_duplicate_identifiers_are_rejected_before_matching() -> None:
    fact = _dart_fact()
    cell = _cell()
    with pytest.raises(ValueError, match="fact IDs"):
        match_numeric_geometry((fact, fact), (cell,))
    with pytest.raises(ValueError, match="cell IDs"):
        match_numeric_geometry((fact,), (cell, cell))


def test_hard_gate_cannot_claim_pass_with_nonzero_counter() -> None:
    with pytest.raises(ValidationError, match="six zero gates"):
        NumericHardGate(
            critical_numeric_mismatch=1,
            unsupported_numeric_row=0,
            missing_authoritative_row=0,
            wrong_sign=0,
            wrong_unit_scale=0,
            wrong_period=0,
            passed=True,
        )


def test_empty_numeric_plane_is_deterministically_safe() -> None:
    result = match_numeric_geometry((), ())
    assert result.hard_gate.passed
    assert result.state is NumericResolutionState.AUTHORITY_VERIFIED
    assert result.matches == result.publishable_matches == ()


def test_wire_contract_contains_complete_v4_cell_key() -> None:
    payload = _key().model_dump(mode="json", by_alias=True)
    assert payload == {
        "entityId": "corp001",
        "statement": "CONSOLIDATED_INCOME_STATEMENT",
        "concept": "ifrs-full:Revenue",
        "periodStart": "2025-01-01",
        "periodEnd": "2025-12-31",
        "instant": None,
        "unit": "KRW",
        "scale": 1000000,
        "dimensions": {},
        "page": 72,
        "rowKey": "revenue",
        "columnKey": "current_year",
    }


def test_matcher_policy_rejects_incomplete_signal_weight_mass() -> None:
    with pytest.raises(ValidationError, match=r"sum to 1\.0"):
        GeometryMatcherConfig(pdf_words_cells_weight=0.11)
