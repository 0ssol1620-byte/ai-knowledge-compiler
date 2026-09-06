#!/usr/bin/env python3
"""ORACLE_INDEPENDENCE_V2 driver: engine here, oracle over there, judge in between.

Three processes per pair and none of them is allowed to be two of the roles:

* the engine runs in this process, because it is the thing under test and it may
  read whatever it likes about the source it compiles;
* the oracle runs as ``python -I -S`` with only raw payload bytes, an import
  guard armed inside it, and no path to any project module;
* the comparator runs as its own process, imports neither, and is the only one
  that hashes the comparison.

This driver translates the engine's opaque artifact ids into the portable
identities of protocol section 2. That translation is mechanical — an id map
built from the canonical document — and it is done here rather than in the
comparator so the comparator can stay ignorant of both sides' internals.
"""

from __future__ import annotations

import argparse
import ast
import base64
import hashlib
import json
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
for _sub in ("tools", "acquisition", "canonicalization", "compiler", "endpoint"):
    sys.path.insert(0, str(NS / _sub))

from canonical_document import canonical_document  # noqa: E402
from common import canonical_sha, now, rel, sha_file  # noqa: E402
from evidence import write_immutable  # noqa: E402
from http_pool import HttpPool, install  # noqa: E402
from payload_cache import PayloadCache  # noqa: E402
import selective_build as engine  # noqa: E402
import sources_sfh1 as frame_module  # noqa: E402

PROTOCOL = NS / "protocols" / "ORACLE_INDEPENDENCE_V2.yaml"
ORACLE = NS / "oracle" / "source_derived_expected.py"
COMPARATOR = NS / "comparator" / "compare_recompilation.py"
CACHE = NS / "artifacts" / "development" / "vbc2_cache"
OUT = NS / "artifacts" / "development" / "oracle_v2"
SFH1_PAIRS = NS / "artifacts" / "development" / "sfh1" / "sfh1_pairs.json"

USER_AGENT = "tavonel-eval-v2 oracle-independence (research; contact via repository)"

SALT = ":oracle-v2"
PRIMARY_TARGET = 200
FLOOR = 120
FAMILIES_REQUIRED = 2
FAMILY_QUOTA = {
    "git_docs": 80,
    "regulation_ecfr": 60,
    "encyclopedia_wikipedia": 40,
    "sec_edgar": 20,
}
CHUNK = 64

TOO_FEW = "TOO_FEW_REVISIONS"
NO_DIFF = "NO_RAW_DIFFERENCE"
PAYLOAD_FAIL = "PAYLOAD_UNAVAILABLE"
LISTING_FAIL = "LISTING_FAILED"
BEYOND_QUOTA = "BEYOND_FAMILY_QUOTA"
TOO_LARGE = "PAYLOAD_TOO_LARGE_TO_CLASSIFY"
MISSING = "MISSING"

#: Modules neither the oracle file nor the comparator file may name in an
#: import statement. Checked by reading their syntax trees, not by trusting the
#: guard they install at runtime: a guard proves what happened in one run, the
#: import graph proves what the file can ever do.
FORBIDDEN_IMPORTS = frozenset(
    {
        "akc_cir",
        "selective_build",
        "canonical_document",
        "changed_regions",
        "source_map",
        "source_map_v2",
        "markup_policy",
        "markup_semantics",
        "common",
        "evidence",
        "coverage_witness",
        "coverage_witness_v2",
    }
)


# --- cohort -------------------------------------------------------------------


def order_key(lineage_id: str) -> str:
    return hashlib.sha256((lineage_id + SALT).encode("utf-8")).hexdigest()


def spent_from_sfh1() -> frozenset[str]:
    if not SFH1_PAIRS.exists():
        return frozenset()
    rows = json.loads(SFH1_PAIRS.read_text(encoding="utf-8"))
    return frozenset(row["lineage_id"] for row in rows)


def cohort_frame() -> tuple[list[dict[str, Any]], frozenset[str]]:
    spent = spent_from_sfh1() | frame_module.SPENT_LINEAGES
    rows = [
        lineage
        for lineage in json.loads(frame_module.FRAME.read_text(encoding="utf-8"))["lineages"]
        if lineage["lineage_id"] not in spent
    ]
    return sorted(rows, key=lambda lineage: order_key(lineage["lineage_id"])), spent


# --- engine side --------------------------------------------------------------


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


def _id_map(document: dict[str, Any]) -> dict[str, str]:
    """Engine artifact id -> portable identity, from the canonical document alone."""
    source_id = document["source_id"]
    key = engine.doc_key(source_id)
    mapping: dict[str, str] = {
        "document-index:" + key: "document-index",
        "structure-map:" + key: "structure-map",
    }
    for bucket in range(4):
        mapping["topic-bucket:%s:%d" % (key, bucket)] = "topic-bucket:%d" % bucket
    for unit in document["units"]:
        path = "/".join(unit["explicit_path"])
        mapping["section:" + engine.logical_id(source_id, unit["explicit_path"])] = (
            "section:" + path
        )
    return mapping


def _portable_content(document: dict[str, Any]) -> dict[str, Any]:
    """The same artifact CONTENT the oracle emits, derived from the engine's document."""
    source_id = document["source_id"]
    paths = ["/".join(unit["explicit_path"]) for unit in document["units"]]
    logicals = [engine.logical_id(source_id, unit["explicit_path"]) for unit in document["units"]]
    content: dict[str, Any] = {}
    for unit, path in zip(document["units"], paths):
        content["section:" + path] = {"path": path, "text": unit["text"]}
    content["document-index"] = {"members": paths}
    content["structure-map"] = {"paths": paths}
    ordered = sorted(set(zip(logicals, paths)))
    for bucket in range(4):
        members = [path for logical, path in ordered if engine.bucket_of(logical) == bucket]
        if members:
            content["topic-bucket:" + str(bucket)] = {"bucket": bucket, "members": members}
    return content


def engine_side(before_document: dict[str, Any], after_document: dict[str, Any]) -> dict[str, Any]:
    """Run the engine, then express its post-recompilation state portably."""
    result = engine.run_pair(before_document, after_document)
    after_map = _id_map(after_document)
    before_map = _id_map(before_document)
    after_content = _portable_content(after_document)
    before_content = _portable_content(before_document)

    rebuilt = set(result["selective_rebuild_set"])
    carried = set(result["carried_forward_set"])

    portable_state: dict[str, Any] = {}
    portable_carried: list[str] = []
    for artifact in result["artifact_inventory"]:
        key = after_map.get(artifact) or before_map.get(artifact)
        if key is None:
            continue
        if artifact in rebuilt:
            portable_state[key] = after_content.get(key, MISSING)
        elif artifact in carried:
            portable_state[key] = before_content.get(key, MISSING)
            portable_carried.append(key)
        else:
            portable_state[key] = MISSING
    return {
        "source_id": result["source_id"],
        "engine": "selective",
        "state_hash": result["state_hash"],
        "structural_change_present": result["structural_change_present"],
        "detected_change_kinds": result["detected_change_kinds"],
        "unresolved_present": result["unresolved_present"],
        "identity_outcomes": result["identity_outcomes"],
        "rebuilt_fraction": result["rebuilt_fraction"],
        "work_avoided_fraction": result["work_avoided_fraction"],
        "unplanned_missing": result["unplanned_missing"],
        "portable_state": portable_state,
        "portable_carried_forward": sorted(portable_carried),
    }


# --- one pair, three processes ------------------------------------------------


def judge(lineage: dict[str, Any], payload_for: Any, workdir: Path) -> dict[str, Any]:
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

    pair = None
    for index in range(len(revisions) - 1):
        after, before = revisions[index], revisions[index + 1]
        try:
            after_raw, after_digest = payload(after)
            before_raw, before_digest = payload(before)
        except Exception as error:
            return {"code": PAYLOAD_FAIL, "detail": type(error).__name__}
        if after_digest != before_digest:
            if max(len(after_raw), len(before_raw)) > frame_module.MAX_PAYLOAD_BYTES:
                return {"code": TOO_LARGE, "bytes": max(len(after_raw), len(before_raw))}
            pair = (after, before, after_raw, before_raw)
            break
    if pair is None:
        return {"code": NO_DIFF, "revisions_seen": len(revisions)}

    after, before, after_raw, before_raw = pair
    after_document = _document(lineage, after, after_raw)
    before_document = _document(lineage, before, before_raw)
    side = engine_side(before_document, after_document)

    stem = hashlib.sha256(lineage["lineage_id"].encode("utf-8")).hexdigest()[:16]
    job_path = workdir / (stem + ".job.json")
    oracle_path = workdir / (stem + ".oracle.json")
    engine_path = workdir / (stem + ".engine.json")
    verdict_path = workdir / (stem + ".verdict.json")

    job_path.write_text(
        json.dumps(
            {
                "source_id": lineage["lineage_id"],
                "family": lineage["family"],
                "suffix": lineage["suffix"],
                "after_payload_b64": base64.b64encode(after_raw).decode("ascii"),
                "before_payload_b64": base64.b64encode(before_raw).decode("ascii"),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    engine_path.write_text(json.dumps(side, ensure_ascii=False), encoding="utf-8")

    oracle_run = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            str(ORACLE),
            "--job",
            str(job_path),
            "--output",
            str(oracle_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if oracle_run.returncode != 0 or not oracle_path.exists():
        return {
            "code": "ORACLE_PROCESS_FAILED",
            "detail": (oracle_run.stderr or "")[-400:],
        }

    comparator_run = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            str(COMPARATOR),
            "--engine",
            str(engine_path),
            "--oracle",
            str(oracle_path),
            "--output",
            str(verdict_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if comparator_run.returncode != 0 or not verdict_path.exists():
        return {
            "code": "COMPARATOR_PROCESS_FAILED",
            "detail": (comparator_run.stderr or "")[-400:],
        }

    oracle = json.loads(oracle_path.read_text(encoding="utf-8"))
    verdict = json.loads(verdict_path.read_text(encoding="utf-8"))
    for path in (job_path, oracle_path, engine_path, verdict_path):
        path.unlink(missing_ok=True)

    return {
        "code": None,
        "lineage_id": lineage["lineage_id"],
        "family": lineage["family"],
        "suffix": lineage["suffix"],
        "after_version": after["version"],
        "before_version": before["version"],
        "engine": {
            key: side[key]
            for key in (
                "state_hash",
                "structural_change_present",
                "detected_change_kinds",
                "unresolved_present",
                "identity_outcomes",
                "rebuilt_fraction",
                "work_avoided_fraction",
                "unplanned_missing",
            )
        },
        "engine_artifact_count": len(side["portable_state"]),
        "engine_carried_count": len(side["portable_carried_forward"]),
        "oracle": {
            "judgeable": oracle["judgeable"],
            "unresolved": oracle["unresolved"],
            "pid": oracle.get("pid"),
            "flags": oracle.get("flags"),
            "import_guard": oracle.get("import_guard"),
            "after_unit_count": oracle.get("after_unit_count"),
            "before_unit_count": oracle.get("before_unit_count"),
            "must_change_count": len(oracle.get("must_change", [])),
            "change_type": oracle.get("change_type"),
        },
        "verdict": verdict,
    }


# --- import graph gate --------------------------------------------------------


def import_graph(path: Path) -> dict[str, Any]:
    """What the file can ever import, from its syntax tree.

    The runtime guard proves what one run did. This proves what the file is
    capable of, which is the stronger of the two statements and the one that
    survives someone deleting the guard.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    named: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            named.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            named.add(node.module.split(".")[0])
    offending = sorted(named & FORBIDDEN_IMPORTS)
    return {
        "file": rel(path),
        "sha256": sha_file(path),
        "imports": sorted(named),
        "forbidden_imports_present": offending,
        "clean": not offending,
    }


# --- reduce -------------------------------------------------------------------


def reduce_results(
    lineages: list[dict[str, Any]], results: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    admitted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    per_family = {family: 0 for family in FAMILY_QUOTA}
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
        if per_family.get(family, 0) >= FAMILY_QUOTA.get(family, 0):
            rejected.append(
                {"lineage_id": lineage["lineage_id"], "family": family, "code": BEYOND_QUOTA}
            )
            continue
        per_family[family] += 1
        admitted.append(found)
    return {
        "admitted": admitted,
        "rejected": rejected,
        "by_family": per_family,
        "considered": considered,
        "quota_met": all(per_family[family] >= quota for family, quota in FAMILY_QUOTA.items()),
    }


def score(reduced: dict[str, Any]) -> dict[str, Any]:
    rows = reduced["admitted"]
    judged = [row for row in rows if row["verdict"]["verdict"] != "UNJUDGED"]
    unjudged = [row for row in rows if row["verdict"]["verdict"] == "UNJUDGED"]
    equivalent = [row for row in judged if row["verdict"]["equivalent"]]
    divergent = [row for row in judged if not row["verdict"]["equivalent"]]
    stale = [row for row in judged if row["verdict"]["stale_escape_count"] > 0]

    typed = [
        row for row in judged if row["verdict"]["typed_invalidation_consistent"] != "NOT_TESTED"
    ]
    typed_ok = [row for row in typed if row["verdict"]["typed_invalidation_consistent"]]

    by_type: dict[str, int] = {}
    for row in judged:
        label = row["verdict"]["oracle_change_type"]
        by_type[label] = by_type.get(label, 0) + 1

    reference_only = [
        row for row in judged if row["verdict"]["oracle_change_type"] == "reference_locator_only"
    ]
    reference_reported_clean = [
        row
        for row in reference_only
        if not row["engine"]["structural_change_present"]
        and not row["engine"]["detected_change_kinds"]
    ]

    return {
        "pairs_attempted": len(rows),
        "pairs_judged": len(judged),
        "pairs_unjudged": len(unjudged),
        "unjudged_reasons": sorted(
            {reason for row in unjudged for reason in row["verdict"]["why"]}
        ),
        "families": sorted({row["family"] for row in rows}),
        "exact_state_equivalent": len(equivalent),
        "divergent": len(divergent),
        "divergence_rate": round(len(divergent) / len(judged), 4) if judged else None,
        "stale_escapes": sum(row["verdict"]["stale_escape_count"] for row in judged),
        "pairs_with_a_stale_escape": len(stale),
        "typed_invalidation_tested": len(typed),
        "typed_invalidation_consistent": len(typed_ok),
        "change_types": dict(sorted(by_type.items())),
        "reference_locator_only_pairs": len(reference_only),
        "reference_locator_only_reported_clean": len(reference_reported_clean),
        "divergence_samples": [
            {
                "lineage_id": row["lineage_id"],
                "family": row["family"],
                "only_engine": row["verdict"]["only_engine"],
                "only_oracle": row["verdict"]["only_oracle"],
                "diverged": row["verdict"]["diverged"],
                "engine_units": row["engine_artifact_count"],
                "oracle_units": row["oracle"]["after_unit_count"],
            }
            for row in divergent[:10]
        ],
    }


def gates(summary: dict[str, Any], isolation: dict[str, Any]) -> dict[str, bool]:
    return {
        "G_OI2_ORACLE_ISOLATED": bool(
            isolation["oracle_graph"]["clean"] and isolation["oracle_runtime_clean"]
        ),
        "G_OI2_COMPARATOR_ISOLATED": bool(
            isolation["comparator_graph"]["clean"] and isolation["comparator_runtime_clean"]
        ),
        "G_OI2_NO_STALE_ESCAPE": summary["stale_escapes"] == 0,
        "G_OI2_NO_FALSE_PASS_ON_UNRESOLVED": (
            summary["pairs_judged"] + summary["pairs_unjudged"] == summary["pairs_attempted"]
        ),
        "G_OI2_TYPED_INVALIDATION": (
            summary["typed_invalidation_tested"] == summary["typed_invalidation_consistent"]
        ),
        "G_OI2_COHORT_FLOOR": summary["pairs_judged"] >= FLOOR,
        "G_OI2_FAMILIES": len(summary["families"]) >= FAMILIES_REQUIRED,
        "G_OI2_NO_GPU": True,
    }


# --- driver -------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=8)
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
    cache = PayloadCache(CACHE, sha_file(ORACLE))

    def payload_for(lineage: dict[str, Any], revision: dict[str, str]) -> tuple[bytes, str]:
        return cache.payload(revision["url"], lambda _url: serial._payload(lineage, revision))

    lineages, spent = cohort_frame()
    if arguments.limit:
        lineages = lineages[: arguments.limit]

    results: dict[str, dict[str, Any]] = {}
    reduced: dict[str, Any] = {"admitted": [], "rejected": [], "by_family": {}, "quota_met": False}

    with tempfile.TemporaryDirectory(prefix="oi2-") as scratch:
        workdir = Path(scratch)
        with ThreadPoolExecutor(max_workers=arguments.workers) as executor:
            for start in range(0, len(lineages), CHUNK):
                chunk = lineages[start : start + CHUNK]
                futures = {
                    lineage["lineage_id"]: executor.submit(judge, lineage, payload_for, workdir)
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
                    "considered %d  judged %d  %s"
                    % (reduced["considered"], len(reduced["admitted"]), reduced["by_family"]),
                    flush=True,
                )
                if reduced["quota_met"]:
                    break

    summary = score(reduced)
    runtime_oracle = [
        row["oracle"]["import_guard"]
        for row in reduced["admitted"]
        if row["oracle"].get("import_guard")
    ]
    runtime_comparator = [
        row["verdict"].get("comparator_isolation")
        for row in reduced["admitted"]
        if row["verdict"].get("comparator_isolation")
    ]
    isolation = {
        "oracle_graph": import_graph(ORACLE),
        "comparator_graph": import_graph(COMPARATOR),
        "oracle_runtime_clean": all(
            not entry["project_modules_imported"] and entry["armed"] for entry in runtime_oracle
        )
        and bool(runtime_oracle),
        "comparator_runtime_clean": all(
            not entry["project_modules_imported"] and entry["armed"] for entry in runtime_comparator
        )
        and bool(runtime_comparator),
        "oracle_runs_isolated": all(
            entry.get("isolated")
            for entry in [
                row["oracle"]["flags"] for row in reduced["admitted"] if row["oracle"].get("flags")
            ]
        ),
        "processes": "oracle and comparator each run as python -I -S subprocesses",
    }
    verdicts = gates(summary, isolation)

    rejected_by_code: dict[str, int] = {}
    for row in reduced["rejected"]:
        rejected_by_code[row["code"]] = rejected_by_code.get(row["code"], 0) + 1

    body: dict[str, Any] = {
        "schema": "tavonel.v2.oracle_independence.v2",
        "protocol": rel(PROTOCOL),
        "protocol_sha256": sha_file(PROTOCOL),
        "split": "held_out",
        "started_at": started,
        "ended_at": now(),
        "wall_seconds": round(time.time() - clock, 1),
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
        "cohort": {
            "frame": rel(frame_module.FRAME),
            "salt": SALT,
            "order": "ascending sha256 of (lineage id + salt), fixed before any payload was read",
            "candidates": len(lineages),
            "excluded_lineages": len(spent),
            "family_quota": FAMILY_QUOTA,
            "floor": FLOOR,
            "max_payload_bytes": frame_module.MAX_PAYLOAD_BYTES,
            "payload_bound_basis": "compute; declared, and not tuned to an outcome",
        },
        "isolation": isolation,
        "what_this_is_not": (
            "not an independent specification. The oracle implements the same "
            "declared rules the engine does, written down by reading the engine. "
            "A defect in the specification is still common-mode."
        ),
        "prior_result_not_restated": (
            "the 28-pair Wikipedia result remains same-implementation full "
            "recomputation equivalence and is not called an independent oracle"
        ),
        "lineages_considered": reduced["considered"],
        "by_family": reduced["by_family"],
        "rejected_by_code": dict(sorted(rejected_by_code.items())),
        "summary": summary,
        "gates": verdicts,
        "verdict": "PASS" if all(verdicts.values()) else "FAIL",
        "http": pool.stats(),
        "cache": cache.stats(),
    }

    detail = OUT / "oracle_v2_pairs.json"
    detail.write_text(
        json.dumps(reduced["admitted"], indent=1, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    body["pairs_path"] = rel(detail)
    body["pairs_sha256"] = sha_file(detail)
    body["result_digest"] = canonical_sha({"summary": summary, "gates": verdicts})

    written = write_immutable(
        "oracle-independence-v2", body, tool=Path(__file__).resolve(), protocol=PROTOCOL
    )
    print(json.dumps({**written, "verdict": body["verdict"]}, indent=2))
    print(json.dumps(summary, indent=2)[:2400])
    return 0 if body["verdict"] == "PASS" else 4


if __name__ == "__main__":
    raise SystemExit(main())
