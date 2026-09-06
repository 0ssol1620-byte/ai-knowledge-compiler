"""Minimal reproductions of what the P0 smoke found.

These are regression tests for *findings*, not for desired behaviour. Two of
them assert that a defect is still present. If one starts failing, the defect
has been fixed and the finding needs re-stating -- which is a result, not a
broken test, and the receipt it supports must be re-run rather than edited.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]
ORACLE = NS / "oracle" / "independent_full_build.py"

sys.path.insert(0, str(ROOT / "packages" / "cir-python" / "src"))
sys.path.insert(0, str(NS / "compiler"))

import selective_build as selective  # noqa: E402
from akc_cir.identity import normalize_text_for_identity  # noqa: E402


def document(source_id: str, units: list[tuple[list[str], str]]) -> dict:
    records = [
        {
            "explicit_path": path,
            "heading": path[-1],
            "ordinal": index,
            "text": text,
            "text_sha256": "sha256:unused-in-this-test",
        }
        for index, (path, text) in enumerate(units)
    ]
    return {
        "schema": "tavonel.v2.canonical_document.v1",
        "source_family": "git_docs",
        "source_id": source_id,
        "version_id": "v",
        "version_time": {"valid_from": None, "known_at": None},
        "source_digest": "sha256:" + str(abs(hash(json.dumps(records)))),
        "license": "test",
        "units": records,
        "structure": {
            "order": ["/".join(record["explicit_path"]) for record in records],
            "block_count": len(records),
        },
    }


def test_case_only_edit_is_invisible_to_identity_normalisation() -> None:
    """The mechanism behind finding INC-V2-002, isolated from any corpus."""
    before = "we know the contents at compile time"
    after = "We know the contents at compile time"
    assert before != after
    assert normalize_text_for_identity(before) == normalize_text_for_identity(after)


def test_case_only_edit_is_caught_and_leaves_no_stale_artifact() -> None:
    """The P0 finding, reproduced until INC-V2-037 was repaired, now guarded.

    Shipped as `..._escapes_invalidation_and_leaves_a_stale_artifact`, asserting
    the defect was REPRODUCIBLE rather than acceptable: a case-only edit folded
    identity-equal, emitted no modification, and left a carried-forward section
    that the full rebuild disagreed with. It is no longer reproducible, because
    the change predicate no longer rides on the identity fold.

    The fold itself is untouched, and the test directly above this one still
    asserts that it folds these two strings equal. That pairing is the point:
    identity continuity preserved, change detection moved.
    """
    units_before = [
        (["Intro"], "we know the contents at compile time, so the text is hard coded"),
        (["Body"], "a second section that does not change at all in this revision"),
    ]
    units_after = [
        (["Intro"], "We know the contents at compile time, so the text is hard coded"),
        (["Body"], "a second section that does not change at all in this revision"),
    ]
    result = selective.run_pair(
        document("test:case-only", units_before),
        document("test:case-only", units_after),
    )
    full = selective.build_all(document("test:case-only", units_after))

    stale = [
        artifact
        for artifact in result["carried_forward_set"]
        if result["state"][artifact] != full[artifact]
    ]
    assert stale == [], f"case-only edit left stale artifact(s): {stale}"
    #: Power. An empty `stale` list is only meaningful if something was actually
    #: carried forward to disagree -- a run that rebuilt everything, or produced
    #: no artifacts at all, would satisfy the assertion above while proving
    #: nothing. The unchanged Body section is what must still be carried.
    assert result["carried_forward_set"], "nothing was carried forward; the check is vacuous"
    #: and the edited section must be on the other side of that split.
    edited = [
        artifact
        for artifact in full
        if artifact.startswith("section:") and artifact not in result["carried_forward_set"]
    ]
    assert edited, "the edited section was carried forward rather than rebuilt"


def test_reorder_only_edit_is_caught_and_rebuilds_only_order_sensitive_artifacts() -> None:
    """The structural positive control, as a unit test.

    Reading order changes, every section text is byte-identical, and exactly the
    two order-sensitive artifacts rebuild.
    """
    units = [
        (["A"], "the first section body, long enough to be admitted as a unit"),
        (["B"], "the second section body, long enough to be admitted as a unit"),
        (["C"], "the third section body, long enough to be admitted as a unit"),
        (["D"], "the fourth section body, long enough to be admitted as a unit"),
    ]
    before = document("test:reorder", units)
    after = document("test:reorder", [units[2], units[3], units[0], units[1]])

    result = selective.run_pair(before, after)
    full = selective.build_all(after)

    assert result["structural_change_present"]
    assert {artifact.split(":")[0] for artifact in result["selective_rebuild_set"]} == {
        "document-index",
        "structure-map",
    }
    assert result["state"] == full, "selective state must equal the full rebuild"


def test_oracle_refuses_to_import_the_implementation_it_audits() -> None:
    """The import guard fires. A guard nobody has seen refuse anything is a claim."""
    probe = (
        "import runpy, sys, json\n"
        "sys.argv = ['oracle', '--after', 'x', '--output', 'y']\n"
        "runpy.run_path(r'''" + str(ORACLE) + "''')\n"
        "try:\n"
        "    import akc_cir\n"
        "    print(json.dumps({'blocked': False}))\n"
        "except ImportError:\n"
        "    print(json.dumps({'blocked': True}))\n"
    )
    completed = subprocess.run(
        [sys.executable, "-I", "-S", "-c", probe],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        check=False,
    )
    lines = [line for line in completed.stdout.splitlines() if line.startswith("{")]
    assert lines, completed.stderr
    assert json.loads(lines[-1])["blocked"] is True


def test_oracle_is_deterministic_across_runs() -> None:
    """Same input, two separate processes, same state hash."""
    canonical = sorted(
        (NS / "artifacts" / "development" / "canonical").glob("*/after.json")
    )
    if not canonical:  # the smoke has not been run in this checkout
        return
    target = canonical[0]
    hashes = []
    for attempt in range(2):
        output = NS / "artifacts" / "development" / "work" / ("determinism-%d.json" % attempt)
        completed = subprocess.run(
            [
                sys.executable,
                "-I",
                "-S",
                str(ORACLE),
                "--after",
                str(target),
                "--output",
                str(output),
            ],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        hashes.append(json.loads(output.read_text(encoding="utf-8"))["state_hash"])
    assert hashes[0] == hashes[1]
