#!/usr/bin/env python3
"""Acquire SFIR1 from one exact frozen roster, then reduce deterministically.

The post-freeze path in this module is the only component allowed to dereference
the roster's immutable before/after locators.  Scientific semantics are not
implemented here: pair extraction is SFI1's native driver, rebuild judgement is
SFI2's :class:`RebuildJudge`, and E1--E9 observations are read through the
existing SFI1/SFI3 endpoint contracts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Any, Callable

NS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(NS / "tools"))
import sfir1_execution as sx  # noqa: E402

for _sub in ("acquisition", "canonicalization", "compiler", "source_fact_ir"):
    sys.path.insert(0, str(NS / _sub))

REJECTION_INSTRUMENT = "INSTRUMENT_UNAVAILABLE"
FAMILY_SUFFIX = {
    "git_docs": ".md",
    "regulation_ecfr": ".xml",
    "encyclopedia_wikipedia": ".html",
}
MAX_PAYLOAD_BYTES = 2_000_000
READ_BLOCK_BYTES = 64 * 1024
MAX_ECFR_RAW_PART_BYTES = 256 * 1024 * 1024
USER_AGENT = "TAVONEL-SFIR1-scientific-acquisition/1.0"
ECFR_PART_CACHE_ROOT = sx.PAYLOAD_CACHE / "ecfr_raw_parts"
MAX_WORKERS = 16
IN_FLIGHT_PER_WORKER = 2


def resolve_payload_locator(family: str, locator: str) -> str:
    """Translate one frozen opaque locator to its authority's immutable URL."""
    parsed = urllib.parse.urlparse(locator)
    if family == "git_docs":
        if parsed.scheme != "github":
            raise sx.Refused("git_docs payload locator does not use github://")
        pieces = [parsed.netloc, *parsed.path.lstrip("/").split("/")]
        if len(pieces) < 5 or pieces[2] != "blob":
            raise sx.Refused("github payload locator has the wrong immutable shape")
        owner, repo, _blob, revision, *document = pieces
        if not owner or not repo or not revision or not document:
            raise sx.Refused("github payload locator is incomplete")
        return (
            f"https://raw.githubusercontent.com/{urllib.parse.quote(owner)}/"
            f"{urllib.parse.quote(repo)}/{urllib.parse.quote(revision, safe='')}/"
            + "/".join(urllib.parse.quote(part) for part in document)
        )
    if family == "regulation_ecfr":
        pieces = parsed.path.strip("/").split("/")
        query = urllib.parse.parse_qs(parsed.query, strict_parsing=True)
        if (
            parsed.scheme != "ecfr"
            or parsed.netloc != "title"
            or len(pieces) != 5
            or pieces[1] != "part"
            or pieces[3] != "section"
        ):
            raise sx.Refused("eCFR payload locator has the wrong immutable shape")
        if set(query) != {"version"} or len(query["version"]) != 1:
            raise sx.Refused("eCFR payload locator has no exact version")
        title, part, section, version = pieces[0], pieces[2], pieces[4], query["version"][0]
        if not title.isdigit() or not part or not section or not version:
            raise sx.Refused("eCFR payload locator is incomplete")
        return (
            "https://www.ecfr.gov/api/versioner/v1/full/"
            f"{urllib.parse.quote(version, safe='')}/title-{int(title)}.xml?"
            + urllib.parse.urlencode({"part": part})
        )
    if family == "encyclopedia_wikipedia":
        pieces = parsed.path.strip("/").split("/")
        if (
            parsed.scheme != "mediawiki"
            or parsed.netloc != "en.wikipedia.org"
            or len(pieces) != 4
            or pieces[0] != "page"
            or pieces[2] != "revision"
        ):
            raise sx.Refused("MediaWiki payload locator has the wrong immutable shape")
        page_id, revision = pieces[1], pieces[3]
        if not page_id.isdigit() or not revision.isdigit():
            raise sx.Refused("MediaWiki payload locator ids are not numeric")
        return "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode(
            {
                "action": "parse",
                "pageid": page_id,
                "oldid": revision,
                "prop": "text",
                "format": "json",
                "formatversion": 2,
            }
        )
    raise sx.Refused(f"unknown SFIR1 payload family {family!r}")


def _bounded_http_get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - resolver pins HTTPS hosts
        declared = response.headers.get("Content-Length")
        if declared is not None and int(declared) > MAX_PAYLOAD_BYTES:
            raise sx.Refused("payload Content-Length exceeds the frozen bound")
        body = bytearray()
        while True:
            block = response.read(READ_BLOCK_BYTES)
            if not block:
                break
            body.extend(block)
            if len(body) > MAX_PAYLOAD_BYTES:
                raise sx.Refused("streamed payload exceeds the frozen bound")
    return bytes(body)


def _ecfr_section_id(locator: str) -> str:
    parsed = urllib.parse.urlparse(locator)
    pieces = parsed.path.strip("/").split("/")
    if parsed.scheme != "ecfr" or parsed.netloc != "title" or len(pieces) != 5:
        raise sx.Refused("eCFR locator cannot identify one section")
    return urllib.parse.unquote(pieces[4])


def _normalise_ecfr_identifier(value: str) -> str:
    return "".join(value.replace("§", "").split()).casefold()


def _ecfr_label_matches(label: str, wanted: str) -> bool:
    normal = _normalise_ecfr_identifier(label)
    if normal == wanted:
        return True
    match = re.search(r"(?:§|section)\s*([0-9]+(?:\.[0-9A-Za-z_-]+)*)", label, re.IGNORECASE)
    return bool(match and _normalise_ecfr_identifier(match.group(1)) == wanted)


def _stream_ecfr_section(
    url: str,
    section_id: str,
    *,
    cache_root: Path | None = None,
) -> bytes:
    """Materialize one immutable part once, then isolate one exact section.

    The complete local file is parsed before a match is returned.  Thus a
    truncated or malformed tail cannot be mistaken for a valid target merely
    because the requested section appeared early in the response.
    """
    from ecfr_raw_part_cache import EcfrRawPartCache, RawPartCacheError

    wanted = _normalise_ecfr_identifier(section_id)
    cache = EcfrRawPartCache(
        cache_root or ECFR_PART_CACHE_ROOT,
        max_bytes=MAX_ECFR_RAW_PART_BYTES,
        block_bytes=READ_BLOCK_BYTES,
    )
    try:
        part_path, _part_digest = cache.materialize(url, user_agent=USER_AGENT)
    except RawPartCacheError as error:
        raise sx.Refused(str(error)) from error
    matched: bytes | None = None
    matches = 0
    try:
        with part_path.open("rb") as response:
            for _event, element in ET.iterparse(  # noqa: S314 - bounded official XML, no entity use
                response, events=("end",)
            ):
                tag = str(element.tag).rsplit("}", 1)[-1].upper()
                if (
                    tag not in {"DIV8", "SECTION"}
                    and str(element.attrib.get("TYPE", "")).upper() != "SECTION"
                ):
                    continue
                labels = [str(element.attrib.get(key, "")) for key in ("N", "ID")]
                for child in element.iter():
                    if str(child.tag).rsplit("}", 1)[-1].upper() in {"SECTNO", "HEAD"}:
                        labels.append("".join(child.itertext()))
                if any(wanted and _ecfr_label_matches(label, wanted) for label in labels):
                    payload = ET.tostring(element, encoding="utf-8")
                    if len(payload) > MAX_PAYLOAD_BYTES:
                        raise sx.Refused("isolated eCFR section exceeds the frozen bound")
                    matched = payload
                    matches += 1
                # Completed non-target sections are discarded as the stream
                # advances, preventing a full historical part tree accumulating.
                element.clear()
    except (ET.ParseError, OSError) as error:
        raise sx.Refused("historical eCFR part XML is malformed or unreadable") from error
    if matches > 1:
        raise sx.Refused(f"exact eCFR section {section_id!r} is ambiguous in historical part")
    if matched is not None:
        return matched
    raise sx.Refused(f"exact eCFR section {section_id!r} is absent from historical part")


def _revision_adapter(candidate: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Audit the frozen metadata contract and adapt it to SFI1's pure pair API.

    This deliberately does not use ``base.reduce_results``: that reducer reads
    the old study's ``frame_module.FAMILY_QUOTA``.  SFIR1's roster has already
    frozen its family allocation, so importing that quota would silently apply
    the wrong study's admission rule.  Only the per-pair extractor is reused.
    """
    lineage = str(candidate.get("lineage_id") or "")
    family = candidate.get("family")
    if family not in FAMILY_SUFFIX:
        raise sx.Refused(f"{lineage} has an unsupported frozen family")
    refs = candidate.get("payload_ref")
    revisions = candidate.get("revision_id")
    timestamps = candidate.get("revision_timestamp")
    for name, value in (
        ("payload_ref", refs),
        ("revision_id", revisions),
        ("revision_timestamp", timestamps),
    ):
        if not isinstance(value, dict) or set(value) != {"before", "after"}:
            raise sx.Refused(f"{lineage} {name} is not an exact before/after mapping")
        if any(not isinstance(value[side], str) or not value[side] for side in ("before", "after")):
            raise sx.Refused(f"{lineage} {name} contains an empty value")
    if revisions["before"] == revisions["after"]:
        raise sx.Refused(f"{lineage} before and after revision ids are equal")
    # RFC3339 UTC strings sort chronologically in their canonical Z form.  The
    # census contract is responsible for canonicalisation; the worker verifies
    # the strict direction before opening either locator.
    if not timestamps["before"].endswith("Z") or not timestamps["after"].endswith("Z"):
        raise sx.Refused(f"{lineage} revision timestamps are not canonical RFC3339 UTC")
    if timestamps["before"] >= timestamps["after"]:
        raise sx.Refused(f"{lineage} revision timestamps are not strictly increasing")
    adapted = dict(candidate)
    suffix = FAMILY_SUFFIX[family]
    if family == "git_docs":
        before_name = refs["before"].split("?", 1)[0].casefold()
        after_name = refs["after"].split("?", 1)[0].casefold()
        choices = [
            extension
            for extension in (".md", ".mdx", ".rst")
            if before_name.endswith(extension) and after_name.endswith(extension)
        ]
        if len(choices) != 1:
            raise sx.Refused(f"{lineage} Git revisions do not name one supported document type")
        suffix = choices[0]
    adapted["suffix"] = suffix
    pair = [
        {"version": revisions["after"], "known_at": timestamps["after"], "url": refs["after"]},
        {"version": revisions["before"], "known_at": timestamps["before"], "url": refs["before"]},
    ]
    return adapted, pair


def _default_payload_fetcher(family: str, locator: str) -> bytes:
    """Dereference through the existing source fetcher; no endpoint semantics."""
    import json as _json

    resolved = resolve_payload_locator(family, locator)
    raw = (
        _stream_ecfr_section(resolved, _ecfr_section_id(locator))
        if family == "regulation_ecfr"
        else _bounded_http_get(resolved)
    )
    if family == "encyclopedia_wikipedia":
        try:
            text = _json.loads(raw)["parse"]["text"]
        except (KeyError, TypeError, UnicodeDecodeError, _json.JSONDecodeError) as error:
            raise sx.Refused("MediaWiki immutable revision payload is malformed") from error
        if not isinstance(text, str):
            raise sx.Refused("MediaWiki immutable revision text is not a string")
        raw = text.encode("utf-8")
        if len(raw) > MAX_PAYLOAD_BYTES:
            raise sx.Refused("unwrapped MediaWiki payload exceeds the frozen bound")
    return raw


def _observe_one(
    candidate: dict[str, Any],
    payload_fetcher: Callable[[str, str], bytes | tuple[bytes, str]],
) -> dict[str, Any]:
    """Return one native pair plus observations, or one explicit rejection."""
    import sfi1_worker as base
    import sfi2_worker as sfi2
    import score_sfi1 as fact_scorer
    import score_sfi3 as endpoint_contract

    # SFI2's worker imports the registry under this historical module name; use
    # the identical object so its lane registrations are visible to the judge.
    import ir
    from compile import load_lanes

    load_lanes()

    adapted, revisions = _revision_adapter(candidate)

    def revisions_for(_lineage: dict[str, Any]) -> list[dict[str, str]]:
        return revisions

    def payload_for(lineage: dict[str, Any], revision: dict[str, str]) -> tuple[bytes, str]:
        fetched = payload_fetcher(lineage["family"], revision["url"])
        if isinstance(fetched, tuple):
            raw, digest = fetched
        else:
            raw = fetched
            digest = "sha256:" + hashlib.sha256(raw).hexdigest()
        if not isinstance(raw, bytes) or not isinstance(digest, str):
            raise TypeError("payload fetcher did not return bytes and a digest")
        return raw, digest

    judge = sfi2.RebuildJudge(ir.extract_all)
    result = base.evaluate(
        adapted,
        payload_for,
        revisions_for=revisions_for,
        document_for=sfi2.document_for,
        extract=judge,
    )
    if result.get("code") is not None:
        return {"status": "REJECTED", "code": result["code"], "detail": result.get("detail")}
    if judge.errors or len(judge.verdicts) != 1:
        return {
            "status": "REJECTED",
            "code": REJECTION_INSTRUMENT,
            "detail": judge.errors or f"expected one rebuild verdict, found {len(judge.verdicts)}",
        }

    fact_rows = fact_scorer.endpoint_rows(result)
    rebuild = judge.verdicts[0]
    executor = __import__("rebuild_equivalence").summarise([rebuild])
    observations: dict[str, dict[str, Any]] = {}
    for endpoint in endpoint_contract.FACT_ENDPOINTS:
        violations, exercised = fact_rows[endpoint]
        observations[endpoint] = {
            "exercised": bool(exercised),
            "violations": int(violations),
            "stages_checked": [],
        }
    for endpoint, block_name, violation_key, _cases_key in endpoint_contract.EXECUTOR_BLOCKS:
        block = executor[block_name]
        observations[endpoint] = {
            "exercised": bool(block["gate_power"]),
            "violations": int(block[violation_key]),
            "stages_checked": list(block.get("stages_checked") or []),
        }
    if set(observations) != set(sx.ENDPOINTS):
        raise sx.Refused("existing endpoint contracts did not produce the exact SFIR1 domain")
    return {
        "status": "OBSERVED",
        "observations": observations,
        "evidence": {"pair": result, "rebuild": rebuild.as_dict()},
    }


def _write_content_addressed(directory: Path, body: dict[str, Any]) -> tuple[Path, str]:
    bare = {key: value for key, value in body.items() if key != "content_digest"}
    digest = sx.canonical_sha(bare)
    body["content_digest"] = digest
    path = directory / f"sfir1-observation-batch--{digest.split(':', 1)[1]}.json"
    directory.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as error:
        raise sx.Refused(f"immutable observation batch already exists: {path}") from error
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(body, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")
    return path, sx.sha_file(path)


def _write_scientific_evidence(
    directory: Path,
    candidate: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, str]:
    """Spool one full result and return the only copy retained by the batch.

    The lineage and family are included in the hashed body, so even two
    scientifically identical pairs remain separately auditable observations.
    The caller drops ``result`` immediately after this function returns.
    """
    body = {
        "schema": "tavonel.sfir1.scientific_evidence.v1",
        "protocol_id": sx.PROTOCOL_ID,
        "lineage_id": candidate["lineage_id"],
        "family": candidate["family"],
        "result": result,
    }
    digest = sx.canonical_sha(body)
    body["content_digest"] = digest
    path = directory / "evidence" / f"sfir1-scientific-evidence--{digest.split(':', 1)[1]}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as error:
        raise sx.Refused(f"immutable scientific evidence already exists: {path}") from error
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(body, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")
    return {
        "path": sx.relative(path),
        "sha256": sx.sha_file(path),
        "content_digest": digest,
    }


def _bounded_observe(
    candidates: list[dict[str, Any]],
    payload_fetcher: Callable[[str, str], bytes | tuple[bytes, str]],
    *,
    workers: int,
    observation_dir: Path,
) -> tuple[dict[str, dict[str, Any]], int]:
    """Observe with a fixed-size submission window and spool on completion.

    Compact results may accumulate because the terminal batch needs one entry
    per lineage. Full pair/rebuild bodies and payload bytes never do: no more
    than ``workers * IN_FLIGHT_PER_WORKER`` futures are submitted, and every
    completed full result is written before another candidate is submitted.
    """
    if isinstance(workers, bool) or not isinstance(workers, int) or not 1 <= workers <= MAX_WORKERS:
        raise sx.Refused(f"workers must be an integer from 1 through {MAX_WORKERS}")
    in_flight_bound = workers * IN_FLIGHT_PER_WORKER
    compact: dict[str, dict[str, Any]] = {}
    next_candidate = 0
    pending: dict[Future[dict[str, Any]], tuple[int, dict[str, Any]]] = {}

    with ThreadPoolExecutor(max_workers=workers) as executor:
        while next_candidate < len(candidates) and len(pending) < in_flight_bound:
            row = candidates[next_candidate]
            pending[executor.submit(_observe_one, row, payload_fetcher)] = (next_candidate, row)
            next_candidate += 1

        while pending:
            completed, _ = wait(pending, return_when=FIRST_COMPLETED)
            # Completion timing has no authority over output order. Sorting is
            # also useful for deterministic failure selection when several
            # futures finish between two scheduler wakeups.
            for future in sorted(completed, key=lambda item: pending[item][0]):
                _index, row = pending.pop(future)
                lineage = row["lineage_id"]
                try:
                    result = future.result()
                except Exception as error:
                    raise sx.Refused(
                        f"scientific observation instrument failed for {lineage}: "
                        f"{type(error).__name__}: {error}"
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
                # Do not retain the full pair/rebuild body while later work is
                # running. The immutable file above is now its sole owner.
                del result

                if next_candidate < len(candidates):
                    next_row = candidates[next_candidate]
                    pending[executor.submit(_observe_one, next_row, payload_fetcher)] = (
                        next_candidate,
                        next_row,
                    )
                    next_candidate += 1

    # Rebuild insertion order from the frozen roster. Completion order is an
    # implementation detail and must not leak into canonical batch bytes.
    ordered = {row["lineage_id"]: compact[row["lineage_id"]] for row in candidates}
    return ordered, in_flight_bound


def produce_observation_batch(
    bindings: dict[str, tuple[Path, str]],
    *,
    payload_fetcher: Callable[[str, str], bytes | tuple[bytes, str]] = _default_payload_fetcher,
    workers: int = 8,
    spent_authority: Path = sx.ACQUISITION_SPENT_AUTHORITY,
    observation_dir: Path = sx.OBSERVATION_DIR,
    acquisition_target: Path = sx.ACQUISITION,
) -> tuple[dict[str, Any], Path, str]:
    """Spend the exact roster once and write its content-addressed observations."""
    verified = sx.verify_design_bindings(bindings)
    protocol = sx.verify_receipt("protocol_freeze", *bindings["protocol_freeze"])["body"]
    if protocol.get("acquisition_authorized") is not True:
        raise sx.Refused("exact protocol freeze does not authorize acquisition")
    roster_body = sx.verify_receipt("roster", *bindings["roster"])["body"]
    candidates = sx.roster_candidates(roster_body, bindings["roster"][0])
    # Validate the complete roster before the irreversible spent marker or any
    # payload read.  A malformed metadata row must not waste the corpus.
    for candidate in candidates:
        _revision_adapter(candidate)
    if acquisition_target.exists():
        raise sx.Refused("fixed SFIR1 acquisition already exists; corpus is spent")
    sx.exclusive_json(
        spent_authority,
        {
            "schema": "tavonel.sfir1.acquisition_spent_authority.v1",
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
        candidates,
        active_fetcher,
        workers=workers,
        observation_dir=observation_dir,
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
        "schema": "tavonel.sfir1.observation_batch.v1",
        "protocol_id": sx.PROTOCOL_ID,
        "design_bindings": verified,
        "lineages_considered": len(candidates),
        "observations": observations,
        "evidence": evidence,
        "rejected": rejected,
        "reducer_input_order": "exact frozen roster order",
        "partial_score_or_preview": False,
        "payload_transport": {
            "opaque_locators_resolved_by": "sfir1_worker.resolve_payload_locator",
            "stream_read_bound_bytes": MAX_PAYLOAD_BYTES,
            "read_block_bytes": READ_BLOCK_BYTES,
            "cache": cache_stats,
            "cache_storage": "content-addressed disk; no process payload retention",
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
    observations: dict[str, dict] | None = None,
    observation_binding: dict[str, str] | None = None,
    rejected_observations: list[dict[str, Any]] | None = None,
    target: Path = sx.ACQUISITION,
) -> dict:
    verified = sx.verify_design_bindings(bindings)
    roster_body = sx.verify_receipt("roster", *bindings["roster"])["body"]
    candidates = sx.roster_candidates(roster_body, bindings["roster"][0])
    observed_candidates = candidates
    if observations is not None:
        roster_ids = {row["lineage_id"] for row in candidates}
        if not set(observations) <= roster_ids:
            raise sx.Refused("observation batch contains a lineage outside the exact frozen roster")
        rejected_ids = {row.get("lineage_id") for row in (rejected_observations or [])}
        if set(observations) | rejected_ids != roster_ids or set(observations) & rejected_ids:
            raise sx.Refused("observation and rejection domains do not partition the frozen roster")
        observed_candidates = [row for row in candidates if row["lineage_id"] in observations]
    reduced = sx.deterministic_reduce(observed_candidates)
    if observations is not None:
        for row in reduced["admitted"]:
            blocks = observations[row["lineage_id"]]
            if not isinstance(blocks, dict) or set(blocks) != set(sx.ENDPOINTS):
                raise sx.Refused(f"observation endpoint domain differs for {row['lineage_id']}")
            row["endpoint_observations"] = blocks
    by_family: dict[str, int] = {}
    for row in reduced["admitted"]:
        family = row["family"]
        by_family[family] = by_family.get(family, 0) + 1
    body = {
        "schema": "tavonel.sfir1.acquisition.v1",
        "protocol_id": sx.PROTOCOL_ID,
        "design_bindings": verified,
        "frame": {"candidates": len(candidates), "roster_order_is_authoritative": True},
        "lineages_considered": len(candidates),
        "by_family": dict(sorted(by_family.items())),
        **reduced,
        "observation_rejections": rejected_observations or [],
        "outcome_blind_reduction": True,
        "acquisition_state": "ACQUIRED" if observations is not None else "ROSTER_STAGED",
        "observation_binding": observation_binding,
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    sx.exclusive_json(target, body)
    return body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    for name in sx.SCHEMAS:
        parser.add_argument(f"--{name.replace('_', '-')}", type=Path, required=True)
        parser.add_argument(f"--{name.replace('_', '-')}-sha256", required=True)
    parser.add_argument("--output", type=Path, default=sx.ACQUISITION)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args(argv)
    bindings = {name: (getattr(args, name), getattr(args, name + "_sha256")) for name in sx.SCHEMAS}
    try:
        # There is intentionally no CLI option for a caller-supplied observation
        # map. The production command must create observations through the
        # frozen scientific stack after the spent guard; injected batches exist
        # only as an in-process unit-test seam.
        batch, observation_path, observation_sha = produce_observation_batch(
            bindings, workers=args.workers, acquisition_target=args.output
        )
        if (
            batch.get("schema") != "tavonel.sfir1.observation_batch.v1"
            or batch.get("protocol_id") != sx.PROTOCOL_ID
        ):
            raise sx.Refused("observation batch schema or protocol_id differs")
        rows = batch.get("observations")
        if not isinstance(rows, dict):
            raise sx.Refused("observation batch observations is not a lineage map")
        body = build(
            bindings,
            observations=rows,
            observation_binding={"path": sx.relative(observation_path), "sha256": observation_sha},
            rejected_observations=batch.get("rejected") or [],
            target=args.output,
        )
        print(
            json.dumps(
                {
                    "state": "ACQUIRED",
                    "admitted": len(body["admitted"]),
                    "output": sx.relative(args.output),
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
