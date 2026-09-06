#!/usr/bin/env python3
"""Hidden post-run evaluation and prospectively declared statistics for TAVONEL-R."""

from __future__ import annotations

import hashlib
import json
import math
import random
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from confirmatory_execution import ArmOutput
from recovery_protocol import Arm, ProtocolRefused

BOOTSTRAP_REPLICATES = 10_000
BOOTSTRAP_SEED = "TAVONEL-R-CLUSTER-BOOTSTRAP-2026-08-30"
PERMUTATION_REPLICATES = 10_000
PERMUTATION_SEED = "TAVONEL-R-PAIRED-PERMUTATION-2026-08-30"


class EvaluationRefused(ProtocolRefused):
    pass


def _normalize(text: str) -> str:
    return " ".join(text.casefold().split())


def _contains_exact_anchor(text: str, expected: str) -> bool:
    haystack = _normalize(text)
    needle = _normalize(expected)
    if not needle:
        raise EvaluationRefused("evaluation anchor expected value cannot be empty")
    if needle not in haystack:
        return False
    # For word-like values, avoid crediting substring matches inside larger words.
    if re.fullmatch(r"[\w.-]+", needle):
        return bool(re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", haystack))
    return True


@dataclass(frozen=True, slots=True)
class EvaluationAnchor:
    anchor_id: str
    expected_text: str
    critical: bool = True


@dataclass(frozen=True, slots=True)
class HiddenPageTruth:
    page_id: str
    document_family: str
    anchors: tuple[EvaluationAnchor, ...]

    def validate(self) -> None:
        if not self.page_id or not self.document_family:
            raise EvaluationRefused("hidden truth requires page and document-family identity")
        if not self.anchors:
            raise EvaluationRefused("hidden truth requires at least one evaluation anchor")
        ids = [anchor.anchor_id for anchor in self.anchors]
        if len(ids) != len(set(ids)):
            raise EvaluationRefused("evaluation anchor IDs must be unique within a page")
        if any(not anchor.anchor_id or not anchor.expected_text for anchor in self.anchors):
            raise EvaluationRefused("evaluation anchors require stable id and expected text")


@dataclass(frozen=True, slots=True)
class PageEvaluation:
    arm: Arm
    page_id: str
    document_family: str
    accepted: bool
    unresolved: bool
    critical_exact: int
    critical_total: int
    accepted_silent_critical_error: bool
    recovered: bool
    escalated: bool
    strong_invocations: int
    gpu_seconds: float
    external_cost_usd: float

    @property
    def exact_fraction(self) -> float:
        return self.critical_exact / self.critical_total if self.critical_total else 0.0

    @property
    def all_critical_correct(self) -> bool:
        return self.critical_exact == self.critical_total


def evaluate_output(output: ArmOutput, truth: HiddenPageTruth) -> PageEvaluation:
    truth.validate()
    if output.page_id != truth.page_id:
        raise EvaluationRefused("runtime output and hidden truth page IDs differ")
    critical = tuple(anchor for anchor in truth.anchors if anchor.critical)
    if not critical:
        raise EvaluationRefused("primary evaluation requires at least one critical anchor")
    exact = 0
    if output.accepted and output.accepted_text is not None:
        exact = sum(
            _contains_exact_anchor(output.accepted_text, anchor.expected_text)
            for anchor in critical
        )
    silent_error = output.accepted and exact < len(critical)
    return PageEvaluation(
        arm=output.arm,
        page_id=output.page_id,
        document_family=truth.document_family,
        accepted=output.accepted,
        unresolved=output.unresolved,
        critical_exact=exact,
        critical_total=len(critical),
        accepted_silent_critical_error=silent_error,
        recovered=output.accepted and output.escalated_to_strong,
        escalated=output.escalated_to_strong,
        strong_invocations=output.strong_invocations,
        gpu_seconds=output.gpu_seconds,
        external_cost_usd=output.external_cost_usd,
    )


def summarize_arm(rows: Sequence[PageEvaluation]) -> dict[str, Any]:
    if not rows:
        raise EvaluationRefused("arm summary requires observations")
    arms = {row.arm for row in rows}
    if len(arms) != 1:
        raise EvaluationRefused("arm summary cannot mix arms")
    accepted = sum(row.accepted for row in rows)
    unresolved = sum(row.unresolved for row in rows)
    silent = sum(row.accepted_silent_critical_error for row in rows)
    exact = sum(row.critical_exact for row in rows)
    total = sum(row.critical_total for row in rows)
    escalated = sum(row.escalated for row in rows)
    recovered = sum(row.recovered for row in rows)
    strong = sum(row.strong_invocations for row in rows)
    n = len(rows)
    return {
        "arm": next(iter(arms)).value,
        "pages": n,
        "accepted_pages": accepted,
        "accepted_silent_critical_errors": silent,
        "accepted_silent_critical_error_rate": silent / accepted if accepted else 0.0,
        "critical_semantic_exactness": exact / total if total else 0.0,
        "unresolved_rate": unresolved / n,
        "recovery_success_given_escalation": recovered / escalated if escalated else 0.0,
        "strong_model_invocation_fraction": strong / n,
        "gpu_seconds_per_1000_pages": sum(row.gpu_seconds for row in rows) / n * 1000,
        "external_cost_usd_per_1000_pages": (sum(row.external_cost_usd for row in rows) / n * 1000),
    }


def mcnemar_exact(
    left: Sequence[PageEvaluation], right: Sequence[PageEvaluation]
) -> dict[str, Any]:
    by_left = {row.page_id: row for row in left}
    by_right = {row.page_id: row for row in right}
    if set(by_left) != set(by_right):
        raise EvaluationRefused("paired McNemar comparison requires identical page identities")
    b = c = 0
    for page_id in sorted(by_left):
        l_ok = by_left[page_id].all_critical_correct and by_left[page_id].accepted
        r_ok = by_right[page_id].all_critical_correct and by_right[page_id].accepted
        if l_ok and not r_ok:
            b += 1
        elif r_ok and not l_ok:
            c += 1
    n = b + c
    if n == 0:
        p_value = 1.0
    else:
        tail = sum(math.comb(n, k) for k in range(0, min(b, c) + 1)) / (2**n)
        p_value = min(1.0, 2.0 * tail)
    return {
        "left_only_correct": b,
        "right_only_correct": c,
        "discordant_pairs": n,
        "exact_two_sided_p": p_value,
        "effect_difference_in_page_correctness": (
            sum(row.accepted and row.all_critical_correct for row in right) / len(right)
            - sum(row.accepted and row.all_critical_correct for row in left) / len(left)
        ),
    }


def _seed(text: str) -> int:
    return int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "big")


def cluster_bootstrap_ci(
    rows: Sequence[PageEvaluation], metric: str, replicates: int = BOOTSTRAP_REPLICATES
) -> dict[str, float]:
    if replicates < 100:
        raise EvaluationRefused("cluster bootstrap requires at least 100 replicates")
    clusters: dict[str, list[PageEvaluation]] = defaultdict(list)
    for row in rows:
        clusters[row.document_family].append(row)
    names = sorted(clusters)
    if not names:
        raise EvaluationRefused("cluster bootstrap requires document families")

    def measure(sample: Sequence[PageEvaluation]) -> float:
        summary = summarize_arm(sample)
        if metric not in summary or not isinstance(summary[metric], (int, float)):
            raise EvaluationRefused(f"unsupported bootstrap metric: {metric}")
        return float(summary[metric])

    # Deterministic scientific resampling, not a cryptographic/security use.
    rng = random.Random(_seed(f"{BOOTSTRAP_SEED}|{metric}"))  # noqa: S311
    values: list[float] = []
    for _ in range(replicates):
        sampled_names = [rng.choice(names) for _ in names]
        sample: list[PageEvaluation] = []
        for name in sampled_names:
            sample.extend(clusters[name])
        values.append(measure(sample))
    values.sort()
    low = values[int(0.025 * (replicates - 1))]
    high = values[int(0.975 * (replicates - 1))]
    return {"estimate": measure(rows), "ci95_low": low, "ci95_high": high}


def paired_permutation_cost(
    left: Sequence[PageEvaluation],
    right: Sequence[PageEvaluation],
    *,
    field: str,
    replicates: int = PERMUTATION_REPLICATES,
) -> dict[str, float]:
    by_left = {row.page_id: row for row in left}
    by_right = {row.page_id: row for row in right}
    if set(by_left) != set(by_right):
        raise EvaluationRefused("paired cost permutation requires identical page identities")
    if field not in {"gpu_seconds", "external_cost_usd"}:
        raise EvaluationRefused("paired cost field must be gpu_seconds or external_cost_usd")
    diffs = [
        float(getattr(by_right[page], field) - getattr(by_left[page], field))
        for page in sorted(by_left)
    ]
    observed = sum(diffs) / len(diffs) if diffs else 0.0
    # Deterministic scientific randomisation, not a cryptographic/security use.
    rng = random.Random(_seed(f"{PERMUTATION_SEED}|{field}"))  # noqa: S311
    exceed = 0
    for _ in range(replicates):
        permuted = sum(diff if rng.getrandbits(1) else -diff for diff in diffs) / len(diffs)
        if abs(permuted) >= abs(observed):
            exceed += 1
    return {
        "paired_mean_difference": observed,
        "two_sided_permutation_p": (exceed + 1) / (replicates + 1),
    }


def holm_adjust(p_values: Mapping[str, float]) -> dict[str, float]:
    if any(not 0.0 <= value <= 1.0 for value in p_values.values()):
        raise EvaluationRefused("Holm inputs must be p-values within 0..1")
    ordered = sorted(p_values.items(), key=lambda item: (item[1], item[0]))
    m = len(ordered)
    adjusted: dict[str, float] = {}
    running = 0.0
    for index, (name, value) in enumerate(ordered):
        candidate = min(1.0, (m - index) * value)
        running = max(running, candidate)
        adjusted[name] = running
    return adjusted


def build_primary_analysis(rows: Sequence[PageEvaluation]) -> dict[str, Any]:
    by_arm: dict[Arm, list[PageEvaluation]] = defaultdict(list)
    for row in rows:
        by_arm[row.arm].append(row)
    required = {
        Arm.PRIMARY_ONLY,
        Arm.ALWAYS_STRONG,
        Arm.PREDICTION_ONLY,
        Arm.DISAGREEMENT_ONLY,
        Arm.TAVONEL_EVIDENCE_RECOVERY,
    }
    if set(by_arm) != required:
        raise EvaluationRefused(
            f"primary analysis requires exactly five arms, got {sorted(a.value for a in by_arm)}"
        )
    identity_sets = {arm: {row.page_id for row in values} for arm, values in by_arm.items()}
    if len({frozenset(value) for value in identity_sets.values()}) != 1:
        raise EvaluationRefused("all primary arms must cover the same page identities")

    summaries = {
        arm.value: summarize_arm(by_arm[arm]) for arm in sorted(required, key=lambda a: a.value)
    }
    tavonel = by_arm[Arm.TAVONEL_EVIDENCE_RECOVERY]
    comparisons: dict[str, Any] = {}
    raw_ps: dict[str, float] = {}
    for baseline in (
        Arm.PRIMARY_ONLY,
        Arm.ALWAYS_STRONG,
        Arm.PREDICTION_ONLY,
        Arm.DISAGREEMENT_ONLY,
    ):
        name = f"{Arm.TAVONEL_EVIDENCE_RECOVERY.value}_vs_{baseline.value}"
        mcnemar = mcnemar_exact(by_arm[baseline], tavonel)
        cost_gpu = paired_permutation_cost(by_arm[baseline], tavonel, field="gpu_seconds")
        cost_usd = paired_permutation_cost(by_arm[baseline], tavonel, field="external_cost_usd")
        comparisons[name] = {
            "mcnemar": mcnemar,
            "gpu_cost": cost_gpu,
            "external_cost": cost_usd,
        }
        raw_ps[name] = float(mcnemar["exact_two_sided_p"])
    adjusted = holm_adjust(raw_ps)
    for name, value in adjusted.items():
        comparisons[name]["holm_adjusted_correctness_p"] = value

    intervals = {
        metric: cluster_bootstrap_ci(tavonel, metric)
        for metric in (
            "accepted_silent_critical_error_rate",
            "critical_semantic_exactness",
            "unresolved_rate",
            "strong_model_invocation_fraction",
            "gpu_seconds_per_1000_pages",
            "external_cost_usd_per_1000_pages",
        )
    }
    body = {
        "schema": "tavonel.recovery.primary_analysis.v1",
        "unit": "page_with_document_family_cluster",
        "summaries": summaries,
        "tavonel_cluster_bootstrap_95": intervals,
        "paired_comparisons": comparisons,
        "multiple_comparison_method": "Holm correction over four paired correctness contrasts",
        "effect_size_reported_before_p_value": True,
        "oracle_in_primary_analysis": False,
        "bootstrap_replicates": BOOTSTRAP_REPLICATES,
        "permutation_replicates": PERMUTATION_REPLICATES,
    }
    raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {**body, "analysis_digest": "sha256:" + hashlib.sha256(raw).hexdigest()}


__all__ = [
    "BOOTSTRAP_REPLICATES",
    "EvaluationAnchor",
    "EvaluationRefused",
    "HiddenPageTruth",
    "PageEvaluation",
    "build_primary_analysis",
    "cluster_bootstrap_ci",
    "evaluate_output",
    "holm_adjust",
    "mcnemar_exact",
    "paired_permutation_cost",
    "summarize_arm",
]
