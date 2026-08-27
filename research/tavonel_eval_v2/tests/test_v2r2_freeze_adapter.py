"""The V2R2 freezer is an adapter over V2R1's. These tests prove it adapted.

An adapter fails silently in a way a fork cannot: if an override lands on a name
that has moved, or on a default that was baked in at class-creation time, every
call still works and quietly uses the PREDECESSOR's settings. A V2R2 rung would
then seal itself against V2R1's protocol, against V2R1's frame, and against
V2R1's corpus directory, and nothing would say so.

That is not hypothetical here. `base.Workspace` is a dataclass, so its field
defaults were compiled into `__init__` when the class was created; rebinding
`base.PROTOCOL` does not reach them. The first version of this adapter did
exactly that and `base.Workspace()` kept handing out V2R1's protocol path.

So each test below asserts the override actually took, not that it was written.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition"), str(NS / "compiler")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import freeze_migration_closure_v2r2 as fz  # noqa: E402


def test_workspace_carries_the_v2r2_protocol() -> None:
    assert fz.workspace().protocol == fz.PROTOCOL
    assert fz.PROTOCOL.name == "IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R2.yaml"


def test_the_base_modules_own_default_workspace_was_rebound() -> None:
    """The one that a module-global rebind would NOT have fixed.

    Every rung inside the base module resolves `ws or Workspace()`, so if this
    still returned V2R1's protocol the whole ladder would freeze the wrong file
    while every assertion about `fz.workspace()` stayed green.
    """
    assert fz.base.Workspace().protocol == fz.PROTOCOL


def test_the_protocol_on_disk_is_the_v2r2_one() -> None:
    protocol = fz.base.load_protocol(fz.workspace().protocol)
    assert protocol["protocol_id"] == "IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R2"
    for rung, stem in protocol["freeze"]["stems"].items():
        assert "v2r2" in stem, f"rung {rung} still names a predecessor stem: {stem}"


def test_the_frame_override_took() -> None:
    assert fz.base.FRAME_MODULE == fz.FRAME_MODULE
    assert fz.FRAME_MODULE.name == "sources_v2r2.py"
    frame = fz.base._load_frame()
    assert frame.PROTOCOL_ID == "IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R2"
    assert frame.ORDER_SALT == ":icmc-v2r2"


def test_the_measurement_glob_names_v2r2() -> None:
    """A stale glob would make the exactly-once guard watch the wrong receipts.

    `_nothing_has_been_scored` uses it to decide whether a rung may still be
    superseded. Pointed at V2R1's name it would report V2R2 unscored forever,
    because a V2R2 measurement receipt would never match.
    """
    assert fz.base.MEASUREMENT_GLOB == "identity-change-migration-closure-v2r2--*.json"


def test_nothing_has_been_measured_watches_the_v2r2_corpus() -> None:
    assert fz.CORPUS.name == "v2r2_corpus"
    clean, blocking = fz.base._nothing_has_been_measured(fz.workspace())
    #: Whatever the current state is, the guard must be talking about V2R2's
    #: corpus and V2R2's rungs -- never the predecessor's.
    assert not any("v2r1" in item for item in blocking), blocking
    assert isinstance(clean, bool)


def test_frame_and_protocol_agree_on_the_sufficiency_gate() -> None:
    """The founder ruling fixes both numbers, and two declarations that differ
    mean one of them is not the gate. The freezer refuses on a mismatch; this
    catches it before a freeze is attempted."""
    protocol = fz.base.load_protocol(fz.workspace().protocol)
    frame = fz.base._load_frame()
    sufficiency = protocol["cohort_sufficiency"]
    assert sufficiency["minimum_admitted_pairs"] == frame.FLOOR == 200
    assert sufficiency["minimum_families"] == frame.FAMILIES_REQUIRED == 3
    assert list(sufficiency["target_families"]) == list(frame.FAMILIES)


def test_the_frame_over_selects_and_its_quotas_fit_its_containers() -> None:
    """Over-selection must precede every outcome, and a quota may not demand
    material the declared roots cannot supply -- otherwise an under-delivery is
    baked in by the frame and answered afterwards by padding, which is
    forbidden."""
    frame = fz.base._load_frame()
    assert frame.PRIMARY_TARGET > frame.FLOOR
    assert sum(frame.FAMILY_QUOTA.values()) == frame.PRIMARY_TARGET
    assert frame.FAMILY_QUOTA["git_docs"] <= len(frame.GIT_ROOTS) * frame.CONTAINER_CAP["git_docs"]
    assert (
        frame.FAMILY_QUOTA["regulation_ecfr"]
        <= len(frame.ECFR_ROOTS) * frame.CONTAINER_CAP["regulation_ecfr"]
    )


def test_the_spent_v2r1_lineages_are_readable_and_non_empty() -> None:
    """A disjointness proof against an empty set proves nothing."""
    ids, meta = fz.v2r1_spent_lineages(fz.workspace())
    assert len(ids) == 285
    assert meta["distinct_lineages"] == 285
    assert "lineage ids only" in meta["read_for"]


def test_override_target_verification_actually_fires() -> None:
    """The guard that makes every other override safe. If it cannot go red, a
    rename in the base module would silently disarm the adapter."""
    original = fz.base.MEASUREMENT_GLOB
    try:
        del fz.base.MEASUREMENT_GLOB
        with pytest.raises(RuntimeError, match="no longer defines"):
            fz._verify_override_targets()
    finally:
        fz.base.MEASUREMENT_GLOB = original
    fz._verify_override_targets()


def test_the_frame_declares_the_v2r1_exclusion() -> None:
    frame = fz.base._load_frame()
    ids = [entry["id"] for entry in frame.EXCLUDED_SETS]
    assert "v2r1_spent_285" in ids
    assert len(ids) == len(set(ids)) == 10


def test_the_sec_rule_starts_above_v2r1s_highest_consumed_issuer() -> None:
    """Container-level disjointness for the family that has no root list.

    285 lineages are excluded by name downstream regardless; this is the
    stronger, cheaper proof, and it is checked here because a wrong constant
    would silently degrade the family to lineage-level exclusion only.
    """
    ids, _ = fz.v2r1_spent_lineages(fz.workspace())
    highest = max(int(i.split(":")[1]) for i in ids if i.startswith("sec:"))
    frame = fz.base._load_frame()
    assert frame.SEC_ISSUER_RULE["start_after_cik"] == highest == 8177


def test_the_scorer_of_record_resolves_the_v2r2_ladder() -> None:
    """The scorer reaches the ladder through the adapter, and only through it.

    This is not a formality. The derived scorer originally called
    `fz.Workspace()`, which the adapter deliberately does not define -- so it
    raised on the first line of `run()` instead of quietly building a workspace
    pointed at V2R1's protocol. The distinction between `fz` (overridden entry
    points) and `fz.base` (ladder helpers) is load-bearing, so it is asserted.
    """
    import identity_change_migration_closure_v2r2 as scorer

    assert scorer.STEM == "identity-change-migration-closure-v2r2"
    assert not hasattr(fz, "Workspace"), (
        "the adapter must not expose a bare `Workspace`; a caller reaching for it "
        "would get V2R1's protocol default and seal the wrong file"
    )
    assert scorer.fz is fz
    assert scorer.base_fz is fz.base
    assert scorer.fz.workspace().protocol == fz.PROTOCOL
