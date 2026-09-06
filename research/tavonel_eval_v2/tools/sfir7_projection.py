#!/usr/bin/env python3
"""Project a publisher record into the record the frame rule may select over.

Two record types exist on purpose, and the seam between them is the dangerous
part. `RawCatalogRecord` is what Libraries.io actually wrote, preserved byte for
byte. `FrameCatalogRecord` is the strict nine-field projection the blind-designed
selection rule operates on. Neither may absorb the other.

**The raw record keeps the publisher's spelling.** `GitHub`, `mit`, `GPL-2.0` are
left exactly as deposited. Canonicalising them here would destroy the evidence
that a later receipt needs to show, side by side, what the publisher wrote and
which declared family it was reconciled to. Semantic reconciliation happens in
the selection comparator, where it is visible and named. Source vocabulary and
comparison semantics are different things and are kept in different places.

**The projection narrows, never widens.** `host_uuid`, `fork` and `status` do not
cross. The rule was designed blind over exactly nine fields; a rule that can
reach a tenth is not the rule that was designed blind, and quietly widening the
predicate surface is how an outcome-independent frame stops being one. Those
three are carried in a provenance sidecar instead, where they can inform a
diagnostic and cannot inform a selection.

**Every mapping is exact or it refuses.** The only structural change is splitting
`name_with_owner` into `namespace` and `name`, and it is checked by
reconstruction: `f"{namespace}/{name}"` must equal the original string. No
trimming, no case conversion, no slash repair, no guessed split. The
`SourceRank`-at-column-33 lesson applies here too -- a field that lands in the
wrong slot produces a record that is entirely plausible and wrong, and only an
identity check catches it.
"""

from __future__ import annotations

import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import sfir7_frame as frame  # noqa: E402 -- needs the sys.path above
from sfir7_catalog_parser import RawCatalogRecord  # noqa: E402

PROTOCOL_ID = "SOURCE_FACT_IR_INDEPENDENT_REPLICATION_V7"

#: raw field -> frame field, for the seven that cross unchanged. `name_with_owner`
#: is absent because it is the one field that is not a rename.
EXACT_PROJECTION: dict[str, str] = {
    "record_id": "record_id",
    "host": "host",
    "language": "primary_language",
    "spdx_license_id": "spdx_license_id",
    "created_utc": "created_utc",
    "last_activity_utc": "last_activity_utc",
    "catalog_rank_value": "catalog_rank_value",
}

#: The fields that stay on the raw record. Declared, not merely omitted.
WITHHELD_FROM_SELECTION = ("host_uuid", "fork", "status")


class ProjectionRefused(RuntimeError):
    """A publisher record could not be projected without changing its meaning."""


class IdentityConflict(RuntimeError):
    """Two records claim one identity, or one identity claims two records."""


@dataclass(frozen=True, slots=True)
class ProvenanceSidecar:
    """What the selection may not see, kept so the census can still use it.

    `host_uuid` is the load-bearing one. It is the host's own repository id, and
    it is how a live census checks that the repository which *answered* is the
    repository that was *selected*. SFIR6 measured that hazard directly:
    `GET /repos/facebook/jest` answers HTTP 200 from a different identity because
    GitHub follows a rename silently (INC-V2-108, finding 4). An address is not
    an identity, and six years separate this snapshot from the census.
    """

    record_id: str
    name_with_owner: str
    host_uuid: str
    fork: bool
    status: str


def split_name_with_owner(value: str) -> tuple[str, str]:
    """Split `owner/repo`, or refuse. Reconstruction is the check."""
    if not isinstance(value, str) or not value:
        raise ProjectionRefused(f"name_with_owner is not a non-empty string: {value!r}")
    if value.count("/") != 1:
        raise ProjectionRefused(
            f"name_with_owner {value!r} is not exactly owner/repo. Guessing a split "
            "would produce an address that looks real and points somewhere else."
        )
    namespace, name = value.split("/")
    if not namespace.strip():
        # `" / "` splits into two non-empty strings that reconstruct perfectly.
        # Blankness is tested, the value is never stripped -- refusing is not
        # repairing, and an address is sent to the endpoint exactly as deposited.
        raise ProjectionRefused(f"name_with_owner {value!r} has a blank owner")
    if not name.strip():
        raise ProjectionRefused(f"name_with_owner {value!r} has a blank repository")
    # Defence in depth, and labelled as such: given exactly one slash, `split`
    # always reconstructs, so this branch cannot fire against today's code and
    # mutation testing confirmed it (removing it changed nothing). It is kept for
    # the better message if the split above is ever rewritten, and it is NOT the
    # guard this seam relies on. The load-bearing reconstruction check is in
    # `require_lossless`, against the raw record rather than against the two
    # pieces this function just produced -- which is what makes it reachable.
    if f"{namespace}/{name}" != value:  # pragma: no cover - unreachable by construction
        raise ProjectionRefused(
            f"round trip failed: {namespace!r} + {name!r} does not reconstruct {value!r}"
        )
    return namespace, name


def project(raw: RawCatalogRecord) -> tuple[frame.FrameCatalogRecord, ProvenanceSidecar]:
    """Return the selection record and the provenance the selection may not see."""
    namespace, name = split_name_with_owner(raw.name_with_owner)
    projected = frame.FrameCatalogRecord(
        record_id=raw.record_id,
        host=raw.host,
        namespace=namespace,
        name=name,
        primary_language=raw.language,
        spdx_license_id=raw.spdx_license_id,
        created_utc=raw.created_utc,
        last_activity_utc=raw.last_activity_utc,
        catalog_rank_value=raw.catalog_rank_value,
    )
    require_lossless(raw, projected)
    return projected, ProvenanceSidecar(
        record_id=raw.record_id,
        name_with_owner=raw.name_with_owner,
        host_uuid=raw.host_uuid,
        fork=raw.fork,
        status=raw.status,
    )


def require_lossless(
    raw: RawCatalogRecord, projected: frame.FrameCatalogRecord
) -> None:
    """Every projected value must be identical to the raw value it came from.

    Written as an independent re-check rather than trusting the constructor
    above, because the failure this guards is a field landing in the wrong slot,
    and a constructor cannot notice that it assigned `language` to
    `spdx_license_id` -- both are strings and the record still looks real.
    """
    for raw_field, frame_field in EXACT_PROJECTION.items():
        source = getattr(raw, raw_field)
        target = getattr(projected, frame_field)
        if source != target:
            raise ProjectionRefused(
                f"projection changed {raw_field!r} -> {frame_field!r}: "
                f"{source!r} became {target!r}"
            )
    if f"{projected.namespace}/{projected.name}" != raw.name_with_owner:
        raise ProjectionRefused(
            f"projection does not reconstruct name_with_owner {raw.name_with_owner!r}"
        )
    for withheld in WITHHELD_FROM_SELECTION:
        if withheld in frame.CATALOG_FIELDS:
            raise ProjectionRefused(
                f"{withheld!r} reached the selection record. The rule was designed "
                "blind over nine fields and may not gain a tenth."
            )


def require_identity_coherence(
    sidecars: Iterable[ProvenanceSidecar],
) -> dict[str, Any]:
    """Refuse a roster whose identities do not line up, and report renames.

    Three distinct situations, and they are not the same:

    * one `record_id` twice -- the catalogue's own key is not unique, and nothing
      downstream can tell which row a selection meant. Refused.
    * one `owner/repo` under two `host_uuid`s -- two different repositories have
      worn one address. Refused, because a census sending requests to that
      address cannot know which one answers.
    * one `host_uuid` under two `owner/repo`s -- the same repository was renamed.
      That is not a conflict. Identity is preserved and the rename is reported.
    """
    by_record: dict[str, ProvenanceSidecar] = {}
    by_address: dict[str, set[str]] = {}
    by_uuid: dict[str, set[str]] = {}
    for sidecar in sidecars:
        if sidecar.record_id in by_record:
            previous = by_record[sidecar.record_id]
            raise IdentityConflict(
                f"record_id {sidecar.record_id!r} appears twice: "
                f"{previous.name_with_owner!r} (uuid {previous.host_uuid!r}) and "
                f"{sidecar.name_with_owner!r} (uuid {sidecar.host_uuid!r})"
            )
        by_record[sidecar.record_id] = sidecar
        by_address.setdefault(sidecar.name_with_owner, set()).add(sidecar.host_uuid)
        by_uuid.setdefault(sidecar.host_uuid, set()).add(sidecar.name_with_owner)

    contested = {
        address: sorted(uuids) for address, uuids in by_address.items() if len(uuids) > 1
    }
    if contested:
        raise IdentityConflict(
            f"{len(contested)} address(es) claimed by more than one repository id, "
            f"e.g. {sorted(contested.items())[:3]}. A census sending requests to that "
            "address cannot know which repository answers."
        )
    renamed = {uuid: sorted(names) for uuid, names in by_uuid.items() if len(names) > 1}
    return {
        "records": len(by_record),
        "distinct_addresses": len(by_address),
        "distinct_host_uuids": len(by_uuid),
        "addresses_contested_by_two_repositories": 0,
        "repositories_seen_under_more_than_one_address": len(renamed),
        "rename_diagnostics": {uuid: names for uuid, names in sorted(renamed.items())[:50]},
        "renames_are_not_conflicts": (
            "one host_uuid under two addresses is the same repository renamed. "
            "Identity is preserved and the rename is reported, because the id is "
            "what the census attests against and the address is only where it asks."
        ),
    }


def attest_live_identity(expected: ProvenanceSidecar, observed_repository_id: Any) -> None:
    """Refuse a live GitHub response that is not the repository we selected.

    The check SFIR6 did not have. `owner/repo` may have moved in the six years
    since this snapshot; the numeric id did not. A response whose id differs is a
    different repository however identical the path looks.
    """
    if str(observed_repository_id) != str(expected.host_uuid):
        raise IdentityConflict(
            f"{expected.name_with_owner!r} answered with repository id "
            f"{observed_repository_id!r}, but the frozen roster selected id "
            f"{expected.host_uuid!r}. Same path, different repository."
        )
