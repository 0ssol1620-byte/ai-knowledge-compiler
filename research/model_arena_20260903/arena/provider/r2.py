"""Cloudflare R2 transport for worker and runtime bundles.

ARENA_CONTRACT section 5: bucket ``tavonel-arena-20260903``; workers receive
time-limited presigned GET URLs and never account credentials. In this build
phase ``preflight_access`` is the only call that may touch the network, and it
only *reads* — it reports whether the bucket exists, is forbidden or is absent.
``create_bucket`` exists, is gated behind ``execute`` plus an explicit
confirmation, and is not called by anything in this phase.

boto3 is imported lazily so this module can be imported (and its request
building tested) on a machine with no AWS stack configured.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from arena.provider.safety import canonical_sha256, sha256_file, utc_now_iso
from arena.provider.secrets import R2Credentials

if TYPE_CHECKING:  # pragma: no cover - typing only
    from mypy_boto3_s3.client import S3Client
else:  # pragma: no cover - runtime placeholder
    S3Client = Any

__all__ = [
    "BUCKET_NAME",
    "R2Client",
    "R2Error",
    "R2Receipt",
    "UploadResult",
]

BUCKET_NAME: Final = "tavonel-arena-20260903"
R2_REGION: Final = "auto"
BUCKET_STATES: Final = ("exists", "forbidden", "missing", "unreachable")


class R2Error(RuntimeError):
    """Sanitized R2 failure. Never carries a credential or a signed URL."""


@dataclass(frozen=True, slots=True)
class R2Receipt:
    action: str
    mode: str  # "dry_run" | "live"
    bucket: str
    endpoint_host: str
    ts: str
    request_sha256: str
    detail: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": "tavonel.arena.r2_receipt.v1",
            "action": self.action,
            "mode": self.mode,
            "bucket": self.bucket,
            "endpoint_host": self.endpoint_host,
            "ts": self.ts,
            "request_sha256": self.request_sha256,
            "credentials_withheld": True,
            "detail": dict(self.detail),
        }


@dataclass(frozen=True, slots=True)
class UploadResult:
    key: str
    sha256: str
    size_bytes: int


class R2Client:
    """S3 client against R2. Read-only unless ``execute`` is set."""

    def __init__(
        self,
        credentials: R2Credentials,
        *,
        bucket: str = BUCKET_NAME,
        execute: bool = False,
        client: S3Client | None = None,
    ) -> None:
        if not bucket.strip():
            raise R2Error("bucket name is required")
        self._credentials = credentials
        self.bucket = bucket
        self.execute = execute
        self._client: S3Client | None = client
        self._receipts: list[R2Receipt] = []

    def __repr__(self) -> str:
        return f"R2Client(bucket={self.bucket!r}, execute={self.execute})"

    @property
    def endpoint_host(self) -> str:
        return self._credentials.endpoint_url.split("://", 1)[-1].split("/", 1)[0]

    @property
    def receipts(self) -> tuple[R2Receipt, ...]:
        return tuple(self._receipts)

    def _s3(self) -> S3Client:
        if self._client is not None:
            return self._client
        try:
            import boto3
            from botocore.config import Config
        except ImportError as exc:  # pragma: no cover - boto3 is a repo dependency
            raise R2Error("boto3 is not installed; R2 transport is unavailable") from exc
        self._client = boto3.client(
            "s3",
            endpoint_url=self._credentials.endpoint_url,
            aws_access_key_id=self._credentials.access_key_id.reveal(),
            aws_secret_access_key=self._credentials.secret_access_key.reveal(),
            region_name=R2_REGION,
            config=Config(
                signature_version="s3v4",
                retries={"max_attempts": 1, "mode": "standard"},
            ),
        )
        return self._client

    def _receipt(self, action: str, mode: str, detail: dict[str, object]) -> R2Receipt:
        receipt = R2Receipt(
            action=action,
            mode=mode,
            bucket=self.bucket,
            endpoint_host=self.endpoint_host,
            ts=utc_now_iso(),
            request_sha256=canonical_sha256(
                {"action": action, "bucket": self.bucket, "host": self.endpoint_host}
            ),
            detail=detail,
        )
        self._receipts.append(receipt)
        return receipt

    def preflight_access(self) -> R2Receipt:
        """Report the bucket's access state without creating anything.

        ``exists`` the bucket is there and the credentials can see it;
        ``forbidden`` it exists but this token may not; ``missing`` no such
        bucket; ``unreachable`` the endpoint itself did not answer.
        """

        if not self.execute:
            return self._receipt("preflight_access", "dry_run", {"bucket_state": None})
        try:
            self._s3().head_bucket(Bucket=self.bucket)
        except Exception as exc:
            state, code = _classify_bucket_error(exc)
            return self._receipt(
                "preflight_access",
                "live",
                {"bucket_state": state, "error_code": code, "error_type": type(exc).__name__},
            )
        return self._receipt(
            "preflight_access", "live", {"bucket_state": "exists", "error_code": None}
        )

    def put_file(self, path: Path, *, key: str | None = None) -> UploadResult | R2Receipt:
        """Upload one local file. Gated: uploads are a paid side effect."""

        if not path.is_file():
            raise R2Error(f"{path.name} is not a readable file")
        digest = sha256_file(path)
        size = path.stat().st_size
        object_key = key or f"bundles/{digest.split(':', 1)[1][:16]}/{path.name}"
        if not self.execute:
            return self._receipt(
                "put_file",
                "dry_run",
                {"key": object_key, "sha256": digest, "size_bytes": size},
            )
        with path.open("rb") as handle:
            self._s3().put_object(
                Bucket=self.bucket,
                Key=object_key,
                Body=handle,
                ChecksumAlgorithm="SHA256",
            )
        self._receipt(
            "put_file", "live", {"key": object_key, "sha256": digest, "size_bytes": size}
        )
        return UploadResult(key=object_key, sha256=digest, size_bytes=size)

    def head_object(self, key: str) -> dict[str, object]:
        """Object metadata, including R2's SHA256 checksum when it kept one.

        ARENA_CONTRACT 11.5 D21: after an upload the *object* is asked what it
        holds. A ``put_object`` that returned 200 says the request was
        accepted, not that the bucket now holds the bytes we built.
        """

        if not key.strip():
            raise R2Error("object key is required")
        if not self.execute:
            self._receipt("head_object", "dry_run", {"key": key})
            raise R2Error("head_object requires execute=True; a dry run reads nothing")
        try:
            response = self._s3().head_object(Bucket=self.bucket, Key=key, ChecksumMode="ENABLED")
        except Exception as exc:
            state, code = _classify_bucket_error(exc)
            self._receipt(
                "head_object",
                "live",
                {"key": key, "object_state": state, "error_code": code},
            )
            raise R2Error(
                f"HEAD {self.bucket}/{key} failed ({state}, code {code!r})"
            ) from None
        checksum = response.get("ChecksumSHA256")
        digest = _checksum_to_sha256_ref(checksum) if isinstance(checksum, str) else None
        size = response.get("ContentLength")
        detail: dict[str, object] = {
            "key": key,
            "checksum_sha256": digest,
            "size_bytes": size if isinstance(size, int) else None,
            "checksum_header_present": digest is not None,
        }
        self._receipt("head_object", "live", detail)
        return detail

    def object_sha256(self, key: str) -> str:
        """Re-download the object and hash it (the no-checksum-header path)."""

        if not self.execute:
            raise R2Error("object_sha256 requires execute=True; a dry run reads nothing")
        try:
            response = self._s3().get_object(Bucket=self.bucket, Key=key)
            body = response["Body"]
            digest = hashlib.sha256()
            for chunk in iter(lambda: body.read(1 << 20), b""):
                digest.update(chunk)
        except Exception as exc:
            state, code = _classify_bucket_error(exc)
            raise R2Error(
                f"GET {self.bucket}/{key} failed ({state}, code {code!r})"
            ) from None
        value = "sha256:" + digest.hexdigest()
        self._receipt("object_sha256", "live", {"key": key, "sha256": value})
        return value

    def presign_get(self, key: str, expires_seconds: int) -> str:
        """Time-limited GET URL for a worker. The result is secret material."""

        if not key.strip():
            raise R2Error("object key is required")
        if not 60 <= expires_seconds <= 7 * 24 * 3600:
            raise R2Error("presign expiry must be between 60 seconds and 7 days")
        if not self.execute:
            raise R2Error("presigning requires execute=True; nothing is signed in a dry run")
        url = self._s3().generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires_seconds,
        )
        # The URL itself is never written to a receipt; only its shape is.
        self._receipt(
            "presign_get", "live", {"key": key, "expires_seconds": expires_seconds, "url": None}
        )
        return str(url)

    def create_bucket(self, *, confirm: bool = False) -> R2Receipt:
        """Create the transport bucket. Not called in this build phase.

        ARENA_CONTRACT section 0 forbids bucket creation until the orchestrator
        says go, so this needs both ``execute`` and an explicit ``confirm``.
        """

        if not self.execute:
            return self._receipt("create_bucket", "dry_run", {"created": False})
        if not confirm:
            raise R2Error(
                "create_bucket requires an explicit confirm=True founder decision"
            )
        self._s3().create_bucket(Bucket=self.bucket)
        return self._receipt("create_bucket", "live", {"created": True})


def _checksum_to_sha256_ref(value: str) -> str | None:
    """S3 reports ``ChecksumSHA256`` base64-encoded; the campaign uses hex.

    A value that is neither valid base64 of 32 bytes nor a 64-hex digest is
    returned as ``None`` rather than guessed at -- the caller then falls back
    to re-downloading and hashing, which is slower and certain.
    """

    candidate = value.strip()
    if len(candidate) == 64 and all(character in "0123456789abcdef" for character in candidate):
        return f"sha256:{candidate}"
    try:
        raw = base64.b64decode(candidate, validate=True)
    except (binascii.Error, ValueError):
        return None
    if len(raw) != 32:
        return None
    return "sha256:" + raw.hex()


def _classify_bucket_error(exc: Exception) -> tuple[str, str | None]:
    """Map a botocore error onto a bucket state without leaking the response."""

    response = getattr(exc, "response", None)
    code: str | None = None
    status: int | None = None
    if isinstance(response, dict):
        error = response.get("Error")
        if isinstance(error, dict):
            raw_code = error.get("Code")
            code = str(raw_code) if raw_code is not None else None
        metadata = response.get("ResponseMetadata")
        if isinstance(metadata, dict):
            raw_status = metadata.get("HTTPStatusCode")
            status = raw_status if isinstance(raw_status, int) else None
    if code in {"404", "NoSuchBucket"} or status == 404:
        return "missing", code
    if code in {"403", "AccessDenied", "AllAccessDisabled"} or status == 403:
        return "forbidden", code
    if code in {"401", "InvalidAccessKeyId", "SignatureDoesNotMatch"} or status == 401:
        return "forbidden", code
    return "unreachable", code
