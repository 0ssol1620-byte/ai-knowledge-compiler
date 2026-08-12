"""Frozen page-family champion matrix with license and evidence gates."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ChampionCandidate:
    candidate_id: str
    page_family: str
    parser_recipe: str
    evidence_revision: str
    license_approved: bool
    promotion_approved: bool


class ChampionMatrix:
    def __init__(self, candidates: tuple[ChampionCandidate, ...]) -> None:
        matrix: dict[str, ChampionCandidate] = {}
        for candidate in candidates:
            if not candidate.license_approved or not candidate.promotion_approved:
                continue
            if candidate.page_family in matrix:
                raise ValueError("each page family must have exactly one promoted champion")
            matrix[candidate.page_family] = candidate
        self._matrix = matrix

    def select(self, page_family: str) -> ChampionCandidate | None:
        return self._matrix.get(page_family)


__all__ = ["ChampionCandidate", "ChampionMatrix"]
