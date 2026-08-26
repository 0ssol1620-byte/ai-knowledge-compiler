"""Controls for the SFIR4 pre-freeze recoverability gate.

The gate exists because INC-V2-089 proved that a sha-256 pin and a recoverable
file are different things, and the study had only the first. These tests check
the properties that difference turns on: that the closure is computed from what
executes rather than from a list someone maintains, that it is computed without
running the instrument, and that it fails closed.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
for extra in (NS, NS / "tools"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import sfir4_execution_closure as closure  # noqa: E402

# ---------------------------------------------------------------------------
# The closure is complete and is computed without executing anything
# ---------------------------------------------------------------------------


def test_every_declared_entry_point_exists() -> None:
    for relative in closure.ENTRY_POINTS:
        assert (NS / relative).is_file(), relative


def test_every_declared_verification_entry_point_exists() -> None:
    for relative in closure.VERIFICATION_ENTRY_POINTS:
        assert (NS / relative).is_file(), relative


def test_the_closure_carries_the_controls_and_not_only_the_code() -> None:
    """The correction INC-V2-089's own file list forced.

    A frozen protocol attestation in this study pins
    ``tests/test_v2r3_contract_consistency.py``, and that file is one of the 29
    the incident lost. A gate that covered only execution would have reported
    PASS while permitting the identical failure.
    """
    files = set(closure.gate()["manifest"])
    for expected in (
        "research/tavonel_eval_v2/tests/test_sfir4_locator.py",
        "research/tavonel_eval_v2/tests/test_sfir4_identity_domain.py",
        "research/tavonel_eval_v2/tests/test_sfir4_response_evidence.py",
        "research/tavonel_eval_v2/tools/anti_blocker_audit.py",
        "research/tavonel_eval_v2/tools/verify_frozen_instrument_integrity.py",
    ):
        assert expected in files, expected


def test_the_closure_stays_inside_this_repository() -> None:
    """Nothing outside the study and the Protected Core may enter the manifest."""
    for name in closure.gate()["manifest"]:
        assert name.startswith(
            ("research/tavonel_eval_v2/", "packages/cir-python/src/akc_cir/")
        ), name


def test_every_declared_data_file_exists() -> None:
    for relative in closure.DECLARED_DATA:
        assert (NS / relative).is_file(), relative


def test_the_closure_resolves_every_import_it_meets() -> None:
    """An unresolved import means the closure may be missing files.

    That is the failure this gate exists to prevent, so it is a REFUSE, not a
    warning. If a new third-party dependency appears, add it to THIRD_PARTY --
    deliberately, in a diff someone reads.
    """
    body = closure.gate()
    assert body["unresolved_imports"] == [], body["unresolved_imports"]


def test_the_closure_reaches_beyond_the_entry_points() -> None:
    """A closure equal to its entry points would mean the walk did nothing."""
    body = closure.gate()
    assert body["totals"]["closure_files"] > len(closure.ENTRY_POINTS) + len(closure.DECLARED_DATA)


def test_the_closure_reaches_the_protected_core_the_study_executes() -> None:
    body = closure.gate()
    assert any(name.endswith("akc_cir/semantic_diff.py") for name in body["manifest"]), (
        "the study imports the Protected Core; a closure that misses it is not a closure"
    )


def test_the_closure_reaches_the_new_sfir4_modules() -> None:
    body = closure.gate()
    files = set(body["manifest"])
    for expected in (
        "research/tavonel_eval_v2/tools/sfir4_locator.py",
        "research/tavonel_eval_v2/tools/sfir4_identity_domain.py",
        "research/tavonel_eval_v2/tools/sfir4_response_evidence.py",
    ):
        assert expected in files, expected


def test_imports_are_read_by_parsing_and_not_by_importing() -> None:
    """``sources_sfir4`` runs a disjointness assertion at module scope.

    A closure built by importing would execute the instrument in order to
    describe it. This test reads a file that has never been imported in this
    process and confirms the analysis still works.
    """
    source = "import os\nfrom pathlib import Path\nimport sfir4_locator\n"
    entries = closure.imported_names(source, Path("synthetic.py"))
    modules = {name for name, _ in entries}
    assert modules == {"os", "pathlib", "sfir4_locator"}


def test_a_from_import_of_an_attribute_is_not_reported_unresolved() -> None:
    """``from common import NS`` names an attribute, not a module.

    Treating every ``X.n`` as a module produced dozens of phantom unresolved
    names and buried the genuine ones.
    """
    entries = closure.imported_names("from common import NS, sha_file\n", Path("s.py"))
    assert entries == [("common", ("common.NS", "common.sha_file"))]
    assert closure.resolve_module("common") is not None
    assert closure.resolve_module("common.NS") is None


def test_a_file_that_does_not_parse_refuses_rather_than_being_skipped() -> None:
    with pytest.raises(closure.ClosureRefused, match="does not parse"):
        closure.imported_names("def (\n", Path("broken.py"))


def test_an_absent_entry_point_refuses() -> None:
    with pytest.raises(closure.ClosureRefused, match="entry point is absent"):
        closure.closure(("tools/does_not_exist.py",))


# ---------------------------------------------------------------------------
# The manifest and the verdict
# ---------------------------------------------------------------------------


def test_the_manifest_covers_every_file_in_the_closure() -> None:
    body = closure.gate()
    assert len(body["manifest"]) == body["totals"]["closure_files"]


def test_every_manifest_entry_is_a_sha256() -> None:
    for digest in closure.gate()["manifest"].values():
        assert digest.startswith("sha256:")
        assert len(digest) == len("sha256:") + 64


def test_committed_and_uncommitted_partition_the_closure() -> None:
    totals = closure.gate()["totals"]
    assert totals["committed_at_head"] + totals["uncommitted"] == totals["closure_files"]


def test_byte_identity_is_checked_on_top_of_being_committed() -> None:
    """Committed is not recoverable if the blob is not the file."""
    totals = closure.gate()["totals"]
    assert (
        totals["byte_identical_to_head"] + totals["divergent_from_head"]
        == totals["committed_at_head"]
    )


def test_the_gate_reads_head_and_not_the_index() -> None:
    """A staged file must not count as recoverable.

    ``git ls-files`` reports the index, so staging alone would flip this gate to
    PASS at the moment before the commit that makes its claim true.
    """
    body = closure.gate()
    assert "why_head_and_not_the_index" in body
    assert len(body["head_commit"]) == 40


def test_the_verdict_is_refuse_exactly_when_a_reason_exists() -> None:
    body = closure.gate()
    assert (body["verdict"] == "REFUSE") == bool(body["why"])


def test_uncommitted_files_are_named_not_merely_counted() -> None:
    """The founder asked for the exact list; a count is not actionable."""
    body = closure.gate()
    assert len(body["untracked"]) == body["totals"]["uncommitted"]
    if body["untracked"]:
        assert all(isinstance(name, str) and name for name in body["untracked"])


def test_require_recoverable_fails_closed() -> None:
    body = closure.gate()
    if body["verdict"] == "PASS":
        assert closure.require_recoverable()["verdict"] == "PASS"
    else:
        with pytest.raises(closure.ClosureRefused, match="not recoverable"):
            closure.require_recoverable()


def test_the_gate_reports_zero_gpu_and_zero_cost() -> None:
    body = closure.gate()
    assert body["gpu_seconds"] == 0
    assert body["estimated_cost_usd"] == 0.0
    assert body["read_only"] is True


def test_the_gate_states_that_it_does_not_repair_history() -> None:
    """It must not be mistaken for a fix for INC-V2-089. Nothing fixes that."""
    body = closure.gate()
    assert "never_repairs_history" in body
    assert "prospective" in body["never_repairs_history"]
