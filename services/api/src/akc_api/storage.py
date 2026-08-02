"""Local and S3-compatible object-store adapters."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Literal, Protocol

import boto3
from botocore.exceptions import ClientError
from mypy_boto3_s3 import S3Client
from mypy_boto3_s3.type_defs import (
    DeleteObjectsOutputTypeDef,
    ListObjectsV2OutputTypeDef,
    ListObjectVersionsOutputTypeDef,
    ListPartsOutputTypeDef,
    ObjectIdentifierTypeDef,
)


@dataclass(frozen=True)
class UploadTarget:
    url: str
    headers: dict[str, str]


@dataclass(frozen=True)
class ObjectMetadata:
    size_bytes: int
    content_type: str | None
    checksum_sha256: str | None


@dataclass(frozen=True)
class MultipartSession:
    provider_upload_id: str


@dataclass(frozen=True)
class MultipartPartTarget:
    part_number: int
    url: str
    headers: dict[str, str]


@dataclass(frozen=True)
class UploadedPart:
    part_number: int
    etag: str
    size_bytes: int


@dataclass(frozen=True)
class CompletedPart:
    part_number: int
    etag: str


class MultipartUploadNotSupportedError(RuntimeError):
    """Raised when an adapter cannot safely emulate browser-direct multipart."""


class MultipartUploadNotFoundError(RuntimeError):
    """Raised when the provider no longer has the opaque multipart session."""


class ObjectPurgeIncompleteError(RuntimeError):
    """Raised unless an exact object key is proven absent from storage."""


class GpuObjectGrantNotSupportedError(RuntimeError):
    """Raised when storage cannot issue provider-safe HTTPS object grants."""


class ObjectStoreSettings(Protocol):
    @property
    def object_store_driver(self) -> str: ...

    s3_endpoint_url: str | None
    s3_region: str
    s3_access_key_id: str | None
    s3_secret_access_key: str | None
    s3_deletion_mode: Literal["versioned", "unversioned-explicit"]
    s3_bucket_quarantine: str
    s3_bucket_source: str
    s3_bucket_working: str
    s3_bucket_derived: str
    s3_bucket_exports: str
    s3_bucket_audit: str

    @property
    def object_root(self) -> Path: ...


class ObjectStore(Protocol):
    async def healthcheck(self) -> None: ...

    async def create_gpu_input_target(
        self,
        *,
        bucket: Literal["source", "derived"],
        object_key: str,
        expires: int,
    ) -> UploadTarget: ...

    async def create_gpu_output_target(
        self,
        *,
        object_key: str,
        expires: int,
    ) -> UploadTarget: ...

    async def create_upload_target(
        self,
        *,
        upload_id: str,
        object_key: str,
        content_type: str,
        expected_sha256: str,
        expires: int,
    ) -> UploadTarget: ...

    async def create_multipart_upload(
        self,
        *,
        object_key: str,
        content_type: str,
        expected_sha256: str,
    ) -> MultipartSession: ...

    async def create_multipart_part_target(
        self,
        *,
        object_key: str,
        provider_upload_id: str,
        part_number: int,
        expires: int,
    ) -> MultipartPartTarget: ...

    async def list_multipart_parts(
        self,
        *,
        object_key: str,
        provider_upload_id: str,
    ) -> list[UploadedPart]: ...

    async def complete_multipart_upload(
        self,
        *,
        object_key: str,
        provider_upload_id: str,
        parts: list[CompletedPart],
    ) -> None: ...

    async def abort_multipart_upload(
        self,
        *,
        object_key: str,
        provider_upload_id: str,
    ) -> None: ...

    async def put_quarantine(self, object_key: str, data: bytes) -> None: ...

    async def put_quarantine_stream(self, object_key: str, stream: BinaryIO) -> None: ...

    async def read_quarantine(self, object_key: str) -> bytes: ...

    async def download_quarantine(self, object_key: str, stream: BinaryIO) -> None: ...

    async def head_quarantine(self, object_key: str) -> ObjectMetadata: ...

    async def promote_source(self, quarantine_key: str, source_key: str) -> None: ...

    async def read_source(self, source_key: str) -> bytes: ...

    async def download_source(self, source_key: str, stream: BinaryIO) -> None: ...

    async def put_derived(self, object_key: str, data: bytes) -> None: ...

    async def read_derived(self, object_key: str) -> bytes: ...

    async def put_export(self, object_key: str, data: bytes) -> None: ...

    async def read_export(self, object_key: str) -> bytes: ...

    async def delete(self, bucket: str, object_key: str) -> bool: ...


class LocalObjectStore:
    """Filesystem adapter intended only for development and tests."""

    def __init__(self, settings: ObjectStoreSettings) -> None:
        self.root = settings.object_root.resolve()
        for bucket in ("quarantine", "source", "working", "derived", "exports", "audit"):
            (self.root / bucket).mkdir(parents=True, exist_ok=True)

    def _path(self, bucket: str, object_key: str) -> Path:
        if bucket not in {"quarantine", "source", "working", "derived", "exports", "audit"}:
            raise ValueError("unknown_object_bucket")
        if not object_key or "\x00" in object_key:
            raise ValueError("unsafe_object_key")
        # Production stores can handle long logical object keys. Hash them in
        # the local adapter so the same contract remains runnable on Windows,
        # where nested tenant/project UUID prefixes otherwise exceed MAX_PATH.
        digest = hashlib.sha256(object_key.encode("utf-8")).hexdigest()
        return self.root / bucket / digest[:2] / digest

    async def healthcheck(self) -> None:
        """Prove that every local development bucket is currently accessible."""

        buckets = ("quarantine", "source", "working", "derived", "exports", "audit")

        def check() -> None:
            if not self.root.is_dir():
                raise OSError("object store root is unavailable")
            if any(not (self.root / bucket).is_dir() for bucket in buckets):
                raise OSError("object store bucket is unavailable")

        await asyncio.to_thread(check)

    async def create_gpu_input_target(
        self,
        *,
        bucket: Literal["source", "derived"],
        object_key: str,
        expires: int,
    ) -> UploadTarget:
        del bucket, object_key, expires
        raise GpuObjectGrantNotSupportedError(
            "local storage cannot issue provider-safe HTTPS input grants"
        )

    async def create_gpu_output_target(
        self,
        *,
        object_key: str,
        expires: int,
    ) -> UploadTarget:
        del object_key, expires
        raise GpuObjectGrantNotSupportedError(
            "local storage cannot issue provider-safe HTTPS output grants"
        )

    async def create_upload_target(
        self,
        *,
        upload_id: str,
        object_key: str,
        content_type: str,
        expected_sha256: str,
        expires: int,
    ) -> UploadTarget:
        del object_key, expected_sha256, expires
        return UploadTarget(
            url=f"/v1/uploads/{upload_id}/content",
            headers={"Content-Type": content_type},
        )

    async def create_multipart_upload(
        self,
        *,
        object_key: str,
        content_type: str,
        expected_sha256: str,
    ) -> MultipartSession:
        del object_key, content_type, expected_sha256
        raise MultipartUploadNotSupportedError(
            "local storage deliberately uses the authenticated single-PUT adapter"
        )

    async def create_multipart_part_target(
        self,
        *,
        object_key: str,
        provider_upload_id: str,
        part_number: int,
        expires: int,
    ) -> MultipartPartTarget:
        del object_key, provider_upload_id, part_number, expires
        raise MultipartUploadNotSupportedError

    async def list_multipart_parts(
        self,
        *,
        object_key: str,
        provider_upload_id: str,
    ) -> list[UploadedPart]:
        del object_key, provider_upload_id
        raise MultipartUploadNotSupportedError

    async def complete_multipart_upload(
        self,
        *,
        object_key: str,
        provider_upload_id: str,
        parts: list[CompletedPart],
    ) -> None:
        del object_key, provider_upload_id, parts
        raise MultipartUploadNotSupportedError

    async def abort_multipart_upload(
        self,
        *,
        object_key: str,
        provider_upload_id: str,
    ) -> None:
        del object_key, provider_upload_id
        raise MultipartUploadNotSupportedError

    async def put_quarantine(self, object_key: str, data: bytes) -> None:
        await self.put_quarantine_stream(object_key, io.BytesIO(data))

    async def put_quarantine_stream(self, object_key: str, stream: BinaryIO) -> None:
        target = self._path("quarantine", object_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        stream.seek(0)

        def write() -> None:
            with target.open("wb") as destination:
                shutil.copyfileobj(stream, destination, length=1024 * 1024)

        await asyncio.to_thread(write)

    async def read_quarantine(self, object_key: str) -> bytes:
        return await asyncio.to_thread(self._path("quarantine", object_key).read_bytes)

    async def download_quarantine(self, object_key: str, stream: BinaryIO) -> None:
        source = self._path("quarantine", object_key)

        def copy() -> None:
            with source.open("rb") as origin:
                shutil.copyfileobj(origin, stream, length=1024 * 1024)
            stream.seek(0)

        await asyncio.to_thread(copy)

    async def head_quarantine(self, object_key: str) -> ObjectMetadata:
        path = self._path("quarantine", object_key)
        return ObjectMetadata(
            size_bytes=path.stat().st_size,
            content_type=None,
            checksum_sha256=None,
        )

    async def promote_source(self, quarantine_key: str, source_key: str) -> None:
        source = self._path("quarantine", quarantine_key)
        target = self._path("source", source_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_file():
            # A previous database transaction may have failed after the
            # content-addressed copy completed. The caller re-hashes the
            # existing target before deleting the quarantine retry object.
            return
        await asyncio.to_thread(shutil.copyfile, source, target)

    async def read_source(self, source_key: str) -> bytes:
        return await asyncio.to_thread(self._path("source", source_key).read_bytes)

    async def download_source(self, source_key: str, stream: BinaryIO) -> None:
        source = self._path("source", source_key)

        def copy() -> None:
            with source.open("rb") as origin:
                shutil.copyfileobj(origin, stream, length=1024 * 1024)
            stream.seek(0)

        await asyncio.to_thread(copy)

    async def put_derived(self, object_key: str, data: bytes) -> None:
        target = self._path("derived", object_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(target.write_bytes, data)

    async def read_derived(self, object_key: str) -> bytes:
        return await asyncio.to_thread(self._path("derived", object_key).read_bytes)

    async def put_export(self, object_key: str, data: bytes) -> None:
        target = self._path("exports", object_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(target.write_bytes, data)

    async def read_export(self, object_key: str) -> bytes:
        return await asyncio.to_thread(self._path("exports", object_key).read_bytes)

    async def delete(self, bucket: str, object_key: str) -> bool:
        target = self._path(bucket, object_key)
        existed = target.exists()
        await asyncio.to_thread(target.unlink, missing_ok=True)
        return existed


class S3ObjectStore:
    """S3/R2 adapter; credentials never leave the control plane."""

    def __init__(self, settings: ObjectStoreSettings) -> None:
        self.settings = settings
        # With no static keys boto3 follows its normal credential chain:
        # IRSA/web identity, ECS task role, instance role, then local profiles.
        self.client: S3Client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key_id,
            aws_secret_access_key=settings.s3_secret_access_key,
        )

    async def healthcheck(self) -> None:
        """HEAD every configured bucket; configuration alone is not health."""

        buckets = {
            self.settings.s3_bucket_quarantine,
            self.settings.s3_bucket_source,
            self.settings.s3_bucket_working,
            self.settings.s3_bucket_derived,
            self.settings.s3_bucket_exports,
            self.settings.s3_bucket_audit,
        }
        if len(buckets) != 6:
            raise RuntimeError("object store bucket identities must be distinct")
        for bucket in sorted(buckets):
            await asyncio.to_thread(self.client.head_bucket, Bucket=bucket)

    async def create_gpu_input_target(
        self,
        *,
        bucket: Literal["source", "derived"],
        object_key: str,
        expires: int,
    ) -> UploadTarget:
        if not 1 <= expires <= 1800:
            raise ValueError("GPU input grant lifetime must be 1..1800 seconds")
        url = await asyncio.to_thread(
            self.client.generate_presigned_url,
            "get_object",
            Params={
                "Bucket": self._bucket_name(bucket),
                "Key": object_key,
            },
            ExpiresIn=expires,
        )
        return UploadTarget(url=url, headers={})

    async def create_gpu_output_target(
        self,
        *,
        object_key: str,
        expires: int,
    ) -> UploadTarget:
        if not 1 <= expires <= 1800:
            raise ValueError("GPU output grant lifetime must be 1..1800 seconds")
        url = await asyncio.to_thread(
            self.client.generate_presigned_url,
            "put_object",
            Params={
                "Bucket": self.settings.s3_bucket_derived,
                "Key": object_key,
                "ContentType": "application/json",
            },
            ExpiresIn=expires,
        )
        return UploadTarget(
            url=url,
            headers={"Content-Type": "application/json"},
        )

    async def create_upload_target(
        self,
        *,
        upload_id: str,
        object_key: str,
        content_type: str,
        expected_sha256: str,
        expires: int,
    ) -> UploadTarget:
        del upload_id
        checksum = base64.b64encode(bytes.fromhex(expected_sha256)).decode("ascii")
        url = await asyncio.to_thread(
            self.client.generate_presigned_url,
            "put_object",
            Params={
                "Bucket": self.settings.s3_bucket_quarantine,
                "Key": object_key,
                "ContentType": content_type,
                "ChecksumSHA256": checksum,
            },
            ExpiresIn=expires,
        )
        return UploadTarget(
            url=url,
            headers={
                "Content-Type": content_type,
                "x-amz-checksum-sha256": checksum,
            },
        )

    async def create_multipart_upload(
        self,
        *,
        object_key: str,
        content_type: str,
        expected_sha256: str,
    ) -> MultipartSession:
        response = await asyncio.to_thread(
            self.client.create_multipart_upload,
            Bucket=self.settings.s3_bucket_quarantine,
            Key=object_key,
            ContentType=content_type,
            Metadata={"expected-sha256": expected_sha256},
        )
        provider_upload_id = str(response.get("UploadId", ""))
        if not provider_upload_id:
            raise RuntimeError("object store returned no multipart upload identifier")
        return MultipartSession(provider_upload_id=provider_upload_id)

    async def create_multipart_part_target(
        self,
        *,
        object_key: str,
        provider_upload_id: str,
        part_number: int,
        expires: int,
    ) -> MultipartPartTarget:
        url = await asyncio.to_thread(
            self.client.generate_presigned_url,
            "upload_part",
            Params={
                "Bucket": self.settings.s3_bucket_quarantine,
                "Key": object_key,
                "UploadId": provider_upload_id,
                "PartNumber": part_number,
            },
            ExpiresIn=expires,
        )
        return MultipartPartTarget(
            part_number=part_number,
            url=url,
            headers={},
        )

    async def list_multipart_parts(
        self,
        *,
        object_key: str,
        provider_upload_id: str,
    ) -> list[UploadedPart]:
        parts: list[UploadedPart] = []
        marker = 0
        while True:
            try:
                response: ListPartsOutputTypeDef = await asyncio.to_thread(
                    self.client.list_parts,
                    Bucket=self.settings.s3_bucket_quarantine,
                    Key=object_key,
                    UploadId=provider_upload_id,
                    PartNumberMarker=marker,
                    MaxParts=1000,
                )
            except ClientError as exc:
                if _client_error_code(exc) == "NoSuchUpload":
                    raise MultipartUploadNotFoundError from exc
                raise
            for item in response.get("Parts", []):
                etag = _sanitize_provider_etag(str(item.get("ETag", "")))
                parts.append(
                    UploadedPart(
                        part_number=int(item["PartNumber"]),
                        etag=etag,
                        size_bytes=int(item["Size"]),
                    )
                )
            if not response.get("IsTruncated"):
                break
            marker = int(response.get("NextPartNumberMarker", 0))
            if marker <= 0:
                raise RuntimeError("object store returned an invalid multipart cursor")
        return sorted(parts, key=lambda part: part.part_number)

    async def complete_multipart_upload(
        self,
        *,
        object_key: str,
        provider_upload_id: str,
        parts: list[CompletedPart],
    ) -> None:
        try:
            await asyncio.to_thread(
                self.client.complete_multipart_upload,
                Bucket=self.settings.s3_bucket_quarantine,
                Key=object_key,
                UploadId=provider_upload_id,
                MultipartUpload={
                    "Parts": [
                        {
                            "ETag": f'"{_sanitize_provider_etag(part.etag)}"',
                            "PartNumber": part.part_number,
                        }
                        for part in parts
                    ]
                },
            )
        except ClientError as exc:
            if _client_error_code(exc) == "NoSuchUpload":
                raise MultipartUploadNotFoundError from exc
            raise

    async def abort_multipart_upload(
        self,
        *,
        object_key: str,
        provider_upload_id: str,
    ) -> None:
        try:
            await asyncio.to_thread(
                self.client.abort_multipart_upload,
                Bucket=self.settings.s3_bucket_quarantine,
                Key=object_key,
                UploadId=provider_upload_id,
            )
        except ClientError as exc:
            if _client_error_code(exc) != "NoSuchUpload":
                raise

    async def put_quarantine(self, object_key: str, data: bytes) -> None:
        await self.put_quarantine_stream(object_key, io.BytesIO(data))

    async def put_quarantine_stream(self, object_key: str, stream: BinaryIO) -> None:
        stream.seek(0)
        await asyncio.to_thread(
            self.client.upload_fileobj,
            stream,
            self.settings.s3_bucket_quarantine,
            object_key,
        )

    async def read_quarantine(self, object_key: str) -> bytes:
        response = await asyncio.to_thread(
            self.client.get_object,
            Bucket=self.settings.s3_bucket_quarantine,
            Key=object_key,
        )
        return await asyncio.to_thread(response["Body"].read)

    async def download_quarantine(self, object_key: str, stream: BinaryIO) -> None:
        await asyncio.to_thread(
            self.client.download_fileobj,
            self.settings.s3_bucket_quarantine,
            object_key,
            stream,
        )
        stream.seek(0)

    async def head_quarantine(self, object_key: str) -> ObjectMetadata:
        response = await asyncio.to_thread(
            self.client.head_object,
            Bucket=self.settings.s3_bucket_quarantine,
            Key=object_key,
        )
        checksum = response.get("ChecksumSHA256")
        return ObjectMetadata(
            size_bytes=int(response["ContentLength"]),
            content_type=response.get("ContentType"),
            checksum_sha256=str(checksum) if checksum else None,
        )

    async def promote_source(self, quarantine_key: str, source_key: str) -> None:
        try:
            await asyncio.to_thread(
                self.client.head_object,
                Bucket=self.settings.s3_bucket_source,
                Key=source_key,
            )
        except ClientError as exc:
            status = int(exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0))
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if status != 404 and code not in {"404", "NoSuchKey", "NotFound"}:
                raise
        else:
            # See LocalObjectStore: the completion path verifies the target
            # bytes before it removes any retained quarantine object.
            return
        await asyncio.to_thread(
            self.client.copy_object,
            Bucket=self.settings.s3_bucket_source,
            Key=source_key,
            CopySource={
                "Bucket": self.settings.s3_bucket_quarantine,
                "Key": quarantine_key,
            },
        )

    async def read_source(self, source_key: str) -> bytes:
        response = await asyncio.to_thread(
            self.client.get_object,
            Bucket=self.settings.s3_bucket_source,
            Key=source_key,
        )
        return await asyncio.to_thread(response["Body"].read)

    async def download_source(self, source_key: str, stream: BinaryIO) -> None:
        await asyncio.to_thread(
            self.client.download_fileobj,
            self.settings.s3_bucket_source,
            source_key,
            stream,
        )
        stream.seek(0)

    async def put_derived(self, object_key: str, data: bytes) -> None:
        await asyncio.to_thread(
            self.client.put_object,
            Bucket=self.settings.s3_bucket_derived,
            Key=object_key,
            Body=data,
            ContentType="image/png",
            CacheControl="private, max-age=300",
        )

    async def read_derived(self, object_key: str) -> bytes:
        response = await asyncio.to_thread(
            self.client.get_object,
            Bucket=self.settings.s3_bucket_derived,
            Key=object_key,
        )
        return await asyncio.to_thread(response["Body"].read)

    async def put_export(self, object_key: str, data: bytes) -> None:
        await asyncio.to_thread(
            self.client.put_object,
            Bucket=self.settings.s3_bucket_exports,
            Key=object_key,
            Body=data,
            ContentType="application/zip",
        )

    async def read_export(self, object_key: str) -> bytes:
        response = await asyncio.to_thread(
            self.client.get_object,
            Bucket=self.settings.s3_bucket_exports,
            Key=object_key,
        )
        return await asyncio.to_thread(response["Body"].read)

    def _bucket_name(self, bucket: str) -> str:
        return {
            "quarantine": self.settings.s3_bucket_quarantine,
            "source": self.settings.s3_bucket_source,
            "working": self.settings.s3_bucket_working,
            "derived": self.settings.s3_bucket_derived,
            "exports": self.settings.s3_bucket_exports,
            "audit": self.settings.s3_bucket_audit,
        }[bucket]

    async def _list_exact_object_versions(
        self,
        *,
        bucket_name: str,
        object_key: str,
    ) -> list[ObjectIdentifierTypeDef]:
        """List every version and delete marker for exactly one key."""

        key_marker: str | None = None
        version_marker: str | None = None
        seen_cursors: set[tuple[str, str]] = set()
        identities: dict[tuple[str, str], ObjectIdentifierTypeDef] = {}
        while True:
            if key_marker is None:
                response = await asyncio.to_thread(
                    self.client.list_object_versions,
                    Bucket=bucket_name,
                    Prefix=object_key,
                    MaxKeys=1000,
                )
            else:
                response = await asyncio.to_thread(
                    self.client.list_object_versions,
                    Bucket=bucket_name,
                    Prefix=object_key,
                    KeyMarker=key_marker,
                    VersionIdMarker=version_marker or "",
                    MaxKeys=1000,
                )
            page: ListObjectVersionsOutputTypeDef = response
            version_items = page.get("Versions", [])
            marker_items = page.get("DeleteMarkers", [])
            for item in (*version_items, *marker_items):
                key = str(item.get("Key", ""))
                version_id = str(item.get("VersionId", ""))
                if key != object_key:
                    continue
                if not version_id:
                    raise ObjectPurgeIncompleteError("object_store_version_identifier_missing")
                identities[(key, version_id)] = {
                    "Key": key,
                    "VersionId": version_id,
                }
            if not page.get("IsTruncated"):
                break
            next_key = str(page.get("NextKeyMarker", ""))
            next_version = str(page.get("NextVersionIdMarker", ""))
            if not next_key or not next_version:
                raise ObjectPurgeIncompleteError("object_store_version_cursor_invalid")
            cursor = (next_key, next_version)
            if cursor in seen_cursors:
                raise ObjectPurgeIncompleteError("object_store_version_cursor_repeated")
            seen_cursors.add(cursor)
            key_marker, version_marker = cursor
        return list(identities.values())

    async def _delete_versioned_key(
        self,
        *,
        bucket_name: str,
        object_key: str,
    ) -> bool:
        identities = await self._list_exact_object_versions(
            bucket_name=bucket_name,
            object_key=object_key,
        )
        for offset in range(0, len(identities), 1000):
            response: DeleteObjectsOutputTypeDef = await asyncio.to_thread(
                self.client.delete_objects,
                Bucket=bucket_name,
                Delete={
                    "Objects": identities[offset : offset + 1000],
                    "Quiet": True,
                },
            )
            errors = response.get("Errors", [])
            if errors:
                codes = sorted({str(error.get("Code", "unknown"))[:80] for error in errors})
                raise ObjectPurgeIncompleteError(
                    "object_store_partial_version_delete:" + ",".join(codes)
                )
        remaining = await self._list_exact_object_versions(
            bucket_name=bucket_name,
            object_key=object_key,
        )
        if remaining:
            raise ObjectPurgeIncompleteError("object_store_versions_still_present")
        return bool(identities)

    async def _delete_explicitly_unversioned_key(
        self,
        *,
        bucket_name: str,
        object_key: str,
    ) -> bool:
        await asyncio.to_thread(
            self.client.delete_object,
            Bucket=bucket_name,
            Key=object_key,
        )
        continuation_token: str | None = None
        seen_tokens: set[str] = set()
        while True:
            if continuation_token is None:
                response = await asyncio.to_thread(
                    self.client.list_objects_v2,
                    Bucket=bucket_name,
                    Prefix=object_key,
                    MaxKeys=1000,
                )
            else:
                response = await asyncio.to_thread(
                    self.client.list_objects_v2,
                    Bucket=bucket_name,
                    Prefix=object_key,
                    ContinuationToken=continuation_token,
                    MaxKeys=1000,
                )
            page: ListObjectsV2OutputTypeDef = response
            if any(str(item.get("Key", "")) == object_key for item in page.get("Contents", [])):
                raise ObjectPurgeIncompleteError("object_store_key_still_present")
            if not page.get("IsTruncated"):
                return True
            next_token = str(page.get("NextContinuationToken", ""))
            if not next_token or next_token in seen_tokens:
                raise ObjectPurgeIncompleteError("object_store_list_cursor_invalid")
            seen_tokens.add(next_token)
            continuation_token = next_token

    async def delete(self, bucket: str, object_key: str) -> bool:
        bucket_name = self._bucket_name(bucket)
        if self.settings.s3_deletion_mode == "versioned":
            return await self._delete_versioned_key(
                bucket_name=bucket_name,
                object_key=object_key,
            )
        if self.settings.s3_deletion_mode == "unversioned-explicit":
            return await self._delete_explicitly_unversioned_key(
                bucket_name=bucket_name,
                object_key=object_key,
            )
        raise ObjectPurgeIncompleteError("object_store_deletion_mode_invalid")


def build_object_store(settings: ObjectStoreSettings) -> ObjectStore:
    if settings.object_store_driver == "s3":
        return S3ObjectStore(settings)
    return LocalObjectStore(settings)


def _client_error_code(exc: ClientError) -> str:
    return str(exc.response.get("Error", {}).get("Code", ""))


def _sanitize_provider_etag(value: str) -> str:
    normalized = value.strip().strip('"')
    if not re.fullmatch(r"[A-Fa-f0-9]{32,128}", normalized):
        raise ValueError("object store returned an invalid multipart ETag")
    return normalized.lower()
