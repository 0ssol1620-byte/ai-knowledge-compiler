"""RED CONTROLS for the INC-V2-106 defect class in git_docs and regulation_ecfr.

Lane C hostile audit, 2026-08-27. Every test marked ``xfail(strict=True)`` here
is EXPECTED TO FAIL against the adapters as they stand. They are not a repair
and they are not a regression suite: they are the executable statement of a
finding, so that a later repair has something that turns green.

The defect class, restated -- three gates, none implying the next:

    transport success      the bytes arrived
    protocol success       the API said yes
    semantic completeness  every requested identity is accounted for

Nothing here touches the network. Every fetcher is injected.

Run:
    .venv/Scripts/python.exe -m pytest \
        research/tavonel_eval_v2/tests/test_adapter_protocol_gates.py -rA
"""

from __future__ import annotations

import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

NS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(NS / "tools"))
sys.path.insert(0, str(NS))

import probe_sfir3_capacity as legacy  # noqa: E402
import probe_sfir4_capacity as probe4  # noqa: E402
import sfir4_protocol as protocol4  # noqa: E402
from acquisition import sources_sfir4 as sources4  # noqa: E402

ECFR_POOL = sources4.SOURCE_POOLS["regulation_ecfr"]
GIT_POOL = sources4.SOURCE_POOLS["git_docs"]
REPO = GIT_POOL["repositories"][0]


def _ecfr_request(index: int = 0) -> dict[str, Any]:
    title = ECFR_POOL["titles"][index]
    return {
        "cursor": str(index),
        "pool": ECFR_POOL,
        "metadata_only": True,
        "expected_discovery_root_id": sources4.discovery_root_id("regulation_ecfr", title),
    }


def _git_request() -> dict[str, Any]:
    return {
        "cursor": "0",
        "pool": GIT_POOL,
        "repository": REPO,
        "metadata_only": True,
        "expected_discovery_root_id": sources4.discovery_root_id("git_docs", REPO),
    }


def _ecfr(fetch: Any) -> Mapping[str, Any]:
    return legacy.LiveMetadataTransport(fetch)._ecfr(_ecfr_request())


# ---------------------------------------------------------------------------
# GREEN CONTROLS -- these must pass, or the harness proves nothing.
# ---------------------------------------------------------------------------


def test_green_control_ecfr_empty_title_is_a_corpus_zero() -> None:
    """The one ZERO_CANDIDATE the eCFR adapter is entitled to emit.

    Envelope shape captured live 2026-08-27 from
    versions/title-4.json?part=ZZZZNONEXISTENT (HTTP 200, 88 bytes):
    {"content_versions":[],"meta":{"title":"4","part":"...","result_count":"0"}}
    Note that result_count is a STRING and total_pages is absent.
    """

    def fetch(url: str) -> Mapping[str, Any]:
        return {"content_versions": [], "meta": {"title": "1", "result_count": "0"}}

    out = _ecfr(fetch)
    assert out["root_disposition"]["state"] == "ZERO_CANDIDATE_ROOT_DISPOSITION"
    assert out["root_disposition"]["reason"] == "EMPTY_ENUMERATION_NO_VERSIONS"


def test_green_control_ecfr_declared_row_count_is_enforced() -> None:
    """Semantic completeness IS gated on eCFR: rows_seen must equal result_count.

    This is the gate the Wikipedia lane never had. It works, and saying so is
    part of the audit.
    """

    def fetch(url: str) -> Mapping[str, Any]:
        return {
            "content_versions": [
                {"type": "section", "part": "1", "identifier": "1.1", "date": "2026-01-01"}
            ],
            "meta": {
                "result_count": "9",
                "total_pages": "1",
                "latest_amendment_date": "2026-01-01",
            },
        }

    out = _ecfr(fetch)
    assert out["root_disposition"]["reason"] == "TRUNCATED_OR_INCOMPLETE_ENUMERATION"


# ---------------------------------------------------------------------------
# FINDING 1 -- an eCFR root the server refused is filed as a corpus zero.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason="FINDING 1 (HIGH): probe_sfir3_capacity.py:426-432 files HTTP 404/409/451 as "
    "ZERO_CANDIDATE_ROOT_DISPOSITION. The very same status on git_docs produces "
    "UNAVAILABLE_ROOT_DISPOSITION (probe_sfir4_capacity.py:410). One census, one "
    "status, two meanings.",
)
def test_ecfr_unavailable_root_is_not_a_zero_candidate() -> None:
    def fetch(url: str) -> Mapping[str, Any]:
        raise legacy.RootUnavailable(404, url)

    out = _ecfr(fetch)
    assert out["root_disposition"]["state"] == "UNAVAILABLE_ROOT_DISPOSITION"


# ---------------------------------------------------------------------------
# FINDING 2 -- an eCFR root the instrument could not finish reading is filed
# as a corpus zero. INC-V2-106's exact shape, in the eCFR lane.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason="FINDING 2 (HIGH): probe_sfir3_capacity.py:433-439 and :464-470 file "
    "TRUNCATED_OR_INCOMPLETE_ENUMERATION -- 'we could not finish reading this root' -- "
    "under the same STATE as 'this root is empty'. 29 of 30 Wikipedia roots carried "
    "exactly this reason in SFIR5 and the family still read C=0 (INC-V2-106).",
)
def test_ecfr_truncated_enumeration_is_not_a_zero_candidate() -> None:
    def fetch(url: str) -> Mapping[str, Any]:
        return {
            "content_versions": [
                {"type": "section", "part": "1", "identifier": "1.1", "date": "2026-01-01"}
            ],
            "meta": {
                "result_count": "1",
                # Above ECFR_POOL["max_version_pages_per_title"] == 250.
                "total_pages": "9999",
                "latest_amendment_date": "2026-01-01",
            },
        }

    out = _ecfr(fetch)
    assert out["root_disposition"]["state"] != "ZERO_CANDIDATE_ROOT_DISPOSITION"


@pytest.mark.xfail(
    strict=True,
    reason="FINDING 2b (MEDIUM): sfir4_protocol.seal_capacity admits "
    "ZERO_CANDIDATE_ROOT_DISPOSITION (:670-679) with no rule whatever about its reason, "
    "so a family whose every zero is an instrument failure seals as a measured C=0. "
    "No disposition reason string appears anywhere in the sealing module.",
)
def test_seal_capacity_can_tell_an_instrument_zero_from_a_corpus_zero() -> None:
    reasons = {
        "TRUNCATED_OR_INCOMPLETE_ENUMERATION",
        "EMPTY_ENUMERATION_DISAGREES_WITH_FIRST_CENSUS",
        "EMPTY_ENUMERATION_NO_VERSIONS",
    }
    source = Path(protocol4.__file__).read_text(encoding="utf-8")
    assert any(reason in source for reason in reasons), (
        "seal_capacity never mentions a zero-disposition reason, so it cannot "
        "distinguish an instrument zero from a corpus zero"
    )


# ---------------------------------------------------------------------------
# FINDING 3 -- git_docs: a path whose commit history comes back empty vanishes.
# ---------------------------------------------------------------------------

_TREE_SHA = "a" * 40
_HEAD_SHA = "b" * 40


def _git_fetcher(commits: list[Any]) -> Any:
    def fetch(url: str) -> Any:
        if url == f"https://api.github.com/repos/{REPO}":
            return {"default_branch": "main", "full_name": REPO}
        if "/commits/main" in url:
            return {"sha": _HEAD_SHA, "commit": {"tree": {"sha": _TREE_SHA}}}
        if "/git/trees/" in url:
            return {
                "sha": _TREE_SHA,
                "truncated": False,
                "tree": [{"path": "README.md", "type": "blob", "sha": "c" * 40}],
            }
        if "/commits?path=" in url:
            return commits
        raise AssertionError(f"unexpected url {url}")

    return fetch


@pytest.mark.xfail(
    strict=True,
    reason="FINDING 3 (HIGH): probe_sfir4_capacity.py:626-627, 'if len(commits) < 2: "
    "continue'. GitHub answers HTTP 200 with [] for a commit query whose path filter "
    "matches nothing -- captured live 2026-08-27 against pypa/setuptools. A path that IS "
    "in the HEAD tree cannot honestly have zero commits, so [] there is a protocol or "
    "instrument failure; it is dropped silently under the same continue as a genuinely "
    "single-commit file. A root where every path answers [] seals as COMPLETE with zero "
    "candidates -- a zero that reads as 'we looked, there was nothing'.",
)
def test_git_path_with_no_commit_history_is_not_silently_dropped() -> None:
    transport = probe4.LiveMetadataTransport(_git_fetcher([]))
    out = transport("git_docs", _git_request())
    proof = out["root_disposition"]["traversal_proof"]
    assert out["items"] == []
    # A path discovered in HEAD that returned no history at all must be counted
    # somewhere. Nothing in the traversal proof records it.
    assert "history_paths_empty" in proof or out["root_disposition"]["state"] != "COMPLETE"


# ---------------------------------------------------------------------------
# FINDING 4 -- git_docs: HTTP 200 carrying a DIFFERENT repository identity.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason="FINDING 4 (HIGH): probe_sfir4_capacity.py:407-409 accepts the repository "
    "metadata body if it merely carries a string default_branch. It never compares "
    "full_name or id to the repository it asked for. urllib follows GitHub's rename 301 "
    "silently: captured live 2026-08-27, GET /repos/facebook/jest -> HTTP 200 served from "
    "/repositories/15062869 with full_name jestjs/jest. Candidates would then be attributed "
    "to a discovery_root_id, snapshot_id and payload_ref naming a repository that does not "
    "hold them, and the SFIR1/2/3 disjointness proof would be defeated.",
)
def test_git_repository_identity_is_verified_against_the_requested_root() -> None:
    base = _git_fetcher([])

    def fetch(url: str) -> Any:
        if url == f"https://api.github.com/repos/{REPO}":
            return {"default_branch": "main", "full_name": "someone-else/other-repo"}
        return base(url)

    transport = probe4.LiveMetadataTransport(fetch)
    with pytest.raises(protocol4.SFIR4Refused):
        transport("git_docs", _git_request())


# ---------------------------------------------------------------------------
# FINDING 5 -- REFUTED. Kept as a passing control, because the refutation is
# worth more than the finding was.
#
# The claim was that only `git_docs` reaches the ResponseLedger, since
# `probe_sfir4_capacity.py:392` is the sole call site of `_observe`. That is
# true of SFIR4's probe and false of the transport that executed SFIR5 and is
# executing SFIR6: `PacedObservingTransport.__init__` replaces the legacy
# closure with one whose body is `self._observe(family, root_id, url)`.
#
# `receipts/sfir5-capacity-census-seal.json` settles it empirically --
# `families_in_ledger` carries all three, and `www.ecfr.gov` logged 1,011
# requests. Had eCFR bypassed the ledger, `require_family_coverage` would have
# refused that census.
#
# The lesson kept in INC-V2-108: an audit of an inherited module is not an audit
# of the code that runs.
# ---------------------------------------------------------------------------


def test_the_transport_that_actually_runs_records_ecfr_in_the_ledger() -> None:
    """Asserted over SFIR5's transport, which is what a census instantiates."""
    import sfir5_transport as t5

    transport = t5.PacedObservingTransport(clock=lambda: 0.0, sleep=lambda _s: None)

    def fetch(url: str):
        return {"content_versions": [], "meta": {"title": "1", "result_count": "0"}}, {
            "status": 200,
            "content_digest": "sha256:" + "e" * 64,
            "observed_length": 64,
            "declared_length": None,
            "observed_bytes": True,
        }

    import probe_sfir4_capacity as _p4

    original = _p4._http_json_observed
    _p4._http_json_observed = fetch
    try:
        transport("regulation_ecfr", _ecfr_request())
    finally:
        _p4._http_json_observed = original

    rows = transport.ledger.observations()
    assert rows, "eCFR left no ledger row"
    assert {row.family for row in rows} == {"regulation_ecfr"}


def test_sfir4s_bare_transport_is_the_one_that_does_not_record_ecfr() -> None:
    """The paired negative, so the control above is not vacuous.

    SFIR4's transport really does bypass the ledger for eCFR. The finding was
    right about this object and wrong about which object runs a census.
    """
    def fetch(url: str) -> Mapping[str, Any]:
        return {"content_versions": [], "meta": {"title": "1", "result_count": "0"}}

    transport = probe4.LiveMetadataTransport(fetch)
    transport("regulation_ecfr", _ecfr_request())
    assert len(transport.ledger) == 0


# ---------------------------------------------------------------------------
# FINDING 6 -- INC-V2-036 lens: a bound that cannot be reached within a root.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason="FINDING 6 (LOW): sources_sfir4.py:283-289 ASSERTS "
    "2 + MAX_GIT_TREE_OBJECTS_PER_ROOT + max_candidates_per_repository == "
    "MAX_GIT_API_REQUESTS_PER_ROOT (2+158+80 == 240), while probe_sfir4_capacity.py:465-469 "
    "returns EXCLUDED as soon as len(visited) >= 158. So request_count >= 240 (:385-388) can "
    "never fire within one attempt at a root, and both except GitRequestBoundExceeded "
    "handlers (:477, :610) are unreachable through the per-root counter. They are reachable "
    "only through _global_git_request_count, which a rate-limit retry does not reset -- so "
    "what that bound actually measures is retry volume, not root size.",
)
def test_per_root_git_request_bound_is_reachable() -> None:
    plan = 2 + sources4.MAX_GIT_TREE_OBJECTS_PER_ROOT + GIT_POOL["max_candidates_per_repository"]
    assert plan > sources4.MAX_GIT_API_REQUESTS_PER_ROOT
