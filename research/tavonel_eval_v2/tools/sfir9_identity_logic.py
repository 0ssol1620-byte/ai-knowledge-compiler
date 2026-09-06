#!/usr/bin/env python3
"""What makes two things the same thing, for SFIR9.

**An address is not an identity.** `facebook/react` and `react/react` were one
repository throughout SFIR7, and the study charged 790 extra provider requests
learning it. A name is a label the host may reassign, to a different repository,
at any time; the numeric repository id is what the host promises to keep. So
identity here is the number, always, and a function that needs an identity
refuses an address rather than accepting it and hoping.

**Refuses rather than coerces.** `"facebook/react"` is not a plausible id and
neither is `""`, but the dangerous case is subtler: an address that happens to
look numeric, or an id arriving as `12345` on one path and `"12345"` on another.
The first is refused; the second is normalized once, here, so two call sites
cannot disagree about whether they matched.

**A candidate is identified by three things and never by its position.** The
repository's numeric id, the path, and the blob sha. Not the discovery order,
which changes with traversal segmentation and would make a resumed run look
different from an uninterrupted one; not the root's address, which changes on
rename. SFIR8's J1 equivalence rests on exactly this.

**Spent identities are excluded for one reason and carry their proof.** A root
SFIR7 or SFIR8 looked at is spent, and `SPENT_DEVELOPMENT_ROOT` is the only
reason any identity is excluded. The proof names which study spent it. It does
not record what that study observed -- not the candidate yield, not the tree
size, not whether the traversal finished -- because an exclusion that carried
those would smuggle an observation into the selection through the exclusion list.

**Nothing here reads the historical chain.** The 59 frozen drifts, the advisory
drift, `root_identity.py`'s expected digest: none is imported, consulted, or
required to pass. This module is a fresh prospective component, and its
independence is checked mechanically by the isolation gate rather than asserted
in this docstring.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

SCHEMA = "tavonel.sfir9.identity_logic.v1"

#: The only reason an identity is excluded from a fresh cohort.
SPENT = "SPENT_DEVELOPMENT_ROOT"

#: Studies whose roots are spent. Naming the study is the proof; naming what the
#: study *found* would be an observation, and observations may not reach
#: selection.
SPENDING_STUDIES = ("SFIR7", "SFIR8")

#: A host id is a decimal integer. Not "mostly digits", not "digits with a
#: suffix" -- anything else is an address, a slug, or a mistake.
_NUMERIC = re.compile(r"\A[1-9][0-9]*\Z")

#: A blob sha is forty lowercase hex characters. A truncated one would make two
#: different blobs compare equal, which is the one thing a content id must not do.
_BLOB_SHA = re.compile(r"\A[0-9a-f]{40}\Z")

#: Facts an earlier study produced. None may appear in an exclusion proof.
FORBIDDEN_EXCLUSION_FIELDS = frozenset(
    {
        "candidate_count",
        "tree_size",
        "traversal_difficulty",
        "completion_status",
        "rename_status",
        "provider_charge",
        "network_hops",
        "source_rank",
    }
)

ADDRESS_AS_IDENTITY = "REFUSED_ADDRESS_USED_AS_IDENTITY"
MALFORMED_IDENTITY = "REFUSED_MALFORMED_IDENTITY"
IDENTITY_MISMATCH = "REFUSED_REPOSITORY_IDENTITY_MISMATCH"
OBSERVATION_IN_PROOF = "REFUSED_OBSERVATION_IN_EXCLUSION_PROOF"


class IdentityRefused(RuntimeError):
    """A refusal carrying the code that names it."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


# --------------------------------------------------------- repository identity


def normalize_host_uuid(value: Any) -> str:
    """One normalization, so two call sites cannot disagree about a match.

    `12345` and `"12345"` are the same repository, and a comparison that treated
    them as different would refuse a root the roster legitimately selected.
    `"facebook/react"` is not a repository id at all -- it is the label this
    module exists to stop standing in for one.

    Everything else is refused by the decimal pattern rather than by a type
    check in front of it. An earlier version had both, and the type check could
    not fail where it stood: every value it rejected -- `None`, a float, a bool,
    a list -- stringifies to something the pattern already refuses, with the
    same refusal code. A guard whose removal changes nothing observable is
    decoration (INC-V2-036).
    """
    text = str(value).strip()
    if "/" in text:
        raise IdentityRefused(
            ADDRESS_AS_IDENTITY,
            f"{value!r} looks like an address, not an identity. A name is a label "
            "the host may reassign to a different repository; the numeric id is "
            "what it promises to keep. SFIR7 spent 790 extra provider requests "
            "learning that `facebook/react` and `react/react` were one repository.",
        )
    if not _NUMERIC.match(text):
        raise IdentityRefused(
            MALFORMED_IDENTITY,
            f"{value!r} is not a decimal repository id.",
        )
    return text


@dataclass(frozen=True, slots=True)
class RepositoryIdentity:
    """A repository, identified by the number rather than by any of its names."""

    host_uuid: str
    catalogue_address: str
    canonical_address: str | None = None

    @classmethod
    def frozen(cls, *, host_uuid: Any, catalogue_address: str) -> RepositoryIdentity:
        return cls(
            host_uuid=normalize_host_uuid(host_uuid),
            catalogue_address=catalogue_address,
        )

    def attest(self, observed_id: Any) -> RepositoryIdentity:
        """Refuse unless the host served the repository the roster froze."""
        observed = normalize_host_uuid(observed_id)
        if observed != self.host_uuid:
            raise IdentityRefused(
                IDENTITY_MISMATCH,
                f"the roster froze repository {self.host_uuid} and this address now "
                f"serves {observed}. HTTP 200 from a real repository is not "
                "evidence that it is the right one.",
            )
        return self

    def adopt(self, canonical_address: str) -> RepositoryIdentity:
        """Take the live name. The identity is unchanged by construction."""
        if not isinstance(canonical_address, str) or canonical_address.count("/") != 1:
            raise IdentityRefused(
                MALFORMED_IDENTITY,
                f"{canonical_address!r} is not a usable owner/name address.",
            )
        return RepositoryIdentity(
            host_uuid=self.host_uuid,
            catalogue_address=self.catalogue_address,
            canonical_address=canonical_address,
        )

    def renamed(self) -> bool:
        """A property of the addresses, never of the identity."""
        if self.canonical_address is None:
            return False
        return self.canonical_address.casefold() != self.catalogue_address.casefold()

    def as_dict(self) -> dict[str, Any]:
        return {
            "host_uuid": self.host_uuid,
            "catalogue_address": self.catalogue_address,
            "canonical_address": self.canonical_address,
            "renamed": self.renamed(),
            "identity_is": "host_uuid",
        }


def same_repository(left: RepositoryIdentity, right: RepositoryIdentity) -> bool:
    """One question, one answer: the numbers. Addresses do not participate."""
    return left.host_uuid == right.host_uuid


# ---------------------------------------------------------- candidate identity


@dataclass(frozen=True, slots=True)
class CandidateIdentity:
    """A file, identified by repository, path and content."""

    repository_numeric_id: str
    path: str
    blob_sha: str

    @classmethod
    def of(cls, *, repository_numeric_id: Any, path: str, blob_sha: str) -> CandidateIdentity:
        if not isinstance(path, str) or not path:
            raise IdentityRefused(MALFORMED_IDENTITY, f"{path!r} is not a path")
        text = blob_sha.lower() if isinstance(blob_sha, str) else blob_sha
        if not isinstance(text, str) or not _BLOB_SHA.match(text):
            raise IdentityRefused(
                MALFORMED_IDENTITY,
                f"{blob_sha!r} is not a full blob sha. A truncated one would make "
                "two different blobs compare equal, which is the one thing a "
                "content identifier must not do.",
            )
        return cls(
            repository_numeric_id=normalize_host_uuid(repository_numeric_id),
            path=path,
            blob_sha=text,
        )

    def key(self) -> tuple[str, str, str]:
        """What makes two candidates the same candidate.

        Discovery order is deliberately absent. It changes when a traversal is
        segmented and resumed, and a candidate that changed identity under
        segmentation would break the equivalence the study rests on.
        """
        return (self.repository_numeric_id, self.path, self.blob_sha)

    def as_dict(self) -> dict[str, Any]:
        return {
            "repository_numeric_id": self.repository_numeric_id,
            "path": self.path,
            "blob_sha": self.blob_sha,
        }


def candidate_set_digest(candidates: Any) -> str:
    """Membership, not order. Two segmentations must digest alike."""
    return _digest(sorted(list(candidate.key()) for candidate in candidates))


def candidate_order_digest(candidates: Any) -> str:
    """Order, as a separate question with a separate answer.

    Kept apart from the set digest because they answer different things and
    SFIR8's J1 needs both: the same candidates, and -- for an uninterrupted run
    compared against a resumed one -- the same order.
    """
    return _digest([list(candidate.key()) for candidate in candidates])


def _digest(payload: Any) -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
    )


# ----------------------------------------------------------- spent exclusions


@dataclass(frozen=True, slots=True)
class SpentIdentity:
    """A root an earlier study looked at, and the proof that it did."""

    host_uuid: str
    spent_by_study: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "host_uuid": self.host_uuid,
            "reason": SPENT,
            "spent_by_study": self.spent_by_study,
            "value_bearing": False,
            "why_not_scientific_authority": (
                "this records only that the identity was looked at, which is a fact "
                "about the study's history. Nothing the earlier study observed about "
                "the repository is carried here."
            ),
        }


def spent_set(records: Any) -> tuple[SpentIdentity, ...]:
    """Build the exclusion list, refusing any record carrying an observation."""
    built: list[SpentIdentity] = []
    for record in records:
        present = FORBIDDEN_EXCLUSION_FIELDS.intersection(record)
        if present:
            raise IdentityRefused(
                OBSERVATION_IN_PROOF,
                f"the exclusion record for {record.get('host_uuid')!r} carries "
                f"{sorted(present)}. An exclusion list that carried what the earlier "
                "study observed would smuggle an observation into selection through "
                "the back door.",
            )
        study = record.get("spent_by_study")
        if study not in SPENDING_STUDIES:
            raise IdentityRefused(
                MALFORMED_IDENTITY,
                f"{study!r} is not a study that spends roots. The proof must name "
                f"one of {list(SPENDING_STUDIES)}.",
            )
        built.append(
            SpentIdentity(
                host_uuid=normalize_host_uuid(record["host_uuid"]),
                spent_by_study=study,
            )
        )
    return tuple(built)


def exclusion_proof(spent: Any) -> dict[str, Any]:
    """The receipt an SFIR9 roster carries for every identity it left out."""
    entries = [item.as_dict() for item in spent]
    return {
        "schema": SCHEMA,
        "reason": SPENT,
        "count": len(entries),
        "host_uuids": sorted(item.host_uuid for item in spent),
        "entries": entries,
        "spending_studies": list(SPENDING_STUDIES),
        "forbidden_in_a_proof": sorted(FORBIDDEN_EXCLUSION_FIELDS),
        "digest": _digest(sorted(entries, key=lambda e: e["host_uuid"])),
        "why_only_one_reason": (
            "a second exclusion reason would be a second selection criterion, and a "
            "criterion derived from what SFIR7 observed is what this protocol exists "
            "to prevent."
        ),
    }
