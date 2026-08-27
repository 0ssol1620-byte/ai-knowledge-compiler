#!/usr/bin/env python3
"""SFIR7's transport: SFIR5's pacing and ledger, plus a fourth gate.

SFIR5 and SFIR6 established three gates on every response. Bytes arrived
(transport), the API said yes (protocol), and what came back is what was asked
for (semantic completeness). SFIR7 needs a fourth, and INC-V2-108's fourth
finding is why: GitHub answers HTTP 200 for a repository that has been renamed,
serving the *new* repository's tree under the old address. All three existing
gates pass. The census measures a repository nobody selected.

That hazard was theoretical for SFIR4, whose twenty roots were chosen by hand
weeks before it ran. It is not theoretical here. SFIR7's roster comes from a
catalogue deposited in January 2020; six years of renames sit between the
snapshot and the census, and the frame rule had no way to prefer repositories
that would keep their names.

**The gate.** The catalogue recorded each repository's numeric host id. GitHub
returns that same id in the metadata response the traversal already fetches. If
they differ, the address now points at a different repository and the root is
refused -- not excluded quietly, not counted as zero, refused. A rename that
keeps the id is fine and is reported as a diagnostic, because the id is what
identity means and the address is only where the question was asked.

**It is checked on the response the traversal actually uses.** Not on a separate
verification request, which could succeed while the traversal's own fetch went
somewhere else, and which would also spend requests against a budget INC-V2-115
already shows is tight. `_observe` is the single point every Git response passes
through, so the check sits where the bytes are, once.
"""

from __future__ import annotations

import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import sfir5_transport as t5  # noqa: E402
import sfir7_projection as projection  # noqa: E402
import sfir7_roots as roots  # noqa: E402

PROTOCOL_ID = "SOURCE_FACT_IR_INDEPENDENT_REPLICATION_V7"

#: The one URL shape that carries a repository's own identity. Anything else --
#: a commit, a tree -- is addressed by sha and cannot be attested this way.
_REPOSITORY_METADATA_PREFIX = "https://api.github.com/repos/"


class RepositoryIdentityRefused(RuntimeError):
    """The repository that answered is not the repository that was selected."""


class SFIR7Transport(t5.PacedObservingTransport):
    """SFIR5's transport with every Git root attested against its frozen host id."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        #: repository -> what the live host said its numeric id is
        self.observed_ids: dict[str, str] = {}
        #: repository -> the address the live host reports for that id today
        self.renames: dict[str, str] = {}

    def _observe(self, family: str, root_id: str, url: str) -> Any:
        value = super()._observe(family, root_id, url)
        if family != "git_docs":
            return value
        repository = _repository_of(url)
        if repository is None:
            return value
        self._attest(repository, value)
        return value

    def _attest(self, repository: str, value: Any) -> None:
        if not isinstance(value, Mapping):
            raise RepositoryIdentityRefused(
                f"{repository}: repository metadata is not an object, so its identity "
                "cannot be attested. A root whose identity is unknown is not censused."
            )
        observed = value.get("id")
        if observed is None:
            raise RepositoryIdentityRefused(
                f"{repository}: the host returned no repository id. The frozen roster "
                "binds an id, and a response that omits it cannot be matched to it."
            )
        expected = roots.expected_uuid(repository)
        sidecar = projection.ProvenanceSidecar(
            record_id="", name_with_owner=repository, host_uuid=expected, fork=False, status=""
        )
        try:
            projection.attest_live_identity(sidecar, observed)
        except projection.IdentityConflict as error:
            raise RepositoryIdentityRefused(
                f"{repository}: {error}. The catalogue selected repository {expected} and "
                f"this address now serves repository {observed}. Censusing it would "
                "measure a tree the frame rule never chose (INC-V2-108, finding 4)."
            ) from error
        self.observed_ids[repository] = str(observed)
        live_address = value.get("full_name")
        if isinstance(live_address, str) and live_address.casefold() != repository.casefold():
            #: Same id, different address: the repository was renamed and GitHub
            #: redirected. Identity holds, so this is reported and not refused.
            self.renames[repository] = live_address

    def identity_attestation(self) -> dict[str, Any]:
        """What the fourth gate saw, for the census receipt."""
        return {
            "gate": "LIVE_REPOSITORY_ID_MATCHES_FROZEN_HOST_UUID",
            "roots_attested": len(self.observed_ids),
            "roots_frozen": len(roots.declared_roots()),
            "renames_observed": dict(sorted(self.renames.items())),
            "rename_count": len(self.renames),
            "why_a_rename_is_not_a_conflict": (
                "identity is the host's numeric repository id, which a rename does not "
                "change. The address is where the question was asked, not what was "
                "asked about. A different id under the same address IS a conflict and "
                "refuses the root."
            ),
            "on_mismatch": "REFUSE",
            "attested_on": (
                "the repository metadata response the traversal itself fetches, not a "
                "separate verification request that could succeed while the traversal "
                "went elsewhere"
            ),
        }


def _repository_of(url: str) -> str | None:
    """`https://api.github.com/repos/owner/name` and nothing longer.

    `/repos/owner/name/commits/...` and `/repos/owner/name/git/trees/...` are
    addressed by sha and carry no repository id, so they are not attestable and
    must not be mistaken for the metadata response.
    """
    if not url.startswith(_REPOSITORY_METADATA_PREFIX):
        return None
    remainder = url[len(_REPOSITORY_METADATA_PREFIX) :]
    if remainder.count("/") != 1 or not all(part for part in remainder.split("/")):
        return None
    return remainder
