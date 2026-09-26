"""Canonical markdown for OvisOCR2.

Transcription of ``OvisOCR2Parser.parse`` from the official model card
(huggingface.co/ATH-MaaS/OvisOCR2 @ 1fc9221b7823a371d6e97f92d527cc847e24e107),
in the card's order:

    text = raw.strip()
    text = filter_imgtags(text)          # default in the card is filter_imgtags=True
    text = _clean_truncated_repeats(text)

The 2026-08 TAVONEL run applied these two steps in the opposite order and used a
stricter tag predicate. Both are corrected here and both are listed in README.md;
masterplan §47 H3 is the reason the order matters.
"""

from __future__ import annotations

from arena.worker.adapter_api import CanonicalOutput, RawOutput

# Model card: `block.strip().startswith('<img src="images/bbox_')`.
VISUAL_REGION_TAG_PREFIX = '<img src="images/bbox_'

# Model card `_clean_truncated_repeats` defaults.
MIN_TEXT_LEN = 8000
MAX_PERIOD = 200
MIN_PERIOD = 1
MIN_REPEAT_CHARS = 100
MIN_REPEAT_TIMES = 5


def filter_imgtags(text: str) -> str:
    """The card's default visual-region filter, predicate and join reproduced exactly."""

    return "\n\n".join(
        block
        for block in text.split("\n\n")
        if not block.strip().startswith(VISUAL_REGION_TAG_PREFIX)
    )


def clean_truncated_repeats(
    text: str,
    *,
    min_text_len: int = MIN_TEXT_LEN,
    max_period: int = MAX_PERIOD,
    min_period: int = MIN_PERIOD,
    min_repeat_chars: int = MIN_REPEAT_CHARS,
    min_repeat_times: int = MIN_REPEAT_TIMES,
) -> str:
    """``OvisOCR2Parser._clean_truncated_repeats``, verbatim in behaviour."""

    n = len(text)
    if n < min_text_len:
        return text

    max_period = min(max_period, n - 1)
    for unit_len in range(min_period, max_period + 1):
        if text[n - 1] != text[n - 1 - unit_len]:
            continue

        match_len = 1
        idx = n - 2
        while idx >= unit_len and text[idx] == text[idx - unit_len]:
            match_len += 1
            idx -= 1

        total_len = match_len + unit_len
        repeat_times = total_len // unit_len
        tail_len = total_len % unit_len

        if repeat_times >= min_repeat_times and total_len >= min_repeat_chars:
            return text[: n - total_len + unit_len] + text[n - tail_len :]

    return text


def canonicalize(raw: RawOutput) -> CanonicalOutput:
    notes: list[str] = []
    stripped = raw.raw_text.strip()

    if not stripped:
        return CanonicalOutput(
            markdown="",
            elements=(),
            conversion_notes=("empty model output preserved as empty markdown",),
            lossy=False,
        )

    filtered = filter_imgtags(stripped)
    dropped_blocks = len(stripped.split("\n\n")) - len(filtered.split("\n\n"))
    lossy = False
    if filtered != stripped:
        lossy = True
        notes.append(
            f"filter_imgtags removed {dropped_blocks} visual-region block(s) "
            f"starting with {VISUAL_REGION_TAG_PREFIX!r} (model-card default); the bbox "
            "coordinates they carried are not represented in the markdown"
        )

    cleaned = clean_truncated_repeats(filtered)
    if cleaned != filtered:
        lossy = True
        notes.append(
            f"_clean_truncated_repeats trimmed {len(filtered) - len(cleaned)} characters "
            "of a repeating tail (model-card default thresholds); the page very likely "
            "degenerated and the raw output holds the untrimmed text"
        )

    for warning in raw.warnings:
        notes.append(f"adapter warning: {warning}")

    return CanonicalOutput(
        markdown=cleaned,
        elements=None,
        conversion_notes=tuple(notes),
        lossy=lossy,
    )


__all__ = [
    "canonicalize",
    "clean_truncated_repeats",
    "filter_imgtags",
]
