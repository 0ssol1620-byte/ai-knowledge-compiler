"""Evaluator input layouts, on a synthetic frozen tree (arena/scoring/LAYOUTS.md)."""

from __future__ import annotations

from pathlib import Path

import pytest
from arena.scoring import evaluators, jsonio
from arena.scoring.errors import InputError, LayoutError
from arena.scoring.outputs import load_model_output_set, load_source_index
from conftest import Campaign, CaseSpec, build_campaign


def _prepare(campaign: Campaign, benchmark: str) -> evaluators.PrepareResult:
    output_set = load_model_output_set(campaign.paths, campaign.model_key)
    return evaluators.prepare_inputs(
        campaign.paths,
        key=campaign.model_key,
        benchmark=benchmark,
        rows=output_set.for_benchmark(benchmark),
        source_index=load_source_index(campaign.paths),
        pipeline_name="tavonel-arena-test",
    )


# --------------------------------------------------------------------- ParseBench


def test_parsebench_files_land_under_their_source_category(campaign: Campaign) -> None:
    result = _prepare(campaign, "parsebench")

    root = campaign.paths.evaluator_input(campaign.model_key, "parsebench")
    assert result.written == 2
    assert (root / "chart" / "quarterly_chart.result.json").is_file()
    assert (root / "text" / "policy_letter.result.json").is_file()


def test_parsebench_test_id_matches_the_evaluator_loader(campaign: Campaign) -> None:
    _prepare(campaign, "parsebench")

    root = campaign.paths.evaluator_input(campaign.model_key, "parsebench")
    document = jsonio.read_json(root / "chart" / "quarterly_chart.result.json")

    assert document["request"]["example_id"] == "chart/quarterly_chart"
    assert document["output"]["pages"][0]["markdown"] == "## Quarterly\n\nrevenue rose\n"
    assert document["request"]["product_type"] == "parse"


def test_parsebench_layout_category_becomes_layout_detection(tmp_path: Path) -> None:
    spec = CaseSpec(
        benchmark="parsebench",
        case_key="parsebench-0000000000000000000000e1",
        source_relative_path="docs/layout/form_page.pdf",
        media_type="pdf",
        page_index=0,
        markdown="form\n",
    )
    campaign = build_campaign(tmp_path / "arena", specs=(spec,))

    _prepare(campaign, "parsebench")
    root = campaign.paths.evaluator_input(campaign.model_key, "parsebench")
    document = jsonio.read_json(root / "layout" / "form_page.result.json")

    assert document["product_type"] == "layout_detection"
    assert document["output"]["predictions"] == []
    assert document["raw_output"]["elements_available"] is False


def test_parsebench_layout_uses_elements_when_the_adapter_emitted_them(
    tmp_path: Path,
) -> None:
    spec = CaseSpec(
        benchmark="parsebench",
        case_key="parsebench-0000000000000000000000e2",
        source_relative_path="docs/layout/boxed_page.pdf",
        media_type="pdf",
        page_index=0,
        markdown="boxed\n",
    )
    campaign = build_campaign(tmp_path / "arena", specs=(spec,))
    jsonio.write_json_atomic(
        campaign.paths.elements_path(campaign.model_key, spec.case_key),
        {
            "elements": [
                {"bbox": [1, 2, 3, 4], "label": "Table", "content": "x"},
                {"label": "Text"},
                {"bbox": [0, 0, 1], "label": "Text"},
            ]
        },
    )

    _prepare(campaign, "parsebench")
    root = campaign.paths.evaluator_input(campaign.model_key, "parsebench")
    document = jsonio.read_json(root / "layout" / "boxed_page.result.json")

    predictions = document["output"]["predictions"]
    assert len(predictions) == 1, "an element without a usable bbox contributes nothing"
    assert predictions[0]["bbox"] == [1.0, 2.0, 3.0, 4.0]
    assert predictions[0]["label"] == "Table"


def test_a_failed_page_is_skipped_with_its_reason(tmp_path: Path) -> None:
    ok, broken = (
        CaseSpec(
            benchmark="parsebench",
            case_key="parsebench-0000000000000000000000f1",
            source_relative_path="docs/table/good.pdf",
            media_type="pdf",
            page_index=0,
            markdown="| a |\n",
        ),
        CaseSpec(
            benchmark="parsebench",
            case_key="parsebench-0000000000000000000000f2",
            source_relative_path="docs/table/bad.pdf",
            media_type="pdf",
            page_index=0,
            markdown="",
            status="FAILED",
        ),
    )
    campaign = build_campaign(tmp_path / "arena", specs=(ok, broken))

    result = _prepare(campaign, "parsebench")

    assert result.written == 1
    assert result.skipped == (
        {
            "case_key": broken.case_key,
            "sample_id": "parsebench:docs/table/bad#p0",
            "reason": "page status is FAILED, not SUCCESS",
        },
    )


def test_the_two_text_groups_share_one_prediction_directory() -> None:
    # evaluation/runner.py filters prediction files by their parent directory
    # name and maps both text groups onto "text"; the layout depends on it.
    assert evaluators.PARSEBENCH_INFERENCE_DIR == {
        "text_content": "text",
        "text_formatting": "text",
    }


# ------------------------------------------------------------------- OmniDocBench


def test_omnidoc_markdown_is_named_after_the_ground_truth_page(campaign: Campaign) -> None:
    result = _prepare(campaign, "omnidoc")

    prediction_dir = campaign.paths.evaluator_input(campaign.model_key, "omnidoc") / "markdown"
    assert result.written == 2
    assert (prediction_dir / "PPT_alpha_page_001.md").read_text(
        encoding="utf-8"
    ) == "# Alpha\n\nfirst page\n"
    assert (prediction_dir / "PPT_beta_page_002.md").is_file()


def test_omnidoc_refuses_two_pages_with_one_name(tmp_path: Path) -> None:
    first, second = (
        CaseSpec(
            benchmark="omnidoc",
            case_key="omnidocbench-000000000000000000000g1",
            source_relative_path="images/collide.png",
            media_type="image",
            page_index=1,
            markdown="one\n",
        ),
        CaseSpec(
            benchmark="omnidoc",
            case_key="omnidocbench-000000000000000000000g2",
            source_relative_path="other/collide.jpg",
            media_type="image",
            page_index=1,
            markdown="two\n",
        ),
    )
    campaign = build_campaign(tmp_path / "arena", specs=(first, second))

    with pytest.raises(LayoutError, match="two cases map to the OmniDocBench page name"):
        _prepare(campaign, "omnidoc")


def test_omnidoc_config_names_both_data_paths(tmp_path: Path) -> None:
    config = evaluators.omnidoc_config(
        gt_path=tmp_path / "gt" / "OmniDocBench.json",
        prediction_dir=tmp_path / "pred" / "markdown",
    )

    assert "match_method: quick_match" in config
    assert "OmniDocBench.json" in config
    assert "pred/markdown" in config
    assert "TEDS" in config


# -------------------------------------------------------------------- olmOCR-Bench


@pytest.mark.parametrize(
    ("source", "page_index", "expected"),
    [
        (
            "bench_data/pdfs/arxiv_math/2502.15977_pg21.pdf",
            0,
            "arxiv_math/2502.15977_pg21_pg1_repeat1.md",
        ),
        ("bench_data/pdfs/tables/table_two.pdf", 0, "tables/table_two_pg1_repeat1.md"),
        ("bench_data/pdfs/old_scans/scan.pdf", 3, "old_scans/scan_pg4_repeat1.md"),
    ],
)
def test_olmocr_names_match_the_evaluator_regex(
    source: str, page_index: int, expected: str
) -> None:
    assert evaluators.olmocr_markdown_name(source, page_index).as_posix() == expected


def test_olmocr_refuses_a_source_outside_bench_data_pdfs() -> None:
    with pytest.raises(LayoutError, match="not under bench_data/pdfs"):
        evaluators.olmocr_markdown_name("elsewhere/file.pdf", 0)


def test_olmocr_candidate_tree_mirrors_the_pdf_tree(campaign: Campaign) -> None:
    result = _prepare(campaign, "olmocr")

    root = campaign.paths.evaluator_input(campaign.model_key, "olmocr")
    candidate = root / campaign.model_key
    assert result.written == 2
    assert (candidate / "arxiv_math" / "2502.15977_pg21_pg1_repeat1.md").read_text(
        encoding="utf-8"
    ) == "$x^2$\n"
    assert (candidate / "tables" / "table_two_pg1_repeat1.md").is_file()


def test_olmocr_bench_root_is_staged_without_touching_ground_truth(
    campaign: Campaign, tmp_path: Path
) -> None:
    gt = tmp_path / "gt" / "bench_data"
    (gt / "pdfs" / "arxiv_math").mkdir(parents=True)
    (gt / "pdfs" / "arxiv_math" / "2502.15977_pg21.pdf").write_bytes(b"%PDF-1.7\n")
    (gt / "arxiv_math.jsonl").write_text('{"id": "t1"}\n', encoding="utf-8")
    before = sorted(path.name for path in gt.rglob("*"))
    input_root = campaign.paths.evaluator_input(campaign.model_key, "olmocr")

    staged = evaluators.stage_olmocr_bench_root(input_root, gt)

    assert staged["rule_files"] == 1
    assert staged["pdfs_linked"] + staged["pdfs_copied"] == 1
    assert (input_root / "pdfs" / "arxiv_math" / "2502.15977_pg21.pdf").is_file()
    assert (input_root / "arxiv_math.jsonl").is_file()
    assert sorted(path.name for path in gt.rglob("*")) == before


def test_olmocr_bench_root_refuses_ground_truth_without_pdfs(
    campaign: Campaign, tmp_path: Path
) -> None:
    gt = tmp_path / "empty"
    gt.mkdir()

    with pytest.raises(InputError, match="no pdfs/ directory"):
        evaluators.stage_olmocr_bench_root(
            campaign.paths.evaluator_input(campaign.model_key, "olmocr"), gt
        )


def test_olmocr_bench_root_refuses_ground_truth_without_rules(
    campaign: Campaign, tmp_path: Path
) -> None:
    gt = tmp_path / "norules" / "bench_data"
    (gt / "pdfs").mkdir(parents=True)
    (gt / "pdfs" / "a.pdf").write_bytes(b"%PDF-1.7\n")

    with pytest.raises(InputError, match=r"no rule \.jsonl files"):
        evaluators.stage_olmocr_bench_root(
            campaign.paths.evaluator_input(campaign.model_key, "olmocr"), gt
        )
