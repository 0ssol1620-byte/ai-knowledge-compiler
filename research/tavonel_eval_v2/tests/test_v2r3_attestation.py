"""The companion attestations and the V2R3 execution gate, driven red.

The defect these repair is a FALSE-PROVENANCE SEAM. The shared base freezer
writes its immutable receipt inside its return path, so a wrapper that computed
a V2R3-only proof and appended it to the returned dictionary produced a proof
that existed in console output and in no frozen body at all. The run looked
proved; the receipt recorded nothing.

Every test here runs against a TEMPORARY receipts directory. A gate that can
only be exercised against the real one cannot be shown to come back red without
writing evidence, and evidence written to prove a test is not evidence.

WHAT IS AND IS NOT COVERED HERE. The base chain -- protocol, universe, scorer,
exclusions and the links between them -- is the base freezer's own subject and
has its own tests. What is new in V2R3, and therefore what is proved here, is:
the three companion attestations exist and are immutable, the gate CONSUMES them
rather than merely reporting them, and each way of breaking the binding turns the
gate red. An attestation nothing reads is decorative (INC-V2-036).
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]
for _root in (
    str(ROOT / "packages" / "cir-python" / "src"),
    str(NS),
    str(NS / "tools"),
    str(NS / "acquisition"),
):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import freeze_migration_closure_v2r3 as fz  # noqa: E402
import v2r3_attestation as att  # noqa: E402
import v2r3_state_table as table  # noqa: E402
from akc_cir.semantic_diff import ChangeKind  # noqa: E402

base = fz.base
FreezeRefused = fz.FreezeRefused
REAL_RECEIPTS = NS / "receipts"


@pytest.fixture
def ws(tmp_path: Path) -> Any:
    """A workspace whose receipts are disposable and whose priors are real.

    `prior_receipts` points at the real directory because the spent V2R1 and
    V2R2 universes are read-only inputs here -- read for lineage ids only, never
    written to.
    """
    return fz.V2R3Workspace(
        root=ROOT,
        receipts=tmp_path / "receipts",
        prior_receipts=REAL_RECEIPTS,
    )


def _fake_base_receipt(stem_key: str, body: dict[str, Any], ws: Any) -> dict[str, Any]:
    """A stand-in base receipt, so the companion can be exercised on its own.

    The companion's subject is the BINDING, not the base rung's own contents, so
    a minimal body is enough and using a real one would make these tests depend
    on a chain they are not about.
    """
    protocol = base.load_protocol(ws.protocol)
    stem = base.stem_for(protocol, stem_key)
    ws.receipts.mkdir(parents=True, exist_ok=True)
    return base.write_receipt(stem, body, ws)


def _spent_pairs(stem: str) -> list[dict[str, str]]:
    runs = sorted(REAL_RECEIPTS.glob(f"{stem}--*.json"))
    if not runs:
        return []
    return json.loads(runs[-1].read_text(encoding="utf-8")).get("pairs", [])


def _universe_receipt(ws: Any, pairs: list[dict[str, str]]) -> dict[str, Any]:
    return _fake_base_receipt("universe", {"rung": 3, "pairs": pairs}, ws)


# ---------------------------------------------------------------------------
# the seam itself
# ---------------------------------------------------------------------------
def test_the_proof_lands_in_an_immutable_body_not_only_in_the_return_value(
    ws: Any,
) -> None:
    """The whole point. Read the proof back OFF DISK, from a file nobody kept a
    handle to, because the defect was a proof that existed only in memory."""
    _fake_base_receipt("acquisition_frame", {"rung": 0}, ws)
    att.attest_frame(ws)

    stem = base.stem_for(base.load_protocol(ws.protocol), "frame_attestation")
    written = sorted(ws.receipts.glob(f"{stem}--*.json"))
    assert len(written) == 1
    body = json.loads(written[0].read_text(encoding="utf-8"))
    assert body["root_disjointness"]["proved"] is True
    assert body["root_disjointness"]["clashes"] == 0
    assert body["root_disjointness"]["v2r3_unverifiable"] == 0
    assert body["provenance"]["immutable"] is True
    assert body["pinned_files"]["acquisition/sources_v2r3.py"].startswith("sha256:")


def test_each_attestation_binds_its_base_receipt_three_ways(ws: Any) -> None:
    """Path, run id and file digest. The path alone can be replaced and the run
    id lives inside the file it identifies, so the digest is what makes the
    binding checkable from outside."""
    written = _fake_base_receipt("acquisition_frame", {"rung": 0}, ws)
    result = att.attest_frame(ws)
    binding = result["attests"]
    assert binding["run_id"] == written["run_id"]
    assert binding["receipt"] == written["receipt"]
    assert binding["receipt_file_sha256"].startswith("sha256:")
    assert binding["receipt_body_sha256"] == written["receipt_sha256"]


# ---------------------------------------------------------------------------
# the red directions the audit named
# ---------------------------------------------------------------------------
def test_deleting_a_companion_receipt_turns_the_gate_red(ws: Any) -> None:
    _fake_base_receipt("acquisition_frame", {"rung": 0}, ws)
    att.attest_frame(ws)
    assert att.verify_frame(ws)["recomputed"]["proved"] is True

    stem = base.stem_for(base.load_protocol(ws.protocol), "frame_attestation")
    for path in ws.receipts.glob(f"{stem}--*.json"):
        path.unlink()
    with pytest.raises(FreezeRefused, match="attestation is missing"):
        att.verify_frame(ws)


def test_editing_an_attested_source_file_turns_the_gate_red(
    ws: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The pinned file is recomputed, not remembered."""
    _fake_base_receipt("acquisition_frame", {"rung": 0}, ws)
    att.attest_frame(ws)

    #: A copy of the namespace, so the edit is made to a throwaway tree and the
    #: real frame is never touched by a test.
    sandbox = tmp_path / "ns"
    (sandbox / "acquisition").mkdir(parents=True)
    (sandbox / "tools").mkdir(parents=True)
    shutil.copy(NS / "acquisition" / "sources_v2r3.py", sandbox / "acquisition")
    shutil.copy(NS / "tools" / "root_identity.py", sandbox / "tools")
    (sandbox / "acquisition" / "sources_v2r3.py").write_text(
        (sandbox / "acquisition" / "sources_v2r3.py").read_text(encoding="utf-8")
        + "\n# an edit after the freeze\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(att, "NS", sandbox)
    with pytest.raises(FreezeRefused, match="files that have since changed"):
        att.verify_frame(ws)


def test_rebinding_to_a_newer_base_receipt_turns_the_gate_red(ws: Any) -> None:
    """An attestation of a SUPERSEDED rung does not attest the run that would
    execute. Without this check a base rung could be re-frozen and its
    predecessor's attestation would still satisfy the gate."""
    _fake_base_receipt("acquisition_frame", {"rung": 0}, ws)
    att.attest_frame(ws)

    #: The superseding receipt is given an explicit, lexicographically greater
    #: run id rather than being left to the clock. "In force" means the LAST
    #: receipt by name, and two receipts written inside the same second share a
    #: timestamp and are ordered by a hash suffix -- so a second write does not
    #: reliably sort later, and a test that relied on it would pass or fail by
    #: luck rather than by the property.
    stem = base.stem_for(base.load_protocol(ws.protocol), "acquisition_frame")
    base.write_receipt(stem, {"rung": 0, "again": True}, ws, run_id="99991231T235959Z-ffffffffffff")

    with pytest.raises(FreezeRefused, match="rung in force"):
        att.verify_frame(ws)


def test_editing_the_bound_base_receipt_turns_the_gate_red(ws: Any) -> None:
    written = _fake_base_receipt("acquisition_frame", {"rung": 0}, ws)
    att.attest_frame(ws)
    target = ROOT / written["receipt"]
    target.write_text(target.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(FreezeRefused, match="has changed since it was attested"):
        att.verify_frame(ws)


def test_a_root_clash_turns_the_proof_red(monkeypatch: pytest.MonkeyPatch) -> None:
    """The proof is recomputed on every verify, so a clash introduced after the
    freeze is caught rather than inherited."""
    import root_identity as ri

    real = ri.read_module_roots("sources_v2r3")
    prior = ri.prior_root_identities(exclude_modules={"sources_v2r3"})
    stolen = next(iter(prior["identities"]))

    def clashing(name: str) -> dict[str, Any]:
        body = dict(real)
        body["identities"] = real["identities"] | {stolen}
        return body

    monkeypatch.setattr(att.ri, "read_module_roots", clashing)
    with pytest.raises(FreezeRefused, match="an earlier study already declared"):
        att.prove_root_disjointness()


def test_an_unverifiable_root_shape_turns_the_proof_red(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """UNVERIFIABLE blocks. It is never assumed disjoint -- that assumption is
    how 7 CFR 273 entered the V2R2 frame."""
    import root_identity as ri

    real = ri.read_module_roots("sources_v2r3")

    def unreadable(name: str) -> dict[str, Any]:
        return {**real, "unverifiable": ["GIT_ROOTS: ('only-one',)"]}

    monkeypatch.setattr(att.ri, "read_module_roots", unreadable)
    with pytest.raises(FreezeRefused, match="cannot interpret"):
        att.prove_root_disjointness()


def test_a_changed_prior_root_set_turns_the_frame_verification_red(
    ws: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Zero clashes against a DIFFERENT prior set is not the proof that was
    frozen, and the count alone would not catch a swap."""
    _fake_base_receipt("acquisition_frame", {"rung": 0}, ws)
    att.attest_frame(ws)

    real = att.prove_root_disjointness()

    def shifted() -> dict[str, Any]:
        return {**real, "prior_root_set_digest": "sha256:" + "0" * 64}

    monkeypatch.setattr(att, "prove_root_disjointness", shifted)
    with pytest.raises(FreezeRefused, match="prior root set has changed"):
        att.verify_frame(ws)


def test_a_contradictory_state_table_row_turns_the_proof_red(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reinstate V2R2's obligations and the protocol attestation refuses."""
    broken = dict(table.OBLIGATIONS)
    broken[table.Effective.UNRESOLVED] = {
        "required": (ChangeKind.UNIT_ADDED, table.UNRESOLVED_RECORD),
        "forbidden": (ChangeKind.UNIT_ADDED, ChangeKind.UNIT_REMOVED),
    }
    monkeypatch.setattr(table, "OBLIGATIONS", broken)
    with pytest.raises(FreezeRefused, match="CONTRACT_BROKEN"):
        att.prove_contract_consistency()


def test_a_protocol_that_disagrees_with_the_code_turns_the_proof_red(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If prose and code disagree, the prose is not a description of anything.

    A REAL failing consistency suite, run in the real subprocess. Pointing the
    proof at a missing file would also raise, and would prove only that pytest
    dislikes a bad path -- which is not the property. That the suite itself goes
    red when the state table is mutated is proved separately, by
    `test_v2r3_contract_consistency.py`'s own mutation control.
    """
    probe = NS / "tests" / "_tmp_v2r3_disagreement_probe.py"
    probe.write_text(
        "def test_the_protocol_and_the_code_disagree() -> None:\n"
        "    assert False, 'a declared row is not the executable row'\n",
        encoding="utf-8",
    )
    try:
        monkeypatch.setattr(att, "CONSISTENCY_TESTS", f"tests/{probe.name}")
        with pytest.raises(FreezeRefused, match="disagree"):
            att.prove_contract_consistency()
    finally:
        probe.unlink()


def test_another_adapter_holding_the_shared_base_does_not_change_what_a_rung_freezes(
    ws: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Import order must not decide which protocol a rung freezes.

    The first version of the adapter rebound the shared base permanently at
    import and turned eight of V2R2's adapter tests red by stealing it. Detecting
    the collision was the wrong repair -- a refusal telling the operator to
    re-import in a different order is a correct diagnosis of a design nobody
    should have to remember. The rung now binds for its own duration.
    """
    foreign = NS / "protocols" / "IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R2.yaml"
    monkeypatch.setattr(base, "PROTOCOL", foreign)

    _fake_base_receipt("acquisition_frame", {"rung": 0}, ws)
    seen: dict[str, Any] = {}
    with fz._bound():
        seen["during"] = base.PROTOCOL
    assert seen["during"] == fz.PROTOCOL, "the rung ran against another study's protocol"
    #: And handed it back, so the next reader sees what it put there.
    assert foreign == base.PROTOCOL


def test_the_bindings_are_restored_even_when_the_rung_refuses() -> None:
    """A refused freeze must not leave the base pointed somewhere another
    study's code would then read."""
    before = {name: getattr(base, name) for name in fz._bindings()}
    with pytest.raises(RuntimeError), fz._bound():
        raise RuntimeError("the rung refused")
    assert {name: getattr(base, name) for name in fz._bindings()} == before


def test_a_binding_that_does_not_take_turns_the_rung_red(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`_assert_bindings` is not redundant with setting them: it catches a base
    that has renamed one out from under the adapter, where the assignment
    quietly creates a new attribute nothing reads."""
    sentinel = object()
    monkeypatch.setattr(fz, "_bindings", lambda: {"PROTOCOL": sentinel})
    #: Applied and then reverted underneath, as a renamed-away attribute behaves.
    monkeypatch.setattr(base, "PROTOCOL", fz.PROTOCOL, raising=False)
    with pytest.raises(FreezeRefused, match="did not take this adapter's bindings"):
        fz._assert_bindings()


# ---------------------------------------------------------------------------
# the universe attestation
# ---------------------------------------------------------------------------
def test_the_universe_attestation_recomputes_both_intersections(ws: Any) -> None:
    _universe_receipt(ws, [{"lineage_id": "ecfr:7:1:1.1"}, {"lineage_id": "ecfr:7:1:1.2"}])
    result = att.attest_universe(ws)
    proof = result["spent_disjointness"]
    assert proof["intersections"] == {"v2r1": 0, "v2r2": 0}
    assert proof["frozen_pairs"] == 2
    assert {entry["study"] for entry in proof["sources"]} == {"v2r1", "v2r2"}
    assert att.verify_universe(ws)["recomputed"]["proved"] is True


def test_one_spent_lineage_in_the_universe_turns_the_proof_red(ws: Any) -> None:
    """The enumerator is not its own proof."""
    spent = _spent_pairs("identity-change-migration-closure-v2r2-universe")
    if not spent:
        pytest.skip("the spent V2R2 universe is not present in this checkout")
    _universe_receipt(ws, [{"lineage_id": "ecfr:7:1:1.1"}, spent[0]])
    with pytest.raises(FreezeRefused, match="intersects V2R2's SPENT cohort"):
        att.attest_universe(ws)


def test_an_empty_universe_turns_the_proof_red(ws: Any) -> None:
    """A disjointness proof over an empty set proves nothing."""
    _universe_receipt(ws, [])
    with pytest.raises(FreezeRefused, match="declares no pairs"):
        att.attest_universe(ws)


# ---------------------------------------------------------------------------
# the gate consumes what was attested
# ---------------------------------------------------------------------------
def test_the_stage_table_overrides_the_inherited_gate() -> None:
    """The inherited `gate` points at the base precondition check, which knows
    nothing about the three V2R3 proofs."""
    assert fz.STAGES["gate"] is fz.require_v2r3_execution_preconditions
    assert fz.STAGES["gate"] is not base.require_execution_preconditions


def test_no_stage_is_inherited_raw() -> None:
    """An inherited stage called raw resolves the BASE's protocol, not this one.

    `scorer` refused with "rung 3 is already frozen" because it had read V2R1's
    protocol, found V2R1's scorer stem and found V2R1's receipt -- and nothing
    in that refusal said it was talking about a different study. While the
    bindings were applied permanently at import it happened to work, which is
    what made it a trap: fixing the import-order hazard exposed a defect the
    hazard had been masking.
    """
    inherited = set(base.STAGES)
    for name in inherited:
        stage = fz.STAGES[name]
        assert stage is not base.STAGES[name], f"stage {name!r} is the raw base function"
        assert stage.__name__.startswith(("bound_", "freeze_", "require_")), name


def test_a_wrapped_stage_runs_with_this_adapters_protocol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The property the wrapper exists for, observed rather than assumed."""
    seen: dict[str, Any] = {}

    def spy(ws: Any = None, **kwargs: Any) -> dict[str, Any]:
        seen["protocol"] = base.PROTOCOL
        return {"state": "SPY"}

    monkeypatch.setitem(base.STAGES, "scorer", spy)
    wrapped = fz._wrap("scorer", spy)
    assert wrapped()["state"] == "SPY"
    assert seen["protocol"] == fz.PROTOCOL


def test_the_gate_refuses_when_the_base_chain_passes_but_attestations_are_absent(
    ws: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The exact state the audit found reachable: every proof printed PASS, the
    base chain reported READY, and nothing immutable bound them."""
    monkeypatch.setattr(
        base,
        "require_execution_preconditions",
        lambda workspace=None: {"state": "READY", "already_measured": []},
    )
    with pytest.raises(FreezeRefused, match="attestation is missing"):
        fz.require_v2r3_execution_preconditions(ws)


def test_the_gate_refuses_when_a_measurement_already_exists(
    ws: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The base gate REPORTS prior measurements; a closure runs exactly once, so
    this one REFUSES on them. A report is not a refusal."""
    monkeypatch.setattr(
        base,
        "require_execution_preconditions",
        lambda workspace=None: {
            "state": "READY",
            "already_measured": ["identity-change-migration-closure-v2r3--x.json"],
        },
    )
    with pytest.raises(FreezeRefused) as raised:
        fz.require_v2r3_execution_preconditions(ws)
    #: Named exactly, because the attestations are absent in this workspace too
    #: and a loose match would be satisfied by the wrong refusal -- reporting a
    #: pass for a check that never ran.
    assert "a V2R3 measurement already exists" in str(raised.value)
    assert "attestation is missing" not in str(raised.value)


def test_an_intact_chain_reports_ready_and_carries_all_three_proofs(
    ws: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The green direction. A gate that only ever goes red proves nothing about
    the case it is meant to admit."""
    _fake_base_receipt("acquisition_frame", {"rung": 0}, ws)
    att.attest_frame(ws)
    _fake_base_receipt("protocol", {"rung": 1}, ws)
    att.attest_protocol(ws)
    _universe_receipt(ws, [{"lineage_id": "ecfr:7:1:1.1"}])
    att.attest_universe(ws)

    monkeypatch.setattr(
        base,
        "require_execution_preconditions",
        lambda workspace=None: {"state": "READY", "already_measured": []},
    )
    ready = fz.require_v2r3_execution_preconditions(ws)
    assert ready["state"] == "READY"
    assert ready["gate"] == "require_v2r3_execution_preconditions"
    assert set(ready["companion_attestations"]) == {
        "frame_attestation",
        "protocol_attestation",
        "universe_attestation",
    }
    assert all(e["recomputed"] for e in ready["companion_attestations"].values())
    assert ready["root_disjointness"]["clashes"] == 0
    assert ready["contract_consistency"]["state"] == "SATISFIABLE"
    assert ready["spent_disjointness"]["intersections"] == {"v2r1": 0, "v2r2": 0}


# ---------------------------------------------------------------------------
# the frame's own declarations
# ---------------------------------------------------------------------------
def test_family_share_is_derived_from_the_quota_and_sums_to_one() -> None:
    """V2R2 hand-maintained both and they disagreed: shares summing to 0.99
    against a quota summing to its target."""
    from fractions import Fraction

    import sources_v2r3 as frame

    shares = frame.family_share_fractions()
    assert sum(shares.values()) == Fraction(1)
    for family, quota in frame.FAMILY_QUOTA.items():
        assert shares[family] == Fraction(quota, frame.PRIMARY_TARGET)
    assert sum(frame.FAMILY_QUOTA.values()) == frame.PRIMARY_TARGET
    assert set(shares) == set(frame.FAMILIES)


def test_no_v2r3_measurement_exists_yet() -> None:
    """The standing precondition that still binds. A closure runs exactly once,
    so a measurement receipt appearing before the single execution would mean
    the corpus was already spent."""
    assert list(REAL_RECEIPTS.glob(fz.MEASUREMENT_GLOB)) == []


def test_the_frame_was_sealed_before_the_corpus_it_authorised() -> None:
    """Rung 0 seals the frame BEFORE acquisition; a frame sealed afterwards
    records what was done rather than constraining what may be done.

    Until acquisition ran, this file asserted the corpus was absent. That
    assertion has served its purpose and would now only be satisfiable by
    deleting evidence, so the property is checked where it still lives: the
    rung-0 receipt claims it sealed before acquisition, and the frame it pinned
    is still the frame on disk -- so the corpus was fetched under these rules
    and not the other way round.
    """
    import hashlib

    frame_receipt = base.latest_receipt(
        base.stem_for(base.load_protocol(fz.PROTOCOL), "acquisition_frame"),
        REAL_RECEIPTS,
    )
    assert frame_receipt is not None, "rung 0 is not frozen"
    assert frame_receipt["sealed_before_acquisition"] is True
    current = "sha256:" + hashlib.sha256(fz.FRAME_MODULE.read_bytes()).hexdigest()
    assert frame_receipt["frame_module_sha256"] == current

    #: And the corpus that exists is the one that frame authorised.
    manifest = fz.CORPUS / "manifest.json"
    if manifest.is_file():
        body = json.loads(manifest.read_text(encoding="utf-8"))
        assert body["protocol_id"] == "IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R3"
