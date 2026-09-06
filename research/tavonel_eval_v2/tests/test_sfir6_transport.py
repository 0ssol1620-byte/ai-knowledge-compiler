"""SFIR6's transport, driven through the real entry point against stubs.

The controls that matter here are about *dispositions*, because that is where
INC-V2-106 actually did its damage. The adapter's failure did not surface as an
exception. It surfaced as 29 roots filed `ZERO_CANDIDATE_ROOT_DISPOSITION` --
"we looked, there was nothing" -- which is a false statement about a request the
endpoint refused. A census reports that as C=0 and a reader takes it for a
measurement.

So each control below asks not only whether the transport stopped, but what it
would have *said* about the root.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import probe_sfir4_capacity as probe4  # noqa: E402
import sfir6_transport as t6  # noqa: E402
import sfir6_wikipedia as wiki  # noqa: E402
from acquisition import sources_sfir4 as sources  # noqa: E402

POOL = sources.SOURCE_POOLS["encyclopedia_wikipedia"]
CATEGORY = POOL["category_roots"][0]
ROOT_ID = sources.discovery_root_id("encyclopedia_wikipedia", CATEGORY)


def _request(index: int = 0) -> dict[str, Any]:
    return {
        "cursor": str(index),
        "pool": POOL,
        "metadata_only": True,
        "expected_discovery_root_id": ROOT_ID,
    }


def _seen(payload: bytes = b"x") -> dict[str, Any]:
    return {
        "status": 200,
        "content_digest": "sha256:" + "c" * 64,
        "observed_length": len(payload),
        "declared_length": None,
        "observed_bytes": True,
    }


def _install(monkeypatch, router):
    """Route by URL shape, so a control describes the endpoint's behaviour rather
    than the order in which the transport happens to ask."""

    def fake(url: str):
        return router(url), _seen()

    monkeypatch.setattr(probe4, "_http_json_observed", fake)


def _members(n: int, start: int = 1000):
    return {
        "batchcomplete": True,
        "query": {"categorymembers": [{"pageid": start + i, "title": f"P{i}"} for i in range(n)]},
    }


def _latest(page_ids, parent_offset: int = 500_000):
    return {
        "batchcomplete": True,
        "query": {
            "pages": [
                {
                    "pageid": p,
                    "title": f"T{p}",
                    "revisions": [
                        {
                            "revid": p + 900_000,
                            "parentid": p + parent_offset,
                            "timestamp": "2026-02-02T00:00:00Z",
                        }
                    ],
                }
                for p in page_ids
            ]
        },
    }


def _parents(revids):
    return {
        "batchcomplete": True,
        "query": {
            "pages": [
                {
                    "pageid": 1,
                    "revisions": [
                        {"revid": r, "timestamp": "2026-01-01T00:00:00Z"} for r in revids
                    ],
                }
            ]
        },
    }


def _transport():
    return t6.SFIR6Transport(clock=lambda: 0.0, sleep=lambda _s: None)


def _ids_in(url: str, key: str) -> list[int]:
    import urllib.parse

    raw = urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get(key, [""])[0]
    return [int(v) for v in raw.split("|") if v]


# --- the happy path, so the refusals below mean something --------------------


def test_a_root_that_resolves_is_COMPLETE_and_yields_pairs(monkeypatch):
    def router(url: str):
        if "categorymembers" in url:
            return _members(3)
        if "pageids=" in url:
            return _latest(_ids_in(url, "pageids"))
        return _parents(_ids_in(url, "revids"))

    _install(monkeypatch, router)
    response = _transport()("encyclopedia_wikipedia", _request())
    assert response["root_disposition"]["state"] == "COMPLETE"
    assert len(response["items"]) == 3
    item = response["items"][0]
    assert item["revision_before"] != item["revision_after"]
    assert item["timestamp_before"] < item["timestamp_after"]


def test_the_repaired_census_records_every_request_in_the_ledger(monkeypatch):
    """INC-V2-102 stays repaired through the new code path."""

    def router(url: str):
        if "categorymembers" in url:
            return _members(2)
        if "pageids=" in url:
            return _latest(_ids_in(url, "pageids"))
        return _parents(_ids_in(url, "revids"))

    _install(monkeypatch, router)
    transport = _transport()
    transport("encyclopedia_wikipedia", _request())
    rows = transport.ledger.observations()
    assert len(rows) == 3
    assert {r.family for r in rows} == {"encyclopedia_wikipedia"}
    assert all(r.observed_bytes for r in rows)


# --- INC-V2-106 cannot recur silently ----------------------------------------


def test_the_sfir5_error_envelope_refuses_instead_of_producing_a_zero(monkeypatch):
    """The whole incident, as one control. SFIR5 turned this response into
    `ZERO_CANDIDATE_ROOT_DISPOSITION` on 29 roots. It must now refuse, because a
    refused request is not a measured absence."""

    def router(url: str):
        if "categorymembers" in url:
            return _members(3)
        return {"error": {"code": "invalidparammix", "info": "..."}, "servedby": "mw"}

    _install(monkeypatch, router)
    with pytest.raises(wiki.WikipediaProtocolError, match="invalidparammix"):
        _transport()("encyclopedia_wikipedia", _request())


def test_a_missing_page_reduces_candidates_but_is_counted(monkeypatch):
    """Accounted, not dropped. The proof carries the number, so a shrunken
    candidate list is explained by the receipt rather than discovered later."""

    def router(url: str):
        if "categorymembers" in url:
            return _members(3)
        if "pageids=" in url:
            ids = _ids_in(url, "pageids")
            body = _latest(ids[1:])
            body["query"]["pages"].append({"pageid": ids[0], "missing": True})
            return body
        return _parents(_ids_in(url, "revids"))

    _install(monkeypatch, router)
    response = _transport()("encyclopedia_wikipedia", _request())
    proof = response["root_disposition"]["traversal_proof"]
    assert proof["pages_absent_at_revision_time"] == 1
    assert proof["pairs_built"] == 2
    assert len(response["items"]) == 2


def test_an_unresolved_parent_revision_refuses(monkeypatch):
    """A hole in the evidence chain, not a page-level fact. Skipping it would
    shrink the cohort without anything saying so."""

    def router(url: str):
        if "categorymembers" in url:
            return _members(2)
        if "pageids=" in url:
            return _latest(_ids_in(url, "pageids"))
        return _parents([])

    _install(monkeypatch, router)
    with pytest.raises(wiki.WikipediaSemanticIncomplete, match="never resolved"):
        _transport()("encyclopedia_wikipedia", _request())


def test_a_truncated_category_is_EXCLUDED_not_ZERO_CANDIDATE(monkeypatch):
    """The disposition distinction INC-V2-106 got wrong. An enumeration that hit
    its page bound before continuation ran out has not established that the
    category is empty, and must not be filed as though it had."""

    def router(url: str):
        if "categorymembers" in url:
            return {**_members(3), "continue": {"cmcontinue": "more|1"}}
        if "pageids=" in url:
            return _latest(_ids_in(url, "pageids"))
        return _parents(_ids_in(url, "revids"))

    _install(monkeypatch, router)
    response = _transport()("encyclopedia_wikipedia", _request())
    disposition = response["root_disposition"]
    assert disposition["state"] == "EXCLUDED_INCOMPLETE_ROOT_DISPOSITION"
    assert disposition["reason"] == "CATEGORY_PAGE_BOUND_BEFORE_CONTINUATION_EXHAUSTED"
    assert disposition["traversal_proof"]["continuation_exhausted"] is False


def test_a_genuinely_empty_category_is_ZERO_CANDIDATE(monkeypatch):
    """The paired positive for the control above: when the enumeration really
    did exhaust and found nothing, ZERO_CANDIDATE is the honest disposition."""

    def router(url: str):
        if "categorymembers" in url:
            return _members(0)
        return _latest([])

    _install(monkeypatch, router)
    response = _transport()("encyclopedia_wikipedia", _request())
    disposition = response["root_disposition"]
    assert disposition["state"] == "ZERO_CANDIDATE_ROOT_DISPOSITION"
    assert disposition["traversal_proof"]["continuation_exhausted"] is True


def test_no_request_the_transport_builds_carries_rvlimit(monkeypatch):
    """Asserted over what actually left the machine, not over the constructor."""
    urls: list[str] = []

    def router(url: str):
        urls.append(url)
        if "categorymembers" in url:
            return _members(2)
        if "pageids=" in url:
            return _latest(_ids_in(url, "pageids"))
        return _parents(_ids_in(url, "revids"))

    _install(monkeypatch, router)
    _transport()("encyclopedia_wikipedia", _request())
    assert urls
    assert not any("rvlimit" in url for url in urls)


# --- the frame is carried forward, not redesigned ----------------------------


def test_a_request_that_escapes_the_frozen_roots_refuses():
    transport = _transport()
    bad = {**_request(), "expected_discovery_root_id": "wikipedia:category:NotDeclared"}
    with pytest.raises(Exception, match="escaped frozen roots"):
        transport("encyclopedia_wikipedia", bad)


def test_git_and_ecfr_still_go_through_the_inherited_path(monkeypatch):
    """SFIR6 repairs one family. If it had quietly changed the others' code path,
    its numbers would be incomparable with SFIR5's for reasons unrelated to the
    repair."""
    calls: list[str] = []
    monkeypatch.setattr(
        t6.t5.PacedObservingTransport,
        "__call__",
        lambda self, family, request: calls.append(family) or {"items": []},
    )
    transport = _transport()
    transport("git_docs", {"expected_discovery_root_id": "x", "pool": {}})
    transport("regulation_ecfr", {"expected_discovery_root_id": "x", "pool": {}})
    assert calls == ["git_docs", "regulation_ecfr"]


def test_sfir6_adds_no_git_root_after_seeing_sfir5s_shortfall():
    """293 was a measurement. Adding a root to clear 750 would make SFIR6 an
    outcome-conditioned redesign rather than an instrument repair, which the
    standing instruction forbids by name."""
    assert len(sources.declared_roots("git_docs")) == 20
    assert len(sources.declared_roots("regulation_ecfr")) == 50
    assert len(sources.declared_roots("encyclopedia_wikipedia")) == 30


def test_the_capacity_thresholds_are_untouched():
    import sfir4_protocol as protocol

    source = (NS / "tools" / "sfir4_protocol.py").read_text(encoding="utf-8")
    assert "count < 750 or quota < 600" in source
    assert protocol.PROTOCOL_ID.endswith("_V4")


def test_a_revision_batch_that_did_not_complete_refuses(monkeypatch):
    """The gap mutation testing found in this file's own controls.

    Every stub above sets `batchcomplete`, so removing the check on pass 1
    changed nothing and the mutant survived. A revision batch that declares a
    continuation is a partial answer, and treating it as the whole one is the
    silent truncation the study keeps paying for.
    """

    def router(url: str):
        if "categorymembers" in url:
            return _members(3)
        if "pageids=" in url:
            body = _latest(_ids_in(url, "pageids"))
            del body["batchcomplete"]
            body["continue"] = {"rvcontinue": "more|1"}
            return body
        return _parents(_ids_in(url, "revids"))

    _install(monkeypatch, router)
    with pytest.raises(wiki.WikipediaSemanticIncomplete, match="did not declare itself complete"):
        _transport()("encyclopedia_wikipedia", _request())


def test_a_parent_batch_that_did_not_complete_refuses(monkeypatch):
    """The same on pass 2, which is a separate request and a separate check."""

    def router(url: str):
        if "categorymembers" in url:
            return _members(3)
        if "pageids=" in url:
            return _latest(_ids_in(url, "pageids"))
        body = _parents(_ids_in(url, "revids"))
        del body["batchcomplete"]
        return body

    _install(monkeypatch, router)
    with pytest.raises(wiki.WikipediaSemanticIncomplete, match="did not declare itself complete"):
        _transport()("encyclopedia_wikipedia", _request())
