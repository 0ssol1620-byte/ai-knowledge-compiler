#!/usr/bin/env python3
"""SFIR9 roster selection: outcome-independent by construction, not by promise.

SFIR7's fifty roots are spent. They were selected by an external ordinal, which
was right, but they have since been looked at: their candidate yields, their tree
sizes, which of them were renamed, which the instrument could finish. Every one
of those is now a fact about the study rather than a fact about the world, and
using any of them to choose SFIR9's roster would let the result select its own
evidence.

**So the selection cannot read them, and the way to guarantee that is to make it
structurally impossible rather than to promise it.** The selector takes catalogue
rows and a frozen protocol. It has no parameter through which an observation
could enter, and `describe()` names every input it does use together with where
that input came from -- external catalogue metadata, or the frozen protocol
itself. A control asserts that no input is classified as an observation.

**The partition comes before the ordering, and that order matters.** Ranking the
whole catalogue and taking the top N invites the obvious objection: you picked
the popular repositories, and popular repositories are well-maintained, and
well-maintained repositories are easy to traverse. Hashing `host_uuid` with a
frozen salt first splits the catalogue into buckets that no property of a
repository can predict, and the external ordering then runs *inside* one
predeclared bucket. The result is still deterministic and still reproducible from
the frozen protocol, but "you chose the easy ones" stops being available.

**N is derived from an execution envelope, never from a capacity count.** How
many rate windows the study may occupy, how much of each window is usable, what
a single root is allowed to spend. Nothing in that chain asks how many candidates
anything produced. SFIR7 derived its N from a request budget too and then the
budget turned out to be wrong in a way nobody had written down (INC-V2-115), so
every term here is declared, named and reported.

**Spent roots are excluded for exactly one reason.** `SPENT_DEVELOPMENT_ROOT`.
Not because they were difficult, not because they were renamed, not because of
anything observed about them -- purely because they have been looked at, which
is a property of the study's history and not of the repository.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

PROTOCOL_ID = "SOURCE_FACT_IR_FRESH_HELDOUT_V9"
SCHEMA = "tavonel.sfir9.roster_selection.v1"

#: The only reason an identity may be excluded. A second reason would be a
#: second selection criterion, and a criterion derived from what SFIR7 observed
#: is exactly what this protocol exists to prevent.
SPENT = "SPENT_DEVELOPMENT_ROOT"

#: Facts about a repository that SFIR7 and SFIR8 produced. None may participate
#: in selection. Listed so the refusal can name what it caught.
FORBIDDEN_SELECTION_INPUTS = frozenset(
    {
        "candidate_count",
        "tree_size",
        "framework",
        "language",
        "rename_status",
        "traversal_difficulty",
        "completion_status",
        "provider_charge",
        "network_hops",
    }
)


class SelectionRefused(RuntimeError):
    """Selection would have depended on something it must not see."""


@dataclass(frozen=True, slots=True)
class EnvelopeTerm:
    """One declared quantity, with where it came from written next to it."""

    name: str
    value: int
    source: str
    rationale: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "source": self.source,
            "rationale": self.rationale,
        }


#: Every term is `external_execution_envelope`. If one were ever
#: `study_observation`, `require_no_observation_participates` refuses.
EXTERNAL = "external_execution_envelope"
OBSERVATION = "study_observation"


@dataclass(frozen=True, slots=True)
class ExecutionEnvelope:
    """What the study may spend, declared before anything is selected."""

    permitted_rate_windows: EnvelopeTerm
    usable_charge_per_window: EnvelopeTerm
    per_root_charge_allowance: EnvelopeTerm

    def terms(self) -> tuple[EnvelopeTerm, ...]:
        return (
            self.permitted_rate_windows,
            self.usable_charge_per_window,
            self.per_root_charge_allowance,
        )

    def global_charge_budget(self) -> int:
        return self.permitted_rate_windows.value * self.usable_charge_per_window.value

    def derive_n(self) -> int:
        """Roots the envelope affords. Nothing here reads a capacity count."""
        allowance = self.per_root_charge_allowance.value
        if allowance <= 0:
            raise SelectionRefused(
                "the per-root charge allowance is not positive, so N is not defined"
            )
        return self.global_charge_budget() // allowance

    def describe(self) -> dict[str, Any]:
        return {
            "terms": [term.as_dict() for term in self.terms()],
            "global_charge_budget": self.global_charge_budget(),
            "n": self.derive_n(),
            "formula": (
                "N = (permitted_rate_windows * usable_charge_per_window) "
                "// per_root_charge_allowance"
            ),
            "no_term_reads_a_capacity_count": True,
            "why_charges_and_not_logical_requests": (
                "only the provider's charge is comparable with the provider's limit. "
                "SFIR7 bounded logical requests and was billed for network hops, and "
                "the two differed by 790 on renamed addresses alone."
            ),
        }


def require_no_observation_participates(envelope: ExecutionEnvelope) -> None:
    for term in envelope.terms():
        if term.source != EXTERNAL:
            raise SelectionRefused(
                f"envelope term {term.name!r} is sourced from {term.source!r}. N must "
                "be a function of what the study may spend, never of what an earlier "
                "study observed."
            )


@dataclass(frozen=True, slots=True)
class FrozenSelection:
    """The selection rule, fixed before a single row is read."""

    salt: str
    partition_count: int
    partition_index: int
    envelope: ExecutionEnvelope
    spent_host_uuids: frozenset[str] = field(default_factory=frozenset)

    def digest(self) -> str:
        return (
            "sha256:"
            + hashlib.sha256(
                json.dumps(
                    {
                        "salt": self.salt,
                        "partition_count": self.partition_count,
                        "partition_index": self.partition_index,
                        "envelope": self.envelope.describe(),
                        "spent_host_uuids": sorted(self.spent_host_uuids),
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
        )

    def partition_of(self, host_uuid: str) -> int:
        """Which bucket an identity falls in. Salted, so it cannot be gamed.

        Keyed on the host's numeric identity rather than the address: an address
        can change, and a partition that moved when a repository was renamed
        would make the roster depend on rename status -- one of the things SFIR7
        observed and this protocol may not use.
        """
        material = f"{self.salt}:{host_uuid}".encode()
        return int.from_bytes(hashlib.blake2b(material, digest_size=8).digest(), "big") % (
            self.partition_count
        )

    def admits(self, host_uuid: str) -> bool:
        return self.partition_of(host_uuid) == self.partition_index


def select(
    rows: Iterable[dict[str, Any]], rule: FrozenSelection
) -> dict[str, Any]:
    """Partition, exclude the spent, order externally, take N.

    `rows` carry only catalogue metadata. A row containing anything from
    `FORBIDDEN_SELECTION_INPUTS` refuses the whole selection rather than being
    filtered: a forbidden field reaching this function means something upstream
    joined study output onto the catalogue, and quietly dropping it would leave
    that join in place for the next caller.
    """
    require_no_observation_participates(rule.envelope)
    n = rule.envelope.derive_n()

    admitted: list[dict[str, Any]] = []
    excluded_spent: list[str] = []
    outside_partition = 0

    for row in rows:
        forbidden = FORBIDDEN_SELECTION_INPUTS.intersection(row)
        if forbidden:
            raise SelectionRefused(
                f"catalogue row carries {sorted(forbidden)}, which SFIR7 or SFIR8 "
                "observed. Selection may not see it, and its presence here means "
                "study output has been joined onto the frozen catalogue upstream."
            )
        host_uuid = str(row["host_uuid"])
        if not rule.admits(host_uuid):
            outside_partition += 1
            continue
        if host_uuid in rule.spent_host_uuids:
            excluded_spent.append(host_uuid)
            continue
        admitted.append(row)

    admitted.sort(key=lambda r: (-int(r["source_rank"]), str(r["record_id"])))
    roster = admitted[:n]

    return {
        "schema": SCHEMA,
        "protocol_id": PROTOCOL_ID,
        "selection_digest": rule.digest(),
        "n": n,
        "n_derivation": rule.envelope.describe(),
        "partition": {
            "salt_digest": "sha256:"
            + hashlib.sha256(rule.salt.encode("utf-8")).hexdigest(),
            "partition_count": rule.partition_count,
            "partition_index": rule.partition_index,
            "keyed_on": "host_uuid",
            "rows_outside_partition": outside_partition,
            "why_partition_before_ordering": (
                "ranking the whole catalogue and taking the top N invites the "
                "objection that popular repositories are well-maintained and "
                "well-maintained repositories are easy to traverse. A salted hash "
                "bucket is not predictable from any property of a repository, so the "
                "external ordering runs inside a population nobody could have chosen."
            ),
        },
        "ordering": {
            "primary": "source_rank descending",
            "secondary": "record_id ascending",
            "source": "frozen Libraries.io catalogue metadata only",
        },
        "exclusions": {
            "reason": SPENT,
            "count": len(excluded_spent),
            "host_uuids": sorted(excluded_spent),
            "why": (
                "these identities have been looked at. That is a property of this "
                "study's history, not of the repository, and it is the only reason "
                "any identity is excluded."
            ),
        },
        "eligible_in_partition": len(admitted),
        "roster": [
            {
                "rank": index + 1,
                "host_uuid": str(row["host_uuid"]),
                "name_with_owner": row["name_with_owner"],
                "record_id": str(row["record_id"]),
                "source_rank": int(row["source_rank"]),
            }
            for index, row in enumerate(roster)
        ],
        "roster_is_short": len(roster) < n,
        "forbidden_selection_inputs": sorted(FORBIDDEN_SELECTION_INPUTS),
        "nothing_observed_participated": (
            "candidate yield, tree size, framework, language, rename status, "
            "traversal difficulty and completion status are all facts SFIR7 or SFIR8 "
            "produced. None is a parameter of this function, and a row carrying one "
            "refuses the selection outright."
        ),
    }


def roster_fingerprint(selection: dict[str, Any]) -> str:
    """Digest of the roster in rank order. Order is part of the freeze."""
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(selection["roster"], sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()
    )
