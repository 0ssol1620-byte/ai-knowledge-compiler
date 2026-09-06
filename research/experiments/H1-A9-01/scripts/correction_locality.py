#!/usr/bin/env python3
"""Did the correction change only what it was supposed to change?

The endpoint-level before/after comparison says whether the conclusion survived.
It does not say whether the instrument behaved as claimed, and those are
different questions. The claim is narrow and checkable:

    the only pages whose score can move are the pages where a wall-clock
    fallback actually fired.

Every other page ran the exact matcher in both the frozen and the corrected
evaluator, so its score must be bit-identical. If a page that never fell back
scores differently, the correction did something beyond removing the wall-clock
decision, and the argument for re-measuring the holdout -- that only the
load-dependent path was removed -- is false.

That makes this a falsification test, not a summary. It compares the frozen and
corrected scorings of the *same* frozen predictions and refuses when a score
moves on a page with no recorded fallback.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

FALLBACK_LINE = re.compile(
    r"\[(?:timeout-fallback|match-timeout|quick-match-timeout)\] (.+?): "
)
ARTIFACTS = (
    "text_block_per_page_edit.json",
    "display_formula_per_page_edit.json",
    "reading_order_per_page_edit.json",
)
SEVERE = 0.10


def canonical_sha256(value: Any) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def page_scores(artifact_dir: Path) -> dict[str, dict[str, float]]:
    merged: dict[str, dict[str, float]] = {}
    for name in ARTIFACTS:
        path = artifact_dir / name
        if not path.is_file():
            continue
        metric = name.removesuffix("_per_page_edit.json")
        for page, value in json.loads(path.read_text(encoding="utf-8")).items():
            merged.setdefault(page, {})[metric] = float(value)
    return merged


def fallback_pages(logs: list[Path]) -> set[str]:
    pages: set[str] = set()
    for log in logs:
        if log.is_file():
            pages |= set(
                FALLBACK_LINE.findall(log.read_text(encoding="utf-8", errors="replace"))
            )
    return pages


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frozen-artifacts", type=Path, required=True)
    parser.add_argument("--corrected-artifacts", type=Path, required=True)
    parser.add_argument("--frozen-logs", type=Path, nargs="+", required=True)
    parser.add_argument("--corrected-logs", type=Path, nargs="*", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    frozen = page_scores(args.frozen_artifacts.resolve())
    corrected = page_scores(args.corrected_artifacts.resolve())
    fell_back = fallback_pages([p.resolve() for p in args.frozen_logs])
    corrected_fell_back = fallback_pages([p.resolve() for p in args.corrected_logs])

    shared = sorted(set(frozen) & set(corrected))
    moved = [page for page in shared if frozen[page] != corrected[page]]

    unexplained = sorted(page for page in moved if page not in fell_back)
    explained = sorted(page for page in moved if page in fell_back)

    # A fallback page whose score did *not* move is worth counting too: it means
    # the approximation happened to agree with the exact matcher there, which is
    # the honest reason the aggregate barely moves.
    fallback_unchanged = sorted(
        page for page in shared if page in fell_back and frozen[page] == corrected[page]
    )

    def severe(scores: dict[str, dict[str, float]]) -> dict[str, bool]:
        return {
            page: metrics["text_block"] > SEVERE
            for page, metrics in scores.items()
            if "text_block" in metrics
        }

    frozen_severe, corrected_severe = severe(frozen), severe(corrected)
    label_flips = sorted(
        page
        for page in shared
        if page in frozen_severe
        and page in corrected_severe
        and frozen_severe[page] != corrected_severe[page]
    )

    locality_holds = not unexplained and not corrected_fell_back

    receipt = {
        "schema": "tavonel.a9-correction-locality.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "frozen_artifacts": str(args.frozen_artifacts.resolve()),
        "corrected_artifacts": str(args.corrected_artifacts.resolve()),
        "pages_compared": len(shared),
        "pages_that_fell_back_under_the_frozen_evaluator": len(fell_back),
        "pages_that_fell_back_under_the_corrected_evaluator": len(corrected_fell_back),
        "pages_whose_score_moved": len(moved),
        "moved_and_had_fallen_back": explained,
        "moved_without_any_recorded_fallback": unexplained,
        "fell_back_but_score_unchanged": len(fallback_unchanged),
        "severe_label_flips": label_flips,
        "severe_before": sum(1 for flag in frozen_severe.values() if flag),
        "severe_after": sum(1 for flag in corrected_severe.values() if flag),
        "locality_holds": locality_holds,
        "what_this_falsifies": (
            "the claim that the correction removed only the wall-clock decision. "
            "A page that never fell back ran the exact matcher under both "
            "evaluators, so its score cannot legitimately move. Any page in "
            "moved_without_any_recorded_fallback contradicts that claim and "
            "invalidates the argument for re-measuring the holdout."
        ),
        "receipt_sha256": None,
    }
    receipt["receipt_sha256"] = canonical_sha256(
        {k: v for k, v in receipt.items() if k != "receipt_sha256"}
    )

    args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.output.resolve().write_text(
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(f"pages compared              : {len(shared)}")
    print(f"fell back (frozen evaluator): {len(fell_back)}")
    print(f"fell back (corrected)       : {len(corrected_fell_back)} (must be 0)")
    print(f"score moved                 : {len(moved)}")
    print(f"  of those, had fallen back : {len(explained)}")
    print(f"  with no recorded fallback : {len(unexplained)}")
    print(f"fell back, score unchanged  : {len(fallback_unchanged)}")
    print(f"severe labels               : {receipt['severe_before']} -> {receipt['severe_after']}")
    print(f"receipt: {args.output.resolve()}")

    if corrected_fell_back:
        raise SystemExit(
            f"{len(corrected_fell_back)} pages fell back under the corrected "
            "evaluator; the wall-clock path is still live"
        )
    if unexplained:
        for page in unexplained[:20]:
            print(f"  UNEXPLAINED {page}: {frozen[page]} -> {corrected[page]}")
        raise SystemExit(
            f"{len(unexplained)} pages changed score without ever having fallen "
            "back. The correction did more than remove the wall-clock decision, "
            "and the case for re-measuring the holdout does not hold as stated."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
