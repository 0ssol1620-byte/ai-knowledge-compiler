"""Regenerate `figures/` from `metrics/`. Hand-rolled SVG, no plotting dependency.

    .venv/Scripts/python.exe research/experiments/EXP-0101/scripts/make_figures.py

Two figures, chosen because they are the two the result turns on: what the
challenger cost on the high-risk set, and whether what it bought on the layout
set survives counting abstentions as invalidations.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

EXPERIMENT = Path(__file__).resolve().parents[1]

ARM_ORDER = (
    "current",
    "baseline",
    "challenger",
    "challenger_no_spatial",
    "challenger_no_type_reasoning",
    "challenger_no_content",
)

_INK = "#1b1b1f"
_MUTED = "#6b6b76"
_GRID = "#d8d8de"
_SERIES = ("#2f6f4f", "#8a3324")


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _load(name: str) -> Any:
    return json.loads((EXPERIMENT / "metrics" / name).read_text(encoding="utf-8"))


#: Stamped into every figure. A figure is the artifact most likely to end up in
#: a slide with its provenance stripped, so the restriction is drawn into the
#: image rather than kept beside it.
_DISCLOSURE = "NOT CLEARED FOR EXTERNAL DISCLOSURE — internal exploratory result"


def _stamp(width: int, height: int) -> str:
    return (
        f'<text x="{width - 12}" y="{height - 10}" font-size="9" '
        f'text-anchor="end" fill="#8a3324">{_DISCLOSURE}</text>'
    )


def _write(name: str, body: str) -> None:
    path = EXPERIMENT / "figures" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def grouped_bars(
    summary: dict[str, Any],
    *,
    keys: tuple[tuple[str, str], ...],
    title: str,
    filename: str,
) -> None:
    width, height = 900, 420
    left, right, top, bottom = 60, 250, 56, 92
    plot_width = width - left - right
    plot_height = height - top - bottom
    group_width = plot_width / len(ARM_ORDER)
    bar_width = group_width / (len(keys) + 1)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}" font-family="Inter, system-ui, sans-serif">',
        f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
        f'<text x="{left}" y="28" font-size="16" font-weight="600" fill="{_INK}">'
        f"{_escape(title)}</text>",
        f'<text x="{left}" y="46" font-size="11" fill="{_MUTED}">'
        "Generated from metrics/summary.json. Rates in [0, 1]; higher is better for "
        "recall, lower for invalidation.</text>",
    ]

    for step in range(6):
        value = step / 5
        y = top + plot_height * (1 - value)
        parts.append(
            f'<line x1="{left}" y1="{y:.1f}" x2="{left + plot_width}" y2="{y:.1f}" '
            f'stroke="{_GRID}" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{left - 8}" y="{y + 4:.1f}" font-size="10" text-anchor="end" '
            f'fill="{_MUTED}">{value:.1f}</text>'
        )

    for index, arm in enumerate(ARM_ORDER):
        base = left + index * group_width
        for series, (key, _label) in enumerate(keys):
            record = summary[arm][key]
            value = record["value"] if isinstance(record, dict) else record
            if value is None:
                continue
            bar_height = plot_height * value
            x = base + bar_width * (series + 0.5)
            y = top + plot_height - bar_height
            parts.append(
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_width:.1f}" '
                f'height="{bar_height:.1f}" fill="{_SERIES[series]}"/>'
            )
            parts.append(
                f'<text x="{x + bar_width / 2:.1f}" y="{y - 4:.1f}" font-size="9" '
                f'text-anchor="middle" fill="{_INK}">{value:.3f}</text>'
            )
        label = arm.replace("challenger_", "chal-").replace("_", " ")
        parts.append(
            f'<text x="{base + group_width / 2:.1f}" y="{top + plot_height + 16}" '
            f'font-size="10" text-anchor="middle" fill="{_INK}" '
            f'transform="rotate(-18 {base + group_width / 2:.1f} '
            f'{top + plot_height + 16})">{_escape(label)}</text>'
        )

    legend_x = left + plot_width + 24
    for series, (key, label) in enumerate(keys):
        y = top + 8 + series * 22
        parts.append(
            f'<rect x="{legend_x}" y="{y - 10}" width="12" height="12" '
            f'fill="{_SERIES[series]}"/>'
        )
        parts.append(
            f'<text x="{legend_x + 18}" y="{y}" font-size="11" fill="{_INK}">'
            f"{_escape(label)}</text>"
        )
        denominator = summary[ARM_ORDER[0]][key]
        if isinstance(denominator, dict):
            parts.append(
                f'<text x="{legend_x + 18}" y="{y + 13}" font-size="9" fill="{_MUTED}">'
                f"n = {denominator['denominator']} ({_escape(denominator['population'])})"
                "</text>"
            )
    parts.append(_stamp(width, height))
    parts.append("</svg>")
    _write(filename, "\n".join(parts) + "\n")


def per_class_grid(per_mutation: dict[str, Any], *, filename: str) -> None:
    classes = sorted(per_mutation[ARM_ORDER[0]])
    cell_width, cell_height = 104, 30
    left, top = 230, 96
    width = left + cell_width * len(ARM_ORDER) + 24
    height = top + cell_height * len(classes) + 40

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}" font-family="Inter, system-ui, sans-serif">',
        f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
        f'<text x="24" y="30" font-size="16" font-weight="600" fill="{_INK}">'
        "Semantic-change recall by mutation class</text>",
        f'<text x="24" y="50" font-size="11" fill="{_MUTED}">'
        "Generated from metrics/per-mutation-class.json. Blank = the class has no "
        "gold semantic change, so recall is undefined rather than zero.</text>",
    ]
    for index, arm in enumerate(ARM_ORDER):
        x = left + index * cell_width + cell_width / 2
        label = arm.replace("challenger_", "chal-").replace("_", " ")
        parts.append(
            f'<text x="{x}" y="{top - 10}" font-size="10" text-anchor="middle" '
            f'fill="{_INK}" transform="rotate(-20 {x} {top - 10})">'
            f"{_escape(label)}</text>"
        )

    for row, mutation in enumerate(classes):
        y = top + row * cell_height
        parts.append(
            f'<text x="{left - 12}" y="{y + 19}" font-size="11" text-anchor="end" '
            f'fill="{_INK}">{_escape(mutation)}</text>'
        )
        for column, arm in enumerate(ARM_ORDER):
            record = per_mutation[arm][mutation]["semantic_change_recall"]
            value = record["value"]
            x = left + column * cell_width
            if value is None:
                fill = "#f2f2f4"
                text = ""
            else:
                shade = int(255 - 120 * value)
                fill = f"rgb({shade},{min(255, shade + 40)},{shade})"
                text = f"{value:.2f}"
            parts.append(
                f'<rect x="{x}" y="{y}" width="{cell_width - 3}" '
                f'height="{cell_height - 3}" fill="{fill}" stroke="{_GRID}"/>'
            )
            if text:
                parts.append(
                    f'<text x="{x + (cell_width - 3) / 2}" y="{y + 19}" font-size="11" '
                    f'text-anchor="middle" fill="{_INK}">{text}</text>'
                )
    parts.append(_stamp(width, height))
    parts.append("</svg>")
    _write(filename, "\n".join(parts) + "\n")


def main() -> int:
    summary = _load("summary.json")
    grouped_bars(
        summary,
        keys=(
            ("critical_change_recall", "Critical change recall"),
            ("layout_only_false_invalidation_rate", "Layout-only false invalidation"),
        ),
        title="What the challenger cost and what it bought",
        filename="critical-vs-layout.svg",
    )
    grouped_bars(
        summary,
        keys=(
            ("layout_only_false_positive_rate", "Layout-only false positive"),
            ("layout_only_unresolved_rate", "Layout-only unresolved"),
        ),
        title="The layout-only gain, split into its two halves",
        filename="layout-split.svg",
    )
    per_class_grid(_load("per-mutation-class.json"), filename="per-class-recall.svg")
    print("figures written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
