"""Publication boundary, P3b: a refusal is legible even when a predicate raises.

Derived from ``knowledge_store.py``, which is **not edited**. P3 v1 stands at
FAIL on assertion A3 and its subject digest is pinned in the P3 receipt; the
repair is validated here, under its own protocol, or it is not validated at all.

INC-V2-004 was this: when a predicate raised, the refusal named the predicate and
the exception class and carried an empty evidence tuple. An operator saw *which*
check could not run and *what kind* of error stopped it, and had nothing to look
at. The contract was not weakened to permit that. What changed is where the
evidence comes from.

**A predicate no longer supplies the evidence for its own failure.** Every
predicate declares a *domain* — the part of the candidate it evaluates over — and
the framework resolves that domain to concrete references **before** calling it.
A predicate that raises on its first line still produces a refusal carrying the
artifacts or inputs it was about to read, because resolving them never ran the
predicate's code.

Every refusal, exception path included, carries:

* the predicate name
* the state, which for the exception path is ``UNVERIFIABLE`` and never ``PASS``
* a stable reason code — the exception's class name, not its message
* the candidate state id, and the digest of the state it refers to
* the evaluation event id, so the refusal joins to the run that produced it
* at least one evidence reference to the artifact or input under evaluation

**Deliberately not recorded:** the exception message and the traceback. A
message can carry a document fragment, a path or a credential from whatever the
predicate was reading, and evidence that cannot be shown to an operator is not
evidence. The class name is stable, safe and enough to group failures; the
domain references say what to go and look at.
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from typing import Any, Callable

PASS = "PASS"
FAIL = "FAIL"
UNVERIFIABLE = "UNVERIFIABLE"
NOT_REACHED = "NOT_REACHED"

#: Domains a predicate may declare. The framework, not the predicate, resolves
#: these to references.
ARTIFACTS = "artifacts"
INPUTS = "declared_inputs"
UNITS = "reachable_units"

#: Predicates whose evidence *is* the pointer, so a bare pointer reference
#: satisfies the evidence requirement. Named explicitly rather than left as a
#: general exemption.
POINTER_EVIDENCE_PREDICATES = frozenset({"pointer_compare_and_swap"})

EVIDENCE_CAP = 8


class RefusalWithoutEvidence(AssertionError):
    """A refusal was constructed with no evidence reference.

    Raised rather than tolerated. The contract requires evidence on every
    refusal, and a refusal that cannot name one is a defect in this module, not
    a condition to be recorded and moved past.
    """


def _digest(payload: Any) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class GateResult:
    predicate: str
    state: str
    evidence_refs: tuple[str, ...] = ()
    reason_code: str = ""
    evaluation_id: str = ""
    candidate_state_id: str = ""
    domain: str = ""

    def as_record(self) -> dict[str, Any]:
        return {
            "predicate": self.predicate,
            "state": self.state,
            "evidence_refs": list(self.evidence_refs),
            "reason_code": self.reason_code,
            "evaluation_id": self.evaluation_id,
            "candidate_state_id": self.candidate_state_id,
            "domain": self.domain,
        }


@dataclass(frozen=True, slots=True)
class Candidate:
    candidate_id: str
    state: dict[str, str]
    sensitivity: dict[str, list[str]]
    fingerprints: dict[str, str | None]
    receipts: dict[str, dict[str, Any]]
    declared_inputs: tuple[str, ...]
    present_inputs: tuple[str, ...]
    authorised_units: frozenset[str] = frozenset()
    reachable_units: frozenset[str] = frozenset()

    @property
    def state_digest(self) -> str:
        return _digest(self.state)


@dataclass
class RefusalEvent:
    candidate_id: str
    predicate: str
    state: str
    evidence_refs: tuple[str, ...]
    reason_code: str
    active_reference_at_refusal: str | None
    evaluation_id: str
    candidate_state_id: str
    candidate_state_digest: str

    def __post_init__(self) -> None:
        if not self.evidence_refs and self.predicate not in POINTER_EVIDENCE_PREDICATES:
            raise RefusalWithoutEvidence(
                "refusal on " + self.predicate + " carries no evidence reference"
            )

    def as_record(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "predicate": self.predicate,
            "state": self.state,
            "evidence_refs": list(self.evidence_refs),
            "reason_code": self.reason_code,
            "active_reference_at_refusal": self.active_reference_at_refusal,
            "evaluation_id": self.evaluation_id,
            "candidate_state_id": self.candidate_state_id,
            "candidate_state_digest": self.candidate_state_digest,
            "raw_message_recorded": False,
            "traceback_recorded": False,
        }


@dataclass
class Verdict:
    admitted: bool
    results: tuple[GateResult, ...]
    refusal: RefusalEvent | None
    active_reference: str | None
    evaluation_id: str = ""

    def as_record(self) -> dict[str, Any]:
        return {
            "admitted": self.admitted,
            "results": [item.as_record() for item in self.results],
            "refusal": self.refusal.as_record() if self.refusal else None,
            "active_reference": self.active_reference,
            "evaluation_id": self.evaluation_id,
        }


# --- domain resolution ------------------------------------------------------


def resolve_domain(candidate: Candidate, domain: str) -> tuple[str, ...]:
    """The references a predicate's domain names, resolved without calling it.

    Capped, with the cap made visible rather than silent: a truncated list that
    looks complete is the kind of thing this programme has been bitten by.
    """
    if domain == ARTIFACTS:
        members = sorted(candidate.state)
        prefix = "artifact:"
    elif domain == INPUTS:
        members = sorted(candidate.declared_inputs)
        prefix = "input:"
    elif domain == UNITS:
        members = sorted(candidate.reachable_units)
        prefix = "unit:"
    else:
        raise KeyError("unknown predicate domain: " + str(domain))

    refs = [prefix + name for name in members[:EVIDENCE_CAP]]
    if len(members) > EVIDENCE_CAP:
        refs.append(
            "%s+%d more of %d" % (prefix, len(members) - EVIDENCE_CAP, len(members))
        )
    if not refs:
        # An empty domain still has to yield something to look at, or the
        # exception path is back where it started.
        refs = ["candidate-state:" + candidate.candidate_id + " (" + domain + " is empty)"]
    return tuple(refs)


# --- predicates -------------------------------------------------------------

Predicate = Callable[[Candidate], GateResult]


def p_sensitivity_recorded(candidate: Candidate) -> GateResult:
    missing = sorted(
        artifact for artifact in candidate.state if not candidate.sensitivity.get(artifact)
    )
    if missing:
        return GateResult(
            "sensitivity_recorded",
            UNVERIFIABLE,
            tuple("artifact:" + name for name in missing[:EVIDENCE_CAP]),
            "NO_RECORDED_SENSITIVITY",
        )
    return GateResult("sensitivity_recorded", PASS)


def p_fingerprint_present(candidate: Candidate) -> GateResult:
    missing = sorted(
        artifact for artifact in candidate.state if not candidate.fingerprints.get(artifact)
    )
    if missing:
        return GateResult(
            "fingerprint_present",
            UNVERIFIABLE,
            tuple("artifact:" + name for name in missing[:EVIDENCE_CAP]),
            "NO_INPUT_FINGERPRINT",
        )
    return GateResult("fingerprint_present", PASS)


def p_receipt_matches_output(candidate: Candidate) -> GateResult:
    absent = sorted(
        artifact for artifact in candidate.state if artifact not in candidate.receipts
    )
    if absent:
        return GateResult(
            "receipt_matches_output",
            UNVERIFIABLE,
            tuple("artifact:" + name for name in absent[:EVIDENCE_CAP]),
            "NO_BUILD_RECEIPT",
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
            tuple("artifact:" + name for name in wrong[:EVIDENCE_CAP]),
            "RECEIPT_DIGEST_MISMATCH",
        )
    return GateResult("receipt_matches_output", PASS)


def p_source_complete(candidate: Candidate) -> GateResult:
    missing = sorted(set(candidate.declared_inputs) - set(candidate.present_inputs))
    if missing:
        return GateResult(
            "source_complete",
            FAIL,
            tuple("input:" + name for name in missing[:EVIDENCE_CAP]),
            "DECLARED_INPUT_ABSENT",
        )
    return GateResult("source_complete", PASS)


def p_permission_respected(candidate: Candidate) -> GateResult:
    leaked = sorted(candidate.reachable_units - candidate.authorised_units)
    if leaked:
        return GateResult(
            "permission_respected",
            FAIL,
            tuple("unit:" + name for name in leaked[:EVIDENCE_CAP]),
            "UNAUTHORISED_UNIT_REACHABLE",
        )
    return GateResult("permission_respected", PASS)


#: name, callable, domain. The domain is what the framework resolves for the
#: exception path, and it is declared beside the predicate so the two cannot
#: drift apart unnoticed.
DEFAULT_PREDICATES: tuple[tuple[str, Predicate, str], ...] = (
    ("sensitivity_recorded", p_sensitivity_recorded, ARTIFACTS),
    ("fingerprint_present", p_fingerprint_present, ARTIFACTS),
    ("receipt_matches_output", p_receipt_matches_output, ARTIFACTS),
    ("source_complete", p_source_complete, INPUTS),
    ("permission_respected", p_permission_respected, UNITS),
)


def evaluation_id(candidate: Candidate, declared: tuple[str, ...], sequence: int) -> str:
    material = _digest(
        {
            "candidate_id": candidate.candidate_id,
            "state_digest": candidate.state_digest,
            "declared": list(declared),
            "sequence": sequence,
        }
    )
    return "eval:" + material.split(":", 1)[1][:16]


def evaluate(
    candidate: Candidate,
    predicates: tuple[tuple[str, Predicate, str], ...] = DEFAULT_PREDICATES,
    *,
    stop_early: bool = True,
    sequence: int = 0,
) -> tuple[tuple[GateResult, ...], str]:
    """Run the conjunction. Returns the results and the evaluation event id."""
    declared = tuple(name for name, _, _ in predicates)
    event = evaluation_id(candidate, declared, sequence)
    results: list[GateResult] = []
    stopped = False

    for name, predicate, domain in predicates:
        if stopped:
            results.append(
                GateResult(
                    name,
                    NOT_REACHED,
                    (),
                    "PRIOR_PREDICATE_DID_NOT_PASS",
                    event,
                    candidate.candidate_id,
                    domain,
                )
            )
            continue

        # Resolved before the predicate runs, so a predicate that raises on its
        # first line still has evidence attached to its refusal.
        scope = resolve_domain(candidate, domain)
        try:
            outcome = predicate(candidate)
        except Exception as error:
            outcome = GateResult(
                name,
                UNVERIFIABLE,
                scope,
                "PREDICATE_RAISED:" + type(error).__name__,
            )
        outcome = GateResult(
            outcome.predicate,
            outcome.state,
            outcome.evidence_refs or (scope if outcome.state != PASS else ()),
            outcome.reason_code,
            event,
            candidate.candidate_id,
            domain,
        )
        results.append(outcome)
        if stop_early and outcome.state != PASS:
            stopped = True

    return tuple(results), event


def admits(results: tuple[GateResult, ...], declared: tuple[str, ...]) -> bool:
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
        self._sequence = 0
        self.refusals: list[RefusalEvent] = []
        self.activations: list[str] = [initial_id]

    @property
    def active_reference(self) -> str:
        return self._active

    def read(self) -> tuple[str, dict[str, str]]:
        reference = self._active
        return reference, self._states[reference]

    def publish(
        self,
        candidate: Candidate,
        predicates: tuple[tuple[str, Predicate, str], ...] = DEFAULT_PREDICATES,
        *,
        expected_active: str | None = None,
        stop_early: bool = True,
    ) -> Verdict:
        declared = tuple(name for name, _, _ in predicates)
        with self._lock:
            self._sequence += 1
            sequence = self._sequence
        results, event = evaluate(
            candidate, predicates, stop_early=stop_early, sequence=sequence
        )

        if not admits(results, declared):
            first = next(
                (item for item in results if item.state != PASS),
                GateResult(
                    "predicate_set_incomplete",
                    UNVERIFIABLE,
                    ("candidate-state:" + candidate.candidate_id,),
                    "NO_PREDICATE_RESULT",
                    event,
                    candidate.candidate_id,
                    "",
                ),
            )
            refusal = RefusalEvent(
                candidate.candidate_id,
                first.predicate,
                first.state,
                first.evidence_refs,
                first.reason_code,
                self._active,
                event,
                candidate.candidate_id,
                candidate.state_digest,
            )
            self.refusals.append(refusal)
            return Verdict(False, results, refusal, self._active, event)

        with self._lock:
            if expected_active is not None and self._active != expected_active:
                refusal = RefusalEvent(
                    candidate.candidate_id,
                    "pointer_compare_and_swap",
                    FAIL,
                    (self._active,),
                    "ACTIVE_REFERENCE_MOVED",
                    self._active,
                    event,
                    candidate.candidate_id,
                    candidate.state_digest,
                )
                self.refusals.append(refusal)
                return Verdict(False, results, refusal, self._active, event)
            self._states[candidate.candidate_id] = dict(candidate.state)
            self._active = candidate.candidate_id
            self.activations.append(candidate.candidate_id)
        return Verdict(True, results, None, self._active, event)
