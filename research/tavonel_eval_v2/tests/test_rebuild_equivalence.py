"""E5 and E6 — the per-pair rebuild comparison.

The single most important test in this file is the synthetic stale escape. An
escape detector that has never seen an escape has not been tested: the real
cohort may contain none, and a detector that always returns "clean" is
indistinguishable from a correct one on such a cohort. So the selective path is
wrapped to carry an artifact the clean rebuild moved, and the detector is
required to confirm it.

The rest of the file pins the two ways this module could report a false clean:
counting a pair it could not judge as a pass, and calling an endpoint met on a
cohort where no pair could have violated it.

No network. Documents are built from inline byte fixtures through the production
canonicaliser, so the artifact keys are the production keys rather than keys
this test invented.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Any

import pytest

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "canonicalization"), str(NS / "compiler")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

from canonicalization.canonical_document import canonical_document  # noqa: E402
from compiler import rebuild_equivalence as reb  # noqa: E402
from source_fact_ir import ir  # noqa: E402

LINEAGE = "lineage:test/rebuild-equivalence"

#: Sections have to clear `canonical_document.MIN_TEXT_CHARS`, so the fixtures
#: are verbose on purpose rather than by accident.
BODY_ONE = (
    "The first section states a rule about retention windows and the authority that "
    "issued it, at sufficient length that the canonicaliser keeps it as a unit rather "
    "than discarding it as boilerplate."
)
BODY_TWO = (
    "The second section describes the reporting obligation, its effective date and the "
    "office responsible, again at sufficient length that the canonicaliser keeps it as "
    "a unit of its own."
)


def markdown(first: str, second: str) -> bytes:
    return f"# Alpha\n\n{first}\n\n# Beta\n\n{second}\n".encode()


def document(raw: bytes, version: str) -> dict[str, Any]:
    return canonical_document(
        source_family="generic_markdown",
        source_id=LINEAGE,
        version_id=version,
        payload=raw,
        source_digest="sha256:" + hashlib.sha256(raw).hexdigest(),
        known_at="2026-08-23T00:00:00Z",
        valid_from="2026-08-23T00:00:00Z",
        licence="test",
    )


def facts(doc: dict[str, Any]) -> list[ir.SourceFact]:
    """One CONTENT_TEXT fact per unit, anchored the way link 4 expects.

    Built here rather than imported from an extractor lane: the comparison must
    be checkable without standing up extraction, and depending on it would mean
    E5/E6 could only be tested once the thing they guard already shipped.
    """
    return [
        ir.SourceFact(
            kind=ir.CONTENT_TEXT,
            witness=ir.Witness(
                construct="section",
                byte_start=unit["ordinal"] * 1000,
                byte_end=unit["ordinal"] * 1000 + len(unit["text"]),
                unit_path=ir.unit_path_for(doc["source_id"], unit["explicit_path"]),
            ),
            state=ir.REPRESENTED,
            representation={"text": unit["text"]},
        )
        for unit in doc["units"]
    ]


def judge(before_raw: bytes, after_raw: bytes) -> reb.RebuildVerdict:
    before_doc = document(before_raw, "v1")
    after_doc = document(after_raw, "v2")
    return reb.judge_pair(
        before_document=before_doc,
        after_document=after_doc,
        before_raw=before_raw,
        after_raw=after_raw,
        before_facts=facts(before_doc),
        after_facts=facts(after_doc),
    )


UNCHANGED = markdown(BODY_ONE, BODY_TWO)
CHANGED = markdown(BODY_ONE, BODY_TWO.replace("reporting obligation", "disclosure duty"))


# --- 1. a pair where nothing changed ---------------------------------------


def test_unchanged_pair_has_no_escape_and_no_gate_power() -> None:
    verdict = judge(UNCHANGED, UNCHANGED)

    assert verdict.status == reb.JUDGED_SUPPORTED
    assert verdict.clean_moved == ()
    assert verdict.confirmed_stale_artifacts == ()
    assert verdict.exactly_equivalent
    #: the point of the test: this pair could not have exhibited an escape, so
    #: its clean result is not evidence that the detector works.
    assert verdict.escape_gate_power is False
    assert verdict.typed_named_every_moved_artifact is True


# --- 2. a real content change ----------------------------------------------


def test_content_change_rebuilds_the_moved_artifact_with_gate_power() -> None:
    verdict = judge(UNCHANGED, CHANGED)

    assert verdict.status == reb.JUDGED_SUPPORTED
    assert len(verdict.clean_moved) == 1
    moved = verdict.clean_moved[0]
    assert moved.startswith("section:")
    assert moved in verdict.selective_rebuilt
    assert moved not in verdict.selective_carried
    assert verdict.confirmed_stale_artifacts == ()
    assert verdict.exactly_equivalent
    assert verdict.escape_gate_power is True
    assert verdict.equivalence_gate_power is True
    #: the typed delta named the artifact the clean rebuild moved, which is the
    #: number that says the IR would have prevented the escape.
    assert moved in verdict.typed_invalidated
    assert verdict.typed_under_invalidated == ()


# --- 3. a synthetic stale escape -------------------------------------------


def _carry_forward(monkeypatch: pytest.MonkeyPatch, victim_prefix: str) -> None:
    """Wrap the production selective path so it carries a moved artifact.

    This is the defect being simulated, stated exactly as the forensic tool
    defines it: the clean rebuild moved the artifact and the selective execution
    left the previous value in the state.
    """
    real_run_pair = reb.engine.run_pair
    real_build_all = reb.engine.build_all

    def wrapped(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
        result = real_run_pair(before, after)
        prior = real_build_all(before)
        victims = [key for key in result["selective_rebuild_set"] if key.startswith(victim_prefix)]
        assert victims, "the fixture must rebuild something for the escape to be planted in"
        victim = victims[0]
        result["selective_rebuild_set"] = [
            key for key in result["selective_rebuild_set"] if key != victim
        ]
        result["carried_forward_set"] = sorted([*result["carried_forward_set"], victim])
        result["state"][victim] = prior[victim]
        return result

    monkeypatch.setattr(reb.engine, "run_pair", wrapped)


def test_synthetic_stale_escape_is_confirmed(monkeypatch: pytest.MonkeyPatch) -> None:
    _carry_forward(monkeypatch, "section:")
    verdict = judge(UNCHANGED, CHANGED)

    assert verdict.status == reb.JUDGED_SUPPORTED
    assert verdict.confirmed_escape is True
    assert verdict.confirmed_stale_artifacts == verdict.clean_moved
    #: an escape is also a divergence: the state does not equal the clean
    #: rebuild of AFTER. E5 and E6 are different questions, not the same one.
    assert verdict.disagreeing_keys == verdict.clean_moved
    assert verdict.escape_gate_power is True

    summary = reb.summarise([verdict])
    escape = summary["E5_confirmed_selective_stale_escape"]
    assert escape["pairs_with_confirmed_escape"] == 1
    assert escape["confirmed"][0]["lineage_id"] == LINEAGE
    assert escape["confirmed"][0]["artifacts"] == list(verdict.clean_moved)


# --- 4. the engine raises ---------------------------------------------------


def test_engine_exception_is_unjudged_and_never_a_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("the plan could not be computed")

    monkeypatch.setattr(reb.engine, "run_pair", explode)
    verdict = judge(UNCHANGED, CHANGED)

    assert verdict.status == reb.UNJUDGED
    assert verdict.reason == reb.ENGINE_EXCEPTION
    assert verdict.detail is not None
    assert "RuntimeError" in verdict.detail
    assert verdict.exactly_equivalent is False
    assert verdict.escape_gate_power is False

    summary = reb.summarise([verdict])
    assert summary["pairs_judged_supported"] == 0
    assert summary["pairs_unjudged"] == 1
    assert summary["unjudged_by_reason"] == {reb.ENGINE_EXCEPTION: 1}
    assert summary["E6_exact_selective_vs_clean_equivalence"]["pairs_exactly_equivalent"] == 0
    #: an unjudged pair puts no endpoint at risk, so it must not manufacture the
    #: gate power that would let the endpoint be called met.
    assert summary["E5_confirmed_selective_stale_escape"]["gate_power"] is False


def test_empty_payload_is_unjudged_with_its_own_reason() -> None:
    before_doc = document(UNCHANGED, "v1")
    verdict = reb.judge_pair(
        before_document=before_doc,
        after_document=document(CHANGED, "v2"),
        before_raw=b"",
        after_raw=CHANGED,
        before_facts=facts(before_doc),
        after_facts=[],
    )
    assert verdict.status == reb.UNJUDGED
    assert verdict.reason == reb.EMPTY_RAW


def test_raw_that_is_not_the_document_is_unjudged() -> None:
    """A document built from other bytes would be compared against a rebuild of
    something else, and the equivalence claim would be about a pairing that
    never existed."""
    before_doc = document(UNCHANGED, "v1")
    after_doc = document(CHANGED, "v2")
    verdict = reb.judge_pair(
        before_document=before_doc,
        after_document=after_doc,
        before_raw=UNCHANGED,
        after_raw=UNCHANGED,
        before_facts=facts(before_doc),
        after_facts=facts(after_doc),
    )
    assert verdict.status == reb.UNJUDGED
    assert verdict.reason == reb.DIGEST_MISMATCH


# --- 5. equivalence names the exact disagreeing key -------------------------


def test_equivalence_names_the_exact_disagreeing_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A divergence that is not an escape: the artifact was rebuilt, and the
    rebuild produced the wrong value. E6 must catch it and E5 must not claim it.
    """
    real_run_pair = reb.engine.run_pair
    corrupted: dict[str, str] = {}

    def wrapped(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
        result = real_run_pair(before, after)
        victim = sorted(result["selective_rebuild_set"])[0]
        corrupted["key"] = victim
        result["state"][victim] = "sha256:" + "0" * 64
        return result

    monkeypatch.setattr(reb.engine, "run_pair", wrapped)
    verdict = judge(UNCHANGED, CHANGED)

    assert verdict.disagreeing_keys == (corrupted["key"],)
    assert verdict.exactly_equivalent is False
    assert verdict.confirmed_stale_artifacts == ()
    assert verdict.forensic_disagreements == (corrupted["key"],)


def test_a_key_the_selective_state_never_emitted_is_a_disagreement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The half of E6 the forensic tool's subset cannot see."""
    real_run_pair = reb.engine.run_pair
    dropped: dict[str, str] = {}

    def wrapped(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
        result = real_run_pair(before, after)
        victim = sorted(result["state"])[0]
        dropped["key"] = victim
        del result["state"][victim]
        return result

    monkeypatch.setattr(reb.engine, "run_pair", wrapped)
    verdict = judge(UNCHANGED, CHANGED)

    assert verdict.disagreeing_keys == (dropped["key"],)
    #: invisible to the forensic tool's own comparison, which iterates the
    #: selective state — the key is not in it.
    assert verdict.forensic_disagreements == ()


# --- unsupported is judged, fails closed, and is not unjudged ---------------


def test_unsupported_construct_fails_closed_without_being_unjudged() -> None:
    before_doc = document(UNCHANGED, "v1")
    after_doc = document(CHANGED, "v2")
    after_facts = [
        *facts(after_doc),
        ir.SourceFact(
            kind=ir.UNSUPPORTED_CONSTRUCT,
            witness=ir.Witness(
                construct="math",
                byte_start=10,
                byte_end=40,
                unit_path=ir.unit_path_for(LINEAGE, after_doc["units"][0]["explicit_path"]),
            ),
            state=ir.UNRESOLVED,
            reason="no kind represents an expression tree",
        ),
    ]
    verdict = reb.judge_pair(
        before_document=before_doc,
        after_document=after_doc,
        before_raw=UNCHANGED,
        after_raw=CHANGED,
        before_facts=facts(before_doc),
        after_facts=after_facts,
    )

    assert verdict.status == reb.JUDGED_UNSUPPORTED
    assert verdict.reason == reb.UNSUPPORTED_CONSTRUCT_PRESENT
    assert verdict.judged is True
    #: the comparison ran — that is what makes it judged rather than unjudged —
    #: and it still may not count towards an endpoint.
    assert verdict.counts_towards_an_endpoint is False

    summary = reb.summarise([verdict])
    assert summary["pairs_judged"] == 1
    assert summary["pairs_judged_supported"] == 0
    assert summary["pairs_unsupported"] == 1
    assert summary["E5_confirmed_selective_stale_escape"]["gate_power"] is False


# --- 6. gate-power arithmetic ----------------------------------------------


def test_summarise_separates_pairs_that_could_fail_from_pairs_that_did(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    powerless = judge(UNCHANGED, UNCHANGED)
    powered = judge(UNCHANGED, CHANGED)
    _carry_forward(monkeypatch, "section:")
    escaped = judge(UNCHANGED, CHANGED)

    summary = reb.summarise([powerless, powered, escaped])

    assert summary["pairs_total"] == 3
    assert summary["pairs_judged_supported"] == 3
    escape = summary["E5_confirmed_selective_stale_escape"]
    #: two of the three pairs could have exhibited an escape; one did. The
    #: unchanged pair is not evidence either way and is excluded from both.
    assert escape["pairs_that_could_have_exhibited"] == 2
    assert escape["pairs_with_confirmed_escape"] == 1
    assert escape["gate_power"] is True

    equivalence = summary["E6_exact_selective_vs_clean_equivalence"]
    assert equivalence["pairs_that_could_have_exhibited"] == 3
    assert equivalence["pairs_exactly_equivalent"] == 2
    assert equivalence["pairs_divergent"] == 1
    assert equivalence["divergent"][0]["keys"] == list(escaped.clean_moved)

    cross = summary["typed_cross_check"]
    assert cross["pairs_evaluated"] == 3
    assert cross["pairs_named_every_moved_artifact"] == 3
    assert cross["artifacts_moved_total"] == 2
    assert cross["errors"] == {}


def test_summarise_reports_zero_gate_power_on_a_cohort_that_never_changed() -> None:
    summary = reb.summarise([judge(UNCHANGED, UNCHANGED), judge(UNCHANGED, UNCHANGED)])
    escape = summary["E5_confirmed_selective_stale_escape"]
    assert escape["pairs_with_confirmed_escape"] == 0
    #: zero escapes on a cohort with no gate power is not a met endpoint.
    assert escape["pairs_that_could_have_exhibited"] == 0
    assert escape["gate_power"] is False


# --- 7. determinism ---------------------------------------------------------


def test_the_same_inputs_produce_an_identical_verdict_dict() -> None:
    first = judge(UNCHANGED, CHANGED).as_dict()
    second = judge(UNCHANGED, CHANGED).as_dict()
    assert first == second

    #: and the summary over them, so no ordering leaks through the aggregate.
    assert reb.summarise([judge(UNCHANGED, CHANGED)]) == reb.summarise(
        [judge(UNCHANGED, CHANGED)]
    )
