from __future__ import annotations

import pytest
from akc_cir.dependency import DependencyChannel
from akc_cir.derivation import ContentAddressedCache, DerivationManifest, ExecutionClass


def _manifest(**kw) -> DerivationManifest:
    values = dict(
        artifact_id="artifact_1",
        tenant_id="tenant_a",
        logical_unit_ids=("ku_1",),
        evidence_occurrence_ids=("ev_page_1",),
        source_content_hashes=("sha256:content",),
        parser="paddle",
        parser_version="1.0",
        config_fingerprint="sha256:config",
    )
    values.update(kw)
    return DerivationManifest(**values)


def test_semantic_cache_key_survives_locator_only_occurrence_move() -> None:
    before = _manifest(evidence_occurrence_ids=("ev_page_1",))
    after = _manifest(evidence_occurrence_ids=("ev_page_9",))
    assert before.cache_key == after.cache_key
    assert before.lineage_fingerprint != after.lineage_fingerprint


def test_locator_sensitive_artifact_invalidates_on_occurrence_move() -> None:
    channels = frozenset({DependencyChannel.SEMANTIC, DependencyChannel.LOCATOR})
    before = _manifest(dependency_channels=channels, evidence_occurrence_ids=("ev_page_1",))
    after = _manifest(dependency_channels=channels, evidence_occurrence_ids=("ev_page_9",))
    assert before.cache_key != after.cache_key


def test_pinned_stochastic_requires_seed_and_version() -> None:
    with pytest.raises(ValueError, match="seed"):
        _manifest(execution_class=ExecutionClass.PINNED_STOCHASTIC, model="vlm", model_version="v1")
    manifest = _manifest(
        execution_class=ExecutionClass.PINNED_STOCHASTIC,
        model="vlm",
        model_version="v1",
        stochastic_seed=7,
    )
    assert manifest.reusable


def test_impure_outputs_cannot_pollute_reusable_cache() -> None:
    cache: ContentAddressedCache[str] = ContentAddressedCache()
    manifest = _manifest(execution_class=ExecutionClass.IMPURE)
    with pytest.raises(ValueError, match="IMPURE"):
        cache.put(manifest, "value")


def test_cache_is_tenant_scoped_and_supports_retention_deletion() -> None:
    cache: ContentAddressedCache[str] = ContentAddressedCache()
    a = _manifest(tenant_id="tenant_a")
    b = _manifest(tenant_id="tenant_b")
    cache.put(a, "A")
    cache.put(b, "B")
    assert cache.get(a) == "A"
    assert cache.get(b) == "B"
    assert cache.delete_tenant("tenant_a") == 1
    assert cache.get(a) is None
    assert cache.get(b) == "B"