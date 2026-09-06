"""The V2 scorer, and the one thing it must never be able to do.

V1 failed on three grounds and two were absences: E5 and E6 were never
exercised. The founder's V2 ruling closes exactly that —

    V2 PASS requires all E1-E7 to be exercised and met where applicable.
    E5/E6 may not be SKIPPED.

A rule written only in a protocol is a rule a tool can be wrong about. These
tests are the mechanism: every path by which E5 or E6 could reach MET without a
rebuild that actually ran is enumerated and closed, and the cohort floor is
checked as a gate rather than as prose.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest
import yaml

NS = Path(__file__).resolve().parents[1]
for _sub in ("tools", "acquisition", "canonicalization", "compiler", "source_fact_ir"):
    sys.path.insert(0, str(NS / _sub))
sys.path.insert(0, str(NS))

import score_sfi2 as scorer  # noqa: E402

PROTOCOL = NS / "protocols" / "SOURCE_FACT_IR_HELDOUT_V2.yaml"


def row(family: str = "git_markdown", **violations: int) -> dict:
    """One pair's contribution, exercising every fact endpoint by default."""
    made = {"family": family, "lineage_id": "l", "facts_after": 1, "facts_before": 1}
    for endpoint in scorer.FACT_ENDPOINTS:
        made[endpoint] = (violations.get(endpoint, 0), True)
    return made


def rebuild(
    *,
    escape_power: int = 4,
    escapes: int = 0,
    equivalence_power: int = 4,
    divergent: int = 0,
) -> dict:
    return {
        "E5_confirmed_selective_stale_escape": {
            "pairs_that_could_have_exhibited": escape_power,
            "pairs_with_confirmed_escape": escapes,
            "confirmed": [{"lineage_id": "l"}] * escapes,
            "gate_power": bool(escape_power),
        },
        "E6_exact_selective_vs_clean_equivalence": {
            "pairs_that_could_have_exhibited": equivalence_power,
            "pairs_divergent": divergent,
            "divergent": [{"lineage_id": "l"}] * divergent,
            "gate_power": bool(equivalence_power),
        },
    }


# ---------------------------------------------------------------------------
# the scorer and the protocol describe the same seven endpoints


def test_the_scorer_scores_the_endpoints_the_protocol_declares():
    """A renamed or dropped endpoint is a mismatch, never a silent absence."""
    declared = set(yaml.safe_load(PROTOCOL.read_text(encoding="utf-8"))["endpoints"])
    assert declared == set(scorer.ENDPOINTS)


def test_e5_and_e6_are_not_measured_from_facts():
    """Facts say what the IR recognised. Equivalence is a claim about rebuilt
    artifacts, and answering it from facts would invent the result."""
    assert set(scorer.REBUILD_ENDPOINTS).isdisjoint(scorer.FACT_ENDPOINTS)


def test_the_cohort_floor_matches_the_founder_s_ruling():
    pass_rule = yaml.safe_load(PROTOCOL.read_text(encoding="utf-8"))["pass_rule"]
    assert scorer.COHORT_FLOOR_PAIRS == pass_rule["cohort_floor_pairs"] == 200
    assert scorer.FAMILIES_REQUIRED == pass_rule["families_required"] == 3


# ---------------------------------------------------------------------------
# E5/E6 without a rebuild


def test_without_a_rebuild_summary_e5_and_e6_are_skipped_not_met():
    """The exact V1 shape. Nothing rebuilt an artifact, so nothing was measured."""
    verdicts = scorer.score([row()], None)
    for endpoint in scorer.REBUILD_ENDPOINTS:
        assert verdicts[endpoint]["verdict"] == scorer.SKIPPED
        assert verdicts[endpoint]["pairs_exercising"] == 0


def test_an_empty_rebuild_summary_is_not_a_clean_rebuild():
    """`{}` means no rebuild ran, not that zero violations were found."""
    verdicts = scorer.score([row()], {})
    for endpoint in scorer.REBUILD_ENDPOINTS:
        assert verdicts[endpoint]["verdict"] == scorer.SKIPPED


def test_a_rebuild_missing_a_block_raises_rather_than_reporting_skipped():
    """The defect that cost the first scored run its E5 line.

    A block the executor does not write is a broken contract between two tools,
    not a property of the cohort. Reporting it as "never exercised" let a run
    say E5 was not measured while fourteen confirmed escapes sat in the same
    receipt, in a block the scorer had looked for under the wrong name.
    """
    body = rebuild()
    del body["E5_confirmed_selective_stale_escape"]
    with pytest.raises(KeyError, match="disagree about the contract"):
        scorer.score([row()], body)


def test_a_rebuild_with_no_gate_power_is_skipped_not_met():
    """A cohort where no pair carried anything forward cannot show an escape did
    not happen. Zero escapes out of zero opportunities is not evidence."""
    verdicts = scorer.score([row()], rebuild(escape_power=0, equivalence_power=0))
    assert verdicts["E5_no_confirmed_selective_stale_escape"]["verdict"] == scorer.SKIPPED
    assert verdicts["E6_exact_selective_vs_clean_equivalence"]["verdict"] == scorer.SKIPPED


def test_gate_power_false_overrides_a_nonzero_denominator():
    """Belt and braces: the executor sets both, and disagreement fails closed."""
    body = rebuild()
    body["E5_confirmed_selective_stale_escape"]["gate_power"] = False
    verdicts = scorer.score([row()], body)
    assert verdicts["E5_no_confirmed_selective_stale_escape"]["verdict"] == scorer.SKIPPED


def test_a_real_rebuild_with_no_violations_meets_both():
    verdicts = scorer.score([row()], rebuild())
    assert verdicts["E5_no_confirmed_selective_stale_escape"]["verdict"] == scorer.MET
    assert verdicts["E6_exact_selective_vs_clean_equivalence"]["verdict"] == scorer.MET


def test_a_confirmed_escape_fails_e5_and_names_the_case():
    verdicts = scorer.score([row()], rebuild(escapes=1))
    found = verdicts["E5_no_confirmed_selective_stale_escape"]
    assert found["verdict"] == scorer.FAILED
    assert found["violations"] == 1
    #: a count cannot be checked against a rebuild; the cases travel with it.
    assert found["cases"]


def test_a_divergent_pair_fails_e6():
    verdicts = scorer.score([row()], rebuild(divergent=2))
    assert verdicts["E6_exact_selective_vs_clean_equivalence"]["verdict"] == scorer.FAILED


# ---------------------------------------------------------------------------
# the fact endpoints keep V1's behaviour


def test_a_fact_endpoint_nothing_exercised_is_skipped():
    unexercised = row()
    unexercised["E4_no_reference_or_locator_only_clean_miss"] = (0, False)
    verdicts = scorer.score([unexercised], rebuild())
    assert verdicts["E4_no_reference_or_locator_only_clean_miss"]["verdict"] == scorer.SKIPPED


def test_an_unrepresented_fact_fails_e2():
    """The endpoint V1 failed. Native provenance is measured here or nowhere."""
    verdicts = scorer.score([row(E2_no_recognized_but_unrepresented=3)], rebuild())
    found = verdicts["E2_no_recognized_but_unrepresented"]
    assert found["verdict"] == scorer.FAILED
    assert found["violations"] == 3


def test_violations_sum_across_pairs():
    rows = [row(E2_no_recognized_but_unrepresented=2), row(E2_no_recognized_but_unrepresented=5)]
    verdicts = scorer.score(rows, rebuild())
    assert verdicts["E2_no_recognized_but_unrepresented"]["violations"] == 7


# ---------------------------------------------------------------------------
# cohort composition, checked rather than described


def test_a_cohort_under_the_floor_is_short():
    gates = scorer.cohort_gates([row() for _ in range(199)])
    assert gates["pairs_met"] is False


def test_the_floor_is_met_at_exactly_two_hundred():
    gates = scorer.cohort_gates([row() for _ in range(200)])
    assert gates["pairs_met"] is True


def test_two_families_do_not_satisfy_the_family_requirement():
    rows = [row("git_markdown")] * 150 + [row("wikipedia")] * 150
    gates = scorer.cohort_gates(rows)
    assert gates["pairs_met"] is True
    assert gates["families_met"] is False


def test_three_families_satisfy_it():
    rows = [row("git_markdown"), row("wikipedia"), row("ecfr")]
    assert scorer.cohort_gates(rows)["families_met"] is True


# ---------------------------------------------------------------------------
# the verdict rule itself


def verdict_for(rows, rebuild_body) -> str:
    """The scorer's own composition rule, exercised as `main` composes it."""
    verdicts = scorer.score(rows, rebuild_body)
    gates = scorer.cohort_gates(rows)
    failed = [name for name, item in verdicts.items() if item["verdict"] == scorer.FAILED]
    skipped = [name for name, item in verdicts.items() if item["verdict"] == scorer.SKIPPED]
    short = not (gates["pairs_met"] and gates["families_met"])
    return "PASS" if not failed and not skipped and not short else "FAIL"


def full_cohort():
    families = ("git_markdown", "wikipedia", "ecfr")
    return [row(families[index % 3]) for index in range(200)]


def test_a_complete_run_with_no_violations_passes():
    assert verdict_for(full_cohort(), rebuild()) == "PASS"


def test_five_met_endpoints_and_two_skipped_is_a_fail():
    """The V1 outcome, and the temptation the ruling closes. Calling E5 and E6
    not-applicable and passing on the other five would have passed a review."""
    assert verdict_for(full_cohort(), None) == "FAIL"


def test_every_endpoint_met_but_the_cohort_short_is_a_fail():
    assert verdict_for(full_cohort()[:100], rebuild()) == "FAIL"


def test_every_endpoint_met_but_one_family_missing_is_a_fail():
    rows = [row("git_markdown") for _ in range(200)]
    assert verdict_for(rows, rebuild()) == "FAIL"


# ---------------------------------------------------------------------------
# the freeze


def test_scoring_refuses_without_a_freeze_receipt():
    """A scorer that runs against a draft produces a number whose rules could
    still move to fit it."""
    if sorted((NS / "receipts").glob("sfi2-protocol-freeze--*.json")):
        pytest.skip("the protocol has been frozen; the refusal path is no longer live")
    with pytest.raises(scorer.NotFrozen, match="must be frozen"):
        scorer.frozen_protocol()


# ---------------------------------------------------------------------------
# the plumbing, exercised before the corpus is spent
#
# Everything above tests the scoring RULES. This tests that a scored body can
# actually be written — a distinction that matters because the two fail at very
# different moments. A rule error shows up in this suite; a serialisation error
# would show up only after a held-out corpus had been consumed, at the one
# moment the study cannot be re-run.


def synthetic_acquisition(directory, *, pairs: int = 3):
    """An acquisition artifact shaped like the worker's, built from fixtures.

    Never a real lineage. This exists to exercise the writer, not to produce a
    number. It is written UNDER the namespace rather than in a system temp
    directory, because `common.rel` — which the scorer calls on the acquisition
    path — refuses a path outside the repository root. Putting it elsewhere and
    patching `rel` away would have made the test pass while removing the very
    path handling a real run depends on.
    """
    import hashlib
    import json
    import sys
    from pathlib import Path

    NS_LOCAL = Path(__file__).resolve().parents[1]
    for sub in ("tools", "canonicalization", "source_fact_ir"):
        sys.path.insert(0, str(NS_LOCAL / sub))

    import ir
    from provenance_document import provenance_document
    from source_fact_ir.compile import load_lanes

    load_lanes()

    body = (
        "# Fixture\n\n## Section\n\n"
        "This paragraph is long enough to clear the canonicaliser's minimum text "
        "threshold so that a unit is actually produced, which is all this fixture "
        "needs to do for the writer to have something to serialise.\n"
    )
    families = ("git_docs", "regulation_ecfr", "encyclopedia_wikipedia")
    admitted = []
    for index in range(pairs):
        raw = body.replace("Fixture", f"Fixture {index}").encode("utf-8")
        built = provenance_document(
            source_family="git_docs",
            source_id=f"fixture/{index}",
            version_id="v1",
            payload=raw,
            source_digest="sha256:" + hashlib.sha256(raw).hexdigest(),
            known_at=None,
            valid_from=None,
            licence="test",
        )
        facts = [fact.as_dict() for fact in ir.extract_all(raw=raw, document=built)]
        admitted.append(
            {
                "lineage_id": f"fixture/{index}",
                "family": families[index % 3],
                "after_version": "v2",
                "before_version": "v1",
                "facts": {"after": facts, "before": facts},
            }
        )

    path = directory / "synthetic_acquisition.json"
    path.write_text(
        json.dumps({"admitted": admitted, "reduction_digest": "sha256:" + "0" * 64}),
        encoding="utf-8",
    )
    return path


def test_a_scored_body_is_serialisable_before_any_corpus_is_spent(monkeypatch):
    """Drives `main` end to end with the writer replaced by a capture.

    No receipt is written. The launcher no longer selects a receipt by this
    stem -- GPU authority is an explicit path and digest now -- but a synthetic
    receipt under a real study's stem is still evidence-shaped material sitting
    in the receipts directory under a name that means something, and this study's
    own history is what makes that a bad idea.
    """
    import json

    captured = {}

    def capture(stem, body, **kwargs):
        captured["stem"] = stem
        captured["body"] = body
        #: the actual failure being guarded against — a body carrying a tuple
        #: key, a Path, a dataclass or a set serialises nowhere.
        captured["json"] = json.dumps(body, ensure_ascii=False)
        return {"receipt": "<not written>", "run_id": "<none>"}

    monkeypatch.setattr(scorer, "write_immutable", capture)
    directory = NS / "tests" / "_synthetic"
    directory.mkdir(exist_ok=True)
    try:
        path = synthetic_acquisition(directory)
        code = scorer.main(["--acquisition", str(path)])
    finally:
        shutil.rmtree(directory, ignore_errors=True)

    assert captured["stem"] == "sfi2-native-provenance"
    assert captured["json"]
    #: three fixture pairs cannot clear a floor of 200, so the only correct
    #: outcome here is FAIL. A PASS would mean the floor was not enforced.
    assert captured["body"]["verdict"] == "FAIL"
    assert code == 4


def test_no_tool_watches_for_this_stem_any_more():
    """This assertion is the inverse of the one it replaces.

    The preflight used to wait on `sfi2-native-provenance` and this test held the
    two spellings together. SFI2 is frozen, FAIL, spent and permanently
    non-rescorable, so that wait could never have ended: a structurally
    impossible requirement, not a live gate. The binding is retired and was NOT
    re-pointed at a successor stem -- an authority that can be searched for is an
    authority that can be found by accident.

    What is preserved: the scorer still writes its own stem, and SFI2's receipts
    and history are untouched.
    """
    import inspect
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    import gpu_successor_preflight as preflight

    assert '"sfi2-native-provenance"' in inspect.getsource(scorer.main)
    assert preflight.RETIRED_HELD_OUT_STUDY_STEM == ""
    assert "sfi2-native-provenance" in preflight.RETIRED_HELD_OUT_STUDY_REASON
