#!/usr/bin/env python3
"""Fetch a large immutable file in ordered byte ranges, resumably.

Zenodo serves the SFIR7 catalogue archive at roughly 0.3 MB/s on a single
connection, which is about twenty-four hours for 24.9 GB. The per-connection
figure is the bound -- six connections measured 1.57 MB/s, close to six times one
-- so the archive is fetched as fixed-size ranges over a small connection pool.

Two properties matter more than the speed.

**The result must be byte-identical to a plain download.** Parts are fixed-size,
written to their own files, checked against their expected length, and
concatenated strictly in index order. Nothing downstream can tell this apart
from a single stream, which is what lets the archive digest still mean what it
says.

**It must survive an interruption.** A four-hour transfer that has to restart
from zero on a dropped connection will not finish. A part whose file already has
exactly its expected length is skipped, so a re-run resumes.

The pool is deliberately small. This is a public academic repository, and eight
connections is what an ordinary download manager opens -- enough to be practical,
not enough to be a load problem for anyone else.
"""

from __future__ import annotations

import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO

#: Big enough that per-request overhead is irrelevant, small enough that a
#: failure re-fetches little.
PART_BYTES = 256 * 1024 * 1024
DEFAULT_CONNECTIONS = 8
MAX_ATTEMPTS_PER_PART = 6
READ_CHUNK = 1024 * 1024


class RangedFetchRefused(RuntimeError):
    """The transfer could not be established as byte-exact."""


def _https_request(url: str, headers: dict[str, str]) -> urllib.request.Request:
    if urllib.parse.urlparse(url).scheme != "https":
        raise RangedFetchRefused(f"source must be https: {url!r}")
    return urllib.request.Request(url, headers=dict(headers))  # noqa: S310 -- checked above


def probe_total_bytes(url: str, *, user_agent: str) -> int:
    """Ask the server for the length, and prove it honours ranges while asking.

    A server that ignores `Range` answers 200 with the whole file. Discovering
    that after assembling parts would mean every part was the entire archive,
    concatenated -- so it is established here, before anything is written.
    """
    request = _https_request(url, {"User-Agent": user_agent, "Range": "bytes=0-1023"})
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 -- scheme checked
        if response.status != 206:
            raise RangedFetchRefused(
                f"server answered {response.status} to a Range request; it does not "
                "support ranges, and a parallel fetch would silently produce "
                "concatenated copies of the whole file"
            )
        content_range = response.headers.get("Content-Range", "")
    if "/" not in content_range:
        raise RangedFetchRefused(f"no Content-Range in a 206 response: {content_range!r}")
    total = content_range.rsplit("/", 1)[1].strip()
    if not total.isdigit():
        raise RangedFetchRefused(f"Content-Range carries no total length: {content_range!r}")
    return int(total)


def _fetch_part(
    url: str, index: int, start: int, length: int, path: Path, user_agent: str
) -> None:
    for attempt in range(1, MAX_ATTEMPTS_PER_PART + 1):
        try:
            request = _https_request(
                url,
                {"User-Agent": user_agent, "Range": f"bytes={start}-{start + length - 1}"},
            )
            written = 0
            temporary = path.with_suffix(".partial")
            with urllib.request.urlopen(request, timeout=300) as response:  # noqa: S310
                if response.status != 206:
                    raise RangedFetchRefused(
                        f"part {index} answered {response.status}, not 206"
                    )
                with temporary.open("wb") as handle:
                    while True:
                        chunk = response.read(READ_CHUNK)
                        if not chunk:
                            break
                        handle.write(chunk)
                        written += len(chunk)
            if written != length:
                raise RangedFetchRefused(
                    f"part {index} declared {length} bytes, {written} arrived"
                )
            temporary.replace(path)
            return
        except (urllib.error.URLError, TimeoutError, RangedFetchRefused, OSError) as error:
            if attempt == MAX_ATTEMPTS_PER_PART:
                raise RangedFetchRefused(
                    f"part {index} failed after {attempt} attempts: {error}"
                ) from error
            time.sleep(min(60, 2**attempt))


def fetch_ranges(
    url: str,
    parts_dir: Path,
    *,
    user_agent: str,
    connections: int = DEFAULT_CONNECTIONS,
    total_bytes: int | None = None,
    progress_seconds: float = 30.0,
) -> tuple[list[Path], int]:
    """Fetch every range, returning the part paths in order and the total length."""
    parts_dir.mkdir(parents=True, exist_ok=True)
    total = (
        total_bytes
        if total_bytes is not None
        else probe_total_bytes(url, user_agent=user_agent)
    )
    plan: list[tuple[int, int, int, Path]] = []
    start = 0
    index = 0
    while start < total:
        length = min(PART_BYTES, total - start)
        plan.append((index, start, length, parts_dir / f"part-{index:05d}.bin"))
        start += length
        index += 1

    pending = [row for row in plan if not (row[3].exists() and row[3].stat().st_size == row[2])]
    already = len(plan) - len(pending)
    print(
        f"  {len(plan)} parts of {PART_BYTES / 1e6:.0f} MB; {already} already complete, "
        f"{len(pending)} to fetch over {connections} connections",
        flush=True,
    )

    lock = threading.Lock()
    cursor = [0]
    done = [already]
    failure: list[BaseException] = []
    started = time.monotonic()

    def worker() -> None:
        while True:
            with lock:
                if failure or cursor[0] >= len(pending):
                    return
                row = pending[cursor[0]]
                cursor[0] += 1
            try:
                _fetch_part(url, row[0], row[1], row[2], row[3], user_agent)
            except BaseException as error:  # recorded, then re-raised by the caller
                with lock:
                    failure.append(error)
                return
            with lock:
                done[0] += 1

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(max(1, connections))]
    for thread in threads:
        thread.start()
    while any(thread.is_alive() for thread in threads):
        time.sleep(progress_seconds)
        with lock:
            complete = done[0]
            failed = bool(failure)
        elapsed = max(1e-9, time.monotonic() - started)
        fetched = max(0, complete - already)
        rate = fetched * PART_BYTES / elapsed
        remaining = len(plan) - complete
        eta = (remaining * PART_BYTES / rate / 60) if rate > 0 else float("inf")
        print(
            f"    {complete}/{len(plan)} parts "
            f"({complete * PART_BYTES / 1e9:.1f} GB) "
            f"{rate / 1e6:.2f} MB/s  ETA {eta:.0f} min",
            flush=True,
        )
        if failed:
            break
    for thread in threads:
        thread.join()
    if failure:
        raise failure[0]

    ordered = [row[3] for row in plan]
    for row in plan:
        if not row[3].exists() or row[3].stat().st_size != row[2]:
            raise RangedFetchRefused(f"part {row[0]} is missing or the wrong length after fetch")
    return ordered, total


class ConcatenatedParts:
    """A read-only file over the parts, in order, indistinguishable from the whole.

    The digests and the tar walk run over this, so a mistake in part ordering or
    length shows up as a digest mismatch rather than as a quietly wrong archive.
    """

    def __init__(self, paths: list[Path]) -> None:
        self._paths = list(paths)
        self._index = 0
        self._handle: BinaryIO | None = None

    def _open_next(self) -> bool:
        if self._handle is not None:
            self._handle.close()
            self._handle = None
        if self._index >= len(self._paths):
            return False
        self._handle = self._paths[self._index].open("rb")
        self._index += 1
        return True

    def read(self, size: int = -1) -> bytes:
        if self._handle is None and not self._open_next():
            return b""
        assert self._handle is not None
        while True:
            chunk = self._handle.read(size)
            if chunk:
                return chunk
            if not self._open_next():
                return b""

    def close(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None

    def __iter__(self) -> Iterator[bytes]:  # pragma: no cover - convenience only
        while True:
            chunk = self.read(READ_CHUNK)
            if not chunk:
                return
            yield chunk
