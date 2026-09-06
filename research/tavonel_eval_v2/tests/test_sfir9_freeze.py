"""Controls for the instrument freeze.

The freeze is the artifact everything downstream points at, so what matters is
what it refuses. Each of its five refusals is driven here. The happy path is
covered by one structural test and by the real freeze receipt, if one exists --
deliberately thin, because a freeze that succeeds is not evidence that it would
ever have failed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import sfir9_freeze as fz  # noqa: E402
import sfir9_freeze_gate as fg  # noqa: E402

RECEIPT = NS / "receipts/sfir9-instrument-freeze.json"


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """A namespace whose gate opens and whose tree is clean, by default."""
    namespace = tmp_path / "research/tavonel_eval_v2"
    (namespace / "receipts").mkdir(parents=True)
    (namespace / "tools").mkdir()
    for _name, filename, digest_key in fz.BOUND_RECEIPTS:
        body = {"schema": "x"}
        if digest_key:
            body[digest_key] = "sha256:" + "0" * 64
        (namespace / "receipts" / filename).write_bytes(
            json.dumps(body).encode("utf-8")
        )
    monkeypatch.setattr(
        fz, "instrument_commit", lambda _root, _ns: fz.Commit("abc123", True, ())
    )
    monkeypatch.setattr(
        fg, "CONDITIONS", (fg.Condition("a", "x", lambda _r: fg.Outcome(fg.PASS, "")),)
    )
    return namespace


def _freeze(namespace, **kwargs):
    return fz.freeze(
        namespace=namespace,
        repository_root=namespace.parents[1],
        **kwargs,
    )


# ------------------------------------------------------------ the refusals


def test_a_dirty_namespace_is_refused(sandbox, monkeypatch):
    """An instrument frozen from a dirty tree exists only on one machine."""
    monkeypatch.setattr(
        fz,
        "instrument_commit",
        lambda _root, _ns: fz.Commit("abc123", False, ("tools/sfir9_protocol.py",)),
    )
    with pytest.raises(fz.FreezeRefused) as caught:
        _freeze(sandbox)
    assert caught.value.code == fz.DIRTY_TREE
    assert "sfir9_protocol.py" in str(caught.value)


def test_a_closed_gate_is_refused(sandbox, monkeypatch):
    monkeypatch.setattr(
        fg,
        "CONDITIONS",
        (fg.Condition("a", "x", lambda _r: fg.Outcome(fg.FAIL, "no")),),
    )
    with pytest.raises(fz.FreezeRefused) as caught:
        _freeze(sandbox)
    assert caught.value.code == fz.GATE_NOT_OPEN
    assert "a" in str(caught.value)


def test_an_unproven_condition_also_refuses_the_freeze(sandbox, monkeypatch):
    """UNPROVEN is not PASS here either."""
    monkeypatch.setattr(
        fg,
        "CONDITIONS",
        (fg.Condition("a", "x", lambda _r: fg.Outcome(fg.UNPROVEN, "could not run")),),
    )
    with pytest.raises(fz.FreezeRefused) as caught:
        _freeze(sandbox)
    assert caught.value.code == fz.GATE_NOT_OPEN


def test_an_opened_cohort_is_refused(sandbox, monkeypatch):
    """A freeze taken after the roster was opened proves nothing about order."""
    (sandbox / "receipts/sfir9-cohort-roster--x.json").write_bytes(b"{}")
    with pytest.raises(fz.FreezeRefused) as caught:
        _freeze(sandbox)
    assert caught.value.code == fz.COHORT_OPENED


def test_a_second_freeze_is_refused(sandbox):
    """Refused, not overwritten. A retakeable freeze is not a freeze."""
    (sandbox / "receipts/sfir9-instrument-freeze.json").write_bytes(b"{}")
    with pytest.raises(fz.FreezeRefused) as caught:
        _freeze(sandbox)
    assert caught.value.code == fz.ALREADY_FROZEN
    assert "after seeing a result" in str(caught.value)


def test_a_missing_supporting_receipt_is_refused(sandbox):
    (sandbox / "receipts/sfir9-hostile-audit.json").unlink()
    with pytest.raises(fz.FreezeRefused) as caught:
        fz.bound_receipts(sandbox)
    assert caught.value.code == fz.GATE_NOT_OPEN
    assert "hostile-audit" in str(caught.value)


def test_a_git_failure_is_refused_rather_than_assumed(tmp_path):
    """No commit means no instrument commit to freeze at."""
    with pytest.raises(fz.FreezeRefused) as caught:
        fz.instrument_commit(tmp_path, "research")
    assert caught.value.code == fz.NO_COMMIT


# ----------------------------------------------------- what the receipt binds


def test_every_supporting_receipt_is_bound_by_two_hashes(sandbox):
    """Its own digest, and the bytes on disk. They answer different questions."""
    records = fz.bound_receipts(sandbox)
    assert set(records) >= {"freeze_gate", "hostile_audit", "mutation_baselines"}
    for name, _filename, digest_key in fz.BOUND_RECEIPTS:
        record = records[name]
        assert record["file_sha256"].startswith("sha256:")
        assert record["bytes"] > 0
        if digest_key:
            assert record["self_digest"] is not None, name


def test_the_file_hash_moves_when_the_bytes_move_even_at_the_same_verdict(sandbox):
    """A receipt regenerated later has the same self-digest and other bytes."""
    before = fz.bound_receipts(sandbox)["hostile_audit"]["file_sha256"]
    path = sandbox / "receipts/sfir9-hostile-audit.json"
    body = json.loads(path.read_text(encoding="utf-8"))
    path.write_bytes(json.dumps(body, indent=4).encode("utf-8"))
    after = fz.bound_receipts(sandbox)["hostile_audit"]["file_sha256"]
    assert before != after


def test_the_gate_receipt_is_among_the_bound_receipts():
    assert "sfir9-freeze-gate.json" in {f for _, f, _ in fz.BOUND_RECEIPTS}


def test_the_freeze_records_no_unfalsifiable_clean_tree_field():
    """The refusal is the evidence that the tree was clean.

    Any field recording it could only ever hold the clean value, because the
    freeze raises before reaching the receipt when the tree is dirty. Two
    versions of this field were written and both were removed for that reason.
    """
    source = (NS / "tools/sfir9_freeze.py").read_text(encoding="utf-8")
    assert '"namespace_working_tree_clean"' not in source
    assert '"namespace_uncommitted_paths"' not in source


# ------------------------------------------------------------ verification


def test_an_edited_freeze_receipt_does_not_verify():
    body = {
        "schema": fz.SCHEMA,
        "state": fz.FROZEN,
        "protocol": {"freeze_state": "PROTOCOL_FROZEN"},
    }
    report = {**body, "freeze_digest": fz._digest(body)}
    assert fz.verify(report)["verified"] is True
    report["state"] = "SOMETHING_ELSE"
    result = fz.verify(report)
    assert result["verified"] is False
    assert any("recompute" in problem for problem in result["problems"])


def test_a_receipt_recording_a_draft_protocol_does_not_verify():
    body = {
        "schema": fz.SCHEMA,
        "state": fz.FROZEN,
        "protocol": {"freeze_state": "PROTOCOL_DRAFT"},
    }
    report = {**body, "freeze_digest": fz._digest(body)}
    result = fz.verify(report)
    assert result["verified"] is False
    assert any("not frozen" in problem for problem in result["problems"])


def test_a_receipt_in_any_other_state_does_not_verify():
    body = {
        "schema": fz.SCHEMA,
        "state": "DRAFT",
        "protocol": {"freeze_state": "PROTOCOL_FROZEN"},
    }
    report = {**body, "freeze_digest": fz._digest(body)}
    assert fz.verify(report)["verified"] is False


# -------------------------------------------------------- the real receipt


@pytest.mark.skipif(not RECEIPT.exists(), reason="the instrument has not been frozen")
def test_the_real_freeze_verifies():
    report = json.loads(RECEIPT.read_text(encoding="utf-8"))
    assert fz.verify(report)["verified"] is True
    assert report["state"] == fz.FROZEN
    assert report["protocol"]["freeze_state"] == "PROTOCOL_FROZEN"
    assert len(report["instrument_commit"]) == 40


@pytest.mark.skipif(not RECEIPT.exists(), reason="the instrument has not been frozen")
def test_the_real_freeze_re_derived_the_gate_rather_than_reading_it():
    report = json.loads(RECEIPT.read_text(encoding="utf-8"))
    gate = report["gate_at_freeze_time"]
    assert gate["re_derived_here"] is True
    assert gate["conditions_passed"] == gate["conditions_checked"]


@pytest.mark.skipif(not RECEIPT.exists(), reason="the instrument has not been frozen")
def test_the_real_freeze_was_taken_with_the_cohort_still_shut():
    report = json.loads(RECEIPT.read_text(encoding="utf-8"))
    assert "no real cohort artifact exists" in report["cohort_state_at_freeze"]


@pytest.mark.skipif(not RECEIPT.exists(), reason="the instrument has not been frozen")
def test_the_real_freeze_says_what_it_does_not_establish():
    report = json.loads(RECEIPT.read_text(encoding="utf-8"))
    assert "calibrated" in report["what_this_does_not_establish"]
    assert "roster generation, exactly once" in report["what_this_authorises"]


# ------------------------------------------------- a freeze that actually runs
#
# Thirteen mutations survived the first pass because every control above stops
# at a refusal, so nothing the freeze *records* was ever exercised. The closure,
# manifest and upstream binding are stubbed here: what is under test is what the
# freeze writes down, not what those three compute.


@pytest.fixture
def completable(sandbox, monkeypatch):
    import sfir9_execution_closure as closure_module
    import sfir9_transport as transport

    monkeypatch.setattr(
        closure_module, "import_origins", lambda: {"sfir9_protocol": "x"}
    )
    monkeypatch.setattr(
        closure_module,
        "closure",
        lambda **_kw: {"component_count": 10, "closure_digest": "sha256:closure"},
    )
    monkeypatch.setattr(
        closure_module,
        "freeze_manifest",
        lambda _result, **_kw: {"manifest_digest": "sha256:manifest"},
    )
    monkeypatch.setattr(
        transport, "verify_upstream_binding", lambda **_kw: {"verified": True}
    )
    return sandbox


def test_a_completed_freeze_records_the_commit_it_was_taken_at(completable):
    report = _freeze(completable)
    assert report["instrument_commit"] == "abc123"
    assert report["namespace"].endswith("research/tavonel_eval_v2")


def test_a_completed_freeze_records_a_frozen_protocol(completable):
    report = _freeze(completable)
    assert report["protocol"]["freeze_state"] == "PROTOCOL_FROZEN"
    assert report["protocol"]["digest"].startswith("sha256:")
    assert fz.verify(report)["verified"] is True


def test_a_completed_freeze_binds_the_closure_manifest_and_upstream(completable):
    """All three, because each answers a question the others do not."""
    report = _freeze(completable)
    assert report["execution_closure"]["closure_digest"] == "sha256:closure"
    assert report["freeze_manifest"]["manifest_digest"] == "sha256:manifest"
    assert report["upstream_binding"] == {"verified": True}


def test_a_completed_freeze_binds_every_supporting_receipt(completable):
    report = _freeze(completable)
    bound = report["supporting_receipts"]
    # Named explicitly. Comparing against BOUND_RECEIPTS would narrow exactly as
    # far as BOUND_RECEIPTS narrowed, which is no check at all.
    assert set(bound) == {
        "freeze_gate",
        "hostile_audit",
        "legacy_failure_taxonomy",
        "mutation_baselines",
        "historical_isolation",
    }
    for record in bound.values():
        assert record["file_sha256"].startswith("sha256:")
        assert record["bytes"] > 0


def test_a_completed_freeze_records_that_it_re_derived_the_gate(completable):
    report = _freeze(completable)
    assert report["gate_at_freeze_time"]["re_derived_here"] is True
    assert report["gate_at_freeze_time"]["conditions_passed"] == 1


def test_a_completed_freeze_says_what_it_authorises_and_what_it_does_not(completable):
    report = _freeze(completable)
    assert "roster generation, exactly once" in report["what_this_authorises"]
    assert "calibrated" in report["what_this_does_not_establish"]


def test_a_completed_freeze_writes_the_receipt_it_returns(completable):
    report = _freeze(completable)
    written = json.loads(
        (completable / "receipts/sfir9-instrument-freeze.json").read_text("utf-8")
    )
    assert written == report


def test_a_gate_with_some_conditions_passing_still_refuses(completable, monkeypatch):
    """`gate_opens`, not a count. One PASS beside one FAIL is not an open gate."""
    monkeypatch.setattr(
        fg,
        "CONDITIONS",
        (
            fg.Condition("a", "x", lambda _r: fg.Outcome(fg.PASS, "")),
            fg.Condition("b", "y", lambda _r: fg.Outcome(fg.FAIL, "no")),
        ),
    )
    with pytest.raises(fz.FreezeRefused) as caught:
        _freeze(completable)
    assert caught.value.code == fz.GATE_NOT_OPEN
    assert "b" in str(caught.value)


def test_the_runner_exits_non_zero_when_the_freeze_is_refused(sandbox, monkeypatch):
    """A green exit on a refused freeze is how an unfrozen instrument proceeds."""
    (sandbox / "receipts/sfir9-instrument-freeze.json").write_bytes(b"{}")
    monkeypatch.setattr(
        fz, "freeze", lambda **_kw: (_ for _ in ()).throw(
            fz.FreezeRefused(fz.ALREADY_FROZEN, "already")
        )
    )
    assert fz.main(["--namespace", str(sandbox)]) == 1


def test_the_dirty_tree_refusal_names_what_was_uncommitted(sandbox, monkeypatch):
    """"has uncommitted changes" with no paths leaves nothing to go and fix."""
    monkeypatch.setattr(
        fz,
        "instrument_commit",
        lambda _root, _ns: fz.Commit("abc", False, ("tools/a.py", "tools/b.py")),
    )
    with pytest.raises(fz.FreezeRefused) as caught:
        _freeze(sandbox)
    assert "tools/a.py" in str(caught.value)
    assert "tools/b.py" in str(caught.value)


@pytest.mark.skipif(not RECEIPT.exists(), reason="the instrument has not been frozen")
def test_the_real_freeze_binds_every_upstream_module_by_origin_as_well_as_hash():
    """A correct hash on disk does not say which copy the interpreter loaded."""
    report = json.loads(RECEIPT.read_text(encoding="utf-8"))
    modules = report["upstream_binding"]["upstream_modules"]
    assert {row["module"] for row in modules} == {
        "sfir8_transport",
        "sfir8_traversal",
        "sfir8_frontier",
        "sfir8_checkpoint",
        "sfir8_hop_accounting",
        "sfir8_provider_accounting",
    }
    for row in modules:
        assert row["committed_bytes_equal_working_bytes"] is True, row["module"]
        assert row["import_origin_inside_frozen_checkout"] is True, row["module"]
        assert row["sha256"].startswith("sha256:")


@pytest.mark.skipif(not RECEIPT.exists(), reason="the instrument has not been frozen")
def test_the_real_freeze_binds_the_closure_and_its_outside_manifest():
    report = json.loads(RECEIPT.read_text(encoding="utf-8"))
    assert report["execution_closure"]["component_count"] == 10
    assert report["freeze_manifest"]["manifest_digest"].startswith("sha256:")
    assert (
        report["freeze_manifest"]["closure_digest"]
        == report["execution_closure"]["closure_digest"]
    )


@pytest.mark.skipif(not RECEIPT.exists(), reason="the instrument has not been frozen")
def test_the_real_freeze_reuses_sfir8_bytes_and_not_sfir8_conclusions():
    """Importing the code is not inheriting the findings."""
    report = json.loads(RECEIPT.read_text(encoding="utf-8"))
    reused = report["upstream_binding"]["what_is_reused"]
    assert "newly frozen for SFIR9" in reused
    assert "Not SFIR8's conclusions" in reused
