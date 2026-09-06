"""Adversarial fixture corpus for SOURCE_FACT_IR_V1, and the checker that runs it.

Founder mandate, 2026-08-23: development/adversarial fixtures must cover at least
ten named classes, and the unsupported and ambiguous cases must FAIL CLOSED
rather than disappear. The classes are in ``CLASSES`` and every one of them has
at least one fixture; ``test_sfi_adversarial.py`` asserts that coverage rather
than trusting this docstring.

Two design decisions carry the whole file, and both exist because of how the
predecessor corpus failed.

**Expectations are properties, not golden strings.** A fixture that asserts an
exact serialized output is a change-detector: it goes red when a representation
is improved and stays green when a representation is wrong in a way the author
already baked into the golden file. So an expectation here is written in the
IR's own vocabulary — "at least one fact of kind REFERENCE_TARGET must differ",
"no fact may differ", "at least one fact must be UNRESOLVED with a reason" — and
is evaluated against whatever the registered extractors actually produce.

**An unexercised fixture is never a pass.** ``check`` returns a three-valued
:class:`Outcome`, and ``NOT_EXERCISED`` is a distinct status carrying a reason.
The failure this corpus exists to prevent is a fixture that goes green because
nothing ran — that is precisely how 63,196 constructs were counted as MODELED
while the compiled state carried nothing for them.

The module deliberately imports nothing but ``ir``. The orchestrator wires it to
the real extractors at integration time by passing their output in; keeping the
corpus extractor-independent is what lets it judge an extractor rather than
agree with one.
"""

from __future__ import annotations

import sys
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

#: Package-qualified, matching metadata.py / reference.py / fingerprint.py.
#: It matters: importing this module's ``ir`` under a second name would give the
#: corpus a second ``_REGISTRY`` and a second ``SourceFact`` class, and it would
#: then judge an extractor set that nobody actually ran.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from source_fact_ir import ir

SCHEMA = "tavonel.v2.source_fact_ir.adversarial_fixtures.v1"


# ---------------------------------------------------------------------------
# fixture classes
#
# The ten the ruling names, plus the three encoding/decidability splits that
# turned up while writing them. A class is a string rather than an enum so a
# receipt can carry it without an import.

VISIBLE_TEXT_UNCHANGED_HREF_CHANGED = "VISIBLE_TEXT_UNCHANGED_HREF_CHANGED"
REFERENCE_DEFINITION_OUT_OF_SPAN = "REFERENCE_DEFINITION_OUT_OF_SPAN"
INCLUDE_TARGET_CHANGED = "INCLUDE_TARGET_CHANGED"
LANGUAGE_METADATA_CHANGED = "LANGUAGE_METADATA_CHANGED"
ACCESSIBILITY_APPLICABILITY_CHANGED = "ACCESSIBILITY_APPLICABILITY_CHANGED"
EFFECTIVE_DATE_CHANGED = "EFFECTIVE_DATE_CHANGED"
MARKUP_ONLY_EQUIVALENCE = "MARKUP_ONLY_EQUIVALENCE"
ENTITY_NORMALIZATION = "ENTITY_NORMALIZATION"
MALFORMED_OR_AMBIGUOUS_LOCATION = "MALFORMED_OR_AMBIGUOUS_LOCATION"
UNSUPPORTED_CONSTRUCT = "UNSUPPORTED_CONSTRUCT"
REFERENCE_TARGET_ENCODING = "REFERENCE_TARGET_ENCODING"
AMBIGUOUS_VS_DECIDABLE_DATE = "AMBIGUOUS_VS_DECIDABLE_DATE"
RECOGNIZED_BUT_UNREPRESENTABLE = "RECOGNIZED_BUT_UNREPRESENTABLE"

#: The ten the founder mandated, in the order they were mandated. Coverage is
#: asserted against this tuple, not against ``CLASSES``, so adding an extra
#: class can never dilute the mandate.
MANDATED_CLASSES: tuple[str, ...] = (
    VISIBLE_TEXT_UNCHANGED_HREF_CHANGED,
    REFERENCE_DEFINITION_OUT_OF_SPAN,
    INCLUDE_TARGET_CHANGED,
    LANGUAGE_METADATA_CHANGED,
    ACCESSIBILITY_APPLICABILITY_CHANGED,
    EFFECTIVE_DATE_CHANGED,
    MARKUP_ONLY_EQUIVALENCE,
    ENTITY_NORMALIZATION,
    MALFORMED_OR_AMBIGUOUS_LOCATION,
    UNSUPPORTED_CONSTRUCT,
)

CLASSES: tuple[str, ...] = (
    *MANDATED_CLASSES,
    REFERENCE_TARGET_ENCODING,
    AMBIGUOUS_VS_DECIDABLE_DATE,
    RECOGNIZED_BUT_UNREPRESENTABLE,
)


# ---------------------------------------------------------------------------
# outcomes

PASS = "PASS"  # noqa: S105 - an outcome status, not a credential
FAIL = "FAIL"
NOT_EXERCISED = "NOT_EXERCISED"

STATUSES: tuple[str, ...] = (PASS, FAIL, NOT_EXERCISED)


@dataclass(frozen=True)
class Outcome:
    """What running one fixture against one extractor set established.

    Three values, not two. ``NOT_EXERCISED`` is the honest answer when no
    extractor claims the kinds a fixture is about, and it is deliberately not
    ``PASS``: a corpus whose green count includes fixtures nobody ran reports
    coverage it does not have.
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
                f"outcome {self.status} for {self.fixture_id!r} with no reason. A verdict nobody "
                "can act on is not a verdict."
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
# comparing facts
#
# Identity for comparison is NOT ``fact_id``. ``fact_id`` folds in
# ``byte_start``, which is correct for the compiled state and useless here: the
# markup-equivalence and entity-normalization fixtures move every byte offset in
# the document while changing nothing that means anything. Comparing on
# ``fact_id`` would report a delta for exactly the two classes whose whole point
# is that there is no delta.


def fact_value(fact: ir.SourceFact) -> str:
    """Position-independent value of a fact, as one canonical string.

    ``reason`` is excluded on purpose: rewording an UNRESOLVED reason is an
    improvement to a message, not a change to what the source says. ``policy_ref``
    is included, because a fact moving between two predeclared policies is a real
    change in what was declined.
    """
    return ir.canonical_json(
        {
            "kind": fact.kind,
            "construct": fact.witness.construct,
            "unit_path": list(fact.witness.unit_path)
            if fact.witness.unit_path is not None
            else None,
            "state": fact.state,
            "representation": fact.representation,
            "policy_ref": fact.policy_ref,
        }
    )


def _bag(facts: tuple[ir.SourceFact, ...], kinds: frozenset[str]) -> Counter[str]:
    """Multiset of fact values, optionally restricted to some kinds."""
    return Counter(fact_value(f) for f in facts if not kinds or f.kind in kinds)


def _kinds_present(facts: tuple[ir.SourceFact, ...]) -> frozenset[str]:
    return frozenset(f.kind for f in facts)


# ---------------------------------------------------------------------------
# expectations
#
# Each one answers two questions: which fact kinds must exist for it to have
# been exercised at all, and — given both sides — did the property hold.


@runtime_checkable
class Expectation(Protocol):
    def relevant_kinds(self) -> frozenset[str]:
        """Kinds that must be produced by someone, or the fixture is NOT_EXERCISED."""

    def describe(self) -> str:
        """One line, in the IR's vocabulary, of what must be true."""

    def evaluate(
        self,
        before: tuple[ir.SourceFact, ...],
        after: tuple[ir.SourceFact, ...],
        *,
        before_raw: bytes = b"",
        after_raw: bytes = b"",
    ) -> tuple[bool, str, dict[str, Any]]:
        """(held, reason, detail). Never raises for ordinary disagreement."""


@dataclass(frozen=True)
class ChangedIn:
    """At least one fact of one of ``kinds`` must differ between before and after.

    The workhorse for every "the visible text did not move but the meaning did"
    class. A system that models a document as text alone cannot satisfy this,
    which is the point.
    """

    kinds: tuple[str, ...]

    def __post_init__(self) -> None:
        _reject_unknown_kinds(self.kinds)
        if not self.kinds:
            raise ValueError("ChangedIn with no kinds cannot say what must change")

    def relevant_kinds(self) -> frozenset[str]:
        return frozenset(self.kinds)

    def describe(self) -> str:
        return f"at least one fact of kind {{{', '.join(sorted(self.kinds))}}} must change"

    def evaluate(
        self,
        before: tuple[ir.SourceFact, ...],
        after: tuple[ir.SourceFact, ...],
        *,
        before_raw: bytes = b"",
        after_raw: bytes = b"",
    ) -> tuple[bool, str, dict[str, Any]]:
        kinds = self.relevant_kinds()
        left, right = _bag(before, kinds), _bag(after, kinds)
        detail = {"before_count": sum(left.values()), "after_count": sum(right.values())}
        if left == right:
            named = ", ".join(sorted(self.kinds))
            #: Two very different defects reach this branch and the reason must
            #: separate them. Zero facts means an extractor claims the kind and
            #: emitted nothing for a document that contains the construct — a
            #: silent drop, or a registry the run never actually wired up. Facts
            #: present but identical means the extractor looked and represented
            #: the change away. Both are failures; they are not the same bug, and
            #: a reader who cannot tell them apart will fix the wrong one.
            if not left and not right:
                return (
                    False,
                    f"no fact of kind {{{named}}} was produced for either revision, though the "
                    "kind is claimed; the construct is silently absent rather than represented",
                    detail,
                )
            return (
                False,
                f"no fact of kind {{{named}}} differs between the two "
                "revisions; the change is invisible to the compiled state",
                detail,
            )
        detail["added"] = sorted((right - left).elements())
        detail["removed"] = sorted((left - right).elements())
        return True, "a fact of the required kind differs between the two revisions", detail


@dataclass(frozen=True)
class Unchanged:
    """No fact may differ. For the classes where a naive system invents a delta.

    ``except_kinds`` defaults to PROVENANCE_SPAN because a provenance span is a
    statement about *where* a fact was seen, and rewriting ``<b>`` as ``<strong>``
    genuinely moves every byte after it. Asserting byte-identity there would make
    the fixture unsatisfiable for a correct system, which is a worse failure than
    not asserting it: an unsatisfiable fixture gets deleted.
    """

    except_kinds: tuple[str, ...] = (ir.PROVENANCE_SPAN,)

    def __post_init__(self) -> None:
        _reject_unknown_kinds(self.except_kinds)

    def relevant_kinds(self) -> frozenset[str]:
        #: Nothing specific is required — but ``check`` still refuses to call this
        #: a pass when both sides are empty. See ``check``.
        return frozenset()

    def describe(self) -> str:
        skipped = ", ".join(sorted(self.except_kinds)) or "nothing"
        return f"no fact may change (excluding kinds: {skipped})"

    def evaluate(
        self,
        before: tuple[ir.SourceFact, ...],
        after: tuple[ir.SourceFact, ...],
        *,
        before_raw: bytes = b"",
        after_raw: bytes = b"",
    ) -> tuple[bool, str, dict[str, Any]]:
        skip = frozenset(self.except_kinds)
        left = Counter(fact_value(f) for f in before if f.kind not in skip)
        right = Counter(fact_value(f) for f in after if f.kind not in skip)
        if left == right:
            return True, "no fact differs, as required", {"compared": sum(left.values())}
        return (
            False,
            "a fact changed where the two revisions are semantically identical; this is a false "
            "delta and it will cause a spurious recompilation",
            {
                "added": sorted((right - left).elements()),
                "removed": sorted((left - right).elements()),
            },
        )


@dataclass(frozen=True)
class MustBeInState:
    """At least one fact must be in ``state``, and (by default) name a reason.

    The fail-closed half of the corpus. ``kinds`` empty means any kind will do —
    correct for a malformed document, where which extractor notices the damage
    is not something the fixture should dictate.
    """

    state: str
    kinds: tuple[str, ...] = ()
    require_reason: bool = True
    #: Both revisions carry the defect in every fixture that uses this, so both
    #: are required. A checker that accepted one side would pass a system that
    #: resolved the ambiguity by guessing on the revision it happened to see second.
    sides: tuple[str, ...] = ("before", "after")

    def __post_init__(self) -> None:
        if self.state not in ir.STATES:
            raise ValueError(f"unknown state {self.state!r}")
        _reject_unknown_kinds(self.kinds)
        for side in self.sides:
            if side not in ("before", "after"):
                raise ValueError(f"unknown side {side!r}")

    def relevant_kinds(self) -> frozenset[str]:
        return frozenset(self.kinds)

    def describe(self) -> str:
        where = f" of kind {{{', '.join(sorted(self.kinds))}}}" if self.kinds else ""
        tail = " with a reason" if self.require_reason else ""
        return f"at least one fact{where} must be in state {self.state}{tail}"

    def _matches(self, facts: tuple[ir.SourceFact, ...]) -> list[ir.SourceFact]:
        kinds = self.relevant_kinds()
        return [
            f
            for f in facts
            if f.state == self.state
            and (not kinds or f.kind in kinds)
            and (not self.require_reason or bool(f.reason))
        ]

    def evaluate(
        self,
        before: tuple[ir.SourceFact, ...],
        after: tuple[ir.SourceFact, ...],
        *,
        before_raw: bytes = b"",
        after_raw: bytes = b"",
    ) -> tuple[bool, str, dict[str, Any]]:
        found = {"before": self._matches(before), "after": self._matches(after)}
        detail = {side: [f.reason for f in facts] for side, facts in found.items()}
        empty = [side for side in self.sides if not found[side]]
        if empty:
            return (
                False,
                f"no fact in state {self.state} on side(s) {', '.join(empty)}; the construct was "
                "resolved when it is not decidable, or dropped without being counted",
                detail,
            )
        return True, f"both required sides carry a {self.state} fact", detail


@dataclass(frozen=True)
class MustFailClosed:
    """At least one fact must be in a fail-closed state (UNREPRESENTED or UNRESOLVED).

    Weaker than :class:`MustBeInState` and deliberately so: for an unsupported
    construct the corpus must not dictate *which* honest refusal an extractor
    makes, only that it makes one. What it forbids is the third option — calling
    it REPRESENTED, or emitting nothing.
    """

    kinds: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _reject_unknown_kinds(self.kinds)

    def relevant_kinds(self) -> frozenset[str]:
        return frozenset(self.kinds)

    def describe(self) -> str:
        where = f" of kind {{{', '.join(sorted(self.kinds))}}}" if self.kinds else ""
        return f"at least one fact{where} must be fail-closed ({'/'.join(sorted(ir.FAIL_CLOSED))})"

    def evaluate(
        self,
        before: tuple[ir.SourceFact, ...],
        after: tuple[ir.SourceFact, ...],
        *,
        before_raw: bytes = b"",
        after_raw: bytes = b"",
    ) -> tuple[bool, str, dict[str, Any]]:
        kinds = self.relevant_kinds()
        hits = [
            f for f in before + after if f.fail_closed and (not kinds or f.kind in kinds)
        ]
        detail = {"fail_closed": [f"{f.kind}:{f.state}" for f in hits]}
        if not hits:
            return (
                False,
                "nothing is fail-closed; a construct the compiled state cannot carry was either "
                "declared REPRESENTED or silently dropped",
                detail,
            )
        return True, "the construct is refused honestly rather than absorbed", detail


@dataclass(frozen=True)
class NoSilentAbsence:
    """Every named region of the source must be witnessed by a fact in SOME state.

    The direct expression of the ruling: a construct that produces no fact at
    all is indistinguishable from one that was never in the source. State is not
    constrained — UNRESOLVED is a fine answer, silence is not.

    Regions are named by a literal byte snippet of the fixture's own source, not
    by a construct label. Construct labels are lane-owned vocabulary: the
    reference lane writes ``html-a-href`` where a fixture author would guess
    ``a``, and a corpus that guesses wrong reports silence where there is none.
    A byte offset is a property of the source, so both sides of the integration
    can be checked against it without agreeing on names first.

    "Witnessed" means a fact's witness span overlaps the snippet's span. A
    zero-length witness at the snippet's start counts: an extractor is entitled
    to point at a position rather than a range.
    """

    snippets: tuple[bytes, ...]

    def __post_init__(self) -> None:
        if not self.snippets:
            raise ValueError("NoSilentAbsence with no snippets constrains nothing")
        if not all(isinstance(s, bytes) and s for s in self.snippets):
            raise ValueError("NoSilentAbsence snippets must be non-empty byte literals")

    def relevant_kinds(self) -> frozenset[str]:
        return frozenset()

    def describe(self) -> str:
        shown = ", ".join(sorted(s.decode("utf-8", "replace") for s in self.snippets))
        return f"no construct may be silently absent: {{{shown}}} must each produce a fact"

    @staticmethod
    def _witnessed(facts: tuple[ir.SourceFact, ...], start: int, end: int) -> bool:
        for fact in facts:
            w = fact.witness
            if w.byte_start < end and start <= w.byte_end:
                return True
        return False

    def evaluate(
        self,
        before: tuple[ir.SourceFact, ...],
        after: tuple[ir.SourceFact, ...],
        *,
        before_raw: bytes = b"",
        after_raw: bytes = b"",
    ) -> tuple[bool, str, dict[str, Any]]:
        missing: dict[str, list[str]] = {}
        for side, facts, raw in (("before", before, before_raw), ("after", after, after_raw)):
            gone: list[str] = []
            for snippet in self.snippets:
                start = raw.find(snippet)
                if start < 0:
                    #: The fixture names a region its own source does not contain.
                    #: Fixture.__post_init__ refuses this, so reaching it means the
                    #: expectation was built by hand against the wrong bytes.
                    gone.append(f"{snippet.decode('utf-8', 'replace')} (not in this revision)")
                elif not self._witnessed(facts, start, start + len(snippet)):
                    gone.append(snippet.decode("utf-8", "replace"))
            if gone:
                missing[side] = gone
        if missing:
            return (
                False,
                f"region(s) present in the source produced no fact at all: {missing}; a "
                "construct that produces nothing cannot be counted and cannot be reported",
                {"missing": missing},
            )
        return (
            True,
            "every named region is witnessed by a fact",
            {"snippets": [s.decode("utf-8", "replace") for s in self.snippets]},
        )


@dataclass(frozen=True)
class AllOf:
    """Every part must hold. Fails on the first part that does not, naming it."""

    parts: tuple[Expectation, ...]

    def __post_init__(self) -> None:
        if len(self.parts) < 2:
            raise ValueError("AllOf with fewer than two parts is just the part")

    def relevant_kinds(self) -> frozenset[str]:
        return frozenset().union(*(p.relevant_kinds() for p in self.parts))

    def describe(self) -> str:
        return " AND ".join(p.describe() for p in self.parts)

    def evaluate(
        self,
        before: tuple[ir.SourceFact, ...],
        after: tuple[ir.SourceFact, ...],
        *,
        before_raw: bytes = b"",
        after_raw: bytes = b"",
    ) -> tuple[bool, str, dict[str, Any]]:
        detail: dict[str, Any] = {}
        for index, part in enumerate(self.parts):
            held, reason, part_detail = part.evaluate(
                before, after, before_raw=before_raw, after_raw=after_raw
            )
            detail[f"part_{index}"] = {"held": held, "reason": reason, "detail": part_detail}
            if not held:
                return False, f"part {index} ({type(part).__name__}) failed: {reason}", detail
        return True, "every part held", detail


def _snippets_of(expectation: Expectation) -> tuple[bytes, ...]:
    """Every byte snippet an expectation (or any part of it) requires a fact for."""
    if isinstance(expectation, NoSilentAbsence):
        return expectation.snippets
    if isinstance(expectation, AllOf):
        return tuple(s for part in expectation.parts for s in _snippets_of(part))
    return ()


def _reject_unknown_kinds(kinds: tuple[str, ...]) -> None:
    unknown = sorted(set(kinds) - set(ir.KIND_CHANNEL))
    if unknown:
        raise ValueError(f"expectation names unknown fact kind(s) {unknown}")


# ---------------------------------------------------------------------------
# the fixture record


@dataclass(frozen=True)
class Fixture:
    """One adversarial pair, frozen, with its expectation declared as a property.

    ``before``/``after`` are raw bytes, never str: a witness carries byte offsets
    into the raw payload, and a fixture that hands an extractor a decoded string
    cannot exercise the encoding classes at all.
    """

    fixture_id: str
    fixture_class: str
    before: bytes
    after: bytes
    requirement: str
    expectation: Expectation
    naive_failure: str

    def __post_init__(self) -> None:
        if self.fixture_class not in CLASSES:
            raise ValueError(f"fixture {self.fixture_id!r} declares unknown class")
        if not self.requirement or not self.naive_failure:
            raise ValueError(f"fixture {self.fixture_id!r} does not say what it is for")
        for snippet in _snippets_of(self.expectation):
            for side, raw in (("before", self.before), ("after", self.after)):
                if snippet not in raw:
                    raise ValueError(
                        f"fixture {self.fixture_id!r} requires a fact for "
                        f"{snippet!r}, which is not in its own {side} source"
                    )

    def as_dict(self) -> dict[str, Any]:
        return {
            "fixture_id": self.fixture_id,
            "fixture_class": self.fixture_class,
            "requirement": self.requirement,
            "expectation": {
                "type": type(self.expectation).__name__,
                "describes": self.expectation.describe(),
                "relevant_kinds": sorted(self.expectation.relevant_kinds()),
            },
            "naive_failure": self.naive_failure,
            "before_sha256": ir.digest({"raw": self.before.decode("utf-8", "replace")}),
            "after_sha256": ir.digest({"raw": self.after.decode("utf-8", "replace")}),
        }


# ---------------------------------------------------------------------------
# the corpus
#
# Filler is long enough that a canonicaliser with a minimum text length keeps the
# unit. Fixtures that are short are short on purpose and say so.

FILLER = (
    "Retention of processed samples is governed by this section and the schedule "
    "referenced from it, which is written at sufficient length that the block "
    "survives any minimum-text-length rule the canonicaliser applies."
)

_HREF_BEFORE = (
    b"<html lang=\"en\"><body><h1>Retention</h1>"
    b"<p>See <a href=\"https://example.com/policy/v1\">the retention schedule</a>. "
    + FILLER.encode("utf-8")
    + b"</p></body></html>"
)
_HREF_AFTER = _HREF_BEFORE.replace(b"/policy/v1", b"/policy/v2")

_REFDEF_BEFORE = (
    b"# Retention\n\n"
    b"See [the retention schedule][schedule]. " + FILLER.encode("utf-8") + b"\n\n"
    b"## Appendix\n\n" + FILLER.encode("utf-8") + b"\n\n"
    b"[schedule]: https://example.com/policy/v1\n"
)
_REFDEF_AFTER = _REFDEF_BEFORE.replace(b"/policy/v1", b"/policy/v2")

_INCLUDE_BEFORE = (
    b"# Retention\n\n" + FILLER.encode("utf-8") + b"\n\n"
    b'{% include "partials/schedule-v1.md" %}\n'
)
_INCLUDE_AFTER = _INCLUDE_BEFORE.replace(b"schedule-v1.md", b"schedule-v2.md")

_LANG_BEFORE = (
    b"<html lang=\"en-US\"><body><h1>Retention</h1><p>"
    + FILLER.encode("utf-8")
    + b"</p></body></html>"
)
_LANG_AFTER = _LANG_BEFORE.replace(b"en-US", b"en-GB")

_ALT_BEFORE = (
    b"<html lang=\"en\"><body><h1>Retention</h1>"
    b"<p><img src=\"schedule.png\" alt=\"Retention schedule: 30 days\">"
    + FILLER.encode("utf-8")
    + b"</p></body></html>"
)
_ALT_AFTER = _ALT_BEFORE.replace(b"30 days", b"90 days")

_APPLIES_BEFORE = (
    b"<html lang=\"en\"><body><h1 data-applies-to=\"US\">Retention</h1><p>"
    + FILLER.encode("utf-8")
    + b"</p></body></html>"
)
_APPLIES_AFTER = _APPLIES_BEFORE.replace(b'data-applies-to="US"', b'data-applies-to="US,CA"')

_EFFECTIVE_BEFORE = (
    b"<html lang=\"en\"><head><meta name=\"effective-date\" content=\"2026-01-01\"></head>"
    b"<body><h1>Retention</h1><p>" + FILLER.encode("utf-8") + b"</p></body></html>"
)
_EFFECTIVE_AFTER = _EFFECTIVE_BEFORE.replace(b"2026-01-01", b"2026-07-01")

#: Markup-only equivalence. Tag spelling, attribute order and quote style all
#: move; the rendered document and every fact it asserts are identical.
_MARKUP_BEFORE = (
    b"<html lang=\"en\"><body><h1>Retention</h1>"
    b"<p>Samples are kept for <b>30 days</b>. "
    b"<a href=\"https://example.com/policy/v1\" title=\"Schedule\">Schedule</a>. "
    + FILLER.encode("utf-8")
    + b"</p></body></html>"
)
_MARKUP_AFTER = (
    b"<html lang='en'><body><h1>Retention</h1>"
    b"<p>Samples are kept for <strong>30 days</strong>. "
    b"<a title='Schedule' href='https://example.com/policy/v1'>Schedule</a>. "
    + FILLER.encode("utf-8")
    + b"</p></body></html>"
)

#: Entity normalization. Named, decimal and hexadecimal references plus a
#: literal UTF-8 character, all denoting the same two code points.
_ENTITY_BEFORE = (
    b"<html lang=\"en\"><body><h1>Retention &amp; disposal</h1>"
    b"<p>Held at the caf&eacute; site. " + FILLER.encode("utf-8") + b"</p></body></html>"
)
_ENTITY_AFTER = (
    b"<html lang=\"en\"><body><h1>Retention &#38; disposal</h1>"
    b"<p>Held at the caf\xc3\xa9 site. " + FILLER.encode("utf-8") + b"</p></body></html>"
)

#: Malformed location. The anchor is never closed and two elements claim the
#: same id, so "the span of #schedule" has no single answer.
_MALFORMED_BEFORE = (
    b"<html lang=\"en\"><body><h1 id=\"schedule\">Retention</h1>"
    b"<p id=\"schedule\">See <a href=\"#schedule\">the schedule</a. "
    + FILLER.encode("utf-8")
    + b"</p></body></html>"
)
_MALFORMED_AFTER = _MALFORMED_BEFORE.replace(b"Retention", b"Retention and disposal")

#: Genuinely ambiguous date: 03/04/2026 is 3 April under one locale and 4 March
#: under another, and nothing in the document says which.
_AMBIG_DATE_BEFORE = (
    b"<html lang=\"en\"><head><meta name=\"effective-date\" content=\"03/04/2026\"></head>"
    b"<body><h1>Retention</h1><p>" + FILLER.encode("utf-8") + b"</p></body></html>"
)
_AMBIG_DATE_AFTER = _AMBIG_DATE_BEFORE.replace(b"03/04/2026", b"05/06/2026")

#: The contrast. Same document shape, ISO-8601 content, decidable — and the day
#: is past 12, so no locale reading makes it ambiguous either.
_CLEAR_DATE_BEFORE = _AMBIG_DATE_BEFORE.replace(b"03/04/2026", b"2026-04-03")
_CLEAR_DATE_AFTER = _AMBIG_DATE_BEFORE.replace(b"03/04/2026", b"2026-06-05")

#: Unsupported construct: embedded MathML. A parser will happily walk it; no
#: kind in the IR represents an expression tree.
_UNSUPPORTED_BEFORE = (
    b"<html lang=\"en\"><body><h1>Retention</h1>"
    b"<p>" + FILLER.encode("utf-8") + b"</p>"
    b"<math><mrow><mi>t</mi><mo>&lt;</mo><mn>30</mn></mrow></math></body></html>"
)
_UNSUPPORTED_AFTER = _UNSUPPORTED_BEFORE.replace(b"<mn>30</mn>", b"<mn>90</mn>")

#: Percent-encoding that IS equivalent: %7E is the unreserved character "~", and
#: RFC 3986 §6.2.2.2 makes the two URIs the same URI.
_PCT_SAME_BEFORE = (
    b"<html lang=\"en\"><body><h1>Retention</h1>"
    b"<p>See <a href=\"https://example.com/%7Eops/policy\">the schedule</a>. "
    + FILLER.encode("utf-8")
    + b"</p></body></html>"
)
_PCT_SAME_AFTER = _PCT_SAME_BEFORE.replace(b"%7Eops", b"~ops")

#: Percent-encoding that is NOT equivalent: %2F is an encoded slash inside one
#: path segment, "/" is a segment delimiter. Different resources.
_PCT_DIFF_BEFORE = (
    b"<html lang=\"en\"><body><h1>Retention</h1>"
    b"<p>See <a href=\"https://example.com/policy/v1%2Fdraft\">the schedule</a>. "
    + FILLER.encode("utf-8")
    + b"</p></body></html>"
)
_PCT_DIFF_AFTER = _PCT_DIFF_BEFORE.replace(b"v1%2Fdraft", b"v1/draft")

#: Recognised but unrepresentable: a conditional include whose target is an
#: expression. Every parser resolves the directive; no extractor can name the
#: single target the REFERENTIAL channel needs to invalidate on.
_UNREPRESENTABLE_BEFORE = (
    b"# Retention\n\n" + FILLER.encode("utf-8") + b"\n\n"
    b'{% include "partials/schedule-" ~ region ~ ".md" %}\n'
)
_UNREPRESENTABLE_AFTER = _UNREPRESENTABLE_BEFORE.replace(b"~ region ~", b"~ tenant ~")


FIXTURES: tuple[Fixture, ...] = (
    Fixture(
        fixture_id="adv-001-href-changed-text-unchanged",
        fixture_class=VISIBLE_TEXT_UNCHANGED_HREF_CHANGED,
        before=_HREF_BEFORE,
        after=_HREF_AFTER,
        requirement="The reference target must change even though no visible character does.",
        expectation=ChangedIn((ir.REFERENCE_TARGET,)),
        naive_failure=(
            "a text-only compiled state produces byte-identical output for both revisions, so "
            "nothing downstream is told the policy now points somewhere else — INC-V2-006"
        ),
    ),
    Fixture(
        fixture_id="adv-002-reference-definition-out-of-span",
        fixture_class=REFERENCE_DEFINITION_OUT_OF_SPAN,
        before=_REFDEF_BEFORE,
        after=_REFDEF_AFTER,
        requirement=(
            "The link definition at the foot of the file must be a fact, and changing it must "
            "change something, even though the citing paragraph is untouched."
        ),
        expectation=ChangedIn((ir.REFERENCE_DEFINITION,)),
        naive_failure=(
            "a per-block extractor only sees the span it was handed; the definition lives in a "
            "different block entirely, so the diff lands on a block nobody considers semantic"
        ),
    ),
    Fixture(
        fixture_id="adv-003-include-target-changed",
        fixture_class=INCLUDE_TARGET_CHANGED,
        before=_INCLUDE_BEFORE,
        after=_INCLUDE_AFTER,
        requirement="An include directive's target must be a fact on the REFERENTIAL channel.",
        naive_failure=(
            "the directive renders to nothing, so a compile-then-extract pipeline sees an empty "
            "delta and never invalidates the artifact that transcluded the old partial"
        ),
        expectation=ChangedIn((ir.INCLUDE_TARGET,)),
    ),
    Fixture(
        fixture_id="adv-004-language-metadata-changed",
        fixture_class=LANGUAGE_METADATA_CHANGED,
        before=_LANG_BEFORE,
        after=_LANG_AFTER,
        requirement="A change of declared language must produce a LANGUAGE fact change.",
        expectation=ChangedIn((ir.LANGUAGE,)),
        naive_failure=(
            "the attribute is on the root element and never appears in extracted text, so a "
            "text-only state cannot tell an en-US corpus from an en-GB one"
        ),
    ),
    Fixture(
        fixture_id="adv-005-accessibility-alt-text-changed",
        fixture_class=ACCESSIBILITY_APPLICABILITY_CHANGED,
        before=_ALT_BEFORE,
        after=_ALT_AFTER,
        requirement="Alt text carries a retention number; changing it must change a fact.",
        expectation=ChangedIn((ir.ACCESSIBILITY,)),
        naive_failure=(
            "alt text is discarded as presentation, so a substantive 30-to-90-day change hides in "
            "an attribute the extractor was told to skip"
        ),
    ),
    Fixture(
        fixture_id="adv-006-applicability-scope-changed",
        fixture_class=ACCESSIBILITY_APPLICABILITY_CHANGED,
        before=_APPLIES_BEFORE,
        after=_APPLIES_AFTER,
        requirement="Widening applicability from US to US+CA must change an APPLICABILITY fact.",
        expectation=ChangedIn((ir.APPLICABILITY,)),
        naive_failure=(
            "a data- attribute looks like vendor decoration; dropping it makes a document apply to "
            "a jurisdiction the compiled state has no record of it entering"
        ),
    ),
    Fixture(
        fixture_id="adv-007-effective-date-changed",
        fixture_class=EFFECTIVE_DATE_CHANGED,
        before=_EFFECTIVE_BEFORE,
        after=_EFFECTIVE_AFTER,
        requirement="A moved effective date must change a fact on the TEMPORAL channel.",
        expectation=ChangedIn((ir.EFFECTIVE_TIME,)),
        naive_failure=(
            "head metadata is not body text; the document reads identically while the period it "
            "governs has moved by six months"
        ),
    ),
    Fixture(
        fixture_id="adv-008-markup-only-equivalence",
        fixture_class=MARKUP_ONLY_EQUIVALENCE,
        before=_MARKUP_BEFORE,
        after=_MARKUP_AFTER,
        requirement="Tag spelling, attribute order and quote style change nothing. No delta.",
        expectation=Unchanged(),
        naive_failure=(
            "a byte- or DOM-shape-sensitive extractor reports a delta on every fact in the "
            "paragraph, which recompiles the world and buries the real changes in noise"
        ),
    ),
    Fixture(
        fixture_id="adv-009-entity-normalization",
        fixture_class=ENTITY_NORMALIZATION,
        before=_ENTITY_BEFORE,
        after=_ENTITY_AFTER,
        requirement="&amp;, &#38; and a literal UTF-8 é denote the same text. No fact may change.",
        expectation=Unchanged(),
        naive_failure=(
            "comparing raw source bytes, or decoding on one side only, turns a lossless re-encode "
            "into a content change on every heading in the corpus"
        ),
    ),
    Fixture(
        fixture_id="adv-010-malformed-ambiguous-location",
        fixture_class=MALFORMED_OR_AMBIGUOUS_LOCATION,
        before=_MALFORMED_BEFORE,
        after=_MALFORMED_AFTER,
        requirement=(
            "The anchor is unterminated and two elements claim id=schedule. The locator is not "
            "decidable and must be UNRESOLVED with a reason, on both revisions."
        ),
        expectation=AllOf(
            (
                MustBeInState(ir.UNRESOLVED),
                #: Only the anchor: the heading belongs to the core lane, and a
                #: reference-lane fixture must not go red for a lane it is not testing.
                NoSilentAbsence((b'<a href="#schedule">',)),
            )
        ),
        naive_failure=(
            "a forgiving parser silently picks the first #schedule and reports a clean locator, "
            "so an undecidable reference is recorded as a resolved one"
        ),
    ),
    Fixture(
        fixture_id="adv-011-unsupported-construct-mathml",
        fixture_class=UNSUPPORTED_CONSTRUCT,
        before=_UNSUPPORTED_BEFORE,
        after=_UNSUPPORTED_AFTER,
        requirement=(
            "No IR kind represents an expression tree. The construct must be refused fail-closed "
            "and must still produce a fact."
        ),
        expectation=AllOf((MustFailClosed(), NoSilentAbsence((b"<math>",)))),
        naive_failure=(
            "the parser recognises <math> and the grammar table says MODELED, so 30-to-90 inside "
            "the formula is counted as carried when nothing carries it — the SFH1 failure exactly"
        ),
    ),
    Fixture(
        fixture_id="adv-012-percent-encoding-equivalent",
        fixture_class=REFERENCE_TARGET_ENCODING,
        before=_PCT_SAME_BEFORE,
        after=_PCT_SAME_AFTER,
        requirement="%7E and ~ are the same URI (RFC 3986 §6.2.2.2). No fact may change.",
        expectation=Unchanged(),
        naive_failure=(
            "string-comparing hrefs reports a reference change and invalidates every dependent "
            "artifact for a re-encode that points at the same resource"
        ),
    ),
    Fixture(
        fixture_id="adv-013-percent-encoding-not-equivalent",
        fixture_class=REFERENCE_TARGET_ENCODING,
        before=_PCT_DIFF_BEFORE,
        after=_PCT_DIFF_AFTER,
        requirement=(
            "%2F is data inside a segment; / is a delimiter. Different targets, real delta."
        ),
        expectation=ChangedIn((ir.REFERENCE_TARGET,)),
        naive_failure=(
            "a normaliser that percent-decodes everything before comparing collapses two distinct "
            "resources into one — the over-correction that fixing adv-012 naively produces"
        ),
    ),
    Fixture(
        fixture_id="adv-014-ambiguous-date",
        fixture_class=AMBIGUOUS_VS_DECIDABLE_DATE,
        before=_AMBIG_DATE_BEFORE,
        after=_AMBIG_DATE_AFTER,
        requirement=(
            "03/04/2026 has two readings and the document names neither. The effective time is "
            "UNRESOLVED with a reason on both revisions."
        ),
        expectation=MustBeInState(ir.UNRESOLVED, kinds=(ir.EFFECTIVE_TIME,)),
        naive_failure=(
            "dateutil parses it without complaint under a default locale, so a guess is stored as "
            "a fact and the temporal channel invalidates on a date nobody asserted"
        ),
    ),
    Fixture(
        fixture_id="adv-015-decidable-date-contrast",
        fixture_class=AMBIGUOUS_VS_DECIDABLE_DATE,
        before=_CLEAR_DATE_BEFORE,
        after=_CLEAR_DATE_AFTER,
        requirement="2026-04-03 is decidable. It must resolve and its change must be a real delta.",
        expectation=ChangedIn((ir.EFFECTIVE_TIME,)),
        naive_failure=(
            "over-correcting adv-014 by declaring every date ambiguous makes the whole corpus "
            "fail-closed, which is a different way of representing nothing"
        ),
    ),
    Fixture(
        fixture_id="adv-016-recognized-but-unrepresentable-include",
        fixture_class=RECOGNIZED_BUT_UNREPRESENTABLE,
        before=_UNREPRESENTABLE_BEFORE,
        after=_UNREPRESENTABLE_AFTER,
        requirement=(
            "The directive parses, but its target is an expression and no single target can be "
            "named. It must be RECOGNIZED_BUT_UNREPRESENTED with a reason, not resolved."
        ),
        expectation=MustBeInState(ir.UNREPRESENTED, kinds=(ir.INCLUDE_TARGET,)),
        naive_failure=(
            "the grammar recognises the include and answers MODELED from a table, which is the "
            "exact split the four-state IR exists to make impossible"
        ),
    ),
)


BY_ID: dict[str, Fixture] = {f.fixture_id: f for f in FIXTURES}


# ---------------------------------------------------------------------------
# the checker


def check(
    fixture: Fixture,
    before_facts: Iterable[ir.SourceFact],
    after_facts: Iterable[ir.SourceFact],
    *,
    available_kinds: Iterable[str] | None = None,
) -> Outcome:
    """Evaluate one fixture's declared expectation against real extractor output.

    ``available_kinds`` is what the caller's registry actually claims — normally
    ``ir.registered_kinds()``. Pass it. Without it the function has to infer
    availability from the facts it was handed, and that inference is
    conservative in the only safe direction: a kind that produced nothing is
    treated as unclaimed, so a genuine FAIL can be reported as NOT_EXERCISED. It
    is never wrong in the other direction, because that direction is a silent
    pass and a silent pass is the thing this file exists to prevent.
    """
    before = tuple(before_facts)
    after = tuple(after_facts)
    expectation = fixture.expectation
    required = expectation.relevant_kinds()

    claimed = (
        frozenset(available_kinds)
        if available_kinds is not None
        else _kinds_present(before) | _kinds_present(after)
    )
    missing = sorted(required - claimed)
    if missing:
        return Outcome(
            fixture.fixture_id,
            NOT_EXERCISED,
            f"no extractor produces {', '.join(missing)}; the fixture's expectation "
            f"({expectation.describe()}) was never evaluated",
            {"missing_kinds": missing, "claimed_kinds": sorted(claimed)},
        )
    if not before and not after:
        return Outcome(
            fixture.fixture_id,
            NOT_EXERCISED,
            "no facts were produced for either revision; nothing ran, so nothing was tested",
            {"claimed_kinds": sorted(claimed)},
        )

    held, reason, detail = expectation.evaluate(
        before, after, before_raw=fixture.before, after_raw=fixture.after
    )
    detail = dict(detail)
    detail["expectation"] = expectation.describe()
    return Outcome(fixture.fixture_id, PASS if held else FAIL, reason, detail)


def check_all(
    extract: Callable[[bytes], Iterable[ir.SourceFact]],
    *,
    available_kinds: Iterable[str] | None = None,
    fixtures: Iterable[Fixture] = FIXTURES,
) -> dict[str, Any]:
    """Run the corpus through one extraction callable and summarise honestly.

    ``not_exercised`` is reported beside ``passed`` and is never folded into it.
    A summary that reports 16/16 green when nine of them never ran is the report
    this programme was created to stop producing.
    """
    outcomes: list[Outcome] = []
    for fixture in fixtures:
        try:
            before = tuple(extract(fixture.before))
            after = tuple(extract(fixture.after))
        except Exception as error:  # an extractor that crashes is a failed fixture, not a skip
            outcomes.append(
                Outcome(
                    fixture.fixture_id,
                    FAIL,
                    f"extraction raised {type(error).__name__}: {error}",
                    {"expectation": fixture.expectation.describe()},
                )
            )
            continue
        outcomes.append(check(fixture, before, after, available_kinds=available_kinds))

    by_status = Counter(o.status for o in outcomes)
    return {
        "schema": SCHEMA,
        "outcomes": [o.as_dict() for o in outcomes],
        "total": len(outcomes),
        "passed": by_status[PASS],
        "failed": by_status[FAIL],
        "not_exercised": by_status[NOT_EXERCISED],
        "all_exercised_and_passed": (
            by_status[PASS] == len(outcomes) and len(outcomes) > 0
        ),
        "failing": [o.fixture_id for o in outcomes if o.status == FAIL],
        "unexercised": [o.fixture_id for o in outcomes if o.status == NOT_EXERCISED],
    }


def inventory() -> list[dict[str, Any]]:
    """The corpus as data, for a receipt."""
    return [f.as_dict() for f in FIXTURES]


if __name__ == "__main__":
    import json

    print(json.dumps({"schema": SCHEMA, "fixtures": inventory()}, indent=2, ensure_ascii=False))
