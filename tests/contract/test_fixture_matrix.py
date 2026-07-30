from __future__ import annotations

import json
from pathlib import Path

import pytest
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from tests.fixtures.build_safe_fixture_matrix import (
    MANIFEST_PATH,
    PASSWORD,
    build_fixture_matrix,
    contains_external_relationship,
    declared_png_pixels,
    maximum_zip_compression_ratio,
    zlib_runtime_available,
)

REQUIRED_PATHS = {
    "valid/text.pdf",
    "valid/scan.pdf",
    "valid/mixed.pdf",
    "valid/encrypted.pdf",
    "valid/docx-with-tables.docx",
    "valid/pptx-with-groups.pptx",
    "valid/xlsx-formulas.xlsx",
    "valid/html-with-tables.html",
    "hostile/fake-extension.pdf.exe",
    "hostile/oversized-image.png",
    "hostile/zip-bomb.docx",
    "hostile/external-relationship.docx",
    "hostile/malformed-xref.pdf",
    "hostile/javascript-link.md",
    "hostile/svg-script.svg",
    "hostile/prompt-injection.pdf",
}


def test_fixture_manifest_exactly_enumerates_masterplan_matrix() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "fixture-matrix-1.0.0"
    assert manifest["generator_version"] == "safe-fixtures-1.0.0"
    assert manifest["policy"] == {
        "synthetic_only": True,
        "network_required": False,
        "executable_payloads": False,
        "maximum_generated_bytes_per_fixture": 1_048_576,
    }
    paths = [entry["path"] for entry in manifest["fixtures"]]
    assert set(paths) == REQUIRED_PATHS
    assert len(paths) == len(set(paths)) == 16
    assert all(entry["expected"] for entry in manifest["fixtures"])


def test_safe_fixture_builder_generates_bounded_real_formats(tmp_path: Path) -> None:
    paths = build_fixture_matrix(tmp_path)
    assert len(paths) == 16
    assert all(path.is_file() and path.stat().st_size <= 1_048_576 for path in paths.values())

    assert PdfReader(paths["valid-text-pdf"]).pages[0].extract_text() == ("SAFE DIGITAL TEXT PDF")
    assert len(PdfReader(paths["valid-scan-pdf"]).pages) == 1
    assert len(PdfReader(paths["valid-mixed-pdf"]).pages) == 2
    encrypted = PdfReader(paths["valid-encrypted-pdf"])
    assert encrypted.is_encrypted
    assert encrypted.decrypt(PASSWORD) != 0

    assert paths["hostile-fake-extension"].read_bytes().startswith(b"MZ")
    assert declared_png_pixels(paths["hostile-oversized-image"].read_bytes()) == (100_000 * 100_000)
    assert maximum_zip_compression_ratio(paths["hostile-zip-bomb-docx"]) > 100
    assert contains_external_relationship(paths["hostile-external-relationship"])
    with pytest.raises(PdfReadError):
        PdfReader(paths["hostile-malformed-xref"], strict=True)
    assert "javascript:" in paths["hostile-javascript-link"].read_text(encoding="utf-8")
    assert "<script>" in paths["hostile-svg-script"].read_text(encoding="utf-8")
    assert "UNTRUSTED DOCUMENT TEXT" in (
        PdfReader(paths["hostile-prompt-injection"]).pages[0].extract_text()
    )
    assert zlib_runtime_available()
