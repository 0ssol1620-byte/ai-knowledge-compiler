"""Controls for SFIR7's census loop and its candidate builder.

The load-bearing one is equivalence. `probe4._candidate` refuses every SFIR7
repository, so a second builder had to be written, and a second builder that is
*almost* the first produces lineage ids that look entirely right and are not the
ones SFIR4's science defines. Nothing downstream would catch that -- the ids are
well-formed, unique and stable; they are simply different.

So `sfir7_candidate` is checked against `probe4._candidate` over a repository
both accept, field for field.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import probe_sfir4_capacity as probe4  # noqa: E402
import probe_sfir7_capacity as probe7  # noqa: E402
import sfir7_roots as roots  # noqa: E402
from acquisition import sources_sfir4 as sources  # noqa: E402

#: A repository SFIR4 froze, so both builders accept it and can be compared.
SHARED = sources.SOURCE_POOLS["git_docs"]["repositories"][0]


def _item(repository: str = SHARED, **overrides):
    item = {
        "repository": repository,
        "path": "docs/index.md",
        "commit_before": "a" * 40,
        "commit_after": "b" * 40,
        "timestamp_before": "2020-01-01T00:00:00Z",
        "timestamp_after": "2021-01-01T00:00:00Z",
    }
    item.update(overrides)
    return item


def _pool(*repositories: str):
    return {
        "repositories": repositories or (SHARED,),
        "extensions": (".md",),
        "max_candidates_per_repository": 80,
        "max_total_candidates": 4000,
    }


# --- the equivalence that licenses a second builder --------------------------


def test_the_candidate_builder_agrees_with_sfir4_for_a_shared_repository():
    """Field for field, including the salted capability draw.

    If these diverge, SFIR7's lineage ids are not the ones SFIR4's science
    defines, and every count built on them describes a different study.
    """
    item = _item()
    theirs = probe4._candidate("git_docs", item)
    ours = probe7.sfir7_candidate(item, _pool())
    assert theirs is not None and ours is not None
    assert ours[0] == theirs[0]
    assert ours[1] == theirs[1]


def test_the_equivalence_covers_the_capability_draw_and_not_just_the_ids():
    """The draw is a salted hash of the lineage; a builder that got the lineage
    right and the salt wrong would still pass a check on ids alone.
    """
    for path in ("a.md", "deeply/nested/guide.rst", "README.mdx"):
        item = _item(path=path)
        theirs = probe4._candidate("git_docs", item)[0]
        ours = probe7.sfir7_candidate(item, _pool())[0]
        assert ours["capability_exercise"] == theirs["capability_exercise"]
        assert ours["lineage_id"] == theirs["lineage_id"]
        assert ours["payload_ref"] == theirs["payload_ref"]


def test_sfir4s_builder_really_would_refuse_an_sfir7_root():
    """The reason a second builder exists. If this stops being true, delete one."""
    outsider = roots.declared_roots()[0]
    assert outsider not in sources.SOURCE_POOLS["git_docs"]["repositories"]
    with pytest.raises(probe4.protocol.SFIR4Refused, match="escaped frozen roots"):
        probe4._candidate("git_docs", _item(repository=outsider))


def test_the_sfir7_builder_accepts_an_sfir7_root():
    outsider = roots.declared_roots()[0]
    row, aliases = probe7.sfir7_candidate(_item(repository=outsider), _pool(outsider))
    assert row["lineage_id"] == f"git:{outsider}:docs/index.md"
    assert aliases == set()


# --- the builder's own refusals ----------------------------------------------


def test_a_repository_outside_the_supplied_pool_is_refused():
    with pytest.raises(probe7.SFIR7CensusRefused, match="escaped SFIR7"):
        probe7.sfir7_candidate(_item(repository="attacker/repo"), _pool())


def test_an_unchanged_document_is_dropped_rather_than_counted():
    """Same commit before and after is not a revision pair."""
    assert probe7.sfir7_candidate(_item(commit_after="a" * 40), _pool()) is None


def test_a_backwards_chronology_is_dropped():
    assert (
        probe7.sfir7_candidate(
            _item(timestamp_after="2019-01-01T00:00:00Z"), _pool()
        )
        is None
    )


def test_a_malformed_revision_pair_is_refused_rather_than_guessed():
    with pytest.raises(probe4.protocol.SFIR4Refused, match="revision pair malformed"):
        probe7.sfir7_candidate(_item(commit_before=""), _pool())


def test_a_non_string_path_is_refused():
    with pytest.raises(probe7.SFIR7CensusRefused, match="escaped SFIR7"):
        probe7.sfir7_candidate(_item(path=None), _pool())


# --- the loop's own guards, driven rather than described ---------------------


class _Recorder:
    """A transport stub that answers from a script, so the loop can be driven."""

    def __init__(self, script, global_count=0):
        self._script = script
        self.calls = []
        self._global_git_request_count = global_count
        self.ledger = None

    def __call__(self, family, request):
        self.calls.append(request["repository"])
        outcome = self._script[request["repository"]]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def identity_attestation(self):
        return {"rename_count": 0, "roots_attested": len(self.calls)}


def _complete(repository, expected, items=()):
    return {
        "items": list(items),
        "metadata_only": True,
        "snapshot_id": f"github:{repository}:head:{'c' * 40}",
        "response_refs": [f"https://api.github.com/repos/{repository}"],
        "rate_limited": False,
        "root_disposition": {
            "discovery_root_id": expected,
            "state": "COMPLETE",
            "reason": "NONRECURSIVE_TREE_BFS_QUEUE_EXHAUSTED",
            "traversal_proof": {"algorithm": "IMMUTABLE_NONRECURSIVE_TREE_BFS"},
        },
    }


def test_the_census_refuses_to_run_under_a_test_harness():
    """The live-cohort guard. A census that can run inside pytest can spend a
    corpus from a test run nobody meant to be live.
    """
    import live_cohort_guard

    with pytest.raises(live_cohort_guard.LiveCohortRefused):
        probe7.census(NS, {"path": "x", "sha256": "y"}, NS / "nowhere.json", _Recorder({}))


def test_a_bound_exclusion_is_not_a_zero_candidate_root():
    """The distinction INC-V2-115 turns on, on the disposition the loop builds.

    A budget exhausted and a tree that held nothing are different observations.
    Reporting the first as the second would turn an accounting event into a
    finding about content -- and it would understate capacity in a way that looks
    like a measurement.
    """
    transport = _Recorder({}, global_count=4800)
    disposition = probe7.bound_excluded_disposition(
        "git:owner/name", "owner/name", transport
    )
    assert disposition["state"] == "EXCLUDED_INCOMPLETE_ROOT_DISPOSITION"
    assert disposition["state"] != "ZERO_CANDIDATE_ROOT_DISPOSITION"
    assert disposition["reason"] == "GLOBAL_GIT_REQUEST_BOUND"
    assert disposition["response_refs"] == []
    assert disposition["traversal_proof"]["api_requests"] == 0


def test_a_bound_exclusion_reports_the_bound_it_hit_and_where_it_hit_it():
    """Without the counter and the bound, a reader cannot tell a census cut at
    root 21 from one cut at root 49.
    """
    transport = _Recorder({}, global_count=4800)
    proof = probe7.bound_excluded_disposition("git:o/n", "o/n", transport)["traversal_proof"]
    assert proof["bound"] == sources.MAX_GIT_API_REQUESTS_GLOBAL
    assert proof["global_api_requests"] == 4800


def test_a_bound_exclusion_carries_no_snapshot_evidence_it_did_not_obtain():
    """A root that was never fetched has no head sha, and inventing one to fill
    the field would be fabricating evidence to satisfy a schema.
    """
    disposition = probe7.bound_excluded_disposition("git:o/n", "o/n", _Recorder({}))
    assert disposition["snapshot_ref"].endswith(":not-reached")
    assert "head:" not in disposition["snapshot_ref"]


def test_every_disposition_state_the_loop_accepts_is_one_sfir4_defines():
    """A state SFIR4 does not know is a state its seal will refuse."""
    assert {
        "COMPLETE",
        "EXCLUDED_INCOMPLETE_ROOT_DISPOSITION",
        "UNAVAILABLE_ROOT_DISPOSITION",
        "ZERO_CANDIDATE_ROOT_DISPOSITION",
    } == probe7.VALID_STATES


# --- the structural checks on a transport answer -----------------------------

EXPECTED = "git:owner/name"


def _response(**overrides):
    body = {
        "items": [],
        "root_disposition": {
            "discovery_root_id": EXPECTED,
            "state": "COMPLETE",
            "reason": "NONRECURSIVE_TREE_BFS_QUEUE_EXHAUSTED",
        },
    }
    body.update(overrides)
    return body


def test_a_well_formed_answer_passes():
    """So the refusals below mean something."""
    disposition, items = probe7.require_well_formed_response(_response(), EXPECTED)
    assert disposition["state"] == "COMPLETE"
    assert items == []


def test_an_answer_about_a_different_root_is_refused():
    """A response that arrived out of order, or for a root nobody asked about."""
    with pytest.raises(probe7.SFIR7CensusRefused, match="disposition malformed"):
        probe7.require_well_formed_response(_response(), "git:someone/else")


def test_a_missing_disposition_is_refused():
    with pytest.raises(probe7.SFIR7CensusRefused, match="disposition malformed"):
        probe7.require_well_formed_response({"items": []}, EXPECTED)


def test_a_state_sfir4_does_not_define_is_refused():
    """Its seal would refuse the census later; refusing here says why."""
    body = _response()
    body["root_disposition"]["state"] = "MOSTLY_COMPLETE"
    with pytest.raises(probe7.SFIR7CensusRefused, match="is not one SFIR4 defines"):
        probe7.require_well_formed_response(body, EXPECTED)


def test_an_incomplete_root_that_emitted_candidates_is_refused():
    """A partial traversal reporting rows presents part of a tree as the whole
    of it. That is the shape of every quietly undercounted corpus.
    """
    body = _response(items=[{"repository": "owner/name", "path": "a.md"}])
    body["root_disposition"]["state"] = "EXCLUDED_INCOMPLETE_ROOT_DISPOSITION"
    with pytest.raises(probe7.SFIR7CensusRefused, match="incomplete root emitted"):
        probe7.require_well_formed_response(body, EXPECTED)


def test_an_incomplete_root_with_no_candidates_is_accepted():
    """The normal case for a bound-excluded or unavailable root."""
    body = _response()
    body["root_disposition"]["state"] = "UNAVAILABLE_ROOT_DISPOSITION"
    _, items = probe7.require_well_formed_response(body, EXPECTED)
    assert items == []


def test_items_that_are_not_a_list_are_refused():
    with pytest.raises(probe7.SFIR7CensusRefused, match="incomplete root emitted"):
        probe7.require_well_formed_response(_response(items={"a": 1}), EXPECTED)


# --- cheap before expensive (INC-V2-117) -------------------------------------


def test_the_receipt_can_be_assembled_and_written_before_anything_is_spent(tmp_path):
    """The control the first live run did not have.

    That run traversed every frozen root, spent the whole request budget, and
    died on the last statement of the census: `import evidence` had bound a
    module of that name in `tools/` rather than `sfir4_response_evidence`, so
    `evidence.ResponseLedger` did not exist. The measurements were lost to a
    name collision in code nothing had ever executed.
    """
    probe7.preflight_receipt_path(tmp_path / "census.json")


def test_the_preflight_uses_the_real_assembly_and_the_real_writer(tmp_path, monkeypatch):
    """A preflight that exercised a stub would prove the stub works."""
    calls = []
    original = probe7.build_census_body
    monkeypatch.setattr(
        probe7, "build_census_body", lambda **kw: calls.append(kw) or original(**kw)
    )
    probe7.preflight_receipt_path(tmp_path / "census.json")
    assert len(calls) == 1
    assert calls[0]["declared"] == roots.declared_roots()


def test_a_receipt_path_that_cannot_be_written_is_found_before_any_request(tmp_path):
    """The whole point: a failure here costs one temporary file, and the same
    failure after the loop costs an entire census budget.
    """
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory", encoding="utf-8")
    with pytest.raises(OSError):
        probe7.preflight_receipt_path(blocked / "census.json")


def test_the_preflight_leaves_no_receipt_behind(tmp_path):
    """A census receipt written by a preflight would be a receipt for a run that
    never happened -- worse than no receipt at all.
    """
    destination = tmp_path / "census.json"
    probe7.preflight_receipt_path(destination)
    assert not destination.exists()
    assert list(tmp_path.iterdir()) == []


def test_the_response_evidence_module_is_the_one_that_has_a_ledger():
    """The name collision itself, asserted directly. `tools/evidence.py` exists
    and is a different module; binding it here is what cost the first run.
    """
    assert probe7.evidence.__name__ == "sfir4_response_evidence"
    assert hasattr(probe7.evidence, "ResponseLedger")
    import evidence as unrelated

    assert not hasattr(unrelated, "ResponseLedger")
    assert probe7.evidence is not unrelated


def test_the_census_and_the_probe_it_carries_use_the_same_ledger_type():
    """A census whose ledger type differs from the traversal's would silently
    write an empty proof for a run full of observations.
    """
    assert probe7.evidence.ResponseLedger is probe4.evidence.ResponseLedger


def test_the_preflight_writes_through_the_real_writer(monkeypatch, tmp_path):
    """A preflight that assembles a body and never writes it proves half of what
    is needed: the last thing that failed in the live run was the write path.
    """
    written = []
    monkeypatch.setattr(
        probe7.protocol, "write_immutable", lambda path, body: written.append((path, body)) or path
    )
    probe7.preflight_receipt_path(tmp_path / "census.json")
    assert len(written) == 1
    assert written[0][1]["schema"] == probe7.SCHEMA


def test_the_preflight_applies_the_metadata_only_assertion(monkeypatch, tmp_path):
    """The receipt must contain no payload. Checking that in the preflight is
    what makes the check part of the cheap step rather than the expensive one.
    """
    seen = []
    original = probe7.protocol._assert_metadata_only
    monkeypatch.setattr(
        probe7.protocol,
        "_assert_metadata_only",
        lambda body, path="": seen.append(body) or original(body, path) if path else
        (seen.append(body) or original(body)),
    )
    probe7.preflight_receipt_path(tmp_path / "census.json")
    assert seen, "the preflight did not assert metadata-only"


def test_the_census_runs_its_preflight_before_its_first_transport_call():
    """An ordering control, and deliberately a static one.

    `census` refuses to run under a test harness, so the position of a call
    inside it cannot be driven. Three times this session a guard's CALL SITE went
    untested while the guard itself was covered, and each time the deletion
    stayed green (INC-V2-113, twice in the census loop, and now on the repair for
    INC-V2-117 itself). Source inspection is weaker than execution and it is not
    nothing: deleting the call, or moving it after the loop, goes red.
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(probe7.census))
    calls = [
        (node.lineno, node.func.id)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    preflight = [line for line, name in calls if name == "preflight_receipt_path"]
    transport = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "transport"
    ]
    assert preflight, "census does not run the receipt preflight at all"
    assert transport, "census never calls the transport, so this control is vacuous"
    assert min(preflight) < min(transport), (
        "the receipt preflight runs after the first request. Its whole purpose is "
        "to fail before anything is spent."
    )


def test_the_ordering_control_would_notice_a_moved_call():
    """The control above compares two line numbers; if either list were empty it
    would pass by accident. Both are asserted non-empty, and this checks that the
    assertion is reachable rather than decorative.
    """
    import ast
    import inspect

    source = inspect.getsource(probe7.census)
    assert "preflight_receipt_path(destination)" in source
    assert source.index("preflight_receipt_path(destination)") < source.index("transport(FAMILY")
    tree = ast.parse(source)
    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "transport"
        for node in ast.walk(tree)
    )


# --- the operational precondition (INC-V2-118) -------------------------------


def _headroom(remaining: int, reset_epoch: int = 1_000_000) -> dict:
    return {
        "limit": 5000,
        "remaining": remaining,
        "used": 5000 - remaining,
        "reset_epoch": reset_epoch,
        "authenticated": True,
    }


def test_a_fresh_window_lets_the_census_start():
    """So the refusal below is not the only answer this can give."""
    probe7.require_rate_limit_headroom(_headroom(5000), now_epoch=0)
    probe7.require_rate_limit_headroom(
        _headroom(sources.MAX_GIT_API_REQUESTS_GLOBAL), now_epoch=0
    )


def test_a_partly_spent_window_refuses_before_anything_is_spent():
    """The second live run's failure, as a control.

    It began with roughly five hundred requests already in the window, met
    GitHub's wall around request 4,500, and was asked to wait out the hour --
    which exceeds SFIR4's frozen fail-safe, so the census refused and produced
    nothing.
    """
    with pytest.raises(probe7.SFIR7CensusRefused, match="requests remaining this window"):
        probe7.require_rate_limit_headroom(_headroom(4503), now_epoch=0)


def test_the_refusal_says_how_long_the_window_has_left():
    """A refusal that does not say when to retry makes the operator guess."""
    with pytest.raises(probe7.SFIR7CensusRefused, match="resets in 1053 seconds"):
        probe7.require_rate_limit_headroom(_headroom(0, reset_epoch=1053), now_epoch=0)


def test_the_threshold_is_the_inherited_bound_and_not_a_number_typed_here():
    """If SFIR4's global bound moves, this precondition moves with it."""
    boundary = sources.MAX_GIT_API_REQUESTS_GLOBAL
    probe7.require_rate_limit_headroom(_headroom(boundary), now_epoch=0)
    with pytest.raises(probe7.SFIR7CensusRefused):
        probe7.require_rate_limit_headroom(_headroom(boundary - 1), now_epoch=0)


def test_the_frozen_retry_fail_safe_is_not_widened_to_absorb_an_hour():
    """The forbidden repair. That bound stops a census idling indefinitely, and
    stretching it to fit an operational inconvenience would loosen a safety
    limit so a run could succeed.
    """
    assert sources.MAX_RATE_LIMIT_WAIT_SECONDS == 60
    assert sources.MAX_TOTAL_RATE_LIMIT_WAIT_SECONDS == 180


def test_the_census_checks_headroom_before_its_first_transport_call():
    """Ordering, statically, for the same reason as the receipt preflight."""
    import ast
    import inspect

    source = inspect.getsource(probe7.census)
    assert "require_rate_limit_headroom(" in source
    assert source.index("require_rate_limit_headroom(") < source.index("transport(FAMILY")
    tree = ast.parse(source)
    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "transport"
        for node in ast.walk(tree)
    )


def test_the_headroom_reading_costs_no_quota_and_is_recorded(monkeypatch):
    """The rate_limit endpoint is free, so asking is not itself a cost. What was
    observed at the start belongs in the receipt: a census that began with a
    partly-spent window is a different observation from one that began fresh.
    """
    import io

    payload = b'{"resources":{"core":{"limit":5000,"remaining":4999,"used":1,"reset":123}}}'

    class _Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    observed = probe7.observed_rate_limit_headroom(
        opener=lambda request, timeout=None: _Response(payload)
    )
    assert observed["remaining"] == 4999
    assert observed["reset_epoch"] == 123

    body = probe7.build_census_body(
        transport=type("E", (), {"ledger": None, "identity_attestation": lambda s: {}})(),
        declared=("a/b",),
        candidates={},
        dispositions=[],
        snapshots=[],
        response_refs=[],
        retries=0,
        transport_retries=0,
        total_wait_seconds=0,
        bound_excluded=0,
        externally_excluded=0,
        started=0.0,
        headroom=observed,
    )
    assert body["frame"]["rate_limit_headroom_at_start"]["remaining"] == 4999


# --- the host's budget, as distinct from ours (INC-V2-119) -------------------


def test_the_frozen_fail_safe_accepts_a_short_wait_and_refuses_a_long_one():
    """Unchanged, read live, and driving a different decision than before."""
    assert probe7._wait_is_within_the_fail_safe(30, 0) is True
    assert probe7._wait_is_within_the_fail_safe(60, 0) is True
    assert probe7._wait_is_within_the_fail_safe(61, 0) is False
    assert probe7._wait_is_within_the_fail_safe(2280, 0) is False


def test_the_cumulative_fail_safe_still_binds():
    """Three sixty-second waits are allowed; a fourth is not."""
    assert probe7._wait_is_within_the_fail_safe(60, 120) is True
    assert probe7._wait_is_within_the_fail_safe(60, 180) is False


def test_a_missing_or_nonsense_wait_is_not_within_the_fail_safe():
    for value in (None, "60", 0, -1, True):
        assert probe7._wait_is_within_the_fail_safe(value, 0) is False


def test_a_host_limited_root_is_excluded_rather_than_aborting_the_census():
    """The change INC-V2-119 makes, and the whole of it.

    Before, GitHub asking for a 38-minute wait raised and the census produced
    nothing at all. Now the remaining roots are excluded and whatever completed
    is recorded. The fail-safe is untouched: no wait is ever taken.
    """
    disposition = probe7.external_limit_disposition("git:o/n", "o/n", 2280)
    assert disposition["state"] == "EXCLUDED_INCOMPLETE_ROOT_DISPOSITION"
    assert disposition["reason"] == "EXTERNAL_RATE_LIMIT_EXHAUSTED"
    assert disposition["traversal_proof"]["host_requested_wait_seconds"] == 2280
    assert disposition["traversal_proof"]["frozen_fail_safe_seconds"] == 60


def test_the_two_kinds_of_exclusion_are_not_merged():
    """Ours firing and the host's firing are different events. A census that
    merged them would lose the only evidence of which budget actually binds --
    which is the open question INC-V2-115 and INC-V2-119 turn on.
    """
    ours = probe7.bound_excluded_disposition("git:o/n", "o/n", _Recorder({}))
    theirs = probe7.external_limit_disposition("git:o/n", "o/n", 2280)
    assert ours["reason"] != theirs["reason"]
    assert ours["reason"] == "GLOBAL_GIT_REQUEST_BOUND"
    assert theirs["reason"] == "EXTERNAL_RATE_LIMIT_EXHAUSTED"


def test_a_host_limited_root_invents_no_evidence():
    disposition = probe7.external_limit_disposition("git:o/n", "o/n", 2280)
    assert disposition["response_refs"] == []
    assert disposition["snapshot_ref"].endswith(":not-reached")
    assert disposition["traversal_proof"]["api_requests"] == 0


def test_the_census_reports_which_budget_bound_it():
    """A reader must be able to tell a census our cap trimmed from one the host
    refused to serve, without reading dispositions one by one.
    """
    def body(bound, external):
        return probe7.build_census_body(
            transport=type("E", (), {"ledger": None, "identity_attestation": lambda s: {}})(),
            declared=("a/b",), candidates={}, dispositions=[], snapshots=[],
            response_refs=[], retries=0, transport_retries=0, total_wait_seconds=0,
            bound_excluded=bound, externally_excluded=external, started=0.0,
        )["bound_exclusions"]

    assert body(5, 0)["which_budget_actually_bound"] == "ours"
    assert body(0, 5)["which_budget_actually_bound"] == "the host's"
    assert body(3, 5)["which_budget_actually_bound"] == "both"
    assert body(0, 0)["which_budget_actually_bound"] == "neither"


def test_the_census_stops_asking_once_the_host_has_refused():
    """Continuing to request roots after the host says stop would spend requests
    to be told the same thing, and every one of them counts against the window
    that has to reset before anything can run again.
    """
    import inspect

    source = inspect.getsource(probe7.census)
    assert "for name in declared[index:]" in source
    assert "if externally_excluded:\n            break" in source
