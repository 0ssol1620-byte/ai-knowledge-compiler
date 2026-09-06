from __future__ import annotations

import hashlib
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
CIR = ROOT / "packages" / "cir-python" / "src"
sys.path.insert(0, str(CIR))

from akc_cir.dependency import DependencyEdge, DependencyGraph, EdgeType  # noqa: E402
from akc_cir.identity import normalize_text_for_identity  # noqa: E402
from akc_cir.recompilation import content_hash, plan_recompilation, verify_equivalence  # noqa: E402
from akc_cir.semantic_diff import (  # noqa: E402
    DiffLevel,
    DocumentShape,
    UnitSnapshot,
    diff_documents,
)

API = "https://en.wikipedia.org/w/api.php"
CUTOFF = "2026-07-01T00:00:00Z"
TITLES = (
    "Artificial intelligence",
    "Machine learning",
    "Large language model",
    "Quantum computing",
    "Climate change",
    "CRISPR",
    "Bitcoin",
    "Kubernetes",
    "Rust (programming language)",
    "JSON",
    "World Wide Web",
    "Cryptography",
)
OUT = ROOT / "research" / "experiments" / "H1-B-REAL-REVISION-01"
CORPUS = OUT / "corpus"
RECEIPTS = OUT / "receipts"
HEADING_RE = re.compile(r"^(={2,6})\s*(.*?)\s*\1\s*$")
TAG_RE = re.compile(r"<[^>]+>")
COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
REF_BLOCK_RE = re.compile(r"<ref\b[^>]*>.*?</ref\s*>", re.IGNORECASE | re.DOTALL)
REF_SELF_RE = re.compile(r"<ref\b[^>]*/\s*>", re.IGNORECASE)
WIKILINK_RE = re.compile(r"\[\[(?:[^|\]]+\|)?([^\]]+)\]\]")
EXTERNAL_LINK_RE = re.compile(r"\[https?://[^\s\]]+(?:\s+([^\]]+))?\]")
SPACE_RE = re.compile(r"\s+")
ADAPTER_VERSION = 3
SKIP_HEADINGS = {"references", "external links", "see also", "further reading", "notes"}
REDIRECT_RE = re.compile(r"^#REDIRECT\s+\[\[([^\]]+)\]\]", re.IGNORECASE)


def now() -> str:
    return datetime.now(UTC).isoformat()


def sha_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def sha_text(text: str) -> str:
    return sha_bytes(text.encode("utf-8"))


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-") or "document"


def normalize_heading(value: str) -> str:
    value = re.sub(r"\{\{.*?\}\}", " ", value)
    value = re.sub(r"\[\[(?:[^\]|]+\|)?([^\]]+)\]\]", r"\1", value)
    value = TAG_RE.sub(" ", value)
    return SPACE_RE.sub(" ", value).strip(" ='\"")


def normalize_body(value: str) -> str:
    # Approximate rendered semantic text while excluding citation/revision markup.
    value = COMMENT_RE.sub(" ", value)
    value = REF_BLOCK_RE.sub(" ", value)
    value = REF_SELF_RE.sub(" ", value)
    value = WIKILINK_RE.sub(r"\1", value)
    value = EXTERNAL_LINK_RE.sub(lambda match: match.group(1) or " ", value)
    value = value.replace(chr(39) * 3, "").replace(chr(39) * 2, "")
    value = TAG_RE.sub(" ", value)
    return SPACE_RE.sub(" ", html.unescape(value)).strip()


@dataclass(frozen=True, slots=True)
class Revision:
    title: str
    revid: int
    parentid: int
    timestamp: str
    mw_sha1: str
    text: str


def fetch_pair(title: str) -> tuple[Revision, Revision]:
    params = {
        "action": "query",
        "format": "json",
        "formatversion": "2",
        "prop": "revisions",
        "titles": title,
        "rvprop": "ids|timestamp|sha1|content",
        "rvslots": "main",
        "rvlimit": "2",
        "rvstart": CUTOFF,
        "rvdir": "older",
    }
    url = API + "?" + urllib.parse.urlencode(params)
    if not url.startswith("https://en.wikipedia.org/w/api.php?"):
        raise RuntimeError("Wikipedia API URL escaped allowlist")
    request = urllib.request.Request(  # noqa: S310
        url, headers={"User-Agent": "TAVONEL-public-revision-holdout/1.0"}
    )
    payload: dict[str, Any] | None = None
    for attempt in range(5):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
                payload = json.load(response)
            break
        except urllib.error.HTTPError as exc:
            if exc.code != 429 or attempt == 4:
                raise
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            delay = min(30.0, max(3.0, float(retry_after or (5 * (attempt + 1)))))
            time.sleep(delay)
    if payload is None:
        raise RuntimeError(f"Wikipedia revision fetch produced no payload for {title}")
    pages = payload.get("query", {}).get("pages", [])
    if len(pages) != 1:
        raise RuntimeError(f"unexpected page result for {title}")
    revisions = pages[0].get("revisions", [])
    if len(revisions) != 2:
        raise RuntimeError(f"expected two revisions for {title}")

    parsed: list[Revision] = []
    for item in revisions:
        slots = item.get("slots", {})
        main = slots.get("main", {}) if isinstance(slots, dict) else {}
        text = str(main.get("content", ""))
        if not text:
            raise RuntimeError(f"revision content missing for {title}")
        parsed.append(
            Revision(
                title=title,
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


def section_units(revision: Revision) -> tuple[list[UnitSnapshot], DocumentShape]:
    redirect = REDIRECT_RE.search(revision.text.strip())
    if redirect is not None:
        target = normalize_heading(redirect.group(1))
        logical_id = (
            "wiki-unit:"
            + hashlib.sha256(f"{revision.title}\nredirect-target".encode()).hexdigest()[:24]
        )
        evidence_id = (
            "wiki-evidence:"
            + hashlib.sha256(f"{revision.title}\nredirect-target".encode()).hexdigest()[:24]
        )
        unit = UnitSnapshot(
            logical_id=logical_id,
            text=target,
            document_path=(revision.title, "redirect-target"),
            anchor="redirect-target",
            neighbour_anchors=("", ""),
            evidence_id=evidence_id,
            explicit_identifier="redirect-target",
            metadata_fingerprint="",
        )
        return [unit], DocumentShape(
            heading_path_set=frozenset({unit.document_path}),
            block_count=1,
        )

    lines = revision.text.splitlines()
    path_stack: list[str] = []
    current_heading = "lead"
    current_level = 1
    body: list[str] = []
    raw_sections: list[tuple[tuple[str, ...], str, str]] = []

    def flush() -> None:
        text = normalize_body("\n".join(body))
        heading = normalize_heading(current_heading) or "lead"
        if len(text) >= 120 and heading.casefold() not in SKIP_HEADINGS:
            raw_sections.append((tuple(path_stack), heading, text))

    for line in lines:
        match = HEADING_RE.match(line.strip())
        if match is None:
            body.append(line)
            continue
        flush()
        body = []
        level = len(match.group(1))
        heading = normalize_heading(match.group(2)) or "untitled"
        if level <= current_level:
            keep = max(0, level - 2)
            path_stack = path_stack[:keep]
        else:
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
        logical_id = (
            "wiki-unit:" + hashlib.sha256(f"{revision.title}\n{explicit}".encode()).hexdigest()[:24]
        )
        prev_anchor = anchors[index - 1] if index else ""
        next_anchor = anchors[index + 1] if index + 1 < len(anchors) else ""
        evidence_id = (
            "wiki-evidence:"
            + hashlib.sha256(f"{revision.title}\n{explicit}".encode()).hexdigest()[:24]
        )
        units.append(
            UnitSnapshot(
                logical_id=logical_id,
                text=text,
                document_path=(revision.title, *canonical_path),
                anchor=heading,
                neighbour_anchors=(prev_anchor, next_anchor),
                evidence_id=evidence_id,
                explicit_identifier=explicit,
                metadata_fingerprint="",
            )
        )
    shape = DocumentShape(
        heading_path_set=frozenset(unit.document_path for unit in units),
        block_count=len(units),
    )
    return units, shape


def artifact_id(kind: str, suffix: str) -> str:
    return f"artifact:{kind}:{suffix}"


def make_graph_and_inventory(
    title: str,
    before: list[UnitSnapshot],
    after: list[UnitSnapshot],
) -> tuple[DependencyGraph, list[str], dict[str, tuple[str, ...]]]:
    logical_ids = sorted({unit.logical_id for unit in before} | {unit.logical_id for unit in after})
    dependencies: dict[str, tuple[str, ...]] = {}
    edges: list[DependencyEdge] = []
    for logical_id in logical_ids:
        section_artifact = artifact_id("section", logical_id)
        dependencies[section_artifact] = (logical_id,)
        edges.append(DependencyEdge(section_artifact, logical_id, EdgeType.DEPENDS_ON))

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
        bucket_artifact = artifact_id("topic-bucket", f"{doc_key}:{bucket}")
        dependencies[bucket_artifact] = members
        for logical_id in members:
            edges.append(DependencyEdge(bucket_artifact, logical_id, EdgeType.DEPENDS_ON))
    return DependencyGraph(edges), sorted(dependencies), dependencies


def artifact_hashes(
    dependencies: dict[str, tuple[str, ...]], units: list[UnitSnapshot]
) -> dict[str, str]:
    by_id = {unit.logical_id: unit.text for unit in units}
    result: dict[str, str] = {}
    for artifact, logical_ids in dependencies.items():
        payload = [
            {
                "logical_id": logical_id,
                "semantic_text": normalize_text_for_identity(by_id.get(logical_id, "<ABSENT>")),
            }
            for logical_id in logical_ids
        ]
        result[artifact] = content_hash(payload)
    return result


def run_pair(before: Revision, after: Revision) -> dict[str, Any]:
    before_units, before_shape = section_units(before)
    after_units, after_shape = section_units(after)
    if not before_units or not after_units:
        raise RuntimeError(f"no eligible section units for {before.title}")
    diff = diff_documents(
        before_sha256=sha_text(before.text),
        after_sha256=sha_text(after.text),
        level=DiffLevel.SEMANTIC,
        before_shape=before_shape,
        after_shape=after_shape,
        before_units=before_units,
        after_units=after_units,
        source=f"wikipedia:{before.title}",
    )
    graph, inventory, dependencies = make_graph_and_inventory(
        before.title, before_units, after_units
    )
    plan = plan_recompilation(diff=diff, graph=graph, artifacts=inventory)
    before_hashes = artifact_hashes(dependencies, before_units)
    full_hashes = artifact_hashes(dependencies, after_units)
    planned = set(plan.to_rebuild)
    selective = {artifact: full_hashes[artifact] for artifact in inventory if artifact in planned}
    carried = {
        artifact: before_hashes[artifact] for artifact in inventory if artifact not in planned
    }
    equivalence = verify_equivalence(
        full_rebuild=full_hashes,
        selective_rebuild=selective,
        carried_over=carried,
        plan=plan,
    )
    changed_ids = sorted(diff.changed_logical_ids)
    return {
        "title": before.title,
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
        "changed_logical_ids": len(changed_ids),
        "unresolved_identity_count": len(diff.unresolved),
        "change_kinds": sorted({change.kind.value for change in diff.changes}),
        "artifact_count": len(inventory),
        "rebuild_count": len(plan.to_rebuild),
        "rebuild_fraction": len(plan.to_rebuild) / len(inventory) if inventory else 0.0,
        "work_avoided_fraction": plan.work_avoided_fraction,
        "equivalent": equivalence.equivalent,
        "stale_left_behind": len(equivalence.stale_left_behind),
        "diverged": list(equivalence.diverged),
        "missing_from_selective": list(equivalence.missing_from_selective),
    }


def main() -> int:
    CORPUS.mkdir(parents=True, exist_ok=True)
    RECEIPTS.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    for title in TITLES:
        before, after = fetch_pair(title)
        title_dir = CORPUS / slug(title)
        title_dir.mkdir(parents=True, exist_ok=True)
        (title_dir / f"{before.revid}.wikitext").write_text(before.text, encoding="utf-8")
        (title_dir / f"{after.revid}.wikitext").write_text(after.text, encoding="utf-8")
        record = run_pair(before, after)
        records.append(record)
        time.sleep(2.0)
        print(
            json.dumps(
                {
                    "title": title,
                    "equivalent": record["equivalent"],
                    "rebuild_fraction": record["rebuild_fraction"],
                },
                sort_keys=True,
            )
        )

    changed = [record for record in records if record["changed_logical_ids"] > 0]
    receipt: dict[str, Any] = {
        "schema": "tavonel.real-public-revision-holdout.v1",
        "generated_at": now(),
        "source": "English Wikipedia MediaWiki revision API",
        "holdout_adapter_version": ADAPTER_VERSION,
        "semantic_text_policy": (
            "semantic section projection: comments/ref citation bodies/HTML/wiki-link "
            "markup normalized; derived semantic artifacts hash identity-canonical text"
        ),
        "cutoff": CUTOFF,
        "pair_count": len(records),
        "changed_pair_count": len(changed),
        "all_pairs_equivalent": all(record["equivalent"] for record in records),
        "stale_left_behind_total": sum(record["stale_left_behind"] for record in records),
        "total_artifacts": sum(record["artifact_count"] for record in records),
        "total_rebuilt": sum(record["rebuild_count"] for record in records),
        "mean_rebuild_fraction": (
            sum(record["rebuild_fraction"] for record in records) / len(records) if records else 0.0
        ),
        "records": records,
        "external_gpu_cost_usd": 0.0,
        "claim_boundary": (
            "Independent public real-revision holdout; Wikipedia text is used as "
            "revision data, not as evidence of domain-specific legal/regulatory "
            "performance."
        ),
    }
    encoded = json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    receipt["receipt_sha256"] = sha_bytes(encoded)
    path = RECEIPTS / "wikipedia-real-revision-holdout-v3-development.json"
    path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "receipt": str(path.relative_to(ROOT)),
                "all_pairs_equivalent": receipt["all_pairs_equivalent"],
                "stale_left_behind_total": receipt["stale_left_behind_total"],
                "mean_rebuild_fraction": receipt["mean_rebuild_fraction"],
            },
            sort_keys=True,
        )
    )
    return (
        0
        if receipt["all_pairs_equivalent"]
        and receipt["stale_left_behind_total"] == 0
        and len(changed) >= 8
        else 2
    )


if __name__ == "__main__":
    raise SystemExit(main())
