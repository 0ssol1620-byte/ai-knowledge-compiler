"""Three endings that look identical in an artifact, told apart.

A run that exhausted its frame, a run that filled its quotas, and a run that
simply stopped all produce the same shape of artifact — a list of admitted
pairs. Only the third is a problem, and it is invisible to the scorer, which
would report honest counts over a cohort smaller than the frame allowed and say
nothing, because nothing in a scored receipt describes what was never attempted.
"""

from __future__ import annotations

import sys
from pathlib import Path

NS = Path(__file__).resolve().parents[1]
for _sub in ("tools", "acquisition"):
    sys.path.insert(0, str(NS / _sub))
sys.path.insert(0, str(NS))

import verify_sfi2_frame as verify  # noqa: E402

QUOTAS = {"git_docs": 120, "regulation_ecfr": 100, "encyclopedia_wikipedia": 70}


def artifact(*, candidates=1859, considered=800, admitted=290, rejected=510, by_family=None):
    return {
        "frame": {"candidates": candidates, "digest": "sha256:" + "0" * 64},
        "lineages_considered": considered,
        "by_family": by_family if by_family is not None else dict(QUOTAS),
        "admitted": [{"lineage_id": f"l{index}"} for index in range(admitted)],
        "rejected": [
            {"lineage_id": f"r{index}", "code": "NO_RAW_DIFFERENCE"}
            for index in range(rejected)
        ],
        "rejected_by_code": {"NO_RAW_DIFFERENCE": rejected},
        "reduction_digest": "sha256:" + "1" * 64,
    }


def test_all_quotas_filled_is_complete():
    """The ordinary good ending: the run stopped because it had enough."""
    found = verify.assess(artifact(), QUOTAS)
    assert found["ending"] == verify.COMPLETE
    assert verify.concerns(found) == []


def test_every_candidate_considered_is_exhausted():
    """The other good ending: the frame ran out before the quotas filled."""
    short = dict(QUOTAS, encyclopedia_wikipedia=40)
    found = verify.assess(
        artifact(considered=1859, admitted=260, rejected=1599, by_family=short), QUOTAS
    )
    assert found["ending"] == verify.EXHAUSTED
    #: a shortfall is still reported. Exhausting the frame explains it; it does
    #: not excuse leaving it unsaid.
    assert any("encyclopedia_wikipedia filled 40 of 70" in line for line in verify.concerns(found))


def test_stopping_early_with_unfilled_quotas_is_neither():
    """The ending worth catching. Nothing downstream would notice."""
    short = dict(QUOTAS, git_docs=12)
    found = verify.assess(
        artifact(considered=400, admitted=182, rejected=218, by_family=short), QUOTAS
    )
    assert found["ending"] == verify.NEITHER
    assert found["candidates_never_considered"] == 1459
    assert any("never considered" in line for line in verify.concerns(found))


def test_a_missing_result_between_the_pool_and_the_reduction_is_caught():
    """Considered but neither admitted nor rejected — a lost future."""
    found = verify.assess(artifact(considered=800, admitted=290, rejected=505), QUOTAS)
    assert found["reconciles"] is False
    assert found["unaccounted"] == 5
    assert any("went missing" in line for line in verify.concerns(found))


def test_a_reconciling_run_reports_no_loss():
    found = verify.assess(artifact(), QUOTAS)
    assert found["reconciles"] is True
    assert found["unaccounted"] == 0


def test_a_shortfall_is_reported_rather_than_absorbed():
    """The quota is never lowered to match what arrived, and a shortfall in one
    family is never covered by a surplus in another."""
    lopsided = {"git_docs": 200, "regulation_ecfr": 100, "encyclopedia_wikipedia": 10}
    found = verify.assess(
        artifact(considered=1859, admitted=310, rejected=1549, by_family=lopsided), QUOTAS
    )
    raised = verify.concerns(found)
    assert any("encyclopedia_wikipedia filled 10 of 70" in line for line in raised)
    assert found["family_quota"]["encyclopedia_wikipedia"] == 70


def test_the_verifier_uses_the_studys_own_quotas():
    """Restating them here would let the two drift apart silently."""
    import sources_sfi2 as frame_module

    assert dict(frame_module.FAMILY_QUOTA) == QUOTAS


def test_a_neither_ending_is_not_scorable_and_a_complete_one_is():
    """`scorable` is the gate the completion order reads before scoring."""
    good = verify.assess(artifact(), QUOTAS)
    assert good["ending"] != verify.NEITHER and good["reconciles"]

    #: unfilled quotas AND candidates left unconsidered. Defaulting the family
    #: counts to the quotas would have made this case indistinguishable from the
    #: good one, which is how a verifier ends up verifying nothing.
    bad = verify.assess(
        artifact(
            considered=400,
            admitted=100,
            rejected=300,
            by_family={"git_docs": 60, "regulation_ecfr": 30, "encyclopedia_wikipedia": 10},
        ),
        QUOTAS,
    )
    assert bad["ending"] == verify.NEITHER
