from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

import sfir9_selection  # noqa: E402
import sfir10r1_protocol as p  # noqa: E402
import sfir10r1_runner as r  # noqa: E402
import sfir10r1_transport as t  # noqa: E402


class FakeResponse:
    def __init__(self, body):
        self.body = body


class FakeTransport:
    def __init__(self, responses=(), *, identity_error=None):
        self.responses = list(responses)
        self.identity_error = identity_error

    def resolve_canonical_address(self, address, expected_uuid):
        if self.identity_error:
            raise self.identity_error
        return {
            "canonical_address": "live/name",
            "observed_repository_id": str(expected_uuid),
            "default_branch": "main",
        }

    def get(self, url):
        if not self.responses:
            raise AssertionError(f"unexpected get {url}")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return FakeResponse(item)


def root():
    return {"host_uuid": "7", "catalogue_address": "old/name", "selection_ordinal": 1}


def test_selection_uses_next_partition_and_is_disjoint_from_partition_zero():
    rule = r._selection_rule()
    assert rule.partition_count == 64
    assert rule.partition_index == 1
    prior = sfir9_selection.FrozenSelection(
        salt=p.SELECTION_SALT,
        partition_count=p.PARTITION_COUNT,
        partition_index=0,
        envelope=rule.envelope,
        spent_host_uuids=frozenset(),
    )
    for identity in map(str, range(1, 10000)):
        assert not (rule.admits(identity) and prior.admits(identity))


def test_runner_contains_no_capacity_threshold_literals():
    source = inspect.getsource(r)
    for forbidden in (
        "MINIMUM_C =",
        "MINIMUM_Q =",
        "MAXIMUM_Q =",
        "USABLE_CHARGE_PER_WINDOW =",
        "PER_ROOT_CHARGE_ALLOWANCE =",
    ):
        assert forbidden not in source


def test_one_tree_exhausts_and_records_candidate(tmp_path):
    commit = {"sha": "d" * 40, "commit": {"tree": {"sha": "a" * 40}}}
    tree = {"tree": [{"path": "README.md", "type": "blob", "sha": "b" * 40}]}
    fake = FakeTransport([commit, tree])
    with r.RootStore(tmp_path / "root.sqlite") as store:
        result = r._run_root(store=store, client=fake, root=root())
        candidates = store.candidates()
    assert result == r.EXHAUSTED
    assert candidates == [("7", "README.md", "b" * 40)]


def test_rate_window_stop_releases_leased_frontier_entry_for_resume(tmp_path):
    commit = {"sha": "d" * 40, "commit": {"tree": {"sha": "a" * 40}}}
    fake = FakeTransport([commit, t.SegmentClose("window")])
    db = tmp_path / "root.sqlite"
    with r.RootStore(db) as store, pytest.raises(t.SegmentClose):
        r._run_root(store=store, client=fake, root=root())
    with r.RootStore(db) as reopened:
        assert reopened.frontier.pending_count() == 1
        pending = list(reopened.frontier.pending())
        assert pending[0].tree_sha == "a" * 40


def test_non_rate_transport_failure_is_stopped_not_exhausted(tmp_path):
    commit = {"sha": "d" * 40, "commit": {"tree": {"sha": "a" * 40}}}
    fake = FakeTransport([commit, t.TransportStop("403 with quota remaining")])
    with r.RootStore(tmp_path / "root.sqlite") as store:
        result = r._run_root(store=store, client=fake, root=root())
        assert store.frontier.pending_count() == 1
    assert result == r.STOPPED


def test_identity_refusal_is_distinct_from_stopped(tmp_path):
    fake = FakeTransport(identity_error=t.IdentityRefused("wrong numeric id"))
    with r.RootStore(tmp_path / "root.sqlite") as store, pytest.raises(t.IdentityRefused):
        r._run_root(store=store, client=fake, root=root())


def test_default_branch_absence_cannot_be_guessed(tmp_path):
    class NoBranch(FakeTransport):
        def resolve_canonical_address(self, address, expected_uuid):
            return {
                "canonical_address": "live/name",
                "observed_repository_id": str(expected_uuid),
                "default_branch": None,
            }

    with (
        r.RootStore(tmp_path / "root.sqlite") as store,
        pytest.raises(t.TransportStop, match="no default branch"),
    ):
        r._run_root(store=store, client=NoBranch(), root=root())


def test_candidate_extension_is_taken_from_protocol(tmp_path):
    commit = {"sha": "d" * 40, "commit": {"tree": {"sha": "a" * 40}}}
    tree = {
        "tree": [
            {"path": "x.md", "type": "blob", "sha": "b" * 40},
            {"path": "x.bin", "type": "blob", "sha": "c" * 40},
        ]
    }
    with r.RootStore(tmp_path / "root.sqlite") as store:
        result = r._run_root(store=store, client=FakeTransport([commit, tree]), root=root())
        candidates = store.candidates()
    assert result == r.EXHAUSTED
    assert [row[1] for row in candidates] == ["x.md"]


def test_mark_remaining_stopped_never_turns_unfinished_into_exhausted():
    state = {"root_states": {"1": r.ACTIVE, "2": r.UNSTARTED, "3": r.REFUSED}}
    r._mark_remaining_stopped(state)
    assert state["root_states"] == {"1": r.STOPPED, "2": r.STOPPED, "3": r.REFUSED}


def test_terminal_requires_every_root_terminal():
    assert not r._terminal_state({"root_states": {"1": r.EXHAUSTED, "2": r.ACTIVE}})
    assert r._terminal_state({"root_states": {"1": r.EXHAUSTED, "2": r.STOPPED, "3": r.REFUSED}})


def test_all_refused_is_not_an_exact_zero_or_fail():
    result = r._capacity_interpretation(lower_bound=0, exhausted=0, stopped=0, refused=50)
    assert result["counted"] == 0
    assert result["complete"] is False
    assert result["exact"] is None
    assert result["verdict"] == "MEASURED_NOT_SEALABLE"


def test_counted_root_requires_immutable_revision_snapshot():
    with pytest.raises(r.RunnerRefused, match="immutable revision snapshot"):
        r._validate_root_evidence(status=r.EXHAUSTED, candidates=[], snapshot=None)


def test_refused_root_cannot_carry_post_attestation_evidence():
    with pytest.raises(r.RunnerRefused, match="post-attestation evidence"):
        r._validate_root_evidence(
            status=r.REFUSED,
            candidates=[],
            snapshot={
                "repository_numeric_id": "7",
                "canonical_address_at_seed": "live/name",
                "default_branch_at_seed": "main",
                "root_commit_sha": "d" * 40,
                "root_tree_sha": "a" * 40,
            },
        )


def test_complete_below_threshold_can_fail_only_with_counted_exhausted_roots():
    result = r._capacity_interpretation(lower_bound=100, exhausted=49, stopped=0, refused=1)
    assert result["complete"] is True
    assert result["exact"] == 100
    assert result["verdict"] == "CAPACITY_CRITERION_NOT_MET"


def test_seeded_but_unexpanded_root_is_never_reseeded(tmp_path):
    db = tmp_path / "root.sqlite"
    first_commit = {"sha": "d" * 40, "commit": {"tree": {"sha": "a" * 40}}}
    with r.RootStore(db) as store:
        canonical, repository_id = r._seed_or_attest(
            store=store,
            client=FakeTransport([first_commit]),
            root=root(),
        )
        assert canonical == "live/name"
        assert repository_id == "7"
        # Frontier enqueue records the root tree in `visited` immediately. This
        # falsifies the hostile hypothesis that V10 could re-seed solely because
        # no expansion had completed yet; R1's snapshot is additional evidence,
        # not a repair of that non-defect.
        assert store.frontier.visited_count() == 1
        assert store.frontier.pending_count() == 1
        snapshot = store.snapshot()
        assert snapshot == {
            "repository_numeric_id": "7",
            "canonical_address_at_seed": "live/name",
            "default_branch_at_seed": "main",
            "root_commit_sha": "d" * 40,
            "root_tree_sha": "a" * 40,
        }

    # A later segment can re-attest identity, but must not fetch a later branch
    # head or enqueue a second root tree even though nothing was expanded yet.
    second = FakeTransport([])
    with r.RootStore(db) as store:
        canonical, repository_id = r._seed_or_attest(store=store, client=second, root=root())
        assert canonical == "live/name"
        assert repository_id == "7"
        assert second.responses == []
        pending = list(store.frontier.pending())
        assert len(pending) == 1
        assert pending[0].tree_sha == "a" * 40
        assert store.snapshot()["root_commit_sha"] == "d" * 40


def test_resume_identity_failure_after_seed_is_stopped_not_refused(tmp_path):
    db = tmp_path / "root.sqlite"
    first_commit = {"sha": "d" * 40, "commit": {"tree": {"sha": "a" * 40}}}
    with r.RootStore(db) as store:
        r._seed_or_attest(store=store, client=FakeTransport([first_commit]), root=root())
    with (
        r.RootStore(db) as store,
        pytest.raises(r.ResumeIdentityStopped),
    ):
        r._seed_or_attest(
            store=store,
            client=FakeTransport(identity_error=t.IdentityRefused("wrong id now")),
            root=root(),
        )


def test_short_roster_is_refused_before_census(tmp_path, monkeypatch):
    roster_path = tmp_path / "roster.json"
    body = {
        "schema": "tavonel.sfir10r1.cohort_roster.v1",
        "study_id": p.PROTOCOL_ID,
        "state": "SEALED_SHORT_ROSTER",
        "protocol_digest": p.Protocol().freeze().digest(),
        "entry_count": 49,
        "entries": [{"selection_ordinal": i, "host_uuid": str(i)} for i in range(1, 50)],
    }
    roster_path.write_text(json.dumps({**body, "roster_seal": r._digest(body)}), encoding="utf-8")
    monkeypatch.setattr(r, "ROSTER_RECEIPT", roster_path)
    with pytest.raises(r.RunnerRefused, match="short cohort"):
        r.verify_roster()


def test_unsealed_active_segment_becomes_terminal_unproven(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    segments = runtime / "segments"
    state_file = runtime / "state.json"
    active = runtime / "active-segment.json"
    terminal = tmp_path / "terminal.json"
    monkeypatch.setattr(r, "RUNTIME", runtime)
    monkeypatch.setattr(r, "SEGMENTS_DIR", segments)
    monkeypatch.setattr(r, "STATE_FILE", state_file)
    monkeypatch.setattr(r, "ACTIVE_SEGMENT_FILE", active)
    monkeypatch.setattr(r, "TERMINAL_UNPROVEN", terminal)
    state = {
        "protocol_digest": "p",
        "freeze_digest": "f",
        "roster_seal": "r",
        "windows_used": 0,
        "current_ordinal": 1,
        "root_states": {"1": r.ACTIVE},
        "root_provider_charges": {"1": 0},
        "segment_chain_head": "GENESIS",
        "measurement_unproven": False,
    }
    runtime.mkdir(parents=True)
    r._write_active_segment(state=state, segment_index=1)
    result = r._recover_closed_active_segment(state)
    assert result is not None
    assert result["what_this_means"] == "no PASS or FAIL may be sealed from this cohort"
    assert terminal.is_file()


def test_active_marker_recovers_only_from_complete_sealed_segment(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    segments = runtime / "segments"
    state_file = runtime / "state.json"
    active = runtime / "active-segment.json"
    terminal = tmp_path / "terminal.json"
    monkeypatch.setattr(r, "RUNTIME", runtime)
    monkeypatch.setattr(r, "SEGMENTS_DIR", segments)
    monkeypatch.setattr(r, "STATE_FILE", state_file)
    monkeypatch.setattr(r, "ACTIVE_SEGMENT_FILE", active)
    monkeypatch.setattr(r, "TERMINAL_UNPROVEN", terminal)
    state = {
        "protocol_digest": "p",
        "freeze_digest": "f",
        "roster_seal": "r",
        "windows_used": 0,
        "current_ordinal": 1,
        "root_states": {"1": r.ACTIVE},
        "root_provider_charges": {"1": 0},
        "segment_chain_head": "GENESIS",
        "measurement_unproven": False,
    }
    runtime.mkdir(parents=True)
    segments.mkdir(parents=True)
    r._write_active_segment(state=state, segment_index=1)
    segment_body = {
        "schema": "tavonel.sfir10r1.segment.v1",
        "study_id": p.PROTOCOL_ID,
        "segment_index": 1,
        "protocol_digest": "p",
        "freeze_digest": "f",
        "roster_seal": "r",
        "previous_segment_digest": "GENESIS",
        "stop_reason": "SEGMENT_COMPLETE_RATE_WINDOW",
        "window": {},
        "transport": {},
        "provider_reconciliation": {
            "accounting_is_complete": True,
            "unattributed_provider_accounting_delta": 0,
        },
        "operational_state": {
            "windows_used": 1,
            "current_ordinal": 2,
            "root_states": {"1": r.EXHAUSTED},
            "root_provider_charges": {"1": 12},
        },
        "scientific_counts_disclosed": False,
    }
    segment = {**segment_body, "segment_digest": r._digest(segment_body)}
    (segments / "segment-01.json").write_text(json.dumps(segment), encoding="utf-8")
    result = r._recover_closed_active_segment(state)
    assert result["status"] == "RECOVERED_ALREADY_SEALED_SEGMENT"
    saved = json.loads(state_file.read_text(encoding="utf-8"))
    assert saved["windows_used"] == 1
    assert saved["root_provider_charges"] == {"1": 12}
    assert saved["segment_chain_head"] == segment["segment_digest"]
    assert not active.exists()
    assert not terminal.exists()
