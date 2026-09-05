"""Source inspector — blueprint §8.1 detection order, §8.2 result.

Never trusts the extension, never raises for hostile input, never extracts an
archive member. `akc_native_parsers.security.validate_source()` is *wrapped*:
its `StructuredParseError` codes become review reasons here, and that module is
not edited.
"""

from __future__ import annotations

import io
import zipfile
from typing import Final

from akc_native_parsers.models import ParserLimits, StructuredParseError
from akc_native_parsers.security import validate_source

from .enums import SourceFamily
from .models import ReaderInput, SourceInspection

_MAGIC_MIME: Final[tuple[tuple[bytes, str], ...]] = (
    (b"%PDF-", "application/pdf"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"II*\x00", "image/tiff"),
    (b"MM\x00*", "image/tiff"),
    (b"BM", "image/bmp"),
    (b"\x1f\x8b", "application/gzip"),
    (b"MZ", "application/vnd.microsoft.portable-executable"),
    (b"\x7fELF", "application/x-elf"),
)

# ZIP package markers, checked in order; the first hit wins (§8.1 step 5).
_ZIP_PACKAGE: Final[tuple[tuple[str, str, str, SourceFamily], ...]] = (
    (
        "word/",
        "docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        SourceFamily.DOCUMENT,
    ),
    (
        "xl/",
        "xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        SourceFamily.SPREADSHEET,
    ),
    (
        "ppt/",
        "pptx",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        SourceFamily.PRESENTATION,
    ),
    ("contents/content.hpf", "hwpx", "application/hwp+zip", SourceFamily.DOCUMENT),
    ("meta-inf/manifest.xml", "odf", "application/vnd.oasis.opendocument", SourceFamily.DOCUMENT),
)

_TEXT_MIME_FAMILY: Final[dict[str, SourceFamily]] = {
    "text/plain": SourceFamily.DOCUMENT,
    "text/markdown": SourceFamily.DOCUMENT,
    "text/html": SourceFamily.WEB,
    "application/json": SourceFamily.STRUCTURED_DATA,
    "application/xml": SourceFamily.STRUCTURED_DATA,
    "text/csv": SourceFamily.STRUCTURED_DATA,
}

_EXTENSION_TEXT_MIME: Final[dict[str, str]] = {
    ".txt": "text/plain",
    ".text": "text/plain",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".html": "text/html",
    ".htm": "text/html",
    ".json": "application/json",
    ".xml": "application/xml",
    ".csv": "text/csv",
}

_MIME_FAMILY: Final[dict[str, SourceFamily]] = {
    "application/pdf": SourceFamily.DOCUMENT,
    "image/png": SourceFamily.IMAGE,
    "image/jpeg": SourceFamily.IMAGE,
    "image/gif": SourceFamily.IMAGE,
    "image/tiff": SourceFamily.IMAGE,
    "image/bmp": SourceFamily.IMAGE,
    "application/zip": SourceFamily.ARCHIVE,
    "application/gzip": SourceFamily.ARCHIVE,
    **_TEXT_MIME_FAMILY,
}

_VALIDATED_EXTENSIONS: Final[frozenset[str]] = frozenset(
    {".docx", ".pptx", ".xlsx", ".html", ".htm", ".srt", ".vtt"}
)

_MAX_COMPRESSION_RATIO: Final[float] = 100.0
_TEXT_SNIFF_BYTES: Final[int] = 8192


def _extension(filename: str) -> str:
    name = filename.replace("\\", "/").rsplit("/", 1)[-1].casefold()
    dot = name.rfind(".")
    return name[dot:] if dot > 0 else ""


def _normalized_mime(declared: str) -> str:
    return declared.split(";", 1)[0].strip().casefold()


def _decodes_as_text(data: bytes) -> bool:
    try:
        text = data[:_TEXT_SNIFF_BYTES].decode("utf-8-sig")
    except UnicodeDecodeError:
        return False
    return "\x00" not in text


def inspect_source(source: ReaderInput, *, limits: ParserLimits | None = None) -> SourceInspection:
    """Diagnose one source version in blueprint §8.1 order.

    ``confidence`` is a structural-completeness score, not a calibrated
    probability and not a quality score: it counts which detection steps
    actually concluded something. Nothing routes on it — ``ReaderRegistry``
    resolves on capability and on the ``encrypted``/``corrupted`` facts.
    """
    extension = _extension(source.filename)
    declared = _normalized_mime(source.declared_mime)
    review: list[str] = []
    data = source.data

    detected = ""
    family = SourceFamily.UNKNOWN
    container: str | None = None
    encrypted = False
    corrupted = False
    has_native_text: bool | None = None
    has_native_structure: bool | None = None
    has_visual_content: bool | None = None
    page_like_units: int | None = None
    magic_hit = False
    container_hit = False

    if not data:
        review.append("FILE_EMPTY")
        corrupted = True

    for prefix, mime in _MAGIC_MIME:
        if data.startswith(prefix):
            detected, magic_hit = mime, True
            break

    if data.startswith(b"PK\x03\x04"):
        magic_hit = True
        detected, container = "application/zip", "zip"
        family = SourceFamily.ARCHIVE
        zip_result = _inspect_zip(data, review)
        if zip_result is None:
            corrupted = True
        else:
            container_hit, detected, family, container, encrypted, has_native_structure = zip_result
    elif detected == "application/pdf":
        family = SourceFamily.DOCUMENT
        container = "pdf"
        pdf = _inspect_pdf(data, review)
        encrypted, corrupted, has_native_text, page_like_units = pdf
        has_native_structure = None if corrupted else True
        has_visual_content = None if corrupted else True
        container_hit = not corrupted
    elif detected:
        family = _MIME_FAMILY.get(detected, SourceFamily.UNKNOWN)
        if family is SourceFamily.IMAGE:
            has_native_text, has_visual_content = False, True
    elif _decodes_as_text(data):
        detected = _EXTENSION_TEXT_MIME.get(extension) or (
            declared if declared in _TEXT_MIME_FAMILY else "text/plain"
        )
        family = _TEXT_MIME_FAMILY.get(detected, SourceFamily.DOCUMENT)
        has_native_text = bool(data.strip())
        has_native_structure = detected in {"application/json", "application/xml", "text/html"}
        has_visual_content = False
    else:
        detected = "application/octet-stream"
        review.append("UNRECOGNIZED_BINARY")

    zip_family = detected.startswith("application/zip")
    if declared and detected and declared != detected and not zip_family:
        review.append("DECLARED_MIME_MISMATCH")
    if extension and detected and _EXTENSION_TEXT_MIME.get(extension, detected) != detected:
        review.append("EXTENSION_MISMATCH")

    if extension in _VALIDATED_EXTENSIONS:
        try:
            validate_source(
                filename=source.filename,
                declared_mime=source.declared_mime,
                data=data,
                limits=limits or ParserLimits(),
            )
        except StructuredParseError as error:
            review.append(error.code)
            if error.code in {"ARCHIVE_ENCRYPTED_ENTRY", "ENCRYPTED_PDF"}:
                encrypted = True
            else:
                corrupted = True

    confidence = 0.0
    if magic_hit:
        confidence += 0.4
    if container_hit:
        confidence += 0.3
    if declared and declared == detected:
        confidence += 0.2
    if not review:
        confidence += 0.1

    return SourceInspection(
        detected_mime=detected,
        source_family=family,
        container_kind=container,
        encrypted=encrypted,
        corrupted=corrupted,
        has_native_text=has_native_text,
        has_native_structure=has_native_structure,
        has_visual_content=has_visual_content,
        page_like_units=page_like_units,
        confidence=round(min(confidence, 1.0), 3),
        review_reasons=tuple(review),
    )


def _inspect_zip(
    data: bytes, review: list[str]
) -> tuple[bool, str, SourceFamily, str | None, bool, bool | None] | None:
    """Sniff a ZIP package without extracting a member (§8.1 steps 4, 5, 6, 10)."""
    if b"PK\x05\x06" not in data[-66_000:]:
        review.append("ZIP_TRUNCATED")
        return None
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            names = [entry.filename.replace("\\", "/").casefold() for entry in entries]
            encrypted = any(entry.flag_bits & 0x1 for entry in entries)
            uncompressed = sum(entry.file_size for entry in entries)
            compressed = sum(entry.compress_size for entry in entries)
    except (OSError, zipfile.BadZipFile, NotImplementedError):
        review.append("ZIP_UNREADABLE")
        return None

    if encrypted:
        review.append("ARCHIVE_ENCRYPTED_ENTRY")
    if uncompressed / max(compressed, 1) > _MAX_COMPRESSION_RATIO:
        review.append("ARCHIVE_RATIO_RISK")
    if not entries:
        review.append("ARCHIVE_EMPTY")

    for marker, kind, mime, family in _ZIP_PACKAGE:
        if any(name.startswith(marker) or name == marker for name in names):
            has_structure = None if encrypted else True
            return True, mime, family, kind, encrypted, has_structure
    return True, "application/zip", SourceFamily.ARCHIVE, "zip", encrypted, None


def _inspect_pdf(data: bytes, review: list[str]) -> tuple[bool, bool, bool | None, int | None]:
    """Return (encrypted, corrupted, has_native_text, page_like_units)."""
    if b"%%EOF" not in data[-2048:]:
        review.append("PDF_TRUNCATED")
        return False, True, None, None
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted:
            review.append("ENCRYPTED_PDF")
            # Page and text facts are unreadable behind encryption; do not guess.
            return True, False, None, None
        pages = len(reader.pages)
        has_text = any(bool(page.extract_text().strip()) for page in reader.pages[:5])
    except Exception as error:  # pypdf raises a wide, undeclared set on hostile input
        review.append(f"PDF_UNREADABLE:{type(error).__name__}")
        return False, True, None, None
    if pages == 0:
        review.append("PDF_NO_PAGES")
    return False, False, has_text, pages
