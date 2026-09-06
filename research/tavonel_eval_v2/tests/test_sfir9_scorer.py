"""Controls for the SFIR9 scorer.

The scorer's whole job is to keep two things apart that SFIR7 merged: what was
counted, and what was reached. Every control here is some version of that
question. The verdict controls matter most, because a three-way outcome is easy
to write and easy to collapse back into two the first time a run is disappointing.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import sfir9_identity_logic as identity  # noqa: E402
import sfir9_protocol as protocol_module  # noqa: E402
import sfir9_scorer as scorer  # noqa: E402

FROZEN = protocol_module.Protocol().freeze()
ROSTER_DIGEST = "sha256:roster"


def _candidates(host_uuid, count, *, start=0, suffix=".py"):
    return tuple(
        identity.CandidateIdentity.of(
            repository_numeric_id=host_uuid,
            path=f"src/file{index}{suffix}",
            blob_sha=f"{index:040x}",
        )
        for index in range(start, start + count)
    )


def _root(host_uuid, count=0, disposition=scorer.EXHAUSTED, **kwargs):
    return scorer.RootResult(
        host_uuid=str(host_uuid),
        disposition=disposition,
        candidates=_candidates(str(host_uuid), count, **kwargs),
    )


def _score(results, roster=None):
    roster = roster or [r.host_uuid for r in results]
    return scorer.score(
        results,
        roster_host_uuids=roster,
        roster_digest=ROSTER_DIGEST,
        protocol=FROZEN,
    )


# ------------------------------------------------------- counted vs reached


def test_an_exhausted_root_is_an_exact_count():
    result = _score([_root(1, 10)])
    assert result["capacity"]["certain_lower_bound"] == 10
    assert result["capacity"]["exact_count"] == 10
    assert result["capacity"]["count_is_exact"] is True


def test_a_stopped_root_makes_the_total_a_floor_and_nothing_more():
    """The SFIR7 failure, refused: no exact figure exists here."""
    result = _score([_root(1, 10), _root(2, 5, disposition=scorer.STOPPED)])
    assert result["capacity"]["certain_lower_bound"] == 15
    assert result["capacity"]["exact_count"] is None
    assert result["capacity"]["count_is_exact"] is False
    assert result["completeness"]["census_complete"] is False


def test_a_stopped_roots_candidates_still_count_toward_the_floor():
    """It saw what it saw. What it did not see is the part that is unknown."""
    with_stop = _score([_root(1, 10), _root(2, 5, disposition=scorer.STOPPED)])
    without = _score([_root(1, 10), _root(2, 0, disposition=scorer.STOPPED)])
    assert with_stop["capacity"]["certain_lower_bound"] == 15
    assert without["capacity"]["certain_lower_bound"] == 10


def test_the_completeness_report_separates_the_three_dispositions():
    result = _score(
        [
            _root(1, 10),
            _root(2, 5, disposition=scorer.STOPPED),
            _root(3, 0, disposition=scorer.REFUSED),
        ]
    )
    completeness = result["completeness"]
    assert completeness["roots_traversed_to_exhaustion"] == 1
    assert completeness["roots_stopped_before_exhaustion"] == 1
    assert completeness["roots_refused_on_identity"] == 1


def test_a_stopped_root_is_still_in_the_denominator():
    """It was attempted and it produced something. Only refusal removes a root.

    Dropping stopped roots from the denominator would report a completeness
    figure computed over the roots that happened to finish -- the same trick as
    calling a stop a measurement, arriving from the other side.
    """
    result = _score(
        [
            _root(1, 10),
            _root(2, 5, disposition=scorer.STOPPED),
            _root(3, 0, disposition=scorer.REFUSED),
        ]
    )
    assert result["completeness"]["roots_in_the_denominator"] == 2


def test_a_refused_root_is_in_neither_the_numerator_nor_the_denominator():
    """It was never measured, so a completeness figure must not claim it."""
    result = _score([_root(1, 10), _root(2, 0, disposition=scorer.REFUSED)])
    assert result["completeness"]["roots_in_the_denominator"] == 1
    assert result["capacity"]["certain_lower_bound"] == 10
    assert result["completeness"]["census_complete"] is True


def test_a_refused_root_carrying_candidates_refuses_the_score():
    """Whatever answered that address is not the repository the roster chose."""
    bad = scorer.RootResult(
        host_uuid="2", disposition=scorer.REFUSED, candidates=_candidates("2", 3)
    )
    with pytest.raises(scorer.ScoringRefused) as caught:
        _score([_root(1, 10), bad])
    assert caught.value.code == scorer.CANDIDATES_ON_A_REFUSED_ROOT


def test_no_stopped_root_is_extrapolated():
    """Doubling the stopped root's yield must not double the reported total."""
    small = _score([_root(1, 10), _root(2, 5, disposition=scorer.STOPPED)])
    assert small["capacity"]["certain_lower_bound"] == 15
    assert "an estimate" in small["what_a_lower_bound_is_not"]


def test_a_stopped_root_does_not_carry_a_short_count_over_the_threshold():
    """The one that would matter: padding that flips the verdict.

    A count below the criterion with roots still stopped is not sealable. If the
    scorer credited a stopped root with a presumed yield -- any yield, however
    modest -- the same census would read as a pass, and the pass would be an
    assumption wearing a measurement's clothes.
    """
    just_short = protocol_module.MINIMUM_C - 50
    result = _score(
        [
            _root(1, just_short),
            _root(2, 5, start=just_short, disposition=scorer.STOPPED),
        ]
    )
    assert result["capacity"]["certain_lower_bound"] == just_short + 5
    assert result["verdict"] == scorer.NOT_SEALABLE


# ----------------------------------------------------------- the three verdicts


def test_a_lower_bound_above_the_threshold_passes_even_with_roots_stopped():
    """More candidates can only raise a count, so this settles the question."""
    result = _score(
        [
            _root(1, protocol_module.MINIMUM_C),
            _root(2, 5, disposition=scorer.STOPPED),
        ]
    )
    assert result["verdict"] == scorer.PASS
    assert result["capacity"]["count_is_exact"] is False
    assert "can only raise a count" in result["why"]


def test_a_complete_census_below_the_threshold_fails():
    result = _score([_root(1, 100)])
    assert result["verdict"] == scorer.FAIL
    assert "what the population says" in result["why"]


def test_an_incomplete_census_below_the_threshold_is_not_sealable():
    """Neither pass nor fail. A result, not a failure to produce one."""
    result = _score([_root(1, 100), _root(2, 5, disposition=scorer.STOPPED)])
    assert result["verdict"] == scorer.NOT_SEALABLE
    assert "neither a pass nor a fail can be sealed" in result["why"]


def test_the_three_verdicts_are_distinct():
    assert len({scorer.PASS, scorer.FAIL, scorer.NOT_SEALABLE}) == 3


def test_the_boundary_count_passes():
    result = _score([_root(1, protocol_module.MINIMUM_C)])
    assert result["verdict"] == scorer.PASS


def test_one_below_the_boundary_fails_on_a_complete_census():
    result = _score([_root(1, protocol_module.MINIMUM_C - 1)])
    assert result["verdict"] == scorer.FAIL


def test_a_census_of_nothing_is_not_a_pass():
    result = _score([], roster=["1"])
    assert result["verdict"] != scorer.PASS
    assert result["completeness"]["census_complete"] is False


def test_the_predecessor_result_would_still_not_seal():
    """C = 459 was SFIR7's lower bound, and it remains below the criterion."""
    result = _score([_root(1, 459), _root(2, 0, disposition=scorer.STOPPED)])
    assert result["verdict"] == scorer.NOT_SEALABLE


# --------------------------------------------------------------- the criterion


def test_the_criterion_is_read_from_the_protocol(monkeypatch):
    """Read, not restated. A local copy could be lowered on its own."""
    monkeypatch.setattr(protocol_module, "MINIMUM_C", 50)
    monkeypatch.setattr(protocol_module, "MINIMUM_Q", 40)
    result = _score([_root(1, 60)])
    assert result["verdict"] == scorer.PASS
    assert result["criterion"]["minimum_c"] == 50


def test_the_scorer_states_no_threshold_of_its_own():
    """Executable code only. Prose explaining the criterion is not an authority.

    A plain substring scan flags the docstring, which is where the criterion is
    described for a reader; what matters is that no number the criterion depends
    on appears where Python would evaluate it.
    """
    import io
    import tokenize

    source = (NS / "tools/sfir9_scorer.py").read_text(encoding="utf-8")
    code = " ".join(
        token.string
        for token in tokenize.generate_tokens(io.StringIO(source).readline)
        if token.type not in (tokenize.STRING, tokenize.COMMENT)
    )
    for number in ("750", "600", "1000", "0.8"):
        assert number not in code, (
            f"{number} appears as a literal in the scorer's code. The criterion is "
            "owned by sfir9_protocol, and a second copy is a second authority."
        )


def test_that_scan_would_notice_a_literal_reintroduced():
    """The scan must be able to fail, or it is not checking anything."""
    import io
    import tokenize

    planted = "def f():\n    return 750\n"
    code = " ".join(
        token.string
        for token in tokenize.generate_tokens(io.StringIO(planted).readline)
        if token.type not in (tokenize.STRING, tokenize.COMMENT)
    )
    assert "750" in code


def test_the_quota_is_reported_from_the_lower_bound():
    result = _score([_root(1, 1000)])
    assert result["capacity"]["quota_from_the_lower_bound"] == protocol_module.quota_for(
        1000
    )


def test_the_redundancy_of_the_two_conditions_is_recorded_not_hidden():
    """A reader must not take the quota floor for an independent second hurdle."""
    note = _score([_root(1, 10)])["criterion"]["note_on_redundancy"]
    assert "same boundary" in note
    assert "600 / 0.8 is exactly 750" in note


def test_both_registered_conditions_are_applied(monkeypatch):
    """Forced apart, the quota floor must still be able to fail a count."""
    monkeypatch.setattr(protocol_module, "MINIMUM_C", 10)
    monkeypatch.setattr(protocol_module, "MINIMUM_Q", 900)
    result = _score([_root(1, 100)])
    assert result["verdict"] == scorer.FAIL


# ------------------------------------------------------------- the pool


def test_only_the_declared_extensions_count():
    result = _score([_root(1, 5, suffix=".png")])
    assert result["capacity"]["certain_lower_bound"] == 0
    assert result["ineligible_paths_seen"] == 5


@pytest.mark.parametrize("suffix", list(protocol_module.CANDIDATE_EXTENSIONS))
def test_every_declared_extension_is_counted(suffix):
    assert _score([_root(1, 3, suffix=suffix)])["capacity"]["certain_lower_bound"] == 3


def test_the_extension_test_is_case_insensitive():
    assert _score([_root(1, 2, suffix=".PY")])["capacity"]["certain_lower_bound"] == 2


def test_the_pool_definition_comes_from_the_protocol(monkeypatch):
    monkeypatch.setattr(protocol_module, "CANDIDATE_EXTENSIONS", (".py",))
    assert _score([_root(1, 4, suffix=".md")])["capacity"]["certain_lower_bound"] == 0


def test_a_suffix_that_merely_contains_an_extension_does_not_count():
    """`notes.mdx` is not markdown, and `a.python` is not Python."""
    assert scorer.eligible("notes.mdx") is False
    assert scorer.eligible("a.python") is False
    assert scorer.eligible("a.py") is True


# --------------------------------------------------------- deduplication


def test_the_same_candidate_found_twice_counts_once():
    """Two addresses for one repository must not double its contribution."""
    shared = _candidates("1", 5)
    a = scorer.RootResult(host_uuid="1", disposition=scorer.EXHAUSTED, candidates=shared)
    result = scorer.score(
        [a],
        roster_host_uuids=["1"],
        roster_digest=ROSTER_DIGEST,
        protocol=FROZEN,
    )
    assert result["capacity"]["certain_lower_bound"] == 5

    doubled = scorer.RootResult(
        host_uuid="1", disposition=scorer.EXHAUSTED, candidates=shared + shared
    )
    assert scorer.score(
        [doubled],
        roster_host_uuids=["1"],
        roster_digest=ROSTER_DIGEST,
        protocol=FROZEN,
    )["capacity"]["certain_lower_bound"] == 5


def test_the_same_path_in_two_repositories_counts_twice():
    """Deduplication is by identity, and two repositories are two identities."""
    result = _score([_root(1, 3), _root(2, 3)])
    assert result["capacity"]["certain_lower_bound"] == 6


def test_the_pool_digest_is_a_function_of_membership_alone():
    """Driven with ordered input, which is the only way the sort is visible.

    Through `score` the argument is a set, and two sets with the same members
    iterate identically -- so the same control applied there would pass with the
    sort removed. It has to be asked of the function directly.
    """
    keys = [("1", "a.py", "a" * 40), ("1", "b.py", "b" * 40), ("2", "c.py", "c" * 40)]
    assert scorer.pool_digest(keys) == scorer.pool_digest(list(reversed(keys)))
    assert scorer.pool_digest(keys) != scorer.pool_digest(keys[:2])


def test_the_pool_digest_ignores_the_order_candidates_arrived_in():
    forward = _score([_root(1, 3), _root(2, 3)])
    backward = _score([_root(2, 3), _root(1, 3)])
    assert forward["candidate_pool_digest"] == backward["candidate_pool_digest"]


def test_the_pool_digest_notices_a_missing_candidate():
    assert (
        _score([_root(1, 3)])["candidate_pool_digest"]
        != _score([_root(1, 2)])["candidate_pool_digest"]
    )


# ------------------------------------------------------------- census hygiene


def test_a_root_outside_the_roster_refuses():
    with pytest.raises(scorer.ScoringRefused) as caught:
        _score([_root(1, 3)], roster=["2"])
    assert caught.value.code == scorer.NOT_IN_ROSTER


def test_a_repeated_root_refuses():
    with pytest.raises(scorer.ScoringRefused) as caught:
        _score([_root(1, 3), _root(1, 4)], roster=["1"])
    assert caught.value.code == scorer.DUPLICATE_ROOT


@pytest.mark.parametrize("disposition", ["DONE", "", "complete", None, "EXHAUSTED"])
def test_an_undeclared_root_disposition_refuses(disposition):
    """Silently treating it as measured, or as stopped, are both wrong."""
    with pytest.raises(scorer.ScoringRefused) as caught:
        _score([_root(1, 3, disposition=disposition)], roster=["1"])
    assert caught.value.code == scorer.UNKNOWN_DISPOSITION


def test_the_declared_dispositions_are_the_three_the_scorer_distinguishes():
    assert {
        "FRONTIER_EXHAUSTED",
        "STOPPED_BEFORE_EXHAUSTION",
        "REPOSITORY_IDENTITY_REFUSED",
    } == scorer.DISPOSITIONS


def test_a_root_cannot_be_identified_by_an_address():
    bad = scorer.RootResult(host_uuid="facebook/react", disposition=scorer.EXHAUSTED)
    with pytest.raises(identity.IdentityRefused):
        _score([bad], roster=["1"])


def test_the_score_names_the_roster_and_protocol_it_was_computed_against():
    result = _score([_root(1, 3)])
    assert result["roster_digest"] == ROSTER_DIGEST
    assert result["protocol_digest"] == FROZEN.digest()


def test_the_roster_size_is_reported_even_when_roots_are_missing_from_the_census():
    """A census short of its roster is a completeness fact, not an absence."""
    result = _score([_root(1, 3)], roster=["1", "2", "3"])
    assert result["completeness"]["roster_size"] == 3
    assert result["completeness"]["roots_in_the_census"] == 1
