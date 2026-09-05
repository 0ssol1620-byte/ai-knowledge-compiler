"""Reproduce the receipt, and check the claims it makes are the ones it shows.

Two jobs.

**Reproduction.** `build_receipt.deterministic()` is run again here and compared
against the committed `receipt.json` byte for byte, through the same canonical
serialisation the receipt digests itself with. A receipt that cannot be
reproduced is a screenshot.

**Non-circularity.** A test that only re-ran the generator would pass on any
receipt the generator happened to write, including one asserting the opposite.
So the claims are checked against the artifacts rather than against the summary:
the refusal is re-derived from the fixture, the digest of every input file is
recomputed from the bytes on disk, and the two claims that failed equivalence
are shown to hold identical text and different geometry.

    .venv/Scripts/python.exe -m pytest research/explore_change_receipt_20260905 -q

`research/` is not in `testpaths`, so this runs by path rather than with the
default suite.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import build_receipt
import pytest
from build_receipt import canonical, deterministic

HERE = Path(__file__).resolve().parent
INPUTS = HERE / "inputs"


@pytest.fixture(scope="module")
def committed() -> dict[str, Any]:
    parsed: dict[str, Any] = json.loads((HERE / "receipt.json").read_text(encoding="utf-8"))
    return parsed


@pytest.fixture(scope="module")
def rebuilt() -> dict[str, Any]:
    return deterministic()


# ---------------------------------------------------------------------------
# reproduction


def test_the_receipt_is_reproduced_byte_for_byte(
    committed: dict[str, Any], rebuilt: dict[str, Any]
) -> None:
    assert canonical(rebuilt) == canonical(committed["deterministic"])


def test_the_receipt_digest_is_over_the_receipt(committed: dict[str, Any]) -> None:
    """The digest must be of the bytes beside it, not of an earlier run."""
    expected = (
        "sha256:"
        + hashlib.sha256(canonical(committed["deterministic"]).encode("utf-8")).hexdigest()
    )
    assert committed["deterministicSha256"] == expected


def test_the_readme_quotes_the_digest_the_receipt_actually_has(
    committed: dict[str, Any],
) -> None:
    """The README prints the digest as a citation, so a stale one is a false claim.

    It went stale once already, in the commit that repaired F2: the receipt was
    regenerated and the number beside it was not.
    """
    readme = (HERE / "README.md").read_text(encoding="utf-8")
    assert committed["deterministicSha256"] in readme
    quoted = {line.strip() for line in readme.splitlines() if line.strip().startswith("sha256:")}
    assert quoted == {committed["deterministicSha256"]}, quoted


def test_every_input_file_hashes_to_what_the_receipt_says(committed: dict[str, Any]) -> None:
    recorded = committed["deterministic"]["inputs"]
    assert recorded, "the receipt names no inputs"
    for entry in recorded:
        path = HERE / entry["path"]
        assert path.is_file(), entry["path"]
        payload = path.read_bytes()
        assert "sha256:" + hashlib.sha256(payload).hexdigest() == entry["sha256"], entry["path"]
        assert str(len(payload)) == entry["bytes"], entry["path"]


def test_the_receipt_is_pinned_to_the_commit_the_lane_contract_names(
    committed: dict[str, Any],
) -> None:
    assert committed["deterministic"]["akcCommit"] == build_receipt.AKC_COMMIT
    assert build_receipt.AKC_COMMIT.startswith("26bb892")


# ---------------------------------------------------------------------------
# the fixture


def _entries(name: str) -> dict[str, dict[str, Any]]:
    parsed: list[dict[str, Any]] = json.loads((INPUTS / name).read_text(encoding="utf-8"))
    return {entry["documentId"]: entry for entry in parsed}


def test_revision_b_differs_from_revision_c_only_where_the_contract_says() -> None:
    """§4.3: the interval text reads 1,500 hours and the replacement sentence is gone.

    Pinned here because the explore lane generates the same document from the
    same description, and two lanes reading that description differently would
    produce two files with two digests and no way to tell which is meant.
    """
    entries = _entries("site-fixture.inputs.json")
    before = [region["text"] for region in entries["fp200-maintenance-manual-rev-b"]["regions"]]
    after = [region["text"] for region in entries["fp200-maintenance-manual-rev-c"]["regions"]]

    assert before == [
        "Scheduled maintenance for feedwater pump FP-200, revision B.",
        "Perform the full service procedure every 1,500 operating hours.",
        "Before replacing the mechanical seal, isolate the unit and fully depressurise the "
        "casing. Confirm zero pressure at gauge PG-11 before removing any fastener.",
        "The pump is rated for continuous duty at 2.4 MPa discharge pressure, and inspection "
        "points are listed in table 12.1.",
    ]
    # The two paragraphs the revision does not touch are character-identical.
    assert before[2:] == after[2:]
    assert after[0].endswith("revision C.")
    assert "2,000 operating hours" in after[1]
    assert "replaces the 1,500 hour interval" in after[1]


def test_the_committed_revision_c_pdf_is_the_one_the_site_publishes(
    committed: dict[str, Any],
) -> None:
    """The digest the site committed for it, checked against the copy here."""
    by_path = {entry["path"]: entry for entry in committed["deterministic"]["inputs"]}
    assert by_path["inputs/fp-200-maintenance-manual-revC.pdf"]["sha256"] == (
        "sha256:e8772bf183ab5bb284ab5da62870609ebd79b4bf5bec51ed70c68e2fe4ee48e4"
    )
    assert by_path["inputs/fp-200-change-notice-CN-2026-03.pdf"]["sha256"] == (
        "sha256:50ebc0931467f3770edc54318a6f19e88f0a17d3fbd0389acc4ec89567cc86bf"
    )
    assert by_path["inputs/fp-200-service-log-2026.pdf"]["sha256"] == (
        "sha256:6190995ab7f69629704b8c1a2ea03c1759d570cd3e61dd98d92ef4556574d95e"
    )


# ---------------------------------------------------------------------------
# the gap, re-derived rather than quoted


def test_the_site_fixture_is_refused_and_resolves_no_unit(rebuilt: dict[str, Any]) -> None:
    run = rebuilt["runs"][0]
    assert run["run"] == "site_fixture_verbatim"
    assert run["corpusIsSiteFixture"] is True
    assert run["outcome"] == "refused"
    assert run["refusalCode"] == "CORE_V3_NO_RESOLVABLE_UNIT"
    assert run["unitsResolved"] == 0
    assert run["regionsSeen"] > 0


def test_every_region_of_the_site_fixture_fails_closed(rebuilt: dict[str, Any]) -> None:
    """Not "most". Every one, and each for the same declared reason."""
    for document in rebuilt["runs"][0]["sourceFactLedger"]:
        assert document["units"] == 0, document["documentId"]
        assert document["facts"], document["documentId"]
        for fact in document["facts"]:
            assert fact["state"] == "UNRESOLVED_SOURCE_FACT", fact
            assert fact["kind"] == "UNNUMBERED_PARAGRAPH", fact


def test_the_refusal_comes_from_the_resolver_and_not_from_this_file() -> None:
    """Re-raised straight out of the core, with nothing of ours in between."""
    from akc_core_v3.sources import SourceResolutionRefused, resolve_sources

    entries = _entries("site-fixture.inputs.json")
    corpus = build_receipt.Corpus(
        {entry["ocrJsonKey"]: build_receipt.ocr_record(entry) for entry in entries.values()}
    )
    documents = [
        build_receipt.document_reference(
            entry, native_id=entry["documentId"], title=entry["documentId"]
        )
        for entry in entries.values()
    ]
    with pytest.raises(SourceResolutionRefused) as refusal:
        resolve_sources(corpus, documents)
    assert refusal.value.code == "CORE_V3_NO_RESOLVABLE_UNIT"


# ---------------------------------------------------------------------------
# what the clause-form runs measured


def test_no_run_produces_a_full_rebuild_equivalence_pass(rebuilt: dict[str, Any]) -> None:
    """The result the campaign turns on. If this ever fails, /explore may change."""
    assert rebuilt["equivalencePassAvailable"] is False
    for run in rebuilt["runs"]:
        if "equivalence" in run:
            assert run["equivalence"]["equivalent"] is False, run["run"]


def test_neither_clause_form_run_claims_to_be_the_site_fixture(rebuilt: dict[str, Any]) -> None:
    for run in rebuilt["runs"][1:]:
        assert run["corpusIsSiteFixture"] is False
        assert run["wireableIntoExplore"] is False
        assert "not the FP-200 documents the site serves" in run["caveat"]


def test_the_sealed_response_agrees_with_the_direct_compile(rebuilt: dict[str, Any]) -> None:
    """The plan and the manifest have to come from the same compile."""
    for run in rebuilt["runs"][1:]:
        assert run["sealedResponseAgreesWithDirectCompile"] is True, run["run"]


def test_a_carried_forward_claim_kept_its_words_and_lost_its_box(
    rebuilt: dict[str, Any],
) -> None:
    """Finding F3, shown rather than asserted.

    Each artifact `verify_equivalence` reported as stale-left-behind holds text
    that is byte-identical across the two worlds and a bounding box that is not.
    That is the whole defect: a claim declares itself sensitive to the semantic
    channel and carries locator fields in its body, so it survives a re-typeset
    that moved the clause it cites.
    """
    run = rebuilt["runs"][1]
    witnesses = run["staleLeftBehindWitness"]
    assert witnesses, "the run reported no stale-left-behind artifact"
    assert [item["artifactId"] for item in witnesses] == run["equivalence"]["stale_left_behind"]
    for witness in witnesses:
        carried = witness["carriedForwardBody"]["reads"][0]
        oracle = witness["fullRebuildBody"]["reads"][0]
        assert carried["text"] == oracle["text"], witness["artifactId"]
        assert carried["provenance"]["bbox1000"] != oracle["provenance"]["bbox1000"]
        assert witness["carriedForwardDigest"] != witness["fullRebuildDigest"]


def test_the_amended_clause_is_where_identity_abstained(rebuilt: dict[str, Any]) -> None:
    """Finding F4. One candidate, a score inside the declared review band."""
    units = rebuilt["runs"][1]["revision"]["units"]
    unsettled = [unit for unit in units if unit["identityContinuity"] != "continued"]
    assert len(unsettled) == 1
    (unit,) = unsettled
    assert unit["identityContinuity"] == "ambiguous"
    assert unit["logicalUnitId"].endswith("_2_1")
    assert "review band" in unit["identityReason"]
    # And the abstention is carried into the world rather than smoothed over.
    assert rebuilt["runs"][1]["revision"]["disposition"] == "review_required"
    assert rebuilt["runs"][1]["selectiveRebuild"]["quarantined"]


def test_the_unchanged_documents_are_carried_forward(rebuilt: dict[str, Any]) -> None:
    """Selective recompilation did happen; the receipt is not a report of nothing."""
    selective = rebuilt["runs"][1]["selectiveRebuild"]
    assert selective["counts"]["workAvoided"] > 0
    carried = selective["carriedOver"]
    assert any("change-notice" in artifact for artifact in carried)
    assert any("service-log" in artifact for artifact in carried)
    assert not set(selective["rebuilt"]) & set(carried)


def test_splitting_the_document_id_costs_the_whole_manual(rebuilt: dict[str, Any]) -> None:
    """Gap F2, the artifact half: with one id per revision nothing of the manual carries."""
    shared, split = rebuilt["runs"][1], rebuilt["runs"][2]
    assert shared["documentIdPolicy"] == "one id across both revisions"
    assert split["documentIdPolicy"] == "one id per revision"
    assert (
        split["selectiveRebuild"]["counts"]["quarantined"]
        > shared["selectiveRebuild"]["counts"]["quarantined"]
    )
    # Nothing of the manual survives into the new world by carry-forward: the
    # artifact ids are built from the logical ids, the logical ids carry the
    # document id, and the document id changed. The collection projections are
    # withheld with them, because they read every unit.
    assert not any("manual" in artifact for artifact in split["selectiveRebuild"]["carriedOver"])
    quarantined = split["selectiveRebuild"]["quarantined"]
    assert all(
        "manual" in artifact or artifact.startswith(("collection:", "graph:"))
        for artifact in quarantined
    )
    assert any("manual" in artifact for artifact in quarantined)


# ---------------------------------------------------------------------------
# F2 and F5 -- the identity half, and the guard against describing it from a label
#
# The first version of this receipt asserted, in prose, that with one id per
# revision "no unit continues and the manual is reported replaced rather than
# amended", while `identityCounts.continued` beside it read 9 and nothing
# anywhere reported a replacement. The tests below exist so that class of claim
# fails rather than ships: every number F2 states is recomputed from the run's
# own records, and the label it was read off is shown not to mean what it was
# read to mean.


def _continued(run: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        unit for unit in run["revision"]["units"] if unit["identityContinuity"] == "continued"
    ]


def test_the_continued_label_is_not_a_match_count(rebuilt: dict[str, Any]) -> None:
    """Finding F5, from the records rather than from the summary.

    Both runs report the same `continued` tally. Only one of them has a
    predecessor behind every unit of it, and the difference is the document id.
    """
    shared, split = rebuilt["runs"][1], rebuilt["runs"][2]
    assert shared["revision"]["identityCounts"]["continued"] == 9
    assert split["revision"]["identityCounts"]["continued"] == 9

    with_predecessor = [unit for unit in _continued(split) if unit.get("previousLogicalUnitId")]
    without = [unit for unit in _continued(split) if not unit.get("previousLogicalUnitId")]
    assert len(without) == 3, "the split run is supposed to lose three predecessors"
    assert len(with_predecessor) == 6
    # And every one that lost it lost the relation too: the record says nothing
    # about the lineage at all, rather than saying it is unknown.
    for unit in without:
        assert "identityRelation" not in unit, unit["logicalUnitId"]
        assert "manual" in unit["logicalUnitId"], unit["logicalUnitId"]
    # The shared run is the control: same tally, every predecessor present.
    assert all(unit.get("previousLogicalUnitId") for unit in _continued(shared))
    assert all(unit["identityRelation"] == "SAME_AS_VERSION" for unit in _continued(shared))


def test_the_identity_breakdown_in_the_receipt_matches_the_records(
    rebuilt: dict[str, Any],
) -> None:
    """The block F2 is written from is recomputed here from the units beside it."""
    for index in (1, 2):
        run = rebuilt["runs"][index]
        recorded = run["revision"]["identityContinuity"]
        continued = _continued(run)
        without = sorted(
            unit["logicalUnitId"] for unit in continued if not unit.get("previousLogicalUnitId")
        )
        assert recorded["continued"] == len(continued) == run["revision"]["identityCounts"][
            "continued"
        ], run["run"]
        assert recorded["continuedWithoutRecordedPredecessor"] == len(without), run["run"]
        assert recorded["continuedWithoutRecordedPredecessorIds"] == without, run["run"]
        assert (
            recorded["continuedWithRecordedPredecessor"] == len(continued) - len(without)
        ), run["run"]


def test_the_resolver_did_match_across_the_document_id_change(
    rebuilt: dict[str, Any],
) -> None:
    """Gap F2, part 1: the correspondence is in the diff, not in the label.

    A change carrying a logical id that belongs to the before world and not to
    the after world is a match the resolver made -- that branch is reached only
    after the decision's id resolved to a prior unit. An after-unit with no
    counterpart is reported `unit_added` instead, so the absence of any such
    record is the other half of the same statement.
    """
    split = rebuilt["runs"][2]
    after = {unit["logicalUnitId"] for unit in split["revision"]["units"]}
    changes = split["revision"]["diffChanges"]
    assert changes, "the split run recorded no diff"
    assert not [change for change in changes if change["kind"] == "unit_added"]

    cross = [
        change
        for change in changes
        if change.get("logical_id") and change["logical_id"] not in after
    ]
    assert len(cross) == 4, [change["kind"] for change in cross]
    assert {change["logical_id"] for change in cross} == {
        "ku_fp200-maintenance-manual-clause-rev-b_1_1",
        "ku_fp200-maintenance-manual-clause-rev-b_3_1",
        "ku_fp200-maintenance-manual-clause-rev-b_4_1",
    }
    # The unsettled unit names its predecessor as the candidate, which is the
    # same statement from the other side.
    (unresolved,) = [change for change in changes if change["kind"] == "identity_unresolved"]
    assert unresolved["candidates"] == ["ku_fp200-maintenance-manual-clause-rev-b_2_1"]

    # Same diff, different ids: the shared run attributes everything to ids that
    # exist in both worlds, so nothing is "cross" there.
    shared = rebuilt["runs"][1]
    shared_after = {unit["logicalUnitId"] for unit in shared["revision"]["units"]}
    assert not [
        change
        for change in shared["revision"]["diffChanges"]
        if change.get("logical_id") and change["logical_id"] not in shared_after
    ]
    assert [change["kind"] for change in shared["revision"]["diffChanges"]] == [
        change["kind"] for change in changes
    ]


def test_what_the_split_id_actually_broke_is_the_impact_path(
    rebuilt: dict[str, Any],
) -> None:
    """Gap F2, part 3. The failure is downstream of identity and it fails closed."""
    split = rebuilt["runs"][2]
    assert split["revision"]["impact"]["affectedArtifactIds"] == []
    assert split["plan"]["stale"] == []
    assert split["revision"]["unresolvedChannels"] == ["locator"]
    (facet,) = split["plan"]["facetResolutions"]
    assert facet["verdict"] == "unresolved"
    assert "not a node in the dependency graph" in facet["reason"]
    # Six artifacts a full rebuild produces are never built by the selective one.
    missing = split["equivalence"]["missing_from_selective"]
    assert len(missing) == 6
    assert all("manual" in artifact for artifact in missing)
    # The shared run is the control again: the same change routes to real work.
    shared = rebuilt["runs"][1]
    assert shared["revision"]["impact"]["affectedArtifactIds"]
    assert shared["equivalence"]["missing_from_selective"] == []


def test_f2_states_the_numbers_its_own_run_measured(rebuilt: dict[str, Any]) -> None:
    """The guard the first version of this receipt did not have.

    F2's prose is generated from the runs, so it cannot drift from them. This
    asserts the generation actually happened: every count the sentence gives is
    recomputed here and looked for in the string, and the retracted claim is
    checked for by name.
    """
    (f2,) = [gap for gap in rebuilt["blockedBy"] if gap["id"] == "F2"]
    observed = f2["observedState"]
    split = rebuilt["runs"][2]
    breakdown = split["revision"]["identityContinuity"]

    assert f"reads {split['revision']['identityCounts']['continued']} in BOTH runs" in observed
    assert f"only {breakdown['continuedWithRecordedPredecessor']} do" in observed
    assert f"{breakdown['continuedWithoutRecordedPredecessor']} carry neither" in observed
    assert (
        f"builds the {len(split['equivalence']['missing_from_selective'])} manual artifacts"
        in observed
    )
    for unit_id in breakdown["continuedWithoutRecordedPredecessorIds"]:
        assert unit_id in observed

    # The claim that was refuted by the block beside it. It must not come back,
    # in F2 or anywhere else in the receipt.
    assert "no unit continues" not in canonical(rebuilt)


def test_f5_is_recorded_as_a_finding_with_its_line_numbers(rebuilt: dict[str, Any]) -> None:
    (f5,) = [finding for finding in rebuilt["findings"] if finding["id"] == "F5"]
    assert f5["kind"] == "correctness"
    assert any("revision_compile.py:883" in where for where in f5["where"])
    assert f5["notFixedHere"]


def test_the_receipt_states_that_no_core_file_was_modified(rebuilt: dict[str, Any]) -> None:
    assert rebuilt["protectedCoreModified"] is False
    assert rebuilt["coreFilesModified"] == []
    assert rebuilt["status"] == "blocked"


# ---------------------------------------------------------------------------
# the population a number was measured over, and whose fixture it is
#
# Both classes of error below shipped once. The receipt was hash-bound,
# byte-reproducible and green when they did, because every test compared machine
# values to machine values. These compare a written sentence to the run it cites,
# and a claim about another repository to that repository.


def test_the_whole_fixture_refusal_is_measured_and_not_inferred(
    rebuilt: dict[str, Any],
) -> None:
    """A world holds three documents; the fixture holds four. Both are counted.

    `runs[0]` compiles the revision-B world, so its ten regions are ten regions
    of three documents. Any sentence about "the four documents" needs the wider
    number, and the wider number is a real call into `resolve_sources` rather
    than an inference from the narrow one.
    """
    run = rebuilt["runs"][0]
    whole = run["wholeFixtureResolverCheck"]

    assert run["documentsCompiled"] == 3
    assert run["regionsSeen"] == 10
    assert whole["documentsSeen"] == 4
    assert whole["regionsSeen"] == 14
    assert whole["regionsSeen"] != run["regionsSeen"], (
        "the two populations must stay distinguishable; if they ever coincide, "
        "the sentences that name them stop being checkable"
    )

    # Recomputed from the fixture on disk rather than from the receipt.
    entries = _entries("site-fixture.inputs.json")
    assert whole["documentIds"] == sorted(entries)
    assert whole["regionsSeen"] == sum(len(entry["regions"]) for entry in entries.values())

    # And the wider population refuses for the same reason, which is the claim
    # the README makes about the corpus.
    assert whole["outcome"] == "refused"
    assert whole["refusalCode"] == "CORE_V3_NO_RESOLVABLE_UNIT"
    assert whole["unitsResolved"] == 0
    assert whole["unitsCanonicalised"] == 0


def test_f1_states_each_count_beside_the_set_it_was_counted_over(
    rebuilt: dict[str, Any],
) -> None:
    """F1's observed state is generated from both populations, not typed."""
    (f1,) = [gap for gap in rebuilt["blockedBy"] if gap["id"] == "F1"]
    observed = f1["observedState"]
    run = rebuilt["runs"][0]
    whole = run["wholeFixtureResolverCheck"]

    assert f"{run['documentsCompiled']} documents and {run['regionsSeen']} regions" in observed
    assert f"{whole['documentsSeen']} documents, {whole['regionsSeen']} regions" in observed
    assert "UNNUMBERED_PARAGRAPH" in observed
    assert "UNRESOLVED_SOURCE_FACT" in observed


def test_the_readme_carries_the_populations_the_runs_measured(
    committed: dict[str, Any],
) -> None:
    """The README is the file a founder reads, so its counts are enforced too.

    Every false statement this lane has shipped landed here: a retracted
    conclusion, then a stale digest, then a count printed against the wrong
    population. `build_receipt.readme_assertions` derives the fragments that
    would mislead if they went wrong, and this asserts the file contains each
    one verbatim.
    """
    readme = (HERE / "README.md").read_text(encoding="utf-8")
    for label, fragment in build_receipt.readme_assertions(committed["deterministic"]).items():
        assert fragment in readme, f"README no longer states {label}: {fragment!r}"

    # The exact conflation the review caught, barred by name in either spelling.
    for retracted in ("ten regions of the four documents", "10 regions of the 4 documents"):
        assert retracted not in readme.lower(), retracted
