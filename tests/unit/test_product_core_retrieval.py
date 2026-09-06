"""Adaptive multilingual retrieval qualification over semantic candidates."""

from __future__ import annotations

from akc_product_core.retrieval import (
    rank_exact_token_baseline,
    rank_semantic_candidates,
    retrieval_candidates,
)
from akc_product_core.semantics import SemanticSource, compile_semantics


def _corpus():
    texts = {
        "a-distractor": "Unrelated operational memo for archive retention.",
        "b-informal": "Security policy requires a quarterly access review.",
        "v-entity": "TAVONEL Research Institute published an audit.",
        "w-research": "이 연구는 공개 데이터셋을 사용해 모델을 평가했다.",
        "x-security": "Security policy requires a quarterly access review.",
        "y-legal": "The Agreement termination period is 30 days.",
        "z-finance": "Revenue increased during the 2025 fiscal quarter.",
    }
    semantics = compile_semantics(
        tuple(
            SemanticSource(
                logical_id=logical_id,
                source_id=f"source-{logical_id}",
                source_version_id=f"version-{logical_id}",
                evidence_id=f"evidence-{logical_id}",
                text=text,
                authority="informal" if logical_id == "b-informal" else "official",
            )
            for logical_id, text in texts.items()
        )
    )
    return retrieval_candidates(semantics)


def test_cross_lingual_query_expansion_improves_fixed_mixed_corpus_precision() -> None:
    candidates = _corpus()
    cases = (
        ("2025 매출 증가", "z-finance"),
        ("계약 해지 기간", "y-legal"),
        ("research dataset", "w-research"),
        ("security policy", "x-security"),
    )

    baseline_hits = 0
    semantic_hits = 0
    for query, expected in cases:
        baseline_hits += rank_exact_token_baseline(query, candidates, top_k=1)[0] == expected
        semantic = rank_semantic_candidates(query, candidates, top_k=1)
        semantic_hits += semantic[0].logical_id == expected
        assert semantic[0].claim_ids
        assert 0.0 <= semantic[0].score <= 1.0

    assert baseline_hits == 1
    assert semantic_hits == 4


def test_ranking_is_deterministic_bounded_and_exposes_score_breakdown() -> None:
    candidates = _corpus()

    first = rank_semantic_candidates("계약 해지 기간", candidates, top_k=3)
    second = rank_semantic_candidates("계약 해지 기간", candidates, top_k=3)

    assert first == second
    assert len(first) == 3
    assert first[0].logical_id == "y-legal"
    assert first[0].lexical_score > 0
    assert first[0].as_record()["authorityScore"] == 1.0
    temporal_hit = rank_semantic_candidates("2025 매출 증가", candidates, top_k=1)[0]
    assert temporal_hit.logical_id == "z-finance"
    assert temporal_hit.temporal_score == 1.0
    authority_hit = rank_semantic_candidates("security policy access review", candidates, top_k=1)[
        0
    ]
    assert authority_hit.logical_id == "x-security"
    assert authority_hit.authority_score == 1.0
    entity_hit = rank_semantic_candidates("TAVONEL", candidates, top_k=1)[0]
    assert entity_hit.logical_id == "v-entity"
    assert entity_hit.graph_score > 0
