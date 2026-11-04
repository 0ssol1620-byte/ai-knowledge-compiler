"""Deterministic evaluators. No model, no judge, no repair.

Every function scores normalised outputs against gold and returns plain
numbers with their denominators. A metric that cannot be computed from what
exists (no human reference schema yet, no gold spans yet) is reported as
``NOT_MEASURED`` with the reason -- never estimated.
"""

from __future__ import annotations

import random
import re
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Final

from karena.gold.htmltext import squash

__all__ = [
    "ABSTAIN",
    "bootstrap_ci",
    "citation_scores",
    "doc_type_scores",
    "grounded_answer_scores",
    "macro_f1",
    "numeric_equal",
    "quote_supported",
    "schema_induction_scores",
    "span_prf",
    "typed_extraction_scores",
]

ABSTAIN: Final = "UNKNOWN"
BOOTSTRAP_SAMPLES: Final = 2000
BOOTSTRAP_SEED: Final = 20261104


@dataclass(frozen=True, slots=True)
class Interval:
    point: float
    low: float
    high: float
    n: int

    def to_dict(self) -> dict[str, float | int]:
        return {"point": self.point, "ci95_low": self.low, "ci95_high": self.high, "n": self.n}


def bootstrap_ci(rows: Sequence[Any], statistic: Callable[[Sequence[Any]], float]) -> Interval:
    """Percentile bootstrap over cases, seeded. Small n gives wide intervals -- by design."""

    if not rows:
        raise ValueError("a confidence interval over zero cases is not a measurement")
    rng = random.Random(BOOTSTRAP_SEED)  # noqa: S311 - resampling, not security
    draws = sorted(
        statistic([rows[rng.randrange(len(rows))] for _ in rows]) for _ in range(BOOTSTRAP_SAMPLES)
    )
    return Interval(
        point=statistic(rows),
        low=draws[int(0.025 * BOOTSTRAP_SAMPLES)],
        high=draws[int(0.975 * BOOTSTRAP_SAMPLES) - 1],
        n=len(rows),
    )


# ----------------------------------------------------------------- doc_type


def macro_f1(pairs: Sequence[tuple[str, str]]) -> float:
    """Macro-F1 over gold labels. An abstention counts against recall, not precision."""

    labels = sorted({gold for gold, _ in pairs})
    scores = []
    for label in labels:
        tp = sum(1 for gold, pred in pairs if gold == label and pred == label)
        fp = sum(1 for gold, pred in pairs if gold != label and pred == label)
        fn = sum(1 for gold, pred in pairs if gold == label and pred != label)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        scores.append(2 * precision * recall / (precision + recall) if precision + recall else 0.0)
    return sum(scores) / len(scores) if scores else 0.0


def doc_type_scores(pairs: Sequence[tuple[str, str | None]]) -> dict[str, Any]:
    """``pairs`` = (gold, predicted); ``None`` = the output did not parse."""

    scored = [(gold, pred if pred is not None else "__INVALID__") for gold, pred in pairs]
    confusion = Counter(f"{gold} -> {pred}" for gold, pred in scored if gold != pred)
    return {
        "n": len(scored),
        "macro_f1": bootstrap_ci(scored, macro_f1).to_dict() if scored else "NOT_MEASURED",
        "accuracy": sum(g == p for g, p in scored) / len(scored) if scored else None,
        "abstained": sum(p == ABSTAIN for _, p in scored),
        "invalid": sum(p == "__INVALID__" for _, p in scored),
        "confusions": dict(confusion.most_common()),
    }


# --------------------------------------------------------- numbers / quotes


def to_decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value).replace(",", "").strip())
    except InvalidOperation:
        return None


def numeric_equal(gold: object, predicted: object) -> bool:
    """Exact equality of the numbers, not of their spelling (``1.50`` == ``1.5``)."""

    left, right = to_decimal(gold), to_decimal(predicted)
    return left is not None and right is not None and left == right


def quote_supported(quote: object, source: str) -> bool:
    """The quote is verbatim in the source, whitespace-insensitively, and not trivial."""

    if not isinstance(quote, str):
        return False
    needle = squash(quote)
    return len(needle) >= 3 and needle in squash(source)


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text)


def typed_extraction_scores(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """``rows``: {gold_value, displayed, excerpt, output (normalised or None)}."""

    exact: list[float] = []
    quoted = 0
    quote_has_number = 0
    nulls = invalid = 0
    for row in rows:
        output = row["output"]
        if output is None:
            invalid += 1
            exact.append(0.0)
            continue
        if output.get("value") is None:
            nulls += 1
        exact.append(1.0 if numeric_equal(row["gold_value"], output.get("value")) else 0.0)
        quote = output.get("evidence_quote")
        if quote_supported(quote, row["excerpt"]):
            quoted += 1
            if _digits(str(row["displayed"])) and _digits(str(row["displayed"])) in _digits(
                str(quote)
            ):
                quote_has_number += 1
    n = len(rows)
    return {
        "n": n,
        "numeric_exact_match": (
            bootstrap_ci(exact, lambda xs: sum(xs) / len(xs)).to_dict() if n else "NOT_MEASURED"
        ),
        "evidence_quote_verbatim": {"count": quoted, "of": n},
        "evidence_quote_contains_gold_number": {"count": quote_has_number, "of": n},
        "null_value": nulls,
        "invalid": invalid,
    }


# ----------------------------------------------------------- grounded answer


def citation_scores(pairs: Iterable[tuple[set[str], set[str]]]) -> dict[str, Any]:
    """Micro citation precision/recall over (gold ids, predicted ids)."""

    tp = fp = fn = 0
    for gold, predicted in pairs:
        tp += len(gold & predicted)
        fp += len(predicted - gold)
        fn += len(gold - predicted)
    return {
        "precision": {"value": tp / (tp + fp) if tp + fp else None, "tp": tp, "fp": fp},
        "recall": {"value": tp / (tp + fn) if tp + fn else None, "tp": tp, "fn": fn},
    }


def grounded_answer_scores(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """``rows``: {truth, excerpts {id: text}, output (normalised or None)}."""

    answerable = [r for r in rows if r["truth"]["answerable"]]
    unanswerable = [r for r in rows if not r["truth"]["answerable"]]
    correct: list[float] = []
    citation_pairs: list[tuple[set[str], set[str]]] = []
    unsupported = claims_total = invalid = wrongly_abstained = 0
    for row in rows:
        output = row["output"]
        if output is None:
            invalid += 1
            continue
        for claim in output.get("claims", []):
            claims_total += 1
            cited = [row["excerpts"].get(c) for c in claim.get("citations", [])]
            if (
                not cited
                or any(text is None for text in cited)
                or not any(quote_supported(claim.get("quote"), text or "") for text in cited)
            ):
                unsupported += 1
    for row in answerable:
        output = row["output"]
        if output is None:
            correct.append(0.0)
            citation_pairs.append((set(row["truth"]["citation_ids"]), set()))
            continue
        claims = output.get("claims", [])
        if output.get("status") != "ANSWERED":
            wrongly_abstained += 1
        values = [c.get("value") for c in claims]
        ok = output.get("status") == "ANSWERED" and any(
            numeric_equal(row["truth"]["value"], v) for v in values
        )
        correct.append(1.0 if ok else 0.0)
        predicted = {cid for c in claims for cid in c.get("citations", [])}
        citation_pairs.append((set(row["truth"]["citation_ids"]), predicted))
    abstained_correctly = sum(
        1
        for r in unanswerable
        if r["output"] is not None and r["output"].get("status") == "ABSTAINED"
    )
    return {
        "n": len(rows),
        "answerable": len(answerable),
        "unanswerable": len(unanswerable),
        "answer_exact_match": (
            bootstrap_ci(correct, lambda xs: sum(xs) / len(xs)).to_dict()
            if correct
            else "NOT_MEASURED"
        ),
        "citations": citation_scores(citation_pairs),
        "abstained_when_unanswerable": {"count": abstained_correctly, "of": len(unanswerable)},
        "abstained_when_answerable": {"count": wrongly_abstained, "of": len(answerable)},
        "unsupported_claims": {"count": unsupported, "of": claims_total},
        "invalid": invalid,
    }


# ---------------------------------------------------------- schema induction


def normalise_type_name(name: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]", "", name.casefold())


def schema_induction_scores(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """``rows``: {excerpts {id: text}, output (normalised or None), reference (None or schema)}."""

    examples = valid_examples = types = duplicate_types = 0
    relations = bad_endpoints = invalid = 0
    recall_pairs: list[tuple[set[str], set[str]]] = []
    for row in rows:
        output = row["output"]
        if output is None:
            invalid += 1
            continue
        names = [normalise_type_name(t.get("name", "")) for t in output.get("entity_types", [])]
        types += len(names)
        duplicate_types += len(names) - len(set(names))
        for item in [*output.get("entity_types", []), *output.get("relation_types", [])]:
            for example in item.get("examples", []):
                examples += 1
                source = row["excerpts"].get(example.get("excerpt_id"))
                if source is not None and quote_supported(example.get("quote"), source):
                    valid_examples += 1
        known = set(names)
        for relation in output.get("relation_types", []):
            relations += 1
            if (
                not {
                    normalise_type_name(relation.get("source_type", "")),
                    normalise_type_name(relation.get("target_type", "")),
                }
                <= known
            ):
                bad_endpoints += 1
        reference = row.get("reference")
        if reference is not None:
            recall_pairs.append(
                ({normalise_type_name(t["name"]) for t in reference["entity_types"]}, known)
            )
    result: dict[str, Any] = {
        "n": len(rows),
        "invalid": invalid,
        "entity_types_proposed": types,
        "duplicate_type_names": {"count": duplicate_types, "of": types},
        "evidence_examples_verbatim": {"count": valid_examples, "of": examples},
        "relation_endpoints_outside_schema": {"count": bad_endpoints, "of": relations},
    }
    if recall_pairs:
        hits = sum(len(gold & pred) for gold, pred in recall_pairs)
        total = sum(len(gold) for gold, _ in recall_pairs)
        result["type_recall_exact_name_lower_bound"] = {"count": hits, "of": total}
    else:
        result["type_recall"] = (
            "NOT_MEASURED: no human reference schema exists yet (programme F-10); "
            "semantic type matching is a person's judgement"
        )
    return result


# --------------------------------------------------- entity / relation spans


def span_prf(
    gold: Iterable[tuple[object, ...]], predicted: Iterable[tuple[object, ...]]
) -> dict[str, float | int]:
    """Exact-match P/R/F1 over (doc, start, end, type) or (head, relation, tail) tuples."""

    gold_set, predicted_set = set(gold), set(predicted)
    tp = len(gold_set & predicted_set)
    precision = tp / len(predicted_set) if predicted_set else 0.0
    recall = tp / len(gold_set) if gold_set else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "tp": tp,
        "gold": len(gold_set),
        "predicted": len(predicted_set),
    }
