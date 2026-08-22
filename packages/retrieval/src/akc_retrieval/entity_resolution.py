"""Auditable Fellegi-Sunter entity linkage with authority conflict guards."""

from __future__ import annotations

import math
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(
        character
        for character in normalized
        if unicodedata.category(character)[0] in {"L", "N"}
    )


def _similarity(left: str | None, right: str | None) -> float:
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, _normalize(left), _normalize(right)).ratio()


@dataclass(frozen=True, slots=True)
class EntityRecord:
    entity_id: str
    name: str
    registration_id: str | None = None
    jurisdiction: str | None = None
    address: str | None = None
    authoritative: bool = False

    def __post_init__(self) -> None:
        if not self.entity_id or not self.name:
            raise ValueError("entity id and name are required")


@dataclass(frozen=True, slots=True)
class FieldWeight:
    field: str
    agreement_probability_match: float
    agreement_probability_nonmatch: float
    similarity_threshold: float

    def __post_init__(self) -> None:
        if not 0 < self.agreement_probability_nonmatch < 1:
            raise ValueError("nonmatch probability must be in (0, 1)")
        if not 0 < self.agreement_probability_match < 1:
            raise ValueError("match probability must be in (0, 1)")
        if self.agreement_probability_match <= self.agreement_probability_nonmatch:
            raise ValueError("match probability must exceed nonmatch probability")
        if not 0 <= self.similarity_threshold <= 1:
            raise ValueError("similarity threshold must be between zero and one")


DEFAULT_FIELD_WEIGHTS = (
    FieldWeight("name", 0.95, 0.08, 0.88),
    FieldWeight("registration_id", 0.995, 0.001, 1.0),
    FieldWeight("jurisdiction", 0.90, 0.20, 1.0),
    FieldWeight("address", 0.85, 0.15, 0.82),
)


@dataclass(frozen=True, slots=True)
class EntityResolutionDecision:
    disposition: str
    log_likelihood_ratio: float
    field_similarities: tuple[tuple[str, float], ...]
    reason_codes: tuple[str, ...]


def resolve_entities(
    left: EntityRecord,
    right: EntityRecord,
    *,
    field_weights: tuple[FieldWeight, ...] = DEFAULT_FIELD_WEIGHTS,
    merge_threshold: float = 4.0,
    possible_threshold: float = 0.0,
) -> EntityResolutionDecision:
    if merge_threshold <= possible_threshold:
        raise ValueError("merge threshold must exceed possible-match threshold")
    if (
        left.registration_id
        and right.registration_id
        and _normalize(left.registration_id) != _normalize(right.registration_id)
        and (left.authoritative or right.authoritative)
    ):
        return EntityResolutionDecision(
            disposition="reject",
            log_likelihood_ratio=float("-inf"),
            field_similarities=(("registration_id", 0.0),),
            reason_codes=("authoritative_registration_conflict",),
        )
    score = 0.0
    similarities: list[tuple[str, float]] = []
    observed_fields = 0
    for weight in field_weights:
        left_value = getattr(left, weight.field)
        right_value = getattr(right, weight.field)
        if not left_value or not right_value:
            continue
        observed_fields += 1
        similarity = _similarity(left_value, right_value)
        similarities.append((weight.field, similarity))
        agreement = similarity >= weight.similarity_threshold
        if agreement:
            score += math.log2(
                weight.agreement_probability_match
                / weight.agreement_probability_nonmatch
            )
        else:
            score += math.log2(
                (1 - weight.agreement_probability_match)
                / (1 - weight.agreement_probability_nonmatch)
            )
    if observed_fields == 0:
        return EntityResolutionDecision(
            disposition="review",
            log_likelihood_ratio=0.0,
            field_similarities=(),
            reason_codes=("no_comparable_fields",),
        )
    disposition = (
        "merge"
        if score >= merge_threshold
        else "review" if score >= possible_threshold else "reject"
    )
    return EntityResolutionDecision(
        disposition=disposition,
        log_likelihood_ratio=score,
        field_similarities=tuple(similarities),
        reason_codes=(f"fellegi_sunter_{disposition}",),
    )


__all__ = [
    "DEFAULT_FIELD_WEIGHTS",
    "EntityRecord",
    "EntityResolutionDecision",
    "FieldWeight",
    "resolve_entities",
]
