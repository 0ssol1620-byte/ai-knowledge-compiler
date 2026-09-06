"""Locally-owned ``sample_id`` / ``case_key`` derivation.

``ARENA_CONTRACT.md`` section 2 defines both identifiers. ``arena/core/ids.py``
(lane A1) is the eventual canonical home for this rule; until it lands, this
module is the *single* indirection point other ``arena.manifest`` code goes
through, so swapping the implementation later is a one-line import change
here and nowhere else.
"""

from __future__ import annotations

from posixpath import splitext


def compute_sample_id(
    *, benchmark: str, source_relative_path: str, media_type: str, page_index: int
) -> str:
    """``ARENA_CONTRACT.md`` section 2: ``sample_id``.

    ``<benchmark>:<official-id>`` where ``official-id`` is the staged
    manifest's ``source_relative_path`` with its extension removed, plus
    ``#p<page_index>`` when ``media_type == "pdf"``.

    Examples (verbatim from the contract)::

        omnidoc:images/PPT_1001115_eng_page_003
        parsebench:docs/chart/(Web_version)_E-Government_Survey_2024_1392024_p101#p0
        olmocr:bench_data/pdfs/arxiv_math/2502.15977_pg21#p0
    """
    if not benchmark:
        raise ValueError("benchmark is required to compute a sample_id")
    if not source_relative_path:
        raise ValueError("source_relative_path is required to compute a sample_id")
    stem, _ext = splitext(source_relative_path)
    if media_type == "pdf":
        if page_index < 0:
            raise ValueError(f"invalid page_index for pdf sample: {page_index}")
        return f"{benchmark}:{stem}#p{page_index}"
    if media_type != "image":
        raise ValueError(f"unsupported media_type for sample_id: {media_type}")
    return f"{benchmark}:{stem}"


def compute_case_key(staged_case_id: str) -> str:
    """``ARENA_CONTRACT.md`` section 2: ``case_key`` is the staged ``case_id`` verbatim."""
    if not staged_case_id:
        raise ValueError("staged case_id is required to compute a case_key")
    return staged_case_id


__all__ = ["compute_case_key", "compute_sample_id"]
