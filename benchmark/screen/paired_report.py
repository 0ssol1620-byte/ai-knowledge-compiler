"""Paired per-stratum report and the frozen selection rule (WO-D08-5).

Input: WO-D08-1 screen records. Selection rule, frozen before A2b:
  1. Any accepted critical error in a stratum disqualifies that candidate there.
  2. At most MAX_ALTERNATIVES alternatives per stratum.
  3. A candidate that is primary in exactly one stratum is routed only there
     (minority isolated). No voting, no ensemble: one primary per stratum.
  4. The worst stratum is reported beside the macro figure, never averaged away.
There is one critical exact rate, computed only by _exact and used by the cell,
its Wilson CI, eligibility, selection and the rule-4 summary alike. Its unit is
the page: n counts every hard-failed page (whatever critical n it recorded) plus
every accepted page with critical fields. An accepted page scores its exact
field fraction, a failed page 0; critical_exact is the sum of those scores and
the rate is their mean. The Wilson CI over (critical_exact, n) is conservative
for a mean of [0, 1] scores, whose variance is at most p(1 - p). Failing or
adding a failed page therefore never raises the rate or either Wilson bound, and
a stratum whose pages all failed reports 0.0 over its page count, never
"insufficient". Ties break on failure fraction before CER and cost, so failures
never move a candidate up. A malformed or duplicated record is a ValueError.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

from akc_absorption.metrics import bootstrap_ci, mcnemar_exact

from benchmark.w6.v2.grading import wilson_interval

MAX_ALTERNATIVES = 2
INSUFFICIENT = "insufficient"
_METRICS = ("cer", "table_f1", "formula_score")


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(q * len(ordered)) - 1)]


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _metric(records: list[dict[str, Any]], key: str) -> float | None:
    return _mean([r["metrics"][key] for r in records if key in r["metrics"]])


def _doc_critical_exact(records: list[dict[str, Any]]) -> bool:
    n = sum(r["critical"]["n"] for r in records)
    return (
        n > 0
        and not any(r["hard_failures"] for r in records)
        and all(r["critical"]["exact"] == r["critical"]["n"] for r in records)
    )


def _exact(records: list[dict[str, Any]]) -> tuple[float, int, float | str, list[float] | str]:
    """The only critical exact rate: (exact score, n pages, rate, Wilson CI)."""
    scores = [
        0.0 if r["hard_failures"] else r["critical"]["exact"] / r["critical"]["n"]
        for r in records
        if r["hard_failures"] or r["critical"]["n"]
    ]
    if not scores:
        return 0.0, 0, INSUFFICIENT, INSUFFICIENT
    exact, n = sum(scores), len(scores)
    return exact, n, exact / n, wilson_interval(exact, n)


def _real(v: object) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v) and v >= 0


def _validate(r: Any) -> None:
    """Fail closed: any malformed WO-D08-1 record is a ValueError, never a wrong rate."""
    try:
        c, m, cost = r["critical"], r["metrics"], r["provider_cost_usd"]
        ok = (
            all(isinstance(r[k], str) for k in ("page_id", "doc_id", "stratum", "candidate_id"))
            and all(type(c[k]) is int for k in ("n", "exact", "accepted_errors"))
            and 0 <= c["exact"] <= c["n"]
            and c["accepted_errors"] >= 0
            and isinstance(r["hard_failures"], list)
            and isinstance(m, dict)
            and all(_real(m[k]) for k in _METRICS if k in m)
            and (cost is None or _real(cost))
            and _real(r["latency_ms"])
        )
    except (KeyError, TypeError) as e:
        raise ValueError(f"malformed screen record ({e!r}): {r!r:.300}") from e
    if not ok:
        raise ValueError(f"malformed screen record: {r!r:.300}")


def _cell(records: list[dict[str, Any]]) -> dict[str, Any]:
    """One stratum x candidate cell. A critical-less cell is insufficient, not zero."""
    accepted = [r for r in records if not r["hard_failures"]]
    exact, n, rate, ci = _exact(records)
    costs = [r["provider_cost_usd"] for r in records]
    known = [c for c in costs if c is not None]
    latencies = [float(r["latency_ms"]) for r in records]
    return {
        "pages": len(records),
        "docs": len({r["doc_id"] for r in records}),
        "critical_n": n,
        "critical_exact": exact,
        "critical_exact_rate": rate,
        "critical_exact_ci": ci,
        "accepted_critical_errors": sum(r["critical"]["accepted_errors"] for r in records),
        "cer": _metric(records, "cer"),
        "table_f1": _metric(records, "table_f1"),
        "formula_score": _metric(records, "formula_score"),
        "failures": len(records) - len(accepted),
        # Never invent a cost: unknown on any page means unknown for the cell.
        "cost_per_accepted_page_usd": (
            sum(known) / len(accepted) if accepted and len(known) == len(costs) else None
        ),
        "latency_ms_p50": _percentile(latencies, 0.5),
        "latency_ms_p95": _percentile(latencies, 0.95),
    }


def _by_doc(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in records:
        out[r["doc_id"]].append(r)
    return out


def _paired(base: list[dict[str, Any]], cand: list[dict[str, Any]]) -> dict[str, Any]:
    b_docs, c_docs = _by_doc(base), _by_doc(cand)
    docs = sorted(set(b_docs) & set(c_docs))
    only_cand = only_base = 0
    cer_diff: list[float] = []
    for d in docs:
        b, c = _doc_critical_exact(b_docs[d]), _doc_critical_exact(c_docs[d])
        only_cand += c and not b
        only_base += b and not c
        cb, cc = _metric(b_docs[d], "cer"), _metric(c_docs[d], "cer")
        if cb is not None and cc is not None:
            cer_diff.append(cc - cb)
    return {
        "paired_docs": len(docs),
        "candidate_only_exact": only_cand,
        "incumbent_only_exact": only_base,
        "mcnemar_p": mcnemar_exact(only_cand, only_base) if docs else INSUFFICIENT,
        "cer_diff_mean": _mean(cer_diff),
        "cer_diff_ci": bootstrap_ci(cer_diff) if cer_diff else INSUFFICIENT,
    }


def _rank_key(cell: dict[str, Any]) -> tuple[float, float, float, float]:
    cer, cost = cell["cer"], cell["cost_per_accepted_page_usd"]
    # Failure fraction before CER: a failed page's metrics must not win a tie.
    return (
        -cell["critical_exact_rate"],
        cell["failures"] / cell["pages"],
        cer if cer is not None else math.inf,
        cost if cost is not None else math.inf,
    )


def build_report(records: list[dict[str, Any]], *, incumbent: str) -> dict[str, Any]:
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    seen: set[tuple[str, str, str, str]] = set()
    for r in records:
        _validate(r)
        # At-least-once delivery: a page counted twice would weigh twice in every rate.
        key = (r["stratum"], r["candidate_id"], r["doc_id"], r["page_id"])
        if key in seen:
            raise ValueError(f"duplicate screen record for {key}")
        seen.add(key)
        grouped[r["stratum"]][r["candidate_id"]].append(r)

    strata: dict[str, Any] = {}
    ranked: dict[str, list[str]] = {}
    for stratum in sorted(grouped):
        cells = {c: _cell(rs) for c, rs in grouped[stratum].items()}
        pairs = {
            c: _paired(grouped[stratum].get(incumbent, []), grouped[stratum][c])
            for c in cells
            if c != incumbent
        }
        rejected: dict[str, str] = {}
        eligible: list[str] = []
        for c, cell in cells.items():
            if cell["accepted_critical_errors"] > 0:
                rejected[c] = f"accepted_critical_errors={cell['accepted_critical_errors']}"
            elif cell["failures"] == cell["pages"]:
                rejected[c] = "no_accepted_pages"
            elif cell["critical_n"] == cell["failures"]:  # no accepted page with critical fields
                rejected[c] = INSUFFICIENT
            else:
                eligible.append(c)
        # Incumbent first on ties, so a challenger must be strictly better to displace it.
        eligible.sort(key=lambda c: (_rank_key(cells[c]), c != incumbent, c))
        ranked[stratum] = eligible
        strata[stratum] = {"cells": cells, "paired_vs_incumbent": pairs, "rejected": rejected}

    wins: dict[str, list[str]] = defaultdict(list)
    for stratum, order in ranked.items():
        if order:
            wins[order[0]].append(stratum)
    minority = {c for c, s in wins.items() if c != incumbent and len(s) == 1}

    routes: dict[str, Any] = {}
    for stratum, order in ranked.items():
        alternatives = [c for c in order[1:] if c not in minority][:MAX_ALTERNATIVES]
        routes[stratum] = {
            "primary": order[0] if order else None,
            "alternatives": alternatives,
            "reason": None if order else "no_eligible_candidate",
        }

    summary: dict[str, Any] = {}
    for c in sorted({r["candidate_id"] for r in records}):
        rates = {
            s: cell["critical_exact_rate"]
            for s in strata
            if (cell := strata[s]["cells"].get(c)) and cell["critical_exact_rate"] != INSUFFICIENT
        }
        worst = min(rates, key=lambda s: (rates[s], s)) if rates else None
        summary[c] = {
            "macro_critical_exact_rate": _mean(list(rates.values())),
            "worst_stratum": worst,
            "worst_stratum_critical_exact_rate": rates[worst] if worst else None,
            "strata_insufficient": sorted(set(strata) - set(rates)),
        }
    return {"incumbent": incumbent, "strata": strata, "routes": routes, "summary": summary}
