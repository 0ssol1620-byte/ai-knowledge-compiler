"""Frozen USKC vocabulary, transliterated from ``contract/enums.v1.json``.

The JSON file is a verbatim copy of the campaign contract artifact
(`USKC_LANE_CONTRACT_2026-09-06.md` §4.0). ``test_frozen_contract.py`` pins its
sha256 and asserts every StrEnum below carries exactly the frozen value list, so
a hand edit here fails the suite rather than silently forking the vocabulary.
"""

from __future__ import annotations

import json
from enum import StrEnum
from functools import cache
from importlib.resources import files
from typing import Any

from akc_cir.inspection import FailureCode

ENUMS_JSON = "contract/enums.v1.json"
EVIDENCE_LOCATOR_SCHEMA_JSON = "contract/evidence-locator.v2.schema.json"


@cache
def frozen_contract(resource: str) -> dict[str, Any]:
    """Load one bundled frozen contract artifact."""
    payload = files(__package__).joinpath(resource).read_text(encoding="utf-8")
    loaded: dict[str, Any] = json.loads(payload)
    return loaded


class SourceFamily(StrEnum):
    DOCUMENT = "document"
    SPREADSHEET = "spreadsheet"
    PRESENTATION = "presentation"
    IMAGE = "image"
    EMAIL = "email"
    STRUCTURED_DATA = "structured_data"
    WEB = "web"
    CODE = "code"
    CAD_2D = "cad_2d"
    CAD_3D = "cad_3d"
    BIM = "bim"
    AUDIO = "audio"
    VIDEO = "video"
    ARCHIVE = "archive"
    DATABASE = "database"
    API = "api"
    UNKNOWN = "unknown"


class CapabilityStatus(StrEnum):
    VERIFIED_NATIVE = "VERIFIED_NATIVE"
    VERIFIED_HYBRID = "VERIFIED_HYBRID"
    BEST_EFFORT = "BEST_EFFORT"
    METADATA_ONLY = "METADATA_ONLY"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    UNSUPPORTED = "UNSUPPORTED"


class RepresentationKind(StrEnum):
    ORIGINAL = "original"
    NATIVE = "native"
    RENDERED = "rendered"
    OCR = "ocr"
    VISUAL = "visual"
    NORMALIZED = "normalized"
    CANONICAL_IR = "canonical_ir"


class ReaderFeature(StrEnum):
    NATIVE_TEXT = "native_text"
    LAYOUT = "layout"
    TABLES = "tables"
    FORMULA = "formula"
    COMMENTS = "comments"
    TRACK_CHANGES = "track_changes"
    CHART_DATA = "chart_data"
    GEOMETRY = "geometry"
    ASSEMBLY = "assembly"
    ACL = "acl"
    THREAD = "thread"
    TIMESTAMP = "timestamp"
    AST = "ast"
    DEPENDENCY_GRAPH = "dependency_graph"


class LocatorKind(StrEnum):
    PDF = "pdf"
    IMAGE = "image"
    DOCX = "docx"
    XLSX = "xlsx"
    PPTX = "pptx"
    EMAIL = "email"
    JSON = "json"
    XML = "xml"
    CODE = "code"
    CAD = "cad"
    MEDIA = "media"
    DATABASE = "database"
    API = "api"


class ReaderRegistryStatus(StrEnum):
    CANDIDATE = "candidate"
    QUALIFIED = "qualified"
    RETIRED = "retired"


class FailureClass(StrEnum):
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


CAPABILITY_STATUS_ACCEPTED_AT_UPLOAD: frozenset[CapabilityStatus] = frozenset(
    {
        CapabilityStatus.VERIFIED_NATIVE,
        CapabilityStatus.VERIFIED_HYBRID,
        CapabilityStatus.BEST_EFFORT,
        CapabilityStatus.METADATA_ONLY,
    }
)

VERIFIED_STATUSES: frozenset[CapabilityStatus] = frozenset(
    {CapabilityStatus.VERIFIED_NATIVE, CapabilityStatus.VERIFIED_HYBRID}
)

# Blueprint §45 taxonomy against the existing `akc_cir.inspection.FailureCode`
# F0-F48. Shipped as data, not as a claim of equivalence: the mapping is lossy
# in both directions and the two gap tuples below name exactly where.
# `akc_cir.inspection` is Protected Core and is imported, never modified.
FAILURE_CODE_TO_CLASS: dict[FailureCode, FailureClass] = {
    FailureCode.F0_SOURCE_CORRUPT: FailureClass.CORRUPT_SOURCE,
    FailureCode.F1_SOURCE_UNSUPPORTED: FailureClass.UNSUPPORTED_FORMAT,
    FailureCode.F3_QUEUE_TIMEOUT: FailureClass.PARSER_TIMEOUT,
    FailureCode.F4_WORKER_LOST: FailureClass.PROVIDER_UNAVAILABLE,
    FailureCode.F5_MODEL_INIT: FailureClass.PROVIDER_UNAVAILABLE,
    FailureCode.F6_MODEL_OOM: FailureClass.PARSER_OOM,
    FailureCode.F8_EMPTY_OUTPUT: FailureClass.EMPTY_OUTPUT,
    FailureCode.F11_GARBLED_TEXT: FailureClass.TEXT_OMISSION,
    FailureCode.F12_READING_ORDER: FailureClass.LAYOUT_FAILURE,
    FailureCode.F13_TABLE_STRUCTURE: FailureClass.TABLE_FAILURE,
    FailureCode.F14_FORMULA: FailureClass.FORMULA_FAILURE,
    FailureCode.F17_NATIVE_RENDER_DISAGREEMENT: FailureClass.NATIVE_VISUAL_DISAGREEMENT,
    FailureCode.F19_ENTITY_AMBIGUITY: FailureClass.IDENTITY_UNRESOLVED,
    FailureCode.F22_LINEAGE_BROKEN: FailureClass.EVIDENCE_BROKEN,
    FailureCode.F24_RECOMPILE_DIVERGENCE: FailureClass.EQUIVALENCE_FAILED,
    FailureCode.F25_PERMISSION_VIOLATION: FailureClass.ACL_UNRESOLVED,
    FailureCode.F28_SECURITY_BLOCKED: FailureClass.MALWARE_QUARANTINED,
    FailureCode.F45_ACTIVE_CONTENT_OR_MALWARE: FailureClass.MALWARE_QUARANTINED,
    FailureCode.F46_ARTIFACT_CHECKSUM_MISMATCH: FailureClass.RECEIPT_MISMATCH,
    FailureCode.F47_PROVENANCE_SIGNATURE_INVALID: FailureClass.RECEIPT_MISMATCH,
}

#: Frozen §45 classes that no `FailureCode` expresses. Never synthesise one.
#: The seam map named only SOURCE_DELETED and PRESERVATION_FAILED;
#: ENCRYPTED_SOURCE has no F-code either (F28_SECURITY_BLOCKED is a security
#: block, not a password), so the reader plane raises it from the inspector's
#: own encryption fact rather than by translating an F-code.
FAILURE_CLASSES_WITHOUT_FAILURE_CODE: tuple[FailureClass, ...] = (
    FailureClass.ENCRYPTED_SOURCE,
    FailureClass.SOURCE_DELETED,
    FailureClass.PRESERVATION_FAILED,
)

#: `FailureCode` values with no §45 counterpart. A run carrying one of these
#: records `failure_class = None` and keeps the F-code in `escalation_reason`.
FAILURE_CODES_WITHOUT_FAILURE_CLASS: tuple[FailureCode, ...] = tuple(
    code for code in FailureCode if code not in FAILURE_CODE_TO_CLASS
)

# `validate_source()` raises StructuredParseError with these stable codes; the
# inspector turns them into review reasons and, where the meaning is
# unambiguous, a frozen failure class. Anything absent stays REVIEW_REQUIRED.
PARSE_ERROR_TO_CLASS: dict[str, FailureClass] = {
    "FILE_EMPTY": FailureClass.EMPTY_OUTPUT,
    "FILE_TOO_LARGE": FailureClass.UNSUPPORTED_FORMAT,
    "UNSUPPORTED_NON_PDF_TYPE": FailureClass.UNSUPPORTED_FORMAT,
    "MIME_MISMATCH": FailureClass.UNSUPPORTED_FORMAT,
    "MAGIC_MISMATCH": FailureClass.CORRUPT_SOURCE,
    "INVALID_OFFICE_ARCHIVE": FailureClass.CORRUPT_SOURCE,
    "ARCHIVE_ENCRYPTED_ENTRY": FailureClass.ENCRYPTED_SOURCE,
    "OOXML_CONTENT_TYPES_MISSING": FailureClass.CORRUPT_SOURCE,
    "OOXML_PACKAGE_KIND_MISMATCH": FailureClass.UNSUPPORTED_FORMAT,
    "OOXML_UNSAFE_XML": FailureClass.MALWARE_QUARANTINED,
    "OFFICE_ACTIVE_CONTENT": FailureClass.MALWARE_QUARANTINED,
    "OFFICE_EMBEDDED_OBJECT": FailureClass.MALWARE_QUARANTINED,
    "OFFICE_EXTERNAL_RELATION": FailureClass.MALWARE_QUARANTINED,
    "ARCHIVE_PATH_TRAVERSAL": FailureClass.MALWARE_QUARANTINED,
    "ARCHIVE_SYMLINK": FailureClass.MALWARE_QUARANTINED,
    "ARCHIVE_RATIO_LIMIT": FailureClass.MALWARE_QUARANTINED,
    "ARCHIVE_SIZE_LIMIT": FailureClass.MALWARE_QUARANTINED,
    "ARCHIVE_MEMBER_LIMIT": FailureClass.MALWARE_QUARANTINED,
    "ARCHIVE_ENTRY_LIMIT": FailureClass.MALWARE_QUARANTINED,
    "ARCHIVE_DUPLICATE_ENTRY": FailureClass.CORRUPT_SOURCE,
    "ENCRYPTED_PDF": FailureClass.ENCRYPTED_SOURCE,
    "PDF_PASSWORD_INVALID": FailureClass.ENCRYPTED_SOURCE,
    "PDF_PARSE_FAILED": FailureClass.CORRUPT_SOURCE,
}

#: What a run failed at when the caller required a feature the output does not
#: carry. ``read()`` compares ``required_features`` against the *observed*
#: features of the extraction, so a declaration alone never satisfies a
#: requirement. A feature with no specific class falls back to
#: ``PRESERVATION_FAILED``.
FEATURE_TO_FAILURE_CLASS: dict[ReaderFeature, FailureClass] = {
    ReaderFeature.NATIVE_TEXT: FailureClass.TEXT_OMISSION,
    ReaderFeature.LAYOUT: FailureClass.LAYOUT_FAILURE,
    ReaderFeature.TABLES: FailureClass.TABLE_FAILURE,
    ReaderFeature.FORMULA: FailureClass.FORMULA_FAILURE,
}

__all__ = [
    "CAPABILITY_STATUS_ACCEPTED_AT_UPLOAD",
    "ENUMS_JSON",
    "EVIDENCE_LOCATOR_SCHEMA_JSON",
    "FAILURE_CLASSES_WITHOUT_FAILURE_CODE",
    "FAILURE_CODES_WITHOUT_FAILURE_CLASS",
    "FAILURE_CODE_TO_CLASS",
    "FEATURE_TO_FAILURE_CLASS",
    "PARSE_ERROR_TO_CLASS",
    "VERIFIED_STATUSES",
    "CapabilityStatus",
    "FailureClass",
    "LocatorKind",
    "ReaderFeature",
    "ReaderRegistryStatus",
    "RepresentationKind",
    "SourceFamily",
    "frozen_contract",
]
