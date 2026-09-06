"""Source-native property/value extraction — the acquisition-side predicate.

The frozen scorer judges *answers* and is not touched. This module decides which
candidates may become questions at all, which is a different job and is why it
is a different file. It reads a source's own structure — a table's row label and
column header, a definition list's term, an infobox key — and reports the value
that structure binds to that label. It never invents a property.

Strictness is deliberate and one-directional. Every rule here can only refuse a
candidate, never manufacture one:

- a cell must hold exactly one value-like token, so "between 5m and 10m" is not
  a value;
- both revisions must bind the *same* label, so a renamed option is out;
- both values must be the same kind, so a version becoming a date is out;
- the label must be readable without reading the value, so the answer cannot
  leak into the question;
- the surrounding evidence atom must carry no other changed value, so a correct
  answer cannot be produced by reciting a neighbour.

``value_tokens`` and ``normalise`` are imported from the frozen scorer rather
than reimplemented. If the two ever disagreed about what a value is, the cohort
would be selected under one definition and judged under another.
"""

from __future__ import annotations

import hashlib
import json
import re
from html.parser import HTMLParser
from typing import Any, Iterator

from value_scorer import _VALUE_PATTERNS, normalise, value_tokens

#: The frozen scorer's value kinds, named. Nothing is added to this list here:
#: a kind that the scorer cannot see is a kind that cannot be scored.
ISO_DATE = "iso_date"
NUMERIC = "numeric"
VERSION_CHAIN = "version_chain"
PERCENTAGE = "percentage"
CURRENCY = "currency"
IDENTIFIER = "identifier"

VALUE_KINDS = (ISO_DATE, VERSION_CHAIN, PERCENTAGE, CURRENCY, NUMERIC, IDENTIFIER)

_KIND_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (ISO_DATE, re.compile(r"^\d{4}-\d{2}-\d{2}$")),
    (PERCENTAGE, re.compile(r"^\d[\d,]*\.?\d*\s?%$")),
    (CURRENCY, re.compile(r"^[$€£¥]\s?\d[\d,]*(?:\.\d+)?$")),
    (VERSION_CHAIN, re.compile(r"^\d+(?:\.\d+){2,3}$")),
    (NUMERIC, re.compile(r"^\d+(?:\.\d+)?$")),
    (IDENTIFIER, re.compile(r"^[A-Za-z]+[-_]?\d[\w.-]*$")),
)

#: The property shapes this study will read, declared before acquisition. A shape
#: that is not on this list is not extracted, however tempting the source looks:
#: adding one after seeing which sources yield would make the taxonomy an
#: outcome. Each entry names where the *label* comes from, because a label read
#: from anywhere but source structure is a label this study invented.
PROPERTY_TAXONOMY: tuple[dict[str, str], ...] = (
    {
        "shape": "table_row_by_column",
        "label_from": "the first cell of the row, under the named column header",
        "grammars": "markdown pipe tables, HTML tables with a header row",
        "example": "a CLI flag's Default column",
    },
    {
        "shape": "key_value_row",
        "label_from": "the row's th, with the value in the td beside it",
        "grammars": "HTML infobox and definition tables",
        "example": "an encyclopedia infobox key",
    },
)

#: Exclusion codes. They are the acquisition vocabulary, not the scorer's.
NO_VALUE_FACT = "NO_VALUE_FACT"
AMBIGUOUS_VALUE_FACT = "AMBIGUOUS_VALUE_FACT"
PROPERTY_NOT_STABLE = "PROPERTY_NOT_STABLE"
VALUE_UNCHANGED = "VALUE_UNCHANGED"
VALUE_KIND_MISMATCH = "VALUE_KIND_MISMATCH"
LABEL_READS_THE_VALUE = "LABEL_READS_THE_VALUE"

#: A label must be a label. These bounds refuse a whole sentence masquerading as
#: a key, which is how a property label starts smuggling the answer.
_LABEL_MIN_CHARS = 2
_LABEL_MAX_CHARS = 80


def _spans(text: str) -> list[tuple[int, int, str]]:
    """Every scorer-pattern match with its position in the normalised text."""
    normalised = normalise(text)
    found: list[tuple[int, int, str]] = []
    for pattern in _VALUE_PATTERNS:
        for match in pattern.finditer(normalised):
            token = match.group(0).strip()
            if token:
                found.append((match.start(), match.end(), token))
    return found


def dominant_tokens(text: str) -> set[str]:
    """The scorer's tokens with the ones nested inside a longer match removed.

    The scorer's patterns overlap on purpose: ``2.14.1`` matches the version
    chain *and*, inside it, the plain number ``2.14``. For judging an answer
    that redundancy is harmless — every one of those tokens is current-only, so
    a hit is a hit. For *selecting* a candidate it is fatal, because a cell
    holding one version would look like a cell holding two values and no
    version-chain property could ever become a question.

    Dominance is decided by span containment, never by string containment: in
    "5 to 15" the token ``5`` is a substring of ``15`` but occupies its own
    position, so both survive and the cell is correctly refused as holding two
    values.
    """
    spans = _spans(text)
    return {
        token
        for start, end, token in spans
        if not any(
            other_start <= start and other_end >= end and (other_end - other_start) > (end - start)
            for other_start, other_end, _ in spans
        )
    }


def value_kind(text: str) -> str | None:
    """The kind of a cell that holds exactly one value, else ``None``.

    "5m" yields ``numeric`` from the token ``5``; "between 5 and 10" yields
    nothing, because two tokens mean the cell does not bind one value.
    """
    tokens = dominant_tokens(text)
    if len(tokens) != 1:
        return None
    token = next(iter(tokens))
    for kind, pattern in _KIND_PATTERNS:
        if pattern.match(token):
            return kind
    return None


def sole_value(text: str) -> tuple[str, str] | None:
    """``(kind, normalised token)`` for a cell binding exactly one value."""
    kind = value_kind(text)
    if kind is None:
        return None
    return kind, next(iter(dominant_tokens(text)))


def contrast(current_text: str, superseded_text: str) -> dict[str, Any]:
    """The scorer's marker construction, over dominant tokens.

    Same shape as ``value_scorer.markers`` and same direction; it differs only
    in reading nested matches as one value. The scorer itself is untouched.
    """
    current = dominant_tokens(current_text)
    superseded = dominant_tokens(superseded_text)
    only_current = sorted(current - superseded)
    only_superseded = sorted(superseded - current)
    return {
        "current": only_current,
        "superseded": only_superseded,
        "distinguishable": bool(only_current) and bool(only_superseded),
    }


def label_is_usable(label: str) -> bool:
    """A label that contains a value can carry the answer into the question."""
    stripped = label.strip()
    if not (_LABEL_MIN_CHARS <= len(stripped) <= _LABEL_MAX_CHARS):
        return False
    return not value_tokens(stripped)


def property_id(document_id: str, heading_path: list[str], row: str, column: str) -> str:
    """Stable across revisions, and injective where an anchor path is not.

    The row ordinal is deliberately absent. Rows move between revisions, and a
    property that changes identity when a row is inserted above it is not a
    stable property.
    """
    blob = json.dumps(
        {
            "document_id": document_id,
            "heading_path": [normalise(part) for part in heading_path],
            "row": normalise(row),
            "column": normalise(column),
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return "prop:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


# --- source-native table reading ----------------------------------------------


def _cells(line: str) -> list[str]:
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|"):
        body = body[:-1]
    return [cell.strip() for cell in body.split("|")]


_SEPARATOR = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
_HEADING = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")


def markdown_tables(raw: str) -> Iterator[dict[str, Any]]:
    """Pipe tables, with the heading path they sit under.

    Markdown's table is the clearest source-native key/value structure there is:
    the header row names the columns and the first cell of each row names the
    thing. Neither is inferred.
    """
    lines = raw.splitlines()
    heading: list[str] = []
    index = 0
    while index < len(lines):
        match = _HEADING.match(lines[index])
        if match:
            depth = len(match.group(1))
            heading = heading[: depth - 1] + [match.group(2)]
            index += 1
            continue
        if (
            "|" in lines[index]
            and index + 1 < len(lines)
            and _SEPARATOR.match(lines[index + 1])
        ):
            header = _cells(lines[index])
            rows: list[list[str]] = []
            cursor = index + 2
            while cursor < len(lines) and "|" in lines[cursor] and lines[cursor].strip():
                cells = _cells(lines[cursor])
                if len(cells) == len(header):
                    rows.append(cells)
                cursor += 1
            if rows:
                yield {"heading_path": list(heading), "header": header, "rows": rows}
            index = cursor
            continue
        index += 1


class _TableReader(HTMLParser):
    """``<table>`` and infobox-shaped ``<tr><th>key</th><td>value</td></tr>``."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[dict[str, Any]] = []
        self.heading: list[str] = []
        self._heading_depth: int | None = None
        self._buffer: list[str] = []
        self._row: list[str] = []
        self._row_kinds: list[str] = []
        self._rows: list[list[str]] = []
        self._row_kind_rows: list[list[str]] = []
        self._depth = 0
        self._heading_stack: list[str] = []

    # heading path -------------------------------------------------------
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._heading_depth = int(tag[1])
            self._buffer = []
        elif tag == "table":
            self._depth += 1
            self._rows = []
            self._row_kind_rows = []
        elif tag == "tr" and self._depth:
            self._row = []
            self._row_kinds = []
        elif tag in ("td", "th") and self._depth:
            self._buffer = []

    def handle_endtag(self, tag: str) -> None:
        text = " ".join("".join(self._buffer).split())
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6") and self._heading_depth:
            depth = self._heading_depth
            self._heading_stack = self._heading_stack[: depth - 1] + [text]
            self._heading_depth = None
            self._buffer = []
        elif tag in ("td", "th") and self._depth:
            self._row.append(text)
            self._row_kinds.append(tag)
            self._buffer = []
        elif tag == "tr" and self._depth:
            if self._row:
                self._rows.append(list(self._row))
                self._row_kind_rows.append(list(self._row_kinds))
            self._row = []
            self._row_kinds = []
        elif tag == "table" and self._depth:
            self._depth -= 1
            if self._rows:
                self.tables.append(
                    {
                        "heading_path": list(self._heading_stack),
                        "rows": list(self._rows),
                        "kinds": list(self._row_kind_rows),
                    }
                )
            self._rows = []
            self._row_kind_rows = []

    def handle_data(self, data: str) -> None:
        self._buffer.append(data)


def html_tables(raw: str) -> Iterator[dict[str, Any]]:
    """Two shapes, both source-native.

    A column-headed table reads like markdown's. An infobox reads by row: the
    ``<th>`` is the key and the ``<td>`` beside it is the value, which is
    exactly the structure encyclopaedic sources publish.
    """
    reader = _TableReader()
    reader.feed(raw)
    reader.close()
    for table in reader.tables:
        rows, kinds = table["rows"], table["kinds"]
        header_is_row = kinds and all(kind == "th" for kind in kinds[0]) and len(rows) > 1
        if header_is_row:
            yield {
                "heading_path": table["heading_path"],
                "header": rows[0],
                "rows": rows[1:],
            }
            continue
        pairs = [
            row
            for row, kind in zip(rows, kinds)
            if len(row) == 2 and kind[0] == "th" and kind[1] == "td"
        ]
        if pairs:
            yield {
                "heading_path": table["heading_path"],
                "header": ["property", "value"],
                "rows": pairs,
            }


def tables(raw: str, suffix: str) -> list[dict[str, Any]]:
    if suffix == ".md":
        return list(markdown_tables(raw))
    return list(html_tables(raw))


# --- observations, then facts --------------------------------------------------


def observations(raw: str, suffix: str, document_id: str) -> dict[str, dict[str, Any]]:
    """Every ``(label, column) -> single value`` binding the source states.

    A label appearing twice under one heading path is dropped rather than
    disambiguated by position. Two rows claiming the same key is exactly the
    ambiguity the endpoint cannot tolerate, and choosing one by ordinal would
    hide it.
    """
    found: dict[str, dict[str, Any]] = {}
    seen_twice: set[str] = set()
    for table in tables(raw, suffix):
        header = table["header"]
        for row in table["rows"]:
            if len(row) != len(header) or len(row) < 2:
                continue
            label = row[0]
            if not label_is_usable(label):
                continue
            for column_index in range(1, len(header)):
                column = header[column_index] or "value"
                got = sole_value(row[column_index])
                if got is None:
                    continue
                kind, token = got
                key = property_id(document_id, table["heading_path"], label, column)
                if key in found:
                    seen_twice.add(key)
                    continue
                found[key] = {
                    "property_id": key,
                    "property_label": label,
                    "column_label": column,
                    "heading_path": table["heading_path"],
                    "value_kind": kind,
                    "value": token,
                    "value_text": row[column_index],
                }
    for key in seen_twice:
        found.pop(key, None)
    return found


def value_facts(
    document_id: str,
    before_raw: str,
    after_raw: str,
    suffix: str,
) -> dict[str, Any]:
    """Paired facts, and a reason for every candidate that did not become one."""
    before = observations(before_raw, suffix, document_id)
    after = observations(after_raw, suffix, document_id)
    facts: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []

    for key, current in sorted(after.items()):
        superseded = before.get(key)
        if superseded is None:
            rejected.append({"property_id": key, "code": PROPERTY_NOT_STABLE})
            continue
        if current["value_kind"] != superseded["value_kind"]:
            rejected.append({"property_id": key, "code": VALUE_KIND_MISMATCH})
            continue
        if normalise(current["value"]) == normalise(superseded["value"]):
            rejected.append({"property_id": key, "code": VALUE_UNCHANGED})
            continue
        if not label_is_usable(current["property_label"]):
            rejected.append({"property_id": key, "code": LABEL_READS_THE_VALUE})
            continue
        pair = contrast(current["value_text"], superseded["value_text"])
        if not pair["distinguishable"]:
            rejected.append({"property_id": key, "code": AMBIGUOUS_VALUE_FACT})
            continue
        facts.append(
            {
                "property_id": key,
                "property_label": current["property_label"],
                "column_label": current["column_label"],
                "heading_path": current["heading_path"],
                "value_kind": current["value_kind"],
                "current_value": current["value"],
                "superseded_value": superseded["value"],
                "current_value_text": current["value_text"],
                "superseded_value_text": superseded["value_text"],
            }
        )
    if not facts and not rejected:
        rejected.append({"property_id": "", "code": NO_VALUE_FACT})
    return {"facts": facts, "rejected": rejected}


def atom_contrast_is_single(
    fact: dict[str, Any],
    current_atom_text: str,
    superseded_atom_text: str,
) -> dict[str, Any]:
    """Criterion 6, applied where the model will actually read.

    The fact may be a clean single-value contrast while the atom carrying it
    changed three other numbers. Answering correctly from that atom would not
    demonstrate currency selection, so it is refused rather than counted.
    """
    pair = contrast(current_atom_text, superseded_atom_text)
    current_markers = set(pair["current"])
    superseded_markers = set(pair["superseded"])
    ok = current_markers == {fact["current_value"]} and superseded_markers == {
        fact["superseded_value"]
    }
    return {
        "single_contrast": ok,
        "code": None if ok else AMBIGUOUS_VALUE_FACT,
        "atom_current_markers": sorted(current_markers),
        "atom_superseded_markers": sorted(superseded_markers),
    }


# --- question identity — INC-V2-018 ------------------------------------------


def question_id(
    family: str,
    document_id: str,
    before_version: str,
    after_version: str,
    atom_id: str,
    anchor_path: str,
    kind: str,
    property_id_value: str,
) -> str:
    """Content-addressed, and injective where the rendered string was not."""
    blob = json.dumps(
        {
            "anchor_path": anchor_path,
            "after_version": after_version,
            "atom_id": atom_id,
            "before_version": before_version,
            "document_id": document_id,
            "family": family,
            "kind": kind,
            "property_id": property_id_value,
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return "q:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


def injective(question_ids: list[str]) -> dict[str, Any]:
    """The hard gate. One duplicate stops the run."""
    duplicates = sorted({q for q in question_ids if question_ids.count(q) > 1})
    return {
        "rows": len(question_ids),
        "unique": len(set(question_ids)),
        "injective": len(set(question_ids)) == len(question_ids),
        "duplicates": duplicates[:20],
    }


# --- question wording ----------------------------------------------------------

#: Constant frame. The property label and the column label are the only
#: document-specific inputs, and both are read from structure rather than from
#: the value.
QUESTION_TEMPLATE = "{column} of {label}"


def question_query(fact: dict[str, Any]) -> str:
    column = fact["column_label"].strip() or "value"
    return QUESTION_TEMPLATE.format(column=column, label=fact["property_label"].strip())


def question_is_blind_to_the_value(query: str, fact: dict[str, Any]) -> dict[str, Any]:
    """A question that contains its answer measures nothing."""
    found = sorted(
        token
        for token in value_tokens(query)
        if token in {fact["current_value"], fact["superseded_value"]}
    )
    leaked = bool(found) or bool(value_tokens(query))
    return {"blind": not leaked, "value_tokens_in_query": sorted(value_tokens(query))}
