"""INC-V2-100: a live-cohort entry point must refuse a test runner.

The anti-blocker audit reported three tools as `real-cohort access reachable
from pytest`, each exposing a `run()` that reaches real roots. The failure being
prevented is not a crash: a stray traversal SUCCEEDS. It walks the real roots,
spends real request budget, and observes -- and this study's method rests on
doing that exactly once, under a frozen protocol, with the result recorded.

These controls are paired throughout. It is trivial to write a guard that
refuses everything and a test that proves it refuses; what has to be shown is
that it refuses under a runner AND permits when deliberately allowed, so the
guard is a gate rather than a wall.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import live_cohort_guard as guard  # noqa: E402

GUARDED = (
    "preflight_sfi3_roots",
    "gpu_successor_preflight",
    "v2r4_preacquisition_gate",
)

#: Which entry point each tool actually guards.
#:
#: INC-V2-104 B moved `gpu_successor_preflight`'s guard off `run()` -- which
#: opens no socket, imports no HTTP client and writes nothing -- and onto
#: `main()`, which seals an immutable receipt and moves a `receipts/latest`
#: pointer. The two parametrised controls below were left naming `run()` and
#: so were RED for every input from that moment on. A control that cannot go
#: green is as empty as one that cannot go red: it stops distinguishing
#: anything, which is the INC-V2-036 class wearing its other face. They now
#: name the entry point each tool guards, and `test_run_is_deliberately_not
#: _guarded_here` below pins the other half of that repair so the guard
#: cannot drift back onto `run()` unnoticed.
GUARDED_ENTRY = {
    "preflight_sfi3_roots": "run",
    "gpu_successor_preflight": "main",
    "v2r4_preacquisition_gate": "run",
}


def test_the_runner_is_detected_at_all():
    """The precondition every other control here depends on. If this is false,
    each refusal below would pass for the wrong reason -- because nothing was
    detected rather than because the guard worked."""
    assert guard.under_test() is True
    assert "pytest" in sys.modules


def test_refuse_raises_under_a_runner():
    with pytest.raises(guard.LiveCohortRefused, match="live cohort"):
        guard.refuse_under_test("some_tool.run")


def test_refuse_names_the_entry_point_it_stopped():
    """A refusal that does not say what it stopped sends whoever hits it
    hunting through three modules with identical guards."""
    with pytest.raises(guard.LiveCohortRefused, match=r"some_tool\.run"):
        guard.refuse_under_test("some_tool.run")


def test_allow_under_test_permits_and_then_restores():
    """The paired positive. Without this the suite could not tell a working
    guard from one that refuses unconditionally and forever."""
    with guard.allow_under_test():
        guard.refuse_under_test("some_tool.run")  # must not raise
    with pytest.raises(guard.LiveCohortRefused):
        guard.refuse_under_test("some_tool.run")


def test_allow_under_test_restores_even_when_the_block_raises():
    with pytest.raises(ValueError):
        with guard.allow_under_test():
            raise ValueError("boom")
    with pytest.raises(guard.LiveCohortRefused):
        guard.refuse_under_test("some_tool.run")


#: `gpu_successor_preflight.run` takes required keyword arguments, and Python
#: binds arguments before the body runs -- so a bare call raises TypeError
#: before reaching the guard. Placeholders are supplied so the control reaches
#: the refusal rather than passing on an argument error, which would be a green
#: test proving nothing. They are never used: the guard raises first, which is
#: exactly the property under test.
ENTRY_KWARGS: dict[str, dict[str, object]] = {}


@pytest.mark.parametrize("module_name", GUARDED)
def test_each_named_tool_refuses_its_guarded_entry_under_pytest(module_name):
    """The real entry points, called for real. This is the control that would
    have caught the original defect: before the guard, each of these calls
    started a live traversal from inside the test suite."""
    module = __import__(module_name)
    entry = getattr(module, GUARDED_ENTRY[module_name])
    with pytest.raises(guard.LiveCohortRefused, match=module_name):
        entry(**ENTRY_KWARGS.get(module_name, {}))


@pytest.mark.parametrize("module_name", GUARDED)
def test_the_refusal_is_the_first_thing_the_guarded_entry_does(module_name):
    """A guard placed after the first request has already spent the budget it
    exists to protect. Asserted on the source rather than by observing traffic,
    because observing traffic here would be the very thing being prevented."""
    source = (NS / "tools" / f"{module_name}.py").read_text(encoding="utf-8")
    index = source.index(f"def {GUARDED_ENTRY[module_name]}(")
    body = source[index : index + 2000]
    guard_at = body.index('if "pytest" in sys.modules')
    for spender in ("urlopen(", "requests.", "subprocess.run(", "http"):
        position = body.find(spender)
        if position != -1:
            assert guard_at < position, f"{module_name}: {spender!r} precedes the refusal"


def test_run_is_deliberately_not_guarded_in_the_gpu_successor_preflight():
    """The other half of INC-V2-104 B, pinned so it cannot silently revert.

    `gpu_successor_preflight.run()` reads local files and returns a dict. A
    guard there protected nothing and made the whole gate-assembly block
    unreachable from any test, which is how a gate true for every input
    survived review. This control fails if the refusal moves back onto
    `run()`: it calls `run()` under the runner and requires it to return.
    """
    import gpu_successor_preflight as gsp

    body = gsp.run(
        manifest=Path("no-such-manifest-anywhere.json"),
        model_pin={},
        runtime_image_digest="repo/image@sha256:" + "0" * 64,
    )
    assert body["verdict"] == "BLOCKED"
    assert body["gpu_seconds"] == 0


@pytest.mark.parametrize("module_name", GUARDED)
def test_the_guard_is_visible_to_the_audits_own_detector(module_name):
    """`anti_blocker_audit` finds this guard by looking for `sys.modules` in the
    module text. The check is written inline for that reason: a fix a detector
    cannot see leaves the finding standing, and the right answer is to make the
    fix visible rather than to loosen the detector."""
    source = (NS / "tools" / f"{module_name}.py").read_text(encoding="utf-8")
    assert "sys.modules" in source


def test_the_audit_no_longer_reports_a_reachable_live_cohort():
    """End to end, against the real audit rather than a reimplementation of it."""
    import anti_blocker_audit

    findings = [f for f in anti_blocker_audit.audit()["findings"] if f["severity"] == "FINDING"]
    assert [f["path"] for f in findings if f["defect_class"] == 10] == []
