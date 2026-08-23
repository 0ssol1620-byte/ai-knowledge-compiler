"""Answer Compiler (§22.3) — intent classification and answer compilation.

The compiler turns a question plus a draft set of claims into a CompiledAnswer
that names its claims, pins the world state it was compiled against, lists every
evidence occurrence it rests on, and states an outcome from a closed set. A
query that cannot be answered honestly resolves to UNRESOLVED, never to a
confident guess.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import ClassVar

import pytest
from akc_cir import (
    AnswerOutcome,
    AuthorityClass,
    ClaimContext,
    CompiledAnswer,
    DraftClaim,
    QueryIntent,
    ScopedClaim,
    SourceStatus,
    ValidationReceipt,
    WorldStateRegistry,
    classify_intent,
    compile_answer,
    publication_manifest,
)


class TestClassifyIntent:
    """Each of the ten intents has at least one deterministic lexical rule."""

    @pytest.mark.parametrize(
        ("query", "expected"),
        [
            ("What is the current warranty period?", QueryIntent.CURRENT),
            ("현재 적용 중인 환불 정책을 알려줘", QueryIntent.APPLICABILITY),
            ("As of March 2024, what was the refund policy?", QueryIntent.AS_OF_VALID),
            ("2024년 3월 기준으로 유효했던 약관은 무엇인가요?", QueryIntent.AS_OF_VALID),
            (
                "What did we know about the supplier as known at 2024-01-01?",
                QueryIntent.AS_KNOWN,
            ),
            (
                "그 시점에 시스템이 알고 있었던 가격은 무엇인가요?",
                QueryIntent.AS_KNOWN,
            ),
            ("Who decides the refund amount for customer disputes?", QueryIntent.AUTHORITY),
            ("두 규정이 상충할 때 어느 쪽이 우선하나요?", QueryIntent.AUTHORITY),
            ("Does the enterprise plan apply to Customer A?", QueryIntent.APPLICABILITY),
            ("이 보증 조항은 리셀러에게도 해당되나요?", QueryIntent.APPLICABILITY),
            ("Do the two policy documents conflict on refunds?", QueryIntent.CONFLICT),
            ("두 문서의 내용이 모순되는 부분이 있나요?", QueryIntent.CONFLICT),
            ("How has the pricing model changed over time?", QueryIntent.HISTORY),
            ("이 규정의 연혁을 알려주세요.", QueryIntent.HISTORY),
            ("Which document is the source of this claim?", QueryIntent.PROVENANCE),
            ("이 주장의 출처가 되는 문서는 어느 것인가요?", QueryIntent.PROVENANCE),
            ("What is the impact of changing the retry timeout?", QueryIntent.IMPACT),
            ("타임아웃 값을 바꾸면 어떤 영향을 받나요?", QueryIntent.IMPACT),
            ("Find all documents mentioning the Merger Clause.", QueryIntent.SEARCH),
            ("지난 분기 매출 관련 문서를 검색해줘.", QueryIntent.SEARCH),
        ],
    )
    def test_intent_is_recognized(self, query: str, expected: QueryIntent) -> None:
        assert classify_intent(query) is expected

    def test_classification_is_deterministic(self) -> None:
        query = "What is the impact of the current policy change?"
        assert {classify_intent(query) for _ in range(5)} == {classify_intent(query)}

    @pytest.mark.parametrize("query", ["", "   ", "?"])
    def test_unrecognizable_query_falls_back_to_search(self, query: str) -> None:
        assert classify_intent(query) is QueryIntent.SEARCH


_T0 = datetime(2026, 8, 1, tzinfo=UTC)
_ACTIVE_WS = "ws_002"
_STALE_WS = "ws_001"


def _active_registry(world_state_id: str = _ACTIVE_WS) -> WorldStateRegistry:
    registry = WorldStateRegistry(workspace_id="wspace_001")
    registry.stage(
        world_state_id=world_state_id,
        compiler_version="0.1.0",
        built_at=_T0,
    )
    artifact = {"kb.md": "sha256:" + "0" * 64}
    registry.publish(
        world_state_id,
        manifest=publication_manifest(
            world_state_id=world_state_id,
            compiler_version="0.1.0",
            artifact_hashes=artifact,
        ),
        receipt=ValidationReceipt(
            receipt_id="rcpt_001",
            checksums_verified=True,
            permission_checked=True,
            integrity_passed=True,
        ),
        artifacts=artifact,
        activated_at=_T0,
    )
    return registry


def _claim(
    claim_id: str = "clm_001",
    *,
    value: str = "The warranty period is three years.",
    authority: AuthorityClass = AuthorityClass.OFFICIAL,
    evidence_id: str | None = "ev_001",
    required_permission: str | None = None,
) -> ScopedClaim:
    return ScopedClaim(
        claim_id=claim_id,
        subject="warranty",
        value=value,
        authority=authority,
        source_status=SourceStatus.ACTIVE,
        required_permission=required_permission,
        evidence_id=evidence_id,
    )


def _draft(
    claim: ScopedClaim,
    world_state_id: str = _ACTIVE_WS,
) -> DraftClaim:
    return DraftClaim(claim=claim, world_state_id=world_state_id)


class TestCompileAnswer:
    """§22.3 — every draft set compiles to exactly one closed-set outcome."""

    def _context(self, **overrides: object) -> ClaimContext:
        fields: dict[str, object] = {
            "subject": "warranty",
            "as_of": _T0,
            "permissions": frozenset[str](),
        }
        fields.update(overrides)
        return ClaimContext(**fields)  # type: ignore[arg-type]

    def test_fresh_single_claim_compiles_current(self) -> None:
        answer = compile_answer(
            "What is the current warranty period?",
            [_draft(_claim())],
            _active_registry(),
            self._context(),
        )
        assert answer.outcome is AnswerOutcome.CURRENT
        assert answer.claim_ids == ("clm_001",)
        assert answer.world_state_id == _ACTIVE_WS

    def test_tampered_world_state_is_stale_not_current(self) -> None:
        """A claim extracted against a superseded state must never read CURRENT."""
        registry = _active_registry()
        fresh = compile_answer(
            "What is the current warranty period?",
            [_draft(_claim("clm_fresh"))],
            registry,
            self._context(),
        )
        tampered = compile_answer(
            "What is the current warranty period?",
            [_draft(_claim("clm_old"), world_state_id=_STALE_WS)],
            registry,
            self._context(),
        )
        assert fresh.outcome is AnswerOutcome.CURRENT
        assert tampered.outcome is AnswerOutcome.STALE
        assert tampered.claim_ids == ("clm_old",)

    def test_stale_answer_pins_the_active_state_it_refused(self) -> None:
        answer = compile_answer(
            "현재 보증 기간은 무엇인가요?",
            [_draft(_claim(), world_state_id=_STALE_WS)],
            _active_registry(),
            self._context(),
        )
        assert answer.world_state_id == _ACTIVE_WS
        assert "ws_001" in answer.reason and "ws_002" in answer.reason

    def test_all_claims_hidden_by_permission_fail_closed(self) -> None:
        answer = compile_answer(
            "What is the current warranty period?",
            [
                _draft(
                    _claim(required_permission="finance_secret"),
                )
            ],
            _active_registry(),
            self._context(),
        )
        assert answer.outcome is AnswerOutcome.NOT_AUTHORIZED
        assert answer.claim_ids == ()
        assert answer.evidence_occurrences == ()

    def test_no_applicable_claim_resolves_unresolved(self) -> None:
        off_scope = ScopedClaim(
            claim_id="clm_b",
            subject="warranty",
            value="Five years for Customer B.",
            authority=AuthorityClass.CONTRACTUAL,
            scope={"customer_id": "B"},
            evidence_id="ev_002",
        )
        answer = compile_answer(
            "Does the five-year warranty apply to Customer A?",
            [_draft(off_scope)],
            _active_registry(),
            self._context(customer_id="A"),
        )
        assert answer.outcome is AnswerOutcome.UNRESOLVED
        assert answer.claim_ids == ()

    def test_empty_draft_set_resolves_unresolved(self) -> None:
        answer = compile_answer(
            "What is the current warranty period?",
            [],
            _active_registry(),
            self._context(),
        )
        assert answer.outcome is AnswerOutcome.UNRESOLVED

    def test_no_active_world_state_resolves_unresolved(self) -> None:
        answer = compile_answer(
            "What is the current warranty period?",
            [_draft(_claim())],
            WorldStateRegistry(workspace_id="wspace_001"),
            self._context(),
        )
        assert answer.outcome is AnswerOutcome.UNRESOLVED
        assert answer.world_state_id == ""

    def test_equal_standing_disagreement_compiles_conflict(self) -> None:
        left = _claim("clm_left", value="Three years.")
        right = _claim("clm_right", value="Five years.")
        answer = compile_answer(
            "두 보증 규정이 서로 모순되나요?",
            [_draft(left), _draft(right)],
            _active_registry(),
            self._context(),
        )
        assert answer.outcome is AnswerOutcome.CONFLICT
        assert set(answer.claim_ids) == {"clm_left", "clm_right"}

    def test_evidence_occurrences_cite_every_backing_source(self) -> None:
        weaker_no_evidence = _claim(
            "clm_none",
            value="A weaker statement with no citation.",
            authority=AuthorityClass.INFORMAL,
            evidence_id=None,
        )
        answer = compile_answer(
            "What is the current warranty period?",
            [_draft(_claim()), _draft(weaker_no_evidence)],
            _active_registry(),
            self._context(),
        )
        occurrences = answer.evidence_occurrences
        assert len(occurrences) == 1
        occurrence = occurrences[0]
        assert occurrence.claim_id == "clm_001"
        assert occurrence.evidence_id == "ev_001"
        assert occurrence.source_status is SourceStatus.ACTIVE

    def test_intent_is_recorded_on_the_answer(self) -> None:
        answer = compile_answer(
            "What was the policy as of March 2024?",
            [_draft(_claim())],
            _active_registry(),
            self._context(),
        )
        assert answer.intent is QueryIntent.AS_OF_VALID


class TestAnswerContract:
    """§22.3's four named fields exist and the outcome set is closed."""

    OUTCOMES: ClassVar[set[AnswerOutcome]] = {
        AnswerOutcome.CURRENT,
        AnswerOutcome.STALE,
        AnswerOutcome.CONFLICT,
        AnswerOutcome.UNRESOLVED,
        AnswerOutcome.NOT_AUTHORIZED,
    }

    def test_outcome_set_is_exactly_the_five_specified(self) -> None:
        assert set(AnswerOutcome) == self.OUTCOMES

    def test_compiled_answer_carries_the_four_contract_fields(self) -> None:
        answer = CompiledAnswer(
            claim_ids=("clm_001",),
            world_state_id=_ACTIVE_WS,
            evidence_occurrences=(),
            outcome=AnswerOutcome.CURRENT,
        )
        assert answer.claim_ids == ("clm_001",)
        assert answer.world_state_id == _ACTIVE_WS
        assert answer.evidence_occurrences == ()
        assert answer.outcome is AnswerOutcome.CURRENT

