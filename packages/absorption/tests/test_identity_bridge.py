"""The three properties the challenger's whole claim to be "additive" rests on.

If any of these fails, the challenger is not supplying signals to Protected
Core, it is replacing Protected Core's judgement, and the experiment stops being
the one the contract authorised.
"""

from __future__ import annotations

import pytest
from akc_absorption.alignment import ALIGNMENT_SIGNAL_NAMES, AlignmentContext
from akc_absorption.element_model import DocumentElement, ElementIndex, ElementType
from akc_absorption.flags import ABSORB_ALIGNMENT_DIFF, AbsorptionFlagError
from akc_absorption.identity_bridge import (
    ALIGNMENT_SHARE,
    AlignmentAwareResolver,
    extended_weights,
)
from akc_cir.identity import (
    CRITICAL_IDENTITY_SIGNALS,
    IDENTITY_SIGNAL_WEIGHTS,
    LogicalIdentityResolver,
    LogicalMatch,
    LogicalUnitFingerprint,
)

ON = {ABSORB_ALIGNMENT_DIFF: "1"}


def _element(logical_id: str, text: str, *, order: int = 0) -> DocumentElement:
    return DocumentElement(
        element_id=f"el_{logical_id}",
        version_id="dv_test",
        element_type=ElementType.TEXT,
        logical_id=logical_id,
        text=text,
        structural_path=("section_1",),
        page_index=0,
        bbox1000=(100, 100, 900, 200),
        order_index=order,
    )


def _fingerprint(logical_id: str, text: str) -> LogicalUnitFingerprint:
    return LogicalUnitFingerprint.of(
        logical_id=logical_id,
        document_path=("section_1",),
        anchor=logical_id,
        text=text,
        source_lineage="src_test",
        explicit_identifier="1.1",
        previous_anchor="prev",
        next_anchor="next",
        geometry_style="body-11pt",
    )


def _resolver(before: list[DocumentElement], after: list[DocumentElement], **kwargs: object):
    before_index = ElementIndex.of("dv_before", before)
    after_index = ElementIndex.of("dv_after", after)
    return AlignmentAwareResolver(
        before_index=before_index, after_index=after_index, env=ON, **kwargs  # type: ignore[arg-type]
    )


def test_flag_off_refuses_to_construct() -> None:
    index = ElementIndex.of("dv", [_element("a", "text")])
    with pytest.raises(AbsorptionFlagError, match="shadow-only"):
        AlignmentAwareResolver(before_index=index, after_index=index, env={})


def test_weights_sum_to_one_and_preserve_core_ratios() -> None:
    weights = extended_weights()
    assert abs(sum(weights.values()) - 1.0) < 1e-9
    core_total = sum(weights[name] for name in IDENTITY_SIGNAL_WEIGHTS)
    assert abs(core_total - (1.0 - ALIGNMENT_SHARE)) < 1e-9
    # Every core weight scaled by the same factor, so their ratios are untouched.
    factors = [
        weights[name] / IDENTITY_SIGNAL_WEIGHTS[name] for name in IDENTITY_SIGNAL_WEIGHTS
    ]
    for factor in factors:
        assert factor == pytest.approx(1.0 - ALIGNMENT_SHARE)


def test_without_alignment_evidence_the_score_is_exactly_current() -> None:
    """Property 1. A unit the alignment layer never saw scores what CURRENT scores."""
    candidate = _fingerprint("before-only", "the supplier may deliver the goods")
    incoming = _fingerprint("after-only", "the supplier may deliver the parts")
    # Neither logical id is in either index, so no alignment signal has a value.
    empty = ElementIndex.of("dv_empty", [])
    challenger = AlignmentAwareResolver(
        before_index=empty, after_index=empty, env=ON
    )
    current = LogicalIdentityResolver()

    challenger_score, _, challenger_missing = challenger.score_pair(candidate, incoming)
    current_score, _, _ = current.score_pair(candidate, incoming)
    assert challenger_score == pytest.approx(current_score, abs=1e-12)
    for name in ALIGNMENT_SIGNAL_NAMES:
        assert challenger_missing[name] == "NOT_APPLICABLE"


def test_alignment_cannot_rescue_a_missing_critical_signal() -> None:
    """Property 2. Perfect alignment evidence still abstains without the core three."""
    # No source lineage on either side, so `source_continuity` -- a critical
    # signal -- has no value.
    candidate = LogicalUnitFingerprint.of(
        logical_id="a", document_path=("s",), anchor="a", text="identical text"
    )
    incoming = LogicalUnitFingerprint.of(
        logical_id="b", document_path=("s",), anchor="a", text="identical text"
    )
    resolver = _resolver(
        [_element("a", "identical text")], [_element("b", "identical text")]
    )
    score, signals, missing = resolver.score_pair(candidate, incoming)
    assert set(missing) & CRITICAL_IDENTITY_SIGNALS
    assert signals["align_type"] == 1.0
    decision = resolver.decide_pair(
        incoming=incoming,
        partner=candidate,
        score=score,
        signals=signals,
        missing=missing,
        runner_up=0.0,
        runner_up_id=None,
        seed_logical_id=None,
    )
    assert decision.match is LogicalMatch.AMBIGUOUS
    assert "source_continuity" in decision.reason


def test_no_core_signal_is_suppressed() -> None:
    """Property 3. The override adds keys and removes none."""
    candidate = _fingerprint("a", "the supplier may deliver the goods")
    incoming = _fingerprint("b", "the supplier must deliver the goods")
    resolver = _resolver(
        [_element("a", "the supplier may deliver the goods")],
        [_element("b", "the supplier must deliver the goods")],
    )
    current = LogicalIdentityResolver()

    _, challenger_signals, challenger_missing = resolver.score_pair(candidate, incoming)
    _, current_signals, current_missing = current.score_pair(candidate, incoming)

    core_names = set(IDENTITY_SIGNAL_WEIGHTS)
    assert set(current_signals) <= set(challenger_signals)
    for name in core_names & set(current_signals):
        assert challenger_signals[name] == current_signals[name]
    assert set(current_missing) <= set(challenger_missing)


def test_core_module_constants_are_not_mutated_by_use() -> None:
    """A subclass that quietly edited a core global would pass every other test."""
    weights_before = dict(IDENTITY_SIGNAL_WEIGHTS)
    critical_before = frozenset(CRITICAL_IDENTITY_SIGNALS)
    resolver = _resolver([_element("a", "one")], [_element("b", "one")])
    resolver.score_pair(_fingerprint("a", "one"), _fingerprint("b", "one"))
    assert weights_before == IDENTITY_SIGNAL_WEIGHTS
    assert critical_before == CRITICAL_IDENTITY_SIGNALS


def test_unknown_ablation_signal_is_rejected() -> None:
    index = ElementIndex.of("dv", [_element("a", "one")])
    with pytest.raises(ValueError, match="unknown alignment signals"):
        AlignmentAwareResolver(
            before_index=index,
            after_index=index,
            enabled=frozenset({"align_vibes"}),
            env=ON,
        )


def test_alignment_context_is_reused_when_supplied() -> None:
    before = ElementIndex.of("dv_before", [_element("a", "one")])
    after = ElementIndex.of("dv_after", [_element("b", "one")])
    context = AlignmentContext(pairs={"b": "a"})
    resolver = AlignmentAwareResolver(
        before_index=before, after_index=after, context=context, env=ON
    )
    assert resolver.alignment_context is context
