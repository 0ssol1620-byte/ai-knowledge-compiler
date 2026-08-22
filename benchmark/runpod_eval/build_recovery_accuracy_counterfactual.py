#!/usr/bin/env python3
"""Derive the olmOCR-Bench recovery counterfactual from the two evaluations.

This roll-up backs the campaign's headline number -- 80.6 against 53.7 when the
recovery lane's output is removed and nothing else changes. It was assembled by
hand during the run, which showed: the two fields meant to bind it to the
evaluation summaries it summarises were left null, so the artifact cited its own
sources and hashed neither.

Everything here is read from the two official summaries. Nothing is typed in.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

# Removing recovery makes some measurements look better, and a comparison that
# only reports the flattering direction is not a comparison. Both are carried.
CAVEAT_ABSENT = (
    "Tests of the 'absent' type check that text is NOT present, and an empty "
    "document passes them trivially. Their pass rate therefore rises without "
    "recovery ({with_rate} -> {without_rate}), which makes the no-recovery "
    "score generous rather than harsh."
)
DESIGN = (
    "Single-variable comparison. Model, evaluator revision, corpus, source "
    "manifest, test set and settings are identical; the only difference is "
    "whether the documents the recovery lane delivered carry content."
)
BOUNDARY = (
    "This measures the recovery lane's contribution on this corpus under this "
    "baseline model and evaluator revision. It is not comparable to published "
    "leaderboard numbers, which use different evaluator revisions and metric "
    "scopes."
)


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _canonical_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _side(summary: dict[str, Any], path: Path) -> dict[str, Any]:
    return {
        "overall_score": summary["overall_score"],
        "confidence_interval_95": summary["confidence_interval_95"],
        "rule_failure_count": summary["rule_failure_count"],
        "summary": path.name,
        "summary_sha256": _sha256(path),
    }


def _pairs(
    with_recovery: dict[str, Any], without_recovery: dict[str, Any], key: str
) -> dict[str, dict[str, float]]:
    """Line up one breakdown from both runs, refusing to invent a missing slice.

    A missing key returned an empty dict on the first pass, which produced an
    artifact with a silently empty per-type section rather than an error.
    """
    if key not in with_recovery or key not in without_recovery:
        raise KeyError(f"{key!r} is not present in both evaluation summaries")
    left = with_recovery[key]
    right = without_recovery[key]
    if set(left) != set(right):
        only_left = sorted(set(left) - set(right))
        only_right = sorted(set(right) - set(left))
        raise ValueError(
            f"{key} does not describe the same slices on both sides; "
            f"only in with_recovery: {only_left}, only in without: {only_right}"
        )
    return {
        slice_name: {
            "with_recovery": round(left[slice_name]["pass_rate"], 4),
            "without_recovery": round(right[slice_name]["pass_rate"], 4),
        }
        for slice_name in sorted(left)
    }


def _held_constant(
    with_recovery: dict[str, Any], without_recovery: dict[str, Any]
) -> dict[str, Any]:
    """A single-variable claim is only true if the other variables match."""
    held: dict[str, Any] = {}
    for field in ("evaluator_revision", "source_manifest_sha256", "input_count", "test_count"):
        left = with_recovery.get(field)
        right = without_recovery.get(field)
        if left != right:
            raise ValueError(
                f"{field} differs between the two runs ({left!r} vs {right!r}), so this "
                "is not a single-variable comparison"
            )
        held[field] = left
    return held


def build(with_path: Path, without_path: Path, emptied_documents: int) -> dict[str, Any]:
    with_recovery = _load(with_path)
    without_recovery = _load(without_path)
    held = _held_constant(with_recovery, without_recovery)

    per_type = _pairs(with_recovery, without_recovery, "type_breakdown")
    absent = per_type.get("absent")

    with_score = with_recovery["overall_score"]
    without_score = without_recovery["overall_score"]
    with_ci = with_recovery["confidence_interval_95"]
    without_ci = without_recovery["confidence_interval_95"]

    payload: dict[str, Any] = {
        "schema": "folynta.recovery-accuracy-counterfactual.v1",
        "question": (
            "How much of the official olmOCR-Bench score is attributable to the "
            "recovery lane?"
        ),
        "design": DESIGN,
        "interpretation_boundary": BOUNDARY,
        "held_constant": held,
        "documents_total": held["input_count"],
        "documents_emptied": emptied_documents,
        "with_recovery": _side(with_recovery, with_path),
        "without_recovery": _side(without_recovery, without_path),
        "absolute_score_delta": round(with_score - without_score, 4),
        # The hand-assembled version carried one field called
        # "relative_score_delta" holding 0.5009 -- the gap over the *without*
        # score. The gap over the *with* score is 0.3337. Both are arithmetically
        # true and they say different things, and the single ambiguous name
        # happened to hold the larger, more flattering one. Named separately so
        # a reader cannot pick one up without knowing which denominator it used.
        "score_share_lost_without_recovery": round(
            (with_score - without_score) / with_score, 4
        ),
        "score_uplift_over_no_recovery": round(
            (with_score - without_score) / without_score, 4
        ),
        "additional_rule_failures_without_recovery": (
            without_recovery["rule_failure_count"] - with_recovery["rule_failure_count"]
        ),
        # Non-overlapping intervals are what makes the gap a finding rather than
        # noise, so the comparison is recorded rather than asserted in prose.
        "confidence_intervals_overlap": not (
            with_ci[0] > without_ci[1] or without_ci[0] > with_ci[1]
        ),
        "per_category": _pairs(with_recovery, without_recovery, "per_jsonl"),
        "per_type": per_type,
        "score_inflation_allowed": False,
    }
    if absent is not None:
        payload["caveat_absent_tests"] = CAVEAT_ABSENT.format(
            with_rate=absent["with_recovery"], without_rate=absent["without_recovery"]
        )
    payload["receipt_sha256"] = _canonical_hash(payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--with-recovery-summary", required=True, type=Path)
    parser.add_argument("--without-recovery-summary", required=True, type=Path)
    parser.add_argument("--emptied-documents", required=True, type=int)
    parser.add_argument("--output-json", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = build(
        args.with_recovery_summary, args.without_recovery_summary, args.emptied_documents
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "with_recovery": payload["with_recovery"]["overall_score"],
                "without_recovery": payload["without_recovery"]["overall_score"],
                "confidence_intervals_overlap": payload["confidence_intervals_overlap"],
                "receipt_sha256": payload["receipt_sha256"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
