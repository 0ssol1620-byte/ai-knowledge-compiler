"""The acquisition lanes: fetcher, enumerator, scorer.

Each is an ADAPTER over its V2R2 counterpart, so what has to be proved is not
that the traversal works -- that is the base's subject and the base's tests --
but that the adapter points the shared machinery at V2R3 and hands it back
unchanged. A permanent rebind at import is how eight V2R2 adapter tests went red
in one pytest process (INC-V2-065), and how 21 of 24 V2R2 gate tests silently
asserted things about V2R1 before that (INC-V2-061).

The scorer's own contract is checked by reading its source: it must call the
V2R3 execution gate and never the base one, and it must offer no way to score
part of the cohort. Those are properties of what the file says, and a test that
tried to observe them by running it would need a frozen chain and a real corpus
-- neither of which exists yet, and building either to satisfy a test would be
the thing the test is guarding against.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]
for _root in (
    str(ROOT / "packages" / "cir-python" / "src"),
    str(NS),
    str(NS / "tools"),
    str(NS / "acquisition"),
    str(NS / "canonicalization"),
    str(NS / "compiler"),
):
    if _root not in sys.path:
        sys.path.insert(0, _root)

SCORER = NS / "tools" / "identity_change_migration_closure_v2r3.py"


# ---------------------------------------------------------------------------
# the fetcher
# ---------------------------------------------------------------------------
def test_the_fetcher_points_at_the_v2r3_frame_and_corpus() -> None:
    import fetch_v2r3_corpus as f

    assert f.OUT.name == "v2r3_corpus"
    assert f.frame.PROTOCOL_ID == "IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R3"


def test_importing_the_fetcher_adapter_does_not_disturb_its_base() -> None:
    """Import order must not decide which corpus an acquisition writes into."""
    import fetch_v2r2_corpus as b
    import fetch_v2r3_corpus  # noqa: F401

    assert b.OUT.name == "v2r2_corpus"
    assert b.frame.PROTOCOL_ID == "IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R2"


def test_the_fetch_is_authorised_by_the_rung_0_receipt_and_by_nothing_else(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The frame is sealed BEFORE acquisition, and the fetcher checks that seal.

    Rung 0 is now frozen, so the green direction is what this asserts; the red
    directions are driven below. Before the freeze this test asserted the
    refusal, and leaving it that way after the freeze would have turned a live
    check into one that could only pass while nothing existed.
    """
    import fetch_v2r3_corpus as f

    body = f.require_frozen_frame()
    assert body["protocol_id"] == "IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R3"
    assert body["frame_module_sha256"].startswith("sha256:")
    assert body["sealed_before_acquisition"] is True


def test_the_fetcher_refuses_when_no_rung_0_receipt_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fetch that ran first would make the freeze a record of what was done
    rather than a constraint on what may be done."""
    import fetch_v2r3_corpus as f

    monkeypatch.setattr(f, "FRAME_FREEZE_GLOB", "no-such-receipt--*.json")
    with pytest.raises(f.FrameNotFrozen, match="no rung-0 V2R3 acquisition frame receipt"):
        f.require_frozen_frame()


def test_the_fetcher_refuses_when_the_frame_has_moved_since_the_freeze(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An acquisition authorised by a frame that has since changed is authorised
    by nothing that is still true."""
    import fetch_v2r3_corpus as f

    edited = tmp_path / "sources_v2r3.py"
    edited.write_text(
        f.FRAME_MODULE.read_text(encoding="utf-8") + "\n# an edit after the freeze\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(f, "FRAME_MODULE", edited)
    with pytest.raises(f.FrameNotFrozen, match="changed after it was frozen"):
        f.require_frozen_frame()


def test_the_fetcher_binding_is_restored_after_use() -> None:
    import fetch_v2r2_corpus as b
    import fetch_v2r3_corpus as f

    before = {name: getattr(b, name) for name in f._bindings()}
    with f._bound():
        assert b.OUT.name == "v2r3_corpus"
    assert {name: getattr(b, name) for name in f._bindings()} == before


# ---------------------------------------------------------------------------
# the enumerator
# ---------------------------------------------------------------------------
def test_the_enumerator_excludes_everything_v2r2_did_plus_v2r2_itself() -> None:
    """Not narrower than its predecessor anywhere."""
    import enumerate_v2r2_universe as b
    import enumerate_v2r3_universe as e

    theirs = {entry["id"] for entry in b.excluded_sets()}
    mine = {entry["id"] for entry in e.excluded_sets()}
    assert theirs < mine
    assert mine - theirs == {"v2r2_spent"}


def test_excluded_sets_still_works_inside_the_binding_scope() -> None:
    """The state the wrapper exists to create, which the first version of this
    file never entered.

    `_bound()` rebinds `base.excluded_sets` to the adapter's own function, so an
    adapter that reached for `base.excluded_sets()` called ITSELF. Calling it
    from outside the scope resolved to the base and passed; the first real
    enumeration run died with `RecursionError` after 996 frames.
    """
    import enumerate_v2r3_universe as e

    with e._bound():
        ids = {entry["id"] for entry in e.base.excluded_sets()}
    assert "v2r2_spent" in ids
    assert "v2r1_spent" in ids


def test_the_v2r2_spent_set_is_the_measured_270(monkeypatch: pytest.MonkeyPatch) -> None:
    import enumerate_v2r3_universe as e

    entry = e.v2r2_spent_set()
    assert entry["measured_lineages"] == 270
    assert entry["lineage_count"] >= 270
    assert entry["_ids"], "an empty spent set would subtract nothing"


def test_an_absent_v2r2_universe_receipt_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    """A disjointness proof against an empty set proves nothing."""
    import enumerate_v2r3_universe as e

    monkeypatch.setattr(e, "V2R2_UNIVERSE_GLOB", "no-such-receipt--*.json")
    with pytest.raises(RuntimeError, match="cannot be subtracted"):
        e.v2r2_spent_set()


def test_importing_the_enumerator_adapter_does_not_disturb_its_base() -> None:
    import enumerate_v2r2_universe as b
    import enumerate_v2r3_universe  # noqa: F401

    assert b.CORPUS.name == "v2r2_corpus"
    assert "v2r2_universe_enumeration" in b.SCHEMA


def test_payload_paths_are_repointed_and_a_stray_one_is_refused() -> None:
    """The base writes payload paths from a string literal, not from its CORPUS
    global, so rebinding the corpus does not reach them."""
    import enumerate_v2r3_universe as e

    body = {
        "pairs": [
            {
                "lineage_id": "ecfr:7:1:1.1",
                "before": {
                    "raw_path": f"{e.BASE_REL}/a.raw",
                    "canonical_path": f"{e.BASE_REL}/a.json",
                },
                "after": {
                    "raw_path": f"{e.BASE_REL}/b.raw",
                    "canonical_path": f"{e.BASE_REL}/b.json",
                },
            }
        ]
    }
    out = e._repoint_payload_paths(body)
    assert out["payload_paths_repointed"]["count"] == 4
    assert out["pairs"][0]["before"]["raw_path"] == f"{e.OUR_REL}/a.raw"

    stray = {
        "pairs": [
            {
                "lineage_id": "ecfr:7:1:1.2",
                "before": {"raw_path": "somewhere/else/a.raw"},
                "after": {},
            }
        ]
    }
    with pytest.raises(RuntimeError, match="does not start with"):
        e._repoint_payload_paths(stray)


def test_a_repointing_that_finds_nothing_over_a_non_empty_universe_refuses() -> None:
    """The failure this function actually had. Reading the wrong key made the
    loop run zero times, so the per-path assertion never fired and 300 pairs
    were written still pointing into V2R2's corpus while the tool reported
    success. A guard that iterates an empty collection proves nothing."""
    import enumerate_v2r3_universe as e

    with pytest.raises(RuntimeError, match="not one payload path was"):
        e._repoint_payload_paths({"pairs": [{"lineage_id": "x", "before": {}, "after": {}}]})


def test_the_key_the_repointing_reads_is_the_key_the_enumerator_writes() -> None:
    """Anchored to the REAL artefact, not to what the adapter assumes.

    The bug was a test written from the implementation rather than from the
    output: both used `rows`, both agreed, and the enumerator emits `pairs`.
    """
    import enumerate_v2r3_universe as e

    if not e.OUT.is_file():
        pytest.skip("the V2R3 universe has not been enumerated in this checkout")
    body = json.loads(e.OUT.read_text(encoding="utf-8"))
    assert body.get("pairs")
    assert body["payload_paths_repointed"]["count"] == 4 * len(body["pairs"])
    for row in body["pairs"]:
        for side in ("before", "after"):
            assert row[side]["canonical_path"].startswith(e.OUR_REL + "/")


# ---------------------------------------------------------------------------
# the scorer's contract, read from its source
# ---------------------------------------------------------------------------
def _calls(path: Path) -> set[str]:
    """Every dotted name this file calls, at any depth."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.Call):
            continue
        target = node.func
        parts: list[str] = []
        while isinstance(target, ast.Attribute):
            parts.append(target.attr)
            target = target.value
        if isinstance(target, ast.Name):
            parts.append(target.id)
            names.add(".".join(reversed(parts)))
    return names


def test_the_scorer_calls_the_v2r3_gate() -> None:
    called = _calls(SCORER)
    assert "fz.require_v2r3_execution_preconditions" in called


def test_the_scorer_never_calls_the_base_gate() -> None:
    """The base gate knows nothing about the three companion attestations, so
    calling it would report READY on a chain that never bound them."""
    called = _calls(SCORER)
    assert "base_fz.require_execution_preconditions" not in called
    assert "fz.base.require_execution_preconditions" not in called
    assert not any(
        name.endswith(".require_execution_preconditions") for name in called
    ), sorted(n for n in called if "precondition" in n)


def test_the_scorer_offers_no_way_to_score_part_of_the_cohort() -> None:
    """A limited run reads real outcomes from part of the cohort and is a
    PREVIEW, whatever it does with the result afterwards."""
    #: Read from the argument parser, not from the file's text: the docstring
    #: explains at length why there is no `--limit`, and a substring search would
    #: be satisfied by that explanation being deleted.
    flags: set[str] = set()
    for node in ast.walk(ast.parse(SCORER.read_text(encoding="utf-8"))):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_argument"
        ):
            flags.update(a.value for a in node.args if isinstance(a, ast.Constant))
    assert flags == {"--write-receipt"}, flags

    #: And `run` takes no parameter that could stand in for one.
    run = next(
        node
        for node in ast.walk(ast.parse(SCORER.read_text(encoding="utf-8")))
        if isinstance(node, ast.FunctionDef) and node.name == "run"
    )
    assert not run.args.args and not run.args.kwonlyargs


def test_the_scorer_refuses_a_second_measurement() -> None:
    source = SCORER.read_text(encoding="utf-8")
    assert "EXACTLY ONCE" in source
    assert 'glob(f"{STEM}--*.json")' in source


def test_no_test_in_this_suite_executes_the_closure() -> None:
    """The closure runs EXACTLY ONCE, and a test run is a run.

    This file previously asserted the scorer refuses while the chain is
    unfrozen, by calling `run()`. That was honest while nothing was frozen. The
    moment rungs 0-5 existed the same line stopped being a refusal test and
    became an EXECUTION: it diffed all 300 pairs before dying on an unrelated
    KeyError. No receipt was written and no outcome was reported -- the protocol
    predeclares that a run raising before grading is not a score -- but the test
    had turned into the thing it was written to guard.

    A refusal test whose subject becomes reachable is not a refusal test any
    more. So the property is enforced structurally instead: nothing under
    `tests/` may call the scorer's `run` or `main`.
    """
    offenders: list[str] = []
    for path in sorted((NS / "tests").glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        aliases = {
            alias.asname or alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
            if alias.name == "identity_change_migration_closure_v2r3"
        }
        if not aliases:
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"run", "main"}
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in aliases
            ):
                offenders.append(f"{path.name}:{node.lineno} calls {node.func.attr}()")
    assert offenders == [], offenders


def test_the_census_keys_the_scorer_aggregates_are_the_ones_the_surface_reports() -> None:
    """The KeyError that turned a refusal test into an execution.

    The scorer restated the surface's key names and got two of them wrong, so
    the mismatch surfaced only after 300 pairs had been diffed. Checked here
    against a SYNTHETIC surface, which costs nothing and needs no corpus.
    """
    import identity_change_migration_closure_v2r3 as scorer
    import v2r3_effective_identity as eff

    surface = eff.build_effective_surface([], [], "src:test")
    produced = set(surface.as_dict())

    aggregated: set[str] = set()
    for node in ast.walk(ast.parse(SCORER.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            if node.targets[0].id in {"scalar_keys", "map_keys"}:
                aggregated.update(
                    el.value for el in node.value.elts if isinstance(el, ast.Constant)
                )
    assert aggregated, "the scorer no longer declares its census keys as literals"
    assert aggregated <= produced, sorted(aggregated - produced)

    #: And the guard fires rather than the aggregation dying mid-run.
    with pytest.raises(scorer.ClosureRefused, match="does not report"):
        scorer._require_census_keys(
            [{"census": {"matched_pairs": 0}}], ("matched_pairs", "no_such_key")
        )
