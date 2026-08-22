"""Persisted Ed25519 trust boundary for autonomous v6 provider output.

The autonomous runtime port is intentionally *not* a trust authority.  It may
report a candidate and an opaque receipt digest, but production admission only
succeeds when an independently configured reader returns the corresponding
persisted envelope and an approved, pinned Ed25519 public key verifies it.

The signed payload binds the complete immutable execution context.  Replaying
an otherwise valid envelope for another job, shard, attempt, provider output,
model/runtime, or release therefore fails closed.  The verifier never receives
or stores a signing secret.
"""

from __future__ import annotations

import base64
import re
import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Protocol, final

from akc_parallel_runtime import canonical_json, canonical_sha256, require_sha256
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

_SCHEMA_VERSION = "parallel-v6-trusted-admission-1.0"
_ALGORITHM = "Ed25519"
_ISSUER = "akc-api"
_UTC_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$")
_PAYLOAD_FIELDS = frozenset(
    {
        "schema_version",
        "issuer",
        "admission_id",
        "tenant_id",
        "collection_id",
        "processing_job_id",
        "document_id",
        "document_version_id",
        "source_sha256",
        "shard_id",
        "submission_id",
        "attempt_id",
        "dispatch_operation_key",
        "recipe_id",
        "worker_id",
        "provider_key",
        "provider_job_id",
        "endpoint_id",
        "prediction_uri",
        "prediction_sha256",
        "candidate_material_sha256",
        "model_revision",
        "runtime_image_digest",
        "release_manifest_sha256",
    }
)
_ENVELOPE_FIELDS = frozenset(
    {
        "schema_version",
        "algorithm",
        "key_id",
        "signed_at",
        "payload_sha256",
        "payload",
        "signature",
    }
)


class TrustedAdmissionError(RuntimeError):
    """Persisted production admission evidence was absent or invalid."""


class PersistedAdmissionEnvelopeReader(Protocol):
    """Read an immutable envelope by its content digest from durable storage."""

    async def load_persisted_admission_envelope(
        self,
        *,
        receipt_sha256: str,
    ) -> Mapping[str, Any] | None: ...


class TrustedAdmissionVerifier(Protocol):
    """Extension contract for independently verified production admission."""

    async def verify(self, expected: TrustedAdmissionContext) -> bool: ...


class _ContextBase:
    """Shared exact-field validation without making trust a dataclass flag."""

    @staticmethod
    def validate_material(material: Mapping[str, str]) -> None:
        for field in (
            "tenant_id",
            "collection_id",
            "processing_job_id",
            "document_id",
            "document_version_id",
            "shard_id",
            "submission_id",
            "attempt_id",
            "dispatch_operation_key",
            "recipe_id",
            "worker_id",
            "provider_key",
            "provider_job_id",
            "endpoint_id",
            "prediction_uri",
            "model_revision",
        ):
            _bounded_identity(material[field], field=field, maximum=500)
        for field in (
            "source_sha256",
            "prediction_sha256",
            "candidate_material_sha256",
            "release_manifest_sha256",
        ):
            require_sha256(material[field], field_name=field)
        runtime = material["runtime_image_digest"]
        if not runtime.startswith("sha256:"):
            raise ValueError("runtime_image_digest must be an exact sha256 image digest")
        require_sha256(
            runtime.removeprefix("sha256:"),
            field_name="runtime_image_digest",
        )


class TrustedAdmissionContext(_ContextBase):
    """Coordinator-derived context that a signed envelope must match exactly."""

    __slots__ = tuple(sorted(_PAYLOAD_FIELDS - {"schema_version", "issuer", "admission_id"}))

    def __init__(
        self,
        *,
        tenant_id: str,
        collection_id: str,
        processing_job_id: str,
        document_id: str,
        document_version_id: str,
        source_sha256: str,
        shard_id: str,
        submission_id: str,
        attempt_id: str,
        dispatch_operation_key: str,
        recipe_id: str,
        worker_id: str,
        provider_key: str,
        provider_job_id: str,
        endpoint_id: str,
        prediction_uri: str,
        prediction_sha256: str,
        candidate_material_sha256: str,
        model_revision: str,
        runtime_image_digest: str,
        release_manifest_sha256: str,
    ) -> None:
        material = {
            "tenant_id": tenant_id,
            "collection_id": collection_id,
            "processing_job_id": processing_job_id,
            "document_id": document_id,
            "document_version_id": document_version_id,
            "source_sha256": source_sha256,
            "shard_id": shard_id,
            "submission_id": submission_id,
            "attempt_id": attempt_id,
            "dispatch_operation_key": dispatch_operation_key,
            "recipe_id": recipe_id,
            "worker_id": worker_id,
            "provider_key": provider_key,
            "provider_job_id": provider_job_id,
            "endpoint_id": endpoint_id,
            "prediction_uri": prediction_uri,
            "prediction_sha256": prediction_sha256,
            "candidate_material_sha256": candidate_material_sha256,
            "model_revision": model_revision,
            "runtime_image_digest": runtime_image_digest,
            "release_manifest_sha256": release_manifest_sha256,
        }
        self.validate_material(material)
        for field, value in material.items():
            object.__setattr__(self, field, value)

    def material(self) -> dict[str, str]:
        return {field: getattr(self, field) for field in self.__slots__}


@final
class PersistedEd25519AdmissionVerifier:
    """Approved production verifier using only a pinned Ed25519 public key.

    The exact concrete type is deliberate: the coordinator rejects structural
    test doubles in production.  Rotation is explicit—construct a new verifier
    with the next approved ``key_id`` and public key only after deployment
    policy has pinned that identity.
    """

    __slots__ = ("_key_id", "_public_key", "_reader")

    def __init__(
        self,
        *,
        reader: PersistedAdmissionEnvelopeReader,
        public_key: Ed25519PublicKey,
        key_id: str,
    ) -> None:
        self._reader = reader
        if not isinstance(public_key, Ed25519PublicKey):
            raise TypeError("trusted admission public key must be Ed25519")
        self._public_key = public_key
        self._key_id = _bounded_identity(key_id, field="key_id", maximum=160)

    async def verify(self, expected: TrustedAdmissionContext) -> bool:
        receipt_sha256 = canonical_sha256(
            {
                "schema_version": _SCHEMA_VERSION,
                "issuer": _ISSUER,
                **expected.material(),
            }
        )
        envelope = await self._reader.load_persisted_admission_envelope(
            receipt_sha256=receipt_sha256
        )
        if envelope is None:
            return False
        try:
            payload = self._verify_envelope(envelope)
        except (TrustedAdmissionError, TypeError, ValueError):
            return False
        expected_payload = {
            "schema_version": _SCHEMA_VERSION,
            "issuer": _ISSUER,
            **expected.material(),
        }
        # admission_id is a signed uniqueness nonce; every other field is
        # coordinator-derived and must match byte-for-byte.
        return {
            key: payload[key] for key in _PAYLOAD_FIELDS if key != "admission_id"
        } == expected_payload

    def _verify_envelope(self, envelope: Mapping[str, Any]) -> dict[str, str]:
        if set(envelope) != _ENVELOPE_FIELDS:
            raise TrustedAdmissionError("trusted admission envelope shape is invalid")
        if (
            envelope.get("schema_version") != _SCHEMA_VERSION
            or envelope.get("algorithm") != _ALGORITHM
            or envelope.get("key_id") != self._key_id
        ):
            raise TrustedAdmissionError("trusted admission envelope identity is invalid")
        signed_at = envelope.get("signed_at")
        if not isinstance(signed_at, str):
            raise TrustedAdmissionError("trusted admission signed_at is invalid")
        _validate_timestamp(signed_at)
        payload = envelope.get("payload")
        if not isinstance(payload, Mapping) or set(payload) != _PAYLOAD_FIELDS:
            raise TrustedAdmissionError("trusted admission payload shape is invalid")
        normalized = _normalize_payload(payload)
        payload_sha256 = envelope.get("payload_sha256")
        if not isinstance(payload_sha256, str):
            raise TrustedAdmissionError("trusted admission payload digest is invalid")
        require_sha256(payload_sha256, field_name="payload_sha256")
        if canonical_sha256(normalized) != payload_sha256:
            raise TrustedAdmissionError("trusted admission payload digest mismatch")
        signature_text = envelope.get("signature")
        if not isinstance(signature_text, str):
            raise TrustedAdmissionError("trusted admission signature is invalid")
        try:
            signature = base64.b64decode(signature_text, validate=True)
        except (TypeError, ValueError) as exc:
            raise TrustedAdmissionError("trusted admission signature is invalid") from exc
        try:
            self._public_key.verify(
                signature,
                canonical_json(
                    _signature_material(
                        key_id=self._key_id,
                        signed_at=signed_at,
                        payload_sha256=payload_sha256,
                        payload=normalized,
                    )
                ).encode("utf-8"),
            )
        except InvalidSignature as exc:
            raise TrustedAdmissionError("trusted admission signature verification failed") from exc
        return normalized


def build_trusted_admission_payload(
    expected: TrustedAdmissionContext,
    *,
    admission_id: str,
) -> dict[str, str]:
    """Build the canonical server-side payload before external signing."""

    try:
        parsed_id = uuid.UUID(admission_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("admission_id must be a canonical UUID") from exc
    if str(parsed_id) != admission_id:
        raise ValueError("admission_id must be a canonical UUID")
    return {
        "schema_version": _SCHEMA_VERSION,
        "issuer": _ISSUER,
        "admission_id": admission_id,
        **expected.material(),
    }


def sign_trusted_admission_envelope(
    payload: Mapping[str, str],
    *,
    private_key: Ed25519PrivateKey,
    key_id: str,
    signed_at: str,
) -> dict[str, Any]:
    """External-signer helper; production verifier code never receives this key."""

    if not isinstance(private_key, Ed25519PrivateKey):
        raise TypeError("trusted admission signer must use Ed25519")
    normalized = _normalize_payload(payload)
    key_identity = _bounded_identity(key_id, field="key_id", maximum=160)
    _validate_timestamp(signed_at)
    payload_sha256 = canonical_sha256(normalized)
    signature = private_key.sign(
        canonical_json(
            _signature_material(
                key_id=key_identity,
                signed_at=signed_at,
                payload_sha256=payload_sha256,
                payload=normalized,
            )
        ).encode("utf-8")
    )
    return {
        "schema_version": _SCHEMA_VERSION,
        "algorithm": _ALGORITHM,
        "key_id": key_identity,
        "signed_at": signed_at,
        "payload_sha256": payload_sha256,
        "payload": normalized,
        "signature": base64.b64encode(signature).decode("ascii"),
    }


def admission_receipt_sha256(expected: TrustedAdmissionContext) -> str:
    """Content address used to fetch the persisted signed envelope."""

    return canonical_sha256(
        {
            "schema_version": _SCHEMA_VERSION,
            "issuer": _ISSUER,
            **expected.material(),
        }
    )


def _normalize_payload(payload: Mapping[str, Any]) -> dict[str, str]:
    if set(payload) != _PAYLOAD_FIELDS:
        raise TrustedAdmissionError("trusted admission payload shape is invalid")
    if any(not isinstance(value, str) for value in payload.values()):
        raise TrustedAdmissionError("trusted admission payload values must be strings")
    normalized = {key: str(payload[key]) for key in sorted(_PAYLOAD_FIELDS)}
    if normalized["schema_version"] != _SCHEMA_VERSION or normalized["issuer"] != _ISSUER:
        raise TrustedAdmissionError("trusted admission payload issuer is invalid")
    try:
        parsed_id = uuid.UUID(normalized["admission_id"])
    except ValueError as exc:
        raise TrustedAdmissionError("trusted admission id is invalid") from exc
    if str(parsed_id) != normalized["admission_id"]:
        raise TrustedAdmissionError("trusted admission id is not canonical")
    _ContextBase.validate_material(
        {
            key: value
            for key, value in normalized.items()
            if key not in {"schema_version", "issuer", "admission_id"}
        }
    )
    return normalized


def _signature_material(
    *,
    key_id: str,
    signed_at: str,
    payload_sha256: str,
    payload: Mapping[str, str],
) -> dict[str, object]:
    """Cover envelope metadata as well as the payload with the Ed25519 signature."""

    return {
        "schema_version": _SCHEMA_VERSION,
        "algorithm": _ALGORITHM,
        "key_id": key_id,
        "signed_at": signed_at,
        "payload_sha256": payload_sha256,
        "payload": dict(payload),
    }


def _bounded_identity(value: str, *, field: str, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > maximum
        or value != value.strip()
        or any(ord(character) < 32 for character in value)
    ):
        raise ValueError(f"{field} is invalid")
    return value


def _validate_timestamp(value: str) -> None:
    if _UTC_TIMESTAMP.fullmatch(value) is None:
        raise ValueError("signed_at must be an explicit UTC RFC3339 timestamp")
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as exc:
        raise ValueError("signed_at is not a real timestamp") from exc
    if parsed.utcoffset() is None:
        raise ValueError("signed_at must be timezone-aware")


__all__ = [
    "PersistedAdmissionEnvelopeReader",
    "PersistedEd25519AdmissionVerifier",
    "TrustedAdmissionContext",
    "TrustedAdmissionError",
    "TrustedAdmissionVerifier",
    "admission_receipt_sha256",
    "build_trusted_admission_payload",
    "sign_trusted_admission_envelope",
]
