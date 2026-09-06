#!/usr/bin/env python3
"""VBC2 parallel acquisition: many read workers, one reducer, one writer.

The scientific contract is untouched. The candidate list, the family quotas and
shares, the ValueFact extractor, the transition predicate, the acquisition
cutoff, the 1,460-day horizon, the twelve-revision bound, the newest-qualifying
rule, one question per lineage and the 190 floor are all the frozen ones. This
module changes only how fast the same answer is computed.

Three roles, and they do not overlap:

* **workers** evaluate one lineage each and can see nothing else — no quota, no
  admitted count, no other result, no coverage or retrieval figure. A worker
  that could see how full the cohort already was would make selection a function
  of arrival rather than of the source.
* **the coordinator** is the only thing that knows the frozen lineage ordering
  and the per-family quotas, and it reduces deterministically.
* **the writer** is the only thing that touches the manifest, the raw tree and
  the receipt.

Completion order is not selection order. Results are collected as they finish
and then re-sorted into frozen lineage order before a single admission pass that
is the serial algorithm, unchanged. `test_part14.py` asserts the two produce the
same admitted ids, the same selected transitions, the same primary properties
and the same manifest digest.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[0] / "acquisition"))
sys.path.insert(0, str(HERE.parents[0] / "canonicalization"))
sys.path.insert(0, str(HERE.parents[0] / "endpoint"))

import fetch_p4c_corpus as p4c  # noqa: E402
import fetch_p4g_corpus as p4g  # noqa: E402
import http_pool as pool_module  # noqa: E402
import run_vbc2_acquire as serial  # noqa: E402
import vbc2_worker  # noqa: E402
from common import NS, canonical_sha, now, rel, sha_bytes, sha_file  # noqa: E402
from evidence import write_immutable  # noqa: E402
from instance_lock import InstanceLock, LockHeld  # noqa: E402
from payload_cache import PayloadCache  # noqa: E402
from sources_vbc2 import (  # noqa: E402
    ADMISSION_FAILURE_CODES,
    CONSUMPTION_ORDER,
    FAMILY_QUOTA,
    FAMILY_SHARE,
    HISTORY,
    PRIMARY_TARGET,
)
from value_fact import observations  # noqa: E402

PROTOCOL = NS / "protocols" / "VALUE_BEARING_COHORT_V2.yaml"
LINEAGES = NS / "artifacts" / "development" / "vbc2_lineages.json"
RAW = NS / "artifacts" / "development" / "raw_vbc2"
CANONICAL = NS / "artifacts" / "development" / "canonical_vbc2"
COHORTS = NS / "artifacts" / "development" / "vbc2_cohorts"
CACHE = NS / "artifacts" / "development" / "vbc2_cache"
LOCK = NS / "artifacts" / "development" / "vbc2_acquire.lock"

DEFAULT_WORKERS = 16


# --- reduction: deterministic, frozen order, quota-bound ------------------------


def reduce_results(
    lineages: list[dict[str, Any]],
    results: dict[str, dict[str, Any]],
    canonicalise: Any,
    materialise: Any,
) -> dict[str, Any]:
    """The serial admission algorithm, applied to results gathered in any order.

    Arrival order is discarded here on purpose. The loop walks the frozen lineage
    list, so a lineage's fate depends on its declared position and its family's
    quota, never on how quickly its worker happened to return.
    """
    admitted: list[dict[str, Any]] = []
    primary: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    per_family: Counter[str] = Counter()
    seen: set[str] = set()

    for lineage in lineages:
        family = lineage["family"]
        lineage_id = lineage["lineage_id"]
        if per_family[family] >= FAMILY_QUOTA[family]:
            rejected.append({"lineage_id": lineage_id, "code": "BEYOND_FAMILY_QUOTA"})
            continue
        if lineage_id in seen:
            rejected.append({"lineage_id": lineage_id, "code": "OTHER"})
            continue
        found = results.get(lineage_id)
        if found is None:
            rejected.append({"lineage_id": lineage_id, "code": "NOT_WALKED"})
            continue
        if found.get("code") is not None:
            row = {"lineage_id": lineage_id, "code": found["code"]}
            if found.get("error"):
                row["error"] = found["error"]
            rejected.append(row)
            continue

        record, failure = materialise(lineage, found, canonicalise)
        if failure is not None:
            rejected.append(failure)
            continue

        transitions = found["transitions"]
        primary.append(
            {**transitions[0], "lineage_id": lineage_id, "slug": record["document_slug"]}
        )
        diagnostics.extend(
            {
                **item,
                "lineage_id": lineage_id,
                "excluded_from": "primary McNemar sample",
            }
            for item in transitions[1:]
        )
        admitted.append(record)
        seen.add(lineage_id)
        per_family[family] += 1

    return {
        "admitted": admitted,
        "primary": primary,
        "diagnostics": diagnostics,
        "rejected": rejected,
        "per_family": dict(per_family),
    }


def semantic_digest(reduced: dict[str, Any]) -> str:
    """What a manifest *means*, independent of when anything arrived.

    Timestamps, worker counts, cache statistics and host tallies are excluded:
    they differ between a serial and a parallel run by construction, and a
    digest that included them could never demonstrate equivalence.
    """
    return canonical_sha(
        {
            "admitted": [
                {
                    "lineage_id": row["lineage_id"],
                    "document_slug": row["document_slug"],
                    "family": row["family"],
                    "before_version": row["before_version"],
                    "after_version": row["after_version"],
                    "adjacency_index": row["adjacency_index"],
                    "before_sha256": row["before"]["raw_sha256"],
                    "after_sha256": row["after"]["raw_sha256"],
                }
                for row in reduced["admitted"]
            ],
            "primary": [
                {
                    "lineage_id": row["lineage_id"],
                    "property_id": row["property_id"],
                    "current_value": row["current_value"],
                    "superseded_value": row["superseded_value"],
                    "value_kind": row["value_kind"],
                }
                for row in reduced["primary"]
            ],
            "rejected": sorted((row["lineage_id"], row["code"]) for row in reduced["rejected"]),
        }
    )


# --- writing: one writer, run-scoped, never the canonical path when partial -----


def build_materialiser(cache: PayloadCache) -> Any:
    """Returns the single function permitted to write into the raw tree."""
    import re  # noqa: PLC0415

    def materialise(
        lineage: dict[str, Any], found: dict[str, Any], canonicalise: Any
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        record = serial._record(lineage, found)
        slug = re.sub(r"[^A-Za-z0-9]+", "-", record["document_id"]).strip("-").lower()[:80]
        record["document_slug"] = slug
        payloads = {}
        for side in ("before", "after"):
            digest = found["payload_digests"][side]
            blob = cache._blob(digest)
            if not blob.exists():
                return None, {
                    "lineage_id": lineage["lineage_id"],
                    "code": serial.PAYLOAD_UNAVAILABLE,
                    "error": "cache miss on reduce",
                }
            payloads[side] = blob.read_bytes()
        try:
            canonical = {
                side: canonicalise(record, side, payloads[side]) for side in ("before", "after")
            }
        except Exception as error:
            return None, {
                "lineage_id": lineage["lineage_id"],
                "code": serial.PARSE_FLOOR,
                "error": type(error).__name__,
            }
        if any(len(value["units"]) < p4g.MIN_UNITS for value in canonical.values()):
            return None, {"lineage_id": lineage["lineage_id"], "code": serial.PARSE_FLOOR}

        for side in ("before", "after"):
            raw_path = RAW / slug / (side + record["suffix"])
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.write_bytes(payloads[side])
            canonical_path = CANONICAL / slug / (side + ".json")
            canonical_path.parent.mkdir(parents=True, exist_ok=True)
            canonical_path.write_text(
                json.dumps(canonical[side], sort_keys=True, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            record[side] = {
                "raw_path": rel(raw_path),
                "raw_sha256": sha_bytes(payloads[side]),
                "canonical_path": rel(canonical_path),
                "unit_count": len(canonical[side]["units"]),
            }
        return record, None

    return materialise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--budget-seconds", type=int, default=0)
    args = parser.parse_args()

    started = now()
    clock = time.monotonic()
    frozen = json.loads(LINEAGES.read_text(encoding="utf-8"))
    lineages = frozen["lineages"][: args.limit] if args.limit else frozen["lineages"]

    run_id = None
    lock = InstanceLock(LOCK, "pending")
    try:
        owner = lock.acquire()
    except LockHeld as held:
        print(json.dumps({"status": held.status, "owner": held.owner}, sort_keys=True))
        return 2

    try:
        pool = pool_module.HttpPool()
        pool_module.install(pool, p4c, p4g, p4g.USER_AGENT)
        cache = PayloadCache(CACHE, sha_file(NS / "endpoint" / "value_fact.py"))

        def payload_for(lineage: dict[str, Any], revision: dict[str, str]) -> tuple[bytes, str]:
            document = {"fetch": {"only": revision["url"]}, "family": lineage["family"]}
            if lineage["family"] == "encyclopedia_wikipedia":
                document["unwrap"] = "parse.text"
            return cache.payload(revision["url"], lambda _url: p4c.payload_for(document, "only"))

        def state_for(lineage: dict[str, Any], body: bytes, digest: str) -> dict[str, Any]:
            return cache.state(
                digest,
                lineage["suffix"],
                lambda: observations(
                    body.decode("utf-8", errors="replace"),
                    lineage["suffix"],
                    lineage["lineage_id"],
                ),
            )

        results: dict[str, dict[str, Any]] = {}
        stopped_on_budget = False
        completed = 0
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {
                executor.submit(
                    vbc2_worker.evaluate,
                    lineage,
                    payload_for=payload_for,
                    state_for=state_for,
                ): lineage["lineage_id"]
                for lineage in lineages
            }
            for future in as_completed(futures):
                lineage_id = futures[future]
                try:
                    results[lineage_id] = future.result()
                except Exception as error:
                    results[lineage_id] = {
                        "lineage_id": lineage_id,
                        "code": "OTHER",
                        "error": type(error).__name__,
                    }
                completed += 1
                if completed % 50 == 0:
                    print(
                        json.dumps(
                            {
                                "stage": "walk",
                                "completed": completed,
                                "of": len(futures),
                                "elapsed_s": round(time.monotonic() - clock, 1),
                            }
                        ),
                        flush=True,
                    )
                if args.budget_seconds and time.monotonic() - clock > args.budget_seconds:
                    stopped_on_budget = True
                    for pending in futures:
                        pending.cancel()
                    break

        walked = len(results)
        complete = (not stopped_on_budget) and walked == len(lineages) and not args.limit
        reduced = reduce_results(lineages, results, p4c.canonicalise, build_materialiser(cache))
        digest = semantic_digest(reduced)
        lineage_ids = [row["lineage_id"] for row in reduced["primary"]]

        run_scope = "complete" if complete else "partial"
        COHORTS.mkdir(parents=True, exist_ok=True)
        body = {
            "schema": "tavonel.v2.vbc2_cohort.v1",
            "protocol": rel(PROTOCOL),
            "protocol_sha256": sha_file(PROTOCOL),
            "status": "COMPLETE" if complete else "PARTIAL",
            "complete": complete,
            "started_at": started,
            "ended_at": now(),
            "executor": {
                "mode": "parallel",
                "workers": args.workers,
                "revision_prefetch": vbc2_worker.REVISION_PREFETCH,
                "roles": "read workers -> one deterministic reducer -> one writer",
                "completion_order_is_not_selection_order": (
                    "results are collected as they finish and then re-sorted into "
                    "frozen lineage order before a single admission pass"
                ),
                "scientific_contract_unchanged": (
                    "candidate list, quotas, extractor, predicate, cutoff, horizon, "
                    "revision bound, newest-qualifying rule, one-per-lineage and the "
                    "190 floor are the frozen ones"
                ),
            },
            "lineage_list": rel(LINEAGES),
            "history_bounds": HISTORY,
            "family_share": FAMILY_SHARE,
            "family_quota": FAMILY_QUOTA,
            "primary_target": PRIMARY_TARGET,
            "consumption_order": CONSUMPTION_ORDER,
            "documents": reduced["admitted"],
            "document_count": len(reduced["admitted"]),
            "documents_sha256": canonical_sha(reduced["admitted"]),
            "semantic_digest": digest,
            "primary_transitions": reduced["primary"],
            "primary_count": len(reduced["primary"]),
            "diagnostic_transitions": reduced["diagnostics"],
            "diagnostic_count": len(reduced["diagnostics"]),
            "by_family": reduced["per_family"],
            "rejected": reduced["rejected"][:6000],
            "rejected_count": len(reduced["rejected"]),
            "rejected_by_code": dict(Counter(row["code"] for row in reduced["rejected"])),
            "admission_failure_codes": list(ADMISSION_FAILURE_CODES),
            "one_question_per_lineage": {
                "primary_questions": len(reduced["primary"]),
                "distinct_lineages": len(set(lineage_ids)),
                "holds": len(reduced["primary"]) == len(set(lineage_ids)),
            },
            "all_pairs_adjacent": all(row["adjacent_pair"] for row in reduced["admitted"]),
            "walk_coverage": {
                "lineages_available": len(frozen["lineages"]),
                "lineages_considered": len(lineages),
                "lineages_walked": walked,
                "stopped_on_wall_clock_budget": stopped_on_budget,
                "budget_seconds": args.budget_seconds or None,
                "limit": args.limit or None,
                "note": (
                    "a partial walk is a coverage limit, not a source property. An "
                    "admitted count from one is a diagnostic figure and is never a "
                    "cohort result."
                ),
            },
            "http": pool.stats(),
            "cache": cache.stats(),
            "gpu_seconds": 0,
            "estimated_cost_usd": 0.0,
        }

        stem = "vbc2-cohort" if complete else "vbc2-cohort-partial"
        run_id = "%s-%s" % (body["ended_at"].replace(":", "").replace("-", ""), digest[7:19])
        name = ("vbc2_cohort.%s.json" if complete else "vbc2_cohort.partial.%s.json") % run_id
        manifest = COHORTS / name
        manifest.write_text(
            json.dumps(body, indent=1, sort_keys=True, ensure_ascii=False), encoding="utf-8"
        )
        written = write_immutable(
            stem,
            {
                **{k: v for k, v in body.items() if k not in ("documents", "rejected")},
                "manifest_path": rel(manifest),
                "manifest_sha256": sha_file(manifest),
            },
            tool=Path(__file__).resolve(),
            protocol=PROTOCOL,
        )
        print(
            json.dumps(
                {
                    **written,
                    "status": body["status"],
                    "manifest": rel(manifest),
                    "manifest_sha256": sha_file(manifest),
                    "admitted": len(reduced["admitted"]),
                    "by_family": reduced["per_family"],
                    "rejected_by_code": body["rejected_by_code"],
                    "semantic_digest": digest,
                    "elapsed_s": round(time.monotonic() - clock, 1),
                },
                sort_keys=True,
            )
        )
        # a partial run must not exit 0: a caller reading only the exit code has
        # to be able to tell a truncated walk from a completed one.
        return 0 if complete else 3
    finally:
        lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
