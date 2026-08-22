"""Context-aware deterministic sharding with explicit page ownership."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from math import ceil
from typing import ClassVar

from .identity import require_sha256, stable_id
from .models import PageClass


class ContinuitySignal(StrEnum):
    REPEATED_TABLE_HEADER = "repeated_table_header"
    TABLE_CUT = "table_cut"
    COLUMN_STRUCTURE_CONTINUES = "column_structure_continues"
    INCOMPLETE_SENTENCE = "incomplete_sentence"
    HEADING_BODY = "heading_body"
    FIGURE_CAPTION = "figure_caption"
    FOOTNOTE_REFERENCE = "footnote_reference"
    NUMBERED_LIST = "numbered_list"
    APPENDIX_TABLE = "appendix_table"
    SAME_TEMPLATE = "same_template"


@dataclass(frozen=True, slots=True)
class PageDescriptor:
    page_id: str
    index0: int
    page_class: PageClass
    width_px: int
    height_px: int
    token_estimate: int
    expected_output_tokens: int
    table_density: float = 0.0
    formula_density: float = 0.0
    prior_latency_seconds: float = 0.0
    prior_oom: bool = False
    continuity_to_next: frozenset[ContinuitySignal] = frozenset()

    def __post_init__(self) -> None:
        if not self.page_id or self.index0 < 0:
            raise ValueError("page_id must be non-empty and index0 must be non-negative")
        if self.width_px < 1 or self.height_px < 1:
            raise ValueError("page dimensions must be positive")
        if self.token_estimate < 0 or self.expected_output_tokens < 0:
            raise ValueError("token estimates cannot be negative")
        if not 0 <= self.table_density <= 1 or not 0 <= self.formula_density <= 1:
            raise ValueError("density values must be between 0 and 1")
        if self.prior_latency_seconds < 0:
            raise ValueError("prior latency cannot be negative")

    @property
    def pixels(self) -> int:
        return self.width_px * self.height_px


@dataclass(frozen=True, slots=True)
class ShardSizing:
    pages_per_shard: int
    max_pixels: int
    expected_seconds: float
    required_worker_class: str
    overlap_pages: int


@dataclass(frozen=True, slots=True)
class ParseShard:
    shard_id: str
    document_id: str
    document_version_id: str
    ordinal: int
    primary_page_ids: tuple[str, ...]
    context_page_ids: tuple[str, ...]
    ordered_input_page_ids: tuple[str, ...]
    expected_seconds: float
    required_worker_class: str
    policy_version: str

    def __post_init__(self) -> None:
        expected = set(self.primary_page_ids) | set(self.context_page_ids)
        if set(self.ordered_input_page_ids) != expected or len(
            self.ordered_input_page_ids
        ) != len(expected):
            raise ValueError("ordered input pages must exactly cover primary and context pages")

    @property
    def input_page_ids(self) -> tuple[str, ...]:
        return self.ordered_input_page_ids


@dataclass(frozen=True, slots=True)
class ShardPlan:
    document_id: str
    document_version_id: str
    source_sha256: str
    shards: tuple[ParseShard, ...]
    policy_version: str

    def __post_init__(self) -> None:
        require_sha256(self.source_sha256, field_name="source_sha256")
        if not self.shards:
            raise ValueError("a shard plan cannot be empty")
        owned = [page_id for shard in self.shards for page_id in shard.primary_page_ids]
        if len(owned) != len(set(owned)):
            raise ValueError("each page must have exactly one primary owner")
        if any(set(shard.primary_page_ids) & set(shard.context_page_ids) for shard in self.shards):
            raise ValueError("context pages cannot also be primary pages in the same shard")

    @property
    def owned_page_ids(self) -> tuple[str, ...]:
        return tuple(page_id for shard in self.shards for page_id in shard.primary_page_ids)


class AdaptiveShardPredictor:
    """Rule-calibrated bootstrap predictor with deterministic safety bounds."""

    _BASE_TARGETS: ClassVar[dict[PageClass, int]] = {
        PageClass.NATIVE_CLEAN: 32,
        PageClass.NORMAL_SCAN: 8,
        PageClass.COMPLEX_LAYOUT: 4,
        PageClass.INDEPENDENT: 2,
        PageClass.LONG_TABLE: 16,
        PageClass.FORMULA_HEAVY: 2,
        PageClass.PHOTOGRAPHED: 2,
        PageClass.OFFICE_STRUCTURED: 16,
    }

    def __init__(
        self,
        *,
        model_context_tokens: int = 32_768,
        vram_gib: int = 24,
        policy_version: str = "adaptive-shard-v2-bootstrap",
    ) -> None:
        if model_context_tokens < 1_024 or vram_gib < 1:
            raise ValueError("model context and VRAM must be positive production values")
        self.model_context_tokens = model_context_tokens
        self.vram_gib = vram_gib
        self.policy_version = policy_version

    def predict(self, page: PageDescriptor) -> ShardSizing:
        target = self._BASE_TARGETS[page.page_class]
        total_tokens = max(1, page.token_estimate + page.expected_output_tokens)
        context_target = max(1, int(self.model_context_tokens * 0.72) // total_tokens)
        target = min(target, context_target)
        if page.table_density >= 0.35 or page.formula_density >= 0.10:
            target = max(1, target // 2)
        if page.prior_oom:
            target = max(1, target // 2)
        if self.vram_gib < 16:
            target = max(1, target // 2)
        pixels_per_page = page.pixels
        max_pixels = min(pixels_per_page * target, max(pixels_per_page, self.vram_gib * 1_500_000))
        complexity = 1.0 + page.table_density * 1.5 + page.formula_density * 2.0
        baseline_seconds = max(
            page.prior_latency_seconds,
            0.25 + total_tokens / 1_200 + pixels_per_page / 8_000_000,
        )
        expected_seconds = round(
            baseline_seconds * complexity,
            6,
        )
        if page.page_class in {PageClass.COMPLEX_LAYOUT, PageClass.LONG_TABLE}:
            worker_class = "large_context_precision"
        elif page.page_class in {PageClass.FORMULA_HEAVY, PageClass.PHOTOGRAPHED}:
            worker_class = "vision_precision"
        else:
            worker_class = "standard"
        overlap = 2 if page.continuity_to_next or page.page_class is PageClass.LONG_TABLE else 1
        return ShardSizing(
            pages_per_shard=target,
            max_pixels=max_pixels,
            expected_seconds=expected_seconds,
            required_worker_class=worker_class,
            overlap_pages=overlap,
        )


class DeterministicShardPlanner:
    def __init__(self, predictor: AdaptiveShardPredictor) -> None:
        self.predictor = predictor

    @staticmethod
    def _validate_pages(pages: tuple[PageDescriptor, ...]) -> None:
        if not pages:
            raise ValueError("cannot plan an empty document")
        if tuple(sorted(pages, key=lambda page: page.index0)) != pages:
            raise ValueError("pages must be ordered by index0")
        if len({page.page_id for page in pages}) != len(pages):
            raise ValueError("page ids must be unique")
        if len({page.index0 for page in pages}) != len(pages):
            raise ValueError("page indexes must be unique")
        if pages[-1].continuity_to_next:
            raise ValueError("the final page cannot declare continuity to a missing page")

    @staticmethod
    def _atomic_groups(pages: tuple[PageDescriptor, ...]) -> tuple[tuple[PageDescriptor, ...], ...]:
        groups: list[tuple[PageDescriptor, ...]] = []
        current: list[PageDescriptor] = []
        for page in pages:
            current.append(page)
            if not page.continuity_to_next:
                groups.append(tuple(current))
                current = []
        if current:
            groups.append(tuple(current))
        return tuple(groups)

    def plan(
        self,
        *,
        document_id: str,
        document_version_id: str,
        source_sha256: str,
        pages: tuple[PageDescriptor, ...],
    ) -> ShardPlan:
        self._validate_pages(pages)
        groups = self._atomic_groups(pages)
        primary_groups: list[tuple[PageDescriptor, ...]] = []
        current: list[PageDescriptor] = []
        current_limit = 2**31 - 1
        for group in groups:
            group_limit = min(self.predictor.predict(page).pages_per_shard for page in group)
            proposed_limit = min(current_limit, group_limit)
            if current and len(current) + len(group) > proposed_limit:
                primary_groups.append(tuple(current))
                current = []
                current_limit = 2**31 - 1
            current.extend(group)
            current_limit = min(current_limit, group_limit)
        if current:
            primary_groups.append(tuple(current))

        page_by_id = {page.page_id: page for page in pages}
        planned: list[ParseShard] = []
        for ordinal, group in enumerate(primary_groups):
            first_index = group[0].index0
            last_index = group[-1].index0
            overlap = max(self.predictor.predict(page).overlap_pages for page in group)
            context = tuple(
                page.page_id
                for page in pages
                if page.index0 not in range(first_index, last_index + 1)
                and (
                    first_index - overlap <= page.index0 < first_index
                    or last_index < page.index0 <= last_index + overlap
                )
            )
            expected_seconds = round(
                sum(self.predictor.predict(page).expected_seconds for page in group), 6
            )
            worker_classes = {
                self.predictor.predict(page).required_worker_class for page in group
            }
            total_tokens = sum(
                page.token_estimate + page.expected_output_tokens for page in group
            )
            requires_oversize_worker = total_tokens > int(
                self.predictor.model_context_tokens * 0.72
            )
            if "large_context_precision" in worker_classes or requires_oversize_worker:
                worker_class = "large_context_precision"
            elif "vision_precision" in worker_classes:
                worker_class = "vision_precision"
            else:
                worker_class = "standard"
            primary_ids = tuple(page.page_id for page in group)
            ordered_input_ids = tuple(
                page.page_id
                for page in pages
                if page.page_id in set(primary_ids) | set(context)
            )
            shard_id = stable_id(
                "shard",
                document_id,
                document_version_id,
                source_sha256,
                self.predictor.policy_version,
                primary_ids,
            )
            planned.append(
                ParseShard(
                    shard_id=shard_id,
                    document_id=document_id,
                    document_version_id=document_version_id,
                    ordinal=ordinal,
                    primary_page_ids=primary_ids,
                    context_page_ids=tuple(
                        sorted(context, key=lambda page_id: page_by_id[page_id].index0)
                    ),
                    ordered_input_page_ids=ordered_input_ids,
                    expected_seconds=expected_seconds,
                    required_worker_class=worker_class,
                    policy_version=self.predictor.policy_version,
                )
            )
        return ShardPlan(
            document_id=document_id,
            document_version_id=document_version_id,
            source_sha256=source_sha256,
            shards=tuple(planned),
            policy_version=self.predictor.policy_version,
        )


def deterministic_benchmark_assignments(
    document_groups: dict[str, tuple[str, ...]], shard_count: int
) -> dict[int, tuple[str, ...]]:
    """Assign whole document groups by SHA-256, never Python's salted hash."""

    if shard_count < 1:
        raise ValueError("shard_count must be positive")
    assignments: dict[int, list[str]] = {index: [] for index in range(shard_count)}
    for group_id in sorted(document_groups):
        pages = document_groups[group_id]
        if not pages or len(set(pages)) != len(pages):
            raise ValueError("benchmark document groups require unique non-empty page ids")
        group_hash = sha256(group_id.encode("utf-8")).digest()
        shard_index = int.from_bytes(group_hash[:8], "big") % shard_count
        assignments[shard_index].extend(pages)
    return {index: tuple(page_ids) for index, page_ids in assignments.items()}


def ideal_worker_target(
    total_remaining_predicted_seconds: float,
    desired_completion_window_seconds: float,
    *,
    provider_limit: int,
    account_limit: int,
    queue_limit: int,
    evaluator_limit: int,
    database_limit: int,
) -> int:
    if total_remaining_predicted_seconds < 0 or desired_completion_window_seconds <= 0:
        raise ValueError("remaining work must be non-negative and completion window positive")
    limits = (provider_limit, account_limit, queue_limit, evaluator_limit, database_limit)
    if any(limit < 0 for limit in limits):
        raise ValueError("worker limits cannot be negative")
    unconstrained = ceil(total_remaining_predicted_seconds / desired_completion_window_seconds)
    return min(
        unconstrained,
        provider_limit,
        account_limit,
        queue_limit,
        evaluator_limit,
        database_limit,
    )


__all__ = [
    "AdaptiveShardPredictor",
    "ContinuitySignal",
    "DeterministicShardPlanner",
    "PageDescriptor",
    "ParseShard",
    "ShardPlan",
    "ShardSizing",
    "deterministic_benchmark_assignments",
    "ideal_worker_target",
]
