"""Controls for SFIR9 acceptance.

The distinction the whole module exists for is between a study that fell short
and a study that cannot say what it measured. The first is a result and gets
published; the second is not and does not. Most of these controls are some form
of that question, and the rest are about the third state -- UNPROVEN -- which
exists so that a check nobody ran cannot read as either a pass or a refutation.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import sfir9_acceptance as acceptance  # noqa: E402
import sfir9_protocol as protocol_module  # noqa: E402
import sfir9_scorer as scorer  # noqa: E402

FROZEN = protocol_module.Protocol().freeze()


def _fact(**overrides):
    body = {
        "source_witness": "sha256:response",
        "canonical_representation": ("1", "a.py", "a" * 40),
        "fingerprint": "a" * 40,
        "dependency_path": "1:/a.py",
    }
    body.update(overrides)
    return body


def _score(verdict=scorer.PASS):
    return {
        "verdict": verdict,
        "capacity": {"certain_lower_bound": 800, "count_is_exact": True},
        "completeness": {"census_complete": True},
        "roster_digest": "sha256:roster",
        "protocol_digest": FROZEN.digest(),
        "candidate_pool_digest": "sha256:pool",
    }


def _artifacts(**overrides):
    body = dict(
        protocol=FROZEN,
        upstream_binding={"upstream_modules": [{}], "manifest_digest": "sha256:up"},
        isolation_proof={
            "sfir9_prospective_integrity": "CLEAN",
            "historical_integrity_receipt_sha256": "sha256:hist",
        },
        roster_seal={"intact": True, "recorded_seal_digest": "sha256:roster"},
        chain_verification={
            "links_intact": True, "head_matches": True, "recomputed_head": "sha256:head"
        },
        attested_host_uuids=["1", "2"],
        counted_host_uuids=["1", "2"],
        provider_reconciliation={"UNATTRIBUTED_PROVIDER_ACCOUNTING_DELTA": 0},
        credential_scan={"credential_material_found": 0, "scan_digest": "sha256:scan"},
        four_link=acceptance.four_link_audit([_fact()], floor=1),
        score=_score(),
    )
    body.update(overrides)
    return body


def _matrix(**overrides):
    return acceptance.acceptance_of(**_artifacts(**overrides))


# ---------------------------------------------------------- the two axes


def test_a_complete_run_that_fell_short_still_seals():
    """The distinction the module exists for. A shortfall is a finding."""
    score = _score(scorer.FAIL)
    sealed = _matrix(score=score).seal(score)
    assert sealed["sealed"] is True
    assert sealed["verdict"] == scorer.FAIL
    assert "not a reason to revisit the threshold" in sealed["what_a_sealed_fail_means"]


def test_a_run_that_could_not_say_what_it_measured_does_not_seal():
    score = _score(scorer.NOT_SEALABLE)
    with pytest.raises(acceptance.AcceptanceRefused) as caught:
        _matrix(score=score).seal(score)
    assert caught.value.code == acceptance.NOT_ACCEPTED


def test_acceptance_evidence_cannot_supply_a_total_the_census_never_established():
    """Every criterion green, and it still does not seal."""
    score = _score(scorer.NOT_SEALABLE)
    matrix = _matrix(score=score)
    assert matrix.failures() == ["verdict_is_sealable"]
    with pytest.raises(acceptance.AcceptanceRefused):
        matrix.seal(score)


def test_a_fully_green_matrix_still_refuses_a_not_sealable_score():
    """The matrix and the score are separate arguments and can disagree.

    `acceptance_of` keeps them consistent, but `seal` accepts any matrix, so a
    hand-built one claiming every criterion passed is a reachable way to present
    a census that established no total as though it had. The check is not
    redundant with `verdict_is_sealable`; it is what covers that gap.
    """
    matrix = acceptance.AcceptanceMatrix()
    for name in acceptance.REQUIRED_CRITERIA:
        matrix.record(name, acceptance.PASS, evidence=f"sha256:{name}")
    assert matrix.accepted() is True

    with pytest.raises(acceptance.AcceptanceRefused) as caught:
        matrix.seal(_score(scorer.NOT_SEALABLE))
    assert caught.value.code == acceptance.NOT_ACCEPTED
    assert "cannot supply a total" in str(caught.value)


def test_a_passing_run_seals():
    score = _score(scorer.PASS)
    assert _matrix(score=score).seal(score)["verdict"] == scorer.PASS


# ------------------------------------------------------- the third state


def test_an_artifact_that_was_never_supplied_is_unproven_not_failed():
    """A check nobody ran has not been refuted."""
    matrix = _matrix(chain_verification=None)
    assert matrix.states()["segment_chain_intact"] == acceptance.UNPROVEN
    assert matrix.failures() == []
    assert matrix.unproven() == ["segment_chain_intact"]


def test_an_artifact_that_says_no_is_failed_not_unproven():
    matrix = _matrix(
        chain_verification={"links_intact": False, "head_matches": True}
    )
    assert matrix.states()["segment_chain_intact"] == acceptance.FAIL
    assert matrix.unproven() == []


def test_neither_unproven_nor_failed_seals():
    for broken in ({"chain_verification": None},
                   {"chain_verification": {"links_intact": False, "head_matches": False}}):
        matrix = _matrix(**broken)
        with pytest.raises(acceptance.AcceptanceRefused) as caught:
            matrix.seal(_score())
        assert caught.value.code == acceptance.NOT_ACCEPTED


def test_the_matrix_says_why_the_two_are_not_one_state():
    report = _matrix().evaluate()
    assert "different states" in report["why_unproven_is_not_failed"]


def test_the_three_states_are_distinct():
    assert {"PASS", "FAIL", "UNPROVEN"} == acceptance.STATES


def test_an_undeclared_state_refuses():
    with pytest.raises(acceptance.AcceptanceRefused) as caught:
        acceptance.Criterion(name="x", state="MAYBE", evidence="e", detail="")
    assert caught.value.code == acceptance.UNKNOWN_STATE


# --------------------------------------------------- a pass needs evidence


def test_a_pass_without_an_evidence_pointer_refuses():
    """An unfollowable pass is an assertion, and this study has a word for those."""
    with pytest.raises(acceptance.AcceptanceRefused) as caught:
        acceptance.Criterion(name="x", state=acceptance.PASS, evidence=None, detail="")
    assert caught.value.code == acceptance.NO_EVIDENCE


@pytest.mark.parametrize("state", [acceptance.FAIL, acceptance.UNPROVEN])
def test_a_non_pass_needs_no_evidence(state):
    assert acceptance.Criterion(name="x", state=state, evidence=None, detail="")


def test_every_passing_criterion_in_a_full_matrix_carries_evidence():
    for criterion in _matrix().evaluate()["criteria"]:
        if criterion["state"] == acceptance.PASS:
            assert criterion["evidence"]


# ----------------------------------------------------- the criteria list


def test_the_matrix_asks_all_ten_criteria():
    report = _matrix().evaluate()
    assert report["not_evaluated"] == []
    assert [c["name"] for c in report["criteria"]] == list(
        acceptance.REQUIRED_CRITERIA
    )


def test_the_required_criteria_are_the_ones_the_study_depends_on():
    assert set(acceptance.REQUIRED_CRITERIA) == {
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
    }


def test_a_matrix_short_of_its_own_list_refuses_to_seal():
    """An unevaluated criterion is not a satisfied one."""
    matrix = acceptance.AcceptanceMatrix()
    matrix.record("protocol_frozen", acceptance.PASS, evidence="sha256:p")
    with pytest.raises(acceptance.AcceptanceRefused) as caught:
        matrix.seal(_score())
    assert caught.value.code == acceptance.MISSING_CRITERION
    assert "protocol_frozen" not in str(caught.value)


def test_the_matrix_reports_what_it_never_evaluated():
    matrix = acceptance.AcceptanceMatrix()
    matrix.record("roster_sealed", acceptance.PASS, evidence="sha256:r")
    assert set(matrix.evaluate()["not_evaluated"]) == set(
        acceptance.REQUIRED_CRITERIA
    ) - {"roster_sealed"}


def test_there_is_no_override_parameter():
    """One would be used, eventually, on the run where it mattered most."""
    import inspect

    signature = inspect.signature(acceptance.AcceptanceMatrix.seal)
    assert set(signature.parameters) == {"self", "score"}


# ----------------------------------------------- each criterion can fail


@pytest.mark.parametrize(
    "override,expected",
    [
        ({"protocol": protocol_module.Protocol()}, "protocol_frozen"),
        ({"upstream_binding": {"upstream_modules": []}}, "upstream_binding_verified"),
        (
            {"isolation_proof": {"sfir9_prospective_integrity": "DIRTY"}},
            "historical_isolation_clean",
        ),
        ({"roster_seal": {"intact": False}}, "roster_sealed"),
        (
            {"chain_verification": {"links_intact": True, "head_matches": False}},
            "segment_chain_intact",
        ),
        ({"attested_host_uuids": ["1"]}, "every_counted_root_attested"),
        ({"provider_reconciliation": {}}, "provider_accounting_recorded"),
        ({"credential_scan": {"credential_material_found": 1}}, "receipts_credential_clean"),
        (
            {"four_link": acceptance.four_link_audit([], floor=1)},
            "four_links_complete",
        ),
    ],
)
def test_each_criterion_fails_on_its_own_artifact(override, expected):
    """A criterion that could not fail would be decoration."""
    matrix = _matrix(**override)
    assert matrix.failures() == [expected]


def test_a_counted_root_without_an_identity_proof_names_itself():
    matrix = _matrix(attested_host_uuids=["1"], counted_host_uuids=["1", "2"])
    detail = next(
        c for c in matrix.evaluate()["criteria"]
        if c["name"] == "every_counted_root_attested"
    )["detail"]
    assert "'2'" in detail


def test_an_attested_root_that_was_never_counted_is_not_a_problem():
    """Attesting more than was counted is thoroughness, not a defect."""
    assert _matrix(attested_host_uuids=["1", "2", "3"]).failures() == []


def test_a_recorded_nonzero_provider_delta_still_passes():
    """The criterion is that it was recorded, not that it was zero."""
    matrix = _matrix(
        provider_reconciliation={"UNATTRIBUTED_PROVIDER_ACCOUNTING_DELTA": 7}
    )
    assert matrix.failures() == []
    assert matrix.states()["provider_accounting_recorded"] == acceptance.PASS


# ------------------------------------------------------------ four links


def test_a_fact_needs_all_four_links():
    assert acceptance.four_links(_fact())["complete"] is True


@pytest.mark.parametrize("link", list(acceptance.REQUIRED_LINKS))
def test_three_of_four_is_not_a_fact(link):
    result = acceptance.four_links(_fact(**{link: None}))
    assert result["complete"] is False
    assert result["missing_links"] == [link]


def test_the_four_links_are_the_ones_the_ruling_names():
    assert set(acceptance.REQUIRED_LINKS) == {
        "source_witness",
        "canonical_representation",
        "fingerprint",
        "dependency_path",
    }


def test_the_audit_counts_only_complete_facts_toward_the_floor():
    audit = acceptance.four_link_audit(
        [_fact(), _fact(fingerprint=None), _fact()], floor=3
    )
    assert audit["facts_examined"] == 3
    assert audit["facts_four_link_complete"] == 2
    assert audit["shortfall"] == 1
    assert audit["feasible"] is False


def test_a_shortfall_is_a_feasibility_failure_and_the_floor_does_not_move():
    audit = acceptance.four_link_audit([_fact()], floor=10)
    assert audit["floor"] == 10
    assert audit["shortfall"] == 9
    assert "not a floor" in audit["why_the_floor_is_not_lowered"]


def test_a_met_floor_is_feasible():
    audit = acceptance.four_link_audit([_fact(), _fact()], floor=2)
    assert audit["feasible"] is True
    assert audit["shortfall"] == 0


def test_a_surplus_is_not_a_shortfall():
    assert acceptance.four_link_audit([_fact()] * 5, floor=2)["shortfall"] == 0


def test_the_audit_shows_which_rows_were_incomplete():
    audit = acceptance.four_link_audit([_fact(source_witness=None)], floor=0)
    assert audit["incomplete_rows"][0]["missing_links"] == ["source_witness"]


# --------------------------------------------------------------- digests


def test_the_matrix_digest_moves_with_any_criterion():
    base = _matrix().evaluate()["matrix_digest"]
    assert _matrix(roster_seal={"intact": False}).evaluate()["matrix_digest"] != base


def test_the_matrix_digest_is_stable_for_the_same_matrix():
    assert _matrix().evaluate()["matrix_digest"] == _matrix().evaluate()["matrix_digest"]


def test_the_sealed_result_names_the_acceptance_that_allowed_it():
    score = _score()
    matrix = _matrix(score=score)
    sealed = matrix.seal(score)
    assert sealed["acceptance_digest"] == matrix.evaluate()["matrix_digest"]
    assert sealed["roster_digest"] == score["roster_digest"]
