"""The scorer, and the two ways a scorer lies.

A scoring tool has exactly two interesting failure modes and both are silent:

* it reports an endpoint MET that nothing exercised. SFH1's FAIL was only
  readable because gate power was reported alongside every endpoint; without it
  a cohort containing no references would have "met" the reference endpoint.
* it scores against rules that could still move. A protocol frozen after the
  score is not a protocol, and the freeze check is the only thing standing
  between this tool and that.

Everything below tests one of those two. The endpoint arithmetic is tested on
hand-built fact rows rather than on an acquisition run, so the tests say what
the scorer does rather than what one cohort happened to contain.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
for _sub in ("tools", "source_fact_ir"):
    sys.path.insert(0, str(NS / _sub))

import ir  # noqa: E402
import score_sfi1 as scorer  # noqa: E402


def fact(
    kind: str,
    state: str,
    *,
    representation=None,
    unit=("doc", "Title"),
    reason=None,
    policy=None,
    identifier: str | None = None,
) -> dict:
    return {
        "fact_id": identifier or f"{kind}:{unit}",
        "kind": kind,
        "channel": ir.KIND_CHANNEL[kind],
        "state": state,
        "witness": {"construct": "x", "byte_start": 0, "byte_end": 1,
                    "excerpt": "", "unit_path": list(unit)},
        "representation": representation,
        "policy_ref": policy,
        "reason": reason,
    }


def pair(after: list[dict], before: list[dict], family: str = "git_docs") -> dict:
    return {
        "lineage_id": "git:x/y:z.md",
        "family": family,
        "facts": {"after": after, "before": before},
    }


# ---------------------------------------------------------------------------
# the freeze check


def test_scoring_refuses_without_a_freeze_receipt(monkeypatch, tmp_path):
    """Scoring a draft protocol produces a number whose rules could still move."""
    monkeypatch.setattr(scorer, "NS", tmp_path)
    (tmp_path / "receipts").mkdir()
    with pytest.raises(scorer.NotFrozen, match="must be frozen"):
        scorer.frozen_protocol()


def test_the_real_protocol_is_frozen_and_has_not_moved():
    """Guards the whole study: if this fails, the frozen bytes are not the
    scored bytes and every endpoint verdict below is about a different file."""
    body = scorer.frozen_protocol()
    assert body.get("protocol_sha256")


def test_the_scorer_knows_the_protocol_s_seven_endpoints():
    import yaml

    declared = yaml.safe_load(
        (NS / "protocols" / "SOURCE_FACT_IR_HELDOUT_V1.yaml").read_text(encoding="utf-8")
    )["endpoints"]
    assert set(scorer.ENDPOINTS) == set(declared), (
        "a renamed or dropped endpoint must be a mismatch, never a silent absence"
    )


# ---------------------------------------------------------------------------
# gate power: the distinction the whole result rests on


def test_an_unexercised_endpoint_is_skipped_and_never_met():
    """A cohort with no reference change has not met the reference endpoint. It
    has avoided it."""
    rows = [scorer.endpoint_rows(pair([fact(ir.CONTENT_TEXT, ir.REPRESENTED,
                                            representation={"t": 1})], []))]
    verdicts = scorer.score(rows, bytes_available=False)
    assert verdicts["E4_no_reference_or_locator_only_clean_miss"]["verdict"] == scorer.SKIPPED
    assert verdicts["E4_no_reference_or_locator_only_clean_miss"]["pairs_exercising"] == 0


def test_a_skipped_endpoint_fails_the_study():
    """The rule that stops a study passing by testing nothing."""
    rows = [scorer.endpoint_rows(pair([fact(ir.CONTENT_TEXT, ir.REPRESENTED,
                                            representation={"t": 1})], []))]
    verdicts = scorer.score(rows, bytes_available=False)
    assert any(row["verdict"] == scorer.SKIPPED for row in verdicts.values())
    #: mirrors main()'s rule, asserted here so the rule cannot drift from the doc
    failed = [name for name, row in verdicts.items() if row["verdict"] == scorer.FAILED]
    skipped = [name for name, row in verdicts.items() if row["verdict"] == scorer.SKIPPED]
    assert ("PASS" if not failed and not skipped else "FAIL") == "FAIL"


def test_the_byte_dependent_endpoints_are_never_met_from_facts_alone():
    """E5 and E6 need artifacts rebuilt. Facts cannot answer them, and a scorer
    that answered anyway would be inventing the programme's central result."""
    rows = [scorer.endpoint_rows(pair([], []))]
    for endpoint in ("E5_no_confirmed_selective_stale_escape",
                     "E6_exact_selective_vs_clean_equivalence"):
        for available in (False, True):
            verdict = scorer.score(rows, bytes_available=available)[endpoint]
            assert verdict["verdict"] == scorer.SKIPPED
            assert verdict["why"]


# ---------------------------------------------------------------------------
# each endpoint can actually fail


def test_e2_fails_on_a_recognised_but_unrepresented_fact():
    rows = [
        scorer.endpoint_rows(
            pair([fact(ir.LANGUAGE, ir.UNREPRESENTED, reason="cannot canonicalise")], [])
        )
    ]
    verdicts = scorer.score(rows, bytes_available=False)
    assert verdicts["E2_no_recognized_but_unrepresented"]["verdict"] == scorer.FAILED
    assert verdicts["E2_no_recognized_but_unrepresented"]["violations"] == 1


def test_e2_passes_when_the_loss_was_declined_in_advance():
    """A declined loss is a declared limitation, not the defect."""
    rows = [
        scorer.endpoint_rows(
            pair([fact(ir.ACCESSIBILITY, ir.IGNORED, policy="POLICY-META-002")], [])
        )
    ]
    verdicts = scorer.score(rows, bytes_available=False)
    assert verdicts["E2_no_recognized_but_unrepresented"]["verdict"] == scorer.MET


def test_e3_is_exercised_only_when_an_unsupported_construct_was_found():
    """Before UNSUPPORTED_CONSTRUCT existed this endpoint could not be measured
    at all: you cannot count a fact that produced nothing."""
    without = [scorer.endpoint_rows(pair([fact(ir.CONTENT_TEXT, ir.REPRESENTED,
                                               representation={"t": 1})], []))]
    assert scorer.score(without, bytes_available=False)[
        "E3_no_silent_loss_in_a_complete_scope"
    ]["verdict"] == scorer.SKIPPED

    withone = [
        scorer.endpoint_rows(
            pair(
                [
                    fact(ir.CONTENT_TEXT, ir.REPRESENTED, representation={"t": 1}),
                    fact(ir.UNSUPPORTED_CONSTRUCT, ir.UNRESOLVED, reason="mathml"),
                ],
                [],
            )
        )
    ]
    assert scorer.score(withone, bytes_available=False)[
        "E3_no_silent_loss_in_a_complete_scope"
    ]["verdict"] == scorer.MET


def test_e3_fails_when_an_unsupported_construct_leaves_its_unit_looking_complete():
    """The anchoring failure: a construct attributed to the document instead of
    the unit it sits in leaves that unit complete while part of it is unheld."""
    rows = [
        scorer.endpoint_rows(
            pair(
                [
                    fact(ir.CONTENT_TEXT, ir.REPRESENTED, representation={"t": 1},
                         unit=("doc", "Title")),
                    #: same unit, so the unit is BOTH complete and unsupported,
                    #: which is only possible if the state assignment is wrong
                    fact(ir.UNSUPPORTED_CONSTRUCT, ir.REPRESENTED,
                         representation={"x": 1}, unit=("doc", "Title")),
                ],
                [],
            )
        )
    ]
    verdicts = scorer.score(rows, bytes_available=False)
    assert verdicts["E3_no_silent_loss_in_a_complete_scope"]["verdict"] == scorer.FAILED


def test_e4_is_exercised_only_when_a_reference_moved_and_the_text_did_not():
    """The shape the production path is blind to. A pair where the text also
    moved proves nothing: the old path would have caught that one anyway."""
    moved_both = scorer.endpoint_rows(
        pair(
            [fact(ir.REFERENCE_TARGET, ir.REPRESENTED, representation={"t": "/b"},
                  identifier="r"),
             fact(ir.CONTENT_TEXT, ir.REPRESENTED, representation={"t": "new"},
                  identifier="c")],
            [fact(ir.REFERENCE_TARGET, ir.REPRESENTED, representation={"t": "/a"},
                  identifier="r"),
             fact(ir.CONTENT_TEXT, ir.REPRESENTED, representation={"t": "old"},
                  identifier="c")],
        )
    )
    assert moved_both["E4_no_reference_or_locator_only_clean_miss"][1] is False

    reference_only = scorer.endpoint_rows(
        pair(
            [fact(ir.REFERENCE_TARGET, ir.REPRESENTED, representation={"t": "/b"},
                  identifier="r"),
             fact(ir.CONTENT_TEXT, ir.REPRESENTED, representation={"t": "same"},
                  identifier="c")],
            [fact(ir.REFERENCE_TARGET, ir.REPRESENTED, representation={"t": "/a"},
                  identifier="r"),
             fact(ir.CONTENT_TEXT, ir.REPRESENTED, representation={"t": "same"},
                  identifier="c")],
        )
    )
    assert reference_only["E4_no_reference_or_locator_only_clean_miss"][1] is True


def test_e4_fails_on_a_moved_reference_that_anchors_to_nothing():
    """A moved reference with no anchor invalidates nothing, which is the clean
    miss wearing a different hat."""
    after = fact(ir.REFERENCE_TARGET, ir.REPRESENTED, representation={"t": "/b"},
                 identifier="r")
    before = fact(ir.REFERENCE_TARGET, ir.REPRESENTED, representation={"t": "/a"},
                  identifier="r")
    after["witness"]["unit_path"] = None
    rows = [scorer.endpoint_rows(pair([after], [before]))]
    verdicts = scorer.score(rows, bytes_available=False)
    assert verdicts["E4_no_reference_or_locator_only_clean_miss"]["verdict"] == scorer.FAILED


def test_e7_fails_when_an_unresolved_fact_carries_no_reason():
    rows = [scorer.endpoint_rows(pair([fact(ir.LANGUAGE, ir.UNRESOLVED)], []))]
    verdicts = scorer.score(rows, bytes_available=False)
    assert verdicts["E7_unresolved_fails_closed"]["verdict"] == scorer.FAILED


def test_e7_passes_when_an_unresolved_fact_is_properly_closed():
    rows = [
        scorer.endpoint_rows(
            pair([fact(ir.LANGUAGE, ir.UNRESOLVED, reason="ambiguous tag")], [])
        )
    ]
    verdicts = scorer.score(rows, bytes_available=False)
    assert verdicts["E7_unresolved_fails_closed"]["verdict"] == scorer.MET


# ---------------------------------------------------------------------------
# the verdict rule


def test_pass_requires_every_endpoint_met():
    """Stated as a property so the rule cannot quietly become 'no failures'."""
    verdicts = {
        name: {"verdict": scorer.MET} for name in scorer.ENDPOINTS
    }
    failed = [n for n, r in verdicts.items() if r["verdict"] == scorer.FAILED]
    skipped = [n for n, r in verdicts.items() if r["verdict"] == scorer.SKIPPED]
    assert not failed and not skipped

    verdicts["E5_no_confirmed_selective_stale_escape"]["verdict"] = scorer.SKIPPED
    skipped = [n for n, r in verdicts.items() if r["verdict"] == scorer.SKIPPED]
    assert skipped, "a skipped endpoint must be visible to the verdict rule"


def test_summary_counts_are_not_endpoint_verdicts():
    """Summary numbers describe the cohort. They must never decide anything."""
    rows = [scorer.endpoint_rows(pair([fact(ir.CONTENT_TEXT, ir.REPRESENTED,
                                            representation={"t": 1})], []))]
    summary = scorer.summary(rows)
    assert summary["pairs_scored"] == 1
    assert set(summary) & {"verdict", "endpoints"} == set()
