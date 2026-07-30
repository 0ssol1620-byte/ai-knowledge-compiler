"""Rights-aware benchmark source acquisition adapters."""

from .dart import (
    DART_CONFIRMATION,
    DartApiError,
    DartClient,
    DartDisclosure,
    acquire_disclosures,
    load_dart_api_key,
)

__all__ = [
    "DART_CONFIRMATION",
    "DartApiError",
    "DartClient",
    "DartDisclosure",
    "acquire_disclosures",
    "load_dart_api_key",
]
