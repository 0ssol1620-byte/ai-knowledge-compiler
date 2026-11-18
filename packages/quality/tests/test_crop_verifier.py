import pytest
from akc_quality.conformal_risk import ConformalCalibration
from akc_quality.crop_verifier import (
    VerifierRequest,
    VerifierResult,
    build_result,
    check_sentinels,
    decide,
    off_result,
)

CAL = ConformalCalibration(0.8, 0.1, 100, 50, 0.02)
RENDERER = ("pdfium", "1.0")


def req(crop_sha256: str | None = "ab" * 32, renderer_version: str = "1.0") -> VerifierRequest:
    return VerifierRequest("r1", crop_sha256, "pdfium", renderer_version, "x", "table")


def build(request: VerifierRequest, score: object = 0.9) -> VerifierResult:
    return build_result(
        request, score, calibrated_renderer=RENDERER, verifier_id="jev", revision="r"
    )


def scored(score: float) -> VerifierResult:
    return VerifierResult("SCORED", score, "jev", "r")


def test_missing_crop_holds() -> None:
    assert build(req(None)).state == "HOLD_MISSING_CROP"
    assert build(req("")).state == "HOLD_MISSING_CROP"


def test_renderer_version_mismatch_holds() -> None:
    assert build(req(renderer_version="2.0")).state == "HOLD_RENDERER_MISMATCH"


@pytest.mark.parametrize("bad", [-0.1, 1.1, float("nan"), float("inf"), "0.9", None, True])
def test_invalid_scores_hold(bad: object) -> None:
    r = build(req(), bad)
    assert r.state == "HOLD_INVALID_OUTPUT" and r.score is None


def test_valid_score() -> None:
    assert build(req(), 0.9).state == "SCORED"


def test_inverted_sentinels_hold_whole_batch() -> None:
    batch = {"m": scored(0.4), "x": scored(0.6), "a": scored(0.99)}
    out = check_sentinels(batch, match_ids=["m"], mismatch_ids=["x"])
    assert {r.state for r in out.values()} == {"HOLD_SENTINEL_FAILED"}
    assert all(r.score is None for r in out.values())


def test_tied_sentinels_hold() -> None:
    batch = {"m": scored(0.5), "x": scored(0.5)}
    out = check_sentinels(batch, match_ids=["m"], mismatch_ids=["x"])
    assert out["m"].state == "HOLD_SENTINEL_FAILED"


def test_missing_sentinel_holds() -> None:
    out = check_sentinels({"m": scored(0.9)}, match_ids=["m"], mismatch_ids=["x"])
    assert out["m"].state == "HOLD_SENTINEL_FAILED"


def test_good_sentinels_pass_through() -> None:
    batch = {"m": scored(0.9), "x": scored(0.1), "a": scored(0.5)}
    assert check_sentinels(batch, match_ids=["m"], mismatch_ids=["x"]) == batch


def test_hard_gate_failure_not_accepted_even_at_score_one() -> None:
    assert not decide(False, scored(1.0), CAL, "jev_on").accepted
    assert not decide(False, scored(1.0), None, "jev_off").accepted


def test_jev_on_without_calibration_raises() -> None:
    with pytest.raises(ValueError):
        decide(True, scored(1.0), None, "jev_on")


def test_threshold_and_holds() -> None:
    assert decide(True, scored(0.9), CAL, "jev_on").accepted
    assert not decide(True, scored(0.5), CAL, "jev_on").accepted
    for hold in (
        VerifierResult("HOLD_MISSING_CROP", None, "jev", "r"),
        VerifierResult("HOLD_SENTINEL_FAILED", None, "jev", "r"),
    ):
        assert not decide(True, hold, CAL, "jev_on").accepted


def test_off_fallback_is_recorded_not_silent() -> None:
    r = off_result("jev", "r")
    assert r.state == "OFF" and r.fallback == "jev_off_policy"
    d = decide(True, r, CAL, "jev_on")
    assert d.accepted and d.fallback == "jev_off_policy"
