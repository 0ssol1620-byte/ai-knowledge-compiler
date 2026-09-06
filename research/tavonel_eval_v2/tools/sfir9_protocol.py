#!/usr/bin/env python3
"""The SFIR9 protocol: everything fixed before a single repository is chosen.

This module is the one place SFIR9's declared quantities live. Nothing here is
derived from an observation, and the controls prove that by checking each term's
declared origin rather than trusting the comment next to it.

**Why a separate module rather than constants scattered where they are used.**
A frozen protocol has to be a thing that can be hashed. Values spread across
eight modules can be changed one at a time, each change looking local and
reasonable, and no digest anywhere moves in a way a reader would notice. One
module, one digest, and the execution closure binds it.

**The protocol is frozen before the roster is opened, not after.** That ordering
is the whole methodological point and it is enforced rather than remembered:
`freeze()` records a state, and the roster generator refuses to run against a
protocol whose freeze state is not `PROTOCOL_FROZEN`. Seeing the roster and then
adjusting the salt, the partition, N or the ranking is the failure this prevents,
and it is not a failure anybody commits deliberately -- it happens when a first
attempt looks disappointing and a knob is within reach.

**Capacity criterion, inherited unchanged.** `C_f >= 750`, `Q_f = min(1000,
floor(0.8 * C_f))`, `Q_f >= 600`. SFIR7 applied it and failed it. SFIR9 applies
the same criterion to a fresh population, and a FAIL is a result rather than a
reason to revisit the threshold.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

PROTOCOL_ID = "SOURCE_FACT_IR_FRESH_HELDOUT_V9"
SCHEMA = "tavonel.sfir9.protocol.v1"

#: Study lineage, stated so no receipt has to be read to know what SFIR9 is.
STUDY_KIND = "FRESH_HELDOUT_CONFIRMATORY"
PREDECESSOR_DEVELOPMENT_STUDIES = ("SFIR7", "SFIR8")

#: The capacity criterion, unchanged from the predecessor protocol.
MINIMUM_C = 750
MAXIMUM_Q = 1000
QUOTA_FRACTION_NUMERATOR = 8
QUOTA_FRACTION_DENOMINATOR = 10
MINIMUM_Q = 600

#: Execution envelope. Every value is a property of what the study is permitted
#: to spend, and none is a property of any repository.
PERMITTED_RATE_WINDOWS = 6
USABLE_CHARGE_PER_WINDOW = 4500
PER_ROOT_CHARGE_ALLOWANCE = 540

#: Rate-window semantics, inherited unchanged from SFIR7. Widening either
#: because a result disappointed is the one thing the protocol forbids.
RETRY_WAIT_SECONDS = 60
TOTAL_WAIT_SECONDS = 180

#: Selection. The salt is part of the freeze; only its digest is published.
SELECTION_SALT = "tavonel-sfir9-partition-salt-2026-08-29"
PARTITION_COUNT = 64
PARTITION_INDEX = 0

#: Working storage the frontier may occupy, in bytes. An execution-environment
#: budget; the per-entry ceiling is derived from it and from the serialization
#: format's own maxima, never from an observed repository.
DECLARED_WORKING_STORAGE_BYTES = 2 * 1024 * 1024 * 1024

#: What counts as a candidate. Inherited from the predecessor pool definition so
#: that the population being counted is the same kind of thing SFIR7 counted.
CANDIDATE_EXTENSIONS = (".py", ".md", ".rst", ".txt")

#: Freeze states. There is no state between these two, deliberately: a protocol
#: is either fixed or it is not, and "mostly fixed" is how a knob gets turned.
DRAFT = "PROTOCOL_DRAFT"
FROZEN = "PROTOCOL_FROZEN"


class ProtocolRefused(RuntimeError):
    """The protocol cannot be used the way it is being used."""


@dataclass(frozen=True, slots=True)
class Protocol:
    """The frozen quantities, as a value that can be hashed and compared."""

    freeze_state: str = DRAFT

    def terms(self) -> dict[str, Any]:
        """Every declared quantity. Adding one here changes the digest."""
        return {
            "protocol_id": PROTOCOL_ID,
            "schema": SCHEMA,
            "study_kind": STUDY_KIND,
            "predecessor_development_studies": list(PREDECESSOR_DEVELOPMENT_STUDIES),
            "capacity_criterion": {
                "minimum_c": MINIMUM_C,
                "maximum_q": MAXIMUM_Q,
                "quota_fraction": [
                    QUOTA_FRACTION_NUMERATOR,
                    QUOTA_FRACTION_DENOMINATOR,
                ],
                "minimum_q": MINIMUM_Q,
                "inherited_unchanged_from": "SFIR7",
            },
            "execution_envelope": {
                "permitted_rate_windows": PERMITTED_RATE_WINDOWS,
                "usable_charge_per_window": USABLE_CHARGE_PER_WINDOW,
                "per_root_charge_allowance": PER_ROOT_CHARGE_ALLOWANCE,
                "denominated_in": "provider_charge",
            },
            "rate_window_semantics": {
                "retry_wait_seconds": RETRY_WAIT_SECONDS,
                "total_wait_seconds": TOTAL_WAIT_SECONDS,
                "inherited_unchanged_from": "SFIR7",
                "on_a_reset_beyond_the_fail_safe": "SEGMENT_COMPLETE_RATE_WINDOW",
            },
            "selection": {
                "salt_digest": salt_digest(),
                "partition_count": PARTITION_COUNT,
                "partition_index": PARTITION_INDEX,
                "partition_keyed_on": "host_uuid",
                "ordering": ["source_rank descending", "record_id ascending"],
            },
            "traversal": {
                "declared_working_storage_bytes": DECLARED_WORKING_STORAGE_BYTES,
                "candidate_extensions": list(CANDIDATE_EXTENSIONS),
                "population_calibrated_bounds": [],
                "why_no_population_calibrated_bounds": (
                    "SFIR4 bounded the frontier at 158 tree objects and 256 queue "
                    "entries, both calibrated on twenty smaller hand-picked "
                    "repositories, and SFIR7 recorded twenty of fifty externally "
                    "selected roots as measured when the instrument had merely "
                    "stopped. A bound derived from repositories cannot distinguish "
                    "'large' from 'unmeasurable'."
                ),
            },
        }

    def digest(self) -> str:
        """Identity of the protocol. The freeze state is deliberately excluded.

        Freezing must not change what the protocol *says*, or a frozen protocol
        could never be compared with the draft it was frozen from -- and the
        comparison is exactly what proves nothing moved at the moment of freeze.
        """
        return (
            "sha256:"
            + hashlib.sha256(
                json.dumps(self.terms(), sort_keys=True, separators=(",", ":")).encode(
                    "utf-8"
                )
            ).hexdigest()
        )

    def freeze(self) -> Protocol:
        return Protocol(freeze_state=FROZEN)

    def is_frozen(self) -> bool:
        return self.freeze_state == FROZEN

    def require_frozen(self, action: str) -> None:
        """Refuse an action that must not happen against a draft protocol."""
        if not self.is_frozen():
            raise ProtocolRefused(
                f"{action} requires a frozen protocol and this one is "
                f"{self.freeze_state}. Generating a roster against a draft leaves "
                "the salt, the partition, N and the ranking adjustable after the "
                "roster has been seen, which is the one thing this protocol exists "
                "to prevent."
            )

    def as_dict(self) -> dict[str, Any]:
        return {
            **self.terms(),
            "freeze_state": self.freeze_state,
            "protocol_digest": self.digest(),
        }


def salt_digest() -> str:
    """The salt is part of the freeze; publishing it would let it be gamed."""
    return "sha256:" + hashlib.sha256(SELECTION_SALT.encode("utf-8")).hexdigest()


def quota_for(count: int) -> int:
    """`Q_f = min(1000, floor(0.8 * C_f))`, in integers so it cannot drift."""
    return min(
        MAXIMUM_Q,
        count * QUOTA_FRACTION_NUMERATOR // QUOTA_FRACTION_DENOMINATOR,
    )


def meets_criterion(count: int) -> bool:
    return count >= MINIMUM_C and quota_for(count) >= MINIMUM_Q
