"""Lane 4 — fingerprint, dependency path, and the alignment invariant.

These tests guard the property, not the arithmetic. The property is that a
typed delta cannot stay silent about an artifact a clean rebuild moved, and the
three ways it could fail quietly are each pinned here:

* a fingerprint that is secretly a function of the witness, so a fact that only
  moved in the file looks changed and a fact that changed looks moved;
* a REFERENTIAL fact whose unit text is byte-identical invalidating nothing,
  which is INC-V2-006 and three of the four confirmed stale escapes;
* a derived-membership artifact invalidated from a structural verdict about the
  document rather than from membership, which is the fourth.

Facts are constructed inline. Lanes 2 and 3 do not need to exist for the chain's
last two links to be checkable, and making this file depend on them would mean
the invariant could only be tested once the thing it guards already shipped.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(NS))

from source_fact_ir import fingerprint as fp  # noqa: E402
from source_fact_ir import ir  # noqa: E402

SOURCE = "lineage:p4c/example"
UNIT_PATH = (SOURCE, "1", "1.2")
OTHER_UNIT_PATH = (SOURCE, "2")

DOC = fp.document_key(SOURCE)
UNIT = fp.unit_key(SOURCE, UNIT_PATH[1:])
OTHER_UNIT = fp.unit_key(SOURCE, OTHER_UNIT_PATH[1:])


def witness(
    construct: str = "paragraph",
    *,
    start: int = 100,
    end: int = 200,
    unit_path: tuple[str, ...] = UNIT_PATH,
) -> ir.Witness:
    return ir.Witness(
        construct=construct, byte_start=start, byte_end=end, unit_path=unit_path
    )


def represented(kind: str, representation: object, **kwargs: object) -> ir.SourceFact:
    return ir.SourceFact(
        kind=kind,
        witness=kwargs.pop("witness", witness()),  # type: ignore[arg-type]
        state=ir.REPRESENTED,
        representation=representation,
        **kwargs,  # type: ignore[arg-type]
    )


# --- 1. fingerprint is a property of the representation --------------------


def test_fingerprint_ignores_dict_key_order_and_construction() -> None:
    left = represented(ir.APPLICABILITY, {"jurisdiction": "EU", "scope": "retail"})
    right = represented(ir.APPLICABILITY, dict(scope="retail", jurisdiction="EU"))
    assert fp.fingerprint(left) == fp.fingerprint(right)

    nested_a = represented(ir.AUTHORITY, {"b": {"y": 2, "x": 1}, "a": [1, 2]})
    nested_b = represented(ir.AUTHORITY, {"a": [1, 2], "b": {"x": 1, "y": 2}})
    assert fp.fingerprint(nested_a) == fp.fingerprint(nested_b)


def test_fingerprint_moves_when_the_representation_moves() -> None:
    before = represented(ir.REFERENCE_TARGET, {"target": "#clause-4"})
    after = represented(ir.REFERENCE_TARGET, {"target": "#clause-5"})
    assert fp.fingerprint(before) != fp.fingerprint(after)


def test_fingerprint_distinguishes_kinds_with_equal_representations() -> None:
    text = represented(ir.CONTENT_TEXT, "x")
    language = represented(ir.LANGUAGE, "x")
    assert fp.fingerprint(text) != fp.fingerprint(language)


# --- 2. fingerprint is not a function of the witness -----------------------


def test_fingerprint_is_not_a_function_of_byte_offsets() -> None:
    """A paragraph inserted above must not restate every fact below it."""
    early = represented(
        ir.CONTENT_TEXT, "the same words", witness=witness(start=10, end=24)
    )
    late = represented(
        ir.CONTENT_TEXT, "the same words", witness=witness(start=9000, end=9014)
    )
    assert fp.fingerprint(early) == fp.fingerprint(late)
    # ...and identity does move, which is what makes them two facts rather than
    # one fact that teleported.
    assert early.fact_id != late.fact_id


def test_fingerprint_is_not_a_function_of_surrounding_text() -> None:
    plain = represented(
        ir.LOCATOR, "s3://bucket/a", witness=ir.Witness("a", 0, 10, "", UNIT_PATH)
    )
    with_excerpt = represented(
        ir.LOCATOR,
        "s3://bucket/a",
        witness=ir.Witness("a", 0, 10, "wholly different context here", UNIT_PATH),
    )
    assert fp.fingerprint(plain) == fp.fingerprint(with_excerpt)


# --- 3. a REFERENTIAL fact whose unit text did not move --------------------


def test_referential_change_invalidates_the_unit_artifact() -> None:
    """The anchor text is identical; only the target moved. INC-V2-006."""
    before = [
        represented(ir.CONTENT_TEXT, "see the annex", witness=witness(start=0, end=13)),
        represented(
            ir.REFERENCE_TARGET,
            {"anchor": "the annex", "target": "#annex-a"},
            witness=witness("link", start=8, end=13),
        ),
    ]
    after = [
        represented(ir.CONTENT_TEXT, "see the annex", witness=witness(start=0, end=13)),
        represented(
            ir.REFERENCE_TARGET,
            {"anchor": "the annex", "target": "#annex-b"},
            witness=witness("link", start=8, end=13),
        ),
    ]
    typed = fp.delta(before, after)

    assert [entry.kind for entry in typed.changed] == [ir.REFERENCE_TARGET]
    assert typed.changed[0].channel == ir.REFERENTIAL
    keys = typed.changed[0].dependency_keys
    assert keys, "a REFERENTIAL fact that invalidates nothing is the escape itself"
    assert fp.SECTION_PREFIX + UNIT in keys


def test_a_document_scoped_fact_still_reaches_membership() -> None:
    fact = represented(
        ir.LANGUAGE, "de", witness=witness(unit_path=(SOURCE,))
    )
    keys = fp.dependency_keys(fact)
    assert fp.DOCUMENT_INDEX_PREFIX + DOC in keys
    assert not any(key.startswith(fp.SECTION_PREFIX) for key in keys)


def test_an_unanchored_fact_refuses_rather_than_invalidating_nothing() -> None:
    fact = ir.SourceFact(
        kind=ir.CONTENT_TEXT,
        witness=ir.Witness("paragraph", 0, 5),
        state=ir.REPRESENTED,
        representation="hello",
    )
    with pytest.raises(fp.UnanchoredFact):
        fp.dependency_keys(fact)


# --- 4. delta matches by fact_id -------------------------------------------


def test_a_changed_value_is_changed_not_removed_and_added() -> None:
    before = [represented(ir.CONTENT_TEXT, "clause as written")]
    after = [represented(ir.CONTENT_TEXT, "clause as amended")]
    typed = fp.delta(before, after)

    assert len(typed.changed) == 1
    assert not typed.added
    assert not typed.removed
    entry = typed.changed[0]
    assert entry.fact_id == before[0].fact_id == after[0].fact_id
    assert entry.fingerprint_before != entry.fingerprint_after


def test_a_state_fall_is_a_change_even_with_no_representation_either_side() -> None:
    """REPRESENTED -> RECOGNIZED_BUT_UNREPRESENTED is a loss and must be visible."""
    before = [represented(ir.INCLUDE_TARGET, {"include": "part-2"})]
    after = [
        ir.SourceFact(
            kind=ir.INCLUDE_TARGET,
            witness=witness(),
            state=ir.UNREPRESENTED,
            reason="transclusion target is not compiled",
        )
    ]
    typed = fp.delta(before, after)
    assert len(typed.changed) == 1
    assert typed.changed[0].state_before == ir.REPRESENTED
    assert typed.changed[0].state_after == ir.UNREPRESENTED


def test_unchanged_facts_are_reported_and_invalidate_nothing() -> None:
    facts = [represented(ir.CONTENT_TEXT, "stable")]
    typed = fp.delta(facts, list(facts))
    assert len(typed.unchanged) == 1
    assert typed.invalidate == ()


# --- 5. membership, decided from membership --------------------------------


def test_membership_artifacts_are_invalidated_without_any_structural_fact() -> None:
    """The fourth escape: membership decided from a structural verdict.

    Nothing here travels the STRUCTURAL channel. The derived-membership
    artifacts must still be named.
    """
    before = [represented(ir.REFERENCE_TARGET, {"target": "#a"}, witness=witness("link"))]
    after = [represented(ir.REFERENCE_TARGET, {"target": "#b"}, witness=witness("link"))]
    typed = fp.delta(before, after)

    assert all(entry.channel == ir.REFERENTIAL for entry in typed.moved)
    assert not any(entry.channel == ir.STRUCTURAL for entry in typed.moved)
    assert fp.DOCUMENT_INDEX_PREFIX + DOC in typed.invalidate
    assert fp.STRUCTURE_MAP_PREFIX + DOC in typed.invalidate
    assert sum(
        1 for key in typed.invalidate if key.startswith(fp.TOPIC_BUCKET_PREFIX)
    ) == fp.BUCKET_COUNT


def test_a_reordered_unit_set_invalidates_membership() -> None:
    before = [
        represented(ir.CONTENT_TEXT, "one", witness=witness(start=0, end=3)),
        represented(
            ir.CONTENT_TEXT,
            "two",
            witness=witness(start=10, end=13, unit_path=OTHER_UNIT_PATH),
        ),
    ]
    after = [
        represented(
            ir.CONTENT_TEXT,
            "two",
            witness=witness(start=0, end=3, unit_path=OTHER_UNIT_PATH),
        ),
        represented(ir.CONTENT_TEXT, "one", witness=witness(start=10, end=13)),
    ]
    typed = fp.delta(before, after)
    assert fp.DOCUMENT_INDEX_PREFIX + DOC in typed.invalidate
    assert fp.SECTION_PREFIX + UNIT in typed.invalidate
    assert fp.SECTION_PREFIX + OTHER_UNIT in typed.invalidate


def test_artifact_key_shapes_match_the_production_recompiler() -> None:
    """The key derivation is mirrored from selective_build, not imported.

    That duplication is the risk this test exists to hold down: if the artifact
    spec moves, both files move or this goes red. Deliberately no skip guard —
    an unimportable recompiler means the mirror is unverified, and an unverified
    mirror is the failure, not an excuse to pass.
    """
    sys.path.insert(0, str(NS / "compiler"))
    import selective_build

    assert selective_build.doc_key(SOURCE) == DOC
    assert selective_build.logical_id(SOURCE, list(UNIT_PATH[1:])) == UNIT
    assert selective_build.bucket_of(UNIT) == fp.bucket_of(UNIT)

    assert UNIT.startswith("u:")
    assert len(UNIT) == 2 + 24
    assert len(DOC) == 16
    assert 0 <= fp.bucket_of(UNIT) < fp.BUCKET_COUNT
    assert fp.membership_keys(DOC) == (
        "document-index:" + DOC,
        "structure-map:" + DOC,
        *(f"topic-bucket:{DOC}:{index}" for index in range(fp.BUCKET_COUNT)),
    )


# --- 6. the alignment invariant --------------------------------------------


def _clean(section_value: str) -> dict[str, str]:
    """A minimal clean-rebuild artifact map for the fixture document."""
    return {
        fp.SECTION_PREFIX + UNIT: section_value,
        fp.DOCUMENT_INDEX_PREFIX + DOC: "sha256:index",
        fp.STRUCTURE_MAP_PREFIX + DOC: "sha256:structure",
    }


def test_alignment_holds_when_the_delta_named_what_moved() -> None:
    before = [represented(ir.CONTENT_TEXT, "as written")]
    after = [represented(ir.CONTENT_TEXT, "as amended")]
    report = fp.assert_aligned(before, after, _clean("sha256:a"), _clean("sha256:b"))
    assert report.is_aligned
    assert report.under_invalidated == ()


def test_an_artifact_that_moved_unnamed_is_caught_and_raises() -> None:
    """The stale escape, reproduced as an invariant failure.

    The delta only knows about the unit its facts witness. A clean rebuild moves
    a *different* unit's artifact — the case where extraction did not produce a
    fact — and that must be reported, not carried forward.
    """
    before = [represented(ir.CONTENT_TEXT, "as written")]
    after = [represented(ir.CONTENT_TEXT, "as amended")]
    orphan = fp.SECTION_PREFIX + OTHER_UNIT

    before_artifacts = {**_clean("sha256:a"), orphan: "sha256:orphan-before"}
    after_artifacts = {**_clean("sha256:b"), orphan: "sha256:orphan-after"}

    report = fp.aligned(before, after, before_artifacts, after_artifacts)
    assert not report.is_aligned
    assert report.under_invalidated == (orphan,)
    assert orphan in report.describe()

    with pytest.raises(ir.NotSourceFaithful) as raised:
        fp.assert_aligned(before, after, before_artifacts, after_artifacts)
    assert orphan in str(raised.value)


def test_an_artifact_that_appeared_unnamed_is_also_a_violation() -> None:
    before = [represented(ir.CONTENT_TEXT, "as written")]
    after = [represented(ir.CONTENT_TEXT, "as amended")]
    appeared = fp.SECTION_PREFIX + OTHER_UNIT
    with pytest.raises(ir.NotSourceFaithful):
        fp.assert_aligned(
            before, after, _clean("sha256:a"), {**_clean("sha256:b"), appeared: "sha256:new"}
        )


def test_a_moved_fact_that_invalidates_nothing_is_a_violation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Over-invalidation is safe; a fact whose channel reaches nothing is not.

    Forced rather than found: no declared channel is currently empty, and the
    check exists so that adding one cannot pass silently.
    """
    monkeypatch.setitem(fp.CHANNEL_ARTIFACT_CLASSES, ir.SEMANTIC, frozenset())
    before = [represented(ir.CONTENT_TEXT, "as written")]
    after = [represented(ir.CONTENT_TEXT, "as amended")]

    report = fp.aligned(before, after, _clean("sha256:a"), _clean("sha256:a"))
    assert report.silent_facts == (before[0].fact_id,)
    assert not report.is_aligned
    with pytest.raises(ir.NotSourceFaithful):
        fp.assert_aligned(before, after, _clean("sha256:a"), _clean("sha256:a"))


# --- 7. over-invalidation is allowed; under-invalidation never is ----------


def test_over_invalidation_is_reported_and_does_not_raise() -> None:
    """Every artifact is named, none of them moved. Wasteful, not wrong."""
    before = [represented(ir.CONTENT_TEXT, "identical")]
    after = [represented(ir.REFERENCE_TARGET, {"target": "#x"}, witness=witness("link"))]
    artifacts = _clean("sha256:same")

    report = fp.assert_aligned(before, after, artifacts, dict(artifacts))
    assert report.moved == ()
    assert report.over_invalidated
    assert report.under_invalidated == ()
    assert report.is_aligned


def test_under_invalidation_always_raises_even_alongside_over_invalidation() -> None:
    before = [represented(ir.CONTENT_TEXT, "as written")]
    after = [represented(ir.CONTENT_TEXT, "as amended")]
    orphan = fp.SECTION_PREFIX + OTHER_UNIT
    report = fp.aligned(
        before,
        after,
        {**_clean("sha256:a"), orphan: "1"},
        {**_clean("sha256:b"), orphan: "2"},
    )
    assert report.over_invalidated, "topic buckets are named but absent from the map"
    assert report.under_invalidated == (orphan,)
    with pytest.raises(ir.NotSourceFaithful):
        fp.assert_aligned(
            before,
            after,
            {**_clean("sha256:a"), orphan: "1"},
            {**_clean("sha256:b"), orphan: "2"},
        )


# --- 8. an empty delta invalidates nothing ---------------------------------


def test_an_empty_delta_invalidates_nothing() -> None:
    assert fp.delta([], []).invalidate == ()
    assert fp.delta([], []).is_empty


def test_an_identical_revision_invalidates_nothing() -> None:
    facts = [
        represented(ir.CONTENT_TEXT, "one", witness=witness(start=0, end=3)),
        represented(
            ir.REFERENCE_TARGET, {"target": "#a"}, witness=witness("link", start=4, end=6)
        ),
        represented(
            ir.EFFECTIVE_TIME, "2026-01-01", witness=witness("meta", unit_path=(SOURCE,))
        ),
    ]
    typed = fp.delta(facts, list(facts))
    assert typed.is_empty
    assert typed.invalidate == ()
    assert len(typed.unchanged) == 3


def test_no_spurious_rebuild_when_only_the_witness_moved() -> None:
    """The file grew a header. Values are identical; identity is not.

    The units still move — their fact_ids are byte-derived — so this is not a
    claim that nothing rebuilds. It is a claim that the *representations* were
    seen as unchanged, which is what stops a fingerprint from disagreeing with
    a diff that correctly said "no semantic edit".
    """
    before = [represented(ir.CONTENT_TEXT, "body", witness=witness(start=0, end=4))]
    after = [represented(ir.CONTENT_TEXT, "body", witness=witness(start=40, end=44))]
    typed = fp.delta(before, after)
    assert len(typed.added) == 1
    assert len(typed.removed) == 1
    assert typed.added[0].fingerprint_after == typed.removed[0].fingerprint_before
