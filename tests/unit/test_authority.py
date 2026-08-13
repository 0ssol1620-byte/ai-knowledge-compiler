"""Authority and applicability resolution — §22 and §N17.

The prohibition under test is `latest wins`. Two claims can both be true, and the
tuple decides which one answers *this* question. §22.3's worked example is here in
full, and it is the test that shows the ordering matters: the contract wins on
scope, which is element three, not on authority, which is element five.
"""

from __future__ import annotations

from datetime import UTC, datetime

from akc_cir.authority import (
    AuthorityClass,
    ClaimContext,
    ResolutionRule,
    ResolutionStatus,
    RuleOutcome,
    ScopedClaim,
    SourceStatus,
    rank_claims,
    resolve_authority,
)

JAN = datetime(2026, 1, 1, tzinfo=UTC)
JUN = datetime(2026, 6, 1, tzinfo=UTC)
AUG = datetime(2026, 8, 10, tzinfo=UTC)
DEC = datetime(2026, 12, 1, tzinfo=UTC)


def _context(**kw) -> ClaimContext:
    base = {"subject": "warranty", "as_of": AUG, "customer_id": "customer_a"}
    base.update(kw)
    return ClaimContext(**base)


def _global_policy(**kw) -> ScopedClaim:
    base = {
        "claim_id": "claim_global",
        "subject": "warranty",
        "value": "3 years",
        "authority": AuthorityClass.OFFICIAL,
        "valid_from": JAN,
        "recorded_at": JUN,
        "evidence_id": "ev_global",
    }
    base.update(kw)
    return ScopedClaim(**base)


def _contract(**kw) -> ScopedClaim:
    base = {
        "claim_id": "claim_contract_a",
        "subject": "warranty",
        "value": "5 years",
        "authority": AuthorityClass.CONTRACTUAL,
        "scope": {"customer_id": "customer_a"},
        "valid_from": JAN,
        "recorded_at": JAN,
        "evidence_id": "ev_contract",
    }
    base.update(kw)
    return ScopedClaim(**base)


# --------------------------------------------------------------------------
# §22.3 — the worked example
# --------------------------------------------------------------------------


def test_a_customer_contract_answers_that_customers_question() -> None:
    resolution = resolve_authority([_global_policy(), _contract()], _context())

    assert resolution.status is ResolutionStatus.RESOLVED
    assert resolution.claim is not None
    assert resolution.claim.value == "5 years"


def test_the_contract_wins_on_scope_not_on_authority() -> None:
    """Element three, not element five. Getting that order backwards would let a
    higher-authority document that does not apply override one that does."""
    resolution = resolve_authority([_global_policy(), _contract()], _context())

    assert "scope_match" in resolution.reason


def test_the_same_contract_does_not_answer_another_customers_question() -> None:
    resolution = resolve_authority(
        [_global_policy(), _contract()], _context(customer_id="customer_b")
    )

    assert resolution.claim is not None
    assert resolution.claim.value == "3 years"


def test_a_claim_scoped_elsewhere_is_disqualified_not_merely_ranked_lower() -> None:
    """Otherwise it wins whenever nothing better exists."""
    resolution = resolve_authority([_contract()], _context(customer_id="customer_b"))

    assert resolution.status is ResolutionStatus.NO_CANDIDATE


# --------------------------------------------------------------------------
# §N17.3 — the ordering, element by element
# --------------------------------------------------------------------------


def test_recency_is_the_last_element_not_the_first() -> None:
    """`latest wins` is the rule this whole module exists to forbid."""
    newer_but_general = _global_policy(claim_id="claim_new", recorded_at=DEC)
    older_but_scoped = _contract(recorded_at=JAN)

    resolution = resolve_authority(
        [newer_but_general, older_but_scoped], _context()
    )

    assert resolution.claim is not None
    assert resolution.claim.claim_id == "claim_contract_a"


def test_a_claim_outside_its_validity_window_does_not_apply() -> None:
    expired = _contract(valid_to=JUN)

    resolution = resolve_authority([_global_policy(), expired], _context())

    assert resolution.claim is not None
    assert resolution.claim.value == "3 years"


def test_a_claim_the_asker_cannot_see_is_not_a_candidate() -> None:
    restricted = _contract(required_permission="contracts:read")

    resolution = resolve_authority([_global_policy(), restricted], _context())

    assert resolution.claim is not None
    assert resolution.claim.value == "3 years"


def test_the_permission_filter_count_stays_out_of_the_answer_body() -> None:
    """A user-visible "1 result hidden" discloses that the document exists."""
    restricted = _contract(required_permission="contracts:read")

    resolution = resolve_authority([_global_policy(), restricted], _context())

    assert resolution.permission_filtered == 1
    assert "claim_contract_a" not in str(resolution.as_record())


def test_permission_makes_the_claim_visible_again() -> None:
    restricted = _contract(required_permission="contracts:read")

    resolution = resolve_authority(
        [_global_policy(), restricted],
        _context(permissions=frozenset({"contracts:read"})),
    )

    assert resolution.claim is not None
    assert resolution.claim.value == "5 years"


def test_a_regulation_outranks_a_contract_at_equal_scope() -> None:
    contract = _contract(claim_id="claim_c", value="5 years")
    regulation = _contract(
        claim_id="claim_r", value="7 years", authority=AuthorityClass.REGULATORY
    )

    resolution = resolve_authority([contract, regulation], _context())

    assert resolution.claim is not None
    assert resolution.claim.value == "7 years"


def test_a_withdrawn_source_loses_to_an_active_one() -> None:
    active = _contract(claim_id="claim_active", value="5 years")
    withdrawn = _contract(
        claim_id="claim_withdrawn",
        value="9 years",
        source_status=SourceStatus.WITHDRAWN,
    )

    resolution = resolve_authority([active, withdrawn], _context())

    assert resolution.claim is not None
    assert resolution.claim.value == "5 years"


def test_a_more_specific_claim_beats_a_broader_one_at_equal_authority() -> None:
    broad = _contract(claim_id="claim_broad", value="5 years")
    narrow = _contract(
        claim_id="claim_narrow",
        value="6 years",
        scope={"customer_id": "customer_a", "region": "US"},
    )

    resolution = resolve_authority([broad, narrow], _context(region="US"))

    assert resolution.claim is not None
    assert resolution.claim.value == "6 years"


# --------------------------------------------------------------------------
# §22.4 / §N17.4 — CONFLICTED
# --------------------------------------------------------------------------


def test_two_equal_claims_that_disagree_are_conflicted_not_averaged() -> None:
    left = _contract(claim_id="claim_left", value="5 years")
    right = _contract(claim_id="claim_right", value="6 years")

    resolution = resolve_authority([left, right], _context())

    assert resolution.status is ResolutionStatus.CONFLICTED
    assert resolution.claim is None
    assert resolution.required_review is True
    assert {c.claim_id for c in resolution.candidates} == {"claim_left", "claim_right"}


def test_two_equal_claims_that_agree_are_not_a_conflict() -> None:
    left = _contract(claim_id="claim_left", value="5 years")
    right = _contract(claim_id="claim_right", value="5 years")

    resolution = resolve_authority([left, right], _context())

    assert resolution.status is ResolutionStatus.RESOLVED


def test_a_conflict_is_not_broken_by_taking_the_newer_one() -> None:
    left = _contract(claim_id="claim_left", value="5 years", recorded_at=JAN)
    right = _contract(claim_id="claim_right", value="6 years", recorded_at=DEC)

    resolution = resolve_authority([left, right], _context())

    # Recency is in the tuple, so these do not actually tie -- but the newer one
    # winning must be visible as a recency win rather than an unexplained pick.
    assert resolution.status is ResolutionStatus.RESOLVED
    assert "recency" in resolution.reason


def test_nothing_applicable_says_so_rather_than_returning_the_best_of_nothing() -> None:
    resolution = resolve_authority([], _context())

    assert resolution.status is ResolutionStatus.NO_CANDIDATE
    assert resolution.claim is None


# --------------------------------------------------------------------------
# §N17.2 — the rule DSL
# --------------------------------------------------------------------------


def _override_rule(**kw) -> ResolutionRule:
    base = {
        "rule_id": "warranty_contract_override_v1",
        "subject_type": "warranty",
        "when": lambda claim, ctx: claim.authority is AuthorityClass.CONTRACTUAL
        and claim.scope.get("customer_id") == ctx.customer_id,
        "precedence": 100,
        "outcome": RuleOutcome.PREFER,
        "approved_by": "legal@acme",
    }
    base.update(kw)
    return ResolutionRule(**base)


def test_an_override_rule_lifts_a_claim_above_a_higher_authority_one() -> None:
    """Both claims scoped to the same customer, so the override is what decides.

    Scoping only one of them would make it win on element three and prove nothing
    about the rule.
    """
    regulation = _contract(
        claim_id="claim_reg", value="3 years", authority=AuthorityClass.REGULATORY
    )

    resolution = resolve_authority(
        [regulation, _contract()], _context(), rules=[_override_rule()]
    )

    assert resolution.claim is not None
    assert resolution.claim.value == "5 years"
    assert "explicit_override" in resolution.reason


def test_without_the_rule_the_regulation_would_have_won() -> None:
    """The other half of the previous test: the override is doing the work."""
    regulation = _contract(
        claim_id="claim_reg", value="3 years", authority=AuthorityClass.REGULATORY
    )

    resolution = resolve_authority([regulation, _contract()], _context())

    assert resolution.claim is not None
    assert resolution.claim.value == "3 years"


def test_an_exclude_rule_removes_a_claim_entirely() -> None:
    rule = _override_rule(
        rule_id="drop_drafts",
        when=lambda claim, ctx: claim.authority is AuthorityClass.CONTRACTUAL,
        outcome=RuleOutcome.EXCLUDE,
    )

    resolution = resolve_authority([_global_policy(), _contract()], _context(), rules=[rule])

    assert resolution.claim is not None
    assert resolution.claim.value == "3 years"


def test_a_rule_requiring_explicit_evidence_does_not_fire_on_a_claim_without_it() -> None:
    """A governance act that fires on an inference would let an inference
    override a contract."""
    unevidenced = _contract(evidence_id=None)

    ranked = rank_claims([unevidenced], _context(), rules=[_override_rule()])

    assert ranked[0][0][3] == 0


def test_a_rule_for_another_subject_does_not_fire() -> None:
    rule = _override_rule(subject_type="shipping")

    ranked = rank_claims([_contract()], _context(), rules=[rule])

    assert ranked[0][0][3] == 0
