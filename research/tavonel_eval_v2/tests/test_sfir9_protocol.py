"""Controls for the SFIR9 protocol.

Two properties are worth more than the rest here.

**Freezing must not change what the protocol says.** If `freeze()` altered the
digest, a frozen protocol could never be compared against the draft it was frozen
from, and that comparison is the only thing proving nothing was adjusted at the
moment of freeze. So the freeze state is deliberately outside the digest, and a
control asserts it.

**No declared quantity may be a population measurement.** SFIR4 bounded the
frontier at 158 tree objects and 256 queue entries, both calibrated on twenty
hand-picked repositories, and SFIR7 then recorded twenty of fifty externally
selected roots as measured when the instrument had merely hit those bounds. The
controls below check the literals are absent rather than trusting the comment
that says they are.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import sfir9_protocol as protocol  # noqa: E402


# ------------------------------------------------------------- capacity criterion


def test_the_capacity_criterion_is_the_one_sfir7_applied():
    assert protocol.MINIMUM_C == 750
    assert protocol.MAXIMUM_Q == 1000
    assert protocol.MINIMUM_Q == 600
    assert (
        protocol.QUOTA_FRACTION_NUMERATOR,
        protocol.QUOTA_FRACTION_DENOMINATOR,
    ) == (8, 10)


def test_the_quota_is_four_fifths_of_the_count_until_it_caps():
    assert protocol.quota_for(750) == 600
    assert protocol.quota_for(1000) == 800
    assert protocol.quota_for(1250) == 1000
    assert protocol.quota_for(100_000) == 1000


def test_the_quota_floors_rather_than_rounding():
    """Integers throughout, so no float ever decides a pass."""
    assert protocol.quota_for(751) == 600
    assert protocol.quota_for(754) == 603


def test_the_criterion_needs_both_halves():
    assert protocol.meets_criterion(750) is True
    assert protocol.meets_criterion(749) is False


def test_the_criterion_is_not_met_by_the_predecessor_result():
    """C = 459 was SFIR7's lower bound, and it failed. It still fails."""
    assert protocol.meets_criterion(459) is False


def test_both_halves_of_the_criterion_are_enforced_independently(monkeypatch):
    """The two halves coincide under the declared constants, so force them apart.

    `Q_f >= 600` and `C_f >= 750` are the same condition when the fraction is
    4/5, because 600 / 0.8 is exactly 750. A control written against the declared
    numbers therefore cannot tell a conjunction from either half alone -- both
    mutations pass it, and the criterion could silently become a one-sided test
    without anything going red.

    Moving a threshold so the halves diverge is what makes the conjunction
    observable. This is a control over the code's structure; it does not change
    the criterion, which stays 750 / 600 everywhere else in this file.
    """
    with monkeypatch.context() as patch:
        patch.setattr(protocol, "MINIMUM_Q", 800)
        assert protocol.meets_criterion(750) is False, (
            "the count cleared its floor and the quota did not, so a criterion "
            "that still passes is only checking the count"
        )

    with monkeypatch.context() as patch:
        patch.setattr(protocol, "MINIMUM_C", 900)
        assert protocol.meets_criterion(750) is False, (
            "the quota cleared its floor and the count did not, so a criterion "
            "that still passes is only checking the quota"
        )


def test_the_two_halves_coincide_under_the_declared_constants():
    """Recorded rather than hidden: the criterion as declared is redundant.

    SFIR7 stated it as two conditions and they are one. Nothing is wrong with
    that -- but a reader who assumes the quota floor is an independent second
    hurdle is mistaken, and a future edit to the fraction would silently make
    the two diverge.
    """
    for count in (0, 100, 749, 750, 751, 1249, 1250, 5000):
        assert (count >= protocol.MINIMUM_C) == (
            protocol.quota_for(count) >= protocol.MINIMUM_Q
        )


# ---------------------------------------------------------------- freeze ordering


def test_a_fresh_protocol_is_a_draft():
    assert protocol.Protocol().is_frozen() is False
    assert protocol.Protocol().freeze_state == protocol.DRAFT


def test_freezing_records_the_state():
    assert protocol.Protocol().freeze().is_frozen() is True


def test_freezing_does_not_change_what_the_protocol_says():
    """The comparison that proves nothing moved at the moment of freeze.

    If the freeze state entered the digest, a frozen protocol and the draft it
    came from would differ by construction, and the digests could never be used
    to show a term was left alone.
    """
    draft = protocol.Protocol()
    assert draft.freeze().digest() == draft.digest()


def test_a_draft_refuses_the_actions_that_must_follow_a_freeze():
    with pytest.raises(protocol.ProtocolRefused, match="requires a frozen protocol"):
        protocol.Protocol().require_frozen("roster generation")


def test_the_refusal_names_the_action_and_says_why():
    with pytest.raises(protocol.ProtocolRefused) as caught:
        protocol.Protocol().require_frozen("roster generation")
    message = str(caught.value)
    assert "roster generation" in message
    assert "after the roster has been seen" in message


def test_a_frozen_protocol_permits_them():
    protocol.Protocol().freeze().require_frozen("roster generation")


def test_the_freeze_state_is_still_reported_even_though_it_is_not_hashed():
    """Excluded from the digest is not the same as invisible."""
    assert protocol.Protocol().as_dict()["freeze_state"] == protocol.DRAFT
    assert protocol.Protocol().freeze().as_dict()["freeze_state"] == protocol.FROZEN


# --------------------------------------------------------------- digest behaviour


def test_the_digest_is_stable():
    assert protocol.Protocol().digest() == protocol.Protocol().digest()


def test_the_digest_covers_every_declared_term(monkeypatch):
    """Changing any constant must move the digest.

    A term the digest does not cover can be edited after a freeze without any
    receipt noticing, which is precisely what a frozen protocol is for.
    """
    baseline = protocol.Protocol().digest()
    for name, changed in [
        ("MINIMUM_C", 700),
        ("MAXIMUM_Q", 900),
        ("MINIMUM_Q", 500),
        ("QUOTA_FRACTION_NUMERATOR", 7),
        ("QUOTA_FRACTION_DENOMINATOR", 9),
        ("PERMITTED_RATE_WINDOWS", 7),
        ("USABLE_CHARGE_PER_WINDOW", 4600),
        ("PER_ROOT_CHARGE_ALLOWANCE", 500),
        ("RETRY_WAIT_SECONDS", 90),
        ("TOTAL_WAIT_SECONDS", 300),
        ("SELECTION_SALT", "a-different-salt"),
        ("PARTITION_COUNT", 32),
        ("PARTITION_INDEX", 1),
        ("DECLARED_WORKING_STORAGE_BYTES", 1024),
        ("CANDIDATE_EXTENSIONS", (".py",)),
        ("PROTOCOL_ID", "SOMETHING_ELSE"),
        ("STUDY_KIND", "EXPLORATORY"),
    ]:
        with monkeypatch.context() as patch:
            patch.setattr(protocol, name, changed)
            assert protocol.Protocol().digest() != baseline, (
                f"{name} is declared by the protocol but does not reach the digest, "
                "so it could be changed after a freeze without any receipt moving"
            )


def test_the_digest_is_prefixed_so_the_algorithm_is_never_guessed():
    assert protocol.Protocol().digest().startswith("sha256:")


# ------------------------------------------------------- nothing is a measurement


def test_the_execution_envelope_is_denominated_in_provider_charges():
    """Only the provider's charge is comparable with the provider's limit."""
    envelope = protocol.Protocol().terms()["execution_envelope"]
    assert envelope["denominated_in"] == "provider_charge"


def test_no_population_calibrated_bound_is_declared():
    traversal = protocol.Protocol().terms()["traversal"]
    assert traversal["population_calibrated_bounds"] == []


def test_the_two_predecessor_bounds_appear_only_as_the_reason_they_are_absent():
    """158 and 256 may be explained. They may not be reinstated as terms."""
    traversal = protocol.Protocol().terms()["traversal"]
    explanation = traversal.pop("why_no_population_calibrated_bounds")
    assert "158" in explanation and "256" in explanation
    assert "158" not in str(traversal)
    assert "256" not in str(traversal)


def test_the_working_storage_budget_is_an_environment_property():
    """Two gibibytes of disk is a fact about the machine, not a repository."""
    assert protocol.DECLARED_WORKING_STORAGE_BYTES == 2 * 1024 * 1024 * 1024


def test_the_fail_safe_waits_are_the_inherited_ones():
    """Widening either because a result disappointed is outcome-fitting."""
    assert protocol.RETRY_WAIT_SECONDS == 60
    assert protocol.TOTAL_WAIT_SECONDS == 180
    semantics = protocol.Protocol().terms()["rate_window_semantics"]
    assert semantics["inherited_unchanged_from"] == "SFIR7"


def test_a_rate_window_ends_a_segment_rather_than_ending_the_study():
    semantics = protocol.Protocol().terms()["rate_window_semantics"]
    assert semantics["on_a_reset_beyond_the_fail_safe"] == "SEGMENT_COMPLETE_RATE_WINDOW"


# ------------------------------------------------------------------------ the salt


def test_the_salt_is_published_only_as_a_digest():
    published = str(protocol.Protocol().as_dict())
    assert protocol.SELECTION_SALT not in published
    assert protocol.salt_digest().startswith("sha256:")


def test_the_salt_digest_moves_with_the_salt(monkeypatch):
    baseline = protocol.salt_digest()
    monkeypatch.setattr(protocol, "SELECTION_SALT", "another-salt")
    assert protocol.salt_digest() != baseline


def test_the_partition_is_keyed_on_identity_rather_than_address():
    """An address-keyed partition would depend on rename status, which SFIR7 saw."""
    assert protocol.Protocol().terms()["selection"]["partition_keyed_on"] == "host_uuid"


def test_a_single_bucket_is_not_a_partition():
    """One bucket admits the whole catalogue, which is the design being avoided.

    The partition exists to answer "you picked the popular repositories". A
    partition count of one makes the selection exactly the global top N again,
    while every other control -- ordering, determinism, digests -- keeps passing.
    """
    assert protocol.PARTITION_COUNT > 1
    assert 0 <= protocol.PARTITION_INDEX < protocol.PARTITION_COUNT


# ------------------------------------------------------------------------- lineage


def test_the_study_declares_itself_confirmatory_over_a_fresh_population():
    terms = protocol.Protocol().terms()
    assert terms["study_kind"] == "FRESH_HELDOUT_CONFIRMATORY"
    assert terms["predecessor_development_studies"] == ["SFIR7", "SFIR8"]


def test_the_protocol_id_is_not_a_predecessor_id():
    """Re-running a spent study ID would overwrite terminal evidence."""
    assert protocol.PROTOCOL_ID not in {
        "SOURCE_FACT_IR_FRESH_HELDOUT_V7",
        "SOURCE_FACT_IR_FRESH_HELDOUT_V8",
    }
    assert protocol.PROTOCOL_ID.endswith("V9")
