#!/usr/bin/env python3
"""Enumerate the candidate universe for a V2 identity-change migration closure.

The founder's ruling on INC-V2-047 is that V1's `overall: FAIL` stands
permanently: it is never repaired, never rescored, and never reused as a
positive closure denominator. A V2 closure therefore needs a NEW universe,
disjoint from everything V1 consumed. This tool finds that universe. It does
not freeze it -- the freeze is Lane D's machinery, which reads the manifest
written here -- and it does not measure it.

**Selection happens before any outcome could be known, and by construction.**
Nothing here imports `akc_cir`, calls a change predicate, or reads a closure
result. Every eligibility decision is a function of lineage identity, manifest
structure, a file path, and a sha256 of bytes on disk. Choosing a cohort by
looking at what it would produce is the defect this whole programme exists to
avoid, so the selection function is written so that it cannot: the result is
never in its scope.

The selection rule is V1's rule, unchanged, with a larger exclusion set. That is
deliberate. A rule invented for V2 would be a rule invented after V1's result
was known, and "the bound must be a predeclared property" is exactly what that
would not be. So: every development revision pair whose payloads are already
cached on local disk, taken in a fixed declared order, deduplicated by lineage
id keeping the first occurrence, then filtered by the exclusion table below. No
count is chosen. No subset is chosen.

What this adds to V1's rule, and why:

* **The cache-key collision detector is structural, not digest-driven.**
  INC-V2-046 found three P4i slug collisions because six digests failed. A
  collision whose members happen to verify would have passed unnoticed, and it
  is just as ambiguous. Here a collision is any raw payload path claimed by more
  than one distinct lineage -- the physical file that gets overwritten -- and,
  independently, any cache slug shared by two documents. Union of both
  detectors, and the ENTIRE group is excluded, never whichever member verifies.
* **A disjointness that cannot be proven is not assumed.** SFI3's Wikipedia
  roots are *categories*. Whether a given article is inside one cannot be
  decided without expanding the category, and expansion is forbidden. So that
  family is excluded and named, rather than assumed disjoint.
* **A lineage some identity measurement has already read is excluded.** P0's
  oracle-independence run, P0b's mechanics, P0c's coverage, P2's identity-policy
  arms and the identity-change benchmark all read identity outcomes on their
  lineages. The closure is an identity measurement; reusing a lineage whose
  identity behaviour is already visible would make selection an outcome.

**No SFI3 payload, expansion or acquisition artifact is opened.**
`acquisition/sources_sfi3.py` is imported for lineage identity metadata only --
`spent_lineages()` and the four root tuples. `artifacts/development/sfi3_lineages.json`
is neither read nor created, and the enumeration refuses to run if it exists.

Nothing immutable is written to, and no historical artifact is rewritten. Every
exclusion is recorded in the manifest this tool produces, never by editing spent
evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from functools import lru_cache
from itertools import pairwise
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "acquisition"))

# Identity metadata only; see the module docstring.
import sources_sfi3
from common import NS, ROOT, canonical_sha, git_head, rel, sha_file, write_hashed
from evidence import RECEIPTS, write_immutable
from freeze_migration_closure import (
    confirmed_defect_lineages,
    retrospective_lineage_ids,
)

RECEIPT_STEM = "identity-change-migration-closure-v2-universe-enumeration"

#: Where the freeze-ready manifest lands. A stable path, deterministically
#: rewritten on every run, so Lane D's freeze machinery has one thing to read.
#: It is NOT evidence and NOT frozen, and it says so in its own body.
MANIFEST_PATH = NS / "artifacts" / "development" / "v2_universe" / "v2_universe_candidates.json"

#: V1's protocol, cited by digest because the rule below is its rule. Never
#: written to and never amended here.
V1_PROTOCOL = NS / "protocols" / "IDENTITY_CHANGE_MIGRATION_CLOSURE_V1.yaml"
V1_UNIVERSE_STEM = "identity-change-migration-closure-universe"

SFI3_FRAME = NS / "artifacts" / "development" / "sfi3_lineages.json"

SELECTION_RULE = (
    "every development revision pair whose before and after payloads are already "
    "cached on local disk and whose canonical document is already written beside "
    "them, taken in the fixed declared manifest order, deduplicated by lineage id "
    "keeping the first occurrence, then filtered by the exclusion table. This is "
    "IDENTITY_CHANGE_MIGRATION_CLOSURE_V1's selection rule unchanged, with a "
    "larger exclusion set. No pair is selected by any property of its content and "
    "no pair is selected by any closure outcome: the selection function never "
    "calls either change predicate and never reads a closure result."
)

#: Exclusion categories in the order they are evaluated. A row is attributed to
#: the FIRST category that claims it, so the counts partition the drops and can
#: be added up. The order is data, not narrative: moving a line moves the counts.
EXCLUSION_ORDER: tuple[tuple[str, str], ...] = (
    (
        "NOT_A_NATURAL_REVISION_PAIR",
        "a constructed control or positive-control pair, not a real revision pair",
    ),
    (
        "DUPLICATE_LINEAGE_OF_AN_EARLIER_MANIFEST",
        "this lineage was already decided on its first occurrence in the declared order",
    ),
    (
        "V1_CLOSURE_LINEAGE",
        "one of the 514 lineages IDENTITY_CHANGE_MIGRATION_CLOSURE_V1 measured. Its "
        "closure outcome is visible and the founder's ruling forbids reuse",
    ),
    (
        "RETROSPECTIVE_538_COHORT",
        "one of the 538 pairs of the retrospective migration safety regression",
    ),
    (
        "SFI2_FORENSIC_14",
        "one of the 14 SFI2 E5-confirmed forensic diagnostic cases. A case used to "
        "diagnose a defect cannot certify its repair",
    ),
    (
        "SPENT_SFI1_SFI2_LINEAGE",
        "spent by a predecessor study -- SFH1, VBC2, SFI1's frame or executor, "
        "SFI2's frame or executor -- per sources_sfi3.spent_lineages()",
    ),
    (
        "IDENTITY_OUTCOME_ALREADY_MEASURED",
        "an identity or recompilation measurement has already read this lineage's "
        "identity outcomes (P0 oracle independence, P0b mechanics, P0c coverage, "
        "P2 identity-policy arms, or the identity-change benchmark). The closure is "
        "an identity measurement, so reusing the lineage would make selection an outcome",
    ),
    (
        "SFI3_ROOT_CONTAINER",
        "this lineage's container is one of SFI3's declared fresh roots. Proven from "
        "sources_sfi3 root identity metadata; no SFI3 artifact is opened",
    ),
    (
        "SFI3_DISJOINTNESS_UNPROVABLE_WITHOUT_EXPANSION",
        "SFI3's roots for this family are Wikipedia CATEGORIES. Whether an article is "
        "inside one cannot be decided without expanding the category, and expansion "
        "is forbidden. An unprovable disjointness is not an assumed one",
    ),
    (
        "CACHE_KEY_COLLISION_GROUP",
        "two or more distinct lineages write to the same cached payload path or share "
        "a truncated cache slug, so one overwrote the other. The ENTIRE group is "
        "excluded: nothing on disk says which member holds the right bytes, and "
        "keeping the one that still verifies is choosing the convenient reading of an "
        "ambiguity (INC-V2-046)",
    ),
    ("PAYLOAD_MISSING", "the cached raw payload named by the manifest is not on disk"),
    (
        "CANONICAL_MISSING",
        "no canonical document is on disk for this pair, so it is not usably cached",
    ),
    (
        "PAYLOAD_DIGEST_MISMATCH",
        "the cached raw payload no longer matches the digest the manifest recorded",
    ),
    (
        "CANONICAL_DIGEST_MISMATCH",
        "the canonical document matches neither the file digest nor the canonical-form "
        "digest the manifest recorded",
    ),
)
EXCLUSION_REASONS = dict(EXCLUSION_ORDER)

#: Families whose SFI3 roots are containers a lineage id can be tested against.
#: `git_docs` ids read `git:<owner>/<repo>:<path>` and `regulation_ecfr` ids read
#: `ecfr:<title>:<part>:<section>`, so both carry their container in the id.
#: `sec_edgar` is provable because SFI3 declares no SEC roots at all. Only
#: `encyclopedia_wikipedia` is not provable, and it gets its own category.
SFI3_UNPROVABLE_FAMILIES: frozenset[str] = frozenset({"encyclopedia_wikipedia"})

#: Studies that have already read identity outcomes on their lineages. Read for
#: lineage ids only. A glob resolves to its most recent match.
IDENTITY_MEASURED_SOURCES: tuple[tuple[str, str], ...] = (
    ("receipts/identity-change-migration-closure-universe--*.json", "pairs.lineage_id"),
    ("artifacts/development/identity_change_benchmark/benchmark.json", "pairs.lineage_id"),
    ("receipts/p0-canonicalisation-manifest.json", "pairs.source_id"),
    ("receipts/p0b-corpus-manifest.json", "pairs.source_id"),
    ("receipts/p0c-corpus-manifest--*.json", "pairs.source_id"),
    ("receipts/p2-lineage.json", "chains.source_id"),
)

#: Studies that have read a NON-identity outcome on their lineages. These do not
#: exclude; a survivor that appears here is not a never-measured lineage and the
#: manifest says so per pair. VBC1's probe declares itself burned in
#: `acquisition/sources_vbc1_probe.py`. Whether a burn taken for one question
#: reaches a different question is a founder decision, surfaced, never decided here.
UNRELATED_OUTCOME_SOURCES: tuple[tuple[str, str, str], ...] = (
    (
        "VBC1_VALUE_BEARING_PROBE",
        "artifacts/development/vbc1_probe_cohort.json",
        "documents.document_id",
    ),
    ("P4C_RETRIEVAL_VALIDITY", "receipts/p4c-cohort-manifest--*.json", "documents.document_id"),
)

#: How many members of an exclusion category are named inline in the receipt.
#: Every category also carries a canonical digest of its full sorted list, and
#: the manifest file carries every excluded row in full, so nothing is hidden by
#: this cap: it keeps a receipt readable, not a finding out of it.
NAMED_MEMBER_CAP = 200


class EnumerationRefused(RuntimeError):
    """A precondition of the enumeration is not met. Never worked around here."""


def _display(path: Path) -> str:
    """A path for a human, that never raises.

    `rel()` refuses a path outside the repository, and a refusal message that
    raises while explaining a refusal is a check that cannot report -- the shape
    this study keeps finding. So this falls back to the absolute path.
    """
    try:
        return rel(path)
    except ValueError:
        return str(path)


# --------------------------------------------------------------------------
# normalised candidate rows
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Side:
    raw_path: str
    raw_sha256_recorded: str | None
    canonical_path: str | None
    canonical_sha256_recorded: str | None


@dataclass(frozen=True)
class Candidate:
    lineage_id: str
    family: str
    before_version: str
    after_version: str
    manifest: str
    cache_slug: str | None
    natural: bool
    before: Side
    after: Side


def _sha_of(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


# --------------------------------------------------------------------------
# manifest adapters
#
# Three row shapes exist on disk and none can be read by the other two's code.
# They are adapted here rather than normalised on disk, because normalising on
# disk would mean rewriting spent artifacts.
# --------------------------------------------------------------------------


def _cohort_rows(manifest: Path) -> list[Candidate]:
    """P4c/P4e/P4g/P4i/VBC1-probe/VBC2 shape: `documents` carrying before/after."""
    body = json.loads(manifest.read_text(encoding="utf-8"))
    out: list[Candidate] = []
    for row in body.get("documents", ()):
        identifier = row.get("document_id") or row.get("lineage_id")
        if not identifier:
            raise EnumerationRefused(f"{rel(manifest)}: a row carries no lineage identity")
        sides = {}
        for side in ("before", "after"):
            entry = row[side]
            sides[side] = Side(
                raw_path=entry.get("raw_path", ""),
                raw_sha256_recorded=entry.get("raw_sha256"),
                canonical_path=entry.get("canonical_path"),
                canonical_sha256_recorded=entry.get("canonical_sha256"),
            )
        out.append(
            Candidate(
                lineage_id=str(identifier),
                family=row["family"],
                before_version=str(row["before_version"]),
                after_version=str(row["after_version"]),
                manifest=rel(manifest),
                cache_slug=row.get("document_slug"),
                natural=True,
                before=sides["before"],
                after=sides["after"],
            )
        )
    return out


def _p0_rows(manifest: Path, raw_index: dict[str, dict[str, Any]]) -> list[Candidate]:
    """P0/P0b/P0c shape: `pairs` keyed by `pair_id`, raw payload held elsewhere.

    The corpus manifests carry only the canonical side; the acquisition manifest
    carries the raw payload path and its digest. The join is by `pair_id`, and a
    pair with no raw row is emitted with an empty raw path so it is excluded and
    named rather than silently skipped.
    """
    body = json.loads(manifest.read_text(encoding="utf-8"))
    out: list[Candidate] = []
    for row in body.get("pairs", ()):
        pair_id = row["pair_id"]
        raw = raw_index.get(pair_id, {})
        natural = row.get("group") == "natural" and not row.get("constructed")
        sides = {}
        for side in ("before", "after"):
            canonical = row.get(side) or {}
            raw_side = raw.get(side) or {}
            sides[side] = Side(
                raw_path=raw_side.get("path", ""),
                raw_sha256_recorded=raw_side.get("sha256"),
                canonical_path=canonical.get("path"),
                canonical_sha256_recorded=canonical.get("canonical_sha256"),
            )
        out.append(
            Candidate(
                lineage_id=str(row["source_id"]),
                family=row["source_family"],
                before_version=str(row.get("before_version_id", "")),
                after_version=str(row.get("after_version_id", "")),
                manifest=rel(manifest),
                cache_slug=str(pair_id),
                natural=bool(natural),
                before=sides["before"],
                after=sides["after"],
            )
        )
    return out


def _chain_rows(manifest: Path) -> list[Candidate]:
    """P2 shape: `chains` of revisions. Each adjacent step is one revision pair.

    A chain is one lineage, so the lineage dedup admits at most one step per
    chain. That is not this adapter's decision, so every step is emitted and the
    dedup is left to say so in the counts.
    """
    body = json.loads(manifest.read_text(encoding="utf-8"))
    out: list[Candidate] = []
    for chain in body.get("chains", ()):
        revisions = list(chain.get("revisions", ()))
        for before, after in pairwise(revisions):
            out.append(
                Candidate(
                    lineage_id=str(chain["source_id"]),
                    family=chain["source_family"],
                    before_version=str(before["version_id"]),
                    after_version=str(after["version_id"]),
                    manifest=rel(manifest),
                    cache_slug=str(chain["chain_id"]),
                    natural=True,
                    before=Side(
                        raw_path=before.get("raw_path", ""),
                        raw_sha256_recorded=before.get("source_digest"),
                        canonical_path=before.get("canonical_path"),
                        canonical_sha256_recorded=before.get("canonical_sha256"),
                    ),
                    after=Side(
                        raw_path=after.get("raw_path", ""),
                        raw_sha256_recorded=after.get("source_digest"),
                        canonical_path=after.get("canonical_path"),
                        canonical_sha256_recorded=after.get("canonical_sha256"),
                    ),
                )
            )
    return out


def _p0_raw_index() -> dict[str, dict[str, Any]]:
    path = NS / "receipts" / "p0-acquisition-manifest.json"
    if not path.is_file():
        return {}
    body = json.loads(path.read_text(encoding="utf-8"))
    return {row["pair_id"]: row for row in body.get("pairs", ())}


#: The declared candidate order, fixed BEFORE any V2 eligibility was computed.
#: Order decides only which manifest a shared lineage is attributed to; it cannot
#: admit a lineage that a later manifest would have excluded, because every
#: exclusion below is a function of the lineage and its bytes, not of the
#: manifest. A superseded pass comes after the pass that supersedes it, so the
#: surviving row is the current one.
CANDIDATE_SOURCES: tuple[tuple[str, str], ...] = (
    ("artifacts/development/p4i_cohort.json", "cohort"),
    ("artifacts/development/p4g_cohort.json", "cohort"),
    ("artifacts/development/p4g_cohort_pass1.json", "cohort"),
    ("artifacts/development/p4e_cohort.json", "cohort"),
    ("receipts/p4c-cohort-manifest--*.json", "cohort"),
    ("artifacts/development/vbc2_cohorts/*.json", "cohort"),
    ("artifacts/development/vbc1_probe_cohort.json", "cohort"),
    ("artifacts/development/_dry_encyclopedia_wikipedia.json", "cohort"),
    ("receipts/p0c-corpus-manifest--*.json", "p0"),
    ("receipts/p0b-corpus-manifest.json", "p0"),
    ("receipts/p0-canonicalisation-manifest.json", "p0"),
    ("receipts/p2-chain-manifest.json", "chains"),
)


def resolve_sources(
    sources: Iterable[tuple[str, str]] = CANDIDATE_SOURCES,
) -> list[tuple[Path, str]]:
    resolved: list[tuple[Path, str]] = []
    for pattern, shape in sources:
        if "*" in pattern:
            resolved.extend((path, shape) for path in sorted(NS.glob(pattern)))
        else:
            target = NS / pattern
            if target.is_file():
                resolved.append((target, shape))
    return resolved


def read_candidates(resolved: list[tuple[Path, str]]) -> list[tuple[Path, list[Candidate]]]:
    raw_index = _p0_raw_index()
    out: list[tuple[Path, list[Candidate]]] = []
    for path, shape in resolved:
        if shape == "cohort":
            rows = _cohort_rows(path)
        elif shape == "p0":
            rows = _p0_rows(path, raw_index)
        elif shape == "chains":
            rows = _chain_rows(path)
        else:  # pragma: no cover -- CANDIDATE_SOURCES is a closed literal
            raise EnumerationRefused(f"unknown manifest shape {shape!r} for {rel(path)}")
        out.append((path, rows))
    return out


# --------------------------------------------------------------------------
# exclusion sets, all derived from lineage identity metadata
# --------------------------------------------------------------------------


def _pluck(body: Any, spec: str) -> set[str]:
    collection, field = spec.split(".", 1)
    rows = body.get(collection) or ()
    return {str(row[field]) for row in rows if row.get(field)}


def _ids_from(pattern: str, spec: str) -> set[str]:
    """Lineage ids out of one manifest. A glob resolves to its most recent match."""
    if "*" in pattern:
        matches = sorted(NS.glob(pattern))
        paths = matches[-1:] if matches else []
    else:
        target = NS / pattern
        paths = [target] if target.is_file() else []
    ids: set[str] = set()
    for path in paths:
        ids |= _pluck(json.loads(path.read_text(encoding="utf-8")), spec)
    return ids


def v1_closure_lineages() -> tuple[frozenset[str], dict[str, Any]]:
    """The 514 lineages V1 measured, from its own universe freeze receipt.

    Read for lineage ids only. V1's *result* is never opened here: the receipt
    carrying the FAIL is a different file and this tool does not name it.
    """
    runs = sorted(RECEIPTS.glob(f"{V1_UNIVERSE_STEM}--*.json"))
    if not runs:
        raise EnumerationRefused(
            "the V1 closure universe receipt is absent. Disjointness from the 514 "
            "cannot be proven against a cohort that is not on disk, and an "
            "unprovable disjointness is not an assumed one."
        )
    source = runs[-1]
    body = json.loads(source.read_text(encoding="utf-8"))
    ids = frozenset(str(row["lineage_id"]) for row in body["pairs"])
    return ids, {
        "source_receipt": rel(source),
        "source_receipt_sha256": sha_file(source),
        "distinct_lineages": len(ids),
        "read_for": "lineage identity only; no closure outcome is opened",
    }


#: V1's derivations of the 538-pair cohort and the 14 forensic cases, reused
#: rather than reimplemented -- a second derivation is a second thing to drift.
#: Cached only: the inputs are two large executor outputs that do not change
#: while this process runs, and re-reading them per call costs minutes in a test
#: suite for an answer that cannot have moved.
cached_retrospective_lineage_ids = lru_cache(maxsize=1)(retrospective_lineage_ids)
cached_confirmed_defect_lineages = lru_cache(maxsize=1)(confirmed_defect_lineages)


@lru_cache(maxsize=1)
def spent_sfi1_sfi2_lineages() -> frozenset[str]:
    """Every lineage a predecessor SFI/SFH/VBC study already looked at.

    Reused from `sources_sfi3`, never reimplemented: a second derivation of the
    spent set is a second thing to drift. Cached because the derivation reads
    two large executor outputs and the answer is a function of files that do not
    change while this process runs.
    """
    return frozenset(sources_sfi3.spent_lineages())


@lru_cache(maxsize=1)
def identity_measured_lineages() -> tuple[frozenset[str], dict[str, Any]]:
    ids: set[str] = set()
    sources: list[dict[str, Any]] = []
    for pattern, spec in IDENTITY_MEASURED_SOURCES:
        here = _ids_from(pattern, spec)
        ids |= here
        sources.append({"source": pattern, "field": spec, "distinct_lineages": len(here)})
    return frozenset(ids), {"sources": sources, "distinct_lineages": len(ids)}


def unrelated_outcome_lineages() -> tuple[dict[str, frozenset[str]], list[dict[str, Any]]]:
    table: dict[str, frozenset[str]] = {}
    meta: list[dict[str, Any]] = []
    for label, pattern, spec in UNRELATED_OUTCOME_SOURCES:
        here = frozenset(_ids_from(pattern, spec))
        table[label] = here
        meta.append({"study": label, "source": pattern, "distinct_lineages": len(here)})
    return table, meta


def sfi3_root_containers() -> tuple[frozenset[str], frozenset[tuple[str, str]], dict[str, Any]]:
    """SFI3's declared fresh roots as containers a lineage id can be tested on.

    Identity metadata only: four literal tuples in `sources_sfi3`. No root is
    expanded, no listing is fetched, and no SFI3 artifact is opened.
    """
    git_roots = frozenset(f"{root['owner']}/{root['repo']}" for root in sources_sfi3.GIT_ROOTS)
    ecfr_roots = frozenset((str(title), str(part)) for title, part, _ in sources_sfi3.ECFR_ROOTS)
    meta = {
        "git_repositories": len(git_roots),
        "ecfr_title_parts": len(ecfr_roots),
        "wikipedia_category_roots": len(sources_sfi3.WIKIPEDIA_CATEGORY_ROOTS),
        "sec_roots": len(sources_sfi3.SEC_ROOTS),
        "read_for": (
            "root identity metadata only; no root is expanded and no SFI3 artifact is opened"
        ),
        "wikipedia_note": (
            "Wikipedia roots are categories, so article membership is not decidable from "
            "metadata. The family is excluded rather than assumed disjoint."
        ),
        "sec_note": (
            "SFI3 declares no SEC roots, so every sec_edgar lineage is provably disjoint "
            "from SFI3 by the empty set."
        ),
    }
    return git_roots, ecfr_roots, meta


def under_sfi3_root(
    lineage_id: str, git_roots: frozenset[str], ecfr_roots: frozenset[tuple[str, str]]
) -> bool:
    if lineage_id.startswith("git:"):
        container = lineage_id[len("git:") :].split(":", 1)[0]
        return container in git_roots
    if lineage_id.startswith("ecfr:"):
        parts = lineage_id.split(":")
        if len(parts) >= 3:
            return (parts[1], parts[2]) in ecfr_roots
    return False


# --------------------------------------------------------------------------
# cache-key collisions -- structural, not digest-driven
# --------------------------------------------------------------------------


def collision_groups(rows: Iterable[Candidate]) -> dict[str, dict[str, Any]]:
    """Every lineage whose cached bytes cannot be attributed, and why.

    Two independent detectors, unioned:

    * **payload path** -- the physical file that gets overwritten. If two
      distinct lineages name the same raw path, one wrote over the other and the
      manifest records the first's digest beside the second's bytes. This is the
      detector INC-V2-046 needed and did not have: it fires on the collision
      itself, before any digest is recomputed, so a collision whose members
      happen to verify is caught too.
    * **cache slug** -- the truncated `document_slug`. Kept as a second reading
      so a collision survives a change in how paths are spelled.

    The ENTIRE group is excluded, never whichever member verifies. Nothing on
    disk says which member holds the right bytes; keeping the verifying one is
    choosing the convenient reading of an ambiguity.
    """
    by_path: dict[str, set[str]] = {}
    by_slug: dict[str, set[str]] = {}
    for row in rows:
        for side in (row.before, row.after):
            if side.raw_path:
                by_path.setdefault(side.raw_path, set()).add(row.lineage_id)
        if row.cache_slug:
            by_slug.setdefault(row.cache_slug, set()).add(row.lineage_id)

    excluded: dict[str, dict[str, Any]] = {}
    for detector, table in (("payload_path", by_path), ("cache_slug", by_slug)):
        for key, members in table.items():
            if len(members) < 2:
                continue
            for lineage in members:
                entry = excluded.setdefault(lineage, {"lineage_id": lineage, "collisions": []})
                entry["collisions"].append(
                    {
                        "detector": detector,
                        "key": key,
                        "group": sorted(members),
                        "group_size": len(members),
                    }
                )
    for entry in excluded.values():
        entry["collisions"].sort(key=lambda item: (item["detector"], item["key"]))
    return excluded


def collision_group_index(collisions: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """The distinct collision groups, deduplicated, for the receipt."""
    seen: set[tuple[str, str, tuple[str, ...]]] = set()
    for entry in collisions.values():
        for item in entry["collisions"]:
            seen.add((item["detector"], item["key"], tuple(item["group"])))
    return [
        {"detector": detector, "key": key, "group": list(group), "group_size": len(group)}
        for detector, key, group in sorted(seen)
    ]


# --------------------------------------------------------------------------
# payload verification
# --------------------------------------------------------------------------


def verify_side(side: Side) -> tuple[dict[str, Any] | None, str | None]:
    """Recompute this side's raw and canonical digests against the manifest.

    Returns `(entry, None)` when both verify and `(None, category)` when they do
    not, where the category is one of EXCLUSION_ORDER's names so the caller never
    invents a reason.

    Two canonical digest conventions exist on disk and both are accepted: the
    sha256 of the file's bytes (P0, P2) and the canonical-form sha256 of the
    parsed document (P4c). Which one matched is recorded. A recorded digest that
    matches neither is a mismatch; an absent recorded digest is recorded as
    absent and the computed value is carried, never invented.
    """
    if not side.raw_path:
        return None, "PAYLOAD_MISSING"
    raw = ROOT / side.raw_path
    if not raw.is_file():
        return None, "PAYLOAD_MISSING"
    if not side.canonical_path:
        return None, "CANONICAL_MISSING"
    canonical = ROOT / side.canonical_path
    if not canonical.is_file():
        return None, "CANONICAL_MISSING"

    raw_digest = _sha_of(raw)
    if side.raw_sha256_recorded and raw_digest != side.raw_sha256_recorded:
        return None, "PAYLOAD_DIGEST_MISMATCH"

    canonical_file_digest = _sha_of(canonical)
    canonical_form_digest = canonical_sha(json.loads(canonical.read_text(encoding="utf-8")))
    convention: str | None = None
    if side.canonical_sha256_recorded:
        if side.canonical_sha256_recorded == canonical_file_digest:
            convention = "file_bytes"
        elif side.canonical_sha256_recorded == canonical_form_digest:
            convention = "canonical_form"
        else:
            return None, "CANONICAL_DIGEST_MISMATCH"

    return {
        "raw_path": side.raw_path,
        "raw_sha256": raw_digest,
        "raw_sha256_recorded": side.raw_sha256_recorded,
        "canonical_path": side.canonical_path,
        "canonical_file_sha256": canonical_file_digest,
        "canonical_form_sha256": canonical_form_digest,
        "canonical_sha256_recorded": side.canonical_sha256_recorded,
        "canonical_digest_convention": convention,
    }, None


# --------------------------------------------------------------------------
# the enumeration
# --------------------------------------------------------------------------


def enumerate_universe(
    sources: Iterable[tuple[str, str]] = CANDIDATE_SOURCES,
    *,
    reader: Callable[[list[tuple[Path, str]]], list[tuple[Path, list[Candidate]]]] | None = None,
) -> dict[str, Any]:
    """Select, prove disjoint, verify. No closure measurement happens here."""
    if SFI3_FRAME.exists():
        raise EnumerationRefused(
            f"{_display(SFI3_FRAME)} exists. This tool runs while SFI3 is unacquired and "
            "must not be the thing that made it exist."
        )

    resolved = resolve_sources(sources)
    if not resolved:
        raise EnumerationRefused("no declared candidate manifest is on disk")
    per_source = (reader or read_candidates)(resolved)

    v1_ids, v1_meta = v1_closure_lineages()
    retro_ids, retro_meta = cached_retrospective_lineage_ids()
    forensic_ids, forensic_meta = cached_confirmed_defect_lineages()
    spent_ids = spent_sfi1_sfi2_lineages()
    identity_ids, identity_meta = identity_measured_lineages()
    unrelated_table, unrelated_meta = unrelated_outcome_lineages()
    git_roots, ecfr_roots, sfi3_meta = sfi3_root_containers()

    every_row = [row for _, rows in per_source for row in rows]
    collisions = collision_groups(every_row)

    def category_for(row: Candidate, seen: set[str]) -> str | None:
        if not row.natural:
            return "NOT_A_NATURAL_REVISION_PAIR"
        if row.lineage_id in seen:
            return "DUPLICATE_LINEAGE_OF_AN_EARLIER_MANIFEST"
        if row.lineage_id in v1_ids:
            return "V1_CLOSURE_LINEAGE"
        if row.lineage_id in retro_ids:
            return "RETROSPECTIVE_538_COHORT"
        if row.lineage_id in forensic_ids:
            return "SFI2_FORENSIC_14"
        if row.lineage_id in spent_ids:
            return "SPENT_SFI1_SFI2_LINEAGE"
        if row.lineage_id in identity_ids:
            return "IDENTITY_OUTCOME_ALREADY_MEASURED"
        if under_sfi3_root(row.lineage_id, git_roots, ecfr_roots):
            return "SFI3_ROOT_CONTAINER"
        if row.family in SFI3_UNPROVABLE_FAMILIES:
            return "SFI3_DISJOINTNESS_UNPROVABLE_WITHOUT_EXPANSION"
        if row.lineage_id in collisions:
            return "CACHE_KEY_COLLISION_GROUP"
        return None

    seen: set[str] = set()
    eligible: list[dict[str, Any]] = []
    excluded_rows: list[dict[str, Any]] = []
    per_manifest: list[dict[str, Any]] = []

    for path, rows in per_source:
        counts: dict[str, int] = {}
        kept = 0
        for row in rows:
            category = category_for(row, seen)
            if category != "DUPLICATE_LINEAGE_OF_AN_EARLIER_MANIFEST":
                seen.add(row.lineage_id)
            if category is None:
                before, before_why = verify_side(row.before)
                after, after_why = verify_side(row.after)
                category = before_why or after_why
                if category is None:
                    measured_by = sorted(
                        label for label, ids in unrelated_table.items() if row.lineage_id in ids
                    )
                    eligible.append(
                        {
                            "lineage_id": row.lineage_id,
                            "family": row.family,
                            "before_version": row.before_version,
                            "after_version": row.after_version,
                            "manifest": row.manifest,
                            "cache_slug": row.cache_slug,
                            "outcome_visibility": (
                                "OUTCOME_VISIBLE_IN_ANOTHER_MEASUREMENT"
                                if measured_by
                                else "NEVER_MEASURED"
                            ),
                            "measured_by": measured_by,
                            "before": before,
                            "after": after,
                        }
                    )
                    kept += 1
                    continue
            counts[category] = counts.get(category, 0) + 1
            excluded_rows.append(
                {
                    "lineage_id": row.lineage_id,
                    "family": row.family,
                    "manifest": row.manifest,
                    "category": category,
                    "reason": EXCLUSION_REASONS[category],
                    **(
                        {"collision": collisions[row.lineage_id]["collisions"]}
                        if category == "CACHE_KEY_COLLISION_GROUP"
                        else {}
                    ),
                }
            )
        per_manifest.append(
            {
                "manifest": rel(path),
                "manifest_sha256": sha_file(path),
                "rows": len(rows),
                # A chain manifest carries many rows per lineage and a cohort
                # manifest carries one, so `rows` alone reads as more material
                # than there is. Both are recorded.
                "distinct_lineages": len({row.lineage_id for row in rows}),
                "kept": kept,
                "excluded_by_category": dict(sorted(counts.items())),
            }
        )

    eligible.sort(key=lambda row: (row["lineage_id"], row["before_version"], row["after_version"]))
    selected = frozenset(row["lineage_id"] for row in eligible)

    disjointness = _disjointness_proof(
        selected,
        {
            "from_the_514_v1_closure_lineages": (v1_ids, v1_meta),
            "from_the_538_pair_retrospective_cohort": (retro_ids, retro_meta),
            "from_the_14_sfi2_forensic_cases": (forensic_ids, forensic_meta),
            "from_the_spent_sfi1_sfi2_lineages": (
                spent_ids,
                {
                    "derived_by": "acquisition/sources_sfi3.spent_lineages()",
                    "sources": list(sources_sfi3.SPENT_SOURCES),
                    "distinct_lineages": len(spent_ids),
                    "read_for": "lineage identity only",
                },
            ),
            "from_lineages_an_identity_measurement_already_read": (identity_ids, identity_meta),
        },
    )
    sfi3_proof = _sfi3_proof(eligible, git_roots, ecfr_roots, sfi3_meta)
    if not sfi3_proof["holds"]:  # pragma: no cover -- the filter above removes them
        raise EnumerationRefused(
            "SFI3 disjointness violated after filtering, which means the filter and "
            f"the proof disagree: {sfi3_proof['overlap']}"
        )
    if not disjointness["all_hold"]:  # pragma: no cover -- the filter above removes them
        raise EnumerationRefused(
            "disjointness violated after filtering, which means the filter and the "
            "proof disagree. This is refused rather than reported."
        )

    by_category: dict[str, list[str]] = {}
    for row in excluded_rows:
        by_category.setdefault(row["category"], []).append(row["lineage_id"])

    families: dict[str, int] = {}
    visibility: dict[str, int] = {}
    for row in eligible:
        families[row["family"]] = families.get(row["family"], 0) + 1
        visibility[row["outcome_visibility"]] = visibility.get(row["outcome_visibility"], 0) + 1

    return {
        "schema": "tavonel.v2.identity_change_migration_closure.v2_universe_enumeration.v1",
        "is_evidence": False,
        "is_frozen": False,
        "what_this_is": (
            "an enumeration of what is AVAILABLE for a V2 closure. It is not a freeze, "
            "it is not a protocol, and it grades nothing. The freeze is Lane D's "
            "machinery and reads this file."
        ),
        "derived_from_protocol": rel(V1_PROTOCOL),
        "derived_from_protocol_sha256": sha_file(V1_PROTOCOL),
        "selection_rule": SELECTION_RULE,
        "selection_declared_before_any_v2_result_existed": True,
        "candidate_sources_in_declared_order": [pattern for pattern, _ in CANDIDATE_SOURCES],
        "candidate_manifests": per_manifest,
        "exclusion_categories": [
            _category_report(name, reason, by_category.get(name, []))
            for name, reason in EXCLUSION_ORDER
        ],
        "cache_integrity": {
            "rule": (
                "every raw and canonical digest is recomputed for every candidate side. "
                "A collision is detected structurally, by payload path and by cache "
                "slug, before any digest is checked, and the ENTIRE collision group is "
                "excluded -- never whichever member verifies (INC-V2-046)."
            ),
            "collision_lineages": len(collisions),
            "collision_groups": collision_group_index(collisions),
            "historical_artifacts_rewritten": False,
        },
        "disjointness": disjointness,
        "sfi3": sfi3_proof,
        "outcome_visibility_sources": unrelated_meta,
        "pair_count": len(eligible),
        "distinct_lineages": len(selected),
        "families": dict(sorted(families.items())),
        "outcome_visibility": dict(sorted(visibility.items())),
        "findings": findings_for(eligible, visibility),
        "sufficiency": {
            "verdict": "FOUNDER_RULING_REQUIRED",
            "why": (
                "no numerical sufficiency threshold was declared before this "
                "enumeration existed, so none is applied to it. A floor chosen now "
                "would be a floor chosen after the count was known, which is what the "
                "ruling on the 1.10% over-fire delta forbids. The counts and the power "
                "arithmetic are reported; the ruling is not an agent's call."
            ),
        },
        "universe_sha256": canonical_sha(
            [
                [row["lineage_id"], row["before"]["raw_sha256"], row["after"]["raw_sha256"]]
                for row in eligible
            ]
        ),
        "pairs": eligible,
        "excluded": sorted(
            excluded_rows, key=lambda row: (row["category"], row["lineage_id"], row["manifest"])
        ),
        "network": "none",
        "git_head": git_head(),
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }


def _category_report(name: str, reason: str, members: list[str]) -> dict[str, Any]:
    distinct = sorted(set(members))
    return {
        "category": name,
        "reason": reason,
        "rows": len(members),
        "distinct_lineages": len(distinct),
        "lineages_digest": canonical_sha(distinct),
        "lineages": (
            distinct
            if len(distinct) <= NAMED_MEMBER_CAP
            else f"{len(distinct)} lineages; every one is named in the manifest file"
        ),
    }


def _disjointness_proof(
    selected: frozenset[str], sets: dict[str, tuple[frozenset[str], dict[str, Any]]]
) -> dict[str, Any]:
    proof: dict[str, Any] = {}
    for label, (ids, meta) in sets.items():
        overlap = sorted(selected & ids)
        proof[label] = {"holds": not overlap, "overlap": overlap, **meta}
    proof["all_hold"] = all(entry["holds"] for entry in proof.values())
    return proof


def _sfi3_proof(
    eligible: list[dict[str, Any]],
    git_roots: frozenset[str],
    ecfr_roots: frozenset[tuple[str, str]],
    meta: dict[str, Any],
) -> dict[str, Any]:
    overlap = sorted(
        row["lineage_id"]
        for row in eligible
        if under_sfi3_root(row["lineage_id"], git_roots, ecfr_roots)
        or row["family"] in SFI3_UNPROVABLE_FAMILIES
    )
    return {
        "holds": not overlap,
        "overlap": overlap,
        "payload_opened": False,
        "expansion_opened": False,
        "acquisition_artifact_opened": False,
        "frame_exists": SFI3_FRAME.exists(),
        "roots": meta,
    }


#: The rate INC-V2-047 already published: INVARIANT_6 violated on 8 of the 514
#: lineages V1 measured. Literals, not read from any closure receipt, and used
#: only by `findings_for`, which runs after selection has returned its pair list.
V1_VIOLATED_LINEAGES = 8
V1_LINEAGES = 514


def findings_for(
    eligible: list[dict[str, Any]], visibility: dict[str, int]
) -> list[dict[str, Any]]:
    """Explicit findings. An empty universe is one of them, never a clean result.

    Called after `enumerate_universe` has finished selecting. Nothing here is
    read by `category_for`, so the power arithmetic below cannot be, and is not,
    an input to selection.
    """
    findings: list[dict[str, Any]] = []
    if not eligible:
        findings.append(
            {
                "code": "NO_ELIGIBLE_MATERIAL",
                "severity": "BLOCKING",
                "detail": (
                    "no disjoint real-development revision pair remains on disk. A "
                    "closure over zero pairs is vacuous. This is reported as a "
                    "shortfall for the founder to rule on; it is NOT a clean empty "
                    "result, and no cohort is manufactured to avoid it."
                ),
            }
        )
        return findings

    if not visibility.get("NEVER_MEASURED"):
        findings.append(
            {
                "code": "NO_NEVER_MEASURED_MATERIAL",
                "severity": "RULING_REQUIRED",
                "detail": (
                    "every eligible lineage has already been read by some other study's "
                    "measurement, none of them an identity measurement. Whether a burn "
                    "taken for one question reaches a different question is a decision "
                    "about what counts as evidence, which the constitution reserves to "
                    "the founder. It is surfaced here rather than decided."
                ),
                "affected_pairs": len(eligible),
            }
        )
    rate = V1_VIOLATED_LINEAGES / V1_LINEAGES
    detect = 1.0 - (1.0 - rate) ** len(eligible)
    findings.append(
        {
            "code": "EMPIRICAL_POWER_NOTE",
            "severity": "INFORMATIONAL",
            "detail": (
                "at the INVARIANT_6 violation rate INC-V2-047 published (8 violated "
                f"lineages of 514), a cohort of {len(eligible)} pairs has P(at least one "
                f"violation observed) = {detect:.3f}. A PASS on it is weak evidence of "
                "repair, not strong evidence. This describes the cohort's power, is "
                "computed after selection was complete, and selected nothing."
            ),
            "eligible_pairs": len(eligible),
            "v1_violated_lineages": V1_VIOLATED_LINEAGES,
            "v1_lineages": V1_LINEAGES,
            "probability_of_observing_at_least_one": round(detect, 6),
        }
    )
    return findings


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------


def write_manifest(body: dict[str, Any], path: Path | None = None) -> str:
    # Resolved at call time, not at def time: a default bound at import cannot be
    # redirected, and a path that cannot be redirected cannot be tested.
    return write_hashed(path or MANIFEST_PATH, dict(body), "manifest_sha256")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Enumerate the V2 closure candidate universe.")
    parser.add_argument(
        "--no-receipt",
        action="store_true",
        help="write the manifest only; a dry read does not need an immutable receipt",
    )
    args = parser.parse_args(argv)

    try:
        body = enumerate_universe()
    except EnumerationRefused as error:
        print(json.dumps({"state": "REFUSED", "why": str(error)}, indent=1))
        return 4

    manifest_digest = write_manifest(body)
    summary = {
        "state": "ENUMERATED",
        "manifest": _display(MANIFEST_PATH),
        "manifest_sha256": manifest_digest,
        "pair_count": body["pair_count"],
        "families": body["families"],
        "outcome_visibility": body["outcome_visibility"],
        "universe_sha256": body["universe_sha256"],
        "findings": [finding["code"] for finding in body["findings"]],
        "sufficiency": body["sufficiency"]["verdict"],
    }

    if not args.no_receipt:
        receipt_body = {key: value for key, value in body.items() if key != "excluded"}
        receipt_body["excluded_rows_live_in"] = _display(MANIFEST_PATH)
        receipt_body["manifest_path"] = _display(MANIFEST_PATH)
        receipt_body["manifest_sha256"] = manifest_digest
        summary.update(
            write_immutable(
                RECEIPT_STEM, receipt_body, tool=Path(__file__).resolve(), protocol=None
            )
        )

    print(json.dumps(summary, indent=1, sort_keys=True))
    if any(finding["severity"] == "BLOCKING" for finding in body["findings"]):
        return 5
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
