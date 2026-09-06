"""The V2R1 freeze gate, and the negative controls the founder ruling requires.

The ruling is explicit that wrong-record-kind, absent-record-kind and the
PENDING sentinel must all BLOCK the freeze. This file proves each of them does,
and it proves the positive case is a real observation rather than a lookup.

One of these controls found a live defect while it was being written. The first
version of `_observe_production_unresolved_record` returned every kind in
`diff.changes`, so asking "is the declared kind emitted?" accepted
`unit_removed` -- production emits it on the probe. Declaring a DEFINITE outcome
as the quarantine channel would let INVARIANT_6(e) be satisfied by the very
statement the repair exists to suppress: a unit reported removed would count as
evidence that its unresolved identity had been made visible. The check now reads
`diff.unresolved`, production's own channel mapping, and every definite kind is
refused.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]
for _root in (str(ROOT / "packages" / "cir-python" / "src"), str(NS), str(NS / "tools")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import freeze_migration_closure_v2r1 as fz  # noqa: E402


def _with_record(protocol: dict, value) -> dict:
    patched = dict(protocol)
    patched["quarantine_channel"] = dict(protocol["quarantine_channel"])
    patched["quarantine_channel"]["production_record"] = value
    return patched


@pytest.fixture(scope="module")
def protocol() -> dict:
    return fz.load_protocol()


def test_the_protocol_is_v2r1(protocol):
    assert protocol["protocol_id"] == "IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R1"


def test_the_sentinel_is_gone(protocol):
    declared = protocol["quarantine_channel"]["production_record"]
    assert declared == "identity_unresolved"


def test_the_declared_record_is_production_s_own_literal():
    """Read from the enum, never transcribed from an instruction."""
    from akc_cir.semantic_diff import ChangeKind

    assert ChangeKind.IDENTITY_UNRESOLVED.value == "identity_unresolved"


def test_positive_case_is_an_observation_not_a_lookup(protocol):
    result = fz.check_quarantine_channel(protocol)
    assert result["verified_against_production"] is True
    #: The proof that production was RUN: it reports what came back.
    assert result["observed_unresolved_kinds"] == ["identity_unresolved"]


def test_eight_invariants_carry_forward_unweakened(protocol):
    assert len(protocol["invariants"]) == 8
    assert "INVARIANT_6_ambiguous_identity_stays_unresolved" in protocol["invariants"]


def test_cohort_sufficiency_is_frozen_before_acquisition(protocol):
    sufficiency = protocol["cohort_sufficiency"]
    assert sufficiency["minimum_admitted_pairs"] == 200
    assert sufficiency["minimum_families"] == 3
    assert len(sufficiency["target_families"]) == 3


def test_the_sufficiency_gate_is_not_an_acceptance_threshold(protocol):
    sufficiency = protocol["cohort_sufficiency"]
    forbidden = sufficiency["how_200_was_chosen"]["forbidden_uses"]
    assert any("numerator" in entry for entry in forbidden)
    assert any("denominator" in entry for entry in forbidden)
    assert any("scorer" in entry for entry in forbidden)


# ---------------------------------------------------------------------------
# negative controls -- each must BLOCK


@pytest.mark.parametrize(
    "bad",
    [
        "PENDING_REPAIR_DECLARATION",
        "NONE_DECLARED_BY_PRODUCTION",
        "quarantine_withheld",
        "identity_ambiguous",
        "",
        None,
        123,
    ],
)
def test_absent_or_wrong_record_kind_blocks_the_freeze(protocol, bad):
    with pytest.raises(fz.FreezeRefused):
        fz.check_quarantine_channel(_with_record(protocol, bad))


@pytest.mark.parametrize(
    "definite",
    ["unit_removed", "unit_added", "modified_claim", "content_unchanged"],
)
def test_a_definite_outcome_may_not_be_declared_as_the_quarantine_channel(protocol, definite):
    """The control that found the defect.

    Every one of these IS a real ChangeKind and `unit_removed` is genuinely
    emitted by the probe, so a membership test accepted it. Only reading
    production's UNRESOLVED channel refuses them.
    """
    with pytest.raises(fz.FreezeRefused):
        fz.check_quarantine_channel(_with_record(protocol, definite))


# ---------------------------------------------------------------------------
# the supersede guard -- it must CLOSE once any data exists
#
# `supersede_frame` and `supersede_protocol` exist because two rungs were sealed
# around holes before any fetch: a frame with no source roots, and a
# manifest_contract still pointing at the ABANDONED V2 enumeration. Correcting
# those pre-measurement is legitimate. What would not be legitimate is a general
# amend path, so the guard is mechanical and these tests prove it shuts.


def test_the_study_is_currently_upstream_of_data_or_the_guard_says_why():
    clean, blocking = fz._nothing_has_been_measured(fz.Workspace())
    assert isinstance(clean, bool)
    assert clean == (not blocking)


def test_supersede_closes_the_moment_acquired_material_exists(tmp_path, monkeypatch):
    """The load-bearing property: this path is unreachable once one pair lands."""
    ws = fz.Workspace()
    corpus = (
        ws.root / "research" / "tavonel_eval_v2" / "artifacts" / "development" / "v2r1_corpus"
    )
    existed = corpus.exists()
    corpus.mkdir(parents=True, exist_ok=True)
    probe = corpus / "__guard_probe_test__.json"
    probe.write_text("{}", encoding="utf-8")
    try:
        clean, blocking = fz._nothing_has_been_measured(ws)
        assert clean is False
        assert any("acquired material exists" in entry for entry in blocking)
        with pytest.raises(fz.FreezeRefused):
            fz.supersede_frame(ws)
        with pytest.raises(fz.FreezeRefused):
            fz.supersede_protocol(ws)
    finally:
        probe.unlink()
        if not existed:
            import shutil

            shutil.rmtree(corpus, ignore_errors=True)


def test_an_unreadable_rung_blocks_rather_than_being_skipped(monkeypatch):
    """A guard that cannot see a rung must not report the study clean.

    The first version used `except Exception: continue`, so a rung whose stem
    could not be read was silently treated as un-frozen -- weakening the check in
    exactly the direction that makes superseding easier.
    """

    def exploding_stem(protocol, rung):
        if rung == "universe":
            raise KeyError("no stem declared")
        return "unused-stem"

    monkeypatch.setattr(fz, "stem_for", exploding_stem)
    clean, blocking = fz._nothing_has_been_measured(fz.Workspace())
    assert clean is False
    assert any("cannot read the stem" in entry for entry in blocking)


def test_the_run_id_helper_reads_provenance_not_the_top_level():
    """INC-V2-057(2): run ids live under `provenance`, and two Nones are not a match."""
    assert fz._run_id_of({"provenance": {"run_id": "abc"}}) == "abc"
    assert fz._run_id_of({"run_id": "fallback"}) == "fallback"
    assert fz._run_id_of({}) is None
    assert fz._run_id_of(None) is None


def test_the_chain_link_is_verified_not_assumed():
    """Rung 1 must reference the frame actually in force."""
    ws = fz.Workspace()
    receipt = fz.require_frozen_protocol(ws)
    frame_receipt = fz.latest_receipt(
        fz.stem_for(fz.load_protocol(ws.protocol), "acquisition_frame"), ws.receipts
    )
    recorded = (receipt.get("prior_rung") or {}).get("run_id")
    assert recorded is not None
    assert recorded == fz._run_id_of(frame_receipt)


def test_the_manifest_contract_points_at_v2r1_not_the_abandoned_v2(protocol):
    """Writing into V2's enumeration would mutate evidence the ruling preserves."""
    path = protocol["manifest_contract"]["path"]
    assert "v2r1_universe" in path
    assert "v2_universe" not in path.replace("v2r1_universe", "")
