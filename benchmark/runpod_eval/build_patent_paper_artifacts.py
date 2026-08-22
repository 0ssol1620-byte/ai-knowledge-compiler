#!/usr/bin/env python3
# ruff: noqa: E501
"""Build deterministic patent drawings and paper-ready evidence artifacts."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass, field
from html import escape
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

SUITES = ("parsebench", "omnidocbench", "olmocr-bench")
INK = "#1B1F24"
MUTED = "#66707A"
GRID = "#D7DCE1"
PAPER = "#FFFFFF"
BLUE = "#205EA6"
CYAN = "#168B9A"
GOLD = "#B7791F"
OPEN_BLUE = "#DDEAF7"
OPEN_CYAN = "#DDF1F3"
OPEN_GOLD = "#F6EBD8"
SAFE_SQL_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


def _load(path: Path) -> dict[str, Any]:
    # PowerShell-written receipts carry a UTF-8 BOM; utf-8-sig reads both shapes.
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _sha256(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _receipt_sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _relative(path: Path, repository: Path) -> str:
    return path.resolve().relative_to(repository.resolve()).as_posix()


def _number(value: Any, *, default: float = 0.0) -> float:
    if value is None:
        return default
    return float(value)


def _integer(value: Any, *, default: int = 0) -> int:
    if value is None:
        return default
    return int(value)


def _font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    candidates = (
        Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
        if bold
        else Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    )
    for candidate in candidates:
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default(size=size)


@dataclass(slots=True)
class Canvas:
    width: int = 1200
    height: int = 800
    background: str = PAPER
    operations: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def rect(
        self,
        x: float,
        y: float,
        width: float,
        height: float,
        *,
        fill: str = "none",
        stroke: str = INK,
        stroke_width: float = 2,
        radius: float = 0,
    ) -> None:
        self.operations.append(
            (
                "rect",
                {
                    "x": x,
                    "y": y,
                    "width": width,
                    "height": height,
                    "fill": fill,
                    "stroke": stroke,
                    "stroke_width": stroke_width,
                    "radius": radius,
                },
            )
        )

    def line(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        *,
        stroke: str = INK,
        stroke_width: float = 2,
        dash: str | None = None,
    ) -> None:
        self.operations.append(
            (
                "line",
                {
                    "x1": x1,
                    "y1": y1,
                    "x2": x2,
                    "y2": y2,
                    "stroke": stroke,
                    "stroke_width": stroke_width,
                    "dash": dash,
                },
            )
        )

    def polygon(
        self,
        points: list[tuple[float, float]],
        *,
        fill: str = "none",
        stroke: str = INK,
        stroke_width: float = 2,
    ) -> None:
        self.operations.append(
            (
                "polygon",
                {
                    "points": points,
                    "fill": fill,
                    "stroke": stroke,
                    "stroke_width": stroke_width,
                },
            )
        )

    def circle(
        self,
        x: float,
        y: float,
        radius: float,
        *,
        fill: str = PAPER,
        stroke: str = INK,
        stroke_width: float = 2,
    ) -> None:
        self.operations.append(
            (
                "circle",
                {
                    "x": x,
                    "y": y,
                    "radius": radius,
                    "fill": fill,
                    "stroke": stroke,
                    "stroke_width": stroke_width,
                },
            )
        )

    def text(
        self,
        x: float,
        y: float,
        value: str,
        *,
        size: int = 24,
        fill: str = INK,
        anchor: str = "start",
        weight: str = "normal",
    ) -> None:
        self.operations.append(
            (
                "text",
                {
                    "x": x,
                    "y": y,
                    "value": value,
                    "size": size,
                    "fill": fill,
                    "anchor": anchor,
                    "weight": weight,
                },
            )
        )

    def arrow(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        *,
        stroke: str = INK,
        stroke_width: float = 2,
    ) -> None:
        self.line(x1, y1, x2, y2, stroke=stroke, stroke_width=stroke_width)
        angle = math.atan2(y2 - y1, x2 - x1)
        length = 13
        spread = 0.55
        points = [
            (x2, y2),
            (
                x2 - length * math.cos(angle - spread),
                y2 - length * math.sin(angle - spread),
            ),
            (
                x2 - length * math.cos(angle + spread),
                y2 - length * math.sin(angle + spread),
            ),
        ]
        self.polygon(points, fill=stroke, stroke=stroke, stroke_width=1)

    def save_svg(self, path: Path) -> None:
        lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            (
                f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.width}" '
                f'height="{self.height}" viewBox="0 0 {self.width} {self.height}" '
                'role="img">'
            ),
            f'<rect width="100%" height="100%" fill="{self.background}"/>',
        ]
        for kind, data in self.operations:
            if kind == "rect":
                lines.append(
                    f'<rect x="{data["x"]}" y="{data["y"]}" '
                    f'width="{data["width"]}" height="{data["height"]}" '
                    f'rx="{data["radius"]}" fill="{data["fill"]}" '
                    f'stroke="{data["stroke"]}" stroke-width="{data["stroke_width"]}"/>'
                )
            elif kind == "line":
                dash = f' stroke-dasharray="{data["dash"]}"' if data["dash"] else ""
                lines.append(
                    f'<line x1="{data["x1"]}" y1="{data["y1"]}" '
                    f'x2="{data["x2"]}" y2="{data["y2"]}" '
                    f'stroke="{data["stroke"]}" stroke-width="{data["stroke_width"]}"{dash}/>'
                )
            elif kind == "polygon":
                points = " ".join(f"{x},{y}" for x, y in data["points"])
                lines.append(
                    f'<polygon points="{points}" fill="{data["fill"]}" '
                    f'stroke="{data["stroke"]}" stroke-width="{data["stroke_width"]}"/>'
                )
            elif kind == "circle":
                lines.append(
                    f'<circle cx="{data["x"]}" cy="{data["y"]}" r="{data["radius"]}" '
                    f'fill="{data["fill"]}" stroke="{data["stroke"]}" '
                    f'stroke-width="{data["stroke_width"]}"/>'
                )
            elif kind == "text":
                anchor = {"start": "start", "middle": "middle", "end": "end"}[data["anchor"]]
                lines.append(
                    f'<text x="{data["x"]}" y="{data["y"]}" '
                    f'font-family="Arial, DejaVu Sans, sans-serif" '
                    f'font-size="{data["size"]}" font-weight="{data["weight"]}" '
                    f'text-anchor="{anchor}" fill="{data["fill"]}">'
                    f"{escape(str(data['value']))}</text>"
                )
        lines.append("</svg>")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def save_png(self, path: Path, *, scale: int = 2) -> None:
        image = Image.new("RGB", (self.width * scale, self.height * scale), self.background)
        draw = ImageDraw.Draw(image)

        def px(value: float) -> int:
            return round(value * scale)

        for kind, data in self.operations:
            if kind == "rect":
                bounds = (
                    px(data["x"]),
                    px(data["y"]),
                    px(data["x"] + data["width"]),
                    px(data["y"] + data["height"]),
                )
                fill = None if data["fill"] == "none" else data["fill"]
                draw.rounded_rectangle(
                    bounds,
                    radius=px(data["radius"]),
                    fill=fill,
                    outline=data["stroke"],
                    width=max(1, px(data["stroke_width"])),
                )
            elif kind == "line":
                draw.line(
                    (px(data["x1"]), px(data["y1"]), px(data["x2"]), px(data["y2"])),
                    fill=data["stroke"],
                    width=max(1, px(data["stroke_width"])),
                )
            elif kind == "polygon":
                points = [(px(x), px(y)) for x, y in data["points"]]
                fill = None if data["fill"] == "none" else data["fill"]
                draw.polygon(points, fill=fill, outline=data["stroke"])
            elif kind == "circle":
                radius = data["radius"]
                bounds = (
                    px(data["x"] - radius),
                    px(data["y"] - radius),
                    px(data["x"] + radius),
                    px(data["y"] + radius),
                )
                draw.ellipse(
                    bounds,
                    fill=data["fill"],
                    outline=data["stroke"],
                    width=max(1, px(data["stroke_width"])),
                )
            elif kind == "text":
                anchor = {"start": "la", "middle": "ma", "end": "ra"}[data["anchor"]]
                draw.text(
                    (px(data["x"]), px(data["y"])),
                    str(data["value"]),
                    fill=data["fill"],
                    font=_font(data["size"] * scale, bold=data["weight"] == "bold"),
                    anchor=anchor,
                )
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path, format="PNG", dpi=(300, 300), optimize=True)


def _save_figure(canvas: Canvas, stem: Path) -> list[Path]:
    svg = stem.with_suffix(".svg")
    png = stem.with_suffix(".png")
    canvas.save_svg(svg)
    canvas.save_png(png)
    return [svg, png]


def _title(canvas: Canvas, title: str, subtitle: str) -> None:
    canvas.text(70, 58, title, size=31, weight="bold")
    canvas.text(70, 92, subtitle, size=17, fill=MUTED)


def _box(
    canvas: Canvas,
    x: float,
    y: float,
    width: float,
    height: float,
    label: str,
    *,
    fill: str = PAPER,
    number: str | None = None,
) -> None:
    canvas.rect(x, y, width, height, fill=fill, radius=8)
    if number:
        canvas.circle(x + 25, y + 25, 14, fill=PAPER)
        canvas.text(x + 25, y + 31, number, size=15, anchor="middle", weight="bold")
    lines = label.split("\n")
    offset = (len(lines) - 1) * 13
    for index, line in enumerate(lines):
        canvas.text(
            x + width / 2,
            y + height / 2 - offset + index * 26 + 7,
            line,
            size=18,
            anchor="middle",
            weight="bold" if index == 0 else "normal",
        )


def _patent_architecture() -> Canvas:
    canvas = Canvas(width=1500, height=980)
    _title(
        canvas,
        "FIG. 1 — Evidence-bound selective recovery system",
        "Deterministic system drawing; not a measured-result figure",
    )
    boxes = [
        (70, 170, "Public benchmark\ninputs"),
        (310, 170, "Document-level\nshard scheduler"),
        (550, 170, "MinerU 3.4.4\nbaseline"),
        (790, 170, "Fault and quality\ndetector"),
    ]
    for index, (x, y, label) in enumerate(boxes, 1):
        _box(canvas, x, y, 190, 100, label, number=str(index))
        if index > 1:
            canvas.arrow(x - 50, y + 50, x, y + 50)
    _box(canvas, 1030, 130, 200, 95, "Different-Pod\nMinerU retry", number="5")
    _box(canvas, 1030, 260, 200, 95, "Selective alternate\nmodel route", number="6")
    canvas.arrow(980, 220, 1030, 178)
    canvas.arrow(980, 220, 1030, 308)
    _box(canvas, 1260, 235, 180, 95, "Official metric\ncomparison", number="7")
    canvas.arrow(1230, 178, 1260, 260)
    canvas.arrow(1230, 308, 1260, 300)
    _box(canvas, 950, 470, 200, 90, "Accept improvement", number="8A")
    _box(canvas, 1210, 470, 200, 90, "Revert regression", number="8B")
    canvas.arrow(1350, 330, 1050, 470)
    canvas.arrow(1350, 330, 1310, 470)
    _box(canvas, 620, 665, 240, 100, "Three-repeat\nstratified audit", number="9")
    _box(canvas, 930, 665, 240, 100, "Signed evidence\nledger and hashes", number="10")
    _box(canvas, 1240, 665, 190, 100, "Cost gate and\nresource cleanup", number="11")
    canvas.arrow(1050, 560, 800, 665)
    canvas.arrow(1310, 560, 1050, 665)
    canvas.arrow(860, 715, 930, 715)
    canvas.arrow(1170, 715, 1240, 715)
    canvas.text(
        70,
        900,
        "Solid arrows denote executable transitions. Every measured claim is bound to a receipt hash.",
        size=18,
        fill=MUTED,
    )
    return canvas


def _patent_state_machine() -> Canvas:
    canvas = Canvas(width=1500, height=980)
    _title(
        canvas,
        "FIG. 2 — Fault detection and recovery state machine",
        "Operational and quality failures remain distinct until official evaluation",
    )
    states = [
        (80, 170, "RUNNING\nhealth observed"),
        (330, 170, "ANOMALY\nclassified"),
        (580, 170, "QUARANTINED\nwhen repeated stall"),
        (830, 170, "RETRY\non different Pod"),
        (1080, 170, "CANDIDATE\noutput frozen"),
    ]
    for index, (x, y, label) in enumerate(states, 1):
        _box(canvas, x, y, 190, 100, label, number=str(index))
        if index > 1:
            canvas.arrow(x - 60, y + 50, x, y + 50)
    diamond = [(1190, 390), (1320, 480), (1190, 570), (1060, 480)]
    canvas.polygon(diamond, fill=PAPER)
    canvas.text(1190, 468, "Official metric", size=19, anchor="middle", weight="bold")
    canvas.text(1190, 495, "improved?", size=19, anchor="middle")
    canvas.arrow(1175, 270, 1190, 390)
    _box(canvas, 760, 665, 200, 90, "ACCEPT\nverified output", number="6A")
    _box(canvas, 1060, 665, 200, 90, "REVERT\nbaseline output", number="6B")
    _box(canvas, 1320, 665, 140, 90, "ESCALATE\nunresolved", number="6C")
    canvas.arrow(1105, 555, 860, 665)
    canvas.text(995, 610, "yes", size=16, weight="bold")
    canvas.arrow(1190, 570, 1160, 665)
    canvas.text(1170, 620, "no / regression", size=16, anchor="middle", weight="bold")
    canvas.arrow(1270, 535, 1385, 665)
    canvas.text(1350, 610, "no valid candidate", size=16, anchor="middle")
    _box(canvas, 170, 665, 230, 90, "EVIDENCE\nraw failure retained", number="7")
    _box(canvas, 470, 665, 220, 90, "AUDIT\nselection replayed", number="8")
    canvas.arrow(760, 710, 690, 710)
    canvas.arrow(470, 710, 400, 710)
    canvas.text(
        80,
        900,
        "A retry completion is not itself an accuracy claim; official evaluators decide acceptance.",
        size=19,
        fill=MUTED,
    )
    return canvas


def _patent_parallel_evidence() -> Canvas:
    canvas = Canvas(width=1500, height=980)
    _title(
        canvas,
        "FIG. 3 — Multi-Pod execution and evidence preservation",
        "Independent document shards converge only through hashed receipts and gates",
    )
    for index, x in enumerate((90, 350, 610, 870), 0):
        _box(
            canvas,
            x,
            180,
            190,
            90,
            f"Primary Pod {index}\nindependent shard",
            number=str(index + 1),
        )
        canvas.arrow(x + 95, 270, x + 95, 370)
        _box(canvas, x, 370, 190, 80, "Run summary\ncase outcomes")
        canvas.arrow(x + 95, 450, 690, 570)
    _box(canvas, 580, 560, 240, 95, "Detection and\nretry plan receipt", number="5")
    _box(canvas, 1080, 340, 270, 90, "Eligible retry Pods\nbyte-identical model", number="6")
    canvas.arrow(820, 605, 1080, 385)
    _box(canvas, 1080, 540, 270, 90, "Accepted/reverted\ncase overlay", number="7")
    canvas.arrow(1215, 430, 1215, 540)
    _box(canvas, 360, 760, 250, 90, "SHA-256 evidence\nmanifest", number="8")
    _box(canvas, 700, 760, 250, 90, "Provider billing and\nUSD 400 cap", number="9")
    _box(canvas, 1040, 760, 250, 90, "Verified deletion of\nall RunPod resources", number="10")
    canvas.arrow(700, 655, 485, 760)
    canvas.arrow(820, 655, 825, 760)
    canvas.arrow(1215, 630, 1165, 760)
    canvas.arrow(610, 805, 700, 805)
    canvas.arrow(950, 805, 1040, 805)
    return canvas


def _accuracy_figure(rows: list[dict[str, Any]]) -> Canvas:
    canvas = Canvas(width=1400, height=900)
    _title(
        canvas,
        "Documents with zero official failures",
        "Full public corpus; baseline and final verified outputs",
    )
    left, top, chart_width = 310, 180, 940
    canvas.line(left, top - 20, left, 760, stroke=INK)
    for tick in range(0, 11):
        x = left + chart_width * tick / 10
        canvas.line(x, top - 10, x, 760, stroke=GRID, stroke_width=1)
        canvas.text(x, 790, f"{tick * 10}%", size=16, anchor="middle", fill=MUTED)
    for index, row in enumerate(rows):
        y = top + index * 185
        canvas.text(left - 25, y + 45, row["suite"], size=22, anchor="end", weight="bold")
        baseline = float(row["baseline_rate"])
        final = float(row["final_rate"])
        canvas.rect(left, y, chart_width * baseline, 48, fill=OPEN_BLUE, stroke=BLUE)
        canvas.rect(left, y + 65, chart_width * final, 48, fill=CYAN, stroke=CYAN)
        canvas.text(
            left + chart_width * baseline + 12,
            y + 31,
            f"{baseline:.1%}",
            size=18,
            fill=BLUE,
            weight="bold",
        )
        canvas.text(
            left + chart_width * final + 12,
            y + 96,
            f"{final:.1%}",
            size=18,
            fill=INK,
            weight="bold",
        )
        canvas.text(
            left,
            y + 142,
            f"+{float(row['absolute_rate_gain']):.2%} points; "
            f"{int(row['additional_cases_cleared']):,} additional documents",
            size=17,
            fill=MUTED,
        )
    canvas.rect(1030, 115, 28, 18, fill=OPEN_BLUE, stroke=BLUE)
    canvas.text(1070, 130, "Baseline", size=17)
    canvas.rect(1170, 115, 28, 18, fill=CYAN, stroke=CYAN)
    canvas.text(1210, 130, "Final", size=17)
    return canvas


def _selection_figure(rows: list[dict[str, Any]]) -> Canvas:
    canvas = Canvas(width=1400, height=900)
    _title(
        canvas,
        "Selective alternate-model outcomes",
        "Only official-metric improvements are accepted; regressions are reverted",
    )
    maximum = max([int(row["routed"]) for row in rows] + [1])
    left, width = 330, 900
    for index, row in enumerate(rows):
        y = 230 + index * 260
        canvas.text(left - 30, y + 50, row["model"], size=24, anchor="end", weight="bold")
        for offset, key, color, label in (
            (0, "routed", OPEN_BLUE, "Routed"),
            (65, "accepted", CYAN, "Accepted"),
            (130, "reverted", OPEN_GOLD, "Reverted"),
        ):
            value = int(row[key])
            bar = width * value / maximum
            canvas.rect(left, y + offset, bar, 42, fill=color, stroke=INK)
            canvas.text(left - 15, y + offset + 28, label, size=17, anchor="end", fill=MUTED)
            canvas.text(left + bar + 12, y + offset + 29, f"{value:,}", size=18, weight="bold")
        canvas.text(
            left,
            y + 210,
            f"Acceptance rate {float(row['acceptance_rate']):.1%}",
            size=18,
            fill=MUTED,
        )
    return canvas


def _stability_figure(rows: list[dict[str, Any]]) -> Canvas:
    canvas = Canvas(width=1400, height=900)
    _title(
        canvas,
        "Three-repeat stratified audit stability",
        "128 cases per benchmark x exactly 3 repeats; not a duplicate full-corpus run",
    )
    left, top, chart_width = 310, 190, 940
    for tick in range(0, 11):
        x = left + chart_width * tick / 10
        canvas.line(x, top - 20, x, 760, stroke=GRID, stroke_width=1)
        canvas.text(x, 795, f"{tick * 10}%", size=16, anchor="middle", fill=MUTED)
    for index, row in enumerate(rows):
        y = top + index * 180
        canvas.text(left - 25, y + 50, row["suite"], size=22, anchor="end", weight="bold")
        identical = float(row["identical_markdown_rate"])
        terminal = float(row["stable_terminal_status_rate"])
        canvas.rect(left, y, chart_width * identical, 48, fill=BLUE, stroke=BLUE)
        canvas.rect(left, y + 65, chart_width * terminal, 48, fill=OPEN_CYAN, stroke=CYAN)
        canvas.text(
            left + chart_width * identical + 12,
            y + 31,
            f"{identical:.1%}",
            size=18,
            weight="bold",
        )
        canvas.text(
            left + chart_width * terminal + 12,
            y + 96,
            f"{terminal:.1%}",
            size=18,
            weight="bold",
        )
    canvas.rect(875, 115, 28, 18, fill=BLUE, stroke=BLUE)
    canvas.text(915, 130, "Identical Markdown", size=17)
    canvas.rect(1115, 115, 28, 18, fill=OPEN_CYAN, stroke=CYAN)
    canvas.text(1155, 130, "Stable status", size=17)
    return canvas


def _detection_figure(rows: list[dict[str, Any]]) -> Canvas:
    canvas = Canvas(width=1500, height=900)
    _title(
        canvas,
        "Fault-detection confusion matrices",
        "Live policy-conformance evidence; controlled injection remains separately identified",
    )
    for panel, row in enumerate(rows):
        x0 = 80 + panel * 480
        canvas.text(x0 + 180, 170, row["label"], size=21, anchor="middle", weight="bold")
        canvas.text(x0 + 180, 207, "Predicted", size=17, anchor="middle", fill=MUTED)
        canvas.text(x0 - 8, 400, "Observed", size=17, anchor="middle", fill=MUTED)
        cells = [
            ("TP", int(row["true_positive"]), BLUE),
            ("FN", int(row["false_negative"]), OPEN_GOLD),
            ("FP", int(row["false_positive"]), OPEN_GOLD),
            ("TN", int(row["true_negative"]), OPEN_CYAN),
        ]
        for index, (label, value, color) in enumerate(cells):
            col, line = index % 2, index // 2
            x, y = x0 + col * 180, 250 + line * 180
            canvas.rect(x, y, 160, 160, fill=color, stroke=INK)
            canvas.text(x + 80, y + 68, label, size=20, anchor="middle", weight="bold")
            canvas.text(x + 80, y + 115, f"{value:,}", size=32, anchor="middle", weight="bold")
        canvas.text(
            x0 + 170,
            660,
            f"Precision {row['precision_text']}   Recall {row['recall_text']}",
            size=17,
            anchor="middle",
        )
    return canvas


def _cost_figure(cost: dict[str, Any], timing: dict[str, Any]) -> Canvas:
    canvas = Canvas(width=1400, height=850)
    _title(
        canvas,
        "Campaign cost and elapsed time",
        "Provider billing boundary through verified cleanup and final report creation",
    )
    total = _number(cost.get("total_runtime_rate_estimate_usd"))
    cap = _number(cost.get("approved_cap_usd"), default=400.0)
    elapsed = _number(timing.get("elapsed_hours_to_report"))
    left, width = 180, 1030
    canvas.text(left, 205, "RunPod cost", size=24, weight="bold")
    canvas.rect(left, 245, width, 72, fill="#F0F2F4", stroke=GRID, radius=8)
    canvas.rect(left, 245, width * min(total / cap, 1), 72, fill=BLUE, stroke=BLUE, radius=8)
    canvas.text(left + 20, 293, f"USD {total:.2f}", size=23, fill=PAPER, weight="bold")
    canvas.text(
        left + width, 293, f"Cap USD {cap:.0f}", size=20, anchor="end", fill=INK, weight="bold"
    )
    canvas.text(left, 430, "Elapsed wall time", size=24, weight="bold")
    canvas.rect(left, 470, width, 72, fill=OPEN_CYAN, stroke=CYAN, radius=8)
    canvas.text(left + 20, 518, f"{elapsed:.2f} hours", size=23, weight="bold")
    canvas.text(
        left,
        665,
        "Cost evidence is provider-derived. Time includes execution, recovery, evaluation, and cleanup.",
        size=19,
        fill=MUTED,
    )
    return canvas


def _accuracy_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for suite in SUITES:
        source = report["case_zero_official_failure_accuracy"][suite]
        input_count = _integer(source["input_count"])
        baseline_count = _integer(source["baseline_cases_with_zero_official_failures"])
        final_count = _integer(source["final_cases_with_zero_official_failures"])
        rows.append(
            {
                "suite": suite,
                "input_count": input_count,
                "baseline_count": baseline_count,
                "final_count": final_count,
                "baseline_rate": baseline_count / input_count if input_count else 0.0,
                "final_rate": final_count / input_count if input_count else 0.0,
                "absolute_rate_gain": _number(source["absolute_rate_gain"]),
                "additional_cases_cleared": _integer(source["additional_cases_cleared"]),
            }
        )
    return rows


def _selection_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    selection = report["selection"]
    rows = []
    for model, prefix in (
        ("PaddleOCR-VL", "paddle"),
        ("DeepSeek-OCR-2", "deepseek"),
    ):
        routed = _integer(selection[f"{prefix}_routed_case_count"])
        accepted = _integer(selection[f"{prefix}_accepted_case_count"])
        reverted = _integer(selection[f"{prefix}_reverted_regression_case_count"])
        if accepted + reverted != routed:
            raise ValueError(f"selection coverage mismatch: {model}")
        rows.append(
            {
                "model": model,
                "routed": routed,
                "accepted": accepted,
                "reverted": reverted,
                "acceptance_rate": accepted / routed if routed else 0.0,
            }
        )
    return rows


def _stability_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    audit = report["three_repeat_variance_audit"]
    records = audit.get("inference_stability", [])
    by_suite = {str(item["benchmark_id"]): item for item in records}
    if set(by_suite) != set(SUITES):
        raise ValueError("three-repeat inference stability does not cover all suites")
    return [
        {
            "suite": suite,
            "identical_markdown_rate": _number(
                by_suite[suite]["identical_markdown_all_three_rate"]
            ),
            "stable_terminal_status_rate": _number(by_suite[suite]["stable_terminal_status_rate"]),
            "identical_markdown_count": _integer(
                by_suite[suite]["identical_markdown_all_three_count"]
            ),
            "stable_terminal_status_count": _integer(
                by_suite[suite]["stable_terminal_status_count"]
            ),
            "input_count": 128,
        }
        for suite in SUITES
    ]


def _detection_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    detection = report["operational_fault_detection"]
    keys = (
        ("Case failure routing", "case_failure_detection"),
        ("Worker anomaly", "worker_anomaly_detection"),
        ("Repeated-stall quarantine", "worker_repeated_stall_quarantine"),
    )
    rows = []
    for label, key in keys:
        metric = detection[key]
        precision = metric.get("precision")
        recall = metric.get("recall")
        rows.append(
            {
                "label": label,
                "true_positive": _integer(metric["true_positive"]),
                "false_positive": _integer(metric["false_positive"]),
                "false_negative": _integer(metric["false_negative"]),
                "true_negative": _integer(metric["true_negative"]),
                "precision": precision,
                "recall": recall,
                "precision_text": "n/a" if precision is None else f"{float(precision):.3f}",
                "recall_text": "n/a" if recall is None else f"{float(recall):.3f}",
            }
        )
    return rows


def _official_delta_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    delta = report["official_metrics"]["delta"]
    return [
        {"metric": str(key), "delta": value, "beneficial_direction": "reported"}
        for key, value in sorted(delta.items())
        if isinstance(value, int | float)
    ]


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"cannot write an empty evidence CSV: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _chart_contracts() -> list[dict[str, Any]]:
    return [
        {
            "id": "paper-fig-01-zero-official-failure-rate",
            "question": "How much did verified selective recovery improve document-level official pass rates?",
            "takeaway": "Compare baseline and final rates per public benchmark without mixing denominators.",
            "family": "comparison",
            "variant": "grouped horizontal bar",
            "data_grain": "one aggregate row per benchmark",
            "renderer": "deterministic SVG and 300-dpi PNG",
            "palette_policy": "hard two-root cap with direct labels",
            "non_color_distinction": "open baseline fill versus solid final fill",
        },
        {
            "id": "paper-fig-02-alternate-model-selection",
            "question": "How many candidates were routed, accepted, and reverted for each alternate model?",
            "takeaway": "Acceptance is conditioned on official improvement; regression candidates return to baseline.",
            "family": "progression",
            "variant": "stage bars",
            "data_grain": "one aggregate row per alternate model",
            "renderer": "deterministic SVG and 300-dpi PNG",
            "palette_policy": "relaxed three-state palette",
            "non_color_distinction": "separate rows and exact labels",
        },
        {
            "id": "paper-fig-03-three-repeat-stability",
            "question": "How stable were outputs and terminal states across exactly three audit repeats?",
            "takeaway": "Show the bounded 128-case-per-suite repeat audit, not a repeated full-corpus claim.",
            "family": "uncertainty and benchmark",
            "variant": "paired horizontal bar",
            "data_grain": "one aggregate row per benchmark",
            "renderer": "deterministic SVG and 300-dpi PNG",
            "palette_policy": "hard two-root cap",
            "non_color_distinction": "solid versus open fill",
        },
        {
            "id": "paper-fig-04-detection-confusion-matrices",
            "question": "Did case routing, anomaly detection, and quarantine decisions match frozen labels?",
            "takeaway": "Confusion matrices expose both positive and negative counts and avoid F1-only reporting.",
            "family": "matrix",
            "variant": "three small-multiple confusion matrices",
            "data_grain": "aggregate confusion counts per decision layer",
            "renderer": "deterministic SVG and 300-dpi PNG",
            "palette_policy": "two-root plus neutral",
            "non_color_distinction": "cell labels and exact counts",
        },
        {
            "id": "paper-fig-05-cost-time",
            "question": "Did the campaign remain inside the approved provider cost boundary?",
            "takeaway": "Show provider-derived cost against the USD 400 cap with total elapsed wall time.",
            "family": "status",
            "variant": "bounded progress bars",
            "data_grain": "one final provider snapshot",
            "renderer": "deterministic SVG and 300-dpi PNG",
            "palette_policy": "single-root preferred",
            "non_color_distinction": "exact labels and outlined cap bar",
        },
    ]


def _sqlite_source(
    *,
    source_id: str,
    label: str,
    path: str,
    table: str,
    rows: list[dict[str, Any]],
    generated_at: str,
    order_by: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Execute the exact report query against a bounded in-memory evidence table."""
    if not rows:
        raise ValueError(f"SQL source rows are empty: {source_id}")
    columns = list(rows[0])
    if not SAFE_SQL_IDENTIFIER.fullmatch(table) or any(
        not SAFE_SQL_IDENTIFIER.fullmatch(column) for column in columns
    ):
        raise ValueError(f"unsafe SQL evidence identifier: {source_id}")
    if order_by not in columns:
        raise ValueError(f"SQL order field is absent: {source_id}/{order_by}")
    if any(list(row) != columns for row in rows):
        raise ValueError(f"SQL source columns are inconsistent: {source_id}")
    declarations = []
    for column in columns:
        values = [row[column] for row in rows if row[column] is not None]
        sql_type = "REAL" if values and all(isinstance(value, int | float) for value in values) else "TEXT"
        declarations.append(f'"{column}" {sql_type}')
    select_columns = ", ".join(f'"{column}"' for column in columns)
    sql = (
        f'SELECT {select_columns} FROM "{table}" ORDER BY "{order_by}"'  # noqa: S608
    )
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute(f'CREATE TABLE "{table}" ({", ".join(declarations)})')
        placeholders = ", ".join("?" for _ in columns)
        connection.executemany(
            f'INSERT INTO "{table}" VALUES ({placeholders})',  # noqa: S608
            [[row[column] for column in columns] for row in rows],
        )
        selected = connection.execute(sql).fetchall()
    finally:
        connection.close()
    if len(selected) != len(rows):
        raise ValueError(f"SQL source row coverage mismatch: {source_id}")
    manifest_source = {"id": source_id, "label": label, "path": path}
    canonical_source = {
        "id": source_id,
        "label": label,
        "path": path,
        "query": {
            "engine": "sqlite",
            "language": "sql",
            "sql": sql,
            "description": (
                "Selects the bounded rows deterministically extracted from the final "
                "FOLYNTA evidence report by build_patent_paper_artifacts.py."
            ),
            "executed_at": generated_at,
            "tables_used": [table],
        },
    }
    return manifest_source, canonical_source


def _paper_artifact(
    *,
    report: dict[str, Any],
    final_report_relative: str,
    accuracy: list[dict[str, Any]],
    selection: list[dict[str, Any]],
    stability: list[dict[str, Any]],
    detection: list[dict[str, Any]],
    official_delta: list[dict[str, Any]],
) -> dict[str, Any]:
    created = str(report["created_at_utc"])
    cost = report["cost"]
    elapsed = _number(report["timing"]["elapsed_hours_to_report"])
    total_cleared = sum(int(row["additional_cases_cleared"]) for row in accuracy)
    accuracy_chart_rows = [
        {
            "suite": row["suite"],
            "absolute_rate_gain": row["absolute_rate_gain"],
            "baseline_rate": row["baseline_rate"],
            "final_rate": row["final_rate"],
            "input_count": row["input_count"],
            "additional_cases_cleared": row["additional_cases_cleared"],
        }
        for row in accuracy
    ]
    headline_rows = [
        {
            "full_corpus": _integer(report["scope"]["full_corpus_input_count"]),
            "additional_cleared": total_cleared,
            "cost_usd": _number(cost["total_runtime_rate_estimate_usd"]),
            "cap_usd": _number(cost["approved_cap_usd"]),
            "elapsed_hours": elapsed,
        }
    ]
    detection_rows = [
        {key: value for key, value in row.items() if not key.endswith("_text")}
        for row in detection
    ]
    source_definitions = [
        _sqlite_source(
            source_id="headline_query",
            label="Final benchmark headline metrics",
            path=final_report_relative,
            table="evidence_headline",
            rows=headline_rows,
            generated_at=created,
            order_by="full_corpus",
        ),
        _sqlite_source(
            source_id="accuracy_query",
            label="Benchmark recovery effects",
            path="data/benchmark-recovery-effects.csv",
            table="evidence_accuracy",
            rows=accuracy,
            generated_at=created,
            order_by="suite",
        ),
        _sqlite_source(
            source_id="selection_query",
            label="Alternate-model selection outcomes",
            path="data/alternate-model-selection.csv",
            table="evidence_selection",
            rows=selection,
            generated_at=created,
            order_by="model",
        ),
        _sqlite_source(
            source_id="stability_query",
            label="Three-repeat stability evidence",
            path="data/three-repeat-stability.csv",
            table="evidence_stability",
            rows=stability,
            generated_at=created,
            order_by="suite",
        ),
        _sqlite_source(
            source_id="detection_query",
            label="Fault-detection confusion counts",
            path="data/fault-detection-confusion-counts.csv",
            table="evidence_detection",
            rows=detection_rows,
            generated_at=created,
            order_by="label",
        ),
        _sqlite_source(
            source_id="official_delta_query",
            label="Official evaluator metric deltas",
            path="data/official-metric-deltas.csv",
            table="evidence_official_delta",
            rows=official_delta,
            generated_at=created,
            order_by="metric",
        ),
    ]
    manifest_sources = [
        {
            "id": "final_report",
            "label": "FOLYNTA final official benchmark recovery report",
            "path": final_report_relative,
        },
        *(item[0] for item in source_definitions),
    ]
    sources = [
        {
            "id": "final_report",
            "label": "FOLYNTA final official benchmark recovery report",
            "path": final_report_relative,
        },
        *(item[1] for item in source_definitions),
    ]
    cards = [
        {
            "id": "corpus_card",
            "description": "Full frozen public benchmark corpus.",
            "dataset": "headline_metrics",
            "sourceId": "headline_query",
            "metrics": [{"label": "Public cases", "field": "full_corpus", "format": "number"}],
        },
        {
            "id": "cleared_card",
            "description": "Additional documents with zero official failures.",
            "dataset": "headline_metrics",
            "sourceId": "headline_query",
            "metrics": [
                {"label": "Additional cleared", "field": "additional_cleared", "format": "number"}
            ],
        },
        {
            "id": "cost_card",
            "description": "Provider-derived campaign cost under the approved cap.",
            "dataset": "headline_metrics",
            "sourceId": "headline_query",
            "metrics": [
                {"label": "RunPod cost", "field": "cost_usd", "format": "currency"},
                {"label": "Approved cap", "field": "cap_usd", "format": "currency"},
            ],
        },
        {
            "id": "elapsed_card",
            "description": "Execution through verified cleanup and reporting.",
            "dataset": "headline_metrics",
            "sourceId": "headline_query",
            "metrics": [{"label": "Elapsed hours", "field": "elapsed_hours", "format": "number"}],
        },
    ]
    charts = [
        {
            "id": "accuracy_gain_chart",
            "title": "Absolute official-pass-rate gain by benchmark",
            "subtitle": "Full public corpus; percentage-point gain from baseline to final verified output",
            "type": "bar",
            "dataset": "accuracy",
            "sourceId": "accuracy_query",
            "valueFormat": "percent",
            "encodings": {
                "x": {"field": "suite", "type": "nominal", "label": "Benchmark"},
                "y": {"field": "absolute_rate_gain", "type": "quantitative", "label": "Rate gain"},
                "tooltip": [
                    {
                        "field": "baseline_rate",
                        "type": "quantitative",
                        "label": "Baseline",
                        "format": "percent",
                    },
                    {
                        "field": "final_rate",
                        "type": "quantitative",
                        "label": "Final",
                        "format": "percent",
                    },
                    {"field": "input_count", "type": "quantitative", "label": "Cases"},
                ],
            },
        },
        {
            "id": "selection_chart",
            "title": "Alternate-model acceptance rate",
            "subtitle": "Accepted candidates divided by routed candidates; regressions are reverted",
            "type": "bar",
            "dataset": "selection",
            "sourceId": "selection_query",
            "valueFormat": "percent",
            "encodings": {
                "x": {"field": "model", "type": "nominal", "label": "Model"},
                "y": {
                    "field": "acceptance_rate",
                    "type": "quantitative",
                    "label": "Acceptance rate",
                },
                "tooltip": [
                    {"field": "routed", "type": "quantitative", "label": "Routed"},
                    {"field": "accepted", "type": "quantitative", "label": "Accepted"},
                    {"field": "reverted", "type": "quantitative", "label": "Reverted"},
                ],
            },
        },
        {
            "id": "stability_chart",
            "title": "Exact Markdown stability across three repeats",
            "subtitle": "128 stratified cases per benchmark; repeat scope is explicitly bounded",
            "type": "bar",
            "dataset": "stability",
            "sourceId": "stability_query",
            "valueFormat": "percent",
            "encodings": {
                "x": {"field": "suite", "type": "nominal", "label": "Benchmark"},
                "y": {
                    "field": "identical_markdown_rate",
                    "type": "quantitative",
                    "label": "Exact stability",
                },
                "tooltip": [
                    {
                        "field": "stable_terminal_status_rate",
                        "type": "quantitative",
                        "label": "Stable terminal status",
                        "format": "percent",
                    },
                    {"field": "input_count", "type": "quantitative", "label": "Cases per repeat"},
                ],
            },
        },
    ]
    tables = [
        {
            "id": "accuracy_table",
            "title": "Benchmark-level recovery effects",
            "subtitle": "Exact full-corpus denominators and baseline/final document counts",
            "dataset": "accuracy",
            "sourceId": "accuracy_query",
            "defaultSort": {"field": "suite", "direction": "asc"},
            "columns": [
                {"field": "suite", "label": "Benchmark", "type": "text"},
                {"field": "input_count", "label": "Input", "format": "number"},
                {"field": "baseline_count", "label": "Baseline zero-failure", "format": "number"},
                {"field": "final_count", "label": "Final zero-failure", "format": "number"},
                {"field": "absolute_rate_gain", "label": "Absolute rate gain", "format": "percent"},
                {
                    "field": "additional_cases_cleared",
                    "label": "Additional cleared",
                    "format": "number",
                },
            ],
        },
        {
            "id": "detection_table",
            "title": "Fault-decision confusion counts",
            "subtitle": "Case routing, worker anomaly, and repeated-stall quarantine layers",
            "dataset": "detection",
            "sourceId": "detection_query",
            "defaultSort": {"field": "label", "direction": "asc"},
            "columns": [
                {"field": "label", "label": "Decision layer", "type": "text"},
                {"field": "true_positive", "label": "TP", "format": "number"},
                {"field": "false_positive", "label": "FP", "format": "number"},
                {"field": "false_negative", "label": "FN", "format": "number"},
                {"field": "true_negative", "label": "TN", "format": "number"},
                {"field": "precision", "label": "Precision", "format": "percent"},
                {"field": "recall", "label": "Recall", "format": "percent"},
            ],
        },
        {
            "id": "official_delta_table",
            "title": "Official evaluator metric deltas",
            "subtitle": "Metrics retain their evaluator-defined units and directions",
            "dataset": "official_delta",
            "sourceId": "official_delta_query",
            "defaultSort": {"field": "metric", "direction": "asc"},
            "columns": [
                {"field": "metric", "label": "Metric", "type": "text"},
                {"field": "delta", "label": "Delta", "format": "number"},
                {"field": "beneficial_direction", "label": "Interpretation", "type": "text"},
            ],
        },
    ]
    blocks = [
        {
            "id": "title",
            "type": "markdown",
            "body": "# FOLYNTA Public Benchmark Recovery Technical Report",
        },
        {
            "id": "technical_summary",
            "type": "markdown",
            "sourceId": "final_report",
            "body": (
                "## Technical summary\n\n"
                f"The frozen {int(report['scope']['full_corpus_input_count']):,}-case public corpus was processed with "
                "MinerU 3.4.4 as the baseline and official-metric-gated selective recovery. "
                f"The final pipeline cleared {total_cleared:,} additional documents of all official failures while "
                f"remaining within the USD {_number(cost['approved_cap_usd']):.0f} provider cap. "
                "Three repeats apply only to the frozen 128-case-per-suite audit cohort."
            ),
        },
        {
            "id": "headline_metrics",
            "type": "metric-strip",
            "cardIds": ["corpus_card", "cleared_card", "cost_card", "elapsed_card"],
        },
        {
            "id": "finding_accuracy",
            "type": "markdown",
            "sourceId": "final_report",
            "body": (
                "## Selective recovery improved official document-level acceptance\n\n"
                "The chart reports absolute pass-rate gain with each benchmark's own fixed denominator. "
                "The accompanying table preserves exact baseline and final counts; it should be used for citation."
            ),
        },
        {"id": "accuracy_gain", "type": "chart", "chartId": "accuracy_gain_chart"},
        {"id": "accuracy_detail", "type": "table", "tableId": "accuracy_table"},
        {
            "id": "finding_selection",
            "type": "markdown",
            "sourceId": "final_report",
            "body": (
                "## Official evaluation controls alternate-model adoption\n\n"
                "PaddleOCR-VL and DeepSeek-OCR-2 outputs are candidates, not automatic replacements. "
                "A candidate is accepted only when official failures decrease without a new failure code or escalation; otherwise the baseline is restored."
            ),
        },
        {"id": "selection", "type": "chart", "chartId": "selection_chart"},
        {"id": "official_delta", "type": "table", "tableId": "official_delta_table"},
        {
            "id": "scope_definitions",
            "type": "markdown",
            "sourceId": "final_report",
            "body": (
                "## Scope, data, and metric definitions\n\n"
                "The full corpus contains OmniDocBench, ParseBench, and olmOCR-Bench under frozen revisions and one baseline inference pass. "
                "Document-level accuracy means the share of documents with zero official evaluator failures. "
                "Operational completion rate is not treated as benchmark accuracy."
            ),
        },
        {
            "id": "methodology",
            "type": "markdown",
            "sourceId": "final_report",
            "body": (
                "## Methodology and experimental design\n\n"
                "Documents are sharded independently across Pods. Terminal failures and repeated stalls are classified, quarantined when required, and retried on a different eligible Pod. "
                "Quality failures may be routed to alternate models. Predictions are frozen before official evaluation and every acceptance or rollback is recorded."
            ),
        },
        {
            "id": "finding_stability",
            "type": "markdown",
            "sourceId": "final_report",
            "body": (
                "## Three repeats quantify bounded audit variance\n\n"
                "Exactly three repeats cover 128 stratified cases per benchmark. "
                "The visual separates byte-identical Markdown stability from stable terminal status and does not imply three full-corpus executions."
            ),
        },
        {"id": "stability", "type": "chart", "chartId": "stability_chart"},
        {
            "id": "robustness",
            "type": "markdown",
            "sourceId": "final_report",
            "body": (
                "## Limitations, uncertainty, and robustness checks\n\n"
                "Live detection metrics primarily test frozen policy conformance and exact retry routing, not independent predictive generalization. "
                "Controlled fault injection and service-equivalence tests provide separate implementation evidence. "
                "External datasets, model revisions, and hardware classes require fresh evaluation."
            ),
        },
        {"id": "detection", "type": "table", "tableId": "detection_table"},
        {
            "id": "next_steps",
            "type": "markdown",
            "body": (
                "## Recommended next steps\n\n"
                "- Freeze the final evidence ZIP and retain its SHA-256 before drafting claims.\n"
                "- File or obtain patent-counsel guidance before any public paper disclosure.\n"
                "- Re-run the same scripts for any changed model, dataset revision, threshold, or evaluator."
            ),
        },
        {
            "id": "further_questions",
            "type": "markdown",
            "body": (
                "## Further questions\n\n"
                "How does recovery gain vary by page family and failure class? "
                "Which accepted routes remain stable on a held-out external corpus? "
                "What calibration strategy best bounds unresolved risk under production drift?"
            ),
        },
    ]
    return {
        "surface": "report",
        "manifest": {
            "version": 1,
            "surface": "report",
            "title": "FOLYNTA Public Benchmark Recovery Technical Report",
            "description": "Evidence-bound technical report for patent and paper review.",
            "generatedAt": created,
            "cards": cards,
            "charts": charts,
            "tables": tables,
            "sources": manifest_sources,
            "blocks": blocks,
        },
        "snapshot": {
            "version": 1,
            "generatedAt": created,
            "status": "ready",
            "datasets": {
                "headline_metrics": headline_rows,
                "accuracy": accuracy_chart_rows,
                "selection": selection,
                "stability": stability,
                "detection": detection_rows,
                "official_delta": official_delta,
            },
            "accessIssues": [],
        },
        "sources": sources,
    }


def _write_supporting_documents(
    *,
    root: Path,
    report: dict[str, Any],
    final_report_relative: str,
    patent_index_relative: str,
    service_evidence_relative: str,
) -> None:
    scope = report["scope"]
    (root / "README_KO.md").write_text(
        "\n".join(
            [
                "# FOLYNTA 특허·논문 증빙 자료",
                "",
                "이 디렉터리는 실제 최종 공개 벤치마크 결과에서 결정론적으로 생성되었습니다.",
                "AI 이미지 생성, 임의 수치, 고객·인증·성능 주장용 합성 증거를 포함하지 않습니다.",
                "",
                "## 구성",
                "",
                "- `patent/`: 흑백 특허 도면과 도면 설명 초안",
                "- `paper/`: 논문용 정적 그림, 기술 보고서 입력 JSON, 표·방법 자료",
                "- `data/`: 그림과 표를 재생성하는 원천 CSV",
                "- `reproducibility/`: 재생성 명령과 차트 계약",
                "- `artifact-provenance-manifest.json`: 모든 산출물의 SHA-256과 진실 등급",
                "",
                "법률 청구항이나 논문 결론은 전문가 검토 전 초안으로 취급해야 합니다.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "patent/PATENT_DRAWING_CAPTIONS_KO.md").write_text(
        "\n".join(
            [
                "# 특허 도면 설명 초안",
                "",
                "- 도 1: 문서 단위 분산 처리, 장애·품질 판별, 다른 Pod 재시도, 대체 모델 후보 생성, 공식 평가, 채택·롤백 및 증거 고정을 포함하는 선택 복구 시스템.",
                "- 도 2: 실행 상태에서 이상 판별, 반복 정지 격리, 다른 Pod 재시도, 공식 지표 비교, 채택·롤백·미해결 에스컬레이션으로 이어지는 상태 전이.",
                "- 도 3: 네 개 기본 샤드와 별도 복구 Pod의 실행 결과가 SHA-256 영수증, 비용 상한 및 자원 삭제 증거로 수렴하는 구조.",
                "",
                "도면은 기능 구조를 설명하는 T1 결정론적 도식입니다. 측정 수치는 논문 그림과 원천 CSV에서만 인용합니다.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "paper/PAPER_METHODS_AND_DISCLOSURE_NOTES_KO.md").write_text(
        "\n".join(
            [
                "# 논문 방법 및 공개 순서 메모",
                "",
                f"- 전체 공개 벤치마크 입력: {int(scope['full_corpus_input_count']):,}건",
                f"- 전체 코퍼스 반복: {int(scope['full_corpus_repeat_count'])}회",
                f"- 층화 표본: 벤치마크별 {int(scope['stratified_audit_input_count_per_suite'])}건",
                f"- 층화 표본 반복: 정확히 {int(scope['stratified_audit_repeat_count'])}회",
                f"- 총 표본 추론: {int(scope['stratified_audit_inference_count']):,}건",
                "",
                "특허 출원 전 논문·프리프린트·학회 발표·공개 저장소 게시 여부는 변리사와 먼저 검토합니다.",
                "결과를 인용할 때는 처리 성공률과 공식 벤치마크 정확도를 구분하고, 표본 3회 결과를 전체 코퍼스 3회 결과로 표현하지 않습니다.",
                "",
                "## 직접 근거",
                "",
                f"- 최종 보고서: `{final_report_relative}`",
                f"- 특허 증빙 인덱스: `{patent_index_relative}`",
                f"- 서비스 동등성 증빙: `{service_evidence_relative}`",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "reproducibility/REPRODUCE.md").write_text(
        "\n".join(
            [
                "# 재현 방법",
                "",
                "다음 생성기는 최종 보고서, 특허 인덱스, 서비스 복구 동등성 증빙이 모두 완결 상태일 때만 실행됩니다.",
                "",
                "```powershell",
                ".venv\\Scripts\\python.exe benchmark\\runpod_eval\\build_patent_paper_artifacts.py `",
                "  --repository-root . `",
                f"  --final-report {final_report_relative} `",
                f"  --patent-index {patent_index_relative} `",
                f"  --service-evidence {service_evidence_relative} `",
                "  --output-root benchmark\\reports\\generated\\folynta-patent-paper-artifacts-2026-08-05",
                "```",
                "",
                "SVG가 정본이며 PNG는 300dpi 검토용 파생본입니다. 생성 후 `artifact-provenance-manifest.json`의 SHA-256을 검증합니다.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _claim_evidence_rows(
    *,
    report: dict[str, Any],
    final_report_relative: str,
    patent_index_relative: str,
    service_evidence_relative: str,
) -> list[dict[str, Any]]:
    return [
        {
            "mapping_id": "M01",
            "draft_technical_concept": "Document-level parallel sharding with independent worker state",
            "technical_effect": "Horizontal throughput without shared GPU memory",
            "primary_evidence": final_report_relative,
            "evidence_pointer": "compute_configuration.pod_topology",
            "legal_status": "technical mapping only; counsel review required",
        },
        {
            "mapping_id": "M02",
            "draft_technical_concept": "Operational anomaly detection and repeated-stall quarantine",
            "technical_effect": "Prevents repeated routing to an unhealthy worker",
            "primary_evidence": final_report_relative,
            "evidence_pointer": "operational_fault_detection",
            "legal_status": "technical mapping only; counsel review required",
        },
        {
            "mapping_id": "M03",
            "draft_technical_concept": "Different-Pod retry with byte-identical model identity",
            "technical_effect": "Separates worker-local faults from model quality failures",
            "primary_evidence": patent_index_relative,
            "evidence_pointer": "technical_effect_matrix",
            "legal_status": "technical mapping only; counsel review required",
        },
        {
            "mapping_id": "M04",
            "draft_technical_concept": "Official-metric-gated alternate-model selection",
            "technical_effect": "Accepts only case-level improvements and reverts regressions",
            "primary_evidence": final_report_relative,
            "evidence_pointer": "selection and official_metrics",
            "legal_status": "technical mapping only; counsel review required",
        },
        {
            "mapping_id": "M05",
            "draft_technical_concept": "Service and benchmark recovery implementation equivalence",
            "technical_effect": "Binds research recovery behavior to service control paths",
            "primary_evidence": service_evidence_relative,
            "evidence_pointer": "source_fingerprints and fault_scenarios",
            "legal_status": "technical mapping only; counsel review required",
        },
        {
            "mapping_id": "M06",
            "draft_technical_concept": "Bounded three-repeat stratified variance audit",
            "technical_effect": "Quantifies repeat stability without tripling the full corpus",
            "primary_evidence": final_report_relative,
            "evidence_pointer": "three_repeat_variance_audit",
            "legal_status": "technical mapping only; counsel review required",
        },
        {
            "mapping_id": "M07",
            "draft_technical_concept": "Provider cost cap and verified resource cleanup gate",
            "technical_effect": "Cost-bounded execution with auditable terminal cleanup",
            "primary_evidence": final_report_relative,
            "evidence_pointer": "cost and evidence cleanup receipts",
            "legal_status": "technical mapping only; counsel review required",
        },
    ]


def build_artifacts(
    *,
    repository: Path,
    final_report_path: Path,
    patent_index_path: Path,
    service_evidence_path: Path,
    output_root: Path,
) -> dict[str, Any]:
    repository = repository.resolve()
    output_root = output_root.resolve()
    if output_root.exists():
        raise FileExistsError(f"patent/paper artifact root exists: {output_root}")
    report = _load(final_report_path)
    patent = _load(patent_index_path)
    service = _load(service_evidence_path)
    if (
        report.get("schema") != "folynta.public-benchmark-recovery-final-report.v1"
        or report.get("status") != "complete_and_officially_verified"
        or _integer(report.get("scope", {}).get("full_corpus_input_count")) != 5132
        or _integer(report.get("scope", {}).get("stratified_audit_repeat_count")) != 3
        or _integer(report.get("scope", {}).get("stratified_audit_inference_count")) != 1152
        or report.get("cost", {}).get("within_approved_cap") is not True
    ):
        raise ValueError("final benchmark report is not complete and publication-safe")
    if patent.get("schema") != "folynta.patent-technical-evidence-index.v1":
        raise ValueError("patent evidence index identity is invalid")
    if (
        service.get("schema") != "folynta.service-recovery-equivalence-evaluation.v1"
        or service.get("status") != "complete_service_recovery_equivalence_verified"
        or service.get("gate_passed") is not True
    ):
        raise ValueError("service recovery equivalence evidence is incomplete")

    accuracy = _accuracy_rows(report)
    selection = _selection_rows(report)
    stability = _stability_rows(report)
    detection = _detection_rows(report)
    official_delta = _official_delta_rows(report)
    final_relative = _relative(final_report_path, repository)
    patent_relative = _relative(patent_index_path, repository)
    service_relative = _relative(service_evidence_path, repository)

    output_root.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output_root.name}-", dir=output_root.parent))
    try:
        _write_csv(temporary / "data/benchmark-recovery-effects.csv", accuracy)
        _write_csv(temporary / "data/alternate-model-selection.csv", selection)
        _write_csv(temporary / "data/three-repeat-stability.csv", stability)
        _write_csv(
            temporary / "data/fault-detection-confusion-counts.csv",
            [
                {key: value for key, value in row.items() if not key.endswith("_text")}
                for row in detection
            ],
        )
        _write_csv(temporary / "data/official-metric-deltas.csv", official_delta)
        claim_rows = _claim_evidence_rows(
            report=report,
            final_report_relative=final_relative,
            patent_index_relative=patent_relative,
            service_evidence_relative=service_relative,
        )
        _write_csv(temporary / "patent/CLAIM_EVIDENCE_TECHNICAL_MAP.csv", claim_rows)

        figure_paths: list[tuple[str, str, list[Path], str]] = []
        for figure_id, stem, canvas, truth_class, alt_text in (
            (
                "FOL-PATENT-T1-FIG-001",
                "patent/figures/FIG-01-selective-recovery-system",
                _patent_architecture(),
                "T1",
                "System architecture from public inputs through selective recovery, official evaluation, evidence hashing, cost gate, and cleanup.",
            ),
            (
                "FOL-PATENT-T1-FIG-002",
                "patent/figures/FIG-02-fault-recovery-state-machine",
                _patent_state_machine(),
                "T1",
                "State machine from running through anomaly classification, quarantine, retry, official comparison, acceptance, rollback, or escalation.",
            ),
            (
                "FOL-PATENT-T1-FIG-003",
                "patent/figures/FIG-03-multipod-evidence-preservation",
                _patent_parallel_evidence(),
                "T1",
                "Four independent primary shards and recovery Pods converge through hashed evidence, billing, and verified deletion gates.",
            ),
            (
                "FOL-PAPER-T0-FIG-001",
                "paper/figures/FIG-01-zero-official-failure-rate",
                _accuracy_figure(accuracy),
                "T0",
                "Baseline and final percentages of documents with zero official failures for each public benchmark.",
            ),
            (
                "FOL-PAPER-T0-FIG-002",
                "paper/figures/FIG-02-alternate-model-selection",
                _selection_figure(selection),
                "T0",
                "Routed, accepted, and reverted candidate counts for PaddleOCR-VL and DeepSeek-OCR-2.",
            ),
            (
                "FOL-PAPER-T0-FIG-003",
                "paper/figures/FIG-03-three-repeat-stability",
                _stability_figure(stability),
                "T0",
                "Exact Markdown and terminal-status stability across three repeats of 128 cases per benchmark.",
            ),
            (
                "FOL-PAPER-T0-FIG-004",
                "paper/figures/FIG-04-fault-detection-confusion-matrices",
                _detection_figure(detection),
                "T0",
                "Confusion matrices for case routing, worker anomaly detection, and repeated-stall quarantine.",
            ),
            (
                "FOL-PAPER-T0-FIG-005",
                "paper/figures/FIG-05-campaign-cost-time",
                _cost_figure(report["cost"], report["timing"]),
                "T0",
                "Provider-derived campaign cost against the approved cap and elapsed wall time.",
            ),
        ):
            outputs = _save_figure(canvas, temporary / stem)
            figure_paths.append((figure_id, truth_class, outputs, alt_text))

        contracts = {
            "schema": "folynta.paper-chart-contracts.v1",
            "contracts": _chart_contracts(),
        }
        (temporary / "reproducibility/chart-contracts.json").parent.mkdir(
            parents=True, exist_ok=True
        )
        (temporary / "reproducibility/chart-contracts.json").write_text(
            json.dumps(contracts, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        paper_artifact = _paper_artifact(
            report=report,
            final_report_relative=final_relative,
            accuracy=accuracy,
            selection=selection,
            stability=stability,
            detection=detection,
            official_delta=official_delta,
        )
        paper_artifact_path = (
            temporary / "paper/FOLYNTA_PUBLIC_BENCHMARK_TECHNICAL_REPORT.artifact.json"
        )
        paper_artifact_path.parent.mkdir(parents=True, exist_ok=True)
        paper_artifact_path.write_text(
            json.dumps(paper_artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        _write_supporting_documents(
            root=temporary,
            report=report,
            final_report_relative=final_relative,
            patent_index_relative=patent_relative,
            service_evidence_relative=service_relative,
        )

        asset_records = []
        for figure_id, truth_class, paths, alt_text in figure_paths:
            asset_records.append(
                {
                    "id": figure_id,
                    "truth_class": truth_class,
                    "generated_with_ai": False,
                    "source_type": (
                        "deterministic-measured-evidence"
                        if truth_class == "T0"
                        else "deterministic-system-diagram"
                    ),
                    "source_evidence": [
                        final_relative,
                        patent_relative,
                        service_relative,
                    ],
                    "derivatives": [
                        {
                            "path": path.relative_to(temporary).as_posix(),
                            "sha256": _sha256(path),
                            "size_bytes": path.stat().st_size,
                        }
                        for path in paths
                    ],
                    "allowed_use": ["patent-review", "paper-review", "internal-research"],
                    "prohibited_use": [
                        "customer-claim-without-review",
                        "certification-claim",
                        "altered-metric-claim",
                    ],
                    "alt_text_en": alt_text,
                }
            )
        all_files = sorted(
            path
            for path in temporary.rglob("*")
            if path.is_file() and path.name != "artifact-provenance-manifest.json"
        )
        manifest: dict[str, Any] = {
            "schema": "folynta.patent-paper-artifact-manifest.v1",
            "status": "complete_real_evidence_only",
            "generated_at_utc": report["created_at_utc"],
            "truth_policy": {
                "measured_figures": "T0 deterministic derivatives of final evidence",
                "system_drawings": "T1 deterministic diagrams of implemented control flow",
                "image_generation_used": False,
                "fabricated_metrics_allowed": False,
            },
            "source_chain": [
                {"path": final_relative, "sha256": _sha256(final_report_path)},
                {"path": patent_relative, "sha256": _sha256(patent_index_path)},
                {"path": service_relative, "sha256": _sha256(service_evidence_path)},
            ],
            "assets": asset_records,
            "file_inventory": [
                {
                    "path": path.relative_to(temporary).as_posix(),
                    "sha256": _sha256(path),
                    "size_bytes": path.stat().st_size,
                }
                for path in all_files
            ],
            "publication_boundary": (
                "Patent counsel review should precede public paper disclosure; this "
                "package is technical evidence, not legal advice or a filed claim set."
            ),
        }
        manifest["receipt_sha256"] = _receipt_sha256(manifest)
        manifest_path = temporary / "artifact-provenance-manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.rename(output_root)
        return manifest
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--final-report", type=Path, required=True)
    parser.add_argument("--patent-index", type=Path, required=True)
    parser.add_argument("--service-evidence", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = build_artifacts(
        repository=args.repository_root.resolve(),
        final_report_path=args.final_report.resolve(),
        patent_index_path=args.patent_index.resolve(),
        service_evidence_path=args.service_evidence.resolve(),
        output_root=args.output_root.resolve(),
    )
    print(
        json.dumps(
            {
                "asset_count": len(manifest["assets"]),
                "file_count": len(manifest["file_inventory"]),
                "receipt_sha256": manifest["receipt_sha256"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_artifacts"]
