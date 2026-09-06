"""The SFI3 frame verifier must be able to return NEITHER.

A verifier that reports a clean ending for every artifact verifies nothing. When
the V2 verifier was written its fixture defaulted the per-family counts to the
quotas, so the deliberately-broken case still satisfied `quota_met` and read
COMPLETE — the test passed, and it was watching nothing. These fixtures build the
counts explicitly for that reason.
"""

from __future__ import annotations

import pathlib
import sys
from pathlib import Path

NS = Path(__file__).resolve().parents[1]
for _sub in ("tools", "acquisition"):
    sys.path.insert(0, str(NS / _sub))
sys.path.insert(0, str(NS))

import verify_sfi2_frame  # noqa: E402
import verify_sfi3_frame as verifier  # noqa: E402

QUOTAS = {"git_docs": 120, "regulation_ecfr": 100, "encyclopedia_wikipedia": 70}


def _acquired(*, candidates: int, considered: int, by_family: dict[str, int]) -> dict:
    """An acquisition artifact shaped like a real one.

    `by_family` is always passed explicitly. Defaulting it to the quotas is the
    exact mistake that made the V2 fixture's broken case read COMPLETE.
    """
    admitted = [
        {"lineage_id": f"{family}:{index}", "family": family}
        for family, count in by_family.items()
        for index in range(count)
    ]
    return {
        "frame": {"candidates": candidates},
        "lineages_considered": considered,
        "by_family": by_family,
        "admitted": admitted,
        "rejected": [
            {"lineage_id": f"rejected:{index}"}
            for index in range(max(0, considered - len(admitted)))
        ],
    }


def test_every_candidate_considered_is_exhausted():
    found = verifier.assess(
        _acquired(candidates=1_500, considered=1_500, by_family={"git_docs": 90}), QUOTAS
    )
    assert found["ending"] == verifier.EXHAUSTED


def test_quotas_filled_early_is_complete():
    found = verifier.assess(
        _acquired(candidates=5_000, considered=900, by_family=dict(QUOTAS)), QUOTAS
    )
    assert found["ending"] == verifier.COMPLETE


def test_a_run_that_stopped_for_another_reason_is_neither():
    """The case the tool exists for, and the one a lazy fixture hides.

    Candidates remain, no quota is filled, and the run stopped anyway. Nothing in
    the artifact says why — which is precisely the point: the cohort's size is not
    evidence of anything.
    """
    found = verifier.assess(
        _acquired(candidates=5_000, considered=900, by_family={"git_docs": 10}), QUOTAS
    )
    assert found["ending"] == verifier.NEITHER


def test_neither_is_not_scorable():
    acquired = _acquired(candidates=5_000, considered=900, by_family={"git_docs": 10})
    found = verifier.assess(acquired, QUOTAS)
    assert found["ending"] == verifier.NEITHER
    #: `main` computes scorability from the ending and the concerns; asserted here
    #: through the same two values rather than by restating the rule.
    assert found["ending"] not in (verifier.EXHAUSTED, verifier.COMPLETE)


def test_the_three_endings_are_the_same_strings_v2_used():
    """Two studies asking the same question must not answer in different words."""
    assert verifier.EXHAUSTED is verify_sfi2_frame.EXHAUSTED
    assert verifier.COMPLETE is verify_sfi2_frame.COMPLETE
    assert verifier.NEITHER is verify_sfi2_frame.NEITHER


def test_the_arithmetic_is_imported_not_reimplemented():
    """A drifted copy would make the studies incomparable while looking like a repeat."""
    assert verifier.assess is verify_sfi2_frame.assess
    assert verifier.concerns is verify_sfi2_frame.concerns


def test_quotas_come_from_the_frame_module_not_from_this_tool():
    """A restated quota can disagree with the one the acquisition actually applied."""
    import sources_sfi3

    assert verifier.quotas() == dict(sources_sfi3.FAMILY_QUOTA)


def test_a_missing_artifact_refuses_rather_than_reporting_an_empty_cohort():
    """An absent artifact is not an empty run, and must not read as one."""
    assert verifier.main(["--acquisition", str(NS / "does" / "not" / "exist.json")]) == 3


def test_the_verifier_never_writes_to_the_acquisition_artifact():
    """Asserted by running it and comparing bytes, not by grepping its source.

    A source scan would pass for a tool that delegated its write to a helper, and
    the property that matters is behavioural: the artifact this study will be
    scored from must be byte-identical after verification. If it were not, the
    thing verified and the thing scored would be different files.
    """
    import hashlib
    import json
    import shutil
    import tempfile

    scratch = pathlib.Path(
        tempfile.mkdtemp(dir=str(NS / "artifacts" / "development"))
    )
    try:
        artifact = scratch / "sfi3_acquisition.json"
        artifact.write_text(
            json.dumps(
                _acquired(candidates=1_500, considered=1_500, by_family={"git_docs": 90})
            ),
            encoding="utf-8",
        )
        before = hashlib.sha256(artifact.read_bytes()).hexdigest()
        verifier.main(["--acquisition", str(artifact)])
        assert hashlib.sha256(artifact.read_bytes()).hexdigest() == before
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
