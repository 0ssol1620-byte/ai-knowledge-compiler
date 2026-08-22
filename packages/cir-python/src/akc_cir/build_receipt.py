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
