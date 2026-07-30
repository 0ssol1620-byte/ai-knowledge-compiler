"""Pure builders and deterministic assembly for the durable A-D knowledge DAG."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from akc_cir import (
    AssertionStatus,
    ConflictCandidate,
    KnowledgeBundle,
    RelatedNoteCandidate,
    RelationAssertion,
    ReviewStatus,
)
from akc_cir import KnowledgeNote as CirKnowledgeNote

from .knowledge_gpu import (
    StageABlockPreview,
    StageAHeading,
    StageAInput,
    StageAResult,
    StageBFragment,
    StageBInput,
    StageBResult,
    StageCCandidateEvidence,
    StageCClaimDescriptor,
    StageCEvidenceDescriptor,
    StageCInput,
    StageCResult,
    StageDAclAttestation,
    StageDInput,
    StageDResult,
    StageDSourceCandidate,
    canonical_json_bytes,
)
from .models import Block, Document, Page, ProcessingJob

_STAGE_A_PREVIEW_CHARS = 200
_STAGE_B_FRAGMENT_BYTES = 32 * 1024
_STAGE_B_UNIT_BYTES = 512 * 1024
_STAGE_B_MAX_FRAGMENTS = 32
_MAX_STAGE_B_UNITS = 256
_MAX_PIPELINE_CANDIDATES = 1_000


@dataclass(frozen=True, slots=True)
class PipelineCandidate:
    candidate_id: str
    unit_id: str
    note: CirKnowledgeNote
    descriptor: StageCCandidateEvidence


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\0".join(parts).encode()).hexdigest()
    return f"{prefix}-{digest[:48]}"


def _document_version_id(document: Document) -> str:
    return f"{document.id}:v{document.active_version}"


def _block_text(block: Block) -> str:
    return (block.markdown or block.normalized_text or block.source_text or "").strip()


def knowledge_compile_input_sha256(
    *,
    document: Document,
    blocks: list[Block],
) -> str:
    """Hash the complete immutable compile revision without exposing source text."""

    payload = {
        "document_id": str(document.id),
        "document_version": document.active_version,
        "cir_schema_version": document.cir_schema_version,
        "blocks": [
            {
                "id": str(block.id),
                "revision": block.revision,
                "content_sha256": hashlib.sha256(_block_text(block).encode()).hexdigest(),
            }
            for block in sorted(blocks, key=lambda value: (value.block_order, str(value.id)))
            if _block_text(block)
        ],
    }
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _source_refs(
    *,
    block: Block,
    document: Document,
    page_number: int,
) -> tuple[dict[str, Any], ...]:
    bbox: tuple[int, int, int, int] | None = None
    if block.bbox1000 is not None and len(block.bbox1000) == 4:
        bbox = (
            int(block.bbox1000[0]),
            int(block.bbox1000[1]),
            int(block.bbox1000[2]),
            int(block.bbox1000[3]),
        )
    return (
        {
            "document_id": str(document.id),
            "document_version_id": _document_version_id(document),
            "page_index0": page_number - 1,
            "page_number1": page_number,
            "bbox1000": bbox,
        },
    )


def build_stage_a_input(
    *,
    document: Document,
    blocks: list[Block],
    pages: list[Page],
) -> StageAInput:
    """Build a bounded map request containing previews, never full document text."""

    page_numbers = {page.id: page.page_number for page in pages}
    eligible = [
        block
        for block in blocks
        if _block_text(block) and block.page_id is not None and block.page_id in page_numbers
    ]
    if not eligible:
        raise RuntimeError("knowledge_input_has_no_evidence")
    eligible_ids = {block.id for block in eligible}
    by_id = {block.id: block for block in eligible}
    heading_blocks = {
        block.id: block for block in eligible if block.block_type in {"heading", "title"}
    }

    def heading_path(block: Block) -> tuple[str, ...]:
        values: list[str] = []
        seen: set[Any] = set()
        parent_id = block.parent_block_id
        while parent_id is not None and parent_id not in seen:
            seen.add(parent_id)
            parent = by_id.get(parent_id)
            if parent is None:
                break
            if parent.id in heading_blocks:
                values.append(str(parent.id))
            parent_id = parent.parent_block_id
        values.reverse()
        return tuple(values[-32:])

    headings: list[StageAHeading] = []
    for block in eligible:
        if block.id not in heading_blocks:
            continue
        ancestors = heading_path(block)
        headings.append(
            StageAHeading(
                heading_id=str(block.id),
                block_id=str(block.id),
                level=min(32, len(ancestors) + 1),
                title_preview=_block_text(block)[:_STAGE_A_PREVIEW_CHARS],
                parent_heading_id=ancestors[-1] if ancestors else None,
            )
        )
    heading_ids = {heading.heading_id for heading in headings}

    def page_number(block: Block) -> int:
        if block.page_id is None:
            raise RuntimeError("knowledge_stage_a_page_scope_invalid")
        value = page_numbers.get(block.page_id)
        if value is None:
            raise RuntimeError("knowledge_stage_a_page_scope_invalid")
        return value

    previews = tuple(
        StageABlockPreview(
            block_id=str(block.id),
            block_type=block.block_type,
            page_number1=page_number(block),
            char_count=len(_block_text(block)),
            preview=_block_text(block)[:_STAGE_A_PREVIEW_CHARS],
            heading_path=tuple(
                heading_id for heading_id in heading_path(block) if heading_id in heading_ids
            ),
        )
        for block in eligible
        if block.id in eligible_ids
    )
    value = StageAInput(
        unit_id=_stable_id("a", str(document.id), _document_version_id(document)),
        document_id=str(document.id),
        document_version_id=_document_version_id(document),
        title=document.title,
        headings=tuple(headings),
        blocks=previews,
    )
    if len(canonical_json_bytes(value)) > 8 * 1024 * 1024:
        raise RuntimeError("knowledge_stage_a_input_too_large")
    return value


def _utf8_fragments(text: str) -> tuple[str, ...]:
    fragments: list[str] = []
    start = 0
    while start < len(text):
        low = start + 1
        high = min(len(text), start + _STAGE_B_FRAGMENT_BYTES)
        best = low
        while low <= high:
            midpoint = (low + high) // 2
            if len(text[start:midpoint].encode()) <= _STAGE_B_FRAGMENT_BYTES:
                best = midpoint
                low = midpoint + 1
            else:
                high = midpoint - 1
        fragments.append(text[start:best])
        start = best
    return tuple(fragments)


def _pack_section_fragments(
    fragments: list[StageBFragment],
) -> list[list[StageBFragment]]:
    units: list[list[StageBFragment]] = []
    current: list[StageBFragment] = []
    for fragment in fragments:
        candidate = [*current, fragment]
        approximate = sum(len(item.text.encode()) for item in candidate)
        if current and (
            len(candidate) > _STAGE_B_MAX_FRAGMENTS or approximate > _STAGE_B_UNIT_BYTES
        ):
            units.append(current)
            current = [fragment]
        else:
            current = candidate
    if current:
        units.append(current)
    return units


def build_stage_b_inputs(
    *,
    document: Document,
    blocks: list[Block],
    pages: list[Page],
    section_map: StageAResult,
) -> tuple[StageBInput, ...]:
    """Split every mapped section into content-bounded, resumable B units."""

    page_numbers = {page.id: page.page_number for page in pages}
    by_id = {str(block.id): block for block in blocks}
    values: list[StageBInput] = []
    for section in section_map.sections:
        fragments: list[StageBFragment] = []
        for block_id in section.block_ids:
            block = by_id.get(block_id)
            if block is None or block.page_id is None or block.page_id not in page_numbers:
                raise RuntimeError("knowledge_stage_b_block_scope_invalid")
            text = _block_text(block)
            if not text:
                raise RuntimeError("knowledge_stage_b_block_content_missing")
            source_refs = _source_refs(
                block=block,
                document=document,
                page_number=page_numbers[block.page_id],
            )
            for fragment_index, fragment_text in enumerate(_utf8_fragments(text)):
                fragments.append(
                    StageBFragment(
                        fragment_id=f"{block_id}.f{fragment_index}",
                        evidence_block_id=block_id,
                        text=fragment_text,
                        source_refs=source_refs,
                    )
                )
        packed = _pack_section_fragments(fragments)
        for shard_index, shard in enumerate(packed):
            unit_id = _stable_id(
                "b",
                str(document.id),
                _document_version_id(document),
                section.section_id,
                str(shard_index),
            )
            stage_input = StageBInput(
                unit_id=unit_id,
                document_id=str(document.id),
                document_version_id=_document_version_id(document),
                section_id=section.section_id,
                section_title=section.title,
                classification=section_map.classification,
                shard_index0=shard_index,
                shard_count=len(packed),
                fragments=tuple(shard),
            )
            if len(canonical_json_bytes(stage_input)) > 1024 * 1024:
                raise RuntimeError("knowledge_stage_b_input_too_large")
            values.append(stage_input)
    if not values:
        raise RuntimeError("knowledge_stage_b_has_no_units")
    if len(values) > _MAX_STAGE_B_UNITS:
        raise RuntimeError("knowledge_stage_b_unit_limit_exceeded")
    return tuple(values)


def _normalized_semantic_text(value: str, *, limit: int) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return re.sub(r"\s+", " ", normalized).strip()[:limit]


def _candidate_descriptor(
    *,
    candidate_id: str,
    note: CirKnowledgeNote,
    stage_input: StageBInput,
) -> StageCCandidateEvidence:
    fragments_by_block: dict[str, list[str]] = {}
    for fragment in stage_input.fragments:
        fragments_by_block.setdefault(fragment.evidence_block_id, []).append(fragment.text)
    evidence: list[StageCEvidenceDescriptor] = []
    for block_id in note.evidence_block_ids:
        fragment_text = "\n".join(fragments_by_block.get(block_id, ())).strip()
        if not fragment_text:
            raise RuntimeError("knowledge_pipeline_candidate_evidence_missing")
        snippet = fragment_text[:200]
        evidence.append(
            StageCEvidenceDescriptor(
                block_id=block_id,
                snippet=snippet,
                snippet_sha256=hashlib.sha256(snippet.encode()).hexdigest(),
            )
        )
    claims = tuple(
        StageCClaimDescriptor(
            text=_normalized_semantic_text(claim.text, limit=500),
            signature_sha256=hashlib.sha256(
                "\0".join(
                    (
                        _normalized_semantic_text(claim.text, limit=500),
                        *claim.source_block_ids,
                    )
                ).encode()
            ).hexdigest(),
            evidence_block_ids=claim.source_block_ids,
        )
        for claim in note.claims[:20]
    )
    descriptor = StageCCandidateEvidence(
        candidate_id=candidate_id,
        normalized_title=_normalized_semantic_text(note.title, limit=300),
        note_type=note.note_type.value,
        summary=_normalized_semantic_text(note.summary or "", limit=2_000),
        aliases=tuple(
            _normalized_semantic_text(value, limit=200)
            for value in note.aliases[:20]
            if value.strip()
        ),
        tags=tuple(
            _normalized_semantic_text(value, limit=100) for value in note.tags[:20] if value.strip()
        ),
        claims=claims,
        evidence_block_ids=note.evidence_block_ids,
        evidence=tuple(evidence),
    )
    if not set(note.evidence_block_ids).issubset(
        {fragment.evidence_block_id for fragment in stage_input.fragments}
    ):
        raise RuntimeError("knowledge_pipeline_candidate_evidence_scope_invalid")
    return descriptor


def pipeline_candidates(
    stage_b_results: tuple[StageBResult, ...],
    *,
    stage_b_inputs: tuple[StageBInput, ...],
) -> tuple[PipelineCandidate, ...]:
    inputs = {stage_input.unit_id: stage_input for stage_input in stage_b_inputs}
    if len(inputs) != len(stage_b_inputs):
        raise RuntimeError("knowledge_pipeline_duplicate_stage_b_input")
    values = tuple(
        PipelineCandidate(
            candidate_id=(
                candidate_id := _stable_id(
                    "candidate",
                    result.unit_id,
                    note.note_id,
                )
            ),
            unit_id=result.unit_id,
            note=note,
            descriptor=_candidate_descriptor(
                candidate_id=candidate_id,
                note=note,
                stage_input=inputs[result.unit_id],
            ),
        )
        for result in stage_b_results
        for note in result.notes
    )
    if not values:
        raise RuntimeError("knowledge_stage_b_has_no_notes")
    if len(values) > _MAX_PIPELINE_CANDIDATES:
        raise RuntimeError("knowledge_pipeline_candidate_limit_exceeded")
    ids = [candidate.candidate_id for candidate in values]
    if len(ids) != len(set(ids)):
        raise RuntimeError("knowledge_pipeline_candidate_id_collision")
    return values


def build_stage_c_input(
    *,
    document: Document,
    candidates: tuple[PipelineCandidate, ...],
) -> StageCInput:
    """Stage C receives bounded semantic descriptors, never full source blocks."""

    value = StageCInput(
        unit_id=_stable_id("c", str(document.id), _document_version_id(document)),
        document_id=str(document.id),
        document_version_id=_document_version_id(document),
        candidates=tuple(candidate.descriptor for candidate in candidates),
    )
    if len(canonical_json_bytes(value)) > 8 * 1024 * 1024:
        raise RuntimeError("knowledge_stage_c_input_too_large")
    return value


def _canonical_evidence(
    *,
    candidates: tuple[PipelineCandidate, ...],
    merge_plan: StageCResult,
) -> dict[str, tuple[str, ...]]:
    by_id = {candidate.candidate_id: candidate for candidate in candidates}
    return {
        group.canonical_candidate_id: tuple(
            dict.fromkeys(
                block_id
                for member_id in group.member_candidate_ids
                for block_id in by_id[member_id].note.evidence_block_ids
            )
        )
        for group in merge_plan.merge_groups
    }


def build_stage_d_input(
    *,
    job: ProcessingJob,
    document: Document,
    candidates: tuple[PipelineCandidate, ...],
    merge_plan: StageCResult,
) -> StageDInput:
    """Emit an explicit no-candidate contract until retrieval is provider-verified."""

    evidence = _canonical_evidence(candidates=candidates, merge_plan=merge_plan)
    by_id = {candidate.candidate_id: candidate for candidate in candidates}
    source_candidates: list[StageDSourceCandidate] = []
    for group in merge_plan.merge_groups:
        members = tuple(by_id[member_id] for member_id in group.member_candidate_ids)
        canonical = by_id[group.canonical_candidate_id].descriptor
        descriptors_by_block = {
            item.block_id: item for member in members for item in member.descriptor.evidence
        }
        claims_by_signature = {
            claim.signature_sha256: claim
            for member in members
            for claim in member.descriptor.claims
        }
        source_candidates.append(
            StageDSourceCandidate(
                candidate_id=group.canonical_candidate_id,
                normalized_title=canonical.normalized_title,
                note_type=canonical.note_type,
                summary=canonical.summary,
                aliases=tuple(
                    dict.fromkeys(
                        alias for member in members for alias in member.descriptor.aliases
                    )
                )[:20],
                tags=tuple(
                    dict.fromkeys(tag for member in members for tag in member.descriptor.tags)
                )[:20],
                claims=tuple(claims_by_signature.values())[:20],
                evidence_block_ids=evidence[group.canonical_candidate_id],
                evidence=tuple(
                    descriptors_by_block[block_id]
                    for block_id in evidence[group.canonical_candidate_id]
                ),
            )
        )
    allowed_projects = (str(job.project_id),)
    value = StageDInput(
        unit_id=_stable_id("d", str(document.id), _document_version_id(document)),
        tenant_id=str(job.tenant_id),
        document_id=str(document.id),
        document_version_id=_document_version_id(document),
        allowed_project_ids=allowed_projects,
        acl_attestation=StageDAclAttestation(
            tenant_id=str(job.tenant_id),
            allowed_project_ids=allowed_projects,
            scope_sha256=hashlib.sha256(
                "\0".join((str(job.tenant_id), *allowed_projects)).encode()
            ).hexdigest(),
        ),
        source_candidates=tuple(source_candidates),
        retrieval_status="provider_unverified",
        retrieval_candidates=(),
    )
    if len(canonical_json_bytes(value)) > 8 * 1024 * 1024:
        raise RuntimeError("knowledge_stage_d_input_too_large")
    return value


def _merge_notes(
    *,
    group_members: tuple[PipelineCandidate, ...],
    canonical_candidate_id: str,
    candidate_to_canonical: dict[str, str],
    local_candidate_ids: dict[tuple[str, str], str],
    links: tuple[Any, ...],
) -> CirKnowledgeNote:
    by_id = {candidate.candidate_id: candidate for candidate in group_members}
    canonical = by_id[canonical_candidate_id].note
    evidence = tuple(
        dict.fromkeys(
            block_id
            for candidate in group_members
            for block_id in candidate.note.evidence_block_ids
        )
    )
    claims = tuple(
        {
            (
                claim.text,
                claim.origin.value,
                claim.source_block_ids,
                claim.confidence,
            ): claim
            for candidate in group_members
            for claim in candidate.note.claims
        }.values()
    )
    aliases = tuple(
        dict.fromkeys(alias for candidate in group_members for alias in candidate.note.aliases)
    )
    tags = tuple(dict.fromkeys(tag for candidate in group_members for tag in candidate.note.tags))
    related: dict[tuple[str, str], RelatedNoteCandidate] = {}
    for candidate in group_members:
        for proposal in candidate.note.related_note_candidates:
            local_id = local_candidate_ids.get((candidate.unit_id, proposal.target_id))
            target = (
                candidate_to_canonical.get(local_id, local_id)
                if local_id is not None
                else proposal.target_id
            )
            if target == canonical_candidate_id:
                continue
            related[(target, proposal.relation)] = proposal.model_copy(update={"target_id": target})
    for proposal in links:
        if proposal.source_candidate_id != canonical_candidate_id:
            continue
        related[(proposal.target_stable_id, proposal.relation)] = RelatedNoteCandidate(
            target_id=proposal.target_stable_id,
            relation=proposal.relation,
            reason=proposal.reason,
            source_block_ids=proposal.evidence_block_ids,
            confidence=proposal.confidence,
        )
    return CirKnowledgeNote(
        note_id=canonical_candidate_id,
        title=canonical.title,
        note_type=canonical.note_type,
        content_origin=canonical.content_origin,
        evidence_block_ids=evidence,
        summary=canonical.summary,
        claims=claims,
        aliases=aliases,
        tags=tags,
        related_note_candidates=tuple(related.values()),
        review_status=(
            ReviewStatus.AUTO_WITH_WARNINGS if len(group_members) > 1 else canonical.review_status
        ),
    )


def assemble_knowledge_bundle(
    *,
    document: Document,
    stage_b_results: tuple[StageBResult, ...],
    candidates: tuple[PipelineCandidate, ...],
    merge_plan: StageCResult,
    links: StageDResult,
) -> KnowledgeBundle:
    """Deterministically assemble the admitted stage artifacts into AKMP data."""

    candidate_by_id = {candidate.candidate_id: candidate for candidate in candidates}
    candidate_to_canonical = {
        member_id: group.canonical_candidate_id
        for group in merge_plan.merge_groups
        for member_id in group.member_candidate_ids
    }
    local_candidate_ids = {
        (candidate.unit_id, candidate.note.note_id): candidate.candidate_id
        for candidate in candidates
    }
    notes = tuple(
        _merge_notes(
            group_members=tuple(
                candidate_by_id[member_id] for member_id in group.member_candidate_ids
            ),
            canonical_candidate_id=group.canonical_candidate_id,
            candidate_to_canonical=candidate_to_canonical,
            local_candidate_ids=local_candidate_ids,
            links=links.links,
        )
        for group in merge_plan.merge_groups
    )

    relations: dict[tuple[str, str, str], RelationAssertion] = {}
    for result in stage_b_results:
        for relation in result.relations:
            subject_local = local_candidate_ids[(result.unit_id, relation.subject)]
            object_local = local_candidate_ids[(result.unit_id, relation.object)]
            subject = candidate_to_canonical[subject_local]
            object_id = candidate_to_canonical[object_local]
            if subject == object_id:
                continue
            key = (subject, relation.predicate, object_id)
            relations[key] = relation.model_copy(
                update={
                    "id": _stable_id("relation", *key),
                    "subject": subject,
                    "object": object_id,
                }
            )
    for group in merge_plan.merge_groups:
        if group.parent_candidate_id is None:
            continue
        key = (
            group.canonical_candidate_id,
            "part_of",
            group.parent_candidate_id,
        )
        relations[key] = RelationAssertion(
            id=_stable_id("relation", *key),
            subject=key[0],
            predicate=key[1],
            object=key[2],
            assertion_status=AssertionStatus.AI_INFERRED,
            confidence=0.5,
            evidence_block_ids=candidate_by_id[key[0]].note.evidence_block_ids,
            review_status=ReviewStatus.PENDING,
        )

    conflicts: dict[str, ConflictCandidate] = {}
    for result in stage_b_results:
        for conflict in result.conflicts:
            stable_id = _stable_id("conflict", result.unit_id, conflict.id)
            conflicts[stable_id] = conflict.model_copy(update={"id": stable_id})

    return KnowledgeBundle(
        document_id=str(document.id),
        notes=notes,
        relations=tuple(relations.values()),
        conflicts=tuple(conflicts.values()),
    )


__all__ = [
    "PipelineCandidate",
    "assemble_knowledge_bundle",
    "build_stage_a_input",
    "build_stage_b_inputs",
    "build_stage_c_input",
    "build_stage_d_input",
    "pipeline_candidates",
]
