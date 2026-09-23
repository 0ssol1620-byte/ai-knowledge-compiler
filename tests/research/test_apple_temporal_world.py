"""Replay the Apple temporal World and hold its receipts to their digests.

Slow on purpose. The point of this module is that the numbers in
`research/apple_temporal_world_20260908/receipts/` came from running the
compiler on the committed filing bytes, and the only way to keep that true is to
run it again and compare digests. A faster test that asserted the committed JSON
against itself would pass forever and prove nothing.

What it pins:

* the five filings' bytes, by sha256, against the public SEC corpus manifest;
* the two chain receipts, by sha256, against a fresh run into a temp directory;
* the per-step counts and rebuild fractions, spelled out here rather than read
  from the file, so a silent change to the receipt fails the test;
* the two fail-closed refusals -- a partial world and a selective build with no
  equivalence check -- both of which must refuse;
* the shadow verdict on PR #46's challenger: it is not better than the branch's
  own protected core on this corpus, and on the revision step it is worse.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[2]
RESEARCH = REPO / "research" / "apple_temporal_world_20260908"
sys.path.insert(0, str(REPO / "services" / "core-v3" / "src"))
sys.path.insert(0, str(RESEARCH))

import run_chain  # noqa: E402

pytestmark = pytest.mark.slow

COMMITTED = RESEARCH / "receipts"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def replay(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """One full W0->W4 + R0->R2 run, into a temp directory."""
    out = tmp_path_factory.mktemp("apple-temporal-world")
    assert run_chain.main(["run_chain.py", str(RESEARCH / "sources"), str(out)]) == 0
    return {
        "out": out,
        "manifest": _load(out / "MANIFEST.json"),
        "chain_a": _load(out / "steps" / "chain-a.json"),
        "chain_b": _load(out / "steps" / "chain-b.json"),
    }


def test_the_committed_filing_bytes_are_the_ones_the_manifest_declares() -> None:
    """Every number below is about these five files and no others."""
    for filing in run_chain.FILINGS:
        path = RESEARCH / "sources" / filing.pdf_filename
        assert path.exists(), f"{filing.filing_id}: source bytes are not committed"
        assert _sha256(path) == filing.pdf_sha256, filing.filing_id


def test_the_receipts_reproduce_byte_for_byte(replay: dict[str, Any]) -> None:
    """A fresh run must hash to what the committed manifest recorded."""
    committed = _load(COMMITTED / "MANIFEST.json")
    for name, digest in committed["receipts"].items():
        produced = replay["out"] / name
        text = produced.read_text(encoding="utf-8")
        actual = "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
        assert actual == digest, name


def test_chain_a_is_the_five_filings_at_two_hundred_and_ninety_pages(
    replay: dict[str, Any],
) -> None:
    steps = replay["chain_a"]["steps"]
    assert [s["step"] for s in steps] == ["w0", "w1", "w2", "w3", "w4"]
    assert [s["pages"] for s in steps] == [80, 110, 213, 250, 290]
    assert [s["units"] for s in steps] == [36, 53, 58, 75, 92]
    assert [s["artifacts"] for s in steps] == [77, 112, 123, 158, 193]
    # One exact evidence locator per unit: page and bbox1000 from the parser.
    for step in steps:
        assert step["evidenceLocators"] == step["units"]


def test_chain_a_rebuild_fractions(replay: dict[str, Any]) -> None:
    """The selective-recompilation numbers, per arm, spelled out."""
    steps = replay["chain_a"]["steps"]
    assert steps[0]["arms"]["rebuildFraction"] == 1.0  # initial compile

    expected_default = [0.339286, 0.113821, 0.240506, 0.196891]
    expected_precise = [0.348214, 0.121951, 0.246835, 0.202073]
    for step, default, precise in zip(
        steps[1:], expected_default, expected_precise, strict=True
    ):
        arms = step["arms"]
        assert arms["legacy_default"]["rebuildFraction"] == default, step["step"]
        assert arms["legacy_precise"]["rebuildFraction"] == precise, step["step"]
        # The challenger is measured, never promoted.
        assert arms["challenger"]["rebuildFraction"] == precise, step["step"]


def test_the_default_recompilation_plan_leaves_the_directory_stale(
    replay: dict[str, Any],
) -> None:
    """The finding this corpus produced, held so it cannot regress silently.

    `plan_recompilation` with no arguments does not reach `collection:directory`
    on any step: the projection's edges declare only the structural channel and
    structural propagation is off by default. The equivalence oracle catches it,
    and `world_state.publish` would refuse the world.
    """
    for step in replay["chain_a"]["steps"][1:]:
        default = step["arms"]["legacy_default"]["equivalence"]
        assert default["stale_left_behind"] == ["collection:directory"], step["step"]
        assert default["equivalent"] is False, step["step"]

        precise = step["arms"]["legacy_precise"]["equivalence"]
        assert precise["equivalent"] is True, step["step"]
        assert precise["stale_left_behind"] == [], step["step"]


def test_every_chain_a_world_activates_and_only_one_is_active(
    replay: dict[str, Any],
) -> None:
    chain = replay["chain_a"]
    assert [s["publish"]["status"] for s in chain["steps"]] == ["ACTIVE"] * 5
    assert chain["activeCount"] == 1
    assert chain["onlyOneActive"] is True


def test_the_registrant_is_one_entity_across_all_five_filings(
    replay: dict[str, Any],
) -> None:
    """Stable identity across sources, on an identifier rather than a name.

    The only mention considered is a region printing "Apple Inc." exactly, and
    the only identifier is the CIK the filing declares. Four of the five merge
    at `SYSTEM_OF_RECORD`; the first is `NEW_ENTITY` because nothing preceded it.
    Nothing needs review, and nothing was inferred by a model.
    """
    steps = replay["chain_a"]["steps"]
    for step in steps:
        assert step["entities"]["entities"] == ["entity:registrant:0000320193"]
        assert step["entities"]["needsReview"] == []
        assert step["entities"]["verdicts"]["NEW_ENTITY"] == 1
    assert steps[-1]["entities"]["verdicts"]["AUTO_MERGE"] == 4
    for decision in steps[-1]["entities"]["decisions"][1:]:
        assert decision["tier"] == "SYSTEM_OF_RECORD"


def test_a_partial_world_and_an_unchecked_selective_build_are_both_refused(
    replay: dict[str, Any],
) -> None:
    controls = replay["chain_a"]["steps"][-1]["failClosedControls"]
    partial = controls["partialWorldRefused"]
    assert "REFUSAL_DID_NOT_HAPPEN" not in partial
    assert partial["activeCount"] == 0
    unchecked = controls["selectiveWithoutEquivalenceRefused"]
    assert "REFUSAL_DID_NOT_HAPPEN" not in unchecked
    assert unchecked["activeCount"] == 0


def test_unresolved_identity_stays_unresolved(replay: dict[str, Any]) -> None:
    """An identity the resolver could not settle never becomes a silent rebuild.

    Chain B's revision steps carry unsettled identities. Their consumers are
    rebuilt and *labelled* UNRESOLVED rather than STALE, which is the
    distinction that makes them reviewable.
    """
    steps = replay["chain_b"]["steps"]
    assert steps[1]["change"]["unresolvedIdentities"] == 6
    assert steps[2]["change"]["unresolvedIdentities"] == 4
    for step in steps[1:]:
        arm = step["arms"]["legacy_precise"]
        assert arm["states"].get("unresolved", 0) > 0, step["step"]
        assert len(arm["unresolvedArtifacts"]) == arm["states"]["unresolved"]


def test_chain_b_refuses_the_world_the_oracle_cannot_clear(
    replay: dict[str, Any],
) -> None:
    """A `claim:` artifact whose evidence moved is carried over stale.

    The claim projection declares itself sensitive to the semantic channel only,
    while its body embeds the unit's provenance (page and bbox). When Note 1's
    text is unchanged and its page moves 10 -> 11, the plan carries the claim
    forward and a full rebuild disagrees. The publish is refused rather than
    activating a world with a wrong-page citation in it.
    """
    r2 = replay["chain_b"]["steps"][2]
    stale = r2["arms"]["legacy_precise"]["equivalence"]["stale_left_behind"]
    assert len(stale) == 1
    assert stale[0].startswith("claim:")
    assert r2["publish"]["status"] == "REFUSED"
    assert r2["publish"]["activeCount"] == 1  # the previous world is still the ACTIVE one


def test_the_challenger_is_not_better_than_the_branch_core(
    replay: dict[str, Any],
) -> None:
    """PR #46, measured in shadow. Nothing here promotes it.

    On the revision step it leaves the `retrieval:` artifact stale as well,
    because it drops the locator facet channel the protected core already
    routes. On the step before it, it rebuilds every artifact where the core
    rebuilds all but one.
    """
    steps = replay["chain_b"]["steps"]
    r1, r2 = steps[1], steps[2]
    assert r1["arms"]["challenger"]["rebuildFraction"] == 1.0
    assert r1["arms"]["legacy_precise"]["rebuildFraction"] == 0.974359

    challenger_stale = r2["arms"]["challenger"]["equivalence"]["stale_left_behind"]
    legacy_stale = r2["arms"]["legacy_precise"]["equivalence"]["stale_left_behind"]
    assert len(challenger_stale) == 2
    assert len(legacy_stale) == 1
    assert set(legacy_stale) < set(challenger_stale)


def test_the_stock_core_canonicaliser_grounds_almost_nothing_in_an_sec_filing(
    replay: dict[str, Any],
) -> None:
    """The Core, unmodified, on 290 pages of SEC filings: one unit.

    `canonicalise_document` recognises one unit shape, a numbered contract
    clause. An SEC filing prints `Item 1A.` and `Note 3 -`, so 14,212 of its
    paragraphs resolve to `UNRESOLVED_SOURCE_FACT` and coverage is 6 per mille.
    It does not crash and it does not pretend: `sourceFaithful` is False, which
    is what forbids a source-faithful CURRENT downstream.
    """
    stock = _load(replay["out"] / "steps" / "stock-core-arm.json")
    assert stock["outcome"] == "RESOLVED"
    assert stock["units"] == 1
    assert stock["facts"]["coveragePermille"] == 6
    assert stock["facts"]["sourceFaithful"] is False
    assert stock["facts"]["failClosedByKind"]["UNNUMBERED_PARAGRAPH"] == 14212


def test_no_stage_is_silently_skipped(replay: dict[str, Any]) -> None:
    """Every §26 stage carries a disposition and a reason."""
    stages = replay["manifest"]["stages"]
    assert len(stages) == 26
    for stage in stages:
        assert stage["disposition"] in {"RUN", "PARTIAL", "NOT_RUN"}
        assert stage["note"], stage["stage"]
