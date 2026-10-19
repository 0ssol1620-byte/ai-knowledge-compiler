"""Paired statistics for ``tavonel.vendor_comparison.v1`` (lane AT-7).

COMPETITOR-PROTOCOL-2026-10-17 §4.4-4.5 and VENDOR-COMPARISON-PREREG.json ``statistics``
(DRAFT_PROPOSED, sha256 d68e0027e8c43fbcbe5c7bdfb77a27ee6ebf6ba5292b8ef992cde0c6354916c9).

* Δ = TAVONEL - vendor on the same units. A lower-is-better metric is flipped (vendor - TAVONEL),
  so a positive Δ always favours TAVONEL.
* The interval is a paired cluster bootstrap: one multiset of clusters (documents on the D axis,
  ``pdf_sha256`` on the A axis) is drawn and applied to both arms at once, and the statistic is
  recomputed with the caller's aggregate — the evaluator's own formula, never one invented here.
* A refused unit (product limit, CDR, timeout, vendor error, empty output, failed epoch) is
  ``None``. It scores 0 and stays in the denominator. On a lower-is-better metric zero would be
  the best possible score, so a ``None`` there is refused: the evaluator scores the empty
  prediction instead (§4.4).
* The verdicts are the Foundation ``documentAxisVerdict`` / ``answerAxisVerdict`` of
  ``nextjs/lib/benchmark-registry.ts`` (P2-21, commit 358dc3a3), rule for rule and in the same
  order: BEHIND, AHEAD, WITHIN, INCONCLUSIVE.

delta, the margin, alpha, the seed, the resample count and the level are arguments, never
constants: the preregistration only proposes them (founder decision FD-6), and a value typed here
would read as a sealed one. Bad input raises; a verdict standing on a NaN or a dropped document is
worse than none.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from fractions import Fraction
from math import comb
from typing import Literal

type Direction = Literal["higher", "lower"]
type Verdict = Literal["AHEAD", "WITHIN", "BEHIND", "INCONCLUSIVE"]
type Interval = tuple[float, float]

VERDICTS: tuple[Verdict, ...] = ("AHEAD", "WITHIN", "BEHIND", "INCONCLUSIVE")


# --------------------------------------------------------------------------- exact McNemar


# BEGIN VERBATIM COPY. The two statement lines between the fmt markers are copied verbatim,
# apart from the 4-space indent a function body needs, from
#   outputs/tavonel-research-replan-20261013/resume-20261015/competitive-20261015/
#   gdp-plan-scripts/reverify_ledgers.py, lines 52-53
#   (sha256 ca360f1dc7063b6e86f25ecfbc771820b34f4235c9abc38c84671a6137202f02, 61 lines, LF).
# outputs/ is untracked, so the script cannot be imported. It computes the test inline, not in a
# function, so the lines are wrapped in one whose parameters carry the script's variable names:
# n_only and c_only are the two discordant counts. `comb` is math.comb, imported the same way.
# The script rounds p to 4 places only when it prints; this function returns it unrounded.
def exact_mcnemar_p(n_only: int, c_only: int) -> float:
    """Two-sided exact McNemar p from the two discordant counts (binomial, p = 1/2)."""
    for count in (n_only, c_only):
        # Not in the script: a negative count would empty the sum and return p = 0.
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError("a discordant count must be a non-negative int")
    # fmt: off
    k, m = min(n_only, c_only), n_only + c_only
    p = min(1.0, 2 * sum(comb(m, i) for i in range(k + 1)) / 2 ** m) if m else 1.0
    # END VERBATIM COPY.
    # fmt: on
    return p


# --------------------------------------------------------------------------- bootstrap


@dataclass(frozen=True)
class PairedUnit[T]:
    """One scored unit in both arms. ``None`` is a refusal: it scores 0, it is never dropped."""

    unit_id: str
    cluster_id: str
    tavonel: T | None
    vendor: T | None


@dataclass(frozen=True)
class PairedDifference:
    point: float
    lower: float
    upper: float
    direction: Direction
    units: int
    clusters: int
    resamples: int
    level: float
    seed: str

    @property
    def ci(self) -> Interval:
        return (self.lower, self.upper)


type Aggregate[T] = Callable[[Sequence[T | None]], float | Fraction]


def mean_refused_as_zero(scores: Sequence[float | None]) -> float:
    """Mean over every unit given; a refusal (``None``) adds 0 and keeps its place in the count."""
    if not scores:
        raise ValueError("no units to aggregate")
    return math.fsum(0.0 if score is None else score for score in scores) / len(scores)


def _percentile(ordered: Sequence[float], q: float) -> float:
    # Linear interpolation between order statistics (numpy "linear", R type 7).
    position = q * (len(ordered) - 1)
    low = math.floor(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def paired_cluster_bootstrap[T](
    units: Sequence[PairedUnit[T]],
    *,
    aggregate: Aggregate[T],
    direction: Direction,
    denominator: int,
    seed: str,
    resamples: int,
    level: float,
) -> PairedDifference:
    """Point Δ and percentile CI from ``resamples`` paired cluster draws.

    ``denominator`` is the number of units provided (the prereg ``corpora[].N``, or the task
    count); a different unit count raises, because a refused unit is kept as ``None``, not
    dropped. The result is a pure function of the set of units and the seed: clusters are sorted
    by id and units within a cluster by unit id before anything is drawn. The generator is
    ``random.Random(seed)`` (a str seed is hashed with SHA-512) and ``Random.choices``.
    """
    if direction not in ("higher", "lower"):
        raise ValueError("direction must be 'higher' or 'lower'")
    if not isinstance(seed, str) or not seed:
        raise ValueError("the seed must be an explicit non-empty string")
    if isinstance(resamples, bool) or not isinstance(resamples, int) or resamples < 1:
        raise ValueError("resamples must be a positive int")
    if not (0.0 < level < 1.0):
        raise ValueError("level must lie strictly between 0 and 1")
    if len(units) != denominator:
        raise ValueError(
            f"{len(units)} units for a denominator of {denominator}: a refused unit stays in "
            "as None, it is never dropped"
        )
    if not units:
        raise ValueError("no units")
    if len({unit.unit_id for unit in units}) != len(units):
        raise ValueError("duplicate unit_id")
    if direction == "lower" and any(u.tavonel is None or u.vendor is None for u in units):
        raise ValueError(
            "a refused unit on a lower-is-better metric has no score: the evaluator scores the "
            "empty prediction (§4.4); zero would reward the refusal"
        )

    grouped: dict[str, list[PairedUnit[T]]] = {}
    for unit in sorted(units, key=lambda u: (u.cluster_id, u.unit_id)):
        grouped.setdefault(unit.cluster_id, []).append(unit)
    clusters = [grouped[key] for key in sorted(grouped)]

    def statistic(sample: Sequence[PairedUnit[T]]) -> float:
        tavonel = aggregate([u.tavonel for u in sample])
        vendor = aggregate([u.vendor for u in sample])
        value = float(tavonel - vendor if direction == "higher" else vendor - tavonel)
        if not math.isfinite(value):
            raise ValueError("the aggregate produced a value that is not a finite number")
        return value

    point = statistic([unit for cluster in clusters for unit in cluster])
    # ponytail: pure-Python resampling, ~1 ms per draw at N = 2,078; vectorise if it ever matters.
    rng = random.Random(seed)  # noqa: S311 - statistical resampling with a published seed
    draws = sorted(
        statistic([u for cluster in rng.choices(clusters, k=len(clusters)) for u in cluster])
        for _ in range(resamples)
    )
    tail = (1.0 - level) / 2.0
    return PairedDifference(
        point=point,
        lower=_percentile(draws, tail),
        upper=_percentile(draws, 1.0 - tail),
        direction=direction,
        units=len(units),
        clusters=len(clusters),
        resamples=resamples,
        level=level,
        seed=seed,
    )


# --------------------------------------------------------------------------- A axis (GDP)


@dataclass(frozen=True)
class AnswerTask:
    """One task, one entry per epoch per arm: True = all_pass, False = not, None = failed epoch."""

    task_id: str
    pdf_sha256: str
    tavonel: tuple[bool | None, ...]
    vendor: tuple[bool | None, ...]


@dataclass(frozen=True)
class AnswerAxisDifference:
    difference: PairedDifference  # percentage points of macro all-pass
    tavonel_only: int
    vendor_only: int
    mcnemar_p: float


def answer_axis_difference(
    tasks: Sequence[AnswerTask],
    *,
    denominator: int,
    seed: str,
    resamples: int,
    level: float,
) -> AnswerAxisDifference:
    """A-T against A-V-x per prereg ``a_axis_verdict.epoch_aggregation_ko``.

    Task score = mean of its epochs' all_pass (a failed epoch is 0); point = macro mean over
    tasks, in percentage points, computed exactly; CI = ``pdf_sha256`` cluster bootstrap. The
    McNemar input is each task's majority over epochs (3 of 5): more than half passed.
    """
    if not tasks:
        raise ValueError("no tasks")
    epochs = len(tasks[0].tavonel)
    if epochs < 1:
        raise ValueError("a task has no epochs")
    for task in tasks:
        if len(task.tavonel) != epochs or len(task.vendor) != epochs:
            raise ValueError(
                f"task {task.task_id!r} does not have {epochs} epochs in both arms: a failed "
                "epoch is recorded as None, never dropped"
            )

    def passes(record: tuple[bool | None, ...]) -> int:
        return sum(1 for epoch in record if epoch is True)

    def macro_pp(counts: Sequence[int | None]) -> Fraction:
        return Fraction(100 * sum(c or 0 for c in counts), len(counts) * epochs)

    difference = paired_cluster_bootstrap(
        [PairedUnit(t.task_id, t.pdf_sha256, passes(t.tavonel), passes(t.vendor)) for t in tasks],
        aggregate=macro_pp,
        direction="higher",
        denominator=denominator,
        seed=seed,
        resamples=resamples,
        level=level,
    )
    tavonel_major = [2 * passes(t.tavonel) > epochs for t in tasks]
    vendor_major = [2 * passes(t.vendor) > epochs for t in tasks]
    tavonel_only = sum(1 for a, b in zip(tavonel_major, vendor_major, strict=True) if a and not b)
    vendor_only = sum(1 for a, b in zip(tavonel_major, vendor_major, strict=True) if b and not a)
    return AnswerAxisDifference(
        difference, tavonel_only, vendor_only, exact_mcnemar_p(tavonel_only, vendor_only)
    )


# --------------------------------------------------------------------------- verdicts


def _check_interval(ci: Interval) -> Interval:
    lower, upper = ci
    if not (math.isfinite(lower) and math.isfinite(upper)):
        raise ValueError("the confidence interval has a bound that is not a finite number")
    if lower > upper:
        raise ValueError("the confidence interval's lower bound is above its upper bound")
    return lower, upper


def _check_positive(value: float, name: str) -> None:
    if not (math.isfinite(value) and value > 0):
        raise ValueError(f"{name} must be a positive finite number")


def document_axis_verdict(ci: Interval | None, delta: float) -> Verdict:
    """D-T-* against D-V-*. ``ci`` is None when the evaluator aggregate does not decompose."""
    _check_positive(delta, "delta")
    if ci is None:
        return "INCONCLUSIVE"
    lower, upper = _check_interval(ci)
    if upper < 0:
        return "BEHIND"
    if lower > delta:
        return "AHEAD"
    if lower >= -delta and upper <= delta:
        return "WITHIN"
    return "INCONCLUSIVE"


def answer_axis_verdict(
    point: float, ci: Interval, mcnemar_p: float, *, margin_pp: float, alpha: float
) -> Verdict:
    """A-T against A-V-*: AHEAD needs the margin, an interval above zero and McNemar p < alpha."""
    _check_positive(margin_pp, "margin_pp")
    if not (0 < alpha < 1):
        raise ValueError("alpha must lie strictly between 0 and 1")
    if not math.isfinite(point):
        raise ValueError("the point difference is not a finite number")
    if not (0 <= mcnemar_p <= 1):
        raise ValueError("mcnemar_p is not a probability")
    lower, upper = _check_interval(ci)
    if upper < 0:
        return "BEHIND"
    if point >= margin_pp and lower > 0 and mcnemar_p < alpha:
        return "AHEAD"
    if lower >= -margin_pp and upper <= margin_pp:
        return "WITHIN"
    return "INCONCLUSIVE"
