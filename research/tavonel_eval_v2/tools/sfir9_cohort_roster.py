#!/usr/bin/env python3
"""The roster: written once, sealed, and unable to carry what the study found.

**Every field here is catalogue metadata or a proof about the selection.** The
Libraries.io record id, the numeric host id, the address the catalogue froze in
January 2020, the external SourceRank, which partition the root fell in, and
where it landed in the ordering. Nothing about how the repository behaved.

That exclusion is the whole point and it is enforced rather than remembered.
`candidate_count`, `tree_size` and `rename_status` are facts SFIR7 and SFIR8
produced, and a roster carrying one would let the confirmatory study's cohort be
shaped by the development study's results. An entry offering one refuses the
whole build.

**The live canonical address is not roster metadata.** A root may have been
renamed since 2020, and the study will discover that during acquisition -- but
that discovery is *execution evidence*, recorded against the roster by digest
and never merged into it. Merging them would make the roster a document that
changes while the study runs, and a cohort that changes during a study is not a
cohort. `execution_evidence()` is deliberately a separate structure.

**Once. The seal is what makes it once.** A roster generated, inspected, and then
regenerated with a different salt is not a held-out cohort, whatever the second
roster contains. `seal()` may be called once, a sealed roster refuses every
mutation, and generation refuses against a protocol that is not frozen -- so the
ordering of "fix the rule, then look" cannot be reversed by accident.

**Spent roots carry their exclusion proof with them.** Not as a note in a
changelog: the sealed roster contains the proof, so a reader a year from now can
see which identities were withheld and that the only reason was that an earlier
study had already looked at them.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

import sfir9_identity_logic as identity
import sfir9_protocol as protocol_module

SCHEMA = "tavonel.sfir9.cohort_roster.v1"

#: Exactly what a roster entry may hold. A field outside this set is either an
#: observation or a live-execution fact, and neither belongs in a cohort.
PERMITTED_ENTRY_FIELDS = (
    "record_id",
    "host_uuid",
    "catalogue_address",
    "source_rank",
    "partition_digest",
    "selection_ordinal",
)

#: Facts SFIR7 and SFIR8 produced about repositories. None may reach a roster.
FORBIDDEN_ROSTER_FIELDS = frozenset(
    {
        "candidate_count",
        "tree_size",
        "framework",
        "language",
        "rename_status",
        "renamed",
        "canonical_address",
        "traversal_difficulty",
        "completion_status",
        "provider_charge",
        "network_hops",
    }
)

OBSERVATION_IN_ROSTER = "REFUSED_OBSERVATION_IN_ROSTER"
SPENT_IN_ROSTER = "REFUSED_SPENT_ROOT_IN_ROSTER"
DUPLICATE = "REFUSED_DUPLICATE_ROSTER_ENTRY"
BROKEN_ORDINALS = "REFUSED_NON_CONTIGUOUS_ORDINALS"
ALREADY_SEALED = "REFUSED_ROSTER_ALREADY_SEALED"
NOT_SEALED = "REFUSED_UNSEALED_ROSTER"
DRAFT_PROTOCOL = "REFUSED_ROSTER_UNDER_DRAFT_PROTOCOL"


class RosterRefused(RuntimeError):
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


def partition_digest(*, salt_digest: str, partition_count: int, partition_index: int,
                     host_uuid: str) -> str:
    """Proof a root belongs in the declared bucket, without exposing the salt.

    The salt stays inside the frozen protocol -- publishing it would let someone
    work out in advance which repositories a partition would select. What can be
    published is a value that changes if the bucket, the count, or the identity
    changes, and this is that value.
    """
    return _digest(
        {
            "salt_digest": salt_digest,
            "partition_count": partition_count,
            "partition_index": partition_index,
            "host_uuid": host_uuid,
        }
    )


@dataclass(frozen=True, slots=True)
class RosterEntry:
    """One selected root. Six fields, all of them catalogue or selection facts."""

    record_id: str
    host_uuid: str
    catalogue_address: str
    source_rank: int
    partition_digest: str
    selection_ordinal: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "host_uuid": self.host_uuid,
            "catalogue_address": self.catalogue_address,
            "source_rank": self.source_rank,
            "partition_digest": self.partition_digest,
            "selection_ordinal": self.selection_ordinal,
        }


def _entry_from(row: dict[str, Any], *, ordinal: int, salt_digest: str,
                partition_count: int, partition_index: int) -> RosterEntry:
    present = FORBIDDEN_ROSTER_FIELDS.intersection(row)
    if present:
        raise RosterRefused(
            OBSERVATION_IN_ROSTER,
            f"the selected row for {row.get('host_uuid')!r} carries {sorted(present)}. "
            "Those are facts SFIR7 or SFIR8 produced, or facts the study has not "
            "learned yet, and a cohort shaped by either is not held out.",
        )
    host_uuid = identity.normalize_host_uuid(row["host_uuid"])
    return RosterEntry(
        record_id=str(row["record_id"]),
        host_uuid=host_uuid,
        catalogue_address=str(row["name_with_owner"]),
        source_rank=int(row["source_rank"]),
        partition_digest=partition_digest(
            salt_digest=salt_digest,
            partition_count=partition_count,
            partition_index=partition_index,
            host_uuid=host_uuid,
        ),
        selection_ordinal=ordinal,
    )


class CohortRoster:
    """Built once from a selection, then sealed and never altered."""

    def __init__(
        self,
        *,
        protocol: protocol_module.Protocol,
        selection: dict[str, Any],
        exclusion_proof: dict[str, Any],
    ) -> None:
        protocol.require_frozen("roster generation")
        self.protocol = protocol
        self.protocol_digest = protocol.digest()
        self.selection_digest = selection["selection_digest"]
        self.exclusion_proof = exclusion_proof
        self.n = selection["n"]
        self.roster_is_short = selection["roster_is_short"]
        self._sealed = False
        self._seal_digest: str | None = None

        partition = selection["partition"]
        spent = set(exclusion_proof["host_uuids"])
        entries: list[RosterEntry] = []
        for ordinal, row in enumerate(selection["roster"], start=1):
            entry = _entry_from(
                row,
                ordinal=ordinal,
                salt_digest=partition["salt_digest"],
                partition_count=partition["partition_count"],
                partition_index=partition["partition_index"],
            )
            if entry.host_uuid in spent:
                raise RosterRefused(
                    SPENT_IN_ROSTER,
                    f"repository {entry.host_uuid} is on the exclusion list and in "
                    "the roster. A root an earlier study looked at cannot be part of "
                    "a fresh held-out cohort.",
                )
            entries.append(entry)

        self._check_wellformed(entries)
        self.entries = tuple(entries)

    @staticmethod
    def _check_wellformed(entries: list[RosterEntry]) -> None:
        uuids = [entry.host_uuid for entry in entries]
        if len(set(uuids)) != len(uuids):
            raise RosterRefused(
                DUPLICATE,
                "the same repository appears twice. One repository measured twice is "
                "one repository, and counting it twice would inflate the census.",
            )
        records = [entry.record_id for entry in entries]
        if len(set(records)) != len(records):
            raise RosterRefused(DUPLICATE, "the same catalogue record appears twice.")
        ordinals = [entry.selection_ordinal for entry in entries]
        if ordinals != list(range(1, len(entries) + 1)):
            raise RosterRefused(
                BROKEN_ORDINALS,
                "the selection ordinals are not 1..N in order. A gap is a root that "
                "was selected and lost; a repeat means two roots claim one rank.",
            )

    # -- sealing ----------------------------------------------------------

    def body(self) -> dict[str, Any]:
        """What the seal covers. The seal state is deliberately outside it."""
        return {
            "schema": SCHEMA,
            "protocol_digest": self.protocol_digest,
            "selection_digest": self.selection_digest,
            "n": self.n,
            "roster_is_short": self.roster_is_short,
            "entry_count": len(self.entries),
            "entries": [entry.as_dict() for entry in self.entries],
            "exclusion_proof": self.exclusion_proof,
            "permitted_entry_fields": list(PERMITTED_ENTRY_FIELDS),
            "forbidden_roster_fields": sorted(FORBIDDEN_ROSTER_FIELDS),
        }

    def digest(self) -> str:
        return _digest(self.body())

    def seal(self) -> str:
        """Once. A second call is refused rather than being idempotent.

        Idempotence would be the friendlier behaviour and the wrong one: a
        caller sealing twice has lost track of whether the roster in hand is the
        one that was sealed the first time.
        """
        if self._sealed:
            raise RosterRefused(
                ALREADY_SEALED,
                "this roster is already sealed. A roster generated, inspected and "
                "regenerated is not a held-out cohort, whatever the second one "
                "contains.",
            )
        self._sealed = True
        self._seal_digest = self.digest()
        return self._seal_digest

    @property
    def sealed(self) -> bool:
        return self._sealed

    def require_sealed(self, action: str) -> None:
        if not self._sealed:
            raise RosterRefused(
                NOT_SEALED,
                f"{action} requires a sealed roster. An unsealed roster can still be "
                "regenerated, so anything measured against it is measured against a "
                "moving cohort.",
            )

    def verify_seal(self) -> dict[str, Any]:
        """Re-derive the digest and compare it with what the seal recorded."""
        self.require_sealed("seal verification")
        recomputed = self.digest()
        return {
            "sealed": True,
            "recorded_seal_digest": self._seal_digest,
            "recomputed_digest": recomputed,
            "intact": recomputed == self._seal_digest,
        }

    # -- receipts ---------------------------------------------------------

    def receipt(self) -> dict[str, Any]:
        return {
            **self.body(),
            "sealed": self._sealed,
            "roster_digest": self._seal_digest or self.digest(),
            "why_no_live_address_here": (
                "a root may have been renamed since the catalogue froze, and the "
                "study learns that during acquisition. That is execution evidence "
                "and is recorded against this roster by digest rather than merged "
                "into it: a cohort that changes while the study runs is not a cohort."
            ),
        }

    def execution_evidence(self, observations: Any) -> dict[str, Any]:
        """Live findings about roster roots, kept beside the roster, never in it."""
        self.require_sealed("recording execution evidence")
        known = {entry.host_uuid for entry in self.entries}
        rows: list[dict[str, Any]] = []
        for observation in observations:
            host_uuid = identity.normalize_host_uuid(observation["host_uuid"])
            if host_uuid not in known:
                raise RosterRefused(
                    SPENT_IN_ROSTER,
                    f"repository {host_uuid} is not in this roster, so an observation "
                    "about it is not evidence about this cohort.",
                )
            rows.append(
                {
                    "host_uuid": host_uuid,
                    "canonical_address": observation.get("canonical_address"),
                    "renamed": bool(observation.get("renamed")),
                    "identity_verified": bool(observation.get("identity_verified")),
                }
            )
        return {
            "schema": SCHEMA + ".execution_evidence",
            "roster_digest": self._seal_digest,
            "observations": rows,
            "is_part_of_the_roster": False,
            "why_separate": (
                "these are facts the study learned by running. Merging them into the "
                "cohort would make the cohort a document that changes mid-study, and "
                "would put `renamed` -- which SFIR7 also observed -- into the "
                "selection record where it must never appear."
            ),
        }
