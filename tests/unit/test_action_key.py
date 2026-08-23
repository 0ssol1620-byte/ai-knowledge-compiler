"""An action-key cache is a standing invitation to lie to yourself.

CompilationActionKey turns "did this exact build already happen?" into a hash
comparison, and a hash comparison is only as safe as the guards around it. So
these tests are adversarial on purpose: every way the world can drift after an
artifact was stored — a policy revision that changed, a permission scope that
narrowed, bytes someone swapped on disk, a dependency that went stale, a model
or prompt that moved on, a validation that never passed — must end in MISS
plus the reason, never in silent reuse. Order independence of the key and
resistance to same-key/different-bytes collisions close the suite.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from akc_cir.action_key import (
    MISS,
    ActionKeyStore,
    ExecutionContract,
    ReuseFailureReason,
    compute_action_key,
    reuse_guard,
)

ARTIFACT = b"compiled knowledge package bytes"

VALIDATIONS: dict[str, dict[str, Any]] = {
    "unit-tests": {"status": "passed", "at": "2026-08-23T03:00:00Z"},
}


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


DIGEST_A = _digest(b"alpha contents")
DIGEST_B = _digest(b"beta contents")
DIGEST_C = _digest(b"gamma contents")


def _contract(**overrides: Any) -> ExecutionContract:
    values: dict[str, Any] = {
        "compiler_revision": "compiler@2026.08.1",
        "parser_revision": "parser@7",
        "schema_revision": "schema/v4.2",
        "policy_revision": "policy@2026-08-01",
        "permission_scope": frozenset({"corpus:read", "build:compile"}),
        "tenant_id": "tenant-acme",
        "params": {"profile": "balanced"},
    }
    values.update(overrides)
    return ExecutionContract(**values)


def _materialize_inputs(root: Path) -> list[tuple[str, str]]:
    """Write two input files, deliberately listed out of lexicographic order."""
    contents = {"zeta.md": b"beta contents", "alpha.md": b"alpha contents"}
    pairs = []
    for name, data in contents.items():
        path = root / name
        path.write_bytes(data)
        pairs.append((str(path), _digest(data)))
    return pairs


def _seed(
    tmp_path: Path,
    *,
    overrides: dict[str, Any] | None = None,
    validations: Mapping[str, Mapping[str, Any]] | None = None,
) -> tuple[ActionKeyStore, str, ExecutionContract, Path]:
    root = tmp_path / "inputs"
    root.mkdir(parents=True, exist_ok=True)
    inputs = _materialize_inputs(root)
    contract = _contract(**(overrides or {}))
    key = compute_action_key(inputs, contract)
    store = ActionKeyStore(tmp_path / "cas")
    store.put(
        key,
        ARTIFACT,
        {"build_id": "build-1"},
        contract=contract,
        inputs=inputs,
        validations=dict(validations) if validations is not None else dict(VALIDATIONS),
    )
    return store, key, contract, root


# ---------------------------------------------------------------------------
# Determinism — one world state, one key, regardless of listing order
# ---------------------------------------------------------------------------


def test_the_same_inputs_in_any_order_hash_to_one_action_key() -> None:
    forward = compute_action_key(
        [("a.md", DIGEST_A), ("b.md", DIGEST_B)],
        _contract(params={"x": 1, "y": [1, 2]}),
    )
    backward = compute_action_key(
        [("b.md", DIGEST_B), ("a.md", DIGEST_A)],
        _contract(params={"y": [1, 2], "x": 1}),
    )

    assert forward == backward


def test_conflicting_digests_for_one_path_are_refused() -> None:
    with pytest.raises(ValueError, match="conflicting"):
        compute_action_key([("a.md", DIGEST_A), ("a.md", DIGEST_B)], _contract())


def test_any_real_change_to_inputs_or_identity_moves_the_action_key() -> None:
    base_inputs = [("a.md", DIGEST_A), ("b.md", DIGEST_B)]
    base = compute_action_key(base_inputs, _contract())
    variants = [
        compute_action_key([("a.md", DIGEST_A), ("b.md", DIGEST_C)], _contract()),
        compute_action_key(base_inputs, _contract(compiler_revision="compiler@2026.09.1")),
        compute_action_key(base_inputs, _contract(parser_revision="parser@8")),
        compute_action_key(base_inputs, _contract(schema_revision="schema/v5")),
        compute_action_key(base_inputs, _contract(tenant_id="tenant-other")),
        compute_action_key(
            base_inputs,
            _contract(permission_scope=frozenset({"corpus:read", "build:compile", "net:fetch"})),
        ),
        compute_action_key(base_inputs, _contract(params={"profile": "precise"})),
    ]

    assert len(set(variants)) == len(variants)
    assert base not in variants


# ---------------------------------------------------------------------------
# Fail-closed construction — an incomplete contract never becomes a key
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field",
    ["compiler_revision", "parser_revision", "schema_revision", "policy_revision", "tenant_id"],
)
def test_blank_identity_fields_are_refused(field: str) -> None:
    with pytest.raises(ValueError, match=field):
        _contract(**{field: "   "})


def test_an_empty_permission_scope_is_refused() -> None:
    with pytest.raises(ValueError, match="permission_scope"):
        _contract(permission_scope=frozenset())


def test_unserializable_params_fail_closed() -> None:
    with pytest.raises(TypeError):
        compute_action_key([], _contract(params={"obj": object()}))


# ---------------------------------------------------------------------------
# The honest path — store, fetch, verify, reuse
# ---------------------------------------------------------------------------


def test_an_honest_replay_hits_both_the_store_and_the_guard(tmp_path: Path) -> None:
    store, key, contract, _root = _seed(tmp_path)

    assert store.verify_integrity(key) is True
    artifact, envelope = store.get(key)
    assert artifact == ARTIFACT
    assert envelope["receipt"] == {"build_id": "build-1"}

    decision = reuse_guard(key, contract, ["unit-tests"], store=store)
    assert decision.hit is True
    assert decision.reason is None
    assert decision.detail
    assert decision.artifact == ARTIFACT
    assert decision.receipt == {"build_id": "build-1"}
    assert reuse_guard(key, contract, [], store=store).hit is True


def test_a_lookup_under_an_unknown_or_malformed_key_misses(tmp_path: Path) -> None:
    store, _key, _contract_obj, _root = _seed(tmp_path)

    assert store.get(_digest(b"never stored")) is MISS
    assert store.verify_integrity(_digest(b"never stored")) is False
    with pytest.raises(ValueError, match="key"):
        store.get("../escape")


# ---------------------------------------------------------------------------
# Sabotage — bytes swapped under a known key
# ---------------------------------------------------------------------------


def test_swapped_bytes_under_a_known_key_cannot_reuse(tmp_path: Path) -> None:
    store, key, contract, _root = _seed(tmp_path)

    store.artifact_path(key).write_bytes(b"counterfeit bytes")

    assert store.verify_integrity(key) is False
    decision = reuse_guard(key, contract, ["unit-tests"], store=store)
    assert decision.hit is False
    assert decision.reason is ReuseFailureReason.CORRUPT_ARTIFACT


def test_a_forged_envelope_cannot_impersonate_an_entry(tmp_path: Path) -> None:
    store, key, contract, _root = _seed(tmp_path)

    forged = {
        "format": "akc.action-key-store.v1",
        "key": key,
        "artifact_sha256": "sha256:" + "0" * 64,
        "preimage": '{"forged": true}',
        "guard": {"contract": {"compiler_revision": "evil"}, "inputs": []},
        "validations": {"unit-tests": {"status": "passed"}},
        "receipt": {"build_id": "evil-1"},
    }
    store.envelope_path(key).write_text(json.dumps(forged), encoding="utf-8")

    assert store.verify_integrity(key) is False
    decision = reuse_guard(key, contract, ["unit-tests"], store=store)
    assert decision.hit is False
    assert decision.reason is ReuseFailureReason.CORRUPT_ARTIFACT


def test_an_entry_minted_elsewhere_cannot_be_transplanted_under_our_key(tmp_path: Path) -> None:
    store, key, contract, root = _seed(tmp_path)
    other_inputs = [(str(root / "alpha.md"), _digest(b"mallory world"))]
    other_contract = _contract(tenant_id="tenant-mallory")
    other_key = compute_action_key(other_inputs, other_contract)
    store.put(
        other_key,
        b"mallory artifact",
        {"build_id": "mallory"},
        contract=other_contract,
        inputs=other_inputs,
        validations=dict(VALIDATIONS),
    )

    stolen = store.envelope_path(other_key).read_text(encoding="utf-8")
    store.envelope_path(key).write_text(stolen, encoding="utf-8")
    store.artifact_path(key).write_bytes(b"mallory artifact")

    assert store.verify_integrity(key) is False
    decision = reuse_guard(key, contract, ["unit-tests"], store=store)
    assert decision.hit is False
    assert decision.reason is ReuseFailureReason.CORRUPT_ARTIFACT


# ---------------------------------------------------------------------------
# Sabotage — the world drifted while nobody was looking
# ---------------------------------------------------------------------------


def test_a_policy_change_breaks_reuse_even_under_the_old_key(tmp_path: Path) -> None:
    store, key, _contract_obj, _root = _seed(tmp_path)
    drifted = _contract(policy_revision="policy@2026-09-01")

    decision = reuse_guard(key, drifted, ["unit-tests"], store=store)

    assert decision.hit is False
    assert decision.reason is ReuseFailureReason.POLICY_CHANGED


def test_narrowed_permissions_block_reuse_but_broadened_ones_do_not(tmp_path: Path) -> None:
    store, key, _contract_obj, _root = _seed(tmp_path)
    narrower = _contract(permission_scope=frozenset({"corpus:read"}))
    broader = _contract(
        permission_scope=frozenset({"corpus:read", "build:compile", "net:fetch"})
    )

    denied = reuse_guard(key, narrower, ["unit-tests"], store=store)
    allowed = reuse_guard(key, broader, ["unit-tests"], store=store)

    assert denied.hit is False
    assert denied.reason is ReuseFailureReason.PERMISSION_NARROWED
    assert allowed.hit is True


def test_a_stale_dependency_blocks_reuse(tmp_path: Path) -> None:
    store, key, contract, root = _seed(tmp_path)

    (root / "alpha.md").write_bytes(b"tampered after the fact")

    decision = reuse_guard(key, contract, ["unit-tests"], store=store)
    assert decision.hit is False
    assert decision.reason is ReuseFailureReason.STALE_DEP


def test_a_vanished_dependency_reports_missing_input(tmp_path: Path) -> None:
    store, key, contract, root = _seed(tmp_path)

    (root / "alpha.md").unlink()

    decision = reuse_guard(key, contract, ["unit-tests"], store=store)
    assert decision.hit is False
    assert decision.reason is ReuseFailureReason.MISSING_INPUT


def test_model_and_prompt_changes_miss_without_moving_the_key(tmp_path: Path) -> None:
    store, key, _contract_obj, root = _seed(tmp_path)
    inputs = _materialize_inputs(root)
    model_drift = _contract(model_revision="model@2026-09")
    prompt_drift = _contract(prompt_revision="prompt@42")

    # model/prompt are guarded, not hashed: they must not silently move the key…
    assert compute_action_key(inputs, model_drift) == key
    assert compute_action_key(inputs, prompt_drift) == key

    model_decision = reuse_guard(key, model_drift, ["unit-tests"], store=store)
    prompt_decision = reuse_guard(key, prompt_drift, ["unit-tests"], store=store)
    assert model_decision.hit is False
    assert model_decision.reason is ReuseFailureReason.MODEL_CHANGED
    assert prompt_decision.hit is False
    assert prompt_decision.reason is ReuseFailureReason.PROMPT_CHANGED


def test_dropping_a_previously_declared_model_also_misses(tmp_path: Path) -> None:
    store, key, _contract_obj, _root = _seed(
        tmp_path, overrides={"model_revision": "model@2026-08", "prompt_revision": "prompt@7"}
    )
    anonymous = _contract()

    decision = reuse_guard(key, anonymous, ["unit-tests"], store=store)

    assert decision.hit is False
    assert decision.reason is ReuseFailureReason.MODEL_CHANGED


def test_validation_evidence_gates_reuse(tmp_path: Path) -> None:
    store, key, contract, _root = _seed(tmp_path)
    failed_store, failed_key, failed_contract, _failed_root = _seed(
        tmp_path,
        overrides={"tenant_id": "tenant-bravo"},
        validations={"unit-tests": {"status": "failed", "at": "2026-08-23T04:00:00Z"}},
    )

    unevidenced = reuse_guard(key, contract, ["integration-suite"], store=store)
    failed = reuse_guard(
        failed_key, failed_contract, ["unit-tests"], store=failed_store
    )

    assert unevidenced.hit is False
    assert unevidenced.reason is ReuseFailureReason.MISSING_INPUT
    assert failed.hit is False
    assert failed.reason is ReuseFailureReason.STALE_DEP
