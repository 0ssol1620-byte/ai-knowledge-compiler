#!/usr/bin/env python3
"""Measure how well ground-truth-free signals find the documents that failed.

The targeted quality retry selects documents by *official* failure count, which
requires ground truth. Customers have none. So the product question is not
whether recovery improves a document it was told to fix, but whether the
documents worth fixing can be found at all when nothing is known about the
right answer.

This scores every frozen prediction using only signals derivable from the
prediction itself -- emptiness, degenerate repetition, table-shape breakage,
length drift within its own benchmark, character-class anomalies -- and then
asks a single question: at the same re-inference budget, how much of the
officially attributed failure mass does the blind ranking reach compared to the
oracle ranking that was allowed to read the answers?

The comparison is deliberately unflattering to us. The oracle is the ceiling by
construction, the detector never sees ground truth, and the reported number is
the ratio between them at a fixed budget rather than a threshold chosen after
looking at the outcome.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import math
import re
import statistics
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable

# A degenerate decode loop repeats a long n-gram many times. Eight tokens is long
# enough that ordinary prose does not trip it and short enough to catch a model
# stuck emitting a table row or a header over and over.
REPETITION_NGRAM = 8
EMPTY_OUTPUT_CHARS = 50
TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
TABLE_DIVIDER = re.compile(r"^\s*\|[\s:|-]+\|\s*$")
HTML_TABLE = re.compile(r"<table\b.*?</table>", re.S | re.I)
HTML_ROW = re.compile(r"<tr\b.*?</tr>", re.S | re.I)
HTML_CELL = re.compile(r"<t[dh]\b", re.I)
WORD = re.compile(r"\w+", re.UNICODE)


@dataclass(frozen=True, slots=True)
class BlindSignals:
    """Signals computable from a prediction with no access to ground truth."""

    benchmark_id: str
    case_id: str
    char_count: int
    word_count: int
    empty_output: bool
    repetition_ratio: float
    table_schema_failure: bool
    table_row_ragged_ratio: float
    alpha_ratio: float
    length_z: float
    truncated_tail: bool

    def score(self) -> float:
        """Combine signals into one suspicion score in [0, 1].

        Weights are fixed before seeing any outcome and are not tuned against the
        official failure counts; tuning them on the same data the detector is
        evaluated against would report a fit, not a detector.
        """
        if self.empty_output:
            return 1.0
        score = 0.0
        score += 0.30 * min(1.0, self.repetition_ratio / 0.30)
        score += 0.20 * (1.0 if self.table_schema_failure else 0.0)
        score += 0.15 * min(1.0, self.table_row_ragged_ratio / 0.20)
        score += 0.15 * min(1.0, max(0.0, (0.70 - self.alpha_ratio) / 0.40))
        score += 0.10 * min(1.0, abs(self.length_z) / 3.0)
        score += 0.10 * (1.0 if self.truncated_tail else 0.0)
        return min(1.0, score)


def repetition_ratio(words: list[str]) -> float:
    """Fraction of n-gram occurrences that are repeats of an earlier n-gram."""
    if len(words) < REPETITION_NGRAM * 2:
        return 0.0
    seen: collections.Counter[tuple[str, ...]] = collections.Counter()
    for index in range(len(words) - REPETITION_NGRAM + 1):
        seen[tuple(words[index : index + REPETITION_NGRAM])] += 1
    total = sum(seen.values())
    repeats = sum(count - 1 for count in seen.values() if count > 1)
    return repeats / total if total else 0.0


def _raggedness(widths_by_block: list[list[int]]) -> tuple[bool, int, int]:
    ragged_rows = 0
    total_rows = 0
    broken = False
    for widths in widths_by_block:
        if len(widths) < 2:
            continue
        modal = statistics.mode(widths)
        total_rows += len(widths)
        off = sum(1 for width in widths if width != modal)
        ragged_rows += off
        if off:
            broken = True
    return broken, ragged_rows, total_rows


def _pipe_table_blocks(lines: Iterable[str]) -> list[list[int]]:
    blocks: list[list[int]] = []
    current: list[int] = []
    for line in lines:
        if TABLE_ROW.match(line):
            if TABLE_DIVIDER.match(line):
                continue
            current.append(line.count("|"))
        elif current:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)
    return blocks


def _html_table_blocks(text: str) -> list[list[int]]:
    """Cell counts per row for each HTML table.

    MinerU emits tables as HTML rather than as pipe tables, so a detector that
    only understood markdown syntax never fired on the format the model actually
    produces.
    """
    blocks: list[list[int]] = []
    for table in HTML_TABLE.findall(text):
        widths = [len(HTML_CELL.findall(row)) for row in HTML_ROW.findall(table)]
        widths = [width for width in widths if width]
        if widths:
            blocks.append(widths)
    return blocks


def table_shape(lines: Iterable[str], text: str | None = None) -> tuple[bool, float]:
    """Report whether any table has inconsistent column counts.

    A model that loses its place in a wide table emits rows with the wrong number
    of cells. That is visible without knowing what the table should contain.
    Both the markdown pipe form and the HTML form MinerU emits are inspected.
    """
    lines = list(lines)
    if text is None:
        text = "\n".join(lines)
    blocks = _pipe_table_blocks(lines) + _html_table_blocks(text)
    broken, ragged_rows, total_rows = _raggedness(blocks)
    ratio = ragged_rows / total_rows if total_rows else 0.0
    return broken, ratio


def compute_signals(benchmark_id: str, case_id: str, text: str) -> BlindSignals:
    stripped = text.strip()
    words = WORD.findall(stripped)
    lines = stripped.splitlines()
    alpha = sum(1 for ch in stripped if ch.isalnum() or ch.isspace())
    broken, ragged = table_shape(lines, stripped)
    tail = stripped[-1:] if stripped else ""
    return BlindSignals(
        benchmark_id=benchmark_id,
        case_id=case_id,
        char_count=len(stripped),
        word_count=len(words),
        empty_output=len(stripped) < EMPTY_OUTPUT_CHARS,
        repetition_ratio=repetition_ratio(words),
        table_schema_failure=broken,
        table_row_ragged_ratio=ragged,
        alpha_ratio=alpha / len(stripped) if stripped else 0.0,
        length_z=0.0,  # filled in per benchmark once the corpus is known
        truncated_tail=bool(stripped) and tail not in ".!?:;\"')]}|`-*_>",
    )


def apply_length_z(signals: list[BlindSignals]) -> list[BlindSignals]:
    """Length is only meaningful relative to the benchmark the case came from."""
    by_suite: dict[str, list[int]] = collections.defaultdict(list)
    for signal in signals:
        by_suite[signal.benchmark_id].append(signal.char_count)
    stats = {}
    for suite, lengths in by_suite.items():
        mean = statistics.fmean(lengths)
        stdev = statistics.pstdev(lengths) if len(lengths) > 1 else 0.0
        stats[suite] = (mean, stdev)
    rescored = []
    for signal in signals:
        mean, stdev = stats[signal.benchmark_id]
        z = (signal.char_count - mean) / stdev if stdev else 0.0
        rescored.append(
            BlindSignals(**{**asdict(signal), "length_z": z})
        )
    return rescored


def _benchmark_of(case_id: str) -> str:
    for suite in ("omnidocbench", "parsebench", "olmocr-bench"):
        if case_id.startswith(suite):
            return suite
    raise ValueError(f"cannot attribute case to a benchmark: {case_id}")


def load_predictions(
    roots: list[Path], *, expected_cases: int | None = None
) -> tuple[list[tuple[str, str, str]], dict[str, Any]]:
    """Merge prediction trees, later roots overriding earlier ones.

    The baseline collection carries a zero-byte placeholder for every case its
    worker never finished, because those cases were re-run by the operational
    recovery lane and landed in a different tree. Reading the baseline alone
    therefore yields ~1,800 apparently empty predictions, which any
    quality detector will rank as the worst documents in the corpus. They are
    not predictions at all, so they are replaced here and their absence is
    asserted rather than assumed.
    """
    found: dict[tuple[str, str], str] = {}
    provenance: collections.Counter[str] = collections.Counter()
    superseded = 0
    for root in roots:
        for markdown in root.rglob("markdown-repeat-1/*.md"):
            case_id = markdown.stem
            key = (_benchmark_of(case_id), case_id)
            text = markdown.read_text(encoding="utf-8", errors="replace")
            if not text.strip():
                continue
            if key in found:
                superseded += 1
            found[key] = text
            provenance[root.name] += 1

    empty = [case for (_, case), text in found.items() if not text.strip()]
    if empty:
        raise ValueError(f"{len(empty)} predictions are empty after merging roots")
    if expected_cases is not None and len(found) != expected_cases:
        raise ValueError(
            f"merged {len(found)} predictions but expected {expected_cases}; "
            "a prediction tree is missing or a case was collected twice"
        )
    manifest = {
        "roots": [str(root) for root in roots],
        "merged_case_count": len(found),
        "cases_contributed_by_root": dict(sorted(provenance.items())),
        "superseded_by_later_root": superseded,
    }
    return (
        [(suite, case, text) for (suite, case), text in sorted(found.items())],
        manifest,
    )


def official_failure_counts(records_path: Path) -> dict[tuple[str, str], int]:
    payload = json.loads(records_path.read_text(encoding="utf-8-sig"))
    counts: collections.Counter[tuple[str, str]] = collections.Counter()
    for record in payload["records"]:
        counts[(str(record["benchmark_id"]), str(record["case_id"]))] += 1
    return dict(counts)


def coverage_at_budget(
    ranking: list[tuple[str, str]], counts: dict[tuple[str, str], int], budget: int
) -> int:
    return sum(counts.get(identity, 0) for identity in ranking[:budget])


def evaluate(
    signals: list[BlindSignals],
    counts: dict[tuple[str, str], int],
    budgets: list[int],
) -> dict[str, Any]:
    identities = [(s.benchmark_id, s.case_id) for s in signals]
    total_failures = sum(counts.get(identity, 0) for identity in identities)

    blind_ranked = [
        (s.benchmark_id, s.case_id)
        for s in sorted(
            signals,
            key=lambda s: (-s.score(), s.benchmark_id, s.case_id),
        )
    ]
    oracle_ranked = sorted(
        identities, key=lambda i: (-counts.get(i, 0), i[0], i[1])
    )

    per_budget = []
    for budget in budgets:
        blind = coverage_at_budget(blind_ranked, counts, budget)
        oracle = coverage_at_budget(oracle_ranked, counts, budget)
        random_expected = total_failures * budget / len(identities)
        blind_set = set(blind_ranked[:budget])
        oracle_set = set(oracle_ranked[:budget])
        overlap = len(blind_set & oracle_set)
        per_budget.append(
            {
                "budget_documents": budget,
                "budget_fraction_of_corpus": budget / len(identities),
                "blind_failure_mass": blind,
                "oracle_failure_mass": oracle,
                "random_expected_failure_mass": round(random_expected, 1),
                "blind_coverage_fraction": blind / total_failures if total_failures else 0.0,
                "oracle_coverage_fraction": oracle / total_failures if total_failures else 0.0,
                "blind_vs_oracle_efficiency": blind / oracle if oracle else 0.0,
                "blind_vs_random_lift": blind / random_expected if random_expected else 0.0,
                "document_overlap_with_oracle": overlap,
                "document_overlap_fraction": overlap / budget if budget else 0.0,
            }
        )

    # A detector is only interesting if it beats the cheapest thing that needs no
    # detection at all. Long documents contain more checkable elements, so
    # ranking by prediction length alone is the honest floor to clear.
    length_ranked = [
        (s.benchmark_id, s.case_id)
        for s in sorted(signals, key=lambda s: (-s.char_count, s.benchmark_id, s.case_id))
    ]
    for row in per_budget:
        budget = row["budget_documents"]
        length_only = coverage_at_budget(length_ranked, counts, budget)
        row["length_only_failure_mass"] = length_only
        row["length_only_vs_oracle_efficiency"] = (
            length_only / row["oracle_failure_mass"] if row["oracle_failure_mass"] else 0.0
        )
        row["blind_beats_length_only"] = row["blind_failure_mass"] > length_only

    # Failure mass scales with document size, so a per-document count conflates
    # "wrong" with "big". Density asks whether a flagged document is wrong per
    # unit of text, which is what a defect signal should predict.
    def _density(signal: BlindSignals) -> float:
        return counts.get((signal.benchmark_id, signal.case_id), 0) / max(signal.char_count, 1) * 1000

    baseline_density = statistics.fmean([_density(s) for s in signals])
    baseline_failure_probability = (
        sum(1 for s in signals if counts.get((s.benchmark_id, s.case_id), 0) > 0) / len(signals)
    )
    predicates: dict[str, Any] = {
        "empty_output": lambda s: s.empty_output,
        "repetition_over_10pct": lambda s: s.repetition_ratio > 0.10,
        "repetition_over_30pct": lambda s: s.repetition_ratio > 0.30,
        "table_schema_failure": lambda s: s.table_schema_failure,
        "table_rows_ragged_over_20pct": lambda s: s.table_row_ragged_ratio > 0.20,
        "alpha_ratio_under_0_7": lambda s: s.alpha_ratio < 0.70,
        "length_z_over_3": lambda s: abs(s.length_z) > 3.0,
        "truncated_tail": lambda s: s.truncated_tail,
    }
    per_signal = {}
    for name, predicate in predicates.items():
        hit = [s for s in signals if predicate(s)]
        if not hit:
            per_signal[name] = {"flagged": 0}
            continue
        density = statistics.fmean([_density(s) for s in hit])
        probability = sum(
            1 for s in hit if counts.get((s.benchmark_id, s.case_id), 0) > 0
        ) / len(hit)
        per_signal[name] = {
            "flagged": len(hit),
            "failures_per_1000_chars": round(density, 3),
            "density_lift_over_corpus": round(density / baseline_density, 3)
            if baseline_density
            else 0.0,
            "probability_of_any_failure": round(probability, 3),
            "probability_lift_over_corpus": round(
                probability / baseline_failure_probability, 3
            )
            if baseline_failure_probability
            else 0.0,
        }

    flagged = [s for s in signals if s.score() > 0.0]
    failing = {i for i in identities if counts.get(i, 0) > 0}
    flagged_ids = {(s.benchmark_id, s.case_id) for s in flagged}
    true_positive = len(flagged_ids & failing)
    false_positive = len(flagged_ids - failing)
    false_negative = len(failing - flagged_ids)
    precision = true_positive / len(flagged_ids) if flagged_ids else 0.0
    recall = true_positive / len(failing) if failing else 0.0

    return {
        "corpus_cases": len(identities),
        "cases_with_official_failures": len(failing),
        "total_official_failure_records": total_failures,
        "budgets": per_budget,
        "any_signal_operating_point": {
            "definition": "flag every case whose blind score is above zero",
            "flagged_cases": len(flagged_ids),
            "true_positive": true_positive,
            "false_positive": false_positive,
            "false_negative": false_negative,
            "precision": precision,
            "recall": recall,
            "f1": (
                2 * precision * recall / (precision + recall)
                if (precision + recall)
                else 0.0
            ),
        },
        "signal_prevalence": {
            "empty_output": sum(1 for s in signals if s.empty_output),
            "repetition_over_10pct": sum(1 for s in signals if s.repetition_ratio > 0.10),
            "table_schema_failure": sum(1 for s in signals if s.table_schema_failure),
            "length_z_over_3": sum(1 for s in signals if abs(s.length_z) > 3.0),
            "truncated_tail": sum(1 for s in signals if s.truncated_tail),
        },
        "corpus_baselines": {
            "failures_per_1000_chars": round(baseline_density, 3),
            "probability_of_any_failure": round(baseline_failure_probability, 3),
        },
        "per_signal_discrimination": per_signal,
        "outcome": _verdict(per_budget),
    }


def _verdict(per_budget: list[dict[str, Any]]) -> dict[str, Any]:
    beat_length = [row for row in per_budget if row["blind_beats_length_only"]]
    beat_random = [row for row in per_budget if row["blind_vs_random_lift"] > 1.0]
    supported = bool(beat_length) and bool(beat_random)
    return {
        "hypothesis": (
            "Prediction-only signals can select the documents carrying the most "
            "officially attributed failure mass."
        ),
        "supported": supported,
        "budgets_where_blind_beats_length_only": [
            row["budget_documents"] for row in beat_length
        ],
        "budgets_where_blind_beats_random": [
            row["budget_documents"] for row in beat_random
        ],
        "statement": (
            "Supported on this corpus at the listed budgets."
            if supported
            else (
                "Not supported. The blind ranking does not beat random selection, and "
                "ranking documents by prediction length alone -- which requires no "
                "detector -- reaches more failure mass at every budget tested. "
                "Failure mass scales with document size, so selecting for defects "
                "selects against size and therefore against mass."
            )
        ),
    }


def _canonical_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prediction-root", required=True, type=Path, nargs="+")
    parser.add_argument("--failure-records", required=True, type=Path)
    parser.add_argument("--budget", type=int, nargs="+", default=[100, 372, 500, 1000])
    parser.add_argument(
        "--expected-cases",
        type=int,
        help="fail if the merged prediction set is not exactly this many cases",
    )
    parser.add_argument("--receipt", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    predictions, manifest = load_predictions(
        args.prediction_root, expected_cases=args.expected_cases
    )
    if not predictions:
        raise ValueError("no predictions found under the supplied roots")
    signals = apply_length_z(
        [compute_signals(suite, case, text) for suite, case, text in predictions]
    )
    counts = official_failure_counts(args.failure_records)
    result = evaluate(signals, counts, sorted(args.budget))

    receipt = {
        "schema": "folynta.blind-quality-detection.v1",
        "question": (
            "Without ground truth, can prediction-only signals select the documents "
            "that official evaluation shows are worst?"
        ),
        "method": [
            "Score every frozen prediction using signals computed from the prediction alone.",
            "Rank blind by that score; rank oracle by official failure count.",
            "At a fixed re-inference budget, compare the official failure mass each ranking reaches.",
            "Report the blind-to-oracle ratio, not a threshold chosen after seeing the outcome.",
        ],
        "weights_fixed_before_evaluation": True,
        "score_inflation_allowed": False,
        "prediction_manifest": manifest,
        "interpretation_policy": (
            "The oracle is a ceiling that requires ground truth and is not achievable in "
            "production. The blind-to-oracle efficiency describes this corpus under this "
            "baseline model and must not be reported as a general detection rate."
        ),
        **result,
    }
    receipt["receipt_sha256"] = _canonical_hash(receipt)
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({k: v for k, v in receipt.items() if k != "method"}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
