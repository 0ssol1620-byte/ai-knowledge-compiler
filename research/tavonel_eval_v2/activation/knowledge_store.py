"""A minimal publication boundary: candidate state, verification, activation.

Small on purpose. P3 asks whether a consumer can observe an unverified or mixed
knowledge state, and that question needs a store with exactly three properties:
a single visible pointer, a verification conjunction that fails closed, and an
activation that is atomic from a reader's point of view. Anything else in here
would be surface a failure could hide behind.

Three states, and the distinction between the last two is the whole point:

    PASS          the predicate was evaluated and held
    FAIL          the predicate was evaluated and did not hold
    UNVERIFIABLE  the predicate could not be evaluated
    NOT_REACHED   the predicate was never evaluated

`UNVERIFIABLE` and `NOT_REACHED` are not `PASS`. A conjunction that treats an
un-evaluated predicate as satisfied is the defect this module exists to make
impossible, so `admits()` requires every declared predicate to be present and
every one of them to be `PASS`.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable

PASS = "PASS"
FAIL = "FAIL"
UNVERIFIABLE = "UNVERIFIABLE"
NOT_REACHED = "NOT_REACHED"


@dataclass(frozen=True, slots=True)
class GateResult:
    predicate: str
    state: str
    evidence_refs: tuple[str, ...] = ()
    reason_code: str = ""

    def as_record(self) -> dict[str, Any]:
        return {
            "predicate": self.predicate,
            "state": self.state,
            "evidence_refs": list(self.evidence_refs),
            "reason_code": self.reason_code,
        }


@dataclass(frozen=True, slots=True)
class Candidate:
    """A knowledge state that has been built and not yet been admitted."""

    candidate_id: str
    state: dict[str, str]
    sensitivity: dict[str, list[str]]
    fingerprints: dict[str, str | None]
    receipts: dict[str, dict[str, Any]]
    declared_inputs: tuple[str, ...]
    present_inputs: tuple[str, ...]
    authorised_units: frozenset[str] = frozenset()
    reachable_units: frozenset[str] = frozenset()


@dataclass
class RefusalEvent:
    candidate_id: str
    predicate: str
    state: str
    evidence_refs: tuple[str, ...]
    reason_code: str
    active_reference_at_refusal: str | None

    def as_record(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "predicate": self.predicate,
            "state": self.state,
            "evidence_refs": list(self.evidence_refs),
            "reason_code": self.reason_code,
            "active_reference_at_refusal": self.active_reference_at_refusal,
        }


@dataclass
class Verdict:
    admitted: bool
    results: tuple[GateResult, ...]
    refusal: RefusalEvent | None
    active_reference: str | None

    def as_record(self) -> dict[str, Any]:
        return {
            "admitted": self.admitted,
            "results": [item.as_record() for item in self.results],
            "refusal": self.refusal.as_record() if self.refusal else None,
            "active_reference": self.active_reference,
        }


# --- predicates -------------------------------------------------------------
# Each returns a GateResult. A predicate that cannot decide returns
# UNVERIFIABLE; it never returns PASS to keep a pipeline moving.

Predicate = Callable[[Candidate], GateResult]


def p_sensitivity_recorded(candidate: Candidate) -> GateResult:
    missing = sorted(
        artifact
        for artifact in candidate.state
        if not candidate.sensitivity.get(artifact)
    )
    if missing:
        return GateResult(
            "sensitivity_recorded",
            UNVERIFIABLE,
            tuple(missing[:8]),
            "an artifact carries no recorded sensitivity, so no fingerprint covers it",
        )
    return GateResult("sensitivity_recorded", PASS, (), "")


def p_fingerprint_present(candidate: Candidate) -> GateResult:
    missing = sorted(
        artifact for artifact in candidate.state if not candidate.fingerprints.get(artifact)
    )
    if missing:
        return GateResult(
            "fingerprint_present",
            UNVERIFIABLE,
            tuple(missing[:8]),
            "no input fingerprint recorded for this artifact",
        )
    return GateResult("fingerprint_present", PASS, (), "")


def p_receipt_matches_output(candidate: Candidate) -> GateResult:
    absent = sorted(artifact for artifact in candidate.state if artifact not in candidate.receipts)
    if absent:
        return GateResult(
            "receipt_matches_output",
            UNVERIFIABLE,
            tuple(absent[:8]),
            "no build receipt exists for this artifact",
        )
    wrong = sorted(
        artifact
        for artifact, value in candidate.state.items()
        if candidate.receipts[artifact].get("output_digest") != value
    )
    if wrong:
        return GateResult(
            "receipt_matches_output",
            FAIL,
            tuple(wrong[:8]),
            "the receipt declares a different output digest than the artifact carries",
        )
    return GateResult("receipt_matches_output", PASS, (), "")


def p_source_complete(candidate: Candidate) -> GateResult:
    missing = sorted(set(candidate.declared_inputs) - set(candidate.present_inputs))
    if missing:
        return GateResult(
            "source_complete",
            FAIL,
            tuple(missing[:8]),
            "a declared source input is absent from this build",
        )
    return GateResult("source_complete", PASS, (), "")


def p_permission_respected(candidate: Candidate) -> GateResult:
    leaked = sorted(candidate.reachable_units - candidate.authorised_units)
    if leaked:
        return GateResult(
            "permission_respected",
            FAIL,
            tuple(leaked[:8]),
            "a unit outside the authorised set is reachable by identifier",
        )
    return GateResult("permission_respected", PASS, (), "")


DEFAULT_PREDICATES: tuple[tuple[str, Predicate], ...] = (
    ("sensitivity_recorded", p_sensitivity_recorded),
    ("fingerprint_present", p_fingerprint_present),
    ("receipt_matches_output", p_receipt_matches_output),
    ("source_complete", p_source_complete),
    ("permission_respected", p_permission_respected),
)


def evaluate(
    candidate: Candidate,
    predicates: tuple[tuple[str, Predicate], ...] = DEFAULT_PREDICATES,
    *,
    stop_early: bool = True,
) -> tuple[GateResult, ...]:
    """Run the conjunction, recording un-evaluated predicates as NOT_REACHED."""
    results: list[GateResult] = []
    stopped = False
    for name, predicate in predicates:
        if stopped:
            results.append(GateResult(name, NOT_REACHED, (), "a prior predicate did not pass"))
            continue
        try:
            outcome = predicate(candidate)
        except Exception as error:  # a predicate that raises has not passed
            outcome = GateResult(name, UNVERIFIABLE, (), type(error).__name__)
        results.append(outcome)
        if stop_early and outcome.state != PASS:
            stopped = True
    return tuple(results)


def admits(results: tuple[GateResult, ...], declared: tuple[str, ...]) -> bool:
    """Admission requires every declared predicate present and every one PASS."""
    seen = {item.predicate: item.state for item in results}
    if set(seen) != set(declared):
        return False
    return all(state == PASS for state in seen.values())


class KnowledgeStore:
    """One visible pointer, and states that are whole when a reader sees them."""

    def __init__(self, initial_id: str, initial_state: dict[str, str]) -> None:
        self._states: dict[str, dict[str, str]] = {initial_id: dict(initial_state)}
        self._active = initial_id
        self._lock = threading.Lock()
        self.refusals: list[RefusalEvent] = []
        self.activations: list[str] = [initial_id]

    @property
    def active_reference(self) -> str:
        return self._active

    def read(self) -> tuple[str, dict[str, str]]:
        """An atomic read: the pointer and the state it named, together.

        The state dictionaries are never mutated after publication, so binding
        the reference and then reading the mapping it names cannot observe a
        half-written state.
        """
        reference = self._active
        return reference, self._states[reference]

    def publish(
        self,
        candidate: Candidate,
        predicates: tuple[tuple[str, Predicate], ...] = DEFAULT_PREDICATES,
        *,
        expected_active: str | None = None,
        stop_early: bool = True,
    ) -> Verdict:
        declared = tuple(name for name, _ in predicates)
        results = evaluate(candidate, predicates, stop_early=stop_early)
        if not admits(results, declared):
            first = next(
                (item for item in results if item.state != PASS),
                GateResult("unknown", UNVERIFIABLE, (), "no predicate result"),
            )
            event = RefusalEvent(
                candidate.candidate_id,
                first.predicate,
                first.state,
                first.evidence_refs,
                first.reason_code,
                self._active,
            )
            self.refusals.append(event)
            return Verdict(False, results, event, self._active)

        with self._lock:
            if expected_active is not None and self._active != expected_active:
                event = RefusalEvent(
                    candidate.candidate_id,
                    "pointer_compare_and_swap",
                    FAIL,
                    (self._active,),
                    "the active reference moved while this candidate was verified",
                    self._active,
                )
                self.refusals.append(event)
                return Verdict(False, results, event, self._active)
            self._states[candidate.candidate_id] = dict(candidate.state)
            self._active = candidate.candidate_id
            self.activations.append(candidate.candidate_id)
        return Verdict(True, results, None, self._active)
