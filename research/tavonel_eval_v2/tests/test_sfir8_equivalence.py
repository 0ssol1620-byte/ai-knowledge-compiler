"""Section J: the two equivalences that must hold before SFIR9 can freeze.

**J1 -- uninterrupted traversal == segmented/resumed traversal.** Candidate
identities, candidate order, root dispositions, the visited identity set and
frontier exhaustion must all be identical. Network request counts need not be:
a segment interrupted mid-root re-issues the tree request it was inside, so the
transport trace legitimately differs. Treating that difference as a failure
would be as wrong as ignoring a real one, so the two are compared separately and
never conflated.

**J2 -- old address followed through a verified redirect == canonical current
address.** For one numeric repository id the final candidate lineage set and the
revision metadata behind it must be identical. Addressing a repository by the
name it has today rather than the name the 2020 catalogue recorded saves
requests; that saving is an efficiency finding and must not move the scientific
population by a single candidate.

The fixture host below is deterministic and offline. These properties are about
the instrument, not about GitHub, and a control that needs the network to run is
a control that will be skipped.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import sfir8_checkpoint as cp  # noqa: E402
import sfir8_frontier as frontier_module  # noqa: E402
import sfir8_transport as transport  # noqa: E402
import sfir8_traversal as traversal  # noqa: E402

EXTENSIONS = (".py", ".md")


# ------------------------------------------------------------- a fixture host


TREES = {
    "t-root": [
        {"path": "README.md", "type": "blob", "sha": "b-readme"},
        {"path": "src", "type": "tree", "sha": "t-src"},
        {"path": "docs", "type": "tree", "sha": "t-docs"},
        {"path": "LICENSE", "type": "blob", "sha": "b-licence"},
    ],
    "t-src": [
        {"path": "a.py", "type": "blob", "sha": "b-a"},
        {"path": "deep", "type": "tree", "sha": "t-deep"},
        {"path": "b.py", "type": "blob", "sha": "b-b"},
    ],
    "t-docs": [
        {"path": "guide.md", "type": "blob", "sha": "b-guide"},
        {"path": "image.png", "type": "blob", "sha": "b-image"},
    ],
    "t-deep": [
        {"path": "c.py", "type": "blob", "sha": "b-c"},
        {"path": "shared", "type": "tree", "sha": "t-src"},
    ],
}

CANONICAL = "acme/widget"
OLD_ADDRESS = "oldorg/widget"
NUMERIC_ID = 4242


class _Headers(dict):
    def get(self, name, default=None):
        for key, value in self.items():
            if key.casefold() == name.casefold():
                return value
        return default


class _Response(io.BytesIO):
    def __init__(self, status, headers, body):
        super().__init__(body)
        self.status = status
        self.headers = _Headers(headers)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


class FixtureHost:
    """A tiny deterministic GitHub: one repository, reachable by two names."""

    def __init__(self):
        self.remaining = 5000
        self.requests: list[str] = []

    def open(self, request, timeout=None):
        url = request.full_url
        self.requests.append(url)
        self.remaining -= 1
        headers = {"x-ratelimit-remaining": str(self.remaining)}

        if url.startswith(f"https://api.github.com/repos/{OLD_ADDRESS}"):
            moved = url.replace(OLD_ADDRESS, CANONICAL, 1)
            return _Response(301, {**headers, "Location": moved}, b"")

        prefix = f"https://api.github.com/repos/{CANONICAL}"
        if url == prefix:
            return self._json(
                headers,
                {"id": NUMERIC_ID, "full_name": CANONICAL, "default_branch": "main"},
            )
        if url == f"{prefix}/commits/main":
            return self._json(
                headers, {"commit": {"tree": {"sha": "t-root"}}, "sha": "c-head"}
            )
        if url.startswith(f"{prefix}/git/trees/"):
            sha = url.rsplit("/", 1)[-1]
            if sha in TREES:
                return self._json(headers, {"sha": sha, "tree": TREES[sha]})
        return _Response(404, headers, b"{}")

    @staticmethod
    def _json(headers, payload):
        return _Response(200, headers, json.dumps(payload).encode("utf-8"))


@pytest.fixture
def host(monkeypatch):
    server = FixtureHost()
    monkeypatch.setattr(transport.urllib.request, "build_opener", lambda *a: server)
    return server


def roots(address=CANONICAL):
    return [{"root_id": "widget", "address": address, "host_uuid": str(NUMERIC_ID)}]


def traverse(db, *, address=CANONICAL, budget=None):
    client = transport.ManualRedirectTransport()
    client.seed_remaining(5000)
    with traversal.Traversal(
        database=db, transport=client, roots=roots(address), extensions=EXTENSIONS
    ) as run:
        return run.run(request_budget=budget), client


# ------------------------------------------------------------- the fixture works


def test_the_fixture_traversal_finds_what_it_should(tmp_path, host):
    result, _ = traverse(tmp_path / "a.sqlite3")
    assert result.frontier_exhausted is True
    assert result.dispositions == {"widget": traversal.COMPLETE}
    assert [c.path for c in result.candidates] == [
        "README.md",
        "src/a.py",
        "src/b.py",
        "docs/guide.md",
        "src/deep/c.py",
    ]


def test_a_tree_reached_twice_is_expanded_once(tmp_path, host):
    """`t-deep/shared` points back at `t-src`. One subtree, counted once."""
    result, _ = traverse(tmp_path / "a.sqlite3")
    assert sorted(sha for _, sha in result.visited) == [
        "t-deep",
        "t-docs",
        "t-root",
        "t-src",
    ]
    assert len([c for c in result.candidates if c.path == "src/a.py"]) == 1


def test_files_outside_the_declared_extensions_are_not_candidates(tmp_path, host):
    result, _ = traverse(tmp_path / "a.sqlite3")
    paths = {c.path for c in result.candidates}
    assert "LICENSE" not in paths
    assert "docs/image.png" not in paths


# ------------------------------------------------- J1: segmented == uninterrupted


def _segmented(db, *, budget_per_segment):
    """Run to exhaustion in slices, rebuilding everything between segments.

    A fresh transport and a fresh Traversal each time is the point: if any state
    that matters lives only in memory, this is where it disappears.
    """
    chain = cp.SegmentChain(study_id="SFIR8-DEV", roster_digest=cp.GENESIS)
    clients = []
    for index in range(20):
        client = transport.ManualRedirectTransport()
        client.seed_remaining(5000)
        clients.append(client)
        with traversal.Traversal(
            database=db, transport=client, roots=roots(), extensions=EXTENSIONS
        ) as run:
            if chain.segments:
                run.resume(chain.segments[-1])
            result = run.run(request_budget=budget_per_segment)
            if result.frontier_exhausted:
                return result, clients, chain
            chain.append(run.checkpoint(index, chain.head))
    raise AssertionError("segmented traversal did not converge")


@pytest.mark.parametrize("budget", [3, 4, 5, 8])
def test_j1_segmentation_does_not_change_the_scientific_result(tmp_path, host, budget):
    """The equivalence itself, at four different interruption granularities."""
    straight, _ = traverse(tmp_path / "straight.sqlite3")
    segmented, _, _ = _segmented(tmp_path / "segmented.sqlite3", budget_per_segment=budget)

    assert segmented.scientific_identity() == straight.scientific_identity()
    assert segmented.scientific_digest() == straight.scientific_digest()


def test_j1_candidate_order_is_part_of_the_equivalence(tmp_path, host):
    """Not merely the same set. A different order is a different traversal."""
    straight, _ = traverse(tmp_path / "straight.sqlite3")
    segmented, _, _ = _segmented(tmp_path / "segmented.sqlite3", budget_per_segment=3)
    assert [c.path for c in segmented.candidates] == [c.path for c in straight.candidates]
    assert [c.discovery_sequence for c in segmented.candidates] == [
        c.discovery_sequence for c in straight.candidates
    ]


def test_j1_the_transport_trace_is_allowed_to_differ(tmp_path, host):
    """And the suite has to say so, or someone will later "fix" it.

    A segment that stops mid-root re-issues the tree request it was inside, so a
    finely-sliced run costs more requests than an uninterrupted one. That is a
    property of segmentation, not a defect, and it is precisely why request
    counts are excluded from the scientific identity.
    """
    _, straight_client = traverse(tmp_path / "straight.sqlite3")
    _, clients, _ = _segmented(tmp_path / "segmented.sqlite3", budget_per_segment=3)
    segmented_requests = sum(c.totals()["logical_requests"] for c in clients)

    assert segmented_requests > straight_client.totals()["logical_requests"]
    assert "logical_requests" not in json.dumps(
        traverse(tmp_path / "c.sqlite3")[0].scientific_identity()
    )


def test_j1_the_segment_chain_links_and_carries_the_state(tmp_path, host):
    _, _, chain = _segmented(tmp_path / "segmented.sqlite3", budget_per_segment=3)
    assert len(chain.segments) >= 2
    receipt = chain.receipt()
    assert receipt["segment_chain_head"] == chain.head
    assert set(receipt["dispositions"]) == {cp.RATE_WINDOW_CLOSE}


def test_j1_a_mid_root_checkpoint_names_the_root_it_is_inside(tmp_path, host):
    """Section F. Checkpointing only between roots lets one repository eat a
    whole window and then restart from nothing."""
    _, _, chain = _segmented(tmp_path / "segmented.sqlite3", budget_per_segment=3)
    inside = [s for s in chain.segments if s.next_action == "CONTINUE_ROOT"]
    assert inside, "no checkpoint was taken mid-root"
    assert inside[0].current_root_id == "widget"
    assert inside[0].current_repository_numeric_id == str(NUMERIC_ID)


def test_j1_resuming_does_not_duplicate_a_candidate(tmp_path, host):
    """The re-issued request offers candidates already held. They are not new."""
    segmented, _, _ = _segmented(tmp_path / "segmented.sqlite3", budget_per_segment=3)
    identities = [c.identity() for c in segmented.candidates]
    assert len(identities) == len(set(identities))


def test_j1_resuming_does_not_lose_a_candidate(tmp_path, host):
    straight, _ = traverse(tmp_path / "straight.sqlite3")
    segmented, _, _ = _segmented(tmp_path / "segmented.sqlite3", budget_per_segment=3)
    assert {c.identity() for c in segmented.candidates} == {
        c.identity() for c in straight.candidates
    }


# --------------------------------- J2: canonical address == redirect-followed one


def test_j2_addressing_by_either_name_yields_the_same_population(tmp_path, host):
    """One numeric identity, two addresses, one candidate lineage set."""
    canonical, canonical_client = traverse(
        tmp_path / "canonical.sqlite3", address=CANONICAL
    )
    followed, followed_client = traverse(tmp_path / "followed.sqlite3", address=OLD_ADDRESS)

    assert {c.identity() for c in followed.candidates} == {
        c.identity() for c in canonical.candidates
    }
    assert [c.path for c in followed.candidates] == [c.path for c in canonical.candidates]
    assert followed.dispositions == canonical.dispositions
    assert followed.scientific_digest() == canonical.scientific_digest()
    assert canonical_client is not followed_client


def test_j2_both_routes_resolve_to_the_same_numeric_identity(tmp_path, host):
    """The equality above would be worthless if they were different repositories."""
    canonical, _ = traverse(tmp_path / "canonical.sqlite3", address=CANONICAL)
    followed, _ = traverse(tmp_path / "followed.sqlite3", address=OLD_ADDRESS)
    assert {c.repository_numeric_id for c in canonical.candidates} == {str(NUMERIC_ID)}
    assert {c.repository_numeric_id for c in followed.candidates} == {str(NUMERIC_ID)}


def test_j2_the_saving_is_an_efficiency_finding_and_nothing_more(tmp_path, host):
    """The old address costs a hop per request. That is all it costs."""
    canonical, canonical_client = traverse(
        tmp_path / "canonical.sqlite3", address=CANONICAL
    )
    followed, followed_client = traverse(tmp_path / "followed.sqlite3", address=OLD_ADDRESS)

    canonical_totals = canonical_client.totals()
    followed_totals = followed_client.totals()
    assert followed_totals["logical_requests"] == canonical_totals["logical_requests"]
    assert followed_totals["network_hops"] > canonical_totals["network_hops"]
    assert followed.scientific_identity() == canonical.scientific_identity(), (
        "the redirect changed the cost and must not have changed the population"
    )


def test_j2_the_revision_the_candidates_came_from_is_the_same(tmp_path, host):
    """Same head, same tree, or the two runs measured different revisions."""
    canonical, _ = traverse(tmp_path / "canonical.sqlite3", address=CANONICAL)
    followed, _ = traverse(tmp_path / "followed.sqlite3", address=OLD_ADDRESS)
    assert sorted(sha for _, sha in followed.visited) == sorted(
        sha for _, sha in canonical.visited
    )
    assert {c.blob_sha for c in followed.candidates} == {
        c.blob_sha for c in canonical.candidates
    }


def test_j2_a_redirect_to_a_different_repository_is_refused_not_traversed(
    tmp_path, monkeypatch
):
    """The hostile case. A moved address that now serves someone else's
    repository must produce no candidates at all, not a plausible population."""
    server = FixtureHost()
    original = server.open

    def impostor(request, timeout=None):
        response = original(request, timeout)
        if request.full_url == f"https://api.github.com/repos/{CANONICAL}":
            return _Response(
                200,
                {"x-ratelimit-remaining": str(server.remaining)},
                json.dumps(
                    {"id": 999999, "full_name": CANONICAL, "default_branch": "main"}
                ).encode(),
            )
        return response

    monkeypatch.setattr(server, "open", impostor)
    monkeypatch.setattr(transport.urllib.request, "build_opener", lambda *a: server)

    result, _ = traverse(tmp_path / "impostor.sqlite3", address=OLD_ADDRESS)
    assert result.candidates == []
    assert result.dispositions == {"widget": traversal.IDENTITY_REFUSED}


def test_j2_an_unresolvable_root_is_recorded_as_not_measured(tmp_path, monkeypatch):
    server = FixtureHost()
    monkeypatch.setattr(
        server, "open", lambda request, timeout=None: _Response(404, {}, b"{}")
    )
    monkeypatch.setattr(transport.urllib.request, "build_opener", lambda *a: server)

    result, _ = traverse(tmp_path / "gone.sqlite3")
    assert result.dispositions == {"widget": traversal.IDENTITY_REFUSED}
    assert result.candidates == []


# ------------------------------------------------- the two layers stay separate


def test_the_scientific_identity_contains_no_request_counter(tmp_path, host):
    result, _ = traverse(tmp_path / "a.sqlite3")
    serialized = json.dumps(result.scientific_identity())
    for counter in ("logical", "hop", "charge", "provider", "request"):
        assert counter not in serialized


def test_the_transport_totals_are_still_reported(tmp_path, host):
    """Excluded from the equivalence is not the same as hidden."""
    result, _ = traverse(tmp_path / "a.sqlite3")
    assert result.transport_totals["logical_requests"] > 0
    assert result.transport_totals["provider_charged"] > 0


# ------------------------------------------- a budget too small to make progress


def test_a_segment_budget_below_the_fixed_overhead_is_refused(tmp_path, host):
    """Found by the J1 controls at a budget of one, where the chain spun.

    A segment that can pay for its own attestation and nothing else expands no
    tree object. Twenty such segments expand twenty times nothing. Refusing is
    the only honest answer -- looping is a hang, and silently rounding the budget
    up would spend more of the provider's window than the caller authorised.
    """
    client = transport.ManualRedirectTransport()
    client.seed_remaining(5000)
    with traversal.Traversal(
        database=tmp_path / "tiny.sqlite3",
        transport=client,
        roots=roots(),
        extensions=EXTENSIONS,
    ) as run, pytest.raises(traversal.TraversalRefused, match="cannot cover"):
        run.run(request_budget=1)
    assert client.totals()["logical_requests"] == 0, (
        "the refusal must come before any request is issued, so it costs nothing"
    )


def test_the_minimum_budget_is_derived_from_the_declared_overhead():
    """Not a hand-picked constant. Opening a root is two requests; one
    expansion is one more."""
    assert traversal.MINIMUM_SEGMENT_REQUEST_BUDGET == (
        traversal.OPEN_ROOT_REQUEST_COST + 1
    )


def test_the_declared_open_cost_is_what_opening_a_root_actually_costs(tmp_path, host):
    """Measured, not asserted.

    Mutation T20 changed the declared cost and survived: the minimum budget is
    derived from it, so the derivation still held and nothing compared the
    declaration against reality. A constant that describes behaviour has to be
    checked against the behaviour, or it is a comment with a type.
    """
    client = transport.ManualRedirectTransport()
    client.seed_remaining(5000)
    with traversal.Traversal(
        database=tmp_path / "open.sqlite3", transport=client, roots=roots(),
        extensions=EXTENSIONS,
    ) as run:
        assert run._open_root(roots()[0]) is True

    assert client.totals()["logical_requests"] == traversal.OPEN_ROOT_REQUEST_COST, (
        "opening a root cost a different number of logical requests than the "
        "constant the segment budget is derived from"
    )


def test_resuming_re_attests_identity_rather_than_trusting_the_checkpoint(
    tmp_path, host, monkeypatch
):
    """A window can be an hour wide and a repository can move inside it."""
    chain = cp.SegmentChain(study_id="SFIR8-DEV", roster_digest=cp.GENESIS)
    client = transport.ManualRedirectTransport()
    client.seed_remaining(5000)
    with traversal.Traversal(
        database=tmp_path / "seg.sqlite3", transport=client, roots=roots(),
        extensions=EXTENSIONS,
    ) as run:
        run.run(request_budget=3)
        chain.append(run.checkpoint(0, chain.head))

    def impostor(request, timeout=None):
        return _Response(
            200,
            {"x-ratelimit-remaining": "4000"},
            json.dumps(
                {"id": 999999, "full_name": CANONICAL, "default_branch": "main"}
            ).encode(),
        )

    monkeypatch.setattr(host, "open", impostor)
    resumed = transport.ManualRedirectTransport()
    resumed.seed_remaining(4000)
    with traversal.Traversal(
        database=tmp_path / "seg.sqlite3", transport=resumed, roots=roots(),
        extensions=EXTENSIONS,
    ) as run, pytest.raises(traversal.TraversalRefused, match="not resumed"):
        run.resume(chain.segments[-1])


def test_resuming_into_a_root_not_on_the_roster_is_refused(tmp_path, host):
    chain = cp.SegmentChain(study_id="SFIR8-DEV", roster_digest=cp.GENESIS)
    client = transport.ManualRedirectTransport()
    client.seed_remaining(5000)
    with traversal.Traversal(
        database=tmp_path / "seg.sqlite3", transport=client, roots=roots(),
        extensions=EXTENSIONS,
    ) as run:
        run.run(request_budget=3)
        checkpoint = run.checkpoint(0, chain.head)

    stranger = cp.Checkpoint(
        **{**checkpoint.as_dict(), "current_root_id": "somebody-elses-repo"}
    )
    with traversal.Traversal(
        database=tmp_path / "seg.sqlite3",
        transport=transport.ManualRedirectTransport(),
        roots=roots(),
        extensions=EXTENSIONS,
    ) as run, pytest.raises(traversal.TraversalRefused, match="not on this roster"):
        run.resume(stranger)


# ============================================================================
# The equivalence relation itself
#
# Everything above compares two runs through `scientific_identity()`. That can
# never detect the function dropping a field, because the field disappears from
# both sides and the equality still holds -- mutations T1 through T5 deleted
# candidate order, dispositions, the visited set and frontier exhaustion, one at
# a time, and every equivalence control stayed green.
#
# A self-comparison cannot validate the relation it compares with. So the
# relation is pinned two ways: against explicit expected content, and against
# runs that genuinely differ and must therefore NOT compare equal.
# ============================================================================


def test_the_scientific_identity_has_exactly_the_declared_fields(tmp_path, host):
    """Named explicitly, so removing one fails rather than silently narrowing."""
    result, _ = traverse(tmp_path / "a.sqlite3")
    assert set(result.scientific_identity()) == {
        "candidate_identities",
        "candidate_order",
        "root_dispositions",
        "visited_identity_set",
        "frontier_exhausted",
    }


def test_the_scientific_identity_holds_the_expected_content(tmp_path, host):
    """A golden assertion. Two runs agreeing proves nothing about what they agree on."""
    identity = traverse(tmp_path / "a.sqlite3")[0].scientific_identity()

    assert identity["candidate_identities"] == [
        [str(NUMERIC_ID), "README.md", "b-readme"],
        [str(NUMERIC_ID), "src/a.py", "b-a"],
        [str(NUMERIC_ID), "src/b.py", "b-b"],
        [str(NUMERIC_ID), "docs/guide.md", "b-guide"],
        [str(NUMERIC_ID), "src/deep/c.py", "b-c"],
    ]
    assert identity["candidate_order"] == [1, 2, 3, 4, 5]
    assert identity["root_dispositions"] == {"widget": traversal.COMPLETE}
    assert identity["visited_identity_set"] == [
        ["widget", "t-deep"],
        ["widget", "t-docs"],
        ["widget", "t-root"],
        ["widget", "t-src"],
    ]
    assert identity["frontier_exhausted"] is True


def _result_with(**overrides):
    """A Result built by hand, so each field can be varied on its own."""
    base = dict(
        candidates=[
            traversal.Candidate(
                root_id="widget",
                repository_numeric_id=str(NUMERIC_ID),
                path="a.py",
                blob_sha="b-a",
                discovery_sequence=1,
            ),
            traversal.Candidate(
                root_id="widget",
                repository_numeric_id=str(NUMERIC_ID),
                path="b.py",
                blob_sha="b-b",
                discovery_sequence=2,
            ),
        ],
        dispositions={"widget": traversal.COMPLETE},
        visited=[("widget", "t-root")],
        frontier_exhausted=True,
        roots_completed=["widget"],
        transport_totals={"logical_requests": 3},
    )
    base.update(overrides)
    return traversal.Result(**base)


def test_a_different_candidate_order_is_not_equivalent():
    """If order were dropped, these two would compare equal. They must not."""
    forwards = _result_with()
    backwards = _result_with(candidates=list(reversed(forwards.candidates)))
    assert backwards.scientific_digest() != forwards.scientific_digest()


def test_a_different_candidate_set_is_not_equivalent():
    fewer = _result_with(candidates=_result_with().candidates[:1])
    assert fewer.scientific_digest() != _result_with().scientific_digest()


def test_a_different_disposition_is_not_equivalent():
    """A truncated root must never compare equal to one that finished."""
    truncated = _result_with(dispositions={"widget": traversal.STORAGE})
    assert truncated.scientific_digest() != _result_with().scientific_digest()


def test_a_different_visited_set_is_not_equivalent():
    other = _result_with(visited=[("widget", "t-root"), ("widget", "t-src")])
    assert other.scientific_digest() != _result_with().scientific_digest()


def test_an_unexhausted_frontier_is_not_equivalent_to_an_exhausted_one():
    """The difference between a measurement and a partial one."""
    partial = _result_with(frontier_exhausted=False)
    assert partial.scientific_digest() != _result_with().scientific_digest()


def test_a_different_transport_trace_is_still_equivalent():
    """The other direction, and just as load-bearing: segmentation changes the
    request count and must not change the verdict."""
    costly = _result_with(transport_totals={"logical_requests": 99, "hops": 400})
    assert costly.scientific_digest() == _result_with().scientific_digest()


# ------------------------------------------------- what identifies a candidate


def test_candidate_identity_is_repository_path_and_blob():
    candidate = _result_with().candidates[0]
    assert candidate.identity() == (str(NUMERIC_ID), "a.py", "b-a")


def test_the_same_file_under_two_addresses_is_one_candidate():
    """The point of keying on the numeric id: an address is not an identity."""
    old = traversal.Candidate(
        root_id="oldorg/widget", repository_numeric_id=str(NUMERIC_ID),
        path="a.py", blob_sha="b-a", discovery_sequence=1,
    )
    new = traversal.Candidate(
        root_id="acme/widget", repository_numeric_id=str(NUMERIC_ID),
        path="a.py", blob_sha="b-a", discovery_sequence=7,
    )
    assert old.identity() == new.identity()


def test_the_same_path_in_two_repositories_is_two_candidates():
    here = _result_with().candidates[0]
    elsewhere = traversal.Candidate(
        root_id="widget", repository_numeric_id="999", path="a.py",
        blob_sha="b-a", discovery_sequence=1,
    )
    assert here.identity() != elsewhere.identity()


def test_the_same_path_at_a_different_revision_is_a_different_candidate():
    """Mutation T8 dropped the blob from identity, making a changed file the
    same file. Two revisions of one path are two facts, not one."""
    before = _result_with().candidates[0]
    after = traversal.Candidate(
        root_id="widget", repository_numeric_id=str(NUMERIC_ID), path="a.py",
        blob_sha="b-a-revised", discovery_sequence=1,
    )
    assert before.identity() != after.identity()


# ------------------------------------------------------------------- resume detail


def test_a_resumed_segment_does_not_reopen_the_root_it_is_inside(tmp_path, host):
    """Mutation T15 made every segment reopen its root. The science was
    unchanged, so the equivalence controls could not see it -- but at a small
    budget the whole allowance goes on re-attestation and nothing advances."""
    chain = cp.SegmentChain(study_id="SFIR8-DEV", roster_digest=cp.GENESIS)
    first = transport.ManualRedirectTransport()
    first.seed_remaining(5000)
    with traversal.Traversal(
        database=tmp_path / "s.sqlite3", transport=first, roots=roots(),
        extensions=EXTENSIONS,
    ) as run:
        run.run(request_budget=3)
        chain.append(run.checkpoint(0, chain.head))

    resumed = transport.ManualRedirectTransport()
    resumed.seed_remaining(4000)
    with traversal.Traversal(
        database=tmp_path / "s.sqlite3", transport=resumed, roots=roots(),
        extensions=EXTENSIONS,
    ) as run:
        run.resume(chain.segments[-1])
        after_resume = resumed.totals()["logical_requests"]
        run.run(request_budget=3)

    assert after_resume == traversal.RESUME_ROOT_REQUEST_COST, (
        "resuming must cost one request -- the identity re-attestation -- and not "
        "the two that opening a root costs"
    )
    assert len([u for u in host.requests if u.endswith("/commits/main")]) == 1, (
        "the head commit was fetched again, so the root was reopened rather than resumed"
    )


def test_resume_refuses_when_the_checkpoint_names_another_repository(tmp_path, host):
    """The traversal's own check, isolated from the transport's.

    Mutation T16 deleted it and survived, because the earlier control used an
    impostor the *transport* already rejects -- the roster's host_uuid check
    fired first and masked the missing one. Here the live id matches the roster
    and differs only from the checkpoint.
    """
    client = transport.ManualRedirectTransport()
    client.seed_remaining(5000)
    with traversal.Traversal(
        database=tmp_path / "s.sqlite3", transport=client, roots=roots(),
        extensions=EXTENSIONS,
    ) as run:
        run.run(request_budget=3)
        checkpoint = run.checkpoint(0, cp.GENESIS)

    elsewhere = cp.Checkpoint(
        **{**checkpoint.as_dict(), "current_repository_numeric_id": "111111"}
    )
    with traversal.Traversal(
        database=tmp_path / "s.sqlite3",
        transport=transport.ManualRedirectTransport(),
        roots=roots(),
        extensions=EXTENSIONS,
    ) as run, pytest.raises(traversal.TraversalRefused, match="now serves"):
        run.resume(elsewhere)


def test_resume_restores_the_root_index_from_the_checkpoint(tmp_path, host):
    """With two roots, ignoring the index re-traverses from the first one."""
    two = [
        {"root_id": "widget", "address": CANONICAL, "host_uuid": str(NUMERIC_ID)},
        {"root_id": "widget-again", "address": CANONICAL, "host_uuid": str(NUMERIC_ID)},
    ]
    client = transport.ManualRedirectTransport()
    client.seed_remaining(5000)
    with traversal.Traversal(
        database=tmp_path / "s.sqlite3", transport=client, roots=two,
        extensions=EXTENSIONS,
    ) as run:
        run.run(request_budget=None)
        checkpoint = run.checkpoint(0, cp.GENESIS)
    assert checkpoint.root_index == 2

    resumed = transport.ManualRedirectTransport()
    resumed.seed_remaining(4000)
    with traversal.Traversal(
        database=tmp_path / "s.sqlite3", transport=resumed, roots=two,
        extensions=EXTENSIONS,
    ) as run:
        run.resume(checkpoint)
        assert run.root_index == 2
        result = run.run(request_budget=None)
    assert result.frontier_exhausted is True
    assert resumed.totals()["logical_requests"] == 0, (
        "a checkpoint taken past the last root must not re-traverse anything"
    )


def test_a_fine_grained_resume_does_not_renumber_candidates(tmp_path, host):
    """Mutation T9 swapped INSERT OR IGNORE for OR REPLACE, which deletes and
    re-inserts and so hands the candidate a new ordinal. Re-offering a candidate
    already held must change nothing at all."""
    straight, _ = traverse(tmp_path / "straight.sqlite3")
    segmented, _, _ = _segmented(tmp_path / "segmented.sqlite3", budget_per_segment=4)
    assert [(c.path, c.discovery_sequence) for c in segmented.candidates] == [
        (c.path, c.discovery_sequence) for c in straight.candidates
    ]


# ------------------------------------------------- storage exhaustion is not done


def test_a_root_stopped_by_the_storage_bound_is_not_recorded_as_complete(
    tmp_path, host
):
    """Mutation T13 recorded it as COMPLETE -- exactly SFIR7's mistake, where
    truncated roots were counted among the measured."""
    client = transport.ManualRedirectTransport()
    client.seed_remaining(5000)
    with traversal.Traversal(
        database=tmp_path / "tiny.sqlite3",
        transport=client,
        roots=roots(),
        extensions=EXTENSIONS,
        working_storage_bytes=frontier_module.worst_case_entry_bytes(),
    ) as run:
        result = run.run()

    assert result.dispositions == {"widget": traversal.STORAGE}
    assert result.frontier_exhausted is False
    assert traversal.COMPLETE not in result.dispositions.values()


def test_every_stop_reason_is_distinct_from_completion():
    assert traversal.STORAGE != traversal.COMPLETE
    assert traversal.RATE_WINDOW != traversal.COMPLETE
    assert traversal.IDENTITY_REFUSED != traversal.COMPLETE


def test_a_storage_stop_mid_expansion_loses_nothing_when_the_envelope_widens(
    tmp_path, host
):
    """The one place a candidate is genuinely re-offered, and both defects it hid.

    With a one-entry envelope the root tree is expanded far enough to record
    `README.md` and enqueue `src`, and then overflows on `docs`. That leaves the
    root tree entry leased and unfinished, and `README.md` already held.

    Two mutations survived every other control here. `T23` consumed the entry
    instead of releasing it, so the un-enqueued half of that tree was never
    reached and `docs/guide.md` vanished from a run reported as exhausted.
    `T9` swapped `INSERT OR IGNORE` for `OR REPLACE`, so re-offering `README.md`
    deleted and re-inserted it and handed it a new ordinal -- the candidate
    order of a resumed run silently differing from an uninterrupted one.

    Nothing else in the suite reaches this state, because everywhere else an
    expansion either completes or the segment ends cleanly between expansions.
    """
    straight, _ = traverse(tmp_path / "straight.sqlite3")

    narrow = transport.ManualRedirectTransport()
    narrow.seed_remaining(5000)
    with traversal.Traversal(
        database=tmp_path / "resumed.sqlite3",
        transport=narrow,
        roots=roots(),
        extensions=EXTENSIONS,
        working_storage_bytes=frontier_module.worst_case_entry_bytes(),
    ) as run:
        stopped = run.run()

    assert stopped.dispositions == {"widget": traversal.STORAGE}
    assert [c.path for c in stopped.candidates] == ["README.md"]

    wide = transport.ManualRedirectTransport()
    wide.seed_remaining(4000)
    with traversal.Traversal(
        database=tmp_path / "resumed.sqlite3",
        transport=wide,
        roots=roots(),
        extensions=EXTENSIONS,
    ) as run:
        finished = run.run()

    assert finished.frontier_exhausted is True
    assert finished.dispositions == {"widget": traversal.COMPLETE}
    assert [(c.path, c.discovery_sequence) for c in finished.candidates] == [
        (c.path, c.discovery_sequence) for c in straight.candidates
    ], (
        "resuming after a storage stop must reproduce the uninterrupted run "
        "exactly -- same candidates, same ordinals, none lost and none renumbered"
    )
    assert finished.scientific_digest() == straight.scientific_digest()


def test_the_released_entry_is_the_one_that_overflowed(tmp_path, host):
    """Named directly, so the release is not merely inferred from the outcome."""
    client = transport.ManualRedirectTransport()
    client.seed_remaining(5000)
    database = tmp_path / "narrow.sqlite3"
    with traversal.Traversal(
        database=database,
        transport=client,
        roots=roots(),
        extensions=EXTENSIONS,
        working_storage_bytes=frontier_module.worst_case_entry_bytes(),
    ) as run:
        run.run()

    with frontier_module.Frontier(database) as reopened:
        pending = [e.tree_sha for e in reopened.pending()]
    assert "t-root" in pending, (
        "the tree that was being expanded when the envelope overflowed must still "
        "be waiting; consuming it would silently drop everything below it"
    )


def test_retrying_in_the_same_process_re_attempts_the_overflowed_entry(
    tmp_path, host
):
    """Release matters within a process; reclamation only helps across one.

    Mutation T23 replaced `release` with nothing and survived every control,
    because each of them opened a fresh store afterwards and reopening reclaims
    stale leases. The dangerous path is the one that does not reopen: a caller
    that simply calls `run` again on the same traversal.

    Without the release the overflowed entry is still leased, so `dequeue`
    refuses to hand it out, the frontier looks empty and the root is recorded as
    FRONTIER_EXHAUSTED -- a truncated traversal reported as a complete one,
    which is precisely the failure SFIR7 shipped.
    """
    client = transport.ManualRedirectTransport()
    client.seed_remaining(5000)
    with traversal.Traversal(
        database=tmp_path / "narrow.sqlite3",
        transport=client,
        roots=roots(),
        extensions=EXTENSIONS,
        working_storage_bytes=frontier_module.worst_case_entry_bytes(),
    ) as run:
        first = run.run()
        assert first.dispositions == {"widget": traversal.STORAGE}

        second = run.run()

    assert second.dispositions == {"widget": traversal.STORAGE}, (
        "retrying inside the same process must re-attempt the entry that "
        "overflowed, not skip it and call the root finished"
    )
    assert second.frontier_exhausted is False
    assert traversal.COMPLETE not in second.dispositions.values()
