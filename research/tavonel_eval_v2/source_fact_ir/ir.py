"""SOURCE_FACT_IR_V1 — the core contract. Every lane implements against this file.

Founder ruling, 2026-08-23:

    A source construct must never be called MODELED merely because the parser
    recognizes it. [...] Every represented source fact must have:
    source witness -> canonical representation -> fingerprint ->
    dependency/invalidation path. If any link in that chain is absent, the state
    cannot be declared source-faithful CURRENT.

SFH1's failure was representation completeness, and the shape of the failure is
worth stating precisely because it is easy to rebuild:

    the old instrument asked the *grammar* whether a construct was modelled. The
    grammar answered from a table. The compiled state was never consulted.

So `MODELED` splits in two. `REPRESENTED_IN_COMPILED_STATE` is an assertion
about the compiled state and is checkable against it. `RECOGNIZED_BUT_UNREPRESENTED`
is what the old `MODELED` actually meant in 63,196 of 121,682 cases, and naming
it is most of the repair.

Four states, and a fact is in exactly one:

    REPRESENTED_IN_COMPILED_STATE   the compiled state carries it, and the whole
                                    chain resolves. The only state that may
                                    appear inside a scope declared complete.
    RECOGNIZED_BUT_UNREPRESENTED    the parser saw it; the compiled state has no
                                    canonical representation for it. Fail-closed.
    IGNORED_BY_PREDECLARED_POLICY   declined in advance, by a policy identifier
                                    that must exist before the run. Fail-open,
                                    and the only fail-open state there is.
    UNRESOLVED_SOURCE_FACT          seen but not decidable — malformed source,
                                    ambiguous locator, unsupported construct.
                                    Fail-closed.

Fail-closed means: a scope containing one cannot be declared complete, and a
compiled state containing one cannot be declared source-faithful CURRENT. It
does *not* mean the run dies. An unresolved fact that stops the run cannot be
counted, and a fact that cannot be counted is indistinguishable from one that
was never seen — which is exactly the silent drop this whole programme exists
to make impossible.

The one rule that shapes everything else: **a representation lives in the IR, not
in unit text.** The ruling forbids stuffing facets into text and it is right to.
Text is where facets go to become invisible: a reference whose target moved but
whose anchor text did not produces no textual difference, so a text-only state
cannot represent the change, cannot fingerprint it and cannot invalidate on it.
That is INC-V2-006 and three of the four confirmed stale escapes.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol

SCHEMA = "tavonel.v2.source_fact_ir.v1"

# ---------------------------------------------------------------------------
# states

REPRESENTED = "REPRESENTED_IN_COMPILED_STATE"
UNREPRESENTED = "RECOGNIZED_BUT_UNREPRESENTED"
IGNORED = "IGNORED_BY_PREDECLARED_POLICY"
UNRESOLVED = "UNRESOLVED_SOURCE_FACT"

STATES: tuple[str, ...] = (REPRESENTED, UNREPRESENTED, IGNORED, UNRESOLVED)

#: The states that forbid "complete" and "source-faithful CURRENT". Note that
#: IGNORED is not among them and REPRESENTED is not either: a declined loss is a
#: declared limitation, and a carried fact is not a loss at all.
FAIL_CLOSED: frozenset[str] = frozenset({UNREPRESENTED, UNRESOLVED})

#: A state that must name why. IGNORED must name a predeclared policy; the two
#: fail-closed states must name a reason. REPRESENTED explains itself by having
#: a representation, and is the only state that may leave `reason` empty.
REQUIRES_POLICY: frozenset[str] = frozenset({IGNORED})
REQUIRES_REASON: frozenset[str] = frozenset({UNREPRESENTED, UNRESOLVED})


# ---------------------------------------------------------------------------
# fact kinds
#
# One entry per semantic facet the ruling names, plus the two the compiled state
# already carries. A kind is not a hint: it selects the dependency channel and
# therefore what a change to it invalidates.

CONTENT_TEXT = "CONTENT_TEXT"
STRUCTURE = "STRUCTURE"
REFERENCE_TARGET = "REFERENCE_TARGET"
REFERENCE_DEFINITION = "REFERENCE_DEFINITION"
INCLUDE_TARGET = "INCLUDE_TARGET"
LOCATOR = "CANONICAL_SOURCE_LOCATOR"
PROVENANCE_SPAN = "PROVENANCE_SPAN"
LANGUAGE = "LANGUAGE"
ACCESSIBILITY = "ACCESSIBILITY"
APPLICABILITY = "APPLICABILITY"
EFFECTIVE_TIME = "EFFECTIVE_TIME"
AUTHORITY = "AUTHORITY"

#: The kind for a construct the supported grammar does not cover at all.
#:
#: It looks like a contradiction - a facet type for things whose facet we cannot
#: name - and it is the most important kind here. Without it an unsupported
#: construct produces NOTHING, and nothing is indistinguishable from a clean
#: document. MathML is the case that forced it: no kind represents an expression
#: tree, so a section containing one was scoring perfectly.
#:
#: A fact of this kind is ALWAYS `UNRESOLVED_SOURCE_FACT`. It never carries a
#: representation and it can never be declined by policy - a policy that
#: declined "everything we do not support" would restore the silence with
#: paperwork attached.
UNSUPPORTED_CONSTRUCT = "UNSUPPORTED_CONSTRUCT"

KINDS: tuple[str, ...] = (
    CONTENT_TEXT,
    STRUCTURE,
    REFERENCE_TARGET,
    REFERENCE_DEFINITION,
    INCLUDE_TARGET,
    LOCATOR,
    PROVENANCE_SPAN,
    LANGUAGE,
    ACCESSIBILITY,
    APPLICABILITY,
    EFFECTIVE_TIME,
    AUTHORITY,
    UNSUPPORTED_CONSTRUCT,
)

#: Lane ownership, declared here so two extractors cannot both claim a kind and
#: so an unclaimed kind is visible rather than merely absent.
KIND_OWNER: dict[str, str] = {
    CONTENT_TEXT: "core",
    STRUCTURE: "core",
    PROVENANCE_SPAN: "core",
    REFERENCE_TARGET: "reference",
    REFERENCE_DEFINITION: "reference",
    INCLUDE_TARGET: "reference",
    LOCATOR: "reference",
    LANGUAGE: "metadata",
    ACCESSIBILITY: "metadata",
    APPLICABILITY: "metadata",
    EFFECTIVE_TIME: "metadata",
    AUTHORITY: "metadata",
    UNSUPPORTED_CONSTRUCT: "core",
}


# ---------------------------------------------------------------------------
# dependency channels
#
# The channel a kind travels on decides what a change to it invalidates. This is
# where INC-V2-028's alignment failure gets fixed: a typed fact whose channel is
# declared cannot move without something downstream being told.

SEMANTIC = "SEMANTIC"
STRUCTURAL = "STRUCTURAL"
REFERENTIAL = "REFERENTIAL"
TEMPORAL = "TEMPORAL"
DESCRIPTIVE = "DESCRIPTIVE"

CHANNELS: tuple[str, ...] = (SEMANTIC, STRUCTURAL, REFERENTIAL, TEMPORAL, DESCRIPTIVE)

KIND_CHANNEL: dict[str, str] = {
    CONTENT_TEXT: SEMANTIC,
    STRUCTURE: STRUCTURAL,
    PROVENANCE_SPAN: STRUCTURAL,
    REFERENCE_TARGET: REFERENTIAL,
    REFERENCE_DEFINITION: REFERENTIAL,
    INCLUDE_TARGET: REFERENTIAL,
    LOCATOR: REFERENTIAL,
    LANGUAGE: DESCRIPTIVE,
    ACCESSIBILITY: DESCRIPTIVE,
    APPLICABILITY: DESCRIPTIVE,
    EFFECTIVE_TIME: TEMPORAL,
    AUTHORITY: TEMPORAL,
    #: semantic, conservatively. We do not know what an unsupported construct
    #: means, so we assume it could mean anything and invalidate accordingly.
    UNSUPPORTED_CONSTRUCT: SEMANTIC,
}


def unit_path_for(source_id: str, explicit_path: Iterable[str]) -> tuple[str, ...]:
    """The one witness `unit_path` convention: document-qualified, always.

    Declared centrally because three extractors write it and one resolver reads
    it, and a disagreement here is silent: an unqualified path still looks like
    a path, still hashes, still compares — and anchors the fact to the wrong
    artifact, or to none.

    Qualified by `source_id` because a bare explicit path is not unique across
    documents. Two files with a `## Notes` heading would otherwise produce facts
    that collide in identity and invalidate each other's artifacts, which is a
    worse failure than the one this IR was built to fix: it would not lose a
    change, it would deliver it to the wrong place.
    """
    return (source_id, *explicit_path)


def canonical_json(value: Any) -> str:
    """One serialization, used by every fingerprint in the system.

    Sorted keys and no incidental whitespace, so a representation's digest is a
    property of the representation rather than of the dict literal that built it.
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# the chain, link by link


class NotSourceFaithful(Exception):
    """Raised where a caller asserts a property the facts do not support.

    Deliberately an exception rather than a boolean: the states that forbid
    "complete" are fail-closed, and a fail-closed condition that returns False
    into an `if` nobody wrote is not fail-closed at all.
    """


@dataclass(frozen=True)
class Witness:
    """Where in the raw source the fact was seen. Link 1 of the chain.

    Byte offsets into the raw payload, never into a decoded or normalised
    string: a witness that cannot be checked against the bytes on disk is a
    claim about the parser rather than about the source.
    """

    construct: str
    byte_start: int
    byte_end: int
    excerpt: str = ""
    unit_path: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        if self.byte_start < 0 or self.byte_end < self.byte_start:
            raise ValueError(
                f"witness span is not a span: {(self.byte_start, self.byte_end)!r}"
            )

    def as_dict(self) -> dict[str, Any]:
        return {
            "construct": self.construct,
            "byte_start": self.byte_start,
            "byte_end": self.byte_end,
            "excerpt": self.excerpt[:200],
            "unit_path": list(self.unit_path) if self.unit_path is not None else None,
        }

    def verify(self, raw: bytes) -> bool:
        """The witness points at bytes that exist and, if an excerpt was
        recorded, at bytes that still contain it."""
        if self.byte_end > len(raw):
            return False
        if not self.excerpt:
            return True
        window = raw[self.byte_start : self.byte_end].decode("utf-8", "replace")
        return self.excerpt[:200] in window or window in self.excerpt


@dataclass(frozen=True)
class SourceFact:
    """One fact the source asserts, and what the compiled state did with it.

    `representation` is link 2 and is the whole point: a JSON-serializable
    canonical value that is NOT the unit's text. A reference target compiles to
    a target, not to the words around it.
    """

    kind: str
    witness: Witness
    state: str
    representation: Any | None = None
    policy_ref: str | None = None
    reason: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in KIND_CHANNEL:
            raise ValueError(f"unknown fact kind {self.kind!r}")
        if self.state not in STATES:
            raise ValueError(f"unknown state {self.state!r}")
        if self.state == REPRESENTED and self.representation is None:
            raise ValueError(
                f"{REPRESENTED} with no representation. The state asserts the compiled state "
                "carries the fact; nothing here carries it."
            )
        if self.state != REPRESENTED and self.representation is not None:
            raise ValueError(
                f"a representation on a {self.state} fact. Only {REPRESENTED} "
                "may carry one, or the distinction the four states exist to "
                "draw stops holding."
            )
        if self.kind == UNSUPPORTED_CONSTRUCT and self.state != UNRESOLVED:
            raise ValueError(
                f"an {UNSUPPORTED_CONSTRUCT} fact in state {self.state}. It is "
                "always unresolved: representing it would mean the grammar "
                "supports it, and declining it by policy would restore the "
                "silence with paperwork attached."
            )
        if self.state in REQUIRES_POLICY and not self.policy_ref:
            raise ValueError(f"{self.state} with no predeclared policy reference")
        if self.state in REQUIRES_REASON and not self.reason:
            raise ValueError(f"{self.state} with no reason")
        if self.state not in REQUIRES_POLICY and self.policy_ref:
            raise ValueError(
                f"a policy reference on a {self.state} fact. Only {IGNORED} is decided by policy; "
                "citing one elsewhere makes a loss look declined when it was not."
            )

    @property
    def channel(self) -> str:
        return KIND_CHANNEL[self.kind]

    @property
    def fail_closed(self) -> bool:
        return self.state in FAIL_CLOSED

    @property
    def fact_id(self) -> str:
        """Identity from witness and kind, never from the representation.

        A fact whose value changed is the SAME fact with a new value — if the
        identity moved with the value there would be no such thing as a change,
        only a disappearance and an arrival, and nothing downstream could be
        told which artifact to rebuild.
        """
        return digest(
            {
                "kind": self.kind,
                "construct": self.witness.construct,
                "unit_path": list(self.witness.unit_path)
                if self.witness.unit_path is not None
                else None,
                "byte_start": self.witness.byte_start,
            }
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "fact_id": self.fact_id,
            "kind": self.kind,
            "channel": self.channel,
            "state": self.state,
            "witness": self.witness.as_dict(),
            "representation": self.representation,
            "policy_ref": self.policy_ref,
            "reason": self.reason,
            "extra": self.extra,
        }


# ---------------------------------------------------------------------------
# extractors
#
# Lanes 2 and 3 implement this protocol. Registration is explicit and the
# registry refuses two extractors for one kind, so a kind cannot be produced by
# two lanes with two different representations.


class Extractor(Protocol):
    kinds: tuple[str, ...]

    def extract(self, *, raw: bytes, document: dict[str, Any]) -> list[SourceFact]:
        ...


_REGISTRY: dict[str, Extractor] = {}


def _producer(extractor: Extractor) -> tuple[str, str]:
    """Who produces a kind, named so a re-import is not mistaken for a rival."""
    kind_of = type(extractor)
    return kind_of.__module__.rsplit(".", 1)[-1], kind_of.__qualname__


def register(extractor: Extractor) -> Extractor:
    for kind in extractor.kinds:
        if kind not in KIND_CHANNEL:
            raise ValueError(f"extractor claims unknown kind {kind!r}")
        owner = _REGISTRY.get(kind)
        #: Identity comparison was wrong twice over. This namespace puts several
        #: directories on sys.path, so one module can be imported under two
        #: roots; that produces two module objects, two class objects and two
        #: instances — a re-import, not a rival. Neither `is` on the instance nor
        #: `is` on the type survives it.
        #:
        #: So a producer is named by where it lives: module basename plus class
        #: name. A re-import matches and is idempotent; a genuine second
        #: implementation lives somewhere else or is called something else, and
        #: is still refused. The guard exists to stop two representations of one
        #: kind, not to police import bookkeeping.
        if owner is not None and _producer(owner) != _producer(extractor):
            raise ValueError(
                f"kind {kind!r} is already produced by {_producer(owner)}; "
                "two representations of one kind is the ambiguity this registry "
                "exists to refuse"
            )
        _REGISTRY[kind] = extractor
    return extractor


def registered_kinds() -> tuple[str, ...]:
    return tuple(sorted(_REGISTRY))


def unclaimed_kinds() -> tuple[str, ...]:
    """Kinds the IR declares and no extractor produces.

    Not an error by itself — it is the honest answer to "what does this build
    not look for", and the protocol's gates read it rather than assuming zero.
    """
    return tuple(sorted(set(KIND_CHANNEL) - set(_REGISTRY)))


def extract_all(*, raw: bytes, document: dict[str, Any]) -> list[SourceFact]:
    """Every registered extractor, in a deterministic order."""
    seen: list[SourceFact] = []
    for extractor in sorted(set(_REGISTRY.values()), key=lambda item: type(item).__name__):
        seen.extend(extractor.extract(raw=raw, document=document))
    return sorted(seen, key=lambda fact: (fact.witness.byte_start, fact.kind, fact.fact_id))


# ---------------------------------------------------------------------------
# chain completeness
#
# Link 3 (fingerprint) and link 4 (dependency path) are implemented by lane 4
# and injected here, so this module states the requirement without depending on
# the implementation that satisfies it.

Fingerprinter = Callable[[SourceFact], str]
DependencyResolver = Callable[[SourceFact], tuple[str, ...]]

_MISSING_LINK = "chain link absent: %s"


def chain(
    fact: SourceFact,
    *,
    raw: bytes | None,
    fingerprint: Fingerprinter | None,
    dependencies: DependencyResolver | None,
) -> dict[str, Any]:
    """Resolve all four links for one fact and report each, without deciding.

    A caller that wants a verdict calls `assert_source_faithful`. This returns
    the evidence for one, because a gate that cannot show which link failed is a
    gate nobody can act on.
    """
    links: dict[str, Any] = {
        "fact_id": fact.fact_id,
        "kind": fact.kind,
        "state": fact.state,
        "witness": fact.witness.byte_end > fact.witness.byte_start
        or fact.witness.byte_end == fact.witness.byte_start,
        "witness_verified": None if raw is None else fact.witness.verify(raw),
        "representation": fact.representation is not None,
        "fingerprint": None,
        "dependency_path": None,
    }
    if fact.state != REPRESENTED:
        #: only a REPRESENTED fact claims the chain. The others make no such
        #: claim, and testing them against it would manufacture failures out of
        #: honest declarations.
        links["required"] = False
        return links

    links["required"] = True
    if fingerprint is not None:
        try:
            value = fingerprint(fact)
        except Exception as error:
            links["fingerprint"] = False
            links["fingerprint_error"] = f"{type(error).__name__}: {error}"
        else:
            links["fingerprint"] = bool(value)
            links["fingerprint_value"] = value
    if dependencies is not None:
        try:
            edges = dependencies(fact)
        except Exception as error:
            links["dependency_path"] = False
            links["dependency_error"] = f"{type(error).__name__}: {error}"
        else:
            links["dependency_path"] = bool(edges)
            links["dependency_keys"] = list(edges)
    return links


def chain_complete(links: dict[str, Any]) -> bool:
    if not links.get("required"):
        return True
    if links.get("witness_verified") is False:
        return False
    return bool(
        links.get("witness")
        and links.get("representation")
        and links.get("fingerprint")
        and links.get("dependency_path")
    )


def assert_source_faithful(
    facts: Iterable[SourceFact],
    *,
    raw: bytes | None = None,
    fingerprint: Fingerprinter | None = None,
    dependencies: DependencyResolver | None = None,
    scope: str = "the compiled state",
) -> None:
    """Fail closed, loudly, naming the fact and the missing link.

    Called where a run wants to say CURRENT or complete. Not called on the
    counting path: counting must survive unresolved facts in order to report
    them.
    """
    broken: list[dict[str, Any]] = []
    blocking: list[SourceFact] = []
    for fact in facts:
        if fact.fail_closed:
            blocking.append(fact)
            continue
        links = chain(fact, raw=raw, fingerprint=fingerprint, dependencies=dependencies)
        if not chain_complete(links):
            broken.append(links)
    if blocking:
        raise NotSourceFaithful(
            f"{scope} carries {len(blocking)} fail-closed source fact(s); "
            f"the first is {blocking[0].state} {blocking[0].kind} "
            f"({blocking[0].reason})"
        )
    if broken:
        missing = [name for name in ("witness", "representation", "fingerprint",
                                     "dependency_path") if not broken[0].get(name)]
        raise NotSourceFaithful(
            _MISSING_LINK % ", ".join(missing)
            + " for {} {} in {}".format(broken[0]["kind"], broken[0]["fact_id"][:19], scope)
        )


def tally(facts: Iterable[SourceFact]) -> dict[str, int]:
    counts = {state: 0 for state in STATES}
    for fact in facts:
        counts[fact.state] += 1
    return counts


# ---------------------------------------------------------------------------
# one module object, whichever name loads first
#
# This namespace imports flatly (`import ir`, with source_fact_ir/ on sys.path)
# and package-qualified (`from .ir import ...`). Without the aliasing below,
# BOTH happen in one process and Python builds two module objects — two
# `_REGISTRY` dicts, two sets of registered extractors.
#
# Nothing raises. `extract_all` walks whichever registry the caller reached and
# returns a shorter list, and a shorter list of source facts is a document that
# looks cleaner than it is. That is this programme's defining failure mode
# arriving through the import system rather than through a parser, and it cost
# an afternoon: lane 2's extractor was registered, tested, and produced nothing.
#
# `setdefault` rather than assignment: the first name to load owns the object
# and the second is bound to it, so the aliasing cannot itself replace a module
# that something already holds a reference to.

for _alias in ("ir", f"{__package__}.ir" if __package__ else "source_fact_ir.ir"):
    sys.modules.setdefault(_alias, sys.modules[__name__])
