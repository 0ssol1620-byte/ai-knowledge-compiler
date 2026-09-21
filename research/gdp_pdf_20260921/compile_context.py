"""Local CPU adapter: PDF text layer WITH geometry -> TAVONEL Product Core V2 -> one packet.

Reads the Product Core compiler out of the p0p2 productization worktree WITHOUT modifying it
(sys.path only). Compilation is pure CPU and deterministic: no network, no LLM, no embedding
model, no database. The only non-determinism a caller could introduce is ``requested_at``,
which is frozen to a constant here.

What the live product sends Product Core per region is page number, paragraph text and a
thousandths bounding box, and nothing else (``buildProductCoreV2Request`` in
gates-lanes/gdp/nextjs/lib/core-runtime-v2.ts). This adapter produces exactly that input from
the PDF's own text layer with PyMuPDF, and sends the same route the product sends
(``high_assurance``, 10 credits, 52,000 ms -- lib/execution-budget.ts).

v1 of this adapter (2026-09-21, superseded) sent ONE region per page carrying the whole page's
text and NO bbox. That made every unit ``REGION_CITATION_UNAVAILABLE`` and every world
``review_required``, and it measured page-anchored text chunks rather than the product. The v1
packets are kept under ``compiled_context_local_v1``; they are not overwritten.

Scope: born-digital PDFs only. A page with no text layer contributes no region, and a document
whose whole text layer is below ``MIN_CHARS_PER_PAGE`` per page is refused with
``scanned_no_text_layer`` rather than compiled from nothing. Those documents need the parser
stage, which this lane does not run; see compiled_context/README.md for the forecast.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pymupdf

P0P2_PACKAGES = Path(r"D:\CodexProjects\ai-knowledge-compiler-p0p2-productization\packages")
for _pkg in ("product-core", "cir-python", "domain-packs"):
    _src = str(P0P2_PACKAGES / _pkg / "src")
    if _src not in sys.path:
        sys.path.insert(0, _src)

from akc_cir.identity import normalize_bbox1000, normalize_text_for_identity  # noqa: E402
from akc_cir.models import BBox1000, BlockType  # noqa: E402
from akc_product_core import ProductCoreCompiler  # noqa: E402
from akc_product_core.contracts import (  # noqa: E402
    ProductCoreCompileRequest,
    ProductCoreDocument,
    ProductCoreRegion,
    ProductCoreRoute,
)

# Frozen so the same PDF always compiles to the same world_state_id and output_sha256.
REQUESTED_AT = datetime(2026, 9, 21, 0, 0, 0, tzinfo=UTC)
CORE_RELEASE_DIGEST = "sha256:" + "0" * 64
TENANT = "gdp-eval"
# Below this, the text layer is noise and the document is a scan: it belongs to the parser stage.
MIN_CHARS_PER_PAGE = 50
ADAPTER_VERSION = "gdp-pdf-compiled-context/2-geometry"
MAX_REGION_CHARS = 200_000  # ProductCoreRegion.text contract maximum.

# The product's own route, copied from core-runtime-v2.ts / execution-budget.ts.
ROUTE_QUALITY = "high_assurance"
ROUTE_MAX_COST_CREDITS = 10
ROUTE_MAX_LATENCY_MS = 52_000  # WORKER_MAX_DURATION_MS 60_000 - WORKER_SETTLEMENT_RESERVE_MS 8_000

# Packet budget. Stated, applied in a fixed order, recorded in the packet and in index.json.
# Nothing is ever dropped silently.
PACKET_BUDGET_CHARS = 400_000
# Sections are truncated head-kept/tail-dropped in this order until the packet fits. The header,
# the budget notice and the validation report are never truncated. The source note goes first
# because its text is already in the chunks, page- and bbox-anchored; relations go before
# entities because a relation is recoverable from a claim's own entityIds.
BUDGET_DROP_ORDER = (
    "source-note",
    "semantics/relations.jsonl",
    "evidence-locators",
    "semantics/entities.jsonl",
    "semantics/claims.jsonl",
    "chunks",
)

# Serialisation order. The compiled retrieval view comes first so that a reader who opens only
# the head of the packet sees the compiled, locator-carrying layer rather than the raw source
# note, which is the same text without the anchors.
SECTION_ORDER = (
    "chunks",
    "semantics/claims.jsonl",
    "semantics/entities.jsonl",
    "semantics/relations.jsonl",
    "evidence-locators",
    "source-note",
)
SECTION_TITLES = {
    "source-note": "## Compiled source note",
    "chunks": "## Retrieval chunks (compiled, page + bbox anchored)",
    "evidence-locators": "## Evidence locators (evidenceId -> page + bbox1000)",
    "semantics/claims.jsonl": "## semantics/claims.jsonl",
    "semantics/entities.jsonl": "## semantics/entities.jsonl",
    "semantics/relations.jsonl": "## semantics/relations.jsonl",
}


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def bbox1000(rect: pymupdf.Rect, page: pymupdf.Rect) -> BBox1000 | None:
    """Containing box on the 0..1000 grid, or None when the page box has no area.

    Floor on the near edges and ceil on the far edges, so the integer box CONTAINS the measured
    rectangle rather than approximating it. That also gives positive area for any block that has
    positive area, which the BBox1000 contract requires. Nothing is invented: every number here
    is a rounding of a coordinate PyMuPDF measured.
    """
    width, height = page.x1 - page.x0, page.y1 - page.y0
    if width <= 0 or height <= 0:
        return None

    def scale(value: float, origin: float, extent: float) -> float:
        return max(0.0, min(1000.0, (value - origin) / extent * 1000.0))

    x0 = math.floor(scale(rect.x0, page.x0, width))
    y0 = math.floor(scale(rect.y0, page.y0, height))
    x1 = math.ceil(scale(rect.x1, page.x0, width))
    y1 = math.ceil(scale(rect.y1, page.y0, height))
    if x1 <= x0:
        x0, x1 = (x0 - 1, x1) if x0 > 0 else (x0, x0 + 1)
    if y1 <= y0:
        y0, y1 = (y0 - 1, y1) if y0 > 0 else (y0, y0 + 1)
    return BBox1000(root=(x0, y0, x1, y1))


def page_paragraphs(pdf_path: Path) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """(paragraph blocks in reading order, geometry stats).

    One entry per non-empty text block PyMuPDF reports, with its bbox normalised to 0..1000 of
    the page box. ``page.rotation_matrix`` is applied first: on a rotated page ``get_text``
    reports unrotated coordinates while ``page.rect`` is the rotated box, and skipping the
    transform puts 1.8% of this corpus's blocks outside their own page.
    """
    blocks: list[dict[str, Any]] = []
    stats = {
        "pages": 0,
        "pages_with_text": 0,
        "rotated_pages": 0,
        "blocks_dropped_empty": 0,
        "blocks_dropped_image": 0,
        "blocks_clamped": 0,
        "blocks_without_bbox": 0,
        "blocks_dropped_duplicate_evidence": 0,
    }
    # Product Core derives an evidence id from (document version, page, bbox1000, text), with the
    # box quantised to a 2-per-mille grid by ``normalize_bbox1000`` and the text folded by
    # ``normalize_text_for_identity``. Two regions that agree after both foldings ARE the same
    # evidence, and sending both makes the Core fail closed on a duplicate knowledge-object id.
    # This corpus hits it: single glyphs drawn twice within two per-mille of the same spot, and
    # blocks differing only in whitespace or punctuation. Collapsing them loses no locator. The
    # key below calls the Core's own two normalisers, so it is the evidence discriminator itself
    # rather than an approximation of it.
    seen: set[tuple[int, tuple[int, int, int, int] | None, str]] = set()
    with pymupdf.open(str(pdf_path)) as document:
        for number, page in enumerate(document, start=1):
            stats["pages"] += 1
            if page.rotation:
                stats["rotated_pages"] += 1
            box, matrix = page.rect, page.rotation_matrix
            rows: list[tuple[float, float, int, dict[str, Any]]] = []
            for index, raw in enumerate(page.get_text("blocks")):
                x0, y0, x1, y1, text, _block_no, block_type = raw[:7]
                if block_type != 0:
                    stats["blocks_dropped_image"] += 1
                    continue
                cleaned = text.strip()
                if not cleaned:
                    stats["blocks_dropped_empty"] += 1
                    continue
                rect = pymupdf.Rect(x0, y0, x1, y1) * matrix
                rect.normalize()
                if (
                    rect.x0 < box.x0 - 0.5
                    or rect.y0 < box.y0 - 0.5
                    or rect.x1 > box.x1 + 0.5
                    or rect.y1 > box.y1 + 0.5
                ):
                    stats["blocks_clamped"] += 1
                geometry = bbox1000(rect, box)
                if geometry is None:
                    stats["blocks_without_bbox"] += 1
                key = (
                    number,
                    normalize_bbox1000(geometry.as_tuple() if geometry else None),
                    normalize_text_for_identity(cleaned[:MAX_REGION_CHARS]),
                )
                if key in seen:
                    stats["blocks_dropped_duplicate_evidence"] += 1
                    continue
                seen.add(key)
                rows.append(
                    (
                        rect.y0,
                        rect.x0,
                        index,
                        {
                            "page_number1": number,
                            "text": cleaned[:MAX_REGION_CHARS],
                            "bbox1000": geometry,
                        },
                    )
                )
            if rows:
                stats["pages_with_text"] += 1
            # Reading order: top to bottom, then left to right, in the page's DISPLAYED space,
            # tie-broken by the PDF's own block index so the order is total and stable.
            rows.sort(key=lambda row: (round(row[0], 1), round(row[1], 1), row[2]))
            blocks.extend(row[3] for row in rows)
    return blocks, stats


def compile_packet(task: dict[str, Any]) -> dict[str, Any]:
    """Compile one task's PDF. Returns {'ok': False, 'reason': ...} when there is no text layer."""
    pdf = Path(task["pdf_local_path"])
    paragraphs, stats = page_paragraphs(pdf)
    total_chars = sum(len(row["text"]) for row in paragraphs)
    page_count = task["pdf_pages"] or stats["pages"] or 1
    if not paragraphs or total_chars < MIN_CHARS_PER_PAGE * page_count:
        return {
            "ok": False,
            "reason": "scanned_no_text_layer",
            "text_chars": total_chars,
            "regions": len(paragraphs),
            "geometry": stats,
            "pages_with_text": stats["pages_with_text"],
            "page_count": page_count,
        }

    regions = tuple(
        ProductCoreRegion(
            region_id=f"p{row['page_number1']:05d}r{order:05d}",
            page_index0=row["page_number1"] - 1,
            page_number1=row["page_number1"],
            order=order,
            block_type=BlockType.PARAGRAPH,
            text=row["text"],
            bbox1000=row["bbox1000"],
            authority="informal",
        )
        for order, row in enumerate(paragraphs)
    )
    content_sha256 = "sha256:" + task["pdf_sha256"]
    identifier = f"gdp-{task['task_id']}"
    document = ProductCoreDocument(
        native_id=identifier,
        connector_type="gdp-pdf",
        immutable_object_key=f"immutable/{TENANT}/{task['task_id']}/source.pdf",
        ocr_object_key=f"immutable/{TENANT}/{task['task_id']}/text-layer.json",
        content_sha256=content_sha256,
        title=task["task_id"],
        source_filename=Path(task["pdf_repo_path"]).name,
        page_count=page_count,
        regions=regions,
    )
    request = ProductCoreCompileRequest(
        request_id=identifier,
        idempotency_key=identifier,
        tenant_id=TENANT,
        workspace_id=TENANT,
        collection_id="gdp-pdf",
        requested_at=REQUESTED_AT,
        route=ProductCoreRoute(
            operation_class="initial_compile",
            quality_requirement=ROUTE_QUALITY,
            max_cost_credits=ROUTE_MAX_COST_CREDITS,
            max_latency_ms=ROUTE_MAX_LATENCY_MS,
            privacy_policy="approved_customer_data",
        ),
        documents=(document,),
    )
    response = ProductCoreCompiler(core_release_digest=CORE_RELEASE_DIGEST).compile(
        request, input_sha256=content_sha256
    )
    return {
        "ok": True,
        "response": response,
        "regions": len(regions),
        "pages_with_text": stats["pages_with_text"],
        "page_count": page_count,
        "text_chars": total_chars,
        "geometry": stats,
    }


def _jsonl_lines(files: dict[str, Any], path: str) -> list[str]:
    blob = files.get(path)
    return [line for line in blob.content.splitlines() if line.strip()] if blob else []


def _sections(candidate: Any) -> dict[str, list[str]]:
    """Every truncatable section of the packet, as lines, straight from the candidate package."""
    files = {f.path: f for f in candidate.package.files}
    sections: dict[str, list[str]] = {}
    sections["source-note"] = [
        line
        for path in sorted(p for p in files if p.startswith("obsidian/Sources/"))
        for line in files[path].content.strip().splitlines()
    ]

    chunk_lines: list[str] = []
    locators: dict[str, tuple[Any, Any]] = {}
    for line in _jsonl_lines(files, "rag/chunks.jsonl"):
        row = json.loads(line)
        chunk_lines.append(
            f"### chunk {row.get('chunkId')} - page {row.get('pageNumber1')}, "
            f"bbox1000 {row.get('bbox1000')}, evidence {row.get('evidenceIds')}"
        )
        chunk_lines.extend(str(row.get("text", "")).strip().splitlines())
        chunk_lines.append("")
        for evidence_id, ref in zip(
            row.get("evidenceIds") or [], row.get("evidenceRefs") or [], strict=False
        ):
            locators.setdefault(evidence_id, (ref.get("pageNumber1"), ref.get("bbox1000")))
    sections["chunks"] = chunk_lines
    sections["evidence-locators"] = [
        json.dumps(
            {"evidenceId": key, "pageNumber1": page, "bbox1000": box},
            sort_keys=True,
            separators=(",", ":"),
        )
        for key, (page, box) in sorted(locators.items())
    ]
    for path in ("semantics/claims.jsonl", "semantics/entities.jsonl", "semantics/relations.jsonl"):
        sections[path] = _jsonl_lines(files, path)
    return sections


def render_packet(response: Any) -> tuple[str, dict[str, Any]]:
    """(packet markdown, budget record). The compiled artifact, serialised deterministically.

    Only what Product Core emitted is written: the source note, the retrieval chunks with their
    page + bbox1000 locators, an evidence locator index projected from the chunks' own
    ``evidenceRefs``, the semantics jsonl files and the validation verdict.
    """
    candidate = response.candidate
    files = {f.path: f for f in candidate.package.files}
    header = [
        "# TAVONEL compiled context",
        "",
        f"- runtime: {response.runtime}",
        f"- status: {response.status}",
        f"- lifecycle: {candidate.lifecycle}",
        f"- world_state_id: {candidate.world_state_id}",
        f"- manifest_digest: {candidate.manifest_digest}",
        f"- review_reasons: {len(candidate.review_reasons)}",
        "",
        "Compiled on CPU from the PDF's own text layer with its geometry: one region per text "
        "block, bbox normalised to 0..1000 of the page box. Page numbers are the PDF's page "
        "numbers. Every unit carries a page + bbox evidence locator.",
        "",
    ]
    validation = files.get("validation/report.json")
    tail = (
        ["## Validation report", "", "```json", validation.content.strip(), "```", ""]
        if validation
        else []
    )

    sections = _sections(candidate)
    totals = {name: len(lines) for name, lines in sections.items()}
    kept = dict(totals)

    def assemble() -> str:
        notice = [
            f"- `{SECTION_TITLES[name]}`: kept {kept[name]} of {totals[name]} lines"
            for name in SECTION_ORDER
            if kept[name] < totals[name]
        ]
        budget_block = (
            [
                "## Budget",
                "",
                f"This packet exceeded the stated budget of {PACKET_BUDGET_CHARS:,} characters, "
                "so sections were truncated head-kept / tail-dropped in the fixed order "
                f"{' > '.join(BUDGET_DROP_ORDER)}:",
                "",
                *notice,
                "",
            ]
            if notice
            else []
        )
        body: list[str] = []
        for name in SECTION_ORDER:
            if totals[name] == 0:
                continue
            if kept[name] == 0:
                body += [
                    SECTION_TITLES[name],
                    "",
                    "_dropped entirely by the packet budget rule._",
                    "",
                ]
                continue
            body += [SECTION_TITLES[name], "", *sections[name][: kept[name]], ""]
        return "\n".join([*header, *budget_block, *body, *tail]) + "\n"

    text = assemble()
    for name in BUDGET_DROP_ORDER:
        if len(text) <= PACKET_BUDGET_CHARS:
            break
        low, high = 0, kept[name]
        while low < high:  # largest prefix of this section that still fits
            middle = (low + high + 1) // 2
            kept[name] = middle
            if len(assemble()) <= PACKET_BUDGET_CHARS:
                low = middle
            else:
                high = middle - 1
        kept[name] = low
        text = assemble()

    budget = {
        "budget_chars": PACKET_BUDGET_CHARS,
        "drop_order": list(BUDGET_DROP_ORDER),
        "truncated": any(kept[name] < totals[name] for name in SECTION_ORDER),
        "section_lines_total": totals,
        "section_lines_kept": kept,
    }
    return text, budget


def compile_stats(response: Any, result: dict[str, Any]) -> dict[str, Any]:
    """Per-document compile facts for the evidence: regions, semantics, citation health."""
    files = {f.path: f for f in response.candidate.package.files}
    validation = json.loads(files["validation/report.json"].content)
    reasons = list(response.candidate.review_reasons)
    kinds: dict[str, int] = {}
    for reason in reasons:
        kind = reason.split(":", 1)[0]
        kinds[kind] = kinds.get(kind, 0) + 1
    return {
        "regions": result["regions"],
        "page_count": result["page_count"],
        "pages_with_text": result["pages_with_text"],
        "text_chars": result["text_chars"],
        "geometry": result["geometry"],
        "unit_count": validation["unitCount"],
        "claim_count": validation["claimCount"],
        "entity_count": validation["entityCount"],
        "relation_count": validation["relationCount"],
        "contradiction_candidate_count": validation["contradictionCandidateCount"],
        "retrieval_chunk_count": validation["retrievalChunkCount"],
        "retrieval_evidence_coverage": validation["retrievalEvidenceCoverage"],
        "semantic_evidence_coverage": validation["semanticEvidenceCoverage"],
        "blueprint": validation["blueprint"],
        "review_reason_count": len(reasons),
        "review_reason_kinds": kinds,
        "region_citation_unavailable": kinds.get("REGION_CITATION_UNAVAILABLE", 0),
        "semantic_claims_empty": "SEMANTIC_CLAIMS_EMPTY" in reasons,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--context-dir", required=True, type=Path)
    parser.add_argument("--limit", type=int, default=0, help="0 = every task in the catalog")
    args = parser.parse_args()

    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    tasks = catalog["tasks"][: args.limit] if args.limit else catalog["tasks"]
    args.context_dir.mkdir(parents=True, exist_ok=True)

    index: dict[str, Any] = {}
    compiled = skipped = 0
    for task in tasks:
        result = compile_packet(task)
        if not result["ok"]:
            index[task["task_id"]] = {
                "compiled": False,
                "reason": result["reason"],
                "adapter_version": ADAPTER_VERSION,
                "pages_with_text": result["pages_with_text"],
                "page_count": result["page_count"],
                "text_chars": result["text_chars"],
                "regions": result["regions"],
                "geometry": result["geometry"],
            }
            skipped += 1
            print(f"skip {task['task_id'][:8]} {result['reason']}", flush=True)
            continue
        response = result["response"]
        packet, budget = render_packet(response)
        out = args.context_dir / f"{task['task_id']}.md"
        out.write_text(packet, encoding="utf-8")
        stats = compile_stats(response, result)
        index[task["task_id"]] = {
            "compiled": True,
            "path": str(out),
            "packet_sha256": sha256_text(packet),
            "packet_bytes": len(packet.encode("utf-8")),
            "packet_chars": len(packet),
            # Recorded because a reader that pages the file sees only part of it per call.
            "packet_lines": packet.count("\n"),
            "packet_budget": budget,
            "adapter_version": ADAPTER_VERSION,
            "core_release_digest": CORE_RELEASE_DIGEST,
            "status": response.status,
            "lifecycle": response.candidate.lifecycle,
            "world_state_id": response.candidate.world_state_id,
            "manifest_digest": response.candidate.manifest_digest,
            "receipt_output_sha256": response.receipt.output_sha256,
            "compile_stats": stats,
            "review_reason_count": stats["review_reason_count"],
            "pages_with_text": stats["pages_with_text"],
            "page_count": stats["page_count"],
        }
        compiled += 1
        print(
            f"ok   {task['task_id'][:8]} regions={stats['regions']:5d} "
            f"claims={stats['claim_count']:5d} ent={stats['entity_count']:4d} "
            f"rel={stats['relation_count']:5d} rcu={stats['region_citation_unavailable']} "
            f"{response.candidate.lifecycle} {len(packet):,}c"
            f"{' TRUNCATED' if budget['truncated'] else ''}",
            flush=True,
        )

    (args.context_dir / "index.json").write_text(
        json.dumps(index, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(f"compiled={compiled} skipped_no_text_layer={skipped} -> {args.context_dir}")
    return 0


def demo() -> None:
    """Self-check: geometry is in range, the compile is deterministic, citations resolve."""
    page = pymupdf.Rect(0, 0, 612, 792)
    assert bbox1000(pymupdf.Rect(0, 0, 612, 792), page).as_tuple() == (0, 0, 1000, 1000)
    tiny = bbox1000(pymupdf.Rect(10, 10, 10.01, 10.01), page).as_tuple()
    assert tiny[0] < tiny[2] and tiny[1] < tiny[3], tiny
    assert bbox1000(pymupdf.Rect(0, 0, 10, 10), pymupdf.Rect(0, 0, 0, 0)) is None

    catalog = json.loads(
        (
            Path(r"D:\CodexData\gdp-pdf-cache\8d1efb32cb57baec2265bb84da03b30654761373")
            / "task_catalog.json"
        ).read_text(encoding="utf-8")
    )
    task = min(
        (t for t in catalog["tasks"] if (t["pdf_pages"] or 0) > 1), key=lambda t: t["pdf_pages"]
    )
    first, second = compile_packet(task), compile_packet(task)
    assert first["ok"] and second["ok"], first
    text_a, budget_a = render_packet(first["response"])
    text_b, _ = render_packet(second["response"])
    assert sha256_text(text_a) == sha256_text(text_b), "compilation is not deterministic"
    assert first["response"].receipt.output_sha256 == second["response"].receipt.output_sha256
    assert len(text_a) <= PACKET_BUDGET_CHARS, (len(text_a), budget_a)
    stats = compile_stats(first["response"], first)
    assert stats["region_citation_unavailable"] == 0, stats["review_reason_kinds"]
    assert stats["claim_count"] > 0 and stats["entity_count"] > 0, stats
    assert "bbox1000 [" in text_a, "chunks must carry a bbox locator"
    print(
        f"compile_context demo ok: {task['task_id'][:8]} regions={stats['regions']} "
        f"claims={stats['claim_count']} entities={stats['entity_count']} "
        f"relations={stats['relation_count']} rcu=0 "
        f"lifecycle={first['response'].candidate.lifecycle} "
        f"packet={len(text_a):,}c sha256 {sha256_text(text_a)[:16]}"
    )


if __name__ == "__main__":
    raise SystemExit(demo() if "--demo" in sys.argv else main())
