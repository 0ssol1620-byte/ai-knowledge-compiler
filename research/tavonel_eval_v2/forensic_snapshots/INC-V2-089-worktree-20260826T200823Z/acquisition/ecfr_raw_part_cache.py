"""Bounded, content-addressed cache for immutable historical eCFR part XML.

The cache is transport only, never evidence.  One exact resolved HTTPS URL is
mapped to one content-addressed blob.  Every hit is streamed through SHA-256
before it can be opened, and a bad pointer, truncated blob, or digest mismatch
is a terminal refusal rather than permission to fetch a replacement silently.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import urllib.request
import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any, BinaryIO


class RawPartCacheError(RuntimeError):
    """The immutable transport cache cannot safely supply the requested part."""


_LOCKS_GUARD = threading.Lock()
_LOCKS: dict[str, threading.Lock] = {}


def _lock_for(key: str) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.Lock())


def _sha256_file(path: Path, *, block_bytes: int, max_bytes: int) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as handle:
            while True:
                block = handle.read(block_bytes)
                if not block:
                    break
                size += len(block)
                if size > max_bytes:
                    raise RawPartCacheError("cached eCFR part exceeds the frozen raw-part bound")
                digest.update(block)
    except OSError as error:
        raise RawPartCacheError("cached eCFR part cannot be read") from error
    return digest.hexdigest(), size


class EcfrRawPartCache:
    """Process-thread-safe materializer for exact historical part URLs."""

    def __init__(self, root: Path, *, max_bytes: int, block_bytes: int) -> None:
        if max_bytes <= 0 or block_bytes <= 0:
            raise ValueError("cache bounds must be positive")
        self.root = root
        self.max_bytes = max_bytes
        self.block_bytes = block_bytes
        self.hits = 0
        self.misses = 0
        self._stats_lock = threading.Lock()

    @staticmethod
    def _key(url: str) -> str:
        return hashlib.sha256(url.encode("utf-8")).hexdigest()

    def _pointer(self, key: str) -> Path:
        return self.root / "pointers" / f"{key}.json"

    def _blob(self, digest: str) -> Path:
        return self.root / "blobs" / f"{digest}.xml"

    def _read_pointer(self, pointer: Path, *, key: str, url: str) -> dict[str, Any]:
        try:
            body = json.loads(pointer.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RawPartCacheError("eCFR raw-part cache pointer is corrupt") from error
        if (
            not isinstance(body, dict)
            or body.get("schema") != "tavonel.ecfr_raw_part_cache_pointer.v1"
            or body.get("url_key") != key
            or body.get("url") != url
            or not isinstance(body.get("sha256"), str)
            or len(body["sha256"]) != 64
            or any(character not in "0123456789abcdef" for character in body["sha256"])
            or not isinstance(body.get("size_bytes"), int)
            or body["size_bytes"] < 0
            or body["size_bytes"] > self.max_bytes
        ):
            raise RawPartCacheError("eCFR raw-part cache pointer binding is invalid")
        return body

    def _verified_hit(self, pointer: Path, *, key: str, url: str) -> tuple[Path, str]:
        body = self._read_pointer(pointer, key=key, url=url)
        expected = body["sha256"]
        blob = self._blob(expected)
        if not blob.is_file():
            raise RawPartCacheError("eCFR raw-part cache blob is missing")
        actual, size = _sha256_file(
            blob, block_bytes=self.block_bytes, max_bytes=self.max_bytes
        )
        if actual != expected or size != body["size_bytes"]:
            raise RawPartCacheError("eCFR raw-part cache blob failed hash or size verification")
        with self._stats_lock:
            self.hits += 1
        return blob, expected

    def materialize(
        self,
        url: str,
        *,
        user_agent: str,
        timeout: int = 60,
        opener: Callable[..., AbstractContextManager[BinaryIO]] | None = None,
    ) -> tuple[Path, str]:
        """Return a verified local part and digest, fetching an absent URL once."""
        if not url.startswith("https://www.ecfr.gov/"):
            raise RawPartCacheError("raw-part cache accepts only resolved eCFR HTTPS URLs")
        key = self._key(url)
        pointer = self._pointer(key)
        with _lock_for(str(self.root.resolve()) + "|" + key):
            if pointer.exists():
                return self._verified_hit(pointer, key=key, url=url)

            request = urllib.request.Request(  # noqa: S310 - exact eCFR HTTPS prefix checked above
                url, headers={"User-Agent": user_agent}
            )
            open_url = opener or urllib.request.urlopen
            temporary = self.root / "tmp" / f"{key}.{uuid.uuid4().hex}.partial"
            temporary.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            size = 0
            try:
                with open_url(request, timeout=timeout) as response:
                    declared = response.headers.get("Content-Length")
                    if declared is not None:
                        try:
                            declared_size = int(declared)
                        except (TypeError, ValueError) as error:
                            raise RawPartCacheError(
                                "eCFR raw-part Content-Length is invalid"
                            ) from error
                        if declared_size < 0 or declared_size > self.max_bytes:
                            raise RawPartCacheError(
                                "eCFR raw-part Content-Length exceeds the frozen bound"
                            )
                    with temporary.open("xb") as handle:
                        while True:
                            block = response.read(self.block_bytes)
                            if not block:
                                break
                            size += len(block)
                            if size > self.max_bytes:
                                raise RawPartCacheError(
                                    "streamed eCFR raw part exceeds the frozen bound"
                                )
                            handle.write(block)
                            digest.update(block)
                        handle.flush()
                        os.fsync(handle.fileno())
                    if declared is not None and size != declared_size:
                        raise RawPartCacheError(
                            "eCFR raw-part download ended before declared Content-Length"
                        )
                hexdigest = digest.hexdigest()
                blob = self._blob(hexdigest)
                blob.parent.mkdir(parents=True, exist_ok=True)
                if blob.exists():
                    existing_digest, existing_size = _sha256_file(
                        blob, block_bytes=self.block_bytes, max_bytes=self.max_bytes
                    )
                    if existing_digest != hexdigest or existing_size != size:
                        raise RawPartCacheError(
                            "content-addressed eCFR blob collides with corrupt bytes"
                        )
                    temporary.unlink()
                else:
                    temporary.replace(blob)
                pointer.parent.mkdir(parents=True, exist_ok=True)
                pointer_tmp = pointer.with_suffix(f".{uuid.uuid4().hex}.partial")
                pointer_tmp.write_text(
                    json.dumps(
                        {
                            "schema": "tavonel.ecfr_raw_part_cache_pointer.v1",
                            "url_key": key,
                            "url": url,
                            "sha256": hexdigest,
                            "size_bytes": size,
                            "is_evidence": False,
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    encoding="utf-8",
                    newline="\n",
                )
                pointer_tmp.replace(pointer)
                with self._stats_lock:
                    self.misses += 1
                return blob, hexdigest
            except Exception:
                if temporary.exists():
                    temporary.unlink()
                raise

    def stats(self) -> dict[str, Any]:
        with self._stats_lock:
            return {
                "hits": self.hits,
                "misses": self.misses,
                "max_bytes": self.max_bytes,
                "block_bytes": self.block_bytes,
                "is_evidence": False,
            }
