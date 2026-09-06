#!/usr/bin/env python3
"""Execute the exact SFIR4 roster once through the native scientific stack."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
import threading
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(NS / "tools"))
import sfir1_worker as native  # noqa: E402
import sfir4_execution as sx  # noqa: E402

MAX_PAYLOAD_BYTES = 2_000_000
READ_BLOCK_BYTES = 64 * 1024
MAX_WORKERS = 2
IN_FLIGHT_PER_WORKER = 2
MAX_ECFR_RAW_PART_BYTES = 256 * 1024 * 1024
MAX_ECFR_TOTAL_CACHE_BYTES = 8 * 1024 * 1024 * 1024
MAX_ACQUISITION_PAYLOAD_CACHE_BYTES = 16 * 1024 * 1024 * 1024
MAX_OBSERVATION_SPOOL_BYTES = 8 * 1024 * 1024 * 1024
MAX_SCIENTIFIC_EVIDENCE_BYTES = 32 * 1024 * 1024
REJECTION_INSTRUMENT = "INSTRUMENT_UNAVAILABLE"
USER_AGENT = "TAVONEL-SFIR4-scientific-acquisition/1.0"
_ECFR_CACHE_GUARD = threading.Lock()
_CACHE_TREE_GUARD = threading.Lock()
_CACHE_TREE_LOCKS: dict[str, threading.RLock] = {}
_SPOOL_TREE_GUARD = threading.Lock()
_SPOOL_TREE_LOCKS: dict[str, threading.RLock] = {}


def _tree_lock(
    root: Path, guard: threading.Lock, locks: dict[str, threading.RLock]
) -> threading.RLock:
    key = str(root.resolve())
    with guard:
        return locks.setdefault(key, threading.RLock())


def _bounded_regular_tree_bytes(root: Path, limit: int, label: str) -> int:
    """Count a regular-file-only tree without following links."""
    if root.is_symlink():
        raise sx.Refused(f"{label} root is a symbolic link")
    if not root.exists():
        return 0
    total = 0
    pending = [root]
    while pending:
        directory = pending.pop()
        if directory.is_symlink() or not directory.is_dir():
            raise sx.Refused(f"{label} contains a non-directory or symbolic link")
        try:
            entries = list(os.scandir(directory))
        except OSError as error:
            raise sx.Refused(f"{label} cannot be enumerated") from error
        for entry in entries:
            try:
                if entry.is_symlink():
                    raise sx.Refused(f"{label} contains a symbolic link")
                if entry.is_dir(follow_symlinks=False):
                    pending.append(Path(entry.path))
                elif entry.is_file(follow_symlinks=False):
                    size = entry.stat(follow_symlinks=False).st_size
                    if size < 0:
                        raise sx.Refused(f"{label} contains an invalid file size")
                    total += size
                    if total > limit:
                        raise sx.Refused(f"{label} exceeds the frozen aggregate bound")
                else:
                    raise sx.Refused(f"{label} contains a non-regular entry")
            except OSError as error:
                raise sx.Refused(f"{label} entry cannot be inspected") from error
    return total


class BoundedPayloadCache:
    """Fail-closed wrapper around PayloadCache with an aggregate tree quota."""

    def __init__(self, root: Path, extractor_digest: str) -> None:
        from payload_cache import PayloadCache

        if root.is_symlink():
            raise sx.Refused("SFIR4 payload/state cache root is a symbolic link")
        self.root = root
        self._cache = PayloadCache(root, extractor_digest)
        self._lock = _tree_lock(root, _CACHE_TREE_GUARD, _CACHE_TREE_LOCKS)

    def _tree_bytes(self) -> int:
        return _bounded_regular_tree_bytes(
            self.root, MAX_ACQUISITION_PAYLOAD_CACHE_BYTES, "SFIR4 payload/state cache"
        )

    @staticmethod
    def _regular_size(path: Path, label: str, maximum: int) -> int:
        if path.is_symlink():
            raise sx.Refused(f"{label} is a symbolic link")
        try:
            held = path.stat()
        except OSError as error:
            raise sx.Refused(f"{label} cannot be inspected") from error
        if not stat.S_ISREG(held.st_mode) or held.st_size < 0 or held.st_size > maximum:
            raise sx.Refused(f"{label} size or file type is invalid")
        return held.st_size

    def payload(self, url: str, fetch: Callable[[str], bytes]) -> tuple[bytes, str]:
        pointer = self._cache._pointer(url)
        with self._lock:
            current = self._tree_bytes()
            if pointer.exists() or pointer.is_symlink():
                self._regular_size(pointer, "SFIR4 payload-cache pointer", 64)
                try:
                    pointer_bytes = pointer.read_bytes()
                    digest = pointer_bytes.decode("ascii")
                except (OSError, UnicodeDecodeError) as error:
                    raise sx.Refused("SFIR4 payload-cache pointer is unreadable") from error
                if (
                    len(pointer_bytes) != 64
                    or len(digest) != 64
                    or any(character not in "0123456789abcdef" for character in digest)
                ):
                    raise sx.Refused("SFIR4 payload-cache pointer format is invalid")
                blob = self._cache._blob(digest)
                if not blob.exists() and not blob.is_symlink():
                    raise sx.Refused("SFIR4 payload-cache target blob is absent")
                self._regular_size(blob, "SFIR4 payload-cache target blob", MAX_PAYLOAD_BYTES)
                try:
                    body = blob.read_bytes()
                except OSError as error:
                    raise sx.Refused("SFIR4 payload-cache target blob is unreadable") from error
                if hashlib.sha256(body).hexdigest() != digest:
                    raise sx.Refused("SFIR4 payload-cache target blob digest is invalid")
                self._cache.hits += 1
                return body, digest
            body = fetch(url)
            if not isinstance(body, bytes) or len(body) > MAX_PAYLOAD_BYTES:
                raise sx.Refused("fetched payload exceeds the frozen bound")
            digest = hashlib.sha256(body).hexdigest()
            blob = self._cache._blob(digest)
            additional = 64
            if blob.exists() or blob.is_symlink():
                self._regular_size(blob, "SFIR4 payload-cache target blob", MAX_PAYLOAD_BYTES)
                if hashlib.sha256(blob.read_bytes()).hexdigest() != digest:
                    raise sx.Refused("pre-existing SFIR4 payload-cache blob is invalid")
            else:
                additional += len(body)
            if current + additional > MAX_ACQUISITION_PAYLOAD_CACHE_BYTES:
                raise sx.Refused("SFIR4 payload/state cache cannot admit another payload")
            if not blob.exists():
                self._cache._write(blob, body)
            self._cache._write(pointer, digest.encode("ascii"))
            self._tree_bytes()
            self._cache.misses += 1
            return body, digest

    def stats(self) -> dict[str, Any]:
        body = self._cache.stats()
        with self._lock:
            body.update(
                {
                    "aggregate_tree_bytes": self._tree_bytes(),
                    "aggregate_tree_bound_bytes": MAX_ACQUISITION_PAYLOAD_CACHE_BYTES,
                    "regular_files_only_no_symlinks": True,
                }
            )
        return body


def _ecfr_blob_bytes() -> int:
    blob_root = sx.ECFR_PART_CACHE_ROOT / "blobs"
    if not blob_root.exists():
        return 0
    total = 0
    for entry in os.scandir(blob_root):
        if entry.is_file(follow_symlinks=False):
            total += entry.stat(follow_symlinks=False).st_size
            if total > MAX_ECFR_TOTAL_CACHE_BYTES:
                raise sx.Refused("existing SFIR4 eCFR cache exceeds the frozen total bound")
    return total


def resolve_payload_locator(family: str, locator: str) -> str:
    """Use the hash-bound immutable locator grammar from the native worker."""
    try:
        return native.resolve_payload_locator(family, locator)
    except native.sx.Refused as error:
        raise sx.Refused(str(error)) from error


def _default_payload_fetcher(family: str, locator: str) -> bytes:
    """Fetch an immutable payload; SFIR4 owns its cache namespace."""
    resolved = resolve_payload_locator(family, locator)
    try:
        if family == "regulation_ecfr":
            key = __import__("hashlib").sha256(resolved.encode("utf-8")).hexdigest()
            pointer = sx.ECFR_PART_CACHE_ROOT / "pointers" / f"{key}.json"
            with _ECFR_CACHE_GUARD:
                current = _ecfr_blob_bytes()
                if (
                    not pointer.exists()
                    and current + MAX_ECFR_RAW_PART_BYTES > MAX_ECFR_TOTAL_CACHE_BYTES
                ):
                    raise sx.Refused("SFIR4 eCFR cache cannot admit another bounded raw part")
                raw = native._stream_ecfr_section(
                    resolved,
                    native._ecfr_section_id(locator),
                    cache_root=sx.ECFR_PART_CACHE_ROOT,
                )
                _ecfr_blob_bytes()
                return raw
        raw = native._bounded_http_get(resolved)
        if family == "encyclopedia_wikipedia":
            try:
                text = json.loads(raw)["parse"]["text"]
            except (KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as error:
                raise sx.Refused("MediaWiki immutable revision payload is malformed") from error
            if not isinstance(text, str):
                raise sx.Refused("MediaWiki immutable revision text is not a string")
            raw = text.encode("utf-8")
            if len(raw) > MAX_PAYLOAD_BYTES:
                raise sx.Refused("unwrapped MediaWiki payload exceeds the frozen bound")
        return raw
    except native.sx.Refused as error:
        raise sx.Refused(str(error)) from error


def _revision_adapter(candidate: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Revalidate identity aliases, then adapt only immutable revision metadata."""
    identity = [
        candidate.get("discovery_root_id"),
        candidate.get("root_container_id"),
        candidate.get("container_id"),
        candidate.get("lineage_id"),
    ]
    if any(not isinstance(value, str) or not value for value in identity):
        raise sx.Refused("SFIR4 candidate has an incomplete root/container/lineage/alias contract")
    aliases = candidate.get("alias_ids")
    if not isinstance(aliases, list) or any(
        not isinstance(value, str) or not value for value in aliases
    ):
        raise sx.Refused("SFIR4 candidate has malformed alias_ids")
    if set(aliases) & set(identity[1:]):
        raise sx.Refused("SFIR4 candidate identity aliases collide")
    try:
        return native._revision_adapter(candidate)
    except native.sx.Refused as error:
        raise sx.Refused(str(error)) from error


def _observe_one(
    candidate: dict[str, Any],
    payload_fetcher: Callable[[str, str], bytes | tuple[bytes, str]],
) -> dict[str, Any]:
    """Compute E1--E9; callers cannot inject outcomes or endpoint maps."""
    _revision_adapter(candidate)
    try:
        result = native._observe_one(candidate, payload_fetcher)
    except native.sx.Refused as error:
        raise sx.Refused(str(error)) from error
    observations = result.get("observations") if isinstance(result, dict) else None
    if result.get("status") == "OBSERVED" and (
        not isinstance(observations, dict) or set(observations) != set(sx.ENDPOINTS)
    ):
        raise sx.Refused("native scientific stack did not produce the exact SFIR4 endpoint domain")
    return result


def _preflight_json_budget(value: Any, remaining: int, active: set[int]) -> int:
    """Conservatively reject an oversized/cyclic body before JSON serialization."""
    if remaining < 0:
        raise sx.Refused("SFIR4 spool body exceeds the frozen pre-serialization bound")
    if value is None or isinstance(value, (bool, int, float)):
        if remaining < 32:
            raise sx.Refused("SFIR4 spool body exceeds the frozen pre-serialization bound")
        return remaining - 32
    if isinstance(value, str):
        required = 2 + 6 * len(value)
        if required > remaining:
            raise sx.Refused("SFIR4 spool body exceeds the frozen pre-serialization bound")
        return remaining - required
    if isinstance(value, (list, tuple, dict)):
        identity = id(value)
        if identity in active:
            raise sx.Refused("SFIR4 spool body contains a recursive JSON value")
        active.add(identity)
        try:
            remaining -= 2
            items = value.items() if isinstance(value, dict) else enumerate(value)
            for key, item in items:
                if isinstance(value, dict):
                    if not isinstance(key, str):
                        raise sx.Refused("SFIR4 spool JSON object has a non-string key")
                    remaining = _preflight_json_budget(key, remaining, active)
                remaining = _preflight_json_budget(item, remaining - 2, active)
            if remaining < 0:
                raise sx.Refused("SFIR4 spool body exceeds the frozen pre-serialization bound")
            return remaining
        finally:
            active.remove(identity)
    raise sx.Refused(f"SFIR4 spool body contains unsupported JSON type {type(value).__name__}")


def _serialized_json(body: dict[str, Any]) -> bytes:
    _preflight_json_budget(body, MAX_SCIENTIFIC_EVIDENCE_BYTES, set())
    encoder = json.JSONEncoder(indent=2, sort_keys=True, ensure_ascii=False)
    chunks: list[bytes] = []
    total = 0
    for chunk in encoder.iterencode(body):
        raw = chunk.encode("utf-8")
        total += len(raw)
        if total + 1 > MAX_SCIENTIFIC_EVIDENCE_BYTES:
            raise sx.Refused("SFIR4 spool body exceeds the frozen serialized bound")
        chunks.append(raw)
    chunks.append(b"\n")
    return b"".join(chunks)


def _write_bounded_spool_file(root: Path, path: Path, raw: bytes, label: str) -> None:
    if len(raw) > MAX_SCIENTIFIC_EVIDENCE_BYTES:
        raise sx.Refused(f"{label} exceeds the frozen per-file spool bound")
    lock = _tree_lock(root, _SPOOL_TREE_GUARD, _SPOOL_TREE_LOCKS)
    with lock:
        current = _bounded_regular_tree_bytes(
            root, MAX_OBSERVATION_SPOOL_BYTES, "SFIR4 observation spool"
        )
        if current + len(raw) > MAX_OBSERVATION_SPOOL_BYTES:
            raise sx.Refused("SFIR4 observation spool cannot admit another file")
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as error:
            raise sx.Refused(f"immutable {label} already exists: {path}") from error
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
        _bounded_regular_tree_bytes(root, MAX_OBSERVATION_SPOOL_BYTES, "SFIR4 observation spool")


def _write_content_addressed(directory: Path, body: dict[str, Any]) -> tuple[Path, str]:
    bare = {key: value for key, value in body.items() if key != "content_digest"}
    digest = sx.canonical_sha(bare)
    body["content_digest"] = digest
    path = directory / f"sfir4-observation-batch--{digest.split(':', 1)[1]}.json"
    _write_bounded_spool_file(directory, path, _serialized_json(body), "SFIR4 observation batch")
    return path, sx.sha_file(path)


def _write_scientific_evidence(
    directory: Path, candidate: dict[str, Any], result: dict[str, Any]
) -> dict[str, str]:
    body = {
        "schema": "tavonel.sfir4.scientific_evidence.v1",
        "protocol_id": sx.PROTOCOL_ID,
        "root_container_id": candidate["root_container_id"],
        "lineage_id": candidate["lineage_id"],
        "family": candidate["family"],
        "result": result,
    }
    digest = sx.canonical_sha(body)
    body["content_digest"] = digest
    path = directory / "evidence" / f"sfir4-scientific-evidence--{digest.split(':', 1)[1]}.json"
    _write_bounded_spool_file(directory, path, _serialized_json(body), "SFIR4 scientific evidence")
    return {"path": sx.relative(path), "sha256": sx.sha_file(path), "content_digest": digest}


def _verify_scientific_evidence_ref(ref: Any, lineage_id: str) -> None:
    if not isinstance(ref, dict) or set(ref) != {"path", "sha256", "content_digest"}:
        raise sx.Refused(f"{lineage_id} scientific evidence reference is malformed")
    path = (sx.ROOT / str(ref["path"])).resolve()
    evidence_root = (sx.OBSERVATION_DIR / "evidence").resolve()
    if path.parent != evidence_root or not path.name.startswith("sfir4-scientific-evidence--"):
        raise sx.Refused(f"{lineage_id} scientific evidence escaped the fixed spool")
    BoundedPayloadCache._regular_size(
        path, f"{lineage_id} scientific evidence", MAX_SCIENTIFIC_EVIDENCE_BYTES
    )
    if not path.is_file() or sx.sha_file(path) != ref["sha256"]:
        raise sx.Refused(f"{lineage_id} scientific evidence is absent or moved")
    body = sx.read_json(path)
    bare = {key: value for key, value in body.items() if key != "content_digest"}
    if (
        body.get("schema") != "tavonel.sfir4.scientific_evidence.v1"
        or body.get("protocol_id") != sx.PROTOCOL_ID
        or body.get("lineage_id") != lineage_id
        or body.get("content_digest") != sx.canonical_sha(bare)
        or body.get("content_digest") != ref["content_digest"]
        or path.name != f"sfir4-scientific-evidence--{ref['content_digest'].split(':', 1)[-1]}.json"
    ):
        raise sx.Refused(f"{lineage_id} scientific evidence binding is invalid")


def _verify_observation_batch(
    binding: Any,
    design_bindings: dict[str, Any],
    acquisition_spent_binding: dict[str, str],
) -> dict[str, Any]:
    if not isinstance(binding, dict) or set(binding) != {"path", "sha256"}:
        raise sx.Refused("observation batch reference is malformed")
    lock = _tree_lock(sx.OBSERVATION_DIR, _SPOOL_TREE_GUARD, _SPOOL_TREE_LOCKS)
    with lock:
        _bounded_regular_tree_bytes(
            sx.OBSERVATION_DIR,
            MAX_OBSERVATION_SPOOL_BYTES,
            "SFIR4 observation spool",
        )
    path = (sx.ROOT / str(binding["path"])).resolve()
    if path.parent != sx.OBSERVATION_DIR.resolve() or not path.name.startswith(
        "sfir4-observation-batch--"
    ):
        raise sx.Refused("observation batch escaped the fixed SFIR4 spool")
    BoundedPayloadCache._regular_size(
        path, "SFIR4 observation batch", MAX_SCIENTIFIC_EVIDENCE_BYTES
    )
    if not path.is_file() or sx.sha_file(path) != binding["sha256"]:
        raise sx.Refused("exact SFIR4 observation batch is absent or moved")
    body = sx.read_json(path)
    bare = {key: value for key, value in body.items() if key != "content_digest"}
    digest = sx.canonical_sha(bare)
    if (
        body.get("schema") != "tavonel.sfir4.observation_batch.v1"
        or body.get("protocol_id") != sx.PROTOCOL_ID
        or body.get("design_bindings") != design_bindings
        or body.get("acquisition_spent_authority") != acquisition_spent_binding
        or body.get("content_digest") != digest
        or path.name != f"sfir4-observation-batch--{digest.split(':', 1)[-1]}.json"
    ):
        raise sx.Refused("SFIR4 observation batch binding is invalid")
    observations = body.get("observations")
    evidence = body.get("evidence")
    rejected = body.get("rejected")
    if (
        not isinstance(observations, dict)
        or not isinstance(evidence, dict)
        or set(evidence) != set(observations)
        or not isinstance(rejected, list)
    ):
        raise sx.Refused("SFIR4 observation/evidence/rejection domains are malformed")
    seen: set[str] = set()
    for lineage_id, ref in evidence.items():
        if not isinstance(lineage_id, str) or not lineage_id or lineage_id in seen:
            raise sx.Refused("SFIR4 observation lineage domain is malformed")
        _verify_scientific_evidence_ref(ref, lineage_id)
        seen.add(lineage_id)
    for row in rejected:
        if not isinstance(row, dict) or not isinstance(row.get("lineage_id"), str):
            raise sx.Refused("SFIR4 rejected observation row is malformed")
        lineage_id = row["lineage_id"]
        if lineage_id in seen:
            raise sx.Refused("SFIR4 observed and rejected evidence domains overlap")
        _verify_scientific_evidence_ref(row.get("evidence_ref"), lineage_id)
        seen.add(lineage_id)
    return body


def _bounded_observe(
    candidates: list[dict[str, Any]],
    payload_fetcher: Callable[[str, str], bytes | tuple[bytes, str]],
    *,
    workers: int,
    observation_dir: Path,
) -> tuple[dict[str, dict[str, Any]], int]:
    if isinstance(workers, bool) or not isinstance(workers, int) or not 1 <= workers <= MAX_WORKERS:
        raise sx.Refused(f"workers must be an integer from 1 through {MAX_WORKERS}")
    bound = workers * IN_FLIGHT_PER_WORKER
    compact: dict[str, dict[str, Any]] = {}
    pending: dict[Future[dict[str, Any]], tuple[int, dict[str, Any]]] = {}
    next_index = 0
    with ThreadPoolExecutor(max_workers=workers) as executor:
        while next_index < len(candidates) and len(pending) < bound:
            row = candidates[next_index]
            pending[executor.submit(_observe_one, row, payload_fetcher)] = (next_index, row)
            next_index += 1
        while pending:
            completed, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in sorted(completed, key=lambda item: pending[item][0]):
                _, row = pending.pop(future)
                lineage = row["lineage_id"]
                try:
                    result = future.result()
                except Exception as error:
                    raise sx.Refused(
                        "scientific observation instrument failed for "
                        f"{lineage}: {type(error).__name__}: {error}"
                    ) from error
                evidence_ref = _write_scientific_evidence(observation_dir, row, result)
                if result.get("status") == "OBSERVED":
                    compact[lineage] = {
                        "status": "OBSERVED",
                        "observations": result["observations"],
                        "evidence_ref": evidence_ref,
                    }
                else:
                    compact[lineage] = {
                        "status": "REJECTED",
                        "code": result.get("code", REJECTION_INSTRUMENT),
                        "detail": result.get("detail"),
                        "evidence_ref": evidence_ref,
                    }
                del result
                if next_index < len(candidates):
                    next_row = candidates[next_index]
                    pending[executor.submit(_observe_one, next_row, payload_fetcher)] = (
                        next_index,
                        next_row,
                    )
                    next_index += 1
    return {row["lineage_id"]: compact[row["lineage_id"]] for row in candidates}, bound


def produce_observation_batch(
    bindings: dict[str, tuple[Path, str]],
    *,
    payload_fetcher: Callable[[str, str], bytes | tuple[bytes, str]] = _default_payload_fetcher,
    workers: int = 2,
    spent_authority: Path = sx.ACQUISITION_SPENT_AUTHORITY,
    observation_dir: Path = sx.OBSERVATION_DIR,
    acquisition_target: Path = sx.ACQUISITION,
    allow_test_paths: bool = False,
) -> tuple[dict[str, Any], Path, str]:
    if not allow_test_paths and (
        spent_authority.resolve() != sx.ACQUISITION_SPENT_AUTHORITY.resolve()
        or observation_dir.resolve() != sx.OBSERVATION_DIR.resolve()
        or acquisition_target.resolve() != sx.ACQUISITION.resolve()
    ):
        raise sx.Refused("SFIR4 acquisition requires its fixed spent/observation/output paths")
    verified = sx.verify_design_bindings(bindings)
    protocol = sx.verify_receipt("protocol_freeze", *bindings["protocol_freeze"])["body"]
    if protocol.get("acquisition_authorized") is not True:
        raise sx.Refused("exact SFIR4 protocol freeze does not authorize acquisition")
    roster_body = sx.verify_receipt("roster", *bindings["roster"])["body"]
    candidates = sx.roster_candidates(roster_body, bindings["roster"][0])
    for candidate in candidates:
        _revision_adapter(candidate)
    if acquisition_target.exists():
        raise sx.Refused("fixed SFIR4 acquisition already exists; corpus is spent")
    sx.exclusive_json(
        spent_authority,
        {
            "schema": sx.ACQUISITION_SPENT_SCHEMA,
            "protocol_id": sx.PROTOCOL_ID,
            "design_bindings": verified,
            "roster_candidates": len(candidates),
            "state": "PAYLOAD_READ_AUTHORIZED_CORPUS_SPENT",
            "single_writer": True,
            "no_preview_or_partial_score": True,
        },
    )
    acquisition_spent_binding = {
        "path": sx.relative(spent_authority),
        "sha256": sx.sha_file(spent_authority),
        "schema": sx.ACQUISITION_SPENT_SCHEMA,
    }
    cache_stats: dict[str, Any] | None = None
    if payload_fetcher is _default_payload_fetcher:
        cache = BoundedPayloadCache(sx.PAYLOAD_CACHE / "payload_state", sx.sha_file(Path(__file__)))

        def cached_fetch(family: str, locator: str) -> tuple[bytes, str]:
            raw, digest = cache.payload(
                locator, lambda _locator: _default_payload_fetcher(family, locator)
            )
            if len(raw) > MAX_PAYLOAD_BYTES:
                raise sx.Refused("cached payload exceeds the frozen bound")
            return raw, "sha256:" + digest

        active_fetcher: Callable[[str, str], bytes | tuple[bytes, str]] = cached_fetch
    else:
        active_fetcher = payload_fetcher
    results, in_flight_bound = _bounded_observe(
        candidates, active_fetcher, workers=workers, observation_dir=observation_dir
    )
    observations = {
        row["lineage_id"]: results[row["lineage_id"]]["observations"]
        for row in candidates
        if results[row["lineage_id"]].get("status") == "OBSERVED"
    }
    evidence = {
        row["lineage_id"]: results[row["lineage_id"]]["evidence_ref"]
        for row in candidates
        if results[row["lineage_id"]].get("status") == "OBSERVED"
    }
    rejected = [
        {
            "lineage_id": row["lineage_id"],
            "family": row["family"],
            "code": results[row["lineage_id"]].get("code", REJECTION_INSTRUMENT),
            "detail": results[row["lineage_id"]].get("detail"),
            "evidence_ref": results[row["lineage_id"]]["evidence_ref"],
        }
        for row in candidates
        if results[row["lineage_id"]].get("status") != "OBSERVED"
    ]
    if payload_fetcher is _default_payload_fetcher:
        cache_stats = cache.stats()
    batch = {
        "schema": "tavonel.sfir4.observation_batch.v1",
        "protocol_id": sx.PROTOCOL_ID,
        "design_bindings": verified,
        "acquisition_spent_authority": acquisition_spent_binding,
        "lineages_considered": len(candidates),
        "observations": observations,
        "evidence": evidence,
        "rejected": rejected,
        "reducer_input_order": "exact frozen roster order",
        "partial_score_or_preview": False,
        "payload_transport": {
            "opaque_locators_resolved_by": "sfir4_worker.resolve_payload_locator",
            "stream_read_bound_bytes": MAX_PAYLOAD_BYTES,
            "read_block_bytes": READ_BLOCK_BYTES,
            "cache": cache_stats,
            "ecfr_raw_part_cache": sx.relative(sx.ECFR_PART_CACHE_ROOT),
            "ecfr_raw_part_bound_bytes": MAX_ECFR_RAW_PART_BYTES,
            "ecfr_total_cache_bound_bytes": MAX_ECFR_TOTAL_CACHE_BYTES,
            "acquisition_payload_cache_total_bytes": MAX_ACQUISITION_PAYLOAD_CACHE_BYTES,
            "observation_spool_total_bytes": MAX_OBSERVATION_SPOOL_BYTES,
            "scientific_evidence_per_file_bytes": MAX_SCIENTIFIC_EVIDENCE_BYTES,
            "reused_native_module_hash_bound": True,
            "max_workers": workers,
            "max_in_flight": in_flight_bound,
            "max_payloads_resident": in_flight_bound * 2,
            "max_payload_bytes_resident": in_flight_bound * 2 * MAX_PAYLOAD_BYTES,
        },
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }
    path, digest = _write_content_addressed(observation_dir, batch)
    return batch, path, digest


def build(
    bindings: dict[str, tuple[Path, str]],
    *,
    observations: dict[str, dict],
    observation_binding: dict[str, str],
    rejected_observations: list[dict[str, Any]],
    acquisition_spent_binding: dict[str, str],
    target: Path = sx.ACQUISITION,
    allow_test_target: bool = False,
) -> dict[str, Any]:
    if not allow_test_target and target.resolve() != sx.ACQUISITION.resolve():
        raise sx.Refused("SFIR4 acquisition has one fixed authority path")
    verified = sx.verify_design_bindings(bindings)
    sx.verify_acquisition_spent_binding(acquisition_spent_binding, verified)
    batch = _verify_observation_batch(observation_binding, verified, acquisition_spent_binding)
    if observations != batch.get("observations") or rejected_observations != batch.get("rejected"):
        raise sx.Refused("caller observation inputs differ from the exact immutable batch")
    roster_body = sx.verify_receipt("roster", *bindings["roster"])["body"]
    candidates = sx.roster_candidates(roster_body, bindings["roster"][0])
    roster_ids = {row["lineage_id"] for row in candidates}
    rejected_ids = {row.get("lineage_id") for row in rejected_observations}
    if set(observations) | rejected_ids != roster_ids or set(observations) & rejected_ids:
        raise sx.Refused(
            "observation and rejection domains do not partition the frozen SFIR4 roster"
        )
    reduced = sx.deterministic_reduce(
        [row for row in candidates if row["lineage_id"] in observations]
    )
    for row in reduced["admitted"]:
        blocks = observations[row["lineage_id"]]
        if not isinstance(blocks, dict) or set(blocks) != set(sx.ENDPOINTS):
            raise sx.Refused(f"observation endpoint domain differs for {row['lineage_id']}")
        row["endpoint_observations"] = blocks
    by_family: dict[str, int] = {}
    for row in reduced["admitted"]:
        by_family[row["family"]] = by_family.get(row["family"], 0) + 1
    body = {
        "schema": "tavonel.sfir4.acquisition.v1",
        "protocol_id": sx.PROTOCOL_ID,
        "design_bindings": verified,
        "acquisition_spent_authority": acquisition_spent_binding,
        "frame": {"candidates": len(candidates), "roster_order_is_authoritative": True},
        "lineages_considered": len(candidates),
        "by_family": dict(sorted(by_family.items())),
        **reduced,
        "observation_rejections": rejected_observations,
        "outcome_blind_reduction": True,
        "acquisition_state": "ACQUIRED",
        "observation_binding": observation_binding,
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }
    sx.exclusive_json(target, body)
    return body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    for name in sx.SCHEMAS:
        parser.add_argument(f"--{name.replace('_', '-')}", type=Path, required=True)
        parser.add_argument(f"--{name.replace('_', '-')}-sha256", required=True)
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args(argv)
    bindings = {name: (getattr(args, name), getattr(args, name + "_sha256")) for name in sx.SCHEMAS}
    try:
        batch, observation_path, observation_sha = produce_observation_batch(
            bindings, workers=args.workers
        )
        body = build(
            bindings,
            observations=batch["observations"],
            observation_binding={"path": sx.relative(observation_path), "sha256": observation_sha},
            rejected_observations=batch["rejected"],
            acquisition_spent_binding=batch["acquisition_spent_authority"],
        )
        print(
            json.dumps(
                {
                    "state": "ACQUIRED",
                    "admitted": len(body["admitted"]),
                    "output": sx.relative(sx.ACQUISITION),
                },
                indent=2,
            )
        )
        return 0
    except sx.Refused as error:
        print(json.dumps({"state": "REFUSED", "why": str(error)}, indent=2), file=sys.stderr)
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
