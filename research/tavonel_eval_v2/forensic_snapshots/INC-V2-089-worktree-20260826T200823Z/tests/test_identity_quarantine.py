"""Rung 3 of the INC-V2-047 quarantine ladder: the adversarial control battery.

Ten controls. Nine were named by the founder; the tenth is the property the
repair is most likely to lose while looking correct, and it is the reason the
module docstring of `akc_cir.identity_quarantine` says membership is only half
the requirement.

**Every control is a predicate over a diff, and every control is shown able to
come back RED.** A control that cannot fail is not a measurement -- INC-V2-044
is what a hardcoded answer looks like from the inside, and INC-V2-036 is the
same thing wearing the other sign. Each `test_control_N_*` has a
`test_control_N_*__can_come_back_red` beside it, and the red is produced by one
of exactly three named mutations:

``pin_off``
    The real pre-repair path, `quarantine_unsettled_identity=False`. The
    strongest red available, because it is production rather than a simulation
    of it.
``over_quarantine``
    `akc_cir.semantic_diff.build_quarantine` replaced, through `monkeypatch`
    and never by editing the module, with one that quarantines every unit on
    either side. This is the over-quarantine defect made real: it runs the
    production code path and asks whether the control notices that every
    genuine change has become unresolved. Over-quarantine is its own defect, not
    a safe direction to err in -- it converts real changes into unresolved and
    destroys the diff's usefulness -- which is why five controls are pointed
    straight at it.
``doctored_records``
    A `SemanticDiff` rebuilt with one record altered. Used only where neither
    of the above can reach the shape, and labelled as the weakest of the three
    because it tests the predicate rather than the system.

**The nine V1 cases are development fixtures.** Control 8 replays them from the
frozen universe of `IDENTITY_CHANGE_MIGRATION_CLOSURE_V1` and asserts the repair
closes them. That is a **development regression** and nothing more.
IDENTITY_CHANGE_MIGRATION_CLOSURE_V1 graded FAIL on INVARIANT_6; that verdict is
permanent, is not rescored here, and these nine cases cannot certify the repair
prospectively -- they are the cases the repair was written after seeing.

**Nothing here flips `QUARANTINE_UNSETTLED_IDENTITY_DEFAULT`.** Every call passes
`quarantine_unsettled_identity` explicitly, so the battery measures the same
behaviour whichever way that module-level switch happens to be set. The switch
is rung 5 and belongs to a different act.
"""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

NS = Path(__file__).resolve().parents[1]
for _sub in ("tools", "acquisition", "canonicalization", "compiler", "source_fact_ir"):
    sys.path.insert(0, str(NS / _sub))
sys.path.insert(0, str(NS))
ROOT = NS.parents[1]
sys.path.insert(0, str(ROOT / "packages" / "cir-python" / "src"))

import selective_build as engine  # noqa: E402
from akc_cir import semantic_diff as sd  # noqa: E402
from akc_cir.identity import (  # noqa: E402
    LogicalIdentityResolver,
    LogicalMatch,
    assign_one_to_one,
)
from akc_cir.identity_quarantine import (  # noqa: E402
    IdentityQuarantine,
    QuarantineMember,
    build_quarantine,
)
from akc_cir.semantic_diff import (  # noqa: E402
    ChangeChannel,
    ChangeKind,
    DiffLevel,
    DocumentShape,
    SemanticChange,
    SemanticDiff,
    UnitSnapshot,
    diff_documents,
)
from identity_change_migration_closure import universe_receipt  # noqa: E402

A = "sha256:" + "a" * 64
B = "sha256:" + "b" * 64

#: Kinds that assert a settled decision about a unit. A quarantined unit may
#: carry none of them. Same set the closure calls CONTINUITY_ASSERTING_KINDS,
#: restated here rather than imported so this battery does not inherit the
#: closure's opinion of its own subject.
DEFINITE_KINDS = frozenset(
    {ChangeKind.MODIFIED_CLAIM, ChangeKind.UNIT_ADDED, ChangeKind.UNIT_REMOVED}
)

#: The projection control 9 compares across the two content predicates: the
#: records that are statements about *matching* rather than about an
#: already-matched pair's content.
IDENTITY_SENSITIVE_KINDS = frozenset(
    {
        ChangeKind.UNIT_ADDED,
        ChangeKind.UNIT_REMOVED,
        ChangeKind.IDENTITY_UNRESOLVED,
        ChangeKind.EVIDENCE_MOVED,
    }
)

#: The declaration the canary reads. `(name, requirement, red_mutation)`.
#: `tools/canary_identity_quarantine.py` derives its expectations from this
#: table and checks that every row has both a control test and a red test, so a
#: control that is edited moves the gate with it. A canary whose expectations
#: are a hand-written copy of the controls gates on nothing but the author's
#: memory of them.
CONTROLS: tuple[tuple[str, str, str], ...] = (
    (
        "control_1_ambiguous_same_logical_id_counterpart_is_never_removed",
        "the INC-V2-047 shape: a before-side unit sharing the logical id of an "
        "incoming unit whose identity is unsettled is reported unresolved, never removed",
        "pin_off",
    ),
    (
        "control_2_a_candidate_never_receives_a_concrete_outcome",
        "no unit named as a candidate of an unsettled decision carries "
        "modified_claim, unit_added or unit_removed",
        "doctored_records",
    ),
    (
        "control_3_a_clear_same_id_match_remains_matched",
        "a unit that matches cleanly is still matched and still reports its "
        "content change; the repair does not touch settled identities",
        "over_quarantine",
    ),
    (
        "control_4_a_genuine_removal_remains_removed",
        "a unit that really disappeared is still reported unit_removed",
        "over_quarantine",
    ),
    (
        "control_5_a_genuine_addition_remains_added",
        "a unit that really appeared is still reported unit_added",
        "over_quarantine",
    ),
    (
        "control_6_ambiguity_does_not_quarantine_unrelated_units",
        "over-quarantine is its own defect: an ambiguity elsewhere in the "
        "document must leave a clean match, a genuine removal and a genuine "
        "addition exactly as they were",
        "over_quarantine",
    ),
    (
        "control_7_many_to_one_one_to_many_tie_and_restructured",
        "the four hard matching shapes each leave every implicated unit "
        "unresolved and no implicated unit definitely classified",
        "pin_off",
    ),
    (
        "control_8_the_nine_v1_failures_replay_and_close",
        "the nine INVARIANT_6 violations of "
        "IDENTITY_CHANGE_MIGRATION_CLOSURE_V1 replay as DEVELOPMENT regressions "
        "and all close under the repair; they certify nothing prospectively",
        "pin_off",
    ),
    (
        "control_9_legacy_and_new_content_predicates_still_agree",
        "the identity repair is orthogonal to the INC-V2-037 content predicate: "
        "the identity-sensitive projection is identical under "
        "legacy_identity_change_predicate True and False",
        "doctored_records",
    ),
    (
        "control_10_every_quarantined_unit_stays_visible",
        "a quarantined unit is reachable from SemanticDiff.unresolved, is on "
        "the UNRESOLVED channel, and does not enter changed_logical_ids: a "
        "fail-closed endpoint cannot score an absence",
        "pin_off",
    ),
)

RED_MUTATIONS = ("pin_off", "over_quarantine", "doctored_records")


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------

SRC = "src:reports"
HEAD = "Sec 1 Content of the reports."

ALPHA = (
    "If the system has performed any monitoring for Cryptosporidium, including "
    "monitoring performed to satisfy the requirements of subpart W, it must "
    "report those results."
)
BETA = (
    "The report must contain a brief explanation regarding contaminants which "
    "may reasonably be expected to be found in drinking water, including "
    "bottled water."
)
BETA_EDITED = (
    "The report must contain a brief explanation regarding contaminants which "
    "may reasonably be expected to be found in drinking water, including "
    "bottled water and private wells."
)
GAMMA = (
    "Each community water system must deliver one copy of the report to the "
    "primacy agency no later than the date the report is distributed."
)
GAMMA_EDITED = (
    "Each community water system must deliver two copies of the report to the "
    "primacy agency no later than the date the report is distributed."
)
DELTA = (
    "Nothing in this section shall be construed to affect the operation of an "
    "existing variance or exemption granted under subpart K."
)
EPSILON = (
    "A supplier of water shall retain copies of each report for no fewer than "
    "three years after the date of distribution."
)


def unit(
    logical_id: str,
    part: str,
    text: str,
    *,
    previous: str = "(3)",
    following: str = "(i)",
    heading: str = HEAD,
    **overrides: Any,
) -> UnitSnapshot:
    fields: dict[str, Any] = {
        "logical_id": logical_id,
        "text": text,
        "document_path": (SRC, heading, part),
        "anchor": part.split("#")[0],
        "neighbour_anchors": (previous, following),
        "explicit_identifier": f"{heading}/{part}",
        "evidence_id": "e:" + logical_id,
    }
    fields.update(overrides)
    return UnitSnapshot(**fields)


def shape_of(units: list[UnitSnapshot]) -> DocumentShape:
    return DocumentShape(
        heading_path_set=frozenset(item.document_path for item in units),
        block_count=len(units),
        unit_order=tuple(item.logical_id for item in units),
    )


def run_diff(
    before: list[UnitSnapshot],
    after: list[UnitSnapshot],
    *,
    pin: bool,
    legacy: bool = False,
) -> SemanticDiff:
    """`diff_documents` with the pin passed EXPLICITLY, always.

    Never `None`. Reading the module default would make this battery measure
    whichever way another lane's switch happens to be set this minute, and the
    whole point of a two-armed control is that both arms are chosen here.
    """
    return diff_documents(
        before_sha256=A,
        after_sha256=B,
        level=DiffLevel.GRAPH,
        before_shape=shape_of(before),
        after_shape=shape_of(after),
        before_units=before,
        after_units=after,
        source=SRC,
        legacy_identity_change_predicate=legacy,
        quarantine_unsettled_identity=pin,
    )


def restructured_section() -> tuple[list[UnitSnapshot], list[UnitSnapshot]]:
    """The INC-V2-047 shape, reproduced from the real `ecfr:40:141:141.153` case.

    A `logical_id` is a pure function of source id and explicit path, so the
    section that was restructured yields the SAME id on both sides carrying
    different text. `u:p1` is that id. The incoming `u:p1` reads like the
    before-side `u:p2` and scores 0.76 against it -- inside the 0.75-0.92 review
    band -- so the resolver returns AMBIGUOUS naming `u:p2`, and the before-side
    `u:p1` is implicated by the same unsettled question while being named by
    nobody.

    The neighbour anchors are what makes the incoming prefer `u:p2`: they are
    the real case's mechanism (the incoming unit sits where `u:p2` sat), and
    without them the explicit-identifier signal carries `u:p1` to the top and
    the fixture quietly stops being about anything.
    """
    before = [
        unit("u:p1", "(1)#2", ALPHA, previous="zeta", following="omega"),
        unit("u:p2", "(1)#3", BETA),
    ]
    after = [unit("u:p1", "(1)#2", BETA_EDITED)]
    return before, after


def clean_match() -> tuple[list[UnitSnapshot], list[UnitSnapshot]]:
    """Same id, same place, an edited sentence. Identity is not in question."""
    before = [unit("u:clean", "(2)", GAMMA)]
    after = [unit("u:clean", "(2)", GAMMA_EDITED)]
    return before, after


def genuine_removal() -> tuple[list[UnitSnapshot], list[UnitSnapshot]]:
    before = [
        unit("u:clean", "(2)", GAMMA),
        unit("u:gone", "(9)", DELTA, previous="(8)", following="(10)"),
    ]
    after = [unit("u:clean", "(2)", GAMMA)]
    return before, after


def genuine_addition() -> tuple[list[UnitSnapshot], list[UnitSnapshot]]:
    before = [unit("u:clean", "(2)", GAMMA)]
    after = [
        unit("u:clean", "(2)", GAMMA),
        unit("u:fresh", "(9)", EPSILON, previous="(8)", following="(10)"),
    ]
    return before, after


def ambiguity_beside_settled_work() -> tuple[list[UnitSnapshot], list[UnitSnapshot]]:
    """Control 6's document: one ambiguity, and three settled decisions beside it.

    The three are in a different heading so the ambiguity's candidate window
    cannot reach them by structural proximity, which is how a real document
    separates an unstable subsection from the rest of itself.
    """
    other = "Sec 2 Retention of reports."
    ambiguous_before, ambiguous_after = restructured_section()
    before = [
        *ambiguous_before,
        unit("u:clean", "(2)", GAMMA, heading=other, previous="(1)", following="(3)"),
        unit("u:gone", "(9)", DELTA, heading=other, previous="(8)", following="(10)"),
    ]
    after = [
        *ambiguous_after,
        unit("u:clean", "(2)", GAMMA_EDITED, heading=other, previous="(1)", following="(3)"),
        unit("u:fresh", "(11)", EPSILON, heading=other, previous="(10)", following="(12)"),
    ]
    return before, after


#: Why every hard shape below moves the explicit path and keeps everything else.
#:
#: With source continuity 1.0, a one-step path disagreement (0.667), a differing
#: explicit identifier (0.0), identical text and identical neighbours, the
#: renormalised score is
#:
#:     (0.25 + 0.20*0.667 + 0.15*0 + 0.15*1 + 0.10*1 + 0.10*1) / 0.95 = 0.772
#:
#: which is the 0.75-0.92 review band, and 0.772 is the same score the real
#: `ecfr:40:141:141.153` case lands on. Keeping the texts IDENTICAL is
#: deliberate: a paraphrase drops the semantic signal and slides the pair under
#: the 0.75 floor, where the resolver answers NEW and the fixture stops being
#: about ambiguity at all. The first draft of these three did exactly that and
#: produced no quarantine.


def many_to_one() -> tuple[list[UnitSnapshot], list[UnitSnapshot]]:
    """Two incoming units contend for one before unit.

    `assign_one_to_one` may award the before unit to only one of them, and that
    one lands in the review band; the other is NEW.
    """
    before = [unit("u:one", "(4)", GAMMA)]
    after = [
        unit("u:one-b", "(4)#2", GAMMA),
        unit("u:one-c", "(4)#3", GAMMA),
    ]
    return before, after


def one_to_many() -> tuple[list[UnitSnapshot], list[UnitSnapshot]]:
    """One incoming unit contends among several before units.

    `u:twin-b` reads nothing like it, so it is a genuine removal sitting next to
    an unsettled decision -- which is control 6's property observed inside
    control 7's shape.
    """
    before = [
        unit("u:twin-a", "(5)", GAMMA),
        unit("u:twin-b", "(5)#2", DELTA),
    ]
    after = [unit("u:twin-c", "(5)#3", GAMMA)]
    return before, after


def scoring_tie() -> tuple[list[UnitSnapshot], list[UnitSnapshot]]:
    """Two candidates the score cannot separate: the tie band, by construction.

    Identical text and identical neighbours on both before units, so the two
    scores are equal and the gap is 0.00 -- inside the 0.05 tie band, where
    merging would pick one history arbitrarily.
    """
    before = [
        unit("u:tie-a", "(6)", GAMMA, previous="(5)", following="(7)"),
        unit("u:tie-b", "(6)#2", GAMMA, previous="(5)", following="(7)"),
    ]
    after = [unit("u:tie-c", "(6)#3", GAMMA, previous="(5)", following="(7)")]
    return before, after


HARD_SHAPES = {
    "many_to_one": many_to_one,
    "one_to_many": one_to_many,
    "tie": scoring_tie,
    "restructured_section": restructured_section,
}


# --------------------------------------------------------------------------
# predicates -- one per control, each usable on any diff
# --------------------------------------------------------------------------


def records_by_unit(diff: SemanticDiff) -> dict[str, set[ChangeKind]]:
    index: dict[str, set[ChangeKind]] = {}
    for change in diff.changes:
        if change.logical_id:
            index.setdefault(change.logical_id, set()).add(change.kind)
    return index


def kinds_on(diff: SemanticDiff, logical_id: str) -> set[str]:
    return {kind.value for kind in records_by_unit(diff).get(logical_id, set())}


def identity_projection(diff: SemanticDiff) -> dict[str, frozenset[str]]:
    """Only the records that are statements about matching. Control 9's subject."""
    index: dict[str, set[str]] = {}
    for change in diff.changes:
        if change.kind in IDENTITY_SENSITIVE_KINDS and change.logical_id:
            index.setdefault(change.logical_id, set()).add(change.kind.value)
    return {unit_id: frozenset(kinds) for unit_id, kinds in index.items()}


def quarantine_for(
    before: list[UnitSnapshot], after: list[UnitSnapshot], source: str
) -> IdentityQuarantine:
    """`diff_documents`' quarantine, reproduced from the same inputs.

    Reproduced rather than read off the diff because membership is the thing
    under test: asking the diff which units it quarantined and then asking
    whether it treated them correctly would be asking one artifact to grade
    itself. Same `assign_one_to_one`, same fingerprints, same lineage, so a
    divergence here is a bug rather than a difference of policy.
    """
    decisions = assign_one_to_one(
        [item.fingerprint(source_lineage=source) for item in after],
        [item.fingerprint(source_lineage=source) for item in before],
        resolver=LogicalIdentityResolver(),
    )
    paired = list(zip(after, decisions, strict=True))
    return build_quarantine(
        unsettled_decisions=[
            (incoming.logical_id, decision.candidates, decision.logical_id)
            for incoming, decision in paired
            if decision.match is LogicalMatch.AMBIGUOUS
        ],
        definite_matches=[
            (incoming.logical_id, decision.logical_id)
            for incoming, decision in paired
            if decision.match is not LogicalMatch.AMBIGUOUS and decision.logical_id
        ],
        before_ids=frozenset(item.logical_id for item in before),
    )


def unsettled_units_carrying_a_definite_outcome(diff: SemanticDiff) -> list[dict[str, Any]]:
    """Controls 1, 2 and 7's shared predicate.

    A unit is implicated if it is the subject of an `identity_unresolved` record
    or is named in one's `candidates`. None of them may carry a definite outcome.
    """
    index = records_by_unit(diff)
    implicated: dict[str, str] = {}
    for change in diff.unresolved:
        if change.logical_id:
            implicated.setdefault(change.logical_id, "subject of an unresolved record")
        for candidate in change.candidates or ():
            if candidate:
                implicated.setdefault(candidate, "candidate of an unresolved record")

    out: list[dict[str, Any]] = []
    for logical_id, why in sorted(implicated.items()):
        asserted = sorted(
            kind.value for kind in index.get(logical_id, set()) & DEFINITE_KINDS
        )
        if asserted:
            out.append({"logical_id": logical_id, "implicated_as": why, "kinds": asserted})
    return out


def quarantined_units_that_are_invisible(
    diff: SemanticDiff, quarantine: IdentityQuarantine
) -> list[dict[str, Any]]:
    """Control 10. Every member must be reachable from `SemanticDiff.unresolved`.

    "Reachable" is the subject of an unresolved record OR named in one's
    `candidates`. The stricter reading -- a record of its own per member -- is
    reported separately by `quarantined_units_without_their_own_record`, because
    production deliberately does not do that for a declared candidate: it is
    already named by the record of the incoming unit whose identity it might
    continue, and giving it a second record made a two-candidate ambiguity emit
    three records where one was correct.
    """
    reachable: set[str] = set()
    for change in diff.unresolved:
        if change.logical_id:
            reachable.add(change.logical_id)
        reachable.update(candidate for candidate in (change.candidates or ()) if candidate)
    return [
        {
            "logical_id": logical_id,
            "reason": quarantine.reason_for(logical_id),
            "why": (
                "quarantined and reachable from no unresolved record: a withheld "
                "statement replaced by no statement, which a fail-closed endpoint "
                "cannot score"
            ),
        }
        for logical_id in sorted(quarantine.members)
        if logical_id not in reachable
    ]


def quarantined_units_without_their_own_record(
    diff: SemanticDiff, quarantine: IdentityQuarantine
) -> list[str]:
    """The stricter visibility reading. Reported, never asserted: see above."""
    subjects = {change.logical_id for change in diff.unresolved if change.logical_id}
    return sorted(logical_id for logical_id in quarantine.members if logical_id not in subjects)


def unresolved_units_in_the_recompilation_seed_set(diff: SemanticDiff) -> list[str]:
    """Control 10's second half. An unsettled identity is not a modification."""
    seeds = set(diff.changed_logical_ids)
    return sorted(
        change.logical_id
        for change in diff.unresolved
        if change.logical_id and change.logical_id in seeds
    )


def unresolved_records_off_channel(diff: SemanticDiff) -> list[str]:
    return sorted(
        change.logical_id or "<no id>"
        for change in diff.unresolved
        if change.channel is not ChangeChannel.UNRESOLVED
    )


# --------------------------------------------------------------------------
# the three red mutations
# --------------------------------------------------------------------------


@pytest.fixture
def over_quarantine(monkeypatch: pytest.MonkeyPatch):
    """Install the over-quarantine defect inside the production code path.

    `monkeypatch`, never an edit: `akc_cir.semantic_diff` and
    `akc_cir.identity_quarantine` are Protected Core and belong to another lane.
    A defect found in either is reported with a failing test, not patched.

    The installed builder withholds every before-side unit, plus any extra ids
    the caller names. **Extras are necessary, not laziness.** `build_quarantine`
    is handed `before_ids`, the unsettled decisions' candidates, and the definite
    matches -- and a NEW incoming unit appears in none of them, because
    `diff_documents` fills a NEW decision's `logical_id` only after the
    quarantine has been built. So an over-quarantine reconstructed from the real
    arguments cannot reach a genuine addition, and a red for control 5 has to
    name it. That is a property of the contract's inputs, not a defect: a NEW
    unit's own id still reaches the real quarantine through clauses (1)-(3) when
    some decision implicates it, which is what the corpus differential observes
    41 times.
    """

    def install(*extra: str) -> None:
        def fake(
            *,
            unsettled_decisions: Any = (),
            definite_matches: Any = (),
            before_ids: Any = frozenset(),
        ) -> IdentityQuarantine:
            return IdentityQuarantine(
                members={
                    logical_id: QuarantineMember(
                        logical_id=logical_id,
                        reason="over-quarantine mutation: everything is unsafe",
                        implicated_by="<mutation>",
                    )
                    for logical_id in sorted(set(before_ids) | set(extra))
                }
            )

        monkeypatch.setattr(sd, "build_quarantine", fake)

    return install


def doctor(diff: SemanticDiff, *, drop: Any = None, add: Any = None) -> SemanticDiff:
    """A diff with one record removed and/or one added. The weakest red.

    It exercises the predicate rather than the system, which is why only the two
    controls that neither `pin_off` nor `over_quarantine` can reach use it, and
    why both of them say so in `CONTROLS`.
    """
    changes = tuple(change for change in diff.changes if change is not drop)
    if add is not None:
        changes = (*changes, add)
    return replace(diff, changes=changes)


# --------------------------------------------------------------------------
# the frozen universe -- controls 8 and 9
# --------------------------------------------------------------------------

#: The nine INVARIANT_6 violations of IDENTITY_CHANGE_MIGRATION_CLOSURE_V1,
#: transcribed from `receipts/identity-change-migration-closure--20260825T001037Z
#: -bee4064eae33.json`. DEVELOPMENT FIXTURES. The V1 FAIL is permanent and is not
#: rescored by anything below; these nine are the cases the repair was written
#: after seeing, so they can demonstrate closure and can certify nothing.
V1_INVARIANT_6_CASES: tuple[tuple[str, str], ...] = (
    ("ecfr:40:141:141.153", "u:aad22330ba59cb2db5271716"),
    ("ecfr:42:422:422.100", "u:b0a99e39ca6c476fc5496db9"),
    ("ecfr:42:422:422.101", "u:8341eaf0ee778ef54d32cbb0"),
    ("ecfr:42:422:422.111", "u:428252a6c1e5c8640ae81ed7"),
    ("ecfr:42:482:482.21", "u:fb2908a47001807f6ebc2ebf"),
    ("ecfr:49:571:571.106", "u:584953a849e1683e9bbae8f5"),
    ("ecfr:50:17:17.21", "u:40a6edb55ee42d113a2bc573"),
    ("ecfr:50:17:17.21", "u:9327aad7f7f428595f018be9"),
    ("git:prometheus/prometheus:docs/configuration/configuration.md", "u:2812935fff1a10ec76712c88"),
)

V1_RECEIPT = (
    NS / "receipts" / "identity-change-migration-closure--20260825T001037Z-bee4064eae33.json"
)


def _universe_rows() -> dict[str, dict[str, Any]]:
    return {row["lineage_id"]: row for row in universe_receipt()["pairs"]}


def _corpus_units(row: dict[str, Any]) -> tuple[list[UnitSnapshot], list[UnitSnapshot], str]:
    before_document = json.loads(
        (ROOT / row["before"]["canonical_path"]).read_text(encoding="utf-8")
    )
    after_document = json.loads(
        (ROOT / row["after"]["canonical_path"]).read_text(encoding="utf-8")
    )
    before_units, _ = engine.snapshots(before_document)
    after_units, _ = engine.snapshots(after_document)
    return before_units, after_units, after_document["source_id"]


def _corpus_diff(row: dict[str, Any], *, pin: bool, legacy: bool = False) -> SemanticDiff:
    before_units, after_units, source = _corpus_units(row)
    return diff_documents(
        before_sha256="sha256:corpus-before",
        after_sha256="sha256:corpus-after",
        level=DiffLevel.GRAPH,
        before_shape=shape_of(before_units),
        after_shape=shape_of(after_units),
        before_units=before_units,
        after_units=after_units,
        source=source,
        legacy_identity_change_predicate=legacy,
        quarantine_unsettled_identity=pin,
    )


@pytest.fixture(scope="module")
def universe() -> dict[str, dict[str, Any]]:
    return _universe_rows()


# --------------------------------------------------------------------------
# the declaration itself
# --------------------------------------------------------------------------


def test_every_declared_control_has_a_test_and_a_red_test() -> None:
    """A declared control with no test is a control that silently never ran.

    This study's oldest defect, and the reason the closure's fixture battery
    checks the same correspondence in the other direction.
    """
    module = sys.modules[__name__]
    missing = []
    for name, _requirement, mutation in CONTROLS:
        if not hasattr(module, f"test_{name}"):
            missing.append(f"test_{name}")
        if not hasattr(module, f"test_{name}__can_come_back_red"):
            missing.append(f"test_{name}__can_come_back_red")
        assert mutation in RED_MUTATIONS, (name, mutation)
    assert not missing, missing
    assert len(CONTROLS) == 10
    assert len({name for name, _, _ in CONTROLS}) == 10


def test_the_battery_never_reads_the_production_switch() -> None:
    """Whichever way rung 5's switch is set, this battery measures the same thing.

    Asserted rather than trusted: `quarantine_unsettled_identity=None` reads
    `QUARANTINE_UNSETTLED_IDENTITY_DEFAULT`, and a helper that forgot to pass the
    pin would make half the controls follow another lane's edit.
    """
    before, after = restructured_section()
    for pin in (False, True):
        explicit = run_diff(before, after, pin=pin)
        assert [change.as_record() for change in explicit.changes] == [
            change.as_record()
            for change in diff_documents(
                before_sha256=A,
                after_sha256=B,
                level=DiffLevel.GRAPH,
                before_shape=shape_of(before),
                after_shape=shape_of(after),
                before_units=before,
                after_units=after,
                source=SRC,
                quarantine_unsettled_identity=pin,
            ).changes
        ]


def test_the_fixture_actually_reaches_the_inc_v2_047_shape() -> None:
    """The fixture is only worth anything if the resolver lands where it did in
    `ecfr:40:141:141.153`: AMBIGUOUS on the incoming, naming a DIFFERENT
    before-side unit, while a before-side unit carries the incoming's own id.

    Without this the fixture could drift into "AMBIGUOUS naming itself", which
    the pre-repair code already handled, and every control below would pass
    against a case that was never the defect.
    """
    before, after = restructured_section()
    quarantine = quarantine_for(before, after, SRC)
    decisions = assign_one_to_one(
        [item.fingerprint(source_lineage=SRC) for item in after],
        [item.fingerprint(source_lineage=SRC) for item in before],
        resolver=LogicalIdentityResolver(),
    )
    assert [decision.match for decision in decisions] == [LogicalMatch.AMBIGUOUS]
    assert decisions[0].candidates == ("u:p2",)
    assert "u:p1" in {item.logical_id for item in before}
    assert "u:p1" in {item.logical_id for item in after}
    assert quarantine.reason_for("u:p1") is not None
    assert quarantine.reason_for("u:p2") is not None


# --------------------------------------------------------------------------
# control 1
# --------------------------------------------------------------------------


def test_control_1_ambiguous_same_logical_id_counterpart_is_never_removed() -> None:
    before, after = restructured_section()
    diff = run_diff(before, after, pin=True)
    assert "unit_removed" not in kinds_on(diff, "u:p1")
    assert "identity_unresolved" in kinds_on(diff, "u:p1")
    assert not unsettled_units_carrying_a_definite_outcome(diff)


def test_control_1_ambiguous_same_logical_id_counterpart_is_never_removed__can_come_back_red() -> (
    None
):
    """The red is production before the repair, not a simulation of it.

    Under pin OFF the diff carries both statements about `u:p1`: its identity is
    unsettled, and it was deleted. That is INC-V2-047 verbatim.
    """
    before, after = restructured_section()
    diff = run_diff(before, after, pin=False)
    assert "unit_removed" in kinds_on(diff, "u:p1")
    assert "identity_unresolved" in kinds_on(diff, "u:p1")
    assert unsettled_units_carrying_a_definite_outcome(diff) == [
        {
            "logical_id": "u:p1",
            "implicated_as": "subject of an unresolved record",
            "kinds": ["unit_removed"],
        }
    ]


# --------------------------------------------------------------------------
# control 2
# --------------------------------------------------------------------------


def implicated_units(diff: SemanticDiff) -> set[str]:
    """Every unit an unresolved record implicates, as subject or as candidate.

    Extracted so control 2 can assert it is watching SOMETHING. Its predicate
    derives the population from the unresolved records themselves, so a diff
    with no unresolved records satisfies it vacuously -- a mutation that drops
    every unresolved record leaves control 2 green while destroying exactly the
    visibility control 10 exists for. Both halves are needed; neither substitutes
    for the other, and this function is what makes that explicit rather than
    accidental.
    """
    out: set[str] = set()
    for change in diff.unresolved:
        if change.logical_id:
            out.add(change.logical_id)
        out.update(candidate for candidate in (change.candidates or ()) if candidate)
    return out


def test_control_2_a_candidate_never_receives_a_concrete_outcome() -> None:
    for name, builder in HARD_SHAPES.items():
        before, after = builder()
        diff = run_diff(before, after, pin=True)
        #: non-vacuity first: a clean answer from a predicate with an empty
        #: population is this study's most-repeated defect
        assert implicated_units(diff), name
        assert not unsettled_units_carrying_a_definite_outcome(diff), name


def test_control_2_a_candidate_never_receives_a_concrete_outcome__can_come_back_red() -> None:
    """Neither pin OFF nor over-quarantine reaches this shape.

    Pin OFF already protects a NAMED candidate from removal -- that is what
    `unsettled.update(decision.candidates)` was for, and it is the half of the
    problem INC-V2-047 was NOT about -- and over-quarantine withholds more
    rather than less. So the red is a doctored record: a candidate given the
    `unit_removed` the contract forbids.
    """
    before, after = restructured_section()
    diff = run_diff(before, after, pin=True)
    doctored = doctor(
        diff,
        add=SemanticChange(kind=ChangeKind.UNIT_REMOVED, logical_id="u:p2", before=BETA),
    )
    assert unsettled_units_carrying_a_definite_outcome(doctored) == [
        {
            "logical_id": "u:p2",
            "implicated_as": "candidate of an unresolved record",
            "kinds": ["unit_removed"],
        }
    ]


# --------------------------------------------------------------------------
# control 3
# --------------------------------------------------------------------------


def test_control_3_a_clear_same_id_match_remains_matched() -> None:
    before, after = clean_match()
    diff = run_diff(before, after, pin=True)
    assert kinds_on(diff, "u:clean") == {"modified_claim"}
    assert diff.unresolved == ()
    assert diff.changed_logical_ids == ("u:clean",)


def test_control_3_a_clear_same_id_match_remains_matched__can_come_back_red(
    over_quarantine,
) -> None:
    over_quarantine()
    before, after = clean_match()
    diff = run_diff(before, after, pin=True)
    assert kinds_on(diff, "u:clean") == {"identity_unresolved"}
    assert diff.changed_logical_ids == ()


# --------------------------------------------------------------------------
# control 4
# --------------------------------------------------------------------------


def test_control_4_a_genuine_removal_remains_removed() -> None:
    before, after = genuine_removal()
    diff = run_diff(before, after, pin=True)
    assert kinds_on(diff, "u:gone") == {"unit_removed"}
    assert diff.unresolved == ()


def test_control_4_a_genuine_removal_remains_removed__can_come_back_red(
    over_quarantine,
) -> None:
    over_quarantine()
    before, after = genuine_removal()
    diff = run_diff(before, after, pin=True)
    assert "unit_removed" not in kinds_on(diff, "u:gone")
    assert "identity_unresolved" in kinds_on(diff, "u:gone")


# --------------------------------------------------------------------------
# control 5
# --------------------------------------------------------------------------


def test_control_5_a_genuine_addition_remains_added() -> None:
    before, after = genuine_addition()
    diff = run_diff(before, after, pin=True)
    assert kinds_on(diff, "u:fresh") == {"unit_added"}
    assert diff.unresolved == ()


def test_control_5_a_genuine_addition_remains_added__can_come_back_red(
    over_quarantine,
) -> None:
    """`u:fresh` has to be named, and the fixture's docstring says why: a NEW
    unit's id reaches `build_quarantine` through none of its three arguments.
    """
    over_quarantine("u:fresh")
    before, after = genuine_addition()
    diff = run_diff(before, after, pin=True)
    assert "unit_added" not in kinds_on(diff, "u:fresh")
    assert "identity_unresolved" in kinds_on(diff, "u:fresh")
    assert diff.changed_logical_ids == ()


# --------------------------------------------------------------------------
# control 6
# --------------------------------------------------------------------------


def test_control_6_ambiguity_does_not_quarantine_unrelated_units() -> None:
    before, after = ambiguity_beside_settled_work()
    diff = run_diff(before, after, pin=True)

    #: the ambiguity did happen -- otherwise this control proves nothing
    assert "identity_unresolved" in kinds_on(diff, "u:p1")

    #: and it reached none of the three settled decisions beside it
    assert kinds_on(diff, "u:clean") == {"modified_claim"}
    assert kinds_on(diff, "u:gone") == {"unit_removed"}
    assert kinds_on(diff, "u:fresh") == {"unit_added"}

    quarantine = quarantine_for(before, after, SRC)
    assert "u:clean" not in quarantine
    assert "u:gone" not in quarantine
    assert "u:fresh" not in quarantine


def test_control_6_ambiguity_does_not_quarantine_unrelated_units__can_come_back_red(
    over_quarantine,
) -> None:
    """Over-quarantine converts both settled *before-side* decisions.

    `u:fresh` is deliberately left out of the `extra` list here: a mutation that
    also named it would prove nothing this red does not already show, and the
    asymmetry is worth leaving visible -- it is the same input-coverage fact
    control 5's red is built on.
    """
    over_quarantine()
    before, after = ambiguity_beside_settled_work()
    diff = run_diff(before, after, pin=True)
    assert kinds_on(diff, "u:clean") == {"identity_unresolved"}
    assert kinds_on(diff, "u:gone") == {"identity_unresolved"}
    assert "u:clean" not in diff.changed_logical_ids


# --------------------------------------------------------------------------
# control 7
# --------------------------------------------------------------------------


def test_control_7_many_to_one_one_to_many_tie_and_restructured() -> None:
    for name, builder in HARD_SHAPES.items():
        before, after = builder()
        diff = run_diff(before, after, pin=True)
        quarantine = quarantine_for(before, after, SRC)
        assert quarantine, name
        assert implicated_units(diff), name
        assert not unsettled_units_carrying_a_definite_outcome(diff), name
        assert not quarantined_units_that_are_invisible(diff, quarantine), name
        assert not unresolved_units_in_the_recompilation_seed_set(diff), name
        assert not unresolved_records_off_channel(diff), name


def test_control_7_many_to_one_one_to_many_tie_and_restructured__can_come_back_red() -> None:
    """At least one of the four shapes must be visibly worse under pin OFF.

    Asserted as "at least one", not "all four": three of them are shapes the
    pre-repair code already handled through the named-candidate path, and
    demanding that all four go red would be a prediction about which shapes the
    old defect touched rather than a control.
    """
    reds = []
    for name, builder in HARD_SHAPES.items():
        before, after = builder()
        diff = run_diff(before, after, pin=False)
        quarantine = quarantine_for(before, after, SRC)
        if (
            unsettled_units_carrying_a_definite_outcome(diff)
            or quarantined_units_that_are_invisible(diff, quarantine)
            or unresolved_units_in_the_recompilation_seed_set(diff)
        ):
            reds.append(name)
    assert "restructured_section" in reds, reds


# --------------------------------------------------------------------------
# control 8 -- DEVELOPMENT FIXTURES ONLY
# --------------------------------------------------------------------------


def test_control_8_the_nine_v1_failures_replay_and_close(universe) -> None:
    """The nine replay and close. **This certifies nothing prospectively.**

    They are the cases the repair was written after seeing, so a green here is a
    development regression: it says the repair does what it was built to do, not
    that the repair is right. IDENTITY_CHANGE_MIGRATION_CLOSURE_V1's FAIL stands.
    """
    assert V1_RECEIPT.exists(), "the V1 receipt these fixtures were read from is gone"
    closed = []
    for lineage_id, logical_id in V1_INVARIANT_6_CASES:
        row = universe[lineage_id]
        diff = _corpus_diff(row, pin=True)
        kinds = kinds_on(diff, logical_id)
        assert "unit_removed" not in kinds, (lineage_id, logical_id, sorted(kinds))
        assert "identity_unresolved" in kinds, (lineage_id, logical_id, sorted(kinds))
        assert logical_id not in diff.changed_logical_ids, (lineage_id, logical_id)
        closed.append((lineage_id, logical_id))
    assert len(closed) == 9
    assert len({lineage for lineage, _ in closed}) == 8


def test_control_8_the_nine_v1_failures_replay_and_close__can_come_back_red(universe) -> None:
    """All nine come back under pin OFF, exactly as V1 recorded them.

    This is what makes the green above meaningful: the fixtures are live, they
    are read from the frozen universe rather than from a stored expectation, and
    the defect is still reachable in the reference path.
    """
    reopened = []
    for lineage_id, logical_id in V1_INVARIANT_6_CASES:
        diff = _corpus_diff(universe[lineage_id], pin=False)
        kinds = kinds_on(diff, logical_id)
        if "unit_removed" in kinds and "identity_unresolved" in kinds:
            reopened.append((lineage_id, logical_id))
    assert len(reopened) == 9, reopened


# --------------------------------------------------------------------------
# control 9
# --------------------------------------------------------------------------

#: The lineages the identity repair actually acts on: the eight carrying a V1
#: INVARIANT_6 case. Control 9 runs over the WHOLE universe, not these -- they
#: are kept only so the red direction can be asserted where a difference is
#: known to exist rather than hoped for.
CONTROL_9_RED_LINEAGES: tuple[str, ...] = tuple(
    sorted({lineage for lineage, _ in V1_INVARIANT_6_CASES})
)


def test_control_9_legacy_and_new_content_predicates_still_agree(universe) -> None:
    """The identity repair is orthogonal to the INC-V2-037 content predicate.

    `legacy_identity_change_predicate=True` is the pinned reference path and must
    stay a faithful one. If the identity repair moved the identity-sensitive
    projection differently under the two predicates, the two migrations would be
    entangled and neither could be reasoned about alone.

    Run over **every** pair in the frozen universe rather than a sample. A
    sample would have to be chosen, and a sample chosen by the author of the
    repair is the weakest population this study has a name for. It costs about a
    minute; the alternative costs a caveat nobody can discharge later.
    """
    disagreeing = []
    for lineage_id, row in sorted(universe.items()):
        legacy = identity_projection(_corpus_diff(row, pin=True, legacy=True))
        migrated = identity_projection(_corpus_diff(row, pin=True, legacy=False))
        if legacy != migrated:
            disagreeing.append(lineage_id)
    assert not disagreeing, disagreeing
    assert len(universe) == 514, len(universe)


def test_control_9_legacy_and_new_content_predicates_still_agree__can_come_back_red(
    universe,
) -> None:
    """The comparator can see an identity-sensitive difference on real data.

    Shown two ways. First, across the pin -- legacy under pin ON against the
    migrated predicate under pin OFF -- which is a real difference on real
    corpus documents and proves the projection is not comparing something
    constant. Second, on a doctored record, which proves the comparator reacts
    to a single altered kind rather than only to a large one.
    """
    differing = []
    for lineage_id in CONTROL_9_RED_LINEAGES:
        row = universe[lineage_id]
        if identity_projection(_corpus_diff(row, pin=True, legacy=True)) != identity_projection(
            _corpus_diff(row, pin=False, legacy=False)
        ):
            differing.append(lineage_id)
    assert len(differing) == len(CONTROL_9_RED_LINEAGES), differing

    before, after = restructured_section()
    diff = run_diff(before, after, pin=True)
    removed = SemanticChange(kind=ChangeKind.UNIT_REMOVED, logical_id="u:p2", before=BETA)
    assert identity_projection(diff) != identity_projection(doctor(diff, add=removed))


# --------------------------------------------------------------------------
# control 10 -- the property that is easiest to lose
# --------------------------------------------------------------------------


def test_control_10_every_quarantined_unit_stays_visible() -> None:
    """Suppressing the false removal is not the fix. Stating the uncertainty is.

    Three assertions, and the third is the one that keeps the first two from
    being a licence to re-classify:

    1. every quarantined member is reachable from `SemanticDiff.unresolved`;
    2. every unresolved record is on the UNRESOLVED channel;
    3. and therefore none of them enters `changed_logical_ids` -- an unsettled
       identity is still not a modification, so it may not seed a recompilation.
    """
    for name, builder in HARD_SHAPES.items():
        before, after = builder()
        diff = run_diff(before, after, pin=True)
        quarantine = quarantine_for(before, after, SRC)
        assert quarantine, name
        assert not quarantined_units_that_are_invisible(diff, quarantine), name
        assert not unresolved_records_off_channel(diff), name
        assert not unresolved_units_in_the_recompilation_seed_set(diff), name
        for change in diff.unresolved:
            assert change.channel is ChangeChannel.UNRESOLVED, name


def test_control_10_every_quarantined_unit_stays_visible__can_come_back_red() -> None:
    """Two reds, and the first is production.

    Under pin OFF the before-side `u:p2` -- a declared candidate -- is skipped
    silently by the removal loop and the unsettled `u:p1` enters
    `changed_logical_ids` as a definite removal. Under a doctored diff with the
    unresolved record for `u:p1` removed, the visibility predicate reports both
    members as unreachable, which shows it is reading the records rather than
    the quarantine it was handed.
    """
    before, after = restructured_section()
    quarantine = quarantine_for(before, after, SRC)

    off = run_diff(before, after, pin=False)
    assert unresolved_units_in_the_recompilation_seed_set(off) == ["u:p1"]

    on = run_diff(before, after, pin=True)
    unresolved_record = next(
        change for change in on.changes if change.kind is ChangeKind.IDENTITY_UNRESOLVED
    )
    blinded = doctor(on, drop=unresolved_record)
    invisible = [
        row["logical_id"] for row in quarantined_units_that_are_invisible(blinded, quarantine)
    ]
    assert invisible == ["u:p1", "u:p2"], invisible


def test_control_10_records_the_stricter_visibility_reading() -> None:
    """Which members are visible only by being NAMED in another unit's record.

    Not an assertion about production: `diff_documents` deliberately does not
    give a declared candidate a record of its own, because it is already named
    by the record of the incoming unit whose identity it might continue, and the
    first version of the repair emitted three records for a two-candidate
    ambiguity by doing it anyway.

    It is asserted as a FACT about the current contract rather than left
    implicit, so that a future reader who expects `SemanticDiff.unresolved` to
    enumerate every quarantined unit by `logical_id` -- which a fail-closed
    endpoint scanning by id would -- finds it written down here instead of
    discovering it in production.
    """
    before, after = restructured_section()
    diff = run_diff(before, after, pin=True)
    quarantine = quarantine_for(before, after, SRC)
    assert sorted(quarantine.members) == ["u:p1", "u:p2"]
    assert quarantined_units_without_their_own_record(diff, quarantine) == ["u:p2"]
    named_as_candidate = {
        candidate
        for change in diff.unresolved
        for candidate in (change.candidates or ())
        if candidate
    }
    assert "u:p2" in named_as_candidate
