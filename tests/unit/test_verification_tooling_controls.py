"""The verification tooling has to fail when it should, and these run in CI.

Every tool added on 2026-08-19 carries a positive control that executes inside
its own run and is written into its receipt. That is the right place for it --- a
receipt whose control did not separate is not citable --- but it is not a test.
It runs only when someone runs the tool, it is not collected by pytest, and CI
never sees it. Three detectors shipped this programme that could not fire, and
each was caught by hand rather than by the suite.

So each detecting path below is exercised together with its failure path: the
input that must produce a finding, and the near-identical input that must not.
Where a tool already computes a control, the control is asserted rather than
re-implemented --- reimplementing it here would test a copy.

The tools are scripts rather than package modules, so they are loaded by path.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load(relative: str, name: str) -> Any:
    path = ROOT / relative
    if not path.exists():
        pytest.skip(f"{relative} is not present")
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def assertions() -> Any:
    return load("tools/ip/audit_assertion_registry.py", "t_assertion_registry")


@pytest.fixture(scope="module")
def coverage() -> Any:
    return load("tools/ip/audit_amendment_coverage.py", "t_amendment_coverage")


@pytest.fixture(scope="module")
def elements() -> Any:
    return load("tools/ip/build_element_support_matrix.py", "t_element_support")


@pytest.fixture(scope="module")
def rounds() -> Any:
    return load("tools/audit/run_convergence_round.py", "t_convergence_round")


@pytest.fixture(scope="module")
def triage() -> Any:
    return load("tools/repro/triage_full_suite.py", "t_triage_full_suite")


# --------------------------------------------------------------------------
# assertion registry: leaks, exemptions, presence, partial statements
# --------------------------------------------------------------------------

WITHDRAWN = {
    "id": "ASSERT_TEST",
    "status": "WITHDRAWN",
    "evidence_class": "NOT_MEASURED",
    "forbidden_wording": ["quorum-certified rollback"],
    "must_appear_in": [],
}


def test_withdrawn_wording_left_in_a_surface_is_a_finding(assertions: Any) -> None:
    found = assertions.scan(WITHDRAWN, {"s": "The system performs quorum-certified rollback.\n"})
    assert len(found) == 1
    assert found[0]["kind"] == "ASSERTION_LEAK"


def test_absent_wording_is_not_a_finding(assertions: Any) -> None:
    assert assertions.scan(WITHDRAWN, {"s": "The system performs an ordinary publish.\n"}) == []


def test_wording_inside_a_prohibition_is_exempt(assertions: Any) -> None:
    surface = {"s": "This disclosure must not recite quorum-certified rollback.\n"}
    assert assertions.scan(WITHDRAWN, surface) == []


def test_negated_mention_is_exempt_but_the_label_used_as_a_heading_is_not(
    assertions: Any,
) -> None:
    """Mention versus use, which a block-level exemption cannot separate."""
    mention = {"s": "The audit establishes single-event activation, not quorum-certified "
                    "rollback.\n"}
    use = {"s": "Section 4. Quorum-certified rollback contract\n"}
    assert assertions.scan(WITHDRAWN, mention) == []
    assert len(assertions.scan(WITHDRAWN, use)) == 1


def test_hyphenated_identifier_is_not_read_as_an_assertion(assertions: Any) -> None:
    """`B-ATOMIC-PROMOTION-CONTRACT` names the audit that disproved the broad reading."""
    withdrawn = {**WITHDRAWN, "forbidden_wording": ["atomic[ -]+promot"]}
    identifier = {"s": "Evidence: `B-ATOMIC-PROMOTION-CONTRACT` over 49 tests.\n"}
    plain = {"s": "Section 4. Atomic promotion contract\n"}
    assert assertions.scan(withdrawn, identifier) == []
    assert len(assertions.scan(withdrawn, plain)) == 1


def test_a_mermaid_fence_does_not_silence_the_rest_of_the_file(assertions: Any) -> None:
    """Backtick parity counted across a block made every diagram node read as code."""
    withdrawn = {**WITHDRAWN, "forbidden_wording": ["atomic activation"]}
    surface = {"s": '```mermaid\ngraph TD\n  ACT["Atomic activation"]\n  B["x"]\n```\n'}
    assert len(assertions.scan(withdrawn, surface)) == 1


def test_a_table_rows_disclaimer_does_not_exempt_the_other_rows(assertions: Any) -> None:
    withdrawn = {**WITHDRAWN, "forbidden_wording": ["quorum-certified rollback"]}
    table = {"s": "| a | may not be recited as independently necessary |\n"
                  "| b | quorum-certified rollback contract |\n"}
    assert len(assertions.scan(withdrawn, table)) == 1


ACTIVE = {
    "id": "ASSERT_PRESENT",
    "status": "ACTIVE",
    "evidence_class": "MEASURED",
    "forbidden_wording": [],
    "must_appear_in": ["s"],
    "appears_as": ["invariant to evaluation order"],
}


def test_active_assertion_missing_from_a_declared_surface_is_a_finding(
    assertions: Any,
) -> None:
    found = assertions.scan(ACTIVE, {"s": "Nothing relevant here.\n"})
    assert len(found) == 1
    assert found[0]["kind"] == "ASSERTION_MISSING"


def test_presence_survives_markdown_hard_wrapping(assertions: Any) -> None:
    """The phrase spans three lines in the claim set; a literal search missed it."""
    wrapped = {"s": "predicates whose acceptance result is invariant\n   to evaluation\n   order\n"}
    assert assertions.scan(ACTIVE, wrapped) == []


def test_narrowed_assertion_must_also_be_present(assertions: Any) -> None:
    """A narrowed assertion still stands; absent, it was lost rather than narrowed."""
    narrowed = {**ACTIVE, "status": "NARROWED", "narrowed_from": "x"}
    assert len(assertions.scan(narrowed, {"s": "Nothing relevant.\n"})) == 1


PARTIAL = {
    "id": "ASSERT_PARTIAL",
    "status": "NARROWED",
    "narrowed_from": "x",
    "evidence_class": "MEASURED",
    "forbidden_wording": [],
    "must_appear_in": [],
    "partial_forms": [
        {"partial": "path-dependent",
         "completed_by": "classification flip|forks lineage",
         "why": "half the narrowing"},
    ],
}


def test_stating_half_a_narrowing_is_a_finding(assertions: Any) -> None:
    found = assertions.scan(PARTIAL, {"s": "The residual assignments were path-dependent.\n"})
    assert len(found) == 1
    assert found[0]["kind"] == "ASSERTION_STATED_IN_PART"


def test_stating_the_whole_narrowing_is_not(assertions: Any) -> None:
    whole = {"s": "The residual divergences were path-dependent, each a classification flip.\n"}
    assert assertions.scan(PARTIAL, whole) == []


def test_registry_controls_separate_in_the_shipped_registry(assertions: Any) -> None:
    """Assert the tool's own controls rather than reimplementing them."""
    import yaml

    registry = ROOT / "docs/ip/ASSERTION_REGISTRY.yaml"
    if not registry.exists():
        pytest.skip("assertion registry is not present")
    declared = (yaml.safe_load(registry.read_text(encoding="utf-8")) or {}).get("assertions") or []
    assert assertions.withdrawal_propagation_control()["separates"] is True
    assert assertions.historical_wording_control(declared)["separates"] is True
    assert assertions.partial_form_control(declared)["separates"] is True


# --------------------------------------------------------------------------
# amendment coverage: the claim-set hash chain
# --------------------------------------------------------------------------


def test_hash_chain_separates_its_three_states(coverage: Any) -> None:
    digest = "sha256:" + "a" * 64
    other = "sha256:" + "b" * 64
    assert coverage.chain_state(digest, digest) == "INTACT"
    assert coverage.chain_state(other, digest) == "BROKEN"
    assert coverage.chain_state(None, digest) == "NO_BASELINE"


def test_hash_chain_control_reports_separation(coverage: Any) -> None:
    assert coverage.chain_control("sha256:" + "c" * 64)["separates"] is True


def test_amendment_targeting_an_unknown_claim_is_caught(coverage: Any) -> None:
    control = coverage.self_control({"B1", "B6"}, {})
    assert control["separates"] is True
    assert control["unknown_target_caught"] is True
    assert control["known_target_passed"] is True


def test_claim_inventory_reads_headings_not_prose(coverage: Any) -> None:
    text = (
        "### Claim A1 (independent, method)\n\nbody\n\n"
        "### Claim A3 (dependent) - RESERVED, NOT SUPPORTED\n\nbody\n"
    )
    inventory = coverage.claim_inventory(text)
    assert [c["id"] for c in inventory] == ["A1", "A3"]
    assert inventory[0]["kind"] == "independent"
    assert inventory[1]["reserved"] is True


# --------------------------------------------------------------------------
# element support: an incomplete binding is not a binding
# --------------------------------------------------------------------------


def test_evidence_block_bullets_are_parsed_per_element(elements: Any) -> None:
    block = (
        "1. a;\n2. b;\n\n**Evidence:**\n"
        "- elements 1, 2: `B-EQUIV-FRESH-HOLDOUT` - controlled\n"
    )
    per_element, unscoped = elements.parse_support(block)
    assert sorted(per_element) == [1, 2]
    assert unscoped == []


def test_a_wrapped_bullet_keeps_both_identifiers_on_the_same_elements(
    elements: Any,
) -> None:
    """Reading line by line stranded the second id as unscoped."""
    block = (
        "1. a;\n\n**Evidence:**\n"
        "- elements 1: `B-PROMOTION-GATE-STALE-BLOCK`, and\n"
        "  `B-ATOMIC-PROMOTION-CONTRACT` - a sealed audit\n"
    )
    per_element, unscoped = elements.parse_support(block)
    assert per_element[1] == [
        "B-PROMOTION-GATE-STALE-BLOCK",
        "B-ATOMIC-PROMOTION-CONTRACT",
    ]
    assert unscoped == []


def test_a_bare_uppercase_code_literal_is_not_read_as_a_citation(elements: Any) -> None:
    """`AMBIGUOUS` is a classification value the claim recites, not evidence."""
    block = "1. a;\n\n**Evidence:**\n- elements 1: `AMBIGUOUS` handling, `H1-K` reproduced it\n"
    per_element, _ = elements.parse_support(block)
    assert "AMBIGUOUS" not in per_element[1]
    assert "H1-K" in per_element[1]


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda row: row.pop("limitation"), "BINDING_INCOMPLETE"),
        (lambda row: row.update(support="TOTALLY_FINE"), "BINDING_BAD_SUPPORT_STATE"),
        (lambda row: row.update(implementation="packages/does-not-exist.py"),
         "BINDING_IMPLEMENTATION_PATH_ABSENT"),
        (lambda row: row.update(evidence="research/experiments/DOES-NOT-EXIST"),
         "BINDING_EVIDENCE_PATH_ABSENT"),
        (lambda row: row.update(support="ELEMENT_BOUND", evidence=None),
         "BINDING_CLAIMS_ELEMENT_BOUND_WITHOUT_EVIDENCE"),
    ],
)
def test_a_defective_binding_is_rejected_rather_than_counted(
    elements: Any, tmp_path: Path, mutate: Any, expected: str
) -> None:
    import copy

    import yaml

    source = ROOT / "docs/ip/ELEMENT_SUPPORT_BINDINGS.yaml"
    if not source.exists():
        pytest.skip("element support bindings are not present")
    row = copy.deepcopy((yaml.safe_load(source.read_text(encoding="utf-8")))["bindings"][0])
    mutate(row)
    probe = tmp_path / "bindings.yaml"
    probe.write_text(yaml.safe_dump({"bindings": [row]}, allow_unicode=True), encoding="utf-8")

    original = elements.BINDINGS
    elements.BINDINGS = probe
    try:
        accepted, problems = elements.load_bindings()
    finally:
        elements.BINDINGS = original

    assert accepted == {}
    assert [p["kind"] for p in problems] == [expected]


def test_the_shipped_bindings_all_validate(elements: Any) -> None:
    accepted, problems = elements.load_bindings()
    assert problems == []
    assert accepted, "expected at least one element-level binding on file"


# --------------------------------------------------------------------------
# convergence: standing bounds must not become a way to retire findings
# --------------------------------------------------------------------------


def test_an_undeclared_finding_stays_open(rounds: Any) -> None:
    open_actionable, standing, rejected, deferred = rounds.classify_findings(
        [{"kind": "SOMETHING_NEW"}], {}
    )
    assert len(open_actionable) == 1
    assert standing == []
    assert rejected == []
    assert deferred == []


def test_a_declaration_missing_a_condition_does_not_confer_bound_status(
    rounds: Any,
) -> None:
    bounds = {
        "KIND": {"id": "SB-X", "matches_finding_kind": "KIND", "admitted": False,
                 "missing_conditions": ["hash_chain_prevents_recurrence"]},
    }
    open_actionable, standing, rejected, deferred = rounds.classify_findings(
        [{"kind": "KIND"}], bounds
    )
    assert len(open_actionable) == 1
    assert standing == []
    assert len(rejected) == 1
    assert deferred == []


def test_a_fully_attested_declaration_becomes_a_bound(rounds: Any) -> None:
    bounds = {"KIND": {"id": "SB-X", "matches_finding_kind": "KIND", "admitted": True,
                       "missing_conditions": []}}
    open_actionable, standing, _, deferred = rounds.classify_findings(
        [{"kind": "KIND"}], bounds
    )
    assert open_actionable == []
    assert len(standing) == 1
    assert deferred == []


# --------------------------------------------------------------------------
# convergence amendment 3: deferral needs BOTH markers, or it is a second way
# to retire a finding by writing one field
# --------------------------------------------------------------------------


def test_the_reserved_severity_alone_does_not_defer_a_finding(rounds: Any) -> None:
    open_actionable, _, _, deferred = rounds.classify_findings(
        [{"kind": "K", "severity": rounds.DEFERRED_SEVERITY}], {}
    )
    assert len(open_actionable) == 1, (
        "a severity string alone deferred a finding; the generator's stamp must be "
        "corroborated by the claim actually being reserved"
    )
    assert deferred == []


def test_the_reserved_flag_alone_does_not_defer_a_finding(rounds: Any) -> None:
    open_actionable, _, _, deferred = rounds.classify_findings(
        [{"kind": "K", "reserved": True}], {}
    )
    assert len(open_actionable) == 1, (
        "the reserved flag alone deferred a finding; every finding on a reserved claim "
        "would then be deferred, including a real one"
    )
    assert deferred == []


def test_both_markers_together_defer(rounds: Any) -> None:
    open_actionable, standing, _, deferred = rounds.classify_findings(
        [{"kind": "K", "severity": rounds.DEFERRED_SEVERITY, "reserved": True}], {}
    )
    assert open_actionable == []
    assert standing == [], "a deferral is not a standing bound and must not be counted as one"
    assert len(deferred) == 1


def test_a_declared_standing_bound_wins_over_deferral(rounds: Any) -> None:
    """Order matters: a bound is the stronger declaration and is checked first."""
    bounds = {"K": {"id": "SB-X", "matches_finding_kind": "K", "admitted": True,
                    "missing_conditions": []}}
    _, standing, _, deferred = rounds.classify_findings(
        [{"kind": "K", "severity": rounds.DEFERRED_SEVERITY, "reserved": True}], bounds
    )
    assert len(standing) == 1
    assert deferred == []


def test_the_runner_control_reports_the_deferral_probes(rounds: Any) -> None:
    """The mechanism's own control must carry the three deferral probes, not assert them."""
    control = rounds.bounds_control({})
    probe = control["deferral_control"]
    assert probe["severity_without_reserved_flag_stays_open"] is True
    assert probe["reserved_flag_without_severity_stays_open"] is True
    assert probe["both_markers_defer"] is True
    assert probe["separates"] is True
    assert control["separates"] is True


def test_loader_refuses_a_declaration_with_any_condition_unattested(
    rounds: Any, tmp_path: Path
) -> None:
    import yaml

    entry: dict[str, Any] = {
        "id": "SB-PROBE",
        "matches_finding_kind": "PROBE_KIND",
        "conditions": {c: {"attested_by": "x"} for c in rounds.REQUIRED_CONDITIONS},
    }
    probe = tmp_path / "bounds.yaml"

    probe.write_text(yaml.safe_dump({"standing_bounds": [entry]}), encoding="utf-8")
    original = rounds.BOUNDS
    rounds.BOUNDS = probe
    try:
        assert rounds.load_bounds()["PROBE_KIND"]["admitted"] is True

        holed = {**entry, "conditions": dict(entry["conditions"])}
        holed["conditions"].pop("never_counted_as_fixed")
        probe.write_text(yaml.safe_dump({"standing_bounds": [holed]}), encoding="utf-8")
        loaded = rounds.load_bounds()["PROBE_KIND"]
        assert loaded["admitted"] is False
        assert loaded["missing_conditions"] == ["never_counted_as_fixed"]
    finally:
        rounds.BOUNDS = original


def test_the_shipped_bounds_registry_control_separates(rounds: Any) -> None:
    assert rounds.bounds_control(rounds.load_bounds())["separates"] is True


# --------------------------------------------------------------------------
# full-suite triage: clustering, and the refusal to call a red run green
# --------------------------------------------------------------------------

CLEAN_RUN = "collected 2790 items\n2758 passed, 32 skipped in 700.00s\n"
FAILING_RUN = (
    "collected 2790 items\n"
    r"D:\repo\tests\unit\test_probe.py:12: assert 0 == 1" + "\n"
    "FAILED tests/unit/test_probe.py::test_probe\n"
    "1 failed, 2757 passed, 32 skipped in 700.00s\n"
)


def test_summary_counts_are_read_from_the_run_not_assumed(triage: Any) -> None:
    parsed = triage.parse_text(CLEAN_RUN, "<probe>")
    assert (parsed["collected"], parsed["passed"], parsed["failed"], parsed["skipped"]) == (
        2790, 2758, 0, 32
    )


def test_a_failure_the_environment_does_not_explain_opens_an_unknown_cluster(
    triage: Any,
) -> None:
    result = triage.classify(
        triage.parse_text(CLEAN_RUN, "<global>"),
        triage.parse_text(FAILING_RUN, "<venv>"),
    )
    assert result["repository_green_allowed"] is False
    assert len(result["unknown"]) == 1
    assert result["unknown"][0]["category"] == "H"


def test_a_clean_run_permits_the_green_verdict(triage: Any) -> None:
    result = triage.classify(
        triage.parse_text(CLEAN_RUN, "<global>"),
        triage.parse_text(CLEAN_RUN, "<venv>"),
    )
    assert result["unknown"] == []
    assert result["repository_green_allowed"] is True


def test_failures_resolved_by_the_interpreter_form_one_cluster_not_many(
    triage: Any,
) -> None:
    """24 assertions with one cause is one defect wearing 24 costumes."""
    shapes = [
        "assert 'queued' == 'completed'",
        "IndexError: list index out of range",
        "assert None is not None",
    ]
    body = "collected 100 items\n"
    for i, shape in enumerate(shapes):
        body += f"D:\\repo\\tests\\unit\\test_{i}.py:{i + 1}: {shape}\n"
    for i in range(len(shapes)):
        body += f"FAILED tests/unit/test_{i}.py::test_{i}\n"
    body += f"{len(shapes)} failed, 90 passed, 7 skipped in 10.00s\n"

    result = triage.classify(
        triage.parse_text(body, "<global>"),
        triage.parse_text(CLEAN_RUN, "<venv>"),
    )
    assert len(result["clusters"]) == 1
    cluster = result["clusters"][0]
    assert cluster["category"] == "D"
    assert cluster["test_count"] == len(shapes)
    assert len(cluster["distinct_assertion_shapes"]) == len(shapes)


def test_triage_detector_control_separates(triage: Any) -> None:
    assert triage.self_control(triage.parse_text(CLEAN_RUN, "<global>"))["separates"] is True
