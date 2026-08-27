"""Unit-level counterparts to the P0c and P3b gates.

A gate is measured over a corpus and can pass for the wrong reason. These pin
the behaviour itself, including the two cases the gates exist to catch: an
unattributable input access, and a refusal produced by an exception.
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
sys.path.insert(0, str(NS / "facets"))
sys.path.insert(0, str(NS / "compiler"))
sys.path.insert(0, str(NS / "activation"))
sys.path.insert(0, str(NS / "tools"))

import selective_build_p0c as engine  # noqa: E402
from facet_coverage import (  # noqa: E402
    LEXICAL,
    SEMANTIC,
    STRUCTURAL,
    UNCLASSIFIED,
    CoverageRecorder,
    change_facets,
    covered_fields,
    project,
    projections_identical,
)
from knowledge_store_p3b import (  # noqa: E402
    ARTIFACTS,
    DEFAULT_PREDICATES,
    FAIL,
    INPUTS,
    PASS,
    UNVERIFIABLE,
    Candidate,
    GateResult,
    KnowledgeStore,
    RefusalEvent,
    RefusalWithoutEvidence,
    evaluate,
    resolve_domain,
)


def unit(path: list[str], text: str, ordinal: int = 0, **extra: object) -> dict:
    return {
        "explicit_path": path,
        "heading": path[-1],
        "ordinal": ordinal,
        "text": text,
        "text_sha256": "sha256:unused",
        **extra,
    }


def document(units: list[dict], source_digest: str = "sha256:aa") -> dict:
    return {
        "schema": "tavonel.v2.canonical_document.v1",
        "source_family": "git_docs",
        "source_id": "test:doc",
        "version_id": "v",
        "version_time": {"valid_from": None, "known_at": None},
        "source_digest": source_digest,
        "license": "test",
        "units": units,
        "structure": {
            "order": ["/".join(item["explicit_path"]) for item in units],
            "block_count": len(units),
        },
    }


# --- the projection map is the whole contract -------------------------------


def test_structural_projection_is_a_function_of_heading() -> None:
    """P0b's was not, which is what made a heading read unattributable."""
    before = unit(["A"], "body", 0)
    after = {**before, "heading": "A renamed"}
    assert project(STRUCTURAL, before) != project(STRUCTURAL, after)
    assert change_facets(before, after) == (STRUCTURAL,)


def test_a_field_absent_from_the_map_is_unclassified_by_construction() -> None:
    assert "unmapped_probe_field" not in covered_fields()


# --- attribution ------------------------------------------------------------


def test_an_unmapped_read_is_recorded_and_disqualifies_the_artifact() -> None:
    recorder = CoverageRecorder()
    view = recorder.view(unit(["A"], "body", 0, unmapped_probe_field="x"))
    assert view.unmapped_probe_field == "x"  # returns the value, does not raise
    assert UNCLASSIFIED in recorder.sensitivity
    assert recorder.unclassified_fields == ("unmapped_probe_field",)
    assert recorder.coverage_proven is False


def test_a_mapped_read_proves_coverage() -> None:
    recorder = CoverageRecorder()
    view = recorder.view(unit(["A"], "body"))
    _ = view.text, view.heading
    assert recorder.sensitivity == (LEXICAL, STRUCTURAL)
    assert recorder.coverage_proven is True


def test_a_builder_that_read_nothing_has_not_proven_coverage() -> None:
    """Not looking is not the same as being insensitive."""
    assert CoverageRecorder().coverage_proven is False


def test_a_missing_attribute_still_raises() -> None:
    recorder = CoverageRecorder()
    with pytest.raises(AttributeError):
        _ = recorder.view(unit(["A"], "body")).not_a_field_at_all


# --- the carry-forward ban --------------------------------------------------


def test_an_unclassified_artifact_is_never_carried() -> None:
    units = [unit(["Intro"], "some body text", 0, unmapped_probe_field="p")]
    before = document(units)
    after = document([dict(item) for item in units])
    result = engine.run_pair(before, after)

    probes = [name for name in result["artifact_inventory"] if name.startswith("coverage-probe:")]
    assert probes, "the probe artifact must exist when the field is present"
    for name in probes:
        assert name not in result["carried_forward_set"]
        assert name in result["unverifiable_set"]
        assert result["state"][name] == "UNVERIFIABLE_UNCLASSIFIED_INPUT"


def test_production_artifacts_still_carry_when_nothing_moved() -> None:
    units = [unit(["Intro"], "some body text", 0), unit(["Body"], "more text", 1)]
    result = engine.run_pair(document(units), document([dict(x) for x in units]))
    assert result["carried_forward_set"]
    assert not result["coverage_unproven_set"]


# --- UNCLASSIFIED_SOURCE_CHANGE ---------------------------------------------


def test_diagnostic_fires_when_only_the_source_digest_moved() -> None:
    units = [unit(["Intro"], "some body text", 0)]
    result = engine.run_pair(
        document(units, "sha256:aa"), document([dict(x) for x in units], "sha256:bb")
    )
    diagnostic = result["unclassified_source_change"]
    assert diagnostic["fires"]
    # and it does not become a global rebuild
    assert result["proven_coverage_rebuild_set"] == []


def test_diagnostic_does_not_fire_when_the_digest_is_unchanged() -> None:
    units = [unit(["Intro"], "some body text", 0)]
    result = engine.run_pair(document(units), document([dict(x) for x in units]))
    assert not result["unclassified_source_change"]["fires"]


def test_diagnostic_does_not_fire_when_a_projection_moved() -> None:
    before = document([unit(["Intro"], "some body text", 0)], "sha256:aa")
    after = document([unit(["Intro"], "different body text", 0)], "sha256:bb")
    assert not engine.run_pair(before, after)["unclassified_source_change"]["fires"]


def test_projections_identical_is_false_when_unit_sets_differ() -> None:
    left = {"u1": unit(["A"], "x")}
    right = {"u1": unit(["A"], "x"), "u2": unit(["B"], "y")}
    assert not projections_identical(left, right)


# --- P0c oracle parity ------------------------------------------------------


def test_p0c_oracle_semantic_projection_matches_the_named_implementation() -> None:
    import importlib.util

    from akc_cir.identity import normalize_text_for_identity

    spec = importlib.util.spec_from_file_location(
        "oracle_probe_p0c", NS / "oracle" / "independent_full_build_p0c.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for sample in ("The Quick, Brown Fox!", "  pad  ", "full-width ＡＢＣ", "MiXeD"):
        assert module.semantic_projection(sample) == normalize_text_for_identity(sample)


def test_no_fuzzy_identity_symbol_is_imported_by_the_p0c_engine() -> None:
    tree = ast.parse((NS / "compiler" / "selective_build_p0c.py").read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            imported.update(alias.name for alias in node.names)
    for symbol in ("diff_documents", "assign_one_to_one", "LogicalIdentityResolver"):
        assert symbol not in imported


# --- P3b: refusals are legible ----------------------------------------------


def healthy() -> Candidate:
    state = {"section:u1": "sha256:aa", "section:u2": "sha256:bb"}
    return Candidate(
        candidate_id="c1",
        state=state,
        sensitivity={key: [LEXICAL] for key in state},
        fingerprints={key: "fp:" + key for key in state},
        receipts={key: {"output_digest": value} for key, value in state.items()},
        declared_inputs=("u1", "u2"),
        present_inputs=("u1", "u2"),
        authorised_units=frozenset({"u1", "u2"}),
        reachable_units=frozenset({"u1", "u2"}),
    )


def boom(_: Candidate) -> GateResult:
    raise RuntimeError("SENSITIVE-FRAGMENT token=abc123")


def test_a_raising_predicate_still_produces_evidence() -> None:
    results, event = evaluate(healthy(), (("raising", boom, ARTIFACTS),))
    outcome = results[0]
    assert outcome.state == UNVERIFIABLE
    assert outcome.reason_code == "PREDICATE_RAISED:RuntimeError"
    assert outcome.evidence_refs
    assert outcome.evaluation_id == event
    assert outcome.candidate_state_id == "c1"


def test_no_exception_text_reaches_the_refusal_record() -> None:
    store = KnowledgeStore("s0", {"artifact:genesis": "sha256:00"})
    verdict = store.publish(
        healthy(), predicates=(("raising", boom, ARTIFACTS),), expected_active="s0"
    )
    blob = json.dumps(verdict.refusal.as_record(), ensure_ascii=False)
    for token in ("SENSITIVE-FRAGMENT", "token=abc123", "Traceback"):
        assert token not in blob


def test_a_raising_predicate_with_an_empty_domain_still_names_something() -> None:
    empty = Candidate("c-empty", {}, {}, {}, {}, (), ())
    results, _ = evaluate(empty, (("raising", boom, INPUTS),))
    assert results[0].evidence_refs
    assert "c-empty" in results[0].evidence_refs[0]


def test_the_reason_code_does_not_depend_on_the_message() -> None:
    def other(_: Candidate) -> GateResult:
        raise RuntimeError("an entirely different message")

    left, _ = evaluate(healthy(), (("raising", boom, ARTIFACTS),))
    right, _ = evaluate(healthy(), (("raising", other, ARTIFACTS),))
    assert left[0].reason_code == right[0].reason_code


def test_an_evidence_free_refusal_cannot_be_constructed() -> None:
    with pytest.raises(RefusalWithoutEvidence):
        RefusalEvent("c", "sensitivity_recorded", UNVERIFIABLE, (), "R", "s0", "e", "c", "d")


def test_the_pointer_predicate_is_exempt_and_only_it() -> None:
    event = RefusalEvent(
        "c", "pointer_compare_and_swap", FAIL, (), "R", "s0", "e", "c", "d"
    )
    assert event.predicate == "pointer_compare_and_swap"


def test_the_evidence_cap_states_its_own_overflow() -> None:
    many = {"section:u%02d" % index: "sha256:aa" for index in range(20)}
    candidate = Candidate("c", many, {}, {}, {}, (), ())
    refs = resolve_domain(candidate, ARTIFACTS)
    assert len(refs) == 9
    assert "more of 20" in refs[-1]


def test_a_refusal_carries_the_state_digest_it_refused() -> None:
    store = KnowledgeStore("s0", {"artifact:genesis": "sha256:00"})
    broken = Candidate(
        "c-broken",
        {"section:u1": "sha256:aa"},
        {"section:u1": []},
        {"section:u1": "fp"},
        {"section:u1": {"output_digest": "sha256:aa"}},
        ("u1",),
        ("u1",),
        frozenset({"u1"}),
        frozenset({"u1"}),
    )
    verdict = store.publish(broken, expected_active="s0")
    assert not verdict.admitted
    assert verdict.refusal.candidate_state_digest == broken.state_digest
    assert store.active_reference == "s0"


def test_the_healthy_candidate_still_admits() -> None:
    store = KnowledgeStore("s0", {"artifact:genesis": "sha256:00"})
    verdict = store.publish(healthy(), expected_active="s0")
    assert verdict.admitted
    assert all(item.state == PASS for item in verdict.results)
    assert {name for name, _, _ in DEFAULT_PREDICATES} == {
        item.predicate for item in verdict.results
    }
