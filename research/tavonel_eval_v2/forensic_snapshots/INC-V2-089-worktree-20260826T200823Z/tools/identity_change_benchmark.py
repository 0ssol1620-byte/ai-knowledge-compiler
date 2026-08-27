#!/usr/bin/env python3
"""Corpus-scale identity-regression benchmark for the INC-V2-037 predicate switch.

Rung 4 of `docs/COMPAT_IDENTITY_CHANGE_SEPARATION.md`. The control that rung 3
shipped was two hand-built pairs, which is a fixture, not a benchmark: it can
show the new predicate behaves as designed on cases chosen to show that, and it
cannot say what the switch costs on revision history nobody picked.

This tool measures the switch on **real revision pairs already on disk**. The
SFI1 and SFI2 acquisition artifacts carry 538 admitted before/after pairs
between them, and both content-addressed payload caches are present. Nothing
here touches the network: a payload that is not cached is reported as an
unresolved pair, never fetched and never silently dropped from a denominator.

**What is measured, on every pair that resolves:**

* *identity continuity* -- the set of `UNIT_ADDED` / `UNIT_REMOVED` /
  `IDENTITY_UNRESOLVED` / `EVIDENCE_MOVED` records under the old predicate,
  against the same set under the new one. This is the regression risk the
  founder named: a change predicate must not disturb which units *match*. It
  is preserved by construction -- the predicate runs strictly downstream of
  `assign_one_to_one` and its verdict never re-enters matching -- and this
  measurement is a check on that construction rather than independent evidence
  for it. A non-zero count here means the construction is wrong.
* *over-fire* -- units the old predicate called unchanged that the new one
  calls changed, with the full nine-facet verdict from
  `source_fact_ir/change_facets.py` recorded for each, and a mechanical
  classification of *what kind* of textual difference it was, so the count can
  be read rather than only counted. A sample is written out in full for hand
  inspection.
* *under-fire* -- anything the old predicate caught that the new one misses.
  Expected zero, and expected zero for a reason rather than by luck: NFKC
  factors through NFC, so two texts with equal NFC forms have equal identity
  folds, so the new predicate's `unchanged` is a strict subset of the old
  one's. Measured anyway, because a proof that is not checked against the
  corpus is a proof about a different program.

**A large over-fire count is a finding, not a reason to loosen the predicate.**
The over-fire number this tool reports is the price of the fix, stated. It is
not a threshold to tune against, and nothing here adjusts the predicate.

**The 14 SFI2 confirmed cases are development regression fixtures.** This tool
covers the whole admitted cohort, not those 14, and nothing it produces may
re-score SFI2 or widen its cohort. It writes under
`artifacts/development/identity_change_benchmark/` and touches no receipt.

Usage::

    python tools/identity_change_benchmark.py            # whole corpus
    python tools/identity_change_benchmark.py --limit 40 # a quick slice
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import unicodedata
import urllib.parse
from collections import Counter
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
for _sub in ("tools", "acquisition", "canonicalization", "compiler", "source_fact_ir"):
    sys.path.insert(0, str(NS / _sub))
sys.path.insert(0, str(NS))
ROOT = NS.parents[1]
sys.path.insert(0, str(ROOT / "packages" / "cir-python" / "src"))

import change_facets as facets  # noqa: E402
import selective_build as engine  # noqa: E402
from akc_cir.identity import (  # noqa: E402
    LogicalIdentityResolver,
    LogicalMatch,
    assign_one_to_one,
)
from akc_cir.semantic_diff import ChangeKind, DiffLevel, diff_documents  # noqa: E402
from payload_cache import PayloadCache  # noqa: E402
from provenance_document import provenance_document  # noqa: E402

SCHEMA = "tavonel.v2.identity_change_benchmark.v1"

from evidence import write_immutable  # noqa: E402

STEM = "identity-change-benchmark"
OUT_DIR = NS / "artifacts" / "development" / "identity_change_benchmark"

#: The two acquisition cohorts whose payload caches are present in this
#: checkout, each paired with the lineage table that carries the per-family
#: fields (`owner`/`repo`/`path`, `title`/`part`/`identifier`, `article`) the
#: URL builders below need. Neither cohort is re-scored by anything here.
COHORTS: tuple[tuple[str, Path, Path, Path], ...] = (
    (
        "sfi1",
        NS / "artifacts" / "development" / "sfi1" / "sfi1_acquisition.json",
        NS / "artifacts" / "development" / "sfi1_lineages.json",
        NS / "artifacts" / "development" / "sfi1_cache",
    ),
    (
        "sfi2",
        NS / "artifacts" / "development" / "sfi2" / "sfi2_acquisition.json",
        NS / "artifacts" / "development" / "sfi2_lineages.json",
        NS / "artifacts" / "development" / "sfi2_cache",
    ),
)

#: The change kinds whose presence would mean *matching* moved, as opposed to
#: the change verdict on an already-matched pair moving. `EVIDENCE_MOVED` is in
#: here because it is emitted per matched pair: if a unit stopped matching, its
#: locator record disappears with it.
IDENTITY_SENSITIVE_KINDS = frozenset(
    {
        ChangeKind.UNIT_ADDED,
        ChangeKind.UNIT_REMOVED,
        ChangeKind.IDENTITY_UNRESOLVED,
        ChangeKind.EVIDENCE_MOVED,
    }
)


#: The frozen SFI2 receipt the 14 E5-confirmed selective stale escapes are read
#: from, for cross-reference only. An "over-fire" here is defined mechanically
#: -- the old predicate said unchanged, the new one says changed -- and that
#: definition cannot tell the defect being *fixed* from the predicate firing
#: where it should not. The 14 confirmed cases are exactly the pairs already
#: adjudicated as changes that must not vanish, so separating them out is the
#: difference between "the fix costs 28 new firings" and "14 of the 28 are what
#: the fix is for". Read-only, and nothing here re-scores SFI2 or widens it.
RECEIPTS = NS / "receipts"


def confirmed_defect_lineages() -> tuple[list[str], dict[str, Any]]:
    candidates = sorted(RECEIPTS.glob("sfi2-native-provenance--*.json"))
    if not candidates:
        return [], {"available": False, "why": "no sfi2-native-provenance receipt present"}
    source = candidates[-1]
    body = json.loads(source.read_text(encoding="utf-8"))
    confirmed = body["rebuild"]["E5_confirmed_selective_stale_escape"]["confirmed"]
    return (
        sorted({row["lineage_id"] for row in confirmed}),
        {
            "available": True,
            "source_receipt": source.name,
            "source_receipt_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "confirmed_count": len(confirmed),
        },
    )


class CacheMiss(RuntimeError):
    """A revision this pair needs is not in the local content-addressed cache."""


class UnsupportedFamily(RuntimeError):
    """A lineage family this tool has no cache-only URL builder for."""


# --------------------------------------------------------------------------
# cache-only payload lookup
#
# The URLs below mirror `tools/run_vbc2_acquire.py`'s construction exactly, so
# a cache hit is looked up under the key acquisition wrote it under. They are
# not imported from there: that module enumerates revisions over the network to
# build them, and this tool must not reach the network at all.
# --------------------------------------------------------------------------


def _git_url(lineage: dict[str, Any], version: str) -> str:
    return "https://raw.githubusercontent.com/%s/%s/%s/%s" % (
        lineage["owner"],
        lineage["repo"],
        version,
        lineage["path"],
    )


def _ecfr_url(lineage: dict[str, Any], version: str) -> str:
    return "https://www.ecfr.gov/api/versioner/v1/full/%s/title-%s.xml?part=%s&section=%s" % (
        version,
        lineage["title"],
        lineage["part"],
        lineage["identifier"],
    )


def _wikipedia_url(lineage: dict[str, Any], version: str) -> str:
    del lineage  # the oldid alone identifies the revision
    return (
        "https://en.wikipedia.org/w/api.php?action=parse&oldid=%s"
        "&prop=text&format=json&formatversion=2" % version
    )


URL_BUILDERS = {
    "git_docs": _git_url,
    "regulation_ecfr": _ecfr_url,
    "encyclopedia_wikipedia": _wikipedia_url,
}


def fetch_payload(cache: PayloadCache, lineage: dict[str, Any], version: str) -> bytes:
    family = lineage["family"]
    builder = URL_BUILDERS.get(family)
    if builder is None:
        raise UnsupportedFamily(
            "no cache-only URL builder for family %r (lineage %r)" % (family, lineage["lineage_id"])
        )
    url = builder(lineage, version)

    def _refuse(_url: str) -> bytes:
        raise CacheMiss("%r @ %r is not cached: %s" % (lineage["lineage_id"], version, url))

    body, _digest = cache.payload(url, _refuse)
    return body


def build_document(lineage: dict[str, Any], version: str, raw: bytes) -> dict[str, Any]:
    return provenance_document(
        source_family=lineage["family"],
        source_id=lineage["lineage_id"],
        version_id=version,
        payload=raw,
        source_digest="sha256:" + hashlib.sha256(raw).hexdigest(),
        known_at=None,
        valid_from=None,
        licence=lineage.get("licence", "unknown"),
    )


# --------------------------------------------------------------------------
# describing an over-fire so a human can read the count
# --------------------------------------------------------------------------

_DIFFERENCE_CLASSES: tuple[tuple[str, Any], ...] = (
    (
        "nfkc_compatibility_only",
        lambda a, b: unicodedata.normalize("NFKC", a) == unicodedata.normalize("NFKC", b),
    ),
    ("case_only", lambda a, b: a.casefold() == b.casefold()),
    ("whitespace_only", lambda a, b: a.split() == b.split()),
)


def classify_difference(before: str, after: str) -> str:
    """A mechanical name for *how* two texts differ, first match wins.

    Order matters and is declared: a pair that is both NFKC-equal and
    case-equal is reported under the first class it satisfies, so the classes
    partition the over-fires rather than double-counting them. `other` is the
    honest bucket for a difference none of the narrow classes explains -- it is
    where a genuine wording edit lands, and it is deliberately not named
    "semantic", because this function reads codepoints and cannot tell.
    """
    for name, predicate in _DIFFERENCE_CLASSES:
        if predicate(before, after):
            return name
    return "other"


#: `diff_documents`'s stand-in source id when a caller does not name one. This
#: tool always names one, so the constant is here only to keep the matching
#: reproduction below honest about what it is reproducing.
_DIFF_SCOPE_LINEAGE = "<diff-scope>"


def matched_pairs(
    before_units: list[Any], after_units: list[Any], source: str
) -> list[tuple[Any, Any]]:
    """The (counterpart, incoming) pairs `diff_documents` decides MODIFIED_CLAIM on.

    Reproduced here rather than read off the change records because a
    `MODIFIED_CLAIM` names `counterpart.logical_id` -- the *before*-side stable
    id -- and the resolver is free to match it to an incoming unit whose own
    `logical_id` differs. Looking the incoming unit up by the reported id
    therefore misses it, which is how the first run of this tool produced one
    over-fire it could not give a facet account for.

    This is a reproduction of `diff_documents`' matching, not a second
    implementation of it: the same `assign_one_to_one` over the same
    fingerprints with the same lineage, so a divergence would be a bug here and
    not a difference of policy. The pairs it yields are used for the denominator
    and the facet breakdown only; the predicate comparison itself always runs
    through the real `diff_documents`.
    """
    lineage = source or _DIFF_SCOPE_LINEAGE
    engine_ = LogicalIdentityResolver()
    by_logical = {unit.logical_id: unit for unit in before_units}
    decisions = assign_one_to_one(
        [unit.fingerprint(source_lineage=lineage) for unit in after_units],
        [unit.fingerprint(source_lineage=lineage) for unit in before_units],
        resolver=engine_,
    )
    pairs: list[tuple[Any, Any]] = []
    for incoming, decision in zip(after_units, decisions, strict=True):
        if decision.match in (LogicalMatch.AMBIGUOUS, LogicalMatch.NEW):
            continue
        counterpart = by_logical.get(decision.logical_id or "")
        if counterpart is None:
            continue
        pairs.append((counterpart, incoming))
    return pairs


def _modified_ids(diff: Any) -> set[str]:
    return {
        change.logical_id
        for change in diff.changes
        if change.kind is ChangeKind.MODIFIED_CLAIM and change.logical_id
    }


def _identity_records(diff: Any) -> list[dict[str, object]]:
    return [
        change.as_record() for change in diff.changes if change.kind in IDENTITY_SENSITIVE_KINDS
    ]


def measure_pair(
    lineage: dict[str, Any], row: dict[str, Any], cache: PayloadCache
) -> dict[str, Any]:
    """One admitted revision pair, old predicate against new, same inputs."""
    result: dict[str, Any] = {
        "lineage_id": row["lineage_id"],
        "family": lineage["family"],
        "before_version": row["before_version"],
        "after_version": row["after_version"],
        "resolved": False,
    }
    try:
        before_raw = fetch_payload(cache, lineage, row["before_version"])
        after_raw = fetch_payload(cache, lineage, row["after_version"])
    except (CacheMiss, UnsupportedFamily) as error:
        result["unresolved_reason"] = "%s: %s" % (type(error).__name__, error)
        return result

    before = build_document(lineage, row["before_version"], before_raw)
    after = build_document(lineage, row["after_version"], after_raw)

    before_units, before_shape = engine.snapshots(before)
    after_units, after_shape = engine.snapshots(after)

    def _diff(legacy: bool) -> Any:
        return diff_documents(
            before_sha256=before["source_digest"],
            after_sha256=after["source_digest"],
            level=DiffLevel.SEMANTIC,
            before_shape=before_shape,
            after_shape=after_shape,
            before_units=before_units,
            after_units=after_units,
            source=after["source_id"],
            legacy_identity_change_predicate=legacy,
        )

    old = _diff(True)
    new = _diff(False)

    old_modified = _modified_ids(old)
    new_modified = _modified_ids(new)

    pairs = matched_pairs(before_units, after_units, after["source_id"])
    pair_by_counterpart = {
        counterpart.logical_id: (counterpart, incoming) for counterpart, incoming in pairs
    }

    over_fires: list[dict[str, Any]] = []
    for logical_id in sorted(new_modified - old_modified):
        pair = pair_by_counterpart.get(logical_id)
        if pair is None:
            # A MODIFIED_CLAIM names a matched pair by construction, so this
            # cannot happen unless the reproduction above has drifted from
            # `diff_documents`. Recorded rather than skipped so a drift shows
            # up as a number instead of disappearing from the breakdown.
            over_fires.append(
                {"logical_id": logical_id, "anomaly": "no matched pair reproduced for this id"}
            )
            continue
        old_unit, new_unit = pair
        verdicts = facets.change_facets(old_unit, new_unit)
        over_fires.append(
            {
                "logical_id": logical_id,
                "difference_class": classify_difference(old_unit.text, new_unit.text),
                "changed_facets": list(facets.facets_with_verdict(verdicts, facets.CHANGED)),
                "unresolved_facets": list(facets.facets_with_verdict(verdicts, facets.UNRESOLVED)),
                "before": old_unit.text,
                "after": new_unit.text,
            }
        )

    result.update(
        {
            "resolved": True,
            "before_unit_count": len(before_units),
            "after_unit_count": len(after_units),
            # The denominator for the over-fire rate: pairs the identity layer
            # actually matched, which is the only population either predicate
            # is ever asked about. Units added, removed or left unsettled are
            # decided elsewhere and are not in it.
            "matched_pair_count": len(pairs),
            "old_modified_count": len(old_modified),
            "new_modified_count": len(new_modified),
            "over_fire_ids": sorted(new_modified - old_modified),
            "under_fire_ids": sorted(old_modified - new_modified),
            "over_fires": over_fires,
            # Identity continuity: byte-identical non-content change records
            # means matching, additions, removals, unsettled identities and
            # locator movement all landed exactly where they landed before.
            "identity_records_agree": _identity_records(old) == _identity_records(new),
            "unresolved_identity_count": len(old.unresolved),
            "unit_added_count": sum(1 for c in new.changes if c.kind is ChangeKind.UNIT_ADDED),
            "unit_removed_count": sum(1 for c in new.changes if c.kind is ChangeKind.UNIT_REMOVED),
        }
    )
    return result


def summarise(
    rows: list[dict[str, Any]], confirmed: frozenset[str] = frozenset()
) -> dict[str, Any]:
    resolved = [row for row in rows if row["resolved"]]
    unresolved = [row for row in rows if not row["resolved"]]

    difference_classes: Counter[str] = Counter()
    changed_facets: Counter[str] = Counter()
    unresolved_facets: Counter[str] = Counter()
    for row in resolved:
        for over in row["over_fires"]:
            if "difference_class" not in over:
                continue
            difference_classes[over["difference_class"]] += 1
            for facet in over["changed_facets"]:
                changed_facets[facet] += 1
            for facet in over["unresolved_facets"]:
                unresolved_facets[facet] += 1

    over_fire_units = sum(len(row["over_fire_ids"]) for row in resolved)
    under_fire_units = sum(len(row["under_fire_ids"]) for row in resolved)
    matched_pairs_total = sum(row["matched_pair_count"] for row in resolved)
    return {
        "pairs_considered": len(rows),
        "pairs_resolved": len(resolved),
        "pairs_unresolved": len(unresolved),
        "unresolved_reasons": Counter(
            row["unresolved_reason"].split(":", 1)[0] for row in unresolved
        ),
        "units_before_total": sum(row["before_unit_count"] for row in resolved),
        "units_after_total": sum(row["after_unit_count"] for row in resolved),
        "matched_pairs_total": matched_pairs_total,
        "old_modified_total": sum(row["old_modified_count"] for row in resolved),
        "new_modified_total": sum(row["new_modified_count"] for row in resolved),
        "over_fire_units": over_fire_units,
        "under_fire_units": under_fire_units,
        # Every rate carries its denominator, per the project constitution.
        "over_fire_rate_over_matched_pairs": (
            round(over_fire_units / matched_pairs_total, 6) if matched_pairs_total else None
        ),
        "under_fire_rate_over_matched_pairs": (
            round(under_fire_units / matched_pairs_total, 6) if matched_pairs_total else None
        ),
        "over_fire_denominator": matched_pairs_total,
        "pairs_with_any_over_fire": sum(1 for row in resolved if row["over_fire_ids"]),
        "pairs_with_any_under_fire": sum(1 for row in resolved if row["under_fire_ids"]),
        "identity_records_disagree_pairs": sum(
            1 for row in resolved if not row["identity_records_agree"]
        ),
        # How many of the mechanical over-fires are the INC-V2-037 defect being
        # fixed, rather than the new predicate firing somewhere it should not.
        "over_fires_on_confirmed_defect_lineages": sum(
            len(row["over_fire_ids"]) for row in resolved if row["lineage_id"] in confirmed
        ),
        "confirmed_defect_lineages_with_an_over_fire": sorted(
            {
                row["lineage_id"]
                for row in resolved
                if row["over_fire_ids"] and row["lineage_id"] in confirmed
            }
        ),
        "over_fire_difference_classes": dict(difference_classes.most_common()),
        "over_fire_changed_facets": dict(changed_facets.most_common()),
        "over_fire_unresolved_facets": dict(unresolved_facets.most_common()),
    }


def run(limit: int | None = None) -> dict[str, Any]:
    started = time.time()
    rows: list[dict[str, Any]] = []
    per_cohort: dict[str, Any] = {}
    confirmed_list, confirmed_meta = confirmed_defect_lineages()
    confirmed = frozenset(confirmed_list)

    for name, acquisition_path, lineages_path, cache_root in COHORTS:
        if not acquisition_path.exists() or not lineages_path.exists():
            per_cohort[name] = {"skipped": "acquisition or lineage artifact absent"}
            continue
        admitted = json.loads(acquisition_path.read_text(encoding="utf-8"))["admitted"]
        lineages = {
            row["lineage_id"]: row
            for row in json.loads(lineages_path.read_text(encoding="utf-8"))["lineages"]
        }
        cache = PayloadCache(cache_root, extractor_digest="identity-change-benchmark")

        cohort_rows: list[dict[str, Any]] = []
        for row in admitted if limit is None else admitted[:limit]:
            lineage = lineages.get(row["lineage_id"])
            if lineage is None:
                cohort_rows.append(
                    {
                        "lineage_id": row["lineage_id"],
                        "family": row.get("family", "?"),
                        "before_version": row["before_version"],
                        "after_version": row["after_version"],
                        "resolved": False,
                        "unresolved_reason": "LineageMissing: not in the frozen lineage table",
                    }
                )
                continue
            cohort_rows.append(measure_pair(lineage, row, cache))
        for entry in cohort_rows:
            entry["cohort"] = name
        rows.extend(cohort_rows)
        per_cohort[name] = summarise(cohort_rows, confirmed)

    report = {
        "schema": SCHEMA,
        "what_this_is": (
            "old (identity-fold) vs new (CONTENT-facet) MODIFIED_CLAIM predicate, "
            "measured on real admitted revision pairs from the local caches, no network"
        ),
        "facet_contract": facets.SCHEMA,
        "limit": limit,
        "overall": summarise(rows, confirmed),
        "confirmed_defect_reference": {**confirmed_meta, "lineages": confirmed_list},
        "per_cohort": per_cohort,
        "wall_seconds": round(time.time() - started, 1),
        "pairs": rows,
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="pairs per cohort")
    parser.add_argument("--write-receipt", action="store_true")
    parser.add_argument(
        "--sample",
        type=int,
        default=25,
        help="how many over-fires to write to the hand-inspection sample",
    )
    args = parser.parse_args()

    report = run(args.limit)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    target = OUT_DIR / "benchmark.json"
    target.write_text(
        json.dumps(report, indent=1, ensure_ascii=False, sort_keys=False),
        encoding="utf-8",
    )

    sample = []
    for row in report["pairs"]:
        for over in row.get("over_fires", []):
            sample.append({"lineage_id": row["lineage_id"], **over})
            if len(sample) >= args.sample:
                break
        if len(sample) >= args.sample:
            break
    (OUT_DIR / "over_fire_sample.json").write_text(
        json.dumps(sample, indent=1, ensure_ascii=False), encoding="utf-8"
    )

    #: The rung, pinned. `benchmark.json` is rewritten by the next run; a gate
    #: that read it could not tell which run it was reading.
    if args.write_receipt:
        pinned = {
            "schema": "tavonel.v2.identity_change_benchmark.v1",
            "overall": report["overall"],
            "per_cohort": report["per_cohort"],
            "gpu_seconds": 0,
            "estimated_cost_usd": 0.0,
        }
        pinned.update(write_immutable(STEM, pinned, tool=Path(__file__).resolve()))
        print("receipt:", pinned.get("receipt"))

    print(json.dumps(report["overall"], indent=1, default=str))
    print("per-cohort:", json.dumps(report["per_cohort"], indent=1, default=str))
    print("written:", target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
