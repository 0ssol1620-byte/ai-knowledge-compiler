from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from benchmark.local_public import terms
from benchmark.local_public.sources import SourceError

X = frozenset({"x.test"})
SRC = [("a", "https://x.test/a"), ("b", "https://x.test/b"), ("c", "https://x.test/a")]


def _run(
    tmp_path: Path,
    handler: Callable[[httpx.Request], httpx.Response],
    monkeypatch: pytest.MonkeyPatch,
    ua: str | None = "TAVONEL-test/1.0 (+t)",
) -> list[dict[str, Any]]:
    monkeypatch.setattr(terms, "_inside_git_tree", lambda p: False)
    if ua is None:
        monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    else:
        monkeypatch.setenv("SEC_USER_AGENT", ua)
    return terms.snapshot(
        tmp_path / "lic", sources=SRC, transport=httpx.MockTransport(handler), allowed_hosts=X
    )


def test_each_url_fetched_once_shared_url_shares_sha(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []

    def h(req: httpx.Request) -> httpx.Response:
        seen.append(str(req.url))
        return httpx.Response(200, content=req.url.path.encode())

    rows = _run(tmp_path, h, monkeypatch)
    assert sorted(seen) == ["https://x.test/a", "https://x.test/b"]
    assert [r["source_id"] for r in rows] == ["a", "b", "c"]
    assert rows[0]["sha256"] == rows[2]["sha256"] != rows[1]["sha256"]
    sha = hashlib.sha256(b"/a").hexdigest()
    assert (tmp_path / "lic" / f"{sha}.html").read_bytes() == b"/a"
    saved = json.loads((tmp_path / "lic" / "terms.json").read_text("utf-8"))
    assert saved == rows and rows[0]["http_status"] == 200
    assert rows[0]["fetched_at"].endswith("+00:00")


def test_non_200_writes_no_terms_json_and_cli_exits_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def h(req: httpx.Request) -> httpx.Response:
        return httpx.Response(404 if req.url.path == "/b" else 200, content=b"ok")

    with pytest.raises(SourceError):
        _run(tmp_path, h, monkeypatch)
    assert not (tmp_path / "lic" / "terms.json").exists()
    # the failed source never got a snapshot of its own
    assert len(list((tmp_path / "lic").glob("*.html"))) == 1

    monkeypatch.setattr(terms, "snapshot", lambda out: (_ for _ in ()).throw(SourceError("x")))
    assert terms.main(["snapshot", "--out", str(tmp_path)]) == 1


@pytest.mark.parametrize("ua", [None, "  "])
def test_unset_user_agent_makes_no_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ua: str | None
) -> None:
    calls: list[int] = []

    def h(req: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200)

    with pytest.raises(SourceError):
        _run(tmp_path, h, monkeypatch, ua=ua)
    assert not calls


def test_output_inside_git_tree_refused(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    with pytest.raises(SourceError, match="git work tree"):
        terms.snapshot(tmp_path / "lic", sources=SRC, user_agent="ua", allowed_hosts=X)


def test_duplicate_source_id_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(terms, "_inside_git_tree", lambda p: False)
    with pytest.raises(SourceError, match="duplicate"):
        terms.snapshot(
            tmp_path,
            sources=[("a", "https://x.test/1"), ("a", "https://x.test/2")],
            user_agent="ua",
            allowed_hosts=X,
        )


def _refused(tmp_path: Path, url: str, sid: str = "innocent_id") -> list[str]:
    seen: list[str] = []

    def h(req: httpx.Request) -> httpx.Response:
        seen.append(str(req.url))
        return httpx.Response(200)

    with pytest.raises(SourceError, match="host not allowed"):
        terms.snapshot(
            tmp_path / "lic",
            sources=[("data_sec_fsds", "https://www.sec.gov/ok"), (sid, url)],
            user_agent="ua",
            transport=httpx.MockTransport(h),
        )
    assert not (tmp_path / "lic").exists()
    return seen


@pytest.mark.parametrize(
    "url",
    [
        "https://fred.stlouisfed.org/legal/",
        "https://stlouisfed.org/",
        "https://api.stlouisfed.org/fred/series?x=1",
        "https://fred.stlouisfed\u3002org/legal/",  # ideographic full stop
        "https://fred.stlouisfed\uff0eorg/legal/",  # full-width dot
        "https://fred.stlouisfed.org\\@evil.test/",
        "https://xn--fred-stlouisfed.org/",
        "https://www.sec.gov./a",  # trailing dot
        "https://www.sec.gov:8443/a",
        "https://user@www.sec.gov/a",
        "http://www.sec.gov/a",
        "https://www.sec.gov.evil.test/a",
        "https://evil.test/www.sec.gov",
        "https://www.sec.gov@evil.test/a",
        "https://[::1]/",
        "https://www.s	ec.gov/",
    ],
)
def test_host_off_the_list_refused_before_any_request(tmp_path: Path, url: str) -> None:
    assert _refused(tmp_path, url) == []


def test_st_louis_fed_named_and_refused_under_a_sec_id(tmp_path: Path) -> None:
    assert _refused(tmp_path, "https://fred.stlouisfed.org/legal/", "data_sec_edgar_filings") == []


def test_upper_case_sec_host_is_the_same_host() -> None:
    assert (
        terms._request_url("https://WWW.SEC.GOV/a", terms.ALLOWED_HOSTS) == "https://www.sec.gov/a"
    )


def test_allowed_hosts_are_the_declared_sources_only() -> None:
    assert {"www.sec.gov"} == terms.ALLOWED_HOSTS


def test_redirect_is_not_followed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def h(req: httpx.Request) -> httpx.Response:
        seen.append(str(req.url))
        return httpx.Response(302, headers={"location": "https://fred.stlouisfed.org/legal/"})

    with pytest.raises(SourceError):
        _run(tmp_path, h, monkeypatch)
    assert all(u.startswith("https://x.test/") for u in seen)


@settings(max_examples=300, deadline=None)
@given(st.text(max_size=30))
def test_accepted_implies_client_host_in_set(host: str) -> None:
    url = f"https://{host}/a"
    try:
        sent = terms._request_url(url, terms.ALLOWED_HOSTS)
    except SourceError:
        return
    assert httpx.URL(sent).host in terms.ALLOWED_HOSTS


@settings(max_examples=300, deadline=None)
@given(
    st.text(alphabet=st.sampled_from(list("fred.stlouisfd\u3002\uff0e\uff61%2E@\\:")), max_size=40)
)
def test_fred_like_hosts_never_accepted(host: str) -> None:
    with pytest.raises(SourceError):
        terms._request_url(f"https://{host}/a", terms.ALLOWED_HOSTS)
