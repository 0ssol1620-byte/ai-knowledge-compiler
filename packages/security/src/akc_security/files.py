"""Fail-closed upload validation and archive inspection."""

from __future__ import annotations

import hashlib
import io
import os
import re
import stat
import tempfile
import unicodedata
import zipfile
from codecs import getincrementaldecoder
from enum import StrEnum
from pathlib import PurePosixPath, PureWindowsPath
from typing import Annotated, BinaryIO, cast

from akc_cir import ContractModel
from defusedxml import ElementTree
from pydantic import Field

ALLOWED_EXTENSIONS = frozenset(
    {
        ".pdf",
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".tif",
        ".tiff",
        ".docx",
        ".pptx",
        ".xlsx",
        ".csv",
        ".html",
        ".htm",
        ".txt",
        ".md",
        ".vtt",
        ".srt",
    }
)

BLOCKED_EXTENSIONS = frozenset(
    {
        ".doc",
        ".xls",
        ".ppt",
        ".xlsm",
        ".docm",
        ".pptm",
        ".zip",
        ".rar",
        ".7z",
        ".svg",
        ".epub",
    }
)

OOXML_MARKERS = {
    ".docx": "word/",
    ".pptx": "ppt/",
    ".xlsx": "xl/",
}

_EXECUTABLE_EXTENSIONS = frozenset(
    {
        ".app",
        ".bat",
        ".cmd",
        ".com",
        ".cpl",
        ".dll",
        ".dmg",
        ".exe",
        ".gadget",
        ".hta",
        ".inf",
        ".ins",
        ".iso",
        ".jar",
        ".js",
        ".jse",
        ".lnk",
        ".msc",
        ".msi",
        ".msp",
        ".mst",
        ".pif",
        ".ps1",
        ".reg",
        ".scr",
        ".sct",
        ".sh",
        ".sys",
        ".vb",
        ".vbe",
        ".vbs",
        ".ws",
        ".wsc",
        ".wsf",
        ".wsh",
    }
)
_EXECUTABLE_MAGIC = (
    b"MZ",
    b"\x7fELF",
    b"\xca\xfe\xba\xbe",
    b"\xcf\xfa\xed\xfe",
    b"\xce\xfa\xed\xfe",
    b"\xfe\xed\xfa\xcf",
    b"\xfe\xed\xfa\xce",
)
_EXECUTABLE_CONTENT_TYPES = (
    b"application/x-dosexec",
    b"application/x-msdownload",
    b"application/x-msi",
    b"application/vnd.microsoft.portable-executable",
)
_MAX_RELATIONSHIP_BYTES = 2 * 1024 * 1024
_STREAM_CHUNK_BYTES = 1024 * 1024
_TEXT_EXTENSIONS = frozenset({".csv", ".html", ".htm", ".txt", ".md", ".vtt", ".srt"})

EXPECTED_MIME = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".csv": "text/csv",
    ".html": "text/html",
    ".htm": "text/html",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".vtt": "text/vtt",
    ".srt": "application/x-subrip",
}


class PlanTier(StrEnum):
    FREE = "free"
    PRO = "pro"
    TEAM = "team"


class UploadLimits(ContractModel):
    max_file_bytes: Annotated[int, Field(gt=0)]
    max_archive_entries: Annotated[int, Field(gt=0)] = 10_000
    max_archive_uncompressed_bytes: Annotated[int, Field(gt=0)] = 2_000_000_000
    max_compression_ratio: Annotated[float, Field(gt=1.0)] = 100.0


PLAN_LIMITS: dict[PlanTier, UploadLimits] = {
    PlanTier.FREE: UploadLimits(max_file_bytes=50 * 1024 * 1024),
    PlanTier.PRO: UploadLimits(max_file_bytes=250 * 1024 * 1024),
    PlanTier.TEAM: UploadLimits(max_file_bytes=1024 * 1024 * 1024),
}


class FileValidationResult(ContractModel):
    accepted: bool
    normalized_filename: str
    extension: str
    detected_mime: str | None = None
    sha256: str | None = None
    reason_code: str | None = None
    warnings: tuple[str, ...] = ()


class UnsafeFileError(ValueError):
    def __init__(self, result: FileValidationResult) -> None:
        super().__init__(result.reason_code or "unsafe_file")
        self.result = result


def sanitize_display_filename(filename: str, *, max_length: int = 120) -> str:
    normalized = unicodedata.normalize("NFKC", filename).replace("\x00", "")
    normalized = PureWindowsPath(normalized).name
    normalized = PurePosixPath(normalized).name
    normalized = "".join(
        character for character in normalized if not unicodedata.category(character).startswith("C")
    )
    normalized = re.sub(r'[<>:"/\\|?*]+', "_", normalized).strip(" .")
    if not normalized:
        normalized = "upload"
    stem, suffix = os.path.splitext(normalized)
    reserved = {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{index}" for index in range(1, 10)),
        *(f"LPT{index}" for index in range(1, 10)),
    }
    if stem.upper() in reserved:
        stem = f"_{stem}"
    available = max(1, max_length - len(suffix))
    return f"{stem[:available]}{suffix[:20]}"


def safe_relative_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    candidate = PurePosixPath(normalized)
    if (
        not normalized
        or candidate.is_absolute()
        or any(part in {"", ".", ".."} for part in candidate.parts)
        or ":" in candidate.parts[0]
    ):
        raise ValueError("path must be a normalized relative path")
    return candidate.as_posix()


def tenant_object_key(tenant_id: str, object_id: str, *, category: str = "source") -> str:
    for component in (tenant_id, object_id, category):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{2,127}", component):
            raise ValueError("object-key components must be opaque safe identifiers")
    return f"tenants/{tenant_id}/{category}/{object_id}"


def _detected_mime(extension: str, data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"II*\x00", b"MM\x00*")):
        return "image/tiff"
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    if data.startswith(b"PK\x03\x04"):
        return EXPECTED_MIME.get(extension) if extension in OOXML_MARKERS else "application/zip"
    if extension in _TEXT_EXTENSIONS:
        return EXPECTED_MIME[extension]
    return None


def _is_executable_payload(prefix: bytes) -> bool:
    stripped = prefix.lstrip(b"\xef\xbb\xbf\t\r\n ")
    return stripped.startswith(_EXECUTABLE_MAGIC) or stripped.startswith(b"#!")


def _validate_relationship_xml(payload: bytes) -> None:
    if len(payload) > _MAX_RELATIONSHIP_BYTES:
        raise ValueError("ooxml_relationship_too_large")
    upper = payload.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise ValueError("ooxml_relationship_unsafe_xml")
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError as exc:
        raise ValueError("ooxml_relationship_invalid") from exc
    for relationship in root.iter():
        if relationship.tag.rsplit("}", 1)[-1].casefold() != "relationship":
            continue
        attributes = {
            name.rsplit("}", 1)[-1].casefold(): value for name, value in relationship.attrib.items()
        }
        target_mode = attributes.get("targetmode", "")
        target = attributes.get("target", "").strip()
        if (
            target_mode.strip().casefold() == "external"
            or target.startswith(("//", "\\\\"))
            or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", target)
        ):
            raise ValueError("ooxml_external_relationship")


def _validate_ooxml(
    archive_source: BinaryIO,
    extension: str,
    limits: UploadLimits,
) -> tuple[str, ...]:
    try:
        archive = zipfile.ZipFile(archive_source)
    except (zipfile.BadZipFile, OSError) as exc:
        raise ValueError("archive_invalid") from exc
    with archive:
        entries = archive.infolist()
        if len(entries) > limits.max_archive_entries:
            raise ValueError("archive_entry_limit")
        names: set[str] = set()
        folded_names: set[str] = set()
        uncompressed_total = 0
        compressed_total = 0
        for entry in entries:
            name = entry.filename.replace("\\", "/")
            safe_relative_path(name.rstrip("/"))
            folded_name = name.casefold()
            if name in names or folded_name in folded_names:
                raise ValueError("archive_duplicate_entry")
            names.add(name)
            folded_names.add(folded_name)
            mode = entry.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise ValueError("archive_symlink")
            if entry.flag_bits & 0x1:
                raise ValueError("archive_encrypted_entry")
            uncompressed_total += entry.file_size
            compressed_total += entry.compress_size
            if entry.file_size > limits.max_archive_uncompressed_bytes:
                raise ValueError("archive_entry_too_large")
            if folded_name.endswith("vbaproject.bin"):
                raise ValueError("archive_macro_payload")
            if PurePosixPath(folded_name).suffix in _EXECUTABLE_EXTENSIONS:
                raise ValueError("archive_embedded_executable")
        if uncompressed_total > limits.max_archive_uncompressed_bytes:
            raise ValueError("archive_uncompressed_limit")
        ratio = uncompressed_total / max(compressed_total, 1)
        if ratio > limits.max_compression_ratio:
            raise ValueError("archive_compression_ratio")
        if "[Content_Types].xml" not in names:
            raise ValueError("ooxml_content_types_missing")
        marker = OOXML_MARKERS[extension]
        if not any(name.startswith(marker) for name in names):
            raise ValueError("ooxml_package_kind_mismatch")

        for entry in entries:
            if entry.is_dir():
                continue
            folded_name = entry.filename.replace("\\", "/").casefold()
            with archive.open(entry, "r") as member:
                if folded_name.endswith(".rels"):
                    payload = member.read(_MAX_RELATIONSHIP_BYTES + 1)
                    _validate_relationship_xml(payload)
                    continue
                if folded_name == "[content_types].xml":
                    prefix = member.read(_MAX_RELATIONSHIP_BYTES + 1)
                    if len(prefix) > _MAX_RELATIONSHIP_BYTES:
                        raise ValueError("ooxml_content_types_too_large")
                else:
                    prefix = member.read(4096)
            if _is_executable_payload(prefix):
                raise ValueError("archive_embedded_executable")
            if "/embeddings/" in f"/{folded_name}" and prefix.startswith(
                b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
            ):
                # OLE Package streams can hide an executable behind a benign .bin
                # filename. They stay quarantined until a dedicated CDR scanner
                # proves the embedded object safe.
                raise ValueError("archive_embedded_object_quarantined")
            if folded_name == "[content_types].xml" and any(
                marker in prefix.lower() for marker in _EXECUTABLE_CONTENT_TYPES
            ):
                raise ValueError("archive_embedded_executable")
    return ()


def _invalid_result(
    *,
    normalized: str,
    extension: str,
    reason_code: str,
    detected_mime: str | None = None,
) -> FileValidationResult:
    return FileValidationResult(
        accepted=False,
        normalized_filename=normalized,
        extension=extension,
        detected_mime=detected_mime,
        reason_code=reason_code,
    )


def _validate_utf8_stream(stream: BinaryIO) -> None:
    stream.seek(0)
    decoder = getincrementaldecoder("utf-8-sig")(errors="strict")
    while chunk := stream.read(_STREAM_CHUNK_BYTES):
        decoder.decode(chunk, final=False)
    decoder.decode(b"", final=True)


def validate_upload_stream(
    filename: str,
    stream: BinaryIO,
    *,
    tier: PlanTier = PlanTier.FREE,
    claimed_content_type: str | None = None,
) -> FileValidationResult:
    """Validate an upload without trusting or fully buffering the caller's stream.

    The input is copied into a bounded spooled file while hashing. OOXML members
    are then inspected from that seekable quarantine copy. No parser-facing
    object should be promoted unless this result is accepted.
    """

    normalized = sanitize_display_filename(filename)
    extension = PurePosixPath(normalized.casefold()).suffix
    if extension in BLOCKED_EXTENSIONS:
        return _invalid_result(
            normalized=normalized,
            extension=extension,
            reason_code="extension_blocked",
        )
    if extension not in ALLOWED_EXTENSIONS:
        return _invalid_result(
            normalized=normalized,
            extension=extension,
            reason_code="extension_not_allowed",
        )
    limits = PLAN_LIMITS[tier]
    hasher = hashlib.sha256()
    total = 0
    with tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b") as quarantine:
        while True:
            chunk = stream.read(_STREAM_CHUNK_BYTES)
            if not chunk:
                break
            total += len(chunk)
            if total > limits.max_file_bytes:
                return _invalid_result(
                    normalized=normalized,
                    extension=extension,
                    reason_code="file_too_large",
                )
            hasher.update(chunk)
            quarantine.write(chunk)
        if total == 0:
            return _invalid_result(
                normalized=normalized,
                extension=extension,
                reason_code="file_empty",
            )

        quarantine.seek(0)
        header = quarantine.read(8192)
        detected = _detected_mime(extension, header)
        expected = EXPECTED_MIME[extension]
        if detected != expected:
            return _invalid_result(
                normalized=normalized,
                extension=extension,
                detected_mime=detected,
                reason_code="file_signature_mismatch",
            )
        if claimed_content_type:
            normalized_claim = claimed_content_type.split(";", 1)[0].strip().casefold()
            if normalized_claim not in {expected, "application/octet-stream"}:
                return _invalid_result(
                    normalized=normalized,
                    extension=extension,
                    detected_mime=detected,
                    reason_code="claimed_mime_mismatch",
                )
        if extension in _TEXT_EXTENSIONS:
            try:
                _validate_utf8_stream(cast(BinaryIO, quarantine))
            except UnicodeDecodeError:
                return _invalid_result(
                    normalized=normalized,
                    extension=extension,
                    detected_mime=None,
                    reason_code="file_signature_mismatch",
                )
        if extension in OOXML_MARKERS:
            quarantine.seek(0)
            try:
                warnings = _validate_ooxml(cast(BinaryIO, quarantine), extension, limits)
            except (OSError, ValueError, zipfile.BadZipFile) as exc:
                return _invalid_result(
                    normalized=normalized,
                    extension=extension,
                    detected_mime=detected,
                    reason_code=str(exc),
                )
        else:
            warnings = ()
        return FileValidationResult(
            accepted=True,
            normalized_filename=normalized,
            extension=extension,
            detected_mime=detected,
            sha256=f"sha256:{hasher.hexdigest()}",
            warnings=warnings,
        )


def validate_upload_bytes(
    filename: str,
    data: bytes,
    *,
    tier: PlanTier = PlanTier.FREE,
    claimed_content_type: str | None = None,
) -> FileValidationResult:
    return validate_upload_stream(
        filename,
        io.BytesIO(data),
        tier=tier,
        claimed_content_type=claimed_content_type,
    )


def require_valid_upload(
    filename: str,
    data: bytes,
    *,
    tier: PlanTier = PlanTier.FREE,
    claimed_content_type: str | None = None,
) -> FileValidationResult:
    result = validate_upload_bytes(
        filename,
        data,
        tier=tier,
        claimed_content_type=claimed_content_type,
    )
    if not result.accepted:
        raise UnsafeFileError(result)
    return result
