#!/usr/bin/env python3
"""Content-addressed S3/R2 transport for the GPU successor controller.

The adapter accepts an already-configured S3 client.  It never discovers or
reads credentials, which keeps secret handling outside the scientific layer.
"""

from __future__ import annotations

import base64
import hashlib
from typing import Any


class R2TransportError(RuntimeError):
    """An object could not be proven to have the requested content identity."""


class S3CompatibleObjectTransport:
    def __init__(self, *, client: Any, bucket: str, prefix: str = "") -> None:
        if not bucket.strip():
            raise R2TransportError("R2 bucket is required")
        self.client = client
        self.bucket = bucket
        self.prefix = prefix.strip("/")

    def _key(self, key: str) -> str:
        if not key or key.startswith("/") or ".." in key.split("/"):
            raise R2TransportError("unsafe object key")
        return f"{self.prefix}/{key}" if self.prefix else key

    def put_if_absent(self, key: str, body: bytes, sha256: str) -> None:
        actual = "sha256:" + hashlib.sha256(body).hexdigest()
        if actual != sha256:
            raise R2TransportError("upload body does not match its sha256")
        object_key = self._key(key)
        try:
            head = self.client.head_object(Bucket=self.bucket, Key=object_key)
        except Exception as error:
            code = str(getattr(error, "response", {}).get("Error", {}).get("Code", ""))
            if code not in {"404", "NoSuchKey", "NotFound"}:
                raise R2TransportError("R2 HEAD failed before content-addressed PUT") from error
        else:
            recorded = (head.get("Metadata") or {}).get("tavonel-sha256")
            if recorded != sha256:
                raise R2TransportError("existing content-addressed R2 object has another digest")
            return
        checksum = base64.b64encode(bytes.fromhex(sha256[7:])).decode("ascii")
        self.client.put_object(
            Bucket=self.bucket,
            Key=object_key,
            Body=body,
            ContentType="application/json",
            ChecksumSHA256=checksum,
            Metadata={"tavonel-sha256": sha256},
            IfNoneMatch="*",
        )

    def get(self, key: str) -> bytes:
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=self._key(key))
            body = response["Body"].read()
        except Exception as error:
            raise R2TransportError("R2 content retrieval failed") from error
        if not isinstance(body, bytes):
            raise R2TransportError("R2 content retrieval returned no bytes")
        return body

    def worker_grants(
        self, *, input_key: str, status_key: str, output_prefix: str, expires: int = 21600
    ) -> dict[str, Any]:
        """Issue bounded worker grants; no storage credential enters the pod."""
        if not 1 <= expires <= 21600:
            raise R2TransportError("research worker grant lifetime must be 1..21600 seconds")
        input_url = self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": self._key(input_key)},
            ExpiresIn=expires,
        )
        status_url = self.client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": self.bucket,
                "Key": self._key(status_key),
                "ContentType": "application/json",
            },
            ExpiresIn=expires,
        )
        output_key_prefix = self._key(output_prefix.rstrip("/") + "/")
        output_post = self.client.generate_presigned_post(
            Bucket=self.bucket,
            Key=output_key_prefix + "${filename}",
            Fields={"Content-Type": "application/json"},
            Conditions=[
                ["starts-with", "$key", output_key_prefix],
                {"Content-Type": "application/json"},
                ["content-length-range", 1, 512 * 1024 * 1024],
            ],
            ExpiresIn=expires,
        )
        return {
            "input_get_url": input_url,
            "status_put_url": status_url,
            "status_put_headers": {"Content-Type": "application/json"},
            "output_post_url": output_post["url"],
            "output_post_fields": output_post["fields"],
            "output_object_prefix": output_prefix.rstrip("/") + "/",
            "expires_seconds": expires,
        }


__all__ = ["R2TransportError", "S3CompatibleObjectTransport"]
