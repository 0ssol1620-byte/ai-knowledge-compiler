"""Provider-free adaptive retrieval over Product-Core semantic candidates."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass

from .semantics import SemanticClaim, SemanticCompilation, semantic_tokens

_SYNONYM_GROUPS = (
    frozenset({"revenue", "sales", "매출", "수익", "売上", "收入"}),
    frozenset({"increase", "increased", "growth", "증가", "상승", "増加", "增长"}),
    frozenset({"contract", "agreement", "계약", "契約", "合同"}),
    frozenset({"termination", "terminate", "cancel", "해지", "종료", "解除", "终止"}),
    frozenset({"period", "term", "days", "기간", "일", "期間", "天"}),
    frozenset({"research", "study", "연구", "研究"}),
    frozenset({"dataset", "data", "데이터셋", "데이터", "データ", "数据"}),
    frozenset({"policy", "rule", "정책", "규정", "方針", "政策"}),
    frozenset({"risk", "위험", "리스크", "リスク", "风险"}),
)
_SYNONYMS = {token: group for group in _SYNONYM_GROUPS for token in group}


def _expanded_terms(value: str) -> frozenset[str]:
    expanded: set[str] = set()
    for token in semantic_tokens(value):
        expanded.update(_SYNONYMS.get(token, (token,)))
    return frozenset(expanded)


@dataclass(frozen=True, slots=True)
class SemanticRetrievalCandidate:
    logical_id: str
    text: str
    terms: tuple[str, ...]
    entity_names: tuple[str, ...]
    temporal_refs: tuple[str, ...]
    authority_score: float
    claim_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SemanticRetrievalHit:
    logical_id: str
    score: float
    lexical_score: float
    graph_score: float
    temporal_score: float
    authority_score: float
    claim_ids: tuple[str, ...]

    def as_record(self) -> dict[str, object]:
        return {
            "logicalId": self.logical_id,
            "score": self.score,
            "lexicalScore": self.lexical_score,
            "graphScore": self.graph_score,
            "temporalScore": self.temporal_score,
            "authorityScore": self.authority_score,
            "claimIds": list(self.claim_ids),
        }


def retrieval_candidates(semantics: SemanticCompilation) -> tuple[SemanticRetrievalCandidate, ...]:
    entities = {entity.entity_id: entity.canonical_name for entity in semantics.entities}
    claims_by_logical: defaultdict[str, list[SemanticClaim]] = defaultdict(list)
    for claim in semantics.claims:
        claims_by_logical[claim.logical_id].append(claim)
    return tuple(
        SemanticRetrievalCandidate(
            logical_id=logical_id,
            text=" ".join(claim.text for claim in claims),
            terms=tuple(dict.fromkeys(term for claim in claims for term in claim.retrieval_terms)),
            entity_names=tuple(
                dict.fromkeys(
                    entities[entity_id] for claim in claims for entity_id in claim.entity_ids
                )
            ),
            temporal_refs=tuple(
                dict.fromkeys(
                    temporal_ref for claim in claims for temporal_ref in claim.temporal_refs
                )
            ),
            authority_score=max(claim.authority_score for claim in claims),
            claim_ids=tuple(claim.claim_id for claim in claims),
        )
        for logical_id, claims in sorted(claims_by_logical.items())
    )


def _bm25_scores(
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


def rank_semantic_candidates(
    query: str,
    candidates: tuple[SemanticRetrievalCandidate, ...],
    *,
    top_k: int = 8,
) -> tuple[SemanticRetrievalHit, ...]:
    if not 1 <= top_k <= 100:
        raise ValueError("top_k must be between 1 and 100")
    query_terms = _expanded_terms(query)
    query_raw_terms = frozenset(semantic_tokens(query))
    lexical_scores = _bm25_scores(query_terms, candidates)
    query_years = {term for term in query_terms if len(term) == 4 and term.isdigit()}
    rows: list[SemanticRetrievalHit] = []
    for candidate in candidates:
        entity_terms = frozenset(
            term for name in candidate.entity_names for term in semantic_tokens(name)
        )
        graph_score = len(query_raw_terms & entity_terms) / max(1, len(query_raw_terms))
        temporal_score = 1.0 if query_years.intersection(candidate.temporal_refs) else 0.0
        lexical_score = lexical_scores[candidate.logical_id]
        score = (
            lexical_score * 0.70
            + graph_score * 0.10
            + temporal_score * 0.10
            + candidate.authority_score * 0.10
        )
        rows.append(
            SemanticRetrievalHit(
                logical_id=candidate.logical_id,
                score=round(score, 12),
                lexical_score=round(lexical_score, 12),
                graph_score=round(graph_score, 12),
                temporal_score=temporal_score,
                authority_score=candidate.authority_score,
                claim_ids=candidate.claim_ids,
            )
        )
    return tuple(sorted(rows, key=lambda item: (-item.score, item.logical_id))[:top_k])


def rank_exact_token_baseline(
    query: str,
    candidates: tuple[SemanticRetrievalCandidate, ...],
    *,
    top_k: int = 8,
) -> tuple[str, ...]:
    query_terms = frozenset(semantic_tokens(query))
    rows = (
        (
            len(query_terms.intersection(semantic_tokens(candidate.text)))
            / max(1, len(query_terms)),
            candidate.logical_id,
        )
        for candidate in candidates
    )
    return tuple(
        logical_id for _, logical_id in sorted(rows, key=lambda item: (-item[0], item[1]))[:top_k]
    )


__all__ = [
    "SemanticRetrievalCandidate",
    "SemanticRetrievalHit",
    "rank_exact_token_baseline",
    "rank_semantic_candidates",
    "retrieval_candidates",
]
