"""Every receipt-identity failure the mutation sweep found must go red here.

The sweep promoted 180 stale artifacts under each of: a receipt reused from the
prior revision, a receipt from another build attached to a rebuilt artifact, and
a builder that never recorded a class of input. The first two are closed by
binding and are asserted below. The third is not closable by binding, and the
test for it asserts a *refusal to vouch*, not a detection -- claiming otherwise
would be the overclaim this module exists to avoid.
"""

from __future__ import annotations

import dataclasses

import pytest
from akc_cir.carry_forward_receipt import (
    BuildReceipt,
    ReceiptFailure,
    VerificationLevel,
    seal_receipt,
    verify_carry_forward,
)

ART = "artifact:index:doc"


def _receipt(**overrides) -> BuildReceipt:
    base = {
        "artifact_id": ART,
        "artifact_sha256": "sha256:artifact-bytes",
        "input_fingerprint": "sha256:inputs-v1",
        "build_action_id": "build-001",
        "parent_world_state_id": "ws-001",
        "builder_version": "index-builder/3.1",
    }
    base.update(overrides)
    return seal_receipt(BuildReceipt(**base))


def _verify(receipt: BuildReceipt, **overrides):
    kwargs = {
        "receipt": receipt,
        "artifact_id": ART,
        "artifact_sha256_now": "sha256:artifact-bytes",
        "live_input_fingerprint": "sha256:inputs-v1",
        "current_world_state_id": "ws-001",
    }
    kwargs.update(overrides)
    return verify_carry_forward(**kwargs)


def test_an_intact_receipt_over_unchanged_inputs_carries_forward() -> None:
    """The gate must still say yes to the good case, or it is measuring nothing."""
    assert _verify(_receipt()).ok is True


# --- the three failures the sweep actually observed -------------------------


def test_a_receipt_from_the_prior_revision_is_refused() -> None:
    """Reusing last revision's receipt promoted 180 stale artifacts."""
    verdict = _verify(_receipt(parent_world_state_id="ws-000"), current_world_state_id="ws-001")
    assert verdict.ok is False
    assert verdict.failure is ReceiptFailure.WRONG_WORLD_STATE


def test_a_receipt_for_another_artifact_is_refused() -> None:
    verdict = _verify(_receipt(artifact_id="artifact:section:ku_0"))
    assert verdict.ok is False
    assert verdict.failure is ReceiptFailure.WRONG_ARTIFACT


def test_a_receipt_describing_other_bytes_is_refused() -> None:
    """Correct receipt, wrong artifact: the binding is what notices."""
    verdict = _verify(_receipt(), artifact_sha256_now="sha256:rebuilt-bytes")
    assert verdict.ok is False
    assert verdict.failure is ReceiptFailure.WRONG_BYTES


def test_inputs_that_moved_since_the_build_are_refused() -> None:
    verdict = _verify(_receipt(), live_input_fingerprint="sha256:inputs-v2")
    assert verdict.ok is False
    assert verdict.failure is ReceiptFailure.INPUTS_MOVED


# --- tampering with any field breaks the seal -------------------------------


@pytest.mark.parametrize(
    "field_name,value",
    [
        ("artifact_sha256", "sha256:other"),
        ("input_fingerprint", "sha256:other"),
        ("build_action_id", "build-999"),
        ("parent_world_state_id", "ws-999"),
        ("builder_version", "index-builder/9.9"),
        ("consumption_automatically_captured", False),
    ],
)
def test_editing_any_sealed_field_breaks_the_seal(field_name: str, value: object) -> None:
    """No field may be edited without detection, or the binding has a gap."""
    tampered = dataclasses.replace(_receipt(), **{field_name: value})
    verdict = _verify(tampered)
    assert verdict.ok is False
    assert verdict.failure is ReceiptFailure.SEAL_BROKEN


def test_an_unsealed_receipt_is_refused() -> None:
    """A missing seal is not a passing one."""
    unsealed = BuildReceipt(
        artifact_id=ART,
        artifact_sha256="sha256:artifact-bytes",
        input_fingerprint="sha256:inputs-v1",
        build_action_id="build-001",
        parent_world_state_id="ws-001",
        builder_version="index-builder/3.1",
    )
    verdict = _verify(unsealed)
    assert verdict.ok is False
    assert verdict.failure is ReceiptFailure.SEAL_BROKEN


# --- the failure binding cannot close ---------------------------------------


def test_an_untracked_builder_is_refused_rather_than_detected() -> None:
    """Signing an incomplete record makes it tamper-evident, not correct.

    Nothing here detects that a builder omitted an input class -- the receipt is
    internally consistent and simply silent. What can be done is decline to
    vouch for it, which is a different and weaker guarantee, and is named as one.
    """
    receipt = _receipt(consumption_automatically_captured=False)
    verdict = _verify(receipt)
    assert verdict.ok is False
    assert verdict.failure is ReceiptFailure.UNTRACKED_BUILDER


def test_an_untracked_builder_may_be_allowed_only_by_explicit_opt_out() -> None:
    """The permissive path exists, and it has to be asked for by name."""
    receipt = _receipt(consumption_automatically_captured=False)
    assert _verify(receipt, require_tracked_builder=False).ok is True


# --- the permissive path must be a downgrade, not a bypass -------------------
#
# This is where a bypass would grow. Someone sets require_tracked_builder=False
# to unblock a pipeline, and from then on an unverifiable artifact carries the
# same `ok` as a verified one. These tests make that impossible to do quietly.


def test_a_tracked_build_reaches_high_integrity() -> None:
    verdict = _verify(_receipt())
    assert verdict.level is VerificationLevel.HIGH_INTEGRITY
    assert verdict.promotable_to_trusted is True


def test_the_permissive_path_downgrades_rather_than_passes() -> None:
    """ok is True and trusted promotion is still refused. Both must be true."""
    verdict = _verify(_receipt(consumption_automatically_captured=False),
                      require_tracked_builder=False)
    assert verdict.ok is True
    assert verdict.level is VerificationLevel.DEGRADED_UNTRACKED
    assert verdict.promotable_to_trusted is False


@pytest.mark.parametrize("require_tracked", [True, False])
def test_no_argument_combination_promotes_an_untracked_build(require_tracked: bool) -> None:
    """The invariant: UNTRACKED output cannot become HIGH_INTEGRITY.

    Parametrised over the only argument that could plausibly override it. If a
    future flag is added that does, this test is where it shows up.
    """
    verdict = _verify(
        _receipt(consumption_automatically_captured=False),
        require_tracked_builder=require_tracked,
    )
    assert verdict.level is not VerificationLevel.HIGH_INTEGRITY
    assert verdict.promotable_to_trusted is False


def test_the_tracked_flag_cannot_be_restored_by_editing_the_receipt() -> None:
    """A migration or deserialisation that flips the flag breaks the seal.

    The flag is inside the sealed body, so 'it came back as tracked=true after a
    schema migration' is not a reachable state -- it is a broken seal.
    """
    untracked = _receipt(consumption_automatically_captured=False)
    forged = dataclasses.replace(untracked, consumption_automatically_captured=True)
    verdict = _verify(forged)
    assert verdict.ok is False
    assert verdict.failure is ReceiptFailure.SEAL_BROKEN
    assert verdict.promotable_to_trusted is False


def test_a_verdict_record_carries_the_level_downstream() -> None:
    """Downstream must be able to tell tracked from untracked without guessing."""
    record = _verify(
        _receipt(consumption_automatically_captured=False), require_tracked_builder=False
    ).as_record()
    assert record["level"] == "degraded_untracked"
    assert record["promotable_to_trusted"] is False
