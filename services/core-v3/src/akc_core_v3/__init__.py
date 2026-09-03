"""Reference Core v3 revision-compile service.

The Product has always called the compiler over HTTP, and until now no source in
either repository implemented the other end. `python_core_v2_configured` on
`/api/status` reports only that a URL and an HMAC secret are present -- it is a
configuration check, not a reachability one -- so the contract the Product
validates was, in this tree, a contract with nothing.

This package is that other end for the revision path: HMAC verification, the v3
request and response shapes, and a handler that runs `akc_cir.revision_compile`
and seals the result. It is deliberately built on `http.server` and the standard
library so a test can start it in a subprocess in milliseconds and so nothing
about the contract depends on a framework.

It resolves documents and dependency edges through injected callables rather than
reaching for object storage itself, which is what lets the end-to-end test drive
the real client against the real compiler without a bucket.
"""

from .contract import CANONICAL_FLOAT_REFUSED, canonicalize, digest
from .service import (
    REQUEST_SCHEMA,
    RESPONSE_SCHEMA,
    RevisionRefused,
    RevisionService,
    SourceResolution,
)

__all__ = [
    "CANONICAL_FLOAT_REFUSED",
    "REQUEST_SCHEMA",
    "RESPONSE_SCHEMA",
    "RevisionRefused",
    "RevisionService",
    "SourceResolution",
    "canonicalize",
    "digest",
]
