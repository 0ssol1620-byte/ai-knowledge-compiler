#!/usr/bin/env python3
"""Outcome-blind fresh-cohort and evidence-split tooling for TAVONEL-R.

Nothing in this module reads model outputs or evaluator scores. Candidate records
are source/provenance metadata only. Primary Stage 1 is the blueprint's 300-page
two-lane result (Dr.DocBench + SEC); OpenDART is a separately sealed optional
external-validity lane and can never become a hidden dependency of the primary
result. Selection is deterministic within prospectively fixed source-family
quotas and refuses a family shortfall instead of reallocating quota after seeing
the available cohort.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from recovery_protocol import EvidenceSplit, ProtocolRefused

SCHEMA = "tavonel.recovery.fresh_selection.v1"
SELECTION_SALT = "TAVONEL-R-FRESH-STAGE1-EQUAL-FAMILY-2026-08-30"
EVIDENCE_SPLIT_SALT = "TAVONEL-R-EVIDENCE-SPLIT-2026-08-30"
STAGE1_FAMILY_QUOTAS: Mapping[str, int] = {
    "drdocbench": 150,
    "sec": 150,
}
SECONDARY_DART_QUOTA = 100
SUPPORTED_SOURCE_FAMILIES = frozenset((*STAGE1_FAMILY_QUOTAS, "dart"))

# Outcome-like fields are illegal even when nested inside a candidate. Keeping
# this list intentionally broad is preferable to silently admitting a post-hoc
# selection degree of freedom.
_OUTCOME_MARKERS = (
    "accuracy",
    "score",
    "correct",
    "error",
    "failure",
    "winner",
    "effect",
    "p_value",
    "confidence_interval",
    "prediction",
    "model_output",
    "recovery_result",
)
_SECRET_MARKERS = ("secret", "token", "password", "api_key", "apikey", "credential")

RIGHTS_CAVEATS: Mapping[str, str] = {
    "drdocbench": (
        "Dr.DocBench annotation metadata may be redistributed under its declared annotation "
        "license, but underlying source-document rights remain with the original sources; "
        "raw source redistribution is not implied by this research manifest."
    ),
    "sec": (
        "SEC filing material is acquired from official SEC endpoints under the SEC automated "
        "access policy; this manifest records accession/source identity rather than claiming a "
        "new license over filing content."
    ),
    "dart": (
        "DART/OpenDART material is acquired through the official service subject to its access "
        "terms; this manifest records source identity and does not expand redistribution rights."
    ),
}


class SelectionRefused(ProtocolRefused):
    pass


def _canonical_digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _walk_keys(value: Any) -> Iterable[str]:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            yield str(key)
            yield from _walk_keys(nested)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for nested in value:
            yield from _walk_keys(nested)


def _reject_forbidden_metadata(value: Mapping[str, Any]) -> None:
    for key in _walk_keys(value):
        folded = key.casefold()
        if any(marker in folded for marker in _OUTCOME_MARKERS):
            raise SelectionRefused(f"outcome-like field is forbidden in fresh selection: {key}")
        if any(marker in folded for marker in _SECRET_MARKERS):
            raise SelectionRefused(f"secret-like field is forbidden in fresh selection: {key}")


def _require_sha256(value: str, field: str) -> None:
    if not value.startswith("sha256:") or len(value) != 71:
        raise SelectionRefused(f"{field} must be a full sha256 digest")


@dataclass(frozen=True, slots=True)
class SourceCandidate:
    source_family: str
    family_id: str
    document_id: str
    page_id: str
    source_locator: str
    source_revision: str
    source_sha256: str
    acquisition_identity: str
    metadata: Mapping[str, Any]

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> SourceCandidate:
        _reject_forbidden_metadata(record)
        required = (
            "source_family",
            "family_id",
            "document_id",
            "page_id",
            "source_locator",
            "source_revision",
            "source_sha256",
            "acquisition_identity",
        )
        missing = [key for key in required if not str(record.get(key) or "").strip()]
        if missing:
            raise SelectionRefused(f"candidate is missing required fields: {missing}")
        family = str(record["source_family"]).casefold()
        if family not in SUPPORTED_SOURCE_FAMILIES:
            raise SelectionRefused(f"unsupported source family: {family}")
        digest = str(record["source_sha256"])
        _require_sha256(digest, "source_sha256")
        metadata = dict(record.get("metadata") or {})
        _reject_forbidden_metadata(metadata)
        return cls(
            source_family=family,
            family_id=str(record["family_id"]),
            document_id=str(record["document_id"]),
            page_id=str(record["page_id"]),
            source_locator=str(record["source_locator"]),
            source_revision=str(record["source_revision"]),
            source_sha256=digest,
            acquisition_identity=str(record["acquisition_identity"]),
            metadata=metadata,
        )

    @property
    def stable_id(self) -> str:
        return "|".join(
            (
                self.source_family,
                self.family_id,
                self.document_id,
                self.page_id,
                self.source_revision,
                self.source_sha256,
            )
        )

    def as_record(self) -> dict[str, Any]:
        return {
            "source_family": self.source_family,
            "family_id": self.family_id,
            "document_id": self.document_id,
            "page_id": self.page_id,
            "source_locator": self.source_locator,
            "source_revision": self.source_revision,
            "source_sha256": self.source_sha256,
            "acquisition_identity": self.acquisition_identity,
            "metadata": dict(self.metadata),
        }


def selection_salt_digest() -> str:
    return "sha256:" + hashlib.sha256(SELECTION_SALT.encode()).hexdigest()


def evidence_split_salt_digest() -> str:
    return "sha256:" + hashlib.sha256(EVIDENCE_SPLIT_SALT.encode()).hexdigest()


def _rank(candidate: SourceCandidate) -> bytes:
    return hashlib.sha256(f"{SELECTION_SALT}|{candidate.stable_id}".encode()).digest()


def build_spent_manifest(
    *, exact_spent_ids: Iterable[str], spent_family_ids: Iterable[str]
) -> dict[str, Any]:
    exact = tuple(sorted(set(map(str, exact_spent_ids))))
    families = tuple(sorted(set(map(str, spent_family_ids))))
    body = {
        "schema": "tavonel.recovery.spent_manifest.v1",
        "exact_spent_ids": list(exact),
        "spent_family_ids": list(families),
        "historical_development_families": [
            "PARSEBENCH_2026_08_09_2078",
            "OMNIDOCBENCH_2026_08_09_1651",
            "OLMOCR_BENCH_2026_08_09_1403",
            "DART_SEC_20_PAGE_A40_FIXED_SET",
            "SEC_PUBLIC_DEMO_FIXTURES_AND_KNOWN_FAILURE_CASES",
        ],
    }
    return {**body, "spent_manifest_digest": _canonical_digest(body)}


def select_stage1(
    candidate_records: Sequence[Mapping[str, Any]], spent_manifest: Mapping[str, Any]
) -> dict[str, Any]:
    _reject_forbidden_metadata(spent_manifest)
    exact_spent = set(map(str, spent_manifest.get("exact_spent_ids", ())))
    spent_families = set(map(str, spent_manifest.get("spent_family_ids", ())))
    candidates = [SourceCandidate.from_record(row) for row in candidate_records]
    ids = [row.stable_id for row in candidates]
    if len(ids) != len(set(ids)):
        raise SelectionRefused("candidate manifest contains duplicate stable page identities")

    eligible: dict[str, list[SourceCandidate]] = {family: [] for family in STAGE1_FAMILY_QUOTAS}
    excluded_exact = 0
    excluded_family = 0
    for candidate in candidates:
        if candidate.stable_id in exact_spent:
            excluded_exact += 1
            continue
        if candidate.family_id in spent_families:
            excluded_family += 1
            continue
        if candidate.source_family in STAGE1_FAMILY_QUOTAS:
            eligible[candidate.source_family].append(candidate)

    selected: list[SourceCandidate] = []
    for family, quota in STAGE1_FAMILY_QUOTAS.items():
        rows = sorted(eligible[family], key=lambda row: (_rank(row), row.stable_id))
        if len(rows) < quota:
            raise SelectionRefused(
                f"fresh family {family} has {len(rows)} eligible pages, below frozen "
                f"quota {quota}; "
                "quota reallocation is forbidden"
            )
        selected.extend(rows[:quota])

    selected.sort(key=lambda row: (row.source_family, _rank(row), row.stable_id))
    counts = Counter(row.source_family for row in selected)
    entries = [
        {"selection_ordinal": index, **row.as_record()}
        for index, row in enumerate(selected, start=1)
    ]
    body = {
        "schema": SCHEMA,
        "selection_salt_digest": selection_salt_digest(),
        "family_quotas": dict(STAGE1_FAMILY_QUOTAS),
        "selection_rule": (
            "exclude exact spent page IDs and spent family IDs, then within each fixed "
            "source-family "
            "quota sort sha256(selection_salt|stable_id) ascending; never reallocate shortfall"
        ),
        "candidate_count": len(candidates),
        "eligible_counts": {family: len(rows) for family, rows in eligible.items()},
        "excluded_exact_spent": excluded_exact,
        "excluded_spent_family": excluded_family,
        "selected_counts": dict(sorted(counts.items())),
        "entry_count": len(entries),
        "rights_caveats": dict(RIGHTS_CAVEATS),
        "optional_secondary_lane": {
            "source_family": "dart",
            "quota": SECONDARY_DART_QUOTA,
            "included_in_primary_result": False,
        },
        "entries": entries,
        "scientific_outcomes_used_for_selection": False,
    }
    return {**body, "cohort_seal_digest": _canonical_digest(body)}


def select_secondary_dart(
    candidate_records: Sequence[Mapping[str, Any]], spent_manifest: Mapping[str, Any]
) -> dict[str, Any]:
    """Seal the optional Korean external-validity lane without affecting Stage 1."""
    _reject_forbidden_metadata(spent_manifest)
    exact_spent = set(map(str, spent_manifest.get("exact_spent_ids", ())))
    spent_families = set(map(str, spent_manifest.get("spent_family_ids", ())))
    candidates = [SourceCandidate.from_record(row) for row in candidate_records]
    ids = [row.stable_id for row in candidates]
    if len(ids) != len(set(ids)):
        raise SelectionRefused("candidate manifest contains duplicate stable page identities")
    rows = [
        row
        for row in candidates
        if row.source_family == "dart"
        and row.stable_id not in exact_spent
        and row.family_id not in spent_families
    ]
    rows.sort(key=lambda row: (_rank(row), row.stable_id))
    if len(rows) < SECONDARY_DART_QUOTA:
        raise SelectionRefused(
            f"fresh family dart has {len(rows)} eligible pages, below frozen secondary quota "
            f"{SECONDARY_DART_QUOTA}; secondary-lane shortfall cannot alter the primary cohort"
        )
    entries = [
        {"selection_ordinal": index, **row.as_record()}
        for index, row in enumerate(rows[:SECONDARY_DART_QUOTA], start=1)
    ]
    body = {
        "schema": "tavonel.recovery.fresh_selection.dart_secondary.v1",
        "selection_salt_digest": selection_salt_digest(),
        "source_family": "dart",
        "quota": SECONDARY_DART_QUOTA,
        "included_in_primary_result": False,
        "entry_count": len(entries),
        "rights_caveat": RIGHTS_CAVEATS["dart"],
        "entries": entries,
        "scientific_outcomes_used_for_selection": False,
    }
    return {**body, "cohort_seal_digest": _canonical_digest(body)}


@dataclass(frozen=True, slots=True)
class EvidenceAnchor:
    anchor_id: str
    anchor_class: str
    evaluator_label: bool = False
    trigger_eligible: bool = False
    evaluation_eligible: bool = False


def build_evidence_split(anchors: Sequence[EvidenceAnchor]) -> dict[str, Any]:
    if not anchors:
        raise SelectionRefused("evidence split requires anchors")
    ids = [anchor.anchor_id for anchor in anchors]
    if len(ids) != len(set(ids)):
        raise SelectionRefused("evidence anchor IDs must be unique")
    trigger: list[str] = []
    evaluation: list[str] = []
    assignment: list[dict[str, Any]] = []
    for anchor in sorted(anchors, key=lambda row: row.anchor_id):
        if not anchor.anchor_id or not anchor.anchor_class:
            raise SelectionRefused("evidence anchors require stable id and class")
        if anchor.evaluator_label:
            side = "evaluation"
        elif anchor.trigger_eligible and not anchor.evaluation_eligible:
            side = "trigger"
        elif anchor.evaluation_eligible and not anchor.trigger_eligible:
            side = "evaluation"
        elif anchor.trigger_eligible and anchor.evaluation_eligible:
            digest = hashlib.sha256(f"{EVIDENCE_SPLIT_SALT}|{anchor.anchor_id}".encode()).digest()
            side = "trigger" if digest[0] % 2 == 0 else "evaluation"
        else:
            raise SelectionRefused(f"anchor {anchor.anchor_id} has no permitted evidence role")
        if side == "trigger":
            trigger.append(anchor.anchor_id)
        else:
            evaluation.append(anchor.anchor_id)
        assignment.append(
            {
                "anchor_id": anchor.anchor_id,
                "anchor_class": anchor.anchor_class,
                "side": side,
                "evaluator_label": anchor.evaluator_label,
            }
        )
    split = EvidenceSplit(
        split_salt_digest=evidence_split_salt_digest(),
        trigger_anchor_ids=tuple(trigger),
        evaluation_anchor_ids=tuple(evaluation),
    )
    split.validate()
    body = {
        "schema": "tavonel.recovery.evidence_split.v1",
        "split_salt_digest": split.split_salt_digest,
        "trigger_anchor_ids": trigger,
        "evaluation_anchor_ids": evaluation,
        "assignment": assignment,
        "evaluator_labels_forced_evaluation_only": True,
        "runtime_may_read_evaluation_side": False,
    }
    return {**body, "evidence_split_digest": _canonical_digest(body)}


__all__ = [
    "EVIDENCE_SPLIT_SALT",
    "RIGHTS_CAVEATS",
    "SELECTION_SALT",
    "STAGE1_FAMILY_QUOTAS",
    "EvidenceAnchor",
    "SelectionRefused",
    "SourceCandidate",
    "build_evidence_split",
    "build_spent_manifest",
    "evidence_split_salt_digest",
    "select_stage1",
    "selection_salt_digest",
]
