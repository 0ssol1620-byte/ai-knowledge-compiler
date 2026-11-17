"""Retrieval arena (WO-D17-4): pre-registration, filing-cluster paired bootstrap, decision rule.

The rule (D17-D2, D17-D3; critique B1, should-fix 1, 4, 5):
- hard gates first: any blocking finding stops the line and nothing is ranked;
- an arm with ``not_run`` > 0 is unranked; A0 (claims only), ``no_cut_bm25_rows`` and the
  ``label_blind`` floor are reported outside the rule;
- a family separates retrievers only if some ranked arm's 95% lower bound of
  delta recall@k against ``label_blind`` is above 0; otherwise nothing is ranked;
- otherwise exactly one of three outcomes, against the incumbent ``bm25_rows``:
  ``simplest_wins`` / ``candidate_adr_shadow`` / ``no_change`` (see DECISION_RULE).
Latency and CPU seconds are reported, never gated. Nothing here is an accuracy.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

A0 = "a0_claims_only"
LABEL_BLIND = "label_blind"
INCUMBENT = "bm25_rows"  # D17-D2: the incumbent is bm25_rows, not A0
SIMPLER_THAN_INCUMBENT = frozenset({"exact_token"})
RANKABLE = frozenset({"exact_token", "bm25_rows", "hybrid_current", "graph_entity", "dense"})
OUTSIDE_RULE = {
    A0: "claims only; its gold is unreachable wherever the gold row has no claim (B1)",
    "no_cut_bm25_rows": "the cut is not applied; it measures the cut's value, not a retriever",
    LABEL_BLIND: "the floor every family is checked against (D17-D3)",
}
PREREG_SCHEMA = "tavonel.retrieval-arena.prereg/v1"
PREREG_KEYS = frozenset(
    {"schema", "incumbent", "arms", "margin", "stratum_floor", "seed", "resamples"}
)
PREREG_MAX_BYTES = 65_536
RESAMPLES_RANGE = (1_000, 100_000)
CONFIDENCE_TAIL_PER_MILLE = 25  # 95% two-sided percentile interval
HOLDOUT_RECEIPT_SUFFIX = ".holdout-receipt.json"
NO_PREREG = "no --prereg: a ranked report needs a pre-registration"
EXACTNESS_NOT_MEASURED = (
    "not measured: exactness here equals precision@1 (top-1 is the gold row), so it is not an "
    "independent measurement; never pass/fail against U09"
)
ABSTENTION_NOT_MEASURED = (
    "not measured: no arm has a score threshold, so abstention is decided by construction; "
    "never pass/fail against U09"
)
LATENCY_NOTE = (
    "reported, never gated: pure-Python arms on a shared PC measure contention; the gate "
    "belongs to shadow on the real store"
)
HOLDOUT_BINDING = "holdout: the single blind run; the outcome is the recorded result"
DEV_NOT_BINDING = "dev: the outcome is not a decision; it binds only on the single holdout run"
DECISION_RULE = (
    "delta = arm recall@k minus incumbent recall@k per answerable task, paired; 95% percentile "
    "interval from a filing-cluster (adsh) bootstrap seeded by the pre-registration. "
    "A candidate beats the incumbent when its lower bound > 0 and no stratum's delta is below "
    "-stratum_floor. simplest_wins when every more complex pre-registered arm was ranked and "
    "the incumbent's lower bound against each (= -upper bound of the candidate's delta) is "
    ">= -margin, and no simpler arm beats it; it is checked first (minimum cost to trusted "
    "output). Else candidate_adr_shadow when some arm beats the incumbent (ADR, then shadow; "
    "nothing is activated here). Else no_change."
)
OUTCOMES = ("no_change", "simplest_wins", "candidate_adr_shadow")
_SHA256 = re.compile(r"[0-9a-f]{64}")


class ArenaError(ValueError):
    """A pre-registration, index or report that the arena cannot rank honestly."""


def latency_percentiles(values: Sequence[float]) -> dict[str, Any]:
    """Nearest-rank p50/p95/p99 of per-task retrieval seconds; reported, never gated."""
    ordered = sorted(values)
    n = len(ordered)

    def rank(p: int) -> float | None:
        return ordered[-(-p * n // 100) - 1] if n else None

    return {"tasks": n, "p50": rank(50), "p95": rank(95), "p99": rank(99), "note": LATENCY_NOTE}


def _refuse_constant(name: str) -> None:
    raise ArenaError(f"pre-registration holds {name}; only finite numbers are allowed")


def _number(prereg: Mapping[str, Any], key: str, low: float, high: float) -> float:
    value = prereg[key]
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ArenaError(f"pre-registration {key} must be a number")
    if not (math.isfinite(value) and low <= value < high):
        raise ArenaError(f"pre-registration {key} must be in [{low}, {high})")
    return float(value)


def load_prereg(raw: bytes, expected_sha256: str) -> dict[str, Any]:
    """Verify the hash given on the command line, then the content; refuse anything else."""
    expected = expected_sha256.strip().lower()
    if not _SHA256.fullmatch(expected):
        raise ArenaError("--prereg-sha256 must be 64 hexadecimal characters")
    if len(raw) > PREREG_MAX_BYTES:
        raise ArenaError(f"pre-registration exceeds {PREREG_MAX_BYTES} bytes")
    digest = hashlib.sha256(raw).hexdigest()
    if digest != expected:
        raise ArenaError(
            f"pre-registration sha256 mismatch: the file is {digest}, the command line says "
            f"{expected}"
        )
    try:
        data = json.loads(raw.decode("utf-8"), parse_constant=_refuse_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ArenaError(f"pre-registration is not UTF-8 JSON: {type(exc).__name__}") from exc
    if not isinstance(data, dict) or set(data) != PREREG_KEYS:
        found = sorted(data) if isinstance(data, dict) else type(data).__name__
        raise ArenaError(f"pre-registration keys must be exactly {sorted(PREREG_KEYS)}: {found}")
    if data["schema"] != PREREG_SCHEMA:
        raise ArenaError(f"pre-registration schema must be {PREREG_SCHEMA!r}")
    if data["incumbent"] != INCUMBENT:
        raise ArenaError(f"pre-registration incumbent must be {INCUMBENT!r} (D17-D2)")
    arms = data["arms"]
    if (
        not isinstance(arms, list)
        or not all(isinstance(a, str) for a in arms)
        or len(set(arms)) != len(arms)
    ):
        raise ArenaError("pre-registration arms must be a list of distinct names")
    unknown = sorted(set(arms) - RANKABLE)
    if unknown:
        raise ArenaError(
            f"pre-registration arms {unknown} cannot be ranked (rankable: {sorted(RANKABLE)})"
        )
    if INCUMBENT not in arms or len(arms) < 2:
        raise ArenaError("pre-registration arms must hold the incumbent and at least one other arm")
    _number(data, "margin", 1e-9, 1.0)
    _number(data, "stratum_floor", 0.0, 1.0)
    for key, (low, high) in (("seed", (0, 2**63)), ("resamples", RESAMPLES_RANGE)):
        value = data[key]
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise ArenaError(f"pre-registration {key} must be an integer in [{low}, {high}]")
    return data


def load_rows_index(lines: Sequence[str]) -> dict[str, tuple[str, str]]:
    """rows_index.jsonl -> logical_id -> (cik, adsh). Refuses by ordinal, never echoes text."""
    out: dict[str, tuple[str, str]] = {}
    for ordinal, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            row = json.loads(line, parse_constant=_refuse_constant)
        except json.JSONDecodeError as exc:
            raise ArenaError(f"rows index line {ordinal} is not JSON") from exc
        key = row.get("fsds_key") if isinstance(row, dict) else None
        values = (
            [row.get("logical_id"), key.get("cik"), row.get("adsh")]
            if isinstance(row, dict) and isinstance(key, dict)
            else []
        )
        if len(values) != 3 or not all(isinstance(v, str) and v.strip() for v in values):
            raise ArenaError(
                f"rows index line {ordinal}: logical_id, fsds_key.cik and adsh must be "
                "non-empty strings"
            )
        lid, cik, adsh = (str(v) for v in values)
        if lid in out:
            raise ArenaError(f"rows index line {ordinal}: logical id appears twice")
        out[lid] = (cik, adsh)
    return out


def task_clusters(
    gold_rows: Mapping[str, Sequence[str]], filing_of: Mapping[str, tuple[str, str]]
) -> dict[str, tuple[str, str]]:
    """Answerable task -> (cik, adsh) of its gold filing; exactly one filing, or refused."""
    out: dict[str, tuple[str, str]] = {}
    for task_id, rows in sorted(gold_rows.items()):
        if not rows:
            raise ArenaError(f"task {task_id!r}: no gold row in the corpus")
        missing = [lid for lid in rows if lid not in filing_of]
        if missing:
            raise ArenaError(f"task {task_id!r}: {len(missing)} gold row(s) not in the rows index")
        filings = {filing_of[lid] for lid in rows}
        if len(filings) != 1:
            raise ArenaError(f"task {task_id!r}: gold rows span {len(filings)} filings")
        (out[task_id],) = filings
    return out


class _Lcg:
    """Seeded 64-bit LCG (Knuth MMIX constants); `random` is barred by lint in this tree."""

    def __init__(self, seed: int) -> None:
        self.state = seed

    def below(self, n: int) -> int:
        self.state = (self.state * 6364136223846793005 + 1442695040888963407) % 2**64
        # ponytail: modulo bias below 2**-31 * n; rejection sampling if clusters reach millions
        return (self.state >> 33) % n


def paired_cluster_bootstrap(
    deltas: Mapping[str, float], cluster_of: Mapping[str, str], *, seed: int, resamples: int
) -> tuple[float, float, float]:
    """(point, lower, upper): task-weighted mean delta, clusters drawn with replacement.

    Each resample draws len(clusters) clusters; its statistic is the sum of the drawn clusters'
    deltas over the sum of their task counts. The interval is the percentile interval with
    tail = resamples * 25 // 1000 resamples cut from each side.
    """
    if not deltas:
        raise ArenaError("no paired task to resample")
    sums: dict[str, float] = defaultdict(float)
    sizes: dict[str, int] = defaultdict(int)
    for task_id, delta in sorted(deltas.items()):
        sums[cluster_of[task_id]] += delta
        sizes[cluster_of[task_id]] += 1
    keys = sorted(sums)
    sum_list = [sums[k] for k in keys]
    size_list = [sizes[k] for k in keys]
    n = len(keys)
    rng = _Lcg(seed)
    stats: list[float] = []
    for _ in range(resamples):
        total = count = 0.0
        for _ in range(n):
            j = rng.below(n)
            total += sum_list[j]
            count += size_list[j]
        stats.append(total / count)
    stats.sort()
    tail = resamples * CONFIDENCE_TAIL_PER_MILLE // 1000
    return math.fsum(sum_list) / sum(size_list), stats[tail], stats[resamples - 1 - tail]


def _mean(values: Sequence[float]) -> float:
    return math.fsum(values) / len(values)


def _cost(entry: Mapping[str, Any]) -> dict[str, Any]:
    tasks = entry["tasks"]
    return {
        "wall_seconds_per_task": entry["wall_seconds"] / tasks,
        "cpu_seconds_per_task": entry["cpu_seconds"] / tasks,
        "usd_per_task": "not applicable: a local arm with no spend",
    }


def _unranked_reason(entry: Mapping[str, Any] | None) -> str | None:
    if entry is None:
        return "not in the report"
    if entry["status"] != "ran":
        return f"not run: {entry['reason']}"
    if entry["not_run_tasks"]:
        return f"not_run_tasks = {entry['not_run_tasks']} ({entry['not_run_reason']})"
    return None


def decide(
    report: Mapping[str, Any],
    prereg: Mapping[str, Any],
    clusters: Mapping[str, tuple[str, str]],
    strata: Mapping[str, str | None],
) -> dict[str, Any]:
    """The ranked arena section of a report (see the module docstring)."""
    entries: Mapping[str, Mapping[str, Any]] = report["retrievers"]
    out: dict[str, Any] = {
        "ranked": False,
        "outcome": None,
        "not_ranked_reason": None,
        "incumbent": INCUMBENT,
        "floor_arm": LABEL_BLIND,
        "decision_rule": DECISION_RULE,
        "pre_registered_arms": list(prereg["arms"]),
        "margin": prereg["margin"],
        "stratum_floor": prereg["stratum_floor"],
        "bootstrap": {
            "unit": "filing (adsh) cluster, paired by task",
            "seed": prereg["seed"],
            "resamples": prereg["resamples"],
            "interval": "95% percentile",
        },
        "outside_rule": {
            name: {"reason": reason, **_outside(entries.get(name))}
            for name, reason in OUTSIDE_RULE.items()
        },
    }
    if report["blocking"]:
        out["not_ranked_reason"] = "hard gate: " + "; ".join(report["blocking"])
        return out
    unranked = {
        a: why for a in [*prereg["arms"], LABEL_BLIND] if (why := _unranked_reason(entries.get(a)))
    }
    out["unranked"] = unranked
    if INCUMBENT in unranked:
        out["not_ranked_reason"] = f"the incumbent {INCUMBENT} is unranked: {unranked[INCUMBENT]}"
        return out
    if LABEL_BLIND in unranked:
        out["not_ranked_reason"] = (
            f"separation untestable: {LABEL_BLIND} is unranked: {unranked[LABEL_BLIND]}"
        )
        return out
    ranked = [a for a in prereg["arms"] if a not in unranked]
    recall = {a: entries[a]["per_task_recall_at_k"] for a in [*ranked, LABEL_BLIND]}
    task_ids = set(recall[INCUMBENT])
    for arm, per_task in recall.items():
        if set(per_task) != task_ids:
            raise ArenaError(f"{arm} and {INCUMBENT} did not score the same answerable tasks")
    if not task_ids:
        out["not_ranked_reason"] = "no answerable task"
        return out
    missing = sorted(task_ids - set(clusters))
    if missing:
        raise ArenaError(f"{len(missing)} answerable task(s) have no filing cluster")
    adsh = {t: clusters[t][1] for t in task_ids}

    def macro(arm: str) -> float:
        by_cik: dict[str, list[float]] = defaultdict(list)
        for t in task_ids:
            by_cik[clusters[t][0]].append(recall[arm][t])
        return _mean([_mean(v) for _, v in sorted(by_cik.items())])

    def compare(arm: str, base: str) -> dict[str, Any]:
        deltas = {t: recall[arm][t] - recall[base][t] for t in task_ids}
        point, low, high = paired_cluster_bootstrap(
            deltas, adsh, seed=prereg["seed"], resamples=prereg["resamples"]
        )
        by_stratum: dict[str, list[float]] = defaultdict(list)
        for t, d in deltas.items():
            by_stratum[strata[t] or "(no stratum)"].append(d)
        stratum_delta = {s: _mean(v) for s, v in sorted(by_stratum.items())}
        worst = min(stratum_delta, key=lambda s: (stratum_delta[s], s))
        return {
            "delta_recall_at_k": point,
            "ci95": [low, high],
            "tasks": len(deltas),
            "clusters": len(set(adsh.values())),
            "companies": len({clusters[t][0] for t in task_ids}),
            "delta_per_company_macro": macro(arm) - macro(base),
            "delta_by_stratum": stratum_delta,
            "worst_stratum": {"stratum": worst, "delta": stratum_delta[worst]},
        }

    out["recall_at_k_mean"] = {a: _mean(list(recall[a].values())) for a in recall}
    out["recall_at_k_per_company_macro"] = {a: macro(a) for a in recall}
    separation = {a: compare(a, LABEL_BLIND) for a in ranked}
    out["separation"] = {
        "separates": any(s["ci95"][0] > 0 for s in separation.values()),
        "against_label_blind": separation,
    }
    if not out["separation"]["separates"]:
        out["not_ranked_reason"] = (
            f"the family does not separate retrievers: no arm's 95% lower bound beats "
            f"{LABEL_BLIND} (D17-D3); nothing is ranked"
        )
        return out
    comparisons: dict[str, dict[str, Any]] = {}
    for arm in ranked:
        if arm == INCUMBENT:
            continue
        c = compare(arm, INCUMBENT)
        c["beats_incumbent"] = (
            c["ci95"][0] > 0 and c["worst_stratum"]["delta"] >= -prereg["stratum_floor"]
        )
        c["incumbent_lower_bound"] = -c["ci95"][1]
        c["incumbent_non_inferior"] = -c["ci95"][1] >= -prereg["margin"]
        c["cost_per_task"] = _cost(entries[arm])
        comparisons[arm] = c
    complex_arms = [a for a in prereg["arms"] if a != INCUMBENT and a not in SIMPLER_THAN_INCUMBENT]
    winners = sorted(a for a, c in comparisons.items() if c["beats_incumbent"])
    simplest = (
        bool(complex_arms)
        and all(a in comparisons and comparisons[a]["incumbent_non_inferior"] for a in complex_arms)
        and not any(a in SIMPLER_THAN_INCUMBENT for a in winners)
    )
    out.update(
        ranked=True,
        comparisons=comparisons,
        incumbent_cost_per_task=_cost(entries[INCUMBENT]),
        winners=winners,
        ranking=sorted(ranked, key=lambda a: (-out["recall_at_k_mean"][a], a)),
    )
    if simplest:
        out["outcome"] = "simplest_wins"
    elif winners:
        out["outcome"] = "candidate_adr_shadow"
    else:
        out["outcome"] = "no_change"
    return out


def _outside(entry: Mapping[str, Any] | None) -> dict[str, Any]:
    """What the report shows for an arm outside the rule, labelled; never a ranked figure."""
    if entry is None or entry["status"] != "ran":
        return {"status": "absent" if entry is None else "not_run"}
    keep = ("tasks", "not_run_tasks", "recall_at_k", "reachable_answerable_tasks")
    return {"status": "ran", **{k: entry[k] for k in keep if k in entry}}
