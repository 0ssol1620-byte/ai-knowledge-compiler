"""Controls for SFIR7's roots and for the fourth gate on every Git response.

Three gates were established by SFIR5 and SFIR6: bytes arrived, the API said
yes, and the answer is complete. The gate here is the fourth -- the thing that
answered is the thing that was selected -- and it exists because GitHub returns
HTTP 200 for a renamed address, serving a different repository's tree, with all
three earlier gates green (INC-V2-108, finding 4).
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import sfir5_transport as t5  # noqa: E402
import sfir7_roots as roots  # noqa: E402
import sfir7_transport as t7  # noqa: E402
from acquisition import sources_sfir4 as sources  # noqa: E402

REPO = "babel/babel"
URL = "https://api.github.com/repos/babel/babel"


@pytest.fixture(autouse=True)
def _clear_cache():
    roots.frozen_roster.cache_clear()
    yield
    roots.frozen_roster.cache_clear()


def _reseal(freeze: dict) -> dict:
    payload = json.dumps(freeze["roster"], sort_keys=True, separators=(",", ":")).encode()
    freeze["roster_fingerprint"] = "sha256:" + hashlib.sha256(payload).hexdigest()
    return freeze


def _with_roster(tmp_path, monkeypatch, freeze: dict) -> None:
    path = tmp_path / "freeze.json"
    path.write_text(json.dumps(freeze), encoding="utf-8")
    monkeypatch.setattr(roots, "FREEZE_PATH", path)
    roots.frozen_roster.cache_clear()


def _frozen() -> dict:
    return json.loads(roots.FREEZE_PATH.read_text(encoding="utf-8"))


# --- the roster is read, never retyped ---------------------------------------


def test_the_roots_are_the_frozen_roster_in_frozen_order():
    freeze = _frozen()
    assert roots.declared_roots() == tuple(
        entry["name_with_owner"] for entry in freeze["roster"]
    )
    assert len(roots.declared_roots()) == 50


def test_an_edited_roster_is_refused_by_recomputing_the_fingerprint(tmp_path, monkeypatch):
    """The digest field beside the roster is written by the same process at the
    same moment, so the two agree by construction. Recomputing is the only form
    of this check that can ever fail.
    """
    freeze = _frozen()
    freeze["roster"][0]["name_with_owner"] = "attacker/repo"
    _with_roster(tmp_path, monkeypatch, freeze)
    with pytest.raises(roots.SFIR7RootsRefused, match="edited since it was frozen"):
        roots.declared_roots()


def test_a_roster_that_is_not_frozen_is_refused(tmp_path, monkeypatch):
    freeze = _frozen()
    freeze["state"] = "DRAFT"
    _with_roster(tmp_path, monkeypatch, freeze)
    with pytest.raises(roots.SFIR7RootsRefused, match="not ROSTER_FROZEN"):
        roots.declared_roots()


def test_two_addresses_for_one_repository_are_refused(tmp_path, monkeypatch):
    """Censusing one tree twice would double-count its facts."""
    freeze = _frozen()
    freeze["roster"][1]["host_uuid"] = freeze["roster"][0]["host_uuid"]
    _with_roster(tmp_path, monkeypatch, _reseal(freeze))
    with pytest.raises(roots.SFIR7RootsRefused, match="repeats host id"):
        roots.declared_roots()


def test_a_root_frozen_without_a_host_id_is_refused(tmp_path, monkeypatch):
    """A root the fourth gate could not attest is not censused at all."""
    freeze = _frozen()
    freeze["roster"][0]["host_uuid"] = ""
    _with_roster(tmp_path, monkeypatch, _reseal(freeze))
    with pytest.raises(roots.SFIR7RootsRefused, match="without a host repository id"):
        roots.declared_roots()


def test_an_address_that_is_not_owner_slash_repo_is_refused(tmp_path, monkeypatch):
    freeze = _frozen()
    freeze["roster"][0]["name_with_owner"] = "no-slash"
    _with_roster(tmp_path, monkeypatch, _reseal(freeze))
    with pytest.raises(roots.SFIR7RootsRefused, match="not owner/repo"):
        roots.declared_roots()


# --- the pool inherits its shape, and derives exactly one number -------------


def test_every_bound_but_one_is_read_live_from_the_inherited_module():
    pool = roots.git_pool()
    inherited = sources.SOURCE_POOLS["git_docs"]
    assert pool["extensions"] == tuple(inherited["extensions"])
    assert pool["max_candidates_per_repository"] == inherited["max_candidates_per_repository"]


def test_the_total_candidate_cap_is_derived_the_way_sfir4_derived_its_own():
    """Roots x per-root cap. SFIR4's 1,600 is 20 x 80; carrying that literal to a
    frame two and a half times larger would be a cap set by historical accident.
    """
    inherited = sources.SOURCE_POOLS["git_docs"]
    assert inherited["max_total_candidates"] == 20 * inherited["max_candidates_per_repository"]
    assert roots.max_total_candidates() == 50 * inherited["max_candidates_per_repository"]
    assert roots.git_pool()["max_total_candidates"] == roots.max_total_candidates()


def test_the_inherited_bounds_are_reported_with_the_values_they_actually_have():
    reported = roots.inherited_bounds()
    assert reported["max_git_api_requests_global"] == sources.MAX_GIT_API_REQUESTS_GLOBAL
    assert reported["max_git_api_requests_per_root"] == sources.MAX_GIT_API_REQUESTS_PER_ROOT
    assert reported["max_git_tree_objects_per_root"] == sources.MAX_GIT_TREE_OBJECTS_PER_ROOT


# --- the fourth gate ---------------------------------------------------------


def _drive(monkeypatch, responses: dict, url: str, family: str = "git_docs"):
    """Run the real `SFIR7Transport._observe`, stubbing only the network beneath it.

    Not a reimplementation and not a subclass: the method under test is the one
    that will run live, and only `PacedObservingTransport._observe` -- the call
    that would open a socket -- is replaced.
    """
    monkeypatch.setattr(
        t5.PacedObservingTransport, "_observe", lambda self, f, r, u: responses[u]
    )
    transport = object.__new__(t7.SFIR7Transport)
    transport.observed_ids = {}
    transport.renames = {}
    return transport, transport._observe(family, "root", url)


def test_the_selected_repository_passes_the_gate(monkeypatch):
    """So the refusals below mean something."""
    expected = roots.expected_uuid(REPO)
    transport, value = _drive(
        monkeypatch, {URL: {"id": int(expected), "default_branch": "main"}}, URL
    )
    assert transport.observed_ids[REPO] == expected
    assert transport.renames == {}
    assert value["default_branch"] == "main"


def test_a_different_repository_under_the_same_address_is_refused(monkeypatch):
    """HTTP 200, well-formed JSON, a real repository -- and the wrong one.

    All three earlier gates pass on this response. This is the only one that does
    not.
    """
    with pytest.raises(t7.RepositoryIdentityRefused, match="different repository"):
        _drive(monkeypatch, {URL: {"id": 999999999, "default_branch": "main"}}, URL)


def test_a_response_without_a_repository_id_is_refused(monkeypatch):
    with pytest.raises(t7.RepositoryIdentityRefused, match="no repository id"):
        _drive(monkeypatch, {URL: {"default_branch": "main"}}, URL)


def test_a_response_that_is_not_an_object_is_refused(monkeypatch):
    with pytest.raises(t7.RepositoryIdentityRefused, match="not an object"):
        _drive(monkeypatch, {URL: [1, 2, 3]}, URL)


def test_a_rename_that_keeps_the_id_is_reported_and_not_refused(monkeypatch):
    """Identity is the id. The address is only where the question was asked."""
    expected = roots.expected_uuid(REPO)
    transport, _ = _drive(
        monkeypatch,
        {URL: {"id": int(expected), "full_name": "babel/renamed", "default_branch": "main"}},
        URL,
    )
    assert transport.renames == {REPO: "babel/renamed"}
    assert transport.observed_ids[REPO] == expected
    assert transport.identity_attestation()["rename_count"] == 1


def test_a_case_only_difference_in_the_address_is_not_a_rename(monkeypatch):
    """GitHub is case-insensitive on owner and repo. Reporting that as a rename
    would fill the receipt with noise nobody can act on.
    """
    expected = roots.expected_uuid(REPO)
    transport, _ = _drive(
        monkeypatch,
        {URL: {"id": int(expected), "full_name": "Babel/Babel", "default_branch": "main"}},
        URL,
    )
    assert transport.renames == {}


def test_a_tree_or_commit_url_is_not_mistaken_for_the_metadata_response(monkeypatch):
    """Those are addressed by sha and carry no repository id. Attesting them
    would refuse every root on its second request.
    """
    for suffix in ("/commits/main", "/git/trees/abc123"):
        url = URL + suffix
        transport, value = _drive(monkeypatch, {url: {"sha": "x" * 40}}, url)
        assert transport.observed_ids == {}
        assert value == {"sha": "x" * 40}


def test_a_non_git_family_is_left_alone(monkeypatch):
    url = "https://www.ecfr.gov/api/versioner/v1/titles.json"
    transport, _ = _drive(monkeypatch, {url: {"titles": []}}, url, family="regulation_ecfr")
    assert transport.observed_ids == {}


def test_a_repository_outside_the_frozen_roster_is_refused(monkeypatch):
    """The gate cannot pass a root it has no frozen id for."""
    url = "https://api.github.com/repos/attacker/repo"
    with pytest.raises(roots.SFIR7RootsRefused, match="not a frozen SFIR7 root"):
        _drive(monkeypatch, {url: {"id": 1, "default_branch": "main"}}, url)


def test_the_attestation_summary_reports_what_the_gate_actually_saw(monkeypatch):
    expected = roots.expected_uuid(REPO)
    transport, _ = _drive(
        monkeypatch, {URL: {"id": int(expected), "default_branch": "main"}}, URL
    )
    summary = transport.identity_attestation()
    assert summary["roots_attested"] == 1
    assert summary["roots_frozen"] == 50
    assert summary["on_mismatch"] == "REFUSE"
    assert summary["rename_count"] == 0
