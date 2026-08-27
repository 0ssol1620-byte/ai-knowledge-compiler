"""The deterministic integration gate for the native-provenance workstreams.

Five lanes were implemented in parallel against one written contract. Every
lane's own suite passed throughout the V1 round and the integration still found
four defects none of them could have found alone — and all four shared one
shape: **none of them raised. Each reported a clean result.** A double-imported
module produced an empty registry, so an extractor was registered, tested and
emitted nothing. A tuple convention differed across a seam, so invalidation was
addressed to a document key that did not exist. An unsupported construct
produced no fact, so a section containing MathML scored perfectly.

That is why this file exists and why it tests the SEAMS rather than the lanes.
A lane's own suite can only check the contract the lane believes in. These
checks put two lanes' beliefs side by side and fail when they differ.

Everything here runs on fixtures. Reading a real lineage before the freeze would
spend the held-out property of the study around it, which is INC-V2-027's
lesson, and no test in this file may do it.
"""

from __future__ import annotations

import hashlib
import inspect
import sys
from pathlib import Path

import yaml

NS = Path(__file__).resolve().parents[1]
for _sub in ("tools", "acquisition", "canonicalization", "compiler", "source_fact_ir"):
    sys.path.insert(0, str(NS / _sub))
sys.path.insert(0, str(NS))

import gpu_successor_preflight as preflight  # noqa: E402
import ir  # noqa: E402
import rebuild_equivalence as reb  # noqa: E402
import score_sfi2 as scorer  # noqa: E402
import sfi2_worker as worker  # noqa: E402
import sources_sfi2 as frame  # noqa: E402
import spanmap as sm  # noqa: E402
from provenance_document import provenance_document  # noqa: E402
from source_fact_ir.compile import load_lanes, missing_lanes  # noqa: E402

load_lanes()

PROTOCOL = NS / "protocols" / "SOURCE_FACT_IR_HELDOUT_V2.yaml"

BEFORE = """# Manual

## Scope

This opening section is written long enough to clear the canonicaliser's minimum
text threshold on its own, and it deliberately contains an &amp; entity together
with a [reference](http://example.invalid/one) so that its canonical text is not
a substring of the bytes it came from.

## Procedure

The second section is likewise long enough to stand as its own unit, which gives
the pair a structural order worth comparing and gives the rebuild something that
can actually move between one revision and the next.
"""

AFTER = BEFORE.replace(
    "[reference](http://example.invalid/one)",
    "[reference](http://example.invalid/two)",
)

META = {
    "source_family": "git_docs",
    "source_id": "integration/manual",
    "known_at": "2026-08-23T00:00:00Z",
    "valid_from": "2026-08-23T00:00:00Z",
    "licence": "test",
}


def document(body: str, version: str) -> tuple[bytes, dict]:
    raw = body.encode("utf-8")
    return raw, provenance_document(
        payload=raw,
        version_id=version,
        source_digest="sha256:" + hashlib.sha256(raw).hexdigest(),
        **META,
    )


# ---------------------------------------------------------------------------
# seam 1 — one IR module, therefore one registry
#
# The V1 integration found `ir` loaded twice under two names, giving two
# registries. Everything downstream looked correct and produced nothing.


def test_every_lane_shares_one_registry():
    assert missing_lanes() == (), missing_lanes()
    #: the partition, not emptiness. An unclaimed kind is the honest answer to
    #: "what does this build not look for", and reading it as a failure would
    #: push a future lane to claim a kind it does not really produce.
    produced = set(ir.registered_kinds())
    unclaimed = set(ir.unclaimed_kinds())
    assert produced | unclaimed == set(ir.KIND_CHANNEL)
    assert not produced & unclaimed


def test_a_kind_that_is_emitted_is_also_claimed():
    """`UNSUPPORTED_CONSTRUCT` was emitted through V1 without being claimed, so
    the registry reported it as a kind nothing looks for while an extractor was
    looking for it. Nothing broke, which is exactly why it survived: the
    declaration and the behaviour disagreed and only the declaration was read."""
    raw, built = document(BEFORE + "\n<math>x</math>\n", "v1")
    emitted = {fact.kind for fact in ir.extract_all(raw=raw, document=built)}
    assert ir.UNSUPPORTED_CONSTRUCT in emitted
    assert emitted <= set(ir.registered_kinds())
    assert not emitted & set(ir.unclaimed_kinds())


def test_the_modules_that_import_ir_all_see_the_same_object():
    """Identity, not equality. Two module objects with equal contents are exactly
    the defect: each has its own registry and neither knows about the other."""
    import core_extractor
    import provenance_document as prov

    assert core_extractor.SourceFact is ir.SourceFact
    assert reb.ir is ir
    assert prov.SpanMap is sm.SpanMap


# ---------------------------------------------------------------------------
# seam 2 — the canonicaliser and the extractor agree on where a span lives
#
# This is the seam the whole V2 round exists to build. If the extractor reads a
# key the canonicaliser does not write, every provenance fact silently reverts
# to the V1 failure and the run reports it as a property of the corpus.


def test_the_extractor_reads_the_key_the_canonicaliser_writes():
    _, built = document(BEFORE, "v1")
    assert built["units"]
    for unit in built["units"]:
        assert "source_span" in unit
        assert "fully_sourced" in unit


def test_native_documents_produce_no_unrepresented_provenance_fact():
    """The endpoint V1 failed, on text no search could have located: an entity is
    decoded and a markdown link is stripped, so the unit's text is not a
    substring of its own source."""
    raw, built = document(BEFORE, "v1")
    facts = ir.extract_all(raw=raw, document=built)
    spans = [fact for fact in facts if fact.kind == ir.PROVENANCE_SPAN]
    assert spans
    assert [fact for fact in spans if fact.state == ir.UNREPRESENTED] == []


def test_every_emitted_span_points_at_bytes_of_its_own_payload():
    raw, built = document(BEFORE, "v1")
    for fact in ir.extract_all(raw=raw, document=built):
        if fact.state != ir.REPRESENTED or fact.kind != ir.PROVENANCE_SPAN:
            continue
        start, end = fact.representation["byte_start"], fact.representation["byte_end"]
        assert 0 <= start < end <= len(raw)


def test_no_scored_path_asks_a_span_map_for_a_sub_range():
    """`to_source` answers at run granularity, so a sub-range query inside one
    long COPY run returns the whole run — a widening, never a wrong region, but
    a widening a caller could mistake for precision (INC-V2-033 §2).

    The reason that limitation is harmless is that nothing scored ever asks. The
    canonicaliser computes each unit's span once, over the unit's whole text,
    and the extractor reads the result. This asserts the property rather than
    trusting it, so a future lane cannot quietly start asking finer questions
    and get an over-approximation back with no sign that it did.
    """
    import core_extractor

    source = inspect.getsource(core_extractor)
    for forbidden in ("to_source(", "SpanMap(", "covering("):
        assert forbidden not in source, forbidden
    _, built = document(BEFORE, "v1")
    for unit in built["units"]:
        #: the span is the whole unit's, so `is_fully_sourced` and the span
        #: describe the same region and neither is a sample of the other.
        assert unit["source_span"] is not None
        assert isinstance(unit["fully_sourced"], bool)


def test_the_extractor_no_longer_searches_for_anything():
    """The founder's ruling was to replace `_locate`, not to widen it. A search
    left anywhere below this line would answer where the native map declines,
    and a wrong span is worse than an absent one because the absent one shows."""
    import core_extractor

    assert not hasattr(core_extractor, "_locate")
    source = inspect.getsource(core_extractor)
    for forbidden in ("raw.find(", "re.escape(", ".search(raw"):
        assert forbidden not in source, forbidden


# ---------------------------------------------------------------------------
# seam 3 — unit_path, the V1 convention defect
#
# One side qualified the path by document, the other did not, so invalidation
# was addressed to a key that did not exist. Nothing raised.


def test_witness_unit_paths_are_document_qualified_everywhere():
    raw, built = document(BEFORE, "v1")
    source_id = built["source_id"]
    for fact in ir.extract_all(raw=raw, document=built):
        path = fact.witness.unit_path
        assert path and path[0] == source_id, (fact.kind, path)


def test_the_canonicalisers_explicit_path_composes_into_the_witness_path():
    raw, built = document(BEFORE, "v1")
    facts = ir.extract_all(raw=raw, document=built)
    emitted = {fact.witness.unit_path for fact in facts}
    for unit in built["units"]:
        assert ir.unit_path_for(built["source_id"], unit["explicit_path"]) in emitted


# ---------------------------------------------------------------------------
# seam 4 — the canonicaliser and the rebuild engine
#
# `judge_pair` refuses a pair whose raw bytes do not match the document's own
# source_digest. The worker computes that digest itself, so the two must agree
# on its exact form — a bare hex digest against a prefixed one would make every
# pair UNJUDGED and both endpoints SKIPPED, which is the V1 outcome again.


def test_a_natively_canonicalised_pair_is_judged_rather_than_refused():
    before_raw, before = document(BEFORE, "v1")
    after_raw, after = document(AFTER, "v2")
    verdict = reb.judge_pair(
        before_document=before,
        after_document=after,
        before_raw=before_raw,
        after_raw=after_raw,
        before_facts=ir.extract_all(raw=before_raw, document=before),
        after_facts=ir.extract_all(raw=after_raw, document=after),
    )
    assert verdict.status != reb.UNJUDGED, (verdict.reason, verdict.detail)
    assert verdict.judged


def test_the_worker_and_the_canonicaliser_agree_on_the_digest_form():
    raw = BEFORE.encode("utf-8")
    built = worker.document_for(
        {"lineage_id": "x", "family": "git_docs", "licence": "test"},
        {"version": "v1", "known_at": None},
        raw,
    )
    assert built["source_digest"] == "sha256:" + hashlib.sha256(raw).hexdigest()
    assert reb._input_refusal("before", built, raw) is None


# ---------------------------------------------------------------------------
# seam 5 — the rebuild summary and the scorer
#
# The scorer reads keys out of `summarise`'s output. Restating them in a test
# fixture would only prove the fixture agrees with the scorer; this drives the
# real function so a renamed key fails here rather than in a scored run.


def test_the_scorer_reads_the_keys_the_summariser_writes():
    before_raw, before = document(BEFORE, "v1")
    after_raw, after = document(AFTER, "v2")
    verdict = reb.judge_pair(
        before_document=before,
        after_document=after,
        before_raw=before_raw,
        after_raw=after_raw,
        before_facts=ir.extract_all(raw=before_raw, document=before),
        after_facts=ir.extract_all(raw=after_raw, document=after),
    )
    summary = reb.summarise([verdict])
    #: The assertion that matters, and the one this test used to lack. It
    #: accepted SKIPPED as a valid outcome "on one fixture pair", which is
    #: precisely how a key mismatch walked through a gate written to catch key
    #: mismatches: the scorer looked for a block under a name the executor does
    #: not use, found nothing, and reported the endpoint as never exercised.
    #: Every key the scorer reads must exist in what the summariser writes.
    for _endpoint, summary_key, violated_key, names_key in scorer.REBUILD_BLOCKS:
        assert summary_key in summary, summary_key
        assert violated_key in summary[summary_key], (summary_key, violated_key)
        assert names_key in summary[summary_key], (summary_key, names_key)
        assert "pairs_that_could_have_exhibited" in summary[summary_key]
        assert "gate_power" in summary[summary_key]

    verdicts = scorer.score_rebuild(summary)
    assert set(verdicts) == set(scorer.REBUILD_ENDPOINTS)


def test_an_empty_rebuild_is_reported_as_unexercised_not_as_clean():
    """`summarise([])` is what a run with nothing to judge produces. It must not
    read as zero violations — that is precisely V1's SKIPPED being laundered."""
    verdicts = scorer.score_rebuild(reb.summarise([]))
    for endpoint in scorer.REBUILD_ENDPOINTS:
        assert verdicts[endpoint]["verdict"] == scorer.SKIPPED


# ---------------------------------------------------------------------------
# seam 6 — the worker, the scorer and the frame agree on names and numbers


def test_the_worker_writes_the_artifact_the_scorer_reads():
    assert worker.OUT / "sfi2_acquisition.json" == scorer.ACQUISITION
    assert worker.PROTOCOL == scorer.PROTOCOL == PROTOCOL


def test_the_protocol_id_is_the_same_in_the_frame_and_the_protocol():
    declared = yaml.safe_load(PROTOCOL.read_text(encoding="utf-8"))
    assert declared["protocol_id"] == frame.PROTOCOL_ID


def test_the_cohort_floor_agrees_across_the_frame_the_protocol_and_the_scorer():
    """Three places state it. A study that met every endpoint on 40 pairs would
    not have shown what it set out to show, and the number was fixed before any
    count existed so that this could never become an argument."""
    declared = yaml.safe_load(PROTOCOL.read_text(encoding="utf-8"))["pass_rule"]
    assert frame.FLOOR == declared["cohort_floor_pairs"] == scorer.COHORT_FLOOR_PAIRS
    assert (
        frame.FAMILIES_REQUIRED
        == declared["families_required"]
        == scorer.FAMILIES_REQUIRED
    )


def test_the_driver_and_the_study_share_their_admission_constants():
    worker.require_shared_admission_constants()


# ---------------------------------------------------------------------------
# seam 7 — this workstream no longer names the GPU gate at all
#
# The preflight used to bind `sfi2-native-provenance`, on the reasoning that SFI1
# was frozen FAIL and a successor stem was the honest thing to wait for. SFI2 is
# now frozen, FAIL and spent too, so that binding could never have turned green
# either — a gate that blocks for the wrong reason will one day unblock for the
# wrong reason. The repair was NOT to point the stem at SFI3. A search that finds
# an authority by name can find one by accident; GPU authority is now one
# explicit immutable path and one digest, named on the command line.
#
# SFI2's own receipts, history and stem are untouched by that retirement. This
# workstream still writes `sfi2-native-provenance`; nothing downstream reads it
# as authorisation any more.


def test_the_preflight_no_longer_binds_this_workstreams_stem():
    assert preflight.RETIRED_HELD_OUT_STUDY_STEM == ""
    assert "sfi2-native-provenance" in preflight.RETIRED_HELD_OUT_STUDY_REASON
    assert not hasattr(preflight, "HELD_OUT_STUDY_STEM")
    assert not hasattr(preflight, "held_out_pass_receipt")


def test_this_workstream_still_writes_its_own_stem():
    """The retirement is of a BINDING, not of SFI2's evidence."""
    source = inspect.getsource(scorer.main)
    assert '"sfi2-native-provenance"' in source


def test_the_gpu_gate_is_still_shut():
    """Nothing in this workstream may open it, and nothing in it is asked to.

    Both acceptances are mandatory and neither substitutes for the other. Naming
    neither is a hard block, which is the state this repository is in.
    """
    assert preflight.sfi3_acceptance_gate(None)["passed"] is False
    assert preflight.four_link_acceptance_gate(None)["passed"] is False


# ---------------------------------------------------------------------------
# seam 8 — the study has not been run, and cannot be run early


def test_the_protocol_is_not_yet_frozen_and_the_tools_refuse_accordingly():
    """The ordering is integrate, freeze, then read fresh lineages. While the
    protocol is a draft both the worker and the scorer must refuse — a study
    whose rules can still move to fit its result is not a study."""
    frozen = sorted((NS / "receipts").glob("sfi2-protocol-freeze--*.json"))
    declared = yaml.safe_load(PROTOCOL.read_text(encoding="utf-8"))
    if not frozen:
        assert declared["status"] == "DRAFT_NOT_FROZEN"
        for refuse in (worker.require_frozen_protocol, scorer.frozen_protocol):
            try:
                refuse()
            except (worker.NotFrozen, scorer.NotFrozen):
                continue
            raise AssertionError(f"{refuse.__qualname__} did not refuse an unfrozen protocol")


def _scan_for(path, marker: str) -> str | None:
    """Find one JSON string value in a large artifact without parsing it.

    The acquisition artifact is 82MB of sorted keys, so the field is nowhere
    near the head and `json.load` would put a multi-second read in every suite
    run. Scanning with an overlap keeps a marker split across a chunk boundary
    from being missed.
    """
    overlap = len(marker) + 64
    tail = ""
    with path.open(encoding="utf-8") as handle:
        while chunk := handle.read(1 << 20):
            window = tail + chunk
            if marker in window:
                return window.split(marker, 1)[1].split('"', 1)[0]
            tail = window[-overlap:]
    return None


def test_the_freeze_precedes_the_first_fresh_lineage():
    """Was the protocol frozen BEFORE the corpus was read?

    This began as `assert not acquisition.exists()` — true and useful until the
    study ran, at which point it asserted a moment that had passed rather than a
    property that must hold. That is the third time a guard in this programme has
    had to be rewritten from a moment into a property, so it is now written as
    the thing that must be true forever: if an acquisition artifact exists, the
    freeze receipt governing it is older than the run that produced it.

    Chronology is the whole of held-out. Two studies were demoted to development
    diagnostics for failing exactly this, and neither failed it by much.
    """
    import json

    acquisition = worker.OUT / "sfi2_acquisition.json"
    if not acquisition.exists():
        return  # nothing read yet; the ordering cannot have been violated

    freezes = sorted((NS / "receipts").glob("sfi2-protocol-freeze--*.json"))
    assert freezes, "a corpus was read with no frozen protocol governing it"
    frozen_at = min(
        json.loads(path.read_text(encoding="utf-8"))["provenance"]["generated_at"]
        for path in freezes
    )

    #: acquisition START, not end. A freeze during a running acquisition is not
    #: a freeze before it.
    started_at = _scan_for(acquisition, '"started_at": "')
    assert started_at, "the artifact does not record when acquisition began"
    assert frozen_at < started_at, (
        f"the protocol was frozen at {frozen_at}, after acquisition began at "
        f"{started_at}. A protocol frozen after the run it governs is not frozen"
    )
