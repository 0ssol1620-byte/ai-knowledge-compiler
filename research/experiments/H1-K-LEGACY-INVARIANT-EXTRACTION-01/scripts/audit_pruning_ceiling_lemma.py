#!/usr/bin/env python3
"""H1-K Amendment 2 -- is `PRUNED_CANDIDATE_SCORE_CEILING = 0.80` an exactness lemma?

P2-13 §5 asks whether the existing ceiling can be reused as the pruning proof for
an exact sparse matcher. The lemma's own comment is careful and states exactly
one consequence:

    "Pruning therefore cannot turn AMBIGUOUS or NEW into MATCHED for a given row."

That is sound, and it is **not** the property an exact replacement needs. Exactness
requires that pruning change *no* observable facet, and there are two flips the
lemma does not address:

  (a) AMBIGUOUS -> NEW. A row whose assigned partner is withheld falls through to
      `resolve(unit, [])` and becomes NEW. Kept, it can be AMBIGUOUS -- via the
      review band [0.75, 0.80], or, as the probe actually found, via the
      missing-critical-signal branch at any score. Both outcomes are non-MATCHED,
      so the lemma's claim survives while the classification changes.

  (b) runner-up / candidate attribution. The lemma proves a pruned candidate
      cannot be the runner-up that fires the tie guard *on a pair that would
      otherwise merge* (0.87 > 0.80). It proves nothing about a pair already in
      the review band, where a pruned candidate can still change which unit is
      named in `candidates` -- a field H1-K Amendment 1 showed is semantic.

(a) is testable and is tested here. (b) is argued from the thresholds and from
Amendment 1's result, and is reported as an analytic gap rather than dressed up
as a measurement.

Nothing in identity.py is modified. Pruning is simulated by withholding the
candidate, which is what a pruning matcher would do.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
IDENT = ROOT / "packages" / "cir-python" / "src" / "akc_cir" / "identity.py"
sys.path.insert(0, str(ROOT / "packages" / "cir-python" / "src"))

from akc_cir.identity import (  # noqa: E402
    _TIE_BAND,
    MERGE_THRESHOLD,
    NEW_IDENTITY_THRESHOLD,
    PRUNED_CANDIDATE_SCORE_CEILING,
    LogicalIdentityResolver,
    LogicalUnitFingerprint,
    MatchingPolicy,
    assign_one_to_one,
)


def unit(lid, text, path, anchor=None, identifier=None, source=None):
    kwargs: dict[str, Any] = {
        "logical_id": lid,
        "text": text,
        "document_path": path,
        "anchor": anchor if anchor is not None else lid,
    }
    if identifier is not None:
        kwargs["explicit_identifier"] = identifier
    if source is not None:
        kwargs["source_document_version"] = source
    try:
        return LogicalUnitFingerprint.of(**kwargs)
    except TypeError:
        kwargs.pop("source_document_version", None)
        return LogicalUnitFingerprint.of(**kwargs)


def decide(inc, prev):
    return assign_one_to_one(
        list(inc), list(prev),
        resolver=LogicalIdentityResolver(), policy=MatchingPolicy.LEGACY,
    )


def search_ambiguous_to_new() -> dict[str, Any]:
    """Does withholding a prunable candidate flip a row AMBIGUOUS -> NEW?

    Every candidate here has disjoint path roots, so `_path_agreement` is 0.0 and
    the ceiling licenses pruning it. Kept, the row is assigned it; withheld, the
    row falls through to `resolve(unit, [])` and becomes NEW. If the kept
    classification is anything but NEW, the ceiling is not sufficient for
    exactness -- whatever branch produced it.
    """
    attempts = []
    texts = [
        ("the quick brown fox jumps", "the quick brown fox jumps"),
        ("alpha beta gamma delta epsilon zeta", "alpha beta gamma delta epsilon zeta"),
        ("one two three four five six seven", "one two three four five six seven eight"),
        ("warranty term is twenty four months", "warranty term is twenty four months"),
    ]
    for before, after in texts:
        for ident in ("shared-identifier", None):
            # Disjoint path roots => `_path_agreement` is 0.0 => the pruning
            # regime the ceiling describes.
            prev = [unit("u1", before, ("RootA", "Sec"), identifier=ident)]
            inc = [unit("n1", after, ("RootB", "Sec"), identifier=ident)]
            engine = LogicalIdentityResolver()
            score, signals, _missing = engine.score_pair(prev[0], inc[0])
            kept = decide(inc, prev)[0]
            withheld = decide(inc, [])[0]
            attempts.append(
                {
                    "identifier": ident,
                    "score": round(score, 6),
                    "path_agreement": round(signals.get("structural_path", -1.0), 6),
                    "within_ceiling": score <= PRUNED_CANDIDATE_SCORE_CEILING,
                    "in_review_band": NEW_IDENTITY_THRESHOLD <= score < MERGE_THRESHOLD,
                    "kept": {"match": kept.match.value, "logical_id": kept.logical_id,
                             "candidates": list(kept.candidates)},
                    "withheld": {"match": withheld.match.value,
                                 "logical_id": withheld.logical_id,
                                 "candidates": list(withheld.candidates)},
                    "flips": (kept.match.value, kept.logical_id)
                    != (withheld.match.value, withheld.logical_id),
                }
            )
    flipping = [a for a in attempts if a["flips"]]
    return {
        "attempts": attempts,
        "flipping_count": len(flipping),
        "found_ambiguous_to_new": any(
            a["kept"]["match"] == "ambiguous" and a["withheld"]["match"] == "new"
            for a in attempts
        ),
        "examples": flipping[:3],
    }


def canonical_sha256(v: Any) -> str:
    body = json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def main() -> int:
    exp = Path(__file__).resolve().parents[1]
    out = exp / "receipts" / "pruning-ceiling-lemma-audit-2026-08-19.json"

    flip = search_ambiguous_to_new()

    band_gap = {
        "ceiling": PRUNED_CANDIDATE_SCORE_CEILING,
        "new_threshold": NEW_IDENTITY_THRESHOLD,
        "merge_threshold": MERGE_THRESHOLD,
        "tie_band": _TIE_BAND,
        "merge_minus_tie": round(MERGE_THRESHOLD - _TIE_BAND, 6),
        "ceiling_below_merge": PRUNED_CANDIDATE_SCORE_CEILING < MERGE_THRESHOLD,
        "ceiling_below_merge_minus_tie": PRUNED_CANDIDATE_SCORE_CEILING
        < MERGE_THRESHOLD - _TIE_BAND,
        "review_band_overlap": [
            NEW_IDENTITY_THRESHOLD, PRUNED_CANDIDATE_SCORE_CEILING
        ],
        "overlap_is_nonempty": NEW_IDENTITY_THRESHOLD < PRUNED_CANDIDATE_SCORE_CEILING,
        "why_it_matters": (
            "A pruned candidate can score anywhere in [0.75, 0.80]. That is inside "
            "the review band, so it can be the assigned partner of a row and make "
            "it AMBIGUOUS, and it can be the runner-up of a review-band pair and "
            "change which unit is named in `candidates`. Neither is a MATCHED "
            "promotion, so neither is excluded by the lemma."
        ),
    }

    receipt: dict[str, Any] = {
        "schema": "tavonel.pruning-ceiling-lemma-audit.v1",
        "experiment": "H1-K-LEGACY-INVARIANT-EXTRACTION-01",
        "amendment": "AMENDMENT_2_2026-08-19.md",
        "generated_at": datetime.now(UTC).isoformat(),
        "identity_module_sha256": "sha256:"
        + hashlib.sha256(IDENT.read_bytes()).hexdigest(),
        "lemma_as_stated": (
            "Pruning cannot turn AMBIGUOUS or NEW into MATCHED for a given row."
        ),
        "lemma_is_sound_as_stated": True,
        "lemma_sufficient_for_exactness": False,
        "gap_a_ambiguous_to_new": flip,
        "mechanism_correction": {
            "predicted": (
                "AMBIGUOUS -> NEW would be demonstrated via the review band: a "
                "pruned candidate scoring in [0.75, 0.80] makes the row AMBIGUOUS "
                "when kept and NEW when withheld."
            ),
            "observed": (
                "The flips are real and reproduce 8/8, but the scores are 0.60 and "
                "0.4286 -- BELOW the 0.75 floor. The AMBIGUOUS comes from the "
                "missing-critical-signal branch (`source_continuity` absent), which "
                "is evaluated BEFORE the new-threshold check and returns AMBIGUOUS "
                "regardless of score."
            ),
            "why_the_finding_is_stronger_not_weaker": (
                "The prediction required a narrow score window. The observed "
                "mechanism needs none: withholding ANY candidate that would have "
                "been the row's assigned partner can flip AMBIGUOUS -> NEW whenever "
                "a critical signal is absent, at any score within the pruning "
                "regime. The candidates used here have path_agreement 0.0 and "
                "scores <= 0.80, so they are exactly what the ceiling licenses "
                "pruning."
            ),
            "review_band_gap_still_open": (
                "The [0.75, 0.80] overlap argument is a SEPARATE analytic gap and "
                "was NOT exercised by these cases. It is reported as analysis, not "
                "as a measurement."
            ),
        },
        "gap_b_runner_up_attribution": {
            "type": "analytic, not measured in this receipt",
            "argument": (
                "The lemma excludes a pruned candidate from being the runner-up "
                "that fires the tie guard on a pair that would otherwise MERGE, "
                "because 0.87 > 0.80. It does not exclude it from being the "
                "runner-up of a pair already in the review band, where the tie "
                "guard returns candidates=(best, runner_up). Withholding it "
                "changes that tuple."
            ),
            "why_this_is_now_load_bearing": (
                "H1-K Amendment 1 established that candidate attribution is "
                "semantic: it seeds selective recompilation and the promotion "
                "gate and is serialized. Before that audit this gap looked "
                "cosmetic."
            ),
            "measured": False,
        },
        "threshold_analysis": band_gap,
        "verdict": (
            "CEILING_INSUFFICIENT_FOR_EXACT_PRUNING"
            if (flip["found_ambiguous_to_new"] or band_gap["overlap_is_nonempty"])
            else "CEILING_MAY_SUFFICE"
        ),
        "supersedes": "receipts/pruning-ceiling-attempt1-mischaracterized-2026-08-19.json",
        "consequence_for_p2_13": (
            "The existing ceiling may NOT be reused as the exactness lemma. An "
            "exact pruning proof must additionally establish that the pruned edge "
            "cannot be the assigned partner of any row (not merely cannot be a "
            "MATCHED partner), and cannot alter the runner-up of any row. "
            "Preserving the winner is not sufficient; the classification-relevant "
            "alternative set must be preserved too."
        ),
        "blocked_policy_touched": False,
        "identity_module_modified": False,
        "external_gpu_cost_usd": 0.0,
        "network_access": False,
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"verdict: {receipt['verdict']}")
    print(f"  lemma sound as stated:      {receipt['lemma_is_sound_as_stated']}")
    print(f"  sufficient for exactness:   {receipt['lemma_sufficient_for_exactness']}")
    print(f"  [0.75,0.80] overlap:        {band_gap['overlap_is_nonempty']}")
    print(f"  AMBIGUOUS->NEW found:       {flip['found_ambiguous_to_new']}")
    print(f"  flipping attempts:          {flip['flipping_count']}/{len(flip['attempts'])}")
    for a in flip["attempts"][:4]:
        print(f"    score={a['score']:.4f} path={a['path_agreement']:.2f} "
              f"kept={a['kept']['match']} withheld={a['withheld']['match']}")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
