"""The Korean hard set and its receipts (program §28).

The same three pins the Office corpus carries — the fixtures rebuild to the
committed bytes, and every committed receipt equals a fresh run — plus the one
that only a language corpus needs: the manifest must state, for every family
§28 names, whether the coverage is a real package, a page this repository drew
and damaged on purpose, or nothing at all. A Korean corpus that silently omitted
`scanned Korean` would read as coverage it does not have, which is the failure
mode this file exists to prevent.
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from research.korean_hard_set_20260908.build_korean_hard_set import (
    CORPUS_ROOT,
    EXPECTED_PATH,
    FAMILIES,
    FORMATS,
    KOREAN_FONT,
    RENDERED_MANIFEST_PATH,
    build_corpus,
    write_expected,
)
from tools.office.qualify_office_readers import build_receipt, receipt_path, serialise

_RECEIPT_STEM = "korean_hard_set_qualification"


def _without_runtime(receipt: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in receipt.items() if key != "runtime"}


def test_the_korean_fixtures_rebuild_to_the_committed_bytes(tmp_path: Path) -> None:
    manifest = build_corpus(tmp_path)
    write_expected(manifest, tmp_path / "expected.json")

    assert (tmp_path / "expected.json").read_bytes() == EXPECTED_PATH.read_bytes()
    for entry in manifest["files"]:
        rebuilt = tmp_path / str(entry["path"])
        committed = CORPUS_ROOT / str(entry["path"])
        assert committed.is_file(), f"{entry['path']} is described but not committed"
        assert rebuilt.read_bytes() == committed.read_bytes(), entry["path"]


@pytest.mark.parametrize("source_format", FORMATS)
def test_the_committed_korean_receipt_matches_a_fresh_run(source_format: str) -> None:
    path = receipt_path(source_format, stem=_RECEIPT_STEM)
    assert path.is_file(), f"no committed Korean receipt for {source_format}"
    committed = json.loads(path.read_text(encoding="utf-8"))
    fresh = build_receipt(
        source_format,
        corpus_root=CORPUS_ROOT,
        expected_path=EXPECTED_PATH,
    )

    assert serialise(_without_runtime(fresh)) == serialise(_without_runtime(committed))
    assert committed["status"] == "BEST_EFFORT"


def test_every_section_28_family_states_real_synthetic_or_nothing() -> None:
    """No family is left out, and none of them is described as more than it is."""
    manifest = json.loads(EXPECTED_PATH.read_text(encoding="utf-8"))
    families = manifest["families"]
    assert set(families) == set(FAMILIES)
    for name, entry in families.items():
        assert entry["coverage"] in {"real", "synthetic", "none"}, name
        assert entry["fixtures"].strip(), name
    assert families["HWPX"]["coverage"] == "none"
    assert "NOT_SUPPORTED" in families["HWPX"]["fixtures"]
    assert families["Korean finance from OpenDART"]["coverage"] == "none"


def test_a_rendered_page_is_pinned_by_digest_and_never_described_as_a_scan() -> None:
    """`SYNTHETIC_DEGRADATION` is in the filename, the manifest and the note.

    The pages are checked by digest rather than rebuilt: FreeType rasterises
    differently between platform builds, so re-rendering them in CI would fail
    on Linux for a reason that has nothing to do with Korean text. The manifest
    says so in `byteReproducible`.
    """
    manifest = json.loads(RENDERED_MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest["byteReproducible"] is False
    degraded = [page for page in manifest["pages"] if page["kind"] == "SYNTHETIC_DEGRADATION"]
    assert degraded, "the degraded page is the whole point of the rendered family"
    for page in manifest["pages"]:
        committed = CORPUS_ROOT / str(page["path"])
        assert committed.is_file(), page["path"]
        digest = "sha256:" + hashlib.sha256(committed.read_bytes()).hexdigest()
        assert digest == page["sha256"], page["path"]
        assert page["measured"] is False
        assert page["groundTruthLines"], page["path"]
    for page in degraded:
        assert "SYNTHETIC_DEGRADATION" in page["path"]
        assert "not a scan" in page["note"].casefold()


def test_every_korean_package_carries_hangul_and_a_korean_font_name() -> None:
    """The corpus is Korean inside the package, not only in the file names.

    §28 asks for Office Korean fonts. What a native reader can see of a font is
    the name on the run, so that is what is asserted — inside the part, because
    an OOXML package is a deflated ZIP and the string is not in the raw bytes.
    No font binary is embedded in any of these files.
    """
    manifest = json.loads(EXPECTED_PATH.read_text(encoding="utf-8"))
    for entry in manifest["files"]:
        assert any(
            "가" <= character <= "힯"
            for row in entry["rows"]
            for character in json.dumps(row, ensure_ascii=False)
        ), entry["path"]
        if entry["format"] not in {"docx", "pptx"}:
            continue
        with zipfile.ZipFile(CORPUS_ROOT / str(entry["path"])) as archive:
            parts = [
                archive.read(name)
                for name in archive.namelist()
                if name.endswith(".xml") and not name.startswith("_rels/")
            ]
            assert not [
                name for name in archive.namelist() if name.endswith((".ttf", ".otf", ".fntdata"))
            ], f"{entry['path']} embeds a font binary"
        assert any(KOREAN_FONT.encode("utf-8") in part for part in parts), entry["path"]
