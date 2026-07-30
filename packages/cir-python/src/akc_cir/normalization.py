"""Deterministic, provenance-preserving document normalization rules.

The rules in this module deliberately avoid statistical language or layout
claims.  They only make bounded, explainable transformations and retain the
exact input text alongside every normalized value.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal

NORMALIZATION_VERSION = "akc-normalization-1.1.0"

_PROTECTED_BLOCK_TYPES = frozenset({"code", "formula", "table", "table_cell"})
_ENGLISH_LINE_HYPHEN = re.compile(
    r"(?P<left>\b[A-Za-z]{2,})-[ \t]*\n[ \t]*(?P<right>[a-z]{2,})(?![A-Za-z-])"
)
_PRESERVE_HYPHEN_PREFIXES = frozenset(
    {
        "cross",
        "e",
        "high",
        "long",
        "low",
        "multi",
        "non",
        "post",
        "pre",
        "real",
        "self",
        "short",
        "state",
        "well",
    }
)
_HANGUL = re.compile(r"[\uac00-\ud7a3]")
_KOREAN_PARTICLE_ENDINGS = (
    "으로",
    "에서",
    "에게",
    "한테",
    "부터",
    "까지",
    "처럼",
    "보다",
    "은",
    "는",
    "이",
    "가",
    "을",
    "를",
    "에",
    "로",
    "와",
    "과",
    "도",
    "만",
    "의",
)
_TERMINAL_PUNCTUATION = frozenset(".!?\u3002\uff01\uff1f\u2026")
_LEGAL_NOTICE = re.compile(
    r"\b(?:all rights reserved|copyright|confidential|legal notice)\b|"
    r"(?:저작권|법적\s*고지|무단\s*(?:복제|전재)|기밀)",
    re.IGNORECASE,
)
_WHITESPACE = re.compile(r"\s+")
_DIGITS = re.compile(r"\d+")


@dataclass(frozen=True, slots=True)
class TextNormalizationResult:
    """Exact source text plus its deterministic, auditable normalization."""

    raw_text: str
    normalized_text: str
    operations: tuple[str, ...]
    quality_flags: tuple[str, ...]

    def payload(self) -> dict[str, object]:
        return {
            "version": NORMALIZATION_VERSION,
            "rawTextPreserved": True,
            "operations": list(self.operations),
            "qualityFlags": list(self.quality_flags),
        }


@dataclass(frozen=True, slots=True)
class NormalizationBlock:
    """Small provider-neutral block view used by document-level rules."""

    block_id: str
    page_number: int
    order: int
    block_type: str
    raw_text: str
    normalized_text: str
    bbox1000: tuple[int, int, int, int] | None
    source_ref_ids: tuple[str, ...]
    provider_order: int | None = None
    provider_label: str | None = None
    font_size_pt: float | None = None
    font_weight: int | None = None
    whitespace_before: float | None = None
    whitespace_after: float | None = None
    explicit_heading_level: int | None = None
    is_toc_entry: bool = False
    toc_level: int | None = None
    markdown: str | None = None


@dataclass(frozen=True, slots=True)
class RepeatedMarginalAnnotation:
    """A repeated marginal block that remains present in the CIR."""

    block_id: str
    classified_type: Literal["header", "footer"]
    group_id: str
    matched_pages: tuple[int, ...]
    confidence: float
    excluded_from_body: bool
    preservation_reason: str

    def payload(self) -> dict[str, object]:
        return {
            "schemaVersion": "akc-repeated-marginal-1.0.0",
            "classifiedType": self.classified_type,
            "groupId": self.group_id,
            "matchedPages": list(self.matched_pages),
            "confidence": self.confidence,
            "excludedFromBody": self.excluded_from_body,
            "preservedInCir": True,
            "preservationReason": self.preservation_reason,
        }


CrossPageKind = Literal[
    "paragraph_continuation",
    "split_table_header",
    "figure_caption_continuation",
    "footnote_continuation",
    "heading_body_continuation",
]


@dataclass(frozen=True, slots=True)
class CrossPageRestoration:
    """A conservative cross-page relationship with multi-source provenance."""

    kind: CrossPageKind
    block_ids: tuple[str, str]
    source_ref_ids: tuple[str, ...]
    from_page: int
    to_page: int
    reconstructed_text: str | None
    uncertain: bool
    quality_flags: tuple[str, ...]

    def payload(self) -> dict[str, object]:
        return {
            "schemaVersion": "akc-cross-page-restoration-1.0.0",
            "kind": self.kind,
            "sourceBlockIds": list(self.block_ids),
            "sourceRefIds": list(self.source_ref_ids),
            "fromPage": self.from_page,
            "toPage": self.to_page,
            "reconstructedText": self.reconstructed_text,
            "uncertain": self.uncertain,
            "qualityFlags": list(self.quality_flags),
        }


def _normalization_line_ending(value: str) -> tuple[str, bool]:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    return normalized, normalized != value


def _merge_english_line_hyphens(value: str) -> tuple[str, bool, bool]:
    joined = False
    preserved = False

    def replace(match: re.Match[str]) -> str:
        nonlocal joined, preserved
        left = match.group("left")
        if left.casefold() in _PRESERVE_HYPHEN_PREFIXES:
            preserved = True
            return left + "-" + match.group("right")
        joined = True
        return left + match.group("right")

    return _ENGLISH_LINE_HYPHEN.sub(replace, value), joined, preserved


def _line_boundary_replacement(
    before: str,
    after: str,
) -> tuple[str, str, bool]:
    left = before.rstrip()
    right = after.lstrip()
    if not left or not right:
        return "", "empty_line_boundary_removed", False
    previous = left[-1]
    following = right[0]
    if previous in _TERMINAL_PUNCTUATION:
        return " ", "sentence_boundary_spaced", False
    if _HANGUL.fullmatch(previous) and _HANGUL.fullmatch(following):
        if any(left.endswith(ending) for ending in _KOREAN_PARTICLE_ENDINGS):
            return " ", "korean_particle_boundary_spaced", False
        return " ", "korean_line_boundary_spaced", True
    return " ", "prose_line_boundary_spaced", False


def _merge_prose_line_breaks(value: str) -> tuple[str, tuple[str, ...], bool]:
    parts = re.split(r"(\n{2,})", value)
    operations: set[str] = set()
    uncertain = False
    output: list[str] = []
    for part in parts:
        if not part:
            continue
        if part.startswith("\n\n"):
            output.append("\n\n")
            continue
        lines = part.split("\n")
        if len(lines) == 1:
            output.append(part)
            continue
        current = lines[0].rstrip()
        for following in lines[1:]:
            replacement, operation, boundary_uncertain = _line_boundary_replacement(
                current,
                following,
            )
            operations.add(operation)
            uncertain = uncertain or boundary_uncertain
            current = current + replacement + following.lstrip()
        output.append(current)
    return "".join(output), tuple(sorted(operations)), uncertain


def normalize_block_text(
    raw_text: str,
    *,
    block_type: str,
) -> TextNormalizationResult:
    """Normalize one block without ever replacing or discarding its raw text."""

    operations: list[str] = []
    quality_flags: list[str] = []
    value, line_endings_changed = _normalization_line_ending(raw_text)
    if line_endings_changed:
        operations.append("line_endings_lf")
    nfc_value = unicodedata.normalize("NFC", value)
    if nfc_value != value:
        operations.append("unicode_nfc")
    value = nfc_value
    if block_type.casefold() in _PROTECTED_BLOCK_TYPES:
        operations.append("line_merge_skipped_protected_content")
        return TextNormalizationResult(
            raw_text=raw_text,
            normalized_text=value,
            operations=tuple(operations),
            quality_flags=(),
        )

    value, hyphen_joined, hyphen_preserved = _merge_english_line_hyphens(value)
    if hyphen_joined:
        operations.append("english_line_end_hyphen_joined")
    if hyphen_preserved:
        operations.append("english_hyphenated_word_line_joined")
    value, line_operations, uncertain = _merge_prose_line_breaks(value)
    operations.extend(line_operations)
    if uncertain:
        quality_flags.append("korean_line_spacing_uncertain")
    return TextNormalizationResult(
        raw_text=raw_text,
        normalized_text=value,
        operations=tuple(dict.fromkeys(operations)),
        quality_flags=tuple(quality_flags),
    )


def _fingerprint(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = _DIGITS.sub("<n>", normalized)
    return _WHITESPACE.sub(" ", normalized).strip()


def _margin_region(block: NormalizationBlock) -> Literal["header", "footer"] | None:
    if block.block_type in {"table", "caption", "formula", "code", "figure", "footnote"}:
        return None
    if block.block_type == "heading":
        return None
    if block.block_type == "header":
        return "header"
    if block.block_type in {"footer", "page_number"}:
        return "footer"
    if block.bbox1000 is None:
        return None
    _x1, y1, _x2, y2 = block.bbox1000
    if y2 <= 150:
        return "header"
    if y1 >= 850:
        return "footer"
    return None


def detect_repeated_marginal_blocks(
    blocks: Sequence[NormalizationBlock],
    *,
    total_pages: int | None = None,
    similarity_threshold: float = 0.88,
) -> tuple[RepeatedMarginalAnnotation, ...]:
    """Classify repeated top/bottom blocks while preserving every source block."""

    if not 0.8 <= similarity_threshold <= 1.0:
        raise ValueError("similarity_threshold must be between 0.8 and 1.0")
    observed_pages = {block.page_number for block in blocks}
    page_count = total_pages or len(observed_pages)
    if page_count < 3:
        return ()

    candidates: list[tuple[NormalizationBlock, Literal["header", "footer"], str]] = []
    for block in blocks:
        region = _margin_region(block)
        fingerprint = _fingerprint(block.normalized_text or block.raw_text)
        if region is not None and fingerprint:
            candidates.append((block, region, fingerprint))

    clusters: list[list[tuple[NormalizationBlock, Literal["header", "footer"], str]]] = []
    for candidate in sorted(
        candidates, key=lambda item: (item[1], item[0].page_number, item[0].order)
    ):
        for cluster in clusters:
            representative = cluster[0]
            if representative[1] != candidate[1]:
                continue
            similarity = SequenceMatcher(
                None, representative[2], candidate[2], autojunk=False
            ).ratio()
            if similarity >= similarity_threshold:
                cluster.append(candidate)
                break
        else:
            clusters.append([candidate])

    annotations: list[RepeatedMarginalAnnotation] = []
    minimum_pages = max(3, (page_count * 3 + 4) // 5)
    for cluster in clusters:
        pages = tuple(sorted({item[0].page_number for item in cluster}))
        if len(pages) < minimum_pages:
            continue
        representative = cluster[0]
        similarities = [
            SequenceMatcher(None, representative[2], item[2], autojunk=False).ratio()
            for item in cluster
        ]
        group_hash = hashlib.sha256(
            f"{representative[1]}:{representative[2]}".encode()
        ).hexdigest()[:20]
        for block, region, _fingerprint_value in cluster:
            legal_notice = _LEGAL_NOTICE.search(block.normalized_text or block.raw_text) is not None
            annotations.append(
                RepeatedMarginalAnnotation(
                    block_id=block.block_id,
                    classified_type=region,
                    group_id=f"marginal_{group_hash}",
                    matched_pages=pages,
                    confidence=round(sum(similarities) / len(similarities), 6),
                    excluded_from_body=not legal_notice,
                    preservation_reason=(
                        "legal_notice_retained_in_body"
                        if legal_notice
                        else "repeated_margin_excluded_from_body_but_preserved_in_cir"
                    ),
                )
            )
    return tuple(sorted(annotations, key=lambda item: item.block_id))


def _first_line(value: str) -> str:
    return _fingerprint(value.splitlines()[0] if value.splitlines() else value)


def _incomplete_sentence(value: str) -> bool:
    stripped = value.rstrip()
    return bool(stripped) and stripped[-1] not in _TERMINAL_PUNCTUATION


def _source_union(left: NormalizationBlock, right: NormalizationBlock) -> tuple[str, ...]:
    return tuple(dict.fromkeys((*left.source_ref_ids, *right.source_ref_ids)))


def _cross_page_pair(
    left: NormalizationBlock,
    right: NormalizationBlock,
) -> CrossPageRestoration | None:
    if (
        not left.source_ref_ids
        or not right.source_ref_ids
        or set(left.source_ref_ids) == set(right.source_ref_ids)
    ):
        return None
    source_refs = _source_union(left, right)
    if len(source_refs) < 2:
        return None
    if left.block_type == "table" and right.block_type == "table":
        left_header = _first_line(left.normalized_text or left.raw_text)
        right_header = _first_line(right.normalized_text or right.raw_text)
        if left_header and left_header == right_header:
            return CrossPageRestoration(
                kind="split_table_header",
                block_ids=(left.block_id, right.block_id),
                source_ref_ids=source_refs,
                from_page=left.page_number,
                to_page=right.page_number,
                reconstructed_text=None,
                uncertain=False,
                quality_flags=("repeated_table_header_preserved",),
            )
    if left.block_type == "figure" and right.block_type == "caption":
        return CrossPageRestoration(
            kind="figure_caption_continuation",
            block_ids=(left.block_id, right.block_id),
            source_ref_ids=source_refs,
            from_page=left.page_number,
            to_page=right.page_number,
            reconstructed_text=right.normalized_text or right.raw_text,
            uncertain=False,
            quality_flags=(),
        )
    if left.block_type == "footnote" and right.block_type == "footnote":
        normalized = normalize_block_text(
            f"{left.normalized_text or left.raw_text}\n{right.normalized_text or right.raw_text}",
            block_type="footnote",
        )
        return CrossPageRestoration(
            kind="footnote_continuation",
            block_ids=(left.block_id, right.block_id),
            source_ref_ids=source_refs,
            from_page=left.page_number,
            to_page=right.page_number,
            reconstructed_text=normalized.normalized_text,
            uncertain=True,
            quality_flags=("cross_page_restoration_uncertain",),
        )
    if (
        left.block_type == "heading"
        and left.bbox1000 is not None
        and left.bbox1000[1] >= 780
        and right.block_type in {"paragraph", "list"}
    ):
        return CrossPageRestoration(
            kind="heading_body_continuation",
            block_ids=(left.block_id, right.block_id),
            source_ref_ids=source_refs,
            from_page=left.page_number,
            to_page=right.page_number,
            reconstructed_text=(
                f"{left.normalized_text or left.raw_text}\n\n"
                f"{right.normalized_text or right.raw_text}"
            ),
            uncertain=False,
            quality_flags=(),
        )
    if (
        left.block_type in {"paragraph", "list", "quote"}
        and right.block_type in {"paragraph", "list", "quote"}
        and _incomplete_sentence(left.normalized_text or left.raw_text)
    ):
        normalized = normalize_block_text(
            f"{left.normalized_text or left.raw_text}\n{right.normalized_text or right.raw_text}",
            block_type="paragraph",
        )
        return CrossPageRestoration(
            kind="paragraph_continuation",
            block_ids=(left.block_id, right.block_id),
            source_ref_ids=source_refs,
            from_page=left.page_number,
            to_page=right.page_number,
            reconstructed_text=normalized.normalized_text,
            uncertain=True,
            quality_flags=("cross_page_restoration_uncertain",),
        )
    return None


def restore_cross_page_continuity(
    blocks: Sequence[NormalizationBlock],
) -> tuple[CrossPageRestoration, ...]:
    """Link supported adjacent-page continuations with at least two source refs."""

    by_page: dict[int, list[NormalizationBlock]] = {}
    for block in blocks:
        if block.block_type in {"header", "footer", "page_number"}:
            continue
        by_page.setdefault(block.page_number, []).append(block)
    restorations: list[CrossPageRestoration] = []
    for page_number in sorted(by_page):
        next_page = page_number + 1
        if next_page not in by_page:
            continue
        left_blocks = sorted(by_page[page_number], key=lambda item: (item.order, item.block_id))
        right_blocks = sorted(by_page[next_page], key=lambda item: (item.order, item.block_id))
        if not left_blocks or not right_blocks:
            continue
        restoration = _cross_page_pair(left_blocks[-1], right_blocks[0])
        if restoration is not None:
            restorations.append(restoration)
    return tuple(restorations)


__all__ = [
    "NORMALIZATION_VERSION",
    "CrossPageRestoration",
    "NormalizationBlock",
    "RepeatedMarginalAnnotation",
    "TextNormalizationResult",
    "detect_repeated_marginal_blocks",
    "normalize_block_text",
    "restore_cross_page_continuity",
]
