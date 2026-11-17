"""WO-D17-2: linear BM25 is bit-identical to the old quadratic function."""

from __future__ import annotations

import math
import random
from collections import Counter

import pytest
from akc_product_core import retrieval
from akc_product_core.retrieval import SemanticRetrievalCandidate, rank_semantic_candidates


def _old_bm25_scores(query_terms, candidates):  # verbatim copy of the pre-WO-D17-2 function
    if not query_terms or not candidates:
        return {candidate.logical_id: 0.0 for candidate in candidates}
    document_terms = {candidate.logical_id: tuple(candidate.terms) for candidate in candidates}
    frequencies = {key: Counter(terms) for key, terms in document_terms.items()}
    average_length = sum(len(terms) for terms in document_terms.values()) / len(candidates)
    scores = {}
    for candidate in candidates:
        frequency = frequencies[candidate.logical_id]
        length = len(document_terms[candidate.logical_id])
        score = 0.0
        for term in query_terms:
            document_frequency = sum(1 for terms in document_terms.values() if term in terms)
            if document_frequency == 0:
                continue
            inverse_frequency = math.log(
                1 + (len(candidates) - document_frequency + 0.5) / (document_frequency + 0.5)
            )
            count = frequency[term]
            denominator = count + 1.2 * (1 - 0.75 + 0.75 * length / max(1.0, average_length))
            score += inverse_frequency * (count * 2.2) / denominator
        scores[candidate.logical_id] = score
    maximum = max(scores.values(), default=0.0)
    return {
        logical_id: (score / maximum if maximum > 0 else 0.0)
        for logical_id, score in scores.items()
    }


_VOCAB = (*(f"t{i}" for i in range(40)), "revenue", "sales", "계약", "2025")


def _candidate(logical_id, terms, rng):
    return SemanticRetrievalCandidate(
        logical_id=logical_id,
        text=" ".join(terms),
        terms=terms,
        entity_names=(),
        temporal_refs=("2025",) if rng.random() < 0.2 else (),
        authority_score=rng.choice((0.0, 0.5, 1.0)),
        claim_ids=(logical_id[::-1],),
    )


def _case(seed):
    rng = random.Random(seed)
    size = (0, 1, 2, 1500)[seed] if seed < 4 else rng.randint(3, 60)
    candidates = []
    for i in range(size):
        # duplicate logical ids on some seeds (the keyed dicts collapse them)
        key = f"d{rng.randint(0, size // 2)}" if seed % 7 == 0 else f"d{i}"
        n = rng.choice((0, 1, 3, 8, 20))
        terms = tuple(rng.choice(_VOCAB[:30]) for _ in range(n))  # repeats inside a document
        candidates.append(_candidate(key, terms, rng))
    query = rng.choice(
        ("", "t1 t2 t3", "revenue growth 2025", "zzzabsent qqqabsent", "t1 zzzabsent", "계약 sales")
    )
    return query, tuple(candidates)


@pytest.mark.parametrize("seed", range(200))
def test_scores_and_ranking_bit_identical_to_old_function(seed, monkeypatch):
    query, candidates = _case(seed)
    query_terms = retrieval._expanded_terms(query)
    assert retrieval._bm25_scores(query_terms, candidates) == _old_bm25_scores(
        query_terms, candidates
    )
    new_hits = rank_semantic_candidates(query, candidates, top_k=100)
    monkeypatch.setattr(retrieval, "_bm25_scores", _old_bm25_scores)
    assert new_hits == rank_semantic_candidates(query, candidates, top_k=100)
    # tie-break pinned independently of the module under test: score desc, then logical id
    assert [h.logical_id for h in new_hits] == [
        h.logical_id for h in sorted(new_hits, key=lambda h: (-h.score, h.logical_id))
    ]


class _CountingMath:
    log_calls = 0

    @staticmethod
    def log(value: float) -> float:
        _CountingMath.log_calls += 1
        return math.log(value)


def test_document_frequency_is_counted_once_per_call(monkeypatch) -> None:
    rng = random.Random(7)
    candidates = tuple(
        _candidate(f"d{i}", tuple(rng.choice(_VOCAB[:30]) for _ in range(10)), rng)
        for i in range(50)
    )
    query_terms = frozenset({"t1", "t2", "t3", "t4", "t5", "absent"})
    present = {term for candidate in candidates for term in candidate.terms} & query_terms
    assert 0 < len(present) < len(query_terms)
    monkeypatch.setattr(retrieval, "math", _CountingMath)
    retrieval._bm25_scores(query_terms, candidates)
    # one idf per query term that occurs anywhere; the old code did one per (document, term)
    assert _CountingMath.log_calls == len(present)
