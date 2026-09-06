"""Change facets and the recording view, per P0b protocol sections 3 and 4.

Selective side only. The independent oracle re-derives the projections it needs
from the protocol prose and imports nothing from here.

The recording view exists because a hand-written sensitivity declaration fails
the same way P0 v1 failed, one level up: it can be wrong, and its wrongness is
silent. A builder cannot disagree with a record of which accessors it called.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "packages" / "cir-python" / "src"))

import unicodedata  # noqa: E402

from akc_cir.identity import normalize_text_for_identity  # noqa: E402

SEMANTIC = "SEMANTIC"
LEXICAL = "LEXICAL"
STRUCTURAL = "STRUCTURAL"

#: Ordered for stable receipts, not by importance.
FACETS: tuple[str, ...] = (LEXICAL, SEMANTIC, STRUCTURAL)


def project(facet: str, unit: dict[str, Any]) -> Any:
    """The facet's comparable value for one unit."""
    if facet is LEXICAL or facet == LEXICAL:
        return unicodedata.normalize("NFC", unit["text"])
    if facet == SEMANTIC:
        return normalize_text_for_identity(unit["text"])
    if facet == STRUCTURAL:
        return ["/".join(unit["explicit_path"]), unit["ordinal"]]
    raise KeyError("no projection for facet " + str(facet))


class RecordingUnitView:
    """A unit that remembers which facets were read through it.

    Attribute access is the whole interface. There is deliberately no escape
    hatch to the underlying mapping: a builder that wants the raw dict has to
    import it from somewhere else, which is exactly the bypass P0b's
    non-empty-sensitivity gate is there to catch.
    """

    __slots__ = ("_unit", "_touched")

    def __init__(self, unit: dict[str, Any], touched: set[str]) -> None:
        object.__setattr__(self, "_unit", unit)
        object.__setattr__(self, "_touched", touched)

    @property
    def text(self) -> str:
        self._touched.add(LEXICAL)
        return str(self._unit["text"])

    @property
    def semantic_text(self) -> str:
        self._touched.add(SEMANTIC)
        return normalize_text_for_identity(str(self._unit["text"]))

    @property
    def explicit_path(self) -> tuple[str, ...]:
        self._touched.add(STRUCTURAL)
        return tuple(self._unit["explicit_path"])

    @property
    def ordinal(self) -> int:
        self._touched.add(STRUCTURAL)
        return int(self._unit["ordinal"])

    @property
    def heading(self) -> str:
        self._touched.add(STRUCTURAL)
        return str(self._unit["heading"])


class Recorder:
    """One build, one recorded sensitivity set."""

    def __init__(self) -> None:
        self.touched: set[str] = set()

    def view(self, unit: dict[str, Any]) -> RecordingUnitView:
        return RecordingUnitView(unit, self.touched)

    @property
    def sensitivity(self) -> tuple[str, ...]:
        return tuple(facet for facet in FACETS if facet in self.touched)


def change_facets(before: dict[str, Any], after: dict[str, Any]) -> tuple[str, ...]:
    """Which facets separate two versions of the same logical unit."""
    return tuple(
        facet for facet in FACETS if project(facet, before) != project(facet, after)
    )
