"""A sealed record of what one build actually consumed, bound to what it produced.

The build-record mutation sweep found three ways a stale artifact reached
promotion (`research/experiments/H1-B-REAL-REVISION-01/BUILD_RECORD_TRUST_BOUNDARY_2026-08-19.md`):
a receipt reused from the prior revision, a receipt from another build attached
to this artifact, and a builder that never recorded a class of input at all. The
first two are receipt-identity failures and are what this module closes. The
third is not, and this module does not pretend to close it -- see `TrackedBuilder`
below.

The binding is the whole point. A receipt names the artifact bytes it describes,
the inputs it consumed, the build action that produced it, the parent world state
it was built against and the builder version that ran. Sealing hashes all of them
together, so a receipt cannot be lifted onto a different artifact, a different
revision or a different build without the seal failing -- there is no field to
edit that is not covered.

One asymmetry is load-bearing and is enforced rather than documented:

    the EXPECTED side may be read from a sealed receipt
    the NOW side must be recomputed from live source

The sweep measured what happens when both sides come from stored state: they
agree, agreement is what the verifier reads as currency, and the staleness
cancels. `verify_carry_forward` therefore takes the live fingerprint as a
separate argument and has no way to default it from the receipt.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum

__all__ = [
    "BuildReceipt",
    "CarryForwardVerdict",
    "ReceiptFailure",
    "VerificationLevel",
    "seal_receipt",
    "verify_carry_forward",
]


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
class BuildReceipt:
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
    seal: str = field(default="")

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


def seal_receipt(receipt: BuildReceipt) -> BuildReceipt:
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
    receipt: BuildReceipt,
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
