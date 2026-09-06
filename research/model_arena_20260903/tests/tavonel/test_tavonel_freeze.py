"""Route freeze: the order guard, the seal, and the oracle's inverted rule."""

from __future__ import annotations

import json

import pytest
from arena.tavonel import freeze, jsonio, signals, variants
from arena.tavonel.errors import FreezeOrderError, MissingInputError
from conftest import PRIMARY, TEXT_SPECIALIST, Campaign


def _prepare(campaign: Campaign) -> None:
    signals.build_signals(campaign.paths)


def _write_scores(campaign: Campaign, model: str, scores: dict[str, float]) -> None:
    jsonio.write_json_atomic(
        campaign.paths.model_scores(model),
        {
            "model_key": model,
            "cases": {
                case_key: {
                    "benchmark": "omnidoc",
                    "evaluator_status": "SCORED",
                    "official_score": value,
                }
                for case_key, value in scores.items()
            },
        },
    )


def test_freeze_writes_one_sealed_decision_per_page(campaign: Campaign) -> None:
    _prepare(campaign)
    report = freeze.freeze_routes(campaign.paths, variant=variants.VARIANT_C)
    assert report.decision_count == len(campaign.cases)
    for case_key in campaign.cases:
        record = json.loads(
            campaign.paths.route_decision_path(variants.VARIANT_C, case_key).read_text(
                encoding="utf-8"
            )
        )
        assert record["decided_before_gt"] is True
        assert record["campaign_id"]
        assert record["policy_sha256"] == report.policy_sha256
        assert record["signals_sha256"].startswith("sha256:")
        body = {key: value for key, value in record.items() if key != "decision_sha256"}
        assert record["decision_sha256"] == jsonio.prefixed(jsonio.json_sha256_hex(body))


def test_freeze_file_carries_the_manifest_hash(campaign: Campaign) -> None:
    _prepare(campaign)
    report = freeze.freeze_routes(campaign.paths, variant=variants.VARIANT_A)
    frozen = json.loads(report.frozen_path.read_text(encoding="utf-8"))
    assert frozen["count"] == len(campaign.cases)
    assert frozen["decision_manifest_sha256"] == report.decision_manifest_sha256
    assert frozen["policy_sha256"] == report.policy_sha256
    assert frozen["gt_order_guard"] == {
        "checked": f"scores/{PRIMARY}",
        "result": "absent",
        "artefacts": 0,
    }


def test_freeze_refuses_once_the_primary_model_has_been_scored(campaign: Campaign) -> None:
    _prepare(campaign)
    _write_scores(campaign, PRIMARY, {"case-clean": 0.9})
    with pytest.raises(FreezeOrderError) as raised:
        freeze.freeze_routes(campaign.paths, variant=variants.VARIANT_C)
    assert "section 2.2" in str(raised.value)
    assert not campaign.paths.route_frozen_path(variants.VARIANT_C).exists()


def test_scores_for_another_model_do_not_block_the_freeze(campaign: Campaign) -> None:
    _prepare(campaign)
    _write_scores(campaign, TEXT_SPECIALIST, {"case-clean": 0.9})
    report = freeze.freeze_routes(campaign.paths, variant=variants.VARIANT_C)
    assert report.decision_count == len(campaign.cases)


def test_a_frozen_variant_cannot_be_refrozen(campaign: Campaign) -> None:
    _prepare(campaign)
    freeze.freeze_routes(campaign.paths, variant=variants.VARIANT_A)
    with pytest.raises(FreezeOrderError):
        freeze.freeze_routes(campaign.paths, variant=variants.VARIANT_A)


def test_freeze_without_signals_fails_closed(campaign: Campaign) -> None:
    with pytest.raises(MissingInputError):
        freeze.freeze_routes(campaign.paths, variant=variants.VARIANT_A)


def test_loading_decisions_verifies_the_seal(campaign: Campaign) -> None:
    _prepare(campaign)
    freeze.freeze_routes(campaign.paths, variant=variants.VARIANT_A)
    assert len(freeze.load_route_decisions(campaign.paths, variants.VARIANT_A)) == len(
        campaign.cases
    )

    path = campaign.paths.route_decision_path(variants.VARIANT_A, "case-clean")
    tampered = json.loads(path.read_text(encoding="utf-8"))
    tampered["decision_sha256"] = "sha256:" + "1" * 64
    jsonio.write_json_atomic(path, tampered)
    with pytest.raises(FreezeOrderError):
        freeze.load_route_decisions(campaign.paths, variants.VARIANT_A)


def test_loading_an_unfrozen_variant_fails_closed(campaign: Campaign) -> None:
    _prepare(campaign)
    with pytest.raises(MissingInputError):
        freeze.load_route_decisions(campaign.paths, variants.VARIANT_B)


def test_the_oracle_refuses_to_run_before_scoring(campaign: Campaign) -> None:
    _prepare(campaign)
    with pytest.raises(MissingInputError):
        freeze.freeze_routes(campaign.paths, variant=variants.VARIANT_E)


def test_the_oracle_selects_the_best_scored_model_and_labels_itself(
    campaign: Campaign,
) -> None:
    _prepare(campaign)
    _write_scores(campaign, PRIMARY, {case: 0.40 for case in campaign.cases})
    _write_scores(campaign, TEXT_SPECIALIST, {case: 0.95 for case in campaign.cases})

    report = freeze.freeze_routes(campaign.paths, variant=variants.VARIANT_E)
    assert variants.ORACLE_LABEL in str(report.decisions_dir)

    frozen = json.loads(report.frozen_path.read_text(encoding="utf-8"))
    assert frozen["deployability"] == variants.ORACLE_LABEL
    assert frozen["decided_before_gt"] is False

    record = json.loads(
        campaign.paths.route_decision_path(variants.VARIANT_E, "case-clean").read_text(
            encoding="utf-8"
        )
    )
    assert record["deployability"] == variants.ORACLE_LABEL
    assert record["final_model"] == TEXT_SPECIALIST


def test_a_blocked_evaluator_is_not_treated_as_a_zero_score(campaign: Campaign) -> None:
    _prepare(campaign)
    jsonio.write_json_atomic(
        campaign.paths.model_scores(PRIMARY),
        {
            "cases": {
                case: {"evaluator_status": "EVALUATOR_BLOCKED"} for case in campaign.cases
            }
        },
    )
    _write_scores(campaign, TEXT_SPECIALIST, {case: 0.10 for case in campaign.cases})
    freeze.freeze_routes(campaign.paths, variant=variants.VARIANT_E)
    record = json.loads(
        campaign.paths.route_decision_path(variants.VARIANT_E, "case-clean").read_text(
            encoding="utf-8"
        )
    )
    # The blocked model is simply absent from the candidates; a zero would have
    # made it look like the worst model rather than an unmeasured one.
    assert PRIMARY not in record["candidate_models"]
    assert record["final_model"] == TEXT_SPECIALIST
