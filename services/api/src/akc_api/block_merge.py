"""Deterministic line-level three-way merge for model reruns."""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from typing import Literal

MergeStatus = Literal[
    "unchanged",
    "model_replaced",
    "kept_user",
    "auto_merged",
    "conflict",
]


@dataclass(frozen=True, slots=True)
class TextEdit:
    start: int
    end: int
    replacement: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ThreeWayMerge:
    status: MergeStatus
    merged: str | None
    conflict_count: int


def _edits(base: list[str], variant: list[str]) -> list[TextEdit]:
    matcher = difflib.SequenceMatcher(a=base, b=variant, autojunk=False)
    return [
        TextEdit(start=i1, end=i2, replacement=tuple(variant[j1:j2]))
        for tag, i1, i2, j1, j2 in matcher.get_opcodes()
        if tag != "equal"
    ]


def _same_edit(left: TextEdit, right: TextEdit) -> bool:
    return (
        left.start == right.start
        and left.end == right.end
        and left.replacement == right.replacement
    )


def _overlaps(left: TextEdit, right: TextEdit) -> bool:
    if _same_edit(left, right):
        return False
    left_insert = left.start == left.end
    right_insert = right.start == right.end
    if left_insert and right_insert:
        return left.start == right.start
    if left_insert:
        return right.start <= left.start <= right.end
    if right_insert:
        return left.start <= right.start <= left.end
    return max(left.start, right.start) < min(left.end, right.end)


def three_way_merge(
    *,
    base: str,
    user: str,
    new_model: str,
    user_locked: bool,
) -> ThreeWayMerge:
    """Merge non-overlapping edits; preserve every locked user change."""

    if not user_locked:
        return ThreeWayMerge(
            status="unchanged" if user == new_model else "model_replaced",
            merged=new_model,
            conflict_count=0,
        )
    if user == new_model:
        return ThreeWayMerge(status="unchanged", merged=user, conflict_count=0)
    if user == base:
        return ThreeWayMerge(status="model_replaced", merged=new_model, conflict_count=0)
    if new_model == base:
        return ThreeWayMerge(status="kept_user", merged=user, conflict_count=0)

    base_lines = base.splitlines(keepends=True)
    user_edits = _edits(base_lines, user.splitlines(keepends=True))
    model_edits = _edits(base_lines, new_model.splitlines(keepends=True))
    conflicts = sum(
        _overlaps(user_edit, model_edit) for user_edit in user_edits for model_edit in model_edits
    )
    if conflicts:
        return ThreeWayMerge(status="conflict", merged=None, conflict_count=conflicts)

    combined: list[TextEdit] = [*user_edits]
    for model_edit in model_edits:
        if not any(_same_edit(model_edit, user_edit) for user_edit in user_edits):
            combined.append(model_edit)
    merged_lines = list(base_lines)
    for edit in sorted(
        combined,
        key=lambda value: (value.start, value.end),
        reverse=True,
    ):
        merged_lines[edit.start : edit.end] = edit.replacement
    return ThreeWayMerge(
        status="auto_merged",
        merged="".join(merged_lines),
        conflict_count=0,
    )


__all__ = ["MergeStatus", "TextEdit", "ThreeWayMerge", "three_way_merge"]
