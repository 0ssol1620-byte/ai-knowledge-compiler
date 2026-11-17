"""WO-D17-2: linear BM25 is bit-identical to the old quadratic function."""

from __future__ import annotations

import math
import random
from collections import Counter
from collections.abc import Callable

import pytest
from akc_product_core import retrieval
from akc_product_core.retrieval import SemanticRetrievalCandidate, rank_semantic_candidates


# verbatim copy of the pre-WO-D17-2 function (560f243)
def _old_bm25_scores(
    query_terms: frozenset[str], candidates: tuple[SemanticRetrievalCandidate, ...]
) -> dict[str, float]:
    if not query_terms or not candidates:
        return {candidate.logical_id: 0.0 for candidate in candidates}
    document_terms = {candidate.logical_id: tuple(candidate.terms) for candidate in candidates}
    frequencies = {key: Counter(terms) for key, terms in document_terms.items()}
    average_length = sum(len(terms) for terms in document_terms.values()) / len(candidates)
    scores: dict[str, float] = {}
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


def _candidate(
    logical_id: str, terms: tuple[str, ...], rng: random.Random
) -> SemanticRetrievalCandidate:
    return SemanticRetrievalCandidate(
        logical_id=logical_id,
        text=" ".join(terms),
        terms=terms,
        entity_names=(),
        temporal_refs=("2025",) if rng.random() < 0.2 else (),
        authority_score=rng.choice((0.0, 0.5, 1.0)),
        claim_ids=(logical_id[::-1],),
    )


def _case(seed: int) -> tuple[str, tuple[SemanticRetrievalCandidate, ...]]:
    rng = random.Random(seed)
    size = (0, 1, 2, 1500)[seed] if seed < 4 else rng.randint(3, 60)
    candidates: list[SemanticRetrievalCandidate] = []
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
def test_scores_and_ranking_bit_identical_to_old_function(
    seed: int, monkeypatch: pytest.MonkeyPatch
) -> None:
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


def test_document_frequency_is_counted_once_per_call(monkeypatch: pytest.MonkeyPatch) -> None:
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
    # one idf per query term that occurs anywhere; the old code did one per (document, term).
    # Kept beside the scaling guard below: an idf recomputed per (document, term) from a
    # once-counted df is linear, so only this count sees it.
    assert _CountingMath.log_calls == len(present)


class _CountedTerm(str):
    """A term that counts every equality test and hash taken on it, in whatever container."""

    calls = 0

    def __eq__(self, other: object) -> bool:
        _CountedTerm.calls += 1
        return str.__eq__(self, other)

    def __hash__(self) -> int:
        _CountedTerm.calls += 1
        return str.__hash__(self)


_Scorer = Callable[[frozenset[str], tuple[SemanticRetrievalCandidate, ...]], dict[str, float]]


def _term_work(score: _Scorer, size: int) -> int:
    """Equality tests and hashes taken on the terms while scoring `size` candidates."""
    rng = random.Random(2026)
    candidates = tuple(
        SemanticRetrievalCandidate(
            logical_id=f"d{i}",
            text="",
            terms=tuple(
                _CountedTerm(rng.choice(_VOCAB[:30])) for _ in range(rng.choice((1, 3, 8, 20)))
            ),
            entity_names=(),
            temporal_refs=(),
            authority_score=0.0,
            claim_ids=(),
        )
        for i in range(size)
    )
    # present terms and one absent term: an early-exit `any(...)` rescan still walks every
    # document for the absent one
    query_terms = frozenset(_CountedTerm(term) for term in ("t1", "t2", "t3", "absent"))
    _CountedTerm.calls = 0
    score(query_terms, candidates)
    return _CountedTerm.calls


# The guard watches the terms, not the container they are copied into: a rescan of a plain
# tuple/list/set copy still compares and hashes the same term objects. Measured on the shipped
# function: 7,774 -> 15,496 (ratio 1.99) at 200 -> 400 and 29,839 -> 61,732 (ratio 2.07) at
# 800 -> 1,600; the verbatim old function: 1,134,789 -> 4,447,220 (ratio 3.92) at 200 -> 400.
_LINEAR_RATIO_BOUND = 2.5


@pytest.mark.parametrize("size", (200, 800))
def test_term_work_is_linear_in_the_number_of_candidates(size: int) -> None:
    small = _term_work(retrieval._bm25_scores, size)
    large = _term_work(retrieval._bm25_scores, 2 * size)
    assert small > 0
    assert large <= _LINEAR_RATIO_BOUND * small, (small, large)


def test_linearity_guard_sees_the_old_quadratic_function() -> None:
    small = _term_work(_old_bm25_scores, 200)
    large = _term_work(_old_bm25_scores, 400)
    assert large > _LINEAR_RATIO_BOUND * small, (small, large)


def test_1500_candidates_with_present_query_terms_bit_identical(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rng = random.Random(1500)
    candidates = tuple(
        _candidate(
            f"d{i}", tuple(rng.choice(_VOCAB[:30]) for _ in range(rng.choice((1, 3, 8, 20)))), rng
        )
        for i in range(1500)
    )
    query = "t1 t2 t3 zzzabsent"
    query_terms = retrieval._expanded_terms(query)
    new = retrieval._bm25_scores(query_terms, candidates)
    old = _old_bm25_scores(query_terms, candidates)
    assert [(key, value.hex()) for key, value in new.items()] == [
        (key, value.hex()) for key, value in old.items()
    ]
    # a real scoring path: most candidates hold a query term and score above zero
    assert sum(1 for value in new.values() if value > 0) > 500
    new_hits = rank_semantic_candidates(query, candidates, top_k=100)
    monkeypatch.setattr(retrieval, "_bm25_scores", _old_bm25_scores)
    assert new_hits == rank_semantic_candidates(query, candidates, top_k=100)
