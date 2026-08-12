"""Contract A's metric list, each with the denominator it is measured over.

"Every rate carries its denominator" is a repository rule, so a rate here is
never a bare float: it is a `Rate` with its numerator, its denominator and the
name of the population that denominator counts. A rate whose denominator is
zero is `None`, not `0.0` -- there is a difference between "none of them" and
"there were none".

Statistics per the contract: paired at document-pair level, McNemar for the
binary judgements, a 10,000-resample bootstrap for the rates, Holm-Bonferroni
across the slices, fixed seeds. The bootstrap draws from a small splitmix64
generator written here rather than `random`, for two reasons: the sequence is
then identical on every platform and Python version, which the reproducibility
gate needs, and the ruff `S311` rule is right that `random` has no business in
package code.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .evolution_suite import (
    CRITICAL_MUTATIONS,
    LAYOUT_ONLY_MUTATIONS,
    MutationCase,
    MutationClass,
)
from .harness import DOCUMENT_ARTIFACT, Arm, ArmOutcome, artifact_id_for

__all__ = [
    "BOOTSTRAP_RESAMPLES",
    "BOOTSTRAP_SEED",
    "CaseScore",
    "Rate",
    "bootstrap_ci",
    "holm_bonferroni",
    "mcnemar_exact",
    "rate",
    "score_case",
    "summarise",
]

BOOTSTRAP_RESAMPLES = 10_000
BOOTSTRAP_SEED = 0x45585030_31303100  # "EXP0101\0"


@dataclass(frozen=True, slots=True)
class Rate:
    numerator: int
    denominator: int
    population: str

    @property
    def value(self) -> float | None:
        if self.denominator == 0:
            return None
        return self.numerator / self.denominator

    def as_record(self) -> dict[str, object]:
        return {
            "value": self.value,
            "numerator": self.numerator,
            "denominator": self.denominator,
            "population": self.population,
        }


def rate(numerator: int, denominator: int, population: str) -> Rate:
    return Rate(numerator=numerator, denominator=denominator, population=population)


class _SplitMix64:
    """A 64-bit generator with a fixed sequence, so a bootstrap is reproducible."""

    __slots__ = ("_state",)

    def __init__(self, seed: int) -> None:
        self._state = seed & 0xFFFFFFFFFFFFFFFF

    def next_u64(self) -> int:
        self._state = (self._state + 0x9E3779B97F4A7C15) & 0xFFFFFFFFFFFFFFFF
        value = self._state
        value = ((value ^ (value >> 30)) * 0xBF58476D1CE4E5B9) & 0xFFFFFFFFFFFFFFFF
        value = ((value ^ (value >> 27)) * 0x94D049BB133111EB) & 0xFFFFFFFFFFFFFFFF
        return value ^ (value >> 31)

    def below(self, bound: int) -> int:
        return self.next_u64() % bound


@dataclass(frozen=True, slots=True)
class CaseScore:
    """One arm on one case, scored against gold. The unit the bootstrap resamples."""

    case_id: str
    mutation: MutationClass
    arm: Arm
    #: Did the arm report a semantic change at all?
    reported_semantic: bool
    gold_semantic: bool
    #: Did it report one on the unit gold says changed?
    detected_gold_change: bool
    #: Same, but counting an unresolved identity naming that unit as surfaced.
    surfaced_gold_change: bool
    #: Did it *name* the change critical? Only an arm with type reasoning can.
    labelled_critical: bool
    left_unresolved: bool
    alignment_true_positives: int
    alignment_predicted: int
    alignment_gold: int
    false_merges: int
    false_splits: int
    impact_recall_hit: int
    impact_recall_total: int
    rebuild_equivalent: bool
    rebuild_fraction: float

    @property
    def correct_semantic_judgement(self) -> bool:
        return self.reported_semantic == self.gold_semantic

    @property
    def mutation_is_layout(self) -> bool:
        return self.mutation in LAYOUT_ONLY_MUTATIONS

    @property
    def mutation_is_critical(self) -> bool:
        return self.mutation in CRITICAL_MUTATIONS


def score_case(case: MutationCase, outcome: ArmOutcome) -> CaseScore:
    gold_pairs = set(case.gold.aligned_pairs)
    arm_pairs = set(outcome.aligned_pairs)
    gold_changed = set(case.gold.changed_logical_ids)
    reported = set(outcome.semantic_change_ids)
    unresolved = set(outcome.unresolved_candidates)

    # A false merge is a pair the arm asserted that gold does not hold. A gold
    # pair the arm left unresolved is neither a merge nor a split: abstention is
    # the third outcome, and scoring it as a split would make the arm that
    # abstains look worse than the arm that guesses.
    false_merges = len(arm_pairs - gold_pairs)
    false_splits = sum(
        1
        for before_id, _after_id in gold_pairs
        if before_id not in {pair[0] for pair in arm_pairs} and before_id not in unresolved
    )

    detected = bool(gold_changed & reported) if gold_changed else False
    surfaced = detected or bool(gold_changed & unresolved)

    gold_impacted = _artifact_names(gold_changed)
    arm_impacted = set(outcome.impacted)

    return CaseScore(
        case_id=case.case_id,
        mutation=case.mutation,
        arm=outcome.arm,
        reported_semantic=outcome.reports_semantic_change,
        gold_semantic=case.gold.semantic_change,
        detected_gold_change=detected,
        surfaced_gold_change=surfaced,
        labelled_critical=bool(gold_changed & set(outcome.critical_change_ids)),
        left_unresolved=bool(unresolved),
        alignment_true_positives=len(arm_pairs & gold_pairs),
        alignment_predicted=len(arm_pairs),
        alignment_gold=len(gold_pairs),
        false_merges=false_merges,
        false_splits=false_splits,
        impact_recall_hit=len(arm_impacted & gold_impacted),
        impact_recall_total=len(gold_impacted),
        rebuild_equivalent=outcome.rebuild.equivalent if outcome.rebuild else False,
        rebuild_fraction=outcome.rebuild.rebuild_fraction if outcome.rebuild else 0.0,
    )


def _artifact_names(unit_ids: set[str]) -> set[str]:
    if not unit_ids:
        return set()
    names = {artifact_id_for(unit_id) for unit_id in unit_ids}
    names.add(DOCUMENT_ARTIFACT)
    return names


# ---------------------------------------------------------------------------
# statistics
# ---------------------------------------------------------------------------


def mcnemar_exact(discordant_a: int, discordant_b: int) -> float:
    """Two-sided exact McNemar over the discordant pairs.

    `discordant_a` is the count where A was right and B wrong, `discordant_b`
    the reverse. The concordant pairs carry no information about a difference
    and are deliberately not in the denominator.
    """
    total = discordant_a + discordant_b
    if total == 0:
        return 1.0
    smaller = min(discordant_a, discordant_b)
    tail = sum(math.comb(total, index) for index in range(smaller + 1))
    return min(1.0, 2.0 * tail / (2.0**total))


def bootstrap_ci(
    values: list[float],
    *,
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
    confidence: float = 0.95,
) -> tuple[float, float] | None:
    """Percentile bootstrap over the case-level values, paired by construction.

    Returns `None` for an empty population rather than a zero-width interval
    around nothing.
    """
    count = len(values)
    if count == 0:
        return None
    generator = _SplitMix64(seed)
    means: list[float] = []
    for _ in range(resamples):
        total = 0.0
        for _index in range(count):
            total += values[generator.below(count)]
        means.append(total / count)
    means.sort()
    tail = (1.0 - confidence) / 2.0
    low = means[int(tail * resamples)]
    high = means[min(resamples - 1, int((1.0 - tail) * resamples))]
    return low, high


def holm_bonferroni(pvalues: dict[str, float]) -> dict[str, float]:
    """Step-down adjustment across the slices. Order-stable for equal p-values."""
    ordered = sorted(pvalues.items(), key=lambda item: (item[1], item[0]))
    count = len(ordered)
    adjusted: dict[str, float] = {}
    running = 0.0
    for position, (label, value) in enumerate(ordered):
        running = max(running, min(1.0, (count - position) * value))
        adjusted[label] = running
    return adjusted


# ---------------------------------------------------------------------------
# aggregation
# ---------------------------------------------------------------------------


def summarise(scores: list[CaseScore], *, with_ci: bool = True) -> dict[str, object]:
    """Every headline metric for one arm, each with its denominator."""
    layout = [item for item in scores if item.mutation in LAYOUT_ONLY_MUTATIONS]
    critical = [item for item in scores if item.mutation in CRITICAL_MUTATIONS]
    numeric = [
        item
        for item in scores
        if item.mutation is MutationClass.TABLE_CELL_NUMERIC_CHANGE
    ]
    positives = [item for item in scores if item.gold_semantic]
    predicted = [item for item in scores if item.reported_semantic]

    alignment_tp = sum(item.alignment_true_positives for item in scores)
    alignment_predicted = sum(item.alignment_predicted for item in scores)
    alignment_gold = sum(item.alignment_gold for item in scores)
    precision = alignment_tp / alignment_predicted if alignment_predicted else None
    recall = alignment_tp / alignment_gold if alignment_gold else None
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision and recall and (precision + recall)
        else None
    )

    summary: dict[str, object] = {
        "cases": len(scores),
        "alignment_precision": {
            "value": precision,
            "numerator": alignment_tp,
            "denominator": alignment_predicted,
            "population": "pairs the arm asserted",
        },
        "alignment_recall": {
            "value": recall,
            "numerator": alignment_tp,
            "denominator": alignment_gold,
            "population": "gold aligned pairs",
        },
        "alignment_f1": f1,
        "semantic_change_precision": rate(
            sum(1 for item in predicted if item.gold_semantic),
            len(predicted),
            "cases where the arm reported a semantic change",
        ).as_record(),
        "semantic_change_recall": rate(
            sum(1 for item in positives if item.reported_semantic),
            len(positives),
            "injected mutations that change meaning",
        ).as_record(),
        "layout_only_false_positive_rate": rate(
            sum(1 for item in layout if item.reported_semantic),
            len(layout),
            "pure-layout mutation cases",
        ).as_record(),
        "layout_only_unresolved_rate": rate(
            sum(1 for item in layout if item.left_unresolved),
            len(layout),
            "pure-layout mutation cases",
        ).as_record(),
        # The one that matters for cost. A layout change reported as a semantic
        # change and a layout change left unresolved both end in a rebuild, so
        # reading the false-positive rate alone lets an arm look better by
        # abstaining more. This counts either.
        "layout_only_false_invalidation_rate": rate(
            sum(1 for item in layout if item.reported_semantic or item.left_unresolved),
            len(layout),
            "pure-layout mutation cases",
        ).as_record(),
        "critical_change_recall": rate(
            sum(1 for item in critical if item.detected_gold_change),
            len(critical),
            "controlled high-risk mutation cases",
        ).as_record(),
        "critical_change_surfaced_rate": rate(
            sum(1 for item in critical if item.surfaced_gold_change),
            len(critical),
            "controlled high-risk mutation cases",
        ).as_record(),
        "critical_change_labelled_rate": rate(
            sum(1 for item in critical if item.labelled_critical),
            len(critical),
            "controlled high-risk mutation cases",
        ).as_record(),
        "critical_numeric_change_recall": rate(
            sum(1 for item in numeric if item.detected_gold_change),
            len(numeric),
            "injected numeric mutations",
        ).as_record(),
        "identity_false_merges": rate(
            sum(item.false_merges for item in scores),
            sum(item.alignment_gold for item in scores),
            "gold identity pairs",
        ).as_record(),
        "identity_false_splits": rate(
            sum(item.false_splits for item in scores),
            sum(item.alignment_gold for item in scores),
            "gold identity pairs",
        ).as_record(),
        "critical_false_merges": rate(
            sum(item.false_merges for item in critical),
            sum(item.alignment_gold for item in critical),
            "gold identity pairs in high-risk cases",
        ).as_record(),
        "downstream_impact_recall": rate(
            sum(item.impact_recall_hit for item in scores),
            sum(item.impact_recall_total for item in scores),
            "gold impacted artifacts",
        ).as_record(),
        "selective_full_equivalence": rate(
            sum(1 for item in scores if item.rebuild_equivalent),
            len(scores),
            "all cases",
        ).as_record(),
        "mean_rebuild_fraction": (
            sum(item.rebuild_fraction for item in scores) / len(scores) if scores else None
        ),
    }

    if with_ci:
        summary["confidence_intervals"] = {
            "semantic_change_recall": bootstrap_ci(
                [1.0 if item.reported_semantic else 0.0 for item in positives]
            ),
            "layout_only_false_positive_rate": bootstrap_ci(
                [1.0 if item.reported_semantic else 0.0 for item in layout]
            ),
            "layout_only_false_invalidation_rate": bootstrap_ci(
                [
                    1.0 if (item.reported_semantic or item.left_unresolved) else 0.0
                    for item in layout
                ]
            ),
            "critical_change_recall": bootstrap_ci(
                [1.0 if item.detected_gold_change else 0.0 for item in critical]
            ),
            "selective_full_equivalence": bootstrap_ci(
                [1.0 if item.rebuild_equivalent else 0.0 for item in scores]
            ),
        }
    return summary
