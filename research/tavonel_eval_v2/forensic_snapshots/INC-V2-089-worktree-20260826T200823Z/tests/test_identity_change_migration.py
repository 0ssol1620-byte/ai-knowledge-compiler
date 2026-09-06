"""Adversarial controls and the anti-drift binding for the INC-V2-037 switch.

Rungs 2 and 4 of `docs/COMPAT_IDENTITY_CHANGE_SEPARATION.md`.
`tools/identity_change_benchmark.py` measures what the switch costs on real
revision history. This module covers the two things a corpus cannot: cases
built specifically to make the new predicate wrong in *both* directions, and a
binding that keeps the copy of the CONTENT facet living in
`akc_cir.semantic_diff` from drifting away from `source_fact_ir/change_facets.py`.

**Why there are two copies at all.** `change_facets.py` lives in the research
tree and `akc_cir` is a package; a package importing `research/` would be the
wrong dependency direction, and the founder's instruction was to say so and port
instead. Two implementations of one rule diverge silently unless something
compares them, which is what `test_the_ported_content_facet_never_drifts_*`
below is for -- run over hand-built adversarial pairs *and* over real corpus
pairs, because agreement on cases chosen by the author of both copies is weak
evidence.

**What "formatting-only" actually means here, and why it is narrower than it
sounds.** The intuitive reading of "formatting-only churn must stay unchanged"
includes recasing, re-spacing and punctuation swaps. Under the declared
contract it does not, and it must not: `Github` -> `GitHub` and `Apache` ->
`Apache(R)` are two of the 14 confirmed selective stale escapes, and neither is
distinguishable from "harmless recasing" by any rule that does not also
re-admit the escapes. The only difference class the contract calls
information-free is Unicode canonical form -- an encoder's choice between a
precomposed codepoint and a base character plus a combining mark for the same
visible text. That is the boundary the controls below pin, in both directions.
"""

from __future__ import annotations

import json
import sys
import unicodedata
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
for _sub in ("tools", "acquisition", "canonicalization", "compiler", "source_fact_ir"):
    sys.path.insert(0, str(NS / _sub))
sys.path.insert(0, str(NS))
ROOT = NS.parents[1]
sys.path.insert(0, str(ROOT / "packages" / "cir-python" / "src"))

import change_facets as facets  # noqa: E402
import identity_change_benchmark as bench  # noqa: E402
from akc_cir.semantic_diff import (  # noqa: E402
    ChangeFacetVerdict,
    ChangeKind,
    DiffLevel,
    DocumentShape,
    UnitSnapshot,
    content_facet_verdict,
    diff_documents,
)

A = "sha256:" + "a" * 64
B = "sha256:" + "b" * 64

CLAUSE = "The warranty covers parts and labour for two years from delivery."


def _unit(text, *, logical_id="ku_warranty", **overrides) -> UnitSnapshot:
    fields = {
        "logical_id": logical_id,
        "text": text,
        "document_path": ("src_one", "Warranty", "Coverage"),
        "anchor": "4.2 Exceptions",
        "neighbour_anchors": ("4.1 Scope", "4.3 Claims"),
        "evidence_id": "ev_one",
        "page_number1": 17,
        "explicit_identifier": "Warranty/Coverage",
    }
    fields.update(overrides)
    return UnitSnapshot(**fields)


def _diff(before_units, after_units, *, legacy=False):
    return diff_documents(
        before_sha256=A,
        after_sha256=B,
        level=DiffLevel.SEMANTIC,
        before_shape=DocumentShape(),
        after_shape=DocumentShape(),
        before_units=before_units,
        after_units=after_units,
        source="src_one",
        legacy_identity_change_predicate=legacy,
    )


def _modified(diff) -> list:
    return [c for c in diff.changes if c.kind is ChangeKind.MODIFIED_CLAIM]


# --------------------------------------------------------------------------
# the adversarial pair table
#
# `expect_changed` is the CONTENT verdict the *declared contract* requires,
# written down before the implementation is consulted. `outcome` is what
# `diff_documents` must do with the pair end to end, which is not always the
# same question: identity is asked first, and a pair identity declines to
# settle never reaches the change predicate at all. A case whose intuitive
# answer and contractual answer differ carries a `why`, because those are the
# cases where a future reader is most likely to "fix" the contract back into
# the defect.
#
# `outcome` values:
#   "modified"            a MODIFIED_CLAIM is emitted for the pair
#   "unchanged"           the pair matched and no MODIFIED_CLAIM was emitted
#   "identity_unresolved" identity declined the match, so the change predicate
#                         was never consulted -- the pre-existing fail-closed
#                         path, and still the right answer
# --------------------------------------------------------------------------

ADVERSARIAL: tuple[tuple[str, str, str, bool, str, str], ...] = (
    (
        "identical",
        CLAUSE,
        CLAUSE,
        False,
        "the floor: no difference of any kind",
        "unchanged",
    ),
    (
        "nfc_vs_nfd",
        "The garantía covers parts for two years.",
        unicodedata.normalize("NFD", "The garantía covers parts for two years."),
        False,
        "the only information-free class the contract names: one encoder chose "
        "a precomposed codepoint, the other a base plus combining mark, for the "
        "same visible text",
        "unchanged",
    ),
    (
        "nfd_vs_nfc_reversed",
        unicodedata.normalize("NFD", "The garantía covers parts for two years."),
        "The garantía covers parts for two years.",
        False,
        "the same case in the other direction; a fold that is not symmetric "
        "would make the verdict depend on which revision arrived first",
        "unchanged",
    ),
    (
        "registered_trademark_added",
        "This describes Apache Druid's storage.",
        "This describes Apache® Druid's storage.",
        True,
        "one of the 14 confirmed escapes; NFKC folds (R) toward nothing useful "
        "here and the identity fold drops it as punctuation",
        "modified",
    ),
    (
        "recasing_of_a_proper_noun",
        "Enable two-factor authorization on Github.",
        "Enable two-factor authorization on GitHub.",
        True,
        "one of the 14 confirmed escapes, and the reason 'case is only "
        "formatting' cannot be a rule here",
        "modified",
    ),
    (
        "hyphen_to_em_dash",
        "Schedule of ratings - hemic and lymphatic systems.",
        "Schedule of ratings—hemic and lymphatic systems.",
        True,
        "one of the 14 confirmed escapes; the identity fold maps both to a space",
        "modified",
    ),
    (
        "spacing_inside_a_citation",
        "limited by man-made barriers ( e.g., fences) or substantially.",
        "limited by man-made barriers (e.g., fences) or substantially.",
        True,
        "one of the 14 confirmed escapes; whitespace collapse erased it",
        "modified",
    ),
    (
        "real_change_buried_in_heavy_formatting_churn",
        "  the warranty covers parts and labour for TWO years from delivery.  ",
        "The  warranty   covers parts, and labour for three years from delivery!",
        True,
        "the direction that matters most: a genuine two -> three edit wrapped in "
        "recasing, re-spacing and punctuation churn must not be lost in the noise",
        "modified",
    ),
    (
        "formatting_churn_with_no_content_change",
        "  the warranty covers parts and labour for two years from delivery.  ",
        "The  warranty   covers parts, and labour for two years from delivery!",
        True,
        "CONTRACTUALLY CHANGED, and this is the price of the fix stated as a "
        "test: the codepoints differ, so CONTENT fires. Any rule that would "
        "call this unchanged is the rule that lost the 14 escapes",
        "modified",
    ),
    (
        "zero_width_space_removed",
        "found in the area of ​​the municipality.",
        "found in the area of the municipality.",
        True,
        "invisible characters are still characters; NFC does not remove them, "
        "and a caller who wants them ignored must declare that, not inherit it",
        "modified",
    ),
    (
        "both_empty",
        "",
        "",
        False,
        "empty is a value both sides carried, not missing data -- CONTENT "
        "resolves unchanged, though identity never asks: two units with no "
        "text at all give the resolver no text signal to settle on, so it "
        "declines and the pair fails closed one layer up",
        "identity_unresolved",
    ),
    (
        "empty_becomes_content",
        "",
        CLAUSE,
        True,
        "a unit that gained its text is a content change, not an absence",
        # Identity scores this pair 0.84, inside its review band, and declines
        # to settle it -- so the change predicate is never consulted. Recorded
        # as the contract's answer rather than argued with: an unsettled
        # identity already fails closed in `plan_recompilation`, and calling it
        # a modification would assert a continuity nobody established.
        "identity_unresolved",
    ),
    (
        "content_becomes_empty",
        CLAUSE,
        "",
        True,
        "and the same in reverse: emptied is not unchanged",
        "identity_unresolved",
    ),
)


@pytest.mark.parametrize(
    "name,before,after,expect_changed,why,outcome",
    ADVERSARIAL,
    ids=[row[0] for row in ADVERSARIAL],
)
def test_adversarial_content_verdicts_match_the_declared_contract(
    name, before, after, expect_changed, why, outcome
) -> None:
    del outcome
    verdict = content_facet_verdict(_unit(before), _unit(after))
    expected = ChangeFacetVerdict.CHANGED if expect_changed else ChangeFacetVerdict.UNCHANGED
    assert verdict is expected, f"{name}: {why}"


@pytest.mark.parametrize(
    "name,before,after,expect_changed,why,outcome",
    ADVERSARIAL,
    ids=[row[0] for row in ADVERSARIAL],
)
def test_the_ported_content_facet_never_drifts_on_adversarial_cases(
    name, before, after, expect_changed, why, outcome
) -> None:
    """The copy in `akc_cir` against the original in the research tree.

    `change_facets.change_facets()` returns plain strings and
    `content_facet_verdict` returns a `StrEnum` whose values are those same
    strings, so this compares the two answers without a translation table that
    could itself be where the drift hides.
    """
    del expect_changed, why, outcome
    ported = content_facet_verdict(_unit(before), _unit(after))
    original = facets.change_facets(_unit(before), _unit(after))[facets.CONTENT]
    assert ported.value == original, name


@pytest.mark.parametrize(
    "name,before,after,expect_changed,why,outcome",
    ADVERSARIAL,
    ids=[row[0] for row in ADVERSARIAL],
)
def test_adversarial_pairs_reach_diff_documents_with_the_declared_outcome(
    name, before, after, expect_changed, why, outcome
) -> None:
    """The facet is not the product; `diff_documents`' answer is.

    A verdict that is right in isolation and never reaches `MODIFIED_CLAIM`
    would fix nothing, so every control is also run end to end through the
    production entry point.

    The end-to-end answer is not always the facet's answer, and the gap is not
    a defect: identity is asked first, and two of these pairs (`""` gaining or
    losing its whole text) score inside the resolver's review band, so it
    declines to settle them and the change predicate is never reached. Those
    still fail closed, as `IDENTITY_UNRESOLVED` rather than as a modification,
    which is the rule `semantic_diff` already existed to hold.
    """
    del why
    diff = _diff([_unit(before)], [_unit(after)])
    kinds = {c.kind for c in diff.changes}

    if outcome == "identity_unresolved":
        assert ChangeKind.IDENTITY_UNRESOLVED in kinds, name
        assert _modified(diff) == [], name
        # The facet still says what it says; identity simply got there first.
        assert (
            content_facet_verdict(_unit(before), _unit(after))
            is (ChangeFacetVerdict.CHANGED if expect_changed else ChangeFacetVerdict.UNCHANGED)
        ), name
        return

    assert ChangeKind.IDENTITY_UNRESOLVED not in kinds, name
    assert bool(_modified(diff)) is (outcome == "modified"), name
    assert (outcome == "modified") is expect_changed, name


# --------------------------------------------------------------------------
# identity continuity -- the regression the fix must not create
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,before,after,expect_changed,why,outcome",
    ADVERSARIAL,
    ids=[row[0] for row in ADVERSARIAL],
)
def test_no_adversarial_pair_is_turned_into_an_add_plus_remove(
    name, before, after, expect_changed, why, outcome
) -> None:
    """Whatever the change verdict, the unit must still be the same unit.

    This is the failure that would make the cure worse than the disease: a
    change predicate that reached back into matching would trade 14 missed
    changes for a severed revision history on every pair it touched.
    """
    del expect_changed, why, outcome
    diff = _diff([_unit(before)], [_unit(after)])
    kinds = {c.kind for c in diff.changes}
    assert ChangeKind.UNIT_ADDED not in kinds, name
    assert ChangeKind.UNIT_REMOVED not in kinds, name


def test_the_change_predicate_cannot_influence_matching_at_all() -> None:
    """Same inputs, both predicates: every non-content record is identical.

    Additions, removals, unsettled identities and locator movement are decided
    upstream of the content question, so switching the content question must
    leave them byte-identical. The corpus benchmark measures this same equality
    over 538 real pairs; this is the unit-level statement of it.
    """
    before = [_unit(CLAUSE, logical_id="ku_one"), _unit("A second clause.", logical_id="ku_two")]
    after = [
        _unit("  THE WARRANTY covers parts and labour for two years from delivery. ", logical_id="ku_one"),
        _unit("A third clause entirely.", logical_id="ku_three"),
    ]

    old = _diff(before, after, legacy=True)
    new = _diff(before, after)

    def _non_content(diff):
        return [c.as_record() for c in diff.changes if c.kind is not ChangeKind.MODIFIED_CLAIM]

    assert _non_content(old) == _non_content(new)


# --------------------------------------------------------------------------
# malformed and absent data -- unknown must never become unchanged
# --------------------------------------------------------------------------


def test_a_non_string_text_is_unresolved_not_unchanged() -> None:
    """The fail-closed rule at the facet level.

    `UnitSnapshot.text` is declared `str`; this is what happens when an adapter
    breaks that declaration. Mapping it to `unchanged` would be exactly the
    INC-V2-037 defect class -- an absence read as agreement -- one layer down.
    """
    assert (
        content_facet_verdict(_unit(None), _unit(CLAUSE)) is ChangeFacetVerdict.UNRESOLVED
    )
    assert (
        content_facet_verdict(_unit(CLAUSE), _unit(None)) is ChangeFacetVerdict.UNRESOLVED
    )
    assert content_facet_verdict(_unit(None), _unit(None)) is ChangeFacetVerdict.UNRESOLVED


def test_an_unresolved_content_facet_fails_closed_as_a_modification() -> None:
    """Fail-closed at the seam `diff_documents` actually uses.

    Driven through the module-level predicate rather than through
    `diff_documents`, because of the limitation the next test records: a `None`
    text never survives long enough to reach this branch by that route. What is
    pinned here is that the branch answers `modified`-shaped rather than
    `unchanged`-shaped when it is reached, and says why.
    """
    verdict = content_facet_verdict(_unit(CLAUSE), _unit(None))
    assert verdict is ChangeFacetVerdict.UNRESOLVED
    assert verdict is not ChangeFacetVerdict.UNCHANGED


def test_a_none_text_never_reaches_the_change_predicate_at_all() -> None:
    """A limitation of the switch, recorded rather than papered over.

    `diff_documents` fingerprints every unit before it compares any of them,
    and `normalize_text_for_identity` raises `TypeError` on a non-`str`. So the
    CONTENT-facet `UNRESOLVED` branch in `diff_documents` is **unreachable via
    a `None` text**: identity crashes first.

    That is not a hole this lane may close. `identity.py` is another lane's
    file, and softening `normalize_text_for_identity` to tolerate `None` would
    be a change to identity semantics made for a change-detection reason --
    exactly the coupling INC-V2-037 is about. The branch stays because
    `content_facet_verdict` is public and callable directly, and because a
    fail-closed default at a fail-closed boundary is correct even when the
    current caller cannot reach it. It is not claimed to be exercised on the
    production path, and this test is what stops that claim being made by
    accident later.
    """
    with pytest.raises(TypeError):
        _diff([_unit(CLAUSE)], [_unit(None)])


def test_facets_with_no_data_source_stay_unresolved_and_never_unchanged() -> None:
    """The two permanently-unresolved facets, and the absent fingerprints.

    A unit built by `selective_build.snapshots` populates none of the temporal,
    metadata, visual or authority fields. Those facets must report that they
    could not be compared -- not that they agreed.
    """
    verdicts = facets.change_facets(_unit(CLAUSE), _unit(CLAUSE))
    for facet in (
        facets.ACCESSIBILITY,
        facets.EXTERNAL_DEPENDENCY_EXECUTION,
        facets.TEMPORAL,
        facets.METADATA,
        facets.VISUAL,
        facets.AUTHORITY_APPLICABILITY,
    ):
        assert verdicts[facet] == facets.UNRESOLVED, facet
    assert verdicts[facets.CONTENT] == facets.UNCHANGED


# --------------------------------------------------------------------------
# under-fire -- the direction that must be empty, and why
# --------------------------------------------------------------------------

_UNDER_FIRE_PROBES: tuple[tuple[str, str], ...] = (
    (CLAUSE, CLAUSE.upper()),
    (CLAUSE, CLAUSE + "  "),
    ("a-b", "a—b"),
    ("½ cup", "1/2 cup"),
    ("ﬁle", "file"),
    ("Aé", "Aé"),
    ("x", "ｘ"),
    ("", " "),
    ("(a)", "( a )"),
    ("Apache", "Apache®"),
)


@pytest.mark.parametrize("before,after", _UNDER_FIRE_PROBES)
def test_the_new_predicate_never_misses_what_the_old_one_caught(before, after) -> None:
    """Under-fire is impossible, and here is the argument checked case by case.

    NFKC factors through NFC: `NFKC(x) == NFKC(NFC(x))`. So if two texts have
    equal NFC forms they have equal NFKC forms, hence equal identity folds.
    Contrapositive: whenever the identity folds differ -- which is exactly when
    the old predicate fired -- the NFC forms differ too, so the new one fires.
    The new predicate's `unchanged` set is a strict subset of the old one's.

    The probes above are chosen to attack that argument: compatibility
    decompositions (1/2, the fi ligature, fullwidth x) are precisely where NFKC
    and NFC disagree, and are the only place a counterexample could live.
    """
    old_fired = _unit(before).identity_text != _unit(after).identity_text
    new_fired = (
        content_facet_verdict(_unit(before), _unit(after)) is not ChangeFacetVerdict.UNCHANGED
    )
    assert not (old_fired and not new_fired), (
        f"under-fire: old predicate caught {before!r} -> {after!r}, new one did not"
    )


def test_the_legacy_predicate_stays_reachable_for_rollback() -> None:
    """Rung 4's escape hatch, and a demonstration that it is really the old one."""
    before, after = [_unit("Apache Druid")], [_unit("Apache® Druid")]
    assert _modified(_diff(before, after)) != []
    assert _modified(_diff(before, after, legacy=True)) == []


# --------------------------------------------------------------------------
# the binding, run over real corpus pairs rather than hand-built ones
# --------------------------------------------------------------------------

_CORPUS_SLICE = 40


def _corpus_pairs(limit: int):
    """Matched unit pairs from real cached revisions, or nothing if uncached."""
    for name, acquisition_path, lineages_path, cache_root in bench.COHORTS:
        if not acquisition_path.exists() or not lineages_path.exists():
            continue
        if not (cache_root / "payloads").exists():
            continue
        admitted = json.loads(acquisition_path.read_text(encoding="utf-8"))["admitted"]
        lineages = {
            row["lineage_id"]: row
            for row in json.loads(lineages_path.read_text(encoding="utf-8"))["lineages"]
        }
        cache = bench.PayloadCache(cache_root, extractor_digest="identity-change-binding")
        for row in admitted[:limit]:
            lineage = lineages.get(row["lineage_id"])
            if lineage is None:
                continue
            try:
                before_raw = bench.fetch_payload(cache, lineage, row["before_version"])
                after_raw = bench.fetch_payload(cache, lineage, row["after_version"])
            except (bench.CacheMiss, bench.UnsupportedFamily):
                continue
            before_doc = bench.build_document(lineage, row["before_version"], before_raw)
            after_doc = bench.build_document(lineage, row["after_version"], after_raw)
            before_units, _ = bench.engine.snapshots(before_doc)
            after_units, _ = bench.engine.snapshots(after_doc)
            yield from bench.matched_pairs(
                before_units, after_units, after_doc["source_id"]
            )


def test_the_ported_content_facet_never_drifts_on_real_corpus_pairs() -> None:
    """Agreement on cases the author chose is weak evidence; this is the rest.

    Skipped rather than silently passed when the payload caches are absent --
    a binding test that quietly compares nothing is worse than no binding test,
    because the suite still goes green.
    """
    compared = 0
    for before_unit, after_unit in _corpus_pairs(_CORPUS_SLICE):
        ported = content_facet_verdict(before_unit, after_unit)
        original = facets.change_facets(before_unit, after_unit)[facets.CONTENT]
        assert ported.value == original, before_unit.logical_id
        compared += 1

    if compared == 0:
        pytest.skip("no cached revision payloads in this checkout to bind against")
    assert compared > 100, f"only {compared} real pairs compared; the slice is too thin"
