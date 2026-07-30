"""Provenance and evidence completeness validation."""

from __future__ import annotations

from collections.abc import Iterable

from akc_cir import (
    CanonicalBlock,
    KnowledgeBundle,
    RelationAssertion,
)

from .models import FindingSeverity, QualityFinding


def source_coverage_ratio(blocks: Iterable[CanonicalBlock]) -> float:
    materialized = tuple(blocks)
    if not materialized:
        return 0.0
    covered = sum(bool(block.source_refs) for block in materialized)
    return covered / len(materialized)


def validate_block_provenance(
    blocks: Iterable[CanonicalBlock],
) -> tuple[QualityFinding, ...]:
    findings: list[QualityFinding] = []
    for block in blocks:
        if not block.source_refs:
            findings.append(
                QualityFinding(
                    code="provenance.block_missing",
                    severity=FindingSeverity.CRITICAL,
                    message="A canonical block has no source reference.",
                    block_id=block.id,
                )
            )
        seen = set()
        for source_ref in block.source_refs:
            identity = (
                source_ref.document_version_id,
                source_ref.page_index0,
                source_ref.bbox1000.root if source_ref.bbox1000 else None,
            )
            if identity in seen:
                findings.append(
                    QualityFinding(
                        code="provenance.duplicate_ref",
                        severity=FindingSeverity.WARNING,
                        message="A block contains duplicate source references.",
                        block_id=block.id,
                    )
                )
            seen.add(identity)
    return tuple(findings)


def validate_knowledge_evidence(
    bundle: KnowledgeBundle,
    available_block_ids: set[str],
) -> tuple[QualityFinding, ...]:
    findings: list[QualityFinding] = []
    for note in bundle.notes:
        note_missing = sorted(set(note.evidence_block_ids) - available_block_ids)
        if note_missing:
            findings.append(
                QualityFinding(
                    code="evidence.note_unknown_block",
                    severity=FindingSeverity.CRITICAL,
                    message=f"Knowledge note references unknown blocks: {note_missing}",
                )
            )
        for claim in note.claims:
            missing = sorted(set(claim.source_block_ids) - available_block_ids)
            if missing:
                findings.append(
                    QualityFinding(
                        code="evidence.claim_unknown_block",
                        severity=FindingSeverity.CRITICAL,
                        message=f"Claim references unknown blocks: {missing}",
                    )
                )
        for candidate in note.related_note_candidates:
            missing = sorted(set(candidate.source_block_ids) - available_block_ids)
            if missing:
                findings.append(
                    QualityFinding(
                        code="evidence.link_unknown_block",
                        severity=FindingSeverity.CRITICAL,
                        message=f"Link proposal references unknown blocks: {missing}",
                    )
                )
    for relation in bundle.relations:
        findings.extend(validate_relation_evidence(relation, available_block_ids))
    return tuple(findings)


def validate_relation_evidence(
    relation: RelationAssertion,
    available_block_ids: set[str],
) -> tuple[QualityFinding, ...]:
    missing = sorted(set(relation.evidence_block_ids) - available_block_ids)
    if not missing:
        return ()
    return (
        QualityFinding(
            code="evidence.relation_unknown_block",
            severity=FindingSeverity.CRITICAL,
            message=f"Relation references unknown blocks: {missing}",
        ),
    )
