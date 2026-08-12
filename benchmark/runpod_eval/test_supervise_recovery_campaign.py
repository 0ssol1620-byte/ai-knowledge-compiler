from __future__ import annotations

from supervise_recovery_campaign import (
    SupervisionBudget,
    SupervisionJournal,
    WorkerObservation,
    build_receipt,
    classify,
    plan_supervision,
    supervise,
)


def _worker(
    worker_id="w1",
    provider_status="RUNNING",
    reachable=True,
    done=10,
    expected=100,
    procs=7,
) -> WorkerObservation:
    return WorkerObservation(worker_id, provider_status, reachable, done, expected, procs)


def test_a_working_pod_is_serving() -> None:
    assert _worker().serving is True
    assert _worker().diagnose() is None


def test_an_unreachable_pod_is_not_serving_but_is_not_idle_either() -> None:
    observation = _worker(reachable=False)
    assert observation.serving is False
    # The distinction that matters: unreachable is its own diagnosis, never
    # "nothing is running", because a probe that cannot connect proves nothing.
    assert observation.diagnose() == "worker_unreachable"


def test_a_pod_missing_from_the_provider_is_diagnosed_as_absent() -> None:
    assert _worker(provider_status=None).diagnose() == "worker_absent_from_provider"


def test_a_stopped_pod_is_diagnosed_as_exited() -> None:
    assert _worker(provider_status="EXITED").diagnose() == "worker_exited"


def test_a_reachable_pod_with_no_processes_and_work_left_is_idle() -> None:
    assert _worker(procs=0).diagnose() == "worker_idle_with_work_outstanding"


def test_a_finished_pod_needs_nothing_even_with_no_processes() -> None:
    finished = _worker(done=100, expected=100, procs=0)
    assert finished.diagnose() is None
    assert finished.serving is True


def _budget(max_replacements=4, ceiling=20.0) -> SupervisionBudget:
    return SupervisionBudget(
        max_replacements=max_replacements, spend_ceiling_usd=ceiling, hourly_rate_usd=1.0
    )


def test_recoverable_diagnoses_are_marked_for_acquisition() -> None:
    assert classify("worker_unreachable", _budget(), 1.0) == "recoverable"
    assert classify("worker_exited", _budget(), 1.0) == "recoverable"


def test_the_attempt_budget_stops_acquisition() -> None:
    budget = _budget(max_replacements=0)
    assert classify("worker_exited", budget, 1.0) == "attempt_budget_exhausted"


def test_the_spend_ceiling_stops_acquisition() -> None:
    budget = _budget(ceiling=1.0)
    assert classify("worker_exited", budget, 5.0) == "spend_ceiling_reached"


def test_a_deficit_with_recoverable_workers_asks_for_replacements() -> None:
    plan = plan_supervision(
        (_worker("w1"), _worker("w2", provider_status=None)),
        minimum_workers=2,
        budget=_budget(),
        replacement_hours=1.0,
    )
    assert plan["serving_worker_count"] == 1
    assert plan["capacity_deficit"] == 1
    assert plan["replacements_to_acquire"] == 1
    assert plan["should_stop"] is False


def test_a_full_fleet_asks_for_nothing() -> None:
    plan = plan_supervision(
        (_worker("w1"), _worker("w2")),
        minimum_workers=2,
        budget=_budget(),
        replacement_hours=1.0,
    )
    assert plan["capacity_deficit"] == 0
    assert plan["replacements_to_acquire"] == 0
    assert plan["should_stop"] is False


def test_a_blocked_budget_stops_rather_than_looping() -> None:
    plan = plan_supervision(
        (_worker("w1", provider_status=None),),
        minimum_workers=1,
        budget=_budget(max_replacements=0),
        replacement_hours=1.0,
    )
    assert plan["should_stop"] is True
    assert "attempt_budget_exhausted" in plan["blocked_reasons"]


def test_supervision_recovers_a_lost_worker_and_resumes() -> None:
    states = [
        (_worker("w1", done=10), _worker("w2", provider_status=None, done=0)),
        (_worker("w1", done=60), _worker("w2", done=40)),
        (_worker("w1", done=100, expected=100), _worker("w2", done=100, expected=100)),
    ]
    calls = {"acquire": 0, "resume": 0}

    def observe():
        return states.pop(0)

    def acquire(count):
        calls["acquire"] += count
        return count

    def resume():
        calls["resume"] += 1

    journal = SupervisionJournal()
    result = supervise(
        observe=observe, acquire=acquire, resume=resume,
        minimum_workers=2, budget=_budget(), replacement_hours=1.0,
        poll_seconds=0, max_cycles=5, journal=journal, sleep=lambda _: None,
    )
    assert result["outcome"] == "completed"
    assert calls["acquire"] == 1
    assert calls["resume"] == 1
    assert journal.counts()["acquired"] == 1


def test_supervision_stops_when_no_capacity_is_offered() -> None:
    def observe():
        return (_worker("w1", provider_status=None, done=0),)

    journal = SupervisionJournal()
    result = supervise(
        observe=observe, acquire=lambda _: 0, resume=lambda: None,
        minimum_workers=1, budget=_budget(), replacement_hours=1.0,
        poll_seconds=0, max_cycles=3, journal=journal, sleep=lambda _: None,
    )
    assert result["outcome"] == "stopped"
    assert any(e["action"] == "stopped" and "no_capacity_offered" in e["reasons"]
               for e in journal.entries)


def test_supervision_never_acquires_for_an_unrecoverable_condition() -> None:
    # An exhausted attempt budget must not be answered by acquiring anyway.
    def observe():
        return (_worker("w1", provider_status="EXITED", done=0),)

    calls = {"acquire": 0}

    def acquire(count):
        calls["acquire"] += count
        return count

    journal = SupervisionJournal()
    result = supervise(
        observe=observe, acquire=acquire, resume=lambda: None,
        minimum_workers=1, budget=_budget(max_replacements=0),
        replacement_hours=1.0, poll_seconds=0, max_cycles=3,
        journal=journal, sleep=lambda _: None,
    )
    assert result["outcome"] == "stopped"
    assert calls["acquire"] == 0


def test_the_receipt_records_what_was_done_and_refused() -> None:
    journal = SupervisionJournal()
    journal.record("observed", cycle=1, serving_worker_count=1)
    journal.record("acquired", cycle=1, requested=1, acquired=1)
    budget = _budget()
    budget.replacements_made = 1
    budget.spent_usd = 2.5
    receipt = build_receipt(
        {"outcome": "completed", "cycles": 2, "plan": {"capacity_deficit": 0}}, journal, budget
    )
    assert receipt["outcome"] == "completed"
    assert receipt["replacements_made"] == 1
    assert receipt["estimated_recovery_spend_usd"] == 2.5
    assert receipt["action_counts"]["acquired"] == 1
    assert receipt["receipt_sha256"].startswith("sha256:")
    assert receipt["score_inflation_allowed"] is False


def test_a_provider_wide_stop_is_named_rather_than_retried() -> None:
    # Every worker down at once is the shape of an exhausted account, not four
    # independent worker failures. Buying replacements cannot fix it.
    from supervise_recovery_campaign import detect_account_exhaustion

    fleet = (
        _worker("w1", provider_status="EXITED", done=10, procs=0),
        _worker("w2", provider_status="EXITED", done=20, procs=0),
    )
    assert detect_account_exhaustion(fleet) is True

    plan = plan_supervision(
        fleet, minimum_workers=2, budget=_budget(), replacement_hours=1.0
    )
    assert plan["should_stop"] is True
    assert plan["blocked_reasons"] == ["account_out_of_credit"]
    assert plan["replacements_to_acquire"] == 0


def test_one_lost_worker_is_not_mistaken_for_an_account_stop() -> None:
    from supervise_recovery_campaign import detect_account_exhaustion

    fleet = (_worker("w1"), _worker("w2", provider_status="EXITED", procs=0))
    assert detect_account_exhaustion(fleet) is False

    plan = plan_supervision(
        fleet, minimum_workers=2, budget=_budget(), replacement_hours=1.0
    )
    assert plan["replacements_to_acquire"] == 1
    assert plan["should_stop"] is False


def test_a_finished_fleet_is_not_an_account_stop() -> None:
    from supervise_recovery_campaign import detect_account_exhaustion

    fleet = (
        _worker("w1", provider_status="EXITED", done=100, expected=100, procs=0),
        _worker("w2", provider_status="EXITED", done=100, expected=100, procs=0),
    )
    assert detect_account_exhaustion(fleet) is False


def test_the_supervisor_stops_on_an_account_stop_without_acquiring() -> None:
    calls = {"acquire": 0}

    def observe():
        return (
            _worker("w1", provider_status="EXITED", done=5, procs=0),
            _worker("w2", provider_status="EXITED", done=5, procs=0),
        )

    journal = SupervisionJournal()
    result = supervise(
        observe=observe,
        acquire=lambda n: calls.__setitem__("acquire", calls["acquire"] + n) or n,
        resume=lambda: None,
        minimum_workers=2, budget=_budget(), replacement_hours=1.0,
        poll_seconds=0, max_cycles=3, journal=journal, sleep=lambda _: None,
    )
    assert result["outcome"] == "stopped"
    assert calls["acquire"] == 0
    assert any("account_out_of_credit" in e.get("reasons", []) for e in journal.entries)
