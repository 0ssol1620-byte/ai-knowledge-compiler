"""Properties of what product-core emits: no forced relation, no forced vertical."""

from __future__ import annotations

import pytest
from akc_domain_packs import ArchitectureProfile, plan_architecture
from akc_product_core.semantics import (
    _DOMAIN_KEYWORDS,
    SemanticSource,
    compile_semantics,
)


def _source(logical_id: str, text: str) -> SemanticSource:
    return SemanticSource(
        logical_id=logical_id,
        source_id=f"source-{logical_id}",
        source_version_id=f"version-{logical_id}",
        evidence_id=f"evidence-{logical_id}",
        text=text,
        authority="official",
    )


def test_every_relation_is_grounded_in_its_subject_claim() -> None:
    sources = (
        _source("a", "Alice Chen reviewed the Harbor Project plan. The plan was approved in 2025."),
        _source("b", "Bob Larsen and Carol Diaz visited Lake Station. NASA was not involved."),
        _source("c", "한국은행은 2026년 정책을 발표했다."),
    )
    result = compile_semantics(sources)
    claims = {claim.claim_id: claim for claim in result.claims}
    entities = {entity.entity_id: entity for entity in result.entities}
    input_evidence = {source.evidence_id for source in sources}

    assert result.relations
    for relation in result.relations:
        assert relation.predicate == "mentions"
        assert relation.subject_id in claims
        claim = claims[relation.subject_id]
        assert relation.object_id in entities
        assert claim.claim_id in entities[relation.object_id].claim_ids
        assert relation.evidence_id == claim.evidence_id
        assert relation.evidence_id in input_evidence


def test_sources_with_disjoint_mentions_are_not_linked() -> None:
    result = compile_semantics(
        (
            _source("left", "Alice Chen was reviewing the Harbor Project plan."),
            _source("right", "Bob Larsen was visiting Lake Station last week."),
        )
    )
    claims = {claim.claim_id: claim for claim in result.claims}
    entities = {entity.entity_id: entity for entity in result.entities}

    assert {claim.evidence_id for claim in result.claims} == {"evidence-left", "evidence-right"}
    assert result.relations
    for relation in result.relations:
        assert set(entities[relation.object_id].evidence_ids) == {
            claims[relation.subject_id].evidence_id
        }


def test_polarity_disagreement_is_a_contradiction_candidate_not_a_relation() -> None:
    # The topic key is the first 12 non-stopword tokens and no negation word is a stopword, so a
    # polarity pair only shares a topic when the negation falls past that prefix.
    prefix = (
        "The harbor queue is stable across every regional gateway during the nightly batch "
        "window under normal load"
    )
    result = compile_semantics(
        (_source("yes", f"{prefix} today."), _source("no", f"{prefix} but not tomorrow."))
    )

    assert [item.reason for item in result.contradictions] == ["polarity_disagreement"]
    assert result.contradictions[0].as_record()["adjudication"] == "human_review_required"
    assert {claim.polarity for claim in result.claims} == {"positive", "negative"}
    assert result.entities == ()
    assert result.relations == ()


_HORIZONTAL_CORPORA = {
    "personal-journal": "The morning was quiet and slow. The river was calm near the old bridge.",
    "study-notes": "Photosynthesis is how a leaf makes sugar. The chloroplast is the site.",
    "lab-notebook": "The sample was heated slowly. The colour was pale green afterwards.",
    "screenplay-draft": "The hall is empty tonight. The lights are flickering above the stage.",
    "team-meeting": "The group was pleased on Friday. The board will be updated tomorrow.",
}
_VERTICALS = ("finance", "legal", "technical")


@pytest.mark.parametrize("name", sorted(_HORIZONTAL_CORPORA))
def test_horizontal_corpora_are_not_forced_into_finance_legal_or_technical(name: str) -> None:
    text = _HORIZONTAL_CORPORA[name]
    lowered = text.casefold()
    # Precondition: a keyword-list change must fail loudly, not silently change what is tested.
    for vertical in _VERTICALS:
        assert not [k for k in _DOMAIN_KEYWORDS[vertical] if k.casefold() in lowered], (
            name,
            vertical,
        )
    result = compile_semantics((_source(name, text),))
    assert result.claims
    assert result.domain not in _VERTICALS


def test_corpus_without_domain_signal_is_mixed_not_a_vertical() -> None:
    result = compile_semantics(
        tuple(_source(name, text) for name, text in sorted(_HORIZONTAL_CORPORA.items()))
    )
    assert result.domain == "mixed"

    plan = plan_architecture(
        ArchitectureProfile(
            domain=result.domain,
            object_types=result.object_types,
            user_goal="compile",
            corpus_size=len(_HORIZONTAL_CORPORA),
            temporal_structure=result.temporal_structure,
        )
    )
    assert plan.blueprint == "generic-mixed-corpus"
