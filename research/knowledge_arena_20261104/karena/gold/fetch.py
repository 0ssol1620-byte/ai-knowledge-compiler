"""Polite, cached, receipted HTTP GET for the public gold sources.

Every byte the gold builder reads is stored once under ``inputs/raw`` by its
sha256 and indexed by URL, so a rebuild is offline and a gold record can always
name the exact bytes it came from. Nothing here retries a 4xx: a refusal is
reported, not routed around.
"""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import httpx
from arena.provider.safety import atomic_write_bytes, sha256_bytes, utc_now_iso

__all__ = ["FetchError", "Fetched", "Fetcher"]

RETRY_STATUSES: Final = frozenset({429, 500, 502, 503, 504})


class FetchError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Fetched:
    url: str
    status: int
    content_type: str
    sha256: str
    path: Path
    fetched_at: str

    def read(self) -> bytes:
        return self.path.read_bytes()

    def text(self, encoding: str = "utf-8") -> str:
        return self.read().decode(encoding, errors="replace")


class Fetcher:
    def __init__(
        self,
        root: Path,
        *,
        headers: Mapping[str, str],
        min_interval_seconds: float = 0.25,
        offline: bool = False,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.raw_dir = root / "raw"
        self.index_path = root / "fetch_index.jsonl"
        self.headers = dict(headers)
        self.min_interval = min_interval_seconds
        self.offline = offline
        self._last = 0.0
        self._index: dict[str, dict[str, object]] = {}
        if self.index_path.is_file():
            for line in self.index_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    self._index[str(row["url"])] = row
        self._client = httpx.Client(
            timeout=httpx.Timeout(60.0), follow_redirects=True, transport=transport
        )

    def close(self) -> None:
        self._client.close()

    def get(self, url: str) -> Fetched:
        cached = self._index.get(url)
        if cached is not None:
            path = self.raw_dir / f"{str(cached['sha256']).removeprefix('sha256:')}.bin"
            if path.is_file():
                return Fetched(
                    url=url,
                    status=int(str(cached["status"])),
                    content_type=str(cached["content_type"]),
                    sha256=str(cached["sha256"]),
                    path=path,
                    fetched_at=str(cached["fetched_at"]),
                )
        if self.offline:
            raise FetchError(f"offline and not cached: {url}")
        response = self._request(url)
        data = response.content
        digest = sha256_bytes(data)
        path = self.raw_dir / f"{digest.removeprefix('sha256:')}.bin"
        if not path.is_file():
            atomic_write_bytes(path, data)
        row: dict[str, object] = {
            "url": url,
            "status": response.status_code,
            "content_type": response.headers.get("content-type", ""),
            "sha256": digest,
            "bytes": len(data),
            "fetched_at": utc_now_iso(),
        }
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        with self.index_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
        self._index[url] = row
        return Fetched(
            url=url,
            status=response.status_code,
            content_type=str(row["content_type"]),
            sha256=digest,
            path=path,
            fetched_at=str(row["fetched_at"]),
        )

    def _request(self, url: str) -> httpx.Response:
        for attempt in range(3):
            wait = self.min_interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            try:
                response = self._client.get(url, headers=self.headers)
            except httpx.HTTPError as exc:
                if attempt == 2:
                    raise FetchError(f"{url}: {type(exc).__name__}") from None
                time.sleep(2.0 * (attempt + 1))
                continue
            if response.status_code == 200:
                return response
            if response.status_code in RETRY_STATUSES and attempt < 2:
                time.sleep(5.0 * (attempt + 1))
                continue
            raise FetchError(f"{url}: HTTP {response.status_code}")
        raise FetchError(f"{url}: gave up")  # pragma: no cover - loop always returns or raises
