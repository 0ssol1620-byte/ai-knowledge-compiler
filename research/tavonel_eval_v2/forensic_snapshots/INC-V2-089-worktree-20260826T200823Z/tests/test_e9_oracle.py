"""Tests for `compiler/e9_oracle.py`.

E9: every detected typed change in a channel this contract declares support
for creates a rebuild request production does not silently drop. This file
proves, per channel:

    1. the independent expected side is genuinely independent (it is computed
       via `dependency_contract`, never via `akc_cir.recompilation
       .plan_recompilation` or `RecompilationPlan.to_rebuild`)
    2. what E9 actually reports on the real fixtures -- SEMANTIC and
       STRUCTURAL PASS (production already supports them); LOCATOR, TEMPORAL
       and METADATA FAIL, and FAIL names exactly the artifact INC-V2-038 found
       missing
    3. gate power for the comparison itself: a PASS is proven capable of
       flipping to FAIL when the expected artifact is withheld, and a FAIL is
       proven capable of flipping to PASS when it is supplied -- so neither
       result is an artifact of a check that can only ever go one way
"""

from __future__ import annotations

import sys
from pathlib import Path

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "compiler")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import compiler.dependency_contract as dc  # noqa: E402
import compiler.e9_oracle as e9  # noqa: E402
from akc_cir.semantic_diff import ChangeChannel  # noqa: E402

# ---------------------------------------------------------------------------
# Independence from the production planner -- the tautology this task
# explicitly forbids re-deriving.


def test_expected_side_never_binds_recompilation_plan_or_module() -> None:
    """`dependency_contract` and `e9_oracle` must not hold a reference to
    `akc_cir.recompilation` (the module), `plan_recompilation` (the function)
    or `RecompilationPlan` (the type this task names as the proven tautology
    `to_rebuild = tuple(dict.fromkeys(stale + unresolved))`) anywhere in their
    module namespace. Checked against the actual bound objects, not by reading
    source text -- an indirect import would still show up here."""
    import akc_cir.recompilation as recompilation_module

    forbidden = (
        recompilation_module,
        recompilation_module.plan_recompilation,
        recompilation_module.RecompilationPlan,
    )
    for module in (e9, dc):
        for name, value in vars(module).items():
            # Identity, not `in`/`==`: several bound values here (dicts,
            # frozensets-of-dicts) are unhashable, and set/`in` membership
            # would raise on them before ever reaching a real comparison.
            assert not any(value is banned for banned in forbidden), (
                f"{module.__name__}.{name} binds a production-planner object; "
                "the expected side would no longer be independent"
            )


# ---------------------------------------------------------------------------
# The five-channel matrix, run against real production output.


def test_semantic_passes_production_already_supports_it() -> None:
    result = e9.evaluate_semantic()
    assert result.verdict == "PASS"
    assert result.decision.verdict is dc.Verdict.SEED_SET
    assert result.silent_disappearance == frozenset()


def test_structural_passes_production_already_supports_it() -> None:
    result = e9.evaluate_structural()
    assert result.verdict == "PASS"
    assert result.decision.verdict is dc.Verdict.SEED_SET
    assert result.silent_disappearance == frozenset()


def test_locator_RESOLVES_to_the_seed_set_the_contract_declares() -> None:
    """INC-V2-038, closed and now guarded.

    This test was `..._FAILS_silent_disappearance_names_the_section_artifact`
    and asserted the finding: the contract said `section:<unit>` must rebuild
    and production's actual rebuild request was empty, so the change was
    detected and then silently disappeared. The channel-closure repair connected
    the facet to the declarative contract, so the same evaluation now resolves to
    the declared seed set. The frozen SFI2 finding is unchanged history; this
    assertion is the guard that keeps the repair in place.

    The expected side still comes from the contract, never from the planner --
    `decision.dependents` is derived from the declared facet sensitivity, so
    this compares an independent expectation against production, not production
    against itself.
    """
    result = e9.evaluate_locator()
    assert result.verdict == "PASS"
    assert result.silent_disappearance == frozenset()
    assert result.decision.dependents <= result.production_actual
    assert result.decision.dependents != frozenset()


def test_temporal_RESOLVES_to_the_seed_set_the_contract_declares() -> None:
    result = e9.evaluate_temporal()
    assert result.verdict == "PASS"
    assert result.silent_disappearance == frozenset()
    assert result.decision.dependents <= result.production_actual
    assert result.decision.dependents != frozenset()


def test_metadata_RESOLVES_to_the_seed_set_the_contract_declares() -> None:
    result = e9.evaluate_metadata()
    assert result.verdict == "PASS"
    assert result.silent_disappearance == frozenset()
    assert result.decision.dependents <= result.production_actual
    assert result.decision.dependents != frozenset()


def test_run_all_produces_exactly_the_five_declared_channels() -> None:
    results = e9.run_all()
    assert [r.channel_name for r in results] == [
        "SEMANTIC",
        "STRUCTURAL",
        "LOCATOR",
        "TEMPORAL",
        "METADATA",
    ]
    by_channel = {r.channel_name: r.verdict for r in results}
    #: Three of these read FAIL until the channel-closure repair landed --
    #: LOCATOR, TEMPORAL and METADATA were detected, typed, and then reached no
    #: seed. The power tests below are what keep this row of PASSes meaningful:
    #: an endpoint nothing could have violated has not been met, it has been
    #: avoided.
    assert by_channel == {
        "SEMANTIC": "PASS",
        "STRUCTURAL": "PASS",
        "LOCATOR": "PASS",
        "TEMPORAL": "PASS",
        "METADATA": "PASS",
    }


# ---------------------------------------------------------------------------
# Gate power for the comparison itself (Task 3): a clean PASS must be shown
# capable of becoming a FAIL, and an observed FAIL must be shown capable of
# becoming a PASS, on the same decision -- otherwise the verdict is not
# measuring anything.


def _refinish_with(result: e9.E9Result, production_actual: frozenset[str]) -> e9.E9Result:
    return e9._finish(
        result.channel_name, result.ir_channel, result.decision, production_actual
    )


def test_semantic_pass_has_power_withholding_the_artifact_flips_it_to_fail() -> None:
    result = e9.evaluate_semantic()
    assert result.verdict == "PASS"
    withheld = result.production_actual - result.decision.dependents
    injected = _refinish_with(result, withheld)
    assert injected.verdict == "FAIL"
    assert injected.silent_disappearance == result.decision.dependents


def test_structural_pass_has_power_withholding_the_artifact_flips_it_to_fail() -> None:
    result = e9.evaluate_structural()
    assert result.verdict == "PASS"
    withheld = result.production_actual - result.decision.dependents
    injected = _refinish_with(result, withheld)
    assert injected.verdict == "FAIL"


def test_locator_pass_has_power_withdrawing_the_artifact_flips_it_to_fail() -> None:
    """The power test, reversed along with the verdict it guards.

    While LOCATOR read FAIL, power meant: supply the missing artifact and watch
    it flip to PASS. Now that it reads PASS, that direction proves nothing -- the
    question became whether this endpoint could still come back red. So the
    artifact the contract declares is withdrawn from production's actual seed
    set, and the endpoint must name it as a silent disappearance.

    Without this, the PASS above would be indistinguishable from an endpoint
    that had stopped watching.
    """
    result = e9.evaluate_locator()
    assert result.verdict == "PASS"
    withdrawn = result.production_actual - result.decision.dependents
    injected = _refinish_with(result, withdrawn)
    assert injected.verdict == "FAIL"
    assert injected.silent_disappearance == result.decision.dependents


def test_temporal_pass_has_power_withdrawing_the_artifact_flips_it_to_fail() -> None:
    result = e9.evaluate_temporal()
    assert result.verdict == "PASS"
    injected = _refinish_with(result, result.production_actual - result.decision.dependents)
    assert injected.verdict == "FAIL"


def test_metadata_pass_has_power_withdrawing_the_artifact_flips_it_to_fail() -> None:
    result = e9.evaluate_metadata()
    assert result.verdict == "PASS"
    injected = _refinish_with(result, result.production_actual - result.decision.dependents)
    assert injected.verdict == "FAIL"


# ---------------------------------------------------------------------------
# UNPROVEN path: an UNRESOLVED contract decision must surface as UNPROVEN, not
# be silently folded into PASS or FAIL by the comparison layer.


def test_unresolved_contract_decision_surfaces_as_unproven_not_pass_or_fail() -> None:
    unresolved = dc.ContractDecision(
        subject="u:phantom",
        channel=ChangeChannel.LOCATOR,
        dependency_channel=None,
        verdict=dc.Verdict.UNRESOLVED,
        reason="synthetic UNRESOLVED for the comparison-layer test",
    )
    result = e9._finish("LOCATOR", "REFERENTIAL", unresolved, frozenset())
    assert result.verdict == "UNPROVEN"
    assert result.silent_disappearance == frozenset()
