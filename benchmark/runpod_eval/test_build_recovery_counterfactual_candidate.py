from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from build_recovery_counterfactual_candidate import (
    build_counterfactual,
    candidate_relative_path,
    long_path,
)


def test_long_path_lifts_the_windows_limit_and_is_idempotent(tmp_path: Path) -> None:
    once = long_path(tmp_path / "a.md")
    twice = long_path(Path(once))
    assert once == twice
    if os.name == "nt":
        assert once.startswith("\\\\?\\")
    else:
        assert once == str(tmp_path / "a.md")


def test_deeply_nested_candidate_survives_the_path_limit(tmp_path: Path) -> None:
    # A path that would exceed MAX_PATH without the extended-length prefix.
    deep = tmp_path / ("nested" + os.sep.join(["x" * 30] * 6))
    candidate = deep / "candidate"
    _candidate_tree(candidate, {f"multi_column/{'f' * 90}_pg1_repeat1.md": "content"})
    result = build_counterfactual(
        candidate_root=candidate,
        output_root=deep / "counterfactual",
        case_index=_index(("case-a", f"bench_data/pdfs/multi_column/{'f' * 90}.pdf")),
        emptied_case_ids={"case-a"},
        candidate_suffix="_pg1_repeat1",
    )
    assert result["cases_emptied"] == 1


def test_candidate_path_is_derived_from_the_source_layout() -> None:
    assert (
        candidate_relative_path("bench_data/pdfs/multi_column/abc_page_31_pg1.pdf", "_pg1_repeat1")
        == "multi_column/abc_page_31_pg1_pg1_repeat1.md"
    )


def test_candidate_path_rejects_a_source_without_a_category() -> None:
    with pytest.raises(ValueError, match="cannot derive category"):
        candidate_relative_path("only-a-filename.pdf", "_pg1_repeat1")


def test_flat_layout_keys_only_on_the_source_stem() -> None:
    assert (
        candidate_relative_path("images/jiaocai_en_769.jpg", "", "flat")
        == "markdown-repeat-1/jiaocai_en_769.md"
    )


def test_flat_layout_does_not_need_a_category_folder() -> None:
    assert (
        candidate_relative_path("bare.jpg", "", "flat") == "markdown-repeat-1/bare.md"
    )


def test_unknown_layout_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown candidate layout"):
        candidate_relative_path("images/a.jpg", "", "sideways")


def test_flat_layout_empties_the_right_documents(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate"
    _candidate_tree(
        candidate,
        {
            "markdown-repeat-1/doc_a.md": "rescued content",
            "markdown-repeat-1/doc_b.md": "primary content",
        },
    )
    result = build_counterfactual(
        candidate_root=candidate,
        output_root=tmp_path / "counterfactual",
        case_index=_index(
            ("case-a", "images/doc_a.jpg"), ("case-b", "images/doc_b.jpg")
        ),
        emptied_case_ids={"case-a"},
        candidate_suffix="",
        layout="flat",
    )
    out = tmp_path / "counterfactual" / "markdown-repeat-1"
    assert (out / "doc_a.md").read_text(encoding="utf-8") == ""
    assert (out / "doc_b.md").read_text(encoding="utf-8") == "primary content"
    assert result["cases_emptied"] == 1


def _index(*cases: tuple[str, str]) -> dict:
    return {
        "records": [
            {"case_id": case_id, "source_relative_path": source}
            for case_id, source in cases
        ]
    }


def _candidate_tree(root: Path, files: dict[str, str]) -> None:
    for relative, text in files.items():
        target = root / relative
        os.makedirs(long_path(target.parent), exist_ok=True)
        with open(long_path(target), "w", encoding="utf-8") as handle:
            handle.write(text)


def test_only_the_rescued_documents_are_emptied(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate"
    _candidate_tree(
        candidate,
        {
            "multi_column/a_pg1_repeat1.md": "rescued content",
            "multi_column/b_pg1_repeat1.md": "primary content",
        },
    )
    index = _index(
        ("case-a", "bench_data/pdfs/multi_column/a.pdf"),
        ("case-b", "bench_data/pdfs/multi_column/b.pdf"),
    )
    result = build_counterfactual(
        candidate_root=candidate,
        output_root=tmp_path / "counterfactual",
        case_index=index,
        emptied_case_ids={"case-a"},
        candidate_suffix="_pg1_repeat1",
    )
    out = tmp_path / "counterfactual"
    assert (out / "multi_column/a_pg1_repeat1.md").read_text(encoding="utf-8") == ""
    assert (out / "multi_column/b_pg1_repeat1.md").read_text(encoding="utf-8") == "primary content"
    assert result["cases_emptied"] == 1
    # The real candidate set must be left untouched.
    rescued = candidate / "multi_column/a_pg1_repeat1.md"
    assert rescued.read_text(encoding="utf-8") == "rescued content"


def test_a_case_with_no_candidate_file_is_reported_not_counted(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate"
    _candidate_tree(candidate, {"multi_column/a_pg1_repeat1.md": "content"})
    index = _index(
        ("case-a", "bench_data/pdfs/multi_column/a.pdf"),
        ("case-gone", "bench_data/pdfs/multi_column/gone.pdf"),
    )
    result = build_counterfactual(
        candidate_root=candidate,
        output_root=tmp_path / "counterfactual",
        case_index=index,
        emptied_case_ids={"case-a", "case-gone"},
        candidate_suffix="_pg1_repeat1",
    )
    assert result["cases_emptied"] == 1
    assert result["cases_without_a_candidate_file"] == 1
    assert result["cases_without_a_candidate_file_ids"] == ["case-gone"]


def test_case_absent_from_the_index_is_an_error(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate"
    _candidate_tree(candidate, {"multi_column/a_pg1_repeat1.md": "content"})
    with pytest.raises(ValueError, match="absent from the case index"):
        build_counterfactual(
            candidate_root=candidate,
            output_root=tmp_path / "counterfactual",
            case_index=_index(("case-a", "bench_data/pdfs/multi_column/a.pdf")),
            emptied_case_ids={"case-ghost"},
            candidate_suffix="_pg1_repeat1",
        )


def test_a_mapping_that_empties_nothing_is_an_error(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate"
    _candidate_tree(candidate, {"multi_column/a_pg1_repeat1.md": "content"})
    with pytest.raises(ValueError, match="mapping is wrong"):
        build_counterfactual(
            candidate_root=candidate,
            output_root=tmp_path / "counterfactual",
            case_index=_index(("case-a", "bench_data/pdfs/multi_column/a.pdf")),
            emptied_case_ids={"case-a"},
            candidate_suffix="_WRONG_SUFFIX",
        )


def test_refuses_to_overwrite_an_existing_counterfactual(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate"
    _candidate_tree(candidate, {"multi_column/a_pg1_repeat1.md": "content"})
    output = tmp_path / "counterfactual"
    output.mkdir()
    with pytest.raises(FileExistsError):
        build_counterfactual(
            candidate_root=candidate,
            output_root=output,
            case_index=_index(("case-a", "bench_data/pdfs/multi_column/a.pdf")),
            emptied_case_ids={"case-a"},
            candidate_suffix="_pg1_repeat1",
        )


def test_parsebench_layout_maps_to_a_result_json(tmp_path: Path) -> None:
    assert (
        candidate_relative_path("docs/layout/17256.png", "", "parsebench_result")
        == "layout/17256.result.json"
    )


def test_parsebench_result_is_emptied_without_breaking_the_envelope(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "candidate"
    target = candidate / "layout"
    target.mkdir(parents=True)
    payload = {
        "pipeline_name": "mineru",
        "raw_output": "something",
        "output": {
            "example_id": "layout/17256",
            "markdown": "real extracted text",
            "layout_pages": [{"items": [1, 2, 3]}],
            "pages": [{"n": 1}],
        },
    }
    (target / "17256.result.json").write_text(json.dumps(payload), encoding="utf-8")

    result = build_counterfactual(
        candidate_root=candidate,
        output_root=tmp_path / "counterfactual",
        case_index=_index(("case-a", "docs/layout/17256.png")),
        emptied_case_ids={"case-a"},
        candidate_suffix="",
        layout="parsebench_result",
    )
    assert result["cases_emptied"] == 1
    written = json.loads(
        (tmp_path / "counterfactual/layout/17256.result.json").read_text(encoding="utf-8")
    )
    # The envelope survives so the evaluator can still read it; the extraction
    # inside is gone, which is what a dead worker would have produced.
    assert written["output"]["markdown"] == ""
    assert written["output"]["layout_pages"] == []
    assert written["output"]["pages"] == []
    assert written["output"]["example_id"] == "layout/17256"
    assert written["pipeline_name"] == "mineru"


def test_parsebench_result_without_an_output_object_is_rejected(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate"
    (candidate / "layout").mkdir(parents=True)
    (candidate / "layout/17256.result.json").write_text('{"no_output": 1}', encoding="utf-8")
    with pytest.raises(ValueError, match="no output object"):
        build_counterfactual(
            candidate_root=candidate,
            output_root=tmp_path / "counterfactual",
            case_index=_index(("case-a", "docs/layout/17256.png")),
            emptied_case_ids={"case-a"},
            candidate_suffix="",
            layout="parsebench_result",
        )
