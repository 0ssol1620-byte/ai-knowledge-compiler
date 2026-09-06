"""Identity vs. change separation, per INC-V2-037.

`akc_cir.identity.normalize_text_for_identity` is documented in its own
docstring as a *lossy* fold built for one job: deciding whether a unit in a new
revision is the same logical thing as a unit in an old one. `akc_cir
.semantic_diff.diff_documents` nevertheless uses that fold's output —
`counterpart.identity_text != incoming.identity_text` — as the *entire* gate
for `MODIFIED_CLAIM`. All 14 of the SFI2 confirmed selective stale escapes
(`receipts/sfi2-native-provenance--20260823T085006Z-e53cc8aaeb7d.json`,
`rebuild.E5_confirmed_selective_stale_escape.confirmed`) are the same root
cause wearing different clothes: `Apache` -> `Apache(R)`, `Github` -> `GitHub`,
a spacing/punctuation edit, a hyphen replaced by an em dash. Every one of those
is correctly the *same unit* under identity continuity — the resolver must
keep matching them across revisions — and every one of them is a real,
compiled-relevant change that must not vanish from the rebuild set.

    Identity equivalence is not change equivalence.

This module is the separation. It answers "has this already-matched unit's
compiled-relevant state moved?" over a declared, closed set of facets, each of
which resolves independently to exactly one of four verdicts:

    CHANGED                     the facet's projection differs
    UNCHANGED                   the facet's projection agrees
    IGNORED_BY_PREDECLARED_POLICY   the caller declared this facet out of scope
                                 for this comparison, in advance, by name
    UNRESOLVED                  there is no data to compare it on

**Never CHANGED-or-UNCHANGED by default when data is missing.** A field that
was never populated on one side (or both) is `UNRESOLVED`, not `UNCHANGED` --
mapping "we do not know" to "no change" is exactly the defect class INC-V2-037
belongs to, one layer up. `IGNORED_BY_PREDECLARED_POLICY` exists for the
opposite situation: a facet a caller has decided, ahead of the comparison and
for a stated reason, does not apply -- e.g. `AUTHORITY_APPLICABILITY` for a
source family that carries no jurisdiction concept at all. It is passed in
explicitly as `ignored_facets`; it is never inferred from the data, because an
inferred "ignore" is indistinguishable from a bug that happens to produce
matching empty values.

**No import of any change decision from `akc_cir.semantic_diff`.** This module
does not call `diff_documents`, does not read `SemanticChange.kind`, and does
not read `UnitSnapshot.identity_text` -- reusing `semantic_diff`'s own answer
would make this module's agreement with it a tautology rather than evidence.
The only shared vocabulary is structural: `before`/`after` are duck-typed
against `UnitLike` below, which happens to be satisfiable by
`akc_cir.semantic_diff.UnitSnapshot` (and is, in `tests/test_change_facets.py`)
without this module importing that class at all.

**What this module does NOT establish**, spelled out because a shadow that
looks clean is the exact failure mode it exists to avoid papering over:

* It does not decide what the production system should do about a CHANGED
  verdict. It is a diagnostic projection, not a rebuild trigger; wiring it into
  `semantic_diff` or `recompilation` is a later rung on the ladder in
  `docs/COMPAT_IDENTITY_CHANGE_SEPARATION.md`, not this one.
* `ACCESSIBILITY` and `EXTERNAL_DEPENDENCY_EXECUTION` have no data source
  anywhere in `UnitSnapshot` today. They are declared facets -- dropping them
  from the partition would hide that compiled-relevant state exists that
  nothing here can see -- and every comparison reports them `UNRESOLVED`. That
  is a real, permanent limitation of the current unit representation, not a
  policy choice, so it is never reported as `IGNORED_BY_PREDECLARED_POLICY`.
* A facet resolving `UNCHANGED` means its own projection agreed. It says
  nothing about facets it does not cover (see `ACCESSIBILITY` above) and
  nothing about whether the two units are the *same logical unit* -- that is
  still identity's question, answered before this module is ever called.
"""

from __future__ import annotations

import unicodedata
from typing import Protocol

SCHEMA = "tavonel.v2.source_fact_ir.change_facets.v1"

# --------------------------------------------------------------------------
# the facet partition
# --------------------------------------------------------------------------

CONTENT = "CONTENT"
STRUCTURAL = "STRUCTURAL"
REFERENCE_LOCATOR = "REFERENCE_LOCATOR"
TEMPORAL = "TEMPORAL"
AUTHORITY_APPLICABILITY = "AUTHORITY_APPLICABILITY"
METADATA = "METADATA"
ACCESSIBILITY = "ACCESSIBILITY"
VISUAL = "VISUAL"
EXTERNAL_DEPENDENCY_EXECUTION = "EXTERNAL_DEPENDENCY_EXECUTION"

#: Ordered for stable receipts, not by importance. This tuple is the whole
#: partition: `change_facets()` always returns exactly this key set, never a
#: subset and never an extra key -- `test_change_facets.py` pins that.
FACETS: tuple[str, ...] = (
    CONTENT,
    STRUCTURAL,
    REFERENCE_LOCATOR,
    TEMPORAL,
    AUTHORITY_APPLICABILITY,
    METADATA,
    ACCESSIBILITY,
    VISUAL,
    EXTERNAL_DEPENDENCY_EXECUTION,
)

#: Facets `UnitSnapshot` (as constructed anywhere in this codebase today) has
#: no field for at all. Declared here, once, so both the resolver and the
#: tests that check "declared but permanently unresolved is honest, not a
#: silent gap" read the same list.
FACETS_WITHOUT_DATA_SOURCE: frozenset[str] = frozenset(
    {ACCESSIBILITY, EXTERNAL_DEPENDENCY_EXECUTION}
)

# --------------------------------------------------------------------------
# the verdict vocabulary
# --------------------------------------------------------------------------

CHANGED = "changed"
UNCHANGED = "unchanged"
IGNORED_BY_PREDECLARED_POLICY = "ignored_by_predeclared_policy"
UNRESOLVED = "unresolved"

VERDICTS: tuple[str, ...] = (CHANGED, UNCHANGED, IGNORED_BY_PREDECLARED_POLICY, UNRESOLVED)


class UnitLike(Protocol):
    """The attributes a matched-unit pair must expose. Structural, not nominal.

    `akc_cir.semantic_diff.UnitSnapshot` satisfies this today, but nothing in
    this module imports it or checks `isinstance` against it -- any object
    with these attributes works, which is what "independently derivable" means
    in practice: this module does not need `semantic_diff` to exist to be
    called.
    """

    text: str
    document_path: tuple[str, ...]
    anchor: str
    explicit_identifier: str
    evidence_id: str | None
    page_number1: int | None
    temporal_fingerprint: str
    metadata_fingerprint: str
    visual_fingerprint: str
    authority: str | None


def _optional(value: str | None) -> str | None:
    """Treat an unset sentinel (`None` or `""`) as "no data", not as a value."""
    return value if value else None


def _compare_optional(before: object | None, after: object | None) -> str:
    """`UNRESOLVED` unless both sides actually carried a value to compare."""
    if before is None or after is None:
        return UNRESOLVED
    return CHANGED if before != after else UNCHANGED


def _content_projection(unit: UnitLike) -> str:
    """NFC only -- canonical-form encoding noise is not a content change.

    Deliberately *not* `normalize_text_for_identity`: that fold is what erased
    the 14 SFI2 cases in the first place (casefold, punctuation-to-space,
    whitespace-collapse). NFC only undoes an encoder's choice between a
    precomposed codepoint and a base character plus a combining mark for the
    *same* visual text -- it does not fold case, does not touch punctuation,
    and does not collapse whitespace. `Apache` vs `Apache(R)` differ under NFC
    (different codepoints); two encodings of the same accented letter do not.
    """
    return unicodedata.normalize("NFC", unit.text)


def _structural_projection(unit: UnitLike) -> tuple[str, ...]:
    """Position and locator label, excluding the shared source-id prefix.

    `document_path`'s first element is the source id, shared by construction
    by any pair this module is ever called on (matched units are, by
    definition, from the same source) -- including it would make every
    STRUCTURAL comparison spuriously sensitive to which source-id string a
    caller happened to pass, never to a structural fact about the unit itself.
    `neighbour_anchors` is deliberately not projected here either: it is an
    identity-*resolution* signal (a hint to `LogicalIdentityResolver`, not a
    property this unit owns), and folding a neighbouring unit's edit into this
    unit's own STRUCTURAL verdict would make "did this unit's position change"
    depend on an unrelated unit's text.
    """
    return (*unit.document_path[1:], unit.anchor, unit.explicit_identifier)


def _locator_projection(unit: UnitLike) -> tuple[str, int | None] | None:
    if unit.evidence_id is None:
        return None
    return (unit.evidence_id, unit.page_number1)


def change_facets(
    before: UnitLike,
    after: UnitLike,
    *,
    ignored_facets: frozenset[str] = frozenset(),
) -> dict[str, str]:
    """Per-facet verdict for one matched unit pair.

    Total over `FACETS`: every call returns exactly the nine declared keys,
    each mapped to one of `VERDICTS`. `ignored_facets` names, in advance,
    which of `FACETS` the caller has decided do not apply to this comparison
    (see the module docstring's `AUTHORITY_APPLICABILITY` example) -- any
    facet named there resolves `IGNORED_BY_PREDECLARED_POLICY` regardless of
    what data is present, because the declaration is what makes it a policy
    rather than an inference.
    """
    unknown = ignored_facets - set(FACETS)
    if unknown:
        raise ValueError(f"not a declared facet: {sorted(unknown)}")

    verdicts: dict[str, str] = {}
    for facet in FACETS:
        if facet in ignored_facets:
            verdicts[facet] = IGNORED_BY_PREDECLARED_POLICY
        elif facet in FACETS_WITHOUT_DATA_SOURCE:
            verdicts[facet] = UNRESOLVED
        elif facet == CONTENT:
            before_v, after_v = _content_projection(before), _content_projection(after)
            verdicts[facet] = CHANGED if before_v != after_v else UNCHANGED
        elif facet == STRUCTURAL:
            before_v, after_v = _structural_projection(before), _structural_projection(after)
            verdicts[facet] = CHANGED if before_v != after_v else UNCHANGED
        elif facet == REFERENCE_LOCATOR:
            verdicts[facet] = _compare_optional(
                _locator_projection(before), _locator_projection(after)
            )
        elif facet == TEMPORAL:
            verdicts[facet] = _compare_optional(
                _optional(before.temporal_fingerprint), _optional(after.temporal_fingerprint)
            )
        elif facet == AUTHORITY_APPLICABILITY:
            verdicts[facet] = _compare_optional(before.authority, after.authority)
        elif facet == METADATA:
            verdicts[facet] = _compare_optional(
                _optional(before.metadata_fingerprint), _optional(after.metadata_fingerprint)
            )
        elif facet == VISUAL:
            verdicts[facet] = _compare_optional(
                _optional(before.visual_fingerprint), _optional(after.visual_fingerprint)
            )
        else:  # pragma: no cover -- FACETS is closed and every member is handled above
            raise KeyError(f"no resolver wired for declared facet {facet!r}")

    assert set(verdicts) == set(FACETS)  # the partition invariant, checked every call
    return verdicts


def facets_with_verdict(verdicts: dict[str, str], verdict: str) -> tuple[str, ...]:
    """Convenience filter, e.g. `facets_with_verdict(v, CHANGED)`."""
    if verdict not in VERDICTS:
        raise ValueError(f"not a declared verdict: {verdict!r}")
    return tuple(facet for facet in FACETS if verdicts[facet] == verdict)
