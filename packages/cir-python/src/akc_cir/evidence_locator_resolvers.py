"""Resolve an :mod:`akc_cir.evidence_locator` locator against stored bytes.

Blueprint §20 invariant #1 is "evidence locator resolves". Until this module
nothing in the tree opened a representation and checked that the anchor is
really there — only structural validation existed. A locator that does not
resolve is ``Unresolved`` with a frozen ``FailureClass``; it is never a best
guess and never a fabricated excerpt.

Scope in this campaign (§48 P0-E): ``pdf``, ``json`` and ``xlsx``. Every other
variant is typed and schema-validated but has no resolver and resolves to
``UNSUPPORTED_FORMAT`` — see ``docs/architecture/evidence-locator-v2.md``.
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final, Protocol

from akc_native_parsers.models import ParserLimits, StructuredParseError
from akc_native_parsers.security import validate_source
from defusedxml import ElementTree as SafeElementTree
from pypdf import PdfReader

from .base import canonical_json, sha256_digest
from .evidence_locator import AnyEvidenceLocator, JsonLocator, PdfLocator, XlsxLocator

__all__ = [
    "FailureClass",
    "JsonLocatorResolver",
    "LocatorResolver",
    "PdfLocatorResolver",
    "Resolution",
    "Resolved",
    "Unresolved",
    "XlsxLocatorResolver",
    "resolve_locator",
]


class FailureClass(StrEnum):
    """Frozen vocabulary — ``contract/enums.v1.json`` ``FailureClass``."""

    UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
    ENCRYPTED_SOURCE = "ENCRYPTED_SOURCE"
    CORRUPT_SOURCE = "CORRUPT_SOURCE"
    MALWARE_QUARANTINED = "MALWARE_QUARANTINED"
    PARSER_TIMEOUT = "PARSER_TIMEOUT"
    PARSER_OOM = "PARSER_OOM"
    EMPTY_OUTPUT = "EMPTY_OUTPUT"
    NATIVE_VISUAL_DISAGREEMENT = "NATIVE_VISUAL_DISAGREEMENT"
    LAYOUT_FAILURE = "LAYOUT_FAILURE"
    TABLE_FAILURE = "TABLE_FAILURE"
    FORMULA_FAILURE = "FORMULA_FAILURE"
    TEXT_OMISSION = "TEXT_OMISSION"
    IDENTITY_UNRESOLVED = "IDENTITY_UNRESOLVED"
    EVIDENCE_BROKEN = "EVIDENCE_BROKEN"
    ACL_UNRESOLVED = "ACL_UNRESOLVED"
    SOURCE_DELETED = "SOURCE_DELETED"
    RECEIPT_MISMATCH = "RECEIPT_MISMATCH"
    PRESERVATION_FAILED = "PRESERVATION_FAILED"
    EQUIVALENCE_FAILED = "EQUIVALENCE_FAILED"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"


EXCERPT_MAX_CHARS: Final = 2000
_MAX_PART_BYTES: Final = 8 * 1024 * 1024
_MAX_RANGE_CELLS: Final = 4096


@dataclass(frozen=True, slots=True)
class Resolved:
    """The anchor exists in the representation.

    ``digest`` binds the *whole* resolved unit; ``excerpt`` is the first
    ``EXCERPT_MAX_CHARS`` characters of it, which is what the frozen schema's
    ``excerpt`` field can carry.
    """

    excerpt: str
    digest: str


@dataclass(frozen=True, slots=True)
class Unresolved:
    reason: FailureClass
    detail: str


Resolution = Resolved | Unresolved


class LocatorResolver(Protocol):
    """One resolver per ``locatorKind``."""

    locator_kind: str

    def resolve(self, locator: AnyEvidenceLocator, data: bytes) -> Resolution: ...


def _resolved(text: str, anchor: str) -> Resolution:
    """Resolved, unless the anchor holds nothing.

    The digest of the empty string is the same for every empty page and every
    empty cell of every document, so ``Resolved("")`` would hand back a
    ``contentDigest`` that verifies against any other empty anchor — a receipt
    that proves nothing. That is ``EMPTY_OUTPUT``, not evidence.
    """
    if not text:
        return Unresolved(FailureClass.EMPTY_OUTPUT, f"{anchor} holds no extractable content")
    return Resolved(excerpt=text[:EXCERPT_MAX_CHARS], digest=sha256_digest(text))


def _wrong_kind(locator: AnyEvidenceLocator, expected: str) -> Unresolved:
    return Unresolved(
        FailureClass.EVIDENCE_BROKEN,
        f"expected a {expected} locator, got {locator.locator_kind!r}",
    )


class PdfLocatorResolver:
    """Structural + page-bound resolution against the PDF representation.

    This resolves to the *page*, not to the bbox region: the union carries a
    bbox but nothing in this tree extracts text for an arbitrary rectangle, and
    inventing one would be a fabricated excerpt. The bbox is validated
    structurally by :class:`~akc_cir.models.BBox1000`.
    """

    locator_kind = "pdf"

    def resolve(self, locator: AnyEvidenceLocator, data: bytes) -> Resolution:
        if not isinstance(locator, PdfLocator):
            return _wrong_kind(locator, "pdf")
        try:
            reader = PdfReader(io.BytesIO(data), strict=False)
            encrypted = reader.is_encrypted
        except Exception as exc:  # hostile bytes: pypdf raises a wide family
            return Unresolved(
                FailureClass.CORRUPT_SOURCE, f"pdf not readable: {type(exc).__name__}"
            )
        if encrypted:
            # Checked before touching .pages, which raises on an encrypted file
            # and would otherwise be reported as corruption.
            return Unresolved(FailureClass.ENCRYPTED_SOURCE, "pdf representation is encrypted")
        try:
            page_count = len(reader.pages)
        except Exception as exc:
            return Unresolved(
                FailureClass.CORRUPT_SOURCE, f"pdf not readable: {type(exc).__name__}"
            )
        if locator.page > page_count:
            return Unresolved(
                FailureClass.EVIDENCE_BROKEN,
                f"page {locator.page} is outside the {page_count}-page representation",
            )
        try:
            text = reader.pages[locator.page - 1].extract_text() or ""
        except Exception as exc:
            return Unresolved(
                FailureClass.CORRUPT_SOURCE,
                f"page {locator.page} not readable: {type(exc).__name__}",
            )
        return _resolved(text, f"page {locator.page}")


def _json_pointer_walk(document: Any, pointer: str) -> tuple[bool, Any]:
    """RFC 6901 evaluation. Returns ``(found, value)``; never raises."""
    if pointer == "":
        return True, document
    node = document
    for raw_token in pointer.split("/")[1:]:
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict):
            if token not in node:
                return False, None
            node = node[token]
        elif isinstance(node, list):
            if not token.isdigit() or (len(token) > 1 and token.startswith("0")):
                return False, None
            index = int(token)
            if index >= len(node):
                return False, None
            node = node[index]
        else:
            return False, None
    return True, node


class JsonLocatorResolver:
    """RFC 6901 pointer resolution (stdlib ``json`` only)."""

    locator_kind = "json"

    def resolve(self, locator: AnyEvidenceLocator, data: bytes) -> Resolution:
        if not isinstance(locator, JsonLocator):
            return _wrong_kind(locator, "json")
        try:
            document = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            return Unresolved(
                FailureClass.CORRUPT_SOURCE, f"json not readable: {type(exc).__name__}"
            )
        found, value = _json_pointer_walk(document, locator.pointer)
        if not found:
            return Unresolved(
                FailureClass.EVIDENCE_BROKEN,
                f"pointer {locator.pointer!r} does not resolve in this representation",
            )
        return _resolved(canonical_json(value), f"pointer {locator.pointer!r}")


_MAIN_NS: Final = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL_NS: Final = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_PKG_REL_NS: Final = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_A1 = re.compile(r"^\$?([A-Z]{1,3})\$?([1-9][0-9]{0,6})$")
_XLSX_MIME: Final = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
# `StructuredParseError.code` is a stable, body-free vocabulary (models.py:29).
# Anything not named here is a package this resolver cannot trust: CORRUPT_SOURCE.
_PACKAGE_FAILURE: Final[dict[str, FailureClass]] = {
    "ARCHIVE_ENCRYPTED_ENTRY": FailureClass.ENCRYPTED_SOURCE,
    "OFFICE_ACTIVE_CONTENT": FailureClass.MALWARE_QUARANTINED,
    "OFFICE_EMBEDDED_OBJECT": FailureClass.MALWARE_QUARANTINED,
    "OFFICE_EXTERNAL_RELATION": FailureClass.MALWARE_QUARANTINED,
}


class _XlsxError(Exception):
    def __init__(self, reason: FailureClass, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


def _column_index(letters: str) -> int:
    index = 0
    for character in letters:
        index = index * 26 + (ord(character) - ord("A") + 1)
    return index


def _column_letters(index: int) -> str:
    letters = ""
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters


def _read_part(archive: zipfile.ZipFile, name: str) -> bytes:
    try:
        info = archive.getinfo(name)
    except KeyError as exc:
        raise _XlsxError(FailureClass.EVIDENCE_BROKEN, f"missing package part {name}") from exc
    if info.file_size > _MAX_PART_BYTES:
        raise _XlsxError(
            FailureClass.CORRUPT_SOURCE,
            f"package part {name} declares {info.file_size} bytes, over the resolver limit",
        )
    return archive.read(name)


def _parse_part(archive: zipfile.ZipFile, name: str) -> Any:
    try:
        return SafeElementTree.fromstring(_read_part(archive, name))
    except _XlsxError:
        raise
    except Exception as exc:
        raise _XlsxError(
            FailureClass.CORRUPT_SOURCE, f"{name} is not safe, well-formed XML"
        ) from exc


def _sheet_part(archive: zipfile.ZipFile, sheet_name: str) -> str:
    workbook = _parse_part(archive, "xl/workbook.xml")
    relationship_id: str | None = None
    for sheet in workbook.iter(f"{_MAIN_NS}sheet"):
        if sheet.get("name") == sheet_name:
            relationship_id = sheet.get(f"{_REL_NS}id")
            break
    if relationship_id is None:
        raise _XlsxError(
            FailureClass.EVIDENCE_BROKEN, f"workbook has no sheet named {sheet_name!r}"
        )
    relationships = _parse_part(archive, "xl/_rels/workbook.xml.rels")
    for relationship in relationships.iter(f"{_PKG_REL_NS}Relationship"):
        if relationship.get("Id") == relationship_id:
            target = str(relationship.get("Target", ""))
            return target[1:] if target.startswith("/") else f"xl/{target.lstrip('./')}"
    raise _XlsxError(
        FailureClass.EVIDENCE_BROKEN, f"sheet {sheet_name!r} has no package relationship"
    )


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    table = _parse_part(archive, "xl/sharedStrings.xml")
    return [
        "".join(node.text or "" for node in item.iter(f"{_MAIN_NS}t"))
        for item in table.iter(f"{_MAIN_NS}si")
    ]


def _cell_text(cell: Any, shared: list[str]) -> str | None:
    cell_type = cell.get("t", "n")
    if cell_type == "inlineStr":
        inline = cell.find(f"{_MAIN_NS}is")
        if inline is None:
            return None
        return "".join(node.text or "" for node in inline.iter(f"{_MAIN_NS}t"))
    value = cell.find(f"{_MAIN_NS}v")
    if value is None:
        return None
    raw = value.text or ""
    if cell_type == "s":
        if not raw.isdigit() or int(raw) >= len(shared):
            return None
        return shared[int(raw)]
    if cell_type == "b":
        return "TRUE" if raw == "1" else "FALSE"
    return raw


def _sheet_cells(archive: zipfile.ZipFile, part: str, shared: list[str]) -> dict[str, str]:
    sheet = _parse_part(archive, part)
    cells: dict[str, str] = {}
    for cell in sheet.iter(f"{_MAIN_NS}c"):
        reference = cell.get("r")
        if not reference:
            continue
        text = _cell_text(cell, shared)
        if text is not None:
            cells[str(reference)] = text
    return cells


def _range_references(start: str, end: str) -> list[list[str]]:
    start_match = _A1.match(start.replace("$", ""))
    end_match = _A1.match(end.replace("$", ""))
    if start_match is None or end_match is None:
        raise _XlsxError(FailureClass.EVIDENCE_BROKEN, "range endpoints are not A1 references")
    first_column = _column_index(start_match.group(1))
    last_column = _column_index(end_match.group(1))
    first_row = int(start_match.group(2))
    last_row = int(end_match.group(2))
    if first_column > last_column or first_row > last_row:
        raise _XlsxError(FailureClass.EVIDENCE_BROKEN, "range end precedes its start")
    if (last_column - first_column + 1) * (last_row - first_row + 1) > _MAX_RANGE_CELLS:
        raise _XlsxError(
            FailureClass.EVIDENCE_BROKEN,
            f"range covers more than {_MAX_RANGE_CELLS} cells",
        )
    return [
        [f"{_column_letters(column)}{row}" for column in range(first_column, last_column + 1)]
        for row in range(first_row, last_row + 1)
    ]


class XlsxLocatorResolver:
    """Sheet + cell/range resolution through ``zipfile`` and safe XML.

    The package goes through the repo's existing hostile-archive guards
    (:func:`akc_native_parsers.security.validate_source`) *before* a single part
    is read. A bare ``zipfile`` resolves a duplicate ``xl/workbook.xml`` out of
    whichever copy the central directory happens to list last, so an appended
    shadow workbook would hand back attacker content as evidence while the real
    sheet reported ``EVIDENCE_BROKEN``. Those guards — duplicate part names,
    path traversal, encrypted and symlink members, entry count, uncompressed
    size and compression ratio — already refuse that package everywhere else in
    the product; the resolver must not be the one door that accepts it.

    ``namedRange``, ``tableId`` and ``chartId`` anchors are typed by the schema
    but have no resolver here; they report ``UNSUPPORTED_FORMAT`` rather than
    resolving to something adjacent. The optional ``workbook`` field is not
    checked: the representation bytes *are* the workbook by contract, and this
    resolver has no way to bind an external workbook name to them.
    """

    locator_kind = "xlsx"

    def resolve(self, locator: AnyEvidenceLocator, data: bytes) -> Resolution:
        if not isinstance(locator, XlsxLocator):
            return _wrong_kind(locator, "xlsx")
        cell_ref = locator.cell
        range_ref = locator.range
        if cell_ref is None and range_ref is None:
            return Unresolved(
                FailureClass.UNSUPPORTED_FORMAT,
                "only cell and range anchors resolve in this campaign",
            )
        try:
            validate_source(
                filename="representation.xlsx",
                declared_mime=_XLSX_MIME,
                data=data,
                limits=ParserLimits(),
            )
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                shared = _shared_strings(archive)
                part = _sheet_part(archive, locator.sheet)
                cells = _sheet_cells(archive, part, shared)
        except StructuredParseError as error:
            return Unresolved(
                _PACKAGE_FAILURE.get(error.code, FailureClass.CORRUPT_SOURCE),
                f"xlsx package refused by the source guards: {error.code}",
            )
        except _XlsxError as error:
            return Unresolved(error.reason, error.detail)
        except Exception as exc:
            # zipfile raises a wider family than BadZipFile on hostile bytes:
            # NotImplementedError for an unsupported extract_version or
            # compression method, RuntimeError for an encrypted member. All of
            # them are a package this resolver cannot read, never a crash.
            return Unresolved(
                FailureClass.CORRUPT_SOURCE,
                f"xlsx is not a readable package: {type(exc).__name__}",
            )
        if cell_ref is not None:
            reference = cell_ref.replace("$", "")
            if reference not in cells:
                return Unresolved(
                    FailureClass.EVIDENCE_BROKEN,
                    f"cell {reference} is empty or absent on sheet {locator.sheet!r}",
                )
            return _resolved(cells[reference], f"cell {reference} on sheet {locator.sheet!r}")
        if range_ref is None:  # pragma: no cover - guarded above
            return Unresolved(FailureClass.UNSUPPORTED_FORMAT, "no resolvable anchor")
        start, _, end = range_ref.partition(":")
        try:
            rows = _range_references(start, end)
        except _XlsxError as error:
            return Unresolved(error.reason, error.detail)
        if not any(reference in cells for row in rows for reference in row):
            return Unresolved(
                FailureClass.EVIDENCE_BROKEN,
                f"range {range_ref} is empty on sheet {locator.sheet!r}",
            )
        return _resolved(
            "\n".join("\t".join(cells.get(reference, "") for reference in row) for row in rows),
            f"range {range_ref} on sheet {locator.sheet!r}",
        )


_RESOLVERS: Final[dict[str, LocatorResolver]] = {
    resolver.locator_kind: resolver
    for resolver in (PdfLocatorResolver(), JsonLocatorResolver(), XlsxLocatorResolver())
}


def resolve_locator(locator: AnyEvidenceLocator, data: bytes) -> Resolution:
    """Resolve ``locator`` against the representation bytes it binds to.

    Fail closed: an unknown kind, a missing anchor, or a ``contentDigest`` that
    disagrees with what was actually read is ``Unresolved``.
    """
    resolver = _RESOLVERS.get(locator.locator_kind)
    if resolver is None:
        return Unresolved(
            FailureClass.UNSUPPORTED_FORMAT,
            f"no resolver for locatorKind {locator.locator_kind!r}",
        )
    result = resolver.resolve(locator, data)
    if (
        isinstance(result, Resolved)
        and locator.content_digest is not None
        and result.digest != locator.content_digest
    ):
        return Unresolved(
            FailureClass.RECEIPT_MISMATCH,
            "resolved content digest does not match the locator contentDigest",
        )
    return result
