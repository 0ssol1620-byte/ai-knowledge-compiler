from __future__ import annotations

import pytest
from akc_api.block_merge import three_way_merge


@pytest.mark.parametrize(
    ("base", "user", "model", "locked", "status", "merged"),
    [
        ("base\n", "base\n", "model\n", True, "model_replaced", "model\n"),
        ("base\n", "user\n", "base\n", True, "kept_user", "user\n"),
        ("base\n", "same\n", "same\n", True, "unchanged", "same\n"),
        ("base\n", "user\n", "model\n", False, "model_replaced", "model\n"),
    ],
)
def test_three_way_merge_fast_paths(
    base: str,
    user: str,
    model: str,
    locked: bool,
    status: str,
    merged: str,
) -> None:
    result = three_way_merge(
        base=base,
        user=user,
        new_model=model,
        user_locked=locked,
    )
    assert result.status == status
    assert result.merged == merged
    assert result.conflict_count == 0


def test_three_way_merge_combines_non_overlapping_user_and_model_edits() -> None:
    result = three_way_merge(
        base="title\nalpha\nbeta\nomega\n",
        user="User title\nalpha\nbeta\nomega\n",
        new_model="title\nalpha\nModel beta\nomega\n",
        user_locked=True,
    )
    assert result.status == "auto_merged"
    assert result.merged == "User title\nalpha\nModel beta\nomega\n"
    assert result.conflict_count == 0


def test_three_way_merge_returns_all_sides_without_conflict_markers() -> None:
    result = three_way_merge(
        base="title\nbody\n",
        user="User title\nbody\n",
        new_model="Model title\nbody\n",
        user_locked=True,
    )
    assert result.status == "conflict"
    assert result.merged is None
    assert result.conflict_count == 1
