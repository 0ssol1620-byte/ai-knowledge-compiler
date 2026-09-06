"""Each of `preflight_checks.py`'s six checks must be able to come back
`FAIL` on a constructed violation, and (where the property is not simply
"today's known gap") come back `PASS` on a clean fixture.

INC-V2-036: a guard placed where its failure is structurally impossible is
not a guard. The `UNVERIFIABLE` placeholders these checks replace blocked the
freeze unconditionally -- that made them safe but also made them
indistinguishable from a broken check. These tests exist so that is no longer
true: every check below is exercised on both sides.

Some tests also run the real check against the real repository and assert
today's known answer (documented per-test). That is deliberate, not
brittleness for its own sake -- `preflight_checks.py`'s whole point is to
measure production state, and a check that has never once been run against
the thing it measures is unproven. If one of those assertions starts
failing because the underlying gap was repaired, that is progress: update
the assertion, do not delete the test.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]
for _sub in ("tools", "acquisition", "compiler", "canonicalization"):
    sys.path.insert(0, str(NS / _sub))
sys.path.insert(0, str(NS))
sys.path.insert(0, str(ROOT / "packages" / "cir-python" / "src"))

import preflight_checks as pf  # noqa: E402


@pytest.fixture
def under_ns(tmp_path_factory):
    """A scratch directory INSIDE the repository tree.

    Mirrors `test_freeze_sfi3_gate.py`'s `under_ns` fixture exactly, for the
    same reason: pytest's `tmp_path` lives on C: while this repository is on
    D:, and `common.rel()` raises across drives.
    """
    root = pathlib.Path(NS) / "artifacts" / "development" / "_scratch_preflight_checks"
    root.mkdir(parents=True, exist_ok=True)
    scratch = pathlib.Path(tempfile.mkdtemp(dir=root))
    yield scratch
    shutil.rmtree(scratch, ignore_errors=True)


# ---------------------------------------------------------------------------
# 1. causal_wording_consistency


def test_causal_wording_can_fail_on_an_unqualified_reappearance(under_ns):
    (under_ns / "note.py").write_text(
        '"""the typed cross-check was clean, nothing more to say here."""\n',
        encoding="utf-8",
    )
    result = pf.causal_wording_consistency(scan_root=under_ns)
    assert result["verdict"] == pf.FAIL
    assert result["violations"]
    assert result["violations"][0]["pattern"] == "cross_check_was_clean"


def test_causal_wording_passes_when_a_qualifier_is_present(under_ns):
    (under_ns / "note.py").write_text(
        '"""the typed cross-check was clean, but only over its own downstream '
        'denominator."""\n',
        encoding="utf-8",
    )
    result = pf.causal_wording_consistency(scan_root=under_ns)
    assert result["verdict"] == pf.PASS


def test_causal_wording_ledger_historical_quote_with_later_correction_passes(under_ns):
    """The ledger is append-only; a correction legitimately lives in a later
    section than the quote it corrects (this is the real shape of
    incident_ledger.md's own INC-V2-036/037 pair)."""
    ledger = under_ns / "incident_ledger.md"
    ledger.write_text(
        "## INC-V2-900 -- an old inference\n\n"
        "the typed cross-check was clean, 191 of 191 named every moved artifact.\n\n"
        "## INC-V2-901 -- update\n\n"
        "INC-V2-900's inference is withdrawn.\n",
        encoding="utf-8",
    )
    result = pf.causal_wording_consistency(scan_root=under_ns)
    assert result["verdict"] == pf.PASS


def test_causal_wording_ledger_new_unmarked_entry_fails(under_ns):
    """Nothing appears after it in the append-only file to correct it."""
    ledger = under_ns / "incident_ledger.md"
    ledger.write_text(
        "## INC-V2-900 -- an old inference\n\nsome unrelated text.\n\n"
        "## INC-V2-999 -- a fresh entry\n\n"
        "the typed cross-check was clean and that is the whole story.\n",
        encoding="utf-8",
    )
    result = pf.causal_wording_consistency(scan_root=under_ns)
    assert result["verdict"] == pf.FAIL


def test_causal_wording_is_clean_across_the_real_repository():
    """The property, not the answer of the day.

    This was written as `..._currently_fails_against_the_real_repository` and
    pinned the one file that then carried the stale phrasing. A test that
    asserts today's violation list has to be edited every time the tree is
    fixed, and in between it reports red for a condition that is green. The
    check's ability to come back red is proven by the fixture tests above, which
    is where power belongs; here the question is only whether the tree is clean.
    """
    result = pf.causal_wording_consistency()
    assert result["verdict"] == pf.PASS, result["violations"]


# ---------------------------------------------------------------------------
# 2. incident_cross_reference_coherence


def test_incident_coherence_can_fail_on_a_duplicate_declaration(under_ns):
    ledger = under_ns / "incident_ledger.md"
    ledger.write_text(
        "## INC-V2-001 -- first thing\n\nbody one.\n\n"
        "## INC-V2-001 -- an unrelated second thing\n\nbody two.\n",
        encoding="utf-8",
    )
    result = pf.incident_cross_reference_coherence(ledger_path=ledger, scan_root=under_ns)
    assert result["verdict"] == pf.FAIL
    assert result["duplicate_declarations"]


def test_incident_coherence_allows_a_marked_follow_up(under_ns):
    ledger = under_ns / "incident_ledger.md"
    ledger.write_text(
        "## INC-V2-001 -- first thing\n\nbody one.\n\n"
        "## INC-V2-001 -- update, corrected\n\nbody two.\n",
        encoding="utf-8",
    )
    result = pf.incident_cross_reference_coherence(ledger_path=ledger, scan_root=under_ns)
    assert result["verdict"] == pf.PASS


def test_incident_coherence_can_fail_on_a_numbering_gap(under_ns):
    ledger = under_ns / "incident_ledger.md"
    ledger.write_text("## INC-V2-001 -- a\n\nx\n\n## INC-V2-003 -- b\n\ny\n", encoding="utf-8")
    result = pf.incident_cross_reference_coherence(ledger_path=ledger, scan_root=under_ns)
    assert result["verdict"] == pf.FAIL
    assert result["numbering_gaps"] == [2]


def test_incident_coherence_can_fail_on_an_unresolved_reference(under_ns):
    ledger = under_ns / "incident_ledger.md"
    ledger.write_text("## INC-V2-001 -- a\n\nx\n", encoding="utf-8")
    (under_ns / "stray.md").write_text("see INC-V2-099 for details\n", encoding="utf-8")
    result = pf.incident_cross_reference_coherence(ledger_path=ledger, scan_root=under_ns)
    assert result["verdict"] == pf.FAIL
    assert any(row["number"] == 99 for row in result["unresolved_references"])


def test_incident_coherence_passes_when_clean(under_ns):
    ledger = under_ns / "incident_ledger.md"
    ledger.write_text("## INC-V2-001 -- a\n\nx\n\n## INC-V2-002 -- b\n\ny\n", encoding="utf-8")
    result = pf.incident_cross_reference_coherence(ledger_path=ledger, scan_root=under_ns)
    assert result["verdict"] == pf.PASS


def test_incident_coherence_missing_ledger_fails(under_ns):
    result = pf.incident_cross_reference_coherence(ledger_path=under_ns / "nope.md")
    assert result["verdict"] == pf.FAIL


def test_incident_coherence_passes_against_the_real_ledger():
    result = pf.incident_cross_reference_coherence()
    assert result["verdict"] == pf.PASS
    assert result["declared_numbers"][0] == 1
    assert result["duplicate_declarations"] == []
    assert result["numbering_gaps"] == []


# ---------------------------------------------------------------------------
# 3. dynamic_include_target_closure


def test_include_target_closure_absence_of_scope_gate_is_fail(under_ns):
    reference = under_ns / "reference.py"
    reference.write_text(
        "INCLUDE_TARGET = 'INCLUDE_TARGET'\n\n"
        "def _extract_foo(raw):\n"
        "    return [_fact(INCLUDE_TARGET, 'foo-include', 0, 1, raw)]\n",
        encoding="utf-8",
    )
    result = pf.dynamic_include_target_closure(
        scope_gate_path=under_ns / "does_not_exist.py", reference_path=reference
    )
    assert result["verdict"] == pf.FAIL
    assert "does not exist" in result["detail"]
    assert result["unrouted"] == ["foo-include"]


def test_include_target_closure_routed_construct_needs_no_gate(under_ns):
    reference = under_ns / "reference.py"
    reference.write_text(
        "INCLUDE_TARGET = 'INCLUDE_TARGET'\n\n"
        "def _extract_foo(raw):\n"
        "    verdict = classify_include_expression(raw)\n"
        "    return [_fact(INCLUDE_TARGET, 'foo-include', 0, 1, raw)]\n",
        encoding="utf-8",
    )
    result = pf.dynamic_include_target_closure(
        scope_gate_path=under_ns / "does_not_exist.py", reference_path=reference
    )
    assert result["verdict"] == pf.PASS
    assert result["unrouted"] == []


def test_include_target_closure_gate_covering_everything_passes(under_ns):
    reference = under_ns / "reference.py"
    reference.write_text(
        "INCLUDE_TARGET = 'INCLUDE_TARGET'\n\n"
        "def _extract_foo(raw):\n"
        "    return [_fact(INCLUDE_TARGET, 'foo-include', 0, 1, raw)]\n",
        encoding="utf-8",
    )
    gate_module = under_ns / "fixture_scope_gate.py"
    gate_module.write_text(
        "INCLUDE_TARGET_CONSTRUCTS = ('foo-include',)\n\n"
        "def prove_scope():\n"
        "    return {'foo-include': {'in_scored_path': True}}\n",
        encoding="utf-8",
    )
    result = pf.dynamic_include_target_closure(scope_gate_path=gate_module, reference_path=reference)
    assert result["verdict"] == pf.PASS


def test_include_target_closure_gate_covering_only_some_still_fails(under_ns):
    reference = under_ns / "reference.py"
    reference.write_text(
        "INCLUDE_TARGET = 'INCLUDE_TARGET'\n\n"
        "def _extract_foo(raw):\n"
        "    return [_fact(INCLUDE_TARGET, 'foo-include', 0, 1, raw)]\n\n"
        "def _extract_bar(raw):\n"
        "    return [_fact(INCLUDE_TARGET, 'bar-include', 0, 1, raw)]\n",
        encoding="utf-8",
    )
    gate_module = under_ns / "fixture_scope_gate.py"
    gate_module.write_text(
        "INCLUDE_TARGET_CONSTRUCTS = ('foo-include', 'bar-include')\n\n"
        "def prove_scope():\n"
        "    return {'foo-include': {}}\n",
        encoding="utf-8",
    )
    result = pf.dynamic_include_target_closure(scope_gate_path=gate_module, reference_path=reference)
    assert result["verdict"] == pf.FAIL
    assert "bar-include" in result["detail"]


def test_include_target_closure_gate_declaring_no_scope_claim_fails(under_ns):
    reference = under_ns / "reference.py"
    reference.write_text(
        "INCLUDE_TARGET = 'INCLUDE_TARGET'\n\n"
        "def _extract_foo(raw):\n"
        "    return [_fact(INCLUDE_TARGET, 'foo-include', 0, 1, raw)]\n",
        encoding="utf-8",
    )
    gate_module = under_ns / "fixture_scope_gate.py"
    gate_module.write_text(
        "INCLUDE_TARGET_CONSTRUCTS = ()\n\n"
        "def prove_scope():\n"
        "    return {}\n",
        encoding="utf-8",
    )
    result = pf.dynamic_include_target_closure(scope_gate_path=gate_module, reference_path=reference)
    assert result["verdict"] == pf.FAIL
    assert "no scope claim" in result["detail"]


def test_include_target_closure_gate_raising_fails(under_ns):
    reference = under_ns / "reference.py"
    reference.write_text(
        "INCLUDE_TARGET = 'INCLUDE_TARGET'\n\n"
        "def _extract_foo(raw):\n"
        "    return [_fact(INCLUDE_TARGET, 'foo-include', 0, 1, raw)]\n",
        encoding="utf-8",
    )
    gate_module = under_ns / "fixture_scope_gate.py"
    gate_module.write_text(
        "INCLUDE_TARGET_CONSTRUCTS = ('foo-include',)\n\n"
        "def prove_scope():\n"
        "    raise AssertionError('boom')\n",
        encoding="utf-8",
    )
    result = pf.dynamic_include_target_closure(scope_gate_path=gate_module, reference_path=reference)
    assert result["verdict"] == pf.FAIL


def test_include_target_closure_missing_reference_module_fails(under_ns):
    result = pf.dynamic_include_target_closure(reference_path=under_ns / "nope.py")
    assert result["verdict"] == pf.FAIL


def test_include_target_closure_passes_against_the_real_scope_gate():
    """`source_fact_ir/scope_gate.py` landed from another lane during this
    check's own development -- see the module docstring on why this reads
    the gate's real contract (`INCLUDE_TARGET_CONSTRUCTS` /
    `prove_scope()`) dynamically rather than a guessed one."""
    result = pf.dynamic_include_target_closure()
    assert result["verdict"] == pf.PASS
    assert set(result["unrouted"]) == {"html-include-src", "mediawiki-template"}


# ---------------------------------------------------------------------------
# 4. artifact_facet_fingerprint_propagation


def test_artifact_facet_propagation_can_fail_synthetically(monkeypatch):
    import compiler.channel_cases as real_cc

    def fake_case():
        return real_cc.ChannelCase(
            ir_channel="X",
            exercised=False,
            diff=None,
            plan=None,
            target_artifact="section:fake",
            prior_value="same",
            rebuilt_value="same",
        )

    for name in pf._CHANNEL_CASE_NAMES:
        monkeypatch.setattr(real_cc, name, fake_case)

    result = pf.artifact_facet_fingerprint_propagation()
    assert result["verdict"] == pf.FAIL
    assert len(result["channels"]) == 5
    assert all(not row["digest_moved"] for row in result["channels"])


def test_artifact_facet_propagation_can_pass_synthetically(monkeypatch):
    import compiler.channel_cases as real_cc

    def fake_case():
        return real_cc.ChannelCase(
            ir_channel="X",
            exercised=True,
            diff=None,
            plan=None,
            target_artifact="section:fake",
            prior_value="before",
            rebuilt_value="after",
        )

    for name in pf._CHANNEL_CASE_NAMES:
        monkeypatch.setattr(real_cc, name, fake_case)

    result = pf.artifact_facet_fingerprint_propagation()
    assert result["verdict"] == pf.PASS


def test_artifact_facet_propagation_covers_every_declared_channel_and_passes():
    """Same reversal as the causal-wording test above, and the same reason.

    This was `..._measures_todays_real_gap` and asserted that exactly
    REFERENTIAL, TEMPORAL and DESCRIPTIVE could not move the digest, because
    `build_all` read only `{logical_id, semantic_text}` for a `section:`
    artifact. It said a flip to PASS would be the repair landing. It flipped.

    The channel set is still asserted, so this cannot go vacuous: a check that
    measured three channels instead of five, or none at all, would otherwise
    report PASS while watching less than it claims.
    """
    result = pf.artifact_facet_fingerprint_propagation()
    measured = {row["ir_channel"] for row in result["channels"]}
    assert measured == {"SEMANTIC", "STRUCTURAL", "REFERENTIAL", "TEMPORAL", "DESCRIPTIVE"}
    assert result["verdict"] == pf.PASS, result["detail"]
    assert all(row["digest_moved"] for row in result["channels"])


# ---------------------------------------------------------------------------
# 5. fresh_frame_disjointness


def test_fresh_frame_disjointness_can_fail_on_a_git_root_collision(under_ns):
    import sources_sfi3 as sfi3

    first_root = sfi3.GIT_ROOTS[0]
    colliding = frozenset({f"git:{first_root['owner']}/{first_root['repo']}:some/path.md"})
    result = pf.fresh_frame_disjointness(spent=colliding, frame_path=under_ns / "no_frame.json")
    assert result["verdict"] == pf.FAIL
    assert any(v["kind"] == "git_root" for v in result["violations"])


def test_fresh_frame_disjointness_can_fail_on_an_ecfr_root_collision(under_ns):
    import sources_sfi3 as sfi3

    title, part, _description = sfi3.ECFR_ROOTS[0]
    colliding = frozenset({f"ecfr:{title}:{part}:{part}.1"})
    result = pf.fresh_frame_disjointness(spent=colliding, frame_path=under_ns / "no_frame.json")
    assert result["verdict"] == pf.FAIL
    assert any(v["kind"] == "ecfr_root" for v in result["violations"])


def test_fresh_frame_disjointness_passes_on_a_clean_spent_set_with_no_frame(under_ns):
    result = pf.fresh_frame_disjointness(
        spent=frozenset({"git:someone-else/unrelated-repo:path.md"}),
        frame_path=under_ns / "no_frame.json",
    )
    assert result["verdict"] == pf.PASS
    assert result["frame_sealed"] is False


def test_fresh_frame_disjointness_can_fail_on_a_sealed_frame_overlap(under_ns):
    frame_file = under_ns / "sfi3_lineages.json"
    frame_file.write_text(
        json.dumps({"lineages": [{"lineage_id": "wikipedia:Some Article", "family": "x"}]}),
        encoding="utf-8",
    )
    result = pf.fresh_frame_disjointness(
        spent=frozenset({"wikipedia:Some Article"}), frame_path=frame_file
    )
    assert result["verdict"] == pf.FAIL
    assert result["frame_sealed"] is True
    assert any(v["kind"] == "expanded_frame_overlap" for v in result["violations"])


def test_fresh_frame_disjointness_sealed_frame_with_no_overlap_passes(under_ns):
    frame_file = under_ns / "sfi3_lineages.json"
    frame_file.write_text(
        json.dumps({"lineages": [{"lineage_id": "wikipedia:Some Other Article", "family": "x"}]}),
        encoding="utf-8",
    )
    result = pf.fresh_frame_disjointness(
        spent=frozenset({"wikipedia:Some Article"}), frame_path=frame_file
    )
    assert result["verdict"] == pf.PASS
    assert result["frame_sealed"] is True


def test_fresh_frame_disjointness_passes_against_the_real_state():
    """Disjointness holds in the real state, whether or not the frame is sealed.

    This asserted `frame_sealed is False` until the SFI3 frame was actually
    sealed, at which point it went red for a reason that has nothing to do with
    disjointness -- it was a snapshot of a moment, not a contract. What it was
    really recording is that the Wikipedia branch had no reachable inputs yet.
    That belongs in the check's own coverage, so it is asserted here against the
    artifact on disk rather than against a hard-coded expectation of it.
    """
    import sources_sfi3 as sfi3

    result = pf.fresh_frame_disjointness()
    assert result["verdict"] == pf.PASS
    assert result["frame_sealed"] is sfi3.FRAME.exists()


# ---------------------------------------------------------------------------
# 6. sfi2_forensic_lineages_excluded


def _fixture_receipt(ids: list[str]) -> dict:
    return {
        "rebuild": {
            "E5_confirmed_selective_stale_escape": {
                "confirmed": [{"lineage_id": lineage_id} for lineage_id in ids]
            }
        }
    }


def test_sfi2_forensic_missing_receipt_fails(under_ns):
    result = pf.sfi2_forensic_lineages_excluded(receipt_path=under_ns / "nope.json")
    assert result["verdict"] == pf.FAIL


def test_sfi2_forensic_wrong_count_fails(under_ns):
    receipt = under_ns / "fixture_receipt.json"
    receipt.write_text(json.dumps(_fixture_receipt(["git:a/b:c.md"])), encoding="utf-8")
    result = pf.sfi2_forensic_lineages_excluded(receipt_path=receipt)
    assert result["verdict"] == pf.FAIL
    assert "expected 14" in result["detail"]


def test_sfi2_forensic_missing_from_spent_set_fails(under_ns):
    ids = [f"git:fixture/repo:file-{i}.md" for i in range(14)]
    receipt = under_ns / "fixture_receipt.json"
    receipt.write_text(json.dumps(_fixture_receipt(ids)), encoding="utf-8")
    result = pf.sfi2_forensic_lineages_excluded(receipt_path=receipt, spent=frozenset())
    assert result["verdict"] == pf.FAIL
    assert len(result["missing_from_spent_set"]) == 14


def test_sfi2_forensic_passes_when_all_pinned_ids_are_spent(under_ns):
    ids = [f"git:fixture/repo:file-{i}.md" for i in range(14)]
    receipt = under_ns / "fixture_receipt.json"
    receipt.write_text(json.dumps(_fixture_receipt(ids)), encoding="utf-8")
    result = pf.sfi2_forensic_lineages_excluded(receipt_path=receipt, spent=frozenset(ids))
    assert result["verdict"] == pf.PASS


def test_sfi2_forensic_passes_against_the_real_receipt_and_spent_set():
    result = pf.sfi2_forensic_lineages_excluded()
    assert result["verdict"] == pf.PASS
    assert len(result["pinned_lineage_ids"]) == 14


# --- INC-V2-097: a mutable pointer must name bytes git can return -----------


def _repo(tmp_path, *, target_on_disk=True, target_committed=True, declared_sha=...):
    """A real one-commit git repository, because the check asks git a question
    and a monkeypatched answer would test the mock rather than the query."""
    root = tmp_path / "repo"
    latest = root / "receipts" / "latest"
    latest.mkdir(parents=True)
    target_rel = "receipts/fixture--20260101T000000Z-abc.json"
    target = root / target_rel
    target.write_text(json.dumps({"is_evidence": True}), encoding="utf-8")
    body = {"is_evidence": False, "points_to": target_rel}
    if declared_sha is ...:
        body["points_to_file_sha256"] = "sha256:" + hashlib.sha256(target.read_bytes()).hexdigest()
    elif declared_sha is not None:
        body["points_to_file_sha256"] = declared_sha
    (latest / "fixture.json").write_text(json.dumps(body), encoding="utf-8")
    run = lambda *a: subprocess.run(a, cwd=root, check=True, capture_output=True)  # noqa: E731,S603
    run("git", "init", "-q")
    run("git", "config", "user.email", "t@example.invalid")
    run("git", "config", "user.name", "t")
    run("git", "add", "receipts/latest/fixture.json")
    if target_committed:
        run("git", "add", target_rel)
    run("git", "commit", "-q", "-m", "fixture")
    if not target_on_disk:
        target.unlink()
    return root, latest


def test_pointer_recoverability_passes_when_the_target_is_on_disk_and_committed(tmp_path):
    root, latest = _repo(tmp_path)
    result = pf.receipt_pointer_targets_are_recoverable(pointer_dir=latest, repo_root=root)
    assert result["verdict"] == pf.PASS
    assert result["pointers_checked"] == 1


def test_pointer_recoverability_fails_when_the_target_is_missing_from_disk(tmp_path):
    root, latest = _repo(tmp_path, target_on_disk=False)
    result = pf.receipt_pointer_targets_are_recoverable(pointer_dir=latest, repo_root=root)
    assert result["verdict"] == pf.FAIL
    assert len(result["absent_from_disk"]) == 1
    assert result["absent_at_head"] == []


def test_pointer_recoverability_fails_when_the_target_was_never_committed(tmp_path):
    """The harder half. Everything works in this checkout and nowhere else --
    which is exactly the state `ad99d18` committed and nothing detected."""
    root, latest = _repo(tmp_path, target_committed=False)
    result = pf.receipt_pointer_targets_are_recoverable(pointer_dir=latest, repo_root=root)
    assert result["verdict"] == pf.FAIL
    assert result["absent_from_disk"] == []
    assert len(result["absent_at_head"]) == 1


def test_pointer_recoverability_is_unverifiable_rather_than_failing_without_git(tmp_path):
    """Not knowing whether a file is committed is a different fact from knowing
    it is not. Reporting the first as the second would make this check fire in
    any export that carries no git directory, and a check that fires everywhere
    is one people learn to ignore.

    The tree here is otherwise PERFECT -- the pointer resolves on disk -- so the
    only thing separating this from the passing case is the absence of git. It
    is built without a repository rather than by deleting one, because removing
    a `.git` directory is unreliable on Windows (its object files are read-only)
    and a control that sometimes leaves a half-deleted repository behind is
    testing something other than what it claims.
    """
    root = tmp_path / "no_repo"
    latest = root / "receipts" / "latest"
    latest.mkdir(parents=True)
    target_rel = "receipts/fixture--20260101T000000Z-abc.json"
    (root / target_rel).write_text(json.dumps({"is_evidence": True}), encoding="utf-8")
    (latest / "fixture.json").write_text(
        json.dumps({"is_evidence": False, "points_to": target_rel}), encoding="utf-8"
    )
    result = pf.receipt_pointer_targets_are_recoverable(pointer_dir=latest, repo_root=root)
    assert result["verdict"] == pf.UNVERIFIABLE
    assert "git could not be consulted" in result["detail"]


def test_pointer_recoverability_passes_against_the_real_receipts_tree():
    result = pf.receipt_pointer_targets_are_recoverable()
    assert result["verdict"] == pf.PASS, result
    assert result["pointers_checked"] > 100


def test_pointer_recoverability_fails_when_the_target_is_not_the_pinned_bytes(tmp_path):
    """Every pointer in this tree states its target's digest, and until this
    existed nothing compared it. It matters because at least one reader follows
    `points_to` WITHOUT checking it: `sources_sfi3.py` derives the fourteen SFI2
    E5/E6 forensic lineages -- the cases that must not certify their own repair
    -- by following a pointer of this kind at import time, guarding the pointer
    being missing but not the pointer having moved."""
    root, latest = _repo(tmp_path, declared_sha="sha256:" + "0" * 64)
    result = pf.receipt_pointer_targets_are_recoverable(pointer_dir=latest, repo_root=root)
    assert result["verdict"] == pf.FAIL
    assert len(result["digest_mismatched"]) == 1
    assert result["absent_from_disk"] == [] and result["absent_at_head"] == []


def test_pointer_recoverability_passes_when_the_digest_matches(tmp_path):
    """The paired positive -- the default fixture states the true digest, so a
    check that rejected every pointer would fail here."""
    root, latest = _repo(tmp_path)
    result = pf.receipt_pointer_targets_are_recoverable(pointer_dir=latest, repo_root=root)
    assert result["verdict"] == pf.PASS
    assert result["digest_mismatched"] == []


def test_a_pointer_that_states_no_digest_is_not_treated_as_mismatched(tmp_path):
    """Absence of a claim is not a false claim. Older pointer schemas may carry
    no digest, and inventing a failure for them would make the check fire on
    files that never promised anything."""
    root, latest = _repo(tmp_path, declared_sha=None)
    result = pf.receipt_pointer_targets_are_recoverable(pointer_dir=latest, repo_root=root)
    assert result["verdict"] == pf.PASS
    assert result["digest_mismatched"] == []
