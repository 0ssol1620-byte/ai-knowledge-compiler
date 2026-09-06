#!/usr/bin/env python3
"""SFIR6's Wikipedia adapter. Three gates, because HTTP 200 is not success.

INC-V2-106: the bound adapter sent 50 page ids together with `rvlimit=2`.
MediaWiki refuses that combination -- `rvlimit` "may only be used on a single
page" -- and answers **HTTP 200** with an `error` object and no `query` at all.
Every revision request this programme ever issued to Wikipedia was rejected, in
every SFIR study, and no Wikipedia candidate has ever existed.

The structural lesson, which this module exists to encode, is that one adapter
was checking one thing where there are three:

    transport success    the bytes arrived      (status, length, digest)
    protocol success     the API said yes       (no error, no warnings envelope)
    semantic completeness we got what we asked for (every id accounted for)

They are separate gates here, and each can refuse on its own. SFIR5's adapter
had the first, inferred the second from it, and approximated the third with a
set comparison that could only fire after the second had already silently
failed. Measured failure envelopes, all returned with HTTP 200:

    multiple pageids + rvlimit    -> {"error": {"code": "invalidparammix"}}, no query
    a page id that does not exist -> {"pages": [{"missing": true, ...}]}, no error
    a revision id that is bogus   -> {"query": {"badrevids": {...}}}, no error

## The batching, and why it is legal

The founder's instruction was to prefer officially supported batching and to
fall back to one request per page only if necessary. It is not necessary. The
supported form is two batched passes, verified against the live endpoint before
this module was written:

    pass 1  pageids=<=50 & prop=revisions & rvprop=ids|timestamp   (NO rvlimit)
            -> the latest revision of each page, carrying `parentid`
    pass 2  revids=<the parent ids> & prop=revisions & rvprop=ids|timestamp
            -> those parent revisions, carrying their timestamps

Two requests per fifty pages rather than one per page: roughly 180 requests for
the declared frame instead of 4,500, which is what makes a paced census fit
inside a finite wall-clock budget at all.

`rvlimit` is never sent with more than one page. It is not sent at all.
"""

from __future__ import annotations

import hashlib
import sys
import urllib.parse
from collections.abc import Mapping
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

from acquisition import sources_sfir4 as sources  # noqa: E402

API = "https://en.wikipedia.org/w/api.php"

#: MediaWiki's own limit for an anonymous multi-value parameter. Sending more is
#: not an efficiency question -- the API truncates or refuses, and a truncation
#: that nobody notices is the defect this module exists to prevent.
MAX_IDS_PER_REQUEST = 50


class WikipediaProtocolError(RuntimeError):
    """The API answered, and what it said was a refusal. HTTP status irrelevant."""


class WikipediaSemanticIncomplete(RuntimeError):
    """The API said yes and did not return what was asked for."""


# --- gate 2: protocol success -------------------------------------------------


def require_protocol_success(body: object, *, url: str) -> Mapping[str, Any]:
    """The API-level gate. Fail closed on anything that is not a plain success.

    `warnings` is treated as a refusal rather than as advice. MediaWiki emits it
    when it has silently altered a request -- truncated a multi-value parameter,
    ignored a property, applied a limit. Every one of those means the response
    describes a different question from the one asked, which is precisely the
    class of failure that hid for four studies.
    """
    if not isinstance(body, Mapping):
        raise WikipediaProtocolError(f"response is not a JSON object: {url}")
    if "error" in body:
        error = body["error"]
        code = error.get("code") if isinstance(error, Mapping) else "unknown"
        raise WikipediaProtocolError(f"MediaWiki error envelope: {code}")
    if "warnings" in body:
        raise WikipediaProtocolError(f"MediaWiki warnings envelope: {sorted(body['warnings'])}")
    query = body.get("query")
    if not isinstance(query, Mapping):
        raise WikipediaProtocolError("response carries no query block")
    bad = query.get("badrevids")
    if bad:
        raise WikipediaProtocolError(f"MediaWiki reports bad revision ids: {sorted(bad)}")
    return query


# --- gate 3: semantic completeness -------------------------------------------


def require_batch_complete(body: Mapping[str, Any], *, url: str) -> None:
    """A batched query must declare itself complete.

    `batchcomplete` is MediaWiki saying it answered for every input. Its absence
    on a batched request means a continuation exists, and continuing is not
    implemented here on purpose: a partial batch must refuse rather than be
    quietly treated as the whole answer.
    """
    if not body.get("batchcomplete"):
        raise WikipediaSemanticIncomplete(f"batch did not declare itself complete: {url}")


def require_every_identity_accounted(
    requested: list[int], returned: list[Mapping[str, Any]], *, key: str, url: str
) -> dict[str, list[int]]:
    """Every id asked for must come back as present or explicitly absent.

    Returns the accounting rather than a bare pass, so a caller records what was
    excluded instead of discovering a smaller list later. "No silent truncation"
    means the exclusions are written down, not that there are none.
    """
    if len(set(requested)) != len(requested):
        raise WikipediaSemanticIncomplete(f"duplicate ids in the request itself: {url}")
    present: list[int] = []
    absent: list[int] = []
    seen: set[int] = set()
    for row in returned:
        if not isinstance(row, Mapping) or not isinstance(row.get(key), int):
            raise WikipediaSemanticIncomplete(f"response row has no integer {key}: {url}")
        value = int(row[key])
        if value in seen:
            raise WikipediaSemanticIncomplete(f"duplicate {key} {value} in response: {url}")
        seen.add(value)
        (absent if (row.get("missing") or row.get("invalid")) else present).append(value)
    unaccounted = sorted(set(requested) - seen)
    if unaccounted:
        raise WikipediaSemanticIncomplete(
            f"{len(unaccounted)} requested {key}s absent from the response entirely "
            f"(first: {unaccounted[:5]}): {url}"
        )
    extra = sorted(seen - set(requested))
    if extra:
        raise WikipediaSemanticIncomplete(f"response carries {key}s never requested: {extra[:5]}")
    return {"present": sorted(present), "absent": sorted(absent)}


# --- request construction ----------------------------------------------------


def _url(params: Mapping[str, Any]) -> str:
    return API + "?" + urllib.parse.urlencode({**params, "format": "json", "formatversion": 2})


def category_url(category: str, *, size: int, continuation: str | None = None) -> str:
    params: dict[str, Any] = {
        "action": "query",
        "list": "categorymembers",
        "cmtitle": f"Category:{category}",
        "cmlimit": size,
        "cmnamespace": sources.SOURCE_POOLS["encyclopedia_wikipedia"]["namespace"],
    }
    if continuation:
        params["cmcontinue"] = continuation
    return _url(params)


def latest_revision_url(page_ids: list[int]) -> str:
    """Pass 1. No `rvlimit` -- that is the parameter that made SFIR5 invalid."""
    if not page_ids or len(page_ids) > MAX_IDS_PER_REQUEST:
        raise WikipediaSemanticIncomplete(
            f"batch size {len(page_ids)} outside 1..{MAX_IDS_PER_REQUEST}"
        )
    return _url(
        {
            "action": "query",
            "pageids": "|".join(str(value) for value in page_ids),
            "prop": "revisions|info|redirects",
            "rvprop": "ids|timestamp",
            "rdlimit": "max",
        }
    )


def parent_revision_url(revision_ids: list[int]) -> str:
    """Pass 2, resolving the `parentid`s pass 1 returned into timestamps."""
    if not revision_ids or len(revision_ids) > MAX_IDS_PER_REQUEST:
        raise WikipediaSemanticIncomplete(
            f"batch size {len(revision_ids)} outside 1..{MAX_IDS_PER_REQUEST}"
        )
    return _url(
        {
            "action": "query",
            "revids": "|".join(str(value) for value in revision_ids),
            "prop": "revisions",
            "rvprop": "ids|timestamp",
        }
    )


def forbids_rvlimit_with_multiple_pages(url: str) -> None:
    """The specific refusal INC-V2-106 is about, as a callable check.

    Kept as its own function rather than as a comment, so a control can assert
    the defect cannot be reconstructed rather than asserting that today's code
    happens not to contain it.
    """
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    ids = query.get("pageids", [""])[0] or query.get("titles", [""])[0]
    if "rvlimit" in query and "|" in ids:
        raise WikipediaSemanticIncomplete(
            "rvlimit may only be used on a single page; MediaWiki answers "
            "invalidparammix with HTTP 200 (INC-V2-106)"
        )


def selection_rank(category: str, page_id: int) -> str:
    """Unchanged from the frozen adapter: SFIR6 repairs the instrument, not the
    selection. Same salt, same material, same ordering."""
    material = sources.SELECTION_SALT + "\0" + category + "\0" + str(page_id)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def pair_from(page: Mapping[str, Any], parents: Mapping[int, Mapping[str, Any]]):
    """Build one before/after pair, or None when the page cannot supply one.

    Returns None -- rather than refusing -- only for the two cases that are
    facts about the page and not about the request: a redirect, and a page whose
    latest revision has no parent because it has only ever had one revision.
    """
    revisions = page.get("revisions") or []
    if page.get("redirect") is True or not revisions:
        return None
    latest = revisions[0]
    parent_id = latest.get("parentid")
    if not parent_id:
        return None
    parent = parents.get(int(parent_id))
    if parent is None:
        raise WikipediaSemanticIncomplete(
            f"parent revision {parent_id} of page {page.get('pageid')} was requested "
            "but never resolved"
        )
    return {
        "revision_before": str(parent["revid"]),
        "revision_after": str(latest["revid"]),
        "timestamp_before": parent.get("timestamp"),
        "timestamp_after": latest.get("timestamp"),
    }
