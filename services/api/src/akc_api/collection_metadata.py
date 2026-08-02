"""Field-level protection for collection source names and relative paths."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import re
import unicodedata
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol

from akc_security import safe_relative_path
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import SecretStr

_KEY_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_NONCE_BYTES = 12
_TAG_BYTES = 16
_MAX_KEYS = 16
_SOURCE_ROOT_DISPLAY_DOMAIN = b"akc.collection.source-root.display-name.v1\0"
_FILE_RELATIVE_PATH_DOMAIN = b"akc.collection.file.relative-path.v1\0"
_FILE_DISPLAY_NAME_DOMAIN = b"akc.collection.file.display-name.v1\0"
_RELATIVE_PATH_INDEX_DOMAIN = b"akc.collection.file.relative-path-index.v1\0"


class CollectionMetadataError(ValueError):
    """Base error that never includes protected metadata or key material."""


class CollectionMetadataConfigurationError(CollectionMetadataError):
    """Raised before startup when the key contract is incomplete."""


class CollectionMetadataIntegrityError(CollectionMetadataError):
    """Raised when ciphertext, key identity, or row binding cannot be verified."""


@dataclass(frozen=True, slots=True)
class EncryptedCollectionMetadata:
    key_id: str
    ciphertext: bytes


@dataclass(frozen=True, slots=True)
class CollectionPathBlindIndex:
    key_id: str
    digest: bytes


class CollectionMetadataSettings(Protocol):
    env: Literal["development", "test", "production"]
    collection_metadata_encryption_enabled: bool
    collection_metadata_active_key_id: str
    collection_metadata_keyring: SecretStr | None
    collection_metadata_blind_index_key_id: str
    collection_metadata_blind_index_key: SecretStr | None

    def _development_secret(self, purpose: str) -> bytes: ...


def _validate_key_id(value: str, *, label: str) -> str:
    if _KEY_ID_PATTERN.fullmatch(value) is None:
        raise CollectionMetadataConfigurationError(f"{label} is not a bounded key identifier")
    return value


def _decode_base64_key(value: str, *, label: str) -> bytes:
    if not value.startswith("base64:"):
        raise CollectionMetadataConfigurationError(f"{label} must use base64: encoding")
    try:
        decoded = base64.b64decode(
            value.removeprefix("base64:"),
            altchars=b"-_",
            validate=True,
        )
    except (ValueError, binascii.Error) as exc:
        raise CollectionMetadataConfigurationError(f"{label} is not valid base64") from exc
    if len(decoded) != 32:
        raise CollectionMetadataConfigurationError(f"{label} must decode to exactly 32 bytes")
    return decoded


def parse_collection_metadata_keyring(value: str) -> dict[str, bytes]:
    """Parse a bounded Secret-backed JSON object of AES-256 keys."""

    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise CollectionMetadataConfigurationError(
            "collection metadata keyring must be valid JSON"
        ) from exc
    if not isinstance(payload, dict) or not payload or len(payload) > _MAX_KEYS:
        raise CollectionMetadataConfigurationError(
            "collection metadata keyring must contain between 1 and 16 keys"
        )
    parsed: dict[str, bytes] = {}
    for raw_key_id, raw_key in payload.items():
        if not isinstance(raw_key_id, str) or not isinstance(raw_key, str):
            raise CollectionMetadataConfigurationError(
                "collection metadata keyring entries must be string pairs"
            )
        key_id = _validate_key_id(raw_key_id, label="collection metadata key id")
        parsed[key_id] = _decode_base64_key(
            raw_key,
            label=f"collection metadata key {key_id}",
        )
    return parsed


def decode_collection_blind_index_key(value: str) -> bytes:
    """Decode one independent HMAC key without accepting short material."""

    if value.startswith("base64:"):
        return _decode_base64_key(value, label="collection metadata blind-index key")
    try:
        decoded = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise CollectionMetadataConfigurationError(
            "collection metadata blind-index key is not valid UTF-8"
        ) from exc
    if len(decoded) < 32:
        raise CollectionMetadataConfigurationError(
            "collection metadata blind-index key must contain at least 32 bytes"
        )
    return decoded


def _bounded_text(value: str, *, maximum_characters: int, field: str) -> bytes:
    if not value or len(value) > maximum_characters:
        raise CollectionMetadataIntegrityError(f"{field} is outside its length contract")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise CollectionMetadataIntegrityError(f"{field} contains a control character")
    try:
        return value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise CollectionMetadataIntegrityError(f"{field} is not valid Unicode") from exc


def _source_root_aad(
    *,
    tenant_id: uuid.UUID,
    collection_id: uuid.UUID,
    source_root_id: uuid.UUID,
) -> bytes:
    return (
        _SOURCE_ROOT_DISPLAY_DOMAIN + tenant_id.bytes + collection_id.bytes + source_root_id.bytes
    )


def _file_aad(
    domain: bytes,
    *,
    tenant_id: uuid.UUID,
    collection_id: uuid.UUID,
    source_root_id: uuid.UUID,
    file_id: uuid.UUID,
) -> bytes:
    return domain + tenant_id.bytes + collection_id.bytes + source_root_id.bytes + file_id.bytes


def normalize_collection_relative_path(value: str) -> str:
    """Return the comparison form frozen for uniqueness and blind indexing."""

    try:
        safe = safe_relative_path(value)
    except ValueError as exc:
        raise CollectionMetadataIntegrityError("relative path is not safe") from exc
    _bounded_text(safe, maximum_characters=2_000, field="relative path")
    return unicodedata.normalize("NFC", safe).casefold()


class CollectionMetadataCodec:
    """Randomized AES-GCM fields plus a separately keyed path blind index."""

    def __init__(
        self,
        *,
        active_key_id: str,
        keyring: Mapping[str, bytes],
        blind_index_key_id: str,
        blind_index_key: bytes,
    ) -> None:
        self.active_key_id = _validate_key_id(
            active_key_id,
            label="collection metadata active key id",
        )
        if not keyring or len(keyring) > _MAX_KEYS:
            raise CollectionMetadataConfigurationError(
                "collection metadata keyring must contain between 1 and 16 keys"
            )
        ciphers: dict[str, AESGCM] = {}
        for raw_key_id, key in keyring.items():
            key_id = _validate_key_id(raw_key_id, label="collection metadata key id")
            if len(key) != 32:
                raise CollectionMetadataConfigurationError(
                    "collection metadata encryption keys must contain exactly 32 bytes"
                )
            ciphers[key_id] = AESGCM(bytes(key))
        if self.active_key_id not in ciphers:
            raise CollectionMetadataConfigurationError(
                "collection metadata active key id is absent from the decrypt keyring"
            )
        self._ciphers = ciphers
        self.blind_index_key_id = _validate_key_id(
            blind_index_key_id,
            label="collection metadata blind-index key id",
        )
        if len(blind_index_key) < 32:
            raise CollectionMetadataConfigurationError(
                "collection metadata blind-index key must contain at least 32 bytes"
            )
        self._blind_index_key = bytes(blind_index_key)

    def _encrypt(self, plaintext: bytes, aad: bytes) -> EncryptedCollectionMetadata:
        nonce = os.urandom(_NONCE_BYTES)
        ciphertext = self._ciphers[self.active_key_id].encrypt(nonce, plaintext, aad)
        return EncryptedCollectionMetadata(
            key_id=self.active_key_id,
            ciphertext=nonce + ciphertext,
        )

    def _decrypt(self, *, key_id: str, ciphertext: bytes, aad: bytes) -> bytes:
        cipher = self._ciphers.get(key_id)
        if cipher is None or len(ciphertext) < _NONCE_BYTES + _TAG_BYTES:
            raise CollectionMetadataIntegrityError("collection metadata ciphertext is unavailable")
        try:
            return cipher.decrypt(
                ciphertext[:_NONCE_BYTES],
                ciphertext[_NONCE_BYTES:],
                aad,
            )
        except InvalidTag as exc:
            raise CollectionMetadataIntegrityError(
                "collection metadata ciphertext failed authentication"
            ) from exc

    @staticmethod
    def _decode_text(
        plaintext: bytes,
        *,
        maximum_characters: int,
        field: str,
    ) -> str:
        try:
            value = plaintext.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CollectionMetadataIntegrityError(
                "collection metadata plaintext is not valid UTF-8"
            ) from exc
        _bounded_text(value, maximum_characters=maximum_characters, field=field)
        return value

    def encrypt_source_root_display_name(
        self,
        value: str,
        *,
        tenant_id: uuid.UUID,
        collection_id: uuid.UUID,
        source_root_id: uuid.UUID,
    ) -> EncryptedCollectionMetadata:
        return self._encrypt(
            _bounded_text(value, maximum_characters=500, field="source root display name"),
            _source_root_aad(
                tenant_id=tenant_id,
                collection_id=collection_id,
                source_root_id=source_root_id,
            ),
        )

    def decrypt_source_root_display_name(
        self,
        ciphertext: bytes,
        *,
        key_id: str,
        tenant_id: uuid.UUID,
        collection_id: uuid.UUID,
        source_root_id: uuid.UUID,
    ) -> str:
        plaintext = self._decrypt(
            key_id=key_id,
            ciphertext=ciphertext,
            aad=_source_root_aad(
                tenant_id=tenant_id,
                collection_id=collection_id,
                source_root_id=source_root_id,
            ),
        )
        return self._decode_text(
            plaintext,
            maximum_characters=500,
            field="source root display name",
        )

    def encrypt_file_relative_path(
        self,
        value: str,
        *,
        tenant_id: uuid.UUID,
        collection_id: uuid.UUID,
        source_root_id: uuid.UUID,
        file_id: uuid.UUID,
    ) -> EncryptedCollectionMetadata:
        try:
            safe = safe_relative_path(value)
        except ValueError as exc:
            raise CollectionMetadataIntegrityError("relative path is not safe") from exc
        return self._encrypt(
            _bounded_text(safe, maximum_characters=2_000, field="relative path"),
            _file_aad(
                _FILE_RELATIVE_PATH_DOMAIN,
                tenant_id=tenant_id,
                collection_id=collection_id,
                source_root_id=source_root_id,
                file_id=file_id,
            ),
        )

    def decrypt_file_relative_path(
        self,
        ciphertext: bytes,
        *,
        key_id: str,
        tenant_id: uuid.UUID,
        collection_id: uuid.UUID,
        source_root_id: uuid.UUID,
        file_id: uuid.UUID,
    ) -> str:
        plaintext = self._decrypt(
            key_id=key_id,
            ciphertext=ciphertext,
            aad=_file_aad(
                _FILE_RELATIVE_PATH_DOMAIN,
                tenant_id=tenant_id,
                collection_id=collection_id,
                source_root_id=source_root_id,
                file_id=file_id,
            ),
        )
        value = self._decode_text(
            plaintext,
            maximum_characters=2_000,
            field="relative path",
        )
        try:
            return safe_relative_path(value)
        except ValueError as exc:
            raise CollectionMetadataIntegrityError("decrypted relative path is not safe") from exc

    def encrypt_file_display_name(
        self,
        value: str,
        *,
        tenant_id: uuid.UUID,
        collection_id: uuid.UUID,
        source_root_id: uuid.UUID,
        file_id: uuid.UUID,
    ) -> EncryptedCollectionMetadata:
        return self._encrypt(
            _bounded_text(value, maximum_characters=500, field="file display name"),
            _file_aad(
                _FILE_DISPLAY_NAME_DOMAIN,
                tenant_id=tenant_id,
                collection_id=collection_id,
                source_root_id=source_root_id,
                file_id=file_id,
            ),
        )

    def decrypt_file_display_name(
        self,
        ciphertext: bytes,
        *,
        key_id: str,
        tenant_id: uuid.UUID,
        collection_id: uuid.UUID,
        source_root_id: uuid.UUID,
        file_id: uuid.UUID,
    ) -> str:
        plaintext = self._decrypt(
            key_id=key_id,
            ciphertext=ciphertext,
            aad=_file_aad(
                _FILE_DISPLAY_NAME_DOMAIN,
                tenant_id=tenant_id,
                collection_id=collection_id,
                source_root_id=source_root_id,
                file_id=file_id,
            ),
        )
        return self._decode_text(
            plaintext,
            maximum_characters=500,
            field="file display name",
        )

    def relative_path_blind_index(
        self,
        value: str,
        *,
        tenant_id: uuid.UUID,
        collection_id: uuid.UUID,
        source_root_id: uuid.UUID,
    ) -> CollectionPathBlindIndex:
        comparison = normalize_collection_relative_path(value).encode("utf-8")
        message = (
            _RELATIVE_PATH_INDEX_DOMAIN
            + tenant_id.bytes
            + collection_id.bytes
            + source_root_id.bytes
            + len(comparison).to_bytes(4, "big")
            + comparison
        )
        return CollectionPathBlindIndex(
            key_id=self.blind_index_key_id,
            digest=hmac.new(self._blind_index_key, message, hashlib.sha256).digest(),
        )


def build_collection_metadata_codec(
    settings: CollectionMetadataSettings,
) -> CollectionMetadataCodec | None:
    """Build the codec only when the collection metadata gate is enabled."""

    if not settings.collection_metadata_encryption_enabled:
        return None

    active_key_id = settings.collection_metadata_active_key_id
    keyring_secret = settings.collection_metadata_keyring
    blind_index_key_id = settings.collection_metadata_blind_index_key_id
    blind_index_secret = settings.collection_metadata_blind_index_key
    if settings.env == "production":
        if not active_key_id or keyring_secret is None:
            raise CollectionMetadataConfigurationError(
                "production collection metadata encryption keyring is not configured"
            )
        if not blind_index_key_id or blind_index_secret is None:
            raise CollectionMetadataConfigurationError(
                "production collection metadata blind-index key is not configured"
            )
        keyring = parse_collection_metadata_keyring(keyring_secret.get_secret_value())
        blind_index_key = decode_collection_blind_index_key(blind_index_secret.get_secret_value())
    else:
        active_key_id = active_key_id or "development-v1"
        blind_index_key_id = blind_index_key_id or "development-bidx-v1"
        keyring = (
            parse_collection_metadata_keyring(keyring_secret.get_secret_value())
            if keyring_secret is not None
            else {active_key_id: settings._development_secret("collection-metadata-aead")}
        )
        blind_index_key = (
            decode_collection_blind_index_key(blind_index_secret.get_secret_value())
            if blind_index_secret is not None
            else settings._development_secret("collection-metadata-blind-index")
        )
    return CollectionMetadataCodec(
        active_key_id=active_key_id,
        keyring=keyring,
        blind_index_key_id=blind_index_key_id,
        blind_index_key=blind_index_key,
    )


__all__ = [
    "CollectionMetadataCodec",
    "CollectionMetadataConfigurationError",
    "CollectionMetadataError",
    "CollectionMetadataIntegrityError",
    "CollectionPathBlindIndex",
    "EncryptedCollectionMetadata",
    "build_collection_metadata_codec",
    "decode_collection_blind_index_key",
    "normalize_collection_relative_path",
    "parse_collection_metadata_keyring",
]
