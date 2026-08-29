"""Evidence-bound multilingual semantics for the Product-Core candidate."""

from __future__ import annotations

from akc_product_core.semantics import SemanticSource, compile_semantics, detect_language


def _source(logical_id: str, text: str, *, authority: str = "regulatory_filing") -> SemanticSource:
    return SemanticSource(
        logical_id=logical_id,
        source_id=f"source-{logical_id}",
        source_version_id=f"version-{logical_id}",
        evidence_id=f"evidence-{logical_id}",
        text=text,
        authority=authority,
    )


def test_detects_supported_scripts_without_translating_source_text() -> None:
    assert detect_language("Revenue increased in the quarter.") == "en"
    assert detect_language("분기 매출이 증가했습니다.") == "ko"
    assert detect_language("これはテストです。") in {"ja", "mixed"}
    assert detect_language("收入同比增长。") == "zh"
    assert detect_language("Revenue와 매출을 함께 검토합니다.") == "mixed"


def test_compiles_claims_entities_relations_authority_and_temporal_evidence() -> None:
    result = compile_semantics(
        (
            _source(
                "filing-a",
                "2025 revenue was 100 million won. TAVONEL Research Institute reported the result.",
            ),
            _source("filing-b", "2025 revenue was 120 million won."),
            _source("policy-ko", "한국은행은 2026년 정책을 발표했다.", authority="official"),
        )
    )

    assert result.domain in {"finance", "mixed"}
    assert len(result.claims) == 4
    assert {claim.language for claim in result.claims} == {"en", "ko"}
    assert all(claim.evidence_id and claim.source_version_id for claim in result.claims)
    assert all(claim.authority_tier == "official" for claim in result.claims)
    assert any(entity.canonical_name == "TAVONEL Research Institute" for entity in result.entities)
    assert any(entity.canonical_name == "한국은행" for entity in result.entities)
    assert result.relations
    assert {relation.predicate for relation in result.relations} == {"mentions"}
    assert any(claim.temporal_refs for claim in result.claims)
    assert result.temporal_structure == "explicit"


def test_numeric_disagreement_is_review_candidate_not_asserted_relation() -> None:
    result = compile_semantics(
        (
            _source("v1", "2025 revenue was 100 million won."),
            _source("v2", "2025 revenue was 120 million won."),
        )
    )

    assert len(result.contradictions) == 1
    contradiction = result.contradictions[0]
    assert contradiction.reason == "numeric_disagreement"
    assert contradiction.as_record()["adjudication"] == "human_review_required"
    assert set(contradiction.claim_ids) <= {claim.claim_id for claim in result.claims}


def test_adaptive_retrieval_profile_is_deterministic_and_honest_about_embeddings() -> None:
    sources = (
        _source("en", "TAVONEL Research Institute published the dataset."),
        _source("ko", "한국은행은 연구 결과를 발표했다."),
    )

    first = compile_semantics(sources)
    second = compile_semantics(sources)

    assert first == second
    weights = first.retrieval_profile["weights"]
    assert isinstance(weights, dict)
    assert sum(float(value) for value in weights.values()) == 1.0
    assert first.retrieval_profile["vectorMaterialization"] == (
        "external_embedding_provider_required"
    )
    assert "multilingual_lexical" in first.retrieval_profile["materializedSignals"]
