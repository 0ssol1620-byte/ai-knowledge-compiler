#!/usr/bin/env python3
"""Freeze arm B's exact same-family recovery recipe, before any outcome exists.

`preregistration-v2.json` says of arm B: "Permit exactly one bounded same-family
recovery variation at the same decision point before independent-family
escalation. The exact same-family recipe/settings must be frozen before outcomes
are scored; no post-hoc tuning."

The readiness audit records that as an open gate
(`exact_same_family_recipe_not_frozen`). This script closes it at zero cost.

**Nothing here is invented.** The recipe is *derived* from two structures that
already exist in the repository and were written for other reasons:

  * `akc_parallel_runtime.recovery_planner.plan_minimal_recovery`, whose
    `_FAILURE_VARIANTS` table already maps each public failure-taxonomy code to
    exactly one preprocessing variant, and which already picks the minimum valid
    scope; and
  * `akc_cir.recovery_policy`'s `L2_SAME_PARSER_VARIATION` rungs, which already
    carry the per-code action and its GPU/cost/wall-clock estimate.

Deriving rather than authoring is the point: a recipe invented for the
experiment would be a knob, and a knob chosen by the experimenter is what
"no post-hoc tuning" exists to forbid. If the derivation is wrong, it is wrong
in the production planner too, and that is a finding rather than a setting.

The freeze is legitimate now precisely because **no arm has run**: the readiness
audit records `gpu_spend_authorized: false` and `incremental_gpu_spend_usd: 0.0`,
and the cohort carries no ground truth. There is no outcome to have peeked at.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "packages" / "cir-python" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "parallel-runtime" / "src"))

from akc_cir.cause_conditioned_recovery import (  # noqa: E402
    RecoveryOperatorKind,
    operator_kind,
)
from akc_cir.recovery_policy import (  # noqa: E402
    FailureCode as PolicyFailureCode,
)
from akc_cir.recovery_policy import (  # noqa: E402
    default_recovery_registry,
)
from akc_parallel_runtime.recovery import RecoveryScope, RegionLevel  # noqa: E402
from akc_parallel_runtime.recovery_planner import (  # noqa: E402
    FailureCode as TaxonomyFailureCode,
)
from akc_parallel_runtime.recovery_planner import (  # noqa: E402
    plan_minimal_recovery,
)

EXP = ROOT / "research" / "experiments" / "H1-A12-01"
COHORT = EXP / "cohorts" / "semantic-divergence-pilot-v1.json"
PREREG = EXP / "preregistration-v2.json"
_PR = ROOT / "packages" / "parallel-runtime" / "src" / "akc_parallel_runtime"
PLANNER = _PR / "recovery_planner.py"
RECOVERY = _PR / "recovery.py"
POLICY = ROOT / "packages" / "cir-python" / "src" / "akc_cir" / "recovery_policy.py"
CAUSE = ROOT / "packages" / "cir-python" / "src" / "akc_cir" / "cause_conditioned_recovery.py"

#: Declared non-recoverable by `benchmark/v6/public_failure_adapter.py`. A case
#: whose codes are entirely non-recoverable gets no same-family attempt at all,
#: in either arm. Recording that here rather than discovering it at scoring time
#: is the difference between a rule and an excuse.
NON_RECOVERABLE = frozenset({"T03", "H01", "H02"})

#: The scope ladder offered to the planner for a case. The *case* supplies the
#: identifiers and its own declared minimum level; the ladder only adds the
#: coarser levels the planner is allowed to escalate to. Offering a level the
#: case does not carry would let the planner pick a scope with no source
#: reference behind it.
_ESCALATION_LADDER = (
    RegionLevel.CELL,
    RegionLevel.REGION,
    RegionLevel.PAGE,
    RegionLevel.DOCUMENT,
)


def scopes_for_case(case: dict[str, Any]) -> tuple[RecoveryScope, ...]:
    """Build the planner's candidate scopes out of the case's own references."""
    refs = tuple(case["scope_ids"])
    declared = RegionLevel(case["minimum_scope_level"])
    rank = {level: index for index, level in enumerate(_ESCALATION_LADDER)}
    start = rank.get(declared, 0)
    levels = [declared] + [
        level for level in _ESCALATION_LADDER[start + 1 :] if level != declared
    ]
    return tuple(
        RecoveryScope(level=level, scope_id=f"{case['case_id']}::{level.value}", source_refs=refs)
        for level in levels
    )


def sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha256(value: Any) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def l2_rungs() -> dict[str, dict[str, Any]]:
    """Every `L2_SAME_PARSER_VARIATION` rung the policy registry already defines."""
    registry = default_recovery_registry()
    rungs: dict[str, dict[str, Any]] = {}
    for code in PolicyFailureCode:
        for policy in registry.for_code(code):
            if operator_kind(policy) is not RecoveryOperatorKind.SAME_FAMILY_RETRY:
                continue
            rungs[code.value] = {
                "policy_id": policy.policy_id,
                "action": policy.action,
                "signature": policy.signature,
                "estimated_gpu_seconds": policy.estimated_gpu_seconds,
                "estimated_cost_units": policy.estimated_cost_units,
                "estimated_wall_clock_seconds": policy.estimated_wall_clock_seconds,
            }
    return rungs


def derive_case_recipes(
    cases: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    recipes: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for case in cases:
        codes = list(case["failure_codes"])
        recoverable = [c for c in codes if c not in NON_RECOVERABLE]
        if not recoverable:
            skipped.append(
                {
                    "case_id": case["case_id"],
                    "stratum": case["stratum"],
                    "failure_codes": codes,
                    "reason": (
                        "all codes are declared non-recoverable by the "
                        "public failure adapter"
                    ),
                }
            )
            continue
        taxonomy = tuple(TaxonomyFailureCode(c) for c in sorted(recoverable))
        scope, variant = plan_minimal_recovery(taxonomy, scopes_for_case(case))
        recipes.append(
            {
                "case_id": case["case_id"],
                "stratum": case["stratum"],
                "failure_codes": codes,
                "codes_used_for_variant": sorted(recoverable),
                "codes_excluded_non_recoverable": sorted(set(codes) & NON_RECOVERABLE),
                "minimum_scope_level": case["minimum_scope_level"],
                "planned_scope_level": str(scope.level.value),
                "planned_scope_id": scope.scope_id,
                "planned_same_family_variant": str(
                    variant.value if hasattr(variant, "value") else variant
                ),
                "candidate_models": case["candidate_models"],
            }
        )
    return recipes, skipped


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    cohort = json.loads(COHORT.read_text(encoding="utf-8"))
    cases = cohort["cases"]
    recipes, skipped = derive_case_recipes(cases)

    by_variant: dict[str, int] = {}
    for recipe in recipes:
        key = recipe["planned_same_family_variant"]
        by_variant[key] = by_variant.get(key, 0) + 1

    receipt: dict[str, Any] = {
        "schema": "tavonel.a12-same-family-recipe-freeze.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "experiment_id": "H1-A12-01",
        "freezes": (
            "preregistration-v2 arm B: exactly one bounded same-family variation "
            "before independent-family escalation"
        ),
        "frozen_before_any_outcome": True,
        "why_that_is_true": (
            "No A12 arm has been executed. The runtime readiness audit records "
            "gpu_spend_authorized false and incremental_gpu_spend_usd 0.0, and the "
            "cohort manifest carries no ground truth. There is no outcome to have seen."
        ),
        "derivation": (
            "Recipes are derived from akc_parallel_runtime.recovery_planner."
            "plan_minimal_recovery over the cohort's own failure codes, and the "
            "L2_SAME_PARSER_VARIATION rungs already present in "
            "akc_cir.recovery_policy. No variant, scope, budget or threshold was "
            "authored for this experiment."
        ),
        "rules": [
            "Arm B permits at most ONE same-family variation per case, then "
            "escalates to independent family.",
            "Arm A permits ZERO same-family variations; it excludes the failed "
            "independent family and escalates directly.",
            "The variant and scope for a case are those frozen below and may not "
            "be changed after any outcome is observed.",
            "A case whose failure codes are all declared non-recoverable receives "
            "no same-family attempt in either arm.",
            "Operational/transient retry is an implementation control and is "
            "excluded from the semantic primary endpoint.",
            "If a frozen variant turns out to be unimplementable at execution "
            "time, the case is reported as NOT RUN. It is not silently re-planned.",
        ],
        "non_recoverable_codes": sorted(NON_RECOVERABLE),
        "non_recoverable_source": "benchmark/v6/public_failure_adapter.py",
        "escalation_ladder": [level.value for level in _ESCALATION_LADDER],
        "l2_same_family_rungs_in_policy_registry": l2_rungs(),
        "case_count": len(cases),
        "recipe_count": len(recipes),
        "skipped_all_non_recoverable": skipped,
        "variant_distribution": dict(sorted(by_variant.items())),
        "case_recipes": recipes,
        "pinned_files": {
            str(p.relative_to(ROOT)).replace("\\", "/"): sha256_file(p)
            for p in (COHORT, PREREG, PLANNER, RECOVERY, POLICY, CAUSE, Path(__file__))
        },
        "claim_boundary": (
            "This is a protocol freeze, not evidence. It authorizes no A12 benefit "
            "claim and does not by itself authorize GPU spend: the formal immutable "
            "runtime gate remains separate and is still open."
        ),
        "external_gpu_cost_usd": 0.0,
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"frozen recipes: {len(recipes)} of {len(cases)} cases")
    print(f"skipped (all codes non-recoverable): {len(skipped)}")
    for variant, count in sorted(by_variant.items()):
        print(f"  {variant}: {count}")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
