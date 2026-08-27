"""Per-pair rebuild comparison — the library E5 and E6 are answered from.

SFI1 returned FAIL and two of the three grounds were absences: E5 and E6 were
`SKIPPED_NEVER_EXERCISED` because nothing in that run rebuilt artifacts from raw
payloads. Founder ruling, 2026-08-23:

    V2 PASS requires all E1-E7 to be exercised and met where applicable. E5/E6
    may not be SKIPPED. Required: confirmed selective stale escape = 0;
    selective == clean full rebuild on every judged supported pair.

This module makes those two questions answerable for one revision pair, and
nothing else. It is a library on purpose: it writes no receipt, keeps no cache,
holds no global state and cannot fetch. A comparison module that can acquire can
quietly extend a cohort, and a comparison module that caches can answer a pair
with another pair's state.

**The escape definition does not drift.** `tools/forensic_stale_escape.py` is the
production-only confirmation the founder already accepted, and its definition is
reproduced here exactly:

    moved      = keys whose production CLEAN FULL REBUILD value differs between
                 the two revisions, over the union of both key sets
    carried    = `run_pair(...)["carried_forward_set"]`
    confirmed  = sorted(moved & carried)

**Equivalence is strictly stronger than the forensic tool's disagreement set.**
The forensic tool compares the selective state against the clean rebuild of
AFTER for the keys the selective state happens to contain. E6 says *every*
artifact key, so the comparison here is over the union of both key sets: a key
the clean rebuild produced and the selective path never emitted at all is a
disagreement here and is invisible there. The forensic tool's own subset is
reported alongside as `forensic_disagreements` so the two numbers can be read
against each other rather than one silently replacing the other.

**Three outcomes, and only one of them can be a pass.**

    JUDGED_SUPPORTED    both endpoints were measured on this pair
    JUDGED_UNSUPPORTED  the pair carries a construct the declared grammar does
                        not cover (an `UNSUPPORTED_CONSTRUCT` fact on either
                        side). The comparison still ran and its numbers are
                        recorded, but the pair fails closed: it is never counted
                        towards a met endpoint, because a result about a
                        document we cannot fully represent is not evidence about
                        a supported one.
    UNJUDGED            the comparison could not be performed at all — empty or
                        undecodable payload, empty canonicalisation, a raw
                        payload that is not the one the document was built from,
                        or an engine exception. Always reported, never dropped,
                        never a pass.

The difference between the last two is *whether the comparison ran*, not how bad
the pair is. A study that counts unjudged pairs as clean is the failure this
whole programme exists to prevent, so they are counted separately and by reason.

**Gate power is reported per pair.** A pair whose clean rebuild moved nothing
cannot exhibit a stale escape, and a pair whose selective path carried nothing
forward cannot exhibit a divergence of the kind E6 is about. An endpoint no pair
could have violated has not been met — it has been avoided, which is precisely
what `SKIPPED_NEVER_EXERCISED` means upstream.
"""

from __future__ import annotations

import hashlib
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "compiler")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import selective_build as engine  # noqa: E402
from source_fact_ir import fingerprint as fp  # noqa: E402
from source_fact_ir import ir  # noqa: E402

SCHEMA = "tavonel.v2.rebuild_equivalence.v1"

JUDGED_SUPPORTED = "JUDGED_SUPPORTED"
JUDGED_UNSUPPORTED = "JUDGED_UNSUPPORTED_FAILS_CLOSED"
UNJUDGED = "UNJUDGED"

#: Reasons a pair cannot be judged. Enumerated so the summary can group by them
#: rather than by a free-text string that differs per pair.
EMPTY_RAW = "EMPTY_RAW_PAYLOAD"
UNDECODABLE_RAW = "UNDECODABLE_PAYLOAD"
EMPTY_CANONICALISATION = "EMPTY_CANONICALISATION"
DIGEST_MISMATCH = "RAW_DOES_NOT_MATCH_DOCUMENT_DIGEST"
ENGINE_EXCEPTION = "ENGINE_EXCEPTION"

UNSUPPORTED_CONSTRUCT_PRESENT = "UNSUPPORTED_CONSTRUCT_PRESENT"


def _sha256(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class RebuildVerdict:
    """One revision pair, judged. Every field is evidence, not a summary.

    Disagreements and escapes are carried as the exact keys rather than as
    counts: a count cannot be checked against a rebuild, and the founder's
    ruling is about named artifacts.
    """

    lineage_id: str
    before_version: str
    after_version: str
    status: str
    reason: str | None
    detail: str | None

    before_sha256: str
    after_sha256: str

    #: (a) the clean full rebuild of each revision, independently.
    clean_before_keys: tuple[str, ...]
    clean_after_keys: tuple[str, ...]
    clean_moved: tuple[str, ...]

    #: (b) the production selective execution.
    selective_rebuilt: tuple[str, ...]
    selective_carried: tuple[str, ...]
    selective_unplanned_missing: tuple[str, ...]
    selective_state_hash: str | None

    #: (c) E5 and (d) E6.
    confirmed_stale_artifacts: tuple[str, ...]
    disagreeing_keys: tuple[str, ...]
    forensic_disagreements: tuple[str, ...]

    #: gate power — what this pair could have exhibited at all.
    escape_gate_power: bool
    equivalence_gate_power: bool

    #: (e) the typed cross-check.
    typed_invalidated: tuple[str, ...]
    typed_under_invalidated: tuple[str, ...]
    typed_over_invalidated: tuple[str, ...]
    typed_silent_facts: tuple[str, ...]
    typed_named_every_moved_artifact: bool
    typed_cross_check_error: str | None

    #: (f) E8 and (g) E9, carried through from the production engine rather than
    #: recomputed here. `selective_build.run_pair` already emits both -- the
    #: per-stage carry-forward observations and the per-pair channel closure --
    #: and recomputing either in this module would be a second implementation of
    #: the same step, which is how a comparison quietly stops describing the
    #: thing it claims to describe. Defaulted so `_unjudged` keeps constructing
    #: a verdict with no execution evidence, which is the honest shape for a pair
    #: that never ran.
    carry_observations: tuple[Mapping[str, Any], ...] = ()
    e9_closure: Mapping[str, Any] | None = None

    @property
    def e8_violated(self) -> tuple[str, ...]:
        """Artifacts required-to-rebuild and carried forward unexecuted, at any
        stage. Named, never counted: a count cannot be checked against a rebuild."""
        seen: set[str] = set()
        for record in self.carry_observations:
            seen.update(record.get("violated") or ())
        return tuple(sorted(seen))

    @property
    def e8_gate_power(self) -> bool:
        """Was this pair in a position to exhibit an unexecuted carry at all?

        True only when some stage saw `required_to_rebuild` and `carried_forward`
        actually intersect. On today's engine the classification loop makes those
        two disjoint by construction, so this reads False on every natural pair --
        which is the honest reading of a structurally closed seam, and exactly
        why E8 is a veto that credits nothing rather than a scored endpoint.
        """
        return any(record.get("could_have_exhibited") for record in self.carry_observations)

    @property
    def e8_stages(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                str(record.get("stage"))
                for record in self.carry_observations
                if record.get("stage")
            )
        )

    @property
    def e9_gate_power(self) -> bool:
        """A detected typed change whose contract verdict is a non-empty seed
        set, so a silent disappearance was reachable here. Not "this pair was
        judged", and not "a violation occurred"."""
        return bool(self.e9_closure and self.e9_closure.get("could_have_exhibited"))

    @property
    def e9_silent(self) -> tuple[str, ...]:
        if not self.e9_closure:
            return ()
        return tuple(self.e9_closure.get("silent") or ())

    @property
    def judged(self) -> bool:
        """Judged means the comparison ran, supported or not."""
        return self.status in (JUDGED_SUPPORTED, JUDGED_UNSUPPORTED)

    @property
    def counts_towards_an_endpoint(self) -> bool:
        """Only a judged *supported* pair can make an endpoint met."""
        return self.status == JUDGED_SUPPORTED

    @property
    def confirmed_escape(self) -> bool:
        return bool(self.confirmed_stale_artifacts)

    @property
    def exactly_equivalent(self) -> bool:
        """Never true for a pair that was not judged — absence is not equality."""
        return self.judged and not self.disagreeing_keys

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "lineage_id": self.lineage_id,
            "before_version": self.before_version,
            "after_version": self.after_version,
            "status": self.status,
            "reason": self.reason,
            "detail": self.detail,
            "before_sha256": self.before_sha256,
            "after_sha256": self.after_sha256,
            "clean_full_rebuild": {
                "artifacts_before": len(self.clean_before_keys),
                "artifacts_after": len(self.clean_after_keys),
                "artifacts_that_moved": list(self.clean_moved),
                "artifacts_that_moved_count": len(self.clean_moved),
            },
            "selective": {
                "rebuilt": list(self.selective_rebuilt),
                "carried_forward": list(self.selective_carried),
                "unplanned_missing": list(self.selective_unplanned_missing),
                "state_hash": self.selective_state_hash,
            },
            "confirmed_stale_artifacts": list(self.confirmed_stale_artifacts),
            "confirmed_escape": self.confirmed_escape,
            "disagreeing_keys": list(self.disagreeing_keys),
            "forensic_disagreements": list(self.forensic_disagreements),
            "exactly_equivalent": self.exactly_equivalent,
            "escape_gate_power": self.escape_gate_power,
            "equivalence_gate_power": self.equivalence_gate_power,
            "E8_carry_observations": [dict(record) for record in self.carry_observations],
            "E8_violated": list(self.e8_violated),
            "E8_gate_power": self.e8_gate_power,
            "E8_stages_observed": list(self.e8_stages),
            "E9_channel_closure": dict(self.e9_closure) if self.e9_closure else None,
            "E9_silent_disappearance": list(self.e9_silent),
            "E9_gate_power": self.e9_gate_power,
            "typed_cross_check": {
                "invalidated": list(self.typed_invalidated),
                "under_invalidated": list(self.typed_under_invalidated),
                "over_invalidated": list(self.typed_over_invalidated),
                "silent_facts": list(self.typed_silent_facts),
                "named_every_moved_artifact": self.typed_named_every_moved_artifact,
                "error": self.typed_cross_check_error,
            },
        }


def _identity(document: Mapping[str, Any]) -> tuple[str, str]:
    return str(document.get("source_id", "")), str(document.get("version_id", ""))


def _unjudged(
    *,
    before_document: Mapping[str, Any],
    after_document: Mapping[str, Any],
    before_raw: bytes,
    after_raw: bytes,
    reason: str,
    detail: str,
) -> RebuildVerdict:
    lineage, after_version = _identity(after_document)
    _, before_version = _identity(before_document)
    return RebuildVerdict(
        lineage_id=lineage or _identity(before_document)[0],
        before_version=before_version,
        after_version=after_version,
        status=UNJUDGED,
        reason=reason,
        detail=detail,
        before_sha256=_sha256(before_raw),
        after_sha256=_sha256(after_raw),
        clean_before_keys=(),
        clean_after_keys=(),
        clean_moved=(),
        selective_rebuilt=(),
        selective_carried=(),
        selective_unplanned_missing=(),
        selective_state_hash=None,
        confirmed_stale_artifacts=(),
        disagreeing_keys=(),
        forensic_disagreements=(),
        #: an unjudged pair exhibits nothing and must not add gate power. A
        #: cohort that could only fail on pairs it never judged has no gate.
        escape_gate_power=False,
        equivalence_gate_power=False,
        typed_invalidated=(),
        typed_under_invalidated=(),
        typed_over_invalidated=(),
        typed_silent_facts=(),
        typed_named_every_moved_artifact=False,
        typed_cross_check_error=None,
    )


def _input_refusal(
    side: str, document: Mapping[str, Any], raw: bytes
) -> tuple[str, str] | None:
    """Why this side cannot be compared, or None.

    The digest check is here because the two arguments can disagree: a document
    built from other bytes than the ones handed in would be compared against a
    clean rebuild of something else, and the resulting equivalence claim would
    be about a pairing that never existed.
    """
    if not raw:
        return EMPTY_RAW, f"the {side} raw payload is empty"
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError as error:
        #: not swallowed — the reason becomes the verdict.
        return UNDECODABLE_RAW, f"the {side} raw payload is not utf-8: {error}"
    if not document.get("units"):
        return (
            EMPTY_CANONICALISATION,
            f"the {side} revision canonicalised to no units, so there is nothing to build",
        )
    declared = document.get("source_digest")
    if declared and declared != _sha256(raw):
        return (
            DIGEST_MISMATCH,
            f"the {side} document declares {declared} and the raw payload is {_sha256(raw)}",
        )
    return None


def _typed_cross_check(
    before_facts: Sequence[ir.SourceFact],
    after_facts: Sequence[ir.SourceFact],
    clean_before: Mapping[str, str],
    clean_after: Mapping[str, str],
) -> tuple[fp.AlignmentReport | None, str | None]:
    """Would the typed IR have named every artifact the clean rebuild moved?

    `fp.aligned` rather than `fp.assert_aligned`: this is the measurement, and a
    raise here would convert "the IR would not have prevented it" — the number
    the whole repair is judged on — into an unjudged pair, losing exactly the
    observation that matters. `assert_aligned` remains the right call for a
    caller that is gating rather than measuring.
    """
    try:
        return fp.aligned(list(before_facts), list(after_facts), clean_before, clean_after), None
    except Exception as error:  # recorded by type, never ignored
        return None, f"{type(error).__name__}: {error}"


def judge_pair(
    *,
    before_document: Mapping[str, Any],
    after_document: Mapping[str, Any],
    before_raw: bytes,
    after_raw: bytes,
    before_facts: Sequence[ir.SourceFact],
    after_facts: Sequence[ir.SourceFact],
) -> RebuildVerdict:
    """Judge one revision pair against E5, E6 and the typed cross-check.

    Nothing is fetched, nothing is written, nothing is remembered between calls.
    """
    for side, document, raw in (
        ("before", before_document, before_raw),
        ("after", after_document, after_raw),
    ):
        refusal = _input_refusal(side, document, raw)
        if refusal is not None:
            return _unjudged(
                before_document=before_document,
                after_document=after_document,
                before_raw=before_raw,
                after_raw=after_raw,
                reason=refusal[0],
                detail=refusal[1],
            )

    try:
        #: (a) the production clean full rebuild of each revision, from that
        #: revision alone: no prior state, no plan, no cross-talk.
        clean_before = engine.build_all(dict(before_document))
        clean_after = engine.build_all(dict(after_document))
        #: (b) the production selective execution on the same documents.
        selective = engine.run_pair(dict(before_document), dict(after_document))
    except Exception as error:  # becomes the verdict, not a pass
        return _unjudged(
            before_document=before_document,
            after_document=after_document,
            before_raw=before_raw,
            after_raw=after_raw,
            reason=ENGINE_EXCEPTION,
            detail=f"{type(error).__name__}: {error}",
        )

    #: The forensic tool's definition, character for character in meaning: the
    #: union of both key sets, a key present on only one side counting as moved.
    moved = sorted(
        artifact
        for artifact in set(clean_after) | set(clean_before)
        if clean_after.get(artifact) != clean_before.get(artifact)
    )
    carried = set(selective["carried_forward_set"])

    #: (c) E5.
    confirmed = tuple(artifact for artifact in moved if artifact in carried)

    #: (d) E6, over the union — see the module docstring for why this is not the
    #: forensic tool's subset.
    state: Mapping[str, str] = selective["state"]
    disagreeing = tuple(
        sorted(
            artifact
            for artifact in set(state) | set(clean_after)
            if state.get(artifact) != clean_after.get(artifact)
        )
    )
    forensic_disagreements = tuple(
        sorted(
            artifact
            for artifact in state
            if artifact in clean_after and state[artifact] != clean_after[artifact]
        )
    )

    #: (e) the typed cross-check, against the two clean rebuilds. Handing it the
    #: selective state would compare the selective path against itself.
    report, cross_check_error = _typed_cross_check(
        before_facts, after_facts, clean_before, clean_after
    )

    unsupported = [
        fact
        for fact in (*before_facts, *after_facts)
        if fact.kind == ir.UNSUPPORTED_CONSTRUCT
    ]

    lineage, after_version = _identity(after_document)
    _, before_version = _identity(before_document)
    return RebuildVerdict(
        lineage_id=lineage,
        before_version=before_version,
        after_version=after_version,
        status=JUDGED_UNSUPPORTED if unsupported else JUDGED_SUPPORTED,
        reason=UNSUPPORTED_CONSTRUCT_PRESENT if unsupported else None,
        detail=(
            f"{len(unsupported)} unsupported construct(s): "
            + ", ".join(sorted({fact.witness.construct for fact in unsupported})[:5])
            if unsupported
            else None
        ),
        before_sha256=_sha256(before_raw),
        after_sha256=_sha256(after_raw),
        clean_before_keys=tuple(sorted(clean_before)),
        clean_after_keys=tuple(sorted(clean_after)),
        clean_moved=tuple(moved),
        selective_rebuilt=tuple(sorted(selective["selective_rebuild_set"])),
        selective_carried=tuple(sorted(carried)),
        selective_unplanned_missing=tuple(sorted(selective["unplanned_missing"])),
        selective_state_hash=selective["state_hash"],
        confirmed_stale_artifacts=confirmed,
        disagreeing_keys=disagreeing,
        forensic_disagreements=forensic_disagreements,
        #: an escape needs both an artifact that moved and something carried
        #: forward for it to hide in.
        escape_gate_power=bool(moved) and bool(carried),
        #: a run that rebuilt everything is equivalent by construction and
        #: proves nothing about carrying forward.
        equivalence_gate_power=bool(carried) or bool(selective["unplanned_missing"]),
        typed_invalidated=report.invalidated if report else (),
        typed_under_invalidated=report.under_invalidated if report else (),
        typed_over_invalidated=report.over_invalidated if report else (),
        typed_silent_facts=report.silent_facts if report else (),
        typed_named_every_moved_artifact=bool(report) and not report.under_invalidated,
        typed_cross_check_error=cross_check_error,
        carry_observations=tuple(selective.get("carry_observations") or ()),
        e9_closure=selective.get("e9_channel_closure"),
    )


def _pair_label(verdict: RebuildVerdict) -> dict[str, str]:
    return {
        "lineage_id": verdict.lineage_id,
        "before_version": verdict.before_version,
        "after_version": verdict.after_version,
    }


def summarise(verdicts: Sequence[RebuildVerdict]) -> dict[str, Any]:
    """The aggregates E5 and E6 are scored from, each with its gate power.

    `pairs_that_could_have_exhibited` is the denominator that decides whether an
    endpoint may be called met at all. Zero there means the cohort never put the
    endpoint at risk, and the scorer must report it as never exercised rather
    than as met — which is the distinction SFI1's FAIL turned on.

    Every count here is taken over judged *supported* pairs only. Unsupported
    and unjudged pairs are listed in full so nothing is dropped, and any escape
    or divergence found in them is surfaced under `outside_supported` where it
    is visible without being counted as evidence for a supported cohort.
    """
    supported = [row for row in verdicts if row.counts_towards_an_endpoint]
    unsupported = [row for row in verdicts if row.status == JUDGED_UNSUPPORTED]
    unjudged = [row for row in verdicts if row.status == UNJUDGED]

    unjudged_by_reason: dict[str, int] = {}
    for row in unjudged:
        key = row.reason or "UNSTATED"
        unjudged_by_reason[key] = unjudged_by_reason.get(key, 0) + 1

    escape_power = [row for row in supported if row.escape_gate_power]
    escaped = [row for row in supported if row.confirmed_escape]
    equivalence_power = [row for row in supported if row.equivalence_gate_power]
    divergent = [row for row in supported if row.disagreeing_keys]

    #: E8 and E9, over judged *supported* pairs only, same denominator rule as
    #: E5/E6 above.
    e8_power = [row for row in supported if row.e8_gate_power]
    e8_violating = [row for row in supported if row.e8_violated]
    e8_stages: set[str] = set()
    for row in supported:
        e8_stages.update(row.e8_stages)

    e9_power = [row for row in supported if row.e9_gate_power]
    e9_silent_pairs = [row for row in supported if row.e9_silent]
    e9_unresolved = [
        row
        for row in supported
        if (row.e9_closure or {}).get("unresolved_facet_changes")
    ]

    cross_checked = [row for row in supported if row.typed_cross_check_error is None]
    cross_check_errors: dict[str, int] = {}
    for row in supported:
        if row.typed_cross_check_error is not None:
            key = row.typed_cross_check_error.split(":", 1)[0]
            cross_check_errors[key] = cross_check_errors.get(key, 0) + 1

    return {
        "schema": SCHEMA,
        "pairs_total": len(verdicts),
        "pairs_judged": len(supported) + len(unsupported),
        "pairs_judged_supported": len(supported),
        "pairs_unsupported": len(unsupported),
        "pairs_unjudged": len(unjudged),
        "unjudged_by_reason": dict(sorted(unjudged_by_reason.items())),
        "unjudged_pairs": [
            {**_pair_label(row), "reason": row.reason, "detail": row.detail}
            for row in unjudged
        ],
        "unsupported_pairs": [
            {**_pair_label(row), "reason": row.reason, "detail": row.detail}
            for row in unsupported
        ],
        "E5_confirmed_selective_stale_escape": {
            "pairs_that_could_have_exhibited": len(escape_power),
            "pairs_with_confirmed_escape": len(escaped),
            "confirmed_artifacts_total": sum(
                len(row.confirmed_stale_artifacts) for row in escaped
            ),
            "confirmed": [
                {**_pair_label(row), "artifacts": list(row.confirmed_stale_artifacts)}
                for row in escaped
            ],
            "gate_power": bool(escape_power),
        },
        "E6_exact_selective_vs_clean_equivalence": {
            "pairs_that_could_have_exhibited": len(equivalence_power),
            "pairs_exactly_equivalent": sum(1 for row in supported if row.exactly_equivalent),
            "pairs_divergent": len(divergent),
            "divergent": [
                {**_pair_label(row), "keys": list(row.disagreeing_keys)} for row in divergent
            ],
            "gate_power": bool(equivalence_power),
        },
        #: E8 -- the mandatory safety veto. Never a positive endpoint: a clean
        #: reading here credits nothing towards a PASS and only a violation can
        #: veto one. `stages_checked` is the union of stages any supported pair
        #: actually observed, because an invariant watched at one of its two
        #: declared stages reports zero violations while leaving the other path
        #: unwatched -- a failure of the instrument, not an absence of defects.
        "E8_rebuild_required_carried_without_execution": {
            "pairs_that_could_have_exhibited": len(e8_power),
            "pairs_with_unexecuted_carry": len(e8_violating),
            "carried": [
                {**_pair_label(row), "artifacts": list(row.e8_violated)}
                for row in e8_violating
            ],
            "gate_power": bool(e8_power),
            "stages_checked": sorted(e8_stages),
            "reading": (
                "zero violations with gate_power False means the seam is "
                "structurally closed and this cohort could not have exhibited the "
                "failure. That is not evidence the invariant holds under a "
                "scheduler defect; it is evidence the invariant was not at risk"
            ),
        },
        #: E9 -- a primary endpoint, and the one that must not be read off the
        #: planner. The expected side is the declarative dependency contract's
        #: own traversal; the actual side is production's rebuild request.
        "E9_detected_change_without_rebuild_request": {
            "pairs_that_could_have_exhibited": len(e9_power),
            "pairs_with_silent_disappearance": len(e9_silent_pairs),
            "silent": [
                {**_pair_label(row), "artifacts": list(row.e9_silent)}
                for row in e9_silent_pairs
            ],
            "gate_power": bool(e9_power),
            "pairs_with_an_unresolved_facet_change": len(e9_unresolved),
            "unresolved": [
                {
                    **_pair_label(row),
                    "changes": list((row.e9_closure or {}).get("unresolved_facet_changes") or []),
                }
                for row in e9_unresolved
            ],
            "expected_side_source": (
                "dependency_contract.decide_unit_change / .decide_structural, over "
                "declared facet sensitivity. Never RecompilationPlan.to_rebuild, "
                "which would make the comparison an identity"
            ),
        },
        "typed_cross_check": {
            "pairs_evaluated": len(cross_checked),
            "pairs_named_every_moved_artifact": sum(
                1 for row in cross_checked if row.typed_named_every_moved_artifact
            ),
            "pairs_under_invalidated": sum(
                1 for row in cross_checked if row.typed_under_invalidated
            ),
            "pairs_with_silent_facts": sum(
                1 for row in cross_checked if row.typed_silent_facts
            ),
            "artifacts_moved_total": sum(len(row.clean_moved) for row in cross_checked),
            "artifacts_under_invalidated_total": sum(
                len(row.typed_under_invalidated) for row in cross_checked
            ),
            "under_invalidated": [
                {**_pair_label(row), "keys": list(row.typed_under_invalidated)}
                for row in cross_checked
                if row.typed_under_invalidated
            ],
            "errors": dict(sorted(cross_check_errors.items())),
        },
        "outside_supported": {
            "confirmed_escapes": [
                {**_pair_label(row), "status": row.status,
                 "artifacts": list(row.confirmed_stale_artifacts)}
                for row in unsupported
                if row.confirmed_escape
            ],
            "divergent": [
                {**_pair_label(row), "status": row.status, "keys": list(row.disagreeing_keys)}
                for row in unsupported
                if row.disagreeing_keys
            ],
        },
    }
