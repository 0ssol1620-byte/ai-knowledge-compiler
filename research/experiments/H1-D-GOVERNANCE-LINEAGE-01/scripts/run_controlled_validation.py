#!/usr/bin/env python3
"""Controlled authority, bi-temporal, and lineage validation."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "packages" / "cir-python" / "src"))
HERE = Path(__file__).resolve().parent
PROTOCOL = HERE.parent / "PROTOCOL_2026-08-19.md"
SEED = 2026081908
CASES = 500

from akc_cir.authority import (  # noqa: E402
    AuthorityClass,
    ClaimContext,
    ResolutionRule,
    ResolutionStatus,
    RuleOutcome,
    ScopedClaim,
    SourceStatus,
    resolve_authority,
)
from akc_cir.consumption_lineage import (  # noqa: E402
    ConsumptionReceipt,
    consumption_dependency_edges,
    trace_stale_consumptions,
)
from akc_cir.dependency import (  # noqa: E402
    DependencyChannel,
    DependencyEdge,
    DependencyGraph,
    EdgeType,
)
from akc_cir.temporal import (  # noqa: E402
    TemporalFact,
    TemporalPolicy,
    TemporalSource,
    TemporalTimeline,
    replay_context,
)

SEM = frozenset({DependencyChannel.SEMANTIC})
LOC = frozenset({DependencyChannel.LOCATOR})
TEMP = frozenset({DependencyChannel.TEMPORAL})
BASE = datetime(2024, 1, 1, tzinfo=UTC)


def sha256_bytes(body: bytes) -> str:
    return "sha256:" + hashlib.sha256(body).hexdigest()


def file_sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_sha256(value: Any) -> str:
    return sha256_bytes(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
    )


def cell_rng(label: str) -> random.Random:
    digest = hashlib.sha256(f"{SEED}|{label}".encode()).digest()
    return random.Random(int.from_bytes(digest[:16], "big"))  # noqa: S311


def claim(
    claim_id: str,
    value: str,
    authority: AuthorityClass,
    **kwargs: Any,
) -> ScopedClaim:
    return ScopedClaim(
        claim_id=claim_id,
        subject="policy",
        value=value,
        authority=authority,
        **kwargs,
    )


def authority_case(label: str, rng: random.Random, index: int) -> tuple[bool, dict[str, Any]]:
    token = f"{label}-{index}-{rng.randrange(10**12)}"
    now = BASE + timedelta(days=rng.randrange(400, 700))
    ctx = ClaimContext(subject="policy", as_of=now, customer_id="A", region="KR")
    rules: tuple[ResolutionRule, ...] = ()
    hidden_id: str | None = None

    if label == "inapplicable_high_authority":
        low = claim(f"low-{token}", "LOW", AuthorityClass.OFFICIAL)
        high = claim(
            f"high-{token}",
            "HIGH",
            AuthorityClass.REGULATORY,
            scope={"customer_id": "B"},
        )
        claims, expected_status, expected_id = (
            [high, low],
            ResolutionStatus.RESOLVED,
            low.claim_id,
        )
    elif label == "narrow_scope":
        broad = claim(f"broad-{token}", "BROAD", AuthorityClass.OFFICIAL)
        narrow = claim(
            f"narrow-{token}",
            "NARROW",
            AuthorityClass.OFFICIAL,
            scope={"customer_id": "A"},
        )
        claims, expected_status, expected_id = (
            [broad, narrow],
            ResolutionStatus.RESOLVED,
            narrow.claim_id,
        )
    elif label == "regulatory_over_contract":
        contract = claim(f"contract-{token}", "CONTRACT", AuthorityClass.CONTRACTUAL)
        regulatory = claim(f"reg-{token}", "REG", AuthorityClass.REGULATORY)
        claims, expected_status, expected_id = (
            [contract, regulatory],
            ResolutionStatus.RESOLVED,
            regulatory.claim_id,
        )
    elif label == "active_over_withdrawn":
        withdrawn = claim(
            f"withdrawn-{token}",
            "OLD",
            AuthorityClass.OFFICIAL,
            source_status=SourceStatus.WITHDRAWN,
        )
        active = claim(
            f"active-{token}",
            "ACTIVE",
            AuthorityClass.OFFICIAL,
            source_status=SourceStatus.ACTIVE,
        )
        claims, expected_status, expected_id = (
            [withdrawn, active],
            ResolutionStatus.RESOLVED,
            active.claim_id,
        )
    elif label == "equal_conflict":
        recorded = now - timedelta(days=5)
        left = claim(
            f"left-{token}",
            "LEFT",
            AuthorityClass.OFFICIAL,
            recorded_at=recorded,
        )
        right = claim(
            f"right-{token}",
            "RIGHT",
            AuthorityClass.OFFICIAL,
            recorded_at=recorded,
        )
        claims, expected_status, expected_id = [left, right], ResolutionStatus.CONFLICTED, None
    elif label == "evidence_override":
        override = claim(
            f"override-{token}",
            "OVERRIDE",
            AuthorityClass.OFFICIAL,
            evidence_id=f"evidence-{token}",
        )
        regulatory = claim(f"reg-{token}", "REG", AuthorityClass.REGULATORY)
        rule = ResolutionRule(
            rule_id=f"rule-{token}",
            subject_type="policy",
            when=lambda item, _ctx: item.value == "OVERRIDE",
            precedence=50,
            outcome=RuleOutcome.PREFER,
        )
        rules = (rule,)
        claims, expected_status, expected_id = (
            [override, regulatory],
            ResolutionStatus.RESOLVED,
            override.claim_id,
        )
    elif label == "override_without_evidence":
        override = claim(f"override-{token}", "OVERRIDE", AuthorityClass.OFFICIAL)
        regulatory = claim(f"reg-{token}", "REG", AuthorityClass.REGULATORY)
        rule = ResolutionRule(
            rule_id=f"rule-{token}",
            subject_type="policy",
            when=lambda item, _ctx: item.value == "OVERRIDE",
            precedence=50,
            outcome=RuleOutcome.PREFER,
        )
        rules = (rule,)
        claims, expected_status, expected_id = (
            [override, regulatory],
            ResolutionStatus.RESOLVED,
            regulatory.claim_id,
        )
    elif label == "permission_hidden":
        hidden = claim(
            f"hidden-{token}",
            "SECRET",
            AuthorityClass.REGULATORY,
            required_permission="secret.read",
        )
        visible = claim(f"visible-{token}", "PUBLIC", AuthorityClass.OFFICIAL)
        hidden_id = hidden.claim_id
        claims, expected_status, expected_id = (
            [hidden, visible],
            ResolutionStatus.RESOLVED,
            visible.claim_id,
        )
    elif label == "temporal_window":
        expired = claim(
            f"expired-{token}",
            "EXPIRED",
            AuthorityClass.REGULATORY,
            valid_to=now - timedelta(days=1),
        )
        current = claim(f"current-{token}", "CURRENT", AuthorityClass.OFFICIAL)
        claims, expected_status, expected_id = (
            [expired, current],
            ResolutionStatus.RESOLVED,
            current.claim_id,
        )
    elif label == "no_candidate":
        wrong_scope = claim(
            f"wrong-{token}",
            "WRONG",
            AuthorityClass.REGULATORY,
            scope={"customer_id": "B"},
        )
        hidden = claim(
            f"hidden-{token}",
            "SECRET",
            AuthorityClass.REGULATORY,
            required_permission="secret.read",
        )
        hidden_id = hidden.claim_id
        claims, expected_status, expected_id = (
            [wrong_scope, hidden],
            ResolutionStatus.NO_CANDIDATE,
            None,
        )
    else:
        raise ValueError(label)

    result = resolve_authority(claims, ctx, rules=rules)
    observed_id = result.claim.claim_id if result.claim else None
    record_text = json.dumps(result.as_record(), sort_keys=True)
    review_ok = (
        result.required_review
        if expected_status is ResolutionStatus.CONFLICTED
        else not result.required_review
    )
    hidden_ok = hidden_id is None or hidden_id not in record_text
    passed = (
        result.status is expected_status
        and observed_id == expected_id
        and review_ok
        and hidden_ok
    )
    return passed, {
        "status": result.status.value,
        "expected_status": expected_status.value,
        "observed_claim_id": observed_id,
        "expected_claim_id": expected_id,
        "review_ok": review_ok,
        "hidden_id_leaked": not hidden_ok,
    }


def temporal_case(label: str, rng: random.Random, index: int) -> tuple[bool, dict[str, Any]]:
    offset = rng.randrange(0, 365)
    t0 = BASE + timedelta(days=offset)
    logical = f"fact:{label}:{index}:{rng.randrange(10**12)}"

    if label == "backdated_late_recording":
        fact = TemporalFact(
            logical_id=logical,
            value="A",
            valid_from=t0,
            recorded_at=t0 + timedelta(days=30),
            temporal_source=TemporalSource.EXPLICIT,
        )
        timeline = TemporalTimeline([fact])
        valid_only = timeline.as_of(valid_at=t0 + timedelta(days=10), logical_id=logical)
        known_early = timeline.as_of(
            valid_at=t0 + timedelta(days=10),
            known_at=t0 + timedelta(days=10),
            logical_id=logical,
        )
        passed = valid_only.values == ("A",) and known_early.values == ()
        detail = {"valid_only": valid_only.values, "known_early": known_early.values}
    elif label == "superseded_known_time":
        fact = TemporalFact(
            logical_id=logical,
            value="A",
            valid_from=t0,
            recorded_at=t0,
            superseded_at=t0 + timedelta(days=20),
            temporal_source=TemporalSource.EXPLICIT,
        )
        timeline = TemporalTimeline([fact])
        before = timeline.as_of(known_at=t0 + timedelta(days=10), logical_id=logical)
        after = timeline.as_of(known_at=t0 + timedelta(days=30), logical_id=logical)
        passed = before.values == ("A",) and after.values == ()
        detail = {"before": before.values, "after": after.values}
    elif label == "overlap_contradiction":
        facts = [
            TemporalFact(
                logical_id=logical,
                value="A",
                valid_from=t0,
                valid_to=t0 + timedelta(days=30),
                temporal_source=TemporalSource.EXPLICIT,
            ),
            TemporalFact(
                logical_id=logical,
                value="B",
                valid_from=t0 + timedelta(days=10),
                valid_to=t0 + timedelta(days=40),
                temporal_source=TemporalSource.EXPLICIT,
            ),
        ]
        contradictions = TemporalTimeline(facts).contradictions(logical)
        passed = len(contradictions) == 1
        detail = {"contradictions": len(contradictions)}
    elif label == "nonoverlap_no_contradiction":
        facts = [
            TemporalFact(
                logical_id=logical,
                value="A",
                valid_from=t0,
                valid_to=t0 + timedelta(days=10),
                temporal_source=TemporalSource.EXPLICIT,
            ),
            TemporalFact(
                logical_id=logical,
                value="B",
                valid_from=t0 + timedelta(days=10),
                valid_to=t0 + timedelta(days=30),
                temporal_source=TemporalSource.EXPLICIT,
            ),
        ]
        contradictions = TemporalTimeline(facts).contradictions(logical)
        passed = contradictions == ()
        detail = {"contradictions": len(contradictions)}
    elif label == "unknown_validity_policy":
        fact = TemporalFact(logical_id=logical, value="A")
        timeline = TemporalTimeline([fact])
        excluded = timeline.as_of(valid_at=t0, logical_id=logical)
        included = timeline.as_of(
            valid_at=t0,
            logical_id=logical,
            policy=TemporalPolicy.INCLUDE_UNKNOWN,
        )
        passed = (
            excluded.values == ()
            and logical in excluded.excluded_unknown
            and included.values == ("A",)
            and logical in included.included_unknown
        )
        detail = {
            "excluded": excluded.values,
            "included": included.values,
            "audit_included_unknown": logical in included.included_unknown,
        }
    elif label == "replay_both_axes":
        replay_t = t0 + timedelta(days=20)
        good = TemporalFact(
            logical_id=f"{logical}:good",
            value="GOOD",
            valid_from=t0,
            recorded_at=t0,
            temporal_source=TemporalSource.EXPLICIT,
        )
        late_record = TemporalFact(
            logical_id=f"{logical}:late",
            value="LATE",
            valid_from=t0,
            recorded_at=t0 + timedelta(days=30),
            temporal_source=TemporalSource.EXPLICIT,
        )
        future_valid = TemporalFact(
            logical_id=f"{logical}:future",
            value="FUTURE",
            valid_from=t0 + timedelta(days=30),
            recorded_at=t0,
            temporal_source=TemporalSource.EXPLICIT,
        )
        answer = replay_context(TemporalTimeline([good, late_record, future_valid]), at=replay_t)
        passed = answer.values == ("GOOD",)
        detail = {"values": answer.values}
    else:
        raise ValueError(label)
    return passed, detail


def edge(
    source: str,
    target: str,
    kind: EdgeType,
    channels: frozenset[DependencyChannel],
) -> DependencyEdge:
    return DependencyEdge(source_id=source, target_id=target, edge_type=kind, channels=channels)


def precision_recall(observed: set[str], gold: set[str]) -> tuple[float, float]:
    precision = 1.0 if not observed else len(observed & gold) / len(observed)
    recall = 1.0 if not gold else len(observed & gold) / len(gold)
    return precision, recall


def lineage_case(label: str, rng: random.Random, index: int) -> tuple[bool, dict[str, Any]]:
    token = f"{label}:{index}:{rng.randrange(10**12)}"
    if label in {"semantic_chain_consumption", "decoy_consumption"}:
        evidence = f"evidence:{token}"
        claim_id = f"claim:{token}"
        ontology = f"ontology:{token}"
        retrieval = f"retrieval:{token}"
        answer = f"answer:{token}"
        decoy = f"decoy:{token}"
        receipt = ConsumptionReceipt(
            consumption_id=f"used:{token}",
            world_state_id="world:before",
            consumed_unit_ids=(answer,),
        )
        decoy_receipt = ConsumptionReceipt(
            consumption_id=f"decoy:{token}",
            world_state_id="world:before",
            consumed_unit_ids=(decoy,),
        )
        edges = [
            edge(evidence, claim_id, EdgeType.SUPPORTS, SEM),
            edge(ontology, claim_id, EdgeType.DERIVED_FROM, SEM),
            edge(retrieval, ontology, EdgeType.DEPENDS_ON, SEM),
            edge(answer, retrieval, EdgeType.DEPENDS_ON, SEM),
            *consumption_dependency_edges(receipt, channels=SEM),
            *consumption_dependency_edges(decoy_receipt, channels=SEM),
        ]
        graph = DependencyGraph(edges)
        report = graph.impact_of([evidence], channel=DependencyChannel.SEMANTIC)
        gold = {claim_id, ontology, retrieval, answer, receipt.dependency_node_id}
        observed = set(report.affected_ids)
        risks = trace_stale_consumptions(
            changed_ids=[evidence],
            graph=graph,
            receipts=[receipt, decoy_receipt],
            candidate_world_state_id="world:after",
        )
        risk_ids = {risk.consumption_id for risk in risks}
        expected_risks = {receipt.consumption_id}
        p, r = precision_recall(observed, gold)
        rp, rr = precision_recall(risk_ids, expected_risks)
        if label == "semantic_chain_consumption":
            passed = p == r == rp == rr == 1.0
        else:
            passed = decoy_receipt.consumption_id not in risk_ids and decoy not in observed
        detail = {
            "precision": p,
            "recall": r,
            "stale_precision": rp,
            "stale_recall": rr,
            "false_impact": len(observed - gold),
            "missed": len(gold - observed),
        }
    elif label == "locator_relocation":
        locator = f"locator:{token}"
        pointer = f"pointer:{token}"
        semantic_claim = f"semantic:{token}"
        graph = DependencyGraph(
            [
                edge(pointer, locator, EdgeType.DEPENDS_ON, LOC),
                edge(semantic_claim, locator, EdgeType.DEPENDS_ON, SEM),
            ]
        )
        observed = set(
            graph.impact_of([locator], channel=DependencyChannel.LOCATOR).affected_ids
        )
        gold = {pointer}
        p, r = precision_recall(observed, gold)
        passed = p == r == 1.0 and semantic_claim not in observed
        detail = {"precision": p, "recall": r, "semantic_false_impact": semantic_claim in observed}
    elif label == "deep_chain_64":
        seed = f"seed:{token}"
        nodes = [f"node:{i:02d}:{token}" for i in range(64)]
        edges = [edge(nodes[0], seed, EdgeType.DEPENDS_ON, SEM)]
        edges.extend(edge(nodes[i], nodes[i - 1], EdgeType.DEPENDS_ON, SEM) for i in range(1, 64))
        report = DependencyGraph(edges).impact_of([seed], channel=DependencyChannel.SEMANTIC)
        observed = set(report.affected_ids)
        gold = set(nodes)
        final_path = next(path for path in report.affected if path.node_id == nodes[-1])
        p, r = precision_recall(observed, gold)
        reason = final_path.describe()
        reason_ok = final_path.depth == 64 and seed in reason and nodes[-1] in reason
        passed = p == r == 1.0 and reason_ok
        detail = {
            "precision": p,
            "recall": r,
            "final_depth": final_path.depth,
            "reason_ok": reason_ok,
        }
    elif label == "temporal_channel":
        seed = f"temporal-seed:{token}"
        temporal_consumer = f"temporal-consumer:{token}"
        semantic_decoy = f"semantic-decoy:{token}"
        graph = DependencyGraph(
            [
                edge(temporal_consumer, seed, EdgeType.DEPENDS_ON, TEMP),
                edge(semantic_decoy, seed, EdgeType.DEPENDS_ON, SEM),
            ]
        )
        observed = set(
            graph.impact_of([seed], channel=DependencyChannel.TEMPORAL).affected_ids
        )
        gold = {temporal_consumer}
        p, r = precision_recall(observed, gold)
        passed = p == r == 1.0 and semantic_decoy not in observed
        detail = {"precision": p, "recall": r, "semantic_false_impact": semantic_decoy in observed}
    elif label == "provenance_reconstruction":
        evidence = f"evidence:{token}"
        claim_id = f"claim:{token}"
        derived = f"derived:{token}"
        final = f"final:{token}"
        decoy = f"decoy:{token}"
        graph = DependencyGraph(
            [
                edge(evidence, claim_id, EdgeType.SUPPORTS, SEM),
                edge(derived, claim_id, EdgeType.DERIVED_FROM, SEM),
                edge(final, derived, EdgeType.DEPENDS_ON, SEM),
                edge(decoy, evidence, EdgeType.REFERENCES, SEM),
            ]
        )
        observed = set(graph.provenance_of(final))
        gold = {derived, claim_id, evidence}
        p, r = precision_recall(observed, gold)
        passed = p == r == 1.0 and decoy not in observed
        detail = {"precision": p, "recall": r, "false_provenance": len(observed - gold)}
    else:
        raise ValueError(label)
    return passed, detail


def run_cells(
    labels: tuple[str, ...],
    runner: Callable[[str, random.Random, int], tuple[bool, dict[str, Any]]],
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for label in labels:
        rng = cell_rng(label)
        counter: Counter[str] = Counter()
        failures: list[dict[str, Any]] = []
        numeric: dict[str, list[float]] = {}
        for index in range(CASES):
            passed, detail = runner(label, rng, index)
            counter["cases"] += 1
            counter["passed"] += int(passed)
            if not passed and len(failures) < 5:
                failures.append({"index": index, **detail})
            for key, value in detail.items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    numeric.setdefault(key, []).append(float(value))
        metrics = {
            key: {
                "min": min(values),
                "max": max(values),
                "mean": sum(values) / len(values),
            }
            for key, values in numeric.items()
            if values
        }
        out[label] = {"totals": dict(counter), "numeric": metrics, "failures": failures}
        print(f"{label}: {counter['passed']}/{counter['cases']} pass")
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    authority_labels = (
        "inapplicable_high_authority",
        "narrow_scope",
        "regulatory_over_contract",
        "active_over_withdrawn",
        "equal_conflict",
        "evidence_override",
        "override_without_evidence",
        "permission_hidden",
        "temporal_window",
        "no_candidate",
    )
    temporal_labels = (
        "backdated_late_recording",
        "superseded_known_time",
        "overlap_contradiction",
        "nonoverlap_no_contradiction",
        "unknown_validity_policy",
        "replay_both_axes",
    )
    lineage_labels = (
        "semantic_chain_consumption",
        "decoy_consumption",
        "locator_relocation",
        "deep_chain_64",
        "temporal_channel",
        "provenance_reconstruction",
    )

    authority = run_cells(authority_labels, authority_case)
    temporal = run_cells(temporal_labels, temporal_case)
    lineage = run_cells(lineage_labels, lineage_case)
    all_cells = {**authority, **temporal, **lineage}
    failed_cells = [
        name
        for name, cell in all_cells.items()
        if cell["totals"].get("passed", 0) != cell["totals"].get("cases", 0)
    ]
    receipt: dict[str, Any] = {
        "schema": "tavonel.governance-temporal-lineage-controlled.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "protocol_sha256": file_sha256(PROTOCOL),
        "script_sha256": file_sha256(Path(__file__)),
        "seed": SEED,
        "cases_per_cell": CASES,
        "authority": authority,
        "temporal": temporal,
        "lineage": lineage,
        "failed_cells": failed_cells,
        "primary_success": not failed_cells,
        "evidence_scope": (
            "controlled mechanism correctness only; no automatic temporal extraction or "
            "real-world frequency/generalization claim"
        ),
        "external_gpu_cost_usd": 0.0,
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"failed cells: {len(failed_cells)}")
    print(f"primary success: {not failed_cells}")
    return 0 if not failed_cells else 2


if __name__ == "__main__":
    raise SystemExit(main())
