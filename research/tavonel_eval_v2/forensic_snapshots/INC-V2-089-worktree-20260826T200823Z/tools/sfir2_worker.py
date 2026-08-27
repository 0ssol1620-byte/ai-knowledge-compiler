#!/usr/bin/env python3
"""Execute the exact SFIR2 roster once through the native scientific stack."""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(NS / "tools"))
import sfir1_worker as native  # noqa: E402
import sfir2_execution as sx  # noqa: E402

MAX_PAYLOAD_BYTES = 2_000_000
READ_BLOCK_BYTES = 64 * 1024
MAX_WORKERS = 16
IN_FLIGHT_PER_WORKER = 2
MAX_ECFR_RAW_PART_BYTES = 256 * 1024 * 1024
MAX_ECFR_TOTAL_CACHE_BYTES = 8 * 1024 * 1024 * 1024
REJECTION_INSTRUMENT = "INSTRUMENT_UNAVAILABLE"
USER_AGENT = "TAVONEL-SFIR2-scientific-acquisition/1.0"
_ECFR_CACHE_GUARD = threading.Lock()


def _ecfr_blob_bytes() -> int:
    blob_root = sx.ECFR_PART_CACHE_ROOT / "blobs"
    if not blob_root.exists():
        return 0
    total = 0
    for entry in os.scandir(blob_root):
        if entry.is_file(follow_symlinks=False):
            total += entry.stat(follow_symlinks=False).st_size
            if total > MAX_ECFR_TOTAL_CACHE_BYTES:
                raise sx.Refused("existing SFIR2 eCFR cache exceeds the frozen total bound")
    return total


def resolve_payload_locator(family: str, locator: str) -> str:
    """Use the hash-bound immutable locator grammar from the native worker."""
    try:
        return native.resolve_payload_locator(family, locator)
    except native.sx.Refused as error:
        raise sx.Refused(str(error)) from error


def _default_payload_fetcher(family: str, locator: str) -> bytes:
    """Fetch an immutable payload; SFIR2 owns its cache namespace."""
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
                    raise sx.Refused("SFIR2 eCFR cache cannot admit another bounded raw part")
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
        raise sx.Refused("SFIR2 candidate has an incomplete root/container/lineage/alias contract")
    aliases = candidate.get("alias_ids")
    if not isinstance(aliases, list) or any(
        not isinstance(value, str) or not value for value in aliases
    ):
        raise sx.Refused("SFIR2 candidate has malformed alias_ids")
    if set(aliases) & set(identity[1:]):
        raise sx.Refused("SFIR2 candidate identity aliases collide")
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
        raise sx.Refused("native scientific stack did not produce the exact SFIR2 endpoint domain")
    return result


def _write_content_addressed(directory: Path, body: dict[str, Any]) -> tuple[Path, str]:
    bare = {key: value for key, value in body.items() if key != "content_digest"}
    digest = sx.canonical_sha(bare)
    body["content_digest"] = digest
    path = directory / f"sfir2-observation-batch--{digest.split(':', 1)[1]}.json"
    directory.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as error:
        raise sx.Refused(f"immutable SFIR2 observation batch already exists: {path}") from error
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(body, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")
    return path, sx.sha_file(path)


def _write_scientific_evidence(
    directory: Path, candidate: dict[str, Any], result: dict[str, Any]
) -> dict[str, str]:
    body = {
        "schema": "tavonel.sfir2.scientific_evidence.v1",
        "protocol_id": sx.PROTOCOL_ID,
        "root_container_id": candidate["root_container_id"],
        "lineage_id": candidate["lineage_id"],
        "family": candidate["family"],
        "result": result,
    }
    digest = sx.canonical_sha(body)
    body["content_digest"] = digest
    path = directory / "evidence" / f"sfir2-scientific-evidence--{digest.split(':', 1)[1]}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as error:
        raise sx.Refused(f"immutable SFIR2 scientific evidence already exists: {path}") from error
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(body, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")
    return {"path": sx.relative(path), "sha256": sx.sha_file(path), "content_digest": digest}


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
    workers: int = 8,
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
        raise sx.Refused("SFIR2 acquisition requires its fixed spent/observation/output paths")
    verified = sx.verify_design_bindings(bindings)
    protocol = sx.verify_receipt("protocol_freeze", *bindings["protocol_freeze"])["body"]
    if protocol.get("acquisition_authorized") is not True:
        raise sx.Refused("exact SFIR2 protocol freeze does not authorize acquisition")
    roster_body = sx.verify_receipt("roster", *bindings["roster"])["body"]
    candidates = sx.roster_candidates(roster_body, bindings["roster"][0])
    for candidate in candidates:
        _revision_adapter(candidate)
    if acquisition_target.exists():
        raise sx.Refused("fixed SFIR2 acquisition already exists; corpus is spent")
    sx.exclusive_json(
        spent_authority,
        {
            "schema": "tavonel.sfir2.acquisition_spent_authority.v1",
            "protocol_id": sx.PROTOCOL_ID,
            "design_bindings": verified,
            "roster_candidates": len(candidates),
            "state": "PAYLOAD_READ_AUTHORIZED_CORPUS_SPENT",
            "single_writer": True,
            "no_preview_or_partial_score": True,
        },
    )
    cache_stats: dict[str, Any] | None = None
    if payload_fetcher is _default_payload_fetcher:
        from payload_cache import PayloadCache

        cache = PayloadCache(sx.PAYLOAD_CACHE, sx.sha_file(Path(__file__)))

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
        "schema": "tavonel.sfir2.observation_batch.v1",
        "protocol_id": sx.PROTOCOL_ID,
        "design_bindings": verified,
        "lineages_considered": len(candidates),
        "observations": observations,
        "evidence": evidence,
        "rejected": rejected,
        "reducer_input_order": "exact frozen roster order",
        "partial_score_or_preview": False,
        "payload_transport": {
            "opaque_locators_resolved_by": "sfir2_worker.resolve_payload_locator",
            "stream_read_bound_bytes": MAX_PAYLOAD_BYTES,
            "read_block_bytes": READ_BLOCK_BYTES,
            "cache": cache_stats,
            "ecfr_raw_part_cache": sx.relative(sx.ECFR_PART_CACHE_ROOT),
            "ecfr_raw_part_bound_bytes": MAX_ECFR_RAW_PART_BYTES,
            "ecfr_total_cache_bound_bytes": MAX_ECFR_TOTAL_CACHE_BYTES,
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
    target: Path = sx.ACQUISITION,
    allow_test_target: bool = False,
) -> dict[str, Any]:
    if not allow_test_target and target.resolve() != sx.ACQUISITION.resolve():
        raise sx.Refused("SFIR2 acquisition has one fixed authority path")
    verified = sx.verify_design_bindings(bindings)
    roster_body = sx.verify_receipt("roster", *bindings["roster"])["body"]
    candidates = sx.roster_candidates(roster_body, bindings["roster"][0])
    roster_ids = {row["lineage_id"] for row in candidates}
    rejected_ids = {row.get("lineage_id") for row in rejected_observations}
    if set(observations) | rejected_ids != roster_ids or set(observations) & rejected_ids:
        raise sx.Refused(
            "observation and rejection domains do not partition the frozen SFIR2 roster"
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
        "schema": "tavonel.sfir2.acquisition.v1",
        "protocol_id": sx.PROTOCOL_ID,
        "design_bindings": verified,
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
    parser.add_argument("--workers", type=int, default=8)
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
