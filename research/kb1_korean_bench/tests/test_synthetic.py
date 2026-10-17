"""Tests for the SYNTHETIC KB1 KS fixture generator (design §4 KS, §5.7, §5.11).

The committed outputs under ``synthetic/out`` are checked without Pillow: manifest
hashes, gold-versus-generator strings, feature coverage, fictional names, fonts.
Only the tests that render import Pillow (``pytest.importorskip``). Every page and
font blob built here is SYNTHETIC test data; no number in this file is a measured
result.
"""

from __future__ import annotations

import dataclasses
import json
import shutil
import struct
import sys
import unicodedata
from pathlib import Path
from typing import Any

import pytest

from research.kb1_korean_bench import harness
from research.kb1_korean_bench.synthetic import generate as gen

OUT = Path(gen.__file__).resolve().parent / "out"
W, H = gen.PAGE_W, gen.PAGE_H
# Real organisations a careless fixture might name; none may appear (design §5.3 M7).
REAL_NAMES = (
    "대한민국",
    "법제처",
    "대법원",
    "헌법재판소",
    "국세청",
    "특허청",
    "서울특별시",
    "지방법원",
    "고등법원",
    "삼성",
    "현대",
    "네이버",
    "카카오",
)


def _gold() -> dict[str, Any]:
    data: dict[str, Any] = json.loads((OUT / gen.GOLD_NAME).read_text(encoding="utf-8"))
    return data


def _manifest() -> dict[str, Any]:
    data: dict[str, Any] = json.loads((OUT / gen.MANIFEST_NAME).read_text(encoding="utf-8"))
    return data


def _all_text(gold: dict[str, Any]) -> str:
    return "\n".join(page["text"] for page in gold["pages"])


# ------------------------------------------------------------- committed outputs


def test_committed_outputs_match_their_manifest() -> None:
    manifest = gen.verify_manifest(OUT)
    assert manifest["synthetic"] is True and manifest["publishable"] is False
    assert all(gen.LABEL in name for name in (*manifest["files"], gen.MANIFEST_NAME))
    total = sum(record["bytes"] for record in manifest["files"].values())
    assert total < 5_000_000


def test_committed_outputs_come_from_this_generator_and_these_fonts() -> None:
    manifest = _manifest()
    assert manifest["generator"] == {
        "path": gen.GENERATOR_PATH,
        "sha256_lf": gen.generator_sha256(),
    }, "generate.py changed after the outputs were rendered; re-run it with py -3.13"
    assert manifest["seed"] == _gold()["seed"] == gen.DEFAULT_SEED
    assert set(manifest["environment"]) >= {"python", "pillow", "freetype2", "zlib", "libjpeg"}
    # The interpreter by name only: a local path carries the builder's user name.
    assert not set("/\\:") & set(manifest["environment"]["python_executable"])
    for font in manifest["fonts"]:
        assert Path(font["path"]) in gen.ALLOWED_FONTS
        assert "malgun" not in font["path"].lower()
        assert gen.OFL_MARK in font["licence_name_id_13"]
        assert len(font["sha256"]) == 64


def test_gold_is_harness_gold_and_labelled_synthetic() -> None:
    gold = _gold()
    assert gen.GOLD_SCHEMA == harness.GOLD_SCHEMA
    assert gold["label"] == gen.LABEL and gold["synthetic"] is True
    pages = harness.parse_gold(gold)
    assert [page.page_id for page in pages] == [spec.page_id for spec in gen.PAGES]
    files = _manifest()["files"]
    for page in gold["pages"]:
        assert page["category"] == "KS" and page["synthetic"] is True
        for key in ("page_id", "family_id", "image", "pdf"):
            assert gen.LABEL in page[key]
        assert page["image_sha256"] == files[page["image"]]["sha256"]
        assert page["text"].startswith(gen.BANNER)


def test_gold_text_is_the_generators_own_strings() -> None:
    """Gold equals the spec strings, so it was written at render time, not read back."""
    for spec, page in zip(gen.PAGES, _gold()["pages"], strict=True):
        blocks = gen.gold_blocks(spec)
        flat = [line for block in blocks for line in block]
        assert page["text"] == "\n".join(flat)
        assert page["blocks"] == ["\n".join(block) for block in blocks]
        assert [line["text"] for line in page["lines"]] == flat
        assert unicodedata.normalize("NFC", page["text"]) == page["text"]
        for line in page["lines"]:
            assert line["provenance"] in {gen.SELF, gen.ART7}
            assert line["provenance"] == gen.SELF or spec.slug == "p01-statute-table"


def test_fixtures_cover_tables_vertical_hanja_symbols_and_seal() -> None:
    gold = _gold()
    cells = [cell for page in gold["pages"] for table in page["tables"] for cell in table["cells"]]
    assert any(cell["rowspan"] > 1 for cell in cells)
    assert any(cell["colspan"] > 1 for cell in cells)
    for page in gold["pages"]:
        for table in page["tables"]:
            assert table["html"].count("<td") == len(table["cells"])
            start, end = table["text_span"]
            assert page["text"][start:end].split("\n")[0] == table["cells"][0]["text"]

    columns = [
        line
        for page in gold["pages"]
        for line in page["lines"]
        if line["writing_mode"] == "vertical-rl"
    ]
    assert len(columns) >= 2
    assert all(b[3] - b[1] > 3 * (b[2] - b[0]) for b in (line["bbox"] for line in columns))
    xs = [line["bbox"][0] for line in columns]
    assert xs == sorted(xs, reverse=True), "vertical columns are read right to left"

    text = _all_text(gold)
    assert sum(harness.is_hanja(char) for char in text) >= 30
    one_dot_leader = chr(0x2024)  # the font draws it as .notdef; the generator refuses it
    assert harness.M6_SYMBOLS - {one_dot_leader} <= set(text)
    assert one_dot_leader not in text

    sealed = [page for page in gold["pages"] if page["seal"]]
    assert len(sealed) == 1
    seal = sealed[0]["seal"]
    assert seal["text"] == gen.SEAL_TEXT == "견본" and seal["fictional"] is True
    assert seal["occluded_spans"]
    assert sealed[0]["approval_box"] is True


def test_boxes_stay_on_the_page_and_inside_their_cells() -> None:
    def inside(box: list[int], frame: list[int]) -> bool:
        return frame[0] <= box[0] < box[2] <= frame[2] and frame[1] <= box[1] < box[3] <= frame[3]

    page_frame = [0, 0, W, H]
    for page in _gold()["pages"]:
        assert all(inside(line["bbox"], page_frame) for line in page["lines"])
        if page["seal"]:
            assert inside(page["seal"]["bbox"], page_frame)
        for table in page["tables"]:
            assert inside(table["bbox"], page_frame)
            for cell in table["cells"]:
                assert inside(cell["bbox"], table["bbox"])
                if cell["text"]:
                    assert inside(cell["text_bbox"], cell["bbox"])


def test_no_real_institution_or_seal() -> None:
    text = _all_text(_gold()) + (OUT / gen.MANIFEST_NAME).read_text(encoding="utf-8")
    assert [name for name in REAL_NAMES if name in text] == []
    for name in gen.FICTIONAL_NAMES:
        assert "가상" in name or "견본" in name
        assert name in text


# ------------------------------------------------------------- harness wiring


def _perfect_run(gold: dict[str, Any]) -> dict[str, Any]:
    caps = {"blocks": True, "table_structure": False, "region_bbox": True, "approval_box": True}
    rows = [
        {
            "page_id": page["page_id"],
            "status": "SUCCESS",
            "text": page["text"],
            "blocks": page["blocks"],
            "regions": [{"text": line["text"], "bbox": line["bbox"]} for line in page["lines"]],
            "approval_box_detected": page["approval_box"],
        }
        for page in gold["pages"]
    ]
    return {
        "schema": harness.RUN_SCHEMA,
        "arm": {"arm_id": "SYNTHETIC-echo", "capabilities": caps},
        "pages": rows,
    }


def test_harness_scores_an_echo_of_the_gold_as_zero_error() -> None:
    gold = _gold()
    ks = harness.score(gold, _perfect_run(gold), resamples=50)["categories"]["KS"]
    assert ks["publication_status"] == "SYNTHETIC_NOT_PUBLISHABLE"
    assert ks["metrics"]["M1"]["micro_cer"]["value"] == 0
    assert ks["metrics"]["M7"]["occluded_cer"]["value"] == 0


def test_harness_sees_a_dropped_character_under_the_stamp() -> None:
    gold = _gold()
    run = _perfect_run(gold)
    page = next(page for page in gold["pages"] if page["seal"])
    start = page["seal"]["occluded_spans"][-1][0]
    row = next(row for row in run["pages"] if row["page_id"] == page["page_id"])
    row["text"] = page["text"][:start] + page["text"][start + 1 :]
    occluded = harness.score(gold, run, resamples=50)["categories"]["KS"]["metrics"]["M7"]
    assert occluded["occluded_cer"]["numerator"] == 1


# ----------------------------------------------------------------- failure paths


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        (unicodedata.normalize("NFD", "한글"), "not NFC"),
        ("가" + chr(0xE000), "Private Use Area"),
        ("가" + chr(0xF900), "compatibility ideograph"),
        ("가\x07", "control character"),
        ("   ", "empty"),
    ],
)
def test_check_text_refuses_what_gold_cannot_mirror(text: str, reason: str) -> None:
    with pytest.raises(gen.FixtureError, match=reason):
        gen.check_text(text, "SYNTHETIC-case")


def _table_page(*cells: gen.Cell, rows: int = 1, cols: int = 2) -> gen.PageSpec:
    table = gen.TableBlock((100,) * cols, (40,) * rows, cells)
    return gen.PageSpec("SYNTHETIC-grid", (), (table,))


@pytest.mark.parametrize(
    ("page", "reason"),
    [
        (_table_page(gen.Cell(0, 0, "가", colspan=2), gen.Cell(0, 1, "나")), "overlap"),
        (_table_page(gen.Cell(0, 0, "가")), "have no cell"),
        (_table_page(gen.Cell(0, 0, "가", colspan=3)), "leaves"),
        (dataclasses.replace(gen.PAGES[3], seal_over="없는 줄"), "exactly one line"),
    ],
)
def test_validate_pages_refuses_broken_specs(page: gen.PageSpec, reason: str) -> None:
    with pytest.raises(gen.FixtureError, match=reason):
        gen.validate_pages([page])


def test_validate_pages_refuses_duplicate_ids() -> None:
    with pytest.raises(gen.FixtureError, match="duplicate"):
        gen.validate_pages([gen.PAGES[0], gen.PAGES[0]])


def _sfnt(licence: str | None, tag: bytes = b"name") -> bytes:
    """A minimal SYNTHETIC sfnt holding one name table (no glyphs)."""
    text = (licence or "").encode("utf-16-be")
    records = [] if licence is None else [struct.pack(">6H", 3, 1, 0x409, 13, len(text), 0)]
    name = struct.pack(">3H", 0, len(records), 6 + 12 * len(records)) + b"".join(records) + text
    header = struct.pack(">I4H", 0x00010000, 1, 16, 0, 0)
    return header + struct.pack(">4sIII", tag, 0, 28, len(name)) + name


def test_require_ofl_reads_the_licence_from_the_font() -> None:
    licence = "This Font Software is licensed under the SIL Open Font License, Version 1.1."
    assert gen.require_ofl(_sfnt(licence)) == licence


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        (_sfnt("Proprietary. All rights reserved."), "does not name"),
        (_sfnt(None), "no licence description"),
        (_sfnt("x", tag=b"head"), "no name table"),
        (_sfnt("SIL Open Font License")[:20], "unreadable"),
    ],
)
def test_require_ofl_refuses_fonts_that_do_not_say_ofl(data: bytes, reason: str) -> None:
    with pytest.raises(gen.FixtureError, match=reason):
        gen.require_ofl(data)


@pytest.mark.parametrize("name", ["malgun.ttf", "malgunbd.ttf", "NanumGothic.ttf"])
def test_check_font_refuses_fonts_off_the_allowlist(name: str) -> None:
    with pytest.raises(gen.FixtureError, match="allowlist"):
        gen.check_font(Path(r"C:\Windows\Fonts") / name)


def test_nanum_gothic_on_this_machine_does_not_name_ofl() -> None:
    nanum = Path(r"C:\Windows\Fonts\NanumGothic.ttf")
    if not nanum.is_file():
        pytest.skip("NanumGothic.ttf is not on this machine")
    with pytest.raises(gen.FixtureError, match="does not name"):
        gen.require_ofl(nanum.read_bytes())


@pytest.mark.parametrize("damage", ["flip", "stray", "missing"])
def test_verify_manifest_catches_tampering(tmp_path: Path, damage: str) -> None:
    copy = tmp_path / "out"
    shutil.copytree(OUT, copy)
    if damage == "flip":
        target = copy / gen.PAGES[0].page_id
        target = target.with_suffix(".png")
        data = bytearray(target.read_bytes())
        data[-20] ^= 0xFF
        target.write_bytes(bytes(data))
        reason = "differs"
    elif damage == "stray":
        (copy / "SYNTHETIC-extra.png").write_bytes(b"SYNTHETIC")
        reason = "unlisted"
    else:
        (copy / gen.GOLD_NAME).unlink()
        reason = "missing"
    with pytest.raises(gen.FixtureError, match=reason):
        gen.verify_manifest(copy)


def test_generate_without_pillow_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("PIL", "PIL.Image", "PIL.ImageDraw", "PIL.ImageFont", "PIL.features"):
        monkeypatch.setitem(sys.modules, name, None)
    with pytest.raises(gen.RenderUnavailable, match="nothing was written"):
        gen.generate(tmp_path / "out")
    assert not (tmp_path / "out").exists()


# ---------------------------------------------------------------- render (Pillow)


def _render_env() -> Any:
    pil = pytest.importorskip("PIL")
    if not gen.NOTO_SANS_KR.is_file():
        pytest.skip(f"{gen.NOTO_SANS_KR} is not on this machine")
    return pil


def test_regeneration_is_byte_identical(tmp_path: Path) -> None:
    _render_env()
    first = gen.generate(tmp_path / "a")
    second = gen.generate(tmp_path / "b")
    assert (tmp_path / "a" / gen.MANIFEST_NAME).read_bytes() == (
        tmp_path / "b" / gen.MANIFEST_NAME
    ).read_bytes()
    assert first == second
    committed = _manifest()
    # The interpreter does not change the bytes (3.12.13 and 3.13.0 rendered the same
    # files); the rasteriser, the codecs, the font and the generator do.
    libraries = ("pillow", "freetype2", "zlib", "libjpeg")
    same_renderer = (
        all(first["environment"][key] == committed["environment"][key] for key in libraries)
        and first["fonts"] == committed["fonts"]
        and first["generator"] == committed["generator"]
    )
    if not same_renderer:
        pytest.skip("Pillow, FreeType, zlib, libjpeg or the font differs from the manifest")
    assert first["files"] == committed["files"]


def test_the_seed_only_moves_the_stamp(tmp_path: Path) -> None:
    _render_env()
    base = gen.generate(tmp_path / "a")["files"]
    moved = gen.generate(tmp_path / "b", seed=gen.DEFAULT_SEED + 1)["files"]
    changed = sorted(name for name in base if base[name] != moved[name])
    stamped = f"{gen.PAGES[3].page_id}.png"
    assert changed == sorted([stamped, gen.PDF_NAME, gen.GOLD_NAME])


def test_a_glyph_the_font_lacks_stops_the_render() -> None:
    _render_env()
    pil = gen._pil()
    font = pil.font.truetype(str(gen.NOTO_SANS_KR), 32)
    gen.require_glyphs(pil, font, {"가", "漢", "①"})
    with pytest.raises(gen.FixtureError, match="U\\+1200"):
        gen.require_glyphs(pil, font, {"가", chr(0x1200)})
