from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
import subprocess
import sys
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import dataclass
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
CIR = ROOT / "packages" / "cir-python" / "src"
sys.path.insert(0, str(CIR))

from akc_cir.dependency import DependencyEdge, DependencyGraph, EdgeType  # noqa: E402
from akc_cir.recompilation import content_hash, plan_recompilation, verify_equivalence  # noqa: E402
from akc_cir.semantic_diff import DiffLevel, DocumentShape, UnitSnapshot, diff_documents  # noqa: E402

API = "https://en.wikipedia.org/w/api.php"
HEADING_RE = re.compile(r"^(={2,6})\s*(.*?)\s*\1\s*$")
TAG_RE = re.compile(r"<[^>]+>")
COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
SPACE_RE = re.compile(r"\s+")

LIVE_INPUTS = (
    Path("packages/cir-python/src/akc_cir/semantic_diff.py"),
    Path("packages/cir-python/src/akc_cir/identity.py"),
    Path("packages/cir-python/src/akc_cir/dependency.py"),
    Path("packages/cir-python/src/akc_cir/recompilation.py"),
)


def now() -> str:
    return datetime.now(UTC).isoformat()


def sha_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def sha_file(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def sha_text(text: str) -> str:
    return sha_bytes(text.encode("utf-8"))


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-") or "document"


def load_protocol() -> dict[str, Any]:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    if protocol.get("status") != "PREPARED_BEFORE_FETCH":
        raise RuntimeError("protocol status is not PREPARED_BEFORE_FETCH")
    titles = protocol.get("titles")
    if not isinstance(titles, list) or len(titles) != 12 or len(set(titles)) != len(titles):
        raise RuntimeError("protocol must contain exactly 12 unique pre-registered titles")
    return protocol


def frozen_hashes() -> dict[str, str]:
    paths = [PROTOCOL, Path(__file__), *(ROOT / item for item in LIVE_INPUTS)]
    return {str(path.relative_to(ROOT)).replace("\\", "/"): sha_file(path) for path in paths}


def verify_hash_map(expected: dict[str, str], *, root: Path = ROOT) -> None:
    for relative, digest in expected.items():
        path = root / relative
        if not path.is_file():
            raise RuntimeError(f"frozen input missing: {relative}")
        actual = sha_file(path)
        if actual != digest:
            raise RuntimeError(f"frozen input drift: {relative}: expected {digest}, got {actual}")


def git_head() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def freeze() -> int:
    protocol = load_protocol()
    if CORPUS.exists() and any(CORPUS.rglob("*")):
        raise RuntimeError("refusing freeze: corpus bytes already exist")
    if RESULT.exists():
        raise RuntimeError("refusing freeze: result receipt already exists")
    RECEIPTS.mkdir(parents=True, exist_ok=True)
    hashes = frozen_hashes()
    seal: dict[str, Any] = {
        "schema": "tavonel.family-b.current-core-public-revision.pre-fetch-seal.v1",
        "experiment_id": protocol["experiment_id"],
        "sealed_at": now(),
        "git_head": git_head(),
        "corpus_bytes_observed_before_seal": 0,
        "external_gpu_cost_usd": 0.0,
        "hashes": hashes,
    }
    encoded = json.dumps(seal, sort_keys=True, separators=(",", ":")).encode("utf-8")
    seal["seal_sha256"] = sha_bytes(encoded)
    SEAL.write_text(json.dumps(seal, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"sealed": str(SEAL.relative_to(ROOT)), "seal_sha256": seal["seal_sha256"]}))
    return 0


def verify_seal() -> dict[str, Any]:
    if not SEAL.is_file():
        raise RuntimeError("pre-fetch seal missing; run --freeze before any network fetch")
    seal = json.loads(SEAL.read_text(encoding="utf-8"))
    hashes = seal.get("hashes")
    if not isinstance(hashes, dict) or not hashes:
        raise RuntimeError("pre-fetch seal has no frozen hashes")
    verify_hash_map(hashes)
    return seal


@dataclass(frozen=True, slots=True)
class Revision:
    requested_title: str
    resolved_title: str
    revid: int
    parentid: int
    timestamp: str
    mw_sha1: str
    text: str


def fetch_pair(title: str, cutoff: str) -> tuple[Revision, Revision]:
    params = {
        "action": "query",
        "format": "json",
        "formatversion": "2",
        "redirects": "1",
        "prop": "revisions",
        "titles": title,
        "rvprop": "ids|timestamp|sha1|content",
        "rvslots": "main",
        "rvlimit": "2",
        "rvstart": cutoff,
        "rvdir": "older",
    }
    url = API + "?" + urllib.parse.urlencode(params)
    if not url.startswith(API + "?"):
        raise RuntimeError("Wikipedia API URL escaped allowlist")
    request = urllib.request.Request(url, headers={"User-Agent": "TAVONEL-research/1.0"})  # noqa: S310
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
        payload = json.load(response)
    pages = payload.get("query", {}).get("pages", [])
    if len(pages) != 1 or pages[0].get("missing") is True:
        raise RuntimeError(f"unexpected or missing page result for {title}")
    resolved_title = str(pages[0].get("title", title))
    revisions = pages[0].get("revisions", [])
    if len(revisions) != 2:
        raise RuntimeError(f"expected two revisions for {title}, got {len(revisions)}")
    parsed: list[Revision] = []
    for item in revisions:
        main = item.get("slots", {}).get("main", {})
        text = str(main.get("content", ""))
        if not text:
            raise RuntimeError(f"revision content missing for {title}")
        parsed.append(
            Revision(
                requested_title=title,
                resolved_title=resolved_title,
                revid=int(item["revid"]),
                parentid=int(item.get("parentid", 0)),
                timestamp=str(item["timestamp"]),
                mw_sha1=str(item.get("sha1", "")),
                text=text,
            )
        )
    newer, older = parsed[0], parsed[1]
    if newer.revid == older.revid or newer.text == older.text:
        raise RuntimeError(f"revision pair did not change content for {title}")
    return older, newer


def normalize_heading(value: str) -> str:
    value = re.sub(r"\{\{.*?\}\}", " ", value)
    value = re.sub(r"\[\[(?:[^\]|]+\|)?([^\]]+)\]\]", r"\1", value)
    value = TAG_RE.sub(" ", value)
    return SPACE_RE.sub(" ", value).strip(" ='\"")


def normalize_body(value: str) -> str:
    value = COMMENT_RE.sub(" ", value)
    value = TAG_RE.sub(" ", value)
    return SPACE_RE.sub(" ", value).strip()


def section_units(revision: Revision, skip_headings: set[str]) -> tuple[list[UnitSnapshot], DocumentShape]:
    path_stack: list[str] = []
    current_heading = "lead"
    current_level = 1
    body: list[str] = []
    raw_sections: list[tuple[tuple[str, ...], str, str]] = []

    def flush() -> None:
        text = normalize_body("\n".join(body))
        heading = normalize_heading(current_heading) or "lead"
        if len(text) >= 120 and heading.casefold() not in skip_headings:
            raw_sections.append((tuple(path_stack), heading, text))

    for line in revision.text.splitlines():
        match = HEADING_RE.match(line.strip())
        if match is None:
            body.append(line)
            continue
        flush()
        body = []
        level = len(match.group(1))
        heading = normalize_heading(match.group(2)) or "untitled"
        keep = max(0, level - 2)
        path_stack = path_stack[:keep]
        path_stack.append(heading)
        current_heading = heading
        current_level = level
    flush()

    occurrence: dict[tuple[str, ...], int] = {}
    units: list[UnitSnapshot] = []
    anchors = [heading for _, heading, _ in raw_sections]
    for index, (path, heading, text) in enumerate(raw_sections):
        canonical_path = path or (heading,)
        count = occurrence.get(canonical_path, 0)
        occurrence[canonical_path] = count + 1
        explicit = "/".join(canonical_path) + (f"#{count}" if count else "")
        logical_id = "wiki-unit:" + hashlib.sha256(
            f"{revision.resolved_title}\n{explicit}".encode("utf-8")
        ).hexdigest()[:24]
        prev_anchor = anchors[index - 1] if index else ""
        next_anchor = anchors[index + 1] if index + 1 < len(anchors) else ""
        units.append(
            UnitSnapshot(
                logical_id=logical_id,
                text=text,
                document_path=(revision.resolved_title, *canonical_path),
                anchor=heading,
                neighbour_anchors=(prev_anchor, next_anchor),
                evidence_id=f"wiki-rev:{revision.revid}:section:{index}",
                explicit_identifier=explicit,
                metadata_fingerprint=f"revision:{revision.revid}",
            )
        )
    shape = DocumentShape(
        heading_path_set=frozenset(unit.document_path for unit in units),
        block_count=len(units),
        unit_order=tuple(unit.logical_id for unit in units),
    )
    return units, shape


def artifact_id(kind: str, suffix: str) -> str:
    return f"artifact:{kind}:{suffix}"


def make_graph_and_inventory(
    title: str, before: list[UnitSnapshot], after: list[UnitSnapshot]
) -> tuple[DependencyGraph, list[str], dict[str, tuple[str, ...]]]:
    logical_ids = sorted({unit.logical_id for unit in before} | {unit.logical_id for unit in after})
    dependencies: dict[str, tuple[str, ...]] = {}
    edges: list[DependencyEdge] = []
    for logical_id in logical_ids:
        artifact = artifact_id("section", logical_id)
        dependencies[artifact] = (logical_id,)
        edges.append(DependencyEdge(artifact, logical_id, EdgeType.DEPENDS_ON))
    doc_key = hashlib.sha256(title.encode("utf-8")).hexdigest()[:16]
    doc_artifact = artifact_id("document-index", doc_key)
    dependencies[doc_artifact] = tuple(logical_ids)
    for logical_id in logical_ids:
        edges.append(DependencyEdge(doc_artifact, logical_id, EdgeType.DEPENDS_ON))
    for bucket in range(4):
        members = tuple(
            logical_id
            for logical_id in logical_ids
            if int(hashlib.sha256(logical_id.encode("utf-8")).hexdigest()[:8], 16) % 4 == bucket
        )
        if not members:
            continue
        artifact = artifact_id("topic-bucket", f"{doc_key}:{bucket}")
        dependencies[artifact] = members
        for logical_id in members:
            edges.append(DependencyEdge(artifact, logical_id, EdgeType.DEPENDS_ON))
    return DependencyGraph(edges), sorted(dependencies), dependencies


def artifact_hashes(dependencies: dict[str, tuple[str, ...]], units: list[UnitSnapshot]) -> dict[str, str]:
    by_id = {unit.logical_id: unit.text for unit in units}
    return {
        artifact: content_hash(
            [{"logical_id": logical_id, "text": by_id.get(logical_id, "<ABSENT>")} for logical_id in ids]
        )
        for artifact, ids in dependencies.items()
    }


def run_pair(before: Revision, after: Revision, skip_headings: set[str]) -> dict[str, Any]:
    before_units, before_shape = section_units(before, skip_headings)
    after_units, after_shape = section_units(after, skip_headings)
    if not before_units or not after_units:
        raise RuntimeError(f"no eligible section units for {before.requested_title}")
    diff = diff_documents(
        before_sha256=sha_text(before.text),
        after_sha256=sha_text(after.text),
        level=DiffLevel.SEMANTIC,
        before_shape=before_shape,
        after_shape=after_shape,
        before_units=before_units,
        after_units=after_units,
        source=f"wikipedia:{before.resolved_title}",
    )
    graph, inventory, dependencies = make_graph_and_inventory(
        before.resolved_title, before_units, after_units
    )
    plan = plan_recompilation(diff=diff, graph=graph, artifacts=inventory)
    before_hashes = artifact_hashes(dependencies, before_units)
    full_hashes = artifact_hashes(dependencies, after_units)
    planned = set(plan.to_rebuild)
    selective = {artifact: full_hashes[artifact] for artifact in inventory if artifact in planned}
    carried = {artifact: before_hashes[artifact] for artifact in inventory if artifact not in planned}
    equivalence = verify_equivalence(
        full_rebuild=full_hashes,
        selective_rebuild=selective,
        carried_over=carried,
        plan=plan,
    )
    channel_counts = Counter(change.channel.value for change in diff.changes)
    kind_counts = Counter(change.kind.value for change in diff.changes)
    return {
        "requested_title": before.requested_title,
        "resolved_title": before.resolved_title,
        "before_revision_id": before.revid,
        "after_revision_id": after.revid,
        "before_timestamp": before.timestamp,
        "after_timestamp": after.timestamp,
        "before_sha256": sha_text(before.text),
        "after_sha256": sha_text(after.text),
        "before_mw_sha1": before.mw_sha1,
        "after_mw_sha1": after.mw_sha1,
        "before_units": len(before_units),
        "after_units": len(after_units),
        "changed_logical_ids": list(diff.changed_logical_ids),
        "changed_logical_id_count": len(diff.changed_logical_ids),
        "unresolved_identity_count": len(diff.unresolved),
        "change_channel_counts": dict(sorted(channel_counts.items())),
        "change_kind_counts": dict(sorted(kind_counts.items())),
        "artifact_count": len(inventory),
        "rebuild_count": len(plan.to_rebuild),
        "rebuild_fraction": len(plan.to_rebuild) / len(inventory) if inventory else 0.0,
        "work_avoided_fraction": plan.work_avoided_fraction,
        "equivalent": equivalence.equivalent,
        "stale_left_behind": list(equivalence.stale_left_behind),
        "diverged": list(equivalence.diverged),
        "missing_from_selective": list(equivalence.missing_from_selective),
    }


def save_corpus_pair(before: Revision, after: Revision) -> None:
    title_dir = CORPUS / slug(before.requested_title)
    title_dir.mkdir(parents=True, exist_ok=True)
    (title_dir / f"{before.revid}.wikitext").write_text(before.text, encoding="utf-8")
    (title_dir / f"{after.revid}.wikitext").write_text(after.text, encoding="utf-8")
    metadata = {
        "requested_title": before.requested_title,
        "resolved_title": before.resolved_title,
        "source": "English Wikipedia MediaWiki revision API",
        "before": {
            "revision_id": before.revid,
            "parent_id": before.parentid,
            "timestamp": before.timestamp,
            "mw_sha1": before.mw_sha1,
            "content_sha256": sha_text(before.text),
        },
        "after": {
            "revision_id": after.revid,
            "parent_id": after.parentid,
            "timestamp": after.timestamp,
            "mw_sha1": after.mw_sha1,
            "content_sha256": sha_text(after.text),
        },
    }
    (title_dir / "source-metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def run() -> int:
    protocol = load_protocol()
    seal = verify_seal()
    if RESULT.exists():
        raise RuntimeError("result receipt already exists; experiment is single-run")
    if CORPUS.exists() and any(path.is_file() for path in CORPUS.rglob("*")):
        raise RuntimeError("corpus is not empty before first run")
    cutoff = str(protocol["cutoff"])
    titles = tuple(str(title) for title in protocol["titles"])
    skip_headings = {str(item).casefold() for item in protocol["projection"]["skip_headings"]}

    try:
        pairs = [(title, *fetch_pair(title, cutoff)) for title in titles]
    except Exception as exc:
        RECEIPTS.mkdir(parents=True, exist_ok=True)
        blocked = {
            "schema": "tavonel.family-b.current-core-public-revision.blocked.v1",
            "experiment_id": protocol["experiment_id"],
            "blocked_at": now(),
            "stage": "network_fetch_before_corpus_persist",
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
        record = run_pair(before, after, skip_headings)
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
    changed = [record for record in records if record["changed_logical_id_count"] > 0]
    gates = protocol["frozen_safety_gates"]
    safety_pass = all(record["equivalent"] for record in records) and sum(
        len(record["stale_left_behind"]) for record in records
    ) == int(gates["stale_left_behind_total"])
    adequacy_pass = len(changed) >= int(gates["minimum_changed_pair_count"])
    receipt: dict[str, Any] = {
        "schema": "tavonel.family-b.current-core-public-revision.result.v1",
        "experiment_id": protocol["experiment_id"],
        "generated_at": now(),
        "classification": "FRESH_PROSPECTIVE_PUBLIC_REVISION_CURRENT_CORE_EVIDENCE",
        "protocol_sha256": sha_file(PROTOCOL),
        "pre_fetch_seal_sha256": seal["seal_sha256"],
        "frozen_git_head": seal["git_head"],
        "source": protocol["source"],
        "cutoff": cutoff,
        "pair_count": len(records),
        "changed_pair_count": len(changed),
        "safety_gate_pass": safety_pass,
        "evidence_adequacy_pass": adequacy_pass,
        "all_pairs_equivalent": all(record["equivalent"] for record in records),
        "stale_left_behind_total": sum(len(record["stale_left_behind"]) for record in records),
        "unresolved_identity_total": sum(record["unresolved_identity_count"] for record in records),
        "total_artifacts": sum(record["artifact_count"] for record in records),
        "total_rebuilt": sum(record["rebuild_count"] for record in records),
        "mean_rebuild_fraction": statistics.fmean(fractions) if fractions else 0.0,
        "median_rebuild_fraction": statistics.median(fractions) if fractions else 0.0,
        "max_rebuild_fraction": max(fractions, default=0.0),
        "mean_work_avoided_fraction": statistics.fmean(
            [float(record["work_avoided_fraction"]) for record in records]
        ) if records else 0.0,
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
            },
            sort_keys=True,
        )
    )
    return 0 if safety_pass and adequacy_pass else 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--freeze", action="store_true")
    group.add_argument("--run", action="store_true")
    group.add_argument("--verify-seal", action="store_true")
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
