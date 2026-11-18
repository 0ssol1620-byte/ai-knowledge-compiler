from __future__ import annotations

from dataclasses import replace

import pytest
from akc_parallel_runtime.models import VerificationState
from akc_parallel_runtime.parse_reuse import ParseArtifactIndex, ReusableParseKey

KEY = ReusableParseKey(
    tenant_scope="t1",
    source_sha256="a" * 64,
    sanitized_recipe_sha256="b" * 64,
    adapter_version="1.0",
    model_digest="sha256:m1",
    ir_schema="ir1",
)
OK = VerificationState.VERIFIED


def _put(idx: ParseArtifactIndex, key: ReusableParseKey = KEY, name: str = "a.pdf") -> str:
    return idx.put(key, artifact_ref="art1", verification_state=OK, source_name=name)


def test_exact_key_hits() -> None:
    idx = ParseArtifactIndex()
    _put(idx)
    rec = idx.get(KEY)
    assert rec is not None and rec.artifact_ref == "art1"


def test_other_tenant_never_hits() -> None:
    idx = ParseArtifactIndex()
    _put(idx)
    assert idx.get(replace(KEY, tenant_scope="t2")) is None


@pytest.mark.parametrize(
    "change",
    [
        {"sanitized_recipe_sha256": "c" * 64},
        {"model_digest": "sha256:m2"},
        {"adapter_version": "1.1"},
        {"ir_schema": "ir2"},
        {"source_sha256": "d" * 64},
    ],
)
def test_any_component_mismatch_misses(change: dict[str, str]) -> None:
    idx = ParseArtifactIndex()
    _put(idx)
    assert idx.get(replace(KEY, **change)) is None


def test_unverified_artifact_is_never_stored() -> None:
    idx = ParseArtifactIndex()
    for state in set(VerificationState) - {
        VerificationState.VERIFIED,
        VerificationState.AUTHORITY_VERIFIED,
        VerificationState.CROSS_MODEL_VERIFIED,
        VerificationState.AUTO_REPAIRED,
    }:
        with pytest.raises(ValueError):
            idx.put(KEY, artifact_ref="art1", verification_state=state, source_name="a.pdf")
    assert idx.get(KEY) is None


def test_two_names_share_artifact_with_distinct_ids() -> None:
    idx = ParseArtifactIndex()
    a, b = _put(idx, name="a.pdf"), _put(idx, name="copy.pdf")
    assert a != b
    rec = idx.get(KEY)
    assert rec is not None and rec.artifact_ref == "art1" and set(rec.source_instance_ids) == {a, b}


def test_conflicting_artifact_under_same_key_refused() -> None:
    idx = ParseArtifactIndex()
    _put(idx)
    with pytest.raises(ValueError):
        idx.put(KEY, artifact_ref="other", verification_state=OK, source_name="a.pdf")


def test_key_is_canonical_regardless_of_construction_order() -> None:
    reordered = ReusableParseKey(
        ir_schema="ir1",
        model_digest="sha256:m1",
        adapter_version="1.0",
        sanitized_recipe_sha256="b" * 64,
        source_sha256="a" * 64,
        tenant_scope="t1",
    )
    assert reordered.digest == KEY.digest


def test_invalid_key_fields_refused() -> None:
    with pytest.raises(ValueError):
        replace(KEY, source_sha256="xyz")
    with pytest.raises(ValueError):
        replace(KEY, tenant_scope=" ")
