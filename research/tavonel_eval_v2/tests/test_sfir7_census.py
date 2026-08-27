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
