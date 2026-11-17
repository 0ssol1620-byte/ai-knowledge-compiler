"""Terms snapshots for the local public corpus (WO-LPC-1T).

One fetch per distinct URL; sources sharing a URL share the snapshot (same sha).
Writes ``<sha256>.html`` plus ``terms.json`` for ``sources.build``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from benchmark.local_public.sources import SourceError, _inside_git_tree
from benchmark.screen.acquire import AcquireError, PacedClient

DEFAULT_OUT = Path("D:/CodexProjects/v34-lanes/corpus/licences")
_SEC = "https://www.sec.gov/about/privacy-information#copyright"
# FRED/ALFRED content is denied for every action (D21-L1, register row data_alfred_vintages;
# FRED legal terms API prohibitions (k) and (l)): no request to fred.stlouisfed.org is made.
DENIED_SOURCE_PREFIXES = ("data_alfred_vintages",)
# (source_id, snapshot_url) from the register rows of WO-LPC-0.
SOURCES: list[tuple[str, str]] = [
    ("data_sec_fsds", _SEC),
    ("data_sec_edgar_filings", _SEC),
]
# Closed set of hosts the module may ask, derived from the sources it declares. Anything else,
# the St. Louis Fed hosts included, is refused by construction (D21-L1).
ALLOWED_HOSTS = frozenset(httpx.URL(u).host for _, u in SOURCES)


def _request_url(url: str, allowed: frozenset[str]) -> str:
    """The URL string to send, decided on the host httpx itself will use; SourceError otherwise."""
    try:  # .host decodes IDNA lazily, so it belongs inside the try
        u = httpx.URL(url)
        ok = u.scheme == "https" and not u.userinfo and u.port is None and u.host in allowed
    except (httpx.InvalidURL, UnicodeError) as exc:  # idna errors are UnicodeError
        raise SourceError(f"host not allowed, no request made: {url!r}: {exc}") from exc
    if not ok:
        raise SourceError(f"host not allowed, no request made: {url!r}")
    return str(u)


def snapshot(
    out: Path,
    *,
    sources: list[tuple[str, str]] = SOURCES,
    user_agent: str | None = None,
    transport: httpx.BaseTransport | None = None,
    allowed_hosts: frozenset[str] = ALLOWED_HOSTS,
) -> list[dict[str, Any]]:
    """Fetch each distinct URL once. Raises SourceError, writing no terms.json, on any failure."""
    denied = [i for i, _ in sources if i.startswith(DENIED_SOURCE_PREFIXES)]
    if denied:
        raise SourceError(f"rights denied for every action, no request made: {denied}")
    sends = {u: _request_url(u, allowed_hosts) for _, u in sources}
    ua = os.environ.get("SEC_USER_AGENT", "") if user_agent is None else user_agent
    if not ua.strip():
        raise SourceError("SEC_USER_AGENT is not set; refusing to fetch")
    if _inside_git_tree(out):
        raise SourceError(f"output {out} is inside a git work tree")
    ids = [s for s, _ in sources]
    if len(set(ids)) != len(ids):
        raise SourceError("duplicate source id")
    client = PacedClient(ua, transport=transport)
    fetched: dict[str, tuple[bytes, str]] = {}
    failed: list[str] = []
    out.mkdir(parents=True, exist_ok=True)
    for url in dict.fromkeys(u for _, u in sources):
        try:
            body = client.get(sends[url])
        except (AcquireError, httpx.HTTPError) as exc:
            failed.append(f"{url}: {exc}")
            continue
        sha = hashlib.sha256(body).hexdigest()
        (out / f"{sha}.html").write_bytes(body)
        fetched[url] = (body, datetime.now(UTC).isoformat())
    if failed:
        raise SourceError("snapshot failed, terms.json not written: " + "; ".join(failed))
    rows = [
        {
            "source_id": sid,
            "url": url,
            "fetched_at": fetched[url][1],
            "sha256": hashlib.sha256(fetched[url][0]).hexdigest(),
            "http_status": 200,  # PacedClient returns only on 200
        }
        for sid, url in sources
    ]
    (out / "terms.json").write_text(json.dumps(rows, indent=1), "utf-8")
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="terms")
    ap.add_argument("cmd", choices=["snapshot"])
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    a = ap.parse_args(argv)
    try:
        rows = snapshot(a.out)
    except SourceError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1
    print(f"snapshotted {len(rows)} sources")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
