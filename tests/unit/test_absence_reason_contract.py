"""Contract audit for claim A2: an abstention records which signals were absent.

A2 recites that an abstention decision is recorded with the identities of the
signals that were present, the identities of the signals that had no value, and
an absence reason for each, "such that an abstention is distinguishable from a
failure to evaluate."

Pass K classified that element `ELEMENT_IMPLEMENTED_ONLY`: the code existed and
was unit-tested, but no receipt bound the recital to an observable. These tests
are that observable. They are a **controlled implementation contract audit** over
the live `akc_cir.identity` module -- no external corpus, no GPU, no new
mechanism. They establish what the implementation records. They do **not**
establish that `MissingReason` enumerates every way a signal can be absent, and
nothing here may be read as a completeness result.

Two boundaries the tests are written to keep visible:

* **Absent is not zero.** A signal with no value must appear in `missing` and
  must *not* appear in `signals`. §N4.4 forbids zero-filling, and a zero-filled
  absence is indistinguishable from genuine disagreement.
* **Two different abstentions exist.** An abstention caused by an absent critical
  signal carries a populated `missing` map; an abstention caused by a scoring tie
  carries an empty one after a complete evaluation. The record distinguishes
  them, and that distinction -- not a claim about crashes -- is what "an
  abstention is distinguishable from a failure to evaluate" means here.
"""

from __future__ import annotations

import json
from dataclasses import asdict, replace

import pytest
from akc_cir.identity import (
    CRITICAL_IDENTITY_SIGNALS,
    IDENTITY_SIGNAL_WEIGHTS,
    LogicalIdentityDecision,
    LogicalIdentityResolver,
    LogicalMatch,
    LogicalUnitFingerprint,
    MissingReason,
)

# Every signal the scorer knows how to compute. The contract is stated over this
# set rather than over whatever a particular decision happened to produce.
ALL_SIGNALS = frozenset(IDENTITY_SIGNAL_WEIGHTS)


def _fully_observable(logical_id: str, *, text: str, ident: str) -> LogicalUnitFingerprint:
    """A fingerprint on which every signal has an input, so none may be absent."""
    return LogicalUnitFingerprint(
        logical_id=logical_id,
        document_path=("contract", "4"),
        anchor=f"anchor::{logical_id}",
        normalized_text=text,
        source_lineage="source::contract-v1",
        version_distance=1,
        explicit_identifier=ident,
        previous_anchor="the preceding clause anchor",
        next_anchor="the following clause anchor",
        geometry_style="serif|11pt|indent-2",
    )


def _absent_lineage(fingerprint: LogicalUnitFingerprint) -> LogicalUnitFingerprint:
    """The same unit with its source lineage genuinely unavailable.

    Empty means *not available*, which is the distinction the module documents at
    `LogicalUnitFingerprint`. It is not a shorter string.
    """
    return replace(fingerprint, source_lineage="")


@pytest.fixture
def engine() -> LogicalIdentityResolver:
    return LogicalIdentityResolver()


@pytest.fixture
def absence_abstention(engine: LogicalIdentityResolver) -> LogicalIdentityDecision:
    """An abstention whose cause is an absent critical signal."""
    prior = _absent_lineage(
        _fully_observable("unit-1", text="the supplier shall deliver by march", ident="4.1")
    )
    incoming = _fully_observable(
        "unit-1-next", text="the supplier shall deliver by march", ident="4.1"
    )
    decision = engine.resolve(incoming, [prior])
    assert decision.match is LogicalMatch.AMBIGUOUS, decision.reason
    return decision


@pytest.fixture
def complete_evaluation(engine: LogicalIdentityResolver) -> LogicalIdentityDecision:
    """A decision reached with every signal available -- the positive control."""
    prior = _fully_observable("unit-1", text="the supplier shall deliver by march", ident="4.1")
    incoming = _fully_observable(
        "unit-1-next", text="the supplier shall deliver by march", ident="4.1"
    )
    return engine.resolve(incoming, [prior])


# -- the recital, element by element ---------------------------------------


def test_an_abstention_records_the_identities_of_the_present_signals(
    absence_abstention: LogicalIdentityDecision,
) -> None:
    present = set(absence_abstention.signals)
    assert present, "an abstention with no recorded present signals records nothing"
    assert present <= ALL_SIGNALS, f"unknown signal identity recorded: {present - ALL_SIGNALS}"


def test_an_abstention_records_the_identities_of_the_absent_signals(
    absence_abstention: LogicalIdentityDecision,
) -> None:
    absent = set(absence_abstention.missing)
    assert absent, "the abstention was caused by an absent signal and records none"
    assert absent <= ALL_SIGNALS, f"unknown signal identity recorded: {absent - ALL_SIGNALS}"
    assert "source_continuity" in absent, (
        "the signal whose input was withheld is not the one reported absent"
    )


def test_each_absent_signal_carries_an_enumerated_absence_reason(
    absence_abstention: LogicalIdentityDecision,
) -> None:
    enumerated = {member.value for member in MissingReason}
    for name, reason in absence_abstention.missing.items():
        assert reason in enumerated, (
            f"{name} carries the free-text absence reason {reason!r}; the recital "
            "requires a reason the implementation distinguishes"
        )


def test_present_and_absent_are_disjoint_and_a_signal_is_never_zero_filled(
    absence_abstention: LogicalIdentityDecision,
) -> None:
    present, absent = set(absence_abstention.signals), set(absence_abstention.missing)
    assert not (present & absent), f"recorded as both present and absent: {present & absent}"
    assert "source_continuity" not in absence_abstention.signals, (
        "an absent signal was given a numeric value; §N4.4 forbids zero-filling "
        "because a zero is indistinguishable from measured disagreement"
    )


def test_an_absence_abstention_names_the_absent_critical_signal_in_its_reason(
    absence_abstention: LogicalIdentityDecision,
) -> None:
    absent_critical = CRITICAL_IDENTITY_SIGNALS & set(absence_abstention.missing)
    assert absent_critical, "the fixture no longer withholds a critical signal"
    for name in absent_critical:
        assert name in absence_abstention.reason, (
            "the operator-facing reason does not name the signal that caused the "
            "abstention, which is the bare-'ambiguous' failure the module warns about"
        )
    assert absence_abstention.logical_id is None, "an abstention assigned an identity"


# -- distinguishability ------------------------------------------------------


def test_a_complete_evaluation_records_no_absence(
    complete_evaluation: LogicalIdentityDecision,
) -> None:
    """Positive control: the absence record fires on absence, not on every decision."""
    assert complete_evaluation.missing == {}, (
        f"signals reported absent when every input was supplied: {complete_evaluation.missing}"
    )
    assert set(complete_evaluation.signals) == ALL_SIGNALS, (
        "a signal with an available input was neither scored nor reported absent"
    )


def test_an_absence_abstention_is_distinguishable_from_a_complete_evaluation(
    absence_abstention: LogicalIdentityDecision,
    complete_evaluation: LogicalIdentityDecision,
) -> None:
    assert absence_abstention.missing != complete_evaluation.missing
    assert bool(absence_abstention.missing) is True
    assert bool(complete_evaluation.missing) is False


def test_an_absence_abstention_is_distinguishable_from_a_tie_abstention(
    engine: LogicalIdentityResolver,
) -> None:
    """Two abstentions with different causes must not read alike.

    A tie abstention is reached after a *complete* evaluation, so its absence map
    is empty. That is the discrimination the recital asks for: the record says
    which kind of abstention this was.
    """
    text = "the supplier shall deliver by march"
    left = _fully_observable("unit-a", text=text, ident="4.1")
    right = _fully_observable("unit-b", text=text, ident="4.1")
    incoming = _fully_observable("unit-new", text=text, ident="4.1")

    decision = engine.resolve(incoming, [left, right])
    assert decision.match is LogicalMatch.AMBIGUOUS, decision.reason
    assert decision.missing == {}, (
        "a tie abstention reports absent signals; the two abstention causes are "
        "then indistinguishable from the record"
    )
    assert len(decision.candidates) == 2, "a tie abstention did not record both candidates"


def test_a_failure_to_evaluate_produces_no_decision_at_all(engine: LogicalIdentityResolver) -> None:
    """The other half of the distinction: a failure yields no record to read.

    This is deliberately narrow. It shows that a refused evaluation does not
    fabricate an abstention record -- not that the engine is crash-safe, and not
    that every internal failure is caught.
    """
    with pytest.raises(ValueError):
        LogicalIdentityResolver(merge_threshold=0.5, new_threshold=0.9)


# -- serialization -----------------------------------------------------------


def test_the_absence_record_survives_serialization(
    absence_abstention: LogicalIdentityDecision,
) -> None:
    payload = json.loads(json.dumps(asdict(absence_abstention), default=str))
    assert set(payload["missing"]) == set(absence_abstention.missing)
    assert set(payload["signals"]) == set(absence_abstention.signals)
    assert payload["missing"] == absence_abstention.missing, (
        "the absence reasons did not round-trip; a record that loses them cannot "
        "distinguish an abstention from a failure to evaluate downstream"
    )
    assert payload["logical_id"] is None


# -- break control -----------------------------------------------------------


def test_the_contract_predicate_refuses_a_zero_filled_absence() -> None:
    """A guard that cannot fail is not a guard.

    This constructs the defect the contract forbids -- a signal recorded as both
    absent and numerically scored -- and asserts the same predicate the tests
    above rely on rejects it.
    """
    defective = LogicalIdentityDecision(
        match=LogicalMatch.AMBIGUOUS,
        logical_id=None,
        score=0.0,
        signals={"source_continuity": 0.0},
        missing={"source_continuity": MissingReason.NOT_APPLICABLE.value},
        reason="constructed defect: absent and zero-filled at once",
    )
    present, absent = set(defective.signals), set(defective.missing)
    assert present & absent, (
        "the disjointness predicate did not detect a zero-filled absence, so the "
        "passing tests above prove nothing"
    )


def test_the_contract_predicate_refuses_an_unenumerated_absence_reason() -> None:
    """The second break control: a free-text reason must not satisfy the recital."""
    defective = LogicalIdentityDecision(
        match=LogicalMatch.AMBIGUOUS,
        logical_id=None,
        score=0.0,
        missing={"semantic": "the model was busy"},
        reason="constructed defect: unenumerated absence reason",
    )
    enumerated = {member.value for member in MissingReason}
    assert not set(defective.missing.values()) <= enumerated, (
        "an unenumerated reason passed the enumeration predicate"
    )
