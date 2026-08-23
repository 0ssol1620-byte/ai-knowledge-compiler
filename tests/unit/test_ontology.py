"""Tests for akc_cir.ontology — induction, §16.5 gates, §8.4 approval gate."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from akc_cir.ontology import (
    ALLOWED_ONTOLOGY_TRANSITIONS,
    ONTOLOGY_MANIFEST_FILENAME,
    ONTOLOGY_MANIFEST_SCHEMA_VERSION,
    CoOccurrence,
    CorpusStats,
    GateName,
    GateReport,
    GateThresholds,
    IllegalTransitionError,
    InductionConfig,
    LifecycleEvent,
    MissingReviewerNoteError,
    OntologyApprovalGate,
    OntologyManifestError,
    OntologySchema,
    OntologyState,
    OntologyStore,
    build_ontology_manifest,
    evaluate_quality_gates,
    propose,
    validate_lifecycle_history,
)
from pydantic import ValidationError

NOW = datetime(2026, 8, 23, 12, 0, 0, tzinfo=UTC)


def _payments_corpus() -> CorpusStats:
    mentions = {
        "Payment Gateway": 50,
        "Merchant Account": 40,
        "Chargeback": 30,
        "Settlement Report": 20,
        "Loyalty Program": 4,
        "Glider": 1,
    }
    co = [
        ("Chargeback", "Payment Gateway", 12),
        ("Merchant Account", "Payment Gateway", 18),
        ("Chargeback", "Merchant Account", 8),
        ("Payment Gateway", "Settlement Report", 6),
    ]
    return CorpusStats(
        corpus_id="corpus_payments_2026_08",
        document_count=40,
        entity_mentions=mentions,
        co_occurrences=[CoOccurrence(entity_a=a, entity_b=b, count=c) for a, b, c in co],
    )


def _full_gate() -> OntologyApprovalGate:
    return OntologyApprovalGate()


class TestInduction:
    def test_propose_induces_candidates_from_synthetic_corpus(self) -> None:
        stats = _payments_corpus()
        proposal = propose(stats, now=NOW)

        names = [candidate.name for candidate in proposal.entity_candidates]
        # Frequency-ranked, ties impossible here; "Glider" (freq 1) and
        # "Loyalty Program" (freq 4 < 3? no, 4 >= 3) — threshold is 3.
        assert names == [
            "Payment Gateway",
            "Merchant Account",
            "Chargeback",
            "Settlement Report",
            "Loyalty Program",
        ]
        assert proposal.method == "frequency_cooccurrence_v1"
        assert proposal.observed_document_count == 40
        top = proposal.entity_candidates[0]
        assert top.suggested_kind == "payment_gateway"
        assert top.mention_frequency == 50
        assert top.mention_share == pytest.approx(50 / 145)

        relation_pairs = {(rel.source, rel.target): rel for rel in proposal.relation_candidates}
        assert ("Merchant Account", "Payment Gateway") in relation_pairs
        strongest = relation_pairs[("Merchant Account", "Payment Gateway")]
        assert strongest.support == 18
        assert strongest.suggested_kind == "relates_to"
        assert strongest.affinity == pytest.approx(18 / 40)

    def test_propose_is_deterministic(self) -> None:
        stats = _payments_corpus()
        first = propose(stats, now=NOW)
        second = propose(stats, now=NOW)
        assert first == second
        assert first.proposal_id == second.proposal_id

    def test_proposal_id_tracks_inputs(self) -> None:
        stats = _payments_corpus()
        other = propose(stats.model_copy(update={"document_count": 41}), now=NOW)
        assert other.proposal_id != propose(stats, now=NOW).proposal_id

    def test_kind_slug_conflicts_get_deterministic_suffixes(self) -> None:
        stats = CorpusStats(
            corpus_id="corpus_dupes",
            document_count=10,
            entity_mentions={"Data Platform": 9, "data platform!": 8, "Data  Platform": 7},
        )
        proposal = propose(stats, now=NOW)
        kinds = [candidate.suggested_kind for candidate in proposal.entity_candidates]
        assert kinds == ["data_platform", "data_platform_2", "data_platform_3"]

    def test_empty_corpus_proposes_nothing_and_fails_gates(self) -> None:
        stats = CorpusStats(corpus_id="corpus_empty", document_count=0, entity_mentions={})
        proposal = propose(stats, now=NOW)
        assert proposal.entity_candidates == ()
        report = evaluate_quality_gates(proposal, stats)
        assert not report.all_passed
        assert GateName.COVERAGE in report.failed_gates


class TestQualityGates:
    def test_gates_pass_on_a_healthy_proposal(self) -> None:
        stats = _payments_corpus()
        proposal = propose(stats, now=NOW)
        report = evaluate_quality_gates(proposal, stats)
        assert report.proposal_id == proposal.proposal_id
        assert [r.gate for r in report.results] == list(GateName)
        assert report.all_passed, [(r.gate.value, r.detail) for r in report.results]

    def test_low_coverage_proposal_is_rejected(self) -> None:
        stats = _payments_corpus()
        # Only the single most frequent entity clears the bar, so the
        # proposal captures 50/145 of the mention mass — below 0.60.
        proposal = propose(
            stats,
            config=InductionConfig(min_mention_frequency=50, max_entity_kinds=1),
            now=NOW,
        )
        assert len(proposal.entity_candidates) == 1
        report = evaluate_quality_gates(proposal, stats)
        coverage = report.result_for(GateName.COVERAGE)
        assert not coverage.passed
        assert coverage.observed == pytest.approx(50 / 145)
        assert coverage.observed < coverage.threshold
        assert not report.all_passed
        assert report.failed_gates == (GateName.COVERAGE,)
        # The other two gates still get itemized verdicts.
        assert report.result_for(GateName.DISTINCTIVENESS).passed
        assert report.result_for(GateName.STABILITY).passed

    def test_stability_fails_when_candidates_diverge_from_prior(self) -> None:
        stats = _payments_corpus()
        first = propose(stats, now=NOW)
        drifted = propose(
            stats,
            config=InductionConfig(min_mention_frequency=30, max_entity_kinds=3),
            now=NOW,
        )
        report = evaluate_quality_gates(drifted, stats, previous_proposal=first)
        stability = report.result_for(GateName.STABILITY)
        assert not stability.passed
        assert "Jaccard" in stability.detail

    def test_thresholds_are_configurable(self) -> None:
        stats = _payments_corpus()
        proposal = propose(stats, now=NOW)
        # The healthy proposal captures 144/145 mentions (~0.993), so a
        # 0.999 coverage bar flips exactly the coverage gate.
        strict = GateThresholds(min_coverage=0.999)
        report = evaluate_quality_gates(proposal, stats, thresholds=strict)
        assert report.failed_gates == (GateName.COVERAGE,)
        assert report.result_for(GateName.COVERAGE).threshold == pytest.approx(0.999)

    def test_gate_report_must_cover_every_gate(self) -> None:
        stats = _payments_corpus()
        proposal = propose(stats, now=NOW)
        report = evaluate_quality_gates(proposal, stats)
        with pytest.raises(ValidationError):
            GateReport(proposal_id=report.proposal_id, results=report.results[:1])


class TestApprovalGateStateMachine:
    def test_allowed_transition_map_is_the_six_state_chain(self) -> None:
        assert ALLOWED_ONTOLOGY_TRANSITIONS[OntologyState.DRAFT] == frozenset(
            {OntologyState.PROPOSED}
        )
        assert ALLOWED_ONTOLOGY_TRANSITIONS[OntologyState.PROPOSED] == frozenset(
            {OntologyState.UNDER_REVIEW}
        )
        assert ALLOWED_ONTOLOGY_TRANSITIONS[OntologyState.UNDER_REVIEW] == frozenset(
            {OntologyState.APPROVED}
        )
        assert ALLOWED_ONTOLOGY_TRANSITIONS[OntologyState.APPROVED] == frozenset(
            {OntologyState.ACTIVE}
        )
        assert ALLOWED_ONTOLOGY_TRANSITIONS[OntologyState.ACTIVE] == frozenset(
            {OntologyState.RETIRED}
        )
        assert ALLOWED_ONTOLOGY_TRANSITIONS[OntologyState.RETIRED] == frozenset()

    def test_normal_lifecycle_passes(self) -> None:
        gate = _full_gate()
        steps = [
            (OntologyState.PROPOSED, None),
            (OntologyState.UNDER_REVIEW, None),
            (OntologyState.APPROVED, "Approved after §16.5 gates passed"),
            (OntologyState.ACTIVE, None),
            (OntologyState.RETIRED, None),
        ]
        for index, (target, note) in enumerate(steps):
            event = gate.transition(
                target,
                actor="reviewer-7",
                at=datetime(2026, 8, 23, 12, index, 0, tzinfo=UTC),
                reviewer_note=note,
            )
            assert event.to_state is target
        assert gate.state is OntologyState.RETIRED
        assert len(gate.history) == 5
        assert gate.history[2].reviewer_note == "Approved after §16.5 gates passed"

    def test_illegal_transitions_are_rejected(self) -> None:
        gate = _full_gate()
        with pytest.raises(IllegalTransitionError):
            gate.transition(
                OntologyState.UNDER_REVIEW, actor="r", at=NOW
            )  # DRAFT → UNDER_REVIEW skips PROPOSED
        with pytest.raises(IllegalTransitionError):
            gate.transition(OntologyState.ACTIVE, actor="r", at=NOW)  # skips the whole chain
        with pytest.raises(IllegalTransitionError):
            gate.transition(OntologyState.DRAFT, actor="r", at=NOW)  # self-transition

        reviewed = gate.transition(OntologyState.PROPOSED, actor="r", at=NOW)
        assert reviewed.from_state is OntologyState.DRAFT
        with pytest.raises(IllegalTransitionError):
            gate.transition(OntologyState.ACTIVE, actor="r", at=NOW)  # PROPOSED → ACTIVE

        retired = OntologyApprovalGate.from_history(
            [
                LifecycleEvent(
                    from_state=OntologyState.DRAFT,
                    to_state=OntologyState.PROPOSED,
                    actor="r",
                    at=NOW,
                ),
                LifecycleEvent(
                    from_state=OntologyState.PROPOSED,
                    to_state=OntologyState.UNDER_REVIEW,
                    actor="r",
                    at=NOW,
                ),
                LifecycleEvent(
                    from_state=OntologyState.UNDER_REVIEW,
                    to_state=OntologyState.APPROVED,
                    actor="r",
                    at=NOW,
                    reviewer_note="ok",
                ),
                LifecycleEvent(
                    from_state=OntologyState.APPROVED,
                    to_state=OntologyState.ACTIVE,
                    actor="r",
                    at=NOW,
                ),
                LifecycleEvent(
                    from_state=OntologyState.ACTIVE,
                    to_state=OntologyState.RETIRED,
                    actor="r",
                    at=NOW,
                ),
            ]
        )
        with pytest.raises(IllegalTransitionError):
            retired.transition(OntologyState.ACTIVE, actor="r", at=NOW)  # RETIRED is terminal

    def test_approved_without_reviewer_note_is_rejected(self) -> None:
        gate = _full_gate()
        gate.transition(OntologyState.PROPOSED, actor="r", at=NOW)
        gate.transition(OntologyState.UNDER_REVIEW, actor="r", at=NOW)
        with pytest.raises(MissingReviewerNoteError):
            gate.transition(OntologyState.APPROVED, actor="r", at=NOW)
        with pytest.raises(MissingReviewerNoteError):
            gate.transition(OntologyState.APPROVED, actor="r", at=NOW, reviewer_note="   ")
        # The guard lives on the event model too, not just the machine —
        # pydantic surfaces it as a ValidationError carrying the same message.
        with pytest.raises(ValidationError, match="reviewer note"):
            LifecycleEvent(
                from_state=OntologyState.UNDER_REVIEW,
                to_state=OntologyState.APPROVED,
                actor="r",
                at=NOW,
            )
        # And the state was not mutated by the rejected attempts.
        assert gate.state is OntologyState.UNDER_REVIEW

    def test_history_validation_rejects_tampered_chains(self) -> None:
        good = LifecycleEvent(
            from_state=OntologyState.DRAFT,
            to_state=OntologyState.PROPOSED,
            actor="r",
            at=NOW,
        )
        with pytest.raises(IllegalTransitionError):
            validate_lifecycle_history(
                [
                    good,
                    LifecycleEvent(
                        from_state=OntologyState.DRAFT,
                        to_state=OntologyState.PROPOSED,
                        actor="r",
                        at=NOW,
                    ),
                ]
            )
        with pytest.raises(IllegalTransitionError):
            OntologyApprovalGate(state=OntologyState.ACTIVE)
        with pytest.raises(IllegalTransitionError):
            OntologyApprovalGate(
                state=OntologyState.PROPOSED,
                history=[good],
            ).transition(OntologyState.APPROVED, actor="r", at=NOW)  # PROPOSED → APPROVED illegal


class TestSchema:
    def test_universal_core_seed_schema(self) -> None:
        schema = OntologySchema.universal_core()
        assert len(schema.entity_kinds) == 11
        assert schema.has_kind("entity", "organization")
        assert schema.has_kind("relation", "relates_to")

    def test_duplicate_kind_names_rejected(self) -> None:
        from akc_cir.ontology import KindDefinition, OntologyKindScope

        kind = KindDefinition(name="person", scope=OntologyKindScope.ENTITY, label="person")
        with pytest.raises(ValidationError):
            OntologySchema(entity_kinds=(kind, kind))


class TestPersistence:
    def test_manifest_roundtrip_and_hash_verification(self, tmp_path: Path) -> None:
        stats = _payments_corpus()
        proposal = propose(stats, now=NOW)
        report = evaluate_quality_gates(proposal, stats)
        gate = OntologyApprovalGate()
        at = datetime(2026, 8, 23, 13, 0, 0, tzinfo=UTC)
        history = [
            gate.transition(OntologyState.PROPOSED, actor="agent", at=at),
            gate.transition(OntologyState.UNDER_REVIEW, actor="agent", at=at),
            gate.transition(
                OntologyState.APPROVED, actor="reviewer-7", at=at, reviewer_note="gates green"
            ),
        ]
        manifest = build_ontology_manifest(
            world_id="atlas-demo",
            ontology_version=1,
            state=gate.state,
            proposal=proposal,
            gates=report,
            history=history,
        )
        store = OntologyStore(tmp_path)
        saved = store.save(manifest)
        # LocalWorldStore convention: <root>/<world_id>/ontology.json sits in
        # the same per-world directory as manifest.json/state.json.
        assert saved == tmp_path / "atlas-demo" / ONTOLOGY_MANIFEST_FILENAME
        assert store.has("atlas-demo")

        loaded = store.load("atlas-demo")
        assert loaded == manifest
        assert loaded.state is OntologyState.APPROVED
        assert loaded.proposal is not None
        assert loaded.proposal.proposal_id == proposal.proposal_id
        assert loaded.verify_hash()
        assert json.loads(saved.read_text(encoding="utf-8"))["schema_version"] == (
            ONTOLOGY_MANIFEST_SCHEMA_VERSION
        )

    def test_load_missing_manifest_raises(self, tmp_path: Path) -> None:
        store = OntologyStore(tmp_path)
        with pytest.raises(OntologyManifestError):
            store.load("no-such-world")

    def test_tampered_body_is_rejected(self, tmp_path: Path) -> None:
        manifest = build_ontology_manifest(
            world_id="atlas-demo",
            ontology_version=1,
            state=OntologyState.DRAFT,
        )
        store = OntologyStore(tmp_path)
        store.save(manifest)
        path = store.ontology_path("atlas-demo")
        document = json.loads(path.read_text(encoding="utf-8"))
        document["ontology_version"] = 99
        path.write_text(json.dumps(document), encoding="utf-8")
        with pytest.raises(OntologyManifestError):
            store.load("atlas-demo")

    def test_corrupt_json_is_rejected(self, tmp_path: Path) -> None:
        store = OntologyStore(tmp_path)
        path = store.ontology_path("atlas-demo")
        path.parent.mkdir(parents=True)
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(OntologyManifestError):
            store.load("atlas-demo")

    def test_invalid_world_ids_are_rejected(self, tmp_path: Path) -> None:
        store = OntologyStore(tmp_path)
        for bad in ("", ".", "..", "a/b", "a\\b"):
            with pytest.raises(OntologyManifestError):
                store.ontology_path(bad)

    def test_state_contradicting_history_is_rejected(self) -> None:
        stats = _payments_corpus()
        proposal = propose(stats, now=NOW)
        with pytest.raises(IllegalTransitionError):
            build_ontology_manifest(
                world_id="atlas-demo",
                ontology_version=1,
                state=OntologyState.ACTIVE,  # no history to back it
                proposal=proposal,
            )
