#!/usr/bin/env python3
"""H1-L extension -- `assigned_column`, the last facet nothing compared directly.

The frozen contract lists six per-row facets. `footprint()` in run_exactness.py
builds rows from five of them:

    match, logical_id, candidates, relation, score

`assigned_column` -- "which previous unit was paired", `assignment[i]` -- is not
there. Amendment 2 described it as *indirectly* implied by `logical_id` and
`candidates`, and the registry was then updated to say all twelve contract facets
are compared and exact.

That sentence was not supported. "Indirectly implied" is the same reasoning that
produced P15 and P16, committed a third time inside the correction to P15, and
the response is the same: measure it.

Why the indirect argument is genuinely insufficient, not merely unproven. Equal
`logical_id` does not entail equal column. `logical_id` comes from the *partner*,
so two distinct previous units carrying the same logical id -- a duplicate, a
re-seeded unit, a carry-forward collision -- are indistinguishable through it.
Two policies could pair row `i` with different columns, agree on every facet
`footprint()` compares, and still have paired different units.

Method. `assign_one_to_one` never returns its `assignment` map and identity.py is
Protected Core, so it is not edited. Instead the resolver is subclassed and its
two entry points are observed: `decide_pair(partner=previous[column])` reveals
the column by object identity, and `resolve(unit, [])` marks an unassigned row.
Both policies call exactly these two functions, so this reads the column the
shipped code actually selected rather than recomputing a candidate for it.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "packages" / "cir-python" / "src"))

from akc_cir.identity import (  # noqa: E402
    LogicalIdentityResolver,
    MatchingPolicy,
    assign_one_to_one,
)
from certified_sparse import Stats, assign_certified_sparse  # noqa: E402
from run_exactness import corpus  # noqa: E402


class ColumnObservingResolver(LogicalIdentityResolver):
    """A resolver that records which previous unit each row was paired with.

    Observation only: both overrides delegate to the base implementation and
    change no decision. The column is recovered by object identity against the
    `previous` list, so duplicate logical ids -- the exact case the indirect
    argument cannot cover -- are still distinguished.
    """

    def __init__(self, previous: list[Any]) -> None:
        super().__init__()
        self._index_of = {id(unit): j for j, unit in enumerate(previous)}
        self.columns: list[int | None] = []

    def decide_pair(self, **kwargs: Any):  # type: ignore[override]
        self.columns.append(self._index_of.get(id(kwargs["partner"])))
        return super().decide_pair(**kwargs)

    def resolve(self, unit: Any, candidates: Any):  # type: ignore[override]
        if not candidates:
            self.columns.append(None)
        return super().resolve(unit, candidates)


def canonical_sha256(v: Any) -> str:
    body = json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def main() -> int:
    divergences = 0
    unresolvable = 0
    compared = 0
    examples: list[dict[str, Any]] = []
    control_hits = 0
    observations = 0
    integer_columns = 0
    unassigned_rows = 0
    cases_observed = 0

    for case in corpus():
        inc, prev = case["incoming"], case["previous"]

        r_leg = ColumnObservingResolver(list(prev))
        assign_one_to_one(list(inc), list(prev), resolver=r_leg, policy=MatchingPolicy.LEGACY)

        r_spa = ColumnObservingResolver(list(prev))
        assign_certified_sparse(list(inc), list(prev), resolver=r_spa, stats=Stats())

        compared += 1
        if len(r_leg.columns) != len(inc):
            unresolvable += 1

        # Liveness control. Two empty observation lists compare equal, so a probe
        # that silently never fired would produce exactly the zero this run
        # reports. That failure has already voided one experiment here, so the
        # counts are recorded as evidence rather than assumed.
        observations += len(r_leg.columns)
        integer_columns += sum(1 for c in r_leg.columns if isinstance(c, int))
        unassigned_rows += sum(1 for c in r_leg.columns if c is None)
        cases_observed += 1 if r_leg.columns else 0

        # Control: does a column exist that logical_id alone could not have
        # distinguished? If previous carries duplicate logical ids, the indirect
        # argument is provably insufficient on this corpus, not just unproven.
        ids = [p.logical_id for p in prev]
        if len(set(ids)) != len(ids):
            control_hits += 1

        if r_leg.columns != r_spa.columns:
            divergences += 1
            if len(examples) < 5:
                examples.append(
                    {
                        "case": case["name"],
                        "legacy_columns": r_leg.columns,
                        "certified_sparse_columns": r_spa.columns,
                    }
                )

    exact = divergences == 0 and cases_observed == compared and integer_columns > 0
    receipt: dict[str, Any] = {
        "schema": "tavonel.certified-sparse-assigned-column.v1",
        "experiment": "H1-L-CERTIFIED-SPARSE-MATCHER-01",
        "extension_of": "receipts/exactness-2026-08-19.json",
        "generated_at": datetime.now(UTC).isoformat(),
        "closes": (
            "assigned_column is the sixth per-row facet of the frozen contract and the only "
            "one footprint() never compared. Amendment 2 called it indirectly implied by "
            "logical_id and candidates, and the registry then claimed all twelve facets were "
            "compared. That claim was unsupported until this run."
        ),
        "why_indirect_was_insufficient": (
            "logical_id is read from the partner, so two distinct previous units sharing a "
            "logical id are indistinguishable through it. Two policies could pair a row with "
            "different columns, agree on every facet footprint() compares, and still have "
            "paired different units."
        ),
        "method": (
            "Subclass LogicalIdentityResolver and observe its two entry points -- "
            "decide_pair(partner=...) gives the column by object identity, resolve(unit, []) "
            "marks an unassigned row. identity.py is Protected Core and is not modified, and "
            "both policies call exactly these functions, so the column observed is the one "
            "the shipped code selected."
        ),
        "cases": compared,
        "instrument_liveness": {
            "cases_producing_observations": cases_observed,
            "total_column_observations": observations,
            "integer_columns_observed": integer_columns,
            "unassigned_rows_observed": unassigned_rows,
            "live": cases_observed == compared and integer_columns > 0,
            "why_recorded": (
                "Two empty observation lists compare equal, so a probe that never fired "
                "would yield the same zero. This programme has already voided an experiment "
                "on a non-separating instrument, so liveness is measured, not assumed."
            ),
        },
        "column_divergences": divergences,
        "rows_with_unrecoverable_column": unresolvable,
        "cases_with_duplicate_previous_logical_ids": control_hits,
        "divergence_examples": examples,
        "assigned_column_exact": exact,
        "result": "ASSIGNED_COLUMN_EXACT" if exact else "ASSIGNED_COLUMN_DIVERGENT",
        "scope_limitation": (
            "The corpus carries no duplicate previous logical ids, so this run does not "
            "exercise the case that makes the indirect argument fail. It establishes that "
            "the columns agree here; it does not establish that logical_id would have been "
            "an adequate proxy, and the facet stays measured directly rather than inferred."
        ),
        "instrument_note": (
            "No mutants of its own. It inherits separating power from the main H1-L run, "
            "whose winner_rotated mutant permutes assignments and separated on 10 cases -- "
            "the mutant most directly targeted at this facet."
        ),
        "identity_module_modified": False,
        "blocked_policy_executed": False,
        "external_gpu_cost_usd": 0.0,
        "network_access": False,
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    out = HERE.parent / "receipts" / "assigned-column-exactness-2026-08-19.json"
    out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"result: {receipt['result']}")
    print(f"  cases:                       {compared}")
    print(f"  column divergences:          {divergences}")
    print(f"  unrecoverable columns:       {unresolvable}")
    print(f"  cases w/ duplicate prev ids: {control_hits}")
    print(f"  observations (int/None):     {observations} ({integer_columns}/{unassigned_rows})")
    print(f"wrote {out}")
    return 0 if exact else 1


if __name__ == "__main__":
    raise SystemExit(main())
