"""The Korean hard set (program §28), built deterministically from literals.

Every Office file here is **real**: a genuine DOCX / PPTX / XLSX package, with
Hangul text, Korean font names on the runs, and Korean finance conventions —
`원`, `억`, `％`, `2026-01-31`, and a negative shown as `(1,234)` rather than
`-1234`. Nothing is a screenshot of a document and nothing is a stub.

**What this set does not contain, stated first.** §28 lists nine families and
this builder covers four of them with real files. The rest are named in
``README.md`` with the reason, because a Korean corpus that quietly omits the
hard classes would read as coverage it does not have:

* *scanned Korean* and *screenshots / photos* — one page is rendered from the
  clean-Hangul text and then degraded (rotation, blur, noise) by
  :func:`_rendered_pages`. It is labelled ``SYNTHETIC_DEGRADATION`` in the
  manifest and in every filename. **It is not a scan.** A real scan carries
  paper texture, a real camera's optics and a real printer's halftone; none of
  those is simulated here, and no OCR result is measured against it in this lane.
* *HWPX* — `NOT_SUPPORTED`, zero code. See ``README.md``.
* *Korean finance from OpenDART* — not here: real filings need authorised
  credentials (program §15). These tables are written by hand in the style of a
  filing, and are not filings.

**Fonts.** The runs name `맑은 고딕` / `Malgun Gothic`, which is what an Office
file authored in Korea carries. No font binary is embedded in any package: a
native reader reads characters, not glyphs, so the font name is the fact under
test. The rendered pages use `apps/web/public/fonts/wanted-sans-ko-400.woff2`,
which is already in this repository under the SIL Open Font License — no
proprietary font is read, rendered or committed.

**Determinism.** The package plumbing is imported from the Office corpus builder
rather than re-derived, so the two corpora are byte-stable by exactly the same
mechanism: fixed ZIP timestamps, fixed core properties, sorted member order.

Run: ``python research/korean_hard_set_20260908/build_korean_hard_set.py``
"""

from __future__ import annotations

import hashlib
import io
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from openpyxl.comments import Comment  # noqa: E402 - the path bootstrap above must run first
from openpyxl.workbook.defined_name import DefinedName  # noqa: E402
from PIL import Image, ImageDraw, ImageFilter, ImageFont  # noqa: E402

from tests.fixtures.office_corpus.build_office_corpus import (  # noqa: E402
    EXPECTED_SCHEMA,
    _blank_slide,
    _document,
    _grid_cells,
    _grid_range,
    _library_versions,
    _presentation,
    _row,
    _save_docx,
    _save_pptx,
    _save_xlsx,
    _textbox,
    _workbook,
    _write_grid,
)

CORPUS_ROOT = Path(__file__).resolve().parent
EXPECTED_PATH = CORPUS_ROOT / "expected.json"
RENDERED_MANIFEST_PATH = CORPUS_ROOT / "rendered" / "MANIFEST.json"
FORMATS = ("xlsx", "docx", "pptx")

#: The font an Office file authored in Korea names on its runs. Naming it is the
#: fact under test; no binary is embedded.
KOREAN_FONT = "맑은 고딕"
#: `#,##0원`, and a negative in parentheses — the convention a Korean finance
#: sheet uses and the one that makes the reader's `-1234` differ from the
#: workbook's `(1,234)원`.
KRW_FORMAT = '#,##0"원";(#,##0)"원"'
PERCENT_FORMAT = "0.0%;(0.0%)"

#: The OFL font already committed to this repository. Nothing proprietary is read.
RENDER_FONT = REPO_ROOT / "apps" / "web" / "public" / "fonts" / "wanted-sans-ko-400.woff2"


# --------------------------------------------------------------------------
# DOCX
# --------------------------------------------------------------------------


def _korean_runs(paragraph: Any) -> Any:
    for run in paragraph.runs:
        run.font.name = KOREAN_FONT
    return paragraph


def _docx_clean_hangul() -> tuple[bytes, list[dict[str, Any]]]:
    """Headings and paragraphs in Hangul only, with a Korean font on every run."""
    document = _document()
    lines = [
        ("2026년 1분기 경영 보고", "Heading 1"),
        ("매출은 전 분기 대비 4퍼센트 늘었습니다.", None),
        ("영업이익률은 12.4％로 집계되었습니다.", None),
        ("가. 국내 부문", "Heading 2"),
        ("수도권 매출이 전체의 절반을 넘었습니다.", None),
    ]
    for text, style in lines:
        _korean_runs(
            document.add_paragraph(text, style=style) if style else document.add_paragraph(text)
        )
    return _save_docx(document), [
        _row("docx_body_paragraphs", [text for text, _style in lines]),
    ]


def _docx_korean_english_mixed() -> tuple[bytes, list[dict[str, Any]]]:
    """One paragraph per mixing pattern a Korean business document actually uses."""
    document = _document()
    lines = [
        "TAVONEL은 조직 지식을 AI가 신뢰할 수 있는 컨텍스트로 컴파일합니다.",
        "SLA 99.9% 를 목표로 하며, RTO는 4시간입니다.",
        "담당: Kim Minjun (김민준), platform team",
        "문서 ID: DOC-2026-0131, 버전 v2.1",
    ]
    for text in lines:
        _korean_runs(document.add_paragraph(text))
    return _save_docx(document), [
        _row("docx_body_paragraphs", lines),
    ]


def _docx_finance_table() -> tuple[bytes, list[dict[str, Any]]]:
    """A filing-style table: 원 / 억 / ％, an ISO date, a negative in parentheses."""
    document = _document()
    _korean_runs(document.add_paragraph("연결 재무 요약 (2026-01-31 기준)"))
    grid = [
        ["과목", "당기", "전기", "증감률"],
        ["매출액", "1,234억 원", "1,186억 원", "4.0％"],
        ["영업이익", "153억 원", "141억 원", "8.5％"],
        ["당기순손실", "(12억 원)", "(31억 원)", "(61.3％)"],
    ]
    table = document.add_table(rows=len(grid), cols=len(grid[0]))
    for row_index, row in enumerate(grid):
        for column_index, value in enumerate(row):
            cell = table.cell(row_index, column_index)
            cell.text = value
            for paragraph in cell.paragraphs:
                _korean_runs(paragraph)
    return _save_docx(document), [
        _row("docx_body_paragraphs", ["연결 재무 요약 (2026-01-31 기준)"]),
        _row(
            "docx_table_cells",
            {
                "0": {
                    f"r/{row_index:06d}/c/{column_index:06d}": value
                    for row_index, row in enumerate(grid)
                    for column_index, value in enumerate(row)
                }
            },
        ),
    ]


# --------------------------------------------------------------------------
# XLSX
# --------------------------------------------------------------------------


def _xlsx_finance_sheet() -> tuple[bytes, list[dict[str, Any]]]:
    """Korean headers, a Hangul defined name, a Hangul note, KRW number formats."""
    grid = [
        ["과목", "당기", "전기"],
        ["매출액", 123400000000, 118600000000],
        ["영업이익", 15300000000, 14100000000],
        ["당기순손실", -1200000000, -3100000000],
    ]
    workbook = _workbook("재무요약")
    sheet = workbook["재무요약"]
    _write_grid(sheet, "A1", grid)
    for row in range(2, 5):
        for column in ("B", "C"):
            sheet[f"{column}{row}"].number_format = KRW_FORMAT
    sheet["B4"].comment = Comment("일회성 손상차손 반영.", "감사팀")
    workbook.defined_names.add(DefinedName("당기금액", attr_text="재무요약!$B$2:$B$4"))
    return _save_xlsx(workbook), [
        _row("xlsx_sheet_names", ["재무요약"]),
        _row("xlsx_cell_values", _grid_cells("재무요약", "A1", grid)),
        _row("xlsx_table_range", {"재무요약": _grid_range("A1", grid)}),
        _row("xlsx_cell_comments", {"재무요약!B4": "일회성 손상차손 반영."}),
        _row("xlsx_named_ranges", {"당기금액": "재무요약!$B$2:$B$4"}),
        _row(
            "xlsx_number_formats",
            {
                f"재무요약!{column}{row}": KRW_FORMAT
                for row in range(2, 5)
                for column in ("B", "C")
            },
        ),
    ]


def _xlsx_mixed_sheet_names() -> tuple[bytes, list[dict[str, Any]]]:
    """Korean and English sheet names, one of them hidden."""
    visible = [["항목", "Value"], ["매출 Revenue", 1234], ["비중 Share", 0.406]]
    draft = [["비고", "Note"], ["내부 검토용", "internal only"]]
    workbook = _workbook("요약 Summary")
    _write_grid(workbook["요약 Summary"], "A1", visible)
    hidden = workbook.create_sheet("초안 Draft")
    _write_grid(hidden, "A1", draft)
    hidden.sheet_state = "hidden"
    workbook["요약 Summary"]["B3"].number_format = PERCENT_FORMAT
    cells = _grid_cells("요약 Summary", "A1", visible)
    cells.update(_grid_cells("초안 Draft", "A1", draft))
    return _save_xlsx(workbook), [
        _row("xlsx_sheet_names", ["요약 Summary", "초안 Draft"]),
        _row("xlsx_cell_values", cells),
        _row("xlsx_hidden_sheets", ["초안 Draft"]),
        _row("xlsx_number_formats", {"요약 Summary!B3": PERCENT_FORMAT}),
    ]


# --------------------------------------------------------------------------
# PPTX
# --------------------------------------------------------------------------


def _pptx_clean_hangul() -> tuple[bytes, list[dict[str, Any]]]:
    presentation = _presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[1])
    slide.shapes.title.text = "2026년 1분기 검토"
    slide.placeholders[1].text_frame.text = "모든 지역에서 매출이 늘었습니다."
    for shape in (slide.shapes.title, slide.placeholders[1]):
        for paragraph in shape.text_frame.paragraphs:
            for run in paragraph.runs:
                run.font.name = KOREAN_FONT
    return _save_pptx(presentation), [
        _row(
            "pptx_slide_units",
            {"1": ["2026년 1분기 검토", "모든 지역에서 매출이 늘었습니다."]},
        ),
    ]


def _pptx_notes_mixed() -> tuple[bytes, list[dict[str, Any]]]:
    """Mixed Korean/English body text with a Korean speaker note."""
    presentation = _presentation()
    slide = _blank_slide(presentation)
    _textbox(slide.shapes, "Roadmap 로드맵 2026 H1", top=1.0)
    _textbox(slide.shapes, "P0: 커넥터 · P1: 온톨로지 · P2: MCP", top=2.2)
    slide.notes_slide.notes_text_frame.text = "지연된 두 건의 계약을 언급할 것."
    return _save_pptx(presentation), [
        _row(
            "pptx_slide_units",
            {"1": ["Roadmap 로드맵 2026 H1", "P0: 커넥터 · P1: 온톨로지 · P2: MCP"]},
        ),
        _row("pptx_speaker_notes", {"1": "지연된 두 건의 계약을 언급할 것."}),
    ]


# --------------------------------------------------------------------------
# rendered pages — SYNTHETIC_DEGRADATION, never called a scan
# --------------------------------------------------------------------------

_RENDER_LINES = (
    "2026년 1분기 경영 보고",
    "매출은 전 분기 대비 4퍼센트 늘었습니다.",
    "영업이익률은 12.4％로 집계되었습니다.",
    "가. 국내 부문",
    "수도권 매출이 전체의 절반을 넘었습니다.",
)


def _rendered_pages() -> dict[str, bytes]:
    """One clean page and one degraded copy of it.

    The degradation is a fixed skew, a fixed Gaussian blur and a fixed contrast
    reduction — a *simulation* of what a bad scan does to a page, produced by
    three PIL calls with hard-coded parameters. It is not a scan, it is not a
    photograph, and this lane measures no OCR against it. Its only purpose is to
    give the OCR lane a Korean page whose ground truth is known exactly, because
    this module wrote it.
    """
    font = ImageFont.truetype(str(RENDER_FONT), 34)
    clean = Image.new("L", (1240, 620), color=255)
    draw = ImageDraw.Draw(clean)
    for index, line in enumerate(_RENDER_LINES):
        draw.text((70, 60 + index * 80), line, font=font, fill=20)

    degraded = clean.rotate(1.4, resample=Image.BICUBIC, fillcolor=255)
    degraded = degraded.filter(ImageFilter.GaussianBlur(radius=1.1))
    degraded = Image.eval(degraded, lambda value: min(255, 40 + value * 4 // 5))

    pages: dict[str, bytes] = {}
    for name, image in (
        ("rendered/korean-page-clean.png", clean),
        ("rendered/korean-page-SYNTHETIC_DEGRADATION.png", degraded),
    ):
        buffer = io.BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        pages[name] = buffer.getvalue()
    return pages


# --------------------------------------------------------------------------
# corpus assembly
# --------------------------------------------------------------------------

CORPUS: dict[str, tuple[tuple[str, Any], ...]] = {
    "xlsx": (
        ("01-finance-sheet.xlsx", _xlsx_finance_sheet),
        ("02-mixed-sheet-names.xlsx", _xlsx_mixed_sheet_names),
    ),
    "docx": (
        ("01-clean-hangul.docx", _docx_clean_hangul),
        ("02-korean-english-mixed.docx", _docx_korean_english_mixed),
        ("03-finance-table.docx", _docx_finance_table),
    ),
    "pptx": (
        ("01-clean-hangul.pptx", _pptx_clean_hangul),
        ("02-notes-mixed.pptx", _pptx_notes_mixed),
    ),
}

#: Every §28 family, and what this set holds for it. `real` means a genuine
#: package built from literals in this file; `synthetic` means a page this file
#: drew and then damaged on purpose; `none` means nothing, said out loud.
FAMILIES: dict[str, dict[str, str]] = {
    "clean Hangul": {
        "coverage": "real",
        "fixtures": "docx/01-clean-hangul.docx, pptx/01-clean-hangul.pptx",
    },
    "Korean/English mixed": {
        "coverage": "real",
        "fixtures": (
            "docx/02-korean-english-mixed.docx, pptx/02-notes-mixed.pptx, "
            "xlsx/02-mixed-sheet-names.xlsx"
        ),
    },
    "finance": {
        "coverage": "real",
        "fixtures": "xlsx/01-finance-sheet.xlsx, docx/03-finance-table.docx",
    },
    "Office Korean fonts": {
        "coverage": "real",
        "fixtures": (
            "every docx and pptx here names 맑은 고딕 on its runs; no font binary is embedded"
        ),
    },
    "PPTX/DOCX/XLSX": {
        "coverage": "real",
        "fixtures": "all seven packages",
    },
    "scanned Korean": {
        "coverage": "synthetic",
        "fixtures": (
            "rendered/korean-page-SYNTHETIC_DEGRADATION.png — a page this builder drew and "
            "then rotated, blurred and lightened. NOT a scan; no OCR is measured against it "
            "in this lane"
        ),
    },
    "screenshots / photos": {
        "coverage": "synthetic",
        "fixtures": "the same rendered pages; no camera, no screen capture, no real device",
    },
    "HWPX": {
        "coverage": "none",
        "fixtures": "NOT_SUPPORTED — zero code in this repository; see README.md",
    },
    "Korean finance from OpenDART": {
        "coverage": "none",
        "fixtures": (
            "authorised credentials required (program §15); the tables here are written in "
            "the style of a filing and are not filings"
        ),
    },
}


def build_corpus(root: Path) -> dict[str, Any]:
    """Write every Korean fixture under ``root`` and return the expected manifest."""
    files: list[dict[str, Any]] = []
    for source_format in FORMATS:
        directory = root / source_format
        directory.mkdir(parents=True, exist_ok=True)
        for name, builder in CORPUS[source_format]:
            payload, rows = builder()
            (directory / name).write_bytes(payload)
            files.append(
                {
                    "path": f"{source_format}/{name}",
                    "format": source_format,
                    "sha256": "sha256:" + hashlib.sha256(payload).hexdigest(),
                    "rows": rows,
                }
            )
    return {
        "schemaVersion": EXPECTED_SCHEMA,
        "builder": "research/korean_hard_set_20260908/build_korean_hard_set.py",
        "libraries": _library_versions(),
        "families": FAMILIES,
        "files": files,
    }


def build_rendered(root: Path) -> dict[str, Any]:
    """Write the two rendered pages and their own manifest.

    They are deliberately **not** in ``expected.json``. Glyph rasterisation is a
    property of the FreeType build under Pillow, so the same code produces
    different bytes on Windows and on Linux; asserting those bytes in CI would
    make a portable corpus fail for a reason that has nothing to do with Korean
    text. The committed PNGs are pinned by digest here and re-rendered only when
    a person runs this builder with ``--rendered``.
    """
    pages: list[dict[str, Any]] = []
    (root / "rendered").mkdir(parents=True, exist_ok=True)
    for name, payload in _rendered_pages().items():
        (root / name).write_bytes(payload)
        pages.append(
            {
                "path": name,
                "kind": "SYNTHETIC_DEGRADATION" if "SYNTHETIC" in name else "RENDERED_SOURCE",
                "sha256": "sha256:" + hashlib.sha256(payload).hexdigest(),
                "groundTruthLines": list(_RENDER_LINES),
                "measured": False,
                "note": (
                    "drawn by this builder with an OFL font and damaged with fixed PIL "
                    "parameters. Not a scan, not a photograph. No OCR result is recorded "
                    "against it here."
                ),
            }
        )
    return {
        "schemaVersion": "tavonel.korean_rendered_pages.v1",
        "builder": "research/korean_hard_set_20260908/build_korean_hard_set.py",
        "renderer": {"pillow": _pillow_version(), "font": RENDER_FONT.name, "licence": "OFL"},
        "byteReproducible": False,
        "byteReproducibleNote": (
            "FreeType rasterises differently between platform builds, so these bytes are "
            "pinned by digest and never rebuilt in CI."
        ),
        "pages": pages,
    }


def _pillow_version() -> str:
    from importlib.metadata import version

    return version("pillow")


def write_expected(manifest: dict[str, Any], path: Path) -> None:
    path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main(argv: list[str] | None = None) -> None:
    manifest = build_corpus(CORPUS_ROOT)
    write_expected(manifest, EXPECTED_PATH)
    written = f"wrote {len(manifest['files'])} packages and {EXPECTED_PATH.name}"
    if "--rendered" in (argv if argv is not None else sys.argv[1:]):
        rendered = build_rendered(CORPUS_ROOT)
        write_expected(rendered, RENDERED_MANIFEST_PATH)
        written += f", {len(rendered['pages'])} rendered pages and {RENDERED_MANIFEST_PATH.name}"
    print(written)


if __name__ == "__main__":
    main()
