#!/usr/bin/env python3
"""E9 -- every detected typed change this contract declares support for
creates a rebuild request production does not silently drop.

    independent expected side:
        detected typed SourceFact change
          -> declared supported channel               (dependency_contract's
                                                          _DEPENDENCY_CHANNEL_OF_UNIT_SCOPED)
          -> artifact-declared facet sensitivity        (dependency_contract
             / dependency contract                       .DEFAULT_SENSITIVITY)
          -> expected dependent seed set                (dependency_contract
                                                          .decide_unit_change /
                                                          .decide_structural,
                                                          real DependencyGraph
                                                          .impact_of traversal)

    production side:
        production diff -> production changed IDs -> production graph/planner
          -> actual rebuild request set                 (compiler.channel_cases'
                                                          cases, which run real
                                                          canonical_document /
                                                          diff_documents /
                                                          graph_for /
                                                          plan_recompilation)

E9 compares the two and reports SILENT_DISAPPEARANCE = expected - actual: the
artifacts this contract says must rebuild that production's actual rebuild
request does not contain. This is a subset check, not set equality --
production's `graph_for` declares some artifacts SEMANTIC-sensitive that its
own `build_all` digest does not actually read (`document-index:` and
`topic-bucket:` for a pure text edit), so production legitimately does *more*
work than this contract requires on SEMANTIC/STRUCTURAL. Extra work is not the
failure mode E9 exists to catch; a missing artifact is.

Neither side is derived from the other. The expected side never calls
`akc_cir.recompilation.plan_recompilation` or reads `RecompilationPlan
.to_rebuild` -- it only reads `inventory_and_dependencies`'s reads mapping
(which artifact touches which logical id -- structural fact, not policy) and
runs its own traversal over its own declared sensitivity table via
`dependency_contract.decide_unit_change` / `.decide_structural`. The production
side is `compiler/channel_cases.py`'s cases, run unmodified. Comparing the two
is what makes "named ≡ planned" (`RecompilationPlan.to_rebuild = tuple(dict
.fromkeys(stale + unresolved))`, provably a tautology against itself) not the
comparison being made here.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]
for _root in (
    str(ROOT / "packages" / "cir-python" / "src"),
    str(NS),
    str(NS / "compiler"),
):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import compiler.channel_cases as cc  # noqa: E402
import compiler.dependency_contract as dc  # noqa: E402
import compiler.selective_build as engine  # noqa: E402
from akc_cir.semantic_diff import DiffLevel, diff_documents  # noqa: E402

__all__ = [
    "E9Result",
    "evaluate_locator",
    "evaluate_metadata",
    "evaluate_semantic",
    "evaluate_structural",
    "evaluate_temporal",
    "run_all",
]


@dataclass(frozen=True, slots=True)
class E9Result:
    """One channel's E9 comparison.

    `verdict` is:

        PASS      contract verdict is SEED_SET and every expected dependent
                   is present in production's actual rebuild set (or the
                   contract verdict is NO_DEPENDENT, so nothing was expected)
        FAIL       contract verdict is SEED_SET and `silent_disappearance`
                   (expected - actual) is non-empty
        UNPROVEN   contract verdict is UNRESOLVED -- the comparison could not
                   be made and is not reported as either PASS or FAIL
    """

    channel_name: str
    ir_channel: str
    decision: dc.ContractDecision
    production_actual: frozenset[str]
    silent_disappearance: frozenset[str]
    verdict: str

    @property
    def passed(self) -> bool:
        return self.verdict == "PASS"


def _finish(
    channel_name: str,
    ir_channel: str,
    decision: dc.ContractDecision,
    production_actual: frozenset[str],
) -> E9Result:
    if decision.verdict is dc.Verdict.UNRESOLVED:
        return E9Result(
            channel_name=channel_name,
            ir_channel=ir_channel,
            decision=decision,
            production_actual=production_actual,
            silent_disappearance=frozenset(),
            verdict="UNPROVEN",
        )
    disappearance = decision.dependents - production_actual
    verdict = "FAIL" if disappearance else "PASS"
    return E9Result(
        channel_name=channel_name,
        ir_channel=ir_channel,
        decision=decision,
        production_actual=production_actual,
        silent_disappearance=frozenset(disappearance),
        verdict=verdict,
    )


# ---------------------------------------------------------------------------
# Per-channel evaluators. Each rebuilds the same document pair
# `compiler/channel_cases.py`'s case function builds internally (using its
# exported `document`/`markdown`/`BODY_*`/`LINEAGE` helpers, not by modifying
# or reaching into that module), so the independently-computed reads mapping
# describes the same artifacts the production case actually produced a plan
# for. `assert case.target_artifact in reads` is the drift guard: if a future
# edit to `channel_cases.py`'s fixture construction diverges from the copy
# here, this fails loudly instead of silently comparing two different corpora.


def evaluate_semantic() -> E9Result:
    case = cc.semantic_case()
    before_doc = cc.document(cc.markdown(cc.BODY_ALPHA, cc.BODY_BETA), "v1")
    after_raw = cc.markdown(
        cc.BODY_ALPHA, cc.BODY_BETA.replace("reporting obligation", "disclosure duty")
    )
    after_doc = cc.document(after_raw, "v2")

    before_units, before_shape = engine.snapshots(before_doc)
    after_units, after_shape = engine.snapshots(after_doc)
    diff = diff_documents(
        before_sha256=before_doc["source_digest"],
        after_sha256=after_doc["source_digest"],
        level=DiffLevel.SEMANTIC,
        before_shape=before_shape,
        after_shape=after_shape,
        before_units=before_units,
        after_units=after_units,
        source=after_doc["source_id"],
    )
    before_deps, _ = engine.inventory_and_dependencies(before_doc)
    after_deps, _ = engine.inventory_and_dependencies(after_doc)
    reads = dc.merged_reads(before_deps, after_deps)
    assert case.target_artifact in reads, (
        "reconstructed fixture does not match channel_cases.semantic_case's document pair"
    )

    changed = [c for c in diff.changes if c.channel.value == "semantic"]
    assert changed, "fixture did not produce a SEMANTIC change"
    decision = dc.decide_unit_change(changed[0], graph_reads=reads)
    production_actual = frozenset(case.result["affected_subgraph"])
    return _finish("SEMANTIC", "SEMANTIC", decision, production_actual)


def evaluate_structural() -> E9Result:
    case = cc.structural_case()
    before_doc = cc.document(cc.markdown(cc.BODY_ALPHA, cc.BODY_BETA, cc.BODY_GAMMA), "v1")
    raw_units = list(before_doc["units"])
    after_units_raw = [raw_units[0], raw_units[2], raw_units[1]]
    after_doc = {**before_doc, "units": after_units_raw, "version_id": "v2"}

    before_deps, _ = engine.inventory_and_dependencies(before_doc)
    after_deps, _ = engine.inventory_and_dependencies(after_doc)
    reads = dc.merged_reads(before_deps, after_deps)
    assert case.target_artifact in reads, (
        "reconstructed fixture does not match channel_cases.structural_case's document pair"
    )

    decision = dc.decide_structural(case.diff, graph_reads=reads)
    production_actual = frozenset(case.plan.to_rebuild)
    return _finish("STRUCTURAL", "STRUCTURAL", decision, production_actual)


def _identical_text_reads() -> dict[str, tuple[str, ...]]:
    """The reads mapping shared by the LOCATOR/TEMPORAL/METADATA cases:
    `channel_cases.referential_case`/`temporal_case`/`descriptive_case` all
    build byte-identical before/after text (`markdown(BODY_ALPHA, BODY_BETA)`
    on both sides), varying only the field their channel is about.
    """
    before_doc = cc.document(cc.markdown(cc.BODY_ALPHA, cc.BODY_BETA), "v1")
    after_doc = cc.document(cc.markdown(cc.BODY_ALPHA, cc.BODY_BETA), "v2")
    before_deps, _ = engine.inventory_and_dependencies(before_doc)
    after_deps, _ = engine.inventory_and_dependencies(after_doc)
    return dc.merged_reads(before_deps, after_deps)


def evaluate_locator() -> E9Result:
    case = cc.referential_case()
    reads = _identical_text_reads()
    assert case.target_artifact in reads, (
        "reconstructed fixture does not match channel_cases.referential_case's document pair"
    )
    changed = [c for c in case.diff.changes if c.channel.value == "locator"]
    assert changed, "fixture did not produce a LOCATOR change"
    decision = dc.decide_unit_change(changed[0], graph_reads=reads)
    production_actual = frozenset(case.plan.to_rebuild)
    return _finish("LOCATOR", "REFERENTIAL", decision, production_actual)


def evaluate_temporal() -> E9Result:
    case = cc.temporal_case()
    reads = _identical_text_reads()
    assert case.target_artifact in reads, (
        "reconstructed fixture does not match channel_cases.temporal_case's document pair"
    )
    changed = [c for c in case.diff.changes if c.channel.value == "temporal"]
    assert changed, "fixture did not produce a TEMPORAL change"
    decision = dc.decide_unit_change(changed[0], graph_reads=reads)
    production_actual = frozenset(case.plan.to_rebuild)
    return _finish("TEMPORAL", "TEMPORAL", decision, production_actual)


def evaluate_metadata() -> E9Result:
    case = cc.descriptive_case()
    reads = _identical_text_reads()
    assert case.target_artifact in reads, (
        "reconstructed fixture does not match channel_cases.descriptive_case's document pair"
    )
    changed = [c for c in case.diff.changes if c.channel.value == "metadata"]
    assert changed, "fixture did not produce a METADATA change"
    decision = dc.decide_unit_change(changed[0], graph_reads=reads)
    production_actual = frozenset(case.plan.to_rebuild)
    return _finish("METADATA", "DESCRIPTIVE", decision, production_actual)


def run_all() -> tuple[E9Result, ...]:
    """The five-channel matrix: SEMANTIC and STRUCTURAL (already supported in
    production) alongside LOCATOR, TEMPORAL and METADATA (this contract's
    subject). GRAPH and VISUAL are out of INC-V2-038's scope and are not
    exercised here -- see `dependency_contract`'s module docstring.
    """
    return (
        evaluate_semantic(),
        evaluate_structural(),
        evaluate_locator(),
        evaluate_temporal(),
        evaluate_metadata(),
    )
