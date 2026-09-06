"""The V2 worker: native documents in, facts and a rebuild verdict out.

Fixtures only. No network, no real lineage, nothing that could spend the corpus —
the founder's ordering is freeze first, read fresh lineages after, and a test
that touched one would spend the held-out property of the study around it. That
is the mistake INC-V2-027 records and it is not repeated here.

Two things carry the weight:

* `RebuildJudge` learns which two extractions form a pair from the ORDER the
  imported driver calls it in. That is an assumption about somebody else's
  control flow, so it is tested against the real driver rather than a mock of
  it — if `sfi1_worker` ever extracted the two sides apart, or on two threads,
  the pairing would break silently and E5/E6 would quietly go missing again.
* the admission constants the driver reads belong to V1's frame module. V2
  shares them deliberately, and the run refuses if that ever stops being true.
"""

from __future__ import annotations

import hashlib
import sys
import threading
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
for _sub in ("tools", "acquisition", "canonicalization", "compiler", "source_fact_ir"):
    sys.path.insert(0, str(NS / _sub))
sys.path.insert(0, str(NS))

import ir  # noqa: E402
import rebuild_equivalence as reb  # noqa: E402
import sfi1_worker as base  # noqa: E402
import sfi2_worker as worker  # noqa: E402
from source_fact_ir.compile import load_lanes  # noqa: E402

load_lanes()


BODY = """# Handbook

## Overview

This paragraph is deliberately long enough to clear the minimum text threshold
the canonicaliser applies before it will admit a unit at all, and it contains an
&amp; entity plus a [link](http://example.invalid/spec) so the mapping has to
survive decoding and markup stripping rather than a plain copy.

## Details

A second substantial paragraph, also long enough to be admitted on its own, so
the fixture has two units and a structural order worth comparing across a pair
of revisions rather than a single block that could be matched by luck.
"""

AFTER = BODY.replace("A second substantial", "A second, revised substantial")

LINEAGE = {
    "lineage_id": "fixture/handbook",
    "family": "git_docs",
    "suffix": ".md",
    "licence": "test",
}


def revisions(_lineage):
    return [
        {"version": "v2", "url": "fixture://v2", "known_at": "2026-08-02T00:00:00Z"},
        {"version": "v1", "url": "fixture://v1", "known_at": "2026-08-01T00:00:00Z"},
    ]


def payload_for(_lineage, revision):
    raw = (AFTER if revision["version"] == "v2" else BODY).encode("utf-8")
    return raw, "sha256:" + hashlib.sha256(raw).hexdigest()


def run_one(extract=None):
    """One lineage through the real driver, with fixture payloads."""
    return base.evaluate(
        LINEAGE,
        payload_for,
        revisions_for=revisions,
        document_for=worker.document_for,
        extract=extract or ir.extract_all,
    )


# ---------------------------------------------------------------------------
# the documents the worker builds carry witnesses


def test_the_worker_builds_documents_with_a_span_for_every_unit():
    raw = BODY.encode("utf-8")
    document = worker.document_for(LINEAGE, revisions(None)[1], raw)
    units = document["units"]
    assert units, "the fixture must produce units or it tests nothing"
    for unit in units:
        assert unit["source_span"] is not None
        start, end = unit["source_span"]
        #: the span points at real bytes of this payload, not at an offset in
        #: some intermediate stage.
        assert 0 <= start < end <= len(raw)


def test_provenance_spans_are_represented_under_the_native_canonicaliser():
    """The endpoint V1 failed, on a fixture the old design would have failed too:
    the unit's text is not a substring of the source — an entity is decoded and a
    markdown link is stripped — so nothing could have found it by searching."""
    raw = BODY.encode("utf-8")
    document = worker.document_for(LINEAGE, revisions(None)[1], raw)
    facts = ir.extract_all(raw=raw, document=document)
    spans = [fact for fact in facts if fact.kind == ir.PROVENANCE_SPAN]
    assert spans
    assert all(fact.state == ir.REPRESENTED for fact in spans)
    assert "&amp;" in BODY and "](http" in BODY


def test_no_fact_is_recognized_but_unrepresented_on_the_fixture():
    raw = BODY.encode("utf-8")
    document = worker.document_for(LINEAGE, revisions(None)[1], raw)
    tally = ir.tally(ir.extract_all(raw=raw, document=document))
    assert tally[ir.UNREPRESENTED] == 0


# ---------------------------------------------------------------------------
# the pairing assumption, tested against the real driver


def test_the_driver_produces_exactly_one_verdict_per_pair():
    judge = worker.RebuildJudge(ir.extract_all)
    found = run_one(judge)
    assert found["code"] is None, found
    assert len(judge.verdicts) == 1
    assert judge.errors == []


def test_the_verdict_is_keyed_by_the_lineage_the_reduction_admits_by():
    """The join between a verdict and an admitted pair. If the two ever used
    different keys the rebuild would be silently scored over an empty cohort."""
    judge = worker.RebuildJudge(ir.extract_all)
    run_one(judge)
    assert judge.verdicts[0].lineage_id == LINEAGE["lineage_id"]


def test_the_verdict_names_the_two_revisions_the_pair_was_built_from():
    judge = worker.RebuildJudge(ir.extract_all)
    run_one(judge)
    verdict = judge.verdicts[0]
    assert (verdict.before_version, verdict.after_version) == ("v1", "v2")


def test_wrapping_the_extractor_does_not_change_the_facts():
    """The judge must be transparent. A rebuild that altered the fact stream
    would make E1-E4 and E7 measurements of a different thing than V1's."""
    plain = run_one(None)
    judged = run_one(worker.RebuildJudge(ir.extract_all))
    assert plain["facts"] == judged["facts"]


def test_a_rebuild_that_raises_loses_the_endpoint_and_not_the_facts():
    """A gap in one endpoint must not become a gap in five."""

    def explode(**_kwargs):
        raise RuntimeError("engine unavailable")

    judge = worker.RebuildJudge(ir.extract_all)
    original = reb.judge_pair
    reb.judge_pair = explode
    try:
        found = run_one(judge)
    finally:
        reb.judge_pair = original
    assert found["code"] is None
    assert found["facts"]["after"] and found["facts"]["before"]
    assert judge.verdicts == []
    assert judge.errors and "engine unavailable" in judge.errors[0]["error"]


def test_two_lineages_on_two_threads_do_not_cross_pair():
    """The buffer is thread-local for this reason. A shared buffer would pair
    one lineage's after side with another's before side and judge equivalence
    between two documents that were never a revision of each other."""
    judge = worker.RebuildJudge(ir.extract_all)
    errors: list[BaseException] = []

    def drive() -> None:
        try:
            run_one(judge)
        except BaseException as error:  # surfaced, never swallowed
            errors.append(error)

    threads = [threading.Thread(target=drive) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert len(judge.verdicts) == 4
    for verdict in judge.verdicts:
        assert (verdict.before_version, verdict.after_version) == ("v1", "v2")


def test_the_judge_holds_at_most_one_half_pair_per_thread():
    judge = worker.RebuildJudge(ir.extract_all)
    run_one(judge)
    assert getattr(judge._local, "pending", None) is None


# ---------------------------------------------------------------------------
# the guards


def test_the_admission_constants_are_shared_with_the_imported_driver():
    """Not decoration. The driver fills quotas and bounds payloads from V1's
    frame module, so a divergence would collect a cohort no declaration names."""
    worker.require_shared_admission_constants()
    assert base.frame_module.FAMILY_QUOTA == worker.frame_module.FAMILY_QUOTA
    assert base.frame_module.MAX_PAYLOAD_BYTES == worker.frame_module.MAX_PAYLOAD_BYTES


def test_a_diverged_quota_refuses_rather_than_collecting_quietly(monkeypatch):
    monkeypatch.setattr(
        worker.frame_module, "FAMILY_QUOTA", {"git_docs": 1}, raising=True
    )
    with pytest.raises(RuntimeError, match="never collected"):
        worker.require_shared_admission_constants()


def test_acquisition_refuses_without_a_protocol_freeze():
    if sorted((NS / "receipts").glob("sfi2-protocol-freeze--*.json")):
        pytest.skip("the protocol has been frozen; the refusal path is no longer live")
    with pytest.raises(worker.NotFrozen, match="before"):
        worker.require_frozen_protocol()


def test_the_real_acquisition_path_carries_the_injections_through():
    """The path `main` actually takes, not the one the unit tests take.

    Every test above drives `base.evaluate` directly, and all of them passed
    while `main` was calling `base.acquire(..., document_for=...)` — a signature
    that does not exist. The run died on the first line of acquisition with a
    TypeError. Nothing was fetched and no corpus was spent, which was luck
    rather than design: the guard that should have caught it is this test, and
    it did not exist.

    Testing a helper is not testing the path. Here the whole loop runs.
    """
    judge = worker.RebuildJudge(ir.extract_all)
    lineages = [dict(LINEAGE, lineage_id=f"fixture/handbook-{index}") for index in range(3)]

    def revisions_for(_lineage):
        return revisions(None)

    original = base._default_revisions_for
    base._default_revisions_for = revisions_for
    try:
        reduced = worker.acquire(
            lineages,
            payload_for,
            workers=2,
            chunk=2,
            document_for=worker.document_for,
            extract=judge,
            progress=lambda _line: None,
        )
    finally:
        base._default_revisions_for = original

    assert reduced["considered"] == 3
    assert len(reduced["admitted"]) == 3, reduced["rejected"]
    #: the injections reached the bottom: native documents were built and every
    #: pair was judged. Either failing would leave E5 and E6 unexercised.
    assert len(judge.verdicts) == 3
    for row in reduced["admitted"]:
        facts = row["facts"]["after"]
        spans = [fact for fact in facts if fact["kind"] == ir.PROVENANCE_SPAN]
        assert spans
        assert all(fact["state"] == ir.REPRESENTED for fact in spans)


def test_the_summary_the_worker_stores_is_the_one_the_scorer_scores():
    """`main` reduces the verdicts to a summary and stores it under `rebuild`.
    A shape the scorer cannot read would leave E5 and E6 SKIPPED after a rebuild
    that actually ran — V1's outcome reached by a new route."""
    import score_sfi2

    judge = worker.RebuildJudge(ir.extract_all)
    run_one(judge)
    verdicts = score_sfi2.score_rebuild(reb.summarise(judge.verdicts))
    assert set(verdicts) == set(score_sfi2.REBUILD_ENDPOINTS)
    for endpoint in score_sfi2.REBUILD_ENDPOINTS:
        assert "verdict" in verdicts[endpoint]


def test_the_worker_writes_where_the_scorer_reads():
    """Two tools, one artifact. A mismatch here would have the scorer report a
    missing cohort while the worker reported a successful run."""
    import score_sfi2

    assert worker.OUT / "sfi2_acquisition.json" == score_sfi2.ACQUISITION
    assert worker.PROTOCOL == score_sfi2.PROTOCOL
