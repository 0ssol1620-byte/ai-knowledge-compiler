#!/usr/bin/env python3
"""Segments, linked so that a gap cannot be mistaken for a measurement.

A census that spans several rate windows is several runs, and several runs are
several chances for one of them to be quietly dropped, replayed, reordered, or
paired with the wrong roster. SFIR7's most expensive failure was of this family:
twenty of fifty roots were recorded as measured when the instrument had merely
stopped. A stop that looks like a result is worse than a stop.

**So each segment names its predecessor by digest, and the chain refuses any link
that does not fit.** Wrong study, wrong protocol, wrong roster, wrong selection,
a skipped index, a predecessor that does not match, a counter that went
backwards. None of these is recoverable by inspection afterwards -- the point of
refusing at append time is that the receipt never contains the bad link at all.

**The three bindings are checked separately.** A segment carries the protocol
digest, the roster digest and the selection digest, and all three must match the
chain's. They are separate questions: the same roster can be produced by two
different selection rules, and the same selection rule under a different protocol
is a different study. Collapsing them into one "study digest" would make a
mismatch unattributable.

**Counters accumulate and never decrease.** They are running totals across the
census, so a segment reporting fewer logical requests than its predecessor has
either lost work or is a replay of an earlier one. Either way it is not the next
segment.

**Nothing here decides anything scientific.** The chain knows how much was spent
and where the traversal stood. It does not know what was found, and a chain that
closed early because the yield looked poor would be selecting its own evidence.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

import sfir9_transport as transport

SCHEMA = "tavonel.sfir9.checkpoint_chain.v1"

#: The predecessor of the first segment. A literal so that "no predecessor" is a
#: value the digest covers rather than an absence it cannot see.
GENESIS = "sha256:" + "0" * 64

#: Dispositions a segment may close with. A disposition outside this set is a
#: state nobody declared, and a chain that accepted one would be recording an
#: outcome the protocol never defined.
OPEN = "SEGMENT_OPEN"
RATE_WINDOW = transport.SEGMENT_CLOSE_RATE_WINDOW
COMPLETE = "CENSUS_COMPLETE"
STORAGE = "WORKING_STORAGE_BUDGET_EXHAUSTED"
DISPOSITIONS = frozenset({OPEN, RATE_WINDOW, COMPLETE, STORAGE})

#: Counters that accumulate across the census and may never decrease.
MONOTONIC_COUNTERS = (
    "logical_request_count",
    "network_hop_count",
    "provider_charged_count",
)

WRONG_STUDY = "REFUSED_SEGMENT_FROM_ANOTHER_STUDY"
WRONG_ROSTER = "REFUSED_SEGMENT_FROM_ANOTHER_ROSTER"
WRONG_SELECTION = "REFUSED_SEGMENT_FROM_ANOTHER_SELECTION"
WRONG_PROTOCOL = "REFUSED_SEGMENT_FROM_ANOTHER_PROTOCOL"
BROKEN_LINK = "REFUSED_BROKEN_SEGMENT_LINK"
COUNTER_REGRESSED = "REFUSED_COUNTER_WENT_BACKWARDS"
UNKNOWN_DISPOSITION = "REFUSED_UNDECLARED_DISPOSITION"
CHAIN_CLOSED = "REFUSED_APPEND_TO_A_CLOSED_CHAIN"


class ChainRefused(RuntimeError):
    """A refusal carrying the code that names it."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


def _digest(payload: Any) -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
    )


@dataclass(frozen=True, slots=True)
class Segment:
    """One rate window's worth of work, and where it sits in the chain."""

    study_id: str
    segment_index: int
    handoff: transport.TransportHandoff
    previous_segment_digest: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "study_id": self.study_id,
            "segment_index": self.segment_index,
            "previous_segment_digest": self.previous_segment_digest,
            "handoff": self.handoff.as_dict(),
        }

    def digest(self) -> str:
        return _digest(self.as_dict())

    def counter(self, name: str) -> int:
        return int(getattr(self.handoff, name))


class SegmentChain:
    """Append-only, and it refuses rather than repairs.

    A chain that quietly fixed a bad link would produce a receipt that looks
    continuous over work that was not. Every refusal below leaves the chain
    exactly as it was, so the last good state is always the recorded one.
    """

    def __init__(
        self,
        *,
        study_id: str,
        protocol_digest: str,
        roster_digest: str,
        selection_digest: str,
    ) -> None:
        self.study_id = study_id
        self.protocol_digest = protocol_digest
        self.roster_digest = roster_digest
        self.selection_digest = selection_digest
        self.segments: list[Segment] = []

    # -- state ------------------------------------------------------------

    def head(self) -> str:
        return self.segments[-1].digest() if self.segments else GENESIS

    def next_index(self) -> int:
        return len(self.segments)

    def is_closed(self) -> bool:
        return bool(self.segments) and self.segments[-1].handoff.disposition == COMPLETE

    # -- appending --------------------------------------------------------

    def append(self, segment: Segment) -> Segment:
        """Every check that must pass before a segment becomes part of the record."""
        if self.is_closed():
            raise ChainRefused(
                CHAIN_CLOSED,
                f"segment {segment.segment_index} was offered to a chain already "
                f"closed with {COMPLETE}. A census that continues after it finished "
                "is two censuses sharing a receipt.",
            )
        if segment.study_id != self.study_id:
            raise ChainRefused(
                WRONG_STUDY,
                f"segment declares study {segment.study_id!r} and this chain is "
                f"{self.study_id!r}.",
            )

        handoff = segment.handoff
        if handoff.protocol_digest != self.protocol_digest:
            raise ChainRefused(
                WRONG_PROTOCOL,
                "the segment was produced under a different protocol digest. The "
                "same selection rule under a different protocol is a different "
                "study, whatever the roster says.",
            )
        if handoff.roster_digest != self.roster_digest:
            raise ChainRefused(
                WRONG_ROSTER,
                "the segment traversed a different roster. Resuming a census from "
                "another roster's checkpoint would report one study's spend against "
                "another study's repositories.",
            )
        if handoff.selection_digest != self.selection_digest:
            raise ChainRefused(
                WRONG_SELECTION,
                "the segment was produced under a different selection digest. One "
                "roster can be reached by more than one selection rule, so a "
                "matching roster is not a matching selection.",
            )

        if handoff.disposition not in DISPOSITIONS:
            raise ChainRefused(
                UNKNOWN_DISPOSITION,
                f"{handoff.disposition!r} is not a declared disposition. Recording "
                "an outcome the protocol never defined puts a state in the receipt "
                f"that nothing can interpret. Declared: {sorted(DISPOSITIONS)}.",
            )

        if segment.segment_index != self.next_index():
            raise ChainRefused(
                BROKEN_LINK,
                f"segment index {segment.segment_index} does not follow "
                f"{self.next_index() - 1}. A skipped index is a segment that was "
                "run and lost, and a repeated one is a replay.",
            )
        if segment.previous_segment_digest != self.head():
            raise ChainRefused(
                BROKEN_LINK,
                "the segment names a predecessor this chain does not end with. Two "
                "segments claiming the same predecessor are a fork, and a fork has "
                "no single answer.",
            )

        if self.segments:
            previous = self.segments[-1]
            for name in MONOTONIC_COUNTERS:
                if segment.counter(name) < previous.counter(name):
                    raise ChainRefused(
                        COUNTER_REGRESSED,
                        f"{name} fell from {previous.counter(name)} to "
                        f"{segment.counter(name)}. These are running totals across "
                        "the census, so a fall means work was lost or this segment "
                        "is a replay of an earlier one.",
                    )

        self.segments.append(segment)
        return segment

    def open_next(self, handoff: transport.TransportHandoff) -> Segment:
        """Build the next segment against this chain's own head.

        Callers cannot supply the index or the predecessor, so the two fields
        most easily got wrong are not theirs to get wrong.
        """
        return Segment(
            study_id=self.study_id,
            segment_index=self.next_index(),
            handoff=handoff,
            previous_segment_digest=self.head(),
        )

    # -- resuming ---------------------------------------------------------

    def resume_input(self) -> dict[str, Any]:
        """Exactly what the next segment needs, and nothing it must not have."""
        if not self.segments:
            raise ChainRefused(
                BROKEN_LINK,
                "an empty chain has no state to resume from. The first segment "
                "starts from the roster, not from a checkpoint.",
            )
        last = self.segments[-1].handoff
        return {
            "schema": SCHEMA,
            "study_id": self.study_id,
            "segment_index": self.next_index(),
            "previous_segment_digest": self.head(),
            "protocol_digest": self.protocol_digest,
            "roster_digest": self.roster_digest,
            "selection_digest": self.selection_digest,
            "current_root_host_uuid": last.current_root_host_uuid,
            "canonical_address": last.canonical_address,
            "frontier_digest": last.frontier_digest,
            "visited_digest": last.visited_digest,
            "candidate_accumulator_digest": last.candidate_accumulator_digest,
            "logical_request_count": last.logical_request_count,
            "network_hop_count": last.network_hop_count,
            "provider_charged_count": last.provider_charged_count,
            "provider_remaining": last.provider_remaining,
            "provider_reset_epoch": last.provider_reset_epoch,
        }

    # -- receipt ----------------------------------------------------------

    def receipt(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "study_id": self.study_id,
            "protocol_digest": self.protocol_digest,
            "roster_digest": self.roster_digest,
            "selection_digest": self.selection_digest,
            "segment_count": len(self.segments),
            "chain_head": self.head(),
            "closed": self.is_closed(),
            "segments": [segment.as_dict() for segment in self.segments],
            "dispositions": [s.handoff.disposition for s in self.segments],
            "declared_dispositions": sorted(DISPOSITIONS),
            "monotonic_counters": list(MONOTONIC_COUNTERS),
            "why_the_predecessor_is_named_by_digest": (
                "a segment that only carried an index could be reordered or replaced "
                "without the receipt changing shape. SFIR7 recorded twenty of fifty "
                "roots as measured when the instrument had merely stopped, and a "
                "stop that looks like a result is worse than a stop."
            ),
        }


def verify_chain(receipt: dict[str, Any]) -> dict[str, Any]:
    """Re-derive the links from a receipt, independently of the builder.

    The chain refuses bad links at append time, which means a receipt this
    process produced is linked by construction. That is exactly why verification
    recomputes from the stored bytes instead: a receipt read back from disk was
    not necessarily written by the object that is checking it.
    """
    previous = GENESIS
    problems: list[str] = []
    for index, stored in enumerate(receipt.get("segments", [])):
        if stored.get("segment_index") != index:
            problems.append(f"segment at position {index} declares index "
                            f"{stored.get('segment_index')}")
        if stored.get("previous_segment_digest") != previous:
            problems.append(f"segment {index} does not name its predecessor")
        previous = _digest(stored)
    head_matches = previous == receipt.get("chain_head")
    if not head_matches:
        problems.append("the recorded chain head is not the digest of the last segment")
    return {
        "schema": SCHEMA,
        "segment_count": len(receipt.get("segments", [])),
        "recomputed_head": previous,
        "recorded_head": receipt.get("chain_head"),
        "head_matches": head_matches,
        "links_intact": not problems,
        "problems": problems,
    }
