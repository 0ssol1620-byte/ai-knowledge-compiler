"""Screening of an untrusted object sitting in the quarantine bucket.

ADR-004 makes every uploaded byte pass the same gauntlet before it is promoted
out of quarantine: structural validation against the declared filename and MIME,
a checksum comparison against what the client committed to, a malware scan, and
- where configured - content disarm and reconstruction. ADR-006 then added a
second caller: an anonymous visitor dropping a file on the marketing hero.

Two callers with one gauntlet is the whole reason this module exists. The
alternative considered in ADR-006 was to have the trial route call the
authenticated handler with a synthesized principal, which would have put a
manufactured identity on the one path that has no identity. Extracting the
screening instead keeps the checks in one place and lets each caller keep its
own bookkeeping.

The seam is drawn at what the two callers share. Screening is about the object:
it needs the bytes, the declared metadata, and the plan tier that sets the size
and type limits. It is not about the account, so nothing here reads a principal,
writes an audit row, or touches the database. What each caller does with a
verdict - which document it belongs to, whose audit log records the rejection,
whether a duplicate is billable - stays with the caller.

Two consequences of that seam are decisions rather than omissions:

  Infrastructure failures raise ``QuarantineUnavailable`` rather than returning
  a verdict or raising ``HTTPException`` directly. A scanner that cannot be
  reached is not a verdict about the file, and every caller wants to audit it
  under its own identity before answering 503. The exception carries the audit
  action name so the two call sites cannot drift apart on what they record.

  ``after_validation`` exists for the free-tier duplicate check, which is
  billing policy rather than screening and applies only to the authenticated
  route. It runs where it ran before the extraction - after the digest is known,
  before the malware scan - because the point of that ordering is to not spend a
  scan on a file that is about to be refused for another reason.

Rejections, by contrast, are returned rather than raised. A file that fails
validation, mismatches its checksum, carries malware, or is refused by CDR is a
legitimate outcome of screening, and both callers respond by recording
``SECURITY_REJECTED`` against their own document row.
"""

from __future__ import annotations

import base64
import secrets
import tempfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, BinaryIO, cast

from akc_security import (
    CdrRequest,
    CdrResult,
    CdrStatus,
    PlanTier,
    validate_cdr_result,
    validate_upload_stream,
)
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException

from akc_api.malware import (
    MalwareDetectedError,
    MalwareScanError,
    scan_quarantined_stream,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from akc_api.settings import Settings
    from akc_api.storage import ObjectMetadata, ObjectStore

# Matches the threshold the authenticated route used before this extraction.
# Below it the staged copy is held in memory; above it, it spills to a temporary
# file rather than growing the process.
SPOOL_MAX_BYTES = 8 * 1024 * 1024

__all__ = [
    "SPOOL_MAX_BYTES",
    "QuarantineUnavailable",
    "QuarantineVerdict",
    "screen_quarantined_object",
]


@dataclass(frozen=True, slots=True)
class QuarantineVerdict:
    """What screening concluded about one quarantined object.

    ``rejection_code`` is ``None`` when the object passed every check. Otherwise
    it is the machine-readable reason, which is what callers record against the
    document and return to the client.
    """

    rejection_code: str | None
    digest: str
    scan_status: str
    cdr_result: CdrResult | None
    # What the object store reported, not what the upload session declared.
    # ``_assert_metadata_matches`` has already proved the two agree, but the
    # promotion path records the size of the object it is promoting, and that
    # is this one.
    size_bytes: int
    # The extension validation resolved from the content, which is not always
    # the one the filename claimed. Empty when the object was rejected before
    # validation could determine it.
    extension: str

    @property
    def accepted(self) -> bool:
        return self.rejection_code is None


class QuarantineUnavailable(Exception):
    """A dependency screening needs could not be reached.

    Distinct from a rejection: nothing was concluded about the file, so it must
    not be promoted, and it must not be marked ``SECURITY_REJECTED`` either. The
    caller audits ``audit_action`` under its own identity and answers 503 with
    ``code``.
    """

    def __init__(self, *, audit_action: str, code: str) -> None:
        super().__init__(code)
        self.audit_action = audit_action
        self.code = code


async def screen_quarantined_object(
    *,
    object_store: ObjectStore,
    cdr_adapter: Any,
    settings: Settings,
    object_key: str,
    safe_filename: str,
    expected_size: int,
    expected_mime: str,
    expected_sha256: str,
    upload_mode: str,
    tier: PlanTier,
    after_validation: Callable[[str], Awaitable[None]] | None = None,
) -> QuarantineVerdict:
    """Run the ADR-004 gauntlet over one quarantined object.

    Raises ``HTTPException`` for a client-caused precondition failure - the
    object is missing, or its stored metadata contradicts what the upload
    session recorded - and ``QuarantineUnavailable`` when a scanner or CDR
    service cannot answer. Returns a verdict in every other case.
    """
    metadata = await _head_quarantine(object_store, object_key)
    _assert_metadata_matches(
        metadata,
        expected_size=expected_size,
        expected_mime=expected_mime,
        expected_sha256=expected_sha256,
        upload_mode=upload_mode,
    )

    rejection_code: str | None = None
    scan_status = ""
    cdr_result: CdrResult | None = None
    with tempfile.SpooledTemporaryFile(max_size=SPOOL_MAX_BYTES, mode="w+b") as staged:
        await object_store.download_quarantine(object_key, cast(BinaryIO, staged))
        validation = validate_upload_stream(
            safe_filename,
            cast(BinaryIO, staged),
            tier=tier,
            claimed_content_type=expected_mime,
        )
        digest = (validation.sha256 or "").removeprefix("sha256:")
        if not validation.accepted:
            rejection_code = validation.reason_code or "UNSAFE_FILE"
        elif not secrets.compare_digest(digest, expected_sha256):
            rejection_code = "CHECKSUM_MISMATCH"

        # The authenticated route's free-tier duplicate check runs here, between
        # a known digest and a not-yet-spent malware scan. It may raise.
        if rejection_code is None and after_validation is not None:
            await after_validation(digest)

        if rejection_code is None:
            staged.seek(0)
            try:
                scan = await scan_quarantined_stream(cast(BinaryIO, staged), settings)
                scan_status = scan.status
            except MalwareDetectedError:
                rejection_code = "MALWARE_DETECTED"
            except MalwareScanError as exc:
                raise QuarantineUnavailable(
                    audit_action="document.security_scan_unavailable",
                    code="ANTIVIRUS_UNAVAILABLE",
                ) from exc

        mime_type = expected_mime.split(";", 1)[0].strip().casefold()
        if (
            rejection_code is None
            and settings.cdr_enabled
            and mime_type in settings.cdr_supported_mimes
        ):
            rejection_code, cdr_result = await _disarm(
                staged,
                cdr_adapter=cdr_adapter,
                settings=settings,
                safe_filename=safe_filename,
                mime_type=mime_type,
                digest=digest,
            )

    return QuarantineVerdict(
        rejection_code=rejection_code,
        digest=digest,
        scan_status=scan_status,
        cdr_result=cdr_result,
        size_bytes=metadata.size_bytes,
        extension=validation.extension or "",
    )


async def _head_quarantine(object_store: ObjectStore, object_key: str) -> ObjectMetadata:
    try:
        return await object_store.head_quarantine(object_key)
    except (FileNotFoundError, OSError, KeyError) as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "UPLOAD_OBJECT_NOT_FOUND"},
        ) from exc
    except (BotoCoreError, ClientError) as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "OBJECT_STORE_UNAVAILABLE"},
        ) from exc


def _assert_metadata_matches(
    metadata: ObjectMetadata,
    *,
    expected_size: int,
    expected_mime: str,
    expected_sha256: str,
    upload_mode: str,
) -> None:
    """Compare what the store says it holds against what the session recorded.

    These are preconditions rather than verdicts: a mismatch means the object
    is not the one the client committed to, so there is nothing to screen.
    """
    if metadata.size_bytes != expected_size:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "SIZE_MISMATCH",
                "expected": expected_size,
                "actual": metadata.size_bytes,
            },
        )
    if metadata.content_type and (
        metadata.content_type.split(";", 1)[0].casefold()
        != expected_mime.split(";", 1)[0].casefold()
    ):
        raise HTTPException(status_code=422, detail={"code": "CONTENT_TYPE_MISMATCH"})
    # Multipart uploads carry a checksum of the composed object rather than of
    # the payload, so the stored value is only comparable for single uploads.
    if metadata.checksum_sha256 and upload_mode == "single":
        expected_b64 = base64.b64encode(bytes.fromhex(expected_sha256)).decode("ascii")
        if not secrets.compare_digest(metadata.checksum_sha256, expected_b64):
            raise HTTPException(status_code=422, detail={"code": "CHECKSUM_MISMATCH"})


async def _disarm(
    staged: tempfile.SpooledTemporaryFile[bytes],
    *,
    cdr_adapter: Any,
    settings: Settings,
    safe_filename: str,
    mime_type: str,
    digest: str,
) -> tuple[str | None, CdrResult | None]:
    """Content disarm and reconstruction, for the MIME types configured for it.

    Returns ``(rejection_code, cdr_result)``. A sanitized result is returned
    with no rejection code; the caller decides where to store the derivative.
    """
    staged.seek(0)
    payload_bytes = staged.read(settings.cdr_max_output_bytes + 1)
    if len(payload_bytes) > settings.cdr_max_output_bytes:
        raise HTTPException(status_code=413, detail={"code": "CDR_SOURCE_TOO_LARGE"})
    try:
        cdr_result = await cdr_adapter.sanitize(
            CdrRequest(
                filename=safe_filename,
                mime_type=mime_type,
                source_sha256=digest,
                payload=payload_bytes,
            )
        )
        cdr_result = validate_cdr_result(
            cdr_result,
            source_sha256=digest,
            max_output_bytes=settings.cdr_max_output_bytes,
        )
    except ValueError as exc:
        raise QuarantineUnavailable(
            audit_action="document.cdr_invalid_response",
            code="CDR_INVALID_RESPONSE",
        ) from exc
    if cdr_result.status is CdrStatus.UNAVAILABLE:
        raise QuarantineUnavailable(
            audit_action="document.cdr_unavailable",
            code="CDR_UNAVAILABLE",
        )
    if cdr_result.status is CdrStatus.UNSUPPORTED:
        return "CDR_UNSUPPORTED", cdr_result
    if cdr_result.status is CdrStatus.REJECTED:
        return "CDR_REJECTED", cdr_result
    return None, cdr_result
