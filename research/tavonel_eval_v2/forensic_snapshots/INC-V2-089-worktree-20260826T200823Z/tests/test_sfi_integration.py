"""The deterministic integration gate. Lane 1, run after every lane lands.

The founder's rule for this programme is `parallel implementation ->
deterministic integration -> freeze -> one fresh held-out scoring`, and this file
is the second arrow. Seven lanes were written simultaneously against one written
contract; what they cannot do individually is agree. Three cross-lane defects
have already been found here rather than by any lane's own suite:

* witness `unit_path` was document-qualified on one side and bare on the other,
  so the dependency resolver derived a document key of 040c3fd8... where the
  real key was e1f43638...  Both sides' tests passed throughout.
* `source_fact_ir` had no `__init__.py`, so package-qualified loading imported a
  submodule whose own imports then failed. The failure surfaced as "no extractor
  produces REFERENCE_TARGET" — an absence, which reads as a clean document.
* the registry refused a re-imported extractor as a rival, turning an import
  order accident into a hard failure.

The pattern in all three is the same and it is why this file exists: **a
cross-lane disagreement does not raise. It reports a clean result.** Every test
below is written to make one of those silences audible.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
for _sub in ("source_fact_ir", "canonicalization", "compiler"):
    sys.path.insert(0, str(NS / _sub))
sys.path.insert(0, str(NS))

import ir  # noqa: E402
from canonical_document import canonical_document  # noqa: E402

compile_module = pytest.importorskip("compile", reason="source_fact_ir.compile absent")

LONG = (
    "This paragraph is padded past the canonicaliser's one hundred and twenty "
    "character minimum so that it survives block assembly and becomes a unit of "
    "its own rather than being folded into a neighbour."
)


def document_for(raw: bytes, version: str = "1") -> dict:
    return canonical_document(
        source_family="git",
        source_id="git:fixture/repo:doc.md",
        version_id=version,
        payload=raw,
        source_digest="sha256:0",
        known_at=None,
        valid_from=None,
        licence="mit",
    )


def _lane(name: str):
    module = compile_module.load_lanes().get(name)
    if module is None:
        pytest.skip(f"lane {name} has not landed")
    return module


# ---------------------------------------------------------------------------
# the lanes agree that they exist


def test_the_core_lane_is_not_optional():
    """A run with no core extractor produces no content facts and scores every
    document clean, so its absence must raise rather than degrade."""
    assert compile_module.load_lanes()["core"] is not None


def test_every_kind_a_lane_owns_is_produced_or_reported_unclaimed():
    """Silence is the failure mode. An owned-but-unproduced kind must appear in
    `unclaimed_kinds`, never simply be missing from the output."""
    compile_module.load_lanes()
    produced = set(ir.registered_kinds())
    unclaimed = set(ir.unclaimed_kinds())
    assert produced | unclaimed == set(ir.KIND_CHANNEL)
    assert not produced & unclaimed


def test_both_import_styles_reach_the_same_registry():
    """The defect this catches imported a module successfully and left its
    extractor unregistered, which reads as a document with no such facts."""
    import contextlib
    import importlib

    #: `ir` is aliased into sys.modules under both names deliberately (see the
    #: foot of ir.py); these are the modules where a split would be silent.
    for name in ("core_extractor", "fingerprint", "reference", "metadata"):
        flat = None
        qualified = None
        with contextlib.suppress(ImportError):
            flat = importlib.import_module(name)
        with contextlib.suppress(ImportError):
            qualified = importlib.import_module(f"source_fact_ir.{name}")
        if flat is None and qualified is None:
            continue
        assert flat is not None and qualified is not None, (
            f"{name} imports under one style and not the other; the failing style "
            "produces no facts rather than an error"
        )


# ---------------------------------------------------------------------------
# the witness convention, which nothing else can check


def test_every_extractor_qualifies_its_unit_paths():
    """One bare path is enough to anchor a fact to the wrong artifact, and the
    wrongness is invisible: it is still a tuple of strings, it still compares."""
    raw = ("# Title\n\n" + LONG + "\n").encode("utf-8")
    document = document_for(raw)
    facts = ir.extract_all(raw=raw, document=document)
    assert facts
    for fact in facts:
        if fact.witness.unit_path is None:
            continue
        assert fact.witness.unit_path[0] == document["source_id"], (
            f"{fact.kind} carries an unqualified unit_path {fact.witness.unit_path}"
        )


def test_every_witness_points_at_bytes_that_exist():
    raw = ("# Title\n\n" + LONG + "\n").encode("utf-8")
    for fact in ir.extract_all(raw=raw, document=document_for(raw)):
        assert fact.witness.verify(raw), f"{fact.kind} witness does not verify"


# ---------------------------------------------------------------------------
# the repair, demonstrated on the defect's own shape


def test_a_target_only_change_produces_a_typed_delta():
    """INC-V2-006, and three of the four confirmed stale escapes.

    The anchor text is byte-identical across the pair. A text-only compiled
    state cannot represent the change, cannot fingerprint it and cannot
    invalidate on it; the whole IR exists so that this pair is not silent.
    """
    _lane("reference")
    fingerprint = _lane("fingerprint")

    body = "\n\n" + LONG + "\n\n[the schedule](%s)\n"
    before_raw = ("# Title" + body % "/rules/2025").encode("utf-8")
    after_raw = ("# Title" + body % "/rules/2026").encode("utf-8")

    before = ir.extract_all(raw=before_raw, document=document_for(before_raw, "1"))
    after = ir.extract_all(raw=after_raw, document=document_for(after_raw, "2"))

    delta = fingerprint.delta(list(before), list(after))
    moved = [change for change in delta.changed if change.kind in ir.KINDS]
    assert moved, "a reference target moved and the typed delta reports nothing"
    assert any(
        ir.KIND_CHANNEL[change.kind] == ir.REFERENTIAL for change in moved
    ), "the change was reported on some channel other than the referential one"
    assert delta.invalidate, "a moved reference target invalidated nothing"


def test_the_anchor_text_really_was_unchanged():
    """Guards the test above from proving nothing.

    If the canonicaliser's unit text differs across this pair then the delta
    could have come from the text, and the demonstration would be worthless.
    """
    body = "\n\n" + LONG + "\n\n[the schedule](%s)\n"
    before = document_for(("# Title" + body % "/rules/2025").encode("utf-8"), "1")
    after = document_for(("# Title" + body % "/rules/2026").encode("utf-8"), "2")
    assert [unit["text_sha256"] for unit in before["units"]] == [
        unit["text_sha256"] for unit in after["units"]
    ], "the fixture's unit text moved, so this pair does not isolate the target"


def test_the_production_selective_path_is_silent_on_the_same_pair():
    """The contrast that makes the result mean something.

    This is the defect stated as a passing test: today's compiler sees nothing
    here. If this ever fails, the production path learned to see reference
    targets and the demonstration above stops being a repair.
    """
    import selective_build as engine

    body = "\n\n" + LONG + "\n\n[the schedule](%s)\n"
    before = document_for(("# Title" + body % "/rules/2025").encode("utf-8"), "1")
    after = document_for(("# Title" + body % "/rules/2026").encode("utf-8"), "2")
    result = engine.run_pair(before, after)
    #: `content_unchanged` is the compiler's marker for "nothing moved", not a
    #: detection, so the assertion is on what it DID: it rebuilt nothing and
    #: carried everything.
    assert not result["selective_rebuild_set"], (
        "the production path now rebuilds on a reference-target change; the "
        "typed-delta result above is no longer evidence of a repair"
    )
    assert result["carried_forward_set"], "the fixture rebuilt nothing at all"


# ---------------------------------------------------------------------------
# fail-closed, end to end


def test_a_pair_compiles_without_raising_even_when_facts_are_unresolved():
    """Counting must survive what the gate refuses. A pipeline that dies on an
    unresolved fact cannot count unresolved facts."""
    raw = ("# Title\n\n" + LONG + "\n").encode("utf-8")
    result = compile_module.compile_pair(
        before_raw=raw,
        before_document=document_for(raw, "1"),
        after_raw=raw,
        after_document=document_for(raw, "2"),
    )
    assert result.before.tally
    assert isinstance(result.as_dict(), dict)


def test_an_unresolved_fact_blocks_the_current_claim():
    raw = ("# Title\n\n" + LONG + "\n").encode("utf-8")
    state = compile_module.compile_state(raw=raw, document=document_for(raw))
    poisoned = compile_module.CompiledState(
        source_id=state.source_id,
        version_id=state.version_id,
        facts=(
            *state.facts,
            ir.SourceFact(
                kind=ir.LANGUAGE,
                witness=ir.Witness(construct="test", byte_start=0, byte_end=0),
                state=ir.UNRESOLVED,
                reason="ambiguous",
            ),
        ),
        links=state.links,
        tally=state.tally,
        unclaimed_kinds=state.unclaimed_kinds,
        lanes_missing=state.lanes_missing,
    )
    assert not poisoned.complete
    assert not poisoned.faithful
    with pytest.raises(ir.NotSourceFaithful):
        compile_module.assert_faithful(poisoned)


def test_a_missing_lane_forbids_the_faithful_claim():
    """Absence of a lane is absence of evidence about the kinds it owns, and
    must never read as evidence of absence."""
    raw = ("# Title\n\n" + LONG + "\n").encode("utf-8")
    state = compile_module.compile_state(raw=raw, document=document_for(raw))
    if not state.lanes_missing:
        pytest.skip("every lane has landed; the degraded path is exercised elsewhere")
    assert not state.faithful
    assert any("lanes absent" in reason for reason in state.why_not_faithful())


def test_an_empty_invalidation_set_cannot_be_produced_by_a_missing_field():
    """`nothing to rebuild` and `nobody computed it` must not be the same value.

    compile_pair reads the delta's invalidation set by name. If the name is ever
    renamed away, the attribute lookup must raise rather than fall through to an
    empty tuple — an empty set here reads as "no rebuild needed", which is the
    stale escape the programme confirmed four times.
    """

    class Hollow:
        """A delta that declares no invalidation set at all."""

    monkey = compile_module.load_lanes()["fingerprint"]
    if monkey is None:
        pytest.skip("lane fingerprint has not landed")

    original = monkey.delta
    monkey.delta = lambda before, after: Hollow()
    try:
        raw = ("# Title\n\n" + LONG + "\n").encode("utf-8")
        with pytest.raises(AttributeError, match="no invalidation set"):
            compile_module.compile_pair(
                before_raw=raw,
                before_document=document_for(raw, "1"),
                after_raw=raw,
                after_document=document_for(raw, "2"),
            )
    finally:
        monkey.delta = original


# ---------------------------------------------------------------------------
# determinism, which the study's reduction depends on


def test_extraction_is_deterministic_across_lanes():
    raw = ("# Title\n\n" + LONG + "\n\n[a](/x)\n\n## Two\n\n" + LONG + "\n").encode("utf-8")
    document = document_for(raw)
    runs = [
        [fact.fact_id for fact in ir.extract_all(raw=raw, document=document)]
        for _ in range(3)
    ]
    assert runs[0] == runs[1] == runs[2]
    assert runs[0]


def test_fact_ids_are_unique_within_one_revision():
    """Two facts sharing an id would make one invisible to the delta."""
    raw = ("# Title\n\n" + LONG + "\n\n[a](/x)\n\n## Two\n\n" + LONG + "\n").encode("utf-8")
    facts = ir.extract_all(raw=raw, document=document_for(raw))
    identifiers = [fact.fact_id for fact in facts]
    assert len(identifiers) == len(set(identifiers))
