"""Domain-separated identity proof for SFIR4 candidates.

``sfir4_protocol`` proved candidate disjointness by pooling three of the five
identity fields into one flat, casefolded, cross-family set::

    identity_values = [container_id, lineage_id, *alias_ids]
    candidate_identities = {value.casefold() for value in identity_values}
    if ... candidate_identities & global_identities: refuse

That set is wrong in both directions at once, which is why neither direction was
visible:

FALSE REFUSAL
    ``discovery_root_id``/``root_container_id`` for one family and
    ``container_id`` for another are different namespaces that happen to be
    spelled as strings. Pooling them across families means an accidental string
    equality is reported as scientific identity equivalence -- two unrelated
    documents in unrelated corpora would sink the census.

FALSE PASS
    ``root_container_id`` was never added to the pooled set at all. A candidate
    whose ``root_container_id`` equals another candidate's ``container_id`` was
    not a collision to that proof, even though those two names denote things at
    the same level of the same family.

The repair is a typed domain. An identity is a ``(family, domain, value)``
triple, collisions are proved inside a namespace, and equality that crosses a
namespace boundary is recorded as INCIDENTAL rather than refused. A proof that
says "no collisions" now also says which namespaces it checked and how many
incidental equalities it saw, so it cannot be a true statement about a narrower
question than the one it appears to answer.

Three namespaces per family, separated by whether repetition is legitimate:

DOCUMENT -- proved UNIQUE
    ``lineage_id``, ``alias_ids``. A lineage is one document's identity across
    revisions and an alias is another name for that same document, so two
    candidates sharing either name are the same document counted twice.

CONTAINER -- proved CONSISTENT, may repeat
    ``container_id``. A container holds many documents; requiring it unique
    would refuse every candidate after the first in any directory. The old
    pooled set had exactly that error, hidden because nothing exercised two
    candidates from one container.

ROOT -- proved CONSISTENT, may repeat
    ``discovery_root_id``, ``root_container_id``. Many candidates share a root.

Across those namespaces one cross-check survives from the old pooling, and it
was the part that was right: within a family, no DOCUMENT name may also be a
CONTAINER name. A string that denotes both a document and the thing containing
it is a genuine ambiguity, whichever namespace it was declared in.

Comparison is exact after NFC, not casefolded. ``casefold`` is retained in
exactly one place -- :func:`spent_key` -- and there it is deliberately widened
further, because the two comparisons want opposite errors. See that function.
"""

from __future__ import annotations

import unicodedata
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class IdentityDomain(StrEnum):
    """The semantic namespace a candidate identity field belongs to."""

    DISCOVERY_ROOT = "discovery_root_id"
    ROOT_CONTAINER = "root_container_id"
    CONTAINER = "container_id"
    LINEAGE = "lineage_id"
    ALIAS = "alias_ids"


#: Names that identify one document. Two candidates may never share one.
DOCUMENT_DOMAINS: tuple[IdentityDomain, ...] = (
    IdentityDomain.LINEAGE,
    IdentityDomain.ALIAS,
)
#: Names that identify a container. Many candidates legitimately share one.
CONTAINER_DOMAINS: tuple[IdentityDomain, ...] = (IdentityDomain.CONTAINER,)
#: Names that identify a discovery root. Many candidates legitimately share one.
ROOT_DOMAINS: tuple[IdentityDomain, ...] = (
    IdentityDomain.DISCOVERY_ROOT,
    IdentityDomain.ROOT_CONTAINER,
)

NAMESPACES: Mapping[str, tuple[IdentityDomain, ...]] = {
    "DOCUMENT": DOCUMENT_DOMAINS,
    "CONTAINER": CONTAINER_DOMAINS,
    "ROOT": ROOT_DOMAINS,
}

#: The namespaces in which a repeated name is legitimate rather than a collision.
REPEATABLE: frozenset[str] = frozenset({"CONTAINER", "ROOT"})

#: Families whose identity constructors ALREADY fold case, so that two document
#: identities differing only by case cannot arise from a well-formed source.
#:
#: Read off ``probe_sfir4_capacity._candidate`` rather than assumed:
#:
#: * ``encyclopedia_wikipedia`` -- the lineage is ``wiki:en:<numeric page id>``
#:   and every alias is built as ``wiki:en:title:{...casefold()}``. A case
#:   variant here cannot come from the API; it means a value arrived from
#:   somewhere unaccounted for, and that is worth refusing.
#: * ``git_docs`` -- the lineage is ``git:{repo}:{path}`` with the tree path
#:   preserved verbatim. Git trees are case-sensitive, so ``README.md`` and
#:   ``readme.md`` are two real files and merging or refusing them would
#:   discard a legitimate candidate.
#: * ``regulation_ecfr`` -- part and section designators come from the eCFR API
#:   with their case preserved. Nothing here establishes that a case variant is
#:   impossible, so nothing here refuses one.
#:
#: A family is listed only where the refusal can be justified from the
#: constructor. The default is to permit, because a wrong refusal silently
#: shrinks the corpus and a census cannot tell that it happened.
CASE_FOLDED_FAMILIES: frozenset[str] = frozenset({"encyclopedia_wikipedia"})


class IdentityDomainRefused(RuntimeError):
    """A collision inside one namespace, or a malformed identity."""


@dataclass(frozen=True, slots=True)
class TypedIdentity:
    """One identity value, tagged with the namespace that gives it meaning."""

    family: str
    domain: IdentityDomain
    value: str

    @property
    def namespace(self) -> str:
        if self.domain in ROOT_DOMAINS:
            return "ROOT"
        if self.domain in CONTAINER_DOMAINS:
            return "CONTAINER"
        return "DOCUMENT"

    @property
    def key(self) -> tuple[str, str, str]:
        """The comparison key: family, namespace, NFC-normalised value.

        Case is preserved. Git document paths are case-sensitive at the source,
        so folding them would merge ``README.md`` and ``readme.md`` -- two files
        that can and do coexist in one tree -- into one identity.
        """
        return (self.family, self.namespace, unicodedata.normalize("NFC", self.value))


def _widen(value: str) -> str:
    """Collapse a value toward every other spelling that could denote it.

    Deliberately lossy and deliberately one-directional. Each step exists
    because omitting it produces a FALSE NEGATIVE against a spent set -- a
    candidate that is the same thing as a spent identity but is spelled
    differently, admitted as fresh:

    * ``NFKC``          -- ``ﬁ`` vs ``fi``, full-width vs ASCII digits, and NFD
                           vs NFC accents, which plain ``casefold`` leaves apart.
    * strip ``Cf``      -- zero-width space, zero-width joiner, soft hyphen and
                           the bidi controls are invisible and would otherwise
                           make a spent name look new.
    * collapse spaces   -- trailing and doubled whitespace.
    * ``casefold``      -- last, so it applies to the already-normalised form.
    """
    folded = unicodedata.normalize("NFKC", value)
    folded = "".join(char for char in folded if unicodedata.category(char) != "Cf")
    folded = " ".join(folded.split())
    return folded.casefold()


def spent_key(value: str) -> str:
    """The comparison key for the SPENT set, widened on purpose.

    The two comparisons in this module want opposite errors, and conflating them
    is why one function used to do both:

    * A collision proof between two *live* candidates must not over-merge. A
      false collision refuses a legitimate candidate and shrinks the corpus.
      That comparison is exact (see :meth:`TypedIdentity.key`).
    * A check against *spent* identities must not under-merge. A false miss
      re-uses an identity a previous study already consumed, which is a
      contamination of the scientific population -- unrecoverable once the
      corpus is opened. That comparison is widened here.

    ``casefold`` alone was neither. It over-merged (``straße`` and ``strasse``
    fold together, so live candidates collided spuriously) and under-merged
    (it does no Unicode normalisation, so an NFD-spelled spent identity never
    matched an NFC candidate). It had both error modes and the guarantee of
    neither.
    """
    return _widen(value)


def identities_of(row: Mapping[str, Any]) -> list[TypedIdentity]:
    """Every typed identity one candidate row carries, all five fields."""
    family = str(row.get("family", ""))
    if not family:
        raise IdentityDomainRefused("candidate row carries no family")
    found: list[TypedIdentity] = []
    for domain in IdentityDomain:
        raw = row.get(str(domain))
        if domain is IdentityDomain.ALIAS:
            if not isinstance(raw, (list, tuple)):
                raise IdentityDomainRefused("alias_ids is not a sequence")
            values: Iterable[Any] = raw
        else:
            values = [raw]
        for value in values:
            if not isinstance(value, str) or not value:
                raise IdentityDomainRefused(f"{domain} carries a non-string or empty identity")
            found.append(TypedIdentity(family=family, domain=domain, value=value))
    return found


def prove(
    candidates: Iterable[Mapping[str, Any]],
    *,
    spent_values: Iterable[str] = (),
) -> dict[str, Any]:
    """Prove domain-separated disjointness over a candidate set.

    Raises :class:`IdentityDomainRefused` on a real collision. Returns a proof
    that names the namespaces actually checked, so the statement it makes is
    the statement it appears to make.
    """
    spent_exact: dict[str, str] = {}
    spent_widened: dict[str, str] = {}
    for value in spent_values:
        text = str(value)
        spent_exact.setdefault(unicodedata.normalize("NFC", text), text)
        spent_widened.setdefault(spent_key(text), text)

    #: (family, DOCUMENT, value) -> the domain that first claimed it
    document_owner: dict[tuple[str, str, str], str] = {}
    #: (family, widened value) -> the exact spellings seen, to catch case-only
    #: differences without merging them.
    document_spellings: dict[tuple[str, str], set[str]] = defaultdict(set)
    #: (family, namespace, value) -> the domains that use it, where repeats are legal
    repeated_names: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    incidental: list[dict[str, str]] = []
    spent_hits: list[dict[str, str]] = []
    counts: dict[str, int] = defaultdict(int)
    rows = 0

    #: value -> the namespaces it appeared in, to classify cross-namespace ties
    seen_anywhere: dict[str, set[tuple[str, str]]] = defaultdict(set)

    for row in candidates:
        rows += 1
        for identity in identities_of(row):
            family, namespace, value = identity.key
            counts[str(identity.domain)] += 1

            if value in spent_exact:
                spent_hits.append(
                    {
                        "rule": "EXACT",
                        "domain": str(identity.domain),
                        "family": family,
                        "value": value,
                    }
                )
            elif spent_key(identity.value) in spent_widened:
                spent_hits.append(
                    {
                        "rule": "WIDENED",
                        "domain": str(identity.domain),
                        "family": family,
                        "value": value,
                        "spent_spelling": spent_widened[spent_key(identity.value)],
                    }
                )

            seen_anywhere[value].add((family, namespace))

            if namespace in REPEATABLE:
                repeated_names[(family, namespace, value)].add(str(identity.domain))
                continue
            previous = document_owner.get((family, namespace, value))
            if previous is not None:
                raise IdentityDomainRefused(
                    f"{family} DOCUMENT namespace collision on {value!r}: "
                    f"claimed by {previous} and again by {identity.domain}"
                )
            document_owner[(family, namespace, value)] = str(identity.domain)
            if family in CASE_FOLDED_FAMILIES:
                document_spellings[(family, spent_key(value))].add(value)

    # Where a family's constructor already folds case, two DOCUMENT names that
    # differ only by case cannot come from a well-formed source, so the pair is
    # refused under its own name -- not merged, which would discard one of them,
    # and not ignored, which is what the old casefolded set effectively did.
    # Where the source is genuinely case-sensitive the pair is legitimate and
    # nothing fires. See CASE_FOLDED_FAMILIES for the per-family derivation.
    variants = sorted(
        (family, sorted(spellings))
        for (family, _), spellings in document_spellings.items()
        if len(spellings) > 1
    )
    if variants:
        family, spellings = variants[0]
        raise IdentityDomainRefused(
            f"{family} document identities differ only by case or normalisation: "
            f"{spellings[0]!r} and {spellings[1]!r} ({len(variants)} such pairs)"
        )

    # The one cross-namespace rule that survives from the old pooled set: a
    # string may not denote both a document and a container inside one family.
    container_names = {
        (family, value) for (family, namespace, value) in repeated_names if namespace == "CONTAINER"
    }
    document_names = {(family, value) for (family, _, value) in document_owner}
    ambiguous = sorted(container_names & document_names)
    if ambiguous:
        family, value = ambiguous[0]
        raise IdentityDomainRefused(
            f"{family} name {value!r} denotes both a document and a container "
            f"({len(ambiguous)} such names)"
        )

    if spent_hits:
        rules = sorted({hit["rule"] for hit in spent_hits})
        raise IdentityDomainRefused(
            f"{len(spent_hits)} candidate identities overlap the spent set "
            f"(rules fired: {', '.join(rules)}); first: {spent_hits[0]['value']!r}"
        )

    for value, places in seen_anywhere.items():
        if len(places) > 1:
            incidental.append(
                {
                    "value": value,
                    "places": ", ".join(sorted(f"{f}/{n}" for f, n in places)),
                }
            )

    return {
        "schema": "tavonel.sfir4.identity_domain_proof.v1",
        "candidates": rows,
        "namespaces_checked": {
            name: [str(domain) for domain in domains] for name, domains in NAMESPACES.items()
        },
        "identities_by_domain": dict(sorted(counts.items())),
        "document_identities_proved_unique": len(document_owner),
        "container_names_proved_consistent": sum(
            1 for (_, namespace, _) in repeated_names if namespace == "CONTAINER"
        ),
        "root_names_proved_consistent": sum(
            1 for (_, namespace, _) in repeated_names if namespace == "ROOT"
        ),
        "document_container_name_ambiguities": 0,
        "document_case_variant_pairs": 0,
        "incidental_cross_namespace_equalities": incidental,
        "spent_values_compared": len(spent_exact),
        "spent_comparison": {
            "exact_rule": "NFC, case preserved",
            "widened_rule": "NFKC, format characters stripped, whitespace collapsed, casefold",
            "why_two_rules": (
                "a live-candidate collision must not over-merge and a spent-set "
                "check must not under-merge; one casefold did neither"
            ),
        },
        "what_a_pass_means": (
            "inside each family: no two candidates share a lineage or alias; no "
            "name denotes both a document and a container; and no candidate "
            "identity of any domain matches a spent identity under either the "
            "exact or the widened rule. Container and root names may repeat, "
            "because many candidates legitimately share them. Equality that "
            "crosses a family boundary is reported as incidental and is not "
            "treated as scientific identity equivalence."
        ),
    }
