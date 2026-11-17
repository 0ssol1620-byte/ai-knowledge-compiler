"""WO-D02-3B: the census writes labels and counts only, and refuses a hash mismatch."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import pytest
from PIL import Image
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from benchmark.screen.native_census import main, run_census
from benchmark.v6.contracts import ContractError

_BODY = "Quarterly SECRETMARKER evidence summary. " * 12


def _pdf(*texts: str | None) -> bytes:
    writer = PdfWriter()
    font = writer._add_object(
        DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
    )
    for text in texts:
        if text is None:
            buf = io.BytesIO()
            Image.new("RGB", (612, 792), "white").save(buf, format="PDF", resolution=72)
            writer.add_page(PdfReader(io.BytesIO(buf.getvalue())).pages[0])
            continue
        page = writer.add_blank_page(width=612, height=792)
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
        )
        content = DecodedStreamObject()
        ops = b"BT /F1 11 Tf 72 720 Td 14 TL "
        for i in range(0, len(text), 80):
            ops += b"(" + text[i : i + 80].encode("ascii") + b") Tj T* "
        content.set_data(ops + b"ET")
        page[NameObject("/Contents")] = writer._add_object(content)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _setup(tmp_path: Path, bad_hash: bool = False) -> tuple[Path, Path]:
    docs = {"digital.pdf": _pdf(_BODY), "raster.pdf": _pdf(None), "mixed.pdf": _pdf(_BODY, None)}
    lines = []
    for name, data in docs.items():
        (tmp_path / name).write_bytes(data)
        digest = hashlib.sha256(b"x" if bad_hash else data).hexdigest()
        lines.append(json.dumps({"doc_id": name, "source_sha256": "sha256:" + digest}))
    rec = tmp_path / "records.jsonl"
    rec.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return rec, tmp_path


def test_census_rows_have_labels_and_no_text(tmp_path: Path) -> None:
    rec, root = _setup(tmp_path)
    out = tmp_path / "out" / "census.jsonl"
    assert main([str(rec), str(root), str(out)]) == 0
    raw = out.read_text(encoding="utf-8")
    assert "SECRETMARKER" not in raw
    rows = [json.loads(x) for x in raw.splitlines()]
    assert len(rows) == 4
    keys = {
        "doc_id",
        "source_sha256",
        "page",
        "technical_class",
        "first_route",
        "estimated_columns",
        "native_word_count",
        "native_text_chars",
        "image_coverage",
    }
    assert all(set(r) == keys for r in rows)
    by = {(r["doc_id"], r["page"]): r for r in rows}
    assert by["digital.pdf", 1]["first_route"] == "native"
    assert by["raster.pdf", 1]["first_route"] != "native"
    assert by["mixed.pdf", 1]["first_route"] == "native"
    assert by["mixed.pdf", 2]["first_route"] != "native"
    assert by["raster.pdf", 1]["image_coverage"] == 1.0
    assert by["digital.pdf", 1]["native_word_count"] > 0


def test_hash_mismatch_refuses_and_writes_nothing(tmp_path: Path) -> None:
    rec, root = _setup(tmp_path, bad_hash=True)
    out = tmp_path / "census.jsonl"
    with pytest.raises(ContractError, match="byte hash mismatch"):
        run_census(rec, root, out)
    assert not out.exists()


def test_missing_file_refuses(tmp_path: Path) -> None:
    rec, root = _setup(tmp_path)
    (root / "raster.pdf").unlink()
    with pytest.raises(ContractError, match="file missing"):
        run_census(rec, root, tmp_path / "o.jsonl")
