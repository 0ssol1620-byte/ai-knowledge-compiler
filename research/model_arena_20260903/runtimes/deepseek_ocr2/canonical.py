"""Canonical markdown for DeepSeek-OCR-2.

This is a transcription of the post-processing in the official OmniDocBench
batch script ``DeepSeek-OCR2-vllm/run_dpsk_ocr2_eval_batch.py``
(github.com/deepseek-ai/DeepSeek-OCR-2 @ 2f3699ebbb96fa8af32212e8c170f2cc28730fad),
not a reimplementation of it. Two behaviours of that script look like bugs and
are kept anyway, because changing them would change what the official evaluator
is fed:

1. The newline collapsing (``\\n\\n\\n\\n`` -> ``\\n\\n``) runs *inside* the loop
   over grounding matches, so a page with no grounding markers is never
   collapsed at all.
2. ``clean_formula`` deletes ``\\quad (...)`` from inside ``\\[ ... \\]`` display
   formulas. That removes equation tags the model actually emitted.

Nothing here adds content. Where the official post-processing drops something
the model emitted, ``lossy`` is set and the drop is named in
``conversion_notes``; the grounding payloads are re-presented in ``elements``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from arena.worker.adapter_api import CanonicalOutput, RawOutput

# run_dpsk_ocr2_eval_batch.py: formula_pattern / process_formula.
_FORMULA_PATTERN = re.compile(r"\\\[(.*?)\\\]")
_QUAD_TAG_PATTERN = re.compile(r"\\quad\s*\([^)]*\)")
# run_dpsk_ocr2_eval_batch.py: re_match.
_GROUNDING_PATTERN = re.compile(
    r"(<\|ref\|>(.*?)<\|/ref\|><\|det\|>(.*?)<\|/det\|>)", re.DOTALL
)


def clean_formula(text: str) -> str:
    """``clean_formula`` from the official batch script, verbatim in behaviour."""

    def process_formula(match: re.Match[str]) -> str:
        formula = _QUAD_TAG_PATTERN.sub("", match.group(1))
        return r"\[" + formula.strip() + r"\]"

    return _FORMULA_PATTERN.sub(process_formula, text)


def grounding_matches(text: str) -> list[tuple[str, str, str]]:
    """``re_match`` from the official batch script: (whole, ref_label, det_payload)."""

    return [
        (whole, label, det) for whole, label, det in _GROUNDING_PATTERN.findall(text)
    ]


def strip_grounding(text: str, matches: list[tuple[str, str, str]]) -> str:
    """The official removal loop, including its inside-the-loop newline collapsing."""

    content = text
    for whole, _label, _det in matches:
        content = (
            content.replace(whole, "")
            .replace("\n\n\n\n", "\n\n")
            .replace("\n\n\n", "\n\n")
        )
    return content


def canonicalize(raw: RawOutput) -> CanonicalOutput:
    notes: list[str] = []
    text = raw.raw_text

    if not text.strip():
        return CanonicalOutput(
            markdown="",
            elements=(),
            conversion_notes=("empty model output preserved as empty markdown",),
            lossy=False,
        )

    formula_cleaned = clean_formula(text)
    if formula_cleaned != text:
        notes.append(
            "clean_formula removed \\quad(...) equation tags inside display formulas "
            "(official run_dpsk_ocr2_eval_batch.py behaviour)"
        )
    lossy = formula_cleaned != text

    matches = grounding_matches(formula_cleaned)
    markdown = strip_grounding(formula_cleaned, matches)

    elements: list[Mapping[str, Any]] = []
    for _whole, label, det in matches:
        elements.append({"category": label.strip(), "det_raw": det.strip()})
    if matches:
        lossy = True
        notes.append(
            f"removed {len(matches)} <|ref|>/<|det|> grounding markers from the markdown "
            "per the official OmniDocBench post-processing; category and det payload are "
            "kept in elements, their position in the markdown is not"
        )
    for warning in raw.warnings:
        notes.append(f"adapter warning: {warning}")

    return CanonicalOutput(
        markdown=markdown,
        elements=tuple(elements),
        conversion_notes=tuple(notes),
        lossy=lossy,
    )


__all__ = [
    "canonicalize",
    "clean_formula",
    "grounding_matches",
    "strip_grounding",
]
