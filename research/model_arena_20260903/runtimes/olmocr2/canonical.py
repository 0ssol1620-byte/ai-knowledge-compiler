"""Canonicalise olmOCR-2 output: lift the YAML front matter out of the markdown.

The toolkit's ``build_no_anchoring_v4_yaml_prompt`` asks for "a front matter section
on top specifying values for the primary_language, is_rotation_valid,
rotation_correction, is_table, and is_diagram parameters", followed by markdown with
LaTeX equations and HTML tables.

Canonical markdown is that body, verbatim. The front matter is metadata about the
page, not page content, so it moves into ``elements`` rather than being deleted and
rather than being left in the text where an evaluator would score it as prose.
Nothing is added, corrected or inferred; an unparseable front matter block is left
in the markdown and flagged.
"""

from __future__ import annotations

from typing import Any

from arena.worker.adapter_api import CanonicalOutput, RawOutput

#: The five keys the prompt names. Anything else the model writes is kept and
#: reported, never dropped and never renamed.
EXPECTED_FRONT_MATTER_KEYS = (
    "primary_language",
    "is_rotation_valid",
    "rotation_correction",
    "is_table",
    "is_diagram",
)


def canonicalize(raw: RawOutput) -> CanonicalOutput:
    notes: list[str] = []
    lossy = False
    for warning in raw.warnings:
        notes.append(f"adapter_warning:{warning}")
        if "OUTPUT_TRUNCATED" in warning or "OUTPUT_EMPTY" in warning:
            lossy = True

    front_matter: dict[str, str] | None = None
    native = raw.native_json
    if native is not None:
        candidate = native.get("front_matter")
        if isinstance(candidate, dict):
            front_matter = {str(k): str(v) for k, v in candidate.items()}

    body, split = _split_body(raw.raw_text)
    elements: list[dict[str, Any]] = []

    if front_matter is None or not split:
        notes.append(
            "no parseable YAML front matter; canonical markdown is the raw text verbatim"
        )
        body = raw.raw_text
    else:
        missing = [key for key in EXPECTED_FRONT_MATTER_KEYS if key not in front_matter]
        extra = [key for key in front_matter if key not in EXPECTED_FRONT_MATTER_KEYS]
        if missing:
            notes.append("front matter omitted: " + ", ".join(missing))
        if extra:
            notes.append("front matter carried unexpected keys: " + ", ".join(sorted(extra)))
        elements.append(
            {
                "kind": "olmocr_front_matter",
                "fields": dict(front_matter),
                "missing_expected_keys": missing,
            }
        )
        rotation = front_matter.get("rotation_correction")
        if rotation not in (None, "", "0"):
            notes.append(
                f"model reported rotation_correction={rotation!r}; "
                "the arena does not re-render or re-run the page"
            )
        if str(front_matter.get("is_rotation_valid", "")).strip().lower() in {"false", "no"}:
            notes.append(
                "model reported is_rotation_valid=False; recorded, not acted on"
            )

    image = native.get("image") if native is not None else None
    if isinstance(image, dict):
        elements.append({"kind": "arena_image_handling", "fields": dict(image)})
        if image.get("resized"):
            notes.append(
                "page was resampled to the toolkit's target longest side before inference"
            )

    if not body.strip() and raw.raw_text.strip():
        notes.append("front matter consumed the entire response; no markdown body remained")
        lossy = True

    return CanonicalOutput(
        markdown=body.strip(),
        elements=tuple(elements) if elements else None,
        conversion_notes=tuple(notes),
        lossy=lossy,
    )


def _split_body(text: str) -> tuple[str, bool]:
    """Return the markdown after the closing ``---``, and whether one was found."""
    stripped = text.lstrip()
    if not stripped.startswith("---"):
        return text, False
    lines = stripped.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return text, False
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return "".join(lines[index + 1 :]), True
    return text, False


__all__ = ["EXPECTED_FRONT_MATTER_KEYS", "canonicalize"]
