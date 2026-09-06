"""The receipt a build seals — and room for what it never declared.

A build receipt is a promise about consumption completeness (§29.2): every
input that shaped the output is written down before the seal goes on. The
catch is that a receipt traditionally lists only *declared* inputs, and a
builder is a program like any other. It reads files nobody listed, consults
environment variables, imports modules mid-build, and sometimes asks the
clock or shakes the dice. A seal over an incomplete list certifies the wrong
thing.

So the schema carries two additive sections beside the declared inputs:

``hidden_inputs``
    Files the builder opened for reading (path + sha256), the names of
    environment variables it consulted (names only — values are secrets and
    are never captured), and modules imported while the build ran.
``non_determinism``
    Which nondeterministic sources were consulted, and how often.

Both default to empty. A receipt written without tracking validates, seals,
verifies, and serializes exactly as before — the sections ride along empty,
and consumers that only read declared inputs see nothing new. What fills
them in is :class:`akc_cir.tracked_build_context.TrackedBuildContext`, which
stands next to the builder and writes down what actually happened.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field as dataclass_field
from enum import StrEnum

from pydantic import Field

from .base import (
    ContractModel,
    NonEmptyStr,
    Sha256,
    StableId,
    TimestampedModel,
    canonical_json,
    sha256_digest,
)

__all__ = [
    "BuildReceipt",
    "DeclaredInput",
    "HiddenInputs",
    "NonDeterminism",
    "NonDeterminismSource",
    "ObservedFile",
    "CarryForwardReceipt",
    "CarryForwardVerdict",
    "ReceiptFailure",
    "VerificationLevel",
    "seal_receipt",
    "verify_carry_forward",
]


class DeclaredInput(ContractModel):
    """An input the builder owned up to: a path and the hash of its bytes."""

    path: NonEmptyStr
    sha256: Sha256


class ObservedFile(ContractModel):
    """A file the builder opened for reading but did not declare.

    ``sha256`` is ``None`` only when the bytes could not be hashed at capture
    time (the file vanished or refused reads between open and hash). The
    observation is kept either way — an unprovable read is still a read, and
    pretending otherwise would repeat the omission this section exists to
    close.
    """

    path: NonEmptyStr
    sha256: Sha256 | None = None


class HiddenInputs(ContractModel):
    """What the builder consumed without declaring.

    ``env_keys`` holds names only. Values are never captured — receipts get
    archived, copied, and attached to tickets, and an environment variable is
    where credentials live precisely because programs read them.
    """

    files: tuple[ObservedFile, ...] = ()
    env_keys: tuple[NonEmptyStr, ...] = ()
    imported_modules: tuple[str, ...] = ()


class NonDeterminismSource(ContractModel):
    """One nondeterministic source and how many times it was consulted."""

    source: NonEmptyStr
    calls: int = Field(ge=1)


class NonDeterminism(ContractModel):
    """The nondeterminism a build consulted, if any.

    Empty means the builder touched neither clock nor dice — not that its
    output is proven reproducible, which would require rerunning it.
    """

    sources: tuple[NonDeterminismSource, ...] = ()

    @property
    def flagged(self) -> bool:
        """True when at least one nondeterministic source was consulted."""
        return bool(self.sources)


class BuildReceipt(TimestampedModel):
    """Sealed statement of what a build consumed and produced.

    ``hidden_inputs`` and ``non_determinism`` are additive: older receipts
    that predate tracking load unchanged with both sections empty, and the
    seal covers whatever the sections hold at sealing time.
    """

    builder_id: StableId
    declared_inputs: tuple[DeclaredInput, ...] = ()
    output_sha256: Sha256 | None = None
    hidden_inputs: HiddenInputs = HiddenInputs()
    non_determinism: NonDeterminism = NonDeterminism()
    sealed: bool = False
    receipt_sha256: Sha256 | None = None

    def _seal_payload(self) -> str:
        """Canonical JSON over everything the seal attests to."""
        payload = self.model_dump(mode="json", by_alias=True, exclude_none=True)
        # The seal is not a fact about itself; attest to the content only.
        payload.pop("receiptSha256", None)
        payload.pop("sealed", None)
        return canonical_json(payload)

    def seal(self) -> BuildReceipt:
        """Return a sealed copy whose digest covers all recorded inputs."""
        if self.sealed:
            return self
        digest = sha256_digest(self._seal_payload())
        return self.model_copy(update={"sealed": True, "receipt_sha256": digest})

    def verify_seal(self) -> bool:
        """True when the content still matches the digest the seal recorded."""
        if not self.sealed or self.receipt_sha256 is None:
            return False
        return sha256_digest(self._seal_payload()) == self.receipt_sha256


# Carry-forward verification contract: separate from the tracked Pydantic BuildReceipt.
class VerificationLevel(StrEnum):
    """How much this verdict is worth. Passing is not one value but two.

    The permissive path for an untracked builder is the obvious place for a
    bypass to grow: someone sets `require_tracked_builder=False` to unblock a
    pipeline, and from then on an unverifiable artifact carries the same `ok`
    as a verified one. So permissive mode does not mean "verification passed";
    it means **verification was downgraded**, and the verdict says which.

    `HIGH_INTEGRITY` is reachable only from a tracked builder. There is no flag,
    override or argument combination that produces it otherwise -- see
    `test_no_argument_combination_promotes_an_untracked_build`.
    """

    HIGH_INTEGRITY = "high_integrity"
    #: Checks passed, but consumption was declared rather than captured, so the
    #: input set may be incomplete. Not eligible for trusted promotion.
    DEGRADED_UNTRACKED = "degraded_untracked"
    NOT_VERIFIED = "not_verified"


class ReceiptFailure(StrEnum):
    """Why a receipt could not be used. The value is what a refusal records."""

    NONE = "none"
    SEAL_BROKEN = "seal_broken"
    WRONG_ARTIFACT = "receipt_describes_a_different_artifact"
    WRONG_BYTES = "receipt_describes_different_artifact_bytes"
    WRONG_WORLD_STATE = "receipt_was_built_against_a_different_parent_world_state"
    INPUTS_MOVED = "declared_inputs_have_changed_since_the_build"
    UNTRACKED_BUILDER = "builder_did_not_capture_consumption_automatically"


@dataclass(frozen=True, slots=True)
class CarryForwardReceipt:
    """What one build consumed and produced, sealed together.

    `input_fingerprint` is the digest of the inputs *as actually read*, produced
    by `artifact_input_fingerprint`. `build_action_id` identifies the single
    execution; `parent_world_state_id` the state it was built against. Both are
    inside the seal so a receipt from an earlier revision cannot be presented for
    a later one -- its parent state will not match.
    """

    artifact_id: str
    artifact_sha256: str
    input_fingerprint: str
    build_action_id: str
    parent_world_state_id: str
    builder_version: str
    #: False when the builder did not capture its own consumption through a
    #: tracked access path. Such a receipt may be well-formed and still be an
    #: incomplete account, which no amount of sealing detects.
    consumption_automatically_captured: bool = True
    seal: str = dataclass_field(default="")

    def body(self) -> dict[str, object]:
        return {
            "artifact_id": self.artifact_id,
            "artifact_sha256": self.artifact_sha256,
            "input_fingerprint": self.input_fingerprint,
            "build_action_id": self.build_action_id,
            "parent_world_state_id": self.parent_world_state_id,
            "builder_version": self.builder_version,
            "consumption_automatically_captured": self.consumption_automatically_captured,
        }

    def expected_seal(self) -> str:
        body = json.dumps(self.body(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()

    def seal_intact(self) -> bool:
        return bool(self.seal) and self.seal == self.expected_seal()


def seal_receipt(receipt: CarryForwardReceipt) -> CarryForwardReceipt:
    """Return the receipt with its seal computed over every field."""
    from dataclasses import replace

    return replace(receipt, seal=receipt.expected_seal())


@dataclass(frozen=True, slots=True)
class CarryForwardVerdict:
    ok: bool
    failure: ReceiptFailure = ReceiptFailure.NONE
    detail: str = ""
    level: VerificationLevel = VerificationLevel.NOT_VERIFIED

    @property
    def promotable_to_trusted(self) -> bool:
        """The only predicate a trusted world-state promotion may consult.

        `ok` alone is not it. An untracked build can be `ok` and must still never
        reach a trusted state, so the two questions are kept separate rather
        than collapsed into one boolean that later grows an exception.
        """
        return self.ok and self.level is VerificationLevel.HIGH_INTEGRITY

    def as_record(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "failure": self.failure.value,
            "detail": self.detail,
            "level": self.level.value,
            "promotable_to_trusted": self.promotable_to_trusted,
        }


def verify_carry_forward(
    *,
    receipt: CarryForwardReceipt,
    artifact_id: str,
    artifact_sha256_now: str,
    live_input_fingerprint: str,
    current_world_state_id: str,
    require_tracked_builder: bool = True,
) -> CarryForwardVerdict:
    """May this artifact be carried forward as CURRENT?

    `live_input_fingerprint` must be recomputed from the live source by the
    caller. It is a required argument with no default precisely so that it cannot
    quietly become `receipt.input_fingerprint`, which would compare the receipt
    with itself and pass every stale artifact.

    `current_world_state_id` is the state being built now. A receipt whose parent
    is not that state describes a build against different ground, and is refused
    even when everything else about it is intact -- that is what makes reusing
    the prior revision's receipt fail rather than silently agree.
    """
    if not receipt.seal_intact():
        return CarryForwardVerdict(
            False, ReceiptFailure.SEAL_BROKEN, "the receipt's seal does not cover its contents"
        )
    if receipt.artifact_id != artifact_id:
        return CarryForwardVerdict(
            False,
            ReceiptFailure.WRONG_ARTIFACT,
            f"receipt is for {receipt.artifact_id}, not {artifact_id}",
        )
    if receipt.artifact_sha256 != artifact_sha256_now:
        return CarryForwardVerdict(
            False,
            ReceiptFailure.WRONG_BYTES,
            "the artifact on disk is not the artifact this receipt describes",
        )
    if receipt.parent_world_state_id != current_world_state_id:
        return CarryForwardVerdict(
            False,
            ReceiptFailure.WRONG_WORLD_STATE,
            (
                f"receipt was built against {receipt.parent_world_state_id}; "
                f"this build is against {current_world_state_id}"
            ),
        )
    if require_tracked_builder and not receipt.consumption_automatically_captured:
        return CarryForwardVerdict(
            False,
            ReceiptFailure.UNTRACKED_BUILDER,
            (
                "consumption was declared rather than captured, so the receipt "
                "may be an incomplete account of what was read. Sealing an "
                "incomplete record makes it tamper-evident, not correct"
            ),
            VerificationLevel.NOT_VERIFIED,
        )
    if receipt.input_fingerprint != live_input_fingerprint:
        return CarryForwardVerdict(
            False,
            ReceiptFailure.INPUTS_MOVED,
            "the inputs this artifact was built from have changed since it was built",
        )
    # The level is read off the receipt, not off the caller's arguments. A
    # permissive call cannot raise it -- passing `require_tracked_builder=False`
    # buys a DEGRADED verdict, never a HIGH_INTEGRITY one.
    level = (
        VerificationLevel.HIGH_INTEGRITY
        if receipt.consumption_automatically_captured
        else VerificationLevel.DEGRADED_UNTRACKED
    )
    return CarryForwardVerdict(True, ReceiptFailure.NONE, "", level)
