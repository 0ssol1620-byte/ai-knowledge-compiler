#!/usr/bin/env python3
"""Segments: how a traversal crosses a rate window without waiting or lying.

SFIR7 had one lever when GitHub's budget ran out mid-census -- wait, up to a
frozen 180-second fail-safe, then stop. Four roots died against a reset that was
forty minutes away. Widening the fail-safe to cover a forty-minute wait would
have been changing an execution bound because a result was disappointing, which
is the one thing the protocol forbids.

The way out is not a longer wait. It is to stop *deliberately*, leave state that
the next window can prove it inherited, and resume from exactly there. The
segment closes with `SEGMENT_COMPLETE_RATE_WINDOW`, an explicit disposition that
is neither a completed traversal nor a failure.

**What makes a resumed run trustworthy is that it cannot be quietly reordered.**
Each segment names the digest of the one before it, so the chain is a line and
not a bag: drop a segment, swap two, edit a field, or start from a different
roster, and the next segment refuses to open. The refusals are the point. A
checkpoint that could be edited between windows would let a traversal be steered
by its own intermediate results, which is exactly the outcome-dependence the
frozen protocol exists to prevent.

**Resume happens mid-root, not merely between roots.** Checkpointing only at
root boundaries lets one large repository consume an entire window and then be
restarted from nothing -- the same truncation SFIR7 suffered, wearing a different
name. And resume must not change traversal order: continuous and segmented
execution over the same fixture must produce identical candidates, identical
ordering, identical dispositions, identical request plans.

Development instrument. SFIR8 produces no capacity claim.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROTOCOL_ID = "SOURCE_FACT_IR_INSTRUMENT_CALIBRATION_V8"
SCHEMA = "tavonel.sfir8.segment_checkpoint.v1"

#: The disposition a segment closes with when the provider's window, not the
#: traversal, ended the work. Distinct from every completion state so it can
#: never be counted as one.
RATE_WINDOW_CLOSE = "SEGMENT_COMPLETE_RATE_WINDOW"

#: Opening digest of a chain. The first segment inherits nothing, and says so
#: with a value that cannot be confused with a real digest.
GENESIS = "sha256:" + "0" * 64


class CheckpointRefused(RuntimeError):
    """The chain does not link, so the next segment does not open."""


def digest(payload: Any) -> str:
    """One canonical digest function, so two callers cannot disagree."""
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
    )


def frontier_digest(entries: Any) -> str:
    """Digest of the pending frontier, in enqueue order.

    Order participates. Two frontiers holding the same entries in a different
    order would traverse differently, so they must not digest alike.
    """
    return digest([entry.as_dict() for entry in entries])


def visited_digest(rows: Any) -> str:
    """Digest of the visited set, sorted -- membership matters, order does not."""
    return digest(sorted([list(row) for row in rows]))


@dataclass(frozen=True, slots=True)
class Checkpoint:
    """Everything the next window needs, and everything it must prove it has."""

    study_id: str
    segment_index: int
    roster_digest: str
    root_index: int
    current_root_id: str | None
    current_canonical_address: str | None
    current_repository_numeric_id: str | None
    frontier_digest: str
    visited_digest: str
    candidate_digest: str
    completed_roots_digest: str
    logical_request_count: int
    network_hop_count: int
    provider_charged_count: int
    provider_remaining: int | None
    provider_reset_epoch: int | None
    previous_segment_digest: str
    next_action: str
    disposition: str
    protocol_id: str = PROTOCOL_ID
    schema: str = SCHEMA

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "protocol_id": self.protocol_id,
            "study_id": self.study_id,
            "segment_index": self.segment_index,
            "roster_digest": self.roster_digest,
            "root_index": self.root_index,
            "current_root_id": self.current_root_id,
            "current_canonical_address": self.current_canonical_address,
            "current_repository_numeric_id": self.current_repository_numeric_id,
            "frontier_digest": self.frontier_digest,
            "visited_digest": self.visited_digest,
            "candidate_digest": self.candidate_digest,
            "completed_roots_digest": self.completed_roots_digest,
            "logical_request_count": self.logical_request_count,
            "network_hop_count": self.network_hop_count,
            "provider_charged_count": self.provider_charged_count,
            "provider_remaining": self.provider_remaining,
            "provider_reset_epoch": self.provider_reset_epoch,
            "previous_segment_digest": self.previous_segment_digest,
            "next_action": self.next_action,
            "disposition": self.disposition,
        }

    def digest(self) -> str:
        """This segment's identity. The next one must name it."""
        return digest(self.as_dict())

    def write(self, path: Path) -> Path:
        body = self.as_dict()
        body["segment_digest"] = self.digest()
        path.write_text(
            json.dumps(body, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8"
        )
        return path


def read(path: Path) -> tuple[Checkpoint, str]:
    """Load a checkpoint and verify it digests to what it claims.

    A checkpoint carries its own digest, so any edit between windows is caught
    here rather than propagating into a resumed traversal that looks sound.
    """
    body = json.loads(Path(path).read_text(encoding="utf-8"))
    claimed = body.pop("segment_digest", None)
    if claimed is None:
        raise CheckpointRefused(f"{path}: no segment_digest, so nothing attests to it")
    checkpoint = Checkpoint(
        **{k: v for k, v in body.items() if k not in {"schema", "protocol_id"}},
        schema=body.get("schema", SCHEMA),
        protocol_id=body.get("protocol_id", PROTOCOL_ID),
    )
    recomputed = checkpoint.digest()
    if recomputed != claimed:
        raise CheckpointRefused(
            f"{path}: the checkpoint digests to {recomputed} but claims {claimed}. "
            "It has been edited since it was written, and a traversal resumed from "
            "an edited checkpoint is steered by whoever edited it."
        )
    return checkpoint, claimed


@dataclass
class SegmentChain:
    """The ordered line of segments, verified as it grows."""

    study_id: str
    roster_digest: str
    segments: list[Checkpoint] = field(default_factory=list)

    @property
    def head(self) -> str:
        return self.segments[-1].digest() if self.segments else GENESIS

    def append(self, checkpoint: Checkpoint) -> Checkpoint:
        """Admit the next segment, or refuse and say which invariant broke."""
        if checkpoint.study_id != self.study_id:
            raise CheckpointRefused(
                f"segment belongs to study {checkpoint.study_id!r} and this chain is "
                f"{self.study_id!r}. Segments from two studies do not compose."
            )
        if checkpoint.roster_digest != self.roster_digest:
            raise CheckpointRefused(
                "segment was produced against a different roster. Resuming across a "
                "roster change would traverse a population nobody selected."
            )
        expected_index = len(self.segments)
        if checkpoint.segment_index != expected_index:
            raise CheckpointRefused(
                f"segment claims index {checkpoint.segment_index} where the chain "
                f"expects {expected_index}. A gap means a segment was omitted; a "
                "repeat means two were reordered."
            )
        if checkpoint.previous_segment_digest != self.head:
            raise CheckpointRefused(
                f"segment names predecessor {checkpoint.previous_segment_digest} but "
                f"the chain head is {self.head}. The line is broken."
            )
        if self.segments:
            self._require_monotonic(self.segments[-1], checkpoint)
        self.segments.append(checkpoint)
        return checkpoint

    @staticmethod
    def _require_monotonic(previous: Checkpoint, current: Checkpoint) -> None:
        """Work only ever accumulates. A counter that fell means state was lost."""
        for name in (
            "root_index",
            "logical_request_count",
            "network_hop_count",
            "provider_charged_count",
        ):
            before, after = getattr(previous, name), getattr(current, name)
            if after < before:
                raise CheckpointRefused(
                    f"{name} went from {before} to {after} across a segment boundary. "
                    "Work does not un-happen; a counter that fell means the resumed "
                    "segment did not inherit the state it claims to have."
                )

    def receipt(self) -> dict[str, Any]:
        """What the run receipt records about how the work was cut up."""
        return {
            "protocol_id": PROTOCOL_ID,
            "study_id": self.study_id,
            "roster_digest": self.roster_digest,
            "segment_count": len(self.segments),
            "segment_chain_head": self.head,
            "segment_digests": [segment.digest() for segment in self.segments],
            "dispositions": [segment.disposition for segment in self.segments],
            "totals": {
                "logical_request_count": (
                    self.segments[-1].logical_request_count if self.segments else 0
                ),
                "network_hop_count": (
                    self.segments[-1].network_hop_count if self.segments else 0
                ),
                "provider_charged_count": (
                    self.segments[-1].provider_charged_count if self.segments else 0
                ),
            },
            "why_the_chain_head_is_in_the_run_receipt": (
                "the head is the only value that depends on every segment, in order. "
                "A receipt that named the segments without it would not detect a "
                "reordering, and a receipt that named none of them would not detect "
                "a segment being dropped."
            ),
            "waiting_was_not_the_alternative": (
                "the frozen 60s-per-retry / 180s-total fail-safe is unchanged. A "
                "window that resets further away than the fail-safe closes the "
                f"segment as {RATE_WINDOW_CLOSE} rather than widening a bound "
                "because a result was inconvenient."
            ),
        }
