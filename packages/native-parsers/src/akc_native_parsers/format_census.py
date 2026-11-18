"""Declared format census across the Core gates (G1 upload, G2 analysis, parse path).

The census is data. ``tests/test_format_census.py`` drives every row through the
real gates, so a gate that drifts from this declaration fails a test instead of
silently skipping or accepting a format. It makes no claim about the Product
path (Foundation CDR image), which is a different entry path.

``python -m akc_native_parsers.format_census`` prints the census as canonical JSON.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

NATIVE_CIR = "native_cir"
LEGACY_TEXT = "legacy_text_structure_lost"
RASTER = "raster_visual_route"
REFUSED = "refused"

G1_ACCEPT = "accept"
G2_ACCEPT = "accept"
G2_REFUSE = "UNSUPPORTED_FILE"


@dataclass(frozen=True, slots=True)
class CensusRow:
    id: str
    label: str
    extensions: tuple[str, ...]
    g1: str  # "accept" or the exact refusal reason code
    g2: str  # "accept" or the exact refusal reason code
    parse_path: str
    remediation: str = ""
    notes: str = ""


def _refused(
    id_: str, label: str, extensions: tuple[str, ...], g1: str, remediation: str, notes: str = ""
) -> CensusRow:
    return CensusRow(id_, label, extensions, g1, G2_REFUSE, REFUSED, remediation, notes)


CENSUS: tuple[CensusRow, ...] = (
    CensusRow(
        "pdf",
        "PDF (text layer or scan)",
        (".pdf",),
        G1_ACCEPT,
        G2_ACCEPT,
        NATIVE_CIR,
        notes="text-layer and image-only PDFs share the parser; scans take the visual route; "
        "D-1 strata #1 and #2 merged under the one-row-per-extension rule",
    ),
    CensusRow("docx", "DOCX", (".docx",), G1_ACCEPT, G2_ACCEPT, NATIVE_CIR),
    CensusRow("xlsx", "XLSX", (".xlsx",), G1_ACCEPT, G2_ACCEPT, NATIVE_CIR),
    CensusRow("pptx", "PPTX", (".pptx",), G1_ACCEPT, G2_ACCEPT, NATIVE_CIR),
    CensusRow("html", "HTML", (".html", ".htm"), G1_ACCEPT, G2_ACCEPT, NATIVE_CIR),
    CensusRow("subtitles", "Subtitles", (".srt", ".vtt"), G1_ACCEPT, G2_ACCEPT, NATIVE_CIR),
    CensusRow(
        "csv",
        "CSV",
        (".csv",),
        G1_ACCEPT,
        G2_ACCEPT,
        LEGACY_TEXT,
        notes="accepted, structure lost: cells are flattened to page text",
    ),
    CensusRow("text", "Plain text / Markdown", (".txt", ".md"), G1_ACCEPT, G2_ACCEPT, LEGACY_TEXT),
    CensusRow(
        "raster",
        "Raster image",
        (".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"),
        G1_ACCEPT,
        G2_ACCEPT,
        RASTER,
        notes="no text layer; OCR route",
    ),
    _refused(
        "opendocument",
        "OpenDocument",
        (".odt", ".ods", ".odp"),
        "extension_not_allowed",
        "Export to PDF or DOCX/XLSX/PPTX and upload that.",
    ),
    _refused(
        "legacy_office",
        "Legacy / macro Office",
        (".doc", ".xls", ".ppt", ".docm", ".xlsm", ".pptm"),
        "extension_blocked",
        "Save as DOCX/XLSX/PPTX without macros, or export to PDF.",
    ),
    _refused(
        "hwp",
        "Korean HWP family",
        (".hwp", ".hwpx", ".hml"),
        "extension_not_allowed",
        "Export to PDF and upload that.",
        "no reader exists; stays refused until the Korean lane passes its gate",
    ),
    _refused(
        "email",
        "Email",
        (".eml", ".msg"),
        "extension_not_allowed",
        "Print the message to PDF and upload that.",
    ),
    _refused(
        "archive",
        "Archive",
        (".zip", ".rar", ".7z"),
        "extension_blocked",
        "Extract the archive and upload its documents.",
    ),
    _refused(
        "active_or_ebook",
        "SVG / ebook",
        (".svg", ".epub"),
        "extension_blocked",
        "Export to PDF and upload that.",
    ),
    _refused(
        "other",
        "Everything else (sampled)",
        (".gif", ".exe", ".mp4", ".dwg"),
        "extension_not_allowed",
        "Convert to a supported format.",
        "open set; only the sampled extensions are asserted",
    ),
)

CONDITIONS: tuple[dict[str, str], ...] = (
    {
        "id": "mime_mismatch",
        "g1": "claimed_mime_mismatch",
        "native": "MIME_MISMATCH",
        "g2": "MIME_MISMATCH",
        "reason_quality": "specific",
    },
    {
        "id": "bad_magic",
        "g1": "file_signature_mismatch",
        "native": "MAGIC_MISMATCH",
        "g2": "MAGIC_MISMATCH",
        "reason_quality": "specific",
    },
    {
        "id": "locked",
        "pdf": "ENCRYPTED_PDF",
        "ooxml_g1": "file_signature_mismatch",
        "reason_quality": "generic",
        "note": "a password-protected OOXML is an OLE file, reported only as a signature mismatch",
    },
    {"id": "huge", "g1": "file_too_large", "g2": "FILE_TOO_LARGE", "reason_quality": "specific"},
    {
        "id": "malformed",
        "ooxml_g1": "archive_invalid",
        "note": "a broken container is archive_invalid; ooxml_* codes cover content-level faults",
        "reason_quality": "specific",
    },
    {
        "id": "lying_member_size",
        "g1": "zipfile's own message, e.g. Bad CRC-32 for file 'word/document.xml' (unstable)",
        "native": "unwrapped zipfile.BadZipFile",
        "expect": "never a successful parse",
        "reason_quality": "generic",
    },
)


def census_json() -> str:
    return json.dumps(
        {"rows": [asdict(row) for row in CENSUS], "conditions": list(CONDITIONS)},
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    )


if __name__ == "__main__":
    print(census_json())
