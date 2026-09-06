"""INVARIANT_6 (c), (d), (e) for V2R1: green cases AND mutation controls.

Every clause gets two tests. One shows it holds on production output. The other
MUTATES that output until the clause is violated and requires the checker to
report it. A clause with only a green test is a claim that has never been shown
capable of failing, and this programme has already paid twice for that shape
(INC-V2-036, INC-V2-044).

The green tests deliberately do NOT claim natural coverage. Where a clause has
zero natural members in the fixtures, the test says so by asserting the reported
observation count, so a reader can tell "held" from "had nothing to hold over".
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]
for _root in (
    str(ROOT / "packages" / "cir-python" / "src"),
    str(NS),
    str(NS / "tools"),
    str(NS / "compiler"),
):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import v2r1_invariant6 as inv6  # noqa: E402
from akc_cir.semantic_diff import ChangeKind  # noqa: E402


@dataclass
class _Change:
    kind: ChangeKind
    logical_id: str | None = None
    candidates: tuple[str, ...] = ()


@dataclass
class _Diff:
    changes: list[_Change]


# ---------------------------------------------------------------------------
# (d) TOTAL UNIT ACCOUNTING


def test_d_matched_unchanged_unit_is_accounted_by_silence():
    """The finding that INC-V2-053 cost a rewrite to learn.

    A matched, unchanged unit emits NO record. If (d) counted only records it
    would report this pair as violating, and it would do so on every clean pair
    in the cohort -- failing the closure for a reason that is not the migration.
    """
    diff = _Diff(changes=[])
    violations, observed = inv6.check_total_accounting(
        diff, before_ids={"u:a", "u:b"}, after_ids={"u:a", "u:b"}
    )
    assert violations == []
    assert observed == 2


def test_d_green_on_a_mixed_pair():
    diff = _Diff(
        changes=[
            _Change(ChangeKind.UNIT_ADDED, "u:new"),
            _Change(ChangeKind.UNIT_REMOVED, "u:gone"),
            _Change(ChangeKind.IDENTITY_UNRESOLVED, "u:x", ("u:y",)),
        ]
    )
    violations, observed = inv6.check_total_accounting(
        diff,
        before_ids={"u:keep", "u:gone", "u:x", "u:y"},
        after_ids={"u:keep", "u:new", "u:x"},
    )
    assert violations == [], violations
    assert observed == 5


def test_d_goes_red_on_silent_disappearance():
    """A before-side unit that leaves with no statement at all."""
    diff = _Diff(changes=[])
    violations, observed = inv6.check_total_accounting(
        diff, before_ids={"u:a", "u:vanished"}, after_ids={"u:a"}
    )
    assert observed == 2
    assert [v["logical_id"] for v in violations] == ["u:vanished"]
    assert violations[0]["clause"] == "d"


def test_d_goes_red_on_silent_appearance():
    diff = _Diff(changes=[])
    violations, _ = inv6.check_total_accounting(
        diff, before_ids={"u:a"}, after_ids={"u:a", "u:appeared"}
    )
    assert [v["logical_id"] for v in violations] == ["u:appeared"]


def test_d_goes_red_when_a_unit_is_accounted_twice():
    """Named unresolved AND definitely classified. Two accounts is not accounting."""
    diff = _Diff(
        changes=[
            _Change(ChangeKind.IDENTITY_UNRESOLVED, "u:x", ("u:y",)),
            _Change(ChangeKind.UNIT_REMOVED, "u:y"),
        ]
    )
    violations, _ = inv6.check_total_accounting(
        diff, before_ids={"u:x", "u:y"}, after_ids={"u:x"}
    )
    assert [v["logical_id"] for v in violations] == ["u:y"]
    assert "not a partition" in violations[0]["why"]


def test_d_an_empty_candidate_does_not_account_for_anything():
    """NAMED means a non-empty id.

    A record claiming a unit is implicated by something it declines to identify
    names nothing. If the empty string counted, this pair would look accounted.
    """
    diff = _Diff(changes=[_Change(ChangeKind.IDENTITY_UNRESOLVED, "u:x", ("",))])
    violations, _ = inv6.check_total_accounting(
        diff, before_ids={"u:x", "u:orphan"}, after_ids={"u:x"}
    )
    assert [v["logical_id"] for v in violations] == ["u:orphan"]


# ---------------------------------------------------------------------------
# (e) QUARANTINE CHANNEL


def test_e_green_when_every_unsettled_id_is_named():
    diff = _Diff(changes=[_Change(ChangeKind.IDENTITY_UNRESOLVED, "u:x", ("u:y",))])
    violations, observed = inv6.check_quarantine_channel(
        diff, unsettled_ids={"u:x", "u:y"}, declared_record="identity_unresolved"
    )
    assert violations == []
    assert observed == 2


def test_e_goes_red_on_silent_suppression():
    """Withholding the definite outcome without stating the uncertainty."""
    diff = _Diff(changes=[_Change(ChangeKind.IDENTITY_UNRESOLVED, "u:x", ("u:y",))])
    violations, _ = inv6.check_quarantine_channel(
        diff,
        unsettled_ids={"u:x", "u:y", "u:withheld_silently"},
        declared_record="identity_unresolved",
    )
    assert [v["logical_id"] for v in violations] == ["u:withheld_silently"]
    assert "SILENT SUPPRESSION" in violations[0]["why"]


def test_e_goes_red_on_a_record_kind_production_never_emits():
    """The vacuity control.

    A clause written over a record nothing emits cannot be violated. This is the
    exact defect the abandoned V2 draft's PENDING sentinel existed to prevent,
    and it is checked against the live enum rather than against a string in the
    protocol.
    """
    diff = _Diff(changes=[_Change(ChangeKind.IDENTITY_UNRESOLVED, "u:x")])
    violations, observed = inv6.check_quarantine_channel(
        diff, unsettled_ids={"u:x"}, declared_record="quarantine_withheld"
    )
    assert observed == 0
    assert len(violations) == 1
    assert "not a member of production's ChangeKind" in violations[0]["why"]


def test_e_rejects_the_pending_sentinel_too():
    violations, _ = inv6.check_quarantine_channel(
        _Diff(changes=[]),
        unsettled_ids=set(),
        declared_record="PENDING_REPAIR_DECLARATION",
    )
    assert len(violations) == 1


def test_e_rejects_none_declared_by_production():
    """V2R1 removed this branch. Production DOES emit a typed record."""
    violations, _ = inv6.check_quarantine_channel(
        _Diff(changes=[]),
        unsettled_ids=set(),
        declared_record="NONE_DECLARED_BY_PRODUCTION",
    )
    assert len(violations) == 1


def test_e_declared_record_matches_the_live_enum():
    """The protocol's value is production's literal, not a transcription."""
    assert inv6.UNRESOLVED_KIND.value == "identity_unresolved"
    assert "identity_unresolved" in {kind.value for kind in ChangeKind}


# ---------------------------------------------------------------------------
# (c) AMBIGUOUS may not enter matched-facet reproduction


def test_c_green_when_no_ambiguous_id_is_reproduced():
    violations, observed = inv6.check_ambiguous_not_reproduced({"u:x"}, {"u:other"})
    assert violations == []
    assert observed == 1


def test_c_goes_red_when_an_ambiguous_id_is_reproduced():
    violations, _ = inv6.check_ambiguous_not_reproduced({"u:x"}, {"u:x", "u:other"})
    assert [v["logical_id"] for v in violations] == ["u:x"]
    assert violations[0]["clause"] == "c"


def test_c_reports_zero_power_rather_than_claiming_a_pass():
    """No AMBIGUOUS decisions means nothing could have violated (c).

    The observation count says so out loud, so a caller cannot read an empty
    violation list as evidence the clause was exercised.
    """
    violations, observed = inv6.check_ambiguous_not_reproduced(set(), {"u:anything"})
    assert violations == []
    assert observed == 0
