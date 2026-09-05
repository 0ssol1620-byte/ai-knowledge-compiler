"""The command line, end to end over a synthetic campaign."""

from __future__ import annotations

import json

import pytest
from arena.tavonel import jsonio, variants
from arena.tavonel.cli import main
from conftest import PRIMARY, Campaign


def _run(campaign: Campaign, *args: str) -> int:
    return main([*args, "--root", str(campaign.root)])


def test_the_whole_lane_runs_from_the_command_line(campaign: Campaign) -> None:
    assert _run(campaign, "signals") == 0
    assert _run(campaign, "disagreement") == 0
    assert _run(campaign, "freeze-routes", "--variant", "C_adaptive") == 0
    assert _run(campaign, "replay", "--variant", "C") == 0
    assert _run(campaign, "plan-recovery", "--variant", "C") == 0
    assert _run(campaign, "cost", "--variant", "C") == 0

    assert campaign.paths.disagreement_pairs.is_file()
    assert campaign.paths.route_frozen_path(variants.VARIANT_C).is_file()
    assert campaign.paths.replay_manifest(variants.VARIANT_C).is_file()
    assert campaign.paths.variant_cost_path(variants.VARIANT_C).is_file()


def test_the_disagreement_trigger_is_live_once_the_matrix_exists(
    campaign: Campaign, capsys: pytest.CaptureFixture[str]
) -> None:
    _run(campaign, "signals")
    _run(campaign, "disagreement")
    _run(campaign, "freeze-routes", "--variant", "A")
    capsys.readouterr()

    frozen = json.loads(
        campaign.paths.route_frozen_path(variants.VARIANT_A).read_text(encoding="utf-8")
    )
    assert frozen["disagreement_trigger_available"] is True
    record = json.loads(
        campaign.paths.route_decision_path(variants.VARIANT_A, "case-clean").read_text(
            encoding="utf-8"
        )
    )
    # The matrix exists, but the configured cheap peer is not one of the models
    # this fixture ran — which the decision says outright instead of silently
    # treating the page as "models agreed".
    assert record["signals"]["peer_similarity"] is None
    assert "mineru_pipeline" in record["signals"]["peer_similarity_unavailable_reason"]


def test_freezing_without_the_matrix_says_so_on_stderr(
    campaign: Campaign, capsys: pytest.CaptureFixture[str]
) -> None:
    _run(campaign, "signals")
    assert _run(campaign, "freeze-routes", "--variant", "A") == 0
    captured = capsys.readouterr()
    assert "no disagreement matrix" in captured.err


def test_the_order_guard_is_visible_from_the_command_line(
    campaign: Campaign, capsys: pytest.CaptureFixture[str]
) -> None:
    _run(campaign, "signals")
    jsonio.write_json_atomic(
        campaign.paths.model_scores(PRIMARY), {"cases": {"case-clean": {"official_score": 0.9}}}
    )
    assert _run(campaign, "freeze-routes", "--variant", "C") == 1
    assert "section 2.2" in capsys.readouterr().err


def test_a_bad_threshold_override_is_refused(
    campaign: Campaign, capsys: pytest.CaptureFixture[str]
) -> None:
    _run(campaign, "signals")
    assert _run(campaign, "freeze-routes", "--variant", "A", "--set-threshold", "nope") == 1
    assert "NAME=VALUE" in capsys.readouterr().err


def test_a_threshold_override_changes_the_frozen_policy_hash(campaign: Campaign) -> None:
    _run(campaign, "signals")
    _run(campaign, "freeze-routes", "--variant", "A")
    _run(
        campaign,
        "freeze-routes",
        "--variant",
        "C",
        "--set-threshold",
        "min_output_chars=1000",
    )
    base = json.loads(
        campaign.paths.route_frozen_path(variants.VARIANT_A).read_text(encoding="utf-8")
    )
    tuned = json.loads(
        campaign.paths.route_frozen_path(variants.VARIANT_C).read_text(encoding="utf-8")
    )
    assert base["policy_sha256"] != tuned["policy_sha256"]
    thresholds = {
        item["name"]: item for item in tuned["policy"]["parameters"]["thresholds"]
    }
    assert thresholds["min_output_chars"]["value"] == 1000.0
    assert thresholds["min_output_chars"]["calibrated"] is False


def test_signals_reports_a_coverage_problem_with_a_non_zero_exit(
    campaign: Campaign, capsys: pytest.CaptureFixture[str]
) -> None:
    campaign.paths.canonical_path(PRIMARY, "case-empty").unlink()
    campaign.paths.raw_text_path(PRIMARY, "case-empty").unlink()
    assert _run(campaign, "signals") == 1
    assert "no output text on disk" in capsys.readouterr().err


def test_an_unknown_variant_is_refused(
    campaign: Campaign, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(campaign, "replay", "--variant", "Z") == 1
    assert "unknown variant" in capsys.readouterr().err


def test_the_primary_model_can_be_overridden(campaign: Campaign) -> None:
    _run(campaign, "signals")
    assert _run(campaign, "freeze-routes", "--variant", "A", "--primary", "mineru_vlm") == 0
    frozen = json.loads(
        campaign.paths.route_frozen_path(variants.VARIANT_A).read_text(encoding="utf-8")
    )
    assert frozen["primary_model_key"] == "mineru_vlm"
    assert frozen["gt_order_guard"]["checked"] == "scores/mineru_vlm"
