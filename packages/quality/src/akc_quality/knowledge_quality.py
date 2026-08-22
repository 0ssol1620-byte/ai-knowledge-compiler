"""Evidence completeness gates for compiled knowledge objects."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class KnowledgeObject:
    object_id: str
    source_ids: tuple[str, ...]
    source_hashes: tuple[str, ...]
    block_ids: tuple[str, ...]
    relation_target_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class KnowledgeQuality:
    total_objects: int
    evidence_complete_objects: int
    evidence_coverage: float
    orphan_relation_targets: tuple[str, ...]
    passed: bool


def validate_knowledge_quality(objects: tuple[KnowledgeObject, ...]) -> KnowledgeQuality:
    if not objects:
        return KnowledgeQuality(0, 0, 0.0, (), False)
    ids = {item.object_id for item in objects}
    complete = sum(
        bool(item.source_ids and item.source_hashes and item.block_ids) for item in objects
    )
    orphans = tuple(
        sorted(
            {target for item in objects for target in item.relation_target_ids if target not in ids}
        )
    )
    coverage = complete / len(objects)
    return KnowledgeQuality(
        len(objects), complete, coverage, orphans, coverage == 1 and not orphans
    )


__all__ = ["KnowledgeObject", "KnowledgeQuality", "validate_knowledge_quality"]
