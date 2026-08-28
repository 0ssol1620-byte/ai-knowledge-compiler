"""Controls for the mutation engine.

The engine's job is to notice when a component's tests have stopped defending
it. So the controls here are mostly about the engine's ability to say no: a
survivor reported as a survivor, a red baseline refused rather than scored, an
emptied selection caught, a stale table entry counted against the score instead
of skipped.

The tables themselves are checked structurally -- every one names a component
the freeze binds, and every mutation is a real three-part edit -- but their
contents are only proved by running them, which `sfir9_mutation.py` does and
`receipts/sfir9-mutation-baselines.json` records.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import sfir9_execution_closure as closure  # noqa: E402
import sfir9_mutation as engine  # noqa: E402

RECEIPT = NS / "receipts/sfir9-mutation-baselines.json"


@pytest.fixture
def sandbox(tmp_path):
    """A component and a test that actually checks it."""
    (tmp_path / "tools").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "tools/widget.py").write_text("LIMIT = 60\n", encoding="utf-8")
    (tmp_path / "tests/test_widget.py").write_text(
        "import sys\n"
        "from pathlib import Path\n"
        "sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))\n"
        "import widget\n"
        "def test_limit():\n"
        "    assert widget.LIMIT == 60\n",
        encoding="utf-8",
    )
    return tmp_path


def table(**overrides):
    body = {
        "component": "widget",
        "target": "tools/widget.py",
        "tests": ("tests/test_widget.py",),
        "mutations": (("W1 the limit moves", "LIMIT = 60", "LIMIT = 61"),),
    }
    body.update(overrides)
    return engine.Table(**body)


def _run(table_, root):
    return engine.run_component(table_, python=sys.executable, root=root, timeout=120)


def _assert_killed(result, expected):
    """Assert on the outcome, and say which one it was when it is not that.

    These controls shell out to pytest, so a loaded machine can turn a kill into
    a HUNG. That is not a defect in the engine, but a bare count mismatch does
    not say so -- and a control whose failure is unreadable gets explained away
    rather than looked at.
    """
    outcomes = [row["outcome"] for row in result.get("survivors", [])]
    assert result["mutations_killed"] == expected, (
        f"state={result['state']} killed={result['mutations_killed']} "
        f"survivor outcomes={outcomes}"
    )


# ------------------------------------------------------ the engine can say no


def test_a_killed_mutation_is_recorded_as_killed(sandbox):
    result = _run(table(), sandbox)
    assert result["state"] == "RUN"
    _assert_killed(result, 1)
    assert result["survivors"] == []


def test_a_surviving_mutation_is_reported(sandbox):
    """A mutation the tests do not notice. Without this the score is decoration."""
    result = _run(
        table(mutations=(("W2 an untested comment", "LIMIT = 60", "LIMIT = 60  # x"),)),
        sandbox,
    )
    assert result["mutations_killed"] == 0
    assert [row["mutation"] for row in result["survivors"]] == ["W2 an untested comment"]
    assert result["survivors"][0]["outcome"] == engine.SURVIVED


def test_a_stale_table_entry_counts_against_the_score(sandbox):
    """Not a skip. An anchor that no longer matches has stopped testing anything,
    and skipping it would let a component drift out from under its own table."""
    result = _run(
        table(mutations=(("W3 a stale anchor", "TEXT_THAT_IS_NOT_THERE", "x"),)), sandbox
    )
    assert result["mutations_killed"] == 0
    assert result["survivors"][0]["outcome"] == engine.ANCHOR_MISSING


def test_a_red_baseline_is_refused_rather_than_scored(sandbox):
    """Every mutation would look killed and the score would be a perfect 100%."""
    (sandbox / "tools/widget.py").write_text("LIMIT = 99\n", encoding="utf-8")
    result = _run(table(), sandbox)
    assert result["state"] == engine.BASELINE_RED
    assert result["mutations_killed"] == 0
    assert "meaningless" in result["why_not_run"]


def test_an_empty_selection_is_refused_rather_than_scored(sandbox):
    """An exclusion that removed every test would also have looked green."""
    result = _run(table(tests=("tests/test_widget.py", "-k", "nothing_matches")), sandbox)
    assert result["state"] == engine.EMPTY_BASELINE
    assert result["baseline_tests_selected"] == 0
    assert result["mutations_killed"] == 0


def test_the_component_is_restored_after_every_mutation(sandbox):
    before = (sandbox / "tools/widget.py").read_bytes()
    _run(table(), sandbox)
    assert (sandbox / "tools/widget.py").read_bytes() == before


def test_the_component_is_restored_even_when_the_run_hangs(sandbox, monkeypatch):
    """The `finally` is what stops a timeout from leaving a mutated tree behind."""

    def hang(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd="pytest", timeout=1)

    before = (sandbox / "tools/widget.py").read_bytes()
    baseline = engine._pytest
    calls = {"n": 0}

    def flaky(*args, **kwargs):
        calls["n"] += 1
        return baseline(*args, **kwargs) if calls["n"] == 1 else hang()

    monkeypatch.setattr(engine, "_pytest", flaky)
    result = _run(table(), sandbox)
    assert result["survivors"][0]["outcome"] == engine.HUNG
    assert (sandbox / "tools/widget.py").read_bytes() == before


# ------------------------------------------------------------------ the report


def test_the_report_does_not_pass_with_a_survivor():
    results = [
        {
            "component": "a",
            "state": "RUN",
            "mutations_declared": 2,
            "mutations_killed": 1,
            "survivors": [{"mutation": "x", "outcome": engine.SURVIVED}],
        }
    ]
    report = engine.baselines(results)
    assert report["all_baselines_green"] is False
    assert report["components_with_no_survivor"] == 0


def test_the_report_does_not_pass_with_a_red_baseline():
    results = [
        {
            "component": "a",
            "state": engine.BASELINE_RED,
            "mutations_declared": 3,
            "mutations_killed": 0,
            "survivors": [],
        }
    ]
    assert engine.baselines(results)["all_baselines_green"] is False


def test_the_report_passes_only_when_every_mutation_was_killed():
    results = [
        {
            "component": "a",
            "state": "RUN",
            "mutations_declared": 2,
            "mutations_killed": 2,
            "survivors": [],
        }
    ]
    report = engine.baselines(results)
    assert report["all_baselines_green"] is True
    assert report["mutations_declared"] == report["mutations_killed"] == 2


def test_the_digest_moves_with_the_results():
    one = engine.baselines(
        [{"component": "a", "state": "RUN", "mutations_declared": 1,
          "mutations_killed": 1, "survivors": []}]
    )
    two = engine.baselines(
        [{"component": "a", "state": "RUN", "mutations_declared": 1,
          "mutations_killed": 0,
          "survivors": [{"mutation": "x", "outcome": engine.SURVIVED}]}]
    )
    assert one["baselines_digest"] != two["baselines_digest"]


# ------------------------------------------------------------------ the tables


def test_every_component_the_freeze_binds_has_a_table():
    """Nine of the ten, plus the audit and the taxonomy that gate the freeze.

    The tenth -- the isolation gate -- is the `gate` table; the closure is
    `closure`. What must not happen is a bound component with no table at all.
    """
    targets = {engine.load(name).target for name in engine.COMPONENTS}
    for component in closure.COMPONENTS:
        assert component.relative_path.endswith(
            tuple(targets)
        ), f"{component.name} has no mutation table"


def test_every_table_names_a_file_that_exists():
    for name in engine.COMPONENTS:
        assert (NS / engine.load(name).target).is_file(), name


def test_every_mutation_is_a_real_three_part_edit():
    for name in engine.COMPONENTS:
        loaded = engine.load(name)
        labels = [label for label, _, _ in loaded.mutations]
        assert len(set(labels)) == len(labels), f"{name} has a duplicate label"
        for label, old, new in loaded.mutations:
            assert label.strip(), name
            assert old.strip(), label
            assert old != new, label


def test_every_mutation_anchor_is_present_in_its_component():
    """A table drifting out of sync with its component, caught without running."""
    stale = []
    for name in engine.COMPONENTS:
        loaded = engine.load(name)
        text = (NS / loaded.target).read_text(encoding="utf-8")
        stale += [
            f"{name}: {label}" for label, old, _ in loaded.mutations if old not in text
        ]
    assert stale == []


def test_the_tables_cover_every_component_in_the_declared_order():
    assert len(engine.COMPONENTS) == len(set(engine.COMPONENTS))
    assert engine.COMPONENTS[0] == "protocol"
    assert set(engine.tables()) == set(engine.tables())


# ------------------------------------------------------ the receipt on disk


@pytest.mark.skipif(not RECEIPT.exists(), reason="the baselines have not been run")
def test_the_recorded_baselines_are_green():
    report = json.loads(RECEIPT.read_text(encoding="utf-8"))
    assert report["schema"] == engine.SCHEMA
    assert report["all_baselines_green"] is True
    assert report["mutations_declared"] == report["mutations_killed"]


@pytest.mark.skipif(not RECEIPT.exists(), reason="the baselines have not been run")
def test_the_recorded_baselines_actually_ran_something():
    """A run over zero components would meet every other assertion here."""
    report = json.loads(RECEIPT.read_text(encoding="utf-8"))
    assert report["components_run"] == len(engine.COMPONENTS)
    assert report["mutations_declared"] > 0
    for result in report["results"]:
        assert result["state"] == "RUN"
        assert result["baseline_tests_selected"] > 0


def test_an_empty_selection_is_not_mistaken_for_a_failing_suite(sandbox):
    """pytest exits 5 on "no tests collected", which is non-zero.

    Checked before the red-baseline branch, or an exclusion that removed every
    test would be reported as a suite that failed rather than one that never ran.
    """
    result = _run(table(tests=("tests/test_widget.py", "-k", "nothing_matches")), sandbox)
    assert result["state"] == engine.EMPTY_BASELINE
    assert result["state"] != engine.BASELINE_RED


def test_a_genuinely_failing_suite_is_still_reported_as_red(sandbox):
    """So the previous test cannot pass by turning every refusal into EMPTY."""
    (sandbox / "tools/widget.py").write_text("LIMIT = 99\n", encoding="utf-8")
    assert _run(table(), sandbox)["state"] == engine.BASELINE_RED
