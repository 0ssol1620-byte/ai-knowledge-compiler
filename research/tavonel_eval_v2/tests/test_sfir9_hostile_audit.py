"""Controls for the hostile audit.

An audit that cannot report a failure is a formality. So the first thing checked
here is that each of its four outcomes is reachable: a real refusal, an attack
that got through, an attack refused for the wrong reason, and an attack whose
control never worked. The last is the one that matters most -- a broken fixture
produces the same silence as a successful defence, and without the control it
would read as one.

The audit is then run in full against the real components, which is the freeze
precondition.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import sfir9_hostile_audit as audit_module  # noqa: E402

# ------------------------------------------------ the four outcomes are reachable


def _attack(**overrides):
    body = dict(
        name="synthetic",
        what_it_tries="nothing real",
        expected_code="EXPECTED",
        control=lambda _sandbox: None,
        attack=lambda _sandbox: (_ for _ in ()).throw(
            audit_module.gate.IsolationRefused("EXPECTED happened")
        ),
        refusals=(audit_module.gate.IsolationRefused,),
    )
    body.update(overrides)
    return audit_module.Attack(**body)


def test_a_properly_refused_attack_is_refused(tmp_path):
    result = audit_module.run_attack(_attack(), tmp_path)
    assert result["outcome"] == audit_module.REFUSED


def test_an_attack_that_gets_through_is_reported(tmp_path):
    result = audit_module.run_attack(
        _attack(attack=lambda _sandbox: "no refusal at all"), tmp_path
    )
    assert result["outcome"] == audit_module.NOT_REFUSED


def test_an_attack_refused_for_the_wrong_reason_is_reported(tmp_path):
    """A refusal for the wrong reason stops firing when that reason goes away."""
    result = audit_module.run_attack(
        _attack(
            attack=lambda _sandbox: (_ for _ in ()).throw(
                audit_module.gate.IsolationRefused("something else entirely")
            )
        ),
        tmp_path,
    )
    assert result["outcome"] == audit_module.WRONG_CODE


def test_an_attack_whose_control_failed_is_not_a_pass(tmp_path):
    """The one that would otherwise read as a defence.

    A fixture that errored, a path that did not exist, an import that failed --
    each produces the same silence as a refusal.
    """
    result = audit_module.run_attack(
        _attack(control=lambda _sandbox: (_ for _ in ()).throw(RuntimeError("broken"))),
        tmp_path,
    )
    assert result["outcome"] == audit_module.CONTROL_FAILED
    assert "would not be evidence" in result["why_this_is_not_a_pass"]


def test_an_unexpected_exception_type_is_not_a_refusal(tmp_path):
    result = audit_module.run_attack(
        _attack(attack=lambda _sandbox: (_ for _ in ()).throw(KeyError("oops"))),
        tmp_path,
    )
    assert result["outcome"] == audit_module.WRONG_CODE


def test_the_audit_fails_when_any_attack_does(tmp_path, monkeypatch):
    """The audit must be able to say no."""
    monkeypatch.setattr(
        audit_module,
        "ATTACKS",
        (_attack(), _attack(name="gets_through", attack=lambda _s: "through")),
    )
    report = audit_module.audit(tmp_path)
    assert report["audit_passes"] is False
    assert report["attacks_refused"] == 1


def test_the_audit_passes_only_when_every_attack_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(audit_module, "ATTACKS", (_attack(), _attack(name="two")))
    assert audit_module.audit(tmp_path)["audit_passes"] is True


# --------------------------------------------------------- the thirteen attacks


def test_the_audit_names_the_thirteen_attacks_the_ruling_lists():
    assert len(audit_module.ATTACKS) == 13
    assert {attack.name for attack in audit_module.ATTACKS} == {
        "selection_rule_omitted_from_closure",
        "isolation_gate_omitted_from_closure",
        "scorer_substituted_after_roster_seal",
        "transport_substituted_after_roster_seal",
        "upstream_sfir8_module_mutated",
        "committed_blob_differs_from_working_bytes",
        "import_resolves_from_a_shared_dirty_tree",
        "segment_under_a_different_selection_digest",
        "roster_generated_before_the_protocol_freeze",
        "spent_sfir7_root_appears_in_the_cohort",
        "drifted_historical_receipt_as_a_scientific_prerequisite",
        "authority_selected_by_recency_or_shape",
        "checkpoint_chain_from_another_roster",
    }


def test_every_attack_declares_the_code_it_expects():
    for attack in audit_module.ATTACKS:
        assert attack.expected_code
        assert attack.what_it_tries


@pytest.mark.parametrize("attack", audit_module.ATTACKS, ids=lambda a: a.name)
def test_every_attacks_control_succeeds(attack, tmp_path):
    """Run on its own so a control failure is attributed to its own attack."""
    sandbox = tmp_path / "control"
    sandbox.mkdir()
    attack.control(sandbox)


@pytest.mark.parametrize("attack", audit_module.ATTACKS, ids=lambda a: a.name)
def test_every_attack_is_refused_with_the_code_it_expects(attack, tmp_path):
    result = audit_module.run_attack(attack, tmp_path)
    assert result["outcome"] == audit_module.REFUSED, result


def test_the_full_audit_passes_against_the_real_components(tmp_path):
    """The freeze precondition."""
    report = audit_module.audit(tmp_path)
    assert report["attacks_mounted"] == 13
    assert report["attacks_refused"] == 13
    assert report["audit_passes"] is True
    assert report["audit_digest"].startswith("sha256:")


def test_the_report_records_why_a_control_failure_is_not_a_pass(tmp_path):
    report = audit_module.audit(tmp_path)
    assert "would read as a defence" in report["why_a_control_failure_is_not_a_pass"]
    assert "wrong reason" in report["why_the_code_is_asserted"]


def test_the_control_failure_count_is_measured_rather_than_asserted(
    tmp_path, monkeypatch
):
    """It read `True` before, which no broken control could have contradicted."""
    monkeypatch.setattr(audit_module, "ATTACKS", (_attack(),))
    assert audit_module.audit(tmp_path / "clean")["attacks_whose_control_failed"] == 0
    monkeypatch.setattr(
        audit_module,
        "ATTACKS",
        (
            _attack(),
            _attack(
                name="broken",
                control=lambda _s: (_ for _ in ()).throw(RuntimeError("broken")),
            ),
        ),
    )
    report = audit_module.audit(tmp_path / "broken")
    assert report["attacks_whose_control_failed"] == 1
    assert report["audit_passes"] is False


def test_the_audit_digest_moves_with_its_results(tmp_path, monkeypatch):
    first = audit_module.audit(tmp_path / "a")
    monkeypatch.setattr(audit_module, "ATTACKS", audit_module.ATTACKS[:2])
    second = audit_module.audit(tmp_path / "b")
    assert first["audit_digest"] != second["audit_digest"]


def test_the_audit_implements_none_of_the_rules_it_checks():
    """Every refusal comes from a component, not from the auditor.

    An audit carrying its own copy of the rules would be testing its copy.
    """
    source = (NS / "tools/sfir9_hostile_audit.py").read_text(encoding="utf-8")
    assert "class ClosureRefused" not in source
    assert "class IsolationRefused" not in source
    assert "class RosterRefused" not in source
    for attack in audit_module.ATTACKS:
        assert attack.refusals, f"{attack.name} names no refusal type"


# ----------------------------------------- what the audit's own report must carry
#
# Every control below was added because a mutation of the auditor survived: the
# audit still said PASS while its reporting had been weakened.


class _Coded(Exception):
    """A refusal whose code lives on the attribute, not in the message."""

    def __init__(self, code):
        super().__init__("refused, for reasons not stated in this text")
        self.code = code


def test_a_wrong_reason_refusal_is_not_counted_as_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(
        audit_module,
        "ATTACKS",
        (
            _attack(),
            _attack(
                name="wrong_reason",
                attack=lambda _s: (_ for _ in ()).throw(
                    audit_module.gate.IsolationRefused("something else entirely")
                ),
            ),
        ),
    )
    report = audit_module.audit(tmp_path)
    assert report["attacks_refused"] == 1
    assert report["audit_passes"] is False


def test_the_expected_code_may_be_carried_on_the_attribute_alone(tmp_path):
    """A component that sets `.code` and writes a human message is still matched."""
    result = audit_module.run_attack(
        _attack(
            attack=lambda _s: (_ for _ in ()).throw(_Coded("EXPECTED")),
            refusals=(_Coded,),
        ),
        tmp_path,
    )
    assert result["outcome"] == audit_module.REFUSED
    assert result["observed_code"] == "EXPECTED"


def test_a_refusal_type_the_attack_did_not_name_is_not_a_refusal(tmp_path):
    """Even when its message carries the expected code.

    Widening the catch to `Exception` would let an unrelated failure -- a typo,
    a missing file -- read as the defence firing.
    """

    class Unrelated(Exception):
        pass

    result = audit_module.run_attack(
        _attack(
            attack=lambda _s: (_ for _ in ()).throw(Unrelated("EXPECTED happened")),
            refusals=(audit_module.gate.IsolationRefused,),
        ),
        tmp_path,
    )
    assert result["outcome"] == audit_module.WRONG_CODE


def test_the_control_and_the_attack_run_in_separate_sandboxes(tmp_path):
    """A shared directory would let the control's setup mount the attack."""
    seen = []
    audit_module.run_attack(
        _attack(
            control=lambda sandbox: seen.append(("control", sandbox)),
            attack=lambda sandbox: seen.append(("attack", sandbox))
            or (_ for _ in ()).throw(
                audit_module.gate.IsolationRefused("EXPECTED happened")
            ),
        ),
        tmp_path,
    )
    assert len(seen) == 2
    assert seen[0][1] != seen[1][1]


def test_every_attack_is_required_to_name_the_refusals_it_accepts():
    """No default. `Exception` as a fallback would accept any failure at all."""
    import dataclasses

    refusals = {f.name: f for f in dataclasses.fields(audit_module.Attack)}["refusals"]
    assert refusals.default is dataclasses.MISSING
    assert refusals.default_factory is dataclasses.MISSING


def test_the_blob_attack_keeps_the_file_length_it_started_with(tmp_path):
    """Otherwise a size comparison would catch it and the attack proves less."""
    sandbox = tmp_path / "blob"
    sandbox.mkdir()
    with pytest.raises(audit_module.closure_module.ClosureRefused):
        audit_module._blob_attack(sandbox)
    target = f"{audit_module.closure_module.TOOLS}/sfir9_protocol.py"
    planted = (sandbox / target).read_bytes()
    committed = (audit_module.REPO / target).read_bytes()
    assert planted != committed
    assert len(planted) == len(committed)


def test_the_receipt_carries_one_result_per_attack(tmp_path):
    report = audit_module.audit(tmp_path)
    assert [r["attack"] for r in report["results"]] == [
        a.name for a in audit_module.ATTACKS
    ]


def test_the_mounted_count_is_measured_rather_than_asserted(tmp_path, monkeypatch):
    monkeypatch.setattr(audit_module, "ATTACKS", (_attack(), _attack(name="two")))
    assert audit_module.audit(tmp_path)["attacks_mounted"] == 2


def test_the_exit_code_follows_the_verdict(tmp_path, monkeypatch):
    """A green exit on a failed audit is how a weakened instrument gets frozen."""
    monkeypatch.setattr(audit_module, "OUTPUT", tmp_path / "receipt.json")
    monkeypatch.setattr(audit_module, "REPO", tmp_path)
    monkeypatch.setattr(audit_module, "ATTACKS", (_attack(),))
    assert audit_module.main() == 0
    monkeypatch.setattr(
        audit_module,
        "ATTACKS",
        (_attack(), _attack(name="gets_through", attack=lambda _s: "through")),
    )
    assert audit_module.main() == 1
