#!/usr/bin/env python3
"""Select SFIR7's fifty roots by streaming, and freeze the whole chain.

`frame.select_top_n` holds the entire universe in memory. Thirty-seven million
projected records do not fit, so this driver streams -- but it must produce
exactly what `select_top_n` would have produced, or the frozen roster is not the
roster the declared rule selects.

**It reuses the rule's own code rather than reimplementing it.** The same
`_evaluate`, applied in the same declared order, and the same `_ranking_key`. A
second implementation of an eligibility test is a second thing that can be
subtly different, and the difference would show up as a roster that is entirely
plausible and not the declared one. `test_streaming_selection_equals_select_top_n`
runs both over the same records and requires identical output.

**Only the top N are retained.** A bounded max-heap of size N, so memory is a
function of N and not of the catalogue. Dispositions are tallied by reason rather
than kept per record, for the same reason.

**Ties are refused, not resolved.** The ranking key ends in the catalogue's own
record id, and the audit proved those unique and strictly increasing across all
37.6M parsed rows, so a tie the tie-breaker cannot settle should be impossible.
"Should be impossible" is exactly the claim this programme has learned to check
rather than assume, so it is checked.
"""

from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import sfir7_catalog_parser as catalog_parser  # noqa: E402
import sfir7_frame as frame  # noqa: E402
import sfir7_projection as projection  # noqa: E402

SCHEMA = "tavonel.sfir7.roster_freeze.v1"
PROTOCOL_ID = "SOURCE_FACT_IR_INDEPENDENT_REPLICATION_V7"

#: Every artifact whose bytes decide what the roster is. A freeze that pins the
#: roster without pinning what produced it records a conclusion and not a
#: derivation.
FREEZE_CHAIN_MODULES = (
    "tools/sfir7_catalog_parser.py",
    "tools/sfir7_projection.py",
    "tools/sfir7_frame.py",
    "tools/sfir7_select_roster.py",
    "tools/sfir7_acquire_catalog.py",
    "tools/sfir7_ranged_fetch.py",
    "tools/sfir7_catalog_vocabulary.py",
    "tools/sfir7_projection_audit.py",
)

FREEZE_CHAIN_RECEIPTS = (
    "receipts/sfir7-catalog-snapshot.json",
    "receipts/sfir7-catalog-vocabulary.json",
    "receipts/sfir7-projection-audit.json",
)

FREEZE_CHAIN_PROTOCOLS = (
    "protocols/SOURCE_FACT_IR_INDEPENDENT_REPLICATION_V7_DESIGN_CHARTER.yaml",
)


class SelectionRefused(RuntimeError):
    """The roster could not be established as the one the declared rule selects."""


def _sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def stream_select(
    catalog: Path,
    rule: frame.FrameRule,
    *,
    progress_rows: int = 2_000_000,
) -> dict[str, Any]:
    """Apply the declared rule by streaming, keeping only the best N."""
    frame.assert_capacity_blind(rule)
    n = frame.refuse_count_tuned_rule(rule)

    heap: list[tuple[Any, int, frame.FrameCatalogRecord, projection.ProvenanceSidecar]] = []
    counter = 0
    dispositions: Counter[str] = Counter()
    parser_rejections: Counter[str] = Counter()
    projection_refusals = 0
    rows = 0
    eligible = 0
    started = time.monotonic()

    for record, reason in catalog_parser.stream_records(catalog):
        rows += 1
        if rows % progress_rows == 0:
            print(f"    {rows:,} rows in {time.monotonic() - started:.0f}s", flush=True)
        if record is None:
            parser_rejections[reason] += 1
            continue
        try:
            projected, sidecar = projection.project(record)
        except projection.ProjectionRefused:
            projection_refusals += 1
            continue

        verdict = "ELIGIBLE"
        for predicate in rule.predicates:
            if not frame._evaluate(predicate, projected):
                verdict = f"REJECTED_{predicate.field}_{predicate.op}"
                break
        dispositions[verdict] += 1
        if verdict != "ELIGIBLE":
            continue
        eligible += 1

        key = frame._ranking_key(projected, rule)
        # A max-heap over the ranking key, so the worst of the retained N is at
        # the top and is what gets displaced. `counter` never breaks a tie that
        # matters -- the key already ends in the unique record id -- it only
        # keeps heapq from comparing dataclasses when keys are equal.
        counter += 1
        entry = (_Inverted(key), counter, projected, sidecar)
        if len(heap) < n:
            heapq.heappush(heap, entry)
        else:
            heapq.heappushpop(heap, entry)

    ordered = sorted(
        (item[2] for item in heap), key=lambda record: frame._ranking_key(record, rule)
    )
    sidecars = {item[2].record_id: item[3] for item in heap}
    _require_distinct_keys(ordered, rule)

    return {
        "rows_read": rows,
        "parser_rejections": dict(sorted(parser_rejections.items())),
        "projection_refusals": projection_refusals,
        "dispositions": dict(sorted(dispositions.items())),
        "eligible_count": eligible,
        "n": n,
        "selected": ordered,
        "sidecars": [sidecars[record.record_id] for record in ordered],
        "selection_is_short": eligible < n,
        "wall_clock_seconds": round(time.monotonic() - started, 3),
    }


class _Inverted:
    """Reverse a ranking key's order so `heapq`'s min-heap behaves as a max-heap."""

    __slots__ = ("key",)

    def __init__(self, key: Any) -> None:
        self.key = key

    def __lt__(self, other: _Inverted) -> bool:
        return other.key < self.key

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _Inverted) and other.key == self.key

    def __hash__(self) -> int:  # pragma: no cover - not used as a key
        return hash(self.key)


def require_tie_breaker_proven_unique(rule: frame.FrameRule, audit: dict[str, Any]) -> dict:
    """Establish the strict total order that streaming cannot check pairwise.

    `select_top_n` calls `assert_strict_total_order` over every eligible record.
    Streaming cannot: holding a ranking key per eligible row is the memory this
    driver exists to avoid. The property is not dropped, it is *derived*.

    The ranking key ends in the rule's tie-breaker, so if the tie-breaker is
    unique across the universe then no two full keys can be equal, whatever the
    ranking fields do. The projection audit measured exactly that over all
    37,662,659 parsed rows before any selection existed.

    Both halves are checked, and each goes red alone: that the audit really
    reports zero duplicates, and that the field it proved unique is the field
    this rule actually ranks on. Changing `tie_breaker` to a non-unique field
    must refuse here rather than quietly fall back to iteration order.
    """
    if rule.tie_breaker != "record_id":
        raise SelectionRefused(
            f"the audit proved uniqueness of record_id, but this rule breaks ties on "
            f"{rule.tie_breaker!r}. An inherited proof does not transfer to a different field."
        )
    measured = audit.get("record_id", {})
    duplicates = measured.get("duplicates")
    distinct = measured.get("distinct")
    parsed = audit.get("rows_parsed")
    if duplicates != 0 or not distinct or distinct != parsed:
        raise SelectionRefused(
            f"the projection audit does not establish tie-breaker uniqueness: "
            f"duplicates={duplicates!r}, distinct={distinct!r}, rows_parsed={parsed!r}. "
            "Without it the ranking key is not a strict total order and the roster "
            "would be settled by iteration order."
        )
    return {
        "tie_breaker": rule.tie_breaker,
        "proven_unique_over_rows": parsed,
        "duplicates_measured": duplicates,
        "why_this_replaces_the_pairwise_assertion": (
            "the ranking key ends in the tie-breaker, so a unique tie-breaker makes "
            "every full key unique. Measured over the whole universe before any "
            "selection existed, not assumed."
        ),
    }


def _require_distinct_keys(
    records: list[frame.FrameCatalogRecord], rule: frame.FrameRule
) -> None:
    """A tie the tie-breaker cannot settle is refused, never resolved arbitrarily."""
    keys = [frame._ranking_key(record, rule) for record in records]
    if len(set(keys)) != len(keys):
        duplicated = [key for key, count in Counter(keys).items() if count > 1]
        raise SelectionRefused(
            f"{len(duplicated)} ranking key(s) are not unique among the selected roots, "
            f"e.g. {duplicated[:3]}. Two roots the declared order cannot separate would "
            "be split by iteration order, which is not a rule."
        )


def build_freeze(
    root: Path,
    catalog: Path,
    result: dict[str, Any],
    rule: frame.FrameRule,
    snapshot_receipt: dict[str, Any],
    generated_at: str,
) -> dict[str, Any]:
    selected = result["selected"]
    sidecars = result["sidecars"]
    coherence = projection.require_identity_coherence(sidecars)

    roster = [
        {
            "rank_position": position,
            "record_id": record.record_id,
            "name_with_owner": sidecar.name_with_owner,
            "host_uuid": sidecar.host_uuid,
            "namespace": record.namespace,
            "name": record.name,
            "catalog_rank_value": record.catalog_rank_value,
            "spdx_license_id_as_published": record.spdx_license_id,
            "primary_language": record.primary_language,
            "created_utc": record.created_utc,
            "last_activity_utc": record.last_activity_utc,
            "fork": sidecar.fork,
            "status": sidecar.status,
        }
        for position, (record, sidecar) in enumerate(zip(selected, sidecars, strict=True), 1)
    ]
    roster_payload = json.dumps(roster, sort_keys=True, separators=(",", ":")).encode()
    sidecar_payload = json.dumps(
        [
            {
                "record_id": s.record_id,
                "name_with_owner": s.name_with_owner,
                "host_uuid": s.host_uuid,
            }
            for s in sidecars
        ],
        sort_keys=True,
        separators=(",", ":"),
    ).encode()

    return {
        "schema": SCHEMA,
        "protocol_id": PROTOCOL_ID,
        "generated_at": generated_at,
        "state": "ROSTER_FROZEN",
        "catalog": {
            "catalog_id": rule.catalog_id,
            "zenodo_doi": snapshot_receipt["zenodo_doi"],
            "archive_filename": snapshot_receipt["archive_filename"],
            "publisher_digest": snapshot_receipt["publisher_digest"],
            "archive_sha256": snapshot_receipt["locally_computed_sha256"],
            "extracted_member_name": snapshot_receipt["extracted_member_name"],
            "extracted_member_sha256": snapshot_receipt["extracted_member_sha256"],
        },
        "frame_rule": {
            "n": result["n"],
            "n_derivation": rule.n_derivation,
            "n_inputs": dict(rule.n_inputs),
            "predicates": [
                {"field": p.field, "op": p.op, "value": p.value} for p in rule.predicates
            ],
            "ranking": [{"field": k.field, "descending": k.descending} for k in rule.ranking],
            "tie_breaker": rule.tie_breaker,
            "snapshot_sha256": rule.snapshot_sha256,
        },
        "selection": {
            "rows_read": result["rows_read"],
            "parser_rejections": result["parser_rejections"],
            "projection_refusals": result["projection_refusals"],
            "dispositions": result["dispositions"],
            "eligible_count": result["eligible_count"],
            "selected_count": len(selected),
            "selection_is_short": result["selection_is_short"],
            "a_short_selection_is_reported_not_repaired": True,
        },
        "identity_coherence": coherence,
        "strict_total_order": result["strict_total_order_proof"],
        "roster": roster,
        "roster_fingerprint": "sha256:" + hashlib.sha256(roster_payload).hexdigest(),
        "selection_sidecar_fingerprint": "sha256:" + hashlib.sha256(sidecar_payload).hexdigest(),
        "freeze_chain": {
            "modules": {name: _sha(root / name) for name in FREEZE_CHAIN_MODULES},
            "receipts": {name: _sha(root / name) for name in FREEZE_CHAIN_RECEIPTS},
            "protocols": {name: _sha(root / name) for name in FREEZE_CHAIN_PROTOCOLS},
            "catalog_member_on_disk": _sha(catalog),
            "why_the_whole_chain": (
                "a freeze that pins the roster without pinning what produced it "
                "records a conclusion, not a derivation. Any of these bytes moving "
                "means the declared rule over the declared universe would no longer "
                "reproduce this roster."
            ),
        },
        "live_identity_attestation_required": {
            "compare": "observed GitHub repository id == frozen host_uuid",
            "on_mismatch": "REFUSE",
            "why": (
                "the snapshot is from 2020 and the census runs now. owner/repo may "
                "have moved; the numeric id did not. A response whose id differs is a "
                "different repository however identical the path looks (INC-V2-108 "
                "finding 4)."
            ),
        },
        "downstream_not_run": {
            "census_started": False,
            "corpus_spent": False,
            "payload_opened": False,
        },
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }


def main() -> int:
    argument_parser = argparse.ArgumentParser(description=__doc__)
    argument_parser.add_argument("--root", required=True, type=Path)
    argument_parser.add_argument("--catalog", required=True, type=Path)
    argument_parser.add_argument("--snapshot-receipt", required=True, type=Path)
    argument_parser.add_argument("--audit-receipt", required=True, type=Path)
    argument_parser.add_argument("--freeze", required=True, type=Path)
    argument_parser.add_argument("--generated-at", required=True)
    args = argument_parser.parse_args()

    snapshot_receipt = json.loads(args.snapshot_receipt.read_text(encoding="utf-8"))
    rule = frame.declared_rule(
        catalog_id=snapshot_receipt["catalog_id"],
        snapshot_sha256=snapshot_receipt["extracted_member_sha256"],
        snapshot_date_utc="2020-01-12",
    )
    audit = json.loads(args.audit_receipt.read_text(encoding="utf-8"))
    order_proof = require_tie_breaker_proven_unique(rule, audit)
    result = stream_select(args.catalog, rule)
    result["strict_total_order_proof"] = order_proof
    body = build_freeze(
        args.root, args.catalog, result, rule, snapshot_receipt, args.generated_at
    )
    body["content_sha256"] = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    args.freeze.parent.mkdir(parents=True, exist_ok=True)
    args.freeze.write_text(
        json.dumps(body, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "state": body["state"],
                "eligible_count": body["selection"]["eligible_count"],
                "selected_count": body["selection"]["selected_count"],
                "selection_is_short": body["selection"]["selection_is_short"],
                "roster_fingerprint": body["roster_fingerprint"],
                "freeze": args.freeze.as_posix(),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
