"""Adversarial fixture corpus for native provenance, and the checker that runs it.

Founder ruling, 2026-08-23, quoted in full in ``spanmap.py``: source witnesses
must survive markup stripping, whitespace normalisation, entity decoding and
block composition BY CONSTRUCTION, not by searching canonical text back inside
raw bytes. SFI1 searched and failed 1,284 units out of 122,349 — not a tuning
problem, a category error. This corpus is what proves the replacement actually
survives the twelve ways that category error shows up, or catches that it does
not.

Two design decisions carry this file, both inherited from
``adversarial_fixtures.py`` because they are the right decisions and inventing
a second vocabulary next to a working one would only cost coverage:

**Expectations are properties, not golden strings.** ``SpanCoversBytes`` reads
the actual raw payload slice a span claims and asserts what must and must not
be in it. A golden output string would go red the day a representation
improves and stay green the day it is wrong in a way nobody noticed yet.

**An unexercised fixture is never a pass.** Two layers here, not one:
``check(fixture, document)`` judges a document that already exists — the
unconditional half of the suite hand-builds one per fixture with ``spanmap``
itself, so the checker can be judged without any extractor at all.
``check_through_canonicaliser`` is the layer that runs a fixture through the
real thing, ``canonicalization/provenance_document.py``.

A prior session found that real entrypoint's actual shape did not match this
corpus's original single-raw-bytes-in assumption: ``provenance_document`` is
keyword-only and requires a full document-assembly context (source_family,
source_id, version_id, source_digest, known_at, valid_from, licence) alongside
the payload. That session correctly declined to fabricate a PROVENANCE answer
to force a call through — but left every fixture reporting ``NOT_EXERCISED``,
which is a corpus with no gate power at all.

The reconciliation, per founder ruling: those seven non-payload parameters are
the constructor's CALLING CONTEXT, not a claim about the fixture's origin.
Supplying them is not the fabrication that was correctly refused — that refusal
was about inventing a PROVENANCE answer (attributing text to bytes that never
produced it). ``FIXTURE_METADATA`` below is declared once, visibly, and
``known_at``/``valid_from`` — the two fields that WOULD be a provenance claim
if invented — are left ``None`` rather than guessed. ``source_digest`` is never
a literal: it is computed from each fixture's own raw bytes at call time.

The second half of the reconciliation is structural. ``provenance_document``
enforces ``MIN_TEXT_CHARS = 120`` before a block-assembly section is emitted at
all (``assemble()``'s ``flush()`` silently drops anything shorter), and
``explicit_path`` comes from real Markdown ATX headings (or, for the
``sec_edgar`` family, real HTML block/heading structure) — not from a literal
string chosen by this corpus. Every fixture below is therefore wrapped in a
heading that names its own unit hint, and padded with neutral filler text long
enough to clear the threshold. The padding is a DECLARED byte segment in the
same ``_cum(...)`` offset arithmetic already used to build the adversarial
core, so nothing about the padding's own placement is hand-counted; a test in
``tests/test_provenance_fixtures.py`` asserts no fixture's padding contains any
of that same fixture's ``must_not_contain`` bytes. The adversarial construct
itself — every ``_XXX_RAW``-shaped byte string — keeps its exact original
bytes; padding surrounds it, never sits between it and the region an
expectation names, and never alters it.

Because padding shifts a fixture's canonical text by however many characters
precede it — and that shift differs by transformation stage in ways not worth
hand-deriving 12 times — ``within`` no longer has to be a fixed offset pair.
``WithinText`` and ``WithinGap`` (below) resolve a region by searching the
UNIT'S OWN canonical text for a distinctive substring (or the gap between two
of them) at evaluation time. This is not a weaker check: what is under test is
still whether the SPAN behind that region is correct, and locating the region
by its own content is the same discipline ``_find_unit`` already applies to
locate a unit by heading — it does not touch raw bytes, only navigates the
canonical text the real document already produced.

The module imports nothing from the canonicaliser at parse time. The only
frozen dependency is ``spanmap`` — the provenance spine this corpus exists to
hold accountable — and even that dependency is used only to let the
hand-built reference documents be built the same way a correct implementation
must build them: by construction, one emission at a time, never by search.
"""

from __future__ import annotations

import hashlib
import importlib
import inspect
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

#: Package-qualified, matching adversarial_fixtures.py's own reasoning: two
#: import paths for this namespace must resolve to one module object, or a
#: hand-built SpanMap here and the SpanMap a real extractor produces stop being
#: the same class and every isinstance-shaped check silently degrades.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from source_fact_ir.spanmap import Segment, SpanMap, TrackedText

SCHEMA = "tavonel.v2.source_fact_ir.provenance_fixtures.v1"


# ---------------------------------------------------------------------------
# fixture classes
#
# The twelve named in the mandate, in the order they were given. A fixture
# class is a string rather than an enum so a receipt can carry it without an
# import, exactly as in adversarial_fixtures.py.

ENTITY_DECODING = "ENTITY_DECODING"
WHITESPACE_NORMALIZATION = "WHITESPACE_NORMALIZATION"
MARKUP_STRIPPING = "MARKUP_STRIPPING"
BLOCK_COMPOSITION_JOIN = "BLOCK_COMPOSITION_JOIN"
MULTIBYTE_UTF8 = "MULTIBYTE_UTF8"
NESTED_MARKUP = "NESTED_MARKUP"
LINK_TEXT_VS_TARGET = "LINK_TEXT_VS_TARGET"
ATTRIBUTE_VS_TEXT = "ATTRIBUTE_VS_TEXT"
MALFORMED_TAG_FAIL_CLOSED = "MALFORMED_TAG_FAIL_CLOSED"
DUPLICATE_CONTENT = "DUPLICATE_CONTENT"
TEXT_NOT_IN_SOURCE = "TEXT_NOT_IN_SOURCE"
SUBSTRING_OF_EARLIER_UNIT = "SUBSTRING_OF_EARLIER_UNIT"

#: The twelve the founder mandated at minimum, in the order given. Coverage is
#: asserted against this tuple in the test suite, never against ``CLASSES``,
#: so an added class can never dilute the mandate.
MANDATED_CLASSES: tuple[str, ...] = (
    ENTITY_DECODING,
    WHITESPACE_NORMALIZATION,
    MARKUP_STRIPPING,
    BLOCK_COMPOSITION_JOIN,
    MULTIBYTE_UTF8,
    NESTED_MARKUP,
    LINK_TEXT_VS_TARGET,
    ATTRIBUTE_VS_TEXT,
    MALFORMED_TAG_FAIL_CLOSED,
    DUPLICATE_CONTENT,
    TEXT_NOT_IN_SOURCE,
    SUBSTRING_OF_EARLIER_UNIT,
)

CLASSES: tuple[str, ...] = MANDATED_CLASSES


# ---------------------------------------------------------------------------
# outcomes

PASS = "PASS"  # noqa: S105 - an outcome status, not a credential
FAIL = "FAIL"
NOT_EXERCISED = "NOT_EXERCISED"

STATUSES: tuple[str, ...] = (PASS, FAIL, NOT_EXERCISED)


@dataclass(frozen=True)
class Outcome:
    """What running one fixture against one document established.

    Three values, not two, for the same reason ``adversarial_fixtures.Outcome``
    has three: ``NOT_EXERCISED`` is the honest answer when nothing ran, and it
    is deliberately not ``PASS`` — a corpus whose green count includes fixtures
    nobody ran reports coverage it does not have.
    """

    fixture_id: str
    status: str
    reason: str
    detail: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"unknown outcome status {self.status!r}")
        if not self.reason:
            raise ValueError(
                f"outcome {self.status} for {self.fixture_id!r} with no reason. A verdict "
                "nobody can act on is not a verdict."
            )

    @property
    def passed(self) -> bool:
        """True only for PASS. NOT_EXERCISED is not a pass and never becomes one."""
        return self.status == PASS

    def as_dict(self) -> dict[str, Any]:
        return {
            "fixture_id": self.fixture_id,
            "status": self.status,
            "reason": self.reason,
            "detail": self.detail,
        }


# ---------------------------------------------------------------------------
# unit lookup
#
# Units are identified by a stable hint, never by index into a list whose
# ordering another workstream controls. A heading-path tuple is preferred; a
# bare int falls back to matching a unit's own "ordinal" field first, and only
# to list position if no unit declares one — so a hint is never silently wrong
# just because a document happens to omit "ordinal".

UnitHint = tuple[str, ...] | int


def _find_unit(document: dict[str, Any], hint: UnitHint) -> dict[str, Any] | None:
    units = document.get("units") or ()
    if isinstance(hint, int):
        for unit in units:
            if unit.get("ordinal") == hint:
                return unit
        if 0 <= hint < len(units):
            return units[hint]
        return None
    hint_path = tuple(hint)
    for unit in units:
        if tuple(unit.get("explicit_path", ())) == hint_path:
            return unit
    return None


def _unit_span_map(unit: dict[str, Any]) -> SpanMap | None:
    """The unit's live SpanMap, rebuilt from a serialized form if that is all it has.

    A real document is a JSON-shaped artifact, so a real extractor is entitled
    to hand back ``span_map`` as ``SpanMap.as_list()`` rather than a live
    object. Rebuilding it here (via the same ``Segment`` the spine itself
    defines) keeps this corpus able to judge that shape without loosening what
    it checks — ``to_source``/``is_fully_sourced`` still run for real, just on
    a map reconstructed from data instead of held in memory.
    """
    span_map = unit.get("span_map")
    if isinstance(span_map, SpanMap):
        return span_map
    if isinstance(span_map, list):
        try:
            segments = [
                Segment(
                    out_start=item["out_start"],
                    out_end=item["out_end"],
                    source_start=item["source_start"] if item["source_start"] is not None else -1,
                    source_end=item["source_end"] if item["source_end"] is not None else -1,
                    kind=item["kind"],
                )
                for item in span_map
            ]
        except (KeyError, TypeError, ValueError):
            return None
        return SpanMap(segments)
    return None


# ---------------------------------------------------------------------------
# dynamic within-locators
#
# Padding shifts a fixture's canonical text by however many characters precede
# it, and that shift is a different function of clean_markdown/normalise for
# every fixture (tag-derived spaces, join separators, entity decoding). Rather
# than hand-deriving 12 different offset formulas — exactly the kind of
# hand-counting this whole corpus exists to distrust — a locator finds its own
# region by searching the unit's own canonical text, at evaluation time. This
# still tests the SPAN behind that region, not the text; it only changes how
# the (out_start, out_end) input to that check is found, the same way
# ``_find_unit`` locates a unit by heading rather than list position.


@dataclass(frozen=True)
class WithinText:
    """The range of ``needle``'s ``occurrence``-th appearance in the unit's own text."""

    needle: str
    occurrence: int = 0

    def resolve(self, text: str) -> tuple[int, int] | None:
        pos = 0
        start = -1
        for _ in range(self.occurrence + 1):
            start = text.find(self.needle, pos)
            if start < 0:
                return None
            pos = start + 1
        return (start, start + len(self.needle))

    def describe(self) -> str:
        return f"the span of {self.needle!r} (occurrence {self.occurrence}) in its own text"


@dataclass(frozen=True)
class WithinGap:
    """The range strictly between the end of ``before`` and the start of ``after``.

    For a region with no bytes of its own to search for — a join separator, an
    inserted value — locating it by what surrounds it is the only honest way
    to find it without hand-counting an offset padding would invalidate.
    """

    before: str
    after: str

    def resolve(self, text: str) -> tuple[int, int] | None:
        before_at = text.find(self.before)
        if before_at < 0:
            return None
        gap_start = before_at + len(self.before)
        after_at = text.find(self.after, gap_start)
        if after_at < 0:
            return None
        return (gap_start, after_at)

    def describe(self) -> str:
        return f"the gap between {self.before!r} and {self.after!r} in its own text"


Within = tuple[int, int] | WithinText | WithinGap


def _resolve_within(within: Within | None, text: str) -> tuple[tuple[int, int] | None, str | None]:
    """(range, problem). ``problem`` is set only when a dynamic locator could not resolve."""
    if within is None:
        return (0, len(text)), None
    if isinstance(within, (WithinText, WithinGap)):
        resolved = within.resolve(text)
        if resolved is None:
            return None, (
                f"within-locator ({within.describe()}) did not resolve against its own text "
                f"{text!r}"
            )
        return resolved, None
    return within, None


# ---------------------------------------------------------------------------
# expectations
#
# Each one answers two questions: what must be true of a document that already
# exists, and — given the document and the fixture's own raw bytes — did the
# property hold. None of them ever raises for ordinary disagreement.


@runtime_checkable
class Expectation(Protocol):
    def describe(self) -> str:
        """One line of what must be true, in this corpus's own vocabulary."""

    def evaluate(self, document: dict[str, Any], *, raw: bytes) -> tuple[bool, str, dict[str, Any]]:
        """(held, reason, detail). Never raises for ordinary disagreement."""


@dataclass(frozen=True)
class SpanCoversBytes:
    """The strongest and simplest check: read the actual raw payload slice.

    ``within`` is an offset pair into the unit's own canonical text (default:
    the whole unit), OR a ``WithinText``/``WithinGap`` locator resolved against
    that same text at evaluation time. The span behind that range is resolved
    through the unit's live ``span_map`` — never through a cached
    ``source_span``, so a fixture always judges what the map says now, not
    what it said when the unit was built.

    ``must_not_contain`` is what catches a span that points at the wrong
    occurrence of otherwise-identical text: such a span still "contains" the
    text asked for, so only a check against what must be ABSENT catches it.
    """

    unit_hint: UnitHint
    must_contain: bytes | None = None
    must_not_contain: bytes | None = None
    within: Within | None = None

    def __post_init__(self) -> None:
        if self.must_contain is None and self.must_not_contain is None:
            raise ValueError(
                "SpanCoversBytes with neither must_contain nor must_not_contain checks nothing"
            )
        if isinstance(self.within, tuple) and self.within[1] < self.within[0]:
            raise ValueError(f"within is not a range: {self.within}")

    def describe(self) -> str:
        where = f" within {self.within!r}" if self.within is not None else ""
        parts = []
        if self.must_contain is not None:
            parts.append(f"must contain {self.must_contain!r}")
        if self.must_not_contain is not None:
            parts.append(f"must not contain {self.must_not_contain!r}")
        return f"unit {self.unit_hint!r}{where} span " + " and ".join(parts)

    def evaluate(
        self, document: dict[str, Any], *, raw: bytes
    ) -> tuple[bool, str, dict[str, Any]]:
        unit = _find_unit(document, self.unit_hint)
        if unit is None:
            return (
                False,
                f"no unit matching hint {self.unit_hint!r}",
                {"hint": repr(self.unit_hint)},
            )
        text = unit.get("text", "")
        resolved, problem = _resolve_within(self.within, text)
        if problem is not None:
            return False, f"unit {self.unit_hint!r}: {problem}", {}
        out_start, out_end = resolved
        span_map = _unit_span_map(unit)
        if span_map is not None:
            source = span_map.to_source(out_start, out_end)
        elif self.within is None and unit.get("source_span") is not None:
            source = tuple(unit["source_span"])
        else:
            source = None
        if source is None:
            return (
                False,
                f"unit {self.unit_hint!r} range {(out_start, out_end)} has no source span; "
                "SpanCoversBytes cannot check bytes that do not exist (use SpanAbsent instead)",
                {"range": (out_start, out_end)},
            )
        start, end = source
        if start < 0 or end > len(raw):
            return (
                False,
                f"source span {source} for unit {self.unit_hint!r} falls outside the raw "
                f"payload (length {len(raw)})",
                {"source": source, "raw_length": len(raw)},
            )
        window = raw[start:end]
        detail: dict[str, Any] = {
            "source": source,
            "window": window[:120].decode("utf-8", "replace"),
        }
        if self.must_contain is not None and self.must_contain not in window:
            return (
                False,
                f"span for unit {self.unit_hint!r} does not contain {self.must_contain!r}; "
                f"it covers raw[{start}:{end}] = {window[:80]!r}",
                detail,
            )
        if self.must_not_contain is not None and self.must_not_contain in window:
            return (
                False,
                f"span for unit {self.unit_hint!r} contains {self.must_not_contain!r}, which it "
                "must not — this is the signature of a span pointing at the wrong bytes (a "
                "duplicate occurrence, a neighbouring word, a stripped delimiter, an attribute)",
                detail,
            )
        return True, "the span covers exactly the required bytes", detail


@dataclass(frozen=True)
class FullySourced:
    """Every character of the unit's text must trace to some source byte."""

    unit_hint: UnitHint

    def describe(self) -> str:
        return f"unit {self.unit_hint!r} must be fully sourced (every character has a source)"

    def evaluate(
        self, document: dict[str, Any], *, raw: bytes
    ) -> tuple[bool, str, dict[str, Any]]:
        unit = _find_unit(document, self.unit_hint)
        if unit is None:
            return False, f"no unit matching hint {self.unit_hint!r}", {}
        fully = _fully_sourced(unit)
        if fully is None:
            return (
                False,
                f"unit {self.unit_hint!r} carries neither 'fully_sourced' nor a 'span_map' to "
                "compute it from",
                {},
            )
        if not fully:
            return (
                False,
                f"unit {self.unit_hint!r} is not fully sourced, but the fixture requires it to be",
                {"fully_sourced": fully},
            )
        return True, "every character in the unit is sourced", {"fully_sourced": fully}


@dataclass(frozen=True)
class NotFullySourced:
    """The unit must NOT be fully sourced — some of its text is honestly unsourced.

    ``why`` documents the expected cause (a join separator, a computed value)
    for a reader of the fixture; it is not itself checked against the
    document, because the document's own honesty is what ``fully_sourced``
    already states.
    """

    unit_hint: UnitHint
    why: str

    def __post_init__(self) -> None:
        if not self.why:
            raise ValueError("NotFullySourced with no reason does not say why that is expected")

    def describe(self) -> str:
        return f"unit {self.unit_hint!r} must NOT be fully sourced ({self.why})"

    def evaluate(
        self, document: dict[str, Any], *, raw: bytes
    ) -> tuple[bool, str, dict[str, Any]]:
        unit = _find_unit(document, self.unit_hint)
        if unit is None:
            return False, f"no unit matching hint {self.unit_hint!r}", {}
        fully = _fully_sourced(unit)
        if fully is None:
            return (
                False,
                f"unit {self.unit_hint!r} carries neither 'fully_sourced' nor a 'span_map' to "
                "compute it from",
                {},
            )
        if fully:
            return (
                False,
                f"unit {self.unit_hint!r} is reported fully sourced, but {self.why}; a correct "
                "implementation cannot claim a source for text that has none",
                {"fully_sourced": fully},
            )
        return True, f"the unit is honestly not fully sourced: {self.why}", {"fully_sourced": fully}


@dataclass(frozen=True)
class SpanAbsent:
    """The named region must have NO source span — fail-closed, not a wrong guess.

    For malformed markup and other undecidable locations: an absent span is
    visible and countable, a wrong one is a silent mis-attribution.
    """

    unit_hint: UnitHint
    within: Within | None = None

    def __post_init__(self) -> None:
        if isinstance(self.within, tuple) and self.within[1] < self.within[0]:
            raise ValueError(f"within is not a range: {self.within}")

    def describe(self) -> str:
        where = f" within {self.within!r}" if self.within is not None else " (whole unit)"
        return f"unit {self.unit_hint!r}{where} must have NO source span"

    def evaluate(
        self, document: dict[str, Any], *, raw: bytes
    ) -> tuple[bool, str, dict[str, Any]]:
        unit = _find_unit(document, self.unit_hint)
        if unit is None:
            return False, f"no unit matching hint {self.unit_hint!r}", {}
        text = unit.get("text", "")
        resolved, problem = _resolve_within(self.within, text)
        if problem is not None:
            return False, f"unit {self.unit_hint!r}: {problem}", {}
        out_start, out_end = resolved
        span_map = _unit_span_map(unit)
        if span_map is not None:
            source = span_map.to_source(out_start, out_end)
        elif self.within is None:
            source = unit.get("source_span")
        else:
            source = None
        if source is not None:
            return (
                False,
                f"unit {self.unit_hint!r} range {(out_start, out_end)} has a source span "
                f"{source}, but this region cannot be safely attributed and must fail closed "
                "with no span at all",
                {"source": source},
            )
        return True, "no source span was claimed, as required", {}


@dataclass(frozen=True)
class AllOf:
    """Every part must hold. Fails on the first part that does not, naming it."""

    parts: tuple[Expectation, ...]

    def __post_init__(self) -> None:
        if len(self.parts) < 2:
            raise ValueError("AllOf with fewer than two parts is just the part")

    def describe(self) -> str:
        return " AND ".join(part.describe() for part in self.parts)

    def evaluate(
        self, document: dict[str, Any], *, raw: bytes
    ) -> tuple[bool, str, dict[str, Any]]:
        detail: dict[str, Any] = {}
        for index, part in enumerate(self.parts):
            held, reason, part_detail = part.evaluate(document, raw=raw)
            detail[f"part_{index}"] = {"held": held, "reason": reason, "detail": part_detail}
            if not held:
                return False, f"part {index} ({type(part).__name__}) failed: {reason}", detail
        return True, "every part held", detail


def _fully_sourced(unit: dict[str, Any]) -> bool | None:
    fully = unit.get("fully_sourced")
    if fully is not None:
        return bool(fully)
    span_map = _unit_span_map(unit)
    if span_map is None:
        return None
    return span_map.is_fully_sourced(0, len(unit.get("text", "")))


# ---------------------------------------------------------------------------
# the fixture record


@dataclass(frozen=True)
class Fixture:
    """One adversarial document, frozen, with its expectation and a reference build.

    ``raw`` is the only INPUT a real canonicaliser reads for content — it is
    the whole payload, adversarial construct plus the heading and padding
    needed to make ``provenance_document`` actually emit a unit for it.
    ``reference_document`` is a zero-argument callable that builds the CORRECT
    document by hand, using ``spanmap.TrackedText`` the same way a correct
    implementation must — one emission at a time, source named at the moment
    it is still known — so the unconditional half of the suite can judge
    ``check`` without any extractor existing yet.

    ``source_family`` is calling context for the real canonicaliser (it picks
    the Markdown or the ``sec_edgar`` HTML reader), not a claim about the
    fixture's provenance — see the module docstring's founder-ruling
    discussion. ``padding`` names the filler byte segments this fixture wraps
    its adversarial construct in, so a test can assert none of them leak a
    ``must_not_contain`` byte string into the window under test.
    """

    fixture_id: str
    fixture_class: str
    raw: bytes
    requirement: str
    expectation: Expectation
    naive_failure: str
    reference_document: Callable[[], dict[str, Any]]
    source_family: str = "internal_markdown_corpus"
    padding: tuple[bytes, ...] = ()

    def __post_init__(self) -> None:
        if self.fixture_class not in CLASSES:
            raise ValueError(f"fixture {self.fixture_id!r} declares unknown class")
        if not isinstance(self.raw, bytes):
            raise ValueError(f"fixture {self.fixture_id!r} source must be raw bytes, not str")
        if not self.requirement or not self.naive_failure:
            raise ValueError(f"fixture {self.fixture_id!r} does not say what it is for")

    def as_dict(self) -> dict[str, Any]:
        return {
            "fixture_id": self.fixture_id,
            "fixture_class": self.fixture_class,
            "requirement": self.requirement,
            "expectation": {
                "type": type(self.expectation).__name__,
                "describes": self.expectation.describe(),
            },
            "naive_failure": self.naive_failure,
            "raw_sha256": "sha256:" + hashlib.sha256(self.raw).hexdigest(),
            "source_family": self.source_family,
        }


# ---------------------------------------------------------------------------
# construction helpers
#
# ``_cum`` computes cumulative byte offsets from a sequence of raw segments so
# a fixture's own correct offsets are read off the segment boundaries rather
# than hand-counted — the discipline this corpus asks of a real implementation,
# applied to building the corpus itself.


def _cum(*segments: bytes) -> list[int]:
    offsets = [0]
    for segment in segments:
        offsets.append(offsets[-1] + len(segment))
    return offsets


def _unit(
    explicit_path: Iterable[str], tracked: TrackedText, *, ordinal: int = 0
) -> dict[str, Any]:
    text = tracked.text
    span_map = tracked.map
    return {
        "explicit_path": list(explicit_path),
        "ordinal": ordinal,
        "text": text,
        "source_span": span_map.to_source(0, len(text)),
        "fully_sourced": span_map.is_fully_sourced(0, len(text)),
        "span_map": span_map,
    }


def _doc(*units: dict[str, Any]) -> dict[str, Any]:
    return {"units": list(units)}


def _md_heading(name: str, level: int = 1) -> bytes:
    return ("#" * level + " " + name + "\n\n").encode("utf-8")


# ---------------------------------------------------------------------------
# shared padding
#
# Neutral, ASCII, single-spaced filler with no markdown/HTML-special
# characters and no word shared with any fixture's must_contain/must_not_contain
# or WithinText/WithinGap needle — reused across fixtures because a dynamic
# locator does not care where in the combined text its needle ends up. Each
# fixture declares it as its own segment in that fixture's ``_cum(...)`` call,
# never folded silently into a neighbouring segment's length.

PAD_BEFORE = (
    b"Filler context marker alpha bravo charlie delta echo foxtrot golf hotel "
    b"india juliet kilo lima mike november oscar papa."
)
PAD_AFTER = (
    b"Trailing context marker quebec romeo sierra tango uniform victor whiskey "
    b"xray yankee zulu alpha bravo charlie delta echo."
)


# ---------------------------------------------------------------------------
# fixture 1 — entity decoding
#
# Naive failure: computing the span from the DECODED text's character offset
# and reusing it as a raw byte offset (as if one decoded character were one
# raw byte) lands inside "caf" or "&eac", never on the whole entity.

_ENT_OPEN = b"<p>"
_ENT_BEFORE = b"Meeting at caf"
_ENT_ENTITY = b"&eacute;"
_ENT_AFTER = b" today."
_ENT_CLOSE = b"</p>"
_ENT_HEADING = _md_heading("meeting")
_ENTITY_RAW = (
    _ENT_HEADING
    + PAD_BEFORE
    + b" "
    + _ENT_OPEN
    + _ENT_BEFORE
    + _ENT_ENTITY
    + _ENT_AFTER
    + _ENT_CLOSE
    + b" "
    + PAD_AFTER
)
_ENT_OFF = _cum(
    _ENT_HEADING,
    PAD_BEFORE,
    b" ",
    _ENT_OPEN,
    _ENT_BEFORE,
    _ENT_ENTITY,
    _ENT_AFTER,
    _ENT_CLOSE,
    b" ",
    PAD_AFTER,
)


def _entity_decoding_document() -> dict[str, Any]:
    tracked = TrackedText()
    tracked.copy(PAD_BEFORE.decode(), _ENT_OFF[1], _ENT_OFF[2])
    tracked.copy(" ", _ENT_OFF[2], _ENT_OFF[3])
    tracked.copy("Meeting at caf", _ENT_OFF[4], _ENT_OFF[5])
    tracked.replace("é", _ENT_OFF[5], _ENT_OFF[6])
    tracked.copy(" today.", _ENT_OFF[6], _ENT_OFF[7])
    tracked.copy(" ", _ENT_OFF[8], _ENT_OFF[9])
    tracked.copy(PAD_AFTER.decode(), _ENT_OFF[9], _ENT_OFF[10])
    return _doc(_unit(("meeting",), tracked))


# ---------------------------------------------------------------------------
# fixture 2 — whitespace normalisation across a newline/tab run
#
# Naive failure: collapsing "\n\t " to a single space in the text buffer while
# still walking the RAW string with a plain index cursor drifts by however many
# bytes the run collapsed away, so every span after the first collapse is off.

_WS_BEFORE = b"Retention"
_WS_RUN = b"\n\t "
_WS_AFTER = b"is thirty days."
_WS_HEADING = _md_heading("retention")
_WHITESPACE_RAW = (
    _WS_HEADING + PAD_BEFORE + b" " + _WS_BEFORE + _WS_RUN + _WS_AFTER + b" " + PAD_AFTER
)
_WS_OFF = _cum(_WS_HEADING, PAD_BEFORE, b" ", _WS_BEFORE, _WS_RUN, _WS_AFTER, b" ", PAD_AFTER)


def _whitespace_document() -> dict[str, Any]:
    tracked = TrackedText()
    tracked.copy(PAD_BEFORE.decode(), _WS_OFF[1], _WS_OFF[2])
    tracked.copy(" ", _WS_OFF[2], _WS_OFF[3])
    tracked.copy("Retention", _WS_OFF[3], _WS_OFF[4])
    tracked.replace(" ", _WS_OFF[4], _WS_OFF[5])
    tracked.copy("is thirty days.", _WS_OFF[5], _WS_OFF[6])
    tracked.copy(" ", _WS_OFF[6], _WS_OFF[7])
    tracked.copy(PAD_AFTER.decode(), _WS_OFF[7], _WS_OFF[8])
    return _doc(_unit(("retention",), tracked))


# ---------------------------------------------------------------------------
# fixture 3 — markup stripping
#
# Naive failure: a span computed as "the whole **bold** run" includes the
# delimiters in the source range even though they produced no output
# character, so the span covers two bytes of asterisk that back nothing.

_MK_BEFORE = b"This is "
_MK_OPEN_STAR = b"**"
_MK_WORD = b"bold"
_MK_CLOSE_STAR = b"**"
_MK_AFTER = b" text."
_MK_HEADING = _md_heading("markup")
_MARKUP_RAW = (
    _MK_HEADING
    + PAD_BEFORE
    + b" "
    + _MK_BEFORE
    + _MK_OPEN_STAR
    + _MK_WORD
    + _MK_CLOSE_STAR
    + _MK_AFTER
    + b" "
    + PAD_AFTER
)
_MK_OFF = _cum(
    _MK_HEADING,
    PAD_BEFORE,
    b" ",
    _MK_BEFORE,
    _MK_OPEN_STAR,
    _MK_WORD,
    _MK_CLOSE_STAR,
    _MK_AFTER,
    b" ",
    PAD_AFTER,
)


def _markup_stripping_document() -> dict[str, Any]:
    tracked = TrackedText()
    tracked.copy(PAD_BEFORE.decode(), _MK_OFF[1], _MK_OFF[2])
    tracked.copy(" ", _MK_OFF[2], _MK_OFF[3])
    tracked.copy("This is ", _MK_OFF[3], _MK_OFF[4])
    tracked.copy("bold", _MK_OFF[5], _MK_OFF[6])
    tracked.copy(" text.", _MK_OFF[7], _MK_OFF[8])
    tracked.copy(" ", _MK_OFF[8], _MK_OFF[9])
    tracked.copy(PAD_AFTER.decode(), _MK_OFF[9], _MK_OFF[10])
    return _doc(_unit(("markup",), tracked))


# ---------------------------------------------------------------------------
# fixture 4 — block composition: two blocks joined under one heading
#
# Naive failure: a join that concatenates two blocks' text with a separator
# and then, needing a span for the whole unit, spans "start of block one" to
# "end of block two" — silently claiming the inserted separator has a source
# too, which is exactly the untraceable character the ruling forbids.
#
# ``assemble()``'s insert-join only fires between two SEPARATE blocks under one
# heading, and the real canonicaliser only produces separate blocks this way
# through its HTML/sec_edgar reader (each ``<p>`` its own block) — Markdown
# ATX headings cannot express "two body blocks, one heading" at all. This
# fixture therefore uses ``source_family="sec_edgar"``, and its two `<p>`
# elements (each other's own reader-level block) are the structural
# reconciliation this corpus's own docstring calls for; ``_BLK_FIRST`` and
# ``_BLK_SECOND`` — the text actually under test — keep their exact original
# bytes.

_BLK_FIRST = b"First block text here."
_BLK_SECOND = b"Second block text here."
_BLK_HEADING = b"<h1>joined</h1>"
_BLK_PAD_OPEN = b"<p>"
_BLK_PAD_CLOSE = b"</p>"
_BLK_MID = b"</p><p>"
_BLOCK_JOIN_RAW = (
    _BLK_HEADING
    + _BLK_PAD_OPEN
    + PAD_BEFORE
    + _BLK_PAD_CLOSE
    + _BLK_PAD_OPEN
    + _BLK_FIRST
    + _BLK_MID
    + _BLK_SECOND
    + _BLK_PAD_CLOSE
    + _BLK_PAD_OPEN
    + PAD_AFTER
    + _BLK_PAD_CLOSE
)
_BLK_OFF = _cum(
    _BLK_HEADING,
    _BLK_PAD_OPEN,
    PAD_BEFORE,
    _BLK_PAD_CLOSE,
    _BLK_PAD_OPEN,
    _BLK_FIRST,
    _BLK_MID,
    _BLK_SECOND,
    _BLK_PAD_CLOSE,
    _BLK_PAD_OPEN,
    PAD_AFTER,
    _BLK_PAD_CLOSE,
)


def _block_composition_document() -> dict[str, Any]:
    tracked = TrackedText()
    tracked.copy(PAD_BEFORE.decode(), _BLK_OFF[2], _BLK_OFF[3])
    tracked.insert(" ")  # join: padding block to first block, genuinely from nothing
    tracked.copy("First block text here.", _BLK_OFF[5], _BLK_OFF[6])
    tracked.insert(" ")  # the join separator under test: genuinely from nothing
    tracked.copy("Second block text here.", _BLK_OFF[7], _BLK_OFF[8])
    tracked.insert(" ")  # join: second block to padding block, genuinely from nothing
    tracked.copy(PAD_AFTER.decode(), _BLK_OFF[10], _BLK_OFF[11])
    return _doc(_unit(("joined",), tracked))


# ---------------------------------------------------------------------------
# fixture 5 — UTF-8 multi-byte content, char-offset vs byte-offset confusion
#
# Naive failure: using Python string length (character count) as if it were a
# byte count. Each CJK character here is 3 UTF-8 bytes, so a char-counted span
# lands a third of the way into the intended region and bleeds into ASCII
# neighbours on both sides.

_MB_BEFORE = "Warranty period: "
_MB_CJK = "保証期間"  # four CJK characters, 12 UTF-8 bytes
_MB_AFTER = " is thirty days."
_MB_OPEN = b"<p>"
_MB_CLOSE = b"</p>"
_MB_HEADING = _md_heading("warranty")
_MULTIBYTE_RAW = (
    _MB_HEADING
    + PAD_BEFORE
    + b" "
    + _MB_OPEN
    + _MB_BEFORE.encode("utf-8")
    + _MB_CJK.encode("utf-8")
    + _MB_AFTER.encode("utf-8")
    + _MB_CLOSE
    + b" "
    + PAD_AFTER
)
_MB_OFF = _cum(
    _MB_HEADING,
    PAD_BEFORE,
    b" ",
    _MB_OPEN,
    _MB_BEFORE.encode("utf-8"),
    _MB_CJK.encode("utf-8"),
    _MB_AFTER.encode("utf-8"),
    _MB_CLOSE,
    b" ",
    PAD_AFTER,
)


def _multibyte_document() -> dict[str, Any]:
    tracked = TrackedText()
    tracked.copy(PAD_BEFORE.decode(), _MB_OFF[1], _MB_OFF[2])
    tracked.copy(" ", _MB_OFF[2], _MB_OFF[3])
    tracked.copy(_MB_BEFORE, _MB_OFF[4], _MB_OFF[5])
    tracked.copy(_MB_CJK, _MB_OFF[5], _MB_OFF[6])
    tracked.copy(_MB_AFTER, _MB_OFF[6], _MB_OFF[7])
    tracked.copy(" ", _MB_OFF[8], _MB_OFF[9])
    tracked.copy(PAD_AFTER.decode(), _MB_OFF[9], _MB_OFF[10])
    return _doc(_unit(("warranty",), tracked))


# ---------------------------------------------------------------------------
# fixture 6 — nested markup: bold wrapping inline code
#
# Naive failure: a delimiter-matching stack that pops too early on the inner
# backtick pair loses track of the outer bold run's true close, so the span
# for "code" walks past its own backticks into neighbouring bold text.

_NEST_A = b"Note: "
_NEST_STAR1 = b"**"
_NEST_B = b"bold with "
_NEST_TICK1 = b"`"
_NEST_CODE = b"code"
_NEST_TICK2 = b"`"
_NEST_C = b" inside"
_NEST_STAR2 = b"**"
_NEST_D = b" end."
_NEST_HEADING = _md_heading("nested")
_NESTED_MARKUP_RAW = (
    _NEST_HEADING
    + PAD_BEFORE
    + b" "
    + _NEST_A
    + _NEST_STAR1
    + _NEST_B
    + _NEST_TICK1
    + _NEST_CODE
    + _NEST_TICK2
    + _NEST_C
    + _NEST_STAR2
    + _NEST_D
    + b" "
    + PAD_AFTER
)
_NEST_OFF = _cum(
    _NEST_HEADING,
    PAD_BEFORE,
    b" ",
    _NEST_A,
    _NEST_STAR1,
    _NEST_B,
    _NEST_TICK1,
    _NEST_CODE,
    _NEST_TICK2,
    _NEST_C,
    _NEST_STAR2,
    _NEST_D,
    b" ",
    PAD_AFTER,
)


def _nested_markup_document() -> dict[str, Any]:
    tracked = TrackedText()
    tracked.copy(PAD_BEFORE.decode(), _NEST_OFF[1], _NEST_OFF[2])
    tracked.copy(" ", _NEST_OFF[2], _NEST_OFF[3])
    tracked.copy("Note: ", _NEST_OFF[3], _NEST_OFF[4])
    tracked.copy("bold with ", _NEST_OFF[5], _NEST_OFF[6])
    tracked.copy("code", _NEST_OFF[7], _NEST_OFF[8])
    tracked.copy(" inside", _NEST_OFF[9], _NEST_OFF[10])
    tracked.copy(" end.", _NEST_OFF[11], _NEST_OFF[12])
    tracked.copy(" ", _NEST_OFF[12], _NEST_OFF[13])
    tracked.copy(PAD_AFTER.decode(), _NEST_OFF[13], _NEST_OFF[14])
    return _doc(_unit(("nested",), tracked))


# ---------------------------------------------------------------------------
# fixture 7 — link visible text vs. href target
#
# Naive failure: spanning the whole "<a ...>text</a>" element for the text
# unit, so the span covers the href URL as well as the words a reader sees.

_LINK_OPEN = b'<a href="https://example.com/policy/retention">'
_LINK_TEXT = b"the retention schedule"
_LINK_CLOSE = b"</a>"
_LINK_HEADING = _md_heading("link")
_LINK_TEXT_RAW = (
    _LINK_HEADING + PAD_BEFORE + b" " + _LINK_OPEN + _LINK_TEXT + _LINK_CLOSE + b" " + PAD_AFTER
)
_LINK_OFF = _cum(
    _LINK_HEADING, PAD_BEFORE, b" ", _LINK_OPEN, _LINK_TEXT, _LINK_CLOSE, b" ", PAD_AFTER
)


def _link_text_document() -> dict[str, Any]:
    tracked = TrackedText()
    tracked.copy(PAD_BEFORE.decode(), _LINK_OFF[1], _LINK_OFF[2])
    tracked.copy(" ", _LINK_OFF[2], _LINK_OFF[3])
    tracked.copy("the retention schedule", _LINK_OFF[4], _LINK_OFF[5])
    tracked.copy(" ", _LINK_OFF[6], _LINK_OFF[7])
    tracked.copy(PAD_AFTER.decode(), _LINK_OFF[7], _LINK_OFF[8])
    return _doc(_unit(("link",), tracked))


# ---------------------------------------------------------------------------
# fixture 8 — HTML attribute value vs. element text
#
# Naive failure: a parser that tracks "current element's raw span" rather than
# "current text node's raw span" hands the text extractor the whole tag
# including its attributes, so the text's span bleeds into the title string.

_ATTR_OPEN = b'<span title="Do not use this value">'
_ATTR_TEXT = b"Visible label"
_ATTR_CLOSE = b"</span>"
_ATTR_HEADING = _md_heading("attribute")
_ATTRIBUTE_RAW = (
    _ATTR_HEADING + PAD_BEFORE + b" " + _ATTR_OPEN + _ATTR_TEXT + _ATTR_CLOSE + b" " + PAD_AFTER
)
_ATTR_OFF = _cum(
    _ATTR_HEADING, PAD_BEFORE, b" ", _ATTR_OPEN, _ATTR_TEXT, _ATTR_CLOSE, b" ", PAD_AFTER
)


def _attribute_document() -> dict[str, Any]:
    tracked = TrackedText()
    tracked.copy(PAD_BEFORE.decode(), _ATTR_OFF[1], _ATTR_OFF[2])
    tracked.copy(" ", _ATTR_OFF[2], _ATTR_OFF[3])
    tracked.copy("Visible label", _ATTR_OFF[4], _ATTR_OFF[5])
    tracked.copy(" ", _ATTR_OFF[6], _ATTR_OFF[7])
    tracked.copy(PAD_AFTER.decode(), _ATTR_OFF[7], _ATTR_OFF[8])
    return _doc(_unit(("attribute",), tracked))


# ---------------------------------------------------------------------------
# fixture 9 — an unterminated tag: fails closed rather than guessing
#
# Naive failure: a forgiving parser recovers from the missing ">" by treating
# everything up to the next "<" as element content anyway, so "30 days</a>"
# through the mismatched close tag gets a confident, wrong span.

_MAL_BEFORE = b"<p>Retention period "
_MAL_BROKEN = b'<b class="term"'  # never closed: no ">"
_MAL_WORDS = b"30 days</a>"
_MAL_HEADING = _md_heading("malformed")
_MALFORMED_RAW = _MAL_BEFORE + _MAL_BROKEN + _MAL_WORDS
_MALFORMED_WRAPPED_RAW = _MAL_HEADING + PAD_BEFORE + b" " + _MALFORMED_RAW + b" " + PAD_AFTER


def _malformed_document() -> dict[str, Any]:
    off = _cum(
        _MAL_HEADING, PAD_BEFORE, b" ", _MAL_BEFORE, _MAL_BROKEN, _MAL_WORDS, b" ", PAD_AFTER
    )
    before_start = off[3] + len(b"<p>")
    before_end = off[3] + len(b"<p>Retention period ")
    tracked = TrackedText()
    tracked.copy(PAD_BEFORE.decode(), off[1], off[2])
    tracked.copy(" ", off[2], off[3])
    tracked.copy("Retention period ", before_start, before_end)
    #: "30 days" sits behind an unterminated tag; there is no reliable
    #: element boundary to name as its source, so it is inserted rather than
    #: attributed to bytes the parser cannot honestly point at.
    tracked.insert("30 days")
    tracked.copy(" ", off[6], off[7])
    tracked.copy(PAD_AFTER.decode(), off[7], off[8])
    return _doc(_unit(("malformed",), tracked))


# ---------------------------------------------------------------------------
# fixture 10 — content that appears TWICE in the document
#
# The single most important fixture: `raw.find(text)` always returns the
# FIRST occurrence, so a second unit whose text starts with the same phrase as
# an earlier unit gets a span pointing at the earlier unit's bytes — silently.
# Both units share the leading phrase; they differ only in their own tail, and
# that tail is exactly what a mis-attributed span would fail to contain.

_DUP_SHARED = "the retention period applies to all processed samples"
_DUP1_TAIL = " under Policy A."
_DUP2_TAIL = " under Policy B."
_DUP1_OPEN = b'<p id="p1">'
_DUP1_TEXT = (_DUP_SHARED + _DUP1_TAIL).encode("utf-8")
_DUP1_CLOSE = b"</p>"
_DUP2_OPEN = b'<p id="p2">'
_DUP2_TEXT = (_DUP_SHARED + _DUP2_TAIL).encode("utf-8")
_DUP2_CLOSE = b"</p>"
_DUP_HEADING = _md_heading("duplicate")
_DUP_SUBHEAD_FIRST = _md_heading("first", level=2)
_DUP_SUBHEAD_SECOND = _md_heading("second", level=2)
_DUPLICATE_RAW = (
    _DUP_HEADING
    + _DUP_SUBHEAD_FIRST
    + PAD_BEFORE
    + b" "
    + _DUP1_OPEN
    + _DUP1_TEXT
    + _DUP1_CLOSE
    + b" "
    + PAD_AFTER
    + b"\n\n"
    + _DUP_SUBHEAD_SECOND
    + PAD_BEFORE
    + b" "
    + _DUP2_OPEN
    + _DUP2_TEXT
    + _DUP2_CLOSE
    + b" "
    + PAD_AFTER
)
_DUP_OFF = _cum(
    _DUP_HEADING,
    _DUP_SUBHEAD_FIRST,
    PAD_BEFORE,
    b" ",
    _DUP1_OPEN,
    _DUP1_TEXT,
    _DUP1_CLOSE,
    b" ",
    PAD_AFTER,
    b"\n\n",
    _DUP_SUBHEAD_SECOND,
    PAD_BEFORE,
    b" ",
    _DUP2_OPEN,
    _DUP2_TEXT,
    _DUP2_CLOSE,
    b" ",
    PAD_AFTER,
)


def _duplicate_content_document() -> dict[str, Any]:
    first = TrackedText()
    first.copy(PAD_BEFORE.decode(), _DUP_OFF[2], _DUP_OFF[3])
    first.copy(" ", _DUP_OFF[3], _DUP_OFF[4])
    first.copy(_DUP_SHARED + _DUP1_TAIL, _DUP_OFF[5], _DUP_OFF[6])
    first.copy(" ", _DUP_OFF[7], _DUP_OFF[8])
    first.copy(PAD_AFTER.decode(), _DUP_OFF[8], _DUP_OFF[9])
    second = TrackedText()
    second.copy(PAD_BEFORE.decode(), _DUP_OFF[11], _DUP_OFF[12])
    second.copy(" ", _DUP_OFF[12], _DUP_OFF[13])
    second.copy(_DUP_SHARED + _DUP2_TAIL, _DUP_OFF[14], _DUP_OFF[15])
    second.copy(" ", _DUP_OFF[16], _DUP_OFF[17])
    second.copy(PAD_AFTER.decode(), _DUP_OFF[17], _DUP_OFF[18])
    return _doc(
        _unit(("duplicate", "first"), first, ordinal=0),
        _unit(("duplicate", "second"), second, ordinal=1),
    )


# ---------------------------------------------------------------------------
# fixture 11 — text that does NOT appear literally in the source at all
#
# The SFI1 failure shape itself. A computed/derived value that the source
# never spelled out in those bytes anywhere. Naive failure: searching
# canonical text back in raw finds nothing, and rather than reporting that
# honestly, a tolerant matcher falls back to "nearest plausible span" —
# usually the placeholder's own byte range — and reports a confident span for
# text that was never those bytes.

_DERIVED_BEFORE = b"<p>Status: "
_DERIVED_PLACEHOLDER = b"{{computed}}"
_DERIVED_CLOSE = b"</p>"
_DERIVED_HEADING = _md_heading("derived")
_TEXT_NOT_IN_SOURCE_RAW = _DERIVED_BEFORE + _DERIVED_PLACEHOLDER + _DERIVED_CLOSE
_DERIVED_WRAPPED_RAW = (
    _DERIVED_HEADING + PAD_BEFORE + b" " + _TEXT_NOT_IN_SOURCE_RAW + b" " + PAD_AFTER
)
_DERIVED_VALUE = "DERIVED-VALUE"


def _text_not_in_source_document() -> dict[str, Any]:
    off = _cum(
        _DERIVED_HEADING,
        PAD_BEFORE,
        b" ",
        _DERIVED_BEFORE,
        _DERIVED_PLACEHOLDER,
        _DERIVED_CLOSE,
        b" ",
        PAD_AFTER,
    )
    tracked = TrackedText()
    tracked.copy(PAD_BEFORE.decode(), off[1], off[2])
    tracked.copy(" ", off[2], off[3])
    tracked.copy("Status: ", off[3] + len(b"<p>"), off[4])
    #: the derived value never appeared in the raw payload in any encoding;
    #: it is computed, so it is inserted rather than falsely attributed to
    #: the placeholder's own bytes.
    tracked.insert(_DERIVED_VALUE)
    tracked.copy(" ", off[6], off[7])
    tracked.copy(PAD_AFTER.decode(), off[7], off[8])
    return _doc(_unit(("derived",), tracked))


# ---------------------------------------------------------------------------
# fixture 12 — a unit's text is a substring of an EARLIER unit's text
#
# Naive failure: re-locating a short unit's text by searching the whole raw
# payload finds the substring inside the earlier, longer unit first, because
# that occurrence comes first in the document — even though the short unit has
# its own, later, distinct occurrence.

_SUB_EARLIER_TEXT = "Retention period applies for thirty days across all regions of the policy."
_SUB_LATER_TEXT = "thirty days (section B)"
_SUB1_OPEN = b'<p id="a">'
_SUB1_TEXT = _SUB_EARLIER_TEXT.encode("utf-8")
_SUB1_CLOSE = b"</p>"
_SUB2_OPEN = b'<p id="b">'
_SUB2_TEXT = _SUB_LATER_TEXT.encode("utf-8")
_SUB2_CLOSE = b"</p>"
_SUB_HEADING = _md_heading("substring")
_SUB_SUBHEAD_EARLIER = _md_heading("earlier", level=2)
_SUB_SUBHEAD_LATER = _md_heading("later", level=2)
_SUBSTRING_RAW = (
    _SUB_HEADING
    + _SUB_SUBHEAD_EARLIER
    + PAD_BEFORE
    + b" "
    + _SUB1_OPEN
    + _SUB1_TEXT
    + _SUB1_CLOSE
    + b" "
    + PAD_AFTER
    + b"\n\n"
    + _SUB_SUBHEAD_LATER
    + PAD_BEFORE
    + b" "
    + _SUB2_OPEN
    + _SUB2_TEXT
    + _SUB2_CLOSE
    + b" "
    + PAD_AFTER
)
_SUB_OFF = _cum(
    _SUB_HEADING,
    _SUB_SUBHEAD_EARLIER,
    PAD_BEFORE,
    b" ",
    _SUB1_OPEN,
    _SUB1_TEXT,
    _SUB1_CLOSE,
    b" ",
    PAD_AFTER,
    b"\n\n",
    _SUB_SUBHEAD_LATER,
    PAD_BEFORE,
    b" ",
    _SUB2_OPEN,
    _SUB2_TEXT,
    _SUB2_CLOSE,
    b" ",
    PAD_AFTER,
)


def _substring_of_earlier_unit_document() -> dict[str, Any]:
    earlier = TrackedText()
    earlier.copy(PAD_BEFORE.decode(), _SUB_OFF[2], _SUB_OFF[3])
    earlier.copy(" ", _SUB_OFF[3], _SUB_OFF[4])
    earlier.copy(_SUB_EARLIER_TEXT, _SUB_OFF[5], _SUB_OFF[6])
    earlier.copy(" ", _SUB_OFF[7], _SUB_OFF[8])
    earlier.copy(PAD_AFTER.decode(), _SUB_OFF[8], _SUB_OFF[9])
    later = TrackedText()
    later.copy(PAD_BEFORE.decode(), _SUB_OFF[11], _SUB_OFF[12])
    later.copy(" ", _SUB_OFF[12], _SUB_OFF[13])
    later.copy(_SUB_LATER_TEXT, _SUB_OFF[14], _SUB_OFF[15])
    later.copy(" ", _SUB_OFF[16], _SUB_OFF[17])
    later.copy(PAD_AFTER.decode(), _SUB_OFF[17], _SUB_OFF[18])
    return _doc(
        _unit(("substring", "earlier"), earlier, ordinal=0),
        _unit(("substring", "later"), later, ordinal=1),
    )


# ---------------------------------------------------------------------------
# the corpus

FIXTURES: tuple[Fixture, ...] = (
    Fixture(
        fixture_id="prov-001-entity-decoding",
        fixture_class=ENTITY_DECODING,
        raw=_ENTITY_RAW,
        requirement=(
            "The named entity &eacute; decodes to é; its span must cover exactly the "
            "entity bytes, not a neighbouring word."
        ),
        expectation=SpanCoversBytes(
            ("meeting",),
            within=WithinText("é"),
            must_contain=b"&eacute;",
            must_not_contain=b"Meeting",
        ),
        naive_failure=(
            "computing the span from the decoded character's offset and reusing it as a raw "
            "byte offset (1 decoded char = 1 raw byte) lands inside 'caf' or 'today', never on "
            "the eight bytes of &eacute; itself"
        ),
        reference_document=_entity_decoding_document,
        padding=(PAD_BEFORE, PAD_AFTER),
    ),
    Fixture(
        fixture_id="prov-002-whitespace-normalization",
        fixture_class=WHITESPACE_NORMALIZATION,
        raw=_WHITESPACE_RAW,
        requirement=(
            "A newline/tab run collapsed to one space must have that space's span cover the "
            "whole run, not a substring of it or the words on either side."
        ),
        expectation=SpanCoversBytes(
            ("retention",),
            within=WithinGap(before="Retention", after="is thirty days."),
            must_contain=b"\n\t",
            must_not_contain=b"Retention",
        ),
        naive_failure=(
            "collapsing '\\n\\t ' to a single space in the output buffer while still walking "
            "the raw string with a plain index cursor drifts by however many bytes were "
            "collapsed away; every span after the first run is off by that amount"
        ),
        reference_document=_whitespace_document,
        padding=(PAD_BEFORE, PAD_AFTER),
    ),
    Fixture(
        fixture_id="prov-003-markup-stripping",
        fixture_class=MARKUP_STRIPPING,
        raw=_MARKUP_RAW,
        requirement="**bold** strips to 'bold'; the word's span must not cover the asterisks.",
        expectation=SpanCoversBytes(
            ("markup",),
            within=WithinText("bold"),
            must_contain=b"bold",
            must_not_contain=b"*",
        ),
        naive_failure=(
            "spanning 'the whole **bold** run' because that is the construct the parser "
            "recognised includes two asterisks that produced no output character at all"
        ),
        reference_document=_markup_stripping_document,
        padding=(PAD_BEFORE, PAD_AFTER),
    ),
    Fixture(
        fixture_id="prov-004-block-composition-join",
        fixture_class=BLOCK_COMPOSITION_JOIN,
        raw=_BLOCK_JOIN_RAW,
        requirement=(
            "Two blocks joined into one unit's text share a separator that came from nowhere; "
            "that separator's span must be absent and the unit must not be reported fully "
            "sourced."
        ),
        expectation=AllOf(
            (
                SpanAbsent(("joined",), within=WithinGap(before="here.", after="Second")),
                NotFullySourced(
                    ("joined",), why="the join separator between the two blocks has no source"
                ),
            )
        ),
        naive_failure=(
            "spanning 'start of block one' to 'end of block two' for the whole unit silently "
            "claims the inserted separator has a source too, which is the untraceable "
            "character the ruling exists to forbid"
        ),
        reference_document=_block_composition_document,
        source_family="sec_edgar",
        padding=(PAD_BEFORE, PAD_AFTER),
    ),
    Fixture(
        fixture_id="prov-005-utf8-multibyte",
        fixture_class=MULTIBYTE_UTF8,
        raw=_MULTIBYTE_RAW,
        requirement=(
            "Four CJK characters occupy 12 UTF-8 bytes; the span for them must be byte-sized, "
            "not character-counted, or it bleeds into the ASCII text on either side."
        ),
        expectation=SpanCoversBytes(
            ("warranty",),
            within=WithinText(_MB_CJK),
            must_contain=_MB_CJK.encode("utf-8"),
            must_not_contain=b"Warranty",
        ),
        naive_failure=(
            "using Python string length (a character count) as a byte offset: each CJK "
            "character is 3 bytes, so a char-counted span lands a third of the way into the "
            "intended region and reads ASCII neighbour bytes instead"
        ),
        reference_document=_multibyte_document,
        padding=(PAD_BEFORE, PAD_AFTER),
    ),
    Fixture(
        fixture_id="prov-006-nested-markup",
        fixture_class=NESTED_MARKUP,
        raw=_NESTED_MARKUP_RAW,
        requirement=(
            "`code` nested inside **bold ... ** must have its own span cover exactly 'code', "
            "not the backticks and not the surrounding bold text."
        ),
        expectation=SpanCoversBytes(
            ("nested",),
            within=WithinText("code"),
            must_contain=b"code",
            must_not_contain=b"`",
        ),
        naive_failure=(
            "a delimiter-matching stack that pops on the inner backtick pair before the outer "
            "bold run is done loses track of where 'code' actually ends, so its span walks "
            "past its own backticks into the surrounding bold text"
        ),
        reference_document=_nested_markup_document,
        padding=(PAD_BEFORE, PAD_AFTER),
    ),
    Fixture(
        fixture_id="prov-007-link-text-vs-target",
        fixture_class=LINK_TEXT_VS_TARGET,
        raw=_LINK_TEXT_RAW,
        requirement="A link's visible text span must not cover its href target.",
        expectation=SpanCoversBytes(
            ("link",),
            within=WithinText("the retention schedule"),
            must_contain=b"the retention schedule",
            must_not_contain=b"https://example.com/policy/retention",
        ),
        naive_failure=(
            "spanning the whole <a href=...>text</a> element for the text unit, so the span "
            "covers the URL as well as the words a reader actually sees"
        ),
        reference_document=_link_text_document,
        padding=(PAD_BEFORE, PAD_AFTER),
    ),
    Fixture(
        fixture_id="prov-008-attribute-vs-element-text",
        fixture_class=ATTRIBUTE_VS_TEXT,
        raw=_ATTRIBUTE_RAW,
        requirement="An element's text span must not bleed into one of its own attribute values.",
        expectation=SpanCoversBytes(
            ("attribute",),
            within=WithinText("Visible label"),
            must_contain=b"Visible label",
            must_not_contain=b"Do not use this value",
        ),
        naive_failure=(
            "tracking 'current element's raw span' instead of 'current text node's raw span' "
            "hands the text extractor the whole tag including its attributes, so the text's "
            "span covers the title string too"
        ),
        reference_document=_attribute_document,
        padding=(PAD_BEFORE, PAD_AFTER),
    ),
    Fixture(
        fixture_id="prov-009-malformed-tag-fails-closed",
        fixture_class=MALFORMED_TAG_FAIL_CLOSED,
        raw=_MALFORMED_WRAPPED_RAW,
        requirement=(
            "An unterminated <b tag with a mismatched closing </a> leaves '30 days' with no "
            "decidable element boundary; its span must be absent, not a confident guess."
        ),
        expectation=AllOf(
            (
                SpanAbsent(("malformed",), within=WithinText("30 days")),
                NotFullySourced(
                    ("malformed",),
                    why="'30 days' sits behind an unterminated tag with no safe boundary",
                ),
            )
        ),
        naive_failure=(
            "a forgiving parser recovers from the missing '>' by treating everything up to the "
            "next '<' as element content anyway, so '30 days' through the mismatched close tag "
            "gets a confident, wrong span instead of an honest absence"
        ),
        reference_document=_malformed_document,
        padding=(PAD_BEFORE, PAD_AFTER),
    ),
    Fixture(
        fixture_id="prov-010-duplicate-content-second-occurrence",
        fixture_class=DUPLICATE_CONTENT,
        raw=_DUPLICATE_RAW,
        requirement=(
            "Two units share an identical leading phrase but differ in their own tail; the "
            "second unit's span must point at its OWN bytes (containing its own tail), not the "
            "first occurrence's."
        ),
        expectation=SpanCoversBytes(
            ("duplicate", "second"),
            within=WithinText("Policy B"),
            must_contain=b"Policy B",
            must_not_contain=b"Policy A",
        ),
        naive_failure=(
            "raw.find(text) always returns the FIRST occurrence; re-locating the second unit's "
            "span by searching for its shared leading phrase silently gives it the first unit's "
            "byte range, so the second unit's provenance points at the first unit's bytes"
        ),
        reference_document=_duplicate_content_document,
        padding=(PAD_BEFORE, PAD_AFTER),
    ),
    Fixture(
        fixture_id="prov-011-text-not-in-source",
        fixture_class=TEXT_NOT_IN_SOURCE,
        raw=_DERIVED_WRAPPED_RAW,
        requirement=(
            "A computed value that never appears literally in the source, in any encoding, "
            "must have no source span at all — not the placeholder's own bytes, not a nearby "
            "guess."
        ),
        expectation=AllOf(
            (
                SpanAbsent(("derived",), within=WithinText(_DERIVED_VALUE)),
                NotFullySourced(
                    ("derived",), why="the value is computed, not read from the source"
                ),
            )
        ),
        naive_failure=(
            "the SFI1 failure shape itself: searching canonical text back inside raw bytes "
            "finds nothing for a computed value, and a tolerant matcher falls back to the "
            "placeholder's own byte range rather than reporting the honest absence"
        ),
        reference_document=_text_not_in_source_document,
        padding=(PAD_BEFORE, PAD_AFTER),
    ),
    Fixture(
        fixture_id="prov-012-substring-of-earlier-unit",
        fixture_class=SUBSTRING_OF_EARLIER_UNIT,
        raw=_SUBSTRING_RAW,
        requirement=(
            "A later, short unit's text ('thirty days (section B)') is a substring of an "
            "earlier, longer unit's text; the later unit's span must point at its own later "
            "occurrence, not the earlier unit's."
        ),
        expectation=SpanCoversBytes(
            ("substring", "later"),
            within=WithinText("(section B)"),
            must_contain=b"(section B)",
            must_not_contain=b"across all",
        ),
        naive_failure=(
            "re-locating the short unit's text by searching the whole raw payload finds the "
            "substring inside the earlier, longer unit first, because that occurrence comes "
            "first in the document, even though the short unit has its own later occurrence"
        ),
        reference_document=_substring_of_earlier_unit_document,
        padding=(PAD_BEFORE, PAD_AFTER),
    ),
)


BY_ID: dict[str, Fixture] = {f.fixture_id: f for f in FIXTURES}


# ---------------------------------------------------------------------------
# the checker
#
# Two layers. ``check`` judges a document that already exists — the
# unconditional half of the suite calls it with each fixture's own
# ``reference_document()``. ``check_through_canonicaliser`` is the layer that
# exercises the real pipeline; it imports the real canonicaliser defensively,
# at call time, and reports NOT_EXERCISED (never PASS) only when that module is
# genuinely absent or genuinely exposes no entrypoint this corpus can call.


def check(fixture: Fixture, document: dict[str, Any]) -> Outcome:
    """Evaluate one fixture's declared expectation against a document that exists.

    Never itself decides NOT_EXERCISED: a caller that already has a document
    ran something to get it, so the only questions left are PASS or FAIL.
    """
    held, reason, detail = fixture.expectation.evaluate(document, raw=fixture.raw)
    detail = dict(detail)
    detail["expectation"] = fixture.expectation.describe()
    return Outcome(fixture.fixture_id, PASS if held else FAIL, reason, detail)


#: The real canonicaliser this corpus runs against. Named here, once, so the
#: defensive import has exactly one place to look and this module's own tests
#: can assert the loader's behaviour without hard-depending on the module.
CANONICALISER_MODULE = "canonicalization.provenance_document"
#: Candidate entrypoint names, tried in order.
CANONICALISER_ENTRYPOINTS: tuple[str, ...] = (
    "build_document",
    "provenance_document",
    "canonicalize",
)
#: The keyword contract this corpus supplies to a matching entrypoint.
#: ``provenance_document``'s own signature, reproduced here as the corpus's
#: stated expectation of the integration contract — see
#: ``_fixture_metadata_kwargs`` for what each fixture actually passes.
CANONICALISER_METADATA_KEYS: tuple[str, ...] = (
    "source_family",
    "source_id",
    "version_id",
    "payload",
    "source_digest",
    "known_at",
    "valid_from",
    "licence",
)

#: Founder ruling, 2026-08-23: these two fields are the only ones that WOULD be
#: a fabricated provenance claim if invented, so they stay None rather than
#: guessed. ``licence`` is calling context, not a claim about the fixture, and
#: is declared plainly rather than hidden inside a helper.
FIXTURE_METADATA: dict[str, Any] = {
    "known_at": None,
    "valid_from": None,
    "licence": "internal-test-fixture",
}


def _fixture_metadata_kwargs(fixture: Fixture) -> dict[str, Any]:
    """The full keyword call this corpus makes for one fixture.

    ``source_digest`` is computed from the fixture's own raw bytes, never a
    literal — the one field among these that WOULD be dishonest if hand-typed,
    since it is supposed to describe those exact bytes.
    """
    return {
        "source_family": fixture.source_family,
        "source_id": fixture.fixture_id,
        "version_id": "v1",
        "payload": fixture.raw,
        "source_digest": "sha256:" + hashlib.sha256(fixture.raw).hexdigest(),
        "known_at": FIXTURE_METADATA["known_at"],
        "valid_from": FIXTURE_METADATA["valid_from"],
        "licence": FIXTURE_METADATA["licence"],
    }


def _accepts_metadata_kwargs(entrypoint: Callable[..., Any], sample: dict[str, Any]) -> bool:
    """True when ``entrypoint`` can be called as ``entrypoint(**sample)``.

    Only parameter NAMES and KINDS are checked (``Signature.bind`` does not
    evaluate the values), so a placeholder sample is enough to test whether
    the shapes match without running anything.
    """
    try:
        inspect.signature(entrypoint).bind(**sample)
    except TypeError:
        return False
    return True


def _load_canonicaliser() -> tuple[Callable[..., dict[str, Any]] | None, str | None]:
    try:
        module = importlib.import_module(CANONICALISER_MODULE)
    except ImportError as error:
        return None, (
            f"{CANONICALISER_MODULE} is not importable ({error}); nothing has been built yet"
        )
    present = [name for name in CANONICALISER_ENTRYPOINTS if callable(getattr(module, name, None))]
    sample = dict.fromkeys(CANONICALISER_METADATA_KEYS)
    for name in present:
        entrypoint = getattr(module, name)
        if _accepts_metadata_kwargs(entrypoint, sample):
            return entrypoint, None
    if present:
        return None, (
            f"{CANONICALISER_MODULE} exposes {present}, but none accepts this corpus's "
            f"metadata-call contract {CANONICALISER_METADATA_KEYS} — the integration contract "
            "between provenance_fixtures and provenance_document has not been agreed"
        )
    return None, (
        f"{CANONICALISER_MODULE} is importable but exposes none of {CANONICALISER_ENTRYPOINTS}; "
        "the integration contract has not been agreed"
    )


def check_through_canonicaliser(fixture: Fixture) -> Outcome:
    """Run one fixture through the real canonicaliser, or report why it could not."""
    entrypoint, reason = _load_canonicaliser()
    if entrypoint is None:
        return Outcome(
            fixture.fixture_id,
            NOT_EXERCISED,
            reason or "no canonicaliser entrypoint was found",
            {"module": CANONICALISER_MODULE},
        )
    try:
        document = entrypoint(**_fixture_metadata_kwargs(fixture))
    except Exception as error:  # a canonicaliser that crashes is a failed fixture, not a skip
        return Outcome(
            fixture.fixture_id,
            FAIL,
            f"canonicaliser raised {type(error).__name__}: {error}",
            {"expectation": fixture.expectation.describe()},
        )
    return check(fixture, document)


def check_all(*, fixtures: Iterable[Fixture] = FIXTURES) -> dict[str, Any]:
    """Run the corpus through the real canonicaliser and summarise honestly.

    ``not_exercised`` is reported beside ``passed`` and never folded into it —
    a summary reporting N/N green when none of them actually ran is the
    report this programme exists to stop producing.
    """
    from collections import Counter

    outcomes = [check_through_canonicaliser(fixture) for fixture in fixtures]
    by_status = Counter(outcome.status for outcome in outcomes)
    return {
        "schema": SCHEMA,
        "outcomes": [outcome.as_dict() for outcome in outcomes],
        "total": len(outcomes),
        "passed": by_status[PASS],
        "failed": by_status[FAIL],
        "not_exercised": by_status[NOT_EXERCISED],
        "all_exercised_and_passed": by_status[PASS] == len(outcomes) and len(outcomes) > 0,
        "failing": [o.fixture_id for o in outcomes if o.status == FAIL],
        "unexercised": [o.fixture_id for o in outcomes if o.status == NOT_EXERCISED],
    }


def inventory() -> list[dict[str, Any]]:
    """The corpus as data, for a receipt."""
    return [fixture.as_dict() for fixture in FIXTURES]


if __name__ == "__main__":
    import json

    print(json.dumps({"schema": SCHEMA, "fixtures": inventory()}, indent=2, ensure_ascii=False))
