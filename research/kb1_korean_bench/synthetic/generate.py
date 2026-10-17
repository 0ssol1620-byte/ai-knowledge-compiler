"""SYNTHETIC KB1 KS fixture generator (KOREAN-BENCHMARK-DESIGN-2026-10-17 §4 KS, §5.7, §5.11).

Renders a handful of SYNTHETIC Korean pages and writes, at render time, the gold the
KB1 harness reads (``tavonel.kb1.gold.v1``) plus a sha256 manifest of every file.

* Gold is the generator's own strings and its own layout boxes. Nothing is OCR'd
  back and nothing is inferred: a line's bbox is the ink box Pillow drew it in, a
  table cell's bbox is the rectangle the generator stroked, and a seal's occluded
  span is every character whose ink box meets the stamp's pixels.
* Every file name, every JSON document and every page image says SYNTHETIC. KS is a
  harness control: never a headline and never a public number (design §4).
* Text is self-written, except the five 저작권법 제7조 items, rendered as quoted in
  ``korean-benchmark-receipts/TERMS-QUOTES-20261017.json``. That receipt quotes
  easylaw.go.kr; the wording was not checked against law.go.kr, and the page says so.
* Organisation names are fictional and carry 가상 or 견본; the stamp reads 견본.
* Fonts: a path allowlist, and the font's own name table (ID 13) must name the SIL
  Open Font License. NanumGothic.ttf on the build machine carries "NHN Corporation"
  there, so it is not used; malgun is never on the list.
* A character the font cannot draw (renders as .notdef or blank) stops the run before
  anything is written: gold must not claim a glyph the image lacks.
* Same seed, interpreter, Pillow/FreeType/zlib/libjpeg and font bytes give
  byte-identical files. The seed only moves and turns the stamp.

Run: ``py -3.13 research/kb1_korean_bench/synthetic/generate.py [--seed N] [--out DIR]``.
Pillow is needed to render; the stdlib-only parts (specs, licence check, manifest
verification) import without it.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import importlib
import io
import json
import math
import struct
import sys
import time
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LABEL = "SYNTHETIC"
DATASET_REVISION = "kb1-ks-synthetic-r1"
GOLD_SCHEMA = "tavonel.kb1.gold.v1"  # harness.GOLD_SCHEMA (a test pins the two together)
MANIFEST_SCHEMA = "tavonel.kb1.synthetic_manifest.v1"
GENERATOR_PATH = "research/kb1_korean_bench/synthetic/generate.py"
DEFAULT_SEED = 20261017

DPI = 150
PAGE_W, PAGE_H = 1240, 1754  # A4 at 150 dpi
MARGIN = 110
INK = (0, 0, 0)
SEAL_RGBA = (200, 30, 30, 205)
GOLD_NAME = f"{LABEL}-KS-gold.json"
MANIFEST_NAME = f"{LABEL}-KS-manifest.sha256.json"
PDF_NAME = f"{LABEL}-KS-pages.pdf"
PDF_DATE = time.strptime("2026-10-17", "%Y-%m-%d")  # fixed, so the PDF is reproducible

NOTO_SANS_KR = Path(r"C:\Windows\Fonts\NotoSansKR-VF.ttf")
ALLOWED_FONTS = (NOTO_SANS_KR,)
FONT_WEIGHT = 400  # the variable font's default instance is Thin (100)
OFL_MARK = "SIL Open Font License"
NOTDEF_PROBE = "\U0010fffd"  # no font here maps it, so it draws .notdef

SELF = "self-written for KB1 KS"
ART7 = (
    "저작권법 제7조 item wording as quoted from easylaw.go.kr in korean-benchmark-receipts/"
    "TERMS-QUOTES-20261017.json (sha256 "
    "2f29a94901aa959261978be79c50a945deedf8983851fe81d24c62240acb5e7e);"
    " not checked against law.go.kr"
)
FICTIONAL_NAMES = ("가상기관 견본청", "㈜가상견본상사")
SEAL_TEXT = "견본"
BANNER = "SYNTHETIC · KB1 KS 합성 대조군 · 실제 문서 아님"


class FixtureError(ValueError):
    """A spec, font or render breaks the KS contract; nothing is written."""


class RenderUnavailable(RuntimeError):
    """Pillow is missing; nothing is rendered and nothing is written."""


# ------------------------------------------------------------------------- specs


@dataclass(frozen=True)
class TextBlock:
    lines: tuple[tuple[str, int], ...]  # (text, indent px)
    size: int = 24
    provenance: str = SELF


@dataclass(frozen=True)
class Cell:
    row: int
    col: int
    text: str
    rowspan: int = 1
    colspan: int = 1


@dataclass(frozen=True)
class TableBlock:
    col_widths: tuple[int, ...]
    row_heights: tuple[int, ...]
    cells: tuple[Cell, ...]
    size: int = 22
    role: str = "table"  # or "approval_box" (결재란)
    provenance: str = SELF


@dataclass(frozen=True)
class VerticalBlock:
    columns: tuple[str, ...]  # reading order: rightmost column first, each top to bottom
    size: int = 36
    provenance: str = SELF


Block = TextBlock | TableBlock | VerticalBlock


@dataclass(frozen=True)
class PageSpec:
    slug: str
    features: tuple[str, ...]
    blocks: tuple[Block, ...]
    seal_over: str | None = None  # the line the 견본 stamp is pressed onto

    @property
    def page_id(self) -> str:
        return f"{LABEL}-KS-{self.slug}"


def _text(*lines: str | tuple[str, int], size: int = 24, provenance: str = SELF) -> TextBlock:
    return TextBlock(
        tuple((line, 0) if isinstance(line, str) else line for line in lines), size, provenance
    )


_BANNER = _text(BANNER, size=22)
# Look-alike punctuation goes through chr() so ruff's RUF001 stays meaningful:
# tortoise-shell brackets U+3014/U+3015 and hangul araea U+318D. U+2024 (one-dot leader)
# is absent: Noto Sans KR draws it as .notdef, and require_glyphs refuses it.
_TL, _TR, _ARAEA = map(chr, (0x3014, 0x3015, 0x318D))

PAGES: tuple[PageSpec, ...] = (
    PageSpec(
        "p01-statute-table",
        ("statute_text", "merged_cell_table", "korean_numerics"),
        (
            _BANNER,
            _text("저작권법 제7조 각 호 (인용, 공식 원문과 대조 전)", size=30),
            _text(
                "1. 헌법·법률·조약·명령·조례 및 규칙",
                "2. 국가 또는 지방자치단체의 고시·공고·훈령 그 밖에 이와 유사한 것",
                "3. 법원의 판결·결정·명령 및 심판이나 행정심판절차 그 밖에",
                ("이와 유사한 절차에 따른 의결·결정 등", 34),
                "4. 국가 또는 지방자치단체가 작성한 것으로서 위에 규정된 것의",
                ("편집물 또는 번역물", 34),
                "5. 사실의 전달에 불과한 시사보도",
                provenance=ART7,
            ),
            _text("표 1. 가상 수치로 만든 병합 셀 표 (직접 작성)"),
            TableBlock(
                col_widths=(170, 200, 300, 300),
                row_heights=(60, 60, 60, 60, 60, 60),
                cells=(
                    Cell(0, 0, "구분", rowspan=2, colspan=2),
                    Cell(0, 2, "연도별 금액", colspan=2),
                    Cell(1, 2, "2025년"),
                    Cell(1, 3, "2026년"),
                    Cell(2, 0, "수입", rowspan=2),
                    Cell(2, 1, "사용료"),
                    Cell(2, 2, "1,234,000원"),
                    Cell(2, 3, "1,500,000원"),
                    Cell(3, 1, "수수료"),
                    Cell(3, 2, "30,000원"),
                    Cell(3, 3, "35,000원"),
                    Cell(4, 0, "합계", colspan=2),
                    Cell(4, 2, "1,264,000원"),
                    Cell(4, 3, "1,535,000원"),
                    Cell(
                        5,
                        0,
                        "비고: 2026. 10. 17. 기준 가상 수치, 전년 대비 10% 이상 증가",
                        colspan=4,
                    ),
                ),
            ),
        ),
    ),
    PageSpec(
        "p02-vertical-hanja",
        ("vertical_writing", "hanja", "reading_order"),
        (
            _BANNER,
            _text("세로쓰기·국한문 혼용 시험 (직접 작성)", size=30),
            VerticalBlock(
                (
                    "本 文書는 試驗用 見本이다",
                    "세로쓰기는 오른쪽 줄부터 읽는다",
                    "各 줄은 위에서 아래로 읽는다",
                    "漢字와 한글을 섞어 쓴다",
                    "合成 對照群은 公開 數値가 아니다",
                )
            ),
            _text(
                "읽기 순서: 오른쪽 열에서 왼쪽 열로, 각 열은 위에서 아래로.",
                "본 시험(試驗)은 한자(漢字) 판독(判讀)을 확인(確認)한다.",
                "法令 用語: 條約·命令·條例 및 規則",
            ),
        ),
    ),
    PageSpec(
        "p03-symbols",
        ("special_characters", "hanja", "korean_numerics"),
        (
            _BANNER,
            _text("특수문자 시험 (직접 작성)", size=30),
            _text(
                "".join(chr(cp) for cp in range(0x2460, 0x2474)),
                "※ 참고 표시는 줄의 맨 앞에 온다.",
                f"「홑낫표」와 『겹낫표』, {_TL}거북 괄호{_TR}를 함께 쓴다.",
                "㈜가상견본상사는 실재하지 않는 회사다.",
                "가·나·다 라 ○ 마 □ 바",
                f"헌법{_ARAEA}법률{_ARAEA}조약 (아래아 가운뎃점)",
                "가상 예시: 제7조 제1항 제2호, 2026. 10. 17., 3억 5천만원, 10%가 적용된다.",
            ),
        ),
    ),
    PageSpec(
        "p04-seal-approval",
        ("seal_overlay", "approval_box", "fictional_institution"),
        (
            _BANNER,
            _text("가상기관 견본청 공고 제2026-1호", size=30),
            _text(
                "이 문서는 KB1 합성 대조군을 위해 직접 작성한 가상 공고문이다.",
                "실제 기관, 실제 직인, 실제 사건과 관계가 없다.",
                "직인 아래에 가려진 글자도 정답에는 그대로 남는다.",
            ),
            TableBlock(
                col_widths=(140, 140, 140),
                row_heights=(50, 110),
                cells=(
                    Cell(0, 0, "담당"),
                    Cell(0, 1, "검토"),
                    Cell(0, 2, "승인"),
                    Cell(1, 0, ""),
                    Cell(1, 1, ""),
                    Cell(1, 2, ""),
                ),
                role="approval_box",
            ),
            _text("2026. 10. 17.", "가상기관 견본청장", size=28),
        ),
        seal_over="가상기관 견본청장",
    ),
)


def check_text(text: str, where: str) -> str:
    """Gold must equal what was drawn: NFC, no PUA, no compatibility ideograph, no control."""
    if not text.strip():
        raise FixtureError(f"{where}: empty text")
    for char in text:
        cp = ord(char)
        if 0xE000 <= cp <= 0xF8FF or cp >= 0xF0000:
            raise FixtureError(f"{where}: Private Use Area code point U+{cp:04X}")
        if 0xF900 <= cp <= 0xFAFF:
            raise FixtureError(f"{where}: compatibility ideograph U+{cp:04X} (NFC folds it)")
        if unicodedata.category(char) == "Cc":
            raise FixtureError(f"{where}: control character U+{cp:04X}")
    if unicodedata.normalize("NFC", text) != text:
        raise FixtureError(f"{where}: text is not NFC")
    return text


def _check_grid(table: TableBlock, where: str) -> None:
    rows, cols = len(table.row_heights), len(table.col_widths)
    owner: dict[tuple[int, int], Cell] = {}
    for cell in table.cells:
        if cell.rowspan < 1 or cell.colspan < 1:
            raise FixtureError(f"{where}: cell {cell} has a span below 1")
        for r in range(cell.row, cell.row + cell.rowspan):
            for c in range(cell.col, cell.col + cell.colspan):
                if not (0 <= r < rows and 0 <= c < cols):
                    raise FixtureError(f"{where}: cell {cell} leaves the {rows}x{cols} grid")
                if (r, c) in owner:
                    raise FixtureError(f"{where}: cells {owner[r, c]} and {cell} overlap")
                owner[r, c] = cell
    if len(owner) != rows * cols:
        gaps = sorted({(r, c) for r in range(rows) for c in range(cols)} - set(owner))
        raise FixtureError(f"{where}: grid slots {gaps} have no cell")


def gold_blocks(page: PageSpec) -> list[list[str]]:
    """Gold blocks in reading order, each a list of its line texts.

    A table is one block read row-major (empty cells carry no line); a vertical block
    gives one block per column, right to left, so reading order is measurable (M5).
    """
    blocks: list[list[str]] = []
    for block in page.blocks:
        if isinstance(block, TextBlock):
            blocks.append([text for text, _ in block.lines])
        elif isinstance(block, TableBlock):
            cells = sorted(block.cells, key=lambda cell: (cell.row, cell.col))
            blocks.append([cell.text for cell in cells if cell.text])
        else:
            blocks.extend([column] for column in block.columns)
    return blocks


def validate_pages(pages: Sequence[PageSpec]) -> None:
    seen: set[str] = set()
    for page in pages:
        if page.page_id in seen:
            raise FixtureError(f"duplicate page id {page.page_id}")
        seen.add(page.page_id)
        for block in page.blocks:
            if isinstance(block, TableBlock):
                _check_grid(block, page.page_id)
                for cell in block.cells:
                    if cell.text:
                        check_text(cell.text, page.page_id)
        lines = [line for block in gold_blocks(page) for line in block]
        for line in lines:
            check_text(line, page.page_id)
        if page.seal_over is not None and lines.count(page.seal_over) != 1:
            raise FixtureError(f"{page.page_id}: seal_over must name exactly one line")


# ------------------------------------------------------------------------- fonts


def require_ofl(data: bytes) -> str:
    """Licence description (name ID 13, Windows, en-US) of an sfnt font; it must name OFL."""
    try:
        num_tables = struct.unpack_from(">H", data, 4)[0]
        for index in range(num_tables):
            tag, _, offset, _ = struct.unpack_from(">4sIII", data, 12 + 16 * index)
            if tag == b"name":
                break
        else:
            raise FixtureError("font has no name table; its licence is unknown")
        _, count, strings = struct.unpack_from(">HHH", data, offset)
        licence = None
        for index in range(count):
            platform, _, language, name_id, length, at = struct.unpack_from(
                ">6H", data, offset + 6 + 12 * index
            )
            if name_id == 13 and platform == 3 and language == 0x409:
                start = offset + strings + at
                licence = data[start : start + length].decode("utf-16-be")
                break
    except (struct.error, UnicodeDecodeError) as exc:
        raise FixtureError(f"font name table is unreadable: {exc}") from exc
    if licence is None:
        raise FixtureError("font name table has no licence description (name ID 13)")
    if OFL_MARK not in licence:
        raise FixtureError(f"font licence does not name the {OFL_MARK}: {licence[:80]!r}")
    return licence


def check_font(path: Path) -> dict[str, Any]:
    if path not in ALLOWED_FONTS:
        raise FixtureError(f"font {path} is not on the allowlist {[str(p) for p in ALLOWED_FONTS]}")
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise FixtureError(f"font {path} is not readable: {exc}") from exc
    return {
        "path": str(path),
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "licence_name_id_13": require_ofl(data),
        "variation": {"wght": FONT_WEIGHT},
    }


# ------------------------------------------------------------------------ render


@dataclass(frozen=True)
class _Pil:
    image: Any
    draw: Any
    font: Any
    features: Any
    version: str


def _pil() -> _Pil:
    try:
        image, draw, font, features = (
            importlib.import_module(f"PIL.{name}")
            for name in ("Image", "ImageDraw", "ImageFont", "features")
        )
        version = importlib.import_module("PIL").__version__
    except ImportError as exc:
        raise RenderUnavailable(
            "Pillow is required to render KS fixtures (run with py -3.13); nothing was written"
        ) from exc
    return _Pil(image, draw, font, features, version)


Box = tuple[int, int, int, int]


def _box(raw: Sequence[float]) -> Box:
    x0, y0, x1, y1 = raw
    return (math.floor(x0), math.floor(y0), math.ceil(x1), math.ceil(y1))


def _union(boxes: Sequence[Box | None]) -> Box:
    ink = [box for box in boxes if box is not None]
    return (
        min(b[0] for b in ink),
        min(b[1] for b in ink),
        max(b[2] for b in ink),
        max(b[3] for b in ink),
    )


def require_glyphs(pil: _Pil, font: Any, chars: set[str]) -> None:
    """Refuse any character the font draws as .notdef or as nothing."""

    def ink(char: str) -> bytes:
        size = font.size
        image = pil.image.new("L", (size * 3, size * 3), 0)
        pil.draw.Draw(image).text((size, size), char, fill=255, font=font)
        return bytes(image.tobytes())

    notdef = ink(NOTDEF_PROBE)
    missing = sorted(
        f"U+{ord(c):04X}"
        for c in chars
        if not c.isspace() and (not any(drawn := ink(c)) or drawn == notdef)
    )
    if missing:
        raise FixtureError(f"font cannot draw {missing}; gold would claim glyphs the image lacks")


def _unit(seed: int, key: str) -> float:
    """Deterministic value in [0, 1) from the seed (stamp jitter only)."""
    digest = hashlib.sha256(f"{seed}:{key}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


@dataclass
class _Line:
    text: str
    chars: list[Box | None]
    provenance: str
    writing_mode: str

    @property
    def bbox(self) -> Box:
        return _union(self.chars)


def _check_inside(box: Box, frame: Box, what: str) -> None:
    if not (
        frame[0] <= box[0] and frame[1] <= box[1] and box[2] <= frame[2] and box[3] <= frame[3]
    ):
        raise FixtureError(f"{what} {box} overflows {frame}; fix the spec instead of clipping")


class _Canvas:
    def __init__(self, pil: _Pil, font_for: Callable[[int], Any]) -> None:
        self.pil = pil
        self.font_for = font_for
        self.image = pil.image.new("RGB", (PAGE_W, PAGE_H), "white")
        self.draw = pil.draw.Draw(self.image)
        self.lines: list[_Line] = []

    def _char(self, char: str, x: float, y: float, font: Any) -> Box | None:
        if char.isspace():
            return None
        self.draw.text((x, y), char, fill=INK, font=font)
        return _box(self.draw.textbbox((x, y), char, font=font))

    def hline(self, text: str, x: float, y: float, size: int, provenance: str) -> _Line:
        font = self.font_for(size)
        boxes = []
        for char in text:
            boxes.append(self._char(char, x, y, font))
            x += font.getlength(char)
        line = _Line(text, boxes, provenance, "horizontal-tb")
        _check_inside(line.bbox, (MARGIN, MARGIN, PAGE_W - MARGIN, PAGE_H - MARGIN), "line")
        self.lines.append(line)
        return line

    def vline(self, text: str, center_x: float, y: float, size: int, provenance: str) -> _Line:
        font = self.font_for(size)
        boxes = []
        for char in text:
            boxes.append(self._char(char, center_x - font.getlength(char) / 2, y, font))
            y += size * (0.5 if char.isspace() else 1.15)
        line = _Line(text, boxes, provenance, "vertical-rl")
        _check_inside(line.bbox, (MARGIN, MARGIN, PAGE_W - MARGIN, PAGE_H - MARGIN), "column")
        self.lines.append(line)
        return line


def _table(canvas: _Canvas, table: TableBlock, y: int) -> tuple[dict[str, Any], list[_Line], int]:
    xs = [MARGIN + sum(table.col_widths[:i]) for i in range(len(table.col_widths) + 1)]
    ys = [y + sum(table.row_heights[:i]) for i in range(len(table.row_heights) + 1)]
    font = canvas.font_for(table.size)
    cells, lines, rows_html = [], [], []
    for row in range(len(table.row_heights)):
        row_cells = sorted((c for c in table.cells if c.row == row), key=lambda c: c.col)
        tds = []
        for cell in row_cells:
            box = (
                xs[cell.col],
                ys[cell.row],
                xs[cell.col + cell.colspan],
                ys[cell.row + cell.rowspan],
            )
            canvas.draw.rectangle(box, outline=INK, width=2)
            record: dict[str, Any] = {
                "row": cell.row,
                "col": cell.col,
                "rowspan": cell.rowspan,
                "colspan": cell.colspan,
                "text": cell.text,
                "bbox": list(box),
            }
            if cell.text:
                width = font.getlength(cell.text)
                tx = box[0] + (box[2] - box[0] - width) / 2
                ty = box[1] + (box[3] - box[1] - table.size * 1.25) / 2
                line = canvas.hline(cell.text, tx, ty, table.size, table.provenance)
                _check_inside(line.bbox, (box[0] + 3, box[1] + 3, box[2] - 3, box[3] - 3), "cell")
                record["text_bbox"] = list(line.bbox)
                lines.append(line)
            cells.append(record)
            spans = "".join(
                f' {name}="{value}"'
                for name, value in (("rowspan", cell.rowspan), ("colspan", cell.colspan))
                if value > 1
            )
            tds.append(f"<td{spans}>{html.escape(cell.text)}</td>")
        rows_html.append(f"<tr>{''.join(tds)}</tr>")
    gold = {
        "role": table.role,
        "bbox": [xs[0], ys[0], xs[-1], ys[-1]],
        "rows": len(table.row_heights),
        "cols": len(table.col_widths),
        "html": f"<table>{''.join(rows_html)}</table>",
        "cells": cells,
    }
    return gold, lines, ys[-1]


def _seal(canvas: _Canvas, target: _Line, seed: int, offsets: dict[int, int]) -> dict[str, Any]:
    pil, diameter = canvas.pil, 150
    layer = pil.image.new("RGBA", (diameter, diameter), (0, 0, 0, 0))
    draw = pil.draw.Draw(layer)
    draw.ellipse((4, 4, diameter - 5, diameter - 5), outline=SEAL_RGBA, width=7)
    font = canvas.font_for(54)
    width = font.getlength(SEAL_TEXT)
    draw.text(
        ((diameter - width) / 2, diameter / 2 - 54 * 0.62), SEAL_TEXT, fill=SEAL_RGBA, font=font
    )
    angle = round(-15 + 30 * _unit(seed, "seal-angle"), 3)
    layer = layer.rotate(angle, resample=pil.image.Resampling.BICUBIC, expand=True)
    _, y0, x1, y1 = target.bbox
    left = round(x1 - 40 + (_unit(seed, "seal-dx") - 0.5) * 50 - layer.width / 2)
    top = round((y0 + y1) / 2 + (_unit(seed, "seal-dy") - 0.5) * 30 - layer.height / 2)
    canvas.image.paste(layer, (left, top), layer)
    alpha = layer.getchannel("A")
    occluded: list[int] = []
    for index, line in enumerate(canvas.lines):
        for k, box in enumerate(line.chars):
            if box is None:
                continue
            crop = (box[0] - left, box[1] - top, box[2] - left, box[3] - top)
            crop = (
                max(crop[0], 0),
                max(crop[1], 0),
                min(crop[2], alpha.width),
                min(crop[3], alpha.height),
            )
            if crop[0] < crop[2] and crop[1] < crop[3] and alpha.crop(crop).getbbox():
                occluded.append(offsets[index] + k)
    if not occluded:
        raise FixtureError("the stamp covers no character; the overlay fixture would test nothing")
    spans: list[list[int]] = []
    for offset in occluded:
        if spans and spans[-1][1] == offset:
            spans[-1][1] = offset + 1
        else:
            spans.append([offset, offset + 1])
    ink = alpha.getbbox()
    return {
        "text": SEAL_TEXT,
        "fictional": True,
        "angle_deg": angle,
        "bbox": [left + ink[0], top + ink[1], left + ink[2], top + ink[3]],
        "occluded_spans": spans,
    }


def _render_page(
    pil: _Pil, font_for: Callable[[int], Any], page: PageSpec, seed: int
) -> tuple[Any, dict[str, Any]]:
    canvas = _Canvas(pil, font_for)
    members: list[list[_Line]] = []
    tables: list[tuple[dict[str, Any], list[_Line]]] = []
    y = MARGIN
    for block in page.blocks:
        if isinstance(block, TextBlock):
            lines = []
            for text, indent in block.lines:
                lines.append(canvas.hline(text, MARGIN + indent, y, block.size, block.provenance))
                y += round(block.size * 1.6)
            members.append(lines)
            y += block.size
        elif isinstance(block, TableBlock):
            gold_table, lines, y = _table(canvas, block, y)
            members.append(lines)
            tables.append((gold_table, lines))
            y += 40
        else:
            pitch = round(block.size * 1.9)
            right = PAGE_W - MARGIN - block.size
            columns = [
                canvas.vline(column, right - i * pitch, y, block.size, block.provenance)
                for i, column in enumerate(block.columns)
            ]
            members.extend([column] for column in columns)
            y = max(column.bbox[3] for column in columns) + 50
    lines = canvas.lines
    if [[line.text for line in block] for block in members] != gold_blocks(page):
        raise FixtureError(f"{page.page_id}: rendered reading order differs from the spec")
    offsets, cursor = {}, 0
    for index, line in enumerate(lines):
        offsets[index] = cursor
        cursor += len(line.text) + 1
    index_of = {id(line): index for index, line in enumerate(lines)}
    table_spans = []
    for gold_table, cell_lines in tables:
        first, last = index_of[id(cell_lines[0])], index_of[id(cell_lines[-1])]
        span = [offsets[first], offsets[last] + len(lines[last].text)]
        gold_table["text_span"] = span
        table_spans.append(span)
    seal = None
    if page.seal_over is not None:
        target = next(line for line in lines if line.text == page.seal_over)
        seal = _seal(canvas, target, seed, offsets)
    gold = {
        "page_id": page.page_id,
        "family_id": f"{LABEL}-KS-family-{page.slug}",
        "category": "KS",
        "synthetic": True,
        "label": LABEL,
        "image": f"{page.page_id}.png",
        "features": list(page.features),
        "text": "\n".join(line.text for line in lines),
        "blocks": ["\n".join(line.text for line in block) for block in members],
        "lines": [
            {
                "text": line.text,
                "bbox": list(line.bbox),
                "writing_mode": line.writing_mode,
                "provenance": line.provenance,
            }
            for line in lines
        ],
        "table_count": len(tables),
        "table_text_spans": table_spans,
        "tables": [gold_table for gold_table, _ in tables],
        "seal": seal,
        "approval_box": any(t["role"] == "approval_box" for t, _ in tables),
    }
    return canvas.image, gold


# ---------------------------------------------------------------------- outputs


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=1) + "\n").encode("utf-8")


def generator_sha256() -> str:
    """sha256 of this file with CRLF folded to LF, so a Windows checkout hashes the same."""
    return _sha256(Path(__file__).read_bytes().replace(b"\r\n", b"\n"))


def generate(out_dir: Path, seed: int = DEFAULT_SEED) -> dict[str, Any]:
    """Render every page in memory, then write PNGs, PDF, gold and manifest. Fail closed."""
    validate_pages(PAGES)
    pil = _pil()
    font_record = check_font(NOTO_SANS_KR)
    fonts: dict[int, Any] = {}

    def font_for(size: int) -> Any:
        if size not in fonts:
            font = pil.font.truetype(str(NOTO_SANS_KR), size)
            font.set_variation_by_axes([FONT_WEIGHT])
            fonts[size] = font
        return fonts[size]

    every_char = {
        c for page in PAGES for block in gold_blocks(page) for line in block for c in line
    }
    require_glyphs(pil, font_for(32), every_char | set(SEAL_TEXT))
    files: dict[str, bytes] = {}
    images, gold_pages = [], []
    for index, page in enumerate(PAGES):
        image, gold_page = _render_page(pil, font_for, page, seed)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        files[gold_page["image"]] = buffer.getvalue()
        gold_page["image_sha256"] = _sha256(buffer.getvalue())
        gold_page["pdf"] = PDF_NAME
        gold_page["pdf_page_index"] = index
        images.append(image)
        gold_pages.append(gold_page)
    buffer = io.BytesIO()
    images[0].save(
        buffer,
        format="PDF",
        save_all=True,
        append_images=images[1:],
        resolution=float(DPI),
        title=f"{LABEL} KB1 KS fixtures ({DATASET_REVISION})",
        creationDate=PDF_DATE,
        modDate=PDF_DATE,
    )
    files[PDF_NAME] = buffer.getvalue()
    files[GOLD_NAME] = _json_bytes(
        {
            "schema": GOLD_SCHEMA,
            "label": LABEL,
            "synthetic": True,
            "publishable": False,
            "dataset_revision": DATASET_REVISION,
            "gold_source": (
                "Written by generate.py at render time from the strings and boxes it drew;"
                " never OCR'd back."
            ),
            "seed": seed,
            "coordinate_frame": {
                "unit": "pixel",
                "dpi": DPI,
                "origin": "top-left",
                "page_size_px": [PAGE_W, PAGE_H],
            },
            "pages": gold_pages,
        }
    )
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "label": LABEL,
        "synthetic": True,
        "publishable": False,
        "note": "KS is a harness control: never a headline, never a public number (design §4).",
        "dataset_revision": DATASET_REVISION,
        "seed": seed,
        "generator": {"path": GENERATOR_PATH, "sha256_lf": generator_sha256()},
        "environment": {
            "python": sys.version,
            # By name only: the full path carries the builder's user name.
            "python_executable": Path(sys.executable).name,
            "pillow": pil.version,
            "freetype2": pil.features.version("freetype2"),
            "zlib": pil.features.version("zlib"),
            "libjpeg": pil.features.version("jpg"),
        },
        "fonts": [font_record],
        "files": {
            name: {"sha256": _sha256(data), "bytes": len(data)} for name, data in files.items()
        },
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    stray = sorted(
        p.name for p in out_dir.iterdir() if p.name not in files and p.name != MANIFEST_NAME
    )
    if stray:
        raise FixtureError(f"{out_dir} holds files this run does not produce: {stray}")
    for name, data in files.items():
        (out_dir / name).write_bytes(data)
    (out_dir / MANIFEST_NAME).write_bytes(_json_bytes(manifest))
    return manifest


def verify_manifest(out_dir: Path) -> dict[str, Any]:
    """Every file in ``out_dir`` is listed, labelled SYNTHETIC and matches its sha256."""
    manifest = json.loads((out_dir / MANIFEST_NAME).read_text(encoding="utf-8"))
    if manifest.get("label") != LABEL or manifest.get("synthetic") is not True:
        raise FixtureError("manifest is not labelled SYNTHETIC")
    listed = manifest.get("files")
    if not isinstance(listed, dict) or not listed:
        raise FixtureError("manifest lists no files")
    present = {p.name for p in out_dir.iterdir() if p.is_file()} - {MANIFEST_NAME}
    if present != set(listed):
        raise FixtureError(
            f"unlisted {sorted(present - set(listed))}, missing {sorted(set(listed) - present)}"
        )
    for name, record in listed.items():
        if LABEL not in name:
            raise FixtureError(f"{name}: file name does not carry {LABEL}")
        data = (out_dir / name).read_bytes()
        if _sha256(data) != record.get("sha256") or len(data) != record.get("bytes"):
            raise FixtureError(f"{name}: sha256 or size differs from the manifest")
    return dict(manifest)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render the SYNTHETIC KB1 KS fixtures.")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parent / "out")
    args = parser.parse_args(argv)
    manifest = generate(args.out, args.seed)
    summary = {name: record["sha256"] for name, record in manifest["files"].items()}
    print(json.dumps({"out": str(args.out), "seed": args.seed, "files": summary}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
