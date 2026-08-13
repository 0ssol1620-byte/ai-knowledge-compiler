"""Identity is the floor the masterplan's later phases stand on.

§9: temporal knowledge and incremental recompilation do not work without stable
identity. Three of the four ids must be pure functions of their inputs, and the
fourth must refuse to guess. Every test here is one of those two properties.
"""

from __future__ import annotations

import pytest
from akc_cir.identity import (
    IDENTITY_SCHEME_VERSION,
    IDENTITY_SIGNAL_WEIGHTS,
    MERGE_THRESHOLD,
    NEW_IDENTITY_THRESHOLD,
    LogicalIdentityDecision,
    LogicalIdentityResolver,
    LogicalMatch,
    LogicalRelation,
    LogicalUnitFingerprint,
    MissingReason,
    assign_one_to_one,
    document_version_id,
    evidence_id,
    generate_candidates,
    logical_id_seed,
    normalize_bbox1000,
    normalize_text_for_identity,
    source_id,
)

DIGEST = "sha256:" + "a" * 64
OTHER_DIGEST = "sha256:" + "b" * 64


def _source(native_id: str = "drive:1AbC") -> str:
    return source_id(tenant_id="tenant-1", connector_type="gdrive", native_id=native_id)


# --------------------------------------------------------------------------
# Determinism — the same inputs give the same id, on any machine, every time
# --------------------------------------------------------------------------


def test_the_same_source_resolves_to_the_same_id() -> None:
    assert _source() == _source()


def test_source_id_is_stable_against_surrounding_whitespace() -> None:
    assert source_id(
        tenant_id=" tenant-1 ", connector_type="gdrive ", native_id=" drive:1AbC"
    ) == _source()


def test_a_different_tenant_is_a_different_source() -> None:
    assert source_id(
        tenant_id="tenant-2", connector_type="gdrive", native_id="drive:1AbC"
    ) != _source()


def test_the_parts_cannot_slide_into_each_other() -> None:
    """Without length delimiting, ("ab","c") and ("a","bc") would collide."""
    left = source_id(tenant_id="ab", connector_type="c", native_id="x")
    right = source_id(tenant_id="a", connector_type="bc", native_id="x")
    assert left != right


def test_identical_bytes_resolve_to_the_same_version() -> None:
    source = _source()
    assert document_version_id(source=source, content_sha256=DIGEST) == (
        document_version_id(source=source, content_sha256=DIGEST)
    )


def test_different_bytes_are_a_different_version() -> None:
    source = _source()
    assert document_version_id(source=source, content_sha256=DIGEST) != (
        document_version_id(source=source, content_sha256=OTHER_DIGEST)
    )


def test_the_same_bytes_under_a_different_source_are_a_different_version() -> None:
    """Two tenants uploading the same file do not share a version row."""
    assert document_version_id(source=_source(), content_sha256=DIGEST) != (
        document_version_id(source=_source("drive:9ZzZ"), content_sha256=DIGEST)
    )


def test_a_renamed_file_keeps_its_source_identity() -> None:
    """§8.1 forbids reading FINAL in a filename as meaning; the connector id rules."""
    before = source_id(tenant_id="t", connector_type="gdrive", native_id="drive:1AbC")
    after = source_id(tenant_id="t", connector_type="gdrive", native_id="drive:1AbC")
    assert before == after


def test_ids_carry_their_prefix_and_scheme() -> None:
    source = _source()
    version = document_version_id(source=source, content_sha256=DIGEST)
    assert source.startswith("src_")
    assert version.startswith("dv_")
    assert IDENTITY_SCHEME_VERSION == "1"


# --------------------------------------------------------------------------
# Refusals — the places the masterplan forbids inventing data
# --------------------------------------------------------------------------


def test_a_version_id_requires_a_real_source_id() -> None:
    with pytest.raises(ValueError, match="requires a source id"):
        document_version_id(source="tenant-1", content_sha256=DIGEST)


def test_a_version_id_requires_a_well_formed_digest() -> None:
    with pytest.raises(ValueError, match="lowercase sha256"):
        document_version_id(source=_source(), content_sha256="deadbeef")


def test_an_empty_identity_part_is_refused() -> None:
    with pytest.raises(ValueError, match="required to derive a source id"):
        source_id(tenant_id="t", connector_type="", native_id="x")


def test_evidence_needs_an_anchor_not_just_a_page() -> None:
    """A page number alone would give every unit on the page one id."""
    version = document_version_id(source=_source(), content_sha256=DIGEST)
    with pytest.raises(ValueError, match="needs an anchor"):
        evidence_id(document_version=version, page_number1=17)


def test_evidence_accepts_a_span_when_there_is_no_bbox() -> None:
    """A source without coordinates anchors on its span; §8.1 forbids a fake box."""
    version = document_version_id(source=_source(), content_sha256=DIGEST)
    anchored = evidence_id(
        document_version=version, page_number1=17, span_text="Warranty is three years"
    )
    assert anchored.startswith("ev_")


def test_an_inverted_bbox_is_refused() -> None:
    with pytest.raises(ValueError, match="inverted edges"):
        normalize_bbox1000((900, 100, 100, 900))


def test_a_bbox_outside_the_per_mille_range_is_refused() -> None:
    with pytest.raises(ValueError, match=r"within 0\.\.1000"):
        normalize_bbox1000((0, 0, 1200, 100))


# --------------------------------------------------------------------------
# Tolerance — re-extraction jitter must not look like the evidence moved
# --------------------------------------------------------------------------


def test_a_box_that_shifts_by_a_per_mille_unit_keeps_its_evidence_id() -> None:
    version = document_version_id(source=_source(), content_sha256=DIGEST)
    first = evidence_id(document_version=version, page_number1=17, bbox1000=(100, 200, 300, 400))
    jittered = evidence_id(document_version=version, page_number1=17, bbox1000=(101, 200, 300, 400))
    assert first == jittered


def test_a_box_that_actually_moves_gets_a_new_evidence_id() -> None:
    version = document_version_id(source=_source(), content_sha256=DIGEST)
    first = evidence_id(document_version=version, page_number1=17, bbox1000=(100, 200, 300, 400))
    moved = evidence_id(document_version=version, page_number1=17, bbox1000=(400, 500, 600, 700))
    assert first != moved


def test_evidence_on_a_different_page_is_different_evidence() -> None:
    version = document_version_id(source=_source(), content_sha256=DIGEST)
    assert evidence_id(
        document_version=version, page_number1=17, bbox1000=(100, 200, 300, 400)
    ) != evidence_id(
        document_version=version, page_number1=18, bbox1000=(100, 200, 300, 400)
    )


def test_identity_normalization_folds_only_what_should_not_matter() -> None:
    assert normalize_text_for_identity("  Warranty:  THREE years. ") == (
        normalize_text_for_identity("warranty three years")
    )
    assert normalize_text_for_identity("two years") != normalize_text_for_identity(
        "three years"
    )


# --------------------------------------------------------------------------
# Logical identity — the judgement, and its refusal to guess
# --------------------------------------------------------------------------


SRC = "src_acme_warranty"


def _unit(
    logical_id: str,
    *,
    path: tuple[str, ...] = ("Warranty", "Coverage"),
    anchor: str = "4.2 Exceptions",
    text: str = "The warranty covers parts and labour for two years from delivery.",
    neighbours: tuple[str, ...] = ("4.1 Scope", "4.3 Claims"),
    lineage: str = SRC,
    identifier: str = "4.2",
    version_distance: int = 1,
    style: str = "body 10pt indent-0",
) -> LogicalUnitFingerprint:
    return LogicalUnitFingerprint.of(
        logical_id=logical_id,
        document_path=path,
        anchor=anchor,
        text=text,
        source_lineage=lineage,
        version_distance=version_distance,
        explicit_identifier=identifier,
        geometry_style=style,
        neighbour_anchors=neighbours,
    )


def test_a_clause_whose_wording_changed_keeps_its_identity() -> None:
    """The whole point: 2 years becoming 3 years is the same clause."""
    resolver = LogicalIdentityResolver()
    previous = [_unit("ku_warranty")]
    incoming = _unit(
        "ku_pending",
        text="The warranty covers parts and labour for three years from delivery.",
    )

    decision = resolver.resolve(incoming, previous)

    assert decision.match is LogicalMatch.MATCHED
    assert decision.logical_id == "ku_warranty"
    assert decision.merged


def test_an_unrelated_clause_starts_a_new_identity() -> None:
    resolver = LogicalIdentityResolver()
    previous = [_unit("ku_warranty")]
    incoming = _unit(
        "ku_seed",
        path=("Shipping", "Carriers"),
        anchor="9.1 Carrier selection",
        text="Shipments are tendered to the carrier with the earliest pickup window.",
        neighbours=("9.0 Overview", "9.2 Rates"),
        identifier="9.1",
        style="body 10pt indent-1",
    )

    decision = resolver.resolve(incoming, previous, seed_logical_id="ku_seed")

    assert decision.match is LogicalMatch.NEW
    assert decision.logical_id == "ku_seed"


def test_two_near_identical_candidates_are_refused_rather_than_picked() -> None:
    """A wrong merge rewrites a clause's history and nothing downstream can see it."""
    resolver = LogicalIdentityResolver()
    previous = [_unit("ku_left"), _unit("ku_right")]
    incoming = _unit("ku_pending")

    decision = resolver.resolve(incoming, previous)

    assert decision.match is LogicalMatch.AMBIGUOUS
    assert decision.logical_id is None
    assert set(decision.candidates) == {"ku_left", "ku_right"}
    assert "arbitrarily" in decision.reason


def test_a_middling_score_lands_in_the_review_band_not_a_merge() -> None:
    resolver = LogicalIdentityResolver()
    previous = [_unit("ku_warranty")]
    incoming = _unit(
        "ku_pending",
        anchor="4.2 Exclusions",
        text="Coverage excludes consumable parts and cosmetic damage entirely.",
        neighbours=("4.1 Scope", "4.4 Remedies"),
    )

    decision = resolver.resolve(incoming, previous)

    assert decision.match is LogicalMatch.AMBIGUOUS
    assert decision.logical_id is None
    assert "review band" in decision.reason


def test_a_decision_always_explains_itself() -> None:
    resolver = LogicalIdentityResolver()
    decision = resolver.resolve(_unit("ku_pending"), [_unit("ku_warranty")])

    assert decision.reason
    assert set(decision.signals) == set(IDENTITY_SIGNAL_WEIGHTS)
    assert all(0.0 <= value <= 1.0 for value in decision.signals.values())


# --------------------------------------------------------------------------
# §N15.4 — the bar sits at 0.92 because a false merge costs more than a split
# --------------------------------------------------------------------------


def test_the_bootstrap_bands_are_the_ones_the_masterplan_fixed() -> None:
    assert MERGE_THRESHOLD == 0.92
    assert NEW_IDENTITY_THRESHOLD == 0.75


def test_the_weights_are_the_ones_the_masterplan_fixed() -> None:
    assert IDENTITY_SIGNAL_WEIGHTS == {
        "source_continuity": 0.25,
        "structural_path": 0.20,
        "explicit_identifier": 0.15,
        "semantic": 0.15,
        "previous_neighbor": 0.10,
        "next_neighbor": 0.10,
        "geometry_style": 0.05,
    }


def test_a_candidate_from_another_source_does_not_continue_this_one() -> None:
    resolver = LogicalIdentityResolver()
    foreign = _unit("ku_other_doc", lineage="src_other_tenant_doc")

    decision = resolver.resolve(_unit("ku_pending"), [foreign])

    assert decision.match is not LogicalMatch.MATCHED
    assert decision.signals["source_continuity"] == 0.0


def test_an_older_version_is_a_weaker_ancestor_than_the_last_one() -> None:
    resolver = LogicalIdentityResolver()
    recent = resolver.resolve(_unit("ku_p"), [_unit("ku_w", version_distance=1)])
    older = resolver.resolve(_unit("ku_p"), [_unit("ku_w", version_distance=4)])

    assert older.signals["source_continuity"] < recent.signals["source_continuity"]


# --------------------------------------------------------------------------
# §N4.4 — a missing signal is missing, and zero-filling it breaks merging
# --------------------------------------------------------------------------


def test_a_clause_with_no_number_can_still_merge() -> None:
    """The regression that motivated renormalising over available weight.

    Most prose carries no clause identifier. Scoring that signal zero caps such
    a unit at 0.85 -- under the 0.92 bar, forever -- so nothing would ever merge
    and every paragraph would look new in every version.
    """
    resolver = LogicalIdentityResolver()
    previous = [_unit("ku_para", identifier="", anchor="", neighbours=())]
    incoming = _unit(
        "ku_pending",
        identifier="",
        anchor="",
        neighbours=(),
        text="The warranty covers parts and labour for three years from delivery.",
    )

    decision = resolver.resolve(incoming, previous)

    assert decision.match is LogicalMatch.MATCHED
    assert "explicit_identifier" in decision.missing
    assert "explicit_identifier" not in decision.signals


def test_an_absent_signal_records_why_rather_than_scoring_zero() -> None:
    resolver = LogicalIdentityResolver()
    decision = resolver.resolve(
        _unit("ku_pending", identifier=""), [_unit("ku_warranty", identifier="")]
    )

    assert decision.missing["explicit_identifier"] == MissingReason.NOT_APPLICABLE.value


def test_a_missing_critical_signal_abstains_however_well_the_rest_score() -> None:
    """§N5.5 -- critical features missing is a mandatory abstention.

    Renormalising the remaining signals to 1.0 would manufacture a confident
    score out of a thin one, which is worse than saying nothing.
    """
    resolver = LogicalIdentityResolver()
    previous = [_unit("ku_warranty", lineage="")]
    incoming = _unit("ku_pending", lineage="")

    decision = resolver.resolve(incoming, previous)

    assert decision.match is LogicalMatch.AMBIGUOUS
    assert "source_continuity" in decision.missing
    assert "critical signal" in decision.reason


# --------------------------------------------------------------------------
# §N15.3 — one old unit to one new unit
# --------------------------------------------------------------------------


def test_two_new_units_cannot_both_continue_the_same_old_one() -> None:
    """Independent resolution forks a history without anyone deciding to fork it."""
    previous = [_unit("ku_warranty"), _unit("ku_shipping", path=("Shipping",),
                                            anchor="9.1", identifier="9.1",
                                            text="Shipments go to the earliest carrier.",
                                            neighbours=("9.0", "9.2"))]
    incoming = [
        _unit("ku_a", text="The warranty covers parts and labour for three years."),
        _unit("ku_b", text="The warranty covers parts and labour for four years."),
    ]

    decisions = assign_one_to_one(incoming, previous)

    claimed = [d.logical_id for d in decisions if d.match is LogicalMatch.MATCHED]
    assert len(claimed) == len(set(claimed))


def test_the_matching_never_promotes_a_weak_pair_just_because_it_was_left_over() -> None:
    previous = [_unit("ku_warranty")]
    incoming = [
        _unit("ku_a", text="The warranty covers parts and labour for three years."),
        _unit(
            "ku_b",
            path=("Shipping", "Carriers"),
            anchor="9.1 Carrier selection",
            identifier="9.1",
            text="Shipments are tendered to the carrier with the earliest window.",
            neighbours=("9.0 Overview", "9.2 Rates"),
            style="body 9pt indent-2",
        ),
    ]

    decisions = assign_one_to_one(incoming, previous)

    assert LogicalMatch.MATCHED not in {
        d.match for d in decisions if d.logical_id == "ku_b"
    }


def test_an_empty_window_is_not_an_error() -> None:
    assert assign_one_to_one([], [_unit("ku_warranty")]) == []
    assert all(
        d.match is LogicalMatch.NEW for d in assign_one_to_one([_unit("ku_a")], [])
    )


# --------------------------------------------------------------------------
# §N15.1 — candidates are restricted, never all-pairs
# --------------------------------------------------------------------------


def test_candidate_generation_drops_another_source_entirely() -> None:
    incoming = _unit("ku_pending")
    candidates = generate_candidates(
        incoming, [_unit("ku_same"), _unit("ku_foreign", lineage="src_elsewhere")]
    )

    assert [c.logical_id for c in candidates] == ["ku_same"]


def test_candidate_generation_bounds_the_window() -> None:
    incoming = _unit("ku_pending")
    previous = [_unit(f"ku_{index}") for index in range(50)]

    assert len(generate_candidates(incoming, previous, window=8)) == 8


# --------------------------------------------------------------------------
# §N15.3 relations
# --------------------------------------------------------------------------


def test_a_clause_that_stayed_put_is_a_same_as_version() -> None:
    decision = LogicalIdentityResolver().resolve(
        _unit("ku_pending", text="The warranty covers parts for three years."),
        [_unit("ku_warranty", text="The warranty covers parts for two years.")],
    )

    assert decision.match is LogicalMatch.MATCHED
    assert decision.relation is LogicalRelation.SAME_AS_VERSION


def test_a_clause_that_changed_section_is_recorded_as_moved() -> None:
    decision = LogicalIdentityResolver().resolve(
        _unit("ku_pending", path=("Warranty", "Coverage", "Parts")),
        [_unit("ku_warranty", path=("Warranty", "Coverage"))],
    )

    if decision.match is LogicalMatch.MATCHED:
        assert decision.relation is LogicalRelation.MOVED_FROM


def test_the_first_version_of_a_document_has_nothing_to_continue() -> None:
    resolver = LogicalIdentityResolver()
    decision = resolver.resolve(_unit("ku_seed"), [], seed_logical_id="ku_seed")

    assert decision.match is LogicalMatch.NEW
    assert decision.logical_id == "ku_seed"
    assert "no prior version" in decision.reason


def test_resolution_does_not_depend_on_candidate_order() -> None:
    resolver = LogicalIdentityResolver()
    incoming = _unit("ku_pending", text="The warranty covers parts for three years.")
    far = _unit(
        "ku_far",
        path=("Shipping",),
        anchor="9.1 Carriers",
        text="Shipments are tendered to the earliest carrier.",
        neighbours=(),
    )
    near = _unit("ku_warranty")

    forward = resolver.resolve(incoming, [near, far])
    backward = resolver.resolve(incoming, [far, near])

    assert forward.match is backward.match
    assert forward.logical_id == backward.logical_id


def test_thresholds_must_be_ordered() -> None:
    with pytest.raises(ValueError, match="thresholds must satisfy"):
        LogicalIdentityResolver(merge_threshold=0.3, new_threshold=0.6)


def test_signal_weights_must_sum_to_one() -> None:
    with pytest.raises(ValueError, match=r"must sum to 1\.0"):
        LogicalIdentityResolver(
            weights={"path": 0.5, "anchor": 0.1, "content": 0.1, "neighbours": 0.1}
        )


# --------------------------------------------------------------------------
# Seeding — identity survives a content rewrite because content is not in it
# --------------------------------------------------------------------------


def test_the_logical_seed_ignores_content() -> None:
    source = _source()
    first = logical_id_seed(
        source=source, document_path=("Warranty", "Coverage"), anchor="4.2 Exceptions"
    )
    again = logical_id_seed(
        source=source, document_path=("Warranty", "Coverage"), anchor="4.2 Exceptions"
    )
    assert first == again
    assert first.startswith("ku_")


def test_a_different_structural_path_seeds_a_different_identity() -> None:
    source = _source()
    assert logical_id_seed(
        source=source, document_path=("Warranty",), anchor="4.2"
    ) != logical_id_seed(source=source, document_path=("Shipping",), anchor="4.2")


def test_the_logical_seed_requires_a_source() -> None:
    with pytest.raises(ValueError, match="requires a source id"):
        logical_id_seed(source="warranty.pdf", document_path=(), anchor="4.2")


def test_a_decision_is_immutable() -> None:
    decision = LogicalIdentityDecision(match=LogicalMatch.NEW, logical_id="ku_a", score=0.0)
    with pytest.raises((AttributeError, TypeError)):
        decision.logical_id = "ku_b"  # type: ignore[misc]
