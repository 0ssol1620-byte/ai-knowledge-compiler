"""Lane resolution, the pinned checkout commands, and the run watchdog.

No real evaluator runs here: the subprocess under test is this interpreter with
``-c``, which is enough to prove that a crash, a hang and a silent no-output
run all become ``EVALUATOR_BLOCKED`` rather than a number.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from arena.constants import HISTORICAL_EVALUATOR_PINS
from arena.scoring import evaluators, jsonio
from arena.scoring.errors import EvaluatorBlockedError, InputError
from arena.scoring.paths import ScoringPaths
from conftest import Campaign


def _step(tmp_path: Path, code: str, **kwargs: object) -> evaluators.EvaluatorStep:
    return evaluators.EvaluatorStep(
        name="probe",
        argv=(sys.executable, "-c", code),
        cwd=tmp_path,
        timeout_seconds=int(kwargs.pop("timeout_seconds", 60)),
        **kwargs,  # type: ignore[arg-type]
    )


# ------------------------------------------------------------------ lane resolution


def test_lane_falls_back_to_the_historical_pin_and_says_so(campaign: Campaign) -> None:
    lane = evaluators.resolve_lane(campaign.paths, "omnidoc", "main")

    assert lane.revision == HISTORICAL_EVALUATOR_PINS["omnidoc"]
    assert lane.revision_source == "arena.constants.HISTORICAL_EVALUATOR_PINS"
    assert any("evaluator_registry.json is absent" in note for note in lane.notes)
    assert any("not comparable to a main-lane score" in note for note in lane.notes)


def test_lane_prefers_the_registry_when_it_exists(campaign: Campaign) -> None:
    jsonio.write_json_atomic(
        campaign.paths.evaluator_registry,
        {
            "benchmarks": {
                "omnidoc": {
                    "benchmark": "omnidoc",
                    "repository": "https://example.invalid/OmniDocBench.git",
                    "historical_pin": HISTORICAL_EVALUATOR_PINS["omnidoc"],
                    "main_pin": "9" * 40,
                    "entrypoint": "python pdf_validation.py --config config.yaml",
                    "frozen": True,
                }
            }
        },
    )

    main = evaluators.resolve_lane(campaign.paths, "omnidoc", "main")
    historical = evaluators.resolve_lane(campaign.paths, "omnidoc", "historical")

    assert main.revision == "9" * 40
    assert main.revision_source == "evaluator_registry.json:main_pin"
    assert main.clone_source_kind == "upstream"
    assert historical.revision == HISTORICAL_EVALUATOR_PINS["omnidoc"]
    assert historical.clone_source_kind == "local_cache"


def test_an_unfrozen_registry_is_flagged(campaign: Campaign) -> None:
    jsonio.write_json_atomic(
        campaign.paths.evaluator_registry,
        {
            "benchmarks": {
                "olmocr": {
                    "benchmark": "olmocr",
                    "historical_pin": HISTORICAL_EVALUATOR_PINS["olmocr"],
                    "main_pin": HISTORICAL_EVALUATOR_PINS["olmocr"],
                    "frozen": False,
                }
            }
        },
    )

    lane = evaluators.resolve_lane(campaign.paths, "olmocr", "main")

    assert any("not frozen yet" in note for note in lane.notes)


def test_unknown_benchmark_and_lane_are_refused(campaign: Campaign) -> None:
    with pytest.raises(InputError, match="unknown benchmark"):
        evaluators.resolve_lane(campaign.paths, "nope", "main")
    with pytest.raises(InputError, match="unknown lane"):
        evaluators.resolve_lane(campaign.paths, "omnidoc", "sideways")  # type: ignore[arg-type]


def test_checkout_never_points_at_benchmark_cache_as_a_worktree(campaign: Campaign) -> None:
    lane = evaluators.resolve_lane(campaign.paths, "parsebench", "historical")
    clone, checkout = evaluators.checkout_commands(lane)

    assert clone[:3] == ("git", "clone", "--no-checkout")
    assert clone[3] == str(campaign.paths.evaluator_cache("parsebench"))
    assert clone[4] == str(lane.checkout_dir)
    assert checkout == ("git", "-C", str(lane.checkout_dir), "checkout", lane.revision)
    assert "scores" in str(lane.checkout_dir).replace("\\", "/")


def test_setup_commands_are_the_documented_ones(campaign: Campaign) -> None:
    parsebench = evaluators.resolve_lane(campaign.paths, "parsebench", "historical")
    olmocr = evaluators.resolve_lane(campaign.paths, "olmocr", "historical")

    assert parsebench.setup_commands[0] == ("uv", "sync", "--extra", "runners")
    assert olmocr.setup_commands[0] == (
        "python",
        "-m",
        "pip",
        "install",
        "-r",
        "requirements.txt",
    )
    assert ("python", "-m", "playwright", "install", "chromium") in olmocr.setup_commands


# ------------------------------------------------------------------- gt resolution


def test_gt_path_selects_one_entry_per_benchmark(tmp_path: Path) -> None:
    paths = ScoringPaths(root=tmp_path, repo_root=tmp_path / "repo")

    omnidoc = evaluators.resolve_gt_path(
        paths,
        "omnidoc",
        ["a/omnidocbench/OmniDocBench.json", "a/omnidocbench/with_mask.json"],
    )
    olmocr = evaluators.resolve_gt_path(
        paths, "olmocr", ["a/olmocr-bench/eval.yaml", "a/olmocr-bench/bench_data/pdfs"]
    )

    assert omnidoc.name == "OmniDocBench.json"
    assert olmocr.name == "bench_data", "the evaluator's --dir is the parent of pdfs/"


def test_ambiguous_or_absent_gt_paths_are_refused(tmp_path: Path) -> None:
    paths = ScoringPaths(root=tmp_path, repo_root=tmp_path)

    with pytest.raises(InputError, match="exactly one entry"):
        evaluators.resolve_gt_path(paths, "omnidoc", [])


def test_gt_path_override_wins(tmp_path: Path) -> None:
    paths = ScoringPaths(root=tmp_path, repo_root=tmp_path)

    assert evaluators.resolve_gt_path(
        paths, "omnidoc", [], override=str(tmp_path / "elsewhere.json")
    ) == (tmp_path / "elsewhere.json")


# ------------------------------------------------------------------- run commands


def test_parsebench_runs_one_step_per_group(campaign: Campaign) -> None:
    lane = evaluators.resolve_lane(campaign.paths, "parsebench", "historical")
    steps = evaluators.build_steps(
        lane,
        input_root=campaign.root / "input",
        raw_root=campaign.root / "raw",
        gt_path=campaign.root / "gt" / "docs",
        candidate=campaign.model_key,
    )

    assert [step.name for step in steps] == [
        "chart",
        "layout",
        "table",
        "text_content",
        "text_formatting",
    ]
    layout = next(step for step in steps if step.name == "layout")
    assert "--product_type=layout_detection" in layout.argv
    assert "--ontology=canonical" in layout.argv
    assert layout.argv[:5] == ("uv", "run", "parse-bench", "evaluation", "run")


def test_omnidoc_step_names_the_config_and_the_result_it_must_produce(
    campaign: Campaign,
) -> None:
    lane = evaluators.resolve_lane(campaign.paths, "omnidoc", "historical")
    (step,) = evaluators.build_steps(
        lane,
        input_root=campaign.root / "input",
        raw_root=campaign.root / "raw",
        gt_path=campaign.root / "gt" / "OmniDocBench.json",
        candidate=campaign.model_key,
    )

    assert step.argv[1:3] == ("pdf_validation.py", "--config")
    assert step.expected_outputs[0].endswith("markdown_quick_match_metric_result.json")
    assert step.collect_globs == ("result/markdown_quick_match_*",)


def test_olmocr_step_runs_the_campaign_driver(campaign: Campaign) -> None:
    lane = evaluators.resolve_lane(campaign.paths, "olmocr", "historical")
    (step,) = evaluators.build_steps(
        lane,
        input_root=campaign.root / "input",
        raw_root=campaign.root / "raw",
        gt_path=campaign.root / "gt" / "bench_data",
        candidate=campaign.model_key,
    )

    assert step.argv[1].endswith("olmocr_driver.py")
    assert "--candidate" in step.argv
    assert step.expected_outputs[0].endswith("official-result.json")


# ---------------------------------------------------------------------- watchdog


def test_a_successful_step_is_recorded_with_its_streams(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    step = _step(tmp_path, "print('hello'); open('done.txt','w').write('x')")
    step = evaluators.EvaluatorStep(
        name=step.name,
        argv=step.argv,
        cwd=step.cwd,
        timeout_seconds=step.timeout_seconds,
        expected_outputs=("done.txt",),
    )

    records = evaluators.run_steps([step], raw)

    assert records[0]["returncode"] == 0
    assert "hello" in (raw / "probe" / "stdout.log").read_text(encoding="utf-8")
    assert (raw / "probe" / "stderr.log").is_file()


def test_a_failing_evaluator_is_blocked_with_its_stderr(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    step = _step(tmp_path, "import sys; sys.stderr.write('boom traceback'); sys.exit(3)")

    with pytest.raises(EvaluatorBlockedError) as caught:
        evaluators.run_steps([step], raw)

    assert caught.value.returncode == 3
    assert "boom traceback" in caught.value.stderr_tail
    assert caught.value.timed_out is False
    assert "boom traceback" in (raw / "probe" / "stderr.log").read_text(encoding="utf-8")


def test_a_hanging_evaluator_is_blocked_by_the_watchdog(tmp_path: Path) -> None:
    step = _step(tmp_path, "import time; time.sleep(30)", timeout_seconds=1)

    with pytest.raises(EvaluatorBlockedError, match="watchdog") as caught:
        evaluators.run_steps([step], tmp_path / "raw")

    assert caught.value.timed_out is True


def test_exit_zero_without_the_expected_output_is_blocked(tmp_path: Path) -> None:
    step = evaluators.EvaluatorStep(
        name="probe",
        argv=(sys.executable, "-c", "pass"),
        cwd=tmp_path,
        timeout_seconds=60,
        expected_outputs=("never-written.json",),
    )

    with pytest.raises(EvaluatorBlockedError, match="exited 0 but produced none of"):
        evaluators.run_steps([step], tmp_path / "raw")


def test_an_unlaunchable_command_is_blocked_not_crashed(tmp_path: Path) -> None:
    step = evaluators.EvaluatorStep(
        name="probe",
        argv=("this-binary-does-not-exist-anywhere",),
        cwd=tmp_path,
        timeout_seconds=5,
    )

    with pytest.raises(EvaluatorBlockedError, match="could not be launched"):
        evaluators.run_steps([step], tmp_path / "raw")


def test_collected_globs_are_copied_out_of_the_checkout(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    (tmp_path / "result").mkdir()
    step = evaluators.EvaluatorStep(
        name="probe",
        argv=(
            sys.executable,
            "-c",
            "open('result/markdown_quick_match_metric_result.json','w').write('{}')",
        ),
        cwd=tmp_path,
        timeout_seconds=60,
        collect_globs=("result/markdown_quick_match_*",),
    )

    records = evaluators.run_steps([step], raw)

    assert records[0]["collected"] == ["markdown_quick_match_metric_result.json"]
    assert (raw / "probe" / "markdown_quick_match_metric_result.json").is_file()
