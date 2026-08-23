"""How far a compiled world reaches, and the only ways that reach may grow.

P1 team boundaries. A world starts as one person's private compile, and every
widening of who can see it is a recorded decision — never a side effect of a
sync, an import, or a well-meaning script. :class:`WorldCategory` names the
rungs, :class:`SharingPolicy` holds the matrix of which rung may follow which,
and :func:`promote` turns a request into a :class:`PromotionDecision`: approved
with a permission diff attached, refused with reasons, or — for the transitions
the matrix forbids outright — not permitted to exist at all.

The hard rule sits above the matrix and is not configurable: a
``PRIVATE_PERSONAL`` world never promotes, to anything, by anyone, even its
owner with a reviewer note in hand. Making a world visible to someone else is a
decision the owner makes once, explicitly, by first moving it out of private
through a channel that records the act; no transition here may impersonate it.

Two refusals are *decisions* rather than exceptions. Reaching ``TEAM_OFFICIAL``
requires a reviewer note, because a team-official world is one someone must be
able to point back at later, and each destination demands a minimum actor role.
Those return ``approved=False`` with reasons so callers can render them next to
the permission preview. The matrix itself raises
:class:`IllegalPromotionError`, because an illegal transition is not a decision
anyone can approve — refusing it loudly is the whole feature.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, ClassVar, Final

__all__ = [
    "ALLOWED_PROMOTIONS",
    "NOTE_REQUIRED_TARGETS",
    "TARGET_MINIMUM_ROLE",
    "ActorRole",
    "IllegalPromotionError",
    "PermissionDiff",
    "PromotionDecision",
    "SharingPolicy",
    "WorldCategory",
    "WorldManifest",
    "promote",
]


class WorldCategory(StrEnum):
    """The seven rungs a world's visibility can sit on."""

    PRIVATE_PERSONAL = "PRIVATE_PERSONAL"
    SHARED_BY_OWNER = "SHARED_BY_OWNER"
    TEAM_OFFICIAL = "TEAM_OFFICIAL"
    PROJECT_SCOPED = "PROJECT_SCOPED"
    ORG_POLICY = "ORG_POLICY"
    EXTERNAL_AUTHORITATIVE = "EXTERNAL_AUTHORITATIVE"
    RESTRICTED = "RESTRICTED"


class ActorRole(StrEnum):
    """The roles a promoter may hold. ``OWNER`` satisfies every gate."""

    OWNER = "OWNER"
    TEAM_ADMIN = "TEAM_ADMIN"
    ORG_ADMIN = "ORG_ADMIN"


class IllegalPromotionError(RuntimeError):
    """A transition the sharing matrix forbids does not happen quietly."""


ALLOWED_PROMOTIONS: Final[Mapping[WorldCategory, frozenset[WorldCategory]]] = {
    # PRIVATE_PERSONAL is the hard rule: the empty set is the feature.
    WorldCategory.PRIVATE_PERSONAL: frozenset(),
    WorldCategory.SHARED_BY_OWNER: frozenset(
        {WorldCategory.TEAM_OFFICIAL, WorldCategory.PROJECT_SCOPED}
    ),
    WorldCategory.TEAM_OFFICIAL: frozenset(
        {WorldCategory.PROJECT_SCOPED, WorldCategory.ORG_POLICY}
    ),
    WorldCategory.PROJECT_SCOPED: frozenset({WorldCategory.ORG_POLICY}),
    WorldCategory.ORG_POLICY: frozenset({WorldCategory.EXTERNAL_AUTHORITATIVE}),
    # Terminal states: nothing promotes out of a published-external or a
    # restricted world through this path. RESTRICTED in particular is a
    # compliance state, not a sharing level.
    WorldCategory.EXTERNAL_AUTHORITATIVE: frozenset(),
    WorldCategory.RESTRICTED: frozenset(),
}

NOTE_REQUIRED_TARGETS: Final[frozenset[WorldCategory]] = frozenset(
    {WorldCategory.TEAM_OFFICIAL}
)

TARGET_MINIMUM_ROLE: Final[Mapping[WorldCategory, ActorRole]] = {
    WorldCategory.TEAM_OFFICIAL: ActorRole.TEAM_ADMIN,
    WorldCategory.PROJECT_SCOPED: ActorRole.TEAM_ADMIN,
    WorldCategory.ORG_POLICY: ActorRole.ORG_ADMIN,
    WorldCategory.EXTERNAL_AUTHORITATIVE: ActorRole.ORG_ADMIN,
}

_ROLE_RANK: Final[Mapping[ActorRole, int]] = {
    ActorRole.TEAM_ADMIN: 1,
    ActorRole.ORG_ADMIN: 2,
}

_ROSTER_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "shared_with",
        "team_members",
        "project_members",
        "org_members",
        "external_audience",
        "restricted_audience",
    }
)


def _parse_roles(actor_roles: Collection[str]) -> frozenset[ActorRole]:
    """Keep recognisable roles, drop unrecognisable ones — fail closed either way."""
    parsed: list[ActorRole] = []
    for raw in actor_roles:
        try:
            parsed.append(ActorRole(str(raw).strip().upper()))
        except ValueError:
            continue
    return frozenset(parsed)


def _role_satisfied(actor_roles: Collection[str], required: ActorRole) -> bool:
    held = _parse_roles(actor_roles)
    if ActorRole.OWNER in held:
        return True
    needed_rank = _ROLE_RANK[required]
    return any(_ROLE_RANK.get(role, 0) >= needed_rank for role in held)


@dataclass(frozen=True, slots=True)
class PermissionDiff:
    """Who a promotion would newly let see the world — computed before approval.

    The preview is pure: it depends only on the manifest's current rosters and
    the two categories, so callers can show it *before* anyone decides, and the
    decision records the same numbers the preview showed.
    """

    from_category: WorldCategory
    to_category: WorldCategory
    before: frozenset[str]
    after: frozenset[str]
    newly_visible: tuple[str, ...]

    @property
    def widens(self) -> bool:
        return bool(self.newly_visible)


@dataclass(frozen=True, slots=True)
class WorldManifest:
    """A world as the sharing layer sees it: identity, category, and rosters.

    ``category`` defaults to ``PRIVATE_PERSONAL`` so manifests written before
    categories existed read back as exactly what they were — private. Nothing
    about an existing world changes merely because this module learned the word.
    """

    world_id: str
    owner_id: str
    category: WorldCategory = WorldCategory.PRIVATE_PERSONAL
    shared_with: frozenset[str] = frozenset()
    team_members: frozenset[str] = frozenset()
    project_members: frozenset[str] = frozenset()
    org_members: frozenset[str] = frozenset()
    external_audience: frozenset[str] = frozenset()
    restricted_audience: frozenset[str] = frozenset()

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> WorldManifest:
        """Load a manifest whose serialised form may predate categories.

        Unknown keys are ignored, a missing ``category`` falls back to
        ``PRIVATE_PERSONAL``, and roster collections arrive from JSON as lists
        and leave as frozensets.
        """
        kwargs: dict[str, Any] = {}
        for f in dataclasses.fields(cls):
            if f.name not in raw:
                continue
            value: Any = raw[f.name]
            if f.name == "category" and isinstance(value, str):
                value = WorldCategory(value)
            if f.name in _ROSTER_FIELDS and isinstance(value, list | tuple | set):
                value = frozenset(str(member) for member in value)
            kwargs[f.name] = value
        return cls(**kwargs)

    def with_category(self, category: WorldCategory) -> WorldManifest:
        """The same world, moved to ``category``. The original is untouched."""
        return dataclasses.replace(self, category=category)

    def audience(self, category: WorldCategory) -> frozenset[str]:
        """Everyone who can see the world while it sits at ``category``.

        Visibility widens cumulatively up the ladder: each rung keeps everyone
        the previous rung already showed it to. ``RESTRICTED`` is the exception
        and deliberately inherits nothing — being restricted means exactly the
        named list can see the world, and an empty list means nobody can.
        """
        match category:
            case WorldCategory.PRIVATE_PERSONAL:
                return frozenset({self.owner_id})
            case WorldCategory.SHARED_BY_OWNER:
                return frozenset({self.owner_id}) | self.shared_with
            case WorldCategory.TEAM_OFFICIAL:
                return self.audience(WorldCategory.SHARED_BY_OWNER) | self.team_members
            case WorldCategory.PROJECT_SCOPED:
                return self.audience(WorldCategory.TEAM_OFFICIAL) | self.project_members
            case WorldCategory.ORG_POLICY:
                return self.audience(WorldCategory.PROJECT_SCOPED) | self.org_members
            case WorldCategory.EXTERNAL_AUTHORITATIVE:
                return self.audience(WorldCategory.ORG_POLICY) | self.external_audience
            case WorldCategory.RESTRICTED:
                return frozenset(self.restricted_audience)


@dataclass(frozen=True, slots=True)
class PromotionDecision:
    """The outcome of one promotion request, with the preview it was judged on.

    ``permission_diff`` is present whether approved or not — a refusal still
    deserves to say what it refused to do. ``resulting_manifest`` is the world
    moved to the new category, and only exists when ``approved``.
    """

    world_id: str
    from_category: WorldCategory
    to_category: WorldCategory
    approved: bool
    permission_diff: PermissionDiff
    reasons: tuple[str, ...] = ()
    reviewer_note: str | None = None
    resulting_manifest: WorldManifest | None = None


class SharingPolicy:
    """The promotion matrix, and the two gates the matrix implies.

    Everything is a classmethod over the module-level tables, so there is one
    matrix in the codebase and tests can read the same rows the decisions do.
    """

    ALLOWED_PROMOTIONS: ClassVar[Mapping[WorldCategory, frozenset[WorldCategory]]] = (
        ALLOWED_PROMOTIONS
    )
    NOTE_REQUIRED_TARGETS: ClassVar[frozenset[WorldCategory]] = NOTE_REQUIRED_TARGETS
    TARGET_MINIMUM_ROLE: ClassVar[Mapping[WorldCategory, ActorRole]] = TARGET_MINIMUM_ROLE

    @classmethod
    def can_promote(cls, from_category: WorldCategory, to_category: WorldCategory) -> bool:
        """True only for transitions the matrix lists. Same-category is not one."""
        if from_category == to_category:
            return False
        return to_category in cls.ALLOWED_PROMOTIONS.get(from_category, frozenset())

    @classmethod
    def require_promotable(
        cls, from_category: WorldCategory, to_category: WorldCategory
    ) -> None:
        """Raise unless the matrix lists this transition.

        The ``PRIVATE_PERSONAL`` check comes first and is unconditional — the
        empty row is the hard rule, and naming it separately keeps the error
        honest about which invariant fired.
        """
        if from_category == WorldCategory.PRIVATE_PERSONAL:
            raise IllegalPromotionError(
                "PRIVATE_PERSONAL never promotes: no category, no role, no note "
                "changes this. Move the world out of private through an explicit, "
                "recorded owner action instead."
            )
        if not cls.can_promote(from_category, to_category):
            allowed = sorted(c.value for c in cls.ALLOWED_PROMOTIONS[from_category])
            raise IllegalPromotionError(
                f"{from_category.value} -> {to_category.value} is not in the "
                f"sharing matrix; allowed destinations: {allowed or 'none'}"
            )

    @classmethod
    def reviewer_note_required(cls, to_category: WorldCategory) -> bool:
        return to_category in cls.NOTE_REQUIRED_TARGETS

    @classmethod
    def permission_diff(
        cls,
        world: WorldManifest,
        from_category: WorldCategory,
        to_category: WorldCategory,
    ) -> PermissionDiff:
        """Who becomes newly able to see the world, computed before deciding."""
        before = world.audience(from_category)
        after = world.audience(to_category)
        return PermissionDiff(
            from_category=from_category,
            to_category=to_category,
            before=before,
            after=after,
            newly_visible=tuple(sorted(after - before)),
        )


def promote(
    world: WorldManifest,
    from_category: WorldCategory | str,
    to_category: WorldCategory | str,
    actor_roles: Collection[str],
    reviewer_note: str | None = None,
) -> PromotionDecision:
    """Ask to move a world from one category to another.

    Raises :class:`IllegalPromotionError` for anything the matrix forbids
    outright — including promoting out of ``PRIVATE_PERSONAL`` — and for
    requests decided against a stale view of the world's current category.
    Returns an approved decision (with the resulting manifest) or a refusal
    (with reasons) for everything that is a judgement rather than a violation.
    """
    from_cat = WorldCategory(from_category)
    to_cat = WorldCategory(to_category)

    SharingPolicy.require_promotable(from_cat, to_cat)

    if world.category != from_cat:
        raise IllegalPromotionError(
            f"{world.world_id} currently reads as {world.category.value}, not "
            f"{from_cat.value}: refusing a promotion decided against a stale view"
        )

    diff = SharingPolicy.permission_diff(world, from_cat, to_cat)
    reasons: list[str] = []

    note = reviewer_note.strip() if reviewer_note else ""
    if SharingPolicy.reviewer_note_required(to_cat) and not note:
        reasons.append(f"reaching {to_cat.value} requires a reviewer note")

    required = SharingPolicy.TARGET_MINIMUM_ROLE.get(to_cat)
    if required is not None and not _role_satisfied(actor_roles, required):
        reasons.append(
            f"promoting to {to_cat.value} requires {required.value} or above"
        )

    approved = not reasons
    return PromotionDecision(
        world_id=world.world_id,
        from_category=from_cat,
        to_category=to_cat,
        approved=approved,
        permission_diff=diff,
        reasons=tuple(reasons),
        reviewer_note=note or None,
        resulting_manifest=world.with_category(to_cat) if approved else None,
    )
