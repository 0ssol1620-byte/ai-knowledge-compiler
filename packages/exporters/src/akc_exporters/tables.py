"""Loss-aware deterministic table assets."""

from __future__ import annotations

import csv
import html
import io

from akc_cir import CanonicalCell, CanonicalTable
from akc_security import escape_csv_formula, sanitize_table_html


def _grid(table: CanonicalTable) -> list[list[str]]:
    rows = [["" for _ in range(table.column_count)] for _ in range(table.row_count)]
    for cell in sorted(
        table.cells, key=lambda item: (item.row_index0, item.column_index0, item.id)
    ):
        rows[cell.row_index0][cell.column_index0] = cell.normalized_text or cell.raw_text
    return rows


def table_to_gfm(table: CanonicalTable) -> str:
    if not table.is_simple_gfm:
        raise ValueError("merged-cell table cannot be represented losslessly as GFM")
    rows = _grid(table)
    header_rows = max(1, table.header_row_count)
    header = rows[0]
    body = rows[header_rows:]

    def row(values: list[str]) -> str:
        escaped = [
            value.replace("\\", "\\\\").replace("|", "\\|").replace("\n", "&#10;")
            for value in values
        ]
        return "| " + " | ".join(escaped) + " |"

    lines = [row(header), "| " + " | ".join("---" for _ in header) + " |"]
    lines.extend(row(values) for values in body)
    return "\n".join(lines)


def table_to_csv(table: CanonicalTable) -> str:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    for row in _grid(table):
        writer.writerow([escape_csv_formula(value) for value in row])
    return output.getvalue()


def table_to_html(table: CanonicalTable) -> str:
    cells_by_row: dict[int, list[CanonicalCell]] = {}
    for cell in table.cells:
        cells_by_row.setdefault(cell.row_index0, []).append(cell)
    lines = ["<table>"]
    if table.caption:
        lines.append(f"<caption>{html.escape(table.caption)}</caption>")
    if table.header_row_count:
        lines.append("<thead>")
    for row_index in range(table.row_count):
        if row_index == table.header_row_count and table.header_row_count:
            lines.extend(["</thead>", "<tbody>"])
        lines.append("<tr>")
        for cell in sorted(
            cells_by_row.get(row_index, []),
            key=lambda item: (item.column_index0, item.id),
        ):
            tag = "th" if row_index < table.header_row_count else "td"
            attrs = ""
            if cell.row_span > 1:
                attrs += f' rowspan="{cell.row_span}"'
            if cell.column_span > 1:
                attrs += f' colspan="{cell.column_span}"'
            if tag == "th":
                attrs += ' scope="col"'
            text = html.escape(cell.normalized_text or cell.raw_text).replace("\n", "<br>")
            lines.append(f"<{tag}{attrs}>{text}</{tag}>")
        lines.append("</tr>")
    if table.header_row_count == table.row_count:
        lines.append("</thead>")
    elif table.header_row_count:
        lines.append("</tbody>")
    lines.append("</table>")
    return sanitize_table_html("\n".join(lines))
