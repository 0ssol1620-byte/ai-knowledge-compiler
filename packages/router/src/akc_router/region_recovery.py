"""Source-bound text-region projection and fail-closed recovery candidates.

The module turns exact CIR ``SourceRef`` geometry into execution bindings and
can package verified replacements for a later compiler step.  It never invents
coordinates, rewrites a ``CanonicalDocument`` or promotes a World.  Missing,
multi-region or overlapping geometry remains unresolved.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from akc_cir import BlockType, CanonicalDocument

from .document_execution import DocumentSourceBinding, DocumentTextExecutionResult
from .evidence_execution import (
    EvidenceDisposition,
    IndependentTextWitness,
    RegionBinding,
    TextObservation,
    text_digest,
)

_SHA = re.compile(r"^sha256:[a-f0-9]{64}$")
_TEXT_TYPES = frozenset(
    {
        BlockType.TITLE,
        BlockType.HEADING,
        BlockType.PARAGRAPH,
        BlockType.LIST,
        BlockType.CAPTION,
        BlockType.FORMULA,
        BlockType.CODE,
        BlockType.QUOTE,
        BlockType.FOOTNOTE,
        BlockType.HEADER,
        BlockType.FOOTER,
        BlockType.PAGE_NUMBER,
    }
)


def _opaque_id(prefix: str, *parts: object) -> str:
    payload = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return f"{prefix}:{hashlib.sha256(payload).hexdigest()}"


@dataclass(frozen=True, slots=True)
class NativeTextRegion:
    binding: RegionBinding
    block_id: str
    block_revision: int
    expected_content_sha256: str
    witness: IndependentTextWitness


@dataclass(frozen=True, slots=True)
class NativeRegionIssue:
    block_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class NativeRegionInventory:
    document_id: str
    document_version_id: str
    source_sha256: str
    representation_sha256: str
    eligible_text_block_count: int
    regions: tuple[NativeTextRegion, ...]
    unresolved: tuple[NativeRegionIssue, ...]

    @property
    def complete(self) -> bool:
        return self.eligible_text_block_count == len(self.regions) and not self.unresolved


def project_source_bound_text_regions(
    document: CanonicalDocument,
    *,
    expected_source_sha256: str,
    representation_sha256: str,
) -> NativeRegionInventory:
    """Project exact, single-bbox text blocks without fabricating geometry."""
    if document.source_sha256 != expected_source_sha256:
        raise ValueError("REGION_SOURCE_BINDING_MISMATCH")
    if not _SHA.fullmatch(representation_sha256):
        raise ValueError("REGION_REPRESENTATION_DIGEST_REQUIRED")

    regions: list[NativeTextRegion] = []
    unresolved: list[NativeRegionIssue] = []
    eligible = 0
    seen_region_ids: set[str] = set()
    for block in document.ordered_blocks():
        if block.type not in _TEXT_TYPES:
            continue
        text = block.raw_text or block.normalized_text or ""
        if not text.strip():
            continue
        eligible += 1
        refs = tuple(block.source_refs)
        if any(
            ref.document_id != document.document_id
            or ref.document_version_id != document.document_version_id
            for ref in refs
        ):
            raise ValueError("REGION_REFERENCE_IDENTITY_MISMATCH")
        if len(refs) != 1:
            unresolved.append(NativeRegionIssue(block.id, "REGION_SINGLE_SOURCE_REF_REQUIRED"))
            continue
        ref = refs[0]
        if ref.bbox1000 is None:
            unresolved.append(NativeRegionIssue(block.id, "REGION_GEOMETRY_UNMEASURED"))
            continue
        region_id = _opaque_id(
            "block",
            document.document_id,
            document.document_version_id,
            block.id,
            block.revision,
            ref.page_index0,
            ref.bbox1000.as_tuple(),
        )
        if region_id in seen_region_ids:
            raise ValueError("REGION_ID_COLLISION")
        seen_region_ids.add(region_id)
        binding = RegionBinding(
            expected_source_sha256,
            representation_sha256,
            ref.page_index0,
            region_id,
            ref.bbox1000.as_tuple(),
        )
        observation = TextObservation(
            binding,
            "native.source",
            text,
            text_digest(text),
        )
        regions.append(
            NativeTextRegion(
                binding,
                block.id,
                block.revision,
                block.content_hash,
                IndependentTextWitness(
                    observation,
                    _opaque_id(
                        "source-witness",
                        document.document_id,
                        document.document_version_id,
                        block.id,
                        block.content_hash,
                    ),
                    True,
                ),
            )
        )
    return NativeRegionInventory(
        document.document_id,
        document.document_version_id,
        document.source_sha256,
        representation_sha256,
        eligible,
        tuple(regions),
        tuple(unresolved),
    )


@dataclass(frozen=True, slots=True)
class VerifiedRegionReplacement:
    binding: RegionBinding
    block_id: str
    expected_block_revision: int
    expected_content_sha256: str
    replacement_text: str
    replacement_sha256: str
    producer_id: str


@dataclass(frozen=True, slots=True)
class RegionRecoveryCandidate:
    source: DocumentSourceBinding
    replacements: Mapping[str, VerifiedRegionReplacement]
    disposition: Literal["verified_candidate", "unresolved", "quarantined"]
    reasons: tuple[str, ...]
    verification_scope: Literal["declared_text_regions_only"] = "declared_text_regions_only"
    production_promotion: Literal[False] = False


def _overlap(
    left: tuple[int, int, int, int], right: tuple[int, int, int, int]
) -> bool:
    return max(left[0], right[0]) < min(left[2], right[2]) and max(
        left[1], right[1]
    ) < min(left[3], right[3])


def build_region_recovery_candidate(
    document: CanonicalDocument,
    *,
    inventory: NativeRegionInventory,
    execution: DocumentTextExecutionResult,
    target_region_ids: frozenset[str] | None = None,
) -> RegionRecoveryCandidate:
    """Bind verified region outputs to unchanged CIR blocks for later review.

    All targeted regions must verify.  A caller cannot merge a partial result,
    a stale block, a foreign representation or overlapping replacements through
    this contract.  The returned object is still only a candidate.
    """
    source = execution.source
    if (
        document.document_id != inventory.document_id
        or document.document_version_id != inventory.document_version_id
        or document.source_sha256 != inventory.source_sha256
        or source.source_version_id != document.document_version_id
        or source.source_sha256 != document.source_sha256
        or source.representation_sha256 != inventory.representation_sha256
    ):
        raise ValueError("RECOVERY_DOCUMENT_SOURCE_MISMATCH")
    all_projected = {region.binding.region_id: region for region in inventory.regions}
    targets = (
        frozenset(all_projected)
        if target_region_ids is None
        else frozenset(target_region_ids)
    )
    if not targets or not targets <= all_projected.keys():
        raise ValueError("RECOVERY_TARGET_REGION_INVALID")
    projected = {region_id: all_projected[region_id] for region_id in targets}
    if len(all_projected) != len(inventory.regions) or set(execution.regions) != set(projected):
        raise ValueError("RECOVERY_REGION_INVENTORY_MISMATCH")
    if inventory.unresolved and target_region_ids is None:
        return RegionRecoveryCandidate(
            source,
            MappingProxyType({}),
            "unresolved",
            ("SOURCE_REGION_INVENTORY_INCOMPLETE",),
        )
    if execution.disposition == "quarantined":
        return RegionRecoveryCandidate(
            source, MappingProxyType({}), "quarantined", ("EXECUTION_QUARANTINED",)
        )
    if execution.disposition != "verified_text_scope":
        return RegionRecoveryCandidate(
            source, MappingProxyType({}), "unresolved", ("EXECUTION_SCOPE_UNVERIFIED",)
        )

    blocks = {block.id: block for block in document.blocks}
    replacements: dict[str, VerifiedRegionReplacement] = {}
    accepted_regions: list[NativeTextRegion] = []
    for region_id, projection in projected.items():
        result = execution.regions[region_id]
        accepted = result.accepted
        if (
            result.binding != projection.binding
            or result.disposition is not EvidenceDisposition.VERIFIED_TEXT_REGION
            or accepted is None
            or accepted.binding != projection.binding
        ):
            return RegionRecoveryCandidate(
                source,
                MappingProxyType({}),
                "unresolved",
                ("REGION_RESULT_UNVERIFIED",),
            )
        block = blocks.get(projection.block_id)
        if (
            block is None
            or block.revision != projection.block_revision
            or block.content_hash != projection.expected_content_sha256
        ):
            raise ValueError("RECOVERY_BASE_BLOCK_CHANGED")
        for other in accepted_regions:
            if (
                other.binding.page_index0 == projection.binding.page_index0
                and _overlap(other.binding.bbox1000, projection.binding.bbox1000)
            ):
                return RegionRecoveryCandidate(
                    source,
                    MappingProxyType({}),
                    "unresolved",
                    ("RECOVERY_REGION_OVERLAP",),
                )
        accepted_regions.append(projection)
        replacements[projection.block_id] = VerifiedRegionReplacement(
            projection.binding,
            projection.block_id,
            projection.block_revision,
            projection.expected_content_sha256,
            accepted.text,
            accepted.output_sha256,
            accepted.producer_id,
        )
    return RegionRecoveryCandidate(
        source,
        MappingProxyType(dict(sorted(replacements.items()))),
        "verified_candidate",
        (),
    )
