from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import statistics
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
EXPERIMENT = Path(__file__).resolve().parent
PROTOCOL = EXPERIMENT / "protocol.json"
CORPUS = EXPERIMENT / "corpus"
RECEIPTS = EXPERIMENT / "receipts"
SEAL = RECEIPTS / "pre-fetch-seal.json"
RESULT = RECEIPTS / "current-core-public-revision-result.json"
BLOCKED = RECEIPTS / "blocked-execution.json"
V01_DIR = ROOT / "research" / "experiments" / "H3-B-CURRENT-CORE-PUBLIC-REVISION-01"
V01_PROTOCOL = V01_DIR / "protocol.json"
V01_RUNNER = V01_DIR / "run_experiment.py"
AKC_CIR = ROOT / "packages" / "cir-python" / "src" / "akc_cir"
API = "https://en.wikipedia.org/w/api.php"


def _load_v01():
    spec = importlib.util.spec_from_file_location("tavonel_h3_b_v01_evaluator", V01_RUNNER)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load frozen V01 evaluator")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


V01 = _load_v01()


def now() -> str:
    return datetime.now(UTC).isoformat()


def sha_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def sha_file(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def git_head() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def load_protocol() -> dict[str, Any]:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    if protocol.get("status") != "PREPARED_BEFORE_V02_FETCH":
        raise RuntimeError("V02 protocol is not in pre-fetch state")
    if protocol.get("amendment_scope") != "TRANSPORT_ONLY":
        raise RuntimeError("V02 is not declared transport-only")
    if protocol.get("scientific_parameters_changed_from_v01") is not False:
        raise RuntimeError("V02 claims a scientific parameter change")
    return protocol


def assert_scientific_parameters_match_v01(v02: dict[str, Any]) -> None:
    v01 = json.loads(V01_PROTOCOL.read_text(encoding="utf-8"))
    keys = (
        "source",
        "cutoff",
        "titles",
        "projection",
        "frozen_safety_gates",
        "performance_metrics_are_measurements_not_pass_gates",
    )
    mismatches = [key for key in keys if v02.get(key) != v01.get(key)]
    if mismatches:
        raise RuntimeError(f"transport-only amendment changed scientific parameters: {mismatches}")


def frozen_hashes() -> dict[str, str]:
    files = [PROTOCOL, Path(__file__), V01_PROTOCOL, V01_RUNNER]
    files.extend(sorted(AKC_CIR.glob("*.py")))
    return {
        str(path.relative_to(ROOT)).replace("\\", "/"): sha_file(path)
        for path in files
    }


def verify_hash_map(expected: dict[str, str], *, root: Path = ROOT) -> None:
    for relative, digest in expected.items():
        path = root / relative
        if not path.is_file():
            raise RuntimeError(f"frozen input missing: {relative}")
        actual = sha_file(path)
        if actual != digest:
            raise RuntimeError(f"frozen input drift: {relative}: expected {digest}, got {actual}")


def freeze() -> int:
    protocol = load_protocol()
    assert_scientific_parameters_match_v01(protocol)
    if CORPUS.exists() and any(path.is_file() for path in CORPUS.rglob("*")):
        raise RuntimeError("refusing V02 freeze: corpus bytes already exist")
    if RESULT.exists():
        raise RuntimeError("refusing V02 freeze: result already exists")
    RECEIPTS.mkdir(parents=True, exist_ok=True)
    seal: dict[str, Any] = {
        "schema": "tavonel.family-b.current-core-public-revision.pre-fetch-seal.v2",
        "experiment_id": protocol["experiment_id"],
        "sealed_at": now(),
        "git_head": git_head(),
        "amendment_scope": "TRANSPORT_ONLY",
        "v01_blocker": "HTTP_429_BEFORE_PERSISTED_CORPUS_OR_EVALUATION_RESULT",
        "corpus_bytes_observed_before_v02_seal": 0,
        "external_gpu_cost_usd": 0.0,
        "hashes": frozen_hashes(),
    }
    encoded = json.dumps(seal, sort_keys=True, separators=(",", ":")).encode("utf-8")
    seal["seal_sha256"] = sha_bytes(encoded)
    SEAL.write_text(json.dumps(seal, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"sealed": str(SEAL.relative_to(ROOT)), "seal_sha256": seal["seal_sha256"]}))
    return 0


def verify_seal() -> dict[str, Any]:
    if not SEAL.is_file():
        raise RuntimeError("V02 pre-fetch seal missing")
    seal = json.loads(SEAL.read_text(encoding="utf-8"))
    hashes = seal.get("hashes")
    if not isinstance(hashes, dict) or not hashes:
        raise RuntimeError("V02 seal has no frozen hashes")
    verify_hash_map(hashes)
    protocol = load_protocol()
    assert_scientific_parameters_match_v01(protocol)
    return seal


def _resolved_title_map(query: dict[str, Any], requested_titles: tuple[str, ...]) -> dict[str, str]:
    mapping = {title: title for title in requested_titles}
    normalized = query.get("normalized", [])
    if isinstance(normalized, list):
        for item in normalized:
            source = str(item.get("from", ""))
            target = str(item.get("to", ""))
            for requested, current in tuple(mapping.items()):
                if current == source:
                    mapping[requested] = target
    redirects = query.get("redirects", [])
    if isinstance(redirects, list):
        for item in redirects:
            source = str(item.get("from", ""))
            target = str(item.get("to", ""))
            for requested, current in tuple(mapping.items()):
                if current == source:
                    mapping[requested] = target
    return mapping


def fetch_all_pairs(titles: tuple[str, ...], cutoff: str):
    params = {
        "action": "query",
        "format": "json",
        "formatversion": "2",
        "redirects": "1",
        "prop": "revisions",
        "titles": "|".join(titles),
        "rvprop": "ids|timestamp|sha1|content",
        "rvslots": "main",
        "rvlimit": "2",
        "rvstart": cutoff,
        "rvdir": "older",
    }
    url = API + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "TAVONEL-research/1.0 (prospective public revision experiment)",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
        payload = json.load(response)
    query = payload.get("query", {})
    pages = query.get("pages", [])
    if not isinstance(pages, list):
        raise RuntimeError("MediaWiki response has no pages list")
    resolved_map = _resolved_title_map(query, titles)
    page_by_title = {
        str(page.get("title", "")).casefold(): page
        for page in pages
        if page.get("missing") is not True
    }
    pairs = []
    for requested in titles:
        resolved = resolved_map[requested]
        page = page_by_title.get(resolved.casefold())
        if page is None:
            raise RuntimeError(f"missing batch page for {requested} -> {resolved}")
        revisions = page.get("revisions", [])
        if not isinstance(revisions, list) or len(revisions) != 2:
            raise RuntimeError(f"expected exactly two revisions for {requested}, got {len(revisions) if isinstance(revisions, list) else 'invalid'}")
        parsed = []
        for item in revisions:
            main = item.get("slots", {}).get("main", {})
            text = str(main.get("content", ""))
            if not text:
                raise RuntimeError(f"revision content missing for {requested}")
            parsed.append(
                V01.Revision(
                    requested_title=requested,
                    resolved_title=str(page.get("title", resolved)),
                    revid=int(item["revid"]),
                    parentid=int(item.get("parentid", 0)),
                    timestamp=str(item["timestamp"]),
                    mw_sha1=str(item.get("sha1", "")),
                    text=text,
                )
            )
        newer, older = parsed[0], parsed[1]
        if newer.revid == older.revid or newer.text == older.text:
            raise RuntimeError(f"batch revision pair did not change content for {requested}")
        pairs.append((requested, older, newer))
    return pairs


def save_corpus_pair(before, after) -> None:
    title_dir = CORPUS / V01.slug(before.requested_title)
    title_dir.mkdir(parents=True, exist_ok=True)
    (title_dir / f"{before.revid}.wikitext").write_text(before.text, encoding="utf-8")
    (title_dir / f"{after.revid}.wikitext").write_text(after.text, encoding="utf-8")
    metadata = {
        "requested_title": before.requested_title,
        "resolved_title": before.resolved_title,
        "source": "English Wikipedia MediaWiki revision API",
        "transport": "single_batched_mediawiki_query",
        "before": {
            "revision_id": before.revid,
            "parent_id": before.parentid,
            "timestamp": before.timestamp,
            "mw_sha1": before.mw_sha1,
            "content_sha256": V01.sha_text(before.text),
        },
        "after": {
            "revision_id": after.revid,
            "parent_id": after.parentid,
            "timestamp": after.timestamp,
            "mw_sha1": after.mw_sha1,
            "content_sha256": V01.sha_text(after.text),
        },
    }
    (title_dir / "source-metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def run() -> int:
    protocol = load_protocol()
    assert_scientific_parameters_match_v01(protocol)
    seal = verify_seal()
    if RESULT.exists():
        raise RuntimeError("V02 result already exists; experiment is single-result")
    if CORPUS.exists() and any(path.is_file() for path in CORPUS.rglob("*")):
        raise RuntimeError("V02 corpus is not empty before first run")
    titles = tuple(str(title) for title in protocol["titles"])
    cutoff = str(protocol["cutoff"])
    skip_headings = {str(item).casefold() for item in protocol["projection"]["skip_headings"]}

    try:
        pairs = fetch_all_pairs(titles, cutoff)
    except Exception as exc:
        RECEIPTS.mkdir(parents=True, exist_ok=True)
        blocked = {
            "schema": "tavonel.family-b.current-core-public-revision.blocked.v2",
            "experiment_id": protocol["experiment_id"],
            "blocked_at": now(),
            "stage": "single_batch_network_fetch_before_corpus_persist",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "seal_sha256": seal["seal_sha256"],
            "corpus_files_persisted": 0,
            "external_gpu_cost_usd": 0.0,
        }
        BLOCKED.write_text(json.dumps(blocked, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(blocked, sort_keys=True), file=sys.stderr)
        return 3

    records: list[dict[str, Any]] = []
    CORPUS.mkdir(parents=True, exist_ok=True)
    for title, before, after in pairs:
        save_corpus_pair(before, after)
        record = V01.run_pair(before, after, skip_headings)
        records.append(record)
        print(
            json.dumps(
                {
                    "title": title,
                    "equivalent": record["equivalent"],
                    "stale": len(record["stale_left_behind"]),
                    "rebuild_fraction": record["rebuild_fraction"],
                },
                sort_keys=True,
            )
        )

    fractions = [float(record["rebuild_fraction"]) for record in records]
    work_avoided = [float(record["work_avoided_fraction"]) for record in records]
    changed = [record for record in records if record["changed_logical_id_count"] > 0]
    gates = protocol["frozen_safety_gates"]
    stale_total = sum(len(record["stale_left_behind"]) for record in records)
    all_equivalent = all(record["equivalent"] for record in records)
    safety_pass = all_equivalent and stale_total == int(gates["stale_left_behind_total"])
    adequacy_pass = len(changed) >= int(gates["minimum_changed_pair_count"])
    receipt: dict[str, Any] = {
        "schema": "tavonel.family-b.current-core-public-revision.result.v2",
        "experiment_id": protocol["experiment_id"],
        "generated_at": now(),
        "classification": "PROSPECTIVE_PROTOCOL_WITH_PREDECLARED_TRANSPORT_ONLY_AMENDMENT",
        "supersedes_transport_of": protocol["supersedes_transport_of"],
        "amendment_scope": "TRANSPORT_ONLY",
        "scientific_parameters_changed_from_v01": False,
        "protocol_sha256": sha_file(PROTOCOL),
        "pre_fetch_seal_sha256": seal["seal_sha256"],
        "frozen_git_head": seal["git_head"],
        "source": protocol["source"],
        "cutoff": cutoff,
        "pair_count": len(records),
        "changed_pair_count": len(changed),
        "safety_gate_pass": safety_pass,
        "evidence_adequacy_pass": adequacy_pass,
        "all_pairs_equivalent": all_equivalent,
        "stale_left_behind_total": stale_total,
        "unresolved_identity_total": sum(record["unresolved_identity_count"] for record in records),
        "total_artifacts": sum(record["artifact_count"] for record in records),
        "total_rebuilt": sum(record["rebuild_count"] for record in records),
        "mean_rebuild_fraction": statistics.fmean(fractions) if fractions else 0.0,
        "median_rebuild_fraction": statistics.median(fractions) if fractions else 0.0,
        "max_rebuild_fraction": max(fractions, default=0.0),
        "mean_work_avoided_fraction": statistics.fmean(work_avoided) if work_avoided else 0.0,
        "performance_threshold_pre_registered": False,
        "records": records,
        "external_gpu_cost_usd": 0.0,
        "claim_boundary": protocol["claim_boundary"],
    }
    encoded = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode("utf-8")
    receipt["receipt_sha256"] = sha_bytes(encoded)
    RECEIPTS.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if BLOCKED.exists():
        BLOCKED.unlink()
    print(
        json.dumps(
            {
                "result": str(RESULT.relative_to(ROOT)),
                "safety_gate_pass": safety_pass,
                "evidence_adequacy_pass": adequacy_pass,
                "mean_rebuild_fraction": receipt["mean_rebuild_fraction"],
                "median_rebuild_fraction": receipt["median_rebuild_fraction"],
                "max_rebuild_fraction": receipt["max_rebuild_fraction"],
                "mean_work_avoided_fraction": receipt["mean_work_avoided_fraction"],
            },
            sort_keys=True,
        )
    )
    return 0 if safety_pass and adequacy_pass else 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--freeze", action="store_true")
    group.add_argument("--verify-seal", action="store_true")
    group.add_argument("--run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.freeze:
        return freeze()
    if args.verify_seal:
        verify_seal()
        print(json.dumps({"seal_verified": True, "seal": str(SEAL.relative_to(ROOT))}))
        return 0
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
