"""Pre-parser validation for non-PDF structured sources."""

from __future__ import annotations

import io
import posixpath
import re
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from akc_security import (
    PLAN_LIMITS,
    PlanTier,
    safe_relative_path,
    validate_upload_bytes,
)
from defusedxml import ElementTree as SafeElementTree
from defusedxml.common import DefusedXmlException

from .models import ParserLimits, StructuredParseError

OFFICE_EXTENSIONS = frozenset({".docx", ".pptx", ".xlsx"})
TEXT_EXTENSIONS = frozenset({".html", ".htm", ".srt", ".vtt"})
SUPPORTED_EXTENSIONS = OFFICE_EXTENSIONS | TEXT_EXTENSIONS

_CANONICAL_MIME = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".html": "text/html",
    ".htm": "text/html",
    ".srt": "application/x-subrip",
    ".vtt": "text/vtt",
}
_ALLOWED_MIME = {
    ".docx": frozenset({_CANONICAL_MIME[".docx"]}),
    ".pptx": frozenset({_CANONICAL_MIME[".pptx"]}),
    ".xlsx": frozenset({_CANONICAL_MIME[".xlsx"]}),
    ".html": frozenset({"text/html", "application/xhtml+xml"}),
    ".htm": frozenset({"text/html", "application/xhtml+xml"}),
    ".srt": frozenset({"application/x-subrip", "text/plain"}),
    ".vtt": frozenset({"text/vtt", "text/plain"}),
}
_OFFICE_MARKER = {
    ".docx": "word/",
    ".pptx": "ppt/",
    ".xlsx": "xl/",
}
_BLOCKED_MEMBER_PARTS = (
    "/embeddings/",
    "/activex/",
    "/oleobjects/",
    "/externallinks/",
    "/customui/",
)
_BLOCKED_MEMBER_SUFFIXES = (
    "vbaproject.bin",
    ".exe",
    ".dll",
    ".com",
    ".bat",
    ".cmd",
    ".ps1",
    ".vbs",
    ".js",
    ".jar",
    ".msi",
)
_RELATIONSHIP_EXTERNAL = re.compile(
    rb"""(?:TargetMode\s*=\s*["']External["']|Target\s*=\s*["'](?:[A-Za-z][A-Za-z0-9+.-]*:|//|\\\\))""",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class ValidatedSource:
    normalized_filename: str
    extension: str
    source_sha256: str
    text: str | None = None


def validate_source(
    *,
    filename: str,
    declared_mime: str,
    data: bytes,
    limits: ParserLimits,
) -> ValidatedSource:
    if not data:
        raise StructuredParseError("FILE_EMPTY")
    if len(data) > limits.max_input_bytes:
        raise StructuredParseError("FILE_TOO_LARGE")
    normalized_filename = Path(filename).name
    extension = Path(normalized_filename.casefold()).suffix
    if extension not in SUPPORTED_EXTENSIONS:
        raise StructuredParseError("UNSUPPORTED_NON_PDF_TYPE")
    normalized_mime = declared_mime.split(";", 1)[0].strip().casefold()
    if normalized_mime not in _ALLOWED_MIME[extension]:
        raise StructuredParseError("MIME_MISMATCH")

    if extension in OFFICE_EXTENSIONS:
        _validate_office_archive(data, extension, limits)

    validation = validate_upload_bytes(
        normalized_filename,
        data,
        tier=_validation_tier(limits.max_input_bytes),
        claimed_content_type=_CANONICAL_MIME[extension],
    )
    if not validation.accepted or validation.sha256 is None:
        raise StructuredParseError((validation.reason_code or "FILE_VALIDATION_FAILED").upper())

    text: str | None = None
    if extension in TEXT_EXTENSIONS:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise StructuredParseError("TEXT_ENCODING") from exc
        if "\x00" in text:
            raise StructuredParseError("BINARY_TEXT_FILE")
        if extension in {".html", ".htm"} and not _looks_like_html(text):
            raise StructuredParseError("HTML_SIGNATURE_MISMATCH")

    return ValidatedSource(
        normalized_filename=validation.normalized_filename,
        extension=extension,
        source_sha256=validation.sha256,
        text=text,
    )


def _validation_tier(max_input_bytes: int) -> PlanTier:
    for tier in (PlanTier.FREE, PlanTier.PRO, PlanTier.TEAM):
        if max_input_bytes <= PLAN_LIMITS[tier].max_file_bytes:
            return tier
    return PlanTier.TEAM


def _looks_like_html(source: str) -> bool:
    prefix = source.lstrip()[:4096].casefold()
    return any(
        marker in prefix
        for marker in ("<!doctype html", "<html", "<head", "<body", "<main", "<article")
    )


def _validate_office_archive(
    data: bytes,
    extension: str,
    limits: ParserLimits,
) -> None:
    if not data.startswith(b"PK\x03\x04"):
        raise StructuredParseError("MAGIC_MISMATCH")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except (OSError, zipfile.BadZipFile) as exc:
        raise StructuredParseError("INVALID_OFFICE_ARCHIVE") from exc

    with archive:
        entries = archive.infolist()
        if len(entries) > limits.max_archive_entries:
            raise StructuredParseError("ARCHIVE_ENTRY_LIMIT")
        names: set[str] = set()
        total_uncompressed = 0
        total_compressed = 0
        embedded_chart_workbooks: list[zipfile.ZipInfo] = []
        for entry in entries:
            normalized_name = entry.filename.replace("\\", "/")
            candidate = normalized_name.rstrip("/")
            if candidate:
                try:
                    safe_relative_path(candidate)
                except ValueError as exc:
                    raise StructuredParseError("ARCHIVE_PATH_TRAVERSAL") from exc
            folded_name = normalized_name.casefold()
            if folded_name in names:
                raise StructuredParseError("ARCHIVE_DUPLICATE_ENTRY")
            names.add(folded_name)
            if entry.flag_bits & 0x1:
                raise StructuredParseError("ARCHIVE_ENCRYPTED_ENTRY")
            if stat.S_ISLNK(entry.external_attr >> 16):
                raise StructuredParseError("ARCHIVE_SYMLINK")
            if entry.file_size > limits.max_archive_member_bytes:
                raise StructuredParseError("ARCHIVE_MEMBER_LIMIT")
            total_uncompressed += entry.file_size
            total_compressed += entry.compress_size
            if total_uncompressed > limits.max_archive_uncompressed_bytes:
                raise StructuredParseError("ARCHIVE_SIZE_LIMIT")
            member_path = f"/{folded_name}"
            if any(part in member_path for part in _BLOCKED_MEMBER_PARTS):
                is_chart_workbook = (
                    extension == ".pptx"
                    and folded_name.startswith("ppt/embeddings/")
                    and folded_name.endswith(".xlsx")
                )
                if not is_chart_workbook:
                    raise StructuredParseError("OFFICE_EMBEDDED_OBJECT")
                embedded_chart_workbooks.append(entry)
            if any(folded_name.endswith(suffix) for suffix in _BLOCKED_MEMBER_SUFFIXES):
                raise StructuredParseError("OFFICE_ACTIVE_CONTENT")

        if total_uncompressed / max(total_compressed, 1) > limits.max_compression_ratio:
            raise StructuredParseError("ARCHIVE_RATIO_LIMIT")
        if "[content_types].xml" not in names:
            raise StructuredParseError("OOXML_CONTENT_TYPES_MISSING")
        if not any(name.startswith(_OFFICE_MARKER[extension]) for name in names):
            raise StructuredParseError("OOXML_PACKAGE_KIND_MISMATCH")
        if embedded_chart_workbooks:
            allowed_workbooks = _chart_workbook_relationship_targets(archive)
            for entry in embedded_chart_workbooks:
                folded_name = entry.filename.replace("\\", "/").casefold()
                if folded_name not in allowed_workbooks:
                    raise StructuredParseError("OFFICE_EMBEDDED_OBJECT")
                _validate_office_archive(archive.read(entry), ".xlsx", limits)

        for entry in entries:
            if entry.is_dir():
                continue
            folded_name = entry.filename.replace("\\", "/").casefold()
            is_xml = folded_name.endswith((".xml", ".rels"))
            if not is_xml:
                continue
            payload = archive.read(entry)
            upper = payload.upper()
            if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
                raise StructuredParseError("OOXML_UNSAFE_XML")
            if folded_name.endswith(".rels") and _RELATIONSHIP_EXTERNAL.search(payload):
                raise StructuredParseError("OFFICE_EXTERNAL_RELATION")
            if folded_name == "[content_types].xml" and (
                b"macroenabled" in payload.lower() or b"vbaproject" in payload.lower()
            ):
                raise StructuredParseError("OFFICE_ACTIVE_CONTENT")


def _chart_workbook_relationship_targets(
    archive: zipfile.ZipFile,
) -> set[str]:
    targets: set[str] = set()
    for entry in archive.infolist():
        folded_name = entry.filename.replace("\\", "/").casefold()
        if not re.fullmatch(r"ppt/charts/_rels/chart\d+\.xml\.rels", folded_name):
            continue
        try:
            root = SafeElementTree.fromstring(archive.read(entry))
        except (DefusedXmlException, SafeElementTree.ParseError) as exc:
            raise StructuredParseError("OOXML_UNSAFE_XML") from exc
        for relationship in root:
            relation_type = str(relationship.attrib.get("Type", ""))
            target = str(relationship.attrib.get("Target", ""))
            target_mode = str(relationship.attrib.get("TargetMode", ""))
            if (
                not relation_type.endswith("/package")
                or not target
                or target_mode.casefold() == "external"
            ):
                continue
            resolved = posixpath.normpath(
                posixpath.join("ppt/charts", target.replace("\\", "/"))
            ).casefold()
            if resolved.startswith("ppt/embeddings/") and resolved.endswith(".xlsx"):
                targets.add(resolved)
    return targets


def inspect_archive_names(data: bytes) -> tuple[str, ...]:
    """Return normalized package names after validation; never extracts members."""

    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return tuple(
            sorted(
                PurePosixPath(entry.filename.replace("\\", "/")).as_posix()
                for entry in archive.infolist()
                if not entry.is_dir()
            )
        )
