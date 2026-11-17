"""WO-D02-3B: the A1 native census as a command.

Runs the router test's chain (parse -> page preflight -> classify / first route) over every page
of the documents in a records JSONL and writes one row per page. A row holds counts and labels
only; it never carries page text. A document whose bytes do not hash to the record is refused
before anything is written.

    py -m benchmark.screen.native_census RECORDS.jsonl CORPUS_ROOT OUT.jsonl
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from akc_native_parsers import ParseContext, parse_pdf_to_cir
from akc_router import RouterContext, classify_page, select_first_route
from akc_router.preflight import PageMetrics
from akc_worker_document.worker import AnalysisWorker

from benchmark.v6.contracts import ContractError, require_sha256

# The worker measures none of these; they are sentinels, so the classifier must skip them.
UNKNOWN = frozenset(
    {
        "handwriting_probability",
        "rotation_degrees",
        "skew_degrees",
        "blur_score",
        "contrast_score",
        "small_text_score",
    }
)


def census_pages(doc_id: str, data: bytes, max_pages: int = 10_000) -> list[dict[str, Any]]:
    now = datetime(2026, 11, 16, tzinfo=UTC)
    document = parse_pdf_to_cir(
        filename=doc_id,
        declared_mime="application/pdf",
        data=data,
        context=ParseContext(
            tenant_id="census",
            document_id=doc_id,
            document_version_id=doc_id + ":v1",
            created_at=now,
            retrieved_at=now,
        ),
        max_pages=max_pages,
    )
    rows = []
    for page_no in range(1, len(document.metadata["pages"]) + 1):
        blocks = [b for b in document.blocks if b.source_refs[0].page_number1 == page_no]
        image = 1.0 if any("embedded_image_native" in b.quality_flags for b in blocks) else 0.0
        text = "\n".join(
            b.raw_text or "" for b in blocks if "embedded_image_native" not in b.quality_flags
        )
        m = AnalysisWorker._page_preflight(
            text,
            image_coverage=image,
            width_pt=612.0,
            height_pt=792.0,
            canonical_blocks=blocks,
        )
        pm = PageMetrics(
            page_index0=page_no - 1,
            width=612,
            height=792,
            native_text_chars=int(m["native_text_chars"]),
            native_word_count=int(m["native_words"]),
            native_block_count=max(1, len(blocks)),
            native_text_coverage=float(m["native_text_coverage"]),
            image_coverage=image,
            invalid_unicode_ratio=float(m["invalid_char_ratio"]),
            replacement_char_ratio=float(m["replacement_char_ratio"]),
            whitespace_anomaly_score=float(m["whitespace_anomaly_score"]),
            native_reading_order_score=float(m["native_reading_order_score"]),
            estimated_columns=int(m["estimated_columns"]),
            table_density=0.0,
            formula_density=0.0,
            chart_probability=0.0,
            handwriting_probability=0.5,
            rotation_degrees=0,
            skew_degrees=0.0,
            blur_score=0.5,
            contrast_score=0.5,
            small_text_score=0.5,
            script_distribution=dict(m["script_distribution"]),
            suspected_prompt_injection=False,
        )
        unknown = frozenset(m["unknown_visual_metrics"]) | UNKNOWN
        rows.append(
            {
                "page": page_no,
                "technical_class": classify_page(pm, unknown_metrics=unknown).value,
                "first_route": select_first_route(RouterContext(), pm).route.value,
                "estimated_columns": pm.estimated_columns,
                "native_word_count": pm.native_word_count,
                "native_text_chars": pm.native_text_chars,
                "image_coverage": image,
            }
        )
    return rows


def run_census(records_path: Path, corpus_root: Path, out_path: Path) -> int:
    records = [
        json.loads(line)
        for line in records_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    loaded = []
    for rec in records:  # integrity first: nothing is written if any document is off
        doc_id = rec["doc_id"]
        require_sha256(rec["source_sha256"], "source_sha256")
        path = Path(corpus_root) / doc_id
        if not path.is_file():
            raise ContractError(f"{doc_id}: file missing under corpus root")
        data = path.read_bytes()
        if "sha256:" + hashlib.sha256(data).hexdigest() != rec["source_sha256"]:
            raise ContractError(f"{doc_id}: byte hash mismatch")
        loaded.append((rec, data))
    lines = []
    for rec, data in loaded:
        for row in census_pages(rec["doc_id"], data):
            lines.append(
                json.dumps(
                    {"doc_id": rec["doc_id"], "source_sha256": rec["source_sha256"], **row},
                    sort_keys=True,
                )
            )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("".join(x + "\n" for x in lines), encoding="utf-8", newline="\n")
    return len(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("records", type=Path)
    ap.add_argument("corpus_root", type=Path)
    ap.add_argument("out", type=Path)
    a = ap.parse_args(argv)
    print(run_census(a.records, a.corpus_root, a.out), "pages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
