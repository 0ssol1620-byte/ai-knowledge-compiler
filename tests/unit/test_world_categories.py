"""World category promotions — the refusals are the feature.

The matrix exists so that widening who can see a world is always a decision
with someone's name on it. The tests that matter most are therefore the
refusals: the private world nobody can promote by any route, the team
promotion with no reviewer note behind it, and the skip-level jump the matrix
never listed. The happy paths are tested too, but they are the easy part.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest
from akc_cir.world_categories import (
    ALLOWED_PROMOTIONS,
    ActorRole,
    IllegalPromotionError,
    PermissionDiff,
    PromotionDecision,
    SharingPolicy,
    WorldCategory,
    WorldManifest,
    promote,
)

TEAM = WorldCategory.TEAM_OFFICIAL
SHARED = WorldCategory.SHARED_BY_OWNER


def _manifest(**kw: Any) -> WorldManifest:
    base: dict[str, Any] = {
        "world_id": "ws_1",
        "owner_id": "owner_1",
        "category": SHARED,
        "shared_with": frozenset({"alice"}),
        "team_members": frozenset({"bob", "carol"}),
        "project_members": frozenset({"dave", "erin"}),
        "org_members": frozenset({"frank", "grace", "heidi"}),
        "external_audience": frozenset({"auditor@external.example"}),
        "restricted_audience": frozenset({"compliance_1"}),
    }
    base.update(kw)
    return WorldManifest(**base)


# --- the hard rule: PRIVATE_PERSONAL never promotes -------------------------


@pytest.mark.parametrize("to_cat", list(WorldCategory))
def test_private_world_never_promotes_to_anything(to_cat: WorldCategory) -> None:
    world = _manifest(category=WorldCategory.PRIVATE_PERSONAL)

    with pytest.raises(IllegalPromotionError, match="PRIVATE_PERSONAL never promotes"):
        promote(
            world,
            WorldCategory.PRIVATE_PERSONAL,
            to_cat,
            [ActorRole.OWNER],
            reviewer_note="owner insists",
        )


def test_hard_rule_is_the_matrix_row_not_a_special_case() -> None:
    assert ALLOWED_PROMOTIONS[WorldCategory.PRIVATE_PERSONAL] == frozenset()
    assert all(
        not SharingPolicy.can_promote(WorldCategory.PRIVATE_PERSONAL, cat)
        for cat in WorldCategory
    )


def test_promoting_from_private_by_any_role_raises() -> None:
    world = _manifest(category=WorldCategory.PRIVATE_PERSONAL)

    # Both entry points refuse: the policy guard directly, promote() by way of it.
    with pytest.raises(IllegalPromotionError):
        SharingPolicy.require_promotable(
            WorldCategory.PRIVATE_PERSONAL, WorldCategory.PROJECT_SCOPED
        )

    with pytest.raises(IllegalPromotionError):
        promote(
            world,
            "PRIVATE_PERSONAL",
            "PROJECT_SCOPED",
            [ActorRole.ORG_ADMIN.value],
            reviewer_note="org admin insists",
        )


# --- transitions outside the matrix -----------------------------------------


@pytest.mark.parametrize(
    ("from_cat", "to_cat"),
    [
        (SHARED, WorldCategory.ORG_POLICY),  # skip-level jump
        (SHARED, WorldCategory.EXTERNAL_AUTHORITATIVE),
        (TEAM, SHARED),  # demotions are not promotions
        (WorldCategory.PROJECT_SCOPED, TEAM),
        (WorldCategory.ORG_POLICY, WorldCategory.PROJECT_SCOPED),
        (WorldCategory.EXTERNAL_AUTHORITATIVE, WorldCategory.ORG_POLICY),
        (WorldCategory.RESTRICTED, TEAM),
        (TEAM, TEAM),  # a no-op is not a transition either
    ],
)
def test_transitions_outside_the_matrix_raise(
    from_cat: WorldCategory, to_cat: WorldCategory
) -> None:
    with pytest.raises(IllegalPromotionError, match="sharing matrix"):
        promote(
            _manifest(category=from_cat),
            from_cat,
            to_cat,
            [ActorRole.ORG_ADMIN],
            reviewer_note="note",
        )


def test_stale_view_of_current_category_is_refused() -> None:
    world = _manifest(category=TEAM)  # caller believes SHARED; it already moved

    with pytest.raises(IllegalPromotionError, match="stale view"):
        promote(world, SHARED, WorldCategory.PROJECT_SCOPED, [ActorRole.TEAM_ADMIN])


# --- the normal path --------------------------------------------------------


def test_shared_by_owner_to_team_official_is_approved_with_reviewer_note() -> None:
    world = _manifest()

    decision = promote(
        world,
        SHARED,
        TEAM,
        [ActorRole.TEAM_ADMIN],
        reviewer_note="team review 2026-08-23: approved for squad visibility",
    )

    assert decision.approved
    assert decision.world_id == "ws_1"
    assert decision.from_category is SHARED
    assert decision.to_category is TEAM
    assert decision.reviewer_note == (
        "team review 2026-08-23: approved for squad visibility"
    )
    assert decision.resulting_manifest is not None
    assert decision.resulting_manifest.category is TEAM
    assert world.category is SHARED  # the original manifest is untouched


def test_owner_can_reach_team_official_and_project_scoped() -> None:
    world = _manifest()

    team = promote(world, SHARED, TEAM, ["OWNER"], reviewer_note="owner decision")
    project = promote(
        world.with_category(TEAM), TEAM, WorldCategory.PROJECT_SCOPED, ["OWNER"]
    )

    assert team.approved
    assert project.approved


def test_org_admin_can_reach_org_policy_and_external() -> None:
    world = _manifest(category=TEAM)

    org = promote(
        world, TEAM, WorldCategory.ORG_POLICY, [ActorRole.ORG_ADMIN]
    )
    external = promote(
        world.with_category(WorldCategory.ORG_POLICY),
        WorldCategory.ORG_POLICY,
        WorldCategory.EXTERNAL_AUTHORITATIVE,
        ["org_admin"],
        reviewer_note="published per disclosure policy",
    )

    assert org.approved
    assert external.approved
    assert external.resulting_manifest is not None
    assert external.resulting_manifest.category is (
        WorldCategory.EXTERNAL_AUTHORITATIVE
    )


# --- permission-diff preview accuracy ---------------------------------------


def test_permission_diff_names_exactly_the_newly_visible_subjects() -> None:
    world = _manifest()

    diff = SharingPolicy.permission_diff(world, SHARED, TEAM)

    assert isinstance(diff, PermissionDiff)
    assert diff.before == frozenset({"owner_1", "alice"})
    assert diff.after == frozenset({"owner_1", "alice", "bob", "carol"})
    assert diff.newly_visible == ("bob", "carol")  # sorted, owner/alice excluded
    assert diff.widens


def test_decision_carries_the_same_preview_it_was_judged_on() -> None:
    decision = promote(
        _manifest(),
        SHARED,
        WorldCategory.PROJECT_SCOPED,
        [ActorRole.TEAM_ADMIN],
    )

    # Cumulative ladder: jumping to project scope pulls the team rung in too.
    assert decision.permission_diff.newly_visible == ("bob", "carol", "dave", "erin")
    assert {"bob", "carol"}.issubset(decision.permission_diff.after)


def test_audience_grows_monotonically_up_the_ladder() -> None:
    world = _manifest()
    ladder = [
        WorldCategory.PRIVATE_PERSONAL,
        SHARED,
        TEAM,
        WorldCategory.PROJECT_SCOPED,
        WorldCategory.ORG_POLICY,
        WorldCategory.EXTERNAL_AUTHORITATIVE,
    ]

    seen = frozenset[str]()
    for cat in ladder:
        current = world.audience(cat)
        assert seen < current, f"{cat.value} must widen beyond the rungs below it"
        seen = current


def test_restricted_audience_inherits_nothing() -> None:
    world = _manifest(category=WorldCategory.RESTRICTED)

    assert world.audience(WorldCategory.RESTRICTED) == frozenset({"compliance_1"})


# --- reviewer-note gate ------------------------------------------------------


def test_team_official_without_reviewer_note_is_refused() -> None:
    decision = promote(_manifest(), SHARED, TEAM, [ActorRole.TEAM_ADMIN])

    assert not decision.approved
    assert any("reviewer note" in reason for reason in decision.reasons)
    assert decision.resulting_manifest is None
    # A refusal still carries the preview it refused to act on.
    assert decision.permission_diff.newly_visible == ("bob", "carol")


@pytest.mark.parametrize("note", [None, "", "   \n\t "])
def test_blank_reviewer_notes_count_as_missing(note: str | None) -> None:
    decision = promote(_manifest(), SHARED, TEAM, [ActorRole.OWNER], reviewer_note=note)

    assert not decision.approved


def test_reviewer_note_is_not_demanded_for_non_team_destinations() -> None:
    decision = promote(
        _manifest(),
        SHARED,
        WorldCategory.PROJECT_SCOPED,
        [ActorRole.TEAM_ADMIN],
        reviewer_note=None,
    )

    assert decision.approved


# --- role gates --------------------------------------------------------------


def test_team_admin_cannot_reach_org_policy_alone() -> None:
    decision = promote(
        _manifest(category=TEAM),
        TEAM,
        WorldCategory.ORG_POLICY,
        [ActorRole.TEAM_ADMIN],
    )

    assert not decision.approved
    assert any("ORG_ADMIN" in reason for reason in decision.reasons)


def test_unrecognised_roles_fail_closed() -> None:
    decision = promote(
        _manifest(), SHARED, TEAM, ["viewer", "guest"], reviewer_note="note"
    )

    assert not decision.approved


def test_owner_satisfies_every_role_gate() -> None:
    decision = promote(
        _manifest(category=TEAM),
        TEAM,
        WorldCategory.ORG_POLICY,
        [ActorRole.OWNER],
    )

    assert decision.approved


# --- backward compatibility --------------------------------------------------


def test_manifest_without_category_reads_as_private_personal() -> None:
    legacy = WorldManifest(world_id="old_world", owner_id="u_1")

    assert legacy.category is WorldCategory.PRIVATE_PERSONAL
    assert legacy.audience(WorldCategory.PRIVATE_PERSONAL) == frozenset({"u_1"})


def test_serialised_manifest_predating_categories_still_loads() -> None:
    raw = {
        "world_id": "old_world",
        "owner_id": "u_1",
        # no "category" key — written before this module existed
        "shared_with": ["alice"],
        "unknown_future_field": {"ignored": True},
    }

    manifest = WorldManifest.from_mapping(raw)

    assert manifest.category is WorldCategory.PRIVATE_PERSONAL
    assert manifest.shared_with == frozenset({"alice"})
    assert manifest.audience(SHARED) == frozenset({"u_1", "alice"})


def test_serialised_category_string_round_trips() -> None:
    manifest = WorldManifest.from_mapping(
        {"world_id": "w", "owner_id": "o", "category": "TEAM_OFFICIAL"}
    )

    assert manifest.category is WorldCategory.TEAM_OFFICIAL


# --- shape of the contract ---------------------------------------------------


def test_decisions_and_diffs_are_immutable() -> None:
    decision = promote(
        _manifest(), SHARED, TEAM, [ActorRole.TEAM_ADMIN], reviewer_note="ok"
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        decision.approved = True  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        decision.permission_diff.newly_visible = ()  # type: ignore[misc]


def test_every_category_has_a_matrix_row() -> None:
    assert set(ALLOWED_PROMOTIONS) == set(WorldCategory)


def test_decision_type_is_returned() -> None:
    decision = promote(
        _manifest(), SHARED, TEAM, [ActorRole.TEAM_ADMIN], reviewer_note="note"
    )

    assert isinstance(decision, PromotionDecision)
