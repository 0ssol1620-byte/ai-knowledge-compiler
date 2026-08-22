"""Page and region coverage invariants."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PageCoverage:
    expected_pages: int
    observed_pages: tuple[int, ...]
    missing_pages: tuple[int, ...]
    duplicate_pages: tuple[int, ...]
    coverage: float
    passed: bool


def validate_page_coverage(expected_pages: int, observed_pages: tuple[int, ...]) -> PageCoverage:
    if expected_pages < 1:
        raise ValueError("expected_pages must be positive")
    if any(page < 1 or page > expected_pages for page in observed_pages):
        raise ValueError("observed page is outside the source range")
    observed = set(observed_pages)
    missing = tuple(sorted(set(range(1, expected_pages + 1)) - observed))
    duplicates = tuple(sorted(page for page in observed if observed_pages.count(page) > 1))
    return PageCoverage(
        expected_pages=expected_pages,
        observed_pages=tuple(sorted(observed)),
        missing_pages=missing,
        duplicate_pages=duplicates,
        coverage=len(observed) / expected_pages,
        passed=not missing and not duplicates,
    )


__all__ = ["PageCoverage", "validate_page_coverage"]
