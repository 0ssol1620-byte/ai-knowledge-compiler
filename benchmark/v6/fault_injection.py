"""Deterministic semantic-fault injection for recovery detector campaigns."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from akc_parallel_runtime import FailureCode, canonical_sha256


@dataclass(frozen=True, slots=True)
class RecoveryBenchmarkSample:
    item_id: str
    text_blocks: tuple[str, ...]
    table_rows: tuple[tuple[str, ...], ...]
    source_refs: tuple[str, ...]
    reading_order: tuple[int, ...]
    page_ids: tuple[str, ...] = ("page-1", "page-2")
    formula_blocks: tuple[str, ...] = ("x^2 + y^2 = z^2",)
    knowledge_notes: tuple[str, ...] = ("Revenue increased in the reported period.",)
    entities: tuple[str, ...] = ("Company", "Revenue")
    relations: tuple[tuple[str, str, str], ...] = (
        ("Company", "reports", "Revenue"),
    )

    def __post_init__(self) -> None:
        if (
            not self.item_id
            or not self.text_blocks
            or not self.source_refs
            or not self.page_ids
        ):
            raise ValueError("recovery benchmark samples require text and source evidence")


@dataclass(frozen=True, slots=True)
class InjectedFault:
    code: FailureCode
    source_sha256: str
    corrupted_sha256: str
    sample: RecoveryBenchmarkSample


def inject_fault(sample: RecoveryBenchmarkSample, code: FailureCode) -> InjectedFault:
    """Inject one controlled fault while preserving an immutable baseline digest."""

    if sample.reading_order != tuple(range(len(sample.text_blocks))):
        raise ValueError("fault injection baseline reading order must be canonical")
    source_sha256 = canonical_sha256(sample)
    corrupted = _inject(sample, code)
    corrupted_sha256 = canonical_sha256(corrupted)
    if corrupted_sha256 == source_sha256:
        raise ValueError(f"fault injection did not change the sample: {code}")
    return InjectedFault(code, source_sha256, corrupted_sha256, corrupted)


def detect_faults(
    authority: RecoveryBenchmarkSample,
    candidate: RecoveryBenchmarkSample,
) -> frozenset[FailureCode]:
    """Detect the masterplan taxonomy against source/authority-bound structure."""

    failures: set[FailureCode] = set()
    if set(authority.page_ids) - set(candidate.page_ids):
        failures.add(FailureCode.PAGE_OMISSION)
    if len(candidate.text_blocks) < len(authority.text_blocks):
        failures.add(FailureCode.BLOCK_OMISSION)

    authority_rows = authority.table_rows
    candidate_rows = candidate.table_rows
    if candidate_rows and authority_rows:
        if set(candidate_rows[0]) != set(authority_rows[0]):
            failures.add(FailureCode.WRONG_TABLE)
        elif candidate_rows[0] != authority_rows[0]:
            failures.add(FailureCode.COLUMN_SHIFT)
        elif len(candidate_rows) > len(authority_rows):
            failures.add(FailureCode.EXTRA_ROWS)
        elif len(candidate_rows) < len(authority_rows):
            failures.add(
                FailureCode.BOTTOM_ROW_OMISSION
                if candidate_rows == authority_rows[: len(candidate_rows)]
                else FailureCode.MIDDLE_ROW_OMISSION
            )

    if candidate.text_blocks != authority.text_blocks and len(
        candidate.text_blocks
    ) == len(authority.text_blocks):
        authority_numbers = _numbers(authority.text_blocks)
        candidate_numbers = _numbers(candidate.text_blocks)
        if authority_numbers != candidate_numbers:
            if len(authority_numbers) == len(candidate_numbers) and any(
                _scale_or_sign_changed(before, after)
                for before, after in zip(authority_numbers, candidate_numbers, strict=True)
            ):
                failures.add(FailureCode.SIGN_SCALE_ERROR)
            else:
                failures.add(FailureCode.DIGIT_MUTATION)

    if candidate.reading_order != tuple(range(len(candidate.text_blocks))):
        failures.add(FailureCode.READING_ORDER)
    if "split://page-boundary" in candidate.source_refs:
        failures.add(FailureCode.CROSS_PAGE_SPLIT)
    elif candidate.source_refs != authority.source_refs:
        failures.add(FailureCode.GROUNDING_MISMATCH)
    if candidate.formula_blocks != authority.formula_blocks:
        failures.add(FailureCode.FORMULA_CORRUPTION)

    if len(candidate.text_blocks) > len(authority.text_blocks):
        additions = candidate.text_blocks[len(authority.text_blocks) :]
        if any(block in authority.text_blocks for block in additions):
            failures.add(FailureCode.REPETITION)
        else:
            failures.add(FailureCode.HALLUCINATION)
    if candidate.knowledge_notes != authority.knowledge_notes:
        failures.add(FailureCode.NOTE_SPLIT_ERROR)
    if candidate.entities != authority.entities:
        failures.add(FailureCode.WRONG_ENTITY_MERGE)
    if candidate.relations != authority.relations:
        failures.add(FailureCode.UNSUPPORTED_RELATION)
    return frozenset(failures)


def _inject(sample: RecoveryBenchmarkSample, code: FailureCode) -> RecoveryBenchmarkSample:
    if code is FailureCode.PAGE_OMISSION:
        if len(sample.page_ids) < 2:
            raise ValueError("page omission needs at least two pages")
        return replace(sample, page_ids=sample.page_ids[:-1])
    if code is FailureCode.BLOCK_OMISSION:
        if len(sample.text_blocks) < 2:
            raise ValueError("block omission needs at least two blocks")
        blocks = sample.text_blocks[:-1]
        return replace(sample, text_blocks=blocks, reading_order=tuple(range(len(blocks))))
    if code is FailureCode.BOTTOM_ROW_OMISSION:
        if len(sample.table_rows) < 2:
            raise ValueError("bottom-row omission needs at least two rows")
        return replace(sample, table_rows=sample.table_rows[:-1])
    if code is FailureCode.MIDDLE_ROW_OMISSION:
        if len(sample.table_rows) < 3:
            raise ValueError("middle-row omission needs at least three rows")
        middle = len(sample.table_rows) // 2
        return replace(
            sample,
            table_rows=sample.table_rows[:middle] + sample.table_rows[middle + 1 :],
        )
    if code is FailureCode.EXTRA_ROWS:
        return replace(sample, table_rows=(*sample.table_rows, sample.table_rows[-1]))
    if code is FailureCode.WRONG_TABLE:
        return replace(sample, table_rows=(("Wrong", "Table"), ("X", "999")))
    if code is FailureCode.COLUMN_SHIFT:
        if not sample.table_rows or len(sample.table_rows[0]) < 2:
            raise ValueError("column-shift injection needs at least two columns")
        first = sample.table_rows[0]
        shifted = (first[-1], *first[:-1])
        return replace(sample, table_rows=(shifted, *sample.table_rows[1:]))
    if code is FailureCode.DIGIT_MUTATION:
        return _mutate_first_digit(sample)
    if code is FailureCode.SIGN_SCALE_ERROR:
        numeric_blocks = list(sample.text_blocks)
        for index, text in enumerate(numeric_blocks):
            match = re.search(r"\d+(?:\.\d+)?", text)
            if match is not None:
                numeric_blocks[index] = (
                    text[: match.start()] + match.group() + "0" + text[match.end() :]
                )
                return replace(sample, text_blocks=tuple(numeric_blocks))
        raise ValueError("sign/scale injection requires at least one number")
    if code is FailureCode.READING_ORDER:
        if len(sample.text_blocks) < 2:
            raise ValueError("reading-order injection needs at least two blocks")
        order = list(sample.reading_order)
        order[0], order[1] = order[1], order[0]
        return replace(sample, reading_order=tuple(order))
    if code is FailureCode.CROSS_PAGE_SPLIT:
        return replace(sample, source_refs=(*sample.source_refs, "split://page-boundary"))
    if code is FailureCode.FORMULA_CORRUPTION:
        return replace(sample, formula_blocks=("x^2 + y^2 = q^2",))
    if code is FailureCode.GROUNDING_MISMATCH:
        return replace(sample, source_refs=("bbox://wrong-region",))
    if code is FailureCode.HALLUCINATION:
        blocks = (*sample.text_blocks, "unsupported generated statement")
        return replace(sample, text_blocks=blocks, reading_order=tuple(range(len(blocks))))
    if code is FailureCode.REPETITION:
        blocks = (*sample.text_blocks, sample.text_blocks[-1])
        return replace(sample, text_blocks=blocks, reading_order=tuple(range(len(blocks))))
    if code is FailureCode.NOTE_SPLIT_ERROR:
        return replace(sample, knowledge_notes=("Revenue", "increased in the period."))
    if code is FailureCode.WRONG_ENTITY_MERGE:
        return replace(sample, entities=("Company+Revenue",))
    if code is FailureCode.UNSUPPORTED_RELATION:
        return replace(
            sample,
            relations=(*sample.relations, ("Revenue", "proves", "Unsupported")),
        )
    raise ValueError(f"unsupported fault injection code: {code}")


def _mutate_first_digit(sample: RecoveryBenchmarkSample) -> RecoveryBenchmarkSample:
    numeric_blocks = list(sample.text_blocks)
    for index, text in enumerate(numeric_blocks):
        match = re.search(r"\d", text)
        if match is not None:
            digit = str((int(match.group()) + 1) % 10)
            numeric_blocks[index] = text[: match.start()] + digit + text[match.end() :]
            return replace(sample, text_blocks=tuple(numeric_blocks))
    raise ValueError("digit-mutation injection requires at least one digit")


def _numbers(blocks: tuple[str, ...]) -> tuple[float, ...]:
    return tuple(
        float(match.group())
        for block in blocks
        for match in re.finditer(r"[-+]?\d+(?:\.\d+)?", block.replace(",", ""))
    )


def _scale_or_sign_changed(before: float, after: float) -> bool:
    if before == 0:
        return after == 0
    return after in {-before, before * 10, before / 10, before * 1000, before / 1000}


__all__ = ["InjectedFault", "RecoveryBenchmarkSample", "detect_faults", "inject_fault"]
