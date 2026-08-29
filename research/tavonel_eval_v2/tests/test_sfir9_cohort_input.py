"""Controls for the cohort-input binding.

Every attack here has a paired control that the same sandbox accepts, because a
refusal that fires on everything is not a check. The sandbox is built from a
frame receipt that would be accepted; each test breaks exactly one thing.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(NS / "tools"))

import sfir9_cohort_input as ci  # noqa: E402

MEMBER_BODY = b"ID,UUID,Host Type\n1,10,GitHub\n" * 64
GOOD_PREDICATES = [
    {"field": "host", "op": "eq", "value": "github"},
    {"field": "spdx_license_id", "op": "in", "value": ["MIT", "Apache-2.0"]},
    {"field": "created_utc", "op": "on_or_before", "value": "2017-01-12"},
    {"field": "last_activity_utc", "op": "on_or_after", "value": "2019-01-12"},
]


class Sandbox:
    """The namespace, plus the two repository facts a sandbox cannot have."""

    def __init__(self, root: Path, readers: dict[str, Path]) -> None:
        self.root = root
        self.readers = readers

    def __truediv__(self, other):
        return self.root / other


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """A namespace whose every input is the one the binding should accept."""
    root = tmp_path / "ns"
    (root / "receipts").mkdir(parents=True)

    member = tmp_path / "catalogue.csv"
    member.write_bytes(MEMBER_BODY)
    member_sha = "sha256:" + hashlib.sha256(MEMBER_BODY).hexdigest()

    (root / ci.SNAPSHOT_RECEIPT).write_text(
        json.dumps(
            {
                "zenodo_doi": "10.5281/zenodo.3626071",
                "archive_filename": "libraries-1.6.0.tar.gz",
                "archive_bytes": 24890021718,
                "content_sha256": "sha256:" + "a" * 64,
                "extracted_member_name": "repositories.csv",
                "extracted_member_path": str(member),
                "extracted_member_bytes": len(MEMBER_BODY),
                "extracted_member_sha256": member_sha,
            }
        ),
        encoding="utf-8",
    )
    (root / ci.INHERITED_FRAME_RECEIPT).write_text(
        json.dumps(
            {
                "frame_rule": {
                    "predicates": GOOD_PREDICATES,
                    "ranking": [{"field": "catalog_rank_value", "descending": True}],
                    "tie_breaker": "record_id",
                    "snapshot_sha256": member_sha,
                }
            }
        ),
        encoding="utf-8",
    )

    # The readers live where the binding will address them: under the repository
    # root, which here is the sandbox.
    readers = {}
    for relative in ci.INPUT_MODULES:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"# reader\n")
        readers[relative] = path

    # A sandbox has no git history, so the two repository facts are supplied.
    # Every test that is not about them inherits a consistent pair.
    monkeypatch.setattr(
        ci, "_git_committed_bytes", lambda _root, relative: readers[relative].read_bytes()
    )
    monkeypatch.setattr(
        ci,
        "_added_at",
        lambda _root, path: "2026-08-27T00:00:00+09:00"
        if path == ci.FRAME_SOURCE
        else "2026-08-29T00:00:00+09:00",
    )
    return Sandbox(root, readers)


def _bind(sandbox, **overrides):
    origins = {Path(relative).stem: str(path) for relative, path in sandbox.readers.items()}
    kwargs = {
        "namespace": sandbox.root,
        "repository_root": sandbox.root,
        "origins": origins,
        **overrides,
    }
    return ci.binding(**kwargs)


# --- the control: the sandbox as built is accepted -------------------------


def test_a_correct_sandbox_binds(sandbox):
    report = _bind(sandbox)
    assert ci.verify(report)["verified"], ci.verify(report)["problems"]
    assert len(report["inherited_frame"]["predicates"]) == 4
    member = report["member_verification"]
    assert member["sha256_recomputed"] == member["sha256_recorded"]


# --- the catalogue ---------------------------------------------------------


def test_an_absent_member_is_refused(sandbox):
    Path(json.loads((sandbox / ci.SNAPSHOT_RECEIPT).read_text())["extracted_member_path"]).unlink()
    with pytest.raises(ci.CohortInputRefused) as caught:
        _bind(sandbox)
    assert caught.value.code == ci.MEMBER_ABSENT


def test_a_member_whose_bytes_changed_is_refused(sandbox):
    path = Path(json.loads((sandbox / ci.SNAPSHOT_RECEIPT).read_text())["extracted_member_path"])
    path.write_bytes(MEMBER_BODY + b"one more row\n")
    with pytest.raises(ci.CohortInputRefused) as caught:
        _bind(sandbox)
    assert caught.value.code == ci.DIGEST_MISMATCH


def test_the_member_is_hashed_past_the_first_chunk(sandbox):
    """A prefix hash would accept a file whose tail was replaced.

    The catalogue is ten gigabytes and the rows that matter are not at the top.
    """
    path = Path(json.loads((sandbox / ci.SNAPSHOT_RECEIPT).read_text())["extracted_member_path"])
    tampered = bytearray(MEMBER_BODY)
    tampered[-1] = ord("X")
    path.write_bytes(bytes(tampered))
    with pytest.raises(ci.CohortInputRefused) as caught:
        _bind(sandbox)
    assert caught.value.code == ci.DIGEST_MISMATCH


def test_a_small_chunk_size_reaches_the_same_digest(sandbox):
    """The control for the test above: chunking must not change the answer."""
    path = Path(json.loads((sandbox / ci.SNAPSHOT_RECEIPT).read_text())["extracted_member_path"])
    assert ci.sha256_of_file(path, chunk=7) == ci.sha256_of_file(path)


def test_an_absent_snapshot_receipt_is_refused(sandbox):
    (sandbox / ci.SNAPSHOT_RECEIPT).unlink()
    with pytest.raises(ci.CohortInputRefused) as caught:
        _bind(sandbox)
    assert caught.value.code == ci.SNAPSHOT_ABSENT


# --- the readers -----------------------------------------------------------


def test_a_reader_that_differs_from_the_commit_is_refused(sandbox, monkeypatch):
    monkeypatch.setattr(ci, "_git_committed_bytes", lambda _root, _relative: b"# something else\n")
    with pytest.raises(ci.CohortInputRefused) as caught:
        _bind(sandbox)
    assert caught.value.code == ci.BYTES_MISMATCH


def test_a_reader_imported_from_elsewhere_is_refused(sandbox, tmp_path):
    elsewhere = tmp_path / "elsewhere.py"
    elsewhere.write_bytes(b"# reader\n")
    origins = {Path(r).stem: str(elsewhere) for r in ci.INPUT_MODULES}
    with pytest.raises(ci.CohortInputRefused) as caught:
        _bind(sandbox, origins=origins)
    assert caught.value.code == ci.ORIGIN_MISMATCH


def test_a_reader_with_no_recorded_origin_is_refused(sandbox):
    with pytest.raises(ci.CohortInputRefused) as caught:
        _bind(sandbox, origins={})
    assert caught.value.code == ci.ORIGIN_MISMATCH


def test_every_reader_is_bound_by_bytes_and_by_blob(sandbox):
    report = _bind(sandbox)
    # Named explicitly. Comparing against INPUT_MODULES would narrow exactly as
    # far as INPUT_MODULES narrowed, which is no check at all -- and the first
    # draft of this binding did narrow, missing the projection and the frame.
    assert {record["module"] for record in report["input_modules"]} == {
        "sfir7_catalog_parser",
        "sfir7_projection",
        "sfir7_frame",
        "sfir7_roots",
    }
    for record in report["input_modules"]:
        assert record["sha256"].startswith("sha256:")
        assert len(record["git_blob_id"]) == 40
        assert record["working_tree_bytes"] > 0


def test_a_reader_that_is_not_on_disk_is_refused(sandbox):
    """The sandbox always has its readers, so this branch needs its own control."""
    sandbox.readers[ci.INPUT_MODULES[0]].unlink()
    with pytest.raises(ci.CohortInputRefused) as caught:
        _bind(sandbox)
    assert caught.value.code == ci.BYTES_MISMATCH
    assert "does not exist" in str(caught.value)


def test_a_path_absent_from_the_commit_is_refused():
    """The real git call, against this repository.

    Everywhere else `_git_committed_bytes` is stubbed, which leaves its own
    failure branch unexercised -- and that branch is the one that decides
    whether an untracked reader can be bound.
    """
    with pytest.raises(ci.CohortInputRefused) as caught:
        ci._git_committed_bytes(NS.parents[1], "research/tavonel_eval_v2/tools/not-a-file.py")
    assert caught.value.code == ci.BYTES_MISMATCH
    assert "is not in the commit" in str(caught.value)


def test_a_tracked_path_returns_its_committed_bytes():
    """Control for the test above: the same call succeeds on a tracked file."""
    committed = ci._git_committed_bytes(
        NS.parents[1], "research/tavonel_eval_v2/tools/sfir9_protocol.py"
    )
    assert committed.startswith(b"#!/usr/bin/env python3")


# --- the inherited frame ---------------------------------------------------


def test_an_absent_frame_receipt_is_refused(sandbox):
    """SFIR9 has no eligibility rule of its own and must not invent one."""
    (sandbox / ci.INHERITED_FRAME_RECEIPT).unlink()
    with pytest.raises(ci.CohortInputRefused) as caught:
        _bind(sandbox)
    assert caught.value.code == ci.FRAME_ABSENT


def test_a_frame_composed_against_other_bytes_is_refused(sandbox):
    receipt = json.loads((sandbox / ci.INHERITED_FRAME_RECEIPT).read_text())
    receipt["frame_rule"]["snapshot_sha256"] = "sha256:" + "b" * 64
    (sandbox / ci.INHERITED_FRAME_RECEIPT).write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(ci.CohortInputRefused) as caught:
        _bind(sandbox)
    assert caught.value.code == ci.FRAME_SNAPSHOT_MISMATCH


def test_a_predicate_naming_an_identity_field_is_refused(sandbox):
    """Filtering on identity is a hand-picked roster wearing a rule's clothes."""
    receipt = json.loads((sandbox / ci.INHERITED_FRAME_RECEIPT).read_text())
    receipt["frame_rule"]["predicates"].append(
        {"field": "record_id", "op": "in", "value": ["12345"]}
    )
    (sandbox / ci.INHERITED_FRAME_RECEIPT).write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(ci.CohortInputRefused) as caught:
        _bind(sandbox)
    assert caught.value.code == ci.FRAME_NAMES_IDENTITY


def test_a_frame_younger_than_the_protocol_is_refused(sandbox, monkeypatch):
    monkeypatch.setattr(
        ci,
        "_added_at",
        lambda _root, path: "2026-08-30T00:00:00+09:00"
        if path == ci.FRAME_SOURCE
        else "2026-08-29T00:00:00+09:00",
    )
    with pytest.raises(ci.CohortInputRefused) as caught:
        _bind(sandbox)
    assert caught.value.code == ci.FRAME_NOT_INDEPENDENT


def test_a_frame_the_same_age_as_the_protocol_is_refused(sandbox, monkeypatch):
    """Strictly older, not merely not-younger. Same commit is not independence."""
    monkeypatch.setattr(ci, "_added_at", lambda _root, _path: "2026-08-29T00:00:00+09:00")
    with pytest.raises(ci.CohortInputRefused) as caught:
        _bind(sandbox)
    assert caught.value.code == ci.FRAME_NOT_INDEPENDENT


def test_a_path_that_was_never_added_has_no_age(tmp_path, monkeypatch):
    # No sandbox fixture here: it stubs _added_at, which is the function under
    # test. A test of a stub is a test of the stub.
    monkeypatch.setattr(ci, "_git", lambda _root, *_args: "")
    with pytest.raises(ci.CohortInputRefused) as caught:
        ci._added_at(tmp_path, "whatever")
    assert caught.value.code == ci.FRAME_ABSENT


def test_the_oldest_adding_commit_is_the_age(tmp_path, monkeypatch):
    """Control for the test above, and git log lists newest first."""
    monkeypatch.setattr(
        ci, "_git", lambda _root, *_args: "2026-08-29T00:00:00+09:00\n2026-08-27T00:00:00+09:00\n"
    )
    assert ci._added_at(tmp_path, "whatever") == "2026-08-27T00:00:00+09:00"


def test_the_binding_records_what_it_does_not_inherit(sandbox):
    """N agreeing at 50 through unrelated arithmetic is a coincidence, not a copy."""
    frame = _bind(sandbox)["inherited_frame"]
    independence = frame["independence"]
    assert (
        independence["frame_entered_repository_at"]
        < independence["protocol_entered_repository_at"]
    )
    assert set(frame["what_is_not_inherited"]) == {"n", "roots", "findings"}
    assert "coincidence" in frame["what_is_not_inherited"]["n"]


def test_the_frame_receipt_is_bound_by_its_own_bytes(sandbox):
    before = _bind(sandbox)["inherited_frame"]["receipt_sha256"]
    receipt = json.loads((sandbox / ci.INHERITED_FRAME_RECEIPT).read_text())
    receipt["frame_rule"]["tie_breaker"] = "record_id"  # same value, different bytes
    (sandbox / ci.INHERITED_FRAME_RECEIPT).write_text(
        json.dumps(receipt, indent=1), encoding="utf-8"
    )
    assert _bind(sandbox)["inherited_frame"]["receipt_sha256"] != before


# --- verification ----------------------------------------------------------


def test_an_edited_receipt_fails_verification(sandbox):
    report = _bind(sandbox)
    report["catalogue"]["zenodo_doi"] = "10.5281/zenodo.0000000"
    assert not ci.verify(report)["verified"]


def test_the_digest_does_not_cover_itself(sandbox):
    report = _bind(sandbox)
    body = {key: value for key, value in report.items() if key != "binding_digest"}
    assert ci._digest(body) == report["binding_digest"]


def test_verification_reports_missing_predicates(sandbox):
    report = _bind(sandbox)
    report["inherited_frame"]["predicates"] = []
    problems = ci.verify(report)["problems"]
    assert any("predicates" in problem for problem in problems)


def test_verification_reports_a_member_digest_that_is_not_the_pinned_one(sandbox):
    """Falsifiable, unlike the boolean this replaced.

    Two earlier drafts recorded `rehashed_in_full: True` and
    `committed_bytes_equal_working_bytes: True`. Neither could ever have held
    another value, because the binding raises before reaching them.
    """
    report = _bind(sandbox)
    report["member_verification"]["sha256_recomputed"] = "sha256:" + "c" * 64
    problems = ci.verify(report)["problems"]
    assert any("recomputed member digest" in problem for problem in problems)


def test_the_binding_records_no_unfalsifiable_boolean(sandbox):
    source = (NS / "tools/sfir9_cohort_input.py").read_text(encoding="utf-8")
    for field in (
        '"rehashed_in_full"',
        '"committed_bytes_equal_working_bytes"',
        '"frame_is_older"',
    ):
        assert f"{field}: True" not in source, field


def test_verification_reports_no_bound_readers(sandbox):
    report = _bind(sandbox)
    report["input_modules"] = []
    problems = ci.verify(report)["problems"]
    assert any("input modules" in problem for problem in problems)


# --- the runner ------------------------------------------------------------


def test_a_refused_binding_exits_nonzero(sandbox, monkeypatch, capsys):
    def refuse(**_kwargs):
        raise ci.CohortInputRefused(ci.MEMBER_ABSENT, "not on disk")

    monkeypatch.setattr(ci, "binding", refuse)
    assert ci.main(["--namespace", str(sandbox.root)]) == 1
    assert "REFUSED" in capsys.readouterr().out


def test_the_binding_authorises_nothing_and_says_so(sandbox):
    report = _bind(sandbox)
    assert "authorises nothing" not in report["this_binding_authorises_nothing"]
    assert "instrument freeze" in report["this_binding_authorises_nothing"]

def test_a_predicate_on_a_field_the_projection_withholds_is_refused(sandbox):
    """`fork` and `status` reach the parser and never reach the rule.

    The first draft of this binding listed the allowed fields by hand and named
    the raw publisher fields, so it would have admitted exactly this.
    """
    receipt = json.loads((sandbox / ci.INHERITED_FRAME_RECEIPT).read_text())
    receipt["frame_rule"]["predicates"].append(
        {"field": "fork", "op": "eq", "value": "false"}
    )
    (sandbox / ci.INHERITED_FRAME_RECEIPT).write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(ci.CohortInputRefused) as caught:
        _bind(sandbox)
    assert caught.value.code == ci.FRAME_NAMES_IDENTITY


def test_a_predicate_on_a_projected_field_is_accepted(sandbox):
    """The other direction of the same bug: the hand-written list refused this."""
    receipt = json.loads((sandbox / ci.INHERITED_FRAME_RECEIPT).read_text())
    receipt["frame_rule"]["predicates"].append(
        {"field": "primary_language", "op": "in", "value": ["Python"]}
    )
    (sandbox / ci.INHERITED_FRAME_RECEIPT).write_text(json.dumps(receipt), encoding="utf-8")
    assert len(_bind(sandbox)["inherited_frame"]["predicates"]) == 5


def test_the_eligibility_fields_are_sfir7s_own_minus_identity():
    """Read live, so a field added to the projection cannot silently become
    available to a predicate without this test noticing."""
    import sfir7_frame

    assert ci.eligibility_fields() == frozenset(sfir7_frame.SELECTABLE_FIELDS) - {
        "record_id",
        "host_uuid",
    }
    assert "record_id" not in ci.eligibility_fields()
    assert "fork" not in ci.eligibility_fields()
    assert "primary_language" in ci.eligibility_fields()


def test_the_binding_records_the_fields_a_predicate_could_have_named(sandbox):
    """A refusal that never fires is only meaningful if the set is written down."""
    assert _bind(sandbox)["eligibility_fields"] == sorted(ci.eligibility_fields())


def test_only_one_identity_field_does_work_and_that_is_declared():
    """host_uuid is outside SFIR7's selectable set, so subtracting it is a no-op.

    Named anyway, because an omission is invisible and a declared exclusion is
    not. A mutation removing it survives; the source says why.
    """
    import sfir7_frame

    assert "host_uuid" not in sfir7_frame.SELECTABLE_FIELDS
    assert "record_id" in sfir7_frame.SELECTABLE_FIELDS
    source = (NS / "tools/sfir9_cohort_input.py").read_text(encoding="utf-8")
    assert "declared equivalent rather than scored" in source
