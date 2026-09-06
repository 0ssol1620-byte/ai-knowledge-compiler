"""Reader provider plane — the plug-in layer above the native parsers.

Readers are resolved by capability and failure class, never by provider or
model name. See `docs/architecture/reader-provider-plane.md`.
"""

from .enums import (
    CAPABILITY_STATUS_ACCEPTED_AT_UPLOAD,
    FAILURE_CLASSES_WITHOUT_FAILURE_CODE,
    FAILURE_CODE_TO_CLASS,
    FAILURE_CODES_WITHOUT_FAILURE_CLASS,
    FEATURE_TO_FAILURE_CLASS,
    CapabilityStatus,
    FailureClass,
    LocatorKind,
    ReaderFeature,
    ReaderRegistryStatus,
    RepresentationKind,
    SourceFamily,
)
from .inspector import inspect_source
from .models import (
    ExtractedUnit,
    NativeExtraction,
    ReaderCapability,
    ReaderHealth,
    ReaderInput,
    ReaderRegistryEntry,
    ReaderResolution,
    ReaderRun,
    SourceInspection,
    digest_units,
)
from .providers import LegacyPdfV1, PlainTextV1
from .registry import (
    OPERATIONAL_FAILURE_CLASSES,
    SEMANTIC_FAILURE_CLASSES,
    ReaderProvider,
    ReaderRegistrationError,
    ReaderRegistry,
    VisualReaderProvider,
    validate_evidence_locator,
)

__all__ = [
    "CAPABILITY_STATUS_ACCEPTED_AT_UPLOAD",
    "FAILURE_CLASSES_WITHOUT_FAILURE_CODE",
    "FAILURE_CODES_WITHOUT_FAILURE_CLASS",
    "FAILURE_CODE_TO_CLASS",
    "FEATURE_TO_FAILURE_CLASS",
    "OPERATIONAL_FAILURE_CLASSES",
    "SEMANTIC_FAILURE_CLASSES",
    "CapabilityStatus",
    "ExtractedUnit",
    "FailureClass",
    "LegacyPdfV1",
    "LocatorKind",
    "NativeExtraction",
    "PlainTextV1",
    "ReaderCapability",
    "ReaderFeature",
    "ReaderHealth",
    "ReaderInput",
    "ReaderProvider",
    "ReaderRegistrationError",
    "ReaderRegistry",
    "ReaderRegistryEntry",
    "ReaderRegistryStatus",
    "ReaderResolution",
    "ReaderRun",
    "RepresentationKind",
    "SourceFamily",
    "SourceInspection",
    "VisualReaderProvider",
    "digest_units",
    "inspect_source",
    "validate_evidence_locator",
]
