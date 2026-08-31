"""Semantic-preservation contracts between document evidence and knowledge facts.

This module does not claim to prove arbitrary natural-language semantics.  It
implements the product-enforceable invariants that must hold before a derived
knowledge object is eligible for promotion: evidence IDs must still resolve,
cell attachments must still belong to the referenced table blocks, source
references must remain bound to the same document/version, and declared
critical tokens must still be present in the attached evidence.

Violations return a *local* quarantine scope (blocks/pages) so the caller can
rerender or route only the affected evidence through a stronger parser and then
reverify, instead of rebuilding an entire document or world by default.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .models import CanonicalBlock, CanonicalDocument

__all__ = [
    "PreservationInvariant",
    "PreservationViolation",
    "SemanticEvidenceBinding",
    "SemanticPreservationReport",
    "verify_semantic_preservation",
]


class PreservationInvariant(StrEnum):
    SOURCE_BLOCK_EXISTS = "source_block_exists"
    SOURCE_CELL_EXISTS = "source_cell_exists"
    SOURCE_DOCUMENT_VERSION = "source_document_version"
    CRITICAL_TOKEN_PRESERVED = "critical_token_preserved"


@dataclass(frozen=True, slots=True)
class SemanticEvidenceBinding:
    """Evidence attachment for one claim/entity/relation/world fact."""

    knowledge_id: str
    knowledge_kind: str
    source_block_ids: tuple[str, ...]
    source_cell_ids: tuple[str, ...] = ()
    critical_tokens: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.knowledge_id or not self.knowledge_kind:
            raise ValueError("knowledge_id and knowledge_kind are required")
        if not self.source_block_ids:
            raise ValueError("semantic evidence bindings require source blocks")
        if any(not value for value in (*self.source_block_ids, *self.source_cell_ids)):
            raise ValueError("source IDs cannot be empty")
        if any(not token.strip() for token in self.critical_tokens):
            raise ValueError("critical tokens cannot be empty")


@dataclass(frozen=True, slots=True)
class PreservationViolation:
    knowledge_id: str
    invariant: PreservationInvariant
    detail: str
    source_block_ids: tuple[str, ...]
    page_indexes0: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class SemanticPreservationReport:
    checked_bindings: int
    violations: tuple[PreservationViolation, ...]
    quarantine_block_ids: tuple[str, ...]
    quarantine_page_indexes0: tuple[int, ...]
    recovery_action: str = "rerender_or_stronger_parser_then_reverify"

    @property
    def passed(self) -> bool:
        return not self.violations


def _normalize_text(value: str) -> str:
    return " ".join(value.casefold().split())


def _block_text(block: CanonicalBlock) -> str:
    pieces = [
        block.raw_text or "",
        block.normalized_text or "",
        block.markdown or "",
        block.sanitized_html or "",
        block.formula_latex or "",
    ]
    if block.table is not None:
        for cell in block.table.cells:
            pieces.extend((cell.raw_text, cell.normalized_text))
    return "\n".join(piece for piece in pieces if piece)


def _pages(blocks: tuple[CanonicalBlock, ...]) -> tuple[int, ...]:
    return tuple(
        sorted({source.page_index0 for block in blocks for source in block.source_refs})
    )


def verify_semantic_preservation(
    document: CanonicalDocument,
    bindings: tuple[SemanticEvidenceBinding, ...],
) -> SemanticPreservationReport:
    """Verify evidence-preservation invariants and derive local repair scope."""

    block_by_id = {block.id: block for block in document.blocks}
    violations: list[PreservationViolation] = []
    quarantine_blocks: set[str] = set()
    quarantine_pages: set[int] = set()

    for binding in bindings:
        resolved_blocks = tuple(
            block_by_id[block_id]
            for block_id in binding.source_block_ids
            if block_id in block_by_id
        )
        missing_blocks = tuple(
            block_id for block_id in binding.source_block_ids if block_id not in block_by_id
        )
        if missing_blocks:
            violations.append(
                PreservationViolation(
                    knowledge_id=binding.knowledge_id,
                    invariant=PreservationInvariant.SOURCE_BLOCK_EXISTS,
                    detail=f"missing source blocks: {', '.join(missing_blocks)}",
                    source_block_ids=binding.source_block_ids,
                    page_indexes0=_pages(resolved_blocks),
                )
            )
            quarantine_blocks.update(binding.source_block_ids)
            quarantine_pages.update(_pages(resolved_blocks))

        wrong_version_blocks: list[str] = []
        for block in resolved_blocks:
            for source in block.source_refs:
                if (
                    source.document_id != document.document_id
                    or source.document_version_id != document.document_version_id
                ):
                    wrong_version_blocks.append(block.id)
                    quarantine_pages.add(source.page_index0)
                    break
            if block.table is not None:
                for cell in block.table.cells:
                    for source in cell.source_refs:
                        if (
                            source.document_id != document.document_id
                            or source.document_version_id != document.document_version_id
                        ):
                            wrong_version_blocks.append(block.id)
                            quarantine_pages.add(source.page_index0)
                            break
        if wrong_version_blocks:
            unique = tuple(sorted(set(wrong_version_blocks)))
            violations.append(
                PreservationViolation(
                    knowledge_id=binding.knowledge_id,
                    invariant=PreservationInvariant.SOURCE_DOCUMENT_VERSION,
                    detail="evidence points outside the canonical document/version",
                    source_block_ids=unique,
                    page_indexes0=_pages(tuple(block_by_id[item] for item in unique)),
                )
            )
            quarantine_blocks.update(unique)

        cell_by_id = {
            cell.id: cell
            for block in resolved_blocks
            if block.table is not None
            for cell in block.table.cells
        }
        missing_cells = tuple(
            cell_id for cell_id in binding.source_cell_ids if cell_id not in cell_by_id
        )
        if missing_cells:
            pages = _pages(resolved_blocks)
            violations.append(
                PreservationViolation(
                    knowledge_id=binding.knowledge_id,
                    invariant=PreservationInvariant.SOURCE_CELL_EXISTS,
                    detail=f"missing or detached source cells: {', '.join(missing_cells)}",
                    source_block_ids=binding.source_block_ids,
                    page_indexes0=pages,
                )
            )
            quarantine_blocks.update(binding.source_block_ids)
            quarantine_pages.update(pages)

        if binding.critical_tokens and resolved_blocks:
            if binding.source_cell_ids and not missing_cells:
                evidence_text = "\n".join(
                    f"{cell.raw_text}\n{cell.normalized_text}"
                    for cell_id, cell in cell_by_id.items()
                    if cell_id in binding.source_cell_ids
                )
            else:
                evidence_text = "\n".join(_block_text(block) for block in resolved_blocks)
            normalized_evidence = _normalize_text(evidence_text)
            missing_tokens = tuple(
                token
                for token in binding.critical_tokens
                if _normalize_text(token) not in normalized_evidence
            )
            if missing_tokens:
                pages = _pages(resolved_blocks)
                violations.append(
                    PreservationViolation(
                        knowledge_id=binding.knowledge_id,
                        invariant=PreservationInvariant.CRITICAL_TOKEN_PRESERVED,
                        detail=f"critical evidence tokens missing: {', '.join(missing_tokens)}",
                        source_block_ids=binding.source_block_ids,
                        page_indexes0=pages,
                    )
                )
                quarantine_blocks.update(binding.source_block_ids)
                quarantine_pages.update(pages)

    return SemanticPreservationReport(
        checked_bindings=len(bindings),
        violations=tuple(violations),
        quarantine_block_ids=tuple(sorted(quarantine_blocks)),
        quarantine_page_indexes0=tuple(sorted(quarantine_pages)),
    )
