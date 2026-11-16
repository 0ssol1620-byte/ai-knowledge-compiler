"""Dev-only Jev calibration: AUROC, risk/coverage, matched-coverage on/off false-accept CI.

Runs through ``HoldoutGuard`` with purpose ``calibrate``: a holdout split or a holdout
document raises. The report never marks a CalibrationTable calibrated; that stays a
separate, human-reviewed act.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from akc_quality.conformal_risk import calibrate_conformal_threshold
from akc_quality.evidence_ladder import SelectivePrediction, risk_coverage_curve

from benchmark.screen.manifest import HoldoutGuard, HoldoutSealedError
from benchmark.w6.v2.grading import wilson_interval


@dataclass(frozen=True, slots=True)
class PageObservation:
    page_id: str
    doc_id: str
    stratum: str
    hard_gates_passed: bool
    score: float | None  # None = verifier state was not SCORED (held)
    correct: bool  # ground truth, dev only
    parser_cost_usd: float
    verifier_cost_usd: float


def auroc(scored: Sequence[tuple[float, bool]]) -> float | None:
    """P(correct page outscores a wrong one), ties 0.5; None if a class is empty."""
    pos = [s for s, ok in scored if ok]
    neg = [s for s, ok in scored if not ok]
    if not pos or not neg:
        return None
    # ponytail: O(pos*neg) pair scan; sort-based ranks if a stratum reaches ~10^5 pages
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def _arm(
    accepted: Sequence[PageObservation],
    all_pages: Sequence[PageObservation],
    *,
    with_verifier: bool,
) -> dict[str, Any]:
    errors = sum(not o.correct for o in accepted)
    cost = sum(
        o.parser_cost_usd + (o.verifier_cost_usd if with_verifier else 0.0) for o in all_pages
    )
    return {
        "accepted_count": len(accepted),
        "false_accept_count": errors,
        "false_accept_rate": errors / len(accepted) if accepted else None,
        "false_accept_wilson_95": wilson_interval(errors, len(accepted)) if accepted else None,
        "cost_per_accepted_page_usd": cost / len(accepted) if accepted else None,
    }


def _stratum_report(obs: Sequence[PageObservation], alpha: float) -> dict[str, Any]:
    hard = [o for o in obs if o.hard_gates_passed]
    scored = [o for o in hard if o.score is not None]
    pairs = tuple((o.score, o.correct) for o in scored if o.score is not None)
    report: dict[str, Any] = {
        "pages": len(obs),
        "hard_gate_passed": len(hard),
        "scored": len(scored),
        "held": len(hard) - len(scored),
        "alpha": alpha,
        "auroc": auroc(pairs),
        "threshold": None,
        "calibration": None,
        "risk_coverage": [],
        "matched_coverage": None,
    }
    if not pairs:
        return report
    cal = calibrate_conformal_threshold(pairs, alpha=alpha)
    curve = risk_coverage_curve(
        [SelectivePrediction(s, ok) for s, ok in pairs],
        thresholds=sorted({s for s, _ in pairs}),
    )
    report["calibration"] = {
        "threshold": cal.threshold,
        "accepted_count": cal.accepted_count,
        "calibration_count": cal.calibration_count,
        "empirical_error_rate": cal.empirical_error_rate,
    }
    report["risk_coverage"] = [
        {
            "threshold": p.threshold,
            "coverage": p.coverage,
            "risk": p.risk,
            "accepted_count": p.accepted_count,
        }
        for p in curve
    ]
    if cal.accepted_count == 0:  # abstain: n too small to support alpha
        return report
    on = [o for o in scored if o.score is not None and o.score >= cal.threshold]
    # Jev-off has no ranking: take the same number of hard-gate-passed pages, in a
    # deterministic hash order, so both arms sit at the same coverage.
    off = sorted(hard, key=lambda o: hashlib.sha256(o.page_id.encode()).hexdigest())[: len(on)]
    report["threshold"] = cal.threshold
    report["matched_coverage"] = {
        "coverage": len(on) / len(obs),
        "jev_on": _arm(on, obs, with_verifier=True),
        "jev_off": _arm(off, obs, with_verifier=False),
    }
    return report


def calibrate_dev(
    guard: HoldoutGuard,
    manifest_sha256: str,
    observations: Sequence[PageObservation],
    *,
    alpha_by_stratum: Mapping[str, float],
    split: str = "dev",
) -> dict[str, Any]:
    dev_docs = {d["doc_id"] for d in guard.load(split, "calibrate")}  # holdout raises here
    by_stratum: dict[str, list[PageObservation]] = defaultdict(list)
    for o in observations:
        if o.doc_id not in dev_docs:
            raise HoldoutSealedError(f"{o.doc_id}: not a dev document; refusing to calibrate")
        by_stratum[o.stratum].append(o)
    missing = sorted(set(by_stratum) - set(alpha_by_stratum))
    if missing:
        raise ValueError(f"no alpha for strata {missing}")
    return {
        "calibrated_from": f"{manifest_sha256}:dev",
        "human_review_required": True,
        "strata": {
            s: _stratum_report(by_stratum[s], alpha_by_stratum[s]) for s in sorted(by_stratum)
        },
    }


def write_calibration(report: dict[str, Any], out_dir: Path) -> Path:
    path = Path(out_dir) / "jev-calibration.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return path
