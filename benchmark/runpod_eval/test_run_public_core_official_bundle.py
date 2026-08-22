from __future__ import annotations

from pathlib import Path

from run_public_core_official_bundle import build_official_commands


def test_official_bundle_freezes_all_three_evaluator_lanes(tmp_path: Path) -> None:
    commands = build_official_commands(
        repository_root=tmp_path,
        merged_root=tmp_path / "merged",
        output_root=tmp_path / "evaluations",
    )

    assert [command.benchmark_id for command in commands] == [
        "parsebench",
        "omnidocbench",
        "olmocr-bench",
    ]
    assert "--repeats" in commands[1].arguments
    assert commands[1].arguments[commands[1].arguments.index("--repeats") + 1] == "1"
    assert "--bootstrap-samples" in commands[2].arguments
    assert (
        commands[2].arguments[commands[2].arguments.index("--bootstrap-samples") + 1]
        == "2000"
    )
