"""Content-addressed payload and parsed-state cache. Not evidence, ever.

Two caches, and the distinction between them matters:

* **payloads** are keyed by URL and stored under their own sha256. A hit is only
  returned after the stored bytes are re-hashed and match the name they are
  filed under, so a corrupted or truncated cache file is a miss rather than a
  silent substitution.
* **parsed state** — the frozen extractor's property observations for one
  payload — is keyed by the *payload digest* and the extractor's digest
  together. Re-parsing 12 revisions of a document on every rerun is most of the
  CPU cost, and keying on the extractor's own bytes means a changed extractor
  can never read a state its predecessor wrote.

Nothing here is evidence. A receipt never cites the cache; it cites payload
hashes, and those hashes are recomputed from bytes rather than trusted from a
filename. Deleting the whole cache directory changes run time and changes no
result.
"""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Any, Callable

PAYLOADS = "payloads"
STATES = "states"


def digest_of(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _url_key(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


class PayloadCache:
    """Thread-safe, process-local locking. Writes are atomic via a temp rename."""

    def __init__(self, root: Path, extractor_digest: str) -> None:
        self.root = root
        self.extractor_digest = extractor_digest
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0
        self.state_hits = 0
        self.state_misses = 0
        self.rejected = 0
        (root / PAYLOADS).mkdir(parents=True, exist_ok=True)
        (root / STATES).mkdir(parents=True, exist_ok=True)

    # --- payloads ------------------------------------------------------------

    def _pointer(self, url: str) -> Path:
        return self.root / PAYLOADS / (_url_key(url) + ".ptr")

    def _blob(self, digest: str) -> Path:
        return self.root / PAYLOADS / (digest + ".bin")

    def payload(self, url: str, fetch: Callable[[str], bytes]) -> tuple[bytes, str]:
        """Cached bytes for a URL, verified against the digest they are filed under."""
        pointer = self._pointer(url)
        if pointer.exists():
            digest = pointer.read_text(encoding="utf-8").strip()
            blob = self._blob(digest)
            if blob.exists():
                body = blob.read_bytes()
                if digest_of(body) == digest:
                    with self._lock:
                        self.hits += 1
                    return body, digest
                with self._lock:
                    self.rejected += 1
        body = fetch(url)
        digest = digest_of(body)
        self._write(self._blob(digest), body)
        self._write(pointer, digest.encode("utf-8"))
        with self._lock:
            self.misses += 1
        return body, digest

    # --- parsed state --------------------------------------------------------

    def _state_path(self, payload_digest: str, suffix: str) -> Path:
        key = hashlib.sha256(
            (payload_digest + "|" + suffix + "|" + self.extractor_digest).encode("utf-8")
        ).hexdigest()
        return self.root / STATES / (key + ".json")

    def state(
        self,
        payload_digest: str,
        suffix: str,
        compute: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        path = self._state_path(payload_digest, suffix)
        if path.exists():
            try:
                body = json.loads(path.read_text(encoding="utf-8"))
                with self._lock:
                    self.state_hits += 1
                return body
            except (ValueError, OSError):
                with self._lock:
                    self.rejected += 1
        body = compute()
        self._write(
            path, json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")
        )
        with self._lock:
            self.state_misses += 1
        return body

    # --- writing -------------------------------------------------------------

    @staticmethod
    def _write(path: Path, body: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(body)
        temporary.replace(path)

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "payload_hits": self.hits,
                "payload_misses": self.misses,
                "state_hits": self.state_hits,
                "state_misses": self.state_misses,
                "rejected_entries": self.rejected,
                "extractor_digest": self.extractor_digest,
                "is_evidence": False,
                "note": (
                    "a cache accelerates a run and proves nothing about it. Every "
                    "hit is verified against the payload hash it is filed under, "
                    "and deleting this directory changes run time, not results."
                ),
            }
