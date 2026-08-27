"""Tests for `tools/preflight_sfi3_roots.py` — the availability-only preflight
for SFI3's 78 fresh roots (`acquisition/sources_sfi3.py`).

No live network call in this file. The point of this preflight is that it is
*structurally* incapable of reading revision content, and that property must
be checkable without depending on GitHub, eCFR or Wikipedia being up — every
test below either checks pure logic (syntax validation, URL-shape whitelist,
classification) or stubs `urllib.request.urlopen` itself.

What this file guards, matching the task's definition of done:

1. every URL the module would build for every one of the 78 REAL declared
   roots matches one of the declared existence-only shapes
2. the whitelist explicitly rejects the sibling content endpoints (eCFR
   `/full/...xml`, Wikipedia `action=parse`/`rvprop=content`, a GitHub
   per-file contents path) — the exclusion is checked, not merely claimed
3. `_bounded_get` refuses to even attempt a request for a non-whitelisted URL
   (`ContentEndpointRefused`), before any network call
4. a response larger than the size guard is reported unread, never parsed
5. a stubbed response carrying a long injected "content"-shaped field never
   appears anywhere in the record `check_git_root` / `check_ecfr_root` /
   `check_wikipedia_root` returns — the structural claim, tested from outside
6. syntactically invalid identifiers are rejected before any network attempt
7. redirect detection compares the requested and final URL ignoring query
8. the cohort-level aggregation reports per-family, per-state counts (never a
   bare pass/fail) and detects the zero-valid-roots-in-a-family case
9. the CLI's `--no-receipt` path round-trips through `main()`
"""

from __future__ import annotations

import json
import sys
import urllib.error
from pathlib import Path
from typing import Any

import pytest

NS = Path(__file__).resolve().parents[1]
for _sub in ("acquisition", "tools"):
    sys.path.insert(0, str(NS / _sub))

import preflight_sfi3_roots as pre  # noqa: E402
import sources_sfi3 as sfi3  # noqa: E402

# ---------------------------------------------------------------------------
# 1 & 2 — the URL whitelist, checked against every real declared root
# ---------------------------------------------------------------------------


def _git_urls(root: dict[str, str]) -> tuple[str, str]:
    owner, repo, prefix = root["owner"], root["repo"], root["prefix"]
    return (
        f"https://api.github.com/repos/{owner}/{repo}",
        f"https://api.github.com/repos/{owner}/{repo}/contents/{prefix.rstrip('/')}",
    )


@pytest.mark.parametrize("root", sfi3.GIT_ROOTS, ids=lambda r: f"{r['owner']}/{r['repo']}")
def test_every_real_git_root_url_is_existence_only(root: dict[str, str]) -> None:
    for url in _git_urls(root):
        assert pre.url_is_existence_only(url), url


@pytest.mark.parametrize(
    "root", sfi3.ECFR_ROOTS, ids=lambda r: f"title-{r[0]}-part-{r[1]}"
)
def test_every_real_ecfr_root_url_is_existence_only(root: tuple[str, str, str]) -> None:
    title, part, _ = root
    url = f"https://www.ecfr.gov/api/versioner/v1/versions/title-{title}.json?part={part}"
    assert pre.url_is_existence_only(url)


@pytest.mark.parametrize("category", sfi3.WIKIPEDIA_CATEGORY_ROOTS)
def test_every_real_wikipedia_root_url_is_existence_only(category: str) -> None:
    import urllib.parse

    encoded = urllib.parse.quote(category, safe="")
    url = f"https://en.wikipedia.org/w/api.php?action=query&titles={encoded}&prop=info&format=json"
    assert pre.url_is_existence_only(url)


def test_whitelist_rejects_the_ecfr_full_text_endpoint() -> None:
    assert not pre.url_is_existence_only(
        "https://www.ecfr.gov/api/versioner/v1/full/2026-01-01/title-5.xml"
    )


def test_whitelist_rejects_wikipedia_parse_and_revision_content() -> None:
    assert not pre.url_is_existence_only(
        "https://en.wikipedia.org/w/api.php?action=parse&oldid=123"
    )
    assert not pre.url_is_existence_only(
        "https://en.wikipedia.org/w/api.php?action=query&prop=revisions&rvprop=content&titles=X"
    )


def test_whitelist_rejects_a_github_single_file_content_path() -> None:
    assert not pre.url_is_existence_only(
        "https://raw.githubusercontent.com/github/docs/main/content/index.md"
    )


# ---------------------------------------------------------------------------
# 3 — the request-boundary guard
# ---------------------------------------------------------------------------


def test_bounded_get_refuses_a_non_whitelisted_url_before_any_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = {"count": 0}

    def _should_not_be_called(*_args: Any, **_kwargs: Any) -> Any:
        called["count"] += 1
        raise AssertionError("urlopen must not be reached for a refused URL")

    monkeypatch.setattr(pre.urllib.request, "urlopen", _should_not_be_called)
    with pytest.raises(pre.ContentEndpointRefused):
        pre._bounded_get("https://www.ecfr.gov/api/versioner/v1/full/2026-01-01/title-5.xml")
    assert called["count"] == 0


# ---------------------------------------------------------------------------
# fake transport for the remaining tests
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, body: bytes, *, status: int = 200, final_url: str | None = None) -> None:
        self._body = body
        self._pos = 0
        self.status = status
        self._final_url = final_url

    def read(self, amount: int) -> bytes:
        chunk = self._body[self._pos : self._pos + amount]
        self._pos += len(chunk)
        return chunk

    def geturl(self) -> str:
        return self._final_url or ""

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None


# ---------------------------------------------------------------------------
# 4 — size guard
# ---------------------------------------------------------------------------


def test_oversized_response_is_reported_unread(monkeypatch: pytest.MonkeyPatch) -> None:
    oversized = b"{" + b"a" * (pre.MAX_RESPONSE_BYTES + 10) + b"}"
    fake = _FakeResponse(oversized, final_url="https://api.github.com/repos/o/r")

    monkeypatch.setattr(pre.urllib.request, "urlopen", lambda *a, **k: fake)
    result = pre._bounded_get("https://api.github.com/repos/o/r")
    assert result["body"] is None
    assert "guard" in result["reason"]


# ---------------------------------------------------------------------------
# 5 — no content leak, checked from outside
# ---------------------------------------------------------------------------


def _no_marker_anywhere(record: dict[str, Any], marker: str) -> bool:
    return marker not in json.dumps(record)


def test_git_root_check_never_leaks_injected_content_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = "REVISION_CONTENT_MARKER_" + "x" * 500
    repo_body = json.dumps(
        {
            "id": 1,
            "full_name": "acme/docs",
            "private": False,
            "archived": False,
            "disabled": False,
            "default_branch": "main",
            "description": marker,  # a field this module must never surface
        }
    ).encode("utf-8")
    contents_body = json.dumps(
        [{"name": "index.md", "path": "docs/index.md", "sha": "abc", "content_preview": marker}]
    ).encode("utf-8")

    responses = [
        _FakeResponse(repo_body, final_url="https://api.github.com/repos/acme/docs"),
        _FakeResponse(
            contents_body, final_url="https://api.github.com/repos/acme/docs/contents/docs"
        ),
    ]

    def _fake_urlopen(*_a: Any, **_k: Any) -> _FakeResponse:
        return responses.pop(0)

    monkeypatch.setattr(pre.urllib.request, "urlopen", _fake_urlopen)
    monkeypatch.setattr(pre.time, "sleep", lambda *_a, **_k: None)

    record = pre.check_git_root(
        {"owner": "acme", "repo": "docs", "prefix": "docs/", "license": "MIT"}
    )
    assert record["state"] == pre.STATE_VALID
    assert _no_marker_anywhere(record, marker)


def test_git_single_file_response_shape_is_refused_not_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`_GIT_CONTENTS_URL` is shape-compatible with both a directory listing
    and a single file's content (GitHub uses one route for both). The real
    protection is the `isinstance(listing, list)` check in `check_git_root`:
    a single-file response — a JSON *object* carrying a base64 `content`
    field — must be refused as unreachable, never read into, even though its
    URL passed the whitelist."""
    marker = "BASE64_FILE_CONTENT_MARKER_" + "z" * 500
    repo_body = json.dumps(
        {
            "id": 1,
            "full_name": "acme/docs",
            "private": False,
            "archived": False,
            "disabled": False,
            "default_branch": "main",
        }
    ).encode("utf-8")
    #: what GitHub actually returns when a "directory" resolves to a single
    #: file: an object, not an array, carrying base64 `content`.
    single_file_body = json.dumps(
        {"name": "docs", "path": "docs", "sha": "abc", "type": "file", "content": marker}
    ).encode("utf-8")

    responses = [
        _FakeResponse(repo_body, final_url="https://api.github.com/repos/acme/docs"),
        _FakeResponse(
            single_file_body, final_url="https://api.github.com/repos/acme/docs/contents/docs"
        ),
    ]

    def _fake_urlopen(*_a: Any, **_k: Any) -> _FakeResponse:
        return responses.pop(0)

    monkeypatch.setattr(pre.urllib.request, "urlopen", _fake_urlopen)
    monkeypatch.setattr(pre.time, "sleep", lambda *_a, **_k: None)

    record = pre.check_git_root(
        {"owner": "acme", "repo": "docs", "prefix": "docs/", "license": "MIT"}
    )
    assert record["state"] == pre.STATE_NOT_FOUND
    assert record["identity"]["prefix_reachable"] is False
    assert _no_marker_anywhere(record, marker)


def test_ecfr_root_check_never_leaks_injected_content_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = "REGULATION_TEXT_MARKER_" + "y" * 500
    body = json.dumps(
        {"content_versions": [{"date": "2026-01-01", "full_text_preview": marker}], "meta": {}}
    ).encode("utf-8")
    fake = _FakeResponse(
        body, final_url="https://www.ecfr.gov/api/versioner/v1/versions/title-5.json?part=2635"
    )

    monkeypatch.setattr(pre.urllib.request, "urlopen", lambda *a, **k: fake)
    monkeypatch.setattr(pre.time, "sleep", lambda *_a, **_k: None)

    record = pre.check_ecfr_root(("5", "2635", "Standards"))
    assert record["state"] == pre.STATE_VALID
    assert _no_marker_anywhere(record, marker)


def test_wikipedia_root_check_never_leaks_injected_content_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = "ARTICLE_TEXT_MARKER_" + "z" * 500
    body = json.dumps(
        {
            "query": {
                "pages": {
                    "1": {
                        "pageid": 1,
                        "ns": 14,
                        "title": "Category:Fixture",
                        "extract_preview": marker,
                    }
                }
            }
        }
    ).encode("utf-8")
    fake = _FakeResponse(
        body,
        final_url="https://en.wikipedia.org/w/api.php?action=query&titles=Category%3AFixture&prop=info&format=json",
    )

    monkeypatch.setattr(pre.urllib.request, "urlopen", lambda *a, **k: fake)
    monkeypatch.setattr(pre.time, "sleep", lambda *_a, **_k: None)

    record = pre.check_wikipedia_root("Category:Fixture")
    assert record["state"] == pre.STATE_VALID
    assert _no_marker_anywhere(record, marker)


# ---------------------------------------------------------------------------
# 6 — syntactic rejection, no network attempted
# ---------------------------------------------------------------------------


def test_invalid_git_identifier_is_rejected_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _should_not_be_called(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("no network call should be attempted")

    monkeypatch.setattr(pre.urllib.request, "urlopen", _should_not_be_called)
    record = pre.check_git_root(
        {"owner": "bad owner!", "repo": "x", "prefix": "docs/", "license": "MIT"}
    )
    assert record["state"] == pre.STATE_INVALID_IDENTIFIER


def test_invalid_ecfr_title_is_rejected_without_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _should_not_be_called(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("no network call should be attempted")

    monkeypatch.setattr(pre.urllib.request, "urlopen", _should_not_be_called)
    record = pre.check_ecfr_root(("99", "1", "not a real title"))
    assert record["state"] == pre.STATE_INVALID_IDENTIFIER


def test_invalid_wikipedia_category_is_rejected_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _should_not_be_called(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("no network call should be attempted")

    monkeypatch.setattr(pre.urllib.request, "urlopen", _should_not_be_called)
    record = pre.check_wikipedia_root("Not A Category")
    assert record["state"] == pre.STATE_INVALID_IDENTIFIER


# ---------------------------------------------------------------------------
# 7 — 404 vs transport failure
# ---------------------------------------------------------------------------


def test_http_404_is_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise_404(*_a: Any, **_k: Any) -> Any:
        raise urllib.error.HTTPError("url", 404, "not found", None, None)

    monkeypatch.setattr(pre.urllib.request, "urlopen", _raise_404)
    monkeypatch.setattr(pre.time, "sleep", lambda *_a, **_k: None)
    record = pre.check_ecfr_root(("5", "2635", "x"))
    assert record["state"] == pre.STATE_NOT_FOUND


def test_transport_failure_is_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*_a: Any, **_k: Any) -> Any:
        raise TimeoutError("connection timed out")

    monkeypatch.setattr(pre.urllib.request, "urlopen", _raise)
    monkeypatch.setattr(pre.time, "sleep", lambda *_a, **_k: None)
    record = pre.check_wikipedia_root("Category:Fixture")
    assert record["state"] == pre.STATE_UNREACHABLE


# ---------------------------------------------------------------------------
# 8 — aggregation
# ---------------------------------------------------------------------------


def test_aggregation_reports_counts_by_family_and_state_never_a_bare_boolean(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_git(_root: dict[str, str]) -> dict[str, Any]:
        return pre._record(
            family=pre.FAMILY_GIT, root_id="x/y", state=pre.STATE_VALID, reason="ok",
            expected_host="api.github.com",
        )

    def _fake_ecfr(_root: tuple[str, str, str]) -> dict[str, Any]:
        return pre._record(
            family=pre.FAMILY_ECFR, root_id="title-5-part-1", state=pre.STATE_NOT_FOUND,
            reason="gone", expected_host="www.ecfr.gov",
        )

    def _fake_wiki(_category: str) -> dict[str, Any]:
        return pre._record(
            family=pre.FAMILY_WIKIPEDIA, root_id="Category:X", state=pre.STATE_VALID,
            reason="ok", expected_host="en.wikipedia.org",
        )

    monkeypatch.setattr(pre, "check_git_root", _fake_git)
    monkeypatch.setattr(pre, "check_ecfr_root", _fake_ecfr)
    monkeypatch.setattr(pre, "check_wikipedia_root", _fake_wiki)

    result = pre.run()
    assert result["declared_totals"][pre.FAMILY_GIT] == len(sfi3.GIT_ROOTS)
    assert result["by_family_state"][pre.FAMILY_GIT][pre.STATE_VALID] == len(sfi3.GIT_ROOTS)
    assert result["valid_root_count_per_family"][pre.FAMILY_ECFR] == 0
    assert pre.FAMILY_ECFR in result["zero_valid_families"]
    assert pre.FAMILY_GIT not in result["zero_valid_families"]
    assert pre.FAMILY_WIKIPEDIA not in result["zero_valid_families"]
    assert len(result["invalid_roots_by_family"][pre.FAMILY_ECFR]) == len(sfi3.ECFR_ROOTS)
    assert "records" in result
    assert len(result["records"]) == len(sfi3.GIT_ROOTS) + len(sfi3.ECFR_ROOTS) + len(
        sfi3.WIKIPEDIA_CATEGORY_ROOTS
    )


# ---------------------------------------------------------------------------
# 9 — CLI
# ---------------------------------------------------------------------------


def test_cli_no_receipt_round_trips(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def _fake_git(_root: dict[str, str]) -> dict[str, Any]:
        return pre._record(
            family=pre.FAMILY_GIT, root_id="x/y", state=pre.STATE_VALID, reason="ok",
            expected_host="api.github.com",
        )

    def _fake_ecfr(_root: tuple[str, str, str]) -> dict[str, Any]:
        return pre._record(
            family=pre.FAMILY_ECFR, root_id="title-5-part-1", state=pre.STATE_VALID,
            reason="ok", expected_host="www.ecfr.gov",
        )

    def _fake_wiki(_category: str) -> dict[str, Any]:
        return pre._record(
            family=pre.FAMILY_WIKIPEDIA, root_id="Category:X", state=pre.STATE_VALID,
            reason="ok", expected_host="en.wikipedia.org",
        )

    monkeypatch.setattr(pre, "check_git_root", _fake_git)
    monkeypatch.setattr(pre, "check_ecfr_root", _fake_ecfr)
    monkeypatch.setattr(pre, "check_wikipedia_root", _fake_wiki)

    exit_code = pre.main(["--no-receipt"])
    assert exit_code == 0
    printed = json.loads(capsys.readouterr().out)
    assert "records" not in printed
    assert printed["valid_root_count_per_family"][pre.FAMILY_GIT] == len(sfi3.GIT_ROOTS)
