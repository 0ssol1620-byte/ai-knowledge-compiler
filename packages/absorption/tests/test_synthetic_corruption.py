from __future__ import annotations

from akc_absorption.synthetic_corruption import CorruptionKind, generate_corruptions

TEXT = "Header | Value\nWeight | -10 kg\nDate | 2026-08-15\nPrice | USD 1250"


def test_corruption_suite_is_reproducible_and_covers_all_declared_families() -> None:
    first = generate_corruptions(TEXT, seed=42, nearby_page_text="NEXT PAGE SECRET 99")
    second = generate_corruptions(TEXT, seed=42, nearby_page_text="NEXT PAGE SECRET 99")
    assert first == second
    assert {item.kind for item in first} == set(CorruptionKind)
    assert all(item.expected_failure_family for item in first)
    assert all(item.changed for item in first)