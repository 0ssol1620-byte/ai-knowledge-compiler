from __future__ import annotations

import base64
import json
import uuid

import pytest
from akc_api.collection_metadata import (
    CollectionMetadataCodec,
    CollectionMetadataConfigurationError,
    CollectionMetadataIntegrityError,
    build_collection_metadata_codec,
    parse_collection_metadata_keyring,
)
from akc_api.collection_schemas import CollectionFilesPlan
from akc_api.settings import Settings
from pydantic import SecretStr, ValidationError


def _codec(
    *,
    active_key_id: str = "metadata-v1",
    keyring: dict[str, bytes] | None = None,
) -> CollectionMetadataCodec:
    return CollectionMetadataCodec(
        active_key_id=active_key_id,
        keyring=keyring or {active_key_id: b"a" * 32},
        blind_index_key_id="path-index-v1",
        blind_index_key=b"b" * 32,
    )


def _ids() -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    return uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


def test_collection_metadata_round_trip_is_randomized_and_not_plaintext() -> None:
    codec = _codec()
    tenant_id, collection_id, source_root_id, file_id = _ids()
    root_name = "민감 고객 폴더"
    relative_path = "회사자료/제품/A/매뉴얼.pdf"
    display_name = "매뉴얼.pdf"

    encrypted_root = codec.encrypt_source_root_display_name(
        root_name,
        tenant_id=tenant_id,
        collection_id=collection_id,
        source_root_id=source_root_id,
    )
    encrypted_path = codec.encrypt_file_relative_path(
        relative_path,
        tenant_id=tenant_id,
        collection_id=collection_id,
        source_root_id=source_root_id,
        file_id=file_id,
    )
    second_path = codec.encrypt_file_relative_path(
        relative_path,
        tenant_id=tenant_id,
        collection_id=collection_id,
        source_root_id=source_root_id,
        file_id=file_id,
    )
    encrypted_name = codec.encrypt_file_display_name(
        display_name,
        tenant_id=tenant_id,
        collection_id=collection_id,
        source_root_id=source_root_id,
        file_id=file_id,
    )

    assert encrypted_path.ciphertext != second_path.ciphertext
    assert root_name.encode() not in encrypted_root.ciphertext
    assert relative_path.encode() not in encrypted_path.ciphertext
    assert display_name.encode() not in encrypted_name.ciphertext
    assert (
        codec.decrypt_source_root_display_name(
            encrypted_root.ciphertext,
            key_id=encrypted_root.key_id,
            tenant_id=tenant_id,
            collection_id=collection_id,
            source_root_id=source_root_id,
        )
        == root_name
    )
    assert (
        codec.decrypt_file_relative_path(
            encrypted_path.ciphertext,
            key_id=encrypted_path.key_id,
            tenant_id=tenant_id,
            collection_id=collection_id,
            source_root_id=source_root_id,
            file_id=file_id,
        )
        == relative_path
    )
    assert (
        codec.decrypt_file_display_name(
            encrypted_name.ciphertext,
            key_id=encrypted_name.key_id,
            tenant_id=tenant_id,
            collection_id=collection_id,
            source_root_id=source_root_id,
            file_id=file_id,
        )
        == display_name
    )


@pytest.mark.parametrize("binding", ["tenant", "collection", "root", "file", "ciphertext"])
def test_collection_metadata_rejects_tamper_and_row_swaps(binding: str) -> None:
    codec = _codec()
    tenant_id, collection_id, source_root_id, file_id = _ids()
    encrypted = codec.encrypt_file_relative_path(
        "private/report.pdf",
        tenant_id=tenant_id,
        collection_id=collection_id,
        source_root_id=source_root_id,
        file_id=file_id,
    )
    ciphertext = encrypted.ciphertext
    if binding == "tenant":
        tenant_id = uuid.uuid4()
    elif binding == "collection":
        collection_id = uuid.uuid4()
    elif binding == "root":
        source_root_id = uuid.uuid4()
    elif binding == "file":
        file_id = uuid.uuid4()
    else:
        ciphertext = ciphertext[:-1] + bytes([ciphertext[-1] ^ 1])

    with pytest.raises(CollectionMetadataIntegrityError):
        codec.decrypt_file_relative_path(
            ciphertext,
            key_id=encrypted.key_id,
            tenant_id=tenant_id,
            collection_id=collection_id,
            source_root_id=source_root_id,
            file_id=file_id,
        )


def test_collection_metadata_decrypt_ring_supports_safe_aead_rotation() -> None:
    tenant_id, collection_id, source_root_id, file_id = _ids()
    old_codec = _codec(active_key_id="metadata-old", keyring={"metadata-old": b"o" * 32})
    encrypted_old = old_codec.encrypt_file_display_name(
        "private.pdf",
        tenant_id=tenant_id,
        collection_id=collection_id,
        source_root_id=source_root_id,
        file_id=file_id,
    )
    rotating_codec = _codec(
        active_key_id="metadata-new",
        keyring={"metadata-old": b"o" * 32, "metadata-new": b"n" * 32},
    )

    assert (
        rotating_codec.decrypt_file_display_name(
            encrypted_old.ciphertext,
            key_id=encrypted_old.key_id,
            tenant_id=tenant_id,
            collection_id=collection_id,
            source_root_id=source_root_id,
            file_id=file_id,
        )
        == "private.pdf"
    )
    encrypted_new = rotating_codec.encrypt_file_display_name(
        "private.pdf",
        tenant_id=tenant_id,
        collection_id=collection_id,
        source_root_id=source_root_id,
        file_id=file_id,
    )
    assert encrypted_new.key_id == "metadata-new"
    with pytest.raises(CollectionMetadataIntegrityError):
        old_codec.decrypt_file_display_name(
            encrypted_new.ciphertext,
            key_id=encrypted_new.key_id,
            tenant_id=tenant_id,
            collection_id=collection_id,
            source_root_id=source_root_id,
            file_id=file_id,
        )


def test_relative_path_blind_index_is_normalized_stable_and_scope_bound() -> None:
    codec = _codec()
    tenant_id, collection_id, source_root_id, _file_id = _ids()
    composed = codec.relative_path_blind_index(
        "RÉSUMÉ/Report.PDF",
        tenant_id=tenant_id,
        collection_id=collection_id,
        source_root_id=source_root_id,
    )
    decomposed = codec.relative_path_blind_index(
        "re\u0301sume\u0301/report.pdf",
        tenant_id=tenant_id,
        collection_id=collection_id,
        source_root_id=source_root_id,
    )
    other_root = codec.relative_path_blind_index(
        "résumé/report.pdf",
        tenant_id=tenant_id,
        collection_id=collection_id,
        source_root_id=uuid.uuid4(),
    )

    assert composed == decomposed
    assert len(composed.digest) == 32
    assert b"report" not in composed.digest
    assert other_root.digest != composed.digest


def test_collection_metadata_keyring_rejects_invalid_or_short_material() -> None:
    with pytest.raises(CollectionMetadataConfigurationError, match="valid JSON"):
        parse_collection_metadata_keyring("not-json")
    with pytest.raises(CollectionMetadataConfigurationError, match="exactly 32 bytes"):
        parse_collection_metadata_keyring(
            json.dumps({"metadata-v1": "base64:" + base64.b64encode(b"short").decode()})
        )
    with pytest.raises(CollectionMetadataConfigurationError, match="active key id is absent"):
        CollectionMetadataCodec(
            active_key_id="metadata-v2",
            keyring={"metadata-v1": b"a" * 32},
            blind_index_key_id="path-index-v1",
            blind_index_key=b"b" * 32,
        )


def test_settings_build_development_codec_without_persisted_keys() -> None:
    settings = Settings(collection_metadata_encryption_enabled=True)

    codec = build_collection_metadata_codec(settings)

    assert codec is not None
    assert codec.active_key_id == "development-v1"
    assert codec.blind_index_key_id == "development-bidx-v1"


def test_settings_accept_explicit_secret_backed_keyring() -> None:
    encoded_key = "base64:" + base64.b64encode(b"k" * 32).decode()
    settings = Settings(
        collection_metadata_encryption_enabled=True,
        collection_metadata_active_key_id="metadata-2026-08",
        collection_metadata_keyring=SecretStr(json.dumps({"metadata-2026-08": encoded_key})),
        collection_metadata_blind_index_key_id="path-index-2026-08",
        collection_metadata_blind_index_key=SecretStr(
            "base64:" + base64.b64encode(b"i" * 32).decode()
        ),
    )

    codec = build_collection_metadata_codec(settings)

    assert codec is not None
    assert codec.active_key_id == "metadata-2026-08"


def test_production_settings_fail_closed_without_collection_metadata_keys() -> None:
    with pytest.raises(
        ValidationError,
        match="production collection metadata encryption keyring is not configured",
    ):
        Settings(env="production", collection_metadata_encryption_enabled=True)


def test_semantic_retrieval_cannot_enable_over_plaintext_collection_metadata() -> None:
    with pytest.raises(
        ValidationError,
        match="collection semantic retrieval requires encrypted collection metadata",
    ):
        Settings(collection_semantic_retrieval_enabled=True)


def test_collection_plan_rejects_nfc_casefold_path_aliases() -> None:
    entry = {
        "display_name": "report.txt",
        "size_bytes": 1,
        "expected_mime": "text/plain",
        "sha256": "a" * 64,
    }
    with pytest.raises(ValidationError, match="case-insensitively unique"):
        CollectionFilesPlan(
            source_root_id=uuid.uuid4(),
            files=[
                {**entry, "relative_path": "résumé/report.txt"},
                {**entry, "relative_path": "re\u0301sume\u0301/report.txt"},
            ],
        )
