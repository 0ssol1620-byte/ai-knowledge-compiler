#!/usr/bin/env python3
"""Freeze IDENTITY_CHANGE_MIGRATION_CLOSURE_V1, and then freeze its universe.

Two subcommands, and the order between them is the point of the tool.

    freeze_migration_closure.py protocol   # rung 1: the contract
    freeze_migration_closure.py universe   # rung 2: the cohort

INC-V2-042 is the reason this exists. The Protected Core ladder ran backwards:
the production switch shipped, and the benchmark and canary that were supposed
to authorise it were produced afterwards, by the party who already knew which
direction was convenient. A closure that froze its acceptance criteria after
seeing its own result would repeat that exactly, one level up.

So ordering here is a *precondition*, not a convention. `universe` refuses
unless the protocol freeze receipt already exists and pins the protocol file's
current sha256, and `identity_change_migration_closure.py` refuses unless both
receipts exist. Wall-clock stamps are recorded too, but they are corroboration:
a stamp can only be read after the fact, whereas a refusal cannot be walked
past.

Neither subcommand reads a closure result, and neither can: nothing here
imports `akc_cir`, calls a change predicate, or opens a canonical document.
`universe` reads cohort manifests, checks that the payload bytes each pair was
derived from are still on disk under the digest recorded for them, proves
disjointness by lineage id, and writes the list.

**No SFI3 payload is opened, listed or fetched by this tool.** The disjointness
the founder's ruling requires is from the 538-pair retrospective cohort, and
that is what is proven; SFI3 is untouched and stays the prospective
confirmatory evidence for the lane that owns it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import NS, ROOT, canonical_sha, git_head, rel, sha_file
from evidence import RECEIPTS, runs_of, write_immutable

PROTOCOL = NS / "protocols" / "IDENTITY_CHANGE_MIGRATION_CLOSURE_V1.yaml"
PROTOCOL_STEM = "identity-change-migration-closure-protocol-freeze"
UNIVERSE_STEM = "identity-change-migration-closure-universe"

#: The two acquisition artifacts whose `admitted` rows are the 538-pair
#: retrospective cohort the new cohort must be disjoint from. Read for their
#: lineage ids only.
RETROSPECTIVE_COHORTS = (
    NS / "artifacts" / "development" / "sfi1" / "sfi1_acquisition.json",
    NS / "artifacts" / "development" / "sfi2" / "sfi2_acquisition.json",
)


class FreezeRefused(RuntimeError):
    """A precondition of the ladder is not met. Never worked around here."""


# --------------------------------------------------------------------------
# reading the frozen protocol
# --------------------------------------------------------------------------


def load_protocol(path: Path = PROTOCOL) -> dict[str, Any]:
    import yaml

    return yaml.safe_load(path.read_text(encoding="utf-8"))


def protocol_freeze_receipt(stem: str = PROTOCOL_STEM) -> dict[str, Any] | None:
    """The most recent protocol freeze receipt, or None if never frozen."""
    runs = runs_of(stem)
    if not runs:
        return None
    body = json.loads((ROOT / runs[-1]).read_text(encoding="utf-8"))
    body["_receipt_path"] = runs[-1]
    return body


def require_frozen_protocol(path: Path = PROTOCOL) -> dict[str, Any]:
    """The freeze receipt for `path`, refusing if absent or digest-mismatched.

    A digest mismatch is refused rather than re-frozen. After a freeze, editing
    the protocol is a deliberate act that needs its own receipt naming what it
    supersedes; silently re-sealing it here would make the freeze mean nothing.
    """
    receipt = protocol_freeze_receipt()
    if receipt is None:
        raise FreezeRefused(
            "the closure protocol has not been frozen. Run "
            "`freeze_migration_closure.py protocol` first -- freezing after "
            "measuring is INC-V2-042."
        )
    current = sha_file(path)
    if receipt.get("protocol_sha256") != current:
        raise FreezeRefused(
            "the closure protocol has changed since it was frozen.\n"
            f"  frozen:  {receipt.get('protocol_sha256')}\n"
            f"  current: {current}\n"
            "A frozen protocol is amended by a new receipt naming what it "
            "supersedes, never by re-sealing it in place."
        )
    return receipt


# --------------------------------------------------------------------------
# the candidate universe
# --------------------------------------------------------------------------


def retrospective_lineage_ids() -> tuple[frozenset[str], dict[str, Any]]:
    """The 538 admitted pairs' lineage ids, with provenance for the receipt."""
    ids: set[str] = set()
    sources: list[dict[str, Any]] = []
    for path in RETROSPECTIVE_COHORTS:
        if not path.is_file():
            raise FreezeRefused(
                f"retrospective cohort artifact absent: {rel(path)}. Disjointness "
                "cannot be proven against a cohort that is not on disk, and an "
                "unprovable disjointness is not an assumed one."
            )
        admitted = json.loads(path.read_text(encoding="utf-8"))["admitted"]
        here = {row["lineage_id"] for row in admitted}
        ids |= here
        sources.append(
            {
                "artifact": rel(path),
                "artifact_sha256": sha_file(path),
                "admitted_pairs": len(admitted),
                "distinct_lineages": len(here),
            }
        )
    return frozenset(ids), {"sources": sources, "distinct_lineages": len(ids)}


def confirmed_defect_lineages() -> tuple[frozenset[str], dict[str, Any]]:
    """The 14 SFI2 E5-confirmed lineages, read for the disjointness proof ONLY.

    They are development fixtures. A case used to diagnose a defect cannot
    certify its repair, so they appear here, in a subtraction, and in no
    numerator or denominator anywhere in the closure.
    """
    candidates = sorted(RECEIPTS.glob("sfi2-native-provenance--*.json"))
    if not candidates:
        raise FreezeRefused(
            "no sfi2-native-provenance receipt present; the 14 confirmed "
            "lineages cannot be excluded by name."
        )
    source = candidates[-1]
    body = json.loads(source.read_text(encoding="utf-8"))
    confirmed = body["rebuild"]["E5_confirmed_selective_stale_escape"]["confirmed"]
    ids = frozenset(row["lineage_id"] for row in confirmed)
    return ids, {
        "source_receipt": rel(source),
        "source_receipt_sha256": sha_file(source),
        "confirmed_rows": len(confirmed),
        "distinct_lineages": len(ids),
        "read_for": "disjointness proof only; never a numerator or a denominator",
    }


def candidate_manifests(protocol: dict[str, Any]) -> list[Path]:
    """The declared candidate sources, in the declared order, that exist.

    Order is read from the frozen protocol rather than restated here: the
    dedup below keeps the first occurrence of a lineage, so the order decides
    which manifest a shared lineage is attributed to, and a restated order
    would be a second home for that decision.
    """
    paths: list[Path] = []
    for pattern in protocol["cohort"]["candidate_sources_in_declared_order"]:
        target = NS / pattern
        if "*" in pattern:
            paths.extend(sorted(NS.glob(pattern)))
        elif target.is_file():
            paths.append(target)
    return paths


def _pair_rows(manifest: Path) -> list[dict[str, Any]]:
    body = json.loads(manifest.read_text(encoding="utf-8"))
    return list(body.get("documents", ()))


def _lineage_id(row: dict[str, Any]) -> str:
    identifier = row.get("document_id") or row.get("lineage_id")
    if not identifier:
        raise FreezeRefused(f"a cohort row carries no lineage identity: {sorted(row)}")
    return str(identifier)


def _verify_side(row: dict[str, Any], side: str) -> tuple[dict[str, Any] | None, str | None]:
    """Check the cached bytes this pair was built from are still what they were.

    The universe has to be *deterministically* frozen, which means a later
    reader must be able to tell whether the inputs moved. Recording the digest
    is not enough on its own; it is recomputed here, so a payload that no longer
    matches the manifest describing it is excluded at freeze time rather than
    measured.

    Returns `(entry, None)` when the bytes verify and `(None, reason)` when they
    do not. Excluding the pair, rather than refusing the whole freeze, is the
    right granularity: the protocol selects pairs "whose payloads are already
    cached on local disk", and a payload that cannot be verified against its own
    manifest is not usably cached. Every exclusion is named in the receipt with
    its reason, so this is a fail-closed drop and never a silent one.
    """
    entry = row[side]
    raw = ROOT / entry["raw_path"]
    canonical = ROOT / entry["canonical_path"]
    if not raw.is_file():
        return None, f"cached payload missing: {entry['raw_path']}"
    if not canonical.is_file():
        return None, f"canonical document missing: {entry['canonical_path']}"
    digest = "sha256:" + hashlib.sha256(raw.read_bytes()).hexdigest()
    if digest != entry["raw_sha256"]:
        return None, (
            f"cached payload changed since acquisition: {entry['raw_path']} "
            f"(recorded {entry['raw_sha256']}, on disk {digest})"
        )
    return {
        "raw_path": entry["raw_path"],
        "raw_sha256": digest,
        "canonical_path": entry["canonical_path"],
        "canonical_sha256": sha_file(canonical),
    }, None


def _colliding_slugs(rows: list[dict[str, Any]]) -> set[str]:
    """Slugs that more than one document in this manifest writes to.

    P4i truncates `document_slug` at 80 characters, and three pairs of distinct
    Kubernetes/Grafana documents collide there, so the second acquisition wrote
    over the first's cached payload. Six of 1,778 cached sides no longer match
    their recorded digest as a result.

    BOTH members of a collision are excluded, not only the side whose digest
    fails. One of them holds the wrong bytes and the other may hold the right
    ones, and nothing on disk says which is which -- keeping the one that still
    verifies would be choosing the convenient reading of an ambiguity. The
    exclusion is a property of the filename, so it cannot correlate with any
    closure outcome.
    """
    counts: dict[str, int] = {}
    for row in rows:
        slug = row.get("document_slug")
        if slug:
            counts[slug] = counts.get(slug, 0) + 1
    return {slug for slug, count in counts.items() if count > 1}


def build_universe(protocol: dict[str, Any]) -> dict[str, Any]:
    """Select, prove disjoint, and verify. No closure measurement happens here."""
    excluded, excluded_meta = retrospective_lineage_ids()
    confirmed, confirmed_meta = confirmed_defect_lineages()

    manifests = candidate_manifests(protocol)
    if not manifests:
        raise FreezeRefused("no declared candidate cohort manifest is on disk")

    seen: set[str] = set()
    pairs: list[dict[str, Any]] = []
    per_manifest: list[dict[str, Any]] = []
    removed_by_disjointness: list[str] = []
    unverifiable: list[dict[str, str]] = []

    for manifest in manifests:
        rows = _pair_rows(manifest)
        collisions = _colliding_slugs(rows)
        kept = duplicate = removed = unverified = 0
        for row in rows:
            identifier = _lineage_id(row)
            if identifier in seen:
                duplicate += 1
                continue
            seen.add(identifier)
            if identifier in excluded or identifier in confirmed:
                removed += 1
                removed_by_disjointness.append(identifier)
                continue

            slug = row.get("document_slug")
            if slug in collisions:
                unverified += 1
                unverifiable.append(
                    {
                        "lineage_id": identifier,
                        "manifest": rel(manifest),
                        "reason": (
                            "two documents in this manifest share the truncated "
                            f"cache slug {slug!r}, so one overwrote the other's "
                            "payload and neither can be attributed"
                        ),
                    }
                )
                continue

            before, before_why = _verify_side(row, "before")
            after, after_why = _verify_side(row, "after")
            if before is None or after is None:
                unverified += 1
                unverifiable.append(
                    {
                        "lineage_id": identifier,
                        "manifest": rel(manifest),
                        "reason": before_why or after_why or "unverifiable",
                    }
                )
                continue

            pairs.append(
                {
                    "lineage_id": identifier,
                    "family": row["family"],
                    "before_version": row["before_version"],
                    "after_version": row["after_version"],
                    "manifest": rel(manifest),
                    "before": before,
                    "after": after,
                }
            )
            kept += 1
        per_manifest.append(
            {
                "manifest": rel(manifest),
                "manifest_sha256": sha_file(manifest),
                "rows": len(rows),
                "kept": kept,
                "dropped_as_duplicate_of_an_earlier_manifest": duplicate,
                "dropped_as_not_disjoint": removed,
                "dropped_as_unverifiable": unverified,
            }
        )

    pairs.sort(key=lambda row: (row["lineage_id"], row["before_version"], row["after_version"]))
    selected = frozenset(row["lineage_id"] for row in pairs)

    overlap_538 = sorted(selected & excluded)
    overlap_14 = sorted(selected & confirmed)
    if overlap_538 or overlap_14:  # pragma: no cover -- the filter above removes them
        raise FreezeRefused(
            "disjointness violated after filtering, which means the filter and "
            f"the proof disagree: 538={overlap_538} confirmed14={overlap_14}"
        )
    if not pairs:
        raise FreezeRefused(
            "the frozen universe would be empty. A closure over zero pairs is "
            "vacuous and this protocol fails it rather than passing it."
        )

    families: dict[str, int] = {}
    for row in pairs:
        families[row["family"]] = families.get(row["family"], 0) + 1

    return {
        "schema": "tavonel.v2.identity_change_migration_closure.universe.v1",
        "protocol_id": protocol["protocol_id"],
        "selection_rule": protocol["cohort"]["selection_rule"],
        "path_taken": protocol["cohort"]["path_taken"],
        "candidate_manifests": per_manifest,
        "pair_count": len(pairs),
        "distinct_lineages": len(selected),
        "families": dict(sorted(families.items())),
        "disjointness": {
            "from_the_538_pair_retrospective_cohort": {
                "holds": True,
                "overlap": overlap_538,
                **excluded_meta,
            },
            "from_the_14_sfi2_forensic_cases": {
                "holds": True,
                "overlap": overlap_14,
                **confirmed_meta,
            },
            "lineages_removed_by_disjointness": sorted(set(removed_by_disjointness)),
        },
        "excluded_as_unverifiable": {
            "count": len(unverifiable),
            "rule": (
                "a pair whose cached payload does not match the manifest digest "
                "describing it, or whose cache slug is shared with another "
                "document, is excluded and named. The exclusion is a property of "
                "the bytes and the filename, never of any closure outcome."
            ),
            "rows": sorted(unverifiable, key=lambda row: row["lineage_id"]),
        },
        "sfi3": {
            "opened": False,
            "listed": False,
            "fetched": False,
            "note": (
                "no SFI3 artifact is read by this tool. Disjointness is proven "
                "against the 538-pair retrospective cohort, which is what the "
                "ruling requires; fresh SFI3 stays the prospective confirmatory "
                "evidence for the lane that owns it."
            ),
        },
        "network": "none",
        "universe_sha256": canonical_sha(
            [
                [row["lineage_id"], row["before"]["raw_sha256"], row["after"]["raw_sha256"]]
                for row in pairs
            ]
        ),
        "pairs": pairs,
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }


# --------------------------------------------------------------------------
# entry points
# --------------------------------------------------------------------------


def freeze_protocol(path: Path = PROTOCOL) -> dict[str, Any]:
    digest = sha_file(path)
    existing = protocol_freeze_receipt()
    if existing is not None:
        if existing.get("protocol_sha256") == digest:
            return {
                "state": "ALREADY_FROZEN",
                "receipt": existing["_receipt_path"],
                "protocol_sha256": digest,
            }
        raise FreezeRefused(
            "this protocol is already frozen at a different digest. Amending a "
            "frozen protocol needs its own receipt naming what it supersedes.\n"
            f"  frozen:  {existing.get('protocol_sha256')}\n  current: {digest}"
        )

    body = {
        "schema": "tavonel.v2.protocol_freeze.v2",
        "protocol_path": rel(path),
        "protocol_sha256": digest,
        "protocol_id": "IDENTITY_CHANGE_MIGRATION_CLOSURE_V1",
        "git_head": git_head(),
        "frozen_before_any_result": True,
        "frozen_before_any_cohort_pair_was_read": True,
        "what_this_seals": (
            "eight threshold-free structural acceptance criteria, the facet "
            "channel declaration, the empty predeclared-ignore declaration, the "
            "cohort selection rule and the fixture battery -- all before the "
            "universe is frozen and before any pair is measured"
        ),
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }
    written = write_immutable(PROTOCOL_STEM, body, tool=Path(__file__).resolve(), protocol=path)
    return {"state": "FROZEN", "protocol_sha256": digest, **written}


def freeze_universe() -> dict[str, Any]:
    receipt = require_frozen_protocol()
    protocol = load_protocol()
    body = build_universe(protocol)
    body["protocol_freeze_receipt"] = receipt["_receipt_path"]
    body["protocol_freeze_run_id"] = receipt["provenance"]["run_id"]
    body["protocol_sha256"] = receipt["protocol_sha256"]
    written = write_immutable(UNIVERSE_STEM, body, tool=Path(__file__).resolve(), protocol=PROTOCOL)
    return {
        "state": "FROZEN",
        "pair_count": body["pair_count"],
        "families": body["families"],
        "universe_sha256": body["universe_sha256"],
        **written,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("protocol", "universe"))
    args = parser.parse_args()

    try:
        result = freeze_protocol() if args.stage == "protocol" else freeze_universe()
    except FreezeRefused as error:
        print(json.dumps({"state": "REFUSED", "why": str(error)}, indent=1))
        return 4
    print(json.dumps(result, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
