"""Bounded, deterministic CSV parsing. Every field is text; nothing is evaluated."""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Iterable
from dataclasses import dataclass

from .models import (
    CirBuilder,
    ParserLimits,
    SourceLocation,
    StructuredParseError,
    TableCellSpec,
    normalize_text,
)

# One fixed RFC 4180 dialect. The delimiter is never sniffed: guessing a
# dialect is an inference about the source, and a wrong guess silently
# reshapes every row.
_DELIMITER = ","
_QUOTE_CHAR = '"'
# Leading characters a spreadsheet application may evaluate. The text is kept
# verbatim and only flagged; escaping belongs to an export, not to the CIR.
_FORMULA_PREFIXES = frozenset({"=", "+", "-", "@"})
_STDLIB_FIELD_LIMIT_MESSAGE = "field larger than field limit"

# Preflight scanner states. They are the strict stdlib reader's own states for
# this dialect (no escape character, no initial-space skipping), so records
# and fields end exactly where csv.reader will end them.
_START_RECORD = 0
_START_FIELD = 1
_IN_FIELD = 2
_IN_QUOTED_FIELD = 3
_QUOTE_IN_QUOTED_FIELD = 4
_EAT_LF = 5
_LINE_BREAKS = frozenset({"\r", "\n"})
# Field text the scanner counts without visiting each character, written for
# the fixed dialect above. An unquoted run stops at a delimiter or line break;
# a quote inside it is literal. A quoted run stops at the first quote that is
# not half of a doubled quote.
_UNQUOTED_RUN = re.compile("[^,\r\n]*")
_QUOTED_RUN = re.compile('[^"]*(?:""[^"]*)*')


@dataclass(frozen=True, slots=True)
class CsvPreflight:
    """What the bounded scan counted. No field or record text is kept."""

    record_count: int
    field_count: int
    widest_record: int
    longest_field: int
    # The scan reached text the strict reader rejects: a character after a
    # closing quote, or a quote never closed. It stops there and leaves the
    # verdict to csv.reader.
    stopped_at_syntax_error: bool


def preflight_csv(chunks: Iterable[str], limits: ParserLimits) -> CsvPreflight:
    """Enforce the CSV bounds on a scan of the text, before csv.reader builds anything.

    csv.reader materializes a whole record as a list of field strings before
    its caller can count it, so one line of delimiters, or one enormous quoted
    field, is allocated in full before any bound is checked. This scan follows
    the same strict dialect without keeping any text, and raises a bound's
    error at the first character that crosses it. ``chunks`` may split the text
    anywhere, including inside a CRLF or a doubled quote; nothing after the
    chunk that crosses a bound is read.
    """
    scan = _PreflightScan(limits)
    for chunk in chunks:
        if not scan.feed(chunk):
            return scan.result(stopped_at_syntax_error=True)
    return scan.finish()


@dataclass(slots=True)
class _PreflightScan:
    limits: ParserLimits
    state: int = _START_RECORD
    record_count: int = 0
    field_count: int = 0
    record_width: int = 0
    widest_record: int = 0
    field_chars: int = 0
    longest_field: int = 0

    def feed(self, chunk: str) -> bool:
        """Scan one chunk. False once the text is something strict reading rejects."""
        pos = 0
        end = len(chunk)
        while pos < end:
            state = self.state
            if state == _IN_FIELD:
                pos = self._count_run(_UNQUOTED_RUN, chunk, pos, end, quoted=False)
                if pos < end:
                    # The run stopped at a delimiter or a line break.
                    self._end_field(chunk[pos])
                    pos += 1
                continue
            if state == _IN_QUOTED_FIELD:
                pos = self._count_run(_QUOTED_RUN, chunk, pos, end, quoted=True)
                if pos < end:
                    # A quote. Whether it closes the field or opens a doubled
                    # quote is decided by the character after it, which may be
                    # in the next chunk.
                    self.state = _QUOTE_IN_QUOTED_FIELD
                    pos += 1
                continue
            char = chunk[pos]
            pos += 1
            if state == _EAT_LF:
                # CRLF is one line break; a lone CR already ended its record.
                state = self.state = _START_RECORD
                if char == "\n":
                    continue
            if state == _START_RECORD:
                self._start_record()
                if char in _LINE_BREAKS:
                    # A blank line is a record with no fields.
                    self._end_record(char)
                    continue
                self._start_field()
                state = _START_FIELD
            if state == _START_FIELD:
                # A quote is special only as the first character of a field.
                if char == _QUOTE_CHAR:
                    self.state = _IN_QUOTED_FIELD
                elif char == _DELIMITER or char in _LINE_BREAKS:
                    self._end_field(char)
                else:
                    self._add_chars(1)
                    self.state = _IN_FIELD
            # _QUOTE_IN_QUOTED_FIELD: the previous character was a quote.
            elif char == _QUOTE_CHAR:
                self._add_chars(1)
                self.state = _IN_QUOTED_FIELD
            elif char == _DELIMITER or char in _LINE_BREAKS:
                self._end_field(char)
            else:
                # strict=True rejects any other character after a closing quote.
                return False
        return True

    def finish(self) -> CsvPreflight:
        if self.state == _IN_QUOTED_FIELD:
            # Strict reading ends a never-closed quote in "unexpected end of data".
            return self.result(stopped_at_syntax_error=True)
        if self.state in (_START_FIELD, _IN_FIELD, _QUOTE_IN_QUOTED_FIELD):
            # The last record has no line break; the end of the text closes it.
            self._end_field("\n")
        return self.result(stopped_at_syntax_error=False)

    def result(self, *, stopped_at_syntax_error: bool) -> CsvPreflight:
        return CsvPreflight(
            record_count=self.record_count,
            field_count=self.field_count,
            widest_record=self.widest_record,
            longest_field=self.longest_field,
            stopped_at_syntax_error=stopped_at_syntax_error,
        )

    def _start_record(self) -> None:
        if self.record_count >= self.limits.max_csv_rows:
            raise StructuredParseError("CSV_ROW_LIMIT")
        self.record_count += 1
        self.record_width = 0

    def _start_field(self) -> None:
        # A field exists from its first character or from the delimiter before
        # it, so a record of bare delimiters is refused at the first one too
        # many. Empty fields count, as they do after reading.
        self.record_width += 1
        if self.record_width > self.limits.max_csv_columns:
            raise StructuredParseError("CSV_COLUMN_LIMIT")
        self.field_count += 1
        if self.field_count > self.limits.max_csv_cells:
            raise StructuredParseError("CSV_CELL_LIMIT")
        self.field_chars = 0

    def _end_field(self, char: str) -> None:
        """Close the open field at a delimiter or a line break."""
        self.longest_field = max(self.longest_field, self.field_chars)
        if char == _DELIMITER:
            self._start_field()
            self.state = _START_FIELD
        else:
            self._end_record(char)

    def _end_record(self, line_break: str) -> None:
        self.widest_record = max(self.widest_record, self.record_width)
        self.state = _EAT_LF if line_break == "\r" else _START_RECORD

    def _add_chars(self, count: int) -> None:
        self.field_chars += count
        if self.field_chars > self.limits.max_csv_field_chars:
            raise StructuredParseError("CSV_FIELD_LIMIT")

    def _count_run(
        self,
        run: re.Pattern[str],
        chunk: str,
        pos: int,
        end: int,
        *,
        quoted: bool,
    ) -> int:
        """Count field text from ``pos`` to the next character the states must see.

        The search stops one field character past what the field may still
        hold (two source characters per doubled quote), so an oversized field
        is refused without scanning the rest of it. A run that is not refused
        therefore ends at ``end`` or at a delimiter, line break or quote.
        """
        room = self.limits.max_csv_field_chars - self.field_chars + 1
        stop = min(end, pos + (2 * room if quoted else room))
        match = run.match(chunk, pos, stop)
        if match is None:  # pragma: no cover - both runs match the empty string.
            raise StructuredParseError("CSV_PARSE_FAILED")
        run_end = match.end()
        count = run_end - pos
        if quoted:
            # Inside a quoted run every quote is half of a doubled quote, and
            # a doubled quote is one character of the field.
            count -= chunk.count(_QUOTE_CHAR * 2, pos, run_end)
        self._add_chars(count)
        return run_end


def parse_csv(text: str, builder: CirBuilder) -> str:
    limits = builder.limits
    # Every bound is enforced before the reader allocates a single record. A
    # syntax error the scan stops at is left to the strict reader, which
    # reports it as CSV_MALFORMED below.
    preflight_csv((text,), limits)
    reader = csv.reader(
        io.StringIO(text, newline=""),
        delimiter=_DELIMITER,
        quotechar=_QUOTE_CHAR,
        doublequote=True,
        skipinitialspace=False,
        strict=True,
    )

    specs: list[TableCellSpec] = []
    record_count = 0
    column_count = 0
    # Every parsed field counts toward the cell bound, empty or not: the work
    # is done per field, and an empty field still occupies a grid position.
    field_count = 0
    record_widths: set[int] = set()
    formula_prefixed = False
    # The preflight has already enforced these bounds; they are checked again
    # on what the reader actually produced.
    try:
        for record_index0, record in enumerate(reader):
            if record_index0 >= limits.max_csv_rows:
                raise StructuredParseError("CSV_ROW_LIMIT")
            if len(record) > limits.max_csv_columns:
                raise StructuredParseError("CSV_COLUMN_LIMIT")
            field_count += len(record)
            if field_count > limits.max_csv_cells:
                raise StructuredParseError("CSV_CELL_LIMIT")
            record_count = record_index0 + 1
            if record:
                record_widths.add(len(record))
            # The widest record sets the grid, so trailing empty fields keep
            # their columns even though they produce no cell.
            column_count = max(column_count, len(record))
            for column_index0, field in enumerate(record):
                if len(field) > limits.max_csv_field_chars:
                    raise StructuredParseError("CSV_FIELD_LIMIT")
                if field == "":
                    continue
                quality_flags: list[str] = []
                if _has_formula_prefix(field):
                    formula_prefixed = True
                    quality_flags.append("spreadsheet_formula_prefix_preserved_as_text")
                if normalize_text(field) != field:
                    quality_flags.append("csv_field_whitespace_normalized")
                coordinate = f"{_column_letter(column_index0 + 1)}{record_index0 + 1}"
                specs.append(
                    TableCellSpec(
                        row_index0=record_index0,
                        column_index0=column_index0,
                        raw_text=field,
                        location=SourceLocation(
                            page_index0=0,
                            native_object_id=f"csv/row/{record_index0:06d}/cell/{coordinate}",
                        ),
                        quality_flags=tuple(quality_flags),
                        # The field as the reader produced it: surrounding
                        # whitespace, embedded CRLF and Unicode composition are
                        # source facts. Only normalized_text is normalized.
                        preserve_raw_text=True,
                        value_type="string",
                    )
                )
    except csv.Error as exc:
        if _STDLIB_FIELD_LIMIT_MESSAGE in str(exc):
            raise StructuredParseError("CSV_FIELD_LIMIT") from exc
        raise StructuredParseError("CSV_MALFORMED") from exc

    if not specs:
        raise StructuredParseError("CSV_EMPTY_DOCUMENT")

    # Trailing records that hold no field add no rows to the grid.
    row_count = max(spec.row_index0 for spec in specs) + 1
    table_flags = ["csv_header_not_declared"]
    if len(record_widths) > 1:
        table_flags.append("csv_ragged_records")
    if formula_prefixed:
        builder.add_warning("csv_formula_prefixed_text_not_executed")

    range_ref = f"A1:{_column_letter(column_count)}{row_count}"
    builder.add_table(
        location=SourceLocation(
            page_index0=0,
            native_object_id=f"csv/table/range/{range_ref}",
        ),
        row_count=row_count,
        column_count=column_count,
        cells=tuple(specs),
        header_row_count=0,
        quality_flags=tuple(table_flags),
    )
    builder.metadata["csv"] = {
        "dialect": {
            "delimiter": _DELIMITER,
            "quoteChar": _QUOTE_CHAR,
            "doubleQuote": True,
            "strict": True,
        },
        "encoding": "utf-8",
        "recordCount": record_count,
        "rowCount": row_count,
        "columnCount": column_count,
        "cellCount": len(specs),
        "range": range_ref,
        "recordWidths": sorted(record_widths),
    }
    return _filename_title(builder.source_filename)


def _has_formula_prefix(field: str) -> bool:
    stripped = field.lstrip()
    return bool(stripped) and stripped[0] in _FORMULA_PREFIXES


def _column_letter(column1: int) -> str:
    letters: list[str] = []
    remaining = column1
    while remaining > 0:
        remaining, offset = divmod(remaining - 1, 26)
        letters.append(chr(ord("A") + offset))
    return "".join(reversed(letters))


def _filename_title(filename: str) -> str:
    return normalize_text(filename.rsplit(".", 1)[0].replace("_", " ")) or "Table"
