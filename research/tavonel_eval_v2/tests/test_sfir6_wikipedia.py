"""SFIR6's Wikipedia adapter, against envelopes the live endpoint actually sent.

Every fixture below was captured from `en.wikipedia.org/w/api.php` before the
adapter was written, and each one arrived with **HTTP 200**. That is the point of
the whole module: the defect that hid for four studies (INC-V2-106) was a
successful HTTP response carrying a refusal.

The oracle here is deliberately independent of the implementation. These are not
shapes the adapter believes MediaWiki produces -- they are shapes MediaWiki
produced, recorded verbatim. A control written against the adapter's own model of
the API could only ever confirm that model, which is the same mistake as checking
a successor against its ancestor.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import sfir6_wikipedia as w  # noqa: E402
from acquisition import sources_sfir4 as sources  # noqa: E402

URL = "https://en.wikipedia.org/w/api.php?probe"

# --- captured verbatim from the endpoint, all HTTP 200 -----------------------

INVALIDPARAMMIX = {
    "error": {
        "code": "invalidparammix",
        "info": '"titles", "pageids" or a generator was used to supply multiple pages, '
        'but the "rvlimit", "rvstartid", "rvendid", "rvdir=newer", "rvuser", '
        '"rvexcludeuser", "rvstart", and "rvend" parameters may only be used on a '
        "single page.",
    },
    "servedby": "mw-api-ext.eqiad.main-7549cc5bd5-8znrb",
}

MISSING_PAGE = {
    "batchcomplete": True,
    "query": {"pages": [{"missing": True, "pageid": 999999999999}]},
}

MIXED_VALID_AND_MISSING = {
    "batchcomplete": True,
    "query": {
        "pages": [
            {
                "pageid": 9228,
                "title": "Earth",
                "revisions": [{"revid": 1370989416, "parentid": 1370831116}],
            },
            {"missing": True, "pageid": 999999999999},
        ]
    },
}

BAD_REVIDS = {
    "batchcomplete": True,
    "query": {
        "badrevids": {"999999999999": {"revid": 999999999999, "missing": True}},
        "pages": [{"pageid": 32978, "title": "Wikipedia:Wikipedians"}],
    },
}

GOOD_BATCH = {
    "batchcomplete": True,
    "limits": {"revisions": 500},
    "query": {
        "pages": [
            {
                "pageid": 9228,
                "title": "Earth",
                "revisions": [
                    {
                        "revid": 1370989416,
                        "parentid": 1370831116,
                        "timestamp": "2026-08-24T00:00:00Z",
                    }
                ],
            },
            {
                "pageid": 22939,
                "title": "Physics",
                "revisions": [
                    {
                        "revid": 1367298570,
                        "parentid": 1367195989,
                        "timestamp": "2026-08-02T00:00:00Z",
                    }
                ],
            },
        ]
    },
}

CONTINUING_BATCH = {
    "continue": {"rvcontinue": "20260101000000|1", "continue": "||"},
    "query": {"pages": [{"pageid": 9228, "title": "Earth", "revisions": []}]},
}


# --- gate 2: the API said no, with HTTP 200 ----------------------------------


def test_invalidparammix_is_refused():
    """The exact envelope that produced four studies of silence. It has no
    `query` block at all, and it arrived as a 200."""
    with pytest.raises(w.WikipediaProtocolError, match="invalidparammix"):
        w.require_protocol_success(INVALIDPARAMMIX, url=URL)


def test_bad_revision_ids_are_refused():
    """`badrevids` sits inside a response with no error and `batchcomplete` set.
    Nothing above the semantic layer would notice it."""
    with pytest.raises(w.WikipediaProtocolError, match="bad revision ids"):
        w.require_protocol_success(BAD_REVIDS, url=URL)


def test_a_warnings_envelope_is_refused_not_tolerated():
    """MediaWiki emits `warnings` when it has silently changed the request --
    truncated a parameter, ignored a property, applied a limit. The response then
    answers a different question from the one asked, so it is a refusal here."""
    with pytest.raises(w.WikipediaProtocolError, match="warnings"):
        w.require_protocol_success(
            {**GOOD_BATCH, "warnings": {"revisions": {"*": "truncated"}}}, url=URL
        )


def test_a_response_with_no_query_block_is_refused():
    with pytest.raises(w.WikipediaProtocolError, match="no query block"):
        w.require_protocol_success({"batchcomplete": True}, url=URL)


def test_a_non_object_response_is_refused():
    with pytest.raises(w.WikipediaProtocolError, match="not a JSON object"):
        w.require_protocol_success([1, 2, 3], url=URL)


def test_a_genuinely_good_response_passes():
    """The paired positive. Without it every control above is satisfied by a
    function that refuses everything."""
    query = w.require_protocol_success(GOOD_BATCH, url=URL)
    assert len(query["pages"]) == 2


# --- gate 3: it said yes and did not answer ----------------------------------


def test_a_missing_page_is_accounted_not_dropped():
    """A page that vanished between the category listing and the revision fetch
    is a fact, not a fault. It must be written down as absent rather than
    silently reducing the candidate count."""
    accounting = w.require_every_identity_accounted(
        [9228, 999999999999], MIXED_VALID_AND_MISSING["query"]["pages"], key="pageid", url=URL
    )
    assert accounting == {"present": [9228], "absent": [999999999999]}


def test_a_requested_id_absent_from_the_response_entirely_is_refused():
    """Different from `missing: true`. Here the API neither returned the page nor
    said anything about it, which is truncation."""
    with pytest.raises(w.WikipediaSemanticIncomplete, match="absent from the response"):
        w.require_every_identity_accounted(
            [9228, 22939], MISSING_PAGE["query"]["pages"], key="pageid", url=URL
        )


def test_a_duplicated_identity_in_the_response_is_refused():
    rows = [{"pageid": 9228}, {"pageid": 9228}]
    with pytest.raises(w.WikipediaSemanticIncomplete, match="duplicate pageid"):
        w.require_every_identity_accounted([9228], rows, key="pageid", url=URL)


def test_a_duplicated_identity_in_the_request_is_refused():
    """Checked on the way out as well as the way back: a request that asks twice
    makes the cardinality comparison meaningless in both directions."""
    with pytest.raises(w.WikipediaSemanticIncomplete, match="duplicate ids in the request"):
        w.require_every_identity_accounted([9228, 9228], [{"pageid": 9228}], key="pageid", url=URL)


def test_a_response_carrying_something_never_requested_is_refused():
    rows = [{"pageid": 9228}, {"pageid": 12345}]
    with pytest.raises(w.WikipediaSemanticIncomplete, match="never requested"):
        w.require_every_identity_accounted([9228], rows, key="pageid", url=URL)


def test_a_row_without_an_integer_identity_is_refused():
    """Schema drift. If MediaWiki ever returns pageid as a string, the set
    comparison would silently match nothing and every page would look missing."""
    with pytest.raises(w.WikipediaSemanticIncomplete, match="no integer pageid"):
        w.require_every_identity_accounted([9228], [{"pageid": "9228"}], key="pageid", url=URL)


def test_an_empty_pages_list_against_a_real_request_is_refused():
    with pytest.raises(w.WikipediaSemanticIncomplete, match="absent from the response"):
        w.require_every_identity_accounted([9228], [], key="pageid", url=URL)


# --- continuation ------------------------------------------------------------


def test_a_batch_that_did_not_declare_itself_complete_is_refused():
    """`batchcomplete` absent means a continuation exists. Treating a partial
    batch as the whole answer is the silent truncation this study keeps paying
    for, so it refuses rather than continuing."""
    with pytest.raises(w.WikipediaSemanticIncomplete, match="did not declare itself complete"):
        w.require_batch_complete(CONTINUING_BATCH, url=URL)


def test_a_complete_batch_passes():
    w.require_batch_complete(GOOD_BATCH, url=URL)


# --- the defect itself, as a check rather than a comment ---------------------


def test_the_repaired_request_carries_no_rvlimit():
    url = w.latest_revision_url([9228, 22939])
    assert "rvlimit" not in url
    w.forbids_rvlimit_with_multiple_pages(url)


def test_reconstructing_sfir5s_request_is_refused():
    """The defect cannot be re-introduced silently. This asserts the shape is
    rejected, not merely that today's code happens not to build it."""
    with pytest.raises(w.WikipediaSemanticIncomplete, match="single page"):
        w.forbids_rvlimit_with_multiple_pages(
            "https://en.wikipedia.org/w/api.php?pageids=9228%7C22939&rvlimit=2"
        )


def test_rvlimit_on_a_single_page_is_not_flagged():
    """The paired positive: `rvlimit` is legal on one page. A check that refused
    it everywhere would be wrong about the API rather than strict."""
    w.forbids_rvlimit_with_multiple_pages(
        "https://en.wikipedia.org/w/api.php?pageids=9228&rvlimit=2"
    )


@pytest.mark.parametrize("size", [0, w.MAX_IDS_PER_REQUEST + 1])
def test_a_batch_outside_the_apis_own_limit_is_refused(size):
    """MediaWiki truncates an over-long multi-value parameter, and a truncation
    nobody notices is exactly this incident. Refused before it is sent."""
    with pytest.raises(w.WikipediaSemanticIncomplete, match="outside"):
        w.latest_revision_url(list(range(1, size + 1)))


# --- pair construction -------------------------------------------------------


def test_a_page_whose_latest_revision_has_no_parent_yields_no_pair():
    """A page with exactly one revision in its history. That is a fact about the
    page, not a failure, so it is skipped rather than refused."""
    page = {"pageid": 1, "revisions": [{"revid": 5, "parentid": 0}]}
    assert w.pair_from(page, {}) is None


def test_a_redirect_yields_no_pair():
    page = {"pageid": 1, "redirect": True, "revisions": [{"revid": 5, "parentid": 4}]}
    assert w.pair_from(page, {}) is None


def test_an_unresolved_parent_is_refused_rather_than_skipped():
    """The difference that matters. A page with no parent is skipped; a parent
    that was requested and never came back is a hole in the evidence chain, and
    skipping it would quietly shrink the cohort."""
    page = {"pageid": 1, "revisions": [{"revid": 5, "parentid": 4}]}
    with pytest.raises(w.WikipediaSemanticIncomplete, match="never resolved"):
        w.pair_from(page, {})


def test_a_resolved_pair_carries_both_ids_and_both_timestamps():
    page = {
        "pageid": 1,
        "revisions": [{"revid": 5, "parentid": 4, "timestamp": "2026-01-02T00:00:00Z"}],
    }
    parents = {4: {"revid": 4, "timestamp": "2026-01-01T00:00:00Z"}}
    pair = w.pair_from(page, parents)
    assert pair == {
        "revision_before": "4",
        "revision_after": "5",
        "timestamp_before": "2026-01-01T00:00:00Z",
        "timestamp_after": "2026-01-02T00:00:00Z",
    }


# --- what SFIR6 carries forward unchanged ------------------------------------


def test_the_selection_ordering_is_the_frozen_one():
    """SFIR6 repairs the instrument, not the selection. Same salt, same material,
    same ordering -- so a candidate's rank does not depend on which study asked."""
    import hashlib

    expected = hashlib.sha256(
        (sources.SELECTION_SALT + "\0" + "Astronomy" + "\0" + "12345").encode("utf-8")
    ).hexdigest()
    assert w.selection_rank("Astronomy", 12345) == expected


def test_the_declared_roots_and_caps_are_untouched():
    pool = sources.SOURCE_POOLS["encyclopedia_wikipedia"]
    assert len(pool["category_roots"]) == 30
    assert pool["max_candidates_per_category"] == 150
    assert pool["category_page_size"] == 500
