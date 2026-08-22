from akc_router.calibration import CalibrationBin, expected_calibration_error
from akc_router.champion_matrix import ChampionCandidate, ChampionMatrix
from akc_router.expected_verified_cost import RouteCostCandidate, select_expected_verified_cost


def test_unapproved_candidate_never_becomes_champion() -> None:
    matrix = ChampionMatrix(
        (
            ChampionCandidate("shadow", "table", "r1", "ev1", True, False),
            ChampionCandidate("champion", "table", "r2", "ev2", True, True),
        )
    )
    assert matrix.select("table").candidate_id == "champion"  # type: ignore[union-attr]


def test_verified_cost_accounts_for_recovery_and_critical_risk() -> None:
    cheap_risky = RouteCostCandidate("cheap", 1, 1, 0.5, 10, 0.1, 100)
    stable = RouteCostCandidate("stable", 3, 1, 0.01, 10, 0.001, 100)
    selected = select_expected_verified_cost(
        (cheap_risky, stable), maximum_critical_failure_probability=0.01
    )
    assert selected is stable


def test_calibration_error_is_zero_for_perfect_binary_confidence() -> None:
    assert expected_calibration_error((CalibrationBin(1, True), CalibrationBin(0, False))) == 0
