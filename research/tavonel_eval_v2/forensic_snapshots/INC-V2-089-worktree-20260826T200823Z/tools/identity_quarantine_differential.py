#!/usr/bin/env python3
"""Rung 2 of the INC-V2-047 quarantine ladder: the same corpus, both ways.

`akc_cir.identity_quarantine` decides which units an unsettled identity decision
makes unsafe to classify, and `diff_documents` withholds a definite outcome from
each of them behind a pin:

    semantic_diff.QUARANTINE_UNSETTLED_IDENTITY_DEFAULT     module default
    diff_documents(..., quarantine_unsettled_identity=...)  per-call override

This tool runs the identity-sensitive projection of `diff_documents` over the
frozen development universe **twice per pair** -- once with the pin explicitly
OFF, once with it explicitly ON -- and reports the complete per-unit delta.

**Both pins are passed explicitly, never inherited.** The module default is
another lane's switch and can move underneath this tool at any time; a
differential that read it would silently become a comparison of one behaviour
with itself. The observed default is *recorded* in the receipt as an
observation, and is never what the measurement runs on.

**Four questions, and only two of them have a required answer.**

* *What changed classification, and how* -- reported as a transition table
  (`unit_removed -> identity_unresolved`, and so on). Descriptive. There is no
  expected count and none is invented here.
* *What is identical under both pins* -- reported with its denominator. This has
  to be the overwhelming majority; a differential that cannot show a large
  identical majority is not measuring the projection it claims to be measuring,
  because the repair touches only units an unsettled decision implicates. It is
  **reported, not gated**: no threshold in this repository is calibrated and a
  rate bar invented here would present an uncalibrated number as a measured one.
* *Did any unit gain a definite outcome it did not have under pin OFF* -- this
  **must be zero**. The quarantine only ever withholds; a unit that acquires
  `unit_added`, `unit_removed`, `modified_claim` or any other concrete record it
  did not have before means the repair is asserting something new rather than
  declining to assert something old. This is a property of the contract, not a
  rate, so it is gated.
* *Did any unit vanish from the diff entirely under pin ON* -- this **must be
  zero**. Withholding a false `unit_removed` and emitting nothing in its place
  replaces a false statement with no statement, which is the silent
  disappearance this programme keeps rediscovering under other names. Also a
  property, also gated.

The population is the universe frozen for
`IDENTITY_CHANGE_MIGRATION_CLOSURE_V1`, read through that closure's own
`universe_receipt()` so the refusal-without-a-freeze rule is inherited rather
than restated. **Nothing here rescores V1.** V1's FAIL is permanent; the
transitions this tool counts describe what the repair does to the same corpus.
They are not a repair of that verdict and not a denominator for it.

Usage::

    python tools/identity_quarantine_differential.py
    python tools/identity_quarantine_differential.py --limit 40
    python tools/identity_quarantine_differential.py --write-receipt
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
for _sub in ("tools", "acquisition", "canonicalization", "compiler", "source_fact_ir"):
    sys.path.insert(0, str(NS / _sub))
sys.path.insert(0, str(NS))
ROOT = NS.parents[1]
sys.path.insert(0, str(ROOT / "packages" / "cir-python" / "src"))

import selective_build as engine  # noqa: E402
from akc_cir import semantic_diff as sd  # noqa: E402
from akc_cir.identity import (  # noqa: E402
    LogicalIdentityResolver,
    LogicalMatch,
    assign_one_to_one,
)
from akc_cir.identity_quarantine import (  # noqa: E402
    DECLARED_CANDIDATE,
    LOGICAL_ID_COUNTERPART,
    MATCHED_TO_A_QUARANTINED_UNIT,
    SELECTED_CANDIDATE,
    build_quarantine,
)
from akc_cir.semantic_diff import (  # noqa: E402
    ChangeChannel,
    ChangeKind,
    DiffLevel,
    diff_documents,
)
from common import rel, sha_file  # noqa: E402
from evidence import write_immutable  # noqa: E402
from identity_change_migration_closure import universe_receipt  # noqa: E402

STEM = "identity-quarantine-differential"
SCHEMA = "tavonel.v2.identity_quarantine_differential.v1"
OUT_DIR = NS / "artifacts" / "development" / "identity_quarantine"

#: The Protected Core files whose behaviour this differential describes. Their
#: digests travel in the receipt so a reading can be tied to the exact code that
#: produced it -- both are being edited by another lane while this runs.
SUBJECT_FILES = (
    ROOT / "packages" / "cir-python" / "src" / "akc_cir" / "semantic_diff.py",
    ROOT / "packages" / "cir-python" / "src" / "akc_cir" / "identity_quarantine.py",
)

#: Every record kind that asserts something concrete about a unit: every
#: `ChangeKind` except `identity_unresolved` (the withholding channel) and
#: `content_unchanged` (which carries no logical id and cannot reach the
#: per-unit projection at all).
DEFINITE_KINDS = frozenset(
    kind.value
    for kind in ChangeKind
    if kind not in {ChangeKind.IDENTITY_UNRESOLVED, ChangeKind.CONTENT_UNCHANGED}
)


def projection(diff: Any) -> dict[str, frozenset[str]]:
    """Every record this diff carries, indexed by the unit it names.

    Deliberately not narrowed to the four kinds the closure calls
    identity-sensitive. A quarantined unit loses its whole matched-pair
    entourage -- `modified_claim`, and also the temporal, metadata, visual and
    graph records `diff_documents` emits only for a pair it matched -- so a
    projection that watched four kinds could report a unit as unchanged while
    several of its records had disappeared.

    Records with no `logical_id` (the structural channel) are counted
    separately by `_document_level`.
    """
    index: dict[str, set[str]] = {}
    for change in diff.changes:
        if change.logical_id:
            index.setdefault(change.logical_id, set()).add(change.kind.value)
    return {unit: frozenset(kinds) for unit, kinds in index.items()}


def _document_level(diff: Any) -> list[str]:
    return sorted(change.kind.value for change in diff.changes if not change.logical_id)


#: The four reasons `akc_cir.identity_quarantine` declares, read from the module
#: rather than restated. A reason that is edited there moves this reading with
#: it; a copy here would drift and report a vocabulary nobody emits any more.
QUARANTINE_REASONS = {
    "declared_candidate": DECLARED_CANDIDATE,
    "selected_candidate": SELECTED_CANDIDATE,
    "logical_id_counterpart": LOGICAL_ID_COUNTERPART,
    "matched_to_a_quarantined_unit": MATCHED_TO_A_QUARANTINED_UNIT,
}


def quarantine_membership(before_units: Any, after_units: Any, source: str) -> dict[str, int]:
    """Which CLAUSES of the contract this pair actually exercises.

    Reproduced from the same inputs `diff_documents` uses, because the diff does
    not expose the quarantine it built and the emitted-record counts below are
    **not** a substitute for it. A clause can be load-bearing and emit nothing:
    the INC-V2-047 member -- clause (3) -- suppresses a false `UNIT_REMOVED`
    while the record that makes it visible was already emitted by the AMBIGUOUS
    branch under the same id, so it never contributes a `detail` of its own.
    Reading the reason counts alone would report clause (3) as never firing on a
    corpus where it fires nine times, which is the exact reading error this
    ladder is being built to avoid.
    """
    decisions = assign_one_to_one(
        [item.fingerprint(source_lineage=source) for item in after_units],
        [item.fingerprint(source_lineage=source) for item in before_units],
        resolver=LogicalIdentityResolver(),
    )
    paired = list(zip(after_units, decisions, strict=True))
    quarantine = build_quarantine(
        unsettled_decisions=[
            (incoming.logical_id, decision.candidates, decision.logical_id)
            for incoming, decision in paired
            if decision.match is LogicalMatch.AMBIGUOUS
        ],
        definite_matches=[
            (incoming.logical_id, decision.logical_id)
            for incoming, decision in paired
            if decision.match is not LogicalMatch.AMBIGUOUS and decision.logical_id
        ],
        before_ids=frozenset(item.logical_id for item in before_units),
    )
    counts = {name: 0 for name in QUARANTINE_REASONS}
    counts["total_members"] = 0
    for member in quarantine.members.values():
        counts["total_members"] += 1
        for name, reason in QUARANTINE_REASONS.items():
            if member.reason == reason:
                counts[name] += 1
    return counts


def _quarantine_reason_counts(diff: Any) -> dict[str, int]:
    """How many unresolved records each declared quarantine reason produced.

    A record whose `detail` is one of the four constants was emitted by the
    quarantine path; one carrying a resolver band or tie reason was emitted by
    the pre-existing AMBIGUOUS branch. Counting them apart is how the canary can
    tell whether the repair is being exercised at all, which is this study's
    most-repeated defect: a check reporting clean because it is watching nothing.

    **Emission, not membership.** See `quarantine_membership` for why the two
    differ and why only the latter says which clauses fired.
    """
    counts = {name: 0 for name in QUARANTINE_REASONS}
    for change in diff.changes:
        if change.kind is not ChangeKind.IDENTITY_UNRESOLVED:
            continue
        for name, reason in QUARANTINE_REASONS.items():
            if change.detail == reason:
                counts[name] += 1
    return counts


def _kind_counts(diff: Any) -> dict[str, int]:
    """Records per kind. The differential's over-quarantine sentinel: a repair
    that withheld too much would show `unit_added` and `unit_removed` collapsing
    under pin ON, and a per-unit delta alone does not say how many survived.
    """
    counts: dict[str, int] = {}
    for change in diff.changes:
        counts[change.kind.value] = counts.get(change.kind.value, 0) + 1
    return counts


def _label(kinds: frozenset[str]) -> str:
    return "+".join(sorted(kinds)) if kinds else "<absent>"


def compare(off: Any, on: Any) -> dict[str, Any]:
    """One pair's complete delta between the two pins."""
    left = projection(off)
    right = projection(on)
    units = sorted(set(left) | set(right))

    identical: list[str] = []
    deltas: list[dict[str, Any]] = []
    gained_definite: list[dict[str, Any]] = []
    vanished: list[dict[str, Any]] = []
    transitions: dict[str, int] = {}

    for unit in units:
        before = left.get(unit, frozenset())
        after = right.get(unit, frozenset())
        if before == after:
            identical.append(unit)
            continue

        gained = sorted(after - before)
        lost = sorted(before - after)
        transition = f"{_label(before)} -> {_label(after)}"
        transitions[transition] = transitions.get(transition, 0) + 1
        deltas.append(
            {
                "logical_id": unit,
                "pin_off": sorted(before),
                "pin_on": sorted(after),
                "gained": gained,
                "lost": lost,
                "transition": transition,
            }
        )

        gained_definite_kinds = sorted(set(gained) & DEFINITE_KINDS)
        if gained_definite_kinds:
            gained_definite.append(
                {
                    "logical_id": unit,
                    "kinds": gained_definite_kinds,
                    "why": (
                        "the quarantine may only withhold; this unit acquired a "
                        "concrete record it did not carry before the repair"
                    ),
                }
            )
        if before and not after:
            vanished.append(
                {
                    "logical_id": unit,
                    "lost": lost,
                    "why": (
                        "the unit carried a record under pin OFF and carries none "
                        "under pin ON: a false statement replaced by no statement"
                    ),
                }
            )

    return {
        "kind_counts_pin_off": _kind_counts(off),
        "kind_counts_pin_on": _kind_counts(on),
        "quarantine_reason_counts_pin_off": _quarantine_reason_counts(off),
        "quarantine_reason_counts_pin_on": _quarantine_reason_counts(on),
        "units_compared": len(units),
        "units_identical": len(identical),
        "units_changed": len(deltas),
        "deltas": deltas,
        "transitions": transitions,
        "gained_a_definite_outcome": gained_definite,
        "vanished_under_pin_on": vanished,
        "document_level_records_pin_off": _document_level(off),
        "document_level_records_pin_on": _document_level(on),
        "document_level_records_identical": _document_level(off) == _document_level(on),
        "records_pin_off": len(off.changes),
        "records_pin_on": len(on.changes),
    }


def _withheld_without_a_statement(on: Any, delta: dict[str, Any]) -> list[dict[str, Any]]:
    """Units that lost a definite record under pin ON and were not restated.

    Weaker than `vanished_under_pin_on`, and reported beside it: a unit can keep
    *some* record while losing its definite one, and if what remains carries no
    `identity_unresolved` then the withholding was still silent about the thing
    that was withheld.
    """
    unresolved_ids = {
        change.logical_id
        for change in on.changes
        if change.kind is ChangeKind.IDENTITY_UNRESOLVED and change.logical_id
    }
    out: list[dict[str, Any]] = []
    for row in delta["deltas"]:
        lost_definite = sorted(set(row["lost"]) & DEFINITE_KINDS)
        if not lost_definite:
            continue
        if row["logical_id"] in unresolved_ids:
            continue
        out.append(
            {
                "logical_id": row["logical_id"],
                "lost": lost_definite,
                "remaining": row["pin_on"],
                "why": (
                    "a definite record was withheld and this unit carries no "
                    "identity_unresolved record of its own to say so"
                ),
            }
        )
    return out


def _unresolved_channel_escapes(on: Any) -> list[dict[str, Any]]:
    """Unresolved records that are not on the UNRESOLVED channel, or whose unit
    entered `changed_logical_ids` anyway.

    The first half is structural -- `_CHANGE_CHANNEL` maps the kind to the
    channel -- and the second is not: a unit carrying an `identity_unresolved`
    record *and* a `unit_added` enters the recompilation seed set regardless,
    which is INVARIANT_6's violation shape wearing the repair's clothes.
    """
    seeds = set(on.changed_logical_ids)
    out: list[dict[str, Any]] = []
    for change in on.unresolved:
        if change.channel is not ChangeChannel.UNRESOLVED:
            out.append(
                {
                    "logical_id": change.logical_id,
                    "why": "an identity_unresolved record is not on the UNRESOLVED channel",
                    "channel": change.channel.value,
                }
            )
        if change.logical_id and change.logical_id in seeds:
            out.append(
                {
                    "logical_id": change.logical_id,
                    "why": (
                        "an unsettled identity entered changed_logical_ids; it "
                        "must carry a semantic or graph record to do that, so "
                        "the unit is both unresolved and definitely classified"
                    ),
                }
            )
    return out


def measure_pair(before_document: dict[str, Any], after_document: dict[str, Any]) -> dict[str, Any]:
    before_units, before_shape = engine.snapshots(before_document)
    after_units, after_shape = engine.snapshots(after_document)

    def _diff(pin: bool) -> Any:
        return diff_documents(
            before_sha256=before_document["source_digest"],
            after_sha256=after_document["source_digest"],
            level=DiffLevel.GRAPH,
            before_shape=before_shape,
            after_shape=after_shape,
            before_units=before_units,
            after_units=after_units,
            source=after_document["source_id"],
            #: Explicit on both sides. Never `None`, which would read the module
            #: default and make one arm whatever the other lane's switch happens
            #: to say this minute.
            quarantine_unsettled_identity=pin,
        )

    off = _diff(False)
    on = _diff(True)
    row = compare(off, on)
    row["quarantine_membership"] = quarantine_membership(
        before_units, after_units, after_document["source_id"]
    )
    row["withheld_without_a_statement"] = _withheld_without_a_statement(on, row)
    row["unresolved_channel_escapes"] = _unresolved_channel_escapes(on)
    row["unresolved_records_pin_off"] = len(off.unresolved)
    row["unresolved_records_pin_on"] = len(on.unresolved)
    row["change_id_pin_off"] = off.change_id
    row["change_id_pin_on"] = on.change_id
    row["before_units"] = len(before_units)
    row["after_units"] = len(after_units)
    return row


def run(limit: int | None = None) -> dict[str, Any]:
    started = time.time()
    universe = universe_receipt()
    rows = universe["pairs"] if limit is None else universe["pairs"][:limit]

    pairs: list[dict[str, Any]] = []
    for row in rows:
        before_document = json.loads(
            (ROOT / row["before"]["canonical_path"]).read_text(encoding="utf-8")
        )
        after_document = json.loads(
            (ROOT / row["after"]["canonical_path"]).read_text(encoding="utf-8")
        )
        result = measure_pair(before_document, after_document)
        result["lineage_id"] = row["lineage_id"]
        result["family"] = row["family"]
        pairs.append(result)

    transitions: dict[str, int] = {}
    for row in pairs:
        for name, count in row["transitions"].items():
            transitions[name] = transitions.get(name, 0) + count

    def collect(key: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for row in pairs:
            for item in row[key]:
                out.append({"lineage_id": row["lineage_id"], **item})
        return out

    gained = collect("gained_a_definite_outcome")
    vanished = collect("vanished_under_pin_on")
    silent = collect("withheld_without_a_statement")
    escapes = collect("unresolved_channel_escapes")

    def kind_totals(key: str) -> dict[str, int]:
        out: dict[str, int] = {}
        for row in pairs:
            for kind, count in row[key].items():
                out[kind] = out.get(kind, 0) + count
        return dict(sorted(out.items()))

    kinds_off = kind_totals("kind_counts_pin_off")
    kinds_on = kind_totals("kind_counts_pin_on")
    reasons_off = kind_totals("quarantine_reason_counts_pin_off")
    reasons_on = kind_totals("quarantine_reason_counts_pin_on")
    membership = kind_totals("quarantine_membership")
    unexercised_clauses = sorted(
        name for name in QUARANTINE_REASONS if membership.get(name, 0) == 0
    )

    units_compared = sum(row["units_compared"] for row in pairs)
    units_identical = sum(row["units_identical"] for row in pairs)
    units_changed = sum(row["units_changed"] for row in pairs)

    #: Pre-repair reference check. If pin OFF stopped producing the INC-V2-047
    #: shape, the ON arm is not being compared against production behaviour and
    #: every number above is a comparison of the repair with itself.
    #:
    #: The membership test is `identity_unresolved` **present under pin ON**,
    #: not *gained*. In the INC-V2-047 shape the unresolved record is already
    #: there under pin OFF -- the diff carries both statements about one key, and
    #: that contradiction is the defect -- so a "gained" test finds none of the
    #: nine and reports the reference arm as healthy. It did, on the first run.
    removed_to_unresolved = [
        {"lineage_id": row["lineage_id"], "logical_id": item["logical_id"]}
        for row in pairs
        for item in row["deltas"]
        if "unit_removed" in item["lost"] and "identity_unresolved" in item["pin_on"]
    ]
    added_to_unresolved = [
        {"lineage_id": row["lineage_id"], "logical_id": item["logical_id"]}
        for row in pairs
        for item in row["deltas"]
        if "unit_added" in item["lost"] and "identity_unresolved" in item["pin_on"]
    ]

    document_level_drift = [
        {
            "lineage_id": row["lineage_id"],
            "pin_off": row["document_level_records_pin_off"],
            "pin_on": row["document_level_records_pin_on"],
        }
        for row in pairs
        if not row["document_level_records_identical"]
    ]

    properties = {
        "no_unit_gained_a_definite_outcome": {
            "why": "the quarantine only ever withholds",
            "violations": len(gained),
            "holds": not gained,
        },
        "no_unit_vanished_from_the_diff": {
            "why": "a withheld statement must be replaced by a stated one, never by nothing",
            "violations": len(vanished),
            "holds": not vanished,
        },
        "every_withheld_definite_record_is_restated_as_unresolved": {
            "why": (
                "the weaker half of the same rule: a unit that keeps some record "
                "while losing its definite one has still been silenced about the "
                "thing that was withheld"
            ),
            "violations": len(silent),
            "holds": not silent,
        },
        "no_unsettled_identity_is_also_definitely_classified": {
            "why": "an unresolved unit that reaches changed_logical_ids is both at once",
            "violations": len(escapes),
            "holds": not escapes,
        },
        "the_document_level_channel_is_untouched": {
            "why": "the repair is about units; a structural record must not move",
            "violations": len(document_level_drift),
            "holds": not document_level_drift,
        },
        "pin_off_still_reproduces_the_pre_repair_defect": {
            "why": (
                "the reference arm must still be production. If no unit_removed "
                "becomes unresolved anywhere, pin OFF is no longer the behaviour "
                "the repair is being compared against"
            ),
            "population_note": (
                "a property of the whole frozen universe. A --limit run truncates "
                "the population and can fail this honestly, which is why the "
                "canary re-runs the differential unlimited rather than reading a "
                "stored one"
            ),
            "limit": limit,
            "observed": len(removed_to_unresolved),
            "holds": bool(removed_to_unresolved),
        },
    }

    return {
        "schema": SCHEMA,
        "rung": "2 -- shadow / differential",
        "population": {
            "universe_freeze_receipt": universe["_receipt_path"],
            "universe_freeze_run_id": universe["provenance"]["run_id"],
            "universe_sha256": universe["universe_sha256"],
            "pairs_declared": universe["pair_count"],
            "pairs_measured": len(pairs),
            "limit": limit,
        },
        "subject_code": {
            "observed_module_default": sd.QUARANTINE_UNSETTLED_IDENTITY_DEFAULT,
            "observed_module_default_is_not_an_input": (
                "both arms pass quarantine_unsettled_identity explicitly; this "
                "value is recorded as an observation of the tree, not as an input"
            ),
            "files": {rel(path): sha_file(path) for path in SUBJECT_FILES},
        },
        "totals": {
            "units_compared": units_compared,
            "units_identical_under_both_pins": units_identical,
            "units_changed": units_changed,
            "identical_share_of_units_compared": (
                round(units_identical / units_compared, 6) if units_compared else None
            ),
            "pairs_with_any_delta": sum(1 for row in pairs if row["units_changed"]),
            "lineages_with_any_delta": sorted(
                {row["lineage_id"] for row in pairs if row["units_changed"]}
            ),
            "records_pin_off": sum(row["records_pin_off"] for row in pairs),
            "records_pin_on": sum(row["records_pin_on"] for row in pairs),
            "kind_counts_pin_off": kinds_off,
            "kind_counts_pin_on": kinds_on,
            "quarantine_reason_counts_pin_off": reasons_off,
            "quarantine_reason_counts_pin_on": reasons_on,
            "declared_quarantine_reasons": sorted(QUARANTINE_REASONS),
            "quarantine_membership_by_clause": membership,
            "clauses_never_exercised_on_this_corpus": unexercised_clauses,
            "clause_coverage_note": (
                "membership, not emission. A clause with members and zero emitted "
                "records is still load-bearing; a clause with zero MEMBERS was "
                "never exercised here and nothing in this run is evidence about it"
            ),
            "unresolved_records_pin_off": sum(row["unresolved_records_pin_off"] for row in pairs),
            "unresolved_records_pin_on": sum(row["unresolved_records_pin_on"] for row in pairs),
        },
        "reported_not_gated": {
            "why": (
                "no threshold in this repository is calibrated; a rate bar "
                "invented here would be an uncalibrated number presented as a "
                "measured one. The identical share is reported with its "
                "denominator and graded by nothing"
            ),
            "transitions": dict(sorted(transitions.items(), key=lambda item: -item[1])),
            "unit_removed_withheld_and_stated_unresolved": removed_to_unresolved,
            "unit_removed_withheld_lineages": sorted(
                {row["lineage_id"] for row in removed_to_unresolved}
            ),
            "unit_added_withheld_and_stated_unresolved": added_to_unresolved,
            "unit_added_withheld_lineages": sorted(
                {row["lineage_id"] for row in added_to_unresolved}
            ),
            "relationship_to_closure_v1": (
                "descriptive only. IDENTITY_CHANGE_MIGRATION_CLOSURE_V1 graded "
                "FAIL on INVARIANT_6 and that verdict is permanent. Nothing here "
                "rescores it, repairs it, or uses it as a denominator"
            ),
        },
        "properties": properties,
        "gated_on": sorted(properties),
        "violations": {
            "gained_a_definite_outcome": gained,
            "vanished_under_pin_on": vanished,
            "withheld_without_a_statement": silent,
            "unresolved_channel_escapes": escapes,
            "document_level_drift": document_level_drift,
        },
        "verdict": "PASS" if all(row["holds"] for row in properties.values()) else "FAIL",
        "wall_seconds": round(time.time() - started, 1),
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
        "pairs": pairs,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="pairs from the frozen universe")
    parser.add_argument("--write-receipt", action="store_true")
    args = parser.parse_args()

    report = run(args.limit)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    target = OUT_DIR / "differential.json"
    target.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")

    if args.write_receipt:
        report.update(write_immutable(STEM, report, tool=Path(__file__).resolve()))
        print("receipt:", report.get("receipt"))

    summary = {key: value for key, value in report.items() if key != "pairs"}
    print(json.dumps(summary, indent=1, ensure_ascii=False, default=str))
    print("written:", target)
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
