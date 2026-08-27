"""Unit-level counterparts to Source Coverage Locality v2.

The witness's whole claim is that it localises *and* follows dependencies out of
the local region. Those two properties pull in opposite directions, so the tests
below pin both — an instrument that always refuses would satisfy the first alone
and an instrument that always grants would satisfy neither.

The eight development controls are also asserted directly here, not only inside
the run, so a regression in the instrument fails the suite rather than waiting
for the next protocol execution.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]

sys.path.insert(0, str(ROOT / "packages" / "cir-python" / "src"))
sys.path.insert(0, str(NS / "canonicalization"))
sys.path.insert(0, str(NS / "retrieval"))
sys.path.insert(0, str(NS / "tools"))

from coverage_witness import (  # noqa: E402
    COMPLETE,
    DIRECT,
    INCOMPLETE,
    NO_DIRECT_SPAN,
    UNMODELED_IN_CLOSURE,
    build_witness,
    witness_status,
)
from locality_fixtures import (  # noqa: E402
    FIXTURES,
    OVER_GRANT_CONTROL,
    POSITIVE_CONTROL,
    UNDER_GRANT_CONTROL,
)
from source_map import (  # noqa: E402
    LOCATION_UNVERIFIABLE,
    LOCATION_VERIFIED,
    html_located,
    located_spans,
    markdown_located,
)
from source_spans import UNMODELED, attribute_to_canonical, reference_facts  # noqa: E402

# imported at module scope, not inside the tests: ``mcnemar_power`` reaches
# ``common``, and the oracle isolation probe another test module installs on
# sys.meta_path is global to the interpreter once any test has run.
from mcnemar_power import (  # noqa: E402
    ALPHA,
    DISCORDANT_RATE,
    EFFECT,
    power,
    required_n,
)


def _evaluate(fixture: dict) -> dict:
    spans, grammar = located_spans(fixture["raw"], fixture["suffix"])
    facts = reference_facts(spans)
    targets = [str(fact.get("target") or "") for fact in facts]
    if grammar == "markdown":
        attribute_to_canonical(spans, [fixture["atom"], *fixture["members"]], targets)
    witness = build_witness(
        spans, fixture["atom"], fixture["members"], targets, raw=fixture["raw"]
    )
    return {"witness": witness, "status": witness_status(witness, spans), "spans": spans}


# --- the eight controls ------------------------------------------------------


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda f: f["name"])
def test_every_development_control_returns_its_expected_verdict(fixture: dict) -> None:
    result = _evaluate(fixture)
    assert result["status"]["status"] == fixture["expect"], (
        fixture["name"],
        fixture["guards"],
        result["status"]["reasons"],
    )


def test_the_directional_pair_disagrees_with_each_other() -> None:
    """One control alone is satisfiable by an instrument that always refuses.

    The pair is what pins both directions, so it is asserted as a pair rather
    than as two independent facts.
    """
    over = _evaluate(next(f for f in FIXTURES if f["name"] == OVER_GRANT_CONTROL))
    under = _evaluate(next(f for f in FIXTURES if f["name"] == UNDER_GRANT_CONTROL))
    assert over["status"]["status"] == INCOMPLETE
    assert under["status"]["status"] == COMPLETE


def test_the_positive_control_can_actually_be_granted() -> None:
    """If this fails the instrument cannot grant at all and every zero is empty."""
    result = _evaluate(next(f for f in FIXTURES if f["name"] == POSITIVE_CONTROL))
    assert result["status"]["status"] == COMPLETE
    assert result["status"]["reasons"] == []


# --- the two rules the controls forced ---------------------------------------


def test_a_dependency_outside_the_atoms_interval_is_still_examined() -> None:
    """The over-grant case locality v1 admitted in its own docstring it could miss."""
    result = _evaluate(next(f for f in FIXTURES if f["name"] == OVER_GRANT_CONTROL))
    assert UNMODELED_IN_CLOSURE in result["status"]["reasons"]
    roles = result["witness"]["by_role"]
    assert roles["reference_definition"] > 0, roles


def test_an_include_target_absent_from_the_source_blocks_completeness() -> None:
    """Reading the signpost is not reading the road."""
    result = _evaluate(
        next(f for f in FIXTURES if f["name"] == "include_directive_dependency")
    )
    assert result["status"]["status"] == INCOMPLETE
    kinds = [e["kind"] for e in result["witness"]["elements"]]
    assert any("UNRESOLVED_INCLUDE_TARGET" in kind for kind in kinds), kinds


def test_an_unmodeled_fact_the_atom_does_not_depend_on_is_ignored() -> None:
    """Failing here would mean the witness is not localising at all."""
    fixture = next(f for f in FIXTURES if f["name"] == UNDER_GRANT_CONTROL)
    result = _evaluate(fixture)
    assert result["status"]["status"] == COMPLETE
    assert any(span.classification == UNMODELED for span in result["spans"]), (
        "the fixture must actually contain an unmodeled fact, or it proves nothing"
    )


# --- positional provenance ---------------------------------------------------


def test_html_events_carry_real_intervals() -> None:
    raw = '<html><body><p binding="true">Records are retained.</p></body></html>'
    spans = html_located(raw)
    located = [span for span in spans if span.located]
    assert located
    for span in located:
        assert 0 <= span.start <= span.end <= len(raw)
        assert span.location_state == LOCATION_VERIFIED


def test_html_intervals_run_forward_in_reading_order() -> None:
    raw = "<a><b>one</b><c>two</c></a>"
    located = [span for span in html_located(raw) if span.located]
    starts = [span.start for span in located]
    assert starts == sorted(starts)


def test_a_span_is_either_located_with_an_interval_or_not_located_at_all() -> None:
    """No estimated positions. That is the whole honesty rule of the source map."""
    for raw in ('<p a="1">x</p>', "<p>unclosed", "<!-- x --><p attr", ""):
        for span in html_located(raw):
            if span.location_state == LOCATION_UNVERIFIABLE:
                assert span.start is None and span.end is None
            else:
                assert span.start is not None and span.end is not None


def test_an_unlocated_span_overlaps_nothing() -> None:
    from source_map import LocatedSpan  # noqa: PLC0415

    span = LocatedSpan(None, None, "x", UNMODELED, "", None, LOCATION_UNVERIFIABLE)
    assert not span.overlaps(0, 10_000)


def test_markdown_positions_are_lifted_unchanged() -> None:
    raw = "# Title\n\nSome prose.\n"
    for span in markdown_located(raw):
        assert span.location_state == LOCATION_VERIFIED
        assert raw[span.start : span.end] == span.text


def test_charref_conversion_is_off_so_positions_stay_per_event() -> None:
    """With convert_charrefs on, merged runs report the start of the merge."""
    source = (NS / "canonicalization" / "source_map.py").read_text(encoding="utf-8")
    assert "convert_charrefs=False" in source


# --- the completeness rule ---------------------------------------------------


def test_completeness_requires_a_direct_span_for_the_target() -> None:
    spans, _ = located_spans("# Heading\n\nUnrelated prose.\n", ".md")
    witness = build_witness(spans, "text that is not in this document", [], [])
    status = witness_status(witness, spans)
    assert status["status"] == INCOMPLETE
    assert NO_DIRECT_SPAN in status["reasons"]


def test_no_grant_ever_carries_an_unmodeled_element() -> None:
    for fixture in FIXTURES:
        result = _evaluate(fixture)
        if result["status"]["status"] == COMPLETE:
            assert result["status"]["unmodeled_in_closure"] == 0


# --- the sealed run ----------------------------------------------------------


def _latest_locality() -> dict:
    receipts = sorted((NS / "receipts").glob("locality-v2--*.json"))
    assert receipts, "locality v2 has no receipt"
    return json.loads(receipts[-1].read_text(encoding="utf-8"))


def test_the_run_records_every_decision_gate_number() -> None:
    body = _latest_locality()
    totals = body["totals"]
    for key in ("locally_complete", "locally_complete_q1", "q1_questions", "questions"):
        assert key in totals
    assert "locally_complete_q1_by_family" in body
    assert "witness_failures_by_reason" in body
    assert "location_unverifiable_spans" in body


def test_the_run_did_not_lower_the_floor() -> None:
    decision = _latest_locality()["decision_gate"]
    assert decision["hard_minimum_eligible_Q1"] == 190
    assert "never lowered" in decision["status_of_the_floor"]


def test_the_run_below_the_floor_asks_for_a_new_cohort_not_for_gpu() -> None:
    body = _latest_locality()
    decision = body["decision_gate"]
    if not decision["meets_floor"]:
        assert decision["outcome"] == "FREEZE_A_NEW_COHORT_ACQUISITION_PROTOCOL"
    assert body["gpu_authorised_by_this_result"] is False


def test_the_run_does_not_rescore_p4e() -> None:
    body = _latest_locality()
    assert "not_rescored" in body["p4e_not_rescored"] or "read as" in body["p4e_not_rescored"]
    assert body["comparison_to_p4e_provisional"]["p4e_provisional_locally_complete"] == 20


def test_p0d_classifier_was_not_edited_by_locality_v2() -> None:
    """A new instrument is a new module, not an edit to a sealed one."""
    tree = ast.parse((NS / "canonicalization" / "source_map.py").read_text(encoding="utf-8"))
    imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert "source_spans" in imports, "v2 builds on v1 rather than replacing it silently"


def test_locality_v2_spent_nothing() -> None:
    body = _latest_locality()
    assert body["gpu_seconds"] == 0
    assert body["estimated_cost_usd"] == 0.0


# --- power -------------------------------------------------------------------


def test_the_power_calculation_is_exact_not_approximate() -> None:
    assert (ALPHA, EFFECT, DISCORDANT_RATE) == (0.05, 0.15, 0.30)
    assert power(190) >= 0.95
    assert power(50) < power(100) < power(190)
    assert required_n() is not None and required_n() <= 190


def test_power_is_zero_at_a_handful_of_questions() -> None:
    assert power(5) == 0.0, "an exact test cannot reject at n = 5"


# --- confirmatory isolation --------------------------------------------------


def test_the_isolated_builder_imports_no_repository_module() -> None:
    from isolated_builder import isolation_evidence  # noqa: PLC0415

    evidence = isolation_evidence()
    assert evidence["passed"], evidence
    assert evidence["child_isolation"]["repository_modules_imported"] == []
    assert evidence["child_isolation"]["site_imported"] is False
    assert evidence["parent_refuses_before_serialising"]
    assert evidence["child_refuses_independently"]


def test_the_isolated_builder_agrees_with_the_in_process_one() -> None:
    from intent_view import ANCHOR, DOC_TYPE, IDENTITY, PARENT, TITLE, IntentView, build_query  # noqa: PLC0415
    from isolated_builder import build_query_isolated  # noqa: PLC0415

    fields = {
        TITLE: "uv documentation",
        IDENTITY: "astral-sh/uv",
        DOC_TYPE: "documentation",
        ANCHOR: "Dependency fields",
        PARENT: "Managing dependencies",
    }
    assert build_query_isolated(dict(fields))["query"] == build_query(
        IntentView("t", **fields)
    )
