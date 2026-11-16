from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from akc_quality.crop_verifier import VerifierRequest

from benchmark.runners.base import RunnerConfig, RunnerUnavailable
from benchmark.screen.jev_calibration import (
    PageObservation,
    auroc,
    calibrate_dev,
    write_calibration,
)
from benchmark.screen.jev_client import verify_crop
from benchmark.screen.manifest import HoldoutGuard, HoldoutSealedError

RENDERER = ("pdfium", "1")
CROP = b"crop-bytes"
CFG = RunnerConfig("jev", "rev1", endpoint="https://jev.example/v", allow_network=True)
MSHA = "sha256:" + "a" * 64


def _req(**kw: Any) -> VerifierRequest:
    base: dict[str, Any] = {
        "region_id": "r",
        "crop_sha256": hashlib.sha256(CROP).hexdigest(),
        "renderer_id": "pdfium",
        "renderer_version": "1",
        "candidate_text": "x",
        "region_kind": "table",
    }
    return VerifierRequest(**{**base, **kw})


def _boom(c: RunnerConfig, p: dict[str, Any]) -> dict[str, Any]:
    raise AssertionError("transport must not be called")


def test_client_scored_and_payload() -> None:
    seen: list[dict[str, Any]] = []

    def transport(cfg: RunnerConfig, payload: dict[str, Any]) -> dict[str, Any]:
        seen.append(payload)
        return {"score": 0.9}

    r = verify_crop(CFG, _req(), CROP, calibrated_renderer=RENDERER, transport=transport)
    assert (r.state, r.score, r.verifier_id, r.revision) == ("SCORED", 0.9, "jev", "rev1")
    assert seen[0]["crop_base64"] and seen[0]["candidate_text"] == "x"


@pytest.mark.parametrize("response", [{"score": 1.5}, {}, {"score": True}])
def test_client_invalid_output_holds(response: dict[str, Any]) -> None:
    r = verify_crop(
        CFG, _req(), CROP, calibrated_renderer=RENDERER, transport=lambda c, p: response
    )
    assert r.state == "HOLD_INVALID_OUTPUT" and r.score is None


def test_client_non_json_body_holds() -> None:
    def bad(c: RunnerConfig, p: dict[str, Any]) -> dict[str, Any]:
        raise ValueError("not json")

    r = verify_crop(CFG, _req(), CROP, calibrated_renderer=RENDERER, transport=bad)
    assert r.state == "HOLD_INVALID_OUTPUT"


def test_client_failures_never_call_or_accept() -> None:
    r = verify_crop(
        CFG, _req(crop_sha256=None), None, calibrated_renderer=RENDERER, transport=_boom
    )
    assert r.state == "HOLD_MISSING_CROP"
    r = verify_crop(
        CFG, _req(renderer_version="2"), CROP, calibrated_renderer=RENDERER, transport=_boom
    )
    assert r.state == "HOLD_RENDERER_MISMATCH"
    with pytest.raises(ValueError, match="crop_sha256"):
        verify_crop(CFG, _req(), b"other", calibrated_renderer=RENDERER, transport=_boom)


def test_client_unavailable_is_off_with_fallback() -> None:
    def down(c: RunnerConfig, p: dict[str, Any]) -> dict[str, Any]:
        raise RunnerUnavailable("down")

    r = verify_crop(CFG, _req(), CROP, calibrated_renderer=RENDERER, transport=down)
    assert (r.state, r.score, r.fallback) == ("OFF", None, "jev_off_policy")


def test_default_transport_refuses_without_network() -> None:
    cfg = RunnerConfig("jev", "rev1", endpoint="https://jev.example/v")  # allow_network False
    assert verify_crop(cfg, _req(), CROP, calibrated_renderer=RENDERER).state == "OFF"


def test_auroc_perfect_chance_inverted_ties_empty() -> None:
    assert auroc([(0.9, True), (0.8, True), (0.2, False), (0.1, False)]) == 1.0
    assert auroc([(0.9, False), (0.8, False), (0.2, True), (0.1, True)]) == 0.0
    assert auroc([(0.5, True), (0.5, False)]) == 0.5
    assert auroc([(0.9, True), (0.5, True), (0.5, False), (0.1, False)]) == 0.875
    assert auroc([(0.9, True)]) is None


def _manifest() -> dict[str, Any]:
    docs = [{"doc_id": f"d{i}", "split": "dev"} for i in range(40)]
    docs.append({"doc_id": "h0", "split": "holdout"})
    return {"manifest_sha256": MSHA, "documents": docs}


def _obs(n: int = 40) -> list[PageObservation]:
    out = []
    for i in range(n):
        ok = i % 4 != 0  # every 4th page is wrong; hard gates pass on all
        score = 0.9 - 0.001 * i if ok else 0.1 + 0.001 * i
        out.append(PageObservation(f"p{i}", f"d{i}", "s1", True, score, ok, 0.01, 0.002))
    return out


def test_calibration_matched_coverage_and_report(tmp_path: Path) -> None:
    guard = HoldoutGuard(_manifest(), tmp_path / "log.jsonl")
    rep = calibrate_dev(guard, MSHA, _obs(), alpha_by_stratum={"s1": 0.2})
    assert rep["calibrated_from"] == MSHA + ":dev"
    assert "calibrated" not in rep and rep["human_review_required"] is True
    s = rep["strata"]["s1"]
    assert s["auroc"] == 1.0 and s["risk_coverage"]
    m = s["matched_coverage"]
    assert abs(m["jev_on"]["accepted_count"] - m["jev_off"]["accepted_count"]) <= 1
    # conformal picks the most permissive threshold that fits alpha, so a few errors remain
    assert m["jev_on"]["false_accept_rate"] <= 0.2
    assert m["jev_on"]["false_accept_rate"] < m["jev_off"]["false_accept_rate"]
    lo, hi = m["jev_on"]["false_accept_wilson_95"]
    assert 0.0 <= lo < hi < 1
    assert m["jev_on"]["cost_per_accepted_page_usd"] > m["jev_off"]["cost_per_accepted_page_usd"]
    path = write_calibration(rep, tmp_path)
    assert json.loads(path.read_text(encoding="utf-8")) == rep
    assert not (tmp_path / "log.jsonl").exists()  # dev calibration never opens the seal


def test_small_n_abstains(tmp_path: Path) -> None:
    guard = HoldoutGuard(_manifest(), tmp_path / "log.jsonl")
    rep = calibrate_dev(guard, MSHA, _obs(3), alpha_by_stratum={"s1": 0.05})
    s = rep["strata"]["s1"]
    assert s["calibration"]["accepted_count"] == 0
    assert s["matched_coverage"] is None and s["threshold"] is None


def test_holdout_input_raises(tmp_path: Path) -> None:
    guard = HoldoutGuard(_manifest(), tmp_path / "log.jsonl")
    bad = [*_obs(), PageObservation("ph", "h0", "s1", True, 0.9, True, 0.01, 0.0)]
    with pytest.raises(HoldoutSealedError):
        calibrate_dev(guard, MSHA, bad, alpha_by_stratum={"s1": 0.2})
    with pytest.raises(HoldoutSealedError):
        calibrate_dev(guard, MSHA, _obs(), alpha_by_stratum={"s1": 0.2}, split="holdout")
    with pytest.raises(ValueError, match="no alpha"):
        calibrate_dev(guard, MSHA, _obs(), alpha_by_stratum={})
