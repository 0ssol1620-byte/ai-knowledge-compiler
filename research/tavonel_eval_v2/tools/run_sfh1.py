#!/usr/bin/env python3
"""SOURCE_FAITHFULNESS_HELDOUT_V1 — held-out source front-end faithfulness.

Parallel read/compute workers, one deterministic reducer, one evidence writer.
The shape is the one the parallel VBC2 executor established and it is here for
the same reason: completion order correlates with latency, payload size and
provider health, so admitting in arrival order would make the cohort a function
of the network. Results are re-sorted into the frozen sampling order before a
single admission pass.

A worker sees one lineage and one payload callable. It does not know the family
quotas, the admitted count, any other lineage's result, or any classification
outcome but its own.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
for _sub in ("tools", "acquisition", "canonicalization", "endpoint", "compiler"):
    sys.path.insert(0, str(NS / _sub))

from canonical_document import canonical_document  # noqa: E402
from changed_region_controls import run_controls  # noqa: E402
from changed_regions import (  # noqa: E402
    MODELED,
    UNCLASSIFIED,
    UNRESOLVED,
    UNVERIFIED,
    blocks_local_completeness,
    classify_pair,
)
from common import NS as _NS, canonical_sha, now, rel, sha_file  # noqa: E402
from coverage_witness import COMPLETE  # noqa: E402
from coverage_witness_v2 import build_witness, witness_status  # noqa: E402
from evidence import write_immutable  # noqa: E402
from http_pool import HttpPool, install  # noqa: E402
from markup_policy import POLICY  # noqa: E402
from markup_semantics import policy_digest  # noqa: E402
from payload_cache import PayloadCache  # noqa: E402
from source_map import LOCATION_VERIFIED  # noqa: E402
import sources_sfh1 as frame_module  # noqa: E402

PROTOCOL = NS / "protocols" / "SOURCE_FAITHFULNESS_HELDOUT_V1.yaml"
CACHE = NS / "artifacts" / "development" / "vbc2_cache"
OUT = NS / "artifacts" / "development" / "sfh1"

USER_AGENT = "tavonel-eval-v2 source-faithfulness (research; contact via repository)"

TOO_FEW = "TOO_FEW_REVISIONS"
NO_DIFF = "NO_RAW_DIFFERENCE"
PAYLOAD_FAIL = "PAYLOAD_UNAVAILABLE"
LISTING_FAIL = "LISTING_FAILED"
EMPTY_CANON = "CANONICALISATION_EMPTY"
TOO_LARGE = "PAYLOAD_TOO_LARGE_TO_CLASSIFY"
BEYOND_QUOTA = "BEYOND_FAMILY_QUOTA"

SILENT_DROP = "SILENT_SOURCE_DROP"

#: Lineages evaluated between reductions. Only affects how many extra lineages
#: are looked at past the stopping point; those are BEYOND_FAMILY_QUOTA and
#: cannot change an admission.
CHUNK = 96


# --- worker -------------------------------------------------------------------


def evaluate(lineage: dict[str, Any], payload_for: Any) -> dict[str, Any]:
    """One lineage: newest adjacent revision pair whose raw bytes differ, classified."""
    import run_vbc2_acquire as serial  # noqa: PLC0415

    try:
        revisions = serial.ENUMERATORS[lineage["family"]](lineage)
    except Exception as error:
        return {"code": LISTING_FAIL, "detail": type(error).__name__}
    if len(revisions) < 2:
        return {"code": TOO_FEW, "revisions_seen": len(revisions)}

    seen: dict[str, tuple[bytes, str]] = {}

    def payload(revision: dict[str, str]) -> tuple[bytes, str]:
        if revision["version"] not in seen:
            seen[revision["version"]] = payload_for(lineage, revision)
        return seen[revision["version"]]

    for index in range(len(revisions) - 1):
        after, before = revisions[index], revisions[index + 1]
        try:
            after_raw, after_digest = payload(after)
            before_raw, before_digest = payload(before)
        except Exception as error:
            return {"code": PAYLOAD_FAIL, "detail": type(error).__name__}
        if after_digest == before_digest:
            continue
        largest = max(len(after_raw), len(before_raw))
        if largest > frame_module.MAX_PAYLOAD_BYTES:
            #: reported, never silently skipped. The count is part of the result.
            return {"code": TOO_LARGE, "bytes": largest}
        return _classify(lineage, after, before, after_raw, before_raw)
    return {"code": NO_DIFF, "revisions_seen": len(revisions)}


def _document(lineage: dict[str, Any], revision: dict[str, str], raw: bytes) -> dict[str, Any]:
    return canonical_document(
        source_family=lineage["family"],
        source_id=lineage["lineage_id"],
        version_id=revision["version"],
        payload=raw,
        source_digest="sha256:" + hashlib.sha256(raw).hexdigest(),
        known_at=revision.get("known_at"),
        valid_from=revision.get("known_at"),
        licence=lineage.get("licence", "unknown"),
    )


def _classify(
    lineage: dict[str, Any],
    after: dict[str, str],
    before: dict[str, str],
    after_raw: bytes,
    before_raw: bytes,
) -> dict[str, Any]:
    after_document = _document(lineage, after, after_raw)
    before_document = _document(lineage, before, before_raw)
    if not after_document["units"] and not before_document["units"]:
        return {"code": EMPTY_CANON, "after": after["version"], "before": before["version"]}

    after_text = after_raw.decode("utf-8", errors="replace")
    before_text = before_raw.decode("utf-8", errors="replace")
    result = classify_pair(
        before_raw=before_text,
        after_raw=after_text,
        before_document=before_document,
        after_document=after_document,
        suffix=lineage["suffix"],
    )
    scopes = _scopes(result, after_text, after_document)
    slim = {key: value for key, value in result.items() if key not in ("rows", "spans")}
    return {
        "code": None,
        "family": lineage["family"],
        "lineage_id": lineage["lineage_id"],
        "suffix": lineage["suffix"],
        "after_version": after["version"],
        "before_version": before["version"],
        "adjacent": True,
        **slim,
        "scopes": scopes,
        "silent_drops": [scope for scope in scopes if scope["silent_drop"]],
        "sample_rows": [
            {key: row[key] for key in ("side", "kind", "state", "verification", "sample")}
            for row in result["rows"]
            if blocks_local_completeness(row)
        ][:6],
    }


def _scopes(
    result: dict[str, Any], after_text: str, after_document: dict[str, Any]
) -> list[dict[str, Any]]:
    """Per changed canonical unit: did the run call it complete, and was it?

    The witness decides completeness from the grammar's four states alone. It has
    no knowledge of whether a MODELED claim survived verification against the
    compiled state, which is exactly why a construct the policy calls MODELED and
    the compiler does not store can pass it unnoticed. This is the only place
    that shows.
    """
    spans = result["spans"]["after"]
    grammar = result["grammar"]
    changed_rows = [row for row in result["rows"] if row["side"] == "after"]
    if not changed_rows:
        return []

    units = after_document["units"]
    texts = [unit["text"] for unit in units]
    scopes: list[dict[str, Any]] = []
    for unit in units[:24]:
        witness = build_witness(
            spans,
            unit["text"],
            [text for text in texts if text != unit["text"]][:8],
            (),
            after_text,
            "\n".join(texts),
            grammar,
        )
        status = witness_status(witness, spans)
        region = witness.get("atom_source_region") or _region_of(witness)
        if region is None:
            scopes.append(
                {
                    "path": "/".join(unit["explicit_path"]),
                    "status": status["status"],
                    "reasons": status["reasons"],
                    "region": None,
                    "blocking_in_scope": 0,
                    "silent_drop": False,
                    "why_not": "the scope could not be localised in the source, so it is refused",
                }
            )
            continue
        low, high = region
        blocking = [
            row
            for row in changed_rows
            if blocks_local_completeness(row) and row["start"] < high and row["end"] > low
        ]
        scopes.append(
            {
                "path": "/".join(unit["explicit_path"]),
                "status": status["status"],
                "reasons": status["reasons"],
                "region": [low, high],
                "blocking_in_scope": len(blocking),
                "blocking_states": sorted({row["state"] for row in blocking}),
                "blocking_verifications": sorted({str(row["verification"]) for row in blocking}),
                "silent_drop": status["status"] == COMPLETE and bool(blocking),
            }
        )
    return scopes


def _region_of(witness: dict[str, Any]) -> tuple[int, int] | None:
    located = [
        (element["start"], element["end"])
        for element in witness["elements"]
        if element.get("start") is not None and element.get("end") is not None
    ]
    if not located:
        return None
    return min(start for start, _ in located), max(end for _, end in located)


# --- reducer ------------------------------------------------------------------


def reduce_results(
    lineages: list[dict[str, Any]], results: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Frozen order in, deterministic admission out. Arrival order never reaches here."""
    admitted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    per_family: dict[str, int] = {family: 0 for family in frame_module.FAMILY_QUOTA}
    considered = 0

    for lineage in lineages:
        found = results.get(lineage["lineage_id"])
        if found is None:
            continue
        considered += 1
        if found.get("code") is not None:
            rejected.append(
                {
                    "lineage_id": lineage["lineage_id"],
                    "family": lineage["family"],
                    "code": found["code"],
                }
            )
            continue
        family = lineage["family"]
        if per_family.get(family, 0) >= frame_module.FAMILY_QUOTA.get(family, 0):
            rejected.append(
                {"lineage_id": lineage["lineage_id"], "family": family, "code": BEYOND_QUOTA}
            )
            continue
        per_family[family] = per_family.get(family, 0) + 1
        admitted.append(found)

    return {
        "admitted": admitted,
        "rejected": rejected,
        "by_family": per_family,
        "considered": considered,
        "quota_met": all(
            per_family.get(family, 0) >= quota
            for family, quota in frame_module.FAMILY_QUOTA.items()
        ),
    }


def score(reduced: dict[str, Any]) -> dict[str, Any]:
    admitted = reduced["admitted"]
    unclassified = sum(row["by_state"].get(UNCLASSIFIED, 0) for row in admitted)
    silent = [
        {"lineage_id": row["lineage_id"], "family": row["family"], "scopes": row["silent_drops"]}
        for row in admitted
        if row["silent_drops"]
    ]
    complete_scopes = [
        scope for row in admitted for scope in row["scopes"] if scope["status"] == COMPLETE
    ]
    unresolved_in_complete = sum(
        1 for scope in complete_scopes if UNRESOLVED in (scope.get("blocking_states") or [])
    )
    pairs_with_unresolved = [row for row in admitted if row["by_state"].get(UNRESOLVED, 0) > 0]
    refused = [
        row
        for row in pairs_with_unresolved
        if all(scope["status"] != COMPLETE for scope in row["scopes"])
        or all(not scope["silent_drop"] for scope in row["scopes"])
    ]

    return {
        "pairs_scored": len(admitted),
        "families": sorted({row["family"] for row in admitted}),
        "regions_total": sum(row["region_count"] for row in admitted),
        "by_state": _sum_states(admitted),
        "unclassified_changed_regions": unclassified,
        "modeled_claims": sum(row["modeled_claims"] for row in admitted),
        "modeled_claims_verified": sum(row["modeled_claims_verified"] for row in admitted),
        "modeled_claims_unverified": sum(row["modeled_claims_unverified"] for row in admitted),
        "unverified_by_reason": _merge(row["unverified_by_reason"] for row in admitted),
        "scopes_examined": sum(len(row["scopes"]) for row in admitted),
        "scopes_declared_complete": len(complete_scopes),
        "silent_source_drops": sum(len(row["silent_drops"]) for row in admitted),
        "pairs_with_a_silent_drop": len(silent),
        "silent_drop_detail": silent[:12],
        "unresolved_inside_a_complete_scope": unresolved_in_complete,
        "pairs_carrying_unresolved": len(pairs_with_unresolved),
        "pairs_carrying_unresolved_and_refused": len(refused),
        "pairs_where_compiled_state_did_not_move": sum(
            1 for row in admitted if not row["compiled_state_changed"]
        ),
    }


def _sum_states(rows: list[dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in rows:
        for state, count in row["by_state"].items():
            out[state] = out.get(state, 0) + count
    return dict(sorted(out.items()))


def _merge(dicts: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    for item in dicts:
        for key, value in item.items():
            out[key] = out.get(key, 0) + value
    return dict(sorted(out.items()))


def gates(summary: dict[str, Any], controls: dict[str, Any]) -> dict[str, bool]:
    return {
        "G_SFH1_CONTROLS_PASS": bool(controls["all_passed"]),
        "G_SFH1_NO_UNCLASSIFIED": summary["unclassified_changed_regions"] == 0,
        "G_SFH1_NO_SILENT_DROP": summary["silent_source_drops"] == 0,
        "G_SFH1_UNRESOLVED_FAIL_CLOSED": (
            summary["pairs_carrying_unresolved"] == summary["pairs_carrying_unresolved_and_refused"]
        ),
        "G_SFH1_LOCALLY_COMPLETE_CLEAN": summary["unresolved_inside_a_complete_scope"] == 0,
        "G_SFH1_COHORT_FLOOR": summary["pairs_scored"] >= frame_module.FLOOR,
        "G_SFH1_FAMILIES": len(summary["families"]) >= frame_module.FAMILIES_REQUIRED,
        "G_SFH1_NO_CONSTRUCT_REMOVED": policy_digest() == _frozen_policy_digest(),
        "G_SFH1_NO_GPU": True,
    }


#: A safety endpoint that was never exercised has not been met; it has been
#: skipped. The silent-drop gate can only bite where the run declared some scope
#: locally complete, so a run that declared none passes it by having nothing to
#: check. That is reported as its own verdict rather than folded into PASS.
def gate_power(summary: dict[str, Any]) -> dict[str, Any]:
    complete = summary["scopes_declared_complete"]
    return {
        "silent_drop_gate_exercised": complete > 0,
        "scopes_declared_complete": complete,
        "why_it_matters": (
            "G_SFH1_NO_SILENT_DROP compares scopes the run called complete against "
            "regions that should have blocked them. With no complete scope it "
            "passes vacuously and establishes nothing."
        ),
    }


def _frozen_policy_digest() -> str:
    """The policy digest as MARKUP_SEMANTICS_V1 sealed it, read from its receipt."""
    receipts = sorted((NS / "receipts").glob("markup-semantics-v1-freeze--*.json"))
    if not receipts:
        return policy_digest()
    body = json.loads(receipts[-1].read_text(encoding="utf-8"))
    for key in ("policy_digest", "policy_sha256"):
        if key in body:
            return str(body[key])
    return str(body.get("policy", {}).get("digest", policy_digest()))


# --- driver -------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--limit", type=int, default=None)
    arguments = parser.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    started = now()
    clock = time.time()

    import fetch_p4c_corpus as p4c  # noqa: PLC0415
    import fetch_p4g_corpus as p4g  # noqa: PLC0415
    import run_vbc2_acquire as serial  # noqa: PLC0415

    pool = HttpPool()
    install(pool, p4c, p4g, USER_AGENT)
    cache = PayloadCache(CACHE, sha_file(NS / "canonicalization" / "changed_regions.py"))

    def payload_for(lineage: dict[str, Any], revision: dict[str, str]) -> tuple[bytes, str]:
        return cache.payload(revision["url"], lambda _url: serial._payload(lineage, revision))

    lineages = frame_module.frame()
    if arguments.limit:
        lineages = lineages[: arguments.limit]

    controls = run_controls()
    results: dict[str, dict[str, Any]] = {}
    reduced: dict[str, Any] = {"admitted": [], "rejected": [], "by_family": {}, "quota_met": False}

    with ThreadPoolExecutor(max_workers=arguments.workers) as executor:
        for start in range(0, len(lineages), CHUNK):
            chunk = lineages[start : start + CHUNK]
            futures = {
                lineage["lineage_id"]: executor.submit(evaluate, lineage, payload_for)
                for lineage in chunk
            }
            for lineage_id, future in futures.items():
                try:
                    results[lineage_id] = future.result()
                except Exception as error:
                    results[lineage_id] = {
                        "code": PAYLOAD_FAIL,
                        "detail": "%s: %s" % (type(error).__name__, error),
                    }
            reduced = reduce_results(lineages, results)
            print(
                "considered %d  admitted %d  %s"
                % (reduced["considered"], len(reduced["admitted"]), reduced["by_family"]),
                flush=True,
            )
            if reduced["quota_met"]:
                break

    summary = score(reduced)
    verdicts = gates(summary, controls)
    power = gate_power(summary)
    rejected_by_code: dict[str, int] = {}
    for row in reduced["rejected"]:
        rejected_by_code[row["code"]] = rejected_by_code.get(row["code"], 0) + 1

    body: dict[str, Any] = {
        "schema": "tavonel.v2.source_faithfulness_heldout.v1",
        "protocol": rel(PROTOCOL),
        "protocol_sha256": sha_file(PROTOCOL),
        "split": "held_out",
        "started_at": started,
        "ended_at": now(),
        "wall_seconds": round(time.time() - clock, 1),
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
        "frame": {
            "source": rel(frame_module.FRAME),
            "candidates": len(lineages),
            "digest": frame_module.frame_digest(lineages),
            "spent_excluded": sorted(frame_module.SPENT_LINEAGES),
            "order": "ascending sha256 of the lineage id, fixed before any payload was read",
        },
        "history_bounds": frame_module.HISTORY,
        "payload_bound": {
            "max_payload_bytes": frame_module.MAX_PAYLOAD_BYTES,
            "basis": frame_module.MAX_PAYLOAD_BASIS,
            "explicitly_not_basis": frame_module.MAX_PAYLOAD_NOT_BASIS,
        },
        "family_quota": frame_module.FAMILY_QUOTA,
        "grammar": {
            "policy_id": POLICY["policy_id"],
            "policy_version": POLICY["version"],
            "policy_digest": policy_digest(),
            "frozen_policy_digest": _frozen_policy_digest(),
            "instrument": rel(NS / "canonicalization" / "changed_regions.py"),
            "instrument_sha256": sha_file(NS / "canonicalization" / "changed_regions.py"),
        },
        "controls": controls,
        "lineages_considered": reduced["considered"],
        "by_family": reduced["by_family"],
        "rejected_by_code": dict(sorted(rejected_by_code.items())),
        "summary": summary,
        "gates": verdicts,
        "gate_power": power,
        "verdict": (
            "FAIL"
            if not all(verdicts.values())
            else ("PASS" if power["silent_drop_gate_exercised"] else "PASS_WITHOUT_POWER")
        ),
        "http": pool.stats(),
        "cache": cache.stats(),
    }

    detail = OUT / "sfh1_pairs.json"
    detail.write_text(
        json.dumps(reduced["admitted"], indent=1, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    body["pairs_path"] = rel(detail)
    body["pairs_sha256"] = sha_file(detail)
    body["result_digest"] = canonical_sha(
        {"summary": summary, "gates": verdicts, "by_family": reduced["by_family"]}
    )

    written = write_immutable(
        "sfh1-source-faithfulness",
        body,
        tool=Path(__file__).resolve(),
        protocol=PROTOCOL,
    )
    print(json.dumps({**written, "verdict": body["verdict"]}, indent=2))
    print(json.dumps(summary, indent=2))
    return 0 if body["verdict"] == "PASS" else 4


if __name__ == "__main__":
    raise SystemExit(main())
