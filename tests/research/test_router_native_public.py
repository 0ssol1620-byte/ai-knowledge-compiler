"""Actual Native arm execution on the already-public, spent Explore corpus.

Manual integration suite: requires the existing public sample directory.
No network, OCR, fresh holdout or evaluator annotations are used. Empty pages
remain in the output. This measures availability, not semantic correctness.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import pytest
from akc_native_parsers.models import ParseContext
from akc_native_parsers.pdf_parser import parse_pdf_to_cir
from akc_router.native_observation import project_native_pages

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def corpus():
    location = os.environ.get("TAVONEL_PUBLIC_SAMPLE_ROOT")
    if not location:
        pytest.fail("Explicit existing public sample root required for this integration suite")
    root = Path(location).resolve(strict=True)
    metadata = root.parents[1] / "lib" / "explore-sample.sources.json"
    raw = metadata.read_bytes()
    rows = json.loads(raw)
    assert len(rows) == 5
    assert sum(row["pageCount"] for row in rows) == 290
    output = ROOT / ".chatgpt2codex" / "native-public-observations"
    output.mkdir(parents=True, exist_ok=False)
    code = ROOT / "packages" / "router" / "src" / "akc_router" / "native_observation.py"
    freeze = {
        "confirmatory_eligible": False,
        "source_manifest_sha256": hashlib.sha256(raw).hexdigest(),
        "projection_code_sha256": hashlib.sha256(code.read_bytes()).hexdigest(),
        "scope": "Existing public five-filing corpus; availability, not correctness",
        "inputs": [
            {
                "id": row["documentId"],
                "sha256": row["representationSha256"],
                "pages": row["pageCount"],
                "representation_kind": row["representationKind"],
            }
            for row in rows
        ],
        "password_policy": "Empty-password allowance only for the known Apple original annual PDF",
    }
    (output / "FREEZE.json").write_text(json.dumps(freeze, indent=2) + "\n", encoding="utf-8")
    return root, rows, output


@pytest.mark.parametrize("index", range(5))
def test_native_observation_preserves_declared_page_denominator(corpus, index: int) -> None:
    root, rows, output = corpus
    row = rows[index]
    path = (root / row["representationFilename"]).resolve(strict=True)
    assert path.is_relative_to(root)
    data = path.read_bytes()
    sha = "sha256:" + hashlib.sha256(data).hexdigest()
    assert sha == row["representationSha256"]
    began, cpu = time.perf_counter(), time.process_time()
    document = parse_pdf_to_cir(
        filename=path.name,
        declared_mime="application/pdf",
        data=data,
        context=ParseContext(
            tenant_id="native-development",
            document_id=row["documentId"],
            document_version_id=sha,
            created_at=datetime(2026, 9, 9, tzinfo=UTC),
        ),
        max_pages=row["pageCount"],
        password=b""
        if row["documentId"] == "apple-form-10-k" and row["representationKind"] == "original"
        else None,
    )
    observations = project_native_pages(
        document, expected_source_sha256=sha, expected_page_count=row["pageCount"]
    )
    elapsed, cpu_elapsed = time.perf_counter() - began, time.process_time() - cpu
    assert len(observations) == row["pageCount"]
    assert [p.page_index0 for p in observations] == list(range(row["pageCount"]))
    assert all(p.quality_verified is False for p in observations)
    for page in observations:
        assert (
            page.output_sha256 == "sha256:" + hashlib.sha256(page.text.encode("utf-8")).hexdigest()
        )
    payload = (
        "\n".join(json.dumps(asdict(page), ensure_ascii=False) for page in observations) + "\n"
    )
    with (output / (row["documentId"] + ".jsonl")).open("x", encoding="utf-8") as stream:
        stream.write(payload)
    receipt = {
        "document_id": row["documentId"],
        "source_sha256": sha,
        "declared_pages": row["pageCount"],
        "text_pages": sum(bool(page.text) for page in observations),
        "no_text_pages": sum(not page.text for page in observations),
        "located_blocks": sum(page.located_block_count for page in observations),
        "unlocated_blocks": sum(page.unlocated_block_count for page in observations),
        "local_wall_seconds": elapsed,
        "local_cpu_seconds": cpu_elapsed,
        "output_sha256": "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        "quality_verified": False,
        "confirmatory_eligible": False,
    }
    with (output / (row["documentId"] + ".receipt.json")).open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(receipt, indent=2) + "\n")
