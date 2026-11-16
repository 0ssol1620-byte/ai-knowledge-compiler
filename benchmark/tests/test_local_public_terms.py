from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx
import pytest

from benchmark.local_public import terms
from benchmark.local_public.sources import SourceError

SRC = [("a", "https://x.test/a"), ("b", "https://x.test/b"), ("c", "https://x.test/a")]


def _run(tmp_path: Path, handler, monkeypatch, ua: str | None = "TAVONEL-test/1.0 (+t)"):
    monkeypatch.setattr(terms, "_inside_git_tree", lambda p: False)
    if ua is None:
        monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    else:
        monkeypatch.setenv("SEC_USER_AGENT", ua)
    return terms.snapshot(tmp_path / "lic", sources=SRC, transport=httpx.MockTransport(handler))


def test_each_url_fetched_once_shared_url_shares_sha(tmp_path, monkeypatch) -> None:
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


def test_non_200_writes_no_terms_json_and_cli_exits_nonzero(tmp_path, monkeypatch) -> None:
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
def test_unset_user_agent_makes_no_request(tmp_path, monkeypatch, ua) -> None:
    calls: list[int] = []

    def h(req: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200)

    with pytest.raises(SourceError):
        _run(tmp_path, h, monkeypatch, ua=ua)
    assert not calls


def test_output_inside_git_tree_refused(tmp_path) -> None:
    (tmp_path / ".git").mkdir()
    with pytest.raises(SourceError, match="git work tree"):
        terms.snapshot(tmp_path / "lic", sources=SRC, user_agent="ua")


def test_duplicate_source_id_refused(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(terms, "_inside_git_tree", lambda p: False)
    with pytest.raises(SourceError, match="duplicate"):
        terms.snapshot(tmp_path, sources=[("a", "u1"), ("a", "u2")], user_agent="ua")
