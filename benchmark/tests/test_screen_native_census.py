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
        "width_pt",
        "height_pt",
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


def _records(tmp_path: Path, *rows: dict[str, str]) -> Path:
    rec = tmp_path / "recs.jsonl"
    rec.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return rec


def test_output_is_write_once_and_receipt_names_image_coverage(tmp_path: Path) -> None:
    rec, root = _setup(tmp_path)
    out = tmp_path / "census.jsonl"
    run_census(rec, root, out)
    before = out.read_bytes()
    with pytest.raises(ContractError, match="already exists"):
        run_census(rec, root, out)
    assert out.read_bytes() == before
    receipt = json.loads(out.with_name("census.jsonl.receipt.json").read_text(encoding="utf-8"))
    assert "presence" in receipt["image_coverage"] and "not an area" in receipt["image_coverage"]
    assert receipt["pages"] == 4 and receipt["out_sha256"] == (
        "sha256:" + hashlib.sha256(before).hexdigest()
    )
    (tmp_path / "other").mkdir()
    rec2, root2 = _setup(tmp_path / "other")
    stale = tmp_path / "stale.jsonl"
    stale.with_name("stale.jsonl.receipt.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ContractError, match="already exists"):
        run_census(rec2, root2, stale)
    assert not stale.exists()


def test_duplicate_doc_id_and_escaping_doc_id_refused(tmp_path: Path) -> None:
    rec, root = _setup(tmp_path)
    lines = rec.read_text(encoding="utf-8").splitlines()
    dup = _records(tmp_path, json.loads(lines[0]), json.loads(lines[0]))
    with pytest.raises(ContractError, match="duplicate doc_id"):
        run_census(dup, root, tmp_path / "d.jsonl")
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    outside = _pdf(_BODY)
    (tmp_path / "outside.pdf").write_bytes(outside)
    digest = "sha256:" + hashlib.sha256(outside).hexdigest()
    esc = _records(tmp_path, {"doc_id": "../outside.pdf", "source_sha256": digest})
    with pytest.raises(ContractError, match="outside the corpus root"):
        run_census(esc, corpus, tmp_path / "e.jsonl")
    absolute = _records(
        tmp_path, {"doc_id": str(tmp_path / "outside.pdf"), "source_sha256": digest}
    )
    with pytest.raises(ContractError, match="outside the corpus root"):
        run_census(absolute, corpus, tmp_path / "a.jsonl")
    assert not (tmp_path / "e.jsonl").exists() and not (tmp_path / "a.jsonl").exists()


@pytest.mark.parametrize("row", [{"source_sha256": "sha256:" + "0" * 64}, {"doc_id": "a.pdf"}])
def test_record_without_doc_id_or_hash_is_a_contract_error(
    tmp_path: Path, row: dict[str, str]
) -> None:
    with pytest.raises(ContractError):
        run_census(_records(tmp_path, row), tmp_path, tmp_path / "o.jsonl")


@pytest.mark.parametrize("row", [[1, 2], "good.pdf", 5, None])
def test_record_that_is_not_an_object_is_a_contract_error(tmp_path: Path, row: object) -> None:
    rec = tmp_path / "recs.jsonl"
    rec.write_text(json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(ContractError, match="not an object"):
        run_census(rec, tmp_path, tmp_path / "o.jsonl")


def test_doc_ids_naming_the_same_file_are_duplicates(tmp_path: Path) -> None:
    data = _pdf(_BODY)
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "good.pdf").write_bytes(data)
    digest = "sha256:" + hashlib.sha256(data).hexdigest()
    spellings = ["./sub/good.pdf", "sub/../sub/good.pdf", "sub//good.pdf"]
    if Path(str(tmp_path / "SUB" / "GOOD.pdf")).is_file():  # case-insensitive file system
        spellings.append("SUB/GOOD.pdf")
    for i, other in enumerate(spellings):
        rec = _records(
            tmp_path,
            {"doc_id": "sub/good.pdf", "source_sha256": digest},
            {"doc_id": other, "source_sha256": digest},
        )
        out = tmp_path / f"dup{i}.jsonl"
        with pytest.raises(ContractError, match="duplicate"):
            run_census(rec, tmp_path, out)
        assert not out.exists(), other


def test_receipt_is_written_first_so_no_output_is_left_without_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from benchmark.screen import native_census

    rec, root = _setup(tmp_path)
    real = native_census.census_pages
    out = tmp_path / "census.jsonl"
    receipt = out.with_name("census.jsonl.receipt.json")

    def receipt_appears(doc_id: str, data: bytes) -> list[dict[str, object]]:
        if not receipt.exists():  # another writer takes the receipt name after the check
            receipt.write_text("{}", encoding="utf-8")
        return real(doc_id, data)

    monkeypatch.setattr(native_census, "census_pages", receipt_appears)
    with pytest.raises(FileExistsError):
        run_census(rec, root, out)
    assert not out.exists()
    receipt.unlink()

    def output_appears(doc_id: str, data: bytes) -> list[dict[str, object]]:
        if not out.exists():  # another writer takes the output name after the check
            out.write_bytes(b"theirs")
        return real(doc_id, data)

    monkeypatch.setattr(native_census, "census_pages", output_appears)
    with pytest.raises(FileExistsError):
        run_census(rec, root, out)
    assert out.read_bytes() == b"theirs" and not receipt.exists()


def _text_and_image_pdf() -> bytes:
    from pypdf.generic import RectangleObject

    writer = PdfWriter()
    page = writer.add_page(PdfReader(io.BytesIO(_pdf(_BODY))).pages[0])
    buf = io.BytesIO()
    Image.new("RGB", (200, 200), "red").save(buf, format="PDF", resolution=72)
    page.merge_page(PdfReader(io.BytesIO(buf.getvalue())).pages[0])
    page.mediabox = RectangleObject((0, 0, 595, 842))
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def test_text_and_image_page_class_and_metadata_page_size(tmp_path: Path) -> None:
    data = _text_and_image_pdf()
    (tmp_path / "both.pdf").write_bytes(data)
    rec = _records(
        tmp_path,
        {"doc_id": "both.pdf", "source_sha256": "sha256:" + hashlib.sha256(data).hexdigest()},
    )
    out = tmp_path / "both.jsonl"
    run_census(rec, tmp_path, out)
    (row,) = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines()]
    assert (row["width_pt"], row["height_pt"]) == (595.0, 842.0)
    assert row["image_coverage"] == 1 and row["native_word_count"] > 0
    assert row["technical_class"] == "NATIVE_COMPLEX"
