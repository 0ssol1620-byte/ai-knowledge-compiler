"""A tail merge is the one place where a good result can be smuggled in.

The candidate overlay trusts run-summary.json over the directory, so whatever
this writes becomes the truth about what the retry delivered. Every refusal
below exists because the alternative is a summary that reads better than the
run it describes.
"""

from __future__ import annotations

import json

import pytest
from merge_tail_recovery import merge, plan_merge


def _summary(cases: list[tuple[str, str, int]]) -> dict:
    completed = sum(1 for _, status, _ in cases if status == "completed")
    return {
        "input_count": len(cases),
        "runs": [
            {
                "completed": completed,
                "failed": len(cases) - completed,
                "cases": [
                    {"case_id": cid, "status": status, "markdown_characters": chars}
                    for cid, status, chars in cases
                ],
            }
        ],
    }


def _write_suite(root, cases: list[tuple[str, str, int]]):
    root.mkdir(parents=True, exist_ok=True)
    (root / "run-summary.json").write_text(json.dumps(_summary(cases)), encoding="utf-8")
    markdown = root / "markdown-repeat-1"
    markdown.mkdir(exist_ok=True)
    for cid, status, _ in cases:
        if status == "completed":
            (markdown / f"{cid}.md").write_text(f"# {cid}", encoding="utf-8")
    return root


def test_a_lost_case_is_accepted(tmp_path) -> None:
    collected = _summary([("a", "completed", 10), ("b", "failed", 0)])
    tail = _summary([("b", "completed", 500)])

    replacements, still_missing = plan_merge(collected, tail)

    assert set(replacements) == {"b"}
    assert still_missing == []


def test_a_case_the_collected_run_already_had_is_refused(tmp_path) -> None:
    """Otherwise a second run could quietly replace a result that was fine."""
    collected = _summary([("a", "completed", 10), ("b", "failed", 0)])
    tail = _summary([("a", "completed", 9999)])

    with pytest.raises(ValueError, match="already completed"):
        plan_merge(collected, tail)


def test_a_case_from_outside_the_run_is_refused() -> None:
    collected = _summary([("a", "completed", 10), ("b", "failed", 0)])
    tail = _summary([("z", "completed", 500)])

    with pytest.raises(ValueError, match="not part of the collected run"):
        plan_merge(collected, tail)


def test_a_tail_case_that_also_failed_is_refused() -> None:
    collected = _summary([("a", "completed", 10), ("b", "failed", 0)])
    tail = _summary([("b", "failed", 0)])

    with pytest.raises(ValueError, match="did not complete in the tail run"):
        plan_merge(collected, tail)


def test_a_tail_that_supplies_nothing_is_refused() -> None:
    collected = _summary([("a", "completed", 10)])
    tail = {"runs": [{"completed": 0, "failed": 0, "cases": []}]}

    with pytest.raises(ValueError, match="supplies nothing"):
        plan_merge(collected, tail)


def test_a_case_left_unrecovered_is_reported_not_hidden() -> None:
    collected = _summary([("a", "failed", 0), ("b", "failed", 0)])
    tail = _summary([("a", "completed", 500)])

    _, still_missing = plan_merge(collected, tail)

    assert still_missing == ["b"]


def test_merge_writes_the_recovered_markdown_and_recounts(tmp_path) -> None:
    collected = _write_suite(
        tmp_path / "collected", [("a", "completed", 10), ("b", "failed", 0)]
    )
    tail = _write_suite(tmp_path / "tail", [("b", "completed", 500)])
    out = tmp_path / "merged"

    receipt = merge(collected, tail, out, reason="suite wall clock")

    assert receipt["completed_before"] == 1
    assert receipt["completed_after"] == 2
    assert receipt["failed_after"] == 0
    assert receipt["cases_merged"] == ["b"]
    assert (out / "markdown-repeat-1" / "b.md").read_text(encoding="utf-8") == "# b"

    merged = json.loads((out / "run-summary.json").read_text(encoding="utf-8"))
    run = merged["runs"][0]
    assert run["completed"] == 2
    assert run["failed"] == 0
    assert {c["case_id"]: c["status"] for c in run["cases"]} == {
        "a": "completed",
        "b": "completed",
    }


def test_the_original_counts_survive_in_the_merged_summary(tmp_path) -> None:
    """A reader of the merged summary can still see what the run itself did."""
    collected = _write_suite(
        tmp_path / "collected", [("a", "completed", 10), ("b", "failed", 0)]
    )
    tail = _write_suite(tmp_path / "tail", [("b", "completed", 500)])

    merge(collected, tail, tmp_path / "merged", reason="suite wall clock")

    run = json.loads((tmp_path / "merged" / "run-summary.json").read_text(encoding="utf-8"))
    provenance = run["runs"][0]["merged_from_tail_recovery"]
    assert provenance["completed_before"] == 1
    assert provenance["failed_before"] == 1
    assert provenance["case_ids"] == ["b"]
    assert provenance["reason"] == "suite wall clock"


def test_the_original_collection_is_left_alone(tmp_path) -> None:
    collected = _write_suite(
        tmp_path / "collected", [("a", "completed", 10), ("b", "failed", 0)]
    )
    tail = _write_suite(tmp_path / "tail", [("b", "completed", 500)])
    before = (collected / "run-summary.json").read_text(encoding="utf-8")

    merge(collected, tail, tmp_path / "merged", reason="suite wall clock")

    assert (collected / "run-summary.json").read_text(encoding="utf-8") == before
    assert not (collected / "markdown-repeat-1" / "b.md").exists()


def test_writing_over_an_existing_merge_is_refused(tmp_path) -> None:
    collected = _write_suite(
        tmp_path / "collected", [("a", "completed", 10), ("b", "failed", 0)]
    )
    tail = _write_suite(tmp_path / "tail", [("b", "completed", 500)])
    out = tmp_path / "merged"
    merge(collected, tail, out, reason="first")

    with pytest.raises(FileExistsError):
        merge(collected, tail, out, reason="second")


def test_a_tail_case_with_no_markdown_on_disk_is_refused(tmp_path) -> None:
    """The summary saying completed is not enough; the output has to be there."""
    collected = _write_suite(
        tmp_path / "collected", [("a", "completed", 10), ("b", "failed", 0)]
    )
    tail = _write_suite(tmp_path / "tail", [("b", "completed", 500)])
    (tail / "markdown-repeat-1" / "b.md").unlink()

    with pytest.raises(FileNotFoundError, match="no markdown for b"):
        merge(collected, tail, tmp_path / "merged", reason="suite wall clock")
