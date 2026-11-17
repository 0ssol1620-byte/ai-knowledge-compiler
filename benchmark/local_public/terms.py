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

# The sources, their host allow-list and the host check live in sources.py, which build() shares.
from benchmark.local_public.sources import (
    TERMS_HOSTS,
    TERMS_SOURCES,
    SourceError,
    _excluded,
    _inside_git_tree,
    _request_url,
)
from benchmark.screen.acquire import AcquireError, PacedClient

DEFAULT_OUT = Path("D:/CodexProjects/v34-lanes/corpus/licences")


def snapshot(
    out: Path,
    *,
    sources: list[tuple[str, str]] = TERMS_SOURCES,
    user_agent: str | None = None,
    transport: httpx.BaseTransport | None = None,
    allowed_hosts: frozenset[str] = TERMS_HOSTS,
) -> list[dict[str, Any]]:
    """Fetch each distinct URL once. Raises SourceError, writing no terms.json, on any failure."""
    # FRED/ALFRED content is denied for every action (D21-L1, register row data_alfred_vintages;
    # FRED legal terms API prohibitions (k) and (l)): no request to fred.stlouisfed.org is made.
    denied = [i for i, _ in sources if _excluded(f"terms/{i}")]
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
