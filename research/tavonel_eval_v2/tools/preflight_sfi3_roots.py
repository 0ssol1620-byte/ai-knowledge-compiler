#!/usr/bin/env python3
"""Availability-only network preflight for `acquisition/sources_sfi3.py`'s 78
fresh roots (32 `GIT_ROOTS`, 36 `ECFR_ROOTS`, 10 `WIKIPEDIA_CATEGORY_ROOTS`).

Founder framing: none of the 78 roots has ever been checked for existence.
This tool checks identity and reachability only — never content:

    PERMITTED   does the root exist? is it reachable? expected host / family?
                redirected or deleted? is the identifier syntactically valid?
    FORBIDDEN   opening or reading any revision content; searching for
                qualifying transitions; inspecting what changed in any
                revision; estimating yield; choosing "good" pairs; checking
                any fact or value transition.

That boundary is not merely a rule this module follows — it is structural,
through three independent layers:

* every URL this module ever calls is validated against a hardcoded regex
  (`_GIT_REPO_URL`, `_GIT_CONTENTS_URL`, `_ECFR_URL`, `_WIKI_URL`) before the
  request leaves, and every one of those patterns excludes the endpoints that
  would return revision or article content: eCFR's `/full/...xml` and
  Wikipedia's `action=parse` / `rvprop=content` are refused by shape alone.
  `_GIT_CONTENTS_URL` is shape-compatible with GitHub's Contents API for both
  a directory and a single file — the API uses one route for both — so the
  URL whitelist alone cannot distinguish them; the type check below is what
  does. A future edit that pointed an eCFR or Wikipedia checker at a content
  endpoint would fail its own assertion before the request left;
* `check_git_root` only ever calls that route with the declared `prefix`
  (always a directory in every real `GIT_ROOTS` entry, never a filename), and
  only accepts the response as a reachable root when the parsed body is a
  JSON *array* (`isinstance(listing, list)`) — the shape GitHub returns for a
  directory listing of names/paths/shas. A single file's response is a JSON
  *object* carrying a base64 `content` field; that shape fails the array
  check and is classified `NOT_FOUND` without ever reading the `content` key,
  regardless of what the body contains;
* every response is read through a size-bounded reader
  (`MAX_RESPONSE_BYTES`), sized against real, observed existence/identity
  metadata bodies — including a large directory listing, still bytes of
  names and shas, never article or regulation text. A response that exceeds
  it is never parsed for fields; it is reported `UNREACHABLE` with the guard
  named as the reason;
* every parser extracts a small, named, whitelisted set of scalar fields
  (existence flags, host, branch name, archived/disabled booleans, category
  namespace) and returns only those. The parsed body itself is discarded
  immediately after extraction and never stored on the returned record —
  there is no code path from "the wire" to "the receipt" that does not pass
  through one of these narrow extractors.

`tests/test_sfi3_root_preflight.py` asserts this from the outside: every URL
this module would build for every real root in `sources_sfi3.py` is checked
against the same regexes, a fetch stubbed to return a body carrying an
injected long "content"-shaped field is asserted to leave no trace of that
field in the returned record, and a GitHub contents response shaped like a
single file (an object with a base64 `content` field, not an array) is
asserted to be refused rather than read.

This module reads `acquisition/sources_sfi3.py` and never writes to it, and it
does not touch `tools/freeze_sfi3_lineages.py` or any receipt. It does not
freeze the frame — the founder's routing instructions are explicit that this
tool's job ends at "is a root reachable", and that the frame freeze is the
orchestrator's next, separate step.

GitHub's unauthenticated rate limit (60 requests/hour) does not comfortably
cover 32 repo-existence checks plus 32 prefix-reachability checks in one run
alongside whatever else shares that budget; `GITHUB_TOKEN`/`GH_TOKEN` is read
from the environment, exactly as `acquisition/fetch_p4g_corpus.py` already
does, to move onto the 5,000/hour authenticated limit. The token is used only
as a request header and is never written to any record this module returns.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import live_cohort_guard

TOOLS = Path(__file__).resolve().parent
NS = TOOLS.parent
for _sub in ("acquisition", "tools"):
    sys.path.insert(0, str(NS / _sub))

import sources_sfi3 as sfi3  # noqa: E402  -- read-only; never modified or frozen here
from common import now  # noqa: E402
from evidence import write_immutable  # noqa: E402

SCHEMA = "tavonel.v2.sfi3_root_preflight.v1"
USER_AGENT = "tavonel-sfi3-root-preflight/1.0 (availability check only)"

#: Sized against the real APIs, observed directly in this session
#: (2026-08-23): a GitHub repo-metadata body was ~6 KB, an eCFR part version
#: list ~30 KB, and a GitHub directory listing ranged up to ~283 KB for a very
#: large documentation tree (`quarkusio/quarkus`'s `docs/src/main/asciidoc/`,
#: several thousand files' worth of names, paths and shas — no content). The
#: first cap tried here (256 KiB) was tight enough to truncate that real,
#: legitimate listing and misclassify a reachable root as unreachable; 1 MiB
#: leaves several times that much headroom for even a very large directory
#: while remaining far below what a full document body (an eCFR title's XML
#: text, a parsed Wikipedia article, a single file's base64 content) would
#: be — so exceeding it is still itself a signal something other than an
#: existence check was reached, not a reason to read further.
MAX_RESPONSE_BYTES = 1_048_576

# ---------------------------------------------------------------------------
# states — never a bare boolean
# ---------------------------------------------------------------------------

STATE_VALID = "VALID"
STATE_REDIRECTED = "REDIRECTED"
STATE_NOT_FOUND = "NOT_FOUND"
STATE_UNREACHABLE = "UNREACHABLE"
STATE_INVALID_IDENTIFIER = "INVALID_IDENTIFIER"
STATE_UNEXPECTED_HOST = "UNEXPECTED_HOST"

ROOT_STATES: tuple[str, ...] = (
    STATE_VALID,
    STATE_REDIRECTED,
    STATE_NOT_FOUND,
    STATE_UNREACHABLE,
    STATE_INVALID_IDENTIFIER,
    STATE_UNEXPECTED_HOST,
)

#: States a root's existence was actually confirmed under. `REDIRECTED` counts
#: — the root answered and identified itself — but is kept visible as its own
#: state rather than folded silently into `VALID`, per "redirected or
#: deleted?" being its own named question.
CONFIRMED_STATES = frozenset({STATE_VALID, STATE_REDIRECTED})

FAMILY_GIT = "git_docs"
FAMILY_ECFR = "regulation_ecfr"
FAMILY_WIKIPEDIA = "encyclopedia_wikipedia"

#: A floor between requests to one host, seconds. Reuses the values
#: `acquisition/http_pool.py` already declares for these same hosts rather
#: than choosing new ones — this is a much smaller, sequential run, but the
#: politeness basis (each provider's published guidance) does not change with
#: the caller.
_HOST_MIN_INTERVAL = {
    "api.github.com": 0.05,
    "www.ecfr.gov": 0.20,
    "en.wikipedia.org": 0.05,
}

# ---------------------------------------------------------------------------
# syntactic validation — before any network call
# ---------------------------------------------------------------------------

_GITHUB_NAME = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$")
_CFR_TITLE = re.compile(r"^([1-9]|[1-4][0-9]|50)$")  # CFR titles are 1-50
_CFR_PART = re.compile(r"^\d{1,4}$")
_WIKI_CATEGORY = re.compile(r"^Category:\S.*$")

# ---------------------------------------------------------------------------
# the only URL shapes this module will ever request — content endpoints are
# excluded by construction, and every URL built below is asserted against one
# of these before the request leaves `_bounded_get`.
# ---------------------------------------------------------------------------

_GIT_REPO_URL = re.compile(r"^https://api\.github\.com/repos/[^/]+/[^/]+$")
_GIT_CONTENTS_URL = re.compile(r"^https://api\.github\.com/repos/[^/]+/[^/]+/contents/[^?]*$")
#: Deliberately excludes `/full/` — that is the endpoint that returns the
#: actual regulation text and this module must never call it.
_ECFR_URL = re.compile(
    r"^https://www\.ecfr\.gov/api/versioner/v1/versions/title-\d{1,4}\.json\?part=\d{1,4}$"
)
#: `prop=info` only — deliberately excludes `action=parse` and any
#: `rvprop=content`/`prop=revisions` variant, which is where article text
#: would come from.
_WIKI_URL = re.compile(
    r"^https://en\.wikipedia\.org/w/api\.php\?action=query&titles=[^&]+&prop=info&format=json$"
)

_ALLOWED_URL_PATTERNS = (_GIT_REPO_URL, _GIT_CONTENTS_URL, _ECFR_URL, _WIKI_URL)


def url_is_existence_only(url: str) -> bool:
    """True if `url` matches one of the declared existence-only shapes.

    Exposed so the test suite can assert this against every URL this module
    would build for every real declared root, without needing the network.
    """
    return any(pattern.match(url) for pattern in _ALLOWED_URL_PATTERNS)


class ContentEndpointRefused(RuntimeError):
    """Raised if a caller ever builds a URL outside the declared whitelist.

    Not expected to be reachable through this module's own checkers — it is
    the structural backstop `tests/test_sfi3_root_preflight.py` names in the
    module docstring: a future edit to a URL template fails here, at the
    request boundary, rather than merely fetching more than intended.
    """


# ---------------------------------------------------------------------------
# bounded, whitelisted-URL-only transport
# ---------------------------------------------------------------------------


def _github_headers() -> dict[str, str]:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = "Bearer " + token
    return headers


def _bounded_read(response: Any, limit: int) -> tuple[bytes, bool]:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = response.read(min(65536, limit + 1 - total))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > limit:
            break
    data = b"".join(chunks)
    return data[:limit], total > limit


def _bounded_get(
    url: str, *, headers: dict[str, str] | None = None, timeout: int = 20
) -> dict[str, Any]:
    """One GET against a pre-whitelisted URL. Never retried, never followed past
    the size guard. Returns status/final_url/body-or-None/reason; never the
    unbounded raw response.
    """
    if not url_is_existence_only(url):
        raise ContentEndpointRefused(
            f"refusing to fetch {url!r}: it does not match any declared existence-only URL shape"
        )
    # `url` is checked against the hardcoded existence-only whitelist above
    # before this point is reached, so it is never an arbitrary caller-
    # supplied scheme (no `file:`, no unexpected host) — the audit S310 flags
    # is exactly the property `url_is_existence_only` already enforces.
    request = urllib.request.Request(  # noqa: S310
        url, headers=headers or {"User-Agent": USER_AGENT}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            body, truncated = _bounded_read(response, MAX_RESPONSE_BYTES)
            if truncated:
                return {
                    "status": response.status,
                    "final_url": response.geturl(),
                    "body": None,
                    "reason": (
                        f"response exceeded the {MAX_RESPONSE_BYTES}-byte existence-check "
                        "guard; not read further and not parsed"
                    ),
                }
            return {
                "status": response.status,
                "final_url": response.geturl(),
                "body": body,
                "reason": "",
            }
    except urllib.error.HTTPError as error:
        return {
            "status": error.code,
            "final_url": getattr(error, "url", url) or url,
            "body": None,
            "reason": f"{type(error).__name__}: {error}",
        }
    except Exception as error:  # any transport failure is UNREACHABLE
        return {
            "status": 0,
            "final_url": url,
            "body": None,
            "reason": f"{type(error).__name__}: {error}",
        }


def _sleep_for_host(host: str) -> None:
    time.sleep(_HOST_MIN_INTERVAL.get(host, 0.05))


# ---------------------------------------------------------------------------
# one record shape, every family
# ---------------------------------------------------------------------------


def _record(
    *,
    family: str,
    root_id: str,
    state: str,
    reason: str,
    expected_host: str,
    url_checked: str | None = None,
    final_url: str | None = None,
    http_status: int | None = None,
    identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "family": family,
        "root_id": root_id,
        "state": state,
        "confirmed_to_exist": state in CONFIRMED_STATES,
        "reason": reason,
        "expected_host": expected_host,
        "url_checked": url_checked,
        "final_url": final_url,
        "redirected": bool(
            url_checked and final_url and _strip_query(url_checked) != _strip_query(final_url)
        ),
        "http_status": http_status,
        #: whitelisted identity fields only — never a pass-through of the
        #: fetched body. See the module docstring's "structural" bullets.
        "identity": identity or {},
    }


def _strip_query(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _classify_transport_failure(status: int, reason: str) -> str:
    if status == 404:
        return STATE_NOT_FOUND
    return STATE_UNREACHABLE


# ---------------------------------------------------------------------------
# git_docs
# ---------------------------------------------------------------------------


def check_git_root(root: dict[str, str]) -> dict[str, Any]:
    owner, repo, prefix = root["owner"], root["repo"], root["prefix"]
    root_id = f"{owner}/{repo}"
    if not (_GITHUB_NAME.match(owner) and _GITHUB_NAME.match(repo) and prefix.endswith("/")):
        return _record(
            family=FAMILY_GIT,
            root_id=root_id,
            state=STATE_INVALID_IDENTIFIER,
            reason="owner, repo or prefix failed the declared GitHub naming/shape check",
            expected_host="api.github.com",
        )

    headers = _github_headers()
    repo_url = f"https://api.github.com/repos/{owner}/{repo}"
    _sleep_for_host("api.github.com")
    repo_resp = _bounded_get(repo_url, headers=headers)
    host = urllib.parse.urlparse(repo_resp["final_url"]).netloc

    if repo_resp["body"] is None:
        return _record(
            family=FAMILY_GIT,
            root_id=root_id,
            state=_classify_transport_failure(repo_resp["status"], repo_resp["reason"]),
            reason=repo_resp["reason"] or f"HTTP {repo_resp['status']}",
            expected_host="api.github.com",
            url_checked=repo_url,
            final_url=repo_resp["final_url"],
            http_status=repo_resp["status"],
        )
    if host != "api.github.com":
        return _record(
            family=FAMILY_GIT,
            root_id=root_id,
            state=STATE_UNEXPECTED_HOST,
            reason=f"resolved host {host!r}, expected api.github.com",
            expected_host="api.github.com",
            url_checked=repo_url,
            final_url=repo_resp["final_url"],
            http_status=repo_resp["status"],
        )
    try:
        meta = json.loads(repo_resp["body"])
    except json.JSONDecodeError as error:
        return _record(
            family=FAMILY_GIT,
            root_id=root_id,
            state=STATE_UNREACHABLE,
            reason=f"repo metadata did not parse as JSON: {error}",
            expected_host="api.github.com",
            url_checked=repo_url,
            final_url=repo_resp["final_url"],
            http_status=repo_resp["status"],
        )
    #: whitelist only — the rest of `meta` (description, topics, owner
    #: avatar, ...) is discarded here and never reaches the returned record.
    identity = {
        "full_name": meta.get("full_name"),
        "private": meta.get("private"),
        "archived": meta.get("archived"),
        "disabled": meta.get("disabled"),
        "default_branch": meta.get("default_branch"),
    }
    if not meta.get("id") or str(identity.get("full_name", "")).lower() != root_id.lower():
        return _record(
            family=FAMILY_GIT,
            root_id=root_id,
            state=STATE_NOT_FOUND,
            reason="repository metadata carried no id / full_name match",
            expected_host="api.github.com",
            url_checked=repo_url,
            final_url=repo_resp["final_url"],
            http_status=repo_resp["status"],
            identity=identity,
        )

    contents_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{prefix.rstrip('/')}"
    _sleep_for_host("api.github.com")
    contents_resp = _bounded_get(contents_url, headers=headers)
    prefix_reachable = False
    if contents_resp["body"] is not None:
        try:
            listing = json.loads(contents_resp["body"])
            prefix_reachable = isinstance(listing, list) and len(listing) > 0
        except json.JSONDecodeError:
            prefix_reachable = False
    identity["prefix_reachable"] = prefix_reachable
    identity["prefix_http_status"] = contents_resp["status"]

    if not prefix_reachable:
        return _record(
            family=FAMILY_GIT,
            root_id=root_id,
            state=STATE_NOT_FOUND,
            reason=(
                f"repository exists but declared prefix {prefix!r} did not resolve to a "
                "non-empty directory listing "
                f"({contents_resp['reason'] or contents_resp['status']})"
            ),
            expected_host="api.github.com",
            url_checked=repo_url,
            final_url=repo_resp["final_url"],
            http_status=repo_resp["status"],
            identity=identity,
        )

    redirected = _strip_query(repo_url) != _strip_query(repo_resp["final_url"]) or _strip_query(
        contents_url
    ) != _strip_query(contents_resp["final_url"])
    return _record(
        family=FAMILY_GIT,
        root_id=root_id,
        state=STATE_REDIRECTED if redirected else STATE_VALID,
        reason="repository and declared prefix both resolved",
        expected_host="api.github.com",
        url_checked=repo_url,
        final_url=repo_resp["final_url"],
        http_status=repo_resp["status"],
        identity=identity,
    )


# ---------------------------------------------------------------------------
# regulation_ecfr
# ---------------------------------------------------------------------------


def check_ecfr_root(root: tuple[str, str, str]) -> dict[str, Any]:
    title, part, _description = root
    root_id = f"title-{title}-part-{part}"
    if not (_CFR_TITLE.match(title) and _CFR_PART.match(part)):
        return _record(
            family=FAMILY_ECFR,
            root_id=root_id,
            state=STATE_INVALID_IDENTIFIER,
            reason="title or part failed the declared CFR shape check",
            expected_host="www.ecfr.gov",
        )

    url = f"https://www.ecfr.gov/api/versioner/v1/versions/title-{title}.json?part={part}"
    _sleep_for_host("www.ecfr.gov")
    resp = _bounded_get(url)
    host = urllib.parse.urlparse(resp["final_url"]).netloc

    if resp["body"] is None:
        return _record(
            family=FAMILY_ECFR,
            root_id=root_id,
            state=_classify_transport_failure(resp["status"], resp["reason"]),
            reason=resp["reason"] or f"HTTP {resp['status']}",
            expected_host="www.ecfr.gov",
            url_checked=url,
            final_url=resp["final_url"],
            http_status=resp["status"],
        )
    if host != "www.ecfr.gov":
        return _record(
            family=FAMILY_ECFR,
            root_id=root_id,
            state=STATE_UNEXPECTED_HOST,
            reason=f"resolved host {host!r}, expected www.ecfr.gov",
            expected_host="www.ecfr.gov",
            url_checked=url,
            final_url=resp["final_url"],
            http_status=resp["status"],
        )
    try:
        body = json.loads(resp["body"])
    except json.JSONDecodeError as error:
        return _record(
            family=FAMILY_ECFR,
            root_id=root_id,
            state=STATE_UNREACHABLE,
            reason=f"versions listing did not parse as JSON: {error}",
            expected_host="www.ecfr.gov",
            url_checked=url,
            final_url=resp["final_url"],
            http_status=resp["status"],
        )
    #: existence only: whether the part has ANY recorded version at all.
    #: `content_versions`'s entries (dates, identifiers) are never read past
    #: this boolean and never stored — reading them would be reading toward
    #: revision history, which this module does not do.
    has_versions = bool(body.get("content_versions"))
    identity = {"has_content_versions": has_versions}
    if not has_versions:
        return _record(
            family=FAMILY_ECFR,
            root_id=root_id,
            state=STATE_NOT_FOUND,
            reason="title/part resolved but carries no recorded content_versions",
            expected_host="www.ecfr.gov",
            url_checked=url,
            final_url=resp["final_url"],
            http_status=resp["status"],
            identity=identity,
        )
    redirected = _strip_query(url) != _strip_query(resp["final_url"])
    return _record(
        family=FAMILY_ECFR,
        root_id=root_id,
        state=STATE_REDIRECTED if redirected else STATE_VALID,
        reason="title/part resolved with at least one recorded version",
        expected_host="www.ecfr.gov",
        url_checked=url,
        final_url=resp["final_url"],
        http_status=resp["status"],
        identity=identity,
    )


# ---------------------------------------------------------------------------
# encyclopedia_wikipedia
# ---------------------------------------------------------------------------


def check_wikipedia_root(category: str) -> dict[str, Any]:
    root_id = category
    if not _WIKI_CATEGORY.match(category):
        return _record(
            family=FAMILY_WIKIPEDIA,
            root_id=root_id,
            state=STATE_INVALID_IDENTIFIER,
            reason="category name did not start with 'Category:' plus a non-empty name",
            expected_host="en.wikipedia.org",
        )

    encoded = urllib.parse.quote(category, safe="")
    url = f"https://en.wikipedia.org/w/api.php?action=query&titles={encoded}&prop=info&format=json"
    _sleep_for_host("en.wikipedia.org")
    resp = _bounded_get(url)
    host = urllib.parse.urlparse(resp["final_url"]).netloc

    if resp["body"] is None:
        return _record(
            family=FAMILY_WIKIPEDIA,
            root_id=root_id,
            state=_classify_transport_failure(resp["status"], resp["reason"]),
            reason=resp["reason"] or f"HTTP {resp['status']}",
            expected_host="en.wikipedia.org",
            url_checked=url,
            final_url=resp["final_url"],
            http_status=resp["status"],
        )
    if host != "en.wikipedia.org":
        return _record(
            family=FAMILY_WIKIPEDIA,
            root_id=root_id,
            state=STATE_UNEXPECTED_HOST,
            reason=f"resolved host {host!r}, expected en.wikipedia.org",
            expected_host="en.wikipedia.org",
            url_checked=url,
            final_url=resp["final_url"],
            http_status=resp["status"],
        )
    try:
        body = json.loads(resp["body"])
    except json.JSONDecodeError as error:
        return _record(
            family=FAMILY_WIKIPEDIA,
            root_id=root_id,
            state=STATE_UNREACHABLE,
            reason=f"query response did not parse as JSON: {error}",
            expected_host="en.wikipedia.org",
            url_checked=url,
            final_url=resp["final_url"],
            http_status=resp["status"],
        )
    pages = body.get("query", {}).get("pages", {})
    page = next(iter(pages.values()), {})
    #: whitelist only: existence + namespace (14 == Category). `length`,
    #: `touched`, `lastrevid` are revision-adjacent and are deliberately never
    #: read out of `page` here.
    exists = "missing" not in page and bool(page.get("pageid"))
    is_category_ns = page.get("ns") == 14
    identity = {"pageid_present": exists, "namespace_is_category": is_category_ns}
    if not exists or not is_category_ns:
        return _record(
            family=FAMILY_WIKIPEDIA,
            root_id=root_id,
            state=STATE_NOT_FOUND,
            reason="category page missing or not in the Category namespace",
            expected_host="en.wikipedia.org",
            url_checked=url,
            final_url=resp["final_url"],
            http_status=resp["status"],
            identity=identity,
        )
    redirected = _strip_query(url) != _strip_query(resp["final_url"])
    return _record(
        family=FAMILY_WIKIPEDIA,
        root_id=root_id,
        state=STATE_REDIRECTED if redirected else STATE_VALID,
        reason="category page exists in the Category namespace",
        expected_host="en.wikipedia.org",
        url_checked=url,
        final_url=resp["final_url"],
        http_status=resp["status"],
        identity=identity,
    )


# ---------------------------------------------------------------------------
# the full 78-root run
# ---------------------------------------------------------------------------


def run() -> dict[str, Any]:
    # INC-V2-100. Reaches a live cohort; a stray call from a test
    # runner would spend real budget and OBSERVE. `sys.modules` and not
    # PYTEST_CURRENT_TEST, so an import-time call is guarded too.
    if "pytest" in sys.modules or "unittest" in sys.modules:
        live_cohort_guard.refuse_under_test("preflight_sfi3_roots.run")
    started = now()
    records: list[dict[str, Any]] = []
    records.extend(check_git_root(root) for root in sfi3.GIT_ROOTS)
    records.extend(check_ecfr_root(root) for root in sfi3.ECFR_ROOTS)
    records.extend(check_wikipedia_root(category) for category in sfi3.WIKIPEDIA_CATEGORY_ROOTS)

    declared_totals = {
        FAMILY_GIT: len(sfi3.GIT_ROOTS),
        FAMILY_ECFR: len(sfi3.ECFR_ROOTS),
        FAMILY_WIKIPEDIA: len(sfi3.WIKIPEDIA_CATEGORY_ROOTS),
    }
    by_family_state: dict[str, dict[str, int]] = {
        family: {state: 0 for state in ROOT_STATES} for family in declared_totals
    }
    invalid_by_family: dict[str, list[dict[str, Any]]] = {family: [] for family in declared_totals}
    for record in records:
        by_family_state[record["family"]][record["state"]] += 1
        if not record["confirmed_to_exist"]:
            invalid_by_family[record["family"]].append(
                {"root_id": record["root_id"], "state": record["state"], "reason": record["reason"]}
            )

    valid_count_per_family = {
        family: sum(count for state, count in states.items() if state in CONFIRMED_STATES)
        for family, states in by_family_state.items()
    }

    zero_valid_families = [family for family, count in valid_count_per_family.items() if count == 0]
    structural_floor_note = (
        "the 200-pair floor cannot be reached if any declared family has zero "
        f"confirmed-reachable roots: {zero_valid_families or 'none did'}. Beyond that "
        "degenerate case, this preflight makes no floor-feasibility claim — whether a "
        "PARTIAL root loss (some roots invalid, some valid) still leaves the floor "
        "reachable depends on how many lineages each surviving root supplies, which is "
        "yield estimation and is explicitly out of scope for an availability-only check; "
        "that determination belongs to the frame freeze and cohort build, after this."
    )

    return {
        "schema": SCHEMA,
        "started_at": started,
        "ended_at": now(),
        "scope": "identity and reachability only — no revision content opened, no yield estimated",
        "declared_totals": declared_totals,
        "total_roots": sum(declared_totals.values()),
        "by_family_state": by_family_state,
        "valid_root_count_per_family": valid_count_per_family,
        "invalid_roots_by_family": invalid_by_family,
        "zero_valid_families": zero_valid_families,
        "floor": sfi3.FLOOR,
        "family_quota": dict(sfi3.FAMILY_QUOTA),
        "structural_floor_note": structural_floor_note,
        "replacement_rule": (
            "if a root must be replaced, it is replaced using only a pre-declared "
            "availability criterion (this receipt's state per root) — never content, "
            "quality or expected yield. Replacement itself is not performed by this tool."
        ),
        "records": records,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-receipt",
        action="store_true",
        help="print the run result without writing an immutable receipt",
    )
    args = parser.parse_args(argv)

    result = run()

    if args.no_receipt:
        summary = {k: v for k, v in result.items() if k != "records"}
        print(json.dumps(summary, indent=2))
        return 0

    written = write_immutable(
        "sfi3-root-preflight",
        result,
        tool=Path(__file__).resolve(),
        protocol=None,
    )
    summary = {
        **written,
        "valid_root_count_per_family": result["valid_root_count_per_family"],
        "declared_totals": result["declared_totals"],
        "zero_valid_families": result["zero_valid_families"],
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
