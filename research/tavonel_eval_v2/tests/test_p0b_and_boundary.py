"""Regression tests for the P0b mechanism and the publication boundary.

Unit-level counterparts to the gates in the frozen protocols. A gate is measured
over a corpus and can pass for the wrong reason; these pin the behaviour itself.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]

sys.path.insert(0, str(ROOT / "packages" / "cir-python" / "src"))
sys.path.insert(0, str(NS / "facets"))
sys.path.insert(0, str(NS / "compiler"))
sys.path.insert(0, str(NS / "activation"))

import selective_build_p0b as engine  # noqa: E402
from akc_cir.identity import normalize_text_for_identity  # noqa: E402
from facets import LEXICAL, SEMANTIC, STRUCTURAL, Recorder, change_facets  # noqa: E402
from knowledge_store import (  # noqa: E402
    DEFAULT_PREDICATES,
    NOT_REACHED,
    PASS,
    UNVERIFIABLE,
    Candidate,
    GateResult,
    KnowledgeStore,
    admits,
    evaluate,
)


def unit(path: list[str], text: str, ordinal: int = 0) -> dict:
    return {
        "explicit_path": path,
        "heading": path[-1],
        "ordinal": ordinal,
        "text": text,
        "text_sha256": "sha256:unused",
    }


def document(units: list[dict], source_id: str = "test:doc") -> dict:
    return {
        "schema": "tavonel.v2.canonical_document.v1",
        "source_family": "git_docs",
        "source_id": source_id,
        "version_id": "v",
        "version_time": {"valid_from": None, "known_at": None},
        "source_digest": "sha256:" + "%064x" % (abs(hash(json.dumps(units))) % (16**64)),
        "license": "test",
        "units": units,
        "structure": {
            "order": ["/".join(item["explicit_path"]) for item in units],
            "block_count": len(units),
        },
    }


# --- facets -----------------------------------------------------------------


def test_case_only_change_moves_lexical_and_not_semantic() -> None:
    before = unit(["A"], "the quick brown fox jumps over the lazy dog")
    after = unit(["A"], "The Quick Brown Fox jumps over the lazy dog")
    assert change_facets(before, after) == (LEXICAL,)


def test_rewrite_moves_both_lexical_and_semantic() -> None:
    before = unit(["A"], "the quick brown fox")
    after = unit(["A"], "a slow grey badger")
    moved = change_facets(before, after)
    assert LEXICAL in moved and SEMANTIC in moved


def test_reorder_moves_structural_only() -> None:
    before = unit(["A"], "identical body text", ordinal=0)
    after = unit(["A"], "identical body text", ordinal=3)
    assert change_facets(before, after) == (STRUCTURAL,)


# --- sensitivity is observed, not declared ----------------------------------


def test_section_builder_records_only_lexical() -> None:
    recorder = Recorder()
    engine.build_section("u:x", recorder.view(unit(["A"], "body")))
    assert recorder.sensitivity == (LEXICAL,)


def test_semantic_summary_builder_records_only_semantic() -> None:
    recorder = Recorder()
    engine.build_semantic_summary("u:x", recorder.view(unit(["A"], "body")))
    assert recorder.sensitivity == (SEMANTIC,)


def test_structure_map_builder_records_only_structural() -> None:
    recorder = Recorder()
    views = [("u:x", recorder.view(unit(["A"], "body", 0)))]
    engine.build_structure_map("key", views)
    assert recorder.sensitivity == (STRUCTURAL,)


# --- the INC-V2-002 case, at unit level -------------------------------------


def test_case_only_edit_rebuilds_raw_artifact_and_carries_the_semantic_one() -> None:
    body = "we know the contents at compile time, so the text is hard coded"
    before = document([unit(["Intro"], body, 0), unit(["Body"], "a second section body", 1)])
    after = document(
        [unit(["Intro"], body.capitalize(), 0), unit(["Body"], "a second section body", 1)]
    )
    result = engine.run_pair(before, after)

    rebuilt = {name.split(":")[0] for name in result["selective_rebuild_set"]}
    carried = {name.split(":")[0] for name in result["carried_forward_set"]}
    assert "section" in rebuilt
    assert "semantic-summary" in carried
    assert "semantic-summary" not in rebuilt

    # and the selective state still equals a full rebuild of the after revision
    full = {
        artifact: info["digest"] for artifact, info in engine.build_revision(after).items()
    }
    assert result["state"] == full


def test_no_identity_resolver_symbol_is_imported_by_the_p0b_engine() -> None:
    """Imports, from the syntax tree. Prose that names the symbol is not an import."""
    import ast

    tree = ast.parse((NS / "compiler" / "selective_build_p0b.py").read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    for symbol in ("diff_documents", "assign_one_to_one", "LogicalIdentityResolver"):
        assert symbol not in imported


# --- the oracle re-derives the semantic projection from prose ---------------


def test_oracle_semantic_projection_agrees_with_the_named_implementation() -> None:
    """The spec is stated in prose; this is whether the prose was enough."""
    spec = importlib.util.spec_from_file_location(
        "oracle_probe", NS / "oracle" / "independent_full_build_p0b.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    samples = [
        "The Quick, Brown Fox!",
        "  leading and trailing  ",
        "full-width ＡＢＣ and ascii ABC",
        "punctuation---heavy?? text!!",
        "MiXeD CaSe WoRdS",
    ]
    for sample in samples:
        assert module.semantic_projection(sample) == normalize_text_for_identity(sample)


# --- publication boundary ---------------------------------------------------


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


def test_admission_requires_every_declared_predicate_to_be_present() -> None:
    declared = tuple(name for name, _ in DEFAULT_PREDICATES)
    results = evaluate(healthy())
    assert admits(results, declared)
    trimmed = tuple(item for item in results if item.predicate != "source_complete")
    assert not admits(trimmed, declared), "a missing predicate must not read as satisfied"


def test_not_reached_and_unverifiable_never_admit() -> None:
    declared = ("a", "b")
    for state in (NOT_REACHED, UNVERIFIABLE):
        results = (GateResult("a", PASS), GateResult("b", state))
        assert not admits(results, declared)


def test_a_refused_candidate_leaves_the_active_reference_where_it_was() -> None:
    store = KnowledgeStore("s0", {"artifact:genesis": "sha256:00"})
    broken = Candidate(
        candidate_id="c-broken",
        state={"section:u1": "sha256:aa"},
        sensitivity={"section:u1": []},
        fingerprints={"section:u1": "fp"},
        receipts={"section:u1": {"output_digest": "sha256:aa"}},
        declared_inputs=("u1",),
        present_inputs=("u1",),
        authorised_units=frozenset({"u1"}),
        reachable_units=frozenset({"u1"}),
    )
    verdict = store.publish(broken, expected_active="s0")
    assert not verdict.admitted
    assert store.active_reference == "s0"
    assert verdict.refusal is not None
    assert verdict.refusal.state == UNVERIFIABLE
    assert verdict.refusal.evidence_refs


def test_a_stale_compare_and_swap_is_refused() -> None:
    store = KnowledgeStore("s0", {"artifact:genesis": "sha256:00"})
    assert store.publish(healthy(), expected_active="s0").admitted
    # a second candidate verified against the reference the first one replaced
    verdict = store.publish(healthy(), expected_active="s0")
    assert not verdict.admitted
    assert verdict.refusal is not None
    assert verdict.refusal.predicate == "pointer_compare_and_swap"
