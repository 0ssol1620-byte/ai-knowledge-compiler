from __future__ import annotations

from infra.security.validate_deployment import (
    COLLECTION_RUNTIME_SECRET_KEYS,
    _collection_runtime_keys_in,
)


def test_collection_runtime_keys_are_reported_by_name_only() -> None:
    misplaced = sorted(COLLECTION_RUNTIME_SECRET_KEYS)[0]
    value = "value-that-must-not-reach-a-log"
    found = _collection_runtime_keys_in({misplaced: value, "AKC_PUBLIC_FLAG": "true"})
    assert found == [misplaced]
    assert value not in repr(found)


def test_collection_runtime_keys_in_clean_mapping_is_empty() -> None:
    assert _collection_runtime_keys_in({"AKC_PUBLIC_FLAG": "true"}) == []
