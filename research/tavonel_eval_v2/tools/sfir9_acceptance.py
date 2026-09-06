#!/usr/bin/env python3
"""Whether a result may be sealed, which is a different question from whether it passed.

**A study that fell short is a result. A study that cannot say what it measured
is not.** SFIR7 conflated these and published a number. So the matrix here has
two axes and they are never collapsed: the scorer says whether the capacity
criterion was met, and this module says whether the run is in a condition to have
said anything at all. `CAPACITY_CRITERION_NOT_MET` is sealable and publishable;
`MEASURED_NOT_SEALABLE` is neither, and no amount of acceptance evidence makes it
so.

**Every criterion carries an evidence pointer or it is UNPROVEN.** Not FAIL --
those are different states and merging them would let a missing check read as a
passed one, or as a refuted one. A criterion nobody evaluated is a criterion
nobody evaluated, and the matrix says so in its own word.

**Four links per fact, and a shortfall is a shortfall.** A counted candidate must
carry a source witness (the response that produced it), a canonical
representation (the identity it was reduced to), a fingerprint (the content
digest), and a dependency path (the root it hangs from). Three of four is not a
fact. If fewer facts survive than the floor requires, that is a feasibility
failure and the floor is not lowered to meet the supply.

**The seal is all-or-nothing and it refuses rather than warns.** A matrix with
one FAIL and one UNPROVEN does not seal, and there is no override parameter --
an override would be used, eventually, on the run where it mattered most.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

import sfir9_protocol as protocol_module
import sfir9_scorer as scorer

SCHEMA = "tavonel.sfir9.acceptance.v1"

PASS = "PASS"  # noqa: S105 - an acceptance state, not a credential
FAIL = "FAIL"
UNPROVEN = "UNPROVEN"
STATES = frozenset({PASS, FAIL, UNPROVEN})

#: The four links every counted fact must carry.
REQUIRED_LINKS = (
    "source_witness",
    "canonical_representation",
    "fingerprint",
    "dependency_path",
)

#: The criteria a census must satisfy before its result may be sealed. Named
#: here so a run that silently evaluated fewer of them is visible as a run that
#: evaluated fewer of them.
REQUIRED_CRITERIA = (
    "protocol_frozen",
    "upstream_binding_verified",
    "historical_isolation_clean",
    "roster_sealed",
    "segment_chain_intact",
    "every_counted_root_attested",
    "provider_accounting_recorded",
    "receipts_credential_clean",
    "four_links_complete",
    "verdict_is_sealable",
)

MISSING_CRITERION = "REFUSED_INCOMPLETE_ACCEPTANCE_MATRIX"
UNKNOWN_STATE = "REFUSED_UNDECLARED_ACCEPTANCE_STATE"
NOT_ACCEPTED = "REFUSED_SEAL_WITHOUT_ACCEPTANCE"
NO_EVIDENCE = "REFUSED_PASS_WITHOUT_EVIDENCE"


class AcceptanceRefused(RuntimeError):
    """A refusal carrying the code that names it."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


def _digest(payload: Any) -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
    )


@dataclass(frozen=True, slots=True)
class Criterion:
    """One acceptance question, its answer, and what backs the answer."""

    name: str
    state: str
    evidence: str | None
    detail: str

    def __post_init__(self) -> None:
        if self.state not in STATES:
            raise AcceptanceRefused(
                UNKNOWN_STATE,
                f"{self.state!r} is not a declared acceptance state. Declared: "
                f"{sorted(STATES)}.",
            )
        if self.state == PASS and not self.evidence:
            raise AcceptanceRefused(
                NO_EVIDENCE,
                f"criterion {self.name!r} passes with no evidence pointer. A pass "
                "nobody can follow back to an artifact is an assertion, and this "
                "study has a name for those: UNPROVEN.",
            )

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "state": self.state,
            "evidence": self.evidence,
            "detail": self.detail,
        }


def four_links(fact: dict[str, Any]) -> dict[str, Any]:
    """Whether one fact carries all four links. Three of four is not a fact."""
    missing = [link for link in REQUIRED_LINKS if not fact.get(link)]
    return {
        "fact": fact.get("canonical_representation"),
        "complete": not missing,
        "missing_links": missing,
        "required_links": list(REQUIRED_LINKS),
    }


def four_link_audit(facts: Any, *, floor: int) -> dict[str, Any]:
    """Audit a body of facts against a floor, without padding to reach it."""
    audited = [four_links(fact) for fact in facts]
    complete = [row for row in audited if row["complete"]]
    shortfall = max(0, floor - len(complete))
    return {
        "facts_examined": len(audited),
        "facts_four_link_complete": len(complete),
        "facts_incomplete": len(audited) - len(complete),
        "floor": floor,
        "shortfall": shortfall,
        "feasible": shortfall == 0,
        "incomplete_rows": [row for row in audited if not row["complete"]][:20],
        "why_the_floor_is_not_lowered": (
            "a floor met by relaxing what counts as a fact is not a floor. A "
            "shortfall is a feasibility failure and is reported as one."
        ),
    }


class AcceptanceMatrix:
    """The ten questions, each answered once, each carrying its evidence."""

    def __init__(self) -> None:
        self._criteria: dict[str, Criterion] = {}

    def record(self, name: str, state: str, *, evidence: str | None = None,
               detail: str = "") -> Criterion:
        criterion = Criterion(name=name, state=state, evidence=evidence, detail=detail)
        self._criteria[name] = criterion
        return criterion

    def missing(self) -> list[str]:
        return [name for name in REQUIRED_CRITERIA if name not in self._criteria]

    def states(self) -> dict[str, str]:
        return {name: criterion.state for name, criterion in self._criteria.items()}

    def failures(self) -> list[str]:
        return sorted(n for n, c in self._criteria.items() if c.state == FAIL)

    def unproven(self) -> list[str]:
        return sorted(n for n, c in self._criteria.items() if c.state == UNPROVEN)

    def accepted(self) -> bool:
        return not self.missing() and not self.failures() and not self.unproven()

    def evaluate(self) -> dict[str, Any]:
        """The matrix as a receipt. Never raises -- reading a matrix is not a gate."""
        return {
            "schema": SCHEMA,
            "required_criteria": list(REQUIRED_CRITERIA),
            "criteria": [
                self._criteria[name].as_dict()
                for name in REQUIRED_CRITERIA
                if name in self._criteria
            ],
            "extra_criteria": [
                criterion.as_dict()
                for name, criterion in sorted(self._criteria.items())
                if name not in REQUIRED_CRITERIA
            ],
            "not_evaluated": self.missing(),
            "failed": self.failures(),
            "unproven": self.unproven(),
            "accepted": self.accepted(),
            "why_unproven_is_not_failed": (
                "a criterion nobody evaluated and a criterion that was refuted are "
                "different states. Merging them lets a missing check read as either "
                "a passed one or a refuted one, and both readings are wrong."
            ),
            "matrix_digest": _digest(
                {
                    name: self._criteria[name].as_dict()
                    for name in sorted(self._criteria)
                }
            ),
        }

    def seal(self, score: dict[str, Any]) -> dict[str, Any]:
        """Produce a sealed result, or refuse. There is no override.

        The two axes stay apart. Acceptance says the run is in a condition to
        report; the scorer says what it found. A sealed FAIL is a finding about
        the population and is published as one.
        """
        if self.missing():
            raise AcceptanceRefused(
                MISSING_CRITERION,
                f"{self.missing()} were never evaluated. An unevaluated criterion is "
                "not a satisfied one, and a matrix short of its own list has not "
                "finished asking.",
            )
        if not self.accepted():
            raise AcceptanceRefused(
                NOT_ACCEPTED,
                f"failed={self.failures()} unproven={self.unproven()}. The run is not "
                "in a condition to report what it measured, which is a different "
                "thing from measuring something disappointing. There is no override: "
                "one would be used, eventually, on the run where it mattered most.",
            )
        if score["verdict"] == scorer.NOT_SEALABLE:
            raise AcceptanceRefused(
                NOT_ACCEPTED,
                "the scorer returned MEASURED_NOT_SEALABLE. Acceptance evidence "
                "cannot supply a total the census did not establish.",
            )
        return {
            "schema": SCHEMA,
            "sealed": True,
            "verdict": score["verdict"],
            "capacity": score["capacity"],
            "completeness": score["completeness"],
            "roster_digest": score["roster_digest"],
            "protocol_digest": score["protocol_digest"],
            "acceptance_digest": self.evaluate()["matrix_digest"],
            "result_is_publishable": True,
            "what_a_sealed_fail_means": (
                "the population did not supply the required capacity. That is a "
                "finding about the population, published as one, and it is not a "
                "reason to revisit the threshold."
            ),
        }


def acceptance_of(
    *,
    protocol: protocol_module.Protocol,
    upstream_binding: dict[str, Any] | None,
    isolation_proof: dict[str, Any] | None,
    roster_seal: dict[str, Any] | None,
    chain_verification: dict[str, Any] | None,
    attested_host_uuids: Any,
    counted_host_uuids: Any,
    provider_reconciliation: dict[str, Any] | None,
    credential_scan: dict[str, Any] | None,
    four_link: dict[str, Any] | None,
    score: dict[str, Any],
) -> AcceptanceMatrix:
    """Fill the matrix from the artifacts each criterion actually depends on.

    Every argument may be `None`, and `None` produces UNPROVEN rather than FAIL.
    A run that never reached a check has not refuted it.
    """
    matrix = AcceptanceMatrix()

    matrix.record(
        "protocol_frozen",
        PASS if protocol.is_frozen() else FAIL,
        evidence=protocol.digest(),
        detail=f"freeze_state={protocol.freeze_state}",
    )

    _from_flag(
        matrix, "upstream_binding_verified", upstream_binding,
        lambda b: bool(b.get("upstream_modules")),
        lambda b: b.get("manifest_digest"),
        "every upstream module hashed, blob-matched and origin-checked",
    )

    _from_flag(
        matrix, "historical_isolation_clean", isolation_proof,
        lambda p: p.get("sfir9_prospective_integrity") == "CLEAN",
        lambda p: p.get("historical_integrity_receipt_sha256"),
        "no historical receipt is a prerequisite of this run",
    )

    _from_flag(
        matrix, "roster_sealed", roster_seal,
        lambda s: bool(s.get("intact")),
        lambda s: s.get("recorded_seal_digest"),
        "the cohort was sealed and its digest still matches",
    )

    _from_flag(
        matrix, "segment_chain_intact", chain_verification,
        lambda c: bool(c.get("links_intact")) and bool(c.get("head_matches")),
        lambda c: c.get("recomputed_head"),
        "every segment links to its predecessor",
    )

    attested = {str(value) for value in attested_host_uuids}
    counted = {str(value) for value in counted_host_uuids}
    unattested = sorted(counted - attested)
    matrix.record(
        "every_counted_root_attested",
        PASS if not unattested else FAIL,
        evidence=_digest(sorted(attested)) if not unattested else None,
        detail=(
            "every counted root proved its numeric id"
            if not unattested
            else f"counted without an identity proof: {unattested}"
        ),
    )

    _from_flag(
        matrix, "provider_accounting_recorded", provider_reconciliation,
        lambda r: "UNATTRIBUTED_PROVIDER_ACCOUNTING_DELTA" in r,
        lambda r: _digest(r),
        "the difference between the provider's counter and ours is recorded, "
        "whatever its value",
    )

    _from_flag(
        matrix, "receipts_credential_clean", credential_scan,
        lambda s: s.get("credential_material_found") == 0,
        lambda s: s.get("scan_digest"),
        "no credential material appears in any receipt",
    )

    _from_flag(
        matrix, "four_links_complete", four_link,
        lambda f: bool(f.get("feasible")),
        lambda f: _digest(f),
        "every counted fact carries all four links, and the floor is met without "
        "relaxing what counts as a fact",
    )

    sealable = score["verdict"] in {scorer.PASS, scorer.FAIL}
    matrix.record(
        "verdict_is_sealable",
        PASS if sealable else FAIL,
        evidence=score.get("candidate_pool_digest") if sealable else None,
        detail=(
            f"scorer returned {score['verdict']}"
            + ("" if sealable else "; the census did not establish a total")
        ),
    )
    return matrix


def _from_flag(matrix, name, artifact, predicate, pointer, detail):
    """UNPROVEN when the artifact is absent; never a silent pass, never a FAIL."""
    if artifact is None:
        matrix.record(
            name, UNPROVEN, evidence=None,
            detail=f"no artifact was supplied, so this was never evaluated: {detail}",
        )
        return
    satisfied = bool(predicate(artifact))
    matrix.record(
        name,
        PASS if satisfied else FAIL,
        evidence=pointer(artifact) if satisfied else None,
        detail=detail,
    )
