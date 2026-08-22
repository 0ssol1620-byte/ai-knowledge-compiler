"""EXP-0103's fixture, and above all the unauthorized probe set.

Contract C makes the unauthorized candidate rate a hard gate at zero rather
than a statistic. A gate needs probes that could actually fire, so the tests
that matter here are the ones checking the probes are answerable somewhere and
that the answer is never in the asking tenant.
"""

from __future__ import annotations

from akc_absorption.retrieval_fixture import (
    PREFERRED_GRANULARITY,
    RetrievalIntent,
    StructuredFact,
    UnitGranularity,
    VersionState,
    build_retrieval_fixture,
    queries_from_structured_facts,
)


def test_the_fixture_is_deterministic() -> None:
    assert build_retrieval_fixture().manifest_sha256 == (
        build_retrieval_fixture().manifest_sha256
    )


def test_every_query_has_gold_evidence() -> None:
    """A query with no answer would sit in the recall denominator forever."""
    fixture = build_retrieval_fixture()
    assert fixture.queries
    known = {unit.unit_id for unit in fixture.units}
    for query in fixture.queries:
        assert query.gold_unit_ids, query.query_id
        assert set(query.gold_unit_ids) <= known


def test_gold_evidence_never_crosses_the_asking_tenant() -> None:
    fixture = build_retrieval_fixture()
    owner = {unit.unit_id: unit.tenant_id for unit in fixture.units}
    for query in fixture.queries:
        for unit_id in query.gold_unit_ids:
            assert owner[unit_id] == query.tenant_id, query.query_id


def test_each_fact_exists_at_more_than_one_granularity() -> None:
    """Otherwise granularity selection is unmeasurable: there is no alternative."""
    fixture = build_retrieval_fixture()
    by_key: dict[str, set[UnitGranularity]] = {}
    for unit in fixture.units:
        if unit.fact_key:
            by_key.setdefault(unit.fact_key, set()).add(unit.granularity)
    assert by_key
    for granularities in by_key.values():
        assert len(granularities) >= 3


def test_the_preferred_granularity_matches_the_intent_table() -> None:
    fixture = build_retrieval_fixture()
    for query in fixture.queries:
        assert query.preferred_granularity == PREFERRED_GRANULARITY[query.intent]


def test_a_version_fixture_exists_for_some_facts() -> None:
    fixture = build_retrieval_fixture()
    superseded = [
        unit for unit in fixture.units if unit.version_state is VersionState.SUPERSEDED
    ]
    assert superseded
    with_history = [
        query
        for query in fixture.queries
        if len(query.version_correct_unit_ids) < len(query.gold_unit_ids)
    ]
    assert with_history


def test_history_intents_are_only_asked_where_history_exists() -> None:
    fixture = build_retrieval_fixture()
    for query in fixture.queries:
        if query.intent in {RetrievalIntent.HISTORICAL, RetrievalIntent.CHANGE}:
            assert len(query.version_correct_unit_ids) < len(query.gold_unit_ids), (
                query.query_id
            )


def test_probes_are_answerable_and_the_answer_is_forbidden() -> None:
    fixture = build_retrieval_fixture()
    assert fixture.probes
    owner = {unit.unit_id: unit.tenant_id for unit in fixture.units}
    for probe in fixture.probes:
        assert probe.forbidden_unit_ids, probe.probe_id
        for unit_id in probe.forbidden_unit_ids:
            assert owner[unit_id] != probe.asking_tenant_id, probe.probe_id
        for unit_id in probe.permitted_unit_ids:
            assert owner[unit_id] == probe.asking_tenant_id, probe.probe_id


def test_probes_cross_every_ordered_tenant_pair() -> None:
    fixture = build_retrieval_fixture()
    tenants = sorted({unit.tenant_id for unit in fixture.units})
    seen = {(probe.asking_tenant_id, probe.probe_id.split(":")[2]) for probe in fixture.probes}
    for asking in tenants:
        for owning in tenants:
            if asking == owning:
                continue
            assert any(pair[0] == asking and pair[1] == owning for pair in seen)


def test_the_structured_fact_arm_is_wired_but_unpopulated() -> None:
    """Contract C's XBRL/DART arm. It works; nothing has been run through it."""
    fixture = build_retrieval_fixture()
    assert queries_from_structured_facts([], list(fixture.units)) == []

    sample = next(unit for unit in fixture.units if unit.fact_key)
    fact = StructuredFact(
        fact_key=sample.fact_key,
        value="42",
        period="FY2026",
        tenant_id=sample.tenant_id,
        project_id=sample.project_id,
        document_id=sample.document_id,
        section=sample.section,
    )
    produced = queries_from_structured_facts([fact], list(fixture.units))
    assert len(produced) == 1
    assert produced[0].truth_source == "structured_fact"
    assert produced[0].gold_unit_ids


def test_a_fact_no_unit_states_produces_no_query() -> None:
    fixture = build_retrieval_fixture()
    orphan = StructuredFact(
        fact_key="tenant-zulu/proj-none/unknown_metric/FY2099",
        value="1",
        period="FY2099",
        tenant_id="tenant-zulu",
        project_id="proj-none",
        document_id="doc-none",
        section="none",
    )
    assert queries_from_structured_facts([orphan], list(fixture.units)) == []
