"""Coverage-completeness over the P0b facet model. P0c sections 3 and 4.

Named ``facet_coverage`` rather than ``coverage`` because the latter shadows the
widely installed test-coverage package: under a test runner that imports it
first, ``from coverage import FACETS`` silently resolves to the wrong module.
The rename is a name change only -- no projection, threshold or rule differs.

P0b established that an artifact's sensitivity can be *observed* rather than
declared. It did not establish that the observation is complete. A builder that
reaches a field no facet projects gets a sensitivity set that looks clean, and
its carry-forward decision is then made on a projection that never saw the input
it actually consumed. That is INC-V2-002's residual risk, stated exactly.

The founder ruling rejected adding a fourth domain facet for it — a new facet
would cover one more thing and leave the same open edge behind it. What is added
instead is an invariant over the model already in place:

    every input access a builder makes is attributed to a known facet, or the
    artifact cannot prove its coverage and may not be carried forward.

So this module differs from ``facets.py`` in three ways.

1. Access is recorded as a **(field, facet)** pair, not a bare facet. The record
   says which part of the input was consumed, not only which lens it was seen
   through.
2. There is a fallback. An access to any other field of the unit does not raise
   and does not pass silently: it is recorded as ``UNCLASSIFIED`` and the
   artifact carrying it is barred from carry-forward for the rest of its life.
3. ``STRUCTURAL`` projects ``heading`` as well as the path and the ordinal.
   P0b's structural projection did not, so a builder reading ``heading`` was
   attributed a facet whose comparison could not see the field it read. That is
   a projection-completeness repair inside the existing model, declared in the
   P0c protocol before the run. **P0b is not amended**; its result stands on its
   own projection.

The map below is the whole contract. A field absent from it is unclassified by
construction, which is the point: the failure mode being guarded against is a
field nobody remembered to think about.
"""

from __future__ import annotations

import sys
import unicodedata
from pathlib import Path
from typing import Any

sys.path.insert(
    0, str(Path(__file__).resolve().parents[3] / "packages" / "cir-python" / "src")
)

from akc_cir.identity import normalize_text_for_identity  # noqa: E402

SEMANTIC = "SEMANTIC"
LEXICAL = "LEXICAL"
STRUCTURAL = "STRUCTURAL"
UNCLASSIFIED = "UNCLASSIFIED"

#: Ordered for stable receipts, not by importance.
FACETS: tuple[str, ...] = (LEXICAL, SEMANTIC, STRUCTURAL)

#: Which facets' projections are a function of which unit field.
FIELD_FACETS: dict[str, tuple[str, ...]] = {
    "text": (LEXICAL, SEMANTIC),
    "explicit_path": (STRUCTURAL,),
    "ordinal": (STRUCTURAL,),
    "heading": (STRUCTURAL,),
}

#: Fields that are a pure function of a covered field. Reading one of these is
#: covered transitively, because the field it derives from is projected and
#: cannot move without it moving. The value is the field it derives from.
DERIVED_FIELDS: dict[str, str] = {"text_sha256": "text"}


def project(facet: str, unit: dict[str, Any]) -> Any:
    """The facet's comparable value for one unit.

    ``STRUCTURAL`` includes ``heading``. In the corpora seen so far the heading
    is the last element of the explicit path, so this changes no observed
    outcome — but "happens to be redundant here" is not coverage, and the
    invariant needs the projection to actually be a function of every field it
    claims.
    """
    if facet == LEXICAL:
        return unicodedata.normalize("NFC", unit["text"])
    if facet == SEMANTIC:
        return normalize_text_for_identity(unit["text"])
    if facet == STRUCTURAL:
        return ["/".join(unit["explicit_path"]), unit["ordinal"], unit["heading"]]
    raise KeyError("no projection for facet " + str(facet))


def covered_fields() -> frozenset[str]:
    return frozenset(FIELD_FACETS) | frozenset(DERIVED_FIELDS)


class Access:
    """One recorded input access."""

    __slots__ = ("field", "facet")

    def __init__(self, field: str, facet: str) -> None:
        self.field = field
        self.facet = facet

    def as_dict(self) -> dict[str, str]:
        return {"field": self.field, "facet": self.facet}


class CoverageView:
    """A unit that records every field a builder reads, and how.

    The named properties are the attributed accessors. ``__getattr__`` catches
    everything else that exists on the unit and records it as unclassified
    rather than raising: refusing the access would let a builder be written
    around the check, while returning it silently is the failure this guards.
    Recording it and disqualifying the artifact is the only option that leaves
    the builder honest and the decision visible.
    """

    __slots__ = ("_unit", "_log")

    def __init__(self, unit: dict[str, Any], log: list[Access]) -> None:
        object.__setattr__(self, "_unit", unit)
        object.__setattr__(self, "_log", log)

    def _record(self, field: str, facet: str) -> None:
        self._log.append(Access(field, facet))

    @property
    def text(self) -> str:
        self._record("text", LEXICAL)
        return str(self._unit["text"])

    @property
    def semantic_text(self) -> str:
        self._record("text", SEMANTIC)
        return normalize_text_for_identity(str(self._unit["text"]))

    @property
    def explicit_path(self) -> tuple[str, ...]:
        self._record("explicit_path", STRUCTURAL)
        return tuple(self._unit["explicit_path"])

    @property
    def ordinal(self) -> int:
        self._record("ordinal", STRUCTURAL)
        return int(self._unit["ordinal"])

    @property
    def heading(self) -> str:
        self._record("heading", STRUCTURAL)
        return str(self._unit["heading"])

    @property
    def text_sha256(self) -> str:
        # derived from a covered field, so attributed to that field's facets
        self._record("text_sha256", LEXICAL)
        return str(self._unit["text_sha256"])

    def __getattr__(self, name: str) -> Any:
        unit = object.__getattribute__(self, "_unit")
        if name.startswith("_") or name not in unit:
            raise AttributeError(name)
        object.__getattribute__(self, "_log").append(Access(name, UNCLASSIFIED))
        return unit[name]


class CoverageRecorder:
    """One build, one access log."""

    def __init__(self) -> None:
        self.log: list[Access] = []

    def view(self, unit: dict[str, Any]) -> CoverageView:
        return CoverageView(unit, self.log)

    @property
    def fields(self) -> tuple[str, ...]:
        return tuple(sorted({access.field for access in self.log}))

    @property
    def sensitivity(self) -> tuple[str, ...]:
        seen = {access.facet for access in self.log}
        ordered = [facet for facet in FACETS if facet in seen]
        if UNCLASSIFIED in seen:
            ordered.append(UNCLASSIFIED)
        return tuple(ordered)

    @property
    def unclassified_fields(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {access.field for access in self.log if access.facet == UNCLASSIFIED}
            )
        )

    @property
    def coverage_proven(self) -> bool:
        """True when every access was attributed and at least one was made.

        An artifact that read nothing has no proven coverage either. It cannot
        be shown to be insensitive to its inputs; it can only be shown not to
        have looked, which is the same evidential position.
        """
        return bool(self.log) and not self.unclassified_fields


def change_facets(before: dict[str, Any], after: dict[str, Any]) -> tuple[str, ...]:
    """Which known facets separate two versions of the same logical unit."""
    return tuple(
        facet for facet in FACETS if project(facet, before) != project(facet, after)
    )


def projections_identical(before_units: dict[str, Any], after_units: dict[str, Any]) -> bool:
    """Whether every known facet projection agrees across two unit sets."""
    if set(before_units) != set(after_units):
        return False
    return all(
        not change_facets(before_units[identifier], after_units[identifier])
        for identifier in before_units
    )
